let latestResult = null;
let currentPage = 1;
let filteredRows = [];
let activeSourceType = "";
const API_ORIGIN = window.location.protocol === "file:" ? "http://127.0.0.1:8006" : "";
const VERCEL_DIRECT_UPLOAD_WARNING_BYTES = 4 * 1024 * 1024;

const elements = {
  periodLabel: document.querySelector("#calcPeriodLabel"),
  rows: document.querySelector("#resultRows"),
  issues: document.querySelector("#issueList"),
  status: document.querySelector("#resultStatus"),
  employees: document.querySelector("#summaryEmployees"),
  amount: document.querySelector("#summaryAmount"),
  issueCount: document.querySelector("#summaryIssues"),
  toast: document.querySelector("#payrollToast"),
  run: document.querySelector("#btnRunCalc"),
  resetSource: document.querySelector("#btnResetSource"),
  export: document.querySelector("#btnExport"),
  runHint: document.querySelector("#runHint"),
  attendanceFiles: document.querySelector("#attendanceFiles"),
  attendanceFileName: document.querySelector("#attendanceFileName"),
  wxAttendanceFiles: document.querySelector("#wxAttendanceFiles"),
  wxAttendanceFileName: document.querySelector("#wxAttendanceFileName"),
  sourceCards: document.querySelectorAll("[data-source-card]"),
  moduleHub: document.querySelector("#moduleHub"),
  workbench: document.querySelector("#mealAllowanceWorkbench"),
  openMealAllowance: document.querySelector("#openMealAllowance"),
  dockCards: document.querySelectorAll("[data-dock-card]"),
  backToModuleHub: document.querySelector("#backToModuleHub"),
  workbenchActions: document.querySelectorAll(".workbench-action"),
  toggleSubnav: document.querySelector("#toggleSubnav"),
  refreshRuns: document.querySelector("#btnRefreshRuns"),
  batchList: document.querySelector("#batchList"),
  resultSearch: document.querySelector("#resultSearch"),
  resultStatusFilter: document.querySelector("#resultStatusFilter"),
  pageSize: document.querySelector("#pageSize"),
  pageInfo: document.querySelector("#resultPageInfo"),
  paginationList: document.querySelector("#paginationList"),
  resultTotal: document.querySelector("#resultTotal"),
  prevPage: document.querySelector("#prevPage"),
  nextPage: document.querySelector("#nextPage"),
};

function money(value) {
  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency: "CNY",
    maximumFractionDigits: 0,
  }).format(value || 0);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function downloadBlob(filename, blob) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function apiUrl(path) {
  return `${API_ORIGIN}${path}`;
}

function friendlyFetchError(error, fallback) {
  if (error instanceof TypeError && /fetch/i.test(error.message || "")) {
    return "无法连接核算服务，请通过 http://127.0.0.1:8006/china-employee-payroll.html 打开页面，并确认 8006 服务已启动。";
  }
  return error.message || fallback;
}

function isProductionHost() {
  return window.location.hostname.endsWith(".vercel.app");
}

async function parseJsonResponse(response, fallback) {
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || data.message || fallback);
    return data;
  }

  const rawText = await response.text().catch(() => "");
  const snippet = rawText.replace(/\s+/g, " ").trim().slice(0, 120);
  if (response.status === 413) {
    throw new Error("上传文件超过生产环境请求大小限制，请拆分考勤文件后重试。");
  }
  if ([500, 502, 503, 504].includes(response.status)) {
    throw new Error("生产环境核算服务超时或返回异常，请拆分考勤文件后重试；如仍失败，请联系管理员查看 Vercel 函数日志。");
  }
  throw new Error(snippet ? `${fallback}：${snippet}` : fallback);
}

function formatDateTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function getVisibleRows() {
  const rows = Array.isArray(latestResult?.results) ? latestResult.results : [];
  const query = elements.resultSearch.value.trim().toLowerCase();
  const status = elements.resultStatusFilter.value;
  return rows.filter((row) => {
    if (status === "payable" && !(row.amount > 0)) return false;
    if (status === "unmatched" && row.amount > 0) return false;
    if (!query) return true;
    return [
      row.employeeId,
      row.employeeName,
      row.status,
      row.secondOrg,
      row.thirdOrg,
      row.fourthOrg,
    ].some((value) => String(value ?? "").toLowerCase().includes(query));
  });
}

function paginationRange(current, total) {
  if (total <= 7) return Array.from({ length: total }, (_, index) => index + 1);
  const pages = new Set([1, total, current, current - 1, current + 1]);
  if (current <= 3) {
    pages.add(2);
    pages.add(3);
    pages.add(4);
  }
  if (current >= total - 2) {
    pages.add(total - 1);
    pages.add(total - 2);
    pages.add(total - 3);
  }
  const sorted = [...pages].filter((page) => page >= 1 && page <= total).sort((a, b) => a - b);
  const range = [];
  sorted.forEach((page, index) => {
    if (index > 0 && page - sorted[index - 1] > 1) range.push("ellipsis");
    range.push(page);
  });
  return range;
}

function renderPagination(totalPages) {
  const items = paginationRange(currentPage, totalPages).map((page, index) => {
    if (page === "ellipsis") {
      return `
        <li>
          <span class="pagination-ellipsis" aria-hidden="true">
            <svg viewBox="0 0 20 20"><circle cx="5" cy="10" r="1.5" /><circle cx="10" cy="10" r="1.5" /><circle cx="15" cy="10" r="1.5" /></svg>
            <span class="sr-only">更多页码</span>
          </span>
        </li>
      `;
    }
    const isActive = page === currentPage;
    return `
      <li>
        <button class="pagination-link pagination-page${isActive ? " active-page" : ""}" type="button" data-page="${page}" ${isActive ? 'aria-current="page"' : ""}>
          ${page}
        </button>
      </li>
    `;
  }).join("");

  elements.paginationList.innerHTML = `
    <li>
      <button class="pagination-link pagination-prev" id="prevPage" type="button" aria-label="上一页" ${currentPage <= 1 ? "disabled" : ""}>
        <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M12.5 15 7.5 10l5-5" /></svg>
        <span>Previous</span>
      </button>
    </li>
    ${items}
    <li>
      <button class="pagination-link pagination-next" id="nextPage" type="button" aria-label="下一页" ${currentPage >= totalPages ? "disabled" : ""}>
        <span>Next</span>
        <svg viewBox="0 0 20 20" aria-hidden="true"><path d="m7.5 5 5 5-5 5" /></svg>
      </button>
    </li>
  `;
  elements.prevPage = document.querySelector("#prevPage");
  elements.nextPage = document.querySelector("#nextPage");
  elements.pageInfo = elements.paginationList.querySelector(".active-page");
}

function renderTablePage() {
  filteredRows = getVisibleRows();
  const pageSize = Number(elements.pageSize.value || 50);
  const totalPages = Math.max(1, Math.ceil(filteredRows.length / pageSize));
  currentPage = Math.min(Math.max(currentPage, 1), totalPages);
  const start = (currentPage - 1) * pageSize;
  const pageRows = filteredRows.slice(start, start + pageSize);

  elements.rows.innerHTML = pageRows.length ? pageRows.map((row) => `
    <tr>
      <td>${escapeHtml(row.employeeId)}</td>
      <td>${escapeHtml(row.employeeName)}</td>
      <td>${escapeHtml(row.secondOrg)}</td>
      <td>${escapeHtml(row.thirdOrg)}</td>
      <td>${escapeHtml(row.payableDays)}</td>
      <td><strong>${money(row.amount)}</strong></td>
      <td><span class="status-badge ${row.amount > 0 ? "success" : "muted"}">${row.amount > 0 ? "已计算" : "未命中"}</span></td>
    </tr>
  `).join("") : '<tr><td colspan="7" class="empty-table-cell">没有符合筛选条件的记录</td></tr>';

  const rangeStart = filteredRows.length ? start + 1 : 0;
  const rangeEnd = Math.min(start + pageSize, filteredRows.length);
  elements.resultTotal.textContent = `共${filteredRows.length}条数据${filteredRows.length ? ` · ${rangeStart}-${rangeEnd}` : ""}`;
  renderPagination(totalPages);
}

function resetTablePage() {
  currentPage = 1;
  renderTablePage();
}

function markActiveRun() {
  elements.batchList.querySelectorAll("[data-run-id]").forEach((item) => {
    item.classList.toggle("active", item.dataset.runId === latestResult?.runId);
  });
}

function getSourceInput(sourceType) {
  return sourceType === "wx" ? elements.wxAttendanceFiles : elements.attendanceFiles;
}

function getSelectedFiles() {
  if (!activeSourceType) return [];
  return Array.from(getSourceInput(activeSourceType)?.files || []);
}

function sourceLabel(sourceType) {
  return sourceType === "wx" ? "WX技术部考勤" : "集团技术部考勤";
}

function updateSourceCards() {
  elements.sourceCards.forEach((card) => {
    const cardSource = card.dataset.sourceCard;
    const locked = Boolean(activeSourceType && activeSourceType !== cardSource);
    card.classList.toggle("active-source", activeSourceType === cardSource);
    card.classList.toggle("locked-source", locked);
    const input = card.querySelector("input");
    if (input) input.disabled = locked;
  });
}

function setRunAvailability() {
  const files = getSelectedFiles();
  const hasFiles = Boolean(files.length);
  elements.run.disabled = !hasFiles;
  elements.resetSource.disabled = !(activeSourceType || latestResult?.runId);
  elements.runHint.textContent = hasFiles
    ? `${sourceLabel(activeSourceType)}已就绪，可开始核算`
    : "选择左侧来源后开始核算";
  updateSourceCards();
}

function setButtonBusy(button, busyText) {
  const previousHtml = button.innerHTML;
  button.dataset.previousHtml = previousHtml;
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  button.innerHTML = `<span class="button-spinner" aria-hidden="true"></span>${escapeHtml(busyText)}`;
}

function restoreButton(button, disabled = false) {
  if (button.dataset.previousHtml) {
    button.innerHTML = button.dataset.previousHtml;
    delete button.dataset.previousHtml;
  }
  button.disabled = disabled;
  button.removeAttribute("aria-busy");
}

async function exportCurrentResult() {
  if (!latestResult?.runId) {
    toast("请先完成餐补核算。");
    return;
  }

  setButtonBusy(elements.export, "正在生成Excel...");
  toast("正在生成导出文件，源数据较多时需要等待几十秒。");
  const previousStatus = elements.status.textContent;
  elements.status.textContent = "正在生成导出文件，请稍候...";
  try {
    const response = await fetch(apiUrl(`/api/china-employee-payroll/meal-allowance/${encodeURIComponent(latestResult.runId)}/export`));
    if (!response.ok) {
      await parseJsonResponse(response, "导出结果失败");
    }
    const disposition = response.headers.get("content-disposition") || "";
    const match = disposition.match(/filename\*=UTF-8''([^;]+)|filename=\"?([^\";]+)\"?/i);
    const filename = match ? decodeURIComponent(match[1] || match[2]) : "技术部餐补核算结果.xlsx";
    downloadBlob(filename, await response.blob());
    toast("导出结果已生成。");
  } catch (error) {
    toast(friendlyFetchError(error, "导出结果失败。"));
  } finally {
    restoreButton(elements.export);
    elements.status.textContent = previousStatus;
  }
}

function renderResult(data) {
  latestResult = data;
  const summary = data?.summary || {};
  const rows = Array.isArray(data?.results) ? data.results : [];
  const missingColumnCount = data?.warnings?.missingColumns?.length || 0;
  const duplicateCount = summary.duplicateCount || 0;
  const dataIssueCount = missingColumnCount + duplicateCount;

  elements.periodLabel.textContent = summary.dateStart && summary.dateEnd
    ? `${summary.dateStart} 至 ${summary.dateEnd}${summary.sourceLabel ? ` · ${summary.sourceLabel}` : ""}`
    : "待上传考勤记录";
  elements.employees.textContent = summary.payableEmployeeCount ?? 0;
  elements.amount.textContent = money(summary.totalAmount || 0);
  elements.issueCount.textContent = dataIssueCount;
  elements.export.disabled = !data?.runId;
  elements.status.textContent = rows.length
    ? `已核算 ${summary.rowCount || 0} 行考勤，${summary.payableDayCount || 0} 个补贴日`
    : "等待上传并核算";

  resetTablePage();

  const warnings = [
    ...(data?.warnings?.missingColumns?.length ? [`缺少必要字段：${data.warnings.missingColumns.join("、")}`] : []),
    ...(data?.warnings?.duplicateKeys?.length ? [`发现 ${data.summary.duplicateCount} 条重复工号+考勤日期，请复核是否重复上传或系统导出重复`] : []),
  ];
  elements.issues.innerHTML = warnings.length
    ? warnings.map((message) => `<article class="issue-item"><strong>待复核</strong><span>${escapeHtml(message)}</span></article>`).join("")
    : '<article class="issue-item clear"><strong>暂无异常</strong><span>当前上传文件未发现缺必要字段或重复工号+考勤日期。</span></article>';
}

function renderEmpty() {
  renderResult({ summary: {}, results: [], warnings: {} });
}

function toast(message) {
  elements.toast.textContent = message;
  elements.toast.classList.add("show");
  window.setTimeout(() => elements.toast.classList.remove("show"), 2200);
}

async function loadRuns() {
  elements.batchList.innerHTML = '<article class="batch-item muted">正在加载历史批次...</article>';
  try {
    const response = await fetch(apiUrl("/api/china-employee-payroll/meal-allowance/runs"));
    const data = await parseJsonResponse(response, "批次加载失败");
    const runs = Array.isArray(data.runs) ? data.runs : [];
    elements.batchList.innerHTML = runs.length ? runs.slice(0, 8).map((run) => `
      <button class="batch-item ${latestResult?.runId === run.runId ? "active" : ""}" data-run-id="${escapeHtml(run.runId)}" type="button">
        <strong>${escapeHtml(run.monthLabel || "技术部餐补")}</strong>
        <span>${escapeHtml(run.period || "待确认周期")} · ${escapeHtml(run.sourceLabel || sourceLabel(run.sourceType))}</span>
        <small>${escapeHtml(formatDateTime(run.createdAt))} · ${escapeHtml(run.payableEmployeeCount)} 人 · ${escapeHtml(money(run.totalAmount))}</small>
      </button>
    `).join("") : '<article class="batch-item muted">暂无历史核算批次</article>';
    markActiveRun();
  } catch (error) {
    elements.batchList.innerHTML = `<article class="batch-item muted">批次加载失败：${escapeHtml(friendlyFetchError(error, "未知错误"))}</article>`;
  }
}

async function loadRun(runId) {
  elements.status.textContent = "正在加载历史批次...";
  try {
    const response = await fetch(apiUrl(`/api/china-employee-payroll/meal-allowance/runs/${encodeURIComponent(runId)}`));
    const data = await parseJsonResponse(response, "批次加载失败");
    renderResult(data);
    markActiveRun();
    await loadRuns();
    toast("已加载历史核算批次。");
  } catch (error) {
    const message = friendlyFetchError(error, "批次加载失败。");
    elements.status.textContent = message;
    toast(message);
  }
}

function clearSourceInput(sourceType) {
  const input = getSourceInput(sourceType);
  if (input) {
    input.disabled = false;
    input.value = "";
  }
  if (sourceType === "wx") {
    elements.wxAttendanceFileName.textContent = "选择文件";
  } else {
    elements.attendanceFileName.textContent = "选择文件";
  }
}

function resetCurrentSourceSelection() {
  clearSourceInput("hr");
  clearSourceInput("wx");
  activeSourceType = "";
  renderEmpty();
  markActiveRun();
  setRunAvailability();
  toast("已清空当前来源，可选择集团技术部或 WX 技术部重新上传。");
}

function bindFileInput(input, label, sourceType) {
  input.addEventListener("change", () => {
    const files = Array.from(input.files || []);
    if (files.length) {
      activeSourceType = sourceType;
      clearSourceInput(sourceType === "wx" ? "hr" : "wx");
    } else if (activeSourceType === sourceType) {
      activeSourceType = "";
    }
    label.textContent = files.length ? `${files.length} 个文件已选择` : "选择文件";
    setRunAvailability();
    toast(files.length ? `已选择${sourceLabel(sourceType)}，点击开始核算。` : "请选择考勤记录。");
  });
}

function setView(view) {
  const isWorkbench = view === "meal-allowance";
  elements.moduleHub.hidden = isWorkbench;
  elements.workbench.hidden = !isWorkbench;
  elements.workbenchActions.forEach((node) => {
    node.hidden = !isWorkbench;
  });

  if (isWorkbench) {
    document.body.dataset.view = "workbench";
    if (!latestResult) renderEmpty();
    loadRuns();
    return;
  }

  document.body.dataset.view = "hub";
}

function syncViewFromHash() {
  setView(window.location.hash === "#meal-allowance" ? "meal-allowance" : "hub");
}

function bindDockCardMotion(card) {
  card.addEventListener("pointermove", (event) => {
    const rect = card.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width - 0.5).toFixed(3);
    const y = ((event.clientY - rect.top) / rect.height - 0.5).toFixed(3);
    card.style.setProperty("--dock-x", x);
    card.style.setProperty("--dock-y", y);
  });

  card.addEventListener("pointerleave", () => {
    card.style.setProperty("--dock-x", "0");
    card.style.setProperty("--dock-y", "0");
  });
}

elements.openMealAllowance.addEventListener("click", () => {
  window.location.hash = "meal-allowance";
  setView("meal-allowance");
});

elements.backToModuleHub.addEventListener("click", () => {
  history.pushState("", document.title, window.location.pathname + window.location.search);
  setView("hub");
});

elements.toggleSubnav.addEventListener("click", () => {
  const collapsed = elements.workbench.classList.toggle("nav-collapsed");
  elements.toggleSubnav.setAttribute("aria-expanded", String(!collapsed));
  elements.toggleSubnav.setAttribute("aria-label", collapsed ? "展开子功能导航" : "收起子功能导航");
});

elements.refreshRuns.addEventListener("click", loadRuns);
elements.batchList.addEventListener("click", (event) => {
  const item = event.target.closest("[data-run-id]");
  if (item) loadRun(item.dataset.runId);
});

elements.resultSearch.addEventListener("input", resetTablePage);
elements.resultStatusFilter.addEventListener("change", resetTablePage);
elements.pageSize.addEventListener("change", resetTablePage);
elements.paginationList.addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button || button.disabled) return;
  if (button.dataset.page) {
    currentPage = Number(button.dataset.page);
  } else if (button.id === "prevPage") {
    currentPage -= 1;
  } else if (button.id === "nextPage") {
    currentPage += 1;
  } else {
    return;
  }
  renderTablePage();
});

elements.run.addEventListener("click", async () => {
  const files = getSelectedFiles();
  if (!files.length) {
    toast("请先上传考勤记录 Excel。");
    return;
  }
  const form = new FormData();
  files.forEach((file) => form.append("attendance_files", file));
  form.append("source_type", activeSourceType);
  const totalUploadSize = files.reduce((sum, file) => sum + file.size, 0);
  if (isProductionHost() && totalUploadSize > VERCEL_DIRECT_UPLOAD_WARNING_BYTES) {
    toast("生产环境文件较大，若核算超时请拆分考勤文件后重试。");
  }
  setButtonBusy(elements.run, "正在核算...");
  elements.runHint.textContent = `正在解析${sourceLabel(activeSourceType)}并生成核算结果`;
  elements.status.textContent = "正在解析考勤记录并核算...";
  try {
    const response = await fetch(apiUrl("/api/china-employee-payroll/meal-allowance"), {
      method: "POST",
      body: form,
    });
    const data = await parseJsonResponse(response, "餐补核算失败");
    renderResult(data);
    await loadRuns();
    toast("餐补核算完成。");
  } catch (error) {
    const message = friendlyFetchError(error, "餐补核算失败。");
    elements.status.textContent = message;
    elements.issues.innerHTML = `<article class="issue-item"><strong>核算失败</strong><span>${escapeHtml(message)}</span></article>`;
    toast(message);
  } finally {
    restoreButton(elements.run, !getSelectedFiles().length);
    setRunAvailability();
  }
});

elements.export.addEventListener("click", () => {
  exportCurrentResult();
});

elements.resetSource.addEventListener("click", resetCurrentSourceSelection);

bindFileInput(elements.attendanceFiles, elements.attendanceFileName, "hr");
bindFileInput(elements.wxAttendanceFiles, elements.wxAttendanceFileName, "wx");
elements.dockCards.forEach(bindDockCardMotion);
setRunAvailability();
window.addEventListener("hashchange", syncViewFromHash);
syncViewFromHash();
