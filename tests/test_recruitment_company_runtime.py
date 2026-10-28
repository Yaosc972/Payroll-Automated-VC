"""Company integration checks; all inputs and identities are synthetic."""
import json

from fastapi import HTTPException
import pytest

from bonus_platform.engine import recruitment_runtime as runtime
from bonus_platform.engine.recruitment_overseas import configured_client
from bonus_platform.engine.recruitment_snapshot_library import SnapshotLibrary
from bonus_platform.engine.recruitment_trials import ScopedDraftStore
from test_company_security_api import secured_company, identity
from test_recruitment_monthly_sync import payloads, MONTH


@pytest.mark.parametrize(('method', 'url'), [
    ('GET', '/api/recruitment/activities'),
    ('GET', '/api/recruitment/drafts/202609/external-personnel/template'),
    ('POST', '/api/recruitment/drafts/202609/sources'),
    ('GET', '/api/recruitment/activities/' + 'a'*32 + '/api/recruitment/drafts/202609/external-personnel/template'),
    ('POST', '/api/recruitment/activities/' + 'a'*32 + '/api/recruitment/drafts/202609/sources'),
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
    assert response.json() == {'activities': [], 'legacyRecords': [], 'currentUserId': 'security-user'}


@pytest.mark.parametrize('avatar',[None,'javascript:alert(1)','https://user:password@example.com/avatar.png','https://[invalid'])
def test_company_identity_uses_existing_session_and_default_avatar(secured_company,monkeypatch,tmp_path,avatar):
    import bonus_platform.recruitment_draft_api as api
    monkeypatch.setattr(api,'store',ScopedDraftStore(tmp_path/'drafts'))
    monkeypatch.setattr(runtime,'production_runtime',lambda:False)
    current=identity(monkeypatch,('recruitment',));current['user'].update(name='公司用户',avatarUrl=avatar)
    response=secured_company.post('/api/recruitment/activities',json={'month':202609,'creator':{'userId':'forged','name':'伪造用户'}})
    assert response.status_code==200,response.text
    expected={'userId':'security-user','name':'公司用户','avatarUrl':'/assets/sigma-user-avatar-default.png'}
    assert response.json()['creator']==expected
    listing=secured_company.get('/api/recruitment/activities').json()
    assert listing['currentUserId']=='security-user' and listing['activities'][0]['creator']==expected


@pytest.mark.parametrize('page', ['recruitment.html', 'recruitment-activities.html', 'recruitment-history.html', 'recruitment-guide.html', 'recruitment-guide.md', 'recruitment-rules.html'])
def test_recruitment_pages_use_company_login_and_module_gate(secured_company, monkeypatch, page):
    import bonus_platform.app as platform
    response = secured_company.get('/'+page, follow_redirects=False)
    assert response.status_code == 302 and response.headers['location'].startswith('/login.html?next=')
    monkeypatch.setattr(platform, 'get_session_user_id', lambda _: 'synthetic-user')
    monkeypatch.setattr(platform, '_user_can_enter_module', lambda *_: False)
    secured_company.cookies.set('sigma_session', 'synthetic-session')
    response = secured_company.get('/'+page, follow_redirects=False)
    assert response.status_code == 403


def test_hosted_workbench_requires_existing_mysql_and_private_obs(monkeypatch):
    from bonus_platform.engine import recruitment_persistence as durable
    monkeypatch.setattr(runtime, 'production_runtime', lambda: True)
    monkeypatch.setattr(durable, 'enabled', lambda: True)
    monkeypatch.setattr(durable, 'obs_storage_configured', lambda: False)
    monkeypatch.setattr(runtime.config, 'ADMIN_DATABASE_URL', 'mysql://invalid/synthetic')
    with pytest.raises(HTTPException) as failure: runtime.require_runtime()
    assert failure.value.status_code == 503
    monkeypatch.setattr(durable, 'obs_storage_configured', lambda: True)
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
    from bonus_platform.engine.recruitment_browser_queue import QueuedClient
    assert isinstance(configured_client(), QueuedClient)






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
