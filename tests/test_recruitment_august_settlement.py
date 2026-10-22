from copy import deepcopy

import pytest

from bonus_platform.engine import recruitment_special as special
from bonus_platform.engine.recruitment_awards import calculate_row, calculate_draft
from bonus_platform.engine.recruitment_drafts import DraftConflict
from test_recruitment_calculation_fixes import confirmed_state
from test_recruitment_special import fixture


def history_fixture(tmp_path, monkeypatch):
    store, state, _ = fixture(tmp_path, monkeypatch)
    state['sources'][-1]['storedName']='approval.pdf'
    row = state['rows'][0]
    award = row['calculation']['recruitment']
    node = award['nodes'][0]
    state['confirmedInstallments'] = [{
        **{k:node[k] for k in ('id','role','label','recipientId','recipientName','currency')},
        'originKey':'original-arrangement', 'nodeId':node['id'], 'rowId':row['id'],
        'kind':'recruitment', 'amount':award['total']+50,
        'scheduledMonth':202606, 'confirmedMonth':202606, 'parentRevision':1,
        'openingSource':{'sourceId':state['sources'][0]['id']}}]
    calculate_draft(state)
    store._write(store._folder(state['month'])/'draft.json', state)
    return store, state


def recovery(state):
    return state['rows'][0]['calculation']['recruitment']['recoveries'][0]


def history_payload(state):
    r = recovery(state)
    return {'revision':state['revision'], 'type':'history', 'kind':'recruitment',
            'rowId':state['rows'][0]['id'], 'recoveryKey':r['key'],
            'fingerprint':r['fingerprint'], 'outcome':'retain'}


def save(store, state, payload):
    p = special.preview(store, state['month'], payload)
    return special.apply_preview(store, state['month'], state['revision'], p['id'])


def test_unknown_total_preserves_history_without_false_deduction():
    state,row=confirmed_state()
    row['values']['招聘渠道']='尚未核定的渠道'
    result=calculate_row(state,row)['recruitment']
    assert result['total'] is None and result['issues']
    assert result['recoveries']==[] and result['accountingIssues']==[]
    old=result['nodes'][0]
    assert (old['amount'],old['currency'],old['recipientId'],old['scheduledMonth'])==(27.5,'欧元','zt-owner',202607)
    assert old['paidAmount'] is None and old['paymentStatus']=='未核实'
    row['values']['招聘渠道']='猎头'
    known=calculate_row(state,row)['recruitment']
    assert known['total']==0 and len(known['recoveries'])==1
    assert known['recoveries'][0]['signedAmount']==-27.5


def test_retain_history_preview_apply_retry_undo_redo_and_stale(tmp_path,monkeypatch):
    store,state=history_fixture(tmp_path,monkeypatch)
    before=deepcopy(state['rows'][0]['calculation']['recruitment'])
    p=special.preview(store,state['month'],history_payload(state))
    assert not p['nodeImpact'] and not p['currentImpact']
    assert store.read(state['month'])==state
    saved=special.apply_preview(store,state['month'],state['revision'],p['id'])
    result=saved['rows'][0]['calculation']['recruitment']
    assert result['total']==before['total'] and result['nodes']==before['nodes']
    assert result['recoveries']==[] and result['accountingIssues']==[]
    assert special.apply_preview(store,state['month'],state['revision'],p['id'])==saved
    with pytest.raises(DraftConflict):special.preview(store,state['month'],history_payload(state))
    undone=store.history_action(state['month'],saved['revision'],'undo')
    assert recovery(undone)['amount']==50
    redone=store.history_action(state['month'],undone['revision'],'redo')
    assert redone['rows'][0]['calculation']['recruitment']['recoveries']==[]


def test_history_reopens_on_source_notes_or_relevant_facts_not_month(tmp_path,monkeypatch):
    store,state=history_fixture(tmp_path,monkeypatch)
    saved=save(store,state,history_payload(state))
    carried=store.carry_forward(202608,202607,0)
    assert carried['rows'][0]['calculation']['recruitment']['recoveries']==[]
    changed=deepcopy(saved);changed['rows'][0]['values']['人工备注']='备注已补'
    calculate_draft(changed)
    assert changed['rows'][0]['calculation']['recruitment']['recoveries']
    changed['sources'][0]['active']=False;calculate_draft(changed)
    assert recovery(changed)['amount']==50
    changed=deepcopy(saved);changed['rows'][0]['values']['招聘负责人工号']='different-payee'
    calculate_draft(changed)
    assert changed['rows'][0]['calculation']['recruitment']['recoveries']


def test_matching_signed_adjustment_closes_only_its_balance_and_survives_future(tmp_path,monkeypatch):
    store,state=history_fixture(tmp_path,monkeypatch);r=recovery(state)
    payload={'revision':state['revision'],'type':'adjustment','basisType':'manual',
        'rowId':state['rows'][0]['id'],'kind':'recruitment','role':r['role'],
        'currency':r['currency'],'recipientId':r['recipientId'],'recipientName':r['recipientName'],
        'amount':-20,'month':202608}
    saved=save(store,state,payload)
    assert recovery(saved)['amount']==30
    full=save(store,saved,{**payload,'revision':saved['revision'],'amount':-30})
    assert full['rows'][0]['calculation']['recruitment']['recoveries']==[]
    assert not any(n.get('adjustmentId') and n.get('scheduledMonth')==202607 for n in full['rows'][0]['calculation']['recruitment']['nodes'])
    carried=store.carry_forward(202608,202607,0)
    assert carried['rows'][0]['calculation']['recruitment']['recoveries']==[]
    assert sum(n['amount'] for n in carried['rows'][0]['calculation']['recruitment']['nodes'] if n.get('adjustmentId'))==-50
    with pytest.raises(ValueError):special.preview(store,202608,{**payload,'revision':carried['revision'],'month':202608,'amount':-50,'recoveryKey':r['key']})


@pytest.mark.parametrize('patch',[{'recipientId':'someone-else'},{'role':'协助招聘人'},{'amount':50}])
def test_unrelated_adjustment_does_not_close_history(tmp_path,monkeypatch,patch):
    store,state=history_fixture(tmp_path,monkeypatch);r=recovery(state)
    saved=save(store,state,{'revision':state['revision'],'type':'adjustment','basisType':'manual',
        'rowId':state['rows'][0]['id'],'kind':'recruitment','role':r['role'],'currency':r['currency'],
        'recipientId':r['recipientId'],'recipientName':r['recipientName'],'amount':-50,'month':202607,**patch})
    assert recovery(saved)['amount']==50


def test_confirmed_adjustment_carries_without_new_difference_or_payment_claim(tmp_path,monkeypatch):
    store,state=history_fixture(tmp_path,monkeypatch);r=recovery(state)
    saved=save(store,state,{'revision':state['revision'],'type':'adjustment','basisType':'manual',
        'rowId':state['rows'][0]['id'],'kind':'recruitment','role':r['role'],'currency':r['currency'],
        'recipientId':r['recipientId'],'recipientName':r['recipientName'],'amount':-50,'month':202607})
    store._write(store._folder(202607)/'accepted.json',{'state':saved})
    carried=store.carry_forward(202608,202607,0)
    result=carried['rows'][0]['calculation']['recruitment']
    assert result['recoveries']==[]
    assert len([n for n in result['nodes'] if n.get('adjustmentId')])==1
    assert all(n['paidAmount'] is None and n['paymentStatus']=='未核实' for n in result['nodes'])


def test_retain_revoke_and_changed_source_rechecked_without_stale_issue(tmp_path,monkeypatch):
    store,state=history_fixture(tmp_path,monkeypatch)
    saved=save(store,state,history_payload(state))
    record=special.context(saved)['records'][-1]
    revoked=save(store,saved,{'revision':saved['revision'],'type':'revoke','recordId':record['id']})
    assert recovery(revoked)['amount']==50
    retained=save(store,revoked,history_payload(revoked))
    assert not retained['rows'][0]['calculation']['recruitment']['recoveries']
    assert not retained['rows'][0]['calculation']['recruitment']['accountingIssues']


def test_history_apply_rechecks_facts_even_with_unchanged_revision(tmp_path,monkeypatch):
    store,state=history_fixture(tmp_path,monkeypatch)
    p=special.preview(store,state['month'],history_payload(state))
    state['confirmedInstallments'][0]['amount']+=10
    store._write(store._folder(state['month'])/'draft.json',state)
    with pytest.raises(ValueError,match='变化'):special.apply_preview(store,state['month'],state['revision'],p['id'])
    assert not store.read(state['month']).get('settlementReviews')


def test_approval_deduction_source_invalidation_and_retain_cannot_double_close(tmp_path,monkeypatch):
    store,state=history_fixture(tmp_path,monkeypatch);r=recovery(state)
    payload={'revision':state['revision'],'type':'adjustment','rowId':state['rows'][0]['id'],
        'kind':'recruitment','role':r['role'],'currency':r['currency'],'recipientId':r['recipientId'],
        'recipientName':r['recipientName'],'amount':-50,'month':202608,
        'lineRef':'历史差异更正1','evidence':{'sourceId':'approval'}}
    saved=save(store,state,payload)
    assert not saved['rows'][0]['calculation']['recruitment']['recoveries']
    with pytest.raises(ValueError):special.preview(store,202607,{**history_payload(state),'revision':saved['revision']})
    changed=deepcopy(saved);next(s for s in changed['sources'] if s['id']=='approval')['active']=False
    calculate_draft(changed)
    assert recovery(changed)['amount']==50
    assert next(n for n in changed['rows'][0]['calculation']['recruitment']['nodes'] if n.get('adjustmentId'))['scheduledMonth'] is None


def test_missing_historical_payee_is_preserved_and_only_retainable(tmp_path,monkeypatch):
    store,state=history_fixture(tmp_path,monkeypatch)
    state['confirmedInstallments'][0].update(recipientId='',recipientName='')
    calculate_draft(state);store._write(store._folder(202607)/'draft.json',state)
    r=recovery(state)
    assert r['recipientId']=='' and r['recipientName']==''
    with pytest.raises(ValueError,match='不匹配'):
        special.preview(store,202607,{'revision':state['revision'],'type':'adjustment','basisType':'manual',
            'rowId':state['rows'][0]['id'],'kind':'recruitment','role':r['role'],'currency':r['currency'],
            'recipientId':'zt-old','recipientName':'原负责人','amount':-50,'month':202607,'recoveryKey':r['key']})
    saved=save(store,state,history_payload(state))
    assert not saved['rows'][0]['calculation']['recruitment']['recoveries']
    assert next(n for n in saved['rows'][0]['calculation']['recruitment']['nodes'] if n.get('openingLocked'))['recipientId']==''


def test_conflicting_opening_sources_are_reviewable_without_inventing_deduction():
    state,row=confirmed_state()
    state['sources']=[{'id':'ledger','active':True}]
    state['settlement']['baselineId']='ledger'
    row['history']=[{'ref':{'sourceId':'ledger','sheet':'原表','row':3},'cells':[
        {'column':c,'value':v} for c,v in [(39,20),(40,202607),(22,'zt-owner'),(23,'招聘负责人'),(56,'欧元')]]}]
    current=calculate_row(state,row)['recruitment']
    r=current['recoveries'][0]
    assert r['type']=='opening_conflict' and r['signedAmount'] is None
    assert r['adjustmentAllowed'] is False
    assert sorted(f['amount'] for f in r['openingFacts'])==[20,27.5]
    state['operations']=[{'id':'review','active':True}]
    state['settlementReviews']=[{'id':'review','operationId':'review','month':202608,'rowId':row['id'],
        'kind':'recruitment','recoveryKey':r['key'],'fingerprint':r['fingerprint'],'outcome':'retain',
        'basisType':'history','sourceIds':['ledger']}]
    assert calculate_row(state,row)['recruitment']['recoveries']==[]
    state['operations'][0]['active']=False
    assert calculate_row(state,row)['recruitment']['recoveries']
    state['operations'][0]['active']=True
    state['month']=202609
    assert calculate_row(state,row)['recruitment']['recoveries']==[]
    row['history'][0]['cells'][0]['value']=40
    changed=calculate_row(state,row)['recruitment']['recoveries'][0]
    assert changed['key']==r['key'] and changed['fingerprint']!=r['fingerprint']
    assert sorted(f['amount'] for f in changed['openingFacts'])==[27.5,40]
    assert changed['signedAmount'] is None
    row['history'][0]['cells'][0]['value']=20
    state['sources'][0]['active']=False
    assert calculate_row(state,row)['recruitment']['recoveries']


def test_changed_entitlement_after_confirmed_deduction_cannot_deduct_gross_history_again(tmp_path,monkeypatch):
    store,state=history_fixture(tmp_path,monkeypatch);r=recovery(state)
    payload={'revision':state['revision'],'type':'adjustment','basisType':'manual',
        'rowId':state['rows'][0]['id'],'kind':'recruitment','role':r['role'],'currency':r['currency'],
        'recipientId':r['recipientId'],'recipientName':r['recipientName'],'amount':-50,'month':202607}
    saved=save(store,state,payload)
    store._write(store._folder(202607)/'accepted.json',{'state':saved})
    carried=store.carry_forward(202608,202607,0)
    changed=store.change(202608,carried['revision'],{'edits':[{'rowId':r['rowId'],'field':'招聘渠道','value':'猎头'}]})
    result=changed['rows'][0]['calculation']['recruitment'];new=recovery(changed)
    assert result['total']==0
    assert next(n for n in result['nodes'] if n.get('adjustmentId'))['amount']==-50
    assert new['adjustmentAllowed'] is True and new['signedAmount']==-60
    assert new['confirmedCorrections'][0]['amount']==-50
    assert any(r['confirmed'] and r['amount']==-50 for r in special.context(changed)['records'])
    for key in (new['key'],None):
        with pytest.raises(ValueError,match='已确认'):
            special.preview(store,202608,{**payload,'revision':changed['revision'],'month':202608,'amount':-110,'recoveryKey':key})
    corrected=save(store,changed,{**payload,'revision':changed['revision'],'month':202608,'amount':-60,'recoveryKey':new['key']})
    assert not corrected['rows'][0]['calculation']['recruitment']['recoveries']
    nodes=corrected['rows'][0]['calculation']['recruitment']['nodes']
    assert sorted(n['amount'] for n in nodes if n.get('adjustmentId'))==[-60,-50]
    assert all(n['paidAmount'] is None for n in nodes)
    undone=store.history_action(202608,corrected['revision'],'undo')
    assert recovery(undone)['signedAmount']==-60
    restored=store.history_action(202608,undone['revision'],'redo')
    store._write(store._folder(202608)/'accepted.json',{'state':restored})
    september=store.carry_forward(202609,202608,0)
    assert september['rows'][0]['calculation']['recruitment']['recoveries']==[]
    assert sum(n['amount'] for n in september['rows'][0]['calculation']['recruitment']['nodes'] if n.get('adjustmentId'))==-110


def test_opening_source_conflict_preview_apply_revoke_carry_and_source_edit(tmp_path,monkeypatch):
    import json
    store,state=history_fixture(tmp_path,monkeypatch)
    row=state['rows'][0];source=state['sources'][0];sid=source['id']
    path=store._folder(202607)/'parsed'/(sid+'.json');parsed=json.loads(path.read_text())
    record=next(r for r in parsed['records'] if r['values'].get('姓名')==row['values']['姓名'])
    record.update(role='ledger',historyCells=[{'column':c,'value':v,'label':str(c)} for c,v in [
        (39,20),(40,202606),(22,'zt-old'),(23,'原负责人'),(56,'人民币')]])
    store._write(path,parsed)
    state['settlement']={'baselineId':sid};state['baseline']=sid
    state=store._save(store._folder(202607),store._rebuild(store._folder(202607),state))
    def conflict(s):
        return next(r for r in s['rows'][0]['calculation']['recruitment'].get('recoveries',[]) if r['type']=='opening_conflict')
    r=conflict(state)
    payload={'revision':state['revision'],'type':'history','kind':'recruitment','rowId':row['id'],
             'recoveryKey':r['key'],'fingerprint':r['fingerprint'],'outcome':'retain'}
    p=special.preview(store,202607,payload)
    assert sid in p['record']['sourceIds']
    assert sorted(f['amount'] for f in p['record']['recovery']['openingFacts'])==[20,110]
    with pytest.raises(ValueError,match='两份来源'):
        special.preview(store,202607,{'revision':state['revision'],'type':'adjustment','basisType':'manual',
            'rowId':row['id'],'kind':'recruitment','role':r['role'],'currency':r['currency'],
            'recipientId':r['recipientId'],'recipientName':r['recipientName'],'amount':-20,'month':202607,'recoveryKey':r['key']})
    saved=special.apply_preview(store,202607,state['revision'],p['id'])
    assert all(r['type']!='opening_conflict' for r in special.context(saved)['recoveries'])
    revoked=save(store,saved,{'revision':saved['revision'],'type':'revoke','recordId':p['record']['id']})
    assert conflict(revoked)['key']==r['key']
    restored=store.history_action(202607,revoked['revision'],'undo')
    assert all(r['type']!='opening_conflict' for r in special.context(restored)['recoveries'])
    carried=store.carry_forward(202608,202607,0)
    assert all(r['type']!='opening_conflict' for r in special.context(carried)['recoveries'])
    new_path=store._folder(202608)/'parsed'/(sid+'.json');changed_parsed=json.loads(new_path.read_text())
    next(r for r in changed_parsed['records'] if r['role']=='ledger')['historyCells'][0]['value']=40
    store._write(new_path,changed_parsed)
    changed=store._save(store._folder(202608),store._rebuild(store._folder(202608),carried))
    new=conflict(changed)
    assert new['key']==r['key'] and new['fingerprint']!=r['fingerprint']
    assert new['signedAmount'] is None and sorted(f['amount'] for f in new['openingFacts'])==[40,110]


def test_increased_entitlement_reprices_future_balance_after_confirmed_deduction(tmp_path,monkeypatch):
    store,state=history_fixture(tmp_path,monkeypatch);r=recovery(state)
    saved=save(store,state,{'revision':state['revision'],'type':'adjustment','basisType':'manual',
        'rowId':r['rowId'],'kind':'recruitment','role':r['role'],'currency':r['currency'],
        'recipientId':r['recipientId'],'recipientName':r['recipientName'],'amount':-50,'month':202607})
    store._write(store._folder(202607)/'accepted.json',{'state':saved})
    carried=store.carry_forward(202608,202607,0)
    changed=store.change(202608,carried['revision'],{'edits':[{'rowId':r['rowId'],'field':'ABC类别','value':'A'}]})
    result=changed['rows'][0]['calculation']['recruitment']
    assert result['total']==2400
    assert next(n for n in result['nodes'] if n.get('openingLocked') and not n.get('adjustmentId'))['amount']==110
    assert next(n for n in result['nodes'] if n.get('adjustmentId'))['amount']==-50
    assert sum(n['amount'] for n in result['nodes'])==2400
    assert next(n for n in result['nodes'] if not n.get('openingLocked') and not n.get('adjustmentId'))['amount']==2340
    assert not result['recoveries'] and all(n['paidAmount'] is None for n in result['nodes'])
    undone=store.history_action(202608,changed['revision'],'undo')
    assert not undone['rows'][0]['calculation']['recruitment']['recoveries']
    assert sum(n['amount'] for n in undone['rows'][0]['calculation']['recruitment']['nodes'])==60
