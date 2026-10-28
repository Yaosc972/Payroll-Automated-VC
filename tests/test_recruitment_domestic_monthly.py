from copy import deepcopy

import pytest

from bonus_platform.engine.recruitment_drafts import DraftStore, DraftConflict
from test_recruitment_beisen import snapshot as employment_snapshot
from test_recruitment_drafts import book
from test_recruitment_activities import activities


def snapshot(month=202607):
    value=employment_snapshot()
    value.update(month=month,monthlyRoster=True,roster=[{'姓名':'甲','工号':'zt1','证件号码':'',
        '入职日期':f'{month//100}-{month%100:02d}-01','人员状态':'正式','转正日期':'',
        '离职日期':'','人员来源':'EHR入职','是否虚拟员工':'否'}])
    return value


def test_monthly_domestic_sync_can_start_without_an_uploaded_roster(tmp_path):
    store=DraftStore(tmp_path)
    state=store.save_beisen_snapshot(202607,0,snapshot())
    assert [r['values']['工号'] for r in state['rows']]==['zt1']
    assert state['rows'][0]['values']['标签分类']=='国内'
    assert state['sources'][0]['monthlyRoster'] is True
    assert not state['sources'][0]['snapshotOnly']


def test_monthly_domestic_snapshots_do_not_replace_existing_rows_or_todos(tmp_path,monkeypatch):
    from bonus_platform.engine import recruitment_awards as awards
    store=DraftStore(tmp_path)
    before=store.ingest(202607,[('roster.xlsx',book(['姓名','工号','入职日期','人员状态','人员来源'],
            [['原姓名','zt1','2026-07-01','正式','EHR入职']]))],0)
    assert len(before['rows'])==1
    protected={key:deepcopy(before.get(key)) for key in ('rows','todos','edits','operations','awardDecisions')}
    def forbidden(*args):pytest.fail('Saving a monthly comparison must not recalculate the payroll')
    monkeypatch.setattr(awards,'calculate_draft',forbidden)
    state=store.save_beisen_snapshot(202607,before['revision'],snapshot())
    assert {key:state.get(key) for key in protected}==protected
    assert state['sources'][-1]['snapshotOnly'] and state['sources'][-1]['comparisonOnly']
    old=(tmp_path/'202607/sources'/state['sources'][-1]['storedName']).read_bytes()
    payload=snapshot();payload['queriedAt']='2026-10-22T19:00:00'
    repeated=store.save_beisen_snapshot(202607,state['revision'],payload)
    assert repeated['revision']==state['revision']
    payload['roster'][0]['人员状态']='已离职'
    updated=store.save_beisen_snapshot(202607,state['revision'],payload)
    assert updated['rows']==protected['rows'] and updated['todos']==protected['todos']
    assert (tmp_path/'202607/sources'/state['sources'][-1]['storedName']).read_bytes()==old


def test_wrong_month_or_stale_revision_never_saves_a_monthly_snapshot(tmp_path):
    store=DraftStore(tmp_path)
    with pytest.raises(ValueError,match='月份'):store.save_beisen_snapshot(202608,0,snapshot())
    assert not list(tmp_path.rglob('sources/*.json'))
    state=store.save_beisen_snapshot(202607,0,snapshot())
    with pytest.raises(DraftConflict):store.save_beisen_snapshot(202607,0,snapshot())
    assert store.read(202607)['revision']==state['revision']


@pytest.mark.parametrize('first',['domestic','overseas'])
def test_new_activity_accepts_both_monthly_sources_in_either_order(tmp_path,first):
    from test_recruitment_overseas import snapshot as overseas_snapshot
    store=DraftStore(tmp_path);domestic=snapshot(202608)
    domestic['roster'][0].update(姓名='国内人员',工号='zt101')
    for h in domestic['candidateHistories']:h['jobNumber']='zt101'
    domestic['scopeJobNumbers']=['zt101']
    actions={'domestic':lambda revision:store.save_beisen_snapshot(202608,revision,domestic),
             'overseas':lambda revision:store.save_overseas_snapshot(202608,revision,overseas_snapshot())}
    state=actions[first](0);state=actions['overseas' if first=='domestic' else 'domestic'](state['revision'])
    assert {r['values']['工号'] for r in state['rows']}=={'zt101','zt1'}


def test_comparison_snapshot_does_not_claim_applied_employee_coverage():
    from bonus_platform.engine.recruitment_beisen import coverage_sets
    source={'kind':'beisen','active':True,'comparisonOnly':True,
            'syncCoverage':{'candidates':{'zt1':{'requested':True,'employment':True,'offer':True}}}}
    assert coverage_sets([source])['candidateEmployment']==set()


def test_domestic_monthly_job_starts_with_no_people_and_retains_completed_message(activities,monkeypatch):
    import time
    from bonus_platform.engine import recruitment_domestic as domestic
    from bonus_platform.engine import recruitment_beisen as employment
    from test_recruitment_activities import create,base
    client,store=activities;activity=create(client)
    calls=[]
    def fetch(month,**options):calls.append(month);return snapshot(month)
    monkeypatch.setattr(domestic,'fetch',fetch)
    lookups=[]
    def fetch_employment(numbers,**options):
        lookups.append(numbers);result=employment_snapshot()
        result.update(employmentOnly=True,requestedJobNumbers=[],requestedRecipientJobNumbers=numbers,
                      recipientHistories=result['candidateHistories'],candidateHistories=[],offers=[],requirements=[],forms=[])
        return result
    monkeypatch.setattr(employment,'fetch_employment',fetch_employment)
    response=client.post(base(activity)+'/sync-domestic-monthly',json={'revision':0})
    assert response.status_code==200 and response.json()['domesticOnly']
    for _ in range(100):
        result=client.get(base(activity)+'/prepare').json()
        if result['status']!='running':break
        time.sleep(.01)
    assert result['status']=='complete',result
    assert result['message']=='国内资料已同步，本月核算已更新。'
    assert calls==[202607]
    assert lookups==[['zt1']]
    assert client.get(base(activity)).json()['sources'][0]['monthlyRoster']


def test_monthly_discovery_includes_leavers_and_excludes_virtual_oehr_and_pending(monkeypatch):
    from bonus_platform.engine import recruitment_domestic as domestic
    from bonus_platform.engine import recruitment_beisen as beisen
    def person(uid,status=3,custom=None,entry='2026-08-01'):
        return {'employeeInfo':{'userID':uid,'name':'甲','customProperties':custom or {}},
                'recordInfoList':[{'userID':uid,'jobNumber':f'zt{uid}','entryDate':entry,
                    'serviceType':0,'approvalStatus':4,'employeeStatus':status}]}
    people=[person(1,8),person(2,custom={domestic.VIRTUAL:True}),
            person(3,custom={domestic.OEHR:True}),person(4,1)]
    class Client:
        def __init__(self):self.calls=[]
        def post(self,path,body):
            if path==beisen.HISTORY:
                return {'data':[{**people[0]['recordInfoList'][0],'startDate':'2026-08-01','stopDate':'9999-12-31'}]}
            assert path==domestic.MONTHLY
            self.calls.append(deepcopy(body))
            return {'total':4,'scrollId':'cursor','data':people if len(self.calls)==1 else []}
    client=Client();fetched=[]
    def details(numbers,**options):fetched.append((numbers,options));return employment_snapshot()
    monkeypatch.setattr(beisen,'fetch',details)
    result=domestic.fetch(202608,client)
    assert [r['工号'] for r in result['roster']]==['zt1']
    assert result['roster'][0]['人员状态']=='已离职'
    assert fetched[0][0]==['zt1'] and fetched[0][1]['newest_first'] is True
    assert 8 in client.calls[0]['empStatus']
    assert client.calls[0]['extQueries'][0]['values']==['2026-08-01','2026-09-01']
    people[0]['recordInfoList'][0]['entryDate']='2026-07-01'
    with pytest.raises(ValueError,match='月份'):domestic.fetch(202608,Client())


def test_monthly_roster_uses_effective_service_at_period_end_and_fetches_carried_people(monkeypatch):
    from bonus_platform.engine import recruitment_domestic as domestic
    from bonus_platform.engine import recruitment_beisen as beisen
    common={'userID':1,'jobNumber':'zt1','entryDate':'2026-08-01','approvalStatus':4,'serviceType':0}
    histories=[{**common,'startDate':'2026-08-01','stopDate':'2026-08-31','employeeStatus':2,
                'translateProperties':{'OIdJobLevelText':'P1-3','OIdJobPositionText':'原岗位'}},
               {**common,'startDate':'2026-09-01','stopDate':'9999-12-31','employeeStatus':3,
                'translateProperties':{'OIdJobLevelText':'M9','OIdJobPositionText':'调动后岗位'}}]
    class Client:
        def post(self,path,body):
            if path==domestic.MONTHLY:
                return {'total':1,'scrollId':'cursor','data':[] if body['scrollId'] else [
                    {'employeeInfo':{'userID':1,'name':'甲'},'recordInfoList':[histories[-1]]}]}
            assert path==beisen.HISTORY
            return {'data':histories}
    fetched=[]
    def details(numbers,**options):fetched.append((numbers,options));return employment_snapshot()
    monkeypatch.setattr(beisen,'fetch',details)
    result=domestic.fetch(202608,Client(),job_numbers=['zt-old'],recipient_numbers=['zt-owner'])
    assert result['roster'][0]['职级']=='P1-3'
    assert result['roster'][0]['职位']=='原岗位'
    assert result['roster'][0]['人员状态']=='试用'
    assert fetched[0][0]==['zt-old','zt1']
    assert fetched[0][1]['recipient_numbers']==['zt-owner']
    assert len(fetched[0][1]['candidate_histories'])==2
    assert result['rosterAsOf']=='2026-08-31'


def test_targeted_refresh_does_not_disable_the_monthly_roster(tmp_path):
    store=DraftStore(tmp_path);first=store.save_beisen_snapshot(202607,0,snapshot())
    updated=store.save_beisen_snapshot(202607,first['revision'],employment_snapshot())
    assert updated['sources'][0]['monthlyRoster'] and updated['sources'][0]['active']
    assert [r['values']['工号'] for r in updated['rows']]==['zt1']


def test_monthly_offer_lookup_keeps_history_without_scanning_former_employments():
    from bonus_platform.engine import recruitment_beisen as beisen
    class Client:
        def __init__(self):self.calls=[]
        def post(self,path,body):
            assert path==beisen.OFFERS
            self.calls.append(deepcopy(body))
            return {'scrollId':'next','data':[] if body['scrollId'] else [
                {'objectId':'current','name':'甲','approvalStatus':'2','customProperties':{}}]}
    client=Client()
    histories=[{'userID':1,'jobNumber':'zt1','entryDate':'2026-08-01','lUOffer':'current','approvalStatus':4},
               {'userID':1,'jobNumber':'zt1','entryDate':'2010-01-01','lUOffer':'former','approvalStatus':4}]
    payload=beisen.fetch(['zt1'],client=client,candidate_histories=histories,newest_first=True,offer_month=202608)
    assert len(client.calls)==2
    assert client.calls[0]['startTime']>'2020-01-01'
    assert [o['objectId'] for o in payload['offers']]==['current']
    assert len(payload['candidateHistories'])==2
    from datetime import datetime
    assert datetime.fromisoformat(payload['queriedAt']).utcoffset() is not None
