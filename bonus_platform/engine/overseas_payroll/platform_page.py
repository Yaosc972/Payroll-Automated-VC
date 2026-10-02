"""Adapt the preserved handover page to the workbench's existing session login."""

from __future__ import annotations


def _replace_once(html: str, old: str, new: str = "") -> str:
    if html.count(old) != 1:
        raise ValueError("Overseas payroll handover page no longer matches its login adapter")
    return html.replace(old, new, 1)


def _replace_section(html: str, start: str, end: str, replacement: str = "") -> str:
    if html.count(start) != 1 or html.count(end) != 1:
        raise ValueError("Overseas payroll handover page login section has changed")
    start_index = html.index(start)
    end_index = html.index(end, start_index)
    return html[:start_index] + replacement + html[end_index:]


def render_platform_page(html: str) -> str:
    # Do not start the handover's standalone HTTP server or introduce another credential.
    # Exact section boundaries fail closed if a later handover changes the source page.
    html = _replace_section(html, "  /* 共享口令锁屏 */", "  /* main */")
    html = _replace_section(html, '<div class="lock-modal hidden" id="lockModal">', '<div class="layout">')
    html = _replace_once(html, '          <a href="javascript:void(0)" class="chg-pass hidden" id="chgpassbtn" onclick="showChgPass()">修改口令</a>\n')
    html = _replace_section(html, '      <div class="host-warning hidden" id="hostwarn">', '      <div id="home">')
    html = _replace_once(html, "const chgpassbtn = document.getElementById('chgpassbtn');\n")
    html = _replace_section(html, "const hostwarn = document.getElementById('hostwarn');", "let TOOLS = [];")
    html = _replace_section(html, "let PAIE_SID =", "function setText(el, s)", """function authHeader(){ return {credentials:'same-origin'}; }
async function apiMe(){
  try {
    const response = await fetch('/api/me', authHeader());
    if (!response.ok) return null;
    const payload = await response.json();
    return payload.user || null;
  } catch(e){ return null; }
}
async function apiTools(){
  try {
    const response = await fetch('/api/tools', authHeader());
    if (!response.ok) return [];
    const payload = await response.json();
    return payload.tools || [];
  } catch(e){ return []; }
}

""")
    html = _replace_section(html, "function renderBar(user){", "function updateHero(){", """function renderBar(user){
  CURRENT_USER = user;
  setText(usernameEl, user ? (user.name || '已登录用户') : '未登录');
  setText(userroleEl, user ? '已登录' : '请登录后使用工具');
  setText(avatarEl, user ? (user.name || 'U').charAt(0) : '?');
  loginbtn.href = '/login.html?next=%2Foverseas-payroll.html';
  loginbtn.classList.toggle('hidden', Boolean(user));
  logoutbtn.classList.toggle('hidden', !user);
  updateHero();
  renderGrid();
  renderNavModules();
  updateFoot();
}

""")
    html = _replace_once(html, "请先登录（输入共享口令）以解锁模块权限", "请先登录工作台以使用工具")
    html = _replace_section(html, "function updateFoot(){", "/* ===== 处理历史", """function updateFoot(){
  const fm = document.getElementById('footmode');
  const fa = document.getElementById('footaddr');
  if (fm) fm.textContent = CURRENT_USER ? '工作台登录' : '待登录';
  if (fa) fa.textContent = '';
}

""")
    old_guard = "if (!CURRENT_USER){ if (typeof showLock === 'function') showLock(); else location.href='/'; return; }"
    if html.count(old_guard) != 2:
        raise ValueError("Overseas payroll handover tool login guards have changed")
    html = html.replace(old_guard, "if (!CURRENT_USER){ location.href='/login.html?next=%2Foverseas-payroll.html'; return; }")
    html = _replace_section(html, "function checkHost(){", "\nboot();\n</script>", """async function boot(){
  const [user, tools] = await Promise.all([apiMe(), apiTools()]);
  TOOLS = tools;
  renderBar(user);
  if (!user){ location.href='/login.html?next=%2Foverseas-payroll.html'; return; }
  router();
  applyGroupCollapse();
}
""")
    if any(value in html for value in ("/api/unlock", "/api/change-passcode", "PAIE_SID", "paie_sid", "PASSCODE_MODE", "NO_AUTH", "共享口令")):
        raise ValueError("Overseas payroll handover contains an unsupported legacy login reference")
    return html
