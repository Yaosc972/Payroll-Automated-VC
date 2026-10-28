/* Read-only API transport in the user's existing Ego browser session. */
import {randomUUID} from 'node:crypto';
const ROSTER_URL='https://oehr.ztn.cn/oehr/personnel/employeeManagement/roster';
const OFFER_URL='https://hrms.ztn.cn/hc/recruitment/offer';
const SIZE=200;
const fail=code=>{throw Object.assign(new Error(code),{code});};
const number=value=>String(value||'').match(/\bzt\d+\b/i)?.[0].toLowerCase()||String(value||'').trim().toLowerCase();
const unique=values=>[...new Set(values.filter(Boolean))].sort();

export async function collectPages(fetchPage){
  const records=[];let total,pages;
  for(let page=1;page<=100;page++){
    const response=await fetchPage(page);
    if(!Number.isSafeInteger(response.total)||response.total<0||response.total>20000||response.current!==page||!Array.isArray(response.records))fail('INCOMPLETE_RESPONSE');
    const count=Math.max(1,Number(response.pages));
    if(!Number.isSafeInteger(count)||count>100)fail('INCOMPLETE_RESPONSE');
    if(page===1){total=response.total;pages=count;}
    if(response.total!==total||count!==pages)fail('CHANGED_DURING_QUERY');
    records.push(...response.records);
    if(page>=pages){if(records.length!==total)fail('INCOMPLETE_RESPONSE');return records;}
    if(!response.records.length)fail('INCOMPLETE_RESPONSE');
  }
  fail('SCOPE_TOO_LARGE');
}

export async function collect(options){
  const fs=await import('node:fs/promises');
  const month=options.month,year=Math.floor(month/100),m=month%100;
  if(!Number.isInteger(month)||year<2000||year>2099||m<1||m>12)fail('INVALID_MONTH');
  // Scheduled and activity syncs can overlap; page-side query state belongs to one capture.
  const task=await taskSpace(options.spaceId||`招聘奖金海外取数-${month}-${randomUUID()}`);
  const checkpoint=async()=>{if(options.cancelFile){try{await fs.access(options.cancelFile);fail('CANCELLED');}catch(e){if(e.code==='CANCELLED')throw e;if(e.code!=='ENOENT')throw e;}}};
  const progress=async message=>{
    if(options.progressFile)await fs.writeFile(options.progressFile,message,{mode:0o600});
    if(options.onProgress)await options.onProgress(message);
    console.log('OVERSEAS_PROGRESS:'+message);
  };
  try{
    const pages=await task.pages(),known=await Promise.all(pages.map(async page=>({page,url:await page.url()})));
    let roster=known.find(p=>p.url.startsWith('https://oehr.ztn.cn/oehr/'))?.page;
    if(!roster){roster=known.find(p=>['about:blank','chrome://new-tab-page/'].includes(p.url))?.page||await task.newPage();await roster.goto(ROSTER_URL);}
    if((await roster.url())!==ROSTER_URL)await roster.goto(ROSTER_URL);
    await roster.waitForFunction(()=>[...document.querySelectorAll('*')].some(e=>e.__vue__?.$options?.name==='personnelRosterPage'),undefined,{timeout:20000});
    await checkpoint();
    async function rosterPage(data,pageNum){
      await checkpoint();
      await roster.evaluate(({data,pageNum,pageSize})=>{
        const v=[...document.querySelectorAll('*')].map(e=>e.__vue__).find(v=>v?.$options?.name==='personnelRosterPage');
        const job=window.__recruitmentOverseasRoster={status:'running'};
        if(!v?.$api?.personnel?.queryRosterList){job.status='error';job.error='LOGIN_REQUIRED';return;}
        const customFieldSet=Object.entries(data).map(([fieldCode,fieldValue])=>({fieldCode,fieldName:fieldCode,
          fieldColumn:'',condition:fieldCode==='entryDate'?'between':Array.isArray(fieldValue)?'in':'eq',
          dataFormat:fieldCode==='entryDate'?'1':'3',format:fieldCode==='entryDate'?'YYYY/MM/DD':null,fieldValue,tableAlias:''}));
        v.$api.personnel.queryRosterList({data:{personnelStatusSet:[],...data,customFieldSet},pageNum,pageSize}).then(response=>{
          if(response?.code!==200){job.status='error';job.error=[401,403].includes(response?.code)?'LOGIN_REQUIRED':'QUERY_FAILED';return;}
          const p=response.data;
          if(!p||!Array.isArray(p.records)){job.status='error';job.error='INCOMPLETE_RESPONSE';return;}
          const table=v.$children.find(c=>c.$options.name==='TableDynamic'),slot=table?.$scopedSlots?.['employmentInfo.employeeStatus'];
          const texts=x=>Array.isArray(x)?x.map(texts).join(''):x?(x.text||'')+texts(x.children):'';
          const day=x=>String(x||'').replaceAll('/','-').slice(0,10);
          const rows=p.records.map(row=>{const e=row.employeeInfo||{},j=row.employmentInfo||{},restricted=row.needAnonymizedFieldSet||[];
            const decoded=key=>restricted.includes(key)?'':String(v.$cnan.decrypt(e[key])||'').trim();
            return {'姓名':e.fullName||j.empName||'','工号':e.empNo||j.empNo||'','证件号码':decoded('idNumber'),
              'offer流程编号':decoded('offerProcessNumber'),'入职日期':day(j.entryDateStr),
              '人员状态':slot?texts(slot({text:j.employeeStatus,record:row})).trim():'',
              '离职日期':day(j.leaveDateStr),'办公地址':j.workPlaceAreaName||'','职级':j.jobLevelName||'',
              '职位':j.positionName||'','二级部门':j.secondOrgName||'','三级部门':j.thirdOrgName||'',
              '四级部门':j.fourthOrgName||'','五级部门':j.fifthOrgName||'','直接上级':j.lineManagerName||'',
              '直接上级工号':j.lineManagerNameCode||j.lineManagerNo||'','人员来源':row.staffSource||'',
              '是否虚拟员工':e.virtualEmployee==='0'?'否':e.virtualEmployee==='1'?'是':''};});
          job.data={records:rows,total:p.total,current:p.current,pages:p.pages,size:p.size};job.status='done';
        }).catch(()=>{job.status='error';job.error='QUERY_FAILED';});
      },{data,pageNum,pageSize:SIZE});
      await roster.waitForFunction(()=>window.__recruitmentOverseasRoster?.status!=='running',undefined,{timeout:20000});
      const result=await roster.evaluate(()=>window.__recruitmentOverseasRoster);
      if(result.status!=='done')fail(result.error||'QUERY_FAILED');
      return result.data;
    }
    const rosterQuery=data=>collectPages(page=>rosterPage(data,page));
    const mm=String(m).padStart(2,'0'),last=new Date(Date.UTC(year,m,0)).getUTCDate();
    const monthly=options.employmentOnly||options.offerOnly?[]:await rosterQuery({entryDate:[`${year}/${mm}/01`,`${year}/${mm}/${last}`],staffSource:'0'});
    if(monthly.some(r=>!r['入职日期'].startsWith(`${year}-${mm}`)||r['人员来源']!=='OEHR入职'))fail('WRONG_QUERY_SCOPE');
    if(!options.employmentOnly&&!options.offerOnly)await progress(`已取得 ${monthly.length} 条本月海外花名册，正在关联 Offer`);
    const records=new Map();
    function merge(items,scope){for(const data of items){const key=number(data['工号'])+'|'+data['入职日期'];const old=records.get(key);
      if(old&&JSON.stringify(old.data)!==JSON.stringify(data))fail('CHANGED_DURING_QUERY');
      if(!old)records.set(key,{scope,data});}}
    merge(monthly,'month');
    const requested=unique((options.jobNumbers||[]).map(number));
    async function lookup(numbers){
      const existing=new Set([...records.values()].map(r=>number(r.data['工号']))),needed=numbers.filter(n=>!existing.has(n));
      for(let i=0;i<needed.length;i+=100){const batch=needed.slice(i,i+100),rows=await rosterQuery({empNo:batch});
        if(rows.some(r=>!batch.includes(number(r['工号']))))fail('WRONG_QUERY_SCOPE');merge(rows,'lookup');
        await progress(`已取得 ${records.size} 条海外人员任职资料`);}
    }
    await lookup(requested);
    const codes=unique([...(options.offerCodes||[]).map(x=>String(x).toLowerCase()),...monthly.filter(r=>r['是否虚拟员工']!=='是').map(r=>r['offer流程编号'].toLowerCase())]);
    if(codes.length>5000||requested.length>5000)fail('SCOPE_TOO_LARGE');
    let offer=known.find(p=>p.url.startsWith('https://hrms.ztn.cn/hc/'))?.page;
    if(codes.length&&!offer){offer=await task.newPage();await offer.goto(OFFER_URL);}
    if(codes.length){
      if((await offer.url())!==OFFER_URL)await offer.goto(OFFER_URL);
      await offer.waitForFunction(()=>[...document.querySelectorAll('button')].some(b=>b.innerText.trim()==='查询'&&b.getBoundingClientRect().width>0),undefined,{timeout:20000});
      await offer.evaluate(()=>{
        const state=window.__recruitmentOverseasOffer={status:'waiting'};
        const open=XMLHttpRequest.prototype.open,header=XMLHttpRequest.prototype.setRequestHeader,send=XMLHttpRequest.prototype.send;
        XMLHttpRequest.prototype.open=function(method,url,...rest){this.__overseas={method,url,headers:{}};return open.call(this,method,url,...rest);};
        XMLHttpRequest.prototype.setRequestHeader=function(k,v){if(this.__overseas)this.__overseas.headers[k]=v;return header.call(this,k,v);};
        XMLHttpRequest.prototype.send=function(body){const request=this.__overseas;
          if(request&&new URL(request.url,location.href).pathname==='/api/hc/offer/pageList'){
            this.addEventListener('loadend',()=>{try{const response=JSON.parse(this.responseText);state.request={headers:request.headers,body:JSON.parse(body)};state.status=this.status===200&&response.code===200?'ready':'error';}catch{state.status='error';}});
            XMLHttpRequest.prototype.open=open;XMLHttpRequest.prototype.setRequestHeader=header;XMLHttpRequest.prototype.send=send;
          }return send.call(this,body);};
        const buttons=[...document.querySelectorAll('button')].filter(b=>b.innerText.trim()==='查询'&&b.getBoundingClientRect().width>0);
        if(buttons.length!==1){state.status='error';return;}buttons[0].click();
      });
      await offer.waitForFunction(()=>window.__recruitmentOverseasOffer?.status!=='waiting',undefined,{timeout:20000});
      if(!await offer.evaluate(()=>window.__recruitmentOverseasOffer.status==='ready'))fail('LOGIN_REQUIRED');
    }
    const offers=[],missing=[];
    for(let offset=0;offset<codes.length;offset+=20){
      await checkpoint();
      await offer.evaluate(codes=>{
        const state=window.__recruitmentOverseasOffer,request=state.request;
        const job=window.__recruitmentOverseasOfferBatch={status:'running',records:[],missing:[]};let next=0;
        const map={'姓名':'fullName','offer编码':'offerCode','状态':'offerStatusName','编制ABC分类':'abcClassificationName',
          '招聘负责人':'recruitmentEmpName','招聘负责人工号':'recruitmentEmpNo','协助招聘负责人姓名':'assistRecruitmentName',
          '协助招聘负责人工号':'assistRecruitmentEmpNo','招聘渠道':'recruitmentChannelName','其他渠道':'otherChannel',
          '招聘启动日期':'recruitmentStartDateStr','招聘需求编码':'recruitmentRequirementCode','内推人姓名':'internalReferrerEmpName','内推人工号':'internalReferrerEmpNo'};
        async function worker(){while(next<codes.length){const code=codes[next++],body=JSON.parse(JSON.stringify(request.body));body.pageNum=1;body.pageSize=200;body.data.offerCode=code;
          body.data.customFieldSet=(body.data.customFieldSet||[]).map(f=>f.fieldCode==='offerCode'?{...f,fieldValue:code}:f);
          const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),15000);
          try{const response=await fetch('/api/hc/offer/pageList',{method:'POST',headers:request.headers,body:JSON.stringify(body),signal:controller.signal});const data=await response.json();
            if(response.status!==200||data.code!==200)throw Error([401,403].includes(response.status)||[401,403].includes(data.code)?'LOGIN_REQUIRED':'QUERY_FAILED');
            const rows=data.data?.records;
            if(!Array.isArray(rows)||rows.length!==data.data.total)throw Error('INCOMPLETE_RESPONSE');
            const exact=rows.filter(r=>String(r.offerCode).toLowerCase()===code);
            if(exact.length>1)throw Error('AMBIGUOUS_OFFER');
            if(!exact.length){job.missing.push(code);continue;}
            job.records.push(Object.fromEntries(Object.entries(map).map(([k,f])=>[k,exact[0][f]??''])));
          }finally{clearTimeout(timer);}}}
        Promise.all([worker(),worker(),worker()]).then(()=>{job.status='done';}).catch(e=>{job.status='error';job.error=e.message;});
      },codes.slice(offset,offset+20));
      await offer.waitForFunction(()=>window.__recruitmentOverseasOfferBatch?.status!=='running',undefined,{timeout:20000});
      const result=await offer.evaluate(()=>window.__recruitmentOverseasOfferBatch);
      if(result.status!=='done')fail(result.error||'QUERY_FAILED');
      offers.push(...result.records);missing.push(...result.missing);
      await progress(`海外 Offer 已核对 ${Math.min(offset+20,codes.length)} / ${codes.length} 份`);
    }
    const recipients=unique(offers.flatMap(o=>['招聘负责人工号','协助招聘负责人工号','内推人工号'].map(k=>number(o[k]))));
    await lookup(recipients);await checkpoint();
    const historyNumbers=unique([...records.values()].filter(r=>(r.data['人员来源']==='OEHR入职'
      ||options.employmentOnly&&r.scope==='lookup'&&r.data['人员来源']==='人员迁移')
      &&r.data['是否虚拟员工']!=='是'&&(r.scope==='lookup'||r.data['offer流程编号'])).map(r=>number(r.data['工号'])));
    const employmentHistory=[];
    for(let offset=0;offset<historyNumbers.length;offset+=12){
      await checkpoint();
      await roster.evaluate(numbers=>{
        const v=[...document.querySelectorAll('*')].map(e=>e.__vue__).find(v=>v?.$options?.name==='personnelRosterPage');
        const job=window.__recruitmentEmploymentHistory={status:'running',records:[]};let next=0;
        const fields=['empNo','employeeInfoId','infoId','recordId','startDate','endDate','entryDate','lastWorkDay',
          'employmentType','employmentStatus','employeeStatus','businessType','businessTypeName','deptCode','deptName',
          'positionCode','positionName','jobLevelCode','jobLevelName','lineManagerNo','lineManagerName','workPlaceAreaId','workPlacePathName','orgPathName'];
        async function query(empNo){for(let attempt=0;attempt<3;attempt++){let timer;
          try{const result=await Promise.race([v.$api.personnel.employmentRecordData({empNo,queryType:'rosterAuth'}),
            new Promise((_,reject)=>{timer=setTimeout(()=>reject(Object.assign(Error('QUERY_TIMEOUT'),{code:'ETIMEDOUT'})),15000);})]);
            if([401,403].includes(result?.code))throw Error('LOGIN_REQUIRED');
            if([408,429].includes(result?.code)||result?.code>=500&&result?.code<=599)throw Object.assign(Error('QUERY_FAILED'),{retryable:true});
            if(result?.code!==200||!Array.isArray(result.data)||result.data.some(h=>!h||typeof h!=='object'||Array.isArray(h)))throw Error('INCOMPLETE_RESPONSE');
            if(result.data.some(h=>String(h.empNo).toLowerCase()!==empNo))throw Error('WRONG_QUERY_SCOPE');
            return {empNo,records:result.data.map(h=>({...Object.fromEntries(fields.map(f=>[f,h[f]??''])),
              lineManagerProvided:Object.hasOwn(h,'lineManagerNo')?'1':'0'}))};
          }catch(error){
            const status=Number(error.response?.status||error.status||0);
            if([401,403].includes(status))throw Error('LOGIN_REQUIRED');
            const transient=error.retryable||[408,429].includes(status)||status>=500&&status<=599
              ||['ERR_NETWORK','ECONNABORTED','ETIMEDOUT','ECONNRESET','ENETUNREACH'].includes(error.code)
              ||/network error|failed to fetch|load failed|timed? ?out/i.test(error.message||'');
            if(!transient)throw error;
            if(attempt===2)throw Error('QUERY_FAILED');
          }finally{clearTimeout(timer);}}
        }
        async function worker(){while(next<numbers.length&&job.status==='running'){
          job.records.push(await query(numbers[next++]));}
        }
        if(!v?.$api?.personnel?.employmentRecordData){job.status='error';job.error='LOGIN_REQUIRED';return;}
        Promise.all([worker(),worker(),worker(),worker()]).then(()=>{job.status='done';}).catch(e=>{job.status='error';job.error=e.message;});
      },historyNumbers.slice(offset,offset+12));
      await roster.waitForFunction(()=>window.__recruitmentEmploymentHistory?.status!=='running',undefined,{timeout:145000});
      const result=await roster.evaluate(()=>window.__recruitmentEmploymentHistory);
      if(result.status!=='done')fail(result.error||'QUERY_FAILED');
      employmentHistory.push(...result.records);
      await progress(`海外任职记录已核对 ${Math.min(offset+12,historyNumbers.length)} / ${historyNumbers.length} 人`);
    }
    await checkpoint();
    const payload={version:1,month,queriedAt:new Date().toISOString(),requestedJobNumbers:requested,
      requestedOfferCodes:unique(options.offerCodes||[]),roster:[...records.values()],offers,missingOfferCodes:unique(missing),employmentHistory};
    if(options.employmentOnly){payload.employmentOnly=true;payload.employmentHistoryScope='oehr_and_migrated';}
    if(options.offerOnly)payload.offerOnly=true;
    if(!options.keepSpace)await task.finish({keep:[]});
    return payload;
  }catch(error){
    if(error.code==='CANCELLED'&&!options.keepSpace)await task.finish({keep:[]});
    const message=String(error.message||'');
    if(/inactive|unassigned|user.*control|EGO.*CONTROL/i.test(message))fail('CONTROL_RELEASED');
    if(/waitForFunction timed out/.test(message))fail('LOGIN_REQUIRED');
    throw error;
  }
}

export async function run(options){
  try{
    const payload=await collect(options);
    if(options.resultFile){const fs=await import('node:fs/promises');await fs.writeFile(options.resultFile,JSON.stringify(payload),{mode:0o600});console.log('OVERSEAS_SNAPSHOT:ok');}
    else console.log('OVERSEAS_SNAPSHOT:'+JSON.stringify(payload));
  }
  catch(error){console.log('OVERSEAS_ERROR:'+(error.code||'QUERY_FAILED'));process.exitCode=1;}
}
