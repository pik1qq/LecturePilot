import json
import unittest
from datetime import datetime, timedelta
from core import normalize, validate_settings, due_lesson, is_webinar_url

class CoreTests(unittest.TestCase):
    def setUp(self):
        self.settings = validate_settings({'group':'000-000', 'name':'Тестовый Участник'})
        self.item = {'type':'lesson', 'uid':'test', 'start':'2026-10-19T10:40:00+03:00',
                     'end':'2026-10-19T12:10:00+03:00', 'subject':'Химия','kind':'Лекция',
                     'is_online':True,'online_format':'webinar',
                     'links':[{'url':'https://my.mts-link.ru/j/1/2','groups':['000-000']}]}
    def data(self, item=None):
        return normalize({'days':[{'items':[item or self.item]}]}, '000-000')
    def test_url_validation(self):
        for url in ['https://evil.com','https://mts-link.ru.evil.com/j','http://my.mts-link.ru','https://user:secret@my.mts-link.ru','https://my.mts-link.ru:444/']:
            self.assertFalse(is_webinar_url(url))
        self.assertTrue(is_webinar_url('https://my.mts-link.ru/j/1/2'))
    def test_due_boundaries(self):
        items=self.data(); start=datetime.fromisoformat(items[0]['start']); end=datetime.fromisoformat(items[0]['end'])
        self.assertIsNone(due_lesson(items,self.settings,set(),start-timedelta(seconds=1)))
        self.assertIsNotNone(due_lesson(items,self.settings,set(),start))
        self.assertIsNone(due_lesson(items,self.settings,set(),end))
    def test_lead(self):
        self.settings['lead']=2
        self.assertIsNotNone(due_lesson(self.data(),self.settings,set(),datetime.fromisoformat(self.item['start'])-timedelta(minutes=2)))
    def test_exclusions_and_opened(self):
        self.settings['excluded']=['test']
        self.assertIsNone(due_lesson(self.data(),self.settings,set(),datetime.fromisoformat(self.item['start'])))
        self.settings['excluded']=[]
        self.assertIsNone(due_lesson(self.data(),self.settings,{'test'},datetime.fromisoformat(self.item['start'])))
    def test_group_links(self):
        self.item['links'][0]['groups']=['other']
        self.assertFalse(self.data()[0]['eligible'])
    def test_missing_link(self):
        self.item['links']=[]
        self.assertEqual(self.data()[0]['reason'],'Ссылка ещё не опубликована')
    def test_multiple_links(self):
        self.item['links'].append({'url':'https://my.mts-link.ru/j/3/4'})
        self.assertFalse(self.data()[0]['eligible'])
    def test_name(self):
        self.assertEqual(self.settings['group']+' '+self.settings['name'],'000-000 Тестовый Участник')
    def test_unknown_group(self):
        with self.assertRaises(ValueError):validate_settings({'group':'../bad','name':'test'})
    def test_duplicates(self):
        self.assertEqual(len(normalize({'days':[{'items':[self.item,self.item]}]},'000-000')),1)

if __name__=='__main__': unittest.main()
