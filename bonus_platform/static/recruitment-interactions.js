/* Shared, short transitions for workbench content and dialogs. */
(() => {
  'use strict';
  const reduced=matchMedia('(prefers-reduced-motion: reduce)'),animations=new Set(),pendingButtons=new WeakSet();
  function enter(element){
    if(!element||reduced.matches||!window.Motion?.animate)return;
    const animation=window.Motion.animate(element,{opacity:[.6,1],y:[6,0]},{duration:.18,ease:'easeOut'});
    animations.add(animation);
    Promise.resolve(animation).finally(()=>animations.delete(animation));
  }
  function pending(button,message,scope){
    if(!button||pendingButtons.has(button))return null;
    pendingButtons.add(button);
    const html=button.innerHTML,width=button.style.minWidth,aria=button.getAttribute('aria-busy'),scopeAria=scope?.getAttribute('aria-busy');
    const controls=[...new Set([button,...(scope?.querySelectorAll('input,select,textarea,button')||[])])].map(control=>[control,control.disabled]);
    const measured=button.getBoundingClientRect().width;
    if(measured)button.style.minWidth=measured+'px';
    controls.forEach(([control])=>control.disabled=true);
    button.classList.add('rd-action-pending');button.setAttribute('aria-busy','true');scope?.setAttribute('aria-busy','true');
    button.innerHTML='<svg class="rd-action-spinner" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M12 2a10 10 0 1 0 10 10"/></svg><span></span>';
    button.lastElementChild.textContent=message;
    const animation=!reduced.matches&&window.Motion?.animate?window.Motion.animate(button.firstElementChild,{rotate:[0,360]},{duration:.8,repeat:Infinity,ease:'linear'}):null;
    if(animation)animations.add(animation);
    let finished=false;
    return ()=>{
      if(finished)return;finished=true;
      pendingButtons.delete(button);animation?.stop();animations.delete(animation);
      button.innerHTML=html;button.style.minWidth=width;button.classList.remove('rd-action-pending');
      if(aria===null)button.removeAttribute('aria-busy');else button.setAttribute('aria-busy',aria);
      if(scope){if(scopeAria===null)scope.removeAttribute('aria-busy');else scope.setAttribute('aria-busy',scopeAria);}
      controls.forEach(([control,disabled])=>control.disabled=disabled);
    };
  }
  function focusControl(control){
    const target=control?.matches('select.rc-select-native')?control.nextElementSibling?.querySelector('.rc-select-trigger'):control?.matches('input.rc-date-native')?control.nextElementSibling?.querySelector('.rc-date-input'):control;
    target?.scrollIntoView({block:'nearest'});target?.focus({preventScroll:true});
  }
  function dialog(){
    const title=document.getElementById('draftInspectorTitle'),body=document.getElementById('draftInspectorBody');
    title.tabIndex=-1;
    // Replacing a dialog's focused form must not leave focus on the page behind it.
    queueMicrotask(()=>{if(document.getElementById('draftInspector').open&&(!document.activeElement?.closest('dialog')||document.activeElement===document.getElementById('draftInspector')))title.focus({preventScroll:true});});
    enter(body);
  }
  reduced.addEventListener('change',()=>{if(reduced.matches){animations.forEach(animation=>animation.complete());animations.clear();}});
  window.RecruitmentInteractions={enter,focusControl,dialog,pending};
})();
