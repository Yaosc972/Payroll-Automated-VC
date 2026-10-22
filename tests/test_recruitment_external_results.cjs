const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const script=fs.readFileSync(path.join(__dirname,'../bonus_platform/static/recruitment-external-results.js'),'utf8');
const clean=value=>JSON.parse(JSON.stringify(value));
function harness(handler=async()=>({revision:1,month:202608,records:[],pendingImports:[],summary:{}}),exposePreview=false){
  const elements={},requests=[],events={},markup=[];
  const element=()=>({innerHTML:'',textContent:'',disabled:false,hidden:false,isConnected:true,attributes:{},dataset:{},classList:{add(){},remove(){},contains(){return true;}},setAttribute(key,value){this.attributes[key]=value;},addEventListener(type,listener){this['on'+type]=listener;},querySelectorAll(){return [];},click(){this.onclick?.();}});
  const $=id=>elements[id]||(elements[id]=element());
  $('draftInspector').open=true;
  const ui={data:{revision:1,month:202608,rows:[],sources:[]},busy:false};
  let currentBase='/activity/api/recruitment/drafts/202608';
  const escape=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const workbench={$,ui,e:escape,base:()=>currentBase,status(){},setView(view){ui.view=view;},request:async(url,options)=>{requests.push({url,options});return handler(url,options);},adopt(data){ui.data=data;},busy(value){ui.busy=value;for(const listener of events['recruitment:busy']||[])listener();},openDialog(title,html){markup.push(html);for(const match of html.matchAll(/id="([^"]+)"/g))elements[match[1]]=element();$('draftInspector').open=true;}};
  const window={RecruitmentWorkbench:workbench};
  vm.runInNewContext(exposePreview?script.replace("={open,", "={loadPreview,open,"):script,{window,FormData:class{constructor(){this.fields=[];}append(key,value){this.fields.push([key,value]);}},document:{querySelectorAll:()=>[],addEventListener(type,listener){(events[type]||=[]).push(listener);}}});
  return {api:window.RecruitmentExternalResults,$,ui,requests,markup,changeBase(value){currentBase=value;}};
}
const api=harness().api;

test('normal and issue records are paginated without creating a row control per normal person',()=>{
  const rows=Array.from({length:103},(_,i)=>({id:String(i),candidateName:`员工${i}`,status:i===48?'blocked':'ready',issues:i===48?['金额未提供']:[]}));
  assert.equal(api.tableModel({rows}).rows.length,40);
  assert.equal(api.tableModel({rows},{page:3}).rows.length,23);
  assert.equal(api.tableModel({rows},{page:9}).page,3);
  assert.equal(api.tableModel({rows},{filter:'blocked'}).total,1);
  assert.equal(api.tableModel({rows},{query:'金额未提供'}).rows[0].id,'48');
});

test('blank money stays missing while zero and signed corrections remain explicit',()=>{
  assert.equal(api.money(null,'CNY'),'未提供');
  assert.equal(api.money('','CNY'),'未提供');
  assert.equal(api.money(0,'CNY'),'0.00 CNY');
  assert.equal(api.money(-20.15,'EUR'),'-20.15 EUR');
});

test('material state distinguishes upload, adoption, replacement, invalidation and monthly carry',()=>{
  assert.equal(api.fileState({records:[]},'source'),'待采用');
  assert.equal(api.fileState({records:[{sourceId:'source',status:'adopted'}]},'source'),'已采用');
  assert.equal(api.fileState({records:[{sourceId:'source',status:'superseded'}]},'source'),'已替换');
  assert.equal(api.fileState({records:[{sourceId:'source',status:'invalid'}]},'source'),'资料已失效');
  assert.deepEqual(clean(api.cardState({records:[],expected:[{}]})),{label:'待导入本月结果',tone:'missing'});
  assert.equal(api.cardState({records:[],pendingImports:[{readyCount:2,blockedCount:1}]}).label,'3 项待处理');
});

test('normal rows use one adopt action and issue rows show exact workbook locations',async()=>{
  const context={revision:1,month:202608,records:[],pendingImports:[{token:'saved',name:'结果.xlsx',readyCount:1,blockedCount:1}],summary:{}};
  const preview={token:'saved',revision:1,peopleCount:2,readyCount:1,blockedCount:1,canApply:true,files:[{id:'source',name:'结果.xlsx'}],totalsByCurrency:{CNY:1000},rows:[{id:'ok',sourceId:'source',candidateName:'甲',recipientName:'乙',project:'招聘负责人奖金',amount:1000,currency:'CNY',status:'ready',issues:[]},{id:'missing',sourceId:'source',candidateName:'<script>',project:'内推奖金',amount:null,status:'blocked',issues:['体系外核算结果 第 3 行 本月核定金额未提供'],sheet:'体系外核算结果',sourceRows:[3]}]};
  const env=harness(async(url)=>url.endsWith('/previews/saved')?preview:context,true);
  await env.api.open();
  assert.match(env.markup.at(-1),/继续处理 结果.xlsx/);
  assert.doesNotMatch(env.markup.at(-1),/依据位置|修改原因|type="checkbox"/);
  await env.api.loadPreview('saved');
  const $=env.$;
  assert.match($('externalRows').innerHTML,/第 3 行 本月核定金额未提供/);
  assert.match($('externalRows').innerHTML,/&lt;script&gt;/);
  assert.match($('externalApply').innerHTML,/采用 1 项/);
  assert.doesNotMatch($('externalRows').innerHTML,/type="checkbox"/);
});

test('an old activity response cannot render into the newly selected activity',async()=>{
  let finish;
  const env=harness(()=>new Promise(resolve=>{finish=resolve;}));
  const opening=env.api.open();
  env.changeBase('/other/api/recruitment/drafts/202609');
  finish({revision:1,records:[{candidateName:'旧活动'}],summary:{}});
  await opening;
  assert.equal(env.markup.length,1);
  assert.doesNotMatch(env.markup[0],/旧活动/);
});


test('adoption stays locked through recalculation and a second click cannot submit twice',async()=>{
  let complete;
  const context={revision:1,records:[],pendingImports:[],summary:{}};
  const preview={token:'one',revision:1,rows:[{id:'a',status:'ready',candidateName:'甲',amount:100,currency:'CNY'}],readyCount:1,canApply:true};
  const env=harness(async(url)=>url.endsWith('/apply')?new Promise(resolve=>{complete=resolve;}):url.endsWith('/previews/one')?preview:context,true);
  await env.api.open();await env.api.loadPreview('one');
  const adopting=env.$('externalApply').onclick();
  assert.equal(env.$('externalApply').disabled,true);
  assert.equal(env.$('draftCloseInspector').disabled,true);
  assert.equal(env.$('externalDetail').disabled,true);
  assert.match(env.$('externalApply').innerHTML,/正在采用并更新核算/);
  await env.$('externalApply').onclick();
  assert.equal(env.requests.filter(call=>call.url.endsWith('/apply')).length,1);
  complete({state:{revision:2,month:202608,rows:[],sources:[]},externalResults:{revision:2,records:[],summary:{}},appliedCount:1,message:'已采用 1 项，核算已更新。'});
  await adopting;
  assert.equal(env.ui.data.revision,2);
  assert.equal(env.$('draftCloseInspector').disabled,false);
  assert.match(env.$('externalFeedback').textContent,/已采用 1 项/);
  assert.match(env.$('externalRows').innerHTML,/已采用/);
});

test('an external-results todo opens its usable result screen without a facts request',async()=>{
  const source=fs.readFileSync(path.join(__dirname,'../bonus_platform/static/recruitment-flow.js'),'utf8');
  const section=source.slice(source.indexOf('  async function openWork(item){'),source.indexOf('  function openingDialog(data){'));
  let opened=0;
  const context={window:{RecruitmentExternalResults:{open(){opened++;}}}};
  vm.createContext(context);vm.runInContext(section,context);
  await context.openWork({mode:'externalResults',key:'external_results'});
  assert.equal(opened,1);
});

test('reopening after a revision change refreshes the shared draft before editing results',async()=>{
  const env=harness(async(url)=>url.endsWith('/external-results')?{revision:2,records:[],pendingImports:[],summary:{}}:{revision:2,month:202608,rows:[],sources:[]});
  await env.api.open();
  assert.equal(env.ui.data.revision,2);
  assert.equal(env.requests.length,3);
  assert.equal(env.$('externalReload').hidden,true);
});

test('missing monthly results name the people and projects in the existing result table',async()=>{
  const expected=[{id:'scope-one',candidateName:'待核人员',recipientName:'体系外负责人',recipientId:'zt-outside',project:'招聘负责人奖金',status:'missing',outcome:'pending',amount:null,currency:'欧元'}];
  const env=harness(async()=>({revision:1,month:202608,records:[],expected,pendingImports:[],summary:{}}));
  await env.api.open();
  assert.match(env.$('externalRows').innerHTML,/待核人员/);
  assert.match(env.$('externalRows').innerHTML,/体系外负责人/);
  assert.match(env.$('externalRows').innerHTML,/待导入本月结果/);
  assert.doesNotMatch(env.$('externalRows').innerHTML,/0\.00/);
  assert.doesNotMatch(env.markup.at(-1),/上月人员已承接|type="checkbox"/);
  assert.equal(api.tableModel({records:[{id:'adopted',candidateName:'已核人员'}],expected}).total,2);
});

test('a matched person with an ownership issue opens the existing details without another person selection',async()=>{
  const preview={token:'matched',revision:1,rows:[{id:'line',rowId:'person',candidateName:'已匹配人员',scopeExpanded:true,status:'blocked',issues:['领取人与当前安排不同'],candidates:[{rowId:'person',name:'已匹配人员'}]}],readyCount:0,blockedCount:1};
  const env=harness(async url=>url.endsWith('/previews/matched')?preview:{revision:1,records:[],pendingImports:[],summary:{}},true);
  await env.api.open();await env.api.loadPreview('matched');
  assert.match(env.$('externalRows').innerHTML,/data-external-review="person"/);
  assert.doesNotMatch(env.$('externalRows').innerHTML,/data-external-person|请选择对应人员/);
});
