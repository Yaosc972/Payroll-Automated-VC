"""Manual or original-source recruitment role corrections, never answer tables."""
from .recruitment_draft_sources import text
from .recruitment_reviews import prepare_preview

ROLES = {'recruiter':'招聘负责人', 'assistant':'协助招聘人'}


def missing_attachments(state, source):
    available = {s['name'] for s in state['sources'] if s.get('active', True)
                 and not s.get('error') and not s.get('comparisonOnly')}
    return [name for name in source.get('mentionedAttachments', []) if name not in available]


def _source(store, state, source_id):
    source = next((s for s in state['sources'] if s['id']==source_id and s.get('active', True)
                   and not s.get('error') and not s.get('comparisonOnly')), None)
    if not source: raise ValueError('请选择当前活动的原始资料或审批作为更正依据')
    if source.get('documentInspectionError'):raise ValueError(source['documentInspectionError']+'可改用对应的原始表格作为更正依据。')
    if source.get('attachment') and 'mentionedAttachments' not in source:
        from .recruitment_reviews import document
        info=document(store,state['month'],source_id)
        from .recruitment_documents import unreadable_pages
        if unreadable_pages(info):raise ValueError('审批文字未完整读取，请核对原件或使用对应的原始表格。')
        source = {**source, 'mentionedAttachments':info['mentionedAttachments']}
    return source


def _people(state, ids):
    if not isinstance(ids,list) or not ids or len(ids)>500 or any(not isinstance(i,str) for i in ids):
        raise ValueError('请选择 1 至 500 名需要更正的人员')
    if len(set(ids))!=len(ids): raise ValueError('所选人员重复')
    people = {r['id']:r for r in state['rows']}
    if any(i not in people for i in ids): raise ValueError('所选人员不在本活动，请重新选择')
    return [people[i] for i in ids]


def _pair(values, prefix):
    return {'name':text(values.get(prefix+'姓名')), 'employeeId':text(values.get(prefix+'工号'))}


def context(store, month, revision, row_ids, source_id=None):
    state=store.read(month);store._check(state,revision)
    rows=_people(state,row_ids)
    source=_source(store,state,source_id) if source_id else None
    people=[]
    for row in rows:
        v=row['values'];proposal={};warnings=[]
        # Provenance already binds the imported row to this employment. Do not
        # fuzzy-match names or reuse employee-directory names as role evidence.
        if source and set(source.get('roles',[])) & {'domestic_offer','overseas_offer','supplement'}:
            for role,prefix in ROLES.items():
                values={}
                for suffix in ('姓名','工号'):
                    found={text(p.get('value')) for p in row.get('provenance',{}).get(prefix+suffix,[])
                           if p['sourceId']==source_id and text(p.get('value')) not in {'','-','无'}}
                    if len(found)>1: warnings.append(prefix+'在该文件中有不同值，需核对')
                    values[suffix]=next(iter(found)) if len(found)==1 else ''
                if not any(w.startswith(prefix) for w in warnings) and values['姓名']:
                    proposal[role]={'name':values['姓名'],'employeeId':values['工号']}
        people.append({'id':row['id'],'name':v.get('姓名',''),'employeeId':v.get('工号',''),
                       'hireDate':v.get('入职日期',''), 'current':{k:_pair(v,p) for k,p in ROLES.items()},
                       'unresolvedRoles':[role for role,prefix in ROLES.items() if any(prefix+suffix in row.get('unresolvedFields',[]) for suffix in ('姓名','工号'))],
                       'proposal':proposal,'warnings':warnings})
    return {'revision':revision,'people':people,'sourceId':source_id,
            'missingAttachments':missing_attachments(state,source) if source else [],
            'sources':[{'id':s['id'],'name':s['name'],'attachment':s.get('attachment',False)}
                       for s in state['sources'] if s.get('active',True) and not s.get('error') and not s.get('comparisonOnly')]}


def preview(store, month, payload):
    state=store.read(month);store._check(state,payload.get('revision'))
    changes=payload.get('assignments')
    if not isinstance(changes,list) or any(not isinstance(c,dict) for c in changes): raise ValueError('招聘分工格式无效')
    rows=_people(state,[c.get('rowId') for c in changes])
    manual=payload.get('basisType')=='manual'
    if manual and payload.get('sourceId'):raise ValueError('手工调整不能同时标记来源文件')
    source=None if manual else _source(store,state,payload.get('sourceId'))
    missing=missing_attachments(state,source) if source else []
    if missing: raise ValueError('请先补充审批引用的附件：'+'、'.join(missing))
    reason=text(payload.get('reason')) or ('手工更换招聘分工' if manual else '核对原始依据，更正招聘分工')
    edits=[]
    for row,change in zip(rows,changes):
        if set(change)-{'rowId',*ROLES}: raise ValueError('这里只能更正招聘分工')
        adopted={k:_pair(row['values'],p) for k,p in ROLES.items()}
        for role in ROLES.keys() & change.keys():
            pair=change[role]
            if pair is None and role=='assistant': pair={'name':'','employeeId':''}
            elif not isinstance(pair,dict) or set(pair)-{'name','employeeId'}: raise ValueError('招聘分工人员格式无效')
            else:
                if any(not isinstance(v,str) for v in pair.values()): raise ValueError('请填写人员姓名和工号')
                pair={'name':text(pair.get('name')),'employeeId':text(pair.get('employeeId')).lower()}
                if not pair['name'] or pair['name'] in {'-','无'}: raise ValueError('请选择或填写'+ROLES[role]+'姓名')
            adopted[role]=pair
        primary,assistant=adopted['recruiter'],adopted['assistant']
        if assistant['name'] and ((primary['employeeId'] and primary['employeeId']==assistant['employeeId'])
                                  or (not primary['employeeId'] or not assistant['employeeId']) and primary['name']==assistant['name']):
            raise ValueError(row['values'].get('姓名','')+'：招聘负责人和协助招聘人不能为同一人')
        for role in ROLES.keys() & change.keys():
            if _pair(row['values'],ROLES[role])==adopted[role] and not any(ROLES[role]+suffix in row.get('unresolvedFields',[]) for suffix in ('姓名','工号')): continue
            for key,suffix in [('name','姓名'),('employeeId','工号')]:
                field=ROLES[role]+suffix;value=adopted[role][key]
                edits.append({'rowId':row['id'],'field':field,'value':value,'evidenceId':source['id'] if source else '', 'reason':reason})
    if not edits:raise ValueError('没有需要应用的招聘分工更正')
    return prepare_preview(store,month,state['revision'],edits,origin='招聘分工更正')
