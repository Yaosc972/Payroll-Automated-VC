'use strict';
(() => {
  const $ = (id) => document.getElementById(id);
  const chinaDate = Object.fromEntries(new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Shanghai', year:'numeric', month:'2-digit'}).formatToParts(new Date()).map(part => [part.type, part.value]));
  const previousMonth = new Date(Date.UTC(Number(chinaDate.year), Number(chinaDate.month) - 2, 1)).toISOString().slice(0,7);
  const state = { catalog: null, category: 'all', query: '', sort: 'recent', view: 'catalog', guideSubject: 'gangwei_butie', guideMonth: previousMonth };
  const escape = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[c]));
  const dateLabel = (value) => new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', year:'numeric', month:'2-digit', day:'2-digit' }).format(new Date(value));
  // Keep subject artwork identical to the domestic payroll home page.
  const subjectIcons = {
    utensils:'<svg viewBox="0 0 24 24" width="23" height="23" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 3v6a3 3 0 0 0 6 0V3M8 3v18M19 21V3c-4 3-4 8 0 9"/></svg>',
    home:'<svg viewBox="0 0 24 24" width="23" height="23" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m3 10 9-7 9 7M5 9v12h14V9M9 21v-8h6v8"/></svg>',
    moon:'<svg viewBox="0 0 24 24" width="23" height="23" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 15.5A8.5 8.5 0 0 1 8.5 4 8.5 8.5 0 1 0 20 15.5Z"/></svg>',
    briefcase:'<svg viewBox="0 0 24 24" width="23" height="23" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="7" width="18" height="14" rx="3"/><path d="M8 7V4h8v3M3 12c5 3 13 3 18 0M10 13v3h4v-3"/></svg>',
    sun:'<svg viewBox="0 0 24 24" width="23" height="23" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 14.5V5a3 3 0 0 1 6 0v9.5a5 5 0 1 1-6 0ZM12 8v9M18 5h3M18 9h2"/></svg>',
    calendar:'<svg viewBox="0 0 24 24" width="23" height="23" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="3"/><path d="M7 3v4M17 3v4M3 10h18m-13 5 3 3 5-5"/></svg>',
    clock:'<svg viewBox="0 0 24 24" width="23" height="23" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2M5 4 3 6M19 4l2 2"/></svg>',
  };
  const icon = (name) => {
    const key = Object.hasOwn(subjectIcons, name) ? name : 'briefcase';
    return `<span class="skill-icon" data-icon="${key}">${subjectIcons[key]}</span>`;
  };
  const matching = (skill) => (state.category === 'all' || skill.category === state.category) &&
    [skill.name, skill.slug, skill.description, ...skill.inputs, ...skill.updates].join(' ').toLowerCase().includes(state.query.toLowerCase());
  const actionIcon = name => SkillHubUI.icon(name);
  const skillById = (id) => state.catalog.skills.find((item) => item.id === id);

  function card(item) {
    return `<article class="skill-card"><div class="card-top">${icon(item.icon)}<h3><button data-detail="${escape(item.id)}">${escape(item.name)}</button></h3>${item.is_new ? '<span class="new-label">新版本</span>' : ''}</div><p class="card-description">${escape(item.description)}</p><p class="rule-version">${escape(item.rule_version)} · ${dateLabel(item.released_at)}</p><div class="card-footer"><button class="text-button" data-detail="${escape(item.id)}">${actionIcon('details')}查看详情</button><a class="button secondary" href="${escape(item.download_url)}" aria-label="下载${escape(item.name)} Skill">${actionIcon('download')}下载</a></div></article>`;
  }

  function render() {
    if (!state.catalog) return;
    const skills = state.catalog.skills.filter(matching).sort((a, b) => state.sort === 'name' ? a.name.localeCompare(b.name, 'zh-CN') : b.released_at.localeCompare(a.released_at));
    const selectedIds = new Set(skills.map((item) => item.id));
    const releases = state.catalog.releases.filter((item) => selectedIds.has(item.skill_id)).sort((a,b) => b.released_at.localeCompare(a.released_at));
    $('libraryTitle').textContent = state.view === 'guide' ? 'Skill 使用指引' : state.view === 'releases' ? '上新动态' : state.category === 'all' ? '全部 Skill' : state.category;
    $('resultCount').textContent = state.view === 'guide' ? '选择科目，按对话示例使用' : state.view === 'releases' ? `${releases.length} 条版本更新` : `${skills.length} 份 Skill · 可独立运行`;
    $('skillCards').innerHTML = skills.map(card).join('');
    $('releaseFeed').innerHTML = releases.map((release) => `<article class="release-item"><div class="release-item-head"><div><span class="new-label">${release.kind === 'new' ? '首次上架' : '版本更新'}</span><h3>${escape(release.title)}</h3></div><time datetime="${escape(release.released_at)}">${dateLabel(release.released_at)}</time></div><ul>${release.updates.map((line) => `<li>${escape(line)}</li>`).join('')}</ul><div class="release-meta"><code>${escape(release.package_version)}</code><code>${escape(release.rule_version)}</code><button class="text-button" data-detail="${escape(release.skill_id)}">${actionIcon('details')}查看当前版本</button></div></article>`).join('');
    $('skillCards').hidden = state.view !== 'catalog';
    $('releaseFeed').hidden = state.view !== 'releases';
    $('empty').hidden = state.view === 'guide' || (state.view === 'catalog' ? skills.length > 0 : releases.length > 0);
    $('catalogTools').hidden = state.view === 'guide';
    $('guidePanel').hidden = state.view !== 'guide';
    if (state.view === 'guide') $('guidePanel').innerHTML = DomesticSkillGuide.render(skillById(state.guideSubject), state.guideMonth, state.catalog.skills);
    $('guideTab').setAttribute('aria-pressed', state.view === 'guide');
    $('catalogTab').setAttribute('aria-pressed', state.view === 'catalog');
    $('releaseTab').setAttribute('aria-pressed', state.view === 'releases');
    $('sort').disabled = state.view === 'releases';
    $('categories').querySelectorAll('button').forEach((button) => button.setAttribute('aria-pressed', button.dataset.category === state.category));
    SkillHubUI.enhance(document, subjectIcons);
  }

  function showDialog(html) {
    $('dialogContent').innerHTML = html;
    if (!$('detailDialog').open) $('detailDialog').showModal();
    $('detailDialog').scrollTop = 0;
    SkillHubUI.enhance($('detailDialog'), subjectIcons);
  }

  function detail(id) {
    const item = skillById(id);
    if (!item) return;
    const fields = item.contract.fields.concat(item.contract.nullable_fields || []);
    const command = `python3 scripts/run.py input.json --mode validate --output validation.json`;
    showDialog(`<div class="detail-title">${icon(item.icon)}<div><p class="eyebrow">${escape(item.slug)}</p><h2 id="dialogTitle">${escape(item.name)}</h2></div></div><p class="detail-description">${escape(item.description)}</p><div class="detail-meta"><span class="tag">${escape(item.category)}</span><span class="tag">${escape(item.rule_version)}</span><span class="tag">更新于 ${dateLabel(item.released_at)}</span><span class="tag">${Math.ceil(item.size_bytes/1024)} KB</span></div><section class="detail-section"><h3>这次更新</h3><ul>${item.updates.map((line) => `<li>${escape(line)}</li>`).join('')}</ul></section><section class="detail-section"><h3>准备这些资料</h3><ul>${item.inputs.map((line) => `<li>${escape(line)}</li>`).join('')}</ul></section><section class="detail-section"><h3>适用规则</h3><p>${escape(item.rules.summary)}</p>${item.rules.regions.map((region) => `<div class="region-rule"><strong>${escape(region.name)}</strong><p>${escape(region.rule)}</p></div>`).join('')}</section><details class="detail-section"><summary>输入字段与版本信息</summary><p>${fields.map((field) => `<span class="tag">${escape(field)}</span>`).join(' ')}</p><p>地区补充字段及逐日字段详见包内 references/input-contract.json。</p><p>Skill 包版本：<code>${escape(item.package_version)}</code></p><p>规则版本与包版本分别记录；输入校验变化也会生成新包版本。</p></details><section class="detail-section"><h3>下载后开始使用</h3><p>解压后，将 ${escape(item.slug)} 文件夹放到所用 AI 助手的 Skill 目录，也可以让助手读取其中的 SKILL.md。准备 input.json 后，先检查资料。</p><pre class="command">${escape(command)}</pre><button class="text-button" id="copyCommand" data-command="${escape(command)}">${actionIcon('copy')}复制检查命令</button><p class="copy-status" id="copyStatus" role="status"></p></section><p class="detail-note">空名单需明确确认；有缺失或待复核的结果不能作为最终发薪金额。</p><div class="detail-actions"><a class="button primary" href="${escape(item.download_url)}">${actionIcon('download')}下载最新 Skill</a><button class="button secondary" data-usage="${escape(item.id)}">${actionIcon('guide')}使用指引</button></div><p class="integrity">文件 SHA-256：${escape(item.sha256)}</p>`);
    history.replaceState(null, '', `#skill=${encodeURIComponent(id)}`);
  }

  function rememberGuide() {
    const params = new URLSearchParams({view:'guide', subject:state.guideSubject, month:state.guideMonth});
    history.replaceState(null, '', `#${params}`);
  }
  function usage(id) {
    if (typeof id === 'string' && state.catalog && skillById(id)) state.guideSubject = id;
    if ($('detailDialog').open) $('detailDialog').close();
    state.view = 'guide';
    render();
    rememberGuide();
    $('libraryTitle').scrollIntoView({block:'start', behavior:'auto'});
  }

  async function load() {
    $('error').hidden = true;
    try {
      const response = await fetch('/api/domestic-labor/skillhub', { cache: 'no-store' });
      if (!response.ok) throw new Error(response.status === 401 ? '请先登录，再查看 SkillHub。' : response.status === 403 ? '当前账号没有中国区外包工薪酬核算权限。' : '暂时无法读取 SkillHub，请重试。');
      state.catalog = await response.json();
      $('categories').innerHTML = [['all','全部 Skill'],['操作线补贴','操作线补贴'],['全区域奖金','全区域奖金']].map(([key,label]) => `<button data-category="${escape(key)}" aria-pressed="${key === state.category}">${label}<span>${state.catalog.skills.filter((item) => key === 'all' || item.category === key).length}</span></button>`).join('');
      $('lastUpdated').textContent = `最近同步 ${dateLabel(state.catalog.updated_at)}`;
      $('downloadAll').hidden = false;
      render();
      const params = new URLSearchParams(location.hash.slice(1));
      if (params.get('view') === 'guide') {
        if (skillById(params.get('subject'))) state.guideSubject = params.get('subject');
        if (/^[1-9]\d{3}-(0[1-9]|1[0-2])$/.test(params.get('month') || '')) state.guideMonth = params.get('month');
        usage();
      } else if (params.get('skill')) detail(params.get('skill'));
    } catch (error) {
      $('error').innerHTML = `${escape(error.message)} <button class="button secondary" id="retry">重试</button>`;
      $('error').hidden = false;
      $('skillCards').innerHTML = '';
      $('resultCount').textContent = '加载失败';
    }
  }

  document.addEventListener('click', async (event) => {
    const detailButton = event.target.closest('[data-detail]');
    const category = event.target.closest('[data-category]');
    if (detailButton) detail(detailButton.dataset.detail);
    if (category) { state.category = category.dataset.category; render(); }
    const usageButton = event.target.closest('[data-usage]');
    if (usageButton) usage(usageButton.dataset.usage);
    const guideCopy = event.target.closest('[data-guide-copy]');
    if (guideCopy && state.catalog) {
      const kind = guideCopy.dataset.guideCopy;
      const target = $(`${kind}PromptStatus`);
      try { await navigator.clipboard.writeText(DomesticSkillGuide.prompt(kind, skillById(state.guideSubject), state.guideMonth)); target.innerHTML = `${actionIcon('check')}已复制`; }
      catch { target.textContent = '复制失败，请手动复制对话示例。'; }
    }
    if (event.target.closest('#retry')) load();
    const copy = event.target.closest('#copyCommand');
    if (copy) {
      try { await navigator.clipboard.writeText(copy.dataset.command); $('copyStatus').innerHTML = `${actionIcon('check')}已复制`; }
      catch { $('copyStatus').textContent = '复制失败，请选中命令手动复制。'; }
    }
  });
  $('search').addEventListener('input', (event) => { state.query = event.target.value.trim(); render(); });
  $('sort').addEventListener('change', (event) => { state.sort = event.target.value; render(); });
  $('clearSearch').addEventListener('click', () => { state.query = ''; state.category = 'all'; $('search').value = ''; render(); });
  document.addEventListener('change', event => {
    if (event.target.id === 'guideSubject') state.guideSubject = event.target.value;
    else if (event.target.id === 'guideMonth') {
      if (!event.target.value) { event.target.value = state.guideMonth; return; }
      state.guideMonth = event.target.value;
    } else return;
    render();
    rememberGuide();
  });
  const switchView = (view) => { state.view = view; render(); history.replaceState(null, '', location.pathname); };
  $('catalogTab').addEventListener('click', () => switchView('catalog'));
  $('releaseTab').addEventListener('click', () => switchView('releases'));
  $('guideTab').addEventListener('click', () => usage());
  $('usageButton').addEventListener('click', () => usage());
  $('closeDialog').addEventListener('click', () => $('detailDialog').close());
  $('detailDialog').addEventListener('close', () => { if (state.view !== 'guide') history.replaceState(null, '', location.pathname); });
  SkillHubUI.enhance(document, subjectIcons);
  load();
})();
