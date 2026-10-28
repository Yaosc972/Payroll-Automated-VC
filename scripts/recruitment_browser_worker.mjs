/* Run through ego-browser nodejs. No listener, application secret or saved Cookie. */
import {collect} from '../bonus_platform/engine/recruitment_overseas_browser.mjs';
import https from 'node:https';
import fs from 'node:fs/promises';

export async function run({spaceId,controlPage,stopFile,gateway,targetUrl}){
  const task=await taskSpace(spaceId),page=task.page(controlPage);
  const current=new URL(await page.url());
  const target=new URL(targetUrl||current.origin);
  if(target.protocol!=='https:'||current.protocol!=='https:')throw Error('HTTPS_REQUIRED');
  const stopped=async()=>{if(!stopFile)return false;try{await fs.access(stopFile);return true;}catch(e){if(e.code==='ENOENT')return false;throw e;}};
  async function post(path,body={}){
    if(!path.startsWith('/api/recruitment/browser-worker/'))throw Error('INVALID_WORKER_PATH');
    if(!gateway){
      if(target.origin!==current.origin)throw Error('SAME_ORIGIN_REQUIRED');
      const result=await page.fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),timeout:30000});
      if(result.status!==200)throw Object.assign(Error('WORKER_HTTP_'+result.status),{status:result.status});
      return JSON.parse(result.body);
    }
    // Preview has a certificate-name mismatch. Use the platform's TLS-verified
    // gateway with this application's preview Host, as in existing release checks.
    const gate=new URL(gateway);
    if(gate.protocol!=='https:'||gate.hostname!=='hras-aideploy.ztn.cn'
       ||target.hostname!=='42141ddcae8f.pre-hras-aideploy.ztn.cn'||current.hostname!=='hras-ai-vc.ztn.cn')throw Error('INVALID_PREVIEW_GATEWAY');
    const result=await page.cdp('Network.getCookies',{urls:[current.origin]});
    const cookie=result.cookies.filter(c=>c.name==='sigma_session').map(c=>c.name+'='+c.value).join('; ');
    if(!cookie)throw Error('WORKER_LOGIN_REQUIRED');
    const content=JSON.stringify(body);
    return new Promise((resolve,reject)=>{
      const request=https.request({hostname:gate.hostname,servername:gate.hostname,port:gate.port||443,
        path:target.pathname.replace(/\/$/,'')+path,method:'POST',timeout:30000,
        headers:{Host:target.host,Cookie:cookie,Origin:target.origin,'Content-Type':'application/json','Content-Length':Buffer.byteLength(content)}},response=>{
        const chunks=[];let size=0;
        response.on('data',c=>{size+=c.length;if(size>40*1024*1024)response.destroy(Error('RESPONSE_TOO_LARGE'));else chunks.push(c);});
        response.on('end',()=>{if(response.statusCode!==200)return reject(Object.assign(Error('WORKER_HTTP_'+response.statusCode),{status:response.statusCode}));try{resolve(JSON.parse(Buffer.concat(chunks)));}catch{reject(Error('INVALID_WORKER_RESPONSE'));}});
        response.on('error',reject);
      });
      request.on('error',reject);request.on('timeout',()=>request.destroy(Error('WORKER_TIMEOUT')));request.end(content);
    });
  }
  console.log('RECRUITMENT_WORKER_READY');
  let disconnected=false;
  while(!await stopped()){
    let response;
    try{response=await post('/api/recruitment/browser-worker/claim');}
    catch(error){
      const network=['ECONNRESET','ECONNREFUSED','ETIMEDOUT','EHOSTUNREACH','ENOTFOUND','EAI_AGAIN','EPIPE'];
      const transient=error.status===429||error.status>=500||network.includes(error.code)||error.message==='WORKER_TIMEOUT';
      if(transient){
        if(!disconnected)console.log('RECRUITMENT_WORKER_WAITING:CONNECTION_UNAVAILABLE');
        disconnected=true;await new Promise(resolve=>setTimeout(resolve,5000));continue;
      }
      console.log('RECRUITMENT_WORKER_STOPPED:'+([401,403].includes(error.status)?'LOGIN_REQUIRED':'CONNECTION_UNAVAILABLE'));return;
    }
    if(disconnected){console.log('RECRUITMENT_WORKER_RECONNECTED');disconnected=false;}
    const job=response.job;
    if(!job){await new Promise(resolve=>setTimeout(resolve,5000));continue;}
    console.log('RECRUITMENT_JOB_STARTED:'+job.id);
    try{
      const snapshot=await collect({spaceId,keepSpace:true,month:job.month,jobNumbers:job.jobNumbers,offerCodes:job.offerCodes,
        employmentOnly:job.employmentOnly===true,offerOnly:job.offerOnly===true,
        cancelFile:stopFile,onProgress:message=>post(`/api/recruitment/browser-worker/${job.id}/progress`,{lease:job.lease,message})});
      await post(`/api/recruitment/browser-worker/${job.id}/complete`,{lease:job.lease,snapshot});
      console.log('RECRUITMENT_JOB_COMPLETED:'+job.id);
    }catch(error){
      const code=['LOGIN_REQUIRED','CONTROL_RELEASED','CANCELLED'].includes(error.code)?error.code:'QUERY_FAILED';
      try{await post(`/api/recruitment/browser-worker/${job.id}/fail`,{lease:job.lease,code});}catch{}
      console.log('RECRUITMENT_JOB_FAILED:'+code);
      if(code!=='QUERY_FAILED')return;
    }
  }
  console.log('RECRUITMENT_WORKER_STOPPED');
}
