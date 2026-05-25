const state = {
  currentRun: null,
  runs: [],
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
  downloadLink: document.querySelector("#downloadLink"),
  pendingDownloadLink: document.querySelector("#pendingDownloadLink"),
  downloadGrid: document.querySelector("#downloadGrid"),
  currentRunTitle: document.querySelector("#currentRunTitle"),
  currentRunSubTitle: document.querySelector("#currentRunSubTitle"),
  ruleVersion: document.querySelector("#ruleVersion"),
  diffSummary: document.querySelector("#diffSummary"),
};

const metricIds = ["month", "importedRows", "recruitmentTotal", "referralTotal", "pendingCount", "exceptionCount"];

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

  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((item) => item.classList.remove("active"));
      document.querySelectorAll(".table-panel").forEach((panel) => panel.classList.remove("active"));
      tab.classList.add("active");
      document.querySelector(`#${tab.dataset.target}`).classList.add("active");
    });
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
  elements.calculateButton.disabled = true;

  try {
    const data = await requestJson("/api/runs/calculate", { method: "POST", body: form });
    await loadRuns(data.id);
    selectRun(data);
    setStatus(elements.status, `初算完成：${data.id}`, false);
  } catch (error) {
    setStatus(elements.status, error.message, true);
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
  elements.finalizeButton.disabled = true;

  try {
    const data = await requestJson(`/api/runs/${state.currentRun.id}/finalize`, { method: "POST", body: form });
    await loadRuns(data.id);
    selectRun(data);
    setStatus(elements.finalStatus, `最终结果已生成：${data.files.finalResult.filename}`, false);
  } catch (error) {
    setStatus(elements.finalStatus, error.message, true);
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
  elements.compareButton.disabled = true;

  try {
    const data = await requestJson(`/api/runs/${state.currentRun.id}/compare`, { method: "POST", body: form });
    await loadRuns(data.id);
    selectRun(data);
    setStatus(elements.compareStatus, `差异报告已生成：${data.files.diffReport.filename}`, false);
  } catch (error) {
    setStatus(elements.compareStatus, error.message, true);
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
      if (preferred) selectRun(preferred);
    } else if (!state.currentRun && state.runs.length) {
      selectRun(state.runs[0]);
    }
  } catch (error) {
    elements.runList.innerHTML = `<div class="empty-card error-text">${escapeHtml(error.message)}</div>`;
  }
}

function selectRun(run) {
  state.currentRun = run;
  renderRunList();
  renderRun(run);
}

function renderRun(run) {
  for (const id of metricIds) {
    const value = run[id];
    document.querySelector(`#${id}`).textContent = formatMetric(id, value);
  }
  elements.currentRunTitle.textContent = `${run.month || "-"} · ${run.status || "已创建"}`;
  elements.currentRunSubTitle.textContent = run.id ? `批次 ${run.id}` : "上传月度导入表后，平台会生成一个可追溯的核算批次。";
  elements.ruleVersion.textContent = formatRuleInfo(run.ruleInfo);
  renderTable("#previewTable", run.detailPreview || []);
  renderTable("#pendingTable", run.pendingConfirmations || []);
  renderTable("#exceptionTable", run.exceptions || []);
  renderDiffSummary(run.diffMetrics);
  renderDownloads(run);
  updateStepState(run);
  updatePrimaryDownloads(run);
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
      <span>${escapeHtml(run.month || "-")}</span>
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
  elements.diffSummary.innerHTML = rows
    .map(([label, count, amount]) => `<div><span>${label}</span><strong>${count ?? 0}</strong><em>${amount === "" ? "明细行数" : formatMoney(amount)}</em></div>`)
    .join("");
}

function renderTable(selector, rows) {
  const table = document.querySelector(selector);
  const thead = table.querySelector("thead");
  const tbody = table.querySelector("tbody");
  thead.innerHTML = "";
  tbody.innerHTML = "";

  if (!rows.length) {
    tbody.innerHTML = '<tr><td class="empty">暂无数据</td></tr>';
    return;
  }

  const headers = Object.keys(rows[0]);
  const headerRow = document.createElement("tr");
  for (const header of headers) {
    const th = document.createElement("th");
    th.textContent = header;
    headerRow.appendChild(th);
  }
  thead.appendChild(headerRow);

  for (const row of rows) {
    const tr = document.createElement("tr");
    for (const header of headers) {
      const td = document.createElement("td");
      td.textContent = row[header] ?? "";
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
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
