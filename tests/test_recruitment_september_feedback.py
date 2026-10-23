from copy import deepcopy

import pytest

from bonus_platform.engine.recruitment_awards import award, calculate_row
from bonus_platform.engine.recruitment_attention import needed
from test_recruitment_awards import person
from test_recruitment_dated_referrer_facts import qualification_row, history


def test_referrer_current_promotion_does_not_overwrite_hire_date_qualification():
    row=qualification_row([
        history(stopDate='2026-08-31'),
        history(startDate='2026-09-01',translateProperties={'OIdJobLevelText':'M4-1','OIdJobPositionText':'HRBP'}),
    ])
    row['values'].update(推荐人职级='M4-1',推荐人职位='HRBP',推荐人入职日期='',推荐人转正日期='')
    before=deepcopy(row)
    result=award(row,'referral',202610)
    assert result['total']==400
    assert result['referrerQualificationBasis'][0]['at']=='2026-08-01'
    assert row==before
    row['edits']=[{'field':'推荐人职级','value':'M4-1'}]
    assert award(row,'referral',202610)['total']==0


def test_current_roster_without_hire_date_evidence_stays_pending():
    row=person(推荐人职级='P2-1',推荐人职位='产品运营')
    row['provenance']={f:[{'role':'roster','sourceId':'current','value':row['values'][f]}]
                       for f in ('推荐人职级','推荐人职位')}
    assert '推荐人岗位与职级待核' in award(row,'referral',202607)['issues']


def test_other_channel_does_not_create_a_referral_award_from_notes_or_recipient():
    row=person(招聘渠道='其他',招聘渠道备注='内推 zt-ref',其他渠道='招聘网站')
    assert award(row,'recruitment',202607)['total']==0
    assert award(row,'referral',202607)['total']==0


def closed_history():
    row=person(hire='2025-01-01')
    row.update(original=deepcopy(row['values']),frozenRecruitmentFacts=True,edits=[])
    # Old business ledger used a different total; all its installments were arranged.
    cells={61:2000,62:0,64:0,66:2000,67:202507,68:0,58:'推荐人',59:'zt-ref',56:'欧元'}
    row['history']=[{'ref':{'sourceId':'opening','sheet':'明细','row':3},'isBaseline':True,
                     'cells':[{'column':k,'value':v} for k,v in cells.items()]}]
    state={'month':202609,'settlement':{'baselineId':'opening'},'sources':[], 'operations':[]}
    return state,row


def test_fully_arranged_opening_preserves_old_total_without_new_recovery():
    state,row=closed_history()
    row['values'].update(推荐人转正日期='',推荐人入职日期='',推荐人人员状态='')
    before=deepcopy(row)
    result=calculate_row(state,row)['referral']
    assert result['total']==2000 and result['currentAmount']==0
    assert result['historyRetained'] and not result['issues'] and not result['recoveries']
    assert result['nodes'][0]['amount']==2000 and result['nodes'][0]['scheduledMonth']==202507
    assert result['nodes'][0]['paymentStatus']=='未核实'
    assert row==before


@pytest.mark.parametrize('case',['unpaid','current','changed-recipient','new-decision','unbalanced'])
def test_open_or_changed_history_still_requires_reconciliation(case):
    state,row=closed_history()
    if case in {'unpaid','current'}:
        next(c for c in row['history'][0]['cells'] if c['column']==67)['value']='待发' if case=='unpaid' else 202609
    elif case=='changed-recipient':row['values']['推荐人工号']='new-person'
    elif case=='new-decision':row['awardDecisions']=[{'kind':'referral','action':'exclude','basisType':'approval'}]
    elif case=='unbalanced':next(c for c in row['history'][0]['cells'] if c['column']==61)['value']=2100
    assert not calculate_row(state,row)['referral'].get('historyRetained')


def test_known_status_needs_no_recipient_entry_or_probation_but_departure_still_blocks():
    row=person(推荐人入职日期='',推荐人转正日期='',推荐人人员状态='试用')
    result=award(row,'referral',202607)
    assert result['nodes'][0]['issues']==[] and result['nodes'][0]['status']=='本月到期'
    row['values']['推荐人最后工作日']='2026-07-20'
    result=award(row,'referral',202607)
    assert result['nodes'][0]['status']=='按规则不发'
    assert result['nodes'][0]['amount']>0 and result['currentAmount']==0
    assert needed(row,'推荐人转正日期',202607)==[]
