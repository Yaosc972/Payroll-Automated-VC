/**
 * FBU美洲绩效奖金核算 - 数据看板交互逻辑
 */

// ═══ State ═══

const state = {
  currentPage: 'activities',
  currentActivity: null,
  activities: [],
  attendanceData: null,
  salaryData: null,
  performanceData: null,
  adjustmentData: null,
  diagnosticsData: null,
  resultsData: null,
  baseRoster: null,
  lastImportResult: null,
  foundationRunDetails: {},
  foundationLoadingRunId: '',
  activityListLoadingRunIds: new Set(),
  tableFilters: {
    attendance: {},
    salary: {},
    performance: {},
    results: {},
    exceptions: {},
  },
  tablePagination: {
    attendance: { page: 1, pageSize: 50 },
    salary: { page: 1, pageSize: 50 },
    performance: { page: 1, pageSize: 50 },
    results: { page: 1, pageSize: 50 },
    exceptions: { page: 1, pageSize: 50 },
  },
};

// ═══ API Base ═══

const API_BASE = '/api/fbu-performance';
const TABLE_PAGE_SIZE_OPTIONS = [25, 50, 100, 200];
const DEFAULT_TABLE_PAGE_SIZE = 50;

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function formatJobType(jobType) {
  if (jobType === 'district_manager') return '区长';
  if (jobType === 'functional') return '职能';
  return '仓库';
}

function toNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function formatCurrency(value, decimals = 2) {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(toNumber(value));
}

function formatPercent(value) {
  return `${(toNumber(value) * 100).toFixed(1)}%`;
}

function formatCoefficient(value) {
  return toNumber(value).toFixed(2);
}

function formatHours(value) {
  return `${toNumber(value).toFixed(2)}h`;
}

function formatFileSize(bytes) {
  const size = Number(bytes);
  if (!Number.isFinite(size) || size <= 0) return '-';
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(2)} MB`;
}

function formatDateTime(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '-';
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatDateOnly(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '-';
  return date.toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  });
}

function formatResultJobType(jobType) {
  const label = formatJobType(jobType);
  const className = jobType === 'functional'
    ? 'functional'
    : jobType === 'district_manager'
      ? 'district'
      : '';
  return `<span class="job-pill ${className}">${escapeHtml(label)}</span>`;
}

function formatJsArg(value) {
  return JSON.stringify(String(value ?? ''))
    .replaceAll('&', '\\u0026')
    .replaceAll('<', '\\u003C')
    .replaceAll('>', '\\u003E')
    .replaceAll('"', '&quot;');
}

function getTableFilter(type) {
  if (!state.tableFilters[type]) state.tableFilters[type] = {};
  return state.tableFilters[type];
}

function getTablePagination(type) {
  if (!state.tablePagination[type]) {
    state.tablePagination[type] = { page: 1, pageSize: DEFAULT_TABLE_PAGE_SIZE };
  }
  return state.tablePagination[type];
}

function resetTableControls(type = null) {
  const types = type ? [type] : Object.keys(state.tablePagination);
  types.forEach(tableType => {
    state.tableFilters[tableType] = {};
    state.tablePagination[tableType] = { page: 1, pageSize: DEFAULT_TABLE_PAGE_SIZE };
  });
}

function normalizeSearch(value) {
  return String(value ?? '').trim().toLowerCase();
}

function matchesEmployeeFilters(row, filters) {
  const id = normalizeSearch(row.employee_id);
  const name = normalizeSearch(row.name);
  const area = normalizeSearch(row.area);
  const dept = normalizeSearch(row.department);
  const filterId = normalizeSearch(filters.id);
  const filterName = normalizeSearch(filters.name);
  const filterArea = normalizeSearch(filters.area);
  const filterDept = normalizeSearch(filters.dept);

  return (!filterId || id.includes(filterId))
    && (!filterName || name.includes(filterName))
    && (!filterArea || area.includes(filterArea))
    && (!filterDept || dept.includes(filterDept));
}

function isBlankImportValue(value) {
  return value === null || value === undefined || String(value).trim() === '';
}

function getAdjustmentEmployeeIds() {
  return new Set((state.adjustmentData?.employees || []).map(emp => normalizeSearch(emp.employee_id)).filter(Boolean));
}

function getSalaryQualityFlags(row) {
  const hourlyRate = toNumber(row.hourly_rate);
  const ratio = toNumber(row.ratio);
  const fixedBase = toNumber(row.fixed_performance_base);

  return {
    complete: hourlyRate > 0 && ratio > 0,
    zeroHourly: hourlyRate <= 0,
    emptyRatio: ratio <= 0,
    fixedBase: fixedBase > 0,
  };
}

function getPerformanceQualityFlags(row, adjustmentIds = getAdjustmentEmployeeIds()) {
  const hasAdjustment = adjustmentIds.has(normalizeSearch(row.employee_id));
  const missingScore = isBlankImportValue(row.score);
  const missingCoefficient = isBlankImportValue(row.coefficient);

  return {
    complete: !missingScore && !missingCoefficient,
    missingScore,
    missingCoefficient,
    hasAdjustment,
  };
}

function findKnownEmployeeInfo(employeeId) {
  const normalizedId = normalizeSearch(employeeId);
  const datasets = [
    state.attendanceData?.employees,
    state.salaryData?.employees,
    state.performanceData?.employees,
  ];

  for (const employees of datasets) {
    const match = (employees || []).find(emp => normalizeSearch(emp.employee_id) === normalizedId);
    if (match) return match;
  }

  return null;
}

function getPerformanceReviewRows(employees) {
  const rows = (employees || []).map(emp => ({ ...emp }));
  const seenIds = new Set(rows.map(emp => normalizeSearch(emp.employee_id)).filter(Boolean));

  (state.adjustmentData?.employees || []).forEach(adjustmentEmployee => {
    const normalizedId = normalizeSearch(adjustmentEmployee.employee_id);
    if (!normalizedId || seenIds.has(normalizedId)) return;

    const knownInfo = findKnownEmployeeInfo(adjustmentEmployee.employee_id) || {};
    rows.push({
      employee_id: adjustmentEmployee.employee_id,
      name: adjustmentEmployee.name || knownInfo.name || '',
      area: adjustmentEmployee.area || knownInfo.area || '',
      department: adjustmentEmployee.department || knownInfo.department || '',
      job_type: knownInfo.job_type || 'warehouse',
      score: null,
      level: null,
      coefficient: null,
      import_source: 'adjustment',
    });
    seenIds.add(normalizedId);
  });

  return rows;
}

function matchesQualityFilter(type, row, quality, context = {}) {
  const value = String(quality || 'all');
  if (!value || value === 'all') return true;

  if (type === 'salary') {
    const flags = getSalaryQualityFlags(row);
    return {
      complete: flags.complete,
      'zero-hourly': flags.zeroHourly,
      'empty-ratio': flags.emptyRatio,
      'fixed-base': flags.fixedBase,
    }[value] ?? true;
  }

  if (type === 'performance') {
    const flags = getPerformanceQualityFlags(row, context.adjustmentIds || getAdjustmentEmployeeIds());
    return {
      complete: flags.complete,
      'missing-score': flags.missingScore,
      'missing-coefficient': flags.missingCoefficient,
      'has-adjustment': flags.hasAdjustment,
    }[value] ?? true;
  }

  return true;
}

function getFilteredRows(type, rows) {
  const filters = getTableFilter(type);
  const context = type === 'performance' ? { adjustmentIds: getAdjustmentEmployeeIds() } : {};
  return (rows || []).filter(row => matchesEmployeeFilters(row, filters)
    && matchesQualityFilter(type, row, filters.quality, context));
}

function getPaginatedRows(type, rows) {
  const pagination = getTablePagination(type);
  const pageSize = TABLE_PAGE_SIZE_OPTIONS.includes(Number(pagination.pageSize))
    ? Number(pagination.pageSize)
    : DEFAULT_TABLE_PAGE_SIZE;
  const total = rows.length;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const page = Math.min(Math.max(1, Number(pagination.page) || 1), totalPages);
  const startIndex = (page - 1) * pageSize;

  pagination.page = page;
  pagination.pageSize = pageSize;

  return {
    items: rows.slice(startIndex, startIndex + pageSize),
    page,
    pageSize,
    total,
    totalPages,
    start: total ? startIndex + 1 : 0,
    end: Math.min(startIndex + pageSize, total),
  };
}

function getPaginationPages(page, totalPages) {
  const candidates = [1, page - 1, page, page + 1, totalPages]
    .filter(value => value >= 1 && value <= totalPages);
  return [...new Set(candidates)].sort((a, b) => a - b);
}

function renderTablePagination(type, pageInfo) {
  const pages = getPaginationPages(pageInfo.page, pageInfo.totalPages);
  const pageButtons = [];

  pages.forEach((page, index) => {
    if (index > 0 && page - pages[index - 1] > 1) {
      pageButtons.push('<span class="table-pagination-ellipsis">...</span>');
    }
    pageButtons.push(`
      <button class="pagination-btn ${page === pageInfo.page ? 'active' : ''}"
              type="button"
              ${page === pageInfo.page ? 'aria-current="page"' : ''}
              onclick="changeTablePage(${formatJsArg(type)}, ${page})">${page}</button>
    `);
  });

  return `
    <div class="table-pagination" aria-label="表格分页">
      <div class="table-pagination-summary">
        显示 <strong>${pageInfo.start}-${pageInfo.end}</strong> / ${pageInfo.total} 条
      </div>
      <div class="table-pagination-controls">
        <button class="pagination-btn" type="button" ${pageInfo.page <= 1 ? 'disabled' : ''} onclick="changeTablePage(${formatJsArg(type)}, ${pageInfo.page - 1})">上一页</button>
        <div class="table-pagination-pages">
          ${pageButtons.join('')}
        </div>
        <button class="pagination-btn" type="button" ${pageInfo.page >= pageInfo.totalPages ? 'disabled' : ''} onclick="changeTablePage(${formatJsArg(type)}, ${pageInfo.page + 1})">下一页</button>
        <label class="page-size-select">
          每页
          <select onchange="changeTablePageSize(${formatJsArg(type)}, this.value)" aria-label="每页条数">
            ${TABLE_PAGE_SIZE_OPTIONS.map(size => `
              <option value="${size}" ${size === pageInfo.pageSize ? 'selected' : ''}>${size}</option>
            `).join('')}
          </select>
        </label>
      </div>
    </div>
  `;
}

function renderEmptyTableRow(colspan, message = '没有匹配的数据') {
  return `
    <tr class="table-empty-row">
      <td colspan="${colspan}">${escapeHtml(message)}</td>
    </tr>
  `;
}

function captureInputFocus() {
  const active = document.activeElement;
  if (!(active instanceof HTMLInputElement) || !active.id) return null;
  return {
    id: active.id,
    start: active.selectionStart,
    end: active.selectionEnd,
  };
}

function restoreInputFocus(snapshot) {
  if (!snapshot?.id) return;
  requestAnimationFrame(() => {
    const input = document.getElementById(snapshot.id);
    if (!(input instanceof HTMLInputElement)) return;
    input.focus({ preventScroll: true });
    if (Number.isInteger(snapshot.start) && Number.isInteger(snapshot.end)) {
      input.setSelectionRange(snapshot.start, snapshot.end);
    }
  });
}

function getShiftHours(employee, shiftName) {
  return toNumber(employee.day_shift?.[shiftName]) + toNumber(employee.night_shift?.[shiftName]);
}

async function apiJson(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || data.message || `请求失败 (${response.status})`);
  }
  return data;
}

// ═══ Element References ═══

const el = {
  // Navigation
  navItems: document.querySelectorAll('.nav-item'),
  moduleEyebrow: document.querySelector('.module-eyebrow'),
  pageTitle: document.querySelector('.top-bar-title'),
  pageSubtitle: document.querySelector('.top-bar-subtitle'),

  // Buttons
  btnNewActivity: document.getElementById('btnNewActivity'),
  btnUploadRoster: document.getElementById('btnUploadRoster'),
  btnUploadAttendance: document.getElementById('btnUploadAttendance'),
  btnUploadAttendanceEmpty: document.getElementById('btnUploadAttendanceEmpty'),
  btnExportAttendance: document.getElementById('btnExportAttendance'),
  btnUploadSalary: document.getElementById('btnUploadSalary'),
  btnUploadSalaryEmpty: document.getElementById('btnUploadSalaryEmpty'),
  btnExportSalary: document.getElementById('btnExportSalary'),
  btnUploadPerformance: document.getElementById('btnUploadPerformance'),
  btnUploadPerformanceEmpty: document.getElementById('btnUploadPerformanceEmpty'),
  btnUploadAdjustments: document.getElementById('btnUploadAdjustments'),
  btnDownloadAdjustmentsTemplate: document.getElementById('btnDownloadAdjustmentsTemplate'),
  btnExportPerformance: document.getElementById('btnExportPerformance'),
  btnCalculate: document.getElementById('btnCalculate'),
  btnCalculateEmpty: document.getElementById('btnCalculateEmpty'),
  btnExportResults: document.getElementById('btnExportResults'),
  btnExportDiagnostics: document.getElementById('btnExportDiagnostics'),

  // Pages
  pages: {
    activities: document.getElementById('pageActivities'),
    foundation: document.getElementById('pageFoundation'),
    exceptions: document.getElementById('pageExceptions'),
    attendance: document.getElementById('pageAttendance'),
    salary: document.getElementById('pageSalary'),
    performance: document.getElementById('pagePerformance'),
    results: document.getElementById('pageResults'),
  },

  // KPIs
  kpiTotalActivities: document.getElementById('kpiTotalActivities'),
  kpiCompleted: document.getElementById('kpiCompleted'),
  kpiInProgress: document.getElementById('kpiInProgress'),
  kpiErrors: document.getElementById('kpiErrors'),
  kpiResultEmployees: document.getElementById('kpiResultEmployees'),
  kpiResultBonus: document.getElementById('kpiResultBonus'),
  kpiResultAvg: document.getElementById('kpiResultAvg'),
  kpiResultErrors: document.getElementById('kpiResultErrors'),

  // Tables
  activitiesBody: document.getElementById('activitiesBody'),

  // Content areas
  foundationLeadMeta: document.getElementById('foundationLeadMeta'),
  foundationActivityCount: document.getElementById('foundationActivityCount'),
  foundationLatestMonth: document.getElementById('foundationLatestMonth'),
  foundationContent: document.getElementById('foundationContent'),
  exceptionsContent: document.getElementById('exceptionsContent'),
  attendanceContent: document.getElementById('attendanceContent'),
  salaryContent: document.getElementById('salaryContent'),
  performanceContent: document.getElementById('performanceContent'),
  resultsContent: document.getElementById('resultsContent'),

  // Upload Modal
  uploadModal: document.getElementById('uploadModal'),
  uploadModalTitle: document.getElementById('uploadModalTitle'),
  uploadZone: document.getElementById('uploadZone'),
  uploadZoneTitle: document.getElementById('uploadZoneTitle'),
  uploadZoneSub: document.getElementById('uploadZoneSub'),
  uploadFileInput: document.getElementById('uploadFileInput'),
  uploadResultPanel: document.getElementById('uploadResultPanel'),
  uploadResultTitle: document.getElementById('uploadResultTitle'),
  uploadResultSub: document.getElementById('uploadResultSub'),
  uploadResultStats: document.getElementById('uploadResultStats'),
  uploadResultFile: document.getElementById('uploadResultFile'),
  btnCloseUploadModal: document.getElementById('btnCloseUploadModal'),
  btnCancelUpload: document.getElementById('btnCancelUpload'),
  btnConfirmUpload: document.getElementById('btnConfirmUpload'),

  // App Dialog
  appDialog: document.getElementById('appDialog'),
  appDialogCard: document.getElementById('appDialogCard'),
  appDialogTitle: document.getElementById('appDialogTitle'),
  appDialogMessage: document.getElementById('appDialogMessage'),
  appDialogField: document.getElementById('appDialogField'),
  appDialogInputLabel: document.getElementById('appDialogInputLabel'),
  appDialogInput: document.getElementById('appDialogInput'),
  appDialogInputHelp: document.getElementById('appDialogInputHelp'),
  appDialogInputError: document.getElementById('appDialogInputError'),
  appDialogMonthPicker: document.getElementById('appDialogMonthPicker'),
  appDialogMonthYear: document.getElementById('appDialogMonthYear'),
  appDialogMonthGrid: document.getElementById('appDialogMonthGrid'),
  btnAppDialogMonthPrev: document.getElementById('btnAppDialogMonthPrev'),
  btnAppDialogMonthNext: document.getElementById('btnAppDialogMonthNext'),
  btnCloseAppDialog: document.getElementById('btnCloseAppDialog'),
  btnCancelAppDialog: document.getElementById('btnCancelAppDialog'),
  btnConfirmAppDialog: document.getElementById('btnConfirmAppDialog'),

  // Calc Chain Modal
  calcChainModal: document.getElementById('calcChainModal'),
  calcChainContent: document.getElementById('calcChainContent'),
  btnCloseCalcChainModal: document.getElementById('btnCloseCalcChainModal'),
  btnCloseCalcChain: document.getElementById('btnCloseCalcChain'),

  // Toasts
  toastRegion: document.getElementById('toastRegion'),
};

// ═══ Accessibility Helpers ═══

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

let activeModal = null;
let modalReturnFocus = null;
const filterTimers = {};

function getFocusableElements(container) {
  if (!container) return [];
  return Array.from(container.querySelectorAll(FOCUSABLE_SELECTOR))
    .filter(element => !element.hidden && element.getClientRects().length > 0);
}

function openModal(modal, focusTarget = null) {
  if (!modal) return;
  modalReturnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  activeModal = modal;
  modal.classList.add('active');

  const focusInsideModal = () => {
    const focusable = getFocusableElements(modal);
    const target = focusTarget && !focusTarget.disabled && focusTarget.getClientRects().length
      ? focusTarget
      : focusable[0];
    target?.focus({ preventScroll: true });
  };

  window.setTimeout(focusInsideModal, 0);
  window.setTimeout(focusInsideModal, 60);
}

function closeModal(modal, { restoreFocus = true } = {}) {
  if (!modal) return;
  modal.classList.remove('active');
  if (activeModal === modal) activeModal = null;

  if (restoreFocus && modalReturnFocus?.isConnected) {
    modalReturnFocus.focus();
  }
  modalReturnFocus = null;
}

function trapModalFocus(event) {
  if (!activeModal || event.key !== 'Tab') return;
  const focusable = getFocusableElements(activeModal);
  if (!focusable.length) {
    event.preventDefault();
    return;
  }

  const first = focusable[0];
  const last = focusable[focusable.length - 1];

  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function queueFilter(filterName) {
  clearTimeout(filterTimers[filterName]);
  filterTimers[filterName] = setTimeout(() => {
    window[filterName]?.();
  }, 180);
}

// ═══ App Dialog ═══

let appDialogResolve = null;
let appDialogValidate = null;
let appDialogInputKind = 'text';
let appDialogMonthYear = new Date().getFullYear();

const APP_DIALOG_MONTH_LABELS = Array.from({ length: 12 }, (_, index) => `${String(index + 1).padStart(2, '0')}月`);

function getDefaultCalcMonth() {
  const date = new Date();
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  return `${year}-${month}`;
}

function parseCalcMonth(value) {
  const match = String(value || '').match(/^(\d{4})-(0[1-9]|1[0-2])$/);
  if (match) {
    return { year: Number(match[1]), month: Number(match[2]) };
  }

  const [year, month] = getDefaultCalcMonth().split('-').map(Number);
  return { year, month };
}

function renderAppDialogMonthPicker() {
  if (!el.appDialogMonthGrid || !el.appDialogMonthYear) return;

  const current = parseCalcMonth(el.appDialogInput.value);
  el.appDialogMonthYear.textContent = String(appDialogMonthYear);

  const buttons = APP_DIALOG_MONTH_LABELS.map((label, index) => {
    const month = index + 1;
    const button = document.createElement('button');
    const selected = current.year === appDialogMonthYear && current.month === month;

    button.type = 'button';
    button.className = `month-picker-option${selected ? ' selected' : ''}`;
    button.dataset.month = String(month);
    button.textContent = label;
    button.setAttribute('role', 'option');
    button.setAttribute('aria-selected', selected ? 'true' : 'false');

    return button;
  });

  el.appDialogMonthGrid.replaceChildren(...buttons);
}

function setAppDialogMonthValue(year, month) {
  const safeYear = Number.isFinite(year) ? year : new Date().getFullYear();
  const safeMonth = Math.min(12, Math.max(1, Number(month) || 1));

  appDialogMonthYear = safeYear;
  el.appDialogInput.value = `${safeYear}-${String(safeMonth).padStart(2, '0')}`;
  el.appDialogInputError.textContent = '';
  renderAppDialogMonthPicker();
}

function setDialogTone(tone = 'primary') {
  el.appDialogCard.classList.remove('warning', 'danger');
  el.btnConfirmAppDialog.classList.remove('btn-primary', 'btn-warning', 'btn-danger');

  if (tone === 'warning') {
    el.appDialogCard.classList.add('warning');
    el.btnConfirmAppDialog.classList.add('btn-warning');
  } else if (tone === 'danger') {
    el.appDialogCard.classList.add('danger');
    el.btnConfirmAppDialog.classList.add('btn-danger');
  } else {
    el.btnConfirmAppDialog.classList.add('btn-primary');
  }
}

function openAppDialog(options = {}) {
  const {
    title = '确认操作',
    message = '',
    confirmText = '确定',
    cancelText = '取消',
    tone = 'primary',
    input = null,
  } = options;

  return new Promise(resolve => {
    appDialogResolve = resolve;
    appDialogValidate = input?.validate || null;

    setDialogTone(tone);
    el.appDialogTitle.textContent = title;
    el.appDialogMessage.textContent = message;
    el.btnConfirmAppDialog.textContent = confirmText;
    el.btnCancelAppDialog.textContent = cancelText;
    el.appDialogInputError.textContent = '';

    if (input) {
      const isMonthPicker = input.kind === 'month';

      appDialogInputKind = isMonthPicker ? 'month' : 'text';
      el.appDialogField.hidden = false;
      el.appDialogInputLabel.textContent = input.label || '';
      el.appDialogInput.placeholder = input.placeholder || '';
      el.appDialogInputHelp.textContent = input.help || '';
      el.appDialogInput.type = 'text';
      el.appDialogInput.readOnly = isMonthPicker || Boolean(input.readOnly);

      if (input.inputMode) {
        el.appDialogInput.inputMode = input.inputMode;
      } else {
        el.appDialogInput.removeAttribute('inputmode');
      }

      if (input.maxLength) {
        el.appDialogInput.maxLength = input.maxLength;
      } else {
        el.appDialogInput.removeAttribute('maxlength');
      }

      if (isMonthPicker) {
        const monthParts = parseCalcMonth(input.value || getDefaultCalcMonth());
        el.appDialogInput.value = `${monthParts.year}-${String(monthParts.month).padStart(2, '0')}`;
        appDialogMonthYear = monthParts.year;
        el.appDialogMonthPicker.hidden = false;
        renderAppDialogMonthPicker();
      } else {
        el.appDialogInput.value = input.value || '';
        el.appDialogMonthPicker.hidden = true;
      }
    } else {
      appDialogInputKind = 'text';
      el.appDialogField.hidden = true;
      el.appDialogInput.value = '';
      el.appDialogInputHelp.textContent = '';
      el.appDialogInput.readOnly = false;
      el.appDialogInput.type = 'text';
      el.appDialogInput.removeAttribute('inputmode');
      el.appDialogInput.removeAttribute('maxlength');
      el.appDialogMonthPicker.hidden = true;
    }

    const focusTarget = appDialogInputKind === 'month'
      ? el.appDialogMonthGrid?.querySelector('.month-picker-option.selected')
      : input
        ? el.appDialogInput
        : el.btnConfirmAppDialog;

    openModal(el.appDialog, focusTarget);

    if (input && appDialogInputKind !== 'month') {
      requestAnimationFrame(() => el.appDialogInput.select());
    }
  });
}

function closeAppDialog(result) {
  closeModal(el.appDialog);
  const resolve = appDialogResolve;
  appDialogResolve = null;
  appDialogValidate = null;
  if (resolve) resolve(result);
}

function confirmAppDialog() {
  const value = el.appDialogInput.value.trim();
  if (!el.appDialogField.hidden && appDialogValidate) {
    const validation = appDialogValidate(value);
    if (validation !== true) {
      el.appDialogInputError.textContent = validation || '请检查输入内容';
      el.appDialogInput.focus();
      return;
    }
  }
  closeAppDialog({ confirmed: true, value });
}

el.btnCloseAppDialog?.addEventListener('click', () => closeAppDialog({ confirmed: false }));
el.btnCancelAppDialog?.addEventListener('click', () => closeAppDialog({ confirmed: false }));
el.btnConfirmAppDialog?.addEventListener('click', confirmAppDialog);
el.appDialog?.addEventListener('click', (event) => {
  if (event.target === el.appDialog) closeAppDialog({ confirmed: false });
});
el.appDialogInput?.addEventListener('input', () => {
  el.appDialogInputError.textContent = '';
});
el.appDialogInput?.addEventListener('keydown', (event) => {
  if (event.key === 'Enter') confirmAppDialog();
});
el.btnAppDialogMonthPrev?.addEventListener('click', () => {
  appDialogMonthYear -= 1;
  renderAppDialogMonthPicker();
});
el.btnAppDialogMonthNext?.addEventListener('click', () => {
  appDialogMonthYear += 1;
  renderAppDialogMonthPicker();
});
el.appDialogMonthGrid?.addEventListener('click', (event) => {
  const button = event.target.closest('.month-picker-option');
  if (!button || !el.appDialogMonthGrid.contains(button)) return;

  setAppDialogMonthValue(appDialogMonthYear, Number(button.dataset.month));
  button.focus();
});
el.appDialogMonthGrid?.addEventListener('keydown', (event) => {
  const options = Array.from(el.appDialogMonthGrid.querySelectorAll('.month-picker-option'));
  const currentIndex = options.indexOf(document.activeElement);
  if (currentIndex === -1) return;

  const keyMoves = {
    ArrowRight: 1,
    ArrowLeft: -1,
    ArrowDown: 3,
    ArrowUp: -3,
  };

  if (event.key in keyMoves) {
    event.preventDefault();
    const nextIndex = (currentIndex + keyMoves[event.key] + options.length) % options.length;
    options[nextIndex]?.focus();
  } else if (event.key === 'Home') {
    event.preventDefault();
    options[0]?.focus();
  } else if (event.key === 'End') {
    event.preventDefault();
    options[options.length - 1]?.focus();
  } else if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault();
    const option = options[currentIndex];
    setAppDialogMonthValue(appDialogMonthYear, Number(option.dataset.month));
    requestAnimationFrame(() => {
      el.appDialogMonthGrid
        ?.querySelector(`.month-picker-option[data-month="${option.dataset.month}"]`)
        ?.focus();
    });
  }
});
document.addEventListener('keydown', (event) => {
  trapModalFocus(event);

  if (event.key !== 'Escape') return;

  if (activeModal === el.appDialog) {
    event.preventDefault();
    closeAppDialog({ confirmed: false });
  } else if (activeModal === el.uploadModal) {
    event.preventDefault();
    closeUploadModal();
  } else if (activeModal === el.calcChainModal) {
    event.preventDefault();
    closeCalcChainModal();
  }
});

// ═══ Navigation ═══

function navigateTo(page) {
  state.currentPage = page;

  // Update nav items
  el.navItems.forEach(item => {
    const isActive = item.dataset.page === page;
    item.classList.toggle('active', isActive);
    if (isActive) {
      item.setAttribute('aria-current', 'page');
    } else {
      item.removeAttribute('aria-current');
    }
  });

  // Show/hide pages
  Object.keys(el.pages).forEach(key => {
    el.pages[key].hidden = key !== page;
  });

  // Update title
  const titles = {
    activities: { module: '绩效管理模块', title: 'FBU美洲绩效核算', subtitle: '月度活动管理' },
    foundation: { module: '平台基础数据', title: '基础数据', subtitle: '组织人员与模板资产' },
    exceptions: { module: '异常处理中心', title: '异常队列', subtitle: state.currentActivity?.calc_month || '待选择活动' },
    attendance: { module: '活动工作流 · 1/4', title: '考勤汇总', subtitle: state.currentActivity?.calc_month || '' },
    salary: { module: '活动工作流 · 2/4', title: '薪资匹配', subtitle: state.currentActivity?.calc_month || '' },
    performance: { module: '活动工作流 · 3/4', title: '绩效明细', subtitle: state.currentActivity?.calc_month || '' },
    results: { module: '活动工作流 · 4/4', title: '核算结果', subtitle: state.currentActivity?.calc_month || '' },
  };

  const title = titles[page] || titles.activities;
  if (el.moduleEyebrow) el.moduleEyebrow.textContent = title.module;
  el.pageTitle.textContent = title.title;
  el.pageSubtitle.textContent = title.subtitle;

  // Load page data
  if (page === 'activities') {
    loadActivities();
  } else if (page === 'foundation') {
    renderFoundationData();
    loadFoundationActivityDetail();
  } else if (page === 'exceptions') {
    renderExceptionQueue();
  }
}

el.navItems.forEach(item => {
  item.addEventListener('click', (e) => {
    e.preventDefault();
    const page = item.dataset.page;
    if (page) {
      navigateTo(page);
    }
  });
});

// ═══ Activities ═══

async function loadActivities() {
  try {
    const data = await apiJson(`${API_BASE}/runs`);

    state.activities = data.runs || [];
    renderActivities();
    updateActivityKPIs();
    loadActivityListDetails();
    if (state.currentPage === 'foundation') {
      renderFoundationData();
      loadFoundationActivityDetail();
    }
  } catch (error) {
    console.error('加载活动列表失败:', error);
  }
}

function renderActivities() {
  if (!state.activities.length) {
    el.activitiesBody.innerHTML = renderEmptyTableRow(7, '暂无月度活动');
    return;
  }

  el.activitiesBody.innerHTML = state.activities.map(activity => {
    const statusMeta = getActivityStatusMeta(activity);
    const completedSteps = getActivityCompletedSteps(activity);
    const progress = `${completedSteps}/${activityStepLabels.length}`;
    const stageCaption = getActivityStageCaption(activity, completedSteps);
    const totalEmployees = activity.total_employees ?? '-';
    const totalBonus = activity.total_bonus === null
      || activity.total_bonus === undefined
      || (activity.status !== 'completed' && toNumber(activity.total_bonus) === 0)
      ? '-'
      : formatCurrency(activity.total_bonus);
    const primaryAction = statusMeta.page
      ? `openActivityPage(${formatJsArg(activity.run_id)}, ${formatJsArg(statusMeta.page)})`
      : `enterActivity(${formatJsArg(activity.run_id)})`;

    return `
      <tr class="activity-row ${statusMeta.rowClass}">
        <td>
          <div class="activity-task">
            <div class="activity-task-main">
              <span class="activity-month">${escapeHtml(activity.calc_month || '-')}</span>
              <span class="status-badge ${statusMeta.className}">${statusMeta.text}</span>
            </div>
            <div class="activity-task-meta">活动 ID ${escapeHtml(activity.run_id || '-')}</div>
          </div>
        </td>
        <td>
          <div class="activity-stage">
            <div class="activity-stage-head">
              <span class="activity-stage-caption">${escapeHtml(stageCaption)}</span>
              <span class="activity-progress-value">${escapeHtml(progress)}</span>
            </div>
            <div class="activity-progress-track" aria-label="核算进度 ${escapeHtml(progress)}">
              ${renderActivityProgress(completedSteps)}
            </div>
          </div>
        </td>
        <td>
          <div class="activity-metric">
            <span class="activity-metric-label">员工</span>
            <span class="activity-metric-value">${escapeHtml(totalEmployees)}</span>
          </div>
        </td>
        <td>${renderActivityDiagnostics(activity)}</td>
        <td><span class="money-cell">${escapeHtml(totalBonus)}</span></td>
        <td>${escapeHtml(formatDateOnly(activity.created_at))}</td>
        <td>
          <div class="activity-action-cell">
            <button class="btn btn-secondary btn-sm" onclick="${primaryAction}">${escapeHtml(statusMeta.action)}</button>
            <button class="btn btn-danger btn-sm" onclick="deleteActivity(${formatJsArg(activity.run_id)})">删除</button>
          </div>
        </td>
      </tr>
    `;
  }).join('');
}

function updateActivityKPIs() {
  el.kpiTotalActivities.textContent = state.activities.length;
  el.kpiCompleted.textContent = state.activities.filter(a => a.status === 'completed').length;
  el.kpiInProgress.textContent = state.activities.filter(a => a.status !== 'completed' && a.status !== 'failed').length;
  el.kpiErrors.textContent = state.activities.filter(a => a.status === 'failed').length;
}

const activityStepLabels = ['考勤汇总', '薪资匹配', '绩效明细', '核算结果'];

function getActivityDetail(activity) {
  if (!activity) return null;
  if (state.currentActivity?.run_id === activity.run_id) return state.currentActivity;
  return state.foundationRunDetails[activity.run_id] || activity;
}

async function loadActivityListDetails() {
  const pendingActivities = state.activities.filter(activity => activity.run_id
    && state.currentActivity?.run_id !== activity.run_id
    && !state.foundationRunDetails[activity.run_id]
    && !state.activityListLoadingRunIds.has(activity.run_id));

  if (!pendingActivities.length) return;

  pendingActivities.forEach(activity => state.activityListLoadingRunIds.add(activity.run_id));
  if (state.currentPage === 'activities') renderActivities();

  await Promise.allSettled(pendingActivities.map(async activity => {
    try {
      const detail = await apiJson(`${API_BASE}/runs/${activity.run_id}`);
      state.foundationRunDetails[activity.run_id] = detail;
    } finally {
      state.activityListLoadingRunIds.delete(activity.run_id);
    }
  }));

  if (state.currentPage === 'activities') {
    renderActivities();
  }
}

function renderActivityDiagnostics(activity) {
  const detail = getActivityDetail(activity);
  const summary = detail?.diagnostics?.summary;
  const isLoading = state.activityListLoadingRunIds.has(activity.run_id);

  if (!summary) {
    return `
      <div class="activity-diagnostics">
        <span class="activity-diagnostics-muted">${isLoading ? '诊断加载中' : '未生成诊断'}</span>
        <button class="activity-link-btn" type="button" onclick="openActivityPage(${formatJsArg(activity.run_id)}, ${formatJsArg('exceptions')})">异常队列</button>
      </div>
    `;
  }

  const errorCount = toNumber(summary.error_count);
  const warningCount = toNumber(summary.warning_count);
  const issueCount = toNumber(summary.issue_count);
  const badgeClass = errorCount ? 'danger' : warningCount ? 'warning' : 'success';
  const badgeText = errorCount ? `${errorCount}严重` : warningCount ? `${warningCount}提醒` : '无阻断';

  return `
    <div class="activity-diagnostics">
      <div class="activity-diagnostics-line">
        <span class="status-badge ${badgeClass}">${escapeHtml(badgeText)}</span>
        <button class="activity-link-btn" type="button" onclick="openActivityPage(${formatJsArg(activity.run_id)}, ${formatJsArg('exceptions')})">异常队列</button>
      </div>
      <div class="activity-diagnostics-meta">
        ${escapeHtml(`${issueCount}项 · 可算 ${toNumber(summary.can_calculate_count)}/${toNumber(summary.attendance_count)}`)}
      </div>
    </div>
  `;
}

function getActivityStatusMeta(activity) {
  if (activity.status === 'completed') {
    return { className: 'success', text: '已完成', rowClass: 'completed', action: '查看结果', page: 'results' };
  }
  if (activity.status === 'failed') {
    return { className: 'danger', text: '失败', rowClass: 'failed', action: '查看异常', page: 'exceptions' };
  }
  return { className: 'warning', text: '进行中', rowClass: 'running', action: '继续处理', page: '' };
}

function getActivityCompletedSteps(activity) {
  if (activity.status === 'completed') return activityStepLabels.length;
  return Math.min(Math.max(toNumber(activity.current_step), 0), activityStepLabels.length);
}

function getActivityStageCaption(activity, completedSteps) {
  if (activity.status === 'completed') return '核算完成';
  if (activity.status === 'failed') return '需要处理异常';
  const nextStep = activityStepLabels[Math.min(completedSteps, activityStepLabels.length - 1)];
  return `下一步：${nextStep}`;
}

function renderActivityProgress(completedSteps) {
  return activityStepLabels.map((label, index) => `
    <span class="activity-progress-segment ${index < completedSteps ? 'done' : ''}" title="${escapeHtml(label)}"></span>
  `).join('');
}

function getLatestActivity() {
  return [...state.activities].sort((a, b) => {
    const timeA = new Date(a.created_at || 0).getTime();
    const timeB = new Date(b.created_at || 0).getTime();
    return timeB - timeA;
  })[0] || null;
}

function getFoundationActivity() {
  return state.currentActivity || getLatestActivity();
}

function getFoundationRunDetail(activity = getFoundationActivity()) {
  if (!activity) return null;
  if (state.currentActivity?.run_id === activity.run_id) return state.currentActivity;
  return state.foundationRunDetails[activity.run_id] || activity;
}

async function loadFoundationActivityDetail(activity = getFoundationActivity()) {
  if (!activity?.run_id) return;
  if (state.currentActivity?.run_id === activity.run_id) return;
  if (state.foundationRunDetails[activity.run_id]) return;
  if (state.foundationLoadingRunId === activity.run_id) return;

  state.foundationLoadingRunId = activity.run_id;
  try {
    const detail = await apiJson(`${API_BASE}/runs/${activity.run_id}`);
    state.foundationRunDetails[activity.run_id] = detail;
    if (state.currentPage === 'foundation') {
      renderFoundationData();
    }
  } catch (error) {
    console.error('加载基础数据活动详情失败:', error);
  } finally {
    if (state.foundationLoadingRunId === activity.run_id) {
      state.foundationLoadingRunId = '';
    }
  }
}

function getBatchStatus({ required, hasFile }) {
  if (hasFile) {
    return '<span class="status-badge success">已解析</span>';
  }
  if (required) {
    return '<span class="status-badge warning">待上传</span>';
  }
  return '<span class="status-badge neutral">可选</span>';
}

function buildImportBatchRows(activity) {
  if (!activity) return [];

  const rows = [];
  const addRow = ({ type, file, required = true, metric = '-', quality = '-', meta = '' }) => {
    const hasFile = Boolean(file);
    rows.push({
      type,
      file: file || '未上传',
      meta,
      metric,
      quality,
      status: getBatchStatus({ required, hasFile }),
      runId: activity.run_id,
    });
  };

  const attendanceSummary = activity.attendance_data?.summary || {};
  addRow({
    type: '考勤报表',
    file: activity.attendance_file,
    metric: activity.attendance_file ? `${toNumber(attendanceSummary.total_employees)}人` : '-',
    quality: activity.attendance_file
      ? `${toNumber(attendanceSummary.roster_matched)}/${toNumber(attendanceSummary.total_employees)}匹配`
      : '-',
    meta: activity.attendance_file ? `计薪工时 ${formatHours(attendanceSummary.total_base_hours)}` : '月度工时来源',
  });

  const salarySummary = activity.salary_data?.summary || {};
  addRow({
    type: '薪资档案',
    file: activity.salary_file,
    metric: activity.salary_file ? `${toNumber(salarySummary.total_employees)}人` : '-',
    quality: activity.salary_file
      ? `${toNumber(salarySummary.valid_hourly_count)}有效时薪`
      : '-',
    meta: activity.salary_file ? `0时薪 ${toNumber(salarySummary.zero_hourly_count)}人` : '时薪与绩效比例来源',
  });

  const performanceSummary = activity.performance_data?.summary || {};
  addRow({
    type: '绩效报表',
    file: activity.performance_file,
    metric: activity.performance_file ? `${toNumber(performanceSummary.total_employees)}人` : '-',
    quality: activity.performance_file
      ? `${toNumber(performanceSummary.scored_employees)}有分数`
      : '-',
    meta: activity.performance_file ? `平均分 ${toNumber(performanceSummary.avg_score).toFixed(2)}` : '绩效得分与等级来源',
  });

  const adjustmentSummary = activity.adjustment_data?.summary || {};
  addRow({
    type: '调薪拆分',
    file: activity.adjustment_file,
    required: false,
    metric: activity.adjustment_file ? `${toNumber(adjustmentSummary.total_employees)}人` : '-',
    quality: activity.adjustment_file
      ? `${toNumber(adjustmentSummary.total_segments)}段`
      : '-',
    meta: activity.adjustment_file ? `有效基数 ${formatCurrency(adjustmentSummary.active_performance_base)}` : '试用期/转正/调薪分段',
  });

  return rows;
}

function renderImportBatchLedger(activity) {
  if (!activity) {
    return `
      <div class="foundation-import-ledger">
        <div class="foundation-ledger-head">
          <div>
            <div class="foundation-ledger-title">导入批次台账</div>
            <div class="foundation-ledger-sub">创建月度活动后，这里会展示该月已导入的报表和解析结果。</div>
          </div>
        </div>
        <div class="empty-state compact">
          <h3 class="empty-state-title">暂无月度活动</h3>
          <p class="empty-state-sub">先创建月度活动，再逐份导入考勤、薪资、绩效和拆分表。</p>
          <button class="btn btn-secondary" type="button" onclick="navigateTo('activities')">查看月度活动</button>
        </div>
      </div>
    `;
  }

  const rows = buildImportBatchRows(activity);
  const isLoading = state.foundationLoadingRunId === activity.run_id && !state.foundationRunDetails[activity.run_id];
  return `
    <div class="foundation-import-ledger">
      <div class="foundation-ledger-head">
        <div>
          <div class="foundation-ledger-title">导入批次台账</div>
          <div class="foundation-ledger-sub">按报表维度追踪本月数据来源、解析结果和可计算状态。</div>
        </div>
        <div class="foundation-ledger-period">${escapeHtml(activity.calc_month || '-')}</div>
      </div>
      <div class="foundation-ledger-table">
        <table class="data-table">
          <thead>
            <tr>
              <th>数据源</th>
              <th>源文件</th>
              <th>解析结果</th>
              <th>匹配/异常</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            ${rows.map(row => `
              <tr>
                <td><strong>${escapeHtml(row.type)}</strong></td>
                <td>
                  <div class="batch-file-name" title="${escapeHtml(row.file)}">${escapeHtml(row.file)}</div>
                  <div class="batch-file-meta">${escapeHtml(row.meta)}</div>
                </td>
                <td>${escapeHtml(row.metric)}</td>
                <td>${escapeHtml(row.quality)}</td>
                <td>${row.status}</td>
                <td><button class="btn btn-secondary btn-sm" type="button" onclick="enterActivity('${escapeHtml(row.runId)}')">进入</button></td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
      ${isLoading ? '<div class="import-result-note"><span><strong>正在读取活动详情</strong> 解析统计加载后会自动刷新。</span></div>' : ''}
    </div>
  `;
}

function renderFoundationData() {
  const roster = state.baseRoster || {};
  const hasRoster = Boolean(roster.has_roster);
  const latestActivity = getLatestActivity();
  const ledgerActivity = getFoundationRunDetail();

  if (el.foundationLeadMeta) {
    el.foundationLeadMeta.textContent = hasRoster
      ? `${roster.filename || '已上传花名册'} · ${roster.total_employees || 0}人`
      : '尚未上传基础花名册';
  }
  if (el.foundationActivityCount) {
    el.foundationActivityCount.textContent = state.activities.length;
  }
  if (el.foundationLatestMonth) {
    el.foundationLatestMonth.textContent = latestActivity?.calc_month || '-';
  }
  if (!el.foundationContent) return;

  const rosterStatus = hasRoster
    ? '<span class="status-badge success">可用</span>'
    : '<span class="status-badge warning">待上传</span>';

  el.foundationContent.innerHTML = `
    <div class="foundation-grid">
      <section>
        <h3 class="module-section-title">基础花名册</h3>
        <p class="module-description">
          基础花名册是月度活动引用员工姓名、部门、区域和岗位类型的底座。更新后，新建或重新导入的活动会引用最新版本。
        </p>
        <div class="meta-list">
          <div class="meta-row">
            <div class="meta-label">状态</div>
            <div class="meta-value">${rosterStatus}</div>
          </div>
          <div class="meta-row">
            <div class="meta-label">员工数</div>
            <div class="meta-value">${hasRoster ? `${roster.total_employees || 0}人` : '-'}</div>
          </div>
          <div class="meta-row">
            <div class="meta-label">文件名</div>
            <div class="meta-value">${escapeHtml(roster.filename || '-')}</div>
          </div>
          <div class="meta-row">
            <div class="meta-label">更新时间</div>
            <div class="meta-value">${escapeHtml(formatDateTime(roster.uploaded_at))}</div>
          </div>
        </div>
      </section>

      <aside>
        <h3 class="module-section-title">常用资料</h3>
        <div class="module-action-list">
          <div class="module-action-card">
            <strong>更新基础花名册</strong>
            <span>上传员工基础资料，供月度活动匹配姓名、部门和岗位类型。</span>
            <button class="btn btn-primary btn-sm" type="button" onclick="chooseRosterFile()">上传花名册</button>
          </div>
          <div class="module-action-card">
            <strong>调薪/转正拆分模板</strong>
            <span>用于处理试用期转正、调薪分段等线下拆分场景。</span>
            <button class="btn btn-secondary btn-sm" type="button" onclick="downloadAdjustmentsTemplate()">下载模板</button>
          </div>
          <div class="module-action-card">
            <strong>月度活动</strong>
            <span>按月份创建独立核算空间，逐份导入报表并生成结果。</span>
            <button class="btn btn-secondary btn-sm" type="button" onclick="navigateTo('activities')">查看活动</button>
          </div>
        </div>
      </aside>
    </div>
    ${renderImportBatchLedger(ledgerActivity)}
  `;
}

const exceptionSeverityLabel = {
  error: '严重',
  warning: '提醒',
  info: '信息',
};

const exceptionSourceOptions = [
  { key: 'all', label: '全部数据源' },
  { key: 'attendance', label: '考勤报表' },
  { key: 'salary', label: '薪资档案' },
  { key: 'performance', label: '绩效报表' },
  { key: 'adjustments', label: '调薪拆分' },
  { key: 'system', label: '系统校验' },
];

function safeExceptionSeverity(severity) {
  const value = String(severity || 'info');
  return value === 'error' || value === 'warning' || value === 'info' ? value : 'info';
}

function getExceptionSource(issue) {
  const type = String(issue?.type || '');
  const detail = String(issue?.detail || '');
  const text = `${type} ${detail}`;
  if (text.includes('拆分') || text.includes('调薪') || text.includes('转正')) {
    return { key: 'adjustments', label: '调薪拆分' };
  }
  if (text.includes('薪资') || text.includes('时薪') || text.includes('绩效比例')) {
    return { key: 'salary', label: '薪资档案' };
  }
  if (text.includes('绩效')) {
    return { key: 'performance', label: '绩效报表' };
  }
  if (text.includes('考勤')) {
    return { key: 'attendance', label: '考勤报表' };
  }
  return { key: 'system', label: '系统校验' };
}

function getFilteredExceptionIssues(issues, filters = {}) {
  const severityFilter = String(filters.severity || 'all');
  const sourceFilter = String(filters.source || 'all');
  const query = normalizeSearch(filters.query);

  return (issues || []).filter(issue => {
    const severity = safeExceptionSeverity(issue.severity);
    const source = getExceptionSource(issue);
    const queryText = normalizeSearch([
      source.label,
      issue.type,
      issue.employee_id,
      issue.name,
      issue.detail,
    ].join(' '));

    return (severityFilter === 'all' || severity === severityFilter)
      && (sourceFilter === 'all' || source.key === sourceFilter)
      && (!query || queryText.includes(query));
  });
}

function getExceptionTypeBreakdown(issues) {
  const counts = new Map();
  (issues || []).forEach(issue => {
    const type = issue.type || '未分类';
    counts.set(type, (counts.get(type) || 0) + 1);
  });
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'zh-CN'))
    .slice(0, 8);
}

function getExceptionSourceBreakdown(issues) {
  const counts = new Map();
  (issues || []).forEach(issue => {
    const source = getExceptionSource(issue);
    const current = counts.get(source.key) || { ...source, count: 0 };
    current.count += 1;
    counts.set(source.key, current);
  });

  return [...counts.values()]
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label, 'zh-CN'));
}

function renderExceptionFilterSummary(filters, filteredCount, totalCount) {
  const activeLabels = [];
  if (filters.severity && filters.severity !== 'all') {
    activeLabels.push(exceptionSeverityLabel[filters.severity] || filters.severity);
  }
  if (filters.source && filters.source !== 'all') {
    const sourceOption = exceptionSourceOptions.find(option => option.key === filters.source);
    activeLabels.push(sourceOption?.label || filters.source);
  }
  if (normalizeSearch(filters.query)) {
    activeLabels.push(`关键词：${filters.query}`);
  }

  return `
    <div class="exception-result-strip">
      <div>
        <span class="exception-result-count">显示 ${filteredCount} / ${totalCount} 条</span>
        <span class="exception-result-meta">${escapeHtml(activeLabels.length ? activeLabels.join(' · ') : '全部问题')}</span>
      </div>
      ${activeLabels.length ? '<button class="activity-link-btn" type="button" onclick="resetExceptionFilter()">清空条件</button>' : ''}
    </div>
  `;
}

const exceptionSourceTargetMeta = {
  attendance: { page: 'attendance', label: '查看考勤' },
  salary: { page: 'salary', label: '查看薪资' },
  performance: { page: 'performance', label: '查看绩效' },
  adjustments: { page: 'performance', label: '查看拆分' },
  system: { page: 'exceptions', label: '聚焦问题' },
};

function renderExceptionAction(issue, source) {
  const meta = exceptionSourceTargetMeta[source.key] || exceptionSourceTargetMeta.system;
  return `
    <button class="exception-row-action" type="button"
            onclick="locateExceptionIssue(${formatJsArg(source.key)}, ${formatJsArg(issue.employee_id || '')}, ${formatJsArg(issue.name || '')}, ${formatJsArg(issue.type || '')})">
      ${escapeHtml(meta.label)}
    </button>
  `;
}

function renderExceptionQueue() {
  if (!el.exceptionsContent) return;

  const diagnostics = state.diagnosticsData;
  const summary = diagnostics?.summary;
  const issues = diagnostics?.issues || [];
  const filters = getTableFilter('exceptions');
  const filteredIssues = getFilteredExceptionIssues(issues, filters);
  const pageInfo = getPaginatedRows('exceptions', filteredIssues);
  if (el.btnExportDiagnostics) {
    el.btnExportDiagnostics.disabled = !state.currentActivity || !summary;
  }

  if (!state.currentActivity || !summary) {
    el.exceptionsContent.innerHTML = `
      <div class="empty-state compact">
        <h3 class="empty-state-title">先选择一个月度活动</h3>
        <p class="empty-state-sub">进入活动后，这里会汇总考勤、薪资、绩效和拆分表之间的匹配问题。</p>
        <button class="btn btn-secondary" type="button" onclick="navigateTo('activities')">返回月度活动</button>
      </div>
    `;
    return;
  }

  const infoCount = Math.max(0, (summary.issue_count || 0) - (summary.error_count || 0) - (summary.warning_count || 0));
  const typeBreakdown = getExceptionTypeBreakdown(issues);
  const sourceBreakdown = getExceptionSourceBreakdown(issues);

  el.exceptionsContent.innerHTML = `
    <div class="exception-workbench">
      <div class="exception-summary">
        <div class="exception-summary-item">
          <span class="exception-summary-label">严重</span>
          <span class="exception-summary-value">${summary.error_count || 0}</span>
        </div>
        <div class="exception-summary-item">
          <span class="exception-summary-label">提醒</span>
          <span class="exception-summary-value">${summary.warning_count || 0}</span>
        </div>
        <div class="exception-summary-item">
          <span class="exception-summary-label">信息</span>
          <span class="exception-summary-value">${infoCount}</span>
        </div>
        <div class="exception-summary-item">
          <span class="exception-summary-label">可计算人数</span>
          <span class="exception-summary-value">${summary.can_calculate_count || 0}/${summary.attendance_count || 0}</span>
        </div>
      </div>

      ${issues.length ? `
        <div class="exception-filter-panel">
          <div class="filter-field">
            <label for="filterExceptionSeverity">严重程度</label>
            <select id="filterExceptionSeverity" onchange="filterExceptionData()">
              ${[
                ['all', '全部级别'],
                ['error', '严重'],
                ['warning', '提醒'],
                ['info', '信息'],
              ].map(([value, label]) => `
                <option value="${value}" ${String(filters.severity || 'all') === value ? 'selected' : ''}>${label}</option>
              `).join('')}
            </select>
          </div>
          <div class="filter-field">
            <label for="filterExceptionSource">数据源</label>
            <select id="filterExceptionSource" onchange="filterExceptionData()">
              ${exceptionSourceOptions.map(option => `
                <option value="${escapeHtml(option.key)}" ${String(filters.source || 'all') === option.key ? 'selected' : ''}>${escapeHtml(option.label)}</option>
              `).join('')}
            </select>
          </div>
          <div class="filter-field">
            <label for="filterExceptionQuery">员工 / 问题</label>
            <input type="text" id="filterExceptionQuery" value="${escapeHtml(filters.query || '')}" placeholder="工号、姓名、问题类型、说明" oninput="queueFilter('filterExceptionData')">
          </div>
          <div class="exception-filter-actions">
            <button class="btn btn-secondary btn-sm" type="button" onclick="filterExceptionData()">筛选</button>
            <button class="btn btn-secondary btn-sm" type="button" onclick="resetExceptionFilter()">重置</button>
          </div>
        </div>

        ${renderExceptionFilterSummary(filters, filteredIssues.length, issues.length)}

        <div class="exception-source-list" aria-label="数据源分布">
          ${sourceBreakdown.map(source => `
            <button class="exception-source-chip ${String(filters.source || 'all') === source.key ? 'active' : ''}"
                    type="button"
                    onclick="quickFilterExceptionSource(${formatJsArg(source.key)})">
              ${escapeHtml(source.label)} <span>${source.count}</span>
            </button>
          `).join('')}
        </div>

        <div class="exception-type-list" aria-label="问题类型分布">
          ${typeBreakdown.map(([type, count]) => `
            <button class="exception-type-chip ${String(filters.query || '') === type ? 'active' : ''}"
                    type="button"
                    onclick="quickFilterExceptionType(${formatJsArg(type)})">
              ${escapeHtml(type)} <span>${count}</span>
            </button>
          `).join('')}
        </div>

        ${filteredIssues.length ? `
          <div class="exception-table-shell">
            <table class="data-table">
              <thead>
                <tr>
                  <th>级别</th>
                  <th>数据源</th>
                  <th>问题类型</th>
                  <th>工号</th>
                  <th>姓名</th>
                  <th>说明</th>
                  <th>处理</th>
                </tr>
              </thead>
              <tbody>
                ${pageInfo.items.map(issue => {
                  const severity = safeExceptionSeverity(issue.severity);
                  const source = getExceptionSource(issue);
                  return `
                  <tr class="${severity === 'error' ? 'row-danger' : ''}">
                    <td><span class="severity-pill ${severity}">${escapeHtml(exceptionSeverityLabel[severity] || '信息')}</span></td>
                    <td>${escapeHtml(source.label)}</td>
                    <td>${escapeHtml(issue.type || '-')}</td>
                    <td>${escapeHtml(issue.employee_id || '-')}</td>
                    <td>${escapeHtml(issue.name || '-')}</td>
                    <td>${escapeHtml(issue.detail || '-')}</td>
                    <td>${renderExceptionAction(issue, source)}</td>
                  </tr>
                  `;
                }).join('')}
              </tbody>
            </table>
          </div>
          ${renderTablePagination('exceptions', pageInfo)}
        ` : `
          <div class="empty-state compact">
            <h3 class="empty-state-title">当前筛选没有异常</h3>
            <p class="empty-state-sub">调整严重程度、数据源或关键词后再查看。</p>
          </div>
        `}
      ` : `
        <div class="empty-state compact">
          <h3 class="empty-state-title">暂无匹配异常</h3>
          <p class="empty-state-sub">${escapeHtml(state.currentActivity.calc_month || '')} 当前没有需要处理的诊断问题。</p>
        </div>
      `}
    </div>
  `;
}

// ═══ Enter Activity ═══

async function openActivityPage(activityId, page) {
  await enterActivity(activityId);
  navigateTo(page);
}

async function enterActivity(activityId, options = {}) {
  const { preservePage = false } = options;

  try {
    const isDifferentActivity = state.currentActivity?.run_id !== activityId;
    const activity = await apiJson(`${API_BASE}/runs/${activityId}`);

    if (isDifferentActivity) {
      resetTableControls();
    }

    state.currentActivity = activity;
    state.foundationRunDetails[activity.run_id] = activity;
    state.diagnosticsData = activity.diagnostics || null;

    // Navigate to appropriate page based on step
    const page = activity.current_step >= 3 ? 'results' :
                 activity.current_step >= 2 ? 'performance' :
                 activity.current_step >= 1 ? 'salary' : 'attendance';

    if (preservePage && state.currentPage !== 'activities') {
      navigateTo(state.currentPage);
    } else {
      navigateTo(page);
    }

    // Load data if available
    if (activity.attendance_data) {
      state.attendanceData = activity.attendance_data;
      renderAttendanceData();
    }
    if (activity.salary_data) {
      state.salaryData = activity.salary_data;
      renderSalaryData();
    }
    if (activity.performance_data) {
      state.performanceData = activity.performance_data;
      renderPerformanceData();
    }
    if (activity.adjustment_data) {
      state.adjustmentData = activity.adjustment_data;
      renderPerformanceData();
    }
    if (activity.results) {
      state.resultsData = activity.results;
      renderResultsData();
    }
  } catch (error) {
    console.error('加载活动详情失败:', error);
    showNotification('加载活动详情失败', 'error');
  }
}

// ═══ New Activity ═══

el.btnNewActivity.addEventListener('click', async () => {
  const dialogResult = await openAppDialog({
    title: '新建月度活动',
    message: '为本月绩效奖金创建一个独立核算空间。',
    confirmText: '创建活动',
    cancelText: '取消',
    input: {
      kind: 'month',
      label: '核算月份',
      value: state.currentActivity?.calc_month || getDefaultCalcMonth(),
      placeholder: '选择月份',
      help: '请选择核算月份，年份可用左右按钮切换。',
      maxLength: 7,
      validate: (value) => {
        if (!value) return '请输入核算月份';
        if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(value)) return '月份格式应为 YYYY-MM，例如 2026-04';
        return true;
      },
    },
  });

  if (!dialogResult.confirmed) return;
  const calcMonth = dialogResult.value;

  try {
    const data = await apiJson(`${API_BASE}/runs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ calc_month: calcMonth }),
    });

    if (data.run_id) {
      showNotification('月度活动创建成功', 'success');
      enterActivity(data.run_id);
    }
  } catch (error) {
    console.error('创建活动失败:', error);
    showNotification('创建活动失败', 'error');
  }
});

// ═══ Delete Activity ═══

async function deleteActivity(activityId) {
  const activity = state.activities.find(item => item.run_id === activityId);
  const dialogResult = await openAppDialog({
    title: '删除月度活动',
    message: `将删除 ${activity?.calc_month || '该月度'} 的活动记录和已导入数据。`,
    confirmText: '删除',
    cancelText: '保留',
    tone: 'danger',
  });
  if (!dialogResult.confirmed) return;

  try {
    await apiJson(`${API_BASE}/runs/${activityId}`, { method: 'DELETE' });
    showNotification('已删除', 'success');
    loadActivities();
  } catch (error) {
    showNotification('删除失败', 'error');
  }
}

// ═══ Base Roster ═══

async function loadBaseRoster() {
  try {
    const roster = await apiJson(`${API_BASE}/roster`);
    state.baseRoster = roster;
    updateRosterButton();
    if (state.currentPage === 'foundation') {
      renderFoundationData();
    }
  } catch (error) {
    console.error('加载基础花名册状态失败:', error);
  }
}

function updateRosterButton() {
  if (!el.btnUploadRoster) return;
  if (state.baseRoster?.has_roster) {
    el.btnUploadRoster.textContent = `基础花名册 · ${state.baseRoster.total_employees || 0}人`;
  } else {
    el.btnUploadRoster.textContent = '上传基础花名册';
  }
}

function chooseRosterFile() {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = '.xlsx,.xls';
  input.addEventListener('change', async () => {
    const file = input.files?.[0];
    if (!file) return;
    const formData = new FormData();
    formData.append('file', file);
    el.btnUploadRoster.disabled = true;
    el.btnUploadRoster.textContent = '花名册上传中...';
    try {
      const data = await apiJson(`${API_BASE}/roster`, {
        method: 'POST',
        body: formData,
      });
      state.baseRoster = data.roster;
      updateRosterButton();
      renderFoundationData();
      showNotification('基础花名册已更新，后续新活动会自动引用', 'success');
    } catch (error) {
      showNotification('花名册上传失败: ' + error.message, 'error');
      updateRosterButton();
    } finally {
      el.btnUploadRoster.disabled = false;
    }
  });
  input.click();
}

el.btnUploadRoster?.addEventListener('click', chooseRosterFile);

// ═══ Upload Modal ═══

let uploadType = '';
let uploadFile = null;
let uploadStage = 'select';

const uploadTypeLabels = {
  attendance: '考勤日报表',
  salary: '薪资档案',
  performance: '绩效报表',
  adjustments: '调薪/转正拆分表',
};

function getUploadTitle(type) {
  const label = uploadTypeLabels[type] || '文件';
  return `上传${label}`;
}

function getUploadHint(type) {
  if (type === 'attendance' && state.baseRoster?.has_roster) {
    return `点击选择或拖拽文件到此处 · 将自动引用基础花名册 ${state.baseRoster.filename || ''}`;
  }
  if (type === 'adjustments') {
    return '点击选择或拖拽文件到此处 · 支持平台模板或线下调薪拆分表';
  }
  return '点击选择或拖拽文件到此处 · 支持 .xlsx / .xls';
}

function resetUploadSelection() {
  uploadStage = 'select';
  uploadFile = null;
  el.uploadFileInput.value = '';
  el.uploadZone.hidden = false;
  el.uploadResultPanel.hidden = true;
  el.uploadZone.classList.remove('has-file', 'is-dragover');
  el.uploadZoneTitle.textContent = '选择文件';
  el.uploadZoneSub.textContent = getUploadHint(uploadType);
  el.btnCancelUpload.disabled = false;
  el.btnCloseUploadModal.disabled = false;
  el.btnCancelUpload.textContent = '取消';
  el.btnConfirmUpload.textContent = '确认上传';
  el.btnConfirmUpload.disabled = true;
}

function setUploadFile(file) {
  if (!file) return;
  if (!/\.(xlsx|xls)$/i.test(file.name)) {
    showNotification('仅支持 .xlsx / .xls 格式，请重新选择文件', 'error', { title: '文件格式不支持' });
    return;
  }
  uploadFile = file;
  uploadStage = 'select';
  el.uploadZone.classList.add('has-file');
  el.uploadZoneTitle.textContent = file.name;
  el.uploadZoneSub.textContent = `${formatFileSize(file.size)} · 已选择，点击确认上传`;
  el.btnConfirmUpload.disabled = false;
}

function setUploadBusy() {
  uploadStage = 'uploading';
  el.btnConfirmUpload.disabled = true;
  el.btnConfirmUpload.textContent = '上传中...';
  el.btnCancelUpload.disabled = true;
  el.btnCloseUploadModal.disabled = true;
}

function buildUploadReceiptStats(type, summary = {}) {
  if (type === 'attendance') {
    const total = toNumber(summary.total_employees);
    const matched = toNumber(summary.roster_matched);
    const missing = toNumber(summary.roster_missing);
    return [
      { label: '解析员工', value: total },
      { label: '花名册匹配', value: `${matched}/${total}`, tone: total && matched < total ? 'warning' : '' },
      { label: '花名册缺失', value: missing, tone: missing ? 'warning' : '' },
      { label: '计薪工时', value: formatHours(summary.total_base_hours) },
    ];
  }

  if (type === 'salary') {
    const zeroHourly = toNumber(summary.zero_hourly_count);
    return [
      { label: '薪资档案人数', value: toNumber(summary.total_employees) },
      { label: '有效时薪', value: toNumber(summary.valid_hourly_count) },
      { label: '0时薪', value: zeroHourly, tone: zeroHourly ? 'danger' : '' },
      { label: '平均时薪', value: formatCurrency(summary.avg_hourly_rate) },
    ];
  }

  if (type === 'performance') {
    const distribution = summary.level_distribution || {};
    return [
      { label: '绩效员工', value: toNumber(summary.total_employees) },
      { label: '有分数', value: toNumber(summary.scored_employees) },
      { label: '平均得分', value: toNumber(summary.avg_score).toFixed(2) },
      { label: '等级种类', value: Object.keys(distribution).length },
    ];
  }

  if (type === 'adjustments') {
    return [
      { label: '拆分员工', value: toNumber(summary.total_employees) },
      { label: '分段数量', value: toNumber(summary.total_segments) },
      { label: '有效拆分基数', value: formatCurrency(summary.active_performance_base) },
      { label: '状态', value: '已并入核算', tone: 'warning' },
    ];
  }

  return [];
}

function renderUploadReceipt(type, data, file) {
  const label = uploadTypeLabels[type] || '报表';
  const summary = data.preview?.summary || {};
  const resultFile = data.result_file;
  const stats = buildUploadReceiptStats(type, summary);

  uploadStage = 'result';
  el.uploadZone.hidden = true;
  el.uploadResultPanel.hidden = false;
  el.uploadResultTitle.textContent = `${label}上传完成`;
  el.uploadResultSub.textContent = '本次文件已完成解析，当前页面的数据预览已刷新。';
  el.uploadResultStats.innerHTML = stats.map(item => `
    <div class="upload-result-stat ${escapeHtml(item.tone || '')}">
      <span class="upload-result-label">${escapeHtml(item.label)}</span>
      <span class="upload-result-value">${escapeHtml(item.value)}</span>
    </div>
  `).join('');
  el.uploadResultFile.innerHTML = `
    <span><strong>源文件</strong><br>${escapeHtml(file?.name || '-')} · ${escapeHtml(formatFileSize(file?.size))}</span>
    <span><strong>结果文件</strong><br>${resultFile ? '已生成，可通过本页导出按钮下载' : '未生成'}</span>
  `;
  el.btnCancelUpload.disabled = false;
  el.btnCloseUploadModal.disabled = false;
  el.btnCancelUpload.textContent = '关闭';
  el.btnConfirmUpload.disabled = false;
  el.btnConfirmUpload.textContent = '继续上传';
}

function openUploadModal(type) {
  uploadType = type;
  el.uploadModalTitle.textContent = getUploadTitle(type);
  resetUploadSelection();
  openModal(el.uploadModal, el.uploadZone);
}

function closeUploadModal() {
  if (uploadStage === 'uploading') return;
  closeModal(el.uploadModal);
  uploadType = '';
  uploadFile = null;
  uploadStage = 'select';
}

el.btnCloseUploadModal.addEventListener('click', closeUploadModal);
el.btnCancelUpload.addEventListener('click', closeUploadModal);

el.uploadZone.addEventListener('click', () => {
  el.uploadFileInput.click();
});

el.uploadZone.addEventListener('keydown', (event) => {
  if (event.key !== 'Enter' && event.key !== ' ') return;
  event.preventDefault();
  el.uploadFileInput.click();
});

el.uploadFileInput.addEventListener('change', (e) => {
  setUploadFile(e.target.files[0]);
});

['dragenter', 'dragover'].forEach(eventName => {
  el.uploadZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    el.uploadZone.classList.add('is-dragover');
  });
});

['dragleave', 'drop'].forEach(eventName => {
  el.uploadZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    el.uploadZone.classList.remove('is-dragover');
  });
});

el.uploadZone.addEventListener('drop', (event) => {
  setUploadFile(event.dataTransfer?.files?.[0]);
});

el.btnConfirmUpload.addEventListener('click', async () => {
  if (uploadStage === 'result') {
    resetUploadSelection();
    return;
  }
  if (!uploadFile || !state.currentActivity) return;

  setUploadBusy();

  try {
    const formData = new FormData();
    formData.append('file', uploadFile);
    const selectedFile = uploadFile;

    let endpoint = '';
    if (uploadType === 'attendance') {
      formData.append('calc_month', state.currentActivity.calc_month);
      formData.append('run_id', state.currentActivity.run_id);
      endpoint = `${API_BASE}/import-attendance`;
    } else if (uploadType === 'salary') {
      formData.append('run_id', state.currentActivity.run_id);
      endpoint = `${API_BASE}/import-salary`;
    } else if (uploadType === 'performance') {
      formData.append('run_id', state.currentActivity.run_id);
      endpoint = `${API_BASE}/import-performance`;
    } else if (uploadType === 'adjustments') {
      formData.append('run_id', state.currentActivity.run_id);
      endpoint = `${API_BASE}/import-adjustments`;
    }

    const data = await apiJson(endpoint, {
      method: 'POST',
      body: formData,
    });

    if (data.success) {
      const completedUploadType = uploadType;
      state.lastImportResult = {
        type: completedUploadType,
        hasResultFile: Boolean(data.result_file),
        filename: selectedFile.name,
        summary: data.preview?.summary || {},
        at: new Date().toLocaleTimeString('zh-CN', { hour12: false }),
      };
      showNotification('本次文件已解析，预览和导入回执已更新', 'success', { title: `${uploadTypeLabels[completedUploadType]}导入完成` });

      // Update state
      if (completedUploadType === 'attendance') {
        state.attendanceData = data.preview;
        renderAttendanceData();
      } else if (completedUploadType === 'salary') {
        state.salaryData = data.preview;
        renderSalaryData();
      } else if (completedUploadType === 'performance') {
        state.performanceData = data.preview;
        renderPerformanceData();
      } else if (completedUploadType === 'adjustments') {
        state.adjustmentData = data.preview;
        renderPerformanceData();
      }

      await enterActivity(state.currentActivity.run_id, { preservePage: true });
      renderUploadReceipt(completedUploadType, data, selectedFile);
    } else {
      showNotification(data.detail || '未知错误', 'error', { title: '上传失败' });
    }
  } catch (error) {
    showNotification(error.message, 'error', { title: '上传失败' });
  } finally {
    if (uploadStage === 'uploading') {
      el.btnConfirmUpload.disabled = false;
      el.btnConfirmUpload.textContent = '确认上传';
      el.btnCancelUpload.disabled = false;
      el.btnCloseUploadModal.disabled = false;
    }
  }
});

// ═══ Upload Buttons ═══

el.btnUploadAttendance?.addEventListener('click', () => openUploadModal('attendance'));
el.btnUploadAttendanceEmpty?.addEventListener('click', () => openUploadModal('attendance'));
el.btnUploadSalary?.addEventListener('click', () => openUploadModal('salary'));
el.btnUploadSalaryEmpty?.addEventListener('click', () => openUploadModal('salary'));
el.btnUploadPerformance?.addEventListener('click', () => openUploadModal('performance'));
el.btnUploadPerformanceEmpty?.addEventListener('click', () => openUploadModal('performance'));
el.btnUploadAdjustments?.addEventListener('click', () => openUploadModal('adjustments'));
function downloadAdjustmentsTemplate() {
  const link = document.createElement('a');
  link.href = `${API_BASE}/templates/adjustments/download`;
  link.download = 'FBU调薪转正拆分表模板.xlsx';
  link.click();
}

el.btnDownloadAdjustmentsTemplate?.addEventListener('click', downloadAdjustmentsTemplate);

// ═══ Diagnostics ═══

function renderDiagnosticsPanel() {
  const diagnostics = state.diagnosticsData;
  const summary = diagnostics?.summary;
  if (!summary || (
    !summary.attendance_count
    && !summary.salary_count
    && !summary.performance_count
    && !summary.adjustment_count
  )) {
    return '';
  }

  const issues = diagnostics.issues || [];
  const hasSalaryData = toNumber(summary.salary_count) > 0;
  const hasPerformanceData = toNumber(summary.performance_count) > 0 || toNumber(summary.adjustment_count) > 0;
  const visibleIssues = issues.slice(0, 8);
  const severityLabel = {
    error: '严重',
    warning: '提醒',
    info: '信息',
  };

  return `
    <div class="summary-stats" style="margin-bottom: 16px;">
      <div class="summary-stat">
        <span class="summary-stat-label">考勤</span>
        <span class="summary-stat-value">${summary.attendance_count}</span>
      </div>
      <div class="summary-stat">
        <span class="summary-stat-label">薪资匹配</span>
        <span class="summary-stat-value">${hasSalaryData ? `${summary.matched_salary_count}/${summary.attendance_count}` : '待上传'}</span>
      </div>
      <div class="summary-stat">
        <span class="summary-stat-label">绩效匹配</span>
        <span class="summary-stat-value">${hasPerformanceData ? `${summary.matched_performance_count}/${summary.attendance_count}` : '待上传'}</span>
      </div>
      <div class="summary-stat">
        <span class="summary-stat-label">拆分</span>
        <span class="summary-stat-value">${summary.adjustment_count}</span>
      </div>
      <div class="summary-stat">
        <span class="summary-stat-label">异常</span>
        <span class="summary-stat-value">${summary.error_count}/${summary.issue_count}</span>
      </div>
      ${issues.length ? `
        <button class="btn btn-secondary btn-sm" onclick="exportData('diagnostics')">导出诊断</button>
      ` : ''}
    </div>
    ${visibleIssues.length ? `
      <div class="data-table-container" style="margin-bottom: 16px;">
        <table class="data-table">
          <thead>
            <tr>
              <th>级别</th>
              <th>问题类型</th>
              <th>工号</th>
              <th>姓名</th>
              <th>说明</th>
            </tr>
          </thead>
          <tbody>
            ${visibleIssues.map(issue => `
              <tr>
                <td>${escapeHtml(severityLabel[issue.severity] || issue.severity || '-')}</td>
                <td>${escapeHtml(issue.type || '-')}</td>
                <td>${escapeHtml(issue.employee_id || '-')}</td>
                <td>${escapeHtml(issue.name || '-')}</td>
                <td>${escapeHtml(issue.detail || '-')}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    ` : ''}
  `;
}

function renderImportResultNote(type) {
  const last = state.lastImportResult;
  const typeMatches = last && (
    last.type === type
    || (type === 'performance' && last.type === 'adjustments')
  );
  if (!typeMatches) return '';

  const typeLabel = {
    attendance: '考勤报表',
    salary: '薪资档案',
    performance: '绩效报表',
    adjustments: '调薪/转正拆分表',
  }[last.type] || '报表';

  return `
    <div class="import-result-note">
      <span><strong>${typeLabel}</strong> 已上传并刷新预览${last.hasResultFile ? '，导出结果已生成' : ''}</span>
      <span>${escapeHtml(last.at || '')}</span>
    </div>
  `;
}

function renderImportSummary(items) {
  return `
    <div class="import-summary-strip">
      ${items.map(item => `
        <div class="import-summary-item ${escapeHtml(item.tone || '')}">
          <span class="import-summary-label">${escapeHtml(item.label)}</span>
          <span class="import-summary-value ${item.mono ? 'mono' : ''}">${escapeHtml(item.value)}</span>
        </div>
      `).join('')}
    </div>
  `;
}

function renderImportToolbar({ title, subtitle, filters, filterFn, resetFn, filterValues = {} }) {
  return `
    <div class="import-toolbar">
      <div>
        <div class="import-toolbar-heading">
          <div class="import-toolbar-title">${escapeHtml(title)}</div>
          <div class="import-toolbar-sub">${escapeHtml(subtitle)}</div>
        </div>
        <div class="import-filter-grid">
          ${filters.map(filter => `
            <div class="filter-field">
              <label for="${escapeHtml(filter.id)}">${escapeHtml(filter.label)}</label>
              ${filter.type === 'select' ? `
                <select id="${escapeHtml(filter.id)}" onchange="queueFilter('${escapeHtml(filterFn)}')">
                  ${(filter.options || []).map(option => `
                    <option value="${escapeHtml(option.value)}" ${String(filterValues[filter.key] || 'all') === String(option.value) ? 'selected' : ''}>${escapeHtml(option.label)}</option>
                  `).join('')}
                </select>
              ` : `
                <input type="text" id="${escapeHtml(filter.id)}" value="${escapeHtml(filterValues[filter.key] || '')}" placeholder="${escapeHtml(filter.placeholder || '')}" oninput="queueFilter('${escapeHtml(filterFn)}')">
              `}
            </div>
          `).join('')}
        </div>
      </div>
      <div class="import-toolbar-actions">
        <button class="btn btn-secondary btn-sm" onclick="${escapeHtml(filterFn)}()">筛选</button>
        <button class="btn btn-secondary btn-sm" onclick="${escapeHtml(resetFn)}()">重置</button>
      </div>
    </div>
  `;
}

function renderImportTable(markup, paginationMarkup = '') {
  return `
    <div class="import-table-card">
      <div class="data-table-container">
        ${markup}
      </div>
      ${paginationMarkup}
    </div>
  `;
}

const employeeFilters = {
  attendance: [
    { id: 'filterAttendanceId', key: 'id', label: '工号', placeholder: 'zt0000000' },
    { id: 'filterAttendanceName', key: 'name', label: '姓名', placeholder: '员工姓名' },
    { id: 'filterAttendanceArea', key: 'area', label: '划分区域', placeholder: '区域' },
    { id: 'filterAttendanceDept', key: 'dept', label: '部门', placeholder: '部门全称' },
  ],
  salary: [
    { id: 'filterSalaryId', key: 'id', label: '工号', placeholder: 'zt0000000' },
    { id: 'filterSalaryName', key: 'name', label: '姓名', placeholder: '员工姓名' },
    { id: 'filterSalaryArea', key: 'area', label: '划分区域', placeholder: '区域' },
    { id: 'filterSalaryDept', key: 'dept', label: '部门', placeholder: '部门全称' },
    {
      id: 'filterSalaryQuality',
      key: 'quality',
      label: '导入状态',
      type: 'select',
      options: [
        { value: 'all', label: '全部状态' },
        { value: 'complete', label: '完整' },
        { value: 'zero-hourly', label: '0时薪' },
        { value: 'empty-ratio', label: '绩效比例空' },
        { value: 'fixed-base', label: '固定基数' },
      ],
    },
  ],
  performance: [
    { id: 'filterPerfId', key: 'id', label: '工号', placeholder: 'zt0000000' },
    { id: 'filterPerfName', key: 'name', label: '姓名', placeholder: '员工姓名' },
    { id: 'filterPerfArea', key: 'area', label: '划分区域', placeholder: '区域' },
    { id: 'filterPerfDept', key: 'dept', label: '部门', placeholder: '部门全称' },
    {
      id: 'filterPerfQuality',
      key: 'quality',
      label: '导入状态',
      type: 'select',
      options: [
        { value: 'all', label: '全部状态' },
        { value: 'complete', label: '完整' },
        { value: 'missing-score', label: '缺绩效得分' },
        { value: 'missing-coefficient', label: '缺绩效系数' },
        { value: 'has-adjustment', label: '有调薪拆分' },
      ],
    },
  ],
};

function renderQualityPills(items) {
  const visibleItems = items.filter(item => item.show !== false);
  if (!visibleItems.length) return '-';

  return visibleItems.map(item => `
    <span class="quality-pill ${escapeHtml(item.tone || '')}">
      ${escapeHtml(item.label)}
    </span>
  `).join('');
}

function renderSalaryQualityStatus(emp) {
  const flags = getSalaryQualityFlags(emp);

  return renderQualityPills([
    { label: '完整', tone: 'success', show: flags.complete },
    { label: '0时薪', tone: 'danger', show: flags.zeroHourly },
    { label: '绩效比例空', tone: 'warning', show: flags.emptyRatio },
    { label: '固定基数', tone: 'neutral', show: flags.fixedBase },
  ]);
}

function renderPerformanceQualityStatus(emp, adjustmentIds = getAdjustmentEmployeeIds()) {
  const flags = getPerformanceQualityFlags(emp, adjustmentIds);

  return renderQualityPills([
    { label: '完整', tone: 'success', show: flags.complete },
    { label: '缺得分', tone: 'warning', show: flags.missingScore },
    { label: '缺系数', tone: 'warning', show: flags.missingCoefficient },
    { label: '调薪拆分', tone: 'neutral', show: flags.hasAdjustment },
    { label: '补充行', tone: 'neutral', show: emp.import_source === 'adjustment' },
  ]);
}

// ═══ Render Attendance Data ═══

function renderAttendanceData() {
  if (!state.attendanceData || !state.attendanceData.employees) {
    el.attendanceContent.innerHTML = `
      ${renderDiagnosticsPanel()}
      <div class="empty-state">
        <div class="empty-state-icon">
          <svg width="64" height="64" viewBox="0 0 64 64" fill="none"><path d="M32 8v24l12 12" stroke="#94A3B8" stroke-width="3" stroke-linecap="round"/><circle cx="32" cy="32" r="28" stroke="#94A3B8" stroke-width="3"/></svg>
        </div>
        <h3 class="empty-state-title">暂无考勤数据</h3>
        <p class="empty-state-sub">上传考勤日报表以查看员工工时明细</p>
        <button class="btn btn-primary" onclick="openUploadModal('attendance')">上传考勤日报表</button>
      </div>
    `;
    return;
  }

  const employees = state.attendanceData.employees;
  const filteredEmployees = getFilteredRows('attendance', employees);
  const pageInfo = getPaginatedRows('attendance', filteredEmployees);
  const summary = state.attendanceData.summary;

  el.attendanceContent.innerHTML = `
    ${renderDiagnosticsPanel()}
    ${renderImportResultNote('attendance')}
    <div class="import-workbench">
      ${renderImportSummary([
        { label: '员工总数', value: summary.total_employees, mono: true },
        { label: '花名册匹配', value: `${summary.roster_matched || 0}/${summary.total_employees}`, mono: true, tone: (summary.roster_matched || 0) === summary.total_employees ? 'success' : 'warning' },
        { label: '总工时', value: formatHours(summary.total_base_hours), mono: true },
        { label: '总OT1.5', value: formatHours(summary.total_ot15), mono: true },
      ])}
      ${renderImportToolbar({
        title: '筛选考勤数据',
        subtitle: '按员工信息快速定位，表格内展示本次上传后的考勤解析结果。',
        filters: employeeFilters.attendance,
        filterFn: 'filterAttendanceData',
        resetFn: 'resetAttendanceFilter',
        filterValues: getTableFilter('attendance'),
      })}
      ${renderImportTable(`
      <table class="data-table" id="attendanceTable">
        <thead>
          <tr>
            <th>工号</th>
            <th>姓名</th>
            <th>划分区域</th>
            <th>部门全称</th>
            <th>岗位类型</th>
            <th>夜班</th>
            <th>计薪出勤</th>
            <th>OT1.5</th>
            <th>OT2.0</th>
            <th>病假</th>
            <th>年假</th>
            <th>节假日</th>
          </tr>
        </thead>
        <tbody>
          ${pageInfo.items.length ? pageInfo.items.map(emp => `
            <tr class="${emp.total_base_hours === 0 ? 'row-danger' : ''}"
                data-id="${escapeHtml(emp.employee_id)}"
                data-name="${escapeHtml(emp.name || '')}"
                data-area="${escapeHtml(emp.area || '')}"
                data-dept="${escapeHtml(emp.department || '')}">
              <td>${escapeHtml(emp.employee_id)}</td>
              <td>${escapeHtml(emp.name || '-')}</td>
              <td>${escapeHtml(emp.area || '-')}</td>
              <td>${escapeHtml(emp.department || '-')}</td>
              <td>${formatJobType(emp.job_type)}</td>
              <td>${emp.has_night_shift ? '✓' : '-'}</td>
              <td>${formatHours(emp.total_base_hours)}</td>
              <td>${formatHours(emp.total_ot15)}</td>
              <td>${formatHours(emp.total_ot20)}</td>
              <td>${formatHours(getShiftHours(emp, '病假'))}</td>
              <td>${formatHours(getShiftHours(emp, '年假'))}</td>
              <td>${formatHours(getShiftHours(emp, '节假日'))}</td>
            </tr>
          `).join('') : renderEmptyTableRow(12, '没有匹配的考勤记录')}
        </tbody>
      </table>
      `, renderTablePagination('attendance', pageInfo))}
    </div>
  `;
}

// ═══ Render Salary Data ═══

function renderSalaryData() {
  if (!state.salaryData || !state.salaryData.employees) {
    el.salaryContent.innerHTML = `
      ${renderDiagnosticsPanel()}
      <div class="empty-state">
        <div class="empty-state-icon">
          <svg width="64" height="64" viewBox="0 0 64 64" fill="none"><path d="M32 16v32M20 24h24M20 40h24M16 32h32" stroke="#94A3B8" stroke-width="3" stroke-linecap="round"/></svg>
        </div>
        <h3 class="empty-state-title">暂无薪资数据</h3>
        <p class="empty-state-sub">上传薪资档案以查看时薪匹配情况</p>
        <button class="btn btn-primary" onclick="openUploadModal('salary')">上传薪资档案</button>
      </div>
    `;
    return;
  }

  const employees = state.salaryData.employees;
  const filteredEmployees = getFilteredRows('salary', employees);
  const pageInfo = getPaginatedRows('salary', filteredEmployees);
  const summary = state.salaryData.summary;
  const salaryQualityCounts = employees.reduce((counts, emp) => {
    const flags = getSalaryQualityFlags(emp);
    if (flags.complete) counts.complete += 1;
    if (flags.zeroHourly) counts.zeroHourly += 1;
    if (flags.emptyRatio) counts.emptyRatio += 1;
    if (flags.fixedBase) counts.fixedBase += 1;
    return counts;
  }, { complete: 0, zeroHourly: 0, emptyRatio: 0, fixedBase: 0 });

  el.salaryContent.innerHTML = `
    ${renderDiagnosticsPanel()}
    ${renderImportResultNote('salary')}
    <div class="import-workbench">
      ${renderImportSummary([
        { label: '薪资档案人数', value: summary.total_employees, mono: true },
        { label: '有效时薪', value: summary.valid_hourly_count ?? summary.total_employees, mono: true, tone: 'success' },
        { label: '0时薪', value: summary.zero_hourly_count ?? 0, mono: true, tone: (summary.zero_hourly_count ?? 0) ? 'danger' : '' },
        { label: '有效平均时薪', value: formatCurrency(summary.avg_hourly_rate), mono: true },
        { label: '绩效比例为空', value: salaryQualityCounts.emptyRatio, mono: true, tone: salaryQualityCounts.emptyRatio ? 'warning' : '' },
        { label: '固定基数', value: salaryQualityCounts.fixedBase, mono: true },
      ])}
      ${renderImportToolbar({
        title: '筛选薪资档案',
        subtitle: '这里展示本次上传薪资档案解析出的员工，不代表最终参与核算人数。',
        filters: employeeFilters.salary,
        filterFn: 'filterSalaryData',
        resetFn: 'resetSalaryFilter',
        filterValues: getTableFilter('salary'),
      })}
      ${renderImportTable(`
      <table class="data-table" id="salaryTable">
        <thead>
          <tr>
            <th>工号</th>
            <th>姓名</th>
            <th>划分区域</th>
            <th>部门全称</th>
            <th>时薪</th>
            <th>绩效比例</th>
            <th>固定绩效基数</th>
            <th>导入状态</th>
          </tr>
        </thead>
        <tbody>
          ${pageInfo.items.length ? pageInfo.items.map(emp => `
            <tr class="${getSalaryQualityFlags(emp).zeroHourly || getSalaryQualityFlags(emp).emptyRatio ? 'row-danger' : ''}"
                data-id="${escapeHtml(emp.employee_id)}"
                data-name="${escapeHtml(emp.name || '')}"
                data-area="${escapeHtml(emp.area || '')}"
                data-dept="${escapeHtml(emp.department || '')}">
              <td>${escapeHtml(emp.employee_id)}</td>
              <td>${escapeHtml(emp.name || '-')}</td>
              <td>${escapeHtml(emp.area || '-')}</td>
              <td>${escapeHtml(emp.department || '-')}</td>
              <td>${formatCurrency(emp.hourly_rate)}</td>
              <td>${formatPercent(emp.ratio)}</td>
              <td>${toNumber(emp.fixed_performance_base) > 0 ? formatCurrency(emp.fixed_performance_base) : '-'}</td>
              <td>${renderSalaryQualityStatus(emp)}</td>
            </tr>
          `).join('') : renderEmptyTableRow(8, '没有匹配的薪资记录')}
        </tbody>
      </table>
      `, renderTablePagination('salary', pageInfo))}
    </div>
  `;
}

// ═══ Render Performance Data ═══

function renderPerformanceData() {
  if (!state.performanceData || !state.performanceData.employees) {
    el.performanceContent.innerHTML = `
      ${renderDiagnosticsPanel()}
      <div class="empty-state">
        <div class="empty-state-icon">
          <svg width="64" height="64" viewBox="0 0 64 64" fill="none"><path d="M12 48V20l12-12 12 12 16-16v44H12z" stroke="#94A3B8" stroke-width="3" stroke-linejoin="round"/></svg>
        </div>
        <h3 class="empty-state-title">暂无绩效数据</h3>
        <p class="empty-state-sub">上传绩效报表以查看绩效明细</p>
        <button class="btn btn-primary" onclick="openUploadModal('performance')">上传绩效报表</button>
      </div>
    `;
    return;
  }

  const employees = getPerformanceReviewRows(state.performanceData.employees);
  const filteredEmployees = getFilteredRows('performance', employees);
  const pageInfo = getPaginatedRows('performance', filteredEmployees);
  const summary = state.performanceData.summary;
  const adjustmentSummary = state.adjustmentData?.summary;
  const adjustmentIds = getAdjustmentEmployeeIds();
  const performanceQualityCounts = employees.reduce((counts, emp) => {
    const flags = getPerformanceQualityFlags(emp, adjustmentIds);
    if (flags.complete) counts.complete += 1;
    if (flags.missingScore) counts.missingScore += 1;
    if (flags.missingCoefficient) counts.missingCoefficient += 1;
    if (flags.hasAdjustment) counts.hasAdjustment += 1;
    return counts;
  }, { complete: 0, missingScore: 0, missingCoefficient: 0, hasAdjustment: 0 });
  const performanceSummaryItems = [
    { label: '绩效报表人数', value: summary.total_employees, mono: true },
    { label: '审查行数', value: employees.length, mono: true },
    { label: '平均得分', value: toNumber(summary.avg_score).toFixed(2), mono: true },
    { label: '缺绩效得分', value: performanceQualityCounts.missingScore, mono: true, tone: performanceQualityCounts.missingScore ? 'warning' : '' },
    { label: '缺绩效系数', value: performanceQualityCounts.missingCoefficient, mono: true, tone: performanceQualityCounts.missingCoefficient ? 'warning' : '' },
    ...(adjustmentSummary ? [
      { label: '拆分员工', value: adjustmentSummary.total_employees, mono: true, tone: 'warning' },
      { label: '有效拆分基数', value: formatCurrency(adjustmentSummary.active_performance_base || 0), mono: true },
    ] : []),
    ...Object.entries(summary.level_distribution || {}).map(([level, count]) => ({
      label: level,
      value: `${count}人`,
      mono: true,
    })),
  ];

  el.performanceContent.innerHTML = `
    ${renderDiagnosticsPanel()}
    ${renderImportResultNote('performance')}
    <div class="import-workbench">
      ${renderImportSummary(performanceSummaryItems)}
      ${renderImportToolbar({
        title: '筛选绩效明细',
        subtitle: '绩效得分、等级、系数来自本次上传绩效报表，调薪拆分会在核算时按员工汇总。',
        filters: employeeFilters.performance,
        filterFn: 'filterPerformanceData',
        resetFn: 'resetPerformanceFilter',
        filterValues: getTableFilter('performance'),
      })}
      ${renderImportTable(`
      <table class="data-table" id="performanceTable">
        <thead>
          <tr>
            <th>工号</th>
            <th>姓名</th>
            <th>划分区域</th>
            <th>部门全称</th>
            <th>岗位类型</th>
            <th>绩效得分</th>
            <th>绩效等级</th>
            <th>绩效系数</th>
            <th>导入状态</th>
          </tr>
        </thead>
        <tbody>
          ${pageInfo.items.length ? pageInfo.items.map(emp => `
            <tr class="${getPerformanceQualityFlags(emp, adjustmentIds).missingScore || getPerformanceQualityFlags(emp, adjustmentIds).missingCoefficient ? 'row-danger' : ''}"
                data-id="${escapeHtml(emp.employee_id)}"
                data-name="${escapeHtml(emp.name || '')}"
                data-area="${escapeHtml(emp.area || '')}"
                data-dept="${escapeHtml(emp.department || '')}">
              <td>${escapeHtml(emp.employee_id)}</td>
              <td>${escapeHtml(emp.name || '-')}</td>
              <td>${escapeHtml(emp.area || '-')}</td>
              <td>${escapeHtml(emp.department || '-')}</td>
              <td>${formatJobType(emp.job_type)}</td>
              <td>${!isBlankImportValue(emp.score) ? toNumber(emp.score).toFixed(2) : '-'}</td>
              <td>${escapeHtml(emp.level || '-')}</td>
              <td>${!isBlankImportValue(emp.coefficient) ? formatCoefficient(emp.coefficient) : '-'}</td>
              <td>${renderPerformanceQualityStatus(emp, adjustmentIds)}</td>
            </tr>
          `).join('') : renderEmptyTableRow(9, '没有匹配的绩效记录')}
        </tbody>
      </table>
      `, renderTablePagination('performance', pageInfo))}
    </div>
  `;
}

// ═══ Render Results Data ═══

function updateResultKpis(totalEmployees, totalBonus, avgBonus, exceptionCount) {
  el.kpiResultEmployees.textContent = totalEmployees;
  el.kpiResultBonus.textContent = formatCurrency(totalBonus);
  el.kpiResultAvg.textContent = formatCurrency(avgBonus);
  el.kpiResultErrors.textContent = exceptionCount;
}

function renderResultsToolbar() {
  const filterValues = getTableFilter('results');

  return `
    <div class="result-toolbar">
      <div>
        <div class="result-toolbar-title">核算明细</div>
        <div class="result-filter-grid">
          <div class="filter-field">
            <label for="filterResultsId">工号</label>
            <input type="text" id="filterResultsId" value="${escapeHtml(filterValues.id || '')}" placeholder="zt0000000" oninput="queueFilter('filterResultsData')">
          </div>
          <div class="filter-field">
            <label for="filterResultsName">姓名</label>
            <input type="text" id="filterResultsName" value="${escapeHtml(filterValues.name || '')}" placeholder="员工姓名" oninput="queueFilter('filterResultsData')">
          </div>
          <div class="filter-field">
            <label for="filterResultsArea">划分区域</label>
            <input type="text" id="filterResultsArea" value="${escapeHtml(filterValues.area || '')}" placeholder="区域" oninput="queueFilter('filterResultsData')">
          </div>
          <div class="filter-field">
            <label for="filterResultsDept">部门</label>
            <input type="text" id="filterResultsDept" value="${escapeHtml(filterValues.dept || '')}" placeholder="部门全称" oninput="queueFilter('filterResultsData')">
          </div>
        </div>
      </div>
      <div class="result-toolbar-actions">
        <button class="btn btn-secondary btn-sm" onclick="filterResultsData()">筛选</button>
        <button class="btn btn-secondary btn-sm" onclick="resetResultsFilter()">重置</button>
      </div>
    </div>
  `;
}

function renderBonusResultTable(results, pageInfo) {
  return `
    <div class="bonus-table-card">
      <div class="bonus-table-shell" role="region" aria-label="绩效奖金核算明细">
        <table class="bonus-table" id="resultsTable">
          <colgroup>
            <col style="width: 128px;">
            <col style="width: 140px;">
            <col style="width: 160px;">
            <col style="width: 260px;">
            <col style="width: 110px;">
            <col style="width: 110px;">
            <col style="width: 140px;">
            <col style="width: 110px;">
            <col style="width: 110px;">
            <col style="width: 120px;">
            <col style="width: 156px;">
            <col style="width: 112px;">
          </colgroup>
          <thead>
            <tr>
              <th class="sticky-id">工号</th>
              <th class="sticky-name">姓名</th>
              <th>划分区域</th>
              <th>部门全称</th>
              <th>岗位类型</th>
              <th class="amount-cell">时薪</th>
              <th class="amount-cell">绩效基数</th>
              <th class="metric-cell">绩效比例</th>
              <th class="metric-cell">绩效系数</th>
              <th>异常</th>
              <th class="sticky-bonus">最终奖金</th>
              <th class="sticky-action">操作</th>
            </tr>
          </thead>
          <tbody>
            ${results.length ? results.map(renderBonusResultRow).join('') : renderEmptyTableRow(12, '没有匹配的核算结果')}
          </tbody>
        </table>
      </div>
      ${renderTablePagination('results', pageInfo)}
    </div>
  `;
}

function renderBonusResultRow(result) {
  const exceptions = Array.isArray(result.exceptions)
    ? result.exceptions.filter(Boolean)
    : [];
  const exceptionTitle = exceptions.length ? escapeHtml(exceptions.join('；')) : '';
  const employeeId = String(result.employee_id ?? '');

  return `
    <tr class="${exceptions.length ? 'has-exception' : ''}"
        data-id="${escapeHtml(employeeId)}"
        data-name="${escapeHtml(result.name || '')}"
        data-area="${escapeHtml(result.area || '')}"
        data-dept="${escapeHtml(result.department || '')}">
      <td class="sticky-id employee-id" title="${escapeHtml(employeeId)}">${escapeHtml(employeeId)}</td>
      <td class="sticky-name" title="${escapeHtml(result.name || '-')}">${escapeHtml(result.name || '-')}</td>
      <td class="muted-cell" title="${escapeHtml(result.area || '-')}">${escapeHtml(result.area || '-')}</td>
      <td class="muted-cell" title="${escapeHtml(result.department || '-')}">${escapeHtml(result.department || '-')}</td>
      <td>${formatResultJobType(result.job_type)}</td>
      <td class="amount-cell">${formatCurrency(result.hourly_rate)}</td>
      <td class="amount-cell">${formatCurrency(result.performance_base)}</td>
      <td class="metric-cell">${formatPercent(result.performance_ratio)}</td>
      <td class="metric-cell">${formatCoefficient(result.performance_coefficient)}</td>
      <td>${exceptions.length ? `<span class="exception-chip" tabindex="0" title="${exceptionTitle}" aria-label="异常：${exceptionTitle}">${exceptions.length}项</span>` : '<span class="muted-cell">-</span>'}</td>
      <td class="sticky-bonus"><span class="bonus-value">${formatCurrency(result.performance_bonus)}</span></td>
      <td class="sticky-action">
        <button class="btn btn-secondary btn-sm detail-btn" onclick="showCalcChain(${formatJsArg(employeeId)})" title="查看计算过程">查看</button>
      </td>
    </tr>
  `;
}

function renderResultsData() {
  if (!state.resultsData || state.resultsData.length === 0) {
    updateResultKpis(0, 0, 0, 0);
    el.resultsContent.innerHTML = `
      ${renderDiagnosticsPanel()}
      <div class="empty-state">
        <div class="empty-state-icon">
          <svg width="64" height="64" viewBox="0 0 64 64" fill="none"><rect x="12" y="12" width="40" height="40" rx="4" stroke="#94A3B8" stroke-width="3"/><path d="M24 28h16M24 36h16" stroke="#94A3B8" stroke-width="3" stroke-linecap="round"/></svg>
        </div>
        <h3 class="empty-state-title">暂无核算结果</h3>
        <p class="empty-state-sub">完成前三步后执行核算</p>
        <button class="btn btn-primary" onclick="executeCalculate()">执行核算</button>
      </div>
    `;
    return;
  }

  const results = state.resultsData;
  const filteredResults = getFilteredRows('results', results);
  const pageInfo = getPaginatedRows('results', filteredResults);
  const totalBonus = results.reduce((sum, r) => sum + toNumber(r.performance_bonus), 0);
  const avgBonus = results.length ? totalBonus / results.length : 0;
  const exceptionCount = results.filter(r => (r.exceptions || []).length > 0).length;

  el.resultsContent.innerHTML = `
    ${renderDiagnosticsPanel()}
    <div class="results-workbench">
      ${renderResultsToolbar()}
      ${renderBonusResultTable(pageInfo.items, pageInfo)}
      <div class="result-summary-bar">
        <div class="result-summary-item">
          <span>参与核算</span>
          <span>${results.length}</span>
        </div>
        <div class="result-summary-item">
          <span>奖金总额</span>
          <span>${formatCurrency(totalBonus)}</span>
        </div>
        <div class="result-summary-item">
          <span>平均奖金</span>
          <span>${formatCurrency(avgBonus)}</span>
        </div>
        <div class="result-summary-item">
          <span>异常记录</span>
          <span>${exceptionCount}</span>
        </div>
      </div>
    </div>
  `;

  updateResultKpis(results.length, totalBonus, avgBonus, exceptionCount);
}

// ═══ Calculate ═══

async function executeCalculate() {
  if (!state.currentActivity) return;

  const summary = state.diagnosticsData?.summary;
  if (summary?.error_count > 0) {
    const dialogResult = await openAppDialog({
      title: '继续执行核算？',
      message: `当前仍有 ${summary.error_count} 个严重匹配问题，可能影响核算结果。`,
      confirmText: '继续核算',
      cancelText: '先处理',
      tone: 'warning',
    });
    if (!dialogResult.confirmed) return;
  }

  try {
    const data = await apiJson(`${API_BASE}/calculate/${state.currentActivity.run_id}`, {
      method: 'POST',
    });

    if (data.success) {
      showNotification('核算完成', 'success');
      enterActivity(state.currentActivity.run_id);
    } else {
      showNotification('核算失败: ' + (data.detail || '未知错误'), 'error');
    }
  } catch (error) {
    showNotification('核算失败: ' + error.message, 'error');
  }
}

el.btnCalculate?.addEventListener('click', executeCalculate);
el.btnCalculateEmpty?.addEventListener('click', executeCalculate);

// ═══ Calc Chain ═══

function showCalcChain(employeeId) {
  const emp = state.resultsData?.find(r => r.employee_id === employeeId);
  if (!emp) return;
  const segments = emp.calculation_segments || [];

  if (segments.length) {
    el.calcChainContent.innerHTML = `
      <div class="calc-chain-title">绩效奖金计算过程 - ${escapeHtml(employeeId)}</div>
      <div class="calc-chain-item">调薪/转正拆分核算</div>
      ${segments.map(segment => `
        <div class="calc-chain-item" style="padding-left: 32px;">
          ${escapeHtml(segment.period || '-')} · ${escapeHtml(segment.reason || '-')}：
          $${Number(segment.performance_base || 0).toFixed(2)}
          × ${(Number(segment.performance_ratio || 0) * 100).toFixed(1)}%
          × ${Number(segment.performance_coefficient || 0).toFixed(2)}
          = $${Number(segment.performance_bonus || 0).toFixed(2)}
        </div>
      `).join('')}
      <div class="calc-chain-item calc-chain-result">绩效奖金合计 = $${emp.performance_bonus.toFixed(2)}</div>
      ${(emp.exceptions || []).length ? `<div class="calc-chain-item">异常提示 = ${escapeHtml(emp.exceptions.join('；'))}</div>` : ''}
    `;
    openModal(el.calcChainModal, el.btnCloseCalcChain);
    return;
  }

  const hourlyRate = emp.hourly_rate;
  const baseHours = emp.base_hours;
  const ot15Hours = emp.ot15_hours;
  const ot20Hours = emp.ot20_hours;
  const sickHours = emp.sick_hours;
  const annualHours = emp.annual_hours;
  const holidayHours = emp.holiday_hours;

  const baseSalary = baseHours * hourlyRate;
  const ot15Salary = ot15Hours * hourlyRate * 1.5;
  const ot20Salary = ot20Hours * hourlyRate * 2.0;
  const sickPay = sickHours * hourlyRate;
  const annualPay = annualHours * hourlyRate;
  const holidayPay = holidayHours * hourlyRate;

  el.calcChainContent.innerHTML = `
    <div class="calc-chain-title">绩效奖金计算过程 - ${escapeHtml(employeeId)}</div>
    <div class="calc-chain-item">绩效基数 = $${emp.performance_base.toFixed(2)}</div>
    <div class="calc-chain-item" style="padding-left: 32px;">├── 基础工资 = ${baseHours}h × $${hourlyRate.toFixed(2)} = $${baseSalary.toFixed(2)}</div>
    <div class="calc-chain-item" style="padding-left: 32px;">├── OT1.5工资 = ${ot15Hours}h × $${hourlyRate.toFixed(2)} × 1.5 = $${ot15Salary.toFixed(2)}</div>
    <div class="calc-chain-item" style="padding-left: 32px;">├── OT2.0工资 = ${ot20Hours}h × $${hourlyRate.toFixed(2)} × 2.0 = $${ot20Salary.toFixed(2)}</div>
    <div class="calc-chain-item" style="padding-left: 32px;">├── 病假工资 = ${sickHours}h × $${hourlyRate.toFixed(2)} = $${sickPay.toFixed(2)}</div>
    <div class="calc-chain-item" style="padding-left: 32px;">├── 年假补贴 = ${annualHours}h × $${hourlyRate.toFixed(2)} = $${annualPay.toFixed(2)}</div>
    <div class="calc-chain-item" style="padding-left: 32px;">└── 节日补贴 = ${holidayHours}h × $${hourlyRate.toFixed(2)} = $${holidayPay.toFixed(2)}</div>
    <div class="calc-chain-item">绩效比例 = ${(emp.performance_ratio * 100).toFixed(1)}%</div>
    <div class="calc-chain-item">绩效系数 = ${emp.performance_coefficient.toFixed(2)}</div>
    <div class="calc-chain-item calc-chain-result">绩效奖金 = $${emp.performance_base.toFixed(2)} × ${(emp.performance_ratio * 100).toFixed(1)}% × ${emp.performance_coefficient.toFixed(2)} = $${emp.performance_bonus.toFixed(2)}</div>
    ${(emp.exceptions || []).length ? `<div class="calc-chain-item">异常提示 = ${escapeHtml(emp.exceptions.join('；'))}</div>` : ''}
  `;

  openModal(el.calcChainModal, el.btnCloseCalcChain);
}

function closeCalcChainModal() {
  closeModal(el.calcChainModal);
}

el.btnCloseCalcChainModal?.addEventListener('click', closeCalcChainModal);
el.btnCloseCalcChain?.addEventListener('click', closeCalcChainModal);

// ═══ Export ═══

async function exportData(type) {
  if (!state.currentActivity) {
    showNotification('请先选择或创建活动', 'error');
    return;
  }

  try {
    // 调用后端导出API
    const data = await apiJson(`${API_BASE}/runs/${state.currentActivity.run_id}/export-excel?type=${type}`);

    if (data.success) {
      // 下载文件（URL编码文件名）
      const encodedFilename = encodeURIComponent(data.filename);
      const downloadUrl = `${API_BASE}/runs/${state.currentActivity.run_id}/download/${encodedFilename}`;
      const link = document.createElement('a');
      link.href = downloadUrl;
      link.download = data.filename;
      link.click();
      showNotification('导出成功', 'success');
    } else {
      showNotification('导出失败: ' + (data.detail || '未知错误'), 'error');
    }
  } catch (error) {
    showNotification('导出失败: ' + error.message, 'error');
  }
}

el.btnExportAttendance?.addEventListener('click', () => exportData('attendance'));
el.btnExportSalary?.addEventListener('click', () => exportData('salary'));
el.btnExportPerformance?.addEventListener('click', () => exportData('performance'));
el.btnExportResults?.addEventListener('click', () => exportData('results'));

// ═══ Attendance Filter ═══

const tableFilterInputIds = {
  attendance: {
    id: 'filterAttendanceId',
    name: 'filterAttendanceName',
    area: 'filterAttendanceArea',
    dept: 'filterAttendanceDept',
  },
  salary: {
    id: 'filterSalaryId',
    name: 'filterSalaryName',
    area: 'filterSalaryArea',
    dept: 'filterSalaryDept',
    quality: 'filterSalaryQuality',
  },
  performance: {
    id: 'filterPerfId',
    name: 'filterPerfName',
    area: 'filterPerfArea',
    dept: 'filterPerfDept',
    quality: 'filterPerfQuality',
  },
  results: {
    id: 'filterResultsId',
    name: 'filterResultsName',
    area: 'filterResultsArea',
    dept: 'filterResultsDept',
  },
};

function readTableFilters(type) {
  if (type === 'exceptions') {
    return {
      severity: String(document.getElementById('filterExceptionSeverity')?.value ?? 'all').trim(),
      source: String(document.getElementById('filterExceptionSource')?.value ?? 'all').trim(),
      query: String(document.getElementById('filterExceptionQuery')?.value ?? '').trim(),
    };
  }

  const ids = tableFilterInputIds[type] || {};
  return {
    id: String(document.getElementById(ids.id)?.value ?? '').trim(),
    name: String(document.getElementById(ids.name)?.value ?? '').trim(),
    area: String(document.getElementById(ids.area)?.value ?? '').trim(),
    dept: String(document.getElementById(ids.dept)?.value ?? '').trim(),
    quality: String(document.getElementById(ids.quality)?.value ?? 'all').trim(),
  };
}

function renderTableByType(type, focusSnapshot = null) {
  if (type === 'attendance') renderAttendanceData();
  if (type === 'salary') renderSalaryData();
  if (type === 'performance') renderPerformanceData();
  if (type === 'results') renderResultsData();
  if (type === 'exceptions') renderExceptionQueue();
  restoreInputFocus(focusSnapshot);
}

function applyTableFilter(type) {
  const focusSnapshot = captureInputFocus();
  state.tableFilters[type] = readTableFilters(type);
  getTablePagination(type).page = 1;
  renderTableByType(type, focusSnapshot);
}

function resetTableFilter(type) {
  resetTableControls(type);
  renderTableByType(type);
}

function changeTablePage(type, page) {
  getTablePagination(type).page = Number(page) || 1;
  renderTableByType(type);
}

function changeTablePageSize(type, pageSize) {
  const size = Number(pageSize);
  const pagination = getTablePagination(type);
  pagination.pageSize = TABLE_PAGE_SIZE_OPTIONS.includes(size) ? size : DEFAULT_TABLE_PAGE_SIZE;
  pagination.page = 1;
  renderTableByType(type);
}

function filterAttendanceData() {
  applyTableFilter('attendance');
}

function resetAttendanceFilter() {
  resetTableFilter('attendance');
}

// ═══ Salary Filter ═══

function filterSalaryData() {
  applyTableFilter('salary');
}

function resetSalaryFilter() {
  resetTableFilter('salary');
}

// ═══ Performance Filter ═══

function filterPerformanceData() {
  applyTableFilter('performance');
}

function resetPerformanceFilter() {
  resetTableFilter('performance');
}

// ═══ Results Filter ═══

function filterResultsData() {
  applyTableFilter('results');
}

function resetResultsFilter() {
  resetTableFilter('results');
}

// ═══ Exception Filter ═══

function filterExceptionData() {
  applyTableFilter('exceptions');
}

function resetExceptionFilter() {
  resetTableFilter('exceptions');
}

function quickFilterExceptionSource(sourceKey) {
  state.tableFilters.exceptions = {
    ...getTableFilter('exceptions'),
    source: sourceKey || 'all',
  };
  getTablePagination('exceptions').page = 1;
  renderExceptionQueue();
}

function quickFilterExceptionType(type) {
  state.tableFilters.exceptions = {
    ...getTableFilter('exceptions'),
    query: type || '',
  };
  getTablePagination('exceptions').page = 1;
  renderExceptionQueue();
}

function locateExceptionIssue(sourceKey, employeeId = '', name = '', issueType = '') {
  const meta = exceptionSourceTargetMeta[sourceKey] || exceptionSourceTargetMeta.system;

  if (meta.page === 'exceptions') {
    state.tableFilters.exceptions = {
      ...getTableFilter('exceptions'),
      source: sourceKey || 'all',
      query: employeeId || name || issueType || '',
    };
    getTablePagination('exceptions').page = 1;
    renderExceptionQueue();
    return;
  }

  state.tableFilters[meta.page] = {
    id: employeeId || '',
    name: employeeId ? '' : name,
    area: '',
    dept: '',
    quality: 'all',
  };
  getTablePagination(meta.page).page = 1;
  navigateTo(meta.page);
  renderTableByType(meta.page);
}

// ═══ Notification ═══

function showNotification(message, type = 'info', options = {}) {
  const toastConfig = {
    success: { title: '操作完成', icon: 'OK' },
    error: { title: '操作失败', icon: '!' },
    warning: { title: '需要注意', icon: '!' },
    info: { title: '提示', icon: 'i' },
  };
  const config = toastConfig[type] || toastConfig.info;
  const title = options.title || config.title;
  const duration = options.duration ?? (type === 'error' ? null : 3600);
  const region = el.toastRegion || document.getElementById('toastRegion');
  if (!region) return;

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.setAttribute('role', type === 'error' ? 'alert' : 'status');
  toast.innerHTML = `
    <div class="toast-icon" aria-hidden="true">${escapeHtml(config.icon)}</div>
    <div>
      <div class="toast-title">${escapeHtml(title)}</div>
      <div class="toast-message">${escapeHtml(message)}</div>
    </div>
    <button class="toast-close" type="button" aria-label="关闭通知">×</button>
  `;

  const dismiss = () => {
    if (!toast.isConnected || toast.classList.contains('is-leaving')) return;
    toast.classList.add('is-leaving');
    setTimeout(() => toast.remove(), 180);
  };

  toast.querySelector('.toast-close')?.addEventListener('click', dismiss);
  region.appendChild(toast);
  if (duration !== null && duration !== false && duration > 0) {
    setTimeout(dismiss, duration);
  }
}

// ═══ Init ═══

document.addEventListener('DOMContentLoaded', () => {
  loadBaseRoster();
  loadActivities();
});
