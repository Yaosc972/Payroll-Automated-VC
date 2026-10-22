from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bonus_platform.engine.recruitment_trials import ScopedDraftStore, TRIAL
from bonus_platform.engine.recruitment_settlement import apply_settlement, preview_plan, apply_plan
from bonus_platform.engine.recruitment_awards import award
from test_recruitment_opening import fixture
from test_recruitment_drafts import book


def test_trusted_opening_empty_helper_is_not_automatically_added_from_offer(tmp_path):
    from bonus_platform.engine.recruitment_drafts import DraftStore
    store=DraftStore(tmp_path)
    state=store.read(202607);state['strictInputs']=True
    store._write(store._folder(202607)/'draft.json',state)
    opening=book(['姓名','工号','入职日期','海外offer流程编号','协助招聘人工号','协助招聘人姓名'],
                 [['历史人员','zt1','2026-06-15','OF1','','']],title='附件一-招聘奖金核算明细')
    offer=book(['offer编码','编制ABC分类','协助招聘人工号','协助招聘人姓名'],[['OF1','C','zt2','新协助人']])
    state=store.ingest(202607,[('招聘奖金核算明细202606.xlsx',opening),('录用.xlsx',offer)],0)
    state=store.change(202607,state['revision'],{'baseline':state['sources'][0]['id']})
    row=state['rows'][0]
    assert not row['values'].get('协助招聘人工号')
    assert not row['values'].get('协助招聘人姓名')
    assert not any(c['sourceId']==state['baseline'] for c in row['conflicts'])
    assert any(p['value']=='zt2' for p in row['provenance']['协助招聘人工号'])
    # Genuine approved changes still supersede the opening relationship.
    state=store.change(202607,state['revision'],{'edits':[
        {'rowId':row['id'],'field':'协助招聘人工号','value':'zt2','reason':'核实原始录用关系','evidenceId':state['sources'][1]['id']},
        {'rowId':row['id'],'field':'协助招聘人姓名','value':'新协助人','reason':'核实原始录用关系','evidenceId':state['sources'][1]['id']} ]})
    assert state['rows'][0]['values']['协助招聘人工号']=='zt2'


def test_opening_without_helper_columns_does_not_claim_no_helper(tmp_path):
    from bonus_platform.engine.recruitment_drafts import DraftStore
    store=DraftStore(tmp_path)
    state=store.read(202607);state['strictInputs']=True
    store._write(store._folder(202607)/'draft.json',state)
    opening=book(['姓名','工号','入职日期','海外offer流程编号'],
                 [['历史人员','zt1','2026-06-15','OF1']],title='附件一-招聘奖金核算明细')
    offer=book(['offer编码','编制ABC分类','协助招聘人工号','协助招聘人姓名'],[['OF1','C','zt2','协助人']])
    state=store.ingest(202607,[('招聘奖金核算明细202606.xlsx',opening),('录用.xlsx',offer)],0)
    state=store.change(202607,state['revision'],{'baseline':state['sources'][0]['id']})
    row=state['rows'][0]
    assert not row['values'].get('协助招聘人工号')
    assert '协助招聘人工号' not in row['openingAbsentFields']
    assert any(p['value']=='zt2' for p in row['provenance']['协助招聘人工号'])


def test_complete_opening_keeps_historical_recruitment_facts_but_updates_dates(tmp_path):
    from bonus_platform.engine.recruitment_drafts import DraftStore
    from test_recruitment_drafts import ROSTER
    store=DraftStore(tmp_path)
    state=store.read(202607);state['strictInputs']=True
    store._write(store._folder(202607)/'draft.json',state)
    opening=book(['姓名','工号','入职日期','身份证','标签分类','人员状态','招聘渠道','ABC类别','招聘启动日期','协助招聘人工号','协助招聘人姓名'],
                 [['历史人员','zt1','2026-06-15','ID1','国内','试用','招聘网站','C','2026-06-01','','']],title='附件一-招聘奖金核算明细')
    offer=book(['姓名','身份证','编制ABC分类','招聘渠道','是否二次入职','协助招聘人工号','协助招聘人姓名'],
               [['历史人员','ID1','A','内推','是','zt2','新协助人']])
    roster=book(ROSTER,[['历史人员','zt1','OF1','2026-06-15','正式','2026-07-20','','EHR入职','中国','中国']])
    state=store.ingest(202607,[('招聘奖金核算明细202606.xlsx',opening),('录用.xlsx',offer),('花名册.xlsx',roster)],0)
    state=store.change(202607,state['revision'],{'baseline':state['sources'][0]['id']})
    row=state['rows'][0];v=row['values']
    assert v['招聘渠道']=='招聘网站' and v['ABC类别']=='C'
    assert not v.get('是否二次入职') and not v.get('协助招聘人工号')
    assert v['转正日期']=='2026-07-20' and v['人员状态']=='试用'
    assert '招聘渠道' not in row['unresolvedFields']
    assert any(p['value']=='内推' for p in row['provenance']['招聘渠道'])
    # Historical fields stay frozen even without a selected/full-schema opening.
    state['baseline']='';state['settlement']={}
    rebuilt=store._rebuild(store._folder(202607),state)
    assert '招聘渠道' not in rebuilt['rows'][0]['unresolvedFields']


def test_changed_roster_start_cannot_create_second_bonus_without_employment_decision(tmp_path):
    from bonus_platform.engine.recruitment_drafts import DraftStore
    from test_recruitment_drafts import ROSTER
    store=DraftStore(tmp_path)
    state=store.read(202607);state['strictInputs']=True
    store._write(store._folder(202607)/'draft.json',state)
    opening=book(['姓名','工号','入职日期','海外offer流程编号','招聘渠道','ABC类别','招聘启动日期'],
                 [['历史人员','zt1','2026-06-15','OF1','招聘网站','C','2026-06-01']],title='附件一-招聘奖金核算明细')
    roster=book(ROSTER,[['历史人员','zt1','OF1','2026-07-01','试用','','','EHR入职','中国','中国']])
    state=store.ingest(202607,[('招聘奖金核算明细202606.xlsx',opening),('花名册.xlsx',roster)],0)
    state=store.change(202607,state['revision'],{'baseline':state['sources'][0]['id']})
    assert len(state['rows'])==2
    old,new=sorted(state['rows'],key=lambda r:r['values']['入职日期'])
    assert old['rule']['version']=='legacy'
    assert new['rule']['version']=='unresolved'
    assert new['employmentCandidates'][0]['rowId']==old['id']
    assert not new['calculation']['recruitment']['nodes']


def test_refresh_upgrades_saved_inputs_without_reupload_and_is_idempotent(tmp_path):
    from bonus_platform.engine.recruitment_drafts import DraftStore, ASSEMBLY_VERSION, DraftConflict
    store=DraftStore(tmp_path)
    state=store.ingest(202607,[('补充.xlsx',book(['体系外人员编号','姓名','入职日期'],[['x','甲','2026-07-01']]))],0)
    version=state['revision'];state['assemblyVersion']=0
    store._write(store._folder(202607)/'draft.json',state)
    updated=store.refresh(202607,version)
    assert updated['assemblyVersion']==ASSEMBLY_VERSION and updated['revision']==version+1
    assert store.refresh(202607,updated['revision'])['revision']==updated['revision']
    with pytest.raises(DraftConflict):store.refresh(202607,version)


def independent():
    _,row,_=fixture(True)
    # Source facts establish eligibility independently of the reference result.
    row['values']['推荐人工号']=''
    state={'month':202607,'revision':1,'strictInputs':True,'baseline':'june',
           'settlement':{'version':1,'baselineId':'june'},'sources':[{'id':'june','active':True}],
           'operations':[],'rows':[row]}
    result={k:award(row,k,202607) for k in ('recruitment','referral')}
    apply_settlement(state,row,result)
    row['calculation']=result
    return state,row,result


def test_rule_remainder_from_opening_without_result_workbook():
    state,row,result=independent()
    assert [(n['amount'],n['scheduledMonth']) for n in result['recruitment']['nodes']]==[(45,202605),(255,202607)]
    assert result['recruitment']['currentAmount']==255
    assert all(n['paidAmount'] is None for n in result['recruitment']['nodes'])
    row['values']['招聘启动日期']=''
    result={k:award(row,k,202607) for k in ('recruitment','referral')}
    apply_settlement(state,row,result)
    assert result['recruitment']['total'] is None
    assert result['recruitment']['currentAmount'] is None


def test_cancellation_only_reduces_unsettled_nodes():
    state,row,result=independent()
    row['values']['最后工作日']='2026-07-10'
    apply_settlement(state,row,result)
    assert result['recruitment']['currentAmount']==0
    assert result['recruitment']['nodes'][0]['amount']==45
    assert result['recruitment']['cancelledBalances'][0]['amount']==255


def test_plans_cannot_override_amount_or_use_reference_or_pay_early(tmp_path,monkeypatch):
    state,row,result=independent();store=ScopedDraftStore(tmp_path/'drafts')
    state['sources'].append({'id':'answer','comparisonOnly':True})
    node=result['recruitment']['nodes'][1]
    store._write(store._folder(202607)/'draft.json',state)
    monkeypatch.setattr('bonus_platform.engine.recruitment_settlement.ensure_calculated',lambda s:s)
    payload={'revision':1,'rowId':row['id'],'nodeId':node['id'],'action':'schedule','month':202607,'sourceId':'june','reason':'核对原始任职资料'}
    with pytest.raises(ValueError,match='金额'):preview_plan(store,202607,{**payload,'amount':45})
    with pytest.raises(ValueError,match='依据'):preview_plan(store,202607,{**payload,'sourceId':'answer'})
    with pytest.raises(ValueError,match='早于'):preview_plan(store,202607,{**payload,'month':202606})
    state['rows'][0]['calculation']['recruitment']['nodes'][1]['dueMonth']=202608
    store._write(store._folder(202607)/'draft.json',state)
    with pytest.raises(ValueError,match='提前'):preview_plan(store,202607,payload)


def test_catchup_needs_basis_and_preserves_amount(tmp_path,monkeypatch):
    state,row,result=independent();store=ScopedDraftStore(tmp_path/'drafts')
    row['values']['转正日期']='2026-06-27'
    apply_settlement(state,row,result)
    node=result['recruitment']['nodes'][1]
    assert node['scheduledMonth'] is None and node['planningIssue']
    store._write(store._folder(202607)/'draft.json',state)
    monkeypatch.setattr('bonus_platform.engine.recruitment_settlement.ensure_calculated',lambda s:s)
    payload={'revision':1,'rowId':row['id'],'nodeId':node['id'],'action':'schedule','month':202607,'sourceId':'june','reason':'六月未安排，核对原始依据后补发'}
    p=preview_plan(store,202607,payload)
    assert p['amount']==255
    state['operations']=[{'id':'plan','active':True}]
    state['installmentPlans']=[{**payload,'operationId':'plan'}]
    apply_settlement(state,row,result)
    assert result['recruitment']['nodes'][1]['scheduledMonth']==202607
    assert result['recruitment']['currentAmount']==255
    state['operations'][0]['active']=False
    apply_settlement(state,row,result)
    assert result['recruitment']['currentAmount']==0


def test_scoped_api_isolation_and_reference_input_guard(tmp_path,monkeypatch):
    import bonus_platform.recruitment_draft_api as api
    store=ScopedDraftStore(tmp_path/'drafts');monkeypatch.setattr(api,'store',store)
    app=FastAPI();app.include_router(api.router);app.include_router(api.trials_router);app.include_router(api.trial_drafts_router)
    client=TestClient(app)
    a=client.post('/api/recruitment/trials',json={'month':202607,'name':'七月独立试算'}).json()
    b=client.post('/api/recruitment/trials',json={'month':202607,'name':'另一个批次'}).json()
    prefix=lambda t:f"/api/recruitment/trials/{t['id']}/api/recruitment/drafts/202607"
    content=book(['姓名','工号','入职日期'],[['参考人员','zt1','2026-07-01']],title='附件一-招聘奖金核算明细')
    r=client.post(prefix(a)+'/sources',data={'revision':0,'periodConfirmed':'true'},files={'files':('招聘奖金核算明细202607.xlsx',content)})
    assert r.status_code==200,r.text
    state=r.json();assert state['strictInputs'] and state['sources'][0]['comparisonOnly'] and not state['rows']
    r=client.post(prefix(a)+'/changes',json={'revision':state['revision'],'baseline':state['sources'][0]['id']})
    assert r.status_code==400
    with ThreadPoolExecutor(2) as pool:
        aa,bb=list(pool.map(lambda p:client.get(p).json(),[prefix(a),prefix(b)]))
    assert aa['revision']==1 and bb['revision']==0 and aa['trial']['id']!=bb['trial']['id']
    assert client.get('/api/recruitment/drafts/202607').json()['revision']==0
    assert client.get(prefix(a).replace('202607','202608')).status_code==400


def test_new_calculation_defaults_name_and_preserves_existing_month(tmp_path,monkeypatch):
    import bonus_platform.recruitment_draft_api as api
    store=ScopedDraftStore(tmp_path/'drafts');monkeypatch.setattr(api,'store',store)
    original=store.ingest(202607,[('本月花名册.xlsx',book(['姓名','工号','入职日期'],[['已有人员','zt1','2026-07-01']]))],0)
    saved=(store._folder(202607)/'draft.json').read_bytes()
    app=FastAPI();app.include_router(api.router);app.include_router(api.trials_router);app.include_router(api.trial_drafts_router)
    client=TestClient(app)
    first=client.post('/api/recruitment/trials',json={'month':202607}).json()
    second=client.post('/api/recruitment/trials',json={'month':202607,'name':'  '}).json()
    assert first['id']!=second['id'] and first['name']==second['name']=='2026年7月核算'
    assert {t['id'] for t in client.get('/api/recruitment/trials').json()}=={first['id'],second['id']}
    fresh=client.get(f"/api/recruitment/trials/{second['id']}/api/recruitment/drafts/202607").json()
    assert fresh['revision']==0 and fresh['rows']==[] and fresh['sources']==[] and fresh['baseline']==''
    assert fresh['strictInputs'] and fresh['isTrial'] and fresh['trial']['id']==second['id']
    assert (store._folder(202607)/'draft.json').read_bytes()==saved
    assert client.get('/api/recruitment/drafts/202607').json()['revision']==original['revision']


@pytest.mark.parametrize('enable_domestic_api',[False,True])
def test_preview_keeps_new_records_inside_sandbox(tmp_path,monkeypatch,enable_domestic_api):
    from scripts.preview_recruitment_flow import create_app
    import bonus_platform.recruitment_draft_api as api
    from bonus_platform.engine import recruitment_beisen
    original=ScopedDraftStore(tmp_path/'original'/'drafts')
    monkeypatch.setattr(api,'store',original)
    monkeypatch.setattr(recruitment_beisen,'fetch',recruitment_beisen.fetch)
    monkeypatch.setattr(recruitment_beisen,'fetch_employment',recruitment_beisen.fetch_employment)
    original_fetch=recruitment_beisen.fetch
    original_employment=recruitment_beisen.fetch_employment
    data_root=tmp_path/'sandbox'
    client=TestClient(create_app(data_root,enable_domestic_api=enable_domestic_api))
    response=client.post('/api/recruitment/trials',json={'month':202607,'name':'重新核算'})
    assert response.status_code==200,response.text
    record=response.json()
    assert (data_root/'recruitment_trials'/record['id']/'trial.json').is_file()
    assert (data_root/'recruitment_trials'/record['id']/'drafts'/'202607'/'draft.json').is_file()
    assert not original.trial_root.exists()
    prefix=f"/api/recruitment/trials/{record['id']}/api/recruitment/drafts/202607"
    state=client.get(prefix).json()
    assert state['isTrial'] and state['month']==202607 and not state['rows']
    assert client.post(prefix+'/confirm-month',json={'revision':state['revision'],'coverageConfirmed':True}).status_code==400
    assert client.get('/api/recruitment/trials').json()==[record]
    if enable_domestic_api:
        assert recruitment_beisen.fetch is original_fetch
        assert recruitment_beisen.fetch_employment is original_employment
    else:
        with pytest.raises(ValueError,match='隔离预览不访问外部接口'):recruitment_beisen.fetch(['zt1'])
        with pytest.raises(ValueError,match='隔离预览不访问外部接口'):recruitment_beisen.fetch_employment(['zt1'])


def test_missing_recipient_numbers_do_not_remove_awards():
    from test_recruitment_awards import person
    row=person(招聘负责人工号='',推荐人工号='',协助招聘人工号='',协助招聘人姓名='已核实协助人',
               协助招聘人入职日期='2020-01-01',协助招聘人人员状态='正式')
    recruitment=award(row,'recruitment',202608)
    assert '招聘负责人待核' not in recruitment['issues']
    assert {n['role'] for n in recruitment['nodes']}=={'招聘负责人','协助招聘人'}
    assert award(row,'referral',202608)['total']>0


def test_strict_business_edits_allow_manual_correction_without_evidence(tmp_path):
    store=ScopedDraftStore(tmp_path/'drafts');trial=store.create_trial(202607,'依据测试')
    token=TRIAL.set(trial['id'])
    try:
        state=store.ingest(202607,[('历史台账202606.xlsx',book(['姓名','工号','入职日期'],[['人员','zt1','2026-06-01']],title='附件一-招聘奖金核算明细'))],0)
        edit={'rowId':state['rows'][0]['id'],'field':'ABC类别','value':'A'}
        changed=store.change(202607,state['revision'],{'edits':[edit]})
        assert changed['rows'][0]['values']['ABC类别']=='A'
        assert changed['edits'][-1]['reason']=='手工修改'
        assert changed['edits'][-1]['evidenceId']==''
    finally:TRIAL.reset(token)


def test_opening_recipient_is_not_rewritten_by_current_owner_correction():
    state,row,result=independent()
    row['history'][0]['cells'] += [{'column':22,'value':'zt-previous'},{'column':23,'value':'期初领取人'},{'column':56,'value':'人民币'}]
    apply_settlement(state,row,result)
    first,last=result['recruitment']['nodes']
    assert first['recipientName']=='期初领取人' and first['recipientId']=='zt-previous'
    assert last['recipientName']=='招聘负责人' and last['recipientId']=='zt-owner'


def test_approval_can_cover_people_across_separate_review_operations():
    from bonus_platform.engine.recruitment_settlement import approved_basis
    s={'sources':[{'id':'approval','attachment':True}], 'operations':[{'id':'a','active':True},{'id':'b','active':True}],
       'reviewEntries':[{'sourceId':'approval','operationId':op,'status':'已认可','scopeChecked':True,'rowIds':[row]} for op,row in [('a','first'),('b','second')]]}
    assert approved_basis(s,'approval','first')['id']=='approval'
    with pytest.raises(ValueError):approved_basis(s,'approval','unknown')
    s['reviewEntries'].append({'sourceId':'approval','status':'已驳回'})
    with pytest.raises(ValueError):approved_basis(s,'approval','first')
