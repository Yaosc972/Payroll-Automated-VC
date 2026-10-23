"""Use approved, effective-dated HR facts without inferring recruitment identity."""
from collections import defaultdict
from copy import deepcopy
import re
from .recruitment_draft_sources import date_text, text


def index_histories(records):
    from .recruitment_drafts import staff_id
    index=defaultdict(list)
    for rec in records:
        if rec['role']=='employment_history':
            item={**rec['apiEvidence']['history'],'source':rec['ref'],
                  'provider':rec['apiEvidence'].get('provider','beisen'),
                  'queriedAt':rec['apiEvidence'].get('queriedAt','')}
            key=staff_id(rec['values']['工号'])
            if item not in index[key]:index[key].append(item)
    # Each successful employment query returns the full approved history for
    # that employee. Use the latest returned history, not two competing snapshot
    # versions; failed/empty lookups never erase saved facts.
    for key,items in index.items():
        latest={provider:max(h.get('queriedAt','') for h in items if h['provider']==provider)
                for provider in {h['provider'] for h in items}}
        index[key]=[h for h in items if h.get('queriedAt','')==latest[h['provider']]]
    return index


def identity_discrepancy_is_observation(row):
    v=row['values']
    if not row.get('identityConflict') or v.get('标签分类')!='国内' or not row.get('offerMatched'):return False
    values={str(p.get('value') or '').strip() for p in row.get('provenance',{}).get('证件号',[]) if p.get('value')}
    formal={value for value in values if re.fullmatch(r'\d{17}[\dXx]',value)}
    if len(formal)!=1 or not values-formal or any(len(value)>=15 for value in values-formal):return False
    for field in ('工号','体系外人员编号','海外offer流程编号'):
        choices={str(p.get('value') or '').strip().lower() for p in row.get('provenance',{}).get(field,[]) if p.get('value')}
        if len(choices)>1:return False
    hire=date_text(v.get('入职日期'))
    current=[h for h in row.get('employmentTimelines',{}).get('',[]) if date_text(h.get('entryDate'))==hire and h.get('lUOffer')]
    return bool(current and len({(h.get('userID'),h.get('lUOffer')) for h in current})==1)


def enrich(row, index, roles):
    """Only unique positive facts are adopted; manual and competing facts survive."""
    from .recruitment_drafts import staff_id
    v=row['values'];edits={e['field'] for e in row['edits']}
    v.pop('_employmentTimelines',None)
    timelines={}
    for field,prefix in [('工号','')]+[(r[0],r[1]) for r in roles]:
        facts=index.get(staff_id(v.get(field)),[])
        if facts:
            timelines[prefix]=facts
            for h in facts:
                if h['source'] not in row['sources']:row['sources'].append(h['source'])
    # The engine consults these only when no manual override or unresolved
    # competing fact affects the role. Never serialize them as worksheet cells.
    row['employmentTimelines']=timelines
    candidate=timelines.get('',[]);hire=date_text(v.get('入职日期'))
    if v.get('标签分类')=='海外' and any(h.get('provider')=='oehr' for h in candidate):
        current=[h for h in candidate if h.get('provider')=='oehr' and h.get('employmentType')=='0'
                 and date_text(h.get('entryDate'))==hire]
        dates={date_text(h.get('lastWorkDay')) for h in current if date_text(h.get('lastWorkDay'))>=hire}
        for value in sorted(dates):
            proof=next(h for h in current if date_text(h.get('lastWorkDay'))==value)
            evidence={**proof['source'],'role':'employment_history','value':value}
            refs=row['provenance'].setdefault('最后工作日',[])
            if evidence not in refs:refs.append(evidence)
        if dates and '最后工作日' not in edits:
            old=date_text(v.get('最后工作日'));choices=dates|({old} if old else set())
            if len(choices)==1:v['最后工作日']=next(iter(choices))
            else:
                conflict={'field':'最后工作日','values':sorted(choices),'sourceId':current[0]['source']['sourceId']}
                if conflict not in row['conflicts']:row['conflicts'].append(conflict)
        return
    current=[h for h in candidate if (date_text(h.get('entryDate'))==hire or
             date_text(h.get('recruitmentEntryDate'))==hire and h.get('continuityEvidence')) and h.get('lUOffer')]
    if not current or len({(h.get('userID'),h.get('lUOffer')) for h in current})!=1:return
    user,offer=current[0]['userID'],current[0]['lUOffer']
    row['automaticFacts']=[]
    for field in ('转正日期','最后工作日'):
        old=date_text(v.get(field))
        if old and old<hire and field not in edits:
            v.pop(field,None)
            row['automaticFacts'].append({'field':field,'before':old,'after':None,
                'reason':'该日期早于已唯一对应的本次入职，不沿用上一段任职事实','source':current[0]['source']})
    def adopt(field,value,proof):
        if not value:return
        refs=row['provenance'].setdefault(field,[])
        evidence={**proof['source'],'role':'employment_history','value':value}
        if evidence not in refs:refs.append(evidence)
        if field in edits:return
        old=v.get(field)
        if old not in ('',None,value):
            conflict={'field':field,'values':[old,value],'sourceId':proof['source']['sourceId']}
            if conflict not in row['conflicts']:row['conflicts'].append(conflict)
        else:
            v[field]=value
            if old!=value:row['automaticFacts'].append({'field':field,'before':old,'after':value,'reason':'采用唯一对应任职的接口事实','source':proof['source']})
    bridged=[h for h in current if h.get('continuityEvidence') and date_text(h.get('recruitmentEntryDate'))==hire]
    formal_dates={date_text(h.get('entryDate')) for h in bridged if date_text(h.get('entryDate'))>hire}
    if len(formal_dates)==1:
        formal=next(iter(formal_dates))
        adopt('人事入职日期',formal,next(h for h in bridged if date_text(h.get('entryDate'))==formal))
    for field,key in [('转正日期','regularizationDate'),('最后工作日','lastWorkDate')]:
        choices={date_text(h.get(key)) for h in current if date_text(h.get(key))>=hire}
        for value in sorted(choices):
            evidence={**current[0]['source'],'role':'employment_history','value':value}
            refs=row['provenance'].setdefault(field,[])
            if evidence not in refs:refs.append(evidence)
        if len(choices)==1:
            value=next(iter(choices));adopt(field,value,current[0])
            if field not in edits and date_text(v.get(field))==value:
                row['conflicts']=[c for c in row['conflicts'] if c['field']!=field
                    or any(date_text(x) not in ('',value) for x in c['values'])]
        elif len(choices)>1 and field not in edits:
            conflict={'field':field,'values':sorted(choices),'sourceId':current[0]['source']['sourceId']}
            if conflict not in row['conflicts']:row['conflicts'].append(conflict)
    prior=[h for h in candidate if h.get('userID')==user and h.get('lUOffer') and h['lUOffer']!=offer
           and date_text(h.get('lastWorkDate')) and date_text(h.get('entryDate'))<=date_text(h['lastWorkDate'])<hire]
    if prior:
        last=max(date_text(h['lastWorkDate']) for h in prior)
        proof=[h for h in prior if date_text(h['lastWorkDate'])==last]
        if len({h['lUOffer'] for h in proof})==1:
            adopt('上次离职日期',last,proof[0])
            if row.get('employmentCandidates') and '任职说明' not in edits and not v.get('任职说明'):
                starts={date_text(h.get('entryDate')) for h in prior}
                if all(c['hireDate'] in starts for c in row['employmentCandidates']):
                    v['任职说明']='二次入职：北森已对应前后不同录用记录，上一段任职已结束'


def status_from_timeline(row,prefix,at,formal=False):
    """Return None when reviewed facts may supply the missing HR evidence.

    StopDate closes a service segment, not necessarily an employment. Null
    RegularizationDate never proves formal status. No future eligibility inferred
    beyond the snapshot date; unusable explicit statuses remain pending.
    """
    if not at:return None
    fields={prefix+f for f in ('入职日期','人员状态','最后工作日','转正日期')}
    if fields & ({e['field'] for e in row.get('edits',[])}|set(row.get('unresolvedFields',[]))):return None
    date=at.strftime('%Y-%m-%d')
    facts=row.get('employmentTimelines',{}).get(prefix,[])
    region=row.get('recipientSourceRegions',{}).get(prefix) if prefix else row['values'].get('标签分类')
    overseas=[h for h in facts if h.get('provider')=='oehr']
    if region=='海外' and (prefix or overseas) or overseas and region!='国内':
        return _overseas_status(overseas,row,prefix,date,formal) if overseas else None
    facts=[h for h in facts if h.get('provider','beisen')=='beisen']
    # Recipient identity follows the employee at the award's business date;
    # their current rehire date must not hide an earlier valid employment.
    hire=date_text(row['values'].get(prefix+'入职日期'))
    if prefix and hire>date:hire=''
    if hire:
        facts=[h for h in facts if date_text(h.get('entryDate'))==hire or
               not prefix and date_text(h.get('recruitmentEntryDate'))==hire and h.get('continuityEvidence')]
    queried=[h.get('queriedAt','')[:10] for h in facts if h.get('queriedAt')]
    if queried and date>max(queried):return '适用日期晚于资料采集日期'
    matches=[h for h in facts if date_text(h.get('startDate')) and date_text(h.get('stopDate'))
             and date_text(h['startDate'])<=date<=date_text(h['stopDate']) and date<=h.get('queriedAt','')[:10]]
    if not matches or len({(h.get('userID'),date_text(h.get('entryDate'))) for h in matches})!=1:return None
    outcomes=set()
    for h in matches:
        # Only the approved active-service code already requested by the adapter
        # is usable; unknown codes remain explicit missing facts.
        if str(h.get('serviceType'))!='0' or str(h.get('approvalStatus'))!='4':return None
        last=date_text(h.get('lastWorkDate'));entry=date_text(h.get('entryDate'))
        if 'employeeStatus' in h:
            status=str(h['employeeStatus'])
            if status not in {'2','3','8'} or status=='8' and not last:
                return '任职记录状态待核对'
        if not entry:return None
        if entry>date or last and last<date:outcomes.add('适用日期已不在职')
        elif formal:
            probation=date_text(h.get('regularizationDate'))
            if not probation or probation<entry:
                reviewed=date_text(row['values'].get(prefix+'转正日期'))
                return None if reviewed and reviewed>=entry else '转正日期待核对'
            outcomes.add('适用日期尚未转正' if probation>date else '')
        else:outcomes.add('')
    return next(iter(outcomes)) if len(outcomes)==1 else None


def referrer_fact_missing(value):
    return text(value).casefold() in {'','-','--','无','无工号','n/a','none','null'}


def _referrer_translations(history, histories):
    """Complete unrequested metadata only from the exact same captured segment."""
    translated=history.get('translateProperties',{})
    if not isinstance(translated,dict):return None
    fields={'OIdJobLevelText':'oIdJobLevel','OIdJobPositionText':'oIdJobPosition'}
    if all(k in translated for k in fields):return translated
    if not text(history.get('jobNumber')):return None
    def segment(h):
        return (h.get('provider','beisen'),str(h.get('userID')),text(h.get('jobNumber')).casefold(),
                *(date_text(h.get(k)) for k in ('entryDate','startDate','stopDate')),
                *(str(h.get(k)) for k in ('serviceType','approvalStatus','employType','lUOffer','queriedAt')))
    peers=[h for h in histories if segment(h)==segment(history) and isinstance(h.get('translateProperties'),dict)
           and all(k in h['translateProperties'] for k in fields)]
    for raw in fields.values():
        identifiers={h[raw] for h in [history]+peers if raw in h}
        if len(identifiers)>1 or any(referrer_fact_missing(v) or v in (0,'0') for v in identifiers):return None
    result=dict(translated)
    for field in fields:
        if field in result:continue
        choices={text(h['translateProperties'][field]) for h in peers}
        if len(choices)!=1:return None
        result[field]=next(iter(choices))
    return result


def referrer_qualification(row, dates):
    """Resolve qualification at candidate hire, keeping explicit corrections intact."""
    fields={'推荐人职级':'OIdJobLevelText','推荐人职位':'OIdJobPositionText'}
    values=row['values']
    if not dates or not all(dates):return []
    protected={e['field'] for e in row.get('edits',[]) if e.get('active',True)}
    protected.update(row.get('unresolvedFields',[]))
    protected.update(c['field'] for c in row.get('conflicts',[]))
    if protected & (set(fields)|{'推荐人工号','推荐人姓名','推荐人入职日期'}):return []
    facts=row.get('employmentTimelines',{}).get('推荐人',[])
    region=row.get('recipientSourceRegions',{}).get('推荐人')
    if region=='海外' or region!='国内' and any(h.get('provider')=='oehr' for h in facts):return []
    facts=[h for h in facts if h.get('provider','beisen')=='beisen']
    basis=[];identities=set();pairs=set()
    for at in sorted(set(dates)):
        day=at.strftime('%Y-%m-%d');hire=date_text(values.get('推荐人入职日期'))
        if hire>day:hire=''
        matches=[h for h in facts if (not hire or date_text(h.get('entryDate'))==hire)
                 and date_text(h.get('startDate')) and date_text(h.get('stopDate'))
                 and date_text(h['startDate'])<=day<=date_text(h['stopDate'])]
        if not matches:return []
        sources=[];day_pairs=set()
        for h in matches:
            entry=date_text(h.get('entryDate'));source=h.get('source',{})
            if (not h.get('userID') or not entry or entry>day or
                str(h.get('approvalStatus'))!='4' or str(h.get('serviceType'))!='0' or
                day>h.get('queriedAt','')[:10] or not source.get('sourceId')):return []
            translated=_referrer_translations(h,matches)
            if translated is None:return []
            pair=tuple(text(translated.get(k)) for k in fields.values())
            if not re.fullmatch(r'[PM]\d+(?:-\d+)?',pair[0].upper()) or referrer_fact_missing(pair[1]):return []
            day_pairs.add(pair);identities.add((h['userID'],entry))
            if source not in sources:sources.append(source)
        if len(day_pairs)!=1 or len(identities)!=1:return []
        pair=next(iter(day_pairs));pairs.add(pair)
        qualification=dict(zip(fields,pair))
        basis.append({'at':day,'values':qualification,'sources':sources})
    return basis if len(pairs)==1 else []


def _overseas_status(facts,row,prefix,at,formal):
    if at>max(h.get('queriedAt','')[:10] for h in facts):return '适用日期晚于资料采集日期'
    hire=date_text(row['values'].get(prefix+'入职日期'))
    if prefix and hire>at:hire=''
    # The assembler may already prove that an opening recruitment and a unique
    # same-Offer roster hire are one employment. Revalidate the date and source
    # anchors before using its HR date for candidate eligibility only.
    basis=row.get('recruitmentContinuityBasis',{});context=row.get('employmentContext',{})
    if not prefix and isinstance(basis,dict) and isinstance(context,dict):
        hr_dates=context.get('hrHireDates',[])
        hr_hire=date_text(hr_dates[0]) if len(hr_dates)==1 else ''
        def source_key(ref):
            return tuple(ref.get(k) for k in ('sourceId','sheet','row')) if isinstance(ref,dict) else ()
        refs=basis.get('sources',[]);keys={source_key(ref) for ref in refs}
        observations=row.get('employmentObservations',[])
        histories=[h for h in facts if h.get('employmentType')=='0' and h.get('entryDate')==hr_hire]
        valid_sources=bool(keys and all(len(key)==3 and all(key) for key in keys)
                           and keys<={source_key(ref) for ref in row.get('sources',[])}
                           and keys=={source_key(ref) for ref in observations}
                           and all(ref.get('role')=='roster' and date_text(ref.get('value'))==hr_hire for ref in observations)
                           and histories and all(h.get('source',{}).get('sourceId') in {key[0] for key in keys} for h in histories))
        if (row.get('frozenRecruitmentFacts') and row['values'].get('标签分类')=='海外'
            and hire and hr_hire and hire[:7]==hr_hire[:7]
            and date_text(context.get('recruitmentHireDate'))==hire
            and text(basis.get('offerId')) and text(basis.get('offerId'))==text(row['values'].get('海外offer流程编号'))
            and row['values'].get('是否二次入职')!='是' and valid_sources):
            hire=hr_hire
    uncertain=[h for h in facts if h.get('employmentType')=='0' and (not hire or not h.get('entryDate') or h['entryDate']==hire)
               and (not h.get('startDate') or h['startDate']<=at) and (not h.get('endDate') or at<=h['endDate'])
               and any(not h.get(key) for key in ('startDate','endDate','entryDate'))]
    if uncertain:return '任职记录生效日期待核对'
    records=[h for h in facts if h.get('employmentType')=='0' and (not hire or h.get('entryDate')==hire)]
    if not records:return '缺少本次任职的日期记录'
    matches=[h for h in records if h.get('startDate','')<=at<=h.get('endDate','')]
    if not matches:return '缺少适用日期的任职记录'
    if len({h.get('entryDate') for h in matches})!=1:return '任职记录在适用日期存在冲突'
    outcomes=set()
    for h in matches:
        # A terminated segment is still valid evidence for its effective interval.
        # Unknown statuses never become positive eligibility.
        if h.get('employmentStatus') not in {'0','1'}:return '任职记录状态待核对'
        last=h.get('lastWorkDay');status=h.get('employeeStatus');entry=h.get('entryDate')
        if not entry or status not in {'2','3','8'}:return '任职记录状态待核对'
        if formal and status=='2' and any(p.get('entryDate')==entry and p.get('employeeStatus')=='3'
                and p.get('employmentStatus') in {'0','1'} and p.get('startDate','')<=at for p in records):
            return '任职记录在适用日期存在冲突'
        if entry>at or last and last<at or status=='8' and not last:outcomes.add('适用日期已不在职')
        elif formal:outcomes.add('适用日期尚未转正' if status=='2' else '' if status=='3' else '转正状态待核对')
        else:outcomes.add('')
    return next(iter(outcomes)) if len(outcomes)==1 else '任职记录在适用日期存在冲突'


def _review_values(row):
    values = dict(row['values'])
    effective = [e for e in row.get('edits', []) if e.get('active', True)]
    for field in {e['field'] for e in effective if e.get('employmentBasis')}:
        ordinary = [e for e in effective if e['field'] == field and not e.get('employmentBasis')]
        if ordinary:
            values[field] = ordinary[-1].get('value')
        elif field in row.get('original', {}):
            values[field] = row['original'][field]
        else:
            values.pop(field, None)
    return values


def employment_review(state, row_id):
    """Project a relation choice with proof from distinct, identified segments."""
    import json
    from .recruitment_draft_sources import digest
    row = next((r for r in state['rows'] if r['id'] == row_id), None)
    if row is None:
        raise ValueError('任职记录已变化，请刷新后核对')
    values = _review_values(row)
    hire = date_text(values.get('入职日期') or values.get('候选人入职时间'))
    source_map = {s['id']: s for s in state.get('sources', [])}
    def valid_ref(ref):
        source = source_map.get(ref.get('sourceId'), {})
        if 'contentDigest' in source and not source['contentDigest']:
            return False
        return bool(source and source.get('active', True) and not source.get('error') and not source.get('comparisonOnly'))
    def refs_for(old, field):
        return [ref for ref in old.get('provenance', {}).get(field, []) if valid_ref(ref)]
    priors = []
    for old in state['rows']:
        if old['id'] == row_id:
            continue
        previous = _review_values(old)
        same = any(values.get(f) and str(values[f]).strip().casefold() == str(previous.get(f, '')).strip().casefold()
                   for f in ('工号', '证件号', '体系外人员编号'))
        conflicting = any(values.get(f) and previous.get(f) and str(values[f]).strip().casefold() != str(previous[f]).strip().casefold() for f in ('工号', '证件号', '体系外人员编号'))
        if conflicting:
            continue
        start = date_text(previous.get('入职日期') or previous.get('候选人入职时间'))
        if not same or not start or not hire or start >= hire:
            continue
        refs = refs_for(old, '入职日期') or [h['ref'] for h in old.get('history', []) if valid_ref(h['ref'])]
        if not refs:
            continue
        end = date_text(previous.get('最后工作日'))
        end_refs = [ref for ref in refs_for(old, '最后工作日') if date_text(ref.get('value')) == end]
        # A manually reviewed date remains traceable to its original operation.
        date_edits = [{'field': '最后工作日', 'value': date_text(e.get('value'))} for e in old.get('edits', [])
                      if e.get('active', True) and e.get('field') == '最后工作日' and not e.get('employmentBasis')][-1:]
        unresolved = ('最后工作日' in old.get('unresolvedFields', []) or
                      not date_edits and any(c['field'] == '最后工作日' for c in old.get('conflicts', [])))
        if unresolved:
            end_refs = []
        elif date_edits:
            end_refs = refs
        priors.append({'rowId': old['id'], 'hireDate': start, 'lastWorkDate': end,
                       'sources': refs, 'exitSources': end_refs, 'dateEdits': date_edits})
    # Only one actual preceding segment can be selected without a further fact.
    latest = max((p['hireDate'] for p in priors), default='')
    nearest = [p for p in priors if p['hireDate'] == latest]
    prior = nearest[0] if len(nearest) == 1 else None
    exit_proof = ({'value': prior['lastWorkDate'], 'sources': prior['exitSources'], 'priorRowId': prior['rowId']}
                  if prior and prior['exitSources'] and prior['hireDate'] <= prior['lastWorkDate'] < hire else None)
    observations = [{'label': '台账入职日' if row.get('history') else '当前入职日', 'value': hire or '未提供',
                     'sources': [{k: ref.get(k) for k in ('sourceId', 'sheet', 'row', 'column')} |
                                 {'file': source_map.get(ref.get('sourceId'), {}).get('name', '人工补充')}
                                 for ref in row.get('provenance', {}).get('入职日期', [])]}]
    for p in priors:
        observations.append({'label': '原任职入职日', 'value': p['hireDate'], 'sources': p['sources']})
        if p['lastWorkDate']:
            observations.append({'label': '原任职最后工作日', 'value': p['lastWorkDate'], 'sources': p['exitSources']})
    issue_labels = {'花名册与台账任职日期不同': '台账与花名册入职日不同', '同一台账存在重复任职记录': '同一台账有重复任职行'}
    issues = list(dict.fromkeys(issue_labels.get(t['title'], t['title']) for t in state.get('todos', []) if row_id in t.get('rowIds', []) and
                              t['kind'] in {'employment_conflict', 'hire_date', 'duplicate_source_row', 'offer_employment', 'previous_exit'}))
    anchors = {f: values.get(f, '') for f in ('工号', '证件号', '体系外人员编号', '海外offer流程编号', '入职日期', '候选人入职时间')}
    refs = [ref for p in priors for ref in p['sources'] + p['exitSources']]
    refs += [ref for field in anchors for ref in row.get('provenance', {}).get(field, []) if valid_ref(ref)]
    sources = [{k: source_map[ref['sourceId']].get(k) for k in ('id', 'active', 'error', 'parserVersion', 'contentDigest')}
               for ref in refs if ref['sourceId'] in source_map]
    signature = digest(json.dumps({'rowId': row_id, 'anchors': anchors, 'priors': priors,
                                   'candidates': row.get('employmentCandidates', []), 'sourceRefs': refs, 'sources': sources}, sort_keys=True, ensure_ascii=False, default=str))
    options = [{'value': 'new_hire', 'label': '本次为新招聘／二次入职'}]
    if prior:
        options.append({'value': 'continuation', 'label': '沿用原任职，本段不新增奖金'})
    selection = {'rowId': row_id, 'signature': signature, 'options': options, 'priorExit': exit_proof, 'priorRowId': prior['rowId'] if prior else '', 'sources': refs} if priors or row.get('employmentCandidates') else None
    return {'issues': issues, 'observations': observations,
            'instruction': '选择本次任职关系，已有的上段离职日随预览带入。' if selection else '核对本次实际入职日期及原始任职资料。',
            'selection': selection, 'priorExit': exit_proof}


_EMPLOYMENT_FACT_FIELDS = {'工号', '证件号', '体系外人员编号', '海外offer流程编号', '入职日期', '候选人入职时间', '最后工作日'}


def _prospective_state(state, proposed_edits):
    """Project ordinary and reference facts already validated by the caller."""
    relevant = [e for e in proposed_edits if not e.get('employmentBasis') and e.get('active', True)
                and e.get('field') in _EMPLOYMENT_FACT_FIELDS]
    if not relevant:
        return state
    prospective = deepcopy(state)
    rows = {row['id']: row for row in prospective['rows']}
    for edit in relevant:
        row = rows[edit['rowId']]
        field = edit['field']
        value = edit.get('value', '')
        if field in {'入职日期', '候选人入职时间', '最后工作日'} and value:
            value = date_text(value)
        projected = {**edit, 'value': value}
        row['values'][field] = value
        row.setdefault('edits', []).append(projected)
        prospective.setdefault('edits', []).append(projected)
    for row in rows.values():
        edited = {e['field'] for e in relevant if e['rowId'] == row['id']}
        refs = row.get('provenance', {}).get('候选人入职时间', [])
        if '入职日期' in edited and '候选人入职时间' not in edited and refs and all(p.get('derivedFrom') == '入职日期' for p in refs):
            row['values']['候选人入职时间'] = row['values']['入职日期']
    return prospective


def employment_edits(state, selections, proposed_edits=()):
    """Resolve only the relation choice; clients never supply generated dates."""
    if not isinstance(selections, list) or len(selections) > 5000:
        raise ValueError('任职选择格式无效')
    prospective = None
    result = []
    seen = set()
    for selected in selections:
        if not isinstance(selected, dict) or set(selected) - {'rowId', 'relation', 'signature'}:
            raise ValueError('任职选择格式无效')
        rid = selected.get('rowId')
        if rid in seen:
            raise ValueError('同一任职不能重复选择关系')
        seen.add(rid)
        review = employment_review(state, rid)
        choice = review['selection']
        if not choice or selected.get('signature') != choice['signature']:
            raise ValueError('任职来源或关联已变化，请重新核对')
        relation = selected.get('relation')
        if relation not in {o['value'] for o in choice['options']}:
            raise ValueError('请选择有效的任职关系')
        if prospective is None:
            prospective = _prospective_state(state, proposed_edits)
        if prospective is not state:
            final = employment_review(prospective, rid)['selection']
            if not final or final['priorRowId'] != choice['priorRowId'] or relation not in {o['value'] for o in final['options']}:
                raise ValueError('更正后的任职关联已变化，请重新核对')
            for linked in (rid, choice['priorRowId']):
                if not linked:
                    continue
                original = _review_values(next(r for r in state['rows'] if r['id'] == linked))
                updated = _review_values(next(r for r in prospective['rows'] if r['id'] == linked))
                identities = lambda values: {(f, str(values[f]).strip().casefold()) for f in ('工号', '证件号', '体系外人员编号') if values.get(f)}
                before, after = identities(original), identities(updated)
                if before != after and not before & after:
                    raise ValueError('更正后的任职身份已变化，请重新核对')
            choice = final
            selected = {**selected, 'signature': choice['signature']}
        prior = choice.get('priorExit')
        changes = [('任职说明', '二次入职：已核对本次为独立招聘任职'), ('核算范围', '纳入核算')]
        if relation == 'continuation':
            # The existing assembler recognizes this stable prior-row link.
            target = choice['priorRowId']
            if not target:
                raise ValueError('原任职关联尚不能唯一确定')
            changes = [('任职说明', '任职延续：沿用原招聘任职' + target), ('核算范围', '不纳入核算')]
        elif prior:
            changes.append(('上次离职日期', prior['value']))
        for field, value in changes:
            basis = {**selected, 'field': field, 'value': value,
                     'sources': choice['sources'], 'priorRowId': choice['priorRowId']}
            result.append({'rowId': rid, 'field': field, 'value': value,
                           'reason': '核对任职关系并复用原任职事实', 'employmentBasis': basis})
    return result


def valid_employment_edit(state, edit, proposed_edits=()):
    basis = edit.get('employmentBasis')
    if not isinstance(basis, dict):
        return False
    try:
        prospective = _prospective_state(state, proposed_edits)
        choices = employment_edits(prospective, [{k: basis.get(k) for k in ('rowId', 'relation', 'signature')}])
    except (ValueError, KeyError, TypeError):
        return False
    return any(e['rowId'] == edit.get('rowId') and e['field'] == edit.get('field') and
               e['value'] == edit.get('value') and e['employmentBasis'] == basis for e in choices)
