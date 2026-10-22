from copy import deepcopy

import pytest

from bonus_platform.engine.recruitment_business_basis import select_unique_opening
from bonus_platform.engine.recruitment_awards import award
from test_recruitment_awards import person


def state():
    return {'month':202607,'strictInputs':True,'sources':[
        {'id':'june','name':'全球招聘奖金核算明细表202606.xlsx','roles':['ledger']},
        {'id':'july','name':'全球招聘奖金核算明细表202607.xlsx','roles':['ledger'],'comparisonOnly':True}]}


def history(row, cells, adopted=True):
    row['history']=[{'ref':{'sourceId':'june','row':3,'sheet':'核算表'},'isBaseline':adopted,
                     'cells':[{'column':column,'value':value,'label':''} for column,value in cells.items()]}]
    return row


def test_unique_previous_month_is_carried_without_using_current_results():
    s=state();select_unique_opening(s)
    assert s['baseline']==s['settlement']['baselineId']=='june'
    assert s['openingSelection']['mode']=='uniquePreviousMonth'
    assert s['sources'][1]['comparisonOnly']


@pytest.mark.parametrize('override',[{'baseline':'chosen'}, {'parentMonth':202606}, {'openingEmptyConfirmed':True}])
def test_existing_opening_choice_is_preserved(override):
    s={**state(),**override};before=deepcopy(s);select_unique_opening(s)
    assert s==before


@pytest.mark.parametrize('variant',['multiple','undated','comparison','future','inactive'])
def test_ambiguous_or_ineligible_source_never_auto_adopted(variant):
    s=state()
    if variant=='multiple':s['sources'].append({**s['sources'][0],'id':'other'})
    if variant=='undated':s['sources'][0]['name']='招聘奖金核算明细.xlsx'
    if variant=='comparison':s['sources'][0]['comparisonOnly']=True
    if variant=='future':s['sources'][0]['name']='招聘奖金核算明细202608.xlsx'
    if variant=='inactive':s['sources'][0]['active']=False
    before=deepcopy(s);select_unique_opening(s)
    assert s==before


def test_zero_referral_from_adopted_previous_month_is_not_a_missing_referrer():
    row=history(person('2026-06-01',招聘渠道='内推',推荐人工号='',推荐人姓名=''),
                {58:'-',59:'-',61:0,62:0,64:0,66:0,68:0})
    result=award(row,'referral',202607)
    assert result['total']==0 and not result['issues']
    assert '上月核算表' in result['reasons'][0]
    row['history'][0]['isBaseline']=False
    assert '推荐人待补充' in award(row,'referral',202607)['issues']
    row['history'][0]['isBaseline']=True
    row['history'][0]['cells']=[c for c in row['history'][0]['cells'] if c['column']!=61]
    assert '推荐人待补充' in award(row,'referral',202607)['issues']


def test_new_referral_relationship_is_not_cancelled_by_previous_zero():
    row=history(person('2026-06-01'),{58:'-',59:'-',61:0,62:0,64:0,66:0,68:0})
    assert award(row,'referral',202607)['total']>0


def test_previous_exclusion_is_evidence_not_another_approval():
    row=history(person('2026-06-15',招聘启动日期='2026-02-24',周期剔除天数=47),{33:47})
    a=award(row,'recruitment',202607)
    assert '周期剔除依据待核' not in a['issues']
    assert a['cycle']['exclusionBasis']['sourceId']=='june'
    row['values']['周期剔除天数']=48
    assert '周期剔除依据待核' in award(row,'recruitment',202607)['issues']


def test_missing_catalog_entry_can_use_unchanged_prior_person_standard_not_global_guess():
    from bonus_platform.engine.recruitment_awards import lookup
    row=history(person('2026-06-22',ABC类别='A',职级='P2-2',招聘启动日期='2026-05-25'),
                {9:'P2-2',19:'海外',21:'A类',32:120,37:1250,38:1625,39:487.5,41:487.5,43:650})
    row['frozenRecruitmentFacts']=True
    row['original']=deepcopy(row['values'])
    result=award(row,'recruitment',202607)
    assert result['total']==1625 and not result['issues']
    assert result['standardBasis']['sourceId']=='june'
    assert lookup(person('2026-06-22',ABC类别='A',职级='P2-2'),'recruitment') is None
    row['values']['职级']='P2-3'
    assert 'standardBasis' not in award(row,'recruitment',202607)
    row['values']['职级']='P2-2';row['history'][0]['isBaseline']=False
    assert award(row,'recruitment',202607)['total'] is None


def test_external_referrer_uses_offline_relationship_not_missing_internal_hr_fields():
    row=person(推荐人工号='体系外-顾问',推荐人职级='',推荐人职位='',推荐人人员状态='',
               推荐人入职日期='',推荐人转正日期='',直线经理工号='')
    row['provenance']={'推荐人工号':[{'sourceId':'business-sheet','role':'supplement','value':'体系外-顾问'}]}
    result=award(row,'referral',202607)
    assert result['total']==400 and not result['issues']
    assert not result['nodes'][0]['issues']
    row['values']['推荐人职位']='HRBP'
    assert award(row,'referral',202607)['total']==0


def test_fully_arranged_historical_date_disagreement_is_not_a_july_task():
    from bonus_platform.engine.recruitment_attention import is_current
    from bonus_platform.engine.recruitment_awards import calculate_draft
    row=history(person('2025-11-01',候选人入职时间='2025-10-09'),
                {38:300,39:150,40:202511,52:150,53:202602,61:0,62:0,64:0,66:0,68:0})
    row['frozenRecruitmentFacts']=True;row['original']=deepcopy(row['values']);row['rule']['version']='unresolved'
    s={'month':202607,'revision':1,'rows':[row],'todos':[],'sources':[],'summary':{}}
    calculate_draft(s)
    assert not is_current(row,'recruitment',202607,set())
    assert is_current(row,'recruitment',202607,{row['id']})
    row['history'][0]['cells']=[c for c in row['history'][0]['cells'] if c['column']!=53]
    assert is_current(row,'recruitment',202607,set())
