"""Explain each review decision with the actual inputs, sources and next action."""
import re
from .recruitment_attention import project, needed, ROLE_FACTS, intake_fields
from .recruitment_awards import present, ensure_calculated
from .recruitment_drafts import staff_id


LABELS = {'ABC类别':'岗位类别','标签分类':'核算地区','奖金地区类型':'适用地区','招聘负责人工号':'招聘负责人','协助招聘人工号':'协助招聘人','推荐人工号':'推荐人','候选人入职时间':'候选人入职日','上次离职日期':'上次任职的最后工作日','二次入职专项口径依据':'二次入职执行依据','周期剔除依据':'剔除天数的审批或说明','周期豁免依据':'免周期的审批或名单','管培生已批名单资格':'是否在认可名单内','原计划入职日期':'最初计划入职日'}
GUIDES = {
    'rehire': ('确认二次入职间隔','填入上一段任职的最后工作日。系统会计算离职间隔，并按本次入职适用的规则重算。','核对日期'),
    'cycle': ('核对招聘周期','核对招聘启动日、实际入职日和已认可的剔除天数；有审批时可直接查看原件。','核对周期'),
    'recipient': ('核对任职资格','下面列出实际缺少或冲突的候选人、领取人任职信息。核对适用日期时是否在职，并选择采用资料。','核对任职'),
    'employment': ('核对任职资料差异','逐人列出日期差异、重复行或尚未对应的录用资料。不同入职记录本身不代表重复。','查看差异'),
    'intake_scope': ('补齐录用资料中的缺项','未匹配到本次入职的录用记录。下面列出实际缺少的核算字段；上传对应录用资料或补充表后自动重新匹配。','补充资料'),
    'scope': ('确认奖金适用范围','核对实际工作地区和岗位类别，确定适用的奖金标准。','选择范围'),
    'standard': ('确认适用奖金标准','核对地区、岗位类别和职级；未知组合不能自动采用其他人的标准。','核对标准'),
    'attachment_review': ('核对审批调整','核对识别的人员与调整内容，补齐提示的缺项后采用。','查看审批调整'),
    'baseline': ('选择历史台账','选择用于承接历史安排的台账。台账原金额保留，实际已付状态单独核实。','选择台账'),
    'resignation_review': ('核对离职审批结果','对照离职流程最终状态，确认最后工作日；原流程未结束时不能直接按离职处理。','核对离职'),
    'hierarchy': ('确认推荐关系','对照推荐人和候选人的汇报关系，确认是否属于制度排除的上下级推荐。','核对关系'),
}


def guide(task):
    if task['kind'].startswith('field:'):
        field=task['kind'].split(':',1)[1];label=LABELS.get(field,field)
        return ('确认'+label, f'不同资料中的{label}不一致或尚未提供。对照下面的原值，选择本次采用的资料。','选择采用值')
    return GUIDES.get(task['kind'],(task['title'],'核对下列资料，补充实际影响本次奖金的事实。','查看并核对'))


def referral_suggestion(row,state):
    """Propose facts from an explicit note plus a same-row manager identity.

    This never changes the worksheet or sets a bonus amount. The ordinary
    revisioned preview applies the chosen facts and the existing rule decides.
    """
    v=row['values'];fields={'推荐人工号','推荐人姓名'}
    if v.get('招聘渠道')!='内推' or any(present(v.get(f)) for f in fields): return None
    if any(e['field'] in fields for e in row.get('edits',[])): return None
    note=str(v.get('人工备注') or '')
    names=re.findall(r'(?:^|[；;。\n])\s*(?:内推人|推荐人)(?:为|是|[：:])\s*([\u4e00-\u9fff·]{2,12})(?=[，,。；;\s]|$)',note)
    if len(set(names))!=1: return None
    name=names[0];provenance=row.get('provenance',{})
    sources={s['id']:s for s in state['sources'] if s.get('active',True) and not s.get('comparisonOnly') and not s.get('error')}
    notes=[p for p in provenance.get('人工备注',[]) if str(p.get('value'))==note and p.get('role')=='ledger' and p['sourceId'] in sources]
    matches=[]
    for prefix in ['直接上级']+['间接上级'+str(i) for i in range(1,5)]:
        if v.get(prefix+'姓名')!=name or not present(v.get(prefix+'工号')): continue
        if set(row.get('unresolvedFields',[])) & {'人工备注',prefix+'姓名',prefix+'工号'}: continue
        for n in notes:
            same=lambda p: all(p.get(k)==n.get(k) for k in ('sourceId','sheet','row'))
            nr=next((p for p in provenance.get(prefix+'姓名',[]) if same(p) and p.get('value')==name),None)
            ir=next((p for p in provenance.get(prefix+'工号',[]) if same(p) and staff_id(p.get('value'))==staff_id(v[prefix+'工号'])),None)
            if nr and ir: matches.append((staff_id(ir['value']),prefix,n,nr,ir))
    if len({m[0] for m in matches})!=1: return None
    employee,prefix,n,nr,ir=matches[0]
    reason=f'台账备注明确推荐人为{name}，同一行{prefix}姓名与工号一致；补齐推荐事实，由上下级推荐规则判断内推资格。'
    refs=[{k:p.get(k) for k in ('sourceId','sheet','row','column')}|{'file':sources[p['sourceId']]['name']} for p in (n,nr,ir)]
    return {'title':f'备注中的推荐人{name}是{prefix}',
            'detail':'采用同一台账记录的推荐人，按奖金规则核算领取资格。',
            'sources':refs,'edits':[{'rowId':row['id'],'field':f,'value':value,'evidenceId':n['sourceId'],'reason':reason}
                                    for f,value in [('推荐人姓名',name),('推荐人工号',employee)]]}


def task_fields(row,task,month):
    kind=task['kind'];v=row['values']
    if kind.startswith('field:'):
        field=kind.split(':',1)[1]
        if field=='招聘渠道' and v.get(field)=='其他' and field not in row.get('unresolvedFields',[]):
            return ['其他渠道']
        return [field]
    if kind=='rehire':
        fields=['上次离职日期'] if not present(v.get('上次离职日期')) or '上次离职日期' in row.get('unresolvedFields',[]) else []
        if '二次入职专项条款执行依据待核' in row['calculation']['recruitment']['issues']:
            fields.append('二次入职执行口径')
        return fields
    if kind=='cycle':
        fields=['招聘启动日期','入职日期','周期剔除天数']
        if v.get('周期剔除天数') not in (None,'',0,'0','0.0') or v.get('周期剔除依据') or '周期剔除依据' in row.get('unresolvedFields',[]):
            fields.append('周期剔除依据')
        try: exemption=float(v.get('周期剔除天数') or 0)<0
        except (ValueError,TypeError): exemption=False
        if exemption or v.get('周期豁免依据') or '管培生' in str(v.get('人工备注','')):
            fields+=['原计划入职日期','应届校招','延后入职原因','管培生已批名单资格','周期豁免依据']
        return fields
    if kind=='employment': return ['入职日期','候选人入职时间','任职说明']+(['核算范围'] if row.get('employmentCandidates') else [])
    if kind=='identity':return ['证件号']
    if kind in {'scope','standard'}:
        fields=['标签分类','奖金地区类型','ABC类别','职级']
        missing=[f for f in fields if not present(v.get(f)) and needed(row,f,month)]
        return missing or fields
    if kind=='intake_scope': return intake_fields(row,month)
    if kind=='hierarchy': return ['推荐人与候选人上下级关系','直线经理工号']
    if kind=='resignation_review': return ['最后工作日']
    if kind=='channel_policy':return ['招聘渠道']
    if kind.startswith('calculation:'):return []
    if kind=='recipient':
        fields=[]
        has_current_nodes=any(n.get('scheduledMonth',n['dueMonth'])==month for k in ('recruitment','referral') for n in row['calculation'][k]['nodes'])
        for f in row.get('unresolvedFields',[]):
            if (f.endswith(('人员状态','入职日期','最后工作日','转正日期')) or f in ROLE_FACTS or f in {'推荐人职位','推荐人职级'}) and needed(row,f,month): fields.append(f)
        for award in (row['calculation'][k] for k in ('recruitment','referral')):
            for node in award['nodes']:
                if has_current_nodes and node.get('scheduledMonth',node['dueMonth'])!=month:continue
                for issue in node['issues']:
                    for prefix in ('候选人','招聘负责人','协助招聘人','推荐人'):
                        if not issue.startswith(prefix+'：'): continue
                        p='' if prefix=='候选人' else prefix
                        if '日期' in issue and '转正' not in issue: fields.append(p+'入职日期')
                        if '正式在职' in issue: fields += [p+'转正日期',p+'人员状态']
                        elif '在职' in issue:
                            fields.append(p+'人员状态')
                            if present(v.get(p+'最后工作日')) or p+'最后工作日' in row.get('unresolvedFields',[]):fields.append(p+'最后工作日')
                        if '转正' in issue:
                            fields.append(p+'转正日期')
                            if '转正日期待核对' not in issue: fields.append(p+'人员状态')
        return list(dict.fromkeys(fields))
    return [f for f in row.get('unresolvedFields',[]) if needed(row,f,month)] or []


def task_detail(state,task_id):
    ensure_calculated(state);attention=project(state)
    task=next((t for scope in ('current','history') for t in attention[scope] if t['id']==task_id),None)
    if task is None: raise ValueError('该事项已处理或发生变化，请刷新待办')
    title,instruction,action=guide(task);names={s['id']:s['name'] for s in state['sources']}
    people_names={staff_id(r['values'].get('工号','')):r['values'].get('姓名','') for r in state['rows'] if r['values'].get('工号')}
    for row in state['rows']:
        for prefix in ('招聘负责人','协助招聘人','推荐人'):
            if row['values'].get(prefix+'工号') and row['values'].get(prefix+'姓名'):
                people_names[staff_id(row['values'][prefix+'工号'])]=row['values'][prefix+'姓名']
    def source(ref):
        return {k:ref.get(k) for k in ('sourceId','sheet','row','column')}|{'file':names.get(ref.get('sourceId'),'人工补充')}
    def employment_review(row):
        v=row['values'];raw=[t for t in state['todos'] if row['id'] in t['rowIds']]
        kinds={t['kind'] for t in raw};observations=[];issues=[]
        def observe(label,value,refs):
            item={'label':label,'value':value or '未提供','sources':[source(r) for r in refs]}
            if item not in observations:observations.append(item)
        first=v.get('入职日期');second=v.get('候选人入职时间')
        observe('台账入职日' if row.get('history') else '当前入职日',first,row.get('provenance',{}).get('入职日期',[]))
        roster=[o for o in row.get('employmentObservations',[]) if o['value']!=first]
        if roster and 'employment_conflict' in kinds:
            issues.append('台账与花名册入职日不同')
            for date in dict.fromkeys(o['value'] for o in roster):
                observe('花名册入职日',date,[o for o in roster if o['value']==date])
        if first and second and first!=second:
            issues.append('台账内两个入职日期不一致')
            observe('台账候选人入职日',second,row.get('provenance',{}).get('候选人入职时间',[]))
        if 'duplicate_source_row' in kinds:
            issues.append('同一台账有重复任职行')
            for h in row.get('history',[]):observe('台账记录',f"{h['ref']['sheet']} · 第 {h['ref']['row']} 行",[h['ref']])
        if 'offer_employment' in kinds:
            issues.append('录用资料尚未对应到本次任职')
            for o in row.get('offerObservations',[]):
                observe('录用资料','；'.join(x for x in [o.get('employmentForm'),o.get('position'),
                        '招聘启动 '+o['recruitmentStart'] if o['recruitmentStart'] else '',o['recruiter'] or '负责人未提供'] if x),[o])
        if row.get('employmentCandidates'):
            issues.append('花名册出现另一入职日')
            for c in row['employmentCandidates']:observe('期初入职日',c['hireDate'],[c['source']])
        if not (first or second):issues.append('本次实际入职日期尚未确定')
        remaining='；'.join(t['title'] for t in raw if t['kind'] in {'employment_conflict','hire_date','duplicate_source_row','offer_employment'})
        if not issues and remaining:issues.append('任职资料需要核对：'+remaining)
        if 'duplicate_source_row' in kinds:
            instruction='查看列出的台账行，确认是重复录入还是不同任职；不要仅因同名而合并。'
        elif roster or row.get('employmentCandidates'):
            instruction='选择本次为独立招聘还是原任职延续，保留前后段原始记录。'
        elif first and second and first!=second:
            instruction='依据原始入职记录核实日期，再更正台账中不准确的字段。'
        else:instruction='核对列出的录用资料和任职记录，选择本次实际采用的日期。'
        from .recruitment_employment import employment_review as relation_review
        relation=relation_review(state,row['id'])
        return {**relation,'issues':list(dict.fromkeys(issues+relation['issues'])),'observations':observations+[o for o in relation['observations'] if o not in observations], 'instruction':relation['instruction'] if relation['selection'] else instruction}
    entries=[]
    for row in state['rows']:
        if row['id'] not in task['rowIds']: continue
        v=row['values'];fields=[]
        for field in task_fields(row,task,state['month']):
            choices=[]
            for ref in row.get('provenance',{}).get(field,[]):
                value=staff_id(ref.get('value')) if field.endswith('工号') else ref.get('value')
                if value in ('',None) or field in ROLE_FACTS and not present(value): continue
                option=next((o for o in choices if o['value']==value),None)
                if option is None:
                    name=people_names.get(str(value).lower(),'') if field.endswith('工号') else ''
                    option={'value':value,'label':f'{name}（{value}）' if name else str(value),'sources':[]};choices.append(option)
                ref=source(ref)
                if ref not in option['sources']:option['sources'].append(ref)
            fields.append({'field':field,'label':LABELS.get(field,field),'value':v.get(field,''),'options':choices,'conflict':field in row.get('unresolvedFields',[])})
        impact=[]
        for kind,title_ in [('recruitment','招聘奖金'),('referral','内推奖金')]:
            a=row['calculation'][kind]
            if a['total']==0 and not a['issues']:continue
            nodes=[n for n in a['nodes'] if n['dueMonth']==state['month']]
            impact.append({'kind':title_,'total':a['total'],'currency':a['currency'],'currentAmount':a['currentAmount'],'issues':list(dict.fromkeys(a['issues']+[i for n in nodes for i in n['issues']])),'nodes':[{'label':n['label'],'amount':n['amount'],'dueDate':n['dueDate'],'recipient':n['recipientName'] or n['recipientId']} for n in nodes]})
        employment_note=''
        from .recruitment_field_controls import controls
        for f in fields:
            if definition:=controls(state,row).get(f['field']):f.update(definition)
        entries.append({'rowId':row['id'],'name':v.get('姓名',''),'employeeId':v.get('工号',''),'hireDate':v.get('入职日期') or v.get('候选人入职时间'),'lastWorkDate':v.get('最后工作日',''),'recipient':v.get('招聘负责人姓名') or v.get('招聘负责人工号',''),'fields':fields,'impact':impact,'sources':[source(r) for r in row['sources']],'note':v.get('人工备注',''),'employmentNote':employment_note,
                        'job':v.get('职位',''),'jobType':v.get('职类',''),'organization':' / '.join(str(v[f]) for f in ('二级组织','三级组织','四级组织') if v.get(f)),
                        'employmentReview':employment_review(row) if task['kind'] in {'employment','rehire'} else None,
                        'reviewSuggestion':referral_suggestion(row,state) if task['kind'] in {'field:推荐人工号','hierarchy'} else None})
    sources=[s for s in state['sources'] if s['id'] in task['sourceIds'] or task['kind']=='baseline' and 'ledger' in s.get('roles',[])]
    return {'id':task_id,'kind':task['kind'],'title':title,'instruction':instruction,'action':action,'revision':state['revision'],'rows':entries,'sources':sources}
