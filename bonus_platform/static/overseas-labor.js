const laborState = {
  run: null,
  headers: [],
  comparePollTimer: null,
  pollRetryCount: 0,
  pollMaxRetries: 200,  // 200 × 3s = 10 分钟
  extractStartedAt: null,
  currentStep: 1,
  materialIndex: null,
  materialDryRun: null,
  moduleAccess: null,
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
    laborState.moduleAccess = access;
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
    laborState.moduleAccess = null;
  }
}

function isVercelLaborLightUat() {
  const access = String(laborState.moduleAccess?.access || "").toLowerCase();
  return Boolean(window.location.hostname && window.location.hostname.endsWith("vercel.app")) && ["uat_trial", "uat", "trial"].includes(access);
}

function showVercelLightUatExtractBlocked() {
  const message = "当前 Vercel UAT 仅支持页面试用和测试材料验证，不启动正式在线抽取任务。请在本地/内网持久化环境执行正式抽取并核对。";
  setText(labor.compareStatus, message, true);
  toast("当前环境不支持正式在线抽取。");
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
  if (isVercelLaborLightUat()) {
    showVercelLightUatExtractBlocked();
    return;
  }
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
      const message = formatLaborFailureMessage(run);
      setText(labor.compareStatus, message, true);
      recordLaborTelemetry("labor.extract.failed", {
        run,
        step: "extract_compare",
        status: "failed",
        durationMs: elapsedMs(laborState.extractStartedAt),
        errorCode: run.errorCode || "",
        errorMessage: message,
      });
      laborState.extractStartedAt = null;
      toast(run.retryable ? "抽取任务中断，可直接重试。" : "抽取失败。");
      return;
    }
    if (run.diffDownloadUrl || run.status === "已生成差异报告") {
      stopComparePolling();
      labor.extractCompare.disabled = false;
      renderResult(run);
      setText(labor.compareStatus, "核对完成。低置信度项已在风险表标记。");
      setDownload(preferredLaborReportDownloadUrl(run));
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

function formatLaborFailureMessage(run) {
  const message = run?.errorMessage || "抽取失败，请检查文件后重试。";
  if (!run?.retryable) return message;
  const nextAction = run.nextAction || "请重新点击「抽取并核对」重试。";
  const stage = run.stage || "系统中断";
  return `${stage}：${message} ${nextAction}`;
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
  updateKpiCards(summary, rows, wcSummary, run.candidateMatches || [], run);

  // 1. 结论 — 用户第一眼看到
  renderConclusion(summary, wcSummary, run.extractionQuality, run);
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
  renderPendingItems(rows, run.candidateMatches || [], summary, run.reviewQueues || {});

  // 5. 抽取明细 / 通过证据
  if (totalPassed) {
    renderPassEvidence(labor.extractPreviewTable, summary, wcSummary);
  } else {
    renderExtractRows(labor.extractPreviewTable, run.pdfExtractedRows || []);
  }
}

function updateKpiCards(summary, rows, wcSummary, candidateMatches = [], run = {}) {
  const pdfCount = summary.pdfEmployeeCount || 0;
  const excelCount = summary.excelEmployeeCount || 0;
  const skippedEmployeeDrilldown = wcSummary && wcSummary.totalPassed && !rows.length;
  const amountDiffCount = summary.amountDiffCount || 0;
  const notInInvoiceCount = summary.notInInvoiceCount || 0;
  const pdfAmount = wcSummary ? wcSummary.pdfAmountTotal || 0 : summary.pdfAmountTotal || 0;
  const excelAmount = wcSummary ? wcSummary.excelAmountTotal || 0 : summary.excelAmountTotal || 0;
  const amountDelta = wcSummary ? wcSummary.amountDeltaTotal || 0 : summary.amountDeltaTotal || 0;
  const pdfInvoiceCount = Array.isArray(run?.files?.pdfInvoices) ? run.files.pdfInvoices.length : 0;
  const excelRecordCount = Array.isArray(run?.excelRows)
    ? run.excelRows.length
    : Array.isArray(run?.warehouseComparison?.rows)
      ? run.warehouseComparison.rows.reduce((sum, row) => sum + Number(row.excelEmployeeCount || 0), 0)
      : excelCount;
  const reviewWarehouses = Array.isArray(wcSummary?.diffWarehouses) ? wcSummary.diffWarehouses : [];

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
  if (totalCard) totalCard.textContent = pdfInvoiceCount ? `${pdfInvoiceCount} 张发票` : (skippedEmployeeDrilldown ? "总额已核对" : `PDF ${pdfCount} 人`);
  if (matchedCard) matchedCard.textContent = excelRecordCount ? `整批账单 ${excelRecordCount} 行` : (skippedEmployeeDrilldown ? "无需查看员工明细" : `Excel ${excelCount} 人`);
  if (varianceCard) varianceCard.textContent = `容差 $0.10`;
  if (unmatchedCard) unmatchedCard.textContent = reviewWarehouses.length ? `需复核仓库 ${reviewWarehouses.join("、")}` : (clearedCount ? `${clearedCount} 人已清账` : "异常队列");
}

function renderConclusion(summary, wcSummary, extractionQuality, run = {}) {
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

  const reviewEmployeeCount = summary.excelEmployeeCount || 0;
  const excelRecordCount = Array.isArray(run?.excelRows)
    ? run.excelRows.length
    : Array.isArray(run?.warehouseComparison?.rows)
      ? run.warehouseComparison.rows.reduce((sum, row) => sum + Number(row.excelEmployeeCount || 0), 0)
      : reviewEmployeeCount;
  const notInInvoice = summary.notInInvoiceCount || 0;
  const reviewWarehouses = Array.isArray(wcSummary?.diffWarehouses) ? wcSummary.diffWarehouses : [];
  const hasReviewWarehouses = reviewWarehouses.length > 0;
  const userMessage = hasReviewWarehouses
    ? `整批账单已读取 ${excelRecordCount || reviewEmployeeCount} 行；下面只展示需要复核的员工明细，不代表账单只有这些人。`
    : conclusionMessage;
  const scopeText = hasReviewWarehouses
    ? `需复核仓库：${reviewWarehouses.join("、")}；当前员工明细 ${reviewEmployeeCount} 人。`
    : `账单员工/记录数 ${reviewEmployeeCount}${notInInvoice > 0 ? `，${notInInvoice} 人不在本批发票` : ""}`;

  section.hidden = false;
  section.className = `conclusion-section ${conclusionLevel}`;
  section.innerHTML = `
    <div class="conclusion-main">
      <span class="conclusion-icon" aria-hidden="true"></span>
      <span class="conclusion-text">${escapeHtml(label)} · ${escapeHtml(userMessage)}</span>
    </div>
    <div class="conclusion-details">
      <span>总金额差异: <strong>$${amountDeltaTotal.toFixed(2)} (${amountDeltaPct}%)</strong></span>
      <span>${escapeHtml(scopeText)}</span>
    </div>
    ${buildBusinessReportPrompt(run)}
  `;
}

function buildBusinessReportPrompt(run) {
  const businessUrl = preferredLaborReportDownloadUrl(run);
  if (!businessUrl) return "";
  const internalExcelUrl = run?.diffDownloadUrl || run?.files?.diffReport?.downloadUrl || "";
  const excelLink = internalExcelUrl && internalExcelUrl !== businessUrl
    ? `<a href="${escapeHtml(internalExcelUrl)}" download>内部差异 Excel</a>`
    : "";
  return `
    <div class="conclusion-details">
      <span><strong>业务报告已生成，可下载留档或转发给业务复核。</strong></span>
      <span><a href="${escapeHtml(businessUrl)}" download>下载业务报告</a>${excelLink ? ` · ${excelLink}` : ""}</span>
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
  const title = section.querySelector(".section-title");
  const subtitle = section.querySelector(".section-sub");
  const reviewWarehouses = Array.isArray(wcSummary?.diffWarehouses) ? wcSummary.diffWarehouses : [];
  if (title) title.textContent = reviewWarehouses.length ? "需复核员工明细" : "员工对账明细";
  if (subtitle) {
    subtitle.textContent = reviewWarehouses.length
      ? `只展示需要复核的员工明细，不代表账单只有这些人。需复核仓库：${reviewWarehouses.join("、")}`
      : "金额或工时有差异的排在前面";
  }

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
    ? "总金额存在差异，先看差异仓库，再确认员工明细。"
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
    const host = window.location.host || "当前环境";
    throw new Error(`无法连接当前服务（${host}）。请稍后重试；若持续失败，请联系管理员检查环境状态。`);
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(formatLaborRequestError(data.detail || data.message || "请求失败。"));
  return data;
}

function formatLaborRequestError(message) {
  const detailMessage = message?.message || message;
  const nextAction = message?.nextAction || "";
  const text = [detailMessage, nextAction].filter(Boolean).join(" ").trim();
  if (/批次不存在|run.*not found|not found/i.test(text)) {
    return "本批次记录未找到。请返回「新建核对批次」重新创建并上传材料；如果刚上传过文件，请确认当前环境是否支持持久化保存。";
  }
  if (/上传|upload|文件|file|持久化|保存/.test(text)) {
    return "上传文件未保存成功。请重新上传 PDF 发票和 Excel 账单；若仍失败，请改用本地/内网持久化环境处理。";
  }
  if (/Failed to fetch|NetworkError|Load failed|无法连接|连接失败/i.test(text)) {
    return "无法连接当前服务。请确认本地服务已启动并刷新页面；若在 UAT 环境，请联系管理员检查服务状态。";
  }
  return text || "请求失败。请检查本批次材料后重试。";
}

function setDownload(url) {
  if (!url) return;
  labor.reportLink.href = url;
  labor.reportLink.classList.remove("disabled");
  labor.reportLink.removeAttribute("aria-disabled");
}

function preferredLaborReportDownloadUrl(run) {
  return run?.businessReportDownloadUrl || run?.files?.businessReport?.downloadUrl || run?.diffDownloadUrl || "";
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
