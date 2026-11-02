"""Detect Windows' default HTTPS browser without modifying its settings."""
import os
import re
from pathlib import Path


def classify_executable(path):
    if not path:
        return None
    p=str(path).replace('\\','/').lower()
    name=p.rsplit('/',1)[-1]
    if name=='chrome.exe': return 'Google Chrome'
    if name=='msedge.exe': return 'Microsoft Edge'
    if name=='browser.exe' and 'yandex' in p: return 'Яндекс Браузер'
    return None


def command_executable(command):
    match=re.match(r'^\s*"([^"]+)"',command)
    if match:return os.path.expandvars(match.group(1))
    match=re.match(r'^\s*([^\s]+\.exe)(?:\s|$)',command,re.I)
    return os.path.expandvars(match.group(1)) if match else None


def default_browser():
    if os.name!='nt':return {'label':'Браузер Windows','supported':False,'path':None}
    import winreg
    try:
        key=r'Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice'
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,key) as k:prog=winreg.QueryValueEx(k,'ProgId')[0]
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT,prog+r'\shell\open\command') as k:cmd=winreg.QueryValueEx(k,'')[0]
        path=command_executable(cmd)
        label=classify_executable(path)
        return {'label':label or ('Firefox' if path and 'firefox' in path.lower() else 'Другой браузер'),
                'supported':bool(label and path and Path(path).is_file()),'path':path}
    except OSError:return {'label':'Не удалось определить браузер','supported':False,'path':None}


def find_installed(choice):
    roots=[os.environ.get('LOCALAPPDATA',''),os.environ.get('PROGRAMFILES',''),os.environ.get('PROGRAMFILES(X86)','')]
    suffix={'chrome':'Google/Chrome/Application/chrome.exe','edge':'Microsoft/Edge/Application/msedge.exe',
            'yandex':'Yandex/YandexBrowser/Application/browser.exe'}.get(choice)
    if not suffix:return None
    return next((str(Path(root)/suffix) for root in roots if root and (Path(root)/suffix).is_file()),None)


def browser_info(choice='default'):
    default=default_browser()
    if choice=='default':selected=default
    else:
        path=find_installed(choice)
        selected={'label':{'chrome':'Google Chrome','edge':'Microsoft Edge','yandex':'Яндекс Браузер'}.get(choice,'Неизвестный браузер'),
                  'supported':bool(path),'path':path}
    return {'default_label':default['label'],'selected_label':selected['label'],'supported':selected['supported']}


def launch_options(choice='default'):
    if choice=='default':path=default_browser()['path']
    else:path=find_installed(choice)
    if not path or not classify_executable(path) or not Path(path).is_file():
        raise ValueError('Автоматический вход поддерживается только для установленных Chrome, Edge и Яндекс. Выбери один из них в настройках. Браузер Windows по умолчанию изменять не требуется.')
    return {'executable_path':path}
