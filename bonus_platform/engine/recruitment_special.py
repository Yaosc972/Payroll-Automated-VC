"""Monthly manual or source-backed adjustments; never records actual payment."""
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import json
import math
import re
from uuid import uuid4

from .recruitment_time import now as recruitment_now
from .models import add_months, as_date
from .recruitment_reviews import evidence_check

ROLES = {'recruitment': ('招聘负责人', '协助招聘人'), 'referral': ('推荐人',)}
CONDITIONS = {'candidate_not_employed': '候选人不在职',
              'recipient_not_employed': '领取人不在职',
              'recipient_not_regularized': '推荐人未转正'}
MODES = {'due': '分期到期日', 'month_end': '核算月末', 'date': '指定核算日期'}


def active(state, key):
    ops={o['id'] for o in state.get('operations', []) if o.get('active')}
    revoked={r['recordId'] for r in state.get('specialRevocations', []) if r['operationId'] in ops}
    return [r for r in state.get(key, []) if r.get('operationId') in ops and r['id'] not in revoked]


def valid_source(state, record):
    if record.get('basisType')=='history':
        return all(any(s['id']==sid and s.get('active',True) and not s.get('error') and not s.get('comparisonOnly')
                       for s in state['sources']) for sid in record.get('sourceIds',[]))
    if record.get('basisType')=='manual':return True
    ids=[record.get('sourceId'), *record.get('attachmentIds', [])]
    ops={o['id'] for o in state.get('operations',[]) if o.get('active')}
    reviews=[r for r in state.get('reviewEntries',[]) if r['sourceId']==record.get('sourceId') and (not r.get('operationId') or r['operationId'] in ops)]
    if reviews and (reviews[-1].get('status')!='已认可' or not reviews[-1].get('scopeChecked')):return False
    if reviews and record.get('rowId') and reviews[-1].get('personScope') is not None:
        if record['rowId'] not in {p.get('rowId') for p in reviews[-1]['personScope']}:return False
    return all(any(s['id']==sid and s.get('active', True) and not s.get('error')
                   and not s.get('comparisonOnly') for s in state['sources']) for sid in ids)


def cutoff(state, kind):
    default={'mode':'due' if kind=='recruitment' else 'month_end', 'month':state['month']}
    record=next((r for r in reversed(active(state, 'cutoffPolicies'))
                 if r['month']==state['month'] and r['kind']==kind), None)
    if not record:return default
    return record if valid_source(state,record) else {**default, 'invalid':True}


def evaluation_date(policy, kind, due, month):
    mode=policy.get('mode') if policy else ('due' if kind=='recruitment' else 'month_end')
    if mode=='due':return due
    if mode=='date':return as_date(policy['date'])
    return add_months(datetime(month//100,month%100,1),1)-timedelta(days=1)


def fingerprint(award, base=True):
    if base and award.get('specialBaseFingerprint'):return award['specialBaseFingerprint']
    values={'total':award['total'],'currency':award['currency'],'issues':award['issues'],
            'nodes':[{**{k:n.get(k) for k in ('id','amount','currency','recipientId','recipientName','dueDate','eligibilityReasons','issues')},
                      'scheduledMonth':n.get('scheduledMonth',n.get('dueMonth'))}
                     for n in award['nodes'] if not n.get('adjustmentId')]}
    return hashlib.sha256(json.dumps(values,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def condition(reason):
    if '未转正' in reason and reason.startswith('推荐人'):return 'recipient_not_regularized'
    if ('不在职' in reason or '离职' in reason):
        return 'candidate_not_employed' if reason.startswith('候选人') else 'recipient_not_employed'
    return None


def apply_special(state, row, result):
    month=state['month']
    for kind in ROLES:
        award=result[kind]; signature=fingerprint(award)
        award['specialBaseFingerprint']=signature
        award.setdefault('accountingIssues',[])
        if cutoff(state,kind).get('invalid'):
            for n in award['nodes']:n['issues'].append('核算截点依据已失效，请重新核对口径')
        for record in active(state,'eligibilityExceptions'):
            if record['rowId']!=row['id'] or record['kind']!=kind or record['month']!=month:continue
            n=next((n for n in award['nodes'] if n['id']==record['nodeId']),None)
            if not n or not valid_source(state,record) or record['fingerprint']!=signature:
                issue='资格例外依据或计算事实已变化，请重新核对'
                award['accountingIssues'].append({'recordId':record['id'],'accountingMonth':record['month'],'reason':issue})
                if n:n['issues'].append(issue)
                continue
            reasons=list(dict.fromkeys(n.get('eligibilityReasons',[])+([n.get('scheduleText')] if n.get('scheduleBasis')=='在职规则' and n.get('scheduleText') else [])))
            remaining=[r for r in reasons if condition(r) not in record['conditions']]
            n['eligibilityReasons']=remaining
            n['exceptionId']=record['id']
            n['exceptionBasis']=record['reason']
            # Exceptions only remove the explicitly selected eligibility failures.
            # They do not remove missing facts, cancellation, deferral or early-payment guards.
            if (not remaining and not n['issues'] and not n.get('openingLocked') and not n.get('roleDecision')
                    and n['status']!='暂缓安排' and n.get('dueMonth') and n['dueMonth']<=month):
                manual=record.get('basisType')=='manual'
                n.update(scheduledMonth=month,status='手工安排发放' if manual else '按审批例外安排',scheduleText=record['reason'],
                         scheduleBasis='手工资格调整' if manual else '资格例外审批',scheduleSource={'sourceId':record['sourceId']})
                n.pop('planningIssue',None)
        adjustment_signature=fingerprint(award,base=False)
        for recovery in award.get('recoveries',[]):
            if recovery.get('type')=='unallocated_balance':
                identity=[row['id'],kind,recovery['role'],recovery['currency'],recovery['recipientId'].casefold(),adjustment_signature]
                recovery['key']=hashlib.sha256(json.dumps(identity,ensure_ascii=False).encode()).hexdigest()
        raw_recoveries=deepcopy(award.get('recoveries',[]))
        award['settlementRecoveries']=raw_recoveries
        confirmed_corrections=[f for f in state.get('confirmedInstallments',[]) if f['rowId']==row['id'] and f['kind']==kind
                               and f.get('adjustmentId') and f.get('settlementRecoveryKey')]
        for recovery in raw_recoveries:
            if recovery['type'] in {'unallocated_balance','opening_conflict'}:continue
            related=[r for r in raw_recoveries if r['type'] not in {'unallocated_balance','opening_conflict'}
                     and all(r[k]==recovery[k] for k in ('role','currency'))
                     and r['recipientId'].casefold()==recovery['recipientId'].casefold()]
            prior=[f for f in confirmed_corrections if all(f.get(k)==recovery[k] for k in ('role','currency'))
                   and f.get('recipientId','').casefold()==recovery['recipientId'].casefold()]
            if not prior:continue
            facts=[{k:f.get(k) for k in ('adjustmentId','amount','currency','role','recipientId','recipientName','scheduledMonth')} for f in prior]
            confirmed_total=sum((Decimal(str(f['amount'])) for f in prior),Decimal(0))
            gross=Decimal(str(recovery['signedAmount']))+(confirmed_total if recovery.get('confirmedCorrectionsIncluded') else Decimal(0))
            recovery.update(confirmedCorrections=facts,grossSignedAmount=float(gross))
            recovery['fingerprint']=hashlib.sha256(json.dumps([recovery['fingerprint'],facts],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            if len(related)==1 and recovery['recipientId'] and recovery['recipientName']:
                net=gross-confirmed_total
                recovery.update(signedAmount=float(net),amount=float(abs(net)))
                if net:recovery['reason']+=f'；计入已确认补扣后，剩余需{"扣回" if net<0 else "补发"} {abs(net):.2f} {recovery["currency"]}'
            else:
                recovery.update(adjustmentAllowed=False,signedAmount=None,
                    correctionReviewReason='同一领取人有多笔历史差异及已确认补扣，请在调整记录核对对应分期')
        for recovery in raw_recoveries:
            chain=[]
            for record in active(state,'specialAdjustments'):
                exact=record.get('settlementRecoveryKey')==recovery['key']
                candidate=(record.get('rowId')==row['id'] and record.get('kind')==kind
                    and all(record.get(k)==recovery.get(k) for k in ('role','currency')) and bool(recovery.get('recipientId'))
                    and record.get('recipientId','').casefold()==recovery['recipientId'].casefold())
                if not exact and not candidate:continue
                source_ids={record.get('sourceId'),*record.get('attachmentIds',[])}-{None,''}
                chain.append({**{k:record.get(k) for k in ('id','amount','currency','role','recipientId','recipientName','month','settlementFingerprint')},
                    'sourceValid':valid_source(state,record),'sourceContentDigests':[
                        [s['id'],s.get('contentDigest',s['id'])] for s in state['sources'] if s['id'] in source_ids]})
            recovery['historyFingerprint']=hashlib.sha256(json.dumps([recovery['fingerprint'],chain],sort_keys=True,ensure_ascii=False).encode()).hexdigest() if chain else recovery['fingerprint']
        for record in active(state,'specialAdjustments'):
            if record['rowId']!=row['id'] or record['kind']!=kind:continue
            confirmed=next((f for f in state.get('confirmedInstallments',[]) if f.get('adjustmentId')==record['id']),None)
            if confirmed:
                record={**record,**{k:confirmed[k] for k in ('amount','currency','recipientId','recipientName')},'month':confirmed['scheduledMonth']}
            invalid=[]
            if confirmed:
                if not valid_source(state,record):
                    invalid.append('已确认补扣的依据已失效，请重新核对')
                    award['accountingIssues'].append({'recordId':record['id'],'accountingMonth':month,'reason':invalid[-1]})
            elif record['month']>=month or record.get('settlementFingerprint'):
                if not valid_source(state,record):invalid.append('补扣依据已失效')
                linked=next((r for r in raw_recoveries if r.get('key')==record.get('settlementRecoveryKey')),None)
                unchanged=(linked and linked['fingerprint']==record.get('settlementFingerprint')) if record.get('settlementFingerprint') else record['fingerprint']==adjustment_signature
                if not unchanged:invalid.append('计算事实已变化，请核对是否重复补差')
            amount=record['amount']
            award['nodes'].append({'id':record['id'],'adjustmentId':record['id'],'rowId':row['id'],
                'role':record['role'],'recipientId':record['recipientId'],'recipientName':record['recipientName'],
                'label':'补发' if amount>0 else '扣回','amount':amount,'currency':record['currency'],
                'dueDate':'','dueMonth':record['month'],'scheduledMonth':None if invalid and not confirmed else record['month'],
                'status':'安排需重新核对' if invalid else '已纳入核算','timing':'本月到期' if record['month']==month else '后续安排',
                'issues':invalid,'paidAmount':None,'paymentReady':False,'paymentStatus':'未核实',
                'amountBasis':('手工补扣' if record.get('basisType')=='manual' else '审批补扣')+'，原规则金额保留',
                'scheduleBasis':'手工补扣' if record.get('basisType')=='manual' else '审批补扣',
                'scheduleText':record['reason'],'scheduleSource':{'sourceId':record['sourceId']},'lineRef':record['lineRef'],
                'linkedNodeId':record.get('nodeId'), 'accountingMonth':record['month'],
                'settlementRecoveryKey':record.get('settlementRecoveryKey'),
                'settlementFingerprint':record.get('settlementFingerprint')})
        for fact in state.get('confirmedInstallments',[]):
            if fact['rowId']!=row['id'] or fact['kind']!=kind or not fact.get('adjustmentId') or fact['scheduledMonth']>=month:continue
            if any(n.get('adjustmentId')==fact['adjustmentId'] for n in award['nodes']):continue
            award['nodes'].append({**{k:fact[k] for k in ('role','label','recipientId','recipientName','currency','amount','scheduledMonth','adjustmentId')},
                'id':fact['nodeId'],'rowId':row['id'],'originKey':fact['originKey'],'dueDate':fact.get('dueDate') or '',
                'dueMonth':fact.get('dueMonth'),'accountingMonth':fact['scheduledMonth'],'status':'期初已安排','timing':'往期安排',
                'settlementRecoveryKey':fact.get('settlementRecoveryKey'),'settlementFingerprint':fact.get('settlementFingerprint'),
                'openingLocked':True,'issues':[],'paidAmount':None,'paymentStatus':'未核实','paymentReady':False,
                'scheduleText':'保留已确认补扣安排；实际支付未核实','scheduleBasis':'平台确认安排'})
        confirmed_ids={f['adjustmentId'] for f in state.get('confirmedInstallments',[]) if f.get('adjustmentId')}
        remaining=[]
        for recovery in raw_recoveries:
            linked=[n for n in award['nodes'] if n.get('settlementRecoveryKey')==recovery['key'] and not n['issues']
                    and (recovery['type']=='unallocated_balance' or n.get('adjustmentId') not in confirmed_ids)
                    and n.get('scheduledMonth') and all(n.get(k)==recovery[k] for k in ('role','currency','recipientName'))
                    and n.get('recipientId','').casefold()==recovery['recipientId'].casefold()]
            if recovery['type']=='unallocated_balance':
                closed=[n for n in linked if (n.get('scheduledMonth')==month or n.get('adjustmentId') in confirmed_ids)
                        and n['amount']==recovery['amount']]
                if closed:recovery.update(resolution='adjusted',adjustmentIds=[n['adjustmentId'] for n in closed])
                else:remaining.append(recovery)
                continue
            if recovery.get('signedAmount')==0:
                recovery.update(resolution='adjusted',adjustmentIds=[f['adjustmentId'] for f in recovery.get('confirmedCorrections',[])])
                continue
            reviews=[r for r in active(state,'settlementReviews') if r['rowId']==row['id'] and r['kind']==kind and r['recoveryKey']==recovery['key']]
            retained=next((r for r in reversed(reviews) if r['fingerprint']==recovery.get('historyFingerprint',recovery['fingerprint']) and valid_source(state,r)),None)
            matched=[n for n in linked if recovery.get('adjustmentAllowed',True) and recovery.get('signedAmount') is not None and n.get('settlementFingerprint')==recovery['fingerprint']
                     and Decimal(str(n['amount']))*Decimal(str(recovery['signedAmount']))>0]
            handled=sum((Decimal(str(n['amount'])) for n in matched),Decimal(0))
            if retained:
                recovery.update(resolution='retained',reviewId=retained['id'])
                continue
            if handled and abs(handled)<=abs(Decimal(str(recovery['signedAmount']))):
                balance=Decimal(str(recovery['signedAmount']))-handled
                recovery.update(resolution='adjusted' if not balance else 'partial',adjustmentIds=[n['adjustmentId'] for n in matched])
                if not balance:continue
                recovery={**recovery,'originalAmount':recovery['amount'],'amount':float(abs(balance)),'signedAmount':float(balance),
                          'reason':recovery['reason']+f'；已安排部分补扣，剩余 {abs(balance):.2f} {recovery["currency"]}'}
            remaining.append(recovery)
        award['recoveries']=remaining
        for record in active(state,'settlementReviews'):
            if record['rowId']!=row['id'] or record['kind']!=kind:continue
            current=next((r for r in raw_recoveries if r['key']==record['recoveryKey']),None)
            if current and current.get('resolution')=='retained':continue
            if not valid_source(state,record) or current and current.get('historyFingerprint',current['fingerprint'])!=record['fingerprint']:
                award['accountingIssues'].append({'recordId':record['id'],'accountingMonth':month,
                    'reason':'历史安排核对所用资料或计算事实已变化，请重新核对'})
        award['accountingIssues']=[i for i in award['accountingIssues'] if not i.get('recovery')]+[
            {'accountingMonth':month,'reason':r['reason'],'recovery':True} for r in award['recoveries']]
        award['currentAmount']=float(sum((Decimal(str(n['amount'])) for n in award['nodes']
            if n.get('scheduledMonth',n.get('dueMonth'))==month),Decimal(0))) if award['total'] is not None else None


def ensure_history_signatures(state):
    if any('historyFingerprint' not in r for row in state.get('rows',[]) for kind in ROLES
           for r in row.get('calculation',{}).get(kind,{}).get('settlementRecoveries',[])):
        from .recruitment_awards import calculate_draft
        calculate_draft(state)
    return state


def context(state):
    ensure_history_signatures(state)
    records=[]
    for key,typ in [('specialAdjustments','adjustment'),('eligibilityExceptions','exception'),('cutoffPolicies','cutoff'),('settlementReviews','history')]:
        live={r['id'] for r in active(state,key)}
        for r in state.get(key,[]):
            confirmed=any(f.get('adjustmentId')==r['id'] for f in state.get('confirmedInstallments',[]))
            if r['month']>=state['month'] or typ=='history' or confirmed or r.get('settlementRecoveryKey'):
                nodes=[n for row in state['rows'] if row['id']==r.get('rowId') for n in row['calculation'][r['kind']]['nodes'] if n.get('adjustmentId')==r['id'] or n.get('exceptionId')==r['id'] or n['id']==r.get('nodeId')]
                issues=list(dict.fromkeys([i for n in nodes for i in n.get('issues',[])]+
                    [i['reason'] for row in state['rows'] if row['id']==r.get('rowId')
                     for i in row['calculation'][r['kind']].get('accountingIssues',[]) if i.get('recordId')==r['id']]))
                records.append({**r,'type':typ,'confirmed':confirmed,'active':r['id'] in live,'sourceValid':valid_source(state,r),'issues':issues})
    recoveries=[];pending_keys=set()
    for row in state['rows']:
        for kind in ROLES:
            award=row['calculation'][kind]
            current={r['key']:r for r in award.get('recoveries',[])}
            pending_keys.update((row['id'],kind,key) for key in current)
            for raw in award.get('settlementRecoveries',award.get('recoveries',[])):
                recovery=deepcopy(current.get(raw['key'],raw))
                recovery['relatedRecords']=[]
                for record in records:
                    exact=record.get('settlementRecoveryKey',record.get('recoveryKey'))==raw['key']
                    candidate=(record.get('rowId')==row['id'] and record.get('kind')==kind and record.get('type')=='adjustment'
                        and all(record.get(k)==raw.get(k) for k in ('role','currency')) and bool(raw.get('recipientId'))
                        and record.get('recipientId','').casefold()==raw['recipientId'].casefold())
                    if exact or candidate:recovery['relatedRecords'].append({**record,'relationship':'linked' if exact else 'candidate'})
                recovery['relatedConfirmedArrangements']=[f for f in state.get('confirmedInstallments',[])
                    if f.get('adjustmentId') and f['rowId']==row['id'] and f['kind']==kind and all(f.get(k)==raw.get(k) for k in ('role','currency'))
                    and bool(raw.get('recipientId')) and f.get('recipientId','').casefold()==raw['recipientId'].casefold()]
                recovery['paymentStatus']='未核实'
                recovery['amountEntry']='blank'
                recoveries.append(recovery)
    return {'revision':state['revision'],'month':state['month'],'conditions':CONDITIONS,
            'policies':{k:cutoff(state,k) for k in ROLES},'records':records,
            'historyRecoveries':recoveries,
            'recoveries':[r for r in recoveries if (r['rowId'],r['kind'],r['key']) in pending_keys]}


def reviewable_history(state, payload):
    if payload.get('outcome')!='retain':raise ValueError('请选择认可历史安排')
    row=next((r for r in state['rows'] if r['id']==payload.get('rowId')),None)
    if not row or payload.get('kind') not in ROLES:raise ValueError('人员或奖金类型不存在')
    award=row['calculation'][payload['kind']]
    r=next((r for r in award.get('recoveries',[]) if r['key']==payload.get('recoveryKey')),None)
    if not r or r['type']=='unallocated_balance':raise ValueError('历史差异已处理或已变化，请重新核对')
    if payload.get('fingerprint')!=r.get('historyFingerprint',r['fingerprint']):raise ValueError('历史差异事实已变化，请重新核对')
    if r.get('resolution')=='partial':raise ValueError('该历史差异已有部分补扣，请先撤销后再认可历史安排')
    source_ids={(f.get('openingSource') or {}).get('sourceId') for f in r['openingFacts'] if (f.get('openingSource') or {}).get('sourceId')}
    if not valid_source(state,{'basisType':'history','sourceIds':source_ids}):raise ValueError('历史安排来源已失效，请重新核对')
    return row,r


def preview(store, month, payload):
    from .recruitment_awards import calculate_draft, ensure_calculated, money
    from .recruitment_settlement import approved_basis, period
    with store._lock(month) as folder:
        before=ensure_history_signatures(ensure_calculated(store.read(month)));store._check(before,payload.get('revision'))
        typ=payload.get('type');kind=payload.get('kind')
        manual=payload.get('basisType')=='manual'
        if manual and (payload.get('evidence') or payload.get('sourceId')):raise ValueError('手工调整不能同时标记为审批调整')
        if typ not in {'adjustment','exception','cutoff','revoke','history'}:raise ValueError('处理类型无效')
        if typ!='revoke' and kind not in ROLES:raise ValueError('奖金类型无效')
        token=uuid4().hex; reviewed=None
        record={'id':uuid4().hex,'month':month,'kind':kind,'at':recruitment_now().isoformat(timespec='seconds')}
        if typ=='revoke':
            old=next((r for r in context(before)['records'] if r['id']==payload.get('recordId') and r['active']),None)
            if not old:raise ValueError('没有可撤销的当前或后续安排')
            if old.get('confirmed'):raise ValueError('已确认补扣保留为历史安排，请通过补发／扣回更正')
            key='specialRevocations';record.update(recordId=old['id'],rowId=old.get('rowId'),reason='撤销特殊安排')
        elif typ=='history':
            row,recovery=reviewable_history(before,payload)
            key='settlementReviews'
            sources=sorted({(f.get('openingSource') or {}).get('sourceId') for f in recovery['openingFacts'] if (f.get('openingSource') or {}).get('sourceId')})
            record.update(rowId=row['id'],name=row['values'].get('姓名'),recoveryKey=recovery['key'],
                fingerprint=recovery.get('historyFingerprint',recovery['fingerprint']),outcome='retain',basisType='history',
                sourceIds=sources,sourceId=sources[0] if sources else '',reason='认可历史安排；原规则金额保留，实际支付未核实',
                recovery=deepcopy(recovery))
        elif typ=='cutoff':
            if payload.get('month')!=month:raise ValueError('核算口径仅适用于当前月份')
            mode=payload.get('mode');date=payload.get('date','')
            if mode not in MODES:raise ValueError('请选择有效的核算截点')
            if mode=='date' and (not as_date(date) or str(date)[:7].replace('-','')!=str(month)):
                raise ValueError('指定核算日期必须在当前核算月内')
            if not manual and not str(payload.get('reason','')).strip():raise ValueError('请填写核算口径依据')
            source=None if manual else approved_basis(before,payload.get('sourceId'))
            key='cutoffPolicies';record.update(mode=mode,date=date if mode=='date' else '',
                sourceId=source['id'] if source else '',basisType='manual' if manual else 'source',
                reason='手工修改在职／转正判断日期' if manual else payload['reason'])
        else:
            reviewed=None if manual else evidence_check(store,before,payload.get('evidence'),True)
            row=next((r for r in before['rows'] if r['id']==payload.get('rowId')),None)
            if not row or row['values'].get('核算范围')=='不纳入核算' and not payload.get('recoveryKey'):raise ValueError('请选择本次核算范围内的人员')
            if reviewed and reviewed.get('personScope') is not None and row['id'] not in {p.get('rowId') for p in reviewed['personScope']}:
                raise ValueError('所选人员不在审批已核实范围内')
            line=record['id'] if manual else str(payload.get('lineRef','')).strip()
            if not line:raise ValueError('请填写审批条目编号，避免重复应用')
            award=row['calculation'][kind]
            record.update(rowId=row['id'],name=row['values'].get('姓名'),lineRef=line,
                fingerprint=fingerprint(award),basisType='manual' if manual else 'approval',
                sourceId=reviewed['sourceId'] if reviewed else '',pageNumbers=reviewed['pageNumbers'] if reviewed else [],
                attachmentIds=reviewed.get('attachmentIds',[]) if reviewed else [],
                reason=reviewed['note'] if reviewed else '手工调整发放资格')
            node=next((n for n in award['nodes'] if n['id']==payload.get('nodeId') and not n.get('adjustmentId')),None)
            if payload.get('nodeId') and not node:raise ValueError('对应分期不存在')
            record['nodeId']=node['id'] if node else None
            if typ=='adjustment':
                key='specialAdjustments';amount=payload.get('amount');target=payload.get('month')
                from .recruitment_external_results import effective as external_effective
                if row.get('externalOnly') or target==month and any(r['rowId']==row['id'] and r['kind']==kind and r['role']==payload.get('role') for r in external_effective(before)['latest']):
                    raise ValueError('该奖金已按体系外月度结果核定，请更正体系外结果表后上传，避免重复补扣')
                record['fingerprint']=fingerprint(award,base=False)
                if type(amount) not in (int,float) or not math.isfinite(amount) or not money(amount):raise ValueError('请输入非零有效补扣金额')
                if type(target) is not int or not period(target) or target<month:raise ValueError('纳入月份不能早于当前核算月')
                if payload.get('currency') not in {'人民币','欧元','美元','捷克克朗'}:raise ValueError('补扣币种无效')
                if award['currency'] and payload['currency']!=award['currency'] and not any(r['key']==payload.get('recoveryKey') and r['currency']==payload['currency'] for r in award.get('recoveries',[])):raise ValueError('补扣币种须与该奖金币种一致；币种有误请先更正原始资料')
                if payload.get('role') not in ROLES[kind]:raise ValueError('奖金角色无效')
                if not str(payload.get('recipientId','')).strip() or not str(payload.get('recipientName','')).strip():raise ValueError('请填写领取人姓名和工号')
                record.update(amount=money(amount),month=target,role=payload['role'],currency=payload['currency'],
                              recipientId=payload['recipientId'].strip(),recipientName=payload['recipientName'].strip(),
                              accountingStatus='included',paymentStatus='未核实',paymentReady=False)
                if manual:record['reason']='手工补发' if amount>0 else '手工扣回'
                blocked=next((r for r in award.get('settlementRecoveries',[]) if not r.get('adjustmentAllowed',True) and (r['type']!='opening_conflict' or r.get('resolution')!='retained')
                    and (payload.get('recoveryKey')==r['key'] or all(record[k]==r[k] for k in ('role','currency'))
                         and record['recipientId'].casefold()==r['recipientId'].casefold())),None)
                if blocked and (blocked['type']=='opening_conflict' or payload.get('recoveryKey')):raise ValueError(blocked['correctionReviewReason'])
                for r in award.get('settlementRecoveries',[]):
                    if not r.get('confirmedCorrections') or r.get('signedAmount') is None:continue
                    if not all(record[k]==r[k] for k in ('role','currency')) or record['recipientId'].casefold()!=r['recipientId'].casefold():continue
                    if (not r['signedAmount'] and record['amount']*r.get('grossSignedAmount',0)>0 or
                            record['amount']*r['signedAmount']>0 and abs(record['amount'])>abs(r['signedAmount'])):
                        raise ValueError('已有已确认补扣，不能超过剩余历史差额或重复纳入')
                matches=[r for r in award.get('recoveries',[]) if r.get('adjustmentAllowed',True) and r.get('recipientId') and r.get('recipientName')
                    and all(record[k]==r[k] for k in ('role','currency','recipientName'))
                    and record['recipientId'].casefold()==r['recipientId'].casefold()
                    and (not node or node['role']==record['role'])
                    and (record['amount']==r['amount'] if r['type']=='unallocated_balance' else
                         record['amount']*r['signedAmount']>0 and abs(record['amount'])<=abs(r['signedAmount']))]
                if payload.get('recoveryKey'):
                    matches=[r for r in matches if r['key']==payload['recoveryKey']]
                    if len(matches)!=1:raise ValueError('该历史差异已处理或补扣的金额、币种、角色、领取人不匹配，请重新核对')
                if not matches and any(r.get('signedAmount') is not None and r.get('resolution') in {'retained','adjusted'} and all(record[k]==r[k] for k in ('role','currency','recipientName'))
                    and record['recipientId'].casefold()==r['recipientId'].casefold() and record['amount']*r.get('grossSignedAmount',r['signedAmount'])>0
                    and abs(record['amount'])<=abs(r.get('grossSignedAmount',r['signedAmount'])) for r in award.get('settlementRecoveries',[])):
                    raise ValueError('该历史差异已有处理记录，请先撤销原处理')
                if len(matches)==1:
                    recovery=matches[0]
                    record['settlementRecoveryKey']=recovery['key']
                    if recovery['type']!='unallocated_balance':record['settlementFingerprint']=recovery['fingerprint']
                elif any(r['key']==payload.get('recoveryKey') for r in award.get('settlementRecoveries',[])):
                    raise ValueError('该历史差异已有处理记录，请先撤销原处理')
            else:
                key='eligibilityExceptions';conditions=payload.get('conditions')
                if payload.get('month')!=month:raise ValueError('资格例外仅适用于当前月份')
                if not node or node.get('openingLocked') or node.get('roleDecision'):raise ValueError('不能覆盖期初或已取消的分期')
                if not node.get('dueMonth') or node['dueMonth']>month:raise ValueError('未达到规则到期条件')
                if not isinstance(conditions,list) or not conditions or set(conditions)-set(CONDITIONS):raise ValueError('请选择具体例外条件')
                reasons=node.get('eligibilityReasons',[])+[node.get('scheduleText','')]
                if not set(conditions)<={condition(r) for r in reasons}:raise ValueError('所选条件不是本分期当前的资格障碍')
                record['conditions']=sorted(set(conditions))
            for old in active(before,key):
                if (old['sourceId'],old['rowId'],old['lineRef'])==(record['sourceId'],record['rowId'],record['lineRef']):
                    raise ValueError('同一审批条目已应用，不能重复提交；更正时先撤销原安排')
                if typ=='adjustment' and all(old.get(k)==record.get(k) for k in ('sourceId','rowId','kind','recipientId','month','amount','currency')):
                    raise ValueError('相同补扣已存在，不能重复纳入')
                if typ=='exception' and old['month']==month and old['nodeId']==node['id']:
                    raise ValueError('该分期已有资格例外，请先撤销后重新核对')
        after=deepcopy(before)
        after.setdefault('operations',[]).append({'id':token,'month':month,'active':True})
        after.setdefault(key,[]).append({**record,'operationId':token})
        calculate_draft(after)
        old={r['id']:r for r in before['rows']}; current=[];nodes=[]
        for r in after['rows']:
            for k,title in [('recruitment','招聘奖金'),('referral','内推奖金')]:
                a=old[r['id']]['calculation'][k];b=r['calculation'][k]
                common={'name':r['values'].get('姓名'),'rowId':r['id'],'kind':title}
                if a['currentAmount']!=b['currentAmount']:current.append({**common,'before':a['currentAmount'],'after':b['currentAmount'],'currency':b['currency']})
                previous={n['id']:n for n in a['nodes']};new={n['id']:n for n in b['nodes']}
                for nid in dict.fromkeys([*previous,*new]):
                    x=previous.get(nid);y=new.get(nid)
                    fields=('amount','currency','recipientId','recipientName','scheduledMonth','status','issues')
                    snap=lambda v:{f:v.get(f) for f in fields} if v else None
                    if snap(x)!=snap(y):nodes.append({**common,'label':(y or x)['label'],'before':snap(x),'after':snap(y)})
        result={'id':token,'revision':before['revision'],'month':month,'type':typ,'key':key,'record':record,
                'evidence':reviewed,'currentImpact':current,'nodeImpact':nodes,'people':len({n['rowId'] for n in nodes}),
                'historyImpact':record.get('recovery') if typ=='history' else None}
        store._write(folder/'special-previews'/f'{token}.json',result)
        return result


def apply_preview(store, month, revision, token):
    if not re.fullmatch('[0-9a-f]{32}',str(token)):raise ValueError('预览标识无效')
    with store._lock(month) as folder:
        state=store.read(month)
        if token in state.get('appliedSpecialPreviews',{}):return state
        store._check(state,revision)
        path=folder/'special-previews'/f'{token}.json'
        if not path.exists():raise ValueError('预览不存在，请重新核对')
        p=json.loads(path.read_text());store._check(state,p['revision'])
        if p['type']=='history':
            from .recruitment_awards import calculate_draft
            calculate_draft(state)
            reviewable_history(state,{**p['record'],'kind':p['record']['kind']})
        if p['evidence']:evidence_check(store,state,p['evidence'],True)
        from .recruitment_settlement import approved_basis
        if p['type']=='cutoff' and p['record'].get('basisType')!='manual':approved_basis(state,p['record']['sourceId'])
        op={'id':token,'month':month,'active':True,'at':recruitment_now().isoformat(timespec='seconds'),
            'label':{'adjustment':'手工补扣' if p['record'].get('basisType')=='manual' else '审批补扣','exception':'资格例外','cutoff':'核算截点','revoke':'撤销特殊安排','history':'认可历史安排'}[p['type']]}
        state.setdefault('operations',[]).append(op);state['redoOperations']=[]
        state.setdefault(p['key'],[]).append({**p['record'],'operationId':token})
        if p['evidence']:
            state.setdefault('reviewEntries',[]).append({**p['evidence'],'id':token,'operationId':token,'applied':True,'rowIds':[p['record']['rowId']]})
        state.setdefault('appliedSpecialPreviews',{})[token]=token
        return store._save(folder,store._rebuild(folder,state))
