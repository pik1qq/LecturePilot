"""Per-user shortcuts with durable, theme-aware icons; no admin rights or pinning."""
import base64
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
NAME='Lecture Pilot by pik1.lnk'
DESCRIPTION='Lecture Pilot by pik1'

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

def persistent_icon(resources,data_dir,theme,version):
    if theme not in ('light','dark') or not version or not all(c.isdigit() or c=='.' for c in version):raise ValueError('Некорректная тема или версия значка.')
    source=Path(resources)/('app-icon-dark.ico' if theme=='dark' else 'app-icon.ico')
    directory=Path(data_dir)/'icons';directory.mkdir(parents=True,exist_ok=True)
    target=directory/('LecturePilot-'+version+'-'+theme+'.ico')
    if not target.exists() or target.read_bytes()!=source.read_bytes():
        fd,name=tempfile.mkstemp(prefix='icon-',suffix='.tmp',dir=directory);os.close(fd)
        try:shutil.copyfile(source,name);os.replace(name,target)
        finally:Path(name).unlink(missing_ok=True)
    return target

def _powershell(script):
    encoded=base64.b64encode(script.encode('utf-16le')).decode('ascii')
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-EncodedCommand',encoded],capture_output=True,timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:raise ValueError('Не удалось обновить ярлыки. Проверь доступ к рабочему столу и ограничения Windows.')

def create(resources,data_dir,theme,version):
    target,args=launch_target()
    if not target.is_file():raise ValueError('Файл запуска не найден.')
    paths=shortcut_paths();icon=str(persistent_icon(resources,data_dir,theme,version))+',0'
    script="$ErrorActionPreference='Stop'; $ws=New-Object -ComObject WScript.Shell;\n"
    for path in paths:
        path.parent.mkdir(parents=True,exist_ok=True)
        script+='$s=$ws.CreateShortcut('+ps_literal(path)+');'
        script+='$s.TargetPath='+ps_literal(target)+';$s.Arguments='+ps_literal(args)+';'
        script+='$s.WorkingDirectory='+ps_literal(target.parent)+';$s.IconLocation='+ps_literal(icon)+';'
        script+='$s.Description='+ps_literal(DESCRIPTION)+';$s.Save();\n'
    _powershell(script)
    if not all(p.is_file() for p in paths):raise ValueError('Не удалось создать ярлыки.')
    return [str(p) for p in paths]

def update_existing(resources,data_dir,theme,version):
    # Change only existing app-created shortcuts that still target this program.
    paths=[p for p in shortcut_paths() if p.is_file()]
    if not paths:return
    target,args=launch_target()
    if not target.is_file():return
    icon=str(persistent_icon(resources,data_dir,theme,version))+',0'
    script="$ErrorActionPreference='Stop'; $ws=New-Object -ComObject WScript.Shell;\n"
    # WScript.Shell may return 8.3 paths (e.g. RUNNER~1); expand both sides.
    script+="Add-Type -TypeDefinition 'using System; using System.Text; using System.Runtime.InteropServices; public static class LPPaths { [DllImport(\"kernel32.dll\", CharSet=CharSet.Unicode, SetLastError=true)] static extern uint GetLongPathName(string p, StringBuilder b, uint n); public static string Long(string p) { var b=new StringBuilder(32768); return GetLongPathName(p,b,(uint)b.Capacity)>0 ? b.ToString() : p; } }';\n"
    for path in paths:
        script+='$s=$ws.CreateShortcut('+ps_literal(path)+');'
        script+='if ([string]::Equals([LPPaths]::Long($s.TargetPath),[LPPaths]::Long('+ps_literal(target)+'),[StringComparison]::OrdinalIgnoreCase) -and $s.Arguments -eq '+ps_literal(args)+' -and $s.Description -eq '+ps_literal(DESCRIPTION)+') {'
        script+='$s.IconLocation='+ps_literal(icon)+';$s.Save()};\n'
    _powershell(script)
