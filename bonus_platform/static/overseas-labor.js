const laborState = {
  run: null,
  headers: [],
  comparePollTimer: null,
  pollRetryCount: 0,
  pollMaxRetries: 200,  // 200 × 3s = 10 分钟
  extractStartedAt: null,
  currentStep: 1,
  reocrBatchPreview: null,
  reocrBatchUpload: null,
  governanceConfirm: null,
  governanceActionFeedback: null,
  reocrJsonInput: null,
  materialIndex: null,
  materialDryRun: null,
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
  moduleStageBadge: document.querySelector("#moduleStageBadge"),

  // Form elements
  supplierName: document.querySelector("#supplierName"),
  supplierOptions: document.querySelector("#supplierOptions"),
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
  ruleGovernanceSection: document.querySelector("#ruleGovernanceSection"),
  ruleGovernanceBody: document.querySelector("#ruleGovernanceBody"),
  governanceStatus: document.querySelector("#governanceStatus"),
  pendingItemsSection: document.querySelector("#pendingItemsSection"),
  amountRateGroup: document.querySelector("#amountRateGroup"),
  hoursDiffGroup: document.querySelector("#hoursDiffGroup"),
  candidateGroup: document.querySelector("#candidateGroup"),
  notInInvoiceGroup: document.querySelector("#notInInvoiceGroup"),
  extractPreviewTable: document.querySelector("#extractPreviewTable"),
  reportLink: document.querySelector("#laborReportLink"),
  toast: document.querySelector("#laborToast"),

  // Reference material dry-run
  loadMaterialBatches: document.querySelector("#loadMaterialBatches"),
  materialBatchSelect: document.querySelector("#materialBatchSelect"),
  runMaterialDryRun: document.querySelector("#runMaterialDryRun"),
  materialReplayStatus: document.querySelector("#materialReplayStatus"),
  materialReplayBody: document.querySelector("#materialReplayBody"),
};

// ── Initialize ──
bindLaborEvents();
listenKpiFilters();
loadModuleAccess();
loadSupplierOptions();

function listenKpiFilters() {
  document.addEventListener('kpi-filter', (e) => {
    filterPendingItems(e.detail);
  });
}

function filterPendingItems(filter) {
  const section = labor.pendingItemsSection;
  if (!section || section.hidden) return;
  const hasPendingRows = (group) => Number(group?.dataset?.count || 0) > 0;

  if (filter === 'all') {
    section.querySelectorAll('.pending-group').forEach(group => {
      group.hidden = !hasPendingRows(group);
    });
  } else if (filter === 'variance') {
    section.querySelectorAll('.pending-group').forEach(group => {
      group.hidden = group.id !== 'hoursDiffGroup' || !hasPendingRows(group);
    });
  } else if (filter === 'unmatched') {
    section.querySelectorAll('.pending-group').forEach(group => {
      group.hidden = group.id !== 'notInInvoiceGroup' || !hasPendingRows(group);
    });
  } else if (filter === 'matched') {
    section.querySelectorAll('.pending-group').forEach(group => {
      group.hidden = true;
    });
  }
  updatePendingGroupLayout(section);
}

function bindLaborEvents() {
  labor.createLaborRun.addEventListener("click", createRun);
  labor.uploadLaborFiles.addEventListener("click", uploadFiles);
  labor.loadSheets.addEventListener("click", loadSheets);
  labor.sheetSelect.addEventListener("change", loadFieldSuggestions);
  labor.saveMapping.addEventListener("click", saveMapping);
  labor.extractCompare.addEventListener("click", extractAndCompare);
  if (labor.loadMaterialBatches) labor.loadMaterialBatches.addEventListener("click", loadMaterialBatches);
  if (labor.runMaterialDryRun) labor.runMaterialDryRun.addEventListener("click", runMaterialDryRun);
  if (labor.materialReplayBody) labor.materialReplayBody.addEventListener("click", handleMaterialReplayAction);
  if (labor.ruleGovernanceBody) labor.ruleGovernanceBody.addEventListener("click", handleGovernanceAction);
  if (labor.reportLink) {
    labor.reportLink.addEventListener("click", () => {
      if (labor.reportLink.classList.contains("disabled")) return;
      recordLaborTelemetry("labor.report.download_clicked", {
        step: "download",
        status: "clicked",
        context: { path: labor.reportLink.getAttribute("href") || "" },
      });
    });
  }
}

async function loadSupplierOptions() {
  if (!labor.supplierOptions) return;
  try {
    const data = await requestJson("/api/labor/suppliers");
    const suppliers = Array.isArray(data.suppliers) ? data.suppliers : [];
    labor.supplierOptions.innerHTML = suppliers
      .map((supplier) => {
        const name = supplier && supplier.name ? String(supplier.name).trim() : "";
        if (!name) return "";
        const label = Array.isArray(supplier.sources) && supplier.sources.includes("profile") ? "已有规则" : "历史批次";
        return `<option value="${escapeHtml(name)}" label="${escapeHtml(label)}"></option>`;
      })
      .join("");
  } catch (error) {
    console.warn("供应商建议加载失败", error);
  }
}

async function loadModuleAccess() {
  try {
    const access = await requestJson("/api/labor/access");
    if (labor.moduleStageBadge) {
      labor.moduleStageBadge.textContent = `${access.stage || "UAT试用版"} · ${access.message || "人工复核后使用"}`;
      labor.moduleStageBadge.classList.toggle("blocked", access.canUse === false);
    }
    if (access.canUse === false) {
      [labor.createLaborRun, labor.uploadLaborFiles, labor.saveMapping, labor.extractCompare, labor.runMaterialDryRun].forEach((button) => {
        if (button) button.disabled = true;
      });
      toast(access.message || "当前账号无权使用海外劳务报账核对。");
    }
  } catch (error) {
    if (labor.moduleStageBadge) {
      labor.moduleStageBadge.textContent = "UAT试用版 · 权限状态读取失败";
      labor.moduleStageBadge.classList.add("blocked");
    }
  }
}

function laborTelemetrySummary(run = laborState.run) {
  const summary = run?.comparisonSummary || {};
  const warehouseSummary = run?.warehouseComparison?.summary || {};
  const source = Object.keys(warehouseSummary).length ? warehouseSummary : summary;
  const governance = run?.ruleGovernance || {};
  const reocrPlan = run?.reocrPlan || {};
  const candidateCount =
    Number(governance.summary?.candidateCount || 0) +
    Number(run?.profileGovernance?.summary?.candidateCount || 0) +
    Number(run?.nameMappingGovernance?.summary?.candidateCount || 0) +
    Number(run?.allocationGovernance?.summary?.candidateCount || 0) +
    Number(run?.correctionGovernance?.summary?.candidateCount || 0) +
    Number(reocrPlan.summary?.taskCount || 0);
  return {
    pdfAmountTotal: source.pdfAmountTotal ?? summary.pdfAmountTotal,
    excelAmountTotal: source.excelAmountTotal ?? summary.excelAmountTotal,
    amountDeltaTotal: source.amountDeltaTotal ?? summary.amountDeltaTotal,
    hoursDeltaTotal: source.hoursDeltaTotal ?? summary.hoursDeltaTotal,
    exceptionCount: summary.exceptionCount,
    amountDiffCount: summary.amountDiffCount,
    hoursRiskCount: summary.hoursRiskCount,
    lowConfidenceCount: summary.lowConfidenceCount,
    candidateMatchCount: summary.candidateMatchCount || (run?.candidateMatches || []).length,
    notInInvoiceCount: summary.notInInvoiceCount,
    pdfEmployeeCount: summary.pdfEmployeeCount,
    excelEmployeeCount: summary.excelEmployeeCount,
    warehouseExceptionCount: warehouseSummary.exceptionCount,
    governanceCandidateCount: candidateCount,
    readinessStatus: run?.readinessGate?.status || run?.readinessGate?.label || "",
  };
}

function elapsedMs(startedAt) {
  if (!Number.isFinite(startedAt)) return undefined;
  return Math.max(0, Math.round(performance.now() - startedAt));
}

function recordLaborTelemetry(event, details = {}) {
  const payload = {
    event,
    runId: details.runId || laborState.run?.id || "",
    supplier: details.supplier || laborState.run?.supplierName || labor.supplierName?.value?.trim() || "",
    step: details.step || "",
    status: details.status || "",
    durationMs: details.durationMs,
    errorCode: details.errorCode || "",
    errorMessage: details.errorMessage || "",
    summary: details.summary || laborTelemetrySummary(details.run || laborState.run),
    context: details.context || {},
  };
  const body = JSON.stringify(payload);
  try {
    if (navigator.sendBeacon) {
      const accepted = navigator.sendBeacon(
        "/api/labor/telemetry",
        new Blob([body], { type: "application/json" })
      );
      if (accepted) return;
    }
    fetch("/api/labor/telemetry", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      keepalive: true,
    }).catch(() => {});
  } catch (error) {
    // 试用埋点不能阻断核对流程。
  }
}

async function createRun() {
  const supplierName = labor.supplierName.value.trim();
  const periodStart = labor.periodStart.value;
  const periodEnd = labor.periodEnd.value;
  const currency = labor.currency.value.trim().toUpperCase();

  if (!supplierName) {
    setText(labor.createStatus, "请先填写供应商名称。", true);
    labor.supplierName.focus();
    return;
  }
  if (!periodStart || !periodEnd) {
    setText(labor.createStatus, "请先选择完整账期。", true);
    (periodStart ? labor.periodEnd : labor.periodStart).focus();
    return;
  }
  if (periodEnd < periodStart) {
    setText(labor.createStatus, "账期结束日期不能早于开始日期。", true);
    labor.periodEnd.focus();
    return;
  }
  if (!currency) {
    setText(labor.createStatus, "请先填写结算币种。", true);
    labor.currency.focus();
    return;
  }

  setText(labor.createStatus, "正在创建批次...");
  labor.createLaborRun.disabled = true;
  const startedAt = performance.now();
  recordLaborTelemetry("labor.create.started", {
    step: "create",
    status: "started",
    supplier: supplierName,
    context: { button: "createLaborRun" },
  });
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
    laborState.reocrBatchPreview = null;
    laborState.reocrBatchUpload = null;
    setText(labor.createStatus, `批次已创建：${run.id}`);

    // Update run badge
    if (labor.chromeRunBadge) {
      labor.chromeRunBadge.hidden = false;
      labor.chromeRunLabel.textContent = `批次 #${run.id.slice(0, 8)}`;
    }

    recordLaborTelemetry("labor.create.succeeded", {
      run,
      runId: run.id,
      supplier: supplierName,
      step: "create",
      status: "succeeded",
      durationMs: elapsedMs(startedAt),
    });
    toast("劳务核对批次已创建。");
    advanceWizardStep("2");
  } catch (error) {
    recordLaborTelemetry("labor.create.failed", {
      step: "create",
      status: "failed",
      durationMs: elapsedMs(startedAt),
      errorMessage: error.message,
      supplier: supplierName,
    });
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
  const startedAt = performance.now();
  const uploadContext = {
    pdfCount: labor.pdfFiles.files.length,
    workbookCount: labor.workbookFile.files.length,
    fileCount: labor.pdfFiles.files.length + labor.workbookFile.files.length,
  };
  recordLaborTelemetry("labor.upload.started", {
    step: "upload",
    status: "started",
    context: uploadContext,
  });
  try {
    laborState.run = await requestJson(`/api/labor/runs/${laborState.run.id}/files`, {
      method: "POST",
      body: form,
    });
    laborState.reocrBatchPreview = null;
    laborState.reocrBatchUpload = null;
    setText(labor.uploadStatus, "文件已上传，可以读取工作表。");
    recordLaborTelemetry("labor.upload.succeeded", {
      step: "upload",
      status: "succeeded",
      durationMs: elapsedMs(startedAt),
      context: uploadContext,
    });
    toast("文件上传完成。");
    advanceWizardStep("3");
  } catch (error) {
    recordLaborTelemetry("labor.upload.failed", {
      step: "upload",
      status: "failed",
      durationMs: elapsedMs(startedAt),
      errorMessage: error.message,
      context: uploadContext,
    });
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
  const startedAt = performance.now();
  const context = {
    sheetName: labor.sheetSelect.value,
    mappingFields: [
      labor.nameColumn.value ? "name" : "",
      labor.employeeIdColumn.value ? "employeeId" : "",
      labor.hoursColumn.value ? "hours" : "",
      labor.amountColumn.value ? "amount" : "",
      labor.currencyColumn.value ? "currency" : "",
    ].filter(Boolean),
  };
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
    recordLaborTelemetry("labor.mapping.succeeded", {
      step: "mapping",
      status: "succeeded",
      durationMs: elapsedMs(startedAt),
      context,
    });
    toast("字段映射已确认，可以开始抽取比对。");
    if (typeof window.closeDrawer === "function") window.closeDrawer();
  } catch (error) {
    recordLaborTelemetry("labor.mapping.failed", {
      step: "mapping",
      status: "failed",
      durationMs: elapsedMs(startedAt),
      errorMessage: error.message,
      context,
    });
    toast(error.message);
  }
}

async function loadMaterialBatches() {
  if (!labor.materialBatchSelect || !labor.materialReplayBody) return;
  setText(labor.materialReplayStatus, "正在扫描参考材料...");
  labor.loadMaterialBatches.disabled = true;
  try {
    const index = await requestJson("/api/labor/material-index");
    laborState.materialIndex = index;
    const batches = Array.isArray(index.candidateBatches) ? index.candidateBatches : [];
    labor.materialBatchSelect.innerHTML = batches.length
      ? batches
          .map((batch) => {
            const label = `${batch.directory || batch.batchKey} · PDF ${batch.invoicePdfCount || 0} · 账单 ${batch.workbookCount || 0}`;
            return `<option value="${escapeHtml(batch.batchKey)}">${escapeHtml(label)}</option>`;
          })
          .join("")
      : '<option value="">未发现可验证材料</option>';
    renderMaterialIndexSummary(index);
    setText(labor.materialReplayStatus, batches.length ? `已发现 ${batches.length} 个可预览批次。` : "未发现可预览批次。", !batches.length);
  } catch (error) {
    setText(labor.materialReplayStatus, error.message, true);
    toast(error.message);
  } finally {
    labor.loadMaterialBatches.disabled = false;
  }
}

async function runMaterialDryRun() {
  const batchKey = labor.materialBatchSelect?.value || "";
  if (!batchKey) return toast("请先选择材料批次。");
  setText(labor.materialReplayStatus, "正在执行测试验证...");
  labor.runMaterialDryRun.disabled = true;
  const startedAt = performance.now();
  recordLaborTelemetry("labor.material.validation.started", {
    step: "material_validation",
    status: "started",
    context: { batchKey },
  });
  try {
    const dryRun = await requestJson("/api/labor/material-dry-run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ batchKey }),
    });
    laborState.materialDryRun = dryRun;
    renderMaterialDryRun(dryRun);
    const governance = dryRun.nameMappingGovernance || {};
    const combinedRows = dryRun.combinedRowGovernance || {};
    const candidateCount = governance.summary?.candidateCount || 0;
    const combinedCount = combinedRows.summary?.candidateCount || 0;
    setText(labor.materialReplayStatus, `测试验证完成：异常 ${dryRun.summary?.comparison?.exceptionCount || 0}，疑似姓名匹配 ${candidateCount}，疑似合并行 ${combinedCount}。`);
    recordLaborTelemetry("labor.material.validation.completed", {
      step: "material_validation",
      status: "completed",
      durationMs: elapsedMs(startedAt),
      summary: {
        ...dryRun.summary?.comparison,
        governanceCandidateCount: candidateCount + combinedCount,
      },
      context: { batchKey },
    });
  } catch (error) {
    recordLaborTelemetry("labor.material.validation.failed", {
      step: "material_validation",
      status: "failed",
      durationMs: elapsedMs(startedAt),
      errorMessage: error.message,
      context: { batchKey },
    });
    setText(labor.materialReplayStatus, error.message, true);
    toast(error.message);
  } finally {
    labor.runMaterialDryRun.disabled = false;
  }
}

function renderMaterialIndexSummary(index) {
  if (!labor.materialReplayBody) return;
  const summary = index.summary || {};
  const batches = Array.isArray(index.candidateBatches) ? index.candidateBatches : [];
  const readyCount = batches.filter((batch) => batch.replayReady).length;
  labor.materialReplayBody.innerHTML = `
    <div class="governance-command">
      <div>
        <strong>参考材料索引</strong>
        <span>发现 ${summary.fileCount || 0} 个文件、${summary.candidateBatchCount || 0} 个材料批次，其中 ${readyCount} 个可测试验证。</span>
      </div>
      <div class="governance-meta">
        <span class="governance-pill">PDF ${summary.invoicePdfCount || 0}</span>
        <span class="governance-pill">账单 ${summary.workbookCount || 0}</span>
        <span class="governance-pill">供应商 ${summary.supplierCount || 0}</span>
      </div>
    </div>
  `;
}

function materialDisplayText(value) {
  return String(value ?? "")
    .replaceAll("candidate-only", "只读建议")
    .replaceAll("Dry-run", "测试验证")
    .replaceAll("dry-run", "测试验证")
    .replaceAll("重 OCR", "图片识别复核")
    .replaceAll("OCR", "图片识别复核")
    .replaceAll("回放", "预览")
    .replaceAll("候选", "建议")
    .replaceAll("姓名映射", "姓名匹配")
    .replaceAll("映射", "匹配")
    .replaceAll("回滚", "撤回");
}

function renderMaterialDryRun(dryRun) {
  if (!labor.materialReplayBody) return;
  const comparison = dryRun.summary?.comparison || {};
  const warehouse = dryRun.summary?.warehouse || {};
  const governance = dryRun.nameMappingGovernance || {};
  const governanceSummary = governance.summary || {};
  const combinedRowGovernance = dryRun.combinedRowGovernance || {};
  const combinedRowSummary = combinedRowGovernance.summary || {};
  const risks = Array.isArray(dryRun.expectedRisks) ? dryRun.expectedRisks : [];
  const reviewQueues = dryRun.reviewQueues || {};
  const reocrQueue = reviewQueues.reocr || {};
  const amountRateQueue = reviewQueues.amountRateReview || {};
  const allocationQueue = reviewQueues.allocationReview || {};
  const combinedQueue = reviewQueues.combinedPdfRows || {};
  const nameMappingQueue = reviewQueues.nameMapping || {};
  const exceptionQueue = reviewQueues.employeeExceptions || {};
  const deliveryGate = dryRun.deliveryGate || {};
  const candidates = Array.isArray(governance.candidates) ? governance.candidates : [];
  const combinedCandidates = Array.isArray(combinedRowGovernance.candidates) ? combinedRowGovernance.candidates : [];
  const riskHtml = risks.length
    ? `<ul class="reocr-evidence-list">${risks.slice(0, 6).map((risk) => `<li>${escapeHtml(materialDisplayText(risk))}</li>`).join("")}</ul>`
    : `<p class="governance-empty">暂无额外风险提示。</p>`;
  const candidateHtml = candidates.length
    ? `<div class="governance-card-grid">${candidates.map(renderMaterialNameMappingCandidateCard).join("")}</div>`
    : `<div class="governance-empty">本次测试验证未发现需要处理的姓名匹配建议。</div>`;
  const combinedRowHtml = combinedCandidates.length
    ? `<div class="governance-card-grid">${combinedCandidates.map(renderMaterialCombinedRowCandidateCard).join("")}</div>`
    : `<div class="governance-empty">本次测试验证未发现疑似 PDF 合并员工行。</div>`;
  const reocrHtml = renderMaterialReviewQueue(reviewQueues);
  const amountRateHtml = renderMaterialAmountRateQueue(reviewQueues);
  const allocationHtml = renderMaterialAllocationQueue(reviewQueues);
  const nameMappingHtml = (nameMappingQueue.count || governanceSummary.candidateCount)
    ? `
    <div class="governance-command">
      <div>
        <strong>疑似姓名匹配</strong>
        <span>建议 ${nameMappingQueue.count || governanceSummary.candidateCount || 0} · 可预览 ${nameMappingQueue.readyToReplayCount || governanceSummary.readyToReplayCount || 0} · 预计修复异常 ${nameMappingQueue.projectedFixedExceptionCount || governanceSummary.projectedFixedExceptionCount || 0} · 高可信 ${nameMappingQueue.highConfidenceCount || governanceSummary.highConfidenceCount || 0} · 金额仍不同 ${nameMappingQueue.amountStillDifferentCount || governanceSummary.amountStillDifferentCount || 0} · 工时仍不同 ${nameMappingQueue.hoursStillDifferentCount || governanceSummary.hoursStillDifferentCount || 0}</span>
      </div>
      <div class="governance-meta">
        <span class="governance-pill warning">只读建议</span>
        <span class="governance-pill warning">需创建批次后预览确认</span>
      </div>
    </div>
    ${renderMaterialNameMappingNextActions(nameMappingQueue.nextActions || [])}
    ${candidateHtml}
  `
    : "";
  const combinedReviewHtml = (combinedQueue.count || combinedRowSummary.candidateCount)
    ? `
    <div class="governance-command">
      <div>
        <strong>PDF 合并员工行复核</strong>
        <span>建议 ${combinedQueue.count || combinedRowSummary.candidateCount || 0} · 金额影响 ${formatMoney(combinedQueue.amountImpactTotal || combinedRowSummary.amountImpactTotal || 0)} · 工时影响 ${formatSignedNumber(combinedQueue.hoursImpactTotal || combinedRowSummary.hoursImpactTotal || 0)}</span>
      </div>
      <div class="governance-meta">
        <span class="governance-pill warning">只读建议</span>
        <span class="governance-pill warning">需人工核对原始发票</span>
      </div>
    </div>
    ${combinedRowHtml}
  `
    : "";
  let orderedReviewHtml = `${reocrHtml}${amountRateHtml}${allocationHtml}${nameMappingHtml}${combinedReviewHtml}`;
  if (reviewQueues.primary === "name_mapping") {
    orderedReviewHtml = `${reocrHtml}${nameMappingHtml}${amountRateHtml}${allocationHtml}${combinedReviewHtml}`;
  } else if (reviewQueues.primary === "combined_pdf_row") {
    orderedReviewHtml = `${reocrHtml}${combinedReviewHtml}${amountRateHtml}${allocationHtml}${nameMappingHtml}`;
  } else if (reviewQueues.primary === "allocation_review") {
    orderedReviewHtml = `${reocrHtml}${allocationHtml}${amountRateHtml}${nameMappingHtml}${combinedReviewHtml}`;
  }
  const reocrPillHtml = reviewQueues.primary === "reocr"
    ? `<span class="governance-pill">图片识别复核 ${reocrQueue.taskCount || 0}</span>`
    : "";
  const primaryPillClass = reviewQueues.primary === "reocr" ? "danger" : reviewQueues.primary === "cleared" ? "ok" : "warning";

  labor.materialReplayBody.innerHTML = `
    <div class="governance-command">
      <div>
        <strong>${escapeHtml(dryRun.directory || dryRun.batchKey || "材料批次")} · 测试验证</strong>
        <span>PDF ${comparison.pdfEmployeeCount || 0} 人，Excel ${comparison.excelEmployeeCount || 0} 人，异常 ${comparison.exceptionCount || 0}，疑似匹配 ${comparison.candidateMatchCount || 0}。${reviewQueues.primaryReason ? ` ${escapeHtml(materialDisplayText(reviewQueues.primaryReason))}` : ""}</span>
      </div>
      <div class="governance-meta">
        <span class="governance-pill ${warehouse.totalPassed ? "ok" : "warning"}">${warehouse.totalPassed ? "总额通过" : "总额需复核"}</span>
        <span class="governance-pill">差额 ${formatSignedMoney(comparison.amountDeltaTotal || 0)}</span>
        <span class="governance-pill ${primaryPillClass}">主路径 ${escapeHtml(materialReviewQueueLabel(reviewQueues.primary, reviewQueues))}</span>
        ${reocrPillHtml}
        <span class="governance-pill">金额复核 ${amountRateQueue.count || 0}</span>
        <span class="governance-pill">跨仓归属 ${allocationQueue.count || 0}</span>
        <span class="governance-pill">后续异常 ${exceptionQueue.count || 0}</span>
        <span class="governance-pill">姓名匹配建议 ${nameMappingQueue.count || governanceSummary.candidateCount || 0}</span>
        <span class="governance-pill">合并行 ${combinedQueue.count || combinedRowSummary.candidateCount || 0}</span>
      </div>
      <div class="governance-action-row">
        <button class="btn-primary-lg" type="button" data-material-action="create-run">创建正式批次</button>
      </div>
      <div id="materialActionFeedback" class="material-action-feedback" role="status" aria-live="polite"></div>
    </div>
    ${renderMaterialDeliveryGate(deliveryGate)}
    ${orderedReviewHtml}
    <div class="governance-command">
      <div>
        <strong>风险提示</strong>
        ${riskHtml}
      </div>
    </div>
  `;
}

function renderMaterialDeliveryGate(deliveryGate) {
  if (!deliveryGate || !deliveryGate.status) return "";
  const status = deliveryGate.status || "needs_review";
  const statusClass = ["ready", "needs_review", "blocked"].includes(status) ? status : "needs_review";
  const summary = deliveryGate.summary || {};
  const issues = Array.isArray(deliveryGate.issues) ? deliveryGate.issues.slice(0, 4) : [];
  const issueHtml = issues.length
    ? `<ul class="readiness-issues">${issues
        .map(
          (issue) => `<li><strong>${escapeHtml(issue.title || issue.code || "待处理")}</strong><span>${escapeHtml(
            issue.message || issue.action || ""
          )}</span></li>`
        )
        .join("")}</ul>`
    : `<p class="readiness-clear">${escapeHtml(deliveryGate.message || "本批测试验证无阻断项。")}</p>`;
  return `<div class="readiness-gate ${statusClass}">
    <div class="readiness-head">
      <span class="readiness-pill">${escapeHtml(deliveryGate.label || "需复核")}</span>
      <span>测试验证交付检查 · 阻断 ${summary.blockedCount || 0} · 待复核 ${summary.reviewCount || 0} · 风险 ${summary.riskCount || 0}</span>
    </div>
    ${issueHtml}
  </div>`;
}

function renderMaterialNameMappingNextActions(actions) {
  return renderMaterialNextActions(actions, { title: "姓名匹配处理路径" });
}

function materialReviewQueueLabel(primary, reviewQueues = {}) {
  const labels = {
    reocr: "图片识别复核",
    amount_rate_review: "金额/费率",
    allocation_review: "跨仓归属",
    name_mapping: "姓名匹配",
    combined_pdf_row: "合并行复核",
    employee_exceptions: "员工异常",
    cleared: "已清账",
  };
  if (primary === "amount_rate_review" && Number(reviewQueues?.amountRateReview?.hoursMismatchCount || 0) > 0) {
    return "金额/工时";
  }
  return labels[primary] || "待处理";
}

function renderMaterialAllocationQueue(reviewQueues) {
  const allocation = reviewQueues?.allocationReview || {};
  const rows = Array.isArray(allocation.rows) ? allocation.rows : [];
  if (!rows.length) return "";
  const cards = rows.map(renderMaterialAllocationCard).join("");
  return `
    <div class="governance-command">
      <div>
        <strong>跨仓归属复核</strong>
        <span>${escapeHtml(allocation.count || 0)} 名员工总额可抵消，但仓库归属仍不一致 · 涉及 ${escapeHtml(allocation.warehousePairCount || 0)} 个仓库明细 · 最大影响 ${formatMoney(allocation.amountImpactTotal || 0)}</span>
      </div>
      <div class="governance-meta">
        <span class="governance-pill warning">需按仓复核</span>
        <span class="governance-pill warning">只留痕不自动改金额</span>
      </div>
    </div>
    ${renderMaterialNextActions(allocation.nextActions || [], { title: "跨仓归属复核路径" })}
    <div class="governance-card-grid">${cards}</div>
  `;
}

function renderMaterialAllocationCard(row) {
  const warehouses = Array.isArray(row.warehouses) ? row.warehouses : [];
  const warehouseText = warehouses
    .map((item) => `仓 ${item.warehouseId || "-"} ${formatSignedMoney(item.amountDelta || 0)}`)
    .join(" · ");
  return `<article class="governance-card">
    <div class="governance-meta">
      <span class="governance-pill warning">跨仓抵消</span>
      <span class="governance-pill">净差 ${formatSignedMoney(row.netAmountDelta || 0)}</span>
      <span class="governance-pill">最大仓差 ${formatMoney(row.maxWarehouseDelta || 0)}</span>
    </div>
    <h3>${escapeHtml(row.employeeName || "员工跨仓库归属")}</h3>
    <p>${escapeHtml(row.recommendation || "员工总额可抵消，但仓库归属金额不一致，需按仓库复核发票与账单归属。")}</p>
    ${warehouseText ? `<p>${escapeHtml(warehouseText)}</p>` : ""}
    <div class="governance-action-row">
      <button class="btn-secondary" type="button" disabled>创建批次后复核</button>
      <button class="btn-primary-lg" type="button" disabled>确认前必须留痕</button>
    </div>
  </article>`;
}

function renderMaterialAmountRateQueue(reviewQueues) {
  const amountRate = reviewQueues?.amountRateReview || {};
  const rows = Array.isArray(amountRate.rows) ? amountRate.rows : [];
  if (!rows.length) return "";
  const hasHoursMismatch = Number(amountRate.hoursMismatchCount || 0) > 0;
  const title = hasHoursMismatch ? "先核对工时，再判断金额" : "工时已对齐，核对金额口径";
  const summaryText = hasHoursMismatch
    ? `${escapeHtml(amountRate.count || 0)} 人姓名已匹配，但工时/金额仍不一致 · 影响金额 ${formatMoney(amountRate.amountImpactTotal || 0)} · 工时差 ${formatHours(amountRate.hoursImpactTotal || 0)}`
    : `${escapeHtml(amountRate.count || 0)} 人姓名和工时已对齐，但金额仍不一致 · 影响金额 ${formatMoney(amountRate.amountImpactTotal || 0)}`;
  const cards = rows.map(renderMaterialAmountRateCard).join("");
  const summaryHtml = renderMaterialAmountRateSummary(amountRate);
  return `
    <div class="governance-command">
      <div>
        <strong>${title}</strong>
        <span>${summaryText}</span>
        ${amountRate.businessQuestion ? `<span>${escapeHtml(amountRate.businessQuestion)}</span>` : ""}
      </div>
      <div class="governance-meta">
        <span class="governance-pill warning">${hasHoursMismatch ? "先核工时" : "只核金额口径"}</span>
        <span class="governance-pill warning">不自动清账</span>
        <span class="governance-pill warning">确认前需留证据</span>
      </div>
    </div>
    ${summaryHtml}
    ${renderMaterialAmountRateNextActions(amountRate.nextActions || [])}
    <div class="governance-card-grid">${cards}</div>
  `;
}

function renderMaterialAmountRateSummary(amountRate) {
  const reviewMode = amountRate.reviewMode || "";
  const rows = Array.isArray(amountRate.rows) ? amountRate.rows : [];
  const amountOnlyCount = Number(amountRate.amountOnlyCount ?? rows.filter((row) => Math.abs(Number(row.hoursDelta || 0)) <= 0.1).length);
  const hoursMismatchCount = Number(amountRate.hoursMismatchCount ?? rows.filter((row) => Math.abs(Number(row.hoursDelta || 0)) > 0.1).length);
  const largestAmountDelta = Number(
    amountRate.largestAmountDelta ?? rows.reduce((max, row) => Math.max(max, Math.abs(Number(row.amountDelta || 0))), 0)
  );
  const hoursImpactTotal = Number(
    amountRate.hoursImpactTotal ?? rows.reduce((sum, row) => sum + Math.abs(Number(row.hoursDelta || 0)), 0)
  );
  return `<div class="amount-rate-summary">
    <div>
      <span>复核结论</span>
      <strong>${escapeHtml(reviewMode === "hours_and_amount" ? "先确认是否同一批工时" : "金额口径待业务确认")}</strong>
      <p>${escapeHtml(amountRate.businessMeaning || "需确认 PDF 与 Excel 的结算口径。")}</p>
    </div>
    <div>
      <span>不能自动处理</span>
      <strong>${escapeHtml(reviewMode === "hours_and_amount" ? "工时会影响金额" : "金额口径需留痕")}</strong>
      <p>${escapeHtml(amountRate.cannotAutoResolveReason || "确认前不能自动改金额或清账。")}</p>
    </div>
    <div>
      <span>金额影响</span>
      <strong>${formatMoney(amountRate.amountImpactTotal || 0)}</strong>
      <p>最大单人差异 ${formatMoney(largestAmountDelta)}</p>
    </div>
    <div>
      <span>问题分布</span>
      <strong>${escapeHtml(amountOnlyCount)} 金额 · ${escapeHtml(hoursMismatchCount)} 工时</strong>
      <p>工时差影响 ${formatHours(hoursImpactTotal)}</p>
    </div>
  </div>`;
}

function renderMaterialAmountRateNextActions(actions) {
  return renderMaterialNextActions(actions, { title: "金额/工时复核路径" });
}

function renderMaterialAmountRateCard(row) {
  const flags = Array.isArray(row.riskFlags) ? row.riskFlags : [];
  const flagHtml = flags.length
    ? flags.slice(0, 3).map((flag) => `<span class="governance-pill warning">${escapeHtml(flag)}</span>`).join("")
    : `<span class="governance-pill warning">金额差异</span>`;
  const reviewLabel = row.reviewLabel || (Number(row.hoursDelta || 0) ? "工时和金额都不同" : "工时一致，仅金额不同");
  const reviewFocus = row.reviewFocus || (Number(row.hoursDelta || 0) ? "先核工时口径" : "先核金额口径");
  const directionHtml = [
    row.amountDirectionLabel || "",
    row.hoursDirectionLabel || "",
  ]
    .filter(Boolean)
    .map((label) => `<span class="governance-pill">${escapeHtml(label)}</span>`)
    .join("");
  return `<article class="governance-card">
    <div class="governance-meta">
      <span class="governance-pill warning">${escapeHtml(reviewLabel)}</span>
      <span class="governance-pill warning">${escapeHtml(reviewFocus)}</span>
      ${flagHtml}
      ${directionHtml}
      <span class="governance-pill">金额差 ${formatSignedMoney(row.amountDelta || 0)}</span>
      <span class="governance-pill">工时差 ${formatSignedNumber(row.hoursDelta || 0)}</span>
    </div>
    <h3>${escapeHtml(row.employeeName || "-")}</h3>
    ${row.businessQuestion ? `<p><strong>${escapeHtml(row.businessQuestion)}</strong></p>` : ""}
    <p>PDF ${formatMoney(row.pdfAmountTotal || 0)} / Excel ${formatMoney(row.excelAmountTotal || 0)} · PDF工时 ${formatHours(row.pdfHoursTotal || 0)} / Excel工时 ${formatHours(row.excelHoursTotal || 0)}</p>
    <p>${escapeHtml(row.cannotAutoResolveReason || row.recommendation || "需复核发票费率、加班、服务费倍率与账单成本口径。")}</p>
    ${row.sourceRefs ? `<p>${escapeHtml(row.sourceRefs)}</p>` : ""}
    <div class="governance-action-row">
      <button class="btn-secondary" type="button" disabled>查看原始证据</button>
      <button class="btn-primary-lg" type="button" disabled>确认前需说明口径</button>
    </div>
  </article>`;
}

function renderMaterialReviewQueue(reviewQueues) {
  const primary = reviewQueues?.primary || "";
  const reocr = reviewQueues?.reocr || {};
  const exceptions = reviewQueues?.employeeExceptions || {};
  if (primary !== "reocr") {
    return "";
  }
  const tasks = Array.isArray(reocr.tasks) ? reocr.tasks : [];
  const reviewable = Array.isArray(reocr.reviewableCandidates) ? reocr.reviewableCandidates : [];
  const taskCards = [
    ...tasks.map((task) => renderMaterialReocrTaskCard(task, "需图片识别复核")),
    ...reviewable.map((candidate) => renderMaterialReocrTaskCard(candidate, "缓存可复核")),
  ];
  const groupSummaryHtml = renderMaterialReocrGroupSummary(reocr);
  const suppressedHtml = exceptions.suppressedByPrimary
    ? `<p class="governance-empty">${escapeHtml(exceptions.count || 0)} 条员工异常来自 PDF 明细缺失；先完成图片识别影响预览后再复核这些差异。</p>`
    : "";
  const nextActionsHtml = renderMaterialReocrNextActions(reocr.nextActions || []);
  return `
    <div class="governance-command">
      <div>
        <strong>图片发票识别复核</strong>
        <span>${escapeHtml(materialDisplayText(reocr.summaryText || "")) || `${escapeHtml(reocr.imageOnlyFileCount || 0)} 个 PDF 无文本层 · 图片识别复核 ${escapeHtml(reocr.taskCount || 0)} · 历史识别可复核 ${escapeHtml(reocr.reviewableCandidateCount || 0)} · 历史识别异常 ${escapeHtml(reocr.cacheExceptionCount || 0)}`}</span>
      </div>
      <div class="governance-meta">
        <span class="governance-pill danger">先处理</span>
        <span class="governance-pill warning">只读建议</span>
        <span class="governance-pill warning">创建正式批次后预览确认</span>
      </div>
    </div>
    ${nextActionsHtml}
    ${groupSummaryHtml}
    ${
      taskCards.length
        ? renderGovernanceCardDeck(taskCards, {
            title: "待处理 PDF",
            limit: 3,
            collapsedLabel: "展开其余图片识别任务",
          })
        : `<div class="governance-empty">暂无图片识别复核任务。</div>`
    }
    ${suppressedHtml}
  `;
}

function renderMaterialReocrGroupSummary(reocr) {
  const groups = Array.isArray(reocr?.groups) ? reocr.groups : [];
  if (!groups.length) return "";
  const visible = groups.slice(0, 4);
  const items = visible.map((group) => {
    const label = group.statusLabel || (Number(group.taskCount || 0) ? "需重新识别" : "历史识别可预览");
    const missing = Number(group.unmatchedExcelCount || 0);
    const exceptionCount = Number(group.exceptionCount || 0);
    const amountImpact = Number(group.amountImpactTotal || 0);
    const source = group.sourceFile || "PDF";
    const warehouse = group.warehouseId ? `仓 ${group.warehouseId}` : "未识别仓库";
    return `<div>
      <span>${escapeHtml(label)} · ${escapeHtml(warehouse)}</span>
      <strong>${escapeHtml(source)}</strong>
      <p>${escapeHtml(exceptionCount)} 项异常 · 缺失 ${escapeHtml(missing)} 人 · 影响 ${formatMoney(amountImpact)}</p>
    </div>`;
  }).join("");
  const more = groups.length > visible.length
    ? `<div><span>已收起</span><strong>其余 ${escapeHtml(groups.length - visible.length)} 个 PDF</strong><p>展开下方“待处理 PDF”查看完整明细。</p></div>`
    : "";
  return `<div class="amount-rate-summary">${items}${more}</div>`;
}

function renderGovernanceCardDeck(cards, options = {}) {
  const list = Array.isArray(cards) ? cards.filter(Boolean) : [];
  if (!list.length) return "";
  const limit = Math.max(1, Number(options.limit || 8));
  const visible = list.slice(0, limit);
  const hidden = list.slice(limit);
  const title = options.title ? `<div class="governance-deck-title"><strong>${escapeHtml(options.title)}</strong><span>${list.length} 项</span></div>` : "";
  const visibleHtml = `<div class="governance-card-grid">${visible.join("")}</div>`;
  if (!hidden.length) return `${title}${visibleHtml}`;
  const label = options.collapsedLabel || "展开其余候选";
  return `${title}${visibleHtml}
    <details class="governance-more">
      <summary>${escapeHtml(label)}（${hidden.length} 项）</summary>
      <div class="governance-card-grid">${hidden.join("")}</div>
    </details>`;
}

function renderMaterialReocrNextActions(actions) {
  return renderMaterialNextActions(actions, { title: "图片发票识别复核路径" });
}

function renderMaterialNextActions(actions, options = {}) {
  const rows = (Array.isArray(actions) ? actions : []).filter((action) => {
    const label = materialDisplayText(action?.label || "");
    return label !== "创建正式批次";
  });
  if (!rows.length) return "";
  const title = options.title ? `<strong class="material-action-title">${escapeHtml(options.title)}</strong>` : "";
  return `<div class="material-action-steps-wrap">
    ${title}
    <div class="material-action-steps">
    ${rows
      .map((action, index) => {
        const enabled = Boolean(action.enabled);
        const label = materialDisplayText(action.label || "等待前一步");
        const description = materialDisplayText(action.description || "");
        const stateText = enabled ? "当前可执行：点击上方主按钮" : "上方创建后解锁";
        return `<div class="material-action-step ${enabled ? "active" : ""}">
          <div class="material-action-index">${escapeHtml(index + 1)}</div>
          <div>
            <strong>${escapeHtml(label)}</strong>
            <span>${escapeHtml(description)}</span>
          </div>
          <span class="material-action-state">${escapeHtml(stateText)}</span>
        </div>`;
      })
      .join("")}
    </div>
  </div>`;
}

function renderMaterialReocrTaskCard(task, label) {
  const diagnostics = task.diagnostics || {};
  const summary = diagnostics.summary || {};
  const coverage = task.pdfTextCoverage || {};
  const focusEmployees = Array.isArray(task.focusEmployees) ? task.focusEmployees : [];
  const issueText = [
    summary.exceptionCount ? `异常 ${summary.exceptionCount}` : "",
    summary.unmatchedCacheCount ? `历史识别多出 ${summary.unmatchedCacheCount} 人` : "",
    summary.unmatchedExcelCount ? `账单有但历史识别缺失 ${summary.unmatchedExcelCount} 人` : "",
    coverage.needsOcr ? "无文本层" : "",
    ].filter(Boolean).join(" · ");
  const focusHtml = focusEmployees.length
    ? `<ul class="reocr-evidence-list">${focusEmployees.slice(0, 5).map((item) => {
        const status = item.matchStatus || "待复核";
        const delta = Number(item.amountDelta || 0);
        return `<li>${escapeHtml(item.employeeName || "-")} · ${escapeHtml(status)} · 金额差 ${formatSignedMoney(delta)}</li>`;
      }).join("")}</ul>`
    : "";
  return `<article class="governance-card">
    <div class="governance-meta">
      <span class="governance-pill warning">${escapeHtml(label)}</span>
      ${task.reviewFocus ? `<span class="governance-pill warning">${escapeHtml(materialDisplayText(task.reviewFocus))}</span>` : ""}
      <span class="governance-pill">仓 ${escapeHtml(task.warehouseId || "-")}</span>
      <span class="governance-pill">金额差 ${formatSignedMoney(task.amountDelta || 0)}</span>
    </div>
    <h3>${escapeHtml(task.sourceFile || "-")}</h3>
    ${task.matchReason ? `<p><strong>${escapeHtml(materialDisplayText(task.matchReason))}</strong></p>` : ""}
    ${task.businessQuestion ? `<p>${escapeHtml(materialDisplayText(task.businessQuestion))}</p>` : ""}
    ${task.impactSummary ? `<p>${escapeHtml(materialDisplayText(task.impactSummary))}</p>` : ""}
    <p>${escapeHtml(materialDisplayText(task.recommendation || task.confirmationGate || "需上传新的识别结果并预览，人工确认后才能影响核对结果。"))}</p>
    ${task.cannotAutoResolveReason ? `<p>${escapeHtml(materialDisplayText(task.cannotAutoResolveReason))}</p>` : ""}
    ${issueText ? `<p>${escapeHtml(issueText)}</p>` : ""}
    ${focusHtml}
    <div class="governance-action-row">
      <button class="btn-secondary" type="button" disabled>等待正式批次</button>
      <button class="btn-primary-lg" type="button" disabled>确认前必须预览</button>
    </div>
  </article>`;
}

function renderMaterialNameMappingCandidateCard(candidate) {
  const evidence = candidate.evidence || {};
  const confidence = candidate.confidence === "high" ? "high" : "medium";
  return `<article class="governance-card">
    <div class="governance-meta">
      <span class="governance-pill ${confidence === "high" ? "ok" : "warning"}">${escapeHtml(confidence)}</span>
      <span class="governance-pill">仓 ${escapeHtml(candidate.warehouseId || "-")}</span>
      <span class="governance-pill ${Number(candidate.projectedFixedExceptionCount || 0) ? "ok" : "warning"}">预计修复 ${escapeHtml(candidate.projectedFixedExceptionCount || 0)} 项</span>
      <span class="governance-pill">金额差 ${formatSignedMoney(candidate.amountGap || 0)}</span>
      <span class="governance-pill">工时差 ${formatSignedNumber(candidate.hoursGap || 0)}</span>
    </div>
    <h3>${escapeHtml(candidate.cacheEmployeeName || "-")} ⇄ ${escapeHtml(candidate.excelEmployeeName || "-")}</h3>
    ${candidate.matchReason ? `<p><strong>${escapeHtml(materialDisplayText(candidate.matchReason))}</strong></p>` : ""}
    ${candidate.businessQuestion ? `<p>${escapeHtml(materialDisplayText(candidate.businessQuestion))}</p>` : ""}
    ${candidate.impactSummary ? `<p>${escapeHtml(materialDisplayText(candidate.impactSummary))}</p>` : ""}
    <p>${escapeHtml(materialDisplayText(candidate.recommendation || "创建批次后需先预览影响，再由人工确认。"))}</p>
    ${candidate.cannotAutoResolveReason ? `<p>${escapeHtml(materialDisplayText(candidate.cannotAutoResolveReason))}</p>` : ""}
    ${evidence.sourceRefs ? `<p>${escapeHtml(evidence.sourceRefs)}</p>` : ""}
    <div class="governance-action-row">
      <button class="btn-secondary" type="button" disabled>等待批次预览</button>
      <button class="btn-primary-lg" type="button" disabled>确认前必须预览</button>
    </div>
  </article>`;
}

function renderMaterialCombinedRowCandidateCard(candidate) {
  const evidence = candidate.evidence || {};
  return `<article class="governance-card">
    <div class="governance-meta">
      <span class="governance-pill warning">合并行复核</span>
      <span class="governance-pill">仓 ${escapeHtml(candidate.warehouseId || "-")}</span>
      <span class="governance-pill">金额影响 ${formatMoney(Math.abs(candidate.amountGap || 0))}</span>
      <span class="governance-pill">工时影响 ${formatSignedNumber(Math.abs(candidate.hoursGap || 0))}</span>
    </div>
    <h3>${escapeHtml(candidate.pdfEmployeeName || "-")} → ${escapeHtml(candidate.excelEmployeeName || "-")}</h3>
    ${candidate.matchReason ? `<p><strong>${escapeHtml(materialDisplayText(candidate.matchReason))}</strong></p>` : ""}
    ${candidate.businessQuestion ? `<p>${escapeHtml(materialDisplayText(candidate.businessQuestion))}</p>` : ""}
    ${candidate.impactSummary ? `<p>${escapeHtml(materialDisplayText(candidate.impactSummary))}</p>` : ""}
    <p>${escapeHtml(materialDisplayText(candidate.recommendation || "疑似 PDF 一行覆盖多名员工，需人工核对原始发票。"))}</p>
    ${candidate.cannotAutoResolveReason ? `<p>${escapeHtml(materialDisplayText(candidate.cannotAutoResolveReason))}</p>` : ""}
    ${evidence.sourceRefs ? `<p>${escapeHtml(evidence.sourceRefs)}</p>` : ""}
    <div class="governance-action-row">
      <button class="btn-secondary" type="button" disabled>保留为异常证据</button>
      <button class="btn-primary-lg" type="button" disabled>不能自动清账</button>
    </div>
  </article>`;
}

async function handleMaterialReplayAction(event) {
  const button = event.target.closest("[data-material-action]");
  if (!button) return;
  const action = button.dataset.materialAction;
  if (action !== "create-run") return;
  if (!laborState.materialDryRun) return toast("请先执行测试材料验证。");
  const feedback = document.querySelector("#materialActionFeedback");
  const originalText = button.textContent;
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  button.textContent = "正在创建批次...";
  setMaterialActionFeedback("处理中", "正在从参考材料创建正式批次；创建完成后会提示下一步。");
  const startedAt = performance.now();
  const batchKey = laborState.materialDryRun?.batchKey || "";
  recordLaborTelemetry("labor.material.create_run.started", {
    step: "material_create_run",
    status: "started",
    context: { batchKey },
  });
  try {
    const dryRun = laborState.materialDryRun;
    const run = await requestJson("/api/labor/material-runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        batchKey: dryRun.batchKey,
        supplierName: labor.supplierName?.value?.trim() || dryRun.supplier || dryRun.directory || dryRun.batchKey,
        periodStart: labor.periodStart?.value || "",
        periodEnd: labor.periodEnd?.value || "",
        currency: labor.currency?.value?.trim() || "USD",
      }),
    });
    laborState.run = run;
    laborState.reocrBatchPreview = null;
    laborState.reocrBatchUpload = null;
    if (labor.chromeRunBadge) {
      labor.chromeRunBadge.hidden = false;
      labor.chromeRunLabel.textContent = `批次 #${run.id.slice(0, 8)}`;
    }
    if (labor.supplierName) labor.supplierName.value = run.supplierName || "";
    if (labor.periodStart) labor.periodStart.value = run.periodStart || "";
    if (labor.periodEnd) labor.periodEnd.value = run.periodEnd || "";
    if (labor.currency) labor.currency.value = run.currency || "USD";
    const nextStep = run.materialReplayNextStep || {};
    setText(labor.materialReplayStatus, `正式批次已创建：${run.id}`);
    if (labor.uploadStatus) setText(labor.uploadStatus, "已从参考材料复制文件。");
    if (labor.compareStatus) setText(labor.compareStatus, nextStep.description || "材料批次已预填文件和字段映射，可直接抽取并比对。");
    setMaterialActionFeedback(
      "正式批次已创建",
      `批次 ${run.id.slice(0, 8)} 已复制参考材料和字段映射。下一步：${nextStep.label || "抽取并比对"}。完成后再回到系统建议区处理待复核事项。`
    );
    if (feedback) feedback.scrollIntoView({ behavior: "smooth", block: "center" });
    recordLaborTelemetry("labor.material.create_run.succeeded", {
      run,
      runId: run.id,
      step: "material_create_run",
      status: "succeeded",
      durationMs: elapsedMs(startedAt),
      context: { batchKey },
    });
    toast(nextStep.label ? `已从真实材料创建正式批次，下一步：${nextStep.label}。` : "已从真实材料创建正式批次。");
  } catch (error) {
    recordLaborTelemetry("labor.material.create_run.failed", {
      step: "material_create_run",
      status: "failed",
      durationMs: elapsedMs(startedAt),
      errorMessage: error.message,
      context: { batchKey },
    });
    setText(labor.materialReplayStatus, error.message, true);
    setMaterialActionFeedback("创建失败", error.message, true);
    toast(error.message);
  } finally {
    button.disabled = false;
    button.removeAttribute("aria-busy");
    button.textContent = originalText;
  }
}

function setMaterialActionFeedback(title, message, isError = false) {
  const feedback = document.querySelector("#materialActionFeedback");
  if (!feedback) return;
  feedback.classList.add("visible");
  feedback.classList.toggle("error", Boolean(isError));
  feedback.innerHTML = `<strong>${escapeHtml(title || "")}</strong><span>${escapeHtml(message || "")}</span>`;
}

function advanceWizardStep(step) {
  document.querySelectorAll(".wz-step").forEach((button) => {
    button.classList.toggle("active", button.dataset.step === step);
  });
  document.querySelectorAll(".wz-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.panel === step);
  });
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
  if (labor.ruleGovernanceSection) labor.ruleGovernanceSection.hidden = true;
  if (labor.ruleGovernanceBody) labor.ruleGovernanceBody.innerHTML = "";
  if (labor.governanceStatus) labor.governanceStatus.textContent = "等待核对结果。";
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
  laborState.extractStartedAt = performance.now();
  recordLaborTelemetry("labor.extract.started", {
    step: "extract_compare",
    status: "started",
    context: { button: "extractCompare" },
  });

  try {
    laborState.run = await requestJson(`/api/labor/runs/${laborState.run.id}/extract-and-compare`, {
      method: "POST",
    });
    laborState.reocrBatchPreview = null;
    laborState.reocrBatchUpload = null;
    setText(labor.compareStatus, "后台抽取中，页面会自动刷新结果…");
    recordLaborTelemetry("labor.extract.submitted", {
      step: "extract_compare",
      status: "submitted",
      durationMs: elapsedMs(laborState.extractStartedAt),
    });
    await pollCompareResult();
    laborState.comparePollTimer = window.setInterval(pollCompareResult, 3000);
  } catch (error) {
    recordLaborTelemetry("labor.extract.failed", {
      step: "extract_compare",
      status: "failed",
      durationMs: elapsedMs(laborState.extractStartedAt),
      errorMessage: error.message,
    });
    laborState.extractStartedAt = null;
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
    recordLaborTelemetry("labor.extract.timeout", {
      step: "extract_compare",
      status: "timeout",
      durationMs: elapsedMs(laborState.extractStartedAt),
    });
    laborState.extractStartedAt = null;
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
      recordLaborTelemetry("labor.extract.failed", {
        run,
        step: "extract_compare",
        status: "failed",
        durationMs: elapsedMs(laborState.extractStartedAt),
        errorMessage: run.errorMessage || "抽取失败",
      });
      laborState.extractStartedAt = null;
      toast(run.errorMessage || "抽取失败。");
      return;
    }
    if (run.diffDownloadUrl || run.status === "已生成差异报告") {
      stopComparePolling();
      labor.extractCompare.disabled = false;
      renderResult(run);
      setText(labor.compareStatus, "核对完成。低置信度项已在风险表标记。");
      setDownload(run.diffDownloadUrl);
      recordLaborTelemetry("labor.extract.completed", {
        run,
        step: "extract_compare",
        status: "completed",
        durationMs: elapsedMs(laborState.extractStartedAt),
      });
      laborState.extractStartedAt = null;
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
    recordLaborTelemetry("labor.extract.failed", {
      step: "extract_compare",
      status: "failed",
      durationMs: elapsedMs(laborState.extractStartedAt),
      errorMessage: error.message,
    });
    laborState.extractStartedAt = null;
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
  renderReadinessGate(run.readinessGate);

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
  renderGovernancePanel(run);
  renderPendingItems(rows, run.candidateMatches || [], summary, run.reviewQueues || {});

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
    (summary.hoursDiffCount || 0) +
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

function renderReadinessGate(readinessGate) {
  const section = labor.conclusionSection;
  if (!section || !readinessGate) return;

  const status = readinessGate.status || "needs_review";
  const statusClass = ["ready", "needs_review", "blocked"].includes(status) ? status : "needs_review";
  const summary = readinessGate.summary || {};
  const issues = Array.isArray(readinessGate.issues) ? readinessGate.issues : [];
  const firstIssues = issues.slice(0, 3);
  const issueHtml = firstIssues.length
    ? `<ul class="readiness-issues">${firstIssues
        .map(
          (issue) => `<li><strong>${escapeHtml(issue.title || issue.code || "待处理")}</strong><span>${escapeHtml(
            issue.message || issue.action || ""
          )}</span></li>`
        )
        .join("")}</ul>`
    : `<p class="readiness-clear">正式结果、人工复核闭环和报告状态均满足当前上线门槛。</p>`;

  section.insertAdjacentHTML(
    "beforeend",
    `<div class="readiness-gate ${statusClass}">
      <div class="readiness-head">
        <span class="readiness-pill">${escapeHtml(readinessGate.label || "需复核")}</span>
        <span>上线就绪检查 · 阻断 ${summary.blockedCount || 0} · 待复核 ${summary.reviewCount || 0}</span>
      </div>
      ${issueHtml}
    </div>`
  );
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
    const status = c.issueType === "combined_pdf_row" ? "疑似PDF合并员工" : "姓名模糊匹配";
    allRows.push({
      name: `${c.pdfEmployeeName || ""} → ${c.excelEmployeeName || ""}`,
      status,
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

  const varianceRows = allRows.filter(r => r.hasVariance);
  const varianceCount = varianceRows.length;
  const totalCount = allRows.length;
  const passedCount = totalCount - varianceCount;
  const amountImpact = varianceRows.reduce((sum, row) => sum + Math.abs(Number(row.amountDelta || 0)), 0);
  const hoursImpact = varianceRows.reduce((sum, row) => sum + Math.abs(Number(row.hoursDelta || 0)), 0);

  const headers = ["员工", "状态", "PDF金额", "Excel金额", "差异", "PDF工时", "Excel工时", "工时差异"];
  const thead = `<thead><tr>${headers.map(h => `<th>${h}</th>`).join("")}</tr></thead>`;
  const visibleLimit = varianceCount > 0 ? 12 : 8;
  const visible = allRows.slice(0, visibleLimit);

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
      <span>已通过 <strong>${passedCount}</strong> 人</span>
    </div>
    <div class="recon-focus-grid">
      <div class="recon-focus-card"><span>当前优先看</span><strong>${varianceCount > 0 ? "差异最高的员工" : "通过样本"}</strong></div>
      <div class="recon-focus-card"><span>金额影响</span><strong>${formatMoney(amountImpact)}</strong></div>
      <div class="recon-focus-card"><span>工时影响</span><strong>${formatHours(hoursImpact)}</strong></div>
      <div class="recon-focus-card"><span>完整明细</span><strong>下载报告查看</strong></div>
    </div>
    <table>${thead}<tbody>${tbody}</tbody></table>
    ${allRows.length > visible.length ? `<p class="table-note">页面只展示最需要处理的 ${visible.length} 条；完整 ${allRows.length} 条明细请下载报告。</p>` : ""}
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

function renderGovernancePanel(run) {
  const section = labor.ruleGovernanceSection;
  const body = labor.ruleGovernanceBody;
  if (!section || !body) return;

  const hasResult = run && (run.diffDownloadUrl || run.status === "已生成差异报告");
  section.hidden = !hasResult;
  if (!hasResult) return;

  const governance = run.ruleGovernance || {};
  const nameMappingGovernance = run.nameMappingGovernance || {};
  const profileGovernance = run.profileGovernance || {};
  const correctionGovernance = run.correctionGovernance || {};
  const allocationGovernance = run.allocationGovernance || {};
  const governanceReport = run.files?.governanceAuditReport;
  const candidates = governance.candidates || [];
  const activeRules = governance.activeRules || [];
  const rolledBackRules = governance.rolledBackRules || [];
  const replaySummaries = governance.replaySummaries || {};
  const nameMappingCandidates = nameMappingGovernance.candidates || [];
  const activeNameMappings = nameMappingGovernance.activeMappings || [];
  const rolledBackNameMappings = nameMappingGovernance.rolledBackMappings || [];
  const nameMappingReplaySummaries = nameMappingGovernance.replaySummaries || {};
  const profileReplaySummaries = profileGovernance.replaySummaries || {};
  const correctionReplaySummaries = correctionGovernance.replaySummaries || {};
  const profileCandidates = profileGovernance.candidates || [];
  const activeProfiles = profileGovernance.activeProfiles || [];
  const rolledBackProfiles = profileGovernance.rolledBackProfiles || [];
  const correctionCandidates = correctionGovernance.candidates || [];
  const activeCorrections = correctionGovernance.activeCorrections || [];
  const rolledBackCorrections = correctionGovernance.rolledBackCorrections || [];
  const allocationCandidates = allocationGovernance.candidates || [];
  const activeAllocations = allocationGovernance.activeAllocations || [];
  const rolledBackAllocations = allocationGovernance.rolledBackAllocations || [];
  const reocrPlan = run.reocrPlan || {};
  const reocrTasks = Array.isArray(reocrPlan.tasks) ? reocrPlan.tasks : [];
  const reviewableReocrCandidates = Array.isArray(reocrPlan.reviewableCandidates) ? reocrPlan.reviewableCandidates : [];
  const reocrGovernance = run.reocrReplayGovernance || {};
  const reocrReplays = reocrGovernance.replays || [];
  const activeReocrCandidates = reocrGovernance.activeCandidates || [];
  const rolledBackReocrCandidates = reocrGovernance.rolledBackCandidates || [];
  const batchPreview = laborState.reocrBatchPreview?.runId === run.id ? laborState.reocrBatchPreview : null;
  const batchUpload = latestReocrBatchUpload(run);
  const batchPreflight = batchPreview?.preflight || run.reocrAdoption?.preflight || null;
  const batchPreflightMode = batchPreview?.preflight ? "preview" : run.reocrAdoption?.preflight ? "adopted" : "";
  const suggested = buildRuleCandidateSuggestion(run);
  const canSuggest = suggested && !candidates.some((item) => item.ruleId === suggested.ruleId);

  if (labor.governanceStatus) {
    const activeCount = activeRules.length + activeProfiles.length + activeCorrections.length + activeReocrCandidates.length + activeAllocations.length;
    const pendingCount = candidates.filter((item) => item.status !== "confirmed").length;
    const pendingNameMappingCount = nameMappingCandidates.filter((item) => item.status !== "confirmed").length;
    const pendingProfileCount = profileCandidates.filter((item) => item.status !== "confirmed").length;
    const pendingCorrectionCount = correctionCandidates.filter((item) => item.status !== "confirmed").length;
    const pendingAllocationCount = allocationCandidates.filter((item) => !["confirmed", "rolled_back"].includes(item.status) && !["confirmed", "rolled_back"].includes(item.decision)).length;
    const reocrCount = reocrTasks.length + reviewableReocrCandidates.length;
    labor.governanceStatus.textContent = `待人工处理 ${pendingCount + pendingNameMappingCount + pendingProfileCount + pendingCorrectionCount + pendingAllocationCount} · 图片识别复核 ${reocrCount} · 已留痕 ${
      activeCount + activeNameMappings.length
    } · 已撤回 ${
      rolledBackRules.length + rolledBackNameMappings.length + rolledBackProfiles.length + rolledBackCorrections.length + rolledBackReocrCandidates.length + rolledBackAllocations.length
    }`;
  }

  const commandHtml = `
    <div class="governance-command">
      <div>
        <strong>处理建议需人工复核后才生效</strong>
        <span>${suggested ? escapeHtml(suggested.description) : "当前批次暂无可自动生成的处理建议。"}</span>
      </div>
      <div class="governance-action-row">
        <button class="btn-secondary" type="button" data-governance-action="create-candidate" ${canSuggest ? "" : "disabled"}>生成处理建议</button>
        <button class="btn-secondary" type="button" data-governance-action="generate-governance-report">导出复核记录</button>
        ${governanceReport?.downloadUrl ? `<a class="governance-link" href="${escapeHtml(governanceReport.downloadUrl)}" download>下载复核记录</a>` : ""}
      </div>
    </div>
  `;
  const reocrGuideHtml = renderReocrWorkflowGuide(reocrTasks, reocrReplays, activeReocrCandidates);
  const batchCacheReplayHtml = renderBatchCacheReplayCommand(reviewableReocrCandidates);
  const batchConfirmReocrHtml = renderBatchReocrConfirmCommand(reocrReplays, activeReocrCandidates);
  const batchReocrHtml = renderBatchReocrApplyCommand(activeReocrCandidates, reocrTasks);
  const batchPreflightHtml = renderReocrBatchPreflightPanel(batchPreflight, batchPreflightMode, batchPreview?.summary || run.reocrAdoption?.summary);
  const batchUploadCoverageHtml = renderReocrUploadCoveragePanel(batchUpload);
  const actionFeedbackHtml = renderGovernanceActionFeedback(laborState.governanceActionFeedback);
  const confirmHtml = renderGovernanceConfirmPanel(laborState.governanceConfirm);
  const jsonInputHtml = renderReocrJsonInputPanel(laborState.reocrJsonInput);

  const reocrCards = [
    ...reocrTasks.map((task, index) => renderReocrTaskCard(task, index, latestReocrReplay(reocrReplays, task))),
    ...reviewableReocrCandidates.map((candidate) => renderReviewableReocrCard(candidate, latestReocrReplay(reocrReplays, candidate))),
    ...activeReocrCandidates.map((candidate) => renderActiveReocrCard(candidate, run.files?.reocrPreviewReport)),
    ...rolledBackReocrCandidates.map((candidate) => renderRollbackReocrCard(candidate)),
  ];
  const otherCards = [
    ...nameMappingCandidates.map((candidate) => renderNameMappingCandidateCard(candidate, nameMappingReplaySummaries[candidate.candidateId])),
    ...candidates.map((candidate) => renderGovernanceCandidateCard(candidate, replaySummaries[candidate.ruleId])),
    ...profileCandidates.map((candidate) => renderProfileCandidateCard(candidate, profileReplaySummaries[candidate.candidateId])),
    ...correctionCandidates.map((candidate) => renderCorrectionCandidateCard(candidate, correctionReplaySummaries[candidate.candidateId])),
    ...allocationCandidates.map(renderAllocationCandidateCard),
    ...activeRules.map((rule) => renderGovernanceActiveCard(rule)),
    ...activeNameMappings.map(renderNameMappingActiveCard),
    ...activeProfiles.map((profile) => renderProfileActiveCard(profile)),
    ...activeCorrections.map((correction) => renderCorrectionActiveCard(correction, run.files?.correctionPreviewReport)),
    ...activeAllocations.map(renderAllocationActiveCard),
    ...rolledBackRules.map((rule) => renderGovernanceRollbackCard(rule)),
    ...rolledBackNameMappings.map(renderNameMappingRollbackCard),
    ...rolledBackProfiles.map((profile) => renderProfileRollbackCard(profile)),
    ...rolledBackCorrections.map((correction) => renderCorrectionRollbackCard(correction)),
    ...rolledBackAllocations.map(renderAllocationRollbackCard),
  ];
  const cardDeckHtml = [
    renderGovernanceCardDeck(reocrCards, {
      title: "图片识别任务",
      limit: 3,
      collapsedLabel: "展开其余图片识别任务",
    }),
    renderGovernanceCardDeck(otherCards, {
      title: "其他复核候选",
      limit: 8,
      collapsedLabel: "展开其余复核候选",
    }),
  ].join("");

  body.innerHTML = `
    ${actionFeedbackHtml}
    ${confirmHtml}
    ${jsonInputHtml}
    ${commandHtml}
    ${reocrGuideHtml}
    ${batchUploadCoverageHtml}
    ${batchCacheReplayHtml}
    ${batchConfirmReocrHtml}
    ${batchReocrHtml}
    ${batchPreflightHtml}
    ${
      cardDeckHtml
        ? cardDeckHtml
        : `<div class="governance-empty">暂无待复核建议。完成核对后，可根据异常诊断生成处理建议，并先预览影响。</div>`
    }
  `;
}

function renderGovernanceActionFeedback(feedback) {
  if (!feedback) return "";
  const kind = ["success", "error", "info", "loading"].includes(feedback.kind) ? feedback.kind : "info";
  const action = feedback.action ? `<span>${escapeHtml(feedback.action)}</span>` : "";
  return `<div class="governance-action-feedback ${kind}" role="status" aria-live="polite" tabindex="-1" data-governance-action-feedback>
    <div>
      <strong>${escapeHtml(feedback.title || "处理状态")}</strong>
      <p>${escapeHtml(feedback.message || "")}</p>
    </div>
    ${action}
  </div>`;
}

function setGovernancePersistentFeedback(kind, title, message, action = "") {
  laborState.governanceActionFeedback = { kind, title, message, action, timestamp: Date.now() };
  if (labor.governanceStatus) labor.governanceStatus.textContent = `${title}${message ? `：${message}` : ""}`;
}

function revealGovernanceFeedback() {
  const feedback = labor.ruleGovernanceBody?.querySelector("[data-governance-action-feedback]");
  if (!feedback) return;
  feedback.scrollIntoView({ behavior: "smooth", block: "center" });
  feedback.focus({ preventScroll: true });
}

function latestReocrBatchUpload(run) {
  if (!run) return null;
  if (laborState.reocrBatchUpload?.runId === run.id) return laborState.reocrBatchUpload;
  const records = Array.isArray(run.files?.reocrCandidateFiles) ? run.files.reocrCandidateFiles : [];
  const latest = [...records].reverse().find((record) => record?.coverage || record?.summary);
  return latest ? { runId: run.id, candidateFile: latest, summary: latest.summary || {}, coverage: latest.coverage || null } : null;
}

function renderReocrUploadCoveragePanel(upload) {
  if (!upload) return "";
  const summary = upload.summary || upload.candidateFile?.summary || {};
  const coverage = upload.coverage || upload.candidateFile?.coverage || {};
  if (!summary && !coverage) return "";
  const missingTasks = Array.isArray(coverage.missingTasks) ? coverage.missingTasks : [];
  const extraScopes = Array.isArray(coverage.extraScopes) ? coverage.extraScopes : [];
  const uploadedScopes = Array.isArray(coverage.uploadedScopes) ? coverage.uploadedScopes : [];
  const coverageComplete = Boolean(coverage.coverageComplete);
  const missingHtml = missingTasks
    .slice(0, 6)
    .map((item) => `<li>${escapeHtml(item.sourceFile || "-")} · 仓 ${escapeHtml(item.warehouseId || "-")}</li>`)
    .join("");
  const extraHtml = extraScopes
    .slice(0, 6)
    .map((item) => `<li>${escapeHtml(item.sourceFile || "-")} · 仓 ${escapeHtml(item.warehouseId || "-")} · ${escapeHtml(item.rowCount || 0)} 行</li>`)
    .join("");
  const uploadedHtml = uploadedScopes
    .slice(0, 6)
    .map((item) => `<span class="governance-pill">${escapeHtml(item.sourceFile || "-")} · 仓 ${escapeHtml(item.warehouseId || "-")} · ${escapeHtml(item.rowCount || 0)} 行</span>`)
    .join("");
  const detailHtml = [
    missingHtml
      ? `<div><span>缺失计划任务</span><ul class="reocr-evidence-list">${missingHtml}</ul></div>`
      : "",
    extraHtml
      ? `<div><span>计划外范围</span><ul class="reocr-evidence-list">${extraHtml}</ul></div>`
      : "",
  ].join("");
  return `<div class="reocr-preflight ${coverageComplete ? "ready" : "blocked"}">
    <div class="reocr-preflight-head">
      <div>
        <strong>批量上传覆盖率</strong>
        <span>${escapeHtml(upload.candidateFile?.filename || "本次上传")} · 预览 ${escapeHtml(summary.replayedCount || 0)} 组 · 通过 ${escapeHtml(summary.readyCount || 0)} · 阻断 ${escapeHtml(summary.blockedCount || 0)}</span>
      </div>
      <span class="governance-pill ${coverageComplete ? "ok" : "danger"}">${coverageComplete ? "覆盖完整" : "覆盖不完整"}</span>
    </div>
    <div class="reocr-preflight-stats">
      <div><span>计划任务</span><strong>${summary.plannedTaskCount ?? coverage.plannedTaskCount ?? 0}</strong></div>
      <div><span>已覆盖</span><strong>${summary.coveredTaskCount ?? coverage.coveredTaskCount ?? 0}</strong></div>
      <div><span>缺失任务</span><strong>${summary.missingTaskCount ?? coverage.missingTaskCount ?? 0}</strong></div>
      <div><span>计划外范围</span><strong>${summary.extraScopeCount ?? coverage.extraScopeCount ?? 0}</strong></div>
      <div><span>解析行数</span><strong>${summary.parsedRowCount || 0}</strong></div>
      <div><span>错误范围</span><strong>${summary.errorCount || 0}</strong></div>
    </div>
    ${detailHtml || `<p class="reocr-preflight-clear">批量识别结果覆盖了当前计划任务；仍需逐项预览通过并人工确认。</p>`}
    ${uploadedHtml ? `<div class="reocr-preflight-meta"><div><span>已上传范围</span><div class="governance-meta">${uploadedHtml}</div></div></div>` : ""}
  </div>`;
}

function renderBatchReocrConfirmCommand(replays, activeCandidates) {
  const activeScopes = new Set((activeCandidates || []).map((candidate) => `${candidate.sourceFile || ""}::${candidate.warehouseId || ""}`));
  const ready = (replays || []).filter(
    (replay) =>
      replay.decision === "ready_for_user_confirmation" &&
      replay.sourceFile &&
      !activeScopes.has(`${replay.sourceFile || ""}::${replay.warehouseId || ""}`)
  );
  if (ready.length < 2) return "";
  const amount = ready.reduce((sum, replay) => sum + Number(replay.summary?.candidateAmountTotal || 0), 0);
  return `<div class="governance-command">
    <div>
      <strong>批量提交图片识别复核意见</strong>
      <span>${ready.length} 个预览已通过 · 识别结果合计 $${formatMoney(amount)} · 只记录复核意见，不覆盖正式结果</span>
    </div>
    <div class="governance-action-row">
      <button class="btn-primary-lg" type="button" data-governance-action="confirm-reocr-batch">批量提交复核意见</button>
    </div>
  </div>`;
}

function renderBatchCacheReplayCommand(reviewableCandidates) {
  const candidates = Array.isArray(reviewableCandidates) ? reviewableCandidates : [];
  if (!candidates.length) return "";
  const total = candidates.reduce((sum, candidate) => sum + Number(candidate.currentCacheAmount || 0), 0);
  const expected = candidates.reduce((sum, candidate) => sum + Number(candidate.expectedExcelAmount || 0), 0);
  return `<div class="governance-command">
    <div>
      <strong>批量核对历史图片识别记录</strong>
      <span>${candidates.length} 个可复核识别结果 · 历史识别 $${formatMoney(total)} · 账单 $${formatMoney(expected)} · 仅生成预览记录，不自动确认</span>
    </div>
    <div class="governance-action-row">
      <button class="btn-secondary" type="button" data-governance-action="batch-replay-cache-reocr">批量预览影响</button>
    </div>
  </div>`;
}

function renderBatchReocrApplyCommand(activeCandidates, reocrTasks) {
  const pending = (activeCandidates || []).filter((candidate) => candidate.status !== "applied" && candidate.decision !== "applied");
  if (pending.length < 2) return "";
  const total = pending.reduce((sum, candidate) => sum + Number(candidate.replay?.summary?.candidateAmountTotal || 0), 0);
  const exceptions = pending.reduce((sum, candidate) => sum + Number(candidate.replay?.summary?.exceptionCount || 0), 0);
  const plannedCount = Array.isArray(reocrTasks) ? reocrTasks.length : 0;
  const confirmedScopes = new Set((activeCandidates || []).map((candidate) => `${candidate.sourceFile || ""}::${candidate.warehouseId || ""}`));
  const pendingPlanCount = plannedCount
    ? reocrTasks.filter((task) => !confirmedScopes.has(`${task.sourceFile || ""}::${task.warehouseId || ""}`)).length
    : 0;
  return `<div class="governance-command">
    <div>
      <strong>批量采纳图片识别结果</strong>
      <span>${pending.length} 个已复核识别结果 · 识别结果合计 $${formatMoney(total)} · 异常 ${exceptions}${plannedCount ? ` · 计划 ${plannedCount} 个，待复核 ${pendingPlanCount} 个` : ""}</span>
    </div>
    <div class="governance-action-row">
      <button class="btn-secondary" type="button" data-governance-action="preview-reocr-batch">批量预览</button>
      <button class="btn-primary-lg" type="button" data-governance-action="apply-reocr-batch">批量采纳</button>
    </div>
  </div>`;
}

function renderGovernanceConfirmPanel(confirm) {
  if (!confirm) return "";
  const warningHtml = Array.isArray(confirm.warnings) && confirm.warnings.length
    ? `<ul class="reocr-preflight-warnings">${confirm.warnings.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`
    : `<p class="reocr-preflight-clear">${escapeHtml(confirm.message || "请确认影响摘要后再执行。")}</p>`;
  return `<div class="governance-confirm" data-governance-confirm-panel>
    <div class="reocr-preflight-head">
      <div>
        <strong>${escapeHtml(confirm.title || "提交复核结论")}</strong>
        <span>${escapeHtml(confirm.subtitle || "需要填写人工复核意见")}</span>
      </div>
      <span class="governance-pill warning">待确认</span>
    </div>
    ${confirm.summaryHtml || ""}
    ${warningHtml}
    <label class="governance-confirm-field">
      <span>确认原因</span>
      <textarea data-governance-confirm-reason rows="3">${escapeHtml(confirm.defaultReason || "")}</textarea>
    </label>
    <div class="governance-action-row">
      <button class="btn-primary-lg" type="button" data-governance-action="submit-governance-confirm">提交复核结论</button>
      <button class="btn-secondary" type="button" data-governance-action="cancel-governance-confirm">取消</button>
    </div>
  </div>`;
}

function renderReocrJsonInputPanel(input) {
  if (!input) return "";
  return `<div class="governance-confirm">
    <div class="reocr-preflight-head">
      <div>
        <strong>粘贴新识别明细</strong>
        <span>${escapeHtml(input.task?.sourceFile || "PDF")} · 仓 ${escapeHtml(input.task?.warehouseId || "-")} · JSON 数组</span>
      </div>
      <span class="governance-pill warning">待预览</span>
    </div>
    <p class="reocr-preflight-clear">提交后只生成识别预览记录，不会确认，也不会覆盖正式核对结果。</p>
    <label class="governance-confirm-field">
      <span>识别明细 JSON</span>
      <textarea data-reocr-json-input rows="12">${escapeHtml(input.value || "")}</textarea>
    </label>
    <div class="governance-action-row">
      <button class="btn-primary-lg" type="button" data-governance-action="submit-reocr-json">提交预览</button>
      <button class="btn-secondary" type="button" data-governance-action="cancel-reocr-json">取消</button>
    </div>
  </div>`;
}

function buildSingleReocrPreflight(candidate) {
  const replay = candidate?.replay || {};
  const rows = Array.isArray(replay.comparisonRows) ? replay.comparisonRows : Array.isArray(replay.previewRows) ? replay.previewRows : [];
  const comparison = replay.comparison || {};
  const current = laborState.run?.comparisonSummary || {};
  const affectedEmployees = Array.from(
    new Set(
      rows
        .map((row) => String(row.employeeName || row.pdfEmployeeName || row.excelEmployeeName || "").trim())
        .filter(Boolean)
    )
  ).sort();
  const exceptionCount = Number(comparison.exceptionCount || 0);
  const delta = {};
  ["amountDeltaTotal", "exceptionCount", "pdfAmountTotal", "excelAmountTotal", "lowConfidenceCount"].forEach((key) => {
    if (typeof comparison[key] === "number" && typeof current[key] === "number") {
      delta[key] = Number((comparison[key] - current[key]).toFixed(4));
    }
  });
  const warnings = [];
  if (exceptionCount) warnings.push(`投影结果仍有 ${exceptionCount} 项异常，采纳后仍需人工复核。`);
  return {
    willOverwriteOfficialResult: true,
    willRegenerateDiffReport: true,
    current: pickPreflightSummary(current),
    projected: pickPreflightSummary(comparison),
    delta,
    affectedScopeCount: 1,
    affectedEmployeeCount: affectedEmployees.length,
    affectedEmployees: affectedEmployees.slice(0, 50),
    coverageCompleteAfterApply: true,
    blockingAfterApply: Boolean(exceptionCount),
    postApplyWarnings: warnings,
    formalResultFields: ["comparisonSummary", "comparisonRows", "candidateMatches", "diffDownloadUrl"],
  };
}

function pickPreflightSummary(summary) {
  const keys = [
    "pdfAmountTotal",
    "excelAmountTotal",
    "amountDeltaTotal",
    "pdfHoursTotal",
    "excelHoursTotal",
    "hoursDeltaTotal",
    "exceptionCount",
    "lowConfidenceCount",
    "amountDiffCount",
    "hoursRiskCount",
    "matchRate",
  ];
  return keys.reduce((result, key) => {
    if (summary && Object.prototype.hasOwnProperty.call(summary, key)) result[key] = summary[key];
    return result;
  }, {});
}

function renderReocrBatchPreflightPanel(preflight, mode = "", summary = {}) {
  if (!preflight) return "";
  const currentDelta = Number(preflight.current?.amountDeltaTotal || 0);
  const projectedDelta = Number(preflight.projected?.amountDeltaTotal || 0);
  const deltaChange = Number(preflight.delta?.amountDeltaTotal || 0);
  const currentExceptions = Number(preflight.current?.exceptionCount || 0);
  const projectedExceptions = Number(preflight.projected?.exceptionCount || 0);
  const warnings = Array.isArray(preflight.postApplyWarnings) ? preflight.postApplyWarnings : [];
  const fields = Array.isArray(preflight.formalResultFields) ? preflight.formalResultFields : [];
  const employees = Array.isArray(preflight.affectedEmployees) ? preflight.affectedEmployees.slice(0, 8) : [];
  const statusLabel = preflight.blockingAfterApply ? "采纳后仍需复核" : "采纳后可进入正式结果";
  const modeLabel = mode === "adopted" ? "已采纳记录" : "采纳前预览";
  const warningHtml = warnings.length
    ? `<ul class="reocr-preflight-warnings">${warnings.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`
    : `<p class="reocr-preflight-clear">采纳后将更新正式核对结果和差异报告。</p>`;
  const employeesHtml = employees.length
    ? employees.map((name) => `<span class="governance-pill">${escapeHtml(name)}</span>`).join("")
    : `<span class="governance-pill">员工明细见预览报告</span>`;
  const fieldsHtml = fields.length
    ? fields.map((field) => `<span class="governance-pill warning">${escapeHtml(field)}</span>`).join("")
    : `<span class="governance-pill warning">正式结果字段</span>`;

  return `<div class="reocr-preflight ${preflight.blockingAfterApply ? "blocked" : "ready"}">
    <div class="reocr-preflight-head">
      <div>
        <strong>图片识别采纳影响摘要</strong>
        <span>${modeLabel} · ${statusLabel}</span>
      </div>
      <span class="governance-pill ${preflight.blockingAfterApply ? "danger" : "ok"}">${escapeHtml(statusLabel)}</span>
    </div>
    <div class="reocr-preflight-stats">
      <div><span>影响范围</span><strong>${preflight.affectedScopeCount || 0} 个</strong></div>
      <div><span>影响员工</span><strong>${preflight.affectedEmployeeCount || 0} 人</strong></div>
      <div><span>识别结果</span><strong>${summary?.candidateCount || 0} 个</strong></div>
      <div><span>采纳覆盖</span><strong>${preflight.coverageCompleteAfterApply ? "完整" : "不完整"}</strong></div>
      <div><span>当前金额差额</span><strong>${formatSignedMoney(currentDelta)}</strong></div>
      <div><span>投影金额差额</span><strong>${formatSignedMoney(projectedDelta)}</strong></div>
      <div><span>金额差额变化</span><strong>${formatSignedMoney(deltaChange)}</strong></div>
      <div><span>异常变化</span><strong>${formatSignedNumber(projectedExceptions - currentExceptions)}</strong></div>
    </div>
    ${warningHtml}
    <div class="reocr-preflight-meta">
      <div>
        <span>将覆盖字段</span>
        <div class="governance-meta">${fieldsHtml}</div>
      </div>
      <div>
        <span>样例员工</span>
        <div class="governance-meta">${employeesHtml}</div>
      </div>
    </div>
  </div>`;
}

function renderReocrWorkflowGuide(tasks, replays, activeCandidates) {
  const taskCount = Array.isArray(tasks) ? tasks.length : 0;
  if (!taskCount) return "";
  const replayCount = Array.isArray(replays)
    ? replays.filter((item) => item.mode === "new_ocr_candidate_replay").length
    : 0;
  const activeCount = Array.isArray(activeCandidates) ? activeCandidates.length : 0;
  const steps = [
    {
      label: "下载模板",
      value: `${taskCount} 个任务`,
      state: "ok",
    },
    {
      label: "上传识别结果并预览",
      value: replayCount ? `${replayCount} 次预览` : "等待识别文件",
      state: replayCount ? "ok" : "warning",
    },
    {
      label: "提交复核意见",
      value: activeCount ? `${activeCount} 个已确认` : "预览通过后可确认",
      state: activeCount ? "ok" : "warning",
    },
  ];
  return `<div class="reocr-guide" aria-label="图片识别复核操作流程">
    ${steps
      .map(
        (step, index) => `<div class="reocr-step ${step.state}">
          <span class="reocr-step-index">${index + 1}</span>
          <span class="reocr-step-label">${escapeHtml(step.label)}</span>
          <span class="reocr-step-value">${escapeHtml(step.value)}</span>
        </div>`
      )
      .join("")}
    <div class="governance-action-row">
      <button class="btn-secondary" type="button" data-governance-action="download-reocr-template-batch">批量下载模板</button>
      <button class="btn-secondary" type="button" data-governance-action="upload-reocr-batch">批量上传识别结果</button>
    </div>
  </div>`;
}

function latestReocrReplay(replays, task) {
  if (!Array.isArray(replays) || !task) return null;
  const sourceFile = String(task.sourceFile || "");
  const warehouseId = String(task.warehouseId || "");
  return (
    [...replays]
      .reverse()
      .find((item) => String(item.sourceFile || "") === sourceFile && String(item.warehouseId || "") === warehouseId) || null
  );
}

function renderReocrTaskCard(task, index, replay) {
  const replayDecision = replay && replay.decision;
  const diagnosticsHtml = renderReocrDiagnostics(task.diagnostics);
  const textCoverageHtml = renderPdfTextCoverage(task.pdfTextCoverage, task.extractionPrerequisite);
  const replayClass =
    replayDecision === "ready_for_user_confirmation"
      ? "ok"
      : replayDecision === "blocked_by_replay"
      ? "danger"
      : "warning";
  const replayText = replay
    ? `已预览 ${replay.summary?.candidateRowCount || 0} 行 · 异常 ${replay.summary?.exceptionCount || 0}`
    : "未预览";
  return `<article class="governance-card">
    <div class="governance-meta">
      <span class="governance-pill danger">图片识别复核</span>
      <span class="governance-pill">仓 ${escapeHtml(task.warehouseId || "-")}</span>
      <span class="governance-pill ${replayClass}">${escapeHtml(replayText)}</span>
    </div>
    <h3>${escapeHtml(task.sourceFile || "待处理 PDF")}</h3>
    <p>${escapeHtml(task.reason || task.confirmationGate || "历史识别结果与账单不一致，需要上传图片识别结果并预览影响。")}</p>
    <div class="governance-meta">
      <span class="governance-pill">账单 $${formatMoney(task.expectedExcelAmount)}</span>
      <span class="governance-pill">历史识别 $${formatMoney(task.currentCacheAmount)}</span>
      <span class="governance-pill">差额 $${formatMoney(task.amountDelta)}</span>
    </div>
    ${textCoverageHtml}
    ${diagnosticsHtml}
    <div class="governance-action-row">
      <button class="btn-secondary" type="button" data-governance-action="download-reocr-template" data-task-index="${index}">下载模板</button>
      <button class="btn-secondary" type="button" data-governance-action="upload-reocr" data-task-index="${index}">上传识别结果并预览</button>
      <button class="btn-secondary" type="button" data-governance-action="replay-reocr" data-task-index="${index}">粘贴 JSON</button>
      <button class="btn-primary-lg" type="button" data-governance-action="confirm-reocr" data-source-file="${escapeHtml(task.sourceFile || "")}" data-warehouse-id="${escapeHtml(task.warehouseId || "")}" ${
        replayDecision === "ready_for_user_confirmation" ? "" : "disabled"
      }>填写复核意见</button>
    </div>
  </article>`;
}

function renderReviewableReocrCard(candidate, replay) {
  const replayDecision = replay && replay.decision;
  const diagnosticsHtml = renderReocrDiagnostics(candidate.diagnostics);
  const textCoverageHtml = renderPdfTextCoverage(candidate.pdfTextCoverage, candidate.extractionPrerequisite);
  const replayClass = replayDecision === "ready_for_user_confirmation" ? "ok" : replayDecision ? "danger" : "warning";
  const replayText = replay ? `已预览 · 异常 ${replay.summary?.exceptionCount || 0}` : "可人工复核";
  return `<article class="governance-card">
    <div class="governance-meta">
      <span class="governance-pill warning">历史图片识别</span>
      <span class="governance-pill">仓 ${escapeHtml(candidate.warehouseId || "-")}</span>
      <span class="governance-pill ${replayClass}">${escapeHtml(replayText)}</span>
    </div>
    <h3>${escapeHtml(candidate.sourceFile || "历史图片识别结果")}</h3>
    <p>${escapeHtml(candidate.recommendation || "文件级金额已接近账单，可作为待复核证据；确认前不会覆盖核对结论。")}</p>
    <div class="governance-meta">
      <span class="governance-pill">账单 $${formatMoney(candidate.expectedExcelAmount)}</span>
      <span class="governance-pill">历史识别 $${formatMoney(candidate.currentCacheAmount)}</span>
      <span class="governance-pill">差额 $${formatMoney(candidate.amountDelta)}</span>
    </div>
    ${textCoverageHtml}
    ${diagnosticsHtml}
    <div class="governance-action-row">
      <button class="btn-secondary" type="button" data-governance-action="replay-cache-reocr" data-source-file="${escapeHtml(candidate.sourceFile || "")}" data-warehouse-id="${escapeHtml(candidate.warehouseId || "")}">预览识别影响</button>
      <button class="btn-primary-lg" type="button" data-governance-action="confirm-reocr" data-source-file="${escapeHtml(candidate.sourceFile || "")}" data-warehouse-id="${escapeHtml(candidate.warehouseId || "")}" ${
        replayDecision === "ready_for_user_confirmation" ? "" : "disabled"
      }>填写复核意见</button>
    </div>
  </article>`;
}

function renderPdfTextCoverage(coverage, prerequisite = "") {
  if (!coverage || typeof coverage !== "object") return "";
  const needsOcr = Boolean(coverage.needsOcr);
  const stateClass = needsOcr ? "danger" : "ok";
  const stateText = needsOcr ? "PDF无文本层" : "PDF文本可读";
  const pageCount = Number(coverage.pageCount || 0);
  const readablePageCount = Number(coverage.readablePageCount || 0);
  const emptyTextPageCount = Number(coverage.emptyTextPageCount || 0);
  const prerequisiteText =
    prerequisite === "pdf_text_layer_empty_requires_ocr"
      ? "PDF 文本不可直接读取，需要上传图片识别结果并预览"
      : coverage.diagnostic || "";
  return `<div class="reocr-diagnostics">
    <div class="reocr-diagnostics-head">
      <span>${escapeHtml(prerequisiteText || stateText)}</span>
      <small>${pageCount} 页 · 可读 ${readablePageCount} · 空文本 ${emptyTextPageCount}</small>
    </div>
    <div class="governance-meta">
      <span class="governance-pill ${stateClass}">${escapeHtml(stateText)}</span>
      ${needsOcr ? `<span class="governance-pill warning">必须人工复核</span>` : ""}
    </div>
  </div>`;
}

function renderReocrDiagnostics(diagnostics) {
  if (!diagnostics || typeof diagnostics !== "object") return "";
  const summary = diagnostics.summary || {};
  const action = reocrActionLabel(diagnostics.recommendedAction);
  const hints = Array.isArray(diagnostics.rootCauseHints) ? diagnostics.rootCauseHints.map(reocrHintLabel) : [];
  const pairs = Array.isArray(diagnostics.suspectedNamePairs) ? diagnostics.suspectedNamePairs.slice(0, 2) : [];
  const topDiffs = Array.isArray(diagnostics.topDifferences) ? diagnostics.topDifferences.slice(0, 2) : [];
  const pairHtml = pairs
    .map(
      (pair) => `<li>
        <strong>${escapeHtml(pair.cacheEmployeeName || "-")}</strong>
        <span>⇄ ${escapeHtml(pair.excelEmployeeName || "-")} · $${formatMoney(pair.cacheAmount)} / $${formatMoney(pair.excelAmount)} · 工时 ${formatHours(pair.cacheHours)} / ${formatHours(pair.excelHours)}</span>
      </li>`
    )
    .join("");
  const diffHtml = topDiffs
    .map(
      (row) => `<li>
        <strong>${escapeHtml(row.employeeName || "-")}</strong>
        <span>${escapeHtml(row.matchStatus || "")} · 差额 ${Number(row.amountDelta || 0) >= 0 ? "+" : "-"}$${formatMoney(Math.abs(Number(row.amountDelta || 0)))}</span>
      </li>`
    )
    .join("");
  return `<div class="reocr-diagnostics">
    <div class="reocr-diagnostics-head">
      <span>${escapeHtml(action)}</span>
      <small>异常 ${escapeHtml(summary.exceptionCount || 0)} · 疑似姓名 ${escapeHtml(summary.suspectedNamePairCount || 0)}</small>
    </div>
    ${hints.length ? `<div class="governance-meta">${hints.map((hint) => `<span class="governance-pill warning">${escapeHtml(hint)}</span>`).join("")}</div>` : ""}
    ${pairHtml ? `<ul class="reocr-evidence-list">${pairHtml}</ul>` : diffHtml ? `<ul class="reocr-evidence-list">${diffHtml}</ul>` : ""}
  </div>`;
}

function reocrActionLabel(action) {
  const labels = {
    review_name_mapping_before_reocr: "先复核姓名匹配",
    review_name_mapping_then_reocr_if_amounts_remain_unexplained: "先复核姓名，再决定是否补充图片识别结果",
    reocr_with_employee_level_review: "补充图片识别结果并做员工级复核",
    review_amount_hours_basis_then_reocr_if_needed: "先复核金额/工时口径",
    review_file_manually: "人工复核文件",
  };
  return labels[action] || "人工复核后再处理";
}

function reocrHintLabel(hint) {
  const labels = {
    possible_name_mapping: "疑似姓名匹配",
    possible_missing_cache_rows: "缓存漏行",
    possible_extra_cache_rows: "缓存多行",
    employee_amount_or_hours_mismatch: "金额/工时不一致",
    possible_combined_pdf_row: "疑似合并行",
  };
  return labels[hint] || hint;
}

function renderActiveReocrCard(candidate, reportFile) {
  const applied = candidate.status === "applied" || candidate.decision === "applied";
  const reportLink = reportFile?.downloadUrl
    ? `<a class="governance-link" href="${escapeHtml(reportFile.downloadUrl)}" download>下载图片识别预览报告</a>`
    : "";
  const replaySummary = candidate.replay?.summary || {};
  const preflight = candidate.preflight || buildSingleReocrPreflight(candidate);
  return `<article class="governance-card">
    <div class="governance-meta">
      <span class="governance-pill ${applied ? "ok" : "warning"}">${applied ? "图片识别已采纳" : "已确认待采纳"}</span>
      <span class="governance-pill">仓 ${escapeHtml(candidate.warehouseId || "-")}</span>
      <span class="governance-pill">${escapeHtml(candidate.confirmedBy || "user")}</span>
    </div>
    <h3>${escapeHtml(candidate.sourceFile || "图片识别结果")}</h3>
    <p>${escapeHtml(applied ? candidate.applicationReason || "识别结果已采纳为当前批次正式核对依据。" : candidate.confirmationReason || "识别结果已通过预览并人工确认；正式结果和差异报告尚未更新。")}</p>
    <div class="governance-meta">
      <span class="governance-pill">识别结果 $${formatMoney(replaySummary.candidateAmountTotal)}</span>
      <span class="governance-pill">账单 $${formatMoney(replaySummary.expectedExcelAmount)}</span>
      <span class="governance-pill">异常 ${escapeHtml(replaySummary.exceptionCount || 0)}</span>
    </div>
    ${renderReocrBatchPreflightPanel(preflight, applied ? "adopted" : "preview", { candidateCount: 1 })}
    <div class="governance-action-row">
      ${reportLink}
      <button class="btn-primary-lg" type="button" data-governance-action="apply-reocr" data-candidate-id="${escapeHtml(candidate.candidateId || "")}" ${applied ? "disabled" : ""}>采纳为当前批次结果</button>
      <button class="btn-secondary" type="button" data-governance-action="rollback-reocr" data-candidate-id="${escapeHtml(candidate.candidateId || "")}">撤回识别结果</button>
    </div>
  </article>`;
}

function renderRollbackReocrCard(candidate) {
  const replaySummary = candidate.replay?.summary || {};
  return `<article class="governance-card">
    <div class="governance-meta">
      <span class="governance-pill danger">图片识别已撤回</span>
      <span class="governance-pill">仓 ${escapeHtml(candidate.warehouseId || "-")}</span>
      <span class="governance-pill">${escapeHtml(candidate.rolledBackBy || "user")}</span>
    </div>
    <h3>${escapeHtml(candidate.sourceFile || "图片识别结果")}</h3>
    <p>${escapeHtml(candidate.rollbackReason || "该识别结果已撤回，不再作为已确认记录参与预览。")}</p>
    <div class="governance-meta">
      <span class="governance-pill">识别结果 $${formatMoney(replaySummary.candidateAmountTotal)}</span>
      <span class="governance-pill">账单 $${formatMoney(replaySummary.expectedExcelAmount)}</span>
      <span class="governance-pill">异常 ${escapeHtml(replaySummary.exceptionCount || 0)}</span>
    </div>
  </article>`;
}

function renderNameMappingCandidateCard(candidate, replay) {
  const status = candidate.status || "";
  const decision = candidate.decision || "";
  const disabled = ["confirmed", "active", "rolled_back"].includes(status) || ["confirmed", "active", "rolled_back"].includes(decision);
  const replayDecision = replay && replay.decision;
  const canConfirm = !disabled && replayDecision === "ready_for_user_confirmation";
  const statusLabel = status === "rolled_back" || decision === "rolled_back"
    ? "姓名匹配已撤回"
    : status === "confirmed" || decision === "confirmed"
      ? "姓名匹配已确认"
      : canConfirm
        ? "预览通过，可填写意见"
        : replayDecision
          ? "预览未改善，先复核差异"
          : "疑似同一员工，先预览影响";
  const evidence = candidate.evidence || {};
  const replayClass = replayDecision === "ready_for_user_confirmation" ? "ok" : replayDecision ? "danger" : "warning";
  const replaySummary = replay?.summary || {};
  const replayText = replay
    ? `预览：可修复 ${replaySummary.fixedCount || 0} · 新增风险 ${replaySummary.regressionCount || 0}`
    : "未预览";
  const historicalText = replay
    ? `历史 ${replaySummary.historicalCheckedCount || 0} 批 · 缺明细 ${replaySummary.historicalInsufficientCount || 0}`
    : "";
  return `<article class="governance-card">
    <div class="governance-meta">
      <span class="governance-pill ${disabled ? "ok" : "warning"}">${escapeHtml(statusLabel)}</span>
      <span class="governance-pill">仓 ${escapeHtml(candidate.warehouseId || "-")}</span>
      <span class="governance-pill ${replayClass}">${escapeHtml(replayText)}</span>
      ${historicalText ? `<span class="governance-pill">${escapeHtml(historicalText)}</span>` : ""}
      <span class="governance-pill">金额差 ${formatSignedMoney(candidate.amountGap || 0)}</span>
      <span class="governance-pill">工时差 ${formatSignedNumber(candidate.hoursGap || 0)}</span>
    </div>
    <h3>${escapeHtml(candidate.cacheEmployeeName || "-")} ⇄ ${escapeHtml(candidate.excelEmployeeName || "-")}</h3>
    ${candidate.matchReason ? `<p><strong>${escapeHtml(candidate.matchReason)}</strong></p>` : ""}
    ${candidate.businessQuestion ? `<p>${escapeHtml(candidate.businessQuestion)}</p>` : ""}
    ${candidate.impactSummary ? `<p>影响：${escapeHtml(candidate.impactSummary)}</p>` : ""}
    ${candidate.cannotAutoResolveReason ? `<p>${escapeHtml(candidate.cannotAutoResolveReason)}</p>` : ""}
    <p>${escapeHtml(candidate.recommendation || "金额/工时接近，需人工确认是否为同一员工。")}</p>
    ${evidence.sourceRefs ? `<p>${escapeHtml(evidence.sourceRefs)}</p>` : ""}
    <div class="governance-action-row">
      <button class="btn-secondary" type="button" data-governance-action="auto-replay-name-mapping" data-candidate-id="${escapeHtml(candidate.candidateId)}" ${disabled ? "disabled" : ""}>预览影响</button>
      <button class="btn-primary-lg" type="button" data-governance-action="confirm-name-mapping" data-candidate-id="${escapeHtml(candidate.candidateId)}" ${!canConfirm ? "disabled" : ""}>${canConfirm ? "填写复核意见" : replayDecision ? "预览未改善" : "先预览影响"}</button>
    </div>
  </article>`;
}

function renderNameMappingActiveCard(mapping) {
  return `<article class="governance-card">
    <div class="governance-meta">
      <span class="governance-pill ok">姓名匹配已确认</span>
      <span class="governance-pill">${escapeHtml(mapping.confirmedBy || "user")}</span>
    </div>
    <h3>${escapeHtml(mapping.cacheEmployeeName || "-")} → ${escapeHtml(mapping.excelEmployeeName || "-")}</h3>
    <p>${escapeHtml(mapping.confirmationReason || "该映射已写入当前批次 姓名匹配记录。")}</p>
    <div class="governance-action-row">
      <button class="btn-secondary" type="button" data-governance-action="rollback-name-mapping" data-candidate-id="${escapeHtml(mapping.candidateId)}">撤回匹配</button>
    </div>
  </article>`;
}

function renderNameMappingRollbackCard(mapping) {
  return `<article class="governance-card">
    <div class="governance-meta">
      <span class="governance-pill danger">姓名匹配已撤回</span>
      <span class="governance-pill">${escapeHtml(mapping.rolledBackBy || "user")}</span>
    </div>
    <h3>${escapeHtml(mapping.cacheEmployeeName || "-")} → ${escapeHtml(mapping.excelEmployeeName || "-")}</h3>
    <p>${escapeHtml(mapping.rollbackReason || "姓名匹配已撤回，并从当前批次姓名匹配记录移除。")}</p>
  </article>`;
}

function renderAllocationCandidateCard(candidate) {
  const status = candidate.status || "";
  const decision = candidate.decision || "";
  const disabled = ["confirmed", "rolled_back"].includes(status) || ["confirmed", "rolled_back"].includes(decision);
  const warehouses = Array.isArray(candidate.warehouses) ? candidate.warehouses : [];
  const details = warehouses
    .slice(0, 4)
    .map(
      (row) =>
        `<li>仓 ${escapeHtml(row.warehouseId || "-")} · PDF $${formatMoney(row.pdfAmount || 0)} · Excel $${formatMoney(row.excelAmount || 0)} · 差异 ${formatSignedMoney(row.amountDelta || 0)}</li>`
    )
    .join("");
  return `<article class="governance-card">
    <div class="governance-meta">
      <span class="governance-pill ${disabled ? "ok" : "warning"}">${disabled ? "跨仓归属已处理" : "跨仓归属待复核"}</span>
      <span class="governance-pill">${escapeHtml(candidate.warehouseCount || warehouses.length || 0)} 个仓库</span>
      <span class="governance-pill">净差 ${formatSignedMoney(candidate.netAmountDelta || 0)}</span>
    </div>
    <h3>${escapeHtml(candidate.employeeName || "员工跨仓库归属")}</h3>
    <p>${escapeHtml(candidate.recommendation || "员工总额可抵消，但仓库归属金额不一致，需人工复核。")}</p>
    ${details ? `<ul class="reocr-evidence-list">${details}</ul>` : ""}
    <div class="governance-action-row">
      <button class="btn-primary-lg" type="button" data-governance-action="confirm-allocation" data-candidate-id="${escapeHtml(candidate.candidateId)}" ${disabled ? "disabled" : ""}>确认已复核</button>
    </div>
  </article>`;
}

function renderAllocationActiveCard(candidate) {
  return `<article class="governance-card">
    <div class="governance-meta">
      <span class="governance-pill ok">跨仓归属已确认</span>
      <span class="governance-pill">${escapeHtml(candidate.confirmedBy || "user")}</span>
      <span class="governance-pill">净差 ${formatSignedMoney(candidate.netAmountDelta || 0)}</span>
    </div>
    <h3>${escapeHtml(candidate.employeeName || "员工跨仓库归属")}</h3>
    <p>${escapeHtml(candidate.confirmationReason || candidate.decisionNote || "该跨仓库归属差异已人工复核并留痕。")}</p>
    <div class="governance-action-row">
      <button class="btn-secondary" type="button" data-governance-action="rollback-allocation" data-candidate-id="${escapeHtml(candidate.candidateId)}">撤回复核</button>
    </div>
  </article>`;
}

function renderAllocationRollbackCard(candidate) {
  return `<article class="governance-card">
    <div class="governance-meta">
      <span class="governance-pill danger">跨仓归属复核已撤回</span>
      <span class="governance-pill">${escapeHtml(candidate.rolledBackBy || "user")}</span>
    </div>
    <h3>${escapeHtml(candidate.employeeName || "员工跨仓库归属")}</h3>
    <p>${escapeHtml(candidate.rollbackReason || "跨仓库归属复核记录已撤回，保留审计记录。")}</p>
  </article>`;
}

function renderAllocationConfirmSummary(candidate) {
  if (!candidate) return `<p class="reocr-preflight-clear">确认后只记录复核结论，不改变正式核对结果。</p>`;
  const warehouses = Array.isArray(candidate.warehouses) ? candidate.warehouses : [];
  const rows = warehouses
    .slice(0, 6)
    .map(
      (row) =>
        `<li>仓 ${escapeHtml(row.warehouseId || "-")}：PDF $${formatMoney(row.pdfAmount || 0)}，Excel $${formatMoney(row.excelAmount || 0)}，差异 ${formatSignedMoney(row.amountDelta || 0)}</li>`
    )
    .join("");
  return `<div class="reocr-preflight ready">
    <div class="reocr-preflight-head">
      <div>
        <strong>${escapeHtml(candidate.employeeName || "员工跨仓库归属")}</strong>
        <span>${escapeHtml(candidate.warehouseCount || warehouses.length || 0)} 个仓库 · 净差 ${formatSignedMoney(candidate.netAmountDelta || 0)}</span>
      </div>
      <span class="governance-pill warning">只留痕</span>
    </div>
    ${rows ? `<ul class="reocr-evidence-list">${rows}</ul>` : ""}
    <p class="reocr-preflight-clear">${escapeHtml(candidate.confirmationGate || "确认后只记录复核结论，不改变正式核对结果。")}</p>
  </div>`;
}

function renderGovernanceCandidateCard(candidate, replay) {
  const status = candidate.status || "pending_user_confirmation";
  const replayDecision = replay && replay.decision;
  const replayClass =
    replayDecision === "ready_for_user_confirmation"
      ? "ok"
      : replayDecision === "blocked_by_replay_regression"
      ? "danger"
      : "warning";
  const replayText = replay
    ? `预览 ${replay.summary?.replayedCount || 0} 批 · 可修复 ${replay.summary?.fixedCount || 0} · 新增风险 ${replay.summary?.regressionCount || 0}`
    : "未预览";
  const canConfirm = replayDecision === "ready_for_user_confirmation" && status !== "confirmed";

  return `<article class="governance-card">
    <div class="governance-meta">
      <span class="governance-pill warning">处理建议</span>
      <span class="governance-pill">${escapeHtml(candidate.proposedBy || "ai")}</span>
      <span class="governance-pill ${replayClass}">${escapeHtml(replayText)}</span>
    </div>
    <h3>${escapeHtml(candidate.title || candidate.ruleId)}</h3>
    <p>${escapeHtml(candidate.description || "等待补充规则说明。")}</p>
    ${renderRulePreflightPanel(replay?.preflight)}
    <div class="governance-action-row">
      <button class="btn-secondary" type="button" data-governance-action="auto-replay" data-rule-id="${escapeHtml(candidate.ruleId)}">预览影响</button>
      <button class="btn-primary-lg" type="button" data-governance-action="confirm" data-rule-id="${escapeHtml(candidate.ruleId)}" ${canConfirm ? "" : "disabled"}>填写复核意见</button>
    </div>
  </article>`;
}

function renderRulePreflightPanel(preflight) {
  if (!preflight) {
    return `<div class="reocr-preflight">
      <div class="reocr-preflight-head">
        <div>
          <strong>处理建议影响预览</strong>
          <span>等待历史批次预览</span>
        </div>
        <span class="governance-pill warning">未预览</span>
      </div>
      <p class="reocr-preflight-clear">处理建议必须先预览历史影响；确认后不会自动覆盖当前核对结果。</p>
    </div>`;
  }
  const current = preflight.current || {};
  const warnings = Array.isArray(preflight.postApplyWarnings) ? preflight.postApplyWarnings : [];
  const suppliers = Array.isArray(preflight.affectedSuppliers) ? preflight.affectedSuppliers.slice(0, 6) : [];
  const fixedRuns = Array.isArray(preflight.fixedRuns) ? preflight.fixedRuns.slice(0, 3) : [];
  const regressionRuns = Array.isArray(preflight.regressionRuns) ? preflight.regressionRuns.slice(0, 3) : [];
  const warningHtml = warnings.length
    ? `<ul class="reocr-preflight-warnings">${warnings.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`
    : `<p class="reocr-preflight-clear">历史预览未发现回归，可进入人工确认。</p>`;
  const runHtml = [...fixedRuns.map((run) => ({ ...run, kind: "修复" })), ...regressionRuns.map((run) => ({ ...run, kind: "回归" }))]
    .map(
      (run) =>
        `<span class="governance-pill ${run.kind === "回归" ? "danger" : "ok"}">${escapeHtml(run.kind)} ${escapeHtml(run.runId || "-")}</span>`
    )
    .join("");
  return `<div class="reocr-preflight ${preflight.blockingAfterApply ? "blocked" : "ready"}">
    <div class="reocr-preflight-head">
      <div>
        <strong>处理建议影响预览</strong>
        <span>只读预览 · 不覆盖正式结果</span>
      </div>
      <span class="governance-pill ${preflight.blockingAfterApply ? "danger" : "ok"}">${preflight.blockingAfterApply ? "阻断确认" : "可确认"}</span>
    </div>
    <div class="reocr-preflight-stats">
      <div><span>预览批次</span><strong>${current.replayedCount || 0} 个</strong></div>
      <div><span>修复批次</span><strong>${current.fixedCount || 0} 个</strong></div>
      <div><span>回归批次</span><strong>${current.regressionCount || 0} 个</strong></div>
      <div><span>无变化</span><strong>${current.unchangedCount || 0} 个</strong></div>
    </div>
    ${warningHtml}
    <div class="governance-meta">
      ${suppliers.length ? suppliers.map((supplier) => `<span class="governance-pill">${escapeHtml(supplier)}</span>`).join("") : `<span class="governance-pill">供应商范围待确认</span>`}
      ${runHtml || ""}
    </div>
  </div>`;
}

function renderProfileCandidateCard(candidate, replay) {
  const profile = candidate.profileData || {};
  const notes = Array.isArray(profile.prompt_notes) ? profile.prompt_notes : [];
  const evidenceCount = Array.isArray(candidate.evidence) ? candidate.evidence.length : 0;
  const confirmed = candidate.status === "confirmed";
  const replayDecision = replay && replay.decision;
  const replayClass =
    replayDecision === "ready_for_user_confirmation"
      ? "ok"
      : replayDecision === "blocked_by_replay_regression"
      ? "danger"
      : "warning";
  const replayText = replay
    ? `预览：兼容 ${replay.summary?.compatibleCount || 0} · 新增风险 ${replay.summary?.regressionCount || 0}`
    : "未预览";
  const canConfirm = replayDecision === "ready_for_user_confirmation" && !confirmed;
  return `<article class="governance-card">
    <div class="governance-meta">
      <span class="governance-pill warning">供应商格式待确认</span>
      <span class="governance-pill">${escapeHtml(candidate.profileKey || profile.key || "unknown")}</span>
      <span class="governance-pill">${evidenceCount} 条证据</span>
      <span class="governance-pill ${replayClass}">${escapeHtml(replayText)}</span>
    </div>
    <h3>${escapeHtml(candidate.supplier || candidate.profileKey || "供应商格式")}</h3>
    <p>${escapeHtml(notes[0] || "系统根据本批抽取结果识别到供应商格式差异，确认后才会进入解析配置。")}</p>
    ${renderProfilePreflightPanel(replay?.preflight)}
    <div class="governance-action-row">
      <button class="btn-secondary" type="button" data-governance-action="auto-replay-profile" data-candidate-id="${escapeHtml(candidate.candidateId)}">预览影响</button>
      <button class="btn-primary-lg" type="button" data-governance-action="confirm-profile" data-candidate-id="${escapeHtml(candidate.candidateId)}" ${canConfirm ? "" : "disabled"}>填写复核意见</button>
    </div>
  </article>`;
}

function renderProfilePreflightPanel(preflight) {
  if (!preflight) {
    return `<div class="reocr-preflight">
      <div class="reocr-preflight-head">
        <div>
          <strong>供应商格式预览</strong>
          <span>等待历史批次预览</span>
        </div>
        <span class="governance-pill warning">未预览</span>
      </div>
      <p class="reocr-preflight-clear">供应商格式必须先预览历史影响；确认后只进入解析配置，不覆盖当前正式核对结果。</p>
    </div>`;
  }
  const current = preflight.current || {};
  const warnings = Array.isArray(preflight.postApplyWarnings) ? preflight.postApplyWarnings : [];
  const suppliers = Array.isArray(preflight.affectedSuppliers) ? preflight.affectedSuppliers.slice(0, 6) : [];
  const fields = Array.isArray(preflight.changedFields) ? preflight.changedFields.slice(0, 8) : [];
  const compatibleRuns = Array.isArray(preflight.compatibleRuns) ? preflight.compatibleRuns.slice(0, 3) : [];
  const regressionRuns = Array.isArray(preflight.regressionRuns) ? preflight.regressionRuns.slice(0, 3) : [];
  const warningHtml = warnings.length
    ? `<ul class="reocr-preflight-warnings">${warnings.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`
    : `<p class="reocr-preflight-clear">历史预览未发现格式回归风险，可进入人工确认。</p>`;
  const runHtml = [...compatibleRuns.map((run) => ({ ...run, kind: "兼容" })), ...regressionRuns.map((run) => ({ ...run, kind: "回归" }))]
    .map(
      (run) =>
        `<span class="governance-pill ${run.kind === "回归" ? "danger" : "ok"}">${escapeHtml(run.kind)} ${escapeHtml(run.runId || "-")}</span>`
    )
    .join("");
  return `<div class="reocr-preflight ${preflight.blockingAfterApply ? "blocked" : "ready"}">
    <div class="reocr-preflight-head">
      <div>
        <strong>供应商格式预览</strong>
        <span>只读预览 · 不覆盖正式结果</span>
      </div>
      <span class="governance-pill ${preflight.blockingAfterApply ? "danger" : "ok"}">${preflight.blockingAfterApply ? "阻断确认" : "可确认"}</span>
    </div>
    <div class="reocr-preflight-stats">
      <div><span>预览批次</span><strong>${current.replayedCount || 0} 个</strong></div>
      <div><span>兼容批次</span><strong>${current.compatibleCount || 0} 个</strong></div>
      <div><span>回归风险</span><strong>${current.regressionCount || 0} 个</strong></div>
      <div><span>证据数量</span><strong>${current.evidenceCount || 0} 条</strong></div>
    </div>
    ${warningHtml}
    <div class="governance-meta">
      ${suppliers.length ? suppliers.map((supplier) => `<span class="governance-pill">${escapeHtml(supplier)}</span>`).join("") : `<span class="governance-pill">供应商范围待确认</span>`}
      ${fields.length ? fields.map((field) => `<span class="governance-pill warning">${escapeHtml(field)}</span>`).join("") : `<span class="governance-pill warning">字段变更待确认</span>`}
      ${runHtml || ""}
    </div>
  </div>`;
}

function renderCorrectionCandidateCard(candidate, replay) {
  const proposed = candidate.proposed || {};
  const confirmed = candidate.status === "confirmed";
  const replayDecision = replay && replay.decision;
  const replayClass =
    replayDecision === "ready_for_user_confirmation"
      ? "ok"
      : replayDecision === "blocked_by_replay_regression"
      ? "danger"
      : "warning";
  const replayText = replay
    ? `预览：影响 ${replay.summary?.affectedEmployees?.length || 0} 人 · 可修复 ${replay.summary?.fixedCount || 0} · 新增风险 ${replay.summary?.regressionCount || 0}`
    : "未预览";
  const canConfirm = replayDecision === "ready_for_user_confirmation" && !confirmed;
  const actionHint = canConfirm
    ? "预览已通过，可以提交人工复核意见。提交后只留痕，不会自动覆盖正式结果。"
    : replay
    ? "当前预览未通过，不能提交复核意见；请先查看新增风险或重新识别。"
    : "请先点击“影响预览”。预览通过后，才可以提交人工复核意见。";
  return `<article class="governance-card">
    <div class="governance-meta">
      <span class="governance-pill warning">疑似误抽</span>
      <span class="governance-pill">${formatPercent(candidate.confidence || 0)}</span>
      <span class="governance-pill">${escapeHtml(formatGovernanceReason(candidate.reason || "low_confidence"))}</span>
      <span class="governance-pill ${replayClass}">${escapeHtml(replayText)}</span>
    </div>
    <h3>${escapeHtml(proposed.employeeName || "低置信度员工")}</h3>
    <p>${escapeHtml(`${proposed.sourceFile || ""} ${proposed.sourcePageOrRow || ""} · 识别金额 $${formatMoney(proposed.amount)} · 识别工时 ${formatHours(proposed.hours)}`)}</p>
    <p>这条 PDF 明细可能是员工行、岗位汇总行或班次差异行。${escapeHtml(actionHint)}</p>
    <div class="governance-action-row">
      <button class="btn-secondary" type="button" data-governance-action="auto-replay-correction" data-candidate-id="${escapeHtml(candidate.candidateId)}">影响预览</button>
      <button class="btn-primary-lg" type="button" data-governance-action="confirm-correction" data-candidate-id="${escapeHtml(candidate.candidateId)}" ${
        canConfirm ? "" : `disabled title="${escapeHtml(actionHint)}"`
      }>${canConfirm ? "提交复核意见" : "预览通过后可提交"}</button>
    </div>
  </article>`;
}

function renderGovernanceActiveCard(rule) {
  return `<article class="governance-card">
    <div class="governance-meta">
      <span class="governance-pill ok">已确认</span>
      <span class="governance-pill">v${escapeHtml(rule.version || 1)}</span>
    </div>
    <h3>${escapeHtml(rule.title || rule.ruleId)}</h3>
    <p>${escapeHtml(rule.confirmationReason || rule.description || "处理建议已进入复核记录。")}</p>
    ${renderRulePreflightPanel(rule.preflight)}
    <div class="governance-action-row">
      <button class="btn-secondary" type="button" data-governance-action="rollback" data-rule-id="${escapeHtml(rule.ruleId)}">撤回</button>
    </div>
  </article>`;
}

function renderCorrectionActiveCard(correction, reportFile) {
  const proposed = correction.proposed || {};
  const reportLink = reportFile?.downloadUrl
    ? `<a class="governance-link" href="${escapeHtml(reportFile.downloadUrl)}" download>下载预览报告</a>`
    : "";
  return `<article class="governance-card">
    <div class="governance-meta">
      <span class="governance-pill ok">低置信度已复核</span>
      <span class="governance-pill">${escapeHtml(correction.confirmedBy || "user")}</span>
    </div>
    <h3>${escapeHtml(proposed.employeeName || "低置信度复核")}</h3>
    <p>${escapeHtml(correction.confirmationReason || "复核意见已进入当前批次记录，未覆盖原始抽取。")}</p>
    ${renderCorrectionPreflightPanel(correction.preflight)}
    ${reportLink}
    <div class="governance-action-row">
      <button class="btn-secondary" type="button" data-governance-action="preview-correction" data-candidate-id="${escapeHtml(correction.candidateId)}">查看影响预览</button>
      <button class="btn-secondary" type="button" data-governance-action="rollback-correction" data-candidate-id="${escapeHtml(correction.candidateId)}">撤回复核</button>
    </div>
  </article>`;
}

function renderCorrectionPreflightPanel(preflight) {
  if (!preflight) {
    return `<div class="reocr-preflight">
      <div class="reocr-preflight-head">
        <div>
          <strong>复核影响摘要</strong>
          <span>等待重算预览</span>
        </div>
        <span class="governance-pill warning">未预览</span>
      </div>
      <p class="reocr-preflight-clear">点击“查看影响预览”后生成影响摘要和预览报告；不会覆盖正式核对结果。</p>
    </div>`;
  }
  const delta = preflight.delta || {};
  const warnings = Array.isArray(preflight.postApplyWarnings) ? preflight.postApplyWarnings : [];
  const employees = Array.isArray(preflight.affectedEmployees) ? preflight.affectedEmployees.slice(0, 8) : [];
  const warningHtml = warnings.length
    ? `<ul class="reocr-preflight-warnings">${warnings.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`
    : `<p class="reocr-preflight-clear">预览结果显示该复核意见会降低异常或低置信度风险；正式结果不会被自动覆盖。</p>`;
  return `<div class="reocr-preflight ${preflight.blockingAfterApply ? "blocked" : "ready"}">
    <div class="reocr-preflight-head">
      <div>
        <strong>复核影响摘要</strong>
        <span>只读预览 · 不覆盖正式结果</span>
      </div>
      <span class="governance-pill ${preflight.blockingAfterApply ? "danger" : "ok"}">${preflight.blockingAfterApply ? "仍需复核" : "预览通过"}</span>
    </div>
    <div class="reocr-preflight-stats">
      <div><span>影响员工</span><strong>${preflight.affectedEmployeeCount || 0} 人</strong></div>
      <div><span>复核项</span><strong>${preflight.affectedScopeCount || 0} 个</strong></div>
      <div><span>异常变化</span><strong>${formatSignedNumber(delta.exceptionCount || 0)}</strong></div>
      <div><span>低置信变化</span><strong>${formatSignedNumber(delta.lowConfidenceCount || 0)}</strong></div>
    </div>
    ${warningHtml}
    <div class="governance-meta">${employees.length ? employees.map((name) => `<span class="governance-pill">${escapeHtml(name)}</span>`).join("") : `<span class="governance-pill">员工明细见预览报告</span>`}</div>
  </div>`;
}

function renderProfileActiveCard(profile) {
  return `<article class="governance-card">
    <div class="governance-meta">
      <span class="governance-pill ok">供应商格式已确认</span>
      <span class="governance-pill">v${escapeHtml(profile.version || 1)}</span>
    </div>
    <h3>${escapeHtml(profile.supplier || profile.profileKey || "供应商格式")}</h3>
    <p>${escapeHtml(profile.confirmationReason || "供应商格式已进入当前批次复核记录，等待上线配置加载。")}</p>
    ${renderProfilePreflightPanel(profile.preflight)}
    <div class="governance-action-row">
      <button class="btn-secondary" type="button" data-governance-action="rollback-profile" data-candidate-id="${escapeHtml(profile.candidateId)}">撤回供应商格式</button>
    </div>
  </article>`;
}

function renderGovernanceRollbackCard(rule) {
  return `<article class="governance-card">
    <div class="governance-meta">
      <span class="governance-pill danger">已撤回</span>
      <span class="governance-pill">to v${escapeHtml(rule.rollbackToVersion ?? 0)}</span>
    </div>
    <h3>${escapeHtml(rule.title || rule.ruleId)}</h3>
    <p>${escapeHtml(rule.rollbackReason || "处理建议已撤回，保留审计记录。")}</p>
  </article>`;
}

function renderProfileRollbackCard(profile) {
  return `<article class="governance-card">
    <div class="governance-meta">
      <span class="governance-pill danger">供应商格式已撤回</span>
      <span class="governance-pill">to v${escapeHtml(profile.rollbackToVersion ?? 0)}</span>
    </div>
    <h3>${escapeHtml(profile.supplier || profile.profileKey || "供应商格式")}</h3>
    <p>${escapeHtml(profile.rollbackReason || "供应商格式已撤回，保留审计记录。")}</p>
  </article>`;
}

function renderCorrectionRollbackCard(correction) {
  const proposed = correction.proposed || {};
  return `<article class="governance-card">
    <div class="governance-meta">
      <span class="governance-pill danger">复核意见已撤回</span>
      <span class="governance-pill">${escapeHtml(correction.rolledBackBy || "user")}</span>
    </div>
    <h3>${escapeHtml(proposed.employeeName || "低置信度复核")}</h3>
    <p>${escapeHtml(correction.rollbackReason || "复核意见已撤回，保留审计记录。")}</p>
  </article>`;
}

function buildRuleCandidateSuggestion(run) {
  const diagnostics = run.reconciliationDiagnostics || {};
  const issues = Array.isArray(diagnostics.issues) ? diagnostics.issues : [];
  const issue = issues[0];
  if (!issue || !issue.code) return null;
  const code = String(issue.code);
  const titleMap = {
    missing_warehouse_id: "补充仓库号识别规则",
    zero_pdf_total: "补充 PDF 总额抽取规则",
    pdf_total_conflict: "复核 PDF 总额口径规则",
    warehouse_mapping_errors: "复核仓库映射口径",
    warehouse_offsetting_deltas: "识别跨仓抵消差异规则",
    warehouse_employee_attribution: "沉淀员工差异归因规则",
    cross_warehouse_employee_allocation: "复核员工跨仓库归属",
    amount_basis_mismatch: "沉淀账单金额口径规则",
  };
  return {
    ruleId: `${run.id}_${code}`.replace(/[^0-9A-Za-z_-]/g, "_"),
    title: titleMap[code] || `处理 ${code}`,
    description: issue.message || issue.title || "根据本批次诊断信号生成处理建议。",
    source: `labor_run:${run.id}`,
    conditions: {
      supplier: run.supplierName || "",
      fixIssueCodes: [code],
    },
    evidence: (issue.items || []).slice(0, 8).map((item) => ({
      issueCode: code,
      evidenceText: String(item),
    })),
  };
}

function openGovernanceConfirm(confirm) {
  laborState.governanceConfirm = confirm;
  laborState.governanceActionFeedback = {
    kind: "info",
    title: "等待人工复核",
    message: "请填写复核原因。提交后会显示是否写入记录、是否影响正式结果。",
    action: confirm.title || "提交复核意见",
    timestamp: Date.now(),
  };
  renderGovernancePanel(laborState.run);
  const panel = labor.ruleGovernanceBody?.querySelector("[data-governance-confirm-panel]");
  if (panel) {
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
    toast("请填写复核意见并提交。");
  }
  const field = labor.ruleGovernanceBody?.querySelector("[data-governance-confirm-reason]");
  if (field) {
    field.focus();
    field.select();
  }
}

function exampleReocrCandidateRows(task) {
  return JSON.stringify(
    [
      {
        employeeName: "Alice Worker",
        sourcePageOrRow: "p1",
        hours: 8,
        amount: Number(task.expectedExcelAmount || 0),
        currency: laborState.run?.currency || "USD",
        confidence: 0.95,
        evidenceText: "Alice Worker 8.00 $100.00",
      },
    ],
    null,
    2
  );
}

function openReocrJsonInput(task) {
  laborState.reocrJsonInput = { task, value: exampleReocrCandidateRows(task) };
  renderGovernancePanel(laborState.run);
  const field = labor.ruleGovernanceBody?.querySelector("[data-reocr-json-input]");
  if (field) {
    field.focus();
    field.select();
  }
}

async function submitReocrJsonInput() {
  const input = laborState.reocrJsonInput;
  if (!input?.task) return;
  const field = labor.ruleGovernanceBody?.querySelector("[data-reocr-json-input]");
  const value = String(field?.value || "").trim();
  if (!value) {
    toast("请粘贴识别明细 JSON 数组。");
    if (field) field.focus();
    return;
  }
  let candidateRows;
  try {
    candidateRows = JSON.parse(value);
  } catch (error) {
    toast("JSON 格式不正确。");
    if (field) field.focus();
    return;
  }
  if (!Array.isArray(candidateRows) || candidateRows.length === 0) {
    toast("识别明细必须是非空 JSON 数组。");
    if (field) field.focus();
    return;
  }
  const replay = await requestJson(`/api/labor/runs/${laborState.run.id}/reocr-candidates/replay`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      task: input.task,
      candidateRows,
      amountTolerance: input.task.amountTolerance,
    }),
  });
  laborState.reocrJsonInput = null;
  toast(replay.decision === "ready_for_user_confirmation" ? "识别预览通过，等待人工确认。" : `识别预览未通过：${(replay.blockers || []).join(", ")}`);
  await refreshCurrentRun();
}

async function submitGovernanceConfirm() {
  const confirm = laborState.governanceConfirm;
  if (!confirm) return;
  const field = labor.ruleGovernanceBody?.querySelector("[data-governance-confirm-reason]");
  const reason = String(field?.value || "").trim();
  if (!reason) {
    setGovernancePersistentFeedback("error", "需要填写复核原因", "确认、采纳或撤回都必须保留人工复核原因。", "提交复核意见");
    toast("请填写确认原因。");
    if (field) field.focus();
    return;
  }
  const actionLabel = confirm.actionLabel || "提交复核意见";
  setGovernancePersistentFeedback("loading", `${actionLabel}中`, "系统正在写入审计记录并刷新当前批次。", actionLabel);
  try {
    const feedback = await executeGovernanceConfirm(confirm, reason);
    laborState.governanceConfirm = null;
    setGovernancePersistentFeedback(feedback.kind, feedback.title, feedback.message, feedback.action);
    renderGovernancePanel(laborState.run);
    revealGovernanceFeedback();
  } catch (error) {
    setGovernancePersistentFeedback("error", `${actionLabel}失败`, error.message || "请检查预览结果后重试。", actionLabel);
    renderGovernancePanel(laborState.run);
    revealGovernanceFeedback();
    toast(error.message || `${actionLabel}失败。`);
  }
}

function getGovernanceConfirmFeedback(confirm, result) {
  const reportReady = Boolean(result?.reportFile?.downloadUrl || result?.recalculatedRun?.diffDownloadUrl);
  const summaryCount = result?.summary?.confirmedCount || result?.summary?.appliedCount || 0;
  const feedback = {
    "confirm-rule": ["success", "处理建议已确认", "已写入复核记录；不会自动覆盖当前正式核对结果。", "确认处理建议"],
    "confirm-profile": ["success", "供应商格式已确认", "已写入供应商解析配置记录，后续批次可按该格式识别。", "格式确认"],
    "apply-reocr": ["success", "图片识别结果已采纳", "当前批次正式核对结果和差异报告已刷新。", "采纳识别结果"],
    "apply-reocr-batch": [
      "success",
      "批量图片识别已采纳",
      result?.reportFile?.downloadUrl
        ? `正式报告已更新；未采纳计划 ${result.summary?.missingAppliedTaskCount || 0} 个。`
        : `采纳记录已写入；未采纳计划 ${result?.summary?.missingAppliedTaskCount || 0} 个。`,
      "批量采纳",
    ],
    "rollback-rule": ["success", "处理建议已撤回", "撤回原因已写入审计记录；该建议不再作为已确认记录展示。", "撤回处理建议"],
    "rollback-profile": ["success", "供应商格式已撤回", "撤回原因已写入审计记录。", "撤回格式"],
    "confirm-reocr": ["success", "图片识别结果已确认", reportReady ? "预览报告已生成；正式结果仍需单独采纳。" : "已记录复核结论；正式结果未覆盖。", "确认识别结果"],
    "confirm-reocr-batch": [
      "success",
      "批量图片识别结果已确认",
      reportReady ? `已确认 ${summaryCount} 个识别结果并生成预览报告。` : `已确认 ${summaryCount} 个识别结果。`,
      "批量确认识别结果",
    ],
    "rollback-reocr": ["success", "图片识别结果已撤回", "撤回原因已写入审计记录；如曾采纳会恢复上一个正式结果快照。", "撤回识别结果"],
    "confirm-name-mapping": ["success", "姓名匹配已确认", reportReady ? "正式报告已刷新；后续仍可撤回该匹配记录。" : "已写入当前批次姓名匹配记录。", "确认姓名匹配"],
    "rollback-name-mapping": ["success", "姓名匹配已撤回", "撤回原因已写入审计记录，建议会重新进入未闭环状态。", "撤回姓名匹配"],
    "confirm-allocation": ["success", "跨仓归属已确认", "只记录复核结论，不改变核对金额或仓库归属。", "确认跨仓归属"],
    "rollback-allocation": ["success", "跨仓归属复核已撤回", "撤回原因已写入审计记录，建议会重新进入未闭环状态。", "撤回跨仓归属"],
    "confirm-correction": ["success", "低置信度复核意见已提交", "只记录人工复核结论，不自动覆盖正式结果。", "提交复核意见"],
    "rollback-correction": ["success", "低置信度复核已撤回", "撤回原因已写入审计记录。", "撤回低置信度复核"],
  };
  const values = feedback[confirm.type] || ["success", "复核意见已提交", "处理完成，页面已刷新。", "提交复核意见"];
  return { kind: values[0], title: values[1], message: values[2], action: values[3] };
}

async function executeGovernanceConfirm(confirm, reason) {
  let result = null;
  if (confirm.type === "confirm-rule") {
    await requestJson(`/api/labor/runs/${laborState.run.id}/rule-candidates/${encodeURIComponent(confirm.ruleId)}/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirmedBy: "ops-user", reason }),
    });
    toast("处理建议已确认。");
  } else if (confirm.type === "confirm-profile") {
    await requestJson(`/api/labor/runs/${laborState.run.id}/profile-candidates/${encodeURIComponent(confirm.candidateId)}/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirmedBy: "ops-user", reason }),
    });
    toast("供应商格式建议已确认。");
  } else if (confirm.type === "apply-reocr") {
    await requestJson(`/api/labor/runs/${laborState.run.id}/reocr-candidates/${encodeURIComponent(confirm.candidateId)}/apply`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ appliedBy: "ops-user", reason }),
    });
    toast("图片识别结果已采纳为当前批次结果。");
  } else if (confirm.type === "apply-reocr-batch") {
    const applied = await requestJson(`/api/labor/runs/${laborState.run.id}/reocr-candidates/batch-apply`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ appliedBy: "ops-user", reason }),
    });
    result = applied;
    laborState.reocrBatchPreview = null;
    toast(
      applied.reportFile?.downloadUrl
        ? `图片识别结果已批量采纳，正式报告已更新。未采纳计划 ${applied.summary?.missingAppliedTaskCount || 0} 个。`
        : `图片识别结果已批量采纳。未采纳计划 ${applied.summary?.missingAppliedTaskCount || 0} 个。`
    );
  } else if (confirm.type === "rollback-rule") {
    await requestJson(`/api/labor/runs/${laborState.run.id}/rule-candidates/${encodeURIComponent(confirm.ruleId)}/rollback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rolledBackBy: "ops-user", reason, targetVersion: 0 }),
    });
    toast("处理建议已撤回。");
  } else if (confirm.type === "rollback-profile") {
    await requestJson(`/api/labor/runs/${laborState.run.id}/profile-candidates/${encodeURIComponent(confirm.candidateId)}/rollback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rolledBackBy: "ops-user", reason, targetVersion: 0 }),
    });
    toast("供应商格式记录已撤回。");
  } else if (confirm.type === "confirm-reocr") {
    const confirmed = await requestJson(`/api/labor/runs/${laborState.run.id}/reocr-candidates/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sourceFile: confirm.sourceFile, warehouseId: confirm.warehouseId, confirmedBy: "ops-user", reason, generateReport: true }),
    });
    result = confirmed;
    toast(confirmed.reportFile?.downloadUrl ? "图片识别结果已确认，预览报告已生成。" : "图片识别结果已确认。");
  } else if (confirm.type === "confirm-reocr-batch") {
    const confirmed = await requestJson(`/api/labor/runs/${laborState.run.id}/reocr-candidates/confirm-batch`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirmedBy: "ops-user", reason, generateReport: true }),
    });
    result = confirmed;
    toast(
      confirmed.reportFile?.downloadUrl
        ? `已批量确认 ${confirmed.summary?.confirmedCount || 0} 个识别结果，预览报告已生成。`
        : `已批量确认 ${confirmed.summary?.confirmedCount || 0} 个识别结果。`
    );
  } else if (confirm.type === "rollback-reocr") {
    await requestJson(`/api/labor/runs/${laborState.run.id}/reocr-candidates/${encodeURIComponent(confirm.candidateId)}/rollback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rolledBackBy: "ops-user", reason }),
    });
    toast("图片识别结果已撤回。");
  } else if (confirm.type === "confirm-name-mapping") {
    const confirmed = await requestJson(`/api/labor/runs/${laborState.run.id}/name-mapping-candidates/${encodeURIComponent(confirm.candidateId)}/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirmedBy: "ops-user", reason, recalculate: true }),
    });
    result = confirmed;
    toast(confirmed.recalculatedRun?.diffDownloadUrl ? "姓名匹配已确认，正式报告已刷新。" : "姓名匹配已确认。");
  } else if (confirm.type === "rollback-name-mapping") {
    await requestJson(`/api/labor/runs/${laborState.run.id}/name-mapping-candidates/${encodeURIComponent(confirm.candidateId)}/rollback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rolledBackBy: "ops-user", reason }),
    });
    toast("姓名匹配已撤回。");
  } else if (confirm.type === "confirm-allocation") {
    await requestJson(`/api/labor/runs/${laborState.run.id}/allocation-candidates/${encodeURIComponent(confirm.candidateId)}/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirmedBy: "ops-user", reason, decisionNote: "已按仓库复核发票与账单归属。" }),
    });
    toast("跨仓库归属复核已确认。");
  } else if (confirm.type === "rollback-allocation") {
    await requestJson(`/api/labor/runs/${laborState.run.id}/allocation-candidates/${encodeURIComponent(confirm.candidateId)}/rollback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rolledBackBy: "ops-user", reason }),
    });
    toast("跨仓库归属复核已撤回。");
  } else if (confirm.type === "confirm-correction") {
    await requestJson(`/api/labor/runs/${laborState.run.id}/correction-candidates/${encodeURIComponent(confirm.candidateId)}/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirmedBy: "ops-user", reason }),
    });
    toast("复核意见已提交。");
  } else if (confirm.type === "rollback-correction") {
    await requestJson(`/api/labor/runs/${laborState.run.id}/correction-candidates/${encodeURIComponent(confirm.candidateId)}/rollback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rolledBackBy: "ops-user", reason }),
    });
    toast("复核意见已撤回。");
  }
  laborState.run = await requestJson(`/api/labor/runs/${laborState.run.id}`);
  renderResult(laborState.run);
  if (laborState.run.diffDownloadUrl) setDownload(laborState.run.diffDownloadUrl);
  return getGovernanceConfirmFeedback(confirm, result);
}

async function handleGovernanceAction(event) {
  const button = event.target.closest("[data-governance-action]");
  if (!button || !laborState.run) return;
  const action = button.dataset.governanceAction;
  const ruleId = button.dataset.ruleId;
  const candidateId = button.dataset.candidateId;
  const originalLabel = setGovernanceActionFeedback(button, action, "loading");
  try {
    if (action === "cancel-governance-confirm") {
      laborState.governanceConfirm = null;
      setGovernancePersistentFeedback("info", "已取消复核提交", "未写入确认、采纳或撤回记录。", "取消");
      renderGovernancePanel(laborState.run);
      revealGovernanceFeedback();
      return;
    } else if (action === "submit-governance-confirm") {
      await submitGovernanceConfirm();
      return;
    } else if (action === "cancel-reocr-json") {
      laborState.reocrJsonInput = null;
      setGovernancePersistentFeedback("info", "已取消图片识别录入", "未写入识别明细。", "取消");
      renderGovernancePanel(laborState.run);
      revealGovernanceFeedback();
      return;
    } else if (action === "submit-reocr-json") {
      await submitReocrJsonInput();
      return;
    } else if (action === "create-candidate") {
      const candidate = buildRuleCandidateSuggestion(laborState.run);
      if (!candidate) return toast("当前批次暂无可生成的处理建议。");
      await requestJson(`/api/labor/runs/${laborState.run.id}/rule-candidates`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(candidate),
      });
      toast("处理建议已生成。");
    } else if (action === "auto-replay") {
      await requestJson(`/api/labor/runs/${laborState.run.id}/rule-candidates/${encodeURIComponent(ruleId)}/auto-replay`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ limit: 20 }),
      });
      toast("影响预览完成。");
    } else if (action === "confirm") {
      const replay = laborState.run.ruleGovernance?.replaySummaries?.[ruleId];
      openGovernanceConfirm({
        type: "confirm-rule",
        ruleId,
        title: "填写处理建议复核意见",
        subtitle: "确认后只记录复核结论，不直接覆盖当前核对结果",
        defaultReason: "历史批次预览通过，人工确认该处理建议。",
        summaryHtml: renderRulePreflightPanel(replay?.preflight),
        warnings: replay?.preflight?.postApplyWarnings || [],
      });
    } else if (action === "rollback") {
      openGovernanceConfirm({
        type: "rollback-rule",
        ruleId,
        title: "撤回处理建议",
        subtitle: "撤回后该建议会移入审计记录，不再作为已确认建议",
        defaultReason: "发现后续批次误伤，撤回处理建议。",
        summaryHtml: `<p class="reocr-preflight-clear">该操作不会删除审计记录；撤回原因会写入复核记录。</p>`,
      });
    } else if (action === "confirm-profile") {
      const replay = laborState.run.profileGovernance?.replaySummaries?.[candidateId];
      openGovernanceConfirm({
        type: "confirm-profile",
        candidateId,
        title: "填写供应商格式复核意见",
        subtitle: "确认后进入供应商解析配置记录",
        defaultReason: "抽取证据与历史预览已复核，填写供应商格式复核意见。",
        summaryHtml: renderProfilePreflightPanel(replay?.preflight),
        warnings: replay?.preflight?.postApplyWarnings || [],
      });
    } else if (action === "auto-replay-profile") {
      await requestJson(`/api/labor/runs/${laborState.run.id}/profile-candidates/${encodeURIComponent(candidateId)}/auto-replay`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ limit: 20 }),
      });
      toast("供应商格式影响预览完成。");
    } else if (action === "rollback-profile") {
      openGovernanceConfirm({
        type: "rollback-profile",
        candidateId,
        title: "撤回供应商格式",
        subtitle: "撤回后该格式记录会移入审计记录，不再作为已确认格式",
        defaultReason: "发现供应商格式建议误伤，撤回。",
        summaryHtml: `<p class="reocr-preflight-clear">该操作不会删除供应商格式证据；撤回原因会写入复核记录。</p>`,
      });
    } else if (action === "generate-governance-report") {
      await requestJson(`/api/labor/runs/${laborState.run.id}/governance-report`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      toast("复核记录已生成。");
    } else if (action === "replay-reocr") {
      const task = (laborState.run.reocrPlan?.tasks || [])[Number(button.dataset.taskIndex)];
      if (!task) return toast("未找到图片识别复核任务。");
      openReocrJsonInput(task);
    } else if (action === "upload-reocr") {
      const task = (laborState.run.reocrPlan?.tasks || [])[Number(button.dataset.taskIndex)];
      if (!task) return toast("未找到图片识别复核任务。");
      await uploadAndReplayReocrCandidate(task);
    } else if (action === "upload-reocr-batch") {
      await uploadAndReplayReocrCandidateBatch();
    } else if (action === "replay-cache-reocr") {
      const sourceFile = button.dataset.sourceFile || "";
      const warehouseId = button.dataset.warehouseId || "";
      const candidate = (laborState.run.reocrPlan?.reviewableCandidates || []).find(
        (item) => String(item.sourceFile || "") === sourceFile && String(item.warehouseId || "") === warehouseId
      );
      if (!candidate) return toast("未找到历史图片识别结果。");
      const replay = await requestJson(`/api/labor/runs/${laborState.run.id}/reocr-candidates/replay-cache`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          task: {
            sourceFile: candidate.sourceFile,
            warehouseId: candidate.warehouseId,
            expectedExcelAmount: candidate.expectedExcelAmount,
            amountDelta: candidate.amountDelta,
            diagnostics: candidate.diagnostics,
            confirmationGate: "历史图片识别结果需通过员工级预览并人工确认后才能用于当前批次。",
          },
        }),
      });
      toast(replay.decision === "ready_for_user_confirmation" ? "历史图片识别预览通过，等待人工确认。" : `历史图片识别预览未通过：${(replay.blockers || []).join(", ")}`);
    } else if (action === "batch-replay-cache-reocr") {
      const replay = await requestJson(`/api/labor/runs/${laborState.run.id}/reocr-candidates/replay-cache-batch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      toast(`历史识别批量预览完成：通过 ${replay.summary?.readyCount || 0}，阻断 ${replay.summary?.blockedCount || 0}，错误 ${replay.summary?.errorCount || 0}。`);
    } else if (action === "download-reocr-template") {
      const task = (laborState.run.reocrPlan?.tasks || [])[Number(button.dataset.taskIndex)];
      if (!task) return toast("未找到图片识别复核任务。");
      const file = await requestJson(`/api/labor/runs/${laborState.run.id}/reocr-candidates/template`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task }),
      });
      if (file.downloadUrl) {
        window.location.href = file.downloadUrl;
        toast("图片识别结果模板已生成。");
      }
    } else if (action === "download-reocr-template-batch") {
      const file = await requestJson(`/api/labor/runs/${laborState.run.id}/reocr-candidates/template-batch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (file.downloadUrl) {
        window.location.href = file.downloadUrl;
        toast(`图片识别批量模板已生成：${file.summary?.taskCount || 0} 个任务，${file.summary?.rowCount || 0} 行。`);
      }
    } else if (action === "confirm-reocr") {
      const sourceFile = button.dataset.sourceFile || "";
      const warehouseId = button.dataset.warehouseId || "";
      openGovernanceConfirm({
        type: "confirm-reocr",
        sourceFile,
        warehouseId,
        title: "填写图片识别复核意见",
        subtitle: "确认后只生成预览报告，不覆盖正式结果",
        defaultReason: "新识别明细预览通过，人工确认生成预览报告。",
        summaryHtml: `<p class="reocr-preflight-clear">${escapeHtml(sourceFile)} · 仓 ${escapeHtml(warehouseId || "-")} · 确认后仍需采纳才会影响正式结果。</p>`,
      });
    } else if (action === "confirm-reocr-batch") {
      openGovernanceConfirm({
        type: "confirm-reocr-batch",
        title: "批量填写图片识别复核意见",
        subtitle: "确认后只生成批量识别预览，不覆盖正式结果",
        defaultReason: "批量识别预览通过，人工确认生成预览报告。",
        summaryHtml: `<p class="reocr-preflight-clear">批量确认只把通过预览的识别结果移入待采纳区；正式结果需要后续批量采纳。</p>`,
      });
    } else if (action === "rollback-reocr") {
      if (!candidateId) return toast("未找到图片识别结果。");
      openGovernanceConfirm({
        type: "rollback-reocr",
        candidateId,
        title: "撤回图片识别结果",
        subtitle: "撤回后识别结果移入审计记录；若已采纳会恢复上一个正式结果快照",
        defaultReason: "识别结果不适用，撤回已确认记录。",
        summaryHtml: `<p class="reocr-preflight-clear">撤回原因会写入识别结果审计记录。</p>`,
      });
    } else if (action === "apply-reocr") {
      if (!candidateId) return toast("未找到图片识别结果。");
      const candidate = (laborState.run.reocrReplayGovernance?.activeCandidates || []).find((item) => item.candidateId === candidateId);
      const preflight = candidate?.preflight || buildSingleReocrPreflight(candidate);
      openGovernanceConfirm({
        type: "apply-reocr",
        candidateId,
        title: "采纳图片识别结果",
        subtitle: "采纳后覆盖当前批次正式核对结果并更新差异报告",
        defaultReason: "预览报告已复核，采纳为当前批次正式核对依据。",
        summaryHtml: renderReocrBatchPreflightPanel(preflight, "preview", { candidateCount: 1 }),
        warnings: preflight?.postApplyWarnings || [],
      });
    } else if (action === "preview-reocr-batch") {
      const preview = await requestJson(`/api/labor/runs/${laborState.run.id}/reocr-candidates/batch-preview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      laborState.reocrBatchPreview = { ...preview, runId: laborState.run.id };
      renderGovernancePanel(laborState.run);
      toast(`批量预览：${preview.summary.candidateCount || 0} 个识别结果，${formatReocrPreflightSummary(preview.preflight)}。`);
    } else if (action === "apply-reocr-batch") {
      const preview = await requestJson(`/api/labor/runs/${laborState.run.id}/reocr-candidates/batch-preview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      laborState.reocrBatchPreview = { ...preview, runId: laborState.run.id };
      const preflightSummary = formatReocrPreflightSummary(preview.preflight);
      openGovernanceConfirm({
        type: "apply-reocr-batch",
        title: "批量采纳图片识别结果",
        subtitle: "采纳后覆盖当前批次正式核对结果并更新差异报告",
        defaultReason: `已复核批量预览：${preflightSummary}。`,
        summaryHtml: renderReocrBatchPreflightPanel(preview.preflight, "preview", preview.summary),
        warnings: preview.preflight?.postApplyWarnings || [],
      });
    } else if (action === "confirm-name-mapping") {
      if (!candidateId) return toast("未找到姓名匹配建议。");
      openGovernanceConfirm({
        type: "confirm-name-mapping",
        candidateId,
        title: "填写姓名匹配复核意见",
        subtitle: "确认后写入当前批次姓名匹配记录",
        defaultReason: "金额/工时接近，人工确认同一员工。",
        summaryHtml: `<p class="reocr-preflight-clear">姓名匹配会影响当前批次匹配结果，后续可撤回。</p>`,
      });
    } else if (action === "auto-replay-name-mapping") {
      if (!candidateId) return toast("未找到姓名匹配建议。");
      const replay = await requestJson(`/api/labor/runs/${laborState.run.id}/name-mapping-candidates/${encodeURIComponent(candidateId)}/auto-replay`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      toast(replay.decision === "ready_for_user_confirmation" ? "姓名匹配影响预览通过。" : "姓名匹配影响预览未通过。");
    } else if (action === "rollback-name-mapping") {
      if (!candidateId) return toast("未找到姓名匹配记录。");
      openGovernanceConfirm({
        type: "rollback-name-mapping",
        candidateId,
        title: "撤回姓名匹配",
        subtitle: "撤回后从当前批次姓名匹配记录移除对应关系",
        defaultReason: "发现姓名匹配不适用，撤回。",
        summaryHtml: `<p class="reocr-preflight-clear">撤回原因会写入姓名匹配审计记录。</p>`,
      });
    } else if (action === "confirm-allocation") {
      if (!candidateId) return toast("未找到跨仓库归属建议。");
      const candidate = (laborState.run.allocationGovernance?.candidates || []).find((item) => item.candidateId === candidateId);
      openGovernanceConfirm({
        type: "confirm-allocation",
        candidateId,
        title: "填写跨仓归属复核意见",
        subtitle: "确认后只记录复核结论，不改变核对金额或仓库归属",
        defaultReason: "已按仓库复核该员工发票与账单归属，确认留痕。",
        summaryHtml: renderAllocationConfirmSummary(candidate),
      });
    } else if (action === "rollback-allocation") {
      if (!candidateId) return toast("未找到跨仓库归属记录。");
      openGovernanceConfirm({
        type: "rollback-allocation",
        candidateId,
        title: "撤回跨仓库归属复核",
        subtitle: "撤回后该建议重新进入未闭环状态",
        defaultReason: "发现复核结论不适用，撤回。",
        summaryHtml: `<p class="reocr-preflight-clear">撤回原因会写入跨仓库归属审计记录。</p>`,
      });
    } else if (action === "auto-replay-correction") {
      await requestJson(`/api/labor/runs/${laborState.run.id}/correction-candidates/${encodeURIComponent(candidateId)}/auto-replay`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      toast("疑似误抽影响预览完成。");
    } else if (action === "confirm-correction") {
      openGovernanceConfirm({
        type: "confirm-correction",
        candidateId,
        title: "填写疑似误抽复核意见",
        subtitle: "确认后只记录复核结论，正式结果仍需单独预览或重算",
        actionLabel: "提交低置信度复核意见",
        defaultReason: "低置信度抽取证据已人工复核。",
        summaryHtml: `<p class="reocr-preflight-clear">提交复核意见不会自动覆盖正式结果；需要后续执行预览或重算。</p>`,
      });
    } else if (action === "preview-correction") {
      const preview = await requestJson(`/api/labor/runs/${laborState.run.id}/corrections/projected-preview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ candidateIds: [candidateId], generateReport: true }),
      });
      const delta = preview.summaryDelta || {};
      toast(`预览报告已生成：异常 ${formatSignedNumber(delta.exceptionCount || 0)}，低置信度 ${formatSignedNumber(delta.lowConfidenceCount || 0)}。`);
    } else if (action === "rollback-correction") {
      openGovernanceConfirm({
        type: "rollback-correction",
        candidateId,
        title: "撤回低置信度复核",
        subtitle: "撤回后复核意见移入审计记录",
        defaultReason: "发现复核意见不适用，撤回。",
        summaryHtml: `<p class="reocr-preflight-clear">撤回原因会写入复核审计记录。</p>`,
      });
    }
    const waitsForHumanInput = new Set([
      "confirm",
      "rollback",
      "confirm-profile",
      "rollback-profile",
      "replay-reocr",
      "confirm-reocr",
      "confirm-reocr-batch",
      "rollback-reocr",
      "apply-reocr",
      "apply-reocr-batch",
      "confirm-name-mapping",
      "rollback-name-mapping",
      "confirm-allocation",
      "rollback-allocation",
      "confirm-correction",
      "rollback-correction",
    ]);
    if (waitsForHumanInput.has(action)) return;
    setGovernanceActionFeedback(button, action, "success", originalLabel);
    await refreshCurrentRun();
    revealGovernanceFeedback();
  } catch (error) {
    setGovernanceActionFeedback(button, action, "error", originalLabel, error.message);
    renderGovernancePanel(laborState.run);
    revealGovernanceFeedback();
    toast(error.message);
  } finally {
    resetGovernanceActionButton(button, originalLabel);
  }
}

function getGovernanceActionLabel(action) {
  const labels = {
    "create-candidate": "生成处理建议",
    "generate-governance-report": "导出复核记录",
    "auto-replay": "预览影响",
    "auto-replay-profile": "预览供应商格式",
    "auto-replay-name-mapping": "预览姓名匹配",
    "auto-replay-correction": "预览疑似误抽",
    "submit-governance-confirm": "提交复核意见",
    "preview-correction": "生成预览报告",
    "preview-reocr-batch": "批量预览",
    "apply-reocr-batch": "批量采纳",
    "batch-replay-cache-reocr": "批量预览历史识别",
    "confirm-reocr-batch": "批量确认识别结果",
    "download-reocr-template": "生成模板",
    "download-reocr-template-batch": "生成批量模板",
    "upload-reocr": "上传并预览",
    "upload-reocr-batch": "上传批量识别结果",
  };
  return labels[action] || "处理";
}

function setGovernanceActionFeedback(button, action, phase, originalLabel, detail = "") {
  const label = originalLabel || button.dataset.originalLabel || button.textContent.trim() || getGovernanceActionLabel(action);
  if (!button.dataset.originalLabel) button.dataset.originalLabel = label;
  const actionLabel = getGovernanceActionLabel(action);
  if (phase === "loading") {
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    button.textContent = `${actionLabel}中...`;
    setGovernancePersistentFeedback("loading", `${actionLabel}中`, "系统正在处理，请稍候。", actionLabel);
    return label;
  }
  if (phase === "success") {
    setGovernancePersistentFeedback("success", `${actionLabel}完成`, "页面已刷新，处理结果已保留在当前批次。", actionLabel);
    return label;
  }
  if (phase === "error") {
    setGovernancePersistentFeedback("error", `${actionLabel}失败`, detail || "请重试。", actionLabel);
    return label;
  }
  return label;
}

function resetGovernanceActionButton(button, label) {
  if (!button || !button.isConnected) return;
  const originalLabel = label || button.dataset.originalLabel;
  button.disabled = false;
  button.removeAttribute("aria-busy");
  if (originalLabel) button.textContent = originalLabel;
  delete button.dataset.originalLabel;
}

function pickReocrCandidateFile() {
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".csv,.xlsx,.xlsm,.xls";
    input.addEventListener(
      "change",
      () => {
        resolve(input.files && input.files[0] ? input.files[0] : null);
      },
      { once: true }
    );
    input.click();
  });
}

async function uploadAndReplayReocrCandidate(task) {
  const file = await pickReocrCandidateFile();
  if (!file) return;
  const form = new FormData();
  form.append("candidate_file", file);
  form.append("task", JSON.stringify(task));
  if (task.amountTolerance != null) form.append("amount_tolerance", String(task.amountTolerance));
  const replay = await requestJson(`/api/labor/runs/${laborState.run.id}/reocr-candidates/replay-file`, {
    method: "POST",
    body: form,
  });
  toast(
    replay.decision === "ready_for_user_confirmation"
      ? `识别文件预览通过：${replay.parsedCandidateRowCount || 0} 行。`
      : `识别文件预览未通过：${(replay.blockers || []).join(", ")}`
  );
}

async function uploadAndReplayReocrCandidateBatch() {
  const file = await pickReocrCandidateFile();
  if (!file) return;
  const form = new FormData();
  form.append("candidate_file", file);
  const replay = await requestJson(`/api/labor/runs/${laborState.run.id}/reocr-candidates/replay-file-batch`, {
    method: "POST",
    body: form,
  });
  laborState.reocrBatchUpload = { ...replay, runId: laborState.run.id };
  renderGovernancePanel(laborState.run);
  toast(
    `批量识别预览完成：${replay.summary?.replayedCount || 0} 组，通过 ${replay.summary?.readyCount || 0}，阻断 ${
      replay.summary?.blockedCount || 0
    }，缺失 ${replay.summary?.missingTaskCount || 0}，错误 ${replay.summary?.errorCount || 0}。`
  );
}

async function refreshCurrentRun() {
  if (!laborState.run) return;
  laborState.run = await requestJson(`/api/labor/runs/${laborState.run.id}`);
  renderResult(laborState.run);
}

function renderPendingItems(rows, candidateMatches, summary, reviewQueues = {}) {
  const section = labor.pendingItemsSection;
  if (!section) return;

  // Group data
  const amountRateRows = sortPendingRowsByImpact(
    normalizeFormalAmountRateRows(reviewQueues?.amountRateReview?.rows, rows),
    "amountRate"
  );
  const hoursDiffRows = sortPendingRowsByImpact(rows.filter((row) => row.matchStatus === "工时不一致"), "hours");
  const notInInvoiceRows = sortPendingRowsByImpact(rows.filter((row) => row.matchStatus === "Excel有PDF无"), "amount");
  const sortedCandidateMatches = sortPendingRowsByImpact(candidateMatches || [], "candidate");

  // Check if there are pending items
  const hasItems = amountRateRows.length > 0 || hoursDiffRows.length > 0 || sortedCandidateMatches.length > 0 || notInInvoiceRows.length > 0;
  section.hidden = !hasItems;
  if (!hasItems) return;

  const overview = section.querySelector("#pendingItemsOverview");
  if (overview) {
    overview.innerHTML = _renderPendingOverview({
      amountRateRows,
      hoursDiffRows,
      candidateMatches: sortedCandidateMatches,
      notInInvoiceRows,
      summary: summary || {},
      reviewQueues,
    });
  }

  // Render groups
  _renderPendingGroup(labor.amountRateGroup, amountRateRows, _renderAmountRateReviewTable, () => _renderPendingPreview(amountRateRows, "amountRate"), { unit: "人" });
  _renderPendingGroup(labor.hoursDiffGroup, hoursDiffRows, _renderHoursDiffTable, () => _renderPendingPreview(hoursDiffRows, "hours"), { unit: "人" });
  _renderPendingGroup(labor.candidateGroup, sortedCandidateMatches, _renderCandidateTable, () => _renderPendingPreview(sortedCandidateMatches, "candidate"), { unit: "条" });
  _renderPendingGroup(labor.notInInvoiceGroup, notInInvoiceRows, _renderNotInInvoiceTable, () => _renderPendingPreview(notInInvoiceRows, "notInInvoice"), { unit: "人" });
  updatePendingGroupLayout(section);
}

function updatePendingGroupLayout(section) {
  if (!section) return;
  const visibleGroups = Array.from(section.querySelectorAll(".pending-group"))
    .filter((group) => !group.hidden && Number(group.dataset.count || 0) > 0);
  const row = section.querySelector(".pending-groups-row");
  if (!row) return;
  row.dataset.visibleGroups = String(visibleGroups.length);
  row.classList.toggle("is-single", visibleGroups.length === 1);
  section.querySelectorAll(".pending-group").forEach((group) => {
    const isDominant = visibleGroups.length === 1 && visibleGroups[0] === group;
    group.classList.toggle("is-dominant", isDominant);
    group.classList.remove("is-expanded");
    if (!isDominant) return;
    const content = group.querySelector(".group-content");
    const header = group.querySelector(".group-header");
    const icon = group.querySelector(".expand-icon");
    const actionLabel = group.querySelector(".group-action-label");
    if (content) content.hidden = true;
    if (header) header.setAttribute("aria-expanded", "false");
    if (icon) icon.textContent = "▸";
    if (actionLabel) actionLabel.textContent = "展开前 5 条";
  });
}

function normalizeFormalAmountRateRows(queueRows, comparisonRows) {
  if (Array.isArray(queueRows) && queueRows.length) return queueRows;
  return (comparisonRows || [])
    .filter((row) => row.matchStatus === "金额差异")
    .map((row) => {
      const hoursDelta = Number(row.hoursDelta || 0);
      const amountDelta = Number(row.amountDelta || 0);
      const hoursAligned = Math.abs(hoursDelta) <= 0.1;
      return {
        ...row,
        reviewFocus: hoursAligned ? "先核金额口径" : "先核工时口径",
        amountDirectionLabel: amountDelta > 0 ? "PDF 高于 Excel" : amountDelta < 0 ? "PDF 少于 Excel" : "金额一致",
        hoursDirectionLabel: hoursAligned ? "工时一致" : hoursDelta > 0 ? "PDF 工时多于 Excel" : "PDF 工时少于 Excel",
        businessQuestion: hoursAligned
          ? `PDF 与 Excel 工时一致，金额差 ${formatSignedMoney(amountDelta)}；请确认费率、加班、服务费或税费是否同一口径。`
          : `PDF 与 Excel 工时差 ${formatSignedNumber(hoursDelta)}，金额差 ${formatSignedMoney(amountDelta)}；请先确认账期、日期行和加班工时。`,
        recommendation: hoursAligned
          ? "先核对 PDF 发票费率、加班/差额行、服务费倍率与 Excel 成本口径；确认前不能自动清账。"
          : "先核对 PDF 与 Excel 的账期范围、日期行、加班行是否一致；确认前不能自动清账。",
      };
    });
}

function sortPendingRowsByImpact(items, type) {
  return [...(items || [])].sort((left, right) => pendingImpactScore(right, type) - pendingImpactScore(left, type));
}

function pendingImpactScore(row, type) {
  if (!row) return 0;
  if (type === "hours") return Math.abs(Number(row.hoursDelta || 0));
  if (type === "candidate") {
    return Math.max(
      Math.abs(Number(row.amountDelta || 0)),
      Math.abs(Number(row.pdfAmountTotal || 0) - Number(row.excelAmountTotal || 0))
    );
  }
  if (type === "amountRate") return Math.abs(Number(row.amountDelta || 0));
  return Math.abs(Number(row.excelAmountTotal ?? row.amountDelta ?? 0));
}

function _renderPendingOverview({ amountRateRows, hoursDiffRows, candidateMatches, notInInvoiceRows, summary, reviewQueues }) {
  const totalCount = amountRateRows.length + hoursDiffRows.length + candidateMatches.length + notInInvoiceRows.length;
  const excelOnlyAmount = notInInvoiceRows.reduce((sum, row) => sum + Math.abs(Number(row.excelAmountTotal || 0)), 0);
  const amountRateImpact = amountRateRows.reduce((sum, row) => sum + Math.abs(Number(row.amountDelta || 0)), 0);
  const hoursImpact = hoursDiffRows.reduce((sum, row) => sum + Math.abs(Number(row.hoursDelta || 0)), 0);
  const primary = reviewQueues?.primary || "";
  const primaryLabel =
    primary === "amount_rate_review" || amountRateRows.length >= Math.max(hoursDiffRows.length, candidateMatches.length, notInInvoiceRows.length)
      ? "先确认金额计算口径"
      : notInInvoiceRows.length >= Math.max(hoursDiffRows.length, candidateMatches.length)
      ? "先确认是否属于本批发票"
      : hoursDiffRows.length
      ? "先核对工时口径"
      : "先处理姓名匹配建议";
  return `<div class="pending-overview-grid">
    <div>
      <span>待处理总数</span>
      <strong>${escapeHtml(totalCount)} 项</strong>
      <p>${escapeHtml(primaryLabel)}</p>
    </div>
    <div>
      <span>金额口径待确认</span>
      <strong>${escapeHtml(amountRateRows.length)} 人</strong>
      <p>影响 ${formatMoney(amountRateImpact)}</p>
    </div>
    <div>
      <span>不在本批发票</span>
      <strong>${escapeHtml(notInInvoiceRows.length)} 人</strong>
      <p>账单金额 ${formatMoney(excelOnlyAmount)}</p>
    </div>
    <div>
      <span>工时不一致</span>
      <strong>${escapeHtml(hoursDiffRows.length)} 人</strong>
      <p>工时差 ${formatHours(hoursImpact)}</p>
    </div>
    <div>
      <span>姓名匹配建议</span>
      <strong>${escapeHtml(candidateMatches.length)} 条</strong>
      <p>确认前只预览，不自动改结果</p>
    </div>
  </div>`;
}

function _renderPendingGroup(groupEl, items, renderFn, previewFn, options = {}) {
  if (!groupEl) return;
  if (!items || items.length === 0) {
    groupEl.hidden = true;
    groupEl.dataset.count = 0;
    return;
  }
  groupEl.hidden = false;
  groupEl.dataset.count = items.length;
  const unit = options.unit || "项";
  const countEl = groupEl.querySelector(".group-count");
  if (countEl) countEl.textContent = `${items.length} ${unit}`;
  const actionEl = groupEl.querySelector(".group-action-label");
  if (actionEl) actionEl.textContent = items.length > 5 ? "展开前 5 条" : "展开明细";

  const previewEl = groupEl.querySelector(".group-preview");
  if (previewEl) {
    previewEl.innerHTML = previewFn ? previewFn(items) : _renderPendingPreview(items, "default");
  }

  const contentEl = groupEl.querySelector(".group-content");
  if (contentEl) {
    contentEl.innerHTML = renderFn(items);
    contentEl.hidden = true;
    groupEl.classList.remove("is-expanded");
  }

  // Bind fold/expand events
  const header = groupEl.querySelector(".group-header");
  if (header) {
    header.setAttribute("aria-expanded", "false");
    const icon = header.querySelector(".expand-icon");
    if (icon) icon.textContent = "▸";
  }
  if (header && !header._bound) {
    header._bound = true;
    header.addEventListener("click", () => {
      const icon = header.querySelector(".expand-icon");
      const content = groupEl.querySelector(".group-content");
      if (!content) return;
      const expanded = !content.hidden;
      content.hidden = expanded;
      groupEl.classList.toggle("is-expanded", !expanded);
      header.setAttribute("aria-expanded", String(!expanded));
      if (icon) icon.textContent = expanded ? "▸" : "▾";
      const currentCount = Number(groupEl.dataset.count || 0);
      if (actionEl) actionEl.textContent = expanded ? (currentCount > 5 ? "展开前 5 条" : "展开明细") : "收起";
    });
  }
}

function _renderPendingPreview(items, type) {
  if (!items || !items.length) return "";
  const totalAmount = items.reduce(
    (sum, row) => sum + Math.abs(Number(type === "amountRate" ? row.amountDelta || 0 : row.excelAmountTotal ?? row.amountDelta ?? 0)),
    0
  );
  const totalHours = items.reduce((sum, row) => sum + Math.abs(Number(row.excelHoursTotal ?? row.hoursDelta ?? 0)), 0);
  const stats =
    type === "candidate"
      ? [
          `建议 ${items.length} 条`,
          `平均相似度 ${formatPercent(items.reduce((sum, row) => sum + Number(row.nameSimilarity || 0), 0) / items.length)}`,
        ]
      : type === "amountRate"
      ? [`金额差 ${formatMoney(totalAmount)}`, `涉及 ${items.length} 人`]
      : type === "hours"
      ? [`工时差 ${formatHours(totalHours)}`, `涉及 ${items.length} 人`]
      : [`账单金额 ${formatMoney(totalAmount)}`, `账单工时 ${formatHours(totalHours)}`];
  const names = items
    .slice(0, 3)
    .map((row) => row.employeeName || row.pdfEmployeeName || row.excelEmployeeName || "")
    .filter(Boolean);
  const chips = names.map((name) => `<span class="pending-chip">${escapeHtml(name)}</span>`).join("");
  const more = items.length > names.length ? `<span class="pending-more">其余 ${items.length - names.length} 条已收起，完整名单下载报告</span>` : "";
  return `<div class="pending-stat-row">${stats.map((item) => `<span class="pending-stat">${escapeHtml(item)}</span>`).join("")}</div>
    <div class="pending-chip-row">${chips}${more}</div>`;
}

function _renderAmountRateReviewTable(rows) {
  if (!rows.length) return "";
  const visible = rows.slice(0, 5);
  return `<div class="pending-detail-list">${visible
    .map(
      (row) => `<div class="pending-detail-item">
        <strong>${escapeHtml(row.employeeName)}</strong>
        <span>${escapeHtml(row.reviewFocus || "核对金额口径")} · ${escapeHtml(row.amountDirectionLabel || "")}</span>
        <span>PDF ${formatHours(row.pdfHoursTotal)}h / ${formatMoney(row.pdfAmountTotal)}</span>
        <span>Excel ${formatHours(row.excelHoursTotal)}h / ${formatMoney(row.excelAmountTotal)}</span>
        <b>${escapeHtml(row.businessQuestion || row.recommendation || "确认费率、加班、服务费或税费是否同一口径。")}</b>
      </div>`
    )
    .join("")}</div>${renderPendingLimitNote(rows.length, visible.length)}`;
}

function _renderHoursDiffTable(rows) {
  if (!rows.length) return "";
  const visible = rows.slice(0, 5);
  return `<div class="pending-detail-list">${visible
    .map(
      (row) => `<div class="pending-detail-item">
        <strong>${escapeHtml(row.employeeName)}</strong>
        <span>PDF ${formatHours(row.pdfHoursTotal)}h / ${formatMoney(row.pdfAmountTotal)}</span>
        <span>Excel ${formatHours(row.excelHoursTotal)}h / ${formatMoney(row.excelAmountTotal)}</span>
        <b>差异 ${formatHours(row.hoursDelta)}h</b>
      </div>`
    )
    .join("")}</div>${renderPendingLimitNote(rows.length, visible.length)}`;
}

function _renderCandidateTable(rows) {
  if (!rows.length) return "";
  const visible = rows.slice(0, 5);
  return `<div class="pending-detail-list">${visible
    .map(
      (row) => `<div class="pending-detail-item">
        <strong>${escapeHtml(row.pdfEmployeeName)} ⇄ ${escapeHtml(row.excelEmployeeName)}</strong>
        <span>${escapeHtml(row.issueType === "combined_pdf_row" ? "疑似 PDF 合并员工" : "疑似同一员工")} · 相似度 ${formatPercent(row.nameSimilarity)}</span>
        <span>PDF ${formatMoney(row.pdfAmountTotal)} / Excel ${formatMoney(row.excelAmountTotal)}</span>
        <b>建议：${escapeHtml(row.recommendation || "人工复核后确认")}</b>
      </div>`
    )
    .join("")}</div>${renderPendingLimitNote(rows.length, visible.length)}`;
}

function _renderNotInInvoiceTable(rows) {
  if (!rows.length) return "";
  const visible = rows.slice(0, 5);
  return `<div class="pending-detail-list">${visible
    .map(
      (row) => `<div class="pending-detail-item">
        <strong>${escapeHtml(row.employeeName)}</strong>
        <span>Excel 金额 ${formatMoney(row.excelAmountTotal)}</span>
        <span>Excel 工时 ${formatHours(row.excelHoursTotal)}</span>
        <b>处理：确认是否不属于本批发票</b>
      </div>`
    )
    .join("")}</div>${renderPendingLimitNote(rows.length, visible.length)}`;
}

function renderPendingLimitNote(total, visible) {
  return total > visible ? `<p class="table-note">这里只展示前 ${visible} 条，完整名单请下载报告。</p>` : "";
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
  const lowConfidenceRows = rows.filter((row) => Number(row.confidence || 0) < 0.9);
  const highAmountRows = [...rows].sort((a, b) => Math.abs(Number(b.amount || 0)) - Math.abs(Number(a.amount || 0))).slice(0, 8);
  const focusRows = uniqueRowsByEvidence([...lowConfidenceRows, ...highAmountRows, ...rows]).slice(0, 16);
  const totalAmount = rows.reduce((sum, row) => sum + Number(row.amount || 0), 0);
  const totalHours = rows.reduce((sum, row) => sum + Number(row.hours || 0), 0);
  container.innerHTML = `
    <div class="extract-evidence-summary">
      <div><span>抽取员工行</span><strong>${rows.length}</strong></div>
      <div><span>低置信度</span><strong>${lowConfidenceRows.length}</strong></div>
      <div><span>抽取金额合计</span><strong>${formatMoney(totalAmount)}</strong></div>
      <div><span>抽取工时合计</span><strong>${formatHours(totalHours)}</strong></div>
    </div>
    <table><thead><tr><th>员工</th><th>工号</th><th>工时</th><th>金额</th><th>置信度</th><th>来源</th><th>证据</th></tr></thead><tbody>${focusRows
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
    rows.length > focusRows.length
      ? `<p class="table-note">页面聚焦展示低置信度和高金额证据 ${focusRows.length} 条；完整 ${rows.length} 条请下载报告查看。</p>`
      : ""
  }`;
}

function uniqueRowsByEvidence(rows) {
  const seen = new Set();
  const result = [];
  rows.forEach((row) => {
    const key = [
      row.source_file || "",
      row.source_page_or_row || "",
      row.employee_id || "",
      row.employee_name_raw || "",
      row.hours || "",
      row.amount || "",
      row.evidence_text || "",
    ].join("|");
    if (seen.has(key)) return;
    seen.add(key);
    result.push(row);
  });
  return result;
}

// ── Utility functions ──
async function requestJson(url, options = {}) {
  let response;
  try {
    response = await fetch(url, options);
  } catch (error) {
    throw new Error("无法连接本地服务。请确认 127.0.0.1:8001 已启动后再重试。");
  }
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

function formatSignedMoney(value) {
  const number = Number(value || 0);
  if (number === 0) return "$0.00";
  return `${number > 0 ? "+" : "-"}$${formatMoney(Math.abs(number))}`;
}

function formatReocrPreflightSummary(preflight) {
  if (!preflight) return "未取得采纳影响摘要";
  const amountDelta = preflight.delta?.amountDeltaTotal ?? preflight.projected?.amountDeltaTotal ?? 0;
  const warnings = Array.isArray(preflight.postApplyWarnings) ? preflight.postApplyWarnings : [];
  const statusText = warnings.length ? warnings[0] : "采纳后将更新正式核对结果和差异报告";
  return `影响 ${preflight.affectedScopeCount || 0} 个范围、${preflight.affectedEmployeeCount || 0} 名员工，金额差额变化 ${formatSignedMoney(amountDelta)}；${statusText}`;
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

function formatGovernanceReason(reason) {
  const labels = {
    low_confidence: "低置信度抽取",
    low_confidence_extraction: "低置信度抽取",
    name_mapping_candidate: "疑似同名员工",
    profile_candidate: "供应商格式建议",
    cross_warehouse_allocation: "跨仓归属待复核",
    cross_warehouse_employee_allocation: "跨仓归属待复核",
  };
  return labels[String(reason || "").trim()] || String(reason || "待人工复核").replaceAll("_", " ");
}

function formatSignedNumber(value) {
  const number = Number(value || 0);
  if (number === 0) return "0";
  return `${number > 0 ? "+" : ""}${number.toLocaleString("en-US")}`;
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
