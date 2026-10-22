import hashlib
import json
from uuid import uuid4

import pytest

from bonus_platform.engine import recruitment_reference_facts as facts
from bonus_platform.engine import recruitment_review_center as center
from bonus_platform.engine import recruitment_reviews as reviews
from test_recruitment_drafts import book
from test_recruitment_reference_facts import fixture, adopt, selections


def replace_channel(path, state, channel):
    values = {**state['rows'][0]['values'], 'ABC类别': 'B', '招聘渠道': channel}
    values = {k: v for k, v in values.items() if isinstance(v, (str, int, float))}
    path.write_bytes(book(list(values), [list(values.values())], '附件一-招聘奖金核算明细'))


@pytest.mark.parametrize('adopted', [False, True])
def test_changed_comparison_refreshes_projection_and_rejects_old_confirmation(tmp_path, adopted):
    store, state, rid = fixture(tmp_path, origin={'ABC类别': 'B', '招聘渠道': '招聘网站',
        '招聘启动日期': '2026-05-20', '招聘负责人姓名': '负责人甲', '招聘负责人工号': 'zt56789'})
    if adopted:
        state = adopt(store, state)
    source = state['sources'][-1]
    folder = store._folder(202607)
    raw = folder / 'sources' / source['storedName']
    cached = folder / 'parsed' / (source['id'] + '.json')
    preview = reviews.prepare_preview(store, 202607, state['revision'], [], reference_selections=selections(store, state))
    queue = center.project(store, state, source['id'])
    difference = queue['differences'][0]
    payload = {'revision': state['revision'], 'token': uuid4().hex, 'sourceId': source['id'],
               'differenceId': difference['id'], 'fingerprint': difference['fingerprint'],
               'outcome': 'retain', 'basisType': 'manual', 'confirmed': True}
    snapshot = (folder / 'draft.json').read_bytes()
    replace_channel(raw, state, '猎头')
    current = store.read(202607)
    parsed = json.loads(cached.read_text())
    assert parsed['records'][0]['values']['招聘渠道'] == '猎头'
    assert parsed['contentDigest'] == hashlib.sha256(raw.read_bytes()).hexdigest()
    assert current['sources'][-1]['parsedContentDigest'] == parsed['contentDigest']
    projected = center.project(store, current, source['id'])
    assert projected['differences'] != queue['differences']
    with pytest.raises(ValueError):
        center.save_review(store, 202607, payload)
    with pytest.raises(ValueError):
        reviews.apply_preview(store, 202607, state['revision'], preview['id'])
    assert current['revision'] == state['revision']
    assert (folder / 'draft.json').read_bytes() == snapshot


def test_missing_original_blocks_adopted_facts_and_restores_without_losing_audit(tmp_path):
    store, state, rid = fixture(tmp_path)
    saved = adopt(store, state)
    source = saved['sources'][0]
    folder = store._folder(202607)
    path = folder / 'sources' / source['storedName']
    original = path.read_bytes()
    snapshot = (folder / 'draft.json').read_bytes()
    path.unlink()
    current = store.read(202607)
    row = next(r for r in current['rows'] if r['id'] == rid)
    assert not row['values'].get('ABC类别')
    assert row['rule']['version'] == 'unresolved'
    assert current['referenceFacts']['staleEdits']
    assert facts.proposals(folder, current) == []
    assert current['edits'] == saved['edits']
    assert current['operations'] == saved['operations']
    assert current['sources'][0]['error']
    assert (folder / 'draft.json').read_bytes() == snapshot
    path.write_bytes(original)
    restored = store.read(202607)
    assert restored['rows'][0]['values']['ABC类别'] == 'B'
    assert not restored['referenceFacts']['staleEdits']
    assert not restored['sources'][0].get('error')


def test_first_read_missing_legacy_original_is_not_treated_as_synthetic(tmp_path):
    store, state, rid = fixture(tmp_path)
    source = state['sources'][0]
    folder = store._folder(202607)
    (folder / 'sources' / source['storedName']).unlink()
    source.pop('contentDigest', None)
    source.pop('parsedContentDigest', None)
    cached = folder / 'parsed' / (source['id'] + '.json')
    parsed = json.loads(cached.read_text())
    parsed.pop('contentDigest', None)
    store._write(cached, parsed)
    store._write(folder / 'draft.json', state)
    current = store.read(202607)
    assert current['sources'][0].get('error')
    assert current['rows'][0]['rule']['version'] == 'unresolved'
    assert facts.proposals(folder, current) == []


def test_missing_comparison_cannot_save_cached_differences(tmp_path):
    store, state, rid = fixture(tmp_path)
    state = adopt(store, state)
    source = state['sources'][-1]
    difference = center.project(store, state, source['id'])['differences'][0]
    (store._folder(202607) / 'sources' / source['storedName']).unlink()
    current = store.read(202607)
    assert current['sources'][-1].get('error')
    with pytest.raises(ValueError):
        center.project(store, current, source['id'])
    with pytest.raises(ValueError):
        center.save_review(store, 202607, {'revision': state['revision'], 'token': uuid4().hex,
            'sourceId': source['id'], 'differenceId': difference['id'], 'fingerprint': difference['fingerprint'],
            'outcome': 'retain', 'basisType': 'manual', 'confirmed': True})


@pytest.mark.parametrize('change', ['changed', 'missing'])
def test_real_employment_original_invalidates_generated_relation(tmp_path, change):
    from bonus_platform.engine.recruitment_drafts import DraftStore
    from bonus_platform.engine.recruitment_employment import employment_review
    store = DraftStore(tmp_path)
    headers = ['姓名', '工号', '入职日期', '最后工作日', '招聘渠道']
    rows = [['甲', 'zt1', '2024-02-01', '2026-09-03', '招聘网站'],
            ['甲', 'zt1', '2026-11-18', '', '二次入职']]
    content = book(headers, rows, '附件一-招聘奖金核算明细')
    state = store.ingest(202611, [('任职.xlsx', content)], 0)
    current = next(r for r in state['rows'] if r['values']['入职日期'] == '2026-11-18')
    rid = current['id']
    choice = {'rowId': rid, 'relation': 'new_hire',
              'signature': employment_review(state, rid)['selection']['signature']}
    preview = reviews.prepare_preview(store, 202611, state['revision'], [], employment_selections=[choice])
    saved = reviews.apply_preview(store, 202611, state['revision'], preview['id'])
    assert next(r for r in saved['rows'] if r['id'] == rid)['values']['上次离职日期'] == '2026-09-03'
    path = store._folder(202611) / 'sources' / saved['sources'][0]['storedName']
    if change == 'missing':
        path.unlink()
    else:
        rows[0][3] = '2026-09-04'
        path.write_bytes(book(headers, rows, '附件一-招聘奖金核算明细'))
    updated = store.read(202611)
    row = next(r for r in updated['rows'] if r['id'] == rid)
    assert not row['values'].get('上次离职日期')
    assert not row['values'].get('任职说明')
    assert updated['referenceFacts']['staleEdits']
    assert updated['edits'] == saved['edits']
    if change == 'changed':
        assert employment_review(updated, rid)['priorExit']['value'] == '2026-09-04'
    else:
        assert employment_review(updated, rid)['priorExit'] is None
        assert row['rule']['version'] == 'unresolved'
    path.write_bytes(content)
    restored = store.read(202611)
    assert next(r for r in restored['rows'] if r['id'] == rid)['values']['上次离职日期'] == '2026-09-03'


def test_corrupt_original_blocks_cache_then_restores_after_saved_error(tmp_path):
    store, state, rid = fixture(tmp_path)
    source = state['sources'][-1]
    path = store._folder(202607) / 'sources' / source['storedName']
    original = path.read_bytes()
    path.write_bytes(b'broken workbook')
    blocked = store.read(202607)
    assert blocked['sources'][-1]['sourceCacheError']
    assert facts.proposals(store._folder(202607), blocked) == []
    saved = store.change(202607, state['revision'], {'edits': [{'rowId': rid, 'field': '人工备注', 'value': '保留审计'}]})
    path.write_bytes(original)
    restored = store.read(202607)
    assert restored['revision'] == saved['revision']
    assert not restored['sources'][-1].get('error')
    assert facts.proposals(store._folder(202607), restored)
    assert restored['rows'][0]['values']['人工备注'] == '保留审计'


def test_legacy_unbound_cache_is_reparsed_before_becoming_current(tmp_path):
    store, state, rid = fixture(tmp_path)
    source = state['sources'][-1]
    folder = store._folder(202607)
    path = folder / 'parsed' / (source['id'] + '.json')
    parsed = json.loads(path.read_text())
    parsed.pop('contentDigest', None)
    parsed['records'][0]['values']['招聘渠道'] = '过时缓存'
    source.pop('parsedContentDigest', None)
    store._write(path, parsed)
    store._write(folder / 'draft.json', state)
    current = store.read(202607)
    assert json.loads(path.read_text())['records'][0]['values']['招聘渠道'] == '招聘网站'
    assert current['sources'][-1]['parsedContentDigest'] == current['sources'][-1]['contentDigest']


def test_raw_original_change_without_generated_edits_updates_current_facts(tmp_path):
    store, state, rid = fixture(tmp_path)
    path = store._folder(202607) / 'sources' / state['sources'][0]['storedName']
    values = {**state['rows'][0]['original'], '招聘渠道': '猎头'}
    values = {k: v for k, v in values.items() if isinstance(v, (str, int, float))}
    path.write_bytes(book(list(values), [list(values.values())]))
    current = store.read(202607)
    assert current['rows'][0]['values']['招聘渠道'] == '猎头'
    assert current['revision'] == state['revision']
    assert not current['edits']


def test_changed_hire_date_keeps_old_row_for_audit_without_old_adopted_identity(tmp_path):
    store, state, rid = fixture(tmp_path)
    saved = adopt(store, state)
    folder = store._folder(202607)
    path = folder / 'sources' / state['sources'][0]['storedName']
    values = {**state['rows'][0]['original'], '入职日期': '2026-06-17', '候选人入职时间': '2026-06-17'}
    values = {k: v for k, v in values.items() if isinstance(v, (str, int, float))}
    path.write_bytes(book(list(values), [list(values.values())]))
    current = store.read(202607)
    old = next(r for r in current['rows'] if r['id'] == rid)
    assert not old['values'].get('ABC类别')
    assert old['identityConflict'] and old['rule']['version'] == 'unresolved'
    assert current['referenceFacts']['staleEdits']
    assert all(p['rowId'] != rid for p in facts.proposals(folder, current))
    assert current['edits'] == saved['edits']
    assert any(r['values']['入职日期'] == '2026-06-17' for r in current['rows'])
