import json
import hashlib
import os
import secrets
import sys
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, urlsplit, parse_qs
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
from core import normalize, validate_settings, due_lesson
from browsers import browser_info, launch_options as browser_launch_options
from settings_store import load_settings, save_settings, atomic_write
from managed_panel import ManagedPanel
from windows_startup import status as windows_startup_status
from schedule_sources import official_schedule, official_group, official_groups
import updater

RESOURCES = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
BASE = Path(os.environ.get('LECTURE_PILOT_DATA_DIR') or ((Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'LecturePilot') if os.name == 'nt' else Path(__file__).resolve().parent / 'local-data'))
BASE.mkdir(parents=True, exist_ok=True)
MOSCOW = ZoneInfo('Europe/Moscow')
TOKEN = secrets.token_urlsafe(32)
DEFAULTS = {'group': '', 'name': '', 'lead': 0, 'muted': True, 'focus_mode': True, 'excluded': [], 'autostart': True, 'consent_accepted': False, 'browser': 'default', 'windows_startup_enabled': False}
LOCK = threading.RLock()
WAKE = threading.Event()
QUIT = threading.Event()
REFRESH_LOCK = threading.Lock()
settings, settings_warning = load_settings(BASE, DEFAULTS, validate_settings)
def load_theme():
    try:
        value=json.loads((BASE/'appearance.json').read_text(encoding='utf-8')).get('theme')
        return value if value in ('light','dark') else 'light'
    except (OSError,ValueError,AttributeError): return 'light'

state = {'settings': settings, 'theme': load_theme(), 'update_status': 'Проверка обновлений ещё не выполнялась', 'update_available': None, 'update_busy': False, 'lessons': [], 'armed': False, 'active': None, 'opened': [],
         'opened_intervals': [], 'refreshing': False, 'updated': None, 'error': '', 'message': 'Выбери группу и сохрани имя для входа', 'signal': None, 'engine_ready': False, 'audio_applied': None,
         'resume_pending': bool(settings.get('autostart') and settings.get('consent_accepted')),
         'fetch_ok': False, 'source': None, 'coverage_until': None, 'source_review': False, 'source_note': '', 'started_at': datetime.now(MOSCOW).isoformat(), 'launch_mode': 'windows' if '--background' in sys.argv else 'manual',
         'settings_warning': settings_warning}
if state['resume_pending']:
    state['message'] = 'Восстанавливаем автовход · загружаем расписание'
logs = deque(maxlen=100)
OPEN_PANEL=threading.Event()
FOCUS_NATIVE=threading.Event()
PANEL_URL=None


def now():
    return datetime.now(MOSCOW)


def log(message):
    with LOCK:
        record={'time':now().strftime('%H:%M:%S'),'at':now().isoformat(),'message':message}
        logs.appendleft(record)
        try:
            target=BASE/'startup-events.jsonl'
            if target.exists() and target.stat().st_size>512000:
                old=BASE/'startup-events.previous.jsonl'
                old.unlink(missing_ok=True)
                target.replace(old)
            with target.open('a',encoding='utf-8') as stream:
                stream.write(json.dumps(record,ensure_ascii=False)+'\n')
        except OSError:
            pass


def persist():
    with LOCK:
        save_settings(BASE,state['settings'])


def restore_logs():
    try:
        rows=(BASE/'startup-events.jsonl').read_text(encoding='utf-8').splitlines()[-100:]
        for row in rows:
            try:
                item=json.loads(row)
                if isinstance(item,dict) and isinstance(item.get('message'),str) and isinstance(item.get('time'),str):
                    logs.appendleft(item)
            except ValueError:pass
    except OSError:pass


def snapshot():
    with LOCK:
        return json.loads(json.dumps({**state, 'logs': list(logs), 'now': now().isoformat(), 'browser_info': browser_info(state['settings'].get('browser', 'default')), 'startup': windows_startup_status()}, ensure_ascii=False))


def maybe_resume():
    with LOCK:
        if not state['resume_pending'] or not state['engine_ready'] or not state['updated'] or state.get('source_review') or (state.get('coverage_until') and now().date().isoformat() > state['coverage_until']):
            return False
        if (now() - datetime.fromisoformat(state['updated'])).total_seconds() > 1200:
            return False
        try:
            validate_settings(state['settings'])
        except ValueError as error:
            state['resume_pending']=False
            state['message']='Не удалось восстановить автовход · проверь профиль'
            state['error']=str(error)
            return False
        try:
            browser_launch_options(state['settings'].get('browser','default'))
        except ValueError as error:
            # Browser files / default handler may not be ready immediately after logon.
            state['message']='Ожидаем готовности браузера · автовход сохранён'
            state['error']=str(error)
            return False
        if not (state['settings'].get('autostart') and state['settings'].get('consent_accepted')):
            state['resume_pending'] = False
            return False
        state.update(armed=True, resume_pending=False, error='', message='Автовход восстановлен автоматически')
    log('Сохранённый автовход восстановлен. Повторное нажатие кнопки не требуется.')
    WAKE.set()
    return True


def refresh():
    if not REFRESH_LOCK.acquire(blocking=False):
        return
    with LOCK:
        state['refreshing'] = True
        group = state['settings']['group']
    try:
        if not group:
            return
        today = now().date()
        url = 'https://mosrasp.ru/api/groups/{}/timeline?from={}&to={}'.format(quote(group, safe=''), today, today + timedelta(days=13))
        req = Request(url, headers={'User-Agent': 'LecturePilot/1.7 (personal schedule client)'})
        source='mosrasp.ru'; coverage=today+timedelta(days=13); note=''
        try:
            with urlopen(req, timeout=12) as response:
                raw = response.read(5_000_001)
            if len(raw) > 5_000_000: raise ValueError('Ответ расписания слишком большой.')
            lessons = normalize(json.loads(raw), group)
        except Exception as primary_error:
            try:
                lessons, coverage = official_schedule(group,today,opener=urlopen)
                source='rasp.dmami.ru'
                if coverage < today+timedelta(days=13):
                    note='Официальное расписание опубликовано только до '+coverage.strftime('%d.%m.%Y')+'. Дальнейшие даты не подтверждены.'
            except Exception as backup_error:
                raise ValueError('Оба источника недоступны или не содержат актуальное расписание. mosrasp: '+str(primary_error)[:100]+'; rasp.dmami: '+str(backup_error)[:120]) from backup_error
        with LOCK:
            if group != state['settings']['group']:
                return
            previous=state.get('source')
            switching=bool(previous and previous != source)
            if switching and state.get('active'):
                state.update(fetch_ok=False, source_note='Найден другой источник. Переключение отложено до окончания текущего занятия.')
                return
            # IDs and exclusions differ across providers; never silently disregard the student's choices.
            excluded=state['settings'].get('excluded',[])
            review = switching or (not previous and any((str(x).startswith('official:')) != (source=='rasp.dmami.ru') for x in excluded))
            if review:
                state.update(armed=False, resume_pending=False, source_review=True)
            if review or state.get('source_review'):
                note='Источник изменился. Проверь выбор занятий и снова запусти автовход. '+note
            state.update(lessons=lessons, updated=now().isoformat(), error='', fetch_ok=True, source=source, coverage_until=coverage.isoformat(), source_note=note)
        if review: log('Источник изменился: проверь выбор занятий и снова запусти автовход.')
        maybe_resume()
        log('Расписание обновлено: '+source+' · '+str(sum(x['eligible'] for x in lessons))+' вебинаров.')
    except Exception as error:
        with LOCK:
            state['fetch_ok'] = False
            state['error'] = 'Не удалось обновить расписание: ' + str(error)[:200]
        log('Ошибка загрузки расписания. Старые данные не заменены.')
    finally:
        with LOCK:
            state['refreshing'] = False
            group_changed = group != state['settings']['group']
        REFRESH_LOCK.release()
        if group_changed:
            threading.Thread(target=refresh, daemon=True).start()
        WAKE.set()


def refresh_delay():
    with LOCK:
        return 15 if state['settings']['group'] and not state.get('fetch_ok') else 300


def refreshing_loop():
    while not QUIT.is_set():
        refresh()
        QUIT.wait(refresh_delay())


def lesson_slot(lesson):
    return (datetime.fromisoformat(lesson['start']).timestamp(), datetime.fromisoformat(lesson['end']).timestamp())



UPDATE_DATA=None

def check_update():
    global UPDATE_DATA
    with LOCK:
        if state.get('update_busy'): return
        state.update(update_busy=True,update_status='Проверяем обновления…')
    try:
        meta,raw,sig=updater.check_latest()
        with LOCK:
            if updater.version_tuple(meta['version'])>updater.version_tuple(updater.VERSION):
                UPDATE_DATA=(meta,raw,sig);state.update(update_available=meta['version'],update_status='Доступна версия '+meta['version'])
            else:
                UPDATE_DATA=None;state.update(update_available=None,update_status='Установлена последняя версия '+updater.VERSION)
    except Exception:
        UPDATE_DATA=None
        with LOCK:state.update(update_available=None,update_status='Не удалось проверить обновления. Попробуй позже.')
    finally:
        with LOCK:state['update_busy']=False

def update_loop():
    while not QUIT.is_set():
        check_update()
        QUIT.wait(21600)

def install_update(server):
    with LOCK:
        if state.get('update_busy'):raise ValueError('Обновление уже выполняется')
        if state.get('active'):raise ValueError('Сначала дождись окончания занятия')
        if not UPDATE_DATA:raise ValueError('Сначала проверь обновления')
        if os.name!='nt' or not getattr(sys,'frozen',False):raise ValueError('Обновление доступно только в собранном EXE для Windows')
        state.update(update_busy=True,update_status='Загружаем и проверяем обновление…')
        data=UPDATE_DATA
    def task():
        candidate=None
        try:
            meta,raw,sig=data
            candidate=updater.download_update(meta,raw,sig,BASE/'updates')
            with LOCK:
                if state.get('active'):raise ValueError('Началось занятие; обновление отложено')
                updater.prepare_helper(sys.executable,candidate,raw,sig)
                state.update(update_status='Обновление проверено, приложение перезапускается')
                request_shutdown(server)
        except Exception as error:
            if candidate:candidate.unlink(missing_ok=True)
            with LOCK:state.update(update_busy=False,update_status='Не удалось установить обновление: '+str(error)[:160])
            log('Обновление не установлено: '+str(error)[:120])
    threading.Thread(target=task,daemon=True).start()

def clean_old_helper():
    if os.name!='nt' or not getattr(sys,'frozen',False):return
    helper=Path(sys.executable).with_name('LecturePilot-update-helper.exe')
    payload=Path(sys.executable).with_name('LecturePilot-update-payload.json')
    # The helper exits shortly after it starts this process. Never remove a live payload.
    for _ in range(30):
        if payload.exists():
            time.sleep(1);continue
        try:helper.unlink(missing_ok=True);return
        except OSError:time.sleep(1)

def is_armed():
    with LOCK:
        return state['armed'] and not QUIT.is_set()


def apply_tab_audio(page, muted):
    applied = 0
    for frame in getattr(page, 'frames', []):
        try:
            result = frame.evaluate("(value) => { if (typeof globalThis.__lecturePilotSetMuted !== 'function') return false; globalThis.__lecturePilotSetMuted(value); return true; }", muted)
            applied += bool(result)
        except Exception:
            pass
    if applied:
        with LOCK:
            state['audio_applied'] = {'muted': muted, 'frames': applied}


def browser_loop():
    # Every Playwright object belongs to this worker thread only.
    from playwright.sync_api import sync_playwright
    import re
    context = None
    page = None
    active = None
    last_resume_attempt = 0
    panel = None
    try:
        with sync_playwright() as p:
            panel=ManagedPanel(p.chromium,BASE,browser_launch_options)
            with LOCK:
                state['engine_ready'] = True
            maybe_resume()
            while not QUIT.is_set():
                if OPEN_PANEL.is_set():
                    OPEN_PANEL.clear()
                    try:
                        with LOCK:selection=state['settings'].get('browser','default')
                        panel.open(PANEL_URL,selection)
                        log('Открыта панель Lecture Pilot by pik1 в отдельном профиле браузера.')
                    except Exception as error:
                        with LOCK:state['error']='Не удалось открыть панель: '+str(error).splitlines()[0][:180]
                        log('Не удалось открыть панель: '+str(error).splitlines()[0][:180])
                panel.pump()
                snap = snapshot()
                if snap['resume_pending'] and time.monotonic() - last_resume_attempt >= 15:
                    last_resume_attempt = time.monotonic()
                    maybe_resume()
                    snap = snapshot()
                if not snap['armed']:
                    if context:
                        try:
                            context.close()
                        except Exception:
                            pass
                        context = page = active = None
                        with LOCK:
                            state.update(active=None, signal=None, audio_applied=None, message='Автовход выключен')
                    WAKE.wait(0.5)
                    WAKE.clear()
                    continue
                if not snap['updated'] or (now() - datetime.fromisoformat(snap['updated'])).total_seconds() > 1200 or (snap.get('coverage_until') and now().date().isoformat() > snap['coverage_until']):
                    with LOCK:
                        state.update(armed=False, resume_pending=bool(state['settings'].get('autostart') and state['settings'].get('consent_accepted')), message='Нет свежего расписания · ждём восстановления связи')
                    log('Автовход остановлен: нет свежего расписания более 20 минут.')
                    continue
                if active:
                    if page.is_closed():
                        with LOCK:
                            state.update(armed=False, message='Остановлено: окно вебинара закрыто')
                        log('Окно вебинара закрыто вручную — автовход остановлен.')
                        continue
                    # Reconcile early endings / cancellations after refreshing the timetable.
                    current = next((x for x in snap['lessons'] if x['id'] == active['id']), None)
                    if current is None or now() >= datetime.fromisoformat(current['end']):
                        if len(context.pages) <= 1:
                            context.new_page()
                        page.close()
                        log('Окно занятия закрыто по расписанию: ' + active['subject'])
                        page = active = None
                        with LOCK:
                            state.update(active=None, signal=None, audio_applied=None, message='Ожидание следующего вебинара')
                if active:
                    apply_tab_audio(page, bool(snap['settings']['muted']))
                    page.wait_for_timeout(400)
                    continue
                seen_slots={tuple(x) for x in snap.get('opened_intervals',[])}
                candidates=[x for x in snap['lessons'] if lesson_slot(x) not in seen_slots]
                lesson = due_lesson(candidates, snap['settings'], set(snap['opened']), now())
                if not lesson:
                    with LOCK:
                        state['message'] = 'Расписание включено · ожидание вебинара'
                    if context and context.pages:
                        context.pages[0].wait_for_timeout(500)
                    else:
                        WAKE.wait(0.5)
                        WAKE.clear()
                    continue
                try:
                    if context is None:
                        args = ['--disable-background-timer-throttling', '--disable-renderer-backgrounding', '--disable-backgrounding-occluded-windows']
                        browser_options = browser_launch_options(snap['settings'].get('browser', 'default'))
                        profile_id = hashlib.sha256(str(browser_options).lower().encode()).hexdigest()[:12]
                        profile_dir = BASE / 'browser-profiles' / profile_id
                        context = p.chromium.launch_persistent_context(str(profile_dir), headless=False, no_viewport=True, args=args, **browser_options)
                        if snap['settings']['focus_mode']:
                            context.add_init_script(path=str(RESOURCES / 'visibility.js'))
                    if not is_armed():
                        continue
                    page = context.new_page()
                    audio_script = (RESOURCES / 'tab_audio.js').read_text(encoding='utf-8')
                    page.add_init_script(script=audio_script + '\n;globalThis.__lecturePilotSetMuted(' + json.dumps(bool(snap['settings']['muted'])) + ');')
                    # Keep the initial blank tab: it keeps Chrome alive between lessons.
                    def on_request(request):
                        if urlsplit(request.url).path.endswith('/setUserInvolvementStatus'):
                            from urllib.parse import parse_qs
                            try:
                                data = parse_qs(request.post_data or '')
                                values = {k: data[k][-1] for k in ('isFocused', 'isSoundEnabled', 'isVideoEnabled') if k in data}
                                if values:
                                    with LOCK:
                                        state['signal'] = {'at': now().strftime('%H:%M:%S'), 'values': values}
                            except Exception:
                                pass
                    page.on('request', on_request)
                    with LOCK:
                        state['message'] = 'Открываем: ' + lesson['subject']
                        state['signal'] = None
                    page.goto(lesson['url'], wait_until='domcontentloaded', timeout=30000)
                    if not is_armed():
                        continue
                    active = lesson
                    with LOCK:
                        state['opened'].append(lesson['id'])
                        state['opened_intervals'].append(list(lesson_slot(lesson)))
                        state['active'] = {**lesson, 'status': 'Окно открыто · вход нужно проверить'}
                    log('Открыт вебинар: ' + lesson['subject'])
                    # Retry only visible name inputs / explicit join buttons, not presence checks.
                    deadline = time.monotonic() + 35
                    full_name = snap['settings']['group'] + ' ' + snap['settings']['name']
                    name_filled = False
                    clicks = 0
                    last_click = 0
                    join = re.compile(r'^(?:Войти|Присоединиться|Подключиться|Участвовать|Войти в вебинар|Присоединиться к вебинару|Join|Join event|Enter)$', re.I)
                    while time.monotonic() < deadline and is_armed() and not page.is_closed():
                        if not name_filled:
                            fields = page.get_by_role('textbox', name=re.compile(r'имя|your name|name', re.I))
                            for field in fields.all():
                                if field.is_visible() and field.is_editable():
                                    field.fill(full_name, timeout=2000)
                                    name_filled = True
                                    break
                        if clicks < 2 and time.monotonic() - last_click > 5:
                            for button in page.get_by_role('button', name=join).all():
                                if button.is_visible() and button.is_enabled():
                                    button.click(timeout=3000)
                                    clicks += 1
                                    last_click = time.monotonic()
                                    break
                        with LOCK:
                            lecture_muted = bool(state['settings']['muted'])
                        apply_tab_audio(page, lecture_muted)
                        page.wait_for_timeout(500)
                    with LOCK:
                        state['message'] = 'Окно открыто · проверь, завершён ли вход'
                    log('Автонажатия завершены. Авторизацию, если нужна, выполни вручную.')
                except Exception as error:
                    with LOCK:
                        state.update(armed=False, message='Автовход остановлен из-за ошибки')
                    log('Ошибка браузера: ' + str(error).splitlines()[0][:250])
            if context:
                try:context.close()
                except Exception:pass
                context=None
            if panel:panel.close()
    except Exception as error:
        with LOCK:
            state.update(armed=False, error='Браузерный модуль недоступен: ' + str(error)[:180])
        log('Ошибка браузерного модуля. Перезапусти приложение после установки зависимостей.')
    finally:
        with LOCK:
            state.update(armed=False, active=None, engine_ready=False)
        if context:
            try:
                context.close()
            except Exception:
                pass


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, code, data, content_type='application/json; charset=utf-8'):
        if isinstance(data, (dict, list)):
            data = json.dumps(data, ensure_ascii=False).encode('utf-8')
        elif isinstance(data, str):
            data = data.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.end_headers()
        self.wfile.write(data)

    def valid_host(self):
        return self.headers.get('Host') == '127.0.0.1:' + str(self.server.server_port)

    def authorized(self):
        return self.valid_host() and secrets.compare_digest(self.headers.get('X-App-Token', ''), TOKEN)

    def do_GET(self):
        if not self.valid_host():
            self.respond(403, {'error': 'Invalid host'})
        elif self.path == '/':
            text = (RESOURCES / 'index.html').read_text(encoding='utf-8').replace('__APP_TOKEN__', TOKEN)
            self.respond(200, text, 'text/html; charset=utf-8')
        elif self.path in ('/app-icon.png', '/app-icon.ico', '/app-icon.svg', '/app-icon-dark.png', '/app-icon-dark.ico', '/app-icon-dark.svg'):
            icon = RESOURCES / self.path.lstrip('/')
            self.respond(200, icon.read_bytes(), 'image/png' if self.path.endswith('.png') else 'image/svg+xml' if self.path.endswith('.svg') else 'image/x-icon')
        elif urlsplit(self.path).path == '/api/groups' and self.authorized():
            try:
                query = parse_qs(urlsplit(self.path).query).get('q', [''])[0].strip()
                if len(query) < 2:
                    self.respond(200, {'groups': []})
                    return
                if len(query) > 30:
                    raise ValueError('Слишком длинный запрос.')
                try:
                    with urlopen('https://mosrasp.ru/api/search?q=' + quote(query, safe=''), timeout=7) as response:
                        data = json.loads(response.read(1000000))
                    names = [str(x['name']) for x in data.get('groups', []) if isinstance(x, dict) and x.get('name')]
                    if not names: names=official_groups(query,opener=urlopen)
                except Exception:
                    names=official_groups(query,opener=urlopen)
                self.respond(200, {'groups': names})
            except Exception:
                self.respond(502, {'error': 'Подсказки недоступны. Можно ввести полный номер группы вручную.'})
        elif self.path == '/api/state' and self.authorized():
            self.respond(200, snapshot())
        else:
            self.respond(404, {'error': 'Not found'})

    def do_POST(self):
        if not self.authorized():
            self.respond(403, {'error': 'Доступ запрещён'})
            return
        origin = self.headers.get('Origin')
        if origin and origin != 'http://127.0.0.1:' + str(self.server.server_port):
            self.respond(403, {'error': 'Доступ запрещён'})
            return
        try:
            size = int(self.headers.get('Content-Length', 0))
            if size > 100000 or size < 0:
                raise ValueError('Слишком большой запрос')
            data = json.loads(self.rfile.read(size) or b'{}')
            if self.path == '/api/update-check':
                threading.Thread(target=check_update,daemon=True).start()
            elif self.path == '/api/update-install':
                install_update(self.server)
            elif self.path == '/api/theme':
                theme=data.get('theme')
                if theme not in ('light','dark'): raise ValueError('Неизвестная тема оформления.')
                with LOCK:
                    atomic_write(BASE/'appearance.json',json.dumps({'theme':theme}))
                    state['theme']=theme
                threading.Thread(target=sync_shortcut_icons,daemon=True).start()
            elif self.path == '/api/open-panel':
                FOCUS_NATIVE.set()
                OPEN_PANEL.set()
                WAKE.set()
            elif self.path == '/api/shortcuts':
                from windows_shortcuts import create
                with SHORTCUT_LOCK:
                    with LOCK:theme=state.get('theme','light')
                    create(RESOURCES,BASE,theme,updater.VERSION)
                log('Созданы ярлыки Lecture Pilot by pik1 на рабочем столе и в меню «Пуск».')
            elif self.path == '/api/save':
                clean = validate_settings(data)
                with LOCK:
                    must_check_group = clean['group'] != state['settings']['group']
                if must_check_group:
                    try:
                        with urlopen('https://mosrasp.ru/api/groups/' + quote(clean['group'], safe=''), timeout=7) as response:
                            card = json.loads(response.read(1000000))
                        if not isinstance(card, dict) or card.get('name') != clean['group']:
                            raise ValueError('Группа не найдена')
                    except Exception:
                        official_group(clean['group'],0,opener=urlopen)
                with LOCK:
                    if state['armed'] or state['active']:
                        raise ValueError('Сначала останови автовход и дождись закрытия окна вебинара.')
                    changed = clean['group'] != state['settings']['group']
                    identity_changed = changed or clean['name'] != state['settings']['name']
                    clean['consent_accepted'] = bool(state['settings'].get('consent_accepted')) and not identity_changed
                    clean['windows_startup_enabled'] = bool(state['settings'].get('windows_startup_enabled'))
                    state['settings'] = clean
                    state['resume_pending'] = False
                    persist()
                    if changed:
                        state.update(lessons=[], updated=None, opened=[], opened_intervals=[], signal=None, source=None, coverage_until=None, source_review=False)
                log('Настройки сохранены.')
                threading.Thread(target=refresh, daemon=True).start()
            elif self.path == '/api/refresh':
                threading.Thread(target=refresh, daemon=True).start()
            elif self.path == '/api/start':
                with LOCK:
                    saved_consent=state['settings'].get('consent_accepted',False)
                if data.get('consent') is not True and not (data.get('use_saved_consent') is True and saved_consent):
                    raise ValueError('Подтверди условия автоматического входа.')
                with LOCK:
                    validate_settings(state['settings'])
                    browser_launch_options(state['settings'].get('browser', 'default'))
                    if state['armed']:
                        raise ValueError('Автовход уже включён.')
                    if not state['engine_ready']:
                        raise ValueError('Браузерный модуль ещё не готов. Перезапусти приложение, если ошибка сохраняется.')
                    if not state['updated'] or (now() - datetime.fromisoformat(state['updated'])).total_seconds() > 1200 or (state.get('coverage_until') and now().date().isoformat() > state['coverage_until']):
                        raise ValueError('Сначала загрузи свежее расписание.')
                    if state.get('source_review') and data.get('source_review_confirmed') is not True:
                        raise ValueError('Проверь выбор занятий после смены источника.')
                    state['source_review'] = False
                    state['source_note'] = state.get('source_note','').replace('Источник изменился. Проверь выбор занятий и снова запусти автовход. ', '')
                    state['settings']['consent_accepted'] = True
                    persist()
                    state.update(armed=True, resume_pending=False, message='Автовход включён')
                log('Автовход включён. Возможен вход на уже начавшееся занятие до его окончания.')
                WAKE.set()
            elif self.path == '/api/stop':
                with LOCK:
                    # Pause this process only. Persisted auto-resume is a separate setting.
                    state['resume_pending'] = False
                    persist()
                    state.update(armed=False, message='Пауза · закрываем окно вебинара')
                WAKE.set()
                log('Пауза текущей работы. Сохранённый автовход не изменён.')
            elif self.path == '/api/audio':
                with LOCK:
                    if not state['active']:
                        raise ValueError('Сначала открой лекцию через приложение.')
                    if not isinstance(data.get('muted'), bool):
                        raise ValueError('Некорректный режим звука.')
                    state['settings']['muted'] = data['muted']
                    persist()
                log('Запрошено ' + ('отключение' if data['muted'] else 'включение') + ' звука только вкладки лекции.')
                WAKE.set()
            elif self.path in ('/api/startup-enable', '/api/startup-disable'):
                from windows_startup import configure
                removing=self.path.endswith('disable')
                result=configure(BASE, remove=removing)
                with LOCK:
                    state['settings']['windows_startup_enabled']=not removing
                    persist()
                if result.get('disabled_by_windows'):
                    log('Запись создана, но Windows отключила её. Включи LecturePilot в параметрах автозагрузки Windows.')
                log('Автозагрузка Windows отключена.' if removing else 'Запись автозагрузки Windows сохранена и проверена.' if not result.get('disabled_by_windows') else 'Ожидается разрешение автозагрузки в параметрах Windows.')
            elif self.path == '/api/shutdown':
                request_shutdown(self.server)
            else:
                self.respond(404, {'error': 'Not found'})
                return
            self.respond(200, {'ok': True})
        except Exception as error:
            self.respond(400, {'error': str(error)[:300]})


def instance_lock():
    handle = open(BASE / 'instance.lock', 'a+b')
    handle.seek(0)
    if not handle.read(1):
        handle.write(b'0')
        handle.flush()
    handle.seek(0)
    try:
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def request_shutdown(server):
    with LOCK:
        if QUIT.is_set():return
        state['armed']=False
        log('Завершение Lecture Pilot by pik1: закрываем только окна программы.')
        QUIT.set()
        WAKE.set()
    threading.Thread(target=server.shutdown,daemon=True).start()


SHORTCUT_LOCK = threading.Lock()
def sync_shortcut_icons():
    if os.name != 'nt':return
    try:
        from windows_shortcuts import update_existing
        with SHORTCUT_LOCK:
            with LOCK:theme=state.get('theme','light')
            update_existing(RESOURCES,BASE,theme,updater.VERSION)
    except Exception as error:log('Не удалось обновить значок ярлыка: '+str(error)[:160])

def notify_existing(url):
    import re
    parsed=urlsplit(url)
    if parsed.scheme!='http' or parsed.hostname!='127.0.0.1' or parsed.path not in ('','/'):
        raise ValueError('Invalid local URL')
    html=urlopen(url,timeout=3).read(500000).decode('utf-8')
    match=re.search(r"const TOKEN='([^']+)'",html)
    if not match:raise ValueError('Existing app did not provide a token')
    request=Request(url.rstrip('/')+'/api/open-panel',data=b'{}',headers={'X-App-Token':match[1],'Content-Type':'application/json'})
    with urlopen(request,timeout=3) as response:
        if not json.load(response).get('ok'):raise ValueError('Could not activate existing app')


def main():
    global PANEL_URL
    guard = instance_lock()
    if guard is None:
        if '--background' not in sys.argv:
            try:notify_existing(json.loads((BASE/'runtime.json').read_text())['url'])
            except Exception as error:
                if os.name=='nt':
                    import ctypes
                    ctypes.windll.user32.MessageBoxW(None,'Приложение уже запущено. Открой его окно на панели задач.','Lecture Pilot by pik1',64)
                else:print('Already running:',str(error)[:150])
        return
    restore_logs()
    log('Запуск Lecture Pilot by pik1: ' + ('автозагрузка Windows / фоновый запуск' if '--background' in sys.argv else 'ручной запуск') + '. Автовход ' + ('сохранён.' if state['resume_pending'] else 'не был сохранён или не подтверждён.'))
    if settings_warning:log(settings_warning)
    startup_info=windows_startup_status()
    if startup_info.get('registered') and not startup_info.get('path_matches') and not startup_info.get('disabled_by_windows') and state['settings'].get('consent_accepted'):
        try:
            from windows_startup import configure
            configure(BASE)
            log('Обновлён путь ранее разрешённого автозапуска на текущий файл приложения.')
        except Exception as error:log('Не удалось обновить путь автозапуска: '+str(error)[:180])
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    PANEL_URL='http://127.0.0.1:'+str(server.server_port)
    (BASE/'runtime.json').write_text(json.dumps({'url':PANEL_URL}),encoding='utf-8')
    serving=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.25},daemon=True)
    serving.start()
    worker=threading.Thread(target=browser_loop,daemon=True)
    worker.start()
    threading.Thread(target=refreshing_loop,daemon=True).start()
    threading.Thread(target=clean_old_helper,daemon=True).start()
    threading.Thread(target=update_loop,daemon=True).start()
    threading.Thread(target=sync_shortcut_icons,daemon=True).start()
    print('Lecture Pilot by pik1 — '+PANEL_URL,flush=True)
    if os.environ.get('LECTURE_PILOT_NO_OPEN')!='1' and '--background' not in sys.argv:
        OPEN_PANEL.set();WAKE.set()
    try:
        if os.name=='nt':
            from native_window import run
            def status():
                with LOCK:return state['error'] or state['message']
            def focus_requested():
                if FOCUS_NATIVE.is_set():FOCUS_NATIVE.clear();return True
                return False
            def open_panel():OPEN_PANEL.set();WAKE.set()
            run(RESOURCES,status,open_panel,lambda:request_shutdown(server),lambda:QUIT.is_set() and not worker.is_alive(),focus_requested,background='--background' in sys.argv,theme=lambda:state.get('theme','light'))
        else:
            while not QUIT.wait(.5):pass
    except KeyboardInterrupt:pass
    finally:
        request_shutdown(server)
        worker.join(timeout=40)
        serving.join(timeout=5)
        server.server_close()
        (BASE/'runtime.json').unlink(missing_ok=True)
        guard.close()

if __name__ == '__main__':
    try:
        if len(sys.argv)==3 and sys.argv[1]=='--apply-update':
            try:updater.run_helper(sys.argv[2])
            except Exception:
                payload=Path(sys.argv[2]).resolve()
                if payload.name=='LecturePilot-update-payload.json' and payload.parent==Path(sys.executable).resolve().parent:
                    payload.unlink(missing_ok=True)
                raise
        else:main()
    except Exception as error:
        if os.name == 'nt' and getattr(sys, 'frozen', False):
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, str(error)[:600], 'Lecture Pilot by pik1 — ошибка запуска', 16)
        else:
            raise
