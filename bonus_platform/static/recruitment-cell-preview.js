/* Preview clipped display values; never read the underlying personnel record. */
(() => {
  'use strict';
  const host=document.getElementById('draftContent');if(!host)return;
  const selector='.flow-ledger td,.flow-recipient-table td,th[data-column-key]';
  const savedTitles=new WeakMap();
  const preview=document.createElement('div');preview.id='flowCellPreview';preview.className='flow-cell-preview';
  preview.setAttribute('role','tooltip');preview.setAttribute('popover','manual');
  const caption=document.createElement('div');caption.className='flow-cell-preview-caption';
  const value=document.createElement('div');value.className='flow-cell-preview-value';
  preview.append(caption,value);document.body.append(preview);
  let target=null,timer=0,hideTimer=0,blockedUntil=0;
  function close(){
    clearTimeout(timer);clearTimeout(hideTimer);timer=hideTimer=0;
    if(target){
      const ids=(target.getAttribute('aria-describedby')||'').split(/\s+/).filter(id=>id&&id!==preview.id);
      if(ids.length)target.setAttribute('aria-describedby',ids.join(' '));else target.removeAttribute('aria-describedby');
    }
    target=null;if(preview.matches(':popover-open'))preview.hidePopover();
  }
  function leave(){clearTimeout(timer);clearTimeout(hideTimer);hideTimer=setTimeout(close,180);}
  function remember(cell){
    if(cell.hasAttribute('title')){savedTitles.set(cell,cell.getAttribute('title'));cell.removeAttribute('title');}
  }
  function clipped(cell){
    const content=cell.querySelector('.rd-row-open,.flow-column-label')||cell;
    if(content.scrollWidth>content.clientWidth||content.scrollHeight>content.clientHeight)return true;
    // Table metrics round to whole pixels; text can still be ellipsized by a fraction.
    const style=getComputedStyle(content),range=document.createRange();range.selectNodeContents(content);
    const rect=range.getBoundingClientRect();
    return style.whiteSpace==='nowrap'&&rect.width>content.clientWidth-parseFloat(style.paddingLeft)-parseFloat(style.paddingRight)+.1;
  }
  function heading(cell){
    if(cell.matches('th'))return cell;
    const headers=[...cell.closest('table').querySelectorAll('th[data-column-key]')];
    const offset=cell.closest('.flow-ledger')?1:0;
    return headers[cell.cellIndex-offset];
  }
  function show(cell){
    if(target!==cell||!cell.isConnected||!clipped(cell))return close();
    if(performance.now()<blockedUntil){timer=setTimeout(()=>show(cell),blockedUntil-performance.now()+80);return;}
    const header=heading(cell),label=header?.querySelector('.flow-column-label')?.textContent||header?.textContent||'';
    let full=savedTitles.get(cell)||cell.textContent.trim();
    if(window.RecruitmentDetailTable.isIdentity(header?.dataset.columnKey||label))full=window.RecruitmentDetailTable.maskIdentity(full);
    caption.textContent=label.trim();caption.hidden=!caption.textContent||cell.matches('th');
    value.textContent=full;
    preview.showPopover();
    const r=cell.getBoundingClientRect(),p=preview.getBoundingClientRect();
    const below=r.bottom+7,above=r.top-p.height-7;
    preview.style.left=Math.max(12,Math.min(r.left,innerWidth-p.width-12))+'px';
    preview.style.top=Math.max(12,Math.min(below+p.height<=innerHeight-12?below:above,innerHeight-p.height-12))+'px';
    const ids=new Set((cell.getAttribute('aria-describedby')||'').split(/\s+/).filter(Boolean));ids.add(preview.id);
    cell.setAttribute('aria-describedby',[...ids].join(' '));
  }
  function enter(event){
    if(document.body.classList.contains('flow-resizing-columns'))return close();
    if(event.type==='pointermove'&&preview.matches(':popover-open')){
      const r=preview.getBoundingClientRect();
      if(event.clientX>=r.left&&event.clientX<=r.right&&event.clientY>=r.top-8&&event.clientY<=r.bottom+8){clearTimeout(hideTimer);return;}
    }
    const cell=event.target.closest(selector);
    if(!cell||!host.contains(cell)||event.target.closest('.flow-column-handle,input,select,textarea'))return close();
    remember(cell);
    if(cell===target){clearTimeout(hideTimer);return;}
    close();if(!clipped(cell))return;
    target=cell;timer=setTimeout(()=>show(cell),Math.max(event.type==='focusin'?0:240,blockedUntil-performance.now()+80));
  }
  function setup(){close();host.querySelectorAll(selector).forEach(remember);}
  function scrolling(event){if(preview.contains(event.target))return;blockedUntil=performance.now()+300;close();}
  host.addEventListener('pointermove',enter);
  host.addEventListener('pointerleave',leave);
  preview.addEventListener('pointerenter',()=>clearTimeout(hideTimer));
  preview.addEventListener('pointerleave',leave);
  host.addEventListener('focusin',enter);
  host.addEventListener('focusout',close);
  host.addEventListener('recruitment:columns-resized',close);
  document.addEventListener('pointerdown',event=>{if(!preview.contains(event.target))close();});
  document.addEventListener('scroll',scrolling,true);
  document.addEventListener('wheel',scrolling,{passive:true,capture:true});
  document.addEventListener('keydown',event=>{if(event.key==='Escape')close();});
  document.addEventListener('recruitment:render',setup);
  window.addEventListener('resize',close);
  new MutationObserver(setup).observe(host,{childList:true});
  setup();
})();
