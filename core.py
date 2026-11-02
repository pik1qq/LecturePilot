import re
from datetime import datetime, timezone
from urllib.parse import urlparse

UTC = timezone.utc

def is_webinar_url(url):
    try:
        p = urlparse(url)
        h = (p.hostname or '').lower()
        return p.scheme == 'https' and not p.username and not p.password and p.port in (None, 443) and any(h == root or h.endswith('.' + root) for root in ('mts-link.ru', 'webinar.ru'))
    except (ValueError, TypeError):
        return False

def validate_settings(data):
    group = str(data.get('group', '')).strip()
    name = ' '.join(str(data.get('name', '')).split())
    if not re.fullmatch(r'[0-9A-Za-zА-Яа-яЁё_-]{2,30}', group):
        raise ValueError('Проверь номер группы, например 000-000.')
    if not name or len(name) > 100:
        raise ValueError('Введи фамилию и имя — до 100 символов.')
    lead = int(data.get('lead', 0))
    if lead not in range(6):
        raise ValueError('Ранний вход: от 0 до 5 минут.')
    excluded = data.get('excluded', [])
    if not isinstance(excluded, list) or len(excluded) > 1000 or not all(isinstance(x, str) for x in excluded):
        raise ValueError('Некорректный список исключений.')
    browser = str(data.get('browser', 'default'))
    if browser not in ('default', 'chrome', 'edge', 'yandex'):
        raise ValueError('Неизвестный браузер.')
    return {'browser': browser, 'group': group, 'name': name, 'lead': lead, 'muted': bool(data.get('muted', True)),
            'focus_mode': bool(data.get('focus_mode', True)), 'excluded': excluded,
            'autostart': bool(data.get('autostart', True)),
            'consent_accepted': bool(data.get('consent_accepted', False)),
            'windows_startup_enabled': bool(data.get('windows_startup_enabled', False))}

def normalize(data, group):
    if not isinstance(data, dict) or not isinstance(data.get('days'), list):
        raise ValueError('Неожиданный формат расписания mosrasp.')
    lessons = []
    seen = set()
    for day in data['days']:
        for item in day.get('items', []):
            if item.get('type') != 'lesson':
                continue
            start, end = datetime.fromisoformat(item['start']), datetime.fromisoformat(item['end'])
            if start.tzinfo is None or end.tzinfo is None or end <= start:
                raise ValueError('В расписании некорректное время занятия.')
            uid = str(item['uid'])
            if uid in seen:
                continue
            seen.add(uid)
            links = [x.get('url', '') for x in item.get('links', [])
                     if (not x.get('groups') or group in x['groups']) and is_webinar_url(x.get('url', ''))]
            # Never guess a URL, or select arbitrarily when several are supplied.
            url = links[0] if len(set(links)) == 1 else None
            online = bool(item.get('is_online'))
            fmt = item.get('online_format')
            reason = '' if url else ('Несколько ссылок — нужен ручной выбор' if len(set(links)) > 1 else
                     'Ссылка ещё не опубликована' if online and fmt == 'webinar' else
                     'Онлайн-курс — не вебинар' if online else 'Очное занятие')
            lessons.append({'id': uid, 'start': start.isoformat(), 'end': end.isoformat(),
                            'subject': str(item.get('subject', 'Занятие')), 'kind': str(item.get('kind', '')),
                            'teacher': ', '.join(x.get('name', '') for x in item.get('teachers', [])),
                            'subgroup': item.get('subgroup'), 'url': url, 'eligible': bool(url), 'reason': reason})
    return sorted(lessons, key=lambda x: (x['start'], x['id']))

def due_lesson(lessons, settings, opened, now):
    from datetime import timedelta
    for lesson in lessons:
        if not lesson['eligible'] or lesson['id'] in settings['excluded'] or lesson['id'] in opened:
            continue
        start, end = datetime.fromisoformat(lesson['start']), datetime.fromisoformat(lesson['end'])
        if start - timedelta(minutes=settings['lead']) <= now < end:
            return lesson
    return None
