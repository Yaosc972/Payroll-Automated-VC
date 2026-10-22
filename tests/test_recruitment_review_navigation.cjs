const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

function reviewNavigation(){
  const elements=new Map(),buttons=['materials','differences','records'].map(tab=>({dataset:{rcTab:tab},focus(){}}));
  const element=id=>{
    if(!elements.has(id))elements.set(id,{value:'',textContent:'',innerHTML:'',hidden:false,parentElement:{},
      insertAdjacentHTML(){},querySelector(){return null;},close(){}});
    return elements.get(id);
  };
  let renders=0,animations=0,base='/example';
  const workbench={$:element,ui:{data:{revision:1,sources:[]},view:'todos'},e:String,base:()=>base,
    request:()=>new Promise(()=>{}),openDialog(){},setView(){element('draftSearch').value='';},render(){renders++;}};
  const window={RecruitmentWorkbench:workbench,RecruitmentInteractions:{enter(){animations++;}}};
  const document={querySelectorAll:()=>buttons,querySelector:()=>null};
  vm.runInNewContext(fs.readFileSync(require.resolve('../bonus_platform/static/recruitment-review-center.js'),'utf8'),{window,document,URLSearchParams});
  window.RecruitmentReviewCenter.render({workItems:[]},()=>{});
  return {element,buttons,review:window.RecruitmentReviewCenter,setBase(value){base=value;},get renders(){return renders;},get animations(){return animations;}};
}

test('the active review tab preserves its query and does not redraw or animate again',()=>{
  const nav=reviewNavigation(),{element,buttons}=nav;
  element('draftSearch').value='保留查询';
  buttons[0].onclick();
  assert.equal(element('draftSearch').value,'保留查询');
  assert.equal(nav.renders,0);assert.equal(nav.animations,0);
  buttons[1].onclick();
  assert.equal(nav.renders,1);assert.equal(nav.animations,1);
  element('draftSearch').value='保留差异筛选';
  buttons[1].onclick();
  assert.equal(element('draftSearch').value,'保留差异筛选');
  assert.equal(nav.renders,1);assert.equal(nav.animations,1);
});

test('switching review tabs retains the current query, including an explicitly cleared query',()=>{
  const nav=reviewNavigation(),search=nav.element('draftSearch');
  search.value='Jikai';
  for(const tab of [1,2,0]){
    nav.buttons[tab].onclick();
    assert.equal(search.value,'Jikai');
  }
  search.value='';
  for(const tab of [2,1,0]){
    nav.buttons[tab].onclick();
    assert.equal(search.value,'');
  }
  assert.equal(nav.renders,6);
  assert.equal(nav.animations,6);
});

test('opening the review workspace in another activity starts with a blank query',()=>{
  const nav=reviewNavigation();
  nav.element('draftSearch').value='Jikai';
  nav.setBase('/another-activity');
  nav.review.open('differences');
  assert.equal(nav.element('draftSearch').value,'');
});
