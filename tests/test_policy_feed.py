from hashlib import sha256
from datetime import datetime, timezone, timedelta
import httpx
import pytest
from fastapi.testclient import TestClient
from bonus_platform.engine.policy import feed


def test_scheduled_refresh_rotates_sources_without_starving_failures(tmp_path, monkeypatch):
    db = tmp_path / 'policy.sqlite'
    feed.migrate(db)
    sources = [{**feed.SOURCES[0], 'id': f'source-{i:02d}'} for i in range(17)]
    monkeypatch.setattr(feed, 'SOURCES', sources)
    seen = []
    def collect(source):
        seen.append(source['id'])
        return [], 'error', 'HTTP 503'
    for stamp in ('2026-09-28T00:00:00+00:00', '2026-09-28T01:00:00+00:00', '2026-09-28T02:00:00+00:00'):
        monkeypatch.setattr(feed, 'now', lambda: stamp)
        assert len(feed.refresh(db, collector=collect)) == 8
    assert len(set(seen)) == 17


def test_article_metadata_cannot_reintroduce_non_hr_content():
    source = feed.SOURCES[0]
    listing = '<a href="/art/2026/9/8/art_104_1.html">关于调整生育保险有关政策的通知</a>'
    article = '<meta name="ArticleTitle" content="关于生育保险诊疗项目目录的通知"><meta name="PubDate" content="2026-09-08">'
    assert feed.collect(source, lambda url: listing if url == source['url'] else article) == ([], 'ok', '')
    assert not feed.relevant_title('关于生育津贴政策公开征求意见的通知')


def test_parser_supports_cdata_and_only_same_host_articles():
    source = feed.SOURCES[0]
    good = '/art/2026/9/8/art_104_22045.html'
    html = f'<script><record><![CDATA[<a href="{good}" title="关于参加基本医疗保险有关政策的通知">截断标题</a>]]></record></script><a href="https://evil.test{good}">关于参加基本医疗保险有关政策的通知</a>'
    assert feed.extract_links(source, html) == [('https://www.nhsa.gov.cn' + good, '关于参加基本医疗保险有关政策的通知')]
    assert feed.article_url(source, 'javascript:alert(1)') is None
    assert feed.publication({'pubdate': '2026-9-8 10:00'}) == '2026-09-08'
    assert feed.publication({'pubdate': '2026-02-30'}) == ''
    beijing = feed.SOURCES[1]
    assert feed.article_url(beijing, '/web/zwgk61/1738100/dtxx42/zlxqjcjd/744131372/index.html') is None
    assert feed.article_url(beijing, '/web/zwgk61/2024zcwj/436433461/744103382/index.html')


def test_collect_reports_partial_failure_and_never_invents_date():
    source = feed.SOURCES[0]
    listing = ''.join(f'<a href="/art/2026/9/8/art_104_{n}.html">关于参加基本医疗保险有关政策的通知{n}</a>' for n in [1, 2])
    def fetch(url):
        if url == source['url']:
            return listing
        return '<meta name="PubDate" content="2026-09-08">' if url.endswith('_1.html') else '<html>captcha</html>'
    rows, state, error = feed.collect(source, fetch)
    assert len(rows) == 1
    assert state == 'partial'
    assert error == 'article_fetch_failed'
    assert rows[0]['published'] == '2026-09-08'


def test_refresh_is_idempotent_and_failed_refresh_preserves_articles(tmp_path):
    db = tmp_path / 'policy.sqlite'
    feed.migrate(db)
    feed.migrate(db)
    source = feed.SOURCES[0]
    rows = [{'id': sha256(str(i).encode()).hexdigest(), 'source_id': source['id'], 'title': f'职工医保缴费政策{i}', 'url': f'https://www.nhsa.gov.cn/art/2026/9/8/art_104_{i}.html', 'published': datetime.now(timezone(timedelta(hours=8))).date().isoformat(), 'fetched_at': feed.now()} for i in range(25)]
    for _ in range(2):
        feed.refresh(db, [source], lambda s: (rows, 'ok', ''))
    first = feed.query(db_path=db)
    assert feed.query(category='公积金', db_path=db)['total'] == 0
    assert feed.query(category='医保', offset=20, db_path=db)['total'] == 25
    assert feed.query(category='医保', q='不存在', db_path=db)['total'] == 0
    assert first['total'] == 25 and first['hasMore'] and len(first['items']) == 20
    assert len(feed.query(offset=20, db_path=db)['items']) == 5
    assert feed.query(q='不存在', db_path=db)['total'] == 0
    success = first['sources'][0]['success_at']
    feed.refresh(db, [source], lambda s: ([], 'error', 'HTTP 403'))
    result = feed.query(db_path=db)
    assert result['total'] == 25
    assert result['sources'][0]['state'] == 'error'
    assert result['sources'][0]['success_at'] == success
    assert result['sources'][1]['state'] == 'pending'


def test_collector_rejects_redirects():
    transport = httpx.MockTransport(lambda r: httpx.Response(302, headers={'location': 'https://evil.test/'}))
    with httpx.Client(transport=transport) as client:
        with pytest.raises(httpx.HTTPStatusError):
            feed.fetch_html(client, feed.SOURCES[0]['url'])


def test_api_auth_query_validation_and_cron(monkeypatch):
    import bonus_platform.app as app_module
    app = app_module.app
    client = TestClient(app)
    monkeypatch.setenv('CRON_SECRET', 'test-policy-secret')
    monkeypatch.setattr(feed, 'refresh', lambda: [{'state': 'ok'}])
    assert client.get('/api/workbench/policies').status_code == 401
    assert client.get('/api/policies/cron/refresh').status_code == 401
    assert client.get('/api/policies/cron/refresh', headers={'authorization': 'Bearer test-policy-secret'}).status_code == 200
    app.dependency_overrides[app_module._current_user_id] = lambda: 'test-user'
    try:
        monkeypatch.setattr(feed, 'query', lambda q, offset, category='': {'items': [], 'q': q, 'offset': offset, 'category': category})
        response = client.get('/api/workbench/policies?q=深圳&offset=20')
        assert response.status_code == 200
        assert response.json()['q'] == '深圳'
        assert client.get('/api/workbench/policies?category=医保').json()['category'] == '医保'
        assert client.get('/api/workbench/policies?category=unknown').status_code == 422
        assert client.get('/api/workbench/policies?offset=-1').status_code == 422
        def unavailable(*args, **kwargs):
            raise RuntimeError('private connection details')
        monkeypatch.setattr(feed, 'query', unavailable)
        error = client.get('/api/workbench/policies')
        assert error.status_code == 503
        assert 'private' not in error.text
    finally:
        app.dependency_overrides.pop(app_module._current_user_id, None)


def test_feed_hides_old_future_and_irrelevant_notices(tmp_path):
    db = tmp_path / 'policy.sqlite'
    feed.migrate(db)
    today = datetime.now(timezone(timedelta(hours=8))).date()
    rows = []
    for i, (days, title) in enumerate([(0, '医保缴费政策'), (180, '边界缴费政策'), (181, '旧缴费政策'), (-1, '未来日期'), (0, '医保采购通知'), (0, '医保政策（已失效）')]):
        rows.append({'id': str(i), 'source_id': 'nhsa', 'title': title, 'url': f'https://www.nhsa.gov.cn/art/2026/9/8/art_104_{i}.html', 'published': (today - timedelta(days=days)).isoformat(), 'fetched_at': feed.now()})
    feed.refresh(db, [feed.SOURCES[0]], lambda s: (rows, 'ok', ''))
    result = feed.query(db_path=db)
    assert {r['title'] for r in result['items']} == {'医保缴费政策', '边界缴费政策'}
    assert feed.query(q='旧缴费政策', db_path=db)['total'] == 0
    with feed._connect(db) as conn:
        assert len(conn.execute('SELECT * FROM policy_articles').fetchall()) == 6


@pytest.mark.parametrize('title', [
    '关于印发2026年纠正医药购销领域和医疗服务中不正之风工作要点的通知',
    '国家医保局关于进一步加强定点零售药店职工基本医疗保险个人账户使用监督管理的通知',
    '关于改革完善儿童用药供应保障机制的实施意见',
    '关于发布《医药代表管理办法》的公告',
    '国家医疗保障局关于印发按病组和病种分值付费3.0版分组方案的通知',
    '关于优化调整房地产政策的通知',
    '广州市城乡居民基本养老保险实施办法',
])
def test_excludes_policies_unrelated_to_enterprise_hr(title):
    assert not feed.relevant_title(title)


@pytest.mark.parametrize('title', [
    '关于2026年度各项社会保险缴费工资基数上下限的通告',
    '关于2026年度住房公积金缴存调整有关问题的通知',
    '关于阶段性降低失业保险费率的通知',
    '关于企业职工参保登记及增员减员业务调整的通知',
    '关于生育津贴申领流程调整的通知',
    '关于工伤认定申请材料的通知',
    '关于职工基本医疗保险个人账户跨省共济经办规程的通知',
    '关于退休人员养老保险待遇资格认证的通知',
])
def test_keeps_hr_operational_policies(title):
    assert feed.relevant_title(title)


def test_no_hr_matches_is_success_not_a_collection_failure():
    rows, state, error = feed.collect(feed.SOURCES[0], lambda url: '<a href="/art/2026/9/8/art_104_1.html">关于医药代表管理办法的公告</a>')
    assert (rows, state, error) == ([], 'ok', '')
