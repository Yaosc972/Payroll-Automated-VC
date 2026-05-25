const state = {
  currentRun: null,
  runs: [],
  table: null,
  tableRows: [],
  filteredRows: [],
  filters: {},
  optionalColumnsHidden: false,
  runsCollapsed: false,
  filtersCollapsed: false,
  sortField: "",
  sortDir: "asc",
  currentPage: 1,
  pageSize: 30,
};

const elements = {
  fileInput: document.querySelector("#fileInput"),
  fileName: document.querySelector("#fileName"),
  calculateButton: document.querySelector("#calculateButton"),
  status: document.querySelector("#status"),
  confirmationInput: document.querySelector("#confirmationInput"),
  confirmationName: document.querySelector("#confirmationName"),
  finalizeButton: document.querySelector("#finalizeButton"),
  finalStatus: document.querySelector("#finalStatus"),
  offlineInput: document.querySelector("#offlineInput"),
  offlineName: document.querySelector("#offlineName"),
  compareButton: document.querySelector("#compareButton"),
  compareStatus: document.querySelector("#compareStatus"),
  runList: document.querySelector("#runList"),
  refreshRunsButton: document.querySelector("#refreshRunsButton"),
  toggleRunsButton: document.querySelector("#toggleRunsButton"),
  downloadLink: document.querySelector("#downloadLink"),
  pendingDownloadLink: document.querySelector("#pendingDownloadLink"),
  downloadGrid: document.querySelector("#downloadGrid"),
  currentRunTitle: document.querySelector("#currentRunTitle"),
  currentRunSubTitle: document.querySelector("#currentRunSubTitle"),
  ruleVersion: document.querySelector("#ruleVersion"),
  diffSummary: document.querySelector("#diffSummary"),
  tableSummary: document.querySelector("#tableSummary"),
  visibleRows: document.querySelector("#visibleRows"),
  totalRows: document.querySelector("#totalRows"),
  globalSearch: document.querySelector("#globalSearch"),
  bonusTypeFilter: document.querySelector("#bonusTypeFilter"),
  statusFilter: document.querySelector("#statusFilter"),
  ruleScopeFilter: document.querySelector("#ruleScopeFilter"),
  ownerFilter: document.querySelector("#ownerFilter"),
  minAmountFilter: document.querySelector("#minAmountFilter"),
  maxAmountFilter: document.querySelector("#maxAmountFilter"),
  columnToggleButton: document.querySelector("#columnToggleButton"),
  toggleFiltersButton: document.querySelector("#toggleFiltersButton"),
  detailDrawer: document.querySelector("#detailDrawer"),
  drawerClose: document.querySelector("#drawerClose"),
  drawerTitle: document.querySelector("#drawerTitle"),
  drawerSubtitle: document.querySelector("#drawerSubtitle"),
  drawerContent: document.querySelector("#drawerContent"),
  toastRegion: document.querySelector("#toastRegion"),
};

const metricIds = ["month", "importedRows", "recruitmentTotal", "referralTotal", "pendingCount", "exceptionCount"];
const optionalColumnFields = ["grade", "category", "channel", "ownerName", "sourceRow"];

init();

function init() {
  bindEvents();
  renderIcons();
  loadRuns();
}

function bindEvents() {
  elements.fileInput.addEventListener("change", () => {
    elements.fileName.textContent = elements.fileInput.files[0]?.name || "选择本月 Excel 文件";
  });

  elements.confirmationInput.addEventListener("change", () => {
    elements.confirmationName.textContent = elements.confirmationInput.files[0]?.name || "上传已确认表";
  });

  elements.offlineInput.addEventListener("change", () => {
    elements.offlineName.textContent = elements.offlineInput.files[0]?.name || "选择线下/复核 Excel";
  });

  elements.calculateButton.addEventListener("click", calculateRun);
  elements.finalizeButton.addEventListener("click", finalizeRun);
  elements.compareButton.addEventListener("click", compareRun);
  elements.refreshRunsButton.addEventListener("click", loadRuns);
  elements.toggleRunsButton.addEventListener("click", toggleRunsPanel);
  elements.toggleFiltersButton.addEventListener("click", toggleFiltersPanel);
  elements.drawerClose.addEventListener("click", closeDrawer);
  elements.detailDrawer.addEventListener("click", (event) => {
    if (event.target === elements.detailDrawer) closeDrawer();
  });
  elements.columnToggleButton.addEventListener("click", toggleOptionalColumns);

  [elements.globalSearch, elements.bonusTypeFilter, elements.statusFilter, elements.ruleScopeFilter, elements.ownerFilter, elements.minAmountFilter, elements.maxAmountFilter].forEach((input) => {
    input.addEventListener("input", applyTableFilters);
    input.addEventListener("change", applyTableFilters);
  });

  document.querySelectorAll(".quick-filters button").forEach((button) => {
    button.addEventListener("click", () => applyQuickFilter(button.dataset.quick));
  });
}

async function calculateRun() {
  const file = elements.fileInput.files[0];
  if (!file) {
    setStatus(elements.status, "请先选择 Excel 文件。", true);
    return;
  }

  const form = new FormData();
  form.append("file", file);
  setStatus(elements.status, "正在创建批次并初算...", false);
  showTableSkeleton("正在生成本月核算结果");
  elements.calculateButton.disabled = true;

  try {
    const data = await requestJson("/api/runs/calculate", { method: "POST", body: form });
    await loadRuns(data.id);
    await selectRun(data);
    setStatus(elements.status, `初算完成：${data.id}`, false);
    showToast("初算完成，已生成新的核算批次。");
  } catch (error) {
    setStatus(elements.status, error.message, true);
    showToast(error.message, "error");
  } finally {
    elements.calculateButton.disabled = false;
  }
}

async function finalizeRun() {
  if (!state.currentRun) {
    setStatus(elements.finalStatus, "请先选择或创建一个核算批次。", true);
    return;
  }
  const confirmationFile = elements.confirmationInput.files[0];
  if (!confirmationFile) {
    setStatus(elements.finalStatus, "请上传已确认的待确认表。", true);
    return;
  }

  const form = new FormData();
  form.append("confirmation_file", confirmationFile);
  setStatus(elements.finalStatus, "正在生成最终结果...", false);
  showTableSkeleton("正在生成最终结果");
  elements.finalizeButton.disabled = true;

  try {
    const data = await requestJson(`/api/runs/${state.currentRun.id}/finalize`, { method: "POST", body: form });
    await loadRuns(data.id);
    await selectRun(data);
    setStatus(elements.finalStatus, `最终结果已生成：${data.files.finalResult.filename}`, false);
    showToast("最终结果已生成。");
  } catch (error) {
    setStatus(elements.finalStatus, error.message, true);
    showToast(error.message, "error");
  } finally {
    elements.finalizeButton.disabled = false;
  }
}

async function compareRun() {
  if (!state.currentRun) {
    setStatus(elements.compareStatus, "请先选择或创建一个核算批次。", true);
    return;
  }
  const offlineFile = elements.offlineInput.files[0];
  if (!offlineFile) {
    setStatus(elements.compareStatus, "请上传线下核算表或复核表。", true);
    return;
  }

  const form = new FormData();
  form.append("offline_file", offlineFile);
  setStatus(elements.compareStatus, "正在生成差异报告...", false);
  showTableSkeleton("正在生成差异报告");
  elements.compareButton.disabled = true;

  try {
    const data = await requestJson(`/api/runs/${state.currentRun.id}/compare`, { method: "POST", body: form });
    await loadRuns(data.id);
    await selectRun(data);
    setStatus(elements.compareStatus, `差异报告已生成：${data.files.diffReport.filename}`, false);
    showToast("差异报告已生成。");
  } catch (error) {
    setStatus(elements.compareStatus, error.message, true);
    showToast(error.message, "error");
  } finally {
    elements.compareButton.disabled = false;
  }
}

async function loadRuns(preferredId = "") {
  try {
    const data = await requestJson("/api/runs");
    state.runs = data.runs || [];
    renderRunList();
    if (preferredId) {
      const preferred = state.runs.find((run) => run.id === preferredId);
      if (preferred) await selectRun(preferred);
    } else if (!state.currentRun && state.runs.length) {
      await selectRun(state.runs[0]);
    }
  } catch (error) {
    elements.runList.innerHTML = `<div class="empty-card error-text">${escapeHtml(error.message)}</div>`;
  }
}

async function selectRun(run) {
  state.currentRun = run;
  renderRunList();
  renderRun(run);
  await loadTableData(run.id);
}

function renderRun(run) {
  for (const id of metricIds) {
    document.querySelector(`#${id}`).textContent = formatMetric(id, run[id]);
  }
  elements.currentRunTitle.textContent = `${run.month || "-"} · ${run.status || "已创建"}`;
  elements.currentRunSubTitle.textContent = run.id ? `批次 ${run.id}` : "上传月度导入表后，平台会生成一个可追溯的核算批次。";
  elements.ruleVersion.textContent = formatRuleInfo(run.ruleInfo);
  renderDiffSummary(run.diffMetrics);
  renderDownloads(run);
  updateStepState(run);
  updatePrimaryDownloads(run);
}

async function loadTableData(runId) {
  if (!runId) return;
  elements.tableSummary.textContent = "正在读取批次明细...";
  showTableSkeleton("正在读取批次明细");
  try {
    const data = await requestJson(`/api/runs/${runId}/table-data`);
    state.tableRows = data.rows || [];
    state.filters = data.filters || {};
    populateFilters(state.filters);
    renderCommandTable(state.tableRows);
    updateTableSummary(data.stats || {});
  } catch (error) {
    elements.tableSummary.textContent = error.message;
    renderCommandTable([]);
    showToast(error.message, "error");
  }
}

function showTableSkeleton(label = "正在加载数据") {
  if (state.table) {
    state.table.destroy();
    state.table = null;
  }
  const container = document.querySelector("#commandTable");
  container.innerHTML = `
    <div class="table-loading" role="status" aria-label="${escapeHtml(label)}">
      <div class="loading-copy">
        <strong>${escapeHtml(label)}</strong>
        <span>平台正在整理核算明细、状态和发放节点。</span>
      </div>
      <div class="skeleton-grid">
        ${Array.from({ length: 8 })
          .map(
            (_, index) => `
              <div class="skeleton-line wide"></div>
              <div class="skeleton-line ${index % 3 === 0 ? "short" : "mid"}"></div>
              <div class="skeleton-line"></div>
              <div class="skeleton-line tiny"></div>
            `,
          )
          .join("")}
      </div>
    </div>
  `;
}

function renderCommandTable(rows) {
  if (!window.Tabulator) {
    renderFallbackTable(rows);
    return;
  }
  if (state.table) {
    state.table.replaceData(rows);
    applyTableFilters();
    return;
  }
  state.table = new Tabulator("#commandTable", {
    data: rows,
    height: "620px",
    layout: "fitDataStretch",
    pagination: true,
    paginationSize: 30,
    paginationSizeSelector: [20, 30, 50, 100],
    placeholder: "暂无明细数据",
    selectableRows: false,
    rowFormatter(row) {
      row.getElement().classList.add(`status-${row.getData().status || "normal"}`);
    },
    columns: [
      { title: "状态", field: "status", width: 104, frozen: true, formatter: statusFormatter },
      { title: "奖金类型", field: "type", width: 112, frozen: true },
      { title: "姓名", field: "employeeName", width: 118, frozen: true },
      { title: "工号", field: "employeeNo", width: 128 },
      { title: "节点", field: "node", width: 150 },
      { title: "金额", field: "amount", hozAlign: "right", width: 126, formatter: moneyFormatter },
      { title: "币种", field: "currency", width: 86 },
      { title: "工作地", field: "location", width: 180 },
      { title: "规则范围", field: "ruleScope", width: 126 },
      { title: "负责人/推荐人", field: "ownerName", width: 140 },
      { title: "职级", field: "grade", width: 80 },
      { title: "ABC", field: "category", width: 80 },
      { title: "渠道", field: "channel", width: 130 },
      { title: "提示", field: "message", width: 280 },
      { title: "源行", field: "sourceRow", width: 82, hozAlign: "right" },
    ],
  });
  state.table.on("rowClick", (_event, row) => openDrawer(row.getData()));
  state.table.on("dataFiltered", (_filters, filteredRows) => {
    elements.visibleRows.textContent = filteredRows.length;
  });
  state.table.on("dataLoaded", () => {
    elements.visibleRows.textContent = state.table.getDataCount("active");
    elements.totalRows.textContent = rows.length;
  });
  applyTableFilters();
}

function renderFallbackTable(rows) {
  const container = document.querySelector("#commandTable");
  const columns = [
    ["status", "状态"],
    ["type", "奖金类型"],
    ["employeeName", "姓名"],
    ["employeeNo", "工号"],
    ["node", "节点"],
    ["amount", "金额"],
    ["currency", "币种"],
    ["location", "工作地"],
    ["ruleScope", "规则范围"],
    ["ownerName", "负责人/推荐人"],
    ["message", "提示"],
    ["sourceRow", "源行"],
  ];
  if (!rows.length) {
    container.innerHTML = '<div class="empty-card">暂无明细数据</div>';
    return;
  }
  const sortedRows = sortRows(rows);
  const totalPages = Math.max(1, Math.ceil(sortedRows.length / state.pageSize));
  state.currentPage = Math.min(state.currentPage, totalPages);
  const start = (state.currentPage - 1) * state.pageSize;
  const pageRows = sortedRows.slice(start, start + state.pageSize);

  const table = document.createElement("table");
  table.className = "fallback-grid";
  const thead = document.createElement("thead");
  const headerRow = document.createElement("tr");
  for (const [field, label] of columns) {
    const th = document.createElement("th");
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = `${label}${state.sortField === field ? (state.sortDir === "asc" ? " ↑" : " ↓") : ""}`;
    button.addEventListener("click", () => {
      if (state.sortField === field) state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
      else {
        state.sortField = field;
        state.sortDir = "asc";
      }
      renderFallbackTable(state.filteredRows);
    });
    th.appendChild(button);
    headerRow.appendChild(th);
  }
  thead.appendChild(headerRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  for (const row of pageRows) {
    const tr = document.createElement("tr");
    tr.addEventListener("click", () => openDrawer(row));
    for (const [field] of columns) {
      const td = document.createElement("td");
      if (field === "status") td.innerHTML = `<span class="status-pill ${statusClass(row.status)}">${escapeHtml(row.status || "-")}</span>`;
      else if (field === "amount") td.innerHTML = `<span class="money-cell">${formatMoney(row.amount)}</span>`;
      else td.textContent = row[field] ?? "";
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);

  const pager = document.createElement("div");
  pager.className = "fallback-pager";
  const prev = document.createElement("button");
  prev.type = "button";
  prev.textContent = "上一页";
  prev.disabled = state.currentPage <= 1;
  prev.addEventListener("click", () => {
    state.currentPage -= 1;
    renderFallbackTable(state.filteredRows);
  });
  const next = document.createElement("button");
  next.type = "button";
  next.textContent = "下一页";
  next.disabled = state.currentPage >= totalPages;
  next.addEventListener("click", () => {
    state.currentPage += 1;
    renderFallbackTable(state.filteredRows);
  });
  const pageText = document.createElement("span");
  pageText.textContent = `第 ${state.currentPage} / ${totalPages} 页`;
  pager.append(prev, pageText, next);

  container.innerHTML = "";
  container.append(table, pager);
}

function applyTableFilters() {
  const rows = state.tableRows || [];
  const search = elements.globalSearch.value.trim().toLowerCase();
  const bonusType = elements.bonusTypeFilter.value;
  const status = elements.statusFilter.value;
  const ruleScope = elements.ruleScopeFilter.value;
  const owner = elements.ownerFilter.value;
  const minAmount = numberOrNull(elements.minAmountFilter.value);
  const maxAmount = numberOrNull(elements.maxAmountFilter.value);

  const filtered = rows.filter((row) => {
    const amount = Number(row.amount || 0);
    if (search && !String(row.searchText || "").includes(search)) return false;
    if (bonusType && row.type !== bonusType) return false;
    if (status && row.status !== status) return false;
    if (ruleScope && row.ruleScope !== ruleScope) return false;
    if (owner && (row.ownerName || row.ownerNo) !== owner) return false;
    if (minAmount !== null && amount < minAmount) return false;
    if (maxAmount !== null && amount > maxAmount) return false;
    return true;
  });
  state.filteredRows = filtered;

  if (state.table) {
    state.table.replaceData(filtered).then(() => {
      elements.visibleRows.textContent = filtered.length;
      elements.totalRows.textContent = rows.length;
    });
  } else {
    state.currentPage = 1;
    renderFallbackTable(filtered);
    elements.visibleRows.textContent = filtered.length;
    elements.totalRows.textContent = rows.length;
  }
}

function sortRows(rows) {
  if (!state.sortField) return rows;
  return [...rows].sort((left, right) => {
    const a = state.sortField === "amount" ? Number(left[state.sortField] || 0) : String(left[state.sortField] || "");
    const b = state.sortField === "amount" ? Number(right[state.sortField] || 0) : String(right[state.sortField] || "");
    if (a < b) return state.sortDir === "asc" ? -1 : 1;
    if (a > b) return state.sortDir === "asc" ? 1 : -1;
    return 0;
  });
}

function applyQuickFilter(action) {
  if (action === "reset") {
    [elements.globalSearch, elements.minAmountFilter, elements.maxAmountFilter].forEach((input) => {
      input.value = "";
    });
    [elements.bonusTypeFilter, elements.statusFilter, elements.ruleScopeFilter, elements.ownerFilter].forEach((select) => {
      select.value = "";
    });
  }
  if (action === "pending") elements.statusFilter.value = "待确认";
  if (action === "exception") elements.statusFilter.value = "异常";
  if (action === "diff") elements.statusFilter.value = "差异";
  if (action === "amount") {
    elements.statusFilter.value = "";
    elements.minAmountFilter.value = "0.01";
  }
  applyTableFilters();
}

function populateFilters(filters) {
  fillSelect(elements.bonusTypeFilter, filters.bonusTypes || []);
  fillSelect(elements.statusFilter, filters.statuses || []);
  fillSelect(elements.ruleScopeFilter, filters.ruleScopes || []);
  fillSelect(elements.ownerFilter, filters.owners || []);
}

function fillSelect(select, values) {
  const current = select.value;
  select.innerHTML = '<option value="">全部</option>';
  for (const value of values) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.appendChild(option);
  }
  if ([...select.options].some((option) => option.value === current)) {
    select.value = current;
  }
}

function updateTableSummary(stats) {
  elements.visibleRows.textContent = stats.totalRows || 0;
  elements.totalRows.textContent = stats.totalRows || 0;
  elements.tableSummary.textContent = `共 ${stats.totalRows || 0} 行，待确认 ${stats.pendingRows || 0}，异常 ${stats.exceptionRows || 0}，差异 ${stats.diffRows || 0}。`;
}

function openDrawer(row) {
  elements.detailDrawer.classList.add("open");
  elements.detailDrawer.setAttribute("aria-hidden", "false");
  elements.drawerTitle.textContent = `${row.employeeName || row.node || row.type || "明细"} ${row.employeeNo ? `· ${row.employeeNo}` : ""}`;
  elements.drawerSubtitle.textContent = `${row.type || "-"} · ${row.status || "-"} · 源行 ${row.sourceRow || "-"}`;
  elements.drawerContent.innerHTML = drawerHtml(row);
  renderIcons();
}

function closeDrawer() {
  elements.detailDrawer.classList.remove("open");
  elements.detailDrawer.setAttribute("aria-hidden", "true");
}

function drawerHtml(row) {
  const nodes = row.calculation?.nodes || [];
  const activeNodes = nodes.filter((node) => Number(node.amount || 0) || node.period);
  return `
    <section class="drawer-section">
      <h3>基础信息</h3>
      <dl>
        ${drawerPair("姓名", row.employeeName)}
        ${drawerPair("工号", row.employeeNo)}
        ${drawerPair("职级", row.grade)}
        ${drawerPair("ABC类别", row.category)}
        ${drawerPair("工作地", row.location)}
        ${drawerPair("入职日期", row.onboardDate)}
        ${drawerPair("转正日期", row.probationDate)}
      </dl>
    </section>
    <section class="drawer-section">
      <h3>奖金解释</h3>
      <dl>
        ${drawerPair("命中规则范围", row.ruleScope)}
        ${drawerPair("招聘奖金标准", formatMoney(row.calculation?.recruitmentStandardBonus))}
        ${drawerPair("内推奖金标准", formatMoney(row.calculation?.referralStandardBonus))}
        ${drawerPair("渠道系数", row.calculation?.channelRatio)}
        ${drawerPair("标准周期", row.calculation?.standardCycleDays)}
        ${drawerPair("实际周期", row.calculation?.actualCycleDays)}
      </dl>
    </section>
    <section class="drawer-section">
      <h3>发放节点</h3>
      <div class="node-list">
        ${
          activeNodes.length
            ? activeNodes.map((node) => `<div><span>${escapeHtml(node.type)} · ${escapeHtml(node.role)} · ${escapeHtml(node.label)}</span><strong>${escapeHtml(node.period || "-")} / ${formatMoney(node.amount)}</strong></div>`).join("")
            : '<div><span>无本月发放节点</span><strong>-</strong></div>'
        }
      </div>
    </section>
    <section class="drawer-section">
      <h3>处理信息</h3>
      <p>${escapeHtml(row.message || "无异常或待确认提示。")}</p>
    </section>
  `;
}

function drawerPair(label, value) {
  return `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value ?? "-")}</dd>`;
}

function renderRunList() {
  if (!state.runs.length) {
    elements.runList.innerHTML = '<div class="empty-card">暂无批次，先上传本月导入表。</div>';
    return;
  }
  elements.runList.innerHTML = "";
  for (const run of state.runs.slice(0, 12)) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `run-item${state.currentRun?.id === run.id ? " active" : ""}`;
    button.innerHTML = `
      <span class="run-status-orb" aria-hidden="true"></span>
      <span class="run-month">${escapeHtml(run.month || "-")}</span>
      <strong>${escapeHtml(run.status || "已创建")}</strong>
      <em>${escapeHtml(shortRunId(run.id))}</em>
    `;
    button.addEventListener("click", () => selectRun(run));
    elements.runList.appendChild(button);
  }
}

function renderDownloads(run) {
  const files = run.files || {};
  const ordered = [
    ["input", "原始导入"],
    ["initialResult", "初算结果"],
    ["pending", "待确认表"],
    ["confirmation", "确认结果"],
    ["finalResult", "最终结果"],
    ["offlineReview", "线下复核表"],
    ["diffReport", "差异报告"],
  ];
  const available = ordered.map(([key, label]) => ({ key, label, file: files[key] })).filter((item) => item.file?.downloadUrl);
  if (!available.length) {
    elements.downloadGrid.innerHTML = '<div class="empty-card">创建批次后显示原始导入、初算结果、待确认表、最终结果和差异报告。</div>';
    return;
  }
  elements.downloadGrid.innerHTML = "";
  for (const item of available) {
    const link = document.createElement("a");
    link.href = item.file.downloadUrl;
    link.download = item.file.filename || "";
    link.className = "file-link";
    link.innerHTML = `<i data-lucide="file-down"></i><span>${item.label}</span><strong>${escapeHtml(item.file.filename)}</strong>`;
    elements.downloadGrid.appendChild(link);
  }
  renderIcons();
}

function updatePrimaryDownloads(run) {
  const resultUrl = run.finalDownloadUrl || run.downloadUrl || run.files?.finalResult?.downloadUrl || run.files?.initialResult?.downloadUrl || "";
  setLink(elements.downloadLink, resultUrl);
  setLink(elements.pendingDownloadLink, run.pendingDownloadUrl || run.files?.pending?.downloadUrl || "");
}

function updateStepState(run) {
  const activeSteps = new Set(["upload", "calculate"]);
  if ((run.pendingCount || 0) > 0 || run.status === "待确认") activeSteps.add("pending");
  if (run.files?.finalResult) activeSteps.add("final");
  if (run.files?.diffReport) activeSteps.add("compare");
  if (run.files?.finalResult || run.files?.diffReport) activeSteps.add("archive");
  document.querySelectorAll(".flow-step").forEach((step) => {
    step.classList.toggle("active", activeSteps.has(step.dataset.step));
  });
}

function renderDiffSummary(metrics) {
  if (!metrics) {
    elements.diffSummary.innerHTML = '<div class="empty-card">上传线下表后展示招聘/内推汇总差异行数和金额差异。</div>';
    return;
  }
  const rows = [
    ["招聘汇总差异", metrics.recruitmentSummaryDiffCount, metrics.recruitmentSummaryDelta],
    ["内推汇总差异", metrics.referralSummaryDiffCount, metrics.referralSummaryDelta],
    ["招聘明细差异", metrics.recruitmentDetailDiffCount, ""],
    ["内推明细差异", metrics.referralDetailDiffCount, ""],
  ];
  elements.diffSummary.innerHTML = rows.map(([label, count, amount]) => `<div><span>${label}</span><strong>${count ?? 0}</strong><em>${amount === "" ? "明细行数" : formatMoney(amount)}</em></div>`).join("");
}

function toggleOptionalColumns() {
  if (!state.table) return;
  state.optionalColumnsHidden = !state.optionalColumnsHidden;
  for (const field of optionalColumnFields) {
    const column = state.table.getColumn(field);
    if (!column) continue;
    if (state.optionalColumnsHidden) column.hide();
    else column.show();
  }
}

function toggleRunsPanel() {
  state.runsCollapsed = !state.runsCollapsed;
  document.body.classList.toggle("runs-collapsed", state.runsCollapsed);
  elements.toggleRunsButton.title = state.runsCollapsed ? "展开批次" : "收起批次";
  elements.toggleRunsButton.innerHTML = `<i data-lucide="${state.runsCollapsed ? "panel-left-open" : "panel-left-close"}"></i>`;
  renderIcons();
}

function toggleFiltersPanel() {
  state.filtersCollapsed = !state.filtersCollapsed;
  document.body.classList.toggle("filters-collapsed", state.filtersCollapsed);
  elements.toggleFiltersButton.title = state.filtersCollapsed ? "展开筛选器" : "收起筛选器";
  elements.toggleFiltersButton.innerHTML = `<i data-lucide="${state.filtersCollapsed ? "sliders-horizontal" : "panel-left-close"}"></i>`;
  renderIcons();
}

function statusFormatter(cell) {
  const value = cell.getValue() || "-";
  return `<span class="status-pill ${statusClass(value)}">${escapeHtml(value)}</span>`;
}

function moneyFormatter(cell) {
  return `<span class="money-cell">${formatMoney(cell.getValue())}</span>`;
}

function statusClass(value) {
  if (value === "待确认") return "pending";
  if (value === "异常") return "exception";
  if (value === "差异") return "diff";
  return "normal";
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || "请求失败");
  }
  return data;
}

function setStatus(element, message, isError) {
  element.textContent = message;
  element.classList.toggle("error", Boolean(isError));
}

function showToast(message, type = "success") {
  if (!elements.toastRegion) return;
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.innerHTML = `<span>${escapeHtml(message)}</span>`;
  elements.toastRegion.appendChild(toast);
  window.setTimeout(() => {
    toast.classList.add("leaving");
    window.setTimeout(() => toast.remove(), 220);
  }, 3200);
}

function setLink(link, url) {
  if (!url) {
    link.href = "#";
    link.removeAttribute("download");
    link.classList.add("disabled");
    link.setAttribute("aria-disabled", "true");
    return;
  }
  link.href = url;
  link.download = "";
  link.classList.remove("disabled");
  link.setAttribute("aria-disabled", "false");
}

function formatMetric(id, value) {
  if (value === undefined || value === null || value === "") return "-";
  if (id.includes("Total")) return formatMoney(value);
  return value;
}

function formatMoney(value) {
  const number = Number(value || 0);
  return number.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatRuleInfo(ruleInfo) {
  if (!ruleInfo?.updatedAt) return "等待读取";
  return new Date(ruleInfo.updatedAt).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function shortRunId(id) {
  if (!id) return "-";
  const parts = id.split("_");
  return parts.length >= 4 ? `${parts[0]} · ${parts[1]} ${parts[2]}` : id;
}

function numberOrNull(value) {
  if (value === "" || value === null || value === undefined) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function renderIcons() {
  if (window.lucide) {
    window.lucide.createIcons();
  }
}
