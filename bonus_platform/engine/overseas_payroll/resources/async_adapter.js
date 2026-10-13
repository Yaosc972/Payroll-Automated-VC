(function () {
  'use strict';

  document.getElementById('sidefoot')?.remove();
  document.getElementById('hostwarn')?.remove();

  const moduleHomeUrl = '/overseas-compensation.html';
  const brand = document.querySelector('.sidebar .brand');
  if (brand) {
    const integrationStyle = document.createElement('style');
    integrationStyle.textContent = '.sidebar .brand[role="link"]:focus-visible{outline:2px solid #2563eb;outline-offset:-2px;border-radius:10px}';
    document.head.appendChild(integrationStyle);
    brand.setAttribute('role', 'link');
    brand.setAttribute('tabindex', '0');
    brand.setAttribute('aria-label', '返回海外薪酬核算页面');
    brand.setAttribute('title', '返回海外薪酬核算页面');
    brand.style.cursor = 'pointer';
    brand.addEventListener('click', () => { window.location.href = moduleHomeUrl; });
    brand.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        window.location.href = moduleHomeUrl;
      }
    });
  }

  function renderFeishuAvatar(user) {
    const avatar = document.getElementById('avatar');
    if (!avatar || !user) return;
    const fallback = String(user.name || user.email || 'U').trim().charAt(0) || 'U';
    const avatarUrl = String(user.avatarUrl || '').trim();
    avatar.replaceChildren();
    avatar.style.overflow = 'hidden';
    if (!avatarUrl.startsWith('https://')) {
      avatar.textContent = fallback;
      return;
    }
    const image = document.createElement('img');
    image.src = avatarUrl;
    image.alt = (user.name || '飞书用户') + '的头像';
    image.referrerPolicy = 'no-referrer';
    image.style.width = '100%';
    image.style.height = '100%';
    image.style.objectFit = 'cover';
    image.addEventListener('error', () => {
      avatar.replaceChildren();
      avatar.textContent = fallback;
    }, { once: true });
    avatar.appendChild(image);
  }

  if (typeof renderBar === 'function') {
    const originalRenderBar = renderBar;
    renderBar = function (user) {
      const previousId = CURRENT_USER && CURRENT_USER.id;
      if (previousId !== (user && user.id)) {
        restoreGeneration += 1;
        document.getElementById('log')?.replaceChildren();
        resetPreparation();
      }
      originalRenderBar(user);
      renderFeishuAvatar(user);
    };
  }

  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const taskHistoryPrefix = 'wb_payroll_async_tasks_v2:';
  const taskHistoryMax = 25;
  let restoreGeneration = 0;

  function historyKey() {
    return CURRENT_USER && CURRENT_USER.id
      ? taskHistoryPrefix + encodeURIComponent(CURRENT_USER.id) : '';
  }

  function getTaskHistory(key = historyKey()) {
    if (!key) return [];
    try {
      const value = JSON.parse(localStorage.getItem(key) || '[]');
      return Array.isArray(value) ? value.filter(item => item && item.id && item.toolId) : [];
    } catch (_) {
      return [];
    }
  }

  function saveTaskHistory(items, key = historyKey()) {
    if (!key) return;
    try {
      localStorage.setItem(key, JSON.stringify(items.slice(0, taskHistoryMax)));
    } catch (_) {}
  }

  function rememberTask(task, key = historyKey()) {
    if (!task || !task.id || !task.toolId) return;
    const items = getTaskHistory(key).filter(item => item.id !== task.id);
    items.unshift({ id: task.id, toolId: task.toolId, createdAt: task.createdAt || new Date().toISOString() });
    saveTaskHistory(items, key);
  }

  function forgetTask(taskId) {
    saveTaskHistory(getTaskHistory().filter(item => item.id !== taskId));
  }

  async function sha256(file) {
    const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer());
    return Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, '0')).join('');
  }

  async function jsonRequest(url, options) {
    const response = await fetch(url, Object.assign({ credentials: 'include' }, options || {}));
    let payload = {};
    try { payload = await response.json(); } catch (_) {}
    if (!response.ok) {
      const detail = payload.detail;
      const message = typeof detail === 'string' ? detail : (detail && detail.message) || payload.error || ('请求失败 (' + response.status + ')');
      const error = new Error(message);
      error.status = response.status;
      throw error;
    }
    return payload;
  }

  function setProgress(item, message) {
    const tag = item.querySelector('.tag2');
    tag.className = 'tag2 wait';
    tag.textContent = message;
  }

  function uploadFile(intent, file, onProgress) {
    return new Promise((resolve, reject) => {
      const request = new XMLHttpRequest();
      request.open(intent.method || 'PUT', intent.signedUrl, true);
      request.withCredentials = String(intent.signedUrl || '').startsWith('/');
      Object.entries(intent.headers || {}).forEach(([name, value]) => request.setRequestHeader(name, value));
      request.upload.onprogress = event => {
        if (event.lengthComputable && onProgress) onProgress(event.loaded, event.total);
      };
      request.onload = () => request.status >= 200 && request.status < 300
        ? resolve()
        : reject(new Error('文件上传失败 (' + request.status + ')'));
      request.onerror = () => reject(new Error('文件上传网络中断，请重试。'));
      request.send(file);
    });
  }

  async function uploadFileWithRetry(intent, file, onProgress) {
    let lastError;
    for (let attempt = 1; attempt <= 3; attempt += 1) {
      try {
        await uploadFile(intent, file, onProgress);
        return;
      } catch (error) {
        lastError = error;
        if (attempt < 3) await sleep(attempt * 800);
      }
    }
    throw lastError;
  }

  async function waitForTask(taskId, item) {
    const deadline = Date.now() + 15 * 60 * 1000;
    while (Date.now() < deadline) {
      if (!item.isConnected || item.dataset.historyKey !== historyKey()) throw new Error('任务视图已切换，请在对应账号下重新查看。');
      const task = await jsonRequest('/api/overseas-payroll/tasks/' + encodeURIComponent(taskId));
      if (task.status === 'succeeded') return task;
      if (task.status === 'failed') throw new Error(task.error || '处理任务失败。');
      const progress = task.progress && task.progress.message;
      setProgress(item, progress || task.statusLabel || '等待云端处理…');
      await sleep(2000);
    }
    throw new Error('处理时间超过 15 分钟，请稍后在任务记录中查看。');
  }

  async function startDownload(task, item) {
    const current = await jsonRequest('/api/me', { cache: 'no-store' });
    const currentKey = current.user && current.user.id
      ? taskHistoryPrefix + encodeURIComponent(current.user.id) : '';
    if (!currentKey || currentKey !== item.dataset.historyKey) {
      renderBar(current.user || null);
      throw new Error('登录账号已变化，请刷新后查看当前账号任务。');
    }
    const download = await jsonRequest('/api/overseas-payroll/tasks/' + encodeURIComponent(task.id) + '/download', { cache: 'no-store' });
    if (!item.isConnected || item.dataset.historyKey !== historyKey()) return;
    const anchor = document.createElement('a');
    anchor.href = download.signedUrl;
    anchor.download = download.filename || '';
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  }

  function appendDownloadButton(task, item) {
    const button = document.createElement('button');
    button.textContent = '下载结果';
    button.className = 'btn-dl';
    button.onclick = async () => {
      button.disabled = true;
      item.querySelector('.download-error')?.remove();
      try {
        await startDownload(task, item);
      } catch (error) {
        const message = document.createElement('div');
        message.className = 'download-error';
        message.setAttribute('role', 'alert');
        message.textContent = '下载失败，可重试：' + error.message;
        item.appendChild(message);
      } finally {
        button.disabled = false;
      }
    };
    item.appendChild(button);
    return button;
  }

  async function downloadTask(task, item, autoDownload) {
    if (!item.isConnected || item.dataset.historyKey !== historyKey()) return;
    const summary = task.summary || '处理完成';
    const meta = {
      in_bytes: (task.files || []).reduce((total, file) => total + Number(file.sizeBytes || 0), 0),
      out_bytes: task.output && task.output.sizeBytes,
    };
    item.dataset.fname = (task.output && task.output.filename) || 'result.xlsx';
    if (item.dataset.preview === 'true') {
      setItem(item, true, '已生成', meta);
      const summaryBox = document.createElement('div');
      summaryBox.className = 'summary';
      summaryBox.textContent = summary;
      item.appendChild(summaryBox);
    } else {
      setItem(item, true, summary.replace(/\n/g, ' ｜ '), meta);
    }
    const button = appendDownloadButton(task, item);
    if (autoDownload !== false && item.dataset.preview !== 'true') await button.onclick();
  }

  function taskDisplayName(task) {
    const names = (task.files || []).map(file => file.filename).filter(Boolean);
    return names.join(' ＋ ') || task.toolName || '海外薪资处理任务';
  }

  async function resumeTask(task, item) {
    if (task.status === 'failed') {
      const message = task.error || '处理任务失败。';
      setItem(item, false, '失败: ' + message);
      showErrorDetail(item, message);
      return;
    }
    if (task.status === 'succeeded') {
      await downloadTask(task, item, false);
      return;
    }
    if (task.status === 'uploading') {
      setItem(item, false, '上传未完成');
      showErrorDetail(item, '上传尚未完成，请重新准备文件并点击开始处理。');
      return;
    }
    if (task.status === 'ready') {
      setProgress(item, '文件已上传 · 等待开始');
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'task-resume'; button.textContent = '开始处理此任务';
      item.dataset.recordState = 'ready';
      appendRecordRemoval(item);
      button.onclick = async () => {
        item.dataset.recordState = 'active';
        item.querySelector('.record-remove').disabled = true;
        button.disabled = true;
        try {
          await jsonRequest('/api/overseas-payroll/tasks/' + encodeURIComponent(task.id) + '/enqueue', { method: 'POST' });
          const completed = await waitForTask(task.id, item);
          await downloadTask(completed, item, false);
          button.remove();
        } catch (error) {
          setItem(item, false, '处理失败'); showErrorDetail(item, error.message); button.remove();
        }
      };
      item.append(button);
      return;
    }
    if (task.status === 'failed') {
      const message = task.error || '处理任务失败。';
      setItem(item, false, '失败: ' + message);
      showErrorDetail(item, message);
      return;
    }
    if (task.status === 'succeeded') {
      await downloadTask(task, item, false);
      return;
    }
    setProgress(item, (task.progress && task.progress.message) || task.statusLabel || '正在恢复任务状态…');
    const completed = await waitForTask(task.id, item);
    await downloadTask(completed, item, false);
  }

  async function restoreTaskHistory(toolId) {
    const generation = ++restoreGeneration;
    const key = historyKey();
    const visibleIds = new Set(Array.from(document.querySelectorAll('[data-task-id]'), item => item.dataset.taskId));
    const refs = getTaskHistory().filter(item => item.toolId === toolId && !visibleIds.has(item.id));
    if (!refs.length) return;
    const results = await Promise.all(refs.map(async ref => {
      try {
        return { ref, task: await jsonRequest('/api/overseas-payroll/tasks/' + encodeURIComponent(ref.id)) };
      } catch (error) {
        return { ref, error };
      }
    }));
    if (generation !== restoreGeneration || key !== historyKey() || !CURRENT_TOOL || CURRENT_TOOL.id !== toolId) return;
    for (const result of results.slice().reverse()) {
      if (result.error) {
        if (result.error.status === 404) forgetTask(result.ref.id);
        continue;
      }
      const item = addItem(taskDisplayName(result.task));
      item.dataset.historyKey = key;
      item.dataset.taskId = result.task.id;
      preparationState(toolId).history.prepend(item);
      resumeTask(result.task, item).catch(error => {
        const message = error && error.message ? error.message : String(error || '恢复任务失败');
        setItem(item, false, '恢复失败: ' + message);
        showErrorDetail(item, message);
      });
    }
  }

  async function runAsyncTask(files, displayName, lockKey) {
    lockKey = historyKey() + '|' + CURRENT_TOOL.id + '|' + lockKey;
    if (_processing.has(lockKey)) return;
    _processing.add(lockKey);
    const item = addItem(displayName);
    const key = historyKey();
    const toolId = CURRENT_TOOL.id;
    item.dataset.historyKey = key;
    let succeeded = false;
    try {
      if (!key) throw new Error('请先登录后再上传。');
      setProgress(item, '正在校验文件…');
      const fileSpecs = [];
      for (const file of files) {
        fileSpecs.push({
          filename: file.name,
          sizeBytes: file.size,
          contentType: file.type || 'application/octet-stream',
          sha256: await sha256(file),
        });
      }
      const created = await jsonRequest('/api/overseas-payroll/tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ toolId, files: fileSpecs }),
      });
      rememberTask(created.task, key);
      item.dataset.taskId = created.task.id;
      const uploadedBytes = new Array(files.length).fill(0);
      const totalBytes = files.reduce((total, file) => total + file.size, 0);
      let nextUpload = 0;
      async function uploadWorker() {
        while (nextUpload < created.intents.length) {
          const index = nextUpload;
          nextUpload += 1;
          const intent = created.intents[index];
          await uploadFileWithRetry(intent, files[index], loaded => {
            uploadedBytes[index] = loaded;
            const current = uploadedBytes.reduce((total, value) => total + value, 0);
            const percent = totalBytes ? Math.round(current * 100 / totalBytes) : 0;
            setProgress(item, '上传文件 · ' + percent + '%');
          });
        }
      }
      const uploadResults = await Promise.allSettled(
        Array.from({ length: Math.min(3, created.intents.length) }, () => uploadWorker())
      );
      for (let index = 0; index < created.intents.length; index += 1) {
        try {
          await jsonRequest('/api/overseas-payroll/tasks/' + encodeURIComponent(created.task.id) + '/files/' + encodeURIComponent(created.intents[index].fileId) + '/finalize', { method: 'POST' });
        } catch (finalizeError) {
          const uploadError = uploadResults.find(result => result.status === 'rejected');
          throw (uploadError && uploadError.reason) || finalizeError;
        }
      }
      setProgress(item, '文件上传完成，正在云端处理…');
      await jsonRequest('/api/overseas-payroll/tasks/' + encodeURIComponent(created.task.id) + '/enqueue', { method: 'POST' });
      const task = await waitForTask(created.task.id, item);
      await downloadTask(task, item, false);
      succeeded = true;
    } catch (error) {
      const message = error && error.message ? error.message : String(error || '未知错误');
      setItem(item, false, '失败: ' + message);
      showErrorDetail(item, message);
    } finally {
      _processing.delete(lockKey);
    }
    return succeeded;
  }

  processFile = async function (file) {
    return runAsyncTask([file], file.name, fileKey(file));
  };

  uploadBatch = async function (files) {
    const list = Array.from(files);
    const displayName = list.map(file => file.name).join(' ＋ ');
    return runAsyncTask(list, displayName, displayName + '|batch');
  };

  const preparationStates = new Map();
  const parkedViews = document.createElement('div');
  parkedViews.hidden = true;
  document.body.append(parkedViews);
  const preparation = document.createElement('section');
  preparation.className = 'payroll-preparation';
  preparation.innerHTML = `<div class="prep-heading"><h3>待处理文件</h3><span class="prep-count"></span></div><p class="prep-help">可分次添加文件，准备好后点击开始处理。</p><div class="prep-files"></div><p class="prep-message" role="status" aria-live="polite"></p><div class="prep-actions"><button type="button" class="prep-clear">清空文件</button><button type="button" class="prep-start">开始处理</button></div>`;
  document.getElementById('log').before(preparation);
  const style = document.createElement('style');
  style.textContent = `
    .payroll-preparation{margin-top:18px;padding:16px;border:1px solid #dbe4ef;border-radius:12px;background:#f8fafc;color:#17233f;text-align:left}
    .prep-heading,.prep-row,.prep-actions,.payroll-history summary{display:flex;align-items:center;gap:12px;justify-content:space-between}
    .prep-heading h3,.payroll-current-title{margin:0;font-size:14px;font-weight:650}.prep-count,.prep-help{font-size:12px;color:#64748b}.prep-help{margin:8px 0 12px;line-height:1.6}
    .prep-row{padding:9px 0;border-top:1px solid #e2e8f0;font-size:13px}.prep-file-name{min-width:0;overflow-wrap:anywhere;flex:1}.prep-size{font-size:12px;color:#64748b;white-space:nowrap}
    .payroll-preparation button,.record-remove,.history-clear,.task-resume{font:inherit;font-size:12px;border:1px solid #d5deeb;border-radius:8px;background:#fff;color:#1e3a8a;padding:7px 12px;cursor:pointer}
    .prep-actions{justify-content:flex-end;margin-top:12px}.payroll-preparation .prep-start,.task-resume{background:#2563eb;color:#fff;border-color:#2563eb;min-width:110px}
    .payroll-preparation button:disabled,.history-clear:disabled{opacity:.45;cursor:not-allowed}.prep-message{margin:10px 0;font-size:12px;line-height:1.6;overflow-wrap:anywhere}.prep-message.error{color:#b42318}
    .payroll-current-title{margin:20px 0 10px}.payroll-history{margin-top:20px;border-top:1px solid #e2e8f0;padding-top:12px}.payroll-history summary{cursor:pointer;justify-content:flex-start;list-style:none;color:#1e3a8a;font-size:13px}.payroll-history summary::-webkit-details-marker{display:none}.payroll-history summary::before{content:'›';font-size:18px}.payroll-history[open] summary::before{transform:rotate(90deg)}
    .history-actions{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}.history-list{max-height:420px;overflow:auto;overscroll-behavior:contain}.record-remove{margin-top:10px;display:block}.payroll-summary{width:100%;font-size:12px;line-height:1.7;overflow-wrap:anywhere;color:#475569;margin-top:8px}
    .payroll-preparation button:focus-visible,.payroll-history summary:focus-visible,.record-remove:focus-visible,.task-resume:focus-visible,.history-clear:focus-visible{outline:3px solid #2563eb70;outline-offset:2px}
    @media(max-width:760px){.sidebar{display:none}.content{padding:12px}.topbar{padding:0 12px}.topbar .search{display:none}.topbar-right{gap:8px}.toolbox{padding:12px}.drop{padding:26px 12px}.hero{flex-wrap:wrap}.grid{grid-template-columns:minmax(0,1fr)}}
    @media(max-width:520px){.user-info{display:none}.mask-toggle{white-space:normal!important;display:block;margin:12px 0 0!important}.payroll-preparation{padding:12px}.prep-row{gap:6px;flex-wrap:wrap}.prep-file-name{flex-basis:65%}.prep-actions button{flex:1}.history-list{max-height:300px}}
  `;
  document.head.append(style);
  let preparationOwner = historyKey();
  function preparationState(id = CURRENT_TOOL && CURRENT_TOOL.id) {
    if (!preparationStates.has(id)) {
      const current = document.createElement('div');
      const details = document.createElement('details');
      details.className = 'payroll-history';
      details.innerHTML = `<summary>历史记录</summary><div class="history-actions"><button type="button" class="history-clear history-failed">清除失败记录</button><button type="button" class="history-clear history-all">清除历史记录</button></div><div class="history-list"></div><p class="prep-help">移除记录仅清理本浏览器的显示；处理中的任务仍保留。</p>`;
      const state = { files: [], running: false, current, details, history: details.querySelector('.history-list') };
      preparationStates.set(id, state);
      details.querySelector('.history-failed').onclick = () => clearRecords(state, true);
      details.querySelector('.history-all').onclick = () => clearRecords(state, false);
    }
    return preparationStates.get(id);
  }
  function removeRecord(item) {
    if (item.dataset.historyKey !== historyKey() || item.dataset.recordState === 'active') return;
    if (item.dataset.taskId) forgetTask(item.dataset.taskId);
    item.remove();
  }
  function clearRecords(state, failedOnly) {
    for (const item of Array.from(state.history.children)) {
      if (!failedOnly || item.dataset.recordState === 'failed') removeRecord(item);
    }
  }
  const originalSetItem = setItem;
  setItem = function (item, ok, message, meta) {
    originalSetItem(item, ok, message, meta);
    item.dataset.recordState = ok ? 'succeeded' : 'failed';
    item.querySelector('.tag2').textContent = ok ? '已完成 · 可下载' : '处理失败';
    if (ok && !item.querySelector('.payroll-summary')) {
      const summary = document.createElement('div');
      summary.className = 'payroll-summary'; summary.textContent = message;
      item.append(summary);
    }
    appendRecordRemoval(item);
    item.querySelector('.record-remove').disabled = false;
  };
  function appendRecordRemoval(item) {
    if (!item.querySelector('.record-remove')) {
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'record-remove'; button.textContent = '移除记录';
      button.onclick = () => removeRecord(item);
      item.append(button);
    }
  }
  const originalAddItem = addItem;
  addItem = function (name) {
    const item = originalAddItem(name);
    item.dataset.recordState = 'active';
    item.dataset.toolId = CURRENT_TOOL.id;
    item.dataset.preview = String(Boolean(CURRENT_TOOL.preview));
    preparationState().current.prepend(item);
    return item;
  };
  function preparationMessage(text, error = false) {
    const message = preparation.querySelector('.prep-message');
    message.textContent = text; message.classList.toggle('error', error);
  }
  function renderPreparation() {
    const state = preparationState();
    const list = preparation.querySelector('.prep-files'); list.replaceChildren();
    preparation.querySelector('.prep-count').textContent = `${state.files.length} 个文件 · ${fmtSize(state.files.reduce((n,f) => n + f.size, 0))}`;
    for (const file of state.files) {
      const row = document.createElement('div'); row.className = 'prep-row';
      const name = document.createElement('span'); name.className = 'prep-file-name'; name.textContent = file.name;
      const size = document.createElement('span'); size.className = 'prep-size'; size.textContent = fmtSize(file.size);
      const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = '移除'; remove.disabled = state.running;
      remove.setAttribute('aria-label', '移除待处理文件 ' + file.name);
      remove.onclick = () => { state.files = state.files.filter(f => f !== file); preparationMessage(''); renderPreparation(); };
      row.append(name, size, remove); list.append(row);
    }
    preparation.querySelector('.prep-clear').disabled = state.running || !state.files.length;
    preparation.querySelector('.prep-start').disabled = state.running || !state.files.length;
    preparation.querySelector('.prep-start').textContent = state.running ? '处理中…' : '开始处理';
  }
  handleFiles = function (fileList) {
    const state = preparationState();
    const incoming = Array.from(fileList);
    fileInput.value = '';
    if (state.running) { preparationMessage('本次任务处理中，请完成后再准备新文件。'); return; }
    const next = state.files.slice();
    for (const file of incoming) {
      const extension = '.' + file.name.split('.').pop().toLowerCase();
      const accepts = (CURRENT_TOOL.accept || '').split(',');
      if (!accepts.includes(extension)) { preparationMessage(`${file.name} 格式不支持，应准备 ${CURRENT_TOOL.accept} 文件。`, true); return; }
      if (!file.size || file.size > 40 * 1024 * 1024) { preparationMessage(`${file.name} 为空或超过 40 MB。`, true); return; }
      const existing = next.findIndex(f => f.name.toLowerCase() === file.name.toLowerCase());
      if (existing >= 0) next[existing] = file; else next.push(file);
    }
    if (!CURRENT_TOOL.multi && next.length > 1) { preparationMessage('这个工具每次只处理一个文件，请先移除原文件。', true); return; }
    if (next.length > 12 || next.reduce((n,f) => n + f.size, 0) > 80 * 1024 * 1024) { preparationMessage('一次最多 12 个文件、总计 80 MB，请移除部分文件。', true); return; }
    state.files = next;
    preparationMessage('文件已加入待处理列表，点击“开始处理”后才会上传和运行。');
    renderPreparation();
  };
  preparation.querySelector('.prep-clear').onclick = () => { preparationState().files = []; preparationMessage('待处理文件已清空。'); renderPreparation(); };
  preparation.querySelector('.prep-start').onclick = async () => {
    const tool = CURRENT_TOOL;
    const state = preparationState(tool.id);
    if (state.running || !state.files.length) return;
    const key = historyKey();
    const files = state.files.slice();
    state.running = true; renderPreparation(); preparationMessage('正在检查文件组合…');
    try {
      const session = await jsonRequest('/api/me', { cache: 'no-store' });
      const actualKey = session.user && session.user.id ? taskHistoryPrefix + encodeURIComponent(session.user.id) : '';
      if (actualKey !== key) {
        renderBar(session.user || null);
        preparationMessage('登录账号已变化，请重新准备文件。', true);
        return;
      }
      const form = new FormData(); files.forEach(file => form.append('files', file));
      await jsonRequest('/api/overseas-payroll/tools/' + encodeURIComponent(tool.id) + '/validate-files', { method: 'POST', body: form });
      if (key !== historyKey() || CURRENT_TOOL.id !== tool.id) return;
      for (const item of Array.from(state.current.children)) state.history.prepend(item);
      preparationMessage('检查通过，正在上传并处理…');
      const succeeded = tool.multi ? await uploadBatch(files) : await processFile(files[0]);
      if (succeeded) state.files = [];
      if (CURRENT_TOOL.id === tool.id && key === historyKey()) preparationMessage(succeeded ? '本次处理已完成，可在下方下载结果。' : '本次处理失败，文件已保留，可调整后重新开始。', !succeeded);
    } catch (error) {
      if (CURRENT_TOOL.id === tool.id && key === historyKey()) preparationMessage(error.message, true);
    } finally {
      state.running = false;
      if (CURRENT_TOOL.id === tool.id && key === historyKey()) renderPreparation();
    }
  };
  function resetPreparation() {
    preparationStates.clear(); parkedViews.replaceChildren();
    preparationOwner = historyKey();
    preparation.querySelector('.prep-files').replaceChildren();
    preparation.querySelector('.prep-count').textContent = '0 个文件 · 0B';
    preparation.querySelector('.prep-start').disabled = true;
    preparation.querySelector('.prep-clear').disabled = true;
    preparationMessage('');
  }
  function showPreparation(tool) {
    if (preparationOwner !== historyKey()) {
      preparationStates.clear(); parkedViews.replaceChildren(); preparationOwner = historyKey();
    }
    const state = preparationState(tool.id);
    const heading = document.createElement('h3'); heading.className = 'payroll-current-title'; heading.textContent = '本次处理';
    document.getElementById('log').replaceChildren(heading, state.current, state.details);
    preparation.querySelector('.prep-help').textContent = `${preparationHint(tool)}。可分次添加，准备好后点击开始处理。`;
    preparationMessage(''); renderPreparation();
  }

  function preparationHint(tool) {
    return (tool.drop_hint || tool.desc || '').trim().replace(/^一次(?:拖入|上传)[：:]?/, '需准备：').replace(/[。.!！?？；;]+$/u, '');
  }

  function applyToolDropHint(tool) {
    if (tool && tool.drop_hint && typeof dropsub !== 'undefined') {
      setText(dropsub, preparationHint(tool) + '；添加文件后点击开始处理。');
    }
  }

  if (typeof showTool === 'function') {
    const originalShowTool = showTool;
    showTool = function (id) {
      for (const state of preparationStates.values()) parkedViews.append(state.current, state.details);
      originalShowTool(id);
      if (CURRENT_TOOL && CURRENT_TOOL.id === id) showPreparation(CURRENT_TOOL);
      applyToolDropHint(CURRENT_TOOL);
      restoreTaskHistory(id);
    };
  }
  if (typeof CURRENT_TOOL !== 'undefined' && CURRENT_TOOL) {
    showPreparation(CURRENT_TOOL);
    applyToolDropHint(CURRENT_TOOL);
    restoreTaskHistory(CURRENT_TOOL.id);
  }
})();
