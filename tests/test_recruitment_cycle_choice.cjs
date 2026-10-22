const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../bonus_platform/static/recruitment-flow.js'),'utf8');
const context={e:v=>String(v).replaceAll('<','&lt;').replaceAll('"','&quot;'),flowIcon:()=>'<svg></svg>'};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('  function originalCycleMarkup('),source.indexOf('  function reviewDialog(')),context);

test('an inverted date card offers two actions and no extra inputs or explanatory text',()=>{
 const html=context.originalCycleMarkup({id:'feng',originalCycle:{startDate:'2026-07-15',hireDate:'2026-07-13',exclusionDays:0,actualDays:-2}});
 assert.match(html,/2026-07-15/);assert.match(html,/2026-07-13/);assert.match(html,/-2 天/);
 assert.match(html,/按原日期核算/);assert.match(html,/修改日期/);
 assert.equal((html.match(/<button /g)||[]).length,2);
 assert.doesNotMatch(html,/<input|<p|确认采用|填写原因/);
});

test('ordinary or confirmed dates do not get another confirmation action',()=>{
 assert.equal(context.originalCycleMarkup({id:'one'}),'');
 assert.equal(context.originalCycleMarkup({id:'one',originalCycle:{confirmed:true}}),'');
});
