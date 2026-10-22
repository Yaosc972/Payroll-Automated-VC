const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../bonus_platform/static/recruitment-flow.js'),'utf8');
const window={RecruitmentWorkbench:{},RecruitmentWorkbenchExtension:{}};
vm.runInNewContext(source.slice(0,source.indexOf('  let pollTimer'))+'})();',{window});
const payload=window.RecruitmentWorkbench.editPayload;
const clean=value=>JSON.parse(JSON.stringify(value));
const fields=[{field:'ABC类别',targets:['row']},{field:'招聘负责人工号',targets:['row']}];

test('source selection sends only proposal identifiers and does not trust the displayed reference value',()=>{
  const choice={proposalId:'fact',signature:'signed',value:999999,field:'奖金金额',sources:['forged']};
  const result=clean(payload(fields,new Set([0]),()=>999999,{0:'comparison'},{},{0:choice},{}));
  assert.deepEqual(result,{edits:[],referenceSelections:[{proposalId:'fact',signature:'signed'}],employmentSelections:[]});
});
test('clearing a source choice and manually typing restores the ordinary edit and drops its old source',()=>{
  const referenceChoices={0:{proposalId:'fact',signature:'signed'}};
  delete referenceChoices[0];
  const result=clean(payload(fields,new Set([0]),()=>'',{},{},referenceChoices,{}));
  assert.deepEqual(result.edits,[{rowId:'row',field:'ABC类别',value:'',evidenceId:''}]);
  assert.deepEqual(result.referenceSelections,[]);
});
test('manual person choice preserves paired identity and untouched fields stay omitted',()=>{
  const result=clean(payload(fields,new Set([1]),()=>'zt-owner',{},{1:{name:'负责人'}},{},{}));
  assert.deepEqual(result.edits,[{rowId:'row',field:'招聘负责人工号',value:'zt-owner',evidenceId:''},{rowId:'row',field:'招聘负责人姓名',value:'负责人',evidenceId:''}]);
});
test('one original preview accepts relation and reference choices in the same payload',()=>{
  const relation={rowId:'row',relation:'new_hire',signature:'segment'};
  const result=clean(payload(fields,new Set([0,1]),()=>'',{},{},{0:{proposalId:'fact',signature:'signed'},1:{proposalId:'fact',signature:'signed'}},{row:relation}));
  assert.equal(result.referenceSelections.length,1);
  assert.deepEqual(result.employmentSelections,[relation]);
  assert.deepEqual(result.edits,[]);
});

test('a relation-only person can choose a relation and preview without a dummy field',async()=>{
  const elements={},sections=[],requests=[];
  const element=()=>({hidden:false,disabled:false,innerHTML:'',textContent:'',dataset:{},isConnected:true,scrollIntoView(){},focus(){this.focused=true;}});
  const form=element();
  form.querySelector=selector=>sections.find(section=>selector===`[data-flow-person="${section.rowId}"]`)||null;
  form.querySelectorAll=selector=>selector==='.flow-review-person'?sections:sections.flatMap(section=>section.select?[section.select]:[]);
  const openDialog=(title,markup)=>{
    for(const match of markup.matchAll(/id="([^"]+)"/g))elements[match[1]]=element();
    elements.flowEditForm=form;elements.draftInspector={open:true};
    for(const match of markup.matchAll(/<section class="flow-review-person" data-flow-person="([^"]+)"/g)){
      const section={...element(),rowId:match[1],querySelector(selector){
        if(selector==='header')return {insertAdjacentHTML(position,html){
          if(html.includes('data-flow-employment='))section.select=element();
        }};
        return selector==='[data-flow-employment]'?section.select:null;
      }};
      sections.push(section);
    }
    assert.doesNotMatch(markup,/data-flow-value=/);
  };
  const context={window:{RecruitmentInteractions:{enter(){},pending(){return ()=>{};}}},ui:{data:{sources:[]}},e:String,fieldName:String,label:String,text:String,help:{},
    $:id=>elements[id],base:()=>'/draft',openDialog,CSS:{escape:String},document:{querySelectorAll:()=>[]},
    editPayload:payload,post:async(path,body)=>{requests.push({path,body:clean(body)});return {id:'preview',revision:3};},
    impactMarkup:()=>'<p>修改结果</p>',w:{sourceLink:()=>''}};
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('  function editForm('),source.indexOf('  async function inspect(')),context);
  context.editForm('核对任职',[],'',3,[{rowId:'current',name:'甲',signature:'proof',options:[{value:'new_hire',label:'本次为新招聘／二次入职'}]}]);
  assert.equal(sections.length,1);
  assert.equal(sections[0].rowId,'current');
  assert.equal(typeof sections[0].select.onchange,'function');
  sections[0].select.onchange({target:{value:'new_hire'}});
  assert.equal(form.dataset.dirty,'true');
  await form.onsubmit({preventDefault(){},target:form});
  assert.deepEqual(requests,[{path:'/previews',body:{revision:3,edits:[],referenceSelections:[],employmentSelections:[{rowId:'current',relation:'new_hire',signature:'proof'}]}}]);
  assert.equal(elements.flowApply.hidden,false);
  assert.equal(elements.flowApply.disabled,false);
});
