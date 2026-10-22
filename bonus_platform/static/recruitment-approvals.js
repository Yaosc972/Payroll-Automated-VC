(() => {
  'use strict';
  const w=window.RecruitmentWorkbench,{$,ui,e,base,request,openDialog,adopt,busy,status}=w;
  const fields=['招聘渠道','ABC类别','周期剔除天数','招聘负责人姓名','招聘负责人工号','协助招聘人姓名','协助招聘人工号','推荐人姓名','推荐人工号','招聘启动日期','入职日期','转正日期','最后工作日','职级'];
  const label=f=>({'ABC类别':'岗位类别','候选人入职时间':'录用入职日期'}[f]||f);
  const shown=v=>v===null||v===undefined||v===''?'未填写':String(v);
  let session=null,sequence=0,pendingUpload=false;
  const post=(url,payload)=>request(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  function selected(){return session.data.items.filter(i=>session.selected.has(i.id));}
  function chosenReferences(item){return Object.values(session.referenceSelections[item.id]||{});}
  function currentFields(item){return {...Object.fromEntries(item.fields.map(f=>[f.field,f.value])),...Object.fromEntries(chosenReferences(item).map(option=>[option.field,option.value])),...(session.overrides[item.id]?.fields||{})};}
  function currentPerson(item){const rid=session.overrides[item.id]?.rowId||item.person.rowId;return ui.data.rows.find(r=>r.id===rid);}
  function override(id){return session.overrides[id]||(session.overrides[id]={fields:{}});}
  function issues(item){
    const change=session.overrides[item.id]||{},values={...Object.fromEntries(chosenReferences(item).map(option=>[option.field,option.value])),...(change.fields||{})};
    return item.issues.filter(message=>{
      if(item.documentIssues?.includes(message))return true;
      if(change.rowId&&message===item.matchIssue)return false;
      if(/调整内容未识别完整|否定的调整表述|请补充调整字段和采用值/.test(message)&&(Object.values(values).some(v=>v!=='')||change.decisions))return false;
      if(/请补充|识别到多个调整值/.test(message)&&Object.entries(values).some(([field,value])=>value!==''&&message.includes(label(field))))return false;
      return true;
    });
  }
  function updateIssues(container,item){
    const messages=issues(item),list=container.querySelector('.rai-issues');
    if(list){list.innerHTML=messages.map(m=>`<li>${e(m)}</li>`).join('');list.hidden=!messages.length;}
    if(item.status!=='consistent')container.querySelector('.rai-state').textContent=messages.length?'需补充':'待采用';
  }
  function footer(){
    const count=selected().length,stale=base()!==session.base||ui.data.revision!==session.data.revision,operation=session.operation;
    const preparing=['running','cancelling'].includes(ui.prepareJob?.status),locked=ui.busy||preparing;
    const updating=!operation&&(preparing||(locked&&session.notice?.tone==='success'));
    const spinner='<span class="rai-spinner" aria-hidden="true"></span>';
    $('approvalApply').innerHTML=updating?spinner+'正在更新…':operation==='apply'?spinner+(session.phase===0?'正在核对…':'正在采用…'):`核对并采用${count?' · '+count+' 项':''}`;
    $('approvalApply').setAttribute('aria-busy',String(operation==='apply'||updating));
    $('approvalApply').disabled=!count||locked||stale||ui.data.activity?.archived;
    $('approvalImpact').innerHTML=operation==='impact'?spinner+'正在核算…':'查看奖金影响';
    $('approvalImpact').setAttribute('aria-busy',String(operation==='impact'));
    $('approvalImpact').disabled=!count||locked||stale;
    $('approvalReload').hidden=!stale;
    $('approvalReload').disabled=locked;
    $('approvalImport').disabled=locked||ui.data.activity?.archived;
    $('approvalEditor').inert=Boolean(operation||updating);
    $('draftCloseInspector').disabled=Boolean(operation);
    const notice=updating?{tone:'running',message:session.notice?.tone==='success'?'审批调整已保存，正在补全资料并更新核算…':'正在更新核算，请稍候…'}:
      session.notice?.tone==='success'&&ui.operationError?{tone:'error',message:`审批调整已保存，${ui.operationMessage}`}:
      session.notice||(stale?{tone:'error',message:'核算资料已更新，请刷新调整清单。'}:null);
    $('approvalFeedback').hidden=!notice;
    $('approvalFeedback').dataset.tone=notice?.tone||'';
    const message=notice?.message||'';
    if($('approvalMessage').textContent!==message)$('approvalMessage').textContent=message;
    $('approvalProgress').hidden=operation!=='apply'&&!updating;
    const phase=updating?1:session.phase;
    $('approvalProgress').querySelectorAll('li').forEach((step,i)=>step.dataset.state=i<phase?'done':i===phase?'active':'waiting');
  }
  function progress(current,phase,message){
    current.phase=phase;current.notice={tone:'running',message};footer();status(message);
  }
  function original(doc){
    return `<details class="rai-original" data-approval-original="${e(doc.sourceId)}"><summary>查看审批原件</summary><div><a href="${session.base}/sources/${e(doc.sourceId)}" target="_blank" rel="noopener">打开完整原件</a>${doc.pageNumbers.length?`<label>页码<select data-approval-page="${e(doc.sourceId)}">${doc.pageNumbers.map(n=>`<option value="${n}">第 ${n} 页</option>`).join('')}</select></label><img alt="${e(doc.name)}的审批原页" loading="lazy"/>`:''}</div></details>`;
  }
  function line(item,field,value){
    const person=currentPerson(item),before=person?.values[field]??item.fields.find(f=>f.field===field)?.before;
    const references=(item.referenceOptions||[]).filter(option=>option.field===field),chosen=session.referenceSelections[item.id]?.[field];
    const referenceOptions=references.map(option=>`<option value="reference:${e(option.referenceProposal.proposalId)}" ${chosen?.referenceProposal.proposalId===option.referenceProposal.proposalId?'selected':''}>${e(option.label)}</option>`).join('');
    const options=field==='ABC类别'?['A','B','C']:field==='招聘渠道'?['招聘网站','内推','校招','猎头','二次入职','其他']:null;
    const control=options?`<select data-approval-field="${e(field)}" aria-label="${e(label(field))}采用值"><option value="">请选择</option>${[...new Set([...options,...(value?[String(value)]:[])])].map(v=>`<option ${!chosen&&String(value)===v?'selected':''} value="${e(v)}">${e(v)}</option>`).join('')}${referenceOptions}</select>`:
      `<input type="${field==='周期剔除天数'?'number':/日期|工作日/.test(field)?'date':'text'}" ${field==='周期剔除天数'?'min="0" step="any"':''} data-approval-field="${e(field)}" aria-label="${e(label(field))}采用值" value="${e(value??'')}"/>${references.length?`<select data-approval-reference="${e(field)}" aria-label="采用${e(label(field))}参考事实"><option value="">选择已有参考事实</option>${referenceOptions}</select>`:''}`;
    return `<tr><td>${e(label(field))}</td><td>${e(shown(before))}</td><td>${control}${value===''&&/姓名|工号/.test(field)?'<span class="rai-empty-value">清空</span>':''}</td></tr>`;
  }
  function card(item){
    const person=currentPerson(item),p=person?{name:person.values.姓名,employeeId:person.values.工号,hireDate:person.values.入职日期}:item.person;
    const values=currentFields(item),done=item.status==='consistent',blocked=item.documentIssues?.length,messages=issues(item);
    return `<article class="rai-item" data-approval-item="${e(item.id)}" data-state="${item.status}"><header><label><input type="checkbox" data-approval-select="${e(item.id)}" ${session.selected.has(item.id)?'checked':''} ${done||blocked?'disabled':''} aria-label="采用${e(p.name||'待匹配人员')}的审批调整"/><span><strong>${e(p.name||'待匹配人员')}</strong><span>${e([p.employeeId,p.hireDate].filter(Boolean).join(' · '))}</span></span></label><span class="rai-state">${done?'已与核算一致':item.issues.length?'需补充':'待采用'}</span>${!done?'<button type="button" class="rd-text-button" data-approval-person>选择人员</button>':''}</header>
      <div class="rai-person-picker" hidden><input type="search" placeholder="搜索姓名、工号" aria-label="选择审批对应人员"/><div role="list"></div></div>
      ${messages.length?`<ul class="rai-issues">${messages.map(i=>`<li>${e(i)}</li>`).join('')}</ul>`:''}
      <table class="rai-table"><thead><tr><th>调整项目</th><th>当前值</th><th>采用值</th></tr></thead><tbody>${Object.entries(values).filter(([f])=>f!=='周期剔除依据').map(([f,v])=>line(item,f,v)).join('')}${item.decisions.map(d=>`<tr><td>${d.kind==='recruitment'?'招聘奖金':'内推奖金'}</td><td>按当前规则核算</td><td><select data-approval-decision="${d.kind}" aria-label="${d.kind==='recruitment'?'招聘奖金':'内推奖金'}采用决定" ${done?'disabled':''}><option value="exclude" ${(session.overrides[item.id]?.decisions||item.decisions).some(v=>v.kind===d.kind)?'selected':''}>不发放</option><option value="" ${!(session.overrides[item.id]?.decisions||item.decisions).some(v=>v.kind===d.kind)?'selected':''}>按规则核算</option></select></td></tr>`).join('')}</tbody></table>
      ${done?'':`<details class="rai-add-field"><summary>补充调整项</summary><select aria-label="补充调整字段">${fields.filter(f=>!(f in values)).map(f=>`<option value="${e(f)}">${e(label(f))}</option>`).join('')}</select><button type="button" class="rd-text-button" data-approval-add>添加</button></details>`}${!done&&!blocked&&(item.canMarkNoChange||currentPerson(item))?'<button type="button" class="rd-text-button" data-approval-no-change>已核对，无需调整</button>':''}</article>`;
  }
  function render(){
    const docs=session.data.documents.filter(d=>!session.sourceId||d.sourceId===session.sourceId);
    const section=(doc,items)=>`<section class="rai-document"><div class="rai-source"><h3 title="${e(doc.name)}">${e(doc.name)}</h3>${original(doc)}</div>${doc.referencedAttachments?.length?`<details class="rai-original"><summary>审批引用附件 · ${doc.referencedAttachments.length} 份</summary><ul>${doc.referencedAttachments.map(ref=>`<li>${ref.sourceIds.length?ref.sourceIds.map(id=>`<a href="${session.base}/sources/${e(id)}" target="_blank" rel="noopener">${e(ref.name)}</a>`).join('、'):e(ref.name)+' · 仅有引用，未附正文'}</li>`).join('')}</ul></details>`:''}${items.map(card).join('')}${!doc.items.length?`<ul class="rai-issues">${doc.issues.map(i=>`<li>${e(i)}</li>`).join('')}</ul>`:''}</section>`;
    const pending=docs.map(d=>{const items=session.data.items.filter(i=>i.sourceId===d.sourceId&&i.status!=='consistent');return items.length||!d.items.length?section(d,items):'';}).join('');
    const completed=docs.map(d=>{const items=session.data.items.filter(i=>i.sourceId===d.sourceId&&i.status==='consistent');return items.length?section(d,items):'';}).join('');
    const completedCount=session.data.items.filter(i=>i.status==='consistent'&&docs.some(d=>d.sourceId===i.sourceId)).length;
    openDialog('审批调整',`<div id="approvalEditor"><div class="rai-toolbar"><strong>${session.data.items.length} 项调整 · ${session.data.documents.length} 份审批</strong>${session.sourceId?'<button id="approvalShowAll" class="rd-text-button" type="button">查看全部审批</button>':''}<button id="approvalSelectReady" class="rd-text-button" type="button">选择可采用项</button></div>
      <div class="rai-documents">${pending||'<p>暂无需要处理的审批调整。</p>'}${completed?`<details class="rai-completed" ${session.sourceId&&!pending?'open':''}><summary>已与核算一致 · ${completedCount} 项</summary>${completed}</details>`:''}</div>
      <div id="approvalAmountImpact" hidden></div></div><div class="rai-footer"><div id="approvalFeedback" class="rai-feedback" hidden><p id="approvalMessage" role="status" aria-live="polite" aria-atomic="true"></p><ol id="approvalProgress" class="rai-progress" aria-label="审批采用进度" hidden><li>核对调整</li><li>更新核算</li></ol></div><div class="rai-footer-actions"><button id="approvalImport" class="rd-button" type="button">补充资料</button><button id="approvalReload" class="rd-button" type="button" hidden>刷新清单</button><span></span><button id="approvalImpact" class="rd-button" type="button">查看奖金影响</button><button id="approvalApply" class="rd-button rd-primary" type="button">核对并采用</button></div></div>`);
    $('draftInspector').classList.add('rd-wide','rai-dialog');
    $('approvalShowAll')?.addEventListener('click',()=>{session.sourceId='';render();});
    $('approvalSelectReady').onclick=()=>{docs.forEach(d=>session.data.items.filter(i=>i.sourceId===d.sourceId&&i.status==='ready'&&!i.requiresRecheck).forEach(i=>session.selected.add(i.id)));session.dirty=true;session.preview=null;render();};
    $('approvalReload').onclick=()=>open(session.sourceId);
    $('approvalImport').onclick=()=>{$('draftInspector').close();w.setView('sources');$('draftUpload').click();};
    document.querySelectorAll('[data-approval-select]').forEach(input=>input.onchange=()=>{input.checked?session.selected.add(input.dataset.approvalSelect):session.selected.delete(input.dataset.approvalSelect);invalidate();});
    document.querySelectorAll('[data-approval-item]').forEach(container=>{
      const id=container.dataset.approvalItem,item=session.data.items.find(i=>i.id===id);
      container.querySelectorAll('[data-approval-field]').forEach(input=>{
        input.disabled=item.status==='consistent'||Boolean(item.documentIssues?.length)||ui.data.activity?.archived;
        input.oninput=()=>{const field=input.dataset.approvalField,option=(item.referenceOptions||[]).find(option=>option.field===field&&input.value==='reference:'+option.referenceProposal.proposalId);
          if(option){(session.referenceSelections[id]||(session.referenceSelections[id]={}))[field]=option;delete override(id).fields[field];}
          else{delete (session.referenceSelections[id]||{})[field];override(id).fields[field]=input.value;}session.selected.add(id);container.querySelector('[data-approval-select]').checked=true;input.nextElementSibling?.classList.contains('rai-empty-value')&&input.nextElementSibling.remove();updateIssues(container,item);invalidate();};
      });
      container.querySelectorAll('[data-approval-reference]').forEach(input=>{input.onchange=()=>{
        const field=input.dataset.approvalReference,option=(item.referenceOptions||[]).find(option=>option.field===field&&input.value==='reference:'+option.referenceProposal.proposalId);
        if(option){(session.referenceSelections[id]||(session.referenceSelections[id]={}))[field]=option;delete override(id).fields[field];session.selected.add(id);invalidate();render();}
      };});
      container.querySelector('[data-approval-add]')?.addEventListener('click',()=>{const field=container.querySelector('.rai-add-field select').value;if(field){override(id).fields[field]='';session.dirty=true;session.preview=null;render();}});
      container.querySelectorAll('[data-approval-decision]').forEach(input=>{
        input.disabled=item.status==='consistent'||Boolean(item.documentIssues?.length)||ui.data.activity?.archived;
        input.onchange=()=>{override(id).decisions=Array.from(container.querySelectorAll('[data-approval-decision]')).filter(c=>c.value==='exclude').map(c=>({kind:c.dataset.approvalDecision,action:'exclude'}));session.selected.add(id);container.querySelector('[data-approval-select]').checked=true;updateIssues(container,item);invalidate();};
      });
      container.querySelector('[data-approval-no-change]')?.addEventListener('click',()=>submit(true,id));
      updateIssues(container,item);
      container.querySelector('[data-approval-person]')?.addEventListener('click',()=>{
        const picker=container.querySelector('.rai-person-picker');picker.hidden=!picker.hidden;
        const search=picker.querySelector('input'),list=picker.querySelector('[role=list]');
        const find=()=>{const q=search.value.trim().toLowerCase();const options=ui.data.rows.filter(r=>!item.matches.length||item.matches.some(m=>m.rowId===r.id||m.name===r.values.姓名)).filter(r=>q?`${r.values.姓名} ${r.values.工号}`.toLowerCase().includes(q):item.matches.some(m=>m.rowId===r.id)).slice(0,20);
          list.innerHTML=options.map(r=>`<button class="rd-text-button" type="button" data-choose-row="${e(r.id)}">${e(r.values.姓名)} · ${e(r.values.工号||'无工号')} · ${e(r.values.入职日期||'')}</button>`).join('')||'<p>未找到人员，请先补充花名册或上月核算表。</p>';
          list.querySelectorAll('[data-choose-row]').forEach(b=>b.onclick=()=>{override(id).rowId=b.dataset.chooseRow;delete session.referenceSelections[id];session.selected.add(id);session.dirty=true;session.preview=null;render();});};
        search.oninput=find;find();search.focus();
      });
    });
    document.querySelectorAll('[data-approval-original]').forEach(details=>{
      const show=()=>{const img=details.querySelector('img'),page=details.querySelector('select');if(details.open&&img&&page)img.src=session.base+`/documents/${details.dataset.approvalOriginal}/pages/${page.value}`;};
      details.ontoggle=show;details.querySelector('select')?.addEventListener('change',show);
    });
    $('approvalImpact').onclick=()=>submit(false);$('approvalApply').onclick=()=>submit(true);footer();
  }
  function invalidate(){session.dirty=true;session.preview=null;session.notice=null;$('approvalAmountImpact').hidden=true;footer();}
  async function submit(apply,noChangeId=''){
    if(ui.busy||['running','cancelling'].includes(ui.prepareJob?.status)||base()!==session.base||ui.data.activity?.archived)return;
    const current=session,ids=noChangeId?[noChangeId]:selected().map(i=>i.id);if(!ids.length)return;
    current.operation=apply?'apply':'impact';busy(true);
    progress(current,0,apply?`正在核对 ${ids.length} 项审批调整…`:'正在计算奖金变化…');
    try{
      const overrides=noChangeId?(current.overrides[noChangeId]?.rowId?{[noChangeId]:{rowId:current.overrides[noChangeId].rowId}}:{}):Object.fromEntries(Object.entries(current.overrides).filter(([id])=>ids.includes(id)));
      const referenceSelections=noChangeId?[]:ids.flatMap(itemId=>Object.values(current.referenceSelections[itemId]||{}).map(option=>({itemId,...option.referenceProposal})));
      const preview=(!noChangeId&&current.preview)||await post(current.base+'/approval-adjustments/preview',{revision:current.data.revision,itemIds:ids,overrides,referenceSelections,...(noChangeId?{outcomes:{[noChangeId]:'no_change'}}:{})});
      if(session!==current||base()!==current.base)return;
      current.preview=noChangeId?null:preview;
      if(apply){
        progress(current,1,noChangeId?'正在保存无需调整的核对结论…':`正在采用 ${ids.length} 项审批调整并更新核算…`);
        const saved=await post(current.base+`/previews/${preview.id}/apply`,{revision:preview.revision});
        if(base()!==current.base)return;
        adopt(saved);
        const message=noChangeId?'已核对，无需调整。核对记录已保存。':`已采用 ${ids.length} 项审批调整，核算结果已更新。`;
        if(session===current){
          current.data=saved.approvalAdjustments;current.selected.clear();current.preview=null;current.operation=null;
          ids.forEach(id=>{delete current.overrides[id];delete current.referenceSelections[id];});current.dirty=Object.keys(current.overrides).length>0;
          current.notice={tone:'success',message};render();
        }
        status(message);
        document.dispatchEvent(new CustomEvent('recruitment:assignments-applied'));
      }else{
        const impact=$('approvalAmountImpact');impact.hidden=false;
        impact.innerHTML=`<h3>本月奖金变化</h3>${preview.currentImpact.length?preview.currentImpact.map(i=>`<p>${e(i.name)} · ${e(i.kind)}：${e(w.amount(i.before,i.beforeCurrency))} → <strong>${e(w.amount(i.after,i.currency))}</strong></p>`).join(''):'<p>本月奖金金额不变。</p>'}${preview.remainingIssues.length?`<details><summary>仍有 ${preview.remainingIssues.length} 项核算条件待处理</summary>${preview.remainingIssues.map(i=>`<p>${e(i.name)}：${e(i.reasons.join('；'))}</p>`).join('')}</details>`:''}`;
        current.notice=null;status('奖金变化已计算完成');
        impact.scrollIntoView({block:'nearest'});
      }
    }catch(err){
      const reason=/fetch|network|load failed/i.test(err.message)?'网络连接中断，请重试。':err.message;
      const message=`${apply?(current.phase===1?'未能确认采用结果':'未能完成审批采用'):'未能计算奖金变化'}：${reason}`;
      if(session===current)current.notice={tone:'error',message};status(message,true);
    }
    finally{current.operation=null;busy(false);if(session===current&&$('approvalApply'))footer();}
  }
  async function open(sourceId='',notice=null){
    const seq=++sequence,url=base();let data=ui.data.approvalAdjustments;
    if(!data){openDialog('审批调整','<p role="status">正在识别人员及调整内容…</p>');try{data=await request(url+'/approval-adjustments');}catch(err){$('draftInspectorBody').textContent=err.message;return;}}
    if(seq!==sequence||base()!==url)return;
    session={base:url,data,sourceId,notice,selected:new Set(data.items.filter(i=>i.status==='ready'&&!i.requiresRecheck&&(!sourceId||i.sourceId===sourceId)).map(i=>i.id)),overrides:{},referenceSelections:{},preview:null};render();
  }
  $('draftInspector').addEventListener('cancel',event=>{if(session?.operation)event.preventDefault();});
  $('draftInspector').addEventListener('close',()=>{$('draftInspector').classList.remove('rai-dialog');$('draftCloseInspector').disabled=false;session=null;sequence++;});
  document.addEventListener('recruitment:uploaded',event=>{pendingUpload=event.detail?.files?.some(name=>/\.(pdf|png|jpe?g)$/i.test(name))||false;});
  document.addEventListener('recruitment:render',()=>{if(session&&$('draftInspector').classList.contains('rai-dialog')&&$('approvalApply')){
    if(!session.operation&&!session.dirty&&base()===session.base&&ui.data.revision!==session.data.revision)open(session.sourceId,session.notice);else footer();
  }});
  document.addEventListener('recruitment:status',()=>{if(session&&$('approvalApply'))footer();});
  document.addEventListener('recruitment:busy',()=>{if(pendingUpload&&!ui.busy){pendingUpload=false;open();}else if(session&&$('approvalApply'))footer();});
  window.RecruitmentApprovals={open};
})();
