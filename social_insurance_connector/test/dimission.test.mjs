import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { BeisenClient } from "../lib/beisen-client.mjs";
import { decideDimission } from "../lib/rules.mjs";

for (const scenario of JSON.parse(readFileSync(new URL('./fixtures/early-dimission.json', import.meta.url)))) {
  test(`early resignation: ${scenario.name}`, () => {
    const records = [{lastWorkDate:scenario.last, voluntaryStopFlag:scenario.flag,
      processTimeReliable:false, source:'beisen-dimission-record'}];
    if (scenario.extraFlag) records.push({...records[0],voluntaryStopFlag:scenario.extraFlag});
    const actual = decideDimission(records, `${scenario.cutoff ?? '2026-09-30'}T23:59:59+08:00`, scenario.entry);
    assert.equal(actual.decision, {include:'增员',exclude:'排除',review:'待人工确认'}[scenario.expected]);
  });
}

test("departure query explicitly requests all approval states and batches candidate IDs", async () => {
  process.env.BEISEN_APP_KEY = "test";
  process.env.BEISEN_APP_SECRET = "test";
  const calls = [];
  const client = new BeisenClient({fetchImpl: async (url, options) => {
    const body = JSON.parse(options.body);
    if (url.endsWith('/token')) return Response.json({access_token:'test'});
    calls.push(body);
    assert.ok(url.endsWith('/Employee/GetServiceInfoByIds'));
    assert.deepEqual(body.approvalStatus, ["Draft", "Approving", "Success", "Refused", "Effective", "Invalid", "Rejected", "Temporary"]);
    assert.equal(body.option, "None");
    return Response.json({code:'200', data: [
      {userID:body.oIds[0],businessTypeOID:'1'},
      {userID:body.oIds[0],businessTypeOID:'5',approvalStatus:1},
      {userID:body.oIds[0],businessTypeOID:'5',stdIsDeleted:true},
    ]});
  }});
  const result = await client.getDimissionRecords(Array.from({length:301},(_,i)=>i+1));
  assert.equal(calls.length, 2);
  assert.equal(calls[0].oIds.length, 300);
  assert.equal(result.length, 2);
  assert.equal(result[0].approvalStatus, 1);
});

test("malformed departure query fails closed", async () => {
  process.env.BEISEN_APP_KEY = "test";
  process.env.BEISEN_APP_SECRET = "test";
  const client = new BeisenClient({fetchImpl: async (url) => Response.json(
    url.endsWith('/token') ? {access_token:'test'} : {code:'200',data:null})});
  await assert.rejects(client.getDimissionRecords([1]), {code:'BEISEN_DIMISSION_INVALID'});
});

test("a known employee with missing business type is retained for review rather than aborting all candidates", async () => {
  process.env.BEISEN_APP_KEY = "test";
  process.env.BEISEN_APP_SECRET = "test";
  const client = new BeisenClient({fetchImpl: async (url) => Response.json(
    url.endsWith('/token') ? {access_token:'test'} : {code:'200',data:[
      {userID:1,businessTypeOID:null,approvalStatus:4,lastWorkDate:null},
      {userID:2,businessTypeOID:'5',approvalStatus:1},
    ]})});
  const rows = await client.getDimissionRecords([1,2]);
  assert.equal(rows.length,2);
  assert.equal(rows[0].businessTypeOID,null);
});

test("old resignation does not block rehire, but a current uncertain resignation does", () => {
  const old = {lastWorkDate:'2026-07-01',processTimeReliable:false};
  assert.equal(decideDimission([old], '2026-09-16T23:59:59+08:00', '2026-09-03').decision, '增员');
  assert.equal(decideDimission([old,{lastWorkDate:'2026-09-10',processTimeReliable:false}],
    '2026-09-16T23:59:59+08:00', '2026-09-03').decision, '待人工确认');
});

function approvalClient(pages) {
  process.env.BEISEN_APP_KEY = 'test'; process.env.BEISEN_APP_SECRET = 'test';
  const calls = [];
  const client = new BeisenClient({fetchImpl: async (url, options) => {
    if (url.endsWith('/token')) return Response.json({access_token:'test'});
    calls.push({url, options});
    return Response.json({code:'200', data:pages.shift()});
  }});
  return {client, calls};
}
const submission = {activityDefinitionName:'开始',comment:'提交。',createdTime:'2026-10-09T17:27:06.4670000'};
test('approval pagination uses actual submission and keeps later resignation included', async () => {
  const {client,calls} = approvalClient([
    {instanceList:[{activityDefinitionName:'审批',comment:'同意。',createdTime:'2026-10-12T10:00:00'}],isLastData:false,offsetId:'next'},
    {instanceList:[submission],isLastData:true},
  ]);
  const time = await client.getApprovalSubmissionTime('test-id');
  assert.equal(time,'2026-10-09T17:27:06.4670000+08:00');
  assert.equal(calls[0].options.method,'GET');
  assert.equal(new URL(calls[1].url).searchParams.get('offsetId'),'next');
  assert.equal(decideDimission([{lastWorkDate:'2026-10-13',processCreatedTime:time,processTimeReliable:true}],
    '2026-09-16T23:59:59+08:00','2026-09-07').decision,'增员');
});
test('missing or multiple submissions remain uncertain', async () => {
  for(const instanceList of [[],[submission,submission],[{...submission,createdTime:'invalid'}]]) {
    const {client} = approvalClient([{instanceList,isLastData:true}]);
    assert.equal(await client.getApprovalSubmissionTime('test-id'),'');
  }
});
test('broken approval pagination stops without retry',async()=>{
  const {client,calls}=approvalClient([{instanceList:[],isLastData:false,offsetId:'same'},{instanceList:[],isLastData:false,offsetId:'same'}]);
  await assert.rejects(client.getApprovalSubmissionTime('test-id'),{code:'BEISEN_APPROVAL_PAGE_ERROR'});
  assert.equal(calls.length,2);
});
test('approval failure stops without retry',async()=>{
  const {client,calls}=approvalClient([null]);
  await assert.rejects(client.getApprovalSubmissionTime('test-id'),{code:'BEISEN_APPROVAL_UNAVAILABLE'});
  assert.equal(calls.length,1);
});

test('departure enrichment uses workflow ID, deduplicates queries, and skips void records',async()=>{
  process.env.BEISEN_APP_KEY='test'; process.env.BEISEN_APP_SECRET='test';
  const id='739acdec-16dd-4527-be58-ab42c62546d3'; let queries=0;
  const client=new BeisenClient({fetchImpl:async(url)=>{
    if(url.endsWith('/token')) return Response.json({access_token:'test'});
    if(url.includes('/record/search?')) {
      queries++; assert.equal(new URL(url).searchParams.get('approvalObjectId'),id);
      return Response.json({code:'200',data:{instanceList:[submission],isLastData:true}});
    }
    return Response.json({code:'200',data:[1,1,5].map(approvalStatus=>({userID:1,businessTypeOID:5,approvalStatus,workFlowProcessId:id}))});
  }});
  const rows=await client.getDimissionRecords([1]);
  assert.equal(queries,1);
  assert.equal(rows[0].approvalSubmissionTime,'2026-10-09T17:27:06.4670000+08:00');
  assert.equal(rows[1].approvalSubmissionTime,rows[0].approvalSubmissionTime);
  assert.equal(rows[2].approvalSubmissionTime,undefined);
});
