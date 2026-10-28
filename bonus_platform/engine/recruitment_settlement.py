"""Rule-derived installments with explicit, evidenced scheduling operations.

No current result workbook is read here. Opening schedules preserve prior-month
arrangements; current entitlements are always recalculated from adopted facts.
"""
from copy import deepcopy
import hashlib
from decimal import Decimal
import json
import re
from uuid import uuid4
from .recruitment_time import now as recruitment_now
from .recruitment_awards import award, money, number, NODES, ensure_calculated
from .recruitment_draft_sources import text, digest
from .recruitment_opening import period, COLUMNS
from .models import as_date, yyyymm


def approved_basis(state,source_id,row_id=None):
    source=next((s for s in state['sources'] if s['id']==source_id and s.get('active',True) and not s.get('error') and not s.get('comparisonOnly')),None)
    if not source:raise ValueError('请选择原始材料或审批依据；核对结果不能作为处理依据')
    if source.get('attachment'):
        active={o['id'] for o in state.get('operations',[]) if o.get('active')}
        reviews=[r for r in state.get('reviewEntries',[]) if r['sourceId']==source_id and (not r.get('operationId') or r['operationId'] in active)]
        applicable=[r for r in reviews if not row_id or row_id in r.get('rowIds',[])]
        review=applicable[-1] if applicable else {}
        if not reviews or reviews[-1].get('status')!='已认可' or review.get('status')!='已认可' or not review.get('scopeChecked') or row_id and row_id not in review.get('rowIds',[]):
            raise ValueError('请先在审批审阅中确认最终意见和本人的适用范围')
    return source


def capture_confirmed_installments(parent):
    records={r['originKey']:dict(r) for r in parent.get('confirmedInstallments',[])}
    month=parent['month']
    for row in parent['rows']:
        for kind in ('recruitment','referral'):
            for node in row['calculation'][kind]['nodes']:
                if node.get('externalResultId'):continue
                scheduled=node.get('scheduledMonth',node.get('dueMonth'))
                if (scheduled!=month and not node.get('openingLocked')) or not scheduled or scheduled>month or node.get('amount') is None:continue
                origin=node.get('originKey') or digest(f"{row['id']}|{kind}|{node['id']}|{month}")
                records.setdefault(origin, {**{k:node.get(k) for k in (
                    'role','label','recipientId','recipientName','currency','amount','dueDate','dueMonth','adjustmentId','settlementRecoveryKey',
                    'settlementFingerprint','openingSource')},
                    'originKey':origin,'nodeId':node['id'],'rowId':row['id'],'kind':kind,
                    'scheduledMonth':scheduled,'confirmedMonth':scheduled,'parentRevision':parent['revision']})
    return list(records.values())


def opening_installments(state,row,kind,history,cells,computed):
    facts=[dict(f) for f in state.get('confirmedInstallments',[]) if f['rowId']==row['id'] and f['kind']==kind
           and f['scheduledMonth']<state['month'] and not f.get('adjustmentId')]
    by_stage={(f['role'],f['label']):f for f in facts};conflicts=[]
    aliases={'人民币':'人民币','RMB':'人民币','CNY':'人民币','欧元':'欧元','EUR':'欧元',
             '美元':'美元','USD':'美元','捷克克朗':'捷克克朗','CZK':'捷克克朗'}
    from .recruitment_drafts import staff_id
    for role,columns in COLUMNS[kind].items():
        for c,p,i in columns:
            amount=number(cells.get(c));month=period(cells.get(p))
            if not amount or not month or month>=state['month']:continue
            node=next((n for n in computed['nodes'] if n['role']==role and n['label']==NODES[i]),{})
            id_col,name_col={'招聘负责人':(22,23),'协助招聘人':(24,25),'推荐人':(59,58)}[role]
            currency=aliases.get(text(cells.get(56)).upper()) or computed['currency']
            if kind=='referral' and '捷克' in text(cells.get(70)):currency='捷克克朗'
            fact={'rowId':row['id'],'kind':kind,'role':role,'label':NODES[i],'nodeId':node.get('id') or digest(row['id']+'|'+kind+'|'+role+'|'+str(i)),
                  'amount':float(amount),'currency':currency,'scheduledMonth':month,'openingSource':history['ref'],
                  'recipientId':staff_id(cells.get(id_col)),
                  'recipientName':text(cells.get(name_col)),
                  'dueDate':node.get('dueDate',''),'dueMonth':node.get('dueMonth',month)}
            fact['originKey']=digest(json.dumps([row['id'],kind,role,NODES[i],month,history['ref']],sort_keys=True,ensure_ascii=False))
            key=(role,NODES[i]);previous=by_stage.get(key)
            if previous:
                keys=('amount','currency','scheduledMonth','recipientId')
                if any(str(previous.get(k,'')).casefold()!=str(fact.get(k,'')).casefold() for k in keys):
                    conflicts.append({'type':'opening_conflict','factLabel':NODES[i],'role':role,'amount':fact['amount'],'source':history['ref'],'sourceArrangement':fact,'reason':'平台确认安排与期初台账不一致，请核对原币种、金额、领取人和月份'})
                continue
            facts.append(fact);by_stage[key]=fact
    return facts,conflicts


def describe_recoveries(row, kind, facts, rule, computed, rule_hash, state=None):
    state=state or {}
    notes=[]; sources=[]
    source_by_id={s['id']:s for s in state.get('sources',[])}
    for history in row.get('history',[]):
        ref=history['ref']; source=source_by_id.get(ref.get('sourceId'),{})
        sources.append({'sourceRef':ref,'contentDigest':source.get('contentDigest',source.get('id')),
                        'active':source.get('active',True),'error':source.get('error'),
                        'historyDigest':hashlib.sha256(json.dumps(history.get('cells',[]),sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()})
        for cell in history.get('cells',[]):
            if cell.get('label','').split(' / ')[-1].endswith('备注') and text(cell.get('value')):
                notes.append({'text':text(cell['value']),'sourceRef':ref,'column':cell.get('column'),'label':cell.get('label','')})
    if text(row['values'].get('人工备注')) and not any(n['text']==text(row['values']['人工备注']) for n in notes):
        notes.append({'text':text(row['values']['人工备注']),'sourceRef':row.get('provenance',{}).get('人工备注',{}),'label':'人工备注'})
    values={k:v for k,v in row['values'].items() if k not in {'核算月份'} and v not in (None,'')}
    rule_facts={k:rule.get(k) for k in ('total','currency','standard','cycle','channelFactor','recipientTotals','approvalDecision')}
    rule_facts.update(ruleHash=rule_hash,version=row['rule']['version'],values=values,
                      unresolvedFields=row.get('unresolvedFields',[]))
    for r in computed['recoveries']:
        history=[f for f in facts if f['role']==r['role'] and f['amount'] and (not r.get('factLabel') or f['label']==r['factLabel'])
                 and (r['type'] not in {'overage','unallocated_balance'} or f['currency']==rule['currency'])]
        snapshot=[{k:f.get(k) for k in ('originKey','label','amount','currency','recipientId','recipientName','scheduledMonth','openingSource')} for f in history]
        if r['type']=='opening_conflict':
            for f in snapshot:f['basisLabel']='平台确认安排'
            snapshot.append({k:r['sourceArrangement'].get(k) for k in ('originKey','label','amount','currency','recipientId','recipientName','scheduledMonth','openingSource')})
            snapshot[-1]['basisLabel']='期初台账'
        identity=[row['id'],kind,r['role'],r['type'], sorted(f.get('originKey') or f['nodeId'] for f in history)]
        r['key']=hashlib.sha256(json.dumps(identity,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        r['fingerprint']=hashlib.sha256(json.dumps([{'contractVersion':2,'notes':notes,'sources':sources},snapshot,rule_facts],sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
        payees={(f.get('recipientId',''),f.get('recipientName',''),f['currency']) for f in history}
        payee=next(iter(payees)) if len(payees)==1 else ('','','')
        r.setdefault('currency',payee[2]);r.setdefault('recipientId',payee[0]);r.setdefault('recipientName',payee[1])
        total=next((t['allocatedAmount']+t['roundingDifference'] for t in rule['recipientTotals'] if t['role']==r['role']),0)
        r.update(rowId=row['id'],kind=kind,name=row['values'].get('姓名'),openingFacts=snapshot,originalNotes=notes,sourceContentDigests=sources,
                 historyAmount=money(sum(Decimal(str(f['amount'])) for f in history)),currentAmount=total,
                 currentRule={'total':rule['total'],'roleAmount':total,'currency':rule['currency'],'version':row['rule']['version']},
                 signedAmount=None if r['type']=='opening_conflict' else r['amount'] if r['type']=='unallocated_balance' else -r['amount'],
                 adjustmentAllowed=r['type']!='opening_conflict')
        if r['type']=='opening_conflict':r['correctionReviewReason']='平台确认安排与期初台账不一致，请先核对两份来源，不能据此推导补扣金额'


def historical_cancellation(state, row, kind, recovery, opening, cells):
    """An award already cancelled in the adopted ledger is not a new recovery.

    Keep its original amount and unverified execution status. A current change,
    explicit correction, conflicting opening or current arrangement still needs
    monthly review; free-text notes never establish that a deduction was paid.
    """
    if (recovery['type']!='removed_installment' or not row.get('frozenRecruitmentFacts')
            or not opening or not opening.get('isBaseline')
            or sum(bool(h.get('isBaseline')) for h in row.get('history',[]))!=1
            or recovery['currentAmount']!=0):return False
    source_id=opening['ref']['sourceId']
    if state.get('baseline')!=source_id or not any(s['id']==source_id and s.get('active',True)
            and not s.get('error') and not s.get('comparisonOnly') for s in state.get('sources',[])):return False
    total_column={'招聘负责人':38,'协助招聘人':45,'推荐人':61}[recovery['role']]
    if number(cells.get(total_column))!=0:return False
    facts=recovery['openingFacts']
    if not facts or any(not f.get('scheduledMonth') or f['scheduledMonth']>=state['month']
                       or (f.get('openingSource') or {}).get('sourceId')!=source_id for f in facts):return False
    if any(number(cells.get(c)) and period(cells.get(p)) and period(cells.get(p))>=state['month']
           for c,p,_ in COLUMNS[kind][recovery['role']]):return False
    if any(e.get('active',True) for e in row.get('edits',[])):return False
    if any(e.get('rowId')==row['id'] and e.get('active',True) for e in state.get('edits',[])):return False
    if any(d.get('kind')==kind for d in row.get('awardDecisions',[])):return False
    ops={o['id'] for o in state.get('operations',[]) if o.get('active')}
    return not any(r.get('rowId')==row['id'] and r.get('kind')==kind and r.get('operationId') in ops
                   for key in ('installmentPlans','adjustmentDrafts','specialAdjustments','eligibilityExceptions')
                   for r in state.get(key,[]))


def recovery_issues(recoveries, month):
    return [{'accountingMonth':None if r.get('historyOnly') else month,'reason':r['reason'],'recovery':True,
             **({'historyOnly':True} if r.get('historyOnly') else {})} for r in recoveries]


def apply_settlement(state,row,result):
    from .recruitment_drafts import staff_id
    month=state['month'];v=row['values'];baseline=state.get('settlement',{}).get('baselineId')
    h=next((h for h in row.get('history',[]) if h['ref']['sourceId']==baseline),None)
    cells={c['column']:c['value'] for c in h['cells']} if h else {}
    active={o['id'] for o in state.get('operations',[]) if o.get('active')}
    plans={p['nodeId']:p for p in state.get('installmentPlans',[]) if p.get('operationId') in active}
    for kind in ('recruitment','referral'):
        original=result[kind]
        from .recruitment_special import cutoff, evaluation_date
        policy=cutoff(state,kind)
        computed=award(row,kind,month,evaluate_employment=False,cutoff_policy=policy)
        rule_basis=deepcopy(computed)
        computed['eligibilityReasons']=original['reasons']
        computed['cancelledBalances']=[];computed['recoveries']=[]
        computed['openingSource']=h['ref'] if h else None
        facts,opening_conflicts=opening_installments(state,row,kind,h,cells,computed)
        computed['recoveries'].extend(opening_conflicts)
        from .recruitment_business_basis import historical_arrangements_complete
        # Fully arranged, unchanged opening awards do not need repricing under
        # today's catalog. New decisions, plans or conflicting opening evidence
        # still follow normal reconciliation. This does not assert bank payment.
        if (h and not opening_conflicts and historical_arrangements_complete(row,kind,month)
                and v.get('核算范围')!='不纳入核算'
                and not any(e.get('active',True) and e['field'].startswith('推荐人')
                            for e in row.get('edits',[]) if kind=='referral')
                and not any(d.get('kind')==kind for d in row.get('awardDecisions',[]))
                and not any(p.get('rowId')==row['id'] and p.get('kind')==kind
                            and p.get('operationId') in active for p in state.get('adjustmentDrafts',[]))
                and not any(n['id'] in plans for n in computed['nodes'])):
            nodes=[]
            for fact in facts:
                nodes.append({**fact,'id':fact['nodeId'],'rowId':row['id'],
                    'dueMonth':fact.get('dueMonth') or fact['scheduledMonth'],
                    'dueDate':fact.get('dueDate') or '', 'issues':[],
                    'status':'期初已安排','timing':'往期安排','openingLocked':True,
                    'openingAmount':fact['amount'],'amountBasis':'承接已完整安排的上月历史金额',
                    'scheduleText':'历史分期已完整安排，保留原金额；实际支付未核实',
                    'paidAmount':None,'paymentStatus':'未核实','paymentReady':False})
            total=money(sum(Decimal(str(n['amount'])) for n in nodes))
            currencies={n['currency'] for n in nodes}
            role_totals=[{'role':role,'allocatedAmount':money(sum(n['amount'] for n in nodes if n['role']==role)),
                         'scheduledAmount':money(sum(n['amount'] for n in nodes if n['role']==role)),
                         'roundingDifference':0} for role in COLUMNS[kind] if any(n['role']==role for n in nodes)]
            computed.update(total=total,nodes=nodes,issues=[],recoveries=[],accountingIssues=[],
                eligibilityReasons=[],currentAmount=0,scheduledTotal=total,roundingDifference=0,
                currency=next(iter(currencies)) if len(currencies)==1 else computed['currency'],recipientTotals=role_totals,
                historyRetained=True,historyBasis=h['ref'],
                reasons=['上月台账分期均已明确安排在往期，承接原历史金额'])
            result[kind]=computed
            continue
        if (v.get('核算范围')=='不纳入核算' or computed.get('approvalDecision')) and not facts:
            result[kind]=original;continue
        for role,columns in COLUMNS[kind].items():
            current=[n for n in computed['nodes'] if n['role']==role]
            locked=[]
            for fact in (f for f in facts if f['role']==role):
                n=next((n for n in current if n['label']==fact['label']),None)
                source=fact.get('openingSource') or {'confirmedMonth':fact['confirmedMonth'],'parentRevision':fact['parentRevision']}
                if n is None:
                    if computed['total'] is not None:
                        computed['recoveries'].append({'type':'removed_installment','factLabel':fact['label'],'role':role,'amount':fact['amount'],'source':source,'reason':'往期已有安排，现规则不再形成该分期，需核对补扣'})
                    n={'id':fact['nodeId'],'rowId':row['id'],'role':role,'label':fact['label'],
                       'dueDate':fact.get('dueDate') or '', 'dueMonth':fact.get('dueMonth'),
                       'issues':[],'timing':'往期安排','paidAmount':None,'paymentStatus':'未核实','paymentReady':False}
                    computed['nodes'].append(n);current.append(n)
                elif (fact['recipientId'] or fact['recipientName']) and (text(n['recipientId']).casefold()!=text(fact['recipientId']).casefold() or (not n['recipientId'] and n['recipientName']!=fact['recipientName'])):
                    computed['recoveries'].append({'type':'recipient_changed','factLabel':fact['label'],'role':role,'amount':fact['amount'],'source':source,'reason':'往期已确认安排的领取人与当前资料不同，请核对补扣'})
                if computed['total'] is not None and fact['currency']!=computed['currency']:
                    computed['recoveries'].append({'type':'currency_changed','factLabel':fact['label'],'role':role,'amount':fact['amount'],'source':source,'reason':'往期安排币种与当前规则币种不同，请核对；不能跨币种扣减余额'})
                current_id=staff_id(n.get('recipientId')).removeprefix('海外-');historical_id=staff_id(fact['recipientId']).removeprefix('海外-')
                if fact['scheduledMonth']<month and current_id and historical_id and current_id!=historical_id:
                    n['issues']=[issue for issue in n['issues'] if not issue.startswith(role+'：')]
                n.update(**{k:fact[k] for k in ('amount','currency','recipientId','recipientName','scheduledMonth')},
                         openingAmount=fact['amount'],openingLocked=True,openingSource=source,
                         status='期初已安排',eligibilityReasons=[],scheduleText='保留已确认安排；实际支付未核实',
                         amountBasis='期初已安排分期，支付未核实')
                if fact.get('originKey'):n['originKey']=fact['originKey']
                n.pop('planningIssue',None);locked.append(n)
            if locked and computed['total'] is not None:
                total=next((Decimal(str(t['allocatedAmount'])) for t in computed['recipientTotals'] if t['role']==role),Decimal(0))
                tail=next((Decimal(str(t['roundingDifference'])) for t in computed['recipientTotals'] if t['role']==role),Decimal(0))
                rest=total+tail-sum((Decimal(str(n['amount'])) for n in locked if n['currency']==computed['currency']),Decimal(0))
                payees={(n['recipientId'].casefold(),n['recipientName'],n['currency']) for n in locked}
                corrections=[f for f in state.get('confirmedInstallments',[]) if f['rowId']==row['id'] and f['kind']==kind
                    and f.get('adjustmentId') and f.get('settlementRecoveryKey') and f['scheduledMonth']<month
                    and f['role']==role and f['currency']==computed['currency'] and f.get('recipientId')
                    and payees=={(f['recipientId'].casefold(),f['recipientName'],f['currency'])}]
                rest-=sum((Decimal(str(f['amount'])) for f in corrections),Decimal(0))
                remaining=[n for n in current if not n.get('openingLocked')]
                if rest>0 and not remaining:
                    computed['recoveries'].append({'type':'unallocated_balance','confirmedCorrectionsIncluded':bool(corrections),'role':role,'amount':money(rest),'source':locked[0]['openingSource'],
                        'currency':computed['currency'],'recipientId':text(v.get(role+'工号')),'recipientName':text(v.get(role+'姓名')),
                        'reason':f'往期分期已确认，重新核算后尚有 {money(rest):.2f} {computed["currency"]} 未安排，请核对补发'})
                if rest<0:
                    if any(t['role']==role for t in computed['recipientTotals']):
                        computed['recoveries'].append({'type':'overage','confirmedCorrectionsIncluded':bool(corrections),'role':role,'amount':money(-rest),'source':locked[0]['openingSource'],'reason':'期初已安排金额超过当前规则总额，需核对补扣'})
                    rest=Decimal(0)
                weights=sum(Decimal(str(n['amount'])) for n in remaining);allocated=Decimal(0)
                for n in remaining:
                    value=rest-allocated if n is remaining[-1] else Decimal(str(money(rest*Decimal(str(n['amount']))/weights))) if weights else Decimal(0)
                    n.update(amount=float(value),amountBasis='规则总额扣除期初净安排后的余额' if corrections else '规则总额扣除期初已安排金额后的余额');allocated+=value
            cancelled=Decimal(0)
            for n in current:
                if n.get('openingLocked'):continue
                n['scheduledMonth']=n['dueMonth'];n.setdefault('amountBasis','按适用制度计算')
                n['scheduleBasis']='规则到期';n['scheduleText']='';n['openingAmount']=next((float(number(cells.get(c)) or 0) for c,p,i in columns if NODES[i]==n['label']),None) if h else None
                if n['dueMonth'] and n['dueMonth']<month:
                    n['scheduledMonth']=None;n['status']='往期未安排';n['planningIssue']='往期到期未安排，核对补发依据'
                i=NODES.index(n['label']);last=as_date(v.get('最后工作日'));recipient_last=as_date(v.get(role+'最后工作日'));due=as_date(n.get('dueDate'));probation=as_date(v.get('转正日期'))
                reason='；'.join(n.get('eligibilityReasons',[]))
                at=evaluation_date(policy,kind,due,month) if policy.get('id') else due
                if last and (not at or last<at or (not policy.get('id') or policy['mode']=='due') and i==3 and probation and yyyymm(last)==yyyymm(probation)):
                    reason='候选人在该分期到期前离职' if i!=3 else '候选人转正前或转正当月离职'
                if recipient_last and at and recipient_last<at:reason='领取人在该分期到期前离职'
                if reason:
                    n.update(scheduledMonth=None,status='按规则不发',scheduleText=reason,scheduleBasis='在职规则')
                    if yyyymm(recipient_last if reason.startswith('领取人') else last)==month:cancelled+=Decimal(str(n['amount']))
                plan=plans.get(n['id'])
                pending_text=next((text(cells.get(p)) for c,p,j in columns if j==i),'')
                # Only an explicit previous-month pending-probation instruction
                # can roll forward automatically. Refusals/deferrals and blank
                # schedules require their own basis, never the comparison file.
                if (not plan and h and kind=='recruitment' and v.get('标签分类')=='国内' and i==3
                        and n.get('planningIssue') and not reason and not n['issues'] and not computed['recoveries']
                        and ('未转正' in pending_text or '待转正' in pending_text) and '待发' in pending_text
                        and not any(token in pending_text for token in ('不发','不享受','暂缓','离职','取消'))):
                    n.pop('planningIssue',None)
                    n.update(scheduledMonth=month,status='已安排',scheduleBasis='上月待转正余额承接',
                             scheduleText='上月明确待转正发放，本次资料已提供实际转正日期',scheduleSource=h['ref'])
                if plan:
                    manual=plan.get('basisType')=='manual'
                    try:source_valid=manual or bool(approved_basis(state,plan['sourceId'],row['id']))
                    except ValueError:source_valid=False
                    if not source_valid:
                        n.update(scheduledMonth=None,status='依据已失效');n['issues'].append('安排依据已停用')
                    elif plan['action']=='schedule':
                        if reason or not n['dueMonth'] or plan['month']<n['dueMonth'] or computed['total'] is None or n['issues']:
                            n.update(scheduledMonth=None,status='安排需重新核对');n['issues'].append('资料更新后不满足原发放安排条件')
                        else:n.pop('planningIssue',None);n.update(scheduledMonth=plan['month'],status='已安排',scheduleBasis='手工调整发放月份' if manual else '已核对的发放安排',scheduleText=plan['reason'],scheduleSource={'sourceId':plan['sourceId']})
                    elif plan['action']=='defer':n.pop('planningIssue',None);n.update(scheduledMonth=None,status='暂缓安排',scheduleBasis='手工暂缓' if manual else '有依据暂缓',scheduleText=plan['reason'],scheduleSource={'sourceId':plan['sourceId']})
                    elif plan['action']=='reset':pass
            if kind=='recruitment':computed['cancelledBalances'].append({'role':role,'amount':money(cancelled) if computed['total'] is not None else None,'currency':computed['currency'],'month':month,
                'basis':'奖金总额尚不可计算，取消余额待核' if computed['total'] is None else '按候选人及领取人的到期任职状态计算'})
        describe_recoveries(row,kind,facts,rule_basis,computed,result.get('ruleHash'),state)
        for recovery in computed['recoveries']:
            if (not any(r['type']=='opening_conflict' and r['role']==recovery['role'] for r in computed['recoveries'])
                    and historical_cancellation(state,row,kind,recovery,h,cells)):
                recovery['historyOnly']=True
        computed['accountingIssues']=recovery_issues(computed['recoveries'],month)
        computed['scheduledTotal']=money(sum(Decimal(str(n['amount'])) for n in computed['nodes'])) if computed['total'] is not None and len({n['currency'] for n in computed['nodes']})<=1 else None
        computed['currentAmount']=money(sum(Decimal(str(n['amount'])) for n in computed['nodes'] if n.get('scheduledMonth')==month)) if computed['total'] is not None else None
        result[kind]=computed


def validation(state):
    problems=[]
    for row in state['rows']:
        for kind in ('recruitment','referral'):
            a=row['calculation'][kind]
            if row['values'].get('核算范围')=='不纳入核算' and not a.get('accountingIssues'):continue
            reasons=list(a['issues'])+[i['reason'] for i in a.get('accountingIssues',[]) if i['accountingMonth']==state['month']]
            if a['total'] is None:reasons.append('缺少可计算的规则或事实')
            reasons += [x['reason'] for x in a.get('recoveries',[]) if not x.get('historyOnly')]
            for node in a['nodes']:
                if node.get('scheduledMonth',node['dueMonth'])==state['month'] or node.get('adjustmentId') and node.get('accountingMonth')==state['month']:reasons+=node['issues']
                if node.get('planningIssue') and node.get('amount') and node.get('status')!='按规则不发':reasons.append(node['planningIssue'])
            if reasons:problems.append({'rowId':row['id'],'name':row['values'].get('姓名'),'kind':kind,'reasons':list(dict.fromkeys(reasons))})
    refs={s['id'] for s in state['sources'] if s.get('comparisonOnly')}
    contaminated=[e for e in state.get('edits',[]) if e.get('active',True) and e.get('evidenceId') in refs]
    return {'passed':bool(state.get('strictInputs') and state.get('baseline')) and not problems and not contaminated,
            'problems':problems,'problemCount':len(problems),'referenceDependentEdits':len(contaminated),
            'basis':'按规则检查采用事实、分期资格和依据；不以线下金额一致代替规则通过'}


def preview_plan(store,month,payload):
    with store._lock(month) as folder:
        state=ensure_calculated(store.read(month));store._check(state,payload.get('revision'))
        if not state.get('settlement',{}).get('baselineId'):raise ValueError('请先在独立试算批次中选择期初')
        row=next((r for r in state['rows'] if r['id']==payload.get('rowId')),None)
        if not row:raise ValueError('人员不存在')
        node=next((n for k in ('recruitment','referral') for n in row['calculation'][k]['nodes'] if n['id']==payload.get('nodeId')),None)
        if not node or node.get('openingLocked'):raise ValueError('不能改写期初已安排分期，请通过补扣流程核对')
        if node.get('adjustmentId'):raise ValueError('补发／扣回请在奖金调整记录中撤销后重新填写')
        if set(payload)-{'revision','rowId','nodeId','action','month','reason','sourceId','basisType'}:raise ValueError('分期安排不能输入或覆盖奖金金额')
        manual=payload.get('basisType')=='manual'
        if manual and payload.get('sourceId'):raise ValueError('手工调整不能同时标记来源文件')
        action=payload.get('action');target=payload.get('month')
        if action not in {'schedule','defer','reset'}:raise ValueError('请选择发放、暂缓或恢复规则安排')
        if not manual:
            if not text(payload.get('reason')):raise ValueError('请填写具体处理依据')
            approved_basis(state,payload.get('sourceId'),row['id'])
        if action=='schedule':
            if type(target) is not int or not period(target) or target<month:raise ValueError('安排月份不能早于当前核算月')
            if not node.get('dueMonth') or target<node['dueMonth']:raise ValueError('未满足规则到期条件，不能提前发放')
            if node.get('status')=='按规则不发' or node['issues']:raise ValueError('该分期仍有资格或资料问题，请先处理：'+'；'.join(node['issues'] or [node['scheduleText']]))
        token=uuid4().hex
        result={'id':token,'revision':state['revision'],'rowId':row['id'],'nodeId':node['id'],'action':action,'month':target,
                'basisType':'manual' if manual else 'source',
                'reason':{'schedule':'手工调整发放月份','defer':'手工暂缓发放','reset':'手工恢复原安排'}[action] if manual else text(payload['reason']),
                'sourceId':'' if manual else payload['sourceId'],
                'name':row['values'].get('姓名'),'role':node['role'],'label':node['label'],'amount':node['amount'],'currency':node['currency'],'beforeMonth':node.get('scheduledMonth',node['dueMonth'])}
        store._write(folder/'plan_previews'/f'{token}.json',result);return result


def apply_plan(store,month,revision,token):
    if not re.fullmatch('[a-f0-9]{32}',token):raise ValueError('安排预览不存在')
    with store._lock(month) as folder:
        state=store.read(month)
        if token in state.get('appliedPlanPreviews',[]):return state
        store._check(state,revision);path=folder/'plan_previews'/f'{token}.json'
        if not path.is_file():raise ValueError('安排预览不存在')
        plan=json.loads(path.read_text());store._check(state,plan['revision'])
        if plan.get('basisType')!='manual':approved_basis(state,plan['sourceId'],plan['rowId'])
        op={'id':uuid4().hex,'month':month,'active':True,'label':'分期安排','at':recruitment_now().isoformat(timespec='seconds')}
        state.setdefault('operations',[]).append(op);state['redoOperations']=[]
        state.setdefault('installmentPlans',[]).append({k:v for k,v in {**plan,'operationId':op['id']}.items() if k not in {'id','amount','currency'}})
        state.setdefault('appliedPlanPreviews',[]).append(token)
        return store._save(folder,state)
