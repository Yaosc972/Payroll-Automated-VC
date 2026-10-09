(() => {
  "use strict";
  const api = "/api/china-employee-payroll/activities", el = name => document.getElementById(`payrollActivity${name}`);
  const titles = { "meal-allowance": "集团技术部餐补", "wx-meal-allowance": "WX 技术部餐补", "relocation-allowance": "职场搬迁补贴 · ABU" };
  const labels = { draft: "待核算", running: "核算中", completed: "已核算", failed: "核算失败" };
  const escape = value => String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const defaultAvatar = "assets/payroll-default-avatar.png";
  function renderCreator(creator) {
    const name = creator?.name || "未记录";
    let avatar = defaultAvatar;
    try { const url = new URL(creator?.avatarUrl || defaultAvatar, location.href); if (["https:", "http:"].includes(url.protocol)) avatar = url.href; } catch { /* Use the supplied default avatar. */ }
    return `<span class="activity-creator"><img src="${escape(avatar)}" alt="" width="32" height="32" loading="lazy" referrerpolicy="no-referrer" /><span>${escape(name)}</span></span>`;
  }
  el("Rows").addEventListener("error", event => {
    const img = event.target;
    if (img instanceof HTMLImageElement && !img.dataset.fallback) { img.dataset.fallback = "true"; img.src = defaultAvatar; }
  }, true);
  let page = 1, pages = 1, listVersion = 0, routeVersion = 0, timer = null, debounce = null, openedId = "";
  const href = a => `?activity=${a.activityId}#${a.subject}`;
  const monthLabel = month => /^\d{4}-\d{2}$/.test(month) ? `${month.slice(0,4)}年${Number(month.slice(5))}月` : "历史核算";
  async function request(url, options = {}) {
    const response = await fetch(url, { ...options, signal: AbortSignal.timeout(30000) });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "活动读取失败，请重试。");
    return data;
  }
  async function loadList() {
    const version = ++listVersion;
    const params = new URLSearchParams({ page: String(page), page_size: "20", search: el("Search").value.trim(), subject: el("Subject").value, month: el("Month").value, status: el("Status").value });
    const error = document.getElementById("payrollActivitiesError");
    el("Refresh").disabled = true;
    try {
      const data = await request(`${api}?${params}`);
      if (version !== listVersion) return;
      error.hidden = true; page = data.page; pages = Math.max(1, Math.ceil(data.total / data.pageSize));
      el("Rows").innerHTML = data.activities.map(a => `<tr><td class="activity-name"><a class="activity-open" href="${href(a)}">${escape(a.name)}</a><small>${a.status === "draft" ? a.subject === "wx-meal-allowance" ? "等待上传 WX 考勤" : "等待开始核算" : a.status === "failed" ? escape(a.progress) : a.status === "running" ? "后台核算中，可继续查看进度" : "结果已保存，可回看与导出"}</small></td><td>${escape(titles[a.subject])}</td><td>${monthLabel(a.month)}</td><td><span class="activity-status" data-status="${escape(a.status)}">${escape(labels[a.status] || a.status)}</span></td><td>${a.status === "completed" ? Number(a.employeeCount).toLocaleString("zh-CN") : "—"}</td><td>${a.status === "completed" ? `¥ ${Number(a.amount).toLocaleString("zh-CN", {minimumFractionDigits:2, maximumFractionDigits:2})}` : "—"}</td><td>${renderCreator(a.creator)}</td><td>${escape(a.createdAt.slice(0,16).replace("T", " "))}</td><td><a class="activity-open" href="${href(a)}">${a.status === "completed" ? "查看结果" : a.status === "running" ? "查看进度" : "进入活动"} →</a></td></tr>`).join("") || `<tr><td colspan="9">${el("Search").value || el("Subject").value || el("Month").value || el("Status").value ? "没有符合条件的活动，请调整筛选。" : "暂无核算活动，点击新建活动开始。"}</td></tr>`;
      el("Count").textContent = `共 ${data.total} 个活动 · 第 ${page} / ${pages} 页`;
      el("Prev").disabled = page <= 1; el("Next").disabled = page >= pages;
    } catch (failure) {
      if (version !== listVersion) return;
      error.textContent = failure.message || "活动列表读取失败，请点击刷新重试。"; error.hidden = false;
      el("Count").textContent = "读取失败";
    } finally { if (version === listVersion) el("Refresh").disabled = false; }
  }
  function syncViews() {
    const list = location.hash === "#activities", work = Object.keys(titles).some(s => location.hash === `#${s}`);
    document.getElementById("moduleHub").hidden = list || work;
    document.getElementById("payrollActivitiesView").hidden = !list;
    document.getElementById("mealAllowanceWorkbench").hidden = !["#meal-allowance", "#wx-meal-allowance"].includes(location.hash);
    document.getElementById("relocationWorkbench").hidden = location.hash !== "#relocation-allowance";
    document.getElementById("payrollSubjectsTab").setAttribute("aria-current", !list && !work ? "page" : "false");
    document.getElementById("payrollActivitiesTab").setAttribute("aria-current", list || work ? "page" : "false");
    document.body.dataset.view = work ? "workbench" : list ? "activities" : "hub";
  }
  function showActivity(activity, autoStart = false) {
    openedId = activity.activityId;
    document.getElementById("payrollActivityLoading").hidden = true; syncViews();
    if (activity.subject === "relocation-allowance") window.RelocationAllowance.openActivity(activity, autoStart);
    else window.MealAllowance.openActivity(activity, autoStart);
    window.scrollTo({ top: 0, behavior: "instant" });
  }
  async function route() {
    const version = ++routeVersion; clearInterval(timer); timer = null;
    document.getElementById("payrollActivityLoading").hidden = true;
    syncViews();
    if (location.hash === "#activities" || !Object.keys(titles).some(s => location.hash === `#${s}`)) {
      openedId = "";
      if (new URLSearchParams(location.search).has("activity")) history.replaceState(null, "", `${location.pathname}${location.hash}`);
      if (location.hash === "#activities") { loadList(); timer = setInterval(loadList, 10000); }
      return;
    }
    const id = new URLSearchParams(location.search).get("activity");
    if (!id) return;
    if (id === openedId) return;
    document.getElementById("mealAllowanceWorkbench").hidden = true;
    document.getElementById("relocationWorkbench").hidden = true;
    document.getElementById("payrollActivityLoading").hidden = false;
    document.getElementById("payrollActivityMessage").textContent = "正在读取活动…";
    try {
      const activity = await request(`${api}/${encodeURIComponent(id)}`);
      if (version !== routeVersion) return;
      history.replaceState(null, "", href(activity)); showActivity(activity);
    } catch (failure) { if (version === routeVersion) document.getElementById("payrollActivityMessage").textContent = failure.message || "活动读取失败，请重试。"; }
  }
  window.PayrollActivities = {
    create: payload => request(api, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }),
    open(activity, autoStart = false) { ++routeVersion; clearInterval(timer); timer = null; history.pushState(null, "", href(activity)); showActivity(activity, autoStart); }
  };
  el("Search").addEventListener("input", () => { clearTimeout(debounce); debounce = setTimeout(() => { page = 1; loadList(); }, 250); });
  ["Subject", "Month", "Status"].forEach(name => el(name).addEventListener("change", () => { page = 1; loadList(); }));
  el("Refresh").addEventListener("click", loadList);
  el("Prev").addEventListener("click", () => { if (page > 1) { --page; loadList(); } });
  el("Next").addEventListener("click", () => { if (page < pages) { ++page; loadList(); } });
  el("Rows").addEventListener("click", event => {
    const link = event.target.closest("a.activity-open");
    if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault(); history.pushState(null, "", link.getAttribute("href")); route();
  });
  window.addEventListener("hashchange", route); window.addEventListener("popstate", route);
  window.addEventListener("payroll-activities-updated", () => { if (location.hash === "#activities") loadList(); });
  route();
})();
