from copy import deepcopy
import time

import pytest

from bonus_platform.engine import recruitment_beisen as beisen, recruitment_overseas as overseas, recruitment_prepare as jobs
from bonus_platform.engine.recruitment_attention import project
from bonus_platform.engine.recruitment_drafts import DraftStore
from bonus_platform.engine.recruitment_employment import enrich
from test_recruitment_awards import person
from test_recruitment_overseas import snapshot


def fact(entry, last='', **changes):
    return {'provider':'oehr','empNo':'zt1','employeeInfoId':'person-one','entryDate':entry,
            'startDate':entry,'endDate':'9999-12-31','lastWorkDay':last,'employmentType':'0',
            'employmentStatus':'1' if last else '0','employeeStatus':'8' if last else '3',
            'queriedAt':'2026-10-26T12:00:00','source':{'sourceId':'api','sheet':'海外任职记录','row':2},**changes}


def rehire_row():
    row=person('2026-08-03',工号='zt1',招聘渠道='二次入职')
    row.update(edits=[],sources=[],provenance={},conflicts=[])
    return row


def test_overseas_rehire_uses_the_nearest_ended_primary_employment():
    row=rehire_row()
    row['employmentCandidates']=[{'hireDate':'2024-07-01'}]
    enrich(row,{'zt1':[fact('2026-08-03','2026-09-25'),fact('2024-03-26','2024-06-09'),
                       fact('2024-07-01','2026-07-17'),fact('2024-07-01','2026-08-01',employmentType='1')]},[])
    assert row['values']['上次离职日期']=='2026-07-17'
    assert row['values']['最后工作日']=='2026-09-25'
    assert row['values']['任职说明'].startswith('二次入职')
    assert row['provenance']['上次离职日期'][0]['sourceId']=='api'


@pytest.mark.parametrize('change',['different-person','missing-current','missing-identity','no-termination','conflicting-exits','current-exit-only','nearer-other-person'])
def test_unproven_history_never_supplies_a_previous_exit(change):
    row=rehire_row();current=fact('2026-08-03','2026-09-25');previous=fact('2024-07-01','2026-07-17')
    records=[current,previous]
    if change=='different-person':previous['employeeInfoId']='someone-else'
    elif change=='missing-current':records=[previous]
    elif change=='missing-identity':current['employeeInfoId']=''
    elif change=='no-termination':previous['employeeStatus']='3'
    elif change=='conflicting-exits':records.append(fact('2024-07-01','2026-07-18'))
    elif change=='current-exit-only':records=[current]
    elif change=='nearer-other-person':records.append(fact('2025-01-01','2026-07-18',employeeInfoId='someone-else'))
    enrich(row,{'zt1':records},[])
    assert not row['values'].get('上次离职日期')


def test_reviewed_previous_exit_is_preserved_and_competing_source_value_is_explicit():
    row=rehire_row();row['values']['上次离职日期']='2026-07-15';row['edits']=[{'field':'上次离职日期'}]
    records=[fact('2026-08-03'),fact('2024-07-01','2026-07-17')]
    enrich(row,{'zt1':records},[])
    assert row['values']['上次离职日期']=='2026-07-15'
    assert not row['conflicts']
    row['edits']=[]
    enrich(row,{'zt1':records},[])
    assert row['values']['上次离职日期']=='2026-07-15'
    assert any(c['field']=='上次离职日期' for c in row['conflicts'])


def test_prepare_queries_historical_overseas_rehires_and_resolves_their_previous_exit(tmp_path,monkeypatch):
    month=202609;store=DraftStore(tmp_path);payload=snapshot(month)
    payload['offers'][0].update(招聘渠道='二次入职',其他渠道='')
    payload['roster'].append({'scope':'lookup','data':{'工号':'zt2','姓名':'招聘人','入职日期':'2020-01-01',
                            '人员来源':'EHR入职','人员状态':'正式'}})
    before=store.save_overseas_snapshot(month,0,payload);rid=before['rows'][0]['id']
    before=store.change(month,before['revision'],{'edits':[{'rowId':rid,'field':'入职日期','value':'2026-08-03','reason':'核对历史任职'}]})
    edits=deepcopy(before['edits']);calls=[]
    def fetch(period,job_numbers,**kwargs):
        calls.append((period,job_numbers))
        return {'version':1,'month':period,'queriedAt':'2026-10-26T12:00:00+08:00','employmentOnly':True,
                'requestedJobNumbers':job_numbers,'requestedOfferCodes':[],'missingOfferCodes':[],
                'roster':[{'scope':'lookup','data':{'工号':'zt1','入职日期':'2026-08-03','人员来源':'OEHR入职',
                           '人员状态':'正式','是否虚拟员工':'否'}}],'offers':[],
                'employmentHistory':[{'empNo':'zt1','records':[fact('2026-08-03'),fact('2024-07-01','2026-07-17')]}]}
    monkeypatch.setattr(overseas,'fetch_employment',fetch)
    monkeypatch.setattr(beisen,'fetch',lambda *a,**k:pytest.fail('Overseas rehire repair must not query domestic candidates'))
    jobs.start(store,month,before['revision'])
    for _ in range(500):
        result=jobs.read(store,month)
        if result['status'] not in {'running','cancelling'}:break
        time.sleep(.01)
    assert result['status']=='complete',result
    assert calls==[(month,['zt1'])]
    after=store.read(month)
    assert len(after['rows'])==1 and after['edits']==edits
    assert after['rows'][0]['values']['上次离职日期']=='2026-07-17'
    assert not any(t['kind'] in {'rehire','employment'} for t in project(after)['current'])
