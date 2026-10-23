const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const window = {};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../bonus_platform/static/recruitment-materials.js'), 'utf8'), {window});
const materials = window.RecruitmentMaterials;
const plain = value => JSON.parse(JSON.stringify(value));
const source = (id, roles, extra = {}) => ({id, name: id + '.xlsx', roles, active: true, forMonth: 202607, ...extra});
const draft = sources => ({month: 202607, sources, rows: [], baseline: '', monthly: {coverage: {}}});

test('historical month and current observation time are explicitly distinguished',()=>{
  const note=materials.snapshotNote({kind:'overseas_api',forMonth:202608,addedAt:'2026-10-22T19:00:00+08:00',snapshotVersion:2});
  assert.match(note,/2026年8月/);assert.match(note,/2026-10-22 19:00/);
  assert.match(note,/第 2 版/);assert.match(note,/不能单独证明/);
  assert.equal(materials.snapshotNote({name:'历史原件.xlsx'}),'');
});

test('domestic monthly sync is available without a roster and preserves comparison snapshots',()=>{
  assert.equal(materials.build(draft([])).find(g=>g.id==='domestic').status,'待同步');
  const file=source('国内快照',['roster','domestic_offer'],{kind:'beisen',monthlyRoster:true,snapshotOnly:true,comparisonOnly:true});
  assert.deepEqual(plain(materials.categories(file)),['roster','domestic']);
  assert.equal(materials.syncStatus(file),'已保存 · 待核对');
  assert.equal(materials.build(draft([file])).find(g=>g.id==='domestic').status,'已保存快照');
});

test('overseas snapshots stay in Offer and roster categories while awaiting review',()=>{
  const file=source('海外资料',['roster','overseas_offer'],{kind:'overseas_api',comparisonOnly:true,snapshotOnly:true});
  assert.deepEqual(plain(materials.categories(file)),['roster','overseas']);
  assert.equal(materials.format(file).badge,'API');
  assert.equal(materials.syncStatus(file),'已保存 · 待核对');
  const groups=materials.build(draft([file]));
  assert.equal(groups.find(g=>g.id==='overseas').status,'已保存快照');
  assert.equal(groups.find(g=>g.id==='extra').status,'按需提供');
  assert.equal(materials.build(draft([source('原花名册',['roster']),file])).find(g=>g.id==='roster').status,'已导入 1 份 · 快照 1');
});

test('a missing approval attachment remains visible until an active original is provided', () => {
  const file=source('审批',[],{attachment:true,mentionedAttachments:['分工.xlsx']});
  const attachment=source('分工', ['supplement'], {comparisonOnly:true});
  const data=draft([file,attachment]);
  assert.equal(materials.approvalStatus(data,file),'缺少引用附件');
  attachment.comparisonOnly=false;
  assert.equal(materials.approvalStatus(data,file),'待审阅');
  attachment.active=false;
  assert.equal(materials.approvalStatus(data,file),'缺少引用附件');
});

test('approval status reflects applied scope and undo instead of always awaiting review', () => {
  const file=source('approval',[],{attachment:true}), data=draft([file]);
  assert.equal(materials.approvalStatus(data,file),'待审阅');
  data.reviewEntries=[{sourceId:file.id,status:'已认可',applied:true,scopeComplete:false,operationId:'op'}];
  data.activeOperations=['op'];
  assert.equal(materials.approvalStatus(data,file),'已部分应用');
  data.reviewEntries[0].scopeComplete=true;
  assert.equal(materials.approvalStatus(data,file),'已应用更正');
  data.activeOperations=[];
  assert.equal(materials.approvalStatus(data,file),'待审阅');
});

test('file contents, not filenames, determine material categories', () => {
  assert.deepEqual(plain(materials.categories(source('任意文件名', ['overseas_offer']))), ['overseas']);
  assert.deepEqual(plain(materials.categories(source('Offer', ['roster']))), ['roster']);
});

test('a workbook with multiple recognised sheets is available in each relevant category', () => {
  const data = draft([source('混合表', ['roster', 'overseas_offer'])]);
  const groups = materials.build(data);
  assert.equal(groups.find(group => group.id === 'roster').files.length, 1);
  assert.equal(groups.find(group => group.id === 'overseas').files.length, 1);
  assert.equal(data.sources.length, 1);
});

test('a comparison workbook never fulfils the previous-month input requirement', () => {
  const groups = materials.build(draft([source('七月核对表', ['ledger'], {comparisonOnly: true})]));
  assert.equal(groups.find(group => group.id === 'opening').files.length, 0);
  assert.equal(groups.find(group => group.id === 'opening').status, '待导入');
  assert.equal(groups.find(group => group.id === 'comparison').files.length, 1);
});

test('imported history remains awaiting adoption until actually adopted', () => {
  const data = draft([source('上月表', ['ledger'])]);
  assert.equal(materials.build(data).find(group => group.id === 'opening').status, '待采用');
  data.baseline = '上月表'; data.monthly.coverage.hasOpening = true;
  assert.equal(materials.build(data).find(group => group.id === 'opening').status, '已采用');
});

test('inactive, failed and older-month rosters are not presented as current-month imports', () => {
  const data = draft([source('停用', ['roster'], {active: false}), source('上月', ['roster'], {forMonth: 202606})]);
  const group = materials.build(data).find(group => group.id === 'roster');
  assert.equal(group.status, '待导入本月资料');
  assert.equal(group.files.length, 2);
  data.sources.push(source('读取失败', ['roster'], {error: '表头无法识别'}));
  assert.equal(materials.build(data).find(group => group.id === 'roster').tone, 'error');
});

test('domestic sync reports actual coverage and missing sync is not marked complete', () => {
  const data = draft([source('同步', ['domestic_offer', 'employment_history'], {kind: 'beisen', name: 'snapshot.json'})]);
  data.monthly.coverage = {domesticPeople: 20, queriedPeople: 20, syncedAt: '2026-09-30', syncRequired: false};
  assert.equal(materials.build(data).find(group => group.id === 'domestic').status, '已同步 · 20 人');
  data.monthly.coverage.syncRequired = true;
  assert.equal(materials.build(data).find(group => group.id === 'domestic').status, '待同步');
});

test('supplemental and unrecognised files remain accessible without adding required materials', () => {
  const groups = materials.build(draft([source('补充', ['supplement']), source('无法识别', ['unknown'])]));
  assert.equal(groups.find(group => group.id === 'other').files.length, 2);
  assert.equal(groups.find(group => group.id === 'extra').status, '按需提供');
  assert.deepEqual(plain(materials.categories(source('审批', [], {attachment: true}))), ['extra']);
  assert.deepEqual(plain(materials.categories(source('审批明细', ['approval']))), ['extra']);
});

test('file format and worksheet count come from imported file metadata', () => {
  assert.deepEqual(plain(materials.format(source('表', ['roster'], {sheets: [{name: '国内'}, {name: '海外'}]}))),
    {badge: 'XLSX', description: 'Excel · 2 个工作表'});
  assert.equal(materials.format(source('审批', [], {name: '审批.PDF', attachment: true})).description, 'PDF 文件');
  assert.equal(materials.format(source('同步', [], {kind: 'beisen', name: 'snapshot.json'})).description, '国内接口快照');
});


test('external result imports have their own purpose and never become opening or personnel facts',()=>{
  const file=source('本月核定结果',['ledger','supplement'],{purpose:'external-results'});
  assert.deepEqual(plain(materials.categories(file)),['external']);
  const groups=materials.build(draft([file]));
  assert.equal(groups.find(group=>group.id==='external').files.length,1);
  assert.equal(groups.find(group=>group.id==='opening').files.length,0);
  assert.equal(groups.find(group=>group.id==='external').status,'按需导入');
});

test('cumulative personnel imports use their own material card and expose skipped rows',()=>{
  const file=source('BP累计',['cumulative'],{purpose:'external-personnel',cumulativeSummary:{newHires:2,updatedPeople:1,notApplied:[{code:'future_hire'}]}});
  assert.deepEqual(plain(materials.categories(file)),['external-personnel']);
  const groups=materials.build(draft([file]));
  assert.equal(groups.find(group=>group.id==='external-personnel').status,'1 条未采用');
  assert.equal(groups.find(group=>group.id==='external-personnel').tone,'missing');
  assert.equal(groups.find(group=>group.id==='opening').files.length,0);
  assert.equal(groups.find(group=>group.id==='external').files.length,0);
});

test('previous month cumulative evidence does not claim a current-month import',()=>{
  const file=source('上月累计',['cumulative'],{purpose:'external-personnel',forMonth:202606});
  const group=materials.build(draft([file])).find(item=>item.id==='external-personnel');
  assert.equal(group.status,'待导入本月资料');
  assert.equal(group.files.length,1);
  assert.equal(materials.build(draft([])).find(item=>item.id==='external-personnel').status,'按需提供');
});
