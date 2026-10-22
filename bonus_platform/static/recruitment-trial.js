(() => {
  'use strict';
  const w=window.RecruitmentWorkbench;
  const {$,ui,e,request,base,openDialog,adopt,amount}=w;
  const post=(url,data)=>request(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  const monthText=m=>m?`${Math.floor(m/100)}年${m%100}月`:'尚未安排';
  const currentId=()=>new URLSearchParams(location.search).get('trial')||'';
  const activityId=()=>new URLSearchParams(location.search).get('activity')||'';
  function remember(month,id){
    try{
      const key='recruitment-calculation-records'+(activityId()?':'+activityId():'');
      const records=JSON.parse(localStorage.getItem(key)||'{}');
      records[month]=id;localStorage.setItem(key,JSON.stringify(records));
    }catch{/* A blocked or full browser store does not prevent opening a record. */}
  }
  function navigate(t,view='rows'){
    const month=String(t.month),query=new URLSearchParams({month:month.slice(0,4)+'-'+month.slice(4),view});
    if(t.id)query.set('trial',t.id);
    if(activityId())query.set('activity',activityId());
    remember(t.month,t.id||'');location.href='recruitment.html?'+query;
  }
  function refresh(){
    if(!ui.data)return;
    remember(ui.data.month,currentId());
    $('trialName').textContent=ui.data.trial?.name||'原月度草稿';
    $('trialRules').textContent=ui.data.strictInputs?(ui.data.baseline?(ui.data.ruleValidation.passed?'规则检查通过':'规则检查未通过'):'待选择期初'):'尚未通过独立试算验收';
    $('trialRules').classList.toggle('rt-pass',!!ui.data.ruleValidation.passed);
    $('trialRules').onclick=ruleProblems;
    ['trialNew','trialChoose','trialReference'].forEach(id=>$(id).disabled=ui.busy);
  }
  function ruleProblems(){
    const check=ui.data.ruleValidation;
    if(!ui.data.strictInputs){openDialog('规则检查','<p>此草稿包含历史操作，不能用于证明从原始材料独立核算通过。请新建独立试算批次。</p>');return;}
    openDialog('规则检查',`<p>${ui.data.baseline?'按原始事实与适用制度检查，线下逐笔核对另行显示。':'先添加上月台账，并在「资料与审批」中选为期初。'}</p><label>查看范围<select id="ruleScope"><option value="current">本月已安排</option><option value="new">本月入职</option><option value="all">全部台账</option></select></label><div id="ruleProblemRows"></div><div class="rd-dialog-actions"><button id="rulePrev" class="rd-button">上一页</button><span id="rulePage"></span><button id="ruleNext" class="rd-button">下一页</button></div>`);
    let page=1;
    function show(){const scope=$('ruleScope').value;const rows=(check.problems||[]).filter(p=>{const r=ui.data.rows.find(r=>r.id===p.rowId);return scope==='all'||scope==='new'?scope==='all'||(r?.values.入职日期||'').slice(0,7).replace('-','')===String(ui.data.month):!!r?.calculation[p.kind].currentAmount;});const pages=Math.ceil(rows.length/40)||1;page=Math.min(page,pages);
      $('ruleProblemRows').innerHTML=rows.slice((page-1)*40,page*40).map(p=>`<article class="rt-rule-item"><strong>${e(p.name)} · ${p.kind==='recruitment'?'招聘奖金':'内推奖金'}</strong><p>${e(p.reasons.join('；'))}</p><button class="rd-text-button" data-rule-row="${p.rowId}">查看资料与计算</button></article>`).join('')||'<p>当前范围没有规则问题。</p>';
      $('rulePage').textContent=`${rows.length} 项 · 第 ${page} / ${pages} 页`;$('rulePrev').disabled=page===1;$('ruleNext').disabled=page===pages;document.querySelectorAll('[data-rule-row]').forEach(b=>b.onclick=()=>w.inspector(b.dataset.ruleRow));
    }
    $('ruleScope').onchange=()=>{page=1;show();};$('rulePrev').onclick=()=>{page--;show();};$('ruleNext').onclick=()=>{page++;show();};show();
  }
  function newCalculation(selectedMonth){
    if(ui.busy)return;
    const initial=typeof selectedMonth==='string'?selectedMonth:$('draftMonth').value;
    openDialog('新建核算',`<form id="trialForm"><div class="ra-month-field"><label for="trialMonth">核算月份</label><input id="trialMonth" type="month" required value="${e(initial)}" /></div><label id="trialTitleLabel" hidden>名称（可选）<input id="trialTitle" maxlength="60" placeholder="例如：7 月重新核算" /></label><p id="trialNewNotice" role="status">正在读取本月记录…</p><p id="trialNewLimit"></p><p id="trialError" role="status" class="rd-error"></p><button id="trialCreate" class="rd-button rd-primary" type="submit" disabled>创建并导入资料</button></form>`);
    const form=$('trialForm'),monthInput=$('trialMonth'),title=$('trialTitle'),nameLabel=$('trialTitleLabel'),notice=$('trialNewNotice'),limit=$('trialNewLimit'),error=$('trialError'),button=$('trialCreate');
    if(activityId()){monthInput.value=$('draftMonth').value;monthInput.disabled=true;$('draftInspectorTitle').textContent='重新核算';}
    window.RecruitmentUI?.monthPicker(monthInput);
    let sequence=0,lastPlan=null;
    const unused=data=>data.revision===0&&!data.sources.length&&!data.rows.length;
    function explain(data){
      const empty=unused(data);lastPlan={month:data.month,empty,opening:data.previousConfirmed||null};nameLabel.hidden=empty;
      notice.textContent=empty?'本月还没有核算资料，开始本月核算。':'本月已有核算记录，新表保留原记录，可重新核算和导出。';
      limit.textContent=empty?(data.previousAccepted?'整理资料时自动承接上月已确认结果，再补充本月资料。':'请导入上月核算表和本月原始资料。'):data.previousConfirmed?`新表自动带入${monthText(data.previousConfirmed.month)}最新已确认结果，再补充本月资料；核对后可采用为本月结果。`:'核对完成后可采用为本月结果，供下月承接；采用前会保留原结果。';
    }
    async function inspect(){
      const check=++sequence,value=monthInput.value;lastPlan=null;button.disabled=true;error.textContent='';nameLabel.hidden=true;limit.textContent='';
      if(!/^20\d{2}-(0[1-9]|1[0-2])$/.test(value)){notice.textContent='请选择核算月份。';return;}
      notice.textContent='正在读取本月记录…';
      try{const data=await request('/api/recruitment/drafts/'+value.replace('-',''));if(check!==sequence||!form.isConnected)return;explain(data);}
      catch(err){if(check!==sequence||!form.isConnected)return;notice.textContent='未能读取本月记录，请重试。';error.textContent=err.message;}
      finally{if(check===sequence&&form.isConnected)button.disabled=false;}
    }
    monthInput.onchange=inspect;
    form.onsubmit=async ev=>{
      ev.preventDefault();const value=monthInput.value,month=Number(value.replace('-','')),previous=lastPlan;
      if(!/^20\d{2}-(0[1-9]|1[0-2])$/.test(value))return;
      ++sequence;button.disabled=true;monthInput.disabled=true;error.textContent='';
      try{
        const data=await request('/api/recruitment/drafts/'+month);
        if(!form.isConnected||monthInput.value!==value)return;
        explain(data);
        if(!previous||previous.month!==month||previous.empty!==unused(data)){error.textContent='本月记录已更新，请核对上方说明后继续。';return;}
        if(previous.opening?.revision!==data.previousConfirmed?.revision){error.textContent='上月核算结果已更新，请核对上方说明后继续。';return;}
        if(unused(data)){navigate({month},'sources');return;}
        const opening=data.previousConfirmed;
        navigate(await post('/api/recruitment/trials',{month,name:title.value.trim(),...(opening?{opening:{month:opening.month,revision:opening.revision}}:{})}),'sources');
      }catch(err){if(form.isConnected)error.textContent=err.message;}
      finally{if(form.isConnected){button.disabled=false;monthInput.disabled=!!activityId();}}
    };
    inspect();
  }
  async function choose(){
    if(ui.busy)return;
    openDialog('历史核算','<p>正在读取…</p>');
    try{
      const rows=await request('/api/recruitment/trials'),month=ui.data?.month||Number($('draftMonth').value.replace('-',''));
      const months=activityId()?[month]:[...new Set([...$('draftMonth').options].map(o=>Number(o.value.replace('-',''))).concat(rows.map(t=>t.month),month))].sort((a,b)=>b-a);
      openDialog('历史核算',`<label>核算月份<select id="trialHistoryMonth">${months.map(m=>`<option value="${m}" ${m===month?'selected':''}>${monthText(m)}</option>`).join('')}</select></label><div id="trialHistoryRows" class="rt-trial-list"></div><button id="trialHistoryNew" class="rd-text-button" type="button">新建核算</button>`);
      function show(){
        const chosen=Number($('trialHistoryMonth').value),monthlyCurrent=chosen===month&&!currentId();
        const records=rows.filter(t=>t.month===chosen);
        $('trialHistoryRows').innerHTML=`<button class="rd-button" type="button" id="trialMonthlyRecord" ${monthlyCurrent?'disabled aria-current="true"':''}><strong>${monthText(chosen)}月度核算</strong><span>${monthlyCurrent?'当前记录':'打开'}</span></button>`+records.map(t=>{
          const selected=t.id===currentId();
          return `<button class="rd-button" type="button" data-trial="${e(t.id)}" ${selected?'disabled aria-current="true"':''}><strong>${e(t.name)}</strong><span>${selected?'当前记录 · ':''}${e(t.createdAt.replace('T',' '))}</span></button>`;
        }).join('');
        $('trialMonthlyRecord').onclick=()=>navigate({month:chosen});
        document.querySelectorAll('[data-trial]').forEach(b=>b.onclick=()=>navigate(records.find(t=>t.id===b.dataset.trial)));
      }
      $('trialHistoryMonth').onchange=show;$('trialHistoryNew').onclick=()=>{const chosen=$('trialHistoryMonth').value;newCalculation(chosen.slice(0,4)+'-'+chosen.slice(4));};show();
    }catch(err){$('draftInspectorBody').textContent=err.message;}
  }
  function installments(row,revision,target){
    const nodes=['recruitment','referral'].flatMap(k=>row.calculation[k].nodes.map(n=>({...n,kind:k})));
    const selected=target&&nodes.find(n=>n.kind===target.kind&&`${n.role} · ${n.label}`===target.item);
    if(selected&&!selected.openingLocked){plan(row,selected,revision);return;}
    openDialog(`${row.values.姓名} · 改发放月份／暂缓发放`,`<div class="rt-installments">${nodes.map(n=>`<article><div><strong>${n.kind==='recruitment'?'招聘奖金':'内推奖金'} · ${e(n.label)}</strong><b>${e(amount(n.amount,n.currency))}</b></div><p>${e(n.recipientName||n.role)} · 规则到期 ${e(n.dueDate||'待转正')}</p><div><span>${n.openingLocked?'期初已安排':e(n.scheduleText||n.status)} · ${monthText(n.scheduledMonth)}</span>${!n.openingLocked?`<button class="rd-text-button" data-plan="${n.id}">调整</button>`:''}</div>${n.issues.length?`<p class="rd-error">${e(w.label(n.issues.join('；')))}</p>`:''}</article>`).join('')||'<p>尚未形成可安排分期，请先核对人员资料与适用规则。</p>'}</div>`);
    document.querySelectorAll('[data-plan]').forEach(b=>b.onclick=()=>plan(row,nodes.find(n=>n.id===b.dataset.plan),revision));
  }
  function plan(row,node,revision){
    openDialog(`${row.values.姓名} · ${node.label}`,`<form id="planForm"><div class="rt-plan-amount"><span>规则计算金额</span><strong>${e(amount(node.amount,node.currency))}</strong></div><p>规则到期 ${e(node.dueDate||'待转正')} · 当前 ${monthText(node.scheduledMonth)}</p><label>这笔奖金怎么发<select id="planAction"><option value="schedule">改到指定月份</option><option value="defer">暂缓发放</option><option value="reset">恢复原安排</option></select></label><label id="planMonthLabel">安排月份<input id="planMonth" type="month" value="${$('draftMonth').value}" /></label><p id="planError" role="status" class="rd-error"></p><button class="rd-button rd-primary" type="submit">查看调整结果</button></form>`);
    $('planAction').onchange=()=>{$('planMonthLabel').hidden=$('planAction').value!=='schedule';};
    const planRoot=$('planForm'),url=base();
    $('planForm').onsubmit=async ev=>{
      ev.preventDefault();if(ui.busy||url!==base())return;
      const finish=window.RecruitmentInteractions.pending(ev.submitter,'正在核算…',planRoot);if(!finish)return;
      try{
        const formNodes=[...$('draftInspectorBody').childNodes];
        const p=await post(url+'/installment-previews',{revision,rowId:row.id,nodeId:node.id,action:$('planAction').value,month:Number($('planMonth').value.replace('-','')),basisType:'manual'});
        finish();if(!planRoot.isConnected||!$('draftInspector').open||url!==base())return;
        openDialog('确认分期安排',`<div class="rt-plan-amount"><span>${e(p.name)} · ${e(p.label)}</span><strong>${e(amount(p.amount,p.currency))}</strong></div><p>${monthText(p.beforeMonth)} → ${p.action==='schedule'?monthText(p.month):p.action==='defer'?'暂缓安排':'恢复规则安排'}</p><p id="planError" class="rd-error" role="status"></p><button id="planBack" class="rd-button" type="button">返回修改</button><button id="planApply" class="rd-button rd-primary">确认保存</button>`);
        $('planBack').onclick=()=>{openDialog(`${row.values.姓名} · ${node.label}`,'');$('draftInspectorBody').replaceChildren(...formNodes);formNodes.forEach(n=>n.querySelectorAll?.('button').forEach(b=>b.disabled=false));};
        const apply=$('planApply'),back=$('planBack'),failure=$('planError');
        apply.onclick=async()=>{if(ui.busy||url!==base())return;const finishSave=window.RecruitmentInteractions.pending(apply,'正在保存…',$('draftInspectorBody'));if(!finishSave)return;w.busy(true);w.status('正在保存分期安排');
          try{const saved=await post(url+`/installment-previews/${p.id}/apply`,{revision:p.revision});if(url===base()){adopt(saved);if(apply.isConnected)$('draftInspector').close();}}
          catch(err){if(failure.isConnected)failure.textContent=err.message;w.status(err.message,true);}finally{finishSave();w.busy(false);}};
      }catch(err){if(planRoot.isConnected)$('planError').textContent=err.message;}finally{finish();}
    };
  }
  $('trialNew').onclick=newCalculation;$('trialChoose').onclick=choose;
  $('trialReference').onclick=()=>$('trialReferenceFile').click();
  $('trialReferenceFile').onchange=async ev=>{await w.upload([...ev.target.files],true);ev.target.value='';window.RecruitmentReviewCenter.open('differences');};
  document.addEventListener('recruitment:render',refresh);document.addEventListener('recruitment:busy',refresh);
  window.RecruitmentTrial={newCalculation,choose,installments,ruleProblems};refresh();
})();
