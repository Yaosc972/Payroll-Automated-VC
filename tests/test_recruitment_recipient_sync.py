from copy import deepcopy
from datetime import datetime
import time

import pytest

from bonus_platform.engine import recruitment_beisen as beisen, recruitment_overseas as overseas, recruitment_prepare as jobs
from bonus_platform.engine.recruitment_drafts import DraftStore
from test_recruitment_overseas import snapshot
from test_recruitment_flow import history
from test_recruitment_awards import person
from bonus_platform.engine.recruitment_employment import status_from_timeline


MONTH = 202609


@pytest.mark.parametrize('last_work_day',['','2026-09-20'])
def test_secondary_assignment_does_not_hide_primary_employment(last_work_day):
    row=person(招聘负责人入职日期='2026-07-01')
    primary={**history(),'lastWorkDate':last_work_day,'queriedAt':'2026-10-26T12:00:00'}
    secondary={**history(),'serviceType':1,'queriedAt':'2026-10-26T12:00:00'}
    row['employmentTimelines']={'招聘负责人':[primary,secondary]}
    expected='适用日期已不在职' if last_work_day else ''
    assert status_from_timeline(row,'招聘负责人',datetime(2026,9,30))==expected
    row['employmentTimelines']['招聘负责人']=[secondary]
    assert status_from_timeline(row,'招聘负责人',datetime(2026,9,30)) is None


def employment_snapshot(last_work_day=''):
    return {'version':1,'month':MONTH,'queriedAt':'2026-10-26T12:00:00+08:00','employmentOnly':True,
            'requestedJobNumbers':['zt2'],'requestedOfferCodes':[],'missingOfferCodes':[],
            'roster':[{'scope':'lookup','data':{'工号':'zt2','姓名':'招聘人','入职日期':'2020-01-01',
                      '人员来源':'OEHR入职','是否虚拟员工':'否','人员状态':'离职' if last_work_day else '正式',
                      '离职日期':last_work_day}}],'offers':[],
            'employmentHistory':[{'empNo':'zt2','records':[{'empNo':'zt2','entryDate':'2020-01-01',
                'startDate':'2020-01-01','endDate':'9999-12-31','employmentType':'0','employmentStatus':'0',
                'employeeStatus':'8' if last_work_day else '3','lastWorkDay':last_work_day}]}]}


def initial(store):
    payload=snapshot(MONTH);payload['offers'][0].update(招聘渠道='招聘网站',其他渠道='')
    return store.save_overseas_snapshot(MONTH,0,payload)


@pytest.mark.parametrize('last_work_day',['','2026-09-20'])
def test_targeted_recipient_facts_update_eligibility_and_preserve_existing_work(tmp_path,last_work_day):
    store=DraftStore(tmp_path);before=initial(store);rid=before['rows'][0]['id']
    before=store.change(MONTH,before['revision'],{'edits':[{'rowId':rid,'field':'人工备注','value':'已核对分工','reason':'业务核对'}]})
    protected=deepcopy(before['rows'][0]['values']);edits=deepcopy(before['edits'])
    original=store._folder(MONTH)/'sources'/before['sources'][0]['storedName'];raw=original.read_bytes()
    after=store.save_overseas_snapshot(MONTH,before['revision'],employment_snapshot(last_work_day))
    assert len(after['rows'])==1
    assert after['edits']==edits and original.read_bytes()==raw
    assert all(after['rows'][0]['values'][k]==v for k,v in protected.items())
    assert after['sources'][-1]['employmentOnly'] is True
    assert not after['sources'][-1]['comparisonOnly']
    node=next(n for n in after['rows'][0]['calculation']['recruitment']['nodes'] if n['dueMonth']==MONTH)
    assert not any('招聘负责人：' in issue for issue in node['issues'])
    assert bool(node.get('eligibilityReasons'))==bool(last_work_day)


def test_recipient_snapshot_cannot_smuggle_new_candidates_or_offers():
    payload=employment_snapshot();payload['roster'][0]['scope']='month'
    with pytest.raises(ValueError):overseas.validate_snapshot(payload,MONTH)
    payload=employment_snapshot();payload['offers']=snapshot(MONTH)['offers']
    payload['requestedOfferCodes']=['OF1']
    with pytest.raises(ValueError):overseas.validate_snapshot(payload,MONTH)


def test_recipient_capture_must_match_the_requested_people():
    from types import SimpleNamespace
    client=SimpleNamespace(fetch=lambda *args,**kwargs:employment_snapshot())
    with pytest.raises(ValueError,match='本次领取人'):
        overseas.fetch_employment(MONTH,['zt3'],client=client)


@pytest.mark.parametrize('known_foreign',[False,True])
def test_prepare_automatically_falls_back_to_overseas_without_reloading_candidates(tmp_path,monkeypatch,known_foreign):
    store=DraftStore(tmp_path)
    if known_foreign:
        payload=snapshot(MONTH);payload['offers'][0].update(招聘渠道='招聘网站',其他渠道='')
        payload['roster'].append({'scope':'lookup','data':{'工号':'zt2','入职日期':'2020-01-01','人员来源':'OEHR入职'}})
        before=store.save_overseas_snapshot(MONTH,0,payload)
    else:before=initial(store)
    calls=[]
    def domestic(numbers,**kwargs):
        calls.append(('domestic',numbers))
        return beisen._with_coverage({'version':1,'employmentOnly':True,'queriedAt':'2026-10-26T11:00:00',
            'requestedJobNumbers':[],'requestedRecipientJobNumbers':numbers,'employeeMappings':[],
            'candidateHistories':[],'recipientHistories':[],'offers':[],'requirements':[],'forms':[]})
    def foreign(month,job_numbers,**kwargs):
        assert month==MONTH;calls.append(('overseas',job_numbers));return employment_snapshot()
    monkeypatch.setattr(beisen,'fetch_employment',domestic)
    monkeypatch.setattr(overseas,'fetch_employment',foreign,raising=False)
    monkeypatch.setattr(beisen,'fetch',lambda *a,**k:pytest.fail('Recipient repair must not reload candidate Offers'))
    jobs.start(store,MONTH,before['revision'])
    for _ in range(500):
        result=jobs.read(store,MONTH)
        if result['status'] not in {'running','cancelling'}:break
        time.sleep(.01)
    assert result['status']=='complete',result
    assert calls==([('domestic',['zt2'])] if not known_foreign else [])+[('overseas',['zt2'])]
    assert not result['coverageGaps']
    assert len(store.read(MONTH)['rows'])==1
