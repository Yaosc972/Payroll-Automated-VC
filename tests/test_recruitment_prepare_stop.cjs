const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const window={};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../bonus_platform/static/recruitment-experience.js'),'utf8'),{window});
const model=window.RecruitmentExperience.model;
const draft={revision:6,rows:[{id:'person'}],sources:[{id:'source'}],monthly:{coverage:{hasOpening:true},worksheet:{rows:[]}}};

test('one click starts the combined monthly job and blocks repeated clicks while it runs',async()=>{
 const source=fs.readFileSync(path.join(__dirname,'../bonus_platform/static/recruitment-flow.js'),'utf8');
 const calls=[],context={ui:{data:{activity:{}}},activePreparation:job=>['running','cancelling'].includes(job?.status),
   busy:value=>{context.ui.busy=value;},status:()=>{},base:()=>'/month',jobBase:'',
   post:async url=>{calls.push(url);return {status:'running',monthlyAll:true};},watch:()=>calls.push('poll'),update:()=>{}};
 vm.createContext(context);vm.runInContext(source.slice(source.indexOf('  async function syncMonthly('),source.indexOf('  async function syncDomestic(')),context);
 await context.syncMonthly();await context.syncMonthly();
 assert.deepEqual(calls,['/sync-monthly','poll']);assert.equal(context.ui.busy,false);
});

test('running and stopping preparation stay locked until the worker acknowledges the stop',()=>{
 const running=model(draft,{id:'job-one',status:'running',revision:5,stage:'refresh'});
 assert.equal(running.progress.canCancel,true);
 const stopping=model(draft,{id:'job-one',status:'cancelling',revision:5,stage:'refresh'});
 assert.equal(stopping.progress.title,'正在停止');
 assert.equal(stopping.progress.canCancel,false);
 assert.equal(stopping.steps[1].state,'running');
});

test('a cancelled task does not claim completion or offer an automatic retry',()=>{
 const state=model(draft,{id:'job-one',status:'cancelled',revision:6,message:'已停止，已保存的资料保留。'});
 assert.equal(state.progress.title,'已停止');
 assert.equal(state.progress.retry,false);
 assert.notEqual(state.steps[1].state,'running');
});

test('stopping targets the exact running job and resumes status polling',async()=>{
 const source=fs.readFileSync(path.join(__dirname,'../bonus_platform/static/recruitment-flow.js'),'utf8');
 const start=source.indexOf('  async function stopPreparation(');
 assert.notEqual(start,-1,'the stop action must send a backend cancellation');
 const calls=[],context={ui:{prepareJob:{id:'job-one',status:'running'}},base:()=>'/month',post:async(url,payload)=>{calls.push({url,payload});return {id:'job-one',status:'cancelling'};},update:()=>{},watch:()=>calls.push('poll'),status:()=>{},jobBase:'',clearTimeout:()=>{},pollTimer:null,pollSequence:0};
 vm.createContext(context);
 vm.runInContext(source.slice(start,source.indexOf('  async function beforeUpload(',start)),context);
 await context.stopPreparation();
 assert.equal(calls[0].url,'/prepare/cancel');
 assert.equal(calls[0].payload.jobId,'job-one');
 assert.equal(context.ui.prepareJob.status,'cancelling');
 assert.equal(calls[1],'poll');
 await context.stopPreparation();
 assert.equal(calls.length,2,'a repeated stop must not submit again');
});

test('a stopped initial preparation is not restarted by reopening the page',async()=>{
 const source=fs.readFileSync(path.join(__dirname,'../bonus_platform/static/recruitment-flow.js'),'utf8');
 const calls=[],context={ui:{data:{previousAccepted:true,revision:0}},base:()=>'/month',request:async()=>({id:'one',status:'cancelled',revision:0}),activePreparation:job=>['running','cancelling'].includes(job?.status),prepare:()=>calls.push('restart'),update:()=>{},status:()=>{}};
 vm.createContext(context);vm.runInContext(source.slice(source.indexOf('  async function resume('),source.indexOf('  async function prepare(')),context);
 await context.resume();assert.equal(calls.length,0);
});

test('a stop acknowledged at the displayed revision skips the full draft download',async()=>{
 const source=fs.readFileSync(path.join(__dirname,'../bonus_platform/static/recruitment-flow.js'),'utf8');
 const calls=[],context={ui:{data:{revision:6}},base:()=>'/month',jobBase:'/month',pollSequence:0,clearTimeout:()=>{},pollTimer:null,activePreparation:job=>['running','cancelling'].includes(job?.status),request:async url=>{calls.push(url);return {id:'one',status:'cancelled',revision:6,message:'已停止'};},status:()=>{},update:()=>{}};
 vm.createContext(context);vm.runInContext(source.slice(source.indexOf('  async function watch('),source.indexOf('  function lockArchived(')),context);
 await context.watch();assert.deepEqual(calls,['/month/prepare']);assert.equal(context.ui.prepareJob.status,'cancelled');
});
