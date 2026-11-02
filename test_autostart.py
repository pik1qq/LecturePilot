import copy
import json
import tempfile
import threading
import unittest
from datetime import timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen
import app
from core import validate_settings

class AutostartTests(unittest.TestCase):
    def setUp(self):
        self.browser_patch=patch('app.browser_launch_options',return_value={'channel':'chrome'})
        self.browser_patch.start()
        self.addCleanup(self.browser_patch.stop)
        self.old=copy.deepcopy(app.state)
        app.state.update(settings={**app.DEFAULTS,'group':'000-000','name':'Тестовый Участник','autostart':True,'consent_accepted':True},
                         armed=False,active=None,resume_pending=True,engine_ready=True,
                         updated=app.now().isoformat(),lessons=[],opened=[])
    def tearDown(self):
        app.state.clear();app.state.update(self.old)
    def test_resume(self):
        self.assertTrue(app.maybe_resume());self.assertTrue(app.state['armed']);self.assertFalse(app.state['resume_pending'])
        self.assertFalse(app.maybe_resume())
    def test_waits_for_schedule(self):
        app.state['updated']=None;self.assertFalse(app.maybe_resume());self.assertTrue(app.state['resume_pending'])
    def test_waits_for_browser_engine(self):
        app.state['engine_ready']=False;self.assertFalse(app.maybe_resume())
    def test_stale_schedule(self):
        app.state['updated']=(app.now()-timedelta(minutes=21)).isoformat();self.assertFalse(app.maybe_resume())
    def test_requires_prior_consent(self):
        app.state['settings']['consent_accepted']=False;self.assertFalse(app.maybe_resume())
    def test_respects_disabled_mode(self):
        app.state['settings']['autostart']=False;self.assertFalse(app.maybe_resume())
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(app,'BASE',Path(folder)):
            app.persist();saved=validate_settings(json.loads((Path(folder)/'settings.json').read_text()))
            self.assertTrue(saved['autostart']);self.assertTrue(saved['consent_accepted'])
    def endpoint(self,path,body):
        server=ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            req=Request('http://127.0.0.1:'+str(server.server_port)+'/api/'+path,
                        headers={'X-App-Token':app.TOKEN,'Content-Type':'application/json'},
                        data=json.dumps(body).encode())
            return json.load(urlopen(req,timeout=3))
        finally:server.shutdown();server.server_close();thread.join()
    def test_pause_preserves_saved_resume(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(app,'BASE',Path(folder)):
            app.state['armed']=True;self.endpoint('stop',{})
            self.assertFalse(app.state['armed']);self.assertFalse(app.state['resume_pending'])
            self.assertTrue(json.loads((Path(folder)/'settings.json').read_text())['autostart'])
    def test_start_saves_consent(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(app,'BASE',Path(folder)):
            app.state['settings']['consent_accepted']=False
            self.endpoint('start',{'consent':True})
            saved=json.loads((Path(folder)/'settings.json').read_text())
            self.assertTrue(saved['consent_accepted']);self.assertTrue(saved['autostart'])
    def test_start_accepts_saved_consent(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(app,'BASE',Path(folder)):
            self.endpoint('start',{'use_saved_consent':True})
            self.assertTrue(app.state['armed'])
    def test_browser_not_ready_retries(self):
        with patch('app.browser_launch_options',side_effect=ValueError('not ready')):
            self.assertFalse(app.maybe_resume());self.assertTrue(app.state['resume_pending'])
        self.assertTrue(app.maybe_resume());self.assertTrue(app.state['armed'])
    def test_network_failure_then_recovery_restores_resume(self):
        import io
        app.state['updated']=None
        with tempfile.TemporaryDirectory() as folder,patch.object(app,'BASE',Path(folder)):
            with patch('app.urlopen',side_effect=OSError('Offline')):
                app.refresh()
            self.assertFalse(app.state['armed']);self.assertTrue(app.state['resume_pending'])
            self.assertEqual(app.refresh_delay(),15)
            with patch('app.urlopen',return_value=io.BytesIO(b'{"days":[]}')):
                app.refresh()
            self.assertTrue(app.state['armed']);self.assertFalse(app.state['resume_pending'])
            self.assertEqual(app.refresh_delay(),300)
    def test_network_retry_interval(self):
        app.state['fetch_ok']=False;self.assertEqual(app.refresh_delay(),15)
        app.state['fetch_ok']=True;self.assertEqual(app.refresh_delay(),300)
    def test_new_identity_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(app,'BASE',Path(folder)),patch.object(app,'refresh'):
            changed={**app.state['settings'],'name':'Другой Участник','consent_accepted':True}
            self.endpoint('save',changed)
            self.assertFalse(app.state['settings']['consent_accepted'])

    def test_audio_switch_is_saved(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(app,'BASE',Path(folder)):
            app.state['active']={'id':'test'}
            self.endpoint('audio',{'muted':False})
            self.assertFalse(app.state['settings']['muted'])
            self.assertFalse(json.loads((Path(folder)/'settings.json').read_text())['muted'])
    def test_audio_switch_does_not_arm_schedule(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(app,'BASE',Path(folder)):
            app.state['active']={'id':'test'}
            app.state['armed']=False
            self.endpoint('audio',{'muted':True})
            self.assertFalse(app.state['armed'])

if __name__=='__main__':unittest.main()
