"""Live review queue. Conclusions annotate differences; they never set money or payment."""
from collections import Counter
from datetime import datetime
from hashlib import sha256
import json

from .recruitment_awards import ensure_calculated
from .recruitment_attention import project as attention
from .recruitment_work_items import project as work_items
from .recruitment_reconcile import monthly_comparison, comparison_month, unavailable_comparison
from .recruitment_special import context as special_context


def fingerprint(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def active(state, entry):
    return not entry.get('operationId') or any(o['id'] == entry['operationId'] and o['active'] for o in state.get('operations', []))


def evidence_signature(state, source_id):
    source = next((s for s in state['sources'] if s['id'] == source_id and s.get('active', True) and not s.get('error')), None)
    if not source:
        return ''
    reviews = [{**r, 'operationActive': active(state, r)} for r in state.get('reviewEntries', []) if r['sourceId'] == source_id]
    return fingerprint([source, reviews])


def processing_records(state):
    sources = {s['id']: s for s in state['sources']}
    rows = {r['id']: r for r in state['rows']}
    result = []
    for r in state.get('reviewEntries', []):
        enabled = active(state, r)
        source = sources.get(r['sourceId'], {})
        result.append({'id': 'approval:' + r['id'], 'type': '审批审阅', 'sourceId': r['sourceId'],
            'title': source.get('name', '审批原件'), 'rowIds': r.get('rowIds', []),
            'status': '已撤销' if not enabled else '依据已停用或移除' if not source or not source.get('active', True) else '已核对，无需调整' if r.get('adoptedItems') and all(i.get('outcome') == 'no_change' for i in r['adoptedItems']) else ('已应用更正' if r.get('scopeComplete') else '已部分应用') if r.get('applied') else r['status'],
            'reason': r.get('note', ''), 'at': r.get('at', ''), 'pageNumbers': r.get('pageNumbers', []), 'action': 'approval' if source.get('attachment') else 'source'})
    for r in special_context(state)['records']:
        status = '已撤销' if not r['active'] else '待重新核对' if not r['sourceValid'] or r['issues'] else '已采用'
        result.append({'id': 'special:' + r['id'], 'type': {'adjustment':'手工补扣' if r.get('basisType')=='manual' else '审批补扣','exception':'资格例外','cutoff':'核算口径','history':'认可历史安排'}[r['type']],
            'title': rows.get(r.get('rowId'), {}).get('values', {}).get('姓名') or r.get('name') or str(r['month']),
            'sourceId': r['sourceId'], 'rowIds': [r['rowId']] if r.get('rowId') else [], 'status': status,
            'reason': r['reason'], 'at': r.get('at', ''), 'amount': r.get('amount'), 'currency': r.get('currency', ''),
            'issues': r['issues'], 'action': 'special'})
    for r in state.get('awardDecisions',[]):
        if r.get('basisType')!='manual':continue
        result.append({'id':'decision:'+r['id'],'type':'不发奖金','sourceId':'',
            'title':rows.get(r['rowId'],{}).get('values',{}).get('姓名',''), 'rowIds':[r['rowId']],
            'status':'已采用' if active(state,r) else '已撤销','reason':r['reason'],
            'at':r['at'],'action':'decision'})
    for i, r in enumerate(state.get('adjustmentDrafts', [])):
        result.append({'id': 'legacy:' + str(i), 'type': '原补扣登记', 'title': r.get('recipientName', '原补扣登记'),
            'sourceId': r.get('sourceId', ''), 'rowIds': [r['rowId']] if r.get('rowId') else [],
            'status': '执行待核' if active(state, r) else '已撤销', 'reason': r.get('reason', '原登记未自动转为有效核算安排'),
            'amount': r.get('amount'), 'currency': r.get('currency', ''), 'at': r.get('at', ''), 'action': 'legacy'})
    return sorted(result, key=lambda r: r['at'], reverse=True)


def roster_key(subject):
    return fingerprint([subject['side'],subject.get('sourceRef'),subject.get('rowId'),subject['identity']])


def roster_anchor(subject):
    from .recruitment_reconcile import identity
    values=subject['identity']
    return fingerprint([subject['side'],subject.get('rowId') if subject['side']=='draft' else identity(values) or [str(values.get('姓名','')).casefold(),values.get('入职日期')]])


def project(store, state, source_id=''):
    from .recruitment_approval_intake import project as approval_project
    state, approvals = approval_project(store, ensure_calculated(state))
    tasks = work_items(state, attention(state))
    records = processing_records(state)
    sources = [s for s in state['sources'] if s.get('active', True) and not s.get('error') and 'ledger' in s.get('roles', [])]
    sources.sort(key=lambda s: (comparison_month(s) != state['month'], not s.get('comparisonOnly', False), s['name']))
    if source_id and not any(s['id'] == source_id for s in sources):
        invalid=next((s for s in state['sources'] if s['id']==source_id and s.get('error')),None)
        if invalid:raise ValueError(invalid['name']+'：'+str(invalid['error']))
        raise ValueError('核对台账已停用或不存在，请重新选择')
    source = next((s for s in sources if s['id'] == source_id), None) if source_id else next((s for s in sources if comparison_month(s) == state['month']), None)
    differences = []; comparison = unavailable_comparison(source); latest = {}
    for r in state.get('differenceReviews', []):
        if r['month'] == state['month'] and active(state, r):
            latest[r['differenceId']] = r
    rows = {r['id']: r for r in state['rows']}
    if source and comparison_month(source) == state['month']:
        path = store._folder(state['month']) / 'parsed' / (source['id'] + '.json')
        if not path.is_file():
            raise ValueError('核对台账的解析资料缺失，请重新整理资料')
        reference = [r for r in json.loads(path.read_text())['records'] if r['role'] == 'ledger']
        comparison = monthly_comparison(state, reference, source)
        for d in [*comparison['differences'],*comparison.get('rosterDifferences',[])]:
            key = fingerprint([state['month'], source['id'], d.get('sheet'), d['sourceRow'], d['rowId'], d['kind'], d['item']])
            row = rows.get(d['rowId'], {})
            kind = 'recruitment' if d['kind'] == '招聘奖金' else 'referral'
            signature = fingerprint([d,source.get('contentDigest'),row.get('values'),row.get('calculation',{}).get(kind) if not d.get('subject') else None,row.get('unresolvedFields'),row.get('provenance')])
            review = latest.get(key)
            valid = bool(review and review['fingerprint'] == signature and (review.get('basisType') == 'manual' or review['evidenceSignature'] == evidence_signature(state, review['evidenceId'])))
            status = ('已确认保留差异' if review['outcome'] == 'retain' else '待继续核对' if review.get('basisType') == 'manual' else '待补依据') if valid else '需重新核对' if review else '待核对'
            linked_records = [r for r in records if d['rowId'] and d['rowId'] in r['rowIds']]
            linked_sources = {r['sourceId'] for r in linked_records}
            linked_items=[i for i in approvals['items'] if d['rowId'] and i.get('person',{}).get('rowId')==d['rowId']]
            linked_sources.update(i['sourceId'] for i in linked_items)
            related_tasks = [t['id'] for t in tasks if d['rowId'] and (d['rowId'] in t['rowIds'] or linked_sources.intersection(t['sourceIds']))]
            item_ids=[i['id'] for i in linked_items]
            related_records = [r['id'] for r in linked_records]
            differences.append({**d, 'id': key, 'fingerprint': signature, 'status': status,
                'review': review, 'reviewValid': valid, 'taskIds': related_tasks, 'itemIds':item_ids,'recordIds': related_records,
                **({'subject':{**d['subject'],'taskIds':related_tasks,'itemIds':item_ids,'fingerprint':signature}} if d.get('subject') else {})})
    prior_subjects={}
    for r in sorted(state.get('differenceReviews',[]),key=lambda entry:(entry['month'],entry.get('at',''))):
        if active(state,r) and r.get('subject'):prior_subjects[roster_anchor(r['subject'])]=r
    current_anchors={roster_anchor(d['subject']) for d in differences if d.get('subject')}
    matched_anchors=set()
    for match in comparison.get('matchedRosterSubjects',[]):
        matched_anchors.add(roster_anchor({'side':'draft','rowId':match['rowId'],'identity':match['identity']}))
        matched_anchors.add(roster_anchor({'side':'reference','identity':match['identity']}))
    for d in differences:
        if not d.get('subject') or d['review']:continue
        previous=next((r for r in reversed(list(prior_subjects.values())) if roster_anchor(r['subject'])==roster_anchor(d['subject'])),None)
        if previous:
            d.update(review=previous,reviewValid=False,status='需重新核对',originMonth=previous.get('originMonth',previous['month']))
    for subject_key,previous in prior_subjects.items():
        anchor=roster_anchor(previous['subject'])
        if anchor in current_anchors or anchor in matched_anchors or previous['month']==state['month'] and previous.get('originMonth',state['month'])==state['month']:continue
        snapshot=previous.get('differenceSnapshot',{})
        subject=previous['subject']
        row=rows.get(subject.get('rowId'),{})
        origin_fingerprint=previous.get('followupOriginFingerprint',previous['fingerprint'])
        source_fact=next((s for s in state['sources'] if s['id']==previous['sourceId']),{})
        signature=fingerprint([state['month'],{k:subject.get(k) for k in ('side','sourceRef','rowId','identity','matchStatus')},origin_fingerprint,source_fact.get('contentDigest'),source_fact.get('active',True),row.get('values'),row.get('unresolvedFields')])
        key=fingerprint([state['month'],'roster-followup',subject_key])
        review=latest.get(key)
        valid=bool(review and review['fingerprint']==signature and (review.get('basisType')=='manual' or review.get('evidenceSignature')==evidence_signature(state,review.get('evidenceId'))))
        related_tasks=[t['id'] for t in tasks if subject.get('rowId') in t.get('rowIds',[])]
        item_ids=[i['id'] for i in approvals['items'] if subject.get('rowId') and i.get('person',{}).get('rowId')==subject['rowId']]
        differences.append({**snapshot,'id':key,'fingerprint':signature,'sourceId':previous['sourceId'],
            'subject':{**subject,'fingerprint':signature,'taskIds':related_tasks,'itemIds':item_ids,'monthImpacts':['future']},
            'taskIds':related_tasks,'itemIds':item_ids,'recordIds':[],'review':review or previous,'reviewValid':valid,
            'status':('已确认保留差异' if review['outcome']=='retain' else '待继续核对') if valid else '需重新核对',
            'originMonth':previous.get('originMonth',previous['month']),'followupOriginFingerprint':origin_fingerprint,'monthImpacts':['future'],
            'reason':snapshot.get('reason','人员范围仍待核对')+'；上月未完成的人员范围跟进，本月需重新核对，未沿用上月结论'})
    current_ids = {d['id'] for d in differences}
    history = []
    for r in reversed(state.get('differenceReviews', [])):
        if r['month'] != state['month'] or (source and r['sourceId'] != source['id']):
            continue
        latest_entry = latest.get(r['differenceId'], {})
        history.append({**r, 'current': r['differenceId'] in current_ids,
            'recordStatus': '已撤销' if not active(state, r) else '已被后续记录替代' if latest_entry.get('id') != r['id'] else
                '当前差异仍在，见清单状态' if r['differenceId'] in current_ids else '不在当前差异清单，请核对最新资料'})
    counts = Counter(d['status'] for d in differences)
    return {'month': state['month'], 'revision': state['revision'], 'sourceId': source['id'] if source else '',
        'comparisonScope': comparison['comparisonScope'], 'comparisonReady': comparison['comparisonReady'],
        'sources': [{'id': s['id'], 'name': s['name'], 'month': comparison_month(s)} for s in sources], 'workItems': tasks, 'records': records,
        'differences': differences, 'history': history, 'totalsByCurrency': comparison.get('totalsByCurrency', []),
        'summary': {'materialGroups': sum(t['current'] for t in tasks), 'differenceItems':sum(not d.get('subject') for d in differences),
                    'rosterDifferenceItems':sum(bool(d.get('subject')) for d in differences),
                    'unmatchedPeople':comparison.get('summary',{}).get('unmatchedPeople',0),'draftOnlyPeople':comparison.get('summary',{}).get('draftOnlyPeople',0),
                    'ambiguousPeople':comparison.get('summary',{}).get('ambiguousPeople',0),
                    'equalNodes':comparison.get('summary',{}).get('equalNodes',0),'referenceNodes':comparison.get('summary',{}).get('referenceNodes',0),
                    'qualificationDifferenceNodes':comparison.get('summary',{}).get('qualificationDifferenceNodes',0),'additionalQualificationNodes':comparison.get('summary',{}).get('additionalQualificationNodes',0),
                    'pendingMonetaryDifferences':sum(not d.get('subject') and d['status']!='已确认保留差异' for d in differences),
                    'pendingRosterDifferences':sum(bool(d.get('subject')) and d['status']!='已确认保留差异' for d in differences),
                    'retainedMonetaryDifferences':sum(not d.get('subject') and d['status']=='已确认保留差异' for d in differences),
                    'retainedRosterDifferences':sum(bool(d.get('subject')) and d['status']=='已确认保留差异' for d in differences),
                    'pendingDifferences': len(differences) - counts['已确认保留差异'], 'retainedDifferences': counts['已确认保留差异'],
                    'recheckDifferences': counts['需重新核对'], 'records': len(records)},
        'basis': comparison.get('basis', '请选择或上传核对台账。')}


def save_review(store, month, payload):
    with store._lock(month) as folder:
        state = store.read(month)
        token = str(payload.get('token', ''))
        if len(token) != 32 or any(c not in '0123456789abcdef' for c in token):
            raise ValueError('保存标识无效，请重新打开核对窗口')
        previous = next((r for r in state.get('differenceReviews', []) if r['id'] == token), None)
        if previous:
            if previous['requestFingerprint'] != fingerprint(payload):
                raise ValueError('保存标识已被另一条记录使用')
            return state
        store._check(state, payload.get('revision'))
        outcome = payload.get('outcome')
        if outcome not in {'retain', 'pending'}:
            raise ValueError('请选择核对结论')
        manual = payload.get('basisType') == 'manual'
        reason = ('手工确认保留当前差异' if outcome == 'retain' else '待继续核对') if manual else str(payload.get('reason', '')).strip()
        if not manual and (not reason or len(reason) > 2000):
            raise ValueError('请填写不超过 2000 字的核对依据及原件位置')
        evidence_id = payload.get('evidenceId', '')
        if manual and evidence_id:
            raise ValueError('手工记录不能同时标记来源文件')
        evidence = next((s for s in state['sources'] if s['id'] == evidence_id and s.get('active', True) and not s.get('error') and not s.get('comparisonOnly')), None)
        if not manual and not evidence:
            raise ValueError('请选择有效的原始资料或审批依据')
        data = project(store, state, payload.get('sourceId', ''))
        difference = next((d for d in data['differences'] if d['id'] == payload.get('differenceId')), None)
        if not difference or difference['fingerprint'] != payload.get('fingerprint'):
            raise ValueError('差异已变化，请刷新清单后重新核对')
        if outcome == 'retain' and payload.get('confirmed') is not True:
            raise ValueError('请确认已核对当前差异')
        entry = {'id': token, 'operationId': token, 'month': month, 'sourceId': difference.get('sourceId',data['sourceId']),
            'differenceId': difference['id'], 'fingerprint': difference['fingerprint'], 'name': difference['name'],
            'rowId': difference['rowId'], 'kind': difference['kind'], 'item': difference['item'],
            'outcome': outcome, 'reason': reason, 'basisType': 'manual' if manual else 'source',
            'evidenceId': evidence_id, 'evidenceSignature': evidence_signature(state, evidence_id),
            'at': datetime.now().isoformat(timespec='seconds'), 'requestFingerprint': fingerprint(payload)}
        if difference.get('subject'):
            entry.update(subject=difference['subject'],differenceSnapshot={k:v for k,v in difference.items() if k not in {'review','status','reviewValid'}},originMonth=difference.get('originMonth',month),**({'followupOriginFingerprint':difference['followupOriginFingerprint']} if difference.get('followupOriginFingerprint') else {}))
        state.setdefault('differenceReviews', []).append(entry)
        state.setdefault('operations', []).append({'id': token, 'month': month, 'active': True, 'label': '差异核对记录', 'at': entry['at']})
        state['redoOperations'] = []
        return store._save(folder, state)
