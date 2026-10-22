(() => {
  'use strict';
  const w=window.RecruitmentWorkbench,{$,ui,e,label,base,request,adopt,busy,status,render,openDialog,mutate,amount,icon}=w;
  const readSetting=(key,fallback)=>{try{return JSON.parse(localStorage.getItem(key))||fallback;}catch{return fallback;}};
  ui.columnView=localStorage.getItem('recruitment-column-view')||'review';
  ui.columnSettings=readSetting('recruitment-columns',{});ui.taskCache={};
  $('draftColumnView').value=ui.columnView;
  const saveColumns=()=>localStorage.setItem('recruitment-columns',JSON.stringify(ui.columnSettings));
  const post=(path,data)=>request(base()+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:ui.data.revision,...data})});
  const cellFmt=(value,column)=>fmt(window.RecruitmentDetailTable?.isIdentity(column.key)?window.RecruitmentDetailTable.maskIdentity(value):value,column.type);
  const fmt=(value,type)=>value===null||value===undefined||value===''?'—':type==='percent'&&Number.isFinite(Number(value))?`${Math.round(Number(value)*100)}%`:['money','number'].includes(type)&&Number.isFinite(Number(value))?Number(value).toLocaleString('zh-CN',{minimumFractionDigits:type==='money'?2:0,maximumFractionDigits:2}):label(value);
  const reviewOrder=['姓名','工号','currency','recruitment.currentAmount','referral.currency','referral.currentAmount','recruitment.total','referral.total','recruitment.roundingDifference','referral.roundingDifference','入职日期','招聘渠道','招聘负责人姓名','协助招聘人姓名','职级','ABC类别','rule','cycle.actualDays','cycle.factor','人工备注','issues'];
  function visibleColumns(){
    const settings=ui.columnSettings[ui.columnView];
    const order=settings?.keys||(ui.columnView==='review'?reviewOrder:null);
    const cols=ui.data.columns.filter(c=>['姓名','工号'].includes(c.key)||(order?order.includes(c.key):c.views.includes(ui.columnView)));
    if(order)cols.sort((a,b)=>order.indexOf(a.key)-order.indexOf(b.key));
    return ui.columnView==='review'?cols.map(c=>({...c,group:c.key==='currency'||c.key.startsWith('recruitment.')||c.key.startsWith('referral.')?'奖金结果':c.group})):cols;
  }
  $('draftColumnView').onchange=()=>{ui.columnView=$('draftColumnView').value;localStorage.setItem('recruitment-column-view',ui.columnView);render();};
  $('draftColumns').onclick=()=>{
    const current=visibleColumns().map(c=>c.key),groups=[...new Set(ui.data.columns.map(c=>c.group))];
    openDialog('设置明细列',`<p class="rd-message">姓名和工号保持固定。选择本视图需要的列，设置会自动保留。</p><div class="rw-column-list">${groups.map(g=>`<section><h3>${e(g)}</h3>${ui.data.columns.filter(c=>c.group===g).map(c=>`<label class="rd-choice"><input type="checkbox" data-column-key="${e(c.key)}" ${current.includes(c.key)?'checked':''} ${['姓名','工号'].includes(c.key)?'disabled':''}/><span>${e(c.title)}</span></label>`).join('')}</section>`).join('')}</div><div class="rd-dialog-actions"><button id="rwResetColumns" class="rd-button" type="button">恢复默认</button><button id="rwSaveColumns" class="rd-button rd-primary" type="button">保存视图</button></div>`);
    $('rwSaveColumns').onclick=()=>{ui.columnSettings[ui.columnView]={...ui.columnSettings[ui.columnView],keys:(()=>{const selected=[...document.querySelectorAll('[data-column-key]:checked')].map(c=>c.dataset.columnKey);return [...current.filter(k=>selected.includes(k)),...selected.filter(k=>!current.includes(k))];})()};saveColumns();$('draftInspector').close();render();};
    $('rwResetColumns').onclick=()=>{delete ui.columnSettings[ui.columnView];saveColumns();$('draftInspector').close();render();};
  };
  function renderRows(rows){
    const cols=visibleColumns(),widths=ui.columnSettings[ui.columnView]?.widths||{},width=c=>widths[c.key]||c.width;
    let left=42;const fixed=new Map();for(const c of cols.slice(0,2)){fixed.set(c.key,left);left+=width(c);}
    const groups=[];for(const c of cols){const last=groups.at(-1);if(last?.name===c.group)last.size++;else groups.push({name:c.group,size:1});}
    $('draftContent').innerHTML=`<table class="rd-table rw-ledger"><colgroup><col style="width:42px"/>${cols.map(c=>`<col style="width:${width(c)}px"/>`).join('')}</colgroup><thead><tr class="rw-group-head"><th rowspan="2" class="rw-select-col"><input id="draftSelectVisible" type="checkbox" aria-label="选择本页人员" ${rows.length&&rows.every(r=>ui.selected.has(r.id))?'checked':''}/></th>${groups.map(g=>`<th colspan="${g.size}">${e(g.name)}</th>`).join('')}</tr><tr>${cols.map(c=>`<th scope="col" ${fixed.has(c.key)?`class="rw-fixed" style="left:${fixed.get(c.key)}px"`:''}><button data-sort-key="${e(c.key)}" draggable="${!['姓名','工号'].includes(c.key)}" title="点击排序，拖动调整列位置" type="button">${e(c.title)}${ui.sort?.key===c.key?ui.sort.direction===1?' ↑':' ↓':''}</button><span class="rw-resize" data-resize-key="${e(c.key)}" role="separator" aria-label="调整${e(c.title)}列宽"></span></th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr><td class="rw-select-col"><input type="checkbox" data-select-row="${r.id}" aria-label="选择 ${e(r.values.姓名)}" ${ui.selected.has(r.id)?'checked':''}/></td>${cols.map(c=>`<td class="${fixed.has(c.key)?'rw-fixed ':''}${['money','number','percent'].includes(c.type)?'rd-number ':''}${r.cells[c.key]==null?'rw-empty-value':''}" ${fixed.has(c.key)?`style="left:${fixed.get(c.key)}px"`:''} title="${e(cellFmt(r.cells[c.key],c))}" ${ui.data.editableFields.includes(c.key)?`data-edit-row="${r.id}" data-edit-field="${e(c.key)}"`:''}>${c.key==='姓名'?`<button class="rd-row-open" data-row="${r.id}" type="button">${e(r.values.姓名||'姓名待补')}</button>`:e(cellFmt(r.cells[c.key],c))}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
    document.querySelectorAll('[data-row]').forEach(b=>b.onclick=()=>w.inspector(b.dataset.row));
    document.querySelectorAll('[data-select-row]').forEach(c=>c.onchange=()=>{c.checked?ui.selected.add(c.dataset.selectRow):ui.selected.delete(c.dataset.selectRow);render();});
    $('draftSelectVisible').onchange=event=>{rows.forEach(r=>event.target.checked?ui.selected.add(r.id):ui.selected.delete(r.id));render();};
    document.querySelectorAll('[data-sort-key]').forEach(b=>b.onclick=()=>{ui.sort={key:b.dataset.sortKey,direction:ui.sort?.key===b.dataset.sortKey?-ui.sort.direction:1};render();});
    document.querySelectorAll('[data-sort-key]').forEach(button=>{
      button.ondragstart=event=>event.dataTransfer.setData('text/plain',button.dataset.sortKey);
      button.ondragover=event=>{if(!['姓名','工号'].includes(button.dataset.sortKey))event.preventDefault();};
      button.ondrop=event=>{event.preventDefault();const key=event.dataTransfer.getData('text/plain'),target=button.dataset.sortKey;if(!cols.some(c=>c.key===key)||['姓名','工号'].includes(key)||['姓名','工号'].includes(target)||key===target)return;const keys=cols.map(c=>c.key).filter(k=>k!==key);keys.splice(keys.indexOf(target),0,key);ui.columnSettings[ui.columnView]={...ui.columnSettings[ui.columnView],keys};saveColumns();render();};
    });
    document.querySelectorAll('[data-resize-key]').forEach(handle=>handle.onpointerdown=event=>{
      event.preventDefault();const key=handle.dataset.resizeKey,index=cols.findIndex(c=>c.key===key),col=document.querySelectorAll('.rw-ledger col')[index+1],start=event.clientX,initial=width(cols[index]);
      const move=ev=>{col.style.width=Math.max(96,initial+ev.clientX-start)+'px';};
      const stop=ev=>{document.removeEventListener('pointermove',move);document.removeEventListener('pointerup',stop);const settings=ui.columnSettings[ui.columnView]||{keys:cols.map(c=>c.key)};settings.widths={...settings.widths,[key]:Math.max(96,initial+ev.clientX-start)};ui.columnSettings[ui.columnView]=settings;saveColumns();render();};
      document.addEventListener('pointermove',move);document.addEventListener('pointerup',stop);
    });
    document.querySelectorAll('[data-edit-row]').forEach(cell=>cell.ondblclick=async()=>{const {row,revision}=await request(base()+'/rows/'+cell.dataset.editRow);w.editor([row.id],row,revision);$('draftEditField').value=cell.dataset.editField;$('draftEditField').dispatchEvent(new Event('change'));});
  }
  function renderTodos(tasks){
    if(!tasks.some(t=>t.id===ui.activeTask))ui.activeTask=tasks[0]?.id;
    const active=tasks.find(t=>t.id===ui.activeTask),cached=ui.taskCache[ui.activeTask];
    $('draftContent').innerHTML=`<div class="rw-review-layout"><nav class="rw-task-nav" aria-label="待处理事项"><div class="rw-nav-title">需要核对<span>${tasks.length} 项</span></div>${tasks.map(t=>`<button type="button" data-task-id="${t.id}" class="rw-task-item ${t.id===ui.activeTask?'is-active':''}" aria-current="${t.id===ui.activeTask?'true':'false'}"><span>${e(t.displayTitle||label(t.title))}</span><b>${t.rowIds.length||t.sourceIds.length||1}</b></button>`).join('')}</nav><section class="rw-task-work"><header class="rw-task-heading"><div><h2>${e(active?.displayTitle||active?.title)}</h2><p>${e(active?.instruction)}</p></div><span class="rw-count-pill">${active?.rowIds.length?active.rowIds.length+' 人':(active?.sourceIds.length||1)+' 项'}</span></header><div id="rwTaskBody">${cached?'':'<div class="rd-loading"><span></span><span></span></div>'}</div></section></div>`;
    document.querySelectorAll('[data-task-id]').forEach(b=>b.onclick=()=>{ui.activeTask=b.dataset.taskId;render();});
    if(cached)renderTaskBody(cached);
    else if(active){const id=active.id,revision=ui.data.revision,url=base();request(url+'/tasks/'+id).then(data=>{if(ui.data.revision!==revision||base()!==url)return;ui.taskCache[id]=data;if(ui.view==='todos'&&ui.activeTask===id)renderTaskBody(data);}).catch(err=>{if(ui.activeTask===id&&$('rwTaskBody'))$('rwTaskBody').innerHTML=`<div class="rw-error"><p>${e(err.message)}</p><button id="rwTaskRetry" class="rd-button" type="button">重新读取</button></div>`;$('rwTaskRetry')?.addEventListener('click',render);});}
  }
  function employmentMarkup(review,detailed=false){
    if(!review)return '';
    return `<div class="rw-employment-review"><strong>${review.issues.map(e).join('；')}</strong><div class="rw-employment-observations">${review.observations.map(o=>`<div><span>${e(o.label)}</span><b>${e(o.value)}</b><div class="rw-employment-sources">${o.sources.map(s=>`<a href="${base()}/sources/${encodeURIComponent(s.sourceId)}" target="_blank" rel="noopener" title="${e(s.file+' · '+s.sheet)}">${detailed?e(s.file)+' · ':''}第 ${e(s.row||'—')} 行</a>`).join('')}</div></div>`).join('')}</div></div>`;
  }
  function suggestionMarkup(suggestion,actionable=false){
    if(!suggestion)return '';
    const refs=[...new Map(suggestion.sources.map(s=>[[s.sourceId,s.sheet,s.row].join('|'),s])).values()];
    return `<div class="rw-source-note"><h3>${e(suggestion.title)}</h3><p>${e(suggestion.detail)}</p>${refs.map(s=>`<span class="rw-source-ref">${sourceReference(s)}</span>`).join('')}${actionable?'<button id="rwSuggestedPreview" class="rd-button rd-primary" type="button">按台账依据预览</button>':''}</div>`;
  }
  function renderTaskBody(task){
    if(!$('rwTaskBody'))return;
    const query=$('draftSearch').value.trim().toLowerCase();
    if(query&&!task.title.toLowerCase().includes(query))task={...task,rows:task.rows.filter(r=>[r.name,r.employeeId,r.job,r.jobType,r.organization,...r.fields.map(f=>f.value)].join(' ').toLowerCase().includes(query))};
    if(!task.rows.length){$('rwTaskBody').innerHTML=`<div class="rw-task-sources">${task.sources.map(s=>sourceCard(s,task.kind==='baseline')).join('')}</div>`;bindSources();return;}
    const scopeTask=task.kind==='intake_scope';
    const fields=task.rows.map(r=>r.fields.length===1?r.fields[0].field:null),shared=fields.length&&fields.every(f=>f===fields[0])?fields[0]:null;
    $('rwTaskBody').innerHTML=`${scopeTask?`<div class="rw-batch-source"><span>勾选同一范围的人员，一次确认是否纳入</span><button id="rwBatchScope" class="rd-button" type="button">批量确认范围</button></div>`:shared?`<div class="rw-batch-source"><span>逐人选择采用值，或按同一份资料批量核对</span><button id="rwBatchSource" class="rd-text-button" type="button">按资料批量选择</button></div>`:''}<table class="rd-table rw-task-table ${scopeTask?'rw-scope-table':''}"><thead><tr>${scopeTask?'<th><input id="rwScopeAll" type="checkbox" aria-label="选择当前范围全部人员"/></th>':''}<th>候选人</th><th>需要确认的内容</th><th>奖金试算总额</th><th>操作</th></tr></thead><tbody>${task.rows.map((r,i)=>`<tr>${scopeTask?`<td><input type="checkbox" data-scope-select="${r.rowId}" aria-label="选择 ${e(r.name)}" ${ui.selected.has(r.rowId)?'checked':''}/></td>`:''}<td><strong>${e(r.name)}</strong><span>${e(r.employeeId||'无工号')} · ${e(r.hireDate||'入职日待核')}</span>${r.lastWorkDate?`<span>最后工作日 ${e(r.lastWorkDate)}</span>`:''}</td><td>${scopeTask?`<div class="rw-fact-summary"><b>${e(r.job||'职位未提供')}</b><span>${e(r.jobType||'岗位分类未提供')} · ${e(r.organization)}</span></div>`:''}${r.reviewSuggestion?suggestionMarkup(r.reviewSuggestion):r.employmentReview?employmentMarkup(r.employmentReview):r.fields.slice(0,3).map(f=>`<div class="rw-fact-summary"><b>${e(f.label)}</b><span>${f.options.length>1?f.options.map(o=>e(o.label)).slice(0,3).join(' / '):f.value?e(label(f.value)):'尚未提供'}</span></div>`).join('')}${!r.employmentReview&&r.fields.length>3?`<span>另有 ${r.fields.length-3} 项资料</span>`:''}</td><td>${r.impact.map(a=>`<div class="rw-amount-line"><span>${a.kind}</span><strong>${e(amount(a.total,a.currency))}</strong></div>`).join('')}</td><td><button type="button" class="rd-button rw-review-button" data-review-index="${i}">${task.action||'核对'}</button></td></tr>`).join('')}</tbody></table>`;
    document.querySelectorAll('[data-review-index]').forEach(b=>b.onclick=()=>reviewPerson(task,task.rows[Number(b.dataset.reviewIndex)]));
    $('rwBatchSource')?.addEventListener('click',()=>batchSource(task,shared));
    document.querySelectorAll('[data-scope-select]').forEach(c=>c.onchange=()=>{c.checked?ui.selected.add(c.dataset.scopeSelect):ui.selected.delete(c.dataset.scopeSelect);});
    if(scopeTask){$('rwScopeAll').checked=task.rows.every(r=>ui.selected.has(r.rowId));$('rwScopeAll').onchange=event=>{task.rows.forEach(r=>event.target.checked?ui.selected.add(r.rowId):ui.selected.delete(r.rowId));renderTaskBody(task);};$('rwBatchScope').onclick=()=>batchScope(task);}

  }
  function sourceReference(s){return `<a href="${base()}/sources/${encodeURIComponent(s.sourceId)}" target="_blank" rel="noopener">${e(s.file)}</a><span>${e(s.sheet||'')} · 第 ${e(s.row||'—')} 行</span>`;}
  function reviewPerson(task,row){
    const seq=ui.data.revision;
    openDialog(row.name,`<div class="rw-person-meta"><span>${e(row.employeeId||'无工号')}</span><span>入职 ${e(row.hireDate||'待核')}</span>${row.lastWorkDate?`<span>最后工作日 ${e(row.lastWorkDate)}</span>`:''}</div><div class="rw-review-purpose">${task.kind==='intake_scope'?`<p>${e(row.job||'职位未提供')} · ${e(row.jobType||'岗位分类未提供')}<br>${e(row.organization)}</p>`:''}<h3>${e(task.title)}</h3><p>${e(row.employmentReview?row.employmentReview.instruction:task.instruction)}</p>${row.employmentReview?employmentMarkup(row.employmentReview,true):''}${row.employmentNote?`<p>${e(row.employmentNote)}</p>`:""}</div>${suggestionMarkup(row.reviewSuggestion,true)}${row.impact.length?`<div class="rw-decision-impact">${row.impact.map(a=>`<div><span>${e(a.kind)} · 本月到期</span><strong>${e(amount(a.currentAmount,a.currency))}</strong>${a.nodes.map(n=>`<span>${e(n.label)} · ${e(n.dueDate)} · ${e(n.recipient)}</span>`).join('')}</div>`).join('')}</div>`:''}${row.fields.map((f,i)=>`<section class="rw-decision-field" data-field-index="${i}"><div class="rw-field-heading"><h3>${e(f.label)}</h3><span>当前 ${e(fmt(f.value,'text'))}</span></div>${f.options.length?`<div class="rw-source-options">${f.options.map((o,j)=>`<label class="rw-source-choice"><input type="radio" name="choice-${i}" data-choice="${i}:${j}"/><span><strong>${e(o.label)}</strong>${o.sources.map(s=>`<span class="rw-source-ref">${sourceReference(s)}</span>`).join('')}</span></label>`).join('')}</div>`:''}<label class="rw-adopt-value">${f.options.length?'采用值，可直接修改':'补充采用值'}${f.field==='核算范围'?`<select data-task-value="${i}"><option value="">请选择</option><option>纳入核算</option><option>不纳入核算</option></select>`:f.field.endsWith('人员状态')?`<select data-task-value="${i}"><option value="">请选择</option>${['正式','试用','在职','离职','待入职'].map(s=>`<option ${s===f.value?'selected':''}>${s}</option>`).join('')}</select>`:`<input data-task-value="${i}" value="${e(f.value)}" type="${/日期|工作日|入职时间/.test(f.field)?'date':f.field.includes('天数')?'number':'text'}"/>`}</label></section>`).join('')}${row.note?`<div class="rw-source-note"><h3>台账备注</h3><p>${e(row.note)}</p></div>`:''}<p id="rwDecisionStatus" class="rd-error" role="status"></p><div class="rw-sticky-actions"><button type="button" id="rwReviewCancel" class="rd-button">返回</button><button type="button" id="rwDecisionPreview" class="rd-button rd-primary">预览修改</button></div>`);
    if(row.reviewSuggestion)$('rwSuggestedPreview').onclick=async()=>{
      const button=$('rwSuggestedPreview');button.disabled=true;
      try{window.RecruitmentReviewExtension.showPreview(await post('/previews',{revision:seq,edits:row.reviewSuggestion.edits}),()=>reviewPerson(task,row));}
      catch(err){$('rwDecisionStatus').textContent=label(err.message);button.disabled=false;}
    };
    row.fields.forEach((field,i)=>{
      const input=document.querySelector(`[data-task-value="${i}"]`);
      const markup=window.RecruitmentFactControls.choice(field.choices?field:ui.data.fieldControls?.[field.field],field.value,`data-task-value="${i}"`);
      if(input&&markup!==null)input.outerHTML=markup;
      if(field.missingMessage)document.querySelectorAll(`[data-choice^="${i}:"]`).forEach(radio=>radio.closest('label')?.remove());
    });
    const touched=new Set(),evidence={};
    document.querySelectorAll('[data-task-value]').forEach(input=>input.oninput=()=>{const i=Number(input.dataset.taskValue);touched.add(i);delete evidence[i];document.querySelectorAll(`[data-choice^="${i}:"]`).forEach(r=>r.checked=false);});
    document.querySelectorAll('[data-choice]').forEach(radio=>radio.onchange=()=>{const [i,j]=radio.dataset.choice.split(':').map(Number),choice=row.fields[i].options[j];document.querySelector(`[data-task-value="${i}"]`).value=choice.value;touched.add(i);evidence[i]=choice.sources[0]?.sourceId||'';});
    $('rwReviewCancel').onclick=()=>$('draftInspector').close();
    $('rwDecisionPreview').onclick=async()=>{
      const edits=[...touched].map(i=>({rowId:row.rowId,field:row.fields[i].field,value:document.querySelector(`[data-task-value="${i}"]`).value,evidenceId:evidence[i]||''}));
      if(!edits.length){$('rwDecisionStatus').textContent='请先选择来源资料或填写采用值。';return;}
      $('rwDecisionPreview').disabled=true;
      try{
        const show=async changes=>window.RecruitmentReviewExtension.showPreview(await post('/previews',{revision:seq,edits:changes}),()=>reviewPerson(task,row));
        await show(edits);
      }catch(err){$('rwDecisionStatus').textContent=label(err.message);$('rwDecisionPreview').disabled=false;}
    };
  }
  function batchSource(task,field){
    const ids=[...new Set(task.rows.flatMap(r=>r.fields.flatMap(f=>f.options.flatMap(o=>o.sources.map(s=>s.sourceId)))))];
    openDialog('按来源批量核对',`<p class="rd-message">每个人采用所选资料中对应的值。资料缺少该人、同一来源有不同值时保留待办。</p><label>采用资料<select id="rwBatchSourceSelect">${ids.map(id=>`<option value="${id}">${e(ui.data.sources.find(s=>s.id===id)?.name||id)}</option>`).join('')}</select></label><p id="rwBatchCount"></p><p id="rwBatchError" class="rd-error" role="status"></p><button id="rwBatchPreview" class="rd-button rd-primary" type="button">预览批量修改</button>`);
    function edits(){const id=$('rwBatchSourceSelect').value;return task.rows.flatMap(r=>{const options=r.fields.find(f=>f.field===field).options.filter(o=>o.sources.some(s=>s.sourceId===id));return options.length===1?[{rowId:r.rowId,field,value:options[0].value,evidenceId:id,reason:'逐人核对并采用所选资料中的'+LABEL(field)}]:[];});}
    const count=()=>{$('rwBatchCount').textContent=`可核对 ${edits().length} 人，其他 ${task.rows.length-edits().length} 人保留待办`;$('rwBatchPreview').disabled=!edits().length;};$('rwBatchSourceSelect').onchange=count;count();
    $('rwBatchPreview').onclick=async()=>{const selected=edits();$('rwBatchPreview').disabled=true;try{window.RecruitmentReviewExtension.showPreview(await post('/previews',{edits:selected}));}catch(err){$('rwBatchError').textContent=label(err.message);count();}};
  }
  function batchScope(task){
    const rows=task.rows.filter(r=>ui.selected.has(r.rowId));
    if(!rows.length){status('请先勾选需要一同确认范围的人员',true);return;}
    openDialog(`确认 ${rows.length} 人的核算范围`,`<p class="rd-message">${rows.map(r=>e(r.name)).join('、')}</p><label>核算范围<select id="rwScopeValue"><option>纳入核算</option><option>不纳入核算</option></select></label><p id="rwScopeStatus" role="status" class="rd-error"></p><button id="rwScopePreview" class="rd-button rd-primary" type="button">预览修改</button>`);
    $('rwScopePreview').onclick=async()=>{$('rwScopePreview').disabled=true;try{const edits=rows.map(r=>({rowId:r.rowId,field:'核算范围',value:$('rwScopeValue').value}));window.RecruitmentReviewExtension.showPreview(await post('/previews',{edits}));}catch(err){$('rwScopeStatus').textContent=err.message;$('rwScopePreview').disabled=false;}};
  }
  const LABEL=f=>({'招聘负责人工号':'招聘负责人','协助招聘人工号':'协助招聘人','推荐人工号':'推荐人'}[f]||label(f));
  function sourceCard(s,baseline=false){
    const scope=ui.data.monthly?.workItems?.find(i=>i.key==='approval:'+s.id)?.approvalPeople||[];
    const scopeStatus=scope.length?`已处理 ${scope.filter(p=>p.status==='已处理').length} 人 · 待匹配 ${scope.filter(p=>p.status==='待匹配').length} 人${scope.some(p=>p.status==='待更正')?' · 有待更正人员':''}`:'';
    const peopleMarkup=scope.map(p=>`<p><strong>${e(p.name)} · ${e(p.status)}</strong><br>${e(p.reason)}</p>`).join('');
    const review=ui.data.reviewEntries?.filter(r=>r.sourceId===s.id&&(!r.operationId||ui.data.activeOperations.includes(r.operationId))).at(-1);
    const syncLabel=window.RecruitmentMaterials?.syncStatus(s);
    return `<article class="rw-source-card"><span class="rw-file-icon">${icon('file')}</span><div class="rw-file-copy"><h3>${e(s.name)}</h3><p>${s.attachment?'审批文件':s.comparisonOnly?'核对结果，不参与计算':s.roles?.includes('ledger')?'线下台账':`${(s.recordCount||0).toLocaleString('zh-CN')} 条原始记录`}<span>${e(syncLabel||s.approvalSummary?.label||(!s.active?'已停用':s.error?'读取失败':ui.data.baseline===s.id?'已选期初':scopeStatus?scopeStatus:review?.applied?(review.scopeComplete?'已应用更正':'已部分应用'):review?.status||(s.syncWarnings?.length?`有 ${s.syncWarnings.length} 项接口资料待核对`:'已保存')))}${syncLabel&&s.active&&s.syncWarnings?.length?` · 有 ${s.syncWarnings.length} 项接口资料待核对`:''}</span></p></div><div class="rw-source-actions"><a class="rd-button" href="${base()}/sources/${s.id}" target="_blank" rel="noopener">查看原件</a>${s.kind==='beisen'?`<button class="rd-button" type="button" data-sync-detail="${s.id}">同步详情</button>`:''}${s.attachment?`<button class="rd-button rd-primary" type="button" data-review-source="${s.id}">核对审批调整</button>`:''}${s.roles?.includes('ledger')?`<button class="rd-button" type="button" data-reconcile-source="${s.id}">核对线下结果</button>`:''}${(baseline||s.roles?.includes('ledger'))&&!s.comparisonOnly&&ui.data.baseline!==s.id&&s.active?`<button class="rd-text-button" type="button" data-baseline="${s.id}">选为期初</button>`:''}${!baseline&&ui.data.baseline!==s.id?`<button class="rd-text-button rw-source-toggle" type="button" data-toggle-source="${s.id}">${s.active?'停用':'恢复'}</button>`:''}</div></article>${scope.length?`<section class="rd-inspector-section" aria-label="审批人员处理进度">${peopleMarkup}</section>`:''}`;
  }
  function bindSources(){
    document.querySelectorAll('[data-sync-detail]').forEach(b=>b.onclick=()=>{
      const source=ui.data.sources.find(s=>s.id===b.dataset.syncDetail),warnings=source.syncWarnings||[];
      openDialog('国内资料同步',`<p>查询范围：本批已有国内人员。海外与体系外资料继续上传。</p><p class="rd-message">已保存期初和人工修改仍然保留。下面列出接口未能完整对应的字段，只有影响本月核算时才需要补充。</p>${warnings.length?`<table class="rd-table"><thead><tr><th>工号</th><th>字段</th><th>未采用原因</th></tr></thead><tbody>${warnings.map(x=>`<tr><td>${e(x.employee)}</td><td>${e(LABEL(x.field))}</td><td>${e(x.reason||'尚未识别选项 '+x.code)}</td></tr>`).join('')}</tbody></table><p>可在奖金明细搜索工号，依据原始资料修改对应字段。</p>`:'<p>本次返回的选项和领取人编号均已对应。</p>'}`);
    });
    document.querySelectorAll('[data-review-source]').forEach(b=>b.onclick=()=>window.RecruitmentReviewExtension.approval(b.dataset.reviewSource));
    document.querySelectorAll('[data-reconcile-source]').forEach(b=>b.onclick=()=>{window.RecruitmentReviewCenter.open('differences',b.dataset.reconcileSource);});
    document.querySelectorAll('[data-baseline]').forEach(b=>b.onclick=()=>{const s=ui.data.sources.find(s=>s.id===b.dataset.baseline);openDialog('选择历史台账',`<p>${e(s.name)}</p><p class="rd-message">承接这份台账的历史记录；实际支付状态仍单独保存。</p><button id="rwUseBaseline" type="button" class="rd-button rd-primary">采用这份历史台账</button>`);$('rwUseBaseline').onclick=async()=>{await mutate({baseline:s.id});$('draftInspector').close();};});
    document.querySelectorAll('[data-toggle-source]').forEach(b=>b.onclick=async()=>{const s=ui.data.sources.find(s=>s.id===b.dataset.toggleSource);await mutate({source:{id:s.id,active:!s.active}});});
  }
  function renderSources(sources){
    const ledgers=sources.filter(s=>s.roles?.includes('ledger')),files=sources.filter(s=>!s.roles?.includes('ledger')&&!s.attachment),approvals=sources.filter(s=>s.attachment);
    $('draftContent').innerHTML=`<div class="rw-source-library">${[['线下台账',ledgers],['原始数据',files],['审批与附件',approvals]].filter(([,items])=>items.length).map(([name,items])=>`<section><header><h2>${name}</h2><span>${items.length} 份</span></header>${items.map(s=>sourceCard(s)).join('')}</section>`).join('')}</div>`;bindSources();
  }
  function renderComparison(){
    const ledgers=ui.data.sources.filter(s=>s.active&&!s.error&&s.roles?.includes('ledger'));
    if(!ledgers.length){$('draftContent').innerHTML='<div class="rd-empty"><strong>添加本月核对结果</strong><p>使用上方「添加核对结果」，仅作逐笔比较，不参与试算。</p></div>';return;}
    if(!ledgers.some(s=>s.id===ui.referenceId))ui.referenceId=ledgers.find(s=>s.name.includes(String(ui.data.month)))?.id||ledgers[0].id;
    $('draftContent').innerHTML=`<section class="rw-comparison"><header class="rw-comparison-heading"><div><h2>与线下结果核对</h2><select id="rwReference" aria-label="选择核对台账">${ledgers.map(s=>`<option value="${s.id}" ${s.id===ui.referenceId?'selected':''}>${e(s.name)}</option>`).join('')}</select></div><a class="rd-button" href="${base()}/reconciliation/${ui.referenceId}/export">导出完整差异</a></header><div id="rwComparisonBody"><div class="rd-loading"><span></span><span></span></div></div></section>`;
    $('rwReference').onchange=()=>{ui.referenceId=$('rwReference').value;ui.comparison=null;renderComparison();};
    const id=ui.referenceId,url=base(),revision=ui.data.revision;
    if(ui.comparison?.referenceId===id)return comparisonBody(ui.comparison);
    request(url+'/reconciliation/'+id).then(result=>{if(ui.referenceId!==id||url!==base()||ui.data.revision!==revision)return;ui.comparison=result;comparisonBody(result);}).catch(err=>{if($('rwComparisonBody'))$('rwComparisonBody').innerHTML=`<p class="rw-error">${e(err.message)}</p>`;});
  }
  function comparisonBody(result){
    if(!$('rwComparisonBody'))return;const s=result.monthly.summary;
    $('rwComparisonBody').innerHTML=`<div class="rt-verification"><strong>${ui.data.strictInputs?(ui.data.ruleValidation.passed?'规则检查通过':'规则检查尚未通过'):'此草稿尚未通过独立试算验收'}</strong><button id="rwRuleProblems" class="rd-text-button">查看规则问题</button></div><div class="rw-comparison-stats">${[['线下本月安排',s.referenceNodes||0],['完全一致',s.equalNodes||0],['线下待核',Math.max(0,(s.referenceNodes||0)-(s.equalNodes||0))],['台账本月未列',s.draftOnlyNodes||0]].map(([title,n])=>`<div><span>${title}</span><strong>${n.toLocaleString('zh-CN')}</strong></div>`).join('')}</div><div class="rw-currency-totals">${result.monthly.totalsByCurrency.map(t=>`<div><strong>${e(t.currency)}</strong><span>线下 ${e(fmt(t.reference,'money'))} · 试算 ${e(fmt(t.calculated,'money'))}</span></div>`).join('')}</div><div class="rw-comparison-filter"><label>核对内容<select id="rwDiffType"><option value="monthly">本月发放安排</option><option value="money">全历史规则试算</option><option value="fields">采用字段</option><option value="people">任职对应</option></select></label><label>显示<select id="rwDiffStatus"><option value="all">全部差异</option><option value="number">数值不同</option><option value="missing">无法试算</option><option value="period">发放月份不同</option><option value="currency">币种不同 · ${s.differentCurrencies||0}</option></select></label><details class="rw-comparison-basis"><summary>核对口径</summary><p>${e(result.monthly.basis)}</p></details><span id="rwDiffCount"></span></div><div id="rwDifferences"></div><div class="rw-diff-pager"><button id="rwDiffPrevious" class="rd-button" type="button">上一页</button><span id="rwDiffPage"></span><button id="rwDiffNext" class="rd-button" type="button">下一页</button></div>`;
    if($('rwRuleProblems'))$('rwRuleProblems').onclick=()=>window.RecruitmentTrial?.ruleProblems();
    let page=1;
    function show(){
      const type=$('rwDiffType').value,filter=$('rwDiffStatus').value,isMoney=['monthly','money'].includes(type);
      let rows=type==='monthly'?result.monthly.differences:type==='money'?result.moneyDifferences:type==='fields'?result.fieldDifferences:result.unmatchedPeople;
      if(isMoney&&filter!=='all')rows=rows.filter(d=>filter==='missing'?d.calculated==null:filter==='period'?d.category==='发放月份不同':filter==='currency'?d.category==='币种不同':d.calculated!=null&&d.reference!=null&&d.calculated!==d.reference);
      page=Math.max(1,Math.min(page,Math.ceil(rows.length/40)||1));const visible=rows.slice((page-1)*40,page*40);
      $('rwDiffCount').textContent=`${rows.length} 项`;
      $('rwDifferences').innerHTML=`<table class="rd-table rw-difference-table"><thead><tr><th>候选人</th><th>${type==='people'?'任职信息':'核对项目'}</th><th>线下台账</th><th>${type==='monthly'?'当前试算':type==='money'?'规则试算':'采用值'}</th><th>差异原因与处理</th></tr></thead><tbody>${visible.map((d,index)=>`<tr><td>${e(d.name)}<span>${e(d.employeeId||'无工号')}${d.sourceRow?` · 台账第 ${d.sourceRow} 行`:''}</span></td><td>${e(isMoney?d.kind+' · '+d.item:type==='fields'?LABEL(d.field):d.hireDate)}</td><td>${e(fmt(d.reference,isMoney?'money':'text'))}${isMoney?` ${e(d.currency||'')}`:''}${type==='monthly'?`<span>${d.referencePeriod?'安排 '+e(d.referencePeriod):'本月未安排'}</span>`:''}</td><td>${e(d.calculated==null?'待核对':fmt(d.calculated,isMoney?'money':'text'))}${isMoney?` ${e(d.calculatedCurrency||d.currency||'')}`:''}${type==='monthly'?`<span>安排月份 ${e(d.calculatedPeriod||'待核')}</span>`:''}</td><td><p>${e(label(d.reason||'两份来源的采用字段不同'))}</p>${d.note?`<div class="rw-difference-note"><strong>线下备注</strong><p>${e(d.note)}</p></div>`:''}${d.rowId?`<button class="rd-text-button" data-diff-row="${d.rowId}" data-diff-index="${index}" data-diff-field="${e(d.field||'')}" type="button">${d.category==='发放月份不同'?'核对发放安排':'根据依据修改'}</button><button class="rd-text-button" data-diff-detail="${d.rowId}" type="button">查看分期与依据</button>`:''}</td></tr>`).join('')}</tbody></table>`;
      if(!rows.length)$('rwDifferences').innerHTML=`<div class="rd-empty"><h3>${type==='monthly'&&!result.monthly.differences.length&&s.referenceNodes?'本月 '+s.referenceNodes+' 笔奖金已全部对齐':'当前筛选没有差异'}</h3></div>`;
      $('rwDiffPage').textContent=`第 ${page} / ${Math.ceil(rows.length/40)||1} 页`;$('rwDiffPrevious').disabled=page===1;$('rwDiffNext').disabled=page*40>=rows.length;
      document.querySelectorAll('[data-diff-detail]').forEach(b=>b.onclick=()=>w.inspector(b.dataset.diffDetail));
      document.querySelectorAll('[data-diff-row]').forEach(b=>b.onclick=async()=>{
        const difference=visible[Number(b.dataset.diffIndex)],{row,revision}=await request(base()+'/rows/'+b.dataset.diffRow);
        if(difference.category==='发放月份不同'&&window.RecruitmentTrial){window.RecruitmentTrial.installments(row,revision);return;}
        let field=b.dataset.diffField;
        if(!field){
          if(difference.category==='领取人不同或待核')field=/协助/.test(difference.item)?'协助招聘人工号':/推荐/.test(difference.item)?'推荐人工号':'招聘负责人工号';
          else if(/管培/.test(difference.note||'')&&row.calculation.recruitment.cycle?.exempt)field='协助招聘人工号';
          else if(/起止|启动日/.test(difference.reason||''))field='招聘启动日期';
          else if(/标准待核/.test(difference.reason||''))field='ABC类别';
          else if((/渠道/.test(difference.reason||'')&&!row.values.招聘渠道)||row.values.招聘渠道==='其他')field='招聘渠道';
          else if(/周期/.test(difference.reason||''))field=/管培/.test(difference.note||'')?'管培生已批名单资格':'周期剔除天数';
          else field='转正日期';
        }
        w.editor([row.id],row,revision,{note:difference?.note,field});
      });
    }
    $('rwDiffType').onchange=$('rwDiffStatus').onchange=()=>{page=1;show();};$('rwDiffPrevious').onclick=()=>{page--;show();};$('rwDiffNext').onclick=()=>{page++;show();};show();
  }
  document.addEventListener('recruitment:render',()=>{
    $('draftDropzone').dataset.view=ui.view;
    $('draftSearch').closest('label').hidden=ui.view==='comparison';
    if(ui.view==='todos')$('draftCount').textContent=`${ui.todoGroups.length} 类事项 · 点击左侧事项逐项核对`;
    if(ui.view==='comparison'){$('draftCount').textContent='按人员、采用字段及奖金节点核对';$('draftSummary').hidden=true;}
    if(ui.view==='rows')$('draftCount').textContent+=` · ${visibleColumns().length} 列`;
    // These bindings deliberately replace the old modal-only source navigation.
    bindSources();
  });
  document.addEventListener('recruitment:busy',bindSources);
  window.RecruitmentWorkbenchExtension={renderRows,renderTodos,renderSources,renderComparison,visibleColumns,suggestionMarkup,employmentMarkup,sourceCard,bindSources,reviewPerson};
  if(ui.data)render();
})();
