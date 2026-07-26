const LABOR_UI_MODULE_VERSION = "0.5-uat";
const LABOR_UI_API_CONTRACT_VERSION = 2;

function detectLaborWorkerPlatform() {
  const platform = String(navigator.userAgentData?.platform || navigator.platform || navigator.userAgent || "");
  return /win/i.test(platform) ? "windows-x64" : "macos-arm64";
}

function laborWorkerPlatformLabel(platform) {
  return platform === "windows-x64" ? "Windows x64" : "macOS Apple 芯片";
}

const laborState = {
  run: null,
  headers: [],
  comparePollTimer: null,
  pollRetryCount: 0,
  pollMaxIdleSeconds: 600,
  extractStartedAt: null,
  currentStep: 1,
  materialIndex: null,
  materialDryRun: null,
  moduleAccess: null,
  releaseCompatible: false,
  workerDevices: [],
  workerRelease: null,
  workerPlatform: detectLaborWorkerPlatform(),
  selectedPdfFiles: [],
  selectedWorkbookFiles: [],
};

let laborFieldSuggestionRequestId = 0;
let laborRunRestoreGeneration = 0;

const LABOR_TOTAL_AMOUNT_TOLERANCE = 0.1;

const periodPickerState = {
  cursorMonth: null,
  selectingEnd: false,
};

const buttonLoadingState = new WeakMap();

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
  moduleReleaseMeta: document.querySelector("#moduleReleaseMeta"),
  btnOpenDrawer: document.querySelector("#btnOpenDrawer"),
  btnOpenGovernance: document.querySelector("#btnOpenGovernance"),
  governanceDialog: document.querySelector("#laborGovernanceDialog"),
  closeGovernance: document.querySelector("#closeLaborGovernance"),
  deleteCurrentRun: document.querySelector("#deleteCurrentLaborRun"),
  storageSummary: document.querySelector("#laborStorageSummary"),
  auditList: document.querySelector("#laborAuditList"),
  btnWorkerStatus: document.querySelector("#btnWorkerStatus"),
  workerStatusLabel: document.querySelector("#workerStatusLabel"),
  workerSection: document.querySelector("#laborWorkerSection"),
  workerMessage: document.querySelector("#laborWorkerMessage"),
  workerDevices: document.querySelector("#laborWorkerDevices"),
  activateWorker: document.querySelector("#activateLaborWorker"),
  refreshWorker: document.querySelector("#refreshLaborWorker"),
  downloadWorker: document.querySelector("#downloadLaborWorker"),
  workerReleaseStatus: document.querySelector("#laborWorkerReleaseStatus"),
  workerReleaseAdmin: document.querySelector("#laborWorkerReleaseAdmin"),
  workerReleasePlatform: document.querySelector("#laborWorkerReleasePlatform"),
  workerReleasePackage: document.querySelector("#laborWorkerReleasePackage"),
  uploadWorkerRelease: document.querySelector("#uploadLaborWorkerRelease"),
  workerReleaseUploadStatus: document.querySelector("#laborWorkerReleaseUploadStatus"),

  // Page views
  toolbench: document.querySelector("#laborToolbench"),
  resultsView: document.querySelector("#laborResultsView"),

  // Form elements
  supplierName: document.querySelector("#supplierName"),
  supplierOptions: document.querySelector("#supplierOptions"),
  periodStart: document.querySelector("#periodStart"),
  periodEnd: document.querySelector("#periodEnd"),
  periodRange: document.querySelector("#periodRange"),
  periodRangeValue: document.querySelector("#periodRangeValue"),
  periodCalendar: document.querySelector("#periodCalendar"),
  periodCalendarTitle: document.querySelector("#periodCalendarTitle"),
  periodCalendarGrid: document.querySelector("#periodCalendarGrid"),
  periodCalendarHint: document.querySelector("#periodCalendarHint"),
  periodCalendarPrev: document.querySelector("#periodCalendarPrev"),
  periodCalendarNext: document.querySelector("#periodCalendarNext"),
  clearPeriodRange: document.querySelector("#clearPeriodRange"),
  currency: document.querySelector("#currency"),
  createLaborRun: document.querySelector("#createLaborRun"),
  createStatus: document.querySelector("#createStatus"),

  // File upload
  pdfFiles: document.querySelector("#pdfFiles"),
  pdfFileName: document.querySelector("#pdfFileName"),
  workbookFile: document.querySelector("#workbookFile"),
  workbookFileName: document.querySelector("#workbookFileName"),
  uploadLaborFiles: document.querySelector("#uploadLaborFiles"),
  clearLaborFiles: document.querySelector("#clearLaborFiles"),
  uploadStatus: document.querySelector("#uploadStatus"),

  // Field mapping
  loadSheets: document.querySelector("#loadSheets"),
  saveMapping: document.querySelector("#saveMapping"),
  sheetSelect: document.querySelector("#sheetSelect"),
  employeeIdColumn: document.querySelector("#employeeIdColumn"),
  nameColumn: document.querySelector("#nameColumn"),
  hoursColumn: document.querySelector("#hoursColumn"),
  amountColumn: document.querySelector("#amountColumn"),
  amountComponentColumns: document.querySelector("#amountComponentColumns"),
  amountScope: document.querySelector("#amountScope"),
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
  autoFixSection: document.querySelector("#autoFixSection"),
  autoFixBody: document.querySelector("#autoFixBody"),
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
bindPeriodPicker();
listenKpiFilters();
showLaborToolbench();
setLaborActionAvailability(false);
loadModuleAccess().then(async () => {
  await Promise.all([restoreLaborRunFromUrl(), loadLaborWorkerRelease()]);
});
loadSupplierOptions();

function bindPeriodPicker() {
  if (!labor.periodRange || !labor.periodCalendar || !labor.periodCalendarGrid) return;

  labor.periodRange.addEventListener("click", (event) => {
    event.stopPropagation();
    if (labor.periodCalendar.hidden) openPeriodRangePicker();
    else closePeriodRangePicker();
  });
  labor.periodCalendar.addEventListener("click", (event) => event.stopPropagation());
  labor.periodCalendarPrev?.addEventListener("click", () => movePeriodCalendarMonth(-1));
  labor.periodCalendarNext?.addEventListener("click", () => movePeriodCalendarMonth(1));
  labor.clearPeriodRange?.addEventListener("click", clearPeriodRange);
  labor.periodCalendarGrid.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target.closest("[data-period-date]") : null;
    if (!target) return;
    selectPeriodDate(target.dataset.periodDate || "");
  });
  labor.periodCalendarGrid.addEventListener("keydown", handlePeriodCalendarKeydown);
  document.addEventListener("click", () => closePeriodRangePicker());
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || labor.periodCalendar.hidden) return;
    closePeriodRangePicker({ restoreFocus: true });
  });
  syncPeriodRangePicker();
}

function openPeriodRangePicker() {
  if (!labor.periodRange || !labor.periodCalendar || labor.periodRange.disabled) return;
  const selectedStart = parseInputDate(labor.periodStart?.value || "");
  const base = selectedStart || new Date();
  periodPickerState.cursorMonth = new Date(base.getFullYear(), base.getMonth(), 1);
  periodPickerState.selectingEnd = false;
  labor.periodCalendar.hidden = false;
  labor.periodRange.setAttribute("aria-expanded", "true");
  renderPeriodCalendar();
  window.requestAnimationFrame(() => {
    const preferredValue = labor.periodStart?.value || formatInputDate(new Date());
    const preferred = labor.periodCalendarGrid.querySelector(`[data-period-date="${preferredValue}"]`)
      || labor.periodCalendarGrid.querySelector("[data-period-date]");
    preferred?.focus();
  });
}

function closePeriodRangePicker({ restoreFocus = false } = {}) {
  if (!labor.periodCalendar || labor.periodCalendar.hidden) return;
  labor.periodCalendar.hidden = true;
  labor.periodRange?.setAttribute("aria-expanded", "false");
  periodPickerState.selectingEnd = false;
  if (restoreFocus) labor.periodRange?.focus();
}

function movePeriodCalendarMonth(offset) {
  const base = periodPickerState.cursorMonth || new Date();
  periodPickerState.cursorMonth = new Date(base.getFullYear(), base.getMonth() + offset, 1);
  renderPeriodCalendar();
}

function handlePeriodCalendarKeydown(event) {
  const target = event.target instanceof Element ? event.target.closest("[data-period-date]") : null;
  if (!target) return;
  const offsets = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 };
  const offset = offsets[event.key];
  if (!offset) return;
  const current = parseInputDate(target.dataset.periodDate || "");
  if (!current) return;
  event.preventDefault();
  const next = addDays(current, offset);
  periodPickerState.cursorMonth = new Date(next.getFullYear(), next.getMonth(), 1);
  renderPeriodCalendar();
  labor.periodCalendarGrid.querySelector(`[data-period-date="${formatInputDate(next)}"]`)?.focus();
}

function selectPeriodDate(value) {
  const picked = parseInputDate(value);
  if (!picked) return;
  const start = parseInputDate(labor.periodStart?.value || "");

  if (!periodPickerState.selectingEnd || !start || picked < start) {
    const automaticEnd = addDays(picked, 6);
    setPeriodRangeValues(formatInputDate(picked), formatInputDate(automaticEnd));
    periodPickerState.cursorMonth = new Date(picked.getFullYear(), picked.getMonth(), 1);
    periodPickerState.selectingEnd = true;
    setText(
      labor.createStatus,
      `已按 7 天选择账期：${formatInputDate(picked)} 至 ${formatInputDate(automaticEnd)}；可再点日期修改结束日。`
    );
    renderPeriodCalendar();
    return;
  }

  setPeriodRangeValues(formatInputDate(start), formatInputDate(picked));
  periodPickerState.cursorMonth = new Date(picked.getFullYear(), picked.getMonth(), 1);
  periodPickerState.selectingEnd = false;
  setText(labor.createStatus, `已选择账期：${formatInputDate(start)} 至 ${formatInputDate(picked)}`);
  renderPeriodCalendar();
  window.setTimeout(() => closePeriodRangePicker({ restoreFocus: true }), 140);
}

function clearPeriodRange() {
  setPeriodRangeValues("", "");
  periodPickerState.selectingEnd = false;
  const now = new Date();
  periodPickerState.cursorMonth = new Date(now.getFullYear(), now.getMonth(), 1);
  setText(labor.createStatus, "已清空账期，可重新选择。");
  renderPeriodCalendar();
}

function setPeriodRangeValues(startValue, endValue) {
  if (labor.periodStart) labor.periodStart.value = startValue;
  if (labor.periodEnd) labor.periodEnd.value = endValue;
  syncPeriodRangePicker();
}

function syncPeriodRangePicker() {
  if (!labor.periodRange || !labor.periodRangeValue) return;
  const start = parseInputDate(labor.periodStart?.value || "");
  const end = parseInputDate(labor.periodEnd?.value || "");
  const complete = Boolean(start && end);
  labor.periodRangeValue.textContent = complete
    ? `${formatPeriodDisplayDate(start)} — ${formatPeriodDisplayDate(end)}`
    : "选择开始日期和结束日期";
  labor.periodRange.classList.toggle("is-set", complete);
  labor.periodRange.setAttribute(
    "aria-label",
    complete ? `账期范围，${formatChineseDate(start)}至${formatChineseDate(end)}` : "选择账期范围"
  );
  if (labor.periodCalendar && !labor.periodCalendar.hidden) renderPeriodCalendar();
}

function renderPeriodCalendar() {
  if (!labor.periodCalendarGrid || !labor.periodCalendarTitle) return;
  const base = periodPickerState.cursorMonth || new Date();
  const monthStart = new Date(base.getFullYear(), base.getMonth(), 1);
  const leadingDays = (monthStart.getDay() + 6) % 7;
  const gridStart = addDays(monthStart, -leadingDays);
  const start = parseInputDate(labor.periodStart?.value || "");
  const end = parseInputDate(labor.periodEnd?.value || "");
  const todayValue = formatInputDate(new Date());
  labor.periodCalendarTitle.textContent = `${monthStart.getFullYear()}年${monthStart.getMonth() + 1}月`;

  labor.periodCalendarGrid.innerHTML = Array.from({ length: 42 }, (_, index) => {
    const date = addDays(gridStart, index);
    const value = formatInputDate(date);
    const outsideMonth = date.getMonth() !== monthStart.getMonth();
    const rangeStart = Boolean(start && value === formatInputDate(start));
    const rangeEnd = Boolean(end && value === formatInputDate(end));
    const inRange = Boolean(start && end && date >= start && date <= end);
    const classes = [
      "period-day",
      outsideMonth ? "outside-month" : "",
      inRange ? "in-range" : "",
      rangeStart ? "range-start" : "",
      rangeEnd ? "range-end" : "",
      value === todayValue ? "is-today" : "",
    ].filter(Boolean).join(" ");
    const selectionText = rangeStart ? "，开始日期" : rangeEnd ? "，结束日期" : inRange ? "，账期内" : "";
    const tabbable = rangeStart || (!start && value === todayValue) || (!start && index === leadingDays);
    return `<button class="${classes}" type="button" role="gridcell" data-period-date="${value}" aria-label="${formatChineseDate(date)}${selectionText}" aria-selected="${inRange}" tabindex="${tabbable ? "0" : "-1"}"><span>${date.getDate()}</span></button>`;
  }).join("");

  if (labor.periodCalendarHint) {
    labor.periodCalendarHint.textContent = periodPickerState.selectingEnd
      ? "已按 7 天选好，可点任意日期修改结束日"
      : start && end
        ? "点击新的开始日期，自动重新选中 7 天"
        : "选择开始日期，系统自动选中 7 天";
  }
}

function addDays(date, days) {
  const next = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  next.setDate(next.getDate() + days);
  return next;
}

function parseInputDate(value) {
  if (!value) return null;
  const [year, month, day] = value.split("-").map(Number);
  if (!year || !month || !day) return null;
  return new Date(year, month - 1, day);
}

function formatInputDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function formatPeriodDisplayDate(date) {
  return `${date.getFullYear()}/${String(date.getMonth() + 1).padStart(2, "0")}/${String(date.getDate()).padStart(2, "0")}`;
}

function formatChineseDate(date) {
  return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日`;
}

function beginButtonLoading(button, label = "处理中") {
  if (!button) return;
  const existing = buttonLoadingState.get(button);
  if (existing) {
    existing.label.textContent = label;
    button.setAttribute("aria-label", label || "正在处理");
    return;
  }

  const bounds = button.getBoundingClientRect();
  const original = document.createElement("span");
  original.className = "button-loading-original";
  while (button.firstChild) original.appendChild(button.firstChild);

  const indicator = document.createElement("span");
  indicator.className = "button-loading-indicator";
  indicator.setAttribute("aria-hidden", "true");
  const spinner = document.createElement("span");
  spinner.className = "button-loading-spinner";
  const loadingLabel = document.createElement("span");
  loadingLabel.className = "button-loading-label";
  loadingLabel.textContent = label;
  indicator.append(spinner, loadingLabel);
  button.append(original, indicator);

  buttonLoadingState.set(button, {
    original,
    indicator,
    label: loadingLabel,
    wasDisabled: button.disabled,
    inlineMinWidth: button.style.minWidth,
    ariaLabel: button.getAttribute("aria-label"),
  });
  if (bounds.width > 0) button.style.minWidth = `${Math.ceil(bounds.width)}px`;
  button.classList.add("is-loading");
  button.setAttribute("aria-busy", "true");
  button.setAttribute("aria-label", label || "正在处理");
  button.disabled = true;
}

function endButtonLoading(button, { disabled } = {}) {
  if (!button) return;
  const state = buttonLoadingState.get(button);
  if (!state) {
    if (typeof disabled === "boolean") button.disabled = disabled;
    return;
  }

  while (state.original.firstChild) button.insertBefore(state.original.firstChild, state.original);
  state.original.remove();
  state.indicator.remove();
  button.classList.remove("is-loading");
  button.removeAttribute("aria-busy");
  button.style.minWidth = state.inlineMinWidth;
  if (state.ariaLabel === null) button.removeAttribute("aria-label");
  else button.setAttribute("aria-label", state.ariaLabel);
  button.disabled = typeof disabled === "boolean" ? disabled : state.wasDisabled;
  buttonLoadingState.delete(button);
}

async function withButtonLoading(button, label, task) {
  beginButtonLoading(button, label);
  try {
    return await task();
  } finally {
    endButtonLoading(button);
  }
}

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
  if (labor.btnOpenDrawer) labor.btnOpenDrawer.addEventListener("click", beginNewLaborBatch);
  labor.createLaborRun.addEventListener("click", createRun);
  labor.pdfFiles.addEventListener("change", handlePdfFilesSelected);
  labor.workbookFile.addEventListener("change", handleWorkbookFilesSelected);
  if (labor.clearLaborFiles) labor.clearLaborFiles.addEventListener("click", clearSelectedLaborFiles);
  labor.uploadLaborFiles.addEventListener("click", uploadFiles);
  labor.loadSheets.addEventListener("click", loadSheets);
  labor.sheetSelect.addEventListener("change", loadFieldSuggestions);
  labor.amountColumn.addEventListener("change", () => renderAmountComponentOptions());
  labor.saveMapping.addEventListener("click", saveMapping);
  labor.extractCompare.addEventListener("click", extractAndCompare);
  if (labor.loadMaterialBatches) labor.loadMaterialBatches.addEventListener("click", loadMaterialBatches);
  if (labor.runMaterialDryRun) labor.runMaterialDryRun.addEventListener("click", runMaterialDryRun);
  if (labor.materialReplayBody) labor.materialReplayBody.addEventListener("click", handleMaterialReplayAction);
  if (labor.btnOpenGovernance) {
    labor.btnOpenGovernance.addEventListener("click", () => withButtonLoading(labor.btnOpenGovernance, "", openLaborGovernance));
  }
  if (labor.btnWorkerStatus) {
    labor.btnWorkerStatus.addEventListener("click", openLaborWorkerPanel);
  }
  if (labor.activateWorker) labor.activateWorker.addEventListener("click", activateLaborWorker);
  if (labor.refreshWorker) {
    labor.refreshWorker.addEventListener("click", () => withButtonLoading(labor.refreshWorker, "正在刷新", loadLaborWorkerDevices));
  }
  if (labor.workerDevices) labor.workerDevices.addEventListener("click", handleLaborWorkerDeviceAction);
  if (labor.downloadWorker) {
    labor.downloadWorker.addEventListener("click", (event) => {
      if (labor.downloadWorker.classList.contains("disabled")) {
        event.preventDefault();
        return;
      }
      recordLaborTelemetry("labor.worker.download_clicked", {
        step: "worker_download",
        status: "clicked",
        context: { version: laborState.workerRelease?.version || "" },
      });
    });
  }
  if (labor.workerReleasePlatform) {
    labor.workerReleasePlatform.addEventListener("change", syncLaborWorkerReleaseUploadControls);
    syncLaborWorkerReleaseUploadControls();
  }
  if (labor.uploadWorkerRelease) labor.uploadWorkerRelease.addEventListener("click", uploadLaborWorkerRelease);
  if (labor.closeGovernance) labor.closeGovernance.addEventListener("click", () => labor.governanceDialog?.close());
  if (labor.deleteCurrentRun) labor.deleteCurrentRun.addEventListener("click", deleteCurrentLaborRun);
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

async function openLaborGovernance() {
  if (!labor.governanceDialog) return;
  labor.governanceDialog.showModal();
  labor.deleteCurrentRun.disabled = !laborState.run?.id;
  const runId = laborState.run?.id || "";
  labor.storageSummary.innerHTML = '<span class="audit-empty">正在读取...</span>';
  labor.auditList.innerHTML = `<li class="audit-empty">${runId ? "正在读取..." : "当前尚未选择批次。"}</li>`;
  if (laborState.moduleAccess?.p1?.required === true) await loadLaborWorkerDevices();
  try {
    const storage = await requestJson("/api/labor/storage-info");
    renderLaborStorageSummary(storage);
  } catch (error) {
    labor.storageSummary.innerHTML = `<span class="audit-empty">${escapeHtml(error.message)}</span>`;
  }
  if (!runId) return;
  try {
    const audit = await requestJson(`/api/labor/audit?run_id=${encodeURIComponent(runId)}&limit=20`);
    renderLaborAuditEvents(audit.events || []);
  } catch (error) {
    labor.auditList.innerHTML = `<li class="audit-empty">${escapeHtml(error.message)}</li>`;
  }
}

function openLaborWorkerPanel() {
  void openLaborGovernance();
  labor.workerSection?.scrollIntoView({ block: "start", behavior: "smooth" });
}

function workerDeviceIsOnline(device) {
  if (!device?.lastSeenAt || device?.revokedAt) return false;
  const seenAt = Date.parse(device.lastSeenAt);
  return Number.isFinite(seenAt) && Date.now() - seenAt < 6 * 1000;
}

function laborWorkerEnvironmentLabel() {
  return window.location.hostname === "sigma-workbench.vercel.app" ? "生产环境" : "UAT 环境";
}

function laborWorkerOfflineMessage() {
  return laborWorkerEnvironmentLabel() === "生产环境"
    ? "核对助手尚未连接当前生产环境，请先激活或重新连接。"
    : "核对助手尚未连接当前 UAT 环境，请先激活或重新连接。";
}

function updateLaborWorkerHeader(devices) {
  const active = devices.filter((device) => !device.revokedAt);
  const online = active.some(workerDeviceIsOnline);
  const environment = laborWorkerEnvironmentLabel();
  if (labor.btnWorkerStatus) {
    labor.btnWorkerStatus.hidden = laborState.moduleAccess?.p1?.required !== true;
    labor.btnWorkerStatus.classList.toggle("online", online);
  }
  if (labor.workerStatusLabel) {
    labor.workerStatusLabel.textContent = online
      ? `核对助手在线 · ${environment}`
      : active.length
        ? `核对助手待连接 · ${environment}`
        : `核对助手未激活 · ${environment}`;
  }
}

async function loadLaborWorkerDevices() {
  if (laborState.moduleAccess?.p1?.required !== true) return;
  if (labor.workerSection) labor.workerSection.hidden = false;
  if (labor.workerDevices) labor.workerDevices.innerHTML = '<span class="audit-empty">正在读取...</span>';
  try {
    const data = await requestJson("/api/labor/worker/devices");
    laborState.workerDevices = Array.isArray(data.devices) ? data.devices : [];
    renderLaborWorkerDevices();
    renderLaborWorkerRelease();
    if (labor.workerMessage) {
      labor.workerMessage.textContent = `当前页面是${laborWorkerEnvironmentLabel()}；重新激活会将桌面核对助手切换到当前环境。`;
    }
    return laborState.workerDevices;
  } catch (error) {
    if (labor.workerDevices) labor.workerDevices.innerHTML = `<span class="audit-empty">${escapeHtml(error.message)}</span>`;
    if (labor.workerMessage) labor.workerMessage.textContent = "核对助手身份服务尚未就绪，当前不能开始私有材料处理。";
    updateLaborWorkerHeader([]);
    return [];
  }
}

async function loadLaborWorkerRelease() {
  if (!labor.downloadWorker || !labor.workerReleaseStatus) return;
  try {
    laborState.workerRelease = await requestJson(`/api/labor/worker/release?platform=${encodeURIComponent(laborState.workerPlatform)}`);
    renderLaborWorkerRelease();
  } catch (error) {
    laborState.workerRelease = null;
    labor.downloadWorker.classList.add("disabled");
    labor.downloadWorker.setAttribute("aria-disabled", "true");
    labor.downloadWorker.href = "#";
    labor.workerReleaseStatus.textContent = "安装包暂不可用";
  }
}

function compareStableVersions(left, right) {
  const parse = (value) => String(value || "").split(".").map((part) => Number(part));
  const a = parse(left);
  const b = parse(right);
  for (let index = 0; index < 3; index += 1) {
    if ((a[index] || 0) !== (b[index] || 0)) return (a[index] || 0) - (b[index] || 0);
  }
  return 0;
}

function renderLaborWorkerRelease() {
  const release = laborState.workerRelease;
  if (!release || !labor.downloadWorker || !labor.workerReleaseStatus) return;
  if (labor.workerReleaseAdmin) labor.workerReleaseAdmin.hidden = release.canUpload !== true;
  const version = String(release.version || "");
  const downloadUrl = String(release.downloadUrl || "");
  const platformLabel = laborWorkerPlatformLabel(release.platform || laborState.workerPlatform);
  if (release.available !== true || !version || !downloadUrl) {
    labor.downloadWorker.classList.add("disabled");
    labor.downloadWorker.setAttribute("aria-disabled", "true");
    labor.downloadWorker.href = "#";
    labor.workerReleaseStatus.textContent = `${platformLabel} 版待发布`;
    return;
  }
  labor.downloadWorker.href = downloadUrl;
  labor.downloadWorker.classList.remove("disabled");
  labor.downloadWorker.removeAttribute("aria-disabled");
  const installedVersions = laborState.workerDevices
    .filter((device) => !device.revokedAt && device.workerVersion)
    .map((device) => String(device.workerVersion));
  const updateAvailable = installedVersions.some((installed) => compareStableVersions(version, installed) > 0);
  labor.workerReleaseStatus.textContent = updateAvailable
    ? `${platformLabel} 有新版本 ${version}，请下载更新`
    : installedVersions.length
      ? `${platformLabel} 已是最新版本 ${version}`
      : `${platformLabel} 最新版本 ${version}`;
}

function syncLaborWorkerReleaseUploadControls() {
  const releasePlatform = labor.workerReleasePlatform?.value || "macos-arm64";
  const isWindows = releasePlatform === "windows-x64";
  if (labor.workerReleasePackage) {
    labor.workerReleasePackage.value = "";
    labor.workerReleasePackage.accept = isWindows
      ? ".exe,application/x-msdownload,application/vnd.microsoft.portable-executable"
      : ".dmg,application/x-apple-diskimage";
  }
  setText(
    labor.workerReleaseUploadStatus,
    `选择对应版本 ${isWindows ? "EXE" : "DMG"} 后上传到当前环境私有存储。`,
  );
}

async function uploadLaborWorkerRelease() {
  const file = labor.workerReleasePackage?.files?.[0];
  const requiredVersion = String(laborState.workerRelease?.requiredWorkerVersion || "");
  const releasePlatform = labor.workerReleasePlatform?.value || laborState.workerPlatform;
  const expectedFilename = releasePlatform === "windows-x64"
    ? `Σ海外报账核对助手-${requiredVersion}-windows-x64.exe`
    : `Σ海外报账核对助手-${requiredVersion}-arm64.dmg`;
  if (!file) return toast(`请先选择核对助手 ${releasePlatform === "windows-x64" ? "EXE" : "DMG"} 安装包。`);
  if (!requiredVersion || file.name !== expectedFilename) {
    const message = `请选择当前要求版本安装包：${expectedFilename}`;
    setText(labor.workerReleaseUploadStatus, message, true);
    return toast(message);
  }
  beginButtonLoading(labor.uploadWorkerRelease, "正在校验");
  try {
    const sha256 = await sha256File(file);
    const intent = await requestJson("/api/labor/worker/release/upload-intent", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        platform: releasePlatform,
        version: requiredVersion,
        filename: file.name,
        sizeBytes: file.size,
        sha256,
      }),
    });
    beginButtonLoading(labor.uploadWorkerRelease, "正在上传");
    const uploaded = await fetch(intent.signedUrl, {
      method: "PUT",
      headers: intent.headers || {
        "content-type": releasePlatform === "windows-x64" ? "application/x-msdownload" : "application/x-apple-diskimage",
      },
      body: file,
    });
    if (!uploaded.ok) throw new Error(`私有存储未接收安装包（HTTP ${uploaded.status}）。`);
    const platformLabel = laborWorkerPlatformLabel(releasePlatform);
    setText(labor.workerReleaseUploadStatus, `${platformLabel} ${requiredVersion} 已上传到当前环境私有存储；更新清单生效后用户会收到提示。`);
    toast(`${platformLabel} 核对助手 ${requiredVersion} 安装包上传完成。`);
  } catch (error) {
    setText(labor.workerReleaseUploadStatus, error.message, true);
    toast(error.message);
  } finally {
    endButtonLoading(labor.uploadWorkerRelease);
  }
}

function renderLaborWorkerDevices() {
  const active = laborState.workerDevices.filter((device) => !device.revokedAt);
  updateLaborWorkerHeader(laborState.workerDevices);
  if (!labor.workerDevices) return;
  if (!active.length) {
    labor.workerDevices.innerHTML = '<span class="audit-empty">尚未激活。点击下方按钮后，浏览器会请求打开“Σ海外报账核对助手”。</span>';
    return;
  }
  labor.workerDevices.innerHTML = active.map((device) => {
    const online = workerDeviceIsOnline(device);
    const seen = device.lastSeenAt ? String(device.lastSeenAt).replace("T", " ").slice(0, 19) : "尚未连接";
    return `<div class="worker-device-item"><div><strong>${escapeHtml(device.displayName || "个人核对助手")} · ${online ? "在线" : "待连接"}</strong><span>版本 ${escapeHtml(device.workerVersion || "待上报")} · 最近连接 ${escapeHtml(seen)}</span></div><button type="button" data-worker-revoke="${escapeHtml(device.id)}">撤销</button></div>`;
  }).join("");
}

async function activateLaborWorker() {
  if (!labor.activateWorker) return;
  beginButtonLoading(labor.activateWorker, "正在连接");
  try {
    const active = laborState.workerDevices.find((device) => !device.revokedAt);
    const endpoint = active
      ? `/api/labor/worker/devices/${encodeURIComponent(active.id)}/rotate`
      : "/api/labor/worker/devices";
    const issued = await requestJson(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        displayName: "Σ海外报账核对助手",
        platform: navigator.userAgentData?.platform || navigator.platform || "macos-arm64",
      }),
    });
    const activationUrl = String(issued.activationUrl || "");
    if (!activationUrl.startsWith("sigma-overseas-labor-worker://activate?")) {
      throw new Error("服务端未返回安全的核对助手激活地址。");
    }
    if (labor.workerMessage) labor.workerMessage.textContent = `激活请求有效至 ${String(issued.expiresAt || "").replace("T", " ").slice(0, 19)}。请在系统提示中允许打开核对助手。`;
    const link = document.createElement("a");
    link.href = activationUrl;
    link.hidden = true;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(loadLaborWorkerDevices, 1800);
  } catch (error) {
    if (labor.workerMessage) labor.workerMessage.textContent = error.message;
    toast(error.message);
  } finally {
    endButtonLoading(labor.activateWorker);
  }
}

async function handleLaborWorkerDeviceAction(event) {
  const button = event.target.closest("[data-worker-revoke]");
  if (!button) return;
  const deviceId = button.dataset.workerRevoke || "";
  if (!deviceId || !window.confirm("确认撤销这台核对助手？撤销后它将立即失去任务访问权限。")) return;
  beginButtonLoading(button, "正在撤销");
  try {
    await requestJson(`/api/labor/worker/devices/${encodeURIComponent(deviceId)}`, { method: "DELETE" });
    await loadLaborWorkerDevices();
  } catch (error) {
    toast(error.message);
  } finally {
    endButtonLoading(button);
  }
}

function renderLaborStorageSummary(storage) {
  const retention = storage?.retention || {};
  const backendLabels = { local: "当前电脑", blob: "云端对象存储", supabase: "云端持久化存储" };
  const backend = backendLabels[storage?.storageBackend] || storage?.storageBackend || "未配置";
  const persistent = storage?.persistentStorageEnabled ? "已启用" : "未启用";
  labor.storageSummary.innerHTML = [
    ["存储位置", backend],
    ["运行环境", storage?.storageEnvironment || "本地"],
    ["持久化", persistent],
    ["批次保留", `${Number(retention.runDays || 0)} 天`],
    ["OCR 缓存保留", `${Number(retention.ocrCacheDays || 0)} 天`],
  ].map(([label, value]) => `<div class="storage-item"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join("");
}

function renderLaborAuditEvents(events) {
  const actionLabels = {
    run_created: "创建批次",
    files_uploaded: "上传材料",
    extraction_started: "开始核对",
    extraction_completed: "完成核对",
    extraction_failed: "核对失败",
    report_downloaded: "下载报告",
    resource_limit_rejected: "资源限制拦截",
    run_deleted: "删除批次",
  };
  if (!events.length) {
    labor.auditList.innerHTML = '<li class="audit-empty">当前批次暂无审计记录。</li>';
    return;
  }
  labor.auditList.innerHTML = events.map((event) => {
    const timestamp = String(event.timestamp || event.createdAt || "").replace("T", " ").slice(0, 19);
    const action = actionLabels[event.action] || event.action || "系统操作";
    const outcome = event.outcome === "failed" || event.outcome === "rejected" ? "异常" : "完成";
    return `<li><span>${escapeHtml(timestamp || "—")}</span><strong>${escapeHtml(action)}</strong><span>${escapeHtml(outcome)}</span></li>`;
  }).join("");
}

async function deleteCurrentLaborRun() {
  const runId = laborState.run?.id;
  if (!runId) return;
  if (!window.confirm(`确认删除批次 ${runId}？该批次的 PDF、Excel、报告和识别结果将一并删除，且无法恢复。`)) return;
  beginButtonLoading(labor.deleteCurrentRun, "正在删除");
  try {
    await requestJson(`/api/labor/runs/${encodeURIComponent(runId)}`, { method: "DELETE" });
    laborState.run = null;
    labor.chromeRunBadge.hidden = true;
    labor.reportLink.href = "#";
    labor.reportLink.classList.add("disabled");
    labor.reportLink.setAttribute("aria-disabled", "true");
    labor.governanceDialog.close();
    toast("当前批次已删除。");
  } catch (error) {
    toast(error.message);
  } finally {
    endButtonLoading(labor.deleteCurrentRun, { disabled: !laborState.run?.id });
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
    renderLaborUploadLimits(access);
    if (labor.workerSection) labor.workerSection.hidden = access.p1?.required !== true;
    if (labor.btnWorkerStatus) labor.btnWorkerStatus.hidden = access.p1?.required !== true;
    if (access.p1?.required === true) loadLaborWorkerDevices();
    const compatibility = laborReleaseCompatibility(access);
    laborState.releaseCompatible = access.canUse !== false && compatibility.compatible;
    if (labor.moduleStageBadge) {
      labor.moduleStageBadge.textContent = `${access.stage || "UAT试用版"} · ${access.message || "结果需业务确认"}`;
      labor.moduleStageBadge.classList.toggle("blocked", access.canUse === false || !compatibility.compatible);
    }
    if (labor.moduleReleaseMeta) {
      labor.moduleReleaseMeta.textContent = compatibility.message;
      labor.moduleReleaseMeta.classList.toggle("blocked", !compatibility.compatible);
    }
    setLaborActionAvailability(laborState.releaseCompatible);
    if (!compatibility.compatible) {
      toast(compatibility.message);
      return;
    }
    if (access.canUse === false) {
      toast(access.message || "当前账号无权使用海外劳务报账核对。");
    }
  } catch (error) {
    if (labor.moduleStageBadge) {
      labor.moduleStageBadge.textContent = "UAT试用版 · 权限状态读取失败";
      labor.moduleStageBadge.classList.add("blocked");
    }
    if (labor.moduleReleaseMeta) {
      labor.moduleReleaseMeta.textContent = "服务版本读取失败，正式操作已锁定。";
      labor.moduleReleaseMeta.classList.add("blocked");
    }
    laborState.moduleAccess = null;
    laborState.releaseCompatible = false;
    setLaborActionAvailability(false);
  }
}

function configuredWorkbookFileLimit() {
  return Math.max(1, Number(laborState.moduleAccess?.uploadLimits?.maxWorkbookFiles || 10));
}

function workbookUploadHint(count = 0) {
  const maxWorkbookFiles = configuredWorkbookFileLimit();
  return count > 0
    ? `${count} 个 Excel 文件已选择 · 最多 ${maxWorkbookFiles} 个`
    : `点击选择 · 支持多选 · 最多 ${maxWorkbookFiles} 个 · .xlsx / .xlsm / .xls`;
}

function laborFileKey(file) {
  return [file?.name || "", Number(file?.size || 0), Number(file?.lastModified || 0)].join("::");
}

function mergeSelectedLaborFiles(existing, additions) {
  const merged = [];
  const seen = new Set();
  [...existing, ...Array.from(additions || [])].forEach((file) => {
    const key = laborFileKey(file);
    if (!key || seen.has(key)) return;
    seen.add(key);
    merged.push(file);
  });
  return merged;
}

function uploadedLaborFileCounts() {
  const files = laborState.run?.files || {};
  return {
    pdf: Array.isArray(files.pdfInvoices) ? files.pdfInvoices.length : 0,
    workbook: Array.isArray(files.workbooks) ? files.workbooks.length : 0,
  };
}

function renderSelectedLaborFiles() {
  const uploaded = uploadedLaborFileCounts();
  const pdfCount = laborState.selectedPdfFiles.length;
  const workbookCount = laborState.selectedWorkbookFiles.length;
  if (labor.pdfFileName) {
    labor.pdfFileName.textContent = pdfCount
      ? `${pdfCount} 个 PDF 待上传${uploaded.pdf ? ` · 已上传 ${uploaded.pdf} 个` : ""}`
      : uploaded.pdf
        ? `已上传 ${uploaded.pdf} 个 · 可继续选择补充文件`
        : "点击选择 · 支持分次累加";
  }
  if (labor.workbookFileName) {
    labor.workbookFileName.textContent = workbookCount
      ? `${workbookCount} 个 Excel 待上传 · 最多 ${configuredWorkbookFileLimit()} 个${uploaded.workbook ? ` · 已上传 ${uploaded.workbook} 个` : ""}`
      : uploaded.workbook
        ? `已上传 ${uploaded.workbook} 个 · 可继续选择补充文件`
        : workbookUploadHint(0);
  }
  document.querySelector("#pdfUploadZone")?.classList.toggle("has-file", pdfCount + uploaded.pdf > 0);
  document.querySelector("#xlsxUploadZone")?.classList.toggle("has-file", workbookCount + uploaded.workbook > 0);
}

function handlePdfFilesSelected() {
  laborState.selectedPdfFiles = mergeSelectedLaborFiles(laborState.selectedPdfFiles, labor.pdfFiles.files);
  labor.pdfFiles.value = "";
  renderSelectedLaborFiles();
}

function handleWorkbookFilesSelected() {
  const maxWorkbookFiles = configuredWorkbookFileLimit();
  const uploaded = uploadedLaborFileCounts().workbook;
  const merged = mergeSelectedLaborFiles(laborState.selectedWorkbookFiles, labor.workbookFile.files);
  const available = Math.max(0, maxWorkbookFiles - uploaded);
  laborState.selectedWorkbookFiles = merged.slice(0, available);
  labor.workbookFile.value = "";
  renderSelectedLaborFiles();
  if (merged.length > available) {
    toast(`每个批次最多上传 ${maxWorkbookFiles} 个 Excel 文件，超出部分未加入。`);
  }
}

function clearSelectedLaborFiles() {
  laborState.selectedPdfFiles = [];
  laborState.selectedWorkbookFiles = [];
  labor.pdfFiles.value = "";
  labor.workbookFile.value = "";
  renderSelectedLaborFiles();
  setText(labor.uploadStatus, "已清空本轮待上传文件；已上传到当前批次的文件不会被删除。");
}

function renderLaborUploadLimits(access) {
  const maxWorkbookFiles = Math.max(1, Number(access.uploadLimits?.maxWorkbookFiles || 10));
  if (!labor.workbookFileName) return;
  const count = laborState.selectedWorkbookFiles.length;
  labor.workbookFileName.textContent = count > 0
    ? `${count} 个 Excel 文件已选择 · 最多 ${maxWorkbookFiles} 个`
    : `点击选择 · 支持多选 · 最多 ${maxWorkbookFiles} 个 · .xlsx / .xlsm / .xls`;
}

function showLaborToolbench() {
  if (labor.toolbench) labor.toolbench.hidden = false;
  if (labor.resultsView) labor.resultsView.hidden = true;
  document.body.style.overflow = "";
  window.requestAnimationFrame(() => window.scrollTo({ top: 0, behavior: "smooth" }));
}

function showLaborResultsView() {
  if (labor.toolbench) labor.toolbench.hidden = true;
  if (labor.resultsView) labor.resultsView.hidden = false;
  document.body.style.overflow = "";
  window.requestAnimationFrame(() => window.scrollTo({ top: 0, behavior: "smooth" }));
}

async function restoreLaborRunFromUrl() {
  const restoreGeneration = ++laborRunRestoreGeneration;
  const runId = new URLSearchParams(window.location.search).get("run");
  if (!runId || !laborState.releaseCompatible) {
    showLaborToolbench();
    return;
  }
  if (!/^[0-9A-Za-z_-]+$/.test(runId)) {
    toast("批次编号格式无效，未恢复历史批次。");
    return;
  }
  try {
    const run = await requestJson(`/api/labor/runs/${encodeURIComponent(runId)}`);
    if (
      restoreGeneration !== laborRunRestoreGeneration
      || new URLSearchParams(window.location.search).get("run") !== runId
    ) return;
    laborState.run = run;
    if (labor.chromeRunBadge) {
      labor.chromeRunBadge.hidden = false;
      labor.chromeRunLabel.textContent = `批次 #${run.id.slice(0, 8)}`;
    }
    if (labor.supplierName) labor.supplierName.value = run.supplierName || "";
    if (labor.periodStart) labor.periodStart.value = run.periodStart || "";
    if (labor.periodEnd) labor.periodEnd.value = run.periodEnd || "";
    syncPeriodRangePicker();
    if (labor.currency) labor.currency.value = run.currency || "";

    const files = run.files && typeof run.files === "object" ? run.files : {};
    const hasUploadedFiles = Array.isArray(files.pdfInvoices) && files.pdfInvoices.length > 0
      && Array.isArray(files.workbooks) && files.workbooks.length > 0;
    const restoredOutput = restoreLaborRunOutput(run);
    if (restoredOutput) {
      showLaborResultsView();
      advanceWizardStep("3");
      toast(restoredOutput === "completed" ? `已恢复批次 ${run.id} 的核对结果。` : `已恢复批次 ${run.id} 的处理进度。`);
      return;
    }
    advanceWizardStep(hasUploadedFiles ? "3" : "2");
    showLaborToolbench();
    if (labor.uploadStatus && hasUploadedFiles) {
      setText(labor.uploadStatus, "已恢复批次，文件仍保存在当前环境私有存储中。");
    }
    toast(`已恢复批次 ${run.id}。`);
    if (hasUploadedFiles && run.mappingPreflight?.status === "completed") {
      await loadSheets();
    }
  } catch (error) {
    if (
      restoreGeneration !== laborRunRestoreGeneration
      || new URLSearchParams(window.location.search).get("run") !== runId
    ) return;
    toast(`恢复批次失败：${error.message}`);
  }
}

function laborRunHasSettledResult(run) {
  const reportUrl = preferredLaborReportDownloadUrl(run);
  const hasCompletedResult = run.status === "已生成差异报告" || Boolean(run.diffDownloadUrl) || Boolean(reportUrl);
  if (!hasCompletedResult) return false;
  const taskStatus = String(run?.asyncTask?.status || "").trim().toLowerCase();
  return !taskStatus || taskStatus === "completed" || taskStatus === "succeeded";
}

function restoreLaborRunOutput(run) {
  const taskStatus = String(run?.asyncTask?.status || "");
  const hasCompletedResult = laborRunHasSettledResult(run);
  if (hasCompletedResult) {
    stopComparePolling();
    endButtonLoading(labor.extractCompare, { disabled: false });
    renderResult(run);
    setDownload(preferredLaborReportDownloadUrl(run));
    setText(labor.compareStatus, "完成：核对报告已生成。识别不完整的明细已进入待确认清单。");
    return "completed";
  }
  const isProcessing = run.status === "抽取中"
    || ["queued", "waiting_for_personal_worker", "running", "retry_wait"].includes(taskStatus);
  if (!isProcessing) return "";
  stopComparePolling();
  laborState.pollRetryCount = 0;
  laborState.extractStartedAt = null;
  beginButtonLoading(labor.extractCompare, "正在生成");
  renderLaborProgress(run);
  setText(labor.compareStatus, formatLaborTaskStatus(run, "处理中：正在恢复后台核对进度。"));
  laborState.comparePollTimer = window.setInterval(pollCompareResult, 3000);
  return "processing";
}

function laborReleaseCompatibility(access) {
  const backendVersion = String(access?.version || "未提供");
  const backendContractVersion = Number(access?.apiContractVersion);
  const contractCompatible = backendVersion === LABOR_UI_MODULE_VERSION
    && backendContractVersion === LABOR_UI_API_CONTRACT_VERSION;
  const runtimeCurrent = access?.runtimeGate?.runtimeSourceCurrent === true;
  const buildId = String(access?.build?.buildId || access?.buildId || "unknown").slice(0, 16);
  const buildSchemaValid = access?.build?.schemaVersion === 1
    && access?.build?.status === "current"
    && String(access?.build?.buildId || "").trim().length > 0
    && access?.build?.moduleVersion === LABOR_UI_MODULE_VERSION
    && Number(access?.build?.apiContractVersion) === LABOR_UI_API_CONTRACT_VERSION;
  if (!contractCompatible) {
    return {
      compatible: false,
      message: `前后端版本不一致：界面 ${LABOR_UI_MODULE_VERSION}/API v${LABOR_UI_API_CONTRACT_VERSION}，服务 ${backendVersion}/API v${Number.isFinite(backendContractVersion) ? backendContractVersion : "未提供"}。请重启或重新部署服务。`,
    };
  }
  if (!runtimeCurrent) {
    return {
      compatible: false,
      message: access?.runtimeGate?.message || "服务版本无法确认，正式操作已锁定。",
    };
  }
  if (!buildSchemaValid) {
    return {
      compatible: false,
      message: "服务 build 信息缺失或不完整，正式操作已锁定。请重启或重新部署服务。",
    };
  }
  return {
    compatible: true,
    message: `界面 ${LABOR_UI_MODULE_VERSION} · API v${LABOR_UI_API_CONTRACT_VERSION} · build ${buildId}`,
  };
}

function setLaborActionAvailability(enabled) {
  [
    labor.btnOpenDrawer,
    labor.createLaborRun,
    labor.uploadLaborFiles,
    labor.loadSheets,
    labor.saveMapping,
    labor.extractCompare,
    labor.runMaterialDryRun,
  ].forEach((button) => {
    if (button) button.disabled = !enabled;
  });
}

function isFormalLaborTaskBlocked() {
  return laborState.moduleAccess?.formalTaskGate?.canQueue !== true;
}

function showFormalLaborTaskBlocked() {
  const message = laborState.moduleAccess?.formalTaskGate?.message
    || "当前环境暂未开放正式核对任务。";
  setText(labor.compareStatus, message, true);
  toast(message);
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

function setLaborRunQuery(runId) {
  const url = new URL(window.location.href);
  if (runId) url.searchParams.set("run", runId);
  else url.searchParams.delete("run");
  window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
}

function beginNewLaborBatch() {
  laborRunRestoreGeneration += 1;
  stopComparePolling();
  endButtonLoading(labor.extractCompare, { disabled: false });
  laborState.run = null;
  laborState.headers = [];
  laborState.amountColumnCandidates = [];
  laborState.pollRetryCount = 0;
  laborState.extractStartedAt = null;
  laborState.currentStep = 1;
  laborState.selectedPdfFiles = [];
  laborState.selectedWorkbookFiles = [];
  [labor.supplierName, labor.periodStart, labor.periodEnd, labor.currency].forEach((input) => {
    if (input) input.value = "";
  });
  syncPeriodRangePicker();
  labor.pdfFiles.value = "";
  labor.workbookFile.value = "";
  renderSelectedLaborFiles();
  labor.sheetSelect.innerHTML = "";
  if (labor.mappingPreview) labor.mappingPreview.innerHTML = '<p class="empty-state-text">读取工作表后显示字段样例。</p>';
  if (labor.amountComponentColumns) {
    labor.amountComponentColumns.hidden = true;
    const list = labor.amountComponentColumns.querySelector("[data-amount-component-list]");
    if (list) list.innerHTML = "";
  }
  setText(labor.createStatus, "填写批次信息后创建。");
  setText(labor.uploadStatus, "创建批次后可上传文件。");
  if (labor.chromeRunBadge) labor.chromeRunBadge.hidden = true;
  if (labor.chromeRunLabel) labor.chromeRunLabel.textContent = "";
  setLaborRunQuery("");
  clearResults();
  advanceWizardStep("1");
  showLaborToolbench();
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
    openPeriodRangePicker();
    return;
  }
  if (periodEnd < periodStart) {
    setText(labor.createStatus, "账期结束日期不能早于开始日期。", true);
    openPeriodRangePicker();
    return;
  }
  if (!currency) {
    setText(labor.createStatus, "请先填写结算币种。", true);
    labor.currency.focus();
    return;
  }

  setText(labor.createStatus, "正在创建批次...");
  beginButtonLoading(labor.createLaborRun, "正在创建");
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
        require_employee_detail: true,
      }),
    });
    laborState.run = run;
    setLaborRunQuery(run.id);
    clearResults();
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
    endButtonLoading(labor.createLaborRun);
  }
}

async function uploadFiles() {
  if (!laborState.run) return toast("请先创建批次。");
  const existing = uploadedLaborFileCounts();
  const pendingPdfCount = laborState.selectedPdfFiles.length;
  const pendingWorkbookCount = laborState.selectedWorkbookFiles.length;
  if (!pendingPdfCount && !pendingWorkbookCount) return toast("请先选择本轮要上传的文件。");
  if (!(existing.pdf + pendingPdfCount) || !(existing.workbook + pendingWorkbookCount))
    return toast("当前批次需同时包含 PDF 发票和 Excel 账单；可分次补充上传。");
  const maxWorkbookFiles = configuredWorkbookFileLimit();
  if (existing.workbook + pendingWorkbookCount > maxWorkbookFiles) {
    const message = `每个批次最多选择 ${maxWorkbookFiles} 个 Excel 文件。`;
    setText(labor.uploadStatus, message, true);
    return toast(message);
  }

  setText(labor.uploadStatus, "正在上传文件...");
  beginButtonLoading(labor.uploadLaborFiles, "正在上传");
  const startedAt = performance.now();
  const uploadContext = {
    pdfCount: pendingPdfCount,
    workbookCount: pendingWorkbookCount,
    fileCount: pendingPdfCount + pendingWorkbookCount,
  };
  recordLaborTelemetry("labor.upload.started", {
    step: "upload",
    status: "started",
    context: uploadContext,
  });
  try {
    if (usesP1DirectUpload()) {
      laborState.run = await uploadFilesDirectlyToPrivateStorage();
    } else {
      const form = new FormData();
      laborState.selectedPdfFiles.forEach((file) => form.append("pdf_files", file));
      laborState.selectedWorkbookFiles.forEach((file) => form.append("workbook_files", file));
      laborState.run = await requestJson(`/api/labor/runs/${laborState.run.id}/files`, {
        method: "POST",
        body: form,
      });
    }
    laborState.selectedPdfFiles = [];
    laborState.selectedWorkbookFiles = [];
    labor.pdfFiles.value = "";
    labor.workbookFile.value = "";
    renderSelectedLaborFiles();
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
    endButtonLoading(labor.uploadLaborFiles);
  }
}

function usesP1DirectUpload() {
  return laborState.moduleAccess?.p1?.required === true
    && laborState.moduleAccess?.p1?.uploadMode === "signed_private_direct";
}

async function sha256File(file) {
  if (!window.crypto?.subtle || typeof file?.arrayBuffer !== "function") {
    throw new Error("当前浏览器不支持 P1 文件完整性校验，请升级浏览器后重试。");
  }
  const digest = await window.crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, "0")).join("");
}

async function uploadFilesDirectlyToPrivateStorage() {
  const runId = laborState.run.id;
  const selected = [
    ...laborState.selectedPdfFiles.map((file) => ({ file, fileKind: "pdf_invoice" })),
    ...laborState.selectedWorkbookFiles.map((file) => ({ file, fileKind: "workbook" })),
  ];
  const fileSpecs = [];
  for (let index = 0; index < selected.length; index += 1) {
    const item = selected[index];
    setText(labor.uploadStatus, `正在校验文件 ${index + 1}/${selected.length}：${item.file.name}`);
    fileSpecs.push({
      filename: item.file.name,
      fileKind: item.fileKind,
      contentType: item.file.type || "application/octet-stream",
      sizeBytes: item.file.size,
      sha256: await sha256File(item.file),
    });
  }
  const response = await requestJson(`/api/labor/runs/${runId}/upload-intents`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ files: fileSpecs }),
  });
  const intents = Array.isArray(response.intents) ? response.intents : [];
  if (intents.length !== selected.length) {
    throw new Error("服务端返回的私有上传清单不完整，请重新上传本批文件。");
  }
  let completedCount = 0;
  const uploadOne = async (index) => {
    const intent = intents[index];
    const item = selected[index];
    const uploadUrl = new URL(String(intent.signedUrl || ""), window.location.href);
    const secureUrl = uploadUrl.protocol === "https:"
      || (uploadUrl.protocol === "http:" && ["localhost", "127.0.0.1"].includes(uploadUrl.hostname));
    if (!secureUrl || String(intent.method || "").toUpperCase() !== "PUT") {
      throw new Error("服务端返回了不安全的私有上传地址，请联系管理员。");
    }
    setText(
      labor.uploadStatus,
      `正在并发上传文件（已完成 ${completedCount}/${intents.length}）：${item.file.name}`,
    );
    const uploaded = await fetch(intent.signedUrl, {
      method: "PUT",
      headers: intent.headers || { "content-type": item.file.type || "application/octet-stream" },
      body: item.file,
    });
    if (!uploaded.ok) {
      throw new Error(`私有存储未接收文件 ${item.file.name}（HTTP ${uploaded.status}）。`);
    }
    completedCount += 1;
    setText(labor.uploadStatus, `文件直传完成 ${completedCount}/${intents.length}：${item.file.name}`);
  };
  const results = await Promise.allSettled(intents.map((_intent, index) => uploadOne(index)));
  const failed = results.find((result) => result.status === "rejected");
  if (failed) {
    const message = failed.reason instanceof Error ? failed.reason.message : String(failed.reason || "");
    throw new Error(message || "上传文件中有文件失败，请检查网络后重试。");
  }
  setText(labor.uploadStatus, `正在一次确认 ${intents.length} 个文件，请稍候…`);
  await requestJson(`/api/labor/runs/${runId}/upload-intents/batch-finalize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fileIds: intents.map((intent) => intent.fileId) }),
  });
  return requestJson(`/api/labor/runs/${runId}`);
}

async function loadSheets() {
  if (!laborState.run) return toast("请先创建并上传文件。");
  beginButtonLoading(labor.loadSheets, "正在读取");
  try {
    if (usesP1DirectUpload()) {
      const preflight = await ensureP1MappingPreflight();
      const sheets = Array.isArray(preflight?.sheets) ? preflight.sheets : [];
      labor.sheetSelect.innerHTML = sheets
        .map((sheet) => `<option value="${escapeHtml(sheet)}">${escapeHtml(sheet)}</option>`)
        .join("");
      if (sheets.length) await loadFieldSuggestions();
      return;
    }
    const data = await requestJson(`/api/labor/runs/${laborState.run.id}/workbook-sheets`);
    labor.sheetSelect.innerHTML = data.sheets
      .map((sheet) => `<option value="${escapeHtml(sheet)}">${escapeHtml(sheet)}</option>`)
      .join("");
    if (data.sheets.length) await loadFieldSuggestions();
  } catch (error) {
    toast(error.message);
  } finally {
    endButtonLoading(labor.loadSheets);
  }
}

async function ensureP1MappingPreflight() {
  await loadLaborWorkerDevices();
  if (!laborState.workerDevices.some(workerDeviceIsOnline)) {
    throw new Error(laborWorkerOfflineMessage());
  }
  const response = await requestJson(`/api/labor/runs/${laborState.run.id}/mapping-preflight`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  const submittedPreflight = response.mappingPreflight || {};
  laborState.run = {
    ...laborState.run,
    mappingPreflight: submittedPreflight,
    workerTask: response.workerTask || laborState.run.workerTask,
  };
  if (submittedPreflight.status === "completed") return submittedPreflight;
  let progressMessage = mappingPreflightProgressMessage(laborState.run);
  labor.mappingPreview.innerHTML = `<p class="empty-state-text">${escapeHtml(progressMessage)}</p>`;
  beginButtonLoading(labor.loadSheets, progressMessage);
  const deadline = Date.now() + (10 * 60 * 1000);
  for (let attempt = 0; Date.now() < deadline; attempt += 1) {
    const delayMs = Math.min(15000, 5000 + (attempt * 2500));
    await new Promise((resolve) => window.setTimeout(resolve, delayMs));
    const run = await requestJson(`/api/labor/runs/${laborState.run.id}`);
    laborState.run = run;
    const preflight = run.mappingPreflight || {};
    if (preflight.status === "completed") return preflight;
    if (preflight.status === "failed") {
      throw new Error(preflight.errorMessage || "本人核对助手读取 Excel 失败，请检查助手状态后重试。");
    }
    progressMessage = mappingPreflightProgressMessage(run);
    beginButtonLoading(labor.loadSheets, progressMessage);
    labor.mappingPreview.innerHTML = `<p class="empty-state-text">${escapeHtml(progressMessage)}</p>`;
  }
  throw new Error("字段预检等待超过 10 分钟，请确认本人核对助手已激活并在线后重试。");
}

function mappingPreflightProgressMessage(run) {
  const task = run?.workerTask || {};
  const status = String(task.status || "");
  const phase = String(task.progress?.phase || "");
  const phaseMessages = {
    claimed: "Worker 已领取任务",
    downloading_excel: "正在下载 Excel",
    reading_workbook: "正在读取工作表",
    uploading_result: "正在回传结果",
  };
  if (phaseMessages[phase]) return phaseMessages[phase];
  if (status === "running") return "Worker 已领取任务";
  if (status === "retry_wait") return "核对助手将在稍后重试";
  return "等待核对助手连接";
}

function mappingPreflightSuggestion(sheetName) {
  const preflight = laborState.run?.mappingPreflight;
  if (preflight?.status !== "completed" || !Array.isArray(preflight.workbooks)) return null;
  for (const workbook of preflight.workbooks) {
    const sheet = Array.isArray(workbook?.sheets)
      ? workbook.sheets.find((item) => String(item?.name || "") === sheetName)
      : null;
    if (sheet?.suggestion && typeof sheet.suggestion === "object") return sheet.suggestion;
  }
  return null;
}

function applyFieldSuggestions(data) {
  laborState.headers = data.headers || [];
  fillColumnSelect(labor.employeeIdColumn, data.suggestedMapping?.employeeId, true);
  fillColumnSelect(labor.nameColumn, data.suggestedMapping?.name);
  fillColumnSelect(labor.hoursColumn, data.suggestedMapping?.hours);
  fillColumnSelect(labor.amountColumn, data.suggestedMapping?.amount);
  laborState.amountColumnCandidates = data.amountColumnCandidates || [];
  renderAmountComponentOptions();
  fillColumnSelect(labor.currencyColumn, data.suggestedMapping?.currency, true);
  renderMappingPreview(data.previewRows || []);
}

async function loadFieldSuggestions() {
  const requestId = ++laborFieldSuggestionRequestId;
  const runId = laborState.run?.id;
  const sheetName = labor.sheetSelect.value;
  if (!sheetName || !runId) return;
  try {
    const cachedSuggestion = mappingPreflightSuggestion(sheetName);
    const data = cachedSuggestion || await requestJson(`/api/labor/runs/${runId}/field-suggestions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sheet_name: sheetName }),
    });
    if (
      requestId !== laborFieldSuggestionRequestId
      || laborState.run?.id !== runId
      || labor.sheetSelect.value !== sheetName
    ) return;
    applyFieldSuggestions(data);
  } catch (error) {
    if (
      requestId !== laborFieldSuggestionRequestId
      || laborState.run?.id !== runId
      || labor.sheetSelect.value !== sheetName
    ) return;
    toast(error.message);
  }
}

async function saveMapping() {
  if (!laborState.run) return toast("请先创建批次。");
  beginButtonLoading(labor.saveMapping, "正在保存");
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
          amountColumns: selectedAmountColumns(),
          amountScope: labor.amountScope.value,
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
    toast("字段映射已确认，开始生成核对报告。");
    await extractAndCompare();
  } catch (error) {
    recordLaborTelemetry("labor.mapping.failed", {
      step: "mapping",
      status: "failed",
      durationMs: elapsedMs(startedAt),
      errorMessage: error.message,
      context,
    });
    toast(error.message);
  } finally {
    endButtonLoading(labor.saveMapping);
  }
}

async function loadMaterialBatches() {
  if (!labor.materialBatchSelect || !labor.materialReplayBody) return;
  setText(labor.materialReplayStatus, "正在加载测试材料...");
  beginButtonLoading(labor.loadMaterialBatches, "正在加载");
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
    setText(labor.materialReplayStatus, batches.length ? `已发现 ${batches.length} 批可验证的测试材料。` : "未发现可验证的测试材料。", !batches.length);
  } catch (error) {
    setText(labor.materialReplayStatus, error.message, true);
    toast(error.message);
  } finally {
    endButtonLoading(labor.loadMaterialBatches);
  }
}

async function runMaterialDryRun() {
  const batchKey = labor.materialBatchSelect?.value || "";
  if (!batchKey) return toast("请先选择材料批次。");
  setText(labor.materialReplayStatus, "正在执行测试验证...");
  beginButtonLoading(labor.runMaterialDryRun, "正在验证");
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
    setText(labor.materialReplayStatus, `测试验证完成：异常 ${dryRun.summary?.comparison?.exceptionCount || 0}，疑似同一员工 ${candidateCount}，疑似合并行 ${combinedCount}。`);
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
    endButtonLoading(labor.runMaterialDryRun);
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
        <strong>测试材料验证</strong>
        <span>已找到 ${readyCount || summary.candidateBatchCount || 0} 批可用于验证的测试材料。选择一批后，可查看系统会如何生成业务报告。</span>
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
    .replaceAll("candidate-only", "仅提示业务确认")
    .replaceAll("Dry-run", "测试验证")
    .replaceAll("dry-run", "测试验证")
    .replaceAll("重 OCR", "图片发票明细待确认")
    .replaceAll("OCR", "图片发票明细待确认")
    .replaceAll("回放", "验证")
    .replaceAll("候选", "建议")
    .replaceAll("姓名映射", "疑似同一员工")
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
    : `<div class="governance-empty">本次测试验证未发现需要业务确认的疑似同一员工。</div>`;
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
        <strong>疑似同一员工</strong>
        <span>系统找到 ${nameMappingQueue.count || governanceSummary.candidateCount || 0} 条需要业务确认的疑似同一员工。业务确认前不会自动改结果。金额仍不同 ${nameMappingQueue.amountStillDifferentCount || governanceSummary.amountStillDifferentCount || 0} 条，工时仍不同 ${nameMappingQueue.hoursStillDifferentCount || governanceSummary.hoursStillDifferentCount || 0} 条。</span>
      </div>
      <div class="governance-meta">
        <span class="governance-pill warning">需业务确认</span>
        <span class="governance-pill warning">业务确认前不自动合并</span>
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
        <strong>疑似一行包含多名员工</strong>
        <span>系统发现 ${combinedQueue.count || combinedRowSummary.candidateCount || 0} 条可能被 PDF 合并显示的员工明细；请对照原发票确认。金额影响 ${formatMoney(combinedQueue.amountImpactTotal || combinedRowSummary.amountImpactTotal || 0)}，工时影响 ${formatSignedNumber(combinedQueue.hoursImpactTotal || combinedRowSummary.hoursImpactTotal || 0)}。</span>
      </div>
      <div class="governance-meta">
        <span class="governance-pill warning">需查看原发票</span>
        <span class="governance-pill warning">不能自动清账</span>
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
    ? `<span class="governance-pill">图片发票明细待确认 ${reocrQueue.taskCount || 0}</span>`
    : "";
  const primaryPillClass = reviewQueues.primary === "reocr" ? "danger" : reviewQueues.primary === "cleared" ? "ok" : "warning";

  labor.materialReplayBody.innerHTML = `
    <div class="governance-command">
      <div>
        <strong>${escapeHtml(dryRun.directory || dryRun.batchKey || "测试材料")} · 测试材料验证</strong>
        <span>总账结论：${warehouse.totalPassed ? "总账通过" : "总金额存在差异"}。PDF ${comparison.pdfEmployeeCount || 0} 人，Excel ${comparison.excelEmployeeCount || 0} 人，待确认 ${comparison.exceptionCount || 0} 项，疑似同一员工 ${comparison.candidateMatchCount || 0} 项。${reviewQueues.primaryReason ? ` ${escapeHtml(materialDisplayText(reviewQueues.primaryReason))}` : ""}</span>
      </div>
      <div class="governance-meta">
        <span class="governance-pill ${warehouse.totalPassed ? "ok" : "warning"}">${warehouse.totalPassed ? "总账通过" : "总金额待确认"}</span>
        <span class="governance-pill">差额 ${formatSignedMoney(comparison.amountDeltaTotal || 0)}</span>
        <span class="governance-pill ${primaryPillClass}">待确认原因 ${escapeHtml(materialReviewQueueLabel(reviewQueues.primary, reviewQueues))}</span>
        ${reocrPillHtml}
        <span class="governance-pill">金额计算 ${amountRateQueue.count || 0}</span>
        <span class="governance-pill">仓库分摊 ${allocationQueue.count || 0}</span>
        <span class="governance-pill">员工明细 ${exceptionQueue.count || 0}</span>
        <span class="governance-pill">疑似同一员工 ${nameMappingQueue.count || governanceSummary.candidateCount || 0}</span>
        <span class="governance-pill">疑似合并行 ${combinedQueue.count || combinedRowSummary.candidateCount || 0}</span>
      </div>
      <div class="governance-action-row">
        <button class="btn-primary-lg" type="button" data-material-action="create-run">生成测试报告</button>
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
      <span class="readiness-pill">${escapeHtml(deliveryGate.label || "需确认")}</span>
      <span>测试材料验证检查 · 阻断 ${summary.blockedCount || 0} · 待确认 ${summary.reviewCount || 0} · 风险 ${summary.riskCount || 0}</span>
    </div>
    ${issueHtml}
  </div>`;
}

function renderMaterialNameMappingNextActions(actions) {
  return renderMaterialNextActions(actions, { title: "疑似同一员工处理路径" });
}

function materialReviewQueueLabel(primary, reviewQueues = {}) {
  const labels = {
    reocr: "图片发票明细待确认",
    amount_rate_review: "金额/费率",
    allocation_review: "跨仓归属",
    name_mapping: "姓名匹配",
    combined_pdf_row: "疑似合并行",
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
        <strong>跨仓归属待确认</strong>
        <span>${escapeHtml(allocation.count || 0)} 名员工总额可抵消，但仓库归属仍不一致 · 涉及 ${escapeHtml(allocation.warehousePairCount || 0)} 个仓库明细 · 最大影响 ${formatMoney(allocation.amountImpactTotal || 0)}</span>
      </div>
      <div class="governance-meta">
        <span class="governance-pill warning">需按仓确认</span>
        <span class="governance-pill warning">只留痕不自动改金额</span>
      </div>
    </div>
    ${renderMaterialNextActions(allocation.nextActions || [], { title: "跨仓归属确认步骤" })}
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
    <p>${escapeHtml(row.recommendation || "员工总额可抵消，但仓库归属金额不一致，需按仓库确认发票与账单归属。")}</p>
    ${warehouseText ? `<p>${escapeHtml(warehouseText)}</p>` : ""}
    <div class="governance-action-row">
      <button class="btn-secondary" type="button" disabled>正式核对时确认</button>
      <button class="btn-primary-lg" type="button" disabled>确认前必须留痕</button>
    </div>
  </article>`;
}

function renderMaterialAmountRateQueue(reviewQueues) {
  const amountRate = reviewQueues?.amountRateReview || {};
  const rows = Array.isArray(amountRate.rows) ? amountRate.rows : [];
  if (!rows.length) return "";
  const hasHoursMismatch = Number(amountRate.hoursMismatchCount || 0) > 0;
  const title = hasHoursMismatch ? "先核对工时，再判断金额" : "工时已对齐，核对金额计算方式";
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
        <span class="governance-pill warning">${hasHoursMismatch ? "先核工时" : "只核金额计算"}</span>
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
      <span>确认结论</span>
      <strong>${escapeHtml(reviewMode === "hours_and_amount" ? "先确认是否同一批工时" : "金额计算方式待业务确认")}</strong>
      <p>${escapeHtml(amountRate.businessMeaning || "需确认 PDF 与 Excel 的结算口径。")}</p>
    </div>
    <div>
      <span>不能自动处理</span>
      <strong>${escapeHtml(reviewMode === "hours_and_amount" ? "工时会影响金额" : "金额计算方式需留痕")}</strong>
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
  return renderMaterialNextActions(actions, { title: "金额/工时确认步骤" });
}

function renderMaterialAmountRateCard(row) {
  const flags = Array.isArray(row.riskFlags) ? row.riskFlags : [];
  const flagHtml = flags.length
    ? flags.slice(0, 3).map((flag) => `<span class="governance-pill warning">${escapeHtml(flag)}</span>`).join("")
    : `<span class="governance-pill warning">金额差异</span>`;
  const reviewLabel = row.reviewLabel || (Number(row.hoursDelta || 0) ? "工时和金额都不同" : "工时一致，仅金额不同");
  const reviewFocus = row.reviewFocus || (Number(row.hoursDelta || 0) ? "先核工时范围" : "先核金额计算方式");
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
    <p>${escapeHtml(row.cannotAutoResolveReason || row.recommendation || "需确认发票费率、加班、服务费倍率与账单成本口径。")}</p>
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
    ...tasks.map((task) => renderMaterialReocrTaskCard(task, "图片发票明细待确认")),
    ...reviewable.map((candidate) => renderMaterialReocrTaskCard(candidate, "历史识别结果待确认")),
  ];
  const groupSummaryHtml = renderMaterialReocrGroupSummary(reocr);
  const suppressedHtml = exceptions.suppressedByPrimary
    ? `<p class="governance-empty">${escapeHtml(exceptions.count || 0)} 条员工异常来自 PDF 明细缺失；请先查看原始发票并确认图片发票明细，再判断这些差异。</p>`
    : "";
  const nextActionsHtml = renderMaterialReocrNextActions(reocr.nextActions || []);
  return `
    <div class="governance-command">
      <div>
        <strong>图片发票明细待确认</strong>
        <span>${escapeHtml(materialDisplayText(reocr.summaryText || "")) || `${escapeHtml(reocr.imageOnlyFileCount || 0)} 个 PDF 需要查看原始发票 · 待确认 ${escapeHtml(reocr.taskCount || 0)} 项 · 历史识别结果待确认 ${escapeHtml(reocr.reviewableCandidateCount || 0)} 项 · 历史识别异常 ${escapeHtml(reocr.cacheExceptionCount || 0)} 项`}</span>
      </div>
      <div class="governance-meta">
        <span class="governance-pill danger">先处理</span>
        <span class="governance-pill warning">需业务确认</span>
        <span class="governance-pill warning">正式核对时确认</span>
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
        : `<div class="governance-empty">暂无图片发票明细待确认事项。</div>`
    }
    ${suppressedHtml}
  `;
}

function renderMaterialReocrGroupSummary(reocr) {
  const groups = Array.isArray(reocr?.groups) ? reocr.groups : [];
  if (!groups.length) return "";
  const visible = groups.slice(0, 4);
  const items = visible.map((group) => {
    const label = group.statusLabel || (Number(group.taskCount || 0) ? "需重新识别" : "已有识别结果可查看");
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
  const label = options.collapsedLabel || "展开其余建议";
  return `${title}${visibleHtml}
    <details class="governance-more">
      <summary>${escapeHtml(label)}（${hidden.length} 项）</summary>
      <div class="governance-card-grid">${hidden.join("")}</div>
    </details>`;
}

function renderMaterialReocrNextActions(actions) {
  return renderMaterialNextActions(actions, { title: "图片发票确认步骤" });
}

function renderMaterialNextActions(actions, options = {}) {
  const rows = (Array.isArray(actions) ? actions : []).filter((action) => {
    const label = materialDisplayText(action?.label || "");
    return label !== "生成测试报告";
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
        const stateText = enabled ? "当前可执行：点击上方主按钮" : "正式核对时解锁";
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
        const status = item.matchStatus || "待确认";
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
    <p>${escapeHtml(materialDisplayText(task.recommendation || task.confirmationGate || "需补充发票识别结果，业务确认后才能影响核对结果。"))}</p>
    ${task.cannotAutoResolveReason ? `<p>${escapeHtml(materialDisplayText(task.cannotAutoResolveReason))}</p>` : ""}
    ${issueText ? `<p>${escapeHtml(issueText)}</p>` : ""}
    ${focusHtml}
    <div class="governance-action-row">
      <button class="btn-secondary" type="button" disabled>正式核对时查看</button>
      <button class="btn-primary-lg" type="button" disabled>正式核对时确认</button>
    </div>
  </article>`;
}

function renderMaterialNameMappingCandidateCard(candidate) {
  const evidence = candidate.evidence || {};
  const isHighConfidence = candidate.confidence === "high";
  const confidenceLabel = isHighConfidence ? "把握较高" : "需业务确认";
  return `<article class="governance-card">
    <div class="governance-meta">
      <span class="governance-pill ${isHighConfidence ? "ok" : "warning"}">${escapeHtml(confidenceLabel)}</span>
      <span class="governance-pill">仓 ${escapeHtml(candidate.warehouseId || "-")}</span>
      <span class="governance-pill ${Number(candidate.projectedFixedExceptionCount || 0) ? "ok" : "warning"}">可能减少待确认 ${escapeHtml(candidate.projectedFixedExceptionCount || 0)} 项</span>
      <span class="governance-pill">金额差 ${formatSignedMoney(candidate.amountGap || 0)}</span>
      <span class="governance-pill">工时差 ${formatSignedNumber(candidate.hoursGap || 0)}</span>
    </div>
    <h3>${escapeHtml(candidate.cacheEmployeeName || "-")} ⇄ ${escapeHtml(candidate.excelEmployeeName || "-")}</h3>
    ${candidate.matchReason ? `<p><strong>${escapeHtml(materialDisplayText(candidate.matchReason))}</strong></p>` : ""}
    ${candidate.businessQuestion ? `<p>${escapeHtml(materialDisplayText(candidate.businessQuestion))}</p>` : ""}
    ${candidate.impactSummary ? `<p>${escapeHtml(materialDisplayText(candidate.impactSummary))}</p>` : ""}
    <p>${escapeHtml(materialDisplayText(candidate.recommendation || "正式核对时需先查看影响，再由业务确认。"))}</p>
    ${candidate.cannotAutoResolveReason ? `<p>${escapeHtml(materialDisplayText(candidate.cannotAutoResolveReason))}</p>` : ""}
    ${evidence.sourceRefs ? `<p>${escapeHtml(evidence.sourceRefs)}</p>` : ""}
    <div class="governance-action-row">
      <button class="btn-secondary" type="button" disabled>正式核对时查看</button>
      <button class="btn-primary-lg" type="button" disabled>正式核对时确认</button>
    </div>
  </article>`;
}

function renderMaterialCombinedRowCandidateCard(candidate) {
  const evidence = candidate.evidence || {};
  return `<article class="governance-card">
    <div class="governance-meta">
      <span class="governance-pill warning">疑似合并行待确认</span>
      <span class="governance-pill">仓 ${escapeHtml(candidate.warehouseId || "-")}</span>
      <span class="governance-pill">金额影响 ${formatMoney(Math.abs(candidate.amountGap || 0))}</span>
      <span class="governance-pill">工时影响 ${formatSignedNumber(Math.abs(candidate.hoursGap || 0))}</span>
    </div>
    <h3>${escapeHtml(candidate.pdfEmployeeName || "-")} → ${escapeHtml(candidate.excelEmployeeName || "-")}</h3>
    ${candidate.matchReason ? `<p><strong>${escapeHtml(materialDisplayText(candidate.matchReason))}</strong></p>` : ""}
    ${candidate.businessQuestion ? `<p>${escapeHtml(materialDisplayText(candidate.businessQuestion))}</p>` : ""}
    ${candidate.impactSummary ? `<p>${escapeHtml(materialDisplayText(candidate.impactSummary))}</p>` : ""}
    <p>${escapeHtml(materialDisplayText(candidate.recommendation || "疑似 PDF 一行覆盖多名员工，需业务确认原始发票。"))}</p>
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
  beginButtonLoading(button, "正在生成");
  setMaterialActionFeedback("处理中", "正在根据测试材料生成测试报告；完成后会提示下一步。");
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
    syncPeriodRangePicker();
    if (labor.currency) labor.currency.value = run.currency || "USD";
    const nextStep = run.materialReplayNextStep || {};
    setText(labor.materialReplayStatus, `测试报告已生成：${run.id}`);
    if (labor.uploadStatus) setText(labor.uploadStatus, "已带入测试材料文件。");
    if (labor.compareStatus) setText(labor.compareStatus, nextStep.description || "测试材料已带入，可直接生成核对报告。");
    setMaterialActionFeedback(
      "测试报告已生成",
      `测试报告 ${run.id.slice(0, 8)} 已带入测试材料和字段映射。下一步：${nextStep.label || "生成核对报告"}。完成后再查看待确认事项。`
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
    toast(nextStep.label ? `已生成测试报告，下一步：${nextStep.label}。` : "已生成测试报告。");
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
    endButtonLoading(button);
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
  if (labor.autoFixSection) {
    labor.autoFixSection.hidden = true;
    if (labor.autoFixBody) labor.autoFixBody.innerHTML = "";
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
        <p class="empty-title">暂无识别证据</p>
        <p class="empty-desc">点击「生成核对报告」开始核对</p>
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
  const totalCard = document.querySelector("#kpiTotal .kpi-sub");
  const matchedCard = document.querySelector("#kpiMatched .kpi-sub");
  const varianceCard = document.querySelector("#kpiVariance .kpi-sub");
  const unmatchedCard = document.querySelector("#kpiUnmatched .kpi-sub");
  if (totalCard) totalCard.textContent = "尚未核对";
  if (matchedCard) matchedCard.textContent = "尚未核对";
  if (varianceCard) varianceCard.textContent = "容差 $0.10";
  if (unmatchedCard) unmatchedCard.textContent = "待确认项目";
  setText(labor.compareStatus, "新批次尚未生成核对结果。");
}

async function extractAndCompare() {
  if (isFormalLaborTaskBlocked()) {
    showFormalLaborTaskBlocked();
    return;
  }
  const requestedRunId = laborState.run?.id;
  if (!requestedRunId) return toast("请先创建批次。");
  showLaborResultsView();
  stopComparePolling();
  clearResults();

  setText(labor.compareStatus, "已提交核对任务，正在等待结果…");
  beginButtonLoading(labor.extractCompare, "正在生成");
  laborState.pollRetryCount = 0;
  laborState.extractStartedAt = performance.now();
  recordLaborTelemetry("labor.extract.started", {
    step: "extract_compare",
    status: "started",
    context: { button: "extractCompare" },
  });

  try {
    const submittedRun = await requestJson(`/api/labor/runs/${requestedRunId}/extract-and-compare`, {
      method: "POST",
    });
    if (laborState.run?.id !== requestedRunId) return;
    laborState.run = submittedRun;
    renderLaborProgress(laborState.run);
    setText(labor.compareStatus, formatLaborTaskStatus(laborState.run, "待处理：核对任务已提交，等待后台开始处理。"));
    recordLaborTelemetry("labor.extract.submitted", {
      step: "extract_compare",
      status: "submitted",
      durationMs: elapsedMs(laborState.extractStartedAt),
    });
    await pollCompareResult();
    laborState.comparePollTimer = window.setInterval(pollCompareResult, 3000);
  } catch (error) {
    if (laborState.run?.id !== requestedRunId) return;
    recordLaborTelemetry("labor.extract.failed", {
      step: "extract_compare",
      status: "failed",
      durationMs: elapsedMs(laborState.extractStartedAt),
      errorMessage: error.message,
    });
    laborState.extractStartedAt = null;
    endButtonLoading(labor.extractCompare, { disabled: false });
    setText(labor.compareStatus, error.message, true);
    toast(error.message);
  }
}

async function pollCompareResult() {
  const requestedRunId = laborState.run?.id;
  if (!requestedRunId) return;
  laborState.pollRetryCount++;
  try {
    const run = await requestJson(`/api/labor/runs/${requestedRunId}`);
    if (laborState.run?.id !== requestedRunId) return;
    laborState.run = run;
    renderLaborProgress(run);
    if (run.status === "抽取失败") {
      stopComparePolling();
      endButtonLoading(labor.extractCompare, { disabled: false });
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
      toast(run.retryable ? "核对任务中断，可直接重试。" : "核对报告生成失败。");
      return;
    }
    if (laborRunHasSettledResult(run)) {
      stopComparePolling();
      endButtonLoading(labor.extractCompare, { disabled: false });
      renderResult(run);
      setText(labor.compareStatus, "完成：核对报告已生成。识别不完整的明细已进入待确认清单。");
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
    const idleSeconds = secondsSince(run?.progress?.lastUpdatedAt);
    if (Number.isFinite(idleSeconds) && idleSeconds > laborState.pollMaxIdleSeconds) {
      stopComparePolling();
      endButtonLoading(labor.extractCompare, { disabled: false });
      const message = "后台超过10分钟没有更新进度，任务可能已中断。请检查服务后再重试。";
      setText(labor.compareStatus, message, true);
      recordLaborTelemetry("labor.extract.stalled", {
        run,
        step: "extract_compare",
        status: "stalled",
        durationMs: elapsedMs(laborState.extractStartedAt),
        context: { idleSeconds },
      });
      laborState.extractStartedAt = null;
      toast("后台任务长时间没有更新。");
      return;
    }
    // 显示实时进度（stage 字段）
    const elapsed = laborState.pollRetryCount * 3;
    setText(labor.compareStatus, formatLaborTaskStatus(run, `处理中：${businessStageLabel(run.stage || "生成核对报告")}... (${elapsed}s)`));
  } catch (error) {
    if (laborState.run?.id !== requestedRunId) return;
    stopComparePolling();
    endButtonLoading(labor.extractCompare, { disabled: false });
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
  const message = formatLaborRequestError(run?.errorMessage || "核对报告生成失败，请检查文件后重试。");
  if (!run?.retryable) return message;
  const nextAction = run.nextAction
    ? formatLaborRequestError(run.nextAction)
    : "请重新点击「生成核对报告」重试。";
  const stage = businessStageLabel(run.stage || "系统中断");
  return nextAction === message ? `${stage}：${message}` : `${stage}：${message} ${nextAction}`;
}

function businessStageLabel(value) {
  const text = String(value || "");
  const extractionWord = "抽" + "取";
  return text
    .replaceAll(`${extractionWord}并比对`, "生成核对报告")
    .replaceAll(`${extractionWord}比对`, "生成核对报告")
    .replaceAll(extractionWord, "核对");
}

function formatLaborTaskStatus(run, fallback) {
  const task = run?.asyncTask || {};
  const progress = formatLaborProgressInline(run);
  const label = task.statusLabel || "";
  const message = task.message || "";
  if (!label) return fallback;
  if (label === "待处理") return message ? `待处理：${message}` : "待处理：核对任务已提交，等待后台开始处理。";
  if (label === "处理中") {
    if (progress) return progress;
    const stage = businessStageLabel(run?.stage || "");
    const detail = message || stage || "后台正在生成核对结果。";
    return `处理中：${detail}`;
  }
  if (label === "完成") return message ? `完成：${message}` : "完成：核对报告已生成。";
  if (label === "失败") return message ? `失败：${message}` : "失败：核对报告生成失败。";
  return `${label}：${message || fallback}`;
}

function renderLaborProgress(run) {
  const progress = run?.progress || {};
  const taskStatus = run?.asyncTask?.status || "";
  const isProcessing = run?.status === "抽取中" || ["queued", "running"].includes(taskStatus);
  if (!isProcessing || !labor.extractPreviewTable) return;

  const phase = progress.phase || "queued";
  const totalPages = Number(progress.totalPages || 0);
  const processedPages = Number(progress.processedPages || 0);
  const totalFiles = Number(progress.totalFiles || 0);
  const processedFiles = Number(progress.processedFiles || 0);
  const percent = totalPages > 0
    ? Math.max(0, Math.min(100, Math.round((processedPages / totalPages) * 100)))
    : processedFiles > 0 && totalFiles > 0
      ? Math.max(0, Math.min(100, Math.round((processedFiles / totalFiles) * 100)))
      : 8;
  const elapsed = formatElapsedFrom(progress.startedAt) || formatElapsedFrom(run?.asyncTask?.startedAt) || "刚开始";
  const idleSeconds = secondsSince(progress.lastUpdatedAt);
  const isIdle = Number.isFinite(idleSeconds) && idleSeconds >= 180;
  const currentFile = progress.currentFile || "等待后台更新";
  const currentPage = progress.currentPage ? `第 ${progress.currentPage} 页` : "待确认";
  const pageText = totalPages > 0 ? `${processedPages} / ${totalPages} 页` : "准备中";
  const fileText = totalFiles > 0 ? `${processedFiles || 0} / ${totalFiles} 个文件` : "准备中";
  const message = progress.message || run?.asyncTask?.message || "后台正在读取已上传文件并生成核对结果。";
  const warning = isIdle
    ? "后台超过 3 分钟没有更新进度，可能正在等待 AI 识别服务响应；如果长时间不变化，可以重新点击生成报告。"
    : "图片型发票需要逐页识别，页数多时会比较慢。页面可以保持打开，系统会自动刷新结果。";

  labor.extractPreviewTable.innerHTML = `
    <div class="labor-progress-card">
      <div class="labor-progress-top">
        <div>
          <span class="labor-progress-eyebrow">${escapeHtml(progress.phaseLabel || "正在生成核对报告")}</span>
          <h3 class="labor-progress-title">正在生成核对报告</h3>
          <p class="labor-progress-message">${escapeHtml(message)}</p>
        </div>
        <div class="labor-progress-time">
          已用时
          <strong>${escapeHtml(elapsed)}</strong>
        </div>
      </div>
      <div class="labor-progress-track" aria-label="核对进度"><span style="width:${percent}%"></span></div>
      <div class="labor-progress-meta">
        <div><span>PDF 识别页数</span><strong>${escapeHtml(pageText)}</strong></div>
        <div><span>当前文件</span><strong>${escapeHtml(currentFile)}</strong></div>
        <div><span>当前位置</span><strong>${escapeHtml(currentPage)}</strong></div>
      </div>
      <ol class="labor-progress-steps">
        ${renderLaborProgressStep("excel", "读取账单", phase)}
        ${renderLaborProgressStep("pdf_total", "核对总金额", phase)}
        ${renderLaborProgressStep("pdf_detail", "识别发票明细", phase)}
        ${renderLaborProgressStep("report", "生成报告", phase)}
      </ol>
      <p class="labor-progress-warning">${escapeHtml(warning)}</p>
    </div>
  `;
}

function renderLaborProgressStep(step, label, phase) {
  const order = { queued: 0, excel: 1, pdf_total: 2, pdf_detail: 3, matching: 4, report: 5, completed: 6 };
  const stepOrder = { excel: 1, pdf_total: 2, pdf_detail: 3, report: 5 };
  const current = order[phase] ?? 0;
  const target = stepOrder[step] ?? 0;
  const className = current === target ? "is-active" : current > target ? "is-done" : "";
  const state = current === target ? "进行中" : current > target ? "已完成" : "等待中";
  return `<li class="${className}">${escapeHtml(label)}<br><span>${escapeHtml(state)}</span></li>`;
}

function formatLaborProgressInline(run) {
  const progress = run?.progress || {};
  if (!progress.phaseLabel && !progress.message) return "";
  const totalPages = Number(progress.totalPages || 0);
  const processedPages = Number(progress.processedPages || 0);
  if (totalPages > 0) {
    return `处理中：${progress.phaseLabel || "生成核对报告"}，${processedPages} / ${totalPages} 页`;
  }
  return `处理中：${progress.message || progress.phaseLabel || "后台正在生成核对结果。"}`;
}

function formatElapsedFrom(isoValue) {
  const startedAt = parseIsoTime(isoValue);
  if (!Number.isFinite(startedAt)) return "";
  return formatDuration(Math.max(0, Date.now() - startedAt));
}

function secondsSince(isoValue) {
  const time = parseIsoTime(isoValue);
  if (!Number.isFinite(time)) return NaN;
  return Math.floor((Date.now() - time) / 1000);
}

function parseIsoTime(value) {
  const text = String(value || "").trim();
  if (!text) return NaN;
  const isIsoDateTime = /^\d{4}-\d{2}-\d{2}T/.test(text);
  const hasExplicitTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(text);
  const normalized = isIsoDateTime && !hasExplicitTimezone ? `${text}Z` : text;
  const parsed = Date.parse(normalized);
  return Number.isFinite(parsed) ? parsed : NaN;
}

function formatDuration(ms) {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes <= 0) return `${seconds} 秒`;
  return `${minutes} 分 ${String(seconds).padStart(2, "0")} 秒`;
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

function renderAmountComponentOptions() {
  if (!labor.amountComponentColumns) return;
  const primary = labor.amountColumn.value;
  const selected = new Set(selectedAdditionalAmountColumns());
  const candidates = (laborState.amountColumnCandidates || []).filter((header) => header && header !== primary);
  const list = labor.amountComponentColumns.querySelector("[data-amount-component-list]");
  labor.amountComponentColumns.hidden = candidates.length === 0;
  if (!list) return;
  list.innerHTML = candidates
    .map((header) => `
      <label class="amount-component-option">
        <input type="checkbox" value="${escapeHtml(header)}" ${selected.has(header) ? "checked" : ""} />
        <span>${escapeHtml(header)}</span>
      </label>
    `)
    .join("");
}

function selectedAdditionalAmountColumns() {
  if (!labor.amountComponentColumns) return [];
  return Array.from(labor.amountComponentColumns.querySelectorAll('input[type="checkbox"]:checked'))
    .map((input) => input.value)
    .filter(Boolean);
}

function selectedAmountColumns() {
  return Array.from(new Set([labor.amountColumn.value, ...selectedAdditionalAmountColumns()].filter(Boolean)));
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

function isLaborTotalAmountPassed(summary, wcSummary) {
  const amountDeltaTotal = Number(wcSummary?.amountDeltaTotal ?? summary?.amountDeltaTotal ?? 0);
  const roundedDelta = Math.round(Math.abs(amountDeltaTotal) * 100) / 100;
  if (Number.isFinite(roundedDelta)) {
    return roundedDelta <= LABOR_TOTAL_AMOUNT_TOLERANCE;
  }
  return Boolean(wcSummary && wcSummary.totalPassed);
}

function renderResult(run) {
  const summary = run.comparisonSummary || {};
  const wc = run.warehouseComparison;
  const wcSummary = wc && wc.summary;
  const totalPassed = isLaborTotalAmountPassed(summary, wcSummary);
  const presentation = laborPresentationContract(run);
  const rows = presentation.employeeRows;
  const candidateMatches = presentation.candidateMatches;
  const presentationSummary = presentation.summary;

  // Update KPI cards
  updateKpiCards(summary, rows, wcSummary, candidateMatches, run, presentationSummary);

  // 1. 顶部卡片下方优先展示完整员工明细
  renderEmployeeReconTable(rows, summary, totalPassed, wcSummary, presentationSummary);

  // 2. 结论和放行提示
  renderConclusion(summary, wcSummary, run.extractionQuality, run, presentation);
  renderReadinessGate(run.readinessGate);

  // 3. 总金额、员工识别和仓库概览
  renderQualityAlert(run.extractionQuality, run.reconciliationDiagnostics, run);
  renderWarehouseTable(wc);
  const hasDiagnostics = (labor.qualityAlert && !labor.qualityAlert.hidden) || (wc && wc.rows && wc.rows.length > 0);
  if (labor.diagnosticsFold) {
    labor.diagnosticsFold.hidden = !hasDiagnostics;
  }

  // 4. 已识别员工明细 / 总账通过证据
  if (totalPassed) {
    renderPassEvidence(labor.extractPreviewTable, summary, wcSummary);
  } else {
    renderExtractRows(labor.extractPreviewTable, run.pdfExtractedRows || []);
  }

  // 5. 系统已安全自动修正的姓名格式差异
  renderAutoFixSummary(rows);

  // 6. 待确认异常和疑似同一员工
  renderPendingItems(rows, candidateMatches, summary, run.reviewQueues || {});
}

function normalizeReviewWarehouses(values) {
  return (Array.isArray(values) ? values : [])
    .map((warehouse) => String(warehouse || "").trim())
    .filter(Boolean);
}

function updateKpiCards(summary, rows, wcSummary, candidateMatches = [], run = {}, presentationSummary = {}) {
  const currencySymbol = laborCurrencySymbol(run);
  const employeeRows = Array.isArray(rows) ? rows : [];
  const pdfCount = summary.pdfEmployeeCount || 0;
  const excelCount = summary.excelEmployeeCount || 0;
  const skippedEmployeeDrilldown = isLaborTotalAmountPassed(summary, wcSummary) && !employeeRows.length;
  const amountDiffCount = summary.amountDiffCount || 0;
  const notInInvoiceCount = summary.notInInvoiceCount || 0;
  const pdfAmount = wcSummary ? wcSummary.pdfAmountTotal || 0 : summary.pdfAmountTotal || 0;
  const excelAmount = wcSummary ? wcSummary.excelAmountTotal || 0 : summary.excelAmountTotal || 0;
  const amountDelta = wcSummary ? wcSummary.amountDeltaTotal || 0 : summary.amountDeltaTotal || 0;
  const pdfInvoiceCount = Array.isArray(run?.files?.pdfInvoices) ? run.files.pdfInvoices.length : 0;
  const excelRecordCount = Number(presentationSummary?.excelRecordCount ?? 0) || (
    Array.isArray(run?.excelRows)
      ? run.excelRows.length
      : Array.isArray(run?.warehouseComparison?.rows)
        ? run.warehouseComparison.rows.reduce((sum, row) => sum + Number(row.excelEmployeeCount || 0), 0)
        : excelCount
  );
  const reviewWarehouses = normalizeReviewWarehouses(wcSummary?.diffWarehouses);

  // Calculate cleared matches
  const clearedCount = Number(presentationSummary?.passedEmployeeCount ?? employeeRows.filter(
    (r) => r.matchStatus === "通过" || r.matchStatus === "金额一致"
  ).length);
  const reviewCount = Number(
    presentationSummary?.reviewItemCount
      ?? (amountDiffCount + notInInvoiceCount + (summary.hoursDiffCount || 0) + (candidateMatches ? candidateMatches.length : 0))
  );

  if (labor.kpiTotal) labor.kpiTotal.textContent = `${currencySymbol}${formatMoney(pdfAmount)}`;
  if (labor.kpiMatched) labor.kpiMatched.textContent = `${currencySymbol}${formatMoney(excelAmount)}`;
  if (labor.kpiVariance) labor.kpiVariance.textContent = `${amountDelta >= 0 ? "+" : "-"}${currencySymbol}${formatMoney(Math.abs(amountDelta))}`;
  if (labor.kpiUnmatched) labor.kpiUnmatched.textContent = `${reviewCount} 项`;

  const totalCard = document.querySelector("#kpiTotal .kpi-sub");
  const matchedCard = document.querySelector("#kpiMatched .kpi-sub");
  const varianceCard = document.querySelector("#kpiVariance .kpi-sub");
  const unmatchedCard = document.querySelector("#kpiUnmatched .kpi-sub");
  if (totalCard) totalCard.textContent = pdfInvoiceCount ? `${pdfInvoiceCount} 张发票` : (skippedEmployeeDrilldown ? "总额已核对" : `PDF ${pdfCount} 人`);
  if (matchedCard) matchedCard.textContent = excelRecordCount ? `整批账单 ${excelRecordCount} 行` : (skippedEmployeeDrilldown ? "无需查看员工明细" : `Excel ${excelCount} 人`);
  if (varianceCard) varianceCard.textContent = `容差 ${currencySymbol}0.10`;
  if (unmatchedCard) unmatchedCard.textContent = reviewWarehouses.length ? `待确认仓库 ${reviewWarehouses.join("、")}` : (clearedCount ? `${clearedCount} 人已清账` : "待确认项目");
}

function renderConclusion(summary, wcSummary, extractionQuality, run = {}, presentationContract = null) {
  const section = labor.conclusionSection;
  if (!section) return;

  const conclusion = buildBusinessConclusion(summary, wcSummary, run);

  const amountDeltaTotal = Number(wcSummary?.amountDeltaTotal ?? summary?.amountDeltaTotal ?? 0);
  const pdfAmountTotal = Math.abs(Number(wcSummary?.pdfAmountTotal ?? summary?.pdfAmountTotal ?? 0));
  const excelAmountTotal = Math.abs(Number(wcSummary?.excelAmountTotal ?? summary?.excelAmountTotal ?? 0));
  const detailPdfAmountTotal = Math.abs(Number(summary?.pdfAmountTotal || 0));
  const detailExcelAmountTotal = Math.abs(Number(summary?.excelAmountTotal || 0));
  const maxAmount = Math.max(pdfAmountTotal, excelAmountTotal, 1);
  const amountDeltaPct = ((Math.abs(amountDeltaTotal) / maxAmount) * 100).toFixed(2);

  const presentation = presentationContract || laborPresentationContract(run);
  const reviewEmployeeCount = Number(presentation.summary?.employeeCount || 0);
  const excelRecordCount = Number(presentation.summary?.excelRecordCount || reviewEmployeeCount);
  const notInInvoice = Number(presentation.summary?.notInInvoiceEmployeeCount || 0);
  const reviewWarehouses = normalizeReviewWarehouses(wcSummary?.diffWarehouses);
  const scopeText = reviewWarehouses.length
    ? `待确认仓库：${reviewWarehouses.join("、")}；当前展示待确认员工明细 ${reviewEmployeeCount} 人，不是整批账单人数。`
    : `账单员工/记录数 ${reviewEmployeeCount}${notInInvoice > 0 ? `，${notInInvoice} 人不在本批发票` : ""}`;

  section.hidden = false;
  section.className = `conclusion-section ${conclusion.level}`;
  section.innerHTML = `
    <div class="conclusion-main">
      <span class="conclusion-icon" aria-hidden="true"></span>
      <span class="conclusion-text">${escapeHtml(conclusion.title)}</span>
    </div>
    <div class="conclusion-details">
      <p class="conclusion-detail conclusion-detail--summary">${escapeHtml(conclusion.message)}</p>
      <p class="conclusion-detail conclusion-detail--metric"><span>总金额差异</span><strong>${formatSignedMoney(amountDeltaTotal)} (${amountDeltaPct}%)</strong></p>
      <p class="conclusion-detail">${escapeHtml(scopeText)}</p>
      <p class="conclusion-detail">${escapeHtml(conclusion.detailMessage)}</p>
      <p class="conclusion-detail conclusion-detail--explanation"><strong>总金额核对：</strong>总账结论优先看整批 PDF 与整批 Excel 的差额。整批 PDF ${formatMoney(pdfAmountTotal)}，整批 Excel ${formatMoney(excelAmountTotal)}；已识别员工明细金额 PDF ${formatMoney(detailPdfAmountTotal)}，Excel ${formatMoney(detailExcelAmountTotal)}。员工明细金额用于定位差异，不等同于整批总账金额；如果员工明细金额小于整批总额，不代表账单少读了，只代表当前页面只展开了用于确认的明细范围。</p>
    </div>
    ${buildBusinessReportPrompt(run)}
  `;
}

function buildBusinessConclusion(summary, wcSummary, run) {
  const guard = run?.batchGuard || {};
  const unresolvedFiles = Array.isArray(guard.unresolvedFiles) ? guard.unresolvedFiles : [];
  if (guard.status === "pdf_recognition_incomplete") {
    return {
      level: "critical",
      title: "PDF 识别未完成",
      message: guard.message || "PDF 已检测到员工或金额证据，但正式金额未生成。",
      detailMessage: "本次属于识别异常，不是业务差异。请修复识别结果后重新生成核对报告。",
    };
  }
  if (guard.status === "currency_review") {
    return {
      level: "warning",
      title: "发票币种待确认",
      message: guard.message || "批次币种与发票识别币种不一致。",
      detailMessage: "已核对结果可以查看，但币种确认前不能直接放行。",
    };
  }
  if (guard.status === "partial_review") {
    return {
      level: "warning",
      title: "部分核对完成",
      message: `已完成可确认发票的核对；仍有 ${unresolvedFiles.length} 张发票待确认。`,
      detailMessage: "已核对仓库结果可以查看，但本批次不能直接放行。",
    };
  }
  if (guard.status === "amount_scope_review") {
    return {
      level: "warning",
      title: "金额口径待确认",
      message: guard.message || "Excel 金额字段未明确含税或不含税口径。",
      detailMessage: "确认核对口径前，本批次不能直接放行。",
    };
  }
  const amountDeltaTotal = Number(wcSummary?.amountDeltaTotal ?? summary?.amountDeltaTotal ?? 0);
  const totalPassed = isLaborTotalAmountPassed(summary, wcSummary);
  const presentation = laborPresentationContract(run);
  const rows = presentation.employeeRows;
  const presentationSummary = presentation.summary;
  const reviewQueues = run?.reviewQueues || {};
  const reviewWarehouses = normalizeReviewWarehouses(wcSummary?.diffWarehouses);
  const detailIssueCount =
    Number(presentationSummary?.reviewItemCount || 0) +
    reviewWarehouses.length +
    Number(reviewQueues?.employeeExceptions?.count || 0) +
    Number(reviewQueues?.nameMapping?.count || 0) +
    Number(reviewQueues?.combinedPdfRows?.count || 0);
  const hasUploadedTotals =
    Number(summary?.pdfEmployeeCount || 0) > 0 ||
    Number(summary?.excelEmployeeCount || 0) > 0 ||
    Math.abs(Number(summary?.pdfAmountTotal || wcSummary?.pdfAmountTotal || 0)) > 0 ||
    Math.abs(Number(summary?.excelAmountTotal || wcSummary?.excelAmountTotal || 0)) > 0;
  const detailRowsIncomplete = !rows.length && hasUploadedTotals;
  const detailNeedsConfirmation = detailRowsIncomplete || detailIssueCount > 0 || (reviewQueues?.primary && reviewQueues.primary !== "cleared");
  const direction = amountDeltaTotal >= 0 ? "PDF 比 Excel 多" : "PDF 比 Excel 少";
  const amountText = `${direction} ${formatMoney(Math.abs(amountDeltaTotal))}`;
  const employeeCount = Number(presentationSummary?.employeeCount || 0);
  const excelRecordCount = Number(presentationSummary?.excelRecordCount || employeeCount);
  const detailScope = `整批账单已读取 ${excelRecordCount || employeeCount} 行；下面只展示需要确认的员工明细，不代表账单只有这些人。`;
  const detailConfirmationMessage = detailRowsIncomplete
    ? "系统已确认本批总金额一致，但部分员工明细未完整识别，员工级差异仅供确认，不能直接作为最终员工明细结论。"
    : "系统已确认本批总金额一致，但员工明细仍有需要确认的项目。";

  if (!totalPassed) {
    return {
      level: "critical",
      title: "总金额存在差异，暂不能放行",
      message: `总金额存在差异：${amountText}。`,
      detailMessage: detailRowsIncomplete
        ? "由于员工明细未完整识别，系统暂时无法定位全部差异来源。"
        : "请先查看下方员工明细中的金额、工时或费率差异。",
    };
  }

  if (detailNeedsConfirmation) {
    return {
      level: "warning",
      title: "总账通过，但员工明细待确认",
      message: detailConfirmationMessage,
      detailMessage: detailRowsIncomplete
        ? detailScope
        : `${detailScope} 员工级差异仅供确认，不能直接作为最终员工明细结论。`,
    };
  }

  return {
    level: "pass",
    title: "总账通过",
    message: "PDF 发票总额与 Excel 账单总额一致，本批可按当前结果留档。",
    detailMessage: "员工明细未发现需要业务确认的异常。",
  };
}

function buildBusinessReportPrompt(run) {
  const businessUrl = preferredLaborReportDownloadUrl(run);
  if (!businessUrl) return "";
  const internalExcelUrl = run?.diffDownloadUrl || run?.files?.diffReport?.downloadUrl || "";
  const excelLink = internalExcelUrl && internalExcelUrl !== businessUrl
    ? `<a href="${escapeHtml(internalExcelUrl)}" download>下载 Excel 明细</a>`
    : "";
  return `
    <div class="conclusion-report-actions">
      <span><strong>业务报告已生成，可下载留档或转发给业务确认。</strong></span>
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
    : `<p class="readiness-clear">当前结果可用于业务确认和留档。</p>`;

  section.insertAdjacentHTML(
    "beforeend",
    `<div class="readiness-gate ${statusClass}">
      <div class="readiness-head">
        <span class="readiness-pill">${escapeHtml(readinessGate.label || "需确认")}</span>
        <span>结果确认提示 · 需先处理 ${summary.blockedCount || 0} 项 · 待确认 ${summary.reviewCount || 0} 项</span>
      </div>
      ${issueHtml}
    </div>`
  );
}

function renderAutoFixSummary(rows) {
  const section = labor.autoFixSection;
  const body = labor.autoFixBody;
  if (!section || !body) return;

  const autoFixedRows = (rows || []).filter(isAutoFixedNameRow);
  if (!autoFixedRows.length) {
    section.hidden = true;
    body.innerHTML = "";
    return;
  }

  section.hidden = false;
  const visible = autoFixedRows.slice(0, 6);
  const cards = visible
    .map((row) => {
      const names = splitMatchedName(row.employeeName || "");
      return `<div class="pending-detail-item">
        <strong>${escapeHtml(names.left || row.employeeName || "-")} ⇄ ${escapeHtml(names.right || row.employeeName || "-")}</strong>
        <span>系统已自动合并姓名格式差异</span>
        <span>PDF ${formatMoney(row.pdfAmountTotal || 0)} / Excel ${formatMoney(row.excelAmountTotal || 0)}</span>
        <b>自动修正仅处理大小写、重音符号、标点、空格或前后顺序差异。</b>
      </div>`;
    })
    .join("");
  const more = autoFixedRows.length > visible.length
    ? `<p class="table-note">其余 ${autoFixedRows.length - visible.length} 条自动修正已收起，可在下方完整员工明细中查看。</p>`
    : "";
  body.innerHTML = `<div class="pending-detail-list">${cards}</div>${more}`;
}

function isAutoFixedNameRow(row) {
  const flags = Array.isArray(row?.riskFlags) ? row.riskFlags : [];
  const passed = row?.matchStatus === "通过" || row?.matchStatus === "金额一致";
  return passed && flags.some((flag) => {
    const text = String(flag);
    return text.includes("姓名格式差异自动合并") || text.includes("疑似姓名匹配");
  });
}

function splitMatchedName(name) {
  const raw = String(name || "");
  if (raw.includes("⇄")) {
    const [left, right] = raw.split("⇄");
    return { left: left.trim(), right: right.trim() };
  }
  if (raw.includes("→")) {
    const [left, right] = raw.split("→");
    return { left: left.trim(), right: right.trim() };
  }
  return { left: raw.trim(), right: "" };
}

function laborEmployeeComparisonRows(rows) {
  const valueFields = ["pdfAmountTotal", "excelAmountTotal", "pdfHoursTotal", "excelHoursTotal"];
  return (Array.isArray(rows) ? rows : []).filter((row) =>
    valueFields.some((field) => Math.abs(Number(row?.[field] || 0)) > 0.005)
  );
}

function laborPresentationContract(run = {}) {
  const presentation = run?.presentation;
  if (
    presentation?.schemaVersion === 1
    && Array.isArray(presentation.employeeRows)
    && Array.isArray(presentation.candidateMatches)
    && presentation.summary
  ) {
    return presentation;
  }

  const employeeRows = laborEmployeeComparisonRows(run?.comparisonRows);
  const candidateMatches = Array.isArray(run?.candidateMatches) ? run.candidateMatches : [];
  const differenceRows = employeeRows.filter(
    (row) => row.matchStatus !== "通过" && row.matchStatus !== "金额一致"
  );
  const passedEmployeeCount = employeeRows.length - differenceRows.length;
  const excelRecordCount = Array.isArray(run?.excelRows)
    ? run.excelRows.length
    : Number(run?.comparisonSummary?.excelEmployeeCount || employeeRows.length);
  return {
    schemaVersion: 0,
    employeeRows,
    candidateMatches,
    summary: {
      employeeCount: employeeRows.length,
      differenceEmployeeCount: differenceRows.length,
      passedEmployeeCount,
      amountDiffEmployeeCount: differenceRows.filter((row) => row.matchStatus === "金额差异").length,
      hoursDiffEmployeeCount: differenceRows.filter((row) =>
        row.matchStatus === "工时不一致" || (row.riskFlags || []).includes("工时需复核")
      ).length,
      notInInvoiceEmployeeCount: differenceRows.filter((row) =>
        row.matchStatus === "PDF有Excel无" || row.matchStatus === "Excel有PDF无"
      ).length,
      candidateMatchCount: candidateMatches.length,
      reviewItemCount: differenceRows.length + candidateMatches.length,
      amountImpact: differenceRows.reduce((sum, row) => sum + Math.abs(Number(row.amountDelta || 0)), 0),
      hoursImpact: differenceRows.reduce((sum, row) => sum + Math.abs(Number(row.hoursDelta || 0)), 0),
      excelRecordCount,
      sourceComparisonRowCount: Array.isArray(run?.comparisonRows) ? run.comparisonRows.length : 0,
      excludedNonEmployeeRowCount: Math.max(
        (Array.isArray(run?.comparisonRows) ? run.comparisonRows.length : 0) - employeeRows.length,
        0
      ),
    },
  };
}

function renderEmployeeReconTable(rows, summary, totalPassed, wcSummary, presentationSummary = {}) {
  const section = labor.employeeReconSection;
  const container = labor.employeeReconTable;
  const currencySymbol = laborCurrencySymbol();
  const employeeRows = Array.isArray(rows) ? rows : [];
  if (!section || !container) return;

  // 总额通过且无员工明细时，显示通过证据
  if (totalPassed && !employeeRows.length) {
    section.hidden = false;
    renderPassEvidence(container, summary, wcSummary);
    return;
  }

  if (!employeeRows.length) {
    section.hidden = true;
    return;
  }
  section.hidden = false;
  const title = section.querySelector(".section-title");
  const subtitle = section.querySelector(".section-sub");
  const reviewWarehouses = normalizeReviewWarehouses(wcSummary?.diffWarehouses);
  if (title) title.textContent = reviewWarehouses.length ? "待确认员工明细" : "员工对账明细";
  if (subtitle) {
    subtitle.textContent = reviewWarehouses.length
      ? `只展示需要确认的员工明细，不代表账单只有这些人。待确认仓库：${reviewWarehouses.join("、")}`
      : "金额或工时有差异的排在前面";
  }

  // 员工核对表只展示真实核对行；姓名候选在上方待确认区单独展示。
  const allRows = [];
  employeeRows.forEach(r => {
    const delta = Math.abs(r.amountDelta || 0);
    const hasVariance = r.matchStatus !== "通过" && r.matchStatus !== "金额一致";
    allRows.push({
      name: r.employeeName || "",
      status: laborBusinessStatusLabel(r.matchStatus, r),
      pdfAmount: r.pdfAmountTotal || 0,
      excelAmount: r.excelAmountTotal || 0,
      amountDelta: r.amountDelta || 0,
      pdfHours: r.pdfHoursTotal || 0,
      excelHours: r.excelHoursTotal || 0,
      hoursDelta: r.hoursDelta || 0,
      hasVariance,
      sortWeight: hasVariance ? delta : -1,
    });
  });

  // 排序：有差异的在前（按差异绝对值降序），无差异在后
  allRows.sort((a, b) => b.sortWeight - a.sortWeight);

  const varianceRows = allRows.filter(r => r.hasVariance);
  const varianceCount = Number(presentationSummary?.differenceEmployeeCount ?? varianceRows.length);
  const totalCount = Number(presentationSummary?.employeeCount ?? allRows.length);
  const passedCount = Number(presentationSummary?.passedEmployeeCount ?? (totalCount - varianceCount));
  const amountImpact = Number(
    presentationSummary?.amountImpact
      ?? varianceRows.reduce((sum, row) => sum + Math.abs(Number(row.amountDelta || 0)), 0)
  );
  const hoursImpact = Number(
    presentationSummary?.hoursImpact
      ?? varianceRows.reduce((sum, row) => sum + Math.abs(Number(row.hoursDelta || 0)), 0)
  );

  const headers = ["员工", "状态", "PDF金额", "Excel金额", "差异", "PDF工时", "Excel工时", "工时差异"];
  const thead = `<thead><tr>${headers.map(h => `<th>${h}</th>`).join("")}</tr></thead>`;
  const visible = allRows;

  const tbody = visible.map(r => {
    const rowClass = r.hasVariance ? "recon-row variance" : "recon-row matched";
    const statusStyle = r.hasVariance ? "color:#FF3B30;font-weight:600" : "color:#34C759";
    const deltaStyle = Math.abs(r.amountDelta) > 0.01
      ? (r.amountDelta > 0 ? "color:#FF9500" : "color:#FF3B30")
      : "color:#8E8E93";
    return `<tr class="${rowClass}">
      <td>${escapeHtml(r.name)}</td>
      <td style="${statusStyle}">${escapeHtml(r.status)}</td>
      <td>${currencySymbol}${formatMoney(r.pdfAmount)}</td>
      <td>${currencySymbol}${formatMoney(r.excelAmount)}</td>
      <td style="${deltaStyle}">${r.amountDelta >= 0 ? "+" : ""}${currencySymbol}${formatMoney(Math.abs(r.amountDelta))}</td>
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
      <div class="recon-focus-card"><span>完整明细</span><strong>页面已展示</strong></div>
    </div>
    <table>${thead}<tbody>${tbody}</tbody></table>
  `;
}

function laborBusinessStatusLabel(status, row = {}) {
  const raw = String(status || "").trim();
  const flags = Array.isArray(row?.riskFlags) ? row.riskFlags.map(String) : [];
  if (raw === "金额差异" && row?.amountDifferenceReasonCode === "excel_amount_component_delta") {
    return "Excel含额外费用项";
  }
  if ((raw === "通过" || raw === "金额一致") && flags.some((flag) => flag.includes("姓名格式差异自动合并"))) {
    return "系统已自动修正";
  }
  const labels = {
    "通过": "一致",
    "金额一致": "一致",
    "金额差异": "金额不一致",
    "工时不一致": "工时待确认",
    ["工时" + "需" + "复核"]: "工时待确认",
    "PDF有Excel无": "发票有账单无",
    "Excel有PDF无": "账单有发票无",
    ["低" + "置信度" + "抽取"]: "明细识别不完整",
    "疑似姓名匹配": "疑似同一员工",
    "姓名模糊匹配": "疑似同一员工",
    "疑似PDF合并员工": "疑似一行包含多名员工",
    "疑似一行包含多名员工": "疑似一行包含多名员工",
  };
  return labels[raw] || raw.replaceAll("_", " ");
}

function renderPassEvidence(container, summary, wcSummary) {
  const currencySymbol = laborCurrencySymbol();
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
        <p>系统已先核对 PDF 发票总额与 Excel 账单总额。差额未超过 ${currencySymbol}0.10，因此无需进入员工级逐项追差；如需留档，可下载完整报告。</p>
      </div>
      <div class="pass-evidence-grid">
        <div>
          <span>PDF 发票总额</span>
          <strong>${currencySymbol}${formatMoney(pdfAmount)}</strong>
          <small>${pdfCount} 人</small>
        </div>
        <div>
          <span>Excel 账单总额</span>
          <strong>${currencySymbol}${formatMoney(excelAmount)}</strong>
          <small>${excelCount} 人</small>
        </div>
        <div>
          <span>金额差额</span>
          <strong>${amountDelta >= 0 ? "+" : "-"}${currencySymbol}${formatMoney(Math.abs(amountDelta))}</strong>
          <small>容差 ${currencySymbol}0.10</small>
        </div>
      </div>
    </div>
  `;
}

function renderWarehouseTable(wc) {
  const section = labor.warehouseSection;
  const heading = labor.warehouseHeading;
  const table = labor.warehouseTable;
  const currencySymbol = laborCurrencySymbol();
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
      <td>${currencySymbol}${r.pdfAmountTotal.toFixed(2)}</td>
      <td>${currencySymbol}${r.excelAmountTotal.toFixed(2)}</td>
      <td>${r.amountDelta >= 0 ? "+" : ""}${currencySymbol}${r.amountDelta.toFixed(2)}</td>
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
    if (actionLabel) actionLabel.textContent = "查看处理建议";
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
      const componentExplained = row.amountDifferenceReasonCode === "excel_amount_component_delta"
        && Boolean(row.amountDifferenceExplanation);
      return {
        ...row,
        reviewFocus: componentExplained ? "先核 Excel 额外费用项" : hoursAligned ? "先核金额计算方式" : "先核工时范围",
        amountDirectionLabel: amountDelta > 0 ? "PDF 高于 Excel" : amountDelta < 0 ? "PDF 少于 Excel" : "金额一致",
        hoursDirectionLabel: hoursAligned ? "工时一致" : hoursDelta > 0 ? "PDF 工时多于 Excel" : "PDF 工时少于 Excel",
        businessQuestion: row.amountDifferenceExplanation || (hoursAligned
          ? `PDF 与 Excel 工时一致，金额差 ${formatSignedMoney(amountDelta)}；请确认费率、加班、服务费或税费是否同一口径。`
          : `PDF 与 Excel 工时差 ${formatSignedNumber(hoursDelta)}，金额差 ${formatSignedMoney(amountDelta)}；请先确认账期、日期行和加班工时。`),
        recommendation: componentExplained
          ? "确认 Excel 额外费用项是否应包含在本批发票中；确认前不能自动清账。"
          : hoursAligned
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
  const componentExplainedCount = amountRateRows.filter(
    (row) => row.amountDifferenceReasonCode === "excel_amount_component_delta"
  ).length;
  const allAmountRowsComponentExplained = amountRateRows.length > 0 && componentExplainedCount === amountRateRows.length;
  const primary = reviewQueues?.primary || "";
  const primaryLabel =
    primary === "amount_rate_review" || amountRateRows.length >= Math.max(hoursDiffRows.length, candidateMatches.length, notInInvoiceRows.length)
      ? allAmountRowsComponentExplained ? "先确认 Excel 额外费用项是否应开票" : "先确认金额计算口径"
      : notInInvoiceRows.length >= Math.max(hoursDiffRows.length, candidateMatches.length)
      ? "先确认是否属于本批发票"
      : hoursDiffRows.length
      ? "先核对工时口径"
      : "先确认疑似同一员工";
  return `<div class="pending-overview-grid">
    <div>
      <span>待确认总数</span>
      <strong>${escapeHtml(totalCount)} 项</strong>
      <p>${escapeHtml(primaryLabel)}</p>
    </div>
    <div>
      <span>${allAmountRowsComponentExplained ? "额外费用项待确认" : "金额计算待确认"}</span>
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
      <span>疑似同一员工</span>
      <strong>${escapeHtml(candidateMatches.length)} 条</strong>
      <p>确认前不会自动合并姓名</p>
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
  if (actionEl) actionEl.textContent = "查看处理建议";

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
      if (actionEl) actionEl.textContent = expanded ? "查看处理建议" : "收起";
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
  const amountDifferenceComponents = type === "amountRate"
    ? items.flatMap((row) => Array.isArray(row.amountDifferenceComponents) ? row.amountDifferenceComponents : [])
    : [];
  const componentNotes = [...new Set(amountDifferenceComponents.map((item) => item.note).filter(Boolean))];
  const componentTotal = amountDifferenceComponents.reduce((sum, item) => sum + Math.abs(Number(item.amount || 0)), 0);
  const stats =
    type === "candidate"
      ? [
          `建议 ${items.length} 条`,
          `平均相似度 ${formatPercent(items.reduce((sum, row) => sum + Number(row.nameSimilarity || 0), 0) / items.length)}`,
        ]
      : type === "amountRate" && amountDifferenceComponents.length
      ? [`Excel额外费用 ${formatMoney(componentTotal)}`, `${componentNotes[0] || "金额组成"} · ${items.length}人`]
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
        <span>${escapeHtml(row.reviewFocus || "核对金额计算方式")} · ${escapeHtml(row.amountDirectionLabel || "")}</span>
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
        <b>处理：核对账期、日期和工时；差异 ${formatHours(row.hoursDelta)}h</b>
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
        <b>建议：${escapeHtml(row.recommendation || "业务确认是否同一人，确认前不会自动合并姓名。")}</b>
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
        <b>处理：确认本员工是否属于本批发票</b>
      </div>`
    )
    .join("")}</div>${renderPendingLimitNote(rows.length, visible.length)}`;
}

function renderPendingLimitNote(total, visible) {
  return total > visible ? `<p class="table-note">这里只展示前 ${visible} 条，完整名单请下载报告。</p>` : "";
}

function renderQualityAlert(quality, diagnostics, run = {}) {
  if (!labor.qualityAlert) return;
  quality = quality || {};
  const hasQualityIssue = quality && quality.level && quality.level !== "ok";
  const hasDiagnosticIssue = diagnostics && diagnostics.level && diagnostics.level !== "ok";
  const pageAuditSummary = run.pdfPageAuditSummary || {};
  const pageAudit = Array.isArray(run.pdfPageAudit) ? run.pdfPageAudit : [];
  const hasPageAuditIssue = Boolean(
    Number(pageAuditSummary.zeroRowPageCount || 0) ||
      Number(pageAuditSummary.failedPageCount || 0) ||
      Number(pageAuditSummary.highResolutionRetryPageCount || 0)
  );
  if (!hasQualityIssue && !hasDiagnosticIssue && !hasPageAuditIssue) {
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
  const alertLevel = _higherSeverity(_higherSeverity(quality.level, diagnostics && diagnostics.level), hasPageAuditIssue ? "warning" : "");
  const severityLabel = alertLevel === "critical" ? "必须确认" : "建议确认";
  const severityTitle =
    (hasDiagnosticIssue && diagnostics && diagnostics.message) ||
    quality.message ||
    (alertLevel === "critical" ? "明细识别存在严重问题。" : "明细识别需要关注。");
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
    : amountDelta > LABOR_TOTAL_AMOUNT_TOLERANCE
    ? "总金额存在差异，先看差异仓库，再确认员工明细。"
    : "总金额在容差内，当前只需抽样确认员工明细。";
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

  // Detail recognition completeness.
  if (confidence.average !== undefined) {
    detailsHtml += `
      <div class="quality-detail-section">
        <h4>明细识别完整度</h4>
        <div class="quality-metrics">
          <span><em>整体识别</em><strong>${(confidence.average * 100).toFixed(1)}%</strong></span>
          <span><em>需确认明细</em><strong>${confidence.lowCount || 0} 条</strong></span>
          <span><em>无法确认明细</em><strong>${confidence.veryLowCount || 0} 条</strong></span>
        </div>
      </div>
    `;
  }

  // Recognition source summary.
  if (Object.keys(methods).length > 0) {
    detailsHtml += `
      <div class="quality-detail-section">
        <h4>识别来源</h4>
        <div class="quality-metrics">
          <span><em>本地识别</em><strong>${methods.rule || 0}</strong></span>
          <span><em>文本增强</em><strong>${methods.ai_text || 0}</strong></span>
          <span><em>图片增强</em><strong>${methods.ai_image || 0}</strong></span>
        </div>
      </div>
    `;
  }

  if (pageAuditSummary.pageCount) {
    const problemPages = pageAudit
      .filter((row) => {
        const status = String(row.status || "");
        return Number(row.rowCount || 0) === 0 || status.includes("failed") || status.startsWith("high_res_retry");
      })
      .slice(0, 8);
    detailsHtml += `
      <div class="quality-detail-section">
        <h4>页面识别检查</h4>
        <div class="quality-metrics">
          <span><em>已检查页面</em><strong>${Number(pageAuditSummary.pageCount || 0)} 页</strong></span>
          <span><em>空结果页面</em><strong>${Number(pageAuditSummary.zeroRowPageCount || 0)} 页</strong></span>
          <span><em>高清补识别</em><strong>${Number(pageAuditSummary.highResolutionRetryPageCount || 0)} 页</strong></span>
          <span><em>识别失败</em><strong>${Number(pageAuditSummary.failedPageCount || 0)} 页</strong></span>
        </div>
        ${
          problemPages.length
            ? `<ul>${problemPages
                .map((row) => `<li>${escapeHtml(_pdfPageAuditText(row))}</li>`)
                .join("")}</ul>`
            : ""
        }
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
        <small>${signals.fastPdfTotal !== undefined ? "发票与账单" : `工时差异 ${formatHours(hoursDelta)}h`}</small>
      </div>
    </div>
    <div class="quality-workflow">
      <section class="quality-focus-card">
        <span class="focus-index">01</span>
        <div>
          <h4>优先确认</h4>
          <p>${escapeHtml(primaryFocus)}</p>
          ${
            secondaryFocus.length
              ? `<ul>${secondaryFocus.map((issue) => `<li>${escapeHtml(issue)}</li>`).join("")}</ul>`
              : ""
          }
        </div>
      </section>
      <section class="quality-ledger-card">
        <h4>当前总金额</h4>
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
      <div><span>明细识别</span><strong>${Number(methods.rule || 0) + Number(methods.ai_text || 0) + Number(methods.ai_image || 0)} 条</strong></div>
      <div><span>识别完整度</span><strong>${confidence.average === undefined ? "—" : `${(confidence.average * 100).toFixed(1)}%`}</strong></div>
    </div>
    ${detailsHtml ? `<details class="quality-diagnostics"><summary>识别情况明细</summary><div class="quality-details">${detailsHtml}</div></details>` : ""}
  `;
}

function _pdfPageAuditText(row) {
  const file = row.sourceFile || "PDF";
  const page = row.page ? `第 ${row.page} 页` : "页码未知";
  const status = String(row.status || "");
  const rowCount = Number(row.rowCount || 0);
  let statusText = "已识别";
  if (status === "high_res_retry_applied") statusText = "低清未识别，已用高清补识别";
  else if (status === "high_res_retry_no_rows") statusText = "高清补识别后仍未识别到员工明细";
  else if (status.includes("failed")) statusText = "识别失败";
  else if (rowCount === 0) statusText = "未识别到员工明细";
  return `${file} ${page}：${statusText}${rowCount ? `，识别 ${rowCount} 条` : ""}`;
}

function _qualityNextStepText(quality, warehouseIssues, totals, diagnostics) {
  if (diagnostics && diagnostics.level && diagnostics.level !== "ok" && diagnostics.nextStep) return diagnostics.nextStep;
  const amountDelta = Math.abs(totals.amountDelta || 0);
  if (warehouseIssues && warehouseIssues.length) {
    return `系统发现 ${warehouseIssues.length} 个仓库需要确认。先看仓库金额，再进入员工明细定位差异。`;
  }
  if (amountDelta <= LABOR_TOTAL_AMOUNT_TOLERANCE && quality.level !== "critical") {
    return "总金额已在容差内，当前只是明细识别提示；可下载报告留档。";
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
        <p class="empty-title">暂无识别证据</p>
        <p class="empty-desc">点击「生成核对报告」开始核对</p>
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
      <div><span>已识别发票明细</span><strong>${rows.length}</strong></div>
      <div><span>待确认明细</span><strong>${lowConfidenceRows.length}</strong></div>
      <div><span>识别金额合计</span><strong>${formatMoney(totalAmount)}</strong></div>
      <div><span>识别工时合计</span><strong>${formatHours(totalHours)}</strong></div>
    </div>
    <table><thead><tr><th>员工</th><th>工号</th><th>工时</th><th>金额</th><th>识别完整度</th><th>来源位置</th><th>原文依据</th></tr></thead><tbody>${focusRows
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
      ? `<p class="table-note">本区是识别证据概览，不作为最终员工核对结论；优先展示待确认和高金额明细 ${focusRows.length} 条，下方完整员工明细会展示全部 ${rows.length} 条核对结果。</p>`
      : `<p class="table-note">本区是识别证据概览，不作为最终员工核对结论；最终结论请看下方完整员工明细。</p>`
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
  const method = String(options.method || "GET").toUpperCase();
  const mutation = ["POST", "PUT", "PATCH", "DELETE"].includes(method);
  if (mutation) {
    const headers = new Headers(options.headers || {});
    headers.set("X-Sigma-Labor-API-Contract", String(LABOR_UI_API_CONTRACT_VERSION));
    headers.set("X-Sigma-Labor-UI-Version", LABOR_UI_MODULE_VERSION);
    headers.set("X-Sigma-Labor-UI-Build", String(laborState.moduleAccess?.build?.buildId || ""));
    options = { ...options, headers };
  }
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
  const errorCode = String(message?.errorCode || "").trim();
  const text = [detailMessage, nextAction].filter(Boolean).join(" ").trim();
  if (errorCode && typeof message === "object") return text || "请求失败，请按提示重试。";
  if (/No such file|ENOENT|FileNotFoundError|\/tmp\/sigma-workbench|\/labor_runs\/|文件不存在|文件已被清理/i.test(text)) {
    return "系统找不到本批次文件。请重新上传 PDF 发票和 Excel 账单后再生成核对报告；如果在 UAT/Vercel 环境，请改用本地或内网持久化环境。";
  }
  if (/批次不存在|run.*not found|not found/i.test(text)) {
    return "本批次记录未找到。请返回「新建核对批次」重新创建并上传材料；如果刚上传过文件，请确认当前环境是否支持持久化保存。";
  }
  if (/JSON|Unexpected token|返回内容异常|invalid response/i.test(text)) {
    return "服务返回内容异常。请刷新页面后重试；若仍失败，请联系管理员查看本批次日志。";
  }
  if (/上传|upload|文件|file|持久化|保存/.test(text)) {
    return "上传文件未保存成功。请重新上传 PDF 发票和 Excel 账单；若仍失败，请改用本地/内网持久化环境处理。";
  }
  if (/Failed to fetch|NetworkError|Load failed|无法连接|连接失败/i.test(text)) {
    return "无法连接当前服务。请确认本地服务已启动并刷新页面；若在 UAT 环境，请联系管理员检查服务状态。";
  }
  if (/Traceback|Errno|Exception|\/tmp\/|\/var\/|\/Users\//i.test(text)) {
    return "核对报告生成失败。请检查材料是否已上传完整，并重新点击「生成核对报告」；若仍失败，请把当前批次号发给管理员。";
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

function laborCurrencySymbol(run = laborState.run) {
  const detected = Array.isArray(run?.batchGuard?.detectedCurrencies)
    ? run.batchGuard.detectedCurrencies.filter(Boolean)
    : [];
  const code = String(detected.length === 1 ? detected[0] : run?.currency || "USD").trim().toUpperCase();
  const symbols = { USD: "$", EUR: "€", CNY: "¥", GBP: "£" };
  return symbols[code] || `${code} `;
}

function formatSignedMoney(value) {
  const number = Number(value || 0);
  const currencySymbol = laborCurrencySymbol();
  if (number === 0) return `${currencySymbol}0.00`;
  return `${number > 0 ? "+" : "-"}${currencySymbol}${formatMoney(Math.abs(number))}`;
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
    low_confidence: "明细识别不完整",
    low_confidence_extraction: "明细识别不完整",
    name_mapping_candidate: "疑似同名员工",
    profile_candidate: "供应商格式建议",
    cross_warehouse_allocation: "跨仓归属待确认",
    cross_warehouse_employee_allocation: "跨仓归属待确认",
  };
  return labels[String(reason || "").trim()] || String(reason || "待确认").replaceAll("_", " ");
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
