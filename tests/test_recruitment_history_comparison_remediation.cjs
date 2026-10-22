const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const script = fs.readFileSync(path.join(__dirname, '../bonus_platform/static/recruitment-special.js'), 'utf8');

function surface(recovery) {
  const elements = new Map(), requests = [];
  const element = id => {
    if (elements.has(id)) return elements.get(id);
    const node={id,value:'',textContent:'',open:true,isConnected:true,hidden:false,disabled:false,dataset:{},
      classList:{remove(){},add(){}},querySelectorAll(selector){
        if(selector!=='[data-rs-retain]')return [];
        return [...String(node.html||'').matchAll(/data-rs-retain="([^"]+)"/g)].map(m=>{const button=element('retain:'+m[1]);button.dataset.rsRetain=m[1];return button;});
      },querySelector(){return element('condition');},
      scrollIntoView(){},closest(){return element('conditionLabel');}};
    node.firstElementChild={isConnected:true};node.parentElement=node;
    Object.defineProperty(node,'innerHTML',{get(){return node.html||'';},set(value){node.html=value;}});
    elements.set(id,node);return node;
  };
  const ui={data:{revision:6,month:202608},busy:false};
  const row={id:'row',values:{姓名:'Perrie样例',招聘负责人姓名:'原领取人',招聘负责人工号:'old'},calculation:{recruitment:{currency:'美元',nodes:[]},referral:{currency:'美元',nodes:[]}}};
  function openDialog(title,html){
    element('draftInspectorBody').innerHTML=html;
    for (const m of html.matchAll(/<select id="([^"]+)"[^>]*>([\s\S]*?)<\/select>/g)) {
      const selected=m[2].match(/<option value="([^"]*)" selected/)||m[2].match(/<option value="([^"]*)"/);
      element(m[1]).value=selected?.[1]||'';
    }
    for (const m of html.matchAll(/<input id="([^"]+)"([^>]*)>/g))element(m[1]).value=m[2].match(/value="([^"]*)"/)?.[1]||'';
  }
  const workbench={$:element,ui,e:String,base:()=>'/activity/example',openDialog,amount:(v,c)=>`${v} ${c||''}`,
    request:async (url,options)=>{requests.push({url,options});return options?.method==='POST'?{id:'preview'}:url.includes('/rows/')?{row}:{revision:6,policies:{},records:[],recoveries:[recovery],historyRecoveries:[recovery]};}};
  const window={RecruitmentWorkbench:workbench,RecruitmentActions:{open(){}},RecruitmentAdjustmentModel:{signedAmount(){}},RecruitmentInteractions:{enter(){},pending(){return ()=>{};}}};
  const document={querySelector:()=>({open:true}),querySelectorAll:()=>[]};
  vm.runInNewContext(script,{window,document,console});
  return {window,elements,requests};
}
const recovery={key:'historical',rowId:'row',kind:'recruitment',role:'招聘负责人',recipientId:'old',recipientName:'原领取人',
  signedAmount:-35.75,amount:35.75,currency:'美元',adjustmentAllowed:true,historyAmount:35.75,currentAmount:0,currentRule:{currency:'美元'},openingFacts:[],
  originalNotes:[{text:'3月扣回35.75美元',sourceRef:{sourceId:'original',sheet:'原台账',row:829},column:72}],
  relatedRecords:[{type:'adjustment',active:false,sourceValid:true,issues:[],amount:-10,currency:'美元',month:202603,reason:'原安排已撤销'}]};

test('the original adjustment form leaves historical money empty and keeps the claim beside it', async()=>{
  const page=surface(recovery);
  await page.window.RecruitmentSpecial.open('row',{type:'adjustment',kind:'recruitment',recovery});
  assert.equal(page.elements.get('rsAmount').value,'');
  assert.equal(page.elements.get('rsDirection').value,'deduct');
  const html=page.elements.get('draftInspectorBody').innerHTML;
  assert.match(html,/3月扣回35.75美元/);
  assert.match(html,/差额参考：35.75 美元/);
  assert.match(html,/原安排已撤销/);
  assert.ok(html.indexOf('原表备注')<html.indexOf('id="rsAmount"'));
  assert.equal(page.requests.filter(r=>r.options?.method==='POST').length,0);
});

test('history review shows source notes and existing arrangements before its money action', async()=>{
  const page=surface(recovery);
  await page.window.RecruitmentSpecial.review({rowIds:['row']});
  const html=page.elements.get('draftInspectorBody').innerHTML;
  assert.ok(html.indexOf('3月扣回35.75美元')<html.indexOf('data-rs-correct'));
  assert.ok(html.indexOf('原安排已撤销')<html.indexOf('data-rs-correct'));
  assert.match(html,/原表注明3月扣回，是否已结清？/);
  assert.match(html,/结算结果待核实/);
  assert.match(html,/保留历史金额/);
  assert.match(html,/登记补发／扣回/);
  const amounts=html.match(/<table class="rs-history-amounts">[\s\S]*?<\/table>/)[0];
  assert.match(amounts,/差额参考/);
  assert.doesNotMatch(amounts,/扣回|补发/);
  assert.doesNotMatch(html,/按当前规则补扣|认可历史安排|均不证明实际支付或扣回执行/);
  assert.equal(page.requests.length,1);
});


test('missing historical payee remains blank in the original form', async()=>{
  const missing={...recovery,recipientId:'',recipientName:''};
  const page=surface(missing);
  await page.window.RecruitmentSpecial.open('row',{type:'adjustment',kind:'recruitment',recovery:missing});
  assert.equal(page.elements.get('rsName').value,'');
  assert.equal(page.elements.get('rsEmployee').value,'');
  assert.equal(page.elements.get('rsAmount').value,'');
});

test('a fully arranged historical difference keeps its record and disables another correction', async()=>{
  const page=surface({...recovery,resolution:'adjusted'});
  await page.window.RecruitmentSpecial.review({rowIds:['row']});
  const html=page.elements.get('draftInspectorBody').innerHTML;
  assert.match(html,/已有足额补扣安排/);
  assert.match(html,/data-rs-correct="historical" disabled/);
  assert.doesNotMatch(html,/data-rs-retain/);
});

test('retaining history previews closure without claiming payment or creating a correction',async()=>{
  const page=surface(recovery);
  await page.window.RecruitmentSpecial.review({rowIds:['row']});
  await page.elements.get('retain:historical').onclick();
  const html=page.elements.get('rsHistoryPreview').innerHTML;
  assert.match(html,/保存并关闭差异/);
  assert.match(html,/本月金额<\/dt><dd>不变/);
  assert.match(html,/支付／扣回结果<\/dt><dd>仍未核实/);
  assert.equal(page.requests.filter(r=>r.options?.method==='POST').length,1);
  const payload=JSON.parse(page.requests.at(-1).options.body);
  assert.equal(payload.type,'history');assert.equal(payload.outcome,'retain');
  assert.equal(payload.amount,undefined);
  assert.doesNotMatch(page.requests.at(-1).url,/apply/);
});

test('existing correction records are shown once and unlinked records remain unconfirmed',async()=>{
  const arranged={adjustmentId:'correction',amount:-10,currency:'美元',recipientName:'原领取人',scheduledMonth:202603};
  const page=surface({...recovery,relatedRecords:[{...arranged,id:'correction',month:202603,active:true,sourceValid:true,issues:[],relationship:'linked'}],
    confirmedCorrections:[arranged],relatedConfirmedArrangements:[arranged,{...arranged,adjustmentId:'candidate',amount:-5}]});
  await page.window.RecruitmentSpecial.review({rowIds:['row']});
  const html=page.elements.get('draftInspectorBody').innerHTML;
  assert.equal(html.match(/扣回 10 美元/g).length,1);
  assert.match(html,/待匹配分期/);
  assert.match(html,/2026年3月/);
  assert.doesNotMatch(html,/未关联到补扣记录/);
});

test('duplicate notes keep all original references and an unknown difference stays unknown',async()=>{
  const page=surface({...recovery,type:'opening_conflict',signedAmount:null,recipientId:'',recipientName:'',originalNotes:[
    {text:'原记录待核对',sourceRef:{sourceId:'original',row:12}},
    {text:'原记录待核对',sourceRef:[{sourceId:'second',row:13}]}]});
  await page.window.RecruitmentSpecial.review({rowIds:['row']});
  const html=page.elements.get('draftInspectorBody').innerHTML;
  assert.equal(html.match(/原记录待核对/g).length,1);
  assert.match(html,/sources\/original/);assert.match(html,/sources\/second/);
  assert.match(html,/差额参考<\/th>[\s\S]*?<td>待核对<\/td>/);
  assert.match(html,/data-rs-correct="historical" disabled/);
  assert.doesNotMatch(html,/已结清<\/span>/);
});
