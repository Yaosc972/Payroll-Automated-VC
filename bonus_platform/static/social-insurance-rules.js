(() => {
  'use strict';

  const RULES_ENDPOINT = '/api/social-insurance/rules';
  const byId = (id) => document.getElementById(id);
  let catalog = null;

  async function loadRules() {
    const response = await fetch(RULES_ENDPOINT, { credentials: 'same-origin', cache: 'no-store' });
    if (response.status === 401) {
      window.location.href = `login.html?next=${encodeURIComponent(window.location.pathname)}`;
      throw new Error('请先登录 HRAS 全球薪酬核算工作台');
    }
    if (!response.ok) throw new Error('业务规则暂时无法读取，请稍后重试');
    return response.json();
  }

  function textNode(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    node.textContent = text;
    return node;
  }

  function renderHeader(payload) {
    byId('rulesSummary').textContent = payload.summary;
    byId('rulesVersion').textContent = payload.version;
    byId('rulesUpdatedAt').textContent = payload.updatedAt;
    byId('rulesScope').textContent = payload.scope;
    byId('rulesStatus').textContent = payload.status;
  }

  function searchableText(section) {
    return [section.title, section.description, ...section.rules.flatMap((rule) => [rule.title, rule.detail, rule.result])]
      .join(' ').toLowerCase();
  }

  function ruleTone(result) {
    if (/人工|复核|阻止|确认/u.test(result)) return 'warning';
    if (/排除/u.test(result)) return 'muted';
    return 'success';
  }

  function renderSections(query = '') {
    const root = byId('rulesSections');
    root.replaceChildren();
    const normalized = query.trim().toLowerCase();
    const sections = catalog.sections.filter((section) => !normalized || searchableText(section).includes(normalized));
    if (!sections.length) {
      const empty = document.createElement('div');
      empty.className = 'empty-result';
      empty.append(textNode('b', '', '没有找到相关规则'), textNode('span', '', '换一个关键词试试，例如“学历”或“离职”'));
      root.append(empty);
      return;
    }
    sections.forEach((section) => {
      const card = document.createElement('section');
      card.className = 'rule-section';
      card.id = section.id;
      const header = document.createElement('header');
      const number = textNode('span', 'section-number', section.number);
      const copy = document.createElement('div');
      copy.append(textNode('h2', '', section.title), textNode('p', '', section.description));
      header.append(number, copy);
      const list = document.createElement('div');
      list.className = 'rule-list';
      section.rules.forEach((rule) => {
        const item = document.createElement('article');
        item.className = 'rule-item';
        const body = document.createElement('div');
        body.append(textNode('h3', '', rule.title), textNode('p', '', rule.detail));
        item.append(body, textNode('span', `result-chip ${ruleTone(rule.result)}`, rule.result));
        list.append(item);
      });
      card.append(header, list);
      root.append(card);
    });
  }

  function renderHistory(history) {
    const root = byId('rulesHistory');
    root.replaceChildren();
    history.forEach((item, index) => {
      const row = document.createElement('article');
      if (index === 0) row.className = 'current';
      const marker = textNode('span', 'history-marker', index === 0 ? '当前' : '');
      const copy = document.createElement('div');
      copy.append(textNode('b', '', item.version), textNode('time', '', item.date), textNode('p', '', item.change));
      row.append(marker, copy);
      root.append(row);
    });
  }

  async function initialize() {
    try {
      catalog = await loadRules();
      renderHeader(catalog);
      renderSections();
      renderHistory(catalog.history || []);
      byId('ruleSearch').addEventListener('input', (event) => renderSections(event.target.value));
    } catch (error) {
      byId('rulesSections').innerHTML = '<div class="empty-result"><b>规则读取失败</b><span>请刷新页面后重试</span></div>';
      const toast = byId('rulesToast');
      toast.textContent = error.message;
      toast.hidden = false;
    }
  }

  initialize();
})();
