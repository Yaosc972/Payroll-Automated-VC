from copy import deepcopy

import pytest

from bonus_platform.engine import recruitment_work_items as work
from bonus_platform.engine.recruitment_actions import task_fields
from bonus_platform.engine.recruitment_employment import employment_review, employment_edits, valid_employment_edit
from test_recruitment_attention import state_for
from test_recruitment_awards import person


def employment_state():
    old = person(hire='2024-02-01', 最后工作日='2026-09-03')
    old['id'] = 'old'
    current = person(hire='2026-11-18', 招聘渠道='二次入职')
    current['id'] = 'current'
    for row in (old, current):
        row.update(original=deepcopy(row['values']), edits=[], sources=[], originKinds=['ledger'])
        row['provenance'] = {f: [{'sourceId': 'ledger', 'sheet': '人员', 'row': 2 if row is old else 3, 'value': row['values'][f]}]
                             for f in ('工号', '入职日期', '最后工作日') if f in row['values']}
    current['employmentCandidates'] = [{'rowId': 'old', 'hireDate': '2024-02-01', 'source': old['provenance']['入职日期'][0]}]
    state = state_for([old, current], [], 202611)
    state['sources'] = [{'id': 'ledger', 'name': '任职.xlsx', 'active': True, 'parserVersion': 15, 'contentDigest': 'original'}]
    return state


def selected(state, relation='new_hire'):
    review = employment_review(state, 'current')
    return {'rowId': 'current', 'relation': relation, 'signature': review['selection']['signature']}


def test_relation_choice_carries_the_real_previous_exit_without_changing_current_last_day():
    state = employment_state()
    before = deepcopy(state)
    edits = employment_edits(state, [selected(state)])
    assert {e['field']: e['value'] for e in edits} == {
        '任职说明': '二次入职：已核对本次为独立招聘任职', '核算范围': '纳入核算', '上次离职日期': '2026-09-03'}
    assert all(e['employmentBasis']['sources'] for e in edits)
    assert all(valid_employment_edit(state, e) for e in edits)
    assert state == before
    state['edits'] = [{**e, 'active': True} for e in edits]
    assert all(valid_employment_edit(state, e) for e in edits)
    assert not any(e['field'] == '最后工作日' for e in edits)


def test_prior_source_change_and_manual_old_exit_change_invalidate_the_whole_relation():
    state = employment_state()
    edits = employment_edits(state, [selected(state)])
    state['sources'][0]['contentDigest'] = 'replaced'
    assert not any(valid_employment_edit(state, e) for e in edits)
    with pytest.raises(ValueError):
        employment_edits(state, [edits[0]['employmentBasis']])
    state['sources'][0]['contentDigest'] = 'original'
    state['edits'] = [{'rowId': 'old', 'field': '最后工作日', 'value': '2026-09-04', 'active': True}]
    state['rows'][0]['edits'] = deepcopy(state['edits'])
    state['rows'][0]['values']['最后工作日'] = '2026-09-04'
    assert not any(valid_employment_edit(state, e) for e in edits)
    state['edits'] = []
    state['sources'][0]['active'] = False
    assert not any(valid_employment_edit(state, e) for e in edits)
    state['sources'][0]['active'] = True
    state['sources'][0]['contentDigest'] = ''
    assert employment_review(state, 'current')['priorExit'] is None
    assert not any(valid_employment_edit(state, e) for e in edits)


def test_continuation_only_links_and_excludes_the_new_segment():
    state = employment_state()
    edits = employment_edits(state, [selected(state, 'continuation')])
    assert {e['field']: e['value'] for e in edits} == {
        '任职说明': '任职延续：沿用原招聘任职old', '核算范围': '不纳入核算'}
    assert all(e['rowId'] == 'current' for e in edits)


def test_missing_previous_exit_is_never_filled_with_the_current_exit_or_recruitment_start():
    state = employment_state()
    state['rows'][0]['original'].pop('最后工作日')
    state['rows'][0]['values'].pop('最后工作日')
    state['rows'][1]['original']['最后工作日'] = '2026-11-30'
    state['rows'][1]['values']['最后工作日'] = '2026-11-30'
    review = employment_review(state, 'current')
    assert review['selection']['priorExit'] is None
    edits = employment_edits(state, [selected(state)])
    assert not any(e['field'] == '上次离职日期' for e in edits)
    assert task_fields(state['rows'][1], {'kind': 'rehire'}, 202611) == ['上次离职日期']


def test_nonunique_or_other_person_prior_does_not_supply_an_exit():
    state = employment_state()
    duplicate = deepcopy(state['rows'][0]); duplicate['id'] = 'competing'
    state['rows'].append(duplicate)
    assert employment_review(state, 'current')['priorExit'] is None
    state['rows'].pop()
    state['rows'][0]['original']['工号'] = 'another-person'
    state['rows'][0]['values']['工号'] = 'another-person'
    assert employment_review(state, 'current')['priorExit'] is None


def test_employment_and_rehire_tasks_share_a_single_entry_and_retain_task_counts():
    state = employment_state()
    attention = {'current': [
        {'id': 'relation', 'kind': 'employment', 'title': '核对两次任职', 'rowIds': ['current'], 'sourceIds': ['ledger']},
        {'id': 'interval', 'kind': 'rehire', 'title': '核对离职间隔', 'rowIds': ['current'], 'sourceIds': ['ledger']}], 'history': []}
    items = work.project(state, attention)
    assert len(items) == 1
    item = items[0]
    assert item['key'] == 'employment' and item['actionClass'] == 'resolve_fact'
    assert item['rowIds'] == ['current'] and item['taskIds'] == ['relation', 'interval']
    assert item['taskCount'] == 2 and item['affectedCount'] == 1 and item['sourceCount'] == 1
    assert 'potential_current_unknown' in item['monthImpacts']
    assert not state['rows'][1]['values'].get('上次离职日期')


def test_conditional_rehire_policy_and_reference_action_classes_work_in_other_months():
    state = employment_state()
    row = state['rows'][1]
    row['values']['上次离职日期'] = '2024-01-01'
    assert task_fields(row, {'kind': 'rehire'}, 202611) == []
    row['calculation']['recruitment']['issues'].append('二次入职专项条款执行依据待核')
    assert task_fields(row, {'kind': 'rehire'}, 202611) == ['二次入职执行口径']
    item = {'mode': 'intake', 'key': 'intake:海外', 'rowIds': ['current'], 'ruleMaintenance': False}
    assert work.action_class(state, item) == 'missing_fact'
    state['referenceFacts'] = {'contractVersion': 1, 'byRowId': {'current': [{'fields': ['招聘渠道'], 'canAdopt': True, 'status': 'available'}]}}
    assert work.action_class(state, item) == 'missing_fact'
    row['values']['招聘启动日期'] = ''
    state['referenceFacts']['byRowId']['current'][0]['fields'] = ['招聘启动日期']
    assert work.action_class(state, item) == 'review_available'
    assert work.action_class(state, {**item, 'mode': 'settlement'}) == 'review_history'
    assert work.action_class(state, {**item, 'ruleMaintenance': True}) == 'policy'


def test_month_impacts_keep_scheduled_future_historical_and_unknown_separate():
    state = employment_state()
    row = state['rows'][1]
    award = row['calculation']['recruitment']
    award['nodes'] = [{'scheduledMonth': 202611, 'amount': 10}, {'dueMonth': 202701, 'amount': 20}]
    row['calculation']['referral']['nodes'] = []
    item = {'mode': 'facts', 'current': True, 'rowIds': ['current']}
    assert work.month_impacts(state, item) == ['scheduled_current', 'future']
    award['nodes'] = []
    assert work.month_impacts(state, item) == ['potential_current_unknown']
    assert work.month_impacts(state, {**item, 'mode': 'settlement'}) == ['historical']
    assert work.month_impacts(state, {**item, 'current': False}) == ['future']


def test_relation_preview_apply_undo_and_source_change_use_existing_operation(tmp_path):
    from bonus_platform.engine.recruitment_drafts import DraftStore
    from bonus_platform.engine.recruitment_reviews import prepare_preview, apply_preview
    from test_recruitment_drafts import book
    store = DraftStore(tmp_path)
    state = store.ingest(202611, [('人员任职.xlsx', book(
        ['姓名', '工号', '入职日期', '最后工作日', '招聘渠道'],
        [['甲', 'zt1', '2024-02-01', '2026-09-03', '招聘网站'],
         ['甲', 'zt1', '2026-11-18', '', '二次入职']], title='附件一-招聘奖金核算明细'))], 0)
    current = next(r for r in state['rows'] if r['values']['入职日期'] == '2026-11-18')
    rid = current['id']
    review = employment_review(state, rid)
    choice = {'rowId': rid, 'relation': 'new_hire', 'signature': review['selection']['signature']}
    preview = prepare_preview(store, 202611, state['revision'], [], employment_selections=[choice])
    assert any(c['field'] == '上次离职日期' and c['after'] == '2026-09-03' for c in preview['changes'])
    updated = apply_preview(store, 202611, state['revision'], preview['id'])
    assert len(updated['operations']) == 1
    assert next(r for r in store.read(202611)['rows'] if r['id'] == rid)['values']['上次离职日期'] == '2026-09-03'
    undone = store.history_action(202611, updated['revision'], 'undo')
    assert not next(r for r in undone['rows'] if r['id'] == rid)['values'].get('上次离职日期')
    redone = store.history_action(202611, undone['revision'], 'redo')
    assert next(r for r in redone['rows'] if r['id'] == rid)['values']['上次离职日期'] == '2026-09-03'
    source = store._folder(202611) / 'sources' / redone['sources'][0]['storedName']
    original_bytes = source.read_bytes()
    source.unlink()
    missing = store.read(202611)
    assert employment_review(missing, rid)['priorExit'] is None
    assert not next(r for r in missing['rows'] if r['id'] == rid)['values'].get('上次离职日期')
    source.write_bytes(original_bytes + b'changed')
    stale = store.read(202611)
    assert not next(r for r in stale['rows'] if r['id'] == rid)['values'].get('上次离职日期')
    assert any(e['field'] == '上次离职日期' for e in stale['referenceFacts']['staleEdits'])


@pytest.mark.parametrize('previous_exit', ['2026-09-03', '2026-09-04'])
def test_same_preview_corrects_hire_date_and_selects_relation_once(tmp_path, previous_exit):
    from bonus_platform.engine.recruitment_drafts import DraftStore
    from bonus_platform.engine.recruitment_reviews import prepare_preview, apply_preview
    from test_recruitment_drafts import book
    store = DraftStore(tmp_path)
    state = store.ingest(202611, [('人员任职.xlsx', book(
        ['姓名', '工号', '入职日期', '最后工作日', '招聘渠道'],
        [['甲', 'zt1', '2024-02-01', '2026-09-03', '招聘网站'],
         ['甲', 'zt1', '2026-11-18', '', '二次入职']], title='附件一-招聘奖金核算明细'))], 0)
    current = next(r for r in state['rows'] if r['values']['入职日期'] == '2026-11-18')
    rid = current['id']
    choice = {'rowId': rid, 'relation': 'new_hire', 'signature': employment_review(state, rid)['selection']['signature']}
    edits = [{'rowId': rid, 'field': '入职日期', 'value': '2026-11-19'}]
    if previous_exit != '2026-09-03':
        old = next(r for r in state['rows'] if r['values']['入职日期'] == '2024-02-01')
        edits.append({'rowId': old['id'], 'field': '最后工作日', 'value': previous_exit})
    preview = prepare_preview(store, 202611, state['revision'], edits, employment_selections=[choice])
    assert {(c['field'], c['after']) for c in preview['changes']} >= {
        ('入职日期', '2026-11-19'), ('上次离职日期', previous_exit)}
    saved = apply_preview(store, 202611, state['revision'], preview['id'])
    actual = next(r for r in store.read(202611)['rows'] if r['id'] == rid)
    assert actual['values']['入职日期'] == '2026-11-19'
    assert actual['values']['上次离职日期'] == previous_exit
    assert len(saved['operations']) == 1
    assert not saved['referenceFacts']['staleEdits']
    undone = store.history_action(202611, saved['revision'], 'undo')
    previous = next(r for r in undone['rows'] if r['id'] == rid)
    assert previous['values']['入职日期'] == '2026-11-18'
    assert not previous['values'].get('上次离职日期')
    redone = store.history_action(202611, undone['revision'], 'redo')
    assert next(r for r in redone['rows'] if r['id'] == rid)['values']['上次离职日期'] == previous_exit


def test_prospective_relation_keeps_stale_source_identity_and_prior_guards():
    state = employment_state()
    choice = selected(state)
    proposed = [{'rowId': 'current', 'field': '入职日期', 'value': '2026-11-19'}]
    state['sources'][0]['contentDigest'] = 'changed'
    with pytest.raises(ValueError):
        employment_edits(state, [choice], proposed_edits=proposed)
    state['sources'][0]['contentDigest'] = 'original'
    with pytest.raises(ValueError):
        employment_edits(state, [{**choice, 'lastWorkDate': '2026-09-03'}], proposed_edits=proposed)
    with pytest.raises(ValueError):
        employment_edits(state, [choice], proposed_edits=[{'rowId': 'current', 'field': '工号', 'value': 'other'}])
    with pytest.raises(ValueError):
        employment_edits(state, [choice], proposed_edits=[{'rowId': 'current', 'field': '入职日期', 'value': '2023-01-01'}])
    with pytest.raises(ValueError):
        employment_edits(state, [choice], proposed_edits=[
            {'rowId': rid, 'field': '工号', 'value': 'another-person'} for rid in ('old', 'current')])


def enriched_employment_state(dates=('2026-09-03',), competing_identity=False):
    from bonus_platform.engine.recruitment_employment import enrich
    from test_recruitment_flow import history
    state = employment_state()
    old = state['rows'][0]
    old['original'].pop('最后工作日')
    old['values'].pop('最后工作日')
    old['provenance'].pop('最后工作日')
    old['conflicts'] = []
    facts = []
    for i, value in enumerate(dates):
        fact = history(lastWorkDate=value)
        fact.update(entryDate='2024-02-01', lUOffer='previous', userID=2 if competing_identity and i else 1)
        facts.append(fact)
    state['sources'].append({'id': 'api', 'active': True, 'parserVersion': 15, 'contentDigest': 'approved-history'})
    enrich(old, {old['values']['工号']: facts}, [])
    return state


def test_actual_enrich_previous_exit_is_available_to_the_original_relation_selection():
    state = enriched_employment_state()
    old = state['rows'][0]
    assert '最后工作日' not in old['original']
    assert old['values']['最后工作日'] == '2026-09-03'
    assert old['provenance']['最后工作日'][0]['role'] == 'employment_history'
    review = employment_review(state, 'current')
    assert review['priorExit']['value'] == '2026-09-03'
    assert review['priorExit']['sources'][0]['sourceId'] == 'api'
    edits = employment_edits(state, [selected(state)])
    assert any(e['field'] == '上次离职日期' and e['value'] == '2026-09-03' for e in edits)
    assert all(valid_employment_edit(state, e) for e in edits)


@pytest.mark.parametrize('change', [{'active': False}, {'error': 'missing'}, {'contentDigest': ''}, None])
def test_invalid_or_missing_hr_source_cannot_supply_a_previous_exit(change):
    state = enriched_employment_state()
    edits = employment_edits(state, [selected(state)])
    if change is None:
        state['sources'].pop()
    else:
        state['sources'][-1].update(change)
    assert employment_review(state, 'current')['priorExit'] is None
    assert not any(e['field'] == '上次离职日期' for e in employment_edits(state, [selected(state)]))
    assert not any(valid_employment_edit(state, e) for e in edits)


def test_effective_manual_clear_wins_over_enrichment_and_stale_audit_values():
    from bonus_platform.engine.recruitment_employment import enrich
    state = enriched_employment_state()
    old = state['rows'][0]
    old['values']['最后工作日'] = ''
    old['edits'] = [{'rowId': 'old', 'field': '最后工作日', 'value': '', 'active': True}]
    state['edits'] = [{'rowId': 'old', 'field': '最后工作日', 'value': '2026-09-07',
                       'active': True, 'referenceFact': {'stale': True}}]
    enrich(old, {old['values']['工号']: old['employmentTimelines']['']}, [])
    assert old['values']['最后工作日'] == ''
    assert employment_review(state, 'current')['priorExit'] is None
    assert not any(e['field'] == '上次离职日期' for e in employment_edits(state, [selected(state)]))


@pytest.mark.parametrize('competing_identity', [False, True])
def test_ambiguous_approved_hr_facts_do_not_generate_a_previous_exit(competing_identity):
    state = enriched_employment_state(('2026-09-03', '2026-09-04'), competing_identity)
    assert not state['rows'][0]['values'].get('最后工作日')
    assert employment_review(state, 'current')['priorExit'] is None
    assert not any(e['field'] == '上次离职日期' for e in employment_edits(state, [selected(state)]))


def test_replaced_hr_content_invalidates_the_generated_relation_basis():
    state = enriched_employment_state()
    edits = employment_edits(state, [selected(state)])
    state['sources'][-1]['contentDigest'] = 'replaced-history'
    assert not any(valid_employment_edit(state, e) for e in edits)


def test_positive_original_and_conflicting_hr_exit_still_require_resolution():
    from bonus_platform.engine.recruitment_employment import enrich
    from test_recruitment_flow import history
    state = employment_state()
    old = state['rows'][0]
    old['conflicts'] = []
    state['sources'].append({'id': 'api', 'active': True, 'contentDigest': 'approved-history'})
    fact = history(lastWorkDate='2026-09-04')
    fact.update(entryDate='2024-02-01', lUOffer='previous')
    enrich(old, {old['values']['工号']: [fact]}, [])
    assert old['values']['最后工作日'] == '2026-09-03'
    assert any(c['field'] == '最后工作日' for c in old['conflicts'])
    assert employment_review(state, 'current')['priorExit'] is None


@pytest.mark.parametrize('missing', [False, True])
def test_same_batch_date_preview_rechecks_source_before_saving(tmp_path, missing):
    from bonus_platform.engine.recruitment_drafts import DraftStore
    from bonus_platform.engine.recruitment_reviews import prepare_preview, apply_preview
    from test_recruitment_drafts import book
    store = DraftStore(tmp_path)
    state = store.ingest(202611, [('任职.xlsx', book(
        ['姓名', '工号', '入职日期', '最后工作日', '招聘渠道'],
        [['甲', 'zt1', '2024-02-01', '2026-09-03', '招聘网站'],
         ['甲', 'zt1', '2026-11-18', '', '二次入职']], title='附件一-招聘奖金核算明细'))], 0)
    current = next(r for r in state['rows'] if r['values']['入职日期'] == '2026-11-18')
    rid = current['id']
    choice = {'rowId': rid, 'relation': 'new_hire', 'signature': employment_review(state, rid)['selection']['signature']}
    preview = prepare_preview(store, 202611, state['revision'], [
        {'rowId': rid, 'field': '入职日期', 'value': '2026-11-19'}], employment_selections=[choice])
    source = store._folder(202611) / 'sources' / state['sources'][0]['storedName']
    if missing:
        source.unlink()
    else:
        source.write_bytes(source.read_bytes() + b'replaced')
    with pytest.raises(ValueError):
        apply_preview(store, 202611, state['revision'], preview['id'])
    actual = store.read(202611)
    assert not actual.get('operations')
    assert next(r for r in actual['rows'] if r['id'] == rid)['values']['入职日期'] == '2026-11-18'
