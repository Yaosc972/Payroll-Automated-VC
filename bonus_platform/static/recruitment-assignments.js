(() => {
  'use strict';
  const w=window.RecruitmentWorkbench,{$,ui,e,base,request,openDialog}=w;
  const roles={recruiter:'招聘负责人',assistant:'协助招聘人'};
  const same=(a,b)=>(a?.name||'')===(b?.name||'')&&(a?.employeeId||'').toLowerCase()===(b?.employeeId||'').toLowerCase();
  const person=p=>p?.name?`${e(p.name)}${p.employeeId?` <span class="ra-id">${e(p.employeeId)}</span>`:''}`:'无';
  let sequence=0;
  const locked=()=>ui.busy||['running','cancelling'].includes(ui.prepareJob?.status)||ui.data?.activity?.archived;
  async function open(ids,options={}) {
    if(locked())return;
    const token=++sequence,url=base(),revision=ui.data.revision,rowIds=[...new Set(ids)];
    if(!rowIds.length)return;
    openDialog('更换招聘负责人／协助人','<p role="status">正在读取所选人员与原始资料…</p>');
    const post=(path,data)=>request(url+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision,...data})});
    const active=()=>token===sequence&&base()===url&&$('draftInspector').open;
    let data;
    try{data=await post('/assignments/context',{rowIds,sourceId:options.sourceId});}
    catch(err){if(active())$('draftInspectorBody').textContent=err.message;return;}
    if(!active())return;
    const singlePerson=rowIds.length===1;
    const edits=new Map();let currentSource=options.sourceId||'',loading=false,editing=null,basisSequence=0,collectEdit=null;
    openDialog('更换招聘负责人／协助人',`<form id="assignmentForm" class="ra-form">

      <details><summary>从原始资料带入分工</summary><div class="ra-basis"><label for="assignmentSource">选择文件</label><select id="assignmentSource"><option value="">请选择原始资料</option>${data.sources.map(s=>`<option value="${e(s.id)}" ${s.id===currentSource?'selected':''}>${e(s.name)}</option>`).join('')}</select><button id="assignmentImport" type="button" class="rd-text-button">导入新资料</button></div>
      <div id="assignmentSourceStatus" aria-live="polite"></div><button id="assignmentFromSource" type="button" class="rd-text-button" disabled>带入分工</button></details>
      <div class="ra-toolbar" ${singlePerson?'hidden':''}><span id="assignmentCount">尚未修改</span>${rowIds.length>1?'<button id="assignmentUniform" type="button" class="rd-button">统一更正所选人员</button>':''}</div>
      <div id="assignmentEditor"></div>
      <div class="ra-table-wrap" ${singlePerson?'hidden':''}><table class="rd-table ra-table"><thead><tr><th>员工</th><th>当前分工</th><th>更正后</th><th><span class="rd-sr-only">操作</span></th></tr></thead><tbody id="assignmentRows"></tbody></table></div>

      <p id="assignmentError" class="rd-error" role="status"></p>
      <div class="rw-sticky-actions"><button id="assignmentPreview" class="rd-button rd-primary" type="submit">查看修改结果</button></div>
    </form>`);
    $('draftInspector').classList.toggle('rd-wide',!singlePerson);
    const form=$('assignmentForm'),valid=()=>active()&&form.isConnected;
    function message(value,error=true){$('assignmentError').textContent=value;$('assignmentError').classList.toggle('rd-error',error);}
    function stage(id,patch){
      const p=data.people.find(p=>p.id===id),next={...(edits.get(id)||{}),...patch};
      for(const role of Object.keys(next))if(same(next[role],p.current[role])&&!p.unresolvedRoles.includes(role))delete next[role];
      if(Object.keys(next).length)edits.set(id,next);else edits.delete(id);
    }
    function draw(){
      $('assignmentCount').textContent=edits.size?`${edits.size} 人将更正 · 其余不变`:'尚未修改';
      $('assignmentRows').innerHTML=data.people.map(p=>{
        const change=edits.get(p.id),lines=values=>Object.keys(roles).map(role=>`<div class="ra-role"><span>${roles[role]}</span><div>${person(values[role])}</div></div>`).join('');
        return `<tr><td><strong>${e(p.name)}</strong><span class="ra-id">${e(p.employeeId||'')} · ${e(p.hireDate||'入职日待补')}</span></td><td>${lines(p.current)}</td><td>${change?lines({...p.current,...change}):'<span class="ra-unchanged">不修改</span>'}${p.warnings.map(t=>`<p class="ra-warning">${e(t)}</p>`).join('')}</td><td><button type="button" class="rd-text-button" data-assignment-edit="${e(p.id)}">${rowIds.length===1?'修改分工':'单独修改'}</button>${change?`<button type="button" class="rd-text-button" data-assignment-reset="${e(p.id)}">还原</button>`:''}</td></tr>`;
      }).join('');
      form.querySelectorAll('[data-assignment-edit]').forEach(b=>b.onclick=()=>edit([b.dataset.assignmentEdit]));
      form.querySelectorAll('[data-assignment-reset]').forEach(b=>b.onclick=()=>{edits.delete(b.dataset.assignmentReset);draw();});
      $('assignmentPreview').disabled=loading||(!singlePerson&&(!edits.size||!!editing))||(!!currentSource&&!!data.missingAttachments.length)||locked();
      $('assignmentFromSource').disabled=loading||!currentSource||!!data.missingAttachments.length||(!singlePerson&&!!editing)||!data.people.some(p=>Object.keys(p.proposal).length);
    }
    function sourceStatus(){
      const missing=data.missingAttachments;
      const matched=data.people.filter(p=>Object.keys(p.proposal).length).length;
      $('assignmentSourceStatus').innerHTML=missing.length?`<div class="ra-warning-box"><strong>这份审批还缺 ${missing.length} 份附件</strong><p>${missing.map(e).join('、')}</p><p>先导入引用附件，才能按附件核对分工。</p></div>`:currentSource?`<p class="ra-source-link"><a href="${e(url+'/sources/'+currentSource)}" target="_blank" rel="noopener">查看原件 ↗</a> <span class="rd-badge">${matched?`已匹配 ${matched} 人`:'未匹配分工'}</span></p>`:'';
    }
    $('assignmentImport').onclick=()=>{
      if(edits.size&&!confirm('尚未保存更正。离开后需要重新选择分工，是否先去导入资料？'))return;
      $('draftInspector').close();w.setView('sources');$('flowUpload')?.click();
    };
    $('assignmentSource').onchange=async()=>{
      const next=$('assignmentSource').value,seq=++basisSequence;loading=true;message('');draw();
      try{
        const reply=await post('/assignments/context',{rowIds,sourceId:next||undefined});
        if(!valid()||seq!==basisSequence)return;
        data=reply;currentSource=next;sourceStatus();
      }catch(err){if(valid()&&seq===basisSequence){$('assignmentSource').value=currentSource;message(err.message);}}
      finally{if(valid()&&seq===basisSequence){loading=false;draw();}}
    };
    $('assignmentFromSource').onclick=()=>{data.people.forEach(p=>stage(p.id,p.proposal));if(singlePerson){editing=null;edit(rowIds);}message('已带入分工。',false);draw();};
    function picker(role,initial){
      const root=document.createElement('div');root.className='ra-picker';
      root.innerHTML=`<label for="assignment-${role}">${roles[role]}</label><input id="assignment-${role}" autocomplete="off" placeholder="输入姓名或工号搜索" value="${e(initial?.name||'')}"/><div class="ra-options" aria-live="polite"></div><details><summary>工号 <span class="ra-picked-id">${e(initial?.employeeId||'选人后自动带入')}</span></summary><label for="assignment-${role}-id" class="rd-sr-only">${roles[role]}工号</label><input id="assignment-${role}-id" placeholder="无工号可留空" value="${e(initial?.employeeId||'')}"/></details>`;
      const name=root.querySelector('input'),id=root.querySelector('details input'),hint=root.querySelector('.ra-picked-id'),list=root.querySelector('.ra-options');let touched=false,querySequence=0,timer;
      id.oninput=()=>{touched=true;hint.textContent=id.value||'无工号';};
      name.oninput=()=>{
        touched=true;id.value='';hint.textContent='选人后自动带入';list.innerHTML='';clearTimeout(timer);
        const seq=++querySequence,q=name.value.trim();if(!q)return;
        timer=setTimeout(async()=>{
          try{
            const reply=await request(url+'/people?revision='+revision+'&q='+encodeURIComponent(q));
            if(!valid()||!root.isConnected||seq!==querySequence)return;
            list.innerHTML=reply.people.length?reply.people.map((p,i)=>`<button type="button" data-choice="${i}">${e(p.name)} <span>${e(p.employeeId)}</span></button>`).join(''):'<p>未找到，可直接填写姓名。</p>';
            list.querySelectorAll('button').forEach(b=>b.onclick=()=>{const p=reply.people[Number(b.dataset.choice)];name.value=p.name;id.value=p.employeeId;hint.textContent=p.employeeId;list.innerHTML='';});
          }catch(err){if(valid()&&root.isConnected&&seq===querySequence)list.textContent=err.message;}
        },250);
      };
      return {root,value:()=>touched?{name:name.value.trim(),employeeId:id.value.trim()}:undefined};
    }
    function edit(targets){
      if(editing){message('请先保留或取消当前编辑，再修改其他人员。');return;}
      editing=targets;message('');const single=targets.length===1,p=data.people.find(p=>p.id===targets[0]);
      const current=single?{...p.current,...edits.get(p.id)}:{};
      const root=$('assignmentEditor');
      root.innerHTML=`<section class="ra-editor"><div class="ra-editor-heading"><strong>${single?e(p.name):`统一更正 ${targets.length} 人`}</strong>${single?`<span>${e(p.employeeId||'')} · ${e(p.hireDate||'入职日待补')}</span>`:''}</div><div class="ra-picker-grid"></div><label class="rd-choice"><input id="assignmentNoAssistant" type="checkbox"/>无协助招聘人</label>${singlePerson?'':`<div class="ra-editor-actions"><button id="assignmentCancelEdit" type="button" class="rd-text-button">取消</button><button id="assignmentKeepEdit" type="button" class="rd-button">用于所选人员</button></div>`}${single?p.warnings.map(t=>`<p class="ra-warning">${e(t)}</p>`).join(''):''}</section>`;
      const pickers=Object.fromEntries(Object.keys(roles).map(role=>[role,picker(role,current[role])]));
      Object.values(pickers).forEach(p=>root.querySelector('.ra-picker-grid').append(p.root));
      const close=()=>{editing=null;collectEdit=null;root.innerHTML='';draw();};
      $('assignmentCancelEdit')?.addEventListener('click',close);
      $('assignmentNoAssistant').onchange=ev=>{pickers.assistant.root.querySelectorAll('input,button').forEach(i=>i.disabled=ev.target.checked);};
      collectEdit=()=>{
        const patch={};for(const role of Object.keys(roles)){const value=pickers[role].value();if(role==='assistant'&&$('assignmentNoAssistant').checked)patch[role]=null;else if(value){if(!value.name){message('请填写'+roles[role]+'姓名；取消协助分工请勾选“无协助招聘人”。');return false;}patch[role]=value;}}
        if(singlePerson&&!$('assignmentNoAssistant').checked&&edits.get(targets[0])?.assistant===null&&current.assistant&&!patch.assistant)patch.assistant=current.assistant;
        targets.forEach(id=>stage(id,patch));message('');return true;
      };
      $('assignmentKeepEdit')?.addEventListener('click',()=>{if(collectEdit())close();});
      draw();root.querySelector('input')?.focus();
    }
    $('assignmentUniform')?.addEventListener('click',()=>edit(rowIds));
    form.onsubmit=async ev=>{
      ev.preventDefault();if(locked()||loading||(!singlePerson&&editing))return;
      if(singlePerson&&collectEdit&&!collectEdit())return;
      if(!edits.size){message('尚未修改招聘分工。');return;}
      loading=true;draw();message('正在核对人员分配和奖金变化…',false);
      const finish=window.RecruitmentInteractions.pending($('assignmentPreview'),'正在核算…',form);if(!finish){loading=false;draw();return;}
      try{
        const preview=await post('/assignments/preview',{sourceId:currentSource||undefined,basisType:currentSource?undefined:'manual',
          assignments:[...edits].map(([rowId,changes])=>({rowId,...changes}))});
        finish();if(!valid())return;
        const nodes=[...$('draftInspectorBody').childNodes];
        window.RecruitmentReviewExtension.showPreview(preview,()=>{if(!active())return;openDialog('更换招聘负责人／协助人','');$('draftInspectorBody').replaceChildren(...nodes);$('draftInspector').classList.toggle('rd-wide',!singlePerson);draw();},()=>document.dispatchEvent(new CustomEvent('recruitment:assignments-applied')));
      }catch(err){if(valid())message(err.message);}
      finally{finish();loading=false;if(valid())draw();}
    };
    sourceStatus();draw();if(rowIds.length===1)edit(rowIds);
  }
  $('draftInspector').addEventListener('close',()=>sequence++);
  function selectable(rows){
    const table=$('draftContent').querySelector('.flow-worksheet');if(!table)return;
    table.classList.add('ra-selectable');
    const ids=new Set(ui.data.rows.map(r=>r.id));for(const id of ui.selected)if(!ids.has(id))ui.selected.delete(id);
    const th=document.createElement('th');th.className='ra-select-cell';
    if(table.classList.contains('flow-ledger')){
      th.rowSpan=2;
      const col=document.createElement('col');col.style.width='42px';table.querySelector('colgroup').prepend(col);
    }
    th.innerHTML='<input type="checkbox" id="assignmentSelectPage" aria-label="选择本页人员"/>';
    table.querySelector('thead tr').prepend(th);
    table.querySelectorAll('tbody tr').forEach((tr,i)=>{
      const r=rows[i],td=document.createElement('td');td.className='ra-select-cell';
      const name=ui.data.rows.find(p=>p.id===r.id)?.values.姓名||'员工';
      td.innerHTML=`<input type="checkbox" data-assignment-select="${e(r.id)}" aria-label="选择 ${e(name)}" ${ui.selected.has(r.id)?'checked':''}/>`;tr.prepend(td);
    });
    const bar=document.createElement('div');bar.className='flow-assignment-selection';
    bar.innerHTML='<span id="assignmentSelectionCount"></span><button id="assignmentSelectionEdit" type="button" class="rd-button">更换招聘负责人／协助人</button><button id="assignmentSelectionClear" type="button" class="rd-text-button">清除选择</button>';
    table.before(bar);
    function sync(){
      const checked=rows.filter(r=>ui.selected.has(r.id)).length;
      th.querySelector('input').checked=checked===rows.length;
      th.querySelector('input').indeterminate=checked>0&&checked<rows.length;
      bar.hidden=!ui.selected.size;$('assignmentSelectionCount').textContent=`已选 ${ui.selected.size} 人`;
      table.querySelectorAll('[data-assignment-select]').forEach(c=>{c.checked=ui.selected.has(c.dataset.assignmentSelect);c.disabled=locked();});
      th.querySelector('input').disabled=$('assignmentSelectionEdit').disabled=locked();
    }
    th.querySelector('input').onchange=ev=>{rows.forEach(r=>ev.target.checked?ui.selected.add(r.id):ui.selected.delete(r.id));sync();};
    table.querySelectorAll('[data-assignment-select]').forEach(c=>c.onchange=()=>{c.checked?ui.selected.add(c.dataset.assignmentSelect):ui.selected.delete(c.dataset.assignmentSelect);sync();});
    $('assignmentSelectionEdit').onclick=()=>open([...ui.selected]);
    $('assignmentSelectionClear').onclick=()=>{ui.selected.clear();sync();};sync();
  }
  document.addEventListener('recruitment:busy',()=>document.querySelectorAll('#assignmentSelectPage,[data-assignment-select],#assignmentSelectionEdit,#flowEditAssignment').forEach(c=>c.disabled=locked()));
  window.RecruitmentAssignments={open,selectable};
})();
