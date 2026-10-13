(() => {
  const launcher = document.getElementById('policyLauncher');
  if (!launcher || document.documentElement.dataset.moduleId !== 'home') return;
  const feedbackLauncher = document.getElementById('feedbackLauncher');
  const userMenu = document.getElementById('dashboardUserMenu');
  if (feedbackLauncher?.closest('.dashboard-topbar')) {
    feedbackLauncher.before(launcher);
    if (userMenu) feedbackLauncher.after(userMenu);
  }
  const drawer = document.createElement('dialog');
  drawer.id = 'policyDrawer';
  drawer.className = 'policy-drawer';
  drawer.setAttribute('aria-labelledby', 'policyTitle');
  drawer.innerHTML = `
    <header class="policy-header">
      <h2 id="policyTitle">政策资讯</h2>
      <form role="search" aria-label="搜索政策"><input name="q" type="search" aria-label="搜索地区或政策关键词" placeholder="搜索地区、政策关键词" maxlength="100" autocomplete="off" /><select name="category" aria-label="政策类型"><option value="">全部类型</option><option value="社保">社保</option><option value="医保">医保</option><option value="公积金">公积金</option></select></form>
      <button type="button" class="policy-close" aria-label="关闭政策资讯">×</button>
    </header>
    <section class="policy-health" aria-label="政策抓取状态" hidden></section>
    <div class="policy-status" role="status" aria-live="polite" hidden></div>
    <div class="policy-body">
      <div class="policy-results" aria-live="polite"></div>
      <button class="policy-more" type="button" hidden>加载更多</button>
    </div>`;
  document.body.append(drawer);
  const form = drawer.querySelector('form');
  const results = drawer.querySelector('.policy-results');
  const status = drawer.querySelector('.policy-status');
  const health = drawer.querySelector('.policy-health');
  const more = drawer.querySelector('.policy-more');
  let controller, timer, offset = 0, previousOverflow;
  const node = (tag, className, text) => {
    const el = document.createElement(tag);
    el.className = className;
    el.textContent = text;
    return el;
  };
  const formatTime = value => {
    const date = new Date(value);
    return value && Number.isFinite(date.getTime())
      ? new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(date)
      : '尚无记录';
  };
  const reason = code => {
    if (!code) return '';
    const partial = /^article_fetch_failed:(\d+):(.+)$/.exec(code);
    if (partial) return `${partial[1]} 篇详情读取失败：${reason(partial[2])}`;
    const messages = {
      ConnectError: '无法连接来源网站', ConnectTimeout: '连接来源网站超时',
      ReadTimeout: '来源网站响应超时', ReadError: '来源网站传输中断',
      no_article_links: '未解析到文章链接，需检查来源栏目',
      publication_missing: '未读取到官方发布日期', article_fetch_failed: '部分文章详情读取失败',
      unexpected_content: '来源返回的内容不是网页', response_too_large: '来源响应超出读取限制',
      tls_verification_failed: '来源网站证书验证失败'
    };
    return messages[code] || (/^HTTP \d{3}$/.test(code) ? `来源网站返回 ${code}` : '来源读取异常');
  };
  const renderHealth = sources => {
    health.hidden = false;
    if (!Array.isArray(sources) || !sources.length) {
      health.replaceChildren(node('p', 'policy-health-warning', '抓取状态暂不可用，无法确认政策是否已更新。'));
      return;
    }
    const stale = source => {
      const checked = Date.parse(source.checked_at);
      return !Number.isFinite(checked) || Date.now() - checked > 3 * 60 * 60 * 1000;
    };
    const counts = { ok: 0, error: 0, partial: 0, pending: 0, stale: 0 };
    for (const source of sources) {
      const state = ['ok', 'error', 'partial'].includes(source.state) ? source.state : 'pending';
      counts[state]++;
      if (state !== 'pending' && stale(source)) counts.stale++;
    }
    const parts = [`成功 ${counts.ok}`];
    if (counts.error) parts.push(`失败 ${counts.error}`);
    if (counts.partial) parts.push(`部分失败 ${counts.partial}`);
    if (counts.pending) parts.push(`待首次抓取 ${counts.pending}`);
    if (counts.stale) parts.push(`检查超时 ${counts.stale}`);
    const warning = counts.error || counts.partial || counts.pending || counts.stale;
    const overview = node('p', warning ? 'policy-health-warning' : 'policy-health-ok', `更新状态：${parts.join(' · ')}`);
    const checked = sources.map(source => Date.parse(source.checked_at)).filter(Number.isFinite);
    const latest = checked.length ? new Date(Math.max(...checked)).toISOString() : '';
    const time = node('p', 'policy-health-time', `最近抓取检查：${formatTime(latest)}（北京时间）`);
    const details = node('details', 'policy-sources', '');
    const summary = node('summary', '', `查看 ${sources.length} 个官方来源及抓取记录`);
    const list = node('div', 'policy-source-list', '');
    const labels = { ok: '抓取成功', error: '抓取失败', partial: '部分失败', pending: '待首次抓取' };
    for (const source of sources) {
      const row = node('article', 'policy-source-row', '');
      const heading = node('div', 'policy-source-heading', '');
      const link = node('a', '', source.name);
      try {
        const url = new URL(source.url);
        if (url.protocol === 'https:' && url.hostname.endsWith('.gov.cn')) {
          link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer';
        }
      } catch (_) { /* Unusable source URLs remain visible as plain text. */ }
      const state = labels[source.state] ? source.state : 'pending';
      heading.append(link, node('span', `policy-source-state policy-source-${state}`, labels[state]));
      row.append(heading, node('p', '', `${source.region} · ${source.category} · 最近检查：${formatTime(source.checked_at)}`),
        node('p', '', `最近完整成功：${formatTime(source.success_at)}`));
      if (state !== 'pending' && stale(source)) row.append(node('p', 'policy-health-warning', '超过 3 小时未检查，当前更新情况未确认。'));
      if (source.error) row.append(node('p', 'policy-health-warning', reason(source.error)));
      list.append(row);
    }
    details.append(summary, list, node('p', 'policy-source-note', '成功表示完成本次检查，不一定有新政策；失败时保留历史文章。'));
    const wasOpen = health.querySelector('details')?.open;
    details.open = Boolean(wasOpen);
    health.replaceChildren(overview, time, details);
  };
  const load = async (append = false) => {
    controller?.abort();
    controller = new AbortController();
    const current = controller;
    more.hidden = true;
    results.setAttribute('aria-busy', 'true');
    if (!append) { offset = 0; results.replaceChildren(); }
    status.hidden = false;
    status.textContent = '正在读取官方政策…';
    const timeout = setTimeout(() => current.abort(), 15000);
    try {
      const params = new URLSearchParams({ q: form.elements.q.value.trim(), offset: String(offset), category: form.elements.category.value });
      const response = await fetch(`/api/workbench/policies?${params}`, { credentials: 'same-origin', cache: 'no-store', signal: current.signal });
      if (!response.ok) throw new Error(response.status === 401 ? '登录已失效，请重新登录后查看。' : '政策资讯暂不可用，请稍后重试。');
      const data = await response.json();
      if (controller !== current) return;
      status.hidden = true;
      status.textContent = '';
      renderHealth(data.sources);
      for (const item of data.items) {
        const article = node('article', 'policy-article', '');
        const heading = node('h3', '', '');
        const link = node('a', '', item.title);
        const url = new URL(item.url);
        if (url.protocol !== 'https:' || !url.hostname.endsWith('.gov.cn')) continue;
        link.href = url.href;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.title = '在新窗口查看官方原文';
        heading.append(link);
        const meta = node('div', 'policy-meta', '');
        const published = node('time', 'policy-date', item.publishedAt || '日期未明确');
        if (item.publishedAt) published.dateTime = item.publishedAt;
        const source = node('span', 'policy-origin', item.source);
        source.title = item.source;
        meta.append(node('span', 'policy-tag', item.region), node('span', 'policy-tag policy-tag-category', item.category), published, source);
        article.append(meta, heading);
        results.append(article);
      }
      offset += data.items.length;
      if (!offset) {
        results.append(node('p', 'policy-empty', form.elements.q.value.trim() ? '暂无匹配政策，试试其他地区或关键词。' : '暂无政策资讯。'));
      }
      more.hidden = !data.hasMore;
    } catch (error) {
      if (controller !== current || !drawer.open) return;
      status.hidden = false;
      status.textContent = error.name === 'AbortError' ? '读取超时，请重试。' : error.message;
      const retry = node('button', 'policy-retry', '重新加载');
      retry.type = 'button';
      retry.addEventListener('click', () => load(false));
      results.append(retry);
    } finally {
      clearTimeout(timeout);
      if (controller === current) results.removeAttribute('aria-busy');
    }
  };
  form.elements.q.addEventListener('input', () => {
    clearTimeout(timer);
    controller?.abort();
    controller = null;
    timer = setTimeout(() => load(false), 300);
  });
  form.addEventListener('submit', event => { event.preventDefault(); clearTimeout(timer); load(false); });
  form.elements.category.addEventListener('change', () => { clearTimeout(timer); load(false); });
  more.addEventListener('click', () => load(true));
  launcher.addEventListener('click', () => {
    if (drawer.open) return;
    health.hidden = true;
    previousOverflow = document.body.style.overflow;
    drawer.showModal();
    document.body.style.overflow = 'hidden';
    launcher.setAttribute('aria-expanded', 'true');
    drawer.querySelector('.policy-close').focus();
    load(false);
  });
  drawer.querySelector('.policy-close').addEventListener('click', () => drawer.close());
  drawer.addEventListener('click', event => {
    if (event.target !== drawer) return;
    const rect = drawer.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) drawer.close();
  });
  drawer.addEventListener('keydown', event => {
    if (event.key === 'Escape') { event.preventDefault(); drawer.close(); }
  });
  drawer.addEventListener('close', () => {
    clearTimeout(timer);
    controller?.abort();
    controller = null;
    document.body.style.overflow = previousOverflow;
    launcher.setAttribute('aria-expanded', 'false');
    launcher.focus({ preventScroll: true });
  });
})();
