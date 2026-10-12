const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const script = fs.readFileSync(path.join(__dirname, '../bonus_platform/static/social-insurance.js'), 'utf8');
const renderer = 'function renderReportValidation' + script.split('  function renderReportValidation', 2)[1].split('  async function revalidateReport', 1)[0];
function render(state) {
  const nodes = new Map();
  const byId = id => {
    if (!nodes.has(id)) nodes.set(id, { replaceChildren() {}, classList: { toggle() {} } });
    return nodes.get(id);
  };
  vm.runInNewContext(renderer + '\nrenderReportValidation();', { state, byId });
  return { title: byId('reportValidationTitle').textContent, disabled: byId('revalidateReport').disabled };
}

test('initial empty batch renders safely without a validation error', () => {
  const result = render({ run: null, operation: null });
  assert.equal(result.title, '生成前请校验最新模板与资料');
  assert.equal(result.disabled, true);
});
test('clearing the batch during subject switching tolerates a cleared error', () => {
  assert.equal(render({ run: null, reportValidationError: null }).disabled, true);
});
test('a prior subject error does not replace the new subject validation', () => {
  const result = render({ run: { id: 'new', reportValidation: { passed: true, issues: [] } }, reportValidationError: { runId: 'old', message: '旧主体错误' } });
  assert.match(result.title, /校验通过/);
  assert.equal(result.disabled, false);
});
test('an error belonging to the current batch remains visible', () => {
  assert.equal(render({ run: { id: 'current' }, reportValidationError: { runId: 'current', message: '模板转换失败' } }).title, '校验未完成：模板转换失败。请处理后重新校验。');
});
