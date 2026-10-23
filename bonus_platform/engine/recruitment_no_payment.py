from .recruitment_awards import NODES, calculate_base
from .recruitment_external_results import automatic_roles


def cancellation_reasons(award):
    if award['total'] != 0:
        return []
    reasons = [reason for reason in award.get('reasons', [])
               if reason in {'入职未满一个月离职', '转正当月离职'}]
    decision = award.get('approvalDecision')
    if decision and decision.get('action') == 'exclude':
        label = '招聘奖金' if award['kind'] == 'recruitment' else '内推奖金'
        origin = '手工取消' if decision.get('basisType') == 'manual' else '按审批取消'
        reasons.append(origin + label + ('：' + decision['reason'] if decision.get('reason') else ''))
    return list(dict.fromkeys(reasons))


def project(state, row):
    calculated = row['calculation']
    if row.get('externalOnly') or row['values'].get('核算范围') == '不纳入核算':
        return calculated
    reasons = {kind: cancellation_reasons(calculated[kind])
               for kind in ('recruitment', 'referral')}
    selected = {kind for kind, details in reasons.items()
                if details and automatic_roles(row, kind)}
    if not selected:
        return calculated
    shadow = {**row, 'awardDecisions': [decision for decision in row.get('awardDecisions', [])
              if not (decision['kind'] in selected and not decision.get('role')
                      and decision.get('action') == 'exclude')]}
    basis = calculate_base(state, shadow, evaluate_employment=False)
    result = dict(calculated)
    for kind in selected:
        award = calculated[kind]
        original = basis[kind]
        if original['total'] is None or original['total'] <= 0 or not original['currency']:
            continue
        roles = automatic_roles(row, kind)
        existing = {(node['role'], node['label']) for node in award['nodes']}
        retained = []
        for node in original['nodes']:
            if (node['role'] not in roles or node['label'] not in NODES
                    or (node['role'], node['label']) in existing
                    or node.get('openingLocked') or node.get('adjustmentId')
                    or node.get('externalResultId') or node.get('amount') is None):
                continue
            scheduled = node.get('scheduledMonth', node.get('dueMonth'))
            if node.get('openingSource') and scheduled and scheduled < state['month']:
                continue
            retained.append({**{key: node.get(key) for key in (
                'role', 'label', 'recipientId', 'recipientName', 'amount', 'currency', 'dueDate', 'dueMonth')},
                'status': '按规则不发', 'scheduledMonth': None, 'issues': [],
                'eligibilityReasons': reasons[kind], 'scheduleText': '；'.join(reasons[kind]),
                'displayOnly': True})
        if retained:
            result[kind] = {**award, 'nonPaymentInstallments': retained}
    return result


def calculations(state):
    return {row['id']: project(state, row) for row in state['rows']}


def installments(award):
    return [*award['nodes'], *award.get('nonPaymentInstallments', [])]
