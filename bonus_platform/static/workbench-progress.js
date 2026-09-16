/* Shared payroll progress. Only explicitly selected requests are observed. */
(() => {
  'use strict';
  const tasks = new Map();
  const nativeFetch = window.fetch.bind(window);
  let panel, motion, sequence = 0, focusedId = '', restoreFocus;
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const abortError = () => new DOMException('已中止本次操作，已完成的步骤和数据会保留。', 'AbortError');
  const phaseNames = { prepare:'准备文件', upload:'上传文件', check:'检查数据', queued:'等待处理', calculate:'正在核算', report:'生成结果', complete:'处理完成', failed:'处理未完成', stopped:'操作已中止' };
  function ensurePanel() {
    if (panel?.isConnected) return;
    panel = document.createElement('dialog');
    panel.className = 'wb-progress';
    panel.setAttribute('aria-labelledby', 'wbProgressTitle');
    panel.innerHTML = `<header><span class="wb-progress-brand">薪酬核算工作台</span><button type="button" data-minimize aria-label="收起进度窗口">−</button></header>
      <div class="wb-progress-art" aria-hidden="true"><div class="wb-progress-orbit"></div><div class="wb-progress-paper wb-progress-paper-back"></div><div class="wb-progress-paper wb-progress-paper-front"><i></i><i></i><i></i><b>✓</b></div><span class="wb-progress-spark">＋</span></div>
      <div class="wb-progress-copy"><span data-subject></span><h2 id="wbProgressTitle" aria-live="polite"></h2><p data-description></p></div>
      <div class="wb-progress-meter" role="progressbar" aria-label="当前步骤进度"><span></span></div>
      <div class="wb-progress-meta"><span data-count></span><span data-percent></span></div>
      <div class="wb-progress-queue" aria-label="正在处理的任务"></div>
      <p class="wb-progress-note"></p><footer><button type="button" data-stop>中止上传</button><button type="button" data-dismiss hidden>关闭</button></footer>`;
    document.body.append(panel);
    panel.querySelector('[data-minimize]').onclick = () => minimize();
    panel.querySelector('[data-dismiss]').onclick = () => {
      [...tasks.values()].filter(t=>t.done).forEach(t=>tasks.delete(t.id));
      panel.close(); render(); restoreFocus?.focus?.({preventScroll:true});
    };
    panel.querySelector('[data-stop]').onclick = async () => {
      const task = tasks.get(focusedId);
      if (!task || task.done || task.stopping) return;
      task.stopping = true; render();
      if (task.abort) task.abort();
      // Server work is allowed to settle; its result is kept, but no next request is started by the caller.
    };
    panel.addEventListener('cancel', event => { event.preventDefault(); minimize(); });
  }
  function animate() {
    motion?.kill(); motion = null;
    if (reduced.matches || !window.gsap || !panel?.open) return;
    window.gsap.fromTo(panel, {opacity:0, y:12, scale:.97}, {opacity:1,y:0,scale:1,duration:.34,ease:'power3.out',clearProps:'opacity,transform'});
    motion = window.gsap.timeline({repeat:-1,repeatDelay:.35});
    motion.to(panel.querySelector('.wb-progress-paper-front'), {y:-5,rotation:3,duration:.7,ease:'sine.inOut'})
      .to(panel.querySelector('.wb-progress-paper-front'), {y:0,rotation:0,duration:.8,ease:'sine.inOut'})
      .to(panel.querySelector('.wb-progress-paper-back'), {x:-4,rotation:-9,duration:.6,ease:'sine.inOut'},0)
      .to(panel.querySelector('.wb-progress-paper-back'), {x:0,rotation:-6,duration:.9,ease:'sine.inOut'},.6);
  }
  function minimize() { panel?.close(); motion?.kill(); renderDock(); restoreFocus?.focus?.({preventScroll:true}); }
  function open(id) {
    focusedId = id || focusedId; ensurePanel();
    if (!panel.open) { restoreFocus = document.activeElement; panel.showModal(); animate(); }
    render();
  }
  function renderDock() {
    let dock = document.getElementById('wbProgressDock');
    if (!tasks.size) { dock?.remove(); return; }
    if (!dock) { dock=document.createElement('button');dock.id='wbProgressDock';dock.className='wb-progress-dock';document.body.append(dock);dock.onclick=()=>open(); }
    const pending=[...tasks.values()].filter(t=>!t.done).length;
    dock.textContent=pending ? `查看处理进度 · ${pending}` : '查看处理结果';
    dock.hidden=Boolean(panel?.open);
  }
  function render() {
    if (!tasks.size) { panel?.close();motion?.kill();renderDock();return; }
    ensurePanel();
    const task=tasks.get(focusedId)||[...tasks.values()].at(-1);focusedId=task.id;
    panel.dataset.phase=task.phase;
    panel.querySelector('[data-subject]').textContent=task.subject || '核算任务';
    panel.querySelector('h2').textContent=task.stopping&&!task.done?'正在中止后续处理':phaseNames[task.phase]||'正在处理';
    panel.querySelector('[data-description]').textContent=task.description || '';
    const numeric=Number.isFinite(task.percent), meter=panel.querySelector('[role="progressbar"]');
    meter.classList.toggle('is-indeterminate',!numeric&&!task.done);
    meter.querySelector('span').style.width=numeric?`${Math.max(0,Math.min(100,task.percent))}%`:task.done?'100%':'35%';
    if(numeric) meter.setAttribute('aria-valuenow',Math.round(task.percent));else meter.removeAttribute('aria-valuenow');
    meter.setAttribute('aria-valuetext',numeric?`${Math.round(task.percent)}%`:phaseNames[task.phase]||'正在处理');
    panel.querySelector('[data-percent]').textContent=numeric?`${Math.round(task.percent)}%`:'';
    panel.querySelector('[data-count]').textContent=task.detail||'';
    panel.querySelector('.wb-progress-note').textContent=task.done ? (task.phase==='stopped'?'已完成的步骤和数据会保留。':'可关闭窗口，继续查看页面。') : task.abort ? '中止后可重新选择文件上传。' : task.stopping ? '等待当前步骤结束后停止，不再继续后续操作。' : '可收起查看页面。中止将在当前步骤结束后生效。';
    const stop=panel.querySelector('[data-stop]');stop.hidden=task.done;stop.disabled=task.stopping;stop.textContent=task.stopping?'正在中止…':task.abort?'中止上传':'中止后续处理';
    panel.querySelector('[data-dismiss]').hidden=!task.done;
    const queue=panel.querySelector('.wb-progress-queue');queue.replaceChildren();
    if(tasks.size>1) for(const t of tasks.values()){const b=document.createElement('button');b.type='button';b.textContent=`${t.subject} · ${phaseNames[t.phase]||'处理中'}`;b.setAttribute('aria-pressed',String(t.id===focusedId));b.onclick=()=>{focusedId=t.id;render();};queue.append(b);}
    if(task.done){motion?.kill();motion=null;}
    renderDock();
  }
  function begin(options={}) {
    for (const [key, value] of tasks) if (value.done) tasks.delete(key);
    const id=options.id||`operation-${++sequence}`;
    const task={id,subject:'核算任务',phase:'prepare',percent:null,done:false,stopping:false,...options};
    tasks.set(id,task);open(id);
    return {
      id,
      update(patch){if(!task.done){Object.assign(task,patch);render();}},
      check(){if(task.stopping)throw abortError();},
      finish(patch={}){if(task.done)return;task.done=true;task.abort=null;Object.assign(task,{phase:task.stopping?'stopped':'complete',percent:null},patch);render();},
      fail(error){if(task.done)return;task.done=true;task.abort=null;task.phase=error?.name==='AbortError'?'stopped':'failed';task.percent=null;task.description=error?.message||'请查看页面提示后重试。';render();},
      get stopping(){return task.stopping;},
    };
  }
  // Route allowlist keeps metadata reads, authentication, and unrelated requests unchanged.
  function describe(path, method) {
    if(method!=='POST')return null;
    if(/^\/api\/runs\/(calculate|[^/]+\/finalize)$/.test(path))return {subject:'招聘奖金',phase:'calculate',description:'正在核对人员和奖金规则，生成核算结果。'};
    if(/^\/api\/fbu-performance\/(import-[a-z-]+|roster)$/.test(path))return {subject:'FBU 资料处理',phase:'check',description:'正在读取并检查核算资料。'};
    if(/^\/api\/fbu-performance\/runs\/[^/]+\/(attendance|previous-attendance|roster|salary-history)(?:[/-].*)?$/.test(path) && !path.includes('direct-upload'))return {subject:'FBU 资料处理',phase:'check',description:'正在读取并检查核算资料。'};
    if(path==='/api/china-employee-payroll/meal-allowance')return {subject:'正式工餐补',phase:'calculate',description:'正在读取考勤，核算餐补。'};
    if(/^\/api\/social-insurance\/.*(sync-all|generate-package)$/.test(path))return {subject:'社保报盘',phase:'report',description:path.endsWith('sync-all')?'正在整理各主体人员名单。':'正在检查资料并生成报盘文件。'};
    return null;
  }
  async function trackedFetch(url, options={}) {
    const descriptor=describe(new URL(url,location.href).pathname,(options.method||'GET').toUpperCase());
    if(!descriptor)return nativeFetch(url,options);
    const task=begin(descriptor);
    try {
      const response=options.body instanceof FormData ? await uploadRequest(url,options,task) : await nativeFetch(url,options);
      task.check();
      let payload;
      try { payload = await response.clone().json(); } catch (_) {}
      if(response.ok && payload?.ok !== false && !['failed','失败'].includes(payload?.status))task.finish();else task.fail(new Error('处理未完成，请查看页面中的具体提示。'));
      return response;
    } catch(error){task.fail(error);throw error;}
  }
  function uploadRequest(url,options,task) {
    return new Promise((resolve,reject)=>{
      const xhr=new XMLHttpRequest();xhr.open(options.method||'POST',url);xhr.withCredentials=options.credentials==='include';
      new Headers(options.headers||{}).forEach((value,key)=>xhr.setRequestHeader(key,value));
      const signal=options.signal;
      const abort=()=>xhr.abort();
      if(signal?.aborted){reject(abortError());return;}
      signal?.addEventListener('abort',abort,{once:true});
      xhr.upload.onprogress=event=>task.update({phase:'upload',description:'正在上传文件，请稍候。',percent:event.lengthComputable?event.loaded/event.total*100:null});
      xhr.upload.onload=()=>task.update({phase:'calculate',description:'文件已上传，正在检查数据并处理。',percent:null,abort:null});
      xhr.onload=()=>resolve(new Response(xhr.responseText,{status:xhr.status,statusText:xhr.statusText,headers:parseHeaders(xhr.getAllResponseHeaders())}));
      xhr.onerror=()=>reject(new Error('连接中断，请检查网络后重试。'));
      xhr.onabort=()=>reject(abortError());
      xhr.ontimeout=()=>reject(new Error('处理超时，请稍后重试。'));
      xhr.onloadend=()=>signal?.removeEventListener('abort',abort);
      task.update({phase:'upload',abort});xhr.send(options.body);
    });
  }
  function parseHeaders(raw){const headers=new Headers();raw.trim().split(/[\r\n]+/).filter(Boolean).forEach(line=>{const i=line.indexOf(':');if(i>0)headers.append(line.slice(0,i),line.slice(i+1).trim());});return headers;}
  reduced.addEventListener('change',()=>{motion?.kill();if(!reduced.matches&&panel?.open)animate();});
  window.WorkbenchProgress={begin,fetch:trackedFetch,uploadRequest,abortError};
})();
