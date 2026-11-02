"""Local Chromium tests for audio isolation; never connects to a webinar."""
import shutil
import tempfile
import unittest
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE=Path(__file__).resolve().parent
class AudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner=sync_playwright().start()
        cls.browser=cls.runner.chromium.launch(executable_path=shutil.which('chromium'),headless=True,args=['--no-sandbox'])
        cls.temp=tempfile.TemporaryDirectory()
        cls.url=(Path(cls.temp.name)/'audio.html').as_uri()
        (Path(cls.temp.name)/'audio.html').write_text('<!doctype html><html><body><audio id="sound"></audio><video id="video"></video></body></html>')
        cls.script=(BASE/'tab_audio.js').read_text()
    @classmethod
    def tearDownClass(cls):
        cls.browser.close();cls.runner.stop();cls.temp.cleanup()
    def setUp(self):
        self.context=self.browser.new_context()
        self.lecture=self.context.new_page();self.lecture.add_init_script(script=self.script);self.lecture.goto(self.url)
        self.other=self.context.new_page();self.other.goto(self.url)
    def tearDown(self):self.context.close()
    def test_only_lecture_page_is_muted(self):
        self.assertTrue(self.lecture.eval_on_selector('#sound','e=>e.muted'))
        self.assertFalse(self.other.eval_on_selector('#sound','e=>e.muted'))
        self.assertFalse(self.other.evaluate("typeof globalThis.__lecturePilotSetMuted==='function'"))
    def test_unmute_restores_media_state(self):
        self.lecture.evaluate('globalThis.__lecturePilotSetMuted(false)')
        self.assertFalse(self.lecture.eval_on_selector('#sound','e=>e.muted'))
        self.lecture.evaluate('globalThis.__lecturePilotSetMuted(true)')
        self.assertTrue(self.lecture.eval_on_selector('#sound','e=>e.muted'))
    def test_future_media_is_muted(self):
        self.lecture.evaluate("let x=document.createElement('audio');x.id='later';document.body.append(x)")
        self.lecture.wait_for_function("document.getElementById('later').muted")
    def test_webaudio_silence_and_restore(self):
        synth='''async()=>{const context=new OfflineAudioContext(1,2048,48000);const source=context.createOscillator();source.connect(context.destination);source.start();const buffer=await context.startRendering();let peak=0;for(const n of buffer.getChannelData(0))peak=Math.max(peak,Math.abs(n));return peak;}'''
        self.assertEqual(self.lecture.evaluate(synth),0)
        self.assertGreater(self.other.evaluate(synth),0.5)
        self.lecture.evaluate('globalThis.__lecturePilotSetMuted(false)')
        self.assertGreater(self.lecture.evaluate(synth),0.5)
    def test_speaker_state_is_not_a_test_of_platform_attention(self):
        # Only verify media state. No platform status is inferred from this test.
        self.assertTrue(self.lecture.eval_on_selector('#video','e=>e.muted'))
        self.assertFalse(self.other.eval_on_selector('#video','e=>e.muted'))

if __name__=='__main__':unittest.main()
