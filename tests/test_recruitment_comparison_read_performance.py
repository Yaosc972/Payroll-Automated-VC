"""Read-only comparisons reuse current calculations and isolate stale ones."""
from copy import deepcopy
import json

from bonus_platform.engine import recruitment_reconcile as reconcile
from bonus_platform.engine.recruitment_awards import calculate_draft
from test_recruitment_review_center import fixture


def inputs(store, state):
    source = next(s for s in state['sources'] if s['id'] == 'ledger')
    reference = json.loads((store._folder(state['month']) / 'parsed/ledger.json').read_text())['records']
    return reference, source


def test_current_comparison_does_not_clone_the_complete_draft(tmp_path, monkeypatch):
    store, state = fixture(tmp_path)
    reference, source = inputs(store, state)
    before = deepcopy(state)
    original = reconcile.deepcopy

    def no_bulk_copy(value, *args, **kwargs):
        assert value is not state, 'A current comparison must not copy the complete draft and its parsed caches'
        return original(value, *args, **kwargs)

    monkeypatch.setattr(reconcile, 'deepcopy', no_bulk_copy)
    result = reconcile.monthly_comparison(state, reference, source)
    assert result['comparisonReady']
    assert result['summary']['referenceNodes'] > 0
    assert state == before


def test_stale_comparison_recalculates_an_isolated_copy(tmp_path):
    store, state = fixture(tmp_path)
    reference, source = inputs(store, state)
    state['calculation']['draftRevision'] = -1
    state['rows'][0]['calculation']['recruitment']['total'] = 999999
    before = deepcopy(state)
    expected = reconcile.monthly_comparison(calculate_draft(deepcopy(state)), reference, source)
    result = reconcile.monthly_comparison(state, reference, source)
    assert result == expected
    assert state == before


def test_approval_target_lookup_does_not_renormalize_the_directory(tmp_path, monkeypatch):
    from bonus_platform.engine import recruitment_approval_intake as approvals
    rows = [{'id':str(i),'values':{'姓名':f'Employee {i:04d}','工号':f'zt{i+10000}','入职日期':'2026-07-01'}} for i in range(500)]
    directory = approvals.Directory(tmp_path, {'sources':[], 'rows':rows})
    original = approvals.compact
    normalized = []

    def tracked(value):
        if str(value).startswith('Employee'):
            normalized.append(value)
        return original(value)

    monkeypatch.setattr(approvals, 'compact', tracked)
    for i in (12, 42):
        matches, issue = directory.target(f'候选人 Employee {i:04d}，批准调整招聘渠道。', '申请人')
        assert not issue
        assert [p['rowId'] for p in matches] == [str(i)]
    assert len(normalized) < 20, 'Each approval lookup must reuse normalized directory names'
