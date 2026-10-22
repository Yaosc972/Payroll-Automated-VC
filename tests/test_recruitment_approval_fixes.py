from copy import deepcopy
import pytest

from bonus_platform.engine import recruitment_approval_intake as intake
from bonus_platform.engine import recruitment_reviews as reviews
from bonus_platform.engine import recruitment_review_center as center
from bonus_platform.engine.recruitment_drafts import DraftConflict
from test_recruitment_approval_intake import setup


def apply(store, state, ids, **kwargs):
    preview = intake.preview(store, 202607, {'revision': state['revision'], 'itemIds': ids, **kwargs})
    return reviews.apply_preview(store, 202607, state['revision'], preview['id']), preview


@pytest.mark.parametrize('ending', [
    '节点名称：主管审批\n意见：同意剔除10天\n节点名称：最终审批\n最终意见：仅批准剔除5天。',
    '节点名称：初审\n审批意见：同意剔除10天\n节点名称：终审\n审批意见：仅批准剔除5天。\n操作时间：2026-07-20',
])
def test_final_approved_value_is_adopted(tmp_path, monkeypatch, ending):
    store, state = setup(tmp_path, monkeypatch, {'审批': '候选甲申请剔除10天。\n' + ending})
    item = intake.proposals(store, state)['items'][0]
    assert item['status'] == 'ready'
    assert next(f['value'] for f in item['fields'] if f['field'] == '周期剔除天数') == 5
    saved, _ = apply(store, state, [item['id']])
    assert saved['rows'][0]['values']['周期剔除天数'] == 5


def test_overturned_historical_exclusion_is_not_adopted(tmp_path, monkeypatch):
    store, state = setup(tmp_path, monkeypatch, {'审批': '候选甲申请剔除10天。\n节点名称：初审\n不发招聘奖金。\n节点名称：终审\n最终意见：撤销此前不发招聘奖金的意见，同意发放招聘奖金，批准剔除5天。'})
    item = intake.proposals(store, state)['items'][0]
    assert item['decisions'] == []
    saved, _ = apply(store, state, [item['id']])
    assert not saved.get('awardDecisions')


def test_each_subject_must_close_and_ids_stay_stable(tmp_path, monkeypatch):
    store, state = setup(tmp_path, monkeypatch, {'审批': '候选甲、候选乙均申请剔除10天。'}, [
        {'姓名': '候选甲', '工号': 'zt12345'}, {'姓名': '候选乙', '工号': 'zt12346'}])
    data = intake.proposals(store, state)
    assert len(data['items']) == 2
    first = next(i for i in data['items'] if i['person']['name'] == '候选甲')
    saved, _ = apply(store, state, [first['id']])
    assert not saved['reviewEntries'][-1]['scopeComplete']
    again = intake.proposals(store, saved)
    assert {i['id'] for i in again['items']} == {i['id'] for i in data['items']}
    assert again['documents'][0]['status'] == 'ready'
    second = next(i for i in again['items'] if i['person']['name'] == '候选乙')
    saved, _ = apply(store, saved, [second['id']])
    assert saved['reviewEntries'][-1]['scopeComplete']
    assert all(r['values']['周期剔除天数'] == 10 for r in saved['rows'])


def test_final_values_are_scoped_per_subject(tmp_path, monkeypatch):
    store, state = setup(tmp_path, monkeypatch, {'审批': '候选甲、候选乙均申请剔除10天。\n节点名称：终审\n最终意见：候选甲批准剔除5天；候选乙批准剔除3天。'}, [
        {'姓名': '候选甲', '工号': 'zt12345'}, {'姓名': '候选乙', '工号': 'zt12346'}])
    data = intake.proposals(store, state)
    assert len(data['items']) == 2
    saved, _ = apply(store, state, [i['id'] for i in data['items']])
    assert {r['values']['姓名']: r['values']['周期剔除天数'] for r in saved['rows']} == {'候选甲': 5, '候选乙': 3}


def test_unknown_final_resolution_can_be_corrected(tmp_path, monkeypatch):
    store, state = setup(tmp_path, monkeypatch, {'审批': '候选甲申请剔除10天。\n节点名称：终审\n最终意见：具体天数另行核定，不能按申请执行。'})
    item = intake.proposals(store, state)['items'][0]
    assert item['status'] == 'blocked'
    saved, _ = apply(store, state, [item['id']], overrides={item['id']: {'fields': {'周期剔除天数': 5}}})
    assert saved['rows'][0]['values']['周期剔除天数'] == 5


def test_no_change_records_only_review_and_invalidates_on_fact_change(tmp_path, monkeypatch):
    store, state = setup(tmp_path, monkeypatch, {'审批': '候选甲现有人员资料正确，本次无需调整。'})
    before = deepcopy(state)
    item = intake.proposals(store, state)['items'][0]
    saved, preview = apply(store, state, [item['id']], outcomes={item['id']: 'no_change'})
    assert preview['changes'] == [] and preview['edits'] == []
    assert saved.get('edits', []) == before.get('edits', [])
    assert intake.proposals(store, saved)['documents'][0]['status'] == 'consistent'
    assert reviews.apply_preview(store, 202607, state['revision'], preview['id']) == saved
    undone = store.history_action(202607, saved['revision'], 'undo')
    assert intake.proposals(store, undone)['documents'][0]['status'] != 'consistent'
    redone = store.history_action(202607, undone['revision'], 'redo')
    assert intake.proposals(store, redone)['documents'][0]['status'] == 'consistent'
    changed = store.change(202607, redone['revision'], {'edits': [{'rowId': redone['rows'][0]['id'], 'field': 'ABC类别', 'value': 'B'}]})
    assert intake.proposals(store, changed)['documents'][0]['status'] != 'consistent'
    with pytest.raises(DraftConflict):
        intake.preview(store, 202607, {'revision': state['revision'], 'itemIds': [item['id']], 'outcomes': {item['id']: 'no_change'}})


def test_no_change_cannot_dismiss_missing_attachment(tmp_path, monkeypatch):
    store, state = setup(tmp_path, monkeypatch, {'审批': '候选甲资料无需调整。附件：名单.xlsx'})
    data = intake.proposals(store, state)
    with pytest.raises(ValueError):
        intake.preview(store, 202607, {'revision': state['revision'], 'itemIds': [i['id'] for i in data['items']], 'outcomes': {i['id']: 'no_change' for i in data['items']}})
    assert intake.project(store, state)[0]['todos']


def test_review_center_uses_same_reopened_approval_projection(tmp_path, monkeypatch):
    store, state = setup(tmp_path, monkeypatch, {'审批': '候选甲申请剔除10天。'})
    item = intake.proposals(store, state)['items'][0]
    saved, _ = apply(store, state, [item['id']])
    changed = store.change(202607, saved['revision'], {'edits': [{'rowId': saved['rows'][0]['id'], 'field': '周期剔除天数', 'value': 12}]})
    assert intake.proposals(store, changed)['items'][0]['requiresRecheck']
    assert sum(w['key'].startswith('approval:') for w in center.project(store, changed)['workItems']) == 1


def test_final_change_invalidates_old_adopted_override(tmp_path, monkeypatch):
    bodies = {'审批': '候选甲申请剔除10天。\n节点名称：终审\n最终意见：批准剔除5天。'}
    store, state = setup(tmp_path, monkeypatch, bodies)
    item = intake.proposals(store, state)['items'][0]
    saved, _ = apply(store, state, [item['id']])
    bodies['审批'] = bodies['审批'].replace('批准剔除5天', '批准剔除3天')
    changed = intake.proposals(store, saved)['items'][0]
    assert changed['id'] == item['id']
    assert changed['status'] == 'ready' and changed['requiresRecheck']
    assert next(f['value'] for f in changed['fields'] if f['field'] == '周期剔除天数') == 3


def test_no_change_ignores_other_people_but_rechecks_changed_original(tmp_path, monkeypatch):
    bodies = {'审批': '候选甲资料正确，无需调整。'}
    store, state = setup(tmp_path, monkeypatch, bodies, [{'姓名': '候选甲', '工号': 'zt12345'}, {'姓名': '候选乙', '工号': 'zt12346'}])
    item = intake.proposals(store, state)['items'][0]
    saved, _ = apply(store, state, [item['id']], outcomes={item['id']: 'no_change'})
    other = next(r for r in saved['rows'] if r['values']['姓名'] == '候选乙')
    changed = store.change(202607, saved['revision'], {'edits': [{'rowId': other['id'], 'field': 'ABC类别', 'value': 'B'}]})
    assert intake.proposals(store, changed)['documents'][0]['status'] == 'consistent'
    bodies['审批'] += '\n最终意见：按B类岗位标准核算。'
    assert intake.proposals(store, changed)['documents'][0]['status'] != 'consistent'


def test_subject_cannot_be_overridden_to_another_person(tmp_path, monkeypatch):
    store, state = setup(tmp_path, monkeypatch, {'审批': '候选甲、候选乙均申请剔除10天。'}, [{'姓名': '候选甲', '工号': 'zt12345'}, {'姓名': '候选乙', '工号': 'zt12346'}])
    items = intake.proposals(store, state)['items']
    with pytest.raises(ValueError):
        apply(store, state, [items[0]['id']], overrides={items[0]['id']: {'rowId': items[1]['person']['rowId']}})


def test_numbered_subjects_keep_final_opinions_separate(tmp_path, monkeypatch):
    store, state = setup(tmp_path, monkeypatch, {'审批': '申请说明：\n1.在zt12345入职的offer中，申请剔除10天。\n2.在zt12346入职的offer中，申请剔除10天。\n节点名称：终审\n最终意见：候选甲批准剔除5天；候选乙批准剔除3天。'}, [{'姓名': '候选甲', '工号': 'zt12345'}, {'姓名': '候选乙', '工号': 'zt12346'}])
    data = intake.proposals(store, state)
    saved, _ = apply(store, state, [i['id'] for i in data['items']])
    assert {r['values']['姓名']: r['values']['周期剔除天数'] for r in saved['rows']} == {'候选甲': 5, '候选乙': 3}


def test_final_shortened_days_and_explicit_no_change(tmp_path, monkeypatch):
    bodies = {'审批': '候选甲申请剔除10天。\n节点名称：终审\n最终意见：仅批准5天。'}
    store, state = setup(tmp_path, monkeypatch, bodies)
    item = intake.proposals(store, state)['items'][0]
    assert next(f['value'] for f in item['fields'] if f['field'] == '周期剔除天数') == 5
    bodies['审批'] = bodies['审批'].replace('仅批准5天', '保持现有资料，无需调整')
    item = intake.proposals(store, state)['items'][0]
    assert item['fields'] == [] and item['canMarkNoChange']
    saved, _ = apply(store, state, [item['id']], outcomes={item['id']: 'no_change'})
    assert not saved['rows'][0]['values'].get('周期剔除天数')


def test_changed_original_between_preview_and_apply_is_rejected(tmp_path, monkeypatch):
    bodies = {'审批': '候选甲资料正确，无需调整。'}
    store, state = setup(tmp_path, monkeypatch, bodies)
    item = intake.proposals(store, state)['items'][0]
    preview = intake.preview(store, 202607, {'revision': state['revision'], 'itemIds': [item['id']], 'outcomes': {item['id']: 'no_change'}})
    bodies['审批'] += '\n最终意见：岗位类别改为B。'
    with pytest.raises(ValueError):
        reviews.apply_preview(store, 202607, state['revision'], preview['id'])
    assert store.read(202607) == state


def test_unmatched_named_subject_remains_open(tmp_path, monkeypatch):
    store, state = setup(tmp_path, monkeypatch, {'审批': '候选甲、候选乙均申请剔除10天。'})
    data = intake.proposals(store, state)
    assert len(data['items']) == 2
    first = next(i for i in data['items'] if i['person']['name'] == '候选甲')
    saved, _ = apply(store, state, [first['id']])
    assert not saved['reviewEntries'][-1]['scopeComplete']
    assert intake.proposals(store, saved)['documents'][0]['status'] == 'blocked'


def test_unreadable_original_cannot_use_no_change(tmp_path, monkeypatch):
    store, state = setup(tmp_path, monkeypatch, {'审批': '候选甲资料正确，无需调整。'})
    monkeypatch.setattr(intake, 'extract_document', lambda *args: {'pages': [{'page': 1, 'text': '', 'blank': False, 'notice': 'OCR不可用'}], 'pageCount': 1})
    item = intake.proposals(store, state)['items'][0]
    assert not item['canMarkNoChange']
    with pytest.raises(ValueError):
        apply(store, state, [item['id']], outcomes={item['id']: 'no_change'})


def test_no_change_rechecks_replaced_attachment(tmp_path, monkeypatch):
    from test_recruitment_drafts import book
    store, state = setup(tmp_path, monkeypatch, {'审批': '候选甲资料正确，无需调整。附件：名单.xlsx'})
    state = store.ingest(202607, [('名单.xlsx', book(['姓名', '工号'], [['候选甲', 'zt12345']]))], state['revision'])
    item = intake.proposals(store, state)['items'][0]
    saved, _ = apply(store, state, [item['id']], outcomes={item['id']: 'no_change'})
    assert intake.proposals(store, saved)['documents'][0]['status'] == 'consistent'
    attachment = next(s for s in saved['sources'] if s['name'] == '名单.xlsx')
    (store._folder(202607) / 'sources' / attachment['storedName']).write_bytes(book(['姓名', '工号'], [['候选甲', 'zt12346']]))
    assert intake.proposals(store, saved)['documents'][0]['status'] != 'consistent'


def test_no_change_requires_one_employment_and_retains_selection(tmp_path, monkeypatch):
    store, state = setup(tmp_path, monkeypatch, {'审批': '候选甲资料正确，无需调整。'}, [{'姓名': '候选甲', '工号': 'zt12345'}, {'姓名': '候选甲', '工号': 'zt12346'}])
    item = intake.proposals(store, state)['items'][0]
    assert not item['canMarkNoChange']
    with pytest.raises(ValueError):
        apply(store, state, [item['id']], outcomes={item['id']: 'no_change'})
    rid = state['rows'][0]['id']
    saved, _ = apply(store, state, [item['id']], outcomes={item['id']: 'no_change'}, overrides={item['id']: {'rowId': rid}})
    resolved = intake.proposals(store, saved)['items'][0]
    assert resolved['person']['rowId'] == rid and resolved['status'] == 'consistent'


def test_final_explicit_rejection_of_requested_days_uses_positive_limit(tmp_path, monkeypatch):
    store, state = setup(tmp_path, monkeypatch, {'审批': '候选甲申请剔除10天。\n节点名称：终审\n最终意见：不同意原申请剔除10天，仅批准剔除5天。'})
    item = intake.proposals(store, state)['items'][0]
    assert item['status'] == 'ready'
    saved, _ = apply(store, state, [item['id']])
    assert saved['rows'][0]['values']['周期剔除天数'] == 5


def test_unrecognized_final_instruction_never_defaults_to_application(tmp_path, monkeypatch):
    store, state = setup(tmp_path, monkeypatch, {'审批': '候选甲申请剔除10天。\n节点名称：终审\n最终意见：请按最新核定口径执行。'})
    item = intake.proposals(store, state)['items'][0]
    assert item['status'] == 'blocked' and any('最终' in issue for issue in item['issues'])


def test_unordered_oa_column_opinions_do_not_guess_latest_value(tmp_path, monkeypatch):
    store, state = setup(tmp_path, monkeypatch, {'审批': '候选甲申请剔除10天。\n节点名称\n直接上级审核\nHSSC审核\n操作者\n审批甲\n审批乙\n处理意见\n同意剔除5天\n同意剔除3天'})
    item = intake.proposals(store, state)['items'][0]
    assert item['status'] == 'blocked'
    saved, _ = apply(store, state, [item['id']], overrides={item['id']: {'fields': {'周期剔除天数': 3}}})
    assert saved['rows'][0]['values']['周期剔除天数'] == 3


def test_final_opinion_can_add_subject_without_overwriting_original_subject(tmp_path, monkeypatch):
    store, state = setup(tmp_path, monkeypatch, {'审批': '候选甲申请剔除10天。\n节点名称：终审\n最终意见：候选甲维持原申请；候选乙批准剔除5天。'}, [{'姓名': '候选甲', '工号': 'zt12345'}, {'姓名': '候选乙', '工号': 'zt12346'}])
    data = intake.proposals(store, state)
    assert len(data['items']) == 2
    first = next(i for i in data['items'] if i['person']['name'] == '候选甲')
    second = next(i for i in data['items'] if i['person']['name'] == '候选乙')
    assert next(f['value'] for f in first['fields'] if f['field'] == '周期剔除天数') == 10
    assert next(f['value'] for f in second['fields'] if f['field'] == '周期剔除天数') == 5
    saved, _ = apply(store, state, [first['id']])
    assert not saved['reviewEntries'][-1]['scopeComplete']
    saved, _ = apply(store, saved, [second['id']])
    assert saved['reviewEntries'][-1]['scopeComplete']
    assert {r['values']['姓名']: r['values']['周期剔除天数'] for r in saved['rows']} == {'候选甲': 10, '候选乙': 5}


def test_unmatched_subject_in_final_opinion_stays_separate_and_open(tmp_path, monkeypatch):
    store, state = setup(tmp_path, monkeypatch, {'审批': '候选甲申请剔除10天。\n节点名称：终审\n最终意见：候选甲维持原申请；候选乙批准剔除5天。'})
    data = intake.proposals(store, state)
    assert len(data['items']) == 2
    first = next(i for i in data['items'] if i['person']['name'] == '候选甲')
    second = next(i for i in data['items'] if i['person']['name'] == '候选乙')
    assert second['status'] == 'blocked' and not second['person']['rowId']
    saved, _ = apply(store, state, [first['id']])
    assert saved['rows'][0]['values']['周期剔除天数'] == 10
    assert not saved['reviewEntries'][-1]['scopeComplete']
    assert intake.proposals(store, saved)['documents'][0]['status'] == 'blocked'


def test_unknown_final_exclusion_target_is_not_assigned_to_known_subject(tmp_path, monkeypatch):
    store, state = setup(tmp_path, monkeypatch, {'审批': '候选甲申请剔除10天。\n节点名称：终审\n最终意见：候选甲维持原申请；候选乙不发招聘奖金。'})
    items = intake.proposals(store, state)['items']
    assert len(items) == 2
    first = next(i for i in items if i['person']['name'] == '候选甲')
    second = next(i for i in items if i['person']['name'] == '候选乙')
    assert not first['decisions'] and second['status'] == 'blocked'
    assert second['decisions'] == [{'kind': 'recruitment', 'action': 'exclude'}]


def legacy_applied(store, state, edits, complete=True):
    source = state['sources'][-1]
    preview = reviews.prepare_preview(store, 202607, state['revision'], edits, evidence={
        'sourceId': source['id'], 'pageNumbers': [1], 'status': '已认可', 'scopeChecked': True,
        'scopeComplete': complete, 'attachmentIds': [], 'note': '已核对适用人员及采用字段。'})
    return reviews.apply_preview(store, 202607, state['revision'], preview['id'])


def test_legacy_applied_scope_projects_original_edits_without_new_forms(tmp_path, monkeypatch):
    store, state = setup(tmp_path, monkeypatch, {'审批': '候选甲资料按已核定口径执行，名单另含候选乙供参考。'}, [{'姓名': '候选甲', '工号': 'zt12345'}, {'姓名': '候选乙', '工号': 'zt12346'}])
    rid = next(r['id'] for r in state['rows'] if r['values']['姓名'] == '候选甲')
    saved = legacy_applied(store, state, [{'rowId': rid, 'field': '管培生已批名单资格', 'value': '是'}])
    data = intake.proposals(store, saved)
    assert data['documents'][0]['status'] == 'consistent'
    assert [i['person']['rowId'] for i in data['items']] == [rid]
    assert saved['reviewEntries'][-1].get('adoptedItems') is None
    changed = store.change(202607, saved['revision'], {'edits': [{'rowId': rid, 'field': '管培生已批名单资格', 'value': '否'}]})
    assert intake.proposals(store, changed)['documents'][0]['status'] != 'consistent'


def test_legacy_complete_does_not_close_explicit_unapplied_subject(tmp_path, monkeypatch):
    store, state = setup(tmp_path, monkeypatch, {'审批': '候选甲、候选乙均申请剔除10天。'}, [{'姓名': '候选甲', '工号': 'zt12345'}, {'姓名': '候选乙', '工号': 'zt12346'}])
    rid = next(r['id'] for r in state['rows'] if r['values']['姓名'] == '候选甲')
    saved = legacy_applied(store, state, [{'rowId': rid, 'field': '周期剔除天数', 'value': 10}])
    data = intake.proposals(store, saved)
    assert any(i['person']['name'] == '候选乙' and i['status'] != 'consistent' for i in data['items'])
    assert data['documents'][0]['status'] != 'consistent'


def test_legacy_scope_never_survives_changed_original_or_undo(tmp_path, monkeypatch):
    store, state = setup(tmp_path, monkeypatch, {'审批': '候选甲资料按已核定口径执行。'})
    rid = state['rows'][0]['id']
    saved = legacy_applied(store, state, [{'rowId': rid, 'field': '管培生已批名单资格', 'value': '是'}])
    assert intake.proposals(store, saved)['documents'][0]['status'] == 'consistent'
    undone = store.history_action(202607, saved['revision'], 'undo')
    assert intake.proposals(store, undone)['documents'][0]['status'] != 'consistent'
    redone = store.history_action(202607, undone['revision'], 'redo')
    source = redone['sources'][-1]
    (store._folder(202607) / 'sources' / source['storedName']).write_text('其他原件')
    monkeypatch.setattr(intake, 'extract_document', lambda *args: {'pages': [{'page': 1, 'text': '候选甲资料按已核定口径执行。', 'blank': False}], 'pageCount': 1})
    assert intake.proposals(store, redone)['documents'][0]['status'] != 'consistent'


def test_legacy_partial_scope_keeps_unmatched_people_and_applied_fields(tmp_path, monkeypatch):
    store, state = setup(tmp_path, monkeypatch, {'审批': '候选甲、候选乙名单。领取甲为招聘负责人。'}, [{'姓名': '候选甲', '工号': 'zt12345'}])
    rid = state['rows'][0]['id']
    saved = legacy_applied(store, state, [{'rowId': rid, 'field': '招聘负责人姓名', 'value': '领取甲'}], complete=False)
    saved['reviewEntries'].append({'sourceId': saved['sources'][-1]['id'], 'status': '已认可', 'scopeChecked': True, 'scopeComplete': False,
        'applied': False, 'personScope': [{'name': '候选甲', 'rowId': rid, 'reason': '已采用'}, {'name': '候选乙', 'rowId': None, 'reason': '未找到有效任职'}]})
    data = intake.proposals(store, saved)
    assert len(data['items']) == 2
    assert next(i for i in data['items'] if i['person']['name'] == '候选甲')['status'] == 'consistent'
    assert next(i for i in data['items'] if i['person']['name'] == '候选乙')['status'] == 'blocked'
    assert data['documents'][0]['status'] == 'blocked'


@pytest.mark.parametrize('problem', ['attachment', 'unreadable'])
def test_legacy_review_cannot_hide_missing_or_unreadable_evidence(tmp_path, monkeypatch, problem):
    bodies = {'审批': '候选甲资料按已核定口径执行。'}
    store, state = setup(tmp_path, monkeypatch, bodies)
    saved = legacy_applied(store, state, [{'rowId': state['rows'][0]['id'], 'field': '管培生已批名单资格', 'value': '是'}])
    if problem == 'attachment':
        bodies['审批'] += '附件：名单.xlsx'
    else:
        monkeypatch.setattr(intake, 'extract_document', lambda *args: {'pages': [{'page': 1, 'text': '', 'blank': False, 'notice': 'OCR不可用'}], 'pageCount': 1})
    assert intake.proposals(store, saved)['documents'][0]['status'] == 'blocked'


def test_legacy_latest_rejection_reopens_previously_applied_scope(tmp_path, monkeypatch):
    store, state = setup(tmp_path, monkeypatch, {'审批': '候选甲资料按已核定口径执行。'})
    saved = legacy_applied(store, state, [{'rowId': state['rows'][0]['id'], 'field': '管培生已批名单资格', 'value': '是'}])
    changed = reviews.save_review(store, 202607, saved['revision'], {'sourceId': saved['sources'][-1]['id'], 'status': '已驳回', 'scopeChecked': False, 'scopeComplete': False, 'note': '核对后撤回原认可状态', 'pageNumbers': [1], 'attachmentIds': []})
    assert intake.proposals(store, changed)['documents'][0]['status'] == 'blocked'


def test_no_change_survives_month_only_and_blank_normalization(tmp_path, monkeypatch):
    store, state = setup(tmp_path, monkeypatch, {'审批': '候选甲资料正确，无需调整。'})
    item = intake.proposals(store, state)['items'][0]
    saved, _ = apply(store, state, [item['id']], outcomes={item['id']: 'no_change'})
    carried = deepcopy(saved)
    carried['month'] = 202608
    for row in carried['rows']:
        row['values'].update({'核算月份': 202608, '空白来源字段': ''})
    folder = store._folder(202607)
    monkeypatch.setattr(store, '_folder', lambda month: folder)
    assert intake.proposals(store, carried)['documents'][0]['status'] == 'consistent'


def test_month_specific_no_change_is_rechecked_after_carry_forward(tmp_path, monkeypatch):
    store, state = setup(tmp_path, monkeypatch, {'审批': '候选甲本月无需调整。'})
    item = intake.proposals(store, state)['items'][0]
    saved, _ = apply(store, state, [item['id']], outcomes={item['id']: 'no_change'})
    carried = deepcopy(saved)
    carried['month'] = 202608
    folder = store._folder(202607)
    monkeypatch.setattr(store, '_folder', lambda month: folder)
    assert intake.proposals(store, carried)['documents'][0]['status'] != 'consistent'
