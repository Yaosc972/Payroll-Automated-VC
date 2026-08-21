/**
 * FBU美洲绩效奖金核算 - 数据看板交互逻辑
 */

// ═══ State ═══

const state = {
  currentPage: 'activities',
  activityStep: 'people',
  currentActivity: null,
  activities: [],
  currentUser: { id: 'local-fbu-user', name: '本地用户', avatarUrl: '' },
  activityRegions: [],
  activityOwnerFilter: 'mine',
  attendanceData: null,
  salaryData: null,
  performanceData: null,
  adjustmentData: null,
  supplementalLeaveData: null,
  baseOverrideData: null,
  ruleLists: null,
  ruleListsRequest: null,
  diagnosticsData: null,
  resultsData: null,
  baseRoster: null,
  lastImportResult: null,
  foundationRunDetails: {},
  foundationLoadingRunId: '',
  activitySectionsLoading: new Set(),
  workbenchSelectedResult: '',
  finalResultSlice: 'warehouse',
  finalResultsRemote: {
    runId: '',
    group: 'warehouse',
    query: '',
    rows: [],
    pagination: null,
    summary: null,
  },
  checkResultsRemote: {
    runId: '',
    rows: [],
    pagination: null,
    summary: null,
  },
  checkTab: 'base',
  workbenchResultFilter: 'all',
  workbenchStepSearch: {},
  hiddenStepNotices: {},
  workbenchTaskFilter: 'open',
  workbenchSupplementDraft: {
    employeeId: '',
    name: '',
    coefficient: '',
    note: '',
  },
  periodAdjustmentDraft: {
    employeeId: '',
    amount: '',
    sourceMonth: '',
    reason: '',
  },
  periodAdjustmentErrors: {},
  periodAdjustmentSubmitting: false,
  periodAdjustmentExpanded: false,
  maintainedRuleEditor: '',
  maintainedRuleDrafts: {
    workHour: [],
    fixedBase: [],
  },
  maintainedRulePending: '',
  salaryVerificationPendingEmployee: '',
  salaryVerificationPendingChoice: '',
  inlineActionNotes: {},
  workbenchPreviousAttendanceFile: null,
  workbenchUploadStates: {},
  salaryVerificationQueue: [],
  salaryVerificationPendingIds: new Set(),
  salaryVerificationFlushTimer: null,
  salaryVerificationFlushing: false,
  calculationPending: false,
  activeFbuUploadJobs: {},
  activeCalculationJob: null,
  calculationJobStatus: null,
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
    activities: { page: 1, pageSize: 50 },
    people: { page: 1, pageSize: 50 },
    attendance: { page: 1, pageSize: 50 },
    salary: { page: 1, pageSize: 50 },
    performance: { page: 1, pageSize: 50 },
    supplementalLeave: { page: 1, pageSize: 50 },
    check: { page: 1, pageSize: 50 },
    baseSummary: { page: 1, pageSize: 50 },
    baseOverrides: { page: 1, pageSize: 50 },
    results: { page: 1, pageSize: 50 },
    resultsWarehouse: { page: 1, pageSize: 50 },
    resultsFunctional: { page: 1, pageSize: 50 },
    resultsDistrict: { page: 1, pageSize: 50 },
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
    { materialKey: 'previousAttendance', label: '上月考勤', tag: '96工时制员工', hint: '上传OEHR上月考勤日报表', uploadType: 'previousAttendance', fileField: 'previous_attendance_file', required: false },
    { materialKey: 'supplementalLeave', label: '补充假勤', tag: '必传', hint: '上传线下sickpay与年假补充数据', uploadType: 'supplementalLeave', fileField: 'supplemental_leave_file', required: true },
  ],
  salary: [
    { materialKey: 'previousSalary', label: '上月薪资档案', tag: '必传', hint: '上传OEHR上月薪资档案（含离职）', uploadType: 'previousSalary', fileField: 'previous_salary_file', required: true },
    { materialKey: 'currentSalary', label: '当月薪资档案', tag: '必传', hint: '上传OEHR当月最新薪资档案（含离职）', uploadType: 'currentSalary', fileField: 'salary_file', required: true },
    { materialKey: 'salaryAdjustments', label: '全量调薪流程', tag: '必传', hint: '上传当前划分区域全量调薪管理导出', uploadType: 'salaryAdjustments', fileField: 'adjustment_file', required: true },
    { materialKey: 'transferHistory', label: '人事调动记录', tag: '必传', hint: '上传覆盖核算月及相邻生效日的当前划分区域调动记录', uploadType: 'transferHistory', fileField: 'transfer_file', required: true },
  ],
  performance: [
    { materialKey: 'performance', label: '绩效报表', tag: '必传', hint: '上传OEHR当月绩效报表', uploadType: 'performance', fileField: 'performance_file', required: true },
  ],
  check: [],
  export: [],
};

const SALARY_HISTORY_MATERIAL_FIELDS = {
  previousSalary: 'previous_salary_file',
  currentSalary: 'salary_file',
  salaryAdjustments: 'adjustment_file',
};

// ═══ API Base ═══

const API_BASE = '/api/fbu-performance';
const DEFAULT_FBU_REGION = { code: 'us_nj', name: 'FBU新泽西区' };
const DEFAULT_USER_AVATAR = 'assets/sigma-user-avatar-default.png';
const TABLE_PAGE_SIZE_OPTIONS = [25, 50, 100, 200];
const DEFAULT_TABLE_PAGE_SIZE = 50;

const ACTIVITY_STEP_SECTIONS = {
  people: ['roster_data'],
  attendance: [
    'attendance_view_data',
    'supplemental_leave_data',
    'base_override_data',
    'hourly_rate_policy_data',
  ],
  salary: [
    'salary_data',
    'previous_salary_data',
    'current_salary_data',
    'salary_verification_data',
    'adjustment_data',
    'transfer_data',
    'base_override_data',
    'hourly_rate_policy_data',
    'period_adjustment_data',
  ],
  performance: ['performance_data'],
  check: [
    'salary_verification_data',
    'supplemental_leave_data',
    'base_override_data',
    'diagnostics',
  ],
  export: [],
};

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function normalizeCurrentUser(user) {
  return {
    id: String(user?.id || user?.userId || 'local-fbu-user').trim(),
    name: String(user?.name || user?.email || '本地用户').trim(),
    avatarUrl: String(user?.avatarUrl || user?.avatar_url || '').trim(),
  };
}

function getActivityCreator(activity) {
  return {
    id: String(activity?.created_by_user_id || 'legacy').trim(),
    name: String(activity?.created_by_name || '历史活动').trim(),
    avatarUrl: String(activity?.created_by_avatar_url || '').trim(),
  };
}

function isMyActivity(activity) {
  const creatorId = getActivityCreator(activity).id;
  return Boolean(creatorId && creatorId !== 'legacy' && creatorId === state.currentUser.id);
}

function getActivityDisplayName(activity) {
  if (activity?.activity_name) return String(activity.activity_name);
  const monthToken = String(activity?.calc_month || '').replace('-', '') || '未指定月份';
  const regionName = activity?.region_name || DEFAULT_FBU_REGION.name;
  return `绩效奖金核算-${monthToken}-${regionName}`;
}

function formatPerformancePeriod(calcMonth) {
  const match = String(calcMonth || '').match(/^(\d{4})-(\d{2})$/);
  if (!match) return String(calcMonth || '-');
  return `${match[1]}年${Number(match[2])}月`;
}

function renderUserAvatar(user, className = '') {
  const avatarUrl = String(user?.avatarUrl || '').trim() || DEFAULT_USER_AVATAR;
  const safeClassName = String(className || '').replace(/[^a-zA-Z0-9_-]/g, '');
  return `<img class="user-avatar ${safeClassName}" src="${escapeHtml(avatarUrl)}" alt="" loading="lazy" onerror="this.onerror=null;this.src='${DEFAULT_USER_AVATAR}'">`;
}

function getUserActivityStorageKey() {
  return `sigma:fbu:last-owned-activity:${state.currentUser.id || 'local-fbu-user'}`;
}

function readLastOwnedActivityPreference() {
  try {
    return JSON.parse(localStorage.getItem(getUserActivityStorageKey()) || 'null') || null;
  } catch (error) {
    return null;
  }
}

function rememberOwnedActivity(activity = state.currentActivity, step = state.activityStep) {
  if (!activity?.run_id || !isMyActivity(activity)) return;
  try {
    localStorage.setItem(getUserActivityStorageKey(), JSON.stringify({
      runId: activity.run_id,
      step: ACTIVITY_STEPS.some(item => item.key === step) ? step : getActivityStepFromActivity(activity),
      updatedAt: new Date().toISOString(),
    }));
  } catch (error) {
    // Browser privacy settings can disable storage; the activity list remains usable.
  }
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

function getDisplayPosition(row, activity = getWorkbenchActivity()) {
  const position = String(row?.position || '').trim();
  if (position) return position;
  const sourceId = sourceEmployeeId(row);
  const salaryPosition = (activity?.salary_data?.employees || [])
    .find(item => sourceEmployeeId(item) === sourceId)?.position;
  if (String(salaryPosition || '').trim()) return String(salaryPosition).trim();
  return formatJobType(row?.job_type);
}

function formatJsArg(value) {
  return JSON.stringify(String(value ?? ''))
    .replaceAll('&', '\\u0026')
    .replaceAll('<', '\\u003C')
    .replaceAll('>', '\\u003E')
    .replaceAll('"', '&quot;');
}

function sourceEmployeeId(row) {
  return String(row?.source_employee_id || row?.employee_id || '').replace(/-1$/, '');
}

function getSpecialPersonTags(row, activity = getWorkbenchActivity()) {
  const tags = [];
  const sourceId = sourceEmployeeId(row);
  const baseRows = activity?.base_override_data?.employees || [];
  const adjustmentRows = activity?.adjustment_data?.employees || [];
  const adjustmentEvents = activity?.adjustment_data?.events || [];
  const salaryHistoryRow = (activity?.salary_verification_data?.employees || [])
    .find(item => sourceEmployeeId(item) === sourceId);
  const hasCurrentMonthAdjustment = Boolean(row?.calculation_segments?.length)
    || salaryHistoryRow?.resolution === 'in_month_split'
    || adjustmentRows.some(item => sourceEmployeeId(item) === sourceId)
    || adjustmentEvents.some(event => (
      sourceEmployeeId(event) === sourceId
      && String(event.effective_date).startsWith(activity?.calc_month || '')
    ));

  if (row?.job_type === 'district_manager') tags.push('区长');
  if (baseRows.some(item => sourceEmployeeId(item) === sourceId && item.rule_type === '96工时制')) tags.push('96工时制');
  if (baseRows.some(item => sourceEmployeeId(item) === sourceId && item.rule_type === '线下固定基数覆盖')) tags.push('固定基数');
  if (hasCurrentMonthAdjustment) tags.push('本月调薪');
  if (row?.personnel_status === '离职' || row?.resignation_date) tags.push('离职发放');

  return [...new Set(tags)].slice(0, 4);
}

function moveEmployeeNamePreview(event) {
  const preview = document.getElementById('employeeNamePreview');
  if (!preview || preview.hidden) return;
  const gap = 12;
  const rect = preview.getBoundingClientRect();
  const left = Math.min(event.clientX + gap, window.innerWidth - rect.width - gap);
  const top = Math.min(event.clientY + gap, window.innerHeight - rect.height - gap);
  preview.style.left = `${Math.max(gap, left)}px`;
  preview.style.top = `${Math.max(gap, top)}px`;
}

function showEmployeeNamePreview(event, name) {
  const text = event.currentTarget?.querySelector('.name-with-tags-text');
  if (!text || (text.scrollWidth <= text.clientWidth && String(name || '').length <= 14)) return;
  let preview = document.getElementById('employeeNamePreview');
  if (!preview) {
    preview = document.createElement('div');
    preview.id = 'employeeNamePreview';
    preview.className = 'employee-name-preview';
    document.body.appendChild(preview);
  }
  preview.textContent = name;
  preview.hidden = false;
  moveEmployeeNamePreview(event);
}

function hideEmployeeNamePreview() {
  const preview = document.getElementById('employeeNamePreview');
  if (preview) preview.hidden = true;
}

function renderNameWithTags(row, activity = getWorkbenchActivity()) {
  const tags = getSpecialPersonTags(row, activity);
  const visible = tags.slice(0, 3);
  const extra = tags.length - visible.length;
  const name = row?.name || '-';
  const tooltip = name === '-' ? '' : ` title="${escapeHtml(name)}"`;

  return `
    <span class="name-with-tags"${tooltip}
          onmouseenter="showEmployeeNamePreview(event, ${formatJsArg(name)})"
          onmousemove="moveEmployeeNamePreview(event)"
          onmouseleave="hideEmployeeNamePreview()">
      <span class="name-with-tags-text">${escapeHtml(name)}</span>
      ${visible.map(tag => `<span class="person-tag">${escapeHtml(tag)}</span>`).join('')}
      ${extra > 0 ? `<span class="person-tag">+${extra}</span>` : ''}
    </span>
  `;
}

function getMaterialStatus(material, activity) {
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

const workbenchUploadTimers = {};

function clearWorkbenchUploadTimer(type) {
  if (workbenchUploadTimers[type]) {
    clearInterval(workbenchUploadTimers[type]);
    delete workbenchUploadTimers[type];
  }
}

function getWorkbenchUploadState(type, activity = getWorkbenchActivity()) {
  const uploadState = state.workbenchUploadStates?.[type];
  if (!uploadState) return null;
  if (uploadState.runId && activity?.run_id && uploadState.runId !== activity.run_id) {
    return null;
  }
  return uploadState;
}

function setWorkbenchUploadState(type, nextState, { render = true } = {}) {
  const currentState = state.workbenchUploadStates[type] || {};
  const runId = type === 'roster' ? '' : (state.currentActivity?.run_id || currentState.runId || '');
  state.workbenchUploadStates = {
    ...state.workbenchUploadStates,
    [type]: {
      ...currentState,
      ...nextState,
      runId,
    },
  };
  if (render && state.currentPage === 'workbench') {
    renderWorkbenchCurrentStep();
  }
}

function clearWorkbenchUploadState(type, { render = true } = {}) {
  clearWorkbenchUploadTimer(type);
  if (type === 'previousAttendance') {
    state.workbenchPreviousAttendanceFile = null;
  }
  const nextStates = { ...state.workbenchUploadStates };
  delete nextStates[type];
  state.workbenchUploadStates = nextStates;
  if (render && state.currentPage === 'workbench') {
    renderWorkbenchCurrentStep();
  }
}

function startWorkbenchUploadProgress(type, file) {
  if (!file) return;
  clearWorkbenchUploadTimer(type);
  setWorkbenchUploadState(type, {
    fileName: file.name,
    fileSize: file.size,
    status: 'uploading',
    progress: 100,
    indeterminate: true,
    message: '正在上传并解析',
  });
}

function finishWorkbenchUploadProgress(type, fileName, message = '已解析', { render = true } = {}) {
  clearWorkbenchUploadTimer(type);
  setWorkbenchUploadState(type, {
    fileName: fileName || state.workbenchUploadStates[type]?.fileName || '',
    status: 'done',
    progress: 100,
    message,
  }, { render });
}

function failWorkbenchUploadProgress(type, fileName, message = '上传失败', { render = true } = {}) {
  clearWorkbenchUploadTimer(type);
  setWorkbenchUploadState(type, {
    fileName: fileName || state.workbenchUploadStates[type]?.fileName || '',
    status: 'failed',
    progress: 100,
    message,
  }, { render });
}

function getMaterialUploadView(material, status, activity) {
  const uploadState = getWorkbenchUploadState(material.uploadType, activity);
  const uploadedFile = status.fileName || '';
  const missingSalaryMaterials = Object.entries(SALARY_HISTORY_MATERIAL_FIELDS)
    .filter(([, fileField]) => !activity?.[fileField])
    .map(([type]) => uploadTypeLabels[type] || type);
  const waitsForSalaryMaterials = Boolean(
    uploadedFile
    && SALARY_HISTORY_MATERIAL_FIELDS[material.uploadType]
    && missingSalaryMaterials.length,
  );
  const baseView = {
    fileName: uploadedFile,
    statusText: status.text,
    detailText: uploadedFile
      ? waitsForSalaryMaterials
        ? `文件已解析，待补：${missingSalaryMaterials.join('、')}`
        : '文件已解析'
      : material.hint,
    actionNote: uploadedFile ? (waitsForSalaryMaterials ? '待补齐' : '已解析') : '',
    tone: status.tone || 'neutral',
    progress: uploadedFile ? 100 : 0,
    showProgress: false,
    busy: false,
    clearable: false,
  };

  if (!uploadState) return baseView;

  const fileName = uploadState.fileName || uploadedFile;
  if (uploadState.status === 'uploading') {
    return {
      fileName,
      statusText: '上传中',
      detailText: uploadState.message || '上传中',
      actionNote: uploadState.message || '上传中',
      tone: 'uploading',
      progress: toNumber(uploadState.progress, 100),
      indeterminate: uploadState.indeterminate !== false,
      showProgress: true,
      busy: true,
      clearable: false,
    };
  }
  if (uploadState.status === 'processing') {
    return {
      fileName,
      statusText: '处理中',
      detailText: uploadState.message || '正在解析',
      actionNote: uploadState.message || '正在解析',
      tone: 'uploading',
      progress: toNumber(uploadState.progress, 100),
      indeterminate: true,
      showProgress: true,
      busy: true,
      clearable: false,
    };
  }
  if (uploadState.status === 'selected') {
    return {
      fileName,
      statusText: '已选择',
      detailText: uploadState.message || '等待当月考勤完成后自动上传',
      actionNote: '已选择',
      tone: 'warning',
      progress: 100,
      showProgress: false,
      busy: false,
      clearable: material.uploadType === 'previousAttendance',
    };
  }
  if (uploadState.status === 'failed') {
    return {
      fileName,
      statusText: '失败',
      detailText: uploadState.message || '上传失败',
      actionNote: uploadState.message || '失败',
      tone: 'danger',
      progress: 100,
      showProgress: true,
      busy: false,
      clearable: true,
      canRetry: Boolean(uploadState.canRetry && uploadState.jobId),
      jobId: uploadState.jobId || '',
    };
  }
  if (uploadState.status === 'done') {
    return {
      fileName,
      statusText: '已上传',
      detailText: uploadState.message || '文件已解析',
      actionNote: uploadState.message || '已解析',
      tone: 'success',
      progress: 100,
      showProgress: false,
      busy: false,
      clearable: false,
    };
  }
  return baseView;
}

function renderMaterialRow(material, activity) {
  const status = getMaterialStatus(material, activity);
  if (!status.visible) return '';
  const uploadView = getMaterialUploadView(material, status, activity);
  const safeTone = ['success', 'warning', 'danger', 'neutral', 'uploading'].includes(uploadView.tone)
    ? uploadView.tone
    : 'neutral';
  const statusTone = safeTone === 'uploading' ? 'warning' : safeTone;
  const hasFile = Boolean(uploadView.fileName);
  const isPreviousAttendance = material.uploadType === 'previousAttendance';
  const canRetry = Boolean(uploadView.canRetry && uploadView.jobId);
  const actionText = canRetry
    ? '重试解析'
    : uploadView.busy
    ? '上传中'
    : isPreviousAttendance && hasFile
      ? '重选'
      : isPreviousAttendance
        ? '选择文件'
        : hasFile
        ? '重新上传'
        : '上传';
  return `
    <div class="material-row ${escapeHtml(safeTone)}" data-upload-type="${escapeHtml(material.uploadType)}">
      <div class="material-marker" aria-hidden="true">
        <span class="material-status-dot ${escapeHtml(safeTone)}"></span>
      </div>
      <div class="material-main">
        <div class="material-title">
          <strong>${escapeHtml(material.label)}</strong>
          <span class="mini-tag">${escapeHtml(material.tag)}</span>
          <span class="status-badge ${escapeHtml(statusTone)}">${escapeHtml(uploadView.statusText)}</span>
        </div>
        <div class="material-hint">${escapeHtml(material.hint)}</div>
        <div class="material-upload-file" title="${escapeHtml(uploadView.fileName || '')}">
          <span class="material-file-name">${escapeHtml(uploadView.fileName || '未选择文件')}</span>
          <span class="material-file-state">${escapeHtml(uploadView.detailText)}</span>
        </div>
        ${uploadView.showProgress ? `
          <div class="material-progress ${uploadView.indeterminate ? 'indeterminate' : ''}" role="progressbar" aria-valuemin="0" aria-valuemax="100" ${uploadView.indeterminate ? '' : `aria-valuenow="${Math.round(uploadView.progress)}"`}>
            <span style="width: ${Math.round(uploadView.progress)}%"></span>
          </div>
        ` : ''}
      </div>
      <div class="material-actions">
        <button class="btn btn-secondary btn-sm ${isPreviousAttendance ? 'btn-quiet' : ''}"
                type="button"
                onclick="${canRetry
                  ? `resumeFbuUploadJob(${formatJsArg(uploadView.jobId)})`
                  : `openWorkbenchUpload(${formatJsArg(material.uploadType)})`}"
                ${uploadView.busy ? 'disabled' : ''}>${actionText}</button>
        ${uploadView.actionNote ? `<span class="material-action-note ${escapeHtml(statusTone)}">${escapeHtml(uploadView.actionNote)}</span>` : ''}
        ${uploadView.clearable ? `<button class="material-clear-btn" type="button" aria-label="清除${escapeHtml(material.label)}文件" onclick="clearWorkbenchUpload(${formatJsArg(material.uploadType)})">×</button>` : ''}
      </div>
    </div>
  `;
}

function renderStepMaterials(stepKey, activity) {
  const rows = STEP_MATERIALS[stepKey] || [];
  if (!rows.length) return '';
  const layoutClass = stepKey === 'attendance' ? ' attendance-material-list' : '';
  return `
    <section class="step-section material-list${layoutClass}">
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
        <label class="page-size-select-wrap">
          <span>每页</span>
          <select class="page-size-select"
                  aria-label="每页条数"
                  onchange="changeTablePageSize(${formatJsArg(type)}, this.value)">
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
    const error = new Error(data.detail || data.message || `请求失败 (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return data;
}

function applyCurrentActivityPatch(patch = {}, { invalidateResults = false } = {}) {
  const runId = patch.run_id || state.currentActivity?.run_id;
  if (!runId) return null;
  const listed = state.activities.find(item => item.run_id === runId) || {};
  const current = state.currentActivity?.run_id === runId ? state.currentActivity : {};
  const updated = { ...listed, ...current, ...patch, run_id: runId };
  if (invalidateResults) {
    updated.results = [];
    updated.total_employees = 0;
    updated.total_bonus = 0;
    updated.match_rate = 0;
    updated.diagnostics = null;
    state.resultsData = null;
    state.diagnosticsData = null;
  }
  state.currentActivity = updated;
  state.activities = [
    updated,
    ...state.activities.filter(item => item.run_id !== runId),
  ];
  state.foundationRunDetails[runId] = updated;
  if (Object.hasOwn(patch, 'attendance_data')) state.attendanceData = patch.attendance_data;
  if (Object.hasOwn(patch, 'salary_data')) state.salaryData = patch.salary_data;
  if (Object.hasOwn(patch, 'performance_data')) state.performanceData = patch.performance_data;
  if (Object.hasOwn(patch, 'adjustment_data')) state.adjustmentData = patch.adjustment_data;
  if (Object.hasOwn(patch, 'supplemental_leave_data')) state.supplementalLeaveData = patch.supplemental_leave_data;
  if (Object.hasOwn(patch, 'base_override_data')) state.baseOverrideData = patch.base_override_data;
  if (Object.hasOwn(patch, 'results')) state.resultsData = patch.results;
  return updated;
}

function setInlineActionNote(key, message, tone = 'success', { render = true } = {}) {
  state.inlineActionNotes = {
    ...state.inlineActionNotes,
    [key]: {
      message,
      tone,
      at: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
    },
  };
  if (render && state.currentPage === 'workbench') {
    renderWorkbenchCurrentStep();
  }
}

function renderInlineActionNote(key) {
  const note = state.inlineActionNotes?.[key];
  if (!note?.message) return '';
  return `<span class="action-inline-note ${escapeHtml(note.tone || 'success')}">${escapeHtml(note.message)}</span>`;
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
  workbenchUploadPreviousSalary: document.getElementById('workbenchUploadPreviousSalary'),
  workbenchUploadCurrentSalary: document.getElementById('workbenchUploadCurrentSalary'),
  workbenchUploadSalaryAdjustments: document.getElementById('workbenchUploadSalaryAdjustments'),
  workbenchUploadTransferHistory: document.getElementById('workbenchUploadTransferHistory'),
  workbenchUploadPerformance: document.getElementById('workbenchUploadPerformance'),
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
  activityResumeButton: document.getElementById('activityResumeButton'),
  activityListMeta: document.getElementById('activityListMeta'),

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
  finalResultExplanationDialog: document.getElementById('finalResultExplanationDialog'),
  finalResultExplanationBody: document.getElementById('finalResultExplanationBody'),

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
  appDialogSelectField: document.getElementById('appDialogSelectField'),
  appDialogSelectLabel: document.getElementById('appDialogSelectLabel'),
  appDialogSelect: document.getElementById('appDialogSelect'),
  appDialogSelectHelp: document.getElementById('appDialogSelectHelp'),
  appDialogSelectError: document.getElementById('appDialogSelectError'),
  appDialogPreview: document.getElementById('appDialogPreview'),
  appDialogMonthPicker: document.getElementById('appDialogMonthPicker'),
  appDialogMonthYear: document.getElementById('appDialogMonthYear'),
  appDialogMonthGrid: document.getElementById('appDialogMonthGrid'),
  btnAppDialogMonthPrev: document.getElementById('btnAppDialogMonthPrev'),
  btnAppDialogMonthNext: document.getElementById('btnAppDialogMonthNext'),
  btnCloseAppDialog: document.getElementById('btnCloseAppDialog'),
  btnCancelAppDialog: document.getElementById('btnCancelAppDialog'),
  btnConfirmAppDialog: document.getElementById('btnConfirmAppDialog'),

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
const composingFilterInputs = new WeakSet();
const pendingCompositionFilters = new WeakMap();

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
  const input = event?.target;
  if (input instanceof HTMLInputElement
      && (event?.isComposing || composingFilterInputs.has(input))) {
    pendingCompositionFilters.set(input, filterName);
    return;
  }

  clearTimeout(filterTimers[filterName]);
  filterTimers[filterName] = setTimeout(() => {
    window[filterName]?.();
  }, 180);
}

document.addEventListener('compositionstart', (event) => {
  if (event.target instanceof HTMLInputElement) {
    composingFilterInputs.add(event.target);
    pendingCompositionFilters.delete(event.target);
  }
});

document.addEventListener('compositionend', (event) => {
  const input = event.target;
  if (!(input instanceof HTMLInputElement)) return;
  const filterName = pendingCompositionFilters.get(input);
  composingFilterInputs.delete(input);
  pendingCompositionFilters.delete(input);
  if (filterName) queueFilter(filterName);
});

// ═══ App Dialog ═══

let appDialogResolve = null;
let appDialogValidate = null;
let appDialogSelectValidate = null;
let appDialogPreviewRenderer = null;
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
  updateAppDialogPreview();
}

function updateAppDialogPreview() {
  if (!el.appDialogPreview) return;
  const preview = appDialogPreviewRenderer?.({
    value: el.appDialogInput?.value?.trim() || '',
    selectValue: el.appDialogSelect?.value || '',
  });
  el.appDialogPreview.textContent = preview || '';
  el.appDialogPreview.hidden = !preview;
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
    select = null,
    preview = null,
  } = options;

  return new Promise(resolve => {
    appDialogResolve = resolve;
    appDialogValidate = input?.validate || null;
    appDialogSelectValidate = select?.validate || null;
    appDialogPreviewRenderer = typeof preview === 'function' ? preview : null;

    setDialogTone(tone);
    el.appDialogTitle.textContent = title;
    el.appDialogMessage.textContent = message;
    el.btnConfirmAppDialog.textContent = confirmText;
    el.btnCancelAppDialog.textContent = cancelText;
    el.appDialogInputError.textContent = '';
    if (el.appDialogSelectError) el.appDialogSelectError.textContent = '';

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

    if (select && el.appDialogSelectField && el.appDialogSelect) {
      el.appDialogSelectField.hidden = false;
      el.appDialogSelectLabel.textContent = select.label || '';
      el.appDialogSelectHelp.textContent = select.help || '';
      const options = (select.options || []).map(option => {
        const element = document.createElement('option');
        element.value = String(option.value || '');
        element.textContent = String(option.label || option.value || '');
        return element;
      });
      el.appDialogSelect.replaceChildren(...options);
      el.appDialogSelect.value = select.value || options[0]?.value || '';
    } else if (el.appDialogSelectField && el.appDialogSelect) {
      el.appDialogSelectField.hidden = true;
      el.appDialogSelect.replaceChildren();
      el.appDialogSelectHelp.textContent = '';
    }

    updateAppDialogPreview();

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
  appDialogSelectValidate = null;
  appDialogPreviewRenderer = null;
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
  const selectValue = el.appDialogSelect?.value || '';
  if (!el.appDialogSelectField?.hidden && appDialogSelectValidate) {
    const validation = appDialogSelectValidate(selectValue);
    if (validation !== true) {
      el.appDialogSelectError.textContent = validation || '请选择有效选项';
      el.appDialogSelect.focus();
      return;
    }
  }
  closeAppDialog({ confirmed: true, value, selectValue });
}

el.btnCloseAppDialog?.addEventListener('click', () => closeAppDialog({ confirmed: false }));
el.btnCancelAppDialog?.addEventListener('click', () => closeAppDialog({ confirmed: false }));
el.btnConfirmAppDialog?.addEventListener('click', confirmAppDialog);
el.appDialog?.addEventListener('click', (event) => {
  if (event.target === el.appDialog) closeAppDialog({ confirmed: false });
});
el.appDialogInput?.addEventListener('input', () => {
  el.appDialogInputError.textContent = '';
  updateAppDialogPreview();
});
el.appDialogSelect?.addEventListener('change', () => {
  el.appDialogSelectError.textContent = '';
  updateAppDialogPreview();
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
  rememberOwnedActivity(state.currentActivity, stepKey);
  renderWorkbenchCurrentStep();
  ensureActivityStepData(stepKey);
}

function getStepIndex(stepKey) {
  return ACTIVITY_STEPS.findIndex(step => step.key === stepKey);
}

function getFirstIncompleteInputStep(activity = state.currentActivity) {
  return ['people', 'attendance', 'salary', 'performance'].find(
    stepKey => buildNeedsForStep(stepKey, activity).length > 0,
  ) || '';
}

function getActivityStepFromActivity(activity = state.currentActivity) {
  if (!activity) return 'people';
  if (activity.status === 'completed') return 'export';
  if (!activity.roster_file) return 'people';
  if (!activity.attendance_file || !activity.supplemental_leave_file) return 'attendance';
  if (
    !activity.previous_salary_file
    || !activity.salary_file
    || !activity.adjustment_file
    || !activity.transfer_file
  ) {
    return 'salary';
  }
  if (!activity.performance_file) return 'performance';
  return 'check';
}

function navigateTo(page) {
  let targetPage = page in el.pages ? page : 'activities';
  if (targetPage === 'workbench' && !state.currentActivity) {
    targetPage = 'activities';
  }
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
    workbench: { title: 'FBU美洲绩效核算', subtitle: getActivityDisplayName(state.currentActivity) },
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
    state.currentUser = normalizeCurrentUser(data.current_user);
    state.activityRegions = Array.isArray(data.regions) && data.regions.length
      ? data.regions
      : [DEFAULT_FBU_REGION];
    state.activities = data.runs || [];
    renderActivities();
    if (state.currentPage === 'workbench' && state.currentActivity) {
      renderWorkbench();
    } else if (state.currentPage !== 'activities') {
      navigateTo('activities');
    }
  } catch (error) {
    console.error('加载活动列表失败:', error);
    state.activities = [];
    if (state.currentPage !== 'activities') navigateTo('activities');
    renderActivities();
  }
}

function getWorkbenchActivity() {
  return state.currentActivity;
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
  if (state.ruleListsRequest) return state.ruleListsRequest;
  state.ruleListsRequest = apiJson(`${API_BASE}/rule-lists`)
    .then((data) => {
      state.ruleLists = data;
      return data;
    })
    .finally(() => {
      state.ruleListsRequest = null;
    });
  return state.ruleListsRequest;
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
    || (hasPrevious ? '已随考勤纳入跨月关联' : '未选择');
  return `
    <article class="workbench-source-card ${tone}">
      <div>
        <div class="workbench-source-top">
          <div class="workbench-source-title">上月考勤</div>
          <span class="status-badge ${hasPrevious ? 'success' : needsPrevious ? 'warning' : 'neutral'}">${hasPrevious ? '已覆盖' : needsPrevious ? '待自动上传' : '按需'}</span>
        </div>
        <div class="workbench-source-file" title="${escapeHtml(fileLabel)}">${escapeHtml(fileLabel)}</div>
        <div class="workbench-source-meta">
          <span class="workbench-chip ${hasPrevious ? 'success' : needsPrevious ? 'warning' : ''}">96工时制关联</span>
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
  const confirmPending = state.maintainedRulePending === `confirm:${kind}`;
  const actionsDisabled = Boolean(state.maintainedRulePending);
  return `
    <section class="step-section maintained-list">
      <div class="section-head compact">
        <div>
          <h3>${title}</h3>
          <p>${isWorkHour ? '本月默认沿用已确认的4名员工。' : '本月默认沿用已确认名单。'}</p>
        </div>
        <div class="section-actions">
          <span class="status-badge ${confirmed ? 'success' : 'warning'}">${confirmed ? '已确认' : '未确认'}</span>
          <button class="btn btn-secondary btn-sm" type="button" ${actionsDisabled ? 'disabled' : ''} onclick="openMaintainedRuleDialog(${formatJsArg(kind)})">编辑名单</button>
          <button class="btn btn-primary btn-sm" type="button" ${actionsDisabled ? 'disabled' : ''} ${confirmPending ? 'aria-busy="true"' : ''} onclick="confirmMaintainedRuleList(${formatJsArg(kind)})">${confirmPending ? '确认中…' : '确认名单'}</button>
          ${renderInlineActionNote(`ruleList-${kind}`)}
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
    </section>
  `;
}

function getMaintainedRuleRows(kind) {
  const lists = state.ruleLists || {};
  return kind === 'workHour'
    ? (lists.work_hour_employees || [])
    : (lists.fixed_base_employees || []);
}

function cloneMaintainedRuleRows(kind) {
  return getMaintainedRuleRows(kind).map(row => ({
    employee_id: row.employee_id || '',
    name: row.name || '',
    fixed_performance_base: row.fixed_performance_base ?? '',
    active: row.active !== false,
  }));
}

function renderMaintainedRuleEditor(kind) {
  if (state.maintainedRuleEditor !== kind) return '';
  const isWorkHour = kind === 'workHour';
  const rows = state.maintainedRuleDrafts?.[kind] || [];
  const saving = state.maintainedRulePending === `save:${kind}`;
  return `
    <div class="maintained-editor" data-maintained-editor="${escapeHtml(kind)}">
      <div class="maintained-editor-head">
        <strong>${isWorkHour ? '维护96工时制员工' : '维护固定基数人员'}</strong>
        <button class="btn btn-secondary btn-sm" type="button" onclick="addMaintainedRuleRow(${formatJsArg(kind)})">新增一行</button>
      </div>
      <div class="managed-rule-grid ${isWorkHour ? 'work-hour' : 'fixed-base'}">
        <div class="managed-rule-header">工号</div>
        <div class="managed-rule-header">姓名</div>
        ${isWorkHour ? '' : '<div class="managed-rule-header">固定基数</div>'}
        <div class="managed-rule-header">状态</div>
        <div class="managed-rule-header">操作</div>
        ${rows.map((row, index) => `
          <input class="managed-rule-input mono" type="text" value="${escapeHtml(row.employee_id || '')}" placeholder="zt0000000" oninput="updateMaintainedRuleDraft(${formatJsArg(kind)}, ${index}, 'employee_id', this.value)">
          <input class="managed-rule-input" type="text" value="${escapeHtml(row.name || '')}" placeholder="员工姓名" oninput="updateMaintainedRuleDraft(${formatJsArg(kind)}, ${index}, 'name', this.value)">
          ${isWorkHour ? '' : `<input class="managed-rule-input mono" type="number" min="0" step="0.01" value="${escapeHtml(row.fixed_performance_base ?? '')}" placeholder="3000" oninput="updateMaintainedRuleDraft(${formatJsArg(kind)}, ${index}, 'fixed_performance_base', this.value)">`}
          <div class="managed-rule-status">
            <button class="${row.active !== false ? 'active' : ''}" type="button" onclick="updateMaintainedRuleDraft(${formatJsArg(kind)}, ${index}, 'active', true)">启用</button>
            <button class="${row.active === false ? 'active danger' : ''}" type="button" onclick="updateMaintainedRuleDraft(${formatJsArg(kind)}, ${index}, 'active', false)">停用</button>
          </div>
          <button class="managed-rule-remove" type="button" onclick="removeMaintainedRuleRow(${formatJsArg(kind)}, ${index})">移除</button>
        `).join('')}
      </div>
      <div class="maintained-editor-actions">
        <button class="btn btn-secondary btn-sm" type="button" onclick="closeMaintainedRuleDialog()">取消</button>
        <button class="btn btn-primary btn-sm" type="button" ${saving ? 'disabled aria-busy="true"' : ''} onclick="saveMaintainedRuleList(${formatJsArg(kind)})">${saving ? '保存中…' : '保存名单'}</button>
      </div>
    </div>
  `;
}

function openMaintainedRuleDialog(kind) {
  state.maintainedRuleEditor = kind;
  state.maintainedRuleDrafts[kind] = cloneMaintainedRuleRows(kind);
  const dialog = document.getElementById('ruleListDialog');
  const title = document.getElementById('ruleListDialogTitle');
  const body = document.getElementById('ruleListDialogBody');
  if (!dialog || !body || !title) return;
  title.textContent = kind === 'workHour' ? '编辑96工时制员工' : '编辑固定基数人员';
  body.innerHTML = renderMaintainedRuleEditor(kind);
  openModal(dialog, body.querySelector('input, button'));
}

function closeMaintainedRuleDialog() {
  const dialog = document.getElementById('ruleListDialog');
  closeModal(dialog);
  state.maintainedRuleEditor = '';
}

function renderMaintainedRuleDialogBody() {
  if (!state.maintainedRuleEditor) return;
  const body = document.getElementById('ruleListDialogBody');
  if (body) body.innerHTML = renderMaintainedRuleEditor(state.maintainedRuleEditor);
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
      title: '暂无待处理事项',
      meta: '当前导入状态可继续核算。',
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
  if (state.maintainedRulePending) return;
  state.maintainedRulePending = `confirm:${kind}`;
  setInlineActionNote(`ruleList-${kind}`, '确认中…', 'warning', { render: false });
  renderWorkbenchCurrentStep();
  try {
    if (!state.ruleLists) await loadRuleLists();
    const data = await apiJson(`${API_BASE}/runs/${state.currentActivity.run_id}/rule-lists/confirm`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(state.ruleLists),
    });
    state.baseOverrideData = data.preview;
    state.currentActivity.base_override_file = '页面维护';
    state.currentActivity.base_override_data = data.preview;
    setInlineActionNote(`ruleList-${kind}`, kind === 'workHour' ? '96工时制名单已确认' : '固定基数名单已确认', 'success', { render: false });
  } catch (error) {
    setInlineActionNote(`ruleList-${kind}`, `名单确认失败：${error.message}`, 'warning', { render: false });
  } finally {
    state.maintainedRulePending = '';
    renderWorkbenchCurrentStep();
  }
}

function toggleMaintainedRuleEditor(kind) {
  if (state.maintainedRuleEditor === kind) {
    state.maintainedRuleEditor = '';
  } else {
    state.maintainedRuleEditor = kind;
    state.maintainedRuleDrafts[kind] = cloneMaintainedRuleRows(kind);
  }
  renderWorkbenchCurrentStep();
}

function updateMaintainedRuleDraft(kind, index, field, value) {
  const rows = state.maintainedRuleDrafts?.[kind] || [];
  if (!rows[index]) return;
  rows[index] = {
    ...rows[index],
    [field]: value,
  };
  state.maintainedRuleDrafts[kind] = rows;
  if (field === 'active') renderMaintainedRuleDialogBody();
}

function addMaintainedRuleRow(kind) {
  const rows = state.maintainedRuleDrafts?.[kind] || [];
  rows.push({
    employee_id: '',
    name: '',
    fixed_performance_base: '',
    active: true,
  });
  state.maintainedRuleDrafts[kind] = rows;
  renderMaintainedRuleDialogBody();
}

function removeMaintainedRuleRow(kind, index) {
  const rows = state.maintainedRuleDrafts?.[kind] || [];
  state.maintainedRuleDrafts[kind] = rows.filter((_, rowIndex) => rowIndex !== index);
  renderMaintainedRuleDialogBody();
}

function normalizeMaintainedRuleRows(kind) {
  const isWorkHour = kind === 'workHour';
  return (state.maintainedRuleDrafts?.[kind] || [])
    .map(row => ({
      employee_id: String(row.employee_id || '').trim(),
      name: String(row.name || '').trim(),
      fixed_performance_base: isWorkHour ? undefined : row.fixed_performance_base,
      active: row.active !== false,
    }))
    .filter(row => row.employee_id)
    .map(row => {
      if (isWorkHour) {
        return {
          employee_id: row.employee_id,
          name: row.name,
          active: row.active,
        };
      }
      return {
        employee_id: row.employee_id,
        name: row.name,
        fixed_performance_base: row.fixed_performance_base === '' ? null : row.fixed_performance_base,
        active: row.active,
      };
    });
}

async function saveMaintainedRuleList(kind) {
  if (state.maintainedRulePending) return;
  state.maintainedRulePending = `save:${kind}`;
  renderMaintainedRuleDialogBody();
  try {
    if (!state.ruleLists) await loadRuleLists();
    const payload = {
      work_hour_employees: kind === 'workHour'
        ? normalizeMaintainedRuleRows('workHour')
        : (state.ruleLists.work_hour_employees || []),
      fixed_base_employees: kind === 'fixedBase'
        ? normalizeMaintainedRuleRows('fixedBase')
        : (state.ruleLists.fixed_base_employees || []),
    };
    const data = await apiJson(`${API_BASE}/rule-lists`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    state.ruleLists = data;
    state.maintainedRuleDrafts[kind] = cloneMaintainedRuleRows(kind);
    setInlineActionNote(`ruleList-${kind}`, kind === 'workHour' ? '96工时制名单已保存' : '固定基数名单已保存', 'success', { render: false });
    closeMaintainedRuleDialog();
    renderWorkbenchCurrentStep();
  } catch (error) {
    setInlineActionNote(`ruleList-${kind}`, `名单保存失败：${error.message}`, 'warning', { render: false });
    showNotification(`名单保存失败：${error.message}`, 'error');
  } finally {
    state.maintainedRulePending = '';
    renderMaintainedRuleDialogBody();
  }
}

function renderWorkbenchPerformanceSupplement() {
  // 页面只补充核算必须值；明细留痕仍走线下表导入。
  const draft = state.workbenchSupplementDraft || {};
  const supplementRows = (state.performanceData?.employees || [])
    .filter(row => row?.performance_source === '绩效补录');
  return `
    <div class="performance-supplement-inline">
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
          <label for="workbenchSupplementCoefficient">绩效系数</label>
          <input id="workbenchSupplementCoefficient" type="number" step="0.01" min="0" value="${escapeHtml(draft.coefficient || '')}" placeholder="0.93" oninput="updateWorkbenchSupplementDraft()">
        </div>
        <div class="workbench-inline-field wide">
          <label for="workbenchSupplementNote">备注</label>
          <input id="workbenchSupplementNote" type="text" value="${escapeHtml(draft.note || '')}" placeholder="离职绩效补录" oninput="updateWorkbenchSupplementDraft()">
        </div>
        <button class="btn btn-primary" id="btnWorkbenchSaveSupplement" type="button" onclick="saveWorkbenchPerformanceSupplement()">保存并继续</button>
      </div>
      ${supplementRows.length ? `
        <div class="performance-supplement-list" aria-label="已补录人员">
          ${supplementRows.slice(-6).map(row => `
            <span class="performance-supplement-chip">
              <strong>${escapeHtml(row.employee_id || '-')}</strong>
              ${escapeHtml(row.name || '-')}
              <em>${formatCoefficient(row.coefficient)}</em>
            </span>
          `).join('')}
        </div>
      ` : ''}
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
      <td>${escapeHtml(getDisplayPosition(result, getWorkbenchActivity()))}</td>
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
  const filteredResults = getWorkbenchFilteredResults(results);
  const pageInfo = getPaginatedRows('results', filteredResults);
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
          <div class="workbench-panel-sub">最终合并结果按员工展示，白/夜班拆行在行内展开。</div>
        </div>
        <div class="workbench-source-actions">
          ${filters.map(([key, label]) => `
            <button class="workbench-segment ${state.workbenchResultFilter === key ? 'active' : ''}" type="button" onclick="setWorkbenchResultFilter(${formatJsArg(key)})">${escapeHtml(label)}</button>
          `).join('')}
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
            ${pageInfo.items.length ? pageInfo.items.map(renderWorkbenchResultRow).join('') : renderEmptyTableRow(12, results.length ? '当前筛选没有记录' : '暂无核算结果')}
          </tbody>
        </table>
      </div>
      ${renderTablePagination('results', pageInfo)}
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
    ['严重异常', toNumber(summary.error_count), `${toNumber(summary.issue_count)} 项检查`, toNumber(summary.error_count) ? 'danger' : 'success'],
    ['补充假勤', `${toNumber(supplementalSummary.pending_count)} 待确认`, `计入 ${formatHours(supplementalSummary.include_hours)}`, toNumber(supplementalSummary.pending_count) ? 'warning' : 'success'],
    ['调薪拆分', toNumber(adjustmentSummary.total_events || adjustmentSummary.total_segments), `人工 ${toNumber(adjustmentSummary.manual_split_required)} · 自动 ${toNumber(adjustmentSummary.auto_split_ready)}`, toNumber(adjustmentSummary.manual_split_required) ? 'warning' : 'success'],
    ['96工时规则', toNumber(baseSummary.active_count), `固定基数 ${formatCurrency(baseSummary.active_fixed_base)}`, ''],
  ];
  return `
    <section class="workbench-panel workbench-audit-ledger">
      <div class="workbench-panel-head">
        <div>
          <div class="workbench-panel-title">查看说明</div>
          <div class="workbench-panel-sub">只展示会影响结果或需要复核的说明。</div>
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

function renderCalculateButton(canCalculate) {
  const isPending = state.calculationPending
    || ['queued', 'processing'].includes(state.calculationJobStatus?.status);
  const disabled = !canCalculate || isPending;
  return `
    <button class="btn btn-primary btn-sm" type="button" onclick="executeCalculate()"
      ${disabled ? 'disabled' : ''} aria-busy="${isPending ? 'true' : 'false'}">
      ${isPending ? '<span class="button-spinner" aria-hidden="true"></span>核算中…' : '开始核算'}
    </button>
  `;
}

function renderWorkbench() {
  if (!el.workbenchContent) return;
  const activity = getWorkbenchActivity();
  if (!activity) {
    el.workbenchContent.innerHTML = `
      <div class="workbench-empty">
        <svg class="workbench-empty-illustration" viewBox="0 0 156 112" fill="none" aria-hidden="true">
          <rect x="20" y="18" width="116" height="76" rx="10" fill="#EEF4FF" stroke="#B8CCFF" stroke-width="1.5"/>
          <rect x="34" y="32" width="48" height="8" rx="4" fill="#2563EB" opacity="0.9"/>
          <rect x="34" y="48" width="88" height="6" rx="3" fill="#C9D8FF"/>
          <rect x="34" y="61" width="72" height="6" rx="3" fill="#DDE7FF"/>
          <rect x="34" y="74" width="58" height="6" rx="3" fill="#DDE7FF"/>
          <circle cx="118" cy="35" r="12" fill="#D1FAE5" stroke="#65CFA6" stroke-width="1.5"/>
          <path d="M112.5 35.2l3.5 3.5 7-8" stroke="#0F766E" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
          <path d="M46 94h64" stroke="#CBD5E1" stroke-width="3" stroke-linecap="round"/>
          <path d="M106 16l7-7 7 7M113 9v17" stroke="#8BA5F8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        <h2>暂无月度活动</h2>
        <p>创建本月活动后，再导入花名册、考勤、薪资和绩效数据。</p>
        <button class="btn btn-primary" type="button" onclick="document.getElementById('btnNewActivity')?.click()">新建活动</button>
      </div>
    `;
    return;
  }
  const activeStep = ACTIVITY_STEPS.find(step => step.key === state.activityStep) || ACTIVITY_STEPS[0];
  const creator = getActivityCreator(activity);
  const canCalculate = buildNeedsForStep('check', activity).length === 0;
  el.workbenchContent.innerHTML = `
    <section class="activity-titlebar activity-page-titlebar">
      <div class="activity-title-main">
        <div class="activity-title-line">
          <h2>${escapeHtml(getActivityDisplayName(activity))}</h2>
        </div>
        <div class="activity-title-meta">
          <span>活动 ${escapeHtml(activity.run_id || '-')}</span>
          <span>${escapeHtml(activeStep.label || '-')}</span>
        </div>
      </div>
      <div class="activity-title-context">
        <div class="activity-creator-card">
          ${renderUserAvatar(creator, 'activity-creator-avatar')}
          <div>
            <strong>${escapeHtml(creator.name)}</strong>
            <span>${escapeHtml(activity.region_name || DEFAULT_FBU_REGION.name)} · ${escapeHtml(formatDateTime(activity.created_at))}</span>
          </div>
        </div>
        <div class="activity-title-actions">
          ${state.activityStep === 'check' ? renderCalculateButton(canCalculate) : ''}
          <button class="btn btn-secondary btn-sm activity-return-button" type="button" onclick="navigateTo('activities')">活动列表</button>
        </div>
      </div>
    </section>
    ${renderActivityStepper(activity)}
    <section class="activity-step-body">
      ${renderStepHeader(activeStep, activity)}
      ${renderStepContent(activity)}
    </section>
  `;
}

function renderWorkbenchCurrentStep({ preserveScroll = true } = {}) {
  if (!el.workbenchContent) return;
  const activity = getWorkbenchActivity();
  const stepBody = el.workbenchContent.querySelector('.activity-step-body');
  const stepper = el.workbenchContent.querySelector('.activity-stepper');
  if (!activity || !stepBody || !stepper) {
    renderWorkbench();
    return;
  }

  const scrollX = window.scrollX;
  const scrollY = window.scrollY;
  const activeStep = ACTIVITY_STEPS.find(step => step.key === state.activityStep) || ACTIVITY_STEPS[0];
  const canCalculate = buildNeedsForStep('check', activity).length === 0;
  const titleMeta = el.workbenchContent.querySelectorAll('.activity-title-meta span');
  if (titleMeta.length) titleMeta[titleMeta.length - 1].textContent = activeStep.label || '-';
  const titleActions = el.workbenchContent.querySelector('.activity-title-actions');
  if (titleActions) {
    titleActions.innerHTML = `
      ${state.activityStep === 'check' ? renderCalculateButton(canCalculate) : ''}
      <button class="btn btn-secondary btn-sm activity-return-button" type="button" onclick="navigateTo('activities')">返回</button>
    `;
  }
  stepper.outerHTML = renderActivityStepper(activity);
  stepBody.innerHTML = `
    ${renderStepHeader(activeStep, activity)}
    ${renderStepContent(activity)}
  `;
  if (preserveScroll) restoreScrollPosition(scrollX, scrollY);
}

function renderActivities() {
  renderActivityResumeAction();
  renderActivityOwnerFilters();
  const filteredActivities = state.activityOwnerFilter === 'mine'
    ? state.activities.filter(isMyActivity)
    : state.activities;

  if (!filteredActivities.length) {
    const message = state.activityOwnerFilter === 'mine'
      ? '你还没有创建活动，可点击右上角新建活动'
      : '暂无活动';
    el.activitiesBody.innerHTML = renderEmptyTableRow(5, message);
    renderActivitiesPagination(null);
    return;
  }

  const pageInfo = getPaginatedRows('activities', filteredActivities);
  renderActivitiesPagination(pageInfo);

  el.activitiesBody.innerHTML = pageInfo.items.map(activity => {
    const statusMeta = getActivityStatusMeta(activity);
    const stepKey = getActivityStepFromActivity(activity);
    const activeStep = ACTIVITY_STEPS.find(step => step.key === stepKey) || ACTIVITY_STEPS[0];
    const completedSteps = activity.status === 'completed'
      ? ACTIVITY_STEPS.length
      : Math.max(0, getStepIndex(stepKey));
    const creator = getActivityCreator(activity);

    return `
      <tr class="activity-row ${statusMeta.rowClass}" data-activity-row-id="${escapeHtml(activity.run_id || '')}">
        <td>
          <div class="activity-task">
            <div class="activity-task-main">
              <span class="activity-name">${escapeHtml(getActivityDisplayName(activity))}</span>
              <span class="status-badge ${statusMeta.className}">${statusMeta.text}</span>
            </div>
            <div class="activity-task-meta">活动 ${escapeHtml(activity.run_id || '-')}</div>
          </div>
        </td>
        <td>
          <span class="activity-period">${escapeHtml(formatPerformancePeriod(activity.calc_month))}</span>
        </td>
        <td>
          <div class="activity-owner">
            ${renderUserAvatar(creator, 'activity-list-avatar')}
            <div>
              <strong>${escapeHtml(creator.name)}</strong>
              <span>${escapeHtml(formatDateTime(activity.created_at))}</span>
            </div>
          </div>
        </td>
        <td>
          <div class="activity-stage">
            <div class="activity-stage-head">
              <span class="activity-stage-caption">${activity.status === 'completed' ? '核算完成' : `当前：${activeStep.label}`}</span>
              <span class="activity-progress-value">${completedSteps}/${ACTIVITY_STEPS.length}</span>
            </div>
            <div class="activity-progress-track" aria-label="核算进度 ${completedSteps}/${ACTIVITY_STEPS.length}">
              ${renderActivityProgress(completedSteps)}
            </div>
          </div>
        </td>
        <td>
          <div class="activity-action-cell">
            <button class="btn btn-primary btn-sm" onclick="enterActivity(${formatJsArg(activity.run_id)})">${activity.status === 'completed' ? '查看' : '进入'}</button>
            <button class="activity-delete-button" type="button" title="删除活动" aria-label="删除活动 ${escapeHtml(activity.run_id || '')}" onclick="deleteActivity(${formatJsArg(activity.run_id)})">
              <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 6h12M8 6V4h4v2m-6 0 1 10h6l1-10M8.5 9v4m3-4v4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
            </button>
          </div>
        </td>
      </tr>
    `;
  }).join('');
}

function renderActivityResumeAction() {
  const button = el.activityResumeButton;
  if (!button) return;
  const myActivities = state.activities.filter(isMyActivity);
  const preference = readLastOwnedActivityPreference();
  const activity = myActivities.find(item => item.run_id === preference?.runId)
    || myActivities[0]
    || null;

  if (!activity) {
    button.hidden = true;
    button.textContent = '';
    button.removeAttribute('title');
    button.onclick = null;
    return;
  }

  const preferredStep = preference?.runId === activity.run_id ? preference.step : '';
  const stepKey = ACTIVITY_STEPS.some(step => step.key === preferredStep)
    ? preferredStep
    : getActivityStepFromActivity(activity);
  const step = ACTIVITY_STEPS.find(item => item.key === stepKey) || ACTIVITY_STEPS[0];
  button.hidden = false;
  button.textContent = activity.status === 'completed'
    ? '查看上次活动'
    : `继续上次 · ${step.label}`;
  button.title = `${getActivityDisplayName(activity)} · 活动 ${activity.run_id}`;
  button.onclick = () => enterActivity(activity.run_id);
}

function renderActivityOwnerFilters() {
  const mineCount = state.activities.filter(isMyActivity).length;
  const allCount = state.activities.length;
  document.querySelectorAll('[data-activity-owner-filter]').forEach(button => {
    const filter = button.dataset.activityOwnerFilter;
    button.classList.toggle('active', filter === state.activityOwnerFilter);
    button.setAttribute('aria-pressed', filter === state.activityOwnerFilter ? 'true' : 'false');
    const count = filter === 'mine' ? mineCount : allCount;
    button.querySelector('[data-filter-count]')?.replaceChildren(String(count));
  });
  if (el.activityListMeta) {
    el.activityListMeta.textContent = `${mineCount} 个我的活动 · ${allCount} 个全部活动`;
  }
}

function setActivityOwnerFilter(filter) {
  if (!['mine', 'all'].includes(filter)) return;
  state.activityOwnerFilter = filter;
  state.tablePagination.activities.page = 1;
  renderActivities();
}

function renderActivitiesPagination(pageInfo) {
  const wrap = document.getElementById('activitiesPagination');
  if (!wrap) return;
  wrap.innerHTML = pageInfo && pageInfo.total
    ? renderTablePagination('activities', pageInfo)
    : '';
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

function renderActivityProgress(completedSteps) {
  return ACTIVITY_STEPS.map((step, index) => `
    <span class="activity-progress-segment ${index < completedSteps ? 'done' : ''}" title="${escapeHtml(step.label)}"></span>
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
    const include = [
      'attendance_view_data',
      'salary_data',
      'performance_data',
      'adjustment_data',
      'supplemental_leave_data',
      'base_override_data',
    ].join(',');
    const detail = await apiJson(
      `${API_BASE}/runs/${activity.run_id}?include=${encodeURIComponent(include)}`,
    );
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
            <span>基础花名册仅在月度活动的“人员核对”步骤上传，避免脱离活动流程单独更新。</span>
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
          <p class="empty-state-sub">${escapeHtml(state.currentActivity.calc_month || '')} 当前没有需要处理的问题。</p>
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
  const targetStep = stepMap[page] || '';
  await enterActivity(activityId, { preservePage: true, initialStep: targetStep });
  setActivityStep(targetStep || getActivityStepFromActivity(state.currentActivity));
  navigateTo('workbench');
}

function resetCurrentActivitySections() {
  state.attendanceData = null;
  state.salaryData = null;
  state.performanceData = null;
  state.adjustmentData = null;
  state.supplementalLeaveData = null;
  state.baseOverrideData = null;
  state.diagnosticsData = null;
  state.resultsData = null;
  state.finalResultsRemote = {
    runId: '',
    group: 'warehouse',
    query: '',
    rows: [],
    pagination: null,
    summary: null,
  };
  state.checkResultsRemote = {
    runId: '',
    rows: [],
    pagination: null,
    summary: null,
  };
  state.activeCalculationJob = null;
  state.calculationJobStatus = null;
}

function clearRemoteResultViews(runId = '') {
  if (!runId || state.finalResultsRemote.runId === runId) {
    state.finalResultsRemote = {
      runId: '',
      group: 'warehouse',
      query: '',
      rows: [],
      pagination: null,
      summary: null,
    };
  }
  if (!runId || state.checkResultsRemote.runId === runId) {
    state.checkResultsRemote = {
      runId: '',
      rows: [],
      pagination: null,
      summary: null,
    };
  }
}

function mergeCurrentActivityPayload(payload) {
  if (!payload?.run_id) return state.currentActivity;
  const current = state.currentActivity?.run_id === payload.run_id
    ? state.currentActivity
    : {};
  const loadedSections = new Set([
    ...(current.loaded_sections || []),
    ...(payload.loaded_sections || []),
  ]);
  ['roster_data', 'diagnostics'].forEach(field => {
    if (Object.prototype.hasOwnProperty.call(payload, field)) loadedSections.add(field);
  });
  const activity = {
    ...current,
    ...payload,
    loaded_sections: [...loadedSections],
  };
  if (payload.status && payload.status !== 'completed') {
    state.resultsData = [];
    clearRemoteResultViews(payload.run_id);
  }
  state.currentActivity = activity;
  state.foundationRunDetails[activity.run_id] = activity;

  if (Object.prototype.hasOwnProperty.call(payload, 'attendance_data')) {
    state.attendanceData = payload.attendance_data || null;
  }
  if (Object.prototype.hasOwnProperty.call(payload, 'salary_data')) {
    state.salaryData = payload.salary_data || null;
  }
  if (Object.prototype.hasOwnProperty.call(payload, 'performance_data')) {
    state.performanceData = payload.performance_data || null;
  }
  if (Object.prototype.hasOwnProperty.call(payload, 'adjustment_data')) {
    state.adjustmentData = payload.adjustment_data || null;
  }
  if (Object.prototype.hasOwnProperty.call(payload, 'supplemental_leave_data')) {
    state.supplementalLeaveData = payload.supplemental_leave_data || null;
  }
  if (Object.prototype.hasOwnProperty.call(payload, 'base_override_data')) {
    state.baseOverrideData = payload.base_override_data || null;
  }
  if (Object.prototype.hasOwnProperty.call(payload, 'diagnostics')) {
    state.diagnosticsData = payload.diagnostics || null;
  }
  if (Object.prototype.hasOwnProperty.call(payload, 'results')) {
    state.resultsData = Array.isArray(payload.results) ? payload.results : [];
  }
  return activity;
}

function activityStepLoadingKey(stepKey, activity = state.currentActivity) {
  return `${activity?.run_id || ''}:${stepKey || ''}`;
}

async function ensureActivityStepData(stepKey, options = {}) {
  const { render = true, force = false } = options;
  const activity = state.currentActivity;
  if (!activity?.run_id) return null;
  if (stepKey === 'export') {
    const remote = state.finalResultsRemote;
    if (
      !force
      && remote.runId === activity.run_id
      && remote.group === state.finalResultSlice
      && remote.pagination
    ) {
      return activity;
    }
    await loadFinalResultsPage({ page: 1, render });
    return state.currentActivity;
  }
  const required = ACTIVITY_STEP_SECTIONS[stepKey] || [];
  const loaded = new Set(activity.loaded_sections || []);
  const missing = force ? required : required.filter(field => !loaded.has(field));
  if (!missing.length) {
    if (
      stepKey === 'check'
      && activity.status === 'completed'
      && (
        force
        || state.checkResultsRemote.runId !== activity.run_id
        || !state.checkResultsRemote.pagination
      )
    ) {
      await loadCheckResultsPage({ page: 1, render });
    }
    return activity;
  }

  const loadingKey = activityStepLoadingKey(stepKey, activity);
  if (state.activitySectionsLoading.has(loadingKey)) return activity;
  state.activitySectionsLoading.add(loadingKey);
  if (render && state.currentPage === 'workbench') renderWorkbench();

  try {
    const include = ['core', ...missing].join(',');
    const payload = await apiJson(
      `${API_BASE}/runs/${activity.run_id}?include=${encodeURIComponent(include)}`,
    );
    if (state.currentActivity?.run_id !== activity.run_id) return null;
    const merged = mergeCurrentActivityPayload(payload);
    if (stepKey === 'check' && merged?.status === 'completed') {
      await loadCheckResultsPage({ page: 1, render: false });
    }
    return merged;
  } catch (error) {
    console.error(`加载活动${stepKey}区块失败:`, error);
    showNotification(`加载当前步骤数据失败：${error.message}`, 'error');
    return null;
  } finally {
    state.activitySectionsLoading.delete(loadingKey);
    if (render && state.currentPage === 'workbench') renderWorkbench();
  }
}

async function enterActivity(activityId, options = {}) {
  const {
    preservePage = false,
    preserveStep = false,
    initialStep = '',
    refreshSections = false,
  } = options;
  const previousStep = state.activityStep;

  try {
    const ruleListsRequest = state.ruleLists ? null : loadRuleLists();
    if (!state.baseRoster) loadBaseRoster();
    const isDifferentActivity = state.currentActivity?.run_id !== activityId;
    let activity = await apiJson(`${API_BASE}/runs/${activityId}?include=core`);

    if (isDifferentActivity) {
      resetTableControls();
    }
    if (isDifferentActivity || refreshSections) {
      resetCurrentActivitySections();
      state.currentActivity = null;
    }
    if (isDifferentActivity) {
      state.periodAdjustmentDraft = {
        employeeId: '',
        amount: '',
        sourceMonth: activity.calc_month || '',
        reason: '',
      };
      state.periodAdjustmentErrors = {};
      state.periodAdjustmentSubmitting = false;
      state.periodAdjustmentExpanded = false;
    }

    activity = mergeCurrentActivityPayload(activity);
    const ownedPreference = readLastOwnedActivityPreference();
    const preferredOwnedStep = isMyActivity(activity)
      && ownedPreference?.runId === activity.run_id
      && ACTIVITY_STEPS.some(step => step.key === ownedPreference.step)
      ? ownedPreference.step
      : '';
    if (preserveStep && !isDifferentActivity && ACTIVITY_STEPS.some(step => step.key === previousStep)) {
      state.activityStep = previousStep;
    } else if (ACTIVITY_STEPS.some(step => step.key === initialStep)) {
      state.activityStep = initialStep;
    } else if (preferredOwnedStep) {
      state.activityStep = preferredOwnedStep;
    } else {
      state.activityStep = getActivityStepFromActivity(activity);
    }
    rememberOwnedActivity(activity, state.activityStep);
    if (ruleListsRequest) await ruleListsRequest;
    await ensureActivityStepData(state.activityStep, { render: false });
    activity = state.currentActivity;
    restoreFbuUploadJobs(activity.run_id);
    restoreFbuCalculationJob(activity.run_id);

    if (preservePage && state.currentPage === 'activities') {
      // Keep list interactions stable while background activity details are loading.
      renderActivities();
      return activity;
    }
    navigateTo(preservePage ? state.currentPage : 'workbench');
    return activity;
  } catch (error) {
    console.error('加载活动详情失败:', error);
    if (state.currentPage === 'workbench') {
      state.currentActivity = null;
      renderWorkbench();
    }
    showNotification('加载活动详情失败', 'error');
    return null;
  }
}

// ═══ New Activity ═══

el.btnNewActivity.addEventListener('click', async () => {
  const regions = state.activityRegions.length ? state.activityRegions : [DEFAULT_FBU_REGION];
  const dialogResult = await openAppDialog({
    title: '新建绩效奖金核算活动',
    message: '同月同区域可创建多个活动，创建人和时间会自动记录。',
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
    select: {
      label: '划分区域',
      value: state.currentActivity?.region_code || DEFAULT_FBU_REGION.code,
      help: '当前仅开放FBU美洲区域。',
      options: regions.map(region => ({ value: region.code, label: region.name })),
      validate: value => regions.some(region => region.code === value) || '请选择划分区域',
    },
    preview: ({ value, selectValue }) => {
      const region = regions.find(item => item.code === selectValue) || DEFAULT_FBU_REGION;
      return `活动名称：绩效奖金核算-${String(value || '').replace('-', '')}-${region.name}`;
    },
  });

  if (!dialogResult.confirmed) return;
  const calcMonth = dialogResult.value;
  const regionCode = dialogResult.selectValue;

  try {
    const data = await apiJson(`${API_BASE}/runs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ calc_month: calcMonth, region_code: regionCode }),
    });

    if (data.run_id) {
      showNotification('活动创建成功', 'success');
      const activity = applyCurrentActivityPatch(data.activity || {
        run_id: data.run_id,
        calc_month: data.calc_month,
        activity_name: data.activity_name,
        region_code: data.region_code,
        region_name: data.region_name,
        created_by_user_id: data.created_by_user_id,
        created_by_name: data.created_by_name,
        created_by_avatar_url: data.created_by_avatar_url,
        status: data.status,
        current_step: 0,
        roster_file: data.roster_file,
        roster_source: data.roster_source,
      });
      state.activityStep = 'people';
      rememberOwnedActivity(activity, state.activityStep);
      resetTableControls();
      navigateTo('workbench');
      renderWorkbench();
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
    title: '删除活动',
    message: `将删除“${getActivityDisplayName(activity)}”及其全部已导入数据。`,
    confirmText: '删除',
    cancelText: '保留',
    tone: 'danger',
  });
  if (!dialogResult.confirmed) return;

  await deleteActivitiesByIds([activityId], {
    successMessage: '已删除',
    failureMessage: '删除失败',
  });
}

async function deleteActivitiesByIds(ids, options = {}) {
  const runIds = [...new Set((ids || []).filter(Boolean))];
  if (!runIds.length) return;

  state.activities = state.activities.filter(activity => !runIds.includes(activity.run_id));
  runIds.forEach(id => {
    delete state.foundationRunDetails[id];
  });
  if (state.currentPage === 'activities') {
    renderActivities();
  }

  try {
    const data = await apiJson(`${API_BASE}/runs/bulk-delete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ run_ids: runIds }),
    });
    showNotification(options.successMessage || `已删除 ${data.deleted_count || runIds.length} 个活动`, 'success');
    await loadActivities();
  } catch (error) {
    showNotification(options.failureMessage || '删除失败', 'error');
    await loadActivities();
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

const uploadTypeLabels = {
  roster: '花名册',
  attendance: '考勤日报表',
  previousAttendance: '上月考勤',
  previousSalary: '上月薪资档案',
  currentSalary: '当月薪资档案',
  salaryAdjustments: '全量调薪流程',
  transferHistory: '人事调动记录',
  performance: '绩效报表',
  supplementalLeave: '补充假勤表',
};

function getWorkbenchUploadInput(type) {
  const map = {
    roster: el.workbenchUploadRoster,
    attendance: el.workbenchUploadAttendance,
    previousAttendance: el.workbenchUploadPreviousAttendance,
    previousSalary: el.workbenchUploadPreviousSalary,
    currentSalary: el.workbenchUploadCurrentSalary,
    salaryAdjustments: el.workbenchUploadSalaryAdjustments,
    transferHistory: el.workbenchUploadTransferHistory,
    performance: el.workbenchUploadPerformance,
    supplementalLeave: el.workbenchUploadSupplementalLeave,
  };
  return map[type] || null;
}

function openWorkbenchUpload(type) {
  const input = getWorkbenchUploadInput(type);
  if (!input) return;
  if (!state.currentActivity && type !== 'roster') {
    showNotification('请先进入一个月度活动，再上传该活动的数据文件', 'warning', { title: '缺少月度活动' });
    return;
  }
  input.value = '';
  input.click();
}

async function uploadWorkbenchRosterFile(file) {
  if (!file) return;
  if (!/\.(xlsx|xls)$/i.test(file.name)) {
    failWorkbenchUploadProgress('roster', file.name, '仅支持 .xlsx / .xls');
    return;
  }
  const formData = new FormData();
  formData.append('file', file);
  startWorkbenchUploadProgress('roster', file);
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
    finishWorkbenchUploadProgress('roster', file.name, '已更新');
  } catch (error) {
    failWorkbenchUploadProgress('roster', file.name, error.message);
  } finally {
    if (el.btnUploadRoster) {
      el.btnUploadRoster.disabled = false;
      updateRosterButton();
    }
  }
}

function isLocalFbuHost() {
  return ['', 'localhost', '127.0.0.1', '::1'].includes(window.location.hostname);
}

const LEGACY_ATTENDANCE_DIRECT_PLAN_ENDPOINT = '/attendance-direct-upload-plan';
const LEGACY_ATTENDANCE_DIRECT_COMPLETE_ENDPOINT = '/attendance-direct-upload-complete';
const FBU_UPLOAD_JOBS_STORAGE_KEY = 'sigma-fbu-active-upload-jobs-v1';
const FBU_CALCULATION_JOB_STORAGE_KEY = 'sigma-fbu-active-calculation-job-v1';
const fbuUploadJobPollers = new Set();
const fbuCalculationJobPollers = new Set();

function persistActiveFbuUploadJobs() {
  try {
    localStorage.setItem(
      FBU_UPLOAD_JOBS_STORAGE_KEY,
      JSON.stringify(state.activeFbuUploadJobs || {}),
    );
  } catch (error) {
    console.warn('保存上传任务状态失败:', error);
  }
}

function loadPersistedFbuUploadJobs() {
  try {
    const payload = JSON.parse(localStorage.getItem(FBU_UPLOAD_JOBS_STORAGE_KEY) || '{}');
    state.activeFbuUploadJobs = payload && typeof payload === 'object' ? payload : {};
  } catch (error) {
    console.warn('读取上传任务状态失败:', error);
    state.activeFbuUploadJobs = {};
  }
}

function rememberFbuUploadJob(jobId, metadata) {
  state.activeFbuUploadJobs = {
    ...state.activeFbuUploadJobs,
    [jobId]: { ...metadata, jobId },
  };
  persistActiveFbuUploadJobs();
}

function forgetFbuUploadJob(jobId) {
  const jobs = { ...state.activeFbuUploadJobs };
  delete jobs[jobId];
  state.activeFbuUploadJobs = jobs;
  persistActiveFbuUploadJobs();
}

const FBU_JOB_UI_FIELDS = [
  'status',
  'stage',
  'progress',
  'indeterminate',
  'message',
  'canRetry',
  'error',
  'fileName',
  'jobId',
];

function hasFbuJobUiStateChanged(currentState, nextState) {
  const current = currentState || {};
  const next = nextState || {};
  return FBU_JOB_UI_FIELDS.some(field => current[field] !== next[field]);
}

function updateFbuUploadJobMaterials(metadata, nextState) {
  let changed = false;
  (metadata?.entries || []).forEach(entry => {
    const currentState = state.workbenchUploadStates[entry.type] || {};
    const candidate = {
      fileName: entry.fileName,
      jobId: metadata.jobId,
      ...nextState,
    };
    if (!hasFbuJobUiStateChanged(currentState, candidate)) return;
    changed = true;
    setWorkbenchUploadState(entry.type, candidate, { render: false });
  });
  if (changed && state.currentPage === 'workbench') renderWorkbench();
}

function waitForFbuUploadPoll(delayMs = 900) {
  return new Promise(resolve => window.setTimeout(resolve, delayMs));
}

function getWorkbenchFileKey(file) {
  if (!file) return '';
  return [file.name || '', file.size || 0, file.lastModified || 0].join(':');
}

function clearMatchingPendingPreviousAttendance(entry) {
  const pendingFile = state.workbenchPreviousAttendanceFile;
  if (!pendingFile || !entry) return;
  const matches = entry.fileKey
    ? getWorkbenchFileKey(pendingFile) === entry.fileKey
    : pendingFile.name === entry.fileName
      && (!entry.fileSize || pendingFile.size === entry.fileSize);
  if (matches) state.workbenchPreviousAttendanceFile = null;
}

async function flushPendingPreviousAttendanceUpload(runId) {
  const file = state.workbenchPreviousAttendanceFile;
  if (!file || state.currentActivity?.run_id !== runId) return;
  if (!state.currentActivity.attendance_file) return;
  await uploadWorkbenchPreviousAttendanceFile(file);
}

async function completeFbuUploadJob(metadata, job) {
  if (!state.activeFbuUploadJobs[metadata.jobId]) return job;
  const entries = metadata.entries || [];
  const coreUpdates = job.result?.coreUpdates;
  const authoritativeCore = coreUpdates && typeof coreUpdates === 'object'
    ? coreUpdates
    : {};
  const activitySnapshot = state.currentActivity?.run_id === metadata.runId
    ? { ...state.currentActivity }
    : null;
  if (activitySnapshot && Object.keys(authoritativeCore).length) {
    mergeCurrentActivityPayload({
      run_id: metadata.runId,
      ...authoritativeCore,
    });
  }
  const refreshedAttendance = entries.some(entry => (
    ['attendance', 'previousAttendance'].includes(entry.type)
  ));
  const refreshedCurrentAttendance = entries.some(entry => entry.type === 'attendance');
  entries
    .filter(entry => entry.type === 'previousAttendance')
    .forEach(clearMatchingPendingPreviousAttendance);
  if (refreshedAttendance) prioritizePendingSupplementalLeave();
  updateFbuUploadJobMaterials(metadata, {
    status: 'done',
    progress: 100,
    indeterminate: false,
    message: job.result?.readyForReconciliation
      ? '已解析并完成核验'
      : '已上传并解析',
    canRetry: false,
  });
  forgetFbuUploadJob(metadata.jobId);
  if (state.currentActivity?.run_id === metadata.runId) {
    await enterActivity(metadata.runId, {
      preservePage: true,
      preserveStep: true,
      refreshSections: true,
    });
  }
  if (Object.keys(authoritativeCore).length) {
    mergeCurrentActivityPayload({
      ...(state.currentActivity?.run_id === metadata.runId
        ? state.currentActivity
        : activitySnapshot || {}),
      run_id: metadata.runId,
      ...authoritativeCore,
    });
    entries.forEach(entry => clearWorkbenchUploadState(entry.type, { render: false }));
    if (state.currentPage === 'workbench') renderWorkbench();
  }
  if (refreshedCurrentAttendance) {
    await flushPendingPreviousAttendanceUpload(metadata.runId);
  }
  return job;
}

async function pollFbuUploadJob(jobId) {
  const metadata = state.activeFbuUploadJobs[jobId];
  if (!metadata || fbuUploadJobPollers.has(jobId)) return null;
  fbuUploadJobPollers.add(jobId);
  try {
    while (state.activeFbuUploadJobs[jobId]) {
      const data = await apiJson(
        `${API_BASE}/runs/${metadata.runId}/uploads/${jobId}`,
      );
      if (!state.activeFbuUploadJobs[jobId]) return null;
      const job = data.job || {};
      if (job.status === 'completed') {
        return completeFbuUploadJob(metadata, job);
      }
      if (job.status === 'failed') {
        updateFbuUploadJobMaterials(metadata, {
          status: 'failed',
          progress: 100,
          indeterminate: false,
          message: job.error || job.message || '解析失败',
          canRetry: Boolean(job.canRetry),
        });
        return job;
      }
      if (job.recoverable) {
        updateFbuUploadJobMaterials(metadata, {
          status: 'failed',
          progress: 100,
          indeterminate: false,
          message: job.message || '处理任务已中断，可点击重试',
          canRetry: true,
        });
        return job;
      }
      updateFbuUploadJobMaterials(metadata, {
        status: 'processing',
        progress: toNumber(job.progress, 5),
        indeterminate: true,
        message: job.stage === 'queued'
          ? '正在排队'
          : job.stage === 'materializing'
            ? '正在读取已上传文件'
            : '正在解析',
        canRetry: false,
      });
      await waitForFbuUploadPoll(job.stage === 'queued' ? 700 : 1500);
    }
    return null;
  } catch (error) {
    updateFbuUploadJobMaterials(metadata, {
      status: 'processing',
      progress: 100,
      indeterminate: true,
      message: '状态确认中断，刷新页面后会继续检查',
      canRetry: false,
    });
    return null;
  } finally {
    fbuUploadJobPollers.delete(jobId);
  }
}

async function resumeFbuUploadJob(jobId) {
  const metadata = state.activeFbuUploadJobs[jobId];
  if (!metadata) return;
  updateFbuUploadJobMaterials(metadata, {
    status: 'processing',
    progress: 5,
    indeterminate: true,
    message: '正在排队',
    canRetry: false,
  });
  try {
    const resumeRequest = apiJson(
      `${API_BASE}/runs/${metadata.runId}/uploads/${jobId}/resume`,
      { method: 'POST' },
    );
    const pollingRequest = pollFbuUploadJob(jobId);
    const resumed = await resumeRequest;
    if (resumed.job?.status === 'completed') {
      return completeFbuUploadJob(metadata, resumed.job);
    }
    return pollingRequest;
  } catch (error) {
    updateFbuUploadJobMaterials(metadata, {
      status: 'failed',
      progress: 100,
      indeterminate: false,
      message: error.message || '重试失败',
      canRetry: true,
    });
  }
}

function restoreFbuUploadJobs(runId) {
  loadPersistedFbuUploadJobs();
  Object.values(state.activeFbuUploadJobs)
    .filter(job => job?.runId === runId)
    .forEach(job => {
      updateFbuUploadJobMaterials(job, {
        status: 'processing',
        progress: 100,
        indeterminate: true,
        message: '正在确认上传任务状态',
        canRetry: false,
      });
      pollFbuUploadJob(job.jobId);
    });
}

function persistActiveFbuCalculationJob() {
  try {
    if (state.activeCalculationJob?.jobId) {
      localStorage.setItem(
        FBU_CALCULATION_JOB_STORAGE_KEY,
        JSON.stringify(state.activeCalculationJob),
      );
    } else {
      localStorage.removeItem(FBU_CALCULATION_JOB_STORAGE_KEY);
    }
  } catch (error) {
    console.warn('保存核算任务状态失败:', error);
  }
}

function loadPersistedFbuCalculationJob() {
  try {
    const payload = JSON.parse(
      localStorage.getItem(FBU_CALCULATION_JOB_STORAGE_KEY) || 'null',
    );
    state.activeCalculationJob = payload?.jobId && payload?.runId ? payload : null;
  } catch (error) {
    console.warn('读取核算任务状态失败:', error);
    state.activeCalculationJob = null;
  }
}

function rememberFbuCalculationJob(runId, jobId) {
  state.activeCalculationJob = { runId, jobId };
  persistActiveFbuCalculationJob();
}

function forgetFbuCalculationJob() {
  state.activeCalculationJob = null;
  persistActiveFbuCalculationJob();
}

async function completeFbuCalculationJob(metadata, job) {
  if (state.activeCalculationJob?.jobId !== metadata.jobId) return job;
  const statusChanged = hasFbuJobUiStateChanged(state.calculationJobStatus, job);
  state.calculationJobStatus = job;
  if (statusChanged && state.currentPage === 'workbench') renderWorkbench();
  forgetFbuCalculationJob();
  if (state.currentActivity?.run_id === metadata.runId) {
    await enterActivity(metadata.runId, {
      preservePage: true,
      initialStep: 'export',
      refreshSections: true,
    });
  }
  return job;
}

async function pollFbuCalculationJob(jobId) {
  const metadata = state.activeCalculationJob;
  if (
    !metadata
    || metadata.jobId !== jobId
    || fbuCalculationJobPollers.has(jobId)
  ) {
    return null;
  }
  fbuCalculationJobPollers.add(jobId);
  try {
    while (state.activeCalculationJob?.jobId === jobId) {
      const data = await apiJson(
        `${API_BASE}/runs/${metadata.runId}/calculation-jobs/${jobId}`,
      );
      if (state.activeCalculationJob?.jobId !== jobId) return null;
      const job = data.job || {};
      const statusChanged = hasFbuJobUiStateChanged(state.calculationJobStatus, job);
      state.calculationJobStatus = job;
      if (statusChanged && state.currentPage === 'workbench') renderWorkbench();

      if (job.status === 'completed') {
        return completeFbuCalculationJob(metadata, job);
      }
      if (job.status === 'failed' || job.recoverable) {
        return job;
      }
      await waitForFbuUploadPoll(1500);
    }
    return null;
  } catch (error) {
    state.calculationJobStatus = {
      status: 'failed',
      canRetry: true,
      message: '核算状态确认中断，可点击重试继续。',
      error: error.message || '',
    };
    if (state.currentPage === 'workbench') renderWorkbench();
    return null;
  } finally {
    fbuCalculationJobPollers.delete(jobId);
  }
}

async function resumeFbuCalculationJob() {
  const metadata = state.activeCalculationJob;
  if (!metadata?.jobId || !metadata?.runId) return null;
  state.calculationJobStatus = {
    status: 'queued',
    progress: 5,
    message: '正在排队',
  };
  if (state.currentPage === 'workbench') renderWorkbench();
  try {
    const resumeRequest = apiJson(
      `${API_BASE}/runs/${metadata.runId}/calculation-jobs/${metadata.jobId}/resume`,
      { method: 'POST' },
    );
    const pollingRequest = pollFbuCalculationJob(metadata.jobId);
    const resumed = await resumeRequest;
    if (resumed.job?.status === 'completed') {
      return completeFbuCalculationJob(metadata, resumed.job);
    }
    return pollingRequest;
  } catch (error) {
    state.calculationJobStatus = {
      status: 'failed',
      canRetry: true,
      message: error.message || '核算任务重试失败',
    };
    if (state.currentPage === 'workbench') renderWorkbench();
    return null;
  }
}

function restoreFbuCalculationJob(runId) {
  loadPersistedFbuCalculationJob();
  const metadata = state.activeCalculationJob;
  if (!metadata || metadata.runId !== runId) {
    state.calculationJobStatus = null;
    return;
  }
  state.calculationJobStatus = {
    status: 'processing',
    progress: 5,
    message: '正在确认核算任务状态',
  };
  pollFbuCalculationJob(metadata.jobId);
}

function prioritizePendingSupplementalLeave() {
  state.tableFilters.supplementalLeave = { quality: 'pending' };
  getTablePagination('supplementalLeave').page = 1;
}

function uploadFbuFileToSignedUrl(upload, file, onProgress) {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open('PUT', upload.signedUrl);
    request.setRequestHeader('x-upsert', 'true');
    request.upload.onprogress = (event) => {
      if (!event.lengthComputable) return;
      onProgress(Math.min(100, Math.round((event.loaded / event.total) * 100)));
    };
    request.onload = () => {
      if (request.status >= 200 && request.status < 300) {
        onProgress(100);
        resolve();
        return;
      }
      const detail = request.responseText ? ` ${request.responseText.slice(0, 160)}` : '';
      reject(new Error(`直传文件失败（HTTP ${request.status}）${detail}`));
    };
    request.onerror = () => reject(new Error('直传文件失败，请检查网络后重试。'));
    request.ontimeout = () => reject(new Error('直传文件超时，请检查网络后重试。'));
    const body = new FormData();
    body.append('cacheControl', '3600');
    body.append('', file);
    request.send(body);
  });
}

async function uploadWorkbenchFilesDirect(entries, options = {}) {
  if (!state.currentActivity || !entries?.length) return;
  const activityId = state.currentActivity.run_id;
  entries.forEach(({ type, file }) => startWorkbenchUploadProgress(type, file));
  try {
    const plan = await apiJson(`${API_BASE}/runs/${activityId}/uploads/plan`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        files: entries.map(({ kind, file }) => ({
          kind,
          fileName: file.name,
          fileSize: file.size,
          contentType: file.type || 'application/octet-stream',
        })),
      }),
    });
    const uploads = Array.isArray(plan.uploads) ? plan.uploads : [];
    if (uploads.length !== entries.length) {
      throw new Error('上传计划与所选文件数量不一致，请重新选择文件。');
    }
    const uploadByKind = new Map(uploads.map(upload => [upload.kind, upload]));
    const directUploadStartedAt = performance.now();
    await Promise.all(entries.map(async ({ kind, type, file }) => {
      const upload = uploadByKind.get(kind);
      if (!upload?.signedUrl) {
        throw new Error(`未生成${uploadTypeLabels[type] || '文件'}直传地址。`);
      }
      await uploadFbuFileToSignedUrl(upload, file, (progress) => {
        setWorkbenchUploadState(type, {
          status: 'uploading',
          progress,
          indeterminate: false,
          message: `直传中 ${progress}%`,
        });
      });
      setWorkbenchUploadState(type, {
        status: 'processing',
        progress: 100,
        indeterminate: true,
        message: '已上传，正在排队',
      });
    }));
    const clientUploadMs = Math.max(0, Math.round(performance.now() - directUploadStartedAt));
    const jobId = plan.job?.jobId;
    if (!jobId) throw new Error('上传任务编号缺失，请重新上传。');
    const metadata = {
      jobId,
      runId: activityId,
      entries: entries.map(({ type, file }) => ({
        type,
        fileName: file.name,
        fileSize: file.size,
        fileKey: getWorkbenchFileKey(file),
      })),
    };
    rememberFbuUploadJob(jobId, metadata);
    updateFbuUploadJobMaterials(metadata, {
      status: 'processing',
      progress: 5,
      indeterminate: true,
      message: '正在排队',
      canRetry: false,
    });
    const startRequest = apiJson(`${API_BASE}/runs/${activityId}/uploads/${jobId}/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ clientUploadMs }),
    });
    const pollingRequest = pollFbuUploadJob(jobId);
    try {
      const started = await startRequest;
      if (started.job?.status === 'completed') {
        return completeFbuUploadJob(metadata, started.job);
      }
    } catch (error) {
      forgetFbuUploadJob(jobId);
      await pollingRequest;
      throw error;
    }
    return pollingRequest;
  } catch (error) {
    const directUnavailable = error.status === 409
      || /未启用 Supabase 直传|DIRECT_UPLOAD_UNAVAILABLE/i.test(error.message || '');
    if (isLocalFbuHost() && directUnavailable && typeof options.fallback === 'function') {
      return options.fallback();
    }
    entries.forEach(({ type, file }) => failWorkbenchUploadProgress(type, file.name, error.message));
  }
}

async function uploadWorkbenchAttendanceFilesDirect(attendanceFile, previousAttendanceFile) {
  if (!state.currentActivity || (!attendanceFile && !previousAttendanceFile)) return;
  const entries = [
    attendanceFile ? { kind: 'attendance', type: 'attendance', file: attendanceFile } : null,
    previousAttendanceFile ? { kind: 'previousAttendance', type: 'previousAttendance', file: previousAttendanceFile } : null,
  ].filter(Boolean);
  return uploadWorkbenchFilesDirect(entries, {
    fallback: () => attendanceFile
      ? uploadWorkbenchFileMultipart('attendance', attendanceFile)
      : uploadWorkbenchPreviousAttendanceFileMultipart(previousAttendanceFile),
  });
}

async function uploadWorkbenchFile(type, file) {
  if (type === 'attendance') {
    return uploadWorkbenchAttendanceFilesDirect(file, state.workbenchPreviousAttendanceFile);
  }
  return uploadWorkbenchFilesDirect(
    [{ kind: type, type, file }],
    { fallback: () => uploadWorkbenchFileMultipart(type, file) },
  );
}

async function uploadWorkbenchFileMultipart(type, file) {
  if (!file || !state.currentActivity) return;
  if (!/\.(xlsx|xls)$/i.test(file.name)) {
    failWorkbenchUploadProgress(type, file.name, '仅支持 .xlsx / .xls');
    return;
  }

  const formData = new FormData();
  formData.append('file', file);
  let endpoint = '';
  const previousAttendanceFile = state.workbenchPreviousAttendanceFile;

  if (type === 'attendance') {
    formData.append('calc_month', state.currentActivity.calc_month);
    formData.append('run_id', state.currentActivity.run_id);
    if (previousAttendanceFile) {
      formData.append('previous_attendance', previousAttendanceFile);
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
  } else if (type === 'transferHistory') {
    formData.append('run_id', state.currentActivity.run_id);
    endpoint = `${API_BASE}/import-transfer-history`;
  } else if (type === 'supplementalLeave') {
    formData.append('run_id', state.currentActivity.run_id);
    endpoint = `${API_BASE}/import-supplemental-leave`;
  }

  if (!endpoint) return;

  try {
    const activityId = state.currentActivity.run_id;
    startWorkbenchUploadProgress(type, file);
    const data = await apiJson(endpoint, {
      method: 'POST',
      body: formData,
    });

    if (!data.success) {
      failWorkbenchUploadProgress(type, file.name, data.detail || '上传失败');
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
      clearMatchingPendingPreviousAttendance(previousAttendanceFile ? {
        fileName: previousAttendanceFile.name,
        fileSize: previousAttendanceFile.size,
        fileKey: getWorkbenchFileKey(previousAttendanceFile),
      } : null);
      prioritizePendingSupplementalLeave();
      if (previousAttendanceFile) {
        finishWorkbenchUploadProgress('previousAttendance', previousAttendanceFile.name, '已随考勤纳入', { render: false });
      }
    } else if (type === 'salary') {
      state.salaryData = data.preview;
    } else if (type === 'performance') {
      state.performanceData = data.preview;
    } else if (type === 'adjustments') {
      state.adjustmentData = data.preview;
    } else if (type === 'supplementalLeave') {
      state.supplementalLeaveData = data.preview;
    }

    const activityPatch = { run_id: activityId };
    if (type === 'attendance') Object.assign(activityPatch, { attendance_file: file.name, attendance_data: data.preview, current_step: 1, status: 'step1' });
    if (type === 'salary') Object.assign(activityPatch, { salary_file: file.name, salary_data: data.preview, current_step: 2, status: 'step2' });
    if (type === 'performance') Object.assign(activityPatch, { performance_file: file.name, performance_data: data.preview, current_step: 3, status: 'step3' });
    if (type === 'adjustments') Object.assign(activityPatch, { adjustment_file: file.name, adjustment_data: data.preview });
    if (type === 'supplementalLeave') Object.assign(activityPatch, { supplemental_leave_file: file.name, supplemental_leave_data: data.preview });
    applyCurrentActivityPatch(activityPatch, { invalidateResults: true });
    finishWorkbenchUploadProgress(type, file.name, '已解析');
    if (type === 'attendance') {
      await flushPendingPreviousAttendanceUpload(activityId);
    }
  } catch (error) {
    failWorkbenchUploadProgress(type, file.name, error.message);
  }
}

async function uploadWorkbenchSalaryHistoryMaterialMultipart(type, file) {
  if (!state.currentActivity || !file) return;
  const activityId = state.currentActivity.run_id;
  const formData = new FormData();
  formData.append('run_id', activityId);
  formData.append('material_type', type);
  formData.append('file', file);
  startWorkbenchUploadProgress(type, file);
  try {
    const data = await apiJson(`${API_BASE}/import-salary-history-material`, {
      method: 'POST',
      body: formData,
    });
    if (!data.success) {
      failWorkbenchUploadProgress(type, file.name, data.detail || '上传失败');
      return;
    }

    const missingLabels = (data.missing_materials || [])
      .map(materialType => uploadTypeLabels[materialType] || materialType);
    if (data.ready_for_reconciliation) {
      state.salaryData = data.preview;
      const completedFileNames = {
        previousSalary: state.currentActivity?.previous_salary_file,
        currentSalary: state.currentActivity?.salary_file,
        salaryAdjustments: state.currentActivity?.adjustment_file,
        [type]: file.name,
      };
      Object.keys(SALARY_HISTORY_MATERIAL_FIELDS).forEach(materialType => {
        finishWorkbenchUploadProgress(
          materialType,
          completedFileNames[materialType] || '',
          '已核验',
        );
      });
    } else {
      finishWorkbenchUploadProgress(
        type,
        file.name,
        missingLabels.length ? `已上传，待补：${missingLabels.join('、')}` : '已上传并解析',
      );
    }
    state.lastImportResult = {
      type,
      hasResultFile: Boolean(data.result_file),
      filename: file.name,
      summary: data.verification?.summary || data.material_preview?.summary || {},
      at: new Date().toLocaleTimeString('zh-CN', { hour12: false }),
    };
    const refreshedActivity = await enterActivity(activityId, {
      preservePage: true,
      preserveStep: true,
      refreshSections: true,
    });
    if (!refreshedActivity) {
      throw new Error('文件已上传，但活动详情刷新失败，请重新进入活动后确认');
    }
    renderWorkbenchCurrentStep();
  } catch (error) {
    failWorkbenchUploadProgress(type, file.name, error.message);
  }
}

async function uploadWorkbenchSalaryHistoryMaterial(type, file) {
  if (!state.currentActivity || !file) return;
  return uploadWorkbenchFilesDirect(
    [{ kind: type, type, file }],
    { fallback: () => uploadWorkbenchSalaryHistoryMaterialMultipart(type, file) },
  );
}

function renderSalaryVerificationButton(employeeId, choice, label, tone = 'secondary', title = '') {
  const isPending = state.salaryVerificationPendingIds.has(String(employeeId || ''));
  return `
    <button class="btn btn-sm btn-${escapeHtml(tone)}"
            type="button"
            ${title ? `title="${escapeHtml(title)}"` : ''}
            ${isPending ? 'disabled aria-busy="true"' : ''}
            onclick="confirmSalaryVerification(${formatJsArg(employeeId)}, ${formatJsArg(choice)})">
      ${isPending ? '处理中…' : escapeHtml(label)}
    </button>
  `;
}

function findSalaryVerificationRowElement(employeeId) {
  return [...document.querySelectorAll('#salaryVerificationReview tr[data-employee-id]')]
    .find(row => row.dataset.employeeId === String(employeeId)) || null;
}

function setSalaryVerificationRowSaving(employeeId, isSaving) {
  const row = findSalaryVerificationRowElement(employeeId);
  if (!row) return;
  row.classList.toggle('is-saving', Boolean(isSaving));
  row.querySelectorAll('button').forEach(button => {
    if (isSaving) {
      button.dataset.originalText = button.textContent;
      button.textContent = '确认中…';
    } else if (button.dataset.originalText) {
      button.textContent = button.dataset.originalText;
      delete button.dataset.originalText;
    }
    button.disabled = Boolean(isSaving);
  });
}

function replaceSalaryStepSection(elementId, markup) {
  const element = document.getElementById(elementId);
  if (!element) return;
  if (!markup) {
    element.remove();
    return;
  }
  element.outerHTML = markup;
}

function refreshSalaryVerificationSections(activity) {
  replaceSalaryStepSection('salaryNeedsPanel', renderNeedsPanel('salary', activity));
  replaceSalaryStepSection('salaryVerificationReview', renderSalaryVerificationReview(activity));
}

function applySalaryVerificationCompactResult(activity, employeeId, data) {
  if (data.preview && data.verification) {
    return applyCurrentActivityPatch({
      run_id: activity.run_id,
      salary_data: data.preview,
      salary_verification_data: data.verification,
      status: 'step2',
    }, { invalidateResults: true });
  }

  const replaceEmployee = row => row.employee_id === employeeId ? data.employee : row;
  const verification = {
    ...(activity.salary_verification_data || {}),
    employees: (activity.salary_verification_data?.employees || []).map(replaceEmployee),
    issues: (activity.salary_verification_data?.issues || []).filter(issue => issue.employee_id !== employeeId),
    summary: data.verification_summary || activity.salary_verification_data?.summary || {},
  };
  const salaryData = {
    ...(activity.salary_data || {}),
    employees: (activity.salary_data?.employees || []).map(replaceEmployee),
    summary: data.salary_summary || activity.salary_data?.summary || {},
  };
  return applyCurrentActivityPatch({
    run_id: activity.run_id,
    salary_data: salaryData,
    salary_verification_data: verification,
    status: 'step2',
  }, { invalidateResults: true });
}

function applySalaryVerificationBatchResult(activity, data) {
  const employees = (data.employees || []).filter(Boolean);
  if (!employees.length) return activity;
  const employeeById = new Map(employees.map(row => [String(row.employee_id), row]));
  const replaceEmployee = row => employeeById.get(String(row.employee_id)) || row;
  const updatedIds = new Set(employeeById.keys());
  const verification = {
    ...(activity.salary_verification_data || {}),
    employees: (activity.salary_verification_data?.employees || []).map(replaceEmployee),
    issues: (activity.salary_verification_data?.issues || [])
      .filter(issue => !updatedIds.has(String(issue.employee_id))),
    summary: data.verification_summary || activity.salary_verification_data?.summary || {},
  };
  const salaryData = {
    ...(activity.salary_data || {}),
    employees: (activity.salary_data?.employees || []).map(replaceEmployee),
    summary: data.salary_summary || activity.salary_data?.summary || {},
  };
  return applyCurrentActivityPatch({
    run_id: activity.run_id,
    salary_data: salaryData,
    salary_verification_data: verification,
    status: 'step2',
  }, { invalidateResults: true });
}

async function confirmSalaryVerification(employeeId, choice) {
  const activity = getWorkbenchActivity();
  const normalizedId = String(employeeId);
  if (!activity?.run_id || state.salaryVerificationPendingIds.has(normalizedId)) return;
  state.salaryVerificationPendingIds.add(normalizedId);
  state.salaryVerificationQueue.push({ employee_id: employeeId, choice });
  setSalaryVerificationRowSaving(employeeId, true);
  scheduleSalaryVerificationFlush();
}

function scheduleSalaryVerificationFlush() {
  if (state.salaryVerificationFlushTimer || state.salaryVerificationFlushing) return;
  state.salaryVerificationFlushTimer = window.setTimeout(() => {
    state.salaryVerificationFlushTimer = null;
    flushSalaryVerificationQueue();
  }, 300);
}

async function flushSalaryVerificationQueue() {
  if (state.salaryVerificationFlushing || !state.salaryVerificationQueue.length) return;
  const activity = getWorkbenchActivity();
  if (!activity?.run_id) return;

  state.salaryVerificationFlushing = true;
  const confirmations = state.salaryVerificationQueue.splice(0);
  const employeeIds = confirmations.map(item => String(item.employee_id));
  try {
    const data = await apiJson(
      `${API_BASE}/runs/${activity.run_id}/salary-verification/confirm`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirmations, response_mode: 'employees' }),
      },
    );
    const updated = applySalaryVerificationBatchResult(getWorkbenchActivity() || activity, data);
    employeeIds.forEach(employeeId => state.salaryVerificationPendingIds.delete(employeeId));
    refreshSalaryVerificationSections(updated);
  } catch (error) {
    employeeIds.forEach(employeeId => {
      state.salaryVerificationPendingIds.delete(employeeId);
      setSalaryVerificationRowSaving(employeeId, false);
    });
    state.inlineActionNotes.salary = `薪资差异确认失败：${error.message}`;
    showNotification(error.message, 'error', { title: '薪资差异确认失败' });
  } finally {
    state.salaryVerificationFlushing = false;
    if (state.salaryVerificationQueue.length) scheduleSalaryVerificationFlush();
  }
}

async function uploadWorkbenchPreviousAttendanceFile(file) {
  if (!file || !state.currentActivity?.attendance_file) return;
  if (!/\.(xlsx|xls)$/i.test(file.name)) {
    failWorkbenchUploadProgress('previousAttendance', file.name, '仅支持 .xlsx / .xls');
    return;
  }

  return uploadWorkbenchAttendanceFilesDirect(null, file);
}

async function uploadWorkbenchPreviousAttendanceFileMultipart(file) {
  if (!file || !state.currentActivity?.attendance_file) return;

  const formData = new FormData();
  formData.append('calc_month', state.currentActivity.calc_month);
  formData.append('run_id', state.currentActivity.run_id);
  formData.append('previous_attendance', file);

  try {
    startWorkbenchUploadProgress('previousAttendance', file);
    const data = await apiJson(`${API_BASE}/import-attendance`, {
      method: 'POST',
      body: formData,
    });
    if (!data.success) {
      failWorkbenchUploadProgress('previousAttendance', file.name, data.detail || '上传失败');
      return;
    }
    applyCurrentActivityPatch({
      run_id: state.currentActivity.run_id,
      previous_attendance_file: file.name,
      attendance_data: data.preview,
      current_step: 1,
      status: 'step1',
    }, { invalidateResults: true });
    clearMatchingPendingPreviousAttendance({
      fileName: file.name,
      fileSize: file.size,
      fileKey: getWorkbenchFileKey(file),
    });
    prioritizePendingSupplementalLeave();
    finishWorkbenchUploadProgress('previousAttendance', file.name, '已随考勤纳入');
  } catch (error) {
    failWorkbenchUploadProgress('previousAttendance', file.name, error.message);
  }
}

function handleWorkbenchUploadChange(type, event) {
  const file = event.target.files?.[0];
  if (!file) return;
  if (['previousSalary', 'currentSalary', 'salaryAdjustments'].includes(type)) {
    if (!/\.(xlsx|xls)$/i.test(file.name)) {
      failWorkbenchUploadProgress(type, file.name, '仅支持 .xlsx / .xls');
      return;
    }
    uploadWorkbenchSalaryHistoryMaterial(type, file);
    return;
  }
  if (type === 'previousAttendance') {
    if (!/\.(xlsx|xls)$/i.test(file.name)) {
      failWorkbenchUploadProgress(type, file.name, '仅支持 .xlsx / .xls');
      return;
    }
    state.workbenchPreviousAttendanceFile = file;
    if (state.currentActivity?.attendance_file) {
      uploadWorkbenchPreviousAttendanceFile(file);
      return;
    }
    setWorkbenchUploadState(type, {
      fileName: file.name,
      fileSize: file.size,
      status: 'selected',
      progress: 100,
      message: '等待当月考勤完成后自动上传',
    });
    renderWorkbenchCurrentStep();
    return;
  }
  if (type === 'roster') {
    uploadWorkbenchRosterFile(file);
    return;
  }
  uploadWorkbenchFile(type, file);
}

function clearWorkbenchUpload(type) {
  clearWorkbenchUploadState(type);
}

function setWorkbenchTaskFilter(filter) {
  state.workbenchTaskFilter = filter || 'open';
  renderWorkbenchCurrentStep();
}

function setWorkbenchResultFilter(filter) {
  state.workbenchResultFilter = filter || 'all';
  renderWorkbenchCurrentStep();
}

function getWorkbenchStepSearch(type) {
  return String(state.workbenchStepSearch?.[type] || '');
}

function setWorkbenchStepSearch(type, value = '') {
  const focusSnapshot = captureInputFocus();
  state.workbenchStepSearch = {
    ...state.workbenchStepSearch,
    [type]: value || '',
  };
  window.clearTimeout(filterTimers[`workbench:${type}`]);
  if (type === 'finalResults') {
    ['resultsWarehouse', 'resultsFunctional', 'resultsDistrict'].forEach(paginationKey => {
      getTablePagination(paginationKey).page = 1;
    });
    renderWorkbench();
    restoreInputFocus(focusSnapshot);
    loadFinalResultsPage({ page: 1 });
    return;
  } else {
    getTablePagination(type).page = 1;
  }
  renderWorkbenchCurrentStep();
  restoreInputFocus(focusSnapshot);
}

function queueWorkbenchStepSearch(type, input) {
  window.clearTimeout(filterTimers[`workbench:${type}`]);
  filterTimers[`workbench:${type}`] = window.setTimeout(() => {
    setWorkbenchStepSearch(type, input.value);
  }, 260);
}

function handleWorkbenchStepSearchInput(event, type) {
  const input = event?.target;
  if (!(input instanceof HTMLInputElement)) return;
  state.workbenchStepSearch = {
    ...state.workbenchStepSearch,
    [type]: input.value || '',
  };
  if (event?.isComposing || composingFilterInputs.has(input)) return;
  queueWorkbenchStepSearch(type, input);
}

function handleWorkbenchStepSearchCompositionStart(event, type) {
  const input = event?.target;
  if (!(input instanceof HTMLInputElement)) return;
  composingFilterInputs.add(input);
  window.clearTimeout(filterTimers[`workbench:${type}`]);
}

function handleWorkbenchStepSearchCompositionEnd(event, type) {
  const input = event?.target;
  if (!(input instanceof HTMLInputElement)) return;
  composingFilterInputs.delete(input);
  state.workbenchStepSearch = {
    ...state.workbenchStepSearch,
    [type]: input.value || '',
  };
  queueWorkbenchStepSearch(type, input);
}

function handleWorkbenchStepSearchKeydown(event, type) {
  if (event.key === 'Enter' && !event.isComposing) {
    event.preventDefault();
    window.clearTimeout(filterTimers[`workbench:${type}`]);
    setWorkbenchStepSearch(type, event.currentTarget.value);
  } else if (event.key === 'Escape') {
    event.preventDefault();
    clearWorkbenchStepSearch(type);
  }
}

function clearWorkbenchStepSearch(type) {
  window.clearTimeout(filterTimers[`workbench:${type}`]);
  setWorkbenchStepSearch(type, '');
}

function setCheckTab(tab = 'base') {
  state.checkTab = tab === 'issues' ? 'issues' : 'base';
  renderWorkbenchCurrentStep();
}

function toggleWorkbenchResultDetail(employeeId) {
  state.workbenchSelectedResult = state.workbenchSelectedResult === employeeId ? '' : employeeId;
  renderWorkbenchCurrentStep();
}

function updateWorkbenchSupplementDraft() {
  state.workbenchSupplementDraft = {
    employeeId: document.getElementById('workbenchSupplementEmployeeId')?.value || '',
    name: document.getElementById('workbenchSupplementName')?.value || '',
    coefficient: document.getElementById('workbenchSupplementCoefficient')?.value || '',
    note: document.getElementById('workbenchSupplementNote')?.value || '',
  };
}

function applyPerformanceSupplementCompactResult(activity, employeeId, data) {
  if (data.preview) {
    return applyCurrentActivityPatch({
      run_id: activity.run_id,
      performance_file: activity.performance_file || '页面绩效补录',
      performance_data: data.preview,
      status: 'step3',
    }, { invalidateResults: true });
  }
  const existingRows = activity.performance_data?.employees || [];
  const hasEmployee = existingRows.some(row => row.employee_id === employeeId);
  const employees = hasEmployee
    ? existingRows.map(row => row.employee_id === employeeId ? data.employee : row)
    : [...existingRows, data.employee];
  return applyCurrentActivityPatch({
    run_id: activity.run_id,
    performance_file: activity.performance_file || '页面绩效补录',
    performance_data: {
      ...(activity.performance_data || {}),
      employees,
      summary: data.summary || activity.performance_data?.summary || {},
    },
    status: 'step3',
  }, { invalidateResults: true });
}

async function saveWorkbenchPerformanceSupplement() {
  const activity = getWorkbenchActivity();
  if (!activity) return;
  const employeeIdInput = document.getElementById('workbenchSupplementEmployeeId');
  const employeeId = employeeIdInput?.value.trim() || '';
  const name = document.getElementById('workbenchSupplementName')?.value.trim() || '';
  const coefficientInput = document.getElementById('workbenchSupplementCoefficient');
  const coefficient = coefficientInput?.value.trim() || '';
  const note = document.getElementById('workbenchSupplementNote')?.value.trim() || '工作台内联补录';
  const button = document.getElementById('btnWorkbenchSaveSupplement');

  if (!employeeId) {
    showNotification('请填写工号', 'warning', { title: '无法保存' });
    employeeIdInput?.focus();
    return;
  }
  if (!coefficient) {
    showNotification('请填写绩效系数', 'warning', { title: '无法保存' });
    coefficientInput?.focus();
    return;
  }

  if (button) {
    button.disabled = true;
    button.textContent = '保存中';
  }

  try {
    const data = await apiJson(`${API_BASE}/runs/${encodeURIComponent(activity.run_id)}/performance-supplement`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        employee_id: employeeId,
        name,
        score: '',
        level: '',
        coefficient,
        note,
        response_mode: 'employee',
      }),
    });

    applyPerformanceSupplementCompactResult(activity, employeeId, data);
    state.workbenchSupplementDraft = { employeeId: '', name: '', coefficient: '', note: '' };
    renderWorkbenchCurrentStep();
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
  renderWorkbenchCurrentStep();
}

function locateWorkbenchSupplementalRow(rowId) {
  setActivityStep('attendance');
  requestAnimationFrame(() => {
    findSupplementalLeaveRowElement(rowId)?.scrollIntoView({ block: 'center', behavior: 'smooth' });
  });
}

// ═══ Upload Buttons ═══
el.workbenchUploadRoster?.addEventListener('change', event => handleWorkbenchUploadChange('roster', event));
el.workbenchUploadAttendance?.addEventListener('change', event => handleWorkbenchUploadChange('attendance', event));
el.workbenchUploadPreviousAttendance?.addEventListener('change', event => handleWorkbenchUploadChange('previousAttendance', event));
el.workbenchUploadPreviousSalary?.addEventListener('change', event => handleWorkbenchUploadChange('previousSalary', event));
el.workbenchUploadCurrentSalary?.addEventListener('change', event => handleWorkbenchUploadChange('currentSalary', event));
el.workbenchUploadSalaryAdjustments?.addEventListener('change', event => handleWorkbenchUploadChange('salaryAdjustments', event));
el.workbenchUploadTransferHistory?.addEventListener('change', event => handleWorkbenchUploadChange('transferHistory', event));
el.workbenchUploadPerformance?.addEventListener('change', event => handleWorkbenchUploadChange('performance', event));
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
        <button class="btn btn-secondary btn-sm" onclick="exportData('diagnostics')">导出检查结果</button>
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
      <span><strong>${typeLabel}</strong> 已上传并刷新预览${last.hasResultFile ? '，结果文件已生成' : ''}</span>
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
        <strong>96工时制跨月关联</strong>
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
        <button class="btn btn-primary" onclick="openWorkbenchUpload('attendance')">上传考勤日报表</button>
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
        <p class="empty-state-sub">上传相邻两月薪资档案和全量调薪流程，核验时薪与绩效比例生效日期</p>
        <button class="btn btn-primary" onclick="openWorkbenchUpload('previousSalary')">开始上传</button>
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
        { label: '字段变化', value: summary.changed_count ?? 0, mono: true, tone: summary.changed_count ? 'warning' : '' },
        { label: '已核验', value: summary.resolved_count ?? summary.total_employees, mono: true, tone: 'success' },
        { label: '待处理', value: summary.blocking_count ?? 0, mono: true, tone: summary.blocking_count ? 'danger' : '' },
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
      <table class="data-table salary-activity-table" id="salaryTable">
        <thead>
          <tr>
            <th>工号</th>
            <th>姓名</th>
            <th>部门全称</th>
            <th>岗位</th>
            <th>人员状态</th>
            <th>划分区域</th>
            <th>成本归属</th>
            <th>时薪</th>
            <th>绩效比例</th>
            <th>固定绩效基数</th>
            <th>导入状态</th>
            <th>历史核验</th>
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
              <td><span class="wrap-cell">${escapeHtml(emp.name || '-')}</span></td>
              <td><span class="wrap-cell">${escapeHtml(emp.department || '-')}</span></td>
              <td><span class="wrap-cell">${escapeHtml(emp.position || '-')}</span></td>
              <td>${escapeHtml(emp.personnel_status || '-')}</td>
              <td>${escapeHtml(emp.area || '-')}</td>
              <td><span class="wrap-cell">${escapeHtml(emp.cost_owner || '-')}</span></td>
              <td>${formatCurrency(emp.hourly_rate)}</td>
              <td>${formatPercent(emp.ratio)}</td>
              <td>${toNumber(emp.fixed_performance_base) > 0 ? formatCurrency(emp.fixed_performance_base) : '-'}</td>
              <td>${renderSalaryQualityStatus(emp)}</td>
              <td>${emp.verification_status === 'blocking'
                ? `<div class="table-actions">${renderSalaryVerificationButton(emp.employee_id, 'previous', '按上月')}${renderSalaryVerificationButton(emp.employee_id, 'current', '按当月', 'primary')}</div>`
                : escapeHtml(emp.resolution || '已核验')}</td>
            </tr>
          `).join('') : renderEmptyTableRow(12, '没有匹配的薪资记录')}
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
          <button class="btn btn-secondary" onclick="setActivityStep('performance')">填写补录</button>
          <button class="btn btn-primary" onclick="openWorkbenchUpload('performance')">上传绩效报表</button>
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
  if (status === 'excluded') return '<span class="status-dot-badge danger"><i></i>已排除</span>';
  if (status === 'confirmed' && includeInBase) return '<span class="status-dot-badge success"><i></i>确认计入</span>';
  if (status === 'confirmed') return '<span class="status-dot-badge neutral"><i></i>已确认</span>';
  return '<span class="status-dot-badge warning"><i></i>待确认</span>';
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

const supplementalLeaveQualityOptions = [
  ['all', '全部'],
  ['pending', '待确认'],
  ['include', '确认计入'],
  ['excluded', '已排除'],
  ['termination', '离职结算'],
];

function getSupplementalLeaveQualityCount(rows, key) {
  if (key === 'all') return rows.length;
  return rows.filter(row => matchesQualityFilter('supplementalLeave', row, key)).length;
}

function renderSupplementalLeaveFilterBar(rows, filteredRows) {
  const filters = getTableFilter('supplementalLeave');
  const quality = String(filters.quality || 'all');
  return `
    <div class="supplemental-filter-bar">
      <label class="supplemental-filter-input" for="filterLeaveId">
        <span>工号</span>
        <input type="text" id="filterLeaveId" value="${escapeHtml(filters.id || '')}" placeholder="zt0000000" oninput="queueFilter('filterSupplementalLeaveData', event)">
      </label>
      <label class="supplemental-filter-input" for="filterLeaveName">
        <span>姓名</span>
        <input type="text" id="filterLeaveName" value="${escapeHtml(filters.name || '')}" placeholder="员工姓名" oninput="queueFilter('filterSupplementalLeaveData', event)">
      </label>
      <input type="hidden" id="filterLeaveQuality" value="${escapeHtml(quality)}">
      <div class="supplemental-filter-segments" aria-label="处理状态">
        ${supplementalLeaveQualityOptions.map(([key, label]) => `
          <button class="${quality === key ? 'active' : ''}" type="button" onclick="setSupplementalLeaveQuality(${formatJsArg(key)})">
            ${escapeHtml(label)} <span>${getSupplementalLeaveQualityCount(rows, key)}</span>
          </button>
        `).join('')}
      </div>
      <div class="supplemental-filter-actions">
        <span>显示 ${filteredRows.length}/${rows.length}</span>
        <button class="btn btn-secondary btn-sm" type="button" onclick="resetSupplementalLeaveFilter()">重置</button>
      </div>
    </div>
  `;
}

function renderSupplementalLeaveBulkBar(calcMonth = '') {
  return `
    <div class="supplemental-bulk-bar">
      <label class="bulk-check">
        <input type="checkbox" id="supplementalLeaveCheckAll" onchange="toggleSupplementalLeavePageSelection(this.checked)">
        <span>本页全选</span>
      </label>
      <input type="hidden" id="bulkLeaveStatus" value="">
      <input type="hidden" id="bulkLeaveInclude" value="">
      <div class="supplemental-bulk-presets" data-bulk-field="bulkLeaveStatus">
        <span>批量</span>
        <button type="button" onclick="setSupplementalBulkPreset('confirmed', 'true', this)">确认计入</button>
        <button type="button" onclick="setSupplementalBulkPreset('excluded', 'false', this)">排除</button>
        <button type="button" onclick="setSupplementalBulkPreset('pending', '', this)">退回待确认</button>
      </div>
      <label class="supplemental-bulk-input" for="bulkLeaveMonth">
        <span>月份</span>
        <input id="bulkLeaveMonth" type="text" value="" placeholder="${escapeHtml(calcMonth || 'YYYY-MM')}" aria-label="归属月份">
      </label>
      <label class="supplemental-bulk-input" for="bulkLeavePeriod">
        <span>周期</span>
        <input id="bulkLeavePeriod" type="text" value="" placeholder="如 4.1-4.11" aria-label="归属周期">
      </label>
      <label class="supplemental-bulk-input hours" for="bulkLeaveHours">
        <span>小时</span>
        <input id="bulkLeaveHours" type="number" min="0" step="0.01" placeholder="计入小时" aria-label="批量计入小时">
      </label>
      <label class="supplemental-bulk-input note" for="bulkLeaveNote">
        <span>备注</span>
        <input id="bulkLeaveNote" type="text" placeholder="例如：已在3月计入" aria-label="备注">
      </label>
      <button class="btn btn-primary btn-sm" type="button" onclick="applySupplementalLeaveBatchFromToolbar()">批量填充</button>
    </div>
  `;
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
      ${renderSupplementalLeaveFilterBar(rows, filteredRows)}
      ${renderSupplementalLeaveBulkBar(calcMonth)}
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

function getSupplementalLeaveActionActivity() {
  const activity = getWorkbenchActivity();
  if (activity?.run_id) return activity;
  showNotification('当前活动尚未加载完成，请重新进入活动后再试', 'warning');
  return null;
}

function applySupplementalLeavePreview(activity, preview) {
  const updatedActivity = {
    ...activity,
    supplemental_leave_data: preview,
  };
  state.supplementalLeaveData = preview;
  state.currentActivity = updatedActivity;
  state.activities = state.activities.map(item => (
    item.run_id === updatedActivity.run_id ? updatedActivity : item
  ));
  state.foundationRunDetails[updatedActivity.run_id] = updatedActivity;
}

function updateSupplementalLeaveSummary(summary = state.supplementalLeaveData?.summary || {}) {
  document.querySelectorAll(
    '.leave-summary-compact [data-summary-key], .supplemental-title-hours[data-summary-key]',
  ).forEach(item => {
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

function summarizeSupplementalLeaveRows(rows, previousSummary = {}) {
  const includeRows = rows.filter(row => row.include_in_base);
  return {
    ...previousSummary,
    total_rows: rows.length,
    include_count: includeRows.length,
    include_hours: includeRows.reduce((total, row) => total + getSupplementalIncludedHours(row), 0),
    pending_count: rows.filter(row => row.confirmation_status === 'pending').length,
    confirmed_count: rows.filter(row => row.confirmation_status === 'confirmed').length,
    excluded_count: rows.filter(row => row.confirmation_status === 'excluded').length,
  };
}

function applyOptimisticSupplementalLeaveRow(rowId, includedHours) {
  const data = state.supplementalLeaveData;
  const rowIndex = (data?.rows || []).findIndex(row => row.row_id === rowId);
  if (!data || rowIndex < 0) return null;

  const snapshot = {
    row: { ...data.rows[rowIndex] },
    summary: { ...(data.summary || {}) },
  };
  data.rows[rowIndex] = {
    ...data.rows[rowIndex],
    included_hours: includedHours,
    confirmation_status: includedHours > 0 ? 'confirmed' : 'excluded',
    include_in_base: includedHours > 0,
  };
  data.summary = summarizeSupplementalLeaveRows(data.rows, data.summary);
  updateSupplementalLeaveRowInPlace(rowId);
  setSupplementalLeaveRowSaving(rowId, true);
  return snapshot;
}

function rollbackOptimisticSupplementalLeaveRow(rowId, snapshot) {
  const data = state.supplementalLeaveData;
  const rowIndex = (data?.rows || []).findIndex(row => row.row_id === rowId);
  if (!data || rowIndex < 0 || !snapshot) return;
  data.rows[rowIndex] = snapshot.row;
  data.summary = snapshot.summary;
  updateSupplementalLeaveRowInPlace(rowId);
}

function applySupplementalLeaveCompactResult(activity, rowId, data) {
  if (data.preview) {
    applySupplementalLeavePreview(activity, data.preview);
    return updateSupplementalLeaveRowInPlace(rowId);
  }
  if (!data.row || !data.summary) return false;

  const preview = state.supplementalLeaveData;
  const rowIndex = (preview?.rows || []).findIndex(row => row.row_id === rowId);
  if (!preview || rowIndex < 0) return false;
  preview.rows[rowIndex] = data.row;
  preview.summary = data.summary;
  applyCurrentActivityPatch(
    { run_id: activity.run_id, supplemental_leave_data: preview },
    { invalidateResults: true },
  );
  return updateSupplementalLeaveRowInPlace(rowId);
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
  const activity = getSupplementalLeaveActionActivity();
  if (!activity) return;
  if (!rowIds.length) {
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
    const data = await apiJson(`${API_BASE}/runs/${activity.run_id}/supplemental-leave/batch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    applySupplementalLeavePreview(activity, data.preview);
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
  const activity = getSupplementalLeaveActionActivity();
  if (!activity) return;
  const suggestionRows = getSupplementalSuggestionRows();
  if (!suggestionRows.length) {
    showNotification('当前没有可应用的建议计入行', 'warning');
    return;
  }
  const anchorRowId = suggestionRows.find(row => findSupplementalLeaveRowElement(row.row_id))?.row_id
    || suggestionRows[0]?.row_id
    || '';

  try {
    const data = await apiJson(`${API_BASE}/runs/${activity.run_id}/supplemental-leave/batch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apply_suggestions: true }),
    });
    applySupplementalLeavePreview(activity, data.preview);
    renderSupplementalLeaveDataPreservingScroll(anchorRowId);
    showNotification(`已应用 ${data.applied_count || suggestionRows.length} 条建议计入`, 'success');
  } catch (error) {
    showNotification(error.message, 'error', { title: '应用建议失败' });
  }
}

async function updateSupplementalLeaveRow(rowId, explicitHours) {
  const activity = getWorkbenchActivity();
  if (!rowId || !activity?.run_id) {
    showNotification('当前活动尚未加载完成，请重新进入活动后再试', 'warning');
    return;
  }
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
    response_mode: 'row',
  };
  const anchorRowId = getSupplementalLeaveContinuationAnchor(rowId);
  const optimisticSnapshot = applyOptimisticSupplementalLeaveRow(rowId, includedHours);

  try {
    const data = await apiJson(`${API_BASE}/runs/${activity.run_id}/supplemental-leave/batch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (applySupplementalLeaveCompactResult(activity, rowId, data)) {
      restoreScrollPosition(scrollX, scrollY);
    } else {
      renderSupplementalLeaveDataPreservingScroll(anchorRowId, { focusInput: true });
    }
    showNotification(includedHours > 0 ? '已确认计入' : '已排除', 'success');
  } catch (error) {
    rollbackOptimisticSupplementalLeaveRow(rowId, optimisticSnapshot);
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
              <th class="amount-cell">最终奖金</th>
              <th>操作</th>
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
  const expanded = state.workbenchSelectedResult === employeeId;

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
      <td>${escapeHtml(getDisplayPosition(result, getWorkbenchActivity()))}</td>
      <td class="amount-cell">${formatCurrency(result.hourly_rate)}</td>
      <td class="amount-cell">${formatCurrency(result.performance_base)}</td>
      <td class="metric-cell">${formatPercent(result.performance_ratio)}</td>
      <td class="metric-cell">${formatCoefficient(result.performance_coefficient)}</td>
      <td>${exceptions.length ? `<span class="exception-chip" tabindex="0" title="${exceptionTitle}" aria-label="异常：${exceptionTitle}">${exceptions.length}项</span>` : '<span class="muted-cell">-</span>'}</td>
      <td class="amount-cell"><span class="bonus-value">${formatCurrency(result.performance_bonus)}</span></td>
      <td>
        <button class="btn btn-secondary btn-sm detail-btn" onclick="toggleWorkbenchResultDetail(${formatJsArg(employeeId)})" title="查看说明">${expanded ? '收起' : '查看说明'}</button>
      </td>
    </tr>
    ${expanded ? renderBonusCalculationDetail(result) : ''}
  `;
}

function renderBonusCalculationDetail(result) {
  const rows = result.calculation_segments || [];
  const detailRows = rows.length ? rows : [{
    period: result.calc_month || '-',
    reason: result.calculation_path || '标准计算',
    performance_base: result.performance_base,
    performance_ratio: result.performance_ratio,
    performance_coefficient: result.performance_coefficient,
    performance_bonus: result.performance_bonus,
  }];

  return `
    <tr class="detail-row">
      <td colspan="12">
        <div class="calculation-lines">
          ${detailRows.map(row => `
            <div class="calculation-line">
              <span>${escapeHtml(row.reason || '-')}</span>
              <strong>${escapeHtml(renderBonusCalculationFormula(row, result))}</strong>
            </div>
          `).join('')}
          ${(result.exceptions || []).length ? `<div class="calculation-line"><span>异常提示</span><strong>${escapeHtml(result.exceptions.join('；'))}</strong></div>` : ''}
        </div>
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
          <span>异常</span>
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
  if (state.calculationPending) return;
  if (['queued', 'processing'].includes(state.calculationJobStatus?.status)) {
    return pollFbuCalculationJob(state.activeCalculationJob?.jobId);
  }

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

  state.calculationPending = true;
  renderWorkbenchCurrentStep();
  try {
    if (
      state.activeCalculationJob?.runId === state.currentActivity.run_id
      && (state.calculationJobStatus?.canRetry || state.calculationJobStatus?.recoverable)
    ) {
      return resumeFbuCalculationJob();
    }
    const runId = state.currentActivity.run_id;
    state.resultsData = [];
    clearRemoteResultViews(runId);
    state.calculationJobStatus = {
      status: 'queued',
      progress: 5,
      message: '正在排队',
    };
    renderWorkbenchCurrentStep();
    const data = await apiJson(`${API_BASE}/runs/${runId}/calculation-jobs`, {
      method: 'POST',
    });
    const jobId = data.job?.jobId;
    if (!jobId) {
      throw new Error('核算任务未返回任务编号');
    }
    rememberFbuCalculationJob(runId, jobId);
    if (data.job?.status === 'completed') {
      return completeFbuCalculationJob(state.activeCalculationJob, data.job);
    }
    return pollFbuCalculationJob(jobId);
  } catch (error) {
    state.calculationJobStatus = {
      status: 'failed',
      canRetry: Boolean(state.activeCalculationJob?.jobId),
      message: error.message || '核算任务创建失败',
    };
    renderWorkbenchCurrentStep();
    showNotification('核算失败: ' + error.message, 'error');
  } finally {
    state.calculationPending = false;
    renderWorkbenchCurrentStep({ preserveScroll: state.activityStep !== 'export' });
  }
}

el.btnCalculate?.addEventListener('click', executeCalculate);
el.btnCalculateEmpty?.addEventListener('click', executeCalculate);

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
    renderWorkbenchCurrentStep();
    restoreInputFocus(focusSnapshot);
    return;
  }
  if (type === 'attendance') renderAttendanceData();
  if (type === 'salary') renderSalaryData();
  if (type === 'performance') renderPerformanceData();
  if (type === 'supplementalLeave') renderSupplementalLeaveData();
  if (type === 'results') renderResultsData();
  if (type === 'exceptions') renderExceptionQueue();
  if (type === 'activities') renderActivities();
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
  if (state.activityStep === 'check' && type === 'baseSummary') {
    loadCheckResultsPage({ page: getTablePagination(type).page });
    return;
  }
  if (
    state.activityStep === 'export'
    && ['resultsWarehouse', 'resultsFunctional', 'resultsDistrict'].includes(type)
  ) {
    loadFinalResultsPage({ page: getTablePagination(type).page });
    return;
  }
  renderTableByType(type);
}

function changeTablePageSize(type, pageSize) {
  const size = Number(pageSize);
  const pagination = getTablePagination(type);
  pagination.pageSize = TABLE_PAGE_SIZE_OPTIONS.includes(size) ? size : DEFAULT_TABLE_PAGE_SIZE;
  pagination.page = 1;
  if (state.activityStep === 'check' && type === 'baseSummary') {
    loadCheckResultsPage({ page: 1, pageSize: pagination.pageSize });
    return;
  }
  if (
    state.activityStep === 'export'
    && ['resultsWarehouse', 'resultsFunctional', 'resultsDistrict'].includes(type)
  ) {
    loadFinalResultsPage({ page: 1, pageSize: pagination.pageSize });
    return;
  }
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

function setSupplementalLeaveQuality(value) {
  const input = document.getElementById('filterLeaveQuality');
  if (input) input.value = value || 'all';
  filterSupplementalLeaveData();
}

function setSupplementalBulkPreset(status, includeValue, button = null) {
  const statusInput = document.getElementById('bulkLeaveStatus');
  const includeInput = document.getElementById('bulkLeaveInclude');
  const currentStatus = statusInput?.value || '';
  const nextStatus = currentStatus === status ? '' : status;
  if (statusInput) statusInput.value = nextStatus;
  if (includeInput) includeInput.value = nextStatus ? includeValue : '';
  const group = button?.closest?.('.supplemental-bulk-presets');
  group?.querySelectorAll('button').forEach(item => {
    item.classList.toggle('active', Boolean(nextStatus) && item === button);
  });
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
  performance: ['有绩效报表的员工按报表数据计算。', '离职员工可在本页补充绩效系数。'],
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
  if (stepKey === 'salary') {
    return activity?.previous_salary_file && activity?.salary_file && activity?.adjustment_file && activity?.transfer_file ? '已完成' : '未完成';
  }
  if (stepKey === 'performance') return activity?.performance_file || activity?.performance_data?.employees?.length ? '已完成' : '未完成';
  if (stepKey === 'check' || stepKey === 'export') {
    return activity?.status === 'completed' || toNumber(activity?.total_employees) > 0
      ? '已完成'
      : '未开始';
  }
  return '未开始';
}

function renderActivityStepIndex(index, done, active) {
  const label = String(index + 1);
  if (active) {
    return `
      <span class="activity-step-index active-pin" aria-hidden="true">
        <svg class="activity-step-pin" viewBox="0 0 48 56" focusable="false">
          <ellipse class="activity-step-pin-shadow" cx="24" cy="51" rx="14" ry="4"></ellipse>
          <path class="activity-step-pin-halo" d="M24 1C11.3 1 1 11.3 1 24c0 12.7 13.5 20.6 20.7 29.6a3 3 0 0 0 4.6 0C33.5 44.6 47 36.7 47 24 47 11.3 36.7 1 24 1Z"></path>
          <path class="activity-step-pin-body" d="M24 6C14.1 6 6 14.1 6 24c0 10.4 11.2 17.2 16.2 24.4a2.2 2.2 0 0 0 3.6 0C30.8 41.2 42 34.4 42 24 42 14.1 33.9 6 24 6Z"></path>
          <text class="activity-step-pin-text" x="24" y="31" text-anchor="middle">${escapeHtml(label)}</text>
        </svg>
      </span>
    `;
  }
  return `<span class="activity-step-index">${done ? '✓' : escapeHtml(label)}</span>`;
}

function renderActivityStepper(activity) {
  return `
    <div class="activity-stepper payroll-activity-stepper activity-progress-strip" role="tablist" aria-label="核算步骤">
      ${ACTIVITY_STEPS.map((step, index) => {
        const active = state.activityStep === step.key;
        const status = getStepStatus(step.key, activity);
        const done = status === '已完成';
        const warning = status === '需要处理';
        return `
          <button class="activity-step activity-step-link ${active ? 'active' : ''} ${done ? 'done' : ''} ${warning ? 'warning' : ''}" type="button" role="tab" aria-selected="${active}" onclick="setActivityStep(${formatJsArg(step.key)})">
            ${renderActivityStepIndex(index, done, active)}
            <span class="activity-step-label">${escapeHtml(step.label)}</span>
            <span class="activity-step-status ${status === '需要处理' ? 'warning' : status === '已完成' ? 'success' : ''}">${escapeHtml(status)}</span>
          </button>
        `;
      }).join('')}
    </div>
  `;
}

function getStepInfoText(stepKey) {
  const notices = {
    people: '上传花名册后，系统自动核对本月参与核算人员。',
    attendance: '上传当月考勤和补充假勤后，系统自动计算本月工时。',
    salary: '上传相邻薪资档案、调薪流程和人事调动记录后，系统按生效日核验时薪、绩效比例及岗位。',
    performance: '上传绩效报表后，缺少绩效数据的离职人员可在本步骤补充系数。',
    check: '确认没有需要继续处理的事项后，开始本月核算。',
    export: '确认最终结果后，导出本月绩效奖金表。',
  };
  return notices[stepKey] || '';
}

function getStepNoticeKey(stepKey, activity = getWorkbenchActivity()) {
  return `${activity?.run_id || 'draft'}:${stepKey || ''}`;
}

function hideCurrentStepNotice(stepKey) {
  const noticeKey = getStepNoticeKey(stepKey);
  state.hiddenStepNotices = {
    ...state.hiddenStepNotices,
    [noticeKey]: true,
  };
  renderWorkbenchCurrentStep();
}

function renderStepInfoStrip(stepKey, activity = getWorkbenchActivity()) {
  const text = getStepInfoText(stepKey);
  if (!text) return '';
  const noticeKey = getStepNoticeKey(stepKey, activity);
  if (state.hiddenStepNotices?.[noticeKey]) return '';
  return `
    <div class="step-info-strip" role="note">
      <span class="step-info-icon">i</span>
      <span class="step-info-text">${escapeHtml(text)}</span>
      <button class="step-info-close" type="button" aria-label="关闭提示" onclick="hideCurrentStepNotice(${formatJsArg(stepKey)})">×</button>
    </div>
  `;
}

function getActivitySectionSummary(activity, field) {
  const listedActivity = state.activities.find(item => item.run_id === activity?.run_id);
  const summary = (
    activity?.sections?.[field]?.summary
    || listedActivity?.sections?.[field]?.summary
  );
  return summary && typeof summary === 'object' ? summary : {};
}

function hasUsableAttendanceView(activity) {
  return Array.isArray(activity?.attendance_data?.employees)
    && activity.attendance_data.employees.length > 0;
}

function hasHourlyRatePolicyRows(activity) {
  return Array.isArray(activity?.hourly_rate_policy_data?.rows)
    && activity.hourly_rate_policy_data.rows.length > 0;
}

function hasBaseOverrideRule(activity, ruleType, summaryKey) {
  const employees = activity?.base_override_data?.employees;
  if (Array.isArray(employees)) {
    return employees.some(row => row.rule_type === ruleType);
  }
  return toNumber(getActivitySectionSummary(activity, 'base_override_data')?.[summaryKey]) > 0;
}

function getSalaryVerificationBlockingCount(activity) {
  const summary = activity?.salary_verification_data?.summary;
  if (summary && typeof summary === 'object') {
    return toNumber(summary.blocking_count);
  }
  return toNumber(
    getActivitySectionSummary(activity, 'salary_verification_data')?.blocking_count,
  );
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
    if (activity.attendance_file && !hasUsableAttendanceView(activity)) {
      const attendanceViewLoaded = (activity.loaded_sections || []).includes('attendance_view_data');
      if (attendanceViewLoaded) {
        push(
          'attendanceRecovery',
          '考勤文件已上传，但工时明细未恢复，请重新上传考勤日报',
          '<button class="btn btn-primary btn-sm" type="button" onclick="openWorkbenchUpload(\'attendance\')">重新上传</button>',
        );
      }
    }
    if (!activity.supplemental_leave_file) push('supplementalLeave', '请上传补充假勤', '<button class="btn btn-primary btn-sm" type="button" onclick="openWorkbenchUpload(\'supplementalLeave\')">上传</button>');
    if (!hasBaseOverrideRule(activity, '96工时制', 'work_hour_rule_count')) {
      push('workHourList', '请确认96工时制员工名单', '<button class="btn btn-primary btn-sm" type="button" onclick="confirmMaintainedRuleList(\'workHour\')">确认名单</button>');
    }
    const supplementalRows = getWorkbenchSupplementalRows(activity);
    const supplementalRowsLoaded = (
      Array.isArray(activity?.supplemental_leave_data?.rows)
      || Array.isArray(state.supplementalLeaveData?.rows)
      || (activity.loaded_sections || []).includes('supplemental_leave_data')
    );
    if (supplementalRowsLoaded) {
      getSupplementalSuggestionRows(supplementalRows).slice(0, 5).forEach(row => {
        push(
          `leave-${row.row_id}`,
          `${row.employee_id} ${row.name || ''} 补充假勤请确认`,
          `<button class="btn btn-primary btn-sm" type="button" onclick="applyWorkbenchSupplementalSuggestion(${formatJsArg(row.row_id)}, ${getSupplementalSuggestedHours(row)})">计入建议小时</button>`,
        );
      });
    } else {
      const pendingCount = toNumber(
        getActivitySectionSummary(activity, 'supplemental_leave_data')?.pending_count,
      );
      if (pendingCount > 0) {
        push('leave-confirmations', `请处理 ${pendingCount} 条补充假勤待确认记录`);
      }
    }
  }
  if (stepKey === 'salary') {
    if (!activity.previous_salary_file) push('previousSalary', '请上传上月薪资档案', '<button class="btn btn-primary btn-sm" type="button" onclick="openWorkbenchUpload(\'previousSalary\')">上传</button>');
    if (!activity.salary_file) push('currentSalary', '请上传当月薪资档案', '<button class="btn btn-primary btn-sm" type="button" onclick="openWorkbenchUpload(\'currentSalary\')">上传</button>');
    if (!activity.adjustment_file) push('salaryAdjustments', '请上传全量调薪流程', '<button class="btn btn-primary btn-sm" type="button" onclick="openWorkbenchUpload(\'salaryAdjustments\')">上传</button>');
    if (!activity.transfer_file) push('transferHistory', '请上传人事调动记录', '<button class="btn btn-primary btn-sm" type="button" onclick="openWorkbenchUpload(\'transferHistory\')">上传</button>');
    const salaryBlockingCount = getSalaryVerificationBlockingCount(activity);
    if (salaryBlockingCount > 0) {
      push('salaryVerification', `请处理 ${salaryBlockingCount} 条薪资历史差异`);
    }
    if (!hasBaseOverrideRule(activity, '线下固定基数覆盖', 'fixed_base_count')) {
      push('fixedBaseList', '请确认固定基数人员名单', '<button class="btn btn-primary btn-sm" type="button" onclick="confirmMaintainedRuleList(\'fixedBase\')">确认名单</button>');
    }
  }
  if (stepKey === 'performance' && !activity.performance_file && !activity.performance_data?.employees?.length) {
    push('performance', '请上传绩效报表或补充离职人员绩效', '<button class="btn btn-primary btn-sm" type="button" onclick="openWorkbenchUpload(\'performance\')">上传</button>');
  }
  if (stepKey === 'check') {
    const incompleteStep = getFirstIncompleteInputStep(activity);
    if (incompleteStep) {
      const stepLabel = ACTIVITY_STEPS.find(step => step.key === incompleteStep)?.label || '前置步骤';
      const salaryBlockingCount = getSalaryVerificationBlockingCount(activity);
      const incompleteMessage = incompleteStep === 'salary' && salaryBlockingCount > 0
        ? `薪资历史核验还有 ${salaryBlockingCount} 条差异待确认`
        : `请先完成“${stepLabel}”后再进行核算前检查`;
      push(
        'incompleteInputStep',
        incompleteMessage,
        `<button class="btn btn-primary btn-sm" type="button" onclick="setActivityStep(${formatJsArg(incompleteStep)})">前往处理</button>`,
      );
    }
  }
  return needs;
}

function renderNeedsPanel(stepKey, activity) {
  const needs = buildNeedsForStep(stepKey, activity);
  if (!needs.length) {
    return `<section id="${escapeHtml(stepKey)}NeedsPanel" class="step-section needs-panel complete">本步骤已完成</section>`;
  }
  return `
    <section id="${escapeHtml(stepKey)}NeedsPanel" class="step-section needs-panel">
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

function rowMatchesWorkbenchStepSearch(row, term) {
  if (!term) return true;
  const values = [
    row?.employee_id,
    row?.source_employee_id,
    row?.name,
    row?.department,
    row?.area,
    row?.personnel_status,
    row?.job_type,
    row?.position,
    row?.cost_owner,
  ];
  return values.some(value => normalizeSearch(value).includes(term));
}

function getWorkbenchStepRows(type, rows) {
  const term = normalizeSearch(getWorkbenchStepSearch(type));
  if (!term) return rows;
  return rows.filter(row => rowMatchesWorkbenchStepSearch(row, term));
}

function renderWorkbenchTableSearch(type, {
  placeholder = '搜索工号、姓名',
  ariaLabel = '搜索工号或姓名',
} = {}) {
  const searchValue = getWorkbenchStepSearch(type);
  const inputId = `workbenchStepSearchInput-${type}`;
  return `
    <label class="activity-table-search" for="${escapeHtml(inputId)}">
      <span class="activity-table-search-icon" aria-hidden="true">
        <svg class="activity-search-icon-svg" viewBox="0 0 16 16" fill="none" focusable="false">
          <circle cx="7" cy="7" r="4.6"></circle>
          <path d="M10.4 10.4L14 14"></path>
        </svg>
      </span>
      <input id="${escapeHtml(inputId)}"
             class="activity-table-search-input"
             type="search"
             value="${escapeHtml(searchValue)}"
             placeholder="${escapeHtml(placeholder)}"
             autocomplete="off"
             spellcheck="false"
             oninput="handleWorkbenchStepSearchInput(event, ${formatJsArg(type)})"
             onkeydown="handleWorkbenchStepSearchKeydown(event, ${formatJsArg(type)})"
             oncompositionstart="handleWorkbenchStepSearchCompositionStart(event, ${formatJsArg(type)})"
             oncompositionend="handleWorkbenchStepSearchCompositionEnd(event, ${formatJsArg(type)})"
             aria-label="${escapeHtml(ariaLabel)}">
      ${searchValue ? `
        <button class="activity-table-search-clear"
                type="button"
                aria-label="清空搜索"
                onclick="event.preventDefault(); clearWorkbenchStepSearch(${formatJsArg(type)})">×</button>
      ` : ''}
    </label>
  `;
}

function renderCompactEmployeeTable(title, type, rows, headers, cellsForRow, activity) {
  const filteredRows = getWorkbenchStepRows(type, rows);
  const pageInfo = getPaginatedRows(type, filteredRows);
  const visibleRows = pageInfo.items;
  const rowCountLabel = `${pageInfo.total}/${rows.length}`;
  return `
    <section class="step-section table-section">
      <div class="activity-table-toolbar">
        <div class="activity-table-title">
          <h3>${escapeHtml(title)}</h3>
          <span>${escapeHtml(rowCountLabel)}</span>
        </div>
        ${renderWorkbenchTableSearch(type)}
      </div>
      <div class="data-table-container">
        <table class="data-table activity-table ${escapeHtml(type)}-activity-table">
          <thead>
            <tr><th class="sticky-employee-id">工号</th><th class="sticky-employee-name">姓名</th>${headers.map(header => `<th>${escapeHtml(header)}</th>`).join('')}</tr>
          </thead>
          <tbody>
            ${visibleRows.length ? visibleRows.map(row => `
              <tr>
                <td class="sticky-employee-id">${escapeHtml(row.employee_id || '-')}</td>
                <td class="sticky-employee-name">${renderNameWithTags(row, activity)}</td>
                ${cellsForRow(row).map(value => `<td>${value}</td>`).join('')}
              </tr>
            `).join('') : renderEmptyTableRow(headers.length + 2, rows.length ? '没有匹配的员工' : '暂无数据')}
          </tbody>
        </table>
      </div>
      ${renderTablePagination(type, pageInfo)}
    </section>
  `;
}

function renderPeopleTable(activity) {
  const rows = activity?.roster_data?.employees || activity?.attendance_data?.employees || activity?.salary_data?.employees || [];
  return renderCompactEmployeeTable('人员表', 'people', rows, ['部门', '岗位', '状态'], row => [
    escapeHtml(row.department || row.area || '-'),
    escapeHtml(getDisplayPosition(row, activity)),
    escapeHtml(row.personnel_status || '参与'),
  ], activity);
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
  const calcMonth = activity?.calc_month || state.currentActivity?.calc_month || '';
  const suggestionRows = getSupplementalSuggestionRows(rows);

  return `
    <section class="step-section">
      <div class="section-head compact">
        <div>
          <div class="supplemental-title-line">
            <h3>补充假勤确认</h3>
            <span class="supplemental-title-hours" data-summary-key="include_hours">
              <span>计入小时</span>
              <strong>${escapeHtml(renderSupplementalSummaryValue(summary, 'include_hours'))}</strong>
            </span>
          </div>
          <p>普通病假、年假默认确认；离职病假结算需要在这里继续处理。</p>
        </div>
        <div class="section-actions">
          <button class="btn btn-primary btn-sm" type="button" onclick="applyAllSupplementalLeaveSuggestions()" ${suggestionRows.length ? '' : 'disabled'}>应用全部建议计入${suggestionRows.length ? `(${suggestionRows.length})` : ''}</button>
        </div>
      </div>
      ${renderSupplementalLeaveFilterBar(rows, filteredRows)}
      ${renderSupplementalLeaveBulkBar(calcMonth)}
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
  const rows = activity?.attendance_data?.employees || [];
  return renderCompactEmployeeTable('工时表', 'attendance', rows, ['普通工时', 'OT1.5', 'OT2.0', '病假', '年假', '计薪工时'], row => [
      escapeHtml(formatHours(toNumber(row.base_hours || row.total_base_hours))),
      escapeHtml(formatHours(row.total_ot15)),
      escapeHtml(formatHours(row.total_ot20)),
      escapeHtml(formatHours(toNumber(row.sick_hours) + toNumber(row.sick_settlement_hours))),
      escapeHtml(formatHours(row.annual_hours)),
      escapeHtml(formatHours(row.total_base_hours)),
    ], activity);
}

const HOURLY_RATE_POLICY_LABELS = {
  base: '全周期基础时薪',
  night: '全周期基础+1',
  by_shift: '按班次（夜班+1）',
};
const HOURLY_RATE_POLICY_BUTTON_LABELS = {
  base: '统一用白班时薪',
  night: '统一用夜班时薪',
  by_shift: '按实际班次',
};

function getHourlyRatePolicyRows(activity, { visibleOnly = true } = {}) {
  const rows = activity?.hourly_rate_policy_data?.rows || [];
  const visibleRows = visibleOnly ? rows.filter(row => row.visible) : rows;
  if (!visibleOnly) return visibleRows;

  const term = normalizeSearch(getWorkbenchStepSearch('hourlyRatePolicy'));
  const shiftFilter = String(getTableFilter('hourlyRatePolicy').shift || 'all');
  return visibleRows.filter(row => {
    const matchesTerm = !term || [
      row.employee_id,
      row.name,
      row.department,
      row.position,
      row.period_start,
      row.period_end,
      row.shift_pattern,
    ].some(value => normalizeSearch(value).includes(term));
    const matchesShift = shiftFilter === 'all'
      || (shiftFilter === 'manual' ? Boolean(row.manual_override) : row.shift_pattern === shiftFilter);
    return matchesTerm && matchesShift;
  });
}

function setHourlyRatePolicyShiftFilter(value) {
  state.tableFilters.hourlyRatePolicy = {
    ...getTableFilter('hourlyRatePolicy'),
    shift: value || 'all',
  };
  getTablePagination('hourlyRatePolicy').page = 1;
  renderWorkbench();
}

function getSalaryRateForPolicyRow(activity, policyRow) {
  const rows = activity?.salary_data?.employees || [];
  const employee = rows.find(
    row => String(row.employee_id || '') === String(policyRow?.employee_id || ''),
  );
  const segments = employee?.effective_segments || [];
  if (segments.length) {
    const policyStart = String(policyRow?.overlap_start || policyRow?.period_start || '');
    const policyEnd = String(policyRow?.overlap_end || policyRow?.period_end || '');
    const rates = [...new Set(
      segments
        .filter(segment => String(segment.period_end || '') >= policyStart
          && String(segment.period_start || '') <= policyEnd)
        .map(segment => toNumber(segment.hourly_rate))
        .filter(rate => rate > 0)
    )];
    if (rates.length === 1) return rates[0];
    if (rates.length > 1) return null;
  }
  return employee && toNumber(employee.hourly_rate) > 0 ? toNumber(employee.hourly_rate) : null;
}

function formatHourlyRatePolicyOption(policy, baseRate) {
  const label = HOURLY_RATE_POLICY_LABELS[policy] || policy;
  if (baseRate === null) return label;
  if (policy === 'night') return `${label}（${formatCurrency(baseRate + 1)}）`;
  if (policy === 'base') return `${label}（${formatCurrency(baseRate)}）`;
  return `${label}（${formatCurrency(baseRate)} / ${formatCurrency(baseRate + 1)}）`;
}

function summarizeHourlyRatePolicies(policyData) {
  const rows = policyData?.rows || [];
  const visibleRows = rows.filter(row => row.visible);
  const previousSummary = policyData?.summary || {};
  policyData.summary = {
    total_periods: toNumber(previousSummary.total_periods, rows.length),
    visible_count: visibleRows.length,
    all_night_count: toNumber(
      previousSummary.all_night_count,
      rows.filter(row => row.shift_pattern === '全夜班').length,
    ),
    mixed_count: toNumber(
      previousSummary.mixed_count,
      rows.filter(row => row.shift_pattern === '白夜混合').length,
    ),
    manual_count: rows.filter(row => row.manual_override).length,
  };
}

function applyHourlyRatePolicyOptimistically(activity, action, payload) {
  const policyData = activity?.hourly_rate_policy_data;
  if (!policyData?.rows?.length) return false;

  if (action === 'update') {
    const row = policyData.rows.find(item => item.row_id === payload.row_id);
    if (!row) return false;
    row.selected_policy = payload.selected_policy;
    row.manual_override = payload.selected_policy !== row.suggested_policy;
    row.visible = true;
  } else if (action === 'restore_all') {
    policyData.rows.forEach(row => {
      row.selected_policy = row.suggested_policy || 'by_shift';
      row.manual_override = false;
      row.visible = row.shift_pattern !== '全白班';
    });
  } else {
    return false;
  }

  summarizeHourlyRatePolicies(policyData);
  return true;
}

async function updateHourlyRatePolicy(action, payload = {}) {
  const activity = getWorkbenchActivity();
  if (!activity?.run_id) return;
  const previousPolicyData = JSON.parse(JSON.stringify(activity.hourly_rate_policy_data || {}));
  const updatedImmediately = applyHourlyRatePolicyOptimistically(activity, action, payload);
  if (updatedImmediately) {
    setInlineActionNote('hourlyRatePolicy', '保存中…', 'warning', { render: false });
    renderWorkbench();
  }
  try {
    const data = await apiJson(`${API_BASE}/runs/${activity.run_id}/hourly-rate-policies`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, ...payload }),
    });
    activity.hourly_rate_policy_data = data.hourly_rate_policy_data;
    activity.results = [];
    activity.total_employees = 0;
    activity.total_bonus = 0;
    activity.match_rate = 0;
    state.resultsData = [];
    clearRemoteResultViews(activity.run_id);
    state.foundationRunDetails[activity.run_id] = activity;
    const activitySummary = state.activities.find(item => item.run_id === activity.run_id);
    if (activitySummary) {
      activitySummary.total_employees = 0;
      activitySummary.total_bonus = 0;
      activitySummary.match_rate = 0;
    }
    setInlineActionNote('hourlyRatePolicy', '已保存', 'success', { render: false });
    renderWorkbench();
  } catch (error) {
    activity.hourly_rate_policy_data = previousPolicyData;
    renderWorkbench();
    setInlineActionNote('hourlyRatePolicy', `周期时薪更新失败：${error.message}`, 'warning');
  }
}

function setHourlyRatePolicy(rowId, selectedPolicy) {
  return updateHourlyRatePolicy('update', { row_id: rowId, selected_policy: selectedPolicy });
}

function restoreHourlyRatePolicySuggestions() {
  return updateHourlyRatePolicy('restore_all');
}

async function addHourlyRatePolicyEmployee() {
  const activity = getWorkbenchActivity();
  const hiddenIds = [
    ...new Set(activity?.hourly_rate_policy_data?.hidden_employee_ids || []),
  ];
  if (!hiddenIds.length) {
    setInlineActionNote('hourlyRatePolicy', '当前所有有实际出勤的员工都已在建议区中。');
    return;
  }
  const result = await openAppDialog({
    title: '添加特殊时薪人员',
    message: '适用于白班出勤但需要按夜班时薪核算的员工。添加后可按工资周期修改。',
    confirmText: '添加',
    input: {
      label: '员工工号',
      placeholder: '例如 zt0020091',
      help: '只支持本月有实际出勤、当前未展示的员工。',
      validate: value => hiddenIds.includes(value.trim()) ? '' : '未找到该员工可调整的工资周期',
    },
  });
  if (!result?.confirmed) return;
  await updateHourlyRatePolicy('add_employee', { employee_id: result.value });
}

function renderHourlyRatePolicySection(activity) {
  if (!hasUsableAttendanceView(activity) && !hasHourlyRatePolicyRows(activity)) return '';
  const rows = getHourlyRatePolicyRows(activity);
  const pageInfo = getPaginatedRows('hourlyRatePolicy', rows);
  const summary = activity?.hourly_rate_policy_data?.summary || {};
  const shiftFilter = String(getTableFilter('hourlyRatePolicy').shift || 'all');
  return `
    <section class="step-section hourly-rate-policy-section">
      <div class="section-head compact hourly-rate-policy-head">
        <div>
          <h3>周期适用时薪</h3>
          <p>系统建议已默认用于核算；点击右侧按钮即可修改。上传薪资档案后会自动显示具体时薪金额。</p>
        </div>
        <div class="table-actions">
          ${toNumber(summary.manual_count) ? '<button class="btn btn-sm btn-secondary" type="button" onclick="restoreHourlyRatePolicySuggestions()">恢复全部建议</button>' : ''}
          <button class="btn btn-sm btn-secondary" type="button" onclick="addHourlyRatePolicyEmployee()">添加特殊人员</button>
        </div>
      </div>
      <div class="hourly-rate-policy-summary">
        <span>全夜班 <strong>${toNumber(summary.all_night_count)}</strong></span>
        <span>白夜混合 <strong>${toNumber(summary.mixed_count)}</strong></span>
        <span>人工调整 <strong>${toNumber(summary.manual_count)}</strong></span>
        ${renderInlineActionNote('hourlyRatePolicy')}
      </div>
      <div class="hourly-rate-policy-filterbar">
        <span class="hourly-rate-policy-filter-count">显示 <strong>${rows.length}</strong> / ${toNumber(summary.visible_count)} 条</span>
        <div class="hourly-rate-policy-filter-controls">
          ${renderWorkbenchTableSearch('hourlyRatePolicy', {
            placeholder: '搜索工号、姓名、部门',
            ariaLabel: '搜索周期时薪人员',
          })}
          <label class="hourly-rate-policy-shift-filter">
            <span>类型</span>
            <select aria-label="筛选出勤类型" onchange="setHourlyRatePolicyShiftFilter(this.value)">
              ${[
                ['all', '全部'],
                ['全夜班', '全夜班'],
                ['白夜混合', '白夜混合'],
                ['manual', '人工调整'],
              ].map(([value, label]) => `
                <option value="${escapeHtml(value)}" ${shiftFilter === value ? 'selected' : ''}>${escapeHtml(label)}</option>
              `).join('')}
            </select>
          </label>
        </div>
      </div>
      <div class="compact-list-table">
        <table class="data-table hourly-rate-policy-table">
          <thead>
            <tr>
              <th>工号</th>
              <th>姓名</th>
              <th>工资周期</th>
              <th>出勤构成</th>
              <th>系统建议</th>
              <th>
                <span class="hourly-rate-policy-heading">
                  核算口径（点击修改）
                  <span class="hourly-rate-policy-help">
                    <button class="hourly-rate-policy-help-trigger" type="button" aria-label="查看核算口径说明" aria-describedby="hourly-rate-policy-help-text">i</button>
                    <span class="hourly-rate-policy-help-content" id="hourly-rate-policy-help-text" role="tooltip">
                      <span class="hourly-rate-policy-help-line"><strong>按实际班次：</strong>白班用白班时薪，夜班用夜班时薪。</span>
                      <span class="hourly-rate-policy-help-line"><strong>统一用白班时薪：</strong>整周期均不加 $1。</span>
                      <span class="hourly-rate-policy-help-line"><strong>统一用夜班时薪：</strong>整周期均加 $1。</span>
                      <span class="hourly-rate-policy-help-line"><strong>其他计薪：</strong>OT 按所选时薪乘相应倍数，病假、年假也按所选时薪计算。</span>
                    </span>
                  </span>
                </span>
              </th>
            </tr>
          </thead>
          <tbody>
            ${pageInfo.items.length ? pageInfo.items.map(row => {
              const baseRate = getSalaryRateForPolicyRow(activity, row);
              return `
                <tr>
                  <td>${escapeHtml(row.employee_id || '-')}</td>
                  <td>${escapeHtml(row.name || '-')}</td>
                  <td>${escapeHtml(`${row.period_start || '-'} 至 ${row.period_end || '-'}`)}</td>
                  <td>${escapeHtml(`${row.shift_pattern || '-'} · 白班${formatHours(row.day_work_hours)} · 夜班${formatHours(row.night_work_hours)}`)}</td>
                  <td>
                    <strong>${escapeHtml(formatHourlyRatePolicyOption(row.suggested_policy, baseRate))}</strong>
                    <span class="cell-note">${escapeHtml(row.suggestion_reason || '')}</span>
                  </td>
                  <td>
                    <div class="hourly-rate-policy-options" role="group" aria-label="${escapeHtml(row.name || row.employee_id)}适用时薪">
                      ${['by_shift', 'base', 'night'].map(policy => `
                        <button class="workbench-segment ${row.selected_policy === policy ? 'active' : ''}"
                                type="button"
                                aria-pressed="${row.selected_policy === policy ? 'true' : 'false'}"
                                title="${escapeHtml(formatHourlyRatePolicyOption(policy, baseRate))}"
                                onclick="setHourlyRatePolicy(${formatJsArg(row.row_id)}, ${formatJsArg(policy)})">
                          ${row.selected_policy === policy ? '✓ ' : ''}${escapeHtml(HOURLY_RATE_POLICY_BUTTON_LABELS[policy])}
                        </button>
                      `).join('')}
                    </div>
                  </td>
                </tr>
              `;
            }).join('') : renderEmptyTableRow(6, '当前没有需要关注的周期时薪建议')}
          </tbody>
        </table>
      </div>
      ${rows.length ? renderTablePagination('hourlyRatePolicy', pageInfo) : ''}
    </section>
  `;
}

function getSalarySnapshotMonthLabels(calcMonth) {
  const match = String(calcMonth || '').match(/^(\d{4})-(\d{1,2})$/);
  if (!match) return { previous: '上月', current: '当月' };
  const currentYear = Number(match[1]);
  const currentMonth = Number(match[2]);
  const previousDate = new Date(currentYear, currentMonth - 2, 1);
  const previousYear = previousDate.getFullYear();
  const previousMonth = previousDate.getMonth() + 1;
  const crossesYear = previousYear !== currentYear;
  const format = (year, month) => crossesYear ? `${year}年${month}月` : `${month}月`;
  return {
    previous: format(previousYear, previousMonth),
    current: format(currentYear, currentMonth),
  };
}

function renderSalaryVerificationReview(activity) {
  const rows = (activity?.salary_verification_data?.employees || []).filter(
    row => row.verification_status === 'blocking',
  );
  if (!rows.length) return '';
  const monthLabels = getSalarySnapshotMonthLabels(activity?.calc_month);
  const snapshotMissing = (row, prefix) => row?.[`${prefix}_hourly_rate`] === null
    || row?.[`${prefix}_hourly_rate`] === undefined;
  const snapshotValue = (row, prefix, field, formatter) => snapshotMissing(row, prefix)
    ? '<span class="status-badge danger">缺失</span>'
    : escapeHtml(formatter(row?.[`${prefix}_${field}`]));
  const verificationResult = row => {
    if (row.resolution === 'missing_current_snapshot') return `${monthLabels.current}薪资档案缺少该员工`;
    if (row.resolution === 'missing_previous_snapshot') return `${monthLabels.previous}薪资档案缺少该员工`;
    return '未匹配已完成调薪流程';
  };

  return `
    <section id="salaryVerificationReview" class="step-section salary-verification-review">
      <div class="section-head compact">
        <div>
          <h3>薪资历史差异确认</h3>
          <p>以下员工存在${monthLabels.previous}与${monthLabels.current}薪资字段变化或相邻月份快照缺失。请根据薪酬依据选择核算值。</p>
        </div>
        <div class="section-actions">
          ${renderInlineActionNote('salary')}
          <span class="status-badge warning">${rows.length}条待确认</span>
        </div>
      </div>
      <div class="compact-list-table">
        <table class="data-table">
          <thead>
            <tr>
              <th>工号</th>
              <th>姓名</th>
              <th>${monthLabels.previous}时薪</th>
              <th>${monthLabels.current}时薪</th>
              <th>${monthLabels.previous}比例</th>
              <th>${monthLabels.current}比例</th>
              <th>核验结果</th>
              <th>确认核算值</th>
            </tr>
          </thead>
          <tbody>
            ${rows.map(row => {
              const isPending = state.salaryVerificationPendingIds.has(String(row.employee_id));
              return `
              <tr class="row-warning" data-employee-id="${escapeHtml(row.employee_id)}">
                <td>${escapeHtml(row.employee_id || '-')}</td>
                <td>${escapeHtml(row.name || '-')}</td>
                <td>${snapshotValue(row, 'previous', 'hourly_rate', formatCurrency)}</td>
                <td>${snapshotValue(row, 'current', 'hourly_rate', formatCurrency)}</td>
                <td>${snapshotValue(row, 'previous', 'ratio', formatPercent)}</td>
                <td>${snapshotValue(row, 'current', 'ratio', formatPercent)}</td>
                <td>${escapeHtml(verificationResult(row))}</td>
                <td>
                  <div class="table-actions">
                    ${snapshotMissing(row, 'previous') ? '' : renderSalaryVerificationButton(row.employee_id, 'previous', `按${monthLabels.previous}值`)}
                    ${snapshotMissing(row, 'current') ? '' : renderSalaryVerificationButton(row.employee_id, 'current', `按${monthLabels.current}值`, 'primary')}
                    ${row.resolution === 'missing_current_snapshot'
                      ? renderSalaryVerificationButton(
                        row.employee_id,
                        'ignore_current',
                        `${monthLabels.current}忽略不计`,
                        'secondary salary-ignore-snapshot-btn',
                        `本次按0处理；后续重新上传${monthLabels.current}薪资后会重新核验`,
                      )
                      : ''}
                  </div>
                </td>
              </tr>
            `;
            }).join('')}
          </tbody>
        </table>
      </div>
    </section>
  `;
}

function renderTransferHistoryReview(activity) {
  const data = activity?.transfer_data || {};
  const summary = data.summary || {};
  const events = data.events || [];
  if (!activity?.transfer_file) return '';
  const monthMatch = String(activity.calc_month || '').match(/^(\d{4})-(\d{2})$/);
  const monthStart = monthMatch ? `${monthMatch[1]}-${monthMatch[2]}-01` : '';
  const monthEnd = monthMatch
    ? `${monthMatch[1]}-${monthMatch[2]}-${String(new Date(Number(monthMatch[1]), Number(monthMatch[2]), 0).getDate()).padStart(2, '0')}`
    : '';
  const applicationLabel = (event) => {
    const effectiveDate = String(event.effective_date || '');
    if (monthStart && effectiveDate < monthStart) return '整月按调动后岗位';
    if (monthEnd && effectiveDate > monthEnd) return '整月按调动前岗位';
    return '按生效日拆分';
  };
  const relevantEvents = events
    .filter(event => event.effective_date)
    .sort((left, right) => String(left.effective_date).localeCompare(String(right.effective_date)));
  return `
    <section class="step-section transfer-history-review">
      <div class="section-head compact">
        <div>
          <h3>岗位历史核验</h3>
          <p>仅采用审批状态为“已完成”的记录；调动日期作为正式生效日期，生效日前按调动前岗位，生效日起按调动后岗位。</p>
        </div>
        <div class="transfer-history-head-meta">
          <div class="period-adjustment-summary">
            <span>有效 ${toNumber(summary.completed_count)} 条</span>
            <strong>月内拆分 ${toNumber(summary.in_month_employee_count)} 人</strong>
          </div>
          ${toNumber(summary.ignored_count) ? `<span class="material-action-note warning transfer-history-warning">已忽略审批中、已废弃或缺少生效日记录 ${toNumber(summary.ignored_count)} 条</span>` : ''}
        </div>
      </div>
      <div class="compact-list-table">
        <table class="data-table">
          <thead>
            <tr>
              <th>工号</th>
              <th>姓名</th>
              <th>生效日期</th>
              <th>调动前岗位</th>
              <th>调动后岗位</th>
              <th>本月处理</th>
            </tr>
          </thead>
          <tbody>
            ${relevantEvents.map(event => `
              <tr>
                <td>${escapeHtml(event.employee_id || '-')}</td>
                <td>${escapeHtml(event.name || '-')}</td>
                <td>${escapeHtml(event.effective_date || '-')}</td>
                <td title="${escapeHtml(event.before_position || '')}">${escapeHtml(event.before_position || '-')}</td>
                <td title="${escapeHtml(event.after_position || '')}">${escapeHtml(event.after_position || '-')}</td>
                <td><span class="status-badge ${applicationLabel(event) === '按生效日拆分' ? 'warning' : 'neutral'}">${escapeHtml(applicationLabel(event))}</span></td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    </section>
  `;
}

function getPeriodAdjustmentDraft(activity) {
  const draft = state.periodAdjustmentDraft;
  if (!draft.sourceMonth) draft.sourceMonth = activity?.calc_month || '';
  return draft;
}

function updatePeriodAdjustmentDraft(field, value) {
  const fieldMap = {
    employeeId: 'employeeId',
    amount: 'amount',
    sourceMonth: 'sourceMonth',
    reason: 'reason',
  };
  const target = fieldMap[field];
  if (!target) return;
  state.periodAdjustmentDraft[target] = value;
  if (state.periodAdjustmentErrors[target]) {
    delete state.periodAdjustmentErrors[target];
    const input = document.getElementById(`period-adjustment-${target === 'employeeId' ? 'employee' : target === 'sourceMonth' ? 'month' : target}`);
    input?.removeAttribute('aria-invalid');
    input?.closest('.workbench-inline-field')?.classList.remove('has-error');
    const error = document.getElementById(`period-adjustment-${target}-error`);
    if (error) error.remove();
  }
}

function setPeriodAdjustmentExpanded(expanded) {
  state.periodAdjustmentExpanded = Boolean(expanded);
}

function resetPeriodAdjustmentDraft(activity = getWorkbenchActivity()) {
  state.periodAdjustmentDraft = {
    employeeId: '',
    amount: '',
    sourceMonth: activity?.calc_month || '',
    reason: '',
  };
  state.periodAdjustmentErrors = {};
  state.periodAdjustmentExpanded = true;
  renderWorkbench();
}

function editPeriodAdjustment(employeeId) {
  const activity = getWorkbenchActivity();
  const row = (activity?.period_adjustment_data?.rows || [])
    .find(item => item.employee_id === employeeId);
  if (!row) return;
  state.periodAdjustmentDraft = {
    employeeId: row.employee_id || '',
    amount: String(row.amount ?? ''),
    sourceMonth: row.source_month || activity?.calc_month || '',
    reason: row.reason || '',
  };
  state.periodAdjustmentErrors = {};
  state.periodAdjustmentExpanded = true;
  renderWorkbench();
  document.getElementById('period-adjustment-amount')?.focus();
}

function validatePeriodAdjustmentDraft(activity, draft) {
  const errors = {};
  const employeeId = draft.employeeId.trim();
  const salaryRows = activity?.salary_data?.employees || [];
  const normalizedEmployeeId = sourceEmployeeId({ employee_id: employeeId });
  const salaryEmployeeExists = salaryRows.some(row => sourceEmployeeId(row) === normalizedEmployeeId);

  if (!employeeId) {
    errors.employeeId = '请输入员工工号';
  } else if (!salaryEmployeeExists) {
    errors.employeeId = '当月薪资档案中未找到该工号';
  }
  if (draft.amount === '') {
    errors.amount = '请输入基数调整额';
  } else if (!Number.isFinite(Number(draft.amount))) {
    errors.amount = '调整额必须为数字';
  } else if (Number(draft.amount) === 0) {
    errors.amount = '调整额不能为 0';
  }
  if (!draft.sourceMonth) errors.sourceMonth = '请选择归属月份';
  if (!draft.reason.trim()) errors.reason = '请填写调整原因';
  return errors;
}

function focusFirstPeriodAdjustmentError(errors) {
  const inputIds = {
    employeeId: 'period-adjustment-employee',
    amount: 'period-adjustment-amount',
    sourceMonth: 'period-adjustment-month',
    reason: 'period-adjustment-reason',
  };
  const firstField = ['employeeId', 'amount', 'sourceMonth', 'reason']
    .find(field => errors[field]);
  if (!firstField) return;
  requestAnimationFrame(() => {
    const input = document.getElementById(inputIds[firstField]);
    input?.scrollIntoView({ block: 'center', behavior: 'smooth' });
    input?.focus({ preventScroll: true });
  });
}

function setPeriodAdjustmentBackendError(message) {
  const text = String(message || '');
  let field = '';
  if (text.includes('工号') || text.includes('薪资档案')) field = 'employeeId';
  else if (text.includes('调整额')) field = 'amount';
  else if (text.includes('归属月份')) field = 'sourceMonth';
  else if (text.includes('原因')) field = 'reason';
  if (!field) return false;
  state.periodAdjustmentErrors = { [field]: text };
  state.periodAdjustmentExpanded = true;
  renderWorkbench();
  focusFirstPeriodAdjustmentError(state.periodAdjustmentErrors);
  return true;
}

async function savePeriodAdjustment() {
  const activity = getWorkbenchActivity();
  const draft = getPeriodAdjustmentDraft(activity);
  const button = document.getElementById('period-adjustment-save');
  const editing = (activity?.period_adjustment_data?.rows || [])
    .some(row => row.employee_id === draft.employeeId);
  if (state.periodAdjustmentSubmitting) return;
  const errors = validatePeriodAdjustmentDraft(activity, draft);
  if (Object.keys(errors).length) {
    state.periodAdjustmentErrors = errors;
    state.periodAdjustmentExpanded = true;
    renderWorkbench();
    focusFirstPeriodAdjustmentError(errors);
    return;
  }
  state.periodAdjustmentErrors = {};
  state.periodAdjustmentSubmitting = true;
  if (button) {
    button.disabled = true;
    button.textContent = '保存中…';
  }
  try {
    const data = await apiJson(`${API_BASE}/runs/${activity.run_id}/period-adjustments`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        action: 'upsert',
        employee_id: draft.employeeId.trim(),
        amount: draft.amount,
        source_month: draft.sourceMonth,
        reason: draft.reason.trim(),
      }),
    });
    activity.period_adjustment_data = data.period_adjustment_data;
    activity.results = [];
    activity.total_employees = 0;
    activity.total_bonus = 0;
    activity.match_rate = 0;
    state.resultsData = [];
    clearRemoteResultViews(activity.run_id);
    state.foundationRunDetails[activity.run_id] = activity;
    state.periodAdjustmentDraft = {
      employeeId: '',
      amount: '',
      sourceMonth: activity.calc_month || '',
      reason: '',
    };
    state.periodAdjustmentErrors = {};
    state.periodAdjustmentExpanded = false;
    renderWorkbench();
    showNotification('Period adjustment 已保存，请重新核算', 'success');
  } catch (error) {
    const message = error.message || 'Period adjustment 保存失败';
    if (!setPeriodAdjustmentBackendError(message)) showNotification(message, 'error');
  } finally {
    state.periodAdjustmentSubmitting = false;
    const currentButton = document.getElementById('period-adjustment-save');
    if (currentButton) {
      currentButton.disabled = false;
      currentButton.textContent = editing ? '更新' : '保存';
    }
  }
}

async function deletePeriodAdjustment(employeeId) {
  const activity = getWorkbenchActivity();
  const result = await openAppDialog({
    title: '删除基数调整',
    message: `将删除 ${employeeId} 的 Period adjustment。`,
    confirmText: '删除',
    cancelText: '保留',
    tone: 'danger',
  });
  if (!result?.confirmed) return;
  try {
    const data = await apiJson(`${API_BASE}/runs/${activity.run_id}/period-adjustments`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'delete', employee_id: employeeId }),
    });
    activity.period_adjustment_data = data.period_adjustment_data;
    activity.results = [];
    activity.total_employees = 0;
    activity.total_bonus = 0;
    activity.match_rate = 0;
    state.resultsData = [];
    clearRemoteResultViews(activity.run_id);
    state.foundationRunDetails[activity.run_id] = activity;
    if (state.periodAdjustmentDraft.employeeId === employeeId) {
      state.periodAdjustmentDraft = {
        employeeId: '',
        amount: '',
        sourceMonth: activity.calc_month || '',
        reason: '',
      };
      state.periodAdjustmentErrors = {};
    }
    renderWorkbench();
    showNotification('Period adjustment 已删除，请重新核算', 'success');
  } catch (error) {
    showNotification(error.message || 'Period adjustment 删除失败', 'error');
  }
}

function renderPeriodAdjustmentSection(activity) {
  const rows = activity?.period_adjustment_data?.rows || [];
  const summary = activity?.period_adjustment_data?.summary || {};
  const salaryRows = activity?.salary_data?.employees || [];
  const salaryReady = salaryRows.length > 0;
  const draft = getPeriodAdjustmentDraft(activity);
  const errors = state.periodAdjustmentErrors || {};
  const editing = rows.some(row => row.employee_id === draft.employeeId);
  const fieldError = (field) => errors[field]
    ? `<span class="workbench-field-error" id="period-adjustment-${field}-error">${escapeHtml(errors[field])}</span>`
    : '';
  const invalidAttribute = field => errors[field]
    ? `aria-invalid="true" aria-describedby="period-adjustment-${field}-error"`
    : '';
  const disabledAttribute = salaryReady ? '' : 'disabled';
  const expanded = state.periodAdjustmentExpanded || editing || Object.keys(errors).length > 0;
  return `
    <details class="period-adjustment-section period-adjustment-compact"
             ${expanded ? 'open' : ''}
             ontoggle="setPeriodAdjustmentExpanded(this.open)">
      <summary class="period-adjustment-toggle">
        <span class="period-adjustment-toggle-copy">
          <strong>绩效基数补发差额</strong>
          <span class="status-badge neutral">选填</span>
        </span>
        <span class="period-adjustment-summary">
          <span>${rows.length} 条</span>
          <strong>${formatCurrency(summary.total_amount || 0)}</strong>
          <span class="period-adjustment-toggle-action">维护</span>
        </span>
      </summary>
      <div class="period-adjustment-body">
        <p class="period-adjustment-guidance">
          正数补发、负数扣回；奖金统一按本次核算月比例和系数计算。
        </p>
        ${salaryReady ? '' : `
          <div class="period-adjustment-dependency" role="status">
            请先上传当月薪资档案，系统需据此校验工号和本月绩效比例。
          </div>
        `}
        <div class="workbench-inline-form period-adjustment-form">
          <div class="workbench-inline-field ${errors.employeeId ? 'has-error' : ''}">
            <label for="period-adjustment-employee">员工工号</label>
            <input id="period-adjustment-employee" value="${escapeHtml(draft.employeeId)}"
                   ${editing ? 'readonly' : ''} ${disabledAttribute} ${invalidAttribute('employeeId')}
                   placeholder="例如 zt0017777"
                   oninput="updatePeriodAdjustmentDraft('employeeId', this.value)">
            ${fieldError('employeeId')}
          </div>
          <div class="workbench-inline-field ${errors.amount ? 'has-error' : ''}">
            <label for="period-adjustment-amount">基数调整额</label>
            <input id="period-adjustment-amount" type="number" step="0.01"
                   value="${escapeHtml(draft.amount)}" placeholder="正数补发，负数扣回" ${disabledAttribute} ${invalidAttribute('amount')}
                   oninput="updatePeriodAdjustmentDraft('amount', this.value)">
            ${fieldError('amount')}
          </div>
          <div class="workbench-inline-field ${errors.sourceMonth ? 'has-error' : ''}">
            <label for="period-adjustment-month">归属月份</label>
            <input id="period-adjustment-month" type="month"
                   value="${escapeHtml(draft.sourceMonth)}" ${disabledAttribute} ${invalidAttribute('sourceMonth')}
                   oninput="updatePeriodAdjustmentDraft('sourceMonth', this.value)">
            ${fieldError('sourceMonth')}
          </div>
          <div class="workbench-inline-field wide ${errors.reason ? 'has-error' : ''}">
            <label for="period-adjustment-reason">调整原因</label>
            <input id="period-adjustment-reason" value="${escapeHtml(draft.reason)}" ${disabledAttribute} ${invalidAttribute('reason')}
                   placeholder="例如 补发5月绩效基数差额"
                   oninput="updatePeriodAdjustmentDraft('reason', this.value)">
            ${fieldError('reason')}
          </div>
          <div class="period-adjustment-form-actions">
            ${editing ? '<button class="btn btn-secondary btn-sm" type="button" onclick="resetPeriodAdjustmentDraft()">取消</button>' : ''}
            <button class="btn btn-primary btn-sm" id="period-adjustment-save" type="button"
                    ${disabledAttribute} onclick="savePeriodAdjustment()">${editing ? '更新' : '保存'}</button>
          </div>
        </div>
        ${rows.length ? `
          <div class="period-adjustment-records">
            ${rows.map(row => `
              <div class="period-adjustment-record">
                <div class="period-adjustment-record-copy">
                  <div>
                    <strong>${escapeHtml(row.employee_id || '-')}</strong>
                    <span>${escapeHtml(row.name || '-')}</span>
                    <span>${escapeHtml(row.source_month || '-')}</span>
                  </div>
                  <p title="${escapeHtml(row.reason || '-')}">${escapeHtml(row.reason || '-')}</p>
                </div>
                <strong class="period-adjustment-record-amount ${toNumber(row.amount) < 0 ? 'negative-amount' : ''}">${formatCurrency(row.amount)}</strong>
                <div class="period-adjustment-record-actions">
                  <button class="btn btn-secondary btn-sm" type="button" onclick="editPeriodAdjustment(${formatJsArg(row.employee_id)})">编辑</button>
                  <button class="btn btn-danger btn-sm" type="button" onclick="deletePeriodAdjustment(${formatJsArg(row.employee_id)})">删除</button>
                </div>
              </div>
            `).join('')}
          </div>
        ` : ''}
      </div>
    </details>
  `;
}

function renderSalarySummaryTable(activity) {
  const rows = activity?.salary_data?.employees || [];
  return renderCompactEmployeeTable('薪资表', 'salary', rows, ['部门全称', '岗位', '人员状态', '划分区域', '成本归属', '时薪', '绩效比例', '固定基数'], row => [
    `<span class="wrap-cell">${escapeHtml(row.department || '-')}</span>`,
    `<span class="wrap-cell">${escapeHtml(row.position || '-')}</span>`,
    escapeHtml(row.personnel_status || '-'),
    escapeHtml(row.area || '-'),
    `<span class="wrap-cell">${escapeHtml(row.cost_owner || '-')}</span>`,
    escapeHtml(formatCurrency(row.hourly_rate)),
    escapeHtml(formatPercent(row.ratio)),
    escapeHtml(toNumber(row.fixed_performance_base) ? formatCurrency(row.fixed_performance_base) : '-'),
  ], activity);
}

function renderPerformanceInlineSupplement() {
  return `
    <section class="step-section">
      <div class="section-head compact">
        <div>
          <h3>离职人员补充</h3>
          <p>缺少绩效数据的离职员工可在这里补充系数。</p>
        </div>
      </div>
      ${renderWorkbenchPerformanceSupplement()}
    </section>
  `;
}

function renderPerformanceSummaryTable(activity) {
  const rows = getPerformanceReviewRows(activity?.performance_data?.employees || []);
  return renderCompactEmployeeTable('绩效表', 'performance', rows, ['得分', '等级', '系数'], row => [
    escapeHtml(formatScore(row.score)),
    escapeHtml(row.level || '-'),
    escapeHtml(formatCoefficient(row.coefficient)),
  ], activity);
}

function renderCheckPreview(activity) {
  const activeTab = state.checkTab === 'issues' ? 'issues' : 'base';
  state.checkTab = activeTab;
  const tabs = [
    { key: 'base', label: '绩效基数汇总' },
    { key: 'issues', label: '检查事项' },
  ];
  return `
    <section class="step-section check-review-section">
      <div class="check-tabbar" role="tablist" aria-label="核算检查">
        ${tabs.map(tab => `
          <button class="workbench-segment ${activeTab === tab.key ? 'active' : ''}"
                  type="button"
                  role="tab"
                  aria-selected="${activeTab === tab.key ? 'true' : 'false'}"
                  onclick="setCheckTab(${formatJsArg(tab.key)})">
            ${escapeHtml(tab.label)}
          </button>
        `).join('')}
      </div>
      ${activeTab === 'base' ? renderPerformanceBaseSummary(activity) : renderCheckIssuesPanel(activity)}
    </section>
  `;
}

function getBasePathLabel(result) {
  return result?.calculation_path || '标准绩效基数路径';
}

function getPerformanceBaseGroups(results) {
  const byPath = new Map();
  results.forEach(result => {
    const path = getBasePathLabel(result);
    if (!byPath.has(path)) {
      byPath.set(path, { path, count: 0, totalBase: 0, totalBonus: 0 });
    }
    const group = byPath.get(path);
    group.count += 1;
    group.totalBase += toNumber(result.performance_base);
    group.totalBonus += toNumber(result.performance_bonus);
  });
  return [...byPath.values()].sort((a, b) => b.totalBase - a.totalBase);
}

function renderPerformanceBaseSummary(activity) {
  const results = getWorkbenchResults(activity);
  const remote = state.checkResultsRemote.runId === activity?.run_id
    ? state.checkResultsRemote
    : null;
  const remotePagination = remote?.pagination || {};
  const pageInfo = remote?.pagination
    ? {
        items: remote.rows || [],
        page: toNumber(remotePagination.page) || 1,
        pageSize: toNumber(remotePagination.page_size) || DEFAULT_TABLE_PAGE_SIZE,
        total: toNumber(remotePagination.total),
        totalPages: toNumber(remotePagination.pages) || 1,
        start: toNumber(remotePagination.total)
          ? ((toNumber(remotePagination.page) || 1) - 1)
            * (toNumber(remotePagination.page_size) || DEFAULT_TABLE_PAGE_SIZE) + 1
          : 0,
        end: Math.min(
          (toNumber(remotePagination.page) || 1)
            * (toNumber(remotePagination.page_size) || DEFAULT_TABLE_PAGE_SIZE),
          toNumber(remotePagination.total),
        ),
      }
    : getPaginatedRows('baseSummary', results);
  const summary = remote?.summary || {};
  const groups = Array.isArray(summary.calculation_paths)
    ? summary.calculation_paths.map(group => ({
        path: group.path,
        count: toNumber(group.count),
        totalBase: toNumber(group.total_base),
        totalBonus: toNumber(group.total_bonus),
      }))
    : getPerformanceBaseGroups(results);
  const resultCount = remote
    ? toNumber(summary.total_employees)
    : results.length;
  const totalBase = remote
    ? toNumber(summary.total_performance_base)
    : results.reduce((sum, result) => sum + toNumber(result.performance_base), 0);
  const totalBonus = remote
    ? toNumber(summary.total_bonus)
    : results.reduce((sum, result) => sum + toNumber(result.performance_bonus), 0);
  const specialCount = remote
    ? toNumber(summary.special_base_count)
    : results.filter(result => getBasePathLabel(result) !== '标准绩效基数路径').length;

  return `
    <div class="check-tab-panel">
      ${renderImportSummary([
        { label: '结果人数', value: resultCount, mono: true },
        { label: '绩效基数合计', value: formatCurrency(totalBase), mono: true },
        { label: '特殊基数', value: `${specialCount}人`, mono: true, tone: specialCount ? 'warning' : 'success' },
        { label: '奖金总额', value: formatCurrency(totalBonus), mono: true },
      ])}
      <div class="compact-list-table base-path-summary-table">
        <table class="data-table">
          <thead>
            <tr>
              <th>核算路径</th>
              <th class="metric-cell">人数</th>
              <th class="amount-cell">绩效基数</th>
              <th class="amount-cell">奖金</th>
            </tr>
          </thead>
          <tbody>
            ${groups.length ? groups.map(group => `
              <tr>
                <td>${escapeHtml(group.path)}</td>
                <td class="metric-cell">${group.count}</td>
                <td class="amount-cell">${formatCurrency(group.totalBase)}</td>
                <td class="amount-cell">${formatCurrency(group.totalBonus)}</td>
              </tr>
            `).join('') : renderEmptyTableRow(4, '暂无绩效基数数据')}
          </tbody>
        </table>
      </div>
      <div class="compact-list-table base-summary-detail-table">
        <table class="data-table">
          <thead>
            <tr>
              <th class="sticky-employee-id">工号</th>
              <th class="sticky-employee-name">姓名</th>
              <th>部门</th>
              <th>岗位</th>
              <th>核算路径</th>
              <th class="amount-cell">绩效基数</th>
              <th class="metric-cell">绩效比例</th>
              <th class="metric-cell">绩效系数</th>
              <th class="amount-cell">最终奖金</th>
            </tr>
          </thead>
          <tbody>
            ${pageInfo.items.length ? pageInfo.items.map(result => {
              const isNinetySixHour = isNinetySixHourResult(result);
              return `
                <tr>
                  <td class="sticky-employee-id">${escapeHtml(result.employee_id || '-')}</td>
                  <td class="sticky-employee-name">${renderNameWithTags(result, activity)}</td>
                  <td>${escapeHtml(result.department || result.area || '-')}</td>
                  <td>${escapeHtml(getDisplayPosition(result, activity))}</td>
                  <td>${escapeHtml(getBasePathLabel(result))}</td>
                  <td class="amount-cell ${isNinetySixHour ? 'highlight-base' : ''}">${formatCurrency(result.performance_base)}</td>
                  <td class="metric-cell">${formatPercent(result.performance_ratio)}</td>
                  <td class="metric-cell">${formatCoefficient(result.performance_coefficient)}</td>
                  <td class="amount-cell">${formatCurrency(result.performance_bonus)}</td>
                </tr>
              `;
            }).join('') : renderEmptyTableRow(9, '暂无绩效基数数据')}
          </tbody>
        </table>
      </div>
      ${resultCount ? renderTablePagination('baseSummary', pageInfo) : ''}
    </div>
  `;
}

function renderCheckIssuesPanel(activity) {
  const diagnostics = getWorkbenchDiagnostics(activity);
  const summary = diagnostics?.summary || {};
  const issues = (diagnostics?.issues || []).filter(Boolean);
  const pageInfo = getPaginatedRows('check', issues);
  const readyCount = toNumber(summary.can_calculate_count);
  const totalCount = toNumber(summary.attendance_count);
  const resultCount = state.checkResultsRemote.runId === activity?.run_id
    ? toNumber(state.checkResultsRemote.summary?.total_employees)
    : getWorkbenchResults(activity).length;
  const severityLabel = { error: '严重', warning: '提醒', info: '信息' };

  return `
    <div class="check-tab-panel">
      ${renderImportSummary([
        { label: '严重', value: toNumber(summary.error_count), mono: true, tone: toNumber(summary.error_count) ? 'danger' : 'success' },
        { label: '提醒', value: toNumber(summary.warning_count), mono: true, tone: toNumber(summary.warning_count) ? 'warning' : 'success' },
        { label: '可继续计算', value: `${readyCount}/${totalCount}`, mono: true },
        { label: '结果人数', value: resultCount, mono: true },
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
            ${pageInfo.items.length ? pageInfo.items.map(issue => {
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
      ${renderTablePagination('check', pageInfo)}
    </div>
  `;
}

function renderExportStep(activity) {
  return `${renderFinalResults(activity)}`;
}

async function loadCheckResultsPage(options = {}) {
  const activity = state.currentActivity;
  if (!activity?.run_id || activity.status !== 'completed') {
    state.checkResultsRemote = {
      runId: '',
      rows: [],
      pagination: null,
      summary: null,
    };
    return null;
  }
  const pagination = getTablePagination('baseSummary');
  const page = Math.max(1, Number(options.page || pagination.page || 1));
  const pageSize = TABLE_PAGE_SIZE_OPTIONS.includes(Number(options.pageSize || pagination.pageSize))
    ? Number(options.pageSize || pagination.pageSize)
    : DEFAULT_TABLE_PAGE_SIZE;
  const render = options.render !== false;
  const loadingKey = activityStepLoadingKey('check-results', activity);
  state.activitySectionsLoading.add(loadingKey);
  if (render && state.currentPage === 'workbench') renderWorkbench();

  try {
    const payload = await apiJson(
      `${API_BASE}/runs/${activity.run_id}/results?`
      + `page=${page}&page_size=${pageSize}&q=&group=all`,
    );
    if (state.currentActivity?.run_id !== activity.run_id) return null;
    const remotePagination = payload.pagination || {};
    pagination.page = Number(remotePagination.page || page);
    pagination.pageSize = Number(remotePagination.page_size || pageSize);
    state.checkResultsRemote = {
      runId: activity.run_id,
      rows: Array.isArray(payload.results) ? payload.results : [],
      pagination: remotePagination,
      summary: payload.summary || {},
    };
    return state.checkResultsRemote;
  } catch (error) {
    console.error('加载核验结果失败:', error);
    showNotification(`加载核验结果失败：${error.message}`, 'error');
    return null;
  } finally {
    state.activitySectionsLoading.delete(loadingKey);
    if (render && state.currentPage === 'workbench') renderWorkbench();
  }
}

async function loadFinalResultsPage(options = {}) {
  const activity = state.currentActivity;
  if (!activity?.run_id || activity.status !== 'completed') return null;
  const group = options.group || state.finalResultSlice || 'warehouse';
  const paginationKey = {
    warehouse: 'resultsWarehouse',
    functional: 'resultsFunctional',
    district: 'resultsDistrict',
  }[group] || 'resultsWarehouse';
  const pagination = getTablePagination(paginationKey);
  const page = Math.max(1, Number(options.page || pagination.page || 1));
  const pageSize = TABLE_PAGE_SIZE_OPTIONS.includes(Number(options.pageSize || pagination.pageSize))
    ? Number(options.pageSize || pagination.pageSize)
    : DEFAULT_TABLE_PAGE_SIZE;
  const query = String(
    options.query === undefined
      ? getWorkbenchStepSearch('finalResults')
      : options.query,
  ).trim();
  const render = options.render !== false;
  const loadingKey = activityStepLoadingKey('export', activity);
  state.activitySectionsLoading.add(loadingKey);
  if (render && state.currentPage === 'workbench') renderWorkbench();

  try {
    const payload = await apiJson(
      `${API_BASE}/runs/${activity.run_id}/results?`
      + `page=${page}&page_size=${pageSize}`
      + `&q=${encodeURIComponent(query)}`
      + `&group=${encodeURIComponent(group)}`,
    );
    if (state.currentActivity?.run_id !== activity.run_id) return null;
    const remotePagination = payload.pagination || {};
    pagination.page = Number(remotePagination.page || page);
    pagination.pageSize = Number(remotePagination.page_size || pageSize);
    state.finalResultSlice = group;
    state.resultsData = Array.isArray(payload.results) ? payload.results : [];
    state.finalResultsRemote = {
      runId: activity.run_id,
      group,
      query,
      rows: state.resultsData,
      pagination: remotePagination,
      summary: payload.summary || {},
    };
    return state.finalResultsRemote;
  } catch (error) {
    console.error('加载最终结果失败:', error);
    showNotification(`加载最终结果失败：${error.message}`, 'error');
    return null;
  } finally {
    state.activitySectionsLoading.delete(loadingKey);
    if (render && state.currentPage === 'workbench') renderWorkbench();
  }
}

function getFinalResultGroupKey(result) {
  if (result?.job_type === 'district_manager') return 'district';
  if (result?.job_type === 'functional') return 'functional';
  return 'warehouse';
}

function getFinalResultGroups(results) {
  const groups = [
    { key: 'warehouse', paginationKey: 'resultsWarehouse', label: '仓库管理人员', rows: [] },
    { key: 'functional', paginationKey: 'resultsFunctional', label: '非仓人员', rows: [] },
    { key: 'district', paginationKey: 'resultsDistrict', label: '区长', rows: [] },
  ];
  const remote = state.finalResultsRemote;
  if (remote.runId === state.currentActivity?.run_id && remote.summary?.groups) {
    groups.forEach(group => {
      const meta = remote.summary.groups[group.key] || {};
      group.count = toNumber(meta.count);
      group.totalBonus = toNumber(meta.total_bonus);
      group.rows = remote.group === group.key ? (remote.rows || []) : [];
    });
    return groups;
  }
  const byKey = Object.fromEntries(groups.map(group => [group.key, group]));
  results.forEach(result => {
    byKey[getFinalResultGroupKey(result)]?.rows.push(result);
  });
  return groups;
}

function getFinalResultGroupMeta(group) {
  if (group.count !== undefined) {
    return {
      count: toNumber(group.count),
      totalBonus: toNumber(group.totalBonus),
    };
  }
  const totalBonus = group.rows.reduce((sum, row) => sum + toNumber(row.performance_bonus), 0);
  return {
    count: group.rows.length,
    totalBonus,
  };
}

function setFinalResultSlice(sliceKey) {
  state.finalResultSlice = sliceKey || 'warehouse';
  getTablePagination({
    warehouse: 'resultsWarehouse',
    functional: 'resultsFunctional',
    district: 'resultsDistrict',
  }[state.finalResultSlice] || 'resultsWarehouse').page = 1;
  renderWorkbenchCurrentStep();
  loadFinalResultsPage({ page: 1, group: state.finalResultSlice });
}

function rowMatchesFinalResultSearch(result, activity, term) {
  if (!term) return true;
  const values = [
    result?.employee_id,
    result?.source_employee_id,
    result?.name,
    result?.department,
    result?.area,
    result?.position,
    getDisplayPosition(result, activity),
  ];
  return values.some(value => normalizeSearch(value).includes(term));
}

function getFinalResultSearchRows(rows, activity) {
  const term = normalizeSearch(getWorkbenchStepSearch('finalResults'));
  if (!term) return rows;
  return rows.filter(result => rowMatchesFinalResultSearch(result, activity, term));
}

function isNinetySixHourResult(result) {
  return result?.work_hour_rule === '96工时制'
    || String(result?.calculation_path || '').includes('96工时制')
    || String(result?.base_override_type || '').includes('96工时制');
}

function renderFinalResults(activity) {
  const results = getWorkbenchResults(activity);
  const groups = getFinalResultGroups(results);
  const activeGroup = groups.find(group => group.key === state.finalResultSlice) || groups[0];
  state.finalResultSlice = activeGroup?.key || 'warehouse';
  const remote = state.finalResultsRemote.runId === activity?.run_id
    ? state.finalResultsRemote
    : null;
  const resultCount = remote?.summary
    ? toNumber(remote.summary.total_employees)
    : results.length;
  const totalBonus = remote?.summary
    ? toNumber(remote.summary.total_bonus)
    : results.reduce((sum, row) => sum + toNumber(row.performance_bonus), 0);
  return `
    <section class="step-section final-results">
      <div class="section-head compact">
        <h3>最终结果</h3>
        <button class="btn btn-primary btn-sm" type="button" onclick="exportData('results')" ${resultCount ? '' : 'disabled'}>导出结果</button>
      </div>
      <div class="result-summary-bar compact">
        <div class="result-summary-item">
          <span>结果人数</span>
          <span>${resultCount}</span>
        </div>
        <div class="result-summary-item">
          <span>奖金总额</span>
          <span>${formatCurrency(totalBonus)}</span>
        </div>
      </div>
      <div class="final-result-slices" role="tablist" aria-label="最终结果切面">
        ${groups.map(group => {
          const meta = getFinalResultGroupMeta(group);
          const isActive = group.key === activeGroup.key;
          return `
            <button class="final-result-slice ${isActive ? 'active' : ''}"
                    type="button"
                    role="tab"
                    aria-selected="${isActive ? 'true' : 'false'}"
                    onclick="setFinalResultSlice(${formatJsArg(group.key)})">
              <span>${escapeHtml(group.label)}</span>
              <strong>${meta.count}人</strong>
              <em>${formatCurrency(meta.totalBonus)}</em>
            </button>
          `;
        }).join('')}
      </div>
      ${renderFinalResultGroup(activeGroup, activity)}
    </section>
  `;
}

function renderFinalResultGroup(group, activity) {
  const remote = state.finalResultsRemote.runId === activity?.run_id
    && state.finalResultsRemote.group === group.key
    ? state.finalResultsRemote
    : null;
  const filteredRows = remote ? group.rows : getFinalResultSearchRows(group.rows, activity);
  const remotePagination = remote?.pagination;
  const pageInfo = remotePagination ? {
    items: group.rows,
    page: toNumber(remotePagination.page, 1),
    pageSize: toNumber(remotePagination.page_size, DEFAULT_TABLE_PAGE_SIZE),
    total: toNumber(remotePagination.total),
    totalPages: toNumber(remotePagination.pages, 1),
    start: toNumber(remotePagination.total)
      ? ((toNumber(remotePagination.page, 1) - 1) * toNumber(remotePagination.page_size, DEFAULT_TABLE_PAGE_SIZE)) + 1
      : 0,
    end: Math.min(
      toNumber(remotePagination.page, 1) * toNumber(remotePagination.page_size, DEFAULT_TABLE_PAGE_SIZE),
      toNumber(remotePagination.total),
    ),
  } : getPaginatedRows(group.paginationKey, filteredRows);
  const groupMeta = getFinalResultGroupMeta(group);
  const groupBonus = groupMeta.totalBonus;
  const searchValue = getWorkbenchStepSearch('finalResults');
  const countLabel = searchValue
    ? `${pageInfo.total}/${groupMeta.count}人`
    : `${groupMeta.count}人`;
  return `
    <section class="final-result-group">
      <div class="final-result-group-head">
        <h4>${escapeHtml(group.label)}</h4>
        <span>${escapeHtml(countLabel)}</span>
        <span>${formatCurrency(groupBonus)}</span>
        ${renderWorkbenchTableSearch('finalResults', {
          placeholder: '搜索工号、姓名、部门或岗位',
          ariaLabel: '搜索最终结果',
        })}
      </div>
      <div class="data-table-container">
        <table class="data-table final-result-table">
          <thead>
            <tr>
              <th class="sticky-employee-id">工号</th>
              <th class="sticky-employee-name">姓名</th>
              <th>部门</th>
              <th>岗位</th>
              <th class="metric-cell">绩效得分</th>
              <th class="amount-cell">绩效基数</th>
              <th class="metric-cell">绩效比例</th>
              <th class="metric-cell">绩效系数</th>
              <th class="amount-cell">最终奖金</th>
              <th>计算过程</th>
            </tr>
          </thead>
          <tbody>
            ${pageInfo.items.length
              ? pageInfo.items.map(result => renderFinalResultRow(result, activity)).join('')
              : renderEmptyTableRow(10, group.rows.length ? '没有匹配的核算结果' : '当前切面暂无结果')}
          </tbody>
        </table>
      </div>
      ${pageInfo.total ? renderTablePagination(group.paginationKey, pageInfo) : ''}
    </section>
  `;
}

function renderFinalResultRow(result, activity) {
  const employeeId = String(result.employee_id || '');
  const isNinetySixHour = isNinetySixHourResult(result);
  const detailKey = getFinalResultDetailKey(result);

  return `
    <tr>
      <td class="sticky-employee-id">${escapeHtml(employeeId)}</td>
      <td class="sticky-employee-name">${renderNameWithTags(result, activity)}</td>
      <td>${escapeHtml(result.department || result.area || '-')}</td>
      <td>${escapeHtml(getDisplayPosition(result, activity))}</td>
      <td class="metric-cell">${formatScore(result.performance_score)}</td>
      <td class="amount-cell ${isNinetySixHour ? 'highlight-base' : ''}">${formatCurrency(result.performance_base)}</td>
      <td class="metric-cell">${formatPercent(result.performance_ratio)}</td>
      <td class="metric-cell">${formatCoefficient(result.performance_coefficient)}</td>
      <td class="amount-cell">${formatCurrency(result.performance_bonus)}</td>
      <td><button class="btn btn-secondary btn-sm" type="button" onclick="openFinalResultExplanation(${formatJsArg(detailKey)})">计算过程</button></td>
    </tr>
  `;
}

function getFinalResultDetailKey(result) {
  const employeeId = String(result?.employee_id || '');
  const rawIds = Array.isArray(result?.raw_employee_ids) ? result.raw_employee_ids.join('|') : '';
  return `${employeeId}::${rawIds}`;
}

function findFinalResultByDetailKey(detailKey) {
  const results = getWorkbenchResults(getWorkbenchActivity());
  return results.find(result => getFinalResultDetailKey(result) === detailKey);
}

function getFinalResultDetailRows(result) {
  const rows = Array.isArray(result?.calculation_segments) ? result.calculation_segments : [];
  return rows.length ? rows : [{
    period: result?.calc_month || getWorkbenchActivity()?.calc_month || '-',
    reason: result?.calculation_path || '标准绩效基数路径',
    performance_base: result.performance_base,
    performance_ratio: result.performance_ratio,
    performance_coefficient: result.performance_coefficient,
    performance_bonus: result.performance_bonus,
  }];
}

function getFinalBaseCalculationDetails(result) {
  const details = Array.isArray(result?.base_calculation_details)
    ? result.base_calculation_details.filter(Boolean)
    : [];
  if (details.length) return details;
  return [{
    display_label: '',
    path: result?.calculation_path || '标准绩效基数路径',
    performance_base: result?.performance_base,
    components: [{ label: '本月绩效基数', amount: result?.performance_base }],
    note: '该历史结果未保存工时组成，展示已核算的绩效基数。',
  }];
}

function renderBaseComponentFormula(component) {
  const hasHours = component?.hours !== undefined && component?.hours !== null;
  const hasRate = component?.hourly_rate !== undefined && component?.hourly_rate !== null;
  if (!hasHours || !hasRate) return formatCurrency(component?.amount);
  const multiplier = toNumber(component?.multiplier, 1) || 1;
  const multiplierText = Math.abs(multiplier - 1) > 0.0001 ? ` × ${multiplier.toFixed(1)}` : '';
  return `${formatHours(component.hours)} × ${formatCurrency(component.hourly_rate, 4)}${multiplierText} = ${formatCurrency(component.amount)}`;
}

function renderFinalBaseCalculationDetail(result) {
  const details = getFinalBaseCalculationDetails(result);
  return `
    <div class="base-calculation-details">
      ${details.map(detail => {
        const components = Array.isArray(detail.components) ? detail.components : [];
        const heading = [detail.display_label, detail.path].filter(Boolean).join(' · ');
        const hourlyRates = [...new Set(
          components
            .filter(component => component?.hourly_rate !== undefined && component?.hourly_rate !== null)
            .map(component => toNumber(component.hourly_rate).toFixed(4))
        )];
        return `
          <div class="base-calculation-block">
            <div class="calculation-line base-calculation-total">
              <span>${escapeHtml(heading || '绩效基数')}</span>
              <strong>${formatCurrency(detail.performance_base)}</strong>
            </div>
            ${hourlyRates.length ? `
              <div class="calculation-line base-calculation-hourly-rate">
                <span>计算时薪</span>
                <strong>${escapeHtml(hourlyRates.map(rate => formatCurrency(rate, 4)).join(' / '))}</strong>
              </div>
            ` : ''}
            ${components.map(component => `
              <div class="calculation-line base-calculation-component">
                <span>${escapeHtml([component.period, component.label].filter(Boolean).join(' · ') || '基数组成')}</span>
                <strong>${escapeHtml(renderBaseComponentFormula(component))}</strong>
              </div>
            `).join('')}
            ${detail.note ? `<p class="base-calculation-note">${escapeHtml(detail.note)}</p>` : ''}
          </div>
        `;
      }).join('')}
    </div>
  `;
}

function renderBonusCalculationFormula(row, result) {
  if (result?.job_type === 'district_manager' && !row?.is_period_adjustment) {
    return `${formatCurrency(row.performance_base)} × ${formatCoefficient(row.performance_coefficient)} = ${formatCurrency(row.performance_bonus)}`;
  }
  return `${formatCurrency(row.performance_base)} × ${formatPercent(row.performance_ratio)} × ${formatCoefficient(row.performance_coefficient)} = ${formatCurrency(row.performance_bonus)}`;
}

function renderFinalCalculationDetail(result) {
  const detailRows = getFinalResultDetailRows(result);

  return `
    <div class="calculation-lines">
      ${detailRows.map(row => `
        <div class="calculation-line">
          <span>${escapeHtml(row.reason || '-')}</span>
          <strong>${escapeHtml(renderBonusCalculationFormula(row, result))}</strong>
        </div>
      `).join('')}
    </div>
  `;
}

function renderFinalResultExplanation(result) {
  const isNinetySixHour = isNinetySixHourResult(result);
  const isDistrictManager = result?.job_type === 'district_manager';
  const formulaText = renderBonusCalculationFormula(result, result);
  const hasPeriodAdjustment = Math.abs(toNumber(result.period_adjustment)) > 0.0001;
  const fields = [
    ...(hasPeriodAdjustment ? [
      ['系统计算绩效基数', '根据考勤、时薪和适用基数规则计算，不含补发或扣回差额。', formatCurrency(result.system_performance_base)],
      ['Period adjustment', '薪酬组提供的绩效基数差额；正数补发，负数扣回。', formatCurrency(result.period_adjustment)],
    ] : []),
    [hasPeriodAdjustment ? '最终绩效基数' : '绩效基数', '按该员工核算路径得到的本月奖金基数。96工时制员工使用跨周期规则，页面和导出会标红。', formatCurrency(result.performance_base)],
    ['绩效比例', '薪资档案或调薪拆分后适用的月度绩效奖金比例。', formatPercent(result.performance_ratio)],
    ['绩效系数', '由绩效得分或绩效等级换算；有人工补录时以补录值为准。', formatCoefficient(result.performance_coefficient)],
    ['最终奖金', isDistrictManager
      ? '区长固定绩效基数 × 绩效系数。'
      : '绩效基数 × 绩效比例 × 绩效系数，拆分行会先分别计算再合并。', formatCurrency(result.performance_bonus)],
  ];
  return `
    <div class="result-explanation-head">
      <div>
        <strong>${escapeHtml(result.name || '-')}</strong>
        <span>${escapeHtml(result.employee_id || '-')} · ${escapeHtml(getDisplayPosition(result))}</span>
      </div>
      ${isNinetySixHour ? '<em>96工时制</em>' : ''}
    </div>
    <div class="result-explanation-formula">
      <span>本月奖金</span>
      <strong>${escapeHtml(formulaText)}</strong>
    </div>
    <div class="result-explanation-grid">
      ${fields.map(([label, desc, value]) => `
        <div class="result-explanation-field">
          <div>
            <strong>${escapeHtml(label)}</strong>
            <span>${escapeHtml(desc)}</span>
          </div>
          <em>${escapeHtml(value)}</em>
        </div>
      `).join('')}
    </div>
    <div class="result-explanation-section">
      <h4>绩效基数计算</h4>
      ${renderFinalBaseCalculationDetail(result)}
    </div>
    <div class="result-explanation-section">
      <h4>奖金计算过程</h4>
      ${renderFinalCalculationDetail(result)}
    </div>
    ${(result.exceptions || []).length ? `
      <div class="result-explanation-section">
        <h4>需要关注</h4>
        <p>${escapeHtml(result.exceptions.join('；'))}</p>
      </div>
    ` : ''}
  `;
}

function openFinalResultExplanation(detailKey) {
  const result = findFinalResultByDetailKey(detailKey);
  if (!result || !el.finalResultExplanationDialog || !el.finalResultExplanationBody) return;
  el.finalResultExplanationBody.innerHTML = renderFinalResultExplanation(result);
  openModal(el.finalResultExplanationDialog, el.finalResultExplanationDialog.querySelector('.modal-close'));
}

function closeFinalResultExplanation() {
  closeModal(el.finalResultExplanationDialog);
}

function renderStepContent(activity) {
  const stepKey = state.activityStep;
  if (state.activitySectionsLoading.has(activityStepLoadingKey(stepKey, activity))) {
    return `
      <section class="step-section step-data-loading" role="status" aria-live="polite">
        <div class="step-data-loading-copy">
          <strong>正在加载当前步骤</strong>
          <span>只读取本步骤需要的数据，请稍候。</span>
        </div>
        <div class="step-data-loading-track" aria-hidden="true"><span></span></div>
      </section>
    `;
  }
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

function renderAttendanceSectionNav() {
  return `
    <nav class="attendance-section-nav" aria-label="考勤内容定位">
      <button class="attendance-section-nav-button" type="button" aria-controls="attendanceSupplementalSection" title="定位到补充假勤" onclick="scrollToAttendanceSection('attendanceSupplementalSection')">补充假勤</button>
      <button class="attendance-section-nav-button" type="button" aria-controls="attendanceHourlyRateSection" title="定位到周期时薪" onclick="scrollToAttendanceSection('attendanceHourlyRateSection')">周期时薪</button>
      <button class="attendance-section-nav-button" type="button" aria-controls="attendanceWorkHoursSection" title="定位到工时表" onclick="scrollToAttendanceSection('attendanceWorkHoursSection')">工时表</button>
    </nav>
  `;
}

function scrollToAttendanceSection(sectionId) {
  const section = document.getElementById(sectionId);
  if (!section) return;
  const prefersReducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  section.scrollIntoView({
    behavior: prefersReducedMotion ? 'auto' : 'smooth',
    block: 'start',
  });
}

function renderAttendanceStep(activity) {
  return `
    <div class="step-rule-grid">
      ${renderStepMaterials('attendance', activity)}
      ${renderMaintainedRuleList('workHour', activity)}
    </div>
    ${renderNeedsPanel('attendance', activity)}
    <div class="attendance-review-layout">
      ${renderAttendanceSectionNav()}
      <div class="attendance-review-sections">
        <div class="attendance-anchor-target" id="attendanceSupplementalSection">
          ${renderSupplementalLeaveSection(activity)}
        </div>
        <div class="attendance-anchor-target" id="attendanceHourlyRateSection">
          ${renderHourlyRatePolicySection(activity)}
        </div>
        <div class="attendance-anchor-target" id="attendanceWorkHoursSection">
          ${renderAttendanceSummaryTable(activity)}
        </div>
      </div>
    </div>
  `;
}

function renderSalaryStep(activity) {
  return `
    <div class="step-rule-grid">
      ${renderStepMaterials('salary', activity)}
      <div class="salary-support-stack">
        ${renderMaintainedRuleList('fixedBase', activity)}
        ${renderPeriodAdjustmentSection(activity)}
      </div>
    </div>
    ${renderNeedsPanel('salary', activity)}
    ${renderSalaryVerificationReview(activity)}
    ${renderTransferHistoryReview(activity)}
    ${renderSalarySummaryTable(activity)}
  `;
}

function renderPerformanceStep(activity) {
  return `
    <div class="performance-step-grid">
      ${renderStepMaterials('performance', activity)}
      ${renderPerformanceInlineSupplement(activity)}
    </div>
    ${renderNeedsPanel('performance', activity)}
    ${renderPerformanceSummaryTable(activity)}
  `;
}

function renderCheckStep(activity) {
  return `${renderCalculationJobStatus()}${renderNeedsPanel('check', activity)}${renderCheckPreview(activity)}`;
}

function renderCalculationJobStatus() {
  const job = state.calculationJobStatus;
  if (!job?.status) return '';
  const isBusy = ['queued', 'processing'].includes(job.status) && !job.recoverable;
  if (isBusy) {
    const label = job.stage === 'queued' || job.status === 'queued'
      ? '核算任务正在排队'
      : '正在核算绩效奖金';
    return `
      <section class="step-section step-data-loading" role="status" aria-live="polite">
        <div class="step-data-loading-copy">
          <strong>${escapeHtml(label)}</strong>
          <span>${escapeHtml(job.message || '任务在后台执行，离开页面后也可继续。')}</span>
        </div>
        <div class="step-data-loading-track" aria-hidden="true"><span></span></div>
      </section>
    `;
  }
  if (job.status === 'failed' || job.recoverable) {
    return `
      <section class="step-section step-data-loading" role="alert">
        <div class="step-data-loading-copy">
          <strong>核算任务未完成</strong>
          <span>${escapeHtml(job.error || job.message || '可重试继续核算。')}</span>
        </div>
        ${job.canRetry || job.recoverable
          ? '<div><button class="btn btn-primary btn-sm" type="button" onclick="resumeFbuCalculationJob()">重试核算</button></div>'
          : ''}
      </section>
    `;
  }
  return '';
}

function renderStepHeader(step, activity) {
  const status = getStepStatus(step?.key || '', activity);
  return `
    <div class="step-header-block">
      <div class="step-topline">
        <div>
          <h3>${escapeHtml(step?.label || '')}</h3>
          <p class="step-topline-status ${status === '需要处理' ? 'warning' : status === '已完成' ? 'success' : ''}">${escapeHtml(status)}</p>
        </div>
        ${renderStepHelp(step?.key || '')}
      </div>
      ${renderStepInfoStrip(step?.key || '', activity)}
    </div>
  `;
}

// ═══ Notification ═══

function showNotification(message, type = 'info', options = {}) {
  if (type === 'success') return;
  const toastConfig = {
    error: { title: '操作失败', icon: '!' },
    warning: { title: '需要注意', icon: '!' },
    info: { title: '提示', icon: 'i' },
  };
  const config = toastConfig[type] || toastConfig.info;
  const title = options.title || config.title;
  const duration = options.duration ?? (type === 'error' ? null : 3600);
  const region = el.toastRegion || document.getElementById('toastRegion');
  if (!region) return;
  const toastKey = `${type}|${title}|${message}`;
  const duplicateToast = [...region.querySelectorAll('.toast')]
    .find(item => item.dataset.toastKey === toastKey && !item.classList.contains('is-leaving'));
  if (duplicateToast) return;

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.dataset.toastKey = toastKey;
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
  navigateTo('activities');
});
