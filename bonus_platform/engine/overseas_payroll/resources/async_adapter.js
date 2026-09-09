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
    if (CURRENT_TOOL && CURRENT_TOOL.preview) {
      setItem(item, true, '已生成', meta);
      const summaryBox = document.createElement('div');
      summaryBox.className = 'summary';
      summaryBox.textContent = summary;
      item.appendChild(summaryBox);
    } else {
      setItem(item, true, summary.replace(/\n/g, ' ｜ '), meta);
    }
    const button = appendDownloadButton(task, item);
    if (autoDownload !== false && !(CURRENT_TOOL && CURRENT_TOOL.preview)) await button.onclick();
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
      try {
        for (const file of task.files || []) {
          const response = await jsonRequest('/api/overseas-payroll/tasks/' + encodeURIComponent(task.id) + '/files/' + encodeURIComponent(file.id) + '/finalize', { method: 'POST' });
          task = response.task || task;
        }
      } catch (error) {
        if (error.status !== 404 && error.status !== 409) throw error;
        setItem(item, false, '上传未完成，请重新选择文件。');
        showErrorDetail(item, '刷新后无法继续传输未完成的文件。已上传的文件不代表整个任务已可处理，请重新选择本次所需文件。');
        return;
      }
    }
    if (task.status === 'ready') {
      setProgress(item, '文件已上传，正在恢复云端处理…');
      try {
        const response = await jsonRequest('/api/overseas-payroll/tasks/' + encodeURIComponent(task.id) + '/enqueue', { method: 'POST' });
        task = response.task || task;
      } catch (error) {
        if (error.status !== 409) throw error;
        task = await jsonRequest('/api/overseas-payroll/tasks/' + encodeURIComponent(task.id));
        if (task.status === 'ready' || task.status === 'uploading') throw error;
      }
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
    const refs = getTaskHistory().filter(item => item.toolId === toolId);
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
      resumeTask(result.task, item).catch(error => {
        const message = error && error.message ? error.message : String(error || '恢复任务失败');
        setItem(item, false, '恢复失败: ' + message);
        showErrorDetail(item, message);
      });
    }
  }

  async function runAsyncTask(files, displayName, lockKey) {
    if (_processing.has(lockKey)) return;
    _processing.add(lockKey);
    const item = addItem(displayName);
    const key = historyKey();
    const toolId = CURRENT_TOOL.id;
    item.dataset.historyKey = key;
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
      await downloadTask(task, item, true);
    } catch (error) {
      const message = error && error.message ? error.message : String(error || '未知错误');
      setItem(item, false, '失败: ' + message);
      showErrorDetail(item, message);
    } finally {
      _processing.delete(lockKey);
    }
  }

  processFile = async function (file) {
    return runAsyncTask([file], file.name, fileKey(file));
  };

  uploadBatch = async function (files) {
    const list = Array.from(files);
    const displayName = list.map(file => file.name).join(' ＋ ');
    return runAsyncTask(list, displayName, displayName + '|batch');
  };

  if (typeof showTool === 'function') {
    const originalShowTool = showTool;
    showTool = function (id) {
      originalShowTool(id);
      restoreTaskHistory(id);
    };
  }
  if (typeof CURRENT_TOOL !== 'undefined' && CURRENT_TOOL) {
    restoreTaskHistory(CURRENT_TOOL.id);
  }
})();
