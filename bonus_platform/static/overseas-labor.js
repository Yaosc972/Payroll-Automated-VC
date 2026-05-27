const laborState = {
  run: null,
  headers: [],
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
  summaryGrid: document.querySelector("#summaryGrid"),
  amountDiffTable: document.querySelector("#amountDiffTable"),
  riskTable: document.querySelector("#riskTable"),
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
  setText(labor.compareStatus, "正在抽取 PDF 并生成差异...");
  try {
    laborState.run = await requestJson(`/api/labor/runs/${laborState.run.id}/extract-and-compare`, { method: "POST" });
    renderResult(laborState.run);
    setText(labor.compareStatus, "核对完成。低置信度项已在风险表标记。");
    setDownload(laborState.run.diffDownloadUrl);
    toast("差异报告已生成。");
  } catch (error) {
    setText(labor.compareStatus, error.message, true);
    toast(error.message);
  }
}

function fillColumnSelect(select, selected = "", optional = false) {
  const empty = optional ? '<option value="">不使用</option>' : "";
  select.innerHTML = empty + laborState.headers.map((header) => `<option value="${escapeHtml(header)}">${escapeHtml(header)}</option>`).join("");
  select.value = selected || "";
}

function renderPreview(rows) {
  if (!rows.length) {
    labor.mappingPreview.textContent = "没有可预览的数据行。";
    return;
  }
  const headers = laborState.headers.slice(0, 6);
  labor.mappingPreview.innerHTML = `<table><thead><tr>${headers.map((header) => `<th>${escapeHtml(header)}</th>`).join("")}</tr></thead><tbody>${rows.slice(0, 4).map((row) => `<tr>${headers.map((header) => `<td>${escapeHtml(row[header] ?? "")}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}

function renderResult(run) {
  const summary = run.comparisonSummary || {};
  const metrics = [
    ["PDF人数", summary.pdfEmployeeCount],
    ["Excel人数", summary.excelEmployeeCount],
    ["PDF总工时", summary.pdfHoursTotal],
    ["Excel总工时", summary.excelHoursTotal],
    ["金额差异人数", summary.amountDiffCount],
    ["风险人数", summary.exceptionCount],
  ];
  labor.summaryGrid.innerHTML = metrics.map(([label, value]) => `<div><span>${label}</span><strong>${escapeHtml(value ?? 0)}</strong></div>`).join("");
  const rows = run.comparisonRows || [];
  renderRows(labor.amountDiffTable, rows.filter((row) => row.matchStatus === "金额差异"));
  renderRows(labor.riskTable, rows.filter((row) => row.matchStatus !== "通过" && row.matchStatus !== "金额差异"));
}

function renderRows(container, rows) {
  if (!rows.length) {
    container.textContent = "暂无数据。";
    return;
  }
  container.innerHTML = `<table><thead><tr><th>员工</th><th>状态</th><th>PDF金额</th><th>Excel金额</th><th>差异</th><th>来源</th></tr></thead><tbody>${rows.map((row) => `<tr><td>${escapeHtml(row.employeeName)}</td><td><span class="risk-pill">${escapeHtml(row.matchStatus)}</span></td><td>${formatMoney(row.pdfAmountTotal)}</td><td>${formatMoney(row.excelAmountTotal)}</td><td>${formatMoney(row.amountDelta)}</td><td>${escapeHtml(row.sourceRefs || "")}</td></tr>`).join("")}</tbody></table>`;
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

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[char]));
}
