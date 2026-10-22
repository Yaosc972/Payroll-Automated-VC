const test = require('node:test');
const assert = require('node:assert/strict');
const model = require('../bonus_platform/static/recruitment-adjustment-model.js');

test('positive business input maps supplement and deduction to opposite ledger amounts', () => {
  assert.equal(model.signedAmount('25.50', 'supplement'), 25.5);
  assert.equal(model.signedAmount('25.50', 'deduct'), -25.5);
});

test('negative, empty and invalid amounts cannot silently reverse or create an adjustment', () => {
  for (const value of ['', ' ', '0', '-25', 'NaN', 'Infinity', 'abc']) {
    assert.throws(() => model.signedAmount(value, 'deduct'), /大于 0/);
  }
  assert.throws(() => model.signedAmount('25', 'unknown'), /补发或扣回/);
});

test('deduction retains the selected employee, recipient, month and approval without mutating the form', () => {
  const values = {rowId:'person-1', recipientId:'payee-1', month:202608, amount:'25.50',
    direction:'deduct', evidence:{sourceId:'approval-1', pageNumbers:[2], scopeChecked:true}};
  const payload = model.adjustment(values);
  assert.deepEqual(payload, {...values, amount:-25.5, type:'adjustment'});
  assert.equal(values.amount, '25.50');
});
