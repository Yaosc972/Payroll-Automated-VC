const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const window = {};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../bonus_platform/static/recruitment-experience.js'), 'utf8'), {window});
const model = window.RecruitmentExperience.model;
const draft = () => ({revision:6, rows:[{id:'a'}], sources:[{id:'s',active:true}], monthly:{coverage:{hasOpening:true}, actionCount:0, worksheet:{rows:[{current:true},{current:false}]}}});

test('combined sync reports both sources without marking a failed phase complete',()=>{
  const running=model(draft(),{status:'running',stage:'sync',monthlyAll:true,syncSource:'overseas',
    syncResults:{domestic:{status:'failed'},overseas:{status:'running'}},revision:6}).progress;
  assert.equal(running.title,'正在同步国内及海外资料');
  assert.deepEqual(Array.from(running.phases),['同步国内资料','同步海外资料']);
  assert.deepEqual(Array.from(running.phaseStates),['error','active']);
  const failed=model(draft(),{status:'failed',monthlyAll:true,revision:6,message:'海外未完成，国内资料已保留'}).progress;
  assert.equal(failed.tone,'error');assert.equal(failed.retry,true);
  assert.equal(failed.title,'资料同步未完成');
  const done=model(draft(),{status:'complete',monthlyAll:true,revision:6,message:'国内及海外快照已保存'}).progress;
  assert.equal(done.title,'国内及海外资料快照已保存');
  assert.equal(done.tone,'complete');
});

test('domestic monthly snapshots report their own progress and completion',()=>{
  const running=model(draft(),{status:'running',stage:'sync',revision:6,domesticOnly:true}).progress;
  assert.equal(running.title,'正在同步国内资料');
  const done=model(draft(),{status:'complete',revision:6,domesticOnly:true,message:'已有核算与待办保留'}).progress;
  assert.equal(done.title,'国内资料快照已保存');
  assert.equal(done.detail,'已有核算与待办保留');
});

test('overseas snapshot progress and completion do not claim to change existing calculation',()=>{
  const running=model(draft(),{status:'running',stage:'sync',revision:6,overseasOnly:true}).progress;
  assert.equal(running.title,'正在同步海外资料');
  assert.ok(running.phases.includes('保存月度快照'));
  const done=model(draft(),{status:'complete',revision:6,overseasOnly:true,message:'已有核算与待办保留'}).progress;
  assert.equal(done.title,'海外资料快照已保存');
  assert.equal(done.detail,'已有核算与待办保留');
});

test('empty data does not claim calculated or exported results', () => {
  const state = model({revision:0,rows:[],sources:[],monthly:{coverage:{}}});
  assert.equal(state.steps[1].state, 'waiting');
  assert.equal(state.steps[2].note, '招聘与内推奖金');
  assert.equal(state.progress, null);
});
test('real server stage drives progress without inventing a percentage', () => {
  const progress = model(draft(), {status:'running',stage:'sync',message:'正在补查资料',revision:5}).progress;
  assert.equal(progress.phase, 1);
  assert.equal(progress.title, '正在同步国内资料');
  assert.equal(progress.detail, '正在补查资料');
  assert.equal('percent' in progress, false);
});
test('an older completed or failed job is not shown as this revision', () => {
  for (const status of ['complete','failed']) assert.equal(model(draft(), {status,revision:5}).progress, null);
});
test('a current failure retains a retry action, never a completion state', () => {
  const state = model(draft(), {status:'interrupted',revision:6,message:'已有资料保留'});
  assert.equal(state.progress.tone, 'error');
  assert.equal(state.progress.retry, true);
});
test('a completed preparation with issues is not described as a confirmed result', () => {
  const data = draft(); data.monthly.actionCount = 3;
  const state = model(data, {status:'complete',revision:6});
  assert.equal(state.progress.tone, 'attention');
  assert.equal(state.steps[1].note, '3 项需核对');
  assert.equal(state.steps[2].note, '可导出供核对');
  assert.match(state.progress.detail, /1 人.*3 项/);
});
test('missing coverage and an out-of-date parent do not imply final export readiness', () => {
  for (const field of ['syncRequired','recipientSyncRequired','sourceErrors']) {
    const data = draft(); data.monthly.coverage[field] = true;
    assert.equal(model(data).steps[2].note, '可导出供核对');
  }
  const data = draft(); data.parentOutdated = true;
  assert.equal(model(data).steps[2].note, '可导出供核对');
});
test('an empty sync response retains its missing-data message and an explicit retry', () => {
  const data = draft(); data.monthly.coverage.recipientSyncRequired = true;
  const state = model(data, {status:'complete',revision:6,coverageGaps:[{role:'领取人',employee:'zt100',reason:'未取得任职资料'}],message:'仍有 1 项任职资料未取得'});
  assert.equal(state.progress.tone, 'attention');
  assert.equal(state.progress.detail, '仍有 1 项任职资料未取得');
  assert.equal(state.progress.retry, true);
  assert.equal(state.steps[2].note, '可导出供核对');
});
test('ordinary imports, exports and errors have their own prominent feedback', () => {
  assert.equal(model(draft(), null, {busy:true,message:'正在整理 2 份资料并核算'}).progress.title, '正在导入资料');
  assert.equal(model(draft(), null, {busy:true,message:'正在生成导出表格'}).progress.title, '正在生成导出表格');
  assert.equal(model(draft(), null, {message:'文件读取失败',error:true}).progress.tone, 'error');
});
test('exported state applies only to the downloaded revision', () => {
  assert.equal(model(draft(), null, {exportedRevision:6}).steps[2].state, 'complete');
  assert.notEqual(model(draft(), null, {exportedRevision:5}).steps[2].state, 'complete');
});
test('archived activities stay read-only, even with an earlier running status', () => {
  const data = draft(); data.activity = {archived:true};
  assert.equal(model(data, {status:'running'}).progress.tone, 'neutral');
  assert.equal(model(data, {status:'running'}).progress.retry, false);
});
test('rule maintenance is distinguished from operator input and remains pending', () => {
  const data = draft();
  data.monthly.actionCount = 3;
  data.monthly.operatorActionCount = 1;
  data.monthly.ruleActionCount = 2;
  const state = model(data);
  assert.equal(state.steps[1].note, '1 项待办 · 2 项制度');
  assert.equal(state.steps[1].state, 'attention');
  assert.equal(state.steps[2].note, '可导出供核对');
});
