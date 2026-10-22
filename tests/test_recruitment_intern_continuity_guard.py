from copy import deepcopy
from datetime import date

import pytest

from bonus_platform.engine.recruitment_awards import calculate_draft
from bonus_platform.engine.recruitment_beisen import parsed_snapshot
from bonus_platform.engine.recruitment_drafts import _empty, assemble
from bonus_platform.engine.recruitment_employment import status_from_timeline
from test_recruitment_awards import person


def continuous_intern_payload():
    common={'userID':101,'jobNumber':'zt101','lUOffer':'intern-offer',
            'approvalStatus':4,'serviceType':0,'lastWorkDate':None}
    formal={**common,'entryDate':'2026-07-01','employType':0,'regularizationDate':'2026-08-01'}
    return {'queriedAt':'2026-10-22T12:00:00','forms':[],'requirements':[],
            # Monthly Offer queries intentionally omit the earlier internship.
            'offers':[],'recipientHistories':[],
            'candidateHistories':[
                {**formal,'startDate':'2026-08-01','stopDate':'2026-08-01'},
                {**common,'entryDate':'2026-05-18','employType':2,'regularizationDate':None,
                 'startDate':'2026-05-18','stopDate':'2026-06-30'},
                {**formal,'startDate':'2026-08-01','stopDate':'9999-12-31'},
                {**formal,'regularizationDate':None,'startDate':'2026-07-01','stopDate':'2026-07-31'}]}


def assemble_opening(payload):
    values=person('2026-05-18',工号='zt101',标签分类='国内',工作地='中国大陆',二级组织='国内组织',
                  奖金地区类型='国内发展中国家',人员状态='试用',转正日期='',招聘启动日期='2026-05-13',
                  推荐人工号='',推荐人姓名='',周期剔除天数=0)['values']
    record={'role':'supplement','values':values,'rawValues':dict(values),'fieldColumns':{},
            'availableFields':list(values),'ref':{'sourceId':'opening','sheet':'期初','row':1}}
    state=_empty(202608)
    state['sources']=[{'id':'opening','name':'期初','recordCount':1,'active':True},
                      {'id':'api','name':'北森同步','recordCount':4,'kind':'beisen','active':True}]
    return calculate_draft(assemble(202608,[record]+parsed_snapshot(payload,'api')['records'],state))


def links(payload):
    return [r for r in parsed_snapshot(payload,'api')['records'] if r['role']=='employment_link']


def test_earlier_intern_offer_is_not_required_for_a_proven_continuity_bridge():
    payload=continuous_intern_payload();before=deepcopy(payload)
    parsed=parsed_snapshot(payload,'api')
    assert [r['values'] for r in parsed['records'] if r['role']=='employment_link']==[
        {'工号':'zt101','入职日期':'2026-05-18','人事入职日期':'2026-07-01'}]
    formal=[r['apiEvidence']['history'] for r in parsed['records'] if r['role']=='employment_history'
            and r['apiEvidence']['history']['employType']==0]
    assert len(formal)==3
    assert all(h['recruitmentEntryDate']=='2026-05-18' and h['continuityEvidence'] for h in formal)
    assert payload==before


def test_continuous_intern_history_drives_regularization_and_final_august_award():
    row=assemble_opening(continuous_intern_payload())['rows'][0]
    assert row['values']['入职日期']=='2026-05-18'
    assert row['values']['候选人入职时间']=='2026-05-18'
    assert row['values']['人事入职日期']=='2026-07-01'
    assert row['rule']['version']=='legacy'
    assert row['values']['转正日期']=='2026-08-01'
    assert status_from_timeline(row,'',date(2026,8,31))==''
    result=row['calculation']['recruitment']
    final=next(n for n in result['nodes'] if n['label']=='转正')
    assert final['dueMonth']==202608
    assert final['status']=='本月到期'
    assert final['amount']==97.5
    assert result['currentAmount']==97.5
    assert not final['issues']


@pytest.mark.parametrize('changed,value',[
    ('stopDate','2026-06-28'),('lUOffer','different-offer'),('lastWorkDate','2026-06-30'),
    ('approvalStatus',1),('serviceType',1),('employType',1),('lUOffer',''),
    ('userID',102),('jobNumber','zt102')])
def test_unproven_internship_never_bridges(changed,value):
    payload=continuous_intern_payload()
    payload['candidateHistories'][1][changed]=value
    assert not links(payload)
    state=assemble_opening(payload)
    assert not state['rows'][0]['values'].get('转正日期')


@pytest.mark.parametrize('changed,value',[
    ('approvalStatus',1),('serviceType',1),('employType',1),('lUOffer','')])
def test_unapproved_or_non_main_formal_employment_never_bridges(changed,value):
    payload=continuous_intern_payload()
    for h in payload['candidateHistories']:
        if h['employType']==0:h[changed]=value
    assert not links(payload)


def test_overlapping_different_employment_prevents_intern_bridge():
    payload=continuous_intern_payload()
    payload['candidateHistories'].append({**payload['candidateHistories'][3],
                                          'lUOffer':'competing-offer','entryDate':'2026-06-25',
                                          'startDate':'2026-06-25','stopDate':'2026-07-15'})
    assert not links(payload)
    assert not assemble_opening(payload)['rows'][0]['values'].get('转正日期')


def test_formal_entry_date_without_a_segment_start_does_not_prove_adjacency():
    payload=continuous_intern_payload()
    payload['candidateHistories']=[h for h in payload['candidateHistories'] if h['startDate']!='2026-07-01']
    assert not links(payload)


def test_non_main_formal_segment_cannot_supply_a_continuity_regularization():
    payload=continuous_intern_payload()
    for h in payload['candidateHistories']:
        if h['startDate']=='2026-08-01':h['serviceType']=1
    parsed=parsed_snapshot(payload,'api')
    secondary=[r['apiEvidence']['history'] for r in parsed['records'] if r['role']=='employment_history'
               and r['apiEvidence']['history']['serviceType']==1]
    assert secondary and all(not h.get('continuityEvidence') for h in secondary)
    assert not assemble_opening(payload)['rows'][0]['values'].get('转正日期')


def test_returned_intern_offer_cannot_override_a_real_exit():
    payload=continuous_intern_payload()
    payload['candidateHistories'][1]['lastWorkDate']='2026-06-30'
    payload['offers']=[{'objectId':'intern-offer','name':'Synthetic','entryDate':'2026-05-18',
                        'approvalStatus':2,'employmentForm':'intern','customProperties':{}}]
    payload['forms']=[{'fields':{'OId':'intern','Name':'实习生日薪'}}]
    assert not links(payload)
