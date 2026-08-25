(() => {
  'use strict';

  const API_ROOT = '/api/social-insurance';
  const SUBJECTS_ENDPOINT = '/api/social-insurance/subjects';
  const METADATA_ENDPOINT = '/api/social-insurance/metadata';
  const SYNC_ENDPOINT = '/api/social-insurance/runs/sync';
  const SYNC_ALL_ENDPOINT = '/api/social-insurance/runs/sync-all';
  const RUN_ENDPOINT_PREFIX = '/api/social-insurance/runs/';
  const WIDE_FIELDS = new Set(['通讯地址', '国家职业资格或职业技能等级', '户口所在地行政区划代码']);
  const STATUS_LABELS = { ready: '可报盘', needs_review: '待人工确认', excluded: '已排除' };
  const STATUS_TEXT = { draft: '审核中', confirmed: '人员已确认', generated: '报盘已生成' };
  const COVERAGE_STATUS_LABELS = {
    ready: '可办理', needs_review: '待确认', supplement: '补缴确认', scheduled: '跨月待办',
    completed: '已完成', excluded: '不办理', deferred: '暂不处理',
  };
  const BUSINESS_COLUMNS = [
    { label: '工号', value: (employee) => employee.source?.jobNumber, className: 'mono-cell job-number-cell' },
    { label: '身份证号码', value: (employee) => employee.maskedId, className: 'mono-cell' },
    { label: '合同主体', value: (employee) => employee.source?.subject || state.run?.subject, className: 'subject-cell' },
    { label: '社保医保', value: (employee) => employee.source?.socialMedicalStatus || coverageStatusSummary(employee.coverageTasks?.social, employee.coverageTasks?.medical), className: 'status-source-cell' },
    { label: '社保基数', value: (employee) => employee.report?.['社保缴交基数'], className: 'number-cell' },
    { label: '公积金基数', value: (employee) => employee.report?.['公积金缴交基数'], className: 'number-cell' },
    { label: '社保电脑号', value: (employee) => employee.report?.['电脑号'], className: 'mono-cell' },
    { label: '公积金号', value: (employee) => employee.report?.['公积金号'], className: 'mono-cell' },
    { label: '参保城市', value: (employee) => employee.source?.socialPlace || employee.source?.socialContributionPlace || employee.source?.place },
    { label: '模板缺失', type: 'missing' },
    { label: '校验结论', type: 'issue' },
  ];
  const SOURCE_COLUMNS = [
    ['工号', 'jobNumber', 'mono-cell job-number-cell'], ['身份证号码', 'maskedId', 'mono-cell'],
    ['合同主体', 'subject', 'subject-cell'], ['工作地点', 'place'], ['雇佣关系', 'employType'], ['性别', 'gender', 'compact-cell'],
    ['手机号码', 'mobile', 'mono-cell', 'phone'], ['入职日期', 'entryDate', 'date-cell'], ['离职日期', 'lastWorkDate', 'date-cell'],
    ['社保医保', 'socialMedicalStatus', 'status-source-cell'], ['公积金', 'housingStatus', 'status-source-cell'],
    ['社保缴交基数', 'socialContributionBase', 'number-cell'], ['公积金缴交基数', 'housingContributionBase', 'number-cell'],
    ['公积金个人比例', 'housingContributionRate', 'number-cell'], ['社保缴纳地', 'socialContributionPlace'],
    ['社保电脑号', 'socialComputer', 'mono-cell'], ['公积金号', 'housingFundAccount', 'mono-cell'],
    ['户口地址', 'householdAddress', 'address-field-cell'], ['户籍所在地', 'birthplace', 'address-field-cell'],
    ['户口类别', 'domicileType'], ['最高学历', 'education'], ['现居住地址', 'currentAddress', 'address-field-cell'],
    ['民族', 'nation', 'compact-cell'], ['在职状态', 'employeeStatus'], ['邮箱', 'email', 'email-cell', 'email'],
    ['员工考勤地点', 'employmentPlace'], ['是否虚拟员工', 'virtualEmployee'], ['变动说明', 'changeDescription', 'wide-cell'],
  ];

  const state = {
    run: null,
    filter: 'all',
    search: '',
    editingId: null,
    operation: null,
    subjectsReady: false,
    subjectLoading: false,
    fieldDefinitions: [],
    schemaDefinitions: [],
    view: 'business',
    templateRoute: '',
    editingRoute: '',
    preflight: null,
    preflightKey: '',
    preflightLoading: false,
    administrativeDivisions: [],
    administrativeDivisionChoices: [],
    administrativeDivisionSet: new Set(),
    supplementCandidate: null,
    batchIndex: new Map(),
  };
  const byId = (id) => document.getElementById(id);
  let comboboxSequence = 0;
  let subjectRequestSequence = 0;
  let subjectLoadTimer = null;
  let subjectCompletionTimer = null;
  let subjectAbortController = null;
  let supplementPoolStatusTimer = null;
  let runRequestSequence = 0;
  const datePickerState = {
    open: null,
    periodBaseMonth: null,
    confirmationBaseMonth: null,
    periodStartDraft: '',
    periodEndDraft: '',
    awaitingPeriodEnd: false,
  };
  const subjectPickerState = { open: false, activeIndex: -1 };

  async function api(path, options = {}) {
    const headers = { ...(options.headers || {}) };
    if (options.body && !(options.body instanceof FormData)) headers['Content-Type'] = 'application/json';
    const response = await fetch(path, { credentials: 'same-origin', cache: 'no-store', ...options, headers });
    if (response.status === 401) {
      window.location.href = `login.html?next=${encodeURIComponent(window.location.pathname)}`;
      throw new Error('请先登录 HRAS 全球薪酬核算工作台');
    }
    if (!response.ok) {
      let message = '操作失败，请稍后重试';
      try {
        const payload = await response.json();
        message = typeof payload.detail === 'string' ? payload.detail : (payload.detail?.message || message);
      } catch { /* response is not JSON */ }
      throw new Error(message);
    }
    return response.json();
  }

  function showToast(message, type = 'success') {
    const region = byId('toastRegion');
    const toast = document.createElement('div');
    toast.className = `toast-item ${type}`;
    toast.setAttribute('role', type === 'error' ? 'alert' : 'status');
    toast.append(
      textNode('span', 'toast-icon', type === 'error' ? '!' : '✓'),
      textNode('span', 'toast-message', message),
    );
    const close = textNode('button', 'toast-close', '×');
    close.type = 'button'; close.setAttribute('aria-label', '关闭通知');
    const remove = () => {
      toast.classList.remove('visible');
      window.setTimeout(() => toast.remove(), 180);
    };
    close.addEventListener('click', remove);
    toast.append(close);
    region.append(toast);
    while (region.children.length > 4) region.firstElementChild?.remove();
    window.requestAnimationFrame(() => toast.classList.add('visible'));
    window.setTimeout(remove, type === 'error' ? 5200 : 3600);
  }

  function setBusy(button, busy, label = '') {
    button.disabled = busy;
    button.classList.toggle('loading', busy);
    if (!button.dataset.originalLabel) button.dataset.originalLabel = button.innerHTML;
    if (busy && label) button.innerHTML = `<span class="button-spinner" aria-hidden="true"></span><span><b>${label}</b><small>请勿关闭页面</small></span>`;
    if (!busy && button.dataset.originalLabel) button.innerHTML = button.dataset.originalLabel;
  }

  function textNode(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    node.textContent = text;
    return node;
  }

  function parseISODate(value) {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value || '');
    if (!match) return null;
    const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
    return Number.isNaN(date.valueOf()) ? null : date;
  }

  function formatISODate(date) {
    if (!(date instanceof Date) || Number.isNaN(date.valueOf())) return '';
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  }

  function formatDisplayDate(value) {
    return value ? value.replaceAll('-', '/') : '';
  }

  function formatRunTimestamp(value) {
    const parsed = new Date(value || '');
    if (Number.isNaN(parsed.valueOf())) return String(value || '').replace('T', ' ').slice(0, 16);
    const parts = Object.fromEntries(new Intl.DateTimeFormat('zh-CN', {
      year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
      hourCycle: 'h23', timeZone: 'Asia/Shanghai',
    }).formatToParts(parsed).map((part) => [part.type, part.value]));
    return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}`;
  }

  function startOfMonth(date) {
    return new Date(date.getFullYear(), date.getMonth(), 1);
  }

  function addMonths(date, amount) {
    return new Date(date.getFullYear(), date.getMonth() + amount, 1);
  }

  function renderDatePickerValues() {
    const periodStart = byId('periodStart').value;
    const periodEnd = byId('periodEnd').value;
    byId('periodRangeValue').textContent = periodStart && periodEnd
      ? `${formatDisplayDate(periodStart)} → ${formatDisplayDate(periodEnd)}`
      : '选择开始和结束日期';
    byId('confirmationDateValue').textContent = formatDisplayDate(byId('confirmationDate').value) || '选择确认日期';
  }

  function renderPeriodDraftValue() {
    const start = datePickerState.periodStartDraft;
    const end = datePickerState.periodEndDraft;
    byId('periodRangeValue').textContent = start
      ? `${formatDisplayDate(start)} → ${end ? formatDisplayDate(end) : '选择结束日期'}`
      : '选择开始和结束日期';
    byId('periodCalendarHint').textContent = datePickerState.awaitingPeriodEnd
      ? '已选择开始日期，请选择结束日期'
      : '先选择开始日期，再选择结束日期';
  }

  function renderCalendarMonth(container, monthDate, mode) {
    const month = document.createElement('section');
    month.className = 'calendar-month';
    month.append(textNode('div', 'calendar-month-title', `${monthDate.getFullYear()}年 ${monthDate.getMonth() + 1}月`));

    const weekdays = document.createElement('div');
    weekdays.className = 'calendar-weekdays';
    ['一', '二', '三', '四', '五', '六', '日'].forEach((day) => weekdays.append(textNode('span', '', day)));
    month.append(weekdays);

    const days = document.createElement('div');
    days.className = 'calendar-days';
    const firstDayOffset = (monthDate.getDay() + 6) % 7;
    const gridStart = new Date(monthDate.getFullYear(), monthDate.getMonth(), 1 - firstDayOffset);
    const today = formatISODate(new Date());
    const selectedConfirmation = byId('confirmationDate').value;
    const rangeStart = datePickerState.periodStartDraft;
    const rangeEnd = datePickerState.periodEndDraft;

    for (let index = 0; index < 42; index += 1) {
      const date = new Date(gridStart.getFullYear(), gridStart.getMonth(), gridStart.getDate() + index);
      const value = formatISODate(date);
      const button = textNode('button', 'calendar-day', String(date.getDate()));
      button.type = 'button';
      button.dataset.date = value;
      button.setAttribute('aria-label', `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日`);
      if (date.getMonth() !== monthDate.getMonth()) button.classList.add('outside');
      if (value === today) button.classList.add('today');
      if (mode === 'confirmation' && value === selectedConfirmation) button.classList.add('selected');
      if (mode === 'period' && rangeStart) {
        if (value === rangeStart) button.classList.add('range-start');
        if (rangeEnd && value === rangeEnd) button.classList.add('range-end');
        if (rangeEnd && value > rangeStart && value < rangeEnd) button.classList.add('range-middle');
        if (rangeEnd && rangeStart === rangeEnd && value === rangeStart) button.classList.add('range-end');
      }
      button.addEventListener('click', () => selectCalendarDate(mode, value));
      days.append(button);
    }
    month.append(days);
    container.append(month);
  }

  function renderDatePickerCalendar(type) {
    if (type === 'period') {
      const holder = byId('periodCalendarMonths');
      holder.replaceChildren();
      const base = datePickerState.periodBaseMonth || startOfMonth(new Date());
      renderCalendarMonth(holder, base, 'period');
      renderCalendarMonth(holder, addMonths(base, 1), 'period');
      renderPeriodDraftValue();
      return;
    }
    const holder = byId('confirmationCalendarMonths');
    holder.replaceChildren();
    renderCalendarMonth(holder, datePickerState.confirmationBaseMonth || startOfMonth(new Date()), 'confirmation');
  }

  function closeDatePicker({ keepPeriodDraft = false } = {}) {
    ['period', 'confirmation'].forEach((type) => {
      byId(type === 'period' ? 'periodCalendar' : 'confirmationCalendar').hidden = true;
      byId(type === 'period' ? 'periodRangeTrigger' : 'confirmationDateTrigger').setAttribute('aria-expanded', 'false');
    });
    datePickerState.open = null;
    if (!keepPeriodDraft) {
      datePickerState.awaitingPeriodEnd = false;
      datePickerState.periodStartDraft = byId('periodStart').value;
      datePickerState.periodEndDraft = byId('periodEnd').value;
      renderDatePickerValues();
    }
  }

  function openDatePicker(type) {
    closeSubjectPicker();
    const currentlyOpen = datePickerState.open === type;
    closeDatePicker();
    if (currentlyOpen) return;
    datePickerState.open = type;
    if (type === 'period') {
      datePickerState.periodStartDraft = byId('periodStart').value;
      datePickerState.periodEndDraft = byId('periodEnd').value;
      datePickerState.awaitingPeriodEnd = false;
      datePickerState.periodBaseMonth = startOfMonth(parseISODate(datePickerState.periodStartDraft) || new Date());
      byId('periodCalendar').hidden = false;
      byId('periodRangeTrigger').setAttribute('aria-expanded', 'true');
    } else {
      datePickerState.confirmationBaseMonth = startOfMonth(parseISODate(byId('confirmationDate').value) || new Date());
      byId('confirmationCalendar').hidden = false;
      byId('confirmationDateTrigger').setAttribute('aria-expanded', 'true');
    }
    renderDatePickerCalendar(type);
  }

  function selectCalendarDate(type, value) {
    if (type === 'confirmation') {
      byId('confirmationDate').value = value;
      renderDatePickerValues();
      byId('confirmationDate').dispatchEvent(new Event('change', { bubbles: true }));
      closeDatePicker({ keepPeriodDraft: true });
      return;
    }

    if (!datePickerState.awaitingPeriodEnd) {
      datePickerState.periodStartDraft = value;
      datePickerState.periodEndDraft = '';
      datePickerState.awaitingPeriodEnd = true;
      renderDatePickerCalendar('period');
      return;
    }
    if (value < datePickerState.periodStartDraft) {
      datePickerState.periodStartDraft = value;
      datePickerState.periodEndDraft = '';
      renderDatePickerCalendar('period');
      return;
    }

    datePickerState.periodEndDraft = value;
    datePickerState.awaitingPeriodEnd = false;
    byId('periodStart').value = datePickerState.periodStartDraft;
    byId('periodEnd').value = datePickerState.periodEndDraft;
    renderDatePickerValues();
    byId('periodStart').dispatchEvent(new Event('change', { bubbles: true }));
    byId('periodEnd').dispatchEvent(new Event('change', { bubbles: true }));
    closeDatePicker({ keepPeriodDraft: true });
  }

  function bindDatePickers() {
    document.querySelectorAll('.date-picker-wrap').forEach((picker) => {
      picker.addEventListener('click', (event) => event.stopPropagation());
    });
    byId('periodRangeTrigger').addEventListener('click', () => openDatePicker('period'));
    byId('confirmationDateTrigger').addEventListener('click', () => openDatePicker('confirmation'));
    byId('periodCalendarPrevious').addEventListener('click', () => {
      datePickerState.periodBaseMonth = addMonths(datePickerState.periodBaseMonth, -1);
      renderDatePickerCalendar('period');
    });
    byId('periodCalendarNext').addEventListener('click', () => {
      datePickerState.periodBaseMonth = addMonths(datePickerState.periodBaseMonth, 1);
      renderDatePickerCalendar('period');
    });
    byId('confirmationCalendarPrevious').addEventListener('click', () => {
      datePickerState.confirmationBaseMonth = addMonths(datePickerState.confirmationBaseMonth, -1);
      renderDatePickerCalendar('confirmation');
    });
    byId('confirmationCalendarNext').addEventListener('click', () => {
      datePickerState.confirmationBaseMonth = addMonths(datePickerState.confirmationBaseMonth, 1);
      renderDatePickerCalendar('confirmation');
    });
    byId('confirmationTodayButton').addEventListener('click', () => selectCalendarDate('confirmation', formatISODate(new Date())));
    document.addEventListener('click', (event) => {
      if (datePickerState.open && !event.target.closest('.date-picker-wrap')) closeDatePicker();
    });
  }

  function subjectOptions() {
    return Array.from(byId('subject').options).filter((option) => option.value);
  }

  function syncSubjectPicker() {
    const select = byId('subject');
    const trigger = byId('subjectTrigger');
    const selected = select.selectedOptions[0];
    trigger.disabled = select.disabled;
    byId('subjectTriggerLabel').textContent = selected?.dataset.subjectLabel || selected?.textContent || '请选择合同主体';
    byId('subjectTriggerCount').textContent = selected?.value && selected.dataset.candidateCount
      ? `候选 ${selected.dataset.candidateCount}`
      : '';
    if (subjectPickerState.open) renderSubjectPickerOptions(byId('subjectSearch').value);
  }

  function visibleSubjectOptions(query = '') {
    const keyword = query.trim().toLowerCase();
    return subjectOptions().filter((option) => {
      const searchText = `${option.dataset.subjectLabel || ''} ${option.value}`.toLowerCase();
      return !keyword || searchText.includes(keyword);
    });
  }

  function chooseSubject(option) {
    const select = byId('subject');
    select.value = option.value;
    syncSubjectPicker();
    select.dispatchEvent(new Event('change', { bubbles: true }));
    closeSubjectPicker();
    byId('subjectTrigger').focus();
  }

  function markSubjectOptionActive(index) {
    subjectPickerState.activeIndex = index;
    Array.from(byId('subjectPickerOptions').children).forEach((node, optionIndex) => {
      node.dataset.active = String(optionIndex === index);
    });
  }

  function renderSubjectPickerOptions(query = '') {
    const holder = byId('subjectPickerOptions');
    const options = visibleSubjectOptions(query);
    const total = subjectOptions().length;
    holder.replaceChildren();
    byId('subjectPickerSummary').textContent = query.trim() ? `${options.length} / ${total} 个主体` : `${total} 个主体`;
    if (!options.length) {
      holder.append(textNode('div', 'subject-picker-empty', total ? '没有匹配的合同主体' : '当前周期暂无合同主体'));
      subjectPickerState.activeIndex = -1;
      return;
    }
    if (subjectPickerState.activeIndex < 0 || subjectPickerState.activeIndex >= options.length) {
      subjectPickerState.activeIndex = Math.max(0, options.findIndex((option) => option.selected));
    }
    options.forEach((option, index) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'subject-option';
      button.setAttribute('role', 'option');
      button.setAttribute('aria-selected', String(option.selected));
      button.dataset.active = String(index === subjectPickerState.activeIndex);
      button.append(
        textNode('span', 'subject-option-mark', option.selected ? '✓' : ''),
        textNode('span', 'subject-option-name', option.dataset.subjectLabel || option.textContent),
        textNode('span', 'subject-option-count', `${option.dataset.candidateCount || 0} 人`),
      );
      button.addEventListener('mouseenter', () => markSubjectOptionActive(index));
      button.addEventListener('click', () => chooseSubject(option));
      holder.append(button);
    });
  }

  function closeSubjectPicker() {
    subjectPickerState.open = false;
    byId('subjectPickerPanel').hidden = true;
    byId('subjectTrigger').setAttribute('aria-expanded', 'false');
  }

  function openSubjectPicker() {
    if (byId('subjectTrigger').disabled) return;
    closeDatePicker();
    subjectPickerState.open = true;
    subjectPickerState.activeIndex = Math.max(0, subjectOptions().findIndex((option) => option.selected));
    byId('subjectPickerPanel').hidden = false;
    byId('subjectTrigger').setAttribute('aria-expanded', 'true');
    byId('subjectSearch').value = '';
    renderSubjectPickerOptions();
    window.setTimeout(() => byId('subjectSearch').focus(), 0);
  }

  function bindSubjectPicker() {
    const picker = byId('subjectPicker');
    const trigger = byId('subjectTrigger');
    const search = byId('subjectSearch');
    picker.addEventListener('click', (event) => event.stopPropagation());
    trigger.addEventListener('click', () => {
      if (subjectPickerState.open) closeSubjectPicker();
      else openSubjectPicker();
    });
    trigger.addEventListener('keydown', (event) => {
      if (['ArrowDown', 'Enter', ' '].includes(event.key)) {
        event.preventDefault();
        if (!subjectPickerState.open) openSubjectPicker();
      }
    });
    search.addEventListener('input', () => {
      subjectPickerState.activeIndex = 0;
      renderSubjectPickerOptions(search.value);
    });
    search.addEventListener('keydown', (event) => {
      const options = visibleSubjectOptions(search.value);
      if (event.key === 'Escape') { event.preventDefault(); closeSubjectPicker(); trigger.focus(); return; }
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        if (!options.length) return;
        const direction = event.key === 'ArrowDown' ? 1 : -1;
        subjectPickerState.activeIndex = (subjectPickerState.activeIndex + direction + options.length) % options.length;
        renderSubjectPickerOptions(search.value);
        byId('subjectPickerOptions').children[subjectPickerState.activeIndex]?.scrollIntoView({ block: 'nearest' });
      }
      if (event.key === 'Enter' && options[subjectPickerState.activeIndex]) {
        event.preventDefault();
        chooseSubject(options[subjectPickerState.activeIndex]);
      }
    });
    document.addEventListener('click', (event) => {
      if (subjectPickerState.open && !event.target.closest('#subjectPicker')) closeSubjectPicker();
    });
    syncSubjectPicker();
  }

  function displayIssue(employee) {
    const blocking = (employee.issues || []).find((item) => item.severity === 'blocking');
    const info = (employee.issues || []).find((item) => item.severity === 'info');
    if (blocking && employee.confirmed) return { type: 'info', title: '已人工确认', message: blocking.message };
    if (blocking) return { type: 'blocking', title: '需要处理', message: blocking.message };
    if (info) return { type: 'info', title: '仅提示', message: info.message };
    return { type: 'clear', title: '校验通过', message: employee.reason || '规则校验通过' };
  }

  function selectionMatchesRun() {
    if (!state.run) return false;
    return state.run.periodStart === byId('periodStart').value
      && state.run.periodEnd === byId('periodEnd').value
      && state.run.confirmationDate === byId('confirmationDate').value
      && (!state.subjectsReady || !byId('subject').value || state.run.subject === byId('subject').value);
  }

  function selectedBatchContext() {
    return {
      periodStart: byId('periodStart').value,
      periodEnd: byId('periodEnd').value,
      confirmationDate: byId('confirmationDate').value,
      subject: byId('subject').value.trim(),
    };
  }

  function batchContextKey(context) {
    return [context.periodStart, context.periodEnd, context.confirmationDate, context.subject].join('::');
  }

  function indexRun(run) {
    if (!run?.id) return;
    state.batchIndex.set(batchContextKey(run), run.id);
  }

  async function loadSelectedSubjectRun({ silent = false } = {}) {
    const context = selectedBatchContext();
    if (!state.subjectsReady || !Object.values(context).every(Boolean)) return;
    if (selectionMatchesRun()) { indexRun(state.run); return; }
    const requestSequence = ++runRequestSequence;
    state.run = null;
    renderRun();
    byId('lastSyncLabel').textContent = '正在加载主体批次…';
    try {
      let runId = state.batchIndex.get(batchContextKey(context));
      if (!runId) {
        const params = new URLSearchParams({ ...context, limit: '1' });
        const payload = await api(`${API_ROOT}/runs?${params.toString()}`);
        if (requestSequence !== runRequestSequence) return;
        runId = payload.runs?.[0]?.id;
        if (runId) state.batchIndex.set(batchContextKey(context), runId);
      }
      if (!runId) {
        state.run = null;
        renderRun();
        if (!silent) showToast('该周期尚未生成主体批次，请点击“生成全部主体批次”', 'error');
        return;
      }
      const run = await api(`${RUN_ENDPOINT_PREFIX}${encodeURIComponent(runId)}`);
      if (requestSequence !== runRequestSequence) return;
      state.run = run;
      state.filter = 'all';
      state.search = '';
      byId('employeeSearch').value = '';
      indexRun(run);
      renderRun();
    } catch (error) {
      if (requestSequence !== runRequestSequence) return;
      byId('lastSyncLabel').textContent = '主体批次加载失败';
      if (!silent) showToast(error.message, 'error');
    }
  }

  function renderMetrics() {
    const summary = state.run?.summary || {};
    byId('metricTotal').textContent = summary.total ?? '—';
    byId('metricReady').textContent = summary.ready ?? '—';
    byId('metricReview').textContent = summary.needsReview ?? '—';
    byId('metricIncluded').textContent = summary.included ?? '—';
    byId('metricExcluded').textContent = summary.excluded ?? '—';
    byId('filterAll').textContent = summary.total ?? 0;
    byId('filterReview').textContent = summary.needsReview ?? 0;
    byId('filterReady').textContent = summary.ready ?? 0;
    byId('filterExcluded').textContent = summary.excluded ?? 0;
  }

  function renderStages() {
    const run = selectionMatchesRun() ? state.run : null;
    const status = run?.status;
    const preflight = currentPreflight();
    const hasReadyTemplateRoute = Boolean(preflight?.groups?.some((group) => group.templateUsable));
    const completed = new Set();
    let active = 'sync';
    if (run) { completed.add('sync'); active = 'review'; }
    if (status === 'confirmed' || status === 'generated') { completed.add('review'); active = 'template'; }
    if (hasReadyTemplateRoute || run?.reportPackage) { completed.add('template'); active = 'generate'; }
    if (run?.reportPackage) { completed.add('generate'); active = 'final'; }
    document.querySelectorAll('.stage').forEach((node) => {
      const key = node.dataset.stage;
      const isComplete = completed.has(key);
      const isActive = key === active;
      node.classList.toggle('complete', isComplete);
      node.classList.toggle('active', isActive);
      node.dataset.state = isComplete ? 'complete' : (isActive ? 'active' : 'pending');
      if (isActive) node.setAttribute('aria-current', 'step');
      else node.removeAttribute('aria-current');
    });
  }

  function filteredEmployees() {
    if (!state.run) return [];
    const query = state.search.trim().toLowerCase();
    return state.run.employees.filter((employee) => {
      if (state.filter !== 'all' && employee.status !== state.filter) return false;
      if (!query) return true;
      const report = employee.report || {};
      const haystack = `${report['姓名'] || ''} ${employee.source?.jobNumber || ''} ${employee.maskedId || ''} ${String(report['证件号码'] || '').slice(-4)}`.toLowerCase();
      return haystack.includes(query);
    });
  }

  function maskPhone(value) {
    const text = String(value || '').trim();
    return /^\d{11}$/.test(text) ? `${text.slice(0, 3)}****${text.slice(-4)}` : text;
  }

  function maskEmail(value) {
    const text = String(value || '').trim();
    const [account, domain] = text.split('@');
    if (!domain) return text;
    return `${account.slice(0, 2)}***@${domain}`;
  }

  function createReviewFieldCell(rawValue, extraClass = '', mask = '') {
    const cell = document.createElement('td');
    cell.className = `review-field-cell ${extraClass}`.trim();
    const original = String(rawValue || '').trim();
    let value = original;
    if (mask === 'phone') value = maskPhone(original);
    if (mask === 'email') value = maskEmail(original);
    const display = textNode('span', original ? '' : 'missing', value || '未提供');
    if (original && !mask) display.title = original;
    cell.append(display);
    return cell;
  }

  function coverageStatusSummary(...tasks) {
    const labels = tasks.map((task) => task?.statusLabel || COVERAGE_STATUS_LABELS[task?.status] || '').filter(Boolean);
    return [...new Set(labels)].join(' / ');
  }

  function ensureStickyTableHeader() {
    const holder = byId('tableStickyHeader');
    const sourceHead = document.querySelector('.table-wrap thead');
    if (!holder || !sourceHead || holder.querySelector('table')) return;
    const table = document.createElement('table');
    table.setAttribute('aria-hidden', 'true');
    const clonedHead = sourceHead.cloneNode(true);
    clonedHead.querySelectorAll('[id]').forEach((node) => node.removeAttribute('id'));
    table.append(clonedHead);
    const decisionHeading = textNode('span', 'floating-key-heading', '处理');
    const personHeading = textNode('span', 'floating-key-heading floating-person-heading', '姓名');
    const actionHeading = textNode('span', 'floating-action-heading', '操作');
    holder.append(table, decisionHeading, personHeading, actionHeading);
  }

  function syncFloatingTableTools(measureHeader = false) {
    const tableWrap = document.querySelector('.table-wrap');
    const sourceTable = tableWrap?.querySelector('table');
    const sourceHead = sourceTable?.querySelector('thead');
    const panel = document.querySelector('.review-panel');
    const dock = byId('tableScrollDock');
    const dockSlot = byId('tableScrollDockSlot');
    const stickyHeader = byId('tableStickyHeader');
    if (!tableWrap || !sourceTable || !sourceHead || !panel || !dock || !dockSlot || !stickyHeader) return;

    ensureStickyTableHeader();
    const floatingTable = stickyHeader.querySelector('table');
    const hasRows = Boolean(tableWrap.querySelector('tbody tr:not(.empty-row)'));
    const maximum = Math.max(0, tableWrap.scrollWidth - tableWrap.clientWidth);
    const viewportHeight = window.innerHeight;
    const panelRect = panel.getBoundingClientRect();
    const tableRect = tableWrap.getBoundingClientRect();
    const slotRect = dockSlot.getBoundingClientRect();
    const shouldFloatDock = hasRows
      && maximum > 1
      && tableRect.top < viewportHeight - 70
      && slotRect.top > viewportHeight - 58
      && panelRect.bottom > 72;
    dock.classList.toggle('is-floating', shouldFloatDock);
    if (shouldFloatDock) {
      const left = Math.max(12, Math.round(panelRect.left));
      const right = Math.min(window.innerWidth - 12, Math.round(panelRect.right));
      dock.style.left = `${left}px`;
      dock.style.setProperty('--dock-width', `${Math.max(280, right - left)}px`);
    } else {
      dock.style.removeProperty('left');
      dock.style.removeProperty('--dock-width');
    }

    const topbar = document.querySelector('.si-topbar');
    const stickyTop = Math.max(0, Math.round(topbar?.getBoundingClientRect().bottom || 0));
    const headRect = sourceHead.getBoundingClientRect();
    const headerHeight = Math.max(42, Math.round(headRect.height));
    const shouldShowHeader = hasRows
      && panelRect.top <= stickyTop + 1
      && headRect.bottom <= stickyTop + 1
      && tableRect.bottom > stickyTop + headerHeight
      && panelRect.bottom > stickyTop + headerHeight;
    stickyHeader.classList.toggle('is-visible', shouldShowHeader);
    stickyHeader.style.left = `${Math.round(panelRect.left)}px`;
    stickyHeader.style.top = `${stickyTop}px`;
    stickyHeader.style.width = `${Math.round(panelRect.width)}px`;
    stickyHeader.style.height = `${headerHeight}px`;

    if (!floatingTable) return;
    if (measureHeader || stickyHeader.dataset.measured !== 'true') {
      floatingTable.style.width = `${sourceTable.scrollWidth}px`;
      const sourceCells = sourceHead.querySelectorAll('th');
      const floatingCells = floatingTable.querySelectorAll('th');
      sourceCells.forEach((cell, index) => {
        const width = cell.getBoundingClientRect().width;
        const floatingCell = floatingCells[index];
        if (!floatingCell) return;
        floatingCell.style.width = `${width}px`;
        floatingCell.style.minWidth = `${width}px`;
        floatingCell.style.maxWidth = `${width}px`;
      });
      stickyHeader.dataset.measured = 'true';
    }
    const position = Math.max(0, tableWrap.scrollLeft);
    floatingTable.style.transform = `translateX(${-position}px)`;
  }

  function syncTableHorizontalControl() {
    const tableWrap = document.querySelector('.table-wrap');
    const range = byId('tableScrollRange');
    if (!tableWrap || !range) return;
    const maximum = Math.max(0, tableWrap.scrollWidth - tableWrap.clientWidth);
    const position = Math.min(maximum, Math.max(0, tableWrap.scrollLeft));
    range.max = String(Math.round(maximum));
    range.value = String(Math.round(position));
    range.disabled = maximum <= 1;
    byId('tableScrollLeft').disabled = position <= 1;
    byId('tableScrollRight').disabled = position >= maximum - 1;
    byId('tableScrollDock').dataset.scrollable = String(maximum > 1);
    syncFloatingTableTools();
  }

  function bindTableHorizontalControl() {
    const tableWrap = document.querySelector('.table-wrap');
    const range = byId('tableScrollRange');
    const left = byId('tableScrollLeft');
    const right = byId('tableScrollRight');
    if (!tableWrap || !range || !left || !right) return;

    const move = (direction) => {
      const distance = Math.max(320, Math.round(tableWrap.clientWidth * .7));
      tableWrap.scrollBy({ left: direction * distance, behavior: 'smooth' });
    };
    tableWrap.addEventListener('scroll', syncTableHorizontalControl, { passive: true });
    tableWrap.addEventListener('wheel', (event) => {
      if (!event.shiftKey || tableWrap.scrollWidth <= tableWrap.clientWidth + 1) return;
      event.preventDefault();
      tableWrap.scrollLeft += event.deltaY || event.deltaX;
    }, { passive: false });
    range.addEventListener('input', () => {
      tableWrap.scrollLeft = Number(range.value);
      syncTableHorizontalControl();
    });
    left.addEventListener('click', () => move(-1));
    right.addEventListener('click', () => move(1));
    window.addEventListener('scroll', syncFloatingTableTools, { passive: true });
    window.addEventListener('resize', () => {
      syncTableHorizontalControl();
      syncFloatingTableTools(true);
    }, { passive: true });
    if ('ResizeObserver' in window) {
      const observer = new ResizeObserver(() => {
        syncTableHorizontalControl();
        syncFloatingTableTools(true);
      });
      observer.observe(tableWrap);
      const table = tableWrap.querySelector('table');
      if (table) observer.observe(table);
    }
    ensureStickyTableHeader();
    window.requestAnimationFrame(() => {
      syncTableHorizontalControl();
      syncFloatingTableTools(true);
    });
  }

  function schemaForRoute(route) {
    return state.schemaDefinitions.find((schema) => schema.route === route) || null;
  }

  function availableTemplateRoutes() {
    const planned = (state.run?.processingPlan || [])
      .filter((plan) => plan.handling === 'template' && schemaForRoute(plan.route))
      .map((plan) => plan.route);
    return [...new Set(planned)];
  }

  function syncTemplateRouteSelectors() {
    const routes = availableTemplateRoutes();
    if (!routes.includes(state.templateRoute)) state.templateRoute = routes[0] || '';
    const fill = (select, selected) => {
      const previous = selected || select.value;
      select.replaceChildren();
      routes.forEach((route) => {
        const option = document.createElement('option');
        option.value = route;
        option.textContent = schemaForRoute(route)?.label || route;
        select.append(option);
      });
      if (routes.includes(previous)) select.value = previous;
      else if (routes.length) select.value = routes[0];
    };
    fill(byId('templateRouteSelect'), state.templateRoute);
    state.templateRoute = byId('templateRouteSelect').value || '';
    fill(byId('templateUploadRoute'), byId('templateUploadRoute').value || state.templateRoute);
    byId('templateRouteSelect').hidden = state.view !== 'template' || routes.length < 2;
  }

  function currentTableColumns() {
    if (state.view === 'source') {
      return SOURCE_COLUMNS.map(([label, key, className = '', mask = '']) => ({ label, key, className, mask, type: 'source' }));
    }
    if (state.view === 'template') {
      const schema = schemaForRoute(state.templateRoute);
      return (schema?.fields || []).map((field) => ({ label: field.name, field, type: 'template' }));
    }
    return BUSINESS_COLUMNS;
  }

  function renderTableHeader() {
    const header = byId('employeeTableHeader');
    header.replaceChildren();
    const append = (label, className = '') => {
      const cell = textNode('th', className, label);
      header.append(cell);
    };
    append('处理', 'sticky-key sticky-decision');
    append('姓名', 'sticky-key sticky-person');
    currentTableColumns().forEach((column) => append(column.label, column.className?.includes('job-number') ? 'job-number-heading' : ''));
    append('操作', 'sticky-action');
    byId('tableStickyHeader').replaceChildren();
  }

  function templateMissingSummary(employee) {
    const missing = [];
    Object.values(employee.templateReports || {}).forEach((report) => {
      (report?.missingRequired || []).forEach((field) => missing.push(field));
    });
    const unique = [...new Set(missing)];
    return unique.length ? `${unique.length}项 · ${unique.slice(0, 2).join('、')}` : '已齐全';
  }

  function sourceColumnValue(employee, key) {
    const source = employee.source || {};
    if (key === 'maskedId') return employee.maskedId;
    if (key === 'entryDate') return employee.entryDate;
    if (key === 'socialComputer') return employee.report?.['电脑号'];
    if (key === 'housingFundAccount') return employee.report?.['公积金号'];
    if (key === 'socialContributionBase') return employee.report?.['社保缴交基数'] || source[key];
    if (key === 'housingContributionBase') return employee.report?.['公积金缴交基数'] || source[key];
    if (key === 'householdAddress') return employee.report?.['户口具体地址'] || source[key];
    if (key === 'mobile') return employee.report?.['手机号码'] || source[key];
    if (key === 'socialMedicalStatus') return source[key] || coverageStatusSummary(employee.coverageTasks?.social, employee.coverageTasks?.medical);
    if (key === 'housingStatus') return source[key] || coverageStatusSummary(employee.coverageTasks?.housing);
    return source[key];
  }

  function appendIssueCell(row, employee) {
    const issue = displayIssue(employee);
    const issueCell = document.createElement('td');
    issueCell.className = `issue-cell ${issue.type}`;
    issueCell.append(textNode('b', '', issue.title), textNode('span', '', issue.message));
    row.append(issueCell);
  }

  function appendActionCell(row, employee, isCurrentBatch) {
    const actionCell = document.createElement('td');
    actionCell.className = 'sticky-action';
    const status = textNode('span', `status-pill ${employee.status}`, STATUS_LABELS[employee.status] || employee.status);
    const edit = textNode('button', 'edit-button', isCurrentBatch ? '查看 / 修改' : '上一批次');
    edit.type = 'button';
    edit.disabled = !isCurrentBatch;
    edit.addEventListener('click', () => openDrawer(employee.id));
    actionCell.append(status, edit);
    row.append(actionCell);
  }

  function renderTable() {
    const body = byId('employeeTableBody');
    body.replaceChildren();
    renderTableHeader();
    const columns = currentTableColumns();
    const employees = filteredEmployees();
    if (!employees.length) {
      const row = document.createElement('tr');
      row.className = 'empty-row';
      const cell = document.createElement('td');
      cell.colSpan = columns.length + 3;
      const holder = document.createElement('div');
      holder.append(textNode('b', '', state.run ? '当前筛选没有人员' : '等待同步北森人员'));
      holder.append(textNode('span', '', state.run ? '调整状态筛选或搜索关键词' : '选择周期和合同主体后点击“生成本批名单”'));
      cell.append(holder); row.append(cell); body.append(row);
      byId('tableCount').textContent = '当前 0 人';
      window.requestAnimationFrame(() => { syncTableHorizontalControl(); syncFloatingTableTools(true); });
      return;
    }
    const isCurrentBatch = selectionMatchesRun();
    employees.forEach((employee) => {
      const report = employee.report || {};
      const row = document.createElement('tr');
      row.dataset.status = employee.status || '';

      const decisionCell = document.createElement('td');
      decisionCell.className = 'sticky-key sticky-decision';
      const decisionLabel = document.createElement('label');
      decisionLabel.className = 'decision-toggle';
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox'; checkbox.checked = employee.decision === 'include';
      checkbox.disabled = !isCurrentBatch;
      checkbox.title = checkbox.checked ? '已纳入本批报盘' : '已排除本批报盘';
      checkbox.addEventListener('change', () => quickDecision(employee, checkbox));
      decisionLabel.append(checkbox, textNode('span', '', checkbox.checked ? '纳入' : '排除'));
      decisionCell.append(decisionLabel); row.append(decisionCell);

      const person = document.createElement('td'); person.className = 'person-cell review-field-cell sticky-key sticky-person';
      person.append(textNode('b', '', report['姓名'] || '未命名')); row.append(person);
      if (employee.supplemental) person.append(textNode('em', 'supplement-tag', `补充 · ${employee.supplemental.label}`));

      const source = employee.source || {};
      columns.forEach((column) => {
        if (column.type === 'issue') { appendIssueCell(row, employee); return; }
        if (column.type === 'missing') {
          const value = templateMissingSummary(employee);
          row.append(createReviewFieldCell(value, value === '已齐全' ? 'template-ready-cell' : 'template-missing-cell'));
          return;
        }
        if (column.type === 'template') {
          const template = employee.templateReports?.[state.templateRoute];
          const value = template ? template.values?.[column.field.name] : '不适用';
          const missing = template?.missingRequired?.includes(column.field.name);
          row.append(createReviewFieldCell(value, `${missing ? 'template-missing-cell' : ''} ${WIDE_FIELDS.has(column.field.name) ? 'address-field-cell' : ''}`));
          return;
        }
        if (column.type === 'source') {
          row.append(createReviewFieldCell(sourceColumnValue(employee, column.key), column.className, column.mask));
          return;
        }
        row.append(createReviewFieldCell(column.value(employee), column.className || '', column.mask || ''));
      });
      appendActionCell(row, employee, isCurrentBatch);
      body.append(row);
    });
    byId('tableCount').textContent = `当前 ${employees.length} 人`;
    window.requestAnimationFrame(() => { syncTableHorizontalControl(); syncFloatingTableTools(true); });
  }

  function renderProcessingPlan() {
    const list = byId('routePlanList');
    const plans = state.run?.processingPlan || [];
    list.replaceChildren();
    byId('routePlanCount').textContent = plans.length ? `${plans.length} 条办理路径` : '等待同步';
    if (!plans.length) {
      list.append(textNode('p', '', '同步后显示模板批次与线下办理任务'));
      return;
    }
    plans.forEach((plan) => {
      const item = document.createElement('article');
      item.dataset.handling = plan.handling || 'manual';
      const coverageLabels = (plan.coverages || []).map((value) => value === 'social' ? '社保' : '医保').join(' + ');
      const copy = document.createElement('span');
      copy.append(textNode('b', '', plan.routeLabel || '线下办理'), textNode('small', '', coverageLabels || '办理任务'));
      item.append(copy, textNode('strong', '', `${plan.employeeCount || 0}人`));
      list.append(item);
    });
  }

  function currentPreflight() {
    const run = state.run;
    const key = run?.id ? `${run.id}:${run.updatedAt || ''}` : '';
    return state.preflight?.runId === run?.id && state.preflightKey === key ? state.preflight : null;
  }

  function selectedPreflightGroup() {
    const route = byId('templateUploadRoute')?.value || state.templateRoute;
    return currentPreflight()?.groups?.find((group) => group.route === route) || null;
  }

  function templateOriginLabel(template) {
    if (!template) return '';
    if (template.source === 'uploaded' || template.matchQuality === 'uploaded') return '本批手动上传';
    if (template.subjectMatched) return '线下模板库 · 主体匹配';
    return '线下模板库 · 仅城市匹配';
  }

  function renderPreflight() {
    const holder = byId('preflightList');
    const label = byId('preflightState');
    const card = byId('preflightCard');
    const preflight = currentPreflight();
    holder.replaceChildren();
    card.classList.remove('ready', 'warning');
    if (!state.run) {
      label.textContent = '等待名单';
      holder.append(textNode('p', '', '生成名单后，按办理路径检查必填资料和模板版本。'));
      byId('templateMatchState').textContent = '等待名单与办理路径';
      return;
    }
    if (state.preflightLoading && !preflight) {
      label.textContent = '正在校验';
      const loading = document.createElement('div');
      loading.className = 'preflight-loading';
      loading.append(textNode('i', '', ''), textNode('span', '', '正在检查字段完整性和模板版本…'));
      holder.append(loading);
      return;
    }
    if (!preflight) {
      label.textContent = '等待校验';
      holder.append(textNode('p', '', '尚未取得生成前校验结果。'));
      return;
    }
    const summary = preflight.summary || {};
    const blocked = Number(summary.blockedRoutes || 0);
    label.textContent = blocked
      ? `${summary.readyRoutes || 0} 条可生成 · ${blocked} 条待处理`
      : (summary.templateRoutes ? '全部模板路径已就绪' : '当前没有模板路径');
    card.classList.toggle('ready', blocked === 0 && Number(summary.templateRoutes || 0) > 0);
    card.classList.toggle('warning', blocked > 0);
    (preflight.groups || []).forEach((group) => {
      const item = document.createElement('article');
      item.className = `preflight-item ${group.status || ''}`;
      const main = document.createElement('span');
      main.append(textNode('b', '', group.label || group.route));
      const details = [];
      details.push(`${group.employeeCount || 0}人`);
      if (group.missingFields?.length) {
        details.push(group.missingFields.slice(0, 2).map((entry) => `${entry.field}${entry.count}人`).join('、'));
      } else if (group.template) {
        details.push(templateOriginLabel(group.template));
      }
      main.append(textNode('small', '', details.filter(Boolean).join(' · ')));
      item.append(main, textNode('strong', '', group.statusLabel || '待校验'));
      holder.append(item);
    });
    (preflight.manualRoutes || []).forEach((route) => {
      const item = document.createElement('article');
      item.className = 'preflight-item manual';
      const main = document.createElement('span');
      main.append(textNode('b', '', route.label || '线下办理'), textNode('small', '', `${route.employeeCount || 0}人 · 不生成政务模板`));
      item.append(main, textNode('strong', '', '线下办理'));
      holder.append(item);
    });
    if (!holder.children.length) holder.append(textNode('p', '', '当前批次没有需要生成的办理路径。'));

    const selected = selectedPreflightGroup();
    const matchState = byId('templateMatchState');
    if (!selected) matchState.textContent = '当前没有可选模板路径';
    else if (!selected.template) matchState.textContent = '模板库未匹配到文件，请手动上传当前版本';
    else if (selected.templateUsable) {
      matchState.textContent = `${templateOriginLabel(selected.template)}：${selected.template.filename}${selected.template.period ? ` · ${selected.template.period}` : ''}`;
    } else {
      matchState.textContent = `找到同城模板：${selected.template.filename}；主体未匹配，请确认后上传`;
    }
  }

  async function ensurePreflight() {
    const run = state.run;
    if (!run?.id) {
      state.preflight = null;
      state.preflightKey = '';
      renderPreflight();
      return;
    }
    const key = `${run.id}:${run.updatedAt || ''}`;
    if (state.preflightKey === key || state.preflightLoading) return;
    state.preflightLoading = true;
    if (state.preflight?.runId !== run.id) state.preflight = null;
    renderPreflight();
    try {
      const payload = await api(`${API_ROOT}/runs/${encodeURIComponent(run.id)}/preflight`);
      if (state.run?.id !== run.id) return;
      state.preflight = payload;
      state.preflightKey = key;
    } catch (error) {
      if (state.run?.id === run.id) {
        state.preflight = null;
        state.preflightKey = key;
        const holder = byId('preflightList');
        holder.replaceChildren(textNode('p', 'preflight-error', error.message));
        byId('preflightState').textContent = '校验失败';
      }
    } finally {
      state.preflightLoading = false;
      if (state.run?.id === run.id) {
        renderPreflight();
        renderStages();
        renderActions();
      } else {
        ensurePreflight();
      }
    }
  }

  function uploadedTemplateForRoute(run, route) {
    if (!run || !route) return null;
    const uploaded = run.templates?.[route];
    if (uploaded) return uploaded;
    return route === 'shenzhen-social-medical' ? run.template : null;
  }

  function renderActions() {
    const run = state.run;
    const isCurrentBatch = selectionMatchesRun();
    const confirmed = isCurrentBatch && (run?.status === 'confirmed' || run?.status === 'generated');
    const preflight = currentPreflight();
    const selectedRoute = byId('templateUploadRoute').value || state.templateRoute;
    const selectedGroup = preflight?.groups?.find((group) => group.route === selectedRoute) || null;
    const uploadedTemplate = uploadedTemplateForRoute(run, selectedRoute);
    const confirmButton = byId('confirmBatchButton');
    confirmButton.disabled = !isCurrentBatch || confirmed;
    confirmButton.textContent = !isCurrentBatch && run ? '等待同步新周期' : (confirmed ? '人员已确认' : '确认本批人员');
    byId('auditExportButton').disabled = !run || Boolean(state.operation);
    byId('missingExportButton').disabled = !run || Boolean(state.operation);
    byId('openSupplementButton').disabled = !isCurrentBatch || !run || Boolean(state.operation);
    const batchStatus = byId('batchStatus');
    batchStatus.className = `batch-status ${run?.status || ''}`;
    batchStatus.querySelector('span').textContent = run
      ? (isCurrentBatch ? (STATUS_TEXT[run.status] || run.status) : '上一批次，仅供查看')
      : '等待同步';

    const templateDropzone = byId('templateDropzone');
    const canUpload = Boolean(confirmed && selectedRoute);
    byId('templateUploadRoute').disabled = !confirmed || !availableTemplateRoutes().length;
    templateDropzone.setAttribute('aria-disabled', String(!canUpload));
    templateDropzone.tabIndex = canUpload ? 0 : -1;
    templateDropzone.dataset.state = uploadedTemplate ? 'uploaded' : (canUpload ? 'ready' : 'locked');
    if (!templateDropzone.classList.contains('loading')) {
      templateDropzone.querySelector('.dropzone-copy b').textContent = uploadedTemplate ? '更换当前路径模板' : '手动上传当前版本';
    }
    byId('templateState').textContent = !isCurrentBatch && run
      ? '等待同步新周期'
      : (confirmed ? (selectedGroup?.templateUsable ? '模板已确认' : '需要确认模板') : '待人员确认');
    byId('templateCard').classList.toggle('ready', Boolean(confirmed && selectedGroup?.templateUsable));
    const templateFile = byId('templateFileState');
    const selectedTemplate = selectedGroup?.template;
    templateFile.querySelector('span').textContent = uploadedTemplate?.originalFilename || selectedTemplate?.filename || '未匹配模板';
    templateFile.querySelector('small').textContent = uploadedTemplate
      ? `${Math.ceil((uploadedTemplate.size || 0) / 1024)} KB · 仅用于当前路径`
      : (selectedTemplate ? templateOriginLabel(selectedTemplate) : '支持 .xls / .xlsx，最大 20MB');

    const generateButton = byId('generateButton');
    const readyRoutes = Number(preflight?.summary?.readyRoutes || 0);
    const templateRoutes = Number(preflight?.summary?.templateRoutes || 0);
    const canGenerate = Boolean(confirmed && preflight && (readyRoutes > 0 || templateRoutes === 0));
    generateButton.disabled = !canGenerate || Boolean(state.operation);
    byId('reportState').textContent = !isCurrentBatch && run
      ? '等待同步新周期'
      : (run?.reportPackage
        ? (run.reportPackage.partial ? '已生成部分路径' : '全部路径已生成')
        : (canGenerate ? (readyRoutes < templateRoutes ? '可生成已就绪路径' : '可以生成') : (confirmed ? '请先处理阻断项' : '等待人员确认')));
    byId('reportCard').classList.toggle('ready', canGenerate);
    const download = byId('downloadButton');
    if (isCurrentBatch && run?.reportPackage) {
      const generatedCount = run.reportPackage.generatedRoutes?.length || 0;
      const blockedCount = run.reportPackage.blockedRoutes?.length || 0;
      download.classList.remove('hidden');
      download.href = `${API_ROOT}/runs/${encodeURIComponent(run.id)}/package/download`;
      download.textContent = blockedCount
        ? `下载报盘包（已生成${generatedCount}条，待处理${blockedCount}条） ↓`
        : `下载政务报盘包（${generatedCount}条路径） ↓`;
    } else {
      download.classList.add('hidden'); download.href = '#';
    }
  }

  function renderRun() {
    syncTemplateRouteSelectors();
    renderMetrics(); renderTable(); renderProcessingPlan(); renderPreflight(); renderStages(); renderActions();
    const isCurrentBatch = selectionMatchesRun();
    const periodNotice = byId('periodContextNotice');
    periodNotice.hidden = !state.run || isCurrentBatch;
    if (state.run && !isCurrentBatch) {
      periodNotice.textContent = `当前显示的是上一批次 ${state.run.periodStart} 至 ${state.run.periodEnd} 的结果；新周期尚未同步，上一批次只能查看。`;
    }
    const sourceWarning = byId('sourceWarning');
    const warnings = state.run?.sourceSummary?.warnings || [];
    sourceWarning.hidden = warnings.length === 0;
    sourceWarning.textContent = warnings.map((warning) => {
      if (!warning.includes('离职快照')) return warning;
      const confirmationDate = state.run?.confirmationDate || '名单确认日';
      if (warning.includes('日期无法从文件名识别')) {
        return `离职数据时点校验：该提示用于确认离职数据是否覆盖到名单确认日，避免已离职人员被误纳入。当前无法识别快照日期，请确认数据已更新至 ${confirmationDate}。`;
      }
      return `离职数据时点校验：该提示用于确认离职数据是否覆盖到名单确认日，避免已离职人员被误纳入。${warning}`;
    }).join('；');
    byId('lastSyncLabel').textContent = state.run
      ? (isCurrentBatch
        ? `${state.run.periodStart} 至 ${state.run.periodEnd} · ${formatRunTimestamp(state.run.updatedAt)}`
        : `上一批次 ${state.run.periodStart} 至 ${state.run.periodEnd}`)
      : '本周期尚未生成';
    ensurePreflight();
  }

  function formatPoolTimestamp(value) {
    if (!value) return '';
    const parsed = new Date(value);
    if (Number.isNaN(parsed.valueOf())) return '';
    return new Intl.DateTimeFormat('zh-CN', {
      month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
    }).format(parsed);
  }

  function renderSupplementPoolStatus(payload = {}) {
    const holder = byId('supplementPoolState');
    if (!holder) return;
    const stateName = payload.state || 'empty';
    holder.dataset.state = stateName;
    const labels = {
      ready: '历史候选已准备',
      warming: '正在准备历史候选',
      error: '历史候选加载失败',
      empty: '历史候选按需加载',
    };
    holder.querySelector('b').textContent = labels[stateName] || payload.label || labels.empty;
    const cachedAt = formatPoolTimestamp(payload.cachedAt);
    const nextRunAt = formatPoolTimestamp(payload.scheduler?.nextRunAt);
    let detail = '首次查找时自动加载，不影响当前批次审核';
    if (stateName === 'ready') detail = `最近更新 ${cachedAt || '刚刚'} · 候选 ${payload.recordCount ?? 0} 人${nextRunAt ? ` · 下次 ${nextRunAt}` : ''}`;
    if (stateName === 'warming') detail = '正在检查本周期开始日前一年内的记录，可以先填写搜索条件';
    if (stateName === 'error') detail = '查找时会自动重试，也可以关闭弹窗继续审核当前批次';
    byId('supplementPoolDetail').textContent = detail;
  }

  async function loadSupplementPoolStatus() {
    window.clearTimeout(supplementPoolStatusTimer);
    if (!state.run || byId('supplementDialog').hidden) return;
    try {
      const payload = await api(`${API_ROOT}/runs/${state.run.id}/supplement-candidates/status`);
      renderSupplementPoolStatus(payload);
      if (payload.state === 'warming') {
        supplementPoolStatusTimer = window.setTimeout(loadSupplementPoolStatus, 5000);
      } else if (payload.state === 'error') {
        supplementPoolStatusTimer = window.setTimeout(loadSupplementPoolStatus, 30000);
      }
    } catch (error) {
      renderSupplementPoolStatus({ state: 'error', label: error.message });
      supplementPoolStatusTimer = window.setTimeout(loadSupplementPoolStatus, 30000);
    }
  }

  function applyContractSubjects(subjects, preferredValue = '') {
    const select = byId('subject');
    const previousValue = select.value;
    select.replaceChildren();
    subjects.forEach((subject) => {
      const option = document.createElement('option');
      option.value = subject.value;
      option.textContent = subject.candidateCount > 0
        ? `${subject.label}（候选${subject.candidateCount}人）`
        : subject.label;
      option.dataset.subjectLabel = subject.label;
      option.dataset.candidateCount = String(subject.candidateCount || 0);
      if (subject.code) option.dataset.subjectCode = subject.code;
      select.append(option);
    });
    const desired = preferredValue || previousValue || state.run?.subject || '';
    if (subjects.some((subject) => subject.value === desired)) select.value = desired;
    syncSubjectPicker();
  }

  function scheduleContractSubjectCompletion(preferredValue, requestSequence, attempt = 0) {
    window.clearTimeout(subjectCompletionTimer);
    if (attempt >= 40) {
      byId('subjectSourceState').textContent = '已加载最近同步主体；后台自动补齐暂未完成';
      byId('retrySubjectsButton').hidden = false;
      return;
    }
    subjectCompletionTimer = window.setTimeout(async () => {
      if (requestSequence !== subjectRequestSequence || state.operation) return;
      const periodStart = byId('periodStart').value;
      const periodEnd = byId('periodEnd').value;
      if (!periodStart || !periodEnd) return;
      try {
        const params = new URLSearchParams({ periodStart, periodEnd });
        const payload = await api(`${SUBJECTS_ENDPOINT}?${params.toString()}`);
        if (requestSequence !== subjectRequestSequence) return;
        const subjects = Array.isArray(payload.subjects) ? payload.subjects : [];
        if (payload.source === 'recent-beisen-runs') {
          byId('retrySubjectsButton').hidden = true;
          byId('subjectSourceState').textContent = `已先加载 ${subjects.length} 个最近同步主体；后台正在补齐完整主体…`;
          scheduleContractSubjectCompletion(preferredValue, requestSequence, attempt + 1);
          return;
        }
        if (!subjects.length) return;
        applyContractSubjects(subjects, preferredValue);
        state.subjectsReady = true;
        byId('subject').disabled = false;
        syncSubjectPicker();
        byId('syncButton').disabled = false;
        byId('retrySubjectsButton').hidden = true;
        byId('subjectSourceState').textContent = payload.source === 'beisen-contract-cache'
          ? `已从后台缓存自动补齐 ${subjects.length} 个主体；不包含员工明细`
          : `已从北森合同接口加载 ${subjects.length} 个主体；不包含员工明细`;
        renderRun();
        loadSelectedSubjectRun({ silent: true });
      } catch {
        if (requestSequence === subjectRequestSequence) {
          scheduleContractSubjectCompletion(preferredValue, requestSequence, attempt + 1);
        }
      }
    }, attempt === 0 ? 1500 : 3000);
  }

  async function loadContractSubjects(preferredValue = '', requestSequence = ++subjectRequestSequence, forceRefresh = false) {
    if (state.operation) return;
    const periodStart = byId('periodStart').value;
    const periodEnd = byId('periodEnd').value;
    if (!periodStart || !periodEnd) return;
    subjectAbortController?.abort();
    subjectAbortController = new AbortController();
    state.subjectLoading = true;
    state.subjectsReady = false;
    const select = byId('subject');
    const retry = byId('retrySubjectsButton');
    const syncButton = byId('syncButton');
    const sourceState = byId('subjectSourceState');
    retry.disabled = true;
    retry.hidden = true;
    select.disabled = true;
    syncButton.disabled = true;
    select.replaceChildren();
    const loadingOption = document.createElement('option');
    loadingOption.value = '';
    loadingOption.textContent = '正在加载当前周期合同主体…';
    select.append(loadingOption);
    syncSubjectPicker();
    sourceState.textContent = '正在读取本周期候选人员的当前有效合同…';
    try {
      const params = new URLSearchParams({ periodStart, periodEnd });
      if (forceRefresh) params.set('refresh', 'true');
      const payload = await api(`${SUBJECTS_ENDPOINT}?${params.toString()}`, { signal: subjectAbortController.signal });
      if (requestSequence !== subjectRequestSequence) return;
      const subjects = Array.isArray(payload.subjects) ? payload.subjects : [];
      applyContractSubjects(subjects, preferredValue);
      if (!subjects.length) {
        const option = document.createElement('option');
        option.value = '';
        option.textContent = '本周期没有可用合同主体';
        select.append(option);
        sourceState.textContent = '北森未返回本周期全国增员候选的合同主体';
        retry.hidden = false;
        syncSubjectPicker();
        return;
      }
      state.subjectsReady = true;
      select.disabled = false;
      syncSubjectPicker();
      syncButton.disabled = false;
      retry.hidden = true;
      if (payload.source === 'recent-beisen-runs') {
        sourceState.textContent = `已先加载 ${subjects.length} 个最近同步主体；后台正在补齐完整主体…`;
        scheduleContractSubjectCompletion(select.value || preferredValue, requestSequence);
      } else {
        sourceState.textContent = payload.source === 'beisen-contract-cache'
          ? `已从后台缓存加载 ${subjects.length} 个主体；不包含员工明细`
          : `已从北森合同接口加载 ${subjects.length} 个主体；不包含员工明细`;
      }
      if (payload.refreshWarning) {
        sourceState.textContent = `${payload.refreshWarning}（${subjects.length} 个主体可继续使用）`;
        showToast(payload.refreshWarning, 'error');
      }
      await loadSelectedSubjectRun({ silent: true });
    } catch (error) {
      if (error.name === 'AbortError' || requestSequence !== subjectRequestSequence) return;
      select.replaceChildren();
      const option = document.createElement('option');
      option.value = '';
      option.textContent = '合同主体加载失败，请重试';
      select.append(option);
      sourceState.textContent = error.message;
      retry.hidden = false;
      syncSubjectPicker();
      showToast(error.message, 'error');
    } finally {
      if (requestSequence === subjectRequestSequence) {
        state.subjectLoading = false;
        retry.disabled = false;
      }
    }
  }

  function scheduleContractSubjectLoad(preferredValue = '', delay = 280, forceRefresh = false) {
    window.clearTimeout(subjectLoadTimer);
    window.clearTimeout(subjectCompletionTimer);
    const requestSequence = ++subjectRequestSequence;
    subjectAbortController?.abort();
    state.subjectsReady = false;
    state.subjectLoading = false;
    const select = byId('subject');
    const retry = byId('retrySubjectsButton');
    const sourceState = byId('subjectSourceState');
    const periodStart = byId('periodStart').value;
    const periodEnd = byId('periodEnd').value;
    select.disabled = true;
    closeSubjectPicker();
    byId('syncButton').disabled = true;
    renderRun();
    if (!periodStart || !periodEnd || periodStart > periodEnd) {
      select.replaceChildren();
      const option = document.createElement('option');
      option.value = '';
      option.textContent = '请先完成有效的增员周期';
      select.append(option);
      sourceState.textContent = '开始日期不能晚于结束日期，请继续选择结束日期';
      retry.hidden = true;
      retry.disabled = false;
      syncSubjectPicker();
      return;
    }
    select.replaceChildren();
    const option = document.createElement('option');
    option.value = '';
    option.textContent = '正在加载当前周期合同主体…';
    select.append(option);
    syncSubjectPicker();
    sourceState.textContent = '正在读取本周期候选人员的当前有效合同，请稍候…';
    retry.hidden = true;
    retry.disabled = true;
    subjectLoadTimer = window.setTimeout(() => loadContractSubjects(preferredValue, requestSequence, forceRefresh), delay);
  }

  async function loadFieldMetadata() {
    const payload = await api(METADATA_ENDPOINT);
    if (!Array.isArray(payload.fields) || !Array.isArray(payload.schemas) || !Array.isArray(payload.administrativeDivisions)) {
      throw new Error('政务模板字段字典格式无效');
    }
    state.fieldDefinitions = payload.fields;
    state.schemaDefinitions = payload.schemas;
    state.administrativeDivisions = payload.administrativeDivisions;
    state.administrativeDivisionChoices = Array.isArray(payload.administrativeDivisionChoices)
      ? payload.administrativeDivisionChoices
      : payload.administrativeDivisions.map((value) => ({ value, context: '', searchText: value }));
    state.administrativeDivisionSet = new Set(payload.administrativeDivisions);
    syncTemplateRouteSelectors();
  }

  function createSearchableCombobox(field, currentValue) {
    const root = document.createElement('div');
    root.className = 'combobox-shell';
    const listId = `administrativeDivisionList-${++comboboxSequence}`;

    const input = document.createElement('input');
    input.type = 'text';
    input.name = field.name;
    input.value = currentValue || '';
    input.placeholder = '输入区县名称或6位代码搜索';
    input.autocomplete = 'off';
    input.dataset.control = field.control;
    input.setAttribute('role', 'combobox');
    input.setAttribute('aria-autocomplete', 'list');
    input.setAttribute('aria-controls', listId);
    input.setAttribute('aria-expanded', 'false');

    const toggle = textNode('button', 'combobox-toggle', '⌄');
    toggle.type = 'button';
    toggle.setAttribute('aria-label', '展开行政区划选项');
    toggle.tabIndex = -1;

    const menu = document.createElement('div');
    menu.className = 'combobox-menu';
    menu.hidden = true;
    const list = document.createElement('div');
    list.id = listId;
    list.className = 'combobox-options';
    list.setAttribute('role', 'listbox');
    const meta = textNode('div', 'combobox-meta', '输入代码或区县名称筛选');
    menu.append(list, meta);
    root.append(input, toggle, menu);

    let visibleChoices = [];
    let activeIndex = -1;

    function closeMenu() {
      menu.hidden = true;
      input.setAttribute('aria-expanded', 'false');
      input.removeAttribute('aria-activedescendant');
      activeIndex = -1;
    }

    function choose(value) {
      input.value = value;
      input.dispatchEvent(new Event('change', { bubbles: true }));
      closeMenu();
      input.focus();
    }

    function setActive(index) {
      const options = [...list.querySelectorAll('[role="option"]')];
      if (!options.length) return;
      activeIndex = Math.max(0, Math.min(index, options.length - 1));
      options.forEach((option, optionIndex) => option.classList.toggle('active', optionIndex === activeIndex));
      const active = options[activeIndex];
      input.setAttribute('aria-activedescendant', active.id);
      active.scrollIntoView({ block: 'nearest' });
    }

    function renderOptions(query = '') {
      const normalized = query.trim().toLowerCase();
      const matched = normalized
        ? state.administrativeDivisionChoices.filter((choice) => String(choice.searchText || choice.value).toLowerCase().includes(normalized))
        : state.administrativeDivisionChoices;
      visibleChoices = matched.slice(0, 60);
      activeIndex = -1;
      list.replaceChildren();
      if (!visibleChoices.length) {
        list.append(textNode('div', 'combobox-empty', '没有匹配的模板行政区划'));
      } else {
        const fragment = document.createDocumentFragment();
        visibleChoices.forEach((choice, index) => {
          const option = document.createElement('button');
          option.className = 'combobox-option';
          option.type = 'button';
          option.id = `${listId}-option-${index}`;
          option.setAttribute('role', 'option');
          option.setAttribute('aria-selected', String(choice.value === input.value));
          option.append(textNode('b', '', choice.value));
          if (choice.context) option.append(textNode('small', '', choice.context));
          option.addEventListener('click', () => choose(choice.value));
          fragment.append(option);
        });
        list.append(fragment);
      }
      const remainder = matched.length - visibleChoices.length;
      meta.textContent = remainder > 0 ? `显示前60项，继续输入可缩小范围（另有${remainder}项）` : `找到${matched.length}项`;
    }

    function openMenu(showAll = false) {
      renderOptions(showAll ? '' : input.value);
      menu.hidden = false;
      input.setAttribute('aria-expanded', 'true');
    }

    input.addEventListener('focus', () => openMenu(true));
    input.addEventListener('input', () => openMenu(false));
    input.addEventListener('keydown', (event) => {
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        if (menu.hidden) openMenu(true);
        setActive(activeIndex + 1);
      } else if (event.key === 'ArrowUp') {
        event.preventDefault();
        if (menu.hidden) openMenu(true);
        setActive(activeIndex < 0 ? visibleChoices.length - 1 : activeIndex - 1);
      } else if (event.key === 'Enter' && activeIndex >= 0) {
        event.preventDefault();
        choose(visibleChoices[activeIndex].value);
      } else if (event.key === 'Escape') {
        closeMenu();
      }
    });
    toggle.addEventListener('click', () => {
      if (menu.hidden) { openMenu(true); input.focus(); }
      else closeMenu();
    });
    root.addEventListener('focusout', () => {
      window.setTimeout(() => { if (!root.contains(document.activeElement)) closeMenu(); }, 0);
    });
    return root;
  }

  function dateInputValue(value) {
    const text = String(value || '').trim();
    if (/^\d{4}-\d{2}-\d{2}$/.test(text)) return text;
    const match = text.match(/^(\d{4})(\d{2})(\d{2})$/);
    return match ? `${match[1]}-${match[2]}-${match[3]}` : '';
  }

  function createFieldControl(field, currentValue) {
    let input;
    if (field.control === 'adminDivision') return createSearchableCombobox(field, currentValue);
    if (field.control === 'select') {
      input = document.createElement('select');
      const blank = document.createElement('option');
      blank.value = ''; blank.textContent = '请选择';
      input.append(blank);
      (field.options || []).forEach((value) => {
        const option = document.createElement('option');
        option.value = value; option.textContent = value;
        input.append(option);
      });
      if (currentValue && !(field.options || []).includes(currentValue)) {
        const legacy = document.createElement('option');
        legacy.value = currentValue; legacy.textContent = `${currentValue}（非当前模板枚举）`;
        input.append(legacy);
      }
      input.value = currentValue || '';
    } else {
      input = document.createElement('input');
      if (field.control === 'date') {
        input.type = 'date';
        input.value = dateInputValue(currentValue);
      } else {
        input.type = 'text';
        input.value = currentValue || '';
      }
      if (field.name === '手机号码' || field.name === '电脑号') input.inputMode = 'numeric';
    }
    input.name = field.name;
    input.autocomplete = 'off';
    input.dataset.control = field.control;
    return input;
  }

  async function quickDecision(employee, checkbox) {
    checkbox.disabled = true;
    try {
      state.run = await api(`${API_ROOT}/runs/${state.run.id}/employees/${employee.id}`, {
        method: 'PATCH', body: JSON.stringify({ decision: checkbox.checked ? 'include' : 'exclude' }),
      });
      renderRun(); showToast(checkbox.checked ? '已纳入本批报盘' : '已从本批报盘排除');
    } catch (error) { checkbox.checked = !checkbox.checked; showToast(error.message, 'error'); }
    finally { checkbox.disabled = false; }
  }

  function drawerFieldDefinitions(employee) {
    if (!state.editingRoute) return state.fieldDefinitions;
    return schemaForRoute(state.editingRoute)?.fields || [];
  }

  function drawerReport(employee) {
    if (!state.editingRoute) return employee.report || {};
    return employee.templateReports?.[state.editingRoute]?.values || {};
  }

  function originClass(origin) {
    if (origin === '人工修改') return 'manual';
    if (origin === '待补充') return 'missing';
    if (origin?.includes('规则') || origin?.includes('解析') || origin?.includes('常量')) return 'rule';
    return 'source';
  }

  function renderDrawerAlert(employee) {
    const alert = byId('drawerAlert');
    const issues = employee.issues || [];
    const supplementContext = employee.supplemental
      ? `${employee.supplemental.label}说明：${employee.supplemental.note}`
      : '';
    const templateReport = state.editingRoute ? employee.templateReports?.[state.editingRoute] : null;
    const missingContext = templateReport?.missingRequired?.length
      ? `${templateReport.label}缺少必填项：${templateReport.missingRequired.join('、')}`
      : '';
    const messages = [
      missingContext,
      supplementContext,
      ...issues.map((item) => `${item.severity === 'info' ? '提示' : '待确认'}：${item.message}`),
    ].filter(Boolean);
    alert.hidden = messages.length === 0;
    alert.textContent = messages.join('；');
  }

  function renderDrawerTemplateFields(employee) {
    const tabs = byId('drawerRouteTabs');
    const fields = byId('reportFields');
    tabs.replaceChildren();
    fields.replaceChildren();
    const routes = Object.keys(employee.templateReports || {});
    if (routes.length && !routes.includes(state.editingRoute)) {
      state.editingRoute = routes.find((route) => employee.templateReports[route]?.missingRequired?.length) || routes[0];
    }
    tabs.hidden = routes.length === 0;
    routes.forEach((route) => {
      const report = employee.templateReports[route] || {};
      const button = document.createElement('button');
      button.type = 'button';
      button.className = route === state.editingRoute ? 'active' : '';
      button.setAttribute('role', 'tab');
      button.setAttribute('aria-selected', String(route === state.editingRoute));
      button.append(
        textNode('b', '', report.label || schemaForRoute(route)?.label || route),
        textNode('small', '', report.missingRequired?.length ? `缺少${report.missingRequired.length}项` : '字段已齐全'),
      );
      button.addEventListener('click', () => {
        state.editingRoute = route;
        renderDrawerTemplateFields(employee);
        renderDrawerAlert(employee);
      });
      tabs.append(button);
    });

    const definitions = drawerFieldDefinitions(employee);
    const report = drawerReport(employee);
    const routeReport = state.editingRoute ? employee.templateReports?.[state.editingRoute] : null;
    definitions.forEach((field) => {
      const label = document.createElement('label');
      const missing = Boolean(routeReport?.missingRequired?.includes(field.name));
      if (WIDE_FIELDS.has(field.name) || field.control === 'adminDivision') label.classList.add('wide');
      if (missing) label.classList.add('missing-required-field');
      const title = textNode('span', 'field-label', field.name);
      const origin = routeReport?.origins?.[field.name] || (report[field.name] ? '北森/规则映射' : '待补充');
      title.append(textNode('em', `field-origin ${originClass(origin)}`, origin));
      if (field.required) title.append(textNode('b', 'required-mark', '必填'));
      const input = createFieldControl(field, report[field.name] || '');
      const notes = [field.note || '', missing ? '当前缺失，需在生成该路径前补齐' : ''].filter(Boolean).join('；');
      label.append(title, input, textNode('small', 'field-note', notes));
      fields.append(label);
    });
    if (!definitions.length) fields.append(textNode('p', 'drawer-empty-fields', '当前人员没有需要填写的政务模板字段。'));
  }

  function openDrawer(employeeId) {
    const employee = state.run?.employees.find((item) => item.id === employeeId);
    if (!employee) return;
    if (!state.fieldDefinitions.length || !state.schemaDefinitions.length) {
      showToast('政务模板字段字典尚未加载，请刷新页面后重试', 'error');
      return;
    }
    state.editingId = employeeId;
    const routes = Object.keys(employee.templateReports || {});
    state.editingRoute = routes.find((route) => employee.templateReports[route]?.missingRequired?.length) || routes[0] || '';
    byId('drawerTitle').textContent = `${employee.report['姓名'] || '人员'} · 信息确认`;
    byId('drawerIdentity').textContent = `${employee.maskedId || '证件号缺失'} · 入职 ${employee.entryDate || '—'}`;
    const coverageSummary = byId('coverageTaskSummary');
    coverageSummary.replaceChildren();
    ['social', 'medical', 'housing'].forEach((coverage) => {
      const task = employee.coverageTasks?.[coverage] || {};
      const card = document.createElement('article');
      card.dataset.status = task.status || 'needs_review';
      const heading = document.createElement('header');
      heading.append(textNode('b', '', task.label || ({ social: '社保', medical: '医保', housing: '公积金' }[coverage])), textNode('span', '', task.statusLabel || '待确认'));
      card.append(
        heading,
        textNode('strong', '', task.routeLabel || '办理去向待确认'),
        textNode('p', '', task.reason || '等待业务确认'),
      );
      coverageSummary.append(card);
    });
    renderDrawerTemplateFields(employee);
    byId('employeeDecision').value = employee.decision;
    byId('employeeConfirmed').checked = Boolean(employee.confirmed);
    byId('employeeNote').value = employee.reviewNote || '';
    renderDrawerAlert(employee);
    byId('drawerBackdrop').hidden = false;
    byId('editDrawer').classList.add('open'); byId('editDrawer').setAttribute('aria-hidden', 'false');
  }

  function closeDrawer() {
    state.editingId = null; state.editingRoute = ''; byId('editDrawer').classList.remove('open'); byId('editDrawer').setAttribute('aria-hidden', 'true');
    window.setTimeout(() => { byId('drawerBackdrop').hidden = true; }, 220);
  }

  async function saveEmployee(event) {
    event.preventDefault();
    if (!state.editingId || !state.run) return;
    const submit = event.submitter; submit.disabled = true;
    const employee = state.run.employees.find((item) => item.id === state.editingId);
    if (!employee) return;
    const report = {};
    const definitions = drawerFieldDefinitions(employee);
    const knownFields = new Set(definitions.map((field) => field.name));
    new FormData(event.currentTarget).forEach((value, key) => {
      if (!knownFields.has(key)) return;
      report[key] = value;
    });
    const adminField = definitions.find((field) => field.control === 'adminDivision');
    const adminValue = String(adminField ? report[adminField.name] || '' : '');
    if (adminField && adminValue && !state.administrativeDivisionSet.has(adminValue)) {
      submit.disabled = false;
      showToast('户口所在地行政区划代码必须从政务模板区县字典选择', 'error');
      event.currentTarget.elements.namedItem(adminField.name)?.focus();
      return;
    }
    const payload = {
      decision: byId('employeeDecision').value,
      confirmed: byId('employeeConfirmed').checked,
      reviewNote: byId('employeeNote').value,
    };
    if (state.editingRoute) {
      payload.templateRoute = state.editingRoute;
      payload.templateReport = report;
    } else {
      payload.report = Object.fromEntries(Object.entries(report).map(([key, value]) => {
        const definition = definitions.find((field) => field.name === key);
        return [key, definition?.control === 'date' ? String(value).replaceAll('-', '') : value];
      }));
    }
    try {
      state.run = await api(`${API_ROOT}/runs/${state.run.id}/employees/${state.editingId}`, {
        method: 'PATCH', body: JSON.stringify(payload),
      });
      closeDrawer(); renderRun(); showToast('人员信息已保存到当前批次');
    } catch (error) { showToast(error.message, 'error'); }
    finally { submit.disabled = false; }
  }

  function updateSupplementSubmitState() {
    byId('addSupplementButton').disabled = !state.supplementCandidate || byId('supplementNote').value.trim().length < 4 || Boolean(state.operation);
  }

  function renderSupplementResults(candidates = null) {
    const holder = byId('supplementResults');
    holder.setAttribute('aria-busy', 'false');
    holder.replaceChildren();
    if (candidates === null) {
      const empty = document.createElement('div'); empty.className = 'supplement-empty';
      empty.append(textNode('b', '', '尚未查找'), textNode('span', '', '人员资料直接从北森带出，不需要重复手填。'));
      holder.append(empty); return;
    }
    if (!candidates.length) {
      const empty = document.createElement('div'); empty.className = 'supplement-empty';
      empty.append(textNode('b', '', '没有找到可补充人员'), textNode('span', '', '请检查姓名或证件号后四位；当前批次已有人员不会重复显示。'));
      holder.append(empty); return;
    }
    candidates.forEach((candidate) => {
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'supplement-result';
      const main = document.createElement('span');
      main.append(textNode('b', '', candidate.name || '未命名'), textNode('small', '', `${candidate.maskedId || '证件号缺失'} · 入职 ${candidate.entryDate || '—'}`));
      const meta = document.createElement('span');
      const sourceLabel = candidate.lookupSource === 'recent-beisen-run' ? '最近北森同步记录' : '北森候选池';
      meta.append(textNode('b', '', candidate.validation || '字段待核对'), textNode('small', '', `${sourceLabel} · ${candidate.place || '地点未知'} · ${candidate.employType || '雇佣关系未知'}`));
      button.append(main, meta);
      button.addEventListener('click', () => {
        state.supplementCandidate = candidate;
        holder.querySelectorAll('.supplement-result').forEach((node) => node.classList.toggle('selected', node === button));
        updateSupplementSubmitState();
      });
      holder.append(button);
    });
  }

  function renderSupplementStatus(title, message, type = '') {
    const holder = byId('supplementResults');
    holder.setAttribute('aria-busy', String(type === 'loading'));
    holder.replaceChildren();
    const status = document.createElement('div');
    status.className = `supplement-empty ${type}`.trim();
    if (type === 'loading') status.append(textNode('span', 'supplement-search-spinner', ''));
    status.append(textNode('b', '', title), textNode('span', '', message));
    holder.append(status);
  }

  function openSupplementDialog() {
    if (!state.run || !selectionMatchesRun()) {
      showToast('请先同步并打开当前批次', 'error'); return;
    }
    state.supplementCandidate = null;
    byId('supplementQuery').value = '';
    byId('supplementReason').value = 'prior_period_omission';
    byId('supplementNote').value = '';
    renderSupplementResults(); updateSupplementSubmitState();
    byId('supplementBackdrop').hidden = false;
    byId('supplementDialog').hidden = false;
    loadSupplementPoolStatus();
    window.setTimeout(() => byId('supplementQuery').focus(), 0);
  }

  function closeSupplementDialog() {
    if (state.operation === 'supplement-search' || state.operation === 'supplement-add') return;
    window.clearTimeout(supplementPoolStatusTimer);
    state.supplementCandidate = null;
    byId('supplementDialog').hidden = true;
    byId('supplementBackdrop').hidden = true;
  }

  async function searchSupplementCandidates() {
    if (!state.run || state.operation) return;
    const query = byId('supplementQuery').value.trim();
    if (query.length < 2) {
      showToast('请输入至少2个字符的姓名或证件号后四位', 'error'); return;
    }
    state.operation = 'supplement-search'; state.supplementCandidate = null;
    const button = byId('searchSupplementButton');
    button.disabled = true; button.textContent = '正在查找…'; updateSupplementSubmitState();
    renderSupplementStatus('正在查找人员', '优先查找平台最近的北森同步记录；未命中时再检查北森候选池。', 'loading');
    try {
      const payload = await api(`${API_ROOT}/runs/${state.run.id}/supplement-candidates/search`, {
        method: 'POST', body: JSON.stringify({ query }),
      });
      renderSupplementResults(payload.candidates || []);
      loadSupplementPoolStatus();
    } catch (error) {
      const message = error instanceof TypeError
        ? '无法连接 HRAS 本地服务，请刷新页面后重试'
        : error.message;
      renderSupplementStatus('查找失败，请重试', message, 'error');
      showToast(message, 'error');
    } finally {
      state.operation = null; button.disabled = false; button.textContent = '查找'; updateSupplementSubmitState(); renderActions();
    }
  }

  async function addSupplementEmployee(event) {
    event.preventDefault();
    if (!state.run || !state.supplementCandidate || state.operation) return;
    const note = byId('supplementNote').value.trim();
    if (note.length < 4) {
      showToast('请填写至少4个字的情况说明', 'error'); return;
    }
    state.operation = 'supplement-add'; updateSupplementSubmitState();
    try {
      state.run = await api(`${API_ROOT}/runs/${state.run.id}/supplements`, {
        method: 'POST',
        body: JSON.stringify({
          candidateId: state.supplementCandidate.id,
          reasonType: byId('supplementReason').value,
          note,
        }),
      });
      const added = [...state.run.employees].reverse().find((employee) => employee.supplemental && !employee.confirmed);
      state.operation = null; closeSupplementDialog(); renderRun();
      showToast('补充人员已加入当前批次，请复核报盘字段并人工确认');
      if (added) openDrawer(added.id);
    } catch (error) {
      state.operation = null; showToast(error.message, 'error'); updateSupplementSubmitState(); renderActions();
    }
  }

  async function syncRun() {
    if (state.operation) return;
    if (!state.subjectsReady || !byId('subject').value) {
      showToast('请等待系统自动加载合同主体后再生成名单', 'error');
      return;
    }
    state.operation = 'sync';
    const button = byId('syncButton'); setBusy(button, true, '正在生成全部主体批次');
    try {
      const payload = await api(SYNC_ALL_ENDPOINT, {
        method: 'POST',
        body: JSON.stringify(selectedBatchContext()),
      });
      (payload.runs || []).forEach(indexRun);
      state.run = payload.selectedRun;
      indexRun(state.run);
      state.filter = 'all'; state.search = ''; byId('employeeSearch').value = '';
      document.querySelectorAll('.filter-tabs button').forEach((node) => node.classList.toggle('active', node.dataset.filter === 'all'));
      const generationSource = state.run?.sourceSummary?.dataMode === 'background-all-subject-snapshot'
        ? '使用定时快照生成'
        : '实时同步北森并生成';
      renderRun(); showToast(`${generationSource} ${payload.batchCount} 个主体批次；当前批次 ${state.run.summary.total} 人`);
    } catch (error) { showToast(error.message, 'error'); }
    finally { state.operation = null; setBusy(button, false); renderActions(); }
  }

  async function confirmBatch() {
    if (!state.run || state.operation) return;
    state.operation = 'confirm';
    const button = byId('confirmBatchButton'); button.disabled = true;
    try {
      state.run = await api(`${API_ROOT}/runs/${state.run.id}/confirm`, { method: 'POST' });
      renderRun(); showToast('本批人员已确认，正在按办理路径校验模板与必填资料');
    } catch (error) { showToast(error.message, 'error'); }
    finally { state.operation = null; renderActions(); }
  }

  async function uploadTemplate(file) {
    if (!file || !state.run || state.operation) return;
    const extension = file.name.toLowerCase().split('.').pop();
    if (!['xls', 'xlsx'].includes(extension)) {
      showToast('政务模板仅支持 .xls 或 .xlsx 文件', 'error');
      return;
    }
    if (file.size > 20 * 1024 * 1024) {
      showToast('政务模板不能超过 20MB', 'error');
      return;
    }
    const route = byId('templateUploadRoute').value || state.templateRoute;
    if (!route) {
      showToast('当前批次没有可上传的政务模板路径', 'error');
      return;
    }
    state.operation = 'template';
    const form = new FormData(); form.append('file', file);
    const dropzone = byId('templateDropzone');
    dropzone.classList.add('loading');
    dropzone.setAttribute('aria-busy', 'true');
    dropzone.querySelector('.dropzone-copy b').textContent = '正在校验政务模板';
    try {
      const params = new URLSearchParams({ route });
      state.run = await api(`${API_ROOT}/runs/${state.run.id}/template?${params.toString()}`, { method: 'POST', body: form });
      state.preflightKey = '';
      renderRun(); showToast(`${schemaForRoute(route)?.label || '政务模板'}已导入；生成时会再次校验表头`);
    } catch (error) { showToast(error.message, 'error'); }
    finally {
      state.operation = null;
      dropzone.classList.remove('loading');
      dropzone.removeAttribute('aria-busy');
      dropzone.querySelector('.dropzone-copy b').textContent = uploadedTemplateForRoute(state.run, route) ? '更换当前路径模板' : '手动上传当前版本';
      renderActions();
      byId('templateInput').value = '';
    }
  }

  function bindTemplateDropzone() {
    const dropzone = byId('templateDropzone');
    const input = byId('templateInput');
    let dragDepth = 0;
    const isAvailable = () => dropzone.getAttribute('aria-disabled') !== 'true' && !state.operation;
    const openPicker = () => {
      if (!isAvailable()) {
        showToast('请先确认本批人员，再导入政务模板', 'error');
        return;
      }
      input.click();
    };

    dropzone.addEventListener('click', openPicker);
    dropzone.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        openPicker();
      }
    });
    dropzone.addEventListener('dragenter', (event) => {
      event.preventDefault();
      dragDepth += 1;
      if (isAvailable()) dropzone.classList.add('dragging');
    });
    dropzone.addEventListener('dragover', (event) => {
      event.preventDefault();
      if (isAvailable() && event.dataTransfer) event.dataTransfer.dropEffect = 'copy';
    });
    dropzone.addEventListener('dragleave', () => {
      dragDepth = Math.max(0, dragDepth - 1);
      if (dragDepth === 0) dropzone.classList.remove('dragging');
    });
    dropzone.addEventListener('drop', (event) => {
      event.preventDefault();
      dragDepth = 0;
      dropzone.classList.remove('dragging');
      if (!isAvailable()) {
        showToast('请先确认本批人员，再导入政务模板', 'error');
        return;
      }
      uploadTemplate(event.dataTransfer?.files?.[0]);
    });
  }

  async function generateReport() {
    if (!state.run || state.operation) return;
    state.operation = 'generate';
    const button = byId('generateButton'); setBusy(button, true, '正在生成政务报盘包');
    const syncButton = byId('syncButton'); syncButton.disabled = true;
    try {
      state.run = await api(`${API_ROOT}/runs/${state.run.id}/generate-package`, { method: 'POST' });
      state.preflightKey = '';
      renderRun();
      const packageResult = state.run.reportPackage || {};
      const generatedCount = packageResult.generatedRoutes?.length || 0;
      const blockedCount = packageResult.blockedRoutes?.length || 0;
      showToast(blockedCount
        ? `已生成 ${generatedCount} 条就绪路径，另有 ${blockedCount} 条路径随待补资料一并说明`
        : `政务报盘包已生成，共 ${generatedCount} 条办理路径；请下载复核`);
    } catch (error) { showToast(error.message, 'error'); }
    finally {
      state.operation = null;
      syncButton.disabled = !state.subjectsReady;
      setBusy(button, false);
      renderActions();
    }
  }

  function downloadAuditExport() {
    if (!state.run || state.operation) return;
    const runId = encodeURIComponent(state.run.id);
    window.location.assign(`${API_ROOT}/runs/${runId}/audit-export`);
  }

  function downloadMissingExport() {
    if (!state.run || state.operation) return;
    const runId = encodeURIComponent(state.run.id);
    window.location.assign(`${API_ROOT}/runs/${runId}/missing-export`);
  }

  function bindEvents() {
    bindDatePickers();
    bindSubjectPicker();
    bindTableHorizontalControl();
    byId('syncButton').addEventListener('click', syncRun);
    byId('retrySubjectsButton').addEventListener('click', () => scheduleContractSubjectLoad(byId('subject').value, 0, true));
    byId('periodStart').addEventListener('change', () => scheduleContractSubjectLoad());
    byId('periodEnd').addEventListener('change', () => scheduleContractSubjectLoad());
    byId('confirmationDate').addEventListener('change', () => { renderRun(); loadSelectedSubjectRun(); });
    byId('subject').addEventListener('change', () => { syncSubjectPicker(); renderRun(); loadSelectedSubjectRun(); });
    byId('openSupplementButton').addEventListener('click', openSupplementDialog);
    byId('closeSupplementButton').addEventListener('click', closeSupplementDialog);
    byId('cancelSupplementButton').addEventListener('click', closeSupplementDialog);
    byId('supplementBackdrop').addEventListener('click', closeSupplementDialog);
    byId('searchSupplementButton').addEventListener('click', searchSupplementCandidates);
    byId('supplementQuery').addEventListener('keydown', (event) => { if (event.key === 'Enter') { event.preventDefault(); searchSupplementCandidates(); } });
    byId('supplementNote').addEventListener('input', updateSupplementSubmitState);
    byId('supplementForm').addEventListener('submit', addSupplementEmployee);
    byId('auditExportButton').addEventListener('click', downloadAuditExport);
    byId('missingExportButton').addEventListener('click', downloadMissingExport);
    byId('confirmBatchButton').addEventListener('click', confirmBatch);
    byId('employeeSearch').addEventListener('input', (event) => { state.search = event.target.value; renderTable(); });
    document.querySelectorAll('.filter-tabs button').forEach((button) => button.addEventListener('click', () => {
      state.filter = button.dataset.filter;
      document.querySelectorAll('.filter-tabs button').forEach((node) => node.classList.toggle('active', node === button)); renderTable();
    }));
    document.querySelectorAll('.review-view-switch button').forEach((button) => button.addEventListener('click', () => {
      state.view = button.dataset.view || 'business';
      document.querySelectorAll('.review-view-switch button').forEach((node) => node.classList.toggle('active', node === button));
      syncTemplateRouteSelectors();
      renderTable();
    }));
    byId('templateRouteSelect').addEventListener('change', (event) => {
      state.templateRoute = event.target.value;
      renderTable();
    });
    byId('templateUploadRoute').addEventListener('change', () => {
      renderPreflight();
      renderActions();
    });
    byId('closeDrawerButton').addEventListener('click', closeDrawer);
    byId('cancelEditButton').addEventListener('click', closeDrawer);
    byId('drawerBackdrop').addEventListener('click', closeDrawer);
    byId('employeeForm').addEventListener('submit', saveEmployee);
    bindTemplateDropzone();
    byId('templateInput').addEventListener('change', (event) => uploadTemplate(event.target.files?.[0]));
    byId('generateButton').addEventListener('click', generateReport);
    document.addEventListener('keydown', (event) => { if (event.key === 'Escape') { closeSubjectPicker(); closeDatePicker(); closeDrawer(); closeSupplementDialog(); } });
  }

  async function initialize() {
    bindEvents();
    try {
      const config = await api(`${API_ROOT}/config`);
      byId('periodStart').value = config.periodStart;
      byId('periodEnd').value = config.periodEnd;
      byId('confirmationDate').value = config.confirmationDate;
      renderDatePickerValues();
      const recent = await api(`${API_ROOT}/runs?limit=1`);
      if (recent.runs?.[0]) {
        state.run = await api(`${RUN_ENDPOINT_PREFIX}${recent.runs[0].id}`);
        indexRun(state.run);
        renderRun();
      }
      await Promise.all([loadContractSubjects(state.run?.subject || config.defaultSubject), loadFieldMetadata()]);
      renderRun();
    } catch (error) { showToast(error.message, 'error'); }
  }

  initialize();
})();
