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
