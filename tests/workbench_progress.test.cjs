const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
function harness(fetchImpl=async()=>new Response('{}',{status:200})) {
  const nodes=new Map();
  class Node {
    constructor(){this.children=new Map();this.style={};this.dataset={};this.attributes={};this.classList={toggle(){}};this.isConnected=true;this.open=false;}
    querySelector(key){if(!this.children.has(key))this.children.set(key,new Node());return this.children.get(key);}
    setAttribute(k,v){this.attributes[k]=v;}removeAttribute(k){delete this.attributes[k];}
    append(n){if(n.id)nodes.set(n.id,n);if(n.className==='wb-progress')nodes.set('panel',n);}
    replaceChildren(){}addEventListener(){}showModal(){this.open=true;}close(){this.open=false;}remove(){this.isConnected=false;}focus(){}
  }
  const document={createElement:()=>new Node(),body:new Node(),activeElement:new Node(),getElementById:id=>nodes.get(id)};
  const requests=[];
  class XHR {
    constructor(){this.upload={};requests.push(this);}
    open(method,url){this.method=method;this.url=url;}setRequestHeader(){}send(body){this.body=body;}
    abort(){this.onabort?.();this.onloadend?.();}
    getAllResponseHeaders(){return 'content-type: application/json';}
    complete(){this.status=200;this.statusText='OK';this.responseText='{}';this.onload();this.onloadend?.();}
  }
  const window={fetch:fetchImpl,matchMedia:()=>({matches:true,addEventListener(){}})};
  vm.runInNewContext(fs.readFileSync('bonus_platform/static/workbench-progress.js','utf8'),{window,document,location:{href:'http://localhost/'},FormData,Headers,Response,URL,DOMException,XMLHttpRequest:XHR});
  return {api:window.WorkbenchProgress,requests,nodes};
}
test('unrelated reads and authentication bypass the progress UI',async()=>{
  let calls=0;const h=harness(async()=>{calls++;return new Response('{}');});
  await h.api.fetch('/api/me');assert.equal(calls,1);assert.equal(h.nodes.has('panel'),false);
});
test('multipart upload can be aborted and rejects before processing results',async()=>{
  const h=harness();const pending=h.api.fetch('/api/runs/calculate',{method:'POST',body:new FormData()});
  const rejected=assert.rejects(pending,{name:'AbortError'});
  await h.nodes.get('panel').querySelector('[data-stop]').onclick();await rejected;
  assert.equal(h.nodes.get('panel').dataset.phase,'stopped');
});
test('stop after upload waits for the current server step and does not claim to kill it',async()=>{
  const h=harness();const pending=h.api.fetch('/api/china-employee-payroll/meal-allowance',{method:'POST',body:new FormData()});
  h.requests[0].upload.onload();
  const panel=h.nodes.get('panel');assert.equal(panel.querySelector('[data-stop]').textContent,'中止后续处理');
  await panel.querySelector('[data-stop]').onclick();
  assert.equal(panel.dataset.phase,'calculate');
  const rejected=assert.rejects(pending,{name:'AbortError'});h.requests[0].complete();await rejected;
  assert.equal(panel.dataset.phase,'stopped');
});
test('server errors remain errors; unknown progress has no invented percentage',async()=>{
  const h=harness(async()=>new Response('{}',{status:422}));
  const response=await h.api.fetch('/api/social-insurance/runs/a/generate-package',{method:'POST'});
  assert.equal(response.status,422);assert.equal(h.nodes.get('panel').dataset.phase,'failed');
  assert.equal(h.nodes.get('panel').querySelector('[role="progressbar"]').attributes['aria-valuenow'],undefined);
});
test('completion is idempotent and cannot turn a stopped operation into success',()=>{
  const h=harness();const task=h.api.begin({subject:'测试'});task.fail(h.api.abortError());task.finish();
  assert.equal(h.nodes.get('panel').dataset.phase,'stopped');
});
