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
