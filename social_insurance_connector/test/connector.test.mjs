import assert from "node:assert/strict";
import { gzipSync } from "node:zlib";
import test from "node:test";

import subjectsHandler from "../api/subjects.mjs";
import { listSubjects, syncCandidates } from "../lib/service.mjs";

const RULE_VERSION = "2026.08.24-06";

function setConfiguration() {
  process.env.CONNECTOR_TOKEN = "test-connector-token";
  process.env.BEISEN_APP_KEY = "test-key";
  process.env.BEISEN_APP_SECRET = "test-secret";
  process.env.SOCIAL_INSURANCE_DIMISSION_SNAPSHOT_DATE = "2026-08-24";
  process.env.SOCIAL_INSURANCE_DIMISSION_SNAPSHOT_GZIP_BASE64 = gzipSync(
    Buffer.from("[]", "utf8"),
  ).toString("base64");
}

function fakeClient() {
  const employee = {
    employeeInfo: {
      userID: 1001,
      name: "测试人员",
      iDNumber: "TEST-ID-001",
      gender: "女",
      nation: "汉",
      mobilePhone: "13800000000",
      educationLevel: "大学本科",
      birthplace: "广东省深圳市",
      residenceAddress: "广东省深圳市南山区科技园",
      customProperties: {
        extsocno_109025_273047989: "123456789",
        extRADD3_109025_721488871: "广东省深圳市南山区科技园",
        extnowadd_109025_1438726230: "广东省深圳市南山区科技园",
        extshifoushixuniyuangong_109025_1767668301: "否",
      },
    },
    recordInfoList: [{
      employType: "内部员工",
      entryDate: "2026-07-20",
      employeeStatus: "在职",
      place: "深圳",
      jobNumber: "ZT-TEST-001",
      modifiedTime: "2026-08-20T12:00:00+08:00",
    }],
  };
  return {
    async getChangedEmployees() { return [employee]; },
    async getContracts() {
      return new Map([[1001, [{ userID: 1001, firstParty: "深圳测试主体", firstPartyCode: "SZ001" }]]]);
    },
    async getChangedOffers() { return []; },
    clear() {},
  };
}

function responseRecorder() {
  return {
    headers: {},
    statusCode: 0,
    payload: null,
    setHeader(key, value) { this.headers[key] = value; },
    status(value) { this.statusCode = value; return this; },
    json(value) { this.payload = value; return this; },
  };
}

test("subjects returns aggregated contract subjects without employee records", async () => {
  setConfiguration();
  const result = await listSubjects({
    periodStart: "2026-07-16",
    periodEnd: "2026-08-15",
    ruleVersion: RULE_VERSION,
  }, { client: fakeClient() });
  assert.deepEqual(result, {
    subjects: [{ value: "SZ001", label: "SZ001", code: "SZ001", candidateCount: 1 }],
  });
  assert.equal(JSON.stringify(result).includes("TEST-ID-001"), false);
});

test("sync returns standardized records and strips raw upstream responses", async () => {
  setConfiguration();
  const result = await syncCandidates({
    periodStart: "2026-07-16",
    periodEnd: "2026-08-15",
    confirmationDate: "2026-08-24",
    subject: "SZ001",
    ruleVersion: RULE_VERSION,
  }, { client: fakeClient() });
  assert.equal(result.records.length, 1);
  assert.equal(result.records[0].report["姓名"], "测试人员");
  assert.match(result.records[0].status, /^(ready|needs_review|excluded)$/u);
  assert.equal(result.sourceSummary.candidateCount, 1);
  assert.equal(result.sourceSummary.rawApiResponseSaved, false);
  assert.equal("rawApiResponse" in result.sourceSummary, false);
});

test("sync includes a private confirmation rule context for snapshot rebasing", async () => {
  setConfiguration();
  process.env.SOCIAL_INSURANCE_DIMISSION_SNAPSHOT_GZIP_BASE64 = gzipSync(
    Buffer.from(JSON.stringify([{
      parent_IDNumber: "TEST-ID-001",
      LastWorkDate: "2026-08-20",
      extshifouziyuantingbao_109025_28464420: "自愿停保",
      LookupPrefix_ApprovalObjectID_CreatedTime: "2026-08-20T10:00:00+08:00",
      ApprovalStatus: "已通过",
    }]), "utf8"),
  ).toString("base64");

  const result = await syncCandidates({
    periodStart: "2026-07-16",
    periodEnd: "2026-08-15",
    confirmationDate: "2026-08-24",
    subject: "SZ001",
    ruleVersion: RULE_VERSION,
  }, { client: fakeClient() });

  const context = result.records[0].confirmationRuleContext;
  assert.equal(context.version, 1);
  assert.match(context.baseStatus, /^(ready|needs_review)$/u);
  assert.equal(context.currentEntryDate, "2026-07-20");
  assert.equal(context.dimissionRecords.length, 1);
  assert.equal(context.dimissionRecords[0].voluntaryStopFlag, "自愿停保");
  assert.equal("idNumber" in context.dimissionRecords[0], false);
});

test("connector endpoint requires bearer token and does not echo supplied credentials", async () => {
  setConfiguration();
  const response = responseRecorder();
  await subjectsHandler({ method: "POST", headers: { authorization: "Bearer wrong-token" }, body: {} }, response);
  assert.equal(response.statusCode, 401);
  assert.equal(JSON.stringify(response.payload).includes("wrong-token"), false);
});

test("rule version mismatch is rejected before calling Beisen", async () => {
  setConfiguration();
  await assert.rejects(
    listSubjects({ periodStart: "2026-07-16", periodEnd: "2026-08-15", ruleVersion: "old" }, { client: fakeClient() }),
    (error) => error.code === "RULE_VERSION_MISMATCH" && error.status === 409,
  );
});
