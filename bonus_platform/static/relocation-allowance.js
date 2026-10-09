(() => {
  "use strict";
  const api = "/api/china-employee-payroll/relocation-allowance/runs";
  const el = (name) => document.getElementById(`relocation${name}`);
  let activityId = "";
  let result = null, runId = "", busy = false, generation = 0, page = 1;
  let exporting = false, exportReset = null;
  const pageSize = 25;
  const currentMonth = new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit" }).format(new Date());
  const previous = new Date(`${currentMonth}-01T00:00:00Z`);
  previous.setUTCMonth(previous.getUTCMonth() - 1);
  el("Month").max = "2099-12";
  el("Month").value = previous.toISOString().slice(0, 7);
  const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const number = (value) => value == null ? "—" : Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 3 });
  const money = (value) => Number(value).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  function availability() {
    el("Start").disabled = busy;
    el("Month").disabled = busy;
    el("Export").disabled = busy || !result || exporting;
    el("Start").textContent = el("Processing").dataset.state === "idle" ? "开始核算" : "重新核算";
    el("Start").hidden = el("Processing").dataset.state !== "error" && !(activityId && el("Processing").dataset.state === "idle");
    el("Export").hidden = !result;
    el("ChooseMonth").hidden = !!activityId || el("Processing").dataset.state !== "idle";
    const month = el("Month").value;
    el("MonthLabel").textContent = `${month.slice(0, 4)}年${Number(month.slice(5))}月`;
    el("Result").setAttribute("aria-busy", String(busy));
    window.PayrollMonthPicker?.sync(el("Month"));
  }
  let clock = null, startedAt = 0;
  function tick() {
    const seconds = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
    el("Elapsed").textContent = `已用时 ${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
  }
  function stopClock() { clearInterval(clock); clock = null; }
  function setProgress(message, detail) {
    el("Progress").textContent = message;
    if (el("Processing").dataset.state !== "running") return;
    const stage = Number.isInteger(detail?.stage) ? detail.stage : /生成|按规则|核算补贴/.test(message) ? 3 : /组织/.test(message) ? 2 : /任职|员工/.test(message) ? 1 : /月报|考勤|准备/.test(message) ? 0 : null;
    if (stage === null || stage < 0 || stage > 3) return;
    const legacy = message.match(/(\d+)\s*\/\s*(\d+)/);
    const completed = detail ? detail.completed : legacy ? Number(legacy[1]) : null;
    const total = detail ? detail.total : legacy ? Number(legacy[2]) : null;
    const displayStage = Math.min(stage, 2);
    const finishing = stage >= 2;
    el("Processing").dataset.finishing = String(finishing);
    el("FinishingStatus").hidden = !finishing;
    el("FinishingLabel").textContent = stage === 3 ? "正在整理核算结果" : "正在核对当月组织与补贴规则";
    const known = !finishing && Number.isFinite(completed) && Number.isFinite(total) && total > 0;
    const fraction = known ? Math.min(1, Math.max(0, completed / total)) : null;
    const percentage = known ? `${(fraction * 100).toFixed(1).replace(/\.0$/, "")}%` : "—";
    const titles = ["正在读取考勤", "正在匹配员工任职", "正在核对当月组织", "正在生成核算明细"];
    el("ProcessingTitle").textContent = finishing ? "正在核对并生成结果" : titles[stage];
    el("StageIndex").textContent = `步骤 0${displayStage + 1} / 03`;
    el("Percent").textContent = percentage;
    el("Count").textContent = known ? `已处理 ${number(completed)} / ${number(total)} ${detail?.unit || ["条", "人", "个组织", "条"][stage]}` : "等待接口返回数据与总量";
    if (known) el("Meter").setAttribute("aria-valuenow", String(fraction * 100));
    else el("Meter").removeAttribute("aria-valuenow");
    document.querySelectorAll(".relocation-steps li").forEach((step, index) => {
      step.dataset.state = index < displayStage ? "done" : index === displayStage ? "active" : "pending";
      step.querySelector("b").textContent = index < displayStage ? "✓" : `0${index + 1}`;
      step.querySelector("small").textContent = index < displayStage ? "已完成" : index === displayStage ? known ? percentage : "处理中" : "待开始";
      if (index === displayStage) step.setAttribute("aria-current", "step"); else step.removeAttribute("aria-current");
    });
    window.RelocationMotion?.update(stage, fraction);
  }
  function startProcessing(message) {
    el("Processing").dataset.state = "running";
    el("ProcessingKicker").textContent = "正在核算";
    stopClock(); startedAt = Date.now(); tick(); clock = setInterval(tick, 1000);
    window.RelocationMotion?.start(); setProgress(message, {stage: 0, completed: 0, total: null}); availability();
  }
  function failProcessing(message) {
    stopClock();
    el("Processing").dataset.state = "error";
    el("ProcessingKicker").textContent = "核算未完成";
    el("ProcessingTitle").textContent = "本次未生成核算结果";
    document.querySelector('.relocation-steps [data-state="active"] small')?.replaceChildren("已中断");
    setProgress(message); window.RelocationMotion?.error();
  }
  function clear() {
    result = null; runId = ""; page = 1;
    el("Result").hidden = true;
    el("Processing").hidden = false;
    el("Search").value = ""; el("Status").value = "";
    availability();
  }
  async function request(url, options = {}) {
    const response = await fetch(url, { ...options, signal: AbortSignal.timeout(30000) });
    let data;
    try { data = await response.json(); } catch { throw new Error("核算服务返回异常，请稍后重试。"); }
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "核算服务暂时不可用。");
    return data;
  }
  function renderRows() {
    if (!result) return;
    const query = el("Search").value.trim().toLowerCase(), status = el("Status").value;
    const rows = result.results.filter((r) => (!query || `${r.employeeId} ${r.employeeName}`.toLowerCase().includes(query)) && (!status || r.status === status));
    const pages = Math.max(1, Math.ceil(rows.length / pageSize));
    page = Math.min(page, pages);
    el("Rows").innerHTML = rows.slice((page - 1) * pageSize, page * pageSize).map((r) => `<tr>
      <td>${escape(r.employeeId)}</td><td>${escape(r.employeeName)}</td><td>${escape(r.thirdOrg)}${r.fourthOrg ? `<small>${escape(r.fourthOrg)}</small>` : ""}</td><td>${escape(r.grade)}</td>
      ${["targetDays", "sickDays", "casualDays", "absentDays", "maternityDays", "normalDays"].map((key) => `<td>${number(r[key])}</td>`).join("")}
      <td class="relocation-amount">${r.amount == null ? "待补全数据" : money(r.amount)}</td><td><span class="relocation-state ${r.status === "待确认" ? "review" : ""}">${escape(r.status)}</span>${r.reason ? `<small>${escape(r.reason)}</small>` : ""}</td></tr>`).join("") || '<tr><td colspan="12">没有符合筛选条件的记录。</td></tr>';
    el("PageInfo").textContent = `共 ${rows.length} 人 · 第 ${page} / ${pages} 页`;
    el("Prev").disabled = page <= 1; el("Next").disabled = page >= pages;
  }
  function show(data) {
    result = data.result; runId = data.runId; page = 1;
    el("Month").value = data.month;
    el("Result").hidden = false;
    const s = result.summary;
    el("Summary").innerHTML = [["试算补贴总额", `¥ ${money(s.amount)}`], ["候选员工", `${s.employeeCount} 人`], ["有补贴员工", `${s.payableCount} 人`], ["待确认员工", `${s.reviewCount} 人`]].map(([label, value]) => `<div><span>${label}</span><strong>${value}</strong></div>`).join("");
    const warnings = [...result.warnings];
    if (s.reviewCount) warnings.push(`有 ${s.reviewCount} 名员工需要核对组织历史或数据完整性；相关金额已计入试算总额。`);
    if (s.missingScopeCount) warnings.push(`有 ${s.missingScopeCount} 条月报无法判断适用范围，未计入候选名单。`);
    el("Warnings").innerHTML = warnings.map((w) => `<li>${escape(w)}</li>`).join("");
    el("ResultMonth").textContent = `${data.month} · 规则 ${result.ruleVersion}`;
    stopClock();
    el("Processing").dataset.state = "completed";
    setProgress(`${data.month} 核算完成 · 已读取 ${s.sourceCount} 条北森月报 · ${data.createdAt.slice(0, 16).replace("T", " ")}`);
    el("ReviewCount").textContent = s.reviewCount || s.missingScopeCount ? "有待核对项" : "";
    el("Review").open = Boolean(s.reviewCount || s.missingScopeCount);
    renderRows(); availability(); window.RelocationMotion?.complete();
  }
  async function loadRuns() {
    if (activityId) { window.dispatchEvent(new Event("payroll-activities-updated")); return; }
    try {
      const data = await request(api);
      el("Runs").innerHTML = data.runs.map((r) => `<button type="button" class="relocation-run" data-id="${escape(r.runId)}" ${busy ? "disabled" : ""}><strong>${escape(r.month)}</strong><span>${({running:"核算中", completed:"已试算", failed:"核算失败"})[r.status] || "未知状态"}</span><small>${escape(r.createdAt.slice(0, 16).replace("T", " "))}</small></button>`).join("") || "<p>暂无核算批次。</p>";
    } catch { el("Runs").textContent = "历史批次读取失败，可点击刷新重试。"; }
  }
  async function follow(id, version) {
    let failures = 0;
    while (version === generation) {
      let data;
      try { data = await request(`${api}/${id}`); failures = 0; }
      catch (error) {
        if (version !== generation) return;
        if (++failures >= 3) throw new Error("进度连接中断；后台可能仍在核算，请刷新历史批次查看结果。");
        setProgress("进度连接暂时中断，正在重试…");
        await new Promise((resolve) => setTimeout(resolve, 2000)); continue;
      }
      if (version !== generation) return;
      el("Month").value = data.month; availability();
      const serverStart = Date.parse(data.createdAt);
      if (Number.isFinite(serverStart)) { startedAt = serverStart; tick(); }
      setProgress(`${data.month} · ${data.progress}`, data.progressDetail);
      if (data.status === "failed") throw new Error(data.progress);
      if (data.status === "completed") { busy = false; show(data); return; }
      await new Promise((resolve) => setTimeout(resolve, 1500));
    }
  }
  async function loadRun(id) {
    if (busy) return;
    const version = ++generation;
    busy = true; clear(); availability();
    startProcessing("正在读取核算批次…");
    try { await follow(id, version); }
    catch (error) { if (version === generation) failProcessing(error.message); }
    finally { if (version === generation) { busy = false; availability(); loadRuns(); } }
  }
  async function followActivity(id, version) {
    while (version === generation) {
      const activity = await request(`/api/china-employee-payroll/activities/${id}`);
      if (version !== generation) return;
      if (activity.runId) { await follow(activity.runId, version); return; }
      if (activity.status === "failed") throw new Error(activity.progress || "本次核算未完成，请重试。");
      await new Promise(resolve => setTimeout(resolve, 1500));
    }
  }
  window.addEventListener("payroll-month-selected", (event) => {
    if (event.detail.subject !== "relocation-allowance" || busy) return;
    if (event.detail.month !== el("Month").value) {
      ++generation; clear(); el("Month").value = event.detail.month;
      window.PayrollMonthPicker?.sync(el("Month"));
      el("Progress").textContent = `${event.detail.month} · 点击开始核算，自动读取北森考勤。`;
    }
    if (event.detail.autoStart) el("Form").requestSubmit();
  });
  el("Form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy || !el("Month").checkValidity()) return;
    const month = el("Month").value, version = ++generation;
    busy = true; clear(); availability(); loadRuns();
    startProcessing(`${month} · 正在准备读取北森数据…`);
    try {
      const data = activityId ? await request(`/api/china-employee-payroll/activities/${activityId}/start`, { method: "POST" }) : await request(api, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ month }) });
      if (version !== generation) return;
      runId = data.runId;
      if (runId) await follow(runId, version); else await followActivity(activityId, version);
    } catch (error) { if (version === generation) failProcessing(error.message || "读取失败，请检查网络后重试。"); }
    finally { if (version === generation) { busy = false; availability(); loadRuns(); } }
  });
  el("Month").addEventListener("change", () => { if (!busy) { ++generation; clear(); el("Progress").textContent = "月份已切换，请开始核算。"; } });
  el("Export").addEventListener("click", async () => {
    if (!result || busy || exporting) return;
    const button = el("Export"), id = runId, version = generation;
    clearTimeout(exportReset); exporting = true;
    button.dataset.state = "loading"; button.textContent = "正在生成 Excel…";
    button.setAttribute("aria-busy", "true");
    el("ExportStatus").textContent = ""; availability();
    try {
      const response = await fetch(`${api}/${id}/export`, { signal: AbortSignal.timeout(60000) });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(typeof data.detail === "string" ? data.detail : "导出失败，请重试。");
      }
      const { blob, filename: storedFilename } = await window.PayrollFiles.download(response);
      if (version !== generation) return;
      const disposition = response.headers.get("Content-Disposition") || "";
      const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i);
      let filename = "职场搬迁补贴.xlsx";
      if (encoded) { try { filename = decodeURIComponent(encoded[1]); } catch { /* Use the fallback filename. */ } }
      if (storedFilename) filename = storedFilename;
      const url = URL.createObjectURL(blob), link = document.createElement("a");
      link.href = url; link.download = filename; document.body.append(link);
      link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 60000);
      button.dataset.state = "success"; button.textContent = "已开始下载";
      el("ExportStatus").textContent = "Excel 已生成，已开始下载。";
    } catch (error) {
      if (version !== generation) return;
      button.dataset.state = "error"; button.textContent = "重试导出";
      el("ExportStatus").textContent = error.name === "TimeoutError" ? "导出超时，请重试。" : error.message || "导出失败，请重试。";
    } finally {
      if (version !== generation) return;
      exporting = false; button.removeAttribute("aria-busy"); availability();
      if (button.dataset.state === "success") exportReset = setTimeout(() => {
        button.dataset.state = "idle"; button.textContent = "导出明细";
      }, 2200);
    }
  });
  window.RelocationAllowance = {
    openActivity(activity, autoStart = false) {
      ++generation; busy = false; stopClock(); activityId = activity.activityId;
      clearTimeout(exportReset); exporting = false;
      el("Export").dataset.state = "idle"; el("Export").textContent = "导出明细"; el("Export").removeAttribute("aria-busy"); el("ExportStatus").textContent = "";
      el("Processing").dataset.state = "idle"; clear(); el("Month").value = activity.month;
      document.getElementById("relocationActivityName").textContent = activity.name;
      el("ProcessingKicker").textContent = "准备就绪"; el("ProcessingTitle").textContent = "活动已保存，随时开始核算";
      setProgress("确认开始后，将自动读取此活动月份的北森考勤。"); availability();
      if (activity.runId) loadRun(activity.runId);
      else if (activity.status === "running") {
        const version = ++generation; busy = true; startProcessing("正在重新连接活动进度…");
        followActivity(activity.activityId, version).catch(error => { if (version === generation) failProcessing(error.message); })
          .finally(() => { if (version === generation) { busy = false; availability(); loadRuns(); } });
      }
      else if (autoStart) el("Form").requestSubmit();
      else if (activity.status === "failed") { failProcessing(activity.progress); availability(); }
    }
  };
  el("Refresh").addEventListener("click", loadRuns);
  el("Runs").addEventListener("click", (event) => { const button = event.target.closest("[data-id]"); if (button) loadRun(button.dataset.id); });
  ["Search", "Status"].forEach((name) => el(name).addEventListener(name === "Search" ? "input" : "change", () => { page = 1; renderRows(); }));
  el("Prev").addEventListener("click", () => { page--; renderRows(); });
  el("Next").addEventListener("click", () => { page++; renderRows(); });
  window.addEventListener("hashchange", () => { if (window.location.hash === "#relocation-allowance" && !activityId) loadRuns(); });
  if (window.location.hash === "#relocation-allowance" && !activityId) loadRuns();
  availability();
})();
