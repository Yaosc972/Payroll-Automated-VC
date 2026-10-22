const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../bonus_platform/static/recruitment-trial.js'), 'utf8');
const settle = () => new Promise(resolve => setImmediate(resolve));
const empty = month => ({month, revision: 0, sources: [], rows: [], previousAccepted: false});
const existing = month => ({...empty(month), revision: 1, sources: [{id: 'saved'}]});

function screen(respond) {
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, {id, value: '', textContent: '', hidden: false, disabled: false, isConnected: true});
    return elements.get(id);
  };
  element('draftMonth').value = '2026-07';
  const calls = [];
  const location = {search: '?month=2026-07', href: ''};
  const storage = new Map();
  const w = {
    $: element, ui: {data: null, busy: false}, e: String,
    request: async (url, options) => {calls.push({url, options}); return respond(url, options);},
    openDialog: (_title, html) => {
      for (const item of elements.values()) if (item.id.startsWith('trial')) item.isConnected = false;
      for (const match of html.matchAll(/<[a-z]+\b[^>]*\bid="([^"]+)"[^>]*>/g)) {
        const item = {id: match[1], value: /\bvalue="([^"]*)"/.exec(match[0])?.[1] || '', textContent: '',
          hidden: /\bhidden\b/.test(match[0]), disabled: /\bdisabled\b/.test(match[0]), isConnected: true};
        elements.set(item.id, item);
      }
    }
  };
  const window = {RecruitmentWorkbench: w};
  vm.runInNewContext(source, {window, location, URLSearchParams,
    document: {addEventListener() {}},
    localStorage: {getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value)}});
  return {element, calls, location, open: () => window.RecruitmentTrial.newCalculation(),
    submit: () => element('trialForm').onsubmit({preventDefault() {}, submitter: element('trialCreate')})};
}

test('an unused month opens monthly intake and never creates an independent record', async () => {
  const app = screen(() => ({...empty(202607), previousAccepted: true}));
  app.open(); await settle();
  assert.match(app.element('trialNewLimit').textContent, /自动承接上月已确认/);
  assert.equal(app.element('trialTitleLabel').hidden, true);
  await app.submit();
  assert.equal(app.calls.length, 2);
  assert.ok(app.calls.every(call => !call.options));
  assert.equal(app.location.href, 'recruitment.html?month=2026-07&view=sources');
});

test('an existing month explains the limit and creates a separate empty record', async () => {
  const app = screen((url, options) => options ? {id: 'new-record', month: 202607} : existing(202607));
  app.open(); await settle();
  assert.match(app.element('trialNewNotice').textContent, /保留原记录/);
  assert.match(app.element('trialNewLimit').textContent, /采用为本月结果，供下月承接/);
  assert.equal(app.element('trialTitleLabel').hidden, false);
  app.element('trialTitle').value = '重算'; await app.submit();
  const writes = app.calls.filter(call => call.options);
  assert.equal(writes.length, 1);
  assert.equal(writes[0].url, '/api/recruitment/trials');
  assert.deepEqual(JSON.parse(writes[0].options.body), {month: 202607, name: '重算'});
  assert.match(app.location.href, /view=sources&trial=new-record/);
});

test('a slow response for the previous month cannot replace the newly selected month', async () => {
  let releaseJuly;
  const app = screen(url => url.endsWith('202607') ? new Promise(resolve => {releaseJuly = resolve;}) : empty(202608));
  app.open();
  app.element('trialMonth').value = '2026-08'; await app.element('trialMonth').onchange();
  releaseJuly(existing(202607)); await settle();
  assert.match(app.element('trialNewNotice').textContent, /还没有核算资料/);
  assert.equal(app.element('trialTitleLabel').hidden, true);
  await app.submit();
  assert.equal(app.location.href, 'recruitment.html?month=2026-08&view=sources');
  assert.ok(app.calls.every(call => !call.options));
});

test('submit rechecks the month before it can change from ordinary intake to a separate record', async () => {
  let reads = 0;
  const app = screen((_url, options) => options ? {id: 'new-record', month: 202607} : ++reads === 1 ? empty(202607) : existing(202607));
  app.open(); await settle(); await app.submit();
  assert.equal(app.location.href, '');
  assert.ok(app.calls.every(call => !call.options));
  assert.match(app.element('trialError').textContent, /本月记录已更新/);
  assert.match(app.element('trialNewNotice').textContent, /本月已有核算记录/);
  await app.submit();
  assert.equal(app.calls.filter(call => call.options).length, 1);
  assert.match(app.location.href, /trial=new-record/);
});

test('recalculation carries the reviewed, confirmed previous month into the new record', async () => {
  const opening = {month: 202606, revision: 4, confirmedAt: '2026-07-01'};
  const app = screen((_url, options) => options ? {id: 'new-record', month: 202607}
    : {...existing(202607), previousConfirmed: opening, parentOutdated: true});
  app.open(); await settle();
  assert.match(app.element('trialNewLimit').textContent, /自动带入2026年6月最新已确认结果/);
  await app.submit();
  const payload = JSON.parse(app.calls.find(call => call.options).options.body);
  assert.deepEqual(payload.opening, {month: 202606, revision: 4});
});

test('an updated previous-month confirmation must be shown before creating the new record', async () => {
  let reads = 0;
  const app = screen((_url, options) => options ? {id: 'new-record', month: 202607}
    : {...existing(202607), previousConfirmed: {month: 202606, revision: ++reads === 1 ? 3 : 4}});
  app.open(); await settle(); await app.submit();
  assert.equal(app.location.href, '');
  assert.ok(app.calls.every(call => !call.options));
  assert.match(app.element('trialError').textContent, /上月核算结果已更新/);
  await app.submit();
  assert.equal(JSON.parse(app.calls.find(call => call.options).options.body).opening.revision, 4);
});
