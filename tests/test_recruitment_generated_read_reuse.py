from unittest.mock import patch

from bonus_platform.engine import recruitment_drafts as drafts
from bonus_platform.engine import recruitment_reference_facts as facts
from bonus_platform.engine import recruitment_employment as employment
from bonus_platform.engine import recruitment_reviews as reviews
from test_recruitment_drafts import book
from test_recruitment_reference_facts import fixture, adopt, selections


def employment_fixture(tmp_path):
    store = drafts.DraftStore(tmp_path)
    state = store.ingest(202611, [('任职.xlsx', book(
        ['姓名', '工号', '入职日期', '最后工作日', '招聘渠道'],
        [['甲', 'zt1', '2024-02-01', '2026-09-03', '招聘网站'],
         ['甲', 'zt1', '2026-11-18', '', '二次入职']], '附件一-招聘奖金核算明细'))], 0)
    current = next(r for r in state['rows'] if r['values']['入职日期'] == '2026-11-18')
    choice = {'rowId': current['id'], 'relation': 'new_hire',
              'signature': employment.employment_review(state, current['id'])['selection']['signature']}
    preview = reviews.prepare_preview(store, 202611, state['revision'], [], employment_selections=[choice])
    return store, reviews.apply_preview(store, 202611, state['revision'], preview['id']), current['id']


def test_unchanged_adoption_revalidates_proofs_without_reassembly(tmp_path):
    store, state, _ = fixture(tmp_path)
    saved = adopt(store, state)
    path = store._folder(202607) / 'draft.json'
    before = path.read_bytes()
    with patch.object(drafts, 'assemble', wraps=drafts.assemble) as assemble, \
            patch.object(facts, '_catalog', wraps=facts._catalog) as catalog, \
            patch.object(store, '_write', wraps=store._write) as write:
        first = store.read(202607)
        second = store.read('202607')
    assert assemble.call_count == 0
    assert catalog.call_count == 2
    assert write.call_count == 0
    assert first['rows'] == second['rows'] == saved['rows']
    assert first['calculation'] == second['calculation'] == saved['calculation']
    assert all(p['status'] == 'adopted' for p in second['referenceFacts']['byRowId'][saved['rows'][0]['id']])
    assert path.read_bytes() == before


def test_inactive_generated_audit_does_not_trigger_reassembly(tmp_path):
    store, state, _ = fixture(tmp_path)
    saved = adopt(store, state)
    undone = store.history_action(202607, saved['revision'], 'undo')
    assert any(e.get('referenceFact') and not e['active'] for e in undone['edits'])
    with patch.object(drafts, 'assemble', wraps=drafts.assemble) as assemble:
        current = store.read(202607)
    assert assemble.call_count == 0
    assert current['rows'] == undone['rows']
    assert not current['rows'][0]['values'].get('ABC类别')


def test_unchanged_employment_adoption_rechecks_basis_without_reassembly(tmp_path):
    store, saved, rid = employment_fixture(tmp_path)
    with patch.object(drafts, 'assemble', wraps=drafts.assemble) as assemble, \
            patch.object(employment, 'valid_employment_edit', wraps=employment.valid_employment_edit) as validate:
        current = store.read(202611)
    assert assemble.call_count == 0
    assert validate.call_count == 3
    assert current['rows'] == saved['rows']
    assert next(r for r in current['rows'] if r['id'] == rid)['values']['上次离职日期'] == '2026-09-03'


def test_invalid_reference_proof_falls_back_to_rebuild(tmp_path):
    store, state, _ = fixture(tmp_path)
    saved = adopt(store, state)
    edit = next(e for e in saved['edits'] if e['field'] == 'ABC类别')
    edit['referenceFact']['signature'] = 'counterfeit'
    store._write(store._folder(202607) / 'draft.json', saved)
    with patch.object(store, '_rebuild', wraps=store._rebuild) as rebuild:
        current = store.read(202607)
    assert rebuild.call_count == 1
    assert not current['rows'][0]['values'].get('ABC类别')
    assert any(e['field'] == 'ABC类别' for e in current['referenceFacts']['staleEdits'])


def test_adopted_rows_from_old_assembly_are_rebuilt(tmp_path):
    store, state, _ = fixture(tmp_path)
    saved = adopt(store, state)
    saved['assemblyVersion'] = drafts.ASSEMBLY_VERSION - 1
    store._write(store._folder(202607) / 'draft.json', saved)
    with patch.object(store, '_rebuild', wraps=store._rebuild) as rebuild:
        current = store.read(202607)
    assert rebuild.call_count == 1
    assert current['assemblyVersion'] == drafts.ASSEMBLY_VERSION
    assert current['rows'][0]['values']['ABC类别'] == 'B'


def test_retained_fact_must_remain_current_on_reuse(tmp_path):
    store, state, rid = fixture(tmp_path, origin={'招聘负责人工号': 'zt56789'})
    retained = [{'rowId': rid, 'field': '招聘负责人工号', 'value': 'zt56789'}]
    generated = facts.selection_edits(store._folder(202607), state, selections(store, state), retained_edits=retained)
    with store._lock(202607) as folder:
        prepared = store._prepare_change(folder, state, {'edits': retained + generated}, trusted_edits=True)
        saved = store._save(folder, store._rebuild(folder, prepared))
    with patch.object(drafts, 'assemble', wraps=drafts.assemble) as assemble:
        current = store.read(202607)
    assert assemble.call_count == 0
    assert current['rows'][0]['values']['招聘负责人姓名'] == '负责人甲'
    changed = store.change(202607, saved['revision'], {'edits': [dict(retained[0], value='zt00000')]})
    with patch.object(store, '_rebuild', wraps=store._rebuild) as rebuild:
        current = store.read(202607)
    assert rebuild.call_count == 1
    assert current['rows'][0]['values']['招聘负责人工号'] == 'zt00000'
    assert not current['rows'][0]['values'].get('招聘负责人姓名')
    assert current['referenceFacts']['staleEdits']
    assert current['revision'] == changed['revision']


def test_manual_identity_change_invalidates_reused_reference(tmp_path):
    store, state, rid = fixture(tmp_path)
    saved = adopt(store, state)
    changed = store.change(202607, saved['revision'], {'edits': [{'rowId': rid, 'field': '工号', 'value': 'zt00000'}]})
    with patch.object(store, '_rebuild', wraps=store._rebuild) as rebuild:
        current = store.read(202607)
    assert rebuild.call_count == 1
    assert current['rows'][0]['values']['工号'] == 'zt00000'
    assert not current['rows'][0]['values'].get('ABC类别')
    assert current['referenceFacts']['staleEdits']
    assert current['revision'] == changed['revision']


def test_manual_prior_exit_change_invalidates_reused_employment(tmp_path):
    store, saved, rid = employment_fixture(tmp_path)
    prior = next(r for r in saved['rows'] if r['values']['入职日期'] == '2024-02-01')
    changed = store.change(202611, saved['revision'], {'edits': [{'rowId': prior['id'], 'field': '最后工作日', 'value': '2026-09-04'}]})
    with patch.object(store, '_rebuild', wraps=store._rebuild) as rebuild:
        current = store.read(202611)
    assert rebuild.call_count == 1
    assert not next(r for r in current['rows'] if r['id'] == rid)['values'].get('上次离职日期')
    assert current['referenceFacts']['staleEdits']
    assert current['revision'] == changed['revision']
