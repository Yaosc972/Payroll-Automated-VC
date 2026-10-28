const test=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
const {pathToFileURL}=require('node:url');
const modulePromise=import(pathToFileURL(path.resolve(__dirname,'../bonus_platform/engine/recruitment_overseas_browser.mjs')));

test('overseas roster collects every page and accepts an explicitly empty month',async()=>{
  const {collectPages}=await modulePromise;
  const requested=[];
  const rows=await collectPages(async page=>{requested.push(page);return {current:page,pages:2,total:3,records:page===1?['a','b']:['c']};});
  assert.deepEqual(requested,[1,2]);assert.deepEqual(rows,['a','b','c']);
  assert.deepEqual(await collectPages(async()=>({current:1,pages:0,total:0,records:[]})),[]);
});

test('partial results, changing totals, unbounded scope and wrong page numbers cannot become snapshots',async()=>{
  const {collectPages}=await modulePromise;
  for(const response of [
    {current:1,pages:1,total:2,records:['only-one']},
    {current:1,pages:2,total:2,records:[]},
    {current:2,pages:1,total:1,records:['wrong-page']},
    {current:1,pages:1,total:20001,records:[]},
    {current:1,pages:'unknown',total:1,records:['x']},
  ])await assert.rejects(collectPages(async()=>response));
  await assert.rejects(collectPages(async page=>({current:page,pages:2,total:page===1?2:3,records:['x']})),/CHANGED_DURING_QUERY/);
});

async function collectWithHistory(numbers,query,{fastTimeout=false,employmentOnly=false,staffSource='OEHR入职'}={}){
  const {collect}=await modulePromise;
  const saved={taskSpace:global.taskSpace,document:global.document,window:global.window,setTimeout:global.setTimeout};
  const requested=[],rosterQueries=[];
  const v={$options:{name:'personnelRosterPage'},$children:[],$cnan:{decrypt:x=>x},$api:{personnel:{
    queryRosterList:async({data,pageNum})=>{
      rosterQueries.push(data);
      const records=(data.empNo||[]).map(empNo=>({staffSource,
        employeeInfo:{empNo,fullName:empNo,virtualEmployee:'0'},
        employmentInfo:{entryDateStr:'2026/07/01'}}));
      return {code:200,data:{records,total:records.length,current:pageNum,pages:1}};
    },
    employmentRecordData:async args=>{requested.push(args);return query(args);},
  }}};
  const page={url:async()=> 'https://oehr.ztn.cn/oehr/personnel/employeeManagement/roster',
    evaluate:async(fn,arg)=>fn(arg),
    waitForFunction:async fn=>{for(let i=0;i<5000;i++){if(fn())return;await new Promise(setImmediate);}throw Error('fake wait deadline');},
  };
  global.document={querySelectorAll:()=>[{__vue__:v}]};
  global.window={};
  global.taskSpace=async()=>({pages:async()=>[page],finish:async()=>{}});
  if(fastTimeout)global.setTimeout=(fn,ms,...args)=>saved.setTimeout(fn,ms===15000?1:ms,...args);
  try{return {payload:await collect({month:202608,spaceId:1,keepSpace:true,jobNumbers:numbers,employmentOnly}),requested,rosterQueries};}
  finally{for(const [key,value] of Object.entries(saved)){if(value===undefined)delete global[key];else global[key]=value;}}
}

const historyResult=empNo=>({code:200,data:[{empNo,recordId:'history-'+empNo,entryDate:'2026/07/01',
  startDate:'2026/07/01',endDate:'9999/12/31',employmentType:'0',employmentStatus:'0'}]});

test('recipient employment lookup skips monthly hires and Offer queries',async()=>{
  const {payload,rosterQueries}=await collectWithHistory(['zt2'],async({empNo})=>historyResult(empNo),{employmentOnly:true});
  assert.equal(rosterQueries.length,1);
  assert.deepEqual(rosterQueries[0].empNo,['zt2']);
  assert.equal(payload.employmentOnly,true);
  assert.ok(payload.roster.every(r=>r.scope==='lookup'));
  assert.deepEqual(payload.offers,[]);
  assert.deepEqual(payload.employmentHistory.map(h=>h.empNo),['zt2']);
});

test('targeted employment reads migrated people histories without importing them as monthly hires',async()=>{
  const {payload,requested}=await collectWithHistory(['zt2'],async({empNo})=>historyResult(empNo),
    {employmentOnly:true,staffSource:'人员迁移'});
  assert.deepEqual(requested.map(r=>r.empNo),['zt2']);
  assert.equal(payload.employmentHistoryScope,'oehr_and_migrated');
  assert.deepEqual(payload.employmentHistory.map(h=>h.empNo),['zt2']);
  assert.ok(payload.roster.every(r=>r.scope==='lookup'));
});

test('employment snapshots retain the dated organization path used to resolve country',async()=>{
  const orgPathName='纵腾网络/FBU仓储事业部/美洲区/加州区/洛杉矶25号仓/包装组';
  const {payload}=await collectWithHistory(['zt1'],async({empNo})=>{
    const response=historyResult(empNo);response.data[0].orgPathName=orgPathName;return response;
  },{employmentOnly:true});
  assert.equal(payload.employmentHistory[0].records[0].orgPathName,orgPathName);
});

test('overlapping captures for the same month keep their browser results separate',async()=>{
  const {collect}=await modulePromise;
  const vm=require('node:vm'),spaces=new Map(),saved=global.taskSpace;
  let firstStarted,releaseFirst;
  const started=new Promise(resolve=>{firstStarted=resolve;});
  const gate=new Promise(resolve=>{releaseFirst=resolve;});
  global.taskSpace=async name=>{
    if(spaces.has(name))return spaces.get(name);
    const v={$options:{name:'personnelRosterPage'},$children:[],$cnan:{decrypt:x=>x},$api:{personnel:{
      queryRosterList:async({data,pageNum})=>{
        const records=(data.empNo||[]).map(empNo=>({staffSource:'OEHR入职',
          employeeInfo:{empNo,virtualEmployee:'0'},employmentInfo:{entryDateStr:'2026/07/01'}}));
        return {code:200,data:{records,total:records.length,current:pageNum,pages:1}};
      },
      employmentRecordData:async({empNo})=>{
        if(empNo==='zt1'){firstStarted();await gate;}
        return historyResult(empNo);
      },
    }}};
    const context=vm.createContext({window:{},document:{querySelectorAll:()=>[{__vue__:v}]},setTimeout,clearTimeout});
    const page={url:async()=> 'https://oehr.ztn.cn/oehr/personnel/employeeManagement/roster',
      evaluate:async(fn,arg)=>{
        context.argument=arg;
        const value=await vm.runInContext(`(${fn.toString()})(argument)`,context);
        return value===undefined?undefined:JSON.parse(JSON.stringify(value));
      },
      waitForFunction:async fn=>{
        for(let i=0;i<5000;i++){
          if(vm.runInContext(`(${fn.toString()})()`,context))return;
          await new Promise(setImmediate);
        }
        throw Error('fake wait deadline');
      },
    };
    const task={pages:async()=>[page],finish:async()=>{}};
    spaces.set(name,task);return task;
  };
  let first;
  try{
    first=collect({month:202608,keepSpace:true,jobNumbers:['zt1']});
    await started;
    const second=await collect({month:202608,keepSpace:true,jobNumbers:['zt2']});
    releaseFirst();
    const original=await first;
    assert.deepEqual(original.employmentHistory.map(h=>h.empNo),['zt1']);
    assert.deepEqual(second.employmentHistory.map(h=>h.empNo),['zt2']);
  }finally{
    releaseFirst();if(first)await first.catch(()=>{});
    if(saved===undefined)delete global.taskSpace;else global.taskSpace=saved;
  }
});

test('a transient employment lookup rejection retries only that person and keeps all batches complete',async()=>{
  const numbers=Array.from({length:13},(_,i)=>'zt'+(i+1)),calls=new Map();
  const {payload,requested}=await collectWithHistory(numbers,async({empNo,queryType})=>{
    assert.equal(queryType,'rosterAuth');
    calls.set(empNo,(calls.get(empNo)||0)+1);
    if(empNo==='zt1'&&calls.get(empNo)===1)throw Object.assign(Error('Network Error'),{code:'ERR_NETWORK'});
    return historyResult(empNo);
  });
  assert.equal(requested.length,14);
  assert.equal(calls.get('zt1'),2);
  assert.deepEqual(payload.employmentHistory.map(h=>h.empNo).sort(),numbers.sort());
  assert.ok(payload.employmentHistory.every(h=>h.records.length===1&&h.records[0].empNo===h.empNo));
});

test('an individual request deadline retries without duplicating its history',async()=>{
  let calls=0;
  const {payload}=await collectWithHistory(['zt1'],async({empNo})=>{
    if(++calls===1)return new Promise(()=>{});
    return historyResult(empNo);
  },{fastTimeout:true});
  assert.equal(calls,2);
  assert.equal(payload.employmentHistory.length,1);
  assert.equal(payload.employmentHistory[0].records.length,1);
});

test('three transient lookup failures fail the entire capture instead of returning a partial snapshot',async()=>{
  const numbers=Array.from({length:13},(_,i)=>'zt'+(i+1)),calls=new Map();
  await assert.rejects(collectWithHistory(numbers,async({empNo})=>{
    calls.set(empNo,(calls.get(empNo)||0)+1);
    if(empNo==='zt1')throw Object.assign(Error('Network Error'),{code:'ERR_NETWORK'});
    return historyResult(empNo);
  }),/QUERY_FAILED/);
  assert.equal(calls.get('zt1'),3);
  assert.ok([...calls].some(([number])=>number!=='zt1'));
  assert.ok([...calls].every(([number,count])=>number==='zt1'||count===1));
});

test('authentication, incomplete records and wrong people fail immediately without retries',async()=>{
  for(const response of [{code:401},{code:403},{code:200,data:{}},{code:200,data:[null]},
    {code:200,data:[{empNo:'zt-other'}]}]){
    let calls=0;
    await assert.rejects(collectWithHistory(['zt1'],async()=>{calls++;return response;}),
      /LOGIN_REQUIRED|INCOMPLETE_RESPONSE|WRONG_QUERY_SCOPE/);
    assert.equal(calls,1);
  }
  let calls=0;
  await assert.rejects(collectWithHistory(['zt1'],async()=>{
    calls++;throw Object.assign(Error('Request failed'),{response:{status:403}});
  }),/LOGIN_REQUIRED/);
  assert.equal(calls,1);
});

test('a transient service response can recover but an ordinary business error is not retried',async()=>{
  let calls=0;
  const {payload}=await collectWithHistory(['zt1'],async({empNo})=>++calls===1?{code:503}:historyResult(empNo));
  assert.equal(calls,2);assert.equal(payload.employmentHistory.length,1);
  calls=0;
  await assert.rejects(collectWithHistory(['zt1'],async()=>{calls++;return {code:400};}),/INCOMPLETE_RESPONSE/);
  assert.equal(calls,1);
});
