import base64,copy,hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
import updater,app

class UpdateTests(unittest.TestCase):
 def setUp(self):
  self.k=Ed25519PrivateKey.generate();self.key=self.k.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw);self.exe=b'fake-test-exe'
  self.meta={'version':'9.0.0','sha256':hashlib.sha256(self.exe).hexdigest(),'size':len(self.exe)}
  self.raw=json.dumps(self.meta,sort_keys=True,separators=(',',':')).encode();self.sig=base64.b64encode(self.k.sign(self.raw))
 def test_verification(self):self.assertEqual(updater.verify_manifest(self.raw,self.sig,self.key),self.meta)
 def test_modified_manifest_rejected(self):
  with self.assertRaises(Exception):updater.verify_manifest(self.raw.replace(b'9.0.0',b'9.0.1'),self.sig,self.key)
 def test_wrong_key_rejected(self):
  with self.assertRaises(Exception):updater.verify_manifest(self.raw,self.sig,Ed25519PrivateKey.generate().public_key().public_bytes(Encoding.Raw,PublicFormat.Raw))
 def test_url_allowlist(self):
  updater.check_url('https://github.com/pik1qq/LecturePilot')
  for bad in ('http://github.com/x','https://github.com.evil.example/x','https://evil.example/x','https://user@github.com/x'):
   with self.assertRaises(ValueError):updater.check_url(bad)
 def test_download_verified_and_tampered(self):
  with tempfile.TemporaryDirectory() as d:
   path=updater.download_update(self.meta,self.raw,self.sig,d,lambda url,limit:self.exe);self.assertEqual(path.read_bytes(),self.exe)
   with self.assertRaises(ValueError):updater.download_update(self.meta,self.raw,self.sig,d,lambda url,limit:b'tampered')
 def test_downgrade_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(ValueError):updater.download_update({**self.meta,'version':'1.0.0'},self.raw,self.sig,d,lambda *a:self.exe)
 def test_fails_without_valid_hash(self):
  bad={**self.meta,'sha256':'not-a-hash'};raw=json.dumps(bad).encode()
  with self.assertRaises(ValueError):updater.verify_manifest(raw,base64.b64encode(self.k.sign(raw)),self.key)
 def test_no_install_with_active_lecture(self):
  old=copy.deepcopy(app.state);app.state.update(active={'id':'x'},update_busy=False)
  try:
   with self.assertRaises(ValueError):app.install_update(None)
  finally:app.state.clear();app.state.update(old)
 def test_version_format(self):
  for v in ['v1.0.0','1.2','1.2.3-rc1','../../abc']:
   with self.assertRaises(ValueError):updater.version_tuple(v)

class ThemeTests(unittest.TestCase):
 def test_save_theme_loads_again(self):
  with tempfile.TemporaryDirectory() as d,patch.object(app,'BASE',Path(d)):
   app.atomic_write(Path(d)/'appearance.json','{"theme":"dark"}')
   self.assertEqual(app.load_theme(),'dark')
 def test_invalid_theme_defaults_light(self):
  with tempfile.TemporaryDirectory() as d,patch.object(app,'BASE',Path(d)):
   app.atomic_write(Path(d)/'appearance.json','{"theme":"unknown"}')
   self.assertEqual(app.load_theme(),'light')
if __name__=='__main__':unittest.main()
