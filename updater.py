"""Signed GitHub release update, opt-in and fail-closed. Never imports private keys."""
import base64, hashlib, json, os, re, shutil, subprocess, sys, tempfile, time
from pathlib import Path
from urllib.request import Request, urlopen, build_opener, HTTPSHandler, HTTPRedirectHandler
from urllib.parse import urlparse
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

VERSION='1.8.0'
REPO='https://github.com/pik1qq/LecturePilot'
ALLOWED={'github.com','objects.githubusercontent.com','release-assets.githubusercontent.com','github-releases.githubusercontent.com'}
MAX_SIZE=150_000_000

def public_key():
    root=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))
    return base64.b64decode((root/'update_public_key.txt').read_text().strip(),validate=True)

def version_tuple(value):
    if not isinstance(value,str) or not re.fullmatch(r'[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}',value):raise ValueError('Некорректная версия обновления')
    return tuple(map(int,value.split('.')))

def verify_manifest(raw,sig,key=None):
    if len(raw)>4096 or len(sig)>512:raise ValueError('Некорректный манифест обновления')
    Ed25519PublicKey.from_public_bytes(key or public_key()).verify(base64.b64decode(sig,validate=True),raw)
    obj=json.loads(raw)
    if set(obj)!={'version','sha256','size'}:raise ValueError('Некорректный манифест')
    version_tuple(obj['version'])
    if not re.fullmatch('[a-f0-9]{64}',obj['sha256']) or type(obj['size']) is not int or not 0<obj['size']<=MAX_SIZE:raise ValueError('Некорректные параметры файла')
    return obj

class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        check_url(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)
def check_url(url):
    u=urlparse(url)
    if u.scheme!='https' or u.hostname not in ALLOWED or u.username or u.password or u.port not in (None,443):raise ValueError('Недопустимый адрес обновления')
def fetch(url,limit):
    check_url(url)
    with build_opener(HTTPSHandler(),SafeRedirect()).open(Request(url,headers={'User-Agent':'LecturePilot-Updater/1.8'}),timeout=25) as r:
        check_url(r.geturl());data=r.read(limit+1)
    if len(data)>limit:raise ValueError('Слишком большой ответ обновления')
    return data

def check_latest(fetcher=fetch):
    raw=fetcher(REPO+'/releases/latest/download/update.json',4096)
    sig=fetcher(REPO+'/releases/latest/download/update.sig',512)
    meta=verify_manifest(raw,sig)
    return meta,raw,sig

def download_update(meta,raw,sig,folder,fetcher=fetch):
    if version_tuple(meta['version'])<=version_tuple(VERSION):raise ValueError('Новая версия не найдена')
    path=REPO+'/releases/download/v'+meta['version']+'/LecturePilot.exe'
    data=fetcher(path,meta['size'])
    if len(data)!=meta['size'] or hashlib.sha256(data).hexdigest()!=meta['sha256']:raise ValueError('Файл не прошёл проверку целостности')
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    fd,p=tempfile.mkstemp(prefix='LecturePilot-update-',suffix='.exe',dir=folder)
    with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
    return Path(p)

def prepare_helper(target,candidate,raw,sig):
    if os.name!='nt' or not getattr(sys,'frozen',False):raise ValueError('Обновление доступно только для собранного приложения Windows')
    target=Path(target).resolve();candidate=Path(candidate).resolve()
    if target.name.lower()!='lecturepilot.exe' or not target.is_file() or not candidate.is_file():raise ValueError('Для обновления файл должен называться LecturePilot.exe')
    meta=verify_manifest(raw,sig)
    if version_tuple(meta['version'])<=version_tuple(VERSION):raise ValueError('Версия обновления устарела')
    helper=target.with_name('LecturePilot-update-helper.exe'); payload=target.with_name('LecturePilot-update-payload.json')
    if helper.exists() or payload.exists():raise ValueError('Остались файлы предыдущего обновления; перезапусти приложение и повтори попытку')
    try:
        shutil.copy2(target,helper)
        payload.write_text(json.dumps({'target':str(target),'candidate':str(candidate),'raw':base64.b64encode(raw).decode(),'sig':base64.b64encode(sig).decode(),'pid':os.getpid()}),encoding='utf-8')
        subprocess.Popen([str(helper),'--apply-update',str(payload)],creationflags=0x00000008|0x00000200,close_fds=True)
    except Exception:
        helper.unlink(missing_ok=True);payload.unlink(missing_ok=True);raise

def run_helper(payload_path):
    if os.name!='nt' or not getattr(sys,'frozen',False):raise ValueError('Недопустимый запуск помощника')
    payload_path=Path(payload_path).resolve();info=json.loads(payload_path.read_text(encoding='utf-8'))
    target=Path(info['target']).resolve();candidate=Path(info['candidate']).resolve()
    if target.name.lower()!='lecturepilot.exe' or payload_path.parent!=target.parent or Path(sys.executable).resolve().parent!=target.parent:raise ValueError('Недопустимый путь обновления')
    meta=verify_manifest(base64.b64decode(info['raw']),base64.b64decode(info['sig']))
    if version_tuple(meta['version'])<=version_tuple(VERSION):raise ValueError('Версия обновления устарела')
    # Wait for the owning process rather than guessing its exit time.
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.windll.kernel32
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD];kernel.WaitForSingleObject.restype=wintypes.DWORD
    kernel.CloseHandle.argtypes=[wintypes.HANDLE];kernel.CloseHandle.restype=wintypes.BOOL
    handle=kernel.OpenProcess(0x00100000,False,int(info['pid']))
    if handle:
        try:
            if kernel.WaitForSingleObject(handle,90000)!=0:raise TimeoutError('Приложение не завершилось')
        finally:kernel.CloseHandle(handle)
    if not candidate.is_file() or candidate.stat().st_size!=meta['size']:raise ValueError('Файл обновления отсутствует')
    with candidate.open('rb') as f:
        digest=hashlib.file_digest(f,'sha256').hexdigest() if hasattr(hashlib,'file_digest') else hashlib.sha256(f.read()).hexdigest()
    if digest!=meta['sha256']:raise ValueError('Подпись обновления не соответствует файлу')
    staged=target.with_name('LecturePilot-next.exe');backup=target.with_name('LecturePilot-previous.exe')
    if staged.exists():raise ValueError('Остался временный файл предыдущего обновления')
    try:
        shutil.copyfile(candidate,staged)
        if backup.exists():backup.unlink()
        os.replace(target,backup)
        try:
            os.replace(staged,target)
            subprocess.Popen([str(target)],close_fds=True)
        except Exception:
            if target.exists():target.unlink()
            os.replace(backup,target)
            subprocess.Popen([str(target)],close_fds=True)
            raise
    finally:
        staged.unlink(missing_ok=True);candidate.unlink(missing_ok=True);payload_path.unlink(missing_ok=True)
