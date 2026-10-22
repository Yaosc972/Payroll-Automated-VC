from copy import deepcopy

import pytest

from bonus_platform.engine import recruitment_approval_intake as approvals
from bonus_platform.engine import recruitment_reference_facts as facts
from bonus_platform.engine import recruitment_reviews as reviews
from bonus_platform.engine import recruitment_work_items as work
from test_recruitment_approval_intake import setup as approval_setup
from test_recruitment_drafts import book
from test_recruitment_reference_facts import fixture
from test_recruitment_workflow_remediation import employment_state


def paired_approval(tmp_path, monkeypatch, name='负责人甲'):
    store, state = approval_setup(tmp_path, monkeypatch,
        {'审批': '候选甲申请补充招聘负责人为负责人甲。'},
        [dict(姓名='候选甲', 工号='zt12345', 招聘负责人姓名='', 招聘负责人工号='')])
    values = {k: v for k, v in state['rows'][0]['values'].items() if isinstance(v, (str, int, float))}
    values.update(招聘负责人姓名=name, 招聘负责人工号='zt56789')
    state = store.ingest(202607, [('招聘奖金核算明细202607.xlsx',
        book(list(values), [list(values.values())], '附件一-招聘奖金核算明细'))], state['revision'], comparison_only=True)
    item = approvals.proposals(store, state)['items'][0]
    option = next(o for o in item['referenceOptions'] if o['field'] == '招聘负责人工号')
    payload = {'revision': state['revision'], 'itemIds': [item['id']],
               'referenceSelections': [{'itemId': item['id'], **option['referenceProposal']}]}
    return store, state, payload


def test_paired_recruiter_only_fills_missing_id_and_keeps_approval_name(tmp_path, monkeypatch):
    store, state, payload = paired_approval(tmp_path, monkeypatch)
    preview = approvals.preview(store, 202607, payload)
    saved = reviews.apply_preview(store, 202607, state['revision'], preview['id'])
    edits = {e['field']: e for e in saved['edits']}
    name, number = edits['招聘负责人姓名'], edits['招聘负责人工号']
    assert name['value'] == '负责人甲' and 'referenceFact' not in name
    assert number['value'] == 'zt56789' and number['referenceFact']['proof']['values']['招聘负责人姓名'] == '负责人甲'
    assert name['evidenceId'] != number['evidenceId'] and name['evidencePages'] == [1]
    assert approvals.proposals(store, saved)['items'][0]['status'] == 'consistent'
    disabled = store.change(202607, saved['revision'], {'source': {'id': number['evidenceId'], 'active': False}})
    assert disabled['rows'][0]['values']['招聘负责人姓名'] == '负责人甲'
    assert not disabled['rows'][0]['values'].get('招聘负责人工号')
    assert approvals.proposals(store, disabled)['items'][0]['status'] == 'blocked'
    restored = store.change(202607, disabled['revision'], {'source': {'id': number['evidenceId'], 'active': True}})
    assert restored['rows'][0]['values']['招聘负责人工号'] == 'zt56789'
    assert any(p.get('restored') for p in restored['referenceFacts']['byRowId'][saved['rows'][0]['id']])
    changed = store.change(202607, restored['revision'], {'edits': [
        {'rowId': saved['rows'][0]['id'], 'field': '招聘负责人姓名', 'value': '负责人乙'}]})
    assert changed['rows'][0]['values']['招聘负责人姓名'] == '负责人乙'
    assert not changed['rows'][0]['values'].get('招聘负责人工号')


def test_paired_recruiter_rejects_conflicting_approved_name(tmp_path, monkeypatch):
    store, state, payload = paired_approval(tmp_path, monkeypatch, name='负责人乙')
    with pytest.raises(ValueError):
        approvals.preview(store, 202607, payload)
    assert store.read(202607) == state


@pytest.mark.parametrize('key,mode,expected', [('intake:海外', 'intake', 'missing_fact'),
    ('recipient', 'recipient', 'missing_fact'), ('cycle', 'facts', 'resolve_fact'),
    ('employment', 'facts', 'resolve_fact')])
def test_action_class_ignores_unrelated_candidate_proposals(key, mode, expected):
    state = employment_state()
    state['referenceFacts'] = {'byRowId': {'current': [
        {'fields': ['ABC类别'], 'canAdopt': True, 'status': 'available'}]}}
    item = {'mode': mode, 'key': key, 'rowIds': ['current']}
    assert work.action_class(state, item) == expected
    assert work.action_class(state, {**item, 'ruleMaintenance': True}) == 'policy'
    assert work.action_class(state, {**item, 'mode': 'settlement'}) == 'review_history'


def test_action_class_uses_matching_row_and_current_needed_fields():
    state = employment_state()
    item = {'mode': 'intake', 'key': 'intake:海外', 'rowIds': ['current']}
    row = state['rows'][1]
    row['values']['招聘启动日期'] = ''
    proposal = {'fields': ['招聘启动日期'], 'canAdopt': True, 'status': 'available'}
    state['referenceFacts'] = {'byRowId': {'old': [proposal]}}
    assert work.action_class(state, item) == 'missing_fact'
    state['referenceFacts']['byRowId']['current'] = [proposal]
    assert work.action_class(state, item) == 'review_available'
    assert work.action_class(state, {**item, 'mode': 'facts', 'key': 'cycle'}) == 'review_available'
    proposal['status'] = 'superseded'
    assert work.action_class(state, item) == 'missing_fact'


def test_canonical_same_category_is_not_a_new_reference_fact(tmp_path):
    store, state, rid = fixture(tmp_path, reference={'ABC类别': 'C'}, origin={'ABC类别': 'C1类'})
    facts.project(store._folder(202607), state)
    assert not any('ABC类别' in p['fields'] for p in state['referenceFacts']['byRowId'][rid])
    conflict = deepcopy(state)
    conflict['rows'][0]['unresolvedFields'] = ['ABC类别']
    facts.project(store._folder(202607), conflict)
    assert any('ABC类别' in p['fields'] for p in conflict['referenceFacts']['byRowId'][rid])


def test_partial_pair_apply_rechecks_reference_content(tmp_path, monkeypatch):
    store, state, payload = paired_approval(tmp_path, monkeypatch)
    preview = approvals.preview(store, 202607, payload)
    source = state['sources'][-1]
    path = store._folder(202607) / 'sources' / source['storedName']
    path.write_bytes(path.read_bytes() + b'changed')
    with pytest.raises(ValueError):
        reviews.apply_preview(store, 202607, state['revision'], preview['id'])
    assert not store.read(202607)['edits']


def test_generic_manual_edit_still_cannot_overlap_a_reference_pair(tmp_path):
    store, state, rid = fixture(tmp_path)
    proposal = next(p for p in facts.proposals(store._folder(202607), state) if '招聘负责人工号' in p['values'])
    selection = {'proposalId': proposal['id'], 'signature': proposal['signature']}
    with pytest.raises(ValueError, match='重复单元格'):
        reviews.prepare_preview(store, 202607, state['revision'], [
            {'rowId': rid, 'field': '招聘负责人姓名', 'value': proposal['values']['招聘负责人姓名']}],
            reference_selections=[selection])
    preview = reviews.prepare_preview(store, 202607, state['revision'], [], reference_selections=[selection])
    saved = reviews.apply_preview(store, 202607, state['revision'], preview['id'])
    edits = {e['field']: e for e in saved['edits']}
    assert set(edits) == {'招聘负责人姓名', '招聘负责人工号'}
    assert all(e['referenceFact']['proof']['values'] == proposal['values'] for e in edits.values())
    assert not any(e['referenceFact'].get('retainedFields') for e in edits.values())
