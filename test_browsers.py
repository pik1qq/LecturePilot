import unittest
from browsers import classify_executable,command_executable
from core import validate_settings

class BrowserTests(unittest.TestCase):
    def test_chrome(self):self.assertEqual(classify_executable(r'C:\Program Files\Google\Chrome\Application\chrome.exe'),'Google Chrome')
    def test_edge(self):self.assertEqual(classify_executable(r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'),'Microsoft Edge')
    def test_yandex(self):self.assertEqual(classify_executable(r'C:\Users\Test\AppData\Local\Yandex\YandexBrowser\Application\browser.exe'),'Яндекс Браузер')
    def test_unknown_browser(self):self.assertIsNone(classify_executable(r'C:\Other\browser.exe'))
    def test_firefox(self):self.assertIsNone(classify_executable(r'C:\Firefox\firefox.exe'))
    def test_command(self):self.assertEqual(command_executable('"C:\\Program Files\\Browser\\chrome.exe" --single-argument "%1"'),r'C:\Program Files\Browser\chrome.exe')
    def test_ambiguous_unquoted_command(self):self.assertIsNone(command_executable(r'C:\Program Files\Browser\chrome.exe %1'))
    def test_unknown_setting(self):
        with self.assertRaises(ValueError):validate_settings({'group':'000-000','name':'Тест','browser':'unknown'})
if __name__=='__main__':unittest.main()
