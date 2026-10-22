from copy import deepcopy
from hashlib import sha256
import json

from openpyxl import Workbook

from scripts.accept_august import business_digest, comparison_is_verified, extract_actual, source_checks, verify_protection
from scripts.accept_august_reference import compare, identifier, match_records, money, read_reference


def fixtures():
    record = {'id': 'ref-1', 'values': {'工号': 'zt-test', '入职日期': '2026-08-01'}}
    node = {'id': 'node-1', 'recordId': 'ref-1', 'kind': 'recruitment', 'role': '招聘负责人',
            'stage': '入职满一个月', 'amount': '10.00', 'month': 202608, 'currency': 'CNY',
            'recipientId': 'zt-recipient', 'eligibility': 'eligible'}
    reference = {'month': 202608, 'records': [record], 'nodes': [node]}
    actual = {'month': 202608, 'records': [deepcopy(record)], 'nodes': [deepcopy(node)]}
    return reference, actual


def test_wrong_recipient_is_dimension_difference_not_missing_node():
    reference, actual = fixtures()
    actual['nodes'][0]['recipientId'] = 'zt-other'
    result = compare(reference, actual)
    assert result['summary']['outcomes'] == {'different': 1}
    assert result['nodes'][0]['dimensions']['recipientId'] == 'different'
    assert result['nodes'][0]['dimensions']['amount'] == 'equal'
    assert result['platformOnly'] == []


def test_explicit_regional_staff_prefix_is_a_label_and_zeroes_are_retained():
    assert identifier('海外-ZT0021614') == identifier('zt0021614')
    assert identifier('zt0021614') != identifier('zt21614')
    assert identifier('part-zt0021614') == 'part-zt0021614'


def test_negative_values_and_unknown_amounts_keep_their_meaning():
    reference, actual = fixtures()
    reference['nodes'][0]['amount'] = actual['nodes'][0]['amount'] = '-12.35'
    assert compare(reference, actual)['summary']['referenceTotals'] == {'CNY': '-12.35'}
    actual['nodes'][0]['amount'] = None
    result = compare(reference, actual)
    assert result['summary']['outcomes'] == {'unknown': 1}
    assert result['summary']['unknownCurrentAmountNodes'] == 1
    assert money(None) is None
    assert money('bad') is None
    assert money('-1.005') == '-1.01'


def test_duplicates_are_ambiguous_and_not_overwritten():
    reference, actual = fixtures()
    duplicate = {**actual['nodes'][0], 'id': 'duplicate'}
    actual['nodes'].append(duplicate)
    result = compare(reference, actual)
    assert result['summary']['outcomes'] == {'node_ambiguous': 1}
    assert len(result['nodes'][0]['actualCandidates']) == 2
    assert len(result['platformOnly']) == 2


def test_name_only_does_not_match_and_strong_duplicate_identity_is_ambiguous():
    refs = [{'id': 'r', 'values': {'姓名': 'Same name', '入职日期': '2026-08-01'}}]
    actual = [{'id': 'a', 'values': dict(refs[0]['values'])}]
    assert match_records(refs, actual)['r']['status'] == 'unmatched'
    refs[0]['values']['工号'] = 'zt-one'
    actual[0]['values']['工号'] = 'ZT-ONE'
    actual.append({'id': 'b', 'values': dict(actual[0]['values'])})
    assert match_records(refs, actual)['r']['status'] == 'ambiguous'


def test_workbook_reader_uses_amount_period_cells_and_referral_currency_note(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = '附件一-招聘奖金核算明细'
    for column, value in {2: 'Virtual', 3: 'zt-one', 5: '2026-08-01', 22: 'zt-r',
                           39: -10.25, 40: 202608, 56: '人民币', 58: 'Virtual R',
                           59: 'zt-r', 62: 12.5, 63: 202608,
                           72: '内推奖币种 CZK', 64: '=1+2', 65: 202608}.items():
        ws.cell(4, column, value)
    path = tmp_path / 'source.xlsx'
    wb.save(path)
    result = read_reference(path)
    assert result['currentNodeCount'] == 2
    assert result['currentTotals'] == {'CNY': '-10.25', 'CZK': '12.50'}
    assert result['observations']['formulaWithoutCachedAmount'] == 1
    assert next(n for n in result['nodes'] if n['column'] == 64)['amount'] is None
    assert result['nodes'][0]['cell'] == '附件一-招聘奖金核算明细!AM4'


def test_explicit_cancelled_schedule_and_qualification_do_not_fall_back():
    state = {'month': 202608, 'revision': 1, 'rows': [{'id': 'r', 'values': {}, 'calculation': {
        'recruitment': {'nodes': [{'id': 'n', 'label': '转正', 'amount': 10,
            'dueMonth': 202608, 'scheduledMonth': None, 'status': '按规则不发',
            'eligibilityReasons': ['virtual exclusion']}], 'total': 10}}}]}
    node = extract_actual(state)['nodes'][0]
    assert node['month'] is None
    assert node['eligibility'] == 'ineligible'


def test_known_cancellation_is_month_difference_while_unknown_period_is_unknown():
    reference, actual = fixtures()
    actual['nodes'][0].update(month=None, monthKnown=True)
    assert compare(reference, actual)['nodes'][0]['dimensions']['month'] == 'different'
    actual['nodes'][0]['monthKnown'] = False
    assert compare(reference, actual)['nodes'][0]['dimensions']['month'] == 'unknown'


def test_protection_detects_changes_and_new_files(tmp_path):
    root = tmp_path / 'recruitment_activities' / 'activity'
    root.mkdir(parents=True)
    original = root / 'draft.json'
    original.write_text('original')
    manifest = tmp_path / 'before.json'
    manifest.write_text(json.dumps({str(original.relative_to(tmp_path)): sha256(original.read_bytes()).hexdigest()}))
    assert verify_protection(manifest, tmp_path)['status'] == 'VERIFIED'
    original.write_text('changed')
    (root / 'extra.json').write_text('new')
    result = verify_protection(manifest, tmp_path)
    assert result['status'] == 'NOT VERIFIED'
    assert len(result['changed']) == len(result['added']) == 1


def test_same_answer_bytes_disguised_as_external_result_are_rejected(tmp_path):
    (tmp_path / 'sources').mkdir()
    source = tmp_path / 'sources' / 'disguised.xlsx'
    source.write_bytes(b'answer')
    answer_hash = sha256(source.read_bytes()).hexdigest()
    inputs = {'files': [], 'reference': {'sha256': answer_hash}, 'openingId': 'opening'}
    state = {'sources': [{'id': 'different-id', 'storedName': source.name,
                         'purpose': 'external-results', 'active': True}]}
    result = source_checks(state, tmp_path, inputs, 'original_files')
    assert result['status'] == 'NOT VERIFIED'
    assert 'held_out_bytes_in_calculation' in {f['reason'] for f in result['failures']}


def test_business_digest_ignores_generated_ids_but_retains_recipient():
    _, actual = fixtures()
    before = business_digest(actual)
    actual['nodes'][0]['id'] = 'another-generated-id'
    assert business_digest(actual) == before
    actual['nodes'][0]['recipientId'] = 'different-recipient'
    assert business_digest(actual) != before


def test_current_unknown_extra_node_prevents_an_otherwise_equal_pass():
    reference, actual = fixtures()
    reference['currentNodeCount'] = 1
    actual['nodes'].append({**actual['nodes'][0], 'id': 'unknown', 'stage': '转正', 'amount': None})
    comparison = compare(reference, actual)
    assert comparison['summary']['outcomes'] == {'equal': 1}
    assert not comparison['platformOnly']
    assert not comparison_is_verified(reference, actual, comparison, {'status': 'VERIFIED'})


def test_current_award_with_unresolved_total_prevents_equal_node_pass():
    reference, actual = fixtures()
    reference['currentNodeCount'] = 1
    state = {'month': 202608, 'revision': 1, 'rows': [{'id': 'ref-1', 'values': actual['records'][0]['values'],
        'calculation': {'recruitment': {'total': None, 'issues': ['unknown total'], 'nodes': [{
            'id': 'node-1', 'role': '招聘负责人', 'label': '入职满一个月', 'amount': 10,
            'dueMonth': 202608, 'currency': 'CNY', 'recipientId': 'zt-recipient', 'status': '本月到期'}]}}}]}
    actual = extract_actual(state)
    comparison = compare(reference, actual)
    assert comparison['summary']['outcomes'] == {'equal': 1}
    assert not comparison_is_verified(reference, actual, comparison, {'status': 'VERIFIED'})
    assert actual['unresolvedCurrentAwards'][0]['issues'] == ['unknown total']


def test_future_unknown_node_and_award_do_not_block_current_month_pass():
    reference, actual = fixtures()
    reference['currentNodeCount'] = 1
    node = {'id': 'node-1', 'role': '招聘负责人', 'label': '入职满一个月', 'amount': 10,
            'dueMonth': 202608, 'currency': 'CNY', 'recipientId': 'zt-recipient', 'status': '本月到期'}
    state = {'month': 202608, 'revision': 1, 'rows': [{'id': 'ref-1', 'values': actual['records'][0]['values'],
        'calculation': {'recruitment': {'total': 10, 'nodes': [node]},
            'referral': {'total': None, 'issues': ['future unknown'], 'nodes': [
                {**node, 'id': 'future', 'role': '推荐人', 'label': '转正', 'dueMonth': 202609, 'amount': None}]}}}]}
    actual = extract_actual(state)
    assert actual['unresolvedAwards'][0]['months'] == [202609]
    assert actual['unresolvedCurrentAwards'] == []
    assert comparison_is_verified(reference, actual, compare(reference, actual), {'status': 'VERIFIED'})


def test_reference_unknown_current_amount_prevents_a_known_nodes_only_pass():
    reference, actual = fixtures()
    reference['currentNodeCount'] = 1
    reference['nodes'].append({**reference['nodes'][0], 'id': 'uncached', 'stage': '转正', 'amount': None})
    assert not comparison_is_verified(reference, actual, compare(reference, actual), {'status': 'VERIFIED'})
