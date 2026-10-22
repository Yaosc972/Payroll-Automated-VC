"""Project pending exits by their effect, without adopting an unapproved fact."""
from copy import deepcopy

from .models import as_date
from .recruitment_awards import calculate_row


def review_evidence(row):
    refs=[p for p in row.get('provenance',{}).get('人员状态',[])
          if p.get('role')=='roster' and p.get('value')]
    statuses={p['value'] for p in refs}
    return {'currentStatus':next(iter(statuses)) if len(statuses)==1 else '',
            'statusSources':refs,'records':row.get('pendingResignations',[])}


def assess(state,row):
    """Compare the same calculation with each observed proposed exit date.

    Raw diagnostics and historical snapshots are untouched. Missing evidence or
    unresolved amounts cannot prove equivalence, so retain the original review.
    """
    records=row.get('pendingResignations',[])
    if not records or any(not as_date(r.get('lastDay')) for r in records):return None
    if set(row.get('unresolvedFields',[])) & {'入职日期','候选人入职时间','最后工作日','人员状态'}:return None
    before=row['calculation'];month=state['month']
    if any(before[k]['total'] is None for k in ('recruitment','referral')):return None

    def signature(award,future=False):
        selected=[]
        for n in award['nodes']:
            scheduled=n.get('scheduledMonth',n['dueMonth'])
            due=scheduled if scheduled is not None else n['dueMonth']
            if not due or (due>month if future else due==month):
                selected.append({k:n.get(k) for k in ('id','amount','currency','recipientId','dueDate',
                    'dueMonth','scheduledMonth','status','issues','eligibilityReasons','openingLocked')})
        return selected

    current=set();future=set()
    for last in sorted({r['lastDay'] for r in records}):
        candidate=deepcopy(row)
        candidate['values']['最后工作日']=last
        candidate.setdefault('edits',[]).append({'field':'最后工作日','value':last})
        # The proposed date is conditional, not a fabricated current status.
        after=calculate_row(state,candidate)
        for kind in ('recruitment','referral'):
            if after[kind]['total'] is None:return None
            if signature(before[kind])!=signature(after[kind]):current.add(kind)
            if signature(before[kind],True)!=signature(after[kind],True):future.add(kind)
            # Future eligibility is intentionally not evaluated by this month's
            # calculator. Preserve those later checks rather than declaring the
            # pending exit harmless for all subsequent installments.
            if any(n.get('amount') and not n.get('openingLocked') and
                   (n.get('scheduledMonth',n['dueMonth']) or n['dueMonth'] or month+1)>month
                   for n in before[kind]['nodes']):future.add(kind)
    return {'currentKinds':sorted(current),'futureKinds':sorted(future),'records':records}
