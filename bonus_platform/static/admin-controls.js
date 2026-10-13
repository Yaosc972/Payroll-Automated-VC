/* Styled controls retain the existing form values and change handlers. */
(() => {
  const controls = new Map();
  let serial = 0;
  const sync = (select, control) => {
    const text = select.selectedOptions[0]?.textContent || '请选择';
    const caption = control.trigger.querySelector('span');
    if (caption.textContent !== text) caption.textContent = text;
    control.trigger.disabled = select.disabled;
    control.menu.querySelectorAll('[role="option"]').forEach(option => {
      option.setAttribute('aria-selected', String(option.dataset.value === select.value));
    });
  };
  const position = control => {
    if (!control.menu.matches(':popover-open')) return;
    const r = control.trigger.getBoundingClientRect();
    const menu = control.menu;
    menu.style.width = `${Math.min(Math.max(r.width, 136), innerWidth - 24)}px`;
    const height = menu.getBoundingClientRect().height;
    menu.style.left = `${Math.max(12, Math.min(r.left, innerWidth - menu.offsetWidth - 12))}px`;
    menu.style.top = `${r.bottom + height + 6 <= innerHeight - 12 ? r.bottom + 6 : Math.max(12, r.top - height - 6)}px`;
  };
  const enhance = select => {
    if (controls.has(select)) return;
    const trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.className = 'admin-select-trigger';
    trigger.innerHTML = '<span></span><i aria-hidden="true"></i>';
    trigger.setAttribute('aria-haspopup', 'listbox');
    trigger.setAttribute('aria-expanded', 'false');
    const label = select.labels?.[0];
    const name = select.getAttribute('aria-label') || label?.querySelector('span')?.textContent || label?.firstChild?.textContent?.trim() || '选择';
    trigger.setAttribute('aria-label', name);
    const menu = document.createElement('div');
    menu.id = `adminSelectMenu${++serial}`;
    menu.className = 'admin-select-menu';
    menu.setAttribute('popover', 'auto');
    menu.setAttribute('role', 'listbox');
    menu.setAttribute('aria-label', name);
    trigger.setAttribute('aria-controls', menu.id);
    const control = {trigger, menu};
    controls.set(select, control);
    select.classList.add('admin-select-source');
    select.tabIndex = -1;
    select.setAttribute('aria-hidden', 'true');
    select.after(trigger);
    document.body.append(menu);
    const choose = option => {
      select.value = option.dataset.value;
      menu.hidePopover();
      trigger.focus({preventScroll: true});
      select.dispatchEvent(new Event('change', {bubbles: true}));
      if (select.isConnected) sync(select, control);
    };
    const open = direction => {
      menu.replaceChildren(...Array.from(select.options, option => {
        const button = document.createElement('button');
        button.type = 'button';
        button.setAttribute('role', 'option');
        button.dataset.value = option.value;
        button.textContent = option.textContent;
        button.disabled = option.disabled;
        button.addEventListener('click', () => choose(button));
        return button;
      }));
      sync(select, control);
      menu.showPopover();
      position(control);
      const options = [...menu.querySelectorAll('button:not(:disabled)')];
      (options.find(option => option.dataset.value === select.value) || options[direction === 'up' ? options.length - 1 : 0])?.focus({preventScroll: true});
    };
    trigger.addEventListener('click', event => {
      event.preventDefault();
      if (menu.matches(':popover-open')) menu.hidePopover(); else open();
    });
    trigger.addEventListener('keydown', event => {
      if (['ArrowDown', 'ArrowUp'].includes(event.key)) { event.preventDefault(); open(event.key === 'ArrowUp' ? 'up' : 'down'); }
    });
    menu.addEventListener('keydown', event => {
      const options = [...menu.querySelectorAll('button:not(:disabled)')];
      const index = options.indexOf(document.activeElement);
      if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
        event.preventDefault();
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? options.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length;
        options[next]?.focus();
      } else if (event.key === 'Escape') { event.preventDefault(); menu.hidePopover(); trigger.focus({preventScroll: true}); }
      else if (event.key === 'Tab') menu.hidePopover();
    });
    menu.addEventListener('toggle', () => trigger.setAttribute('aria-expanded', String(menu.matches(':popover-open'))));
    select.addEventListener('change', () => sync(select, control));
    sync(select, control);
  };
  const refresh = () => {
    for (const [select, control] of controls) {
      if (!select.isConnected) { control.menu.remove(); controls.delete(select); }
      else sync(select, control);
    }
    document.querySelectorAll('.admin-console-shell select').forEach(enhance);
  };
  refresh();
  new MutationObserver(refresh).observe(document.querySelector('.admin-console-shell'), {childList: true, subtree: true});
  window.addEventListener('resize', () => controls.forEach(position));
  window.addEventListener('scroll', () => controls.forEach(position), true);
})();
