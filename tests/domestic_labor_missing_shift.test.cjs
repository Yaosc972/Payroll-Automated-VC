const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('bonus_platform/static/domestic-labor.js', 'utf8');
const functions = source.slice(source.indexOf('function resolveMissingShiftPeriod('), source.indexOf('function bindNightShiftMissingPanel('));
function collect(shiftTime, start, end) {
  const context = vm.createContext({
    state: { currentResults: [], activeNightShiftMissingCode: 'HD061' },
    document: { querySelectorAll: () => [{ querySelector: selector => ({value: selector.includes('startTime') ? start : end}) }] },
  });
  vm.runInContext(functions, context);
  return JSON.parse(JSON.stringify(context.collectMissingShiftBreakSegments({shiftCode:'HD061',shiftTime})));
}
test('preflight confirmation uses displayed shift even before results exist', () => {
  assert.deepEqual(collect('13:00-21:30;', '18:00', '18:30'), [{period:'18:00-18:30',category:'其他休息'}]);
});
test('overnight rest retains next-day assignment', () => {
  assert.deepEqual(collect('23:30-32:00;', '06:00', '06:30'), [{period:'30:00-30:30',category:'早上休息'}]);
});
test('genuinely missing shift time remains blocked', () => {
  assert.throws(() => collect('', '18:00', '18:30'), /缺少排班起始时间/);
});
test('invalid rest interval remains blocked', () => {
  assert.throws(() => collect('13:00-21:30;', '18:00', '18:00'), /不能相同/);
});

test('successfully recalculated supplementary shifts no longer appear as configuration tasks', () => {
  const start = source.indexOf('function getMissingNightShiftGroups(');
  const end = source.indexOf('function defaultNightShiftEffectiveDate(', start);
  const context = vm.createContext({
    getNightShiftDetails: row => row.details,
    formatNightShiftAttendanceDate: value => value,
  });
  vm.runInContext(source.slice(start, end), context);
  const row = daily => ({employee_id:'test',details:{daily_results:[daily]}});
  const shift = {shift_code:'HD061',shift_time:'13:00-21:30',attendance_date:'2026-08-31'};
  assert.equal(context.getMissingNightShiftGroups([row({...shift,reason_code:'calculated'})]).length,0);
  assert.equal(context.getMissingNightShiftGroups([row({...shift,reason_code:'shift_break_config_missing'})]).length,1);
});
