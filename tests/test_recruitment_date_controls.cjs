const test=require('node:test');
const assert=require('node:assert/strict');
const {parse,addDays,addMonths,monthDays}=require('../bonus_platform/static/recruitment-date-controls.js');

test('manual date input accepts ordinary business date formats and normalizes them',()=>{
  for(const value of ['2026-08-01','2026/8/1','2026.8.1','2026年8月1日','20260801'])assert.equal(parse(value),'2026-08-01');
  for(const value of ['', '2026-02-29','2026-04-31','2026-13-01','2026-00-01','0000-01-01','text'])assert.equal(parse(value),null);
});
test('leap days and early years use the entered year without a 1900 offset',()=>{
  assert.equal(parse('2024-02-29'),'2024-02-29');
  assert.equal(parse('2000-02-29'),'2000-02-29');
  assert.equal(parse('1900-02-29'),null);
  assert.equal(parse('0099-01-01'),'0099-01-01');
});
test('calendar has six complete weeks with correct adjacent month dates',()=>{
  const dates=monthDays(2026,7);
  assert.equal(dates.length,42);assert.equal(dates[0],'2026-07-26');assert.equal(dates.at(-1),'2026-09-05');
  assert.equal(new Set(dates).size,42);
  assert.equal(dates.filter(value=>value.startsWith('2026-08')).length,31);
});
test('month navigation clamps to the last day and supports year boundaries',()=>{
  assert.equal(addMonths('2026-01-31',1),'2026-02-28');
  assert.equal(addMonths('2024-01-31',1),'2024-02-29');
  assert.equal(addMonths('2026-12-31',1),'2027-01-31');
  assert.equal(addMonths('2024-02-29',-12),'2023-02-28');
});
test('keyboard day and week movements preserve dates across month and leap boundaries',()=>{
  assert.equal(addDays('2026-08-01',-1),'2026-07-31');
  assert.equal(addDays('2024-02-28',1),'2024-02-29');
  assert.equal(addDays('2026-12-30',7),'2027-01-06');
});
