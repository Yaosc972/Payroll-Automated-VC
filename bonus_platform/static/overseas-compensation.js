(async () => {
  const entries = [...document.querySelectorAll('[data-child-module]')];
  const lockEntry = (entry, reason) => {
    entry.classList.add('permission-locked');
    entry.setAttribute('aria-disabled', 'true');
    entry.dataset.originalHref = entry.getAttribute('href') || '#';
    entry.setAttribute('href', '#');
    entry.setAttribute('title', reason);
    const action = entry.querySelector('.module-action span');
    if (action) action.textContent = '无权限进入';
    const status = entry.querySelector('.module-status');
    if (status) status.textContent = 'Locked · 无权限';
  };

  try {
    const response = await fetch('/api/me', { credentials: 'same-origin', cache: 'no-store' });
    if (response.status === 401) {
      window.location.replace(`/login.html?next=${encodeURIComponent(window.location.pathname)}`);
      return;
    }
    if (!response.ok) throw new Error(`权限接口返回 ${response.status}`);
    const context = await response.json();
    const modules = new Map((context.modules || []).map((module) => [module.id, module]));
    const roleIds = context.user?.roleIds || [];
    const isAdmin = roleIds.includes('admin');
    const moduleAccess = context.permissions?.moduleAccess || {};
    const rolePermissions = context.permissions?.rolePermissions || {};
    const canEnter = (moduleId) => {
      const module = modules.get(moduleId);
      if (!module?.enabled) return false;
      if (isAdmin || module.canEnter === true) return true;
      return roleIds.some((roleId) => moduleAccess[roleId]?.[moduleId] && rolePermissions[roleId]?.enter);
    };
    entries.forEach((entry) => {
      if (!canEnter(entry.dataset.childModule)) lockEntry(entry, '当前用户没有该子模块权限');
    });
  } catch (error) {
    entries.forEach((entry) => lockEntry(entry, '暂时无法确认模块权限，请刷新后重试'));
  }

  document.addEventListener('click', (event) => {
    const entry = event.target.closest('[data-child-module][aria-disabled="true"]');
    if (entry) event.preventDefault();
  });
})();
