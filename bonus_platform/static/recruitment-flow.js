(() => {
  'use strict';
  const w=window.RecruitmentWorkbench, x=window.RecruitmentWorkbenchExtension;
  const {$,ui,e,base,request,adopt,busy,status,render,openDialog,amount}=w;
  const label=v=>String(v??'').replace(/候选人及领取人/g,'员工及招聘负责人、协助招聘人、推荐人').replace(/奖金领取人|领取人/g,'招聘负责人、协助招聘人、推荐人').replace(/期初/g,'上月核算表').replace(/试算/g,'核算');
  const fieldName=f=>f==='ABC类别'?'岗位类别（ABC）':label(f);
  const workTitle=c=>c.mode==='settlement'&&/现规则不再形成该分期/.test(c.title)?'核对往期奖金是否已结清':c.mode==='settlement'&&/超过当前规则总额/.test(c.title)?'核对往期奖金标准与差额':label(c.title);
  const deprecatedFields=new Set(['职族','职类','职族分类','海外招聘需求编号']);
  const text=v=>v==null||v===''?'未提供':e(v);
  const fieldText=(field,value)=>text(window.RecruitmentDetailTable.isIdentity(field)?window.RecruitmentDetailTable.maskIdentity(value):value);
  const month=m=>m?`${Math.floor(m/100)}年${m%100}月`:'待确认';
  const nodeMonth=n=>n?(Object.hasOwn(n,'scheduledMonth')?n.scheduledMonth:n.dueMonth):null;
  const post=(path,data={})=>request(base()+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:ui.data.revision,...data})});
  function editPayload(fields,touched,readValue,evidence,selectedPeople,referenceChoices,employmentSelections){
    const raw=[...touched].filter(i=>!referenceChoices[i]).flatMap(i=>(fields[i].bindings||fields[i].targets.map(rowId=>({rowId,field:fields[i].field}))).flatMap(binding=>{
      const proof={evidenceId:evidence[i]||''};
      const edits=[{...binding,value:readValue(i),...proof}];
      if(selectedPeople[i])edits.push({rowId:binding.rowId,field:binding.field.replace(/工号$/,'姓名'),value:selectedPeople[i].name,...proof});
      return edits;
    }));
    return {edits:[...new Map(raw.map(change=>[change.rowId+'|'+change.field,change])).values()],
      referenceSelections:[...new Map(Object.values(referenceChoices).map(choice=>[choice.proposalId,{proposalId:choice.proposalId,signature:choice.signature}])).values()],
      employmentSelections:Object.values(employmentSelections)};
  }
  w.editPayload=editPayload;
  function activePreparation(job){return ['running','cancelling'].includes(job?.status);}
  let pollTimer,pollSequence=0,jobBase='',restoring=false,lastLoaded='',detailSequence=0;
  let materialBase='',materialCategory='',materialSourceIds=new Set();
  let progressSignature='',transitionKey='',progressWasRunning=false,progressCloseTimer;
  document.body.classList.add('recruitment-experience');
  const flowIcon=name=>`<svg class="rd-icon" aria-hidden="true"><use href="#icon-${name}"/></svg>`;
  ui.flowPage=1;ui.flowRange='current';ui.flowAdvanced=false;
  const savedView=new URLSearchParams(location.search).get('view');
  if(['sources','rows','export','todos'].includes(savedView))ui.view=savedView==='export'?'rows':savedView;

  // Keep proven legacy tools usable, but remove them from the everyday surface.
  const tool=$('flowToolContent');
  [document.querySelector('.rt-batchbar'),document.querySelector('.rd-commandbar'),$('draftTableTools'),$('flowLegacyActions')].forEach(el=>{el.hidden=false;tool.append(el);});
  $('draftExport').classList.remove('rd-primary');$('draftExport').textContent='导出完整核算底稿';
  $('draftRefresh').textContent='重新整理已保存资料';
  document.querySelector('.rd-draft-label').innerHTML='<button id="flowVersion" class="rd-text-button" type="button">核算记录</button>';
  $('flowVersion').onclick=()=>window.RecruitmentTrial.choose();
  $('flowPrimary').onclick=()=>window.RecruitmentTrial.newCalculation();
  const openingNotice=document.createElement('div');openingNotice.id='flowOpeningNotice';openingNotice.className='flow-review-notice';openingNotice.hidden=true;$('flowProgress').after(openingNotice);
  $('flowRecalculate').onclick=()=>prepare(false,true);
  $('draftRefresh').onclick=()=>prepare(false,true);
  $('draftSyncDomestic').onclick=()=>prepare(true);
  $('flowSync').onclick=syncMonthly;
  const range=document.createElement('label');range.className='rd-scope';range.id='flowRangeLabel';
  range.innerHTML='<span class="rd-sr-only">人员范围</span><select id="flowRange"><option value="current">本月核算人员</option><option value="review">需要核对的人员</option><option value="all">全部人员</option></select>';
  $('draftScopeLabel').after(range);
  $('flowRange').onchange=()=>{ui.flowRange=$('flowRange').value;ui.flowPage=1;render();};
  const columnNav=document.createElement('div');columnNav.className='flow-column-nav';columnNav.hidden=true;
  columnNav.innerHTML='<label for="flowColumnGroup">字段组</label><select id="flowColumnGroup" aria-label="跳到字段组"></select>';
  $('flowViewCount').after(columnNav);
  const resultTabs=document.createElement('nav');resultTabs.className='flow-result-tabs';resultTabs.setAttribute('aria-label','核算表格');
  resultTabs.innerHTML=[['detail','核算明细'],['recruitment','招聘奖金汇总'],['referral','内推奖金汇总']].map(([key,title])=>`<button type="button" class="rd-text-button" data-result-table="${key}">${title}</button>`).join('');
  $('draftContent').before(resultTabs);
  resultTabs.querySelectorAll('button').forEach(button=>button.onclick=()=>{ui.flowResult=button.dataset.resultTable;ui.flowPage=1;$('draftSearch').value='';$('draftContent').scrollTo(0,0);render();});
  const materialViews=document.createElement('div');materialViews.className='flow-material-view-switch';materialViews.hidden=true;materialViews.setAttribute('role','group');materialViews.setAttribute('aria-label','资料显示方式');
  materialViews.innerHTML=[['list','列表'],['grid','网格']].map(([key,title])=>`<button type="button" data-material-view="${key}" aria-label="${title}显示资料" aria-pressed="${key==='grid'}">${flowIcon(key)}</button>`).join('');
  $('flowUpload').after(materialViews);
  materialViews.querySelectorAll('button').forEach(button=>button.onclick=()=>{ui.materialView=button.dataset.materialView;render();});

  function renderRecipientSummary(m){
    columnNav.hidden=true;$('flowRangeLabel').hidden=true;$('draftContent').onscroll=null;
    const data=m.recipientSummaries?.[ui.flowResult];
    if(!data){$('draftContent').innerHTML=empty('汇总尚未加载','请刷新页面加载最新核算服务。');return;}
    const query=$('draftSearch').value.trim().toLowerCase();
    const rows=data.rows.filter(r=>[r.employeeId,r.name,r.position].join(' ').toLowerCase().includes(query));
    $('flowViewCount').textContent=`${data.rows.length} 条汇总`;
    const visible=page(rows,'条汇总');
    const number=v=>Number(v).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2});
    const tone=c=>c.key==='pending'?'pending':c.key==='confirmed'?'total':c.key==='probation'?'probation':c.key.startsWith('month')?'installment':c.key==='note'?'neutral':'people';
    const cells=(r,total=false)=>data.columns.map(c=>`<td data-tone="${tone(c)}" class="${c.type==='money'?'rd-number':''}">${c.type==='money'?number(r[c.key]||0):e(total?(c.key==='name'?'合计':c.key==='currency'?r.currency:c.key==='note'&&r.unknown?`${r.unknown} 笔金额待确认`:''):(r[c.key]||'—'))}</td>`).join('');
    $('draftContent').innerHTML=visible.length?`<table class="flow-recipient-table"><thead><tr>${data.columns.map(c=>`<th data-tone="${tone(c)}" data-column-key="${e(c.key)}" data-column-type="${c.type||'text'}" scope="col" class="${c.type==='money'?'rd-number':''}">${e(c.label)}</th>`).join('')}</tr></thead><tbody>${visible.map(r=>`<tr>${cells(r)}</tr>`).join('')}</tbody>${!query?`<tfoot>${data.totals.map(r=>`<tr>${cells(r,true)}</tr>`).join('')}</tfoot>`:''}</table>`:empty('没有匹配的汇总记录','可调整搜索条件。');
  }
  $('draftSearch').addEventListener('input',()=>{ui.flowPage=1;render();});
  const tabs=[...document.querySelectorAll('[data-draft-view]:not([hidden])')];
  tabs.forEach((b,i)=>{b.onclick=()=>{ui.flowAdvanced=false;ui.editing=false;w.setView(b.dataset.draftView);};b.onkeydown=ev=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(ev.key))return;ev.preventDefault();const next=ev.key==='Home'?0:ev.key==='End'?tabs.length-1:(i+(ev.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tabs[next].click();tabs[next].focus();};});
  document.querySelectorAll('.flow-more button').forEach(button=>button.addEventListener('click',()=>{document.querySelector('.flow-more').open=false;}));
  $('flowCloseTools').onclick=()=>{$('flowTools').hidden=true;$('draftDropzone').hidden=false;render();};
  function showTools(title='核算工具'){$('flowTools').querySelector('h2').textContent=title;$('flowTools').hidden=false;$('draftDropzone').hidden=true;$('flowCloseTools').focus();}
  $('flowSettings').onclick=()=>showTools();
  $('flowBatch').onclick=()=>{ui.flowAdvanced=true;ui.editing=false;w.setView('rows');};
  $('flowComparison').onclick=()=>window.RecruitmentReviewCenter.open('differences');
  $('flowEvidence').onclick=()=>{if(ui.data?.rows.length)location.href=base()+'/calculation/export';};
  $('flowChanges').onclick=async()=>{
    const url=base();openDialog('修改记录','<p>正在读取…</p>');const loading=$('draftInspectorBody').firstElementChild;
    try{const data=await request(url+'/changes');if(url!==base()||!loading.isConnected||!$('draftInspector').open)return;openDialog('修改记录',`<div class="flow-person"><span>版本 ${data.revision}</span><button id="flowUndo" class="rd-text-button" type="button" ${ui.data.canUndo?'':'disabled'}>撤销上次更正</button><button id="flowRedo" class="rd-text-button" type="button" ${ui.data.canRedo?'':'disabled'}>重做</button></div>${data.entries.map(c=>`<article class="flow-provenance"><strong>${e(c.name)} · ${e(fieldName(c.field))}</strong><p>${fieldText(c.field,c.before)} → ${fieldText(c.field,c.value)}</p><p>${e(c.reason||'')} · ${e(c.at||'')}${c.active===false?' · 已撤销':''}${w.editSourceMarkup(c)}</p></article>`).join('')||'<p>尚无人工更正。</p>'}`);$('flowUndo').onclick=()=>{$('draftUndo').click();$('draftInspector').close();};$('flowRedo').onclick=()=>{$('draftRedo').click();$('draftInspector').close();};}catch(err){if(loading.isConnected&&$('draftInspector').open)$('draftInspectorBody').textContent=err.message;}
  };
  $('draftGridToggle').addEventListener('click',()=>{ui.flowAdvanced=true;render();});
  function empty(title,body){return `<div class="rd-empty"><strong>${e(title)}</strong><p>${e(body)}</p></div>`;}
  function page(items,unit){
    const size=40,pages=Math.max(1,Math.ceil(items.length/size));ui.flowPage=Math.min(Math.max(1,ui.flowPage),pages);
    $('draftCount').textContent=`${items.length} ${unit}${pages>1?` · 第 ${ui.flowPage} / ${pages} 页`:''}`;
    $('draftPrevious').parentElement.hidden=pages===1;
    $('draftPrevious').disabled=ui.flowPage===1;$('draftNext').disabled=ui.flowPage===pages;
    $('draftPrevious').onclick=()=>{ui.flowPage--;render();$('draftContent').scrollTo(0,0);};
    $('draftNext').onclick=()=>{ui.flowPage++;render();$('draftContent').scrollTo(0,0);};
    return items.slice((ui.flowPage-1)*size,ui.flowPage*size);
  }
  function renderResults(m){
    const query=$('draftSearch').value.trim().toLowerCase();
    if(!m.worksheet){$('draftContent').innerHTML=empty('正在加载核算明细','请重新打开页面，加载最新版核算服务。');return;}
    const {columns,rows}=m.worksheet;
    const detail=window.RecruitmentDetailTable;
    columnNav.hidden=false;
    $('flowColumnGroup').innerHTML=detail.groups(columns).map(g=>`<option value="${e(g.key)}">${e(g.label)}</option>`).join('');
    if(ui.flowColumn)$('flowColumnGroup').value=ui.flowColumn;
    $('flowColumnGroup').onchange=()=>{
      ui.flowColumn=$('flowColumnGroup').value;
      const content=$('draftContent'),cell=[...content.querySelectorAll('[data-detail-column]')].find(el=>el.dataset.detailColumn===$('flowColumnGroup').value);
      const fixedWidth=Number(content.querySelector('.flow-ledger')?.dataset.fixedWidth)||330;
      if(cell)content.scrollTo({left:$('flowColumnGroup').selectedIndex===0?0:content.scrollLeft+cell.getBoundingClientRect().left-content.getBoundingClientRect().left-fixedWidth,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
    };
    const all=rows.filter(r=>(ui.flowRange==='all'||ui.flowRange==='review'?ui.flowRange==='all'||r.review:r.current)&&Object.values(r.cells).join(' ').toLowerCase().includes(query));
    const visible=page(all,'人');
    const operatorCount=m.operatorActionCount??m.actionCount,ruleCount=m.ruleActionCount||0;
    const notice=m.actionCount?`<div class="flow-review-notice"><span>${operatorCount?`${operatorCount} 项待办`:''}${operatorCount&&ruleCount?'；':''}${ruleCount?`${ruleCount} 项制度`:''}。</span><button id="flowReview" class="rd-text-button" type="button">去处理</button></div>`:'';
    const table=visible.length?detail.table(columns,visible):empty(ui.data.sources.length?'当前范围没有人员':'先导入本月资料',ui.data.sources.length?'可切换人员范围或调整搜索条件。':'点击「导入资料」，放入上月核算表和本月原始资料。');
    $('draftContent').innerHTML=notice+table;
    $('draftContent').onscroll=()=>{
      const content=$('draftContent'),left=content.getBoundingClientRect().left+(Number(content.querySelector('.flow-ledger')?.dataset.fixedWidth)||330)+1;
      const headers=[...content.querySelectorAll('[data-detail-column]')];
      const current=detail.groups(columns).filter(g=>headers.find(h=>h.dataset.detailColumn===g.key)?.getBoundingClientRect().left<=left).at(-1);
      if(current){ui.flowColumn=current.key;$('flowColumnGroup').value=current.key;}
    };
    $('flowReview')?.addEventListener('click',()=>window.RecruitmentReviewCenter.open('materials'));
    document.querySelectorAll('[data-flow-row]').forEach(b=>b.onclick=()=>inspect(b.dataset.flowRow));
    window.RecruitmentAssignments?.selectable(visible);
  }
  let sourcePreviewSequence=0;
  async function previewSource(source){
    if(!source)return;
    if(source.purpose==='external-results'){window.RecruitmentExternalResults.open();return;}
    if(source.attachment&&source.approvalSummary){window.RecruitmentApprovals.open(source.id);return;}
    const current=base(),id=source.id;
    const materials=window.RecruitmentMaterials,version=materials.syncStatus(source),syncedAt=materials.syncTime(source);
    const toolbar=`<div class="flow-preview-toolbar">${version?`<span class="flow-preview-version"><strong>${e(version)}</strong>${syncedAt?`<time>${e(syncedAt)}</time>`:''}</span>`:''}<a class="rd-button" href="${current}/sources/${e(id)}" download>下载原件</a>${source.attachment?`<button class="rd-button" data-review-source="${e(id)}">审阅与处理记录</button>`:''}<details><summary>更多</summary>${x.sourceCard(source)}</details></div>`;
    const snapshotNote=materials.snapshotNote(source);
    openDialog(source.name,`<section class="flow-source-preview">${toolbar}${snapshotNote?`<p>${e(snapshotNote)}</p><p>历史核验需对照当时留存资料或带生效日期的任职记录，再将复算结果与已确认月度表逐笔比较。</p>`:''}<div id="sourcePreviewContent" role="status">正在读取资料…</div></section>`);x.bindSources();
    const host=$('sourcePreviewContent');
    if(source.attachment){
      try{
        const doc=await request(current+'/documents/'+id);
        if(!host.isConnected||current!==base())return;
        host.innerHTML=`<label class="flow-preview-page">页码 <select id="sourcePreviewPage">${doc.pages.map(p=>`<option value="${p.page}">第 ${p.page} / ${doc.pageCount} 页</option>`).join('')}</select></label><div class="flow-preview-image"><img id="sourcePreviewImage" alt="${e(source.name)}原文" /></div>`;
        const show=()=>$('sourcePreviewImage').src=current+`/documents/${id}/pages/${$('sourcePreviewPage').value}`;
        $('sourcePreviewPage').onchange=show;show();
      }catch(err){if(host.isConnected)host.textContent=err.message;}
      return;
    }
    host.innerHTML='<form class="flow-preview-filters"><label>工作表 <select id="sourcePreviewSheet"></select></label><input id="sourcePreviewQuery" type="search" placeholder="搜索姓名、工号或内容" aria-label="搜索资料内容"/><button class="rd-button" type="submit">搜索</button></form><div id="sourcePreviewTable"></div><div class="flow-preview-pager"><span id="sourcePreviewCount" role="status"></span><button id="sourcePreviewPrev" class="rd-button">上一页</button><button id="sourcePreviewNext" class="rd-button">下一页</button></div>';
    let pageNumber=1;
    async function load(){
      const seq=++sourcePreviewSequence;
      const params=new URLSearchParams({sheet:$('sourcePreviewSheet').value,query:$('sourcePreviewQuery').value,page:pageNumber});
      $('sourcePreviewCount').textContent='正在读取…';$('sourcePreviewPrev').disabled=true;$('sourcePreviewNext').disabled=true;
      try{
        const data=await request(current+`/sources/${id}/preview?${params}`);
        if(!host.isConnected||seq!==sourcePreviewSequence||current!==base())return;
        $('sourcePreviewSheet').innerHTML=data.sheets.map(s=>`<option value="${e(s)}">${e(s)}</option>`).join('');$('sourcePreviewSheet').value=data.sheet;pageNumber=data.page;
        const display=v=>v===null||v===''?'—':typeof v==='object'?JSON.stringify(v):String(v);
        const showCell=(column,value)=>display(window.RecruitmentDetailTable.isIdentity(column)?window.RecruitmentDetailTable.maskIdentity(value):value);
        $('sourcePreviewTable').innerHTML=data.rows.length?`<div class="flow-preview-scroll"><table><thead><tr><th>原表行号</th>${data.columns.map(c=>`<th>${e(c)}</th>`).join('')}</tr></thead><tbody>${data.rows.map(r=>`<tr><td>${e(r.sourceRow??'—')}</td>${data.columns.map(c=>`<td title="${e(showCell(c,r.values[c]))}">${e(showCell(c,r.values[c]))}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`:'<p class="rd-empty">没有匹配的解析记录，可调整搜索条件或下载原件查看。</p>';
        $('sourcePreviewCount').textContent=`${data.total.toLocaleString('zh-CN')} 条 · 第 ${data.page} / ${data.pages} 页`;
        $('sourcePreviewPrev').disabled=data.page<=1;$('sourcePreviewNext').disabled=data.page>=data.pages;
      }catch(err){if(host.isConnected&&seq===sourcePreviewSequence){$('sourcePreviewTable').textContent=err.message;$('sourcePreviewCount').textContent='读取失败，可重新搜索或下载原件';}}
    }
    host.querySelector('form').onsubmit=ev=>{ev.preventDefault();pageNumber=1;load();};
    $('sourcePreviewSheet').onchange=()=>{pageNumber=1;load();};
    $('sourcePreviewPrev').onclick=()=>{pageNumber--;load();};$('sourcePreviewNext').onclick=()=>{pageNumber++;load();};
    load();
  }
  function renderCases(m){
    if(window.RecruitmentReviewCenter)return window.RecruitmentReviewCenter.render(m,()=>renderMaterialCases(m));
    renderMaterialCases(m);
  }
  function renderMaterialCases(m){
    const disclosureScope=base();
    if(ui.flowDisclosureScope!==disclosureScope){ui.flowDisclosureScope=disclosureScope;ui.flowDisclosures={};}
    else document.querySelectorAll('#draftContent [data-flow-disclosure]').forEach(detail=>{ui.flowDisclosures[detail.dataset.flowDisclosure]=detail.open;});
    const focusedDisclosure=document.activeElement?.matches?.('[data-flow-disclosure]>summary')?document.activeElement.parentElement.dataset.flowDisclosure:null;
    const query=$('draftSearch').value.trim().toLowerCase();
    const items=(m.workItems||[]).filter(c=>[workTitle(c),c.title,...c.reasons,...c.rowIds.map(id=>Object.values(ui.data.rows.find(r=>r.id===id)?.values||{}).join(' '))].join(' ').toLowerCase().includes(query));
    page(items,'项');$('draftPrevious').parentElement.hidden=true;
    const current=items.filter(c=>c.current),operator=current.filter(c=>!c.ruleMaintenance),rules=current.filter(c=>c.ruleMaintenance);
    $('draftCount').textContent=`本月 ${operator.length} 项待办${rules.length?` · ${rules.length} 项制度`:''}`;
    const section=(title,list,kind='materials')=>list.length?`<section class="flow-review-section" data-review-section="${kind}"><header><h2>${title}</h2><span>${list.length} 项</span></header>${list.map(c=>{
      const count=c.affectedCount??(c.current?c.currentRowIds.length:c.rowIds.length);
      const countLabel=e(count?`影响 ${count} 人`:c.key==='baseline'?'上月资料':c.sourceIds.length?`${c.sourceIds.length} 份文件`:'待导入');
      const action=c.mode==='externalResults'?'查看体系外结果':c.mode==='settlement'?'核对往期奖金':c.mode==='specialRecords'?'核对奖金调整':c.key==='baseline'?(c.openingCandidates?.length?'确认采用':'补充上月表'):c.mode==='assignments'?'更正招聘分工':c.key==='channel_policy'?'核定渠道归类':c.ruleMaintenance?(c.mode==='policy'?'选择核算口径':'查看缺少的标准'):c.key==='employment'?'核对任职资料':c.key==='field:招聘渠道'?'确认渠道':c.key==='field:推荐人工号'?'选择推荐人':['intake','recipient'].includes(c.mode)?(c.actionClass==='review_available'?'核对采用':'补充资料'):c.mode==='sources'?((c.key==='attachment_review'||c.key.startsWith('approval:'))?'查看审批':'查看资料'):'核对差异';
      const icon=c.ruleMaintenance?'checklist':c.mode==='settlement'?'clock':c.key==='employment'?'people':/日期|天数/.test(c.title)?'calendar':c.mode==='externalResults'||c.mode==='intake'||c.key==='baseline'?'file':c.mode==='recipient'||c.mode==='assignments'||c.key==='field:推荐人工号'?'people':'compare';
      const names=[...new Set([...(c.previews||[]).map(p=>p.name),...(c.current?c.currentRowIds:c.rowIds).map(id=>ui.data.rows.find(r=>r.id===id)?.values.姓名)].filter(Boolean))];
      const impactLabels={scheduled_current:'本月有安排',potential_current_unknown:'本月金额待定',historical:'历史差额',future:'后续跟进'};
      const impacts=(c.monthImpacts||[]).map(v=>impactLabels[v]).filter(Boolean);
      return `<article class="flow-review-item"><span class="flow-review-symbol">${flowIcon(icon)}</span><div class="flow-review-copy"><h3>${e(workTitle(c))}</h3>${names.length?`<p class="flow-review-names" title="${e(names.join('、'))}">${names.slice(0,4).map(e).join('、')}${count>Math.min(names.length,4)?` 等 ${count} 人`:''}</p>`:''}</div><div class="flow-review-meta"><span class="flow-review-count">${countLabel}</span>${impacts.length?`<div class="flow-review-tags">${impacts.map(t=>`<span class="flow-status-tag">${e(t)}</span>`).join('')}</div>`:''}</div><button class="rd-button" type="button" data-flow-work="${e(c.id)}" aria-label="${e(action+'：'+workTitle(c))}">${action}${flowIcon('right')}</button></article>`;
    }).join('')}</section>`:'';
    const future=items.filter(c=>!c.current);
    const classes=[['missing_fact','待补资料'],['review_available','已有材料待核'],['resolve_fact','事实核对'],['review_history','往期奖金核对'],['policy','制度核定']];
    const grouped=classes.map(([key,title])=>section(title,current.filter(c=>(c.actionClass||(c.ruleMaintenance?'policy':'resolve_fact'))===key),key)).join('');
    const automatic=(m.automaticResults||[]);
    $('draftContent').innerHTML=`<div class="flow-review-heading"><button id="flowBackResults" class="rd-text-button" type="button">← 返回核算明细</button><p></p></div>${current.length?grouped:empty('本月没有需要核对的事项','可返回核算明细，或导出表格。')}${automatic.length?`<details class="flow-automatic" data-flow-disclosure="automatic" ${ui.flowDisclosures.automatic?'open':''}><summary>已自动处理</summary><dl>${automatic.map(a=>`<div><dt>${e(a.title)}</dt><dd>${e(a.detail)}</dd></div>`).join('')}</dl></details>`:''}${future.length?`<details class="flow-future" data-flow-disclosure="future" ${ui.flowDisclosures.future?'open':''}><summary>后续跟进 · ${future.length} 项</summary>${section('后续准备',future,'future')}</details>`:''}`;
    document.querySelectorAll('#draftContent [data-flow-disclosure]').forEach(detail=>{detail.ontoggle=()=>{if(detail.isConnected&&ui.flowDisclosureScope===disclosureScope)ui.flowDisclosures[detail.dataset.flowDisclosure]=detail.open;};});
    if(focusedDisclosure)document.querySelector(`[data-flow-disclosure="${focusedDisclosure}"]>summary`)?.focus({preventScroll:true});
    $('flowBackResults').onclick=()=>w.setView('rows');
    document.querySelectorAll('[data-flow-work]').forEach(b=>b.onclick=()=>openWork(items.find(c=>c.id===b.dataset.flowWork)));
  }
  function renderSources(m){
    const c=m.coverage,q=$('draftSearch').value.trim().toLowerCase(),materials=window.RecruitmentMaterials;
    const groups=materials.build(ui.data),preparing=activePreparation(ui.prepareJob),locked=ui.busy||preparing;
    const icon=name=>`<svg class="rd-icon" aria-hidden="true"><use href="#icon-${name}"/></svg>`;
    const matches=source=>[source.name,materials.format(source).description,materials.syncTime(source),...(source.sheets||[]).map(sheet=>sheet.name)].join(' ').toLowerCase().includes(q);
    $('draftCount').textContent=`共 ${ui.data.sources.length} 份资料`;
    $('draftPrevious').parentElement.hidden=true;
    const fileRow=source=>{
      const format=materials.format(source);let tone=source.active===false?'muted':source.error?'error':ui.data.baseline===source.id?'ready':'info';
      let state=source.active===false?'已停用':source.error?'读取失败':source.purpose==='external-results'?window.RecruitmentExternalResults.fileState(ui.data.externalResults,source.id):source.comparisonOnly?'仅供核对':ui.data.baseline===source.id?'已采用':source.attachment?window.RecruitmentMaterials.approvalStatus(ui.data,source):source.kind==='beisen'?'已保存快照':!(source.roles||[]).length||source.roles.every(role=>role==='unknown')?'待识别':'已导入';
      state=materials.syncStatus(source)||state;
      const fileType=['XLS','XLSX','XLSM'].includes(format.badge)?'excel':format.badge==='PDF'?'pdf':format.badge==='API'?'api':['PNG','JPG','JPEG','WEBP'].includes(format.badge)?'image':'file';
      const adoptOpening=!c.hasOpening&&source.active!==false&&!source.error&&!source.comparisonOnly&&source.roles?.includes('ledger');
      if(adoptOpening)state='待采用';
      if(['缺少引用附件','原件需核对','待审阅','待识别','待采用','需处理','资料已失效'].includes(state))tone='missing';
      if(['已应用更正','当前采用','补查已采用','已采用'].includes(state))tone='ready';
      if(/待处理|已部分应用/.test(state))tone='missing';
      if(source.approvalSummary)tone=source.approvalSummary.status==='consistent'?'ready':source.approvalSummary.status==='ready'?'info':'missing';
      const otherMonth=source.forMonth&&source.forMonth!==ui.data.month;
      const syncedAt=materials.syncTime(source);
      const bytes=Number(source.bytes),size=bytes>0?bytes>=1048576?`${(bytes/1048576).toFixed(1)} MB`:`${Math.max(1,Math.round(bytes/1024))} KB`:'';
      const meta=[syncedAt?`采集于 ${syncedAt}`:source.addedAt?String(source.addedAt).slice(0,10):'',source.snapshotVersion?`第 ${source.snapshotVersion} 版`:'',size].filter(Boolean).join(' · ');
      return `<li class="flow-material-file" data-tone="${tone}"><button class="flow-file-open" data-flow-source="${e(source.id)}" type="button" aria-label="查看文件：${e(source.name)}，${e(state)}${syncedAt?'，'+e(syncedAt):''}" title="${e(source.name)}"><span class="flow-file-mark" data-format="${fileType}">${icon(fileType)}</span><span class="flow-file-copy"><strong>${e(source.name)}</strong>${otherMonth?`<span class="flow-file-period">${e(month(source.forMonth))}</span>`:''}${meta?`<span class="flow-file-meta">${e(meta)}</span>`:''}${syncedAt?`<time class="flow-file-time" datetime="${e(source.addedAt)}">${e(syncedAt)}</time>`:''}</span><span class="flow-material-status" data-tone="${tone}">${icon(tone==='ready'?'check':tone==='missing'||tone==='error'?'alert':'file')}${e(state)}</span></button><details class="rd-menu flow-file-menu"><summary aria-label="文件操作：${e(source.name)}" title="文件操作">${icon('more')}</summary><div class="rd-menu-items"><button data-flow-source="${e(source.id)}" type="button">${icon('file')}查看资料</button><a href="${base()}/sources/${e(source.id)}" download>${icon('down')}下载原件</a></div></details>${adoptOpening?`<div class="flow-file-adopt"><button class="rd-text-button" data-flow-opening="${e(source.id)}" type="button" ${locked?'disabled':''}>采用上月表${icon('right')}</button></div>`:''}</li>`;

    };
    const blocks=groups.map(group=>{
      const files=group.files.filter(source=>matches(source)||group.title.toLowerCase().includes(q));
      if(q&&!files.length&&!group.title.toLowerCase().includes(q))return '';
      const history=files.filter(materials.isSyncHistory),current=files.filter(source=>!materials.isSyncHistory(source));
      const rendered=current.map(source=>({source,html:fileRow(source)}));
      const pending=rendered.filter(row=>/^<li[^>]*data-tone="(?:missing|error)"/.test(row.html));
      // Put actionable files on the cover, without hiding other files or history.
      const rest=rendered.filter(row=>!pending.includes(row));
      rest.sort((a,b)=>Number(materials.syncStatus(b.source)==='当前采用')-Number(materials.syncStatus(a.source)==='当前采用'));
      const ordered=[...pending,...rest];
      const coverCount=group.id==='domestic'?1:2;
      const ready=group.id==='opening'&&(c.hasOpening||ui.data.previousAccepted);
      const emptyLabel=ready?group.status:group.tone==='missing'?group.status:group.status==='按需提供'?'暂无资料 · 按需提供':group.id==='overseas'?'暂无资料 · 有海外人员时提供':'暂无资料';
      const rows=ordered.length?`<ul class="flow-material-files">${ordered.slice(0,coverCount).map(row=>row.html).join('')}</ul>${ordered.length>coverCount?`<details class="flow-file-stack" ${q||ui.materialView==='list'?'open':''}><summary>${icon('folder')}查看其余 ${ordered.length-coverCount} 份资料${pending.length>coverCount?`<span class="flow-block-warning">另有 ${pending.length-coverCount} 份待处理</span>`:''}${icon('chevron')}</summary><ul class="flow-material-files">${ordered.slice(coverCount).map(row=>row.html).join('')}</ul></details>`:''}`:`<div class="flow-block-empty" data-tone="${group.tone}">${icon(ready?'check':group.tone==='missing'?'alert':'folder')}<span>${e(emptyLabel)}</span>${group.id==='opening'&&!ready?'<button id="flowEmptyOpening" class="rd-text-button" type="button">没有历史未结奖金</button>':''}</div>`;
      const historyList=history.length?`<details class="flow-sync-history" ${q?'open':''}><summary>查看历史同步记录<span>${history.length} 份</span>${icon('chevron')}</summary><ul class="flow-material-files">${history.map(fileRow).join('')}</ul></details>`:'';
      const intake=group.id==='roster'?ui.data.intakeSummary:null;
      const intakeNotes=Object.entries(intake?.excludedByReason||{}).filter(([,n])=>n).map(([key,n])=>`${n} 人${({oehrMissingOffer:'缺海外 Offer 流程编号',ehrNonZt:'工号不以 zt 开头',otherSource:'不属于 EHR/OEHR 新入职记录'})[key]||'未自动新增'}`);
      const externalAction=group.id==='external'?`<div class="flow-external-actions"><a class="rd-button" href="${base()}/external-results/template" download>下载模板</a><button data-external-upload class="rd-button" type="button" ${locked?'disabled':''}>上传结果</button>${files.length||ui.data.externalResults?.summary?.records||ui.data.externalResults?.pendingImports?.length?'<button data-external-open class="rd-button" type="button">查看结果</button>':''}</div>`:'';
      const approvalAction=group.id==='extra'&&files.some(s=>s.approvalSummary)?'<button id="flowApprovalAdjustments" class="rd-button" type="button">核对审批调整</button>':'';
      return `<section class="flow-material-block" data-category="${group.id}" data-tone="${group.tone}"><header><span class="flow-block-icon">${icon(group.id==='comparison'?'compare':group.icon)}</span><h3>${e(group.title)}</h3><span class="flow-material-status" data-tone="${pending.length?'missing':group.tone}">${pending.length?`${pending.length} 份${group.id==='extra'?'需补充':'待处理'}`:e(group.status)}</span></header>${approvalAction}${group.id==='external'&&!files.length?'':rows}${historyList}${externalAction}${intake?`<details class="flow-material-intake"><summary>人员导入情况</summary><p>${intake.eligibleNewHires} 人符合本月新增条件${intakeNotes.length?'；'+e(intakeNotes.join('；')):''}。</p></details>`:''}</section>`;
    }).filter(Boolean);
    $('draftContent').innerHTML=`<div class="flow-sources flow-materials" data-layout="${ui.materialView||'grid'}"><div id="flowMaterialFiles" class="flow-material-board">${blocks.join('')||empty('没有匹配的资料','试试其他文件名或资料分类。')}</div><div class="flow-step-actions"><button id="flowPerson" class="rd-text-button" type="button" ${locked?'disabled':''}>${icon('person')}手动补充人员</button><button id="flowToResults" class="rd-button rd-primary" type="button" ${locked?'disabled':''}>${ui.data.previousAccepted&&!ui.data.rows.length?'承接上月并开始核算':'查看核算明细'}${icon('right')}</button></div></div>`;
    $('flowUpload').onclick=()=>$('draftUpload').click();
    document.querySelectorAll('[data-external-upload]').forEach(button=>button.onclick=()=>window.RecruitmentExternalResults.chooseUpload());
    document.querySelectorAll('[data-external-open]').forEach(button=>button.onclick=()=>window.RecruitmentExternalResults.open());
    $('flowApprovalAdjustments')?.addEventListener('click',()=>window.RecruitmentApprovals.open());
    $('flowEmptyOpening')?.addEventListener('click',()=>{
        openDialog('确认历史奖金情况', '<p>如果还有往月未发完的奖金，请导入上月核算表。确实没有历史未结奖金时，可以直接从本月开始。</p><p id="flowOpeningError" class="rd-error" role="status"></p><button id="flowOpeningApply" class="rd-button rd-primary" type="button">确认没有历史未结奖金</button>');
        const revision=ui.data.revision;$('flowOpeningApply').onclick=async()=>{$('flowOpeningApply').disabled=true;try{adopt(await post('/opening-empty',{revision,confirmed:true}));$('draftInspector').close();}catch(err){$('flowOpeningError').textContent=err.message;$('flowOpeningApply').disabled=false;}};
    });
    $('flowPerson').onclick=()=>$('draftAddPerson').click();
    $('flowToResults').onclick=()=>{if(!ui.data.activity?.archived&&ui.data.previousAccepted&&!ui.data.rows.length)prepare(false);else w.setView('rows');};
    document.querySelectorAll('[data-flow-source]').forEach(b=>b.onclick=()=>{const menu=b.closest('details.rd-menu');if(menu)menu.open=false;previewSource(ui.data.sources.find(s=>s.id===b.dataset.flowSource));});
    document.querySelectorAll('[data-flow-opening]').forEach(button=>button.onclick=async()=>{const id=button.dataset.flowOpening;await w.mutate({baseline:id});if(ui.data.baseline===id)prepare(false);});
  }
  function refreshControls(){
    const locked=ui.busy||activePreparation(ui.prepareJob)||!!ui.data?.activity?.archived;
    $('draftDropzone').setAttribute('aria-busy',String(locked));
    $('flowPrimary').disabled=locked;
    $('flowRecalculate').disabled=locked||!ui.data?.sources.length;
    ['flowUpload','flowSync','flowPerson','flowToResults','flowDownload','flowConfirmMonth','flowRestartFromOpening','flowProgressRetry'].forEach(id=>{if($(id))$(id).disabled=locked;});
    document.querySelectorAll('[data-flow-opening]').forEach(button=>{button.disabled=locked;});
    lockArchived();
  }
  function refreshExperience(){
    const state=window.RecruitmentExperience.model(ui.data,ui.prepareJob,{busy:ui.busy,message:ui.operationMessage,error:ui.operationError,exportedRevision:ui.exportedBase===base()?ui.exportedRevision:undefined});
    state.steps.forEach(step=>{
      const button=document.querySelector(`.flow-step[data-draft-view="${step.id}"]`);
      if(!button)return;
      button.dataset.state=step.state;button.querySelector('.flow-step-note').textContent=step.note;
      const current=ui.view==='comparison'?'rows':ui.view;
      button.setAttribute('aria-selected',String(current===step.id));button.tabIndex=current===step.id?0:-1;
    });
    let progress=state.progress;
    const wasRunning=progressWasRunning;
    progressWasRunning=progress?.tone==='running';
    if(!progress&&wasRunning)progress={tone:'complete',title:'处理完成',detail:ui.operationMessage||'资料已读取',phases:[],retry:false};
    if(progress&&['complete','attention','neutral'].includes(progress.tone)&&!wasRunning&&!progress.retry)progress=null;
    const signature=JSON.stringify(progress),container=$('flowProgress');
    if(signature!==progressSignature){
      clearTimeout(progressCloseTimer);
      progressSignature=signature;container.hidden=!progress;
      if(progress){
        const running=progress.tone==='running',cancelled=progress.tone==='cancelled',done=['complete','attention'].includes(progress.tone);
        const phases=progress.phases.map((title,i)=>{const state=progress.phaseStates?.[i]||(i<progress.phase?'done':i===progress.phase?'active':'waiting');return `<li data-state="${state}">${state==='done'?flowIcon('check'):state==='error'?flowIcon('alert'):'<span class="flow-phase-dot"></span>'}${e(title)}${state==='error'?' · 未完成':''}</li>`;}).join('');
        const scan='<svg class="flow-scan-icon" viewBox="0 0 32 32" fill="none" aria-hidden="true"><path d="M10 5H7a2 2 0 0 0-2 2v3m17-5h3a2 2 0 0 1 2 2v3M5 22v3a2 2 0 0 0 2 2h3m12 0h3a2 2 0 0 0 2-2v-3"/><path d="M11 10h10M11 15h10M11 20h6"/><path class="flow-scan-line" d="M7 16h18"/></svg>';
        container.innerHTML=`<section class="flow-progress-card" data-tone="${progress.tone}"><span class="flow-progress-symbol">${running?scan:flowIcon(cancelled?'close':done?'check':'alert')}</span><div class="flow-progress-copy"><h2>${e(progress.title)}</h2>${progress.detail&&progress.detail!==progress.title?`<p>${e(label(progress.detail))}</p>`:''}</div>${running&&activePreparation(ui.prepareJob)?`<button id="flowProgressStop" class="rd-button" type="button" ${progress.canCancel?'':'disabled'}>${progress.canCancel?'停止':'正在停止'}</button>`:running?'':`<button id="flowProgressDismiss" class="rd-text-button" type="button" aria-label="关闭进度提示">×</button>`}${running?`<div class="flow-progress-track" role="progressbar" aria-label="${e(progress.title)}" aria-valuetext="${e(progress.phases[progress.phase]||progress.detail||'正在处理')}"><span></span></div>`:''}${phases?`<ol class="flow-progress-phases" aria-label="资料整理进度">${phases}</ol>`:''}${progress.retry?'<button id="flowProgressRetry" class="rd-button" type="button">重新整理资料</button>':''}</section>`;
        $('flowProgressStop')?.addEventListener('click',stopPreparation);
        if(ui.prepareJob?.monthlyAll&&$('flowProgressRetry'))$('flowProgressRetry').textContent='重新同步资料';
        $('flowProgressRetry')?.addEventListener('click',()=>ui.prepareJob?.monthlyAll?syncMonthly():ui.prepareJob?.overseasOnly?syncOverseas():ui.prepareJob?.domesticOnly?syncDomestic():prepare(false));
        $('flowProgressDismiss')?.addEventListener('click',()=>{container.hidden=true;});
        if(done&&!progress.retry)progressCloseTimer=setTimeout(()=>{container.hidden=true;},1000);
      }else container.innerHTML='';
    }
    refreshControls();
  }
  function transitionContent(){
    const key=`${base()}|${ui.view}|${ui.view==='sources'?materialCategory:''}`;
    if(key===transitionKey)return;transitionKey=key;
    if(matchMedia('(prefers-reduced-motion: reduce)').matches)return;
    const target=ui.view==='sources'?$('flowMaterialFiles'):$('draftContent');
    window.RecruitmentInteractions?.enter(target);
  }
  function update(renderContent=true){
    const d=ui.data,m=d?.monthly;if(!m){refreshExperience();if(d){$('flowProgress').hidden=false;$('flowProgress').textContent='后端尚未加载新版核算接口，请重启本地服务后继续。';$('flowPrimary').disabled=true;}return;}
    if(d.activity){
      document.body.classList.add('ra-in-activity');document.body.classList.toggle('ra-archived',d.activity.archived);
      $('draftTitle').textContent=d.activity.name;$('draftTitle').title=d.activity.name;
      $('draftMonth').parentElement.hidden=true;
      if(!$('activityCurrentMonth')){const span=document.createElement('span');span.id='activityCurrentMonth';span.className='ra-activity-month';$('draftMonth').parentElement.after(span);}
      $('activityCurrentMonth').innerHTML=flowIcon('calendar')+`<span>${e(month(d.month))}</span>`;$('activityCurrentMonth').setAttribute('aria-label','核算月份：'+month(d.month));$('flowPrimary').innerHTML=flowIcon('refresh')+'重新核算';
      $('draftCorrectPeriod').hidden=true;
      document.querySelector('.rd-brand>span').textContent='招聘奖金与内推奖金';
    }
    if(['sources','rows','export'].includes(ui.view)){const url=new URL(location.href);if(url.searchParams.get('view')!==ui.view){url.searchParams.set('view',ui.view);history.replaceState(null,'',url);}}
    $('flowVersion').textContent='核算记录';
    $('flowVersion').title=d.trial?.name||'当前月度核算';
    $('draftTodoCount').textContent=m.actionCount||'';
    $('draftScopeLabel').hidden=!ui.flowAdvanced||ui.view!=='rows';
    $('draftTodoScopeLabel').hidden=true;
    $('flowRangeLabel').hidden=ui.view!=='rows'||ui.flowAdvanced;
    columnNav.hidden=ui.view!=='rows'||ui.flowAdvanced;
    $('draftSummary').hidden=true;
    $('draftSummary').innerHTML='';
    const job=ui.prepareJob,c=m.coverage,preparing=activePreparation(job);
    if($('flowSync'))$('flowSync').disabled=ui.busy||preparing||!!d.activity?.archived;
    openingNotice.hidden=!d.parentOutdated;
    if(d.parentOutdated){openingNotice.innerHTML='<span>上月核算结果已更新，本表仍采用旧结果。重新核算会带入最新结果，原记录保留。</span><button id="flowRestartFromOpening" class="rd-text-button" type="button">重新核算</button>';$('flowRestartFromOpening').disabled=ui.busy||preparing;$('flowRestartFromOpening').onclick=()=>window.RecruitmentTrial.newCalculation();}
    refreshExperience();
    $('draftDropzone').dataset.view=ui.view;
    $('flowViewTitle').textContent=({sources:'本月资料',rows:'核算明细',todos:'待办与差异',export:'导出本月表格',comparison:'与线下结果比较'})[ui.view]||'核算明细';
    $('flowViewCount').textContent=ui.view==='sources'?`${d.sources.length} 份文件`:ui.view==='rows'?`${m.worksheet?.rows.filter(row=>row.current).length||0} 人`:'';
    resultTabs.hidden=ui.view!=='rows'||ui.flowAdvanced;
    resultTabs.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.resultTable===(ui.flowResult||'detail'))));
    if(ui.view==='rows'&&!ui.flowAdvanced)$('flowViewTitle').textContent=({recruitment:'招聘奖金汇总',referral:'内推奖金汇总'})[ui.flowResult]||'核算明细';
    $('flowUpload').hidden=ui.view!=='sources';
    $('flowSync').hidden=ui.view!=='sources';
    materialViews.hidden=ui.view!=='sources';
    materialViews.querySelectorAll('button').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.materialView===(ui.materialView||'grid'))));
    $('flowDownload').hidden=ui.view!=='rows';
    $('flowDownload').disabled=ui.busy||preparing||!d.rows.length;
    const primary=$('flowPrimary');primary.disabled=ui.busy||preparing;primary.hidden=true;
    $('flowRecalculate').disabled=ui.busy||preparing||!d.sources.length;
    $('draftSearch').parentElement.hidden=ui.view==='export';
    $('draftSearch').setAttribute('aria-label',ui.view==='sources'?'搜索资料文件或工作表':'搜索姓名、工号或事项');
    if(ui.view==='todos'){$('flowReviewCenter').setAttribute('aria-selected','true');$('flowReviewCenter').tabIndex=0;$('draftContent').setAttribute('aria-labelledby','flowReviewCenter');}
    if(renderContent!==false){
    if(ui.flowAdvanced&&ui.view==='rows'){
      $('draftContext').before($('draftTableTools'));
      $('draftPrevious').onclick=()=>{ui.page--;ui.selected.clear();render();$('draftContent').scrollTo(0,0);};
      $('draftNext').onclick=()=>{ui.page++;ui.selected.clear();render();$('draftContent').scrollTo(0,0);};
      $('draftTableTools').hidden=false;
      $('draftContent').insertAdjacentHTML('afterbegin','<div class="flow-advanced-head"><strong>完整明细与批量修改</strong><button id="flowExitAdvanced" class="rd-text-button" type="button">返回本月核算明细</button></div>');
      $('flowExitAdvanced').onclick=()=>{ui.flowAdvanced=false;ui.editing=false;render();};
    }else if(ui.view==='rows'){tool.append($('draftTableTools'));if(ui.flowResult&&ui.flowResult!=='detail')renderRecipientSummary(m);else renderResults(m);$('draftContext').hidden=true;}
    else if(ui.view==='todos'&&$('draftTodoScope').value!=='history')renderCases(m);
    else if(ui.view==='sources')renderSources(m);

    else if(ui.view==='comparison'){
      $('draftContent').insertAdjacentHTML('afterbegin','<div class="flow-advanced-head"><button id="flowBackReviewCenter" class="rd-text-button" type="button">← 返回待办与差异</button><span>对照资料不参与计算</span><button id="flowCompareUpload" class="rd-text-button" type="button">添加核对结果</button></div>');
      $('flowCompareUpload').onclick=()=>$('trialReferenceFile').click();
      $('flowBackReviewCenter').onclick=()=>window.RecruitmentReviewCenter.open('differences',ui.referenceId);
    }
    transitionContent();
    }
    lockArchived();
    if(lastLoaded!==base()){lastLoaded=base();ui.prepareJob=null;resume();}
  }
  $('flowDownload').onclick=async()=>{
      if(ui.busy||activePreparation(ui.prepareJob))return;
      const revision=ui.data.revision;
      const url=base(),fileMonth=ui.data.month;busy(true);status('正在生成导出表格');
      try{
        const job=await request(url+'/prepare');
        if(activePreparation(job)){ui.prepareJob=job;jobBase=url;watch();update();throw new Error('资料正在整理，完成后即可导出最新核算表。');}
        const response=await fetch(url+'/monthly/export?revision='+revision);
        if(!response.ok){let detail;try{detail=(await response.json()).detail;}catch{}throw new Error(typeof detail==='string'?detail:'核算资料已更新，请刷新核算明细后重试。');}
        const file=URL.createObjectURL(await response.blob()),link=document.createElement('a');
        link.href=file;link.download=`全球招聘奖金核算明细表（非操作类）${fileMonth}.xlsx`;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(file),1000);
        ui.exportedRevision=revision;ui.exportedBase=url;status('已导出本月核算表。');
      }catch(err){if($('flowDownloadStatus'))$('flowDownloadStatus').textContent=err.message;status(err.message,true);}
      finally{busy(false);}
  };
  $('flowConfirmResult').onclick=()=>{
    if(ui.busy||activePreparation(ui.prepareJob)||ui.data.activity?.archived)return;
    const m=ui.data.monthly,revision=ui.data.revision;
    const ready=!m.cases.length&&!m.coverage.syncRequired&&!m.coverage.sourceErrors&&!ui.data.parentOutdated&&ui.data.rows.length;
    if(!ready){
      const blockers=[m.cases.length?`${m.cases.length} 项资料待处理`:'',m.coverage.syncRequired?'人员资料待更新':'',m.coverage.sourceErrors?'导入资料有错误':'',ui.data.parentOutdated?'上月结果已更新':'',!ui.data.rows.length?'尚未导入人员':''].filter(Boolean);
      openDialog('本月还有待处理事项',`<p>${blockers.map(e).join('；')}</p><button id="flowConfirmResolve" class="rd-button rd-primary" type="button">去处理</button>`);
      $('flowConfirmResolve').onclick=()=>{if(!ui.data.rows.length){$('draftInspector').close();w.setView('sources');}else window.RecruitmentReviewCenter.open('materials');};return;
    }
    if(ui.data.isTrial){confirmRecalculation(revision);return;}
    if(ui.data.confirmation?.revision===revision){openDialog('本月结果已确认','<p>新建下月活动时，可承接本月结果。</p>');return;}
    openDialog('确认本月结果',`<p>${month(ui.data.month)} · 本月核算 ${m.currentCount} 人</p>${m.totals.map(t=>`<p class="rw-preview-amount">本月奖金<strong>${e(amount(t.confirmed,t.currency))}</strong></p>`).join('')}<p>确认人员和资料完整后，保存为本月结果。</p><div class="rw-sticky-actions"><button id="flowConfirmMonth" class="rd-button rd-primary" type="button">确认本月结果</button></div><p id="flowConfirmStatus" role="status"></p>`);
    $('flowConfirmMonth').onclick=async()=>{const button=$('flowConfirmMonth'),finish=window.RecruitmentInteractions.pending(button,'正在保存…',button.parentElement);if(!finish)return;try{const result=await post('/confirm-month',{revision,coverageConfirmed:true});ui.data.confirmation=result;update();$('draftInspector').close();status(result.message||'已确认本月结果。');}catch(err){$('flowConfirmStatus').textContent=err.message;}finally{finish();}};
  };
  async function confirmRecalculation(revision){
    const url=base();openDialog('确认本月核算','<p>正在核对新旧记录…</p>');
    try{
      const preview=await request(url+'/adoption-preview?sourceRevision='+revision);
      if(url!==base()||!$('draftInspector').open)return;
      const totals=new Map();
      for(const side of ['target','source'])for(const row of preview[side].totals||[]){if(!totals.has(row.currency))totals.set(row.currency,{});totals.get(row.currency)[side]=row.confirmed;}
      const nextStep=!ui.data.activity&&preview.nextMonth?.exists?`${month(preview.nextMonth.month)}已有记录，确认后需到该月重新核算。`:'';
      openDialog('确认本月核算',`<p>将「${e(preview.source.name)}」保存为${month(preview.month)}结果，原记录保留。</p><table class="flow-installment-table"><thead><tr><th>核对内容</th><th>原月度记录</th><th>这次重新核算</th></tr></thead><tbody><tr><td>台账人数</td><td>${preview.target.people}</td><td>${preview.source.people}</td></tr>${[...totals].map(([currency,value])=>`<tr><td>${e(currency)}</td><td class="rd-number">${e(amount(value.target??0))}</td><td class="rd-number">${e(amount(value.source??0))}</td></tr>`).join('')}</tbody></table>${nextStep?`<p>${e(nextStep)}</p>`:''}<p id="flowAdoptError" class="rd-error" role="status">${e(preview.blockers.join('；'))}</p><button id="flowAdoptApply" class="rd-button rd-primary" type="button" ${preview.canAdopt?'':'disabled'}>采用并确认本月核算</button>`);
      $('flowAdoptApply').onclick=async()=>{
        const button=$('flowAdoptApply'),finish=window.RecruitmentInteractions.pending(button,'正在采用…');if(!finish)return;
        try{const result=await request(url+'/adopt-month',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sourceRevision:preview.sourceRevision,targetRevision:preview.targetRevision,coverageConfirmed:true})});location.href=result.url;}
        catch(err){$('flowAdoptError').textContent=err.message;}finally{finish();}
      };
    }catch(err){$('draftInspectorBody').textContent=err.message;}
  }
  async function resume(){
    if(ui.data?.activity?.archived)return;
    const url=base();try{const job=await request(url+'/prepare');if(url!==base())return;ui.prepareJob=job;if(activePreparation(job)){jobBase=url;watch();}else if(ui.data.previousAccepted&&!ui.data.revision&&!['complete','failed','interrupted','cancelled'].includes(job?.status))prepare(false);else update();}catch(err){status(err.message,true);}
  }
  async function prepare(force=false,localOnly=false){
    if(ui.busy||activePreparation(ui.prepareJob))return;
    const data=ui.data,period=String(data.month).slice(0,4)+'-'+String(data.month).slice(4);
    const hasSnapshot=data.sources.some(s=>s.kind==='overseas_api'&&s.forMonth===data.month&&!s.error);
    const initial=!data.revision||data.parentMonth&&!data.rows.some(r=>String(r.values['入职日期']||r.values['候选人入职时间']||'').startsWith(period));
    const payload={force,localOnly};if(!force&&!localOnly&&initial&&!hasSnapshot)payload.includeOverseas=true;
    busy(true);status('正在准备本月资料');try{ui.prepareJob=await post('/prepare',payload);jobBase=base();watch();}catch(err){status(err.message,true);}finally{busy(false);update();}
  }
  async function syncMonthly(){
    if(ui.busy||activePreparation(ui.prepareJob)||ui.data.activity?.archived)return;
    busy(true);status('正在同步本月国内及海外资料');
    try{ui.prepareJob=await post('/sync-monthly');jobBase=base();watch();}
    catch(err){status(err.message,true);}finally{busy(false);update();}
  }
  async function syncDomestic(){
    if(ui.busy||activePreparation(ui.prepareJob)||ui.data.activity?.archived)return;
    busy(true);status('正在同步本月国内资料');
    try{ui.prepareJob=await post('/sync-domestic-monthly');jobBase=base();watch();}
    catch(err){status(err.message,true);}finally{busy(false);update();}
  }
  async function syncOverseas(){
    if(ui.busy||activePreparation(ui.prepareJob)||ui.data.activity?.archived)return;
    busy(true);status('正在同步本月海外资料');
    try{ui.prepareJob=await post('/sync-overseas');jobBase=base();watch();}
    catch(err){status(err.message,true);}finally{busy(false);update();}
  }
  async function stopPreparation(){
    const job=ui.prepareJob,url=base();
    if(!job?.id||job.status!=='running')return;
    clearTimeout(pollTimer);pollSequence++;
    ui.prepareStopId=job.id;ui.prepareJob={...job,status:'cancelling',message:'正在停止，已保存的资料保留。'};update(false);
    try{const result=await post('/prepare/cancel',{jobId:job.id});if(url!==base())return;ui.prepareJob=result;jobBase=url;watch();}
    catch(err){if(url===base()){ui.prepareStopId='';ui.prepareJob=job;status(err.message,true);jobBase=url;watch();}}
  }
  async function beforeUpload(target=ui.data,url=base()){
    const origin=base(),needsOpening=target.previousAccepted&&!target.revision;
    let job=await request(url+'/prepare');
    if(needsOpening&&!activePreparation(job)){
      const latest=await request(url);
      if(!latest.revision)job=await request(url+'/prepare',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:latest.revision})});
    }
    const waitingJob=activePreparation(job)?job.id:null;
    const started=Date.now();
    while(activePreparation(job)){
      if(base()!==origin)throw new Error('核算月份已切换，请在当前月份重新导入。');
      if(url===origin){ui.prepareJob=job;update(false);}
      if(Date.now()-started>300000){if(url===origin){jobBase=url;watch();}throw new Error('资料仍在整理，文件尚未导入。请在整理完成后再次导入。');}
      await new Promise(resolve=>setTimeout(resolve,800));
      job=await request(url+'/prepare');
    }
    if(waitingJob&&job?.id===waitingJob&&job.status==='cancelled')throw new Error('已停止，文件尚未导入。');
    const latest=await request(url);
    if(base()!==origin)throw new Error('核算月份已切换，请在当前月份重新导入。');
    if(url===origin){ui.prepareJob=job;adopt(latest);}
    if(needsOpening&&!latest.parentMonth)throw new Error('尚未完成上月记录承接，请先重试资料整理，再导入本月文件。');
    return latest;
  }
  async function watch(){
    clearTimeout(pollTimer);const url=jobBase,sequence=++pollSequence;if(url!==base())return;
    try{
      let job=await request(url+'/prepare');if(sequence!==pollSequence||url!==base())return;
      if(ui.prepareStopId===job?.id&&job.status==='running')job={...job,status:'cancelling'};
      ui.prepareJob=job;
      if(activePreparation(job)){update(false);pollTimer=setTimeout(watch,1800);}
      else {ui.prepareStopId='';if(['cancelled','complete'].includes(job?.status)&&job.revision===ui.data.revision){status(job.message||'资料已更新');update(false);return;}const data=await request(url);if(sequence!==pollSequence||url!==base())return;if(data.revision>=ui.data.revision)adopt(data);status(job?.message||'资料已更新',job?.status==='failed');}
    }catch(err){if(sequence!==pollSequence||url!==base())return;status(err.message,true);pollTimer=setTimeout(watch,5000);}
  }
  function lockArchived(){
    if(!ui.data?.activity?.archived)return;
    const ids=['flowPrimary','flowRecalculate','flowUpload','flowSync','flowPerson','flowEmptyOpening','flowConfirmMonth','flowCoverageConfirmed','flowRestartFromOpening','draftUpload','trialNew','trialHistoryNew','trialReference','flowCompareUpload','flowEditPerson','draftEditRecord','flowUndo','flowRedo','flowWorkUpload','flowWorkSync','rwUseBaseline','rwSuggestedPreview','flowOpeningApply'];
    document.querySelectorAll(ids.map(id=>'#'+id).concat(['[data-flow-opening]','[data-baseline]','[data-toggle-source]','[data-plan]','#flowEditForm input','#flowEditForm select','#flowEditForm button','.rd-review-form input','.rd-review-form select','.rd-review-form textarea','.rd-review-form button']).join(',')).forEach(control=>{if(!control.disabled)control.disabled=true;});
  }
  // Inspectors are populated asynchronously; viewing evidence stays available,
  // while their editing controls inherit the same archive state as the page.
  new MutationObserver(lockArchived).observe($('draftInspectorBody'),{childList:true,subtree:true});
  document.addEventListener('recruitment:uploaded',()=>setTimeout(()=>prepare(false),0));
  document.addEventListener('recruitment:assignments-applied',()=>{status('招聘分工已更正，奖金已更新；可在修改记录中撤销。');});
  document.addEventListener('recruitment:render',update);
  document.addEventListener('recruitment:status',refreshExperience);
  document.addEventListener('recruitment:busy',()=>{
    refreshExperience();
  });

  async function openWork(item){
    if(item.mode==='externalResults'||item.key==='external_results'){window.RecruitmentExternalResults.open();return;}
    if(item.mode==='settlement'){window.RecruitmentSpecial.review(item);return;}
    if(item.mode==='specialRecords'){window.RecruitmentSpecial.records();return;}
    if(item.key==='attachment_review'||item.key.startsWith('approval:')){window.RecruitmentApprovals.open(item.sourceIds.length===1?item.sourceIds[0]:'');return;}
    if(item.mode==='assignments'){window.RecruitmentAssignments.open(item.current?item.currentRowIds:item.rowIds);return;}
    if(item.mode==='sources'&&item.key!=='attachment_review'&&item.key!=='baseline'&&!item.key.startsWith('approval:')){w.setView('sources');return;}
    const seq=++detailSequence,url=base();openDialog(label(item.title),'<p role="status">正在读取资料…</p>');
    try{
      const data=await request(url+'/work-items/'+item.id+'?revision='+ui.data.revision);
      if(seq!==detailSequence||url!==base()||!$('draftInspector').open)return;
      if(item.key==='baseline'){openingDialog(data);return;}
      if(item.mode==='sources'){
        const sources=ui.data.sources.filter(s=>item.sourceIds.includes(s.id));
        openDialog(label(item.title),`<p>${e(label(item.detail))}</p>${sources.map(s=>x.sourceCard(s)).join('')}`);x.bindSources();return;
      }
      if(item.mode==='intake'){intakeDialog(item,data);return;}
      if(data.ruleMaintenance&&data.key==='standard'){standardDialog(data);return;}
      reviewDialog(item,data);
    }catch(err){if(seq===detailSequence)$('draftInspectorBody').textContent=err.message;}
  }
  function openingDialog(data){
    const candidates=data.openingCandidates||[];
    if(!candidates.length){w.setView('sources');materialCategory='opening';render();$('draftInspector').close();return;}
    openDialog('确认采用上月核算表',`<section class="flow-opening-choice"><div class="flow-review-lead">${flowIcon('file')}<div><h3>选择要承接的上月结果</h3></div></div><form id="flowOpeningForm">${candidates.map((s,i)=>`<label class="flow-opening-file"><input type="radio" name="opening" value="${e(s.id)}" ${candidates.length===1&&i===0?'checked':''}/><span><strong>${e(s.name)}</strong><a href="${e(base()+'/sources/'+s.id)}" target="_blank" rel="noopener">查看原表</a></span></label>`).join('')}<p id="flowOpeningError" class="rd-error" role="status"></p><div class="rw-sticky-actions"><button id="flowOpeningApply" class="rd-button rd-primary" type="submit">确认采用并更新核算</button></div></form></section>`);
    $('flowOpeningForm').onsubmit=async ev=>{
      ev.preventDefault();const selected=ev.target.querySelector('input:checked');if(!selected){$('flowOpeningError').textContent='请选择要采用的上月核算表。';return;}
      if(ui.busy)return;busy(true);$('flowOpeningApply').disabled=true;
      try{adopt(await post('/changes',{revision:data.revision,baseline:selected.value}));$('draftInspector').close();status('已采用上月核算表，正在更新核算。');setTimeout(()=>prepare(false),0);}
      catch(err){$('flowOpeningError').textContent=err.message;$('flowOpeningApply').disabled=false;}finally{busy(false);}
    };
  }
  function standardDialog(data){
    const people=data.people.filter(p=>p.current),shown=people.length?people:data.people;
    openDialog('补充适用奖金标准',`<section class="flow-standard-gap"><div class="flow-review-lead">${flowIcon('checklist')}<div><h3>缺少适用的奖金标准</h3><p>需由制度维护人员补齐。</p></div></div>${shown.map(p=>`<article class="flow-review-person"><h3>${e(p.name)} <span>${e(p.employeeId)}</span></h3><dl class="flow-standard-facts">${Object.entries(p.values).filter(([k])=>['标签分类','奖金地区类型','ABC类别','职级'].includes(k)).map(([k,v])=>`<div><dt>${e(k)}</dt><dd>${text(v)}</dd></div>`).join('')}</dl><p class="flow-person-cause">${e(p.reasons.map(label).join('；'))}</p></article>`).join('')}<button id="flowRuleMaterials" class="rd-text-button" type="button">查看已导入的依据资料 →</button></section>`);
    $('flowRuleMaterials').onclick=()=>{$('draftInspector').close();w.setView('sources');};
  }
  function originalCycleMarkup(person){
    const cycle=person.originalCycle;
    if(!cycle||cycle.confirmed)return '';
    return `<div class="flow-cycle-choice"><dl class="flow-cycle-values"><div><dt>招聘启动日</dt><dd>${e(cycle.startDate)}</dd></div><div><dt>入职日</dt><dd>${e(cycle.hireDate)}</dd></div><div><dt>剔除天数</dt><dd>${e(cycle.exclusionDays)} 天</dd></div><div><dt>招聘周期</dt><dd>${e(cycle.actualDays)} 天</dd></div></dl><div class="flow-cycle-actions"><button type="button" class="rd-button rd-primary" data-flow-cycle-original="${e(person.id)}">${flowIcon('check')}按原日期核算</button><button type="button" class="rd-button" data-flow-cycle-edit="${e(person.id)}">修改日期</button></div></div>`;
  }
  function policyScopeMarkup(people,version){
    return `<section class="flow-policy-scope"><strong>${e(version)} 制度 · ${people.length} 人</strong><table class="flow-policy-people"><thead><tr><th>人员</th><th>上次离职日</th><th>本次入职日</th><th>离职间隔</th><th>核算范围</th></tr></thead><tbody>${people.map(p=>`<tr><td>${e(p.name)}</td><td>${e(p.previousExitDate||'待补充')}</td><td>${e(p.hireDate)}</td><td>不超过12个月</td><td>${p.current?'本月':'后续'}</td></tr>`).join('')}</tbody></table></section>`;
  }
  function reviewDialog(item,data,includeFuture=false){
    if(item.mode==='policy')includeFuture=true;
    const current=data.people.filter(p=>p.current),future=data.people.filter(p=>!p.current);
    const people=includeFuture||!current.length?data.people:current;
    let fields=includeFuture||!current.length?data.fields:data.currentFields||data.fields;
    if(item.key==='employment'){
      const merged=[];
      for(const person of people){
        const own=fields.filter(f=>f.targets.includes(person.id)),dates=own.filter(f=>['入职日期','候选人入职时间'].includes(f.field));
        if(dates.length===2&&!own.some(f=>f.field==='核算范围')){
          const options=[...new Map(dates.flatMap(f=>f.options||[]).map(o=>[String(o.value),o])).values()];
          merged.push({...dates[0],label:'本次实际入职日期',help:'按原始入职记录确认，同时更新核算表中的两个入职字段。预览会列出每处修改。',mixed:dates[0].value!==dates[1].value,options,bindings:dates.flatMap(f=>f.bindings)});
          merged.push(...own.filter(f=>!dates.includes(f)));
        }else merged.push(...own);
      }
      fields=merged;
    }
    if(item.mode==='policy')fields=fields.map(f=>({...f,person:''}));
    const rehirePolicy=item.mode==='policy'&&item.key.startsWith('rehire:');
    const purpose='';
    if(!fields.length&&!people.some(p=>p.employmentReview?.selection)){
      openDialog(label(item.title),`<section class="flow-standard-gap">${people.map(p=>`<article><h3>${e(p.name)}</h3><p>${e(p.explanation||p.reasons.map(label).join('；'))}</p></article>`).join('')}<button class="rd-button" type="button" data-fact-upload>上传对应资料</button></section>`);return;
    }
    editForm(label(item.title),fields,purpose,data.revision,people.filter(p=>p.employmentReview?.selection).map(p=>({name:p.name,...p.employmentReview.selection})));
    const form=$('flowEditForm');
    if(rehirePolicy)$('flowPreview').textContent='查看核算结果';
    if(current.length&&future.length&&item.mode!=='policy'){
      form.insertAdjacentHTML('beforebegin',`<div class="flow-review-range"><strong>${includeFuture?`全部 ${people.length} 人`:`本月 ${current.length} 人`}</strong><button id="flowReviewFuture" class="rd-text-button" type="button">${includeFuture?'只看影响本月的人员':`后续 ${future.length} 人，展开查看`}</button></div>`);
      $('flowReviewFuture').onclick=()=>{if(form.dataset.dirty==='true'&&!confirm('切换人员范围会放弃尚未保存的修改，是否继续？'))return;reviewDialog(item,data,!includeFuture);};
    }
    if(item.mode==='recipient'){
      const checks=data.checks||[],unqueried=checks.some(c=>c.message==='可通过接口补查');
      form.insertAdjacentHTML('beforebegin',`<div class="flow-work-tools"><button id="flowWorkUpload" class="rd-button" type="button">上传任职资料，匹配整批</button>${unqueried?'<button id="flowWorkSync" class="rd-text-button" type="button">补查尚未查询的国内人员</button>':''}</div>${checks.length?`<details class="flow-query-receipts"><summary>查看已查询结果 · ${checks.length} 人</summary>${checks.map(c=>`<p><strong>${e(c.name)}</strong>：${e(label(c.message))}</p>`).join('')}</details>`:''}<details class="flow-linked-people"><summary>影响 ${people.length} 名员工的奖金</summary><p>${people.map(p=>e(p.name)+' · '+e(p.employeeId)).join('、')}</p></details>`);
      $('flowWorkUpload').onclick=()=>{$('draftInspector').close();$('draftUpload').click();};
      $('flowWorkSync')?.addEventListener('click',()=>{$('draftInspector').close();prepare(false);});
    }else if(item.mode==='policy'){
      form.insertAdjacentHTML('beforebegin',`${policyScopeMarkup(people,item.key.split(':').slice(1).join(':'))}`);
    }else{
      for(const person of people){
        const section=form.querySelector(`[data-flow-person="${CSS.escape(person.id)}"]`);if(!section)continue;
        const review=person.employmentReview;
        const exit=person.resignationReview;
        if(exit){
          const sourceName=ref=>ui.data.sources.find(s=>s.id===ref.sourceId)?.name||'原始资料';
          section.querySelector('header').insertAdjacentHTML('afterend',`<div class="flow-exit-evidence">${exit.currentStatus?`<p>花名册状态：<strong>${e(exit.currentStatus)}</strong><span>${e(sourceName(exit.statusSources[0]))}</span></p>`:''}${exit.records.map(r=>`<p>离职流程：${e(r.status)} · 预计最后工作日 ${e(r.lastDay)}<span>${e(sourceName(r.source))}${r.source.row?` · 第 ${e(r.source.row)} 行`:''}</span></p>`).join('')}</div><p class="flow-person-cause">预计日期尚未作为最终离职日期采用。上传最新流程结果可自动更新；手工更正时只填最终最后工作日。</p>`);
        }else if(review)section.querySelector('header').insertAdjacentHTML('afterend',`${x.employmentMarkup(review,true)}<p class="flow-person-cause">${e(label(review.instruction))}</p>`);
        else {
          const reason=person.explanation||person.reasons.map(label).join('；');
          const dateConflict=/^招聘启动日 \d{4}-\d{2}-\d{2} 晚于入职日 \d{4}-\d{2}-\d{2}[，,]请核对日期[。.]?$/.test(reason.replace(/，\s+/g,'，'));
          section.querySelector('header').insertAdjacentHTML(dateConflict?'beforeend':'afterend',dateConflict?'<span class="flow-status-tag" data-tone="warning">启动日晚于入职日</span>':reason?`<p class="flow-person-cause">${e(reason)}</p>`:'');
          const choice=originalCycleMarkup(person);
          if(choice){section.querySelector('.flow-person-fields').hidden=true;section.querySelector('header').insertAdjacentHTML('afterend',choice);}
        }
      }
    }
    const cycleButtons=[...form.querySelectorAll('[data-flow-cycle-original]')];
    if(cycleButtons.length){
      $('flowPreview').hidden=![...form.querySelectorAll('.flow-person-fields')].some(fields=>!fields.hidden);
      form.querySelectorAll('[data-flow-cycle-edit]').forEach(button=>button.onclick=()=>{
        const section=button.closest('.flow-review-person');section.querySelector('.flow-cycle-choice').hidden=true;section.querySelector('.flow-person-fields').hidden=false;$('flowPreview').hidden=false;
        window.RecruitmentInteractions?.focusControl(section.querySelector('[data-flow-value]'));
      });
      cycleButtons.forEach(button=>button.onclick=async()=>{
        if(ui.busy)return;
        if(form.dataset.dirty==='true'){$('flowEditError').textContent='请先保存已修改的日期。';return;}
        const url=base(),finish=window.RecruitmentInteractions.pending(button,'正在核算…',form);if(!finish)return;busy(true);status('正在按原日期核算');$('flowEditError').textContent='';
        try{
          const result=await post('/cycle-confirmations',{revision:data.revision,rowIds:[button.dataset.flowCycleOriginal]});
          if(url!==base())return;
          adopt(result);render();
          const row=result.rows.find(row=>row.id===button.dataset.flowCycleOriginal),award=row?.calculation.recruitment;
          status(`${row?.values.姓名||'该人员'}已按原日期核算${award?.currentAmount!=null?`，本月招聘奖金 ${amount(award.currentAmount)} ${award.currency}`:''}。`);
          if(form.isConnected&&$('draftInspector').open){const remaining=result.monthly.workItems.find(work=>work.id===item.id);if(remaining)await openWork(remaining);else $('draftInspector').close();}
        }catch(err){if(form.isConnected)$('flowEditError').textContent=err.message;}
        finally{finish();busy(false);}
      });
    }
  }
  function intakeDialog(item,data,includeFuture=false){
    if(data.fields.some(f=>f.options?.some(o=>o.referenceProposal))){reviewDialog(item,data,includeFuture);return;}
    const current=data.people.filter(p=>p.current),future=data.people.filter(p=>!p.current);
    const people=includeFuture?data.people:current.length?current:future;
    const table=list=>`<table class="flow-intake-table"><thead><tr><th>人员／入职日</th><th>具体缺项或差异</th><th></th></tr></thead><tbody>${list.map(p=>`<tr><td><strong>${e(p.name)}</strong><span>${e(p.employeeId)} · ${e(p.hireDate)}</span>${includeFuture&&!p.current?'<span>后续准备，不影响本月</span>':''}</td><td>${p.missingFields.length?`缺少：${e(p.missingFields.map(fieldName).join('、'))}`:''}${p.reviewFields.length?`<span>需核对：${e(p.reviewFields.map(fieldName).join('、'))}</span>`:''}<span>${e(p.offerStatus)}</span></td><td><button class="rd-text-button" type="button" data-flow-intake-person="${e(p.id)}">手工补充</button></td></tr>`).join('')}</tbody></table>`;
    openDialog(label(item.title),`<section class="flow-intake"><h3>${current.length?`本月 ${current.length} 人`:`后续 ${future.length} 人`}</h3><div class="flow-work-tools"><button id="flowWorkUpload" class="rd-button rd-primary" type="button">上传录用资料或补充表</button><a id="flowIntakeTemplate" class="rd-text-button" href="${e(base()+'/work-items/'+item.id+'/supplement.xlsx?revision='+data.revision+'&includeFuture='+includeFuture)}">下载${includeFuture?'全部人员':'当前清单'}补充表</a>${item.key==='intake:国内'?'<button id="flowWorkSync" class="rd-text-button" type="button">接口补查</button>':''}</div>${future.length&&current.length?`<button id="flowIntakeFuture" class="rd-text-button" type="button">${includeFuture?'只看影响本月的 '+current.length+' 人':'另有 '+future.length+' 人仅影响后续月份，展开查看'}</button>`:''}${table(people)}</section>`);
    $('flowWorkUpload').onclick=()=>{$('draftInspector').close();$('draftUpload').click();};
    $('flowWorkSync')?.addEventListener('click',()=>{$('draftInspector').close();prepare(false);});
    $('flowIntakeFuture')?.addEventListener('click',()=>intakeDialog(item,data,!includeFuture));
    document.querySelectorAll('[data-flow-intake-person]').forEach(button=>button.onclick=()=>{
      const person=data.people.find(p=>p.id===button.dataset.flowIntakePerson);
      const fields=data.fields.filter(f=>f.targets.includes(person.id)).map(f=>({...f,person:'',targets:[person.id],bindings:(f.bindings||[]).filter(b=>b.rowId===person.id)}));
      editForm(person.name+' · 补充录用信息',fields,'',data.revision);
      $('flowEditForm').insertAdjacentHTML('beforebegin','<button id="flowIntakeBack" class="rd-text-button" type="button">← 返回缺项清单</button>');
      $('flowIntakeBack').onclick=()=>intakeDialog(item,data,includeFuture);
      if(fields.length>1)$('flowEditForm').classList.add('flow-batch-form');
    });
  }
  async function openCase(c){
    if(!c.rowIds.length){w.setView('sources');return;}
    const seq=++detailSequence,url=base();openDialog(c.title,'<p role="status">正在整理问题与依据…</p>');
    try{
      const tasks=await Promise.all(c.taskIds.map(id=>request(url+'/tasks/'+id)));
      if(seq!==detailSequence||url!==base()||!$('draftInspector').open)return;
      const fields=new Map();
      for(const t of tasks)for(const r of t.rows.filter(r=>c.rowIds.includes(r.rowId)))for(const f of r.fields){
        if(c.id.startsWith('rule:rehire:')&&f.field!=='二次入职执行口径')continue;
        if(c.id.startsWith('recipient:')){
          const values=ui.data.rows.find(x=>x.id===r.rowId)?.values||{};
          if(!['招聘负责人','协助招聘人','推荐人'].some(prefix=>f.field.startsWith(prefix)&&values[prefix+'工号']===c.id.slice(10)))continue;
        }
        const key=c.id.startsWith('recipient:')||c.id.startsWith('rule:')?f.field:r.rowId+'|'+f.field;
        if(!fields.has(key))fields.set(key,{...f,targets:[],person:r.name});
        const value=fields.get(key);if(!value.targets.includes(r.rowId))value.targets.push(r.rowId);
        for(const o of f.options)if(!value.options.some(x=>String(x.value)===String(o.value)))value.options.push(o);
      }
      editForm(c.title,[...fields.values()],c.reasons.join('；'),ui.data.revision);
    }catch(err){if(seq===detailSequence)$('draftInspectorBody').textContent=err.message;}
  }
  function impactMarkup(p){
    const totals=new Map(),changes=new Map(),unresolved=p.unresolvedAmounts||[],remaining=p.remainingIssues||[];
    for(const i of p.currentImpact){
      for(const side of ['before','after']){
        const currency=(side==='before'?i.beforeCurrency:i.currency)||'币种待定';
        if(!totals.has(currency))totals.set(currency,{before:0,after:0,beforeUnknown:0,afterUnknown:0,beforeKnown:0,afterKnown:0});
        const t=totals.get(currency);if(i[side]==null)t[side+'Unknown']++;else{t[side]+=Number(i[side]);t[side+'Known']++;}
      }
    }
    for(const c of p.changes){const key=JSON.stringify([c.field,c.before,c.after]);if(!changes.has(key))changes.set(key,{...c,count:0});changes.get(key).count++;}
    const table=(headers,rows)=>`<div class="flow-impact-table"><table><thead><tr>${headers.map(h=>`<th>${e(h)}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`;
    const summary=(t,side)=>[t[side+'Known']?e(amount(t[side])):'',t[side+'Unknown']?`${t[side+'Unknown']} 笔金额待确定`:''].filter(Boolean).join(' ＋ ');
    const pending=new Map();
    for(const r of [...unresolved,...remaining]){const key=`${r.rowId||r.name}|${r.kind}`,prior=pending.get(key);pending.set(key,{...r,reasons:[...new Set([...(prior?.reasons||[]),...(r.reasons||[])])]});}
    const issues=[...pending.values()];
    return `<h3>本次修改影响 ${p.people} 人</h3>${[...changes.values()].map(c=>`<p>${e(fieldName(c.field))}：${c.before===c.after?`沿用 <strong>${text(c.after)}</strong>，关联所选依据`:`${text(c.before)} → <strong>${text(c.after)}</strong>`} · ${c.count} 人</p>`).join('')}<h3>本月金额影响</h3>${totals.size?[...totals].map(([currency,t])=>`<p>${e(currency)}：${summary(t,'before')} → <strong>${summary(t,'after')}</strong></p>`).join(''):unresolved.length?'<p class="rd-error">金额待确定</p>':'<p>本月金额不变。</p>'}${unresolved.length&&totals.size?`<p class="rd-error">金额待确定 · ${unresolved.length} 项</p>`:''}${issues.length?`<section class="flow-remaining"><h3>仍待处理 · ${issues.length} 项</h3>${issues.map(r=>`<div><strong>${e(r.name)} · ${e(r.kind)}</strong><p>${e([...new Set(r.reasons||[])].map(label).join('；'))}</p></div>`).join('')}</section>`:''}${p.currentImpact.length?table(['人员','项目','修改前','修改后'],p.currentImpact.map(i=>`<tr><td>${e(i.name)}</td><td>${e(i.kind)}</td><td>${e(amount(i.before,i.beforeCurrency))}</td><td>${e(amount(i.after,i.currency))}</td></tr>`)):''}${p.nodeImpact?.length?`<details class="rd-inspector-section"><summary>各期奖金变化 · ${p.nodeImpact.length} 笔</summary>${table(['姓名／发放阶段','原安排','新安排'],p.nodeImpact.map(n=>`<tr><td>${e(n.name)} · ${e(n.label)}</td><td>${n.before?`${e(n.before.recipientName||n.before.recipientId||'未确定')} / ${month(nodeMonth(n.before))}`:'未安排'}</td><td>${n.after?`${e(n.after.recipientName||n.after.recipientId||'未确定')} / ${month(nodeMonth(n.after))}`:'不再安排'}</td></tr>`))}</details>`:''}`;
  }
  function editForm(title,fields,purpose,revision,employmentChoices=[]){
    const sources=ui.data.sources.filter(s=>s.active&&!s.error&&!s.comparisonOnly);
    const referenceDefaults=fields.flatMap((field,index)=>{
      if(field.mixed||field.value!==null&&field.value!==undefined&&field.value!=='')return [];
      const options=(field.options||[]).map((option,choice)=>({option,choice})).filter(({option})=>option.referenceProposal&&option.referenceStatus==='available');
      return options.length===1&&!field.options.some(option=>String(option.value)!==String(options[0].option.value))?[{index,choice:options[0].choice}]:[];
    });
    let preview=null;
    const fieldLabel=f=>fieldName(f.label||f.field),roleFor=f=>['招聘负责人','协助招聘人','推荐人'].find(role=>f.field===role+'工号');
    const fieldMarkup=(f,i)=>{
      const role=roleFor(f),fieldTitle=f.field==='其他渠道'?'其他渠道名称':fieldLabel(f);
      const picker=role?`<div class="flow-person-picker"><label for="flowPersonSearch${i}">${e(role)}</label><div class="rc-person-search">${flowIcon('search')}<input id="flowPersonSearch${i}" type="search" placeholder="姓名或工号" autocomplete="off"/></div><div id="flowPersonChoices${i}" aria-live="polite"></div><p id="flowPersonSelected${i}" class="flow-picker-hint"></p></div>`:'';
      const conflict=f.mixed?f.options?.length?`<button class="flow-status-tag" data-tone="warning" data-flow-state="${i}" data-flow-conflict="${i}" type="button">来源不一致</button>`:`<span class="flow-status-tag" data-tone="warning" data-flow-state="${i}">来源不一致</span>`:'';
      const definition=f.choices?f:ui.data.fieldControls?.[f.field],value=f.mixed?'':f.value??'';
      const choice=window.RecruitmentFactControls.choice(definition,value,`id="flowValue${i}" data-flow-value="${i}"`);
      const content=`${picker}<div class="flow-field-label"><label for="flowValue${i}">${e(role?role+'工号':definition?.label||fieldTitle)}</label>${conflict}</div>${choice??`<input id="flowValue${i}" data-flow-value="${i}" type="${/日期|工作日|入职时间/.test(f.field)?'date':f.field.includes('天数')?'number':'text'}" value="${e(value)}" ${f.mixed?'placeholder="选择来源值或填写"':''}/>`}`;
      return `<section class="flow-field${f.field==='任职说明'?' flow-employment-note':''}">${content}</section>`;
    };
    const groups=new Map();
    fields.forEach((f,i)=>{const key=f.identity||f.targets[0]||'shared';if(!groups.has(key))groups.set(key,{person:f.person,rowId:f.targets[0],fields:[]});groups.get(key).fields.push([f,i]);});
    employmentChoices.forEach(choice=>{if(![...groups.values()].some(group=>group.rowId===choice.rowId))groups.set('employment:'+choice.rowId,{person:choice.name,rowId:choice.rowId,fields:[]});});
    const grouped=[...groups.values()].map(g=>`<section class="flow-review-person" data-flow-person="${e(g.rowId||'')}"><header>${g.person?`<h3>${e(g.person)}</h3>`:''}</header><div class="flow-person-fields">${g.fields.map(([f,i])=>fieldMarkup(f,i)).join('')}</div></section>`).join('');
    const sourceFields=fields.flatMap((f,i)=>f.options?.length&&!f.missingMessage?[`<div class="flow-reference-field"><label for="flowOption${i}">${f.person?e(f.person)+' · ':''}${e(fieldLabel(f))}</label><select id="flowOption${i}" data-flow-option="${i}" aria-label="${f.person?e(f.person)+' · ':''}${e(fieldLabel(f))}的来源值"><option value="">选择来源值</option>${f.options.map((o,j)=>`<option value="${j}">${e(o.label)}${o.referenceProposal?' · 核对表':o.sources?.[0]?.sourceId?' · '+e(o.sources[0].file||sources.find(s=>s.id===o.sources[0].sourceId)?.name||'原始资料'):''}</option>`).join('')}</select><div id="flowSourceRefs${i}" class="flow-reference-links" hidden></div></div>`]:[]).join('');
    const toolbar=sourceFields?`<div class="flow-edit-tools">${referenceDefaults.length>1?`<button id="flowUseReferences" class="rd-button" type="button">带入已有信息 · ${referenceDefaults.length} 项</button>`:''}<button id="flowSourcesToggle" class="rd-text-button" type="button" aria-expanded="false" aria-controls="flowSources">资料来源</button></div><section id="flowSources" class="flow-reference-panel" aria-label="资料来源" hidden>${sourceFields}</section>`:'';
    openDialog(title,`${purpose?`<p class="flow-person-cause">${e(label(purpose))}</p>`:''}<form id="flowEditForm" class="flow-review-form">${toolbar}<div class="flow-edit-people">${grouped}</div><div id="flowImpact" aria-live="polite"></div><div class="flow-edit-footer"><p id="flowEditError" class="rd-error" role="alert" tabindex="-1"></p><div class="rw-sticky-actions"><button id="flowPreview" class="rd-button rd-primary" type="submit">查看修改结果</button><button id="flowBackEdit" class="rd-button" type="button" hidden>返回修改</button><button id="flowApply" class="rd-button rd-primary" type="button" hidden disabled>确认保存</button></div></div></form>`);
    const touched=new Set(),evidence={},selectedPeople={},referenceChoices={},employmentSelections={},form=$('flowEditForm'),formBase=base();
    $('flowSourcesToggle')?.addEventListener('click',()=>{const panel=$('flowSources');panel.hidden=!panel.hidden;$('flowSourcesToggle').setAttribute('aria-expanded',String(!panel.hidden));if(!panel.hidden)window.RecruitmentInteractions?.enter(panel);});
    form.querySelectorAll('[data-flow-conflict]').forEach(button=>button.onclick=()=>{$('flowSources').hidden=false;$('flowSourcesToggle').setAttribute('aria-expanded','true');const select=$('flowOption'+button.dataset.flowConflict),target=select.nextElementSibling?.querySelector('.rc-select-trigger')||select;target.scrollIntoView({block:'nearest'});target.focus();});
    for(const choice of employmentChoices){
      const section=form.querySelector(`[data-flow-person="${CSS.escape(choice.rowId)}"]`);if(!section)continue;
      section.querySelector('header').insertAdjacentHTML('afterend',`<label>本次任职关系<select data-flow-employment="${e(choice.rowId)}"><option value="">请选择需要核对的关系</option>${choice.options.map(o=>`<option value="${e(o.value)}">${e(o.label)}</option>`).join('')}</select></label>${choice.priorExit?`<p class="flow-current">原任职最后工作日 ${e(choice.priorExit.value)} · 选择新聘后带入${choice.priorExit.sources.map(ref=>' '+w.sourceLink(ref.sourceId)).join('')}</p>`:''}`);
      section.querySelector('[data-flow-employment]').onchange=ev=>{if(ev.target.value)employmentSelections[choice.rowId]={rowId:choice.rowId,relation:ev.target.value,signature:choice.signature};else delete employmentSelections[choice.rowId];invalidate();};
    }
    fields.forEach((f,i)=>{
      const choices=f.field==='ABC类别'?['A','B','C']:f.field==='核算范围'?['纳入核算','不纳入核算']:f.field==='招聘渠道'?['招聘网站','内推','校招','猎头','二次入职','其他']:f.field.endsWith('人员状态')?['正式','试用','在职','离职','待入职']:null;
      if(!choices||fields[i].choices||ui.data.fieldControls?.[f.field])return;
      const input=$('flowValue'+i),select=document.createElement('select');select.id=input.id;select.dataset.flowValue=String(i);
      select.innerHTML='<option value="">请选择</option>'+[...new Set([...choices,...(f.value?[String(f.value)]:[])])].map(value=>`<option ${!f.mixed&&value===f.value?'selected':''}>${e(value)}</option>`).join('');input.replaceWith(select);
    });
    function invalidate(){
      form.querySelectorAll('.flow-review-person').forEach(section=>section.hidden=false);preview=null;$('flowEditError').textContent='';form.dataset.preview='false';form.dataset.dirty=String(touched.size>0||Object.keys(employmentSelections).length>0);$('flowApply').disabled=true;$('flowApply').hidden=true;$('flowBackEdit').hidden=true;$('flowPreview').hidden=false;$('flowImpact').innerHTML='';
      fields.forEach((f,i)=>{if(!f.mixed)return;const tag=form.querySelector(`[data-flow-state="${i}"]`);if(!tag)return;const selected=evidence[i]||referenceChoices[i];tag.textContent=selected?'已选来源':touched.has(i)?'已修改':'来源不一致';tag.dataset.tone=touched.has(i)?'':'warning';});
    }
    document.querySelectorAll('[data-flow-value]').forEach(input=>input.oninput=()=>{const i=Number(input.dataset.flowValue);touched.add(i);delete evidence[i];delete selectedPeople[i];delete referenceChoices[i];const select=form.querySelector(`[data-flow-option="${i}"]`);if(select){select.value='';$('flowSourceRefs'+i).hidden=true;}if($('flowPersonSelected'+i))$('flowPersonSelected'+i).textContent='';invalidate();});
    document.querySelectorAll('[data-flow-option]').forEach(select=>select.onchange=()=>{
      const i=Number(select.dataset.flowOption),refs=$('flowSourceRefs'+i);refs.hidden=true;
      delete selectedPeople[i];if($('flowPersonSelected'+i))$('flowPersonSelected'+i).textContent='';
      if(select.value===''){delete evidence[i];delete referenceChoices[i];$('flowValue'+i).value=fields[i].mixed?'':fields[i].value??'';touched.delete(i);invalidate();return;}
      const o=fields[i].options[Number(select.value)];$('flowValue'+i).value=o.value??'';
      if(o.referenceProposal){referenceChoices[i]=o.referenceProposal;delete evidence[i];}else{delete referenceChoices[i];evidence[i]=o.sources?.[0]?.sourceId||'';}
      refs.hidden=!o.sources?.length;refs.innerHTML=(o.sources||[]).map(ref=>`${w.sourceLink(ref.sourceId)} ${e(ref.sheet||'')}${ref.row?' · 第 '+e(ref.row)+' 行':''}${ref.column?' · '+e(ref.column):''}`).join('<br>');
      touched.add(i);invalidate();
    });
    $('flowUseReferences')?.addEventListener('click',()=>{
      if(ui.busy||$('flowPreview').disabled)return;
      referenceDefaults.forEach(({index,choice})=>{if(touched.has(index))return;const select=form.querySelector(`[data-flow-option="${index}"]`);select.value=String(choice);select.onchange();});
    });
    fields.forEach((f,i)=>{
      if(!roleFor(f))return;
      const input=$('flowPersonSearch'+i),choices=$('flowPersonChoices'+i);let timer,sequence=0;
      input.oninput=()=>{
        clearTimeout(timer);const seq=++sequence,q=input.value.trim();choices.innerHTML='';if(!q)return;
        timer=setTimeout(async()=>{
          try{
            const reply=await request(formBase+'/people?revision='+revision+'&q='+encodeURIComponent(q));
            if(seq!==sequence||!form.isConnected||base()!==formBase)return;
            choices.innerHTML=reply.people.length?`<ul class="flow-picker-options">${reply.people.map((p,j)=>`<li><button type="button" data-person-choice="${j}"><strong>${e(p.name)}</strong><span>${e(p.employeeId)}</span></button></li>`).join('')}</ul>`:'<p class="flow-picker-hint">未找到，可直接填写工号。</p>';
            choices.querySelectorAll('[data-person-choice]').forEach(button=>button.onclick=()=>{const person=reply.people[Number(button.dataset.personChoice)];selectedPeople[i]=person;delete evidence[i];delete referenceChoices[i];$('flowValue'+i).value=person.employeeId;touched.add(i);choices.innerHTML='';input.value=person.name;$('flowPersonSelected'+i).textContent=`已选择 ${person.name} · ${person.employeeId}`;invalidate();});
          }catch(err){if(seq===sequence&&form.isConnected)choices.textContent=err.message;}
        },280);
      };
    });
    function showEditError(message){const error=$('flowEditError');error.textContent=message;error.focus({preventScroll:true});error.scrollIntoView({block:'nearest'});}
    $('flowBackEdit').onclick=()=>{invalidate();window.RecruitmentInteractions?.focusControl(form.querySelector('[data-flow-value], [data-flow-employment]'));};
    $('flowEditForm').onsubmit=async ev=>{
      ev.preventDefault();if($('flowPreview').disabled||ui.busy)return;$('flowEditError').textContent='';
      const form=ev.target;
      const payload=editPayload(fields,touched,i=>$('flowValue'+i).value,evidence,selectedPeople,referenceChoices,employmentSelections);
      if(!payload.edits.length&&!payload.referenceSelections.length&&!payload.employmentSelections.length){showEditError('请先修改字段或选择采用值。');return;}
      const finish=window.RecruitmentInteractions.pending($('flowPreview'),'正在核算…',form);if(!finish)return;
      try{preview=await post('/previews',{revision,...payload});finish();if(!form.isConnected||!$('draftInspector').open||base()!==formBase)return;form.querySelectorAll('.flow-review-person').forEach(section=>section.hidden=true);form.dataset.preview='true';$('flowImpact').innerHTML=impactMarkup(preview);$('flowApply').disabled=false;$('flowApply').hidden=false;$('flowBackEdit').hidden=false;$('flowPreview').hidden=true;$('flowImpact').scrollIntoView({block:'start'});window.RecruitmentInteractions?.enter($('flowImpact'));$('flowBackEdit').focus({preventScroll:true});}
      catch(err){if(form.isConnected&&$('draftInspector').open)showEditError(err.message);}finally{finish();}
    };
    $('flowApply').onclick=async()=>{
      if(!preview||ui.busy||base()!==formBase)return;
      const finish=window.RecruitmentInteractions.pending($('flowApply'),'正在保存…',form);if(!finish)return;busy(true);status('正在保存核算结果');
      const scroll=$('draftContent').scrollTop,flowPage=ui.flowPage;
      try{const saved=await post(`/previews/${preview.id}/apply`,{revision:preview.revision});if(base()!==formBase)return;const close=form.isConnected;adopt(saved);ui.flowPage=flowPage;render();$('draftContent').scrollTop=scroll;if(close)$('draftInspector').close();status('已保存，奖金已更新。');}
      catch(err){if(form.isConnected&&$('draftInspector').open)showEditError(err.message);status(err.message,true);}finally{finish();busy(false);}
    };
  }
  async function inspect(id){
    const seq=++detailSequence,url=base();openDialog('奖金与依据','<p role="status">正在读取…</p>');
    try{const {row,revision}=await request(url+'/rows/'+id);if(seq!==detailSequence||url!==base()||!$('draftInspector').open)return;
      const v=row.values;
      openDialog(v.姓名||'核算明细',`<div class="flow-person"><span>${e(v.工号||'')}</span><span>入职 ${e(v.入职日期||'待核对')}</span><button id="flowEditPerson" class="rd-text-button" type="button">修改资料</button></div><div class="flow-detail-tabs" role="tablist">${[['awards','奖金明细'],['facts','员工资料'],['sources','原始资料与修改记录']].map(([id,title],i)=>`<button role="tab" id="flowDetailTab-${id}" aria-controls="flowDetail" aria-selected="${i===0}" tabindex="${i===0?0:-1}" data-flow-detail="${id}" type="button">${title}</button>`).join('')}</div><section id="flowDetail" role="tabpanel"></section>`);
      function show(tab){
        document.querySelectorAll('[data-flow-detail]').forEach(b=>{const selected=b.dataset.flowDetail===tab;b.setAttribute('aria-selected',String(selected));b.tabIndex=selected?0:-1;});$('flowDetail').setAttribute('aria-labelledby','flowDetailTab-'+tab);
        if(tab==='awards')$('flowDetail').innerHTML=['recruitment','referral'].map(k=>{const a=row.calculation[k];return `<section class="flow-award"><h3>${k==='recruitment'?'招聘奖金':'内推奖金'}</h3><div class="flow-award-summary"><span>奖金总额 <strong>${e(a.total==null?'待补充':amount(a.total))}</strong></span><span>币种 ${e(a.currency)}</span></div><p>${e(row.rule.label||'')}${a.cycle?` · ${a.cycle.exempt?'已按确认依据免除周期':`招聘周期 ${e(a.cycle.actualDays??'待核对')} 天`} · 周期系数 ${a.cycle.factor==null?'待核对':`${Math.round(a.cycle.factor*100)}%`}`:''}</p>${a.issues.length?`<p class="rd-error">${e(label(a.issues.join('；')))}</p>`:''}${a.cycle?.warning?`<p class="rd-message">${e(a.cycle.warning)}</p>`:''}${a.nodes.length?`<table class="flow-installment-table"><thead><tr><th>发放时间</th><th>姓名</th><th>金额</th><th>币种</th><th>发放月份</th></tr></thead><tbody>${a.nodes.map(n=>`<tr><td>${e(n.label)}</td><td>${e(n.recipientName||n.recipientId||'待补充')}<span>${e(n.role)}</span></td><td class="rd-number">${e(amount(n.amount))}</td><td>${e(n.currency)}</td><td>${month(nodeMonth(n))}${n.issues.length?'<span class="flow-warn">待核对</span>':''}${['按规则不发','暂缓安排'].includes(n.status)?`<span>${e(n.status)}</span>`:''}</td></tr>`).join('')}</tbody></table>`:`<p>${e(label((a.reasons||[]).join('；')))||'暂无分期金额。'}</p>`}</section>`;}).join('');
        else if(tab==='facts')$('flowDetail').innerHTML=`<dl class="flow-facts">${Object.entries(v).filter(([f,val])=>!f.startsWith('_')&&!deprecatedFields.has(f)&&val!==''&&val!=null).map(([f,val])=>`<dt>${e(fieldName(f))}</dt><dd>${fieldText(f,val)}</dd>`).join('')}</dl>`;
        else $('flowDetail').innerHTML=`<h3>采用的原始资料</h3>${[...new Set(row.sources.map(s=>s.sourceId))].map(s=>`<p>${w.sourceLink(s)}</p>`).join('')}<h3>字段依据</h3>${Object.entries(row.provenance).map(([f,refs])=>`<article class="flow-provenance"><strong>${e(fieldName(f))}</strong>${refs.map(r=>`<p>${fieldText(f,r.value)} <span>${w.sourceLink(r.sourceId)} · ${e(r.sheet||'')} 第 ${e(r.row||'—')} 行</span></p>`).join('')}</article>`).join('')}<h3>人工修改</h3>${row.edits.map(edit=>`<p>${e(fieldName(edit.field))}：${fieldText(edit.field,edit.before)} → ${fieldText(edit.field,edit.value)}<br>${e(edit.reason||'手工修改')} · ${e((edit.at||'').replace('T',' '))}${w.editSourceMarkup(edit)}</p>`).join('')||'<p>没有人工修改。</p>'}`;
        const basis=row.calculation.recruitment.rehireBasis;
        if(tab==='awards'&&basis)$('flowDetail').querySelector('.flow-award p').insertAdjacentHTML('afterend',`<p>${e(basis.description)}<br>依据：${e(basis.source)}</p>`);
      }
      const detailTabs=[...document.querySelectorAll('[data-flow-detail]')];detailTabs.forEach((b,i)=>{b.onclick=()=>show(b.dataset.flowDetail);b.onkeydown=ev=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(ev.key))return;ev.preventDefault();const next=ev.key==='Home'?0:ev.key==='End'?2:(i+(ev.key==='ArrowRight'?1:2))%3;detailTabs[next].click();detailTabs[next].focus();};});show('awards');
      $('flowEditPerson').textContent='调整数据';$('flowEditPerson').className='rd-button rd-primary';
      $('flowEditPerson').disabled=!!ui.data.activity?.archived||ui.busy||activePreparation(ui.prepareJob);
      $('flowEditPerson').onclick=()=>window.RecruitmentActions.open(id);
    }catch(err){if(seq===detailSequence)$('draftInspectorBody').textContent=err.message;}
  }
  function editPerson(row,revision){
    w.editor([row.id],row,revision);
  }
  w.inspector=inspect;
  window.RecruitmentFlow={beforeUpload,openWork,editPerson,handles:view=>!!ui.data?.monthly&&(view==='sources'||view==='export'||view==='rows'&&!ui.flowAdvanced&&!ui.editing||view==='todos'&&$('draftTodoScope').value!=='history')};
  $('draftInspector').addEventListener('close',()=>{
    detailSequence++;
    const opener=ui.dialogOpener;
    const target=opener?.isConnected&&opener.getClientRects().length?opener:document.querySelector('[data-flow-case]')||document.querySelector('[data-draft-view][aria-selected="true"]');
    target?.focus();
  });
  if(ui.data)update();else refreshExperience();
})();
