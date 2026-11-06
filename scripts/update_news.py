#!/usr/bin/env python3
"""HSN newswire: sourced RSS articles, rotating Top 25 coverage, limited football/racing.

Official athletics website articles are NOT represented as social media posts.
Social platforms are not polled without approved API access.
"""
import datetime as dt
import html
import email.utils
import json
import random
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
 ('ESPN', google_news('site:espn.com/mens-college-basketball/ (injury OR transfer OR recruiting OR coach OR upset OR award) when:3d'), 'NCAA NEWS', 'aggregated'),
 ('FOX SPORTS', google_news('site:foxsports.com/college-basketball/ (player OR coach OR injury OR transfer OR upset) when:3d'), 'NCAA NEWS', 'aggregated'),
 ('THE ATHLETIC', google_news('site:nytimes.com/athletic/college-basketball/ (player OR coach OR transfer OR injury) when:3d'), 'NCAA NEWS', 'aggregated'),
 ('KENTUCKY ATHLETICS', google_news('site:ukathletics.com/sports/mens-basketball/ when:3d'), 'KENTUCKY', 'aggregated'),
 ('IOWA ATHLETICS', google_news('site:hawkeyesports.com/sports/mbball/ when:3d'), 'IOWA', 'aggregated'),
 ('KENTUCKY', google_news('"Kentucky" "men basketball" (player OR coach OR injury OR transfer OR recruit OR upset) when:3d'), 'KENTUCKY', 'aggregated'),
 ('IOWA', google_news('"Iowa" "men basketball" (player OR coach OR injury OR transfer OR recruit OR upset) when:3d'), 'IOWA', 'aggregated'),
 ('TOP 25', google_news('"men college basketball" (AP poll OR top 25 OR ranked) (injury OR transfer OR coach OR upset OR player) when:3d'), 'TOP 25', 'aggregated'),
 # Game-day storylines are real published articles, not generated predictions.
 ('KENTUCKY STORYLINES', google_news('("Kentucky basketball" OR "Kentucky Wildcats basketball") ("former team" OR "former coach" OR "player to watch" OR "matchup" OR "return to" OR "career high") when:2d'), 'KENTUCKY', 'aggregated'),
 ('IOWA STORYLINES', google_news('("Iowa basketball" OR "Iowa Hawkeyes basketball") ("former team" OR "former coach" OR "player to watch" OR "matchup" OR "return to" OR "career high") when:2d'), 'IOWA', 'aggregated'),
 ('MEN BASKETBALL STORYLINES', google_news('"men college basketball" ("player to watch" OR "former team" OR "rivalry" OR "breakout" OR "career high" OR "matchup") when:2d'), 'NCAA NEWS', 'aggregated'),
 ('COLLEGE FOOTBALL', google_news('"college football" (playoff OR injury OR coach fired OR transfer OR upset) when:2d'), 'COLLEGE FOOTBALL', 'aggregated'),
 ('NFL', google_news('"NFL" (injury OR trade OR coach OR contract OR playoffs) when:2d'), 'NFL', 'aggregated'),
 ('RACING', google_news('(NASCAR OR NHRA) (driver OR victory OR penalty OR championship OR contract) when:3d'), 'RACING', 'aggregated'),
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
        title = clean_title(re.sub(r'\s+', ' ', element_text(item, 'title')).strip())
        link = element_text(item, 'link').strip()
        date = parsedate(element_text(item, 'pubDate') or element_text(item, '{http://purl.org/dc/elements/1.1/}date'))
        if not title or not link or not date or not (NOW - dt.timedelta(days=7) <= date <= NOW + dt.timedelta(hours=1)):
            continue
        if not link.startswith(('https://', 'http://')):
            continue
        if kind == 'aggregated' and ' - ' in title:
            title = title.rsplit(' - ', 1)[0]
        if CORRUPT.search(title) or len(title) < 18:
            continue
        result.append({'headline': title[:220], 'source': source, 'category': category,
                       'url': link, 'published': date.isoformat(), 'via': kind})
    return result

# Prefer false negatives to presenting football, women's sports or generic athletics
# stories as men's college basketball. Category comes from a dedicated feed,
# never from a stray team nickname or a generic keyword in the headline.
UNRELATED = re.compile(r"\b(women(?:'s|s)?|wbb|wwr|wrestling|volleyball|softball|baseball|field hockey|gymnastics|swimming|soccer|lacrosse|tennis|track and field|cross country|rowing|golf|equestrian|hockey|WNBA|Geno Auriemma|Paige Bueckers|South Carolina women's)\b", re.I)
LOW_VALUE = re.compile(r"\b(game notes?|postgame notes?|preview notes?|press conference|photo gallery|photos of the day|watch live|how to watch|where to watch|broadcast information|tickets? on sale|schedule released|game preview|pregame notes?|media availability|weekly roundup|podcast|highlights video|vs\.?|tip.?off|kickoff time|TV channel|streaming guide|2026.27 rankings predictions|power rankings prediction)\b", re.I)
BASKETBALL = re.compile(r"\b(basketball|hoops|NCAA tournament|March Madness|Final Four|college basketball)\b", re.I)
FOOTBALL = re.compile(r"\b(NFL|football|quarterback|touchdown|wide receiver|running back|linebacker|head coach|general manager|Super Bowl|playoffs?)\b", re.I)
RACING = re.compile(r"\b(NASCAR|NHRA|Cup Series|Xfinity|IndyCar|Formula 1|F1|racing|race|driver|dragster|pit crew|qualifying)\b", re.I)
STORY = re.compile(r"\b(injur\w*|out for|return\w*|suspend\w*|sign\w*|commit\w*|recruit\w*|transfer\w*|portal|coach\w*|hire\w*|fired|resign\w*|win\w*|won|defeat\w*|upset\w*|record|career.high|milestone|award\w*|rank\w*|champion\w*|playoff\w*|penalt\w*|contract\w*|trade\w*|qualif\w*|victor\w*|crash\w*|rival\w*|points|scor\w*|performance|tournament|draft|driver\w*|debut|announc\w*|extension|deal|leads|named|breaks)\b", re.I)
BREAKING = re.compile(r"\b(fired|resigns?|dies|death|suspended|season.ending|out for season|arrested|traded|wins championship|championship clinched)\b", re.I)
CORRUPT = re.compile(r"undefined|\[object Object\]|\bnull\b", re.I)

def clean_title(title):
    # Repair predictable upstream substitutions before filtering, never publish raw 'undefined'.
    title = html.unescape(title)
    title = re.sub(r"([A-Za-z])undefineds\b", r"\1's", title, flags=re.I)
    title = re.sub(r"undefined([^\s]+?)undefined", r"“\1”", title, flags=re.I)
    return re.sub(r"\s+", " ", title).strip()


def quality(item):
    h=item['headline']; cat=item['category']; age=(NOW-parsedate(item['published'])).total_seconds()/3600
    if age>72 or CORRUPT.search(h) or UNRELATED.search(h) or LOW_VALUE.search(h):return None
    # A men's basketball article must say basketball/hoops, or originate from
    # a men's basketball-specific direct feed. A generic team name is not proof.
    basketball_feed = item['source'] in ('CBS SPORTS','NCAA.COM') and item['via']=='direct'
    if cat in ('KENTUCKY','IOWA','NCAA NEWS','TOP 25'):
        if not (BASKETBALL.search(h) or basketball_feed):return None
        if FOOTBALL.search(h) and not BASKETBALL.search(h):return None
        if RACING.search(h) and not BASKETBALL.search(h):return None
    elif cat=='NFL':
        if not re.search(r"\b(NFL|football|quarterback|Super Bowl|team's general manager)\b",h,re.I):return None
    elif cat=='COLLEGE FOOTBALL':
        if not re.search(r"\b(college football|football|CFP|quarterback|touchdown)\b",h,re.I):return None
    elif cat=='RACING':
        if not RACING.search(h):return None
    else:return None
    if not STORY.search(h) and not re.search(r'\b(former team|former coach|player to watch|matchup|rivalry|breakout|faces former|returns to|storyline)\b',h,re.I):return None
    score=50+(28 if cat in ('KENTUCKY','IOWA') else 20 if cat=='TOP 25' else 12 if cat=='NCAA NEWS' else 0)
    score+=(10 if re.search(r'\b(former team|former coach|player to watch|matchup|rivalry|breakout|faces former|returns to|career.high)\b',h,re.I) else 0)
    score+=(18 if re.search(r"\b(injur\w*|transfer\w*|coach\w*|recruit\w*|champion\w*|upset\w*|driver\w*|contract\w*|traded|suspend\w*)\b",h,re.I) else 6)
    score+=max(0,24-age/3)
    item['score']=round(score,1)
    item['breaking']=bool(BREAKING.search(h) and age<8 and cat in ('NFL','COLLEGE FOOTBALL','RACING','KENTUCKY','IOWA','NCAA NEWS','TOP 25'))
    return item

def select_diverse(items, limit=45):
    # Soft category mix, not a rigid Kentucky/Iowa alternating pattern.
    # Randomize among comparably scored items while avoiding consecutive repeats.
    groups = {}
    for item in items:
        groups.setdefault(item['category'], []).append(item)
    for group in groups.values():
        group.sort(key=lambda a: a['score'], reverse=True)
        reordered = []
        while group:
            batch = group[:5]
            del group[:5]
            random.shuffle(batch)
            reordered.extend(batch)
        group.extend(reordered)
    caps = {'KENTUCKY': 9, 'IOWA': 9, 'TOP 25': 15, 'NCAA NEWS': 18,
            'NFL': 4, 'COLLEGE FOOTBALL': 4, 'RACING': 3}
    chosen, counts, other = [], {}, 0
    while len(chosen) < limit:
        options = []
        for category, group in groups.items():
            if not group or counts.get(category, 0) >= caps.get(category, 4):
                continue
            is_other = category in ('NFL', 'COLLEGE FOOTBALL', 'RACING')
            if is_other and other >= max(1, (len(chosen) + 1) // 5):
                continue
            article = group[0]
            score = article['score'] + random.uniform(0, 28)
            if chosen and chosen[-1]['category'] == category:
                score -= 38
            if chosen and chosen[-1]['source'] == article['source']:
                score -= 20
            if category in ('TOP 25', 'NCAA NEWS'):
                score += 10
            options.append((score, category))
        if not options:
            break
        _, category = max(options)
        article = groups[category].pop(0)
        chosen.append(article)
        counts[category] = counts.get(category, 0) + 1
        if category in ('NFL', 'COLLEGE FOOTBALL', 'RACING'):
            other += 1
    return chosen

def main():
    feeds = list(FEEDS)
    top25 = get_top25()
    # Targeted ranked-team articles plus sourced game-day player and coaching storylines.
    # These are search results from publishers, NOT Google's AI Overview text.
    # Targeted official athletics-site searches for AP-ranked programs, if poll available.
    # One feed per team is expensive: batch 5 names per search to cover all 25.
    for start in range(0, len(top25), 5):
        names = top25[start:start+5]
        terms = ' OR '.join('"' + name.replace('"','') + '"' for name in names)
        feeds.append(('AP TOP 25 TEAMS', google_news('(' + terms + ') \"men college basketball\" (player OR coach OR injury OR transfer) when:3d'), 'TOP 25', 'aggregated'))
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
            selected=quality(item)
            if selected:
                seen.add(key)
                unique.append(selected)
    chosen=select_diverse(unique)
    if not chosen:
        print('No high-quality recent headlines; writing an empty feed rather than misleading filler')
    OUTPUT.write_text(json.dumps({'updated': NOW.isoformat(), 'sources': sorted(set(sources)),
                                  'ap_top25_teams': top25, 'articles': chosen},
                                 ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Saved', len(chosen), 'articles; AP poll teams:', len(top25), '; source warnings:', errors)

if __name__ == '__main__':
    main()
