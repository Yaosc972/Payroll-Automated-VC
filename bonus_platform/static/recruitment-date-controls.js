/* Date controls share the workbench surface while retaining native form values. */
(() => {
  'use strict';
  const iso=date=>`${String(date.getUTCFullYear()).padStart(4,'0')}-${String(date.getUTCMonth()+1).padStart(2,'0')}-${String(date.getUTCDate()).padStart(2,'0')}`;
  function date(year,month,day=1){const value=new Date(0);value.setUTCHours(12,0,0,0);value.setUTCFullYear(year,month,day);return value;}
  function parse(value){
    const raw=String(value||'').trim();
    const match=raw.match(/^(\d{4})(\d{2})(\d{2})$/)||raw.match(/^(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})日?$/);
    if(!match)return null;
    const [year,month,day]=match.slice(1).map(Number),result=date(year,month-1,day);
    return year>=1&&year<=9999&&result.getUTCFullYear()===year&&result.getUTCMonth()===month-1&&result.getUTCDate()===day?iso(result):null;
  }
  function addDays(value,days){const d=new Date(value+'T12:00:00Z');d.setUTCDate(d.getUTCDate()+days);return iso(d);}
  function addMonths(value,months){
    const d=new Date(value+'T12:00:00Z'),last=date(d.getUTCFullYear(),d.getUTCMonth()+months+1,0).getUTCDate();
    return iso(date(d.getUTCFullYear(),d.getUTCMonth()+months,Math.min(d.getUTCDate(),last)));
  }
  function monthDays(year,month){const first=date(year,month),start=new Date(first);start.setUTCDate(1-first.getUTCDay());return Array.from({length:42},(_,i)=>iso(date(start.getUTCFullYear(),start.getUTCMonth(),start.getUTCDate()+i)));}
  if(typeof document==='undefined'){if(typeof module!=='undefined')module.exports={parse,addDays,addMonths,monthDays};return;}
  const controls=new Map();let opened=null,sequence=0,queued=false;
  const icon=name=>`<svg class="rd-icon" aria-hidden="true"><use href="#icon-${name}"/></svg>`;
  const today=()=>{const d=new Date();return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;};
  const allowed=(c,value)=>!!parse(value)&&(!c.input.min||value>=c.input.min)&&(!c.input.max||value<=c.input.max);
  function close(restore=false){
    if(!opened)return;
    const c=opened;opened=null;
    if(c.panel.matches(':popover-open'))c.panel.hidePopover();
    c.button.setAttribute('aria-expanded','false');
    if(restore&&c.text.isConnected)c.text.focus({preventScroll:true});
  }
  function sync(c,force=false){
    const input=c.input,disabled=input.disabled||input.matches(':disabled');
    c.text.disabled=disabled;c.text.readOnly=input.readOnly;c.text.required=input.required;
    c.button.disabled=disabled||input.readOnly;c.root.hidden=input.hidden;
    if(force||c.lastValue!==input.value){c.text.value=input.value;c.lastValue=input.value;c.text.setCustomValidity('');}
    if(opened===c&&(c.button.disabled||!c.root.getClientRects().length))close();
  }
  function commit(c,value,manual=false){
    const parsed=parse(value),empty=!value.trim();
    c.text.setCustomValidity(empty?'':!parsed?'请输入有效日期':!allowed(c,parsed)?'日期超出可选范围':'');
    c.input.value=parsed||'';c.lastValue=c.input.value;
    if(!manual||parsed)c.text.value=parsed||'';
    c.writing=true;
    c.input.dispatchEvent(new Event('input',{bubbles:true}));
    c.input.dispatchEvent(new Event('change',{bubbles:true}));c.writing=false;
  }
  function choose(c,value){if(value&&!allowed(c,value))return;commit(c,value);close(true);}
  function position(c){
    const box=c.root.getBoundingClientRect(),panel=c.panel;
    panel.style.width='300px';panel.style.maxHeight=`${innerHeight-24}px`;
    const up=innerHeight-box.bottom-12<panel.offsetHeight&&box.top>innerHeight-box.bottom;
    panel.style.left=`${Math.max(12,Math.min(box.left,innerWidth-panel.offsetWidth-12))}px`;
    panel.style.top=`${Math.max(12,up?box.top-panel.offsetHeight-6:Math.min(box.bottom+6,innerHeight-panel.offsetHeight-12))}px`;
  }
  function render(c,focus=false){
    const y=c.year,m=c.month,selected=c.input.value,now=today(),minYear=Number(c.input.min?.slice(0,4)||1),maxYear=Number(c.input.max?.slice(0,4)||9999);
    let title,body;
    if(c.mode==='days'){
      title=`${y}年${m+1}月`;
      const days=monthDays(y,m);
      body=`<div class="rc-date-week" aria-hidden="true">${['日','一','二','三','四','五','六'].map(d=>`<span>${d}</span>`).join('')}</div><div class="rc-date-grid" role="grid" aria-label="${title}">${Array.from({length:6},(_,week)=>`<div role="row">${days.slice(week*7,week*7+7).map(value=>`<button type="button" class="rc-date-day" role="gridcell" data-date="${value}" aria-label="${Number(value.slice(0,4))}年${Number(value.slice(5,7))}月${Number(value.slice(8))}日" aria-selected="${value===selected}" ${value===now?'aria-current="date"':''} data-outside="${Number(value.slice(5,7))!==m+1}" tabindex="${value===c.focusDate?0:-1}" ${allowed(c,value)?'':'disabled'}>${Number(value.slice(8))}</button>`).join('')}</div>`).join('')}</div>`;
    }else if(c.mode==='months'){
      title=`${y}年`;
      body=`<div class="rc-date-choices" role="group" aria-label="选择月份">${Array.from({length:12},(_,i)=>{const first=iso(date(y,i)),last=iso(date(y,i+1,0)),disabled=c.input.min&&last<c.input.min||c.input.max&&first>c.input.max;return `<button type="button" data-month="${i}" aria-pressed="${i===m}" ${disabled?'disabled':''}>${i+1}月</button>`;}).join('')}</div>`;
    }else{
      const first=Math.max(1,Math.floor((y-1)/12)*12+1);title=`${first}–${Math.min(9999,first+11)}年`;
      body=`<div class="rc-date-choices" role="group" aria-label="选择年份">${Array.from({length:12},(_,i)=>first+i).map(year=>`<button type="button" data-year="${year}" aria-pressed="${year===y}" ${year<minYear||year>maxYear?'disabled':''}>${year}</button>`).join('')}</div>`;
    }
    const firstVisible=c.mode==='days'?iso(date(y,m)):iso(date(y,0)),lastVisible=c.mode==='days'?iso(date(y,m+1,0)):iso(date(y,12,0));
    c.panel.innerHTML=`<div class="rc-date-header"><button type="button" data-nav="-1" aria-label="${c.mode==='days'?'上个月':c.mode==='months'?'上一年':'上一组年份'}" ${y<=minYear&&(c.mode!=='days'||m===0)||c.input.min&&firstVisible<=c.input.min?'disabled':''}>${icon('left')}</button><button type="button" class="rc-date-heading" data-view aria-live="polite">${title}${icon('chevron')}</button><button type="button" data-nav="1" aria-label="${c.mode==='days'?'下个月':c.mode==='months'?'下一年':'下一组年份'}" ${y>=maxYear&&(c.mode!=='days'||m===11)||c.input.max&&lastVisible>=c.input.max?'disabled':''}>${icon('right')}</button></div>${body}<div class="rc-date-footer"><button type="button" data-clear>清除</button><button type="button" data-today ${allowed(c,now)?'':'disabled'}>今天</button></div>`;
    if(opened===c)position(c);
    if(focus)(c.panel.querySelector(`[data-date="${c.focusDate}"]:not(:disabled)`)||c.panel.querySelector('[data-date]:not(:disabled)')||c.panel.querySelector('[data-view]'))?.focus({preventScroll:true});
  }
  function open(c){
    close();sync(c);if(c.button.disabled)return;
    const month=String(window.RecruitmentWorkbench?.ui.data?.month||'');
    let value=parse(c.input.value)||(month.length===6?`${month.slice(0,4)}-${month.slice(4)}-01`:today());
    if(c.input.min&&value<c.input.min)value=c.input.min;if(c.input.max&&value>c.input.max)value=c.input.max;
    c.year=Number(value.slice(0,4));c.month=Number(value.slice(5,7))-1;c.focusDate=value;c.mode='days';
    (c.input.closest('dialog')||document.body).append(c.panel);render(c);opened=c;
    c.panel.showPopover();c.button.setAttribute('aria-expanded','true');position(c);render(c,true);
    window.RecruitmentInteractions?.enter(c.panel);
  }
  function enhance(input){
    if(controls.has(input))return;
    const root=document.createElement('span');root.className='rc-date';
    const text=document.createElement('input');text.type='text';text.className='rc-date-input';text.placeholder='YYYY-MM-DD';text.inputMode='numeric';text.autocomplete='off';text.id=`rc-date-input-${++sequence}`;
    const labels=[...input.labels||[]];labels.forEach((label,i)=>label.id||=text.id+'-label-'+i);
    const label=input.getAttribute('aria-label')||labels.map(l=>{const copy=l.cloneNode(true);copy.querySelectorAll('input,button,select,.rc-date').forEach(n=>n.remove());return copy.textContent.trim();}).join(' ')||'日期';
    text.setAttribute('aria-label',label);
    const button=document.createElement('button');button.type='button';button.className='rc-date-trigger';button.innerHTML=icon('calendar');button.setAttribute('aria-label','选择'+label);button.setAttribute('aria-haspopup','dialog');button.setAttribute('aria-expanded','false');
    const panel=document.createElement('div');panel.className='rc-date-popover';panel.id=`rc-date-panel-${sequence}`;panel.setAttribute('popover','manual');panel.setAttribute('role','dialog');panel.setAttribute('aria-label','选择'+label);button.setAttribute('aria-controls',panel.id);
    input.after(root);root.append(text,button);
    const c={input,root,text,button,panel,lastValue:null,writing:false,tabIndex:input.getAttribute('tabindex'),ariaHidden:input.getAttribute('aria-hidden')};
    input.classList.add('rc-date-native');input.tabIndex=-1;input.setAttribute('aria-hidden','true');controls.set(input,c);
    text.oninput=()=>commit(c,text.value,true);text.onblur=()=>{if(parse(text.value))text.value=parse(text.value);};
    button.onclick=()=>opened===c?close(true):open(c);
    text.onkeydown=event=>{if(event.key==='ArrowDown'&&event.altKey){event.preventDefault();open(c);}if(event.key==='Escape'&&opened===c){event.preventDefault();event.stopPropagation();close(true);}};
    c.onFocus=()=>text.focus({preventScroll:true});input.addEventListener('focus',c.onFocus);
    c.onClick=event=>{event.preventDefault();text.focus({preventScroll:true});};input.addEventListener('click',c.onClick);
    c.onChange=()=>{if(!c.writing)sync(c,true);};input.addEventListener('input',c.onChange);input.addEventListener('change',c.onChange);
    c.onInvalid=event=>{event.preventDefault();text.setCustomValidity(input.validationMessage);text.focus();text.reportValidity();};input.addEventListener('invalid',c.onInvalid);
    panel.onclick=event=>{
      const target=event.target.closest('button');if(!target||target.disabled)return;
      if(target.hasAttribute('data-date'))return choose(c,target.dataset.date);
      if(target.hasAttribute('data-clear'))return choose(c,'');
      if(target.hasAttribute('data-today'))return choose(c,today());
      if(target.hasAttribute('data-view'))c.mode=c.mode==='days'?'months':c.mode==='months'?'years':'months';
      if(target.hasAttribute('data-month')){c.month=Number(target.dataset.month);c.mode='days';c.focusDate=iso(date(c.year,c.month));}
      if(target.hasAttribute('data-year')){c.year=Number(target.dataset.year);c.mode='months';}
      if(target.hasAttribute('data-nav')){
        const offset=Number(target.dataset.nav);
        if(c.mode==='days'){const d=date(c.year,c.month+offset);c.year=d.getUTCFullYear();c.month=d.getUTCMonth();c.focusDate=iso(d);}
        else c.year=Math.max(1,Math.min(9999,c.year+offset*(c.mode==='years'?12:1)));
      }
      render(c,target.hasAttribute('data-month'));
      if(c.mode!=='days')(c.panel.querySelector('[aria-pressed=true]:not(:disabled)')||c.panel.querySelector('.rc-date-choices button:not(:disabled)'))?.focus({preventScroll:true});
      else if(target.hasAttribute('data-nav'))(c.panel.querySelector(`[data-nav="${target.dataset.nav}"]:not(:disabled)`)||c.panel.querySelector('[data-view]'))?.focus({preventScroll:true});
    };
    panel.onkeydown=event=>{
      if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close(true);return;}
      const target=event.target.closest('[data-date]');if(!target)return;
      const offsets={ArrowLeft:-1,ArrowRight:1,ArrowUp:-7,ArrowDown:7};let value;
      if(event.key in offsets)value=addDays(target.dataset.date,offsets[event.key]);
      if(event.key==='Home')value=addDays(target.dataset.date,-new Date(target.dataset.date+'T12:00:00Z').getUTCDay());
      if(event.key==='End')value=addDays(target.dataset.date,6-new Date(target.dataset.date+'T12:00:00Z').getUTCDay());
      if(event.key==='PageUp'||event.key==='PageDown')value=addMonths(target.dataset.date,(event.key==='PageUp'?-1:1)*(event.shiftKey?12:1));
      if(value){event.preventDefault();if(!allowed(c,value))return;c.focusDate=value;c.year=Number(value.slice(0,4));c.month=Number(value.slice(5,7))-1;render(c,true);}
    };
    sync(c);
  }
  function scan(){
    queued=false;
    controls.forEach((c,input)=>{
      if(!input.isConnected||input.type!=='date'){
        if(opened===c)close();c.root.remove();c.panel.remove();input.classList.remove('rc-date-native');
        input.removeEventListener('focus',c.onFocus);input.removeEventListener('click',c.onClick);input.removeEventListener('input',c.onChange);input.removeEventListener('change',c.onChange);input.removeEventListener('invalid',c.onInvalid);
        if(c.tabIndex===null)input.removeAttribute('tabindex');else input.setAttribute('tabindex',c.tabIndex);
        if(c.ariaHidden===null)input.removeAttribute('aria-hidden');else input.setAttribute('aria-hidden',c.ariaHidden);controls.delete(input);
      }else sync(c);
    });
    document.querySelectorAll('input[type=date]:not(.rc-date-native)').forEach(enhance);
  }
  function schedule(){if(!queued){queued=true;queueMicrotask(scan);}}
  new MutationObserver(records=>{if(records.some(r=>r.target.matches?.('input[type=date]')||r.target.querySelector?.('input[type=date]')||[...r.addedNodes,...r.removedNodes].some(n=>n.nodeType===1&&(n.matches('input[type=date]')||n.querySelector('input[type=date]')))))schedule();}).observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['disabled','readonly','required','min','max','hidden','value','type']});
  document.addEventListener('pointerdown',event=>{if(opened&&!opened.root.contains(event.target)&&!opened.panel.contains(event.target))close();});
  document.addEventListener('focusin',event=>{if(opened&&!opened.root.contains(event.target)&&!opened.panel.contains(event.target))close();});
  document.addEventListener('close',()=>close(),true);
  document.addEventListener('scroll',event=>{if(opened&&!opened.panel.contains(event.target))close();},true);
  window.addEventListener('resize',()=>close());
  document.addEventListener('recruitment:render',schedule);document.addEventListener('recruitment:busy',schedule);
  document.addEventListener('change',schedule);
  document.addEventListener('reset',()=>requestAnimationFrame(()=>{scan();controls.forEach(c=>sync(c,true));}));
  scan();
})();
