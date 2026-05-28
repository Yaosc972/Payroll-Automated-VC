const laborState = {
  run: null,
  headers: [],
  comparePollTimer: null,
};

const labor = {
  supplierName: document.querySelector("#supplierName"),
  periodStart: document.querySelector("#periodStart"),
  periodEnd: document.querySelector("#periodEnd"),
  currency: document.querySelector("#currency"),
  createLaborRun: document.querySelector("#createLaborRun"),
  createStatus: document.querySelector("#createStatus"),
  pdfFiles: document.querySelector("#pdfFiles"),
  pdfFileName: document.querySelector("#pdfFileName"),
  workbookFile: document.querySelector("#workbookFile"),
  workbookFileName: document.querySelector("#workbookFileName"),
  uploadLaborFiles: document.querySelector("#uploadLaborFiles"),
  uploadStatus: document.querySelector("#uploadStatus"),
  loadSheets: document.querySelector("#loadSheets"),
  saveMapping: document.querySelector("#saveMapping"),
  sheetSelect: document.querySelector("#sheetSelect"),
  employeeIdColumn: document.querySelector("#employeeIdColumn"),
  nameColumn: document.querySelector("#nameColumn"),
  hoursColumn: document.querySelector("#hoursColumn"),
  amountColumn: document.querySelector("#amountColumn"),
  currencyColumn: document.querySelector("#currencyColumn"),
  mappingPreview: document.querySelector("#mappingPreview"),
  extractCompare: document.querySelector("#extractCompare"),
  compareStatus: document.querySelector("#compareStatus"),
  qualityAlert: document.querySelector("#qualityAlert"),
  summaryGrid: document.querySelector("#summaryGrid"),
  amountDiffTable: document.querySelector("#amountDiffTable"),
  candidateTable: document.querySelector("#candidateTable"),
  riskTable: document.querySelector("#riskTable"),
  extractPreviewTable: document.querySelector("#extractPreviewTable"),
  reportLink: document.querySelector("#laborReportLink"),
  toast: document.querySelector("#laborToast"),
};

bindLaborEvents();

function bindLaborEvents() {
  labor.createLaborRun.addEventListener("click", createRun);
  labor.uploadLaborFiles.addEventListener("click", uploadFiles);
  labor.loadSheets.addEventListener("click", loadSheets);
  labor.sheetSelect.addEventListener("change", loadFieldSuggestions);
  labor.saveMapping.addEventListener("click", saveMapping);
  labor.extractCompare.addEventListener("click", extractAndCompare);
  labor.pdfFiles.addEventListener("change", () => {
    labor.pdfFileName.textContent = labor.pdfFiles.files.length ? `${labor.pdfFiles.files.length} 个 PDF 已选择` : "选择供应商 PDF 发票";
  });
  labor.workbookFile.addEventListener("change", () => {
    labor.workbookFileName.textContent = labor.workbookFile.files[0]?.name || "选择线下账单";
  });
}

async function createRun() {
  setText(labor.createStatus, "正在创建批次...");
  try {
    const run = await requestJson("/api/labor/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        supplier_name: labor.supplierName.value,
        period_start: labor.periodStart.value,
        period_end: labor.periodEnd.value,
        currency: labor.currency.value,
      }),
    });
    laborState.run = run;
    setText(labor.createStatus, `批次已创建：${run.id}`);
    toast("劳务核对批次已创建。");
  } catch (error) {
    setText(labor.createStatus, error.message, true);
    toast(error.message);
  }
}

async function uploadFiles() {
  if (!laborState.run) return toast("请先创建批次。");
  if (!labor.pdfFiles.files.length || !labor.workbookFile.files[0]) return toast("请上传 PDF 发票和 Excel 账单。");
  const form = new FormData();
  Array.from(labor.pdfFiles.files).forEach((file) => form.append("pdf_files", file));
  form.append("workbook_file", labor.workbookFile.files[0]);
  setText(labor.uploadStatus, "正在上传文件...");
  try {
    laborState.run = await requestJson(`/api/labor/runs/${laborState.run.id}/files`, { method: "POST", body: form });
    setText(labor.uploadStatus, "文件已上传，可以读取工作表。");
    toast("文件上传完成。");
  } catch (error) {
    setText(labor.uploadStatus, error.message, true);
    toast(error.message);
  }
}

async function loadSheets() {
  if (!laborState.run) return toast("请先创建并上传文件。");
  try {
    const data = await requestJson(`/api/labor/runs/${laborState.run.id}/workbook-sheets`);
    labor.sheetSelect.innerHTML = data.sheets.map((sheet) => `<option value="${escapeHtml(sheet)}">${escapeHtml(sheet)}</option>`).join("");
    if (data.sheets.length) await loadFieldSuggestions();
  } catch (error) {
    toast(error.message);
  }
}

async function loadFieldSuggestions() {
  const sheetName = labor.sheetSelect.value;
  if (!sheetName) return;
  try {
    const data = await requestJson(`/api/labor/runs/${laborState.run.id}/field-suggestions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sheet_name: sheetName }),
    });
    laborState.headers = data.headers || [];
    fillColumnSelect(labor.employeeIdColumn, data.suggestedMapping?.employeeId, true);
    fillColumnSelect(labor.nameColumn, data.suggestedMapping?.name);
    fillColumnSelect(labor.hoursColumn, data.suggestedMapping?.hours);
    fillColumnSelect(labor.amountColumn, data.suggestedMapping?.amount);
    fillColumnSelect(labor.currencyColumn, data.suggestedMapping?.currency, true);
    renderPreview(data.previewRows || []);
  } catch (error) {
    toast(error.message);
  }
}

async function saveMapping() {
  if (!laborState.run) return toast("请先创建批次。");
  try {
    laborState.run = await requestJson(`/api/labor/runs/${laborState.run.id}/mapping`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sheet_name: labor.sheetSelect.value,
        mapping: {
          name: labor.nameColumn.value,
          employeeId: labor.employeeIdColumn.value,
          hours: labor.hoursColumn.value,
          amount: labor.amountColumn.value,
          currency: labor.currencyColumn.value,
        },
      }),
    });
    toast("字段映射已确认。");
  } catch (error) {
    toast(error.message);
  }
}

async function extractAndCompare() {
  if (!laborState.run) return toast("请先创建批次。");
  stopComparePolling();
  setText(labor.compareStatus, "已提交后台抽取，正在等待结果...");
  labor.extractCompare.disabled = true;
  try {
    laborState.run = await requestJson(`/api/labor/runs/${laborState.run.id}/extract-and-compare`, { method: "POST" });
    setText(labor.compareStatus, "后台抽取中，页面会自动刷新结果...");
    await pollCompareResult();
    laborState.comparePollTimer = window.setInterval(pollCompareResult, 3000);
  } catch (error) {
    labor.extractCompare.disabled = false;
    setText(labor.compareStatus, error.message, true);
    toast(error.message);
  }
}

async function pollCompareResult() {
  if (!laborState.run) return;
  try {
    const run = await requestJson(`/api/labor/runs/${laborState.run.id}`);
    laborState.run = run;
    if (run.status === "抽取失败") {
      stopComparePolling();
      labor.extractCompare.disabled = false;
      setText(labor.compareStatus, run.errorMessage || "抽取失败，请检查文件后重试。", true);
      toast(run.errorMessage || "抽取失败。");
      return;
    }
    if (run.diffDownloadUrl || run.status === "已生成差异报告") {
      stopComparePolling();
      labor.extractCompare.disabled = false;
      renderResult(run);
      setText(labor.compareStatus, "核对完成。低置信度项已在风险表标记。");
      setDownload(run.diffDownloadUrl);
      toast("差异报告已生成。");
      return;
    }
    setText(labor.compareStatus, "后台抽取中，页面会自动刷新结果...");
  } catch (error) {
    stopComparePolling();
    labor.extractCompare.disabled = false;
    setText(labor.compareStatus, error.message, true);
    toast(error.message);
  }
}

function stopComparePolling() {
  if (!laborState.comparePollTimer) return;
  window.clearInterval(laborState.comparePollTimer);
  laborState.comparePollTimer = null;
}

function fillColumnSelect(select, selected = "", optional = false) {
  const empty = optional ? '<option value="">不使用</option>' : "";
  select.innerHTML = empty + laborState.headers.map((header) => `<option value="${escapeHtml(header)}">${escapeHtml(header)}</option>`).join("");
  select.value = selected || "";
}

function renderPreview(rows) {
  if (!rows.length) {
    labor.mappingPreview.innerHTML = '<p class="empty-state-text">No preview data available.</p>';
    return;
  }
  const headers = laborState.headers.slice(0, 6);
  labor.mappingPreview.innerHTML = `<table><thead><tr>${headers.map((header) => `<th>${escapeHtml(header)}</th>`).join("")}</tr></thead><tbody>${rows.slice(0, 4).map((row) => `<tr>${headers.map((header) => `<td>${escapeHtml(row[header] ?? "")}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}

function renderResult(run) {
  const summary = run.comparisonSummary || {};
  renderQualityAlert(run.extractionQuality);
  const metrics = [
    { label: "PDF人数", value: summary.pdfEmployeeCount, type: "info" },
    { label: "Excel人数", value: summary.excelEmployeeCount, type: "info" },
    { label: "PDF总工时", value: summary.pdfHoursTotal, type: "info" },
    { label: "Excel总工时", value: summary.excelHoursTotal, type: "info" },
    { label: "金额差异人数", value: summary.amountDiffCount, type: summary.amountDiffCount > 0 ? "warning" : "success" },
    { label: "疑似姓名匹配", value: summary.fuzzyMatchCount, type: "info" },
    { label: "候选匹配", value: summary.candidateMatchCount, type: "info" },
    { label: "低置信度", value: summary.lowConfidenceCount, type: summary.lowConfidenceCount > 0 ? "warning" : "success" },
    { label: "风险人数", value: summary.exceptionCount, type: summary.exceptionCount > 0 ? "warning" : "success" },
  ];
  labor.summaryGrid.innerHTML = metrics.map(({ label, value, type }) => `<div class="metric-${type}"><span>${label}</span><strong>${escapeHtml(value ?? 0)}</strong></div>`).join("");
  const rows = run.comparisonRows || [];
  renderRows(labor.amountDiffTable, rows.filter((row) => row.matchStatus === "金额差异"));
  renderCandidateRows(labor.candidateTable, run.candidateMatches || []);
  renderRows(labor.riskTable, rows.filter((row) => row.matchStatus !== "通过" && row.matchStatus !== "金额差异"));
  renderExtractRows(labor.extractPreviewTable, run.pdfExtractedRows || []);
}

function renderQualityAlert(quality) {
  if (!labor.qualityAlert) return;
  if (!quality || quality.level === "ok") {
    labor.qualityAlert.hidden = true;
    labor.qualityAlert.innerHTML = "";
    return;
  }
  const issues = quality.issues || [];
  labor.qualityAlert.hidden = false;
  labor.qualityAlert.innerHTML = `<strong>${escapeHtml(quality.message || "抽取质量存在风险。")}</strong>${issues.length ? `<ul>${issues.map((issue) => `<li>${escapeHtml(issue)}</li>`).join("")}</ul>` : ""}`;
}

function renderRows(container, rows) {
  if (!rows.length) {
    container.innerHTML = '<p class="empty-state-text">No anomalies detected. System running smoothly.</p>';
    return;
  }
  container.innerHTML = `<table><thead><tr><th>员工</th><th>状态</th><th>PDF金额</th><th>Excel金额</th><th>差异</th><th>来源</th></tr></thead><tbody>${rows.map((row) => {
    const statusClass = row.matchStatus === "通过" ? "status-pass" : row.matchStatus === "金额差异" ? "status-diff" : "status-warn";
    return `<tr><td>${escapeHtml(row.employeeName)}</td><td><span class="risk-pill ${statusClass}">${escapeHtml(row.matchStatus)}</span></td><td>${formatMoney(row.pdfAmountTotal)}</td><td>${formatMoney(row.excelAmountTotal)}</td><td>${formatMoney(row.amountDelta)}</td><td>${escapeHtml(row.sourceRefs || "")}</td></tr>`;
  }).join("")}</tbody></table>`;
}

function renderCandidateRows(container, rows) {
  if (!rows.length) {
    container.innerHTML = '<p class="empty-state-text">No candidate matches to review.</p>';
    return;
  }
  const visible = rows.slice(0, 40);
  container.innerHTML = `<table><thead><tr><th>PDF员工</th><th>Excel员工</th><th>相似度</th><th>PDF金额</th><th>Excel金额</th><th>金额差</th><th>工时差</th><th>建议</th></tr></thead><tbody>${visible.map((row) => `<tr><td>${escapeHtml(row.pdfEmployeeName)}</td><td>${escapeHtml(row.excelEmployeeName)}</td><td>${formatPercent(row.nameSimilarity)}</td><td>${formatMoney(row.pdfAmountTotal)}</td><td>${formatMoney(row.excelAmountTotal)}</td><td>${formatMoney(row.amountDelta)}</td><td>${formatHours(row.hoursDelta)}</td><td><span class="candidate-pill">${escapeHtml(row.recommendation || "人工复核")}</span></td></tr>`).join("")}</tbody></table>${rows.length > visible.length ? `<p class="table-note">仅展示前 ${visible.length} 条，完整候选请下载报告查看。</p>` : ""}`;
}

function renderExtractRows(container, rows) {
  if (!rows.length) {
    container.innerHTML = '<p class="empty-state-text">Extract data will appear here after comparison.</p>';
    return;
  }
  const visible = rows.slice(0, 80);
  container.innerHTML = `<table><thead><tr><th>员工</th><th>工号</th><th>工时</th><th>金额</th><th>置信度</th><th>来源</th><th>证据</th></tr></thead><tbody>${visible.map((row) => `<tr><td>${escapeHtml(row.employee_name_raw)}</td><td>${escapeHtml(row.employee_id || "")}</td><td>${formatHours(row.hours)}</td><td>${formatMoney(row.amount)}</td><td>${formatPercent(row.confidence)}</td><td>${escapeHtml(`${row.source_file || ""} ${row.source_page_or_row || ""}`)}</td><td>${escapeHtml(row.evidence_text || "")}</td></tr>`).join("")}</tbody></table>${rows.length > visible.length ? `<p class="table-note">仅展示前 ${visible.length} 条，完整明细请下载报告查看。</p>` : ""}`;
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || "请求失败。");
  return data;
}

function setDownload(url) {
  if (!url) return;
  labor.reportLink.href = url;
  labor.reportLink.classList.remove("disabled");
  labor.reportLink.removeAttribute("aria-disabled");
}

function setText(element, value, error = false) {
  element.textContent = value;
  element.classList.toggle("error-text", error);
}

function toast(message) {
  labor.toast.textContent = message;
  labor.toast.classList.add("visible");
  window.setTimeout(() => labor.toast.classList.remove("visible"), 2600);
}

function formatMoney(value) {
  return Number(value || 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatHours(value) {
  return Number(value || 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatPercent(value) {
  const number = Number(value || 0);
  return number > 1 ? `${number.toFixed(1)}%` : `${(number * 100).toFixed(1)}%`;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[char]));
}
