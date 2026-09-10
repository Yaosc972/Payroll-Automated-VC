const test = require('node:test');
const assert = require('node:assert/strict');
const {calculate, supports} = require('../bonus_platform/static/domestic-labor-rulebook.js');
const amount = (id, region, input) => calculate(id, region, input).amount;

test('current examples cannot be presented as historical rules', () => {
  assert.equal(supports({version:'1.4.9'}), true);
  for (const version of ['1.4.8', '1.3.0', '1.5.0', '']) assert.equal(supports({version}), false);
});

test('position allowance keeps 56 hours intact and deducts all hours above the boundary', () => {
  for (const [absence, expected] of [[0,800],[56,800],[56.5,574],[81.5,474],[248,0]]) {
    assert.equal(amount('gangwei_butie',0,{absence}), expected);
  }
  assert.equal(amount('gangwei_butie',0,{scheduled:20,absence:56.5}),517.5);
  assert.equal(amount('gangwei_butie',2,{absence:56,standard:'800'}),600);
  assert.equal(amount('gangwei_butie',2,{absence:56.5}),430.5);
  assert.equal(amount('gangwei_butie',1,{standard:'1300',absence:0}),1300);
});

test('Dongguan meal allowance caps daily hours and rounds only after monthly accumulation', () => {
  assert.equal(amount('canbu',0,{hours:4,days:25}),237.5);
  assert.equal(amount('canbu',0,{hours:16,days:25}),475);
  assert.equal(amount('canbu',0,{hours:8,days:31}),500);
  assert.equal(amount('canbu',0,{hours:.5,days:31}),36.81);
  assert.equal(amount('canbu',0,{days:0}),0);
});

test('Jiashan meal example distinguishes sick leave from personal leave; Jinjiang stays zero', () => {
  assert.equal(amount('canbu',1,{personal:8}),288);
  assert.equal(amount('canbu',1,{sick:8}),295.2);
  assert.equal(amount('canbu',1,{personal:8,sick:8,absentDays:1}),271.2);
  assert.equal(amount('canbu',1,{employed:0}),0);
  assert.equal(amount('canbu',2,{hours:8,days:31}),0);
});

test('housing example includes checkout day and updates month-length bounds', () => {
  assert.equal(amount('waisu_butie',0,{checkout:1}),150);
  assert.equal(amount('waisu_butie',0,{checkout:10}),106.45);
  assert.equal(amount('waisu_butie',0,{checkout:31}),4.84);
  assert.equal(amount('waisu_butie',0,{housing:'staying'}),0);
  assert.equal(amount('waisu_butie',1,{monthDays:'30',checkout:10}),105);
  assert.equal(calculate('waisu_butie',0,{monthDays:'28',checkout:32}).values.checkout,28);
});

test('housing absence starts at 56 hours, while Jinjiang leave starts above seven days', () => {
  assert.equal(amount('waisu_butie',0,{scenario:'absence',absence:55.5}),150);
  assert.equal(amount('waisu_butie',0,{scenario:'absence',absence:56}),116.13);
  assert.equal(amount('waisu_butie',1,{scenario:'absence',monthDays:'30',absence:56}),115);
  assert.equal(amount('waisu_butie',2,{leaveDays:7}),150);
  assert.equal(amount('waisu_butie',2,{leaveDays:7.5}),113.71);
  assert.equal(amount('waisu_butie',2,{monthDays:'30',entryDays:5,leaveDays:8}),85);
});

test('night windows independently apply minimum duration and half-hour truncation', () => {
  assert.equal(amount('yeban_butie',0,{evening:.75,morning:.75}),0);
  assert.equal(amount('yeban_butie',0,{evening:1,morning:0}),3);
  assert.equal(amount('yeban_butie',1,{evening:1.25,morning:0}),3);
  assert.equal(amount('yeban_butie',2,{evening:1.5,morning:2.25}),10.5);
  assert.equal(amount('yeban_butie',0,{evening:8.5,morning:0}),25);
  assert.equal(amount('yeban_butie',4,{evening:8,morning:8}),25);
});

test('LB15 uses regular hours rather than the ordinary three-yuan hourly rate', () => {
  assert.equal(amount('yeban_butie',3,{}),25);
  assert.equal(amount('yeban_butie',3,{late:.5}),23.44);
  assert.equal(amount('yeban_butie',3,{late:1,early:1}),18.75);
  assert.equal(amount('yeban_butie',3,{late:8,early:8}),0);
});

test('attendance award requires mutually exclusive lateness tiers and all other conditions', () => {
  assert.equal(amount('quanqinjiang',0,{minor:3,signs:3}),100);
  assert.equal(amount('quanqinjiang',0,{middle:1}),100);
  for (const input of [{minor:4},{middle:2},{minor:1,middle:1},{major:1},{signs:4},{eligible:'no'}]) {
    assert.equal(amount('quanqinjiang',0,input),0);
  }
});

test('seniority has its own inclusive threshold, caps, and independent FBU proration', () => {
  assert.equal(amount('gonglingjiang',0,{years:0}),0);
  assert.equal(amount('gonglingjiang',0,{years:8}),600);
  assert.equal(amount('gonglingjiang',0,{absence:55.5}),300);
  assert.equal(amount('gonglingjiang',0,{absence:56}),216);
  assert.equal(amount('gonglingjiang',0,{absence:56,entryHours:16}),192);
  assert.equal(amount('gonglingjiang',2,{years:2,absence:8,entryHours:16}),176);
  assert.equal(amount('gonglingjiang',2,{years:8}),500);
  assert.equal(amount('gonglingjiang',4,{years:4}),150);
  assert.equal(amount('gonglingjiang',3,{years:8}),0);
  assert.equal(amount('gonglingjiang',6,{years:8}),0);
  assert.equal(calculate('gonglingjiang',0,{absence:200,entryHours:16}).invalid,true);
});

test('temperature examples match season, shift temperature, local caps and monthly rounding', () => {
  assert.equal(amount('gaowen_butie',0,{temperature:32.9}),0);
  assert.equal(amount('gaowen_butie',0,{temperature:33,days:10}),138);
  assert.equal(amount('gaowen_butie',0,{month:'5',temperature:40}),0);
  assert.equal(amount('gaowen_butie',0,{month:'11',temperature:40}),0);
  assert.equal(amount('gaowen_butie',1,{temperature:33}),200);
  assert.equal(amount('gaowen_butie',2,{temperature:33,days:10}),120);
  assert.equal(amount('gaowen_butie',0,{month:'7',hours:.5,days:31}),26.74);
  assert.equal(amount('gaowen_butie',0,{shift:'night',temperature:32.9}),0);
  assert.equal(calculate('gaowen_butie',0,{month:'9',days:31}).values.days,30);
});

test('invalid numeric entries and incompatible standards stay within the configured model', () => {
  const r=calculate('gangwei_butie',2,{standard:'-1',scheduled:0,absence:NaN});
  assert.equal(r.values.standard,'600');
  assert.equal(r.values.scheduled,1);
  assert.ok(Number.isFinite(r.amount));
  assert.equal(calculate('canbu',0,{hours:-2,days:99}).amount,0);
});
