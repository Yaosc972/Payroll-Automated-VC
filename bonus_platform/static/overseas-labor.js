const laborState = {
  run: null,
  headers: [],
  comparePollTimer: null,
  pollRetryCount: 0,
  pollMaxRetries: 200,  // 200 × 3s = 10 分钟
  currentStep: 1,
};

// ── Element references ──
const labor = {
  // KPI cards
  kpiTotal: document.querySelector("#kpiTotalVal"),
  kpiMatched: document.querySelector("#kpiMatchedVal"),
  kpiVariance: document.querySelector("#kpiVarianceVal"),
  kpiUnmatched: document.querySelector("#kpiUnmatchedVal"),

  // Run badge
  chromeRunBadge: document.querySelector("#chromeRunBadge"),
  chromeRunLabel: document.querySelector("#chromeRunLabel"),

  // Form elements
  supplierName: document.querySelector("#supplierName"),
  periodStart: document.querySelector("#periodStart"),
  periodEnd: document.querySelector("#periodEnd"),
  currency: document.querySelector("#currency"),
  createLaborRun: document.querySelector("#createLaborRun"),
  createStatus: document.querySelector("#createStatus"),

  // File upload
  pdfFiles: document.querySelector("#pdfFiles"),
  pdfFileName: document.querySelector("#pdfFileName"),
  workbookFile: document.querySelector("#workbookFile"),
  workbookFileName: document.querySelector("#workbookFileName"),
  uploadLaborFiles: document.querySelector("#uploadLaborFiles"),
  uploadStatus: document.querySelector("#uploadStatus"),

  // Field mapping
  loadSheets: document.querySelector("#loadSheets"),
  saveMapping: document.querySelector("#saveMapping"),
  sheetSelect: document.querySelector("#sheetSelect"),
  employeeIdColumn: document.querySelector("#employeeIdColumn"),
  nameColumn: document.querySelector("#nameColumn"),
  hoursColumn: document.querySelector("#hoursColumn"),
  amountColumn: document.querySelector("#amountColumn"),
  currencyColumn: document.querySelector("#currencyColumn"),
  mappingPreview: document.querySelector("#mappingPreview"),

  // Results
  extractCompare: document.querySelector("#extractCompare"),
  compareStatus: document.querySelector("#compareStatus"),
  employeeReconSection: document.querySelector("#employeeReconSection"),
  employeeReconTable: document.querySelector("#employeeReconTable"),
  diagnosticsFold: document.querySelector("#diagnosticsFold"),
  qualityAlert: document.querySelector("#qualityAlert"),
  conclusionSection: document.querySelector("#conclusionSection"),
  warehouseSection: document.querySelector("#warehouseSection"),
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

// ── Initialize ──
bindLaborEvents();
listenKpiFilters();

function listenKpiFilters() {
  document.addEventListener('kpi-filter', (e) => {
    filterPendingItems(e.detail);
  });
}

function filterPendingItems(filter) {
  const section = labor.pendingItemsSection;
  if (!section || section.hidden) return;

  if (filter === 'all') {
    section.querySelectorAll('.pending-group').forEach(group => {
      if (group.dataset.count > 0) group.hidden = false;
    });
  } else if (filter === 'variance') {
    section.querySelectorAll('.pending-group').forEach(group => {
      group.hidden = group.id !== 'hoursDiffGroup';
    });
  } else if (filter === 'unmatched') {
    section.querySelectorAll('.pending-group').forEach(group => {
      group.hidden = group.id !== 'notInInvoiceGroup';
    });
  } else if (filter === 'matched') {
    section.querySelectorAll('.pending-group').forEach(group => {
      group.hidden = true;
    });
  }
}

function bindLaborEvents() {
  labor.createLaborRun.addEventListener("click", createRun);
  labor.uploadLaborFiles.addEventListener("click", uploadFiles);
  labor.loadSheets.addEventListener("click", loadSheets);
  labor.sheetSelect.addEventListener("change", loadFieldSuggestions);
  labor.saveMapping.addEventListener("click", saveMapping);
  labor.extractCompare.addEventListener("click", extractAndCompare);
}

async function createRun() {
  const supplierName = labor.supplierName.value.trim();
  const periodStart = labor.periodStart.value.trim();
  const periodEnd = labor.periodEnd.value.trim();
  const currency = (labor.currency.value.trim() || "USD").toUpperCase();

  if (!supplierName) {
    labor.supplierName.focus();
    setText(labor.createStatus, "请填写供应商名称。", true);
    return toast("请填写供应商名称。");
  }
  if (!periodStart || !periodEnd) {
    (periodStart ? labor.periodEnd : labor.periodStart).focus();
    setText(labor.createStatus, "请填写账期开始和结束日期。", true);
    return toast("请填写账期开始和结束日期。");
  }
  if (periodEnd < periodStart) {
    labor.periodEnd.focus();
    setText(labor.createStatus, "账期结束日期不能早于开始日期。", true);
    return toast("账期结束日期不能早于开始日期。");
  }

  setText(labor.createStatus, "正在创建批次...");
  labor.createLaborRun.disabled = true;
  try {
    const run = await requestJson("/api/labor/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        supplier_name: supplierName,
        period_start: periodStart,
        period_end: periodEnd,
        currency,
      }),
    });
    laborState.run = run;
    setText(labor.createStatus, `批次已创建：${run.id}`);

    // Update run badge
    if (labor.chromeRunBadge) {
      labor.chromeRunBadge.hidden = false;
      labor.chromeRunLabel.textContent = `批次 #${run.id.slice(0, 8)}`;
    }

    toast("劳务核对批次已创建。");
    advanceWizardStep("2");
  } catch (error) {
    setText(labor.createStatus, error.message, true);
    toast(error.message);
  } finally {
    labor.createLaborRun.disabled = false;
  }
}

async function uploadFiles() {
  if (!laborState.run) return toast("请先创建批次。");
  if (!labor.pdfFiles.files.length || !labor.workbookFile.files.length)
    return toast("请上传 PDF 发票和 Excel 账单。");

  const form = new FormData();
  Array.from(labor.pdfFiles.files).forEach((file) => form.append("pdf_files", file));
  Array.from(labor.workbookFile.files).forEach((file) => form.append("workbook_files", file));

  setText(labor.uploadStatus, "正在上传文件...");
  labor.uploadLaborFiles.disabled = true;
  try {
    laborState.run = await requestJson(`/api/labor/runs/${laborState.run.id}/files`, {
      method: "POST",
      body: form,
    });
    setText(labor.uploadStatus, "文件已上传，可以读取工作表。");
    toast("文件上传完成。");
    advanceWizardStep("3");
  } catch (error) {
    setText(labor.uploadStatus, error.message, true);
    toast(error.message);
  } finally {
    labor.uploadLaborFiles.disabled = false;
  }
}

async function loadSheets() {
  if (!laborState.run) return toast("请先创建并上传文件。");
  try {
    const data = await requestJson(`/api/labor/runs/${laborState.run.id}/workbook-sheets`);
    labor.sheetSelect.innerHTML = data.sheets
      .map((sheet) => `<option value="${escapeHtml(sheet)}">${escapeHtml(sheet)}</option>`)
      .join("");
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
    renderMappingPreview(data.previewRows || []);
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
    toast("字段映射已确认，可以开始抽取比对。");
    if (typeof window.closeDrawer === "function") window.closeDrawer();
  } catch (error) {
    toast(error.message);
  }
}

function advanceWizardStep(step) {
  const stepButton = document.querySelector(`.wz-step[data-step="${step}"]`);
  if (stepButton) stepButton.click();
}

function clearResults() {
  if (labor.conclusionSection) {
    labor.conclusionSection.hidden = true;
    labor.conclusionSection.innerHTML = "";
  }
  if (labor.employeeReconSection) {
    labor.employeeReconSection.hidden = true;
    if (labor.employeeReconTable) labor.employeeReconTable.innerHTML = "";
  }
  if (labor.diagnosticsFold) labor.diagnosticsFold.hidden = true;
  if (labor.warehouseSection) labor.warehouseSection.hidden = true;
  if (labor.warehouseHeading) labor.warehouseHeading.hidden = true;
  if (labor.warehouseTable) {
    labor.warehouseTable.hidden = true;
    labor.warehouseTable.innerHTML = "";
  }
  if (labor.pendingItemsSection) labor.pendingItemsSection.hidden = true;
  if (labor.qualityAlert) {
    labor.qualityAlert.hidden = true;
    labor.qualityAlert.innerHTML = "";
  }
  if (labor.extractPreviewTable) {
    labor.extractPreviewTable.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">
          <svg width="40" height="40" viewBox="0 0 40 40" fill="none"><rect x="6" y="8" width="28" height="24" rx="4" stroke="#D2D2D7" stroke-width="1.5"/><path d="M12 16h16M12 20h10M12 24h7" stroke="#D2D2D7" stroke-width="1.5" stroke-linecap="round"/></svg>
        </div>
        <p class="empty-title">暂无抽取数据</p>
        <p class="empty-desc">点击「抽取并比对」开始核对</p>
      </div>
    `;
  }
  labor.reportLink.classList.add("disabled");
  labor.reportLink.setAttribute("aria-disabled", "true");
  labor.reportLink.href = "#";

  // Reset KPI
  if (labor.kpiTotal) labor.kpiTotal.textContent = "—";
  if (labor.kpiMatched) labor.kpiMatched.textContent = "—";
  if (labor.kpiVariance) labor.kpiVariance.textContent = "—";
  if (labor.kpiUnmatched) labor.kpiUnmatched.textContent = "—";
}

async function extractAndCompare() {
  if (!laborState.run) return toast("请先创建批次。");
  stopComparePolling();
  clearResults();

  setText(labor.compareStatus, "已提交后台抽取，正在等待结果…");
  labor.extractCompare.disabled = true;
  laborState.pollRetryCount = 0;

  try {
    laborState.run = await requestJson(`/api/labor/runs/${laborState.run.id}/extract-and-compare`, {
      method: "POST",
    });
    setText(labor.compareStatus, "后台抽取中，页面会自动刷新结果…");
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
  laborState.pollRetryCount++;
  if (laborState.pollRetryCount > laborState.pollMaxRetries) {
    stopComparePolling();
    labor.extractCompare.disabled = false;
    setText(labor.compareStatus, "抽取超时（10分钟），请重新点击「抽取并比对」重试。", true);
    toast("抽取超时。");
    return;
  }
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
    // 显示实时进度（stage 字段）
    const stage = run.stage || "抽取中";
    const elapsed = laborState.pollRetryCount * 3;
    setText(labor.compareStatus, `${stage}... (${elapsed}s)`);
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
  select.innerHTML =
    empty +
    laborState.headers
      .map((header) => `<option value="${escapeHtml(header)}">${escapeHtml(header)}</option>`)
      .join("");
  select.value = selected || "";
}

function renderMappingPreview(rows) {
  if (!rows.length) {
    labor.mappingPreview.innerHTML = '<p class="empty-state-text">暂无预览数据。</p>';
    return;
  }
  const headers = laborState.headers.slice(0, 6);
  labor.mappingPreview.innerHTML = `<table><thead><tr>${headers
    .map((header) => `<th>${escapeHtml(header)}</th>`)
    .join("")}</tr></thead><tbody>${rows
    .slice(0, 3)
    .map(
      (row) =>
        `<tr>${headers.map((header) => `<td>${escapeHtml(row[header] ?? "")}</td>`).join("")}</tr>`
    )
    .join("")}</tbody></table>`;
}

function renderResult(run) {
  const summary = run.comparisonSummary || {};
  const wc = run.warehouseComparison;
  const wcSummary = wc && wc.summary;
  const totalPassed = wcSummary && wcSummary.totalPassed;
  const rows = run.comparisonRows || [];

  // Update KPI cards
  updateKpiCards(summary, rows, wcSummary, run.candidateMatches || []);

  // 1. 结论 — 用户第一眼看到
  renderConclusion(summary, wcSummary, run.extractionQuality);

  // 2. 全员对账明细 — 核心信息，有差异排前面
  renderEmployeeReconTable(rows, run.candidateMatches || [], summary, totalPassed, wcSummary);

  // 3. 质量诊断 + 仓库概览 — 折叠在底部
  renderQualityAlert(run.extractionQuality, run.reconciliationDiagnostics);
  renderWarehouseTable(wc);
  const hasDiagnostics = (labor.qualityAlert && !labor.qualityAlert.hidden) || (wc && wc.rows && wc.rows.length > 0);
  if (labor.diagnosticsFold) {
    labor.diagnosticsFold.hidden = !hasDiagnostics;
  }

  // 4. 待处理事项
  renderPendingItems(rows, run.candidateMatches || [], summary);

  // 5. 抽取明细 / 通过证据
  if (totalPassed) {
    renderPassEvidence(labor.extractPreviewTable, summary, wcSummary);
  } else {
    renderExtractRows(labor.extractPreviewTable, run.pdfExtractedRows || []);
  }
}

function updateKpiCards(summary, rows, wcSummary, candidateMatches = []) {
  const pdfCount = summary.pdfEmployeeCount || 0;
  const excelCount = summary.excelEmployeeCount || 0;
  const skippedEmployeeDrilldown = wcSummary && wcSummary.totalPassed && !rows.length;
  const amountDiffCount = summary.amountDiffCount || 0;
  const notInInvoiceCount = summary.notInInvoiceCount || 0;
  const pdfAmount = wcSummary ? wcSummary.pdfAmountTotal || 0 : summary.pdfAmountTotal || 0;
  const excelAmount = wcSummary ? wcSummary.excelAmountTotal || 0 : summary.excelAmountTotal || 0;
  const amountDelta = wcSummary ? wcSummary.amountDeltaTotal || 0 : summary.amountDeltaTotal || 0;

  // Calculate cleared matches
  const clearedCount = rows.filter(
    (r) => r.matchStatus === "通过" || r.matchStatus === "金额一致"
  ).length;
  const reviewCount =
    amountDiffCount +
    notInInvoiceCount +
    (summary.hoursRiskCount || summary.hoursDiffCount || 0) +
    (candidateMatches ? candidateMatches.length : 0);

  if (labor.kpiTotal) labor.kpiTotal.textContent = `$${formatMoney(pdfAmount)}`;
  if (labor.kpiMatched) labor.kpiMatched.textContent = `$${formatMoney(excelAmount)}`;
  if (labor.kpiVariance) labor.kpiVariance.textContent = `${amountDelta >= 0 ? "+" : "-"}$${formatMoney(Math.abs(amountDelta))}`;
  if (labor.kpiUnmatched) labor.kpiUnmatched.textContent = `${reviewCount} 项`;

  const totalCard = document.querySelector("#kpiTotal .kpi-sub");
  const matchedCard = document.querySelector("#kpiMatched .kpi-sub");
  const varianceCard = document.querySelector("#kpiVariance .kpi-sub");
  const unmatchedCard = document.querySelector("#kpiUnmatched .kpi-sub");
  if (totalCard) totalCard.textContent = skippedEmployeeDrilldown ? "总额已核对" : `PDF ${pdfCount} 人`;
  if (matchedCard) matchedCard.textContent = skippedEmployeeDrilldown ? "未下钻员工明细" : `Excel ${excelCount} 人`;
  if (varianceCard) varianceCard.textContent = `容差 $0.10`;
  if (unmatchedCard) unmatchedCard.textContent = clearedCount ? `${clearedCount} 人已清账` : "异常队列";
}

function renderConclusion(summary, wcSummary, extractionQuality) {
  const section = labor.conclusionSection;
  if (!section) return;

  const conclusionLevel = summary.conclusionLevel || "pass";
  const conclusionMessage = summary.conclusionMessage || "";
  const levelLabels = { pass: "通过", warning: "需关注", critical: "需人工复核" };

  const label = levelLabels[conclusionLevel] || conclusionLevel;

  const amountDeltaTotal = wcSummary ? wcSummary.amountDeltaTotal || 0 : 0;
  const pdfAmountTotal = wcSummary ? Math.abs(wcSummary.pdfAmountTotal || 0) : 0;
  const excelAmountTotal = wcSummary ? Math.abs(wcSummary.excelAmountTotal || 0) : 0;
  const maxAmount = Math.max(pdfAmountTotal, excelAmountTotal, 1);
  const amountDeltaPct = ((Math.abs(amountDeltaTotal) / maxAmount) * 100).toFixed(2);

  const pdfCount = summary.pdfEmployeeCount || 0;
  const excelCount = summary.excelEmployeeCount || 0;
  const notInInvoice = summary.notInInvoiceCount || 0;

  section.hidden = false;
  section.className = `conclusion-section ${conclusionLevel}`;
  section.innerHTML = `
    <div class="conclusion-main">
      <span class="conclusion-icon" aria-hidden="true"></span>
      <span class="conclusion-text">${escapeHtml(label)} · ${escapeHtml(conclusionMessage)}</span>
    </div>
    <div class="conclusion-details">
      <span>总金额差异: <strong>$${amountDeltaTotal.toFixed(2)} (${amountDeltaPct}%)</strong></span>
      <span>本批发票覆盖 <strong>${pdfCount}</strong>人，账单共 <strong>${excelCount}</strong>人${
        notInInvoice > 0 ? `（<strong>${notInInvoice}</strong>人不在本批发票）` : ""
      }</span>
    </div>
  `;
}

function renderEmployeeReconTable(rows, candidateMatches, summary, totalPassed, wcSummary) {
  const section = labor.employeeReconSection;
  const container = labor.employeeReconTable;
  if (!section || !container) return;

  // 总额通过且无员工明细时，显示通过证据
  if (totalPassed && !rows.length) {
    section.hidden = false;
    renderPassEvidence(container, summary, wcSummary);
    return;
  }

  if (!rows.length && !candidateMatches.length) {
    section.hidden = true;
    return;
  }
  section.hidden = false;

  // 合并：精确匹配行 + 模糊匹配候选
  const allRows = [];
  rows.forEach(r => {
    const delta = Math.abs(r.amountDelta || 0);
    const hasVariance = r.matchStatus !== "通过" && r.matchStatus !== "金额一致";
    allRows.push({
      name: r.employeeName || "",
      status: r.matchStatus || "",
      pdfAmount: r.pdfAmountTotal || 0,
      excelAmount: r.excelAmountTotal || 0,
      amountDelta: r.amountDelta || 0,
      pdfHours: r.pdfHoursTotal || 0,
      excelHours: r.excelHoursTotal || 0,
      hoursDelta: r.hoursDelta || 0,
      hasVariance,
      sortWeight: hasVariance ? delta : -1,
      isCandidate: false,
    });
  });
  candidateMatches.forEach(c => {
    const delta = Math.abs(c.amountDelta || 0);
    allRows.push({
      name: `${c.pdfEmployeeName || ""} → ${c.excelEmployeeName || ""}`,
      status: "姓名模糊匹配",
      pdfAmount: c.pdfAmountTotal || 0,
      excelAmount: c.excelAmountTotal || 0,
      amountDelta: c.amountDelta || 0,
      pdfHours: 0,
      excelHours: 0,
      hoursDelta: 0,
      hasVariance: true,
      sortWeight: delta,
      isCandidate: true,
      similarity: c.nameSimilarity,
    });
  });

  // 排序：有差异的在前（按差异绝对值降序），无差异在后
  allRows.sort((a, b) => b.sortWeight - a.sortWeight);

  const varianceCount = allRows.filter(r => r.hasVariance).length;
  const totalCount = allRows.length;

  const headers = ["员工", "状态", "PDF金额", "Excel金额", "差异", "PDF工时", "Excel工时", "工时差异"];
  const thead = `<thead><tr>${headers.map(h => `<th>${h}</th>`).join("")}</tr></thead>`;
  const visible = allRows.slice(0, 100);

  const tbody = visible.map(r => {
    const rowClass = r.hasVariance ? "recon-row variance" : "recon-row matched";
    const statusStyle = r.hasVariance ? "color:#FF3B30;font-weight:600" : "color:#34C759";
    const deltaStyle = Math.abs(r.amountDelta) > 0.01
      ? (r.amountDelta > 0 ? "color:#FF9500" : "color:#FF3B30")
      : "color:#8E8E93";
    const similarityTag = r.similarity != null ? ` <small>(${formatPercent(r.similarity)})</small>` : "";
    return `<tr class="${rowClass}">
      <td>${escapeHtml(r.name)}${similarityTag}</td>
      <td style="${statusStyle}">${escapeHtml(r.status)}</td>
      <td>$${formatMoney(r.pdfAmount)}</td>
      <td>$${formatMoney(r.excelAmount)}</td>
      <td style="${deltaStyle}">${r.amountDelta >= 0 ? "+" : ""}$${formatMoney(Math.abs(r.amountDelta))}</td>
      <td>${formatHours(r.pdfHours)}</td>
      <td>${formatHours(r.excelHours)}</td>
      <td>${formatHours(r.hoursDelta)}</td>
    </tr>`;
  }).join("");

  container.innerHTML = `
    <div class="recon-summary-bar">
      <span>共 <strong>${totalCount}</strong> 人</span>
      ${varianceCount > 0 ? `<span class="recon-variance-badge">${varianceCount} 人有差异</span>` : '<span class="recon-ok-badge">全部一致</span>'}
    </div>
    <table>${thead}<tbody>${tbody}</tbody></table>
    ${allRows.length > visible.length ? `<p class="table-note">仅展示前 ${visible.length} 条，完整明细请下载报告。</p>` : ""}
  `;
}

function renderPassEvidence(container, summary, wcSummary) {
  const amountDelta = wcSummary ? wcSummary.amountDeltaTotal || 0 : 0;
  const pdfAmount = wcSummary ? wcSummary.pdfAmountTotal || 0 : 0;
  const excelAmount = wcSummary ? wcSummary.excelAmountTotal || 0 : 0;
  const pdfCount = summary.pdfEmployeeCount || 0;
  const excelCount = summary.excelEmployeeCount || 0;
  container.innerHTML = `
    <div class="pass-evidence">
      <div class="pass-evidence-copy">
        <span class="decision-badge">总额核对通过</span>
        <h3>本批发票与账单金额在容差内一致</h3>
        <p>系统已先核对 PDF 发票总额与 Excel 账单总额。差额未超过 $0.10，因此无需进入员工级逐项追差；如需留档，可下载完整报告。</p>
      </div>
      <div class="pass-evidence-grid">
        <div>
          <span>PDF 发票总额</span>
          <strong>$${formatMoney(pdfAmount)}</strong>
          <small>${pdfCount} 人</small>
        </div>
        <div>
          <span>Excel 账单总额</span>
          <strong>$${formatMoney(excelAmount)}</strong>
          <small>${excelCount} 人</small>
        </div>
        <div>
          <span>金额差额</span>
          <strong>${amountDelta >= 0 ? "+" : "-"}$${formatMoney(Math.abs(amountDelta))}</strong>
          <small>容差 $0.10</small>
        </div>
      </div>
    </div>
  `;
}

function renderWarehouseTable(wc) {
  const section = labor.warehouseSection;
  const heading = labor.warehouseHeading;
  const table = labor.warehouseTable;
  if (!heading || !table || !section) return;
  if (!wc || !wc.rows || wc.rows.length === 0) {
    section.hidden = true;
    return;
  }
  section.hidden = false;

  const headers = ["仓库", "PDF金额", "Excel金额", "差异", "状态"];
  const thead = `<thead><tr>${headers.map((h) => `<th>${h}</th>`).join("")}</tr></thead>`;

  const tbody = wc.rows
    .map((r, idx) => {
      const hasAttribution = r.attribution && r.attribution.length > 0;
      const expandIcon = hasAttribution ? "▸" : "";

      const attributionRow = hasAttribution
        ? `<tr class="warehouse-attribution-row" id="wh-attr-${idx}" hidden><td colspan="5">${_renderAttribution(
            r.attribution
          )}</td></tr>`
        : r.matchStatus !== "通过"
        ? `<tr class="warehouse-attribution-row" id="wh-attr-${idx}" hidden><td colspan="5"><div class="no-attribution">无显著差异员工</div></td></tr>`
        : "";

      return `<tr class="warehouse-main-row" ${
        hasAttribution || r.matchStatus !== "通过" ? `data-idx="${idx}" style="cursor:pointer"` : ""
      }>
      <td>${expandIcon} 仓库${escapeHtml(r.warehouseId)}</td>
      <td>$${r.pdfAmountTotal.toFixed(2)}</td>
      <td>$${r.excelAmountTotal.toFixed(2)}</td>
      <td>${r.amountDelta >= 0 ? "+" : ""}$${r.amountDelta.toFixed(2)}</td>
      <td style="color:${
        r.matchStatus === "通过" ? "#34C759" : "#FF3B30"
      };font-weight:600">${escapeHtml(r.matchStatus)}</td>
    </tr>${attributionRow}`;
    })
    .join("");

  table.innerHTML = `<table>${thead}<tbody>${tbody}</tbody></table>`;

  // Auto-expand warehouses with difference >= $1
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
      if (icon)
        icon.textContent = icon.textContent.replace(expanded ? "▾" : "▸", expanded ? "▸" : "▾");
    });
  });
}

function _renderAttribution(attribution) {
  if (!attribution || attribution.length === 0) {
    return '<div class="no-attribution">无显著差异员工</div>';
  }

  const rows = attribution
    .map((item) => {
      const isOther = item.employeeName.startsWith("其他");
      const nameClass = isOther ? "attribution-name attribution-other" : "attribution-name";
      const deltaClass = item.delta >= 0 ? "attribution-delta positive" : "attribution-delta negative";
      const amountsHtml =
        item.pdfAmount != null
          ? `<span>PDF: $${item.pdfAmount.toFixed(2)}</span><span>Excel: $${item.excelAmount.toFixed(
              2
            )}</span>`
          : "";

      return `<div class="attribution-row">
      <span class="${nameClass}">${escapeHtml(item.employeeName)}</span>
      <span class="attribution-amounts">${amountsHtml}</span>
      <span class="${deltaClass}">${item.delta >= 0 ? "+" : ""}$${item.delta.toFixed(2)}</span>
    </div>`;
    })
    .join("");

  return `<div class="warehouse-attribution">${rows}</div>`;
}

function renderPendingItems(rows, candidateMatches, summary) {
  const section = labor.pendingItemsSection;
  if (!section) return;

  // Group data
  const hoursDiffRows = rows.filter(
    (row) => row.matchStatus === "工时不一致" || (row.riskFlags || []).includes("工时需复核")
  );
  const notInInvoiceRows = rows.filter((row) => row.matchStatus === "Excel有PDF无");

  // Check if there are pending items
  const hasItems = hoursDiffRows.length > 0 || candidateMatches.length > 0 || notInInvoiceRows.length > 0;
  section.hidden = !hasItems;
  if (!hasItems) return;

  // Render groups
  _renderPendingGroup(labor.hoursDiffGroup, hoursDiffRows, _renderHoursDiffTable);
  _renderPendingGroup(labor.candidateGroup, candidateMatches, _renderCandidateTable);
  _renderPendingGroup(labor.notInInvoiceGroup, notInInvoiceRows, _renderNotInInvoiceTable);
}

function _renderPendingGroup(groupEl, items, renderFn) {
  if (!groupEl) return;
  if (!items || items.length === 0) {
    groupEl.hidden = true;
    groupEl.dataset.count = 0;
    return;
  }
  groupEl.hidden = false;
  groupEl.dataset.count = items.length;
  const countEl = groupEl.querySelector(".group-count");
  if (countEl) countEl.textContent = `${items.length}人`;

  const contentEl = groupEl.querySelector(".group-content");
  if (contentEl) {
    contentEl.innerHTML = renderFn(items);
  }

  // Bind fold/expand events
  const header = groupEl.querySelector(".group-header");
  if (header && !header._bound) {
    header._bound = true;
    header.addEventListener("click", () => {
      const icon = header.querySelector(".expand-icon");
      const content = groupEl.querySelector(".group-content");
      if (!content) return;
      const expanded = !content.hidden;
      content.hidden = expanded;
      header.setAttribute("aria-expanded", String(!expanded));
      if (icon) icon.textContent = expanded ? "▸" : "▾";
    });
  }
}

function _renderHoursDiffTable(rows) {
  if (!rows.length) return "";
  const visible = rows.slice(0, 40);
  return `<table>
    <thead><tr><th>员工</th><th>PDF工时</th><th>Excel工时</th><th>工时差</th><th>PDF金额</th><th>Excel金额</th></tr></thead>
    <tbody>${visible
      .map(
        (row) => `<tr>
      <td>${escapeHtml(row.employeeName)}</td>
      <td>${formatHours(row.pdfHoursTotal)}</td>
      <td>${formatHours(row.excelHoursTotal)}</td>
      <td>${formatHours(row.hoursDelta)}</td>
      <td>${formatMoney(row.pdfAmountTotal)}</td>
      <td>${formatMoney(row.excelAmountTotal)}</td>
    </tr>`
      )
      .join("")}</tbody>
  </table>${
    rows.length > visible.length
      ? `<p class="table-note">仅展示前 ${visible.length} 条。</p>`
      : ""
  }`;
}

function _renderCandidateTable(rows) {
  if (!rows.length) return "";
  const visible = rows.slice(0, 40);
  return `<table>
    <thead><tr><th>PDF员工</th><th>Excel员工</th><th>相似度</th><th>PDF金额</th><th>Excel金额</th><th>金额差</th></tr></thead>
    <tbody>${visible
      .map(
        (row) => `<tr>
      <td>${escapeHtml(row.pdfEmployeeName)}</td>
      <td>${escapeHtml(row.excelEmployeeName)}</td>
      <td>${formatPercent(row.nameSimilarity)}</td>
      <td>${formatMoney(row.pdfAmountTotal)}</td>
      <td>${formatMoney(row.excelAmountTotal)}</td>
      <td>${formatMoney(row.amountDelta)}</td>
    </tr>`
      )
      .join("")}</tbody>
  </table>${
    rows.length > visible.length
      ? `<p class="table-note">仅展示前 ${visible.length} 条，完整候选请下载报告查看。</p>`
      : ""
  }`;
}

function _renderNotInInvoiceTable(rows) {
  if (!rows.length) return "";
  const visible = rows.slice(0, 40);
  return `<table>
    <thead><tr><th>员工</th><th>Excel金额</th><th>Excel工时</th></tr></thead>
    <tbody>${visible
      .map(
        (row) => `<tr>
      <td>${escapeHtml(row.employeeName)}</td>
      <td>${formatMoney(row.excelAmountTotal)}</td>
      <td>${formatHours(row.excelHoursTotal)}</td>
    </tr>`
      )
      .join("")}</tbody>
  </table>${
    rows.length > visible.length
      ? `<p class="table-note">仅展示前 ${visible.length} 条。</p>`
      : ""
  }`;
}

function renderQualityAlert(quality, diagnostics) {
  if (!labor.qualityAlert) return;
  quality = quality || {};
  const hasQualityIssue = quality && quality.level && quality.level !== "ok";
  const hasDiagnosticIssue = diagnostics && diagnostics.level && diagnostics.level !== "ok";
  if (!hasQualityIssue && !hasDiagnosticIssue) {
    labor.qualityAlert.hidden = true;
    labor.qualityAlert.innerHTML = "";
    return;
  }

  const issues = quality.issues || [];
  const diagnosticIssues = diagnostics && Array.isArray(diagnostics.issues) ? diagnostics.issues : [];
  const metrics = quality.metrics || {};
  const confidence = metrics.confidence || {};
  const methods = metrics.extractionMethods || {};
  const employeeCounts = metrics.employeeCounts || {};
  const totals = metrics.totals || {};
  const warehouseIssues = metrics.warehouseIssues || [];
  const alertLevel = _higherSeverity(quality.level, diagnostics && diagnostics.level);
  const severityLabel = alertLevel === "critical" ? "必须复核" : "建议复核";
  const severityTitle =
    (hasDiagnosticIssue && diagnostics && diagnostics.message) ||
    quality.message ||
    (alertLevel === "critical" ? "抽取质量存在严重问题。" : "抽取质量需要关注。");
  const actionItems = diagnosticIssues.length
    ? diagnosticIssues
        .slice(0, 6)
        .map((issue) => `${issue.title || "信号异常"}：${issue.message || ""}`)
        .filter(Boolean)
    : warehouseIssues.length
    ? warehouseIssues.slice(0, 6)
    : issues.slice(0, 6);
  const amountDelta = Math.abs(totals.amountDelta || 0);
  const hoursDelta = Math.abs(totals.hoursDelta || 0);
  const pdfAmount = totals.pdfAmount;
  const excelAmount = totals.excelAmount;
  const signals = (diagnostics && diagnostics.signals) || {};
  const employeeGap = Math.abs((employeeCounts.unmatchedPdf || 0) + (employeeCounts.unmatchedExcel || 0));
  const signalDelta =
    signals.fastPdfTotal !== undefined
      ? Math.abs((signals.fastPdfTotal || 0) - (signals.excelTotal || 0))
      : amountDelta;
  const primaryFocus = actionItems.length
    ? actionItems[0]
    : amountDelta > 0.1
    ? "总金额存在差异，先按仓库定位，再下钻到员工。"
    : "总金额在容差内，当前只需抽样复核抽取证据。";
  const secondaryFocus = actionItems.slice(1, 4);

  // Build details
  let detailsHtml = "";

  if (diagnosticIssues.length) {
    detailsHtml += `
      <div class="quality-detail-section">
        <h4>信号诊断</h4>
        ${diagnosticIssues
          .map(
            (issue) => `<div class="diagnostic-issue">
              <strong>${escapeHtml(issue.title || "信号异常")}</strong>
              <p>${escapeHtml(issue.message || "")}</p>
              ${
                issue.items && issue.items.length
                  ? `<ul>${issue.items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`
                  : ""
              }
            </div>`
          )
          .join("")}
      </div>
    `;
  }

  // Confidence distribution
  if (confidence.average !== undefined) {
    detailsHtml += `
      <div class="quality-detail-section">
        <h4>置信度分布</h4>
        <div class="quality-metrics">
          <span><em>平均置信度</em><strong>${(confidence.average * 100).toFixed(1)}%</strong></span>
          <span><em>低置信度</em><strong>${confidence.lowCount || 0} 条</strong></span>
          <span><em>极低置信度</em><strong>${confidence.veryLowCount || 0} 条</strong></span>
        </div>
      </div>
    `;
  }

  // Extraction methods
  if (Object.keys(methods).length > 0) {
    detailsHtml += `
      <div class="quality-detail-section">
        <h4>抽取方法</h4>
        <div class="quality-metrics">
          <span><em>规则</em><strong>${methods.rule || 0}</strong></span>
          <span><em>AI 文本</em><strong>${methods.ai_text || 0}</strong></span>
          <span><em>AI 图片</em><strong>${methods.ai_image || 0}</strong></span>
        </div>
      </div>
    `;
  }

  // Employee counts
  if (employeeCounts.pdf !== undefined) {
    detailsHtml += `
      <div class="quality-detail-section">
        <h4>员工覆盖</h4>
        <div class="quality-metrics">
          <span><em>PDF</em><strong>${employeeCounts.pdf} 人</strong></span>
          <span><em>Excel</em><strong>${employeeCounts.excel} 人</strong></span>
          <span><em>未匹配</em><strong>${
            (employeeCounts.unmatchedPdf || 0) + (employeeCounts.unmatchedExcel || 0)
          } 人</strong></span>
        </div>
      </div>
    `;
  }

  // Amount/hours drift
  if (totals.pdfAmount !== undefined) {
    const amountDelta = Math.abs(totals.amountDelta || 0);
    const hoursDelta = Math.abs(totals.hoursDelta || 0);
    if (amountDelta > 0.01 || hoursDelta > 0.01) {
      detailsHtml += `
        <div class="quality-detail-section">
          <h4>差异统计</h4>
          <div class="quality-metrics">
            <span><em>金额差异</em><strong>$${amountDelta.toFixed(2)}</strong></span>
            <span><em>工时差异</em><strong>${hoursDelta.toFixed(2)}h</strong></span>
          </div>
        </div>
      `;
    }
  }

  labor.qualityAlert.hidden = false;
  labor.qualityAlert.dataset.level = alertLevel || "warning";
  labor.qualityAlert.innerHTML = `
    <div class="quality-command">
      <div class="quality-command-main">
        <span class="quality-eyebrow">${escapeHtml(severityLabel)}</span>
        <h3>${escapeHtml(severityTitle)}</h3>
        <p>${escapeHtml(_qualityNextStepText(quality, warehouseIssues, totals, diagnostics))}</p>
      </div>
      <div class="quality-money-stack">
        <span>${signals.fastPdfTotal !== undefined ? "总额差异" : "金额差异"}</span>
        <strong>${signalDelta > 0 ? "+" : ""}$${formatMoney(signalDelta)}</strong>
        <small>${signals.fastPdfTotal !== undefined ? "PDF vs Excel" : `工时差异 ${formatHours(hoursDelta)}h`}</small>
      </div>
    </div>
    <div class="quality-workflow">
      <section class="quality-focus-card">
        <span class="focus-index">01</span>
        <div>
          <h4>优先复核</h4>
          <p>${escapeHtml(primaryFocus)}</p>
          ${
            secondaryFocus.length
              ? `<ul>${secondaryFocus.map((issue) => `<li>${escapeHtml(issue)}</li>`).join("")}</ul>`
              : ""
          }
        </div>
      </section>
      <section class="quality-ledger-card">
        <h4>当前口径</h4>
        <div class="ledger-grid">
          <div><span>PDF 总额</span><strong>${signals.fastPdfTotal === undefined ? pdfAmount === undefined ? "—" : `$${formatMoney(pdfAmount)}` : `$${formatMoney(signals.fastPdfTotal)}`}</strong></div>
          <div><span>Excel 总额</span><strong>${signals.excelTotal === undefined ? excelAmount === undefined ? "—" : `$${formatMoney(excelAmount)}` : `$${formatMoney(signals.excelTotal)}`}</strong></div>
          <div><span>员工明细</span><strong>${signals.employeePdfTotal === undefined ? pdfAmount === undefined ? "—" : `$${formatMoney(pdfAmount)}` : `$${formatMoney(signals.employeePdfTotal)}`}</strong></div>
          <div><span>仓库 PDF</span><strong>${signals.warehouseTotal === undefined ? "—" : `$${formatMoney(signals.warehouseTotal)}`}</strong></div>
        </div>
      </section>
    </div>
    <div class="quality-mini-metrics">
      <div><span>覆盖</span><strong>PDF ${employeeCounts.pdf ?? "—"} / Excel ${employeeCounts.excel ?? "—"}</strong></div>
      <div><span>未匹配</span><strong>${employeeGap} 人</strong></div>
      <div><span>抽取</span><strong>规则 ${methods.rule || 0} · AI ${Number(methods.ai_text || 0) + Number(methods.ai_image || 0)}</strong></div>
      <div><span>置信度</span><strong>${confidence.average === undefined ? "—" : `${(confidence.average * 100).toFixed(1)}%`}</strong></div>
    </div>
    ${detailsHtml ? `<details class="quality-diagnostics"><summary>技术诊断与抽取指标</summary><div class="quality-details">${detailsHtml}</div></details>` : ""}
  `;
}

function _qualityNextStepText(quality, warehouseIssues, totals, diagnostics) {
  if (diagnostics && diagnostics.level && diagnostics.level !== "ok" && diagnostics.nextStep) return diagnostics.nextStep;
  const amountDelta = Math.abs(totals.amountDelta || 0);
  if (warehouseIssues && warehouseIssues.length) {
    return `系统发现 ${warehouseIssues.length} 个仓库需要复核。先看仓库金额，再进入员工明细定位差异。`;
  }
  if (amountDelta <= 0.1 && quality.level !== "critical") {
    return "总金额已在容差内，当前只是抽取质量提示；可下载报告留档。";
  }
  return "先核对总额口径，再按仓库和员工明细逐层确认。";
}

function _higherSeverity(levelA, levelB) {
  const rank = { ok: 0, warning: 1, critical: 2 };
  const a = rank[levelA] || 0;
  const b = rank[levelB] || 0;
  return a >= b ? levelA || "ok" : levelB || "ok";
}

function renderExtractRows(container, rows) {
  if (!rows.length) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">
          <svg width="40" height="40" viewBox="0 0 40 40" fill="none"><rect x="6" y="8" width="28" height="24" rx="4" stroke="#D2D2D7" stroke-width="1.5"/><path d="M12 16h16M12 20h10M12 24h7" stroke="#D2D2D7" stroke-width="1.5" stroke-linecap="round"/></svg>
        </div>
        <p class="empty-title">暂无抽取数据</p>
        <p class="empty-desc">点击「抽取并比对」开始核对</p>
      </div>
    `;
    return;
  }
  const visible = rows.slice(0, 80);
  container.innerHTML = `<table><thead><tr><th>员工</th><th>工号</th><th>工时</th><th>金额</th><th>置信度</th><th>来源</th><th>证据</th></tr></thead><tbody>${visible
    .map(
      (row) =>
        `<tr><td>${escapeHtml(row.employee_name_raw)}</td><td>${escapeHtml(
          row.employee_id || ""
        )}</td><td>${formatHours(row.hours)}</td><td>${formatMoney(
          row.amount
        )}</td><td>${formatPercent(row.confidence)}</td><td>${escapeHtml(
          `${row.source_file || ""} ${row.source_page_or_row || ""}`
        )}</td><td>${escapeHtml(row.evidence_text || "")}</td></tr>`
    )
    .join("")}</tbody></table>${
    rows.length > visible.length
      ? `<p class="table-note">仅展示前 ${visible.length} 条，完整明细请下载报告查看。</p>`
      : ""
  }`;
}

// ── Utility functions ──
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
  return Number(value || 0).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function formatHours(value) {
  return Number(value || 0).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function formatPercent(value) {
  const number = Number(value || 0);
  return number > 1 ? `${number.toFixed(1)}%` : `${(number * 100).toFixed(1)}%`;
}

function escapeHtml(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (char) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#039;",
      }[char])
  );
}
