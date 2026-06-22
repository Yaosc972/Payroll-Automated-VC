(() => {
  const storageKey = "sigma-admin-console-draft-v3";
  const defaults = {
    selectedUserId: "payrollAdmin",
    users: [
      { id: "payrollAdmin", name: "Payroll Admin", roleIds: ["admin"], status: "启用" },
      { id: "recruitmentAdminUser", name: "Recruitment Admin", roleIds: ["recruitmentAdmin"], status: "启用" },
      { id: "cnPayrollAdminUser", name: "CN Payroll Admin", roleIds: ["employeeAdmin", "domesticAdmin"], status: "启用" },
      { id: "fbuAdminUser", name: "FBU Bonus Admin", roleIds: ["fbuAdmin"], status: "启用" },
      { id: "overseasAdminUser", name: "Overseas Audit Admin", roleIds: ["overseasAdmin"], status: "启用" },
    ],
    roles: [
      { id: "admin", name: "系统管理员" },
      { id: "recruitmentAdmin", name: "招聘奖金核算管理员", moduleId: "recruitment" },
      { id: "employeeAdmin", name: "国内正式工核算管理员", moduleId: "employee" },
      { id: "domesticAdmin", name: "国内外包工核算管理员", moduleId: "domestic" },
      { id: "fbuAdmin", name: "FBU美洲绩效核算管理员", moduleId: "fbu" },
      { id: "overseasAdmin", name: "海外报账管理员", moduleId: "overseas" },
    ],
    modules: [
      { id: "recruitment", name: "全球招聘奖金核算", owner: "招聘奖金核算管理员", enabled: true },
      { id: "employee", name: "中国区正式工薪酬核算", owner: "国内正式工核算管理员", enabled: false },
      { id: "domestic", name: "中国区外包工薪酬核算", owner: "国内外包工核算管理员", enabled: false },
      { id: "fbu", name: "FBU美洲绩效奖金核算", owner: "FBU美洲绩效核算管理员", enabled: false },
      { id: "overseas", name: "海外劳务报账核对", owner: "海外报账管理员", enabled: true },
    ],
    features: [
      { id: "enter", name: "进入模块", role: "对应模块管理员", enabled: true },
      { id: "import", name: "导入数据", role: "对应模块管理员", enabled: true },
      { id: "calculate", name: "提交核算", role: "对应模块管理员", enabled: true },
      { id: "review", name: "异常复核", role: "对应模块管理员", enabled: true },
      { id: "export", name: "导出结果", role: "系统管理员", enabled: true },
      { id: "archive", name: "归档批次", role: "系统管理员", enabled: false },
      { id: "audit", name: "查看日志", role: "系统管理员", enabled: true },
    ],
    rolePermissions: {
      admin: { enter: true, import: true, calculate: true, review: true, export: true, archive: true, audit: true },
      recruitmentAdmin: { enter: true, import: true, calculate: true, review: true, export: false, archive: false, audit: false },
      employeeAdmin: { enter: true, import: true, calculate: true, review: true, export: false, archive: false, audit: false },
      domesticAdmin: { enter: true, import: true, calculate: true, review: true, export: false, archive: false, audit: false },
      fbuAdmin: { enter: true, import: true, calculate: true, review: true, export: false, archive: false, audit: false },
      overseasAdmin: { enter: true, import: true, calculate: true, review: true, export: false, archive: false, audit: false },
    },
    moduleAccess: {
      admin: { recruitment: true, employee: true, domestic: true, fbu: true, overseas: true },
      recruitmentAdmin: { recruitment: true, employee: false, domestic: false, fbu: false, overseas: false },
      employeeAdmin: { recruitment: false, employee: true, domestic: false, fbu: false, overseas: false },
      domesticAdmin: { recruitment: false, employee: false, domestic: true, fbu: false, overseas: false },
      fbuAdmin: { recruitment: false, employee: false, domestic: false, fbu: true, overseas: false },
      overseasAdmin: { recruitment: false, employee: false, domestic: false, fbu: false, overseas: true },
    },
    config: {
      defaultPeriod: "2026-05",
      reviewThreshold: 80,
      exportPolicy: "owner-and-admin",
    },
    logs: [
      { time: "2026-06-12 09:30", actor: "Payroll Admin", action: "初始化权限草稿", target: "后台管理" },
      { time: "2026-06-12 09:42", actor: "Payroll Admin", action: "启用模块", target: "FBU美洲绩效奖金核算" },
      { time: "2026-06-12 10:05", actor: "Recruitment Admin", action: "进入模块核算", target: "全球招聘奖金核算" },
      { time: "2026-06-12 10:28", actor: "Domestic Labor Admin", action: "提交核算", target: "中国区外包工薪酬核算" },
      { time: "2026-06-12 11:10", actor: "Overseas Audit Admin", action: "进入模块核对", target: "海外劳务报账核对" },
    ],
  };

  const readState = () => {
    try {
      const stored = JSON.parse(localStorage.getItem(storageKey) || "{}");
      return {
        ...structuredClone(defaults),
        ...stored,
        config: { ...defaults.config, ...(stored.config || {}) },
        rolePermissions: { ...structuredClone(defaults.rolePermissions), ...(stored.rolePermissions || {}) },
        moduleAccess: { ...structuredClone(defaults.moduleAccess), ...(stored.moduleAccess || {}) },
      };
    } catch {
      return structuredClone(defaults);
    }
  };

  let state = readState();
  let apiBacked = false;
  let currentActorId = "";

  const mergeApiState = (apiState) => {
    const roleNameById = Object.fromEntries((apiState.roles || []).map(role => [role.id, role.name]));
    return {
      ...state,
      users: apiState.users || state.users,
      roles: apiState.roles || state.roles,
      modules: (apiState.modules || state.modules).map(module => ({
        ...module,
        owner: module.ownerRoleName || roleNameById[module.ownerRoleId] || module.owner || "",
      })),
      rolePermissions: apiState.rolePermissions || state.rolePermissions,
      moduleAccess: apiState.moduleAccess || state.moduleAccess,
    };
  };

  const apiRequest = async (url, options = {}) => {
    const response = await fetch(url, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    if (response.status === 401) {
      window.location.href = `login.html?next=${encodeURIComponent(window.location.pathname || "/admin.html")}`;
      throw new Error("Unauthorized");
    }
    if (!response.ok) {
      let detail = `API ${response.status}`;
      try {
        const data = await response.json();
        detail = data.detail || detail;
      } catch {
        // Keep the HTTP status fallback.
      }
      throw new Error(detail);
    }
    return response.json();
  };

  const loadApiState = async () => {
    try {
      const [apiState, auditData, meData] = await Promise.all([
        apiRequest("/api/admin/state"),
        apiRequest("/api/admin/audit-logs?limit=12"),
        apiRequest("/api/me"),
      ]);
      currentActorId = meData.user?.id || "";
      state = {
        ...mergeApiState(apiState),
        logs: (auditData.logs || []).map(log => ({
          time: log.createdAt,
          actor: log.actorUserId,
          action: log.action,
          target: log.targetId,
        })),
      };
      apiBacked = true;
      saveState("已连接数据库权限配置");
      render();
    } catch {
      apiBacked = false;
      saveState("使用本地草稿配置");
      render();
    }
  };

  const refreshApiState = async (message = "数据库权限配置已保存") => {
    if (!apiBacked) {
      saveState(message);
      render();
      return;
    }
    try {
      const [apiState, auditData, meData] = await Promise.all([
        apiRequest("/api/admin/state"),
        apiRequest("/api/admin/audit-logs?limit=12"),
        apiRequest("/api/me"),
      ]);
      currentActorId = meData.user?.id || currentActorId;
      state = {
        ...mergeApiState(apiState),
        logs: (auditData.logs || []).map(log => ({
          time: log.createdAt,
          actor: log.actorUserId,
          action: log.action,
          target: log.targetId,
        })),
      };
      saveState(message);
      render();
    } catch {
      apiBacked = false;
      saveState("数据库连接失败，已切回本地草稿");
      render();
    }
  };

  const getRole = (roleId) => state.roles.find(role => role.id === roleId);

  const getModule = (moduleId) => state.modules.find(module => module.id === moduleId);

  const escapeHtml = (value) => String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");

  const getRoleNames = (roleIds) => roleIds.map(roleId => getRole(roleId)?.name).filter(Boolean).join("、");

  const getUserScope = (user) => {
    if (user.roleIds.includes("admin")) return "全模块";
    const moduleNames = user.roleIds
      .map(roleId => getRole(roleId)?.moduleId)
      .filter(Boolean)
      .map(moduleId => getModule(moduleId)?.name)
      .filter(Boolean);
    return moduleNames.join("、") || "未配置模块";
  };

  const roleOptionMarkup = (user) => {
    const noModuleChecked = !Array.isArray(user.roleIds) || user.roleIds.length === 0;
    return `
      <label class="admin-role-option is-default">
        <input type="checkbox" value="" ${noModuleChecked ? "checked" : ""} data-role-none="true" />
        <span>默认权限：无模块权限</span>
      </label>
      ${state.roles.map(role => `
        <label class="admin-role-option">
          <input type="checkbox" value="${escapeHtml(role.id)}" ${user.roleIds.includes(role.id) ? "checked" : ""} />
          <span>${escapeHtml(role.name)}</span>
        </label>
      `).join("")}
    `;
  };

  const getStatusLabel = (status) => {
    const labels = {
      active: "启用",
      pending: "待授权",
      disabled: "停用",
      启用: "启用",
      待授权: "待授权",
      停用: "停用",
    };
    return labels[status] || status || "待授权";
  };

  const saveState = (message = "本地草稿已保存") => {
    localStorage.setItem(storageKey, JSON.stringify(state));
    const saveStateEl = document.getElementById("adminSaveState");
    if (saveStateEl) saveStateEl.textContent = message;
  };

  const addLog = (action, target = "权限配置") => {
    const now = new Date();
    const time = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")} ${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
    state.logs.unshift({ time, actor: "Payroll Admin", action, target });
    state.logs = state.logs.slice(0, 12);
    saveState("操作已写入本地草稿");
    render();
  };

  const toggleMarkup = (checked, label, dataAttrs) => {
    const attrs = Object.entries(dataAttrs).map(([key, value]) => `data-${key}="${value}"`).join(" ");
    return `
      <label class="admin-toggle">
        <input type="checkbox" ${checked ? "checked" : ""} ${attrs} />
        <span aria-hidden="true"></span>
        <b>${label}</b>
      </label>
    `;
  };

  const getUserInitials = (user) => String(user.name || user.email || user.id || "U").trim().slice(0, 2).toUpperCase();

  const userAvatarMarkup = (user) => {
    if (user.avatarUrl) {
      return `<img class="admin-user-avatar" src="${escapeHtml(user.avatarUrl)}" alt="" />`;
    }
    return `<span class="admin-user-avatar fallback" aria-hidden="true">${escapeHtml(getUserInitials(user))}</span>`;
  };

  const renderUsers = () => {
    const list = document.getElementById("userRoleList");
    if (!list) return;
    const rows = state.users.map(user => {
      const roleNames = getRoleNames(user.roleIds) || "默认权限：无模块权限";
      return `
        <tr>
          <td>
            <div class="admin-user-identity">
              ${userAvatarMarkup(user)}
              <div>
                <strong>${escapeHtml(user.name)}</strong>
                <span>${escapeHtml(user.email || user.id)}</span>
              </div>
            </div>
          </td>
          <td><span class="admin-role-summary">${escapeHtml(roleNames)}</span></td>
          <td>${escapeHtml(getUserScope(user))}</td>
          <td><span class="admin-status-pill">${escapeHtml(getStatusLabel(user.status))}</span></td>
          <td>
            <details class="admin-role-dropdown" data-role-dropdown data-user="${escapeHtml(user.id)}">
              <summary>
                <span>${escapeHtml(user.roleIds.length ? `${user.roleIds.length} 个角色` : "默认权限")}</span>
                <b>选择角色</b>
              </summary>
              <div class="admin-role-menu" data-user="${escapeHtml(user.id)}">
                ${roleOptionMarkup(user)}
                <button type="button" data-type="save-user-roles" data-user="${escapeHtml(user.id)}">保存授权</button>
              </div>
            </details>
          </td>
        </tr>
      `;
    }).join("");
    list.innerHTML = `
      <table class="admin-user-table">
        <thead>
          <tr>
            <th>用户</th>
            <th>当前角色</th>
            <th>可进入范围</th>
            <th>状态</th>
            <th>角色授权</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    `;
  };

  const renderModules = () => {
    const list = document.getElementById("modulePermissionList");
    if (!list) return;
    list.innerHTML = state.modules.map(module => `
      <article class="admin-permission-card ${module.enabled ? "is-enabled" : "is-disabled"}">
        <div class="admin-module-card-head">
          <div>
            <strong>${module.name}</strong>
            <span>默认模块管理员：${module.owner}</span>
            <small>模块未开放时，模块管理员不能进入；系统管理员仍可进入验证。</small>
          </div>
          ${toggleMarkup(module.enabled, module.enabled ? "模块开放" : "模块关闭", { type: "module", id: module.id })}
        </div>
        <div class="admin-module-access-grid" aria-label="${module.name} 角色进入权限">
          ${state.roles.map(role => toggleMarkup(Boolean(state.moduleAccess[role.id]?.[module.id]), role.name, {
            type: "module-access",
            role: role.id,
            module: module.id,
          })).join("")}
        </div>
      </article>
    `).join("");
  };

  const renderFeatures = () => {
    const list = document.getElementById("featurePermissionList");
    if (!list) return;
    const roleHeaders = state.roles.map(role => `<th>${role.name}</th>`).join("");
    const rows = state.features.map(feature => `
      <tr>
        <th scope="row">
          <strong>${feature.name}</strong>
          <span>默认授权：${feature.role} · ${feature.enabled ? "功能开放" : "功能关闭"}</span>
        </th>
        ${state.roles.map(role => `
          <td>
            ${toggleMarkup(Boolean(state.rolePermissions[role.id]?.[feature.id]), state.rolePermissions[role.id]?.[feature.id] ? "允许" : "拒绝", {
              type: "role",
              role: role.id,
              feature: feature.id,
            })}
          </td>
        `).join("")}
      </tr>
    `).join("");
    list.innerHTML = `
      <table class="admin-feature-table">
        <thead>
          <tr>
            <th>功能</th>
            ${roleHeaders}
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    `;
  };

  const renderConfig = () => {
    const defaultPeriod = document.getElementById("defaultPeriod");
    const reviewThreshold = document.getElementById("reviewThreshold");
    const exportPolicy = document.getElementById("exportPolicy");
    const activeAdminUser = document.getElementById("activeAdminUser");
    if (defaultPeriod) defaultPeriod.value = state.config.defaultPeriod;
    if (reviewThreshold) reviewThreshold.value = state.config.reviewThreshold;
    if (exportPolicy) exportPolicy.value = state.config.exportPolicy;
    if (activeAdminUser) {
      activeAdminUser.innerHTML = state.users.map(user => `
        <option value="${user.id}">${user.name} · ${getRoleNames(user.roleIds)}</option>
      `).join("");
      activeAdminUser.value = state.selectedUserId;
    }
  };

  const renderLogs = () => {
    const rows = document.getElementById("auditLogRows");
    if (!rows) return;
    rows.innerHTML = state.logs.map(log => `
      <tr>
        <td>${log.time}</td>
        <td>${log.actor}</td>
        <td>${log.action}</td>
        <td>${log.target}</td>
      </tr>
    `).join("");
  };

  const renderMetrics = () => {
    const enabledModuleCount = document.getElementById("enabledModuleCount");
    const enabledFeatureCount = document.getElementById("enabledFeatureCount");
    const adminLogCount = document.getElementById("adminLogCount");
    if (enabledModuleCount) enabledModuleCount.textContent = state.modules.filter(item => item.enabled).length;
    if (enabledFeatureCount) {
      enabledFeatureCount.textContent = Object.values(state.rolePermissions)
        .flatMap(permissionMap => Object.values(permissionMap))
        .filter(Boolean).length;
    }
    if (adminLogCount) adminLogCount.textContent = state.logs.length;
  };

  const render = () => {
    renderUsers();
    renderModules();
    renderFeatures();
    renderConfig();
    renderLogs();
    renderMetrics();
  };

  document.addEventListener("change", async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement || target instanceof HTMLSelectElement)) return;

    if (target.dataset.type === "module") {
      const module = state.modules.find(item => item.id === target.dataset.id);
      if (!module) return;
      if (apiBacked) {
        await apiRequest(`/api/admin/modules/${module.id}`, {
          method: "PATCH",
          body: JSON.stringify({ enabled: target.checked }),
        });
        await refreshApiState(target.checked ? "模块开放状态已写入数据库" : "模块关闭状态已写入数据库");
        return;
      }
      module.enabled = target.checked;
      addLog(module.enabled ? "开放模块权限" : "停用模块权限", module.name);
      return;
    }

    if (target.dataset.type === "feature") {
      const feature = state.features.find(item => item.id === target.dataset.id);
      if (!feature) return;
      feature.enabled = target.checked;
      addLog(feature.enabled ? "启用功能权限" : "关闭功能权限", feature.name);
      return;
    }

    if (target.dataset.type === "role") {
      const role = state.roles.find(item => item.id === target.dataset.role);
      const feature = state.features.find(item => item.id === target.dataset.feature);
      if (role?.id === "admin") {
        target.checked = true;
        saveState("系统管理员权限保持全开");
        render();
        return;
      }
      if (!role || !feature) return;
      if (apiBacked) {
        await apiRequest(`/api/admin/roles/${role.id}/features/${feature.id}`, {
          method: "PUT",
          body: JSON.stringify({ enabled: target.checked }),
        });
        await refreshApiState(target.checked ? "角色功能权限已写入数据库" : "角色功能权限已写入数据库");
        return;
      }
      state.rolePermissions[role.id] = state.rolePermissions[role.id] || {};
      state.rolePermissions[role.id][feature.id] = target.checked;
      addLog(target.checked ? "授予角色功能权限" : "撤销角色功能权限", `${role.name} · ${feature.name}`);
      return;
    }

    if (target.dataset.type === "module-access") {
      const role = state.roles.find(item => item.id === target.dataset.role);
      const module = state.modules.find(item => item.id === target.dataset.module);
      if (!role || !module) return;
      if (role.id === "admin") {
        target.checked = true;
        saveState("系统管理员模块进入权限保持全开");
        render();
        return;
      }
      if (apiBacked) {
        await apiRequest(`/api/admin/modules/${module.id}/roles/${role.id}`, {
          method: "PUT",
          body: JSON.stringify({ canEnter: target.checked }),
        });
        await refreshApiState(target.checked ? "角色进入模块权限已写入数据库" : "角色进入模块权限已写入数据库");
        return;
      }
      state.moduleAccess[role.id] = state.moduleAccess[role.id] || {};
      state.moduleAccess[role.id][module.id] = target.checked;
      addLog(target.checked ? "开放角色进入模块" : "关闭角色进入模块", `${role.name} · ${module.name}`);
      return;
    }

    if (target.id === "activeAdminUser") {
      const user = state.users.find(item => item.id === target.value);
      if (!user) return;
      state.selectedUserId = user.id;
      addLog("切换模拟当前用户", `${user.name} · ${getRoleNames(user.roleIds)}`);
      return;
    }

    if (target.id in state.config) {
      state.config[target.id] = target.type === "number" ? Number(target.value) : target.value;
      saveState("模块配置已保存到本地草稿");
    }
  });

  document.addEventListener("click", async (event) => {
    const roleSummary = event.target.closest(".admin-role-dropdown summary");
    if (roleSummary) {
      document.querySelectorAll(".admin-role-dropdown[open]").forEach(dropdown => {
        if (dropdown !== roleSummary.parentElement) dropdown.removeAttribute("open");
      });
    }

    const saveRolesButton = event.target.closest("[data-type='save-user-roles']");
    if (saveRolesButton) {
      const user = state.users.find(item => item.id === saveRolesButton.dataset.user);
      const menu = saveRolesButton.closest(".admin-role-menu");
      if (!user || !menu) return;
      const noneChecked = menu.querySelector("[data-role-none]")?.checked;
      let nextRoleIds = noneChecked ? [] : Array.from(menu.querySelectorAll("input[type='checkbox']:checked"))
        .map(input => input.value)
        .filter(Boolean);
      nextRoleIds = Array.from(new Set(nextRoleIds));
      if (user.id === "payrollAdmin" && !nextRoleIds.includes("admin")) {
        nextRoleIds.unshift("admin");
        saveState("系统管理员账号必须保留系统管理员角色");
      }
      if (user.id === currentActorId && !nextRoleIds.includes("admin")) {
        saveState("不能移除当前登录账号的系统管理员角色");
        render();
        return;
      }
      saveRolesButton.disabled = true;
      saveRolesButton.textContent = "保存中";
      if (apiBacked) {
        try {
          await apiRequest(`/api/admin/users/${user.id}/roles`, {
            method: "PUT",
            body: JSON.stringify({ roleIds: nextRoleIds }),
          });
          sessionStorage.removeItem("sigma-auth-context-v1");
          sessionStorage.removeItem("sigma-auth-context-v2");
          await refreshApiState("用户角色已写入数据库");
        } catch (error) {
          saveState(error.message || "用户角色保存失败");
          render();
        }
        return;
      }
      user.roleIds = nextRoleIds;
      user.status = nextRoleIds.length ? "启用" : "待授权";
      addLog("更新用户角色", `${user.name} · ${getRoleNames(user.roleIds) || "默认权限：无模块权限"}`);
      return;
    }

    const target = event.target.closest("[data-log-action]");
    if (target) addLog(target.dataset.logAction);
  });

  document.addEventListener("change", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement)) return;
    const menu = target.closest(".admin-role-menu");
    if (!menu) return;
    if (target.dataset.roleNone === "true" && target.checked) {
      menu.querySelectorAll("input[type='checkbox']").forEach(input => {
        if (input !== target) input.checked = false;
      });
      return;
    }
    if (target.checked) {
      const noneInput = menu.querySelector("[data-role-none]");
      if (noneInput) noneInput.checked = false;
    }
    if (!menu.querySelector("input[type='checkbox']:checked")) {
      const noneInput = menu.querySelector("[data-role-none]");
      if (noneInput) noneInput.checked = true;
    }
  });

  document.getElementById("resetAdminConfig")?.addEventListener("click", () => {
    localStorage.removeItem(storageKey);
    state = structuredClone(defaults);
    apiBacked = false;
    saveState("已重置为默认静态配置");
    render();
  });

  render();
  loadApiState();
})();
