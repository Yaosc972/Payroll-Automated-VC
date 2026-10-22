import hashlib
import json
from unittest.mock import patch

import pytest

from bonus_platform.engine.recruitment_draft_sources import PARSER_VERSION
from test_recruitment_drafts import book
from test_recruitment_reference_facts import fixture
from test_recruitment_intake_fixes import _api_payload


@pytest.mark.parametrize('cache_version', [True, False])
def test_bound_legacy_cache_is_reused_without_rebuild_or_writes(tmp_path, cache_version):
    store, state, _ = fixture(tmp_path)
    folder = store._folder(202607)
    for source in state['sources']:
        source.pop('parsedContentDigest', None)
        path = folder / 'parsed' / (source['id'] + '.json')
        parsed = json.loads(path.read_text())
        if cache_version:
            parsed['parserVersion'] = PARSER_VERSION
        else:
            parsed.pop('parserVersion', None)
        store._write(path, parsed)
    store._write(folder / 'draft.json', state)
    paths = [folder / 'draft.json', *sorted((folder / 'parsed').glob('*.json'))]
    before = {path: path.read_bytes() for path in paths}
    with patch.object(store, '_parse_source', wraps=store._parse_source) as parse, \
            patch.object(store, '_rebuild', wraps=store._rebuild) as rebuild, \
            patch.object(store, '_write', wraps=store._write) as write:
        first = store.read(202607)
        second = store.read(202607)
    assert parse.call_count == 0
    assert rebuild.call_count == 0
    assert write.call_count == 0
    assert first['rows'] == second['rows'] == state['rows']
    assert all(s['parsedContentDigest'] == s['contentDigest'] for s in second['sources'])
    assert {path: path.read_bytes() for path in paths} == before


def test_unbound_cache_is_parsed_once_across_unsaved_reads(tmp_path):
    store, state, _ = fixture(tmp_path)
    folder = store._folder(202607)
    source = state['sources'][0]
    source.pop('parsedContentDigest', None)
    path = folder / 'parsed' / (source['id'] + '.json')
    parsed = json.loads(path.read_text())
    parsed.pop('contentDigest', None)
    store._write(path, parsed)
    store._write(folder / 'draft.json', state)
    before = (folder / 'draft.json').read_bytes()
    with patch.object(store, '_parse_source', wraps=store._parse_source) as parse, \
            patch.object(store, '_rebuild', wraps=store._rebuild) as rebuild:
        first = store.read(202607)
        second = store.read(202607)
    assert parse.call_count == 1
    assert rebuild.call_count == 1
    assert first['rows'] == second['rows'] == state['rows']
    assert json.loads(path.read_text())['parserVersion'] == PARSER_VERSION
    assert (folder / 'draft.json').read_bytes() == before


def test_changed_original_reuses_new_cache_but_rebuilds_unsaved_facts(tmp_path):
    store, state, _ = fixture(tmp_path)
    folder = store._folder(202607)
    source = state['sources'][0]
    path = folder / 'sources' / source['storedName']
    values = {**state['rows'][0]['original'], '招聘渠道': '猎头'}
    values = {k: v for k, v in values.items() if isinstance(v, (str, int, float))}
    path.write_bytes(book(list(values), [list(values.values())]))
    before = (folder / 'draft.json').read_bytes()
    with patch.object(store, '_parse_source', wraps=store._parse_source) as parse, \
            patch.object(store, '_rebuild', wraps=store._rebuild) as rebuild:
        first = store.read(202607)
        second = store.read(202607)
    assert parse.call_count == 1
    assert rebuild.call_count == 2
    assert first['rows'][0]['values']['招聘渠道'] == '猎头'
    assert second['rows'][0]['values']['招聘渠道'] == '猎头'
    assert (folder / 'draft.json').read_bytes() == before


@pytest.mark.parametrize('persisted_old_version', [False, True])
def test_parser_upgrade_reuses_only_current_version_cache(tmp_path, persisted_old_version):
    store, state, _ = fixture(tmp_path)
    folder = store._folder(202607)
    source = state['sources'][0]
    source['parserVersion'] = PARSER_VERSION - 1 if persisted_old_version else PARSER_VERSION
    path = folder / 'parsed' / (source['id'] + '.json')
    parsed = json.loads(path.read_text())
    parsed['parserVersion'] = PARSER_VERSION - 1
    parsed['records'][0]['values']['招聘渠道'] = '过时缓存'
    store._write(path, parsed)
    store._write(folder / 'draft.json', state)
    with patch.object(store, '_parse_source', wraps=store._parse_source) as parse, \
            patch.object(store, '_rebuild', wraps=store._rebuild) as rebuild:
        first = store.read(202607)
        second = store.read(202607)
    assert parse.call_count == 1
    assert rebuild.call_count == (2 if persisted_old_version else 1)
    assert first['rows'] == second['rows'] == state['rows']
    assert json.loads(path.read_text())['parserVersion'] == PARSER_VERSION


def test_missing_original_is_blocked_even_when_cache_is_bound(tmp_path):
    store, state, _ = fixture(tmp_path)
    folder = store._folder(202607)
    source = state['sources'][0]
    path = folder / 'sources' / source['storedName']
    assert hashlib.sha256(path.read_bytes()).hexdigest() == source['contentDigest']
    path.unlink()
    with patch.object(store, '_parse_source', wraps=store._parse_source) as parse:
        current = store.read(202607)
    assert parse.call_count == 0
    assert current['sources'][0]['sourceCacheError']
    assert current['rows'][0]['rule']['version'] == 'unresolved'


@pytest.mark.parametrize('cached_metadata', [True, False])
def test_legacy_beisen_metadata_recovers_without_reparsing_bound_responses(tmp_path, cached_metadata):
    from bonus_platform.engine.recruitment_drafts import DraftStore
    store = DraftStore(tmp_path)
    payload = _api_payload('zt1', 'OF1')
    payload['scopeJobNumbers'] = ['zt1', 'zt2']
    state = store.save_beisen_snapshot(202607, 0, payload)
    folder = store._folder(202607)
    source = state['sources'][0]
    source['parserVersion'] = PARSER_VERSION - 1
    source.pop('syncCoverage')
    source['scopeJobNumbers'] = ['zt1', 'zt2']
    store._write(folder / 'draft.json', state)
    cache = folder / 'parsed' / (source['id'] + '.json')
    parsed = json.loads(cache.read_text())
    if not cached_metadata:
        parsed.pop('beisenSourceMetadata', None)
        store._write(cache, parsed)
    before = (folder / 'draft.json').read_bytes()
    original = (folder / 'sources' / source['storedName']).read_bytes()
    with patch.object(store, '_parse_source', wraps=store._parse_source) as parse, \
            patch.object(store, '_write', wraps=store._write) as write:
        first = store.read(202607)
        second = store.read(202607)
    assert parse.call_count == (0 if cached_metadata else 1)
    assert write.call_count == (0 if cached_metadata else 1)
    for current in (first, second):
        recovered = current['sources'][0]
        assert recovered['scopeJobNumbers'] == ['zt1']
        assert recovered['requestedJobNumbers'] == ['zt1', 'zt2']
        assert recovered['syncCoverage']['candidates']['zt2']['employment'] is False
    assert (folder / 'draft.json').read_bytes() == before
    assert (folder / 'sources' / source['storedName']).read_bytes() == original
