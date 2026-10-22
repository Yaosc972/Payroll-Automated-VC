"""Manual business adjustments retain calculation, preview and undo safeguards."""
from copy import deepcopy
from io import BytesIO
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from test_recruitment_assignments import setup as assignment_fixture
from test_recruitment_drafts import book
from bonus_platform.engine import recruitment_assignments as assignments
from bonus_platform.engine import recruitment_reviews as reviews
from bonus_platform.engine import recruitment_settlement as settlement
from bonus_platform.engine import recruitment_special as special
from bonus_platform.engine.recruitment_awards import calculate_draft
from bonus_platform.engine.recruitment_drafts import DraftConflict
from bonus_platform.engine.recruitment_review_center import processing_records
from bonus_platform.engine.recruitment_worksheet import export_results as export_worksheet


def setup(tmp_path):
    store, state = assignment_fixture(tmp_path)
    parsed_path = store._folder(202607) / 'parsed' / (state['sources'][0]['id'] + '.json')
    parsed = json.loads(parsed_path.read_text())
    for record in parsed['records']:
        record['values']['奖金地区类型'] = '国内发展中国家'
    store._write(parsed_path, parsed)
    return store, store._save(store._folder(202607), store._rebuild(store._folder(202607), state))


def adjustment(state, **changes):
    row = state['rows'][0]
    return {'revision': state['revision'], 'basisType': 'manual', 'type': 'adjustment',
            'rowId': row['id'], 'kind': 'recruitment', 'role': '招聘负责人',
            'recipientId': 'zt-manual', 'recipientName': '手工领取人',
            'amount': 25.5, 'currency': '人民币', 'month': 202607, **changes}


@pytest.mark.parametrize('amount', [25.5, -10])
def test_manual_amount_preview_apply_retry_export_and_undo(tmp_path, amount):
    store, before = setup(tmp_path)
    payload = adjustment(before, amount=amount)
    preview = special.preview(store, 202607, payload)
    assert store.read(202607) == before
    assert preview['evidence'] is None
    assert preview['currentImpact'][0]['after'] - preview['currentImpact'][0]['before'] == amount
    saved = special.apply_preview(store, 202607, before['revision'], preview['id'])
    assert special.apply_preview(store, 202607, before['revision'], preview['id']) == saved
    record = saved['specialAdjustments'][0]
    assert record['basisType'] == 'manual' and not record['sourceId']
    assert not saved.get('reviewEntries')
    node = next(n for n in saved['rows'][0]['calculation']['recruitment']['nodes'] if n.get('adjustmentId'))
    assert node['amount'] == amount and node['scheduledMonth'] == 202607
    assert node['scheduleBasis'] == '手工补扣'
    assert processing_records(saved)[0]['type'] == '手工补扣'
    workbook = load_workbook(BytesIO(export_worksheet(saved)))
    assert any('手工补扣' in str(cell.value) for sheet in workbook for row in sheet for cell in row)
    with pytest.raises(ValueError, match='重复'):
        special.preview(store, 202607, {**payload, 'revision': saved['revision']})
    changed = deepcopy(saved)
    changed['rows'][0]['values']['ABC类别'] = 'A'
    calculate_draft(changed)
    assert any(n.get('adjustmentId') and n['issues'] for n in changed['rows'][0]['calculation']['recruitment']['nodes'])
    undone = store.history_action(202607, saved['revision'], 'undo')
    assert not any(n.get('adjustmentId') for n in undone['rows'][0]['calculation']['recruitment']['nodes'])


def test_manual_adjustment_guards_and_carry_forward(tmp_path):
    store, before = setup(tmp_path)
    payload = adjustment(before, month=202608)
    for patch in ({'amount': 0}, {'amount': float('nan')}, {'month': 202606},
                  {'currency': '欧元'}, {'recipientId': ''}, {'kind': 'invalid'},
                  {'evidence': {'sourceId': before['sources'][0]['id']}}):
        with pytest.raises(ValueError):
            special.preview(store, 202607, {**payload, **patch})
    preview = special.preview(store, 202607, payload)
    saved = special.apply_preview(store, 202607, before['revision'], preview['id'])
    carried = store.carry_forward(202608, 202607, 0)
    nodes = carried['rows'][0]['calculation']['recruitment']['nodes']
    assert sum(n['amount'] for n in nodes if n.get('adjustmentId') and n['scheduledMonth'] == 202608) == 25.5
    revoke = special.preview(store, 202608, {'revision': carried['revision'], 'type': 'revoke', 'recordId': saved['specialAdjustments'][0]['id']})
    revoked = special.apply_preview(store, 202608, carried['revision'], revoke['id'])
    assert not any(n.get('adjustmentId') for n in revoked['rows'][0]['calculation']['recruitment']['nodes'])
    restored = store.history_action(202608, revoked['revision'], 'undo')
    assert any(n.get('adjustmentId') for n in restored['rows'][0]['calculation']['recruitment']['nodes'])


def test_manual_exception_requires_actual_condition_and_current_month(tmp_path):
    store, state = setup(tmp_path)
    row = state['rows'][0]
    state = store.change(202607, state['revision'], {'edits': [
        {'rowId': row['id'], 'field': '招聘负责人最后工作日', 'value': '2026-01-01'}]})
    row = state['rows'][0]
    node = row['calculation']['recruitment']['nodes'][0]
    payload = adjustment(state, type='exception', nodeId=node['id'], conditions=['recipient_not_employed'])
    for patch in ({'conditions': ['candidate_not_employed']}, {'month': 202608},
                  {'nodeId': row['calculation']['recruitment']['nodes'][1]['id']}):
        with pytest.raises(ValueError):
            special.preview(store, 202607, {**payload, **patch})
    preview = special.preview(store, 202607, payload)
    saved = special.apply_preview(store, 202607, state['revision'], preview['id'])
    node = saved['rows'][0]['calculation']['recruitment']['nodes'][0]
    assert not node['eligibilityReasons'] and node['scheduledMonth'] == 202607
    assert node['status'] == '手工安排发放'
    future = deepcopy(saved)
    future['month'] = 202608
    calculate_draft(future)
    assert not any(n.get('exceptionId') for n in future['rows'][0]['calculation']['recruitment']['nodes'])


def test_manual_cutoff_validation_apply_and_undo(tmp_path):
    store, before = setup(tmp_path)
    payload = {'revision': before['revision'], 'type': 'cutoff', 'basisType': 'manual',
               'kind': 'referral', 'mode': 'date', 'date': '2026-07-15', 'month': 202607}
    with pytest.raises(ValueError, match='当前核算月'):
        special.preview(store, 202607, {**payload, 'date': '2026-08-15'})
    preview = special.preview(store, 202607, payload)
    saved = special.apply_preview(store, 202607, before['revision'], preview['id'])
    assert special.cutoff(saved, 'referral')['date'] == '2026-07-15'
    assert not saved.get('reviewEntries')
    undone = store.history_action(202607, saved['revision'], 'undo')
    assert special.cutoff(undone, 'referral')['mode'] == 'month_end'


@pytest.mark.parametrize('role', ['', '招聘负责人'])
def test_manual_exclude_api_has_truthful_history_and_undo(tmp_path, monkeypatch, role):
    from bonus_platform import recruitment_draft_api as api
    store, before = setup(tmp_path)
    monkeypatch.setattr(api, 'store', store)
    app = FastAPI()
    app.include_router(api.router)
    client = TestClient(app)
    url = '/api/recruitment/drafts/202607'
    row = before['rows'][0]
    decision = {'rowId': row['id'], 'kind': 'recruitment', 'action': 'exclude', **({'role': role} if role else {})}
    payload = {'revision': before['revision'], 'basisType': 'manual', 'edits': [], 'decisions': [decision]}
    response = client.post(url + '/previews', json=payload)
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview['evidence'] is None and preview['currentImpact'][0]['after'] == 0
    path = url + '/previews/' + preview['id'] + '/apply'
    response = client.post(path, json={'revision': before['revision']})
    assert response.status_code == 200, response.text
    saved = store.read(202607)
    assert client.post(path, json={'revision': before['revision']}).json()['revision'] == saved['revision']
    assert not saved.get('reviewEntries')
    assert saved['awardDecisions'][0]['basisType'] == 'manual'
    record = next(r for r in processing_records(saved) if r['action'] == 'decision')
    assert record['type'] == '不发奖金' and record['status'] == '已采用'
    undone = store.history_action(202607, saved['revision'], 'undo')
    assert undone['rows'][0]['calculation']['recruitment']['currentAmount'] == row['calculation']['recruitment']['currentAmount']
    assert next(r for r in processing_records(undone) if r['action'] == 'decision')['status'] == '已撤销'


def test_manual_assignments_preserve_identity_checks_preview_and_undo(tmp_path):
    store, before = setup(tmp_path)
    payload = {'revision': before['revision'], 'basisType': 'manual', 'assignments': [
        {'rowId': r['id'], 'recruiter': {'name': '新负责人', 'employeeId': 'zt-new'}} for r in before['rows']]}
    invalid = deepcopy(payload)
    invalid['assignments'][0]['assistant'] = {'name': '新负责人', 'employeeId': 'zt-new'}
    with pytest.raises(ValueError, match='同一人'):
        assignments.preview(store, 202607, invalid)
    preview = assignments.preview(store, 202607, payload)
    assert store.read(202607) == before
    assert preview['people'] == 2 and preview['nodeImpact']
    saved = reviews.apply_preview(store, 202607, before['revision'], preview['id'])
    assert all(r['values']['招聘负责人工号'] == 'zt-new' for r in saved['rows'])
    assert all(not e.get('evidenceId') for e in saved['edits'])
    undone = store.history_action(202607, saved['revision'], 'undo')
    assert all(r['values']['招聘负责人工号'] == 'zt-old' for r in undone['rows'])


def test_manual_scheduling_preserves_amount_date_and_revision_guards(tmp_path):
    store, state = setup(tmp_path)
    state = store.ingest(202607, [('招聘奖金核算明细202606.xlsx', book(
        ['姓名', '工号', '入职日期'], [['甲', 'zt0', '2026-07-01']], title='附件一-招聘奖金核算明细'))], state['revision'])
    state = store.change(202607, state['revision'], {'baseline': state['sources'][-1]['id']})
    row = state['rows'][0]
    node = row['calculation']['recruitment']['nodes'][0]
    payload = {'revision': state['revision'], 'basisType': 'manual', 'rowId': row['id'],
               'nodeId': node['id'], 'action': 'schedule', 'month': 202608}
    with pytest.raises(ValueError, match='金额'):
        settlement.preview_plan(store, 202607, {**payload, 'amount': 1})
    with pytest.raises(ValueError, match='早于'):
        settlement.preview_plan(store, 202607, {**payload, 'month': 202606})
    with pytest.raises(DraftConflict):
        settlement.preview_plan(store, 202607, {**payload, 'revision': -1})
    preview = settlement.preview_plan(store, 202607, payload)
    assert preview['amount'] == node['amount'] and store.read(202607) == state
    saved = settlement.apply_plan(store, 202607, state['revision'], preview['id'])
    assert settlement.apply_plan(store, 202607, state['revision'], preview['id']) == saved
    calculate_draft(saved)
    changed = next(n for n in saved['rows'][0]['calculation']['recruitment']['nodes'] if n['id'] == node['id'])
    assert changed['amount'] == node['amount'] and changed['scheduledMonth'] == 202608
    undone = store.history_action(202607, saved['revision'], 'undo')
    assert undone['rows'][0]['calculation']['recruitment']['nodes'][0]['scheduledMonth'] == node['scheduledMonth']


@pytest.mark.parametrize('outcome', ['pending', 'retain'])
def test_manual_difference_conclusion_keeps_amounts_and_reopens_when_facts_change(tmp_path, outcome):
    from test_recruitment_review_center import fixture, payload
    from bonus_platform.engine import recruitment_review_center as center
    store, before = fixture(tmp_path)
    request = {k: v for k, v in payload(store, before).items() if k not in {'reason', 'evidenceId'}}
    request.update(basisType='manual', outcome=outcome)
    saved = center.save_review(store, 202607, request)
    assert [r['calculation'] for r in saved['rows']] == [r['calculation'] for r in before['rows']]
    assert center.save_review(store, 202607, request) == saved
    data = center.project(store, saved, 'ledger')
    assert data['differences'][0]['status'] == ('待继续核对' if outcome == 'pending' else '已确认保留差异')
    changed = deepcopy(saved)
    changed['rows'][0]['values']['招聘负责人姓名'] = '更正后负责人'
    assert center.project(store, changed, 'ledger')['summary']['recheckDifferences'] == 1
    undone = store.history_action(202607, saved['revision'], 'undo')
    assert center.project(store, undone, 'ledger')['summary']['retainedDifferences'] == 0
