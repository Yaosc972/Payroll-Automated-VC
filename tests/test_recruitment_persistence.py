"""Durable workbench behavior using an isolated repository and private objects."""
from copy import deepcopy
from contextlib import contextmanager
import json
from pathlib import Path
import threading
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from bonus_platform.engine import recruitment_persistence as durable
from bonus_platform.engine import recruitment_runtime as runtime
from bonus_platform.engine.recruitment_trials import ScopedDraftStore
from bonus_platform.engine.recruitment_snapshot_library import SnapshotLibrary
from test_recruitment_monthly_sync import MONTH, payloads


@pytest.fixture
def backend(tmp_path, monkeypatch):
    state, objects, versions = {}, {}, []
    lock = threading.Lock()
    owner = [None]
    class Repo:
        serial = 0
        def __init__(self, write=False, wait=0):
            self.write = write
            if write and not lock.acquire(timeout=wait): raise durable.Busy()
            Repo.serial += 1; self.connection_id = Repo.serial
            if write: owner[0] = self.connection_id
        def read(self):
            row = state.get(durable.environment())
            return (row[0], deepcopy(row[1]), owner[0]) if row else (0, {'files': {}}, owner[0])
        def save(self, revision, document):
            assert self.write and owner[0] == self.connection_id
            assert state.get(durable.environment(), (0,))[0] == revision
            state[durable.environment()] = (revision+1, deepcopy(document)); versions.append(deepcopy(document))
        def close(self):
            if self.write: owner[0] = None; lock.release(); self.write = False
    monkeypatch.setattr(durable, 'Repository', Repo)
    monkeypatch.setattr(durable, 'enabled', lambda: True)
    monkeypatch.setattr(durable, 'obs_get_bytes', lambda key: objects.get(key))
    monkeypatch.setattr(durable, 'obs_put_bytes', lambda key, content, **kw: objects.__setitem__(key, content))
    monkeypatch.setattr(durable.config, 'OUTPUT_DIR', tmp_path/'cache')
    monkeypatch.setattr(runtime, 'production_runtime', lambda: False)
    monkeypatch.setenv('SIGMA_LABOR_STORAGE_ENV', 'synthetic')
    monkeypatch.setenv('AIDEPLOY_ENV', 'preview')
    return state, objects, versions


@contextmanager
def session(write=False, **kw):
    s = durable.Session(write=write, **kw).open(); token = durable.SESSION.set(s)
    try:
        yield s
        s.publish()
    finally:
        durable.SESSION.reset(token); s.close()


def client(monkeypatch, tmp_path):
    import bonus_platform.recruitment_draft_api as api
    monkeypatch.setattr(api, 'store', ScopedDraftStore(tmp_path/'not-authoritative'/'recruitment_drafts'))
    app = FastAPI()
    for route in (api.activities_router,api.activity_drafts_router,api.router,api.trials_router,api.trial_drafts_router):
        app.include_router(route)
    return TestClient(app), api.store


def test_new_working_copy_restores_snapshots_activity_edits_and_settings(backend, monkeypatch, tmp_path):
    payloads(monkeypatch); store = ScopedDraftStore(tmp_path/'unused'/'recruitment_drafts')
    with session(write=True) as original:
        library = SnapshotLibrary(store); library.refresh(MONTH)
        library.configure({'enabled':False,'hour':9,'minute':15})
        activity = store.create_activity(MONTH)
        from bonus_platform.engine.recruitment_activities import ACTIVITY
        token = ACTIVITY.set(activity['id'])
        try:
            state = store.read(MONTH); row = next(r for r in state['rows'] if r['values']['工号']=='zt101')
            changed = store.change(MONTH,state['revision'],{'edits':[{'rowId':row['id'],'field':'招聘负责人姓名','value':'人工核实','reason':'合成验证'}]})
        finally: ACTIVITY.reset(token)
        path = original.root
    assert not path.exists()
    with session() as restored:
        assert restored.root != path
        assert store.list_activities()[0]['people'] == 2
        assert SnapshotLibrary(store).settings() == {'enabled':False,'hour':9,'minute':15}
        saved=json.loads((store.activity_root/activity['id']/'drafts'/str(MONTH)/'draft.json').read_text())
        assert any(e['value']=='人工核实' for e in saved['edits'])
        assert set(SnapshotLibrary(store).current(MONTH)) == {'domestic','overseas'}
    assert backend[1] and backend[2]


def test_company_creator_survives_object_restore_and_a_different_viewer(backend,monkeypatch,tmp_path):
    import shutil
    import bonus_platform.auth as auth
    payloads(monkeypatch);api,_=client(monkeypatch,tmp_path)
    current={'user':{'id':'synthetic-creator','name':'合成创建人','avatar_url':'https://example.com/company-avatar.png'}}
    monkeypatch.setattr(auth,'current_user_from_request',lambda _:current)
    response=api.post('/api/recruitment/activities',json={'month':MONTH,'creator':{'userId':'forged','name':'伪造用户'}})
    assert response.status_code==200,response.text
    item=response.json();expected={'userId':'synthetic-creator','name':'合成创建人','avatarUrl':'https://example.com/company-avatar.png'}
    assert item['creator']==expected
    assert any(json.loads(content).get('creator')==expected for content in backend[1].values() if content.startswith(b'{'))
    shutil.rmtree(tmp_path/'cache')
    current['user']={'id':'synthetic-viewer','name':'其他查看人'}
    restored,_=client(monkeypatch,tmp_path/'new-process')
    listing=restored.get('/api/recruitment/activities').json()
    assert listing['currentUserId']=='synthetic-viewer'
    assert next(x for x in listing['activities'] if x['id']==item['id'])['creator']==expected
    assert not (tmp_path/'not-authoritative').exists()


def test_failed_publish_keeps_last_committed_manifest_and_history(backend, monkeypatch):
    with session(write=True) as s:
        root=s.root/'recruitment_drafts';root.mkdir();(root/'evidence.json').write_text('{"value":1}')
    before=deepcopy(backend[0])
    def unavailable(*a,**kw): raise RuntimeError('synthetic object outage')
    monkeypatch.setattr(durable,'obs_put_bytes',unavailable)
    with pytest.raises(RuntimeError):
        with session(write=True) as s:(s.root/'recruitment_drafts/evidence.json').write_text('{"value":2}')
    assert backend[0] == before
    with session() as s: assert json.loads((s.root/'recruitment_drafts/evidence.json').read_text()) == {'value':1}


def test_reader_sees_committed_progress_writer_exclusion_and_stale_job_detection(backend):
    with session(write=True,job_id='a'*32) as writer:
        folder=writer.root/'recruitment_drafts';folder.mkdir();(folder/'job.json').write_text('{}')
        writer.publish(active=True)
        with session() as reader: assert durable.job_active('a'*32)
        with pytest.raises(durable.Busy): durable.Session(write=True).open()
    with session(): assert not durable.job_active('a'*32)


def test_corrupt_object_fails_closed_without_rewriting_sql(backend, tmp_path):
    with session(write=True) as s:
        p=s.root/'recruitment_drafts/input.json';p.parent.mkdir();p.write_text('{}')
    before=deepcopy(backend[0]);backend[1][next(iter(backend[1]))]=b'bad'
    with pytest.raises(ValueError): durable.Session().open()
    assert backend[0]==before


@pytest.mark.parametrize('name',['../outside','/outside','recruitment_drafts/../../outside','other/input.json','recruitment_drafts\\input.json'])
def test_restore_rejects_manifest_path_escape(name):
    with pytest.raises(ValueError):durable.relative_path(name)


def test_preview_isolated_from_production_without_new_settings(backend,monkeypatch):
    with session(write=True) as s:
        p=s.root/'recruitment_drafts/input.json';p.parent.mkdir();p.write_text('{}')
    monkeypatch.setenv('AIDEPLOY_ENV','production')
    with session() as s:assert not list(s.root.rglob('input.json'))
    monkeypatch.setenv('AIDEPLOY_ENV','preview')
    with session() as s:assert (s.root/'recruitment_drafts/input.json').is_file()


def test_real_api_writes_survive_fresh_requests_and_downloads(backend,monkeypatch,tmp_path):
    payloads(monkeypatch);api,store=client(monkeypatch,tmp_path)
    with session(write=True):SnapshotLibrary(store).refresh(MONTH)
    response=api.post('/api/recruitment/activities',json={'month':MONTH,'name':'持久化验证'})
    assert response.status_code==200,response.text
    assert response.json()['updatedAt'].endswith('+08:00')
    item=response.json();base=f"/api/recruitment/activities/{item['id']}/api/recruitment/drafts/{MONTH}"
    state=api.get(base).json();row=next(r for r in state['rows'] if r['values']['工号']=='zt101')
    change=api.post(base+'/changes',json={'revision':state['revision'],'edits':[{'rowId':row['id'],'field':'招聘负责人姓名','value':'持久人工','reason':'合成验证'}]})
    assert change.status_code==200,change.text
    assert any(e['value']=='持久人工' for e in api.get(base+'/changes').json()['entries'])
    source=api.get(base).json()['sources'][0]
    exported=api.get(base+'/sources/'+source['id'])
    assert exported.status_code==200 and exported.content
    assert json.loads(exported.content)['version']==1
    result=api.get(base+'/calculation/export')
    assert result.status_code==200 and result.content.startswith(b'PK')
    assert api.get('/api/recruitment/activities').json()['activities'][0]['name']=='持久化验证'
    assert not (tmp_path/'not-authoritative').exists()


def test_background_sync_uses_new_persistent_session_after_request_closes(backend,monkeypatch,tmp_path):
    payloads(monkeypatch);api,store=client(monkeypatch,tmp_path)
    response=api.post(f'/api/recruitment/activities/snapshot-library/{MONTH}/refresh')
    assert response.status_code==200,response.text
    for _ in range(200):
        result=api.get(f'/api/recruitment/activities/snapshot-library/{MONTH}').json()
        if result['job']['status']=='complete':break
        time.sleep(.02)
    assert result['job']['status']=='complete',result
    assert set(result['snapshots'])=={'domestic','overseas'}
    item=api.post('/api/recruitment/activities',json={'month':MONTH}).json()
    base=f"/api/recruitment/activities/{item['id']}/api/recruitment/drafts/{MONTH}"
    monkeypatch.setattr(durable,'Cancellation',lambda identifier,event:event)
    state=api.get(base).json()
    response=api.post(base+'/sync-monthly',json={'revision':state['revision']})
    assert response.status_code==200,response.text
    for _ in range(200):
        status=api.get(base+'/prepare').json()
        if status['status']=='complete':break
        time.sleep(.02)
    assert status['status']=='complete',status
