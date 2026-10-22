(() => {
  'use strict';
  const w=window.RecruitmentWorkbench,{$,ui,e,base,request,openDialog}=w;
  const actions=[['facts','修改人员资料'],['assignment','更换招聘负责人／协助人'],['schedule','改发放月份／暂缓发放'],['adjustment','补发／扣回奖金'],['exception','离职／未转正仍需发放'],['exclude','不发奖金']];
  const locked=()=>ui.busy||['running','cancelling'].includes(ui.prepareJob?.status)||ui.data?.activity?.archived;
  let sequence=0;
  function open(rowId='',options={}){
    if(!ui.data||locked())return;
    const row=ui.data.rows.find(r=>r.id===rowId);
    $('draftInspector').classList.remove('rd-wide');
    if(row&&options.action){run(options.action,rowId,options);return;}
    let action=options.action||'';
    openDialog('调整数据',`<section class="rx-actions">${row?`<div class="rx-person"><div><strong>${e(row.values.姓名||'未命名')}</strong><span>${e(row.values.工号||'无工号')} · ${e(row.values.入职日期||'')}</span></div><button id="rxChangePerson" class="rd-text-button" type="button">换个人</button></div>`:`<label class="rx-search">调整哪位员工<input id="rxSearch" type="search" placeholder="输入姓名或工号" autocomplete="off" /></label><div id="rxPeople" class="rx-people" aria-live="polite"></div>`}<div class="rx-options" aria-label="调整事项">${actions.map(([id,title])=>`<button type="button" data-rx-action="${id}" aria-pressed="${id===action}"><span>${title}</span><span aria-hidden="true">›</span></button>`).join('')}</div><div class="rx-footer"><button id="rxBatch" class="rd-text-button" type="button">批量修改</button><button id="rxExcel" class="rd-text-button" type="button">用 Excel 修改</button><button id="rxExternal" class="rd-text-button" type="button">体系外核算结果</button></div></section>`);
    document.querySelectorAll('[data-rx-action]').forEach(b=>b.onclick=()=>{
      if(row){run(b.dataset.rxAction,rowId,options);return;}
      action=b.dataset.rxAction;
      $('draftInspectorTitle').textContent=actions.find(([id])=>id===action)[1]+' · 选择员工';
      document.querySelectorAll('[data-rx-action]').forEach(button=>button.setAttribute('aria-pressed',String(button===b)));
      $('rxSearch').focus();
    });
    if(row)$('rxChangePerson').onclick=()=>open('',options);
    else{
      function people(){const q=$('rxSearch').value.trim().toLowerCase();const found=q?ui.data.rows.filter(r=>`${r.values.姓名} ${r.values.工号}`.toLowerCase().includes(q)):[];
        $('rxPeople').innerHTML=!q?'':found.length?found.slice(0,12).map(r=>`<button type="button" data-rx-person="${e(r.id)}"><strong>${e(r.values.姓名||'未命名')}</strong><span>${e(r.values.工号||'无工号')} · ${e(r.values.入职日期||'')}</span></button>`).join('')+(found.length>12?'<p>请补全姓名或工号。</p>':''):'<p>未找到员工</p>';
        document.querySelectorAll('[data-rx-person]').forEach(b=>b.onclick=()=>open(b.dataset.rxPerson,{...options,action}));}
      $('rxSearch').oninput=people;$('rxSearch').focus();
    }
    $('rxBatch').onclick=batch;$('rxExcel').onclick=excel;$('rxExternal').onclick=()=>window.RecruitmentExternalResults.open();
  }
  function batch(){
    if(locked())return;
    const selected=new Set([...ui.selected].filter(id=>ui.data.rows.some(r=>r.id===id)));let page=1;
    openDialog('批量修改',`<section class="rx-actions"><label class="rx-search">选择员工<input id="rxBatchSearch" type="search" placeholder="搜索姓名或工号"/></label><label class="rd-choice"><input id="rxBatchAll" type="checkbox"/>选择本页</label><div id="rxBatchPeople" class="rx-batch-people"></div><div class="rx-batch-pagination"><button id="rxBatchPrev" class="rd-text-button" type="button">上一页</button><span id="rxBatchCount" role="status"></span><button id="rxBatchNext" class="rd-text-button" type="button">下一页</button></div><div class="rx-footer"><button id="rxBatchFacts" class="rd-button rd-primary" type="button">修改资料</button><button id="rxBatchAssignments" class="rd-button" type="button">更换招聘分工</button><button id="rxBatchTable" class="rd-text-button" type="button">在表格中编辑</button></div></section>`);
    function draw(){
      const q=$('rxBatchSearch').value.trim().toLowerCase(),rows=ui.data.rows.filter(r=>`${r.values.姓名} ${r.values.工号}`.toLowerCase().includes(q)),pages=Math.max(1,Math.ceil(rows.length/40));page=Math.min(page,pages);const visible=rows.slice((page-1)*40,page*40);
      $('rxBatchPeople').innerHTML=visible.map(r=>`<label class="rd-choice"><input type="checkbox" data-rx-batch-person="${e(r.id)}" ${selected.has(r.id)?'checked':''}/><strong>${e(r.values.姓名||'未命名')}</strong><span>${e(r.values.工号||'无工号')} · ${e(r.values.入职日期||'')}</span></label>`).join('')||'<p>未找到员工</p>';
      $('rxBatchCount').textContent=`已选 ${selected.size} 人 · ${page} / ${pages} 页${selected.size>500?' · 单次最多 500 人，请减少选择':''}`;
      $('rxBatchPrev').disabled=page===1;$('rxBatchNext').disabled=page===pages;
      $('rxBatchAll').checked=visible.length>0&&visible.every(r=>selected.has(r.id));$('rxBatchAll').indeterminate=visible.some(r=>selected.has(r.id))&&!$('rxBatchAll').checked;
      $('rxBatchAll').onchange=ev=>{visible.forEach(r=>ev.target.checked?selected.add(r.id):selected.delete(r.id));draw();};
      document.querySelectorAll('[data-rx-batch-person]').forEach(c=>c.onchange=()=>{c.checked?selected.add(c.dataset.rxBatchPerson):selected.delete(c.dataset.rxBatchPerson);draw();document.querySelector(`[data-rx-batch-person="${c.dataset.rxBatchPerson}"]`)?.focus();});
      ['rxBatchFacts','rxBatchAssignments'].forEach(id=>$(id).disabled=!selected.size||selected.size>500);
    }
    $('rxBatchSearch').oninput=()=>{page=1;draw();};$('rxBatchPrev').onclick=()=>{page--;draw();};$('rxBatchNext').onclick=()=>{page++;draw();};
    $('rxBatchFacts').onclick=()=>{if(locked())return;ui.selected=new Set(selected);w.editor([...selected]);};
    $('rxBatchAssignments').onclick=()=>{if(locked())return;ui.selected=new Set(selected);window.RecruitmentAssignments.open([...selected]);};
    $('rxBatchTable').onclick=()=>{ui.selected=new Set(selected);$('draftInspector').close();$('flowBatch').click();};draw();
  }
  async function run(action,rowId,options={}){
    if(locked())return;
    if(action==='assignment'){window.RecruitmentAssignments.open([rowId],options);return;}
    if(['adjustment','exception','exclude'].includes(action)){window.RecruitmentSpecial.open(rowId,{...options,type:action});return;}
    const url=base(),seq=++sequence;openDialog('正在读取人员资料','<p role="status">正在读取…</p>');const loading=$('draftInspectorBody').firstElementChild;
    try{const {row,revision}=await request(url+'/rows/'+encodeURIComponent(rowId));if(seq!==sequence||url!==base()||!loading.isConnected||!$('draftInspector').open)return;
      if(action==='schedule')window.RecruitmentTrial.installments(row,revision,options.installment);
      else window.RecruitmentFlow.editPerson(row,revision);
    }catch(err){if(loading.isConnected)loading.textContent=err.message;}
  }
  function excel(){$('draftInspector').classList.remove('rd-wide');openDialog('用 Excel 修改',`<section class="rx-actions rx-options"><a class="rd-button" href="${base()}/worksheet">下载可修改的底稿</a><button id="rxReturn" type="button">上传修改后的底稿</button></section>`);$('rxReturn').onclick=()=>$('draftWorkbookReturn').click();}
  function settings(){
    $('draftInspector').classList.remove('rd-wide');
    openDialog('本月设置',`<section class="rx-actions rx-options"><button id="rxCutoff" type="button">在职／转正看哪一天</button><button id="rxRecalculate" type="button">重新读取已上传资料</button><button id="rxNewCalculation" type="button">另建一份核算</button><button id="rxTools" type="button">资料与规则工具</button></section>`);
    $('rxCutoff').onclick=()=>window.RecruitmentSpecial.open('',{type:'cutoff'});
    $('rxRecalculate').onclick=()=>{$('draftInspector').close();$('flowRecalculate').click();};
    $('rxNewCalculation').onclick=()=>window.RecruitmentTrial.newCalculation();
    $('rxTools').onclick=()=>{$('draftInspector').close();$('flowSettings').click();};
    ['rxCutoff','rxRecalculate','rxNewCalculation'].forEach(id=>$(id).disabled=locked());
  }
  const download=$('flowDownload').onclick;
  $('flowDownload').onclick=()=>{
    if(ui.busy)return;
    $('draftInspector').classList.remove('rd-wide');
    openDialog('导出与完成本月',`<section class="rx-actions"><div class="rx-options"><button id="rxDownload" type="button"><strong>下载本月核算表</strong><span>›</span></button><button id="rxComplete" type="button"><strong>确认本月结果</strong><span>›</span></button></div><details class="rx-secondary"><summary>其他导出</summary><button id="rxEvidence" class="rd-text-button" type="button">下载核算依据</button><a class="rd-text-button" href="${base()}/worksheet">下载可修改的底稿</a></details></section>`);
    $('rxDownload').onclick=()=>{$('draftInspector').close();download();};$('rxComplete').disabled=locked();$('rxComplete').onclick=()=>$('flowConfirmResult').click();$('rxEvidence').onclick=()=>$('flowEvidence').click();
  };
  $('flowAdjust').onclick=()=>open();$('flowMonthSettings').onclick=settings;$('flowProcessHistory').onclick=()=>window.RecruitmentReviewCenter.open('records');
  function refresh(){
    $('flowPrimary').hidden=true;$('flowAdjust').disabled=locked()||!ui.data?.rows.length;
    $('flowDownload').innerHTML='<svg class="rd-icon" aria-hidden="true"><use href="#icon-down"/></svg>导出与完成';
  }
  document.addEventListener('recruitment:render',refresh);document.addEventListener('recruitment:busy',refresh);document.addEventListener('recruitment:status',refresh);
  window.RecruitmentActions={open,run,settings};refresh();
})();
