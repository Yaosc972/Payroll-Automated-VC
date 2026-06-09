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
  pollTimer: null,
  pollRetryCount: 0,
  pollMaxRetries: 200, // 200 × 3s = 10 min
};

const ENGINE_META = {
  quanqinjiang: {
    name: '全勤奖',
    desc: '100元/人/月，按出勤天数、迟到、旷工等条件计算',
    icon: '✓',
    color: 'brand',
  },
  canbu: {
    name: '餐补',
    desc: '19元/天，封顶500元/月，按出勤天数计算',
    icon: '🍜',
    color: 'info',
  },
  waisu_butie: {
    name: '外宿补贴',
    desc: '150元/月，按出勤、请假等条件计算',
    icon: '🏠',
    color: 'warning',
  },
  gonglingjiang: {
    name: '工龄奖',
    desc: '按工龄阶梯计算，每年递增',
    icon: '🏆',
    color: 'violet',
  },
};

// ── Element references ──
const el = {
  // KPI
  kpiTotalVal: document.querySelector('#kpiTotalVal'),
  kpiProcessedVal: document.querySelector('#kpiProcessedVal'),
  kpiQuanqinVal: document.querySelector('#kpiQuanqinVal'),
  kpiCanbuVal: document.querySelector('#kpiCanbuVal'),
  kpiWaisuVal: document.querySelector('#kpiWaisuVal'),
  kpiGonglingVal: document.querySelector('#kpiGonglingVal'),

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
  reportLink: document.querySelector('#reportLink'),
  toast: document.querySelector('#payrollToast'),
};

// ── Initialize ──
init();

function init() {
  loadEngineCards();
  loadTemplateLinks();
  bindEvents();
  setDefaultMonth();
}

function setDefaultMonth() {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, '0');
  el.attendanceMonth.value = `${y}-${m}`;
}

function loadEngineCards() {
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
  el.engineCardGrid.addEventListener('click', (e) => {
    const card = e.target.closest('.engine-card');
    if (!card) return;
    card.classList.toggle('selected');
    updateSelectedEngines();
  });

  // Month change
  el.attendanceMonth.addEventListener('change', updateStep1State);

  // Step navigation
  el.btnToStep2.addEventListener('click', () => goToStep(2));
  el.btnToStep3.addEventListener('click', () => goToStep(3));
  el.btnToStep4.addEventListener('click', () => goToStep(4));

  // File upload
  el.payrollFile.addEventListener('change', () => {
    const file = el.payrollFile.files[0];
    state.payrollFile = file || null;
    el.payrollFileName.textContent = file ? file.name : '点击选择 · 支持 .xlsx / .xlsm / .xls';
    if (file) el.fileUploadZone.classList.add('has-file');
    updateStep2State();
  });

  // Submit
  el.btnSubmitTask.addEventListener('click', submitTask);
  el.btnRefreshStatus.addEventListener('click', refreshStatus);
  el.btnExport.addEventListener('click', exportResults);
}

function updateSelectedEngines() {
  state.selectedEngines = [];
  el.engineCardGrid.querySelectorAll('.engine-card.selected').forEach(card => {
    state.selectedEngines.push(card.dataset.engine);
  });
  updateStep1State();
}

function updateStep1State() {
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
      el.confirmHrbp.textContent = `${arr.length} 人`;
    } catch {
      state.hrbpList = null;
      el.confirmHrbp.textContent = '格式错误（将计算全部员工）';
    }
  } else {
    state.hrbpList = null;
    el.confirmHrbp.textContent = '未配置（计算全部员工）';
  }
}

async function submitTask() {
  if (!state.payrollFile) return toast('请先上传文件。');
  if (!state.selectedEngines.length) return toast('请至少选择一个引擎。');

  setText(el.submitStatus, '正在提交计算任务...');
  el.btnSubmitTask.disabled = true;

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

function showTaskSection() {
  el.workspaceEmpty.hidden = true;
  el.taskStatusSection.hidden = false;
  renderTaskStatusCard('submitted');
}

function renderTaskStatusCard(status) {
  const statusLabels = {
    submitted: { label: '已提交', class: 'status-pending', text: '任务已提交，等待计算...' },
    '计算中': { label: '计算中', class: 'status-running', text: '正在计算薪酬，请稍候...' },
    '已完成': { label: '已完成', class: 'status-success', text: '计算完成，可查看结果或导出。' },
    '失败': { label: '失败', class: 'status-error', text: '计算失败，请检查文件后重试。' },
  };
  const s = statusLabels[status] || statusLabels.submitted;
  el.taskStatusCard.innerHTML = `
    <div class="status-indicator ${s.class}">
      <span class="status-dot"></span>
      <span class="status-label">${s.label}</span>
    </div>
    <p class="status-text">${s.text}</p>
    ${status === '计算中' ? '<div class="progress-bar"><div class="progress-fill"></div></div>' : ''}
  `;
  el.taskStatusSub.textContent = s.text;
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
    renderTaskStatusCard(status);

    if (status === '已完成') {
      stopPolling();
      renderResults(metadata);
      el.btnExport.hidden = false;
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
    renderTaskStatusCard(status);
    if (status === '已完成') {
      renderResults(metadata);
      el.btnExport.hidden = false;
    }
    toast('状态已刷新。');
  } catch (error) {
    toast(error.message);
  }
}

function renderResults(metadata) {
  const results = metadata.results || [];
  const summary = metadata.summary || {};

  // Update KPI - 适配后端字段名
  el.kpiTotalVal.textContent = summary.total_employees || summary.totalEmployees || '—';
  el.kpiProcessedVal.textContent = results.length || '—';

  // Per-engine KPI - 适配后端汇总格式
  el.kpiQuanqinVal.textContent = formatMoney(summary.total_quanqinjiang ?? 0);
  el.kpiCanbuVal.textContent = formatMoney(summary.total_canbu ?? 0);
  el.kpiWaisuVal.textContent = formatMoney(summary.total_waisu_butie ?? 0);
  el.kpiGonglingVal.textContent = formatMoney(summary.total_gonglingjiang ?? 0);

  // Results table
  if (results.length > 0) {
    el.resultsSection.hidden = false;
    renderResultsTable(results);
  }

  // Engine summary - 适配后端汇总格式
  const engineSummary = {
    quanqinjiang: { count: results.filter(r => r.quanqinjiang > 0).length, totalAmount: summary.total_quanqinjiang || 0 },
    canbu: { count: results.filter(r => r.canbu > 0).length, totalAmount: summary.total_canbu || 0 },
    waisu_butie: { count: results.filter(r => r.waisu_butie > 0).length, totalAmount: summary.total_waisu_butie || 0 },
    gonglingjiang: { count: results.filter(r => r.gonglingjiang > 0).length, totalAmount: summary.total_gonglingjiang || 0 },
  };
  el.engineSummarySection.hidden = false;
  renderEngineSummary(engineSummary);
}

function renderResultsTable(results) {
  // 字段映射：后端英文字段 -> 中文列名
  const FIELD_MAP = {
    employee_id: '工号',
    employee_name: '姓名',
    department: '部门',
    quanqinjiang: '全勤奖',
    canbu: '餐补',
    waisu_butie: '外宿补贴',
    gonglingjiang: '工龄奖',
    total: '合计',
    warnings: '备注',
  };

  // 固定列顺序
  const columnOrder = ['employee_id', 'employee_name', 'quanqinjiang', 'canbu', 'waisu_butie', 'gonglingjiang', 'total', 'warnings'];
  const availableCols = columnOrder.filter(k => results[0]?.[k] !== undefined);

  const thead = `<thead><tr>${availableCols.map(k => `<th>${FIELD_MAP[k] || k}</th>`).join('')}</tr></thead>`;
  const visible = results.slice(0, 100);

  const tbody = visible.map(row => {
    return `<tr>${availableCols.map(k => {
      const val = row[k];
      const formatted = typeof val === 'number' ? formatMoney(val) : escapeHtml(String(val ?? ''));
      return `<td>${formatted}</td>`;
    }).join('')}</tr>`;
  }).join('');

  el.resultsTable.innerHTML = `
    <div class="recon-summary-bar">
      <span>共 <strong>${results.length}</strong> 条记录</span>
    </div>
    <table>${thead}<tbody>${tbody}</tbody></table>
    ${results.length > visible.length ? `<p class="table-note">仅展示前 ${visible.length} 条，完整明细请下载报告。</p>` : ''}
  `;
}

function renderEngineSummary(engineSummary) {
  const html = Object.entries(engineSummary).map(([key, info]) => {
    const meta = ENGINE_META[key] || { name: key, icon: '⚙', color: 'neutral' };
    return `
      <div class="engine-summary-card engine-${meta.color}">
        <div class="engine-summary-icon">${meta.icon}</div>
        <div class="engine-summary-body">
          <h3>${meta.name}</h3>
          <div class="engine-summary-stats">
            <span><strong>${info.count ?? 0}</strong> 人</span>
            <span><strong>${formatMoney(info.totalAmount ?? 0)}</strong> 元</span>
          </div>
        </div>
      </div>
    `;
  }).join('');
  el.engineSummaryGrid.innerHTML = html;
}

async function exportResults() {
  if (!state.currentRun) return toast('暂无任务。');
  setText(el.taskStatusSub, '正在生成 Excel...');
  try {
    const data = await requestJson(`/api/domestic-labor/runs/${state.currentRun.id}/export`);
    const downloadUrl = `/api/domestic-labor/runs/${state.currentRun.id}/download/${encodeURIComponent(data.file_name)}`;
    el.reportLink.href = downloadUrl;
    el.reportLink.classList.remove('disabled');
    el.reportLink.removeAttribute('aria-disabled');
    toast('Excel 已生成，点击下载。');
    setText(el.taskStatusSub, 'Excel 已生成。');
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
