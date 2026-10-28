from copy import deepcopy

import pytest

from bonus_platform.engine.recruitment_awards import calculate_row
from bonus_platform.engine.recruitment_awards import calculate_draft
from bonus_platform.engine.recruitment_attention import project as attention_project
from bonus_platform.engine.recruitment_business_basis import historical_arrangements_complete
from bonus_platform.engine.recruitment_special import context as special_context
from test_recruitment_awards import person


def historical_recruitment():
    row=person('2025-11-06',招聘渠道='内推')
    row.update(original=deepcopy(row['values']),frozenRecruitmentFacts=True,edits=[])
    cells={38:39.6,39:49.5,40:202512,41:19.8,42:202602,43:0,45:0,46:0,48:0,50:0,
           22:row['values']['招聘负责人工号'],23:row['values']['招聘负责人姓名'],56:'欧元'}
    row['history']=[{'ref':{'sourceId':'opening','sheet':'历史台账','row':3},'isBaseline':True,
                     'cells':[{'column':k,'value':v} for k,v in cells.items()]}]
    state={'month':202609,'settlement':{'baselineId':'opening'},'sources':[],'operations':[]}
    return state,row


def test_all_past_installments_keep_their_recorded_amounts_despite_a_lower_nominal_standard():
    state,row=historical_recruitment();before=deepcopy(row)
    result=calculate_row(state,row)['recruitment']
    assert historical_arrangements_complete(row,'recruitment',state['month'])
    assert result['historyRetained'] and result['total']==69.3
    assert result['currentAmount']==0 and not result['recoveries']
    assert [(n['amount'],n['scheduledMonth']) for n in result['nodes']]==[(49.5,202512),(19.8,202602)]
    assert all(n['paymentStatus']=='未核实' and n['paidAmount'] is None for n in result['nodes'])
    assert row==before


@pytest.mark.parametrize('case',['missing-month','current-month','future-month','unfinished-total','cancelled-standard','negative-amount','changed-recipient'])
def test_incomplete_or_cancelled_history_still_needs_its_actual_evidence(case):
    state,row=historical_recruitment()
    def change(column,value):next(c for c in row['history'][0]['cells'] if c['column']==column)['value']=value
    if case=='missing-month':change(42,'-')
    elif case=='current-month':change(42,202609)
    elif case=='future-month':change(42,202610)
    elif case=='unfinished-total':change(38,100)
    elif case=='cancelled-standard':change(38,0)
    elif case=='negative-amount':change(39,-49.5)
    elif case=='changed-recipient':row['values']['招聘负责人工号']='another-person'
    assert not historical_arrangements_complete(row,'recruitment',state['month'])
    assert not calculate_row(state,row)['recruitment'].get('historyRetained')


def cancelled_history():
    state,row=historical_recruitment()
    row['values'].update(姓名='Perrie样例',入职日期='2026-02-01',候选人入职时间='2026-02-01',招聘渠道='人员调动',二级组织='美国',工作地='美国')
    row['original']=deepcopy(row['values'])
    row['original']['招聘渠道']='体系外转体系内'
    row['history'][0]['cells']=[{'column':c,'value':v,'label':'人工备注' if c==72 else ''} for c,v in
        [(38,0),(39,35.75),(40,202602),(45,0),(22,'zt-owner'),(23,'招聘负责人'),(56,'美元'),
         (72,'2月已发35.75美元招聘奖金，3月扣回')]]
    state.update(revision=1,rows=[row],todos=[],summary={},edits=[],baseline='opening',strictInputs=True,
                 sources=[{'id':'opening','name':'202608招聘奖金台账.xlsx','roles':['ledger']}])
    return state,row


def test_cancelled_opening_amount_is_history_without_a_new_monthly_deduction():
    state,row=cancelled_history();original=deepcopy(row['history'])
    calculate_draft(state)
    recovery=row['calculation']['recruitment']['recoveries'][0]
    assert recovery['historyOnly']
    assert not attention_project(state)['current']
    assert any(t['rowIds']==[row['id']] for t in attention_project(state)['history'])
    assert state['ruleValidation']['passed']
    assert row['calculation']['recruitment']['currentAmount']==0
    node=row['calculation']['recruitment']['nodes'][0]
    assert (node['amount'],node['scheduledMonth'],node['paymentStatus'],node['paidAmount'])==(35.75,202602,'未核实',None)
    record=special_context(state)['historyRecoveries'][0]
    assert record['originalNotes'][0]['text']=='2月已发35.75美元招聘奖金，3月扣回'
    assert record.get('resolution') is None and not record['relatedRecords']
    assert row['history']==original and not state.get('specialAdjustments')


@pytest.mark.parametrize('case',['no-adoption','inactive-source','not-frozen','positive-standard','blank-standard','current-arrangement','manual-change'])
def test_new_or_unsupported_cancellation_stays_actionable(case):
    state,row=cancelled_history()
    if case=='no-adoption':state['baseline']='';state['openingEmptyConfirmed']=True;row['history'][0]['isBaseline']=False
    elif case=='inactive-source':state['sources'][0]['active']=False
    elif case=='not-frozen':row['frozenRecruitmentFacts']=False
    elif case in {'positive-standard','blank-standard'}:
        next(c for c in row['history'][0]['cells'] if c['column']==38)['value']=35.75 if case=='positive-standard' else ''
    elif case=='current-arrangement':row['history'][0]['cells']+=[{'column':41,'value':10,'label':''},{'column':42,'value':202609,'label':'发放周期'}]
    elif case=='manual-change':
        edit={'rowId':row['id'],'field':'招聘渠道','active':True,'operationId':'changed'}
        row['edits']=[edit];state['edits']=[edit];state['operations']=[{'id':'changed','active':True,'month':202609}]
    calculate_draft(state)
    assert not row['calculation']['recruitment']['recoveries'][0].get('historyOnly')
    assert attention_project(state)['current']


def test_old_assistant_cancellation_stays_historical_when_the_owner_has_a_current_arrangement():
    state,row=cancelled_history()
    row['values'].update(招聘渠道='招聘网站',招聘启动日期='2026-01-01')
    row['original']=deepcopy(row['values'])
    row['history'][0]['cells']=[{'column':c,'value':v,'label':'发放周期' if c==40 else ''} for c,v in
        [(38,55),(39,27.5),(40,202609),(45,0),(46,6.6),(47,202605),
         (22,'zt-owner'),(23,'招聘负责人'),(24,'zt-assistant'),(25,'原协助招聘人'),(56,'美元')]]
    calculate_draft(state)
    view=attention_project(state)
    recovery=next(r for r in row['calculation']['recruitment']['recoveries'] if r['role']=='协助招聘人')
    assert recovery['historyOnly']
    assert not any(recovery['reason'] in t['title'] for t in view['current'])
    assert any(recovery['reason'] in t['title'] for t in view['history'])
