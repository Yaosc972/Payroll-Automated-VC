from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bonus_platform.engine import recruitment_work_items as work
from bonus_platform.engine.recruitment_attention import project
from bonus_platform.engine.recruitment_drafts import DraftStore, DraftConflict
from bonus_platform.engine.recruitment_reviews import prepare_preview, apply_preview
from test_recruitment_awards import person
from test_recruitment_drafts import book


@pytest.fixture
def draft(tmp_path):
    store=DraftStore(tmp_path)
    values=person('2026-07-13',招聘启动日期='2026-07-15',周期剔除天数=0,招聘渠道='内推')['values']
    values['体系外人员编号']='cycle-test'
    state=store.ingest(202608,[('补充人员.xlsx',book(list(values),[list(values.values())]))],0)
    return store,state,state['rows'][0]['id']


def test_todo_offers_original_dates_without_changing_them(draft):
    store,state,rid=draft;before=deepcopy(state)
    item=next(item for item in work.project(state,project(state)) if item['key']=='cycle')
    data=work.detail(state,item)
    choice=data['people'][0]['originalCycle']
    assert choice==dict(startDate='2026-07-15',hireDate='2026-07-13',exclusionDays=0,
                        actualDays=-2,standardDays=42,confirmed=False)
    assert {f['field'] for f in data['fields']}=={'招聘启动日期','入职日期','周期剔除天数'}
    assert state==before and store.read(202608)['revision']==state['revision']


def test_original_date_action_updates_awards_and_supports_undo_redo(draft):
    store,state,rid=draft;values=deepcopy(state['rows'][0]['values'])
    result=work.confirm_original_cycle(store,202608,state['revision'],[rid])
    row=result['rows'][0];award=row['calculation']['recruitment']
    assert award['cycle']['actualDays']==-2 and award['cycle']['factor']==1.3
    assert award['total']==28.6 and award['currentAmount']==14.3
    assert {field:row['values'][field] for field in values}==values
    assert not any(item['key']=='cycle' for item in work.project(result,project(result)))
    assert result['operations'][-1]['label']=='按原日期核算招聘周期'
    repeated=work.confirm_original_cycle(store,202608,result['revision'],[rid,rid])
    assert repeated['revision']==result['revision'] and len(repeated['edits'])==4
    undone=store.history_action(202608,result['revision'],'undo')
    assert undone['rows'][0]['calculation']['recruitment']['total'] is None
    redone=store.history_action(202608,undone['revision'],'redo')
    assert redone['rows'][0]['calculation']['recruitment']['total']==28.6


def test_changing_dates_is_an_alternative_and_changed_confirmation_reopens(draft):
    store,state,rid=draft
    confirmed=work.confirm_original_cycle(store,202608,state['revision'],[rid])
    preview=prepare_preview(store,202608,confirmed['revision'],[dict(rowId=rid,field='招聘启动日期',value='2026-07-16')])
    changed=apply_preview(store,202608,confirmed['revision'],preview['id'])
    assert changed['rows'][0]['calculation']['recruitment']['total'] is None
    assert any(item['key']=='cycle' for item in work.project(changed,project(changed)))
    preview=prepare_preview(store,202608,changed['revision'],[dict(rowId=rid,field='招聘启动日期',value='2026-07-01')])
    corrected=apply_preview(store,202608,changed['revision'],preview['id'])
    cycle=corrected['rows'][0]['calculation']['recruitment']['cycle']
    assert cycle['actualDays']==12 and cycle['factor']==1.3 and not cycle.get('warning')


def test_action_rejects_stale_or_invalid_person_scope_atomically(draft):
    store,state,rid=draft
    with pytest.raises(DraftConflict):work.confirm_original_cycle(store,202608,0,[rid])
    with pytest.raises(ValueError):work.confirm_original_cycle(store,202608,state['revision'],[rid,'missing'])
    with pytest.raises(ValueError):work.confirm_original_cycle(store,202608,state['revision'],[])
    assert store.read(202608)['revision']==state['revision']


def test_next_month_reuses_confirmation_and_new_exclusion_invalidates_it(draft):
    store,state,rid=draft
    confirmed=work.confirm_original_cycle(store,202608,state['revision'],[rid])
    following=store.carry_forward(202609,202608,0)
    row=following['rows'][0]
    assert row['calculation']['recruitment']['cycle']['actualDays']==-2
    assert row['calculation']['recruitment']['total']==28.6
    assert row['values']['负周期确认剔除天数']==0
    changed=store.change(202609,following['revision'],{'edits':[dict(rowId=rid,field='周期剔除天数',value=1)]})
    assert changed['rows'][0]['calculation']['recruitment']['total'] is None


def test_conflicting_dates_and_invalid_exclusion_do_not_offer_adoption(draft):
    _,state,_=draft;row=deepcopy(state['rows'][0])
    row['unresolvedFields']=['招聘启动日期']
    assert work.original_cycle_option(row) is None
    row['unresolvedFields']=[];row['values']['周期剔除天数']='1e10000'
    assert work.original_cycle_option(row) is None


def test_optional_blank_exclusion_does_not_require_another_input(draft):
    store,state,rid=draft
    state=store.change(202608,state['revision'],{'edits':[dict(rowId=rid,field='周期剔除天数',value='')]})
    result=work.confirm_original_cycle(store,202608,state['revision'],[rid])
    assert result['rows'][0]['calculation']['recruitment']['cycle']['actualDays']==-2


def test_api_applies_without_a_second_preview_or_confirmation(draft,monkeypatch):
    from bonus_platform import recruitment_draft_api as api
    store,state,rid=draft;monkeypatch.setattr(api,'store',store)
    app=FastAPI();app.include_router(api.router);client=TestClient(app)
    url='/api/recruitment/drafts/202608/cycle-confirmations'
    assert client.post(url,json={'revision':0,'rowIds':[rid]}).status_code==409
    response=client.post(url,json={'revision':state['revision'],'rowIds':[rid]})
    assert response.status_code==200,response.text
    assert response.json()['rows'][0]['calculation']['recruitment']['total']==28.6
    assert not list((store._folder(202608)/'previews').glob('*.json'))
