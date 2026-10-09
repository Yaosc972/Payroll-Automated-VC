from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import urljoin, urlsplit, urlunsplit
from concurrent.futures import ThreadPoolExecutor

import httpx
from bonus_platform.engine.admin_store import _connect

SOURCES = json.loads(Path(__file__).with_name('sources.json').read_text())
SCHEMA = '''
CREATE TABLE IF NOT EXISTS policy_articles (
 id VARCHAR(64) PRIMARY KEY, source_id VARCHAR(80) NOT NULL,
 title TEXT NOT NULL, url TEXT NOT NULL, published VARCHAR(10) NOT NULL,
 fetched_at VARCHAR(32) NOT NULL
);
CREATE TABLE IF NOT EXISTS policy_source_checks (
 id VARCHAR(80) PRIMARY KEY, checked_at VARCHAR(32) NOT NULL,
 success_at VARCHAR(32) NOT NULL, state VARCHAR(24) NOT NULL,
 error VARCHAR(80) NOT NULL
);
'''


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def migrate(db_path=None):
    """Explicit deployment migration; never called from a web request."""
    with _connect(db_path) as db:
        db.executescript(SCHEMA)
        db.commit()


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.links, self.meta, self.active = [], {}, None
        # Government CMS list pages embed article anchors inside CDATA records.
        self.feed(html)
        for record in re.findall(r'<!\[CDATA\[(.*?)\]\]>', html, re.S):
            fragment = Page(record)
            self.links.extend(fragment.links)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'meta':
            self.meta[(attrs.get('name') or attrs.get('property') or '').lower()] = attrs.get('content', '')
        if tag == 'a':
            self.active = [attrs.get('href', ''), attrs.get('title', ''), []]

    def handle_data(self, data):
        if self.active is not None:
            self.active[2].append(data)

    def handle_endtag(self, tag):
        if tag == 'a' and self.active is not None:
            href, title, fragments = self.active
            self.links.append((href, ' '.join((title or ''.join(fragments)).split())))
            self.active = None


def article_url(source, href):
    parsed = urlsplit(urljoin(source['url'], href))
    if parsed.hostname != urlsplit(source['url']).hostname or parsed.scheme not in {'http', 'https'} or parsed.username or parsed.password:
        return None
    if not re.fullmatch(source['articlePattern'], parsed.path):
        return None
    return urlunsplit(('https', parsed.netloc, parsed.path, '', ''))


def relevant_title(title):
    """Conservative title-based eligibility for enterprise HR, not legal interpretation."""
    if any(word in title for word in (
        '采购', '招聘', '招标', '中标', '送达', '放假', '暂停办理',
        '责令限期', '面试', '录用', '办公地址', '满意度调查', '已失效', '已废止',
        '医药购销', '定点零售药店', '医药代表', '儿童用药', '药品价格',
        '药品目录', '医用设备', '医用耗材', '医疗服务价格', '病组', '病种分值',
        '病理云', '编码规则', '基金监督检查', '基金监管', '制定计划项目表',
        '征求意见', '医疗机构制剂', '诊疗项目', '中药配方颗粒',
    )):
        return False
    if '城乡居民' in title and '企业职工' not in title:
        return False
    return any(topic in title for topic in (
        '缴存', '缴费', '费率', '缴纳', '缴款', '补缴', '缓缴',
        '增员', '减员', '参保登记', '参保缴', '参加基本医疗保险',
        '转移接续', '稳岗返还', '稳岗补贴', '失业保险', '退休', '养老金',
        '生育津贴', '生育保险', '工伤认定', '劳动能力鉴定', '工伤保险待遇',
        '个人账户跨省共济', '住房公积金管理条例', '住房公积金管理办法',
        '企业职工基本养老保险', '职工基本医疗保险待遇',
    ))


def extract_links(source, html):
    results = {}
    for href, title in Page(html).links:
        url = article_url(source, href)
        if not url or len(title) < 12 or not relevant_title(title):
            continue
        if source['category'] != '医保' and not any(word in title for word in ('公积金', '社会保险', '养老保险', '工伤保险', '失业保险', '缴费', '缴存')):
            continue
        results[url] = title
    return list(results.items())[:20]


def publication(meta):
    for key in ('pubdate', 'publishdate', 'publishtime', 'publication_date', 'dc.date', 'article:published_time'):
        match = re.search(r'(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})', meta.get(key, ''))
        if match:
            try:
                return date(*map(int, match.groups())).isoformat()
            except ValueError:
                continue
    return ''


def fetch_html(client, url):
    # Fixed registry hosts only, no arbitrary user URLs or cross-host redirects.
    with client.stream('GET', url) as response:
        response.raise_for_status()
        if 'html' not in response.headers.get('content-type', '').lower():
            raise ValueError('unexpected_content')
        data = bytearray()
        for chunk in response.iter_bytes():
            data.extend(chunk)
            if len(data) > 2_000_000:
                raise ValueError('response_too_large')
        encoding = response.encoding or 'utf-8'
        if re.search(br'charset\s*=\s*["\x27]?gb', data[:4096], re.I):
            encoding = 'gb18030'
        return data.decode(encoding, errors='replace')


def collect(source, fetcher=None):
    rows, failures = [], 0
    try:
        with httpx.Client(timeout=8, follow_redirects=False, headers={'User-Agent': 'SigmaPolicyReader/1.0'}) as client:
            fetch = fetcher or (lambda url: fetch_html(client, url))
            listing = fetch(source['url'])
            links = extract_links(source, listing)
            if not links:
                if any(article_url(source, href) for href, _ in Page(listing).links):
                    return [], 'ok', ''
                raise ValueError('no_article_links')
            for url, title in links:
                try:
                    meta = Page(fetch(url)).meta
                    title = meta.get('articletitle') or title
                    if not relevant_title(title):
                        continue
                    published = publication(meta)
                    if not published:
                        raise ValueError('publication_missing')
                    rows.append({'id': sha256(url.encode()).hexdigest(), 'source_id': source['id'], 'title': title[:500], 'url': url, 'published': published, 'fetched_at': now()})
                except (httpx.HTTPError, ValueError):
                    failures += 1
        return rows, ('error' if failures and not rows else 'partial' if failures else 'ok'), ('article_fetch_failed' if failures else '')
    except (httpx.HTTPError, ValueError) as exc:
        error = f'HTTP {exc.response.status_code}' if isinstance(exc, httpx.HTTPStatusError) else str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        return [], 'error', error


def upsert(db, table, values):
    columns = list(values)
    fields = ', '.join(columns)
    placeholders = ', '.join('?' for _ in columns)
    if db.backend == 'mysql':
        tail = 'ON DUPLICATE KEY UPDATE ' + ', '.join(f'{c}=VALUES({c})' for c in columns if c != 'id')
    else:
        tail = 'ON CONFLICT(id) DO UPDATE SET ' + ', '.join(f'{c}=excluded.{c}' for c in columns if c != 'id')
    db.execute(f'INSERT INTO {table} ({fields}) VALUES ({placeholders}) {tail}', tuple(values.values()))


def refresh(db_path=None, sources=None, collector=collect):
    if sources is None:
        # Scheduled calls rotate through the oldest checks in bounded batches.
        # Explicit CLI source lists can still run a full initial import.
        with _connect(db_path) as db:
            checks = {r['id']: r['checked_at'] for r in db.execute('SELECT id, checked_at FROM policy_source_checks').fetchall()}
        sources = sorted(SOURCES, key=lambda s: (checks.get(s['id'], ''), s['id']))[:8]
    # Bound per-host requests and keep database writes sequential.
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(collector, sources))
    report = []
    for source, (rows, state, error) in zip(sources, results):
        stamp = now()
        with _connect(db_path) as db:
            old = db.execute('SELECT success_at FROM policy_source_checks WHERE id=?', (source['id'],)).fetchone()
            for row in rows:
                upsert(db, 'policy_articles', row)
            upsert(db, 'policy_source_checks', {
                'id': source['id'], 'checked_at': stamp,
                'success_at': stamp if state == 'ok' else (dict(old)['success_at'] if old else ''),
                'state': state, 'error': error,
            })
            db.commit()
        report.append({'id': source['id'], 'state': state, 'articles': len(rows), 'error': error})
    return report


def query(q='', offset=0, limit=20, db_path=None, category=''):
    with _connect(db_path) as db:
        rows = [dict(r) for r in db.execute('SELECT * FROM policy_articles ORDER BY published DESC, id').fetchall()]
        checks = {r['id']: dict(r) for r in db.execute('SELECT * FROM policy_source_checks').fetchall()}
    sources = [{**s, **checks.get(s['id'], {'state': 'pending', 'checked_at': '', 'success_at': '', 'error': ''})} for s in SOURCES]
    by_id = {s['id']: s for s in sources}
    items = []
    today = datetime.now(timezone(timedelta(hours=8))).date()
    cutoff = today - timedelta(days=180)
    for row in rows:
        try:
            published = date.fromisoformat(row['published'])
        except ValueError:
            continue
        if not cutoff <= published <= today or not relevant_title(row['title']):
            continue
        source = by_id.get(row['source_id'])
        if not source or not article_url(source, row['url']):
            continue
        if category and source['category'] != category:
            continue
        if q and q not in ' '.join((row['title'], source['region'], source['name'])):
            continue
        items.append({'id': row['id'], 'title': row['title'], 'url': row['url'], 'publishedAt': row['published'], 'source': source['name'], 'region': source['region'], 'category': source['category']})
    return {'items': items[offset:offset+limit], 'total': len(items), 'hasMore': offset+limit < len(items), 'sources': [{k:v for k,v in s.items() if k != 'articlePattern'} for s in sources], 'coverage': '首批来源试接入，尚未覆盖全国所有城市；仅采集各来源当前列表页。'}
