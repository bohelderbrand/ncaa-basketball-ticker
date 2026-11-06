#!/usr/bin/env python3
"""Build a sourced, deduplicated basketball headline cache for HSN GitHub Pages."""
import datetime as dt
import email.utils
import json
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'hsn-news.json'
UTC = dt.timezone.utc
NOW = dt.datetime.now(UTC)
HEADERS = {'User-Agent': 'HSN-College-Basketball-News/1.0 (RSS reader)'}

def google_news(query):
    return 'https://news.google.com/rss/search?' + urllib.parse.urlencode({'q':query,'hl':'en-US','gl':'US','ceid':'US:en'})

# Original publisher RSS feeds, plus targeted Google News search feeds where a
# publisher or school does not offer a verified public RSS endpoint.
FEEDS = [
 ('CBS SPORTS','https://www.cbssports.com/rss/headlines/college-basketball/','direct'),
 ('NCAA.COM','https://www.ncaa.com/news/basketball-men/d1/rss.xml','direct'),
 ('FOX SPORTS',google_news('site:foxsports.com/college-basketball college basketball when:7d'),'aggregated'),
 ('NBC SPORTS',google_news('site:nbcsports.com college basketball when:7d'),'aggregated'),
 ('KENTUCKY ATHLETICS',google_news('site:ukathletics.com basketball Kentucky when:7d'),'aggregated'),
 ('IOWA ATHLETICS',google_news('site:hawkeyesports.com basketball Iowa when:7d'),'aggregated'),
 ('THE ATHLETIC',google_news('site:nytimes.com/athletic/college-basketball when:7d'),'aggregated'),
 ('COLLEGE BASKETBALL REPORTERS',google_news('college basketball Jon Rothstein OR Jeff Goodman when:3d'),'aggregated'),
]

def text(el, name):
    n=el.find(name)
    return ''.join(n.itertext()).strip() if n is not None else ''

def parsedate(raw):
    try:
        value=email.utils.parsedate_to_datetime(raw)
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    except Exception:
        try:return dt.datetime.fromisoformat(raw.replace('Z','+00:00')).astimezone(UTC)
        except Exception:return None

def fetch_feed(source,url,kind):
    req=urllib.request.Request(url,headers=HEADERS)
    with urllib.request.urlopen(req,timeout=18) as res:
        data=res.read(2_000_000)
    root=ET.fromstring(data)
    result=[]
    for item in root.findall('.//item')[:35]:
        title=re.sub(r'\s+',' ',text(item,'title')).strip()
        link=text(item,'link').strip()
        date=parsedate(text(item,'pubDate') or text(item,'{http://purl.org/dc/elements/1.1/}date'))
        if not title or not link or not date or not (NOW-dt.timedelta(days=7)<=date<=NOW+dt.timedelta(hours=1)):
            continue
        if not link.startswith(('https://','http://')):continue
        # Google News titles often end with a publisher name; keep source labels distinct.
        if kind=='aggregated' and ' - ' in title:title=title.rsplit(' - ',1)[0]
        if len(title)<18:continue
        result.append({'headline':title[:220], 'source':source, 'url':link,
                       'published':date.isoformat(), 'via':kind})
    return result

def main():
    all_items=[];errors=[];sources=[]
    for name,url,kind in FEEDS:
        try:
            items=fetch_feed(name,url,kind)
            if items:sources.append(name);all_items.extend(items)
            else:errors.append(name+': no recent items')
        except Exception as e:errors.append(name+': '+str(e)[:110])
    # Preserve the last good feed if all remote requests fail.
    if not all_items:
        print('No feeds available; preserving previous file. '+ '; '.join(errors))
        return
    seen=set();unique=[]
    for x in sorted(all_items,key=lambda i:i['published'],reverse=True):
        key=re.sub('[^a-z0-9]','',x['headline'].lower())[:100]
        if key in seen:continue
        seen.add(key);unique.append(x)
    # Do not let one publisher dominate. All items remain traceable to original links.
    counts={};chosen=[]
    for x in unique:
        if counts.get(x['source'],0)>=14:continue
        counts[x['source']]=counts.get(x['source'],0)+1
        chosen.append(x)
        if len(chosen)>=75:break
    data={'updated':NOW.isoformat(),'sources':sources,'articles':chosen}
    OUTPUT.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Saved',len(chosen),'stories from',len(sources),'sources. Warnings:',errors)

if __name__=='__main__':main()
