"""Project preserved diagnostics into the facts a monthly operator needs to resolve."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from pathlib import Path
import re

from .recruitment_awards import NO_RECRUIT, RECRUIT_FIELDS, CORE_FIELDS, lookup, present, material_conflicts, observed_values, uses_previous_exit, status_at, channel, recipient_conflict_fields
from .recruitment_draft_sources import date_text, digest, text
from .models import add_months, as_date, yyyymm


def named_month(names):
    periods=[]
    for name in names:
        name=Path(name).name
        if not re.search(r'奖金.*(?:核算|明细|台账)|(?:招聘|内推).*台账',name) or re.search(r'offer',name,re.I): continue
        matches=re.findall(r'(?<!\d)(20\d{2})[年._-]?(0?[1-9]|1[0-2])月?(?!\d)',name)
        periods.extend(int(y)*100+int(m) for y,m in matches)
    return max(periods) if periods else None


def period_info(state):
    sources=[s for s in state['sources'] if s.get('active',True) and 'ledger' in s.get('roles',[])]
    suggested=named_month(s['name'] for s in sources)
    mismatch=bool(suggested and suggested!=state['month'] and not any(state.get(k) for k in ('periodConfirmed','parentMonth','baseline')))
    can_align=mismatch and not any(state.get(key) for key in ('edits','manualRows','reviewEntries','operations','baseline','parentMonth'))
    return {'suggestedMonth':suggested,'mismatch':mismatch,'canAlign':bool(can_align)}


def scheduled_month(row,month):
    for history in row.get('history',[]):
        for cell in history['cells']:
            if '发放周期' not in cell['label'] and '发放月份' not in cell['label']: continue
            raw=text(cell['value']).removesuffix('.0')
            if raw==str(month) or date_text(raw)[:7].replace('-','')==str(month): return True
    return False


def applicable(row,kind):
    values=row['values'];unresolved=row.get('unresolvedFields',[])
    from .recruitment_external_results import automatic_roles
    if not automatic_roles(row,kind):return False
    if row['calculation'][kind].get('accountingIssues') or material_conflicts(row,kind):return True
    if kind=='recruitment' and values.get('招聘渠道') in NO_RECRUIT and '招聘渠道' not in unresolved: return False
    if kind=='referral' and not present(values.get('推荐人工号')) and values.get('招聘渠道')!='内推' and '推荐人工号' not in unresolved: return False
    return row['calculation'][kind]['total']!=0


def is_current(row,kind,month,edited):
    if any(i['accountingMonth']==month for i in row['calculation'][kind].get('accountingIssues',[])):return True
    if row['id'] in edited or scheduled_month(row,month): return True
    from .recruitment_business_basis import historical_arrangements_complete
    if row['rule']['version']=='unresolved' and historical_arrangements_complete(row,kind,month):return False
    hire=as_date(row['values'].get('入职日期') or row['values'].get('候选人入职时间'))
    if not hire or set(row.get('unresolvedFields',[])) & {'入职日期','候选人入职时间'} or row['rule']['version']=='unresolved': return True
    award=row['calculation'][kind]
    if any(n.get('scheduledMonth',n['dueMonth'])==month or n.get('adjustmentId') and n.get('accountingMonth')==month for n in award['nodes']): return True
    # A known effective probation date competing with a monthly blank must not
    # disappear merely because the adopted blank prevented a due month.
    if '转正日期' in row.get('unresolvedFields',[]) and any(
            n['label']=='转正' and not n.get('openingLocked') and n.get('amount') for n in award['nodes']):
        dates=[as_date(p.get('value')) for p in row.get('provenance',{}).get('转正日期',[])]
        if any(d and d>=hire and yyyymm(d)<=month for d in dates):return True
    if kind=='recruitment' and '最后工作日' in row.get('unresolvedFields',[]):
        dates=[as_date(p.get('value')) for p in row.get('provenance',{}).get('最后工作日',[])]
        exits=[d for d in dates if d and d>=hire and yyyymm(d)==month]
        if exits and (award['total'] is None or any(not n.get('openingLocked') and n.get('amount')
                and (not n.get('dueMonth') or n['dueMonth']>=month) for n in award['nodes'])):return True
    # Missing facts can prevent nodes from being built. Keep possible current
    # installments visible; never infer that an old amount was paid.
    if award['total'] is None:
        standard=None if set(row.get('unresolvedFields',[])) & set(CORE_FIELDS) else lookup(row,kind)
        ratios=standard['ratios'] if standard else [1,1,1,1]
        for i,offset in enumerate((1,3,6)):
            if ratios[i] and yyyymm(add_months(hire,offset)-timedelta(days=1))==month: return True
        if ratios[3] and yyyymm(as_date(row['values'].get('转正日期')))==month: return True
    return False


LABELS={'ABC类别':'岗位类别','标签分类':'核算地区','奖金地区类型':'核算地区','海外招聘需求编号':'招聘需求','海外offer流程编号':'录用记录'}
ROLE_FACTS={'招聘负责人工号':'recruitment','协助招聘人工号':'recruitment','推荐人工号':'referral'}
STATUS_FIELDS={'人员状态','转正日期','最后工作日','直线经理工号','直接上级工号'}


def candidate_status_affects(row,kind,month):
    statuses=observed_values(row,'人员状态')
    hire=as_date(row['values'].get('入职日期') or row['values'].get('候选人入职时间'))
    nodes=row['calculation'][kind]['nodes']
    dates=[as_date(n['dueDate']) for n in nodes if n.get('dueDate')]
    if kind=='referral' and month:
        dates.append(add_months(as_date(f'{month//100:04d}-{month%100:02d}-01'),1)-timedelta(days=1))
    if not hire or not dates or len(statuses)<2: return True
    return len({tuple(status_at({**row['values'],'人员状态':s},'',at) for at in dates) for s in statuses})>1


def needed(row,field,month=None):
    if field in row.get('unresolvedFields',[]) and field.endswith('人员状态'):
        prefix=field.removesuffix('人员状态')
        if prefix in {'招聘负责人','协助招聘人','推荐人'} and field not in recipient_conflict_fields(row,prefix):return []
    if field in {'推荐人转正日期','推荐人入职日期','招聘负责人入职日期','协助招聘人入职日期'}:return []
    if field=='上次离职日期' and not uses_previous_exit(row): return []
    if field=='招聘负责人工号' and not present(row['values'].get(field)) and present(row['values'].get('招聘负责人姓名')) and field not in row.get('unresolvedFields',[]): return []
    if field in row.get('unresolvedFields',[]):
        dependencies=[kind for kind in ('recruitment','referral') if field in material_conflicts(row,kind)]
        if dependencies:
            from .recruitment_external_results import automatic_dependency
            return [k for k in dependencies if automatic_dependency(row,k,field)]
        if field in {'推荐人职级','推荐人职位'}:return []
    kinds=[]
    if field in CORE_FIELDS: kinds=['recruitment','referral']
    elif field in RECRUIT_FIELDS or field=='周期剔除依据': kinds=['recruitment']
    elif field in ROLE_FACTS: kinds=[ROLE_FACTS[field]]
    elif field in STATUS_FIELDS: kinds=['referral'] if '上级' in field or '经理' in field else ['recruitment','referral']
    elif field in {'推荐人职级','推荐人职位','推荐人转正日期'}: kinds=['referral']
    else:
        for prefix,kind in [('招聘负责人','recruitment'),('协助招聘人','recruitment'),('推荐人','referral')]:
            if field in {prefix+'入职日期',prefix+'最后工作日',prefix+'人员状态'}: kinds=[kind]
    from .recruitment_external_results import automatic_dependency
    kinds=[kind for kind in kinds if applicable(row,kind) and automatic_dependency(row,kind,field)]
    if field=='转正日期':
        # Candidate probation only controls probation installments. Do not hold
        # an unrelated monthly referral or a previously arranged installment.
        kinds=[kind for kind in kinds if any(n['label']=='转正' and not n.get('openingLocked')
               and n.get('amount') for n in row['calculation'][kind]['nodes'])]
    if field in row.get('unresolvedFields',[]) and field in RECRUIT_FIELDS:
        kinds=[kind for kind in kinds if field in material_conflicts(row,kind)]
    if field=='人员状态': kinds=[kind for kind in kinds if candidate_status_affects(row,kind,month)]
    return kinds


def recipient_requirements(state,month):
    from .recruitment_beisen import coverage_sets
    from .recruitment_drafts import ROLE_FIELDS, staff_id
    coverage=coverage_sets([s for s in state['sources'] if s.get('kind')=='beisen' and s.get('forMonth')==month])
    current=set();covered=set();domestic=set();missing=set()
    for row in state['rows']:
        roles={n['role'] for kind in ('recruitment','referral') for n in row['calculation'][kind]['nodes']
               if not n.get('externalResultId') and n.get('scheduledMonth',n.get('dueMonth'))==month}
        for field,prefix,_,_ in ROLE_FIELDS:
            number=staff_id(row['values'].get(field))
            if prefix not in roles or not number.startswith('zt'):continue
            current.add(number)
            evidence=row.get('recipientEmploymentEvidence',{}).get(prefix,{})
            overseas=row.get('recipientSourceRegions',{}).get(prefix)=='海外'
            proven=evidence.get('covered') or not overseas and not evidence.get('virtual') and number in coverage['recipientEmployment']
            if proven:covered.add(number)
            else:missing.add(number)
            if not overseas and not evidence.get('virtual'):domestic.add(number)
    covered_for_all_roles=covered-missing
    return {'currentRecipients':current,'coveredRecipients':covered_for_all_roles,'domesticRecipients':domestic,
            'domesticFetchIds':domestic-covered_for_all_roles,
            'coverageGaps':[{'role':'领取人','employee':n,'reason':'未取得任职资料'} for n in sorted(missing)]}


def channel_classification_required(row):
    v=row['values']
    provided=text(v.get('其他渠道')) or text(v.get('招聘渠道')) not in {'','其他'}
    return bool(channel(v,row['rule']['version'])[1] and provided
                and not row.get('channelResolution',{}).get('description')=='渠道说明及备注不一致')


def field_action(field):
    if field in {'入职日期','候选人入职时间'}: return ('employment','确认本次任职')
    if field in {'招聘启动日期','周期剔除天数','周期剔除依据','原计划入职日期'}: return ('cycle','核对招聘周期及依据')
    if field=='上次离职日期': return ('rehire','核对二次入职间隔')
    if field in {'直线经理工号','直接上级工号'}: return ('hierarchy','核对推荐关系')
    if field not in ROLE_FACTS and field.startswith(('招聘负责人','协助招聘人','推荐人')):
        return ('recipient','核对候选人及领取人任职状态')
    return ('field:'+field,'核对'+LABELS.get(field,field))


def intake_fields(row,month):
    """An unmatched Offer is evidence context, not a scope decision.

    Show only missing facts used by an applicable award. Known facts remain
    usable without a matched Offer; real conflicts keep their separate tasks.
    """
    v=row['values'];fields=[]
    for kind in ('recruitment','referral'):
        if not applicable(row,kind): continue
        if lookup(row,kind) is None:
            fields += [f for f in ('标签分类','ABC类别','职级') if not present(v.get(f))]
            if kind=='referral' and not present(v.get('奖金地区类型')): fields.append('奖金地区类型')
        if kind=='recruitment':
            if channel(v,row['rule']['version'])[1] and not uses_previous_exit(row): fields.append('招聘渠道')
            if not as_date(v.get('招聘启动日期')) and not (row['calculation'][kind].get('cycle') or {}).get('exempt',False): fields.append('招聘启动日期')
            from .recruitment_external_results import automatic_roles
            if '招聘负责人' in automatic_roles(row,kind) and not any(present(v.get('招聘负责人'+f)) for f in ('工号','姓名')): fields.append('招聘负责人工号')
        elif not any(present(v.get('推荐人'+f)) for f in ('工号','姓名')): fields.append('推荐人工号')
    return list(dict.fromkeys(fields))


def indistinguishable_records(rows):
    # Do not request an identifier merely because it is blank. A duplicate check
    # is necessary only when distinct records have the same employment facts and
    # existing identifiers cannot establish that they are different people.
    fields=('姓名','入职日期','候选人入职时间','标签分类','二级组织','三级组织','工作地','职位',
            '职级','ABC类别','招聘渠道','招聘启动日期','招聘负责人工号','协助招聘人工号','推荐人工号')
    identities=('工号','证件号','体系外人员编号','海外offer流程编号')
    groups=defaultdict(list)
    for row in rows:
        if not present(row['values'].get('姓名')) or not present(row['values'].get('入职日期') or row['values'].get('候选人入职时间')): continue
        groups[tuple(text(row['values'].get(f)).casefold() for f in fields)].append(row)
    return [group for group in groups.values() if len(group)>1 and any(not any(present(r['values'].get(f)) for f in identities) for r in group)]


def project(state):
    rows={r['id']:r for r in state['rows']};month=state['month'];current={};history={};notices={}
    ops={o['id'] for o in state.get('operations',[]) if o['active'] and o['month']==month}
    # Confirming employment continuity does not make unrelated historical
    # diagnostics current. Actual hire/due months below still take precedence.
    edited={e['rowId'] for e in state.get('edits',[]) if e.get('field')!='任职说明' and e.get('active',True) and (e.get('operationId') in ops or not e.get('operationId') and not state.get('parentMonth'))}
    active_ops={o['id'] for o in state.get('operations',[]) if o['active']}
    # A carried, unverified recovery/top-up arrangement remains actionable.
    edited.update(d['rowId'] for d in state.get('adjustmentDrafts',[]) if d['operationId'] in active_ops)
    scopes={rid:{k:is_current(r,k,month,edited) for k in ('recruitment','referral')} for rid,r in rows.items()}
    sources={s['id']:s for s in state['sources']}
    def add(action,title,task,rid=None,kinds=None,active_override=None):
        active=any(scopes[rid][k] for k in kinds or ('recruitment','referral')) if rid else not task.get('sourceIds') or any(sources.get(s,{}).get('forMonth',month)==month for s in task['sourceIds'])
        if active_override is not None:active=active_override
        bucket=current if active else history
        item=bucket.setdefault(action,{'id':digest(('current' if active else 'history')+'|'+action),'kind':action,'title':title,'detail':'','rowIds':set(),'sourceIds':set(),'reasons':set(),'rowReasons':{},'rowAwardKinds':{}})
        if rid:
            item['rowIds'].add(rid)
            item['rowReasons'].setdefault(rid,set()).add(task['title'])
            item['rowAwardKinds'].setdefault(rid,set()).update(kinds or ('recruitment','referral'))
        item['sourceIds'].update(task.get('sourceIds',[]));item['reasons'].add(task['title'])
    for task in state['todos']:
        # Candidate documents/employee numbers are optional source identifiers,
        # not award inputs. Actual duplicate/ambiguous employment has its own task.
        if task['kind']=='external_identity': continue
        if task['kind'].startswith('external_results_'):
            if task['rowIds']:
                for rid in task['rowIds']:
                    if rid in rows:add(task['kind'],task['title'],task,rid,active_override=True)
            else:add(task['kind'],task['title'],task,active_override=True)
            continue
        if not task['rowIds']:
            add(task['kind'],task['title'].replace('首次使用：',''),task);continue
        for rid in task['rowIds']:
            if rid not in rows: continue
            row=rows[rid];values=row['values'];kind=task['kind'];title=task['title']
            eligible=[k for k in ('recruitment','referral') if applicable(row,k)]
            if not eligible: continue
            if kind=='resignation_review':
                from .recruitment_resignations import assess
                check=assess(state,row)
                if check is not None:
                    if check['currentKinds']:add(kind,title,task,rid,check['currentKinds'],True)
                    else:
                        if any(scopes[rid][k] for k in eligible):
                            notices[rid]={'rowId':rid,'name':values.get('姓名') or values.get('工号'),**check}
                        if check['futureKinds']:add(kind,title,task,rid,check['futureKinds'],False)
                    continue
            if kind=='missing_offer':
                if intake_fields(row,month): add('intake_scope','补齐录用资料中的缺项',task,rid,eligible)
                continue
            fields=[]
            if kind=='source_conflict': fields=[title.removeprefix('核对不同来源的')]
            elif kind=='missing_fields': fields=title.split('：',1)[-1].split('、')
            elif kind=='calculation' and '核算字段来源冲突：' in title: fields=title.split('核算字段来源冲突：',1)[1].split('、')
            if fields:
                for field in fields:
                    dependencies=needed(row,field,month)
                    if dependencies:
                        action,name=field_action(field);add(action,name,task,rid,dependencies)
                continue
            if kind in {'employment_conflict','offer_employment','hire_date','duplicate_source_row'}:
                add('employment','确认本次任职',task,rid,eligible);continue
            if kind in {'missing_recipient','recipient_conflict','recipient_employment'}:
                recipient=text(task.get('recipientId')).lower()
                from .recruitment_external_results import automatic_dependency, automatic_roles
                dependencies=[k for f,k in ROLE_FACTS.items() if text(values.get(f)).lower()==recipient and k in eligible and automatic_dependency(row,k,f)] if recipient else eligible
                if kind=='missing_recipient':
                    # Import-time diagnostics are not user tasks once the
                    # calculator has resolved the offline basis or eligibility.
                    dependencies=[k for k in dependencies if any(
                        not n.get('externalResultId') and n['role'] in automatic_roles(row,k) and not n.get('eligibilityReasons') and not n.get('openingLocked') and n.get('issues')
                        and (not recipient or text(n.get('recipientId')).lower()==recipient)
                        for n in row['calculation'][k]['nodes'])]
                elif kind=='recipient_conflict':
                    fields=[task['field']] if task.get('field') else [f for f in row.get('unresolvedFields',[]) if f.startswith(('招聘负责人','协助招聘人','推荐人'))]
                    dependencies=[k for k in dependencies if any(k in needed(row,f,month) for f in fields)]
                if dependencies: add('recipient','核对候选人及领取人任职状态',task,rid,dependencies)
                continue
            if kind=='calculation':
                dependencies=['recruitment'] if title.startswith('招聘奖金：') else ['referral']
                if not applicable(row,dependencies[0]): continue
                issue=title.split('：',1)[-1]
                if issue=='领取人资料冲突':
                    fields=[f for f in row.get('unresolvedFields',[]) if f.startswith(('招聘负责人','协助招聘人','推荐人')) and dependencies[0] in needed(row,f,month)]
                    if fields:
                        for field in fields:
                            action,name=field_action(field);add(action,name,task,rid,dependencies)
                        continue
                if '核算范围' in issue: action,name='scope','核对奖金适用范围'
                elif '本次任职' in issue: action,name='employment','确认本次任职'
                elif '二次入职' in issue: action,name='rehire','核对二次入职间隔'
                elif '周期' in issue or '招聘起止' in issue: action,name='cycle','核对招聘周期及依据'
                elif '招聘渠道' in issue: action,name=('channel_policy','核定招聘渠道归类及系数') if channel_classification_required(row) else ('field:招聘渠道','核对招聘渠道')
                elif '招聘负责人待核' in issue: action,name='field:招聘负责人工号','核对招聘负责人工号'
                elif '推荐人待补充' in issue: action,name='field:推荐人工号','核对推荐人工号'
                elif '汇报关系' in issue: action,name='hierarchy','核对推荐关系'
                elif '推荐人岗位与职级' in issue: action,name='referral_qualification','核对推荐人资格'
                elif any(token in issue for token in ('在职','转正','任职日期','任职记录','日期记录','采集日期','领取人资料')): action,name='recipient','核对候选人及领取人任职状态'
                elif '标准' in issue or '特殊规则' in issue: action,name='standard','核对适用奖金标准'
                else: action,name='calculation:'+issue,issue
                add(action,name,task,rid,dependencies);continue
            if kind=='previous_exit':
                if 'recruitment' in eligible and uses_previous_exit(row): add('rehire','核对二次入职间隔',task,rid,['recruitment'])
                continue
            if kind=='channel':
                if 'recruitment' not in eligible:continue
                action,name=('channel_policy','核定招聘渠道归类及系数') if channel_classification_required(row) else ('field:招聘渠道','核对招聘渠道')
                add(action,name,task,rid,['recruitment']);continue
            add(kind,title,task,rid,eligible)
    for group in indistinguishable_records(rows.values()):
        task={'title':'相同任职资料存在多条记录，核对是否重复','sourceIds':list({s['sourceId'] for r in group for s in r.get('sources',[])})}
        for row in group:
            eligible=[k for k in ('recruitment','referral') if applicable(row,k)]
            if eligible: add('employment','确认本次任职',task,row['id'],eligible)
    def finish(bucket):
        return [{**item,'rowIds':sorted(item['rowIds']),'sourceIds':sorted(item['sourceIds']),'reasons':sorted(item['reasons']),
                 'rowReasons':{rid:sorted(reasons) for rid,reasons in item['rowReasons'].items()},
                 'rowAwardKinds':{rid:sorted(kinds) for rid,kinds in item['rowAwardKinds'].items()}} for item in bucket.values()]
    a,b=finish(current),finish(history)
    return {'current':a,'history':b,'notices':list(notices.values()),'currentPeople':len({rid for t in a for rid in t['rowIds']}),'historyPeople':len({rid for t in b for rid in t['rowIds']})}
