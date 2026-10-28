import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bonus_platform.engine.recruitment_trials import ScopedDraftStore
from test_recruitment_adoption import fill_month, snapshot
from test_recruitment_drafts import book


@pytest.fixture
def activities(tmp_path,monkeypatch):
    import bonus_platform.recruitment_draft_api as api
    store=ScopedDraftStore(tmp_path/'drafts');monkeypatch.setattr(api,'store',store)
    app=FastAPI()
    for router in (api.activities_router,api.activity_drafts_router,api.router,api.trials_router,api.trial_drafts_router):app.include_router(router)
    return TestClient(app),store


def create(client,name='七月活动',month=202607,**extra):
    response=client.post('/api/recruitment/activities',json={'name':name,'month':month,**extra})
    assert response.status_code==200,response.text
    return response.json()


def base(item,trial=''):
    return f"/api/recruitment/activities/{item['id']}"+(f'/api/recruitment/trials/{trial}' if trial else '')+f"/api/recruitment/drafts/{item['month']}"


def test_same_month_activities_and_legacy_are_independent(activities):
    client,store=activities
    original=fill_month(client,'/api/recruitment/drafts/202607',202607,'旧记录')
    before=snapshot(store.base_root)
    a=create(client,'同名活动');b=create(client,'同名活动')
    assert a['id']!=b['id']
    results=[]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda args:fill_month(client,base(args[0]),202607,args[1]),[(a,'活动甲'),(b,'活动乙')]))
    for item,name in ((a,'活动甲'),(b,'活动乙')):
        state=client.get(base(item)).json()
        assert state['activity']['id']==item['id'] and state['rows'][0]['values']['姓名']==name
        assert state['previousConfirmed'] is None
    source=results[0]['sources'][0]['id']
    assert client.get(base(b)+'/sources/'+source).status_code!=200
    assert snapshot(store.base_root)==before
    assert len(client.get('/api/recruitment/activities').json()['legacyRecords'])==1
    assert client.get(base(a).replace('202607','202608')).status_code==400


def test_review_name_lookup_does_not_search_other_activities(activities):
    client,store=activities
    a=create(client,'活动甲');b=create(client,'活动乙')
    headers=['姓名','工号','入职日期','人员状态','人员来源']
    states=[]
    for activity,name,number in ((a,'甲专属人员','zt-a'),(b,'乙专属人员','zt-b')):
        response=client.post(base(activity)+'/sources',data={'revision':0,'periodConfirmed':'true'},
                             files=[('files',('花名册.xlsx',book(headers,[[name,number,'2026-07-01','正式','OEHR入职']])))] )
        assert response.status_code==200,response.text
        states.append(response.json())
    before=snapshot(store.activity_root)
    reply=client.get(base(a)+'/people',params={'revision':states[0]['revision'],'q':'专属人员'})
    assert reply.status_code==200
    assert [p['employeeId'] for p in reply.json()['people']]==['zt-a']
    assert client.get(base(a)+'/people',params={'revision':states[0]['revision'],'q':'乙专属人员'}).json()['people']==[]
    assert snapshot(store.activity_root)==before


def test_trial_preview_adoption_and_files_stay_in_activity(activities):
    client,store=activities;a=create(client);b=create(client)
    target=fill_month(client,base(a),202607,'原活动人员')
    fill_month(client,base(b),202607,'另一个活动')
    before=snapshot(store.activity_root/b['id'])
    prefix=f"/api/recruitment/activities/{a['id']}"
    trial=client.post(prefix+'/api/recruitment/trials',json={'month':202607}).json()
    src=base(a,trial['id']);state=fill_month(client,src,202607,'重新核算人员')
    assert client.get(base(b,trial['id'])).status_code==400
    assert client.get('/api/recruitment/trials').json()==[]
    assert client.post(prefix+'/api/recruitment/trials',json={'month':202608}).status_code==400
    preview=client.get(src+'/adoption-preview',params={'sourceRevision':state['revision']}).json()
    assert a['id'] in preview['returnUrl']
    adopted=client.post(src+'/adopt-month',json={'sourceRevision':state['revision'],'targetRevision':target['revision'],'coverageConfirmed':True})
    assert adopted.status_code==200,adopted.text
    assert a['id'] in adopted.json()['url']
    current=client.get(base(a)).json()
    assert current['rows'][0]['values']['姓名']=='重新核算人员'
    assert client.get(base(a)+f"/monthly/export?revision={current['revision']}").status_code==200
    assert snapshot(store.activity_root/b['id'])==before
    assert not (store.base_root/'202607'/'draft.json').exists()


def test_archive_restore_and_stale_management(activities):
    client,store=activities;a=create(client);state=fill_month(client,base(a),202607,'归档人员')
    path=f"/api/recruitment/activities/{a['id']}"
    renamed=client.patch(path,json={'version':1,'name':'修订名称'}).json()
    assert renamed['version']==2 and renamed['name']=='修订名称'
    assert client.patch(path,json={'version':1,'name':'过期名称'}).status_code==409
    before=snapshot(store.activity_root/a['id']/'drafts')
    assert client.patch(path,json={'version':2,'archived':True}).status_code==200
    assert client.get(base(a)).status_code==200
    for suffix,payload in [('/prepare',{'revision':state['revision']}),('/refresh',{'revision':state['revision']}),('/changes',{'revision':state['revision'],'supplement':{'姓名':'不可写入'}})]:
        assert client.post(base(a)+suffix,json=payload).status_code==409
    assert client.post(path+'/api/recruitment/trials',json={'month':202607}).status_code==409
    assert snapshot(store.activity_root/a['id']/'drafts')==before
    assert client.patch(path,json={'version':3,'archived':False}).status_code==200
    assert client.post(base(a)+'/refresh',json={'revision':state['revision']}).status_code==200


def test_explicit_previous_copy_is_snapshot_not_shared_data(activities):
    client,store=activities;previous=create(client,'七月')
    state=fill_month(client,base(previous),202607,'上月人员')
    assert client.post(base(previous)+'/confirm-month',json={'revision':state['revision'],'coverageConfirmed':True}).status_code==200
    blank=create(client,'八月空白',202608)
    assert client.get(base(blank)).json()['previousConfirmed'] is None
    before=snapshot(store.activity_root/previous['id']/'drafts')
    child=create(client,'八月承接',202608,opening={'activityId':previous['id'],'revision':state['revision']})
    result=client.get(base(child)).json()
    assert result['parentMonth']==202607 and result['rows'][0]['values']['姓名']=='上月人员'
    assert result['previousConfirmed']['revision']==state['revision']
    material=result['sources'][0]
    p=store.activity_root/child['id']/'drafts'/'202608'/'sources'/material['storedName']
    original=store.activity_root/previous['id']/'drafts'/'202607'/'sources'/material['storedName']
    assert p.read_bytes()==original.read_bytes() and p.stat().st_ino!=original.stat().st_ino
    assert snapshot(store.activity_root/previous['id']/'drafts')==before
    assert client.post('/api/recruitment/activities',json={'month':202609,'opening':{'activityId':previous['id'],'revision':state['revision']}}).status_code==400
    assert client.post('/api/recruitment/activities',json={'month':202608,'opening':{'activityId':previous['id'],'revision':0}}).status_code==409


def test_background_sync_context_and_archive_guard(activities,monkeypatch):
    import threading,time
    from bonus_platform.engine import recruitment_beisen
    client,store=activities;a=create(client);b=create(client)
    state=client.post(base(a)+'/sources',data={'revision':0,'periodConfirmed':'true'},files=[('files',('花名册.xlsx',book(['姓名','工号','入职日期','人员状态','人员来源'],[['同步人员','zt1','2026-07-01','正式','EHR入职']])))]).json()
    assert state['rows'][0]['values']['标签分类']=='国内'
    entered=threading.Event();release=threading.Event()
    def fetch(*args,**kwargs):
        entered.set();assert release.wait(5)
        return {'version':1,'queriedAt':'2026-09-30T10:00:00','scopeJobNumbers':['zt1'],'scopeRecipientJobNumbers':[], 'candidateHistories':[],'recipientHistories':[],'offers':[],'requirements':[],'forms':[]}
    monkeypatch.setattr(recruitment_beisen,'fetch',fetch)
    assert client.post(base(a)+'/prepare',json={'revision':state['revision'],'force':True}).status_code==200
    try:
        assert entered.wait(3)
        assert client.patch(f"/api/recruitment/activities/{a['id']}",json={'version':1,'archived':True}).status_code==409
    finally:release.set()
    for _ in range(100):
        job=client.get(base(a)+'/prepare').json()
        if job['status']!='running':break
        time.sleep(.02)
    assert job['status']=='complete',job
    assert any(s.get('kind')=='beisen' for s in client.get(base(a)).json()['sources'])
    assert client.get(base(b)).json()['sources']==[]
    assert not (store.base_root/'202607'/'prepare.json').exists()


@pytest.mark.parametrize('payload',[{'month':202613},{'month':'202607'},{'month':True},{'month':202607,'name':'x'*61}])
def test_invalid_activity_input(activities,payload):
    client,_=activities
    assert client.post('/api/recruitment/activities',json=payload).status_code==400


def test_activity_list_reads_saved_summaries_without_rebuilding_drafts(activities,monkeypatch):
    from bonus_platform.engine.recruitment_drafts import DraftStore
    from bonus_platform.engine import recruitment_prepare as jobs
    client,store=activities;activity=create(client)
    folder=store.activity_root/activity['id']
    saved={'month':202607,'revision':4,'rows':[{},{}],'sources':[{}],'updatedAt':'2026-07-30T10:00:00'}
    store._write(folder/'drafts/202607/draft.json',saved)
    store._write(folder/'drafts/202607/accepted-status.json',{'revision':4})
    store._write(folder/'drafts/202607/prepare.json',{'status':'complete'})
    store._write(folder/'recruitment_trials'/('a'*32)/'drafts/202607/draft.json',
                 {**saved,'updatedAt':'2099-07-31T10:00:00'})
    store._write(store.base_root/'202607/draft.json',saved)
    before=snapshot(store.activity_root)
    def unexpected(*args,**kwargs):pytest.fail('Listing activities must not validate or calculate full drafts')
    monkeypatch.setattr(DraftStore,'read',unexpected)
    monkeypatch.setattr(jobs,'coverage_gaps',unexpected)
    result=client.get('/api/recruitment/activities')
    assert result.status_code==200,result.text
    item=result.json()['activities'][0]
    assert (item['people'],item['sources'],item['records'],item['status'],item['confirmedRevision'])==(2,1,1,'已确认',4)
    assert item['updatedAt']=='2099-07-31T10:00:00'
    assert result.json()['legacyRecords'][0]['people']==2
    assert snapshot(store.activity_root)==before


@pytest.mark.parametrize('status,active,expected',[
    ('running',True,'正在整理'),('cancelling',True,'正在整理'),
    ('running',False,'核算中'),('cancelling',False,'核算中'),
    ('complete',False,'核算中'),('cancelled',False,'核算中')])
def test_activity_list_preserves_live_preparation_status(activities,monkeypatch,status,active,expected):
    from bonus_platform.engine import recruitment_prepare as jobs
    client,store=activities;activity=create(client);folder=store.activity_root/activity['id']/'drafts/202607'
    store._write(folder/'draft.json',{'month':202607,'revision':1,'rows':[],'sources':[]})
    store._write(folder/'prepare.json',{'status':status})
    monkeypatch.setattr(jobs,'RUNNING',{str(folder/'prepare.json'):'job'} if active else {})
    result=client.get('/api/recruitment/activities')
    assert result.status_code==200,result.text
    assert result.json()['activities'][0]['status']==expected


def test_activity_list_summary_updates_after_saved_draft_changes(activities):
    client,store=activities;activity=create(client)
    path=store.activity_root/activity['id']/'drafts/202607/draft.json'
    saved={'month':202607,'revision':1,'rows':[{}],'sources':[],'updatedAt':'2099-07-01T10:00:00'}
    store._write(path,saved)
    store._write(store.base_root/'202607/draft.json',saved)
    result=client.get('/api/recruitment/activities').json()
    assert result['activities'][0]['people']==result['legacyRecords'][0]['people']==1
    saved.update(revision=2,rows=[{},{}],sources=[{}],updatedAt='2099-07-02T10:00:00')
    store._write(path,saved)
    store._write(store.base_root/'202607/draft.json',saved)
    result=client.get('/api/recruitment/activities').json()
    for key in ('activities','legacyRecords'):
        assert (result[key][0]['people'],result[key][0]['sources'],result[key][0]['updatedAt'])==(2,1,'2099-07-02T10:00:00')


def test_creator_uses_session_and_survives_other_user_updates(activities,monkeypatch):
    import sys
    from types import ModuleType
    client,store=activities
    auth=ModuleType('bonus_platform.auth')
    current={'user':{'id':'user-a','name':'创建人甲','avatarUrl':'https://example.com/avatar.png','email':'private@example.com'}}
    auth.current_user_from_request=lambda request:current
    monkeypatch.setitem(sys.modules,'bonus_platform.auth',auth)
    item=create(client,creator={'userId':'forged','name':'伪造创建人'})
    expected={'userId':'user-a','name':'创建人甲','avatarUrl':'https://example.com/avatar.png'}
    assert item['creator']==expected
    assert store.activity(item['id'])['creator']==expected
    current['user']={'id':'user-b','name':'其他用户'}
    response=client.get('/api/recruitment/activities').json()
    assert response['currentUserId']=='user-b'
    assert response['activities'][0]['creator']==expected
    changed=client.patch('/api/recruitment/activities/'+item['id'],json={'name':'改名','version':1})
    assert changed.status_code==200
    assert changed.json()['creator']==expected
    assert client.patch('/api/recruitment/activities/'+item['id'],json={'creator':{'name':'替换'},'version':2}).status_code==400


def test_missing_creator_does_not_relabel_old_activities(activities,monkeypatch):
    import sys
    from types import ModuleType
    client,store=activities
    auth=ModuleType('bonus_platform.auth');auth.current_user_from_request=lambda request:None
    monkeypatch.setitem(sys.modules,'bonus_platform.auth',auth)
    item=create(client,creator={'name':'不能从请求填写'})
    assert item['creator']=={'userId':'','name':'','avatarUrl':''}
    path=store.activity_root/item['id']/'activity.json'
    old=json.loads(path.read_text());old.pop('creator');path.write_text(json.dumps(old))
    before=path.read_bytes()
    auth.current_user_from_request=lambda request:{'user':{'id':'later','name':'后来查看的人'}}
    result=client.get('/api/recruitment/activities').json()
    assert result['currentUserId']=='later'
    assert not result['activities'][0].get('creator')
    assert path.read_bytes()==before
