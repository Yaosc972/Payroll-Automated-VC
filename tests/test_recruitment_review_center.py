from copy import deepcopy
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bonus_platform.engine import recruitment_review_center as center
from bonus_platform.engine.recruitment_drafts import DraftConflict
from test_recruitment_assignments import setup


def fixture(tmp_path):
    store, state = setup(tmp_path)
    source = {'id':'ledger', 'storedName':'ledger.xlsx', 'name':'2026年7月核对台账.xlsx', 'roles':['ledger'], 'active':True, 'comparisonOnly':True}
    state['sources'].append(source)
    records = []
    for i, row in enumerate(state['rows']):
        records.append({'role':'ledger','values':{**row['values'],'标准币种':'人民币'},'ref':{'sheet':'核对表','row':i+2,'sourceId':'ledger'},
                        'historyCells':[{'column':1,'label':'招聘负责人 / 入职1个月 / 发放奖金','value':123},
                                        {'column':2,'label':'周期','value':'202607'}]})
    store._write(store._folder(202607)/'parsed'/'ledger.json', {'records':records})
    store._write(store._folder(202607)/'draft.json', state)
    return store, state


def payload(store, state):
    d=center.project(store,state,'ledger')['differences'][0]
    return {'revision':state['revision'],'token':uuid4().hex,'sourceId':'ledger','differenceId':d['id'],
            'fingerprint':d['fingerprint'],'outcome':'retain','evidenceId':state['sources'][0]['id'],
            'reason':'原件第2行及适用分期，核对后保留当前结果','confirmed':True}


def test_queue_read_only_no_automatic_closure_and_no_money_changes(tmp_path):
    store,state=fixture(tmp_path);before=deepcopy(state)
    result=center.project(store,state,'ledger')
    assert result['summary']['pendingDifferences']>=2
    assert all(d['status']=='待核对' for d in result['differences'])
    assert store.read(202607)==before
    p=payload(store,state);saved=center.save_review(store,202607,p)
    assert [r['calculation'] for r in saved['rows']]==[r['calculation'] for r in before['rows']]
    queue=center.project(store,saved,'ledger')
    assert queue['summary']['retainedDifferences']==1
    assert queue['summary']['pendingDifferences']==len(queue['differences'])-1
    assert center.save_review(store,202607,p)==saved
    with pytest.raises(ValueError,match='另一条'):
        center.save_review(store,202607,{**p,'reason':'changed'})


def test_invalidates_on_fact_and_evidence_changes_and_undo_redo(tmp_path):
    store,state=fixture(tmp_path);p=payload(store,state);saved=center.save_review(store,202607,p)
    changed=deepcopy(saved);changed['rows'][0]['values']['招聘负责人姓名']='更正后的负责人'
    assert center.project(store,changed,'ledger')['summary']['recheckDifferences']==1
    changed=deepcopy(saved);changed['sources'][0]['active']=False
    assert center.project(store,changed,'ledger')['summary']['recheckDifferences']==1
    undone=store.history_action(202607,saved['revision'],'undo')
    assert center.project(store,undone,'ledger')['summary']['retainedDifferences']==0
    redone=store.history_action(202607,undone['revision'],'redo')
    assert center.project(store,redone,'ledger')['summary']['retainedDifferences']==1


def test_concurrency_scope_and_confirmation_guards(tmp_path):
    store,state=fixture(tmp_path);p=payload(store,state)
    for changes, message in [({'confirmed':False},'确认'),({'fingerprint':'old'},'差异已变化'),({'evidenceId':'ledger'},'原始资料'),({'reason':''},'核对依据')]:
        with pytest.raises(ValueError,match=message):center.save_review(store,202607,{**p,**changes})
    saved=center.save_review(store,202607,p)
    with pytest.raises(DraftConflict):center.save_review(store,202607,{**p,'token':uuid4().hex})
    carried=store.carry_forward(202608,202607,0)
    data=center.project(store,carried,'ledger')
    assert data['summary']['retainedDifferences']==0 and not data['history']
    changed=deepcopy(saved);changed['sources'][-1]['active']=False
    with pytest.raises(ValueError,match='停用'):center.project(store,changed,'ledger')


def test_pending_review_and_linked_records_do_not_close_differences(tmp_path):
    store,state=fixture(tmp_path)
    state['reviewEntries']=[{'id':'r','sourceId':state['sources'][0]['id'],'status':'已认可','rowIds':[state['rows'][0]['id']], 'note':'已有解释'}]
    store._write(store._folder(202607)/'draft.json',state)
    data=center.project(store,state,'ledger')
    assert data['differences'][0]['recordIds']==['approval:r']
    assert data['summary']['retainedDifferences']==0
    p=payload(store,state);p.update(outcome='pending',confirmed=False)
    saved=center.save_review(store,202607,p)
    assert center.project(store,saved,'ledger')['differences'][0]['status']=='待补依据'


def test_api_revision_and_save(tmp_path,monkeypatch):
    from bonus_platform import recruitment_draft_api as api
    store,state=fixture(tmp_path);monkeypatch.setattr(api,'store',store)
    app=FastAPI();app.include_router(api.router);client=TestClient(app)
    url='/api/recruitment/drafts/202607/review-center'
    assert client.get(url,params={'revision':0}).status_code==409
    assert client.get(url,params={'revision':state['revision'],'sourceId':'ledger'}).status_code==200
    p=payload(store,state)
    # The public projection needs a scoped store in production; use the saved
    # state here to verify route dispatch and preparation lock independently.
    monkeypatch.setattr(api,'public',lambda s:s)
    response=client.post(url,json=p)
    assert response.status_code==200,response.text
    assert response.json()['revision']==state['revision']+1


def test_disappeared_difference_keeps_history_without_claiming_payment(tmp_path):
    store,state=fixture(tmp_path);p=payload(store,state);saved=center.save_review(store,202607,p)
    path=store._folder(202607)/'parsed'/'ledger.json'
    import json
    parsed=json.loads(path.read_text())
    parsed['records'][0]['historyCells'][0]['value']=30
    store._write(path,parsed)
    result=center.project(store,saved,'ledger')
    assert len(result['differences'])==1
    assert result['history'][0]['current'] is False
    assert result['history'][0]['recordStatus']=='不在当前差异清单，请核对最新资料'
    assert result['summary']['retainedDifferences']==0


def test_review_revocation_invalidates_prior_confirmation(tmp_path):
    store,state=fixture(tmp_path)
    state['operations']=[{'id':'approval-op','active':True,'month':202607}]
    state['reviewEntries']=[{'id':'approval','operationId':'approval-op','sourceId':state['sources'][0]['id'],
                            'status':'已认可','rowIds':[state['rows'][0]['id']]}]
    store._write(store._folder(202607)/'draft.json',state)
    saved=center.save_review(store,202607,payload(store,state))
    saved['operations'][0]['active']=False
    result=center.project(store,saved,'ledger')
    assert result['summary']['recheckDifferences']==1
    assert result['records'][0]['status']=='已撤销'
