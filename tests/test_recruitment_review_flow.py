"""Operator tasks explain the cause; calculation diagnostics remain preserved."""
from copy import deepcopy

from bonus_platform.engine import recruitment_work_items as work
from bonus_platform.engine.recruitment_actions import task_fields
from bonus_platform.engine.recruitment_attention import project
from test_recruitment_attention import state_for, fact_task
from test_recruitment_awards import person


def ready_row(**values):
    row=person(**values)
    row.update(sources=[],provenance={},employmentObservations=[],edits=[],offerMatched=True)
    return row


def test_date_conflict_owns_derived_standard_task_without_clearing_diagnostics():
    row=ready_row(候选人入职时间='2026-07-02')
    row['rule']['version']='unresolved'
    state=state_for([row],[fact_task(row,'hire_date','核对本次实际入职日期')])
    before=deepcopy(state);attention=project(state)
    assert any(t['kind']=='standard' for t in attention['current'])
    items=work.project(state,attention)
    assert any(i['key']=='employment' for i in items)
    assert not any(i['key']=='standard' for i in items)
    assert state==before and row['calculation']['recruitment']['total'] is None


def test_date_conflict_does_not_hide_an_independent_classification_gap():
    for values,unresolved in [({'职级':'-'},[]),({'职级':'P2-1'},['职级'])]:
        row=ready_row(候选人入职时间='2026-07-02')
        row['rule']['version']='unresolved'
        state=state_for([row],[fact_task(row,'hire_date','核对本次实际入职日期')])
        row['values'].update(values)
        row['unresolvedFields']=unresolved
        before=deepcopy(state)
        items=work.project(state,project(state))
        assert any(i['key']=='employment' for i in items)
        standard=next(i for i in items if i['key']=='standard')
        assert not standard['ruleMaintenance']
        assert state==before


def test_complete_person_facts_send_catalog_gap_to_rule_maintenance():
    row=ready_row(hire='2026-06-22',ABC类别='A',职级='P2-2')
    state=state_for([row],[]);before=deepcopy(state)
    item=next(i for i in work.project(state,project(state)) if i['key']=='standard')
    assert item['ruleMaintenance'] and item['title']=='补充适用奖金标准'
    data=work.detail(state,item)
    assert data['fields']==[]
    assert data['people'][0]['values']['职级']=='P2-2'
    assert state==before


def test_already_uploaded_opening_is_adoption_not_a_missing_upload():
    state=state_for([],[])
    state['sources']=[{'id':'june','name':'招聘奖金核算明细202606.xlsx','roles':['ledger'],'active':True},
                      {'id':'answer','name':'招聘奖金核算明细202607.xlsx','roles':['ledger'],'active':True,'comparisonOnly':True}]
    state['todos']=[{'id':'baseline','kind':'baseline','title':'选择可信期初','rowIds':[],'sourceIds':[]}]
    item=next(i for i in work.project(state,project(state)) if i['key']=='baseline')
    assert item['title']=='确认采用上月核算表'
    assert [s['id'] for s in item['openingCandidates']]==['june']


def test_work_detail_defaults_to_current_fields_but_preserves_future_data():
    first=ready_row(招聘渠道='其他');first['id']='current'
    second=ready_row(hire='2026-07-15',招聘渠道='其他');second['id']='future'
    state=state_for([first,second],[]);before=deepcopy(state)
    item=next(i for i in work.project(state,project(state)) if i['key']=='field:招聘渠道')
    data=work.detail(state,item)
    assert {p['id'] for p in data['people']}=={'current','future'}
    assert {b['rowId'] for f in data['currentFields'] for b in f['bindings']}=={'current'}
    assert {b['rowId'] for f in data['fields'] for b in f['bindings']}=={'current','future'}
    assert state==before


def test_hidden_future_recipient_value_does_not_make_current_form_mixed():
    first=ready_row(推荐人人员状态='试用');first['id']='current'
    second=deepcopy(first);second['id']='future';second['values'].update(入职日期='2026-07-15',候选人入职时间='2026-07-15',推荐人人员状态='在职')
    second['unresolvedFields']=['推荐人人员状态']
    state=state_for([first,second],[{**fact_task(second,'recipient_conflict','推荐人状态不同'),'recipientId':'zt-ref'}])
    item=next(i for i in work.project(state,project(state)) if i['key']=='recipient')
    data=work.detail(state,item)
    field=next(f for f in data['fields'] if f['field']=='推荐人人员状态')
    current=next(f for f in data['currentFields'] if f['field']=='推荐人人员状态')
    assert field['mixed'] is True
    assert current['value']=='试用' and current['mixed'] is False


def test_employment_form_shows_roster_date_as_a_real_source_choice():
    row=ready_row(入职日期='2026-04-13',候选人入职时间='2026-04-13')
    row['history']=[{'ref':{'sourceId':'ledger','sheet':'明细','row':2},'cells':[]}]
    row['provenance']={'入职日期':[{'sourceId':'ledger','sheet':'明细','row':2,'value':'2026-04-13'}]}
    row['employmentObservations']=[{'sourceId':'roster','sheet':'员工','row':8,'value':'2026-04-29'}]
    state=state_for([row],[fact_task(row,'employment_conflict','花名册与台账任职日期不同')])
    state['sources']=[{'id':'ledger','name':'上月核算表.xlsx'},{'id':'roster','name':'花名册.xlsx'}]
    item=next(i for i in work.project(state,project(state)) if i['key']=='employment')
    data=work.detail(state,item)
    review=data['people'][0]['employmentReview']
    assert {o['value'] for o in review['observations']}=={'2026-04-13','2026-04-29'}
    field=next(f for f in data['fields'] if f['field']=='入职日期')
    assert any(o['value']=='2026-04-29' and o['sources'][0]['sourceId']=='roster' for o in field['options'])


def test_recipient_count_is_actual_subjects_not_affected_candidates():
    first=ready_row(招聘负责人入职日期='');first['id']='one'
    second=deepcopy(first);second['id']='two'
    state=state_for([first,second],[])
    item=next(i for i in work.project(state,project(state)) if i['key']=='recipient')
    assert item['subjectCount']==1 and item['affectedCount']==2


def test_formal_qualification_exposes_probation_not_a_blank_last_work_day():
    row=ready_row(推荐人人员状态='在职',推荐人转正日期='')
    state_for([row],[])
    fields=task_fields(row,{'kind':'recipient'},202607)
    assert '推荐人转正日期' in fields
    assert '推荐人最后工作日' not in fields


def test_zero_exclusion_does_not_ask_for_an_unrelated_approval():
    row=ready_row(招聘启动日期='2026-07-05',周期剔除天数=0)
    state_for([row],[])
    assert '周期剔除依据' not in task_fields(row,{'kind':'cycle'},202607)


def test_grouping_never_shows_another_persons_missing_fields():
    first=ready_row(招聘启动日期='2026-07-02');first['id']='date-error'
    second=ready_row(ABC类别='',招聘启动日期='');second['id']='missing-data'
    state=state_for([first,second],[fact_task(second,'missing_fields','补充核算所需信息：ABC类别、招聘启动日期')])
    item=next(i for i in work.project(state,project(state)) if i['key']=='cycle')
    data=work.detail(state,item)
    person=next(p for p in data['people'] if p['id']=='date-error')
    assert not any('ABC类别' in r for r in person['reasons'])
    assert '晚于入职日' in person['explanation']


def test_other_channel_only_asks_for_its_missing_detail():
    row=ready_row(招聘渠道='其他')
    assert task_fields(row,{'kind':'field:招聘渠道'},202607)==['其他渠道']
    row['unresolvedFields']=['招聘渠道']
    assert task_fields(row,{'kind':'field:招聘渠道'},202607)==['招聘渠道']


def test_recipient_form_does_not_ask_about_unrelated_future_qualification():
    row=ready_row()
    row['calculation']={'recruitment':{'nodes':[{'dueMonth':202607,'issues':['招聘负责人：任职日期待核']}]},
                        'referral':{'nodes':[{'dueMonth':202610,'issues':['推荐人：推荐人正式在职状态待核']}]}}
    row['unresolvedFields']=[]
    assert task_fields(row,{'kind':'recipient'},202607)==['招聘负责人入职日期']


def test_name_lookup_only_uses_active_activity_materials_and_keeps_namesakes(tmp_path):
    from bonus_platform.engine.recruitment_drafts import DraftStore
    store=DraftStore(tmp_path)
    folder=tmp_path/'202607'
    records=[{'values':{'姓名':'李华','工号':'zt1'},'ref':{'sheet':'花名册','row':2}},
             {'values':{'姓名':'李华','工号':'zt2'},'ref':{'sheet':'花名册','row':3}},
             {'values':{'推荐人姓名':'王华','推荐人工号':'zt-ref'},'ref':{'sheet':'明细','row':4}},
             {'values':{'姓名':'只有姓名'},'ref':{}},
             {'values':{'姓名':'-','工号':'zt-empty'},'ref':{}}]
    for sid in ('active','comparison','inactive'):
        store._write(folder/'parsed'/f'{sid}.json',{'records':records})
    state=state_for([],[])
    state['sources']=[{'id':'active','name':'花名册.xlsx','active':True},
                      {'id':'comparison','name':'线下答案.xlsx','comparisonOnly':True},
                      {'id':'inactive','name':'已停用.xlsx','active':False}]
    before=deepcopy(state)
    choices=work.people_choices(folder,state,'李华')
    assert {p['employeeId'] for p in choices}=={'zt1','zt2'}
    assert all(s['sourceId']=='active' for p in choices for s in p['sources'])
    assert work.people_choices(folder,state,'ZT-REF')[0]['name']=='王华'
    assert work.people_choices(folder,state,'只有姓名')==[]
    assert work.people_choices(folder,state,'')==[]
    assert work.people_choices(folder,state,'zt-empty')==[]
    assert state==before


def test_name_lookup_endpoint_is_revision_checked(tmp_path,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from bonus_platform import recruitment_draft_api as api
    from bonus_platform.engine.recruitment_drafts import DraftStore
    from test_recruitment_drafts import book,ROSTER
    store=DraftStore(tmp_path)
    state=store.ingest(202607,[('花名册.xlsx',book(ROSTER,[['张三','zt7','OF7','2026-07-01','正式','','','OEHR入职','德国','德国']]))],0)
    before=(tmp_path/'202607'/'draft.json').read_bytes()
    monkeypatch.setattr(api,'store',store)
    app=FastAPI();app.include_router(api.router)
    client=TestClient(app)
    reply=client.get(f'/api/recruitment/drafts/202607/people?revision={state["revision"]}&q=张三')
    assert reply.status_code==200
    assert reply.json()['people'][0]['employeeId']=='zt7'
    assert client.get('/api/recruitment/drafts/202607/people?revision=0&q=张三').status_code==409
    assert (tmp_path/'202607'/'draft.json').read_bytes()==before
