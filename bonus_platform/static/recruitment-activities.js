(() => {
  'use strict';
  const $=id=>document.getElementById(id),endpoint='/api/recruitment/activities';
  const escape=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const month=m=>`${Math.floor(m/100)}年${String(m%100).padStart(2,'0')}月`;
  const url=a=>`recruitment.html?activity=${encodeURIComponent(a.id)}&month=${String(a.month).slice(0,4)}-${String(a.month).slice(4)}&view=sources`;
  const query=new URLSearchParams(location.search);
  const initialPage=Number(query.get('page'));
  const state={activities:[],legacyRecords:[],scope:query.get('scope')==='legacy'?'legacy':'activities',page:Number.isSafeInteger(initialPage)?Math.max(1,initialPage):1,loading:false,loaded:false,error:'',sequence:0};
  $('activitySearch').value=query.get('q')||'';
  if([...$('activityState').options].some(o=>o.value===query.get('state')))$('activityState').value=query.get('state');
  let opener,submitting=false;
  async function request(path,options){
    let response,data;
    try{response=await fetch(path,options);data=await response.json();}
    catch{const error=new Error(options?'未收到保存结果，请重新读取活动，确认操作是否已完成。':'读取失败，请检查本地服务后重试。');error.uncertain=!!options;throw error;}
    if(!response.ok){const error=new Error(typeof data.detail==='string'?data.detail:'操作未完成，请重试');error.status=response.status;throw error;}return data;
  }
  function remember(){
    if(!state.loaded)return;
    const u=new URL(location.href);['scope','q','month','state','page'].forEach(key=>u.searchParams.delete(key));
    Object.entries({scope:state.scope,q:$('activitySearch').value,month:$('activityMonth').value,state:$('activityState').value,page:state.page}).forEach(([key,value])=>{if(value)u.searchParams.set(key,value);});
    history.replaceState(null,'',u);try{sessionStorage.setItem('recruitment-activity-list',u.searchParams.toString());}catch{}
  }
  function feedback(message){$('activityFeedback').textContent=message;$('activityFeedback').hidden=!message;}
  function render(){
    const legacy=state.scope==='legacy',q=$('activitySearch').value.trim().toLowerCase(),filter=$('activityState').value;
    $('activityStateLabel').hidden=legacy;$('activityNote').hidden=!legacy;
    document.querySelectorAll('[data-scope]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.scope===state.scope)));
    const rows=(legacy?state.legacyRecords:state.activities).filter(a=>(!q||a.name.toLowerCase().includes(q))&&(!$('activityMonth').value||String(a.month)===$('activityMonth').value)&&(legacy||filter==='all'||(filter==='active'?!a.archived:filter==='archived'?a.archived:a.status===filter)));
    const pages=Math.max(1,Math.ceil(rows.length/20));if(state.loaded)state.page=Math.min(state.page,pages);remember();
    $('activityCount').textContent=state.loading?'正在读取…':`${rows.length} ${legacy?'份原核算记录':'个活动'} · 第 ${state.page} / ${pages} 页`;
    $('activityPrev').disabled=state.page<=1;$('activityNext').disabled=state.page>=pages;
    $('activityRefresh').disabled=state.loading;$('activityNew').disabled=state.loading||!!state.error;
    $('activityTable').setAttribute('aria-busy',String(state.loading));
    if(state.error){$('activityTable').innerHTML=`<div class="ra-empty"><h2>暂时无法读取活动</h2><p>${escape(state.error)}</p><button class="rd-button" id="activityRetry">重试</button></div>`;$('activityRetry').onclick=load;return;}
    if(state.loading&&!state.loaded){$('activityTable').innerHTML='<div class="rd-loading" role="status"><p>正在读取活动…</p><span aria-hidden="true"></span><span aria-hidden="true"></span><span aria-hidden="true"></span></div>';return;}
    if(!rows.length){
      const fresh=!legacy&&!state.activities.length;
      $('activityTable').innerHTML=`<div class="ra-empty"><span class="ra-empty-mark" aria-hidden="true"><svg class="rd-icon" aria-hidden="true"><use href="#icon-${fresh?'plus':'search'}"/></svg></span><h2>${fresh?'从一次核算活动开始':'没有符合条件的记录'}</h2><p>${fresh?'选择核算月份，开始导入资料。':'请调整月份、状态或搜索条件。'}</p>${fresh?'<button class="rd-button rd-primary" id="activityFirst">新建核算活动</button>':'<button class="rd-button" id="activityClear">清除筛选</button>'}${fresh&&state.legacyRecords.length?`<button class="rd-text-button" id="activityLegacy">查看 ${state.legacyRecords.length} 份原核算记录</button>`:''}</div>`;
      $('activityFirst')?.addEventListener('click',create);$('activityLegacy')?.addEventListener('click',()=>scope('legacy'));
      $('activityClear')?.addEventListener('click',()=>{$('activitySearch').value='';$('activityMonth').value='';$('activityState').value='all';render();});return;
    }
    $('activityTable').innerHTML=`<table class="ra-table"><thead><tr><th>核算月份</th><th>${legacy?'记录名称':'活动名称'}</th><th>人员 / 资料</th><th>状态</th><th>最近更新</th><th>操作</th></tr></thead><tbody>${rows.slice((state.page-1)*20,state.page*20).map(a=>`<tr><td>${month(a.month)}</td><td><a class="ra-name" href="${escape(a.url||url(a))}" title="${escape(a.name)}">${escape(a.name)}</a>${a.records?`<span class="ra-meta">${a.records} 份历史记录</span>`:''}</td><td>${a.people} 人<span class="ra-meta">${a.sources} 份资料</span></td><td><span class="ra-status" data-status="${escape(a.status)}">${escape(a.status)}</span></td><td>${escape(a.updatedAt?.replace('T',' ').slice(0,16)||'—')}</td><td><div class="ra-actions"><a class="ra-enter" href="${escape(a.url||url(a))}">${a.archived?'查看':'进入核算'}<svg class="rd-icon" aria-hidden="true"><use href="#icon-right"/></svg></a>${!legacy?`<button type="button" class="ra-manage" data-manage="${a.id}" aria-label="管理 ${escape(a.name)}"><svg class="rd-icon" aria-hidden="true"><use href="#icon-more"/></svg></button>`:''}</div></td></tr>`).join('')}</tbody></table>`;
    document.querySelectorAll('[data-manage]').forEach(b=>b.onclick=()=>manage(state.activities.find(a=>a.id===b.dataset.manage)));
  }
  function scope(value){state.scope=value;state.page=1;$('activityMonth').value='';render();}
  async function load(){
    const seq=++state.sequence;state.loading=true;state.error='';render();
    try{const data=await request(endpoint);if(seq!==state.sequence)return;state.activities=data.activities;state.legacyRecords=data.legacyRecords;
      const selected=state.loaded?$('activityMonth').value:query.get('month'),months=[...new Set([...state.activities,...state.legacyRecords].map(a=>a.month))].sort((a,b)=>b-a);
      $('activityMonth').innerHTML='<option value="">全部月份</option>'+months.map(m=>`<option value="${m}">${month(m)}</option>`).join('');$('activityMonth').value=months.includes(Number(selected))?selected:'';
      state.loaded=true;
    }catch(err){if(seq===state.sequence)state.error=err.message;}finally{if(seq===state.sequence){state.loading=false;render();}}
  }
  function dialog(title,fields,submit){opener=document.activeElement;submitting=false;$('activityDialogTitle').textContent=title;$('activityFields').innerHTML=fields;$('activitySubmit').textContent=submit;$('activitySubmit').disabled=false;$('activityError').textContent='';$('activityReload').hidden=true;$('activityReload').onclick=async()=>{close();await load();feedback('活动已重新读取，请核对最新状态后再操作。');};$('activityCancel').textContent='取消';$('activityCancel').onclick=close;$('activityDialog').showModal();}
  function close(){if(!submitting)$('activityDialog').close();}
  async function perform(action){
    if(submitting)return;submitting=true;$('activityError').textContent='';$('activityReload').hidden=true;
    const controls=[...$('activityForm').querySelectorAll('button,input,select')].map(node=>({node,disabled:node.disabled})),label=$('activitySubmit').textContent;
    controls.forEach(({node})=>node.disabled=true);$('activityForm').setAttribute('aria-busy','true');$('activitySubmit').textContent='正在保存…';
    let stale=false;
    try{await action();}catch(err){$('activityError').textContent=err.message;stale=err.status===409||err.uncertain;$('activityReload').hidden=!stale;}
    finally{submitting=false;controls.forEach(({node,disabled})=>node.disabled=disabled);$('activityForm').setAttribute('aria-busy','false');$('activitySubmit').textContent=label;if(stale)$('activitySubmit').disabled=true;}
  }
  let libraryView=0;
  const libraryEndpoint=endpoint+'/snapshot-library';
  const localTime=value=>value?new Date(value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}):'尚未同步';
  function snapshotText(data){
    return ['domestic','overseas'].map(name=>{
      const s=data.snapshots[name],status=data.job.sources?.[name];
      return `${name==='domestic'?'国内':'海外'}：${s?`采集于 ${localTime(s.queriedAt)}，花名册 ${s.rosterCount} 条、Offer ${s.offerCount} 份`:'尚无公共资料'}${status?.status==='failed'?'；更新失败，'+(status.message||'请重试'):''}`;
    }).join('；');
  }
  function library(){
    const view=++libraryView,now=new Date(),period=new Date(now.getFullYear(),now.getMonth()-1,1).toLocaleDateString('sv-SE').slice(0,7);
    dialog('公共资料同步','<label>奖金所属月份<input id="libraryMonth" type="month" required min="2000-01" max="2099-12" /></label><p id="libraryStatus" role="status">正在读取同步状态…</p><p>更新后的公共资料供新建活动使用。已有活动可在资料页手动更新。</p><label class="ra-checkbox"><input id="libraryEnabled" type="checkbox" /> 每天自动同步</label><label>北京时间<input id="libraryTime" type="time" value="08:00" required /></label><button id="libraryScheduleSave" class="rd-button" type="button">保存定时设置</button><p id="libraryScheduleStatus" role="status"></p>','立即同步所选月份');
    $('libraryMonth').value=period;
    let selected=0,configured=false;
    async function loadLibrary(){
      const month=Number($('libraryMonth')?.value.replace('-','')),seq=++selected;
      try{
        const data=await request(libraryEndpoint+'/'+month);
        if(view!==libraryView||seq!==selected||!$('activityDialog').open||!$('libraryStatus'))return;
        $('libraryStatus').textContent=snapshotText(data)+(!['idle','complete'].includes(data.job.status)?`；${data.job.message}`:'');
        $('activitySubmit').disabled=data.job.status==='running';
        if(!configured){$('libraryEnabled').checked=data.schedule.enabled;$('libraryTime').value=`${String(data.schedule.hour).padStart(2,'0')}:${String(data.schedule.minute).padStart(2,'0')}`;configured=true;}
        $('libraryScheduleStatus').textContent=data.schedule.running?(data.schedule.enabled?'服务运行期间按北京时间定时同步，错过时间会在启动后补跑。':'自动同步已暂停。'):'后台定时服务未运行，请启动工作台服务。';
        if(data.job.status==='running')setTimeout(()=>{if(view===libraryView&&seq===selected&&$('activityDialog').open&&$('libraryMonth'))loadLibrary(true);},1500);
      }catch(err){if(view===libraryView&&seq===selected&&$('libraryStatus'))$('libraryStatus').textContent=err.message;}
    }
    $('libraryMonth').onchange=()=>loadLibrary();
    $('libraryScheduleSave').onclick=()=>perform(async()=>{
      const [hour,minute]=$('libraryTime').value.split(':').map(Number);
      await request(libraryEndpoint+'/schedule',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:$('libraryEnabled').checked,hour,minute})});
      $('libraryScheduleStatus').textContent='定时设置已保存。';
    });
    $('activityForm').onsubmit=ev=>{ev.preventDefault();perform(async()=>{
      await request(libraryEndpoint+'/'+Number($('libraryMonth').value.replace('-',''))+'/refresh',{method:'POST'});
      setTimeout(()=>loadLibrary(true),100);
    });};
    loadLibrary();
  }
  function create(){
    const view=++libraryView;
    const now=new Date(),current=new Date(now.getFullYear(),now.getMonth()-1,1).toLocaleDateString('sv-SE').slice(0,7);
    dialog('新建核算活动','<div class="ra-month-field"><label for="activityNewMonth">奖金所属月份</label><input id="activityNewMonth" type="month" required min="2000-01" max="2099-12" /></div><p>默认核算上月奖金；回算历史奖金时，选择对应月份。</p><p id="activitySnapshotNote" role="status"></p><label id="activityOpeningField" hidden>承接上月结果<select id="activityOpening"></select></label><p id="activityOpeningNote"></p><label>活动名称<input id="activityName" maxlength="60" /></label>','创建并进入');
    $('activityNewMonth').value=current;
    window.RecruitmentUI.monthPicker($('activityNewMonth'),{inline:true}).focus();
    function options(){const m=Number($('activityNewMonth').value.replace('-','')),previous=m%100===1?(Math.floor(m/100)-1)*100+12:m-1;
      const previousActivities=state.activities.filter(a=>a.month===previous&&a.confirmedRevision);
      $('activityOpening').innerHTML=(previousActivities.length>1?'<option value="">请选择上月确认结果</option>':'')+previousActivities.map(a=>`<option value="${a.id}">${escape(a.name)} · 已确认版本 ${a.confirmedRevision}</option>`).join('')+'<option value="manual">自行导入上月表</option>';
      $('activityOpening').required=previousActivities.length>1;
      $('activityOpeningField').hidden=!previousActivities.length;
      $('activityOpeningNote').textContent=previousActivities.length===1?'已选中上月确认结果，历史未结奖金和已保存的处理将随活动承接。':previousActivities.length>1?'上月有多份确认结果，请选择本次要承接的一份。':'首次核算这个月份时，请导入上月核算表作为历史奖金起点；确无未结奖金可进入后确认。';
      $('activityName').placeholder=`${month(m)}招聘与内推奖金`;
      $('activitySnapshotNote').textContent='正在检查已同步资料…';
      request(libraryEndpoint+'/'+m).then(data=>{
        if(view!==libraryView||!$('activitySnapshotNote')||Number($('activityNewMonth').value.replace('-',''))!==m)return;
        $('activitySnapshotNote').textContent=Object.keys(data.snapshots).length?`创建时自动采用。${snapshotText(data)}`:'此月份尚无公共资料，创建后可手动同步；也可先在活动列表的「资料同步」中预取。';
      }).catch(()=>{if(view===libraryView&&$('activitySnapshotNote'))$('activitySnapshotNote').textContent='暂时无法检查公共资料，创建后可查看资料并手动更新。';});}
    $('activityNewMonth').onchange=options;options();
    $('activityForm').onsubmit=ev=>{ev.preventDefault();const selected=state.activities.find(a=>a.id===$('activityOpening').value),payload={month:Number($('activityNewMonth').value.replace('-','')),name:$('activityName').value.trim(),...(selected?{opening:{activityId:selected.id,revision:selected.confirmedRevision}}:{})};perform(async()=>{const activity=await request(endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});location.href=url(activity);});};
  }
  function manage(a){
    ++libraryView;
    dialog('管理活动',`<label>活动名称<input id="activityName" required maxlength="60" value="${escape(a.name)}" /></label><p>${month(a.month)} · ${escape(a.status)}</p><div class="ra-archive"><p>${a.archived?'恢复后可继续核算。':'归档后仅可查看，可随时恢复。'}</p><button type="button" class="rd-button" id="activityArchive">${a.archived?'恢复活动':'归档活动'}</button></div>`,'保存名称');
    const update=payload=>perform(async()=>{await request(endpoint+'/'+a.id,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({version:a.version,...payload})});$('activityDialog').close();feedback(payload.archived===true?'已归档，资料和结果均保留。可在「已归档」筛选中恢复。':payload.archived===false?'已恢复，可在「未归档」列表继续核算。':'活动名称已保存。');await load();document.querySelector(`[data-manage="${a.id}"]`)?.focus();});
    $('activityForm').onsubmit=ev=>{ev.preventDefault();update({name:$('activityName').value.trim()});};
    $('activityArchive').onclick=()=>update({archived:!a.archived});
  }
  document.querySelectorAll('[data-scope]').forEach(b=>b.onclick=()=>scope(b.dataset.scope));
  ['activitySearch','activityMonth','activityState'].forEach(id=>$(id).addEventListener(id==='activitySearch'?'input':'change',()=>{state.page=1;render();}));
  $('activityPrev').onclick=()=>{state.page--;render();};$('activityNext').onclick=()=>{state.page++;render();};$('activityRefresh').onclick=load;$('activityNew').onclick=create;$('activitySync').onclick=library;
  $('activityClose').onclick=close;$('activityCancel').onclick=close;$('activityDialog').addEventListener('cancel',ev=>{if(submitting)ev.preventDefault();});$('activityDialog').addEventListener('close',()=>{if(!$('activityDialog').open)(opener?.isConnected?opener:$('activityNew')).focus();});
  load().then(()=>{if(query.get('new')==='1'&&!state.error){const u=new URL(location.href);u.searchParams.delete('new');history.replaceState(null,'',u);create();}});
})();
