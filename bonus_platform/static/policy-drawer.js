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
    <div class="policy-status" role="status" aria-live="polite" hidden></div>
    <div class="policy-body">
      <div class="policy-results" aria-live="polite"></div>
      <button class="policy-more" type="button" hidden>加载更多</button>
    </div>`;
  document.body.append(drawer);
  const form = drawer.querySelector('form');
  const results = drawer.querySelector('.policy-results');
  const status = drawer.querySelector('.policy-status');
  const more = drawer.querySelector('.policy-more');
  let controller, timer, offset = 0, previousOverflow;
  const node = (tag, className, text) => {
    const el = document.createElement(tag);
    el.className = className;
    el.textContent = text;
    return el;
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
