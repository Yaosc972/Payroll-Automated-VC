/**
 * Domestic Labor Payroll - 西格玛工作台
 * 劳务工薪酬核算前端交互
 */

const state = {
  selectedEngines: [],
  attendanceMonth: '',
  payrollFile: null,
  payrollFiles: [],
  currentRun: null,
  currentResults: [],
  currentResultsRunId: '',
  view: 'home',
  canbuBatches: [],
  activeCanbuBatchId: '',
  activeCanbuOperation: null,
  activeWorkbenchSubject: 'canbu',
  activeSubject: 'all',
  resultSearch: '',
  reviewStatusFilter: 'all',
  amountFilter: 'all',
  canbuRegionFilter: 'all',
  canbuPage: 1,
  canbuPageSize: 50,
  canbuSearchComposing: false,
  canbuBatchPickerYear: new Date().getFullYear(),
  rulePackage: null,
  rulePackageLoading: false,
  nightShiftConfigs: {},
  nightShiftConfigLoading: {},
  activeRuleCategory: 'all',
  activeRuleSubject: 'canbu',
  pollTimer: null,
  pollRequestInFlight: false,
  pollRetryCount: 0,
  pollMaxRetries: 400, // 400 × 1.5s = 10 min
  exportInProgress: false,
};

const CANBU_BATCH_STORAGE_KEY = 'domesticLabor.canbuBatches.v1';
const CANBU_STEPS = [
  { key: 'upload', label: '数据上传' },
  { key: 'fields', label: '字段检查' },
  { key: 'results', label: '餐补核算' },
];

const SUBJECT_WORKBENCH = {
  quanqinjiang: {
    name: '全勤奖',
    batchNoun: '全勤奖批次',
    resultField: 'quanqinjiang',
    totalField: 'total_quanqinjiang',
    uploadTitle: '全勤奖数据 Excel',
    uploadDescription: '全勤奖核算需要月考勤中的三档迟到次数；日考勤用于识别月初入职前是否存在工作日。',
  },
  canbu: {
    name: '餐补',
    batchNoun: '餐补批次',
    resultField: 'canbu',
    totalField: 'total_canbu',
    uploadTitle: '餐补数据 Excel',
    uploadDescription: '餐补核算需要日考勤和月考勤数据。文件内可包含多张工作表。',
  },
  waisu_butie: {
    name: '外宿补贴',
    batchNoun: '外宿补贴批次',
    resultField: 'waisu_butie',
    totalField: 'total_waisu_butie',
    uploadTitle: '外宿补贴数据 Excel',
    uploadDescription: '外宿补贴核算需要月考勤、日考勤和住宿名单。文件内可包含多张工作表。',
  },
  gonglingjiang: {
    name: '工龄奖',
    batchNoun: '工龄奖批次',
    resultField: 'gonglingjiang',
    totalField: 'total_gonglingjiang',
    uploadTitle: '工龄奖数据 Excel',
    uploadDescription: '工龄奖核算需要月考勤数据；识别到第四纵队时要求确认揽收线工龄奖名单。',
  },
  gangwei_butie: {
    name: '岗位补贴',
    batchNoun: '岗位补贴批次',
    resultField: 'gangwei_butie',
    totalField: 'total_gangwei_butie',
    uploadTitle: '岗位补贴月考勤 Excel',
    uploadDescription: '岗位补贴只需要月考勤，标准以2026年7月确认规则为依据；按地区、岗位名称、排班天数和九类缺勤字段计算，并用实际在职工作日天数自动计算入离职缺勤时数，职级不参与。',
  },
  gaowen_butie: {
    name: '高温补贴',
    batchNoun: '高温补贴批次',
    resultField: 'gaowen_butie',
    totalField: 'total_gaowen_butie',
    uploadTitle: '高温补贴月考勤、日考勤与测温登记 Excel',
    uploadDescription: '高温补贴核算需要月考勤、日考勤和高温测温登记；可上传一个多Sheet文件，也可上传三份拆分文件。',
  },
  yeban_butie: {
    name: '夜班补贴',
    batchNoun: '夜班补贴批次',
    resultField: 'yeban_butie',
    totalField: 'total_yeban_butie',
    uploadTitle: '夜班补贴月考勤与日考勤 Excel',
    uploadDescription: '夜班补贴核算需要月考勤和日考勤。班次休息使用平台基线并支持当月修改；晋江额外排除人员按月确认。',
  },
};

const ENGINE_META = {
  quanqinjiang: {
    name: '全勤奖',
    desc: '100元/人/月，迟到豁免按6分钟内或6-20分钟二选一',
    icon: 'Q',
    color: 'brand',
  },
  canbu: {
    name: '餐补',
    desc: '19元/天，封顶500元/月，按出勤天数计算',
    icon: 'C',
    color: 'info',
  },
  waisu_butie: {
    name: '外宿补贴',
    desc: '150元/月，按出勤、请假等条件计算',
    icon: 'W',
    color: 'warning',
  },
  gonglingjiang: {
    name: '工龄奖',
    desc: '按工龄阶梯计算，每年递增',
    icon: 'G',
    color: 'violet',
  },
  gangwei_butie: {
    name: '岗位补贴',
    desc: '按岗位标准和56小时缺勤门槛折算，女神假1天按8小时',
    icon: 'P',
    color: 'warning',
  },
  gaowen_butie: {
    name: '高温补贴',
    desc: '同仓同日同班次达到33℃后按实际出勤折算',
    icon: 'H',
    color: 'warning',
  },
  yeban_butie: {
    name: '夜班补贴',
    desc: '22:00至次日08:00，3元/小时，单日封顶25元',
    icon: 'N',
    color: 'info',
  },
};

const DEFAULT_COLLECTION_SENIORITY_ROSTER = [
  { employeeId: 'OWHN2313', employeeName: '何俊伟' },
  { employeeId: 'OWHN0424', employeeName: '韩录阳' },
  { employeeId: 'OWHN6172', employeeName: '邓军洋' },
  { employeeId: 'OWHN0474', employeeName: '曾威' },
  { employeeId: 'OWHN2248', employeeName: '赖志强' },
  { employeeId: 'OWHN6887', employeeName: '梁嘉恩' },
  { employeeId: 'OWHN10141', employeeName: '谢丹' },
  { employeeId: 'OWHN10605', employeeName: '蒋治云' },
  { employeeId: 'OWHN10863', employeeName: '黄华' },
  { employeeId: 'OWHN10892', employeeName: '黄宝强' },
  { employeeId: 'OWHN11388', employeeName: '夏雷' },
  { employeeId: 'OWHN11405', employeeName: '陈鹏宇' },
];

function normalizeCollectionRoster(value) {
  if (!Array.isArray(value)) return [];
  const roster = [];
  const seen = new Set();
  value.forEach((item) => {
    const employeeId = String(typeof item === 'string' ? item : (item?.employeeId || item?.employee_id || '')).trim();
    const employeeName = String(typeof item === 'string' ? '' : (item?.employeeName || item?.employee_name || '')).trim();
    if (!employeeId || seen.has(employeeId)) return;
    seen.add(employeeId);
    roster.push({ employeeId, employeeName });
  });
  return roster;
}

function renderCollectionRosterRow(item = {}) {
  return `
    <tr data-collection-roster-row>
      <td><input class="dl-roster-input" data-roster-field="employeeId" value="${escapeHtml(item.employeeId || '')}" placeholder="OWHN0001" aria-label="人员工号"></td>
      <td>
        <div class="dl-roster-name-cell">
          <input class="dl-roster-input" data-roster-field="employeeName" value="${escapeHtml(item.employeeName || '')}" placeholder="姓名" aria-label="人员姓名">
          <button class="dl-icon-btn dl-roster-remove" type="button" title="删除人员" aria-label="删除人员">×</button>
        </div>
      </td>
    </tr>
  `;
}

function renderCollectionRosterRows(value) {
  const roster = normalizeCollectionRoster(value);
  return (roster.length ? roster : [{}]).map(renderCollectionRosterRow).join('');
}

function collectCollectionRosterTable() {
  return normalizeCollectionRoster([...document.querySelectorAll('[data-collection-roster-row]')].map(row => ({
    employeeId: row.querySelector('[data-roster-field="employeeId"]')?.value || '',
    employeeName: row.querySelector('[data-roster-field="employeeName"]')?.value || '',
  })));
}

function loadCanbuBatches() {
  try {
    const raw = window.localStorage.getItem(CANBU_BATCH_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    state.canbuBatches = Array.isArray(parsed)
      ? parsed.map(batch => ({
          ...batch,
          subject: batch.subject || 'canbu',
          collectionSeniorityRoster: batch.subject === 'gonglingjiang'
            ? normalizeCollectionRoster(
                Array.isArray(batch.collectionSeniorityRoster)
                  ? batch.collectionSeniorityRoster
                  : (Array.isArray(batch.hrbpList) ? batch.hrbpList : DEFAULT_COLLECTION_SENIORITY_ROSTER)
              )
            : [],
        }))
      : [];
  } catch {
    state.canbuBatches = [];
  }
}

function saveCanbuBatches() {
  window.localStorage.setItem(CANBU_BATCH_STORAGE_KEY, JSON.stringify(state.canbuBatches));
}

function createCanbuBatch(month, name, subject = state.activeWorkbenchSubject) {
  const now = new Date().toISOString();
  const batch = {
    id: `${subject}-${Date.now()}`,
    subject,
    month,
    name: name || `${month} ${getWorkbenchConfig(subject).name}初算`,
    status: '草稿',
    employeeCount: 0,
    payableTotal: 0,
    exceptionCount: 0,
    exportFileName: '',
    exportedAt: '',
    runId: '',
    collectionSeniorityRoster: subject === 'gonglingjiang'
      ? DEFAULT_COLLECTION_SENIORITY_ROSTER.map(item => ({ ...item }))
      : [],
    createdAt: now,
    updatedAt: now,
  };
  state.canbuBatches.unshift(batch);
  state.activeCanbuBatchId = batch.id;
  saveCanbuBatches();
  return batch;
}

function getActiveCanbuBatch() {
  return state.canbuBatches.find((batch) => batch.id === state.activeCanbuBatchId) || null;
}

function getWorkbenchConfig(subject = state.activeWorkbenchSubject) {
  return SUBJECT_WORKBENCH[subject] || SUBJECT_WORKBENCH.canbu;
}

function getActiveWorkbenchSubject() {
  return getActiveCanbuBatch()?.subject || state.activeWorkbenchSubject || 'canbu';
}

function getCanbuBatchById(batchId) {
  if (!batchId) return null;
  return state.canbuBatches.find((batch) => batch.id === batchId) || null;
}

function getCanbuBatchByRunId(runId) {
  if (!runId) return null;
  return state.canbuBatches.find((batch) => batch.runId === runId) || null;
}

function getCanbuBatch({ runId = '', batchId = '' } = {}) {
  return getCanbuBatchByRunId(runId) || getCanbuBatchById(batchId);
}

function updateCanbuBatch(patch, options = {}) {
  const batch = getCanbuBatch(options);
  if (!batch) return null;
  Object.assign(batch, patch, { updatedAt: new Date().toISOString() });
  saveCanbuBatches();
  return batch;
}

function updateActiveCanbuBatch(patch) {
  return updateCanbuBatch(patch, { batchId: state.activeCanbuBatchId });
}

function clearCurrentRunState({ clearFile = false } = {}) {
  stopPolling();
  state.currentRun = null;
  state.currentResults = [];
  state.currentResultsRunId = '';
  if (clearFile) {
    state.payrollFile = null;
    state.payrollFiles = [];
  }
  resetReportLink();
}

function resetCanbuFilters() {
  state.resultSearch = '';
  state.reviewStatusFilter = 'all';
  state.amountFilter = 'all';
  state.canbuRegionFilter = 'all';
  state.canbuPage = 1;
}

// ── Element references ──
const el = {
  // KPI
  kpiTotalVal: document.querySelector('#kpiTotalVal'),
  kpiProcessedVal: document.querySelector('#kpiProcessedVal'),
  kpiQuanqinVal: document.querySelector('#kpiQuanqinVal'),
  kpiCanbuVal: document.querySelector('#kpiCanbuVal'),
  kpiWaisuVal: document.querySelector('#kpiWaisuVal'),
  kpiGonglingVal: document.querySelector('#kpiGonglingVal'),
  kpiWarningsVal: document.querySelector('#kpiWarningsVal'),
  kpiGrandVal: document.querySelector('#kpiGrandVal'),
  batchNameText: document.querySelector('#batchNameText'),
  batchStatusText: document.querySelector('#batchStatusText'),

  // Run badge
  chromeRunBadge: document.querySelector('#chromeRunBadge'),
  chromeRunLabel: document.querySelector('#chromeRunLabel'),

  // Wizard
  engineCardGrid: document.querySelector('#engineCardGrid'),
  attendanceMonth: document.querySelector('#attendanceMonth'),
  btnToStep2: document.querySelector('#btnToStep2'),
  engineStatus: document.querySelector('#engineStatus'),
  payrollFile: document.querySelector('#payrollFile'),
  payrollFileName: document.querySelector('#payrollFileName'),
  fileUploadZone: document.querySelector('#fileUploadZone'),
  templateLinks: document.querySelector('#templateLinks'),
  filePassword: document.querySelector('#filePassword'),
  btnToStep3: document.querySelector('#btnToStep3'),
  uploadStatus: document.querySelector('#uploadStatus'),
  btnToStep4: document.querySelector('#btnToStep4'),
  confirmEngines: document.querySelector('#confirmEngines'),
  confirmMonth: document.querySelector('#confirmMonth'),
  confirmFile: document.querySelector('#confirmFile'),
  submitStatus: document.querySelector('#submitStatus'),
  btnSubmitTask: document.querySelector('#btnSubmitTask'),

  // Workspace
  workspaceEmpty: document.querySelector('#workspaceEmpty'),
  taskStatusSection: document.querySelector('#taskStatusSection'),
  taskStatusSub: document.querySelector('#taskStatusSub'),
  taskStatusCard: document.querySelector('#taskStatusCard'),
  btnRefreshStatus: document.querySelector('#btnRefreshStatus'),
  btnExport: document.querySelector('#btnExport'),
  resultsSection: document.querySelector('#resultsSection'),
  resultsTable: document.querySelector('#resultsTable'),
  engineSummarySection: document.querySelector('#engineSummarySection'),
  engineSummaryGrid: document.querySelector('#engineSummaryGrid'),
  exceptionQueue: document.querySelector('#exceptionQueue'),
  subjectTabs: document.querySelector('#subjectTabs'),
  payrollShell: document.querySelector('#payrollShell'),
  btnToggleRail: document.querySelector('#btnToggleRail'),
  btnToggleAside: document.querySelector('#btnToggleAside'),
  resultSearchInput: document.querySelector('#resultSearchInput'),
  reviewStatusFilter: document.querySelector('#reviewStatusFilter'),
  amountFilter: document.querySelector('#amountFilter'),
  canbuRegionFilter: document.querySelector('#canbuRegionFilter'),
  resultCountText: document.querySelector('#resultCountText'),
  canbuPagination: document.querySelector('#canbuPagination'),
  // New task 1 views
  subjectHomeView: document.querySelector('#subjectHomeView'),
  rulePackageView: document.querySelector('#rulePackageView'),
  canbuBatchListView: document.querySelector('#canbuBatchListView'),
  canbuWorkbenchView: document.querySelector('#canbuWorkbenchView'),
  subjectCardGrid: document.querySelector('#subjectCardGrid'),
  recentBatchTable: document.querySelector('#recentBatchTable'),
  canbuBatchTable: document.querySelector('#canbuBatchTable'),
  subjectBatchListTitle: document.querySelector('#subjectBatchListTitle'),
  subjectBatchListSub: document.querySelector('#subjectBatchListSub'),
  canbuWorkbenchRoot: document.querySelector('#canbuWorkbenchRoot'),
  btnBackHome: document.querySelector('#btnBackHome'),
  navSubjectHome: document.querySelector('#navSubjectHome'),
  navBatchList: document.querySelector('#navBatchList'),
  navRulePackage: document.querySelector('#navRulePackage'),
  rulePackageEntry: document.querySelector('#rulePackageEntry'),
  btnBackFromRules: document.querySelector('#btnBackFromRules'),
  rulePackageTitle: document.querySelector('#rulePackageTitle'),
  rulePackageScope: document.querySelector('#rulePackageScope'),
  rulePackageVersionSelect: document.querySelector('#rulePackageVersionSelect'),
  rulePackageSummary: document.querySelector('#rulePackageSummary'),
  rulePackageCategoryTabs: document.querySelector('#rulePackageCategoryTabs'),
  rulePackageSubjectTabs: document.querySelector('#rulePackageSubjectTabs'),
  rulePackageContent: document.querySelector('#rulePackageContent'),
  rulePackageHistory: document.querySelector('#rulePackageHistory'),
  canbuBatchModal: document.querySelector('#canbuBatchModal'),
  canbuBatchModalTitle: document.querySelector('#canbuBatchModalTitle'),
  subjectBatchModalSub: document.querySelector('#subjectBatchModalSub'),
  canbuBatchMonth: document.querySelector('#canbuBatchMonth'),
  canbuBatchYear: document.querySelector('#canbuBatchYear'),
  canbuBatchMonthGrid: document.querySelector('#canbuBatchMonthGrid'),
  btnCanbuBatchPrevYear: document.querySelector('#btnCanbuBatchPrevYear'),
  btnCanbuBatchNextYear: document.querySelector('#btnCanbuBatchNextYear'),
  btnNewCanbuBatch: document.querySelector('#btnNewCanbuBatch'),
  btnCancelCanbuBatch: document.querySelector('#btnCancelCanbuBatch'),
  btnConfirmCanbuBatch: document.querySelector('#btnConfirmCanbuBatch'),
  explainDrawer: document.querySelector('#explainDrawer'),
  explainTitle: document.querySelector('#explainTitle'),
  explainBody: document.querySelector('#explainBody'),
  btnCloseExplain: document.querySelector('#btnCloseExplain'),
  calcModal: document.querySelector('#calcModal'),
  calcModalTitle: document.querySelector('#calcModalTitle'),
  calcModalSub: document.querySelector('#calcModalSub'),
  calcModalBody: document.querySelector('#calcModalBody'),
  btnCloseCalcModal: document.querySelector('#btnCloseCalcModal'),
  reportLink: document.querySelector('#reportLink'),
  toast: document.querySelector('#payrollToast'),
};

// ── Initialize ──
init();

function init() {
  loadCanbuBatches();
  loadEngineCards();
  loadTemplateLinks();
  bindEvents();
  setDefaultMonth();
  setDefaultCanbuBatchMonth();
  renderEmptyWorkbench();
  renderRecentBatchTable();
  showView('home');
}

function setDefaultMonth() {
  if (!el.attendanceMonth) return;
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, '0');
  el.attendanceMonth.value = `${y}-${m}`;
}

function setDefaultCanbuBatchMonth() {
  if (!el.canbuBatchMonth || el.canbuBatchMonth.value) return;
  setCanbuBatchMonth(getCurrentMonthValue());
}

function setCanbuBatchMonth(monthValue) {
  if (!el.canbuBatchMonth) return;
  const normalized = String(monthValue || getCurrentMonthValue()).match(/^\d{4}-\d{2}$/)
    ? String(monthValue)
    : getCurrentMonthValue();
  el.canbuBatchMonth.value = normalized;
  state.canbuBatchPickerYear = Number(normalized.slice(0, 4));
  renderCanbuBatchMonthPicker();
}

function renderCanbuBatchMonthPicker() {
  if (!el.canbuBatchYear || !el.canbuBatchMonthGrid) return;
  const year = Number(state.canbuBatchPickerYear || new Date().getFullYear());
  const selected = el.canbuBatchMonth?.value || getCurrentMonthValue();
  el.canbuBatchYear.textContent = String(year);
  el.canbuBatchMonthGrid.innerHTML = Array.from({ length: 12 }, (_, index) => {
    const month = String(index + 1).padStart(2, '0');
    const value = `${year}-${month}`;
    const active = value === selected;
    return `
      <button class="dl-month-picker-option ${active ? 'selected' : ''}" type="button" role="option" aria-selected="${active}" data-canbu-batch-month="${value}">
        ${month}月
      </button>
    `;
  }).join('');
}

function loadEngineCards() {
  if (!el.engineCardGrid) return;
  const html = Object.entries(ENGINE_META).map(([key, meta]) => `
    <div class="engine-card" data-engine="${key}">
      <div class="engine-card-icon">${meta.icon}</div>
      <div class="engine-card-body">
        <h3 class="engine-card-name">${meta.name}</h3>
        <p class="engine-card-desc">${meta.desc}</p>
      </div>
      <div class="engine-card-check">
        <svg width="18" height="18" viewBox="0 0 18 18" fill="none"><path d="M4 9l4 4 6-8" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
      </div>
    </div>
  `).join('');
  el.engineCardGrid.innerHTML = html;
}

function loadTemplateLinks() {
  if (!el.templateLinks) return;
  const html = Object.entries(ENGINE_META).map(([key, meta]) => `
    <a class="template-link" href="/api/domestic-labor/templates/${key}/download" download>
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M6 1v6M3 5l3 3 3-3M1 9h10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
      ${meta.name}模板
    </a>
  `).join('');
  el.templateLinks.innerHTML = `<p class="template-hint">没有模板？下载对应引擎的模板：</p>` + html;
}

function bindEvents() {
  // Engine card selection
  el.engineCardGrid?.addEventListener('click', (e) => {
    const card = e.target.closest('.engine-card');
    if (!card) return;
    card.classList.toggle('selected');
    updateSelectedEngines();
  });

  // Month change
  el.attendanceMonth?.addEventListener('change', updateStep1State);

  // Step navigation
  el.btnToStep2?.addEventListener('click', () => goToStep(2));
  el.btnToStep3?.addEventListener('click', () => goToStep(3));
  el.btnToStep4?.addEventListener('click', () => goToStep(4));

  // File upload
  el.payrollFile?.addEventListener('change', () => {
    const file = el.payrollFile.files[0];
    state.payrollFile = file || null;
    el.payrollFileName.textContent = file ? file.name : '点击选择 · 支持 .xlsx / .xlsm / .xls';
    if (file) el.fileUploadZone.classList.add('has-file');
    updateStep2State();
  });

  // Submit
  el.btnSubmitTask?.addEventListener('click', submitTask);
  el.btnRefreshStatus?.addEventListener('click', refreshStatus);
  el.btnExport?.addEventListener('click', () => exportResults(false));
  el.reportLink?.addEventListener('click', (event) => {
    if (el.reportLink.classList.contains('disabled')) return;
    if (el.reportLink.dataset.readyToExport === 'true') {
      event.preventDefault();
      exportResults(true);
    }
  });
  el.subjectTabs?.addEventListener('click', (event) => {
    const tab = event.target.closest('[data-subject]');
    if (!tab) return;
    state.activeSubject = tab.dataset.subject;
    el.subjectTabs.querySelectorAll('.dl-segment').forEach(button => {
      button.classList.toggle('active', button === tab);
    });
    renderResultsTable(state.currentResults);
  });
  el.resultSearchInput?.addEventListener('input', () => {
    state.resultSearch = el.resultSearchInput.value.trim();
    renderResultsTable(state.currentResults);
  });
  el.reviewStatusFilter?.addEventListener('change', () => {
    state.reviewStatusFilter = el.reviewStatusFilter.value;
    renderResultsTable(state.currentResults);
  });
  el.amountFilter?.addEventListener('change', () => {
    state.amountFilter = el.amountFilter.value;
    renderResultsTable(state.currentResults);
  });

  el.subjectCardGrid?.addEventListener('click', (event) => {
    const card = event.target.closest('[data-subject-entry]');
    if (!card) return;
    if (card.disabled || card.getAttribute('aria-disabled') === 'true') return;
    const subject = card.dataset.subjectEntry;
    if (subject === 'quanqinjiang' || subject === 'canbu' || subject === 'waisu_butie' || subject === 'gonglingjiang' || subject === 'gangwei_butie' || subject === 'gaowen_butie' || subject === 'yeban_butie') {
      state.activeWorkbenchSubject = subject;
      state.activeCanbuBatchId = '';
      showView('canbuBatches');
      updateSubjectWorkbenchLabels();
      renderCanbuBatchList();
      return;
    }
    toast('该科目将按餐补样板工作台后续改造。');
  });

  el.navSubjectHome?.addEventListener('click', (event) => {
    event.preventDefault();
    showView('home');
    renderRecentBatchTable();
  });
  el.navBatchList?.addEventListener('click', (event) => {
    event.preventDefault();
    showView('canbuBatches');
    renderCanbuBatchList();
  });
  el.navRulePackage?.addEventListener('click', (event) => {
    event.preventDefault();
    openRulePackageView();
  });
  el.rulePackageEntry?.addEventListener('click', openRulePackageView);
  el.btnBackFromRules?.addEventListener('click', () => {
    showView('home');
    renderRecentBatchTable();
  });
  el.rulePackageCategoryTabs?.addEventListener('click', (event) => {
    const tab = event.target.closest('[data-rule-category]');
    if (!tab) return;
    state.activeRuleCategory = tab.dataset.ruleCategory;
    const visibleSubjects = getVisibleRuleSubjects();
    if (!visibleSubjects.some(subject => subject.id === state.activeRuleSubject)) {
      state.activeRuleSubject = visibleSubjects[0]?.id || '';
    }
    renderRulePackageNavigation();
    renderRulePackageSubject();
  });
  el.rulePackageSubjectTabs?.addEventListener('click', (event) => {
    const tab = event.target.closest('[data-rule-subject]');
    if (!tab) return;
    state.activeRuleSubject = tab.dataset.ruleSubject;
    renderRulePackageNavigation();
    renderRulePackageSubject();
  });
  el.rulePackageVersionSelect?.addEventListener('change', () => {
    loadRulePackageVersion(el.rulePackageVersionSelect.value);
  });

  el.btnBackHome?.addEventListener('click', () => {
    showView('home');
    renderRecentBatchTable();
  });

  el.btnNewCanbuBatch?.addEventListener('click', openCanbuBatchModal);
  el.btnCancelCanbuBatch?.addEventListener('click', closeCanbuBatchModal);
  el.canbuBatchModal?.addEventListener('click', (event) => {
    if (event.target === el.canbuBatchModal) closeCanbuBatchModal();
  });
  el.btnCanbuBatchPrevYear?.addEventListener('click', () => {
    state.canbuBatchPickerYear = Number(state.canbuBatchPickerYear || new Date().getFullYear()) - 1;
    renderCanbuBatchMonthPicker();
  });
  el.btnCanbuBatchNextYear?.addEventListener('click', () => {
    state.canbuBatchPickerYear = Number(state.canbuBatchPickerYear || new Date().getFullYear()) + 1;
    renderCanbuBatchMonthPicker();
  });
  el.canbuBatchMonthGrid?.addEventListener('click', (event) => {
    const option = event.target.closest('[data-canbu-batch-month]');
    if (!option) return;
    setCanbuBatchMonth(option.dataset.canbuBatchMonth);
  });
  el.btnConfirmCanbuBatch?.addEventListener('click', createCanbuBatchFromModal);
  el.btnCloseCalcModal?.addEventListener('click', closeCalcModal);
  el.calcModal?.addEventListener('click', (event) => {
    if (event.target === el.calcModal) closeCalcModal();
  });

  el.btnToggleRail?.addEventListener('click', toggleRail);
  el.btnToggleAside?.addEventListener('click', toggleAside);
  el.btnCloseExplain?.addEventListener('click', closeExplainDrawer);
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      closeCanbuBatchModal();
      closeCalcModal();
      closeExplainDrawer();
    }
  });
}

function openCanbuBatchModal() {
  updateSubjectWorkbenchLabels();
  setDefaultCanbuBatchMonth();
  renderCanbuBatchMonthPicker();
  el.canbuBatchModal?.classList.add('visible');
  document.body.style.overflow = 'hidden';
  window.setTimeout(() => el.canbuBatchMonthGrid?.querySelector('.selected')?.focus(), 0);
}

function closeCanbuBatchModal() {
  if (!el.canbuBatchModal?.classList.contains('visible')) return;
  el.canbuBatchModal.classList.remove('visible');
  document.body.style.overflow = '';
}

function closeCalcModal() {
  if (!el.calcModal?.classList.contains('visible')) return;
  el.calcModal.classList.remove('visible');
  document.body.style.overflow = '';
}

function createCanbuBatchFromModal() {
  const config = getWorkbenchConfig();
  const month = el.canbuBatchMonth?.value || '';
  if (!month) {
    toast(`请先选择${config.name}核算月份。`);
    el.canbuBatchMonth?.focus();
    return;
  }
  clearCurrentRunState({ clearFile: true });
  resetCanbuFilters();
  const batch = createCanbuBatch(month, `${formatMonthLabel(month)} ${config.name}初算`, state.activeWorkbenchSubject);
  state.activeCanbuBatchId = batch.id;
  closeCanbuBatchModal();
  showView('canbuWorkbench');
  renderCanbuWorkbench('upload');
}

function updateSubjectWorkbenchLabels() {
  const config = getWorkbenchConfig();
  if (el.subjectBatchListTitle) el.subjectBatchListTitle.textContent = `${config.name}核算批次`;
  if (el.subjectBatchListSub) el.subjectBatchListSub.textContent = `一个批次对应一次可回看的${config.name}核算，同一月份可保留多次试算或复算。`;
  if (el.btnNewCanbuBatch) el.btnNewCanbuBatch.textContent = `新建${config.name}批次`;
  if (el.canbuBatchModalTitle) el.canbuBatchModalTitle.textContent = `新建${config.name}批次`;
  if (el.subjectBatchModalSub) el.subjectBatchModalSub.textContent = `选择本次${config.name}核算月份，创建后进入数据上传流程。`;
}

function showView(viewName) {
  state.view = viewName;
  [
    ['home', el.subjectHomeView],
    ['rulePackage', el.rulePackageView],
    ['canbuBatches', el.canbuBatchListView],
    ['canbuWorkbench', el.canbuWorkbenchView],
  ].forEach(([name, node]) => {
    if (!node) return;
    const active = name === viewName;
    node.hidden = !active;
      node.classList.toggle('active', active);
  });
  el.navSubjectHome?.classList.toggle('active', viewName === 'home');
  el.navBatchList?.classList.toggle('active', ['canbuBatches', 'canbuWorkbench'].includes(viewName));
  el.navRulePackage?.classList.toggle('active', viewName === 'rulePackage');
}

function beginCanbuOperation(batch, message = '正在准备上传文件...') {
  if (!batch) return;
  state.activeCanbuOperation = {
    batchId: batch.id,
    runId: batch.runId || '',
    phase: 'running',
    message,
    startedAt: new Date().toISOString(),
  };
  refreshCanbuOperationStatus();
}

function updateCanbuOperation(message, patch = {}) {
  if (!state.activeCanbuOperation) return;
  Object.assign(state.activeCanbuOperation, patch, { message });
  refreshCanbuOperationStatus();
}

function finishCanbuOperation(runId = '', errorMessage = '') {
  const operation = state.activeCanbuOperation;
  if (!operation || (runId && operation.runId && operation.runId !== runId)) return;
  if (errorMessage) {
    operation.phase = 'failed';
    operation.message = errorMessage;
  } else {
    state.activeCanbuOperation = null;
  }
  refreshCanbuOperationStatus();
}

function renderCanbuOperationStatus(batch) {
  const operation = state.activeCanbuOperation;
  const batchIsComplete = Boolean(batch && ['已核算', '可导出', '已导出'].includes(batch.status));
  if (!batch || batchIsComplete || !operation || operation.batchId !== batch.id) return '';
  const failed = operation.phase === 'failed';
  return `
    <section class="dl-operation-status ${failed ? 'failed' : ''}" id="canbuOperationStatus" role="status" aria-live="polite">
      ${failed ? '<span class="dl-operation-error" aria-hidden="true">!</span>' : '<span class="dl-button-spinner" aria-hidden="true"></span>'}
      <div>
        <strong>${failed ? '本次处理未完成' : '批次正在处理'}</strong>
        <p id="canbuOperationMessage">${escapeHtml(operation.message)}</p>
        ${failed ? '' : '<small>正在后台继续处理，可安全切换步骤；请勿关闭或刷新当前页面。</small>'}
      </div>
    </section>
  `;
}

function refreshCanbuOperationStatus() {
  const batch = getActiveCanbuBatch();
  const current = document.querySelector('#canbuOperationStatus');
  const markup = renderCanbuOperationStatus(batch);
  if (!markup) {
    current?.remove();
    return;
  }
  if (current) {
    current.outerHTML = markup;
    return;
  }
  if (state.view === 'canbuWorkbench') {
    document.querySelector('#canbuWorkbenchRoot .dl-workbench-head')?.insertAdjacentHTML('afterend', markup);
  }
}

async function openRulePackageView() {
  showView('rulePackage');
  window.scrollTo({ top: 0, behavior: 'smooth' });
  if (state.rulePackage) {
    renderRulePackage();
    return;
  }
  await loadRulePackageVersion();
}

async function loadRulePackageVersion(version = '') {
  if (state.rulePackageLoading) return;
  state.rulePackageLoading = true;
  if (el.rulePackageContent) {
    el.rulePackageContent.innerHTML = '<div class="dl-rule-loading">正在读取已发布规则...</div>';
  }
  try {
    const query = version ? `?version=${encodeURIComponent(version)}` : '';
    state.rulePackage = await requestJson(`/api/domestic-labor/rule-package${query}`);
    const subjects = Array.isArray(state.rulePackage.subjects) ? state.rulePackage.subjects : [];
    state.activeRuleSubject = subjects.some(subject => subject.id === state.activeRuleSubject)
      ? state.activeRuleSubject
      : (subjects[0]?.id || '');
    renderRulePackage();
  } catch (error) {
    if (el.rulePackageContent) {
      el.rulePackageContent.innerHTML = `<div class="dl-rule-loading error-text">${escapeHtml(error.message)}</div>`;
    }
  } finally {
    state.rulePackageLoading = false;
  }
}

function renderRulePackage() {
  const packageData = state.rulePackage;
  if (!packageData) return;
  if (el.rulePackageTitle) el.rulePackageTitle.textContent = packageData.name;
  if (el.rulePackageScope) el.rulePackageScope.textContent = packageData.scope_note;
  if (el.rulePackageVersionSelect) {
    const availableVersions = packageData.available_versions || packageData.version_history || [];
    el.rulePackageVersionSelect.innerHTML = availableVersions.map((version) => `
      <option value="${escapeHtml(version.version)}" ${version.version === packageData.version ? 'selected' : ''}>${escapeHtml(version.display_version)} · ${escapeHtml(version.status)}</option>
    `).join('');
  }
  if (el.rulePackageSummary) {
    const summary = [
      ['当前版本', packageData.display_version],
      ['发布状态', packageData.status],
      ['规则科目', String((packageData.subjects || []).length)],
      ['生效月份', formatRuleEffectiveMonth(packageData.effective_from)],
    ];
    el.rulePackageSummary.innerHTML = summary.map(([label, value]) => `
      <div class="dl-rule-summary-item"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>
    `).join('');
  }
  renderRulePackageNavigation();
  renderRulePackageSubject();
  renderRulePackageHistory();
}

function getVisibleRuleSubjects() {
  const subjects = state.rulePackage?.subjects || [];
  if (state.activeRuleCategory === 'all') return subjects;
  return subjects.filter(subject => subject.category_id === state.activeRuleCategory);
}

function renderRulePackageNavigation() {
  const packageData = state.rulePackage;
  if (!packageData) return;
  const categories = packageData.categories || [];
  if (el.rulePackageCategoryTabs) {
    const tabs = [{ id: 'all', name: '全部科目', subject_ids: packageData.subjects.map(subject => subject.id) }, ...categories];
    el.rulePackageCategoryTabs.innerHTML = tabs.map((category) => `
      <button class="dl-rule-tab ${category.id === state.activeRuleCategory ? 'active' : ''}" type="button" data-rule-category="${escapeHtml(category.id)}">
        <span>${escapeHtml(category.name)}</span><span>${category.subject_ids.length}</span>
      </button>
    `).join('');
  }
  if (el.rulePackageSubjectTabs) {
    const subjects = getVisibleRuleSubjects();
    el.rulePackageSubjectTabs.innerHTML = `
      <p class="dl-rule-section-label">核算科目</p>
      ${subjects.map((subject) => `
        <button class="dl-rule-tab ${subject.id === state.activeRuleSubject ? 'active' : ''}" type="button" data-rule-subject="${escapeHtml(subject.id)}">
          <span>${escapeHtml(subject.name)}</span><span class="dl-rule-status ${getRuleStatusClass(subject.status)}">${escapeHtml(subject.status)}</span>
        </button>
      `).join('')}
    `;
  }
}

function renderRulePackageSubject() {
  if (!el.rulePackageContent || !state.rulePackage) return;
  const subject = state.rulePackage.subjects.find(item => item.id === state.activeRuleSubject);
  if (!subject) {
    el.rulePackageContent.innerHTML = '<div class="dl-rule-loading">当前分类暂无规则科目。</div>';
    return;
  }
  el.rulePackageContent.innerHTML = `
    <div class="dl-rule-subject-head">
      <div>
        <span class="dl-rule-status ${getRuleStatusClass(subject.status)}">${escapeHtml(subject.status)}</span>
        <h2>${escapeHtml(subject.name)}</h2>
        <p>${escapeHtml(subject.summary)}</p>
      </div>
      <span class="dl-rule-version-tag">${escapeHtml(subject.version)}</span>
    </div>
    ${renderRulePackageBlock('数据来源', subject.data_sources)}
    ${renderRulePackageBlock('通用规则', subject.common_rules)}
    ${renderRuleFieldCalculations(subject.field_calculations, subject.name)}
    <section class="dl-rule-block">
      <h3>地区口径</h3>
      <div class="dl-rule-region-grid">
        ${(subject.regions || []).map((region) => `
          <article class="dl-rule-region">
            <div class="dl-rule-region-head">
              <strong>${escapeHtml(region.name)}</strong>
              <span class="dl-rule-formula">${escapeHtml(region.formula)}</span>
            </div>
            <p>${escapeHtml(region.rule)}</p>
            ${renderRuleList(region.details)}
          </article>
        `).join('')}
      </div>
    </section>
    ${renderRulePackageBlock('验证依据', subject.verification)}
    ${(subject.pending_confirmations || []).length ? renderRulePackageBlock('待薪酬确认', subject.pending_confirmations) : ''}
    ${renderRulePackageBlock('科目版本记录', (subject.change_log || []).map(item => `${item.version} · ${item.released_at} · ${item.changes}`))}
  `;
}

function renderRuleFieldCalculations(items = [], subjectName = '') {
  if (!items.length) return '';
  return `
    <section class="dl-rule-block">
      <h3>字段计算公式</h3>
      <p class="dl-rule-block-note">对应${escapeHtml(subjectName || '当前科目')}结果及导出明细，按业务字段从输入到应发金额逐步说明。</p>
      <div class="dl-table-wrap">
        <table class="dl-table dl-rule-formula-table">
          <thead><tr><th>结果字段</th><th>字段含义</th><th>计算公式</th><th>计算示例</th></tr></thead>
          <tbody>
            ${items.map(item => `
              <tr>
                <td>${escapeHtml(item.field)}</td>
                <td>${escapeHtml(item.definition)}</td>
                <td class="dl-rule-formula-text">${escapeHtml(item.formula)}</td>
                <td>${escapeHtml(item.example)}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    </section>
  `;
}

function renderRulePackageBlock(title, items) {
  return `<section class="dl-rule-block"><h3>${escapeHtml(title)}</h3>${renderRuleList(items)}</section>`;
}

function getRuleStatusClass(status) {
  return status === '验证中' ? 'validating' : '';
}

function renderRuleList(items = []) {
  return `<ul class="dl-rule-list">${items.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul>`;
}

function renderRulePackageHistory() {
  if (!el.rulePackageHistory || !state.rulePackage) return;
  const rows = state.rulePackage.version_history || [];
  el.rulePackageHistory.innerHTML = `
    <table class="dl-table">
      <thead><tr><th>规则包版本</th><th>状态</th><th>发布日期</th><th>生效月份</th><th>规则科目</th><th>变更说明</th></tr></thead>
      <tbody>
        ${rows.map((row) => `
          <tr>
            <td class="dl-strong">${escapeHtml(row.display_version)}</td>
            <td><span class="dl-rule-status">${escapeHtml(row.status)}</span></td>
            <td>${escapeHtml(row.released_at)}</td>
            <td>${escapeHtml(formatRuleEffectiveMonth(row.effective_from))}</td>
            <td>${row.subject_ids.length}</td>
            <td>${escapeHtml(row.summary)}</td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;
}

function formatRuleEffectiveMonth(value) {
  const matched = String(value || '').match(/^(\d{4})-(\d{2})$/);
  return matched ? `${matched[1]}年${matched[2]}月` : String(value || '');
}

function renderRecentBatchTable() {
  if (!el.recentBatchTable) return;
  const rows = state.canbuBatches.slice(0, 8);
  if (!rows.length) {
    el.recentBatchTable.innerHTML = '<div class="dl-empty compact"><p>暂无核算批次。</p></div>';
    return;
  }
  el.recentBatchTable.innerHTML = renderBatchTable(rows);
  bindBatchTableActions(el.recentBatchTable);
}

function renderCanbuBatchList() {
  if (!el.canbuBatchTable) return;
  updateSubjectWorkbenchLabels();
  const config = getWorkbenchConfig();
  const batches = state.canbuBatches.filter(batch => (batch.subject || 'canbu') === state.activeWorkbenchSubject);
  if (!batches.length) {
    el.canbuBatchTable.innerHTML = `<div class="dl-empty compact"><p>暂无${escapeHtml(config.name)}核算批次，请先新建${escapeHtml(config.name)}批次。</p></div>`;
    return;
  }
  el.canbuBatchTable.innerHTML = renderBatchTable(batches);
  bindBatchTableActions(el.canbuBatchTable);
}

function renderBatchTable(rows) {
  return `
    <table class="dl-table">
      <thead>
        <tr>
          <th>核算月份</th>
          <th>批次名称</th>
          <th>状态</th>
          <th class="dl-num">员工数</th>
          <th class="dl-num">应发合计</th>
          <th class="dl-num">异常</th>
          <th>最近更新</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        ${rows.map((batch) => `
          <tr>
            <td>${escapeHtml(formatMonthLabel(batch.month))}</td>
            <td class="dl-strong">${escapeHtml(batch.name)}</td>
            <td><span class="dl-badge ${getBatchStatusClass(batch.status)}">${escapeHtml(batch.status)}</span></td>
            <td class="dl-num">${Number(batch.employeeCount || 0)}</td>
            <td class="dl-num">${formatMoney(batch.payableTotal || 0)}</td>
            <td class="dl-num">${Number(batch.exceptionCount || 0)}</td>
            <td>${escapeHtml(formatDateTime(batch.updatedAt))}</td>
            <td><button class="dl-segment" data-open-canbu-batch="${escapeHtml(batch.id)}" type="button">进入</button></td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;
}

function bindBatchTableActions(root) {
  root.querySelectorAll('[data-open-canbu-batch]').forEach((button) => {
    button.addEventListener('click', () => {
      state.activeCanbuBatchId = button.dataset.openCanbuBatch;
      const batch = getActiveCanbuBatch();
      state.activeWorkbenchSubject = batch?.subject || 'canbu';
      resetCanbuFilters();
      if (!batch?.runId || state.currentRun?.id !== batch.runId) {
        state.currentRun = null;
        state.currentResults = [];
        state.currentResultsRunId = '';
      }
      const targetStep = isCanbuBatchCalculating(batch) ? 'results'
        : batch?.runId && ['已核算', '可导出', '已导出'].includes(batch.status) ? 'results' : 'upload';
      showView('canbuWorkbench');
      renderCanbuWorkbench(targetStep);
    });
  });
}

function renderCanbuWorkbench(step = 'upload') {
  const batch = getActiveCanbuBatch();
  if (!batch || !el.canbuWorkbenchRoot) return;
  const batchIsComplete = ['已核算', '可导出', '已导出'].includes(batch.status);
  if (batchIsComplete && state.activeCanbuOperation?.batchId === batch.id) {
    state.activeCanbuOperation = null;
  }
  if (step !== 'upload' && !batch.runId) step = 'upload';
  state.activeWorkbenchSubject = batch.subject || 'canbu';
  const config = getWorkbenchConfig(batch.subject);
  syncWorkbenchChrome(batch);
  const canbuRunId = batch.runId || '';
  const hasMatchingRun = Boolean(canbuRunId && state.currentRun && state.currentRun.id === canbuRunId);
  const hasMatchingResults = Boolean(hasMatchingRun && state.currentResultsRunId === canbuRunId);
  const batchIsCalculating = isCanbuBatchCalculating(batch);
  const isActiveRunCalculating = Boolean(hasMatchingRun && !hasMatchingResults && batchIsCalculating);
  const shouldRestoreRun = Boolean(
    canbuRunId &&
      !isActiveRunCalculating &&
      (!hasMatchingRun || !hasMatchingResults) &&
      (batchIsCalculating || step === 'results' || (step !== 'upload' && ['已核算', '可导出', '已导出'].includes(batch.status)))
  );
  if (shouldRestoreRun) {
    renderCanbuRunLoading(batch, step);
    restoreCanbuRunStatus(canbuRunId, step);
    return;
  }
  const canbuResults = hasMatchingResults ? (Array.isArray(state.currentResults) ? state.currentResults : []) : [];
  const showAside = step === 'results' || canbuResults.length > 0;
  const canbuWarningCount = countWorkbenchWarnings(canbuResults, batch.subject);
  if (el.payrollShell) {
    el.payrollShell.classList.toggle('aside-collapsed', showAside);
  }
  el.canbuWorkbenchRoot.innerHTML = `
    <section class="dl-panel dl-workbench-head">
      <div class="dl-panel-head">
        <div>
          <h2 class="dl-panel-title">${escapeHtml(batch.name)}</h2>
          <p class="dl-panel-sub">${escapeHtml(formatMonthLabel(batch.month))} · ${escapeHtml(config.name)}核算 · <span class="dl-badge ${getBatchStatusClass(batch.status)}">${escapeHtml(batch.status)}</span></p>
        </div>
        <div class="dl-actions-inline">
          <button class="dl-btn" id="btnBackCanbuBatches" type="button">返回批次列表</button>
          <button class="dl-btn" id="btnRecalculateCanbu" type="button">重新核算</button>
          <button class="btn-primary btn-export" id="btnExportCanbu" type="button" ${canbuResults.length ? '' : 'disabled'}>导出结果</button>
        </div>
      </div>
      ${renderCanbuStepper(step, batch)}
    </section>
    ${renderCanbuOperationStatus(batch)}
    ${showAside ? `
      <div class="dl-grid dl-grid-workbench">
        <div class="dl-stack" id="canbuStepContent"></div>
        <aside class="dl-aside">
          <button class="dl-aside-toggle" id="btnToggleAside" type="button" aria-expanded="false" aria-label="展开异常队列">
            <span class="dl-aside-toggle-main">
              <span class="dl-aside-toggle-icon">‹</span>
              <span class="dl-aside-toggle-text">展开异常</span>
            </span>
            ${canbuWarningCount ? `<span class="dl-aside-count" aria-label="${canbuWarningCount} 条异常">${canbuWarningCount}</span>` : ''}
          </button>
          <section class="dl-panel dl-aside-panel">
            <div class="dl-panel-head">
              <div>
                <h2 class="dl-panel-title">异常</h2>
                <p class="dl-panel-sub">仅显示需处理项。</p>
              </div>
            </div>
            <div class="dl-panel-body">
              <div id="exceptionQueue" class="dl-exception-list"></div>
            </div>
          </section>
        </aside>
      </div>
    ` : '<div class="dl-stack dl-stack-wide" id="canbuStepContent"></div>'}
  `;
  refreshDynamicWorkbenchRefs();
  renderCanbuStepContent(step, canbuResults);
  bindCanbuWorkbenchEvents();
}

function syncWorkbenchChrome(batch) {
  if (!batch) return;
  const complete = ['已核算', '可导出', '已导出'].includes(batch.status);
  if (el.batchNameText) el.batchNameText.textContent = batch.name;
  if (el.batchStatusText) {
    el.batchStatusText.textContent = batch.status;
    el.batchStatusText.classList.toggle('is-ok', complete);
    el.batchStatusText.classList.toggle('is-warn', !complete);
  }
  if (el.chromeRunBadge) el.chromeRunBadge.hidden = !batch.runId;
  if (el.chromeRunLabel) el.chromeRunLabel.textContent = batch.runId ? `任务 #${batch.runId.slice(-8)}` : '任务 #—';
}

function renderCanbuRunLoading(batch, step) {
  if (!el.canbuWorkbenchRoot) return;
  const config = getWorkbenchConfig(batch.subject);
  syncWorkbenchChrome(batch);
  el.canbuWorkbenchRoot.innerHTML = `
    <section class="dl-panel dl-workbench-head">
      <div class="dl-panel-head">
        <div>
          <h2 class="dl-panel-title">${escapeHtml(batch.name)}</h2>
          <p class="dl-panel-sub">${escapeHtml(formatMonthLabel(batch.month))} · ${escapeHtml(config.name)}核算 · <span class="dl-badge ${getBatchStatusClass(batch.status)}">${escapeHtml(batch.status)}</span></p>
        </div>
        <div class="dl-actions-inline">
          <button class="dl-btn" id="btnBackCanbuBatches" type="button">返回批次列表</button>
        </div>
      </div>
      ${renderCanbuStepper(step, batch)}
    </section>
    ${renderCanbuOperationStatus(batch)}
    <section class="dl-panel">
      <div class="dl-panel-body">
        <p class="inline-status">正在加载本批次核算结果...</p>
      </div>
    </section>
  `;
  refreshDynamicWorkbenchRefs();
  bindCanbuWorkbenchEvents();
}

async function restoreCanbuRunStatus(runId, step = 'results') {
  try {
    const runStatus = await requestJson(`/api/domestic-labor/runs/${runId}?response_mode=status`);
    if (runStatus.status !== '已完成') {
      state.currentRun = { ...runStatus, id: runStatus.id || runId };
      syncCanbuBatchFromRun(state.currentRun);
      if (runStatus.status === '失败') {
        finishCanbuOperation(runId, runStatus.error || '核算失败，请重新上传文件。');
        renderCanbuWorkbench('upload');
        return;
      }
      if (!state.activeCanbuOperation) {
        beginCanbuOperation(getActiveCanbuBatch(), '已恢复后台任务状态，正在等待核算完成...');
        updateCanbuOperation('已恢复后台任务状态，正在等待核算完成...', { runId });
      }
      renderCanbuWorkbench('results');
      startPolling();
      return;
    }
    const resultPayload = await requestJson(`/api/domestic-labor/runs/${runId}/results`);
    const metadata = { ...runStatus, ...resultPayload, id: runStatus.id || runId };
    state.currentRun = metadata;
    state.currentResults = sanitizePayrollResults(metadata.results);
    state.currentResultsRunId = metadata.id || runId;
    syncCanbuBatchFromRun(metadata, { includeResults: true });
    finishCanbuOperation(runId);
    renderCanbuWorkbench(step);
  } catch (error) {
    updateActiveCanbuBatch({ status: '失败' });
    finishCanbuOperation(runId, error.message || '读取后台任务状态失败，请稍后重试。');
    toast(error.message || '加载核算结果失败。');
    renderCanbuWorkbench('upload');
  }
}

function renderCanbuStepper(activeStep, batch) {
  const config = getWorkbenchConfig(batch?.subject);
  const completed = new Set();
  if (batch.status !== '草稿') completed.add('upload');
  if (['已核算', '可导出', '已导出'].includes(batch.status)) completed.add('fields');
  if (['已核算', '可导出', '已导出'].includes(batch.status)) completed.add('results');
  return `
    <div class="dl-stepper">
      ${CANBU_STEPS.map((stepItem) => {
        const active = stepItem.key === activeStep;
        const done = completed.has(stepItem.key);
        const available = stepItem.key === 'upload' || Boolean(batch?.runId);
        const index = CANBU_STEPS.indexOf(stepItem) + 1;
        const status = done ? '已完成' : active ? '进行中' : '未开始';
        const icon = active
          ? `<span class="dl-stepper-index active-pin">${renderStepperPin(index)}</span>`
          : `<span class="dl-stepper-index">${done ? '✓' : index}</span>`;
        return `
          <button class="dl-stepper-item ${active ? 'active' : ''} ${done ? 'done' : ''}" data-canbu-step="${stepItem.key}" type="button" ${available ? '' : 'disabled aria-disabled="true"'}>
            ${icon}
            <span class="dl-stepper-label">${stepItem.key === 'results' ? `${escapeHtml(config.name)}核算` : stepItem.label}</span>
            <span class="dl-stepper-status ${done ? 'success' : ''}">${status}</span>
          </button>
        `;
      }).join('')}
    </div>
  `;
}

function renderStepperPin(index) {
  return `
    <svg class="dl-stepper-pin" viewBox="0 0 34 40" aria-hidden="true">
      <path class="dl-stepper-pin-shadow" d="M17 39c8 0 14-3 14-7s-6-7-14-7S3 28 3 32s6 7 14 7z"></path>
      <path class="dl-stepper-pin-halo" d="M17 35c9.39 0 17-7.61 17-17S26.39 1 17 1 0 8.61 0 18s7.61 17 17 17z"></path>
      <path class="dl-stepper-pin-body" d="M17 31c7.18 0 13-5.82 13-13S24.18 5 17 5 4 10.82 4 18s5.82 13 13 13z"></path>
      <text class="dl-stepper-pin-text" x="17" y="19" text-anchor="middle">${index}</text>
    </svg>
  `;
}

function refreshDynamicWorkbenchRefs() {
  el.exceptionQueue = document.querySelector('#exceptionQueue');
  el.btnToggleAside = document.querySelector('#btnToggleAside');
}

function nightShiftMonth(batch = getActiveCanbuBatch()) {
  return String(batch?.month || '').replace(/\D/g, '').slice(0, 6);
}

function getNightShiftConfig(batch = getActiveCanbuBatch()) {
  return state.nightShiftConfigs[nightShiftMonth(batch)] || null;
}

function isNightShiftConfigReady(batch = getActiveCanbuBatch()) {
  const config = getNightShiftConfig(batch);
  return Number(config?.counts?.effective_shift_count || 0) > 0;
}

async function loadNightShiftConfig(batch = getActiveCanbuBatch(), { force = false } = {}) {
  const month = nightShiftMonth(batch);
  if (!month || state.nightShiftConfigLoading[month]) return;
  if (!force && state.nightShiftConfigs[month]) return;
  state.nightShiftConfigLoading[month] = true;
  try {
    state.nightShiftConfigs[month] = await requestJson(`/api/domestic-labor/night-shift/config/${month}`);
  } catch (error) {
    toast(error.message || '加载夜班配置失败。');
  } finally {
    state.nightShiftConfigLoading[month] = false;
    if (getActiveCanbuBatch()?.id === batch?.id && getActiveWorkbenchSubject() === 'yeban_butie') {
      renderCanbuStepContent('upload');
    }
  }
}

function renderNightShiftConfigRows(rows, columns, emptyText) {
  const visibleRows = (rows || []).slice(0, 8);
  if (!visibleRows.length) return `<p class="inline-status">${escapeHtml(emptyText)}</p>`;
  return `
    <div class="dl-table-wrap">
      <table class="dl-table">
        <thead><tr>${columns.map(column => `<th>${escapeHtml(column.label)}</th>`).join('')}</tr></thead>
        <tbody>${visibleRows.map(row => `<tr>${columns.map(column => `<td>${escapeHtml(column.value(row))}</td>`).join('')}</tr>`).join('')}</tbody>
      </table>
    </div>
    ${(rows || []).length > visibleRows.length ? `<p class="inline-status">仅预览前 ${visibleRows.length} 条，完整内容请下载当前配置。</p>` : ''}
  `;
}

const NIGHT_SHIFT_BREAK_CATEGORIES = ['晚上休息', '早上休息', '其他休息'];

function getNightShiftBreakSegments(row) {
  const configured = Array.isArray(row?.break_segments) ? row.break_segments : [];
  const legacy = Array.isArray(row?.break_periods) ? row.break_periods : [];
  const segments = configured.length
    ? configured
    : legacy.map(period => ({ period, category: '其他休息' }));
  return [...segments, null, null, null].slice(0, 3).map(segment => ({
    period: String(segment?.period || ''),
    category: NIGHT_SHIFT_BREAK_CATEGORIES.includes(segment?.category)
      ? segment.category
      : '其他休息',
  }));
}

function renderNightShiftBreakSegment(segment, index) {
  const number = index + 1;
  return `
    <td>
      <div class="dl-break-segment-input">
        <select data-shift-field="break_category_${number}" aria-label="休息段${number}类型">
          ${NIGHT_SHIFT_BREAK_CATEGORIES.map(category => `
            <option value="${escapeHtml(category)}" ${segment.category === category ? 'selected' : ''}>${escapeHtml(category)}</option>
          `).join('')}
        </select>
        <input class="dl-roster-input" data-shift-field="break_${number}" value="${escapeHtml(segment.period)}" placeholder="HH:MM-HH:MM" aria-label="休息段${number}时段">
      </div>
    </td>
  `;
}

function renderNightShiftBreakEditor(config) {
  const rows = config.effective_shift_breaks || config.shift_breaks || [];
  const overrideCodes = new Set((config.shift_break_overrides || []).map(row => String(row.shift_code || '')));
  return `
    <div class="dl-night-shift-break-editor">
      <div class="dl-break-editor-toolbar">
        <label class="dl-break-search-field">
          <span>筛选班次</span>
          <input id="nightShiftBreakSearch" type="search" placeholder="输入班次编号、名称或类别">
        </label>
        <p class="inline-status">每段休息必须明确选择“晚上休息 / 早上休息 / 其他休息”；00:00—01:00等跨零点时段不会被系统自行改判。</p>
        <button class="btn-primary" id="btnSaveNightShiftBreaks" type="button">保存当月班次调整</button>
      </div>
      <div class="dl-roster-table-wrap dl-break-table-wrap">
        <table class="dl-roster-table dl-break-edit-table">
          <thead><tr><th>状态</th><th>班次类别</th><th>班次编号</th><th>班次名称</th><th>班次时间</th><th>正班时数</th><th>休息段1（类型/时段）</th><th>休息段2（类型/时段）</th><th>休息段3（类型/时段）</th><th>备注</th></tr></thead>
          <tbody>${rows.map(row => {
            const breakSegments = getNightShiftBreakSegments(row);
            const searchText = [row.shift_category, row.shift_code, row.shift_name].filter(Boolean).join(' ').toLowerCase();
            const adjusted = overrideCodes.has(String(row.shift_code || ''));
            return `
              <tr data-night-shift-break-row data-shift-code="${escapeHtml(row.shift_code || '')}" data-search-text="${escapeHtml(searchText)}">
                <td><span class="dl-badge ${adjusted ? 'warn' : 'neutral'}">${adjusted ? '当月调整' : '平台基线'}</span></td>
                <td><input class="dl-roster-input" data-shift-field="shift_category" value="${escapeHtml(row.shift_category || '')}" aria-label="班次类别"></td>
                <td><strong class="dl-shift-code">${escapeHtml(row.shift_code || '')}</strong></td>
                <td><input class="dl-roster-input" data-shift-field="shift_name" value="${escapeHtml(row.shift_name || '')}" aria-label="班次名称"></td>
                <td><input class="dl-roster-input" data-shift-field="shift_time" value="${escapeHtml(row.shift_time || '')}" aria-label="班次时间"></td>
                <td><input class="dl-roster-input" data-shift-field="regular_hours" inputmode="decimal" value="${escapeHtml(row.regular_hours ?? '')}" aria-label="正班时数"></td>
                ${breakSegments.map(renderNightShiftBreakSegment).join('')}
                <td><input class="dl-roster-input" data-shift-field="note" value="${escapeHtml(row.note || '')}" aria-label="备注"></td>
              </tr>
            `;
          }).join('')}</tbody>
        </table>
      </div>
    </div>
  `;
}

function collectNightShiftBreakOverrides(config) {
  const baselineByCode = new Map((config.baseline_shift_breaks || []).map(row => [String(row.shift_code || ''), row]));
  const fields = ['shift_category', 'shift_name', 'shift_code', 'shift_time', 'regular_hours', 'break_segments', 'note'];
  const comparable = row => Object.fromEntries(fields.map(field => [field, row?.[field] ?? (field === 'break_segments' ? [] : '')]));
  return Array.from(document.querySelectorAll('[data-night-shift-break-row]')).map(row => {
    const value = field => row.querySelector(`[data-shift-field="${field}"]`)?.value.trim() || '';
    const regularHoursText = value('regular_hours');
    const breakSegments = [1, 2, 3].map(index => ({
      period: value(`break_${index}`),
      category: value(`break_category_${index}`) || '其他休息',
    })).filter(segment => segment.period);
    return {
      shift_category: value('shift_category'),
      shift_name: value('shift_name'),
      shift_code: row.dataset.shiftCode || '',
      shift_time: value('shift_time'),
      regular_hours: regularHoursText === '' ? null : Number(regularHoursText),
      break_periods: breakSegments.map(segment => segment.period),
      break_segments: breakSegments,
      note: value('note'),
    };
  }).filter(row => JSON.stringify(comparable(row)) !== JSON.stringify(comparable(baselineByCode.get(row.shift_code))));
}

function renderNightShiftConfigPanel(batch) {
  const month = nightShiftMonth(batch);
  const config = getNightShiftConfig(batch);
  const loading = Boolean(state.nightShiftConfigLoading[month]);
  if (!config) {
    return `
      <section class="dl-panel">
        <div class="dl-panel-head"><div><h2 class="dl-panel-title">当月夜班配置</h2><p class="dl-panel-sub">${loading ? '正在读取配置版本…' : '准备读取配置版本。'}</p></div></div>
      </section>
    `;
  }
  const counts = config.counts || {};
  const ready = isNightShiftConfigReady(batch);
  const listConfirmed = Boolean(config.jinjiang_list_confirmed);
  const updatedText = config.updated_at
    ? `最近更新：${escapeHtml(formatDateTime(config.updated_at))}${config.copied_from ? ` · 晋江名单复制自 ${escapeHtml(config.copied_from)}` : ''}`
    : '平台班次基线已加载。请确认本月是否存在晋江额外排除人员；未确认前，晋江普通岗进入待确认。';
  const exclusionCount = Number(counts.jinjiang_exclusion_count || 0);
  const listStatus = !listConfirmed ? '未确认' : exclusionCount ? `已确认 ${exclusionCount} 人` : '已确认无额外排除';
  return `
    <section class="dl-panel">
      <div class="dl-panel-head">
        <div>
          <h2 class="dl-panel-title">${escapeHtml(formatMonthLabel(batch.month))} 夜班特殊配置</h2>
          <p class="dl-panel-sub">班次休息以平台基线为准，可保存当月差异；地区范围由固定线下规则判断；晋江仅需确认额外不享有人员。</p>
        </div>
        <span class="dl-badge ${listConfirmed ? 'ok' : 'warn'}">${listConfirmed ? `版本 ${Number(config.revision || 0)} · ${listStatus}` : '平台基线可核算 · 晋江名单未确认'}</span>
      </div>
      <div class="dl-result-summary">
        <div class="dl-result-stat primary"><span>平台有效班次</span><strong>${Number(counts.effective_shift_count || 0)}</strong></div>
        <div class="dl-result-stat"><span>当月班次调整</span><strong>${Number(counts.shift_break_override_count || 0)}</strong></div>
        <div class="dl-result-stat"><span>适用地区规则</span><strong>固定内置</strong></div>
        <div class="dl-result-stat"><span>晋江额外排除人数</span><strong>${exclusionCount}</strong></div>
        <div class="dl-result-stat ${listConfirmed ? '' : 'warning'}"><span>晋江名单状态</span><strong>${listStatus}</strong></div>
      </div>
      <div class="dl-night-config-guide" aria-label="晋江名单填写说明">
        <div class="dl-night-config-guide-item is-purpose"><strong>这份名单会做什么</strong><p>名单内人员在填写的生效日期范围内，不计算晋江夜班补贴。</p></div>
        <div class="dl-night-config-guide-item"><strong>需要人工维护</strong><p>考勤字段无法稳定识别，但因轻松岗位或其他线下确认原因不享有补贴的人员。</p></div>
        <div class="dl-night-config-guide-item"><strong>不要重复维护</strong><p>计件岗、门禁由系统自动排除；其他地区人员也不填这份名单。</p></div>
      </div>
      <div class="dl-actions-inline dl-night-config-actions">
        ${!listConfirmed ? '<button class="dl-btn" id="btnConfirmNoJinjiangExclusions" type="button">确认本月无额外排除人员</button>' : ''}
        <a class="dl-btn" href="/api/domestic-labor/night-shift/config-template/download" download>下载有名单时的填写模板</a>
        ${listConfirmed ? `<a class="dl-btn" href="/api/domestic-labor/night-shift/config/${month}/download" download>下载当前晋江名单</a>` : ''}
        <button class="dl-btn" id="btnCopyNightShiftConfig" type="button" ${listConfirmed ? 'disabled' : ''}>复制上月晋江名单</button>
        <button class="btn-primary" id="btnImportNightShiftConfig" type="button">${listConfirmed ? '更新不享有名单' : '上传填写完成的名单'}</button>
        <input id="nightShiftConfigFile" type="file" accept=".xlsx,.xlsm" hidden>
      </div>
      <p class="inline-status" id="nightShiftConfigStatus">${updatedText}</p>
      <details class="dl-parameter-panel" open><summary><span>平台班次休息表</span><strong>${Number(counts.effective_shift_count || 0)} 条 · ${Number(counts.shift_break_override_count || 0)} 条当月调整</strong></summary><div class="dl-parameter-panel-body">${renderNightShiftBreakEditor(config)}</div></details>
        <details class="dl-parameter-panel"><summary><span>晋江不享有夜班补贴人员名单</span><strong>${exclusionCount} 人 · ${listStatus}</strong></summary><div class="dl-parameter-panel-body">${renderNightShiftConfigRows(config.jinjiang_exclusions, [
          { label: '工号', value: row => row.employee_id || '' }, { label: '姓名', value: row => row.employee_name || '' }, { label: '排除原因', value: row => row.reason || '' }, { label: '有效期', value: row => `${row.start_date || ''} 至 ${row.end_date || '持续有效'}` },
        ], listConfirmed ? '本月已确认无额外排除人员。计件岗和门禁仍由系统自动排除。' : '请先确认本月无人，或下载模板填写后上传。')}</div></details>
    </section>
  `;
}

function renderCanbuStepContent(step, results = []) {
  const root = document.querySelector('#canbuStepContent');
  if (!root) return;
  const batch = getActiveCanbuBatch();
  const config = getWorkbenchConfig(batch?.subject);
  const operation = state.activeCanbuOperation;
  if (step !== 'upload' && operation?.batchId === batch?.id && operation.phase !== 'failed' && isCanbuBatchCalculating(batch)) {
    root.innerHTML = renderCanbuCalculatingState(batch);
    renderExceptionQueue([]);
    return;
  }
  const collectionRoster = batch?.subject === 'gonglingjiang'
    ? normalizeCollectionRoster(
        Array.isArray(batch.collectionSeniorityRoster)
          ? batch.collectionSeniorityRoster
          : DEFAULT_COLLECTION_SENIORITY_ROSTER
      )
    : [];
  if (step === 'upload') {
    const isNightShift = batch?.subject === 'yeban_butie';
    root.innerHTML = `
      ${isNightShift ? renderNightShiftConfigPanel(batch) : ''}
      <section class="dl-panel">
        <div class="dl-panel-head">
          <div>
            <h2 class="dl-panel-title">数据上传</h2>
            <p class="dl-panel-sub">${escapeHtml(config.uploadDescription)} 可上传一个含多张Sheet的文件，也可一次上传多个拆分文件。</p>
          </div>
        </div>
        <div class="dl-upload-list">
          <div class="dl-upload-row">
            <strong>日考勤数据</strong>
            <span>${batch?.subject === 'yeban_butie' ? '日期、班次、上下班打卡与岗位识别' : batch?.subject === 'gaowen_butie' ? '出勤日期、班次、正班时数、刷卡加班与实际上班时数' : batch?.subject === 'waisu_butie' ? '出勤与工作地区识别' : batch?.subject === 'gangwei_butie' ? '岗位补贴不依赖日考勤明细' : batch?.subject === 'gonglingjiang' ? '工龄奖不依赖日考勤明细' : batch?.subject === 'quanqinjiang' ? '月初入职前工作日识别' : '东莞餐补逐日计算'}</span>
            <span class="dl-badge ${(batch?.subject === 'gonglingjiang' || batch?.subject === 'gangwei_butie') ? 'ok' : 'warn'}">${(batch?.subject === 'gonglingjiang' || batch?.subject === 'gangwei_butie') ? '非必需' : batch?.subject === 'quanqinjiang' ? '建议上传' : '随 Excel 上传'}</span>
          </div>
          <div class="dl-upload-row">
            <strong>月考勤数据</strong>
            <span>${batch?.subject === 'yeban_butie' ? '员工、工作地区和岗位基础字段' : batch?.subject === 'gaowen_butie' ? '员工、地区、岗位和各级组织归属，用于识别测温网点' : batch?.subject === 'waisu_butie' ? '岗位、入离职和缺勤字段' : batch?.subject === 'gangwei_butie' ? '地区、岗位、排班天数和九类缺勤字段' : batch?.subject === 'gonglingjiang' ? '地区、部门、岗位、入职日期和缺勤字段' : batch?.subject === 'quanqinjiang' ? '入离职、缺勤、迟到早退和签卡字段' : '嘉善/义乌汇总计算、人员字段补充'}</span>
            <span class="dl-badge warn">随 Excel 上传</span>
          </div>
          ${batch?.subject === 'waisu_butie' ? `
          <div class="dl-upload-row">
            <strong>住宿名单字段</strong>
            <span>工号、入住时间、退宿时间</span>
            <span class="dl-badge warn">随 Excel 上传</span>
          </div>` : ''}
          ${batch?.subject === 'gaowen_butie' ? `
          <div class="dl-upload-row">
            <strong>高温测温登记</strong>
            <span>班次日期、测温班次、测温网点、测温温度；同仓同日同班次最高温达到33℃才计发</span>
            <span class="dl-badge warn">随 Excel 上传</span>
          </div>` : ''}
        </div>
        ${batch?.subject === 'gonglingjiang' ? `
        <details class="dl-parameter-panel dl-upload-parameter">
          <summary><span>揽收线工龄奖名单</span><strong><span id="workbenchCollectionRosterCount">${collectionRoster.length}</span> 人</strong><span class="dl-badge">命中第四纵队时要求</span></summary>
          <div class="dl-upload-parameter-body">
            <div class="dl-roster-table-wrap">
              <table class="dl-roster-table">
                <colgroup><col class="dl-roster-id-col"><col></colgroup>
                <thead><tr><th>工号</th><th>姓名</th></tr></thead>
                <tbody id="workbenchCollectionRosterRows">${renderCollectionRosterRows(collectionRoster)}</tbody>
              </table>
            </div>
            <button class="dl-btn dl-roster-add" id="btnAddCollectionRosterPerson" type="button">＋ 新增人员</button>
            <p class="inline-status">字段检查识别到工作地区为东莞、二级部门为第四纵队时，才校验本名单；其他部门无需维护。名单会随本次批次保存。</p>
          </div>
        </details>` : ''}
        <div class="upload-zone" id="fileUploadZone" role="button" tabindex="0">
          <input id="payrollFile" type="file" accept=".xlsx,.xlsm,.xls" multiple />
          <p class="upload-title">${escapeHtml(config.uploadTitle)}</p>
          <p class="upload-sub" id="payrollFileName">点击选择一个或多个文件 · 支持 .xlsx / .xlsm / .xls</p>
        </div>
        <div class="dl-selected-files" id="selectedPayrollFileList" hidden></div>
        <div class="drawer-footer compact">
          <p id="uploadStatus" class="inline-status">选择文件后开始字段检查。</p>
          <button id="btnSubmitCanbuBatch" class="btn-primary-lg" type="button" disabled>开始字段检查</button>
        </div>
      </section>
    `;
    refreshUploadRefs();
    bindCanbuUploadEvents();
    renderSelectedPayrollFiles();
    renderExceptionQueue([]);
    if (isNightShift && !getNightShiftConfig(batch)) loadNightShiftConfig(batch);
    return;
  }

  if (step === 'fields') {
    root.innerHTML = renderCanbuFieldCheck(batch?.subject);
    renderExceptionQueue([]);
    return;
  }

  if (step === 'results' && !results.length && isCanbuBatchCalculating(batch)) {
    root.innerHTML = renderCanbuCalculatingState(batch);
    renderExceptionQueue([]);
    return;
  }

  root.innerHTML = '<section class="dl-panel"><div id="resultsTable" class="dl-table-wrap"></div></section>';
  el.resultsTable = document.querySelector('#resultsTable');
  if (batch?.subject === 'quanqinjiang') renderQuanqinResults(results);
  else if (batch?.subject === 'waisu_butie') renderWaisuResults(results);
  else if (batch?.subject === 'gonglingjiang') renderGonglingResults(results);
  else if (batch?.subject === 'gangwei_butie') renderGangweiResults(results);
  else if (batch?.subject === 'gaowen_butie') renderGaowenResults(results);
  else if (batch?.subject === 'yeban_butie') renderNightShiftResults(results);
  else renderCanbuResults(results);
}

function refreshUploadRefs() {
  el.payrollFile = document.querySelector('#payrollFile');
  el.payrollFileName = document.querySelector('#payrollFileName');
  el.fileUploadZone = document.querySelector('#fileUploadZone');
  el.selectedPayrollFileList = document.querySelector('#selectedPayrollFileList');
  el.uploadStatus = document.querySelector('#uploadStatus');
}

function payrollFileKey(file) {
  return `${file.name}::${file.size}::${file.lastModified}`;
}

function formatFileSize(size) {
  const bytes = Number(size || 0);
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function renderSelectedPayrollFiles(message = '') {
  const files = state.payrollFiles || [];
  const submit = document.querySelector('#btnSubmitCanbuBatch');
  state.payrollFile = files[0] || null;
  if (el.payrollFileName) {
    el.payrollFileName.textContent = files.length
      ? `已累计选择 ${files.length} 个文件，可继续选择追加`
      : '点击选择一个或多个文件 · 支持 .xlsx / .xlsm / .xls';
  }
  el.fileUploadZone?.classList.toggle('has-file', files.length > 0);
  const configReady = getActiveWorkbenchSubject() !== 'yeban_butie' || isNightShiftConfigReady();
  if (submit) submit.disabled = files.length === 0 || !configReady;
  if (el.uploadStatus) {
    setText(el.uploadStatus, message || (files.length
      ? (configReady ? '提交后自动识别月考勤、日考勤及住宿名单。' : '先完成当月夜班配置，文件已暂存。')
      : (configReady ? '选择文件后开始字段检查。' : '先完成当月夜班配置，再上传考勤文件。')));
  }
  if (!el.selectedPayrollFileList) return;
  el.selectedPayrollFileList.hidden = files.length === 0;
  el.selectedPayrollFileList.innerHTML = files.map(file => `
    <div class="dl-selected-file">
      <span class="dl-selected-file-icon" aria-hidden="true">XLS</span>
      <span class="dl-selected-file-name">${escapeHtml(file.name)}</span>
      <span class="dl-selected-file-size">${escapeHtml(formatFileSize(file.size))}</span>
      <button class="dl-selected-file-remove" data-remove-payroll-file="${escapeHtml(payrollFileKey(file))}" type="button" aria-label="移除${escapeHtml(file.name)}" title="移除文件">×</button>
    </div>
  `).join('');
  el.selectedPayrollFileList.querySelectorAll('[data-remove-payroll-file]').forEach(button => {
    button.addEventListener('click', () => {
      const key = button.dataset.removePayrollFile;
      state.payrollFiles = state.payrollFiles.filter(file => payrollFileKey(file) !== key);
      renderSelectedPayrollFiles('已更新待上传文件清单。');
    });
  });
}

function bindCanbuUploadEvents() {
  const submit = document.querySelector('#btnSubmitCanbuBatch');
  const collectionRosterRows = document.querySelector('#workbenchCollectionRosterRows');
  const collectionRosterCount = document.querySelector('#workbenchCollectionRosterCount');
  const syncCollectionRoster = () => {
    const roster = collectCollectionRosterTable();
    updateActiveCanbuBatch({ collectionSeniorityRoster: roster });
    if (collectionRosterCount) collectionRosterCount.textContent = String(roster.length);
  };
  collectionRosterRows?.addEventListener('input', syncCollectionRoster);
  collectionRosterRows?.addEventListener('click', (event) => {
    const removeButton = event.target.closest('.dl-roster-remove');
    if (!removeButton) return;
    removeButton.closest('[data-collection-roster-row]')?.remove();
    if (!collectionRosterRows.querySelector('[data-collection-roster-row]')) {
      collectionRosterRows.insertAdjacentHTML('beforeend', renderCollectionRosterRow());
    }
    syncCollectionRoster();
  });
  document.querySelector('#btnAddCollectionRosterPerson')?.addEventListener('click', () => {
    collectionRosterRows?.insertAdjacentHTML('beforeend', renderCollectionRosterRow());
    collectionRosterRows?.querySelector('tr:last-child [data-roster-field="employeeId"]')?.focus();
  });
  const nightShiftConfigInput = document.querySelector('#nightShiftConfigFile');
  document.querySelector('#btnConfirmNoJinjiangExclusions')?.addEventListener('click', async () => {
    const batch = getActiveCanbuBatch();
    const month = nightShiftMonth(batch);
    const config = getNightShiftConfig(batch);
    const status = document.querySelector('#nightShiftConfigStatus');
    if (!month || !config) return;
    setText(status, '正在确认本月无额外排除人员…');
    try {
      state.nightShiftConfigs[month] = await requestJson(
        `/api/domestic-labor/night-shift/config/${month}`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            shift_break_overrides: config.shift_break_overrides || [],
            jinjiang_exclusions: [],
            jinjiang_list_confirmed: true,
          }),
        }
      );
      toast('已确认本月无额外排除人员。');
      renderCanbuStepContent('upload');
    } catch (error) {
      setText(status, error.message, true);
      toast(error.message);
    }
  });
  document.querySelector('#btnImportNightShiftConfig')?.addEventListener('click', () => {
    nightShiftConfigInput?.click();
  });
  nightShiftConfigInput?.addEventListener('change', async () => {
    const file = nightShiftConfigInput.files?.[0];
    const batch = getActiveCanbuBatch();
    const month = nightShiftMonth(batch);
    if (!file || !month) return;
    const status = document.querySelector('#nightShiftConfigStatus');
    setText(status, '正在校验并保存晋江不享有夜班补贴人员名单…');
    try {
      const form = new FormData();
      form.append('file', file);
      state.nightShiftConfigs[month] = await requestJson(
        `/api/domestic-labor/night-shift/config/${month}/import`,
        { method: 'POST', body: form }
      );
      toast('当月晋江不享有夜班补贴人员名单已保存。');
      renderCanbuStepContent('upload');
    } catch (error) {
      setText(status, error.message, true);
      toast(error.message);
    } finally {
      nightShiftConfigInput.value = '';
    }
  });
  document.querySelector('#btnCopyNightShiftConfig')?.addEventListener('click', async () => {
    const batch = getActiveCanbuBatch();
    const month = nightShiftMonth(batch);
    const status = document.querySelector('#nightShiftConfigStatus');
    if (!month) return;
    setText(status, '正在复制上月晋江不享有名单…');
    try {
      state.nightShiftConfigs[month] = await requestJson(
        `/api/domestic-labor/night-shift/config/${month}/copy`,
        { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }
      );
      toast('已复制上月晋江不享有名单，请核对后再提交核算。');
      renderCanbuStepContent('upload');
    } catch (error) {
      setText(status, error.message, true);
      toast(error.message);
    }
  });
  document.querySelector('#nightShiftBreakSearch')?.addEventListener('input', (event) => {
    const keyword = event.target.value.trim().toLowerCase();
    document.querySelectorAll('[data-night-shift-break-row]').forEach(row => {
      row.hidden = Boolean(keyword) && !String(row.dataset.searchText || '').includes(keyword);
    });
  });
  document.querySelector('#btnSaveNightShiftBreaks')?.addEventListener('click', async () => {
    const batch = getActiveCanbuBatch();
    const month = nightShiftMonth(batch);
    const config = getNightShiftConfig(batch);
    const status = document.querySelector('#nightShiftConfigStatus');
    if (!month || !config) return;
    const overrides = collectNightShiftBreakOverrides(config);
    if (overrides.some(row => row.regular_hours !== null && !Number.isFinite(row.regular_hours))) {
      return toast('正班时数必须填写数字。');
    }
    setText(status, `正在保存 ${overrides.length} 条当月班次调整…`);
    try {
      state.nightShiftConfigs[month] = await requestJson(
        `/api/domestic-labor/night-shift/config/${month}`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            shift_break_overrides: overrides,
            jinjiang_exclusions: config.jinjiang_exclusions || [],
            jinjiang_list_confirmed: Boolean(config.jinjiang_list_confirmed),
          }),
        }
      );
      toast(overrides.length ? `已保存 ${overrides.length} 条当月班次调整。` : '已恢复使用完整平台班次基线。');
      renderCanbuStepContent('upload');
    } catch (error) {
      setText(status, error.message, true);
      toast(error.message);
    }
  });
  el.fileUploadZone?.addEventListener('click', (event) => {
    if (event.target === el.payrollFile) return;
    el.payrollFile?.click();
  });
  el.fileUploadZone?.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    el.payrollFile?.click();
  });
  el.payrollFile?.addEventListener('change', () => {
    const selectedFiles = Array.from(el.payrollFile.files || []);
    const existingKeys = new Set(state.payrollFiles.map(payrollFileKey));
    const addedFiles = selectedFiles.filter(file => !existingKeys.has(payrollFileKey(file)));
    state.payrollFiles = [...state.payrollFiles, ...addedFiles];
    el.payrollFile.value = '';
    const duplicateCount = selectedFiles.length - addedFiles.length;
    const message = duplicateCount
      ? `新增 ${addedFiles.length} 个文件，已跳过 ${duplicateCount} 个重复文件。`
      : `新增 ${addedFiles.length} 个文件，可继续选择追加。`;
    renderSelectedPayrollFiles(message);
  });
  submit?.addEventListener('click', submitCanbuBatch);
}

function renderCanbuFieldCheck(subject = getActiveWorkbenchSubject()) {
  const validationSummary = renderInputValidationSummary();
  const inputSummary = state.currentRun?.inputSummary || state.currentRun?.input_summary || {};
  if (subject === 'quanqinjiang') {
    return `
      <section class="dl-panel">
        <div class="dl-panel-head"><div><h2 class="dl-panel-title">字段检查</h2><p class="dl-panel-sub">字段检查按入离职、缺勤和异常考勤口径分组展示。</p></div></div>
        ${validationSummary}
        <div class="dl-field-groups">
          ${renderFieldGroup('基础员工字段', ['工号', '姓名', '考勤月份', '入职日期', '最后工作日'])}
          ${renderFieldGroup('迟到豁免字段（二选一）', ['迟到6分钟内(次)：最多3次', '迟到6-20分钟内(次)：最多1次', '迟到20-30分钟内(次)：出现即为0'])}
          ${renderFieldGroup('其他全勤判断字段', ['旷工天数', '正班迟到次数', '早退次数', '签卡次数', '迟到早退30分钟内扣款'])}
          ${renderFieldGroup('请假与缺勤字段', ['工伤假天数', '事假时数', '病假时数', '入离职缺勤时数'])}
          ${renderFieldGroup('月初入职辅助字段', ['出勤日期', '工作状态（有日考勤时优先使用）'])}
        </div>
        <div class="drawer-footer compact"><p class="inline-status">字段已识别，核算完成后可查看发放结果和判断原因。</p><button class="btn-primary-lg" type="button" id="btnGoCanbuResults">查看核算结果</button></div>
      </section>
    `;
  }
  if (subject === 'waisu_butie') {
    return `
      <section class="dl-panel">
        <div class="dl-panel-head"><div><h2 class="dl-panel-title">字段检查</h2><p class="dl-panel-sub">字段检查按外宿补贴资格、住宿区间和缺勤折算分组展示。</p></div></div>
        ${validationSummary}
        <div class="dl-field-groups">
          ${renderFieldGroup('基础员工字段', ['工号', '姓名', '工作地区', '岗位名称', '考勤月份', '入职日期', '最后工作日'])}
          ${renderFieldGroup('住宿名单字段', ['工号', '入住时间/入宿时间', '退宿时间/离宿时间'])}
          ${renderFieldGroup('缺勤折算字段', ['休年假小时', '事假时数', '病假时数', '排休请假时数/天数', '旷工时数/天数'])}
        </div>
        <div class="drawer-footer compact"><p class="inline-status">字段已识别，核算完成后可查看结果。</p><button class="btn-primary-lg" type="button" id="btnGoCanbuResults">查看核算结果</button></div>
      </section>
    `;
  }
  if (subject === 'yeban_butie') {
    const snapshot = state.currentRun?.nightShiftConfigSnapshot || state.currentRun?.night_shift_config_snapshot || {};
    return `
      <section class="dl-panel">
        <div class="dl-panel-head"><div><h2 class="dl-panel-title">字段与配置检查</h2><p class="dl-panel-sub">考勤事实与当月配置均已绑定到本次任务，后续修改配置不会改变本批次。</p></div></div>
        ${validationSummary}
        <div class="dl-field-groups">
          ${renderFieldGroup('员工基础字段', ['工号', '姓名', '考勤月份', '工作地区', '岗位名称'])}
          ${renderFieldGroup('日考勤字段', ['日期', '班次编号', '上班一', '下班一'])}
          ${renderFieldGroup('配置快照', [
            `月份 ${snapshot.month || nightShiftMonth()}`,
            `版本 ${snapshot.revision || '—'}`,
            `平台有效班次 ${(snapshot.shift_breaks || []).length} 条`,
            `当月班次调整 ${(snapshot.shift_break_overrides || []).length} 条`,
            '适用地区规则 固定内置',
            `晋江额外排除 ${(snapshot.jinjiang_exclusions || []).length} 人`,
            `晋江名单 ${snapshot.jinjiang_list_confirmed ? '已确认' : '未确认'}`,
          ])}
        </div>
        <div class="drawer-footer compact"><p class="inline-status">字段已识别；未命中配置、异常打卡和未确认规则会进入复核，不会自动计薪。</p><button class="btn-primary-lg" type="button" id="btnGoCanbuResults">查看核算结果</button></div>
      </section>
    `;
  }
  if (subject === 'gaowen_butie') {
    return `
      <section class="dl-panel">
        <div class="dl-panel-head"><div><h2 class="dl-panel-title">字段检查</h2><p class="dl-panel-sub">按员工组织归属、逐日出勤和同仓同日同班次测温三组依据检查。</p></div></div>
        ${validationSummary}
        <div class="dl-field-groups">
          ${renderFieldGroup('员工与网点识别', ['工号', '姓名', '工作地区', '岗位名称', '一级至六级部门名称'])}
          ${renderFieldGroup('日考勤字段', ['出勤日期', '班次名称/班次时间段', '正班时数', '刷卡加班', '实际上班时数'])}
          ${renderFieldGroup('测温登记字段', [
            '班次日期', '测温班次（白班/夜班）', '测温网点', '测温温度',
            `已识别测温记录 ${Number(inputSummary.temperature_rows || 0)} 条`,
          ])}
        </div>
        <div class="drawer-footer compact"><p class="inline-status">测温文件缺失不阻止任务，但测温区没有同班次记录时按0元；不会误判为无测温区域全额发放。</p><button class="btn-primary-lg" type="button" id="btnGoCanbuResults">查看核算结果</button></div>
      </section>
    `;
  }
  if (subject === 'gangwei_butie') {
    return `
      <section class="dl-panel">
        <div class="dl-panel-head"><div><h2 class="dl-panel-title">字段检查</h2><p class="dl-panel-sub">岗位补贴标准以2026年7月确认规则为依据；按岗位资格、月度标准和56小时缺勤门槛分组检查，职级不参与。</p></div></div>
        ${validationSummary}
        <div class="dl-field-groups">
          ${renderFieldGroup('资格与标准字段', ['工号', '姓名', '工作地区', '岗位名称', '排班天数', '实际在职工作日天数'])}
          ${renderFieldGroup('缺勤折算字段', ['事假时数', '排休请假时数', '病假时数', '旷工时数', '休年假小时', '其他带薪假时数', '调休时数', '入离职缺勤时数'])}
          ${renderFieldGroup('女神假字段', ['女神假天数×8小时后计入56小时门槛'])}
        </div>
        <div class="drawer-footer compact"><p class="inline-status">已有入离职缺勤时数优先；否则按排班天数与实际在职工作日天数自动计算，缺字段只提示、不阻止核算。</p><button class="btn-primary-lg" type="button" id="btnGoCanbuResults">查看核算结果</button></div>
      </section>
    `;
  }
  if (subject === 'gonglingjiang') {
    const requiresCollectionRoster = Boolean(inputSummary.requires_collection_seniority_roster);
    const collectionEmployeeCount = Number(inputSummary.collection_seniority_employee_count || 0);
    const rosterCount = normalizeCollectionRoster(getActiveCanbuBatch()?.collectionSeniorityRoster || []).length;
    return `
      <section class="dl-panel">
        <div class="dl-panel-head"><div><h2 class="dl-panel-title">字段检查</h2><p class="dl-panel-sub">字段检查按工龄、资格和线下缺勤折算口径分组展示。</p></div></div>
        ${validationSummary}
        <div class="dl-field-groups">
          ${renderFieldGroup('基础员工字段', ['工号', '姓名', '考勤月份', '一级部门名称', '二级部门名称', '岗位名称', '工作地区'])}
          ${renderFieldGroup('工龄与出勤字段', ['入职日期', '排班天数', '实际在职工作日天数', '正班出勤天数'])}
          ${renderFieldGroup('缺勤折算字段', ['事假时数', '病假时数', '旷工时数/天数', '排休请假时数/天数'])}
          ${renderFieldGroup('揽收线工龄奖名单', [
            requiresCollectionRoster
              ? `已识别第四纵队 ${collectionEmployeeCount} 人，已确认名单 ${rosterCount} 人`
              : '未识别到第四纵队，本批次无需维护名单',
          ])}
        </div>
        <div class="drawer-footer compact"><p class="inline-status">字段已识别，核算完成后可查看工龄、标准、折算过程和异常。</p><button class="btn-primary-lg" type="button" id="btnGoCanbuResults">查看核算结果</button></div>
      </section>
    `;
  }
  return `
    <section class="dl-panel">
      <div class="dl-panel-head">
        <div>
          <h2 class="dl-panel-title">字段检查</h2>
          <p class="dl-panel-sub">字段检查按餐补规则分组展示。文件上传后系统已自动提交餐补核算。</p>
        </div>
      </div>
      ${validationSummary}
      <div class="dl-field-groups">
        ${renderFieldGroup('基础员工字段', ['工号', '姓名', '一级部门', '二级部门', '岗位名称', '工作地区', '在职状态'])}
        ${renderFieldGroup('东莞日考勤字段', ['日期', '工作状态', '正班时数', '刷卡加班', '异常标记', '异常原因'])}
        ${renderFieldGroup('嘉善/义乌月考勤字段', ['排班天数', '实际在职工作日天数', '事假时数', '病假时数', '旷工天数'])}
      </div>
      <div class="drawer-footer compact">
        <p class="inline-status">字段已识别，核算完成后可查看结果。</p>
        <button class="btn-primary-lg" type="button" id="btnGoCanbuResults">查看核算结果</button>
      </div>
    </section>
  `;
}

function renderInputValidationSummary() {
  const summary = state.currentRun?.inputSummary || state.currentRun?.input_summary;
  if (!summary) return '';
  return `
    <div class="dl-result-summary">
      <div class="dl-result-stat primary"><span>文件数</span><strong>${Number(summary.file_count || 0)}</strong></div>
      <div class="dl-result-stat"><span>月考勤</span><strong>${Number(summary.monthly_rows || 0)}</strong></div>
      <div class="dl-result-stat"><span>日考勤</span><strong>${Number(summary.daily_rows || 0)}</strong></div>
      <div class="dl-result-stat"><span>住宿记录</span><strong>${Number(summary.housing_rows || 0)}</strong></div>
      <div class="dl-result-stat"><span>校验</span><strong>通过</strong></div>
    </div>
  `;
}

function renderFieldGroup(title, fields) {
  return `
    <div class="dl-field-group">
      <h3>${escapeHtml(title)}</h3>
      <div class="dl-field-grid">
        ${fields.map(field => `<span class="dl-field-pill ok">${escapeHtml(field)}</span>`).join('')}
      </div>
    </div>
  `;
}

function renderCanbuCalculatingState(batch) {
  const status = batch?.status || state.currentRun?.status || '计算中';
  const config = getWorkbenchConfig(batch?.subject);
  return `
    <section class="dl-panel">
      <div class="dl-calc-loading" role="status" aria-live="polite">
        <div class="dl-calc-spinner" aria-hidden="true"></div>
        <div>
          <h3>正在核算${escapeHtml(config.name)}</h3>
          <p>系统已收到本批次数据，正在解析考勤、匹配地区规则并生成应发${escapeHtml(config.name)}明细。当前状态：${escapeHtml(status)}。</p>
          <div class="dl-calc-steps" aria-hidden="true">
            <span>读取 Excel</span>
            <span>匹配字段</span>
            <span>计算${escapeHtml(config.name)}</span>
            <span>生成明细</span>
          </div>
        </div>
      </div>
    </section>
  `;
}

function renderQuanqinResults(results = []) {
  const root = document.querySelector('#canbuStepContent');
  if (!root) return;
  const rows = Array.isArray(results) ? results : [];
  const total = sumField(rows, 'quanqinjiang');
  const awardedCount = rows.filter(row => Number(row.quanqinjiang || 0) === 100).length;
  const zeroCount = rows.filter(row => Number(row.quanqinjiang || 0) === 0).length;
  const warnings = countSubjectWarnings(rows, 'quanqinjiang');
  root.innerHTML = `
    <section class="dl-panel">
      <div class="dl-panel-head"><div><h2 class="dl-panel-title">全勤奖核算</h2><p class="dl-panel-sub">按固定100元标准，复核入离职、缺勤、迟到早退和签卡判断结果。</p></div></div>
      <div class="dl-result-summary">
        <div class="dl-result-stat primary"><span>应发合计</span><strong>${formatMoney(total)}</strong></div>
        <div class="dl-result-stat"><span>员工数</span><strong>${rows.length}</strong></div>
        <div class="dl-result-stat"><span>发放人数</span><strong>${awardedCount}</strong></div>
        <div class="dl-result-stat"><span>不发放人数</span><strong>${zeroCount}</strong></div>
        <div class="dl-result-stat warning"><span>需处理</span><strong>${warnings}</strong></div>
      </div>
      <div class="dl-toolbar dl-toolbar-compact"><div class="dl-table-tools">
        <input class="dl-search" id="resultSearchInput" type="search" placeholder="筛选工号、姓名、部门" aria-label="筛选全勤奖结果">
        <select class="dl-select" id="reviewStatusFilter" aria-label="筛选异常状态"><option value="all">全部状态</option><option value="review">只看异常</option><option value="pass">只看通过</option></select>
        <select class="dl-select" id="amountFilter" aria-label="筛选金额状态"><option value="all">全部金额</option><option value="positive">发放100元</option><option value="zero">不发放</option></select>
        <span class="dl-result-count" id="resultCountText">—</span>
      </div></div>
      <div id="resultsTable" class="dl-table-wrap"></div><div class="dl-pagination" id="canbuPagination"></div>
    </section>
  `;
  el.resultsTable = document.querySelector('#resultsTable');
  el.resultSearchInput = document.querySelector('#resultSearchInput');
  el.reviewStatusFilter = document.querySelector('#reviewStatusFilter');
  el.amountFilter = document.querySelector('#amountFilter');
  el.resultCountText = document.querySelector('#resultCountText');
  el.canbuPagination = document.querySelector('#canbuPagination');
  if (el.resultSearchInput) el.resultSearchInput.value = state.resultSearch || '';
  if (el.reviewStatusFilter) el.reviewStatusFilter.value = ['all', 'review', 'pass'].includes(state.reviewStatusFilter) ? state.reviewStatusFilter : 'all';
  if (el.amountFilter) el.amountFilter.value = ['all', 'positive', 'zero'].includes(state.amountFilter) ? state.amountFilter : 'all';
  bindQuanqinResultFilters();
  renderQuanqinResultsTable(rows);
  renderExceptionQueue(rows);
}

function filterQuanqinResults(results) {
  const keyword = state.resultSearch.trim().toLowerCase();
  return results.filter(row => {
    const issue = hasSubjectReviewIssue(row, 'quanqinjiang');
    if (state.reviewStatusFilter === 'review' && !issue) return false;
    if (state.reviewStatusFilter === 'pass' && issue) return false;
    const amount = Number(row.quanqinjiang || 0);
    if (state.amountFilter === 'positive' && amount <= 0) return false;
    if (state.amountFilter === 'zero' && amount !== 0) return false;
    if (!keyword) return true;
    const detail = getSubjectDetail(row, 'quanqinjiang');
    const inputs = detail?.audit_explanation?.inputs || {};
    return [row.employee_id, row.employee_name, row.department, inputs['工作地区'], detail?.details?.reason, getEffectiveWarningText(row)]
      .map(value => String(value || '').toLowerCase()).join(' ').includes(keyword);
  });
}

function renderQuanqinResultsTable(results) {
  if (!el.resultsTable) return;
  const filtered = filterQuanqinResults(results);
  updateResultCount(results.length, filtered.length);
  const pages = Math.max(1, Math.ceil(filtered.length / state.canbuPageSize));
  state.canbuPage = Math.min(Math.max(state.canbuPage, 1), pages);
  const start = (state.canbuPage - 1) * state.canbuPageSize;
  const pageRows = filtered.slice(start, start + state.canbuPageSize);
  if (!filtered.length) {
    el.resultsTable.innerHTML = '<div class="dl-empty compact"><p>暂无全勤奖核算结果。</p></div>';
    renderQuanqinPagination(0, 0, 0);
    return;
  }
  el.resultsTable.innerHTML = `
    <table class="dl-table dl-result-table"><thead><tr>
      <th class="sticky-col id-col">工号</th><th class="sticky-col name-col">姓名</th><th>工作地区</th><th>部门</th><th>考勤月份</th><th>入职日期</th><th>最后工作日</th><th>判断结果</th><th class="dl-num">应发全勤奖</th><th>状态</th><th>解释</th>
    </tr></thead><tbody>${pageRows.map(row => {
      const detail = getSubjectDetail(row, 'quanqinjiang');
      const inputs = detail?.audit_explanation?.inputs || {};
      const issue = hasSubjectReviewIssue(row, 'quanqinjiang');
      const rowIndex = results.indexOf(row);
      return `<tr>
        <td class="sticky-col id-col dl-strong">${escapeHtml(row.employee_id)}</td><td class="sticky-col name-col">${escapeHtml(row.employee_name)}</td>
        <td>${escapeHtml(displayValue(inputs['工作地区'], '—'))}</td><td class="wrap-cell">${escapeHtml(displayValue(row.department, '—'))}</td><td>${escapeHtml(displayValue(inputs['考勤月份'], '—'))}</td>
        <td>${escapeHtml(displayValue(inputs['入职日期'], '—'))}</td><td>${escapeHtml(displayValue(inputs['最后工作日'], '—'))}</td><td>${escapeHtml(displayValue(detail?.details?.reason, '—'))}</td>
        <td class="dl-num dl-strong">${formatMoney(row.quanqinjiang)}</td><td><span class="dl-badge ${issue ? 'warn' : 'ok'}">${issue ? '需关注' : '通过'}</span></td><td><button class="dl-segment compact" data-quanqin-explain-index="${rowIndex}" type="button">计算过程</button></td>
      </tr>`;
    }).join('')}</tbody></table>
  `;
  el.resultsTable.querySelectorAll('[data-quanqin-explain-index]').forEach(button => button.addEventListener('click', () => openExplainDrawer(results[Number(button.dataset.quanqinExplainIndex)])));
  renderQuanqinPagination(filtered.length, start + 1, Math.min(start + pageRows.length, filtered.length));
}

function bindQuanqinResultFilters() {
  const rerender = () => { state.canbuPage = 1; renderQuanqinResultsTable(state.currentResults); };
  el.resultSearchInput?.addEventListener('input', () => { state.resultSearch = el.resultSearchInput.value.trim(); rerender(); });
  el.reviewStatusFilter?.addEventListener('change', () => { state.reviewStatusFilter = el.reviewStatusFilter.value; rerender(); });
  el.amountFilter?.addEventListener('change', () => { state.amountFilter = el.amountFilter.value; rerender(); });
}

function renderQuanqinPagination(total, start, end) {
  if (!el.canbuPagination) return;
  if (!total) { el.canbuPagination.innerHTML = ''; return; }
  const pages = Math.max(1, Math.ceil(total / state.canbuPageSize));
  el.canbuPagination.innerHTML = `<span>${start}-${end} / ${total}</span><div class="dl-pagination-actions"><button class="dl-segment compact" data-quanqin-page="prev" type="button" ${state.canbuPage <= 1 ? 'disabled' : ''}>上一页</button><strong>${state.canbuPage} / ${pages}</strong><button class="dl-segment compact" data-quanqin-page="next" type="button" ${state.canbuPage >= pages ? 'disabled' : ''}>下一页</button></div>`;
  el.canbuPagination.querySelectorAll('[data-quanqin-page]').forEach(button => button.addEventListener('click', () => { state.canbuPage += button.dataset.quanqinPage === 'prev' ? -1 : 1; renderQuanqinResultsTable(state.currentResults); }));
}

function renderCanbuResults(results = []) {
  const root = document.querySelector('#canbuStepContent');
  if (!root) return;
  const canbuResults = Array.isArray(results) ? results : [];
  const total = sumField(canbuResults, 'canbu');
  const warnings = countCanbuWarnings(canbuResults);
  const capCount = canbuResults.filter(row => Number(row.canbu || 0) >= 500).length;
  const positiveCount = canbuResults.filter(row => Number(row.canbu || 0) > 0).length;
  if (!getCanbuRegionFilterValues(canbuResults).includes(state.canbuRegionFilter)) {
    state.canbuRegionFilter = 'all';
  }
  root.innerHTML = `
    <section class="dl-panel">
      <div class="dl-panel-head">
        <div>
          <h2 class="dl-panel-title">餐补核算</h2>
          <p class="dl-panel-sub">按线下结果表口径查看应发餐补、适用规则和计算过程。</p>
        </div>
      </div>
      <div class="dl-result-summary">
        <div class="dl-result-stat primary"><span>应发合计</span><strong>${formatMoney(total)}</strong></div>
        <div class="dl-result-stat"><span>员工数</span><strong>${canbuResults.length}</strong></div>
        <div class="dl-result-stat"><span>享有人数</span><strong>${positiveCount}</strong></div>
        <div class="dl-result-stat"><span>封顶人数</span><strong>${capCount}</strong></div>
        <div class="dl-result-stat warning"><span>需处理</span><strong>${warnings}</strong></div>
      </div>
      <div class="dl-result-tabs" id="canbuRegionTabs">
        ${renderCanbuRegionTabs(canbuResults)}
      </div>
      <div class="dl-toolbar dl-toolbar-compact">
        <div class="dl-table-tools">
          <input class="dl-search" id="resultSearchInput" type="search" placeholder="筛选工号、姓名、部门" aria-label="筛选工号、姓名、部门">
          <select class="dl-select" id="reviewStatusFilter" aria-label="筛选异常状态">
            <option value="all">全部状态</option>
            <option value="review">只看异常</option>
            <option value="pass">只看通过</option>
          </select>
          <select class="dl-select" id="amountFilter" aria-label="筛选金额状态">
            <option value="all">全部金额</option>
            <option value="positive">应发大于0</option>
            <option value="zero">应发为0</option>
          </select>
          <span class="dl-result-count" id="resultCountText">—</span>
        </div>
      </div>
      <div id="resultsTable" class="dl-table-wrap"></div>
      <div class="dl-pagination" id="canbuPagination"></div>
    </section>
  `;
  el.resultsTable = document.querySelector('#resultsTable');
  el.resultSearchInput = document.querySelector('#resultSearchInput');
  el.reviewStatusFilter = document.querySelector('#reviewStatusFilter');
  el.amountFilter = document.querySelector('#amountFilter');
  el.resultCountText = document.querySelector('#resultCountText');
  el.canbuPagination = document.querySelector('#canbuPagination');
  const filterValue = (value, allowed) => (allowed.includes(value) ? value : allowed[0]);
  const canbuReviewFilter = filterValue(state.reviewStatusFilter, ['all', 'review', 'pass']);
  const canbuAmountFilter = filterValue(state.amountFilter, ['all', 'positive', 'zero']);
  state.reviewStatusFilter = canbuReviewFilter;
  state.amountFilter = canbuAmountFilter;
  if (el.resultSearchInput) el.resultSearchInput.value = state.resultSearch || '';
  if (el.reviewStatusFilter) el.reviewStatusFilter.value = canbuReviewFilter;
  if (el.amountFilter) el.amountFilter.value = canbuAmountFilter;
  bindCanbuResultFilters();
  bindCanbuRegionTabs();
  renderCanbuResultsTable(canbuResults);
  renderCanbuExceptionQueue(canbuResults);
}

function renderCanbuRegionTabs(results) {
  const items = getCanbuRegionTabs(results);
  return items.map(item => `
    <button class="dl-result-tab ${state.canbuRegionFilter === item.value ? 'active' : ''}" data-canbu-region="${escapeHtml(item.value)}" type="button">
      <span>${escapeHtml(item.label)}</span>
      <strong>${item.count}</strong>
    </button>
  `).join('');
}

function getCanbuRegionTabs(results) {
  const base = [{ value: 'all', label: '全部', count: results.length }];
  const regionCounts = new Map();
  results.forEach(row => {
    const region = getCanbuRowRegion(row);
    regionCounts.set(region, (regionCounts.get(region) || 0) + 1);
  });
  Array.from(regionCounts.entries())
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'zh-CN'))
    .forEach(([region, count]) => base.push({ value: region, label: region, count }));
  const issueCount = results.filter(hasCanbuReviewIssue).length;
  if (issueCount) base.push({ value: '__issues__', label: '需处理', count: issueCount });
  return base;
}

function getCanbuRegionFilterValues(results) {
  return getCanbuRegionTabs(results).map(item => item.value);
}

function getCanbuRowRegion(row) {
  const detail = getSubjectDetail(row, 'canbu');
  const inputs = detail?.audit_explanation?.inputs || {};
  return String(inputs['工作地区'] || row.work_region || row.region || '未识别').trim() || '未识别';
}

function renderCanbuResultsTable(results) {
  const filtered = filterCanbuResults(results || []);
  if (!el.resultsTable) return;
  updateResultCount(results.length, filtered.length);
  const totalPages = Math.max(1, Math.ceil(filtered.length / state.canbuPageSize));
  if (state.canbuPage > totalPages) state.canbuPage = totalPages;
  if (state.canbuPage < 1) state.canbuPage = 1;
  const pageStart = (state.canbuPage - 1) * state.canbuPageSize;
  const pageRows = filtered.slice(pageStart, pageStart + state.canbuPageSize);
  if (!filtered.length) {
    el.resultsTable.innerHTML = '<div class="dl-empty compact"><p>暂无餐补核算结果。</p></div>';
    renderCanbuPagination(0, 0, 0);
    return;
  }
  el.resultsTable.innerHTML = `
    <table class="dl-table dl-result-table">
      <thead>
        <tr>
          <th class="sticky-col id-col">工号</th>
          <th class="sticky-col name-col">姓名</th>
          <th>工作地区</th>
          <th>部门</th>
          <th>岗位</th>
          <th>餐补资格</th>
          <th class="dl-num">有效出勤</th>
          <th>扣减项</th>
          <th class="dl-num">应发餐补</th>
          <th>异常</th>
          <th>解释</th>
        </tr>
      </thead>
      <tbody>
        ${pageRows.map(row => {
          const level = getCanbuWarningLevel(row);
          const detail = getSubjectDetail(row, 'canbu');
          const inputs = detail?.audit_explanation?.inputs || {};
          const employeeId = displayValue(row.employee_id, inputs['工号']);
          const employeeName = displayValue(row.employee_name, row.name, inputs['姓名']);
          const department = displayValue(row.department, inputs['部门字段'], '—');
          const position = displayValue(row.position, inputs['岗位名称'], '—');
          const rowIndex = results.indexOf(row);
          return `
            <tr>
              <td class="sticky-col id-col dl-strong">${escapeHtml(employeeId)}</td>
              <td class="sticky-col name-col">${escapeHtml(employeeName)}</td>
              <td>${escapeHtml(getCanbuRowRegion(row))}</td>
              <td class="wrap-cell" title="${escapeHtml(department)}">${escapeHtml(department)}</td>
              <td class="wrap-cell" title="${escapeHtml(position)}">${escapeHtml(position)}</td>
              <td><span class="dl-badge ${Number(row.canbu || 0) > 0 ? 'ok' : 'warn'}">${Number(row.canbu || 0) > 0 ? '享有' : '不享有/未发放'}</span></td>
              <td class="dl-num">${escapeHtml(inputs['有效出勤'] || inputs['有效时数'] || '—')}</td>
              <td>${escapeHtml(inputs['扣减项'] || '—')}</td>
              <td class="dl-num dl-strong">${formatMoney(row.canbu)}</td>
              <td><span class="dl-badge ${level.className}">${level.label}</span></td>
              <td><button class="dl-segment compact" data-canbu-explain-index="${rowIndex}" type="button">计算过程</button></td>
            </tr>
          `;
        }).join('')}
      </tbody>
    </table>
  `;
  el.resultsTable.querySelectorAll('[data-canbu-explain-index]').forEach(item => {
    item.addEventListener('click', () => {
      const index = Number(item.dataset.canbuExplainIndex);
      openCanbuExplainDrawer(results[index]);
    });
  });
  renderCanbuPagination(filtered.length, pageStart + 1, Math.min(pageStart + pageRows.length, filtered.length));
}

function bindCanbuResultFilters() {
  el.resultSearchInput?.addEventListener('compositionstart', () => {
    state.canbuSearchComposing = true;
  });
  el.resultSearchInput?.addEventListener('compositionend', () => {
    state.canbuSearchComposing = false;
    state.resultSearch = el.resultSearchInput.value.trim();
    state.canbuPage = 1;
    renderCanbuResultsTable(state.currentResults);
  });
  el.resultSearchInput?.addEventListener('input', () => {
    if (state.canbuSearchComposing) return;
    state.resultSearch = el.resultSearchInput.value.trim();
    state.canbuPage = 1;
    renderCanbuResultsTable(state.currentResults);
  });
  el.reviewStatusFilter?.addEventListener('change', () => {
    state.reviewStatusFilter = el.reviewStatusFilter.value;
    state.canbuPage = 1;
    renderCanbuResultsTable(state.currentResults);
  });
  el.amountFilter?.addEventListener('change', () => {
    state.amountFilter = el.amountFilter.value;
    state.canbuPage = 1;
    renderCanbuResultsTable(state.currentResults);
  });
}

function bindCanbuRegionTabs() {
  document.querySelectorAll('[data-canbu-region]').forEach(button => {
    button.addEventListener('click', () => {
      state.canbuRegionFilter = button.dataset.canbuRegion || 'all';
      state.canbuPage = 1;
      document.querySelectorAll('[data-canbu-region]').forEach(item => {
        item.classList.toggle('active', item === button);
      });
      renderCanbuResultsTable(state.currentResults);
    });
  });
}

function renderCanbuPagination(total, start, end) {
  if (!el.canbuPagination) return;
  if (!total) {
    el.canbuPagination.innerHTML = '';
    return;
  }
  const totalPages = Math.max(1, Math.ceil(total / state.canbuPageSize));
  el.canbuPagination.innerHTML = `
    <span>${start}-${end} / ${total}</span>
    <div class="dl-pagination-actions">
      <button class="dl-segment compact" data-canbu-page="prev" type="button" ${state.canbuPage <= 1 ? 'disabled' : ''}>上一页</button>
      <strong>${state.canbuPage} / ${totalPages}</strong>
      <button class="dl-segment compact" data-canbu-page="next" type="button" ${state.canbuPage >= totalPages ? 'disabled' : ''}>下一页</button>
    </div>
  `;
  el.canbuPagination.querySelectorAll('[data-canbu-page]').forEach(button => {
    button.addEventListener('click', () => {
      const direction = button.dataset.canbuPage;
      if (direction === 'prev') state.canbuPage -= 1;
      if (direction === 'next') state.canbuPage += 1;
      renderCanbuResultsTable(state.currentResults);
    });
  });
}

function renderCanbuExceptionQueue(results) {
  if (!el.exceptionQueue) return;
  const rows = results.filter(hasCanbuReviewIssue);
  if (!rows.length) {
    el.exceptionQueue.innerHTML = `
      <div class="dl-exception">
        <p class="dl-exception-title">暂无异常</p>
        <p class="dl-exception-meta">完成计算后，餐补可复核异常会进入这里。</p>
      </div>
    `;
    return;
  }
  el.exceptionQueue.innerHTML = rows.map((row) => {
    const firstException = getCanbuReviewExceptions(row)[0];
    const level = getCanbuWarningLevel(row);
    const message = firstException?.message || getCanbuWarningMessage(row);
    return `
      <button class="dl-exception ${level.className}" data-exception-id="${escapeHtml(row.employee_id)}" type="button">
        <p class="dl-exception-title">${level.label} · ${escapeHtml(row.employee_id)} ${escapeHtml(row.employee_name)}</p>
        <p class="dl-exception-meta">${escapeHtml(message)}</p>
      </button>
    `;
  }).join('');
  el.exceptionQueue.querySelectorAll('[data-exception-id]').forEach((item) => {
    item.addEventListener('click', () => {
      const row = results.find(candidate => candidate.employee_id === item.dataset.exceptionId);
      if (row) openCanbuExplainDrawer(row);
    });
  });
}

function filterCanbuResults(results) {
  const keyword = state.resultSearch.trim().toLowerCase();
  return results.filter(row => {
    if (state.canbuRegionFilter === '__issues__' && !hasCanbuReviewIssue(row)) return false;
    if (state.canbuRegionFilter !== 'all' && state.canbuRegionFilter !== '__issues__' && getCanbuRowRegion(row) !== state.canbuRegionFilter) return false;
    if (state.reviewStatusFilter === 'review' && !hasCanbuReviewIssue(row)) return false;
    if (state.reviewStatusFilter === 'pass' && hasCanbuReviewIssue(row)) return false;
    const amount = Number(row.canbu || 0);
    if (state.amountFilter === 'positive' && amount <= 0) return false;
    if (state.amountFilter === 'zero' && amount !== 0) return false;
    if (!keyword) return true;
    return [
      row.employee_id,
      row.employee_name,
      row.department,
      row.position,
      getCanbuWarningMessage(row),
      getEffectiveWarningText(row),
    ].map(value => String(value || '').toLowerCase()).join(' ').includes(keyword);
  });
}

function openCanbuExplainDrawer(row) {
  if (!row || !el.calcModal || !el.calcModalTitle || !el.calcModalBody) return;
  el.calcModalTitle.textContent = `${row.employee_id || ''} ${row.employee_name || ''} · 计算过程`;
  if (el.calcModalSub) el.calcModalSub.textContent = '展示本员工餐补的规则来源、关键输入和计算公式。';
  const detail = getSubjectDetail(row, 'canbu');
  const explanation = detail?.audit_explanation || {};
  const rowExceptions = getCanbuReviewExceptions(row);
  const warningText = getEffectiveWarningText(row);
  el.calcModalBody.innerHTML = `
    <div class="dl-kv-grid">
      <div class="dl-kv"><span>部门</span><strong>${escapeHtml(row.department || '—')}</strong></div>
      <div class="dl-kv"><span>岗位</span><strong>${escapeHtml(row.position || '—')}</strong></div>
      <div class="dl-kv"><span>应发餐补</span><strong>${formatMoney(row.canbu)}</strong></div>
      <div class="dl-kv"><span>异常状态</span><strong>${hasCanbuReviewIssue(row) ? '需关注' : '通过'}</strong></div>
    </div>
    <div class="dl-rule-card">
      <h3>规则命中</h3>
      <dl>
        <dt>规则状态</dt><dd>${escapeHtml(explanation.rule_name || '餐补规则')}</dd>
        <dt>计算公式</dt><dd>${escapeHtml(explanation.formula || '按工作地区、岗位资格、有效出勤和月度封顶计算。')}</dd>
        <dt>关键输入</dt><dd>${formatAuditMap(explanation.inputs)}</dd>
        <dt>中间值</dt><dd>${formatAuditMap(explanation.intermediate_values)}</dd>
        <dt>计算步骤</dt><dd>${formatAuditSteps(explanation.steps) || '按餐补规则计算应发金额。'}</dd>
      </dl>
    </div>
    <div class="dl-rule-card">
      <h3>异常与建议</h3>
      <dl>
        <dt>异常等级</dt><dd>${getCanbuWarningLevel(row).label}</dd>
        <dt>异常说明</dt><dd>${formatExceptions(rowExceptions) || escapeHtml(warningText || '暂无异常')}</dd>
        <dt>建议动作</dt><dd>${rowExceptions[0]?.suggested_action ? escapeHtml(rowExceptions[0].suggested_action) : '无需人工处理。'}</dd>
      </dl>
    </div>
  `;
  el.calcModal.classList.add('visible');
  document.body.style.overflow = 'hidden';
}

function getNightShiftDetails(row) {
  return getSubjectDetail(row, 'yeban_butie')?.details || {};
}

function getNightShiftDailyCounts(row) {
  const details = getNightShiftDetails(row);
  return {
    calculated: Number(details.calculated_days || 0),
    excluded: Number(details.excluded_days || 0),
    manual: Number(details.manual_review_days || 0),
    pending: Number(details.pending_rule_days || 0),
    reviewCalculated: Number(details.review_calculated_days || 0),
    unpricedReview: Number(details.unpriced_review_days || 0),
  };
}

function getNightShiftReasonLabel(reasonCode) {
  const labels = {
    generic_rule: '按通用夜班规则计算',
    invalid_attendance_date: '出勤日期缺失或格式错误',
    missing_punch: '员工缺勤（考勤异常）',
    implausible_duration: '上下班时长超出合理范围',
    no_effective_attendance: '取整后没有有效出勤时段',
    no_night_overlap: '当天未覆盖夜班时段',
    no_scheduled_night_work: '当天排班无需计算夜班补贴',
    invalid_break_period: '班次休息时间配置错误',
    partial_break_overlap: '实际出勤只覆盖部分休息时段',
    negative_effective_duration: '扣除休息后没有有效夜班时长',
    three_am_shift_pending: '凌晨3点班早退口径待确认',
    work_area_scope_pending: '工作地区口径待确认',
    jinjiang_special_list_unconfirmed: '晋江特殊名单尚未确认',
    jinjiang_piecework_excluded: '晋江计件岗位不享有夜班补贴',
    jinjiang_special_list_excluded: '属于晋江不享有夜班补贴名单',
    jinjiang_gatekeeper_excluded: '晋江门禁岗位不享有夜班补贴',
    shift_break_config_missing: '班次休息时间尚未维护',
  };
  return labels[reasonCode] || '需要核对当天考勤或业务口径';
}

function formatNightShiftAttendanceDate(value) {
  const text = String(value || '').trim();
  const matched = text.match(/\d{4}-\d{2}-\d{2}/);
  return matched ? matched[0] : (text || '日期缺失');
}

function formatNightShiftMinutesAsClock(value) {
  if (value === null || value === undefined || value === '') return '—';
  const minutes = Number(value);
  if (!Number.isFinite(minutes)) return '—';
  const dayOffset = Math.floor(minutes / (24 * 60));
  const minuteOfDay = ((Math.round(minutes) % (24 * 60)) + (24 * 60)) % (24 * 60);
  const hour = String(Math.floor(minuteOfDay / 60)).padStart(2, '0');
  const minute = String(minuteOfDay % 60).padStart(2, '0');
  return `${dayOffset > 0 ? '次日' : ''}${hour}:${minute}`;
}

function formatNightShiftBreakHours(value) {
  if (value === null || value === undefined || value === '') return '—';
  const minutes = Number(value);
  return Number.isFinite(minutes) ? (minutes / 60).toFixed(2) : '—';
}

function getNightShiftDailyAction(daily) {
  const status = String(daily?.status || '');
  const reasonCode = String(daily?.reason_code || '');
  if (status === 'calculated_review' || status === 'calculated_pending') {
    return `当日${formatMoney(daily?.amount)}元已计入，请确认后留档`;
  }
  if (reasonCode === 'missing_punch') return '员工当天缺勤，按考勤异常处理，当日不计夜班补贴';
  if (reasonCode === 'shift_break_config_missing' || reasonCode === 'invalid_break_period') {
    return '维护该班次休息时间后重新核算；当前金额未包含这一天';
  }
  if (status === 'pending_rule') return '确认当天业务口径后重新核算；当前金额未包含这一天';
  return '核对当天原始考勤后重新核算；当前金额未包含这一天';
}

function renderNightShiftExplanation(row) {
  const details = getNightShiftDetails(row);
  const counts = getNightShiftDailyCounts(row);
  const dailyResults = Array.isArray(details.daily_results) ? details.daily_results : [];
  const resultStatus = getNightShiftResultStatus(row);
  const actionRows = dailyResults.filter(daily => [
    'manual_review', 'pending_rule', 'calculated_review', 'calculated_pending',
  ].includes(String(daily?.status || '')));
  const actionHtml = actionRows.length ? actionRows.map(daily => {
    const date = formatNightShiftAttendanceDate(daily.attendance_date);
    const shift = String(daily.shift_code || '').trim();
    const reason = getNightShiftReasonLabel(daily.reason_code);
    return `
      <div class="dl-explain-action">
        <strong>${escapeHtml(date)}</strong>
        <span>${escapeHtml(reason)}${shift ? ` · 班次${escapeHtml(shift)}` : ''}</span>
        <em>${escapeHtml(getNightShiftDailyAction(daily))}</em>
      </div>
    `;
  }).join('') : '<div class="dl-explain-empty">本月没有需要人工处理的日期。</div>';
  const includedText = counts.reviewCalculated > 0
    ? `正常核算${counts.calculated}天；另有${counts.reviewCalculated}天暂算金额已计入，待确认。`
    : `正常核算${counts.calculated}天，没有暂算金额。`;
  const unpricedText = counts.unpricedReview > 0
    ? `${counts.unpricedReview}天；当前应发金额未包含这些日期。`
    : '0天；所有需要计薪的日期均已计入。';
  const dailyBreakdownHtml = dailyResults.length ? `
    <div class="dl-night-daily-wrap">
      <table class="dl-night-daily-table">
        <thead><tr>
          <th>出勤日期</th><th>班次</th><th>计薪上班</th><th>计薪下班</th><th>夜班时长</th>
          <th>晚上休息扣除</th><th>早上休息扣除</th><th>休息扣除合计</th><th>当日补贴</th>
        </tr></thead>
        <tbody>${dailyResults.map(daily => `
          <tr>
            <td>${escapeHtml(formatNightShiftAttendanceDate(daily.attendance_date))}</td>
            <td>${escapeHtml(daily.shift_code || '—')}</td>
            <td>${escapeHtml(formatNightShiftMinutesAsClock(daily.rounded_start_minutes))}</td>
            <td>${escapeHtml(formatNightShiftMinutesAsClock(daily.rounded_end_minutes))}</td>
            <td>${escapeHtml(formatNightShiftBreakHours(daily.night_minutes))}</td>
            <td>${escapeHtml(formatNightShiftBreakHours(daily.evening_break_minutes))}</td>
            <td>${escapeHtml(formatNightShiftBreakHours(daily.morning_break_minutes))}</td>
            <td>${escapeHtml(formatNightShiftBreakHours(daily.break_minutes))}</td>
            <td>${daily.amount === null || daily.amount === undefined ? '—' : escapeHtml(formatMoney(daily.amount))}</td>
          </tr>
        `).join('')}</tbody>
      </table>
    </div>
  ` : '<div class="dl-explain-empty">本月没有日考勤计算明细。</div>';

  el.explainTitle.textContent = `${row.employee_id || ''} ${row.employee_name || ''} · 夜班补贴`;
  el.explainBody.innerHTML = `
    <div class="dl-kv-grid">
      <div class="dl-kv"><span>本月应发</span><strong>${formatMoney(row.yeban_butie)}</strong></div>
      <div class="dl-kv"><span>本月核算结果</span><strong>${escapeHtml(resultStatus.label)}</strong></div>
      <div class="dl-kv"><span>需处理日期</span><strong>${actionRows.length}天</strong></div>
    </div>
    <div class="dl-rule-card">
      <h3>这笔钱是怎么得出的</h3>
      <dl>
        <dt>本月考勤</dt><dd>${dailyResults.length}天</dd>
        <dt>已计入金额</dt><dd>${escapeHtml(includedText)}以上日期的每日夜班补贴相加，得到本月应发${formatMoney(row.yeban_butie)}元。</dd>
        <dt>无需补贴</dt><dd>${counts.excluded}天；当天没有符合夜班补贴的有效时长。</dd>
        <dt>异常未计金额日</dt><dd>${escapeHtml(unpricedText)}</dd>
        <dt>计算口径</dt><dd>只计算22:00至次日08:00内的有效时长；上下班时间按半小时取整，按班次配置分别扣除晚上休息和早上休息，再按3元/小时计算，单日最高25元。</dd>
      </dl>
    </div>
    <div class="dl-rule-card">
      <h3>每日计算明细（${dailyResults.length}天）</h3>
      ${dailyBreakdownHtml}
    </div>
    <div class="dl-rule-card">
      <h3>需要处理的日期（${actionRows.length}天）</h3>
      <p class="dl-explain-summary">暂算日期的金额已经计入；员工缺勤等考勤异常或缺少核算依据的日期不计金额，具体原因见下方明细。</p>
      <div class="dl-explain-actions">${actionHtml}</div>
    </div>
  `;
}

const HIGH_TEMPERATURE_REASON_LABELS = {
  calculated: '同仓同日同班次最高温达到33℃，按实际出勤折算',
  temperature_below_33: '同班次最高温未达到33℃',
  no_matching_temperature: '没有匹配到同仓同日同班次测温',
  actual_attendance_zero: '无正班且仅有0.5小时内残留刷卡，按无实际出勤处理',
  no_actual_attendance: '没有可计发的实际出勤时长',
  outside_high_temperature_season: '不在6月至10月高温津贴期间',
  employee_or_position_excluded: '命中地区固定排除人员或岗位规则',
  measurement_site_unresolved: '无法识别员工对应测温网点',
  attendance_shift_unresolved: '无法从考勤识别白班或夜班',
  invalid_attendance_date: '出勤日期缺失或格式错误',
};

function renderHighTemperatureExplanation(row) {
  const subject = getSubjectDetail(row, 'gaowen_butie') || {};
  const details = subject.details || {};
  const dailyResults = Array.isArray(details.daily_results) ? details.daily_results : [];
  const payableRows = dailyResults.filter(daily => daily.status === 'calculated');
  const missingMeasurements = dailyResults.filter(daily => daily.reason_code === 'no_matching_temperature');
  const exceptions = getSubjectExceptions(row, 'gaowen_butie');
  const actionHtml = exceptions.length
    ? exceptions.map(item => `
        <div class="dl-explain-action">
          <strong>${escapeHtml(item.level === 'blocking' ? '阻断' : '需确认')}</strong>
          <span>${escapeHtml(item.message || '高温补贴口径待确认')}</span>
          <em>${escapeHtml(item.suggested_action || '核对测温与人员口径后重新核算')}</em>
        </div>
      `).join('')
    : '<div class="dl-explain-empty">本月没有平台已识别的异常。</div>';
  const dailyBreakdownHtml = dailyResults.length ? `
    <div class="dl-night-daily-wrap">
      <table class="dl-night-daily-table">
        <thead><tr>
          <th>出勤日期</th><th>班次</th><th>测温网点</th><th>最高温</th><th>计薪时长</th><th>当日结果</th><th>当日补贴</th>
        </tr></thead>
        <tbody>${dailyResults.map(daily => {
          const temperature = daily.temperature === null || daily.temperature === undefined ? '—' : `${Number(daily.temperature).toFixed(1)}℃`;
          const reason = HIGH_TEMPERATURE_REASON_LABELS[daily.reason_code] || daily.reason_code || '原因待确认';
          return `
            <tr>
              <td>${escapeHtml(formatNightShiftAttendanceDate(daily.attendance_date))}</td>
              <td>${escapeHtml(daily.shift || '—')}</td>
              <td>${escapeHtml(daily.site || '—')}</td>
              <td>${escapeHtml(temperature)}</td>
              <td>${escapeHtml(Number(daily.attendance_hours || 0).toFixed(2))}小时</td>
              <td>${escapeHtml(reason)}</td>
              <td>${escapeHtml(formatMoney(daily.amount || 0))}</td>
            </tr>
          `;
        }).join('')}</tbody>
      </table>
    </div>
  ` : '<div class="dl-explain-empty">本月没有日考勤计算明细。</div>';

  el.explainTitle.textContent = `${row.employee_id || ''} ${row.employee_name || ''} · 高温补贴`;
  el.explainBody.innerHTML = `
    <div class="dl-kv-grid">
      <div class="dl-kv"><span>本月应发</span><strong>${formatMoney(row.gaowen_butie)}</strong></div>
      <div class="dl-kv"><span>对应测温网点</span><strong>${escapeHtml(details['测温网点'] || '待确认')}</strong></div>
      <div class="dl-kv"><span>高温出勤日</span><strong>${Number(details['高温出勤天数'] || 0)}天</strong></div>
      <div class="dl-kv"><span>计发日</span><strong>${payableRows.length}天</strong></div>
    </div>
    <div class="dl-rule-card">
      <h3>这笔钱是怎么得出的</h3>
      <dl>
        <dt>测温匹配</dt><dd>按同测温网点、同出勤日期、同白/夜班取最高温；达到33℃才计算当天金额。</dd>
        <dt>计薪时长</dt><dd>取正班时数与刷卡加班较大值；无正班且只有0.5小时内残留刷卡时按无实际出勤处理。</dd>
        <dt>当日金额</dt><dd>计薪时长 × ${escapeHtml(displayValue(details['小时单价'], 0))}元，单日最高${escapeHtml(displayValue(details['单日封顶'], 0))}元。</dd>
        <dt>本月金额</dt><dd>${payableRows.length}个计发日逐日相加，月度最高${escapeHtml(displayValue(details['月度封顶'], 0))}元，得到${formatMoney(row.gaowen_butie)}。</dd>
        <dt>缺少测温</dt><dd>${missingMeasurements.length}天；这些日期当前按0元处理，不会借用其他仓、其他日期或其他班次温度。</dd>
      </dl>
    </div>
    <div class="dl-rule-card">
      <h3>每日计算明细（${dailyResults.length}天）</h3>
      ${dailyBreakdownHtml}
    </div>
    <div class="dl-rule-card">
      <h3>需要处理的事项（${exceptions.length}项）</h3>
      <div class="dl-explain-actions">${actionHtml}</div>
    </div>
  `;
}

function hasNightShiftReviewIssue(row) {
  const counts = getNightShiftDailyCounts(row);
  return counts.manual > 0 || counts.pending > 0 || getSubjectExceptions(row, 'yeban_butie').length > 0;
}

function getNightShiftResultStatus(row) {
  const counts = getNightShiftDailyCounts(row);
  const actions = [];
  if (counts.reviewCalculated > 0) actions.push(`确认${counts.reviewCalculated}天暂算结果`);
  if (counts.unpricedReview > 0) actions.push(`查看${counts.unpricedReview}天异常未计金额原因`);
  if (counts.unpricedReview > 0 && counts.reviewCalculated > 0) {
    return { className: 'warn', label: '金额已核算（含暂算，不含异常未计金额日）', action: actions.join('；') };
  }
  if (counts.unpricedReview > 0) {
    return { className: 'warn', label: '金额已核算（不含异常未计金额日）', action: actions.join('；') };
  }
  if (counts.reviewCalculated > 0 || counts.manual > 0 || counts.pending > 0) {
    return { className: 'warn', label: '金额已核算（含暂算）', action: actions.join('；') || '复核异常或特殊情况' };
  }
  return { className: 'ok', label: '核算完成', action: '无需处理' };
}

function filterNightShiftResults(results) {
  const keyword = state.resultSearch.trim().toLowerCase();
  return (results || []).filter(row => {
    const issue = hasNightShiftReviewIssue(row);
    if (state.reviewStatusFilter === 'review' && !issue) return false;
    if (state.reviewStatusFilter === 'pass' && issue) return false;
    const amount = Number(row.yeban_butie || 0);
    if (state.amountFilter === 'positive' && amount <= 0) return false;
    if (state.amountFilter === 'zero' && amount !== 0) return false;
    if (!keyword) return true;
    const inputs = getSubjectDetail(row, 'yeban_butie')?.audit_explanation?.inputs || {};
    return [row.employee_id, row.employee_name, row.department, inputs['工作地区'], inputs['岗位名称'], getEffectiveWarningText(row)]
      .map(value => String(value || '').toLowerCase()).join(' ').includes(keyword);
  });
}

function renderNightShiftResults(results = []) {
  const root = document.querySelector('#canbuStepContent');
  if (!root) return;
  const rows = Array.isArray(results) ? results : [];
  const totals = rows.reduce((summary, row) => {
    const counts = getNightShiftDailyCounts(row);
    summary.calculated += counts.calculated;
    summary.excluded += counts.excluded;
    summary.manual += counts.manual;
    summary.pending += counts.pending;
    summary.reviewCalculated += counts.reviewCalculated;
    summary.unpricedReview += counts.unpricedReview;
    return summary;
  }, { calculated: 0, excluded: 0, manual: 0, pending: 0, reviewCalculated: 0, unpricedReview: 0 });
  root.innerHTML = `
    <section class="dl-panel">
      <div class="dl-panel-head"><div><h2 class="dl-panel-title">夜班补贴核算</h2><p class="dl-panel-sub">结果按证据状态分层：自动核算可发放，明确排除不发放，异常与未确认口径进入复核。</p></div></div>
      <div class="dl-result-summary">
        <div class="dl-result-stat primary"><span>核算合计（含暂算）</span><strong>${formatMoney(sumField(rows, 'yeban_butie'))}</strong></div>
        <div class="dl-result-stat"><span>正常核算日</span><strong>${totals.calculated}</strong></div>
        <div class="dl-result-stat"><span>无需补贴日</span><strong>${totals.excluded}</strong></div>
        <div class="dl-result-stat warning"><span>暂算需确认日</span><strong>${totals.reviewCalculated}</strong></div>
        <div class="dl-result-stat warning"><span>异常未计金额日</span><strong>${totals.unpricedReview}</strong></div>
      </div>
      <div class="dl-toolbar dl-toolbar-compact"><div class="dl-table-tools">
        <input class="dl-search" id="resultSearchInput" type="search" placeholder="筛选工号、姓名、地区、岗位" aria-label="筛选夜班补贴结果">
        <select class="dl-select" id="reviewStatusFilter" aria-label="筛选处理状态"><option value="all">全部处理状态</option><option value="review">只看需处理</option><option value="pass">只看无需处理</option></select>
        <select class="dl-select" id="amountFilter" aria-label="筛选金额"><option value="all">全部金额</option><option value="positive">应发大于0</option><option value="zero">应发为0</option></select>
        <span class="dl-result-count" id="resultCountText">—</span>
      </div></div>
      <div id="resultsTable" class="dl-table-wrap"></div><div class="dl-pagination" id="canbuPagination"></div>
    </section>
  `;
  el.resultsTable = document.querySelector('#resultsTable');
  el.resultSearchInput = document.querySelector('#resultSearchInput');
  el.reviewStatusFilter = document.querySelector('#reviewStatusFilter');
  el.amountFilter = document.querySelector('#amountFilter');
  el.resultCountText = document.querySelector('#resultCountText');
  el.canbuPagination = document.querySelector('#canbuPagination');
  if (el.resultSearchInput) el.resultSearchInput.value = state.resultSearch || '';
  if (el.reviewStatusFilter) el.reviewStatusFilter.value = ['all', 'review', 'pass'].includes(state.reviewStatusFilter) ? state.reviewStatusFilter : 'all';
  if (el.amountFilter) el.amountFilter.value = ['all', 'positive', 'zero'].includes(state.amountFilter) ? state.amountFilter : 'all';
  const rerender = () => { state.canbuPage = 1; renderNightShiftResultsTable(rows); };
  el.resultSearchInput?.addEventListener('input', () => { state.resultSearch = el.resultSearchInput.value.trim(); rerender(); });
  el.reviewStatusFilter?.addEventListener('change', () => { state.reviewStatusFilter = el.reviewStatusFilter.value; rerender(); });
  el.amountFilter?.addEventListener('change', () => { state.amountFilter = el.amountFilter.value; rerender(); });
  renderNightShiftResultsTable(rows);
  renderExceptionQueue(rows);
}

function renderNightShiftResultsTable(results) {
  if (!el.resultsTable) return;
  const filtered = filterNightShiftResults(results);
  updateResultCount(results.length, filtered.length);
  const pages = Math.max(1, Math.ceil(filtered.length / state.canbuPageSize));
  state.canbuPage = Math.min(Math.max(state.canbuPage, 1), pages);
  const start = (state.canbuPage - 1) * state.canbuPageSize;
  const pageRows = filtered.slice(start, start + state.canbuPageSize);
  if (!filtered.length) {
    el.resultsTable.innerHTML = '<div class="dl-empty compact"><p>暂无夜班补贴核算结果。</p></div>';
    if (el.canbuPagination) el.canbuPagination.innerHTML = '';
    return;
  }
  el.resultsTable.innerHTML = `
    <table class="dl-table dl-result-table"><thead><tr>
      <th class="sticky-col id-col">工号</th><th class="sticky-col name-col">姓名</th><th>工作地区</th><th>部门</th><th>岗位</th>
      <th class="dl-num">正常核算日</th><th class="dl-num">暂算需确认日</th><th class="dl-num">无需补贴日</th><th class="dl-num">异常未计金额日</th><th class="dl-num">应发夜班补贴</th><th>核算结果</th><th>需处理事项</th><th>解释</th>
    </tr></thead><tbody>${pageRows.map(row => {
      const inputs = getSubjectDetail(row, 'yeban_butie')?.audit_explanation?.inputs || {};
      const counts = getNightShiftDailyCounts(row);
      const resultStatus = getNightShiftResultStatus(row);
      const index = results.indexOf(row);
      return `<tr>
        <td class="sticky-col id-col dl-strong">${escapeHtml(row.employee_id)}</td><td class="sticky-col name-col">${escapeHtml(row.employee_name)}</td>
        <td>${escapeHtml(displayValue(inputs['工作地区'], '—'))}</td><td class="wrap-cell">${escapeHtml(displayValue(row.department, '—'))}</td><td class="wrap-cell">${escapeHtml(displayValue(inputs['岗位名称'], '—'))}</td>
        <td class="dl-num">${counts.calculated}</td><td class="dl-num">${counts.reviewCalculated}</td><td class="dl-num">${counts.excluded}</td><td class="dl-num">${counts.unpricedReview}</td>
        <td class="dl-num dl-strong">${formatMoney(row.yeban_butie)}</td><td><span class="dl-badge ${resultStatus.className}">${resultStatus.label}</span></td><td class="wrap-cell">${escapeHtml(resultStatus.action)}</td><td><button class="dl-segment compact" data-yeban-explain-index="${index}" type="button">计算过程</button></td>
      </tr>`;
    }).join('')}</tbody></table>
  `;
  el.resultsTable.querySelectorAll('[data-yeban-explain-index]').forEach(button => button.addEventListener('click', () => openExplainDrawer(results[Number(button.dataset.yebanExplainIndex)])));
  if (el.canbuPagination) {
    el.canbuPagination.innerHTML = `<span>${start + 1}-${Math.min(start + pageRows.length, filtered.length)} / ${filtered.length}</span><div class="dl-pagination-actions"><button class="dl-segment compact" data-yeban-page="prev" type="button" ${state.canbuPage <= 1 ? 'disabled' : ''}>上一页</button><strong>${state.canbuPage} / ${pages}</strong><button class="dl-segment compact" data-yeban-page="next" type="button" ${state.canbuPage >= pages ? 'disabled' : ''}>下一页</button></div>`;
    el.canbuPagination.querySelectorAll('[data-yeban-page]').forEach(button => button.addEventListener('click', () => { state.canbuPage += button.dataset.yebanPage === 'prev' ? -1 : 1; renderNightShiftResultsTable(results); }));
  }
}

function renderGonglingResults(results = []) {
  const root = document.querySelector('#canbuStepContent');
  if (!root) return;
  const rows = Array.isArray(results) ? results : [];
  const total = sumField(rows, 'gonglingjiang');
  const positiveCount = rows.filter(row => Number(row.gonglingjiang || 0) > 0).length;
  const cappedCount = rows.filter(row => {
    const details = getSubjectDetail(row, 'gonglingjiang')?.details || {};
    return Number(details['应发'] || 0) > 0 && Number(details['应发']) >= Number(details['上限'] || Infinity);
  }).length;
  const warnings = countSubjectWarnings(rows, 'gonglingjiang');
  const batch = getActiveCanbuBatch();
  const savedCollectionRoster = normalizeCollectionRoster(
    state.currentRun?.collectionSeniorityRoster || batch?.collectionSeniorityRoster || []
  );
  const requiresCollectionRoster = Boolean(state.currentRun?.inputSummary?.requires_collection_seniority_roster);
  const hasSavedRunRoster = Array.isArray(state.currentRun?.collectionSeniorityRoster);
  root.innerHTML = `
    <section class="dl-panel">
      <div class="dl-panel-head"><div><h2 class="dl-panel-title">工龄奖核算</h2><p class="dl-panel-sub">按工作地区、部门岗位、入职日期及线下缺勤口径复核应发工龄奖。</p></div></div>
      <div class="dl-result-summary">
        <div class="dl-result-stat primary"><span>应发合计</span><strong>${formatMoney(total)}</strong></div>
        <div class="dl-result-stat"><span>员工数</span><strong>${rows.length}</strong></div>
        <div class="dl-result-stat"><span>享有人数</span><strong>${positiveCount}</strong></div>
        <div class="dl-result-stat"><span>达到上限</span><strong>${cappedCount}</strong></div>
        <div class="dl-result-stat warning"><span>需处理</span><strong>${warnings}</strong></div>
      </div>
      ${requiresCollectionRoster ? `<details class="dl-parameter-panel">
        <summary><span>本批次揽收线工龄奖名单</span><strong>${savedCollectionRoster.length} 人</strong><span class="dl-badge ${hasSavedRunRoster ? 'ok' : 'warn'}">${hasSavedRunRoster ? '已随任务保存' : '旧批次待复核'}</span></summary>
        <div class="dl-parameter-panel-body">
          <div class="dl-parameter-list">${savedCollectionRoster.length ? savedCollectionRoster.map(item => `<span class="dl-badge">${escapeHtml(item.employeeId)} · ${escapeHtml(item.employeeName || '姓名待补')}</span>`).join('') : '<span class="inline-status">本批次名单为空。</span>'}</div>
          <button class="dl-btn" id="btnEditGonglingHrbpList" type="button">修改名单并重新核算</button>
        </div>
      </details>` : ''}
      <div class="dl-toolbar dl-toolbar-compact"><div class="dl-table-tools">
        <input class="dl-search" id="resultSearchInput" type="search" placeholder="筛选工号、姓名、部门、岗位" aria-label="筛选工龄奖结果">
        <select class="dl-select" id="reviewStatusFilter" aria-label="筛选异常状态"><option value="all">全部状态</option><option value="review">只看异常</option><option value="pass">只看通过</option></select>
        <select class="dl-select" id="amountFilter" aria-label="筛选金额状态"><option value="all">全部金额</option><option value="positive">应发大于0</option><option value="zero">应发为0</option></select>
        <span class="dl-result-count" id="resultCountText">—</span>
      </div></div>
      <div id="resultsTable" class="dl-table-wrap"></div><div class="dl-pagination" id="canbuPagination"></div>
    </section>
  `;
  el.resultsTable = document.querySelector('#resultsTable');
  el.resultSearchInput = document.querySelector('#resultSearchInput');
  el.reviewStatusFilter = document.querySelector('#reviewStatusFilter');
  el.amountFilter = document.querySelector('#amountFilter');
  el.resultCountText = document.querySelector('#resultCountText');
  el.canbuPagination = document.querySelector('#canbuPagination');
  if (el.resultSearchInput) el.resultSearchInput.value = state.resultSearch || '';
  if (el.reviewStatusFilter) el.reviewStatusFilter.value = ['all', 'review', 'pass'].includes(state.reviewStatusFilter) ? state.reviewStatusFilter : 'all';
  if (el.amountFilter) el.amountFilter.value = ['all', 'positive', 'zero'].includes(state.amountFilter) ? state.amountFilter : 'all';
  bindGonglingResultFilters();
  document.querySelector('#btnEditGonglingHrbpList')?.addEventListener('click', restartActiveBatchForRecalculation);
  renderGonglingResultsTable(rows);
  renderExceptionQueue(rows);
}

function renderGangweiResults(results = []) {
  const root = document.querySelector('#canbuStepContent');
  if (!root) return;
  const rows = Array.isArray(results) ? results : [];
  const total = sumField(rows, 'gangwei_butie');
  const positiveCount = rows.filter(row => Number(row.gangwei_butie || 0) > 0).length;
  const deductionCount = rows.filter(row => Number(getSubjectDetail(row, 'gangwei_butie')?.details?.['扣减天数'] || 0) > 0).length;
  const warnings = countSubjectWarnings(rows, 'gangwei_butie');
  root.innerHTML = `
    <section class="dl-panel">
      <div class="dl-panel-head"><div><h2 class="dl-panel-title">岗位补贴核算 <span class="dl-badge warn">验证中</span></h2><p class="dl-panel-sub">按岗位标准和排班天数核算；九类缺勤达到56小时后按全部小时折算，女神假1天按8小时。</p></div></div>
      <div class="dl-result-summary">
        <div class="dl-result-stat primary"><span>应发合计</span><strong>${formatMoney(total)}</strong></div>
        <div class="dl-result-stat"><span>员工数</span><strong>${rows.length}</strong></div>
        <div class="dl-result-stat"><span>享有人数</span><strong>${positiveCount}</strong></div>
        <div class="dl-result-stat"><span>触发缺勤扣减</span><strong>${deductionCount}</strong></div>
        <div class="dl-result-stat warning"><span>需确认</span><strong>${warnings}</strong></div>
      </div>
      <div class="dl-toolbar dl-toolbar-compact"><div class="dl-table-tools">
        <input class="dl-search" id="resultSearchInput" type="search" placeholder="筛选工号、姓名、地区、岗位" aria-label="筛选岗位补贴结果">
        <select class="dl-select" id="reviewStatusFilter" aria-label="筛选确认状态"><option value="all">全部状态</option><option value="review">只看需确认</option><option value="pass">只看已核算</option></select>
        <select class="dl-select" id="amountFilter" aria-label="筛选金额状态"><option value="all">全部金额</option><option value="positive">应发大于0</option><option value="zero">应发为0</option></select>
        <span class="dl-result-count" id="resultCountText">—</span>
      </div></div>
      <div id="resultsTable" class="dl-table-wrap"></div><div class="dl-pagination" id="canbuPagination"></div>
    </section>
  `;
  el.resultsTable = document.querySelector('#resultsTable');
  el.resultSearchInput = document.querySelector('#resultSearchInput');
  el.reviewStatusFilter = document.querySelector('#reviewStatusFilter');
  el.amountFilter = document.querySelector('#amountFilter');
  el.resultCountText = document.querySelector('#resultCountText');
  el.canbuPagination = document.querySelector('#canbuPagination');
  if (el.resultSearchInput) el.resultSearchInput.value = state.resultSearch || '';
  if (el.reviewStatusFilter) el.reviewStatusFilter.value = ['all', 'review', 'pass'].includes(state.reviewStatusFilter) ? state.reviewStatusFilter : 'all';
  if (el.amountFilter) el.amountFilter.value = ['all', 'positive', 'zero'].includes(state.amountFilter) ? state.amountFilter : 'all';
  const rerender = () => { state.canbuPage = 1; renderGangweiResultsTable(rows); };
  el.resultSearchInput?.addEventListener('input', () => { state.resultSearch = el.resultSearchInput.value.trim(); rerender(); });
  el.reviewStatusFilter?.addEventListener('change', () => { state.reviewStatusFilter = el.reviewStatusFilter.value; rerender(); });
  el.amountFilter?.addEventListener('change', () => { state.amountFilter = el.amountFilter.value; rerender(); });
  renderGangweiResultsTable(rows);
  renderExceptionQueue(rows);
}

function renderGangweiResultsTable(results) {
  if (!el.resultsTable) return;
  const keyword = state.resultSearch.trim().toLowerCase();
  const filtered = results.filter(row => {
    const detail = getSubjectDetail(row, 'gangwei_butie')?.details || {};
    const issue = hasSubjectReviewIssue(row, 'gangwei_butie');
    if (state.reviewStatusFilter === 'review' && !issue) return false;
    if (state.reviewStatusFilter === 'pass' && issue) return false;
    const amount = Number(row.gangwei_butie || 0);
    if (state.amountFilter === 'positive' && amount <= 0) return false;
    if (state.amountFilter === 'zero' && amount !== 0) return false;
    if (!keyword) return true;
    const inputs = detail.audit_explanation?.inputs || {};
    return [row.employee_id, row.employee_name, row.department, inputs['工作地区'], inputs['岗位名称'], detail['资格判断'], getEffectiveWarningText(row)]
      .map(value => String(value || '').toLowerCase()).join(' ').includes(keyword);
  });
  updateResultCount(results.length, filtered.length);
  const pages = Math.max(1, Math.ceil(filtered.length / state.canbuPageSize));
  state.canbuPage = Math.min(Math.max(state.canbuPage, 1), pages);
  const start = (state.canbuPage - 1) * state.canbuPageSize;
  const pageRows = filtered.slice(start, start + state.canbuPageSize);
  if (!filtered.length) {
    el.resultsTable.innerHTML = '<div class="dl-empty compact"><p>暂无岗位补贴核算结果。</p></div>';
    if (el.canbuPagination) el.canbuPagination.innerHTML = '';
    return;
  }
  el.resultsTable.innerHTML = `
    <table class="dl-table dl-result-table"><thead><tr>
      <th class="sticky-col id-col">工号</th><th class="sticky-col name-col">姓名</th><th>工作地区</th><th>岗位</th><th>资格</th>
      <th class="dl-num">标准</th><th class="dl-num">排班天数</th><th class="dl-num">缺勤时数</th><th class="dl-num">扣减天数</th><th class="dl-num">计发天数</th><th class="dl-num">应发岗位补贴</th><th>状态</th><th>解释</th>
    </tr></thead><tbody>${pageRows.map(row => {
      const detail = getSubjectDetail(row, 'gangwei_butie')?.details || {};
      const inputs = detail.audit_explanation?.inputs || {};
      const issue = hasSubjectReviewIssue(row, 'gangwei_butie');
      const index = results.indexOf(row);
      return `<tr>
        <td class="sticky-col id-col dl-strong">${escapeHtml(row.employee_id)}</td><td class="sticky-col name-col">${escapeHtml(row.employee_name)}</td>
        <td>${escapeHtml(displayValue(inputs['工作地区'], '—'))}</td><td class="wrap-cell">${escapeHtml(displayValue(inputs['岗位名称'], '—'))}</td><td>${escapeHtml(displayValue(detail['资格判断'], '—'))}</td>
        <td class="dl-num">${formatMoney(detail['岗位补贴标准'] || 0)}</td><td class="dl-num">${escapeHtml(displayValue(detail['排班天数'], 0))}</td><td class="dl-num">${escapeHtml(displayValue(detail['缺勤合计时数'], 0))}</td><td class="dl-num">${escapeHtml(displayValue(detail['扣减天数'], 0))}</td><td class="dl-num">${escapeHtml(displayValue(detail['岗位补贴计发天数'], 0))}</td>
        <td class="dl-num dl-strong">${formatMoney(row.gangwei_butie)}</td><td><span class="dl-badge ${issue ? 'warn' : 'ok'}">${issue ? '需确认' : '核算完成'}</span></td><td><button class="dl-segment compact" data-gangwei-explain-index="${index}" type="button">计算过程</button></td>
      </tr>`;
    }).join('')}</tbody></table>
  `;
  el.resultsTable.querySelectorAll('[data-gangwei-explain-index]').forEach(button => button.addEventListener('click', () => openExplainDrawer(results[Number(button.dataset.gangweiExplainIndex)])));
  if (el.canbuPagination) {
    el.canbuPagination.innerHTML = `<span>${start + 1}-${Math.min(start + pageRows.length, filtered.length)} / ${filtered.length}</span><div class="dl-pagination-actions"><button class="dl-segment compact" data-gangwei-page="prev" type="button" ${state.canbuPage <= 1 ? 'disabled' : ''}>上一页</button><strong>${state.canbuPage} / ${pages}</strong><button class="dl-segment compact" data-gangwei-page="next" type="button" ${state.canbuPage >= pages ? 'disabled' : ''}>下一页</button></div>`;
    el.canbuPagination.querySelectorAll('[data-gangwei-page]').forEach(button => button.addEventListener('click', () => { state.canbuPage += button.dataset.gangweiPage === 'prev' ? -1 : 1; renderGangweiResultsTable(results); }));
  }
}

function renderGaowenResults(results = []) {
  const root = document.querySelector('#canbuStepContent');
  if (!root) return;
  const rows = Array.isArray(results) ? results : [];
  const total = sumField(rows, 'gaowen_butie');
  const paidCount = rows.filter(row => Number(row.gaowen_butie || 0) > 0).length;
  const hotDays = rows.reduce((sum, row) => sum + Number(getSubjectDetail(row, 'gaowen_butie')?.details?.['高温出勤天数'] || 0), 0);
  const warnings = countSubjectWarnings(rows, 'gaowen_butie');
  root.innerHTML = `
    <section class="dl-panel">
      <div class="dl-panel-head"><div><h2 class="dl-panel-title">高温补贴核算 <span class="dl-badge warn">验证中</span></h2><p class="dl-panel-sub">同测温网点、同出勤日期、同白/夜班最高温达到33℃后，按实际高温出勤时长逐日折算。</p></div></div>
      <div class="dl-result-summary">
        <div class="dl-result-stat primary"><span>应发合计</span><strong>${formatMoney(total)}</strong></div>
        <div class="dl-result-stat"><span>员工数</span><strong>${rows.length}</strong></div>
        <div class="dl-result-stat"><span>计发人数</span><strong>${paidCount}</strong></div>
        <div class="dl-result-stat"><span>高温出勤日</span><strong>${hotDays}</strong></div>
        <div class="dl-result-stat warning"><span>需确认</span><strong>${warnings}</strong></div>
      </div>
      <div class="dl-toolbar dl-toolbar-compact"><div class="dl-table-tools">
        <input class="dl-search" id="resultSearchInput" type="search" placeholder="筛选工号、姓名、地区、岗位、测温网点" aria-label="筛选高温补贴结果">
        <select class="dl-select" id="reviewStatusFilter" aria-label="筛选确认状态"><option value="all">全部状态</option><option value="review">只看需确认</option><option value="pass">只看已核算</option></select>
        <select class="dl-select" id="amountFilter" aria-label="筛选金额状态"><option value="all">全部金额</option><option value="positive">应发大于0</option><option value="zero">应发为0</option></select>
        <span class="dl-result-count" id="resultCountText">—</span>
      </div></div>
      <div id="resultsTable" class="dl-table-wrap"></div><div class="dl-pagination" id="canbuPagination"></div>
    </section>
  `;
  el.resultsTable = document.querySelector('#resultsTable');
  el.resultSearchInput = document.querySelector('#resultSearchInput');
  el.reviewStatusFilter = document.querySelector('#reviewStatusFilter');
  el.amountFilter = document.querySelector('#amountFilter');
  el.resultCountText = document.querySelector('#resultCountText');
  el.canbuPagination = document.querySelector('#canbuPagination');
  if (el.resultSearchInput) el.resultSearchInput.value = state.resultSearch || '';
  if (el.reviewStatusFilter) el.reviewStatusFilter.value = ['all', 'review', 'pass'].includes(state.reviewStatusFilter) ? state.reviewStatusFilter : 'all';
  if (el.amountFilter) el.amountFilter.value = ['all', 'positive', 'zero'].includes(state.amountFilter) ? state.amountFilter : 'all';
  const rerender = () => { state.canbuPage = 1; renderGaowenResultsTable(rows); };
  el.resultSearchInput?.addEventListener('input', () => { state.resultSearch = el.resultSearchInput.value.trim(); rerender(); });
  el.reviewStatusFilter?.addEventListener('change', () => { state.reviewStatusFilter = el.reviewStatusFilter.value; rerender(); });
  el.amountFilter?.addEventListener('change', () => { state.amountFilter = el.amountFilter.value; rerender(); });
  renderGaowenResultsTable(rows);
  renderExceptionQueue(rows);
}

function renderGaowenResultsTable(results) {
  if (!el.resultsTable) return;
  const keyword = state.resultSearch.trim().toLowerCase();
  const filtered = results.filter(row => {
    const detail = getSubjectDetail(row, 'gaowen_butie')?.details || {};
    const issue = hasSubjectReviewIssue(row, 'gaowen_butie');
    if (state.reviewStatusFilter === 'review' && !issue) return false;
    if (state.reviewStatusFilter === 'pass' && issue) return false;
    const amount = Number(row.gaowen_butie || 0);
    if (state.amountFilter === 'positive' && amount <= 0) return false;
    if (state.amountFilter === 'zero' && amount !== 0) return false;
    if (!keyword) return true;
    const inputs = detail.audit_explanation?.inputs || {};
    return [row.employee_id, row.employee_name, row.department, inputs['工作地区'], inputs['岗位名称'], detail['测温网点'], detail['资格判断'], getEffectiveWarningText(row)]
      .map(value => String(value || '').toLowerCase()).join(' ').includes(keyword);
  });
  updateResultCount(results.length, filtered.length);
  const pages = Math.max(1, Math.ceil(filtered.length / state.canbuPageSize));
  state.canbuPage = Math.min(Math.max(state.canbuPage, 1), pages);
  const start = (state.canbuPage - 1) * state.canbuPageSize;
  const pageRows = filtered.slice(start, start + state.canbuPageSize);
  if (!filtered.length) {
    el.resultsTable.innerHTML = '<div class="dl-empty compact"><p>暂无高温补贴核算结果。</p></div>';
    if (el.canbuPagination) el.canbuPagination.innerHTML = '';
    return;
  }
  el.resultsTable.innerHTML = `
    <table class="dl-table dl-result-table"><thead><tr>
      <th class="sticky-col id-col">工号</th><th class="sticky-col name-col">姓名</th><th>工作地区</th><th>岗位</th><th>测温网点</th>
      <th class="dl-num">小时单价</th><th class="dl-num">单日上限</th><th class="dl-num">高温出勤日</th><th class="dl-num">月度上限</th><th class="dl-num">应发高温补贴</th><th>状态</th><th>解释</th>
    </tr></thead><tbody>${pageRows.map(row => {
      const detail = getSubjectDetail(row, 'gaowen_butie')?.details || {};
      const inputs = detail.audit_explanation?.inputs || {};
      const issue = hasSubjectReviewIssue(row, 'gaowen_butie');
      const index = results.indexOf(row);
      return `<tr>
        <td class="sticky-col id-col dl-strong">${escapeHtml(row.employee_id)}</td><td class="sticky-col name-col">${escapeHtml(row.employee_name)}</td>
        <td>${escapeHtml(displayValue(inputs['工作地区'], '—'))}</td><td class="wrap-cell">${escapeHtml(displayValue(inputs['岗位名称'], '—'))}</td><td class="wrap-cell">${escapeHtml(displayValue(detail['测温网点'], '待识别'))}</td>
        <td class="dl-num">${formatMoney(detail['小时单价'] || 0)}</td><td class="dl-num">${formatMoney(detail['单日封顶'] || 0)}</td><td class="dl-num">${escapeHtml(displayValue(detail['高温出勤天数'], 0))}</td><td class="dl-num">${formatMoney(detail['月度封顶'] || 0)}</td>
        <td class="dl-num dl-strong">${formatMoney(row.gaowen_butie)}</td><td><span class="dl-badge ${issue ? 'warn' : 'ok'}">${issue ? '需确认' : '核算完成'}</span></td><td><button class="dl-segment compact" data-gaowen-explain-index="${index}" type="button">计算过程</button></td>
      </tr>`;
    }).join('')}</tbody></table>
  `;
  el.resultsTable.querySelectorAll('[data-gaowen-explain-index]').forEach(button => button.addEventListener('click', () => openExplainDrawer(results[Number(button.dataset.gaowenExplainIndex)])));
  if (el.canbuPagination) {
    el.canbuPagination.innerHTML = `<span>${start + 1}-${Math.min(start + pageRows.length, filtered.length)} / ${filtered.length}</span><div class="dl-pagination-actions"><button class="dl-segment compact" data-gaowen-page="prev" type="button" ${state.canbuPage <= 1 ? 'disabled' : ''}>上一页</button><strong>${state.canbuPage} / ${pages}</strong><button class="dl-segment compact" data-gaowen-page="next" type="button" ${state.canbuPage >= pages ? 'disabled' : ''}>下一页</button></div>`;
    el.canbuPagination.querySelectorAll('[data-gaowen-page]').forEach(button => button.addEventListener('click', () => { state.canbuPage += button.dataset.gaowenPage === 'prev' ? -1 : 1; renderGaowenResultsTable(results); }));
  }
}

function hasGonglingReviewIssue(row) {
  const exceptions = (getSubjectDetail(row, 'gonglingjiang')?.exceptions || [])
    .filter(item => !isNormalHrbpListExclusionException(item));
  return exceptions.length > 0 || Boolean(getEffectiveWarningText(row));
}

function filterGonglingResults(results) {
  const keyword = state.resultSearch.trim().toLowerCase();
  return results.filter(row => {
    if (state.reviewStatusFilter === 'review' && !hasGonglingReviewIssue(row)) return false;
    if (state.reviewStatusFilter === 'pass' && hasGonglingReviewIssue(row)) return false;
    const amount = Number(row.gonglingjiang || 0);
    if (state.amountFilter === 'positive' && amount <= 0) return false;
    if (state.amountFilter === 'zero' && amount !== 0) return false;
    if (!keyword) return true;
    const details = getSubjectDetail(row, 'gonglingjiang')?.details || {};
    const inputs = details.audit_explanation?.inputs || {};
    return [row.employee_id, row.employee_name, row.department, details['岗位'], inputs['工作地区'], getEffectiveWarningText(row)]
      .map(value => String(value || '').toLowerCase()).join(' ').includes(keyword);
  });
}

function renderGonglingResultsTable(results) {
  if (!el.resultsTable) return;
  const filtered = filterGonglingResults(results);
  updateResultCount(results.length, filtered.length);
  const totalPages = Math.max(1, Math.ceil(filtered.length / state.canbuPageSize));
  state.canbuPage = Math.min(Math.max(state.canbuPage, 1), totalPages);
  const start = (state.canbuPage - 1) * state.canbuPageSize;
  const pageRows = filtered.slice(start, start + state.canbuPageSize);
  if (!filtered.length) {
    el.resultsTable.innerHTML = '<div class="dl-empty compact"><p>暂无工龄奖核算结果。</p></div>';
    renderGonglingPagination(0, 0, 0);
    return;
  }
  el.resultsTable.innerHTML = `
    <table class="dl-table dl-result-table"><thead><tr>
      <th class="sticky-col id-col">工号</th><th class="sticky-col name-col">姓名</th><th>工作地区</th><th>部门</th><th>岗位</th>
      <th class="dl-num">工龄(年)</th><th class="dl-num">标准</th><th class="dl-num">上限</th><th class="dl-num">缺勤时数</th><th class="dl-num">应发工龄奖</th><th>状态</th><th>解释</th>
    </tr></thead><tbody>${pageRows.map(row => {
      const details = getSubjectDetail(row, 'gonglingjiang')?.details || {};
      const inputs = details.audit_explanation?.inputs || {};
      const issue = hasGonglingReviewIssue(row);
      const index = results.indexOf(row);
      return `<tr>
        <td class="sticky-col id-col dl-strong">${escapeHtml(row.employee_id)}</td><td class="sticky-col name-col">${escapeHtml(row.employee_name)}</td>
        <td>${escapeHtml(displayValue(inputs['工作地区'], '—'))}</td><td class="wrap-cell">${escapeHtml(displayValue(row.department, '—'))}</td><td class="wrap-cell">${escapeHtml(displayValue(details['岗位'], inputs['岗位名称'], '—'))}</td>
        <td class="dl-num">${escapeHtml(displayValue(details['工龄(年)'], 0))}</td><td class="dl-num">${formatMoney(details['标准'] || 0)}</td><td class="dl-num">${formatMoney(details['上限'] || 0)}</td><td class="dl-num">${escapeHtml(displayValue(details['事病旷排休时数'], 0))}</td>
        <td class="dl-num dl-strong">${formatMoney(row.gonglingjiang)}</td><td><span class="dl-badge ${issue ? 'warn' : 'ok'}">${issue ? '需关注' : '通过'}</span></td><td><button class="dl-segment compact" data-gongling-explain-index="${index}" type="button">计算过程</button></td>
      </tr>`;
    }).join('')}</tbody></table>
  `;
  el.resultsTable.querySelectorAll('[data-gongling-explain-index]').forEach(button => button.addEventListener('click', () => openExplainDrawer(results[Number(button.dataset.gonglingExplainIndex)])));
  renderGonglingPagination(filtered.length, start + 1, Math.min(start + pageRows.length, filtered.length));
}

function bindGonglingResultFilters() {
  const rerender = () => { state.canbuPage = 1; renderGonglingResultsTable(state.currentResults); };
  el.resultSearchInput?.addEventListener('input', () => { state.resultSearch = el.resultSearchInput.value.trim(); rerender(); });
  el.reviewStatusFilter?.addEventListener('change', () => { state.reviewStatusFilter = el.reviewStatusFilter.value; rerender(); });
  el.amountFilter?.addEventListener('change', () => { state.amountFilter = el.amountFilter.value; rerender(); });
}

function renderGonglingPagination(total, start, end) {
  if (!el.canbuPagination) return;
  if (!total) { el.canbuPagination.innerHTML = ''; return; }
  const pages = Math.max(1, Math.ceil(total / state.canbuPageSize));
  el.canbuPagination.innerHTML = `<span>${start}-${end} / ${total}</span><div class="dl-pagination-actions"><button class="dl-segment compact" data-gongling-page="prev" type="button" ${state.canbuPage <= 1 ? 'disabled' : ''}>上一页</button><strong>${state.canbuPage} / ${pages}</strong><button class="dl-segment compact" data-gongling-page="next" type="button" ${state.canbuPage >= pages ? 'disabled' : ''}>下一页</button></div>`;
  el.canbuPagination.querySelectorAll('[data-gongling-page]').forEach(button => button.addEventListener('click', () => { state.canbuPage += button.dataset.gonglingPage === 'prev' ? -1 : 1; renderGonglingResultsTable(state.currentResults); }));
}

function renderWaisuResults(results = []) {
  const root = document.querySelector('#canbuStepContent');
  if (!root) return;
  const rows = Array.isArray(results) ? results : [];
  const total = sumField(rows, 'waisu_butie');
  const positiveCount = rows.filter(row => Number(row.waisu_butie || 0) > 0).length;
  const housedCount = rows.filter(row => Number(getWaisuDetails(row)['住宿扣除天数'] || 0) > 0).length;
  const warnings = rows.filter(hasWaisuReviewIssue).length;
  if (!getWaisuRegionTabs(rows).some(item => item.value === state.canbuRegionFilter)) state.canbuRegionFilter = 'all';
  root.innerHTML = `
    <section class="dl-panel">
      <div class="dl-panel-head"><div><h2 class="dl-panel-title">外宿补贴核算</h2><p class="dl-panel-sub">按地区岗位资格、实际入住退宿区间和缺勤口径复核应发外宿补贴。</p></div></div>
      <div class="dl-result-summary">
        <div class="dl-result-stat primary"><span>应发合计</span><strong>${formatMoney(total)}</strong></div>
        <div class="dl-result-stat"><span>员工数</span><strong>${rows.length}</strong></div>
        <div class="dl-result-stat"><span>享有人数</span><strong>${positiveCount}</strong></div>
        <div class="dl-result-stat"><span>有住宿扣除</span><strong>${housedCount}</strong></div>
        <div class="dl-result-stat warning"><span>需处理</span><strong>${warnings}</strong></div>
      </div>
      <div class="dl-result-tabs" id="canbuRegionTabs">${renderWaisuRegionTabs(rows)}</div>
      <div class="dl-toolbar dl-toolbar-compact"><div class="dl-table-tools">
        <input class="dl-search" id="resultSearchInput" type="search" placeholder="筛选工号、姓名、部门、岗位" aria-label="筛选外宿补贴结果">
        <select class="dl-select" id="reviewStatusFilter" aria-label="筛选异常状态"><option value="all">全部状态</option><option value="review">只看异常</option><option value="pass">只看通过</option></select>
        <select class="dl-select" id="amountFilter" aria-label="筛选金额状态"><option value="all">全部金额</option><option value="positive">应发大于0</option><option value="zero">应发为0</option></select>
        <span class="dl-result-count" id="resultCountText">—</span>
      </div></div>
      <div id="resultsTable" class="dl-table-wrap"></div><div class="dl-pagination" id="canbuPagination"></div>
    </section>
  `;
  el.resultsTable = document.querySelector('#resultsTable');
  el.resultSearchInput = document.querySelector('#resultSearchInput');
  el.reviewStatusFilter = document.querySelector('#reviewStatusFilter');
  el.amountFilter = document.querySelector('#amountFilter');
  el.resultCountText = document.querySelector('#resultCountText');
  el.canbuPagination = document.querySelector('#canbuPagination');
  if (el.resultSearchInput) el.resultSearchInput.value = state.resultSearch || '';
  if (el.reviewStatusFilter) el.reviewStatusFilter.value = ['all', 'review', 'pass'].includes(state.reviewStatusFilter) ? state.reviewStatusFilter : 'all';
  if (el.amountFilter) el.amountFilter.value = ['all', 'positive', 'zero'].includes(state.amountFilter) ? state.amountFilter : 'all';
  bindWaisuResultFilters();
  bindWaisuRegionTabs();
  renderWaisuResultsTable(rows);
  renderWaisuExceptionQueue(rows);
}

function getWaisuDetails(row) {
  return getSubjectDetail(row, 'waisu_butie')?.details || {};
}

function getWaisuAudit(row) {
  const payload = getSubjectDetail(row, 'waisu_butie') || {};
  return payload.audit_explanation || payload.details?.audit_explanation || {};
}

function getWaisuRowRegion(row) {
  const audit = getWaisuAudit(row);
  return displayValue(audit.inputs?.['工作地区'], row.work_region, row.region, '未识别');
}

function getWaisuReviewExceptions(row) {
  return (getSubjectDetail(row, 'waisu_butie')?.exceptions || []).filter(item => !isOfflineAnswerComparison(item));
}

function hasWaisuReviewIssue(row) {
  return getWaisuReviewExceptions(row).length > 0 || Boolean(getEffectiveWarningText(row));
}

function getWaisuWarningLevel(row) {
  const warnings = getWaisuReviewExceptions(row);
  if (warnings.some(item => item.level === 'blocking')) return { label: '阻断', className: 'block' };
  if (warnings.length || getEffectiveWarningText(row)) return { label: '需关注', className: 'warn' };
  return { label: '通过', className: 'ok' };
}

function getWaisuRegionTabs(results) {
  const tabs = [{ value: 'all', label: '全部', count: results.length }];
  const counts = new Map();
  results.forEach(row => counts.set(getWaisuRowRegion(row), (counts.get(getWaisuRowRegion(row)) || 0) + 1));
  Array.from(counts.entries()).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'zh-CN')).forEach(([region, count]) => tabs.push({ value: region, label: region, count }));
  const issueCount = results.filter(hasWaisuReviewIssue).length;
  if (issueCount) tabs.push({ value: '__issues__', label: '需处理', count: issueCount });
  return tabs;
}

function renderWaisuRegionTabs(results) {
  return getWaisuRegionTabs(results).map(item => `<button class="dl-result-tab ${state.canbuRegionFilter === item.value ? 'active' : ''}" data-waisu-region="${escapeHtml(item.value)}" type="button"><span>${escapeHtml(item.label)}</span><strong>${item.count}</strong></button>`).join('');
}

function filterWaisuResults(results) {
  const keyword = state.resultSearch.trim().toLowerCase();
  return results.filter(row => {
    if (state.canbuRegionFilter === '__issues__' && !hasWaisuReviewIssue(row)) return false;
    if (!['all', '__issues__'].includes(state.canbuRegionFilter) && getWaisuRowRegion(row) !== state.canbuRegionFilter) return false;
    if (state.reviewStatusFilter === 'review' && !hasWaisuReviewIssue(row)) return false;
    if (state.reviewStatusFilter === 'pass' && hasWaisuReviewIssue(row)) return false;
    const amount = Number(row.waisu_butie || 0);
    if (state.amountFilter === 'positive' && amount <= 0) return false;
    if (state.amountFilter === 'zero' && amount !== 0) return false;
    if (!keyword) return true;
    const audit = getWaisuAudit(row);
    return [row.employee_id, row.employee_name, row.department, row.position, audit.inputs?.['岗位名称'], getEffectiveWarningText(row)]
      .map(value => String(value || '').toLowerCase()).join(' ').includes(keyword);
  });
}

function renderWaisuResultsTable(results) {
  if (!el.resultsTable) return;
  const filtered = filterWaisuResults(results);
  updateResultCount(results.length, filtered.length);
  const totalPages = Math.max(1, Math.ceil(filtered.length / state.canbuPageSize));
  state.canbuPage = Math.min(Math.max(state.canbuPage, 1), totalPages);
  const start = (state.canbuPage - 1) * state.canbuPageSize;
  const pageRows = filtered.slice(start, start + state.canbuPageSize);
  if (!filtered.length) {
    el.resultsTable.innerHTML = '<div class="dl-empty compact"><p>暂无外宿补贴核算结果。</p></div>';
    renderWaisuPagination(0, 0, 0);
    return;
  }
  el.resultsTable.innerHTML = `
    <table class="dl-table dl-result-table"><thead><tr>
      <th class="sticky-col id-col">工号</th><th class="sticky-col name-col">姓名</th><th>工作地区</th><th>部门</th><th>岗位</th><th>资格/状态</th>
      <th class="dl-num">在职天数</th><th class="dl-num">住宿扣除</th><th class="dl-num">外宿天数</th><th class="dl-num">缺勤时数</th><th class="dl-num">应发外宿补贴</th><th>异常</th><th>解释</th>
    </tr></thead><tbody>${pageRows.map(row => {
      const detail = getWaisuDetails(row);
      const audit = getWaisuAudit(row);
      const inputs = audit.inputs || {};
      const level = getWaisuWarningLevel(row);
      const amount = Number(row.waisu_butie || 0);
      const reason = detail.reason || (amount > 0 ? '享有' : '不享有/未发放');
      const rowIndex = results.indexOf(row);
      return `<tr>
        <td class="sticky-col id-col dl-strong">${escapeHtml(displayValue(row.employee_id, inputs['工号']))}</td>
        <td class="sticky-col name-col">${escapeHtml(displayValue(row.employee_name, inputs['姓名']))}</td>
        <td>${escapeHtml(getWaisuRowRegion(row))}</td><td class="wrap-cell">${escapeHtml(displayValue(row.department, inputs['部门字段'], '—'))}</td><td class="wrap-cell">${escapeHtml(displayValue(row.position, inputs['岗位名称'], '—'))}</td>
        <td><span class="dl-badge ${amount > 0 ? 'ok' : 'warn'}">${escapeHtml(reason)}</span></td>
        <td class="dl-num">${escapeHtml(displayValue(detail['在职天数'], '—'))}</td><td class="dl-num">${escapeHtml(displayValue(detail['住宿扣除天数'], '—'))}</td><td class="dl-num">${escapeHtml(displayValue(detail['外宿补贴天数'], '—'))}</td><td class="dl-num">${escapeHtml(displayValue(detail['缺勤时数'], '—'))}</td>
        <td class="dl-num dl-strong">${formatMoney(amount)}</td><td><span class="dl-badge ${level.className}">${level.label}</span></td><td><button class="dl-segment compact" data-waisu-explain-index="${rowIndex}" type="button">计算过程</button></td>
      </tr>`;
    }).join('')}</tbody></table>
  `;
  el.resultsTable.querySelectorAll('[data-waisu-explain-index]').forEach(button => button.addEventListener('click', () => openWaisuExplainDrawer(results[Number(button.dataset.waisuExplainIndex)])));
  renderWaisuPagination(filtered.length, start + 1, Math.min(start + pageRows.length, filtered.length));
}

function bindWaisuResultFilters() {
  const rerender = () => { state.canbuPage = 1; renderWaisuResultsTable(state.currentResults); };
  el.resultSearchInput?.addEventListener('input', () => { state.resultSearch = el.resultSearchInput.value.trim(); rerender(); });
  el.reviewStatusFilter?.addEventListener('change', () => { state.reviewStatusFilter = el.reviewStatusFilter.value; rerender(); });
  el.amountFilter?.addEventListener('change', () => { state.amountFilter = el.amountFilter.value; rerender(); });
}

function bindWaisuRegionTabs() {
  document.querySelectorAll('[data-waisu-region]').forEach(button => button.addEventListener('click', () => {
    state.canbuRegionFilter = button.dataset.waisuRegion || 'all';
    state.canbuPage = 1;
    document.querySelectorAll('[data-waisu-region]').forEach(item => item.classList.toggle('active', item === button));
    renderWaisuResultsTable(state.currentResults);
  }));
}

function renderWaisuPagination(total, start, end) {
  if (!el.canbuPagination) return;
  if (!total) { el.canbuPagination.innerHTML = ''; return; }
  const pages = Math.max(1, Math.ceil(total / state.canbuPageSize));
  el.canbuPagination.innerHTML = `<span>${start}-${end} / ${total}</span><div class="dl-pagination-actions"><button class="dl-segment compact" data-waisu-page="prev" type="button" ${state.canbuPage <= 1 ? 'disabled' : ''}>上一页</button><strong>${state.canbuPage} / ${pages}</strong><button class="dl-segment compact" data-waisu-page="next" type="button" ${state.canbuPage >= pages ? 'disabled' : ''}>下一页</button></div>`;
  el.canbuPagination.querySelectorAll('[data-waisu-page]').forEach(button => button.addEventListener('click', () => { state.canbuPage += button.dataset.waisuPage === 'prev' ? -1 : 1; renderWaisuResultsTable(state.currentResults); }));
}

function renderWaisuExceptionQueue(results) {
  if (!el.exceptionQueue) return;
  const rows = results.filter(hasWaisuReviewIssue);
  if (!rows.length) {
    el.exceptionQueue.innerHTML = '<div class="dl-exception"><p class="dl-exception-title">暂无异常</p><p class="dl-exception-meta">完成计算后，外宿补贴可复核异常会进入这里。</p></div>';
    return;
  }
  el.exceptionQueue.innerHTML = rows.map(row => `<button class="dl-exception ${getWaisuWarningLevel(row).className}" data-waisu-exception-id="${escapeHtml(row.employee_id)}" type="button"><p class="dl-exception-title">${getWaisuWarningLevel(row).label} · ${escapeHtml(row.employee_id)} ${escapeHtml(row.employee_name)}</p><p class="dl-exception-meta">${escapeHtml(getWaisuReviewExceptions(row)[0]?.message || getEffectiveWarningText(row))}</p></button>`).join('');
  el.exceptionQueue.querySelectorAll('[data-waisu-exception-id]').forEach(button => button.addEventListener('click', () => openWaisuExplainDrawer(results.find(row => row.employee_id === button.dataset.waisuExceptionId))));
}

function openWaisuExplainDrawer(row) {
  if (!row || !el.calcModal || !el.calcModalTitle || !el.calcModalBody) return;
  const audit = getWaisuAudit(row);
  const detail = getWaisuDetails(row);
  const exceptions = getWaisuReviewExceptions(row);
  el.calcModalTitle.textContent = `${row.employee_id || ''} ${row.employee_name || ''} · 外宿补贴计算过程`;
  if (el.calcModalSub) el.calcModalSub.textContent = '展示资格判断、住宿日期、缺勤折算和最终应发金额。';
  el.calcModalBody.innerHTML = `
    <div class="dl-kv-grid"><div class="dl-kv"><span>工作地区</span><strong>${escapeHtml(getWaisuRowRegion(row))}</strong></div><div class="dl-kv"><span>岗位</span><strong>${escapeHtml(displayValue(row.position, audit.inputs?.['岗位名称'], '—'))}</strong></div><div class="dl-kv"><span>应发外宿补贴</span><strong>${formatMoney(row.waisu_butie)}</strong></div><div class="dl-kv"><span>外宿天数</span><strong>${escapeHtml(displayValue(detail['外宿补贴天数'], '—'))}</strong></div></div>
    <div class="dl-rule-card"><h3>规则命中</h3><dl><dt>规则状态</dt><dd>${escapeHtml(audit.rule_name || detail.reason || '外宿补贴规则')}</dd><dt>计算公式</dt><dd>${escapeHtml(audit.formula || '按地区岗位资格、在职区间、住宿区间和缺勤时数计算。')}</dd><dt>关键输入</dt><dd>${formatAuditMap(audit.inputs)}</dd><dt>中间值</dt><dd>${formatAuditMap(audit.intermediate_values)}</dd><dt>计算步骤</dt><dd>${formatAuditSteps(audit.steps) || '按外宿补贴规则计算应发金额。'}</dd></dl></div>
    <div class="dl-rule-card"><h3>异常与建议</h3><dl><dt>异常等级</dt><dd>${getWaisuWarningLevel(row).label}</dd><dt>异常说明</dt><dd>${formatExceptions(exceptions) || escapeHtml(getEffectiveWarningText(row) || '暂无异常')}</dd><dt>建议动作</dt><dd>${exceptions[0]?.suggested_action ? escapeHtml(exceptions[0].suggested_action) : '无需人工处理。'}</dd></dl></div>
  `;
  el.calcModal.classList.add('visible');
  document.body.style.overflow = 'hidden';
}

function hasCanbuReviewIssue(row) {
  return getCanbuReviewExceptions(row).length > 0;
}

function getCanbuReviewExceptions(row) {
  return (getSubjectDetail(row, 'canbu')?.exceptions || []).filter(item => !isOfflineAnswerComparison(item));
}

function getCanbuWarningLevel(row) {
  const warnings = getCanbuReviewExceptions(row);
  if (warnings.some(item => item.level === 'blocking')) return { label: '阻断', className: 'block' };
  if (warnings.some(item => item.level === 'high' || item.level === 'error' || item.level === 'warn')) return { label: '高风险', className: 'warn' };
  if (warnings.length) return { label: '提示', className: 'warn' };
  return { label: '通过', className: 'ok' };
}

function getCanbuWarningMessage(row) {
  const warnings = getCanbuReviewExceptions(row);
  const first = warnings[0];
  return (first?.message || '').trim();
}

function isOfflineAnswerComparison(item) {
  if (!item) return false;
  if (String(item.code || '').toLowerCase().includes('offline')) return true;
  return /离线.*对比|离线.*答案|offline/i.test(String(item.message || ''));
}

function bindCanbuWorkbenchEvents() {
  document.querySelector('#btnBackCanbuBatches')?.addEventListener('click', () => {
    showView('canbuBatches');
    renderCanbuBatchList();
  });
  document.querySelector('#btnRecalculateCanbu')?.addEventListener('click', restartActiveBatchForRecalculation);
  document.querySelector('#btnExportCanbu')?.addEventListener('click', () => exportResults(true));
  document.querySelector('#btnGoCanbuResults')?.addEventListener('click', () => renderCanbuWorkbench('results'));
  document.querySelectorAll('[data-canbu-step]').forEach((button) => {
    button.addEventListener('click', () => {
      if (button.disabled || button.getAttribute('aria-disabled') === 'true') return;
      const nextStep = button.dataset.canbuStep;
      renderCanbuWorkbench(nextStep === 'results' ? 'results' : nextStep);
    });
  });
  el.btnToggleAside?.addEventListener('click', toggleAside);
}

function restartActiveBatchForRecalculation() {
  const batch = getActiveCanbuBatch();
  if (batch) {
    updateActiveCanbuBatch({
      status: '草稿',
      employeeCount: 0,
      payableTotal: 0,
      exceptionCount: 0,
      exportFileName: '',
      exportedAt: '',
      runId: '',
    });
  }
  clearCurrentRunState({ clearFile: true });
  resetCanbuFilters();
  renderCanbuWorkbench('upload');
}

function getBatchStatusClass(status) {
  if (status === '已导出' || status === '可导出' || status === '已核算') return 'ok';
  if (status === '字段异常' || status === '失败') return 'block';
  return 'warn';
}

function isCanbuBatchCalculating(batch) {
  const status = batch?.status || state.currentRun?.status || '';
  const hasRun = Boolean(batch?.runId || state.currentRun?.id);
  return hasRun && ['上传中', '校验中', '已提交', '已上传', '等待上传', '计算中'].includes(status);
}

function formatMonthLabel(value) {
  const text = String(value || '');
  const match = text.match(/^(\d{4})-(\d{2})$/);
  return match ? `${match[1]}年${match[2]}月` : text;
}

function formatDateTime(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
}

function getCurrentMonthValue() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
}

function getBatchStatusFromRunStatus(runStatus) {
  if (!runStatus) return undefined;
  if (runStatus === '已完成') return '已核算';
  if (runStatus === '失败') return '失败';
  if (runStatus === '等待上传') return '上传中';
  if (runStatus === '已上传' || runStatus === '计算中') return '已提交';
  return runStatus;
}

function syncCanbuBatchFromRun(targetRun = state.currentRun, options = {}) {
  if (!targetRun?.id) return;
  const batch = getCanbuBatch({
    runId: targetRun.id,
    batchId: options.batchId,
  });
  if (!batch) return;

  const patch = {
    runId: targetRun.id || '',
    status: options.status || getBatchStatusFromRunStatus(targetRun.status),
  };

  if (Array.isArray(targetRun.collectionSeniorityRoster)) {
    patch.collectionSeniorityRoster = normalizeCollectionRoster(targetRun.collectionSeniorityRoster);
  }

  if (options.includeResults) {
    const results = state.currentResults || [];
    const summary = targetRun.summary || {};
    const config = getWorkbenchConfig(batch.subject);
    patch.employeeCount = results.length;
    patch.exceptionCount = countWorkbenchWarnings(results, batch.subject);
    patch.payableTotal = Number(summary[config.totalField] ?? sumField(results, config.resultField));
  }

  if (options.exportFileName) {
    patch.exportFileName = options.exportFileName;
  }
  if (options.exportedAt) {
    patch.exportedAt = options.exportedAt;
  }

  updateCanbuBatch(patch, { runId: targetRun.id, batchId: batch.id });
}

function updateSelectedEngines() {
  if (!el.engineCardGrid) return;
  state.selectedEngines = [];
  el.engineCardGrid.querySelectorAll('.engine-card.selected').forEach(card => {
    state.selectedEngines.push(card.dataset.engine);
  });
  updateStep1State();
}

function updateStep1State() {
  if (!el.btnToStep2 || !el.engineStatus || !el.attendanceMonth) return;
  const hasEngines = state.selectedEngines.length > 0;
  const hasMonth = el.attendanceMonth.value;
  el.btnToStep2.disabled = !(hasEngines && hasMonth);
  if (!hasEngines) {
    setText(el.engineStatus, '请至少选择一个计算引擎');
  } else if (!hasMonth) {
    setText(el.engineStatus, '请选择考勤月份');
  } else {
    setText(el.engineStatus, `已选择 ${state.selectedEngines.length} 个引擎`);
  }
}

function updateStep2State() {
  if (!el.btnToStep3 || !el.uploadStatus || !el.payrollFile) return;
  el.btnToStep3.disabled = !state.payrollFile;
  setText(el.uploadStatus, state.payrollFile ? `已选择: ${state.payrollFile.name}` : '请选择文件');
}

function goToStep(step) {
  document.querySelectorAll('.wz-step').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.wz-panel').forEach(p => p.classList.remove('active'));
  document.querySelector(`.wz-step[data-step="${step}"]`).classList.add('active');
  document.querySelector(`.wz-panel[data-panel="${step}"]`).classList.add('active');

  if (step === 4) {
    renderConfirmSummary();
  }
}

function renderConfirmSummary() {
  const engineNames = state.selectedEngines.map(k => ENGINE_META[k]?.name || k).join('、');
  el.confirmEngines.textContent = engineNames || '—';
  el.confirmMonth.textContent = el.attendanceMonth.value || '—';
  el.confirmFile.textContent = state.payrollFile?.name || '—';

}

async function submitTask() {
  if (!state.payrollFile) return toast('请先上传文件。');
  if (!state.selectedEngines.length) return toast('请至少选择一个引擎。');

  setText(el.submitStatus, '正在上传并完成核算，请稍候...');
  setButtonBusy(el.btnSubmitTask, true, '准备上传...');
  resetReportLink();

  try {
    const data = await submitDomesticLaborRun({
      file: state.payrollFile,
      engines: state.selectedEngines,
      attendanceMonth: el.attendanceMonth.value,
      password: el.filePassword.value || '',
      hrbpList: state.hrbpList,
      statusElement: el.submitStatus,
      progressButton: el.btnSubmitTask,
    });
    if (data.status === '失败') {
      throw new Error(data.error || '计算失败，请检查文件后重试。');
    }

    state.currentRun = { id: data.run_id, status: data.status };
    syncCanbuBatchFromRun(state.currentRun);
    setText(el.submitStatus, `核算完成: ${data.run_id}`);

    // Update run badge
    el.chromeRunBadge.hidden = false;
    el.chromeRunLabel.textContent = `任务 #${data.run_id.slice(-8)}`;

    document.querySelector('.btn-close-drawer').click();
    showTaskSection();
    if (data.status === '已完成') {
      await loadCompletedRun(data.run_id);
      toast('薪酬计算完成！');
    } else {
      startPolling();
      toast('计算任务已提交，正在处理...');
    }
  } catch (error) {
    setText(el.submitStatus, error.message, true);
    toast(error.message);
  } finally {
    setButtonBusy(el.btnSubmitTask, false);
  }
}

async function submitCanbuBatch() {
  const batch = getActiveCanbuBatch();
  const config = getWorkbenchConfig(batch?.subject);
  if (!state.payrollFiles.length && !state.payrollFile) return toast(`请先上传${config.name}数据文件。`);
  if (!batch) return toast(`暂无${config.name}批次。`);
  if (batch.subject === 'yeban_butie' && !isNightShiftConfigReady(batch)) {
    return toast('平台班次休息基线未加载，请刷新页面后重试。');
  }

  const submit = document.querySelector('#btnSubmitCanbuBatch');
  beginCanbuOperation(batch, '正在生成安全直传地址...');
  updateCanbuBatch({ status: '上传中' }, { batchId: batch.id });
  setButtonBusy(submit, true, '准备上传...');
  setText(el.uploadStatus, `正在上传并完成${config.name}核算，请稍候...`);
  resetReportLink();
  stopPolling();
  state.currentRun = null;
  state.currentResults = [];
  state.currentResultsRunId = '';

  try {
    const files = state.payrollFiles.length ? state.payrollFiles : [state.payrollFile];
    let hrbpList = null;
    if (batch.subject === 'gonglingjiang') {
      const collectionRoster = collectCollectionRosterTable();
      updateCanbuBatch({ collectionSeniorityRoster: collectionRoster }, { batchId: batch.id });
      hrbpList = collectionRoster.map(item => ({
        employee_id: item.employeeId,
        employee_name: item.employeeName,
      }));
    }

    const data = await submitDomesticLaborRun({
      file: files[0],
      files,
      engines: [batch.subject],
      attendanceMonth: String(batch.month || '').replace('-', ''),
      password: el.filePassword?.value || '',
      hrbpList,
      statusElement: el.uploadStatus,
      progressButton: submit,
      onPlanCreated: (plan) => {
        state.currentRun = { id: plan.runId, status: '等待上传' };
        updateCanbuBatch({ runId: plan.runId, status: '上传中' }, { batchId: batch.id });
        updateCanbuOperation('安全直传地址已生成，正在上传文件...', { runId: plan.runId });
      },
    });
    if (data.status === '失败') {
      throw new Error(data.error || `${config.name}核算失败，请检查文件后重试。`);
    }

    state.currentRun = {
      id: data.run_id,
      status: data.status,
      inputSummary: data.input_summary,
      collectionSeniorityRoster: data.collection_seniority_roster,
      collectionSeniorityRosterCount: data.collection_seniority_roster_count,
      nightShiftConfigSnapshot: data.night_shift_config_snapshot,
    };
    state.currentResultsRunId = '';
    syncCanbuBatchFromRun(state.currentRun, { batchId: batch.id, status: data.status });
    if (data.status === '已完成') {
      await loadCompletedRun(data.run_id);
      finishCanbuOperation(data.run_id);
      toast(`${config.name}核算完成。`);
    } else {
      updateCanbuOperation(`${config.name}数据已上传，后台正在核算...`, { runId: data.run_id, phase: 'calculating' });
      startPolling();
      renderCanbuWorkbench('fields');
      toast(`${config.name}批次已提交，正在处理。`);
    }
  } catch (error) {
    updateCanbuBatch({ status: '失败' }, { batchId: batch.id });
    finishCanbuOperation(state.activeCanbuOperation?.runId || '', error.message || `${config.name}核算失败。`);
    setText(el.uploadStatus, error.message, true);
    toast(error.message);
  } finally {
    setButtonBusy(submit, false);
  }
}

async function submitDomesticLaborRun({ file, files = [], engines, attendanceMonth, password, hrbpList, statusElement, progressButton, onPlanCreated }) {
  const selectedFiles = files.length ? files : [file].filter(Boolean);
  try {
    return await submitDomesticLaborRunDirect({
      files: selectedFiles,
      engines,
      attendanceMonth,
      password,
      hrbpList,
      statusElement,
      progressButton,
      onPlanCreated,
    });
  } catch (error) {
    const localHost = ['', 'localhost', '127.0.0.1', '::1'].includes(window.location.hostname);
    const directUnavailable = error.status === 409
      || /未启用 Supabase 直传|DIRECT_UPLOAD_UNAVAILABLE/i.test(error.message || '');
    if (!localHost || !directUnavailable) throw error;
    setText(statusElement, '本地未启用对象存储，改用本地上传并核算...');
    return submitDomesticLaborRunMultipart({ files: selectedFiles, engines, attendanceMonth, password, hrbpList });
  }
}

async function submitDomesticLaborRunDirect({ files, engines, attendanceMonth, password, hrbpList, statusElement, progressButton, onPlanCreated }) {
  updateUploadProgress(statusElement, progressButton, '正在生成安全直传地址...');
  const plan = await requestJson('/api/domestic-labor/runs/direct-upload-plan', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      files: files.map(file => ({
        fileName: file.name,
        fileSize: file.size,
        contentType: file.type || 'application/octet-stream',
      })),
    }),
  });
  onPlanCreated?.(plan);
  const uploads = plan.uploads || (plan.upload ? [plan.upload] : []);
  if (uploads.length !== files.length) {
    await fetch(`/api/domestic-labor/runs/${plan.runId}`, { method: 'DELETE' }).catch(() => {});
    throw new Error('上传计划与所选文件数量不一致，请重新选择文件。');
  }
  try {
    await uploadDomesticFilesConcurrently(uploads, files, (overall, completed) => {
      updateUploadProgress(
        statusElement,
        progressButton,
        `正在并行上传 ${files.length} 个文件：已完成 ${completed}/${files.length}（总进度 ${overall}%）`,
        `上传中 ${overall}%`
      );
    });
  } catch (error) {
    await fetch(`/api/domestic-labor/runs/${plan.runId}`, { method: 'DELETE' }).catch(() => {});
    throw error;
  }
  updateUploadProgress(statusElement, progressButton, '上传完成，正在校验并核算...');
  return requestJson(`/api/domestic-labor/runs/${plan.runId}/direct-upload-complete`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ engines, attendanceMonth, password, hrbpList }),
  });
}

async function uploadDomesticFilesConcurrently(uploads, files, onProgress) {
  const progressByFile = files.map(() => 0);
  const totalBytes = files.reduce((sum, file) => sum + Math.max(1, Number(file.size || 0)), 0);
  const report = () => {
    const uploadedBytes = files.reduce((sum, file, index) => {
      return sum + Math.max(1, Number(file.size || 0)) * progressByFile[index] / 100;
    }, 0);
    const overall = Math.min(100, Math.round(uploadedBytes / totalBytes * 100));
    const completed = progressByFile.filter(percent => percent >= 100).length;
    onProgress(overall, completed);
  };
  let nextIndex = 0;
  const workerCount = Math.min(3, files.length);
  const uploadNext = async () => {
    while (nextIndex < files.length) {
      const index = nextIndex;
      nextIndex += 1;
      await uploadDomesticFileToSignedUrl(uploads[index], files[index], (percent) => {
        progressByFile[index] = percent;
        report();
      });
    }
  };
  await Promise.all(Array.from({ length: workerCount }, uploadNext));
}

function uploadDomesticFileToSignedUrl(upload, file, onProgress) {
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
      reject(new Error(`直传文件失败（HTTP ${request.status}）${request.responseText ? ` ${request.responseText.slice(0, 160)}` : ''}`));
    };
    request.onerror = () => reject(new Error('直传文件失败，请检查网络后重试。'));
    request.ontimeout = () => reject(new Error('直传文件超时，请检查网络后重试。'));
    const body = new FormData();
    body.append('cacheControl', '3600');
    body.append('', file);
    request.send(body);
  });
}

function submitDomesticLaborRunMultipart({ files, engines, attendanceMonth, password, hrbpList }) {
  const form = new FormData();
  files.forEach(file => form.append('files', file));
  form.append('engines', engines.join(','));
  form.append('attendance_month', attendanceMonth);
  form.append('password', password || '');
  if (hrbpList) form.append('hrbp_list', JSON.stringify(hrbpList));
  return requestJson('/api/domestic-labor/runs', { method: 'POST', body: form });
}

function showTaskSection() {
  if (el.workspaceEmpty) el.workspaceEmpty.hidden = true;
  if (el.taskStatusSection) el.taskStatusSection.hidden = false;
  renderTaskStatusCard('submitted');
}

function renderTaskStatusCard(status) {
  if (!el.taskStatusCard || !el.taskStatusSub) return;
  const statusLabels = {
    draft: { label: '草稿', tone: 'warn', text: '当前批次尚未提交计算。先创建任务，系统会进入数据校验和科目核算流程。' },
    submitted: { label: '已提交', tone: 'warn', text: '任务已提交，等待后台计算。' },
    '已上传': { label: '已上传', tone: 'warn', text: '文件已上传，系统正在准备校验和计算。' },
    '计算中': { label: '计算中', tone: 'warn', text: '正在计算薪酬，请稍候。' },
    '已完成': { label: '已完成', tone: 'ok', text: '计算完成，可在结果页导出。' },
    '失败': { label: '失败', tone: 'block', text: '计算失败，请检查文件后重试。' },
  };
  const s = statusLabels[status] || statusLabels.submitted;
  const config = getWorkbenchConfig(getActiveWorkbenchSubject());
  el.taskStatusCard.innerHTML = `
    <div class="dl-empty">
      <div>
        <span class="dl-badge ${s.tone}">${s.label}</span>
        <h2 style="margin:12px 0 0;">${s.text}</h2>
        <p>本工作台按「数据上传 → 字段检查 → ${escapeHtml(config.name)}核算」路径处理，导出作为结果页动作。</p>
      </div>
      <div class="dl-empty-map">
        <div class="dl-empty-map-row"><strong>01</strong><span>数据上传</span></div>
        <div class="dl-empty-map-row"><strong>02</strong><span>字段检查</span></div>
        <div class="dl-empty-map-row"><strong>03</strong><span>${escapeHtml(config.name)}核算</span></div>
      </div>
    </div>
  `;
  el.taskStatusSub.textContent = s.text;
  if (el.batchStatusText) {
    el.batchStatusText.textContent = s.label;
    el.batchStatusText.classList.toggle('is-ok', s.tone === 'ok');
    el.batchStatusText.classList.toggle('is-warn', s.tone !== 'ok');
  }
}

function startPolling() {
  stopPolling();
  state.pollRetryCount = 0;
  state.pollRequestInFlight = false;
  pollStatus();
  state.pollTimer = window.setInterval(pollStatus, 1500);
}

function stopPolling() {
  if (state.pollTimer) {
    window.clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
  state.pollRequestInFlight = false;
}

async function loadCompletedRun(runId) {
  const [metadata, resultPayload] = await Promise.all([
    requestJson(`/api/domestic-labor/runs/${runId}?response_mode=status`),
    requestJson(`/api/domestic-labor/runs/${runId}/results`),
  ]);
  const completedRun = { ...metadata, ...resultPayload, id: metadata.id || runId };
  state.currentRun = completedRun;
  syncCanbuBatchFromRun(completedRun);
  renderTaskStatusCard(completedRun.status || '已完成');
  finishCanbuOperation(runId);
  renderResults(completedRun);
  if (el.btnExport) el.btnExport.hidden = false;
  return completedRun;
}

async function pollStatus() {
  if (!state.currentRun || state.pollRequestInFlight) return;
  state.pollRequestInFlight = true;
  state.pollRetryCount++;

  if (state.pollRetryCount > state.pollMaxRetries) {
    stopPolling();
    finishCanbuOperation(state.currentRun?.id || '', '计算超时，请稍后重新进入批次查看状态。');
    renderTaskStatusCard('失败');
    setText(el.taskStatusSub, '计算超时（10分钟），请刷新重试。', true);
    toast('计算超时。');
    state.pollRequestInFlight = false;
    return;
  }

  try {
    const metadata = await requestJson(`/api/domestic-labor/runs/${state.currentRun.id}?response_mode=status`);
    state.currentRun = metadata;

    const status = metadata.status || '计算中';
    syncCanbuBatchFromRun(metadata);
    renderTaskStatusCard(status);

    if (status === '已完成') {
      stopPolling();
      await loadCompletedRun(metadata.id);
      toast('薪酬计算完成！');
    } else if (status === '失败') {
      stopPolling();
      const errMsg = metadata.error || '计算失败，请检查文件后重试。';
      finishCanbuOperation(metadata.id, errMsg);
      setText(el.taskStatusSub, errMsg, true);
      toast(errMsg);
    }
  } catch (error) {
    // Ignore transient errors during polling
  } finally {
    state.pollRequestInFlight = false;
  }
}

async function refreshStatus() {
  if (!state.currentRun) return toast('暂无任务。');
  try {
    const metadata = await requestJson(`/api/domestic-labor/runs/${state.currentRun.id}?response_mode=status`);
    state.currentRun = metadata;
    const status = metadata.status || '计算中';
    syncCanbuBatchFromRun(metadata);
    renderTaskStatusCard(status);
    if (status === '已完成') {
      await loadCompletedRun(metadata.id);
    }
    toast('状态已刷新。');
  } catch (error) {
    toast(error.message);
  }
}

function renderResults(metadata) {
  const results = sanitizePayrollResults(metadata.results);
  const summary = metadata.summary || {};
  const resultRunId = metadata.id || metadata.run_id || state.currentRun?.id || '';
  state.currentResults = results;
  state.currentResultsRunId = resultRunId;
  if (results.length) enableReportExportLink();
  else resetReportLink();

  const activeBatch = getActiveCanbuBatch?.();
  if (activeBatch && state.view === 'canbuWorkbench') {
    if (activeBatch.runId && resultRunId && activeBatch.runId !== resultRunId) {
      return;
    }
    const config = getWorkbenchConfig(activeBatch.subject);
    const subjectWarnings = countWorkbenchWarnings(results, activeBatch.subject);
    updateActiveCanbuBatch({
      status: subjectWarnings ? '已核算' : '可导出',
      employeeCount: results.length,
      payableTotal: summary[config.totalField] ?? sumField(results, config.resultField),
      exceptionCount: subjectWarnings,
      runId: resultRunId || activeBatch.runId,
    });
    syncCanbuBatchFromRun(metadata, {
      includeResults: true,
      status: subjectWarnings ? '已核算' : '可导出',
    });
    renderCanbuWorkbench('results');
    return;
  }

  if (!el.taskStatusCard) return;

  syncCanbuBatchFromRun(metadata, { includeResults: true });

  // Update KPI - 适配后端字段名
  if (el.kpiTotalVal) el.kpiTotalVal.textContent = summary.total_employees || summary.totalEmployees || '—';
  if (el.kpiProcessedVal) el.kpiProcessedVal.textContent = results.length || '—';
  if (el.kpiWarningsVal) el.kpiWarningsVal.textContent = summary.warning_count ?? countWarnings(results);
  if (el.kpiGrandVal) el.kpiGrandVal.textContent = formatMoney(summary.grand_total ?? sumField(results, 'total'));

  // Per-engine KPI - 适配后端汇总格式
  if (el.kpiQuanqinVal) el.kpiQuanqinVal.textContent = formatMoney(summary.total_quanqinjiang ?? 0);
  if (el.kpiCanbuVal) el.kpiCanbuVal.textContent = formatMoney(summary.total_canbu ?? 0);
  if (el.kpiWaisuVal) el.kpiWaisuVal.textContent = formatMoney(summary.total_waisu_butie ?? 0);
  if (el.kpiGonglingVal) el.kpiGonglingVal.textContent = formatMoney(summary.total_gonglingjiang ?? 0);

  // Results table
  if (el.resultsSection) el.resultsSection.hidden = false;
  renderResultsTable(results);
  renderExceptionQueue(results);

  // Engine summary - 适配后端汇总格式
  const engineSummary = {
    quanqinjiang: { count: results.filter(r => r.quanqinjiang > 0).length, totalAmount: summary.total_quanqinjiang || 0 },
    canbu: { count: results.filter(r => r.canbu > 0).length, totalAmount: summary.total_canbu || 0 },
    waisu_butie: { count: results.filter(r => r.waisu_butie > 0).length, totalAmount: summary.total_waisu_butie || 0 },
    gonglingjiang: { count: results.filter(r => r.gonglingjiang > 0).length, totalAmount: summary.total_gonglingjiang || 0 },
    gangwei_butie: { count: results.filter(r => r.gangwei_butie > 0).length, totalAmount: summary.total_gangwei_butie || 0 },
    gaowen_butie: { count: results.filter(r => r.gaowen_butie > 0).length, totalAmount: summary.total_gaowen_butie || 0 },
    yeban_butie: { count: results.filter(r => r.yeban_butie > 0).length, totalAmount: summary.total_yeban_butie || 0 },
  };
  if (el.engineSummarySection) el.engineSummarySection.hidden = false;
  renderEngineSummary(engineSummary);
}

function renderResultsTable(results) {
  if (!el.resultsTable) {
    return;
  }
  const filtered = filterResults(results);
  updateResultCount(results.length, filtered.length);
  if (!filtered.length) {
    el.resultsTable.innerHTML = `
      <div class="dl-empty">
        <div>
          <span class="dl-badge warn">等待数据</span>
          <h2>员工薪酬结果会显示在这里</h2>
          <p>结果表将包含员工工号、部门、岗位、各科目金额、计算结果、异常等级、复核状态与导出就绪状态。</p>
        </div>
        <div class="dl-empty-map">
          <div class="dl-empty-map-row"><strong>表格</strong><span>可筛选、可排序、可追溯</span></div>
          <div class="dl-empty-map-row"><strong>异常</strong><span>阻断、高风险、提示分级</span></div>
          <div class="dl-empty-map-row"><strong>解释</strong><span>点击员工行打开右侧抽屉</span></div>
        </div>
      </div>
    `;
    return;
  }

  const tbody = filtered.map((row) => {
    const warningLevel = getWarningLevel(row);
    const needsReview = hasReviewIssue(row);
    return `
      <tr data-result-index="${results.indexOf(row)}">
        <td class="dl-strong">${escapeHtml(row.employee_id || '')}</td>
        <td>${escapeHtml(row.employee_name || '')}</td>
        <td>${escapeHtml(row.department || '—')}</td>
        <td><span class="dl-badge ok">在职</span></td>
        <td class="dl-num">${formatMoney(row.quanqinjiang)}</td>
        <td class="dl-num">${formatMoney(row.canbu)}</td>
        <td class="dl-num">${formatMoney(row.waisu_butie)}</td>
        <td class="dl-num">${formatMoney(row.gonglingjiang)}</td>
        <td class="dl-num">${formatMoney(row.gangwei_butie)}</td>
        <td class="dl-num">${formatMoney(row.gaowen_butie)}</td>
        <td class="dl-num">${formatMoney(row.yeban_butie)}</td>
        <td class="dl-num dl-strong">${formatMoney(row.total)}</td>
        <td><span class="dl-badge ${warningLevel.className}">${warningLevel.label}</span></td>
        <td><span class="dl-badge">${needsReview ? '待复核' : '自动通过'}</span></td>
        <td><button class="dl-segment" data-explain-index="${results.indexOf(row)}" type="button">解释</button></td>
      </tr>
    `;
  }).join('');

  el.resultsTable.innerHTML = `
    <table class="dl-table">
      <thead>
        <tr>
          <th>工号</th>
          <th>姓名</th>
          <th>部门</th>
          <th>在职状态</th>
          <th class="dl-num">全勤奖</th>
          <th class="dl-num">餐补</th>
          <th class="dl-num">外宿补贴</th>
          <th class="dl-num">工龄奖</th>
          <th class="dl-num">岗位补贴</th>
          <th class="dl-num">高温补贴</th>
          <th class="dl-num">夜班补贴</th>
          <th class="dl-num">应发合计</th>
          <th>异常等级</th>
          <th>复核状态</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>${tbody}</tbody>
    </table>
  `;
  el.resultsTable.querySelectorAll('[data-result-index], [data-explain-index]').forEach(item => {
    item.addEventListener('click', (event) => {
      const node = event.target.closest('[data-result-index], [data-explain-index]');
      const index = Number(node.dataset.resultIndex ?? node.dataset.explainIndex);
      openExplainDrawer(results[index]);
    });
  });
}

function renderEngineSummary(engineSummary) {
  if (!el.engineSummaryGrid || !el.engineSummarySection) return;
  const html = Object.entries(engineSummary).map(([key, info]) => {
    const meta = ENGINE_META[key] || { name: key, icon: '', color: 'neutral' };
    return `
      <div class="dl-metric">
        <span class="dl-metric-label">${meta.name}<span class="dl-dot"></span></span>
        <span class="dl-metric-value">${formatMoney(info.totalAmount ?? 0)}</span>
        <span class="dl-metric-meta">${info.count ?? 0} 人 · 异常 ${countSubjectWarnings(state.currentResults, key)}</span>
      </div>
    `;
  }).join('');
  el.engineSummaryGrid.innerHTML = html;
}

function renderEmptyWorkbench() {
  if (!el.taskStatusCard || !el.resultsTable || !el.exceptionQueue || !el.engineSummaryGrid) return;
  renderTaskStatusCard('draft');
  renderResultsTable([]);
  renderExceptionQueue([]);
  resetReportLink();
}

function updateResultCount(total, filtered) {
  if (!el.resultCountText) return;
  el.resultCountText.textContent = total
    ? `显示 ${filtered} / ${total} 条`
    : '暂无结果';
}

function toggleRail() {
  if (!el.payrollShell || !el.btnToggleRail) return;
  const collapsed = el.payrollShell.classList.toggle('rail-collapsed');
  el.btnToggleRail.setAttribute('aria-expanded', String(!collapsed));
  el.btnToggleRail.setAttribute('aria-label', collapsed ? '展开批次流程' : '收起批次流程');
  const icon = el.btnToggleRail.querySelector('.dl-rail-toggle-icon');
  const text = el.btnToggleRail.querySelector('.dl-rail-toggle-text');
  if (icon) icon.textContent = collapsed ? '›' : '‹';
  if (text) text.textContent = collapsed ? '展开流程' : '收起流程';
}

function toggleAside() {
  if (!el.payrollShell || !el.btnToggleAside) return;
  const collapsed = el.payrollShell.classList.toggle('aside-collapsed');
  el.btnToggleAside.setAttribute('aria-expanded', String(!collapsed));
  el.btnToggleAside.setAttribute('aria-label', collapsed ? '展开异常队列' : '收起异常队列');
  const icon = el.btnToggleAside.querySelector('.dl-aside-toggle-icon');
  const text = el.btnToggleAside.querySelector('.dl-aside-toggle-text');
  if (icon) icon.textContent = collapsed ? '‹' : '›';
  if (text) text.textContent = collapsed ? '展开异常' : '收起异常';
}

function filterResults(results) {
  const keyword = state.resultSearch.trim().toLowerCase();
  return results.filter(row => {
    if (state.activeSubject === 'warnings' && !hasReviewIssue(row)) return false;
    if (state.activeSubject !== 'all' && state.activeSubject !== 'warnings' && Number(row[state.activeSubject] || 0) === 0) return false;

    if (state.reviewStatusFilter === 'review' && !hasReviewIssue(row)) return false;
    if (state.reviewStatusFilter === 'pass' && hasReviewIssue(row)) return false;

    const total = Number(row.total || 0);
    if (state.amountFilter === 'positive' && total <= 0) return false;
    if (state.amountFilter === 'zero' && total !== 0) return false;

    if (!keyword) return true;
    const haystack = [
      row.employee_id,
      row.employee_name,
      row.department,
      row.position,
      row.warning,
      getEffectiveWarningText(row),
    ].map(value => String(value || '').toLowerCase()).join(' ');
    return haystack.includes(keyword);
  });
}

function renderExceptionQueue(results) {
  if (!el.exceptionQueue) return;
  const activeSubject = state.view === 'canbuWorkbench' ? getActiveWorkbenchSubject() : '';
  const rows = results.filter(row => activeSubject ? hasSubjectReviewIssue(row, activeSubject) : hasReviewIssue(row));
  if (!rows.length) {
    el.exceptionQueue.innerHTML = `
      <div class="dl-exception">
        <p class="dl-exception-title">暂无异常</p>
        <p class="dl-exception-meta">完成计算后，阻断、高风险和提示类异常会进入这里。</p>
      </div>
    `;
    return;
  }
  el.exceptionQueue.innerHTML = rows.map(row => {
    const level = activeSubject ? getSubjectWarningLevel(row, activeSubject) : getWarningLevel(row);
    const firstException = activeSubject ? getSubjectExceptions(row, activeSubject)[0] : getEffectiveExceptions(row)[0];
    const message = firstException?.message || getEffectiveWarningText(row);
    return `
      <button class="dl-exception ${level.className}" data-exception-id="${escapeHtml(row.employee_id)}" type="button">
        <p class="dl-exception-title">${level.label} · ${escapeHtml(row.employee_id)} ${escapeHtml(row.employee_name)}</p>
        <p class="dl-exception-meta">${escapeHtml(message)}</p>
      </button>
    `;
  }).join('');
  el.exceptionQueue.querySelectorAll('[data-exception-id]').forEach(item => {
    item.addEventListener('click', () => {
      const row = results.find(candidate => candidate.employee_id === item.dataset.exceptionId);
      if (row) openExplainDrawer(row);
    });
  });
}

function openExplainDrawer(row) {
  if (!row || !el.explainDrawer || !el.explainTitle || !el.explainBody) return;
  const allSubjectKeys = ['quanqinjiang', 'canbu', 'waisu_butie', 'gonglingjiang', 'gangwei_butie', 'gaowen_butie', 'yeban_butie'];
  const activeSubject = state.view === 'canbuWorkbench' ? getActiveWorkbenchSubject() : '';
  const calculatedSubjectKeys = allSubjectKeys.filter(key => getSubjectDetail(row, key));
  const subjectKeys = activeSubject && ENGINE_META[activeSubject]
    ? [activeSubject]
    : (calculatedSubjectKeys.length ? calculatedSubjectKeys : allSubjectKeys);
  const singleSubject = subjectKeys.length === 1 ? subjectKeys[0] : '';
  const singleSubjectMeta = singleSubject ? ENGINE_META[singleSubject] : null;
  if (singleSubject === 'yeban_butie') {
    renderNightShiftExplanation(row);
    el.explainDrawer.classList.add('open');
    return;
  }
  if (singleSubject === 'gaowen_butie') {
    renderHighTemperatureExplanation(row);
    el.explainDrawer.classList.add('open');
    return;
  }
  el.explainTitle.textContent = `${row.employee_id || ''} ${row.employee_name || ''}`;
  const subjectCards = subjectKeys.map(key => {
    const meta = ENGINE_META[key];
    const amount = Number(row[key] || 0);
    const subjectDetail = getSubjectDetail(row, key);
    const explanation = subjectDetail?.audit_explanation;
    return `
      <div class="dl-rule-card">
        <h3>${meta.name}：${formatMoney(amount)}</h3>
        <dl>
          <dt>规则状态</dt><dd>${explanation?.rule_name ? escapeHtml(explanation.rule_name) : (amount ? '已命中发放规则' : '未产生发放金额或无资格')}</dd>
          <dt>计算公式</dt><dd>${escapeHtml(explanation?.formula || '来自本批次月考勤、日考勤、住宿名单及科目参数')}</dd>
          <dt>关键输入</dt><dd>${formatAuditMap(explanation?.inputs)}</dd>
          <dt>中间值</dt><dd>${formatAuditMap(explanation?.intermediate_values)}</dd>
          <dt>计算步骤</dt><dd>${formatAuditSteps(explanation?.steps) || buildRuleExplanation(key, row)}</dd>
        </dl>
      </div>
    `;
  }).join('');
  const rowExceptions = singleSubject ? getSubjectExceptions(row, singleSubject) : getEffectiveExceptions(row);
  const warningText = getEffectiveWarningText(row);
  const needsReview = singleSubject ? hasSubjectReviewIssue(row, singleSubject) : hasReviewIssue(row);
  const warningLevel = singleSubject ? getSubjectWarningLevel(row, singleSubject) : getWarningLevel(row);
  const payableLabel = singleSubjectMeta ? `应发${singleSubjectMeta.name}` : '应发合计';
  const payableAmount = singleSubject ? row[singleSubject] : row.total;
  el.explainBody.innerHTML = `
    <div class="dl-kv-grid">
      <div class="dl-kv"><span>部门</span><strong>${escapeHtml(row.department || '—')}</strong></div>
      <div class="dl-kv"><span>${escapeHtml(payableLabel)}</span><strong>${formatMoney(payableAmount)}</strong></div>
      <div class="dl-kv"><span>复核状态</span><strong>${needsReview ? '待复核' : '自动通过'}</strong></div>
    </div>
    ${subjectCards}
    <div class="dl-rule-card">
      <h3>异常与处理</h3>
      <dl>
        <dt>异常等级</dt><dd>${warningLevel.label}</dd>
        <dt>异常说明</dt><dd>${formatExceptions(rowExceptions) || escapeHtml(warningText || '暂无异常')}</dd>
        <dt>建议动作</dt><dd>${rowExceptions[0]?.suggested_action ? escapeHtml(rowExceptions[0].suggested_action) : (warningText ? '确认数据、补充规则参数或登记人工调整原因。' : '无需人工处理，结果可直接导出。')}</dd>
      </dl>
    </div>
  `;
  el.explainDrawer.classList.add('open');
}

function closeExplainDrawer() {
  el.explainDrawer?.classList.remove('open');
}

function buildRuleExplanation(key, row) {
  if (key === 'quanqinjiang') return '按考勤月份、入离职、旷工、签卡和迟到分档判断；6分钟内最多3次或6-20分钟最多1次，两档不可混用。';
  if (key === 'canbu') return '按餐补资格、日有效出勤和月度封顶金额计算。';
  if (key === 'waisu_butie') return '按外宿资格、当月在职天数、住宿扣除和缺勤阈值折算。';
  if (key === 'gonglingjiang') return '按地区、部门、岗位、工龄、排班天数、缺勤与揽收线工龄奖名单计算。';
  if (key === 'gangwei_butie') return '按地区、岗位名称、岗位补贴标准、排班天数和56小时缺勤门槛计算；入离职缺勤优先读取已有值，否则按排班天数与实际在职工作日天数自动计算；女神假每1天按8小时折算，职级不参与。';
  if (key === 'gaowen_butie') return '按同测温网点、同出勤日期、同白/夜班最高温是否达到33℃判断；达到后取正班时数与刷卡加班较大值，按地区小时单价、单日及月度上限逐日计算。';
  if (key === 'yeban_butie') return '按夜班窗口、半小时取整、平台班次休息、固定地区规则和晋江额外排除名单逐日计算。';
  return '该科目按照当前规则包计算。';
}

function getWarningLevel(row) {
  const exceptions = getEffectiveExceptions(row);
  if (exceptions.some(item => item.level === 'blocking')) return { label: '阻断', className: 'block' };
  if (exceptions.some(item => item.level !== 'info')) return { label: '高风险', className: 'warn' };
  if (exceptions.length) return { label: '提示', className: 'warn' };
  const text = getEffectiveWarningText(row);
  if (!text) return { label: '通过', className: 'ok' };
  if (/失败|异常|不存在|缺失|请提供/.test(text)) return { label: '高风险', className: 'warn' };
  return { label: '提示', className: 'warn' };
}

function getSubjectExceptions(row, subject) {
  return (getSubjectDetail(row, subject)?.exceptions || []).filter(item => !isNormalHrbpListExclusionException(item));
}

function hasSubjectReviewIssue(row, subject) {
  return getSubjectExceptions(row, subject).length > 0 || Boolean(getEffectiveWarningText(row));
}

function getSubjectWarningLevel(row, subject) {
  const exceptions = getSubjectExceptions(row, subject);
  if (exceptions.some(item => item.level === 'blocking')) return { label: '阻断', className: 'block' };
  if (exceptions.some(item => item.level !== 'info')) return { label: '高风险', className: 'warn' };
  if (exceptions.length || getEffectiveWarningText(row)) return { label: '提示', className: 'warn' };
  return { label: '通过', className: 'ok' };
}

function countWarnings(results) {
  return results.filter(hasReviewIssue).length;
}

function countCanbuWarnings(results) {
  return results.filter(hasCanbuReviewIssue).length;
}

function countWorkbenchWarnings(results, subject) {
  if (subject === 'canbu') return countCanbuWarnings(results);
  if (subject === 'waisu_butie') return results.filter(hasWaisuReviewIssue).length;
  return countSubjectWarnings(results, subject);
}

function hasValidEmployeeId(row) {
  const text = String(row?.employee_id ?? '').trim();
  return Boolean(text) && !['none', 'null', 'nan'].includes(text.toLowerCase()) && text !== '工号';
}

function sanitizePayrollResults(results) {
  return Array.isArray(results) ? results.filter(hasValidEmployeeId) : [];
}

function countSubjectWarnings(results, key) {
  return results.filter(row => {
    const subjectExceptions = (getSubjectDetail(row, key)?.exceptions || []).filter(item => !isNormalHrbpListExclusionException(item));
    return subjectExceptions.length || (getEffectiveWarningText(row) && Number(row[key] || 0) !== 0);
  }).length;
}

function sumField(results, key) {
  return results.reduce((sum, row) => sum + Number(row[key] || 0), 0);
}

function getSubjectDetail(row, key) {
  return row.subject_details?.[key] || null;
}

function getRowExceptions(row) {
  if (Array.isArray(row.exceptions)) return row.exceptions;
  const details = row.subject_details || {};
  return Object.values(details).flatMap(item => item?.exceptions || []);
}

function getEffectiveExceptions(row) {
  return getRowExceptions(row).filter(item => !isNormalHrbpListExclusionException(item));
}

function getEffectiveWarningText(row) {
  const text = String(row.warnings || '').trim();
  if (!text) return '';
  return text
    .split(';')
    .map(item => item.trim())
    .filter(Boolean)
    .filter(item => !isNormalHrbpListExclusionText(item))
    .join('; ');
}

function hasReviewIssue(row) {
  return getEffectiveExceptions(row).length > 0 || Boolean(getEffectiveWarningText(row));
}

function isNormalHrbpListExclusionException(item) {
  if (!item) return false;
  return item.code === 'NOT_IN_HRBP_LIST' || isNormalHrbpListExclusionText(item.message);
}

function isNormalHrbpListExclusionText(value) {
  const text = String(value || '');
  return /不在本月HRBP发放名单|不在.*HRBP.*发放名单|未命中揽收线工龄奖名单|揽收工龄奖不发放/.test(text);
}

function formatAuditMap(value) {
  if (!value || typeof value !== 'object' || !Object.keys(value).length) return '—';
  return Object.entries(value)
    .map(([key, val]) => `<span class="dl-badge" style="margin:0 6px 6px 0;">${escapeHtml(key)}: ${escapeHtml(String(val ?? ''))}</span>`)
    .join('');
}

function formatAuditSteps(steps) {
  if (!Array.isArray(steps) || !steps.length) return '';
  return `<ol style="margin:0; padding-left:18px;">${steps.map(step => `<li>${escapeHtml(step)}</li>`).join('')}</ol>`;
}

function formatExceptions(exceptions) {
  if (!Array.isArray(exceptions) || !exceptions.length) return '';
  return exceptions.map(item => {
    const code = item.code ? `[${item.code}] ` : '';
    return `<p style="margin:0 0 6px;">${escapeHtml(code + (item.message || ''))}</p>`;
  }).join('');
}

function resetReportLink() {
  if (!el.reportLink) return;
  el.reportLink.href = '#';
  el.reportLink.dataset.readyToExport = 'false';
  el.reportLink.classList.add('disabled');
  el.reportLink.setAttribute('aria-disabled', 'true');
}

function enableReportExportLink() {
  if (!el.reportLink) return;
  el.reportLink.href = '#';
  el.reportLink.dataset.readyToExport = 'true';
  el.reportLink.classList.remove('disabled');
  el.reportLink.removeAttribute('aria-disabled');
}

async function exportResults(autoDownload = false) {
  if (!state.currentRun) return toast('暂无任务。');
  if (state.exportInProgress) return;
  state.exportInProgress = true;
  const exportButtons = [...new Set([
    el.btnExport,
    document.querySelector('#btnExportCanbu'),
  ].filter(Boolean))];
  exportButtons.forEach(button => setExportButtonState(button, 'exporting'));
  setText(el.taskStatusSub, '正在生成 Excel...');
  try {
    const data = await requestJson(`/api/domestic-labor/runs/${state.currentRun.id}/export`);
    const downloadUrl = `/api/domestic-labor/runs/${state.currentRun.id}/download/${encodeURIComponent(data.file_name)}`;
    if (el.reportLink) {
      el.reportLink.href = downloadUrl;
      el.reportLink.dataset.readyToExport = 'false';
      el.reportLink.classList.remove('disabled');
      el.reportLink.removeAttribute('aria-disabled');
    }
    if (autoDownload) {
      window.location.href = downloadUrl;
      toast('Excel 已生成，正在下载。');
      setText(el.taskStatusSub, 'Excel 已生成，正在下载。');
    } else {
      toast('Excel 已生成，点击下载。');
      setText(el.taskStatusSub, 'Excel 已生成。');
    }

    syncCanbuBatchFromRun(state.currentRun, {
      status: '已导出',
      exportFileName: data.file_name,
      exportedAt: new Date().toISOString(),
    });
    exportButtons.forEach(button => setExportButtonState(button, 'exported'));
    await new Promise(resolve => window.setTimeout(resolve, 650));
    if (state.view === 'canbuWorkbench' && getActiveCanbuBatch()) {
      syncWorkbenchChrome(getActiveCanbuBatch());
    }
  } catch (error) {
    toast(error.message);
    setText(el.taskStatusSub, error.message, true);
    exportButtons.forEach(button => setExportButtonState(button, 'error'));
    await new Promise(resolve => window.setTimeout(resolve, 900));
  } finally {
    state.exportInProgress = false;
    exportButtons.forEach(button => setExportButtonState(button, 'idle'));
  }
}

function setExportButtonState(button, status) {
  if (!button) return;
  if (!button.dataset.exportDefaultLabel) {
    button.dataset.exportDefaultLabel = button.textContent.trim() || '导出结果';
    button.dataset.exportWasDisabled = button.disabled ? 'true' : 'false';
  }
  button.classList.toggle('is-exporting', status === 'exporting');
  button.classList.toggle('is-exported', status === 'exported');
  button.classList.toggle('is-export-error', status === 'error');

  if (status === 'idle') {
    button.disabled = button.dataset.exportWasDisabled === 'true';
    button.removeAttribute('aria-busy');
    button.textContent = button.dataset.exportDefaultLabel;
    delete button.dataset.exportDefaultLabel;
    delete button.dataset.exportWasDisabled;
    return;
  }

  button.disabled = true;
  button.setAttribute('aria-busy', status === 'exporting' ? 'true' : 'false');
  if (status === 'exporting') {
    button.innerHTML = `
      <span>正在生成 Excel</span>
      <span class="dl-export-button-dots" aria-hidden="true"><span></span><span></span><span></span></span>
    `;
  } else if (status === 'exported') {
    button.textContent = 'Excel 已生成';
  } else {
    button.textContent = '生成失败，请重试';
  }
}

// ── Utility functions ──
async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data.detail;
    const message = typeof detail === 'string'
      ? detail
      : detail?.message || detail?.nextAction || '请求失败。';
    const error = new Error(message);
    error.status = response.status;
    error.code = detail?.errorCode || '';
    throw error;
  }
  return data;
}

function setText(element, value, error = false) {
  if (!element) return;
  element.textContent = value;
  element.classList.toggle('error-text', error);
}

function setButtonBusy(button, busy, label = '处理中...') {
  if (!button) return;
  if (busy) {
    if (!button.dataset.idleText) button.dataset.idleText = button.textContent.trim();
    button.classList.add('is-busy');
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    button.replaceChildren();
    const spinner = document.createElement('span');
    spinner.className = 'dl-button-spinner';
    spinner.setAttribute('aria-hidden', 'true');
    const text = document.createElement('span');
    text.className = 'dl-button-busy-label';
    text.textContent = label;
    button.append(spinner, text);
    return;
  }
  button.classList.remove('is-busy');
  button.disabled = false;
  button.removeAttribute('aria-busy');
  button.textContent = button.dataset.idleText || button.textContent;
  delete button.dataset.idleText;
}

function updateUploadProgress(statusElement, progressButton, message, buttonLabel = message) {
  setText(statusElement, message);
  updateCanbuOperation(message);
  const label = progressButton?.querySelector('.dl-button-busy-label');
  if (label) label.textContent = buttonLabel;
}

function toast(message) {
  el.toast.textContent = message;
  el.toast.classList.add('visible');
  window.setTimeout(() => el.toast.classList.remove('visible'), 2600);
}

function formatMoney(value) {
  return Number(value || 0).toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function displayValue(...values) {
  for (const value of values) {
    if (value === undefined || value === null) continue;
    const text = String(value).trim();
    if (!text || ['none', 'null', 'nan'].includes(text.toLowerCase())) continue;
    return text;
  }
  return '';
}

function escapeHtml(value) {
  return String(value ?? '').replace(
    /[&<>"']/g,
    (char) =>
      ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;',
      }[char])
  );
}
