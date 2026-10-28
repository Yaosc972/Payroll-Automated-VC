(() => {
  'use strict';
  const w=window.RecruitmentWorkbench,{$,ui,e,base,request,openDialog}=w;
  const titles={adjustment:'补发／扣回奖金',exception:'离职／未转正仍需发放',exclude:'不发奖金',cutoff:'在职／转正看哪一天',revoke:'撤销安排',history:'保留历史金额'};
  const kinds={recruitment:'招聘奖金',referral:'内推奖金'};
  const conditions={candidate_not_employed:'候选人不在职',recipient_not_employed:'领取人不在职',recipient_not_regularized:'推荐人未转正'};
  const modes={due:'分期到期日',month_end:'核算月末',date:'指定日期'};
  const option=(v,t,chosen='')=>`<option value="${e(v)}" ${v===chosen?'selected':''}>${e(t)}</option>`;
  const choices=(values,chosen='')=>Object.entries(values).map(([v,t])=>option(v,t,chosen)).join('');
  const field=(title,control)=>`<label>${title}${control}</label>`;
  const input=(id,extra='')=>`<input id="${id}" ${extra} />`;
  let sequence=0;
  const locked=()=>ui.busy||['running','cancelling'].includes(ui.prepareJob?.status)||ui.data?.activity?.archived;
  async function open(rowId='',options={}) {
    if(locked()||!ui.data)return;
    const typ=options.type||'adjustment';
    if(!rowId&&typ!=='cutoff'){window.RecruitmentActions.open('',{...options,action:typ});return;}
    const seq=++sequence,url=base(),revision=ui.data.revision,month=ui.data.month;
    $('draftInspector').classList.remove('rd-wide');
    openDialog(titles[typ],'<p role="status">正在读取…</p>');
    const loading=$('draftInspectorBody').firstElementChild;
    const active=()=>seq===sequence&&base()===url&&$('draftInspector').open;
    let data,currentRow;
    try{[data,currentRow]=await Promise.all([request(url+'/special'),rowId?request(url+'/rows/'+encodeURIComponent(rowId)).then(d=>d.row):Promise.resolve(null)]);}
    catch(err){if(active()&&loading.isConnected)loading.textContent=err.message;return;}
    if(!active()||!loading.isConnected)return;
    const peopleName=currentRow?.values.姓名||'';
    const conditionNames={candidate_not_employed:'允许候选人离职后发放',recipient_not_employed:'允许领取人离职后发放',recipient_not_regularized:'允许推荐人未转正时发放'};
    openDialog(titles[typ],`<section class="rs-panel">
      <nav class="rs-stepper" aria-label="调整步骤"><span data-rs-step="1" aria-current="step">1 填写调整</span><span data-rs-step="2">2 确认结果</span></nav>
      ${currentRow?`<div class="rs-person-summary"><strong>${e(peopleName)}</strong><span>${e(currentRow.values.工号||'无工号')} · ${e(currentRow.values.入职日期||'')}</span></div>`:''}
      ${options.recovery?historyBasis(options.recovery,url):''}
      ${options.recovery?`<p class="rs-history-reference">差额参考：${options.recovery.signedAmount==null?'待核对':e(w.amount(Math.abs(options.recovery.signedAmount),options.recovery.currency))}</p>`:''}
      <div id="rsStepOne">
        ${field('调整哪种奖金',`<select id="rsKind">${choices(kinds,options.kind||'recruitment')}</select>`)}
        ${typ==='adjustment'?`<div class="rs-grid">${field('怎么调整',`<select id="rsDirection">${choices({supplement:'补发',deduct:'扣回'})}</select>`)}${field('金额',input('rsAmount','type="number" step="0.01" min="0.01" inputmode="decimal" placeholder="填写金额"'))}</div><div class="rs-grid">${field('计入哪月',input('rsMonth',`type="month" value="${String(month).slice(0,4)}-${String(month).slice(4)}"`))}${field('发给谁','<select id="rsRole"></select>')}</div><div id="rsReceiver" class="rs-receiver"></div><details><summary>更换领取人</summary><div class="rs-grid">${field('领取人姓名',input('rsName'))}${field('领取人工号',input('rsEmployee'))}</div></details><details><summary>关联原奖金（选填）</summary><div>${field('对应哪笔奖金','<select id="rsNode"></select>')}</div></details>`:''}
        ${typ==='exception'?`${field('哪笔奖金需要发放','<select id="rsNode"></select>')}<p id="rsNodeInfo" class="rs-error"></p><div class="rs-conditions">${Object.entries(conditionNames).map(([k,t])=>`<label><input type="checkbox" data-rs-condition="${k}"/>${t}</label>`).join('')}</div>`:''}
        ${typ==='exclude'?field('不发哪一部分','<select id="rsExcludeRole"></select>'):''}
        ${typ==='cutoff'?`<p id="rsCurrentPolicy"></p>${field('在职和转正以哪天为准',`<select id="rsMode">${choices({due:'每笔奖金的到期日',month_end:'本月最后一天',date:'指定日期'})}</select>`)}${field('具体日期',input('rsDate','type="date"'))}`:''}
      </div>
      <p id="rsError" class="rs-error" role="alert"></p><div id="rsNavigation" class="rd-dialog-actions"><button id="rsPrevious" class="rd-button" type="button">返回</button><button id="rsPreview" class="rd-button rd-primary" type="button">查看调整结果</button></div><div id="rsPreviewArea" hidden></div>
    </section>`);
    const root=$('draftInspectorBody'),formRoot=root.firstElementChild;
    const valid=()=>active()&&formRoot.isConnected&&ui.data.revision===revision;
    const post=(path,body)=>request(url+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision,...body})});
    let step=1,previewData=null;
    const error=message=>{if(valid())$('rsError').textContent=message;};
    const node=()=>currentRow?.calculation[$('rsKind').value]?.nodes.find(n=>n.id===$('rsNode')?.value);
    function show(next){step=next;error('');$('rsStepOne').hidden=step!==1;$('rsNavigation').hidden=step===2;$('rsPreviewArea').hidden=step!==2;root.querySelectorAll('[data-rs-step]').forEach(el=>{if(Number(el.dataset.rsStep)===step)el.setAttribute('aria-current','step');else el.removeAttribute('aria-current');});root.scrollTop=0;$('draftInspector').scrollTop=0;}
    function recipient(){if(typ!=='adjustment')return;const role=$('rsRole').value,v=currentRow.values,n=node();
      $('rsName').value=n?.recipientName||v[role+'姓名']||'';$('rsEmployee').value=n?.recipientId||v[role+'工号']||'';receiver();}
    function receiver(){if(typ==='adjustment')$('rsReceiver').textContent=`${$('rsName').value||'领取人待填写'} · ${$('rsEmployee').value||'工号待填写'} · ${options.recovery?.currency||currentRow.calculation[$('rsKind').value].currency||'币种待核'}`;}
    function nodeChanged(){const n=node();if(typ==='adjustment'){if(n)$('rsRole').value=n.role;recipient();}if(typ==='exception')$('rsNodeInfo').textContent=n?[...(n.eligibilityReasons||[]),...(n.issues||[])].join('；'):'';}
    function kindChanged(){const kind=$('rsKind').value;
      if($('rsNode')){$('rsNode').innerHTML=option('',typ==='exception'?'请选择奖金':'不关联，单独补发或扣回')+(currentRow?.calculation[kind].nodes||[]).filter(n=>!n.adjustmentId).map(n=>option(n.id,`${n.role} · ${n.label} · ${n.recipientName||n.recipientId||'待核'} · ${n.amount} ${n.currency}`)).join('');}
      if(typ==='adjustment'){$('rsRole').innerHTML=(kind==='recruitment'?['招聘负责人','协助招聘人']:['推荐人']).map(r=>option(r,r)).join('');recipient();}
      if(typ==='exclude')$('rsExcludeRole').innerHTML=kind==='recruitment'?choices({'':'全部招聘奖金','招聘负责人':'只不发招聘负责人','协助招聘人':'只不发协助招聘人'}):choices({'':'全部内推奖金'});
      if(typ==='exception'){const c=root.querySelector('[data-rs-condition="recipient_not_regularized"]');c.closest('label').hidden=kind!=='referral';c.checked=false;}
      if(typ==='cutoff'){const policy=data.policies[kind];$('rsMode').value=policy.mode;$('rsDate').value=policy.date||'';$('rsDate').parentElement.hidden=policy.mode!=='date';$('rsCurrentPolicy').textContent=`当前：${modes[policy.mode]}${policy.date?' · '+policy.date:''}`;}
      nodeChanged();
    }
    $('rsKind').onchange=kindChanged;kindChanged();
    if(typ==='adjustment'&&options.recovery?.adjustmentAllowed!==false&&options.recovery){const r=options.recovery;
      $('rsDirection').value=r.signedAmount<0?'deduct':'supplement';$('rsAmount').value='';
      $('rsRole').value=r.role;$('rsName').value=r.recipientName||'';$('rsEmployee').value=r.recipientId||'';receiver();
    }
    if(typ==='adjustment'&&options.recipient){const r=options.recipient;$('rsRole').value=r.role;$('rsName').value=r.recipientName||'';$('rsEmployee').value=r.recipientId||'';receiver();}
    if($('rsRole'))$('rsRole').onchange=()=>{$('rsNode').value='';recipient();};
    if($('rsNode'))$('rsNode').onchange=nodeChanged;
    if($('rsName')){$('rsName').oninput=receiver;$('rsEmployee').oninput=receiver;}
    if($('rsMode'))$('rsMode').onchange=()=>{$('rsDate').parentElement.hidden=$('rsMode').value!=='date';};
    $('rsPrevious').onclick=()=>typ==='cutoff'?window.RecruitmentActions.settings():window.RecruitmentActions.open(rowId);
    $('rsPreview').onclick=async()=>{
      if(!valid()||locked())return;
      try{
        if(typ==='adjustment'){window.RecruitmentAdjustmentModel.signedAmount($('rsAmount').value,$('rsDirection').value);if(!$('rsMonth').value)throw new Error('请选择计入月份');if(!$('rsName').value.trim()||!$('rsEmployee').value.trim())throw new Error('请在「更换领取人」中补充姓名和工号');}
        if(typ==='exception'&&(!$('rsNode').value||!root.querySelector('[data-rs-condition]:checked')))throw new Error('请选择奖金和需要允许发放的情况');
        if(typ==='cutoff'&&$('rsMode').value==='date'&&!$('rsDate').value)throw new Error('请选择具体日期');
      }catch(err){error(err.message);return;}
      const kind=$('rsKind').value;
      let payload={type:typ,kind,rowId,month,basisType:'manual'};
      if(typ==='adjustment')payload=window.RecruitmentAdjustmentModel.adjustment({...payload,direction:$('rsDirection').value,amount:$('rsAmount').value,month:Number($('rsMonth').value.replace('-','')),role:$('rsRole').value,recipientName:$('rsName').value,recipientId:$('rsEmployee').value,currency:options.recovery?.currency||currentRow.calculation[kind].currency,nodeId:$('rsNode').value});
      if(typ==='adjustment'&&options.recovery)payload.recoveryKey=options.recovery.key;
      if(typ==='exception')Object.assign(payload,{nodeId:$('rsNode').value,conditions:[...root.querySelectorAll('[data-rs-condition]:checked')].map(x=>x.dataset.rsCondition)});
      if(typ==='cutoff')Object.assign(payload,{mode:$('rsMode').value,date:$('rsDate').value});
      if(typ==='exclude'){const role=$('rsExcludeRole').value;payload={basisType:'manual',edits:[],decisions:[{rowId,kind,action:'exclude',...(role?{role}:{})}]};}
      const finish=window.RecruitmentInteractions.pending($('rsPreview'),'正在核算…',formRoot);if(!finish)return;error('');
      try{
        previewData=await post(typ==='exclude'?'/previews':'/special/preview',payload);finish();if(!valid())return;
        const p=previewData;
        const cell=(n,other)=>n?`${e(w.amount(n.amount,n.currency))}<span>${e(n.recipientName||n.recipientId||'')} · ${e(n.scheduledMonth||'未安排')}</span>${n.status&&n.status!==other?.status?`<span>${e(n.status)}</span>`:''}${n.issues?.length&&JSON.stringify(n.issues)!==JSON.stringify(other?.issues||[])?`<details><summary>待处理 ${n.issues.length} 项</summary><p>${e(n.issues.join('；'))}</p></details>`:''}`:'无';
        const policySummary=typ==='cutoff'?`<p>${e(kinds[kind])}：${e(modes[data.policies[kind].mode])}${e(data.policies[kind].date||'')} → <strong>${e(modes[payload.mode])}${payload.mode==='date'?' · '+e(payload.date):''}</strong></p>`:'';
        const planSummary=typ==='adjustment'?`<p><strong>${payload.amount>0?'补发':'扣回'} ${e(w.amount(Math.abs(payload.amount),payload.currency))}</strong> · ${e(payload.recipientName)} · ${String(payload.month).slice(0,4)}年${Number(String(payload.month).slice(4))}月</p>`:typ==='exclude'?`<p>${e($('rsExcludeRole').selectedOptions[0].textContent)}</p>`:typ==='exception'?`<p>${e($('rsNode').selectedOptions[0].textContent)}</p><p>${payload.conditions.map(k=>e(conditionNames[k])).join('；')}</p>`:'';
        $('rsPreviewArea').innerHTML=`<section class="rs-impact"><h3>${e(titles[typ])}${p.people?` · ${p.people} 人`:""}</h3>${policySummary}${planSummary}${p.currentImpact.length?`<table><thead><tr><th>本月奖金</th><th>修改前</th><th>修改后</th></tr></thead><tbody>${p.currentImpact.map(x=>`<tr><td>${e(x.name)} · ${e(x.kind)}</td><td>${e(w.amount(x.before,x.beforeCurrency||x.currency))}</td><td><strong>${e(w.amount(x.after,x.currency))}</strong></td></tr>`).join('')}</tbody></table>`:'<p>本月合计不变。</p>'}${p.nodeImpact.length?`<details class="rs-preview-details"><summary>涉及的奖金 · ${p.nodeImpact.length} 笔</summary><div class="rs-impact-table"><table><thead><tr><th>奖金</th><th>修改前</th><th>修改后</th></tr></thead><tbody>${p.nodeImpact.map(n=>`<tr><td>${e(n.name)} · ${e(n.label)}</td><td>${cell(n.before,n.after)}</td><td>${cell(n.after,n.before)}</td></tr>`).join('')}</tbody></table></div></details>`:''}${(p.remainingIssues||[]).map(r=>`<p class="rs-error">${e(r.name)}：${e(r.reasons.join('；'))}</p>`).join('')}<p id="rsApplyError" class="rs-error" role="alert"></p><div class="rd-dialog-actions"><button id="rsBack" type="button" class="rd-button">返回修改</button><button id="rsApply" type="button" class="rd-button rd-primary">确认保存</button></div></section>`;
        show(2);window.RecruitmentInteractions.enter($('rsPreviewArea'));$('rsBack').onclick=()=>show(1);
        $('rsApply').onclick=async()=>{if(!valid()||locked())return;const savedButton=$('rsApply'),finishSave=window.RecruitmentInteractions.pending(savedButton,'正在保存…',formRoot);if(!finishSave)return;w.busy(true);w.status('正在保存奖金调整');
          try{const saved=await post((typ==='exclude'?'/previews/':'/special/previews/')+p.id+'/apply',{});if(base()===url){const close=valid();w.adopt(saved);if(close)$('draftInspector').close();w.status('调整已保存');}}
          catch(err){if(formRoot.isConnected)$('rsApplyError').textContent=err.message;w.status(err.message,true);}finally{finishSave();w.busy(false);}};
      }catch(err){error(err.message);}finally{finish();}
    };
  }
  const historyMonth=value=>/^\d{6}$/.test(String(value))?`${String(value).slice(0,4)}年${Number(String(value).slice(4))}月`:String(value||'月份待核对');
  function historyQuestion(r){
    if(r.historyOnly)return '原表已记录的往期调整';
    const notes=(r.originalNotes||[]).map(n=>n.text).join('；');
    const deduction=notes.match(/(\d{1,2})月(?:已)?(?:扣回|扣除)/);
    if(deduction)return `原表注明${Number(deduction[1])}月扣回，是否已结清？`;
    if(r.type==='removed_installment'&&/取消/.test(notes))return '原奖金取消后，是否已结清？';
    if(r.type==='overage')return '往期金额高于现行规则，是否保留原金额？';
    if(r.type==='recipient_changed')return '领取人变更后，原奖金是否已处理？';
    if(r.type==='unallocated_balance')return '剩余奖金应在哪月发放？';
    if(r.type==='opening_conflict'||r.signedAmount==null)return '历史分期存在冲突，应采用哪项记录？';
    return '往期奖金是否已结清？';
  }
  function historyBasis(r,url){
    const notes=new Map();
    for(const note of r.originalNotes||[]){
      const key=String(note.text||'').trim();if(!key)continue;
      if(!notes.has(key))notes.set(key,{text:key,refs:[]});
      notes.get(key).refs.push(...[].concat(note.sourceRef||[]).map(ref=>({...ref,column:ref.column||note.column})));
    }
    const noteMarkup=[...notes.values()].map(note=>{
      const refs=[...new Map(note.refs.filter(ref=>ref.sourceId).map(ref=>[[ref.sourceId,ref.sheet,ref.row,ref.column].join('|'),ref])).values()];
      return `<div class="rs-history-note"><p>${e(note.text)}</p>${refs.length?`<div class="rs-history-links">${refs.map(ref=>`<a href="${url}/sources/${e(ref.sourceId)}" target="_blank" rel="noopener">${e(ref.sheet||'查看原件')}${ref.row?' · 第 '+e(ref.row)+' 行':''}${ref.column?' · 第 '+e(ref.column)+' 列':''}</a>`).join('')}</div>`:''}</div>`;
    });
    const records=new Map();
    for(const record of [...(r.relatedRecords||[]),...(r.confirmedCorrections||[]).map(x=>({...x,confirmed:true})),...(r.relatedConfirmedArrangements||[]).map(x=>({...x,confirmed:true,relationship:'candidate'}))]){
      const key=record.id||record.adjustmentId||[record.month||record.scheduledMonth,record.amount,record.recipientId,record.type].join('|');
      if(!records.has(key))records.set(key,record);
    }
    const recordMarkup=[...records.values()].map(x=>{
      const state=x.active===false?'已撤销':x.sourceValid===false||x.issues?.length?'需重新核对':x.relationship==='candidate'?'待匹配分期':x.type==='history'?'已保留历史金额':x.confirmed?'已确认安排':'已安排';
      const amount=x.amount==null?'':`${x.amount<0?'扣回':'补发'} ${w.amount(Math.abs(x.amount),x.currency)}`;
      return `<li><div><strong>${e(historyMonth(x.month||x.scheduledMonth))}${amount?' · '+e(amount):''}</strong><span class="flow-status-tag">${e(state)}</span></div>${x.recipientName||x.recipientId?`<p>${e(x.recipientName||x.recipientId)}</p>`:''}${x.reason||x.issues?.length?`<p>${e([x.reason,...(x.issues||[])].filter(Boolean).join('；'))}</p>`:''}</li>`;
    });
    return `<div class="rs-history-basis">${noteMarkup.length?`<section class="rs-history-notes"><h4>原表备注</h4>${noteMarkup[0]}${noteMarkup.length>1?`<details><summary>其他备注与原件 · ${noteMarkup.length-1}</summary>${noteMarkup.slice(1).join('')}</details>`:''}</section>`:''}${recordMarkup.length?`<section class="rs-history-records"><h4>已有处理记录</h4><ul>${recordMarkup.join('')}</ul></section>`:'<p class="rs-history-missing">未关联到补扣记录</p>'}</div>`;
  }
  function historyCard(r,url){
    const status={adjusted:'已有足额补扣安排',retained:'已保留历史金额',partial:'已有部分补扣安排'}[r.resolution]||(r.historyOnly?'历史记录':({overage:'金额依据待核对',opening_conflict:'历史记录待核对',unallocated_balance:'待安排发放'}[r.type]||'结算结果待核实'));
    const missingPayee=!r.recipientId||!r.recipientName;
    return `<article class="rs-record rs-history-card" data-rs-history="${e(r.key)}"><header class="rs-history-heading"><div><strong>${e(r.name)}</strong><span>${e(kinds[r.kind])} · ${e(r.role)}</span></div><span class="flow-status-tag" ${!r.resolution&&!r.historyOnly?'data-tone="warning"':''}>${e(status)}</span></header>
      <h3 class="rs-history-question">${e(historyQuestion(r))}</h3>${historyBasis(r,url)}${r.historyOnly?'<p>历史记录不计入本月金额，实际扣回结果未核实。确需本月补扣时再登记。</p>':''}
      <table class="rs-history-amounts"><thead><tr><th>历史安排</th><th>现行规则金额</th><th>差额参考</th></tr></thead><tbody><tr><td>${e(w.amount(r.historyAmount,r.currency))}</td><td>${e(w.amount(r.currentAmount,r.currentRule.currency))}</td><td>${r.signedAmount==null?'待核对':e(w.amount(Math.abs(r.signedAmount),r.currency))}</td></tr></tbody></table>
      <details class="rs-history-installments"><summary>历史分期与原件</summary>${(r.openingFacts||[]).map(f=>`<p>${f.basisLabel?e(f.basisLabel)+' · ':''}${e(f.label)} · ${e(historyMonth(f.scheduledMonth))} · ${e(w.amount(f.amount,f.currency))} · ${e(f.recipientName||f.recipientId||'原领取人未关联')}${f.openingSource?.sourceId?` · <a href="${url}/sources/${e(f.openingSource.sourceId)}" target="_blank" rel="noopener">查看原件</a>`:''}</p>`).join('')}</details>
      <div class="rs-history-footer"><span>${missingPayee?'历史分期未关联领取人':`原领取人：${e(r.recipientName)}`}</span><div class="rd-dialog-actions">${r.type!=='unallocated_balance'&&!r.resolution&&!r.historyOnly?`<button class="rd-button" type="button" data-rs-retain="${e(r.key)}">保留历史金额</button>`:''}<button class="rd-button" type="button" data-rs-correct="${e(r.key)}" ${r.adjustmentAllowed===false||['adjusted','retained'].includes(r.resolution)||missingPayee?'disabled':''}>登记补发／扣回</button></div></div>${r.correctionReviewReason?`<p class="rs-error">${e(r.correctionReviewReason)}</p>`:''}</article>`;
  }
  async function review(item={}) {
    if(locked()||!ui.data)return;
    const seq=++sequence,url=base(),revision=ui.data.revision;
    $('draftInspector').classList.remove('rd-wide');
    openDialog('核对往期奖金','<p role="status">正在读取…</p>');
    const active=()=>seq===sequence&&base()===url&&$('draftInspector').open&&ui.data.revision===revision;
    try {
      const data=await request(url+'/special');if(!active())return;
      const ids=new Set(item.rowIds||item.rows?.map(r=>r.rowId||r.id)||[]);
      const recoveries=(data.historyRecoveries||data.recoveries).filter(r=>!ids.size||ids.has(r.rowId));
      const pending=recoveries.filter(r=>!['adjusted','retained'].includes(r.resolution)),completed=recoveries.filter(r=>['adjusted','retained'].includes(r.resolution));
      openDialog('核对往期奖金',`<section class="rs-panel">${pending.map(r=>historyCard(r,url)).join('')}${completed.length?`<details class="rs-history-completed" ${!pending.length?'open':''}><summary>已有处理安排 · ${completed.length} 项</summary>${completed.map(r=>historyCard(r,url)).join('')}</details>`:''}${!recoveries.length?'<p>该事项的历史差异已处理。</p>':''}<p id="rsHistoryError" class="rs-error" role="alert"></p><section id="rsHistoryPreview"></section></section>`);
      const root=$('draftInspectorBody'),controls=disabled=>root.querySelectorAll('button').forEach(b=>b.disabled=disabled||b.dataset.rsCorrect&&!recoveries.some(r=>r.key===b.dataset.rsCorrect&&r.adjustmentAllowed!==false&&!['adjusted','retained'].includes(r.resolution)&&r.recipientId&&r.recipientName));
      root.querySelectorAll('[data-rs-correct]').forEach(b=>b.onclick=()=>{if(!active()||locked())return;const r=recoveries.find(r=>r.key===b.dataset.rsCorrect);open(r.rowId,{type:'adjustment',kind:r.kind,recovery:r});});
      root.querySelectorAll('[data-rs-retain]').forEach(b=>b.onclick=async()=>{
        if(!active()||locked())return;const r=recoveries.find(r=>r.key===b.dataset.rsRetain),finish=window.RecruitmentInteractions.pending(b,'正在核算…',root);if(!finish)return;
        try {
          const p=await request(url+'/special/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision,type:'history',rowId:r.rowId,kind:r.kind,recoveryKey:r.key,fingerprint:r.historyFingerprint||r.fingerprint,outcome:'retain'})});finish();if(!active())return;
          $('rsHistoryPreview').innerHTML=`<section class="rs-impact"><h3>保留 ${e(r.name)} 的历史金额</h3><p>保留 ${e(w.amount(r.historyAmount,r.currency))} 的历史安排，关闭这项历史差异。</p><dl class="rs-history-result"><div><dt>本月金额</dt><dd>不变</dd></div><div><dt>支付／扣回结果</dt><dd>仍未核实</dd></div></dl><div class="rd-dialog-actions"><button id="rsHistoryBack" class="rd-button" type="button">返回</button><button id="rsHistoryApply" class="rd-button rd-primary" type="button">保存并关闭差异</button></div></section>`;
          $('rsHistoryPreview').scrollIntoView({block:'nearest'});$('rsHistoryBack').onclick=()=>review(item);
          $('rsHistoryApply').onclick=async()=>{
            if(!active()||locked())return;const finishSave=window.RecruitmentInteractions.pending($('rsHistoryApply'),'正在保存…',root);if(!finishSave)return;w.busy(true);w.status('正在保存历史差异处理结果');
            try {const saved=await request(url+'/special/previews/'+p.id+'/apply',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision})});if(base()===url){const close=active();w.adopt(saved);if(close)$('draftInspector').close();w.status('历史差异已关闭，本月金额不变');}}
            catch(err){if(active()){$('rsHistoryError').textContent=err.message;controls(false);}}
            finally{finishSave();w.busy(false);}
          };
        } catch(err){if(active()){$('rsHistoryError').textContent=err.message;}}finally{finish();}
      });
    } catch(err){if(active())$('draftInspectorBody').textContent=err.message;}
  }
  function snapshot(n){return n?`${e(n.recipientName||n.recipientId||'')} ${e(w.amount(n.amount,n.currency))} · ${e(n.scheduledMonth||'未安排')} · ${e(n.status||'')} ${e((n.issues||[]).join('；'))}`:'无';}
  async function records(){if(!ui.data||ui.busy)return;const seq=++sequence,url=base();openDialog('奖金调整记录','<p>正在读取…</p>');
    const active=()=>seq===sequence&&base()===url&&$('draftInspector').open;
    try{const data=await request(url+'/special');if(!active())return;
      openDialog('奖金调整记录',`<section class="rs-panel"><div class="rd-dialog-actions"><button id="rsNew" class="rd-button" type="button">新增调整</button><button id="rsPolicy" class="rd-button" type="button">在职／转正判断日期</button></div>${data.records.length?data.records.slice().reverse().map(r=>`<article class="rs-record"><strong>${e(titles[r.type])} · ${e(r.name||kinds[r.kind])}</strong><span>${e(r.month)} · ${!r.active?'已撤销':!r.sourceValid||r.issues.length?'待重新核对':'已采用'}</span><p>${e(r.type==='adjustment'?`${r.recipientName} ${w.amount(r.amount,r.currency)}`:r.type==='exception'?r.conditions.map(k=>conditions[k]).join('、'):r.type==='history'?`${r.recovery.role} · 历史 ${w.amount(r.recovery.historyAmount,r.recovery.currency)} · 当前规则 ${w.amount(r.recovery.currentAmount,r.recovery.currentRule.currency)}`:modes[r.mode]+(r.date||''))}</p><p>${e(r.reason)}</p>${r.issues.length?`<p class="rd-error">${e(r.issues.join('；'))}</p>`:''}${r.sourceId?`<a href="${url}/sources/${e(r.sourceId)}" target="_blank" rel="noopener">查看原件</a>`:''}${r.confirmed?`<span>已确认历史安排</span><button class="rd-text-button" type="button" data-rs-amend="${e(r.id)}" ${locked()?'disabled':''}>补发／扣回更正</button>`:''}${r.active&&!r.confirmed&&!locked()?`<button class="rd-text-button" type="button" data-rs-revoke="${e(r.id)}">撤销并重算</button>`:''}</article>`).join(''):'<p class="rd-message">暂无奖金调整记录。</p>'}<p class="rd-message">实际支付状态未核实。</p><p id="rsRecordError" class="rd-error" role="status"></p><section id="rsRevokePreview"></section></section>`);
      $('rsNew').disabled=locked();$('rsPolicy').disabled=locked();$('rsNew').onclick=()=>open();$('rsPolicy').onclick=()=>open('',{type:'cutoff'});
      document.querySelectorAll('[data-rs-amend]').forEach(b=>b.onclick=()=>{const r=data.records.find(r=>r.id===b.dataset.rsAmend);open(r.rowId,{type:'adjustment',kind:r.kind,recipient:r});});
      document.querySelectorAll('[data-rs-revoke]').forEach(b=>b.onclick=async()=>{if(!active()||locked())return;const finish=window.RecruitmentInteractions.pending(b,'正在核算…',$('draftInspectorBody'));if(!finish)return;
        try{const p=await request(url+'/special/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:data.revision,type:'revoke',recordId:b.dataset.rsRevoke})});finish();if(!active())return;
          document.querySelectorAll('[data-rs-revoke]').forEach(x=>x.disabled=true);
          $('rsRevokePreview').innerHTML=`<h3>撤销影响 · ${p.people} 人</h3>${p.currentImpact.map(x=>`<p>${e(x.name)} ${e(x.kind)}：${e(w.amount(x.before,x.currency))} → ${e(w.amount(x.after,x.currency))}</p>`).join('')}${p.nodeImpact.map(x=>`<p>${e(x.name)} · ${e(x.label)}：${snapshot(x.before)} → ${snapshot(x.after)}</p>`).join('')}<button id="rsRevokeCancel" class="rd-button" type="button">取消</button><button id="rsRevokeApply" class="rd-button rd-primary" type="button">确认撤销</button>`;
          $('rsRevokeCancel').onclick=records;$('rsRevokeApply').onclick=async()=>{if(!active()||locked())return;const finishSave=window.RecruitmentInteractions.pending($('rsRevokeApply'),'正在撤销…',$('draftInspectorBody'));if(!finishSave)return;w.busy(true);w.status('正在撤销奖金调整');
            try{const saved=await request(url+'/special/previews/'+p.id+'/apply',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:data.revision})});if(base()===url){const close=active();w.adopt(saved);if(close)$('draftInspector').close();w.status('已撤销，奖金已更新');}}catch(err){if(active())$('rsRecordError').textContent=err.message;w.status(err.message,true);}finally{finishSave();w.busy(false);}};
        }catch(err){if(active())$('rsRecordError').textContent=err.message;}finally{finish();}});
    }catch(err){if(active())$('draftInspectorBody').textContent=err.message;}}
  window.RecruitmentSpecial={open,records,review};
  $('flowSpecialRecords').onclick=()=>{document.querySelector('.flow-more').open=false;records();};
  $('flowCutoffPolicy').onclick=()=>{document.querySelector('.flow-more').open=false;open('',{type:'cutoff'});};
})();
