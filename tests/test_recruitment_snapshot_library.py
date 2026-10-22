from copy import deepcopy
from datetime import datetime
from threading import Event
from zoneinfo import ZoneInfo

import pytest

from bonus_platform.engine.recruitment_snapshot_library import SnapshotLibrary, SnapshotScheduler
from bonus_platform.engine.recruitment_trials import ScopedDraftStore
from bonus_platform.engine import recruitment_domestic as domestic, recruitment_overseas as overseas
from test_recruitment_activities import activities, base, create
from test_recruitment_monthly_sync import payloads, MONTH
from test_recruitment_adoption import snapshot as file_snapshot


def test_new_activity_adopts_shared_inputs_without_hr_calls(activities,monkeypatch):
    client,store=activities;calls=payloads(monkeypatch);library=SnapshotLibrary(store)
    assert library.refresh(MONTH)['job']['status']=='complete'
    assert calls==['domestic','overseas']
    a=create(client,month=MONTH);b=create(client,month=MONTH)
    assert calls==['domestic','overseas']
    for activity in (a,b):
        state=client.get(base(activity)).json()
        assert {r['values']['工号'] for r in state['rows']}=={'zt101','zt1'}
        assert set(activity['snapshotSources'])=={'domestic','overseas'}
        assert all(not s['comparisonOnly'] for s in state['sources'])
    other=create(client,month=202609)
    assert client.get(base(other)).json()['rows']==[]


def test_cached_activity_files_are_independent_and_manual_edits_survive_refresh(activities,monkeypatch):
    from bonus_platform.engine import recruitment_prepare as jobs
    client,store=activities;payloads(monkeypatch);library=SnapshotLibrary(store);library.refresh(MONTH)
    a=create(client,month=MONTH);url=base(a)
    state=client.get(url).json();row=next(r for r in state['rows'] if r['values']['工号']=='zt101')
    updated=client.post(url+'/changes',json={'revision':state['revision'],'edits':[{'rowId':row['id'],'field':'招聘负责人姓名','value':'人工核对负责人','reason':'业务核实'}]})
    assert updated.status_code==200,updated.text
    path=store.activity_root/a['id'];before=file_snapshot(path)
    original=domestic.fetch
    def changed(month,**options):
        value=original(month,**options);value['queriedAt']='2026-10-23T08:00:00+08:00';value['roster'][0]['姓名']='后台新姓名';return value
    monkeypatch.setattr(domestic,'fetch',changed)
    library.refresh(MONTH)
    assert file_snapshot(path)==before
    state=client.get(url).json();protected={k:deepcopy(state[k]) for k in ('rows','todos','activeOperations')}
    assert client.post(url+'/sync-monthly',json={'revision':state['revision']}).status_code==200
    # Poll the actual activity-scoped job through HTTP.
    import time
    for _ in range(500):
        job=client.get(url+'/prepare').json()
        if job['status'] not in {'running','cancelling'}:break
        time.sleep(.01)
    assert job['status']=='complete',job
    current=client.get(url).json()
    assert {k:current[k] for k in protected}==protected
    new=create(client,month=MONTH)
    assert any(r['values']['姓名']=='后台新姓名' for r in client.get(base(new)).json()['rows'])
    assert any(r['values'].get('招聘负责人姓名')=='人工核对负责人' for r in current['rows'])


@pytest.mark.parametrize('failed',['domestic','overseas'])
def test_failed_refresh_keeps_previous_source_and_all_versions(tmp_path,monkeypatch,failed):
    store=ScopedDraftStore(tmp_path/'drafts');library=SnapshotLibrary(store);payloads(monkeypatch)
    library.refresh(MONTH);before=library.current(MONTH)
    files=file_snapshot(library._folder(MONTH)/'versions')
    payloads(monkeypatch,{failed});result=library.refresh(MONTH)
    assert result['job']['status']=='failed'
    assert result['job']['sources'][failed]['status']=='failed'
    assert library.current(MONTH)[failed]==before[failed]
    assert file_snapshot(library._folder(MONTH)/'versions')==files


def test_corrupt_snapshot_cannot_create_half_an_activity(activities,monkeypatch):
    client,store=activities;payloads(monkeypatch);library=SnapshotLibrary(store);library.refresh(MONTH)
    entry=library.current(MONTH)['overseas']
    path=library._folder(MONTH)/'versions'/'overseas'/(entry['id']+'.json');path.write_text('{}')
    response=client.post('/api/recruitment/activities',json={'month':MONTH})
    assert response.status_code==400,response.text
    assert not list(store.activity_root.glob('*/activity.json'))


def test_schedule_runs_once_per_beijing_day_and_catches_up_after_restart(tmp_path,monkeypatch):
    store=ScopedDraftStore(tmp_path/'drafts');library=SnapshotLibrary(store);calls=payloads(monkeypatch)
    tz=ZoneInfo('Asia/Shanghai')
    assert not library.tick(datetime(2026,10,23,7,59,tzinfo=tz))
    assert library.tick(datetime(2026,10,23,8,0,tzinfo=tz))
    assert len(calls)==4
    assert not SnapshotLibrary(store).tick(datetime(2026,10,23,22,0,tzinfo=tz))
    assert library.tick(datetime(2026,10,24,12,0,tzinfo=tz))
    assert len(calls)==8
    library.configure({'enabled':False,'hour':9,'minute':30})
    assert not library.tick(datetime(2026,10,25,12,0,tzinfo=tz))


def test_refresh_single_flight_and_interrupted_receipt(tmp_path,monkeypatch):
    store=ScopedDraftStore(tmp_path/'drafts');library=SnapshotLibrary(store);calls=payloads(monkeypatch)
    with library.lock('.refresh-lock') as locked:
        assert locked
        with pytest.raises(ValueError,match='正在同步'):library.refresh(MONTH)
    assert calls==[]
    library.files._write(library._folder(MONTH)/'job.json',{'status':'running','sources':{}})
    assert library.status(MONTH)['job']['status']=='interrupted'
    stop=Event();stop.set();assert library.refresh(MONTH,stop)['job']['status']=='interrupted'


def test_refresh_scope_contains_active_history_without_copying_decisions(activities,monkeypatch):
    client,store=activities;a=create(client,month=MONTH);library=SnapshotLibrary(store)
    from test_recruitment_adoption import fill_month
    fill_month(client,base(a),MONTH,'历史奖金人员')
    before=file_snapshot(store.activity_root)
    calls=payloads(monkeypatch);captured=[];fetch=overseas.fetch
    def inspect(month,**options):captured.append(options);return fetch(month,**options)
    monkeypatch.setattr(overseas,'fetch',inspect)
    library.refresh(MONTH)
    assert captured and captured[0]['job_numbers']
    assert file_snapshot(store.activity_root)==before
    assert MONTH in library.months(datetime(2026,10,23,tzinfo=ZoneInfo('Asia/Shanghai')))


def test_schedule_api_and_manual_refresh_are_available(activities,monkeypatch):
    client,store=activities;payloads(monkeypatch)
    response=client.patch('/api/recruitment/activities/snapshot-library/schedule',json={'enabled':True,'hour':6,'minute':30})
    assert response.status_code==200,response.text
    assert response.json()['timezone']=='Asia/Shanghai'
    assert client.patch('/api/recruitment/activities/snapshot-library/schedule',json={'enabled':True,'hour':25,'minute':0}).status_code==400
    response=client.post('/api/recruitment/activities/snapshot-library/202608/refresh')
    assert response.status_code==200,response.text
    store.snapshot_refresh_thread.join(timeout=10)
    data=client.get('/api/recruitment/activities/snapshot-library/202608').json()
    assert data['job']['status']=='complete'
    assert set(data['snapshots'])=={'domestic','overseas'}


def test_opening_history_and_its_manual_correction_survive_shared_adoption(activities,monkeypatch):
    from test_recruitment_adoption import fill_month
    client,store=activities;parent=create(client,month=202607)
    state=fill_month(client,base(parent),202607,'上月奖金人员')
    row=state['rows'][0]
    state=client.post(base(parent)+'/changes',json={'revision':state['revision'],'edits':[{'rowId':row['id'],'field':'招聘负责人姓名','value':'上月人工负责人','reason':'上月已核对'}]}).json()
    response=client.post(base(parent)+'/confirm-month',json={'revision':state['revision'],'coverageConfirmed':True})
    assert response.status_code==200,response.text
    protected=file_snapshot(store.activity_root/parent['id'])
    payloads(monkeypatch);SnapshotLibrary(store).refresh(MONTH)
    child=create(client,month=MONTH,opening={'activityId':parent['id'],'revision':state['revision']})
    result=client.get(base(child)).json()
    assert result['parentMonth']==202607
    assert len(result['rows'])==3
    assert any(r['values'].get('招聘负责人姓名')=='上月人工负责人' for r in result['rows'])
    assert file_snapshot(store.activity_root/parent['id'])==protected


def test_service_lifecycle_starts_and_stops_the_daily_worker(tmp_path,monkeypatch):
    entered=Event()
    monkeypatch.setattr(SnapshotLibrary,'tick',lambda *a,**kw:entered.set())
    store=ScopedDraftStore(tmp_path/'drafts');scheduler=SnapshotScheduler(store).start()
    assert entered.wait(2)
    assert store.snapshot_scheduler_running
    scheduler.close()
    assert not scheduler.thread.is_alive()
    assert not store.snapshot_scheduler_running


def test_overseas_domestic_recipients_are_included_before_publishing(tmp_path,monkeypatch):
    from bonus_platform.engine import recruitment_beisen as beisen
    store=ScopedDraftStore(tmp_path/'drafts');payloads(monkeypatch);original=overseas.fetch
    def fetch(month,**kwargs):
        value=original(month,**kwargs)
        value['roster'].append({'scope':'lookup','data':{'工号':'zt2','姓名':'跨系统领取人','入职日期':'2020-01-01','人员来源':'EHR入职'}})
        return value
    captured=[]
    def extra(numbers,**kwargs):
        captured.extend(numbers)
        return {'recipientHistories':[{'jobNumber':'zt2','approvalStatus':4}],'employeeMappings':[]}
    monkeypatch.setattr(overseas,'fetch',fetch);monkeypatch.setattr(beisen,'fetch_employment',extra)
    library=SnapshotLibrary(store);result=library.refresh(MONTH)
    assert result['job']['status']=='complete',result
    assert captured==['zt2']
    saved=library.load(MONTH,'domestic',library.current(MONTH)['domestic'])
    assert any(h['jobNumber']=='zt2' for h in saved['recipientHistories'])
