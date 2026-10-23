from copy import deepcopy

from bonus_platform.engine.recruitment_awards import calculate_row
from test_recruitment_calculation_fixes import confirmed_state


def test_historical_owner_does_not_inherit_new_owner_qualification_issues():
    state,row=confirmed_state()
    state['month']=202609
    fact=deepcopy(state['confirmedInstallments'][0])
    row['values'].update({'招聘负责人工号':'zt-new','招聘负责人姓名':'新领取人',
                         '招聘负责人入职日期':'','招聘负责人人员状态':'','人员状态':''})
    result=calculate_row(state,row)['recruitment']
    historical=next(n for n in result['nodes'] if n.get('openingLocked'))
    assert not any(i.startswith('招聘负责人：') for i in historical['issues'])
    assert any(i.startswith('候选人：') for i in historical['issues'])
    for key in ('recipientId','recipientName','amount','currency','scheduledMonth','dueDate','dueMonth'):
        assert historical[key]==fact[key]
    assert historical['openingSource']=={'confirmedMonth':fact['confirmedMonth'],'parentRevision':fact['parentRevision']}
    assert any(r['type']=='recipient_changed' for r in result['recoveries'])
    current=next(n for n in result['nodes'] if not n.get('openingLocked'))
    assert any(i.startswith('招聘负责人：') for i in current['issues'])
    assert state['confirmedInstallments'][0]==fact


def test_same_owner_historical_qualification_issue_is_preserved():
    state,row=confirmed_state()
    row['values']['招聘负责人入职日期']=''
    row['values']['招聘负责人人员状态']=''
    result=calculate_row(state,row)['recruitment']
    historical=next(n for n in result['nodes'] if n.get('openingLocked'))
    assert historical['recipientId']=='zt-owner'
    assert any(i.startswith('招聘负责人：') for i in historical['issues'])


def test_overseas_prefix_does_not_make_the_same_recipient_a_different_person():
    state,row=confirmed_state()
    state['confirmedInstallments'][0]['recipientId']='zt25991'
    row['values'].update({'招聘负责人工号':'海外-zt25991','招聘负责人入职日期':'','招聘负责人人员状态':''})
    result=calculate_row(state,row)['recruitment']
    historical=next(n for n in result['nodes'] if n.get('openingLocked'))
    assert historical['recipientId']=='zt25991'
    assert any(i.startswith('招聘负责人：') for i in historical['issues'])


def test_current_month_fact_does_not_hide_current_owner_qualification_issue():
    state,row=confirmed_state()
    state['month']=202609
    state['confirmedInstallments'][0]['scheduledMonth']=202609
    row['values'].update({'招聘负责人工号':'zt-new','招聘负责人入职日期':'','招聘负责人人员状态':''})
    result=calculate_row(state,row)['recruitment']
    assert not any(n.get('openingLocked') for n in result['nodes'])
    current=next(n for n in result['nodes'] if n.get('scheduledMonth')==202609)
    assert any(i.startswith('招聘负责人：') for i in current['issues'])


def test_historical_owner_cleanup_preserves_opening_conflict_and_original_amount():
    state,row=confirmed_state()
    state['settlement']['baselineId']='ledger'
    row['history']=[{'ref':{'sourceId':'ledger'},'cells':[{'column':c,'value':v} for c,v in
        [(39,30),(40,202607),(22,'zt-owner'),(23,'招聘负责人'),(56,'欧元')]]}]
    row['values'].update({'招聘负责人工号':'zt-new','招聘负责人入职日期':'','招聘负责人人员状态':''})
    result=calculate_row(state,row)['recruitment']
    historical=next(n for n in result['nodes'] if n.get('openingLocked'))
    assert not any(i.startswith('招聘负责人：') for i in historical['issues'])
    assert (historical['recipientId'],historical['amount'],historical['scheduledMonth'])==('zt-owner',27.5,202607)
    assert any(r['type']=='opening_conflict' for r in result['recoveries'])
    assert any(r['type']=='recipient_changed' for r in result['recoveries'])
