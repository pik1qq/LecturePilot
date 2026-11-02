"""Explicit, per-user Windows logon registration. Never changes StartupApproved."""
import json
import os
import re
import sys
from pathlib import Path

RUN_KEY=r'Software\Microsoft\Windows\CurrentVersion\Run'
APPROVED_KEY=r'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run'
VALUE_NAME='LecturePilot'


def _registry():
    if sys.platform!='win32':raise ValueError('Автозагрузка доступна только в Windows.')
    import winreg
    return winreg


def command_for(target, script=None):
    target=str(target)
    if '"' in target or (script is not None and '"' in str(script)):
        raise ValueError('Недопустимые кавычки в пути приложения.')
    cmd='"'+target+'"'+(' "'+str(script)+'"' if script is not None else '')+' --background'
    if len(cmd)>260:
        raise ValueError('Путь автозапуска слишком длинный. Перемести приложение в папку с более коротким путём.')
    return cmd


def launch_command():
    if getattr(sys,'frozen',False):
        target=Path(sys.executable).resolve()
        if not target.is_file():raise ValueError('EXE приложения не найден.')
        return command_for(target)
    folder=Path(__file__).resolve().parent
    target=Path(sys.executable).with_name('pythonw.exe')
    if not target.is_file():
        target=folder/'.venv/Scripts/pythonw.exe'
    if not target.is_file():raise ValueError('Для автозапуска исходников сначала запусти start.bat. Для раздачи используй собранный EXE.')
    return command_for(target,folder/'app.py')


def _legacy_shortcuts():
    appdata=os.environ.get('APPDATA')
    if not appdata:return []
    folder=Path(appdata)/'Microsoft/Windows/Start Menu/Programs/Startup'
    if not folder.is_dir():return []
    return [p for p in folder.iterdir() if p.name=='Lecture Pilot.lnk' or re.fullmatch(r'Lecture Pilot [0-9a-f]{8}\.lnk',p.name)]


def status():
    try:r=_registry()
    except ValueError:return {'supported':False,'registered':False,'disabled_by_windows':False,'path_matches':False,'legacy':False,'label':'Проверка автозапуска доступна на Windows'}
    command=None
    try:
        with r.OpenKey(r.HKEY_CURRENT_USER,RUN_KEY,0,r.KEY_READ) as key:command=r.QueryValueEx(key,VALUE_NAME)[0]
    except OSError:pass
    disabled=False
    try:
        with r.OpenKey(r.HKEY_CURRENT_USER,APPROVED_KEY,0,r.KEY_READ) as key:approved=r.QueryValueEx(key,VALUE_NAME)[0]
        if isinstance(approved,bytes) and len(approved)>=4:disabled=int.from_bytes(approved[:4],'little') in (3,7)
    except OSError:pass
    try:matches=bool(command and command==launch_command())
    except ValueError:matches=False
    legacy=bool(_legacy_shortcuts())
    label=('Отключено в параметрах автозагрузки Windows' if disabled and command else
           'Включено при входе в Windows' if command and matches else
           'Запись есть, но путь отличается — нажми «Включить / исправить»' if command else
           'Найден старый ярлык — нажми «Включить / исправить»' if legacy else
           'Автозагрузка Windows не настроена')
    return {'supported':True,'registered':bool(command),'disabled_by_windows':disabled,'path_matches':matches,'legacy':legacy,'label':label}


def configure(data_dir, remove=False):
    r=_registry()
    if remove:
        try:
            with r.OpenKey(r.HKEY_CURRENT_USER,RUN_KEY,0,r.KEY_SET_VALUE) as key:r.DeleteValue(key,VALUE_NAME)
        except FileNotFoundError:pass
        for path in _legacy_shortcuts():path.unlink(missing_ok=True)
        return status()
    data=json.loads((Path(data_dir)/'settings.json').read_text(encoding='utf-8'))
    if not(data.get('name') and data.get('group') and data.get('autostart') and data.get('consent_accepted')):
        raise ValueError('Сначала сохрани профиль и один раз включи автовход с его запоминанием.')
    command=launch_command()
    with r.CreateKeyEx(r.HKEY_CURRENT_USER,RUN_KEY,0,r.KEY_SET_VALUE) as key:
        r.SetValueEx(key,VALUE_NAME,0,r.REG_SZ,command)
    # Delete only this application's known legacy shortcuts after successful registration.
    for path in _legacy_shortcuts():path.unlink(missing_ok=True)
    result=status()
    if not result['registered'] or not result['path_matches']:
        raise ValueError('Не удалось подтвердить запись автозапуска Windows.')
    return result
