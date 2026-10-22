(() => {
  'use strict';
  const w=window.RecruitmentWorkbench,{$,ui,e,base,request,openDialog}=w;
  let tab='materials',sourceId='',scope='',cache=null,cacheKey='',pending='',error='',errorKey='',filter='pending',page=1;
  const locked=()=>ui.busy||['running','cancelling'].includes(ui.prepareJob?.status)||ui.data?.activity?.archived;
  const key=()=>`${base()}|${ui.data.revision}|${sourceId}`;
  const options=(items,selected)=>items.map(([v,t])=>`<option value="${e(v)}" ${v===selected?'selected':''}>${e(t)}</option>`).join('');
  const period=value=>String(value||'').replace(/\b(20\d{2})(0[1-9]|1[0-2])\b/g,(_,year,month)=>`${year}年${Number(month)}月`);
  const empty=message=>`<p class="rd-empty">${e(message)}</p>`;
  function open(next='materials',source=''){
    if(scope!==base()){scope=base();cache=null;cacheKey='';error='';}
    tab=next;page=1;filter='pending';sourceId=source;
    $('draftSearch').value='';$('draftTodoScope').value='current';ui.flowAdvanced=false;ui.editing=false;
    $('draftInspector').close();w.setView('todos');
  }
  async function load(){
    const current=key(),url=base(),revision=ui.data.revision;
    if(pending===current||cacheKey===current)return;
    pending=current;error='';errorKey='';
    try{
      const data=await request(url+`/review-center?${new URLSearchParams({revision,sourceId})}`);
      if(current!==key())return;
      cache=data;cacheKey=current;
    }catch(err){if(current===key()){error=err.message;errorKey=current;}}
    finally{if(pending===current)pending='';if(current===key()&&ui.view==='todos')w.render();}
  }
  function render(m,renderMaterials){
    if(scope!==base()){scope=base();cache=null;cacheKey='';sourceId='';error='';page=1;}
    if(sourceId&&!ui.data.sources.some(s=>s.id===sourceId&&s.active&&!s.error))sourceId='';
    if(error&&errorKey!==key())error='';
    const fresh=cacheKey===key(),data=fresh?cache:null;
    // An error remains visible until an explicit retry; avoid request loops.
    if(!fresh&&!error)load();
    if(tab==='materials')renderMaterials();else $('draftContent').innerHTML='';
    const counts=data?.summary;
    const bar=`<section class="rc-toolbar"><div class="rc-tabs" role="group" aria-label="核对事项类型">${[['materials',`核对事项 · ${counts?.materialGroups??m.workItems.filter(t=>t.current).length} 项`],['differences',`线下差异${data?.comparisonReady===false?` · 尚未比较${counts?.rosterDifferenceItems?' / '+counts.rosterDifferenceItems+' 项范围待跟进':''}`:counts?` · ${counts.differenceItems} 笔奖金节点 / ${counts.rosterDifferenceItems||0} 项人员范围`:''}`],['records',`处理记录${counts?` · ${counts.records} 条`:''}`]].map(([k,t])=>`<button type="button" class="rd-button" data-rc-tab="${k}" aria-pressed="${tab===k}">${t}</button>`).join('')}</div><button id="rcRefresh" class="rd-text-button" type="button">刷新进度</button></section>`;
    $('draftContent').insertAdjacentHTML('afterbegin',bar);
    document.querySelectorAll('[data-rc-tab]').forEach(b=>b.onclick=()=>{if(tab===b.dataset.rcTab)return;tab=b.dataset.rcTab;page=1;w.render();$('draftContent').scrollTop=0;document.querySelector(`[data-rc-tab="${tab}"]`)?.focus({preventScroll:true});window.RecruitmentInteractions?.enter($('draftContent'));});
    $('rcRefresh').disabled=!!ui.busy;
    $('rcRefresh').onclick=async()=>{const url=base();if(ui.busy)return;w.busy(true);try{const current=await request(url);if(url===base()){cacheKey='';error='';w.adopt(current);}}catch(err){w.status(err.message,true);}finally{w.busy(false);}};
    if(tab==='materials'){
      $('draftContent').querySelector('.flow-review-heading p')?.remove();
      if(error)$('draftContent').insertAdjacentHTML('beforeend',`<p class="rd-error" role="status">${e(error)}</p>`);
      return;
    }
    $('draftPrevious').parentElement.hidden=true;$('draftCount').textContent='';
    if(!data){$('draftContent').insertAdjacentHTML('beforeend',`<p class="rd-message" role="status">${e(error||'正在读取核对进度…')}</p>`);return;}
    if(tab==='differences')renderDifferences(data);else renderRecords(data);
  }
  function renderDifferences(data){
    const q=$('draftSearch').value.trim().toLowerCase();
    let rows=data.differences.filter(d=>(filter==='all'||filter==='retained'?filter==='all'||d.status==='已确认保留差异':filter==='recheck'?d.status==='需重新核对':d.status!=='已确认保留差异')&&[d.name,d.employeeId,d.item,d.kind,d.reason,d.review?.reason].join(' ').toLowerCase().includes(q));
    const pages=Math.max(1,Math.ceil(rows.length/40));page=Math.min(page,pages);const visible=rows.slice((page-1)*40,page*40);
    $('draftCount').textContent=`${rows.filter(d=>!d.subject).length} 笔奖金节点 · ${rows.filter(d=>d.subject).length} 项人员范围 · 第 ${page} / ${pages} 页`;
    const s=data.summary;
    $('draftContent').insertAdjacentHTML('beforeend',`<section class="rc-differences"><div class="rc-filters"><label>核对台账<select id="rcSource">${options([['','本月线下核对表'],...data.sources.map(x=>[x.id,x.name])],data.sourceId)}</select></label><label>处理进度<select id="rcFilter" ${data.comparisonReady===false&&!data.differences.length?'disabled':''}>${options([['pending','待处理'],['all','全部差异'],['retained','已确认保留'],['recheck','需重新核对']],filter)}</select></label><button id="rcUpload" class="rd-button" type="button">添加核对结果</button><button id="rcFullCompare" class="rd-text-button" type="button" ${data.sourceId?'':'disabled'}>全历史与字段核对</button></div>${data.comparisonReady===false&&!data.differences.length?'':summaryMarkup(s)}${data.comparisonReady===false?'':`<details class="rc-basis"><summary>核对范围</summary><p>${e(data.basis)}</p></details>`}${visible.length?`<table class="rc-table"><thead><tr><th>人员／项目</th><th>线下安排</th><th>当前核算</th><th>原因与关联处理</th><th>核对进度</th></tr></thead><tbody>${visible.map(d=>`<tr><td><strong>${e(d.name||'未匹配人员')}</strong><span>${e(d.employeeId||'')} · ${e(d.hireDate||'')}</span><span>${e(d.kind)} · ${e(d.item)}</span>${d.sourceRow?`<span>${e(d.sheet||'')} · 第 ${e(d.sourceRow)} 行</span>`:''}</td><td>${d.subject?e(d.side==='reference'?'线下有此任职':'线下未列此任职'):e(w.amount(d.reference,d.currency))}<span>${d.subject?e(d.monthImpacts.includes('scheduled_current')?'本月范围待核':'后续月份跟进'):e(period(d.referencePeriod||'本月未安排'))}</span></td><td>${d.subject?e(d.rowId?'平台有此任职':'尚未唯一匹配'):e(w.amount(d.calculated,d.calculatedCurrency))}<span>${d.subject?e(d.originMonth?'承接 '+period(d.originMonth)+' 未完成事项':'先核对身份及范围'):e(period(d.calculatedPeriod||'尚未安排'))}</span></td><td>${d.subject||!Object.values(d.dimensions||{}).some(v=>v.status!=='equal')?`<strong>${e(d.category)}</strong>`:''}${dimensionMarkup(d)}${conciseReason(d.reason)?`<p class="rc-reason" title="${e(conciseReason(d.reason))}">${e(conciseReason(d.reason))}</p>`:''}</td><td><strong class="rc-status" data-status="${e(d.status)}">${e(d.status)}</strong><button class="rd-button" data-rc-handle="${e(d.id)}">处理</button></td></tr>`).join('')}</tbody></table>`:empty(data.comparisonReady===false?data.basis:'当前筛选没有差异。可切换进度或核对台账。')}<div class="rc-pager" ${data.comparisonReady===false&&!data.differences.length?'hidden':''}><button id="rcPrev" class="rd-button" ${page===1?'disabled':''}>上一页</button><span>第 ${page} / ${pages} 页</span><button id="rcNext" class="rd-button" ${page===pages?'disabled':''}>下一页</button></div>${data.history.length?`<details class="rc-history"><summary>差异核对历史 · ${data.history.length} 条</summary>${data.history.map(r=>`<article><strong>${e(r.name)} · ${e(r.item)}</strong><p>${e(r.recordStatus)} · ${e(r.at)}</p><p>${e(r.reason)}</p></article>`).join('')}</details>`:''}</section>`);
    $('rcSource').onchange=()=>{sourceId=$('rcSource').value;cacheKey='';error='';page=1;w.render();};
    $('rcFilter').onchange=()=>{filter=$('rcFilter').value;page=1;w.render();};
    $('rcUpload').disabled=locked();$('rcUpload').onclick=()=>$('trialReferenceFile').click();
    $('rcFullCompare').onclick=()=>{ui.referenceId=data.sourceId;w.setView('comparison');};
    $('rcPrev').onclick=()=>{page--;w.render();$('draftContent').scrollTop=0;$('draftSearch').focus({preventScroll:true});};$('rcNext').onclick=()=>{page++;w.render();$('draftContent').scrollTop=0;$('draftSearch').focus({preventScroll:true});};
    document.querySelectorAll('[data-rc-handle]').forEach(b=>b.onclick=()=>handle(data,data.differences.find(d=>d.id===b.dataset.rcHandle)));
  }
  function summaryMarkup(s){
    const tags=[
      [`待处理 ${s.pendingMonetaryDifferences||0} 笔 · 范围 ${s.pendingRosterDifferences||0} 项`,true],
      [`已保留 ${s.retainedMonetaryDifferences||0} 笔 · 范围 ${s.retainedRosterDifferences||0} 项`,s.retainedMonetaryDifferences||s.retainedRosterDifferences],
      [`需重核 ${s.recheckDifferences} 项`,s.recheckDifferences],
      [`四项一致 ${s.equalNodes||0} / ${s.referenceNodes||0} 节点`,true,'金额、月份、币种、领取人均一致；仅统计线下本月非零奖金节点'],
      [`角色／资格待核 ${s.qualificationDifferenceNodes} 节点`,s.qualificationDifferenceNodes],
      [`四项一致、资格待核 ${s.additionalQualificationNodes} 节点`,s.additionalQualificationNodes],
      [`线下未匹配 ${s.unmatchedPeople} 人`,s.unmatchedPeople],
      [`平台独有 ${s.draftOnlyPeople} 人`,s.draftOnlyPeople],
      [`匹配不唯一 ${s.ambiguousPeople} 项`,s.ambiguousPeople],
    ];
    return `<div class="rc-summary" aria-label="核对汇总">${tags.filter(([,show])=>show).map(([text,,title])=>`<span class="rc-stat"${title?` title="${e(title)}"`:''}>${e(text)}</span>`).join('')}</div>`;
  }
  function dimensionMarkup(d){
    const labels={amount:'金额',period:'月份',currency:'币种',recipient:'领取人',role:'角色分配',eligibility:'资格'};
    const status={equal:'一致',different:'不同',unknown:'待核',blocked:'受阻'};
    const seen=new Set(conciseReason(d.reason).split('；')),entries=Object.entries(d.dimensions||{}).filter(([,v])=>v.status!=='equal');
    return entries.length?`<div class="rc-dimensions">${entries.map(([k,v])=>{
      const reason=conciseReason(v.reason).split('；').filter(part=>part&&!seen.has(part)).map(part=>{seen.add(part);return part;}).join('；');
      return `<div><span class="rc-dimension" data-status="${e(v.status)}">${e(labels[k]||k)} ${e(status[v.status]||v.status)}</span>${reason?`<p>${e(reason)}</p>`:''}</div>`;
    }).join('')}</div>`:'';
  }
  function conciseReason(value){
    const explanations=new Set(['金额及安排一致不代表资格或实际支付已经核实','合计一致不能替代逐角色核对']);
    return String(value||'').split('；').filter(part=>part&&!explanations.has(part)).join('；');
  }
  function handle(data,d){
    $('draftInspector').classList.remove('rd-wide');
    const schedule=d.dimensions?.period?.status==='different'&&d.dimensions?.amount?.status==='equal';
    openDialog((d.name||'')+' · 处理差异',`<section class="rx-actions"><div><strong>${e(d.kind)} · ${e(d.item)}</strong>${d.subject?`<p>${e(d.category)}</p>`:`<div class="rc-amount-compare"><div><span>线下安排</span><strong>${e(w.amount(d.reference,d.currency))}</strong><span>${e(period(d.referencePeriod||'未安排月份'))}</span></div><div><span>当前核算</span><strong>${e(w.amount(d.calculated,d.calculatedCurrency))}</strong><span>${e(period(d.calculatedPeriod||'未安排月份'))}</span></div></div>`}${conciseReason(d.reason)?`<p class="rc-reason">${e(conciseReason(d.reason))}</p>`:''}${dimensionMarkup(d)}${d.note?`<details><summary>线下备注</summary><p>${e(d.note)}</p></details>`:''}${d.review?`<p>${e(d.status)}：${e(d.review.reason)}</p>`:''}</div><div class="rx-options">${d.rowId?`<button id="rcAdjustPerson" type="button" ${locked()?'disabled':''}>${schedule?'改发放月份':'调整这位员工的数据'}</button>`:''}<button id="rcRecordConclusion" type="button" ${locked()?'disabled':''}>记录核对结论</button>${(d.taskIds||[]).map(id=>`<button type="button" data-rc-task="${e(id)}">${e(data.workItems.find(t=>t.id===id)?.title||'补充关联资料')}</button>`).join('')}${d.rowId?'<button id="rcPersonDetail" type="button">查看人员与奖金明细</button>':''}</div>${(d.recordIds||[]).length?`<details><summary>相关处理记录 · ${d.recordIds.length} 条</summary>${recordMarkup(data.records.filter(r=>d.recordIds.includes(r.id)))}</details>`:''}</section>`);
    if($('rcAdjustPerson'))$('rcAdjustPerson').onclick=()=>schedule?window.RecruitmentActions.run('schedule',d.rowId,{installment:{kind:d.kind==='招聘奖金'?'recruitment':'referral',item:d.item}}):window.RecruitmentActions.open(d.rowId);
    if($('rcPersonDetail'))$('rcPersonDetail').onclick=()=>w.inspector(d.rowId);
    $('rcRecordConclusion').onclick=()=>review(data,d);
    document.querySelectorAll('[data-rc-task]').forEach(b=>b.onclick=()=>window.RecruitmentFlow.openWork(data.workItems.find(t=>t.id===b.dataset.rcTask)));bindRecords();
  }

  function recordMarkup(records){return records.map(r=>`<article class="rc-record"><header><strong>${e(r.type)} · ${e(r.title)}</strong><span>${e(r.status)}</span></header><p>${e(r.reason)}</p>${r.amount!=null?`<p>${e(w.amount(r.amount,r.currency))} · 实际支付未核实</p>`:''}<p>${e(r.at)}${r.pageNumbers?.length?` · 第 ${e(r.pageNumbers.join('、'))} 页`:''}</p>${r.issues?.length?`<p class="rd-error">${e(r.issues.join('；'))}</p>`:''}<div class="rc-actions">${r.action==='approval'?`<button class="rd-text-button" data-rc-approval="${e(r.sourceId)}">查看审批</button>`:r.action==='source'?`<a class="rd-text-button" href="${base()}/sources/${e(r.sourceId)}" target="_blank" rel="noopener">查看原始依据</a>`:r.action==='special'?'<button class="rd-text-button" data-rc-arrangements>查看调整记录</button>':''}${r.rowIds.length?`<details><summary>涉及 ${r.rowIds.length} 人</summary><div class="rc-actions">${r.rowIds.map(id=>`<button class="rd-text-button" data-rc-person="${e(id)}">${e(ui.data.rows.find(x=>x.id===id)?.values.姓名||'涉及人员')}</button>`).join('')}</div></details>`:''}</div></article>`).join('')||empty('尚无匹配的调整记录。');}
  function bindRecords(){document.querySelectorAll('[data-rc-approval]').forEach(b=>b.onclick=()=>window.RecruitmentReviewExtension.approval(b.dataset.rcApproval));document.querySelectorAll('[data-rc-arrangements]').forEach(b=>b.onclick=()=>window.RecruitmentSpecial.records());document.querySelectorAll('[data-rc-person]').forEach(b=>b.onclick=()=>w.inspector(b.dataset.rcPerson));}
  function renderRecords(data){
    const q=$('draftSearch').value.trim().toLowerCase(),rows=data.records.filter(r=>[r.title,r.type,r.status,r.reason,...r.rowIds.map(id=>ui.data.rows.find(x=>x.id===id)?.values.姓名)].join(' ').toLowerCase().includes(q));
    $('draftCount').textContent=`${rows.length} 条处理记录`;
    $('draftContent').insertAdjacentHTML('beforeend',`<section class="rc-records"><div class="rc-actions"><button id="rcNewArrangement" class="rd-button" type="button">调整数据</button><button id="rcAllArrangements" class="rd-text-button" type="button">奖金调整记录</button></div>${recordMarkup(rows)}</section>`);bindRecords();
    $('rcNewArrangement').disabled=locked();$('rcNewArrangement').onclick=()=>window.RecruitmentActions.open();$('rcAllArrangements').onclick=()=>window.RecruitmentSpecial.records();
  }
  function review(data,d){
    if(locked())return;
    const url=base(),token=crypto.randomUUID().replaceAll('-','');
    openDialog('记录差异核对结论',`<form id="rcReviewForm" class="rc-form"><strong>${e(d.name)} · ${e(d.kind)} · ${e(d.item)}</strong>${d.subject?`<p>${e(d.category)} · ${e(d.reason)}</p>`:`<div class="rc-amount-compare"><div><span>线下安排</span><strong>${e(w.amount(d.reference,d.currency))}</strong><span>${e(period(d.referencePeriod||'未安排月份'))}</span></div><div><span>当前核算</span><strong>${e(w.amount(d.calculated,d.calculatedCurrency))}</strong><span>${e(period(d.calculatedPeriod||'未安排月份'))}</span></div></div>`}<label>核对结论<select id="rcOutcome"><option value="pending">待继续核对</option><option value="retain">已核对，保留当前差异</option></select></label><p id="rcSaveError" class="rd-error" role="status"></p><button id="rcSave" class="rd-button rd-primary" type="submit">确认保存结论</button></form>`);
    const form=$('rcReviewForm');let payload=null;
    form.onsubmit=async ev=>{ev.preventDefault();if(locked()||url!==base())return;
      const next={revision:data.revision,sourceId:data.sourceId,differenceId:d.id,fingerprint:d.fingerprint,token:payload?.token||token,outcome:$('rcOutcome').value,basisType:'manual',confirmed:true};
      if(payload&&JSON.stringify(payload)!==JSON.stringify(next)){next.token=crypto.randomUUID().replaceAll('-','');}
      payload=next;const finish=window.RecruitmentInteractions.pending($('rcSave'),'正在保存…',form);if(!finish)return;w.busy(true);w.status('正在保存差异核对结论');
      try{const saved=await request(url+'/review-center',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});if(url===base()){cacheKey='';error='';w.adopt(saved);if(form.isConnected)$('draftInspector').close();}}
      catch(err){if(form.isConnected){$('rcSaveError').textContent=err.message;$('rcSave').disabled=false;}}
      finally{finish();w.busy(false);}
    };
  }
  window.RecruitmentReviewCenter={open,render};
})();
