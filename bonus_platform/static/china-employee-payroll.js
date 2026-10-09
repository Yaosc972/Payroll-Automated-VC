(() => {
  "use strict";
  const base = "/api/china-employee-payroll/meal-allowance", el = name => document.getElementById(`meal${name}`);
  const titles = { hr: "集团技术部餐补", wx: "WX 技术部餐补" };
  const current = new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit" }).format(new Date());
  const previous = new Date(`${current}-01T00:00:00Z`); previous.setUTCMonth(previous.getUTCMonth() - 1);
  const initialMonth = previous.toISOString().slice(0, 7);
  const createState = source => ({ source, month: initialMonth, version: 0, busy: false, status: "idle", runId: "", result: null, files: [], runs: [], historyVersion: 0, page: 1, query: "", filter: "all", pageSize: 25, progress: "", detail: null, startedAt: 0, exporting: false, exportState: "idle", exportMessage: "", interrupted: false, uncertain: false });
  const activityStates = new Map();
  const states = { hr: createState("hr"), wx: createState("wx") };
  let active = "hr", clock = null;
  const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const number = value => Number(value || 0).toLocaleString("zh-CN", { maximumFractionDigits: 3 });
  const money = value => Number(value || 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const monthLabel = value => /^\d{4}-\d{2}$/.test(value || "") ? `${value.slice(0, 4)}年${Number(value.slice(5))}月` : value || "历史批次";
  const isMealView = () => ["#meal-allowance", "#wx-meal-allowance"].includes(location.hash);
  function isCurrent(s, version) { return s.version === version; }
  async function request(path, options = {}, timeout = 30000) {
    const response = await fetch(path, { ...options, signal: AbortSignal.timeout(timeout) });
    const data = await response.json().catch(() => { throw new Error("核算服务返回异常，请稍后重试。"); });
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "核算请求失败，请重试。");
    return data;
  }
  function validateSource(data, s) {
    const source = data.sourceType || data.summary?.sourceType;
    if (source && source !== s.source) throw new Error("返回批次的考勤来源不匹配，请刷新历史批次重试。");
  }
  function tick() {
    const s = states[active], seconds = s.startedAt ? Math.max(0, Math.floor(((s.finishedAt || Date.now()) - s.startedAt) / 1000)) : 0;
    el("Elapsed").textContent = `已用时 ${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
  }
  function syncClock() {
    clearInterval(clock); clock = null; tick();
    if (isMealView() && states[active].busy) clock = setInterval(tick, 1000);
  }
  function renderProgress(s) {
    const running = s.busy, stage = Math.max(0, Math.min(2, Number(s.detail?.stage) || 0));
    const uploaded = s.source === "wx", final = stage === 2 || uploaded;
    const completed = s.detail?.completed, total = s.detail?.total;
    const known = running && !final && Number.isFinite(completed) && Number.isFinite(total) && total > 0;
    const fraction = known ? Math.max(0, Math.min(1, completed / total)) : null;
    const percentage = known ? `${(fraction * 100).toFixed(1).replace(/\.0$/, "")}%` : "";
    el("Processing").dataset.state = s.status;
    el("Processing").dataset.finishing = String(final);
    el("ProcessingKicker").textContent = running ? "正在核算" : s.status === "error" ? "核算未完成" : "准备就绪";
    el("StageIndex").textContent = uploaded ? "WX 考勤 · 文件核算" : running ? `步骤 0${stage + 1} / 03` : "北森考勤 · 自动核算";
    el("ProcessingTitle").textContent = s.status === "error" ? (s.interrupted ? "进度连接已中断" : "本次核算未完成") : running ? uploaded ? "正在读取考勤并核算" : ["正在匹配核算人员", "正在读取日考勤", "正在核对并生成结果"][stage] : "选择月份后开始核算";
    el("Progress").textContent = s.progress || "自动读取日考勤，按集团技术部餐补规则生成明细。";
    el("NumericProgress").hidden = !known;
    el("Percent").textContent = percentage;
    el("Count").textContent = known ? `已处理 ${number(completed)} / ${number(total)} ${s.detail.unit || "条"}` : "";
    if (known) el("Meter").setAttribute("aria-valuenow", String(fraction * 100)); else el("Meter").removeAttribute("aria-valuenow");
    el("TransitionStatus").hidden = !running || known;
    el("TransitionLabel").textContent = uploaded ? "正在读取文件、校验并计算餐补" : final ? "正在校验考勤与补贴明细" : stage === 1 ? "等待北森返回考勤数据" : "正在核对当月组织与核算人员";
    el("ChooseMonth").hidden = s.status !== "idle" || !!s.activityId;
    el("ActivityStart").hidden = s.status !== "idle" || !s.activityId || s.source !== "hr";
    el("Retry").hidden = s.status !== "error" || s.interrupted || s.uncertain;
    el("Reconnect").hidden = !s.interrupted || !s.runId;
    el("Processing").querySelector(".meal-steps").hidden = uploaded || s.status === "idle";
    el("Processing").querySelectorAll("[data-meal-step]").forEach((step, index) => {
      step.dataset.state = index < stage ? "done" : index === stage ? "active" : "pending";
      step.querySelector("b").textContent = index < stage ? "✓" : `0${index + 1}`;
      step.querySelector("small").textContent = index < stage ? "已完成" : index === stage ? s.status === "error" ? "已中断" : known ? percentage : "处理中" : "待开始";
      if (index === stage) step.setAttribute("aria-current", "step"); else step.removeAttribute("aria-current");
    });
    window.MealAllowanceMotion?.update(uploaded ? 2 : stage, fraction, running);
  }
  function warningMessages(data) {
    const warnings = data.warnings || {}, messages = Array.isArray(warnings) ? [...warnings] : [];
    if (warnings.missingColumns?.length) messages.push(`缺少必要字段：${warnings.missingColumns.join("、")}`);
    if (warnings.duplicateKeys?.length) messages.push(`发现 ${number(data.summary?.duplicateCount || warnings.duplicateKeys.length)} 条重复考勤记录，请核对源数据。`);
    if (Array.isArray(warnings.messages)) messages.push(...warnings.messages);
    return messages;
  }
  function renderRows(s) {
    const query = s.query.toLowerCase();
    const rows = (s.result?.results || []).filter(row => (s.filter === "all" || (s.filter === "payable" ? row.amount > 0 : !(row.amount > 0))) && (!query || [row.employeeId, row.employeeName, row.secondOrg, row.thirdOrg, row.fourthOrg].some(value => String(value ?? "").toLowerCase().includes(query))));
    const pages = Math.max(1, Math.ceil(rows.length / s.pageSize)); s.page = Math.max(1, Math.min(s.page, pages));
    el("Rows").innerHTML = rows.slice((s.page - 1) * s.pageSize, s.page * s.pageSize).map(row => `<tr><td>${esc(row.employeeId)}</td><td>${esc(row.employeeName)}</td><td>${esc(row.thirdOrg || row.secondOrg)}${row.fourthOrg ? `<small>${esc(row.fourthOrg)}</small>` : ""}</td><td>${number(row.payableDays)}</td><td class="meal-amount">${money(row.amount)}</td><td>${row.amount > 0 ? "已核算" : "无餐补"}${row.warnings?.length ? `<small>${esc(row.warnings.join("；"))}</small>` : ""}</td></tr>`).join("") || '<tr><td colspan="6">没有符合筛选条件的记录。</td></tr>';
    el("PageInfo").textContent = `共 ${rows.length} 人 · 第 ${s.page} / ${pages} 页`;
    el("Prev").disabled = s.page <= 1; el("Next").disabled = s.page >= pages;
  }
  function renderResult(s) {
    const summary = s.result.summary || {}, warnings = warningMessages(s.result);
    el("Summary").innerHTML = [["应发餐补", `¥ ${money(summary.totalAmount)}`], ["核算员工", `${number(summary.employeeCount)} 人`], ["有餐补员工", `${number(summary.payableEmployeeCount)} 人`], ["补贴天数", `${number(summary.payableDayCount)} 天`]].map(([label, value]) => `<div><span>${label}</span><strong>${value}</strong></div>`).join("");
    el("Warnings").hidden = !warnings.length; el("Warnings").open = !!warnings.length;
    el("WarningCount").textContent = warnings.length ? `${warnings.length} 项` : "";
    el("WarningList").innerHTML = warnings.map(message => `<li>${esc(message)}</li>`).join("");
    el("ResultMeta").textContent = `${monthLabel(s.month)} · ${number(summary.rowCount)} 条考勤`;
    el("Search").value = s.query; el("Status").value = s.filter; el("PageSize").value = String(s.pageSize); renderRows(s);
  }
  function renderExport(s) {
    el("Export").hidden = !s.result; el("Export").disabled = s.busy || s.exporting;
    el("Export").dataset.state = s.exportState;
    el("Export").textContent = ({ idle: "导出明细", loading: "正在生成 Excel…", success: "已开始下载", error: "重试导出" })[s.exportState];
    el("Export").setAttribute("aria-busy", String(s.exporting)); el("ExportStatus").textContent = s.exportMessage;
  }
  function render(s) {
    if (states[active] !== s) return;
    el("Title").textContent = titles[s.source]; el("NavTitle").textContent = titles[s.source];
    document.getElementById("mealActivityName").textContent = s.activityName || "月度餐补核算";
    el("NavSource").textContent = s.source === "hr" ? "北森考勤 · 自动读取" : "WX 考勤 · Excel 导入";
    el("MonthLabel").textContent = monthLabel(s.month);
    el("Upload").hidden = s.source !== "wx" || s.busy || !!s.result;
    el("Processing").hidden = !!s.result || (s.source === "wx" && s.status === "idle");
    el("Result").hidden = !s.result; el("Result").setAttribute("aria-busy", String(s.busy));
    el("Files").disabled = s.busy; el("UploadStart").disabled = s.busy || !s.files.length;
    el("FileLabel").textContent = s.files.length ? s.files.length === 1 ? s.files[0].name : `已选择 ${s.files.length} 个文件` : "选择考勤文件";
    el("UploadHint").textContent = s.files.length ? `为 ${monthLabel(s.month)} 核算 ${s.files.length} 个考勤文件。` : "仅核算 WX 技术部，与集团技术部分开保存。";
    renderExport(s); syncClock();
    if (s.result) { renderResult(s); window.MealAllowanceMotion?.stop(); }
    else renderProgress(s);
  }
  function renderHistory(s) {
    if (states[active] !== s) return;
    el("Runs").innerHTML = s.historyError ? `<p>${esc(s.historyError)}</p>` : s.runs.length ? s.runs.slice(0, 20).map(run => `<button type="button" class="meal-run" data-run-id="${esc(run.runId)}" ${s.busy ? "disabled" : ""} aria-current="${run.runId === s.runId}"><strong>${esc(monthLabel(run.month || run.monthLabel))}</strong><span>${({ running: "核算中", completed: "已核算", failed: "核算失败" })[run.status] || "已核算"}</span><small>${esc((run.createdAt || "").slice(0, 16).replace("T", " "))}</small></button>`).join("") : "<p>暂无核算批次。</p>";
  }
  async function loadRuns(s = states[active]) {
    if (s.activityId) { window.dispatchEvent(new Event("payroll-activities-updated")); return; }
    const version = ++s.historyVersion;
    try {
      const data = await request(`${base}/runs`);
      if (version !== s.historyVersion) return;
      s.runs = (data.runs || []).filter(run => run.sourceType === s.source); s.historyError = "";
    } catch { if (version !== s.historyVersion) return; s.historyError = "历史批次读取失败，可点击刷新重试。"; }
    renderHistory(s);
  }
  function begin(s, message) {
    s.busy = true; s.status = "running"; s.result = null; s.progress = message; s.detail = { stage: 0, completed: 0, total: null };
    s.startedAt = Date.now(); s.finishedAt = 0; s.interrupted = false; s.uncertain = false; s.page = 1; s.query = ""; s.filter = "all";
    s.exportState = "idle"; s.exportMessage = ""; render(s);
  }
  function complete(s, data) {
    validateSource(data, s);
    s.busy = false; s.status = "completed"; s.result = data; s.runId = data.runId || s.runId; s.month = data.month || data.summary?.dateStart?.slice(0, 7) || s.month;
    s.finishedAt = Date.now(); render(s);
    if (states[active] === s && isMealView()) window.MealAllowanceMotion?.reveal();
  }
  function fail(s, error) {
    s.busy = false; s.status = "error"; s.finishedAt = Date.now();
    s.progress = error.name === "TimeoutError" ? "请求超时，请重试。" : error.message || "核算未完成，请重试。";
    render(s);
  }
  async function follow(s, id, version) {
    let failures = 0;
    while (isCurrent(s, version)) {
      let data;
      try { data = await request(`${base}/runs/${encodeURIComponent(id)}`); failures = 0; }
      catch (error) {
        if (!isCurrent(s, version)) return;
        if (++failures >= 3) { s.interrupted = true; throw new Error("后台可能仍在核算，可重新连接进度或刷新历史批次查看结果。"); }
        s.progress = "进度连接暂时中断，正在重试…"; render(s);
        await new Promise(resolve => setTimeout(resolve, 1800)); continue;
      }
      if (!isCurrent(s, version)) return;
      validateSource(data, s);
      if (data.month && data.month !== s.month) throw new Error("返回批次的核算月份不匹配，请刷新历史批次重试。");
      if (data.createdAt && Number.isFinite(Date.parse(data.createdAt))) s.startedAt = Date.parse(data.createdAt);
      s.progress = data.progress || "正在读取核算批次…"; if (data.progressDetail) s.detail = data.progressDetail;
      if (data.status === "failed") throw new Error(data.progress || "本次核算失败，请重试。");
      if (data.status === "completed" || (!data.status && data.summary)) { complete(s, data); return; }
      render(s); await new Promise(resolve => setTimeout(resolve, 1500));
    }
  }
  async function followActivity(s, version) {
    while (isCurrent(s, version)) {
      const activity = await request(`/api/china-employee-payroll/activities/${s.activityId}`);
      if (!isCurrent(s, version)) return;
      if (activity.runId) { s.runId = activity.runId; await follow(s, s.runId, version); return; }
      if (activity.status === "failed") throw new Error(activity.progress || "本次核算未完成，请重试。");
      s.progress = activity.progress || "正在读取上传的考勤文件…"; render(s);
      await new Promise(resolve => setTimeout(resolve, 1500));
    }
  }
  async function start(s) {
    if (s.busy || !/^\d{4}-\d{2}$/.test(s.month)) return;
    if (s.source === "wx" && !s.files.length) return;
    const version = ++s.version, month = s.month; s.runId = "";
    begin(s, s.source === "hr" ? "正在连接北森，读取所选月份的核算人员与日考勤。" : "正在上传 WX 考勤文件并按餐补规则核算。");
    let creating = true;
    try {
      if (s.source === "hr") {
        const data = s.activityId ? await request(`/api/china-employee-payroll/activities/${s.activityId}/start`, { method: "POST" }) : await request(`${base}/beisen/runs`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ month }) });
        if (!isCurrent(s, version)) return;
        validateSource(data, s); s.runId = data.runId; creating = false; loadRuns(s);
        if (s.runId) await follow(s, s.runId, version);
        else await followActivity(s, version);
      } else {
        const form = new FormData(); s.files.forEach(file => form.append("attendance_files", file)); form.append("source_type", "wx"); form.append("month", month);
        const data = await request(s.activityId ? `/api/china-employee-payroll/activities/${s.activityId}/start` : base, { method: "POST", body: form }, 180000);
        if (isCurrent(s, version)) {
          if (s.activityId) { creating = false; s.runId = data.runId; if (s.runId) await follow(s, s.runId, version); else await followActivity(s, version); }
          else complete(s, data);
        }
      }
    } catch (error) {
      if (!isCurrent(s, version)) return;
      if (creating && ["TypeError", "TimeoutError"].includes(error.name)) { s.uncertain = true; error = new Error("开始请求尚未确认，后台可能已开始核算。请从活动列表重新打开此活动查看状态。"); }
      fail(s, error);
    } finally { if (isCurrent(s, version)) loadRuns(s); }
  }
  async function loadRun(id, reconnect = false) {
    const s = states[active]; if (s.busy) return;
    const run = s.runs.find(item => item.runId === id);
    if (run?.month) s.month = run.month;
    const version = ++s.version; s.runId = id;
    begin(s, reconnect ? "正在重新连接核算进度…" : "正在读取历史核算结果…");
    try {
      if (!run?.month && !reconnect) {
        const data = await request(`${base}/runs/${encodeURIComponent(id)}`); if (!isCurrent(s, version)) return;
        validateSource(data, s); s.month = data.month || data.summary?.dateStart?.slice(0, 7) || s.month;
        if (data.summary && data.status !== "running" && data.status !== "failed") { complete(s, data); return; }
      }
      await follow(s, id, version);
    } catch (error) { if (isCurrent(s, version)) fail(s, error); }
    finally { if (isCurrent(s, version)) loadRuns(s); }
  }
  async function exportResult() {
    const s = states[active]; if (!s.result || s.busy || s.exporting) return;
    const version = s.version, id = s.runId;
    s.exporting = true; s.exportState = "loading"; s.exportMessage = ""; renderExport(s);
    try {
      const response = await fetch(`${base}/${encodeURIComponent(id)}/export`, { signal: AbortSignal.timeout(120000) });
      if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(typeof data.detail === "string" ? data.detail : "导出失败，请重试。"); }
      const blob = await response.blob();
      if (!isCurrent(s, version) || s.runId !== id) return;
      const header = response.headers.get("content-disposition") || "", match = header.match(/filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i);
      let filename = `${monthLabel(s.month)}${titles[s.source]}.xlsx`; if (match) { try { filename = decodeURIComponent(match[1] || match[2]); } catch { /* Keep the source-specific fallback. */ } }
      const url = URL.createObjectURL(blob), link = document.createElement("a"); link.href = url; link.download = filename; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 60000);
      s.exportState = "success"; s.exportMessage = "Excel 已生成，已开始下载。";
      setTimeout(() => { if (isCurrent(s, version) && s.runId === id && s.exportState === "success") { s.exportState = "idle"; s.exportMessage = ""; if (states[active] === s) renderExport(s); } }, 2400);
    } catch (error) {
      if (isCurrent(s, version)) { s.exportState = "error"; s.exportMessage = error.name === "TimeoutError" ? "导出超时，请重试。" : error.message || "导出失败，请重试。"; }
    } finally { s.exporting = false; if (states[active] === s) renderExport(s); }
  }
  function selectSource(source, month) {
    const s = states[source]; active = source;
    if (!s.busy) {
      ++s.version; Object.assign(s, { month, status: "idle", result: null, runId: "", progress: "", detail: null, files: [], startedAt: 0, finishedAt: 0, exportState: "idle", exportMessage: "" });
      el("Files").value = "";
    }
    render(s); loadRuns(s); return s;
  }
  function syncView() {
    const view = location.hash.slice(1), meal = ["meal-allowance", "wx-meal-allowance"].includes(view), relocation = view === "relocation-allowance";
    const activities = view === "activities";
    document.getElementById("moduleHub").hidden = meal || relocation || activities;
    document.getElementById("payrollActivitiesView").hidden = !activities;
    document.getElementById("mealAllowanceWorkbench").hidden = !meal;
    document.getElementById("relocationWorkbench").hidden = !relocation;
    document.body.dataset.view = meal || relocation ? "workbench" : "hub";
    if (meal) { active = view === "wx-meal-allowance" ? "wx" : "hr"; render(states[active]); }
    else { clearInterval(clock); clock = null; window.MealAllowanceMotion?.stop(); }
  }
  window.MealAllowance = {
    canStart: () => true,
    openActivity(activity, autoStart = false) {
      const source = activity.subject === "wx-meal-allowance" ? "wx" : "hr";
      active = source;
      let s = activityStates.get(activity.activityId);
      if (!s) { s = createState(source); s.activityId = activity.activityId; activityStates.set(activity.activityId, s); }
      states[source] = s; s.activityName = activity.name; s.month = activity.month; el("Files").value = "";
      render(s);
      if (s.busy) return;
      if (activity.runId) loadRun(activity.runId);
      else if (activity.status === "running") {
        const version = ++s.version; begin(s, "正在重新连接活动进度…");
        followActivity(s, version).catch(error => { if (isCurrent(s, version)) fail(s, error); });
      }
      else if (autoStart && source === "hr") start(s);
      else { s.status = activity.status === "failed" ? "error" : "idle"; s.progress = activity.progress; render(s); }
    }
  };
  window.addEventListener("payroll-month-selected", event => {
    const { subject, month, autoStart } = event.detail;
    if (!["meal-allowance", "wx-meal-allowance"].includes(subject)) return;
    const source = subject === "wx-meal-allowance" ? "wx" : "hr";
    if (states[source].busy) return;
    const s = selectSource(source, month); if (autoStart && source === "hr") start(s);
  });
  el("Files").addEventListener("change", () => { const s = states[active]; if (s.source !== "wx" || s.busy) return; s.files = [...el("Files").files]; render(s); });
  el("ActivityStart").addEventListener("click", () => start(states[active]));
  el("UploadStart").addEventListener("click", () => start(states[active]));
  el("Retry").addEventListener("click", () => start(states[active]));
  el("Reconnect").addEventListener("click", () => loadRun(states[active].runId, true));
  el("Refresh").addEventListener("click", () => loadRuns());
  el("Runs").addEventListener("click", event => { const button = event.target.closest("[data-run-id]"); if (button && !button.disabled) loadRun(button.dataset.runId); });
  el("Search").addEventListener("input", () => { const s = states[active]; s.query = el("Search").value.trim(); s.page = 1; renderRows(s); });
  el("Status").addEventListener("change", () => { const s = states[active]; s.filter = el("Status").value; s.page = 1; renderRows(s); });
  el("PageSize").addEventListener("change", () => { const s = states[active]; s.pageSize = Number(el("PageSize").value); s.page = 1; renderRows(s); });
  el("Prev").addEventListener("click", () => { const s = states[active]; --s.page; renderRows(s); });
  el("Next").addEventListener("click", () => { const s = states[active]; ++s.page; renderRows(s); });
  el("Export").addEventListener("click", exportResult);
  window.addEventListener("hashchange", syncView); syncView();
})();
