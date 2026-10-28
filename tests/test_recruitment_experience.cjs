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
  assert.equal(progress.title, '正在同步接口资料');
  assert.equal(progress.detail, '正在补查资料');
  assert.equal('percent' in progress, false);
});
test('measured progress describes only the current sync operation', () => {
  const job={status:'running',stage:'sync',revision:6};
  for(const [message,completed,total,unit,percent] of [
    ['正在补查 1 份海外录用资料中的核算缺项',0,1,'份',0],
    ['海外 Offer 已核对 20 / 50 份',20,50,'份',40],
    ['海外任职记录已核对 12 / 24 人',12,24,'人',50],
    ['正在读取国内花名册：300/400 人',300,400,'人',75],
  ]){
    const measurement=model(draft(),{...job,message}).progress.measurement;
    assert.deepEqual(JSON.parse(JSON.stringify(measurement)),{completed,total,unit,percent});
  }
  for(const message of ['正在连接接口','海外 Offer 已核对 5 / 4 份','海外任职记录已核对 0 / 0 人'])
    assert.equal(model(draft(),{...job,message}).progress.measurement,null);
  assert.equal(model(draft(),{...job,status:'cancelling',message:'海外 Offer 已核对 1 / 2 份'}).progress.measurement,undefined);
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
test('upload feedback stays an import while intermediate draft reads change the message',()=>{
  for(const message of ['正在导入 2 份资料','已保存','正在读取']){
    const progress=model(draft(),null,{busy:true,uploadCount:2,message}).progress;
    assert.equal(progress.title,'正在导入资料');
    assert.equal(progress.detail,'正在读取、识别并保存 2 份资料');
  }
  const finished=model(draft(),null,{busy:false,uploadCount:0,message:'资料已导入'});
  assert.equal(finished.progress,null);
});
test('overseas gaps remain visible in every successful sync mode', () => {
  for(const flags of [{},{overseasOnly:true},{domesticOnly:true},{monthlyAll:true}]){
    const data=draft();data.monthly.coverage.syncRequired=true;
    const state=model(data,{status:'complete',revision:6,...flags,
      coverageGaps:[{role:'海外候选人',reason:'未取得有效录用资料'}],message:'1 名海外候选人未取得有效录用资料'});
    assert.equal(state.progress.title,'资料尚未齐全');
    assert.equal(state.progress.tone,'attention');
    assert.equal(state.progress.retry,true);
    assert.equal(state.steps[0].note,'资料待补齐');
  }
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
