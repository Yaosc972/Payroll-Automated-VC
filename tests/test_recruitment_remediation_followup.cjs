const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const script = name => fs.readFileSync(path.join(__dirname, '../bonus_platform/static/', name), 'utf8');

test('the primary summary counts work items alongside policy items', () => {
  const window = {};
  vm.runInNewContext(script('recruitment-experience.js'), {window});
  const data = {revision: 4, rows: [{id: 'a'}], sources: [], monthly: {
    actionCount: 11, operatorActionCount: 9, ruleActionCount: 2,
    coverage: {hasOpening: true}, worksheet: {rows: [{current: true}]}}};
  const result = window.RecruitmentExperience.model(data, {status: 'complete', revision: 4});
  assert.equal(result.steps[1].note, '9 项待办 · 2 项制度');
  assert.match(result.progress.detail, /9 项待办 · 2 项制度/);
});

test('the existing review toolbar counts concrete review items', () => {
  const nodes = new Map();
  const $ = id => {
    if (!nodes.has(id)) nodes.set(id, {html: '', querySelector: () => null,
      insertAdjacentHTML(position, html) { this.html += html; }});
    return nodes.get(id);
  };
  const window = {RecruitmentWorkbench: {$, ui: {data: {revision: 4, sources: []}},
    e: String, base: () => '/fixture', request: () => new Promise(() => {})}};
  vm.runInNewContext(script('recruitment-review-center.js'), {window, URLSearchParams,
    document: {querySelectorAll: () => []}});
  window.RecruitmentReviewCenter.render({workItems: Array.from({length: 11}, () => ({current: true}))}, () => {});
  assert.match($('draftContent').html, /核对事项 · 11 项/);
  assert.doesNotMatch($('draftContent').html, /资料待办|11 类/);
});
