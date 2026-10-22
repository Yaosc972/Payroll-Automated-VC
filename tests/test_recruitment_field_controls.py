from copy import deepcopy

import pytest

from bonus_platform.engine.recruitment_awards import award, channel
from bonus_platform.engine.recruitment_drafts import DraftStore
from bonus_platform.engine.recruitment_field_controls import controls, normalize_edit, SYSTEM_FIELDS
from bonus_platform.engine.recruitment_reviews import prepare_preview, apply_preview
from bonus_platform.engine.recruitment_attention import project
from bonus_platform.engine.recruitment_work_items import project as work_items, detail
from test_recruitment_awards import person
from test_recruitment_drafts import book


def setup(tmp_path, **overrides):
    values=person(招聘渠道='二次入职',上次离职日期='2026-01-01',**overrides)['values']
    values['体系外人员编号']='test'
    store=DraftStore(tmp_path)
    state=store.ingest(202607,[('任职与招聘资料.xlsx',book(list(values),[list(values.values())]))],0)
    return store,state,state['rows'][0]['id']


@pytest.mark.parametrize('choice,factor',[('不发招聘奖金',0),('按40%核算',.4)])
def test_explicit_rehire_choice_changes_calculation_and_survives_carry_undo_redo(tmp_path,choice,factor):
    store,state,rid=setup(tmp_path)
    item=next(i for i in work_items(state,project(state)) if i['key'].startswith('rehire:'))
    field=detail(state,item)['fields'][0]
    assert field['field']=='二次入职执行口径'
    assert {c['value'] for c in field['choices']}=={'不发招聘奖金','按40%核算'}
    assert '二次入职专项口径依据' not in {f['field'] for f in detail(state,item)['fields']}
    assert state['rows'][0]['calculation']['recruitment']['total'] is None
    preview=prepare_preview(store,202607,state['revision'],[{'rowId':rid,'field':field['field'],'value':choice}])
    assert store.read(202607)['revision']==state['revision']
    saved=apply_preview(store,202607,state['revision'],preview['id'])
    result=saved['rows'][0]['calculation']['recruitment']
    assert result['channelFactor']==factor and result['total'] is not None
    assert (result['total']==0)==(factor==0)
    assert not any(i['key'].startswith('rehire:') for i in work_items(saved,project(saved)))
    assert saved['rows'][0]['calculation']['referral']['total']==0
    undone=store.history_action(202607,saved['revision'],'undo')
    assert undone['rows'][0]['calculation']['recruitment']['total'] is None
    redone=store.history_action(202607,undone['revision'],'redo')
    assert redone['rows'][0]['calculation']['recruitment']['channelFactor']==factor
    carried=store.carry_forward(202608,202607,0)
    assert carried['rows'][0]['values']['二次入职执行口径']==choice
    assert carried['rows'][0]['calculation']['recruitment']['channelFactor']==factor


def test_rehire_choice_cannot_replace_dates_or_override_other_rule_scopes():
    values=person(招聘渠道='二次入职',二次入职执行口径='不发招聘奖金')['values']
    assert channel(values,'2026-07')[0] is None
    values['上次离职日期']='2024-01-01'
    assert channel(values,'2026-07')[:2]==(.4,[])
    assert channel(values,'legacy')[:2]==(.4,[])
    values['上次离职日期']='2026-01-01';values['二次入职执行口径']='随便写点说明'
    assert channel(values,'2026-07')[0] is None


@pytest.mark.parametrize('field,value',[('二次入职执行口径','已确认'),('应届校招','应当是'),('推荐人与候选人上下级关系','不是上级'),('延后入职原因','随便说明')])
def test_non_choice_text_is_rejected_by_the_edit_boundary(tmp_path,field,value):
    store,state,rid=setup(tmp_path)
    with pytest.raises(ValueError,match='请选择有效'):
        prepare_preview(store,202607,state['revision'],[{'rowId':rid,'field':field,'value':value}])
    assert store.read(202607)['revision']==state['revision']


def test_cycle_basis_selects_existing_record_without_retyping_explanation(tmp_path):
    store,state,rid=setup(tmp_path,周期剔除天数=3)
    row=state['rows'][0];before=deepcopy(state)
    definition=controls(state,row)['周期剔除依据']
    choice=definition['choices'][0]
    assert choice['label']=='任职与招聘资料.xlsx'
    preview=prepare_preview(store,202607,state['revision'],[{'rowId':rid,'field':'周期剔除依据','value':choice['value']}])
    saved=apply_preview(store,202607,state['revision'],preview['id'])
    edit=saved['edits'][-1]
    assert edit['evidenceId']==state['sources'][0]['id']
    assert '任职与招聘资料.xlsx' in saved['rows'][0]['values']['周期剔除依据']
    assert state==before
    state['sources'][0]['active']=False
    assert not controls(state,row)['周期剔除依据']['choices']
    with pytest.raises(ValueError,match='资料已变化'):
        normalize_edit(state,row,'周期剔除依据',choice['value'],'')


def test_unrelated_or_comparison_files_are_not_offered_as_cycle_evidence():
    row=person(周期剔除天数=3);state={'sources':[{'id':'unrelated','name':'其他资料','active':True},
                                 {'id':'comparison','name':'核对结果','comparisonOnly':True}]}
    row['provenance']={'周期剔除天数':[{'sourceId':'comparison','value':3}]}
    definition=controls(state,row)['周期剔除依据']
    assert not definition['choices'] and '缺少' in definition['missingMessage']
    assert {'二次入职专项口径依据','旧特殊规则依据','负周期确认依据'}<=SYSTEM_FIELDS


def test_hierarchy_choices_control_eligibility_without_parsing_explanations():
    row=person(直线经理工号='',推荐人与候选人上下级关系='是')
    assert award(row,'referral',202607)['total']==0
    row['values']['推荐人与候选人上下级关系']='否'
    assert award(row,'referral',202607)['total']==400


def test_continuation_choice_previews_scope_and_does_not_create_new_awards(tmp_path):
    store,state,rid=setup(tmp_path)
    choice='任职延续：人员迁移，本段不新增奖金'
    preview=prepare_preview(store,202607,state['revision'],[{'rowId':rid,'field':'任职说明','value':choice}])
    assert {'任职说明','核算范围'}<={c['field'] for c in preview['changes']}
    saved=apply_preview(store,202607,state['revision'],preview['id'])
    row=saved['rows'][0]
    assert row['values']['核算范围']=='不纳入核算'
    assert row['scopeStatus']!='已纳入底稿'
    undone=store.history_action(202607,saved['revision'],'undo')
    assert undone['rows'][0]['values'].get('核算范围')!='不纳入核算'


def test_changed_days_cannot_borrow_a_source_that_only_proves_old_days(tmp_path):
    store,state,rid=setup(tmp_path,周期剔除天数=3)
    selected=controls(state,state['rows'][0])['周期剔除依据']['choices'][0]['value']
    with pytest.raises(ValueError,match='资料已变化'):
        prepare_preview(store,202607,state['revision'],[{'rowId':rid,'field':'周期剔除天数','value':9},
                                                      {'rowId':rid,'field':'周期剔除依据','value':selected}])


def test_batch_controls_reuse_common_material_and_route_distinct_people_without_reupload(tmp_path,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from bonus_platform import recruitment_draft_api as api
    from bonus_platform.engine.recruitment_field_controls import shared_controls
    store,state,rid=setup(tmp_path,周期剔除天数=3)
    monkeypatch.setattr(api,'store',store)
    app=FastAPI();app.include_router(api.router)
    response=TestClient(app).post('/api/recruitment/drafts/202607/field-controls',json={'revision':state['revision'],'rowIds':[rid]})
    assert response.status_code==200
    assert response.json()['fieldControls']['周期剔除依据']['choices']
    other=person();other['id']='other'
    result=shared_controls(state,[state['rows'][0],other])['周期剔除依据']
    assert not result['choices']
    assert [p['id'] for p in result['people']]==[rid,'other']
    assert '上传' not in result['missingMessage']


def test_a_later_day_change_invalidates_source_basis_and_undo_restores_it(tmp_path):
    store,state,rid=setup(tmp_path,周期剔除天数=3)
    selected=controls(state,state['rows'][0])['周期剔除依据']['choices'][0]['value']
    preview=prepare_preview(store,202607,state['revision'],[{'rowId':rid,'field':'周期剔除依据','value':selected},
                                                         {'rowId':rid,'field':'二次入职执行口径','value':'按40%核算'}])
    saved=apply_preview(store,202607,state['revision'],preview['id'])
    original=saved['rows'][0]['values']['周期剔除依据']
    changed=store.change(202607,saved['revision'],{'edits':[{'rowId':rid,'field':'周期剔除天数','value':13}]})
    row=changed['rows'][0]
    assert not row['values']['周期剔除依据']
    assert '周期剔除依据待核' in row['calculation']['recruitment']['issues']
    undone=store.history_action(202607,changed['revision'],'undo')
    assert undone['rows'][0]['values']['周期剔除依据']==original
    assert '周期剔除依据待核' not in undone['rows'][0]['calculation']['recruitment']['issues']
    carried=store.carry_forward(202608,202607,0)
    assert carried['rows'][0]['values']['周期剔除依据']==original


def test_source_disabling_invalidates_adopted_cycle_evidence(tmp_path):
    store,state,rid=setup(tmp_path,周期剔除天数=3)
    values=person(招聘渠道='二次入职',上次离职日期='2026-01-01',周期剔除天数=3)['values'];values['体系外人员编号']='test'
    state=store.ingest(202607,[('另一份任职资料.xlsx',book(list(values),[list(values.values())],title='另一份资料'))],state['revision'])
    token=controls(state,state['rows'][0])['周期剔除依据']['choices'][0]['value']
    saved=store.change(202607,state['revision'],{'edits':[{'rowId':rid,'field':'周期剔除依据','value':token},
                                                       {'rowId':rid,'field':'二次入职执行口径','value':'按40%核算'}]})
    changed=store.change(202607,saved['revision'],{'source':{'id':token[7:],'active':False}})
    assert not changed['rows'][0]['values']['周期剔除依据']
    assert '周期剔除依据待核' in changed['rows'][0]['calculation']['recruitment']['issues']


def test_zero_exclusion_does_not_request_an_unnecessary_document():
    row=person(周期剔除天数=0);row['calculation']={'recruitment':award(row,'recruitment',202607)}
    definition=controls({'sources':[]},row)['周期剔除依据']
    assert definition['upload'] is False and '缺少' not in definition['missingMessage']


def test_an_old_basis_description_cannot_bypass_its_sources_day_count():
    state={'sources':[{'id':'original','name':'原始资料','active':True}]}
    row=person(周期剔除天数=9)
    row['provenance']={'周期剔除依据':[{'sourceId':'original','value':'审批同意剔除3天'}],
                       '周期剔除天数':[{'sourceId':'original','value':3}]}
    with pytest.raises(ValueError,match='资料已变化'):
        normalize_edit(state,row,'周期剔除依据','source:original','')
