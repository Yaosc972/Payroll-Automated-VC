"""Real SQL transactions with synthetic HR results and existing browser auth."""
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from bonus_platform.engine import recruitment_browser_queue as queue
from bonus_platform.engine import recruitment_persistence as durable


@pytest.fixture
def worker(tmp_path,monkeypatch):
    path=tmp_path/'queue.db'
    with sqlite3.connect(path) as db:
        db.executescript('''CREATE TABLE sigma_recruitment_browser_jobs (
        environment TEXT,id TEXT,request_key TEXT,request_document TEXT,status TEXT,
        lease_token TEXT DEFAULT '',lease_until REAL DEFAULT 0,claims INTEGER DEFAULT 0,
        document TEXT,created_at REAL,PRIMARY KEY(environment,id),UNIQUE(environment,request_key));''')
    class Cursor:
        def __init__(self,db):self.cursor=db.cursor()
        def __enter__(self):return self
        def __exit__(self,*a):self.cursor.close()
        def execute(self,sql,args=()):
            sql=sql.replace('INSERT IGNORE','INSERT OR IGNORE').replace('%s','?').replace(' FOR UPDATE','').replace('UNIX_TIMESTAMP()',"CAST(strftime('%s','now') AS INTEGER)")
            self.cursor.execute(sql,args)
        def fetchone(self):
            row=self.cursor.fetchone();return dict(row) if row else None
    class DB:
        def __init__(self,db):self.db=db
        def cursor(self):return Cursor(self.db)
    @contextmanager
    def connect():
        db=sqlite3.connect(path,timeout=10);db.row_factory=sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE');yield DB(db);db.commit()
        except BaseException:db.rollback();raise
        finally:db.close()
    objects={}
    monkeypatch.setattr(queue,'connection',connect)
    monkeypatch.setattr(queue,'actor',lambda request:'synthetic-recruitment-user')
    monkeypatch.setattr(queue,'obs_put_bytes',lambda key,content,**kw:objects.__setitem__(key,content))
    monkeypatch.setattr(queue,'obs_get_bytes',lambda key:objects.get(key))
    app=FastAPI();app.include_router(queue.router)
    return TestClient(app),path,objects


def value(month=202608):
    return {'version':1,'month':month,'queriedAt':'2026-10-23T08:00:00+08:00','requestedJobNumbers':[],
            'requestedOfferCodes':[],'roster':[],'offers':[]}


def test_concurrent_workers_claim_once_and_stale_lease_cannot_publish(worker):
    client,path,objects=worker;identifier=queue.enqueue(202608,[],[])
    with ThreadPoolExecutor(max_workers=4) as pool:
        claimed=list(pool.map(lambda _:client.post('/api/recruitment/browser-worker/claim').json()['job'],range(4)))
    jobs=[j for j in claimed if j];assert len(jobs)==1
    first=jobs[0];assert first['id']==identifier
    with sqlite3.connect(path) as db:db.execute('UPDATE sigma_recruitment_browser_jobs SET lease_until=0')
    second=client.post('/api/recruitment/browser-worker/claim').json()['job']
    assert second['id']==identifier and second['lease']!=first['lease']
    old=client.post(f'/api/recruitment/browser-worker/{identifier}/complete',json={'lease':first['lease'],'snapshot':value()})
    assert old.status_code==409 and not objects
    current=client.post(f'/api/recruitment/browser-worker/{identifier}/complete',json={'lease':second['lease'],'snapshot':value()})
    assert current.status_code==200 and objects
    assert queue.get(identifier)['status']=='completed'


def test_scope_and_month_mismatch_rejected_and_login_failure_is_explicit(worker):
    client,_,objects=worker;identifier=queue.enqueue(202608,[],[])
    job=client.post('/api/recruitment/browser-worker/claim').json()['job']
    url=f'/api/recruitment/browser-worker/{identifier}'
    assert client.post(url+'/complete',json={'lease':job['lease'],'snapshot':value(202609)}).status_code==400
    mismatch=value();mismatch['requestedJobNumbers']=['zt1']
    assert client.post(url+'/complete',json={'lease':job['lease'],'snapshot':mismatch}).status_code==400
    assert not objects
    assert client.post(url+'/fail',json={'lease':job['lease'],'code':'LOGIN_REQUIRED'}).status_code==200
    assert queue.get(identifier)['status']=='failed'
    assert '登录已失效' in queue.get(identifier)['document']['message']


def test_server_reuses_completed_result_and_original_capture_time(worker,monkeypatch):
    client,_,objects=worker
    def execute(_):
        job=client.post('/api/recruitment/browser-worker/claim').json()['job']
        assert job
        assert client.post(f"/api/recruitment/browser-worker/{job['id']}/complete",json={'lease':job['lease'],'snapshot':value()}).status_code==200
    monkeypatch.setattr(queue.time,'sleep',execute)
    result=queue.QueuedClient().fetch(202608)
    assert result['queriedAt']=='2026-10-23T08:00:00+08:00'


def test_application_login_and_recruitment_permission_are_required(monkeypatch):
    # The endpoint independently checks ordinary workbench identity, without a new secret.
    monkeypatch.setattr(queue,'current_user_from_request',lambda _:None)
    app=FastAPI();app.include_router(queue.router);client=TestClient(app)
    assert client.post('/api/recruitment/browser-worker/claim').status_code==401
    monkeypatch.setattr(queue,'current_user_from_request',lambda _:{'user':{'id':'synthetic'},'modules':[],'roles':[]})
    assert client.post('/api/recruitment/browser-worker/claim').status_code==403


def test_waiting_worker_progress_is_republished_when_the_message_does_not_change(worker,monkeypatch):
    client,_,_=worker
    clock=[0];messages=[]
    monkeypatch.setattr(queue.time,'monotonic',lambda:clock[0])
    def tick(_):
        clock[0]+=2
        if clock[0]>=8:
            job=client.post('/api/recruitment/browser-worker/claim').json()['job']
            assert client.post(f"/api/recruitment/browser-worker/{job['id']}/complete",json={'lease':job['lease'],'snapshot':value()}).status_code==200
    monkeypatch.setattr(queue.time,'sleep',tick)
    result=queue.QueuedClient().fetch(202608,progress=messages.append)
    assert result['month']==202608
    assert len(messages)>=2 and messages[0]==messages[1]


def targeted_result(job):
    result=value(job['month'])
    result.update(requestedJobNumbers=job['jobNumbers'],requestedOfferCodes=job['offerCodes'],
                  missingOfferCodes=job['offerCodes'])
    if job.get('employmentOnly'):
        result.update(employmentOnly=True,employmentHistoryScope='oehr_and_migrated',employmentHistory=[])
    if job.get('offerOnly'):result['offerOnly']=True
    return result


@pytest.mark.parametrize('mode',['ordinary','employment','offer'])
def test_hosted_calls_roundtrip_the_requested_mode_and_explicit_missing_scope(worker,monkeypatch,mode):
    import bonus_platform.auth as auth
    from bonus_platform.engine import recruitment_overseas as overseas
    client,_,_=worker;claimed=[]
    monkeypatch.setattr(auth,'production_runtime',lambda:True)
    monkeypatch.setattr(overseas,'BrowserClient',lambda:pytest.fail('Company queries must use the queue'))
    def execute(_):
        job=client.post('/api/recruitment/browser-worker/claim').json()['job'];claimed.append(job)
        assert client.post(f"/api/recruitment/browser-worker/{job['id']}/complete",
                           json={'lease':job['lease'],'snapshot':targeted_result(job)}).status_code==200
    monkeypatch.setattr(queue.time,'sleep',execute)
    if mode=='ordinary':result=overseas.fetch(202609)
    elif mode=='employment':result=overseas.fetch_employment(202609,['ZT-TARGET'])
    else:result=overseas.fetch_offers(202609,['OF-TARGET'])
    assert len(claimed)==1
    assert claimed[0]['employmentOnly']==(mode=='employment')
    assert claimed[0]['offerOnly']==(mode=='offer')
    assert result['roster']==result['offers']==[]
    assert result['requestedJobNumbers']==(['zt-target'] if mode=='employment' else [])
    assert result['missingOfferCodes']==(['of-target'] if mode=='offer' else [])
    if mode=='employment':assert result['employmentHistoryScope']=='oehr_and_migrated'


def test_mode_is_part_of_idempotency_key_and_older_jobs_remain_claimable(worker):
    from types import SimpleNamespace
    client,path,_=worker;token=queue.SESSION.set(SimpleNamespace(job_id='synthetic-preparation'))
    try:
        normal=queue.enqueue(202609,['zt-target'],[])
        employment=queue.enqueue(202609,['zt-target'],[],employment_only=True)
        assert normal!=employment
        assert queue.enqueue(202609,['zt-target'],[],employment_only=True)==employment
    finally:queue.SESSION.reset(token)
    with sqlite3.connect(path) as db:
        db.execute('UPDATE sigma_recruitment_browser_jobs SET request_document=? WHERE id=?',
                   (json.dumps({'month':202609,'jobNumbers':['zt-target'],'offerCodes':[]}),normal))
    job=client.post('/api/recruitment/browser-worker/claim').json()['job']
    assert job['id']==normal and not job.get('employmentOnly') and not job.get('offerOnly')
    assert client.post(f"/api/recruitment/browser-worker/{normal}/complete",
                       json={'lease':job['lease'],'snapshot':targeted_result(job)}).status_code==200


@pytest.mark.parametrize('mode',['employment','offer'])
def test_targeted_result_without_mode_or_wrong_scope_cannot_publish(worker,mode):
    client,_,objects=worker
    identifier=queue.enqueue(202609,['zt-target'] if mode=='employment' else [],
                             ['of-target'] if mode=='offer' else [],
                             employment_only=mode=='employment',offer_only=mode=='offer')
    job=client.post('/api/recruitment/browser-worker/claim').json()['job'];result=targeted_result(job)
    result.pop('employmentOnly' if mode=='employment' else 'offerOnly')
    if mode=='employment':result.pop('employmentHistoryScope')
    url=f'/api/recruitment/browser-worker/{identifier}/complete'
    assert client.post(url,json={'lease':job['lease'],'snapshot':result}).status_code==400
    assert not objects and queue.get(identifier)['status']=='running'
    result=targeted_result(job);result['requestedJobNumbers']=['out-of-scope']
    assert client.post(url,json={'lease':job['lease'],'snapshot':result}).status_code==400
    assert not objects


@pytest.mark.parametrize('mode',['employment','offer'])
def test_targeted_query_cancellation_releases_pending_work_without_a_snapshot(worker,monkeypatch,mode):
    from threading import Event
    from bonus_platform.engine.recruitment_cancellation import ACTIVE,PreparationCancelled
    client,path,objects=worker;event=Event();token=ACTIVE.set(event)
    monkeypatch.setattr(queue.time,'sleep',lambda _:event.set())
    try:
        with pytest.raises(PreparationCancelled):
            queue.QueuedClient().fetch(202609,['zt-target'] if mode=='employment' else [],
                                       ['of-target'] if mode=='offer' else [],
                                       employment_only=mode=='employment',offer_only=mode=='offer')
    finally:ACTIVE.reset(token)
    assert client.post('/api/recruitment/browser-worker/claim').json()['job'] is None
    with sqlite3.connect(path) as db:assert db.execute('SELECT status FROM sigma_recruitment_browser_jobs').fetchall()==[('failed',)]
    assert not objects


def test_queued_offer_repair_preserves_manual_values_and_original_sources(worker,monkeypatch,tmp_path):
    import bonus_platform.auth as auth
    from bonus_platform.engine import recruitment_overseas as overseas
    from bonus_platform.engine.recruitment_drafts import DraftStore
    from test_recruitment_overseas import snapshot
    client,_,_=worker;store=DraftStore(tmp_path/'protected');initial=snapshot(202609)
    initial.update(offers=[],missingOfferCodes=['OF1'])
    before=store.save_overseas_snapshot(202609,0,initial);rid=before['rows'][0]['id']
    before=store.change(202609,before['revision'],{'edits':[{'rowId':rid,'field':'招聘负责人姓名','value':'人工负责人','reason':'合成验证'}]})
    original=(store._folder(202609)/'sources'/before['sources'][0]['storedName']).read_bytes()
    monkeypatch.setattr(auth,'production_runtime',lambda:True)
    def execute(_):
        job=client.post('/api/recruitment/browser-worker/claim').json()['job'];result=snapshot(202609)
        result.update(offerOnly=True,roster=[],requestedOfferCodes=job['offerCodes'])
        assert client.post(f"/api/recruitment/browser-worker/{job['id']}/complete",json={'lease':job['lease'],'snapshot':result}).status_code==200
    monkeypatch.setattr(queue.time,'sleep',execute)
    result=overseas.fetch_offers(202609,['OF1']);after=store.save_overseas_snapshot(202609,before['revision'],result)
    assert len(after['rows'])==1 and after['rows'][0]['offerMatched']
    assert after['rows'][0]['values']['招聘负责人姓名']=='人工负责人' and after['edits']==before['edits']
    assert (store._folder(202609)/'sources'/before['sources'][0]['storedName']).read_bytes()==original
