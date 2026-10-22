"""Applying one reviewed change assembles only the final, complete operation."""
from copy import deepcopy
import shutil

import pytest

from bonus_platform.engine.recruitment_drafts import DraftStore
from bonus_platform.engine import recruitment_reviews as reviews
from test_recruitment_reviews import setup


def comparable(state):
    """Ignore generated operation identities and wall-clock audit timestamps."""
    operation_ids = {item['id']: f'operation-{i}' for i, item in enumerate(state.get('operations', []))}

    def visit(value):
        if isinstance(value, dict):
            return {operation_ids.get(key, key): visit(item) for key, item in value.items()
                    if key not in {'at', 'updatedAt'}}
        if isinstance(value, list):
            return [visit(item) for item in value]
        return operation_ids.get(value, value) if isinstance(value, str) else value

    return visit(state)


@pytest.mark.parametrize('kind', ['edit', 'approval_edit', 'approval_decision',
                                  'manual_decision', 'arrangement', 'review_only'])
def test_apply_assembles_once_and_matches_previous_results_with_undo_redo(tmp_path, monkeypatch, kind):
    store, state, rid = setup(tmp_path / 'current')
    evidence = None
    if kind in {'approval_edit', 'approval_decision', 'arrangement', 'review_only'}:
        state = store.ingest(202607, [('审批.pdf', b'%PDF-test')], state['revision'])
        monkeypatch.setattr(reviews, 'document', lambda *args: {'pageCount': 1, 'mentionedAttachments': []})
        evidence = {'sourceId': state['sources'][-1]['id'], 'pageNumbers': [1],
                    'status': '已认可', 'scopeChecked': True, 'scopeComplete': True,
                    'note': '审批原件已核对'}
    edits = [{'rowId': rid, 'field': '职级', 'value': 'P2-1'}] if kind in {'edit', 'approval_edit'} else []
    options = {}
    if kind in {'approval_decision', 'manual_decision'}:
        options['decisions'] = [{'rowId': rid, 'kind': 'recruitment', 'action': 'exclude'}]
    if kind == 'manual_decision':
        options['basis_type'] = 'manual'
    if kind == 'arrangement':
        options['arrangements'] = [{'rowId': rid, 'recipientId': 'zt12345',
                                    'recipientName': '领取人', 'amount': -10, 'currency': '欧元'}]
    if kind == 'review_only':
        options['approval_reviews'] = [evidence]
        evidence = None
    preview = reviews.prepare_preview(store, 202607, state['revision'], edits,
                                      evidence=evidence, **options)
    original = deepcopy(state)
    legacy_root = tmp_path / 'previous'
    shutil.copytree(store.root, legacy_root)
    legacy = DraftStore(legacy_root)
    prepare_change = legacy._prepare_change
    monkeypatch.setattr(legacy, '_prepare_change',
                        lambda *args, **kwargs: prepare_change(*args, **{**kwargs, 'validate_only': False}))
    rebuild = store._rebuild
    rebuilds = []

    def assemble(*args, **kwargs):
        rebuilds.append(True)
        return rebuild(*args, **kwargs)

    monkeypatch.setattr(store, '_rebuild', assemble)
    saved = reviews.apply_preview(store, 202607, state['revision'], preview['id'])
    assert len(rebuilds) == 1
    previous = reviews.apply_preview(legacy, 202607, state['revision'], preview['id'])
    assert comparable(saved) == comparable(previous)
    assert saved['revision'] == original['revision'] + 1
    assert len(saved['operations']) == len(original.get('operations', [])) + 1
    assert reviews.apply_preview(store, 202607, original['revision'], preview['id']) == saved
    for action in ('undo', 'redo'):
        saved = store.history_action(202607, saved['revision'], action)
        previous = legacy.history_action(202607, previous['revision'], action)
        assert comparable(saved) == comparable(previous)
        if action == 'undo':
            assert saved['rows'][0]['values'] == original['rows'][0]['values']
            assert saved['rows'][0]['calculation'] == original['rows'][0]['calculation']
    assert comparable(DraftStore(store.root).read(202607)) == comparable(saved)
