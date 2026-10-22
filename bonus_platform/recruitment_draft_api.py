"""Monthly intake API; deliberately separate from calculation/finalization routes."""
from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from .config import OUTPUT_DIR
from .engine.recruitment_drafts import DraftStore, DraftConflict, EDITABLE_FIELDS
from .engine.recruitment_awards import ensure_calculated, money
from .engine.recruitment_attention import project as attention_project, period_info, named_month
from .engine.recruitment_worksheet import worksheet, export_results
from .engine.recruitment_actions import task_detail, guide
from .engine.recruitment_trials import (ScopedDraftStore, TRIAL, require_confirmation,
                                       previous_confirmed, previous_confirmation_lock, next_month_status, confirmation_message)
from .engine.recruitment_monthly import project as monthly_project
from .engine.recruitment_activities import ACTIVITY
from .engine.recruitment_runtime import data_root

router=APIRouter(prefix='/api/recruitment/drafts',tags=['recruitment-drafts'])
store=ScopedDraftStore(data_root()/'recruitment_drafts')


def public(state):
    from .engine.recruitment_reference_facts import project as reference_project
    if 'referenceFacts' not in state:reference_project(store._folder(state['month']),state)
    ensure_calculated(state)
    from .engine.recruitment_approval_intake import project as approval_project
    state,approval_adjustments=approval_project(store,state)
    previous=previous_confirmed(store,state['month'])
    attention=attention_project(state)
    table=worksheet(state);cells={r['id']:r['cells'] for r in table['rows']}
    current_ids={rid for t in attention['current'] for rid in t['rowIds']}
    history_ids={rid for t in attention['history'] for rid in t['rowIds']}
    from .engine import recruitment_external_results as external
    external_context=external.context(store,state)
    source_rows={}
    for row in state['rows']:
        for ref in row.get('sources',[]): source_rows.setdefault(ref['sourceId'],set()).add(row['id'])
    from .engine.recruitment_field_controls import definitions, SYSTEM_FIELDS
    return {**{k:state[k] for k in ('month','revision','sources','todos','baseline','summary','updatedAt','paymentReady','parentMonth','parentRevision','calculation')},
            'todos':[{**t,'displayTitle':guide(t)[0],'instruction':guide(t)[1],'action':guide(t)[2]} for t in attention['current']],
            'historyTodos':[{**t,'displayTitle':guide(t)[0],'instruction':guide(t)[1],'action':guide(t)[2]} for t in attention['history']],
            'columns':table['columns'],'trial':state.get('trial'),'strictInputs':state.get('strictInputs',False),
            'previousConfirmed':previous,'parentOutdated':bool(previous and state.get('parentMonth')==previous['month']
                                                               and state.get('parentRevision')!=previous['revision']),
            'isTrial':bool(TRIAL.get()),'activity':store.activity(ACTIVITY.get()) if ACTIVITY.get() else None,
            'settlementEnabled':bool(state.get('settlement')),'ruleValidation':state.get('ruleValidation',{}),
            'summary':{**state['summary'],'todoGroups':len(attention['current']),'reviewPeople':len(current_ids),
                       'historyTodoGroups':len(attention['history']),'historyReviewPeople':len(history_ids)},
            'attentionSummary':{k:attention[k] for k in ('currentPeople','historyPeople')},
            'period':period_info(state),
            'intakeSummary':state.get('intakeSummary'),'referenceFacts':state['referenceFacts'],
            'monthly':monthly_project(state,attention),'externalResults':external_context,
            'sources':[{**source,'relatedRowIds':sorted(source_rows.get(source['id'],set()))} for source in state['sources']],
            'fieldControls':definitions(),'editableFields':sorted(EDITABLE_FIELDS-SYSTEM_FIELDS),
            'canUndo':any(o['month']==state['month'] and o['active'] for o in state.get('operations',[])),
            'canRedo':bool(state.get('redoOperations')),
            'reviewEntries':state.get('reviewEntries',[]),
            'approvalAdjustments':approval_adjustments,
            'activeOperations':[o['id'] for o in state.get('operations',[]) if o['active']],
            'rows':[{**{k:r[k] for k in ('id','values','rule','needsReview','offerMatched','scopeStatus')},
                     'needsReview':r['id'] in current_ids or r['id'] in history_ids,
                     'cells':cells[r['id']],
                     'attentionScope':'current' if r['id'] in current_ids else 'history' if r['id'] in history_ids else '',
                     'calculation':{kind:{k:v for k,v in r['calculation'][kind].items() if k!='nodes'} for kind in ('recruitment','referral')}} for r in state['rows']]}


def public_response(state):
    return JSONResponse(public(state))


def call(fn,*args):
    try: return fn(*args)
    except DraftConflict as exc: raise HTTPException(409,str(exc)) from exc
    except (ValueError,KeyError,TypeError) as exc: raise HTTPException(400,str(exc)) from exc


@router.get('/{month}')
def read(month:int):
    state=call(store.read,month)
    previous=(month//100-1)*100+12 if month%100==1 else month-1
    data=public(state)
    data['previousAvailable']=bool(call(store.read,previous)['revision']) if previous>=200001 else False
    data['previousMonth']=previous
    data['previousAccepted']=(store._folder(previous)/'accepted.json').exists() if previous>=200001 and not TRIAL.get() else False
    receipt=store._folder(month)/'accepted-status.json'
    if receipt.exists():
        import json
        data['confirmation']=json.loads(receipt.read_text())
    return JSONResponse(data)


@router.post('/{month}/confirm-month')
def confirm_month(month:int,payload:dict[str,Any]):
    from datetime import datetime
    from .engine import recruitment_prepare as jobs
    from .engine.recruitment_trials import _require_idle
    if TRIAL.get():raise HTTPException(400,'请先预览新旧结果，再采用为本月并确认')
    with jobs.GUARD:
        call(_require_idle,month,store)
        with previous_confirmation_lock(store,month),store._lock(month) as folder:
            state=call(store.read,month);call(store._check,state,payload.get('revision'))
            call(require_confirmation,state,payload.get('coverageConfirmed'),store)
            record={'revision':state['revision'],'confirmedAt':datetime.now().isoformat(timespec='seconds'),'state':state}
            store._write(folder/'accepted'/f"{state['revision']}.json",record)
            store._write(folder/'accepted.json',record)
            store._write(folder/'accepted-status.json',{'revision':record['revision'],'confirmedAt':record['confirmedAt']})
    following=next_month_status(store,month,state['revision'])
    return {'revision':state['revision'],'confirmedAt':record['confirmedAt'],'nextMonth':following,
            'message':'已确认当前活动；新建下月活动时可选择承接此结果；未标记为已支付。' if ACTIVITY.get() else confirmation_message('已保存本月核算版本',following)}


@router.get('/{month}/adoption-preview')
def adoption_preview(month:int,sourceRevision:int):
    return call(store.adoption_preview,month,sourceRevision)


@router.post('/{month}/adopt-month')
def adopt_month(month:int,payload:dict[str,Any]):
    return call(store.adopt_month,month,payload.get('sourceRevision'),payload.get('targetRevision'),payload.get('coverageConfirmed'))


@router.post('/{month}/opening-empty')
def confirm_empty_opening(month:int,payload:dict[str,Any]):
    from .engine.recruitment_drafts import _date
    with store._lock(month) as folder:
        state=call(store.read,month);call(store._check,state,payload.get('revision'))
        if payload.get('confirmed') is not True:raise HTTPException(400,'请确认没有历史未结奖金')
        if state.get('baseline') or state.get('parentMonth') or any(not r.get('externalOnly') and _date(r['values'])[:7].replace('-','')<str(month) for r in state['rows']) or any(s.get('active',True) and 'ledger' in s.get('roles',[]) and not s.get('comparisonOnly') for s in state['sources']):
            raise HTTPException(400,'当前存在历史记录，请采用真实期初，不能设为空期初')
        if not state.get('openingEmptyConfirmed'):
            state['openingEmptyConfirmed']=True;state=store._save(folder,store._rebuild(folder,state))
        return public_response(state)


@router.post('/{month}/carry-forward')
def carry_forward(month:int,payload:dict[str,Any]):
    return public_response(call(store.carry_forward,month,payload.get('sourceMonth'),payload.get('revision')))


@router.post('/{month}/refresh')
def refresh(month:int,payload:dict[str,Any]):
    return public_response(call(store.refresh,month,payload.get('revision')))


@router.get('/{month}/prepare')
def prepare_status(month:int):
    from .engine.recruitment_prepare import read
    return call(read,store,month)


@router.get('/{month}/changes')
def change_history(month:int):
    state=call(store.read,month);names={r['id']:r['values'].get('姓名','') for r in state['rows']}
    return {'revision':state['revision'],'entries':[{**e,'name':names.get(e['rowId'],'')} for e in reversed(state.get('edits',[]))]}


@router.post('/{month}/prepare')
def prepare_month(month:int,payload:dict[str,Any]):
    from .engine.recruitment_prepare import start
    return call(start,store,month,payload.get('revision'),bool(payload.get('force')),bool(payload.get('localOnly')),
                bool(payload.get('includeOverseas')))


@router.post('/{month}/sync-overseas')
def sync_overseas(month:int,payload:dict[str,Any]):
    from .engine.recruitment_prepare import start
    return call(start,store,month,payload.get('revision'),False,False,False,True)


@router.post('/{month}/sync-domestic-monthly')
def sync_domestic_monthly(month:int,payload:dict[str,Any]):
    from .engine.recruitment_prepare import start
    return call(start,store,month,payload.get('revision'),False,False,False,False,True)


@router.post('/{month}/sync-monthly')
def sync_monthly(month:int,payload:dict[str,Any]):
    from .engine.recruitment_prepare import start
    return call(start,store,month,payload.get('revision'),False,False,False,False,False,True)


@router.post('/{month}/prepare/cancel')
def cancel_preparation(month:int,payload:dict[str,Any]):
    from .engine.recruitment_prepare import cancel
    return call(cancel,store,month,payload.get('jobId'))


@router.post('/{month}/sync-domestic')
async def sync_domestic(month:int,payload:dict[str,Any]):
    from .engine.recruitment_beisen import fetch
    from .engine.recruitment_drafts import staff_id, ROLE_FIELDS
    state=call(store.read,month)
    call(store._check,state,payload.get('revision'))
    from .engine.recruitment_external_results import automatic_roles
    numbers=sorted({staff_id(r['values'].get('工号')) for r in state['rows']
        if r['values'].get('标签分类')=='国内' and r['values'].get('是否虚拟员工')!='是' and staff_id(r['values'].get('工号')) and any(automatic_roles(r,k) for k in ('recruitment','referral'))})
    if not numbers:raise HTTPException(400,'请先添加本批人员资料；同步按本批国内人员查询，海外和体系外请继续上传')
    recipients=sorted({staff_id(r['values'].get(f)) for r in state['rows'] for f,prefix,_,_ in ROLE_FIELDS if prefix in automatic_roles(r,'referral' if prefix=='推荐人' else 'recruitment') and staff_id(r['values'].get(f)).startswith('zt')})
    snapshot=await run_in_threadpool(call,fetch,numbers,None,recipients) if recipients else await run_in_threadpool(call,fetch,numbers)
    return public_response(await run_in_threadpool(call,store.save_beisen_snapshot,month,payload.get('revision'),snapshot))


def call_when_prepared(fn,month,*args):
    from .engine import recruitment_prepare as jobs
    # start() registers under the same guard. An upload cannot pass an idle
    # check and then invalidate the version being prepared in another tab.
    with jobs.GUARD:
        if jobs.key_for(store,month) in jobs.RUNNING:
            raise HTTPException(409,'资料正在整理和核算，完成后再导入或导出。')
        return call(fn,month,*args)


@router.post('/{month}/sources')
async def upload(month:int,revision:int=Form(...),files:list[UploadFile]=File(...),periodConfirmed:bool=Form(False),comparisonOnly:bool=Form(False)):
    existing=call(store.read,month)
    suggested=named_month(f.filename or '' for f in files)
    if suggested and suggested!=month and not existing['revision'] and not periodConfirmed:
        raise HTTPException(409,{'code':'material_month','suggestedMonth':suggested,'message':f'台账月份为{suggested//100}年{suggested%100}月，请核对核算月份'})
    payload=[]
    for upload in files:
        # Reject oversized input before reading an unbounded body into process memory.
        content=await upload.read(80*1024*1024+1)
        if len(content)>80*1024*1024: raise HTTPException(413,'单份文件不能超过80MB')
        payload.append((upload.filename or '资料.xlsx',content))
    state=await run_in_threadpool(call_when_prepared,store.ingest,month,payload,revision,periodConfirmed and bool(suggested and suggested!=month),comparisonOnly)
    return public_response(state)


@router.get('/{month}/external-results')
def external_results_context(month:int):
    from .engine import recruitment_external_results as external
    return call(external.context,store,call(store.read,month))


@router.get('/{month}/external-results/template')
def external_results_template(month:int):
    from .engine import recruitment_external_results as external
    import urllib.parse
    content=call(external.template,month)
    name=urllib.parse.quote(f'体系外核算结果{month}.xlsx')
    return StreamingResponse(BytesIO(content),media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition':f"attachment; filename*=UTF-8''{name}"})


@router.post('/{month}/external-results/import')
async def external_results_import(month:int,revision:int=Form(...),files:list[UploadFile]=File(...)):
    from .engine import recruitment_external_results as external
    payload=[]
    for upload in files:
        content=await upload.read(80*1024*1024+1)
        if len(content)>80*1024*1024:raise HTTPException(413,'单份文件不能超过80MB')
        payload.append((upload.filename or '体系外结果.xlsx',content))
    return await run_in_threadpool(call_when_prepared,lambda m:external.prepare_import(store,m,revision,payload),month)


@router.post('/{month}/external-results/scope')
def external_results_scope(month:int,payload:dict[str,Any]):
    from .engine import recruitment_external_results as external
    state=call_when_prepared(lambda m:external.apply_scope(store,m,payload.get('revision'),payload.get('scopes')),month)
    return public_response(state)


@router.post('/{month}/external-results/previews/{token}')
def external_results_repreview(month:int,token:str,payload:dict[str,Any]):
    from .engine import recruitment_external_results as external
    return call_when_prepared(lambda m:external.repreview(store,m,payload.get('revision'),token,payload.get('resolutions',[])),month)


@router.post('/{month}/external-results/previews/{token}/apply')
def external_results_apply(month:int,token:str,payload:dict[str,Any]):
    from .engine import recruitment_external_results as external
    state,count=call_when_prepared(lambda m:external.apply_import(store,m,payload.get('revision'),token),month)
    return JSONResponse({'state':public(state),'externalResults':external.context(store,state),'appliedCount':count,
                         'message':f'已采用 {count} 项体系外核算结果' if count else '核算结果已更新，本次未重复采用'})


@router.post('/{month}/correct-period')
def correct_period(month:int,payload:dict[str,Any]):
    if ACTIVITY.get():raise HTTPException(400,'活动月份固定，请新建正确月份的活动；原资料保留')
    return public_response(call(store.correct_period,month,payload.get('revision')))


@router.post('/{month}/changes')
def change(month:int,payload:dict[str,Any]):
    if not isinstance(payload.get('revision'),int): raise HTTPException(400,'缺少当前底稿版本，请刷新后重试')
    return public_response(call(store.change,month,payload['revision'],payload))


@router.get('/{month}/rows/{row_id}')
def row_detail(month:int,row_id:str):
    from .engine.recruitment_actions import referral_suggestion
    state=ensure_calculated(call(store.read,month))
    row=next((r for r in state['rows'] if r['id']==row_id),None)
    if not row: raise HTTPException(404,'人员记录不存在')
    from .engine.recruitment_field_controls import controls
    return {'revision':state['revision'],'row':{**row,'fieldControls':controls(state,row),'reviewSuggestion':referral_suggestion(row,state)}}


@router.post('/{month}/field-controls')
def field_controls(month:int,payload:dict[str,Any]):
    from .engine.recruitment_field_controls import shared_controls
    state=call(store.read,month);call(store._check,state,payload.get('revision'))
    ids=payload.get('rowIds')
    if not isinstance(ids,list) or not ids or len(ids)>5000 or any(not isinstance(rid,str) for rid in ids):
        raise HTTPException(400,'请选择需要修改的人员')
    rows={row['id']:row for row in state['rows']}
    if any(rid not in rows for rid in ids):raise HTTPException(400,'人员记录已变化，请重新选择')
    return {'revision':state['revision'],'fieldControls':shared_controls(state,[rows[rid] for rid in ids])}


@router.get('/{month}/tasks/{task_id}')
def review_task(month:int,task_id:str):
    return call(task_detail,call(store.read,month),task_id)


@router.get('/{month}/sources/{source_id}/preview')
def source_preview(month:int,source_id:str,sheet:str='',query:str='',page:int=1):
    from .engine.recruitment_source_preview import preview
    return call(preview,store,month,source_id,sheet,query,page)


@router.get('/{month}/sources/{source_id}')
def source_file(month:int,source_id:str):
    state=call(store.read,month)
    source=next((s for s in state['sources'] if s['id']==source_id),None)
    if not source: raise HTTPException(404,'来源文件不存在')
    path=store._folder(month)/'sources'/Path(source['storedName']).name
    if not path.is_file(): raise HTTPException(404,'来源文件不存在')
    return FileResponse(path,filename=source['name'])


def safe_cell(value):
    if isinstance(value,(dict,list)):
        import json
        value=json.dumps(value,ensure_ascii=False)
    if isinstance(value,str) and value.startswith(('=','+','-','@')): return "'"+value
    return value


@router.get('/{month}/export')
def export(month:int):
    state=ensure_calculated(call(store.read,month))
    attention=attention_project(state)
    review_ids={rid for key in ('current','history') for task in attention[key] for rid in task['rowIds']}
    wb=Workbook(); wb.remove(wb.active)
    def sheet(name,headers,rows):
        ws=wb.create_sheet(name); ws.append(headers)
        for row in rows: ws.append([safe_cell(v) for v in row])
        ws.freeze_panes='C2'; ws.auto_filter.ref=ws.dimensions
        for cell in ws[1]: cell.font=Font(color='FFFFFF',bold=True); cell.fill=PatternFill('solid',fgColor='1E3A8A')
        for col in ws.columns: ws.column_dimensions[col[0].column_letter].width=20
    fields=list(dict.fromkeys(['姓名','工号','入职日期','标签分类','人员状态','转正日期','最后工作日','招聘负责人工号','ABC类别']+sorted({f for r in state['rows'] for f in r['values']})))
    sheet('工作底稿',['记录标识','底稿版本','规则归属','归属依据','待核']+fields,
          [[r['id'],state['revision'],r['rule']['label'],r['rule']['basis'],'是' if r['id'] in review_ids else '否']+[r['values'].get(f,'') for f in fields] for r in state['rows']])
    sheet('集中待办',['范围','事项','原因','影响记录标识','依据文件'],
          [[scope,t['title'],'；'.join(t['reasons']),'、'.join(t['rowIds']),'、'.join(t['sourceIds'])] for key,scope in [('current','本月待办'),('history','历史待核')] for t in attention[key]])
    sheet('人工更正',['记录标识','字段','原值','采用值','依据','时间'],[[e['rowId'],e['field'],e['before'],e['value'],e['reason'],e['at']] for e in state['edits']])
    sheet('历史原记录',['记录标识','来源文件','工作表','行','列','字段','原值','支付状态'],
          [[r['id'],h['ref']['sourceId'],h['ref']['sheet'],h['ref']['row'],c['column'],c['label'],c['value'],'未核实'] for r in state['rows'] for h in r['history'] for c in h['cells']])
    sheet('资料清单',['文件','摘要','记录数','状态','已认可期初'],[[s['name'],s['id'],s.get('recordCount',0),'使用中' if s['active'] else '已停用','是' if state['baseline']==s['id'] else '否'] for s in state['sources']])
    out=BytesIO(); wb.save(out); out.seek(0)
    from urllib.parse import quote
    filename=quote(f"招聘奖金_{month}_工作底稿_草稿_v{state['revision']}.xlsx")
    return StreamingResponse(out,media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition':f"attachment; filename*=UTF-8''{filename}"})


@router.get('/{month}/calculation/export')
def export_calculation(month:int):
    from urllib.parse import quote
    data=export_results(ensure_calculated(call(store.read,month)))
    filename=quote(f'招聘奖金_{month}_核算结果_草稿.xlsx')
    return StreamingResponse(BytesIO(data),media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':f"attachment; filename*=UTF-8''{filename}"})


@router.get('/{month}/monthly/export')
def export_monthly(month:int,revision:int):
    from urllib.parse import quote
    from .engine.recruitment_monthly import export, export_filename
    state=call_when_prepared(store.read,month);call(store._check,state,revision);ensure_calculated(state)
    data=export(state,monthly_project(state,attention_project(state)))
    filename=quote(export_filename(month))
    return StreamingResponse(BytesIO(data),media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':f"attachment; filename*=UTF-8''{filename}"})


@router.get('/{month}/work-items/{item_id}')
def work_item(month:int,item_id:str,revision:int):
    from .engine.recruitment_work_items import project,detail
    state=call(store.read,month);call(store._check,state,revision);ensure_calculated(state)
    from .engine.recruitment_reference_facts import project as reference_project,enrich_detail
    if 'referenceFacts' not in state:reference_project(store._folder(month),state)
    attention=attention_project(state)
    item=next((i for i in project(state,attention) if i['id']==item_id),None)
    if item is None or item['key']=='attachment_review' or item['key'].startswith('approval:'):
        from .engine.recruitment_approval_intake import project as approval_project
        state,_=call(approval_project,store,state)
        attention=attention_project(state)
        item=next((i for i in project(state,attention) if i['id']==item_id),None)
    if not item:raise HTTPException(404,'该事项已更新，请重新读取')
    return enrich_detail(store._folder(month),state,detail(state,item,attention))


@router.get('/{month}/people')
def review_people(month:int,revision:int,q:str=''):
    from .engine.recruitment_work_items import people_choices
    if len(q)>100:raise HTTPException(400,'姓名或工号过长')
    state=call(store.read,month);call(store._check,state,revision)
    return {'people':people_choices(store._folder(month),state,q),'revision':state['revision']}


@router.post('/{month}/assignments/context')
def assignment_context(month:int,payload:dict[str,Any]):
    from .engine.recruitment_assignments import context
    return call(context,store,month,payload.get('revision'),payload.get('rowIds'),payload.get('sourceId'))


@router.post('/{month}/assignments/preview')
def assignment_preview(month:int,payload:dict[str,Any]):
    from .engine.recruitment_assignments import preview
    return call_when_prepared(lambda m:preview(store,m,payload),month)


@router.get('/{month}/work-items/{item_id}/supplement.xlsx')
def work_supplement(month:int,item_id:str,revision:int,includeFuture:bool=False):
    from urllib.parse import quote
    from .engine.recruitment_work_items import supplement_workbook
    data=work_item(month,item_id,revision)
    if data['mode']!='intake':raise HTTPException(400,'此事项不使用录用信息补充表')
    state=call(store.read,month);call(store._check,state,revision)
    content=call(supplement_workbook,state,data,includeFuture)
    filename=quote(f'录用信息补充表_{month}_v{revision}.xlsx')
    return StreamingResponse(BytesIO(content),media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':f"attachment; filename*=UTF-8''{filename}"})


@router.post('/{month}/history')
def history(month:int,payload:dict[str,Any]):
    return public_response(call(store.history_action,month,payload.get('revision'),payload.get('action')))


@router.get('/{month}/approval-adjustments')
def approval_adjustments(month:int):
    from .engine.recruitment_approval_intake import proposals
    return call(proposals,store,call(store.read,month))


@router.post('/{month}/approval-adjustments/preview')
def preview_approval_adjustments(month:int,payload:dict[str,Any]):
    from .engine.recruitment_approval_intake import preview
    return call(preview,store,month,payload)


@router.get('/{month}/documents/{source_id}')
def approval_document(month:int,source_id:str):
    from .engine.recruitment_reviews import document
    return call(document,store,month,source_id)


@router.get('/{month}/documents/{source_id}/pages/{page}')
def approval_page(month:int,source_id:str,page:int):
    from .engine.recruitment_reviews import document
    info=call(document,store,month,source_id)
    if page<1 or page>info['pageCount']: raise HTTPException(404,'审批页码不存在')
    return FileResponse(store._folder(month)/'documents'/source_id/f'page-{page}.png',media_type='image/png')


@router.get('/{month}/special')
def special_context(month:int):
    from .engine.recruitment_special import context
    return context(ensure_calculated(call(store.read,month)))


@router.post('/{month}/special/preview')
def special_preview(month:int,payload:dict[str,Any]):
    from .engine.recruitment_special import preview
    return call_when_prepared(lambda m:preview(store,m,payload),month)


@router.post('/{month}/special/previews/{token}/apply')
def special_apply(month:int,token:str,payload:dict[str,Any]):
    from .engine.recruitment_special import apply_preview
    return public_response(call_when_prepared(lambda m:apply_preview(store,m,payload.get('revision'),token),month))


@router.post('/{month}/reviews')
def record_review(month:int,payload:dict[str,Any]):
    from .engine.recruitment_reviews import save_review
    return public_response(call(save_review,store,month,payload.get('revision'),payload.get('evidence')))


@router.post('/{month}/cycle-confirmations')
def confirm_original_cycle(month:int,payload:dict[str,Any]):
    from .engine.recruitment_work_items import confirm_original_cycle as confirm
    return public_response(call_when_prepared(lambda m:confirm(store,m,payload.get('revision'),payload.get('rowIds')),month))


@router.post('/{month}/previews')
def preview(month:int,payload:dict[str,Any]):
    from .engine.recruitment_reviews import prepare_preview
    try:
        return prepare_preview(store,month,payload.get('revision'),payload.get('edits',[]),evidence=payload.get('evidence'),origin='审批更正' if payload.get('evidence') else '手工设置不发奖金' if payload.get('decisions') else '工作表更正',arrangements=payload.get('arrangements'),decisions=payload.get('decisions'),basis_type=payload.get('basisType'),reference_selections=payload.get('referenceSelections'),employment_selections=payload.get('employmentSelections'))
    except DraftConflict as exc: raise HTTPException(409,str(exc)) from exc
    except (ValueError,KeyError,TypeError) as exc: raise HTTPException(400,str(exc)) from exc


@router.post('/{month}/previews/{token}/apply')
def apply_review_preview(month:int,token:str,payload:dict[str,Any]):
    from .engine.recruitment_reviews import apply_preview
    return public_response(call(apply_preview,store,month,payload.get('revision'),token))


@router.get('/{month}/worksheet')
def download_worksheet(month:int):
    from urllib.parse import quote
    from .engine.recruitment_reviews import editable_workbook
    data=call(editable_workbook,call(store.read,month))
    filename=quote(f'招聘奖金_{month}_可编辑底稿.xlsx')
    return StreamingResponse(BytesIO(data),media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':f"attachment; filename*=UTF-8''{filename}"})


@router.post('/{month}/worksheet/preview')
async def return_worksheet(month:int,revision:int=Form(...),file:UploadFile=File(...),sourceId:str=Form(''),reason:str=Form('')):
    from .engine.recruitment_reviews import workbook_edits,prepare_preview
    content=await file.read(30*1024*1024+1)
    if len(content)>30*1024*1024: raise HTTPException(413,'回传表格不能超过30MB')
    def prepare():
        state=call(store.read,month);call(store._check,state,revision)
        edits=call(workbook_edits,state,content)
        for edit in edits:
            if sourceId:edit['evidenceId']=sourceId
            if reason.strip():edit['reason']=reason.strip()
        return call(prepare_preview,store,month,revision,edits)
    return await run_in_threadpool(prepare)


@router.get('/{month}/review-center')
def review_center(month:int,revision:int,sourceId:str=''):
    from .engine.recruitment_review_center import project
    state=call(store.read,month);call(store._check,state,revision)
    return call(project,store,state,sourceId)


@router.post('/{month}/review-center')
def save_difference_review(month:int,payload:dict[str,Any]):
    from .engine.recruitment_review_center import save_review
    return public_response(call_when_prepared(lambda m,p: save_review(store,m,p),month,payload))


@router.get('/{month}/reconciliation/{source_id}')
def compare_ledger(month:int,source_id:str):
    from .engine.recruitment_reconcile import reconcile
    return call(reconcile,store,month,source_id)


@router.get('/{month}/reconciliation/{source_id}/export')
def export_ledger_comparison(month:int,source_id:str):
    from urllib.parse import quote
    from .engine.recruitment_reconcile import reconcile,export_reconciliation
    data=call(export_reconciliation,call(reconcile,store,month,source_id))
    filename=quote(f'招聘奖金_{month}_差异核对.xlsx')
    return StreamingResponse(BytesIO(data),media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':f"attachment; filename*=UTF-8''{filename}"})


@router.post('/{month}/installment-previews')
def installment_preview(month:int,payload:dict[str,Any]):
    from .engine.recruitment_settlement import preview_plan
    return call(preview_plan,store,month,payload)


@router.post('/{month}/installment-previews/{token}/apply')
def installment_apply(month:int,token:str,payload:dict[str,Any]):
    from .engine.recruitment_settlement import apply_plan
    return public_response(call(apply_plan,store,month,payload.get('revision'),token))


trials_router=APIRouter(prefix='/api/recruitment/trials',tags=['recruitment-trials'])


@trials_router.get('')
def trials():return store.list_trials()


@trials_router.post('')
def create_trial(payload:dict[str,Any]):
    return call(store.create_trial,payload.get('month'),payload.get('name',''),payload.get('opening'))


async def trial_context(trial_id:str,month:int):
    trial=call(store.trial,trial_id)
    if month!=trial['month']:raise HTTPException(400,'独立批次的核算月份固定，请另建批次')
    token=TRIAL.set(trial_id)
    try:yield
    finally:TRIAL.reset(token)


trial_drafts_router=APIRouter(prefix='/api/recruitment/trials/{trial_id}',dependencies=[Depends(trial_context)])
trial_drafts_router.include_router(router)

# The activity dependency scopes every existing intake, export, review and trial
# route, including copied ContextVars in background preparation jobs.
activities_router=APIRouter(prefix='/api/recruitment/activities',tags=['recruitment-activities'])

@activities_router.get('')
def activities():return {'activities':call(store.list_activities),'legacyRecords':call(store.legacy_records)}

@activities_router.post('')
def create_activity(payload:dict[str,Any]):
    return call(store.create_activity,payload.get('month'),payload.get('name',''),payload.get('opening'))

@activities_router.get('/snapshot-library/{month}')
def snapshot_library_status(month:int):
    from .engine.recruitment_snapshot_library import SnapshotLibrary
    return call(SnapshotLibrary(store).status,month)

@activities_router.post('/snapshot-library/{month}/refresh')
def refresh_snapshot_library(month:int):
    from .engine.recruitment_snapshot_library import start_refresh
    return call(start_refresh,store,month)

@activities_router.patch('/snapshot-library/schedule')
def configure_snapshot_schedule(payload:dict[str,Any]):
    from .engine.recruitment_snapshot_library import SnapshotLibrary
    return call(SnapshotLibrary(store).configure,payload)

@activities_router.patch('/{activity_id}')
def update_activity(activity_id:str,payload:dict[str,Any]):return call(store.update_activity,activity_id,payload)

async def activity_context(activity_id:str,request:Request):
    try:
        with store.activity_lock(activity_id) as activity:
            month=request.path_params.get('month')
            if month is not None and str(month)!=str(activity['month']):raise HTTPException(400,'请在活动的核算月份内操作')
            if activity['archived'] and request.method not in {'GET','HEAD'}:raise HTTPException(409,'活动已归档，请先在活动列表恢复后再修改')
            token=ACTIVITY.set(activity_id)
            try:yield
            finally:ACTIVITY.reset(token)
    except DraftConflict as exc:raise HTTPException(409,str(exc)) from exc
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc

activity_drafts_router=APIRouter(prefix='/api/recruitment/activities/{activity_id}',dependencies=[Depends(activity_context)])
activity_drafts_router.include_router(router)
activity_drafts_router.include_router(trials_router)
activity_drafts_router.include_router(trial_drafts_router)
