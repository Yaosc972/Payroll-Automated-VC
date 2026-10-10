'use strict';
(() => {
  const shapes = {
    download:'<path d="M12 3v12m-4-4 4 4 4-4M5 16v4a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-4"/>',
    details:'<path d="M13 3H5v18h7M13 3v5h6V8l-6-5M8 12h4M8 16h2"/><circle cx="17" cy="16" r="3"/><path d="m19.2 18.2 2.3 2.3"/>',
    guide:'<path d="M12 5v16M3 4c3-1 6-1 9 1 3-2 6-2 9-1v15c-3-1-6-1-9 2-3-3-6-3-9-2ZM6 8h3M15 8h3M6 12h3M15 12h3"/>',
    copy:'<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M15 9V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h4"/>',
    check:'<path d="m5 12 4 4L19 6"/>',
    close:'<path d="m6 6 12 12M18 6 6 18"/>',
    chevron:'<path d="m7 10 5 5 5-5"/>',
    left:'<path d="m14 6-6 6 6 6"/>',
    right:'<path d="m10 6 6 6-6 6"/>',
    sort:'<path d="M8 3v18m-4-4 4 4 4-4M16 21V3m-4 4 4-4 4 4"/>',
    recent:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    grid:'<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    calendar:'<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M7 3v4M17 3v4M3 10h18M7 14h2M15 14h2M7 17h2"/>',
  };
  const icon = name => `<svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${shapes[name] || ''}</svg>`;
  const escape = value => String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const controllers = new WeakMap();
  let active = null, subjectArtwork = {};

  function closeMenu(restoreFocus=false) {
    if (!active) return;
    const control = active;
    active = null;
    control.popup.remove();
    control.trigger.setAttribute('aria-expanded','false');
    control.trigger.removeAttribute('aria-activedescendant');
    if (restoreFocus && control.trigger.isConnected) control.trigger.focus();
  }
  function place(control) {
    const rect = control.trigger.getBoundingClientRect();
    const popup = control.popup;
    const width = Math.min(control.month ? 280 : Math.max(rect.width, control.native.id === 'sort' ? 192 : 220), innerWidth-24);
    popup.style.width = `${width}px`;
    popup.style.left = `${Math.max(12, Math.min(rect.left, innerWidth-width-12))}px`;
    const height = popup.getBoundingClientRect().height;
    const below = innerHeight - rect.bottom - 12, above = rect.top - 12;
    popup.style.top = `${below >= height || below >= above ? rect.bottom+6 : Math.max(12,rect.top-height-6)}px`;
    popup.style.maxHeight = `${Math.max(80,Math.max(below,above)-6)}px`;
  }
  function commit(control, value) {
    const changed = control.native.value !== value;
    closeMenu();
    control.native.value = value;
    control.sync();
    if (changed) control.native.dispatchEvent(new Event('change',{bubbles:true}));
    // The guide re-renders after a choice; restore focus to its replacement.
    document.getElementById(`${control.native.id}Trigger`)?.focus();
  }
  function open(control) {
    if (control.native.disabled) return;
    closeMenu();
    active = control;
    control.trigger.setAttribute('aria-expanded','true');
    control.build();
    document.body.append(control.popup);
    place(control);
  }
  function controlFor(native, month=false) {
    const wrapper = document.createElement('span');
    wrapper.className = `ui-control ${month ? 'ui-month' : 'ui-select'}`;
    wrapper.dataset.control = native.id;
    native.before(wrapper);
    wrapper.append(native);
    native.hidden = true;
    native.tabIndex = -1;
    const trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.id = `${native.id}Trigger`;
    trigger.className = 'ui-trigger';
    trigger.setAttribute('aria-expanded','false');
    trigger.setAttribute('aria-haspopup',month ? 'dialog' : 'listbox');
    trigger.setAttribute('aria-controls',`${native.id}Popup`);
    if (!month) trigger.setAttribute('role','combobox');
    wrapper.append(trigger);
    const popup = document.createElement('div');
    popup.id = `${native.id}Popup`;
    popup.className = `ui-popup ${month ? 'ui-month-popup' : 'ui-select-popup'}`;
    popup.setAttribute('role',month ? 'dialog' : 'listbox');
    const label = native.id === 'sort' ? '排序' : month ? '核算月份' : '科目';
    popup.setAttribute('aria-label',label);
    const control = {native,trigger,popup,month,label};
    control.sync = () => {
      const text = month ? native.value.replace('-', ' 年 ')+' 月' : native.selectedOptions[0]?.textContent || '';
      const artwork = !month && native.selectedOptions[0]?.dataset.icon;
      const leading = artwork && subjectArtwork[artwork]
        ? `<span class="ui-subject-icon" data-icon="${escape(artwork)}">${subjectArtwork[artwork]}</span>`
        : icon(month ? 'calendar' : native.value === 'recent' ? 'recent' : 'sort');
      trigger.innerHTML = `${leading}<span class="ui-control-value">${escape(text)}</span>${icon('chevron')}`;
      trigger.disabled = native.disabled;
      trigger.setAttribute('aria-label',`${label}：${text}`);
      trigger.title = text;
      if (native.disabled && active === control) closeMenu();
    };
    trigger.addEventListener('click',()=>{if(active===control)closeMenu();else open(control);});
    native.addEventListener('change',control.sync);
    controllers.set(native,control);
    control.sync();
    return control;
  }
  function enhanceSelect(native) {
    const control = controlFor(native);
    let current=0, buffer='', typedAt=0;
    const options = () => [...native.options].filter(option=>!option.disabled);
    const activate = index => {
      const rows=[...control.popup.querySelectorAll('[role="option"]')];
      current=Math.max(0,Math.min(index,rows.length-1));
      rows.forEach((row,i)=>row.classList.toggle('active',i===current));
      const row=rows[current];
      if(row){control.trigger.setAttribute('aria-activedescendant',row.id);row.scrollIntoView({block:'nearest'});}
    };
    control.build = () => {
      const rows=options();
      control.popup.innerHTML=rows.map((option,i)=>{
        const artwork=option.dataset.icon;
        const leading=artwork && subjectArtwork[artwork]
          ? `<span class="ui-subject-icon" data-icon="${escape(artwork)}">${subjectArtwork[artwork]}</span>`
          : icon(option.value==='recent'?'recent':'sort');
        return `<div id="${native.id}Option${i}" role="option" aria-selected="${option.value===native.value}" class="ui-option">${leading}<span>${escape(option.textContent)}</span><span class="ui-option-check">${icon('check')}</span></div>`;
      }).join('');
      [...control.popup.children].forEach((row,i)=>{
        row.addEventListener('pointermove',()=>activate(i));
        row.addEventListener('pointerdown',event=>event.preventDefault());
        row.addEventListener('click',()=>commit(control,rows[i].value));
      });
      current=Math.max(0,rows.findIndex(option=>option.value===native.value));
      queueMicrotask(()=>{if(active===control)activate(current);});
    };
    control.trigger.addEventListener('keydown',event=>{
      const opened=active===control;
      if(['ArrowDown','ArrowUp','Home','End','Enter',' '].includes(event.key)){
        event.preventDefault();
        if(!opened){open(control);if(event.key==='Home')activate(0);if(event.key==='End')activate(options().length-1);}
        else if(event.key==='Enter'||event.key===' ')commit(control,options()[current].value);
        else activate(event.key==='Home'?0:event.key==='End'?options().length-1:current+(event.key==='ArrowDown'?1:-1));
      }else if(event.key==='Escape'&&opened){event.preventDefault();closeMenu(true);}
      else if(event.key==='Tab')closeMenu();
      else if(event.key.length===1&&!event.ctrlKey&&!event.metaKey&&!event.altKey){
        event.preventDefault();
        buffer=Date.now()-typedAt>700?event.key:buffer+event.key;typedAt=Date.now();
        if(!opened)open(control);
        const index=options().findIndex(option=>option.textContent.toLowerCase().startsWith(buffer.toLowerCase()));
        if(index>=0)activate(index);
      }
    });
    return control;
  }
  function enhanceMonth(native) {
    const control=controlFor(native,true);
    let year=Number(native.value.slice(0,4)), cursor=Number(native.value.slice(5))-1;
    const setYear=delta=>{year=Math.max(1,Math.min(9999,year+delta));draw();place(control);};
    const valueAt=index=>`${String(year).padStart(4,'0')}-${String(index+1).padStart(2,'0')}`;
    const draw=()=>{
      control.popup.innerHTML=`<div class="ui-month-heading"><button type="button" class="ui-month-nav" aria-label="上一年" ${year===1?'disabled':''}>${icon('left')}</button><span aria-live="polite">${year} 年</span><button type="button" class="ui-month-nav" aria-label="下一年" ${year===9999?'disabled':''}>${icon('right')}</button></div><div class="ui-month-grid">${Array.from({length:12},(_,i)=>`<button type="button" class="ui-month-option" data-month-index="${i}" aria-label="${year} 年 ${i+1} 月" aria-pressed="${valueAt(i)===native.value}" tabindex="${i===cursor?0:-1}">${i+1} 月</button>`).join('')}</div><div class="ui-month-footer"><button type="button" class="ui-month-shortcut">上个月</button><span>选择核算月份</span></div>`;
      const nav=control.popup.querySelectorAll('.ui-month-nav');
      nav[0].addEventListener('click',()=>{setYear(-1);control.popup.querySelectorAll('.ui-month-nav')[0].focus();});
      nav[1].addEventListener('click',()=>{setYear(1);control.popup.querySelectorAll('.ui-month-nav')[1].focus();});
      control.popup.querySelectorAll('.ui-month-option').forEach((button,i)=>{
        button.addEventListener('click',()=>commit(control,valueAt(i)));
        button.addEventListener('keydown',event=>{
          const shifts={ArrowLeft:-1,ArrowRight:1,ArrowUp:-3,ArrowDown:3};
          if(event.key in shifts||event.key==='Home'||event.key==='End'){
            event.preventDefault();
            cursor=event.key==='Home'?0:event.key==='End'?11:Math.max(0,Math.min(11,i+shifts[event.key]));
            control.popup.querySelectorAll('.ui-month-option').forEach((row,index)=>{row.tabIndex=index===cursor?0:-1;});
            control.popup.querySelectorAll('.ui-month-option')[cursor].focus();
          }
        });
      });
      control.popup.querySelector('.ui-month-shortcut').addEventListener('click',()=>{
        const parts=Object.fromEntries(new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit'}).formatToParts(new Date()).map(part=>[part.type,part.value]));
        commit(control,new Date(Date.UTC(Number(parts.year),Number(parts.month)-2,1)).toISOString().slice(0,7));
      });
    };
    control.build=()=>{year=Number(native.value.slice(0,4));cursor=Number(native.value.slice(5))-1;draw();};
    control.trigger.addEventListener('keydown',event=>{
      if(['Enter',' ','ArrowDown'].includes(event.key)){
        event.preventDefault();open(control);control.popup.querySelectorAll('.ui-month-option')[cursor]?.focus();
      }
    });
    control.popup.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();closeMenu(true);}});
    return control;
  }
  function enhance(root=document, artwork=subjectArtwork) {
    subjectArtwork=artwork;
    if(active&&!active.native.isConnected)closeMenu();
    root.querySelectorAll('[data-ui-icon]').forEach(node=>{node.innerHTML=icon(node.dataset.uiIcon);});
    root.querySelectorAll('select[data-ui-select],input[data-ui-month]').forEach(native=>{
      const existing=controllers.get(native);
      if(existing)existing.sync();
      else if(native.matches('[data-ui-month]'))enhanceMonth(native);
      else enhanceSelect(native);
    });
  }
  document.addEventListener('pointerdown',event=>{if(active&&!active.popup.contains(event.target)&&!active.trigger.contains(event.target))closeMenu();});
  document.addEventListener('focusin',event=>{if(active&&!active.popup.contains(event.target)&&!active.trigger.contains(event.target))closeMenu();});
  window.addEventListener('resize',()=>closeMenu());
  document.addEventListener('scroll',event=>{if(active&&!active.popup.contains(event.target))closeMenu();},true);
  window.SkillHubUI={icon,enhance};
})();
