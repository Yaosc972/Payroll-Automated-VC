"""Company integration checks; all inputs and identities are synthetic."""
import io
import json
from types import SimpleNamespace

from fastapi import HTTPException
import pytest

from bonus_platform.engine import recruitment_runtime as runtime
from bonus_platform.engine.recruitment_remote import RemoteClient, configured_client
from bonus_platform.engine.recruitment_snapshot_library import SnapshotLibrary
from bonus_platform.engine.recruitment_trials import ScopedDraftStore
from test_company_security_api import secured_company, identity
from test_recruitment_monthly_sync import payloads, MONTH


@pytest.mark.parametrize(('method', 'url'), [
    ('GET', '/api/recruitment/activities'),
    ('POST', '/api/recruitment/activities'),
    ('GET', '/api/recruitment/activities/snapshot-library/202608'),
    ('POST', '/api/recruitment/activities/snapshot-library/202608/refresh'),
    ('PATCH', '/api/recruitment/activities/snapshot-library/schedule'),
    ('GET', '/api/recruitment/drafts/202608'),
    ('POST', '/api/recruitment/drafts/202608/prepare'),
    ('GET', '/api/recruitment/drafts/202608/sources/synthetic/download'),
    ('GET', '/api/recruitment/trials'),
    ('POST', '/api/recruitment/source-packages/calculate'),
    ('GET', '/api/recruitment/activities/' + 'a'*32 + '/api/recruitment/drafts/202608'),
])
def test_all_new_business_routes_use_existing_module_permission(secured_company, monkeypatch, method, url):
    assert secured_company.request(method, url, json={}).status_code == 401
    identity(monkeypatch, ('employee',))
    assert secured_company.request(method, url, json={}).status_code == 403


def test_recruitment_role_can_read_isolated_activity_list(secured_company, monkeypatch, tmp_path):
    import bonus_platform.recruitment_draft_api as api
    monkeypatch.setattr(api, 'store', ScopedDraftStore(tmp_path/'drafts'))
    monkeypatch.setattr(runtime, 'production_runtime', lambda: False)
    identity(monkeypatch, ('recruitment',))
    response = secured_company.get('/api/recruitment/activities')
    assert response.status_code == 200
    assert response.json() == {'activities': [], 'legacyRecords': []}


@pytest.mark.parametrize('page', ['recruitment.html', 'recruitment-activities.html', 'recruitment-history.html', 'recruitment-guide.html', 'recruitment-guide.md'])
def test_recruitment_pages_use_company_login_and_module_gate(secured_company, monkeypatch, page):
    import bonus_platform.app as platform
    response = secured_company.get('/'+page, follow_redirects=False)
    assert response.status_code == 302 and response.headers['location'].startswith('/login.html?next=')
    monkeypatch.setattr(platform, 'get_session_user_id', lambda _: 'synthetic-user')
    monkeypatch.setattr(platform, '_user_can_enter_module', lambda *_: False)
    secured_company.cookies.set('sigma_session', 'synthetic-session')
    response = secured_company.get('/'+page, follow_redirects=False)
    assert response.status_code == 403


def test_hosted_workbench_rejects_ephemeral_storage_and_missing_lock_database(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, 'production_runtime', lambda: True)
    monkeypatch.delenv('SIGMA_RECRUITMENT_DATA_DIR', raising=False)
    with pytest.raises(HTTPException) as failure:
        runtime.require_runtime()
    assert failure.value.status_code == 503
    monkeypatch.setenv('SIGMA_RECRUITMENT_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(runtime, 'shared_mount', lambda _: False)
    with pytest.raises(HTTPException): runtime.require_runtime()
    monkeypatch.setattr(runtime, 'shared_mount', lambda _: True)
    monkeypatch.setattr(runtime.config, 'ADMIN_DATABASE_URL', 'sqlite:///synthetic')
    with pytest.raises(HTTPException): runtime.require_runtime()
    monkeypatch.setattr(runtime.config, 'ADMIN_DATABASE_URL', 'mysql://invalid/synthetic')
    runtime.require_runtime()


def test_mysql_lock_excludes_competing_host_and_releases_after_error(monkeypatch):
    monkeypatch.setattr(runtime, 'production_runtime', lambda: True)
    monkeypatch.setattr(runtime, 'require_runtime', lambda: None)
    held = set()
    class Connection:
        def cursor(self): return self
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql, params):
            self.name = params[0]; self.owns = self.name not in held
            if self.owns: held.add(self.name)
        def fetchone(self): return {'acquired': int(self.owns)}
        def close(self):
            if self.owns: held.remove(self.name)
    monkeypatch.setattr(runtime, 'mysql_connection', lambda _: Connection())
    with pytest.raises(ValueError):
        with runtime.task_lock('public-refresh') as first:
            assert first
            with runtime.task_lock('public-refresh') as second: assert not second
            raise ValueError('synthetic crash')
    with runtime.task_lock('public-refresh') as after: assert after


def test_persisted_activity_snapshot_settings_and_manual_state_survive_new_process(tmp_path, monkeypatch):
    import subprocess
    import sys
    from bonus_platform.engine.recruitment_activities import ACTIVITY
    store = ScopedDraftStore(tmp_path/'drafts'); library = SnapshotLibrary(store)
    payloads(monkeypatch); library.refresh(MONTH)
    library.configure({'enabled': False, 'hour': 9, 'minute': 15})
    item = store.create_activity(MONTH)
    token = ACTIVITY.set(item['id'])
    try:
        state = store.read(MONTH)
        row = next(r for r in state['rows'] if r['values']['工号'] == 'zt101')
        store.change(MONTH, state['revision'], {'edits': [{'rowId': row['id'], 'field': '招聘负责人姓名', 'value': '人工负责人', 'reason': '合成验证'}]})
    finally: ACTIVITY.reset(token)
    root = store.activity_root/item['id']
    before = {str(p.relative_to(tmp_path)):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    code = '''
import sys
from bonus_platform.engine.recruitment_trials import ScopedDraftStore
from bonus_platform.engine.recruitment_snapshot_library import SnapshotLibrary
s=ScopedDraftStore(sys.argv[1]); item=s.list_activities()[0]
assert item['id']==sys.argv[2] and item['people']==2
assert SnapshotLibrary(s).settings()=={'enabled':False,'hour':9,'minute':15}
assert set(SnapshotLibrary(s).current(202608))=={'domestic','overseas'}
'''
    subprocess.run([sys.executable, '-c', code, str(store.base_root), item['id']], check=True)
    assert before == {str(p.relative_to(tmp_path)):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    saved = json.loads((root/'drafts'/str(MONTH)/'draft.json').read_text())
    assert any(e['value'] == '人工负责人' for e in saved['edits'])


def test_hosted_overseas_never_falls_back_to_local_browser(monkeypatch):
    import bonus_platform.auth as auth
    monkeypatch.setattr(auth, 'production_runtime', lambda: True)
    monkeypatch.delenv('SIGMA_RECRUITMENT_OVERSEAS_CONNECTOR_URL', raising=False)
    monkeypatch.delenv('SIGMA_RECRUITMENT_OVERSEAS_CONNECTOR_TOKEN', raising=False)
    with pytest.raises(ValueError, match='尚未接通'): configured_client()


@pytest.mark.parametrize('url', ['http://invalid.example', 'https://user:pass@invalid.example', 'https://invalid.example/other', 'https://invalid.example?key=value'])
def test_remote_connector_rejects_unsafe_destinations(monkeypatch, url):
    monkeypatch.setenv('SIGMA_RECRUITMENT_OVERSEAS_CONNECTOR_URL', url)
    monkeypatch.setenv('SIGMA_RECRUITMENT_OVERSEAS_CONNECTOR_TOKEN', 'synthetic-token')
    with pytest.raises(ValueError): RemoteClient()


def test_remote_snapshot_keeps_capture_time_and_validates_month(monkeypatch):
    monkeypatch.setenv('SIGMA_RECRUITMENT_OVERSEAS_CONNECTOR_URL', 'https://connector.invalid')
    monkeypatch.setenv('SIGMA_RECRUITMENT_OVERSEAS_CONNECTOR_TOKEN', 'synthetic-token')
    value = {'version': 1, 'month': 202608, 'queriedAt': '2026-08-31T08:00:00+08:00', 'roster': [], 'offers': []}
    client = RemoteClient(); requests = []
    def open_request(request, **kwargs):
        requests.append(request)
        return io.BytesIO(json.dumps(value).encode())
    client.opener = SimpleNamespace(open=open_request)
    assert client.fetch(202608)['queriedAt'] == value['queriedAt']
    assert requests[0].full_url.endswith('/v1/recruitment/overseas-snapshot')
    assert json.loads(requests[0].data)['month'] == 202608
    with pytest.raises(ValueError): client.fetch(202609)


def test_beisen_uses_deployment_secrets_without_local_file(monkeypatch):
    import bonus_platform.auth as auth
    from bonus_platform.engine.recruitment_beisen import Client
    monkeypatch.setattr(auth, 'production_runtime', lambda: True)
    monkeypatch.setenv('BEISEN_APP_KEY', 'synthetic-key')
    monkeypatch.setenv('BEISEN_APP_SECRET', 'synthetic-secret')
    seen = []
    monkeypatch.setattr(Client, 'post', lambda self, path, body: seen.append(body) or {'access_token': 'synthetic-result'})
    assert Client().token == 'synthetic-result'
    assert seen == [{'grant_type': 'client_credentials', 'app_key': 'synthetic-key', 'app_secret': 'synthetic-secret'}]


def test_runtime_mount_check_rejects_container_submount_and_accepts_nfs(monkeypatch, tmp_path):
    from pathlib import Path
    original_file, original_text = Path.is_file, Path.read_text
    mountinfo = Path('/proc/self/mountinfo')
    monkeypatch.setattr(Path, 'is_file', lambda p: True if p == mountinfo else original_file(p))
    root = tmp_path.resolve()
    lines = ['1 0 0:1 / / rw - overlay overlay rw',
             f'2 1 0:2 / {root} rw - nfs4 storage:/payroll rw']
    monkeypatch.setattr(Path, 'read_text', lambda p, *a, **kw: '\n'.join(lines) if p == mountinfo else original_text(p, *a, **kw))
    assert runtime.shared_mount(root/'recruitment')
    lines.append(f'3 2 0:3 / {root}/recruitment rw - tmpfs tmpfs rw')
    assert not runtime.shared_mount(root/'recruitment')


def test_ego_runner_protocol_auth_scope_busy_and_login_failure(monkeypatch):
    from http.server import ThreadingHTTPServer
    from threading import Thread
    import urllib.error
    import urllib.request
    from scripts import recruitment_overseas_connector as runner
    from bonus_platform.engine.recruitment_remote import PATH
    monkeypatch.setenv('SIGMA_RECRUITMENT_OVERSEAS_CONNECTOR_TOKEN', 'synthetic-token')
    calls = []
    payload = {'version': 1, 'month': 202608, 'queriedAt': '2026-08-31T08:00:00+08:00', 'roster': [], 'offers': []}
    monkeypatch.setattr(runner.BrowserClient, 'fetch', lambda self, *a: calls.append(a) or payload)
    server = ThreadingHTTPServer(('127.0.0.1', 0), runner.Handler)
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    query = {'month': 202608, 'jobNumbers': [], 'offerCodes': []}
    def request(body=query, token='synthetic-token'):
        req = urllib.request.Request(f'http://127.0.0.1:{server.server_port}{PATH}',
            data=json.dumps(body).encode(), headers={'Authorization': 'Bearer '+token})
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as exc:
            return exc.code, json.load(exc)
    try:
        assert request(token='invalid')[0] == 401
        assert request({**query, 'url': 'https://arbitrary.invalid'})[0] == 400
        assert not calls
        with runner.BUSY:
            assert request()[0] == 409
        assert request() == (200, {**payload, 'requestedJobNumbers': [], 'requestedOfferCodes': [], 'missingOfferCodes': []})
        assert len(calls) == 1
        def expired(*args): raise ValueError('private upstream diagnostic')
        monkeypatch.setattr(runner.BrowserClient, 'fetch', expired)
        status, error = request()
        assert status == 424 and 'private' not in json.dumps(error)
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)
