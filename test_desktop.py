"""Offline Windows-shell/native UI contract tests; no real registry or desktop writes."""
import base64,copy,json,sys,tempfile,threading,time,types,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
import app
import native_window
import windows_shortcuts as shortcuts
from managed_panel import ManagedPanel
from test_worker import Page,Context,FakePlaywright

class PanelPage(Page):
    def bring_to_front(self):self.brought=True
class PanelContext(Context):
    def __init__(self):super().__init__();self._pages=[PanelPage(self)]
    def new_page(self):p=PanelPage(self);self._pages.append(p);return p
class ManyContexts(FakePlaywright):
    def __init__(self):super().__init__();self.contexts=[]
    def launch_persistent_context(self,*args,**kwargs):
        c=PanelContext();self.contexts.append(c);return c

class PanelTests(unittest.TestCase):
    def test_panel_reused_and_only_own_context_closed(self):
        chromium=ManyContexts();personal=PanelContext()
        panel=ManagedPanel(chromium,Path('/tmp/qa'),lambda s:{'channel':'chrome'})
        panel.open('http://127.0.0.1:12345','default');first=panel.page
        panel.open('http://127.0.0.1:12345','default')
        self.assertEqual(len(chromium.contexts),1);self.assertIs(panel.page,first)
        first.close();panel.open('http://127.0.0.1:12345','default')
        self.assertIsNot(panel.page,first);panel.close()
        self.assertTrue(chromium.contexts[0].closed);self.assertFalse(personal.closed)
    def test_unsupported_default_can_fallback_only_for_local_panel(self):
        calls=[]
        def options(selection):
            calls.append(selection)
            if selection=='default':raise ValueError('Firefox unsupported')
            return {'channel':'msedge'}
        panel=ManagedPanel(ManyContexts(),Path('/tmp/qa'),options)
        panel.open('http://127.0.0.1:12345','default');self.assertEqual(calls,['default','edge']);panel.close()
    def test_external_panel_url_rejected(self):
        panel=ManagedPanel(ManyContexts(),Path('/tmp/qa'),lambda s:{})
        with self.assertRaises(ValueError):panel.open('https://example.com','default')
    def test_worker_exit_closes_panel_and_lecture(self):
        old=copy.deepcopy(app.state);oldurl=app.PANEL_URL
        fake=ManyContexts();app.QUIT.clear();app.OPEN_PANEL.set();app.PANEL_URL='http://127.0.0.1:12345'
        current=app.now()
        lesson={'id':'desktop-test','subject':'Тест','start':current.isoformat(),'end':(current+app.timedelta(minutes=90)).isoformat(),'eligible':True,'url':'https://my.mts-link.ru/j/test'}
        app.state.update(settings={**app.DEFAULTS,'group':'000-000','name':'Тестовый Участник'},lessons=[lesson],armed=True,active=None,opened=[],resume_pending=False,updated=current.isoformat())
        with tempfile.TemporaryDirectory() as folder,patch.object(app,'BASE',Path(folder)),patch('app.browser_launch_options',return_value={'channel':'chrome'}),patch('playwright.sync_api.sync_playwright',return_value=fake):
            worker=threading.Thread(target=app.browser_loop);worker.start()
            try:
                deadline=time.monotonic()+5
                while not app.state['active'] and time.monotonic()<deadline:time.sleep(.01)
                self.assertTrue(app.state['active']);self.assertEqual(len(fake.contexts),2)
                fake.contexts[0].pages[0].close()
                self.assertTrue(app.state['armed'],'Closing dashboard must not stop the schedule')
            finally:
                app.QUIT.set();app.WAKE.set();worker.join(timeout=5)
                app.state.clear();app.state.update(old);app.PANEL_URL=oldurl;app.OPEN_PANEL.clear();app.QUIT.clear()
        self.assertFalse(worker.is_alive());self.assertTrue(all(c.closed for c in fake.contexts))

class NativeContractTests(unittest.TestCase):
    def test_exactly_two_buttons_and_taskbar_title(self):
        tk=types.ModuleType('tkinter');ttk=types.ModuleType('tkinter.ttk');messagebox=types.ModuleType('tkinter.messagebox')
        root=MagicMock();tk.Tk=MagicMock(return_value=root);tk.StringVar=MagicMock();tk.PhotoImage=MagicMock();tk.TclError=RuntimeError
        ttk.Style=MagicMock();ttk.Frame=MagicMock();ttk.Label=MagicMock();buttons=[]
        def button(*args,**kwargs):
            buttons.append(kwargs);return MagicMock()
        ttk.Button=button;messagebox.askyesno=MagicMock(return_value=True)
        tk.ttk=ttk;tk.messagebox=messagebox;opening=MagicMock();shutdown=MagicMock()
        with patch.dict(sys.modules,{'tkinter':tk,'tkinter.ttk':ttk,'tkinter.messagebox':messagebox}):
            native_window.run(Path('/qa'),lambda:'Тест',opening,shutdown,lambda:False,lambda:False)
        root.title.assert_called_once_with('Lecture Pilot by pik1')
        self.assertEqual([b['text'] for b in buttons],['Открыть панель','Завершить всё'])
        buttons[0]['command']();opening.assert_called_once()
        buttons[1]['command']();buttons[1]['command']();shutdown.assert_called_once()
        root.protocol.assert_called_once()

class ShortcutTests(unittest.TestCase):
    def test_quote_unicode_and_frozen_icon_is_not_temporary(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td);target=folder/'LecturePilot.exe';target.touch()
            paths=[folder/'Рабочий стол'/shortcuts.NAME,folder/'Пуск'/shortcuts.NAME]
            scripts=[]
            def run(args,**kw):
                scripts.append(base64.b64decode(args[-1]).decode('utf-16le'))
                for path in paths:path.touch()
                return types.SimpleNamespace(returncode=0)
            with patch.object(shortcuts,'launch_target',return_value=(target,'')),patch.object(shortcuts,'shortcut_paths',return_value=paths),patch.object(sys,'frozen',True,create=True),patch('windows_shortcuts.subprocess.run',side_effect=run):
                self.assertEqual(len(shortcuts.create('/temporary/MEIPASS')),2)
            self.assertIn('by pik1',scripts[0]);self.assertIn(str(target)+',0',scripts[0]);self.assertNotIn('MEIPASS',scripts[0])
            self.assertEqual(shortcuts.ps_literal("O'Brien"),"'O''Brien'")
    def test_shell_failure_not_reported_as_success(self):
        with tempfile.TemporaryDirectory() as td:
            target=Path(td)/'app.exe';target.touch()
            with patch.object(shortcuts,'launch_target',return_value=(target,'')),patch.object(shortcuts,'shortcut_paths',return_value=[Path(td)/'bad.lnk']),patch('windows_shortcuts.subprocess.run',return_value=types.SimpleNamespace(returncode=1)):
                with self.assertRaises(ValueError):shortcuts.create(td)

if __name__=='__main__':unittest.main()
