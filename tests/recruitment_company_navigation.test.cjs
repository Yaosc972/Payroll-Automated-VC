const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const read = name => fs.readFileSync(`bonus_platform/static/${name}`, 'utf8');

function node() {
  const classes = new Set();
  return {
    hidden: true, children: [], href: '', textContent: '',
    classList: { add: value => classes.add(value), toggle(value, enabled) { enabled ? classes.add(value) : classes.delete(value); }, contains: value => classes.has(value) },
    append(child) { this.children.push(child); },
    addEventListener(event, handler) { this[event] = handler; },
  };
}

for (const destination of ['explicit', 'known', 'fallback']) {
  test(`feedback mounts once in the ${destination} header without a second navigation bar`, () => {
    const launcher = node(), slot = node(), known = node(), body = node();
    body.prepend = child => body.children.unshift(child);
    const created = [];
    const document = {
      body,
      querySelector(selector) {
        if (selector === '[data-feedback-slot]') return destination === 'explicit' ? slot : null;
        if (selector.startsWith('.app-chrome')) return destination !== 'fallback' ? known : null;
        return null;
      },
      createElement() { const item = node(); created.push(item); return item; },
    };
    const source = read('feedback-widget.js');
    vm.runInNewContext(source.slice(source.indexOf('const mountLauncher ='), source.indexOf('  const drawer =')), { document, launcher });
    const target = destination === 'explicit' ? slot : destination === 'known' ? known : created[0];
    assert.deepEqual(target.children, [launcher]);
    assert.equal(body.children.length, destination === 'fallback' ? 1 : 0);
    assert.equal(known.children.length, destination === 'known' ? 1 : 0);
  });
}

function historyPage(search = '', hash = '') {
  const elements = new Map();
  const document = { body: node(), getElementById(id) { if (!elements.has(id)) elements.set(id, node()); return elements.get(id); } };
  vm.runInNewContext(read('recruitment-history.js'), {
    document, URL, URLSearchParams,
    location: { href: `https://example.test/recruitment-history.html${search}${hash}`, search, hash },
  });
  return { document, get: id => document.getElementById(id) };
}

test('history opens in archive mode and compatibility calculation requires its own entry', () => {
  const page = historyPage();
  assert.equal(page.document.body.classList.contains('legacy-calculation'), false);
  assert.equal(page.get('legacyPageTitle').textContent, '历史批次');
  assert.equal(page.get('legacyReturnActivity').hidden, true);
  assert.equal(new URL(page.get('legacyModeLink').href).search, '?mode=legacy');
  const legacy = historyPage('?mode=legacy');
  assert.equal(legacy.document.body.classList.contains('legacy-calculation'), true);
  assert.equal(legacy.get('legacyPageTitle').textContent, '旧版核算（兼容）');
  assert.equal(new URL(legacy.get('legacyModeLink').href).search, '');
});

test('archive and compatibility navigation retain the activity, month, tab and selected old run', () => {
  const search = '?activity=act_preview&month=2026-09&view=records&trial=1';
  const page = historyPage(search, '#run=older');
  const back = new URL(page.get('legacyReturnActivity').href);
  assert.equal(page.get('legacyReturnActivity').hidden, false);
  assert.equal(back.pathname, '/recruitment.html');
  assert.deepEqual(Object.fromEntries(back.searchParams), Object.fromEntries(new URLSearchParams(search)));
  assert.equal(back.hash, '');
  const legacyUrl = new URL(page.get('legacyModeLink').href);
  assert.equal(legacyUrl.hash, '#run=older');
  const legacy = historyPage(legacyUrl.search, legacyUrl.hash);
  assert.deepEqual(Object.fromEntries(new URL(legacy.get('legacyModeLink').href).searchParams), Object.fromEntries(new URLSearchParams(search)));
  assert.equal(new URL(legacy.get('legacyModeLink').href).hash, '#run=older');
});

test('history return links ignore malformed context and external redirect parameters', () => {
  const page = historyPage('?activity=https://evil.test&month=2026-13&view=../../&next=https://evil.test');
  assert.equal(page.get('legacyReturnActivity').hidden, true);
  assert.equal(new URL(page.get('legacyModeLink').href).origin, 'https://example.test');
  assert.equal(new URL(page.get('legacyModeLink').href).search, '?mode=legacy');
});

test('workbench auxiliary links follow the current activity and the newly selected month', () => {
  const elements = new Map(['recruitmentGuide', 'recruitmentHistory', 'draftMonth'].map(id => [id, node()]));
  elements.get('draftMonth').value = '2026-10';
  const document = { getElementById: id => elements.get(id), addEventListener(event, handler) { this[event] = handler; } };
  const location = { href: 'https://example.test/recruitment.html?activity=act_preview&month=2026-09&view=records&trial=1', search: '?activity=act_preview&month=2026-09&view=records&trial=1' };
  vm.runInNewContext(read('recruitment-guide-link.js'), { document, location, URL, URLSearchParams });
  const history = elements.get('recruitmentHistory');
  assert.equal(new URL(history.href).search, '?activity=act_preview&month=2026-10&trial=1&view=records');
  assert.equal(new URL(elements.get('recruitmentGuide').href).searchParams.has('view'), false);
  location.search = '?activity=another&month=2026-11';
  elements.get('draftMonth').value = '2026-11';
  document['recruitment:render']();
  assert.equal(new URL(history.href).search, '?activity=another&month=2026-11');
});

test('archive view keeps all old batch downloads and their server URLs', () => {
  const links = [], grid = { appendChild: item => links.push(item) };
  const context = {
    elements: { downloadGrid: grid }, document: { createElement: node },
    fileDisplayName: file => file.filename, escapeHtml: String, renderIcons() {},
  };
  const source = read('app.js');
  vm.runInNewContext(source.slice(source.indexOf('function renderDownloads('), source.indexOf('function updatePrimaryDownloads(')), context);
  const keys = ['input', 'sourceReport', 'initialResult', 'pending', 'confirmation', 'finalResult'];
  const files = Object.fromEntries(keys.map(key => [key, { filename: `${key}.xlsx`, downloadUrl: `/api/runs/fixture/files/${key}` }]));
  context.renderDownloads({ files });
  assert.deepEqual(links.map(item => item.href), keys.map(key => files[key].downloadUrl));
  assert.deepEqual(links.map(item => item.download), keys.map(key => files[key].filename));
  context.renderDownloads({ files: {} });
  assert.match(grid.innerHTML, /此批次暂无可下载文件/);
});
