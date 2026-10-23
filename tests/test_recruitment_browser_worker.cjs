const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const os=require('node:os');
const path=require('node:path');
const {pathToFileURL}=require('node:url');
const modulePromise=import(pathToFileURL(path.resolve(__dirname,'../scripts/recruitment_browser_worker.mjs')));

async function polling(responses){
  const {run}=await modulePromise,dir=await fs.mkdtemp(path.join(os.tmpdir(),'recruitment-worker-'));
  const stop=path.join(dir,'stop'),saved={taskSpace:global.taskSpace,setTimeout:global.setTimeout};let calls=0;
  global.taskSpace=async()=>({page:()=>({url:async()=> 'https://hras-ai-vc.ztn.cn/',fetch:async()=>{
    const result=responses[calls++];if(result instanceof Error)throw result;
    if(calls===responses.length)await fs.writeFile(stop,'');return {status:result,body:'{"job":null}'};
  }})});
  global.setTimeout=callback=>saved.setTimeout(callback,0);
  try{await run({spaceId:4,controlPage:'p2',stopFile:stop});return calls;}
  finally{global.taskSpace=saved.taskSpace;global.setTimeout=saved.setTimeout;await fs.rm(dir,{recursive:true,force:true});}
}

test('polling resumes after rolling deployment gateway failures',async()=>{
  assert.equal(await polling([502,503,200]),3);
});

test('expired login and released browser control stop without retry',async()=>{
  assert.equal(await polling([401,200]),1);
  assert.equal(await polling([Object.assign(Error('control released'),{code:'EGO_TASK_SPACE_NOT_ACTIVE'}),200]),1);
});
