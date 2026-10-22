from copy import deepcopy
import json

from bonus_platform.engine import recruitment_review_center as center
from bonus_platform.engine import recruitment_special as special
from bonus_platform.engine.recruitment_awards import calculate_draft
from test_recruitment_august_settlement import save
from test_recruitment_history_comparison_remediation import roster_fixture, review_payload
from test_recruitment_special import fixture


def test_shared_detail_options_do_not_duplicate_reference_choices(tmp_path):
    from bonus_platform.engine.recruitment_reference_facts import enrich_detail
    field = {'field': 'ABC类别', 'targets': ['row'], 'options': []}
    data = {'fields': [field], 'currentFields': [{**field}]}
    proposal = {'id': 'category', 'signature': 'signed', 'status': 'available', 'values': {'ABC类别': 'C'},
        'refs': [{'sourceId': 'ref', 'sourceName': '核对表.xlsx', 'sheet': '明细', 'row': 2, 'cell': 'U2'}]}
    state = {'referenceFacts': {'contractVersion': 1, 'byRowId': {'row': [proposal]}}}
    enrich_detail(tmp_path, state, data)
    enrich_detail(tmp_path, state, data)
    assert len(data['fields'][0]['options']) == 1
    assert len(data['currentFields'][0]['options']) == 1
    assert data['currentFields'][0]['options'][0]['referenceStatus'] == 'available'


def test_closed_unallocated_balance_stays_closed_in_history_dialog(tmp_path, monkeypatch):
    store, state, _ = fixture(tmp_path, monkeypatch)
    row = state['rows'][0]
    state['confirmedInstallments'] = [{
        **{k: node[k] for k in ('role', 'label', 'recipientId', 'recipientName', 'currency')},
        'amount': node['amount'] - (10 if index == 0 else 0), 'originKey': 'old' + str(index),
        'nodeId': node['id'], 'rowId': row['id'], 'kind': 'recruitment',
        'scheduledMonth': 202606, 'confirmedMonth': 202606, 'parentRevision': 1,
        'openingSource': {'sourceId': state['sources'][0]['id']}}
        for index, node in enumerate(row['calculation']['recruitment']['nodes'])]
    calculate_draft(state)
    store._write(store._folder(202607) / 'draft.json', state)
    recovery = next(r for r in row['calculation']['recruitment']['recoveries'] if r['type'] == 'unallocated_balance')
    saved = save(store, state, {'revision': state['revision'], 'type': 'adjustment', 'basisType': 'manual',
        'rowId': row['id'], 'kind': 'recruitment', 'month': 202607, 'amount': recovery['amount'],
        'role': recovery['role'], 'currency': recovery['currency'], 'recipientId': recovery['recipientId'],
        'recipientName': recovery['recipientName'], 'recoveryKey': recovery['key']})
    assert not saved['rows'][0]['calculation']['recruitment']['recoveries']
    context = special.context(saved)
    assert not context['recoveries']
    complete = next(r for r in context['historyRecoveries'] if r['key'] == recovery['key'])
    assert complete['resolution'] == 'adjusted'
    assert complete['relatedRecords']
    undone = store.history_action(202607, saved['revision'], 'undo')
    assert any(r['key'] == recovery['key'] for r in special.context(undone)['recoveries'])


def test_three_months_keep_one_latest_roster_followup_and_full_source_history(tmp_path):
    store, state = roster_fixture(tmp_path)
    first = next(d for d in center.project(store, state)['differences'] if d.get('matchStatus') == 'unmatched')
    center.save_review(store, 202607, review_payload(state, first))
    carried = store.carry_forward(202608, 202607, 0)
    parsed = json.loads((store._folder(202607) / 'parsed/ledger.json').read_text())
    current = {**carried['sources'][-1], 'id': 'new-ledger', 'storedName': 'new.xlsx', 'name': '202608核对表.xlsx'}
    carried['sources'].append(current)
    for record in parsed['records']:
        record['ref']['sourceId'] = current['id']
    store._write(store._folder(202608) / 'parsed/new-ledger.json', parsed)
    store._write(store._folder(202608) / 'draft.json', carried)
    second = next(d for d in center.project(store, carried)['differences'] if d.get('matchStatus') == 'unmatched')
    payload = review_payload(carried, second)
    payload['sourceId'] = current['id']
    saved = center.save_review(store, 202608, payload)
    september = store.carry_forward(202609, 202608, 0)
    matching = [d for d in center.project(store, september)['differences'] if d.get('subject') and d['name'] == first['name']]
    assert len(matching) == 1
    assert matching[0]['sourceId'] == current['id']
    assert not matching[0]['reviewValid']
    assert len([r for r in september['differenceReviews'] if r['name'] == first['name']]) == 2
    undone = store.history_action(202608, saved['revision'], 'undo')
    next_month = deepcopy(undone)
    next_month['month'] = 202609
    calculate_draft(next_month)
    after_undo = [d for d in center.project(store, next_month)['differences'] if d.get('subject') and d['name'] == first['name']]
    assert len(after_undo) == 1 and after_undo[0]['sourceId'] == 'ledger'
    assert len([r for r in next_month['differenceReviews'] if r['name'] == first['name']]) == 2
