"""Read-only August acceptance evidence from an isolated platform activity.

Business writes and synchronization remain the existing HTTP API's responsibility.
"""
import argparse
from collections import Counter
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys

if __package__:
    from .accept_august_reference import compare, currency, date_string, identifier, identities, money, period, read_reference
else:
    from accept_august_reference import compare, currency, date_string, identifier, identities, money, period, read_reference

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_SHA = '8e9a204125d4429da22cc597c74680b86cc3f2cfba57cf9aa798b4118f3324e8'


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def canonical_digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    os.chmod(path, 0o600)


def extract_actual(state):
    records, nodes, unresolved_awards = [], [], []
    for row in state['rows']:
        values = row['values']
        records.append({'id': row['id'], 'values': values,
                        'provenance': row.get('provenance', {}), 'conflicts': row.get('conflicts', []),
                        'unresolvedFields': row.get('unresolvedFields', [])})
        for kind in ('recruitment', 'referral'):
            award = row.get('calculation', {}).get(kind, {})
            if award.get('total') is None and any(award.get(key) for key in ('pending', 'issues', 'reasons', 'nodes')):
                months = sorted({period(node['scheduledMonth'] if 'scheduledMonth' in node else node.get('dueMonth'))
                    for node in award.get('nodes', [])} - {None})
                unresolved_awards.append({'recordId': row['id'], 'kind': kind,
                    'pending': award.get('pending'), 'issues': award.get('issues', []),
                    'reasons': award.get('reasons', []), 'months': months})
            for index, node in enumerate(award.get('nodes', [])):
                scheduled = node['scheduledMonth'] if 'scheduledMonth' in node else node.get('dueMonth')
                issues = node.get('issues', [])
                eligibility = 'ineligible' if node.get('eligibilityReasons') or node.get('status') == '按规则不发' else (
                    'unknown' if issues or node.get('status') == '待核对' else 'eligible')
                nodes.append({'id': node.get('id') or f'{row["id"]}:{kind}:{index}',
                    'recordId': row['id'], 'kind': kind, 'role': node.get('role'), 'stage': node.get('label'),
                    'amount': money(node.get('amount')), 'month': period(scheduled),
                    'monthKnown': ('scheduledMonth' in node and scheduled is None) or period(scheduled) is not None,
                    'dueMonth': period(node.get('dueMonth')), 'dueDate': date_string(node.get('dueDate')),
                    'currency': currency(node.get('currency')), 'recipientId': identifier(node.get('recipientId')),
                    'recipientName': node.get('recipientName', ''), 'eligibility': eligibility,
                    'status': node.get('status'), 'issues': issues,
                    'eligibilityReasons': node.get('eligibilityReasons', []),
                    'adjustmentId': node.get('adjustmentId'), 'sourceEvidence': node.get('employmentBasis') or node.get('openingSource')})
    return {'month': state['month'], 'revision': state['revision'], 'records': records,
            'nodes': nodes, 'unresolvedAwards': unresolved_awards,
            'unresolvedCurrentAwards': [a for a in unresolved_awards if state['month'] in a['months']],
            'paymentReady': bool(state.get('paymentReady'))}


def business_digest(actual):
    by_id = {r['id']: r for r in actual['records']}
    payload = []
    for node in actual['nodes']:
        record = by_id[node['recordId']]
        payload.append({'identity': identities(record['values']),
            **{k: node.get(k) for k in ('kind', 'role', 'stage', 'amount', 'month', 'dueMonth',
                                       'currency', 'recipientId', 'eligibility')}})
    return canonical_digest(sorted(payload, key=lambda v: json.dumps(v, sort_keys=True, ensure_ascii=False)))


def comparison_is_verified(reference, actual, comparison, calculation_check):
    summary = comparison['summary']
    return (summary['outcomes'].get('equal', 0) == reference['currentNodeCount']
            and summary['eligibility'].get('eligible', 0) == reference['currentNodeCount']
            and not summary['referenceUnknownCurrentAmounts']
            and not comparison['unknownCurrentAmounts']
            and not actual.get('unresolvedCurrentAwards')
            and not comparison['platformOnly'] and calculation_check['status'] == 'VERIFIED')


def verify_protection(manifest, repo_root=ROOT):
    expected = read_json(manifest)
    changed, missing, roots = [], [], set()
    for name, expected_digest in expected.items():
        path = repo_root / name
        parts = Path(name).parts
        if 'recruitment_activities' in parts:
            end = parts.index('recruitment_activities') + 2
            roots.add(repo_root.joinpath(*parts[:end]))
        if not path.is_file():
            missing.append(name)
        elif digest(path) != expected_digest:
            changed.append(name)
    observed = {str(p.relative_to(repo_root)) for root in roots for p in root.rglob('*')
                if p.is_file() and p.name != '.lock'}
    added = sorted(observed - set(expected))
    return {'status': 'VERIFIED' if not (changed or missing or added) else 'NOT VERIFIED',
            'files': len(expected), 'changed': sorted(changed), 'missing': sorted(missing), 'added': added}


def input_checks(inputs):
    items = [*inputs['files'], inputs['reference']]
    failures = []
    for item in items:
        path = Path(item['path'])
        if not path.is_file() or digest(path) != item['sha256']:
            failures.append(item.get('name', str(path)))
    return {'status': 'VERIFIED' if not failures else 'NOT VERIFIED', 'files': len(items), 'failures': failures}


def source_checks(state, folder, inputs, scenario, comparison_receipt=None):
    allowed = {f['sha256'] for f in inputs['files']}
    held_out = inputs['reference']['sha256']
    failures, comparison_sources, active_sources = [], [], []
    for source in state['sources']:
        path = folder / 'sources' / source['storedName']
        actual_digest = digest(path) if path.is_file() else None
        record = {'id': source['id'], 'kind': source.get('kind'), 'sha256': actual_digest,
                  'active': bool(source.get('active', True)), 'comparisonOnly': bool(source.get('comparisonOnly')),
                  'snapshotOnly': bool(source.get('snapshotOnly')), 'error': source.get('error')}
        active_sources.append(record)
        if not path.is_file():
            failures.append({'reason': 'source_file_missing', 'id': source['id']})
        if not record['active']:
            continue
        if actual_digest == held_out and record['comparisonOnly']:
            comparison_sources.append(record)
            continue
        if actual_digest == held_out:
            failures.append({'reason': 'held_out_bytes_in_calculation', 'id': source['id']})
        if scenario != 'manual_preserved':
            if source.get('purpose') == 'external-results':
                failures.append({'reason': 'external_result_input', 'id': source['id']})
            if actual_digest not in allowed and source.get('kind') not in {'beisen', 'overseas_api'}:
                failures.append({'reason': 'unapproved_input_bytes', 'id': source['id']})
            if scenario == 'api_independent' and actual_digest in allowed:
                original = next(f for f in inputs['files'] if f['sha256'] == actual_digest)
                if original.get('role') and actual_digest != inputs['openingId']:
                    failures.append({'reason': 'current_file_facts_in_api_scenario', 'id': source['id']})
    active_operations = {o['id'] for o in state.get('operations', []) if o.get('active', True)}
    effective = lambda item: item.get('active', True) and (not item.get('operationId') or item['operationId'] in active_operations)
    edits = [e for e in state.get('edits', []) if effective(e)]
    reference_edits = [e for e in edits if e.get('referenceFact')]
    manual_counts = {key: sum(1 for e in state.get(key, []) if effective(e)) for key in (
        'manualRows', 'reviewEntries', 'awardDecisions', 'specialAdjustments', 'externalResults')}
    if scenario != 'manual_preserved' and (edits or any(manual_counts.values()) or active_operations):
        failures.append({'reason': 'manual_or_reference_adoption_in_independent_scenario',
                         'edits': len(edits), 'operations': len(active_operations), 'counts': manual_counts})
    if scenario == 'api_independent':
        for kind in ('beisen', 'overseas_api'):
            if not any(s['kind'] == kind and s['active'] and not s['comparisonOnly'] and not s['snapshotOnly'] for s in active_sources):
                failures.append({'reason': 'monthly_api_source_not_adopted', 'kind': kind})
    comparison_proven = not comparison_sources
    if comparison_sources and comparison_receipt:
        comparison_proven = (comparison_receipt.get('beforeBusinessDigest') == comparison_receipt.get('afterBusinessDigest')
                             and bool(comparison_receipt.get('beforeBusinessDigest'))
                             and comparison_receipt.get('todosUnchanged') is True)
    status = 'NOT VERIFIED' if failures else 'VERIFIED' if comparison_proven else 'INCONCLUSIVE'
    return {'status': status, 'sources': active_sources, 'failures': failures,
            'comparisonOnlyHeldOutSources': comparison_sources, 'comparisonIsolationProven': comparison_proven,
            'activeReferenceFactEdits': len(reference_edits), 'activeEdits': len(edits),
            'activeOperations': len(active_operations), 'manualCounts': manual_counts,
            'manualScenarioExcludedFromIndependentAccuracy': scenario == 'manual_preserved'}


def report(options):
    data_root = Path(options.data_root).resolve(strict=True)
    if not re.fullmatch(r'[a-f0-9]{32}', options.activity):
        raise ValueError('Expected an exact isolated activity ID')
    activity_root = (data_root / 'recruitment_activities' / options.activity).resolve(strict=True)
    if not activity_root.is_relative_to(data_root):
        raise ValueError('Activity escapes the supplied isolated data root')
    inputs = read_json(options.inputs)
    month = inputs['month']
    folder = activity_root / 'drafts' / str(month)
    state = read_json(folder / 'draft.json')
    out = Path(options.out).resolve()
    if out.is_relative_to(activity_root):
        raise ValueError('Evidence cannot be written into an activity')
    out.mkdir(parents=True, exist_ok=True)
    os.chmod(out, 0o700)
    protection = verify_protection(options.protected)
    checks = input_checks(inputs)
    reference = read_reference(inputs['reference']['path'], month)
    actual = extract_actual(state)
    comparison = compare(reference, actual)
    receipt = read_json(options.comparison_receipt) if options.comparison_receipt else None
    sources = source_checks(state, folder, inputs, options.scenario, receipt)
    reference_integrity = {'status': 'VERIFIED' if inputs['reference']['sha256'] == REFERENCE_SHA and
        reference['currentNodeCount'] == 438 and reference['currentRoles'] == {'招聘负责人': 355, '协助招聘人': 42, '推荐人': 41}
        and reference['currentTotals'] == {'CNY': '41427.00', 'EUR': '6724.54', 'USD': '2101.17'} else 'NOT VERIFIED',
        'currentNodes': reference['currentNodeCount'], 'roles': reference['currentRoles'],
        'totals': reference['currentTotals'], 'observations': reference['observations']}
    calculated_revision = state.get('calculation', {}).get('draftRevision')
    calculation_check = {'status': 'VERIFIED' if calculated_revision == state['revision'] else 'NOT VERIFIED',
                         'draftRevision': state['revision'], 'calculatedRevision': calculated_revision}
    result_status = 'VERIFIED' if comparison_is_verified(reference, actual, comparison, calculation_check) else 'NOT VERIFIED'
    result = {'scenario': options.scenario, 'activityId': options.activity, 'month': month,
        'revision': state['revision'], 'inputManifestDigest': canonical_digest(inputs),
        'draftFileDigest': digest(folder / 'draft.json'), 'businessDigest': business_digest(actual),
        'inputChecks': checks, 'sourceChecks': sources, 'referenceIntegrity': reference_integrity,
        'protection': protection, 'calculationRevision': calculation_check, 'comparisonStatus': result_status,
        'unresolvedCurrentAwards': actual['unresolvedCurrentAwards'],
        'comparison': comparison, 'paymentReady': actual['paymentReady'],
        'actualPayment': 'NOT VERIFIED', 'limitations': [
            'The held-out workbook contains cached values; this command does not recalculate Excel formulas.',
            'Source API pagination and controls require separate live/replay/UI receipts.',
            'Four compared output dimensions do not establish eligibility or actual payment.']}
    write_json(out / 'report.json', result)
    write_json(out / 'actual-nodes.json', actual)
    write_json(out / 'reference-cells.json', reference)
    summary = comparison['summary']
    content = '\n'.join([
        f'# 2026 年 8 月验收：{options.scenario}', '',
        f'活动 `{options.activity}`，版本 {state["revision"]}。本命令只读现有计算结果。', '',
        f'- 原件完整性：{reference_integrity["status"]}，{reference["currentNodeCount"]} 笔本月非零节点。',
        f'- 比较结果：{result_status}。{json.dumps(summary["outcomes"], ensure_ascii=False)}。',
        f'- 平台本月独有节点：{summary["platformOnlyCurrentNodes"]}；本月未知金额：{summary["unknownCurrentAmountNodes"]}；本月总额未定奖项：{len(actual["unresolvedCurrentAwards"])}。',
        f'- 来源独立性：{sources["status"]}；原件摘要：{checks["status"]}；原活动保护：{protection["status"]}。',
        f'- 原币参考合计：{json.dumps(summary["referenceTotals"], ensure_ascii=False)}。',
        f'- 原币平台本月合计：{json.dumps(summary["actualCurrentTotals"], ensure_ascii=False)}。', '',
        '逐任职、逐节点、领取人、来源和差异写入受限 report.json。金额一致仍需独立核对资格。',
        '本报告不证明实际工资支付；真实接口原页、操作及桌面控件由另附证据判定。', '',
        f'业务节点摘要：`{result["businessDigest"]}`。', ''])
    (out / 'report.md').write_text(content)
    os.chmod(out / 'report.md', 0o600)
    print(json.dumps({'scenario': options.scenario, 'status': result_status,
        'sourceIndependence': sources['status'], 'protection': protection['status'],
        'summary': summary, 'businessDigest': result['businessDigest']}, ensure_ascii=False))
    return 0 if all(c['status'] == 'VERIFIED' for c in (checks, sources, protection, reference_integrity)) and result_status == 'VERIFIED' else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    command = commands.add_parser('report')
    command.add_argument('--data-root', required=True)
    command.add_argument('--activity', required=True)
    command.add_argument('--inputs', required=True)
    command.add_argument('--protected', required=True)
    command.add_argument('--out', required=True)
    command.add_argument('--scenario', required=True, choices=('original_files', 'api_independent', 'manual_preserved'))
    command.add_argument('--comparison-receipt')
    return report(parser.parse_args(argv))


if __name__ == '__main__':
    sys.exit(main())
