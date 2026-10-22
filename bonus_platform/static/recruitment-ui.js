/* Shared workbench controls. Month grid follows domestic-labor's year/12-month picker. */
(() => {
  'use strict';
  function monthPicker(input, {inline = false} = {}) {
    if (!input || input.dataset.monthPicker) return;
    input.dataset.monthPicker = 'true';
    const root = document.createElement('div');
    root.className = inline ? 'ru-month ru-month-inline' : 'ru-month';
    root.innerHTML = `${inline ? '' : `<button type="button" class="ru-month-trigger" id="${input.id}Picker" aria-expanded="false" aria-controls="${input.id}Options"></button>`}<div class="ru-month-panel" id="${input.id}Options" ${inline ? '' : 'hidden'}><div class="ru-month-year"><button type="button" data-year="-1" aria-label="上一年"><svg class="rd-icon" aria-hidden="true"><use href="#icon-left"/></svg></button><strong aria-live="polite"></strong><button type="button" data-year="1" aria-label="下一年"><svg class="rd-icon" aria-hidden="true"><use href="#icon-right"/></svg></button></div><div class="ru-month-grid" role="group" aria-label="选择月份"></div></div>`;
    const trigger = root.querySelector('.ru-month-trigger'), panel = root.querySelector('.ru-month-panel');
    const labels = [...input.labels];
    input.type = 'hidden'; input.after(root);
    if (inline) {
      root.setAttribute('role','group');
      labels.forEach((label,index) => { label.id ||= `${input.id}Label${index}`; label.removeAttribute('for'); });
      if (labels.length) root.setAttribute('aria-labelledby',labels.map(label=>label.id).join(' '));
    } else labels.forEach(label => label.htmlFor = trigger.id);
    let year = Number(input.value.slice(0,4));
    const min = input.min || '2000-01', max = input.max || '2099-12';
    function focus() { (inline ? root.querySelector(`[data-month="${input.value}"]:not(:disabled)`) : trigger)?.focus(); }
    function close(restoreFocus = false) { if (!inline) { panel.hidden = true; trigger.setAttribute('aria-expanded','false'); } if (restoreFocus) focus(); }
    function render() {
      if (trigger) {
        trigger.innerHTML = `${input.value.slice(0,4)}年${Number(input.value.slice(5))}月<svg class="rd-icon" aria-hidden="true"><use href="#icon-chevron"/></svg>`;
        trigger.disabled = input.disabled;
      }
      root.querySelector('strong').textContent = `${year}年`;
      root.querySelector('[data-year="-1"]').disabled = input.disabled || year <= Number(min.slice(0,4));
      root.querySelector('[data-year="1"]').disabled = input.disabled || year >= Number(max.slice(0,4));
      root.querySelector('.ru-month-grid').innerHTML = Array.from({length:12},(_,i) => {
        const value = `${year}-${String(i+1).padStart(2,'0')}`;
        return `<button type="button" data-month="${value}" aria-pressed="${value===input.value}" ${input.disabled||value<min||value>max?'disabled':''}>${i+1}月</button>`;
      }).join('');
    }
    if (trigger) trigger.onclick = () => { if (!panel.hidden) return close(); year=Number(input.value.slice(0,4)); render(); panel.hidden=false; trigger.setAttribute('aria-expanded','true'); };
    root.addEventListener('click', event => {
      const button = event.target.closest('button');
      if (!button || button.disabled || input.disabled) return;
      if (button.dataset.year) { year += Number(button.dataset.year); render(); }
      if (button.dataset.month) { input.value=button.dataset.month; render(); input.dispatchEvent(new Event('change',{bubbles:true})); close(true); }
    });
    root.addEventListener('keydown', event => {
      if (!inline && event.key==='Escape' && !panel.hidden) { event.preventDefault(); event.stopPropagation(); close(true); }
      const columns=inline?6:3,offsets={ArrowRight:1,ArrowLeft:-1,ArrowDown:columns,ArrowUp:-columns};
      if (event.key in offsets) {
        event.preventDefault(); panel.hidden=false; trigger?.setAttribute('aria-expanded','true');
        const buttons=[...root.querySelectorAll('[data-month]:not(:disabled)')];
        const current=buttons.indexOf(document.activeElement);
        const index=current<0?buttons.findIndex(b=>b.dataset.month===input.value):(current+offsets[event.key]+buttons.length)%buttons.length;
        buttons[Math.max(0,index)]?.focus();
      }
    });
    root.addEventListener('focusout', event => { if (!inline && !root.contains(event.relatedTarget)) close(); });
    input.addEventListener('change',render);
    new MutationObserver(() => { render(); if (input.disabled) close(); }).observe(input,{attributes:true,attributeFilter:['disabled']});
    render();
    return {close,focus};
  }
  document.addEventListener('click', event => document.querySelectorAll('.ru-month:not(.ru-month-inline)').forEach(root => {
    if (!root.contains(event.target)) { root.querySelector('.ru-month-panel').hidden=true; root.querySelector('.ru-month-trigger').setAttribute('aria-expanded','false'); }
  }));
  // Restore the user's list filters after entering an activity or a legacy record.
  try {
    const query = new URLSearchParams(sessionStorage.getItem('recruitment-activity-list') || '');
    const safe = new URLSearchParams();
    ['scope','q','month','state','page'].forEach(key => { if(query.has(key)) safe.set(key,query.get(key)); });
    if (safe.size) document.querySelectorAll('.ra-back').forEach(link => link.href='recruitment-activities.html?'+safe);
  } catch {}
  window.RecruitmentUI = {monthPicker};
})();
