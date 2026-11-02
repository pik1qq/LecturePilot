"""Offline tests only: registry is a fake, no Windows startup is modified."""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import app
import windows_startup as startup
from core import validate_settings
from settings_store import load_settings,save_settings

PROFILE={**app.DEFAULTS,'group':'000-000','name':'Тестовый Участник','lead':5,'autostart':True,'consent_accepted':True,'windows_startup_enabled':True}

class Key:
    def __init__(self,path):self.path=path
    def __enter__(self):return self
    def __exit__(self,*a):pass
class FakeRegistry:
    HKEY_CURRENT_USER=1;KEY_READ=1;KEY_SET_VALUE=2;REG_SZ=1
    def __init__(self):self.values={};self.writes=[]
    def OpenKey(self,root,path,*args):
        if path not in self.values:raise FileNotFoundError(path)
        return Key(path)
    def CreateKeyEx(self,root,path,*args):self.values.setdefault(path,{});return Key(path)
    def QueryValueEx(self,key,name):
        if name not in self.values[key.path]:raise FileNotFoundError(name)
        return self.values[key.path][name],1
    def SetValueEx(self,key,name,reserved,kind,value):self.values[key.path][name]=value;self.writes.append((key.path,name,value))
    def DeleteValue(self,key,name):
        if name not in self.values[key.path]:raise FileNotFoundError(name)
        del self.values[key.path][name]

class StartupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.folder=Path(self.tmp.name)
        save_settings(self.folder,PROFILE)
        self.registry=FakeRegistry();self.command='"C:\\Apps with spaces\\LecturePilot.exe" --background'
        for target,value in [('_registry',self.registry),('launch_command',self.command),('_legacy_shortcuts',[])]:
            p=patch.object(startup,target,return_value=value);p.start();self.addCleanup(p.stop)
    def test_quoted_command(self):
        self.assertEqual(startup.command_for(r'C:\Apps with spaces\LecturePilot.exe'),self.command)
        self.assertEqual(startup.command_for(r'C:\Apps\pythonw.exe',r'C:\My Folder\app.py'),'"C:\\Apps\\pythonw.exe" "C:\\My Folder\\app.py" --background')
        with self.assertRaises(ValueError):startup.command_for('bad"path')
        with self.assertRaises(ValueError):startup.command_for('x'*300)
    def test_register_verify_remove(self):
        info=startup.configure(self.folder)
        self.assertTrue(info['registered']);self.assertTrue(info['path_matches'])
        self.assertEqual(self.registry.values[startup.RUN_KEY][startup.VALUE_NAME],self.command)
        self.assertFalse(startup.configure(self.folder,remove=True)['registered'])
    def test_requires_saved_permission(self):
        save_settings(self.folder,{**PROFILE,'consent_accepted':False})
        with self.assertRaises(ValueError):startup.configure(self.folder)
        self.assertEqual(self.registry.writes,[])
    def test_does_not_override_os_disabled_flag(self):
        flag=(3).to_bytes(4,'little')+bytes(8)
        self.registry.values[startup.APPROVED_KEY]={startup.VALUE_NAME:flag}
        info=startup.configure(self.folder)
        self.assertTrue(info['disabled_by_windows']);self.assertTrue(info['registered'])
        self.assertEqual(self.registry.values[startup.APPROVED_KEY][startup.VALUE_NAME],flag)
        self.assertTrue(all(key==startup.RUN_KEY for key,name,value in self.registry.writes))
    def test_moved_path_reported(self):
        self.registry.values[startup.RUN_KEY]={startup.VALUE_NAME:'"C:\\old.exe" --background'}
        self.assertFalse(startup.status()['path_matches'])
        self.assertTrue(startup.configure(self.folder)['path_matches'])
    def test_legacy_shortcut_removed(self):
        old=self.folder/'Lecture Pilot.lnk';old.touch()
        with patch.object(startup,'_legacy_shortcuts',return_value=[old]):startup.configure(self.folder)
        self.assertFalse(old.exists())
    def test_cannot_claim_registration_if_verification_fails(self):
        with patch.object(startup,'status',return_value={'registered':False,'path_matches':False}):
            with self.assertRaises(ValueError):startup.configure(self.folder)

class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.folder=Path(self.tmp.name)
    def test_latest_state_in_backup(self):
        save_settings(self.folder,PROFILE)
        saved={**PROFILE,'consent_accepted':False,'autostart':False}
        save_settings(self.folder,saved)
        self.assertEqual(json.loads((self.folder/'settings.backup.json').read_text()),saved)
        self.assertFalse((self.folder/'settings.json.tmp').exists())
    def test_corrupt_primary_uses_backup(self):
        save_settings(self.folder,PROFILE);(self.folder/'settings.json').write_text('{broken')
        data,warning=load_settings(self.folder,app.DEFAULTS,validate_settings)
        self.assertTrue(data['autostart']);self.assertTrue(data['consent_accepted']);self.assertTrue(warning)
    def test_invalid_shape_safe_defaults(self):
        (self.folder/'settings.json').write_text('[]')
        data,warning=load_settings(self.folder,app.DEFAULTS,validate_settings)
        self.assertFalse(data['consent_accepted']);self.assertTrue(warning)
    def test_fresh_install_requires_confirmation(self):
        data,warning=load_settings(self.folder,app.DEFAULTS,validate_settings)
        self.assertEqual(data['name'],'');self.assertFalse(data['consent_accepted']);self.assertEqual(warning,'')
    def cold_start(self):
        env={**os.environ,'LECTURE_PILOT_DATA_DIR':str(self.folder)}
        script="import app,json;print(json.dumps({k:app.state[k] for k in ('settings','resume_pending','armed')}))"
        output=subprocess.check_output([sys.executable,'-c',script],env=env,text=True)
        return json.loads(output)
    def test_new_process_restores_preferences_and_pending_resume(self):
        save_settings(self.folder,PROFILE);state=self.cold_start()
        self.assertTrue(state['resume_pending']);self.assertFalse(state['armed'])
        for key in ('name','group','lead','autostart','consent_accepted','windows_startup_enabled'):
            self.assertEqual(state['settings'][key],PROFILE[key])
    def test_disabled_resume_remains_disabled_in_new_process(self):
        save_settings(self.folder,{**PROFILE,'autostart':False})
        self.assertFalse(self.cold_start()['resume_pending'])
    def test_local_event_log_survives_restart(self):
        old=list(app.logs)
        try:
            with patch.object(app,'BASE',self.folder):
                app.logs.clear();app.log('Test boot');app.logs.clear();app.restore_logs()
                self.assertEqual(app.logs[0]['message'],'Test boot');self.assertIn('at',app.logs[0])
        finally:app.logs.clear();app.logs.extend(old)

if __name__=='__main__':unittest.main()
