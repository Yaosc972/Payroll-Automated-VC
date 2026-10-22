/* Styled single-select controls retain the original select and change handlers. */
(() => {
  'use strict';
  const controls=new Map();let opened=null,sequence=0,queued=false;
  const svg=name=>`<svg class="rd-icon" aria-hidden="true"><use href="#icon-${name}"/></svg>`;
  function close(restore=false){
    if(!opened)return;
    const c=opened;opened=null;
    if(c.panel.matches(':popover-open'))c.panel.hidePopover();
    c.button.setAttribute('aria-expanded','false');c.button.removeAttribute('aria-activedescendant');
    if(restore&&c.button.isConnected)c.button.focus();
  }
  function sync(c){
    const s=c.select,label=s.selectedOptions[0]?.textContent||'请选择';
    if(c.caption.textContent!==label)c.caption.textContent=label;
    c.button.disabled=s.disabled||s.matches(':disabled');
    c.root.hidden=s.hidden;
    c.button.setAttribute('aria-label',`${s.getAttribute('aria-label')||c.label}：${label}`);
    if(opened===c&&(c.button.disabled||!c.button.getClientRects().length))close();
  }
  function highlight(c,index){
    c.index=index;
    c.items.forEach((item,i)=>item.dataset.highlighted=String(i===index));
    const item=c.items[index];
    if(item){c.button.setAttribute('aria-activedescendant',item.id);item.scrollIntoView({block:'nearest'});}else c.button.removeAttribute('aria-activedescendant');
  }
  function choose(c,index){
    const option=c.select.options[index];
    if(!option||option.disabled||option.parentElement.disabled)return;
    c.select.selectedIndex=index;close(true);sync(c);
    c.select.dispatchEvent(new Event('input',{bubbles:true}));
    c.select.dispatchEvent(new Event('change',{bubbles:true}));
    schedule();
  }
  function open(c){
    close();sync(c);if(c.button.disabled)return;
    c.panel.replaceChildren();c.items=[];
    let search,list=c.panel,empty;
    const searchable=c.select.hasAttribute('data-searchable');
    c.panel.setAttribute('role',searchable?'group':'listbox');
    if(searchable){
      search=document.createElement('input');search.type='search';search.className='rc-select-search';search.placeholder='搜索修改项目';search.setAttribute('aria-label','搜索修改项目');
      list=document.createElement('div');list.setAttribute('role','listbox');list.id=c.panel.id+'-list';list.setAttribute('aria-label',c.label);
      empty=document.createElement('p');empty.className='rc-select-empty';empty.textContent='没有匹配的项目';empty.hidden=true;
      c.panel.append(search,list,empty);c.button.setAttribute('aria-controls',list.id);
      search.oninput=()=>{const query=search.value.trim().toLowerCase();c.items.forEach((item,i)=>{item.hidden=c.select.options[i].hidden||c.select.options[i].parentElement.hidden||!item.textContent.toLowerCase().includes(query);});const index=c.items.findIndex(item=>!item.hidden&&item.getAttribute('aria-disabled')!=='true');empty.hidden=index>=0;highlight(c,index);};
      search.onkeydown=event=>{if(['ArrowDown','ArrowUp','Enter','Escape'].includes(event.key))c.button.onkeydown(event);};
    }else c.button.setAttribute('aria-controls',c.panel.id);
    [...c.select.options].forEach((option,index)=>{
      const item=document.createElement('div');item.className='rc-select-option';item.id=`${c.panel.id}-${index}`;
      item.setAttribute('role','option');item.setAttribute('aria-selected',String(option.selected));
      item.setAttribute('aria-disabled',String(option.disabled||!!option.parentElement.disabled));
      item.hidden=option.hidden||option.parentElement.hidden;
      const text=document.createElement('span');text.textContent=option.textContent;item.append(text);
      item.insertAdjacentHTML('beforeend',svg('check'));
      item.onpointerdown=event=>event.preventDefault();
      item.onclick=()=>choose(c,index);
      item.onpointermove=()=>{if(item.getAttribute('aria-disabled')!=='true')highlight(c,index);};
      list.append(item);c.items.push(item);
    });
    const host=c.select.closest('dialog')||document.body;host.append(c.panel);
    opened=c;c.button.setAttribute('aria-expanded','true');c.panel.showPopover();
    const box=c.button.getBoundingClientRect();
    c.panel.style.width=`${Math.min(innerWidth-24,Math.max(box.width,220))}px`;
    const below=innerHeight-box.bottom-12,above=box.top-12,up=below<220&&above>below;
    c.panel.style.maxHeight=`${Math.max(80,Math.min(340,up?above:below))}px`;
    c.panel.style.left=`${Math.max(12,Math.min(box.left,innerWidth-c.panel.offsetWidth-12))}px`;
    c.panel.style.top=`${up?box.top-c.panel.offsetHeight-6:box.bottom+6}px`;
    highlight(c,Math.max(0,c.select.selectedIndex));
    search?.focus();
  }
  function enhance(select){
    if(controls.has(select)||select.multiple||select.size>1)return;
    const root=document.createElement('span');root.className='rc-select';
    const button=document.createElement('button');button.type='button';button.className='rc-select-trigger';
    button.setAttribute('role','combobox');button.setAttribute('aria-haspopup','listbox');button.setAttribute('aria-expanded','false');
    const panel=document.createElement('div');panel.className='rc-select-popover';panel.id=`rc-select-${++sequence}`;panel.setAttribute('popover','manual');panel.setAttribute('role','listbox');
    button.setAttribute('aria-controls',panel.id);
    const caption=document.createElement('span');button.append(caption);button.insertAdjacentHTML('beforeend',svg('chevron'));
    const labels=[...select.labels||[]];
    const label=labels.map(l=>{const copy=l.cloneNode(true);copy.querySelectorAll('select,button,.rc-select').forEach(n=>n.remove());return copy.textContent.trim();}).join(' ')||'选择';
    panel.setAttribute('aria-label',select.getAttribute('aria-label')||label);
    select.after(root);root.append(button);select.classList.add('rc-select-native');
    const c={root,button,caption,panel,select,label,items:[],index:0,typed:'',typedAt:0};controls.set(select,c);
    button.onclick=()=>opened===c?close():open(c);
    button.onkeydown=event=>{
      const key=event.key;
      if(key==='Escape'&&opened===c){event.preventDefault();event.stopPropagation();close(true);return;}
      if(key==='Tab'){close();return;}
      if(['ArrowDown','ArrowUp','Home','End','Enter',' '].includes(key)){
        event.preventDefault();
        if(opened!==c){open(c);return;}
        if(key==='Enter'||key===' '){choose(c,c.index);return;}
        const enabled=c.items.map((item,i)=>({item,i})).filter(({item})=>!item.hidden&&item.getAttribute('aria-disabled')!=='true').map(({i})=>i);
        const at=enabled.indexOf(c.index),next=key==='Home'?0:key==='End'?enabled.length-1:Math.max(0,Math.min(enabled.length-1,at+(key==='ArrowDown'?1:-1)));
        if(enabled.length)highlight(c,enabled[next]);
      }else if(key.length===1&&!event.ctrlKey&&!event.metaKey&&!event.altKey){
        if(opened!==c)open(c);
        c.typed=Date.now()-c.typedAt>700?key:c.typed+key;c.typedAt=Date.now();
        const index=c.items.findIndex(item=>!item.hidden&&item.getAttribute('aria-disabled')!=='true'&&item.textContent.toLowerCase().startsWith(c.typed.toLowerCase()));
        if(index>=0)highlight(c,index);
      }
    };
    c.onChange=()=>sync(c);select.addEventListener('change',c.onChange);
    c.labels=labels;c.onLabelClick=event=>{if(labels.includes(event.target)){event.preventDefault();button.focus();}};
    labels.forEach(l=>l.addEventListener('click',c.onLabelClick));
    sync(c);
  }
  function scan(){
    queued=false;
    controls.forEach((c,s)=>{if(!s.isConnected){if(opened===c)close();c.panel.remove();c.root.remove();s.classList.remove('rc-select-native');s.removeEventListener('change',c.onChange);c.labels.forEach(l=>l.removeEventListener('click',c.onLabelClick));controls.delete(s);}else sync(c);});
    document.querySelectorAll('select:not(.rc-select-native)').forEach(enhance);
  }
  function schedule(){if(!queued){queued=true;queueMicrotask(scan);}}
  new MutationObserver(records=>{
    if(opened&&records.some(r=>r.target.closest?.('select')===opened.select))close();
    if(records.some(r=>r.target.closest?.('select')||(r.type==='attributes'&&r.target.querySelector?.('select'))||[...r.addedNodes,...r.removedNodes].some(n=>n.nodeType===1&&(n.matches('select')||n.querySelector('select')))))schedule();
  }).observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['disabled','hidden','selected','label','value']});
  document.addEventListener('recruitment:render',schedule);
  document.addEventListener('recruitment:busy',schedule);
  document.addEventListener('reset',()=>requestAnimationFrame(scan));
  document.addEventListener('pointerdown',event=>{
    if(opened&&!opened.root.contains(event.target)&&!opened.panel.contains(event.target))close();
    document.querySelectorAll('details.rd-menu[open]').forEach(menu=>{if(!menu.contains(event.target))menu.open=false;});
  });
  document.addEventListener('focusin',event=>{if(opened&&!opened.root.contains(event.target)&&!opened.panel.contains(event.target))close();});
  document.addEventListener('scroll',event=>{if(opened&&!opened.panel.contains(event.target))close();schedule();},true);
  window.addEventListener('resize',()=>close());
  document.addEventListener('keydown',event=>{
    const menu=event.target.closest('details.rd-menu');if(!menu)return;
    const items=[...menu.querySelectorAll('.rd-menu-items button:not(:disabled),.rd-menu-items a')];
    if(event.key==='Escape'&&menu.open){event.preventDefault();event.stopPropagation();menu.open=false;menu.querySelector('summary').focus();}
    if(['ArrowDown','ArrowUp'].includes(event.key)){event.preventDefault();menu.open=true;const i=items.indexOf(document.activeElement);items[(i+(event.key==='ArrowDown'?1:-1)+items.length)%items.length]?.focus();}
  });
  scan();
})();
