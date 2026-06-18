(() => {
  const fallbackUsers = [
    { id: "payrollAdmin", name: "Payroll Admin", roleIds: ["admin"] },
    { id: "recruitmentAdminUser", name: "Recruitment Admin", roleIds: ["recruitmentAdmin"] },
    { id: "cnPayrollAdminUser", name: "CN Payroll Admin", roleIds: ["employeeAdmin", "domesticAdmin"] },
    { id: "fbuAdminUser", name: "FBU Bonus Admin", roleIds: ["fbuAdmin"] },
    { id: "overseasAdminUser", name: "Overseas Audit Admin", roleIds: ["overseasAdmin"] },
  ];
  const roleNames = {
    admin: "系统管理员",
    recruitmentAdmin: "招聘奖金核算管理员",
    employeeAdmin: "国内正式工核算管理员",
    domesticAdmin: "国内外包工核算管理员",
    fbuAdmin: "FBU美洲绩效核算管理员",
    overseasAdmin: "海外报账管理员",
  };
  const userList = document.getElementById("loginUserList");
  const status = document.getElementById("loginStatus");
  const feishuLoginLink = document.getElementById("feishuLoginLink");
  const feishuLoginStatus = document.getElementById("feishuLoginStatus");
  const mockLoginPanel = document.getElementById("mockLoginPanel");
  const searchParams = new URLSearchParams(window.location.search);
  const nextUrl = searchParams.get("next") || "/";
  const isLocalDev = ["localhost", "127.0.0.1", ""].includes(window.location.hostname);
  const mockEnabled = isLocalDev || searchParams.get("mock") === "1";

  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[char]);

  const showMockLogin = () => {
    if (!mockLoginPanel) return;
    mockLoginPanel.hidden = false;
    mockLoginPanel.open = mockEnabled;
  };

  const redirectIfAlreadyLoggedIn = async () => {
    if (searchParams.get("force") === "1") return false;
    try {
      const response = await fetch("/api/me", { credentials: "same-origin" });
      if (!response.ok) return false;
      sessionStorage.setItem("sigma-auth-context-v1", JSON.stringify({
        createdAt: Date.now(),
        me: await response.json(),
      }));
      status.textContent = "已登录，正在进入工作台...";
      window.location.replace(nextUrl);
      return true;
    } catch {
      return false;
    }
  };

  const renderUsers = (users) => {
    userList.innerHTML = users.map(user => `
      <button type="button" data-user-id="${escapeHtml(user.id)}">
        <strong>${escapeHtml(user.name)}</strong>
        <span>${escapeHtml((user.roleIds || []).map(roleId => roleNames[roleId] || roleId).join("、") || "待授权")}</span>
      </button>
    `).join("");
  };

  const loadUsers = async () => {
    try {
      const response = await fetch("/api/auth/mock-users");
      if (!response.ok) throw new Error(`API ${response.status}`);
      const data = await response.json();
      renderUsers(data.users || fallbackUsers);
      status.textContent = "开发调试模式：请选择一个模拟用户登录。";
    } catch {
      renderUsers(fallbackUsers);
      status.textContent = "开发调试模式：未连接后端，显示本地模拟用户。";
    }
  };

  const loadFeishuConfig = async () => {
    try {
      const response = await fetch("/api/auth/feishu/config");
      if (!response.ok) throw new Error(`API ${response.status}`);
      const data = await response.json();
      if (data.configured) {
        feishuLoginLink.setAttribute("aria-disabled", "false");
        feishuLoginLink.href = `/api/auth/feishu/login?next=${encodeURIComponent(nextUrl)}`;
        feishuLoginStatus.textContent = "飞书应用已配置，可进入授权登录流程。";
        if (mockEnabled) {
          showMockLogin();
          await loadUsers();
        } else {
          status.textContent = "请使用飞书登录。角色授权由系统管理员在后台管理中配置。";
        }
      } else {
        feishuLoginStatus.textContent = "飞书应用尚未配置，当前仅开放开发调试模拟登录。";
        showMockLogin();
        await loadUsers();
      }
    } catch {
      feishuLoginStatus.textContent = "后端未连接，当前仅开放开发调试模拟登录。";
      showMockLogin();
      await loadUsers();
    }
  };

  feishuLoginLink.addEventListener("click", (event) => {
    if (feishuLoginLink.getAttribute("aria-disabled") !== "false") {
      event.preventDefault();
    }
  });

  userList.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-user-id]");
    if (!button) return;
    status.textContent = "正在登录...";
    try {
      const response = await fetch("/api/auth/mock-login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ userId: button.dataset.userId }),
      });
      if (!response.ok) throw new Error(`API ${response.status}`);
      sessionStorage.removeItem("sigma-auth-context-v1");
      window.location.href = nextUrl;
    } catch {
      sessionStorage.removeItem("sigma-auth-context-v1");
      localStorage.setItem("sigma-admin-console-draft-v3", JSON.stringify({
        selectedUserId: button.dataset.userId,
      }));
      status.textContent = "后端未连接，已切换本地模拟用户。";
      window.location.href = nextUrl;
    }
  });

  redirectIfAlreadyLoggedIn().then((redirected) => {
    if (!redirected) loadFeishuConfig();
  });
})();
