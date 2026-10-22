from copy import deepcopy
from threading import Event
import time

import pytest

from bonus_platform.engine import recruitment_domestic as domestic
from bonus_platform.engine import recruitment_overseas as overseas
from bonus_platform.engine import recruitment_prepare as jobs
from bonus_platform.engine.recruitment_drafts import DraftStore
from test_recruitment_activities import activities, base, create
from test_recruitment_domestic_monthly import snapshot as domestic_snapshot
from test_recruitment_overseas import snapshot as overseas_snapshot
from test_recruitment_prepare_cancellation import settled


MONTH=202608


def payloads(monkeypatch, failures=()):
    calls=[]
    for name,module,fixture in [('domestic',domestic,domestic_snapshot),('overseas',overseas,overseas_snapshot)]:
        def fetch(month,*,name=name,fixture=fixture,**kwargs):
            calls.append(name)
            if name in failures:raise ValueError('接口暂未返回完整资料')
            value=fixture(month)
            if name=='domestic':
                value['roster'][0]['工号']='zt101'
                for history in value['candidateHistories']:history['jobNumber']='zt101'
                value['scopeJobNumbers']=['zt101']
            return value
        monkeypatch.setattr(module,'fetch',fetch)
    return calls


def test_one_action_syncs_both_sources_and_deduplicates_retry(activities,monkeypatch):
    client,store=activities;activity=create(client,month=MONTH);url=base(activity)
    calls=payloads(monkeypatch)
    response=client.post(url+'/sync-monthly',json={'revision':0})
    assert response.status_code==200,response.text
    assert response.json()['monthlyAll'] is True
    def completed():
        for _ in range(500):
            result=client.get(url+'/prepare').json()
            if result['status'] not in {'running','cancelling'}:return result
            time.sleep(.01)
        pytest.fail('Combined sync did not finish')
    result=completed();assert result['status']=='complete',result
    assert calls==['domestic','overseas']
    state=client.get(url).json()
    assert {r['values']['工号'] for r in state['rows']}=={'zt101','zt1'}
    assert {s['kind'] for s in state['sources']}=={'beisen','overseas_api'}
    assert all(item['status']=='complete' for item in result['syncResults'].values())
    assert {item['sourceId'] for item in result['syncResults'].values()}=={s['id'] for s in state['sources']}
    assert '已有核算与待办保留' not in result['message']
    assert client.post(url+'/sync-monthly',json={'revision':state['revision']}).status_code==200
    repeated=completed()
    assert repeated['status']=='complete' and repeated['revision']==state['revision']
    assert all(item['reused'] for item in repeated['syncResults'].values())


@pytest.mark.parametrize('failed',['domestic','overseas'])
def test_one_failed_source_does_not_hide_or_discard_the_successful_source(tmp_path,monkeypatch,failed):
    store=DraftStore(tmp_path);calls=payloads(monkeypatch,{failed})
    jobs.start(store,MONTH,0,monthly_all=True);result=settled(store)
    assert calls==['domestic','overseas']
    assert result['status']=='failed' and result['revision']==1
    assert result['syncResults'][failed]['status']=='failed'
    success='overseas' if failed=='domestic' else 'domestic'
    assert result['syncResults'][success]['status']=='complete'
    assert '已保留' in result['message'] and '未完成' in result['message']
    assert len(store.read(MONTH)['sources'])==1
    payloads(monkeypatch)
    jobs.start(store,MONTH,1,monthly_all=True);retry=settled(store)
    assert retry['status']=='complete' and retry['syncResults'][success]['reused']
    assert len(store.read(MONTH)['sources'])==2


def test_sync_keeps_old_sources_revision_results_and_pending_work(tmp_path,monkeypatch):
    store=DraftStore(tmp_path);payloads(monkeypatch)
    jobs.start(store,MONTH,0,monthly_all=True);settled(store)
    state=store.read(MONTH)
    protected={k:deepcopy(state.get(k)) for k in ('rows','todos','edits','operations','awardDecisions','installmentPlans')}
    files={p:p.read_bytes() for folder in ('sources','revisions') for p in (store._folder(MONTH)/folder).glob('*.json')}
    for module in (domestic,overseas):
        original=module.fetch
        def changed(month,*,original=original,**options):
            value=original(month,**options);value['queriedAt']='2026-10-23T10:00:00+08:00'
            raw=value['roster'][0];raw=raw.get('data',raw)
            raw['人员状态']='已离职';raw['离职日期']='2026-10-23'
            return value
        monkeypatch.setattr(module,'fetch',changed)
    jobs.start(store,MONTH,state['revision'],monthly_all=True);result=settled(store)
    updated=store.read(MONTH)
    assert result['status']=='complete' and '已有核算与待办保留' in result['message']
    assert {k:updated.get(k) for k in protected}==protected
    assert all(s['snapshotOnly'] and s['comparisonOnly'] for s in updated['sources'][-2:])
    assert all(p.read_bytes()==content for p,content in files.items())


def test_stop_keeps_saved_first_source_and_never_saves_second_response(tmp_path,monkeypatch):
    store=DraftStore(tmp_path);payloads(monkeypatch);entered=Event();release=Event()
    def fetch(month,**kwargs):
        entered.set();assert release.wait(5)
        return overseas_snapshot(month)
    monkeypatch.setattr(overseas,'fetch',fetch)
    job=jobs.start(store,MONTH,0,monthly_all=True)
    try:
        assert entered.wait(3)
        assert jobs.start(store,MONTH,0,monthly_all=True)['id']==job['id']
        jobs.cancel(store,MONTH,job['id'])
    finally:release.set()
    result=settled(store)
    assert result['status']=='cancelled' and result['revision']==1
    assert result['syncResults']['domestic']['status']=='complete'
    assert [s['kind'] for s in store.read(MONTH)['sources']]==['beisen']


def test_edit_during_sync_rejects_stale_save_without_overwriting_the_edit(tmp_path,monkeypatch):
    store=DraftStore(tmp_path);payloads(monkeypatch);entered=Event();release=Event()
    def fetch(month,**kwargs):
        entered.set();assert release.wait(5)
        return overseas_snapshot(month)
    monkeypatch.setattr(overseas,'fetch',fetch)
    jobs.start(store,MONTH,0,monthly_all=True)
    try:
        assert entered.wait(3)
        state=store.read(MONTH)
        edited=store.change(MONTH,state['revision'],{'edits':[{'rowId':state['rows'][0]['id'],
            'field':'招聘负责人姓名','value':'核对后的负责人','reason':'人工确认'}]})
    finally:release.set()
    result=settled(store)
    assert result['status']=='failed' and '已更新' in result['message']
    assert store.read(MONTH)['rows']==edited['rows']
    assert not any(s['kind']=='overseas_api' for s in store.read(MONTH)['sources'])


def test_overseas_new_domestic_recipients_are_completed_in_the_same_click(tmp_path,monkeypatch):
    from bonus_platform.engine import recruitment_beisen as beisen
    store=DraftStore(tmp_path);payloads(monkeypatch);original=overseas.fetch;calls=[]
    def foreign(month,**options):
        value=original(month,**options)
        value['roster'].append({'scope':'lookup','data':{'工号':'zt2','入职日期':'2020-01-01',
                               '人员来源':'EHR入职','人员状态':'正式'}})
        return value
    def employment(numbers,**options):
        calls.append(numbers)
        return beisen._with_coverage({'version':1,'employmentOnly':True,'queriedAt':'2026-10-22T19:00:00',
            'requestedJobNumbers':[],'requestedRecipientJobNumbers':numbers,'candidateHistories':[],
            'recipientHistories':[{'jobNumber':'zt2','userID':2,'approvalStatus':4,'serviceType':0,
                                  'entryDate':'2020-01-01','startDate':'2020-01-01','stopDate':'9999-12-31'}],
            'offers':[],'forms':[],'requirements':[]})
    monkeypatch.setattr(overseas,'fetch',foreign);monkeypatch.setattr(beisen,'fetch_employment',employment)
    jobs.start(store,MONTH,0,monthly_all=True);result=settled(store)
    assert result['status']=='complete',result
    assert calls==[['zt2']]
    assert result['syncResults']['domestic']['relatedEmploymentPeople']==1
    state=store.read(MONTH)
    assert len(state['sources'])==3
    jobs.start(store,MONTH,state['revision'],monthly_all=True);result=settled(store)
    assert result['status']=='complete' and calls==[['zt2']]


def test_retry_completes_new_overseas_recipients_when_domestic_snapshot_changed(tmp_path,monkeypatch):
    from bonus_platform.engine import recruitment_beisen as beisen
    store=DraftStore(tmp_path);payloads(monkeypatch,{'overseas'})
    jobs.start(store,MONTH,0,monthly_all=True);first=settled(store)
    assert first['status']=='failed'
    initial=store.read(MONTH);original=initial['sources'][0]
    original_path=store._folder(MONTH)/'sources'/original['storedName']
    original_bytes=original_path.read_bytes()

    payloads(monkeypatch);original_domestic=domestic.fetch;original_overseas=overseas.fetch;calls=[]
    def changed(month,**options):
        value=original_domestic(month,**options)
        value['roster'][0]['姓名']='后续观察姓名'
        return value
    def foreign(month,**options):
        value=original_overseas(month,**options)
        value['roster'].append({'scope':'lookup','data':{'工号':'zt2','入职日期':'2020-01-01',
                               '人员来源':'EHR入职','人员状态':'正式'}})
        return value
    def employment(numbers,**options):
        calls.append(numbers)
        return beisen._with_coverage({'version':1,'employmentOnly':True,'queriedAt':'2026-10-22T19:00:00',
            'requestedJobNumbers':[],'requestedRecipientJobNumbers':numbers,'candidateHistories':[],
            'recipientHistories':[{'jobNumber':'zt2','userID':2,'approvalStatus':4,'serviceType':0,
                                  'entryDate':'2020-01-01','startDate':'2020-01-01','stopDate':'9999-12-31'}],
            'offers':[],'forms':[],'requirements':[]})
    monkeypatch.setattr(domestic,'fetch',changed)
    monkeypatch.setattr(overseas,'fetch',foreign)
    monkeypatch.setattr(beisen,'fetch_employment',employment)
    jobs.start(store,MONTH,initial['revision'],monthly_all=True);retry=settled(store)
    assert retry['status']=='complete',retry
    assert retry['syncResults']['domestic']['snapshotOnly']
    assert not retry['syncResults']['overseas']['snapshotOnly']
    state=store.read(MONTH)
    assert 'zt2' in beisen.coverage_sets(state['sources'])['recipientEmployment']
    assert calls==[['zt2']]
    foreign_row=next(r for r in state['rows'] if r['values']['工号']=='zt1')
    assert foreign_row['employmentTimelines']['招聘负责人'][0]['provider']=='beisen'
    domestic_row=next(r for r in state['rows'] if r['values']['工号']=='zt101')
    assert domestic_row['values']['姓名']!='后续观察姓名'
    assert original_path.read_bytes()==original_bytes
    jobs.start(store,MONTH,state['revision'],monthly_all=True);repeated=settled(store)
    assert repeated['status']=='complete' and calls==[['zt2']]
    assert store.read(MONTH)['revision']==state['revision']
    protected={k:deepcopy(state.get(k)) for k in ('rows','todos','edits','operations')}
    def changed_foreign(month,**options):
        value=foreign(month,**options)
        value['offers'][0].update(协助招聘负责人工号='zt3',协助招聘负责人姓名='新增协助人')
        value['roster'].append({'scope':'lookup','data':{'工号':'zt3','入职日期':'2020-01-01',
                               '人员来源':'EHR入职','人员状态':'正式'}})
        return value
    monkeypatch.setattr(overseas,'fetch',changed_foreign)
    jobs.start(store,MONTH,state['revision'],monthly_all=True);comparison=settled(store)
    assert comparison['status']=='complete' and comparison['syncResults']['overseas']['snapshotOnly']
    current=store.read(MONTH)
    assert {k:current.get(k) for k in protected}==protected
    assert calls==[['zt2']]
    assert 'zt3' not in beisen.coverage_sets(current['sources'])['recipientEmployment']
