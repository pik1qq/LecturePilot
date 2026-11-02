"""CI release signing; private key must be supplied through a secret environment variable."""
import base64, hashlib, json, os, sys
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat

def sign(exe,version):
    key=Ed25519PrivateKey.from_private_bytes(base64.b64decode(os.environ['LECTUREPILOT_SIGNING_KEY'],validate=True))
    public=base64.b64encode(key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)).decode()
    if public != Path('update_public_key.txt').read_text().strip():raise ValueError('Ключ не соответствует публичному ключу приложения')
    exe=Path(exe);data=exe.read_bytes()
    manifest=json.dumps({'version':version,'sha256':hashlib.sha256(data).hexdigest(),'size':len(data)},sort_keys=True,separators=(',',':')).encode()
    Path('update.json').write_bytes(manifest)
    Path('update.sig').write_bytes(base64.b64encode(key.sign(manifest)))
if __name__=='__main__':sign(sys.argv[1],sys.argv[2])
