from copy import deepcopy

import pytest

from bonus_platform.engine import recruitment_approval_intake as intake
from bonus_platform.engine import recruitment_documents as documents
from bonus_platform.engine import recruitment_reconcile as reconcile
from bonus_platform.engine import recruitment_review_center as center
from bonus_platform.engine import recruitment_reviews as reviews
from test_recruitment_review_center import fixture
from test_recruitment_approval_intake import setup as approval_setup


def august_fixture(tmp_path):
    store, state = fixture(tmp_path)
    state = store.carry_forward(202608, 202607, 0)
    state['sources'][-1]['forMonth'] = 202608
    state['baseline'] = 'ledger'
    store._write(store._folder(202608) / 'draft.json', state)
    return store, state


def test_previous_month_ledger_never_defaults_to_august_comparison(tmp_path):
    store, state = august_fixture(tmp_path)
    before = deepcopy(state)
    result = center.project(store, state)
    assert result['sourceId'] == ''
    assert result['comparisonScope'] == 'not_provided'
    assert result['comparisonReady'] is False
    assert result['differences'] == [] and result['totalsByCurrency'] == []
    assert result['summary']['differenceItems'] == result['summary']['pendingDifferences'] == 0
    assert result['basis'] == '尚未导入本月线下核对表'
    assert result['sources'][0]['id'] == 'ledger'
    assert store.read(202608) == before


def test_explicit_previous_month_keeps_full_history_without_monthly_missing_rows(tmp_path):
    store, state = august_fixture(tmp_path)
    result = center.project(store, state, 'ledger')
    assert result['sourceId'] == 'ledger' and result['comparisonScope'] == 'history'
    assert result['comparisonReady'] is False and result['differences'] == []
    historical = reconcile.reconcile(store, 202608, 'ledger')
    assert historical['referenceId'] == 'ledger'
    assert historical['moneyDifferences']
    assert historical['monthly']['differences'] == []
    assert historical['monthly']['comparisonScope'] == 'history'


def test_current_month_ledger_still_reports_real_missing_nodes(tmp_path):
    store, state = fixture(tmp_path)
    state['sources'][-1]['name'] = '2026年7月核对台账.xlsx'
    result = center.project(store, state)
    assert result['sourceId'] == 'ledger' and result['comparisonReady'] is True
    assert result['comparisonScope'] == 'current'
    assert result['differences'] and result['summary']['pendingDifferences'] > 0
    path = store._folder(202607) / 'parsed' / 'ledger.json'
    store._write(path, {'records': []})
    result = center.project(store, state)
    assert result['differences']
    assert all(d['category'] == '台账本月未列' for d in result['differences'] if not d.get('subject'))
    assert any(d.get('matchStatus') == 'draft_only' for d in result['differences'])


def test_undated_ledger_is_not_proof_of_current_month(tmp_path):
    store, state = fixture(tmp_path)
    state['sources'][-1].update(name='线下核对台账.xlsx', forMonth=202607, comparisonOnly=False)
    result = center.project(store, state)
    assert result['sourceId'] == '' and not result['differences']
    assert result['comparisonScope'] == 'not_provided'


def test_undated_file_uploaded_as_current_comparison_is_a_valid_reference(tmp_path):
    store, state = fixture(tmp_path)
    state['sources'][-1].update(name='核对结果.xlsx', forMonth=202607, comparisonOnly=True)
    for source_id in ('', 'ledger'):
        result = center.project(store, state, source_id)
        assert result['sourceId'] == 'ledger' and result['comparisonScope'] == 'current'
        assert result['comparisonReady'] is True and result['differences']


@pytest.mark.parametrize('name', ['7月招聘奖金台账.xlsx', '2026 07招聘奖金台账.xlsx', '2026年 7月招聘奖金台账.xlsx'])
def test_explicit_other_month_never_falls_back_to_upload_month(tmp_path, name):
    store, state = august_fixture(tmp_path)
    state['sources'][-1].update(name=name, comparisonOnly=True, forMonth=202608)
    result = center.project(store, state)
    assert result['sourceId'] == '' and result['comparisonReady'] is False
    assert not result['differences'] and result['comparisonScope'] == 'not_provided'
    historical = center.project(store, state, 'ledger')
    assert historical['comparisonScope'] == 'history' and not historical['differences']


def test_real_august_reference_preserves_unlisted_august_nodes(tmp_path):
    from bonus_platform.engine.recruitment_awards import calculate_draft
    store, state = fixture(tmp_path)
    state['month'] = 202608
    for row in state['rows']:
        row['values'].update(入职日期='2026-07-02', 候选人入职时间='2026-07-02')
    calculate_draft(state)
    state['sources'][-1]['name'] = '全球招聘奖金核算明细表202608.xlsx'
    (store._folder(202608) / 'parsed').mkdir(parents=True, exist_ok=True)
    store._write(store._folder(202608) / 'parsed' / 'ledger.json', {'records': []})
    result = center.project(store, state)
    assert result['comparisonScope'] == 'current' and result['comparisonReady'] is True
    assert result['differences'] and all(d['category'] == '台账本月未列' for d in result['differences'] if not d.get('subject'))
    assert any(d.get('matchStatus') == 'draft_only' for d in result['differences'])


def test_missing_pdf_references_are_visible_but_complete_changes_can_apply(tmp_path, monkeypatch):
    store, state = approval_setup(tmp_path, monkeypatch, {'审批': '候选甲申请剔除10天。附件：WANG_TAO_offer.pdf；YANG_QIUSHI_offer.PDF。'})
    data = intake.proposals(store, state)
    doc = data['documents'][0]
    assert doc['referencedAttachments'] == [
        {'name': 'WANG_TAO_offer.pdf', 'sourceIds': [], 'status': 'reference_only', 'required': False},
        {'name': 'YANG_QIUSHI_offer.pdf', 'sourceIds': [], 'status': 'reference_only', 'required': False},
    ]
    item = data['items'][0]
    assert item['status'] == 'ready' and item['documentIssues'] == []
    preview = intake.preview(store, 202607, {'revision': state['revision'], 'itemIds': [item['id']]})
    saved = reviews.apply_preview(store, 202607, state['revision'], preview['id'])
    assert saved['rows'][0]['values']['周期剔除天数'] == 10


def test_oa_pdf_reference_keeps_spaces_and_normalizes_observed_ocr_extension():
    data = {'pages': [{'text': '附件\nYANG QIUSHI的（HC） 海外员工offer审批流程.paf\nWANG TAO的（HC） 海外员工offer审批流程.pdf\n审批记录'}]}
    assert documents.mentioned_attachments(data, include_pdf=True) == [
        'YANG QIUSHI的（HC） 海外员工offer审批流程.pdf',
        'WANG TAO的（HC） 海外员工offer审批流程.pdf']


def test_pdf_reference_matching_lists_only_real_available_sources(tmp_path, monkeypatch):
    store, state = approval_setup(tmp_path, monkeypatch, {'审批': '候选甲申请剔除10天。附件：Offer.PDF。', 'Offer': '候选甲申请剔除10天。'})
    doc = intake.proposals(store, state)['documents'][0]
    available = next(s for s in state['sources'] if s['name'] == 'Offer.pdf')
    assert doc['referencedAttachments'][0]['sourceIds'] == [available['id']]
    assert doc['referencedAttachments'][0]['status'] == 'available'
    assert available['id'] in doc['attachmentIds']
    available['active'] = False
    assert intake.proposals(store, state)['documents'][0]['referencedAttachments'][0]['status'] == 'reference_only'


def test_missing_excel_reference_keeps_existing_mandatory_check(tmp_path, monkeypatch):
    store, state = approval_setup(tmp_path, monkeypatch, {'审批': '候选甲申请剔除10天。附件：资格名单.xIsx，Offer.pdf。'})
    item = intake.proposals(store, state)['items'][0]
    assert item['status'] == 'blocked' and '资格名单.xlsx' in str(item['issues'])
    with pytest.raises(ValueError, match='附件'):
        intake.preview(store, 202607, {'revision': state['revision'], 'itemIds': [item['id']]})
    assert documents.mentioned_attachments({'pages': [{'text': '资格名单.xIsx，Offer.pdf'}]}) == ['资格名单.xlsx']
