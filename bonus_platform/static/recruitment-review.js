(() => {
  'use strict';
  const w=window.RecruitmentWorkbench,{$,ui,e,label,base,request,adopt,busy,status,render,openDialog,mutate,amount}=w;
  let gridFields=['姓名','工号','入职日期','职级','ABC类别','招聘渠道','招聘启动日期','招聘负责人工号','协助招聘人工号','推荐人工号','周期剔除天数','人工备注'];
  let visibleRows=[],reviewSequence=0;
  const shown=value=>value===null||value===undefined||value===''?'空白':value;
  const post=(path,data)=>request(base()+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:ui.data.revision,...data})});
  function tools(){
    $('draftTableTools').hidden=ui.view!=='rows'||!ui.data.rows.length;
    $('draftGridToggle').disabled=ui.busy;
    document.querySelectorAll('[data-grid-row]').forEach(input=>input.disabled=ui.busy);
    $('draftGridToggle').textContent=ui.editing?'查看奖金':'编辑资料';
    $('draftUndo').disabled=ui.busy||!ui.data.canUndo;$('draftRedo').disabled=ui.busy||!ui.data.canRedo;
    $('draftEditableExport').href=base()+'/worksheet';
    document.querySelectorAll('[data-reconcile-source]').forEach(b=>b.onclick=()=>reconciliation(b.dataset.reconcileSource));
    document.querySelectorAll('[data-review-source]').forEach(b=>b.onclick=()=>approval(b.dataset.reviewSource));
  }
  document.addEventListener('recruitment:render',tools);
  document.addEventListener('recruitment:busy',()=>{if(ui.data)tools();});
  $('draftGridToggle').onclick=()=>{ui.editing=!ui.editing;render();};
  async function history(action){if(ui.busy)return;busy(true);status('正在恢复并更新试算');try{adopt(await post('/history',{action}));}catch(err){status(err.message,true);}finally{busy(false);tools();}}
  $('draftUndo').onclick=()=>history('undo');$('draftRedo').onclick=()=>history('redo');
  $('draftInspector').addEventListener('close',()=>{$('draftInspector').classList.remove('rd-wide');reviewSequence++;});
  function wide(title,html){ui.focusRow=null;openDialog(title,html);$('draftInspector').classList.add('rd-wide');}
  function error(id,err){$(id).textContent=label(err.message);$(id).classList.add('rd-error');}
  function tsv(raw){
    const rows=[];let row=[],value='',quoted=false;
    for(let i=0;i<raw.length;i++){const c=raw[i];if(c==='"'&&(quoted||value==='')){if(quoted&&raw[i+1]==='"'){value+='"';i++;}else quoted=!quoted;}else if(!quoted&&(c==='\t'||c==='\n'||c==='\r')){row.push(value);value='';if(c!=='\t'){rows.push(row);row=[];if(c==='\r'&&raw[i+1]==='\n')i++;}}else value+=c;}
    if(value||row.length){row.push(value);rows.push(row);}return rows;
  }
  function renderGrid(rows){
    if(window.RecruitmentWorkbenchExtension)gridFields=window.RecruitmentWorkbenchExtension.visibleColumns().filter(c=>ui.data.editableFields.includes(c.key)).map(c=>c.key);
    visibleRows=rows;
    $('draftContent').innerHTML=`<table class="rd-table rd-edit-grid"><thead><tr>${gridFields.map(f=>`<th scope="col">${e(label(f))}</th>`).join('')}</tr></thead><tbody>${rows.map((r,ri)=>`<tr>${gridFields.map((f,ci)=>`<td><input data-grid-row="${ri}" data-grid-col="${ci}" aria-label="${e(r.values.姓名)} ${e(label(f))}" value="${e(r.values[f]??'')}" autocomplete="off" /></td>`).join('')}</tr>`).join('')}</tbody></table>`;
    document.querySelectorAll('[data-grid-row]').forEach(input=>{
      const row=rows[Number(input.dataset.gridRow)],field=gridFields[Number(input.dataset.gridCol)];
      if(ui.data.fieldControls?.[field]?.missingMessage){input.outerHTML=`<button type="button" class="rd-text-button" data-grid-evidence-row="${e(row.id)}" data-grid-evidence-field="${e(field)}">选择已有资料</button>`;return;}
      const markup=window.RecruitmentFactControls.choice(ui.data.fieldControls?.[field],row.values[field],`data-grid-row="${input.dataset.gridRow}" data-grid-col="${input.dataset.gridCol}" aria-label="${e(row.values.姓名)} ${e(label(field))}"`);
      if(markup!==null)input.outerHTML=markup;
    });
    document.querySelectorAll('[data-grid-evidence-row]').forEach(button=>button.onclick=()=>w.editor([button.dataset.gridEvidenceRow],null,ui.data.revision,{field:button.dataset.gridEvidenceField}));
    document.querySelectorAll('[data-grid-row]').forEach(input=>{
      input.onchange=async()=>{if(ui.busy)return;const r=rows[Number(input.dataset.gridRow)],field=gridFields[Number(input.dataset.gridCol)];if(input.value===String(r.values[field]??''))return;const edits=[{rowId:r.id,field,value:input.value,reason:'工作表核对更正'}];busy(true);try{showPreview(await post('/previews',{edits}));}catch(err){status(err.message,true);}finally{input.value=String(r.values[field]??'');busy(false);}};
      input.onkeydown=event=>{if(event.key==='Escape'){input.value=input.defaultValue;input.blur();}if(event.key==='Enter'){event.preventDefault();input.blur();}if((event.metaKey||event.ctrlKey)&&event.key==='z'&&input.value===input.defaultValue){event.preventDefault();history(event.shiftKey?'redo':'undo');}};
      input.onpaste=async event=>{
        const raw=event.clipboardData?.getData('text/plain')||'';if(!/[\t\r\n]/.test(raw))return;
        event.preventDefault();const matrix=tsv(raw),ri=Number(input.dataset.gridRow),ci=Number(input.dataset.gridCol);
        if(matrix.length+ri>rows.length||matrix.some(r=>r.length+ci>gridFields.length)){status('粘贴范围超出当前可见表格，请缩小范围后重试',true);return;}
        const edits=[];matrix.forEach((line,y)=>line.forEach((value,x)=>{const row=rows[ri+y],field=gridFields[ci+x];if(value!==String(row.values[field]??''))edits.push({rowId:row.id,field,value,reason:'工作表区域粘贴核对'});}));
        if(!edits.length)return;busy(true);status('正在核对粘贴影响');
        try{showPreview(await post('/previews',{edits}));}catch(err){status(err.message,true);}finally{busy(false);}
      };
    });
  }
  function showPreview(preview,back,onApplied){
    const previewBase=base();
    const nodes=preview.nodeImpact||[],current=preview.currentImpact||[];
    const month=v=>v?String(v).slice(0,4)+'年'+Number(String(v).slice(4))+'月':'未安排';
    const cell=n=>n?`<strong>${e(amount(n.amount,n.currency))}</strong><span>${e(n.recipientName||n.recipientId||'领取人待核')}</span><span>${month(Object.hasOwn(n,'scheduledMonth')?n.scheduledMonth:n.dueMonth)} · ${e(label(n.status))}</span>`:'未形成分期';
    const unresolved=preview.unresolvedAmounts||[],remaining=preview.remainingIssues||[];
    const changes=preview.changes.length?`<div class="rd-preview-table"><table class="rd-table"><thead><tr><th>姓名</th><th>修改项目</th><th>修改前</th><th>修改后</th></tr></thead><tbody>${preview.changes.map(c=>`<tr><td>${e(c.name)}</td><td>${e(label(c.field))}</td><td>${e(shown(c.before))}</td><td>${e(shown(c.after))}</td></tr>`).join('')}</tbody></table></div>`:'';
    const amounts=current.length?`<section><h3>本月奖金</h3><div class="rw-current-impact">${current.map(i=>`<p class="rw-preview-amount">${e(i.name)} · ${e(i.kind)}<span>${e(amount(i.before,i.beforeCurrency))} → <b>${e(amount(i.after,i.currency))}</b></span></p>`).join('')}</div></section>`:`<p class="rd-message">${unresolved.length?'仍有资料待核，奖金金额待定。':'本月金额不变。'}</p>`;
    const detail=nodes.length?`<details class="rd-inspector-section"><summary>各期奖金变化 · ${nodes.length} 笔</summary><div class="rd-preview-table rw-node-preview"><table class="rd-table"><thead><tr><th>人员与分期</th><th>修改前</th><th>修改后</th></tr></thead><tbody>${nodes.map(n=>`<tr><td>${e(n.name)}<span>${e(n.kind)} · ${e(n.role)}<br>${e(n.label)}</span></td><td>${cell(n.before)}</td><td>${cell(n.after)}</td></tr>`).join('')}</tbody></table></div></details>`:'';
    $('draftInspector').classList.toggle('rd-wide',preview.people>5);
    (preview.people>5?wide:openDialog)(`确认修改 · ${preview.people} 人`,`${changes}${amounts}${preview.impact.length?`<details class="rd-inspector-section"><summary>奖金总额变化</summary>${preview.impact.map(i=>`<p>${e(i.name)} · ${e(i.kind)}：${e(amount(i.before,i.beforeCurrency))} → <b>${e(amount(i.after,i.currency))}</b></p>`).join('')}</details>`:''}${detail}${preview.arrangements.length?`<h3>补扣安排</h3>${preview.arrangements.map(i=>`<p>${e(i.recipientName)} · ${e(amount(i.amount,i.currency))} · 待核实际支付</p>`).join('')}`:''}${remaining.length?`<details class="rd-inspector-section" ${unresolved.length?'open':''}><summary>仍待处理 · ${remaining.length} 项</summary>${remaining.map(r=>`<p>${e(r.name)} · ${e(r.kind)}：${e(label(r.reasons.join('；')))}</p>`).join('')}</details>`:''}<p id="reviewApplyStatus" role="status"></p><div class="rw-sticky-actions">${back?'<button id="reviewBack" class="rd-button" type="button">返回修改</button>':''}<button id="reviewApply" class="rd-button rd-primary" type="button">确认保存</button></div>`);
    if(back)$('reviewBack').onclick=back;
    const resultBody=$('draftInspectorBody'),resultButton=$('reviewApply');
    $('reviewApply').onclick=async()=>{if(ui.busy||base()!==previewBase||ui.data.activity?.archived)return;const finish=window.RecruitmentInteractions.pending(resultButton,'正在保存…',resultButton.parentElement);if(!finish)return;busy(true);status('正在保存核算结果');try{const saved=await post(`/previews/${preview.id}/apply`,{revision:preview.revision});if(base()!==previewBase)return;const close=resultBody.contains(resultButton);adopt(saved);if(close)$('draftInspector').close();onApplied?.();status('已保存，奖金已更新');}catch(err){if(resultBody.contains(resultButton))error('reviewApplyStatus',err);status(err.message,true);}finally{finish();busy(false);}};
  }
  $('draftWorkbookReturn').onclick=()=>$('draftWorkbookFile').click();
  $('draftWorkbookFile').onchange=async()=>{
    const file=$('draftWorkbookFile').files[0];if(!file||ui.busy)return;
    const send=async()=>{const form=new FormData();form.append('revision',ui.data.revision);form.append('file',file);busy(true);status('正在核对回传差异');try{showPreview(await request(base()+'/worksheet/preview',{method:'POST',body:form}));status('已生成回传修改预览');}finally{busy(false);$('draftWorkbookFile').value='';}};
    try{await send();}catch(err){status(err.message,true);}
  };
  async function reconciliation(id){
    const sequence=++reviewSequence,current=base();
    wide('核对台账差异','<p class="rd-message" role="status">正在独立重算并核对</p>');
    try{const result=await request(base()+'/reconciliation/'+id),s=result.summary;
      if(sequence!==reviewSequence||base()!==current||!$('draftInspector').open)return;
      wide('核对台账差异',`<p>${s.matchedPeople||0} 条已对应 · ${s.unmatchedPeople} 条身份待核 · ${s.numericMoneyDifferences} 项数值不同 · ${s.unresolvedMoneyItems} 项资料待核</p><p class="rd-message">${e(result.basis)}</p><a class="rd-button" href="${base()}/reconciliation/${id}/export">导出差异</a><div class="rd-preview-table rd-reconciliation"><table class="rd-table"><thead><tr><th>姓名</th><th>项目</th><th>台账</th><th>独立试算</th><th>原因</th></tr></thead><tbody>${result.moneyDifferences.slice(0,200).map(d=>`<tr><td><button class="rd-row-open" data-difference-row="${d.rowId}" type="button">${e(d.name)}</button></td><td>${e(d.kind)} · ${e(d.item)}</td><td>${e(amount(d.reference,d.currency))}</td><td>${e(amount(d.calculated,d.currency))}</td><td>${e(label(d.reason))}</td></tr>`).join('')}</tbody></table></div>${result.moneyDifferences.length>200?'<p class="rd-message">页面显示前200项，导出包含全部差异及字段依据。</p>':''}`);
      document.querySelectorAll('[data-difference-row]').forEach(b=>b.onclick=()=>w.inspector(b.dataset.differenceRow));
    }catch(err){$('draftInspectorBody').textContent=label(err.message);}
  }
  function approval(id){return window.RecruitmentApprovals.open(id);}
  window.RecruitmentReviewExtension={renderGrid,approval,showPreview,tsv,reconciliation};
  if(ui.data)tools();
})();
