"""Persistent, revisioned recruitment intake. No award or payment execution."""
from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import contextmanager
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
from xml.etree import ElementTree as ET
import zipfile
from uuid import uuid4

from .recruitment_time import now as recruitment_now
from .recruitment_cancellation import checkpoint

from .recruitment_draft_sources import (
    DATE_FIELDS, DEPRECATED_FIELDS, FIELDS, PARSER_VERSION, date_text, digest, read_source, text,
)
from .recruitment_import_validation import (
    _is_domestic_location, _normalized_region_type, _normalized_special_region_rule, _classify_overseas_country, _normalize_offer_channel, _channel_notes, _channel_note_categories, _confirmed_domestic_scope, offer_validity,
)

ROLE_LABELS={'ledger':'历史/核对台账','roster':'人员花名册','domestic_offer':'国内Offer','overseas_offer':'海外Offer',
             'supplement':'补充人员','resignation':'离职资料','approval':'审批资料','unknown':'待识别','employment_history':'任职时间线'}
EDITABLE_FIELDS = (FIELDS - DEPRECATED_FIELDS - {'核算月份','审批状态','是否作废','状态','数据动作','申请单编号'}) | {
    '二次入职执行口径','原始ABC类别','任职说明','招聘负责人入职日期','协助招聘人入职日期','推荐人入职日期',
    '管培生资格依据','周期豁免依据','发薪币种','发薪主体','核算范围','二次入职间隔结论',
    '负周期确认启动日期','负周期确认入职日期','负周期确认剔除天数','负周期确认依据',
}
ROLE_FIELDS=[('招聘负责人工号','招聘负责人','招聘负责人姓名','招聘负责人人员状态'),
             ('协助招聘人工号','协助招聘人','协助招聘人姓名','协助招聘人人员状态'),
             ('推荐人工号','推荐人','推荐人姓名','推荐人人员状态')]
DYNAMIC={'人员状态','最后工作日','转正日期','直线经理','直线经理工号','直接上级工号'}
MONTHLY_FIELDS={'最后工作日','转正日期'}
IDENTITY={'工号','证件号','体系外人员编号','海外offer流程编号'}
SNAPSHOT_FIELDS={'姓名','工号','证件号','入职日期','候选人入职时间','人员状态','工作地','职级',
                 '二级组织','三级组织','四级组织','五级组织','职位','直线经理','直线经理工号','直接上级工号','直接上级姓名',
                 '标签分类','ABC类别','招聘负责人工号','招聘负责人姓名','协助招聘人工号','协助招聘人姓名',
                 '招聘渠道','海外offer流程编号','招聘启动日期','推荐人姓名','推荐人工号',
                 '原始ABC类别','原始招聘渠道','奖金地区类型'}
OFFER_FIELDS={'ABC类别','招聘负责人工号','招聘负责人姓名','协助招聘人工号','协助招聘人姓名',
              '招聘渠道','原始招聘渠道','招聘启动日期','推荐人姓名','推荐人工号'}
ASSEMBLY_VERSION=34


@lru_cache(maxsize=64)
def _parsed_metadata(path, file_stamp):
    """Retain validation metadata, without retaining the full personnel records."""
    parsed=json.loads(Path(path).read_text())
    result={k:parsed[k] for k in ('contentDigest','parserVersion','beisenSourceMetadata','attachment','sheets') if k in parsed}
    records=parsed.get('records',[])
    result.update(recordCount=len(records),roles=sorted({r['role'] for r in records}),
                  roleCounts=dict(Counter(r['role'] for r in records)))
    return result


class DraftConflict(ValueError):
    pass


def scope_status(values):
    """Scope comes from employment facts and explicit decisions, not job family."""
    if values.get('核算范围')=='纳入核算': return '已纳入底稿'
    if values.get('核算范围')=='不纳入核算': return '经核对不纳入'
    if text(values.get('人员来源'))=='人员迁移' and not text(values.get('任职说明')): return '范围待核'
    return '已纳入底稿'


def _empty(month):
    return {'month':month,'revision':0,'sources':[],'rows':[],'todos':[],'baseline':'','edits':[],
            'manualRows':[], 'parentMonth':None, 'parentRevision':None, 'paymentReady':False,'summary':{},'updatedAt':''}


def _date(values):
    return date_text(values.get('入职日期') or values.get('候选人入职时间'))


def staff_id(value):
    value=text(value)
    match=re.search(r'(?i)\bzt\d+\b',value)
    return match.group(0).lower() if match else value.lower()


def _identity(values, ref):
    # Names alone are never a join key. The employment start is part of identity.
    start=_date(values)
    for field in ('工号','证件号','体系外人员编号','海外offer流程编号'):
        value=text(values.get(field))
        if value and value not in {'-','无','无工号','N/A'}:
            return f'{field}:{value.lower()}|{start}'
    return f"source:{ref['sourceId']}:{ref['sheet']}:{ref['row']}"


def employment_aliases(values):
    start=_date(values)
    if not start:return set()
    return {(field,staff_id(values[field]) if field=='工号' else text(values[field]).lower(),start)
            for field in IDENTITY if text(values.get(field)) not in {'','-','无','无工号','N/A'}}


def _employment_keys(records, previous):
    anchors=[r for r in records if r['role'] in {'ledger','supplement','roster'}]
    nodes=[(None,r['values'],r['key']) for r in previous]
    nodes += [(r,r['values'],_identity(r['values'],r['ref'])) for r in anchors]
    parents=list(range(len(nodes)));index={}
    def root(i):
        while parents[i]!=i:
            parents[i]=parents[parents[i]];i=parents[i]
        return i
    for i,(_,values,_) in enumerate(nodes):
        for alias in employment_aliases(values):
            if alias in index:parents[root(i)]=root(index[alias])
            else:index[alias]=i
    groups=defaultdict(list)
    for i,node in enumerate(nodes):groups[root(i)].append(node)
    resolved={};conflicts={};old_conflicts={}
    for group in groups.values():
        old_keys={key for rec,_,key in group if rec is None}
        facts=defaultdict(set)
        for _,values,_ in group:
            for field,value,_ in employment_aliases(values):facts[field].add(value)
        ambiguous=len(old_keys)>1 or any(len(values)>1 for values in facts.values())
        preferred=next((key for rec,_,key in group if rec is not None and rec['role'] in {'ledger','supplement'}),group[0][2])
        canonical=next(iter(old_keys)) if len(old_keys)==1 else preferred
        marker=digest('|'.join(sorted({key for _,_,key in group})))
        for rec,values,key in group:
            if rec is None:
                if ambiguous:old_conflicts[key]=marker
                continue
            if ambiguous:
                primary=_identity(values,rec['ref'])
                exact=[old_key for old_rec,old_values,old_key in group if old_rec is None and _identity(old_values,{'sourceId':'','sheet':'','row':0})==primary]
                resolved[id(rec)]=exact[0] if len(exact)==1 else key
                conflicts[id(rec)]=marker
            else:resolved[id(rec)]=canonical
    return resolved,conflicts,old_conflicts


def _intake_exclusion(values):
    """Roster eligibility is not a missing-fact task or an award exclusion."""
    source=text(values.get('人员来源'))
    if source=='EHR入职' or not source and values.get('标签分类')=='国内':
        return '' if staff_id(values.get('工号')).startswith('zt') else 'ehrNonZt'
    if source=='OEHR入职' or not source and values.get('标签分类')=='海外':
        return '' if text(values.get('海外offer流程编号')) not in {'','-','无','N/A'} else 'oehrMissingOffer'
    return 'otherSource'


def _rule(row, unresolved):
    v=row['values']; first=date_text(v.get('入职日期')); second=date_text(v.get('候选人入职时间'))
    if (not first and not second) or (first and second and first!=second) or unresolved or (v.get('人员来源')=='人员迁移' and not text(v.get('任职说明'))):
        return {'version':'unresolved','label':'入职事实待核','basis':'核对本次实际入职日期及任职关系','specialScope':''}
    start=first or second
    version='legacy' if start<'2026-07-01' else '2026-07'
    return {'version':version,'label':'旧规则' if version=='legacy' else '2026年7月规则',
            'basis':f'本次实际入职日 {start}；版本随本次任职固定',
            'specialScope':_normalized_special_region_rule(v) if version=='legacy' else ''}


def assemble(month, records, state):
    checkpoint()
    from .recruitment_business_basis import select_unique_opening
    select_unique_opening(state)
    from .recruitment_employment import index_histories, enrich, identity_discrepancy_is_observation
    employment_index=index_histories(records)
    current_sources={s['id'] for s in state['sources'] if s.get('forMonth',month)==month}
    state['assemblyVersion']=ASSEMBLY_VERSION
    # API continuity requires a unique, proven relationship; it never uses name
    # matching or rewrites a user-edited employment. Keep both dates in evidence.
    edited={e['rowId'] for e in state.get('edits',[]) if e.get('active',True)}
    active_ops={o['id'] for o in state.get('operations',[]) if o.get('active')}
    reviewed=edited | {d['rowId'] for key in ('awardDecisions','installmentPlans','adjustmentDrafts')
                      for d in state.get(key,[]) if d.get('operationId') in active_ops and d.get('rowId')}
    reviewed.update(rid for review in state.get('reviewEntries',[]) if review.get('applied')
                    and (not review.get('operationId') or review['operationId'] in active_ops)
                    for rid in review.get('rowIds',[]))
    protected={(staff_id(r['values'].get('工号')),_date(r['values'])) for r in state.get('rows',[]) if r['id'] in edited}
    links=defaultdict(dict)
    for rec in records:
        checkpoint()
        if rec['role']=='employment_link':
            v=rec['values'];links[(staff_id(v.get('工号')),v['人事入职日期'])][v['入职日期']]=rec
    normalized=[];replaced=set();virtual=set()
    for rec in records:
        checkpoint()
        if rec['role']=='roster':
            v=rec['values'];key=(staff_id(v.get('工号')),_date(v))
            if text(v.get('是否虚拟员工'))=='是':virtual.add(key)
            choices=links.get(key,{})
            if len(choices)==1 and key not in protected and key not in virtual:
                original,proof=next(iter(choices.items()));rec=deepcopy(rec)
                rec['values'].update({'入职日期':original,'候选人入职时间':original,'人事入职日期':key[1],
                    '任职说明':'任职延续：北森同一实习录用记录转正式，招聘日期沿用 '+original})
                rec['continuityEvidence']=proof['ref'];replaced.add(key)
        normalized.append(rec)
    records=normalized
    virtual_numbers={number for number,_ in virtual}
    latest_api={}
    for rec in records:
        checkpoint()
        proof=rec.get('apiEvidence',{})
        if rec['role']=='domestic_offer' and proof.get('offerId') and not proof.get('field'):
            anchor=(staff_id(rec['values'].get('工号')),_date(rec['values']))
            latest_api[anchor]=max(latest_api.get(anchor,''),proof.get('queriedAt',''))
    records=[rec for rec in records if rec['role']!='domestic_offer' or not rec.get('apiEvidence',{}).get('offerId')
             or rec.get('apiEvidence',{}).get('field') or rec['apiEvidence'].get('queriedAt','')==latest_api.get((staff_id(rec['values'].get('工号')),_date(rec['values'])), '')]
    unavailable_sources={s['id'] for s in state['sources'] if s.get('sourceCacheError') and s.get('purpose')!='external-results'}
    old_by_key={r['key']:r for r in state.get('rows',[])}
    # Preserve a stable row after a previously unidentified person gains an employee number.
    record_keys,identity_conflicts,old_identity_conflicts=_employment_keys(records,state.get('rows',[]))
    original_sources={s['id'] for s in state['sources'] if 'contentDigest' in s and not s.get('comparisonOnly')}
    current_anchors={(r['ref']['sourceId'],record_keys[id(r)]) for r in records if id(r) in record_keys}
    def unavailable_origins(row):
        origins={ref['sourceId'] for field in (*IDENTITY,'入职日期','候选人入职时间')
                 for ref in row.get('provenance',{}).get(field,[]) if ref.get('role') in {'ledger','supplement','roster'}}
        return sorted(({ref['sourceId'] for ref in row.get('sources',[])} & unavailable_sources) |
                      {sid for sid in origins & original_sources if (sid,row['key']) not in current_anchors})
    rows={}; offers=defaultdict(list); unusable_offers=defaultdict(list); people=defaultdict(list); resignations=defaultdict(list)
    grouped={}
    def todo(kind, title, key, row_id=None, detail='', source_id=None):
        tid=digest(kind+'|'+key)
        item=grouped.setdefault(tid,{'id':tid,'kind':kind,'title':title,'detail':detail,'rowIds':[],'sourceIds':[]})
        if row_id and row_id not in item['rowIds']: item['rowIds'].append(row_id)
        if source_id and source_id not in item['sourceIds']: item['sourceIds'].append(source_id)
        return item
    def row_for(rec):
        key=record_keys.get(id(rec),_identity(rec['values'],rec['ref']))
        if key not in rows:
            old=old_by_key.get(key,{})
            rows[key]={'id':old.get('id') or digest(key),'key':key,'original':{},'values':{},'provenance':{},
                       'sources':[],'history':[],'conflicts':[],'edits':[], 'originKinds':[], 'offerMatched':False,
                       'openingAbsentFields':[]}
            if old and state.get('parentMonth') and _date(old['values']) and _date(old['values'])[:7].replace('-','')<str(month):
                # Carry the actual accepted facts, including reviewed values and
                # empty cells. Re-reading last month's raw exports is not carry.
                rows[key]['original'].update({f:deepcopy(old['values'].get(f,'')) for f in SNAPSHOT_FIELDS})
                rows[key]['frozenRecruitmentFacts']=True
                missing=unavailable_origins(old)
                if missing:rows[key]['unavailableSourceIds']=missing
        marker=identity_conflicts.get(id(rec)) or old_identity_conflicts.get(key)
        if marker:rows[key]['identityConflict']=marker
        return rows[key]
    def apply(row,rec,fields=None,overwrite=False,observe_only=False):
        if rec.get('continuityEvidence'): row['continuityEvidence']=rec['continuityEvidence']
        if rec.get('scopeBasis'):
            row.setdefault('sourceScopeEvidence',[]).append({**rec['ref'],'scope':rec.get('sourceScope'),'basis':rec['scopeBasis']})
        referrer_issue=rec['values'].get('推荐人说明冲突')
        if referrer_issue:
            conflict={'field':'推荐人工号','values':referrer_issue['values'],'sourceId':rec['ref']['sourceId'], 'reason':'其他渠道中的推荐人与显式字段不一致或存在多个工号'}
            if conflict not in row['conflicts']:row['conflicts'].append(conflict)
        ref=rec['ref']; row['sources'].append(ref) if ref not in row['sources'] else None
        if rec['role'] not in row['originKinds']: row['originKinds'].append(rec['role'])
        for field,val in rec['values'].items():
            if field in {'录用有效性','推荐人说明冲突'}:continue
            if fields is not None and field not in fields: continue
            opening_absent=field in row.get('openingAbsentFields',[])
            monthly_cell=rec['role']=='roster' and field in MONTHLY_FIELDS
            if val in ('',None) and not opening_absent and not monthly_cell: continue
            old=row['original'].get(field)
            evidence={**ref,'role':rec['role'],'column':rec['fieldColumns'].get(field),'value':val,'rawValue':rec.get('rawValues',{}).get(field,val)}
            if field=='候选人入职时间' and rec['role']=='roster' and rec['fieldColumns'].get(field) is not None and rec['fieldColumns'][field]==rec['fieldColumns'].get('入职日期'):
                evidence['derivedFrom']='入职日期'
            refs=row['provenance'].setdefault(field,[])
            if evidence not in refs: refs.append(evidence)
            if observe_only or (monthly_cell and ref['sourceId'] not in current_sources) or (row.get('frozenRecruitmentFacts') and field in SNAPSHOT_FIELDS
                                and rec['role'] in {'roster','domestic_offer','overseas_offer'}): continue
            prior_roster=any(p.get('role')=='roster' and p!=evidence
                            and (not monthly_cell or p['sourceId'] in current_sources) for p in refs)
            dynamic_refresh=field in DYNAMIC and rec['role']=='roster' and not prior_roster
            if monthly_cell and field not in row.setdefault('monthlyRosterFields',[]):row['monthlyRosterFields'].append(field)
            equivalent=False
            if field=='ABC类别':
                before=text(old).replace('类','').replace('C1','C')
                after=text(val).replace('类','').replace('C1','C')
                domestic=row['original'].get('标签分类')=='国内' or rec['role']=='domestic_offer'
                equivalent=before==after or (domestic and {before,after}=={'C','不占编'})
            if field=='招聘渠道':
                before,before_unknown=_normalize_offer_channel(old,row['original'].get('其他渠道'),_channel_notes(row['original']))
                after,after_unknown=_normalize_offer_channel(val,rec['values'].get('其他渠道'),_channel_notes(rec['values']))
                equivalent=before==after and before not in {'','其他'} and not before_unknown and not after_unknown
            if field.endswith('工号'): equivalent=staff_id(old)==staff_id(val)
            if field=='海外招聘需求编号':equivalent=text(old).removesuffix('.0')==text(val).removesuffix('.0')
            if (old not in ('',None) or opening_absent and field in row['original'] or monthly_cell and prior_roster) and old!=val and not equivalent and not dynamic_refresh and not field.startswith('原始'):
                # Two observed source values need a decision, regardless of upload order.
                conflict={'field':field,'values':[old,val],'sourceId':ref['sourceId']}
                if conflict not in row['conflicts']: row['conflicts'].append(conflict)
            if (old in ('',None) and not opening_absent and not (monthly_cell and prior_roster)) or overwrite or dynamic_refresh or (opening_absent and ref['sourceId']==state.get('baseline')):
                row['original'][field]=val
    for rec in records:
        checkpoint()
        role=rec['role']; v=rec['values']
        if role=='roster':
            if text(v.get('是否虚拟员工'))=='是': continue
            if text(v.get('工号')): people[text(v['工号']).lower()].append(rec)
        elif role in {'domestic_offer','overseas_offer'}:
            validity=offer_validity(v,role)
            target=offers if validity['state'] in {'valid','absent'} else unusable_offers
            for field in ('工号','证件号','海外offer流程编号'):
                if text(v.get(field)): target[(field,text(v[field]).lower())].append(rec)
        elif role=='resignation':
            if text(v.get('工号')): resignations[text(v['工号']).lower()].append(rec)
    # Historical and explicit supplement rows are retained even when incomplete.
    candidates=[r for r in records if r['role'] in {'ledger','supplement'}]
    candidates.sort(key=lambda r: 0 if r['ref']['sourceId']==state.get('baseline') else 1)
    for rec in candidates:
        checkpoint()
        row=row_for(rec)
        if state.get('strictInputs') and rec['ref']['sourceId']==state.get('baseline'):
            # The user's field-source contract keeps historical recruitment
            # facts unchanged; monthly Offers populate new hires only. A full
            # opening schema (including blanks) is distinct from a partial list.
            if {'招聘渠道','ABC类别','招聘启动日期'} <= set(rec.get('availableFields',rec['fieldColumns'])):
                row['openingFactsSource']=rec['ref']
            cells={c['column']:c['value'] for c in rec.get('historyCells',[])}
            for fields,amount_cols in ((('协助招聘人工号','协助招聘人姓名'),(45,46,48,50,54)),
                                       (('推荐人工号','推荐人姓名'),(61,62,64,66,68))):
                if all(f in rec['fieldColumns'] and text(rec['values'].get(f)) in {'','-','无'} for f in fields) and not any(cells.get(c) not in (None,'',0,'0') for c in amount_cols):
                    row['openingAbsentFields'].extend(fields)
        apply(row,rec)
        if rec['role']=='ledger' or _date(row['original']) and _date(row['original'])[:7].replace('-','')<str(month):
            row['frozenRecruitmentFacts']=True
        if rec['role']=='ledger':
            if any(h['ref']['sourceId']==rec['ref']['sourceId'] and h['ref']!=rec['ref'] for h in row['history']):
                todo('duplicate_source_row','同一台账存在重复任职记录',rec['ref']['sourceId'],row['id'],'保留所有原始行；需核对是否重复或需要进一步区分任职。',source_id=rec['ref']['sourceId'])
            row['history'].append({'ref':rec['ref'],'cells':rec.get('historyCells',[]),'paymentStatus':'unverified',
                                   'isBaseline':rec['ref']['sourceId']==state.get('baseline')})
    opening_people=defaultdict(list)
    if state.get('strictInputs'):
        for row in rows.values():
            if any(h['isBaseline'] for h in row['history']) and staff_id(row['original'].get('工号')):
                opening_people[staff_id(row['original']['工号'])].append(row)
    excluded_intake={};eligible_intake=set()
    for rec in records:
        checkpoint()
        if rec['role']!='roster' or rec['ref']['sourceId'] not in current_sources or rec.get('lookupOnly'): continue
        if text(rec['values'].get('是否虚拟员工'))=='是': continue
        start=_date(rec['values'])
        if start and (start[:7].replace('-','')==str(month) or (rec.get('continuityEvidence') and str(rec['values'].get('人事入职日期',''))[:7].replace('-','')==str(month))):
            key=record_keys.get(id(rec),_identity(rec['values'],rec['ref']))
            reason=_intake_exclusion(rec['values'])
            if reason:
                excluded_intake[key]=reason
                if reason=='otherSource' and not text(rec['values'].get('人员来源')):
                    row=row_for(rec);apply(row,rec,set(rec['values'])-OFFER_FIELDS)
                    row['intakeScopeUnknown']=True
                continue
            eligible_intake.add(key)
            row=row_for(rec);apply(row,rec,set(rec['values'])-OFFER_FIELDS)
            alternatives=[r for r in opening_people.get(staff_id(rec['values'].get('工号')),[]) if _date(r['original'])!=start]
            if alternatives and not row['history']:
                row['employmentCandidates']=[{'rowId':r['id'],'hireDate':_date(r['original']),'source':next(h['ref'] for h in r['history'] if h['isBaseline'])} for r in alternatives]
    # Keep previously saved rows even if a source is replaced or removed from use.
    for key,old in old_by_key.items():
        checkpoint()
        if key not in rows:
            # Rebuild an old automatic cohort using the corrected source rule.
            # Historical, explicit and reviewed records are never discarded.
            if (key in excluded_intake and not old.get('history') and old['id'] not in reviewed
                and 'supplement' not in old.get('originKinds',[]) and 'ledger' not in old.get('originKinds',[])):
                continue
            old_identity=(staff_id(old['values'].get('工号')),_date(old['values']))
            if old_identity in virtual | replaced and not old.get('history') and old['id'] not in edited: continue
            if (not old.get('history') and old['id'] not in edited and 'supplement' not in old.get('originKinds',[])
                and text(old['values'].get('任职说明')).startswith('任职延续：北森')
                and str(old['values'].get('人事入职日期',''))[:7].replace('-','')!=str(month)): continue
            row=deepcopy(old); row.pop('identityConflict',None)
            if key in old_identity_conflicts:row['identityConflict']=old_identity_conflicts[key]
            row['conflicts']=[]; row['edits']=[]; row['monthlyRosterFields']=[]; rows[key]=row
            missing=unavailable_origins(old)
            row.pop('unavailableSourceIds',None)
            if missing:row['unavailableSourceIds']=missing
            if _date(old['values']) and _date(old['values'])[:7].replace('-','')<str(month):row['frozenRecruitmentFacts']=True
            if not any(s['id'] in {r['sourceId'] for r in old['sources']} and s.get('active',True) for s in state['sources']):
                todo('source_removed','人员来源已停用，核对保留范围',key,row['id'])
    for row in rows.values():
        checkpoint()
        if row.get('unavailableSourceIds'):
            row['identityConflict']='原始来源不可验证：'+','.join(row['unavailableSourceIds'])
    # Snapshot employment anchors before enriching rows with Offers. Otherwise
    # an earlier row's imported Offer can change how a later row is matched.
    employment_facts=defaultdict(list); effective_facts={}
    for row in rows.values():
        checkpoint()
        facts={**row['original'],**{e['field']:e['value'] for e in state.get('edits',[]) if e['rowId']==row['id'] and e.get('active',True)}}
        effective_facts[row['id']]=facts
        for field in ('工号','证件号'):
            if text(facts.get(field)):
                employment_facts[(field,text(facts[field]).lower())].append(facts)
    continuations=defaultdict(set)
    for rid,facts in effective_facts.items():
        checkpoint()
        note=text(facts.get('任职说明'))
        if facts.get('核算范围')!='不纳入核算' or not note.startswith('任职延续'): continue
        # Reuse the explicitly reviewed link, never infer continuity merely
        # from matching names or adjacent dates. A later reversal removes it.
        for target in re.findall(r'沿用原招聘任职\s*([a-f0-9]{24})(?![a-f0-9])',note):
            prior=effective_facts.get(target,{})
            same_person=any(text(facts.get(f)) and text(facts[f]).lower()==text(prior.get(f)).lower() for f in ('工号','证件号','体系外人员编号'))
            if same_person and _date(prior) and _date(facts)>_date(prior) and prior.get('核算范围')!='不纳入核算':
                continuations[target].add(_date(facts))
    def same_offer(offer,facts):
        for anchor in ('海外offer流程编号','海外招聘需求编号','招聘启动日期'):
            if text(facts.get(anchor)) and text(offer.get(anchor))==text(facts[anchor]):
                return True
        return bool(_date(offer) and _date(offer)==_date(facts))
    for row in rows.values():
        checkpoint()
        v=row['original']; no=text(v.get('工号')).lower(); start=_date(v)
        link_values={**v,**{e['field']:e['value'] for e in state.get('edits',[]) if e['rowId']==row['id'] and e.get('active',True)}}
        matched=[p for p in people.get(no,[]) if _date(p['values'])==start]
        for rec in matched:
            apply(row,rec,DYNAMIC)
            if row.get('identityConflict'):apply(row,rec,IDENTITY,observe_only=True)
        roster_starts={_date(p['values']) for p in people.get(no,[]) if _date(p['values'])}
        # Diagnostic evidence stays separate from adopted recruitment facts.
        # In particular, an unmatched roster date must not overwrite this hire.
        row['employmentObservations']=[{**p['ref'],'value':_date(p['values']),'role':'roster'}
                                       for p in people.get(no,[]) if _date(p['values'])]
        # A roster date change on the exact same overseas Offer is not a new
        # recruitment. Preserve the original ledger date and current HR dates.
        offer_anchor=text(link_values.get('海外offer流程编号'))
        same_offer_roster=[p for p in people.get(no,[]) if offer_anchor and
                           text(p['values'].get('海外offer流程编号'))==offer_anchor]
        same_offshore_hire=bool(row.get('frozenRecruitmentFacts') and link_values.get('标签分类')=='海外'
                               and len(roster_starts)==1 and same_offer_roster
                               and len(same_offer_roster)==len(people.get(no,[]))
                               and start and next(iter(roster_starts))[:7]==start[:7]
                               and link_values.get('是否二次入职')!='是')
        if same_offshore_hire:
            for rec in same_offer_roster:apply(row,rec,DYNAMIC)
            row['recruitmentContinuityBasis']={'description':'上月核算表与花名册的录用流程相同，沿用原招聘入职日',
                'offerId':offer_anchor,'sources':[p['ref'] for p in same_offer_roster]}
        row['offerObservations']=[];invalid_offers=[]
        for field in ('工号','证件号','海外offer流程编号'):
            for rec in unusable_offers.get((field,text(link_values.get(field)).lower()),[]):
                if _date(rec['values']) and _date(rec['values'])!=start:continue
                if rec not in invalid_offers:invalid_offers.append(rec)
        label=text(link_values.get('标签分类'))
        match_fields=('证件号','工号') if label=='国内' else ('海外offer流程编号',) if label=='海外' else ('海外offer流程编号','证件号','工号')
        def offer_candidates(field):
            found=offers.get((field,text(link_values.get(field)).lower()),[]) if link_values.get(field) else []
            if label in {'国内','海外'}:
                found=[p for p in found if p['role']==('domestic_offer' if label=='国内' else 'overseas_offer')]
            if label=='国内' and field=='工号':
                cert=text(link_values.get('证件号')).lower()
                # A plain job-number match never outranks the workbook's ID
                # join. The API may supply its proven employee -> LUOffer link
                # when an ID card is unavailable; it cannot override a mismatch.
                found=[p for p in found if (cert and text(p['values'].get('证件号')).lower()==cert)
                       or (not text(p['values'].get('证件号')) and p.get('apiEvidence',{}).get('offerId')
                           and p.get('apiEvidence',{}).get('userId'))]
            return found
        for field in match_fields:
            for p in offer_candidates(field):
                observation={**p['ref'],'hireDate':_date(p['values']),
                             'recruitmentStart':text(p['values'].get('招聘启动日期')),
                             'employmentForm':text(p['values'].get('录用用工形式')),
                             'position':text(p['values'].get('录用岗位')),
                             'recruiter':text(p['values'].get('招聘负责人姓名') or p['values'].get('招聘负责人工号'))}
                if observation not in row['offerObservations']:row['offerObservations'].append(observation)
        last=date_text(link_values.get('最后工作日'))
        closed_before_roster=bool(start and last and start<=last and roster_starts and last<min(roster_starts))
        employment_confirmed=(same_offshore_hire or text(link_values.get('任职说明')).startswith(('二次入职','新增任职','任职延续')) or
                              bool(roster_starts) and roster_starts <= ({start} | continuations[row['id']]))
        if start and roster_starts and start not in roster_starts and not closed_before_roster and not employment_confirmed:
            todo('employment_conflict','花名册与台账任职日期不同',no,row['id'],'可能是二次入职或调动，保留两份日期并核对任职关系。')
        linked=[];row.pop('offerMatchBasis',None)
        for field in match_fields:
            found=offer_candidates(field)
            if found:
                api_anchored=False
                if label=='国内' and field=='证件号':
                    proofs=[p for p in offer_candidates('工号') if _date(p['values'])==start
                            and p.get('apiEvidence',{}).get('offerId') and p.get('apiEvidence',{}).get('userId')]
                    proof_ids={(p['apiEvidence']['userId'],p['apiEvidence']['offerId']) for p in proofs}
                    if len(proof_ids)==1:
                        requirements={text(p['values'].get('海外招聘需求编号')) for p in proofs
                                      if text(p['values'].get('海外招聘需求编号'))}
                        matches=[p for p in found if text(p['values'].get('海外招聘需求编号')) in requirements
                                 and (not _date(p['values']) or _date(p['values'])==start)]
                        if len(requirements)==1 and matches:
                            found=matches+proofs
                            api_anchored=True
                            row['offerMatchBasis']={'reason':'身份证对应的录用资料按北森本次任职关联的招聘需求匹配，不沿用上一段招聘。',
                                                   'sources':[p['ref'] for p in proofs]}
                anchored=field=='海外offer流程编号' or api_anchored
                employments=employment_facts.get((field,text(link_values.get(field)).lower()),[])
                # A personal identifier identifies a person, not a recruitment.
                # Never attach a dated Offer to another employment, or reuse an
                # Offer already anchored to another historical recruitment.
                if not anchored:
                    found=[r for r in found if not _date(r['values']) or _date(r['values'])==start]
                    found=[r for r in found if same_offer(r['values'],link_values) or not any(
                        _date(other)!=start and same_offer(r['values'],other) for other in employments)]
                    if not found: continue
                    dated=[r for r in found if _date(r['values'])==start]
                    if dated: found=dated; anchored=True
                if not anchored:
                    for anchor in ('海外招聘需求编号','招聘启动日期'):
                        target=text(link_values.get(anchor))
                        matches=[r for r in found if target and text(r['values'].get(anchor))==target]
                        if matches:
                            found=matches;anchored=True;break
                # Use the historical internship Offer only after continuity
                # was explicitly verified. A later contract Offer belongs to
                # the conversion, not a second recruitment. Multiple internship
                # Offers or different historical hire dates still need review.
                if not anchored and text(link_values.get('任职说明')).startswith('任职延续') and '实习' in text(link_values.get('职位')):
                    historical_starts={_date(other) for other in employments if _date(other)}
                    interns=[r for r in found if text(r['values'].get('录用用工形式')) in {'实习生日薪','实习生月薪','实习','实习用工'}]
                    if len(interns)==1 and historical_starts=={start}:
                        found=interns;anchored=True
                        row['offerMatchBasis']={'reason':'已核实任职延续，采用唯一的原实习录用记录；后续合同用工不作为新增招聘。',
                                              'sources':[interns[0]['ref']]}
                known_starts=roster_starts | {_date(other) for other in employments if _date(other)}
                if not anchored and (len(known_starts)>1 or (known_starts and start not in known_starts)):
                    todo('offer_employment','Offer无法唯一对应本次任职',no or row['id'],row['id'])
                    continue
                linked=found; break
        row['offerMatched']=bool(linked)
        row['offerStatusObservations']=[{**rec['ref'],**offer_validity(rec['values'],rec['role'])} for rec in invalid_offers]
        if not linked:
            for rec in invalid_offers:
                validity=offer_validity(rec['values'],rec['role'])
                todo('offer_status','录用资料状态待核',rec['ref']['sourceId'],row['id'],validity['reason']+'：'+(validity['status'] or '作废标记'),rec['ref']['sourceId'])
        offer_ids={rec.get('apiEvidence',{}).get('offerId') for rec in linked}
        row['channelChecks']=[{**check,'sourceId':s['id']} for s in state['sources'] if s.get('active',True)
                              for check in s.get('channelChecks',[]) if check.get('offerId') in offer_ids]
        for rec in linked:
            permitted=set(rec['values'])-IDENTITY-{'姓名','入职日期','候选人入职时间','状态','审批状态','录用用工形式','录用岗位'}
            observed=permitted & (SNAPSHOT_FIELDS-OFFER_FIELDS)
            apply(row,rec,observed,observe_only=True)
            apply(row,rec,permitted-observed,
                  observe_only=bool(row.get('frozenRecruitmentFacts')))
        row['pendingResignations']=[];completed_exit_dates=set()
        for rec in resignations.get(no,[]):
            rv=rec['values']; last=date_text(rv.get('最后工作日')); entry=_date(rv)
            status=text(rv.get('审批状态'))
            if text(rv.get('是否作废'))=='是' or status in {'已废弃','已驳回','已撤回','已撤销','已取消','作废','驳回','撤回'}: continue
            known_starts=roster_starts | {_date(other) for other in employment_facts.get(('工号',no),[]) if _date(other)}
            applicable=(entry and entry==start) or (not entry and last and start and last>=start and len(known_starts)<=1)
            if not applicable: continue
            if status not in {'已通过','审批通过','已完成','已结束','完成','审批结束'}:
                reviewed=any(e['rowId']==row['id'] and e['field']=='最后工作日' and e.get('active',True) for e in state.get('edits',[]))
                if last and last>=start and last[:7].replace('-','')<=str(month) and not reviewed:
                    row['pendingResignations'].append({'lastDay':last,'status':status or '未提供',
                                                      'source':deepcopy(rec['ref'])})
                continue
            apply(row,rec,{'最后工作日'})
            completed_exit_dates.add(last)
        # Reimporting a final result for the same employment/date supersedes
        # the older pending snapshot; a different proposed date remains distinct.
        row['pendingResignations']=[r for r in row['pendingResignations'] if r['lastDay'] not in completed_exit_dates]
        for pending in row['pendingResignations']:
            todo('resignation_review','离职资料最终状态待核',no,row['id'],source_id=pending['source']['sourceId'])
        # Offer/ledger snapshots do not contradict a unique current roster fact.
        # Keep every source value for inspection; competing roster facts and
        # approved resignation facts still require an explicit resolution.
        for field in DYNAMIC:
            refs=row['provenance'].get(field,[])
            roster_values={staff_id(p['value']) if field.endswith('工号') else p['value'] for p in refs if p.get('role')=='roster'}
            if len(roster_values)==1:
                authoritative={p['sourceId'] for p in refs if p.get('role') not in {'ledger','domestic_offer','overseas_offer'}}
                row['conflicts']=[c for c in row['conflicts'] if c['field']!=field or c['sourceId'] in authoritative]
        row['values']=dict(row['original']); row['values']['核算月份']=month
        for edit in state.get('edits',[]):
            if edit['rowId']==row['id'] and edit.get('active',True):
                row['values'][edit['field']]=edit['value']; row['edits'].append(edit)
        v=row['values']
        date_refs=row['provenance'].get('候选人入职时间',[])
        if (any(e['field']=='入职日期' for e in row['edits']) and not any(e['field']=='候选人入职时间' for e in row['edits'])
            and date_refs and all(p.get('derivedFrom')=='入职日期' for p in date_refs)):
            # These two worksheet cells came from one roster column. Correcting
            # that source date should not manufacture a second conflicting date.
            v['候选人入职时间']=v['入职日期']
        enrich(row,employment_index,ROLE_FIELDS)
        note_fields=('其他渠道','招聘渠道说明','招聘渠道备注','人工备注')
        note_refs=[p for f in note_fields for p in row['provenance'].get(f,[]) if p.get('value')]
        notes=_channel_notes(v)
        # Retain all same-employment observations, independent of upload order.
        notes += [p['value'] for f in note_fields[1:] for p in row['provenance'].get(f,[]) if p.get('value')]
        raw_channel=v.get('招聘渠道')
        if not row.get('frozenRecruitmentFacts') and not any(e['field']=='招聘渠道' for e in row['edits']) and v.get('原始招聘渠道')=='其他':
            raw_channel='其他'
        v['_channelNotes']=list(dict.fromkeys(notes))
        normalized_channel,channel_unknown=_normalize_offer_channel(raw_channel,v.get('其他渠道'),notes)
        if normalized_channel and normalized_channel!='其他' and not channel_unknown:
            v.setdefault('原始招聘渠道',v.get('招聘渠道'))
            v['招聘渠道']=normalized_channel
        if raw_channel=='其他':
            v['招聘渠道']=normalized_channel
            v['渠道待核']=channel_unknown
            categories=_channel_note_categories(notes)
            detail,unknown=_normalize_offer_channel('其他',v.get('其他渠道'))
            if not unknown:categories.add(detail)
            if len(categories)>1:
                row['conflicts'].append({'field':'招聘渠道','values':sorted(categories),
                    'sourceId':note_refs[-1]['sourceId'] if note_refs else '', 'reason':'渠道说明及备注不一致'})
            row['channelResolution']={'original':'其他','channel':normalized_channel,'resolved':not channel_unknown,
                'sources':note_refs,'description':'按已导入的渠道说明及备注识别' if not channel_unknown else '渠道说明及备注不一致' if len(categories)>1 else '现有说明及备注仍无法唯一确定渠道'}
        # Recipient facts keep original roster status and employment start, separately from the candidate.
        row['recipientSourceRegions']={};row['recipientEmploymentEvidence']={}
        for id_field,prefix,name_field,status_field in ROLE_FIELDS:
            recipient=staff_id(v.get(id_field))
            if any(e['field']==id_field and staff_id(e['before'])!=recipient for e in row['edits']):
                # A different recipient cannot inherit the previous recipient's employment facts.
                explicit={e['field'] for e in row['edits']}
                for field in (name_field,status_field,prefix+'入职日期',prefix+'最后工作日',prefix+'职级',prefix+'职位',prefix+'转正日期'):
                    if field not in explicit: v.pop(field,None)
            if not recipient or recipient=='-': continue
            v[id_field]=recipient
            matches=people.get(recipient,[])
            regions={m['values'].get('标签分类') for m in matches if m['role']=='roster' and m['values'].get('标签分类')}
            if len(regions)==1:row['recipientSourceRegions'][prefix]=next(iter(regions))
            spans={_date(m['values']) for m in matches}
            recipient_refs=row['provenance'].get(id_field,[])
            foreign_identity=any(text(value).lower().startswith('海外-') for value in
                [row['original'].get(id_field)]+[ref.get('value') for ref in recipient_refs])
            virtual_recipient=recipient in virtual_numbers and foreign_identity
            if virtual_recipient:
                row['recipientSourceRegions'][prefix]='海外'
            row['recipientEmploymentEvidence'][prefix]={'covered':bool(matches and len(spans)==1 and '' not in spans
                and all(text(m['values'].get('人员状态')) for m in matches) and not virtual_recipient),
                'virtual':virtual_recipient,'sources':[m['ref'] for m in matches]}
            if len(spans)==1 and matches:
                for dest,src in ((name_field,'姓名'),(status_field,'人员状态'),(prefix+'入职日期','入职日期'),(prefix+'最后工作日','最后工作日'),
                                 (prefix+'职级','职级'),(prefix+'职位','职位'),(prefix+'转正日期','转正日期')):
                    observed=[]
                    monthly=src in MONTHLY_FIELDS
                    current_matches=[rec for rec in matches if rec['ref']['sourceId'] in current_sources]
                    selected=current_matches if monthly and current_matches else matches
                    for rec in selected:
                        value=rec['values'].get(src)
                        monthly_cell=monthly and src in rec['fieldColumns'] and rec['ref']['sourceId'] in current_sources
                        if value in ('',None) and not monthly_cell: continue
                        if value not in observed: observed.append(value)
                        row['provenance'].setdefault(dest,[]).append({**rec['ref'],'role':'roster','column':rec['fieldColumns'].get(src),'value':value,'rawValue':rec.get('rawValues',{}).get(src,value)})
                    if any(e['field']==dest for e in row['edits']): continue
                    if row.get('frozenRecruitmentFacts') and dest in SNAPSHOT_FIELDS:continue
                    if dest==name_field and text(v.get(dest)) not in {'','-','无'}:continue
                    if len(observed)>1:
                        if not text(v.get(dest)):v[dest]=next((value for value in observed if text(value)),observed[0])
                        conflict={'field':dest,'values':observed,'sourceId':selected[-1]['ref']['sourceId']}
                        if conflict not in row['conflicts']:row['conflicts'].append(conflict)
                        task=todo('recipient_conflict','领取人资料存在不同值',recipient+'|'+src,row['id'],detail='并列保留来源，请选择有效事实。')
                        task.update(recipientId=recipient,field=dest)
                    elif observed and not (row.get('frozenRecruitmentFacts') and dest in SNAPSHOT_FIELDS): v[dest]=observed[0]
            elif not matches and not row.get('employmentTimelines',{}).get(prefix) and not (v.get(prefix+'入职日期') and v.get(status_field)):
                todo('missing_recipient',f'补充领取人 {text(v.get(id_field))} 的任职资料',recipient,row['id'],'补充一次可更新所有关联人员。')['recipientId']=recipient
            elif len(spans)>1:
                todo('recipient_employment','领取人有多段任职，需确定适用时点',recipient,row['id'])['recipientId']=recipient
        org=' '.join(text(v.get(f)) for f in ('二级组织','三级组织','四级组织','五级组织'))
        region=_classify_overseas_country(org)
        source_region=bool(row.get('frozenRecruitmentFacts') or any(e['field']=='标签分类' for e in row['edits'])
                           or any(p.get('role')=='roster' for p in row['provenance'].get('标签分类',[])))
        if source_region and v.get('标签分类')=='国内':
            v['标签分类']='国内'; v['奖金地区类型']='国内发展中国家'
        elif source_region and v.get('标签分类')=='海外':
            region=region or _classify_overseas_country(text(v.get('工作地')))
            if region:v['奖金地区类型']=region
        elif _confirmed_domestic_scope(v):
            v['标签分类']='国内'; v['奖金地区类型']='国内发展中国家'
        elif region:
            v['标签分类']='海外'; v['奖金地区类型']=region
        elif _is_domestic_location(org):
            v['标签分类']='国内'; v['奖金地区类型']='国内发展中国家'
        else:
            region=_normalized_region_type(v)
            if region.startswith('海外'): v['标签分类']='海外'
            elif region.startswith('国内'): v['标签分类']='国内'
            if region: v['奖金地区类型']=region
        if v.get('标签分类')=='国内' and text(v.get('ABC类别'))=='不占编':
            v['原始ABC类别']='不占编'; v['ABC类别']='C'
        if v.get('标签分类')=='国内' and any(text(ref.get('rawValue',ref.get('value')))=='不占编' for ref in row['provenance'].get('ABC类别',[])):
            v['原始ABC类别']='不占编'
        if v.get('标签分类')=='海外':
            v['转正日期']=''
            row['conflicts']=[c for c in row['conflicts'] if c['field']!='转正日期']
        edited_fields={e['field'] for e in row['edits']}
        unresolved=[c for c in row['conflicts'] if c['field'] not in edited_fields]
        for conflict in unresolved:
            todo('source_conflict',f"核对不同来源的{conflict['field']}",conflict['field']+'|'+conflict['sourceId'],row['id'],source_id=conflict['sourceId'])
        version_conflict=any(c['field'] in {'入职日期','候选人入职时间'} for c in unresolved)
        employment_pending=bool(row.get('employmentCandidates')) and not text(v.get('任职说明')).startswith(('二次入职','新增任职')) and v.get('核算范围')!='不纳入核算'
        if employment_pending:
            todo('employment_conflict','同一人员出现新的入职日，确认是否新增任职',row['id'],row['id'],
                 '期初已存在该人员。核对属于任职延续还是确有新的招聘；确认前不生成第二份奖金。')
        identity_observation=not row.get('unavailableSourceIds') and identity_discrepancy_is_observation(row)
        row.pop('identityDiscrepancy',None)
        if row.get('identityConflict'):
            if identity_observation:
                row['identityDiscrepancy']={'field':'证件号','sources':row['provenance'].get('证件号',[]),
                    'description':'工号、实际入职日和本次录用关系一致，证件来源存在格式差异。'}
                if '证件号' not in edited_fields:todo('identity','核对证件来源差异',row['identityConflict'],row['id'],row['identityDiscrepancy']['description'])
            else:todo('employment_conflict','任职标识互相矛盾或对应多条已有记录',row['identityConflict'],row['id'],'保留原记录及操作，核对同一入职日下的人员标识，避免重复计奖。')
        scope_confirmed=(v.get('核算范围')=='不纳入核算' or
                         v.get('核算范围')=='纳入核算' and v.get('标签分类') in {'国内','海外'})
        if row.get('intakeScopeUnknown') and scope_confirmed:
            row.pop('intakeScopeUnknown',None)
            if v.get('核算范围')=='纳入核算':
                eligible_intake.add(row['key']);excluded_intake.pop(row['key'],None)
            else:
                eligible_intake.discard(row['key']);excluded_intake[row['key']]='reviewedOutOfScope'
        if row.get('intakeScopeUnknown'):
            todo('coverage','人员来源范围待核',row['key'],row['id'],'已保留人员，现有列无法证明国内或海外入组范围。')
        row['rule']=_rule(row,version_conflict or employment_pending or bool(row.get('identityConflict') and not identity_observation) or bool(row.get('intakeScopeUnknown')))
        row['scopeStatus']=scope_status(v)
        if row['rule']['version']=='unresolved': todo('hire_date','核对本次实际入职日期',row['id'],row['id'])

        if not row['offerMatched'] and 'roster' in row['originKinds'] and 'ledger' not in row['originKinds'] and 'supplement' not in row['originKinds'] and v.get('核算范围') not in {'纳入核算','不纳入核算'}:
            scope=text(v.get('标签分类')) or '地区待核'
            todo('missing_offer',f'{scope}人员待补Offer或核对调动范围',scope,row['id'],'人员仍在底稿内，未据此判断奖金为0。')
        if v.get('渠道待核') and '招聘渠道' not in edited_fields:
            todo('channel','核对其他渠道',text(v.get('其他渠道')),row['id'])
        channel=text(v.get('招聘渠道'))
        transfer=channel in {'跨体系调动','跨主体调动','内部调动','体系内调动','调动'}
        if transfer: row['scopeStatus']='调动记录，保留核对'
        else:
            required=['ABC类别','职级','招聘渠道','招聘启动日期','标签分类','招聘负责人工号']
            missing=[f for f in required if not text(v.get(f))]
            if missing:
                todo('missing_fields','补充核算所需信息：'+'、'.join(missing),'|'.join(missing),row['id'])
            if channel in {'二次入职','返聘'} or v.get('是否二次入职')=='是':
                if not date_text(v.get('上次离职日期')):
                    todo('previous_exit','二次入职：上一段离职日期待核','previous_exit',row['id'],'保留人工依据入口；本阶段不按缺失值推算奖金。')
        row['unresolvedFields']=sorted({c['field'] for c in unresolved})
        from .recruitment_field_controls import invalidate_source_choices
        invalidate_source_choices(state,row)
        if row.get('continuityEvidence'):
            row['offerMatchBasis']={'reason':'北森前后任职连续且关联同一实习录用记录，招聘奖金沿用原招聘日期。','sources':[row['continuityEvidence']]}
        row['employmentContext']={'recruitmentHireDate':_date(v),'hrHireDates':sorted({p['values'].get('人事入职日期') or _date(p['values']) for p in people.get(no,[]) if _date(p['values'])}),
                                  'probationDate':date_text(v.get('转正日期')),
                                  'continuationConfirmed':text(v.get('任职说明')).startswith('任职延续'),
                                  'offerMatchBasis':row.get('offerMatchBasis')}
        active_ops={o['id'] for o in state.get('operations',[]) if o['active']}
        row['awardDecisions']=[d for d in state.get('awardDecisions',[]) if d['rowId']==row['id'] and d['operationId'] in active_ops]
    monthly_queries={s['id'] for s in state['sources'] if s.get('forMonth')==month and s.get('dataDigest')
                     and (s.get('monthlyRoster') or s.get('kind')=='overseas_api')
                     and s.get('active',True) and not s.get('comparisonOnly') and not s.get('error')}
    for source in state['sources']:
        checkpoint()
        if source.get('purpose')=='external-results':continue
        if not source.get('active',True): continue
        if source.get('error'):
            todo('source_error','资料读取失败，可重新上传',source['id'],detail=source['error'],source_id=source['id'])
        elif source.get('attachment') or 'approval' in source.get('roles',[]):
            active_ops={o['id'] for o in state.get('operations',[]) if o['active']}
            review=next((r for r in reversed(state.get('reviewEntries',[])) if r['sourceId']==source['id'] and (not r.get('operationId') or r['operationId'] in active_ops)),None)
            if not review or not review.get('applied') or not review.get('scopeComplete'):
                title='核对审批范围及附件' if not review else ('审批剩余范围待核' if review.get('applied') else '审批附件待补齐' if review.get('missingAttachments') else '审批'+review['status'])
                from .recruitment_assignments import missing_attachments
                missing=missing_attachments(state,source)
                detail=source['name']
                if missing:title='补充审批引用的附件';detail+='：缺少 '+'、'.join(missing)
                todo('attachment_review',title,source['id'],detail=detail,source_id=source['id'])
        elif not source.get('recordCount') and source['id'] not in monthly_queries and not (source.get('channelDetailsOnly') and source.get('channelDetailsCheckedOfferIds')):
            todo('source_unrecognized','资料未识别到人员记录',source['id'],detail=source['name'],source_id=source['id'])
    if not state.get('baseline') and not state.get('parentMonth') and not state.get('openingEmptyConfirmed'):
        todo('baseline','首次使用：选择可信期初','baseline',detail='历史金额和月份会保留；认可期初不等于确认实际已付。')
    has_roster=bool(monthly_queries) or any(s.get('active',True) and not s.get('comparisonOnly') and not s.get('error')
        and s.get('forMonth',month)==month and 'roster' in s.get('roles',[]) for s in state['sources'])
    if not has_roster: todo('coverage','补充本期花名册以核对人员覆盖','roster')
    out=sorted(rows.values(),key=lambda r:(_date(r['values']),text(r['values'].get('工号')),r['id']))
    counts=Counter(r['rule']['version'] for r in out)
    todo_rows={rid for t in grouped.values() for rid in t['rowIds']}
    for row in out: row['needsReview']=row['id'] in todo_rows
    state.update(rows=out,todos=list(grouped.values()),paymentReady=False,
        intakeSummary={'month':month,'eligibleNewHires':len(eligible_intake),
                       'parsedRosterRecords':sum(rec['role']=='roster' and rec['ref']['sourceId'] in current_sources for rec in records),
                       'unknownScope':sum(bool(r.get('intakeScopeUnknown')) for r in out),
                       'excludedByReason':dict(Counter(reason for key,reason in excluded_intake.items() if key not in eligible_intake and not rows.get(key,{}).get('intakeScopeUnknown')))},
        summary={'people':len(out),'newHires':sum(_date(r['values'])[:7].replace('-','')==str(month) for r in out),
                 'oldRule':counts['legacy'],'newRule':counts['2026-07'],'unresolvedRule':counts['unresolved'],
                 'todoGroups':len(grouped),'reviewPeople':len(todo_rows),'baselineConfirmed':bool(state.get('baseline')),
                 'rosterRecords':sum(s.get('roleCounts',{}).get('roster',0) for s in state['sources'] if s.get('active',True)),
                 'ledgerRows':sum(s.get('roleCounts',{}).get('ledger',0) for s in state['sources'] if s.get('active',True)),
                 'sourceOnlyNewHires':sum(_date(r['values'])[:7].replace('-','')==str(month) and 'ledger' not in r['originKinds'] for r in out),
                 'resignationRecords':sum(s.get('roleCounts',{}).get('resignation',0) for s in state['sources'] if s.get('active',True))})
    return state

class DraftStore:
    def __init__(self, root): self.root=Path(root)

    def _folder(self,month):
        if not re.fullmatch(r'20\d{4}',str(month)) or int(month)%100 not in range(1,13): raise ValueError('核算月份格式无效')
        return self.root/str(month)

    @contextmanager
    def _lock(self,month):
        # OS file lock covers concurrent requests and multiple worker processes.
        import fcntl
        folder=self._folder(month); folder.mkdir(parents=True,exist_ok=True)
        with (folder/'.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            try: yield folder
            finally: fcntl.flock(lock,fcntl.LOCK_UN)

    def read(self,month,*,_refresh_changes=None):
        path=self._folder(month)/'draft.json'
        state=json.loads(path.read_text()) if path.exists() else _empty(month)
        changed=self._source_digests(path.parent,state)
        generated=any(e.get('active',True) and (e.get('referenceFact') or e.get('employmentBasis')) for e in state.get('edits',[]))
        if generated and not changed and state.get('assemblyVersion')==ASSEMBLY_VERSION:
            from . import recruitment_reference_facts as reference
            from .recruitment_employment import valid_employment_edit
            catalog=reference._catalog(path.parent,state,True)
            effective,stale=reference.effective_edits(path.parent,state,catalog)
            changed=bool(stale) or any(e.get('active',True) and e.get('employmentBasis') and
                                      not valid_employment_edit(state,e,proposed_edits=effective) for e in effective)
            if not changed:
                reference.project(path.parent,state,[p for p in catalog if p['proof']['sourceMonth']==state['month']],stale)
        elif generated:
            changed=True
        if changed:
            state=self._rebuild(path.parent,state,digests_current=True)
        if changed and state.get('rows'):
            from .recruitment_awards import calculate_draft
            calculate_draft(state)
        if _refresh_changes is not None:_refresh_changes.append(changed)
        return state

    def _source_digests(self,folder,state):
        changed=False
        for source in state.get('sources',[]):
            checkpoint()
            original=folder/'sources'/source.get('storedName','')
            if not original.is_file() and not any(key in source for key in ('bytes','contentDigest','parsedContentDigest')):
                continue
            before=deepcopy(source)
            try:
                if not original.is_file():
                    source['contentDigest']=''
                    raise ValueError('原始文件缺失，请恢复原件或重新上传后核对')
                source['contentDigest']=hashlib.sha256(original.read_bytes()).hexdigest()
                if source.get('purpose')=='external-results':
                    if source['contentDigest']!=source.get('idDigest',source.get('parsedContentDigest')):
                        raise ValueError('体系外核定原件已变化，请重新上传核算结果')
                    if source.pop('sourceCacheError',False):source.pop('error',None)
                    changed=changed or before!=source
                    continue
                if source.get('active',True) and (not source.get('error') or source.get('sourceCacheError')):
                    path=folder/'parsed'/f"{source['id']}.json"
                    try:
                        stamp=path.stat()
                        parsed=_parsed_metadata(str(path.resolve()),(stamp.st_dev,stamp.st_ino,stamp.st_size,
                                                                     stamp.st_mtime_ns,stamp.st_ctime_ns))
                    except (OSError,ValueError):
                        parsed={}
                    missing_beisen_metadata=(source.get('kind')=='beisen' and not parsed.get('beisenSourceMetadata') and
                                             (source.get('parserVersion')!=PARSER_VERSION or not source.get('syncCoverage') or
                                              before.get('contentDigest')!=source['contentDigest']))
                    if (parsed.get('contentDigest')!=source['contentDigest'] or
                        parsed.get('parserVersion',source.get('parserVersion'))!=PARSER_VERSION or source.get('sourceCacheError') or missing_beisen_metadata):
                        self._parse_source(folder,source)
                        changed=True
                    else:
                        source['parsedContentDigest']=source['contentDigest']
                        if source.get('kind')=='beisen' and parsed.get('beisenSourceMetadata'):
                            source.update(deepcopy(parsed['beisenSourceMetadata']))
                        if source.get('parserVersion')!=PARSER_VERSION:
                            source.update(attachment=parsed['attachment'],sheets=parsed['sheets'],recordCount=parsed['recordCount'],
                                          roles=parsed['roles'],roleCounts=parsed['roleCounts'],parserVersion=PARSER_VERSION)
            except (ValueError,OSError,KeyError,zipfile.BadZipFile,ET.ParseError) as exc:
                source['sourceCacheError']=True
                source['error']=str(exc) if isinstance(exc,ValueError) else f'原始文件无法重新读取：{type(exc).__name__}，请恢复原件或重新上传'
            changed=changed or {k:v for k,v in source.items() if k!='parsedContentDigest'}!={k:v for k,v in before.items() if k!='parsedContentDigest'}
        return changed

    def _check(self,state,revision):
        if revision!=state['revision']: raise DraftConflict('底稿已更新，请刷新后查看最新内容再修改；本次修改尚未保存。')

    def _write(self,path,value):
        path.parent.mkdir(parents=True,exist_ok=True)
        temp=path.with_name(path.name+'.'+uuid4().hex+'.tmp')
        try:
            with temp.open('w',encoding='utf-8') as out:
                json.dump(value,out,ensure_ascii=False,separators=(',',':'),allow_nan=False)
                out.flush(); os.fsync(out.fileno())
            os.replace(temp,path)
        finally:
            temp.unlink(missing_ok=True)

    def _save(self,folder,state,*,recalculate=True):
        checkpoint()
        if recalculate:
            from .recruitment_external_results import attach_rows
            attach_rows(state)
        state['revision']+=1; state['updatedAt']=recruitment_now().isoformat(timespec='seconds')
        if recalculate:
            from .recruitment_awards import calculate_draft
            calculate_draft(state)
        elif state.get('calculation'):
            # Only source metadata changed; the saved calculation still covers
            # these identical rows and decisions. Do not reorder their todos.
            state['calculation']['draftRevision']=state['revision']
        persisted={k:v for k,v in state.items() if k!='referenceFacts'}
        checkpoint()
        # Once commit starts, finish both files before observing a stop request.
        self._write(folder/'revisions'/f"{state['revision']}.json",persisted)
        self._write(folder/'draft.json',persisted)
        return state

    def _rebuild(self,folder,state,*,digests_current=False):
        checkpoint()
        if not digests_current:self._source_digests(folder,state)
        state=deepcopy(state)
        state['rows']=[r for r in state['rows'] if not r.get('externalOnly')]
        records=[]
        for source in state['sources']:
            checkpoint()
            if source.get('purpose')=='external-results':continue
            if source.get('active',True) and not source.get('error') and not source.get('comparisonOnly'):
                parsed = (self._parse_source(folder,source) if source.get('parserVersion') != PARSER_VERSION or (source.get('contentDigest') and source.get('parsedContentDigest') and source['contentDigest']!=source['parsedContentDigest'])
                          else json.loads((folder/'parsed'/f"{source['id']}.json").read_text()))
                records.extend(parsed['records'])
        records.extend(state.get('manualRows',[]))
        generated=any(e.get('referenceFact') or e.get('employmentBasis') for e in state.get('edits',[]))
        if not generated:
            result=assemble(state['month'],records,state)
            from .recruitment_external_results import attach_rows
            attach_rows(result)
            return result
        from . import recruitment_reference_facts as reference
        audit=state['edits']
        previously_applied={(r['id'],e['field'],e.get('operationId')) for r in state['rows'] for e in r.get('edits',[])}
        baseline=reference.strip_generated_values(deepcopy(state))
        baseline['edits']=[e for e in audit if not e.get('referenceFact') and not e.get('employmentBasis')]
        baseline=assemble(state['month'],records,baseline)
        baseline['edits']=audit
        catalog=reference._catalog(folder,baseline,True)
        effective,stale=reference.effective_edits(folder,baseline,catalog)
        from .recruitment_employment import valid_employment_edit
        baseline['edits']=effective
        validated=[]
        for edit in effective:
            if edit.get('active',True) and edit.get('employmentBasis') and not valid_employment_edit(baseline,edit,proposed_edits=effective):
                stale.append({'rowId':edit['rowId'],'field':edit['field'],'reason':'任职来源或关联已变化，请重新核对'})
            else:validated.append(edit)
        baseline['edits']=validated
        result=assemble(state['month'],records,baseline)
        result['edits']=audit
        reference.project(folder,result,[p for p in catalog if p['proof']['sourceMonth']==state['month']],stale)
        restored={e['referenceFact']['proposalId'] for e in validated if e.get('referenceFact') and e.get('active',True) and e.get('revision',0)<=state['revision'] and (e['rowId'],e['field'],e.get('operationId')) not in previously_applied}
        for options in result['referenceFacts']['byRowId'].values():
            for option in options:
                if option['id'] in restored and option['status']=='adopted':option.update(status='restored',restored=True)
        from .recruitment_external_results import attach_rows
        attach_rows(result)
        return result

    def _parse_source(self,folder,source):
        original=folder/'sources'/source['storedName']
        content_digest=hashlib.sha256(original.read_bytes()).hexdigest()
        if source.get('kind')=='overseas_api':
            from .recruitment_overseas import parsed_snapshot
            parsed=parsed_snapshot(json.loads(original.read_text()),source['id'])
        elif source.get('kind')=='beisen':
            from .recruitment_beisen import parsed_snapshot, sync_coverage, CHANNEL
            snapshot=json.loads((folder/'sources'/source['storedName']).read_text())
            parsed=parsed_snapshot(snapshot,source['id'])
            coverage=sync_coverage(snapshot)
            source['syncCoverage']=coverage
            source['validOfferIds']=sorted(o['objectId'] for o in snapshot.get('offers',[]) if o.get('objectId') and offer_validity(o,'domestic_offer')['state']=='valid')
            source['offerResponseIds']=sorted(o['objectId'] for o in snapshot.get('offers',[]) if o.get('objectId') and offer_validity(o,'domestic_offer')['state']!='absent')
            source['requestedJobNumbers']=sorted(n for n,c in coverage['candidates'].items() if c['requested'])
            source['requestedRecipientJobNumbers']=sorted(n for n,c in coverage['recipients'].items() if c['requested'])
            source['scopeJobNumbers']=sorted(n for n,c in coverage['candidates'].items() if c['employment'])
            source['scopeRecipientJobNumbers']=sorted(n for n,c in coverage['recipients'].items() if c['employment'])
            source['syncWarnings']=parsed.get('warnings',[])
            source['channelDetailsCheckedOfferIds']=snapshot.get('channelDetailsCheckedOfferIds',[])
            source['channelChecks']=snapshot.get('channelChecks',[])
            if not snapshot.get('channelDetailsOnly'):
                checks=[{'offerId':o['objectId'],'status':'已取得备注' if str(o.get('remarks') or '').strip() else '备注为空'}
                        for o in snapshot.get('offers',[]) if o.get('objectId') and 'remarks' in o
                        and not o.get('stdIsDeleted') and str(o.get('approvalStatus'))=='2'
                        and str(o.get('customProperties',{}).get(CHANNEL))=='10']
                source['channelChecks']=checks
                source['channelDetailsCheckedOfferIds']=[c['offerId'] for c in checks]
            parsed['beisenSourceMetadata']={key:deepcopy(source[key]) for key in (
                'syncCoverage','validOfferIds','offerResponseIds','requestedJobNumbers','requestedRecipientJobNumbers',
                'scopeJobNumbers','scopeRecipientJobNumbers','syncWarnings','channelDetailsCheckedOfferIds','channelChecks')}
        else:
            parsed=read_source(folder/'sources'/source['storedName'],source['id'])
        source.update(attachment=parsed['attachment'],sheets=parsed['sheets'],recordCount=len(parsed['records']),
                      roles=sorted({r['role'] for r in parsed['records']}),roleCounts=dict(Counter(r['role'] for r in parsed['records'])),
                      parserVersion=PARSER_VERSION)
        if source['attachment']:self._inspect_attachment(folder,source)
        if hashlib.sha256(original.read_bytes()).hexdigest()!=content_digest:
            raise ValueError('原始文件在读取时发生变化，请重新读取后核对')
        parsed['contentDigest']=content_digest
        parsed['parserVersion']=PARSER_VERSION
        source.update(contentDigest=content_digest,parsedContentDigest=content_digest)
        if source.pop('sourceCacheError',False):source.pop('error',None)
        self._write(folder/'parsed'/f"{source['id']}.json",parsed)
        if source.get('kind')=='overseas_api':(folder/'parsed'/f"{source['id']}.json").chmod(0o600)
        return parsed

    def _inspect_attachment(self,folder,source):
        from .recruitment_documents import extract_document, mentioned_attachments, unreadable_pages, DOCUMENT_REFERENCE_VERSION
        try:
            data=extract_document(folder/'sources'/source['storedName'],folder/'documents'/source['id'])
            if unreadable_pages(data) or not any(p.get('text','').strip() for p in data['pages']):raise ValueError('审批文字未完整读取')
            source['mentionedAttachments']=mentioned_attachments(data)
            source['attachmentInspectionVersion']=DOCUMENT_REFERENCE_VERSION
            source.pop('documentInspectionError',None)
        except Exception:
            # Keep the original available for review even when OCR/rendering
            # fails. A failed extraction must never mean "no attachment needed".
            source['documentInspectionError']='无法自动读取审批附件名称，请打开原件核对。'

    def refresh(self,month,revision):
        """Rebuild after a parser/assembly/engine upgrade using saved inputs."""
        from .recruitment_awards import ENGINE_VERSION, RULE_HASH
        from .recruitment_documents import DOCUMENT_REFERENCE_VERSION
        with self._lock(month) as folder:
            checkpoint()
            read_changes=[]
            state=self.read(month,_refresh_changes=read_changes);self._check(state,revision)
            inspected=False
            for source in state['sources']:
                checkpoint()
                if source.get('active',True) and source.get('attachment') and not source.get('comparisonOnly') and source.get('attachmentInspectionVersion')!=DOCUMENT_REFERENCE_VERSION:
                    before=deepcopy(source);self._inspect_attachment(folder,source)
                    inspected=inspected or before!=source
            external_changed=False
            if state.get('externalResults'):
                from .recruitment_external_results import effective
                selected=effective(state);valid={r['id'] for r in selected['valid']}
                expected={(r['id'],r['id'] in valid) for r in selected['latest']+selected['expected']}
                calculated={(n['externalResultId'],n.get('amount') is not None)
                            for row in state['rows'] for award in row.get('calculation',{}).values() if isinstance(award,dict)
                            for n in award.get('nodes',[]) if n.get('externalResultId')}
                external_changed=expected!=calculated
            changed=(state.get('assemblyVersion')!=ASSEMBLY_VERSION or
                     any(s.get('parserVersion')!=PARSER_VERSION for s in state['sources'] if s.get('active',True) and not s.get('error') and not s.get('comparisonOnly')) or
                     state.get('calculation',{}).get('engineVersion')!=ENGINE_VERSION or
                     state.get('calculation',{}).get('ruleHash')!=RULE_HASH or inspected)
            if state['sources'] and (changed or external_changed or any(read_changes)):
                return self._save(folder,self._rebuild(folder,state) if changed else state)
            return state

    def ingest(self,month,files,revision,period_confirmed=False,comparison_only=False):
        with self._lock(month) as folder:
            state=self.read(month); self._check(state,revision)
            changed=bool(state['revision'] and state.get('assemblyVersion')!=ASSEMBLY_VERSION)
            if period_confirmed and not state.get('periodConfirmed'):
                state['periodConfirmed']=True; changed=True
            for name,content in files:
                name=Path(name).name; suffix=Path(name).suffix.lower()
                if suffix not in {'.xlsx','.xlsm','.xls','.pdf','.png','.jpg','.jpeg'}: raise ValueError('请上传Excel、PDF或图片资料')
                if len(content)>80*1024*1024: raise ValueError('单份文件不能超过80MB')
                sid=hashlib.sha256(content).hexdigest()
                existing=next((s for s in state['sources'] if s['id']==sid),None)
                if existing:
                    if existing.get('forMonth')!=month:
                        existing['forMonth']=month; changed=True
                    if existing.get('parserVersion')!=PARSER_VERSION and not existing.get('error'):
                        changed=True
                    continue
                path=folder/'sources'/f'{sid}{suffix}'; path.parent.mkdir(parents=True,exist_ok=True)
                with path.open('wb') as dest:
                    dest.write(content); dest.flush(); os.fsync(dest.fileno())
                source={'id':sid,'name':name,'storedName':path.name,'active':True,'bytes':len(content),'forMonth':month,'addedAt':recruitment_now().isoformat(timespec='seconds'),'comparisonOnly':comparison_only}
                try:
                    self._parse_source(folder,source)
                    if state.get('strictInputs') and 'ledger' in source.get('roles',[]):
                        periods=re.findall(r'(?<!\d)(20\d{2})[年._-]?(0[1-9]|1[0-2])月?(?!\d)',name)
                        if periods and max(int(y)*100+int(m) for y,m in periods)>=month:
                            source['comparisonOnly']=True
                except (ValueError,OSError,KeyError,zipfile.BadZipFile,ET.ParseError) as exc:
                    source.update(error=f'无法读取该文件：{type(exc).__name__}',recordCount=0,roles=[])
                state['sources'].append(source); changed=True
            return self._save(folder,self._rebuild(folder,state)) if changed else state

    def save_overseas_snapshot(self,month,revision,payload):
        from .recruitment_overseas import save_snapshot
        return save_snapshot(self,month,revision,payload)

    def save_beisen_snapshot(self,month,revision,payload):
        if payload.get('monthlyRoster'):
            from .recruitment_domestic import save_snapshot
            return save_snapshot(self,month,revision,payload)
        # Network retrieval happens before this lock. A concurrent user edit
        # rejects the save, leaving the draft and its previous snapshot intact.
        with self._lock(month) as folder:
            checkpoint()
            state=self.read(month);self._check(state,revision)
            content=json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()
            sid=hashlib.sha256(content).hexdigest()
            if any(s['id']==sid for s in state['sources']):return state
            source={'id':sid,'kind':'beisen','name':'北森国内资料（验证快照）.json' if payload.get('verificationReplay') else '北森国内资料.json','storedName':sid+'.json',
                'active':True,'bytes':len(content),'forMonth':month,'addedAt':payload['queriedAt'],
                'scope':'本批已有国内人员','comparisonOnly':False,'employmentOnly':bool(payload.get('employmentOnly')),
                'channelDetailsOnly':bool(payload.get('channelDetailsOnly'))}
            if payload.get('employmentOnly'):source.update(name='北森任职补查.json',scope='奖金领取人任职资料定向补查')
            if payload.get('channelDetailsOnly'):source.update(name='北森招聘渠道备注.json',scope='原Offer渠道备注定向补查')
            checkpoint()
            self._write(folder/'sources'/source['storedName'],payload)
            self._parse_source(folder,source)
            for previous in state['sources']:
                if previous.get('kind')=='beisen' and previous.get('active',True) and 'validOfferIds' not in previous:
                    self._parse_source(folder,previous)
                if (previous.get('kind')=='beisen' and not previous.get('monthlyRoster') and not previous.get('employmentOnly') and not previous.get('channelDetailsOnly')
                    and not payload.get('employmentOnly') and not payload.get('channelDetailsOnly')
                    and set(previous.get('requestedJobNumbers',previous.get('scopeJobNumbers',[]))) <= set(source['scopeJobNumbers'])
                    and set(previous.get('scopeRecipientJobNumbers',[])) <= set(source['scopeRecipientJobNumbers'])
                    and set(previous.get('validOfferIds',[])) <= set(source['offerResponseIds'])):
                    previous['active']=False
            state['sources'].append(source)
            return self._save(folder,self._rebuild(folder,state))

    def correct_period(self,month,revision):
        from .recruitment_attention import period_info
        # Original imports remain intact. Target ingestion deduplicates files
        # and preserves any existing target edits, reviews and revision history.
        with self._lock(month) as folder:
            state=self.read(month); self._check(state,revision)
            period=period_info(state)
            if not period['canAlign']: raise ValueError('本月底稿已有处理记录，请保留本月并在目标月份添加原始资料')
            target=period['suggestedMonth']
            files=[(s['name'],(folder/'sources'/s['storedName']).read_bytes()) for s in state['sources'] if s.get('active',True)]
        target_state=self.read(target)
        return self.ingest(target,files,target_state['revision'])

    def _prepare_change(self,folder,state,change,*,trusted_edits=False,validate_only=False):
        if not change or set(change)-{'revision','baseline','source','edits','supplement'}: raise ValueError('不支持的底稿操作')
        if not isinstance(change.get('edits',[]),list): raise ValueError('更正内容格式无效')
        if len(change.get('edits',[]))>5000: raise ValueError('单次最多修改5000个单元格')
        known={r['id']:r for r in state['rows']}; sources={s['id']:s for s in state['sources']}
        if 'baseline' in change:
            sid=change['baseline']
            if sid not in sources or 'ledger' not in sources[sid].get('roles',[]) or not sources[sid]['active'] or sources[sid].get('comparisonOnly'):
                raise ValueError('请选择已上传且正在使用的历史台账')
            state['baseline']=sid
            if state.get('strictInputs'):
                from .recruitment_attention import named_month
                previous=(state['month']//100-1)*100+12 if state['month']%100==1 else state['month']-1
                if named_month([sources[sid]['name']])!=previous:raise ValueError('期初必须是紧邻上月台账，请核对文件月份')
                state['settlement']={'version':1,'baselineId':sid}
        if 'source' in change:
            update=change['source']
            if not isinstance(update,dict) or not isinstance(update.get('active'),bool): raise ValueError('来源状态格式无效')
            sid=update.get('id')
            if sid not in sources: raise ValueError('来源不存在')
            if sid==state['baseline'] and not update.get('active',True): raise ValueError('可信期初不能直接停用，请先选择替代期初')
            sources[sid]['active']=bool(update.get('active',True))
        if not isinstance(change.get('edits',[]),list): raise ValueError('更正内容格式无效')
        from .recruitment_field_controls import expand_choices
        change={**change,'edits':expand_choices(change.get('edits',[]))}
        proposed_values={rid:dict(row['values']) for rid,row in known.items()}
        for edit in change['edits']:
            if isinstance(edit,dict) and edit.get('rowId') in proposed_values:
                proposed_values[edit['rowId']][edit.get('field')]=edit.get('value','')
        operation_id=uuid4().hex
        for edit in change.get('edits',[]):
            if not isinstance(edit,dict): raise ValueError('更正内容格式无效')
            from .recruitment_reference_facts import TRUSTED_KEYS
            if not trusted_edits and TRUSTED_KEYS.intersection(edit): raise ValueError('可信事实依据只能通过服务端选择生成')
            rid=edit.get('rowId'); field=edit.get('field'); value=edit.get('value','')
            if rid not in known: raise ValueError('人员记录不存在')
            if field not in EDITABLE_FIELDS: raise ValueError('此字段不能直接修改')
            if not isinstance(value,(str,int,float)) or isinstance(value,bool): raise ValueError('请输入文本或数字')
            if isinstance(value,float) and not math.isfinite(value): raise ValueError('请输入有限的有效数值')
            if len(str(value))>4000: raise ValueError('字段内容过长')
            if field in DATE_FIELDS and value and not date_text(value): raise ValueError('请输入有效日期')
            if field in DATE_FIELDS and value: value=date_text(value)
            if field=='核算范围' and value not in {'','纳入核算','不纳入核算'}: raise ValueError('请选择纳入核算或不纳入核算')
            evidence=edit.get('evidenceId','')
            from .recruitment_field_controls import normalize_edit, source_basis
            prospective={**known[rid],'values':proposed_values[rid]}
            value,evidence=normalize_edit(state,prospective,field,value,evidence)
            proof=source_basis(state,prospective,field,edit.get('value',''))
            if evidence and evidence not in sources: raise ValueError('依据文件不存在')
            if evidence and ((sources[evidence].get('comparisonOnly') and not (trusted_edits and edit.get('referenceFact'))) or not sources[evidence].get('active',True)):
                raise ValueError('核对结果表或已停用资料不能作为修改依据，请选择原始材料或审批')
            # Link only matching values from the server's original field records.
            # A manual correction must never inherit the old value's provenance.
            refs=[deepcopy(ref) for ref in known[rid].get('provenance',{}).get(field,[])
                  if evidence and ref.get('sourceId')==evidence and text(ref.get('value'))==text(value)]
            if trusted_edits and edit.get('referenceFact'):
                refs=deepcopy([r for r in edit['referenceFact']['refs'] if r['field']==field])
            state['edits'].append({'rowId':rid,'field':field,'value':value,'before':known[rid]['values'].get(field,''),
                 'reason':text(edit.get('reason')) or ('采用原始资料' if refs else '手工修改'),
                 'evidenceId':evidence,'evidenceRefs':refs,'revision':state['revision']+1,
                 'at':recruitment_now().isoformat(timespec='seconds'),'operationId':operation_id,'active':True,
                 **({'fieldSourceBasis':proof} if proof else {}),
                 **{k:deepcopy(edit[k]) for k in ('referenceFact','employmentBasis') if trusted_edits and k in edit}})
        identity_edits=[e for e in change.get('edits',[]) if e.get('field') in IDENTITY | {'入职日期','候选人入职时间'}]
        if identity_edits:
            proposed={rid:dict(r['values']) for rid,r in known.items()}
            for edit in change.get('edits',[]): proposed[edit['rowId']][edit['field']]=edit.get('value','')
            identities={rid:_identity(v,known[rid]['sources'][0]) for rid,v in proposed.items()}
            for edit in identity_edits:
                rid=edit['rowId']
                if any(other!=rid and key==identities[rid] for other,key in identities.items()):
                    raise ValueError('同一任职已有另一条记录，请核对身份；不能通过改工号静默合并')
        if 'supplement' in change:
            values=change['supplement']
            if not isinstance(values,dict) or any(not isinstance(v,(str,int,float)) or isinstance(v,bool) for v in values.values()): raise ValueError('补充字段请输入文本或数字')
            if not text(values.get('姓名')): raise ValueError('请填写人员姓名')
            if any(f not in EDITABLE_FIELDS for f in values): raise ValueError('补充数据含未知字段')
            for field in DATE_FIELDS:
                if values.get(field):
                    if not date_text(values[field]): raise ValueError('请输入有效日期')
                    values[field]=date_text(values[field])
            uid=uuid4().hex
            values.setdefault('体系外人员编号',uid)
            state['manualRows'].append({'role':'supplement','values':values,'fieldColumns':{},'ref':{'sourceId':'manual-'+uid,'sheet':'人工补充','row':1},'historyCells':[]})
        if change.get('edits'):
            state.setdefault('operations',[]).append({'id':operation_id,'month':state['month'],'active':True,'label':'资料更正','at':recruitment_now().isoformat(timespec='seconds')})
            state['redoOperations']=[]
            state['operations'][-1]['referenceFacts']=[deepcopy(e['referenceFact']) for e in change['edits'] if e.get('referenceFact')]
            state['operations'][-1]['employmentSelections']=[deepcopy(e['employmentBasis']) for e in change['edits'] if e.get('employmentBasis')]
        return state if validate_only else self._rebuild(folder,state)

    def change(self,month,revision,change):
        with self._lock(month) as folder:
            state=self.read(month); self._check(state,revision)
            return self._save(folder,self._prepare_change(folder,state,change))

    def history_action(self,month,revision,action):
        with self._lock(month) as folder:
            state=self.read(month);self._check(state,revision)
            operations=state.get('operations',[])
            if action=='undo':
                operation=next((o for o in reversed(operations) if o['month']==month and o['active']),None)
                if not operation: raise ValueError('没有可以撤销的修改')
                operation['active']=False
                state.setdefault('redoOperations',[]).append(operation['id'])
            elif action=='redo':
                if not state.get('redoOperations'): raise ValueError('没有可以重做的修改')
                oid=state['redoOperations'].pop()
                operation=next(o for o in operations if o['id']==oid and o['month']==month)
                operation['active']=True
            else: raise ValueError('不支持的历史操作')
            for edit in state['edits']:
                if edit.get('operationId')==operation['id']: edit['active']=operation['active']
            state.setdefault('historyActions',[]).append({'operationId':operation['id'],'action':action,'at':recruitment_now().isoformat(timespec='seconds')})
            return self._save(folder,self._rebuild(folder,state))

    def carry_forward(self, month, source_month, revision):
        previous = (month // 100 - 1) * 100 + 12 if month % 100 == 1 else month - 1
        if source_month != previous: raise ValueError('只能承接紧邻上月的底稿')
        with self._lock(source_month) as origin:
            approved=origin/'accepted.json'
            parent=json.loads(approved.read_text())['state'] if approved.exists() else self.read(source_month)
            if not parent['revision']: raise ValueError('上月尚未保存底稿')
            with self._lock(month) as folder:
                state=self.read(month); self._check(state,revision)
                if state['revision']: raise ValueError('本月底稿已有内容，不能整份覆盖')
                monthly_workflow=state.get('monthlyWorkflow',False)
                state=deepcopy(parent)
                if monthly_workflow:state['monthlyWorkflow']=True
                if approved.exists():
                    from .recruitment_settlement import capture_confirmed_installments
                    state['confirmedInstallments']=capture_confirmed_installments(parent)
                state.update(month=month,revision=0,parentMonth=source_month,parentRevision=parent['revision'],redoOperations=[],externalImports=[])
                state.pop('trial',None)
                state.pop('adoptedFrom',None)
                for name in ('sources','parsed'):
                    for source in parent['sources']:
                        filename=source['storedName'] if name=='sources' else source['id']+'.json'
                        path=origin/name/filename
                        if path.exists():
                            dest=folder/name/filename;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,dest)
                return self._save(folder,self._rebuild(folder,state))
