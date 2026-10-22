const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const script = fs.readFileSync(path.join(__dirname, '../bonus_platform/static/recruitment-flow.js'), 'utf8');

function surface(job, data = null) {
  const elements = new Map(), listeners = new Map(), calls = [], reviews = [], records = [];
  const element = id => {
    if (elements.has(id)) return elements.get(id);
    const node = {id, value:'', dataset:{}, style:{}, classList:{add(){}, remove(){}, toggle(){}},
      addEventListener(){}, setAttribute(){}, append(){}, after(){}, before(){}, focus(){},
      insertAdjacentHTML(){}, scrollTo(){}, querySelectorAll(){return [];},
      querySelector(selector){return element(id+selector);}, getClientRects(){return [];}};
    elements.set(id, node); node.parentElement = node;
    return node;
  };
  const ui = {data, view:'todos', busy:false};
  const workbench = {$:element, ui, e:String, base:()=>'/activity/test',
    request:async (url, options) => {calls.push({url, method:options?.method || 'GET'});return job;},
    render(){}, busy(){}, status(){}, adopt(){}, openDialog(){}, setView(){}, amount:String};
  const document = {body:element('body'), querySelector:element, querySelectorAll:()=>[],
    createElement:()=>element('created'+elements.size), addEventListener:(name, listener)=>listeners.set(name, listener)};
  const window = {RecruitmentWorkbench:workbench, RecruitmentWorkbenchExtension:{},
    RecruitmentExperience:{model:()=>({steps:[], progress:null})}, RecruitmentSpecial:{review:item=>reviews.push(item),records:()=>records.push('opened')}};
  const context = {window, document, location:{search:'', href:'http://localhost/'},
    history:{replaceState(){}}, URL, URLSearchParams, setTimeout, clearTimeout,
    MutationObserver:class {observe(){}} ,
    matchMedia:()=>({matches:true}), CSS:{escape:String}};
  vm.runInNewContext(script, context);
  return {ui, calls, reviews, records, window, elements, listeners};
}
function data() {return {revision:6, month:202608, previousAccepted:false, sources:[], rows:[],
  monthly:{actionCount:0, workItems:[], coverage:{recipientSyncRequired:true}}};}
const tick = () => new Promise(resolve=>setTimeout(resolve,15));

test('opening an updated calculation keeps a completed prepare job read only', async () => {
  const page = surface({status:'complete',revision:5}, data());
  await tick();
  assert.equal(page.calls.filter(c=>c.method==='POST').length, 0);
  assert.deepEqual(page.calls.map(c=>c.url), ['/activity/test/prepare']);
});
test('an ordinary opening with missing coverage does not query HR automatically', async () => {
  const page = surface(null, data());
  await tick();
  assert.equal(page.calls.filter(c=>c.method==='POST').length, 0);
});
test('newly uploaded material still starts the existing prepare operation', async () => {
  const page = surface({status:'complete',revision:6});
  page.ui.data = data();
  page.listeners.get('recruitment:uploaded')();
  await tick();
  assert.equal(page.calls.filter(c=>c.method==='POST'&&c.url.endsWith('/prepare')).length, 1);
});
test('historical work items open the existing settlement review', async () => {
  const page = surface(null);
  const item = {id:'history',key:'recovery',mode:'settlement',rowIds:['row']};
  await page.window.RecruitmentFlow.openWork(item);
  assert.equal(page.reviews[0], item);
  assert.deepEqual(page.calls, []);
});

test('an invalidated special arrangement opens adjustment records without claiming history is settled', async () => {
  const page = surface(null);
  const item = {id:'special',key:'calculation:fact',mode:'specialRecords',rowIds:['row']};
  await page.window.RecruitmentFlow.openWork(item);
  assert.deepEqual(page.records, ['opened']);
  assert.deepEqual(page.reviews, []);
  assert.deepEqual(page.calls, []);
});
