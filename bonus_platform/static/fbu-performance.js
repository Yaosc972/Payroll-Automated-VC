/**
 * FBU美洲绩效奖金核算 - 数据看板交互逻辑
 */

// ═══ State ═══

const state = {
  currentPage: 'workbench',
  activityStep: 'people',
  currentActivity: null,
  activities: [],
  attendanceData: null,
  salaryData: null,
  performanceData: null,
  adjustmentData: null,
  supplementalLeaveData: null,
  baseOverrideData: null,
  ruleLists: null,
  diagnosticsData: null,
  resultsData: null,
  baseRoster: null,
  lastImportResult: null,
  foundationRunDetails: {},
  foundationLoadingRunId: '',
  activityListLoadingRunIds: new Set(),
  workbenchSelectedResult: '',
  workbenchResultFilter: 'all',
  workbenchTaskFilter: 'open',
  workbenchSupplementLevel: '',
  workbenchSupplementDraft: {
    employeeId: '',
    name: '',
    score: '',
  },
  workbenchPreviousAttendanceFile: null,
  tableFilters: {
    attendance: {},
    salary: {},
    performance: {},
    supplementalLeave: {},
    baseOverrides: {},
    results: {},
    exceptions: {},
  },
  tablePagination: {
    attendance: { page: 1, pageSize: 50 },
    salary: { page: 1, pageSize: 50 },
    performance: { page: 1, pageSize: 50 },
    supplementalLeave: { page: 1, pageSize: 50 },
    baseOverrides: { page: 1, pageSize: 50 },
    results: { page: 1, pageSize: 50 },
    exceptions: { page: 1, pageSize: 50 },
  },
};

const ACTIVITY_STEPS = [
  { key: 'people', label: '人员核对' },
  { key: 'attendance', label: '考勤工时' },
  { key: 'salary', label: '薪资数据' },
  { key: 'performance', label: '绩效数据' },
  { key: 'check', label: '核算检查' },
  { key: 'export', label: '确认导出' },
];

const STEP_MATERIALS = {
  people: [
    { materialKey: 'roster', label: '花名册', tag: '必传', hint: '上传人员基础资料', uploadType: 'roster', fileField: 'roster_file', required: true },
  ],
  attendance: [
    { materialKey: 'attendance', label: '考勤日报', tag: '必传', hint: '上传OEHR当月考勤日报表', uploadType: 'attendance', fileField: 'attendance_file', required: true },
    { materialKey: 'previousAttendance', label: '上月考勤', tag: '96工时制员工', hint: '上传OEHR上月考勤日报表', uploadType: 'previousAttendance', fileField: 'previous_attendance_file', required: false, conditional: 'needsPreviousAttendance' },
    { materialKey: 'supplementalLeave', label: '补充假勤', tag: '必传', hint: '上传线下sickpay与年假补充数据', uploadType: 'supplementalLeave', fileField: 'supplemental_leave_file', required: true },
  ],
  salary: [
    { materialKey: 'salary', label: '薪资档案', tag: '必传', hint: '上传OEHR最新薪资档案（含离职）', uploadType: 'salary', fileField: 'salary_file', required: true },
    { materialKey: 'adjustments', label: '当月转正/调薪表', tag: '按需', hint: '上传OEHR转正调薪流程', uploadType: 'adjustments', fileField: 'adjustment_file', required: false },
  ],
  performance: [
    { materialKey: 'performance', label: '绩效报表', tag: '必传', hint: '上传OEHR当月绩效报表', uploadType: 'performance', fileField: 'performance_file', required: true },
  ],
  check: [],
  export: [],
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

function formatScore(value) {
  if (value === null || value === undefined || value === '') return '-';
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

function needsPreviousAttendance(activity) {
  const context = activity?.attendance_data?.summary?.attendance_context || {};
  return Boolean(context.required || activity?.previous_attendance_file || state.workbenchPreviousAttendanceFile);
}

function getMaterialStatus(material, activity) {
  if (material.conditional === 'needsPreviousAttendance' && !needsPreviousAttendance(activity)) {
    return { visible: false };
  }
  const fileName = activity?.[material.fileField] || '';
  if (fileName) {
    return { visible: true, tone: 'success', text: '已上传', fileName };
  }
  if (material.materialKey === 'previousAttendance' && state.workbenchPreviousAttendanceFile) {
    return { visible: true, tone: 'warning', text: '已选择', fileName: state.workbenchPreviousAttendanceFile.name };
  }
  return {
    visible: true,
    tone: material.required ? 'warning' : 'neutral',
    text: material.required ? '未上传' : '按需',
    fileName: '',
  };
}

function renderMaterialRow(material, activity) {
  const status = getMaterialStatus(material, activity);
  if (!status.visible) return '';
  const actionText = status.fileName ? '重新上传' : '上传';
  return `
    <div class="material-row ${escapeHtml(status.tone)}">
      <div class="material-marker"></div>
      <div class="material-main">
        <div class="material-title">
          <strong>${escapeHtml(material.label)}</strong>
          <span class="mini-tag">${escapeHtml(material.tag)}</span>
          <span class="status-badge ${escapeHtml(status.tone)}">${escapeHtml(status.text)}</span>
        </div>
        <div class="material-hint">${escapeHtml(material.hint)}</div>
      </div>
      <div class="material-file">${escapeHtml(status.fileName || '-')}</div>
      <button class="btn btn-secondary btn-sm" type="button" onclick="openWorkbenchUpload(${formatJsArg(material.uploadType)})">${actionText}</button>
    </div>
  `;
}

function renderStepMaterials(stepKey, activity) {
  const rows = STEP_MATERIALS[stepKey] || [];
  if (!rows.length) return '';
  return `
    <section class="step-section material-list">
      ${rows.map(row => renderMaterialRow(row, activity)).join('')}
    </section>
  `;
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

  if (type === 'supplementalLeave') {
    return {
      pending: row.confirmation_status === 'pending',
      confirmed: row.confirmation_status === 'confirmed',
      excluded: row.confirmation_status === 'excluded',
      include: Boolean(row.include_in_base),
      termination: Boolean(row.is_termination_settlement),
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
  btnToggleSidebar: document.getElementById('btnToggleSidebar'),
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
  btnAddPerformanceSupplement: document.getElementById('btnAddPerformanceSupplement'),
  btnAddPerformanceSupplementEmpty: document.getElementById('btnAddPerformanceSupplementEmpty'),
  btnUploadAdjustments: document.getElementById('btnUploadAdjustments'),
  btnDownloadAdjustmentsTemplate: document.getElementById('btnDownloadAdjustmentsTemplate'),
  btnExportPerformance: document.getElementById('btnExportPerformance'),
  btnCalculate: document.getElementById('btnCalculate'),
  btnCalculateEmpty: document.getElementById('btnCalculateEmpty'),
  btnExportResults: document.getElementById('btnExportResults'),
  btnExportDiagnostics: document.getElementById('btnExportDiagnostics'),
  workbenchContent: document.getElementById('workbenchContent'),
  workbenchUploadRoster: document.getElementById('workbenchUploadRoster'),
  workbenchUploadAttendance: document.getElementById('workbenchUploadAttendance'),
  workbenchUploadPreviousAttendance: document.getElementById('workbenchUploadPreviousAttendance'),
  workbenchUploadSalary: document.getElementById('workbenchUploadSalary'),
  workbenchUploadPerformance: document.getElementById('workbenchUploadPerformance'),
  workbenchUploadAdjustments: document.getElementById('workbenchUploadAdjustments'),
  workbenchUploadSupplementalLeave: document.getElementById('workbenchUploadSupplementalLeave'),

  // Pages
  pages: {
    workbench: document.getElementById('pageWorkbench'),
    activities: document.getElementById('pageActivities'),
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
  supplementalLeaveContent: document.getElementById('supplementalLeaveContent'),
  resultsContent: document.getElementById('resultsContent'),

  // Upload Modal
  uploadModal: document.getElementById('uploadModal'),
  uploadModalTitle: document.getElementById('uploadModalTitle'),
  uploadZone: document.getElementById('uploadZone'),
  uploadZoneTitle: document.getElementById('uploadZoneTitle'),
  uploadZoneSub: document.getElementById('uploadZoneSub'),
  uploadFileInput: document.getElementById('uploadFileInput'),
  previousAttendanceField: document.getElementById('previousAttendanceField'),
  previousAttendanceInput: document.getElementById('previousAttendanceInput'),
  previousAttendanceSub: document.getElementById('previousAttendanceSub'),
  btnChoosePreviousAttendance: document.getElementById('btnChoosePreviousAttendance'),
  btnClearPreviousAttendance: document.getElementById('btnClearPreviousAttendance'),
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

  // Performance supplement modal
  performanceSupplementModal: document.getElementById('performanceSupplementModal'),
  supplementEmployeeId: document.getElementById('supplementEmployeeId'),
  supplementEmployeeName: document.getElementById('supplementEmployeeName'),
  supplementScore: document.getElementById('supplementScore'),
  supplementLevel: document.getElementById('supplementLevel'),
  supplementCoefficient: document.getElementById('supplementCoefficient'),
  supplementNote: document.getElementById('supplementNote'),
  btnClosePerformanceSupplementModal: document.getElementById('btnClosePerformanceSupplementModal'),
  btnCancelPerformanceSupplement: document.getElementById('btnCancelPerformanceSupplement'),
  btnSavePerformanceSupplement: document.getElementById('btnSavePerformanceSupplement'),

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
let composingFilterInput = null;
let pendingCompositionFilter = null;

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

function queueFilter(filterName, event = null) {
  if (event?.isComposing || (event?.target && event.target === composingFilterInput)) {
    pendingCompositionFilter = filterName;
    return;
  }

  if (composingFilterInput) {
    pendingCompositionFilter = filterName;
    return;
  }

  clearTimeout(filterTimers[filterName]);
  filterTimers[filterName] = setTimeout(() => {
    window[filterName]?.();
  }, 180);
}

document.addEventListener('compositionstart', (event) => {
  if (event.target instanceof HTMLInputElement) {
    composingFilterInput = event.target;
    pendingCompositionFilter = null;
  }
});

document.addEventListener('compositionend', () => {
  const filterName = pendingCompositionFilter;
  composingFilterInput = null;
  pendingCompositionFilter = null;
  if (filterName) queueFilter(filterName);
});

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

function setSidebarCollapsed(collapsed) {
  document.body.classList.toggle('sidebar-collapsed', collapsed);
  if (el.btnToggleSidebar) {
    const label = collapsed ? '展开侧边栏' : '收起侧边栏';
    el.btnToggleSidebar.setAttribute('aria-label', label);
    el.btnToggleSidebar.setAttribute('title', label);
    el.btnToggleSidebar.setAttribute('aria-expanded', String(!collapsed));
  }
  localStorage.setItem('fbuSidebarCollapsed', collapsed ? '1' : '0');
}

function setActivityStep(stepKey) {
  if (!ACTIVITY_STEPS.some(step => step.key === stepKey)) return;
  state.activityStep = stepKey;
  renderWorkbench();
}

function getStepIndex(stepKey) {
  return ACTIVITY_STEPS.findIndex(step => step.key === stepKey);
}

function getActivityStepFromActivity(activity = state.currentActivity) {
  if (!activity) return 'people';
  if (activity.status === 'completed' || Array.isArray(activity.results) && activity.results.length) return 'export';
  if (activity.diagnostics || activity.base_override_data || activity.adjustment_data) return 'check';
  if (activity.performance_data || activity.performance_file) return 'performance';
  if (activity.salary_data || activity.salary_file) return 'salary';
  if (activity.attendance_data || activity.attendance_file || activity.supplemental_leave_file) return 'attendance';
  return 'people';
}

function navigateTo(page) {
  const targetPage = page in el.pages ? page : 'workbench';
  state.currentPage = targetPage;

  // Update nav items
  el.navItems.forEach(item => {
    const isActive = item.dataset.page === targetPage;
    item.classList.toggle('active', isActive);
    if (isActive) {
      item.setAttribute('aria-current', 'page');
    } else {
      item.removeAttribute('aria-current');
    }
  });

  // Show/hide pages
  Object.keys(el.pages).forEach(key => {
    el.pages[key].hidden = key !== targetPage;
  });

  // Update title
  const titles = {
    workbench: { title: 'FBU美洲绩效核算', subtitle: state.currentActivity?.calc_month || '' },
    activities: { title: 'FBU美洲绩效核算', subtitle: '活动列表' },
  };

  const title = titles[targetPage] || titles.workbench;
  if (el.moduleEyebrow) el.moduleEyebrow.textContent = '绩效管理模块';
  if (el.pageTitle) el.pageTitle.textContent = title.title;
  if (el.pageSubtitle) el.pageSubtitle.textContent = title.subtitle;

  // Load page data
  if (targetPage === 'workbench') {
    renderWorkbench();
    if (!state.activities.length) loadActivities();
  } else if (targetPage === 'activities') {
    loadActivities();
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

el.btnToggleSidebar?.addEventListener('click', () => {
  setSidebarCollapsed(!document.body.classList.contains('sidebar-collapsed'));
});

// ═══ Activities ═══

async function loadActivities() {
  try {
    const data = await apiJson(`${API_BASE}/runs`);

    state.activities = data.runs || [];
    if (state.currentPage === 'workbench') {
      await loadRuleLists();
    }
    renderActivities();
    updateActivityKPIs();
    loadActivityListDetails();
    if (state.currentPage === 'workbench') {
      if (!state.currentActivity) {
        const defaultActivity = getWorkbenchDefaultActivity();
        if (defaultActivity?.run_id) {
          await enterActivity(defaultActivity.run_id, { preservePage: true, silent: true });
        } else {
          renderWorkbench();
        }
      } else {
        renderWorkbench();
      }
    }
  } catch (error) {
    console.error('加载活动列表失败:', error);
  }
}

function hasWorkbenchActivityPayload(activity) {
  return activity?.status === 'completed'
    || toNumber(activity?.current_step) > 0
    || toNumber(activity?.total_employees) > 0
    || toNumber(activity?.total_bonus) > 0;
}

function getWorkbenchDefaultActivity() {
  const activities = [...state.activities];
  return activities.find(hasWorkbenchActivityPayload) || getLatestActivity();
}

function getWorkbenchActivity() {
  return state.currentActivity || getWorkbenchDefaultActivity();
}

function getWorkbenchResults(activity = getWorkbenchActivity()) {
  if (Array.isArray(state.resultsData) && state.currentActivity?.run_id === activity?.run_id) {
    return state.resultsData;
  }
  return Array.isArray(activity?.results) ? activity.results : [];
}

function getWorkbenchDiagnostics(activity = getWorkbenchActivity()) {
  return activity?.diagnostics || state.diagnosticsData || null;
}

function getWorkbenchSupplementalRows(activity = getWorkbenchActivity()) {
  return activity?.supplemental_leave_data?.rows || state.supplementalLeaveData?.rows || [];
}

async function loadRuleLists() {
  if (state.ruleLists) return state.ruleLists;
  const data = await apiJson(`${API_BASE}/rule-lists`);
  state.ruleLists = data;
  return data;
}

function getWorkbenchSourceKey(label) {
  const map = {
    '考勤报表': 'attendance',
    '薪资档案': 'salary',
    '绩效报表': 'performance',
    '调薪拆分': 'adjustments',
    '补充假勤': 'supplementalLeave',
  };
  return map[label] || '';
}

function getWorkbenchSourceTone(batch) {
  if (String(batch.status || '').includes('已解析')) return 'ready';
  if (String(batch.status || '').includes('待上传')) return 'pending';
  return 'optional';
}

function renderWorkbenchSourceCard(batch) {
  const sourceKey = getWorkbenchSourceKey(batch.type);
  const tone = getWorkbenchSourceTone(batch);
  const canUpload = Boolean(sourceKey);
  return `
    <article class="workbench-source-card ${tone}">
      <div>
        <div class="workbench-source-top">
          <div class="workbench-source-title">${escapeHtml(batch.type)}</div>
          ${batch.status}
        </div>
        <div class="workbench-source-file" title="${escapeHtml(batch.file)}">${escapeHtml(batch.file)}</div>
        <div class="workbench-source-meta">
          <span class="workbench-chip ${tone === 'ready' ? 'success' : tone === 'pending' ? 'warning' : ''}">${escapeHtml(batch.metric)}</span>
          <span class="workbench-chip">${escapeHtml(batch.quality)}</span>
        </div>
      </div>
      <div class="workbench-source-meta">
        <span>${escapeHtml(batch.meta || '-')}</span>
      </div>
      <div class="workbench-source-actions">
        ${canUpload ? `<button class="btn btn-secondary btn-sm" type="button" onclick="openWorkbenchUpload(${formatJsArg(sourceKey)})">${tone === 'ready' ? '替换' : '上传'}</button>` : ''}
      </div>
    </article>
  `;
}

function renderWorkbenchPreviousAttendanceCard(activity) {
  const context = activity?.attendance_data?.summary?.attendance_context;
  const hasPrevious = ['ready', 'covered', 'complete'].includes(context?.status);
  const needsPrevious = context?.required || state.workbenchPreviousAttendanceFile;
  const tone = hasPrevious ? 'ready' : needsPrevious ? 'pending' : 'optional';
  const fileLabel = state.workbenchPreviousAttendanceFile?.name
    || (hasPrevious ? '已随考勤纳入跨月上下文' : '未选择');
  return `
    <article class="workbench-source-card ${tone}">
      <div>
        <div class="workbench-source-top">
          <div class="workbench-source-title">上月考勤</div>
          <span class="status-badge ${hasPrevious ? 'success' : needsPrevious ? 'warning' : 'neutral'}">${hasPrevious ? '已覆盖' : needsPrevious ? '待随考勤上传' : '按需'}</span>
        </div>
        <div class="workbench-source-file" title="${escapeHtml(fileLabel)}">${escapeHtml(fileLabel)}</div>
        <div class="workbench-source-meta">
          <span class="workbench-chip ${hasPrevious ? 'success' : needsPrevious ? 'warning' : ''}">96工时制上下文</span>
          <span class="workbench-chip">${escapeHtml(context?.status || '自动判断')}</span>
        </div>
      </div>
      <div class="workbench-source-meta">
        <span>${escapeHtml(context?.message || '仅在首段跨月需要时使用')}</span>
      </div>
      <div class="workbench-source-actions">
        <button class="btn btn-secondary btn-sm" type="button" onclick="openWorkbenchUpload('previousAttendance')">${state.workbenchPreviousAttendanceFile ? '重选' : '选择'}</button>
        <button class="btn btn-primary btn-sm" type="button" onclick="openWorkbenchUpload('attendance')">上传考勤</button>
      </div>
    </article>
  `;
}

function renderMaintainedRuleList(kind, activity) {
  const lists = state.ruleLists || {};
  const isWorkHour = kind === 'workHour';
  const rows = isWorkHour ? (lists.work_hour_employees || []) : (lists.fixed_base_employees || []);
  const title = isWorkHour ? '96工时制员工' : '固定基数人员';
  const confirmed = isWorkHour
    ? (activity?.base_override_data?.employees || []).some(row => row.rule_type === '96工时制')
    : (activity?.base_override_data?.employees || []).some(row => row.rule_type === '线下固定基数覆盖');
  return `
    <section class="step-section maintained-list">
      <div class="section-head compact">
        <div>
          <h3>${title}</h3>
          <p>${isWorkHour ? '本月默认沿用已确认的4名员工。' : '本月默认沿用已确认名单。'}</p>
        </div>
        <div class="section-actions">
          <span class="status-badge ${confirmed ? 'success' : 'warning'}">${confirmed ? '已确认' : '未确认'}</span>
          <button class="btn btn-secondary btn-sm" type="button" onclick="toggleMaintainedRuleEditor(${formatJsArg(kind)})">管理名单</button>
          <button class="btn btn-primary btn-sm" type="button" onclick="confirmMaintainedRuleList(${formatJsArg(kind)})">确认名单</button>
        </div>
      </div>
      <div class="compact-list-table">
        <table class="data-table">
          <thead><tr><th class="sticky-employee-id">工号</th><th class="sticky-employee-name">姓名</th>${isWorkHour ? '' : '<th>固定基数</th>'}<th>状态</th></tr></thead>
          <tbody>
            ${rows.map(row => `
              <tr>
                <td class="sticky-employee-id">${escapeHtml(row.employee_id)}</td>
                <td class="sticky-employee-name">${escapeHtml(row.name || '-')}</td>
                ${isWorkHour ? '' : `<td class="amount-cell">${formatCurrency(row.fixed_performance_base)}</td>`}
                <td>${row.active === false ? '停用' : '启用'}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
      <div class="maintained-editor-placeholder" data-maintained-editor="${escapeHtml(kind)}" hidden>
        名单维护入口保留在当前页面，后续任务再补完整编辑能力。
      </div>
    </section>
  `;
}

function buildWorkbenchTasks(activity = getWorkbenchActivity()) {
  if (!activity) return [];
  const tasks = [];
  const diagnostics = getWorkbenchDiagnostics(activity);
  const issues = (diagnostics?.issues || []).filter(Boolean);

  getSupplementalSuggestionRows(getWorkbenchSupplementalRows(activity)).slice(0, 6).forEach(row => {
    const hours = getSupplementalSuggestedHours(row);
    tasks.push({
      id: `leave-${row.row_id}`,
      tone: 'warning',
      title: `${row.employee_id} ${row.name || ''} 补充假勤`,
      meta: `${row.leave_type || '-'} · 建议计入 ${formatHours(hours)} · ${row.suggested_month || '-'} / ${row.suggested_period || '-'}`,
      actions: `
        <button class="btn btn-primary btn-sm" type="button" onclick="applyWorkbenchSupplementalSuggestion(${escapeHtml(JSON.stringify(row.row_id))}, ${hours})">计入建议小时</button>
        <button class="btn btn-secondary btn-sm" type="button" onclick="applyWorkbenchSupplementalSuggestion(${escapeHtml(JSON.stringify(row.row_id))}, 0)">排除</button>
        <button class="btn btn-secondary btn-sm" type="button" onclick="locateWorkbenchSupplementalRow(${escapeHtml(JSON.stringify(row.row_id))})">查看行</button>
      `,
    });
  });

  issues.filter(issue => issue.severity === 'error').slice(0, 4).forEach((issue, index) => {
    const source = getExceptionSource(issue);
    tasks.push({
      id: `issue-${index}-${issue.employee_id || issue.type || ''}`,
      tone: 'danger',
      title: issue.type || '严重异常',
      meta: `${issue.employee_id || '-'} ${issue.name || ''} · ${issue.detail || ''}`,
      actions: `<button class="btn btn-secondary btn-sm" type="button" onclick="locateExceptionIssue(${formatJsArg(source.key)}, ${formatJsArg(issue.employee_id || '')}, ${formatJsArg(issue.name || '')}, ${formatJsArg(issue.type || '')})">定位</button>`,
    });
  });

  if (tasks.length === 0) {
    tasks.push({
      id: 'ready',
      tone: 'success',
      title: '暂无阻断任务',
      meta: '当前导入状态可继续核算或导出结果。',
      actions: `<button class="btn btn-primary btn-sm" type="button" onclick="executeCalculate()">执行核算</button>`,
    });
  }

  return tasks;
}

function getFilteredWorkbenchTasks(tasks) {
  if (state.workbenchTaskFilter === 'all') return tasks;
  if (state.workbenchTaskFilter === 'source') return tasks.filter(task => task.id.startsWith('source-'));
  if (state.workbenchTaskFilter === 'leave') return tasks.filter(task => task.id.startsWith('leave-'));
  if (state.workbenchTaskFilter === 'issue') return tasks.filter(task => task.id.startsWith('issue-'));
  return tasks.filter(task => task.tone !== 'success');
}

function renderWorkbenchTasks(activity) {
  const tasks = buildWorkbenchTasks(activity);
  const visibleTasks = getFilteredWorkbenchTasks(tasks);
  const suggestionCount = getSupplementalSuggestionRows(getWorkbenchSupplementalRows(activity)).length;
  const filters = [
    ['open', `待处理 ${tasks.filter(task => task.tone !== 'success').length}`],
    ['source', '数据源'],
    ['leave', `假勤 ${suggestionCount}`],
    ['issue', '异常'],
    ['all', '全部'],
  ];
  return `
    <section class="workbench-panel workbench-task-board">
      <div class="workbench-panel-head">
        <div>
          <div class="workbench-panel-title">待处理任务</div>
          <div class="workbench-panel-sub">规则能自动判断的直接进入结果，只保留需要人确认的动作。</div>
        </div>
        <div class="workbench-source-actions">
          ${filters.map(([key, label]) => `
            <button class="workbench-segment ${state.workbenchTaskFilter === key ? 'active' : ''}" type="button" onclick="setWorkbenchTaskFilter(${formatJsArg(key)})">${escapeHtml(label)}</button>
          `).join('')}
        </div>
      </div>
      <div class="workbench-task-list">
        ${visibleTasks.map(task => `
          <article class="workbench-task ${escapeHtml(task.tone)}">
            <div>
              <div class="workbench-task-title">${escapeHtml(task.title)}</div>
              <div class="workbench-task-meta">${escapeHtml(task.meta)}</div>
            </div>
            <div class="workbench-task-actions">${task.actions}</div>
          </article>
        `).join('')}
      </div>
      ${renderWorkbenchPerformanceSupplement()}
    </section>
  `;
}

async function confirmMaintainedRuleList(kind) {
  if (!state.currentActivity?.run_id) return;
  if (!state.ruleLists) await loadRuleLists();
  const data = await apiJson(`${API_BASE}/runs/${state.currentActivity.run_id}/rule-lists/confirm`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(state.ruleLists),
  });
  state.baseOverrideData = data.preview;
  state.currentActivity.base_override_file = '页面维护';
  state.currentActivity.base_override_data = data.preview;
  renderWorkbench();
  showNotification(kind === 'workHour' ? '96工时制名单已确认' : '固定基数名单已确认', 'success');
}

function toggleMaintainedRuleEditor(kind) {
  const panel = document.querySelector(`[data-maintained-editor="${kind}"]`);
  if (panel) panel.hidden = !panel.hidden;
}

function renderWorkbenchPerformanceSupplement() {
  // 绩效补录不再打开弹窗，离职/漏绩效员工直接在工作台内联写入。
  const levelOptions = ['S', 'A', 'B', 'C', 'D'];
  const draft = state.workbenchSupplementDraft || {};
  return `
    <div class="workbench-inline-form" aria-label="绩效补录">
      <div class="workbench-inline-field">
        <label for="workbenchSupplementEmployeeId">工号</label>
        <input id="workbenchSupplementEmployeeId" type="text" value="${escapeHtml(draft.employeeId || '')}" placeholder="zt0000000" oninput="updateWorkbenchSupplementDraft()">
      </div>
      <div class="workbench-inline-field">
        <label for="workbenchSupplementName">姓名</label>
        <input id="workbenchSupplementName" type="text" value="${escapeHtml(draft.name || '')}" placeholder="员工姓名" oninput="updateWorkbenchSupplementDraft()">
      </div>
      <div class="workbench-inline-field">
        <label for="workbenchSupplementScore">得分</label>
        <input id="workbenchSupplementScore" type="number" step="0.01" value="${escapeHtml(draft.score || '')}" placeholder="0.00" oninput="updateWorkbenchSupplementDraft()">
      </div>
      <div class="workbench-inline-field">
        <label>等级</label>
        <div class="workbench-source-actions">
          ${levelOptions.map(level => `
            <button class="workbench-segment ${state.workbenchSupplementLevel === level ? 'active' : ''}" type="button" onclick="setWorkbenchSupplementLevel(${formatJsArg(level)})">${level}</button>
          `).join('')}
        </div>
      </div>
      <button class="btn btn-primary" id="btnWorkbenchSaveSupplement" type="button" onclick="saveWorkbenchPerformanceSupplement()">保存补录</button>
    </div>
  `;
}

function renderWorkbenchResultRow(result) {
  const employeeId = String(result.employee_id ?? '');
  const expanded = state.workbenchSelectedResult === employeeId;
  const exceptions = Array.isArray(result.exceptions) ? result.exceptions.filter(Boolean) : [];
  return `
    <tr class="${exceptions.length ? 'has-exception' : ''}">
      <td class="employee-id">${escapeHtml(employeeId)}</td>
      <td>${escapeHtml(result.name || '-')}</td>
      <td>${escapeHtml(result.area || '-')}</td>
      <td>${escapeHtml(result.department || '-')}</td>
      <td>${formatResultJobType(result.job_type)}</td>
      <td class="amount-cell">${formatCurrency(result.hourly_rate)}</td>
      <td class="amount-cell">${formatCurrency(result.performance_base)}</td>
      <td class="metric-cell">${formatPercent(result.performance_ratio)}</td>
      <td class="metric-cell">${formatCoefficient(result.performance_coefficient)}</td>
      <td>${exceptions.length ? `<span class="exception-chip">${exceptions.length}项</span>` : '<span class="muted-cell">-</span>'}</td>
      <td class="amount-cell"><span class="bonus-value">${formatCurrency(result.performance_bonus)}</span></td>
      <td><button class="btn btn-secondary btn-sm" type="button" onclick="toggleWorkbenchResultDetail(${formatJsArg(employeeId)})">${expanded ? '收起' : '展开'}</button></td>
    </tr>
    ${expanded ? renderWorkbenchCalculationDetail(result) : ''}
  `;
}

function renderWorkbenchCalculationDetail(result) {
  const segments = result.calculation_segments || [];
  const detail = segments.length ? segments.map(segment => `
    <div class="workbench-calc-line">
      <span>${escapeHtml(segment.period || '-')} · ${escapeHtml(segment.reason || '-')}</span>
      <strong>${formatCurrency(segment.performance_base)} × ${formatPercent(segment.performance_ratio)} × ${formatCoefficient(segment.performance_coefficient)} = ${formatCurrency(segment.performance_bonus)}</strong>
    </div>
  `).join('') : `
    <div class="workbench-calc-line">
      <span>标准绩效基数路径</span>
      <strong>${formatCurrency(result.performance_base)} × ${formatPercent(result.performance_ratio)} × ${formatCoefficient(result.performance_coefficient)} = ${formatCurrency(result.performance_bonus)}</strong>
    </div>
  `;
  return `
    <tr class="workbench-detail-row">
      <td colspan="12">
        <div class="workbench-calc-detail">
          ${detail}
          ${(result.exceptions || []).length ? `<div class="workbench-calc-line"><span>异常提示</span><strong>${escapeHtml(result.exceptions.join('；'))}</strong></div>` : ''}
        </div>
      </td>
    </tr>
  `;
}

function getWorkbenchFilteredResults(results) {
  if (state.workbenchResultFilter === 'exception') {
    return results.filter(result => (result.exceptions || []).length);
  }
  if (state.workbenchResultFilter === 'split') {
    return results.filter(result => (result.calculation_segments || []).length > 1);
  }
  if (state.workbenchResultFilter === 'bonus') {
    return [...results].sort((a, b) => toNumber(b.performance_bonus) - toNumber(a.performance_bonus));
  }
  return results;
}

function renderWorkbenchResults(activity) {
  const results = getWorkbenchResults(activity);
  const filteredResults = getWorkbenchFilteredResults(results).slice(0, 80);
  const filters = [
    ['all', `全部 ${results.length}`],
    ['exception', `异常 ${results.filter(result => (result.exceptions || []).length).length}`],
    ['split', `拆分 ${results.filter(result => (result.calculation_segments || []).length > 1).length}`],
    ['bonus', '奖金排序'],
  ];
  return `
    <section class="workbench-panel workbench-result-panel">
      <div class="workbench-panel-head">
        <div>
          <div class="workbench-panel-title">核算结果</div>
          <div class="workbench-panel-sub">沿用现有结果明细口径，白/夜班拆行在行内展开。</div>
        </div>
        <div class="workbench-source-actions">
          ${filters.map(([key, label]) => `
            <button class="workbench-segment ${state.workbenchResultFilter === key ? 'active' : ''}" type="button" onclick="setWorkbenchResultFilter(${formatJsArg(key)})">${escapeHtml(label)}</button>
          `).join('')}
          <button class="btn btn-secondary btn-sm" type="button" onclick="exportData('results')" ${results.length ? '' : 'disabled'}>导出</button>
          <button class="btn btn-primary btn-sm" type="button" onclick="executeCalculate()">执行核算</button>
        </div>
      </div>
      <div class="workbench-table-wrap">
        <table class="workbench-result-table">
          <thead>
            <tr>
              <th>工号</th>
              <th>姓名</th>
              <th>划分区域</th>
              <th>部门全称</th>
              <th>岗位类型</th>
              <th class="amount-cell">时薪</th>
              <th class="amount-cell">绩效基数</th>
              <th class="metric-cell">绩效比例</th>
              <th class="metric-cell">绩效系数</th>
              <th>异常</th>
              <th class="amount-cell">最终奖金</th>
              <th>计算</th>
            </tr>
          </thead>
          <tbody>
            ${filteredResults.length ? filteredResults.map(renderWorkbenchResultRow).join('') : renderEmptyTableRow(12, results.length ? '当前筛选没有记录' : '暂无核算结果')}
          </tbody>
        </table>
      </div>
    </section>
  `;
}

function renderWorkbenchAudit(activity) {
  const diagnostics = getWorkbenchDiagnostics(activity);
  const summary = diagnostics?.summary || {};
  const supplementalSummary = activity?.supplemental_leave_data?.summary || {};
  const adjustmentSummary = activity?.adjustment_data?.summary || {};
  const baseSummary = activity?.base_override_data?.summary || {};
  const cards = [
    ['严重异常', toNumber(summary.error_count), `${toNumber(summary.issue_count)} 项诊断`, toNumber(summary.error_count) ? 'danger' : 'success'],
    ['补充假勤', `${toNumber(supplementalSummary.pending_count)} 待确认`, `计入 ${formatHours(supplementalSummary.include_hours)}`, toNumber(supplementalSummary.pending_count) ? 'warning' : 'success'],
    ['调薪拆分', toNumber(adjustmentSummary.total_events || adjustmentSummary.total_segments), `人工 ${toNumber(adjustmentSummary.manual_split_required)} · 自动 ${toNumber(adjustmentSummary.auto_split_ready)}`, toNumber(adjustmentSummary.manual_split_required) ? 'warning' : 'success'],
    ['96工时规则', toNumber(baseSummary.active_count), `固定基数 ${formatCurrency(baseSummary.active_fixed_base)}`, ''],
  ];
  return `
    <section class="workbench-panel workbench-audit-ledger">
      <div class="workbench-panel-head">
        <div>
          <div class="workbench-panel-title">审计明细</div>
          <div class="workbench-panel-sub">只展示会影响结果或需要复核的口径。</div>
        </div>
        <button class="btn btn-secondary btn-sm" type="button" onclick="setActivityStep('check')">查看核算检查</button>
      </div>
      <div class="workbench-audit-grid">
        ${cards.map(([label, value, note, tone]) => `
          <article class="workbench-audit-card">
            <div class="workbench-audit-label">${escapeHtml(label)}</div>
            <div class="workbench-audit-value ${escapeHtml(tone)}">${escapeHtml(value)}</div>
            <div class="workbench-audit-note">${escapeHtml(note)}</div>
          </article>
        `).join('')}
      </div>
    </section>
  `;
}

function renderWorkbench() {
  if (!el.workbenchContent) return;
  const activity = getWorkbenchActivity();
  if (!activity) {
    el.workbenchContent.innerHTML = `
      <div class="workbench-empty">
        <h2>暂无月度活动</h2>
        <p>先创建月度活动。</p>
        <button class="btn btn-primary" type="button" onclick="document.getElementById('btnNewActivity')?.click()">新建活动</button>
      </div>
    `;
    return;
  }
  const activeStep = ACTIVITY_STEPS.find(step => step.key === state.activityStep) || ACTIVITY_STEPS[0];
  el.workbenchContent.innerHTML = `
    <section class="activity-titlebar">
      <div>
        <button class="link-button" type="button" onclick="navigateTo('activities')">返回活动列表</button>
        <h2>${escapeHtml(activity.calc_month || '-')} FBU美洲绩效核算</h2>
        <span class="activity-id">活动 ${escapeHtml(activity.run_id || '-')}</span>
      </div>
      <div class="activity-title-actions">
        ${state.activityStep === 'check' ? '<button class="btn btn-primary btn-sm" type="button" onclick="executeCalculate()">开始核算</button>' : ''}
        ${state.activityStep === 'export' ? '<button class="btn btn-primary btn-sm" type="button" onclick="exportData(\'results\')">导出结果</button>' : ''}
      </div>
    </section>
    ${renderActivityStepper(activity)}
    <section class="activity-step-body">
      ${renderStepHeader(activeStep, activity)}
      ${renderStepContent(activity)}
    </section>
  `;
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
  const hasAdjustmentEvents = toNumber(adjustmentSummary.total_events) > 0;
  addRow({
    type: '调薪拆分',
    file: activity.adjustment_file,
    required: false,
    metric: activity.adjustment_file
      ? (hasAdjustmentEvents
        ? `${toNumber(adjustmentSummary.total_events)}事件`
        : `${toNumber(adjustmentSummary.total_employees)}人`)
      : '-',
    quality: activity.adjustment_file
      ? (hasAdjustmentEvents
        ? `自动${toNumber(adjustmentSummary.auto_split_ready)} / 人工${toNumber(adjustmentSummary.manual_split_required)}`
        : `${toNumber(adjustmentSummary.total_segments)}段`)
      : '-',
    meta: activity.adjustment_file
      ? (hasAdjustmentEvents
        ? '按生效日和考勤日报自动拆分'
        : `有效基数 ${formatCurrency(adjustmentSummary.active_performance_base)}`)
      : '试用期/转正/调薪分段',
  });

  const supplementalSummary = activity.supplemental_leave_data?.summary || {};
  addRow({
    type: '补充假勤',
    file: activity.supplemental_leave_file,
    required: false,
    metric: activity.supplemental_leave_file ? `${toNumber(supplementalSummary.total_rows)}行` : '-',
    quality: activity.supplemental_leave_file
      ? `${toNumber(supplementalSummary.pending_count)}待确认`
      : '-',
    meta: activity.supplemental_leave_file ? `计入 ${formatHours(supplementalSummary.include_hours)}` : 'sickpay&年假补充确认',
  });

  const baseOverrideSummary = activity.base_override_data?.summary || {};
  addRow({
    type: '工时规则 / 固定基数例外',
    file: activity.base_override_file,
    required: false,
    metric: activity.base_override_file ? `${toNumber(baseOverrideSummary.active_count)}行计入` : '-',
    quality: activity.base_override_file
      ? formatCurrency(baseOverrideSummary.active_fixed_base)
      : '-',
    meta: activity.base_override_file
      ? `排除 ${toNumber(baseOverrideSummary.excluded_count)}行`
      : '96工时制标记 / 固定基数例外',
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
            <span>基础花名册仅在月度活动的“人员核对”步骤上传，避免脱离活动上下文单独更新。</span>
            <button class="btn btn-secondary btn-sm" type="button" onclick="navigateTo('activities')">查看月度活动</button>
          </div>
          <div class="module-action-card">
            <strong>调薪/转正拆分模板</strong>
            <span>用于处理试用期转正、调薪分段等线下拆分场景。</span>
            <button class="btn btn-secondary btn-sm" type="button" onclick="downloadAdjustmentsTemplate()">下载模板</button>
          </div>
          <div class="module-action-card">
            <strong>96工时制 / 固定基数名单</strong>
            <span>这两类名单改为在月度活动页面内维护并确认，不再提供规则表上传入口。</span>
            <button class="btn btn-secondary btn-sm" type="button" onclick="navigateTo('activities')">进入活动维护</button>
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
  { key: 'baseOverrides', label: '工时规则 / 固定基数例外' },
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
  if (text.includes('固定基数') || text.includes('96工时')) {
    return { key: 'baseOverrides', label: '工时规则 / 固定基数例外' };
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
            <input type="text" id="filterExceptionQuery" value="${escapeHtml(filters.query || '')}" placeholder="工号、姓名、问题类型、说明" oninput="queueFilter('filterExceptionData', event)">
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
  const stepMap = {
    attendance: 'attendance',
    salary: 'salary',
    performance: 'performance',
    exceptions: 'check',
    results: 'export',
  };
  await enterActivity(activityId, { preservePage: true });
  setActivityStep(stepMap[page] || getActivityStepFromActivity(state.currentActivity));
  navigateTo('workbench');
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
    state.activityStep = getActivityStepFromActivity(activity);
    state.foundationRunDetails[activity.run_id] = activity;
    state.diagnosticsData = activity.diagnostics || null;
    if (state.currentPage === 'workbench') {
      await loadRuleLists();
    }

    if (preservePage && state.currentPage !== 'activities') {
      navigateTo(state.currentPage);
    } else {
      navigateTo('workbench');
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
    state.supplementalLeaveData = activity.supplemental_leave_data || null;
    state.baseOverrideData = activity.base_override_data || null;
    renderSupplementalLeaveData();
    if (activity.results) {
      state.resultsData = activity.results;
      renderResultsData();
    }
    renderWorkbench();
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
    if (el.btnUploadRoster) {
      el.btnUploadRoster.disabled = true;
      el.btnUploadRoster.textContent = '花名册上传中...';
    }
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
      if (el.btnUploadRoster) {
        el.btnUploadRoster.disabled = false;
      }
    }
  });
  input.click();
}

el.btnUploadRoster?.addEventListener('click', chooseRosterFile);

// ═══ Upload Modal ═══

let uploadType = '';
let uploadFile = null;
let previousAttendanceFile = null;
let uploadStage = 'select';

const uploadTypeLabels = {
  attendance: '考勤日报表',
  salary: '薪资档案',
  performance: '绩效报表',
  adjustments: '调薪/转正拆分表',
  supplementalLeave: '补充假勤表',
};

function getWorkbenchUploadInput(type) {
  const map = {
    roster: el.workbenchUploadRoster,
    attendance: el.workbenchUploadAttendance,
    previousAttendance: el.workbenchUploadPreviousAttendance,
    salary: el.workbenchUploadSalary,
    performance: el.workbenchUploadPerformance,
    adjustments: el.workbenchUploadAdjustments,
    supplementalLeave: el.workbenchUploadSupplementalLeave,
  };
  return map[type] || null;
}

function openWorkbenchUpload(type) {
  const input = getWorkbenchUploadInput(type);
  if (!input) return;
  if (!state.currentActivity && !['roster', 'previousAttendance'].includes(type)) {
    showNotification('请先进入一个月度活动，再上传该活动的数据文件', 'warning', { title: '缺少月度活动' });
    return;
  }
  input.value = '';
  input.click();
}

async function uploadWorkbenchRosterFile(file) {
  if (!file) return;
  const formData = new FormData();
  formData.append('file', file);
  if (el.btnUploadRoster) {
    el.btnUploadRoster.disabled = true;
    el.btnUploadRoster.textContent = '花名册上传中...';
  }
  try {
    const data = await apiJson(`${API_BASE}/roster`, {
      method: 'POST',
      body: formData,
    });
    state.baseRoster = data.roster;
    updateRosterButton();
    renderFoundationData();
    renderWorkbench();
    showNotification('基础花名册已更新', 'success');
  } catch (error) {
    showNotification('花名册上传失败: ' + error.message, 'error');
  } finally {
    if (el.btnUploadRoster) {
      el.btnUploadRoster.disabled = false;
      updateRosterButton();
    }
  }
}

async function uploadWorkbenchFile(type, file) {
  if (!file || !state.currentActivity) return;
  if (!/\.(xlsx|xls)$/i.test(file.name)) {
    showNotification('仅支持 .xlsx / .xls 格式，请重新选择文件', 'error', { title: '文件格式不支持' });
    return;
  }

  const formData = new FormData();
  formData.append('file', file);
  let endpoint = '';

  if (type === 'attendance') {
    formData.append('calc_month', state.currentActivity.calc_month);
    formData.append('run_id', state.currentActivity.run_id);
    if (state.workbenchPreviousAttendanceFile) {
      formData.append('previous_attendance', state.workbenchPreviousAttendanceFile);
    }
    endpoint = `${API_BASE}/import-attendance`;
  } else if (type === 'salary') {
    formData.append('run_id', state.currentActivity.run_id);
    endpoint = `${API_BASE}/import-salary`;
  } else if (type === 'performance') {
    formData.append('run_id', state.currentActivity.run_id);
    endpoint = `${API_BASE}/import-performance`;
  } else if (type === 'adjustments') {
    formData.append('run_id', state.currentActivity.run_id);
    endpoint = `${API_BASE}/import-adjustments`;
  } else if (type === 'supplementalLeave') {
    formData.append('run_id', state.currentActivity.run_id);
    endpoint = `${API_BASE}/import-supplemental-leave`;
  }

  if (!endpoint) return;

  try {
    showNotification(`${uploadTypeLabels[type] || '文件'}上传中`, 'info', { duration: 1200 });
    const data = await apiJson(endpoint, {
      method: 'POST',
      body: formData,
    });

    if (!data.success) {
      showNotification(data.detail || '未知错误', 'error', { title: '上传失败' });
      return;
    }

    state.lastImportResult = {
      type,
      hasResultFile: Boolean(data.result_file),
      filename: file.name,
      summary: data.preview?.summary || {},
      context: data.preview?.summary?.attendance_context || null,
      at: new Date().toLocaleTimeString('zh-CN', { hour12: false }),
    };

    if (type === 'attendance') {
      state.attendanceData = data.preview;
      state.workbenchPreviousAttendanceFile = null;
      renderAttendanceData();
    } else if (type === 'salary') {
      state.salaryData = data.preview;
      renderSalaryData();
    } else if (type === 'performance') {
      state.performanceData = data.preview;
      renderPerformanceData();
    } else if (type === 'adjustments') {
      state.adjustmentData = data.preview;
      renderPerformanceData();
    } else if (type === 'supplementalLeave') {
      state.supplementalLeaveData = data.preview;
      renderSupplementalLeaveData();
    }

    showNotification(`${uploadTypeLabels[type]}已上传并刷新工作台`, 'success');
    await enterActivity(state.currentActivity.run_id, { preservePage: true });
    renderWorkbench();
  } catch (error) {
    showNotification(error.message, 'error', { title: '上传失败' });
  }
}

function handleWorkbenchUploadChange(type, event) {
  const file = event.target.files?.[0];
  if (!file) return;
  if (type === 'previousAttendance') {
    if (!/\.(xlsx|xls)$/i.test(file.name)) {
      showNotification('仅支持 .xlsx / .xls 格式，请重新选择文件', 'error', { title: '文件格式不支持' });
      return;
    }
    state.workbenchPreviousAttendanceFile = file;
    renderWorkbench();
    showNotification('上月考勤已暂存，将随本月考勤一起上传', 'success');
    return;
  }
  if (type === 'roster') {
    uploadWorkbenchRosterFile(file);
    return;
  }
  uploadWorkbenchFile(type, file);
}

function setWorkbenchTaskFilter(filter) {
  state.workbenchTaskFilter = filter || 'open';
  renderWorkbench();
}

function setWorkbenchResultFilter(filter) {
  state.workbenchResultFilter = filter || 'all';
  renderWorkbench();
}

function toggleWorkbenchResultDetail(employeeId) {
  state.workbenchSelectedResult = state.workbenchSelectedResult === employeeId ? '' : employeeId;
  renderWorkbench();
}

function updateWorkbenchSupplementDraft() {
  state.workbenchSupplementDraft = {
    employeeId: document.getElementById('workbenchSupplementEmployeeId')?.value || '',
    name: document.getElementById('workbenchSupplementName')?.value || '',
    score: document.getElementById('workbenchSupplementScore')?.value || '',
  };
}

function setWorkbenchSupplementLevel(level) {
  updateWorkbenchSupplementDraft();
  state.workbenchSupplementLevel = state.workbenchSupplementLevel === level ? '' : level;
  renderWorkbench();
}

async function saveWorkbenchPerformanceSupplement() {
  if (!state.currentActivity) return;
  const employeeIdInput = document.getElementById('workbenchSupplementEmployeeId');
  const employeeId = employeeIdInput?.value.trim() || '';
  const name = document.getElementById('workbenchSupplementName')?.value.trim() || '';
  const score = document.getElementById('workbenchSupplementScore')?.value.trim() || '';
  const level = state.workbenchSupplementLevel;
  const button = document.getElementById('btnWorkbenchSaveSupplement');

  if (!employeeId) {
    showNotification('请填写工号', 'warning', { title: '无法保存' });
    employeeIdInput?.focus();
    return;
  }
  if (!score && !level) {
    showNotification('请至少填写绩效得分或绩效等级', 'warning', { title: '无法保存' });
    document.getElementById('workbenchSupplementScore')?.focus();
    return;
  }

  if (button) {
    button.disabled = true;
    button.textContent = '保存中';
  }

  try {
    const data = await apiJson(`${API_BASE}/runs/${encodeURIComponent(state.currentActivity.run_id)}/performance-supplement`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        employee_id: employeeId,
        name,
        score,
        level,
        coefficient: '',
        note: '工作台内联补录',
      }),
    });

    state.performanceData = data.preview;
    state.currentActivity.performance_data = data.preview;
    if (!state.currentActivity.performance_file) {
      state.currentActivity.performance_file = '页面绩效补录';
    }
    state.workbenchSupplementLevel = '';
    state.workbenchSupplementDraft = { employeeId: '', name: '', score: '' };
    renderPerformanceData();
    renderWorkbench();
    showNotification('绩效补录已保存', 'success');
  } catch (error) {
    showNotification(error.message, 'error', { title: '保存失败' });
    if (button) {
      button.disabled = false;
      button.textContent = '保存补录';
    }
  }
}

async function applyWorkbenchSupplementalSuggestion(rowId, suggestedHours) {
  await applySupplementalLeaveSuggestion(rowId, suggestedHours);
  renderWorkbench();
}

function locateWorkbenchSupplementalRow(rowId) {
  setActivityStep('attendance');
  renderWorkbench();
}

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
  if (type === 'supplementalLeave') {
    return '点击选择或拖拽文件到此处 · 支持薪酬 sickpay&年假原始表';
  }
  return '点击选择或拖拽文件到此处 · 支持 .xlsx / .xls';
}

function resetUploadSelection() {
  uploadStage = 'select';
  uploadFile = null;
  previousAttendanceFile = null;
  el.uploadFileInput.value = '';
  if (el.previousAttendanceInput) el.previousAttendanceInput.value = '';
  el.uploadZone.hidden = false;
  if (el.previousAttendanceField) {
    el.previousAttendanceField.hidden = uploadType !== 'attendance';
  }
  el.uploadResultPanel.hidden = true;
  el.uploadZone.classList.remove('has-file', 'is-dragover');
  el.uploadZoneTitle.textContent = '选择文件';
  el.uploadZoneSub.textContent = getUploadHint(uploadType);
  if (el.previousAttendanceSub) el.previousAttendanceSub.textContent = '用于96工时制跨月首段';
  if (el.btnClearPreviousAttendance) el.btnClearPreviousAttendance.hidden = true;
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

function setPreviousAttendanceFile(file) {
  if (!file) return;
  if (!/\.(xlsx|xls)$/i.test(file.name)) {
    showNotification('仅支持 .xlsx / .xls 格式，请重新选择文件', 'error', { title: '文件格式不支持' });
    return;
  }
  previousAttendanceFile = file;
  if (el.previousAttendanceSub) {
    el.previousAttendanceSub.textContent = `${file.name} · ${formatFileSize(file.size)}`;
  }
  if (el.btnClearPreviousAttendance) el.btnClearPreviousAttendance.hidden = false;
}

function clearPreviousAttendanceFile() {
  previousAttendanceFile = null;
  if (el.previousAttendanceInput) el.previousAttendanceInput.value = '';
  if (el.previousAttendanceSub) el.previousAttendanceSub.textContent = '用于96工时制跨月首段';
  if (el.btnClearPreviousAttendance) el.btnClearPreviousAttendance.hidden = true;
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
    const stats = [
      { label: '解析员工', value: total },
      { label: '花名册匹配', value: `${matched}/${total}`, tone: total && matched < total ? 'warning' : '' },
      { label: '花名册缺失', value: missing, tone: missing ? 'warning' : '' },
      { label: '计薪工时', value: formatHours(summary.total_base_hours) },
    ];
    const context = summary.attendance_context;
    if (context?.required) {
      stats.push({
        label: '96跨月上下文',
        value: context.status === 'complete' ? '已覆盖' : '缺少上月',
        tone: context.status === 'complete' ? 'success' : 'warning',
      });
    }
    return stats;
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
    if (toNumber(summary.total_events) > 0) {
      return [
        { label: '调薪事件', value: toNumber(summary.total_events) },
        { label: '自动拆分', value: toNumber(summary.auto_split_ready), tone: 'success' },
        { label: '需人工拆分', value: toNumber(summary.manual_split_required), tone: summary.manual_split_required ? 'warning' : 'success' },
        { label: '状态', value: summary.manual_split_required ? '部分需补拆分表' : '自动并入核算', tone: summary.manual_split_required ? 'warning' : 'success' },
      ];
    }
    return [
      { label: '拆分员工', value: toNumber(summary.total_employees) },
      { label: '分段数量', value: toNumber(summary.total_segments) },
      { label: '有效拆分基数', value: formatCurrency(summary.active_performance_base) },
      { label: '状态', value: '已并入核算', tone: 'warning' },
    ];
  }

  if (type === 'supplementalLeave') {
    return [
      { label: '解析行数', value: toNumber(summary.total_rows) },
      { label: '待确认', value: toNumber(summary.pending_count), tone: summary.pending_count ? 'warning' : '' },
      { label: '确认计入', value: toNumber(summary.include_count), tone: 'success' },
      { label: '计入小时', value: formatHours(summary.include_hours) },
    ];
  }

  return [];
}

function renderUploadReceipt(type, data, file) {
  const label = uploadTypeLabels[type] || '报表';
  const summary = data.preview?.summary || {};
  const resultFile = data.result_file;
  const stats = buildUploadReceiptStats(type, summary);
  const attendanceContext = type === 'attendance' ? summary.attendance_context : null;

  uploadStage = 'result';
  el.uploadZone.hidden = true;
  if (el.previousAttendanceField) el.previousAttendanceField.hidden = true;
  el.uploadResultPanel.hidden = false;
  el.uploadResultTitle.textContent = `${label}上传完成`;
  el.uploadResultSub.textContent = attendanceContext?.message || '本次文件已完成解析，当前页面的数据预览已刷新。';
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
  if (['attendance', 'salary', 'performance', 'adjustments', 'supplementalLeave'].includes(type) && !state.currentActivity) {
    showNotification('请先进入一个月度活动，再上传该活动的数据文件', 'warning', { title: '缺少月度活动' });
    return;
  }
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
  previousAttendanceFile = null;
  uploadStage = 'select';
}

el.btnCloseUploadModal.addEventListener('click', closeUploadModal);
el.btnCancelUpload.addEventListener('click', closeUploadModal);

function resetPerformanceSupplementForm() {
  if (!el.performanceSupplementModal) return;
  el.supplementEmployeeId.value = '';
  el.supplementEmployeeName.value = '';
  el.supplementScore.value = '';
  el.supplementLevel.value = '';
  el.supplementCoefficient.value = '';
  el.supplementNote.value = '';
  el.btnSavePerformanceSupplement.disabled = false;
  el.btnSavePerformanceSupplement.textContent = '保存补录';
}

function openPerformanceSupplementModal() {
  if (!state.currentActivity) {
    showNotification('请先进入一个月度活动，再补录绩效', 'warning', { title: '缺少月度活动' });
    return;
  }
  resetPerformanceSupplementForm();
  openModal(el.performanceSupplementModal, el.supplementEmployeeId);
}

function closePerformanceSupplementModal() {
  if (el.btnSavePerformanceSupplement?.disabled) return;
  closeModal(el.performanceSupplementModal);
}

async function savePerformanceSupplement() {
  if (!state.currentActivity) return;
  const employeeId = el.supplementEmployeeId.value.trim();
  const name = el.supplementEmployeeName.value.trim();
  const score = el.supplementScore.value.trim();
  const level = el.supplementLevel.value.trim();
  const coefficient = el.supplementCoefficient.value.trim();
  const note = el.supplementNote.value.trim();

  if (!employeeId) {
    showNotification('请填写工号', 'warning', { title: '无法保存' });
    el.supplementEmployeeId.focus();
    return;
  }
  if (!score && !level && !coefficient) {
    showNotification('请至少填写绩效得分、绩效等级或绩效系数', 'warning', { title: '无法保存' });
    el.supplementScore.focus();
    return;
  }

  el.btnSavePerformanceSupplement.disabled = true;
  el.btnSavePerformanceSupplement.textContent = '保存中';
  try {
    const data = await apiJson(`${API_BASE}/runs/${encodeURIComponent(state.currentActivity.run_id)}/performance-supplement`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        employee_id: employeeId,
        name,
        score,
        level,
        coefficient,
        note,
      }),
    });

    state.performanceData = data.preview;
    state.currentActivity.performance_data = data.preview;
    if (!state.currentActivity.performance_file) {
      state.currentActivity.performance_file = '页面绩效补录';
    }
    renderPerformanceData();
    closeModal(el.performanceSupplementModal);

    const summary = data.preview?.summary || {};
    if (toNumber(summary.supplement_added) > 0 || summary.source_type === 'performance_supplement') {
      showNotification('绩效补录已保存', 'success');
    } else if (toNumber(summary.supplement_skipped_existing) > 0) {
      showNotification('该员工已有绩效记录，本次未覆盖', 'warning', { title: '未覆盖已有绩效' });
    } else {
      showNotification('绩效补录已处理', 'success');
    }
  } catch (error) {
    showNotification(error.message, 'error', { title: '保存失败' });
    el.btnSavePerformanceSupplement.disabled = false;
    el.btnSavePerformanceSupplement.textContent = '保存补录';
  }
}

el.btnClosePerformanceSupplementModal?.addEventListener('click', closePerformanceSupplementModal);
el.btnCancelPerformanceSupplement?.addEventListener('click', closePerformanceSupplementModal);
el.btnSavePerformanceSupplement?.addEventListener('click', savePerformanceSupplement);

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

el.btnChoosePreviousAttendance?.addEventListener('click', () => {
  el.previousAttendanceInput?.click();
});

el.previousAttendanceInput?.addEventListener('change', (e) => {
  setPreviousAttendanceFile(e.target.files[0]);
});

el.btnClearPreviousAttendance?.addEventListener('click', clearPreviousAttendanceFile);

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
      if (previousAttendanceFile) formData.append('previous_attendance', previousAttendanceFile);
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
    } else if (uploadType === 'supplementalLeave') {
      formData.append('run_id', state.currentActivity.run_id);
      endpoint = `${API_BASE}/import-supplemental-leave`;
    } else if (uploadType === 'baseOverrides') {
      formData.append('run_id', state.currentActivity.run_id);
      endpoint = `${API_BASE}/import-base-overrides`;
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
        context: data.preview?.summary?.attendance_context || null,
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
      } else if (completedUploadType === 'supplementalLeave') {
        state.supplementalLeaveData = data.preview;
        renderSupplementalLeaveData();
      } else if (completedUploadType === 'baseOverrides') {
        state.baseOverrideData = data.preview;
        renderFoundationData();
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
el.btnAddPerformanceSupplement?.addEventListener('click', openPerformanceSupplementModal);
el.btnAddPerformanceSupplementEmpty?.addEventListener('click', openPerformanceSupplementModal);
el.btnUploadAdjustments?.addEventListener('click', () => openUploadModal('adjustments'));
el.workbenchUploadRoster?.addEventListener('change', event => handleWorkbenchUploadChange('roster', event));
el.workbenchUploadAttendance?.addEventListener('change', event => handleWorkbenchUploadChange('attendance', event));
el.workbenchUploadPreviousAttendance?.addEventListener('change', event => handleWorkbenchUploadChange('previousAttendance', event));
el.workbenchUploadSalary?.addEventListener('change', event => handleWorkbenchUploadChange('salary', event));
el.workbenchUploadPerformance?.addEventListener('change', event => handleWorkbenchUploadChange('performance', event));
el.workbenchUploadAdjustments?.addEventListener('change', event => handleWorkbenchUploadChange('adjustments', event));
el.workbenchUploadSupplementalLeave?.addEventListener('change', event => handleWorkbenchUploadChange('supplementalLeave', event));
function downloadAdjustmentsTemplate() {
  const link = document.createElement('a');
  link.href = `${API_BASE}/templates/adjustments/download`;
  link.download = 'FBU调薪转正拆分表模板.xlsx';
  link.click();
}

function downloadBaseOverridesTemplate() {
  const link = document.createElement('a');
  link.href = `${API_BASE}/templates/base-overrides/download`;
  link.download = 'FBU工时规则与固定基数模板.xlsx';
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
    && !summary.base_override_count
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

function renderAttendanceContextNote(context) {
  if (!context?.required || !context.message) return '';
  const isMissing = context.status === 'missing';
  return `
    <div class="import-result-note ${isMissing ? 'warning' : ''}">
      <span>
        <strong>96工时制跨月上下文</strong>
        <span class="import-result-context">${escapeHtml(context.message)}</span>
      </span>
      <span>${isMissing ? '需补传' : '已覆盖'}</span>
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
                <input type="text" id="${escapeHtml(filter.id)}" value="${escapeHtml(filterValues[filter.key] || '')}" placeholder="${escapeHtml(filter.placeholder || '')}" oninput="queueFilter('${escapeHtml(filterFn)}', event)">
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
  supplementalLeave: [
    { id: 'filterLeaveId', key: 'id', label: '工号', placeholder: 'zt0000000' },
    { id: 'filterLeaveName', key: 'name', label: '姓名', placeholder: '员工姓名' },
    {
      id: 'filterLeaveQuality',
      key: 'quality',
      label: '处理状态',
      type: 'select',
      options: [
        { value: 'all', label: '全部状态' },
        { value: 'pending', label: '待确认' },
        { value: 'confirmed', label: '已确认' },
        { value: 'excluded', label: '已排除' },
        { value: 'include', label: '计入基数' },
        { value: 'termination', label: '离职结算' },
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
  const formatShiftType = (emp) => emp.shift_type || (emp.has_night_shift ? '夜班' : '白班');

  el.attendanceContent.innerHTML = `
    ${renderDiagnosticsPanel()}
    ${renderImportResultNote('attendance')}
    ${renderAttendanceContextNote(summary.attendance_context)}
    <div class="import-workbench">
      ${renderImportSummary([
        { label: '员工总数', value: summary.total_employees, mono: true },
        { label: '考勤行数', value: summary.attendance_rows || employees.length, mono: true },
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
            <th>班次</th>
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
              <td>${formatShiftType(emp)}</td>
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
        <div style="display: flex; gap: 8px; justify-content: center;">
          <button class="btn btn-secondary" onclick="openPerformanceSupplementModal()">绩效补录</button>
          <button class="btn btn-primary" onclick="openUploadModal('performance')">上传绩效报表</button>
        </div>
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
  const adjustmentSummaryItems = adjustmentSummary
    ? (toNumber(adjustmentSummary.total_events) > 0
      ? [
        { label: '调薪事件', value: adjustmentSummary.total_events, mono: true, tone: 'warning' },
        { label: '自动拆分', value: adjustmentSummary.auto_split_ready, mono: true, tone: 'success' },
        { label: '需人工拆分', value: adjustmentSummary.manual_split_required, mono: true, tone: adjustmentSummary.manual_split_required ? 'warning' : '' },
      ]
      : [
        { label: '拆分员工', value: adjustmentSummary.total_employees, mono: true, tone: 'warning' },
        { label: '有效拆分基数', value: formatCurrency(adjustmentSummary.active_performance_base || 0), mono: true },
      ])
    : [];
  const performanceSummaryItems = [
    { label: '绩效报表人数', value: summary.total_employees, mono: true },
    { label: '审查行数', value: employees.length, mono: true },
    { label: '平均得分', value: toNumber(summary.avg_score).toFixed(2), mono: true },
    { label: '缺绩效得分', value: performanceQualityCounts.missingScore, mono: true, tone: performanceQualityCounts.missingScore ? 'warning' : '' },
    { label: '缺绩效系数', value: performanceQualityCounts.missingCoefficient, mono: true, tone: performanceQualityCounts.missingCoefficient ? 'warning' : '' },
    ...adjustmentSummaryItems,
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

function formatLeaveConfirmationStatus(status, includeInBase) {
  if (status === 'excluded') return '<span class="status-badge danger">已排除</span>';
  if (status === 'confirmed' && includeInBase) return '<span class="status-badge success">确认计入</span>';
  if (status === 'confirmed') return '<span class="status-badge neutral">已确认</span>';
  return '<span class="status-badge warning">待确认</span>';
}

function getSupplementalLeavePeriodOptions(rows) {
  const values = new Set();
  (rows || []).forEach(row => {
    if (row.suggested_period) values.add(row.suggested_period);
    if (row.allocation_period) values.add(row.allocation_period);
  });
  ['3.29-3.31', '4.1-4.11', '4.12-4.25', '4.26-4.30'].forEach(value => values.add(value));
  return [...values].filter(Boolean);
}

function getSupplementalIncludedHours(row) {
  if (row && row.included_hours !== undefined && row.included_hours !== null && row.included_hours !== '') {
    return toNumber(row.included_hours);
  }
  return toNumber(row?.hours);
}

function getSupplementalSuggestedHours(row) {
  const value = toNumber(row?.suggested_included_hours);
  return Number.isFinite(value) && value > 0 ? value : 0;
}

function getSupplementalSuggestionRows(rows = state.supplementalLeaveData?.rows || []) {
  return (rows || []).filter(row => (
    row?.suggestion_status === 'suggested'
    && row?.confirmation_status === 'pending'
    && getSupplementalSuggestedHours(row) > 0
  ));
}

function renderSupplementalSuggestionAction(row) {
  const suggestedHours = getSupplementalSuggestedHours(row);
  if (!getSupplementalSuggestionRows([row]).length || !suggestedHours) {
    return '';
  }
  return `
    <button
      class="btn btn-secondary btn-sm suggestion-action-btn"
      type="button"
      title="${escapeHtml(`建议计入 ${formatHours(suggestedHours)}；点击后写入并保存`)}"
      onclick="applySupplementalLeaveSuggestion(${escapeHtml(JSON.stringify(row.row_id))}, ${suggestedHours})"
    >建议计入</button>
  `;
}

function renderSupplementalSummaryValue(summary, key) {
  if (key === 'include_hours') return formatHours(summary?.include_hours);
  return summary?.[key] || 0;
}

function renderSupplementalSummaryItem(summary, key, label, tone = '') {
  const value = renderSupplementalSummaryValue(summary, key);
  const dynamicTone = (
    key === 'pending_count' && toNumber(summary?.pending_count)
      ? 'warning'
      : key === 'attendance_unmatched_count' && toNumber(summary?.attendance_unmatched_count)
        ? 'warning'
        : tone
  );
  return `<div class="${dynamicTone}" data-summary-key="${escapeHtml(key)}"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`;
}

function renderSupplementalLeaveRow(row) {
  return `
    <td><input class="supplemental-row-check" type="checkbox" value="${escapeHtml(row.row_id)}" aria-label="选择 ${escapeHtml(row.employee_id)}"></td>
    <td>${formatLeaveConfirmationStatus(row.confirmation_status, row.include_in_base)}</td>
    <td>${escapeHtml(row.employee_id)}</td>
    <td>${escapeHtml(row.name || '-')}</td>
    <td>${escapeHtml(row.termination_date || '-')}</td>
    <td>${escapeHtml(row.leave_type || '-')}</td>
    <td>${formatHours(row.hours)}</td>
    <td>
      <span class="included-hours-cell">
        <input
          class="supplemental-included-hours-input"
          type="number"
          min="0"
          step="0.01"
          value="${escapeHtml(getSupplementalIncludedHours(row))}"
          data-row-id="${escapeHtml(row.row_id)}"
          onkeydown="handleSupplementalLeaveHoursKeydown(event, ${escapeHtml(JSON.stringify(row.row_id))})"
          aria-label="计入小时 ${escapeHtml(row.employee_id)}"
        >
        <button class="btn btn-secondary btn-sm save-included-hours-btn" type="button" onclick="updateSupplementalLeaveRow(${escapeHtml(JSON.stringify(row.row_id))})">保存</button>
        ${renderSupplementalSuggestionAction(row)}
      </span>
    </td>
    <td>${escapeHtml(row.start_at ? `${row.start_at} ~ ${row.end_at || '-'}` : '-')}</td>
    <td>${escapeHtml(row.paid_at || '-')}</td>
    <td>${escapeHtml(row.suggested_month || '-')} / ${escapeHtml(row.suggested_period || '-')}</td>
    <td>${escapeHtml(row.allocation_month || '-')} / ${escapeHtml(row.allocation_period || '-')}</td>
    <td>
      <div>${escapeHtml(row.system_reason || '-')}</div>
      ${row.suggestion_reason ? `<div class="batch-file-meta">${escapeHtml(row.suggestion_reason)}</div>` : ''}
      ${row.confirmation_note ? `<div class="batch-file-meta">${escapeHtml(row.confirmation_note)}</div>` : ''}
    </td>
  `;
}

function renderSupplementalLeaveData() {
  if (!el.supplementalLeaveContent) return;

  const data = state.supplementalLeaveData;
  if (!data || !data.rows) {
    el.supplementalLeaveContent.innerHTML = `
      <div class="subsection-card">
        <div class="subsection-head">
          <div>
            <h3>补充假勤确认</h3>
            <p>请在“考勤工时”步骤的材料行上传补充假勤，系统会在这里生成待确认清单。</p>
          </div>
        </div>
      </div>
    `;
    return;
  }

  const rows = data.rows || [];
  const summary = data.summary || {};
  const filteredRows = getFilteredRows('supplementalLeave', rows);
  const pageInfo = getPaginatedRows('supplementalLeave', filteredRows);
  const periodOptions = getSupplementalLeavePeriodOptions(rows);
  const calcMonth = state.currentActivity?.calc_month || '';
  const suggestionRows = getSupplementalSuggestionRows(rows);

  el.supplementalLeaveContent.innerHTML = `
    <div class="subsection-card supplemental-leave-card">
      <div class="subsection-head">
        <div>
          <h3>补充假勤确认</h3>
          <p>普通病假/年假默认确认；离职病假结算默认待确认，可勾选后批量处理。</p>
        </div>
        <div class="subsection-actions">
          <button
            class="btn btn-primary btn-sm"
            type="button"
            onclick="applyAllSupplementalLeaveSuggestions()"
            ${suggestionRows.length ? '' : 'disabled'}
          >应用全部建议计入${suggestionRows.length ? `(${suggestionRows.length})` : ''}</button>
        </div>
      </div>
      <div class="leave-summary-compact">
        ${renderSupplementalSummaryItem(summary, 'total_rows', '解析')}
        ${renderSupplementalSummaryItem(summary, 'pending_count', '待确认')}
        ${renderSupplementalSummaryItem(summary, 'include_count', '确认计入', 'success')}
        ${renderSupplementalSummaryItem(summary, 'excluded_count', '已排除')}
        ${renderSupplementalSummaryItem(summary, 'attendance_unmatched_count', '未匹配考勤')}
        ${renderSupplementalSummaryItem(summary, 'include_hours', '计入小时')}
      </div>
      ${renderImportToolbar({
        title: '筛选补充假勤',
        subtitle: '按处理状态、员工快速定位需要人工确认的行。',
        filters: employeeFilters.supplementalLeave,
        filterFn: 'filterSupplementalLeaveData',
        resetFn: 'resetSupplementalLeaveFilter',
        filterValues: getTableFilter('supplementalLeave'),
      })}
      <div class="bulk-action-bar">
        <label class="bulk-check">
          <input type="checkbox" id="supplementalLeaveCheckAll" onchange="toggleSupplementalLeavePageSelection(this.checked)">
          当前页全选
        </label>
        <select id="bulkLeaveStatus" aria-label="批量状态">
          <option value="" selected>状态不修改</option>
          <option value="confirmed">确认计入</option>
          <option value="excluded">排除</option>
          <option value="pending">退回待确认</option>
        </select>
        <select id="bulkLeaveInclude" aria-label="是否计入">
          <option value="" selected>计入不修改</option>
          <option value="true">计入基数</option>
          <option value="false">不计入</option>
        </select>
        <input id="bulkLeaveMonth" type="text" value="" placeholder="${escapeHtml(calcMonth || 'YYYY-MM')}" aria-label="归属月份">
        <select id="bulkLeavePeriod" aria-label="归属周期">
          <option value="" selected>周期不修改</option>
          ${periodOptions.map(period => `
            <option value="${escapeHtml(period)}">${escapeHtml(period)}</option>
          `).join('')}
        </select>
        <input id="bulkLeaveHours" type="number" min="0" step="0.01" placeholder="计入小时" aria-label="批量计入小时">
        <input id="bulkLeaveNote" type="text" placeholder="备注，例如：已在3月计入" aria-label="备注">
        <button class="btn btn-primary btn-sm" type="button" onclick="applySupplementalLeaveBatchFromToolbar()">批量填充</button>
      </div>
      ${renderImportTable(`
        <table class="data-table" id="supplementalLeaveTable">
          <thead>
            <tr>
              <th style="width: 48px;">选择</th>
              <th>状态</th>
              <th>工号</th>
              <th>姓名</th>
              <th>离职日期</th>
              <th>假期类型</th>
              <th>原始小时</th>
              <th>计入小时</th>
              <th>申请时间</th>
              <th>发放时间</th>
              <th>建议归属</th>
              <th>当前归属</th>
              <th>说明</th>
            </tr>
          </thead>
          <tbody>
            ${pageInfo.items.length ? pageInfo.items.map(row => `
              <tr class="${row.confirmation_status === 'pending' ? 'row-warning' : row.confirmation_status === 'excluded' ? 'row-muted' : ''}" data-row-id="${escapeHtml(row.row_id)}">
                ${renderSupplementalLeaveRow(row)}
              </tr>
            `).join('') : renderEmptyTableRow(13, '没有匹配的补充假勤记录')}
          </tbody>
        </table>
      `, renderTablePagination('supplementalLeave', pageInfo))}
    </div>
  `;
}

function getSelectedSupplementalLeaveRowIds() {
  return [...document.querySelectorAll('.supplemental-row-check:checked')]
    .map(input => input.value)
    .filter(Boolean);
}

function toggleSupplementalLeavePageSelection(checked) {
  document.querySelectorAll('.supplemental-row-check').forEach(input => {
    input.checked = checked;
  });
}

function findSupplementalLeaveRowElement(rowId) {
  if (!rowId) return null;
  return [...document.querySelectorAll('#supplementalLeaveTable tr[data-row-id]')]
    .find(row => row.dataset.rowId === rowId) || null;
}

function focusSupplementalLeaveRowInput(rowId) {
  const row = findSupplementalLeaveRowElement(rowId);
  const input = row?.querySelector?.('.supplemental-included-hours-input');
  if (!input) return;
  input.focus({ preventScroll: true });
  input.select?.();
}

function getSupplementalLeaveContinuationAnchor(rowId) {
  const visibleRows = [...document.querySelectorAll('#supplementalLeaveTable tr[data-row-id]')];
  const index = visibleRows.findIndex(row => row.dataset.rowId === rowId);
  if (index < 0) return rowId;

  const nextRow = visibleRows[index + 1] || visibleRows[index - 1];
  return nextRow?.dataset?.rowId || rowId;
}

function renderSupplementalLeaveDataPreservingScroll(anchorRowId = '', options = {}) {
  const scrollY = window.scrollY;
  const scrollX = window.scrollX;
  const anchorTop = findSupplementalLeaveRowElement(anchorRowId)?.getBoundingClientRect().top ?? null;
  renderSupplementalLeaveData();
  requestAnimationFrame(() => {
    if (anchorRowId && anchorTop !== null) {
      const nextAnchor = findSupplementalLeaveRowElement(anchorRowId);
      if (nextAnchor) {
        const nextTop = nextAnchor.getBoundingClientRect().top;
        window.scrollTo(scrollX, window.scrollY + nextTop - anchorTop);
        if (options.focusInput) {
          requestAnimationFrame(() => focusSupplementalLeaveRowInput(anchorRowId));
        }
        return;
      }
    }
    window.scrollTo(scrollX, scrollY);
    if (options.focusInput) {
      requestAnimationFrame(() => focusSupplementalLeaveRowInput(anchorRowId));
    }
  });
}

function setSupplementalLeaveRowSaving(rowId, isSaving) {
  const row = findSupplementalLeaveRowElement(rowId);
  if (!row) return;
  row.classList.toggle('is-saving', Boolean(isSaving));
  const input = row.querySelector('.supplemental-included-hours-input');
  if (input) input.disabled = Boolean(isSaving);
  row.querySelectorAll('button').forEach(button => {
    button.disabled = Boolean(isSaving);
  });
  const saveButton = row.querySelector('.save-included-hours-btn');
  if (saveButton) {
    saveButton.textContent = isSaving ? '保存中' : '保存';
  }
}

function updateSupplementalLeaveSummary(summary = state.supplementalLeaveData?.summary || {}) {
  document.querySelectorAll('.leave-summary-compact [data-summary-key]').forEach(item => {
    const key = item.dataset.summaryKey;
    const value = item.querySelector('strong');
    if (value) value.textContent = renderSupplementalSummaryValue(summary, key);
    item.classList.toggle('warning', (
      key === 'pending_count' && toNumber(summary.pending_count) > 0
    ) || (
      key === 'attendance_unmatched_count' && toNumber(summary.attendance_unmatched_count) > 0
    ));
    if (key === 'include_count') item.classList.add('success');
  });
}

function updateSupplementalSuggestionHeader() {
  const button = document.querySelector('.supplemental-leave-card .subsection-actions .btn-primary');
  if (!button) return;
  const suggestionCount = getSupplementalSuggestionRows().length;
  button.disabled = suggestionCount === 0;
  button.textContent = `应用全部建议计入${suggestionCount ? `(${suggestionCount})` : ''}`;
}

function updateSupplementalLeaveRowInPlace(rowId) {
  const rowData = (state.supplementalLeaveData?.rows || []).find(row => row.row_id === rowId);
  const rowElement = findSupplementalLeaveRowElement(rowId);
  if (!rowData || !rowElement) return false;

  updateSupplementalLeaveSummary();
  updateSupplementalSuggestionHeader();

  rowElement.classList.toggle('row-warning', rowData.confirmation_status === 'pending');
  rowElement.classList.toggle('row-muted', rowData.confirmation_status === 'excluded');
  rowElement.innerHTML = renderSupplementalLeaveRow(rowData);
  return true;
}

function restoreScrollPosition(scrollX, scrollY) {
  window.scrollTo(scrollX, scrollY);
  requestAnimationFrame(() => window.scrollTo(scrollX, scrollY));
  requestAnimationFrame(() => {
    requestAnimationFrame(() => window.scrollTo(scrollX, scrollY));
  });
  window.setTimeout(() => window.scrollTo(scrollX, scrollY), 80);
}

function handleSupplementalLeaveHoursKeydown(event, rowId) {
  if (event.key !== 'Enter') return;
  event.preventDefault();
  updateSupplementalLeaveRow(rowId);
}

async function applySupplementalLeaveBatchFromToolbar() {
  const rowIds = getSelectedSupplementalLeaveRowIds();
  if (!rowIds.length || !state.currentActivity) {
    showNotification('请先勾选需要处理的补充假勤行', 'warning');
    return;
  }
  const anchorRowId = getSupplementalLeaveContinuationAnchor(rowIds[rowIds.length - 1]);

  const status = document.getElementById('bulkLeaveStatus')?.value || '';
  const includeRawValue = document.getElementById('bulkLeaveInclude')?.value || '';
  const bulkHoursValue = document.getElementById('bulkLeaveHours')?.value;
  const payload = {
    row_ids: rowIds,
  };
  if (status) {
    payload.confirmation_status = status;
  }
  if (includeRawValue) {
    payload.include_in_base = includeRawValue === 'true';
  } else if (status === 'excluded') {
    payload.include_in_base = false;
  }
  const allocationMonth = document.getElementById('bulkLeaveMonth')?.value || '';
  if (allocationMonth.trim()) {
    payload.allocation_month = allocationMonth.trim();
  }
  const allocationPeriod = document.getElementById('bulkLeavePeriod')?.value || '';
  if (allocationPeriod.trim()) {
    payload.allocation_period = allocationPeriod.trim();
  }
  const confirmationNote = document.getElementById('bulkLeaveNote')?.value || '';
  if (confirmationNote.trim()) {
    payload.confirmation_note = confirmationNote.trim();
  }
  if (bulkHoursValue !== undefined && String(bulkHoursValue).trim() !== '') {
    payload.included_hours = Number(bulkHoursValue);
  }
  if (Object.keys(payload).length <= 1) {
    showNotification('请选择至少一个要批量填充的字段', 'warning');
    return;
  }

  try {
    const data = await apiJson(`${API_BASE}/runs/${state.currentActivity.run_id}/supplemental-leave/batch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    state.supplementalLeaveData = data.preview;
    state.currentActivity.supplemental_leave_data = data.preview;
    renderSupplementalLeaveDataPreservingScroll(anchorRowId);
    showNotification(`已批量处理 ${rowIds.length} 行补充假勤`, 'success');
  } catch (error) {
    showNotification(error.message, 'error', { title: '批量处理失败' });
  }
}

async function applySupplementalLeaveSuggestion(rowId, suggestedHours) {
  const input = [...document.querySelectorAll('.supplemental-included-hours-input')]
    .find(item => item.dataset.rowId === rowId);
  if (input) {
    input.value = String(suggestedHours);
  }
  await updateSupplementalLeaveRow(rowId, suggestedHours);
}

async function applyAllSupplementalLeaveSuggestions() {
  if (!state.currentActivity) return;
  const suggestionRows = getSupplementalSuggestionRows();
  if (!suggestionRows.length) {
    showNotification('当前没有可应用的建议计入行', 'warning');
    return;
  }
  const anchorRowId = suggestionRows.find(row => findSupplementalLeaveRowElement(row.row_id))?.row_id
    || suggestionRows[0]?.row_id
    || '';

  try {
    const data = await apiJson(`${API_BASE}/runs/${state.currentActivity.run_id}/supplemental-leave/batch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apply_suggestions: true }),
    });
    state.supplementalLeaveData = data.preview;
    state.currentActivity.supplemental_leave_data = data.preview;
    renderSupplementalLeaveDataPreservingScroll(anchorRowId);
    showNotification(`已应用 ${data.applied_count || suggestionRows.length} 条建议计入`, 'success');
  } catch (error) {
    showNotification(error.message, 'error', { title: '应用建议失败' });
  }
}

async function updateSupplementalLeaveRow(rowId, explicitHours) {
  if (!rowId || !state.currentActivity) return;
  const scrollX = window.scrollX;
  const scrollY = window.scrollY;
  const input = [...document.querySelectorAll('.supplemental-included-hours-input')]
    .find(item => item.dataset.rowId === rowId);
  const value = explicitHours !== undefined ? explicitHours : input?.value;
  if (value === undefined || String(value).trim() === '') {
    showNotification('请填写计入小时', 'warning');
    return;
  }
  const includedHours = Number(value);
  if (!Number.isFinite(includedHours) || includedHours < 0) {
    showNotification('计入小时必须是不小于0的数字', 'warning');
    return;
  }
  const payload = {
    row_ids: [rowId],
    included_hours: includedHours,
    confirmation_status: includedHours > 0 ? 'confirmed' : 'excluded',
    include_in_base: includedHours > 0,
  };
  const anchorRowId = getSupplementalLeaveContinuationAnchor(rowId);

  try {
    setSupplementalLeaveRowSaving(rowId, true);
    const data = await apiJson(`${API_BASE}/runs/${state.currentActivity.run_id}/supplemental-leave/batch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    state.supplementalLeaveData = data.preview;
    state.currentActivity.supplemental_leave_data = data.preview;
    if (updateSupplementalLeaveRowInPlace(rowId)) {
      restoreScrollPosition(scrollX, scrollY);
    } else {
      renderSupplementalLeaveDataPreservingScroll(anchorRowId, { focusInput: true });
    }
    showNotification(includedHours > 0 ? '已确认计入' : '已排除', 'success');
  } catch (error) {
    setSupplementalLeaveRowSaving(rowId, false);
    showNotification(error.message, 'error', { title: '保存失败' });
  }
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
            <input type="text" id="filterResultsId" value="${escapeHtml(filterValues.id || '')}" placeholder="zt0000000" oninput="queueFilter('filterResultsData', event)">
          </div>
          <div class="filter-field">
            <label for="filterResultsName">姓名</label>
            <input type="text" id="filterResultsName" value="${escapeHtml(filterValues.name || '')}" placeholder="员工姓名" oninput="queueFilter('filterResultsData', event)">
          </div>
          <div class="filter-field">
            <label for="filterResultsArea">划分区域</label>
            <input type="text" id="filterResultsArea" value="${escapeHtml(filterValues.area || '')}" placeholder="区域" oninput="queueFilter('filterResultsData', event)">
          </div>
          <div class="filter-field">
            <label for="filterResultsDept">部门</label>
            <input type="text" id="filterResultsDept" value="${escapeHtml(filterValues.dept || '')}" placeholder="部门全称" oninput="queueFilter('filterResultsData', event)">
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
      <div class="calc-chain-item">分段/拆行核算</div>
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

  el.calcChainContent.innerHTML = `
    <div class="calc-chain-title">绩效奖金计算过程 - ${escapeHtml(employeeId)}</div>
    <div class="calc-chain-item">绩效基数 = $${emp.performance_base.toFixed(2)}</div>
    <div class="calc-chain-item">绩效比例 = ${(emp.performance_ratio * 100).toFixed(1)}%</div>
    <div class="calc-chain-item">绩效得分 = ${formatScore(emp.performance_score)}</div>
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
  supplementalLeave: {
    id: 'filterLeaveId',
    name: 'filterLeaveName',
    quality: 'filterLeaveQuality',
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
  if (state.currentPage === 'workbench') {
    renderWorkbench();
    restoreInputFocus(focusSnapshot);
    return;
  }
  if (type === 'attendance') renderAttendanceData();
  if (type === 'salary') renderSalaryData();
  if (type === 'performance') renderPerformanceData();
  if (type === 'supplementalLeave') renderSupplementalLeaveData();
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

// ═══ Supplemental Leave Filter ═══

function filterSupplementalLeaveData() {
  applyTableFilter('supplementalLeave');
}

function resetSupplementalLeaveFilter() {
  resetTableFilter('supplementalLeave');
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
    setActivityStep('check');
    navigateTo('workbench');
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
  setActivityStep(meta.page === 'results'
    ? 'export'
    : meta.page === 'performance'
      ? 'performance'
      : meta.page === 'salary'
        ? 'salary'
        : 'attendance');
  navigateTo('workbench');
}

const STEP_HELP = {
  people: ['花名册用于匹配姓名、部门和岗位。'],
  attendance: ['普通病假、年假按申请时间计入本月。', '离职年假默认不计入。', '96工时制员工按本月和必要的上月考勤计算。'],
  salary: ['当月转正或调薪按生效日期拆分。', '未发生转正或调薪的员工按薪资档案计算。'],
  performance: ['有绩效报表的员工按报表得分计算。', '离职员工可在本页补充绩效得分。'],
  check: ['只展示必须处理后才能继续的问题。'],
  export: ['最终结果按员工合并展示，拆分明细在行内展开。'],
};

function getAttendanceStepData(activity) {
  return activity?.attendance_data || state.attendanceData || null;
}

function getSalaryStepData(activity) {
  return activity?.salary_data || state.salaryData || null;
}

function getPerformanceStepData(activity) {
  return activity?.performance_data || state.performanceData || null;
}

function getSupplementalLeaveStepData(activity) {
  return activity?.supplemental_leave_data || state.supplementalLeaveData || null;
}

function getAdjustmentStepData(activity) {
  return activity?.adjustment_data || state.adjustmentData || null;
}

function getStepStatus(stepKey, activity) {
  const needs = buildNeedsForStep(stepKey, activity);
  if (needs.length) return '需要处理';
  if (stepKey === 'people') return activity?.roster_file ? '已完成' : '未完成';
  if (stepKey === 'attendance') return activity?.attendance_file && activity?.supplemental_leave_file ? '已完成' : '未完成';
  if (stepKey === 'salary') return activity?.salary_file ? '已完成' : '未完成';
  if (stepKey === 'performance') return activity?.performance_file || activity?.performance_data?.employees?.length ? '已完成' : '未完成';
  if (stepKey === 'check') return activity?.results?.length ? '已完成' : '未开始';
  if (stepKey === 'export') return activity?.results?.length ? '已完成' : '未开始';
  return '未开始';
}

function getStepSummary(stepKey, activity) {
  if (stepKey === 'people') return `${toNumber(activity?.attendance_data?.summary?.roster_matched)}已匹配`;
  if (stepKey === 'attendance') return `${formatHours(activity?.attendance_data?.summary?.total_base_hours)}工时`;
  if (stepKey === 'salary') return `${toNumber(activity?.salary_data?.summary?.valid_hourly_count)}有效时薪`;
  if (stepKey === 'performance') return `${toNumber(activity?.performance_data?.summary?.total_employees)}人`;
  if (stepKey === 'check') return `${buildNeedsForStep(stepKey, activity).length}项`;
  if (stepKey === 'export') return `${getWorkbenchResults(activity).length}人`;
  return '-';
}

function renderActivityStepper(activity) {
  return `
    <div class="activity-stepper" role="tablist" aria-label="核算步骤">
      ${ACTIVITY_STEPS.map((step, index) => {
        const active = state.activityStep === step.key;
        const status = getStepStatus(step.key, activity);
        return `
          <button class="activity-step ${active ? 'active' : ''}" type="button" role="tab" aria-selected="${active}" onclick="setActivityStep(${formatJsArg(step.key)})">
            <span class="activity-step-index">${index + 1}</span>
            <span class="activity-step-label">${escapeHtml(step.label)}</span>
            <span class="activity-step-summary">${escapeHtml(getStepSummary(step.key, activity))}</span>
            <span class="activity-step-status ${status === '需要处理' ? 'warning' : status === '已完成' ? 'success' : ''}">${escapeHtml(status)}</span>
          </button>
        `;
      }).join('')}
    </div>
  `;
}

function buildNeedsForStep(stepKey, activity) {
  const needs = [];
  const push = (id, text, action = '') => needs.push({ id, text, action });
  if (!activity) return needs;

  if (stepKey === 'people' && !activity.roster_file) {
    push('roster', '请上传花名册', '<button class="btn btn-primary btn-sm" type="button" onclick="openWorkbenchUpload(\'roster\')">上传</button>');
  }
  if (stepKey === 'attendance') {
    if (!activity.attendance_file) push('attendance', '请上传考勤日报', '<button class="btn btn-primary btn-sm" type="button" onclick="openWorkbenchUpload(\'attendance\')">上传</button>');
    if (!activity.supplemental_leave_file) push('supplementalLeave', '请上传补充假勤', '<button class="btn btn-primary btn-sm" type="button" onclick="openWorkbenchUpload(\'supplementalLeave\')">上传</button>');
    if (!activity.base_override_data?.employees?.some(row => row.rule_type === '96工时制')) {
      push('workHourList', '请确认96工时制员工名单', '<button class="btn btn-primary btn-sm" type="button" onclick="confirmMaintainedRuleList(\'workHour\')">确认名单</button>');
    }
    getSupplementalSuggestionRows(getWorkbenchSupplementalRows(activity)).slice(0, 5).forEach(row => {
      push(
        `leave-${row.row_id}`,
        `${row.employee_id} ${row.name || ''} 补充假勤请确认`,
        `<button class="btn btn-primary btn-sm" type="button" onclick="applyWorkbenchSupplementalSuggestion(${formatJsArg(row.row_id)}, ${getSupplementalSuggestedHours(row)})">计入建议小时</button>`,
      );
    });
  }
  if (stepKey === 'salary') {
    if (!activity.salary_file) push('salary', '请上传薪资档案', '<button class="btn btn-primary btn-sm" type="button" onclick="openWorkbenchUpload(\'salary\')">上传</button>');
    if (!activity.base_override_data?.employees?.some(row => row.rule_type === '线下固定基数覆盖')) {
      push('fixedBaseList', '请确认固定基数人员名单', '<button class="btn btn-primary btn-sm" type="button" onclick="confirmMaintainedRuleList(\'fixedBase\')">确认名单</button>');
    }
  }
  if (stepKey === 'performance' && !activity.performance_file && !activity.performance_data?.employees?.length) {
    push('performance', '请上传绩效报表或补充离职人员绩效', '<button class="btn btn-primary btn-sm" type="button" onclick="openWorkbenchUpload(\'performance\')">上传</button>');
  }
  if (stepKey === 'check') {
    ['people', 'attendance', 'salary', 'performance'].forEach(key => {
      buildNeedsForStep(key, activity).forEach(item => needs.push(item));
    });
  }
  return needs;
}

function renderNeedsPanel(stepKey, activity) {
  const needs = buildNeedsForStep(stepKey, activity);
  if (!needs.length) {
    return '<section class="step-section needs-panel complete">本步骤已完成</section>';
  }
  return `
    <section class="step-section needs-panel">
      <div class="section-head compact"><h3>需要处理</h3></div>
      <div class="needs-list">
        ${needs.map(item => `
          <div class="need-row">
            <span>${escapeHtml(item.text)}</span>
            <span class="need-actions">${item.action}</span>
          </div>
        `).join('')}
      </div>
    </section>
  `;
}

function renderStepHelp(stepKey) {
  const rows = STEP_HELP[stepKey] || [];
  return `
    <details class="step-help">
      <summary>查看说明</summary>
      <ul>${rows.map(row => `<li>${escapeHtml(row)}</li>`).join('')}</ul>
    </details>
  `;
}

function renderInlineEmptyState(title, message, actionLabel = '', action = '') {
  return `
    <section class="step-section empty-inline-state">
      <div>
        <h3>${escapeHtml(title)}</h3>
        <p>${escapeHtml(message)}</p>
      </div>
      ${actionLabel && action ? `<button class="btn btn-primary btn-sm" type="button" onclick="${action}">${escapeHtml(actionLabel)}</button>` : ''}
    </section>
  `;
}

function renderPeopleTable(activity) {
  const summary = getAttendanceStepData(activity)?.summary || {};
  const rosterFile = activity?.roster_file || state.baseRoster?.filename || '';
  return `
    <section class="step-section">
      <div class="section-head compact">
        <div>
          <h3>人员范围</h3>
          <p>当前活动使用的花名册和本月匹配结果。</p>
        </div>
      </div>
      ${renderImportSummary([
        { label: '花名册', value: rosterFile ? '已上传' : '未上传', tone: rosterFile ? 'success' : 'warning' },
        { label: '已匹配', value: toNumber(summary.roster_matched), mono: true },
        { label: '未匹配', value: toNumber(summary.roster_missing), mono: true, tone: toNumber(summary.roster_missing) ? 'warning' : '' },
        { label: '本月员工', value: toNumber(summary.total_employees), mono: true },
      ])}
      <div class="compact-list-table">
        <table class="data-table">
          <thead>
            <tr>
              <th>项目</th>
              <th>当前情况</th>
              <th>说明</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>花名册文件</td>
              <td>${escapeHtml(rosterFile || '-')}</td>
              <td>${rosterFile ? '当前活动已关联花名册。' : '请先上传花名册。'}</td>
            </tr>
            <tr>
              <td>匹配结果</td>
              <td>${escapeHtml(`${toNumber(summary.roster_matched)} / ${toNumber(summary.total_employees)}`)}</td>
              <td>后续步骤按这里的员工范围继续。</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  `;
}

function renderSupplementalLeaveSection(activity) {
  const data = getSupplementalLeaveStepData(activity);
  if (!data || !data.rows) {
    return renderInlineEmptyState('补充假勤确认', '上传补充假勤后，这里会列出需要继续处理的行。');
  }
  const rows = data.rows || [];
  const summary = data.summary || {};
  const filteredRows = getFilteredRows('supplementalLeave', rows);
  const pageInfo = getPaginatedRows('supplementalLeave', filteredRows);
  const periodOptions = getSupplementalLeavePeriodOptions(rows);
  const calcMonth = activity?.calc_month || state.currentActivity?.calc_month || '';
  const suggestionRows = getSupplementalSuggestionRows(rows);

  return `
    <section class="step-section">
      <div class="section-head compact">
        <div>
          <h3>补充假勤确认</h3>
          <p>普通病假、年假默认确认；离职病假结算需要在这里继续处理。</p>
        </div>
        <div class="section-actions">
          <button class="btn btn-primary btn-sm" type="button" onclick="applyAllSupplementalLeaveSuggestions()" ${suggestionRows.length ? '' : 'disabled'}>应用全部建议计入${suggestionRows.length ? `(${suggestionRows.length})` : ''}</button>
        </div>
      </div>
      <div class="leave-summary-compact">
        ${renderSupplementalSummaryItem(summary, 'total_rows', '解析')}
        ${renderSupplementalSummaryItem(summary, 'pending_count', '待确认')}
        ${renderSupplementalSummaryItem(summary, 'include_count', '确认计入', 'success')}
        ${renderSupplementalSummaryItem(summary, 'excluded_count', '已排除')}
        ${renderSupplementalSummaryItem(summary, 'attendance_unmatched_count', '未匹配考勤')}
        ${renderSupplementalSummaryItem(summary, 'include_hours', '计入小时')}
      </div>
      ${renderImportToolbar({
        title: '筛选补充假勤',
        subtitle: '按处理状态、员工快速定位。',
        filters: employeeFilters.supplementalLeave,
        filterFn: 'filterSupplementalLeaveData',
        resetFn: 'resetSupplementalLeaveFilter',
        filterValues: getTableFilter('supplementalLeave'),
      })}
      <div class="bulk-action-bar">
        <label class="bulk-check">
          <input type="checkbox" id="supplementalLeaveCheckAll" onchange="toggleSupplementalLeavePageSelection(this.checked)">
          当前页全选
        </label>
        <select id="bulkLeaveStatus" aria-label="批量状态">
          <option value="" selected>状态不修改</option>
          <option value="confirmed">确认计入</option>
          <option value="excluded">排除</option>
          <option value="pending">退回待确认</option>
        </select>
        <select id="bulkLeaveInclude" aria-label="是否计入">
          <option value="" selected>计入不修改</option>
          <option value="true">计入基数</option>
          <option value="false">不计入</option>
        </select>
        <input id="bulkLeaveMonth" type="text" value="" placeholder="${escapeHtml(calcMonth || 'YYYY-MM')}" aria-label="归属月份">
        <select id="bulkLeavePeriod" aria-label="归属周期">
          <option value="" selected>周期不修改</option>
          ${periodOptions.map(period => `<option value="${escapeHtml(period)}">${escapeHtml(period)}</option>`).join('')}
        </select>
        <input id="bulkLeaveHours" type="number" min="0" step="0.01" placeholder="计入小时" aria-label="批量计入小时">
        <input id="bulkLeaveNote" type="text" placeholder="备注，例如：已在3月计入" aria-label="备注">
        <button class="btn btn-primary btn-sm" type="button" onclick="applySupplementalLeaveBatchFromToolbar()">批量填充</button>
      </div>
      ${renderImportTable(`
        <table class="data-table" id="supplementalLeaveTable">
          <thead>
            <tr>
              <th style="width: 48px;">选择</th>
              <th>状态</th>
              <th>工号</th>
              <th>姓名</th>
              <th>离职日期</th>
              <th>假期类型</th>
              <th>原始小时</th>
              <th>计入小时</th>
              <th>申请时间</th>
              <th>发放时间</th>
              <th>建议归属</th>
              <th>当前归属</th>
              <th>说明</th>
            </tr>
          </thead>
          <tbody>
            ${pageInfo.items.length ? pageInfo.items.map(row => `
              <tr class="${row.confirmation_status === 'pending' ? 'row-warning' : row.confirmation_status === 'excluded' ? 'row-muted' : ''}" data-row-id="${escapeHtml(row.row_id)}">
                ${renderSupplementalLeaveRow(row)}
              </tr>
            `).join('') : renderEmptyTableRow(13, '没有匹配的补充假勤记录')}
          </tbody>
        </table>
      `, renderTablePagination('supplementalLeave', pageInfo))}
    </section>
  `;
}

function renderAttendanceSummaryTable(activity) {
  const data = getAttendanceStepData(activity);
  if (!data || !data.employees) {
    return `${renderInlineEmptyState('考勤预览', '上传考勤日报后，这里会显示员工工时和补充假勤明细。', '上传考勤日报', "openWorkbenchUpload('attendance')")}${renderSupplementalLeaveSection(activity)}`;
  }
  const employees = data.employees || [];
  const filteredEmployees = getFilteredRows('attendance', employees);
  const pageInfo = getPaginatedRows('attendance', filteredEmployees);
  const summary = data.summary || {};
  const formatShiftType = (emp) => emp.shift_type || (emp.has_night_shift ? '夜班' : '白班');

  return `
    <section class="step-section">
      ${renderImportSummary([
        { label: '员工总数', value: summary.total_employees, mono: true },
        { label: '考勤行数', value: summary.attendance_rows || employees.length, mono: true },
        { label: '花名册匹配', value: `${summary.roster_matched || 0}/${summary.total_employees || 0}`, mono: true, tone: (summary.roster_matched || 0) === (summary.total_employees || 0) ? 'success' : 'warning' },
        { label: '总工时', value: formatHours(summary.total_base_hours), mono: true },
        { label: '总OT1.5', value: formatHours(summary.total_ot15), mono: true },
      ])}
      ${renderImportToolbar({
        title: '筛选考勤数据',
        subtitle: '按员工信息快速定位本次解析结果。',
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
              <th>班次</th>
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
                <td>${formatShiftType(emp)}</td>
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
    </section>
    ${renderSupplementalLeaveSection(activity)}
  `;
}

function renderSalarySummaryTable(activity) {
  const data = getSalaryStepData(activity);
  if (!data || !data.employees) {
    return renderInlineEmptyState('薪资预览', '上传薪资档案后，这里会显示时薪、绩效比例和固定基数。', '上传薪资档案', "openWorkbenchUpload('salary')");
  }
  const employees = data.employees || [];
  const filteredEmployees = getFilteredRows('salary', employees);
  const pageInfo = getPaginatedRows('salary', filteredEmployees);
  const summary = data.summary || {};
  const salaryQualityCounts = employees.reduce((counts, emp) => {
    const flags = getSalaryQualityFlags(emp);
    if (flags.complete) counts.complete += 1;
    if (flags.zeroHourly) counts.zeroHourly += 1;
    if (flags.emptyRatio) counts.emptyRatio += 1;
    if (flags.fixedBase) counts.fixedBase += 1;
    return counts;
  }, { complete: 0, zeroHourly: 0, emptyRatio: 0, fixedBase: 0 });

  return `
    <section class="step-section">
      ${renderImportSummary([
        { label: '薪资档案人数', value: summary.total_employees, mono: true },
        { label: '有效时薪', value: summary.valid_hourly_count ?? summary.total_employees, mono: true, tone: 'success' },
        { label: '0时薪', value: summary.zero_hourly_count ?? 0, mono: true, tone: (summary.zero_hourly_count ?? 0) ? 'danger' : '' },
        { label: '有效平均时薪', value: formatCurrency(summary.avg_hourly_rate), mono: true },
        { label: '绩效比例空', value: salaryQualityCounts.emptyRatio, mono: true, tone: salaryQualityCounts.emptyRatio ? 'warning' : '' },
        { label: '固定基数', value: salaryQualityCounts.fixedBase, mono: true },
      ])}
      ${renderImportToolbar({
        title: '筛选薪资档案',
        subtitle: '这里展示本次导入后的薪资结果。',
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
    </section>
  `;
}

function renderPerformanceInlineSupplement() {
  return `
    <section class="step-section">
      <div class="section-head compact">
        <div>
          <h3>离职人员补充</h3>
          <p>缺少绩效报表的离职员工可在这里补充得分。</p>
        </div>
      </div>
      ${renderWorkbenchPerformanceSupplement()}
    </section>
  `;
}

function renderPerformanceSummaryTable(activity) {
  const data = getPerformanceStepData(activity);
  if (!data || !data.employees) {
    return renderInlineEmptyState('绩效预览', '上传绩效报表后，这里会显示绩效得分、等级和系数。', '上传绩效报表', "openWorkbenchUpload('performance')");
  }
  const employees = getPerformanceReviewRows(data.employees);
  const filteredEmployees = getFilteredRows('performance', employees);
  const pageInfo = getPaginatedRows('performance', filteredEmployees);
  const summary = data.summary || {};
  const adjustmentSummary = getAdjustmentStepData(activity)?.summary;
  const adjustmentIds = getAdjustmentEmployeeIds();
  const performanceQualityCounts = employees.reduce((counts, emp) => {
    const flags = getPerformanceQualityFlags(emp, adjustmentIds);
    if (flags.complete) counts.complete += 1;
    if (flags.missingScore) counts.missingScore += 1;
    if (flags.missingCoefficient) counts.missingCoefficient += 1;
    if (flags.hasAdjustment) counts.hasAdjustment += 1;
    return counts;
  }, { complete: 0, missingScore: 0, missingCoefficient: 0, hasAdjustment: 0 });
  const adjustmentSummaryItems = adjustmentSummary
    ? (toNumber(adjustmentSummary.total_events) > 0
      ? [
        { label: '调薪事件', value: adjustmentSummary.total_events, mono: true, tone: 'warning' },
        { label: '自动拆分', value: adjustmentSummary.auto_split_ready, mono: true, tone: 'success' },
        { label: '需补拆分', value: adjustmentSummary.manual_split_required, mono: true, tone: adjustmentSummary.manual_split_required ? 'warning' : '' },
      ]
      : [
        { label: '拆分员工', value: adjustmentSummary.total_employees, mono: true, tone: 'warning' },
        { label: '有效拆分基数', value: formatCurrency(adjustmentSummary.active_performance_base || 0), mono: true },
      ])
    : [];

  return `
    <section class="step-section">
      ${renderImportSummary([
        { label: '绩效报表人数', value: summary.total_employees, mono: true },
        { label: '审查行数', value: employees.length, mono: true },
        { label: '平均得分', value: toNumber(summary.avg_score).toFixed(2), mono: true },
        { label: '缺绩效得分', value: performanceQualityCounts.missingScore, mono: true, tone: performanceQualityCounts.missingScore ? 'warning' : '' },
        { label: '缺绩效系数', value: performanceQualityCounts.missingCoefficient, mono: true, tone: performanceQualityCounts.missingCoefficient ? 'warning' : '' },
        ...adjustmentSummaryItems,
      ])}
      ${renderImportToolbar({
        title: '筛选绩效明细',
        subtitle: '这里展示本次导入后的绩效结果和补充行。',
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
    </section>
  `;
}

function renderCheckPreview(activity) {
  const diagnostics = getWorkbenchDiagnostics(activity);
  const summary = diagnostics?.summary || {};
  const issues = (diagnostics?.issues || []).filter(Boolean);
  const readyCount = toNumber(summary.can_calculate_count);
  const totalCount = toNumber(summary.attendance_count);
  const severityLabel = { error: '严重', warning: '提醒', info: '信息' };

  return `
    <section class="step-section">
      ${renderImportSummary([
        { label: '严重', value: toNumber(summary.error_count), mono: true, tone: toNumber(summary.error_count) ? 'danger' : 'success' },
        { label: '提醒', value: toNumber(summary.warning_count), mono: true, tone: toNumber(summary.warning_count) ? 'warning' : 'success' },
        { label: '可继续计算', value: `${readyCount}/${totalCount}`, mono: true },
        { label: '结果人数', value: getWorkbenchResults(activity).length, mono: true },
      ])}
      <div class="compact-list-table">
        <table class="data-table">
          <thead>
            <tr>
              <th>级别</th>
              <th>问题</th>
              <th>工号</th>
              <th>姓名</th>
              <th>说明</th>
              <th>处理</th>
            </tr>
          </thead>
          <tbody>
            ${issues.length ? issues.slice(0, 20).map(issue => {
              const source = getExceptionSource(issue);
              const severity = safeExceptionSeverity(issue.severity);
              return `
                <tr class="${severity === 'error' ? 'row-danger' : ''}">
                  <td>${escapeHtml(severityLabel[severity] || '信息')}</td>
                  <td>${escapeHtml(issue.type || '-')}</td>
                  <td>${escapeHtml(issue.employee_id || '-')}</td>
                  <td>${escapeHtml(issue.name || '-')}</td>
                  <td>${escapeHtml(issue.detail || '-')}</td>
                  <td>${renderExceptionAction(issue, source)}</td>
                </tr>
              `;
            }).join('') : renderEmptyTableRow(6, '当前没有需要继续处理的问题')}
          </tbody>
        </table>
      </div>
    </section>
  `;
}

function renderFinalResults(activity) {
  const results = getWorkbenchResults(activity);
  if (!results.length) {
    return renderInlineEmptyState('暂无核算结果', '完成前面的步骤后，在这里查看最终结果。', '开始核算', 'executeCalculate()');
  }
  const filteredResults = getFilteredRows('results', results);
  const pageInfo = getPaginatedRows('results', filteredResults);
  const totalBonus = results.reduce((sum, row) => sum + toNumber(row.performance_bonus), 0);
  const avgBonus = results.length ? totalBonus / results.length : 0;
  const issueCount = results.filter(row => (row.exceptions || []).length > 0).length;

  return `
    <section class="step-section">
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
          <span>需关注</span>
          <span>${issueCount}</span>
        </div>
      </div>
    </section>
  `;
}

function renderStepContent(activity) {
  const stepKey = state.activityStep;
  if (stepKey === 'people') return renderPeopleStep(activity);
  if (stepKey === 'attendance') return renderAttendanceStep(activity);
  if (stepKey === 'salary') return renderSalaryStep(activity);
  if (stepKey === 'performance') return renderPerformanceStep(activity);
  if (stepKey === 'check') return renderCheckStep(activity);
  if (stepKey === 'export') return renderExportStep(activity);
  return '';
}

function renderPeopleStep(activity) {
  return `${renderStepMaterials('people', activity)}${renderNeedsPanel('people', activity)}${renderPeopleTable(activity)}`;
}

function renderAttendanceStep(activity) {
  return `${renderStepMaterials('attendance', activity)}${renderMaintainedRuleList('workHour', activity)}${renderNeedsPanel('attendance', activity)}${renderAttendanceSummaryTable(activity)}`;
}

function renderSalaryStep(activity) {
  return `${renderStepMaterials('salary', activity)}${renderMaintainedRuleList('fixedBase', activity)}${renderNeedsPanel('salary', activity)}${renderSalarySummaryTable(activity)}`;
}

function renderPerformanceStep(activity) {
  return `${renderStepMaterials('performance', activity)}${renderPerformanceInlineSupplement(activity)}${renderNeedsPanel('performance', activity)}${renderPerformanceSummaryTable(activity)}`;
}

function renderCheckStep(activity) {
  return `${renderNeedsPanel('check', activity)}${renderCheckPreview(activity)}`;
}

function renderExportStep(activity) {
  return `${renderFinalResults(activity)}`;
}

function renderStepHeader(step, activity) {
  return `
    <div class="step-topline">
      <div>
        <h3>${escapeHtml(step?.label || '')}</h3>
        <p class="step-topline-summary">${escapeHtml(getStepSummary(step?.key || '', activity))}</p>
      </div>
      ${renderStepHelp(step?.key || '')}
    </div>
  `;
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
  setSidebarCollapsed(false);
  loadBaseRoster();
  loadActivities();
});
