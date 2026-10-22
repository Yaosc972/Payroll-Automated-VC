"""Pending approvals are evidence, not decisions the payroll operator must repeat."""
from copy import deepcopy

import pytest

from bonus_platform.engine.recruitment_attention import project
from bonus_platform.engine.recruitment_monthly import project as monthly_project
from bonus_platform.engine.recruitment_actions import task_fields
from bonus_platform.engine.recruitment_work_items import detail, project as work_items
from bonus_platform.engine.recruitment_drafts import DraftStore
from test_recruitment_attention import state_for, fact_task
from test_recruitment_awards import person
from test_recruitment_drafts import book


def pending_state(last='2026-07-31'):
    row=person(招聘渠道='内推')
    row.update(provenance={'人员状态':[
        {'sourceId':'opening','role':'ledger','value':'试用'},
        {'sourceId':'roster','role':'roster','value':'正式'}]},
        sources=[],edits=[],offerMatched=True,
        pendingResignations=[{'lastDay':last,'status':'审批中',
                             'source':{'sourceId':'exit','sheet':'离职','row':2}}])
    state=state_for([row],[{**fact_task(row,'resignation_review','离职资料最终状态待核'),'sourceIds':['exit']}])
    state['sources']=[{'id':'exit','name':'海外离职流程.xlsx','active':True},
                      {'id':'roster','name':'海外花名册.xlsx','active':True}]
    return state


def test_month_end_pending_exit_does_not_block_unchanged_current_awards():
    state=pending_state();before=deepcopy(state)
    attention=project(state);monthly=monthly_project(state,attention)
    assert not any(t['kind']=='resignation_review' for t in attention['current'])
    assert not monthly['actionCount']
    assert any('离职' in n['title'] and '7月31日' in n['detail'] for n in monthly['automaticResults'])
    assert all(not n['review'] for n in monthly['nodes'] if n['scope']=='current')
    assert state==before  # Do not approve the exit, fill a date or change money.
    assert any(t['kind']=='resignation_review' for t in state['todos'])
    assert any(t['kind']=='resignation_review' for t in attention['history'])  # Later awards still need the outcome.


def test_earlier_pending_exit_still_blocks_affected_current_awards():
    state=pending_state('2026-07-30');before=deepcopy(state)
    attention=project(state);monthly=monthly_project(state,attention)
    task=next(t for t in attention['current'] if t['kind']=='resignation_review')
    assert task['rowAwardKinds']['employee-span']==['recruitment','referral']
    assert monthly['actionCount']==1
    assert all(n['review'] for n in monthly['nodes'] if n['scope']=='current')
    assert not any('离职' in n['title'] for n in monthly['automaticResults'])
    assert state==before


def test_unavailable_or_conflicting_evidence_is_not_silently_dismissed():
    for observations in ([],[{'lastDay':'','status':'审批中','source':{'sourceId':'exit'}}],
                         pending_state()['rows'][0]['pendingResignations']+[
                             {'lastDay':'2026-07-30','status':'审批中','source':{'sourceId':'exit'}}]):
        state=pending_state();state['rows'][0]['pendingResignations']=observations
        assert any(t['kind']=='resignation_review' for t in project(state)['current'])


@pytest.mark.parametrize('last,blocks',[('2026-07-31',False),('2026-07-30',True)])
def test_exit_comparison_reuses_settlement_rules(last,blocks):
    from bonus_platform.engine.recruitment_awards import calculate_draft
    state=pending_state(last);state['settlement']={'baselineId':'opening'}
    calculate_draft(state);before=deepcopy(state)
    assert any(t['kind']=='resignation_review' for t in project(state)['current']) is blocks
    assert state==before


def test_earlier_exit_is_not_masked_by_existing_active_employment_timeline():
    state=pending_state('2026-07-30')
    state['rows'][0]['employmentTimelines']={'':[{'userID':'one','entryDate':'2026-07-01',
        'startDate':'2026-07-01','stopDate':'9999-12-31','queriedAt':'2026-08-10',
        'serviceType':'0','approvalStatus':'4'}]}
    assert any(t['kind']=='resignation_review' for t in project(state)['current'])


def test_exit_form_requests_only_final_date_and_displays_existing_sources():
    state=pending_state('2026-07-30');row=state['rows'][0]
    assert task_fields(row,{'kind':'resignation_review'},202607)==['最后工作日']
    item=next(i for i in work_items(state,project(state)) if i['key']=='resignation_review')
    data=detail(state,item)
    assert [f['field'] for f in data['currentFields']]==['最后工作日']
    review=data['people'][0]['resignationReview']
    assert review['currentStatus']=='正式'
    assert review['statusSources'][0]['sourceId']=='roster'
    assert review['records'][0]['lastDay']=='2026-07-30'
    assert not data['currentFields'][0]['options']  # Unapproved date is not an adopted fact.


@pytest.mark.parametrize('status,expected',[('审批中',True),('已撤回',False),('已通过',False)])
def test_assembly_retains_only_applicable_pending_exit_evidence(tmp_path,status,expected):
    state=DraftStore(tmp_path).ingest(202607,[
        ('历史.xlsx',book(['姓名','工号','入职日期'],[['甲','zt1','2026-06-01']],title='附件一-招聘奖金核算明细')),
        ('离职.xlsx',book(['工号','入职日期','最后工作日','离职类型','审批状态'],
                      [['zt1','2026-06-01','2026-07-31','主动离职',status],
                       ['zt1','2025-06-01','2026-07-15','主动离职','审批中']]))],0)
    records=state['rows'][0].get('pendingResignations',[])
    assert bool(records) is expected
    if expected:
        assert len(records)==1 and records[0]['lastDay']=='2026-07-31'
        assert records[0]['source']['row']==2
        assert not state['rows'][0]['values'].get('最后工作日')


def test_final_result_supersedes_same_pending_date_without_manual_confirmation(tmp_path):
    store=DraftStore(tmp_path)
    headers=['工号','入职日期','最后工作日','离职类型','审批状态']
    state=store.ingest(202607,[
        ('历史.xlsx',book(['姓名','工号','入职日期'],[['甲','zt1','2026-06-01']],title='附件一-招聘奖金核算明细')),
        ('离职审批中.xlsx',book(headers,[['zt1','2026-06-01','2026-07-30','主动离职','审批中']]))],0)
    state=store.ingest(202607,[('离职已完成.xlsx',book(headers,
        [['zt1','2026-06-01','2026-07-30','主动离职','已通过']]))],state['revision'])
    assert state['rows'][0]['values']['最后工作日']=='2026-07-30'
    assert not state['rows'][0]['pendingResignations']
    assert not any(t['kind']=='resignation_review' for t in state['todos'])
