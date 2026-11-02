"""Atomic local preferences with fsync and a validated backup."""
import json
import os
from pathlib import Path


def atomic_write(path, text):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.tmp')
    try:
        with temporary.open('w',encoding='utf-8',newline='\n') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)


def save_settings(folder, data):
    content=json.dumps(data,ensure_ascii=False,indent=2)
    atomic_write(Path(folder)/'settings.json',content)
    # Same most recent confirmed state, not a backup of an unconfirmed older mode.
    atomic_write(Path(folder)/'settings.backup.json',content)


def load_settings(folder, defaults, validate):
    folder=Path(folder)
    primary=folder/'settings.json'
    backup=folder/'settings.backup.json'
    for path in (primary,backup):
        try:
            values=validate(json.loads(path.read_text(encoding='utf-8-sig')))
            if path==backup:
                return values,'Настройки восстановлены из резервной копии.'
            return values,''
        except (OSError,ValueError,TypeError,AttributeError):
            continue
    warning='Не удалось прочитать настройки. Нужно повторно сохранить профиль.' if primary.exists() or backup.exists() else ''
    return dict(defaults),warning
