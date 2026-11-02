"""Explicit per-user Desktop and Start Menu shortcuts; no admin rights or pinning."""
import base64
import os
import subprocess
import sys
from pathlib import Path
NAME='Lecture Pilot by pik1.lnk'

def launch_target():
    if getattr(sys,'frozen',False):return Path(sys.executable).resolve(),''
    exe=Path(sys.executable).with_name('pythonw.exe')
    if not exe.is_file():raise ValueError('Для ярлыков исходников нужен pythonw.exe. Используй Python с python.org или собранный EXE.')
    return exe,'"'+str(Path(__file__).resolve().parent/'app.py')+'"'

def shortcut_paths():
    if sys.platform!='win32':raise ValueError('Ярлыки доступны только в Windows.')
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders') as key:
        desktop=os.path.expandvars(winreg.QueryValueEx(key,'Desktop')[0])
    appdata=os.environ.get('APPDATA')
    if not appdata:raise ValueError('Не найдена пользовательская папка меню «Пуск».')
    return [Path(desktop)/NAME,Path(appdata)/'Microsoft/Windows/Start Menu/Programs'/NAME]

def ps_literal(value):return "'"+str(value).replace("'","''")+"'"

def create(resources):
    target,args=launch_target()
    if not target.is_file():raise ValueError('Файл запуска не найден.')
    paths=shortcut_paths()
    # EXE icon remains stable; never reference one-file's temporary _MEIPASS.
    icon=str(target)+',0' if getattr(sys,'frozen',False) else str(Path(resources)/'app-icon.ico')
    script="$ErrorActionPreference='Stop'; $ws=New-Object -ComObject WScript.Shell;\n"
    for path in paths:
        path.parent.mkdir(parents=True,exist_ok=True)
        script+='$s=$ws.CreateShortcut('+ps_literal(path)+');'
        script+='$s.TargetPath='+ps_literal(target)+';$s.Arguments='+ps_literal(args)+';'
        script+='$s.WorkingDirectory='+ps_literal(target.parent)+';$s.IconLocation='+ps_literal(icon)+';'
        script+="$s.Description='Lecture Pilot by pik1';$s.Save();\n"
    encoded=base64.b64encode(script.encode('utf-16le')).decode('ascii')
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-EncodedCommand',encoded],capture_output=True,timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode or not all(p.is_file() for p in paths):
        raise ValueError('Не удалось создать ярлыки. Проверь доступ к рабочему столу и ограничения Windows.')
    return [str(p) for p in paths]
