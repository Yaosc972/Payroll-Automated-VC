from copy import deepcopy
from test_recruitment_awards import person
from bonus_platform.engine.recruitment_awards import award
from bonus_platform.engine.recruitment_opening import apply_opening


def fixture(reprice=False):
    row=person('2026-04-27',标签分类='国内',工作地='中国大陆',奖金地区类型='国内发展中国家',职级='P2-2',ABC类别='C',招聘启动日期='2026-03-11',转正日期='2026-07-27',周期剔除天数=0)
    ref={'sourceId':'june','sheet':'opening','row':5}
    row['history']=[{'ref':ref,'cells':[{'column':c,'value':v} for c,v in {38:90,39:45,40:202605,52:45,53:'未转正'}.items()]}]
    state={'month':202607,'offlineReplay':{'opening':{row['id']:{'ref':ref,'reprice':reprice}},'schedules':{row['id']:{'ref':{'sourceId':'july','row':8},'periods':{'40':'202605','53':'202607'}}}}}
    result={k:award(row,k,202607) for k in ('recruitment','referral')}
    return state,row,result


def test_corrected_total_only_changes_unsettled_installment():
    state,row,result=fixture(True)
    original=deepcopy(row['history'])
    apply_opening(state,row,result)
    nodes=result['recruitment']['nodes']
    assert [(n['amount'],n['scheduledMonth']) for n in nodes]==[(45,202605),(255,202607)]
    assert result['recruitment']['currentAmount']==255
    assert row['history']==original
    assert all(n['paidAmount'] is None and not n['paymentReady'] for n in nodes)


def test_opening_schedule_is_distinct_from_due_date_and_amounts_are_held():
    state,row,result=fixture()
    row['values']['转正日期']='2026-06-27'
    apply_opening(state,row,result)
    node=result['recruitment']['nodes'][1]
    assert node['dueMonth']==202606 and node['scheduledMonth']==202607
    assert node['amount']==45
    assert node['scheduleSource']['sourceId']=='july'
    assert node['openingSource']['sourceId']=='june'


def test_unscheduled_opening_installment_does_not_enter_current_total():
    state,row,result=fixture()
    state['offlineReplay']['schedules'][row['id']]['periods']['53']='员工离职，不发放'
    apply_opening(state,row,result)
    assert result['recruitment']['nodes'][1]['scheduledMonth'] is None
    assert result['recruitment']['currentAmount']==0


def test_cancellation_is_recorded_in_departure_month_without_double_subtraction():
    state,row,result=fixture()
    row['values']['最后工作日']='2026-07-10'
    state['offlineReplay']['schedules'][row['id']]['periods']['53']='员工转正前离职，不发放'
    apply_opening(state,row,result)
    assert result['recruitment']['currentAmount']==0
    assert result['recruitment']['cancelledBalances'][0]['amount']==45
    row['values']['最后工作日']='2026-06-10'
    apply_opening(state,row,result)
    assert result['recruitment']['cancelledBalances'][0]['amount']==0


def test_explicit_exclusion_is_not_overridden_by_opening():
    state,row,result=fixture()
    row['values']['核算范围']='不纳入核算'
    result={k:award(row,k,202607) for k in ('recruitment','referral')}
    apply_opening(state,row,result)
    assert result['recruitment']['currentAmount']==0
    assert not result['recruitment']['nodes']


def test_comparison_only_source_cannot_become_calculation_or_opening(tmp_path):
    import pytest
    from bonus_platform.engine.recruitment_drafts import DraftStore
    from test_recruitment_drafts import book
    store=DraftStore(tmp_path)
    content=book(['姓名','工号','入职日期'],[['参考人员','zt1','2026-07-01']],title='附件一-招聘奖金核算明细')
    state=store.ingest(202607,[('reference.xlsx',content)],0,comparison_only=True)
    assert not state['rows']
    with pytest.raises(ValueError):store.change(202607,state['revision'],{'baseline':state['sources'][0]['id']})
