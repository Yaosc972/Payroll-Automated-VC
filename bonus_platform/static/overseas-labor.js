const laborState = {
  run: null,
  headers: [],
  comparePollTimer: null,
};

const labor = {
  steps: document.querySelectorAll(".audit-step"),
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
  conclusionSection: document.querySelector("#conclusionSection"),
  warehouseHeading: document.querySelector("#warehouseHeading"),
  warehouseTable: document.querySelector("#warehouseTable"),
  pendingItemsSection: document.querySelector("#pendingItemsSection"),
  hoursDiffGroup: document.querySelector("#hoursDiffGroup"),
  candidateGroup: document.querySelector("#candidateGroup"),
  notInInvoiceGroup: document.querySelector("#notInInvoiceGroup"),
  extractPreviewTable: document.querySelector("#extractPreviewTable"),
  reportLink: document.querySelector("#laborReportLink"),
  toast: document.querySelector("#laborToast"),
};

bindLaborEvents();

function updateSteps(activeIndex) {
  labor.steps.forEach((step, i) => {
    step.classList.toggle("active", i === activeIndex);
    step.classList.toggle("done", i < activeIndex);
  });
}

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
    updateSteps(1);
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
    updateSteps(2);
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
    updateSteps(3);
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
  updateSteps(3);
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
      updateSteps(4);
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
  const wc = run.warehouseComparison;
  const wcSummary = wc && wc.summary;
  const totalPassed = wcSummary && wcSummary.totalPassed;

  // 渲染结论区
  renderConclusion(summary, wcSummary, run.extractionQuality);

  // 渲染仓库概览
  renderWarehouseTable(wc);

  // 渲染待处理事项分组
  const rows = run.comparisonRows || [];
  renderPendingItems(rows, run.candidateMatches || [], summary);

  // 渲染AI抽取明细
  if (totalPassed) {
    labor.extractPreviewTable.innerHTML = '<p class="empty-state-text" style="color:#16a34a">总金额一致，无需核对明细。</p>';
  } else {
    renderExtractRows(labor.extractPreviewTable, run.pdfExtractedRows || []);
  }
}

function renderConclusion(summary, wcSummary, extractionQuality) {
  const section = labor.conclusionSection;
  if (!section) return;

  const conclusionLevel = summary.conclusionLevel || "pass";
  const conclusionMessage = summary.conclusionMessage || "";
  const levelIcons = { pass: "✅", warning: "⚠️", critical: "🔴" };
  const levelLabels = { pass: "通过", warning: "需关注", critical: "需人工复核" };

  const icon = levelIcons[conclusionLevel] || "❓";
  const label = levelLabels[conclusionLevel] || conclusionLevel;

  const amountDeltaTotal = wcSummary ? (wcSummary.amountDeltaTotal || 0) : 0;
  const pdfAmountTotal = wcSummary ? Math.abs(wcSummary.pdfAmountTotal || 0) : 0;
  const excelAmountTotal = wcSummary ? Math.abs(wcSummary.excelAmountTotal || 0) : 0;
  const maxAmount = Math.max(pdfAmountTotal, excelAmountTotal, 1);
  const amountDeltaPct = (Math.abs(amountDeltaTotal) / maxAmount * 100).toFixed(2);

  const pdfCount = summary.pdfEmployeeCount || 0;
  const excelCount = summary.excelEmployeeCount || 0;
  const notInInvoice = summary.notInInvoiceCount || 0;

  section.hidden = false;
  section.className = `conclusion-section ${conclusionLevel}`;
  section.innerHTML = `
    <div class="conclusion-main">
      <span class="conclusion-icon">${icon}</span>
      <span class="conclusion-text">${escapeHtml(label)} - ${escapeHtml(conclusionMessage)}</span>
    </div>
    <div class="conclusion-details">
      <span>总金额差异: <strong>$${amountDeltaTotal.toFixed(2)} (${amountDeltaPct}%)</strong></span>
      <span>📋 本批发票覆盖 <strong>${pdfCount}</strong>人，账单共 <strong>${excelCount}</strong>人${notInInvoice > 0 ? `（<strong>${notInInvoice}</strong>人不在本批发票）` : ""}</span>
    </div>
  `;
}

function renderWarehouseTable(wc) {
  const heading = labor.warehouseHeading;
  const table = labor.warehouseTable;
  if (!heading || !table) return;
  if (!wc || !wc.rows || wc.rows.length === 0) {
    heading.hidden = true;
    table.hidden = true;
    return;
  }
  heading.hidden = false;
  table.hidden = false;

  const headers = ["仓库", "PDF金额", "Excel金额", "差异", "状态"];
  const thead = `<thead><tr>${headers.map((h) => `<th>${h}</th>`).join("")}</tr></thead>`;

  const tbody = wc.rows.map((r, idx) => {
    const hasAttribution = r.attribution && r.attribution.length > 0;
    const statusClass = r.matchStatus === "通过" ? "status-pass" : "status-fail";
    const expandIcon = hasAttribution ? "▸" : "";

    // 归因行
    const attributionRow = hasAttribution
      ? `<tr class="warehouse-attribution-row" id="wh-attr-${idx}" hidden><td colspan="5">${_renderAttribution(r.attribution)}</td></tr>`
      : (r.matchStatus !== "通过" ? `<tr class="warehouse-attribution-row" id="wh-attr-${idx}" hidden><td colspan="5"><div class="no-attribution">无显著差异员工</div></td></tr>` : "");

    return `<tr class="warehouse-main-row" ${hasAttribution || r.matchStatus !== "通过" ? `data-idx="${idx}" style="cursor:pointer"` : ""}>
      <td>${expandIcon} 仓库${escapeHtml(r.warehouseId)}</td>
      <td>$${r.pdfAmountTotal.toFixed(2)}</td>
      <td>$${r.excelAmountTotal.toFixed(2)}</td>
      <td>${r.amountDelta >= 0 ? "+" : ""}$${r.amountDelta.toFixed(2)}</td>
      <td style="color:${r.matchStatus === "通过" ? "#16a34a" : "#dc2626"};font-weight:600">${escapeHtml(r.matchStatus)}</td>
    </tr>${attributionRow}`;
  }).join("");

  table.innerHTML = `<table class="audit-data-table">${thead}<tbody>${tbody}</tbody></table>`;

  // 差异>= $1 的仓库自动展开
  wc.rows.forEach((r, idx) => {
    if (Math.abs(r.amountDelta) >= 1) {
      const attrRow = document.getElementById(`wh-attr-${idx}`);
      if (attrRow) {
        attrRow.hidden = false;
        const mainRow = table.querySelector(`.warehouse-main-row[data-idx="${idx}"]`);
        if (mainRow) {
          const icon = mainRow.querySelector("td:first-child");
          if (icon) icon.textContent = icon.textContent.replace("▸", "▾");
        }
      }
    }
  });

  // Bind expand/collapse
  table.querySelectorAll(".warehouse-main-row[data-idx]").forEach((row) => {
    row.addEventListener("click", () => {
      const idx = row.dataset.idx;
      const detail = document.getElementById(`wh-attr-${idx}`);
      if (!detail) return;
      const expanded = !detail.hidden;
      detail.hidden = expanded;
      const icon = row.querySelector("td:first-child");
      if (icon) icon.textContent = icon.textContent.replace(expanded ? "▾" : "▸", expanded ? "▸" : "▾");
    });
  });
}

function _renderAttribution(attribution) {
  if (!attribution || attribution.length === 0) {
    return '<div class="no-attribution">无显著差异员工</div>';
  }

  const rows = attribution.map(item => {
    const isOther = item.employeeName.startsWith("其他");
    const nameClass = isOther ? "attribution-name attribution-other" : "attribution-name";
    const deltaClass = item.delta >= 0 ? "attribution-delta positive" : "attribution-delta negative";
    const amountsHtml = item.pdfAmount != null
      ? `<span>PDF: $${item.pdfAmount.toFixed(2)}</span><span>Excel: $${item.excelAmount.toFixed(2)}</span>`
      : "";

    return `<div class="attribution-row">
      <span class="${nameClass}">${escapeHtml(item.employeeName)}</span>
      <span class="attribution-amounts">${amountsHtml}</span>
      <span class="${deltaClass}">${item.delta >= 0 ? "+" : ""}$${item.delta.toFixed(2)}</span>
    </div>`;
  }).join("");

  return `<div class="warehouse-attribution">${rows}</div>`;
}

function renderPendingItems(rows, candidateMatches, summary) {
  const section = labor.pendingItemsSection;
  if (!section) return;

  // 分组数据
  const hoursDiffRows = rows.filter(row => row.matchStatus === "工时不一致");
  const notInInvoiceRows = rows.filter(row => row.matchStatus === "Excel有PDF无");

  // 判断是否有待处理事项
  const hasItems = hoursDiffRows.length > 0 || candidateMatches.length > 0 || notInInvoiceRows.length > 0;
  section.hidden = !hasItems;
  if (!hasItems) return;

  // 渲染工时不一致组
  _renderPendingGroup(labor.hoursDiffGroup, hoursDiffRows, _renderHoursDiffTable);

  // 渲染姓名格式差异组
  _renderPendingGroup(labor.candidateGroup, candidateMatches, _renderCandidateTable);

  // 渲染不在本批发票组
  _renderPendingGroup(labor.notInInvoiceGroup, notInInvoiceRows, _renderNotInInvoiceTable);
}

function _renderPendingGroup(groupEl, items, renderFn) {
  if (!groupEl) return;
  if (!items || items.length === 0) {
    groupEl.hidden = true;
    return;
  }
  groupEl.hidden = false;
  const countEl = groupEl.querySelector(".group-count");
  if (countEl) countEl.textContent = `${items.length}人`;

  const contentEl = groupEl.querySelector(".group-content");
  if (contentEl) {
    contentEl.innerHTML = renderFn(items);
  }

  // 绑定折叠/展开事件
  const header = groupEl.querySelector(".group-header");
  if (header && !header._bound) {
    header._bound = true;
    header.addEventListener("click", () => {
      const icon = header.querySelector(".expand-icon");
      const content = groupEl.querySelector(".group-content");
      if (!content) return;
      const expanded = !content.hidden;
      content.hidden = expanded;
      if (icon) icon.textContent = expanded ? "▸" : "▾";
    });
  }
}

function _renderHoursDiffTable(rows) {
  if (!rows.length) return "";
  const visible = rows.slice(0, 40);
  return `<table class="audit-data-table">
    <thead><tr><th>员工</th><th>PDF工时</th><th>Excel工时</th><th>工时差</th><th>PDF金额</th><th>Excel金额</th></tr></thead>
    <tbody>${visible.map(row => `<tr>
      <td>${escapeHtml(row.employeeName)}</td>
      <td>${formatHours(row.pdfHoursTotal)}</td>
      <td>${formatHours(row.excelHoursTotal)}</td>
      <td>${formatHours(row.hoursDelta)}</td>
      <td>${formatMoney(row.pdfAmountTotal)}</td>
      <td>${formatMoney(row.excelAmountTotal)}</td>
    </tr>`).join("")}</tbody>
  </table>${rows.length > visible.length ? `<p class="table-note">仅展示前 ${visible.length} 条。</p>` : ""}`;
}

function _renderCandidateTable(rows) {
  if (!rows.length) return "";
  const visible = rows.slice(0, 40);
  return `<table class="audit-data-table">
    <thead><tr><th>PDF员工</th><th>Excel员工</th><th>相似度</th><th>PDF金额</th><th>Excel金额</th><th>金额差</th></tr></thead>
    <tbody>${visible.map(row => `<tr>
      <td>${escapeHtml(row.pdfEmployeeName)}</td>
      <td>${escapeHtml(row.excelEmployeeName)}</td>
      <td>${formatPercent(row.nameSimilarity)}</td>
      <td>${formatMoney(row.pdfAmountTotal)}</td>
      <td>${formatMoney(row.excelAmountTotal)}</td>
      <td>${formatMoney(row.amountDelta)}</td>
    </tr>`).join("")}</tbody>
  </table>${rows.length > visible.length ? `<p class="table-note">仅展示前 ${visible.length} 条，完整候选请下载报告查看。</p>` : ""}`;
}

function _renderNotInInvoiceTable(rows) {
  if (!rows.length) return "";
  const visible = rows.slice(0, 40);
  return `<table class="audit-data-table">
    <thead><tr><th>员工</th><th>Excel金额</th><th>Excel工时</th></tr></thead>
    <tbody>${visible.map(row => `<tr>
      <td>${escapeHtml(row.employeeName)}</td>
      <td>${formatMoney(row.excelAmountTotal)}</td>
      <td>${formatHours(row.excelHoursTotal)}</td>
    </tr>`).join("")}</tbody>
  </table>${rows.length > visible.length ? `<p class="table-note">仅展示前 ${visible.length} 条。</p>` : ""}`;
}

function _renderWarehouseEmployees(rows) {
  if (!rows.length) return '<p class="empty-state-text">无员工明细。</p>';
  return `<table class="audit-data-table" style="margin-top:8px"><thead><tr><th>员工</th><th>状态</th><th>PDF金额</th><th>Excel金额</th><th>差异</th><th>PDF工时</th><th>Excel工时</th><th>工时差</th></tr></thead><tbody>${rows.map((row) => {
    const sc = row.matchStatus === "通过" ? "status-pass" : row.matchStatus === "金额差异" ? "status-diff" : "status-warn";
    return `<tr><td>${escapeHtml(row.employeeName)}</td><td><span class="risk-pill ${sc}">${escapeHtml(row.matchStatus)}</span></td><td>${formatMoney(row.pdfAmountTotal)}</td><td>${formatMoney(row.excelAmountTotal)}</td><td>${formatMoney(row.amountDelta)}</td><td>${formatHours(row.pdfHoursTotal)}</td><td>${formatHours(row.excelHoursTotal)}</td><td>${formatHours(row.hoursDelta)}</td></tr>`;
  }).join("")}</tbody></table>`;
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
