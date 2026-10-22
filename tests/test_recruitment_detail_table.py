from copy import deepcopy

from bonus_platform.engine.recruitment_detail_table import columns, cells
from test_recruitment_flow import state_with_rows


def test_offline_business_groups_and_pair_order():
    cols=columns();keys=[c['key'] for c in cols]
    assert len(keys)==len(set(keys))
    assert [c['label'] for c in cols[:8]]==['姓名','工号','身份证','入职日期','人员状态','工作地','最后工作日','职级']
    assert list(dict.fromkeys(c['group'] for c in cols))==['人员资料','招聘信息','招聘负责人入职奖金明细','协助人入职奖金明细','招聘人转正奖金','协助人转正奖金','币种','内推奖明细','备注','本月核算']
    assert keys.index('招聘负责人工号')<keys.index('recruiter')<keys.index('协助招聘人工号')<keys.index('assistant')
    for role in ('招聘负责人','协助招聘人'):
        for i in range(4):
            key=f'recruitment.{role}.{i}.amount'
            assert keys[keys.index(key)+1]==key.replace('.amount','.period')
    assert not set(keys)&{'职族','职类','职族分类','海外招聘需求编号','验证唯一'}


def test_mapping_uses_calculated_role_amounts_and_actual_schedule_not_comparison():
    row=state_with_rows()['rows'][0];before=deepcopy(row)
    a=row['calculation']['recruitment'];n=a['nodes'][0]
    n.update(amount=41.23,scheduledMonth=202610,amountBasis='按审批改期')
    row['history']=[{'cells':[{'column':39,'value':999999}], 'ref':{'sourceId':'comparison'}}]
    data,notes=cells(row)
    assert data['recruitment.招聘负责人.0.amount']==41.23
    assert data['recruitment.招聘负责人.0.period']=='202610'
    assert data['recruitment.招聘负责人.allocated']==a['recipientTotals'][0]['allocatedAmount']
    assert data['recruitment.difference']==a['cycle']['actualDays']-a['cycle']['standardDays']
    assert '按审批改期' in notes['recruitment.招聘负责人.0.amount']
    assert row['values']==before['values']


def test_unscheduled_nodes_do_not_fall_back_to_due_month_and_no_assistant_stays_blank():
    row=state_with_rows()['rows'][0];n=row['calculation']['recruitment']['nodes'][0]
    for status in ('按规则不发','暂缓安排','往期未安排'):
        n.update(scheduledMonth=None,status=status)
        data,_=cells(row)
        assert data['recruitment.招聘负责人.0.period']==status
        assert data['recruitment.招聘负责人.0.amount']==n['amount']
    assert data['recruitment.协助招聘人.allocated']==''
    assert data['recruitment.协助招聘人.0.amount']==''


def test_unknown_zero_unused_and_mixed_currency_are_not_conflated():
    row=state_with_rows()['rows'][0];a=row['calculation']['recruitment']
    a.update(total=None,nodes=[],recipientTotals=[])
    data,_=cells(row)
    assert data['recruitment.招聘负责人.0.amount'] is None
    assert data['recruitment.招聘负责人.allocated'] is None
    a['total']=0
    data,_=cells(row)
    assert data['recruitment.招聘负责人.allocated']==0
    assert data['recruitment.招聘负责人.0.amount']==''
    row=state_with_rows()['rows'][0];a=row['calculation']['recruitment']
    n=deepcopy(a['nodes'][0]);n['currency']='美元';a['nodes'].append(n)
    data,_=cells(row)
    assert data['recruitment.招聘负责人.0.amount'] is None
