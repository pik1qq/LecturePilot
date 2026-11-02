"""Official Moscow Poly schedule adapter. No guessed webinar URLs."""
import hashlib
import json
import re
import time
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
from core import is_webinar_url

MOSCOW = ZoneInfo('Europe/Moscow')
TIMES = {
  0: [('09:00','10:30'),('10:40','12:10'),('12:20','13:50'),('14:30','16:00'),('16:10','17:40'),('17:50','19:20'),('19:30','21:00')],
  1: [('09:00','10:30'),('10:40','12:10'),('12:20','13:50'),('14:30','16:00'),('16:10','17:40'),('18:20','19:40'),('19:50','21:10')],
  2: [('09:00','10:30'),('10:40','12:10'),('12:20','13:50'),('14:30','16:00'),('16:10','17:40'),('18:30','20:00'),('20:10','21:40')],
}
HEADERS={'User-Agent':'Mozilla/5.0 (compatible; LecturePilot/1.7)', 'X-Requested-With':'XMLHttpRequest','Referer':'https://rasp.dmami.ru/','Accept':'application/json, text/javascript, */*; q=0.01'}
class Links(HTMLParser):
    def __init__(self): super().__init__(); self.urls=[]
    def handle_starttag(self,tag,attrs):
        if tag.lower()=='a':
            for key,value in attrs:
                if key.lower()=='href' and value: self.urls.append(value)

class GroupNotFound(ValueError): pass

def official_group(group, session=0, opener=urlopen):
    url='https://rasp.dmami.ru/site/group?'+urlencode({'group':group,'session':session,'_':str(time.time_ns())})
    with opener(Request(url,headers=HEADERS),timeout=15) as r: raw=r.read(5_000_001)
    if len(raw)>5_000_000: raise ValueError('Ответ официального расписания слишком большой')
    data=json.loads(raw)
    if not isinstance(data,dict): raise ValueError('Неожиданный ответ официального расписания')
    if data.get('status')=='error':
        message=str(data.get('message') or '')
        if 'не нашлось расписание' in message.casefold() or 'не готово расписание' in message.casefold(): raise GroupNotFound('Официальное расписание для группы не найдено')
        raise ValueError('Ошибка официального расписания: '+message[:120])
    if data.get('status')!='ok': raise ValueError('Неожиданный ответ официального расписания')
    if not isinstance(data.get('group'),dict) or data['group'].get('title')!=group or not isinstance(data.get('grid'),dict): raise ValueError('Неожиданный ответ официального расписания')
    return data

def official_groups(query, opener=urlopen):
    with opener(Request('https://rasp.dmami.ru/?_='+str(time.time_ns()),headers=HEADERS),timeout=15) as r: text=r.read(3_000_001).decode('utf-8')
    if len(text)>3_000_000: raise ValueError('Каталог групп слишком большой')
    match=re.search(r'var\s+globalListGroups\s*=\s*(\{.*?\})\.groups',text,re.S)
    if not match: raise ValueError('Не найден каталог групп')
    groups=json.loads(match.group(1)).get('groups')
    if not isinstance(groups,dict): raise ValueError('Некорректный каталог групп')
    return sorted((k for k in groups if query.casefold() in k.casefold()), key=str.casefold)[:40]

def parse_official(data, group, first_day, last_day):
    info=data['group']; evening=info.get('evening')
    if evening not in TIMES: raise ValueError('Неизвестное расписание времени пар')
    try: start_range=date.fromisoformat(info['dateFrom']); end_range=date.fromisoformat(info['dateTo'])
    except (KeyError, TypeError, ValueError): raise ValueError('Не указан период официального расписания')
    if start_range>end_range: raise ValueError('Некорректный период расписания')
    session=data.get('isSession'); grid=data['grid']
    if not isinstance(session,bool): raise ValueError('Неизвестный формат периода')
    result=[]
    for offset in range((last_day-first_day).days+1):
        day=first_day+timedelta(days=offset)
        if not start_range<=day<=end_range: continue
        slots=grid.get(day.isoformat() if session else str(day.isoweekday()),{})
        if not isinstance(slots,dict): raise ValueError('Некорректные занятия')
        for slot, items in slots.items():
            try: n=int(slot)
            except ValueError: raise ValueError('Неизвестный номер пары')
            if not 1<=n<=7 or not isinstance(items,list): raise ValueError('Неизвестное время пары')
            st,en=TIMES[evening][n-1]; start=datetime.fromisoformat(day.isoformat()+'T'+st+':00').replace(tzinfo=MOSCOW); end=datetime.fromisoformat(day.isoformat()+'T'+en+':00').replace(tzinfo=MOSCOW)
            for item in items:
                if not isinstance(item,dict): raise ValueError('Некорректное занятие')
                if item.get('week') not in (None,''): raise ValueError('Неизвестный тип чередования недель')
                try: df=date.fromisoformat(item['df']);dt=date.fromisoformat(item['dt'])
                except (KeyError,TypeError,ValueError): raise ValueError('У занятия не указан период')
                if not df<=day<=dt: continue
                subject=str(item.get('sbj','Занятие'));kind=str(item.get('type') or '');teacher=str(item.get('teacher') or '')
                venue=str(item.get('location') or '')
                urls=[]
                if item.get('e_link'): urls.append(str(item['e_link']))
                for room in item.get('auditories',[]):
                    parser=Links(); parser.feed(str(room.get('title','')) if isinstance(room,dict) else ''); urls.extend(parser.urls)
                # Only explicit links on Webinar events; never turn LMS/other events into webinars.
                urls=sorted(set(u for u in urls if is_webinar_url(u))) if venue.casefold()=='webinar' else []
                link=urls[0] if len(urls)==1 else None
                identity='|'.join((group,start.isoformat(),end.isoformat(),subject,kind,teacher))
                uid='official:'+hashlib.sha256(identity.encode()).hexdigest()[:32]
                reason='' if link else ('Несколько ссылок — нужен ручной выбор' if len(urls)>1 else 'Ссылка ещё не опубликована' if venue.casefold()=='webinar' else 'Онлайн-курс — не вебинар' if venue.casefold() in ('online курс','сдо (lms)') else 'Очное занятие')
                result.append({'id':uid,'start':start.isoformat(),'end':end.isoformat(),'subject':subject,'kind':kind,'teacher':teacher,'subgroup':None,'url':link,'eligible':bool(link),'reason':reason})
    return result,(start_range,end_range)

def official_schedule(group,first_day,opener=urlopen):
    last=first_day+timedelta(days=13)
    primary=official_group(group,0,opener)
    datasets=[primary]
    if not primary['isSession']:
        try:
            other=official_group(group,1,opener)
            if other.get('isSession'): datasets.append(other)
        except GroupNotFound: pass
    lessons=[]; periods=[]
    for data in datasets:
        got,period=parse_official(data,group,first_day,last);lessons.extend(got);periods.append(period)
    covered={first_day+timedelta(days=i) for i in range(14) if any(a<=first_day+timedelta(days=i)<=b for a,b in periods)}
    if first_day not in covered: raise ValueError('Официальный источник не содержит расписание на сегодня')
    # Never claim freshness beyond a gap in source coverage.
    valid_until=first_day
    while valid_until+timedelta(days=1) in covered: valid_until+=timedelta(days=1)
    unique={}
    for x in lessons:
        if date.fromisoformat(x['start'][:10])>valid_until: continue
        if x['id'] in unique and unique[x['id']] != x: raise ValueError('Неоднозначные данные занятия в официальном расписании')
        unique[x['id']]=x
    return sorted(unique.values(),key=lambda x:(x['start'],x['id'])),valid_until
