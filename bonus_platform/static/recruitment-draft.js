(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const ui = {data:null, view:"rows", page:1, filterIds:null, filterTitle:"", selected:new Set(), busy:false, inspection:0, monthExplicit:!!new URLSearchParams(location.search).get("month")};
  const e = (v) => String(typeof v === "boolean" ? (v ? "是" : "否") : v ?? "").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const icon = name => `<svg class="rd-icon" aria-hidden="true"><use href="#icon-${name}"/></svg>`;
  const label = v => String(v??"").replace(/Offer|offer/g,"录用资料").replace(/ABC类别/g,"岗位类别").replace(/FBU/g,"仓储事业部").replace(/HRBP/g,"人力业务伙伴").replace(/Excel/g,"表格").replace(/PDF/g,"审批文件");
  const fields=["姓名","工号","入职日期","职级","ABC类别","招聘渠道","招聘启动日期","招聘负责人工号","招聘负责人姓名","协助招聘人工号","推荐人工号","人员状态","转正日期","最后工作日","周期剔除天数","周期剔除依据","原计划入职日期","应届校招","延后入职原因","管培生已批名单资格","周期豁免依据","上次离职日期","任职说明","人工备注"];
  const month=()=>$("draftMonth").value.replace("-","");
  const trial=new URLSearchParams(location.search).get("trial");
  const activity=new URLSearchParams(location.search).get("activity");
  const activityRoot=activity?`/api/recruitment/activities/${encodeURIComponent(activity)}`:"";
  const apiMonth=m=>`${activityRoot}${trial?`/api/recruitment/trials/${encodeURIComponent(trial)}`:""}/api/recruitment/drafts/${m}`;
  const base=()=>apiMonth(month());
  const amount=(value,currency="")=>value==null?"待核对":`${Number(value).toLocaleString("zh-CN",{maximumFractionDigits:2})}${currency?` ${currency}`:""}`;
  const sourceName=id=>ui.data.sources.find(s=>s.id===id)?.name||"人工补充";
  function editSourceMarkup(edit){
    if(!edit.evidenceId)return '';
    const refs=edit.evidenceRefs||[];
    return '<br>'+sourceLink(edit.evidenceId)+refs.map(ref=>` · ${e(ref.sheet||'')} 第 ${e(ref.row||'—')} 行${ref.column?`，第 ${e(ref.column)} 列`:''}`).join('');
  }
  function sourceLink(id,title){return ui.data.sources.some(s=>s.id===id)?`<a href="${base()}/sources/${encodeURIComponent(id)}" target="_blank" rel="noopener">${e(title||sourceName(id))}</a>`:e(title||sourceName(id));}
  function status(message,error=false){$("draftStatus").textContent=label(message);$("draftStatus").classList.toggle("rd-error",error);ui.operationMessage=label(message);ui.operationError=error;document.dispatchEvent(new CustomEvent("recruitment:status"));}
  function busy(value){
    ui.busy=value;
    ["draftMonth","draftUpload","draftUploadButton","draftSyncDomestic","draftRefresh","draftAddPerson","draftCarry"].forEach(id=>$(id).disabled=value);
    if(activity)$("draftMonth").disabled=true;
    if(ui.data?.activity?.archived)["draftUpload","draftUploadButton","draftSyncDomestic","draftRefresh","draftAddPerson","draftCarry"].forEach(id=>$(id).disabled=true);
    $("draftDropzone").setAttribute("aria-busy",String(value));
    const unavailable=value||!ui.data?.rows.length;$("draftExport").setAttribute("aria-disabled",String(unavailable));$("draftExport").tabIndex=unavailable?-1:0;
    document.dispatchEvent(new CustomEvent("recruitment:busy"));
  }
  async function request(url,options){
    if(activity&&url.startsWith('/api/recruitment/')&&!url.startsWith('/api/recruitment/activities/'))url=activityRoot+url;
    if(ui.data?.activity?.archived&&options?.method&&options.method!=='GET')throw new Error('活动已归档，请先在活动列表恢复后再修改');
    const response=await fetch(url,options);let data;
    try{data=await response.json();}catch{throw new Error("读取失败，请重试");}
    if(!response.ok)throw new Error(typeof data.detail==="string"?data.detail:data.detail?.message||"操作未完成，请核对输入后重试");
    return data;
  }
  function adopt(data){
    if((!ui.data||ui.data.month!==data.month)&&!data.rows.length&&!data.sources.length)ui.view="sources";
    const period=String(data.month),value=period.slice(0,4)+"-"+period.slice(4);
    if(![...$("draftMonth").options].some(o=>o.value===value))$("draftMonth").add(new Option(`${period.slice(0,4)}年${Number(period.slice(4))}月`,value));
    $("draftMonth").value=value;localStorage.setItem("recruitment-draft-month",value);
    const url=new URL(location.href);url.searchParams.set("month",value);history.replaceState(null,"",url);
    ui.data=data;ui.page=1;ui.selected.clear();ui.taskCache={};ui.comparison=null;
    $("draftCarry").hidden=!!data.revision||!data.previousAvailable;
    $("draftExport").href=base()+"/calculation/export";
    $("draftRawExport").href=base()+"/export";
    $("draftExport").setAttribute("aria-disabled",String(!data.rows.length));
    status(data.updatedAt?"已保存":"添加资料后自动保存");render();
  }
  async function load(){
    if(ui.busy||!month())return;
    busy(true);status("正在读取");
    try{
      let data=await request(base());let aligned=false;
      if(!trial&&!activity&&!ui.monthExplicit&&data.period?.canAlign){
        const target=await request(apiMonth(data.period.suggestedMonth));
        if(data.sources.filter(s=>s.active).every(s=>target.sources.some(t=>t.id===s.id&&t.active))){data=target;aligned=true;}
      }
      adopt(data);if(aligned)status(`已按资料月份切换至 ${data.month%100} 月`);
    }catch(err){ui.data=null;status(err.message,true);$("draftSummary").innerHTML="";$("draftCount").textContent="";$("draftExport").setAttribute("aria-disabled","true");$("draftContent").innerHTML=`<div class="rd-empty"><strong>暂时无法读取</strong><p>${e(err.message)}</p><button id="draftRetry" class="rd-button" type="button">重试</button></div>`;$("draftRetry").onclick=load;}
    finally{busy(false);}
  }
  async function refreshData(){
    if(ui.busy)return;if(!ui.data)return load();
    busy(true);status("正在按已保存资料重新核算");
    try{adopt(await request(base()+"/refresh",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({revision:ui.data.revision})}));}
    catch(err){status(err.message,true);}finally{busy(false);}
  }
  async function syncDomestic(){
    if(ui.busy||!ui.data)return;
    busy(true);status("正在查询本批国内人员的历史任职与招聘资料，请稍候");
    try{adopt(await request(base()+"/sync-domestic",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({revision:ui.data.revision})}));status("国内资料已同步并重新核算；快照已保存在资料中");}
    catch(err){status(err.message,true);}finally{busy(false);}
  }
  async function upload(files,comparisonOnly=false,purpose=''){
    if(ui.busy||!files.length||!ui.data)return;
    if(ui.data.activity?.archived){status('活动已归档，请先在活动列表恢复后再导入资料。',true);return;}
    ui.uploadCount=files.length;
    busy(true);status(`正在导入 ${files.length} 份资料`);
    try{
      const periods=purpose?[]:files.filter(f=>/奖金.*(?:核算|明细|台账)|(?:招聘|内推).*台账/.test(f.name)&&!/offer/i.test(f.name)).flatMap(f=>[...f.name.matchAll(/(?<!\d)(20\d{2})[年._-]?(0?[1-9]|1[0-2])月?(?!\d)/g)].map(m=>Number(m[1])*100+Number(m[2])));
      const inferred=periods.length?Math.max(...periods):null;
      let target=ui.data;
      if(!ui.monthExplicit&&!target.revision&&inferred&&inferred!==target.month)target=await request(apiMonth(inferred));
      // Preserve the confirmed opening and avoid writes during an existing task.
      target=await window.RecruitmentFlow?.beforeUpload?.(target,apiMonth(target.month))||target;
      const form=new FormData();form.append("comparisonOnly",String(comparisonOnly));form.append("revision",target.revision);form.append("periodConfirmed",String(ui.monthExplicit));if(purpose)form.append("purpose",purpose);for(const file of files)form.append("files",file);
      const changedMonth=target.month!==ui.data.month;
      adopt(await request(apiMonth(target.month)+"/sources",{method:"POST",body:form}));$("draftUpload").value="";
      if(!comparisonOnly)document.dispatchEvent(new CustomEvent("recruitment:uploaded",{detail:{files:files.map(file=>file.name)}}));
      if(changedMonth)status(`已按台账月份归入 ${target.month%100} 月`);
    }
    catch(err){status(err.message,true);}finally{ui.uploadCount=0;busy(false);}
  }
  async function change(payload,revision=ui.data.revision){adopt(await request(base()+"/changes",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({...payload,revision})}));}
  async function mutate(payload){if(ui.busy)return;busy(true);status("正在保存并更新试算");try{await change(payload);}catch(err){status(err.message,true);}finally{busy(false);}}
  function setView(view){if($("flowTools"))$("flowTools").hidden=true;$("draftDropzone").hidden=false;ui.view=view;ui.page=1;ui.flowPage=1;ui.selected.clear();ui.filterIds=null;ui.filterTitle="";$("draftScope").value="all";$("draftSearch").value="";render();$("draftContent").scrollTo(0,0);}
  function todoGroups(tasks=ui.data.todos){
    const groups=new Map();
    for(const task of tasks){
      const key=task.kind+"|"+task.title;
      if(!groups.has(key))groups.set(key,{...task,rowIds:[],sourceIds:[],taskIds:[]});
      const group=groups.get(key);group.rowIds.push(...task.rowIds);group.sourceIds.push(...task.sourceIds);group.taskIds.push(task.id);
    }
    return [...groups.values()].map(g=>({...g,rowIds:[...new Set(g.rowIds)],sourceIds:[...new Set(g.sourceIds)]}));
  }
  function render(){
    if(!ui.data)return;
    const s=ui.data.summary,currentCount=todoGroups().length;
    ui.todoGroups=todoGroups($("draftTodoScope").value==="history"?ui.data.historyTodos||[]:ui.data.todos);
    $("draftSummary").innerHTML=[["台账人员",s.people||0],["本月入职",s.newHires||0],["需核对人员",s.reviewPeople||0],["已添加资料",ui.data.sources.length]].map(([title,n])=>`<div class="rd-stat"><span>${title}</span><strong>${n.toLocaleString("zh-CN")}</strong></div>`).join("");
    $("draftTodoCount").textContent=currentCount||"";
    $("draftTodoScopeLabel").hidden=ui.view!=="todos";
    $("draftPeriodNotice").hidden=!ui.data.period?.mismatch;
    if(ui.data.period?.mismatch){const suggested=ui.data.period.suggestedMonth;$("draftPeriodText").textContent=`台账为 ${Math.floor(suggested/100)} 年 ${suggested%100} 月，当前按 ${ui.data.month%100} 月试算`;$("draftCorrectPeriod").textContent=`按 ${suggested%100} 月核算`;$("draftCorrectPeriod").hidden=!ui.data.period.canAlign;}
    document.querySelectorAll("[data-draft-view]").forEach(b=>{const active=b.dataset.draftView===ui.view;b.setAttribute("aria-selected",String(active));b.tabIndex=active?0:-1;if(active)$("draftContent").setAttribute("aria-labelledby",b.id);});
    $("draftSearch").placeholder=ui.view==="todos"?"搜索待办或人员":ui.view==="sources"?"搜索资料":"搜索姓名、工号";
    const query=$("draftSearch").value.trim().toLowerCase();
    let data=ui.view==="todos"?ui.todoGroups:["sources","comparison"].includes(ui.view)?ui.data.sources:ui.data.rows;
    $("draftScopeLabel").hidden=ui.view!=="rows";
    if(ui.view==="rows"){
      const scope=$("draftScope").value;
      if(scope==="new")data=data.filter(r=>(r.values.入职日期||r.values.候选人入职时间||"").slice(0,7).replace("-","")===month());
      if(scope==="due")data=data.filter(r=>["recruitment","referral"].some(k=>(r.calculation[k].currentAmount||0)>0));
      if(scope==="review")data=data.filter(r=>r.needsReview);
      data=[...data].sort((a,b)=>(b.values.入职日期||"").localeCompare(a.values.入职日期||""));
      if(ui.sort){const {key,direction}=ui.sort;data.sort((a,b)=>{const x=a.cells?.[key],y=b.cells?.[key];return (typeof x==="number"&&typeof y==="number"?x-y:String(x??"").localeCompare(String(y??""),"zh-CN",{numeric:true}))*direction;});}
    }
    if(ui.view==="rows"&&ui.filterIds)data=data.filter(r=>ui.filterIds.includes(r.id));
    if(query){
      const people=ui.view==="todos"?new Set(ui.data.rows.filter(r=>JSON.stringify(r.values).toLowerCase().includes(query)).map(r=>r.id)):null;
      data=data.filter(r=>label(JSON.stringify(ui.view==="rows"?r.values:r)).toLowerCase().includes(query)||(people&&r.rowIds.some(id=>people.has(id))));
    }
    const total=data.length,pageSize=ui.view==="todos"||ui.view==="comparison"?1000:50;
    ui.page=Math.max(1,Math.min(ui.page,Math.ceil(total/pageSize)||1));const visible=data.slice((ui.page-1)*pageSize,ui.page*pageSize);
    $("draftContext").hidden=!ui.filterTitle&&!ui.selected.size;
    $("draftContext").innerHTML=`<span>${e(label(ui.filterTitle))}${ui.selected.size?` · 已选 ${ui.selected.size} 人`:""}</span><div>${ui.selected.size?'<button class="rd-text-button" id="draftBatchEdit" type="button">批量修改</button>':""}<button class="rd-text-button" id="draftClearFilter" type="button">清除</button></div>`;
    $("draftClearFilter")?.addEventListener("click",()=>{ui.filterIds=null;ui.filterTitle="";ui.selected.clear();render();});
    $("draftBatchEdit")?.addEventListener("click",()=>editor([...ui.selected]));
    if(window.RecruitmentFlow?.handles(ui.view)){
      // The monthly projection renders below, without first fetching legacy
      // category panels or constructing the full ledger behind the new view.
    }else if(!total){
      const empty=!ui.data.rows.length&&!ui.data.sources.length;
      $("draftContent").innerHTML=`<div class="rd-empty"><span class="rd-empty-icon">${icon(empty?"file":"check")}</span><strong>${empty?"添加本月资料":query?"没有匹配结果":ui.view==="todos"?"当前没有待处理事项":"暂无记录"}</strong><p>${empty?"花名册、录用资料、历史台账，直接拖入即可。":query?"试试其他姓名、工号或关键词。":ui.view==="todos"?"可前往奖金明细查看试算结果。":"添加资料后会显示在这里。"}</p>${empty?'<button id="draftEmptyUpload" class="rd-button rd-primary" type="button">选择资料</button>':""}</div>`;
      $("draftEmptyUpload")?.addEventListener("click",()=>$("draftUpload").click());
    }else if(ui.view==="todos")renderTodos(visible);else if(ui.view==="rows")renderRows(visible);else if(ui.view==="comparison"&&window.RecruitmentWorkbenchExtension)window.RecruitmentWorkbenchExtension.renderComparison();else renderSources(visible);
    $("draftContent").dataset.view=ui.view;
    $("draftSummary").hidden=!ui.data.rows.length;
    $("draftPrevious").parentElement.hidden=total<=pageSize;
    $("draftCount").textContent=`${total} ${ui.view==="rows"?"人":ui.view==="sources"?"份资料":"类待办"}${total>pageSize?` · 第 ${ui.page} 页`:""}`;
    $("draftPrevious").disabled=ui.page<=1;$("draftNext").disabled=ui.page*pageSize>=total;
    document.dispatchEvent(new CustomEvent("recruitment:render"));
  }
  function renderTodos(rows){
    if(window.RecruitmentWorkbenchExtension)return window.RecruitmentWorkbenchExtension.renderTodos(rows);
    $("draftContent").innerHTML=rows.map(t=>`<article class="rd-todo"><div class="rd-todo-copy"><strong>${e(label(t.title.replace(/^首次使用：/,"")))}</strong></div><span class="rd-todo-meta">${t.rowIds.length?`${t.rowIds.length} 人`:"资料"}</span><button class="rd-text-button" type="button" data-todo="${t.id}">处理${icon("right")}</button></article>`).join("");
    document.querySelectorAll("[data-todo]").forEach(b=>b.onclick=()=>{
      const t=ui.todoGroups.find(t=>t.id===b.dataset.todo);
      if(t.rowIds.length){ui.view="rows";ui.filterIds=t.rowIds;ui.filterTitle=t.title;$("draftScope").value="all";ui.page=1;ui.selected.clear();$("draftSearch").value="";render();}
      else setView("sources");
    });
  }
  function renderRows(rows){
    if(ui.editing && window.RecruitmentReviewExtension) return window.RecruitmentReviewExtension.renderGrid(rows);
    if(window.RecruitmentWorkbenchExtension)return window.RecruitmentWorkbenchExtension.renderRows(rows);
    $("draftContent").innerHTML=`<table class="rd-table"><thead><tr><th><label class="rd-check"><input id="draftSelectVisible" type="checkbox" aria-label="选择本页人员" ${rows.every(r=>ui.selected.has(r.id))?"checked":""}></label></th>${["姓名","工号","入职日期","规则","招聘试算","内推试算","状态"].map((h,i)=>`<th scope="col" ${i===4||i===5?'class="rd-number"':""}>${h}</th>`).join("")}</tr></thead><tbody>${rows.map(r=>{
      const v=r.values,c=r.calculation;
      const rowStatus=r.attentionScope==="current"?"本月待核":r.attentionScope==="history"?"历史待核":["recruitment","referral"].some(k=>c?.[k].total==null)?"资料待核":"已试算";
      return `<tr><td><label class="rd-check"><input data-select-row="${r.id}" type="checkbox" aria-label="选择 ${e(v.姓名)}" ${ui.selected.has(r.id)?"checked":""}></label></td><td><button class="rd-row-open" data-row="${r.id}" type="button">${e(v.姓名||"姓名待补")}</button></td><td class="rd-cell-muted">${e(v.工号||"无工号")}</td><td>${e(v.入职日期||v.候选人入职时间||"待核对")}</td><td>${r.rule.version==="legacy"?"旧版":r.rule.version==="2026-07"?"七月新版":"待核对"}</td><td class="rd-number">${e(amount(c?.recruitment.total,c?.recruitment.currency))}</td><td class="rd-number">${e(amount(c?.referral.total,c?.referral.currency))}</td><td><span class="rd-badge ${r.attentionScope==="current"?"rd-attention":""}">${rowStatus}</span></td></tr>`;
    }).join("")}</tbody></table>`;
    document.querySelectorAll("[data-row]").forEach(b=>b.onclick=()=>inspector(b.dataset.row));
    document.querySelectorAll("[data-select-row]").forEach(input=>input.onchange=()=>{input.checked?ui.selected.add(input.dataset.selectRow):ui.selected.delete(input.dataset.selectRow);render();});
    const selection=$("draftSelectVisible");selection.indeterminate=rows.some(r=>ui.selected.has(r.id))&&!rows.every(r=>ui.selected.has(r.id));selection.onchange=event=>{rows.forEach(r=>event.target.checked?ui.selected.add(r.id):ui.selected.delete(r.id));render();};
  }
  function approvalStatus(source){
    const review=ui.data.reviewEntries?.filter(r=>r.sourceId===source.id&&(!r.operationId||ui.data.activeOperations.includes(r.operationId))).at(-1);
    return !review?'审批附件':review.applied?`已应用 ${review.rowIds.length} 人${review.scopeComplete?'':' · 剩余范围待核'}`:review.status;
  }
  function renderSources(rows){
    if(window.RecruitmentWorkbenchExtension)return window.RecruitmentWorkbenchExtension.renderSources(rows);
    $("draftContent").innerHTML=rows.map(s=>`<article class="rd-todo"><span class="rd-source-icon">${icon("file")}</span><div class="rd-todo-copy"><strong>${sourceLink(s.id)}${ui.data.baseline===s.id?' <span class="rd-badge">已选期初</span>':""}</strong><p class="${s.error?"rd-error":""}">${e(s.error?"读取失败，请核对文件":s.attachment?approvalStatus(s):`${(s.recordCount||0).toLocaleString("zh-CN")} 条记录`)}${s.active?"":" · 已停用"}</p></div><div>${s.roles?.includes("ledger")?`<button class="rd-text-button" type="button" data-reconcile-source="${s.id}">核对差异</button>`:""}${s.attachment?`<button class="rd-text-button" type="button" data-review-source="${s.id}">审阅</button>`:""}${s.roles?.includes("ledger")&&ui.data.baseline!==s.id&&s.active?`<button class="rd-text-button" type="button" data-baseline="${s.id}">设为期初</button>`:""}${ui.data.baseline!==s.id?`<button class="rd-text-button" type="button" data-toggle-source="${s.id}">${s.active?"停用":"恢复"}</button>`:""}</div></article>`).join("");
    document.querySelectorAll("[data-baseline]").forEach(b=>b.onclick=()=>{const source=ui.data.sources.find(s=>s.id===b.dataset.baseline);openDialog("选择期初",`<p>${e(source.name)}</p><p class="rd-message">作为历史对照保存。历史金额的实际支付状态仍需核实。</p><button id="draftConfirmBaseline" class="rd-button rd-primary" type="button">采用这份期初</button>`);$("draftConfirmBaseline").onclick=async()=>{await mutate({baseline:source.id});$("draftInspector").close();};});
    document.querySelectorAll("[data-toggle-source]").forEach(b=>b.onclick=()=>{const s=ui.data.sources.find(s=>s.id===b.dataset.toggleSource);mutate({source:{id:s.id,active:!s.active}});});
  }
  function openDialog(title,html){if(!$("draftInspector").open)ui.dialogOpener=document.activeElement;$("draftInspectorTitle").textContent=title;$("draftInspectorBody").innerHTML=html;$("draftInspector").scrollTop=0;$("draftInspectorBody").scrollTop=0;if(!$("draftInspector").open)$("draftInspector").showModal();window.RecruitmentInteractions?.dialog();}
  function awardMarkup(a,title){
    const notes=[...a.issues,...a.reasons];
    const proof=a.approvalDecision?`<p class="rd-message">按公式试算 ${e(amount(a.formulaTotal,a.currency))} · ${a.approvalDecision.basisType==='manual'?'手工设置不发':`${sourceLink(a.approvalDecision.sourceId,"查看审批原件")} · 第 ${a.approvalDecision.pageNumbers.join("、")} 页`}</p>`:"";
    return `<section class="rd-award"><div class="rd-award-head"><span>${title}</span><strong>${e(amount(a.total,a.currency))}</strong></div>${proof}${a.roundingDifference?`<p class="rd-rounding-line">分期合计 ${e(amount(a.scheduledTotal,a.currency))} · 尾差 ${a.roundingDifference>0?'+':''}${e(amount(a.roundingDifference,a.currency))}</p>`:""}${notes.length?`<p class="rd-message">${e(label(notes.join("；")))}</p>`:""}<details class="rd-evidence"><summary>计算与分期</summary><p>${e(a.source||"标准待核对")}${a.standard!=null?` · 标准 ${e(amount(a.standard,a.currency))}`:""}</p>${a.cycle?`<p>${a.cycle.exempt?"已按依据免除周期限制":`标准周期 ${a.cycle.standardDays} 天 · 采用周期 ${a.cycle.actualDays??"待核"} 天`}<br>周期系数 ${a.cycle.factor==null?"待核":`${Math.round(a.cycle.factor*100)}%`} · 渠道比例 ${a.channelFactor==null?"待核":`${Math.round(a.channelFactor*100)}%`}</p>`:""}${a.nodes.map(n=>`<div class="rd-node"><div class="rd-node-line"><span>${e(n.label)}</span><b>${e(amount(n.amount,n.currency))}</b></div><p>${e(n.recipientName||n.recipientId||"领取人待核")} · ${e(n.dueDate||"日期待核")} · ${e(n.status)}</p>${n.issues.length?`<p>${e(label(n.issues.join("；")))}</p>`:""}</div>`).join("")}</details></section>`;
  }
  function fieldDisplay(field,value){return e(window.RecruitmentDetailTable?.isIdentity(field)?window.RecruitmentDetailTable.maskIdentity(value):value);}
  async function inspector(id){
    ui.focusRow=id;const seq=++ui.inspection,url=base();
    openDialog("人员详情",'<div class="rd-loading" aria-label="正在读取"><span></span><span></span></div>');
    try{
      const {row,revision}=await request(url+`/rows/${id}`);if(!$("draftInspector").open||seq!==ui.inspection||url!==base())return;
      const v=row.values,c=row.calculation;
      const pairs=fields.filter(f=>v[f]!==undefined&&v[f]!=="");
      const employment=row.employmentContext;
      const employmentInfo=employment?`<section class="rd-inspector-section"><h3>招聘任职</h3><dl><dt>原招聘入职日</dt><dd>${e(employment.recruitmentHireDate||'待核')}</dd><dt>人事入职日</dt><dd>${e(employment.hrHireDates.join('、')||'未提供')}</dd><dt>试用期转正日</dt><dd>${e(employment.probationDate||'未提供')}</dd></dl>${employment.continuationConfirmed?'<p>已确认任职延续，奖金沿用原招聘入职日。</p>':''}${employment.offerMatchBasis?`<p>${e(employment.offerMatchBasis.reason)}</p>${employment.offerMatchBasis.sources.map(s=>`<p>${sourceLink(s.sourceId)} · 第 ${e(s.row)} 行</p>`).join('')}`:''}</section>`:'';

      openDialog(v.姓名||"人员详情",`<p class="rd-message">${e(v.工号||"无工号")} · ${e(row.rule.label)}</p>${awardMarkup(c.recruitment,"招聘奖金")}${awardMarkup(c.referral,"内推奖金")}${employmentInfo}${window.RecruitmentWorkbenchExtension?.suggestionMarkup(row.reviewSuggestion,true)||''}<p id="draftSuggestedStatus" class="rd-error" role="status"></p><div class="rd-person-actions"><button id="draftEditRecord" class="rd-button rd-primary" type="button">修改资料</button></div><details class="rd-inspector-section"><summary>人员资料</summary><dl>${pairs.map(f=>`<dt>${e(label(f))}</dt><dd>${e(window.RecruitmentDetailTable?.isIdentity(f)?window.RecruitmentDetailTable.maskIdentity(v[f]):v[f])}</dd>`).join("")}</dl></details><details class="rd-inspector-section"><summary>来源与采用值</summary>${Object.entries(row.provenance).filter(([f])=>f!=="证件号").map(([f,refs])=>`<details class="rd-evidence"><summary>${e(label(f))} · ${fieldDisplay(f,v[f]??"待补充")}</summary>${refs.map(ref=>`<p>${sourceLink(ref.sourceId)}<br>${e(ref.sheet)} · 第 ${ref.row} 行${ref.column?`，第 ${ref.column} 列`:""}<br>原值：${fieldDisplay(f,ref.rawValue??ref.value)}</p>`).join("")}</details>`).join("")}</details><details class="rd-inspector-section"><summary>修改记录${row.edits.length?` · ${row.edits.length} 条`:""}</summary>${row.edits.length?row.edits.map(ed=>`<div class="rd-evidence">${e(label(ed.field))}：${fieldDisplay(ed.field,ed.before===null||ed.before===undefined||ed.before===""?"空白":ed.before)} → ${fieldDisplay(ed.field,ed.value===null||ed.value===undefined||ed.value===""?"空白":ed.value)}<p>${e(ed.reason)}<br>${e(ed.at.replace("T"," "))}${editSourceMarkup(ed)}</p></div>`).join(""):'<p class="rd-message">暂无人工修改</p>'}</details><details class="rd-inspector-section"><summary>历史记录 · ${row.history.length} 份</summary><p class="rd-message">原始金额与安排完整保留，实际支付尚未核实。</p>${row.history.map(h=>`<div class="rd-evidence">${sourceLink(h.ref.sourceId)}<p>${e(h.ref.sheet)} · 第 ${h.ref.row} 行</p></div>`).join("")}</details>`);
      $("draftEditRecord").onclick=()=>editor([id],row,revision);
      if(row.reviewSuggestion&&$("rwSuggestedPreview"))$("rwSuggestedPreview").onclick=async()=>{
        const button=$("rwSuggestedPreview"),finish=window.RecruitmentInteractions.pending(button,"正在核算…",$("draftInspectorBody"));if(!finish)return;
        try{const preview=await request(url+'/previews',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision,edits:row.reviewSuggestion.edits})});finish();if(button.isConnected&&$('draftInspector').open&&url===base())window.RecruitmentReviewExtension.showPreview(preview,()=>inspector(id));}
        catch(err){if(button.isConnected)$("draftSuggestedStatus").textContent=label(err.message);}finally{finish();}
      };

      if(ui.data.settlementEnabled&&window.RecruitmentTrial){const b=document.createElement("button");b.className="rd-button";b.textContent="分期安排";b.id="draftInstallments";b.onclick=()=>window.RecruitmentTrial.installments(row,revision);$("draftEditRecord").after(b);}
    }catch(err){if(seq===ui.inspection)$("draftInspectorBody").textContent=label(err.message);}
  }
  async function editor(ids,row=null,revision=ui.data.revision,context={}){
    if(!row&&ids.length===1){
      const seq=++ui.inspection,url=base();openDialog('修改资料','<p role="status">正在读取…</p>');
      try{const data=await request(url+'/rows/'+ids[0]);if(seq!==ui.inspection||url!==base()||!$('draftInspector').open)return;if(data.revision!==revision)throw new Error('资料已更新，请刷新后重试');row=data.row;}
      catch(err){if(seq===ui.inspection&&$('draftInspector').open)$('draftInspectorBody').textContent=label(err.message);return;}
    }
    let factControls=row?.fieldControls||ui.data.fieldControls;
    if(ids.length>1){
      const url=base();openDialog('批量修改资料','<p role="status">正在读取已有资料…</p>');
      try{const data=await request(url+'/field-controls',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision,rowIds:ids})});if(url!==base()||!$('draftInspector').open||revision!==ui.data.revision)return;factControls=data.fieldControls;}
      catch(err){$('draftInspectorBody').textContent=err.message;return;}
    }
    const available=ui.data.editableFields,options=[...fields.filter(f=>available.includes(f)),...available.filter(f=>!fields.includes(f))];
    const sources=ui.data.sources.filter(s=>s.active&&!s.error&&!s.comparisonOnly);
    const groups={'任职资料':['转正日期','最后工作日','任职说明'],'招聘信息':['招聘渠道','其他渠道','招聘启动日期','职级','ABC类别'],'招聘与推荐关系':['招聘负责人姓名','招聘负责人工号','协助招聘人姓名','协助招聘人工号','推荐人姓名','推荐人工号'],'招聘周期':['管培生已批名单资格','周期豁免依据','周期剔除天数','周期剔除依据']};
    openDialog(row?`${row.values.姓名} · 修改资料`:`修改 ${ids.length} 人`, `<form id="draftEditForm" class="rw-fact-editor">${context.note?`<section class="rw-edit-note"><h3>线下备注</h3><p>${e(context.note)}</p></section>`:''}<details class="rw-edit-shortcuts"><summary>按类别添加多项</summary><div>${Object.keys(groups).map(g=>`<button type="button" class="rd-button" data-edit-group="${g}">${g}</button>`).join('')}</div></details><div id="draftEditLines"></div><button type="button" id="draftAddEditField" class="rd-text-button">＋ 再改一项</button><p id="draftEditStatus" class="rd-message" role="status"></p><div class="rw-sticky-actions"><button type="button" id="draftEditCancel" class="rd-button">取消</button><button type="submit" class="rd-button rd-primary">查看修改结果</button></div></form>`);
    let serial=0;
    function addLine(initial){
      const first=serial++===0,line=document.createElement('section');line.className='rw-edit-line';
      line.innerHTML=`<div class="rw-edit-inputs"><label>修改项目<select ${first?'id="draftEditField"':''} data-fact-field data-searchable>${options.map(f=>`<option value="${e(f)}">${e(ui.data.fieldControls?.[f]?.label||label(f))}</option>`).join('')}</select></label><label>修改为<input ${first?'id="draftEditValue"':''} data-fact-value autocomplete="off" list="factOptions-${serial}"/><datalist id="factOptions-${serial}"></datalist></label><button type="button" class="rd-text-button" aria-label="移除此字段">移除</button></div><p class="rw-adopted-value" hidden></p><div class="rw-edit-provenance"></div>`;
      const select=line.querySelector('select');let input=line.querySelector('[data-fact-value]');select.value=initial||'入职日期';
      const originalValue=()=>{const original=line.querySelector('.rw-adopted-value'),value=row?.values[select.value]??'';original.hidden=!row||input.value===String(value);original.textContent=original.hidden?'':`原值：${value===''?'未提供':value}`;};
      const inputChanged=()=>{line.dataset.dirty='true';delete line.dataset.evidence;originalValue();const summary=line.querySelector('.rw-edit-provenance summary');if(summary)summary.textContent='来源值';};
      const update=()=>{const f=select.value;line.dataset.dirty='false';delete line.dataset.evidence;
        const definition=factControls?.[f];
        const markup=window.RecruitmentFactControls.choice(definition,row?.values[f]??'',`${first?'id="draftEditValue"':''} data-fact-value`);
        input.parentElement.innerHTML=`修改为${markup??`<input ${first?'id="draftEditValue"':''} data-fact-value autocomplete="off" type="${/日期|工作日|入职时间/.test(f)?'date':f.includes('天数')?'number':'text'}" value="${e(row?.values[f]??'')}"/>`}`;
        input=line.querySelector('[data-fact-value]');input.oninput=inputChanged;originalValue();
        const refs=(row?.provenance?.[f]||[]).filter(ref=>sources.some(s=>s.id===ref.sourceId)),holder=line.querySelector('.rw-edit-provenance');
        const candidates=new Map();refs.forEach(ref=>{const key=String(ref.value??'');if(!candidates.has(key))candidates.set(key,[]);const group=candidates.get(key);if(!group.some(r=>r.sourceId===ref.sourceId&&r.sheet===ref.sheet&&r.row===ref.row&&r.column===ref.column))group.push(ref);});
        const groups=[...candidates.values()];
        holder.innerHTML=groups.length&&!definition?.choices?`<details><summary>来源值</summary>${groups.map((group,i)=>`<p><button type="button" class="rd-text-button" data-fact-source="${i}">采用 ${e(group[0].value??'空白')}</button>${group.map(ref=>`${sourceLink(ref.sourceId)} · ${e(ref.sheet)} 第 ${e(ref.row)} 行`).join('；')}</p>`).join('')}</details>`:'';
        holder.querySelectorAll('[data-fact-source]').forEach(button=>button.onclick=()=>{const ref=groups[Number(button.dataset.factSource)][0];input.value=ref.value??'';line.dataset.dirty='true';line.dataset.evidence=ref.sourceId;originalValue();holder.querySelector('details').open=false;holder.querySelector('summary').textContent='已关联来源';});
      };
      select.onchange=update;line.querySelector('button').onclick=()=>line.remove();$('draftEditLines').append(line);update();
    }
    addLine(context.field||'入职日期');
    $('draftAddEditField').onclick=()=>addLine('');
    document.querySelectorAll('[data-edit-group]').forEach(b=>b.onclick=()=>{const existing=[...document.querySelectorAll('[data-fact-field]')].map(s=>s.value);groups[b.dataset.editGroup].filter(f=>available.includes(f)&&!existing.includes(f)).forEach(addLine);});
    $('draftEditCancel').onclick=()=>$('draftInspector').close();
    $('draftEditForm').onsubmit=async event=>{
      event.preventDefault();if(ui.busy)return;const form=event.target,url=base(),button=event.submitter||form.querySelector('[type="submit"]');
      const finish=window.RecruitmentInteractions.pending(button,'正在核算…',form);if(!finish)return;busy(true);status('正在核算修改结果');
      const lines=[...$('draftEditLines').children].filter(line=>line.dataset.dirty==='true').map(line=>({field:line.querySelector('[data-fact-field]').value,value:line.querySelector('[data-fact-value]').value,evidenceId:line.dataset.evidence||''}));
      const edits=ids.flatMap(rowId=>{const current=row?.id===rowId?row:ui.data.rows.find(r=>r.id===rowId);return lines.filter(x=>x.evidenceId||String(current?.values[x.field]??'')!==x.value).map(x=>({rowId,...x}));});
      try{if(!edits.length)throw new Error('请填写修改后的内容');const preview=await request(url+'/previews',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision,edits})});finish();if(!form.isConnected||!$('draftInspector').open||url!==base())return;const nodes=[...$('draftInspectorBody').childNodes];window.RecruitmentReviewExtension.showPreview(preview,()=>{openDialog(row?`${row.values.姓名} · 修改资料`:`修改 ${ids.length} 人`,'');$('draftInspectorBody').replaceChildren(...nodes);});status('核算完成，请查看修改结果');}
      catch(err){if(form.isConnected){$('draftEditStatus').textContent=label(err.message);$('draftEditStatus').classList.add('rd-error');}status(err.message,true);}
      finally{finish();busy(false);}
    };
  }
  function addPerson(){
    if(!ui.data)return;
    const revision=ui.data.revision;
    openDialog("补充人员",`<form id="draftPersonForm">${["姓名","工号","入职日期","招聘负责人工号","人工备注"].map(f=>`<label>${label(f)}<input name="${f}" ${f==="姓名"?"required":""} type="${f==="入职日期"?"date":"text"}" /></label>`).join("")}<p id="draftEditStatus" class="rd-message" role="status"></p><button class="rd-button rd-primary" type="submit">保存人员</button></form>`);
    $("draftPersonForm").onsubmit=async event=>{event.preventDefault();if(ui.busy)return;const form=event.target,supplement=Object.fromEntries(new FormData(form)),finish=window.RecruitmentInteractions.pending(event.submitter,"正在保存…",form);if(!finish)return;busy(true);status("正在保存人员资料");try{await change({supplement},revision);if(form.isConnected)$("draftInspector").close();setView("rows");status("已保存，奖金已更新");}catch(err){if(form.isConnected){$("draftEditStatus").textContent=label(err.message);$("draftEditStatus").classList.add("rd-error");}status(err.message,true);}finally{finish();busy(false);}};
  }
  const now=new Date(),current=now.toLocaleDateString("sv-SE").slice(0,7);
  const stored=new URLSearchParams(location.search).get("month")||localStorage.getItem("recruitment-draft-month")||current;
  const months=new Set([current,/^20\d{2}-(0[1-9]|1[0-2])$/.test(stored)?stored:current]);
  for(let i=-24;i<=3;i++){const d=new Date(now.getFullYear(),now.getMonth()+i,1);months.add(`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}`);}
  $("draftMonth").innerHTML=[...months].sort().reverse().map(m=>`<option value="${m}">${m.slice(0,4)}年${Number(m.slice(5))}月</option>`).join("");$("draftMonth").value=months.has(stored)?stored:current;
  $("draftMonth").onchange=()=>{ui.monthExplicit=true;ui.filterIds=null;ui.filterTitle="";ui.inspection++;$("draftInspector").close();localStorage.setItem("recruitment-draft-month",$("draftMonth").value);if(trial){location.href="recruitment.html?month="+$("draftMonth").value;return;}load();};
  $("draftExport").onclick=event=>{if(ui.busy||!ui.data?.rows.length)event.preventDefault();};
  $("draftSyncDomestic").onclick=syncDomestic;$("draftRefresh").onclick=refreshData;$("draftUploadButton").onclick=()=>$("draftUpload").click();$("draftUpload").onchange=event=>upload([...event.target.files]);
  $("draftCarry").onclick=async()=>{if(ui.busy||!ui.data?.previousAvailable)return;busy(true);status("正在承接上月");try{adopt(await request(base()+"/carry-forward",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({revision:ui.data.revision,sourceMonth:ui.data.previousMonth})}));}catch(err){status(err.message,true);}finally{busy(false);}};
  $("draftScope").onchange=()=>{ui.page=1;ui.selected.clear();render();};
  $("draftTodoScope").onchange=()=>{ui.page=1;ui.selected.clear();render();};
  $("draftCorrectPeriod").onclick=async()=>{if(ui.busy)return;busy(true);status("正在按台账月份整理");try{const data=await request(base()+"/correct-period",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({revision:ui.data.revision})});ui.monthExplicit=false;ui.filterIds=null;ui.filterTitle="";adopt(data);status(`已按 ${data.month%100} 月核算`);}catch(err){status(err.message,true);}finally{busy(false);}};
  $("draftSearch").oninput=()=>{ui.page=1;ui.selected.clear();render();};$("draftAddPerson").onclick=addPerson;
  $("draftPrevious").onclick=()=>{ui.page--;ui.selected.clear();render();$("draftContent").scrollTo(0,0);};$("draftNext").onclick=()=>{ui.page++;ui.selected.clear();render();$("draftContent").scrollTo(0,0);};
  $("draftInspector").addEventListener("close",()=>{const target=ui.dialogOpener?.isConnected?ui.dialogOpener:document.querySelector(`[data-row="${ui.focusRow}"]`)||$("draftTabRows");target.focus();});
  $("draftCloseInspector").onclick=()=>{ui.inspection++;$("draftInspector").close();};
  const tabs=[...document.querySelectorAll("[data-draft-view]")];tabs.forEach((b,i)=>{b.onclick=()=>setView(b.dataset.draftView);b.onkeydown=event=>{if(!["ArrowLeft","ArrowRight","Home","End"].includes(event.key))return;event.preventDefault();const next=event.key==="Home"?0:event.key==="End"?tabs.length-1:(i+(event.key==="ArrowRight"?1:-1)+tabs.length)%tabs.length;setView(tabs[next].dataset.draftView);tabs[next].focus();};});
  document.addEventListener("click",event=>{document.querySelectorAll(".rd-menu[open]").forEach(menu=>{if(!menu.contains(event.target)||event.target.closest(".rd-menu-items"))menu.open=false;});});
  document.addEventListener("keydown",event=>{if(event.key==="Escape")document.querySelectorAll(".rd-menu[open]").forEach(m=>m.open=false);});
  let dragDepth=0;const drop=$("draftDropzone");drop.ondragenter=event=>{event.preventDefault();dragDepth++;drop.classList.add("rd-dragover");};drop.ondragover=event=>event.preventDefault();drop.ondragleave=()=>{dragDepth=Math.max(0,dragDepth-1);if(!dragDepth)drop.classList.remove("rd-dragover");};drop.ondrop=event=>{event.preventDefault();dragDepth=0;drop.classList.remove("rd-dragover");upload([...event.dataTransfer.files]);};
  load();
  window.RecruitmentWorkbench={ui,$,e,label,base,request,adopt,busy,status,render,openDialog,mutate,amount,sourceLink,editSourceMarkup,inspector,setView,editor,icon,upload,refreshData,syncDomestic};
})();
