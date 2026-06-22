(async () => {
  const moduleId = document.documentElement.dataset.moduleId;
  const adminOnly = document.documentElement.dataset.adminOnly === "true";
  if (!moduleId && !adminOnly) return;
  const authCacheKey = "sigma-auth-context-v2";
  const authCacheTtlMs = 5 * 60 * 1000;
  const authFetchTimeoutMs = 10 * 1000;
  const isLocalPreview = window.location.protocol === "file:" || ["localhost", "127.0.0.1", ""].includes(window.location.hostname);
  let loadingFinished = false;
  document.documentElement.classList.add("permission-checking");

  const injectLoadingStyles = () => {
    if (document.getElementById("permissionLoadingStyles")) return;
    const style = document.createElement("style");
    style.id = "permissionLoadingStyles";
    style.textContent = `
      .permission-loading-overlay {
        position: fixed;
        inset: 0;
        z-index: 2147483647;
        display: grid;
        place-items: center;
        background:
          radial-gradient(circle at 18% 14%, rgba(34, 211, 238, 0.2), transparent 34%),
          radial-gradient(circle at 82% 10%, rgba(139, 92, 246, 0.18), transparent 36%),
          #eef3f7;
        color: #0f172a;
        font-family: "PingFang SC", "Microsoft YaHei", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }
      .permission-loader-card {
        display: grid;
        width: min(420px, calc(100vw - 44px));
        justify-items: center;
        gap: 16px;
        border: 1px solid rgba(255, 255, 255, 0.78);
        border-radius: 28px;
        padding: 28px;
        background: rgba(255, 255, 255, 0.72);
        box-shadow: 0 28px 76px rgba(15, 23, 42, 0.12), inset 0 1px 0 rgba(255, 255, 255, 0.86);
        backdrop-filter: blur(28px);
        -webkit-backdrop-filter: blur(28px);
      }
      .sigma-loader-core {
        position: relative;
        width: 76px;
        height: 76px;
      }
      .sigma-loader-ring,
      .sigma-loader-dot {
        position: absolute;
        inset: 0;
        border-radius: 999px;
      }
      .sigma-loader-ring {
        border: 5px solid rgba(37, 99, 235, 0.12);
        border-top-color: #2563eb;
        animation: sigmaLoaderSpin 0.9s linear infinite;
      }
      .sigma-loader-dot {
        inset: 24px;
        background: linear-gradient(135deg, #0f172a, #2563eb);
        box-shadow: 0 12px 28px rgba(37, 99, 235, 0.25);
      }
      .permission-loader-card strong {
        font-size: 18px;
        font-weight: 900;
      }
      .permission-loader-card span {
        color: #64748b;
        font-size: 13px;
        font-weight: 700;
      }
      @keyframes sigmaLoaderSpin { to { transform: rotate(360deg); } }
    `;
    document.head.appendChild(style);
  };

  const animateLoading = () => {
    const run = () => {
      if (!window.gsap) return;
      window.gsap.to(".sigma-loader-dot", {
        scale: 0.76,
        opacity: 0.72,
        duration: 0.58,
        repeat: -1,
        yoyo: true,
        ease: "sine.inOut",
      });
      window.gsap.to(".permission-loader-card", {
        y: -4,
        duration: 0.9,
        repeat: -1,
        yoyo: true,
        ease: "sine.inOut",
      });
    };
    run();
  };

  const mountLoadingOverlay = () => {
    if (loadingFinished) return;
    if (!document.body || document.querySelector(".permission-loading-overlay")) return;
    const overlay = document.createElement("div");
    overlay.className = "permission-loading-overlay";
    overlay.setAttribute("role", "status");
    overlay.setAttribute("aria-live", "polite");
    overlay.innerHTML = `
      <div class="permission-loader-card">
        <div class="sigma-loader-core" aria-hidden="true">
          <span class="sigma-loader-ring"></span>
          <span class="sigma-loader-dot"></span>
        </div>
        <strong>正在校验访问权限</strong>
        <span>读取账号角色与模块开放状态...</span>
      </div>
    `;
    document.body.appendChild(overlay);
    animateLoading();
  };

  const finishLoading = () => {
    loadingFinished = true;
    window.clearInterval(ensureLoadingOverlay);
    document.documentElement.classList.remove("permission-checking");
    document.querySelector(".permission-loading-overlay")?.remove();
  };

  injectLoadingStyles();
  const ensureLoadingOverlay = window.setInterval(() => {
    if (loadingFinished || document.querySelector(".permission-loading-overlay")) {
      window.clearInterval(ensureLoadingOverlay);
      return;
    }
    mountLoadingOverlay();
  }, 120);
  if (document.body) {
    mountLoadingOverlay();
  } else {
    document.addEventListener("DOMContentLoaded", mountLoadingOverlay, { once: true });
  }

  const storageKey = "sigma-admin-console-draft-v3";
  const defaults = {
    selectedUserId: "payrollAdmin",
    users: [
      { id: "payrollAdmin", name: "Payroll Admin", roleIds: ["admin"] },
      { id: "recruitmentAdminUser", name: "Recruitment Admin", roleIds: ["recruitmentAdmin"] },
      { id: "cnPayrollAdminUser", name: "CN Payroll Admin", roleIds: ["employeeAdmin", "domesticAdmin"] },
      { id: "fbuAdminUser", name: "FBU Bonus Admin", roleIds: ["fbuAdmin"] },
      { id: "overseasAdminUser", name: "Overseas Audit Admin", roleIds: ["overseasAdmin"] },
    ],
    modules: [
      { id: "recruitment", name: "全球招聘奖金核算", enabled: true },
      { id: "employee", name: "中国区正式工薪酬核算", enabled: false },
      { id: "domestic", name: "中国区外包工薪酬核算", enabled: true },
      { id: "fbu", name: "FBU美洲绩效奖金核算", enabled: true },
      { id: "overseas", name: "海外劳务报账核对", enabled: true },
    ],
    rolePermissions: {
      admin: { enter: true },
      recruitmentAdmin: { enter: true },
      employeeAdmin: { enter: true },
      domesticAdmin: { enter: true },
      fbuAdmin: { enter: true },
      overseasAdmin: { enter: true },
    },
    moduleAccess: {
      admin: { recruitment: true, employee: true, domestic: true, fbu: true, overseas: true },
      recruitmentAdmin: { recruitment: true },
      employeeAdmin: { employee: true },
      domesticAdmin: { domestic: true },
      fbuAdmin: { fbu: true },
      overseasAdmin: { overseas: true },
    },
  };

  const readPermissionState = () => {
    try {
      const stored = JSON.parse(localStorage.getItem(storageKey) || "{}");
      return {
        ...defaults,
        ...stored,
        rolePermissions: { ...defaults.rolePermissions, ...(stored.rolePermissions || {}) },
        moduleAccess: { ...defaults.moduleAccess, ...(stored.moduleAccess || {}) },
      };
    } catch {
      return defaults;
    }
  };

  let state = readPermissionState();
  const mergeAuthContext = (me) => ({
    ...state,
    users: [{ ...me.user, roleIds: me.user.roleIds || [] }],
    modules: me.modules || state.modules,
    rolePermissions: me.permissions?.rolePermissions || state.rolePermissions,
    moduleAccess: me.permissions?.moduleAccess || state.moduleAccess,
    selectedUserId: me.user?.id || state.selectedUserId,
  });
  const readCachedAuthContext = () => {
    try {
      const cached = JSON.parse(sessionStorage.getItem(authCacheKey) || "{}");
      if (!cached.createdAt || Date.now() - cached.createdAt > authCacheTtlMs || !cached.me) return null;
      return cached.me;
    } catch {
      return null;
    }
  };
  const writeCachedAuthContext = (me) => {
    try {
      sessionStorage.setItem(authCacheKey, JSON.stringify({ createdAt: Date.now(), me }));
    } catch {
      // Ignore storage limits; the network request path remains authoritative.
    }
  };
  const fetchAuthContext = async () => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), authFetchTimeoutMs);
    try {
      return await fetch("/api/me", {
        credentials: "same-origin",
        cache: "no-store",
        signal: controller.signal,
      });
    } finally {
      window.clearTimeout(timeout);
    }
  };
  const escapeHtml = (value) => String(value).replace(/[&<>"']/g, char => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[char]);
  const renderGuardError = (title, detail) => {
    const safeTitle = escapeHtml(title);
    const safeDetail = escapeHtml(detail);
    document.open();
    document.write(`<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>${safeTitle} · 西格玛工作台</title>
    <link rel="icon" type="image/png" href="assets/bonus-logo-dark.png" />
    <style>
      * { box-sizing: border-box; }
      body {
        min-height: 100vh;
        margin: 0;
        display: grid;
        place-items: center;
        background: #eef3f7;
        color: #0f172a;
        font-family: "PingFang SC", "Microsoft YaHei", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }
      main {
        width: min(560px, calc(100vw - 32px));
        border: 1px solid rgba(255, 255, 255, 0.78);
        border-radius: 28px;
        padding: 28px;
        background: rgba(255, 255, 255, 0.72);
        box-shadow: 0 28px 76px rgba(15, 23, 42, 0.12), inset 0 1px 0 rgba(255, 255, 255, 0.86);
      }
      p {
        margin: 0 0 8px;
        color: #2563eb;
        font-size: 12px;
        font-weight: 800;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }
      h1 {
        margin: 0;
        font-size: 30px;
        line-height: 1.12;
      }
      span {
        display: block;
        margin-top: 12px;
        color: #475569;
        font-size: 14px;
        line-height: 1.7;
      }
      nav {
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        margin-top: 22px;
      }
      a {
        border-radius: 999px;
        padding: 11px 15px;
        color: #fff;
        background: linear-gradient(135deg, #0f172a, #1e3a8a);
        text-decoration: none;
        font-size: 13px;
        font-weight: 800;
      }
      a.secondary {
        color: #0f172a;
        background: rgba(255, 255, 255, 0.78);
        box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.28);
      }
    </style>
  </head>
  <body>
    <main>
      <p>ACCESS GUARD</p>
      <h1>${safeTitle}</h1>
      <span>${safeDetail}</span>
      <nav>
        <a href="index.html">返回工作台首页</a>
        <a class="secondary" href="login.html?force=1&next=${encodeURIComponent(window.location.pathname || "/")}">重新登录</a>
      </nav>
    </main>
  </body>
</html>`);
    document.close();
    window.stop();
  };
  try {
    const cachedMe = readCachedAuthContext();
    if (cachedMe) {
      state = mergeAuthContext(cachedMe);
    } else {
      const response = await fetchAuthContext();
      if (response.status === 401) {
        sessionStorage.removeItem(authCacheKey);
        window.location.href = `login.html?next=${encodeURIComponent(window.location.pathname || "/")}`;
        return;
      }
      if (response.ok) {
        const me = await response.json();
        writeCachedAuthContext(me);
        state = mergeAuthContext(me);
      }
    }
  } catch (error) {
    sessionStorage.removeItem(authCacheKey);
    if (!isLocalPreview) {
      const detail = error?.name === "AbortError"
        ? "读取账号角色与模块开放状态超时。请刷新页面，或重新登录后再进入模块。"
        : "读取账号角色与模块开放状态失败。请刷新页面，或重新登录后再进入模块。";
      renderGuardError("权限校验失败", detail);
      return;
    }
    // Static file fallback keeps direct local previews usable before the API server is running.
  }
  const module = state.modules.find(item => item.id === moduleId);
  const currentUser = state.users.find(user => user.id === state.selectedUserId) || state.users[0];
  const currentRoleIds = Array.isArray(currentUser?.roleIds) ? currentUser.roleIds : [];
  const isSystemAdmin = currentRoleIds.includes("admin");
  const canAccessAdmin = !adminOnly || currentRoleIds.includes("admin");
  const canEnter = Boolean(module?.enabled) && (isSystemAdmin || (typeof module?.canEnter === "boolean" ? module.canEnter : currentRoleIds.some(roleId => {
    return state.moduleAccess[roleId]?.[moduleId] && state.rolePermissions[roleId]?.enter;
  })));

  if ((adminOnly && canAccessAdmin) || (!adminOnly && canEnter)) {
    finishLoading();
    return;
  }

  const reason = adminOnly ? "后台管理仅系统管理员可访问" : (module?.enabled ? "当前用户没有该模块管理员角色" : "该模块权限未开放");
  const moduleName = escapeHtml(adminOnly ? "后台管理" : (module?.name || "当前模块"));
  const safeReason = escapeHtml(reason);
  document.open();
  document.write(`<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>无权限访问 · 西格玛工作台</title>
    <link rel="icon" type="image/png" href="assets/bonus-logo-dark.png" />
    <style>
      * { box-sizing: border-box; }
      body {
        min-height: 100vh;
        margin: 0;
        display: grid;
        place-items: center;
        background: #eef3f7;
        color: #0f172a;
        font-family: "PingFang SC", "Microsoft YaHei", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }
      main {
        width: min(560px, calc(100vw - 32px));
        border: 1px solid rgba(255, 255, 255, 0.78);
        border-radius: 28px;
        padding: 28px;
        background: rgba(255, 255, 255, 0.72);
        box-shadow: 0 28px 76px rgba(15, 23, 42, 0.12), inset 0 1px 0 rgba(255, 255, 255, 0.86);
      }
      p {
        margin: 0 0 8px;
        color: #2563eb;
        font-size: 12px;
        font-weight: 800;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }
      h1 {
        margin: 0;
        font-size: 30px;
        line-height: 1.12;
      }
      span {
        display: block;
        margin-top: 12px;
        color: #475569;
        font-size: 14px;
        line-height: 1.7;
      }
      nav {
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        margin-top: 22px;
      }
      a {
        border-radius: 999px;
        padding: 11px 15px;
        color: #fff;
        background: linear-gradient(135deg, #0f172a, #1e3a8a);
        text-decoration: none;
        font-size: 13px;
        font-weight: 800;
      }
      a.secondary {
        color: #0f172a;
        background: rgba(255, 255, 255, 0.78);
        box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.28);
      }
    </style>
  </head>
  <body>
    <main>
      <p>Access Guard</p>
      <h1>无权限访问：${moduleName}</h1>
      <span>${safeReason}。请返回首页切换模拟用户，或在后台管理中开放模块权限/授予对应模块管理员角色。</span>
      <nav>
        <a href="/">返回工作台首页</a>
        <a class="secondary" href="admin.html">进入后台管理</a>
      </nav>
    </main>
  </body>
</html>`);
  document.close();
  window.stop();
})();
