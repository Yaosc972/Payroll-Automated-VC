from copy import deepcopy
from datetime import date

import pytest

from bonus_platform.engine.recruitment_awards import award
from bonus_platform.engine.recruitment_employment import status_from_timeline
from test_recruitment_awards import person


def same_offer_row():
    row=person('2026-07-02',海外offer流程编号='same-offer',人员状态='试用')
    roster={'sourceId':'oehr-source','sheet':'OEHR花名册','row':597}
    row.update(edits=[],frozenRecruitmentFacts=True,sources=[roster],
               recruitmentContinuityBasis={'offerId':'same-offer','sources':[dict(roster)]},
               employmentContext={'recruitmentHireDate':'2026-07-02','hrHireDates':['2026-07-01']},
               employmentObservations=[{**roster,'value':'2026-07-01','role':'roster'}],
               employmentTimelines={'':[{
                   'provider':'oehr','empNo':'zt-check','entryDate':'2026-07-01',
                   'startDate':'2026-07-02','endDate':'9999-12-31',
                   'employmentType':'0','employmentStatus':'0','employeeStatus':'2',
                   'queriedAt':'2026-10-22T12:00:00','lastWorkDay':'',
                   'source':{'sourceId':'oehr-source','sheet':'海外任职记录','row':1805}}]})
    return row


def august_node(row,kind):
    return next(n for n in award(row,kind,202608)['nodes'] if n['dueMonth']==202608)


@pytest.mark.parametrize('kind',['recruitment','referral'])
def test_proven_same_offer_hr_date_qualifies_existing_recruitment_without_rewriting_it(kind):
    row=same_offer_row();before=deepcopy(row)
    node=august_node(row,kind)
    assert node['status']=='本月到期'
    assert node['dueDate']=='2026-08-01'
    assert node['amount']>0 and not node['issues']
    assert status_from_timeline(row,'',date(2026,8,31))==''
    assert row==before


@pytest.mark.parametrize('change',[
    'no_basis','different_offer','empty_offer','multiple_hr_hires','different_recruitment_hire',
    'different_month','missing_roster_source','wrong_roster_row','wrong_roster_date',
    'different_history_source','not_frozen','rehire'])
def test_unproven_or_stale_same_offer_basis_cannot_supply_candidate_eligibility(change):
    row=same_offer_row()
    if change=='no_basis':row.pop('recruitmentContinuityBasis')
    elif change=='different_offer':row['values']['海外offer流程编号']='other-offer'
    elif change=='empty_offer':row['values']['海外offer流程编号']=''
    elif change=='multiple_hr_hires':row['employmentContext']['hrHireDates'].append('2026-07-03')
    elif change=='different_recruitment_hire':row['employmentContext']['recruitmentHireDate']='2026-07-03'
    elif change=='different_month':row['employmentContext']['hrHireDates']=['2026-06-30']
    elif change=='missing_roster_source':row['sources']=[]
    elif change=='wrong_roster_row':row['recruitmentContinuityBasis']['sources'][0]['row']=598
    elif change=='wrong_roster_date':row['employmentObservations'][0]['value']='2026-07-03'
    elif change=='different_history_source':row['employmentTimelines'][''][0]['source']['sourceId']='other-source'
    elif change=='not_frozen':row['frozenRecruitmentFacts']=False
    elif change=='rehire':row['values']['是否二次入职']='是'
    assert status_from_timeline(row,'',date(2026,8,31))=='缺少本次任职的日期记录'
    if change=='rehire':return
    node=august_node(row,'recruitment')
    assert node['status']=='待核对'
    assert any('缺少本次任职的日期记录' in issue for issue in node['issues'])


def test_candidate_same_offer_basis_never_bridges_a_recipient_employment():
    row=same_offer_row()
    row['values']['推荐人入职日期']='2026-07-02'
    row['recipientSourceRegions']={'推荐人':'海外'}
    row['employmentTimelines']['推荐人']=deepcopy(row['employmentTimelines'][''])
    assert status_from_timeline(row,'推荐人',date(2026,8,31))=='缺少本次任职的日期记录'
    assert august_node(row,'referral')['status']=='待核对'


def test_reviewed_candidate_date_keeps_manual_priority_over_the_continuity_basis():
    row=same_offer_row()
    row['values']['入职日期']=row['values']['候选人入职时间']='2026-07-05'
    row['edits']=[{'field':'入职日期','value':'2026-07-05','active':True}]
    assert status_from_timeline(row,'',date(2026,8,31)) is None
    node=august_node(row,'recruitment')
    assert node['dueDate']=='2026-08-04'
    assert node['status']=='本月到期'
