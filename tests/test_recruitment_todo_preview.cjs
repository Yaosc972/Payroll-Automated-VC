const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../bonus_platform/static/recruitment-flow.js'),'utf8');
const context={e:value=>String(value).replaceAll('<','&lt;'),label:String,fieldName:String,text:String,amount:v=>String(v),month:String,nodeMonth:n=>n.scheduledMonth};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('  function impactMarkup('),source.indexOf('  function editForm(')),context);
const preview=patch=>({people:1,changes:[],currentImpact:[],nodeImpact:[],...patch});
test('unknown amounts remain visible even when monthly values have not changed',()=>{
 const html=context.impactMarkup(preview({unresolvedAmounts:[{rowId:'one',name:'甲',kind:'招聘奖金',reasons:['渠道待核']}],remainingIssues:[{rowId:'one',name:'甲',kind:'招聘奖金',reasons:['资格待核']}]}));
 assert.match(html,/金额待确定/);assert.doesNotMatch(html,/本月金额不变/);
 assert.match(html,/仍待处理 · 1 项/);assert.match(html,/渠道待核；资格待核/);
});
test('a wholly unknown monthly amount is not presented as a zero subtotal',()=>{
 const html=context.impactMarkup(preview({currentImpact:[{name:'甲',kind:'招聘奖金',before:null,after:null,beforeCurrency:'美元',currency:'美元'}]}));
 assert.match(html,/美元：1 笔金额待确定 → <strong>1 笔金额待确定/);assert.doesNotMatch(html,/0 ＋/);
});
test('unchanged known amounts and remaining issues keep their separate meanings',()=>{
 const html=context.impactMarkup(preview({remainingIssues:[{name:'<甲>',kind:'招聘奖金',reasons:['领取人待核']}]}));
 assert.match(html,/本月金额不变/);assert.match(html,/领取人待核/);assert.match(html,/&lt;甲>/);
});
