"""Carry forward opening installments and separately retain adopted schedules.

Opening amounts are prior-month ledger facts, never proof of bank payment.
Current-month result amounts are deliberately unavailable to this module.
"""
from copy import deepcopy
from decimal import Decimal
from datetime import timedelta
from .models import add_months, as_date, yyyymm
from .recruitment_draft_sources import digest, text
from .recruitment_awards import NODES, money, number, award as calculate_award

COLUMNS={'recruitment':{'招聘负责人':[(39,40,0),(41,42,1),(43,44,2),(52,53,3)],
                        '协助招聘人':[(46,47,0),(48,49,1),(50,51,2),(54,55,3)]},
         'referral':{'推荐人':[(62,63,0),(64,65,1),(66,67,2),(68,69,3)]}}


def period(value):
    value=text(value)
    return int(value) if len(value)==6 and value.isdigit() and 1<=int(value[-2:])<=12 else None


def apply_opening(state,row,result):
    replay=state['offlineReplay'];opening=replay.get('opening',{}).get(row['id'])
    if opening and opening.get('facts'):
        from .recruitment_reconcile import comparable
        changed=[f for f,v in opening['facts'].items() if comparable(f,v)!=comparable(f,row['values'].get(f,''))]
        opening={**opening,'reprice':bool(changed),'changedFields':changed}
    schedule=replay.get('schedules',{}).get(row['id'],{})
    history=next((h for h in row.get('history',[]) if opening and h['ref']==opening['ref']),None)
    cells={c['column']:c['value'] for c in history['cells']} if history else {}
    month=state['month'];v=row['values'];hire=as_date(v.get('入职日期'))
    for kind,roles in COLUMNS.items():
        award=result[kind]
        if v.get('核算范围')=='不纳入核算' or award.get('approvalDecision',{} ) and award['approvalDecision'].get('action')=='exclude':
            award['cancelledBalances']=[]
            continue
        award['formulaNodes']=deepcopy(award['nodes'])
        gross=calculate_award(row,kind,month,evaluate_employment=False) if kind=='recruitment' else award
        award['entitlementTotal']=gross['total']
        award['cancelledBalances']=[]
        if history:
            original={ (n['role'],n['label']):n for n in award['nodes'] }
            carried=[]
            for role,columns in roles.items():
                amounts={i:number(cells.get(c)) for c,p,i in columns}
                # Preserve already arranged opening installments on a repricing.
                # Allocate the changed entitlement across still-open installments.
                if opening['reprice'] and kind=='recruitment' and award['total'] is not None:
                    role_total=next((Decimal(str(r['allocatedAmount'])) for r in award['recipientTotals'] if r['role']==role),Decimal(0))
                    locked=[i for c,p,i in columns if period(cells.get(p)) and period(cells[p])<month]
                    remaining=[i for c,p,i in columns if i not in locked and (role,NODES[i]) in original]
                    residual=role_total-sum((amounts[i] or Decimal(0)) for i in locked)
                    weights=sum(Decimal(str(original[(role,NODES[i])]['amount'])) for i in remaining)
                    allocated=Decimal(0)
                    for i in remaining:
                        value=(Decimal(str(money(residual*Decimal(str(original[(role,NODES[i])]['amount']))/weights))) if weights else Decimal(0)) if i!=remaining[-1] else residual-allocated
                        amounts[i]=value;allocated+=value
                for c,p,i in columns:
                    amount=amounts[i]
                    if amount is None or amount==0:continue
                    due=add_months(hire,(1,3,6)[i])-timedelta(days=1) if hire and i<3 else as_date(v.get('转正日期')) if i==3 else None
                    node=deepcopy(original.get((role,NODES[i]),{}))
                    node.update(id=digest(row['id']+'|'+kind+'|'+role+'|'+str(i)),rowId=row['id'],role=role,
                        recipientId=text(v.get(role+'工号')),recipientName=text(v.get(role+'姓名')),
                        label=NODES[i],amount=float(amount),currency=award['currency'],
                        dueDate=due.strftime('%Y-%m-%d') if due else '',dueMonth=yyyymm(due),
                        paidAmount=None,paymentStatus='未核实',paymentReady=False,
                        openingAmount=float(number(cells.get(c)) or 0),openingPeriod=text(cells.get(p)),openingSource=opening['ref'],
                        amountBasis='期初未结分期更正' if opening['reprice'] and kind=='recruitment' else '六月期初分期')
                    node.setdefault('issues',[]);node.setdefault('status','待核对');node.setdefault('timing','往期待核')
                    carried.append(node)
            award['nodes']=carried
            award['openingSource']=opening['ref'];award['openingRepriced']=opening['reprice']
            if not opening['reprice']:
                award['openingTotal']=money(sum(number(cells.get(c)) or Decimal(0) for c in ((38,45) if kind=='recruitment' else (61,))))
                award['total']=award['openingTotal']
        if kind=='recruitment':
            for role,columns in roles.items():
                entitled=next((Decimal(str(t['allocatedAmount'])) for t in gross['recipientTotals'] if t['role']==role),Decimal(0))
                if history and not opening['reprice']: entitled=number(cells.get(38 if role=='招聘负责人' else 45)) or Decimal(0)
                source_nodes=award['nodes'] if history else gross['nodes']
                cancelled=[]
                for c,p,i in columns:
                    current=text(schedule.get('periods',{}).get(str(p)))
                    previous=text(cells.get(p))
                    if '不发放' not in current or '不发放' in previous:continue
                    departure=as_date(v.get(role+'最后工作日') if '招聘负责人离职' in current or '协助招聘人离职' in current else v.get('最后工作日'))
                    if yyyymm(departure)!=month:continue
                    n=next((n for n in source_nodes if n['role']==role and n['label']==NODES[i]),None)
                    if n:cancelled.append(Decimal(str(n['amount'])))
                value=money(min(entitled,sum(cancelled)))
                award['cancelledBalances'].append({'role':role,'amount':value,'currency':award['currency'],'month':month,'source':schedule.get('ref'),'basis':'本月新取消的未发分期；不重复冲减本月发放'})
        for node in award['nodes']:
            col=next(p for c,p,i in roles[node['role']] if NODES[i]==node['label'])
            raw=schedule.get('periods',{}).get(str(col))
            node['scheduledMonth']=period(raw) if raw is not None else node['dueMonth']
            node['scheduleText']=raw if raw is not None else ''
            node['scheduleSource']=schedule.get('ref')
            node['scheduleBasis']='线下安排还原' if raw is not None else '规则到期'
        award['scheduledTotal']=money(sum(Decimal(str(n['amount'])) for n in award['nodes']))
        award['currentAmount']=money(sum(Decimal(str(n['amount'])) for n in award['nodes'] if n['scheduledMonth']==month))
        if history:
            allocations=[]
            for role in roles:
                amount=(number(cells.get(38 if role=='招聘负责人' else 45 if role=='协助招聘人' else 61)) or Decimal(0)) if not opening['reprice'] else next((Decimal(str(t['allocatedAmount'])) for t in gross['recipientTotals'] if t['role']==role),Decimal(0))
                planned=sum(Decimal(str(n['amount'])) for n in award['nodes'] if n['role']==role)
                difference=money(planned-amount)
                allocations.append({'role':role,'allocatedAmount':money(amount),'scheduledAmount':money(planned),'roundingDifference':difference if abs(difference)<=.04 else None,'scheduleAdjustment':difference if abs(difference)>.04 else 0})
            award['recipientTotals']=allocations
            award['roundingDifference']=money(sum(t['roundingDifference'] or 0 for t in allocations))
        award['historyStatus']='期初已安排，实际支付未核实' if history else '无期初分期'
