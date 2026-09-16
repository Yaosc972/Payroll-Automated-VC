const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('bonus_platform/static/domestic-labor.js', 'utf8');
const section = (start, end) => source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start)));
test('slow startup does not navigate away after the user opens an activity', async () => {
  let resolve, restored = false;
  const state = {view:'home', navigationRevision:0};
  const context = vm.createContext({state, location:{hash:'#view=home'}, restoringPayrollPage:true,
    loadEngineCards(){},loadTemplateLinks(){},bindEvents(){},setDefaultMonth(){},setDefaultCanbuBatchMonth(){},renderEmptyWorkbench(){},renderRecentBatchTable(){},setupActivityList(){},rememberPayrollPage(){},
    showView(view){state.view=view;state.navigationRevision++;},
    refreshActivities:()=>new Promise(r=>{resolve=r;}),restorePayrollPage:()=>{restored=true;state.view='home';},
  });
  vm.runInContext(section('async function init()', 'function setDefaultMonth('),context);
  const pending=context.init();
  context.showView('canbuWorkbench');
  resolve();await pending;
  assert.equal(state.view,'canbuWorkbench');assert.equal(restored,false);
});
test('a list request started before creation cannot remove the new uploading activity', async () => {
  let resolve;
  const state={canbuBatches:[],activityUser:{ownerId:'alice'}};
  const context=vm.createContext({state,requestJson:()=>new Promise(r=>{resolve=r;})});
  vm.runInContext(section('async function loadCanbuBatches()', 'function saveCanbuBatches('),context);
  const pending=context.loadCanbuBatches();
  state.canbuBatches.push({id:'new',isMine:true,status:'上传中',runId:'run'});
  state.activeCanbuBatchId='new';
  resolve({activities:[],currentUser:{ownerId:'alice'}});await pending;
  assert.equal(state.canbuBatches[0]?.id,'new');
  assert.equal(state.canbuBatches[0]?.runId,'run');
});
test('activity dates display China time even in a UTC browser', () => {
  const context=vm.createContext({Intl,Date});
  vm.runInContext(section('function formatDateTime(', 'function getCurrentMonthValue('),context);
  assert.equal(context.formatDateTime('2026-09-16T10:23:00+00:00'),'2026-09-16 18:23');
  assert.equal(context.formatDateTime('2026-09-16T18:23:00+08:00'),'2026-09-16 18:23');
});
test('stale response cannot roll back a run link assigned during upload', async () => {
  let resolve;
  const state={canbuBatches:[{id:'a',runId:'',status:'草稿'}],activityUser:{ownerId:'alice'}};
  const context=vm.createContext({state,requestJson:()=>new Promise(r=>{resolve=r;})});
  vm.runInContext(section('async function loadCanbuBatches()', 'function saveCanbuBatches('),context);
  const pending=context.loadCanbuBatches();
  Object.assign(state.canbuBatches[0],{runId:'run',status:'已核算'});
  resolve({activities:[{id:'a',runId:'',status:'草稿'}],currentUser:{ownerId:'alice'}});await pending;
  assert.equal(state.canbuBatches[0].runId,'run');assert.equal(state.canbuBatches[0].status,'已核算');
});
test('out-of-order refreshes keep the latest response', async () => {
  const resolve=[];const state={canbuBatches:[],activityUser:{ownerId:'alice'}};
  const context=vm.createContext({state,requestJson:()=>new Promise(r=>resolve.push(r))});
  vm.runInContext(section('async function loadCanbuBatches()', 'function saveCanbuBatches('),context);
  const old=context.loadCanbuBatches(),latest=context.loadCanbuBatches();
  resolve[1]({activities:[{id:'new'}],currentUser:{ownerId:'alice'}});await latest;
  resolve[0]({activities:[],currentUser:{ownerId:'alice'}});await old;
  assert.equal(state.canbuBatches[0].id,'new');
});
test('opening activity list during startup reuses the read and exposes loading until completion', async () => {
  let resolve, reads=0, notifyStarted;
  const started=new Promise(r=>{notifyStarted=r;});
  const state={}; const button={}; const renders=[];
  const context=vm.createContext({state,activityRefreshPromise:null,activitySaveQueue:Promise.resolve(),
    document:{querySelector:()=>button},renderCanbuBatchList:()=>renders.push(state.activityLoading),renderRecentBatchTable(){},
    loadCanbuBatches:()=>{reads++;notifyStarted();return new Promise(r=>{resolve=r;});},
  });
  vm.runInContext(section('function refreshActivities()', 'function setupActivityList('),context);
  const startup=context.refreshActivities();
  await started;
  const navigation=context.refreshActivities();
  assert.equal(reads,1);assert.equal(startup,navigation);
  assert.equal(state.activityLoading,true);assert.equal(button.textContent,'正在读取…');
  resolve();await startup;
  assert.equal(state.activityLoading,false);assert.equal(button.disabled,false);
  assert.deepEqual(renders,[true,false]);
});
