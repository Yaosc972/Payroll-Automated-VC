const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const window={};vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname,'../bonus_platform/static/recruitment-detail-table.js'),'utf8'),{window});
const detail=window.RecruitmentDetailTable;
test('zero, unknown, unused and percent retain their meaning',()=>{
  assert.equal(detail.format(0,'money'),'0.00');
  assert.equal(detail.format(null,'money'),'待核对');
  assert.equal(detail.format('','money'),'—');
  assert.equal(detail.format(.4,'percent'),'40%');
  assert.equal(detail.format(202607,'text'),'202607');
});
test('two header tiers preserve groups and fixed identity fields',()=>{
  const columns=[{key:'name',label:'姓名',group:'人员资料',width:160},{key:'employeeId',label:'工号',group:'人员资料',width:128},{key:'amount',label:'入职1个月发放奖金',group:'招聘负责人入职奖金明细',width:148,type:'money'},{key:'period',label:'入职1个月发放周期',group:'招聘负责人入职奖金明细',width:148}];
  const html=detail.table(columns,[{id:'test',cells:{name:'<人>',employeeId:'zt1',amount:0,period:'暂缓安排'},cellNotes:{amount:'<script>'}}]);
  assert.match(html,/colspan="2"/);assert.match(html,/rowspan="2"/);
  assert.match(html,/flow-fixed-id/);assert.match(html,/0\.00/);
  assert.match(html,/暂缓安排/);assert.match(html,/&lt;script&gt;/);
  assert.doesNotMatch(html,/<人>|<script>/);
});
test('identity masking handles full, short and missing values without affecting employee numbers',()=>{
  assert.equal(detail.maskIdentity('110101199001011234'),'110********1234');
  assert.equal(detail.maskIdentity('110101900101234'),'110********1234');
  assert.equal(detail.maskIdentity('123456'),'******');
  assert.equal(detail.maskIdentity(null),null);
  assert.equal(detail.maskIdentity(''),'');
  assert.equal(detail.display(null,{key:'证件号',type:'text'}),'待核对');
  assert.equal(detail.display('zt12345',{key:'employeeId',type:'text'}),'zt12345');
});
test('identity rows and hover titles never contain the unmasked identifier or its raw note',()=>{
  const value='110101199001011234';
  const columns=[{key:'name',label:'姓名',group:'人员资料',width:160},{key:'employeeId',label:'工号',group:'人员资料',width:128},{key:'证件号',label:'身份证',group:'人员资料',width:180,type:'text'}];
  const row={id:'mask-test',cells:{name:'甲',employeeId:'zt1',证件号:value},cellNotes:{证件号:'原值：'+value}};
  const before=JSON.stringify(row),html=detail.table(columns,[row]);
  assert.equal(JSON.stringify(row),before);
  assert.ok(html.includes('110********1234'));
  assert.ok(!html.includes(value));
  assert.ok(!html.includes('原值：'));
});
