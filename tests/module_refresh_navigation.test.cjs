const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const read = name => fs.readFileSync(`bonus_platform/static/${name}.js`, 'utf8');
const section = (source, start, end) => source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start)));

for (const view of ['canbuBatches', 'canbuWorkbench', 'rulePackage']) {
  test(`domestic refresh displays ${view} before the activity request finishes`, async () => {
    let resolve;
    const state = { view: 'home', navigationRevision: 0 };
    const context = vm.createContext({ state, URLSearchParams, el: { canbuWorkbenchRoot: {} },
      location: { hash: `#view=${view}&activity=a&step=results` }, restoringPayrollPage: true,
      loadEngineCards(){}, loadTemplateLinks(){}, bindEvents(){}, setDefaultMonth(){}, setDefaultCanbuBatchMonth(){},
      renderEmptyWorkbench(){}, renderRecentBatchTable(){}, setupActivityList(){}, rememberPayrollPage(){},
      showView(value){ state.view=value; state.navigationRevision++; },
      refreshActivities: () => new Promise(r => { resolve=r; }), restorePayrollPage(){},
    });
    vm.runInContext(section(read('domestic-labor'), 'async function init()', 'function setDefaultMonth('), context);
    const pending = context.init();
    assert.equal(state.view, view);
    resolve(); await pending;
    assert.equal(state.view, view);
  });
}

test('FBU restores only the activity and step explicitly present in the URL', async () => {
  const source = read('fbu-performance');
  for (const hash of ['', '#view=activities', '#view=workbench&activity=run_a&step=salary']) {
    let initialize;
    const calls = [];
    const context = vm.createContext({ URLSearchParams, location: { hash }, state: { navigationRevision: 0 },
      el: { pages: { workbench: {}, activities: {} }, workbenchContent: {} },
      document: { addEventListener: (_, fn) => { initialize=fn; } }, setSidebarCollapsed(){},
      navigateTo: page => calls.push(page), loadActivities: async () => {},
      enterActivity: async (id, options) => { calls.push([id, options.initialStep]); return {}; },
    });
    vm.runInContext(source.slice(source.lastIndexOf("document.addEventListener('DOMContentLoaded'")), context);
    await initialize();
    assert.deepEqual(calls, hash.includes('run_a') ? [['run_a', 'salary']] : ['activities']);
  }
});

test('FBU startup does not override navigation while the activity list is loading', async () => {
  let initialize, resolve, opened = false;
  const state = { navigationRevision: 0 };
  const context = vm.createContext({ URLSearchParams, location: { hash: '#view=workbench&activity=run_a&step=salary' }, state,
    el: { pages: { workbench: {}, activities: {} }, workbenchContent: {} },
    document: { addEventListener: (_, fn) => { initialize=fn; } }, setSidebarCollapsed(){},
    loadActivities: () => new Promise(r => { resolve=r; }), enterActivity: () => { opened=true; },
  });
  const source = read('fbu-performance');
  vm.runInContext(source.slice(source.lastIndexOf("document.addEventListener('DOMContentLoaded'")), context);
  const pending = initialize(); state.navigationRevision++; resolve(); await pending;
  assert.equal(opened, false);
});

test('recruitment refresh restores the selected run instead of the newest run', async () => {
  const location = { pathname: '/recruitment.html', search: '', hash: '#run=older' };
  const state = { currentRun: null };
  const context = vm.createContext({ state, location, URLSearchParams,
    history: { replaceState: (_, __, url) => { location.hash = new URL(url, 'https://example.test').hash; } },
    requestJson: async () => ({ runs: [{ id: 'newest' }, { id: 'older' }] }),
    elements: { runList: {} }, renderRunList(){}, renderRun(){}, loadTableData: async () => {}, escapeHtml: String,
    bindEvents(){}, syncRunsPanelState(){}, renderIcons(){},
  });
  const source = read('app');
  vm.runInContext(section(source, 'async function loadRuns(', 'function renderRun('), context);
  vm.runInContext(section(source, 'function init()', 'function bindEvents('), context);
  context.init();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(state.currentRun.id, 'older');
  assert.equal(location.hash, '#run=older');
});

test('employee activity restores once and ignores an older navigation response', async () => {
  const runs = [], requests = new Map(), nodes = new Map();
  const context = vm.createContext({ URLSearchParams,
    location: { search: '?activity=older', hash: '#meal-allowance' },
    routeVersion: 0, timer: null, openedId: '', titles: { 'meal-allowance': '集团技术部餐补' },
    api: '/api/china-employee-payroll/activities', clearInterval(){}, syncViews(){},
    document: { getElementById(id) { if (!nodes.has(id)) nodes.set(id, {}); return nodes.get(id); } },
    history: { replaceState(){} }, href: a => '?activity=' + a.activityId,
    request: url => new Promise(resolve => requests.set(url.split('/').pop(), resolve)),
    loadList(){}, showActivity(a) { context.openedId = a.activityId; runs.push(a.activityId); },
  });
  const source = read('payroll-activities');
  vm.runInContext(section(source, 'async function route()', 'window.PayrollActivities ='), context);
  const older = context.route();
  context.location.search = '?activity=newer';
  const newer = context.route();
  requests.get('newer')({ activityId: 'newer' }); await newer;
  requests.get('older')({ activityId: 'older' }); await older;
  await context.route();
  assert.deepEqual(runs, ['newer']);
  assert.equal(requests.size, 2);
});

test('social insurance accepts only known restored views', () => {
  const source = read('social-insurance');
  for (const [hash, expected] of [['#view=template', 'template'], ['#view=source', 'source'], ['#view=unknown', 'business']]) {
    const context = vm.createContext({ URLSearchParams, location: { hash } });
    vm.runInContext(section(source, 'const state = {', 'const byId =') + ';globalThis.result = state.view;', context);
    assert.equal(context.result, expected);
  }
});

test('overseas results navigation retains run query and records the visible page', () => {
  const location = { pathname: '/overseas-labor.html', search: '?run=existing', hash: '' };
  const context = vm.createContext({ location, laborState: { run: { id: 'existing' } },
    history: { replaceState: (_, __, url) => { location.hash = new URL(url, 'https://example.test').hash; } },
    labor: { toolbench: {}, resultsView: {} }, document: { body: { style: {} } },
    window: { requestAnimationFrame(){}, scrollTo(){} },
  });
  vm.runInContext(section(read('overseas-labor'), 'function showLaborToolbench()', 'async function restoreLaborRunFromUrl()'), context);
  context.showLaborResultsView();
  assert.equal(location.hash, '#view=results');
  context.showLaborToolbench();
  assert.equal(location.hash, '#view=toolbench');
  assert.equal(location.search, '?run=existing');
});
