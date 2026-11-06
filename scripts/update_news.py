#!/usr/bin/env python3
"""HSN newswire: sourced RSS articles, rotating Top 25 coverage, limited football/racing.

Official athletics website articles are NOT represented as social media posts.
Social platforms are not polled without approved API access.
"""
import datetime as dt
import email.utils
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'hsn-news.json'
UTC = dt.timezone.utc
NOW = dt.datetime.now(UTC)
HEADERS = {'User-Agent': 'HSN-News/1.1 (RSS reader)'}

def google_news(query):
    return 'https://news.google.com/rss/search?' + urllib.parse.urlencode({'q': query, 'hl': 'en-US', 'gl': 'US', 'ceid': 'US:en'})

# Obtain AP Top 25 team names from a rankings feed where possible; never label
# a team as ranked unless that feed actually provides its current poll position.
RANKINGS_URL = 'https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/rankings'

def get_top25():
    try:
        req = urllib.request.Request(RANKINGS_URL, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=12) as res:
            data = json.load(res)
        polls = data.get('rankings', [])
        poll = next((p for p in polls if 'associated press' in str(p.get('name','')).lower() or str(p.get('name','')).lower().startswith('ap top')), None)
        if poll is None:
            return []
        teams = []
        for entry in poll.get('ranks', []):
            rank = entry.get('current') or entry.get('rank')
            team = entry.get('team') or {}
            name = team.get('displayName') or team.get('name') or ''
            if name and rank and 1 <= int(rank) <= 25:
                teams.append((int(rank), name))
        return [name for _, name in sorted(teams)][:25]
    except Exception as exc:
        print('AP ranking retrieval unavailable:', str(exc)[:140])
        return []

FEEDS = [
 ('CBS SPORTS', 'https://www.cbssports.com/rss/headlines/college-basketball/', 'NCAA NEWS', 'direct'),
 ('NCAA.COM', 'https://www.ncaa.com/news/basketball-men/d1/rss.xml', 'NCAA NEWS', 'direct'),
 ('ESPN', google_news('site:espn.com/mens-college-basketball college basketball when:5d'), 'NCAA NEWS', 'aggregated'),
 ('FOX SPORTS', google_news('site:foxsports.com/college-basketball college basketball when:5d'), 'NCAA NEWS', 'aggregated'),
 ('NBC SPORTS', google_news('site:nbcsports.com college basketball when:5d'), 'NCAA NEWS', 'aggregated'),
 ('THE ATHLETIC', google_news('site:nytimes.com/athletic/college-basketball when:5d'), 'NCAA NEWS', 'aggregated'),
 ('KENTUCKY ATHLETICS', google_news('site:ukathletics.com (basketball OR Wildcats) when:5d'), 'KENTUCKY', 'aggregated'),
 ('IOWA ATHLETICS', google_news('site:hawkeyesports.com (basketball OR Hawkeyes) when:5d'), 'IOWA', 'aggregated'),
 ('COLLEGE BASKETBALL REPORTERS', google_news('college basketball (Jon Rothstein OR Jeff Goodman) when:3d'), 'NCAA NEWS', 'aggregated'),
 ('TOP 25', google_news('AP top 25 college basketball ranked teams injury upset basketball when:3d'), 'TOP 25', 'aggregated'),
 ('COLLEGE FOOTBALL', google_news('college football top 25 playoffs breaking news when:2d'), 'COLLEGE FOOTBALL', 'aggregated'),
 ('NFL', google_news('NFL breaking news trades injuries when:2d'), 'NFL', 'aggregated'),
 ('RACING', google_news('(NASCAR OR NHRA) racing breaking news when:4d'), 'RACING', 'aggregated'),
]

def element_text(el, name):
    node = el.find(name)
    return ''.join(node.itertext()).strip() if node is not None else ''

def parsedate(raw):
    try:
        value = email.utils.parsedate_to_datetime(raw)
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    except Exception:
        try:
            return dt.datetime.fromisoformat(raw.replace('Z', '+00:00')).astimezone(UTC)
        except Exception:
            return None

def fetch_feed(source, url, category, kind):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=18) as res:
        root = ET.fromstring(res.read(2_000_000))
    result = []
    for item in root.findall('.//item')[:45]:
        title = re.sub(r'\s+', ' ', element_text(item, 'title')).strip()
        link = element_text(item, 'link').strip()
        date = parsedate(element_text(item, 'pubDate') or element_text(item, '{http://purl.org/dc/elements/1.1/}date'))
        if not title or not link or not date or not (NOW - dt.timedelta(days=7) <= date <= NOW + dt.timedelta(hours=1)):
            continue
        if not link.startswith(('https://', 'http://')):
            continue
        if kind == 'aggregated' and ' - ' in title:
            title = title.rsplit(' - ', 1)[0]
        if len(title) < 18:
            continue
        result.append({'headline': title[:220], 'source': source, 'category': category,
                       'url': link, 'published': date.isoformat(), 'via': kind})
    return result

def main():
    feeds = list(FEEDS)
    top25 = get_top25()
    # Targeted official athletics-site searches for AP-ranked programs, if poll available.
    # One feed per team is expensive: batch 5 names per search to cover all 25.
    for start in range(0, len(top25), 5):
        names = top25[start:start+5]
        terms = ' OR '.join('"' + name.replace('"','') + '"' for name in names)
        feeds.append(('AP TOP 25 TEAMS', google_news('(' + terms + ') college basketball when:3d'), 'TOP 25', 'aggregated'))
    articles, errors, sources = [], [], []
    for source, url, category, kind in feeds:
        try:
            items = fetch_feed(source, url, category, kind)
            if items:
                sources.append(source)
                articles.extend(items)
            else:
                errors.append(source + ': no recent items')
        except Exception as exc:
            errors.append(source + ': ' + str(exc)[:110])
    if not articles:
        print('All feeds unavailable; retaining last successful news file:', errors)
        return
    seen, unique = set(), []
    for item in sorted(articles, key=lambda x: x['published'], reverse=True):
        key = re.sub('[^a-z0-9]', '', item['headline'].lower())[:100]
        if key not in seen:
            seen.add(key)
            unique.append(item)
    # Cap non-basketball content to ~20%, with basketball as the default.
    limits = {'COLLEGE FOOTBALL': 6, 'NFL': 5, 'RACING': 4, 'KENTUCKY': 12, 'IOWA': 12,
              'TOP 25': 24, 'NCAA NEWS': 40}
    counts, chosen = {}, []
    for item in unique:
        cat = item['category']
        if counts.get(cat, 0) >= limits.get(cat, 8):
            continue
        counts[cat] = counts.get(cat, 0) + 1
        chosen.append(item)
        if len(chosen) >= 100:
            break
    OUTPUT.write_text(json.dumps({'updated': NOW.isoformat(), 'sources': sorted(set(sources)),
                                  'ap_top25_teams': top25, 'articles': chosen},
                                 ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Saved', len(chosen), 'articles; AP poll teams:', len(top25), '; source warnings:', errors)

if __name__ == '__main__':
    main()
