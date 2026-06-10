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
};

// ═══ API Base ═══

const API_BASE = '/api/fbu-performance';

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

  // Pages
  pages: {
    activities: document.getElementById('pageActivities'),
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

// ═══ App Dialog ═══

let appDialogResolve = null;
let appDialogValidate = null;

function getDefaultCalcMonth() {
  const date = new Date();
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  return `${year}-${month}`;
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
      el.appDialogField.hidden = false;
      el.appDialogInputLabel.textContent = input.label || '';
      el.appDialogInput.placeholder = input.placeholder || '';
      el.appDialogInput.value = input.value || '';
      el.appDialogInputHelp.textContent = input.help || '';
      el.appDialogInput.inputMode = input.inputMode || 'text';
      el.appDialogInput.maxLength = input.maxLength || 64;
    } else {
      el.appDialogField.hidden = true;
      el.appDialogInput.value = '';
      el.appDialogInputHelp.textContent = '';
    }

    el.appDialog.classList.add('active');

    setTimeout(() => {
      if (input) {
        el.appDialogInput.focus();
        el.appDialogInput.select();
      } else {
        el.btnConfirmAppDialog.focus();
      }
    }, 0);
  });
}

function closeAppDialog(result) {
  el.appDialog.classList.remove('active');
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
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && el.appDialog?.classList.contains('active')) {
    closeAppDialog({ confirmed: false });
  }
});

// ═══ Navigation ═══

function navigateTo(page) {
  state.currentPage = page;

  // Update nav items
  el.navItems.forEach(item => {
    item.classList.toggle('active', item.dataset.page === page);
  });

  // Show/hide pages
  Object.keys(el.pages).forEach(key => {
    el.pages[key].hidden = key !== page;
  });

  // Update title
  const titles = {
    activities: { title: 'FBU美洲绩效核算', subtitle: '月度活动管理' },
    attendance: { title: '考勤汇总', subtitle: state.currentActivity?.calc_month || '' },
    salary: { title: '薪资匹配', subtitle: state.currentActivity?.calc_month || '' },
    performance: { title: '绩效明细', subtitle: state.currentActivity?.calc_month || '' },
    results: { title: '核算结果', subtitle: state.currentActivity?.calc_month || '' },
  };

  el.pageTitle.textContent = titles[page].title;
  el.pageSubtitle.textContent = titles[page].subtitle;

  // Load page data
  if (page === 'activities') {
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

// ═══ Activities ═══

async function loadActivities() {
  try {
    const data = await apiJson(`${API_BASE}/runs`);

    state.activities = data.runs || [];
    renderActivities();
    updateActivityKPIs();
  } catch (error) {
    console.error('加载活动列表失败:', error);
  }
}

function renderActivities() {
  el.activitiesBody.innerHTML = state.activities.map(activity => {
    const statusClass = activity.status === 'completed' ? 'success' :
                       activity.status === 'failed' ? 'danger' : 'warning';
    const statusText = activity.status === 'completed' ? '已完成' :
                      activity.status === 'failed' ? '失败' : '进行中';
    const progress = `${activity.current_step || 0}/4`;

    return `
      <tr>
        <td><strong>${escapeHtml(activity.calc_month)}</strong></td>
        <td><span class="status-badge ${statusClass}">${statusText}</span></td>
        <td>${progress}</td>
        <td>${activity.total_employees || '-'}</td>
        <td>${activity.total_bonus ? '$' + activity.total_bonus.toLocaleString() : '-'}</td>
        <td>${escapeHtml(new Date(activity.created_at).toLocaleDateString())}</td>
        <td>
          <button class="btn btn-secondary btn-sm" onclick="enterActivity('${escapeHtml(activity.run_id)}')">进入</button>
          <button class="btn btn-danger btn-sm" onclick="deleteActivity('${escapeHtml(activity.run_id)}')">删除</button>
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

// ═══ Enter Activity ═══

async function enterActivity(activityId, options = {}) {
  const { preservePage = false } = options;

  try {
    const activity = await apiJson(`${API_BASE}/runs/${activityId}`);

    state.currentActivity = activity;
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
      label: '核算月份',
      value: state.currentActivity?.calc_month || getDefaultCalcMonth(),
      placeholder: '2026-04',
      help: '格式：YYYY-MM',
      maxLength: 7,
      inputMode: 'numeric',
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
  el.uploadModal.classList.add('active');
}

function closeUploadModal() {
  if (uploadStage === 'uploading') return;
  el.uploadModal.classList.remove('active');
  uploadType = '';
  uploadFile = null;
  uploadStage = 'select';
}

el.btnCloseUploadModal.addEventListener('click', closeUploadModal);
el.btnCancelUpload.addEventListener('click', closeUploadModal);

el.uploadZone.addEventListener('click', () => {
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
el.btnDownloadAdjustmentsTemplate?.addEventListener('click', () => {
  const link = document.createElement('a');
  link.href = `${API_BASE}/templates/adjustments/download`;
  link.download = 'FBU调薪转正拆分表模板.xlsx';
  link.click();
});

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
        <span class="summary-stat-value">${summary.matched_salary_count}/${summary.attendance_count}</span>
      </div>
      <div class="summary-stat">
        <span class="summary-stat-label">绩效匹配</span>
        <span class="summary-stat-value">${summary.matched_performance_count}/${summary.attendance_count}</span>
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

function renderImportToolbar({ title, subtitle, filters, filterFn, resetFn }) {
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
              <input type="text" id="${escapeHtml(filter.id)}" placeholder="${escapeHtml(filter.placeholder)}" oninput="${escapeHtml(filterFn)}()">
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

function renderImportTable(markup) {
  return `
    <div class="import-table-card">
      <div class="data-table-container">
        ${markup}
      </div>
    </div>
  `;
}

const employeeFilters = {
  attendance: [
    { id: 'filterAttendanceId', label: '工号', placeholder: 'zt0000000' },
    { id: 'filterAttendanceName', label: '姓名', placeholder: '员工姓名' },
    { id: 'filterAttendanceArea', label: '划分区域', placeholder: '区域' },
    { id: 'filterAttendanceDept', label: '部门', placeholder: '部门全称' },
  ],
  salary: [
    { id: 'filterSalaryId', label: '工号', placeholder: 'zt0000000' },
    { id: 'filterSalaryName', label: '姓名', placeholder: '员工姓名' },
    { id: 'filterSalaryArea', label: '划分区域', placeholder: '区域' },
    { id: 'filterSalaryDept', label: '部门', placeholder: '部门全称' },
  ],
  performance: [
    { id: 'filterPerfId', label: '工号', placeholder: 'zt0000000' },
    { id: 'filterPerfName', label: '姓名', placeholder: '员工姓名' },
    { id: 'filterPerfArea', label: '划分区域', placeholder: '区域' },
    { id: 'filterPerfDept', label: '部门', placeholder: '部门全称' },
  ],
};

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
          ${employees.map(emp => `
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
          `).join('')}
        </tbody>
      </table>
      `)}
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
  const summary = state.salaryData.summary;

  el.salaryContent.innerHTML = `
    ${renderDiagnosticsPanel()}
    ${renderImportResultNote('salary')}
    <div class="import-workbench">
      ${renderImportSummary([
        { label: '薪资档案人数', value: summary.total_employees, mono: true },
        { label: '有效时薪', value: summary.valid_hourly_count ?? summary.total_employees, mono: true, tone: 'success' },
        { label: '0时薪', value: summary.zero_hourly_count ?? 0, mono: true, tone: (summary.zero_hourly_count ?? 0) ? 'danger' : '' },
        { label: '有效平均时薪', value: formatCurrency(summary.avg_hourly_rate), mono: true },
      ])}
      ${renderImportToolbar({
        title: '筛选薪资档案',
        subtitle: '这里展示本次上传薪资档案解析出的员工，不代表最终参与核算人数。',
        filters: employeeFilters.salary,
        filterFn: 'filterSalaryData',
        resetFn: 'resetSalaryFilter',
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
          </tr>
        </thead>
        <tbody>
          ${employees.map(emp => `
            <tr data-id="${escapeHtml(emp.employee_id)}"
                data-name="${escapeHtml(emp.name || '')}"
                data-area="${escapeHtml(emp.area || '')}"
                data-dept="${escapeHtml(emp.department || '')}">
              <td>${escapeHtml(emp.employee_id)}</td>
              <td>${escapeHtml(emp.name || '-')}</td>
              <td>${escapeHtml(emp.area || '-')}</td>
              <td>${escapeHtml(emp.department || '-')}</td>
              <td>${formatCurrency(emp.hourly_rate)}</td>
              <td>${formatPercent(emp.ratio)}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
      `)}
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

  const employees = state.performanceData.employees;
  const summary = state.performanceData.summary;
  const adjustmentSummary = state.adjustmentData?.summary;
  const performanceSummaryItems = [
    { label: '绩效员工数', value: summary.total_employees, mono: true },
    { label: '平均得分', value: toNumber(summary.avg_score).toFixed(2), mono: true },
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
          </tr>
        </thead>
        <tbody>
          ${employees.map(emp => `
            <tr data-id="${escapeHtml(emp.employee_id)}"
                data-name="${escapeHtml(emp.name || '')}"
                data-area="${escapeHtml(emp.area || '')}"
                data-dept="${escapeHtml(emp.department || '')}">
              <td>${escapeHtml(emp.employee_id)}</td>
              <td>${escapeHtml(emp.name || '-')}</td>
              <td>${escapeHtml(emp.area || '-')}</td>
              <td>${escapeHtml(emp.department || '-')}</td>
              <td>${formatJobType(emp.job_type)}</td>
              <td>${emp.score !== null ? toNumber(emp.score).toFixed(2) : '-'}</td>
              <td>${escapeHtml(emp.level || '-')}</td>
              <td>${emp.coefficient !== null ? formatCoefficient(emp.coefficient) : '-'}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
      `)}
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
  return `
    <div class="result-toolbar">
      <div>
        <div class="result-toolbar-title">核算明细</div>
        <div class="result-filter-grid">
          <div class="filter-field">
            <label for="filterResultsId">工号</label>
            <input type="text" id="filterResultsId" placeholder="zt0000000" oninput="filterResultsData()">
          </div>
          <div class="filter-field">
            <label for="filterResultsName">姓名</label>
            <input type="text" id="filterResultsName" placeholder="员工姓名" oninput="filterResultsData()">
          </div>
          <div class="filter-field">
            <label for="filterResultsArea">划分区域</label>
            <input type="text" id="filterResultsArea" placeholder="区域" oninput="filterResultsData()">
          </div>
          <div class="filter-field">
            <label for="filterResultsDept">部门</label>
            <input type="text" id="filterResultsDept" placeholder="部门全称" oninput="filterResultsData()">
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

function renderBonusResultTable(results) {
  return `
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
          ${results.map(renderBonusResultRow).join('')}
        </tbody>
      </table>
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
      <td>${exceptions.length ? `<span class="exception-chip" title="${exceptionTitle}">${exceptions.length}项</span>` : '<span class="muted-cell">-</span>'}</td>
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
  const totalBonus = results.reduce((sum, r) => sum + toNumber(r.performance_bonus), 0);
  const avgBonus = results.length ? totalBonus / results.length : 0;
  const exceptionCount = results.filter(r => (r.exceptions || []).length > 0).length;

  el.resultsContent.innerHTML = `
    ${renderDiagnosticsPanel()}
    <div class="results-workbench">
      ${renderResultsToolbar()}
      ${renderBonusResultTable(results)}
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
    el.calcChainModal.classList.add('active');
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

  el.calcChainModal.classList.add('active');
}

el.btnCloseCalcChainModal?.addEventListener('click', () => {
  el.calcChainModal.classList.remove('active');
});

el.btnCloseCalcChain?.addEventListener('click', () => {
  el.calcChainModal.classList.remove('active');
});

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

function filterAttendanceData() {
  const filterId = document.getElementById('filterAttendanceId')?.value.toLowerCase() || '';
  const filterName = document.getElementById('filterAttendanceName')?.value.toLowerCase() || '';
  const filterArea = document.getElementById('filterAttendanceArea')?.value.toLowerCase() || '';
  const filterDept = document.getElementById('filterAttendanceDept')?.value.toLowerCase() || '';

  const table = document.getElementById('attendanceTable');
  if (!table) return;

  const rows = table.querySelectorAll('tbody tr');
  rows.forEach(row => {
    const id = (row.dataset.id || '').toLowerCase();
    const name = (row.dataset.name || '').toLowerCase();
    const area = (row.dataset.area || '').toLowerCase();
    const dept = (row.dataset.dept || '').toLowerCase();

    const matchId = !filterId || id.includes(filterId);
    const matchName = !filterName || name.includes(filterName);
    const matchArea = !filterArea || area.includes(filterArea);
    const matchDept = !filterDept || dept.includes(filterDept);

    row.style.display = (matchId && matchName && matchArea && matchDept) ? '' : 'none';
  });
}

function resetAttendanceFilter() {
  document.getElementById('filterAttendanceId').value = '';
  document.getElementById('filterAttendanceName').value = '';
  document.getElementById('filterAttendanceArea').value = '';
  document.getElementById('filterAttendanceDept').value = '';
  filterAttendanceData();
}

// ═══ Salary Filter ═══

function filterSalaryData() {
  const filterId = document.getElementById('filterSalaryId')?.value.toLowerCase() || '';
  const filterName = document.getElementById('filterSalaryName')?.value.toLowerCase() || '';
  const filterArea = document.getElementById('filterSalaryArea')?.value.toLowerCase() || '';
  const filterDept = document.getElementById('filterSalaryDept')?.value.toLowerCase() || '';

  const table = document.getElementById('salaryTable');
  if (!table) return;

  const rows = table.querySelectorAll('tbody tr');
  rows.forEach(row => {
    const id = (row.dataset.id || '').toLowerCase();
    const name = (row.dataset.name || '').toLowerCase();
    const area = (row.dataset.area || '').toLowerCase();
    const dept = (row.dataset.dept || '').toLowerCase();

    const matchId = !filterId || id.includes(filterId);
    const matchName = !filterName || name.includes(filterName);
    const matchArea = !filterArea || area.includes(filterArea);
    const matchDept = !filterDept || dept.includes(filterDept);

    row.style.display = (matchId && matchName && matchArea && matchDept) ? '' : 'none';
  });
}

function resetSalaryFilter() {
  document.getElementById('filterSalaryId').value = '';
  document.getElementById('filterSalaryName').value = '';
  document.getElementById('filterSalaryArea').value = '';
  document.getElementById('filterSalaryDept').value = '';
  filterSalaryData();
}

// ═══ Performance Filter ═══

function filterPerformanceData() {
  const filterId = document.getElementById('filterPerfId')?.value.toLowerCase() || '';
  const filterName = document.getElementById('filterPerfName')?.value.toLowerCase() || '';
  const filterArea = document.getElementById('filterPerfArea')?.value.toLowerCase() || '';
  const filterDept = document.getElementById('filterPerfDept')?.value.toLowerCase() || '';

  const table = document.getElementById('performanceTable');
  if (!table) return;

  const rows = table.querySelectorAll('tbody tr');
  rows.forEach(row => {
    const id = (row.dataset.id || '').toLowerCase();
    const name = (row.dataset.name || '').toLowerCase();
    const area = (row.dataset.area || '').toLowerCase();
    const dept = (row.dataset.dept || '').toLowerCase();

    const matchId = !filterId || id.includes(filterId);
    const matchName = !filterName || name.includes(filterName);
    const matchArea = !filterArea || area.includes(filterArea);
    const matchDept = !filterDept || dept.includes(filterDept);

    row.style.display = (matchId && matchName && matchArea && matchDept) ? '' : 'none';
  });
}

function resetPerformanceFilter() {
  document.getElementById('filterPerfId').value = '';
  document.getElementById('filterPerfName').value = '';
  document.getElementById('filterPerfArea').value = '';
  document.getElementById('filterPerfDept').value = '';
  filterPerformanceData();
}

// ═══ Results Filter ═══

function filterResultsData() {
  const filterId = document.getElementById('filterResultsId')?.value.toLowerCase() || '';
  const filterName = document.getElementById('filterResultsName')?.value.toLowerCase() || '';
  const filterArea = document.getElementById('filterResultsArea')?.value.toLowerCase() || '';
  const filterDept = document.getElementById('filterResultsDept')?.value.toLowerCase() || '';

  const table = document.getElementById('resultsTable');
  if (!table) return;

  const rows = table.querySelectorAll('tbody tr');
  rows.forEach(row => {
    const id = (row.dataset.id || '').toLowerCase();
    const name = (row.dataset.name || '').toLowerCase();
    const area = (row.dataset.area || '').toLowerCase();
    const dept = (row.dataset.dept || '').toLowerCase();

    const matchId = !filterId || id.includes(filterId);
    const matchName = !filterName || name.includes(filterName);
    const matchArea = !filterArea || area.includes(filterArea);
    const matchDept = !filterDept || dept.includes(filterDept);

    row.style.display = (matchId && matchName && matchArea && matchDept) ? '' : 'none';
  });
}

function resetResultsFilter() {
  document.getElementById('filterResultsId').value = '';
  document.getElementById('filterResultsName').value = '';
  document.getElementById('filterResultsArea').value = '';
  document.getElementById('filterResultsDept').value = '';
  filterResultsData();
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
  const duration = options.duration ?? (type === 'error' ? 5200 : 3600);
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
  setTimeout(dismiss, duration);
}

// ═══ Init ═══

document.addEventListener('DOMContentLoaded', () => {
  loadBaseRoster();
  loadActivities();
});
