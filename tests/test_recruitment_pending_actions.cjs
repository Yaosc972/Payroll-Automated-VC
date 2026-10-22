const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../bonus_platform/static/recruitment-interactions.js'),'utf8');
function element(disabled=false){
  const attrs=new Map(),classes=new Set();
  return {disabled,innerHTML:'保存',style:{minWidth:''},firstElementChild:{},lastElementChild:{textContent:''},
    classList:{add:c=>classes.add(c),remove:c=>classes.delete(c),contains:c=>classes.has(c)},
    getAttribute:k=>attrs.get(k)??null,setAttribute:(k,v)=>attrs.set(k,v),removeAttribute:k=>attrs.delete(k),
    getBoundingClientRect:()=>({width:120}),querySelectorAll:()=>[]};
}
function surface(reducedMotion=false){
  const window={},animations=[],reduced={matches:reducedMotion,addEventListener(type,handler){this.change=handler;}};
  window.Motion={animate(target,values,options){const animation={target,values,options,stopped:false,stop(){this.stopped=true;},complete(){this.stopped=true;}};animations.push(animation);return animation;}};
  vm.runInNewContext(source,{window,matchMedia:()=>reduced});
  return {...window.RecruitmentInteractions,animations,reduced};
}
test('a pending action immediately exposes a visible busy label and locks the form once',()=>{
  const s=surface(),button=element(),input=element(),blocked=element(true),form=element();form.querySelectorAll=()=>[button,input,blocked];
  const finish=s.pending(button,'正在核算…',form);
  assert.equal(button.lastElementChild.textContent,'正在核算…');
  assert.match(button.innerHTML,/rd-action-spinner/);
  assert.equal(button.getAttribute('aria-busy'),'true');assert.equal(form.getAttribute('aria-busy'),'true');
  assert.ok(button.disabled&&input.disabled&&blocked.disabled);
  assert.equal(button.style.minWidth,'120px');
  assert.equal(s.pending(button,'重复提交',form),null);
  assert.equal(s.animations.length,1);assert.equal(s.animations[0].options.repeat,Infinity);
  finish();assert.equal(button.innerHTML,'保存');assert.equal(button.disabled,false);assert.equal(input.disabled,false);assert.equal(blocked.disabled,true);
  assert.equal(button.getAttribute('aria-busy'),null);assert.equal(form.getAttribute('aria-busy'),null);assert.equal(s.animations[0].stopped,true);
});
test('completion and failure both release the pending state without clearing the next operation',()=>{
  const s=surface(),button=element();
  const finish=s.pending(button,'正在保存…');finish();
  const retry=s.pending(button,'正在重试…');finish();
  assert.equal(button.getAttribute('aria-busy'),'true');assert.equal(button.lastElementChild.textContent,'正在重试…');
  retry();assert.equal(button.disabled,false);assert.equal(button.style.minWidth,'');
});
test('closing a form releases only its own controls and preserves existing disabled states',()=>{
  const s=surface(),button=element(),form=element(),replacement=element();form.querySelectorAll=()=>[button];form.setAttribute('aria-busy','false');
  const finish=s.pending(button,'正在保存…',form);form.isConnected=false;finish();
  assert.equal(replacement.innerHTML,'保存');assert.equal(replacement.disabled,false);assert.equal(form.getAttribute('aria-busy'),'false');
});
test('reduced motion retains the busy indication without starting a spinner animation',()=>{
  const s=surface(true),button=element(),finish=s.pending(button,'正在核算…');
  assert.match(button.innerHTML,/rd-action-spinner/);assert.equal(s.animations.length,0);finish();
});
test('switching to reduced motion completes active animations',()=>{
  const s=surface(),button=element(),finish=s.pending(button,'正在保存…');s.reduced.matches=true;s.reduced.change();
  assert.equal(s.animations[0].stopped,true);finish();assert.equal(button.disabled,false);
});
