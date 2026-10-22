const test=require('node:test');
const assert=require('node:assert/strict');
const {choice}=require('../bonus_platform/static/recruitment-fact-controls.js');

test('business decisions show explicit choices without a free text box',()=>{
  const html=choice({choices:[{value:'不发招聘奖金',label:'不发招聘奖金'},{value:'按40%核算',label:'按40%核算'}]},'', 'id="decision"');
  assert.match(html,/<select id="decision">/);assert.match(html,/按40%核算/);assert.match(html,/不发招聘奖金/);
  assert.doesNotMatch(html,/<input|<textarea|selected/);
});
test('missing evidence offers a material entry instead of an explanation blank',()=>{
  const html=choice({choices:[],missingMessage:'缺少剔除天数的原始记录或审批'},'');
  assert.match(html,/缺少剔除天数/);assert.match(html,/上传对应资料/);
  assert.doesNotMatch(html,/<input|<textarea/);
});
test('existing source names and values are escaped and ordinary facts keep their own editor',()=>{
  const html=choice({choices:[{value:'source:"1',label:'<原始资料>'}]},'source:"1');
  assert.match(html,/&lt;原始资料>/);assert.match(html,/source:&quot;1/);assert.match(html,/selected/);
  assert.equal(choice(undefined,'2026-07-01'),null);
});

test('a batch without shared evidence links to each person instead of requesting another upload',()=>{
  const html=choice({field:'周期剔除依据',choices:[],missingMessage:'按人员关联已有资料',people:[{id:'one',name:'甲'}]},'');
  assert.match(html,/data-fact-person="one"/);assert.match(html,/甲/);assert.doesNotMatch(html,/上传对应资料|<input/);
});

test('a case with no evidence requirement does not prompt another upload',()=>{
  const html=choice({choices:[],missingMessage:'当前没有需要关联的剔除资料',upload:false},'');
  assert.doesNotMatch(html,/上传|<input/);
});
