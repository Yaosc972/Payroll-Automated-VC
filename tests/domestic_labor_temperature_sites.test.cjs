const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('bonus_platform/static/domestic-labor.js', 'utf8');
const helper = source.slice(source.indexOf('async function submitPayrollWithTemperatureSiteConfirmation('), source.indexOf('async function submitPayrollWithRosterConfirmation('));
const gate = retryCompletion => Object.assign(new Error('name confirmation'), {detail:{code:'temperature_site_confirmation_required'}, retryCompletion});

test('direct confirmation reuses completion and preserves mappings across retries', async () => {
  let uploads = 0, completions = 0;
  const seen = [];
  const mappings = [{aliasA:'siteA'}, {aliasB:'siteB'}];
  const complete = async updates => {
    seen.push(updates.temperatureSiteMapping);
    if (++completions === 1) throw gate(complete);
    return {status:'已完成'};
  };
  const context = vm.createContext({
    submitDomesticLaborRun: async () => { uploads++; throw gate(complete); },
    confirmTemperatureSiteMapping: async () => mappings.shift(), el:{}, setText:()=>{},
  });
  vm.runInContext(helper, context);
  const result = await context.submitPayrollWithTemperatureSiteConfirmation({});
  assert.equal(result.status, '已完成');
  assert.equal(uploads, 1);
  assert.equal(completions, 2);
  assert.deepEqual(JSON.parse(JSON.stringify(seen[1])), {aliasA:'siteA',aliasB:'siteB'});
});

test('multipart retry passes the confirmed mapping to the upload request', async () => {
  let attempts = 0;
  const context = vm.createContext({
    submitDomesticLaborRun: async options => { if (++attempts === 1) throw gate(); return options.temperatureSiteMapping; },
    confirmTemperatureSiteMapping: async () => ({alias:'site'}), el:{}, setText:()=>{},
  });
  vm.runInContext(helper, context);
  assert.deepEqual(JSON.parse(JSON.stringify(await context.submitPayrollWithTemperatureSiteConfirmation({}))), {alias:'site'});
  assert.equal(attempts, 2);
});

test('cancel returns to upload without triggering another calculation', async () => {
  let attempts = 0;
  const context = vm.createContext({submitDomesticLaborRun:async()=>{attempts++;throw gate();}, confirmTemperatureSiteMapping:async()=>null,el:{},setText:()=>{}});
  vm.runInContext(helper, context);
  assert.equal(await context.submitPayrollWithTemperatureSiteConfirmation({}), null);
  assert.equal(attempts, 1);
});

test('other validation errors keep their existing handling', async () => {
  const error = new Error('workbook invalid');
  const context = vm.createContext({submitDomesticLaborRun:async()=>{throw error;}});
  vm.runInContext(helper, context);
  await assert.rejects(context.submitPayrollWithTemperatureSiteConfirmation({}), value=>value===error);
});

test('direct completion retains prior confirmations through another validation gate', async () => {
  let calls = 0, uploads = 0;
  const bodies = [];
  const context = vm.createContext({state:{},
    updateUploadProgress:()=>{},uploadDomesticFilesConcurrently:async()=>{uploads++;},
    requestJson:async(url,options)=>{
      if(url.endsWith('direct-upload-plan')) return {runId:'same-run',uploads:[{}]};
      bodies.push(JSON.parse(options.body));
      if(++calls<=2) throw gate();
      return {status:'已完成'};
    },
  });
  const start = source.indexOf('async function submitDomesticLaborRunDirect(');
  vm.runInContext(source.slice(start,source.indexOf('async function uploadDomesticFilesConcurrently(',start)),context);
  let first;
  try { await context.submitDomesticLaborRunDirect({files:[{name:'test.xlsx'}]}); } catch(error) { first=error; }
  let second;
  try { await first.retryCompletion({temperatureSiteMapping:{alias:'site'}}); } catch(error) { second=error; }
  await second.retryCompletion({jinjiangRosterDecision:'confirmed'});
  assert.equal(uploads,1);
  assert.deepEqual(bodies[2].temperatureSiteMapping,{alias:'site'});
  assert.equal(bodies[2].jinjiangRosterDecision,'confirmed');
});

test('site alias confirmation followed by empty roster confirmation keeps the same direct upload', async () => {
  let uploads=0, calls=0;
  const bodies=[];
  const context=vm.createContext({state:{},el:{},setText:()=>{},updateUploadProgress:()=>{},
    uploadDomesticFilesConcurrently:async()=>{uploads++;},
    confirmTemperatureSiteMapping:async()=>({alias:'site'}),
    confirmEmptySupplementalSheets:async()=>({temperature_exclusions:'none'}),
    requestJson:async(url,options)=>{
      if(url.endsWith('direct-upload-plan')) return {runId:'same-run',uploads:[{}]};
      bodies.push(JSON.parse(options.body));
      if(++calls===1)throw gate();
      if(calls===2)throw Object.assign(new Error('empty roster'),{detail:{code:'supplemental_empty_confirmation_required',sheets:[]}});
      return {status:'已完成'};
    },
  });
  vm.runInContext(helper,context);
  const start=source.indexOf('async function submitDomesticLaborRunDirect(');
  vm.runInContext(source.slice(start,source.indexOf('async function uploadDomesticFilesConcurrently(',start)),context);
  context.submitDomesticLaborRun=options=>context.submitDomesticLaborRunDirect({...options,files:[{name:'test.xlsx'}]});
  const result=await context.submitPayrollWithTemperatureSiteConfirmation({});
  assert.equal(result.status,'已完成');
  assert.equal(uploads,1);
  assert.deepEqual(bodies[2].temperatureSiteMapping,{alias:'site'});
  assert.deepEqual(bodies[2].supplementalConfirmation,{temperature_exclusions:'none'});
});
