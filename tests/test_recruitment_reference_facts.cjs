const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const script=fs.readFileSync(path.join(__dirname,'../bonus_platform/static/recruitment-approvals.js'),'utf8');

function surface(){
  const elements=new Map(),calls=[];
  const element=id=>{
    if(!elements.has(id))elements.set(id,{id,dataset:{},value:'',checked:false,hidden:false,textContent:'',
      classList:{add(){},remove(){},contains(){return false;}},addEventListener(){},setAttribute(){},focus(){},scrollIntoView(){},
      querySelectorAll(){return [];},querySelector(selector){return element(id+selector);}});
    return elements.get(id);
  };
  const channel={field:'招聘渠道',value:'招聘网站',label:'招聘网站 · 已上传核对表 Sheet1!D2',sources:[{sourceId:'reference',cell:'D2'}],referenceProposal:{proposalId:'channel-proposal',signature:'signed'}};
  const items=Array.from({length:7},(_,i)=>({id:'item'+i,sourceId:'approval',sourceName:'原审批',person:{rowId:'row'+i,name:'人员'+i},matches:[],documentIssues:[],extractionIssues:[],decisions:[],
    status:i===6?'blocked':'ready',issues:i===6?['请补充实际招聘渠道。']:[],fields:[{field:i===6?'招聘渠道':'ABC类别',value:i===6?'':'B',before:i===6?'内推':'C'}],referenceOptions:i===6?[channel]:[]}));
  const data={revision:6,items,documents:[{sourceId:'approval',name:'原审批',items:items.map(i=>i.id),issues:[],pageNumbers:[]}]};
  const controls=new Map(),containers=new Map(),checks=new Map();
  for(const item of items){
    const control=element('control'+item.id);control.dataset.approvalField=item.fields[0].field;control.value=item.fields[0].value;controls.set(item.id,control);
    const check=element('check'+item.id);check.dataset.approvalSelect=item.id;checks.set(item.id,check);
    const container=element('container'+item.id);container.dataset.approvalItem=item.id;
    container.querySelectorAll=selector=>selector==='[data-approval-field]'?[control]:[];
    container.querySelector=selector=>selector==='[data-approval-select]'?check:selector==='.rai-state'||selector==='.rai-issues'?element(item.id+selector):null;
    containers.set(item.id,container);
  }
  const ui={busy:false,data:{revision:6,approvalAdjustments:data,rows:items.map(i=>({id:i.person.rowId,values:{姓名:i.person.name,招聘渠道:'内推',ABC类别:'C'}}))}};
  const w={$:element,ui,e:String,base:()=>'/isolated',amount:String,openDialog(_title,html){element('html').textContent=html;},status(){},busy(value){ui.busy=value;},adopt(value){ui.data=value;},
    async request(url,options){calls.push({url,payload:JSON.parse(options.body)});return url.endsWith('/preview')?{id:'preview',revision:6,currentImpact:[],remainingIssues:[]}:{...ui.data,revision:7,approvalAdjustments:{...data,revision:7}};}};
  const document={addEventListener(){},dispatchEvent(){},querySelectorAll(selector){return selector==='[data-approval-item]'?[...containers.values()]:selector==='[data-approval-select]'?[...checks.values()]:[];}};
  const window={RecruitmentWorkbench:w};
  vm.runInNewContext(script,{window,document,CustomEvent:class{}});
  return {calls,ui,element,controls,open:()=>window.RecruitmentApprovals.open()};
}

test('reference channel uses the original approval preview and preserves six ready selections',async()=>{
  const page=surface();await page.open();
  assert.match(page.element('approvalApply').innerHTML,/6 项/);
  assert.match(page.element('html').textContent,/已上传核对表 Sheet1!D2/);
  const field=page.controls.get('item6');field.value='reference:channel-proposal';field.oninput();
  assert.match(page.element('approvalApply').innerHTML,/7 项/);
  await page.element('approvalApply').onclick();
  assert.equal(page.calls.length,2);
  assert.equal(page.calls[0].url,'/isolated/approval-adjustments/preview');
  assert.deepEqual(page.calls[0].payload.referenceSelections,[{itemId:'item6',proposalId:'channel-proposal',signature:'signed'}]);
  assert.equal(page.calls[0].payload.itemIds.length,7);
  assert.equal(page.calls[0].payload.overrides.item6.fields['招聘渠道'],undefined);
  assert.equal(page.calls[1].url,'/isolated/previews/preview/apply');
});

test('typing a channel after choosing a reference removes the reference selection',async()=>{
  const page=surface();await page.open();
  const field=page.controls.get('item6');field.value='reference:channel-proposal';field.oninput();field.value='猎头';field.oninput();
  await page.element('approvalImpact').onclick();
  assert.equal(page.calls.length,1);
  assert.deepEqual(page.calls[0].payload.referenceSelections,[]);
  assert.equal(page.calls[0].payload.overrides.item6.fields['招聘渠道'],'猎头');
});
