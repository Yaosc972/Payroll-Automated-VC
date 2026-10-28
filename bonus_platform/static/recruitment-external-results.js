(() => {
  'use strict';
  const w=window.RecruitmentWorkbench,{$,ui,e,base,request,openDialog,adopt,busy,status}=w;
  const size=40;
  const outcomeLabels={pay:'本月发放',exclude:'不发',hold:'暂缓',pending:'待核定'};
  const statusLabels={ready:'待采用',unchanged:'未变化',blocked:'需处理',missing:'待导入本月结果',adopted:'已采用',active:'已采用',invalid:'资料已失效',superseded:'已替换',revoked:'已撤销'};
  const money=(value,currency='')=>value===null||value===undefined||value===''?'未提供':`${Number(value).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2})}${currency?' '+currency:''}`;
  function tableModel(data,options={}){
    const query=String(options.query||'').trim().toLowerCase();
    const filtered=(data.rows||[...(data.expected||[]),...(data.records||[])]).filter(row=>(options.filter!=='blocked'||row.status==='blocked')&&[row.candidateName,row.candidateId,row.recipientName,row.recipientId,row.project,row.sourceName,...(row.issues||[])].join(' ').toLowerCase().includes(query));
    const pages=Math.max(1,Math.ceil(filtered.length/size)),page=Math.max(1,Math.min(options.page||1,pages));
    return {rows:filtered.slice((page-1)*size,page*size),page,pages,total:filtered.length};
  }
  function cardState(context){
    if(!context)return {label:'按需导入',tone:'muted'};
    const invalid=(context.records||[]).filter(row=>row.status==='invalid').length;
    if(invalid)return {label:`${invalid} 项资料已失效`,tone:'missing'};
    const pending=(context.pendingImports||[]).reduce((sum,item)=>sum+Number(item.readyCount||0)+Number(item.blockedCount||0),0);
    if(pending)return {label:`${pending} 项待处理`,tone:'missing'};
    if(context.expected?.length)return {label:'待导入本月结果',tone:'missing'};
    return context.summary?.records?{label:`已采用 ${context.summary.records} 项`,tone:'ready'}:{label:'按需导入',tone:'muted'};
  }
  function fileState(context,id){
    const known=context?.sourceStatuses?.[id];
    if(known==='invalid')return '资料已失效';
    const pending=(context?.pendingImports||[]).filter(item=>item.sourceIds?.includes(id));
    if(pending.some(item=>item.blockedCount))return '需处理';
    if(pending.some(item=>item.readyCount))return '待采用';
    if(known)return ({adopted:'已采用',superseded:'已替换',revoked:'已撤销',pending:'待采用'})[known]||known;
    const rows=(context?.records||[]).filter(row=>row.sourceId===id);
    if(rows.some(row=>row.status==='invalid'))return '资料已失效';
    if(rows.some(row=>!['superseded','revoked','invalid'].includes(row.status)))return '已采用';
    if(rows.some(row=>row.status==='superseded'))return '已替换';
    if(rows.length)return '已撤销';
    return '待采用';
  }
  let session=null,sequence=0,uploadInput;
  const current=s=>session===s&&base()===s.base&&$('draftInspector').open;
  const locked=()=>ui.busy||['running','cancelling'].includes(ui.prepareJob?.status)||ui.data?.activity?.archived;
  const post=(s,path,payload)=>request(s.base+'/external-results'+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  function totals(values){return Object.entries(values||{}).map(([currency,value])=>`<span>${e(money(value,currency))}</span>`).join('');}
  function source(row){
    const file=row.sourceName||(session.preview?.files||[]).find(item=>item.id===row.sourceId)?.name||'';
    return [file,row.sheet,row.sourceRows?.length?`第 ${row.sourceRows.join('、')} 行`:''].filter(Boolean).join(' · ');
  }
  function rowMarkup(row){
    const identity=[row.candidateId,row.hireDate].filter(Boolean).join(' · ');
    const candidates=row.status==='blocked'&&row.candidates?.length>1?`<label class="rer-person">对应任职<select data-external-person="${e(row.id)}"><option value="">请选择对应人员与任职</option>${row.candidates.map(person=>`<option value="${e(person.rowId)}">${e([person.name,person.number,person.hireDate].filter(Boolean).join(' · '))}</option>`).join('')}</select></label>`:'';
    const review=row.status==='blocked'&&row.scopeExpanded&&row.rowId?`<button class="rd-text-button" type="button" data-external-review="${e(row.rowId)}">核对领取人与补扣</button>`:'';
    const state=row.status==='ready'&&row.change==='replacement'?'更正后替换':statusLabels[row.status]||row.status||'已采用';
    return `<tr data-external-row="${e(row.id)}" data-state="${e(row.status||'adopted')}"><td><strong>${e(row.candidateName||'被招聘人未提供')}</strong>${identity?`<span class="rer-sub">${e(identity)}</span>`:''}${candidates}${review}</td><td>${e(row.project||'未提供')}</td><td>${e(row.recipientName||'未提供')}${row.recipientId?`<span class="rer-sub">${e(row.recipientId)}</span>`:''}</td><td class="rer-number">${e(money(row.amount,row.currency))}</td><td>${e(outcomeLabels[row.outcome]||row.outcome||'本月发放')}</td><td><span class="rer-state">${e(state)}</span>${row.issues?.length?`<ul class="rer-issues">${row.issues.map(issue=>`<li>${e(issue)}</li>`).join('')}</ul>`:''}${source(row)?row.sourceId?`<a class="rer-sub" href="${session.base}/sources/${encodeURIComponent(row.sourceId)}" title="${e(source(row))}" aria-label="原表：${e(source(row))}" download>原表</a>`:`<span class="rer-sub">${e(source(row))}</span>`:''}</td></tr>`;
  }
  function drawTable(){
    const s=session,data=s.preview||s.context,model=tableModel(data,{query:s.query,filter:s.filter,page:s.page});s.page=model.page;
    $('externalRows').innerHTML=model.rows.length?`<div class="rer-table-scroll"><table class="rer-table"><thead><tr><th>被招聘人</th><th>奖金项目</th><th>领取人</th><th class="rer-number">本月核定金额</th><th>发放状态</th><th>处理状态与来源</th></tr></thead><tbody>${model.rows.map(rowMarkup).join('')}</tbody></table></div>`:'<p class="rer-empty">'+(s.preview?'没有符合条件的记录。':'尚未采用本月体系外核算结果。')+'</p>';
    $('externalPageCount').textContent=`${model.total} 项${model.pages>1?` · 第 ${model.page} / ${model.pages} 页`:''}`;
    $('externalPrevious').disabled=model.page===1;$('externalNext').disabled=model.page===model.pages;
    $('externalPager').hidden=model.pages===1;
    $('externalRows').querySelectorAll('[data-external-person]').forEach(select=>select.onchange=()=>resolve(select.dataset.externalPerson,select.value));
    $('externalRows').querySelectorAll('[data-external-review]').forEach(button=>button.onclick=()=>{if(session?.operation)return;session=null;$('draftInspector').classList.remove('rer-dialog','rd-wide');w.inspector(button.dataset.externalReview);});
  }
  function controls(){
    if(!session||!$('externalPanel'))return;
    const s=session,working=Boolean(s.operation),stale=s.base!==base()||s.revision!==ui.data.revision;
    $('externalPanel').setAttribute('aria-busy',String(working));
    $('externalEditor').inert=working;
    $('draftCloseInspector').disabled=working;
    ['externalUpload','externalReload','externalDetail','externalRecords'].forEach(id=>{if($(id))$(id).disabled=working||locked();});
    const button=$('externalApply');
    if(button){button.disabled=working||locked()||stale||!s.preview?.canApply||!s.preview.readyCount;button.innerHTML=s.operation==='apply'?'<span class="rer-spinner" aria-hidden="true"></span>正在采用并更新核算…':`采用 ${s.preview?.readyCount||0} 项`;button.setAttribute('aria-busy',String(s.operation==='apply'));}
    const feedback=s.notice||(stale?{tone:'error',message:'资料已更新，请重新读取结果。'}:null);
    $('externalFeedback').hidden=!feedback;$('externalFeedback').dataset.tone=feedback?.tone||'';
    $('externalFeedback').textContent=feedback?.message||'';
    $('externalReload').hidden=!stale;
    $('externalUpload').innerHTML=working&&s.operation==='upload'?'<span class="rer-spinner" aria-hidden="true"></span>正在识别表格…':s.preview?'更正表格后重传':'上传结果';
  }
  function render(){
    const s=session,preview=s.preview,context=s.context;
    const pending=!preview?(context.pendingImports||[]):[];
    const count=preview?`${preview.peopleCount||0} 人 · ${preview.readyCount||0} 项可采用${preview.appliedCount?` · ${preview.appliedCount} 项已采用`:''}${preview.blockedCount?` · ${preview.blockedCount} 项需处理`:''}${preview.unchangedCount?` · ${preview.unchangedCount} 项未变化`:''}`:`${context.summary?.people||0} 人 · ${context.summary?.records||0} 项已采用${context.expected?.length?` · ${context.expected.length} 项待导入`: ""}`;
    openDialog('体系外核算结果',`<section id="externalPanel" class="rer-panel"><div id="externalEditor"><div class="rer-toolbar"><strong>${e(count)}</strong><button id="externalUpload" class="rd-button" type="button">上传结果</button><input id="externalUploadFiles" type="file" accept=".xlsx,.xlsm" multiple hidden/></div><div class="rer-totals" aria-label="本月发放合计">${Object.keys(preview?.totalsByCurrency||context.summary?.totalsByCurrency||{}).length?'<strong>本月发放合计</strong>':''}${totals(preview?.totalsByCurrency||context.summary?.totalsByCurrency)}</div>${pending.length?`<div class="rer-pending">${pending.map(item=>`<button class="rd-button" type="button" data-external-preview="${e(item.token)}">继续处理 ${e(item.name||'已上传结果')} · ${item.readyCount||0} 项可采用${item.blockedCount?' · '+item.blockedCount+' 项需处理':''}</button>`).join('')}</div>`:''}<div class="rer-filters"><input id="externalSearch" type="search" value="${e(s.query)}" placeholder="搜索被招聘人、领取人或问题" aria-label="搜索体系外核算结果"/>${preview?.blockedCount?`<button id="externalProblems" class="rd-button" type="button" aria-pressed="${s.filter==='blocked'}">仅看需处理 · ${preview.blockedCount} 项</button>`:''}<span id="externalPageCount" role="status"></span></div><div id="externalRows"></div><div id="externalPager" class="rer-pager"><button id="externalPrevious" class="rd-button" type="button">上一页</button><button id="externalNext" class="rd-button" type="button">下一页</button></div></div><footer class="rer-footer"><p id="externalFeedback" class="rer-feedback" role="status" aria-live="polite" hidden></p><div class="rer-actions"><button id="externalReload" class="rd-button" type="button" hidden>重新读取结果</button><span></span>${preview?'<button id="externalRecords" class="rd-button" type="button">查看已采用结果</button>':''}<button id="externalDetail" class="rd-button" type="button">查看核算明细</button>${preview?'<button id="externalApply" class="rd-button rd-primary" type="button">采用</button>':''}</div></footer></section>`);
    $('draftInspector').classList.add('rd-wide','rer-dialog');
    $('externalUpload').onclick=()=>$('externalUploadFiles').click();
    $('externalUploadFiles').onchange=()=>upload([...$('externalUploadFiles').files]);
    $('externalSearch').oninput=()=>{s.query=$('externalSearch').value;s.page=1;drawTable();};
    $('externalProblems')?.addEventListener('click',()=>{s.filter=s.filter==='blocked'?'all':'blocked';s.page=1;$('externalProblems').setAttribute('aria-pressed',String(s.filter==='blocked'));drawTable();});
    $('externalPrevious').onclick=()=>{s.page--;drawTable();};$('externalNext').onclick=()=>{s.page++;drawTable();};
    $('externalReload').onclick=()=>open();$('externalRecords')?.addEventListener('click',()=>open());
    $('externalDetail').onclick=()=>{$('draftInspector').close();w.setView('rows');};
    $('externalApply')?.addEventListener('click',apply);
    document.querySelectorAll('[data-external-preview]').forEach(button=>button.onclick=()=>loadPreview(button.dataset.externalPreview));
    drawTable();controls();
  }
  async function transaction(operation,task){
    const s=session;if(!s||s.operation||locked())return;
    s.operation=operation;s.notice={tone:'running',message:operation==='apply'?'正在采用结果并更新核算…':operation==='resolve'?'正在匹配人员…':'正在识别人员与核定金额…'};
    busy(true);controls();
    try{await task(s);}
    catch(err){if(current(s)){s.notice={tone:'error',message:err.message};status(err.message,true);}}
    finally{if(session===s)s.operation='';busy(false);if(current(s))controls();}
  }
  async function syncState(s){const data=await request(s.base);if(current(s)){adopt(data);s.revision=data.revision;return true;}return false;}
  async function upload(files){
    if(!files.length)return;
    await transaction('upload',async s=>{
      const form=new FormData();form.append('revision',s.revision);files.forEach(file=>form.append('files',file));
      const preview=await request(s.base+'/external-results/import',{method:'POST',body:form});
      if(!current(s))return;
      s.preview=preview;s.revision=preview.revision;s.query='';s.page=1;s.filter='all';
      if(!await syncState(s))return;
      s.notice={tone:preview.blockedCount?'attention':'success',message:preview.blockedCount?`${preview.readyCount} 项可采用，${preview.blockedCount} 项按表内提示处理。`:preview.readyCount?`已识别 ${preview.readyCount} 项，核对后采用。`:'结果与已采用记录一致，无需重复采用。'};
      render();
    });
  }
  async function loadPreview(token){
    await transaction('resolve',async s=>{const preview=await post(s,`/previews/${encodeURIComponent(token)}`,{revision:s.revision,resolutions:[]});if(!current(s))return;s.preview=preview;s.revision=preview.revision;s.page=1;s.query='';s.filter='all';s.notice=null;render();});
  }
  async function resolve(itemId,rowId){
    if(!rowId)return;
    await transaction('resolve',async s=>{const preview=await post(s,`/previews/${encodeURIComponent(s.preview.token)}`,{revision:s.revision,resolutions:[{itemId,rowId}]});if(!current(s))return;s.preview=preview;s.revision=preview.revision;s.notice=null;render();});
  }
  async function apply(){
    await transaction('apply',async s=>{
      const result=await post(s,`/previews/${encodeURIComponent(s.preview.token)}/apply`,{revision:s.revision});
      if(!current(s))return;
      adopt(result.state);s.revision=result.state.revision;s.context=result.externalResults;
      const count=result.appliedCount||0;
      s.preview={...s.preview,revision:s.revision,readyCount:0,canApply:false,appliedCount:(s.preview.appliedCount||0)+count,rows:s.preview.rows.map(row=>row.status==='ready'?{...row,status:'adopted'}:row)};
      s.notice={tone:'success',message:result.message||`已采用 ${count} 项，核算明细与汇总已更新。`};
      status(s.notice.message);render();
    });
  }
  function chooseUpload(){
    if(!ui.data||locked())return;
    if(!uploadInput){
      uploadInput=document.createElement('input');uploadInput.type='file';uploadInput.accept='.xlsx,.xlsm';uploadInput.multiple=true;uploadInput.hidden=true;
      uploadInput.onchange=async()=>{const files=[...uploadInput.files];uploadInput.value='';if(files.length&&await open())await upload(files);};
      document.body.append(uploadInput);
    }
    uploadInput.click();
  }
  async function open(){
    if(!ui.data)return;
    const id=++sequence,s={base:base(),revision:ui.data.revision,context:{records:[],pendingImports:[],summary:{}},preview:null,operation:'',page:1,query:'',filter:'all',notice:null};session=s;
    openDialog('体系外核算结果','<p class="rer-empty" role="status">正在读取核算结果…</p>');
    $('draftInspector').classList.add('rd-wide','rer-dialog');
    try{let data=await request(s.base+'/external-results');if(id!==sequence||!current(s))return;if(data.revision!==ui.data.revision){if(!await syncState(s))return;data=await request(s.base+'/external-results');if(id!==sequence||!current(s))return;}s.context=data;s.revision=data.revision;render();return true;}
    catch(err){if(id===sequence&&current(s)){$('draftInspectorBody').innerHTML=`<p class="rd-error" role="status">${e(err.message)}</p><button id="externalRetry" class="rd-button" type="button">重新读取</button>`;$('externalRetry').onclick=open;}}
  }
  $('draftInspector').addEventListener('cancel',event=>{if(session?.operation&&$('externalPanel'))event.preventDefault();});
  $('draftInspector').addEventListener('close',()=>{if($('draftInspector').classList.contains('rer-dialog')){$('draftInspector').classList.remove('rer-dialog');$('draftCloseInspector').disabled=false;session=null;sequence++;}});
  document.addEventListener('recruitment:busy',()=>{if($('externalPanel')&&$('draftInspector').open)controls();});
  window.RecruitmentExternalResults={open,chooseUpload,tableModel,cardState,fileState,money};
})();
