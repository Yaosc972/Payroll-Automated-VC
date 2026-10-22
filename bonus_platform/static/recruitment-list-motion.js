/* Designeer shared spring highlight, adapted for stationary financial cells. */
(() => {
  'use strict';
  const host=document.getElementById('draftContent');
  const tabs=document.querySelector('.flow-result-tabs');
  if(!host||!tabs)return;
  const reduced=matchMedia('(prefers-reduced-motion: reduce)');
  const plate=document.createElement('div');plate.className='flow-row-plate';plate.setAttribute('aria-hidden','true');
  const tabPlate=document.createElement('span');tabPlate.className='flow-tab-plate';tabPlate.setAttribute('aria-hidden','true');tabs.prepend(tabPlate);
  const spring=(value=0)=>({value,target:value,velocity:0});
  const row={x:spring(),y:spring(),width:spring(),height:spring(),opacity:spring()};
  const tab={x:spring(),y:spring(),width:spring(),height:spring(),opacity:spring(1)};
  let target=null,active=null,table=null,lenis=null,raf=0,last=0,queued=false;
  function step(s,dt,k=140,d=18){s.velocity+=((s.target-s.value)*k-s.velocity*d)*dt;s.value+=s.velocity*dt;if(Math.abs(s.value-s.target)<.03&&Math.abs(s.velocity)<.03){s.value=s.target;s.velocity=0;}}
  function jump(s,v){s.value=s.target=v;s.velocity=0;}
  function updateRect(values,rect,instant=false){Object.entries(rect).forEach(([key,value])=>{if(instant||reduced.matches)jump(values[key],value);else values[key].target=value;});}
  function measureRow(){
    const selected=target||active;
    if(!selected?.isConnected||!table){row.opacity.target=0;return;}
    const box=host.getBoundingClientRect(),r=selected.getBoundingClientRect();
    const head=table.querySelector('thead')?.getBoundingClientRect();
    const top=Math.max(r.top,head?.bottom||box.top),bottom=Math.min(r.bottom,box.bottom);
    if(bottom<=top){row.opacity.target=0;return;}
    updateRect(row,{x:host.scrollLeft+5,y:top-box.top+host.scrollTop+1,width:host.clientWidth-10,height:Math.max(1,bottom-top-2),opacity:1},row.opacity.value<.05);
  }
  function measureTab(){
    const button=tabs.querySelector('button[aria-pressed="true"]');
    if(!button||tabs.hidden)return;
    const r=button.getBoundingClientRect(),b=tabs.getBoundingClientRect();
    updateRect(tab,{x:r.left-b.left,y:r.top-b.top+3,width:r.width,height:r.height-6,opacity:1},!tab.width.value);
  }
  function draw(el,values){
    el.style.transform=`translate3d(${values.x.value}px,${values.y.value}px,0)`;
    el.style.width=`${values.width.value}px`;el.style.height=`${values.height.value}px`;el.style.opacity=values.opacity.value;
  }
  function moving(){return [row,tab].some(values=>Object.values(values).some(s=>Math.abs(s.value-s.target)>.03||Math.abs(s.velocity)>.03));}
  function frame(time){
    raf=0;const dt=Math.min((time-(last||time))/1000,.032);last=time;
    if(lenis)lenis.raf(time);
    for(let i=0;i<3;i++)for(const values of [row,tab])for(const [key,s] of Object.entries(values)){
      if(reduced.matches)jump(s,s.target);else step(s,dt/3,key==='opacity'?700:140,key==='opacity'?46:18);
    }
    draw(plate,row);draw(tabPlate,tab);
    if(moving()||lenis?.isScrolling==='smooth')wake();else last=0;
  }
  function wake(){if(!raf){if(!last&&lenis)lenis.time=0;raf=requestAnimationFrame(frame);}}
  function setup(){
    queued=false;
    const next=host.querySelector('.flow-ledger,.flow-recipient-table');
    const changed=next!==table;
    if(changed){
      target=active=null;table=next;
      // Old highlight geometry must not extend the new table's scroll bounds.
      for(const value of Object.values(row))jump(value,0);
      draw(plate,row);
    }
    host.classList.toggle('flow-motion-host',!!next);
    if(next&&!plate.isConnected)host.append(plate);
    if(!next)plate.remove();
    if(changed||reduced.matches){lenis?.destroy();lenis=null;}
    if(next&&!reduced.matches&&!lenis&&typeof window.Lenis==='function'){
      lenis=new window.Lenis({wrapper:host,content:host,eventsTarget:host,duration:.65,smoothWheel:true,
        virtualScroll:({event,deltaX,deltaY})=>{
          if(event.shiftKey||event.ctrlKey||Math.abs(deltaY)<=Math.abs(deltaX)||event.target.closest('input,select,textarea,[contenteditable="true"]'))return false;
          // Release outward wheel input to native page scrolling at either edge.
          const limit=lenis?.limit??Math.max(0,host.scrollHeight-host.clientHeight);
          return deltaY<0?host.scrollTop>1:host.scrollTop<limit-1;
        }});
      host.dataset.smoothScroll='true';
    }else if(!lenis)delete host.dataset.smoothScroll;
    lenis?.resize();measureTab();wake();
  }
  function schedule(){if(!queued){queued=true;queueMicrotask(setup);}}
  host.addEventListener('pointermove',event=>{
    if(event.pointerType==='touch')return;
    const selected=event.target.closest('tbody tr');
    if(!selected||!table?.contains(selected)){if(target){target=null;measureRow();wake();}return;}
    if(target!==selected){target=selected;measureRow();wake();}
  });
  host.addEventListener('pointerleave',()=>{target=null;measureRow();wake();});
  host.addEventListener('focusin',event=>{const selected=event.target.closest('tbody tr');if(table?.contains(selected)){active=selected;measureRow();wake();}});
  host.addEventListener('focusout',event=>{if(!host.contains(event.relatedTarget)){active=null;measureRow();wake();}});
  host.addEventListener('scroll',()=>{measureRow();wake();},{passive:true});
  host.addEventListener('wheel',wake,{passive:true});
  host.addEventListener('recruitment:columns-resized',()=>{lenis?.resize();measureRow();measureTab();wake();});
  new MutationObserver(schedule).observe(host,{childList:true});
  new MutationObserver(()=>{measureTab();wake();}).observe(tabs,{subtree:true,attributes:true,attributeFilter:['aria-pressed','hidden']});
  new ResizeObserver(()=>{lenis?.resize();measureRow();measureTab();wake();}).observe(host);
  document.addEventListener('recruitment:render',schedule);
  reduced.addEventListener('change',()=>{lenis?.destroy();lenis=null;setup();});
  window.addEventListener('resize',()=>{measureRow();measureTab();wake();});
  window.addEventListener('pagehide',()=>{lenis?.destroy();cancelAnimationFrame(raf);});
  setup();
})();
