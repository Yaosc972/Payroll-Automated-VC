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
  btnCloseUploadModal: document.getElementById('btnCloseUploadModal'),
  btnCancelUpload: document.getElementById('btnCancelUpload'),
  btnConfirmUpload: document.getElementById('btnConfirmUpload'),

  // Calc Chain Modal
  calcChainModal: document.getElementById('calcChainModal'),
  calcChainContent: document.getElementById('calcChainContent'),
  btnCloseCalcChainModal: document.getElementById('btnCloseCalcChainModal'),
  btnCloseCalcChain: document.getElementById('btnCloseCalcChain'),
};

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

async function enterActivity(activityId) {
  try {
    const activity = await apiJson(`${API_BASE}/runs/${activityId}`);

    state.currentActivity = activity;
    state.diagnosticsData = activity.diagnostics || null;

    // Navigate to appropriate page based on step
    const page = activity.current_step >= 3 ? 'results' :
                 activity.current_step >= 2 ? 'performance' :
                 activity.current_step >= 1 ? 'salary' : 'attendance';

    navigateTo(page);

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
  const calcMonth = prompt('请输入核算月份（格式：2026-04）：');
  if (!calcMonth) return;

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
  if (!confirm('确定删除此活动？')) return;

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

function openUploadModal(type) {
  uploadType = type;
  uploadFile = null;
  el.uploadFileInput.value = '';

  const titles = {
    attendance: '上传考勤日报表',
    salary: '上传薪资档案',
    performance: '上传绩效报表',
    adjustments: '上传调薪/转正拆分表',
  };

  el.uploadModalTitle.textContent = titles[type];
  el.uploadZoneTitle.textContent = '选择文件';
  el.uploadZoneSub.textContent = type === 'attendance' && state.baseRoster?.has_roster
    ? `点击选择或拖拽文件到此处 · 将自动引用基础花名册 ${state.baseRoster.filename || ''}`
    : '点击选择或拖拽文件到此处 · 支持 .xlsx / .xls';
  el.btnConfirmUpload.disabled = true;

  el.uploadModal.classList.add('active');
}

function closeUploadModal() {
  el.uploadModal.classList.remove('active');
  uploadType = '';
  uploadFile = null;
}

function downloadGeneratedResult(resultFile) {
  if (!resultFile?.download_url) return;
  const link = document.createElement('a');
  link.href = resultFile.download_url;
  link.download = resultFile.filename || '';
  link.click();
}

el.btnCloseUploadModal.addEventListener('click', closeUploadModal);
el.btnCancelUpload.addEventListener('click', closeUploadModal);

el.uploadZone.addEventListener('click', () => {
  el.uploadFileInput.click();
});

el.uploadFileInput.addEventListener('change', (e) => {
  const file = e.target.files[0];
  if (file) {
    uploadFile = file;
    el.uploadZoneTitle.textContent = file.name;
    el.uploadZoneSub.textContent = '已选择文件，点击确认上传';
    el.btnConfirmUpload.disabled = false;
  }
});

el.btnConfirmUpload.addEventListener('click', async () => {
  if (!uploadFile || !state.currentActivity) return;

  el.btnConfirmUpload.disabled = true;
  el.btnConfirmUpload.textContent = '上传中...';

  try {
    const formData = new FormData();
    formData.append('file', uploadFile);

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
      showNotification(data.result_file ? `上传成功，已生成 ${data.result_file.filename}` : '上传成功', 'success');
      closeUploadModal();
      downloadGeneratedResult(data.result_file);

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

      // Refresh activity data
      enterActivity(state.currentActivity.run_id);
    } else {
      showNotification('上传失败: ' + (data.detail || '未知错误'), 'error');
    }
  } catch (error) {
    showNotification('上传失败: ' + error.message, 'error');
  } finally {
    el.btnConfirmUpload.disabled = false;
    el.btnConfirmUpload.textContent = '确认上传';
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
    <!-- 筛选条件 -->
    <div style="display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap;">
      <input type="text" id="filterAttendanceId" placeholder="工号" style="padding: 8px 12px; border: 1px solid #E2E8F0; border-radius: 6px; width: 120px;">
      <input type="text" id="filterAttendanceName" placeholder="姓名" style="padding: 8px 12px; border: 1px solid #E2E8F0; border-radius: 6px; width: 120px;">
      <input type="text" id="filterAttendanceArea" placeholder="划分区域" style="padding: 8px 12px; border: 1px solid #E2E8F0; border-radius: 6px; width: 150px;">
      <input type="text" id="filterAttendanceDept" placeholder="部门" style="padding: 8px 12px; border: 1px solid #E2E8F0; border-radius: 6px; width: 200px;">
      <button class="btn btn-secondary btn-sm" onclick="filterAttendanceData()">筛选</button>
      <button class="btn btn-secondary btn-sm" onclick="resetAttendanceFilter()">重置</button>
    </div>

    <div class="data-table-container">
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
              <td>${emp.total_base_hours.toFixed(2)}h</td>
              <td>${emp.total_ot15.toFixed(2)}h</td>
              <td>${emp.total_ot20.toFixed(2)}h</td>
              <td>${(emp.day_shift['病假'] + emp.night_shift['病假']).toFixed(2)}h</td>
              <td>${(emp.day_shift['年假'] + emp.night_shift['年假']).toFixed(2)}h</td>
              <td>${(emp.day_shift['节假日'] + emp.night_shift['节假日']).toFixed(2)}h</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
    <div class="summary-stats">
      <div class="summary-stat">
        <span class="summary-stat-label">员工总数</span>
        <span class="summary-stat-value">${summary.total_employees}</span>
      </div>
      <div class="summary-stat">
        <span class="summary-stat-label">白班人数</span>
        <span class="summary-stat-value">${summary.day_shift_count}</span>
      </div>
      <div class="summary-stat">
        <span class="summary-stat-label">夜班人数</span>
        <span class="summary-stat-value">${summary.night_shift_count}</span>
      </div>
      <div class="summary-stat">
        <span class="summary-stat-label">花名册匹配</span>
        <span class="summary-stat-value">${summary.roster_matched || 0}/${summary.total_employees}</span>
      </div>
      <div class="summary-stat">
        <span class="summary-stat-label">总工时</span>
        <span class="summary-stat-value">${summary.total_base_hours.toFixed(2)}h</span>
      </div>
      <div class="summary-stat">
        <span class="summary-stat-label">总OT1.5</span>
        <span class="summary-stat-value">${summary.total_ot15.toFixed(2)}h</span>
      </div>
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
    <!-- 筛选条件 -->
    <div style="display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap;">
      <input type="text" id="filterSalaryId" placeholder="工号" style="padding: 8px 12px; border: 1px solid #E2E8F0; border-radius: 6px; width: 120px;">
      <input type="text" id="filterSalaryName" placeholder="姓名" style="padding: 8px 12px; border: 1px solid #E2E8F0; border-radius: 6px; width: 120px;">
      <input type="text" id="filterSalaryArea" placeholder="划分区域" style="padding: 8px 12px; border: 1px solid #E2E8F0; border-radius: 6px; width: 150px;">
      <input type="text" id="filterSalaryDept" placeholder="部门" style="padding: 8px 12px; border: 1px solid #E2E8F0; border-radius: 6px; width: 200px;">
      <button class="btn btn-secondary btn-sm" onclick="filterSalaryData()">筛选</button>
      <button class="btn btn-secondary btn-sm" onclick="resetSalaryFilter()">重置</button>
    </div>

    <div class="data-table-container">
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
              <td>$${emp.hourly_rate.toFixed(2)}</td>
              <td>${(emp.ratio * 100).toFixed(1)}%</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
    <div class="summary-stats">
      <div class="summary-stat">
        <span class="summary-stat-label">档案人数</span>
        <span class="summary-stat-value">${summary.total_employees}</span>
      </div>
      <div class="summary-stat">
        <span class="summary-stat-label">有效时薪</span>
        <span class="summary-stat-value">${summary.valid_hourly_count ?? summary.total_employees}</span>
      </div>
      <div class="summary-stat">
        <span class="summary-stat-label">0时薪</span>
        <span class="summary-stat-value">${summary.zero_hourly_count ?? 0}</span>
      </div>
      <div class="summary-stat">
        <span class="summary-stat-label">有效平均时薪</span>
        <span class="summary-stat-value">$${summary.avg_hourly_rate.toFixed(2)}</span>
      </div>
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

  el.performanceContent.innerHTML = `
    ${renderDiagnosticsPanel()}
    ${adjustmentSummary ? `
      <div class="summary-stats" style="margin-bottom: 16px;">
        <div class="summary-stat">
          <span class="summary-stat-label">拆分员工</span>
          <span class="summary-stat-value">${adjustmentSummary.total_employees}</span>
        </div>
        <div class="summary-stat">
          <span class="summary-stat-label">拆分段数</span>
          <span class="summary-stat-value">${adjustmentSummary.total_segments}</span>
        </div>
        <div class="summary-stat">
          <span class="summary-stat-label">有效拆分基数</span>
          <span class="summary-stat-value">$${Number(adjustmentSummary.active_performance_base || 0).toFixed(2)}</span>
        </div>
      </div>
    ` : ''}
    <!-- 筛选条件 -->
    <div style="display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap;">
      <input type="text" id="filterPerfId" placeholder="工号" style="padding: 8px 12px; border: 1px solid #E2E8F0; border-radius: 6px; width: 120px;">
      <input type="text" id="filterPerfName" placeholder="姓名" style="padding: 8px 12px; border: 1px solid #E2E8F0; border-radius: 6px; width: 120px;">
      <input type="text" id="filterPerfArea" placeholder="划分区域" style="padding: 8px 12px; border: 1px solid #E2E8F0; border-radius: 6px; width: 150px;">
      <input type="text" id="filterPerfDept" placeholder="部门" style="padding: 8px 12px; border: 1px solid #E2E8F0; border-radius: 6px; width: 200px;">
      <button class="btn btn-secondary btn-sm" onclick="filterPerformanceData()">筛选</button>
      <button class="btn btn-secondary btn-sm" onclick="resetPerformanceFilter()">重置</button>
    </div>

    <div class="data-table-container">
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
              <td>${emp.score !== null ? emp.score.toFixed(2) : '-'}</td>
              <td>${escapeHtml(emp.level || '-')}</td>
              <td>${emp.coefficient !== null ? emp.coefficient.toFixed(2) : '-'}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
    <div class="summary-stats">
      <div class="summary-stat">
        <span class="summary-stat-label">员工总数</span>
        <span class="summary-stat-value">${summary.total_employees}</span>
      </div>
      <div class="summary-stat">
        <span class="summary-stat-label">平均得分</span>
        <span class="summary-stat-value">${summary.avg_score.toFixed(2)}</span>
      </div>
      ${Object.entries(summary.level_distribution || {}).map(([level, count]) => `
        <div class="summary-stat">
          <span class="summary-stat-label">${level}</span>
          <span class="summary-stat-value">${count}人</span>
        </div>
      `).join('')}
    </div>
  `;
}

// ═══ Render Results Data ═══

function renderResultsData() {
  if (!state.resultsData || state.resultsData.length === 0) {
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
  const totalBonus = results.reduce((sum, r) => sum + r.performance_bonus, 0);
  const avgBonus = totalBonus / results.length;
  const exceptionCount = results.filter(r => (r.exceptions || []).length > 0).length;

  el.resultsContent.innerHTML = `
    ${renderDiagnosticsPanel()}
    <!-- 筛选条件 -->
    <div style="display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap;">
      <input type="text" id="filterResultsId" placeholder="工号" style="padding: 8px 12px; border: 1px solid #E2E8F0; border-radius: 6px; width: 120px;">
      <input type="text" id="filterResultsName" placeholder="姓名" style="padding: 8px 12px; border: 1px solid #E2E8F0; border-radius: 6px; width: 120px;">
      <input type="text" id="filterResultsArea" placeholder="划分区域" style="padding: 8px 12px; border: 1px solid #E2E8F0; border-radius: 6px; width: 150px;">
      <input type="text" id="filterResultsDept" placeholder="部门" style="padding: 8px 12px; border: 1px solid #E2E8F0; border-radius: 6px; width: 200px;">
      <button class="btn btn-secondary btn-sm" onclick="filterResultsData()">筛选</button>
      <button class="btn btn-secondary btn-sm" onclick="resetResultsFilter()">重置</button>
    </div>

    <div class="data-table-container">
      <table class="data-table" id="resultsTable">
        <thead>
          <tr>
            <th>工号</th>
            <th>姓名</th>
            <th>划分区域</th>
            <th>部门全称</th>
            <th>岗位类型</th>
            <th>时薪</th>
            <th>绩效基数</th>
            <th>绩效比例</th>
            <th>绩效系数</th>
            <th>绩效奖金</th>
            <th>异常</th>
            <th>计算过程</th>
          </tr>
        </thead>
        <tbody>
          ${results.map(r => `
            <tr data-id="${escapeHtml(r.employee_id)}"
                data-name="${escapeHtml(r.name || '')}"
                data-area="${escapeHtml(r.area || '')}"
                data-dept="${escapeHtml(r.department || '')}">
              <td>${escapeHtml(r.employee_id)}</td>
              <td>${escapeHtml(r.name || '-')}</td>
              <td>${escapeHtml(r.area || '-')}</td>
              <td>${escapeHtml(r.department || '-')}</td>
              <td>${formatJobType(r.job_type)}</td>
              <td>$${r.hourly_rate.toFixed(2)}</td>
              <td>$${r.performance_base.toFixed(2)}</td>
              <td>${(r.performance_ratio * 100).toFixed(1)}%</td>
              <td>${r.performance_coefficient.toFixed(2)}</td>
              <td><strong>$${r.performance_bonus.toFixed(2)}</strong></td>
              <td>${(r.exceptions || []).length ? `<span class="status-badge danger">${escapeHtml((r.exceptions || []).length)}项</span>` : '-'}</td>
              <td><button class="btn btn-secondary btn-sm" onclick="showCalcChain('${escapeHtml(r.employee_id)}')">查看</button></td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
    <div class="summary-stats">
      <div class="summary-stat">
        <span class="summary-stat-label">员工总数</span>
        <span class="summary-stat-value">${results.length}</span>
      </div>
      <div class="summary-stat">
        <span class="summary-stat-label">奖金总额</span>
        <span class="summary-stat-value">$${totalBonus.toLocaleString()}</span>
      </div>
      <div class="summary-stat">
        <span class="summary-stat-label">平均奖金</span>
        <span class="summary-stat-value">$${avgBonus.toFixed(2)}</span>
      </div>
    </div>
  `;

  // Update KPIs
  el.kpiResultEmployees.textContent = results.length;
  el.kpiResultBonus.textContent = '$' + totalBonus.toLocaleString();
  el.kpiResultAvg.textContent = '$' + avgBonus.toFixed(2);
  el.kpiResultErrors.textContent = exceptionCount;
}

// ═══ Calculate ═══

async function executeCalculate() {
  if (!state.currentActivity) return;

  const summary = state.diagnosticsData?.summary;
  if (summary?.error_count > 0) {
    const confirmed = confirm(`当前仍有 ${summary.error_count} 个严重匹配问题，可能影响核算结果。是否继续核算？`);
    if (!confirmed) return;
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

function showNotification(message, type = 'info') {
  const notification = document.createElement('div');
  notification.className = `notification notification-${type}`;
  notification.textContent = message;
  notification.style.cssText = `
    position: fixed;
    top: 20px;
    right: 20px;
    padding: 12px 24px;
    background: ${type === 'success' ? '#10B981' : type === 'error' ? '#EF4444' : '#3B82F6'};
    color: white;
    border-radius: 8px;
    z-index: 1000;
    animation: slideIn 0.3s ease;
  `;
  document.body.appendChild(notification);

  setTimeout(() => {
    notification.remove();
  }, 3000);
}

// ═══ Init ═══

document.addEventListener('DOMContentLoaded', () => {
  loadBaseRoster();
  loadActivities();
});
