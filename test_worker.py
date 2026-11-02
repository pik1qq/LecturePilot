"""Offline scheduler integration test: no browser or external connection."""
import threading
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
import app

class Page:
    def __init__(self, context):
        self.context=context
        self.url='about:blank'
        self.closed=False
        self.filled=[]
        self.scripts=[]
    def is_closed(self): return self.closed
    def close(self): self.closed=True
    def goto(self,url,**kwargs): self.url=url
    def on(self,*args): pass
    def add_init_script(self,**kwargs): self.scripts.append(kwargs)
    def get_by_role(self,role,**kwargs): return Fields(self,role)
    def wait_for_timeout(self,ms): time.sleep(.002)
class Fields:
    def __init__(self,page,role): self.page=page; self.role=role
    def all(self): return [self] if self.role=='textbox' else []
    def is_visible(self): return True
    def is_editable(self): return True
    def fill(self,value,**kwargs): self.page.filled.append(value)
class Context:
    def __init__(self): self._pages=[Page(self)]; self.closed=False; self.scripts=[]
    @property
    def pages(self): return [x for x in self._pages if not x.closed]
    def new_page(self): p=Page(self); self._pages.append(p); return p
    def add_init_script(self,**kwargs): self.scripts.append(kwargs)
    def close(self):
        self.closed=True
        for page in self._pages: page.close()
class FakePlaywright:
    def __init__(self): self.chromium=self; self.context=Context(); self.launch_args=None
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def launch_persistent_context(self,*args,**kwargs): self.launch_args=kwargs; return self.context

class WorkerTest(unittest.TestCase):
    def test_sequential_lessons_and_stop(self):
        clock=[datetime(2026,10,19,10,40,tzinfo=app.MOSCOW)]
        tick=[0]
        def monotonic(): tick[0]+=10; return tick[0]
        lessons=[]
        for n in range(2):
            start=clock[0]+timedelta(minutes=90*n)
            lessons.append({'id':str(n),'subject':'Тест '+str(n),'start':start.isoformat(),
                            'end':(start+timedelta(minutes=90)).isoformat(),'eligible':True,
                            'url':'https://my.mts-link.ru/j/test/'+str(n)})
        app.QUIT.clear();app.WAKE.clear()
        app.state.update(settings={**app.DEFAULTS, 'group':'000-000', 'name':'Тестовый Участник'}, lessons=lessons,armed=True,
                         active=None,opened=[],updated=clock[0].isoformat())
        fake=FakePlaywright()
        def wait_for(predicate):
            deadline=time.perf_counter()+4
            while time.perf_counter()<deadline:
                if predicate(): return
                time.sleep(.01)
            self.fail('Timed out')
        with patch('app.browser_launch_options',return_value={'channel':'chrome'}),patch('playwright.sync_api.sync_playwright',return_value=fake),patch.object(app,'now',side_effect=lambda:clock[0]),patch('app.time.monotonic',side_effect=monotonic):
            thread=threading.Thread(target=app.browser_loop,daemon=True);thread.start()
            try:
                actual = lambda: [p for p in fake.context._pages if p.url != 'about:blank']
                wait_for(lambda:len(actual())>=1 and bool(actual()[0].filled))
                self.assertEqual(actual()[0].filled[0],'000-000 Тестовый Участник')
                self.assertNotIn('--mute-audio',fake.launch_args['args'])
                self.assertEqual(len(actual()[0].scripts),1)
                self.assertEqual(len(fake.context.scripts),1)
                clock[0]+=timedelta(minutes=90)
                app.state['updated']=clock[0].isoformat()
                wait_for(lambda:len(actual())==2 and bool(actual()[1].filled))
                self.assertTrue(actual()[0].closed)
                self.assertTrue(any(p.url == 'about:blank' and not p.closed for p in fake.context._pages))
                self.assertEqual(app.state['opened'],['0','1'])
                app.state['armed']=False;app.WAKE.set()
                wait_for(lambda:fake.context.closed and app.state['active'] is None)
            finally:
                app.QUIT.set();app.WAKE.set();thread.join(timeout=4)
        self.assertFalse(thread.is_alive())

if __name__=='__main__':unittest.main()
