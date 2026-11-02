import copy, io, json, unittest
from datetime import date, timedelta
from unittest.mock import patch
import app
from schedule_sources import parse_official, official_schedule, official_group, official_groups

def item(location='Webinar', link='https://my.mts-link.ru/j/1/2', **kwargs):
    return {'sbj':'Лекция','teacher':'Преподаватель','type':'Лекция','location':location,'df':'2026-10-01','dt':'2026-12-31','week':'','e_link':None,'auditories':[{'title':f'<a href="{link}">Webinar</a>'}],**kwargs}
def data(group='000-000',evening=0):
    return {'status':'ok','isSession':False,'group':{'title':group,'dateFrom':'2026-10-01','dateTo':'2026-12-31','evening':evening},'grid':{'1':{'1':[item()]}}}
def response(d): return io.BytesIO(json.dumps(d).encode())
class SourceTests(unittest.TestCase):
    def test_weekly_dates_and_webinar(self):
        lessons,cover=parse_official(data(),'000-000',date(2026,11,2),date(2026,11,15))
        self.assertEqual([x['start'][:10] for x in lessons],['2026-11-02','2026-11-09'])
        self.assertTrue(all(x['eligible'] for x in lessons)); self.assertEqual(cover[1],date(2026,12,31))
    def test_no_url_guessing_and_reject_evil(self):
        d=data(); d['grid']['1']['1']=[item(link='https://my.mts-link.ru.evil.example/j/1'),item('Online курс'),item(link='https://webinar.ru/j/a',e_link='https://my.mts-link.ru/j/b')]
        lessons,_=parse_official(d,'000-000',date(2026,11,2),date(2026,11,2))
        self.assertTrue(all(not x['eligible'] for x in lessons))
    def test_evening_times(self):
        d=data(evening=1);d['grid']={'1':{'6':[item()]}}
        lessons,_=parse_official(d,'000-000',date(2026,11,2),date(2026,11,2)); self.assertIn('T18:20',lessons[0]['start'])
    def test_session_exact_dates(self):
        d=data();d['isSession']=True;d['grid']={'2026-11-02':{'2':[item()]}}
        lessons,_=parse_official(d,'000-000',date(2026,11,2),date(2026,11,15));self.assertEqual(len(lessons),1);self.assertIn('T10:40',lessons[0]['start'])
    def test_unclear_week_rejected(self):
        d=data(); d['grid']['1']['1'][0]['week']='odd'
        with self.assertRaises(ValueError):parse_official(d,'000-000',date(2026,11,2),date(2026,11,2))
    def test_period_missing_today_rejected(self):
        def opener(req,timeout):return response(data()) if 'session=0' in req.full_url else response({'status':'error','message':'Не нашлось расписание для группы'})
        with self.assertRaises(ValueError):official_schedule('000-000',date(2027,1,1),opener)
    def test_partial_coverage(self):
        d=data();d['group']['dateTo']='2026-11-06'
        def opener(req,timeout):return response(d) if 'session=0' in req.full_url else response({'status':'error','message':'Не нашлось расписание для группы'})
        lessons,until=official_schedule('000-000',date(2026,11,2),opener);self.assertEqual(until,date(2026,11,6));self.assertEqual(len(lessons),1)
    def test_ajax_request_and_other_group(self):
        def opener(req,timeout):
            self.assertIn('group=262-611',req.full_url);self.assertIn('_=',req.full_url);self.assertEqual(req.get_header('X-requested-with'),'XMLHttpRequest');return response(data('262-611'))
        self.assertEqual(official_group('262-611',0,opener)['group']['title'],'262-611')
    def test_group_list(self):
        html=b'<script>var globalListGroups = {"groups":{"000-000":false,"262-611":true}}.groups;</script>'
        self.assertEqual(official_groups('262',lambda req,timeout:io.BytesIO(html)),['262-611'])
    def test_duplicate_identity_with_conflicting_urls_rejected(self):
        d=data();d['grid']['1']['1'].append(item(link='https://my.mts-link.ru/j/different'))
        def opener(req,timeout):return response(d) if 'session=0' in req.full_url else response({'status':'error','message':'Не нашлось расписание для группы'})
        with self.assertRaises(ValueError):official_schedule('000-000',date(2026,11,2),opener)
    def test_failure_of_second_session_not_silently_ignored(self):
        def opener(req,timeout):
            if 'session=0' in req.full_url:return response(data())
            raise OSError('network')
        with self.assertRaises(OSError):official_schedule('000-000',date(2026,11,2),opener)

class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.old=copy.deepcopy(app.state)
        app.state.update(settings={**app.DEFAULTS,'group':'000-000','name':'Тест'},source=None,coverage_until=None,source_review=False,lessons=[],opened=[],opened_intervals=[],active=None,armed=False,resume_pending=False,updated=None)
    def tearDown(self): app.state.clear();app.state.update(self.old)
    def test_fallback_and_return_to_primary_requires_review(self):
        d=data(); today=app.now().date();d['group']['dateFrom']=(today-timedelta(days=2)).isoformat();d['group']['dateTo']=(today+timedelta(days=30)).isoformat();d['grid']={}
        def open_(req,timeout):
            url=req.full_url if hasattr(req,'full_url') else req
            if 'mosrasp.ru' in url:raise OSError('offline')
            return response(d if 'session=0' in url else {'status':'error','message':'Не нашлось расписание для группы'})
        with patch('app.urlopen',side_effect=open_),patch('app.log'):
            app.refresh()
        self.assertEqual(app.state['source'],'rasp.dmami.ru'); self.assertTrue(app.state['fetch_ok'])
        app.state['armed']=True
        with patch('app.urlopen',return_value=response({'days':[]})),patch('app.log'):
            app.refresh()
        self.assertEqual(app.state['source'],'mosrasp.ru');self.assertFalse(app.state['armed']);self.assertTrue(app.state['source_review'])
    def test_both_offline_preserves_old(self):
        app.state['lessons']=[{'id':'keep'}]
        with patch('app.urlopen',side_effect=OSError('offline')),patch('app.log'):app.refresh()
        self.assertEqual(app.state['lessons'],[{'id':'keep'}]);self.assertFalse(app.state['fetch_ok'])
    def test_active_window_defers_source_change(self):
        app.state.update(source='rasp.dmami.ru',active={'id':'active'},armed=True,lessons=[{'id':'keep'}])
        with patch('app.urlopen',return_value=response({'days':[]})),patch('app.log'):app.refresh()
        self.assertEqual(app.state['source'],'rasp.dmami.ru');self.assertEqual(app.state['lessons'],[{'id':'keep'}]);self.assertTrue(app.state['armed'])
if __name__=='__main__':unittest.main()
