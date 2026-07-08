/**
 * Domestic Labor Payroll - 西格玛工作台
 * 劳务工薪酬核算前端交互
 */

const state = {
  selectedEngines: [],
  attendanceMonth: '',
  payrollFile: null,
  hrbpList: null,
  currentRun: null,
  currentResults: [],
  view: 'home',
  canbuBatches: [],
  activeCanbuBatchId: '',
  activeSubject: 'all',
  resultSearch: '',
  reviewStatusFilter: 'all',
  amountFilter: 'all',
  canbuRegionFilter: 'all',
  canbuPage: 1,
  canbuPageSize: 50,
  canbuSearchComposing: false,
  pollTimer: null,
  pollRetryCount: 0,
  pollMaxRetries: 200, // 200 × 3s = 10 min
};

const CANBU_BATCH_STORAGE_KEY = 'domesticLabor.canbuBatches.v1';
const CANBU_STEPS = [
  { key: 'upload', label: '数据上传' },
  { key: 'fields', label: '字段检查' },
  { key: 'results', label: '餐补核算' },
  { key: 'exported', label: '导出归档' },
];

const ENGINE_META = {
  quanqinjiang: {
    name: '全勤奖',
    desc: '100元/人/月，按出勤天数、迟到、旷工等条件计算',
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
};

const DEFAULT_HRBP_LIST = [
  'OWHN2313',
  'OWHN0424',
  'OWHN6172',
  'OWHN0474',
  'OWHN2248',
  'OWHN6887',
  'OWHN10141',
  'OWHN10605',
  'OWHN10863',
  'OWHN10892',
  'OWHN11388',
  'OWHN11405',
];

function loadCanbuBatches() {
  try {
    const raw = window.localStorage.getItem(CANBU_BATCH_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    state.canbuBatches = Array.isArray(parsed) ? parsed : [];
  } catch {
    state.canbuBatches = [];
  }
}

function saveCanbuBatches() {
  window.localStorage.setItem(CANBU_BATCH_STORAGE_KEY, JSON.stringify(state.canbuBatches));
}

function createCanbuBatch(month, name) {
  const now = new Date().toISOString();
  const batch = {
    id: `canbu-${Date.now()}`,
    subject: 'canbu',
    month,
    name: name || `${month} 餐补初算`,
    status: '草稿',
    employeeCount: 0,
    payableTotal: 0,
    exceptionCount: 0,
    exportFileName: '',
    exportedAt: '',
    runId: '',
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
  hrbpList: document.querySelector('#hrbpList'),
  paramStatus: document.querySelector('#paramStatus'),
  btnToStep4: document.querySelector('#btnToStep4'),
  confirmEngines: document.querySelector('#confirmEngines'),
  confirmMonth: document.querySelector('#confirmMonth'),
  confirmFile: document.querySelector('#confirmFile'),
  confirmHrbp: document.querySelector('#confirmHrbp'),
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
  canbuBatchListView: document.querySelector('#canbuBatchListView'),
  canbuWorkbenchView: document.querySelector('#canbuWorkbenchView'),
  subjectCardGrid: document.querySelector('#subjectCardGrid'),
  recentBatchTable: document.querySelector('#recentBatchTable'),
  canbuBatchTable: document.querySelector('#canbuBatchTable'),
  canbuWorkbenchRoot: document.querySelector('#canbuWorkbenchRoot'),
  btnBackHome: document.querySelector('#btnBackHome'),
  canbuBatchModal: document.querySelector('#canbuBatchModal'),
  canbuBatchMonth: document.querySelector('#canbuBatchMonth'),
  btnNewCanbuBatch: document.querySelector('#btnNewCanbuBatch'),
  btnCancelCanbuBatch: document.querySelector('#btnCancelCanbuBatch'),
  btnConfirmCanbuBatch: document.querySelector('#btnConfirmCanbuBatch'),
  explainDrawer: document.querySelector('#explainDrawer'),
  explainTitle: document.querySelector('#explainTitle'),
  explainBody: document.querySelector('#explainBody'),
  btnCloseExplain: document.querySelector('#btnCloseExplain'),
  calcModal: document.querySelector('#calcModal'),
  calcModalTitle: document.querySelector('#calcModalTitle'),
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
  setDefaultHrbpList();
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
  el.canbuBatchMonth.value = getCurrentMonthValue();
}

function setDefaultHrbpList() {
  if (!el.hrbpList || el.hrbpList.value.trim()) return;
  el.hrbpList.value = JSON.stringify(DEFAULT_HRBP_LIST, null, 2);
  state.hrbpList = [...DEFAULT_HRBP_LIST];
  setText(el.paramStatus, `已预置莞深区揽收工龄奖名单 ${DEFAULT_HRBP_LIST.length} 人，可继续补充。`);
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
    const subject = card.dataset.subjectEntry;
    if (subject === 'canbu') {
      state.activeCanbuBatchId = '';
      showView('canbuBatches');
      renderCanbuBatchList();
      return;
    }
    toast('该科目将按餐补样板工作台后续改造。');
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
  setDefaultCanbuBatchMonth();
  el.canbuBatchModal?.classList.add('visible');
  document.body.style.overflow = 'hidden';
  window.setTimeout(() => el.canbuBatchMonth?.focus(), 0);
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
  const month = el.canbuBatchMonth?.value || '';
  if (!month) {
    toast('请先选择餐补核算月份。');
    el.canbuBatchMonth?.focus();
    return;
  }
  const batch = createCanbuBatch(month, `${formatMonthLabel(month)} 餐补初算`);
  state.activeCanbuBatchId = batch.id;
  closeCanbuBatchModal();
  showView('canbuWorkbench');
  renderCanbuWorkbench('upload');
}

function showView(viewName) {
  state.view = viewName;
  [
    ['home', el.subjectHomeView],
    ['canbuBatches', el.canbuBatchListView],
    ['canbuWorkbench', el.canbuWorkbenchView],
  ].forEach(([name, node]) => {
    if (!node) return;
    const active = name === viewName;
    node.hidden = !active;
    node.classList.toggle('active', active);
  });
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
  if (!state.canbuBatches.length) {
    el.canbuBatchTable.innerHTML = '<div class="dl-empty compact"><p>暂无餐补核算批次，请先新建餐补批次。</p></div>';
    return;
  }
  el.canbuBatchTable.innerHTML = renderBatchTable(state.canbuBatches);
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
      showView('canbuWorkbench');
      renderCanbuWorkbench('upload');
    });
  });
}

function renderCanbuWorkbench(step = 'upload') {
  const batch = getActiveCanbuBatch();
  if (!batch || !el.canbuWorkbenchRoot) return;
  const canbuRunId = batch.runId || '';
  const hasMatchingRun = Boolean(canbuRunId && state.currentRun && state.currentRun.id === canbuRunId);
  const canbuResults = hasMatchingRun ? (Array.isArray(state.currentResults) ? state.currentResults : []) : [];
  const showAside = step === 'results' || canbuResults.length > 0;
  el.canbuWorkbenchRoot.innerHTML = `
    <section class="dl-panel dl-workbench-head">
      <div class="dl-panel-head">
        <div>
          <h2 class="dl-panel-title">${escapeHtml(batch.name)}</h2>
          <p class="dl-panel-sub">${escapeHtml(formatMonthLabel(batch.month))} · 餐补核算 · <span class="dl-badge ${getBatchStatusClass(batch.status)}">${escapeHtml(batch.status)}</span></p>
        </div>
        <div class="dl-actions-inline">
          <button class="dl-btn" id="btnBackCanbuBatches" type="button">返回批次列表</button>
          <button class="dl-btn" id="btnRecalculateCanbu" type="button">重新核算</button>
          <button class="btn-primary" id="btnExportCanbu" type="button" ${canbuResults.length ? '' : 'disabled'}>导出结果</button>
        </div>
      </div>
      ${renderCanbuStepper(step, batch)}
    </section>
    ${showAside ? `
      <div class="dl-grid dl-grid-workbench">
        <div class="dl-stack" id="canbuStepContent"></div>
        <aside class="dl-aside">
          <button class="dl-aside-toggle" id="btnToggleAside" type="button" aria-expanded="true" aria-label="收起异常队列">
            <span class="dl-aside-toggle-icon">›</span>
            <span class="dl-aside-toggle-text">收起异常</span>
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

function renderCanbuStepper(activeStep, batch) {
  const completed = new Set();
  if (batch.status !== '草稿') completed.add('upload');
  if (['已核算', '可导出', '已导出'].includes(batch.status)) completed.add('fields');
  if (['已核算', '可导出', '已导出'].includes(batch.status)) completed.add('results');
  if (batch.status === '已导出') completed.add('exported');
  return `
    <div class="dl-stepper">
      ${CANBU_STEPS.map((stepItem) => {
        const active = stepItem.key === activeStep;
        const done = completed.has(stepItem.key);
        const index = CANBU_STEPS.indexOf(stepItem) + 1;
        const status = done ? '已完成' : active ? '进行中' : '未开始';
        const icon = active
          ? `<span class="dl-stepper-index active-pin">${renderStepperPin(index)}</span>`
          : `<span class="dl-stepper-index">${done ? '✓' : index}</span>`;
        return `
          <button class="dl-stepper-item ${active ? 'active' : ''} ${done ? 'done' : ''}" data-canbu-step="${stepItem.key}" type="button">
            ${icon}
            <span class="dl-stepper-label">${stepItem.label}</span>
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

function renderCanbuStepContent(step, results = []) {
  const root = document.querySelector('#canbuStepContent');
  if (!root) return;
  if (step === 'upload') {
    root.innerHTML = `
      <section class="dl-panel">
        <div class="dl-panel-head">
          <div>
            <h2 class="dl-panel-title">数据上传</h2>
            <p class="dl-panel-sub">餐补核算需要日考勤和月考勤数据。第一版沿用当前单 Excel 上传入口，文件内可包含多张工作表。</p>
          </div>
        </div>
        <div class="dl-upload-list">
          <div class="dl-upload-row">
            <strong>日考勤数据</strong>
            <span>东莞餐补逐日计算</span>
            <span class="dl-badge warn">随 Excel 上传</span>
          </div>
          <div class="dl-upload-row">
            <strong>月考勤数据</strong>
            <span>嘉善/义乌汇总计算、人员字段补充</span>
            <span class="dl-badge warn">随 Excel 上传</span>
          </div>
        </div>
        <div class="upload-zone" id="fileUploadZone">
          <input id="payrollFile" type="file" accept=".xlsx,.xlsm,.xls" />
          <p class="upload-title">餐补数据 Excel</p>
          <p class="upload-sub" id="payrollFileName">点击选择 · 支持 .xlsx / .xlsm / .xls</p>
        </div>
        <div class="drawer-footer compact">
          <p id="uploadStatus" class="inline-status">选择文件后开始字段检查。</p>
          <button id="btnSubmitCanbuBatch" class="btn-primary-lg" type="button" disabled>开始字段检查</button>
        </div>
      </section>
    `;
    refreshUploadRefs();
    bindCanbuUploadEvents();
    renderExceptionQueue([]);
    return;
  }

  if (step === 'fields') {
    root.innerHTML = renderCanbuFieldCheck();
    renderExceptionQueue([]);
    return;
  }

  root.innerHTML = '<section class="dl-panel"><div id="resultsTable" class="dl-table-wrap"></div></section>';
  el.resultsTable = document.querySelector('#resultsTable');
  renderCanbuResults(results);
}

function refreshUploadRefs() {
  el.payrollFile = document.querySelector('#payrollFile');
  el.payrollFileName = document.querySelector('#payrollFileName');
  el.fileUploadZone = document.querySelector('#fileUploadZone');
  el.uploadStatus = document.querySelector('#uploadStatus');
}

function bindCanbuUploadEvents() {
  const submit = document.querySelector('#btnSubmitCanbuBatch');
  el.payrollFile?.addEventListener('change', () => {
    const file = el.payrollFile.files[0];
    state.payrollFile = file || null;
    el.payrollFileName.textContent = file ? file.name : '点击选择 · 支持 .xlsx / .xlsm / .xls';
    if (file) el.fileUploadZone.classList.add('has-file');
    if (submit) submit.disabled = !file;
    setText(el.uploadStatus, file ? `已选择: ${file.name}` : '请选择文件');
  });
  submit?.addEventListener('click', submitCanbuBatch);
}

function renderCanbuFieldCheck() {
  return `
    <section class="dl-panel">
      <div class="dl-panel-head">
        <div>
          <h2 class="dl-panel-title">字段检查</h2>
          <p class="dl-panel-sub">字段检查按餐补规则分组展示，当前版本以后端解析结果为准。</p>
        </div>
      </div>
      <div class="dl-field-groups">
        ${renderFieldGroup('基础员工字段', ['工号', '姓名', '一级部门', '二级部门', '岗位名称', '工作地区', '在职状态'])}
        ${renderFieldGroup('东莞日考勤字段', ['日期', '工作状态', '正班时数', '刷卡加班', '异常标记', '异常原因'])}
        ${renderFieldGroup('嘉善/义乌月考勤字段', ['排班天数', '实际在职工作日天数', '事假时数', '病假时数', '旷工天数'])}
      </div>
      <div class="drawer-footer compact">
        <p class="inline-status">字段检查通过后进入餐补核算。</p>
        <button class="btn-primary-lg" type="button" id="btnGoCanbuResults">查看餐补核算</button>
      </div>
    </section>
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
          const rowIndex = results.indexOf(row);
          return `
            <tr>
              <td class="sticky-col id-col dl-strong">${escapeHtml(row.employee_id || '')}</td>
              <td class="sticky-col name-col">${escapeHtml(row.employee_name || '')}</td>
              <td>${escapeHtml(getCanbuRowRegion(row))}</td>
              <td class="wrap-cell" title="${escapeHtml(row.department || '—')}">${escapeHtml(row.department || '—')}</td>
              <td class="wrap-cell" title="${escapeHtml(row.position || inputs['岗位名称'] || '—')}">${escapeHtml(row.position || inputs['岗位名称'] || '—')}</td>
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
  document.querySelector('#btnRecalculateCanbu')?.addEventListener('click', () => {
    renderCanbuWorkbench('upload');
  });
  document.querySelector('#btnExportCanbu')?.addEventListener('click', () => exportResults(true));
  document.querySelector('#btnGoCanbuResults')?.addEventListener('click', () => renderCanbuWorkbench('results'));
  document.querySelectorAll('[data-canbu-step]').forEach((button) => {
    button.addEventListener('click', () => {
      const nextStep = button.dataset.canbuStep;
      if (nextStep === 'exported') return;
      renderCanbuWorkbench(nextStep === 'results' ? 'results' : nextStep);
    });
  });
  el.btnToggleAside?.addEventListener('click', toggleAside);
}

function getBatchStatusClass(status) {
  if (status === '已导出' || status === '可导出' || status === '已核算') return 'ok';
  if (status === '字段异常' || status === '失败') return 'block';
  return 'warn';
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

  if (options.includeResults) {
    const results = state.currentResults || [];
    const summary = targetRun.summary || {};
    patch.employeeCount = results.length;
    patch.exceptionCount = countCanbuWarnings(results);
    patch.payableTotal = Number(summary.total_canbu ?? sumField(results, 'canbu'));
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

  const hrbpText = el.hrbpList.value.trim();
  if (hrbpText) {
    try {
      const arr = JSON.parse(hrbpText);
      state.hrbpList = arr;
      el.confirmHrbp.textContent = `已配置 ${arr.length} 个工号（含预置名单）`;
    } catch {
      state.hrbpList = null;
      el.confirmHrbp.textContent = '格式错误（揽收工龄奖将按未配置处理）';
    }
  } else {
    state.hrbpList = null;
    el.confirmHrbp.textContent = '未配置';
  }
}

async function submitTask() {
  if (!state.payrollFile) return toast('请先上传文件。');
  if (!state.selectedEngines.length) return toast('请至少选择一个引擎。');

  setText(el.submitStatus, '正在提交计算任务...');
  el.btnSubmitTask.disabled = true;
  resetReportLink();

  try {
    const form = new FormData();
    form.append('file', state.payrollFile);
    form.append('engines', state.selectedEngines.join(','));
    form.append('attendance_month', el.attendanceMonth.value);
    form.append('password', el.filePassword.value || '');
    if (state.hrbpList) {
      form.append('hrbp_list', JSON.stringify(state.hrbpList));
    }

    const data = await requestJson('/api/domestic-labor/runs', {
      method: 'POST',
      body: form,
    });

    state.currentRun = { id: data.run_id, status: data.status };
    syncCanbuBatchFromRun(state.currentRun);
    setText(el.submitStatus, `任务已提交: ${data.run_id}`);

    // Update run badge
    el.chromeRunBadge.hidden = false;
    el.chromeRunLabel.textContent = `任务 #${data.run_id.slice(0, 8)}`;

    // Close drawer and start polling
    setTimeout(() => {
      document.querySelector('.btn-close-drawer').click();
      showTaskSection();
      startPolling();
    }, 600);

    toast('计算任务已提交，正在后台处理...');
  } catch (error) {
    setText(el.submitStatus, error.message, true);
    toast(error.message);
  } finally {
    el.btnSubmitTask.disabled = false;
  }
}

async function submitCanbuBatch() {
  if (!state.payrollFile) return toast('请先上传餐补数据文件。');
  const batch = getActiveCanbuBatch();
  if (!batch) return toast('暂无餐补批次。');

  const submit = document.querySelector('#btnSubmitCanbuBatch');
  if (submit) submit.disabled = true;
  setText(el.uploadStatus, '正在提交餐补核算...');
  resetReportLink();

  try {
    const form = new FormData();
    form.append('file', state.payrollFile);
    form.append('engines', 'canbu');
    form.append('attendance_month', String(batch.month || '').replace('-', ''));
    form.append('password', el.filePassword?.value || '');

    const data = await requestJson('/api/domestic-labor/runs', {
      method: 'POST',
      body: form,
    });

    state.currentRun = { id: data.run_id, status: data.status };
    syncCanbuBatchFromRun(state.currentRun, { batchId: batch.id, status: '已上传' });
    startPolling();
    renderCanbuWorkbench('fields');
    toast('餐补批次已提交，正在后台处理。');
  } catch (error) {
    updateCanbuBatch({ status: '失败' }, { batchId: batch.id });
    setText(el.uploadStatus, error.message, true);
    toast(error.message);
  } finally {
    if (submit) submit.disabled = false;
  }
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
    '已完成': { label: '已完成', tone: 'ok', text: '计算完成，可进入导出归档。' },
    '失败': { label: '失败', tone: 'block', text: '计算失败，请检查文件后重试。' },
  };
  const s = statusLabels[status] || statusLabels.submitted;
  el.taskStatusCard.innerHTML = `
    <div class="dl-empty">
      <div>
        <span class="dl-badge ${s.tone}">${s.label}</span>
        <h2 style="margin:12px 0 0;">${s.text}</h2>
        <p>本工作台按「数据上传 → 字段检查 → 餐补核算 → 导出归档」单一路径处理。</p>
      </div>
      <div class="dl-empty-map">
        <div class="dl-empty-map-row"><strong>01</strong><span>数据上传</span></div>
        <div class="dl-empty-map-row"><strong>02</strong><span>字段检查</span></div>
        <div class="dl-empty-map-row"><strong>03</strong><span>餐补核算</span></div>
        <div class="dl-empty-map-row"><strong>04</strong><span>导出归档（同页）</span></div>
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
  pollStatus();
  state.pollTimer = window.setInterval(pollStatus, 3000);
}

function stopPolling() {
  if (state.pollTimer) {
    window.clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
}

async function pollStatus() {
  if (!state.currentRun) return;
  state.pollRetryCount++;

  if (state.pollRetryCount > state.pollMaxRetries) {
    stopPolling();
    renderTaskStatusCard('失败');
    setText(el.taskStatusSub, '计算超时（10分钟），请刷新重试。', true);
    toast('计算超时。');
    return;
  }

  try {
    const metadata = await requestJson(`/api/domestic-labor/runs/${state.currentRun.id}`);
    state.currentRun = metadata;

    const status = metadata.status || '计算中';
    syncCanbuBatchFromRun(metadata);
    renderTaskStatusCard(status);

    if (status === '已完成') {
      stopPolling();
      renderResults(metadata);
      if (el.btnExport) el.btnExport.hidden = false;
      toast('薪酬计算完成！');
    } else if (status === '失败') {
      stopPolling();
      const errMsg = metadata.error || '计算失败，请检查文件后重试。';
      setText(el.taskStatusSub, errMsg, true);
      toast(errMsg);
    }
  } catch (error) {
    // Ignore transient errors during polling
  }
}

async function refreshStatus() {
  if (!state.currentRun) return toast('暂无任务。');
  try {
    const metadata = await requestJson(`/api/domestic-labor/runs/${state.currentRun.id}`);
    state.currentRun = metadata;
    const status = metadata.status || '计算中';
    syncCanbuBatchFromRun(metadata);
    renderTaskStatusCard(status);
    if (status === '已完成') {
      renderResults(metadata);
      if (el.btnExport) el.btnExport.hidden = false;
    }
    toast('状态已刷新。');
  } catch (error) {
    toast(error.message);
  }
}

function renderResults(metadata) {
  if (!el.taskStatusCard) return;
  const results = metadata.results || [];
  const summary = metadata.summary || {};
  state.currentResults = results;
  if (results.length) enableReportExportLink();
  else resetReportLink();

  const activeBatch = getActiveCanbuBatch?.();
  if (activeBatch && state.view === 'canbuWorkbench') {
    const canbuWarnings = countCanbuWarnings(results);
    updateActiveCanbuBatch({
      status: canbuWarnings ? '已核算' : '可导出',
      employeeCount: summary.total_employees || summary.totalEmployees || results.length || 0,
      payableTotal: summary.total_canbu ?? sumField(results, 'canbu'),
      exceptionCount: canbuWarnings,
      runId: metadata.run_id || state.currentRun?.id || activeBatch.runId,
    });
    syncCanbuBatchFromRun(metadata, {
      includeResults: true,
      status: canbuWarnings ? '已核算' : '可导出',
    });
    renderCanbuWorkbench('results');
    return;
  }

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
          <p>结果表将包含员工工号、部门、岗位、四项科目金额、计算结果、异常等级、复核状态与导出就绪状态。</p>
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
  const rows = results.filter(hasReviewIssue);
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
    const level = getWarningLevel(row);
    const firstException = getEffectiveExceptions(row)[0];
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
  el.explainTitle.textContent = `${row.employee_id || ''} ${row.employee_name || ''}`;
  const subjectCards = ['quanqinjiang', 'canbu', 'waisu_butie', 'gonglingjiang'].map(key => {
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
  const rowExceptions = getEffectiveExceptions(row);
  const warningText = getEffectiveWarningText(row);
  const needsReview = hasReviewIssue(row);
  el.explainBody.innerHTML = `
    <div class="dl-kv-grid">
      <div class="dl-kv"><span>部门</span><strong>${escapeHtml(row.department || '—')}</strong></div>
      <div class="dl-kv"><span>应发合计</span><strong>${formatMoney(row.total)}</strong></div>
      <div class="dl-kv"><span>复核状态</span><strong>${needsReview ? '待复核' : '自动通过'}</strong></div>
    </div>
    ${subjectCards}
    <div class="dl-rule-card">
      <h3>异常与处理</h3>
      <dl>
        <dt>异常等级</dt><dd>${getWarningLevel(row).label}</dd>
        <dt>异常说明</dt><dd>${formatExceptions(rowExceptions) || escapeHtml(warningText || '暂无异常')}</dd>
        <dt>建议动作</dt><dd>${rowExceptions[0]?.suggested_action ? escapeHtml(rowExceptions[0].suggested_action) : (warningText ? '确认数据、补充规则参数或登记人工调整原因。' : '无需人工处理，结果可直接进入导出归档。')}</dd>
      </dl>
    </div>
  `;
  el.explainDrawer.classList.add('open');
}

function closeExplainDrawer() {
  el.explainDrawer?.classList.remove('open');
}

function buildRuleExplanation(key, row) {
  if (key === 'quanqinjiang') return '按考勤月份、入离职、旷工、迟到早退、签卡和扣款条件判断。';
  if (key === 'canbu') return '按餐补资格、日有效出勤和月度封顶金额计算。';
  if (key === 'waisu_butie') return '按外宿资格、当月在职天数、住宿扣除和缺勤阈值折算。';
  if (key === 'gonglingjiang') return '按区域、部门、岗位、工龄、排班天数、缺勤与 HRBP 发放名单计算。';
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

function countWarnings(results) {
  return results.filter(hasReviewIssue).length;
}

function countCanbuWarnings(results) {
  return results.filter(hasCanbuReviewIssue).length;
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
  return /不在本月HRBP发放名单|不在.*HRBP.*发放名单|揽收工龄奖不发放/.test(text);
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
  setText(el.taskStatusSub, '正在生成 Excel...');
  try {
    const data = await requestJson(`/api/domestic-labor/runs/${state.currentRun.id}/export`);
    const downloadUrl = `/api/domestic-labor/runs/${state.currentRun.id}/download/${encodeURIComponent(data.file_name)}`;
    el.reportLink.href = downloadUrl;
    el.reportLink.dataset.readyToExport = 'false';
    el.reportLink.classList.remove('disabled');
    el.reportLink.removeAttribute('aria-disabled');
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
  } catch (error) {
    toast(error.message);
    setText(el.taskStatusSub, error.message, true);
  }
}

// ── Utility functions ──
async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || '请求失败。');
  return data;
}

function setText(element, value, error = false) {
  if (!element) return;
  element.textContent = value;
  element.classList.toggle('error-text', error);
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
