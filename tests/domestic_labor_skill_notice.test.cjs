const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('bonus_platform/static/domestic-labor-skill-notice.js', 'utf8');
const prefix = 'hras:domestic-skillhub:seen:v1:';
const skill = (id, fingerprint, name = '操作线高温补贴') => ({id, fingerprint, name, released_at:'2026-10-10T00:00:00Z', is_new:false});
function browser(storage = new Map()) {
  const elements = Object.fromEntries(['navSkillHub','skillHubNotice','skillHubNoticeLabel','skillHubNoticeCount'].map(id => [id, {
    hidden:true, textContent:'', attributes:{}, events:{},
    setAttribute(key, value) { this.attributes[key] = value; },
    removeAttribute(key) { delete this.attributes[key]; },
    addEventListener(key, fn) { this.events[key] = fn; },
  }]));
  const events = {};
  const context = vm.createContext({Map, Date, console,
    document:{hidden:false,getElementById:id=>elements[id],addEventListener(){}},
    window:{addEventListener:(key,fn)=>{events[key]=fn;}},
    localStorage:{getItem:key=>storage.get(key) ?? null,setItem:(key,value)=>storage.set(key,value)},
    fetch:async()=>({ok:true,json:async()=>({skills:[]})}),
  });
  vm.runInContext(source, context);
  return {elements,context,events,refresh:context.window.DomesticSkillUpdates.refresh,
    catalog(rows) { context.fetch=async()=>({ok:true,json:async()=>({skills:rows})}); },
    click(type='click',button=0) { elements.navSkillHub.events[type]({type,button,defaultPrevented:false}); },
    get visible() { return !elements.skillHubNotice.hidden; },
  };
}
test('unread release appears, entry click persists dismissal through reload, and new content reappears', async () => {
  const storage = new Map(), a = browser(storage);
  a.catalog([skill('gaowen_butie','v1')]); await a.refresh('alice');
  assert.equal(a.visible,true); assert.equal(a.elements.skillHubNoticeLabel.textContent,'高温补贴 Skill 上新');
  a.click(); assert.equal(a.visible,false);
  const b=browser(storage); b.catalog([skill('gaowen_butie','v1')]); await b.refresh('alice');
  assert.equal(b.visible,false);
  b.catalog([skill('gaowen_butie','v2')]); await b.refresh('alice'); assert.equal(b.visible,true);
});
test('reading one release does not acknowledge a concurrently published version', async () => {
  const a=browser(); a.catalog([skill('gaowen_butie','v1')]); await a.refresh('alice');
  let complete; a.context.fetch=()=>new Promise(r=>{complete=r;});
  const update=a.refresh('alice'); a.click();
  complete({ok:true,json:async()=>({skills:[skill('gaowen_butie','v2')]})}); await update;
  assert.equal(a.visible,true);
});
test('all displayed subjects are acknowledged; a single later update names only that subject', async () => {
  const a=browser(); a.catalog([skill('gaowen_butie','v1'),skill('waisu_butie','v1','操作线外宿补贴')]); await a.refresh('alice');
  assert.equal(a.elements.skillHubNoticeCount.textContent,'+1');
  assert.match(a.elements.navSkillHub.title,/高温补贴、外宿补贴/);
  a.click('auxclick',1); assert.equal(a.visible,false);
  a.catalog([skill('gaowen_butie','v1'),skill('waisu_butie','v2','操作线外宿补贴')]); await a.refresh('alice');
  assert.equal(a.elements.skillHubNoticeLabel.textContent,'外宿补贴 Skill 上新');
  assert.equal(a.elements.skillHubNoticeCount.hidden,true);
});
test('read state is isolated by account and late responses cannot restore another user notice', async () => {
  const a=browser(); a.catalog([skill('gaowen_butie','v1')]); await a.refresh('alice'); a.click();
  await a.refresh('bob'); assert.equal(a.visible,true);
  await a.refresh('alice'); assert.equal(a.visible,false);
  let complete; a.context.fetch=()=>new Promise(r=>{complete=r;}); const stale=a.refresh('bob');
  a.catalog([skill('gaowen_butie','v1')]); await a.refresh('alice');
  complete({ok:true,json:async()=>({skills:[skill('gaowen_butie','v2')]})}); await stale;
  assert.equal(a.visible,false);
});
test('catalog failure hides notification without erasing read state or preventing navigation', async () => {
  const a=browser(); a.catalog([skill('gaowen_butie','v1')]); await a.refresh('alice'); a.click();
  a.context.fetch=async()=>({ok:false}); await a.refresh('alice'); assert.equal(a.visible,false);
  a.catalog([skill('gaowen_butie','v1')]); await a.refresh('alice'); assert.equal(a.visible,false);
});
test('storage write failure still dismisses current page, and malformed saved data recovers', async () => {
  const storage=new Map([[prefix+'alice','broken JSON']]); const a=browser(storage);
  a.catalog([skill('gaowen_butie','v1')]); await a.refresh('alice'); assert.equal(a.visible,true);
  a.context.localStorage.setItem=()=>{throw Error('Storage full');}; a.click(); assert.equal(a.visible,false);
  await a.refresh('alice'); assert.equal(a.visible,false);
});
test('read marker synchronizes across tabs, and bfcache return checks for a new release', async () => {
  const storage=new Map(), a=browser(storage), b=browser(storage);
  for (const tab of [a,b]) {tab.catalog([skill('gaowen_butie','v1')]); await tab.refresh('alice');}
  a.click(); b.events.storage({key:prefix+'alice'}); assert.equal(b.visible,false);
  b.catalog([skill('gaowen_butie','v2')]); b.events.pageshow({persisted:true});
  await new Promise(resolve=>setImmediate(resolve)); assert.equal(b.visible,true);
});
test('right click and prevented clicks leave releases unread', async () => {
  const a=browser(); a.catalog([skill('gaowen_butie','v1')]); await a.refresh('alice');
  a.click('auxclick',2); assert.equal(a.visible,true);
  a.elements.navSkillHub.events.click({type:'click',button:0,defaultPrevented:true}); assert.equal(a.visible,true);
});
