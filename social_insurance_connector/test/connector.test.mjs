import assert from "node:assert/strict";
import { gzipSync } from "node:zlib";
import test from "node:test";

import subjectsHandler from "../api/subjects.mjs";
import healthHandler from "../api/health.mjs";
import { listSubjects, syncCandidates } from "../lib/service.mjs";

const RULE_VERSION = "2026.08.27-07";

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
  assert.equal(result.sourceSummary.departureRuleSource, "configured-snapshot-fallback");
});

test("sync requires review when compatibility records mix valid and missing process times", async () => {
  setConfiguration();
  process.env.SOCIAL_INSURANCE_DIMISSION_SNAPSHOT_GZIP_BASE64 = gzipSync(
    Buffer.from(JSON.stringify([{
      parent_IDNumber: "TEST-ID-001",
      LastWorkDate: "2026-08-20",
      extshifouziyuantingbao_109025_28464420: "自愿停保",
      LookupPrefix_ApprovalObjectID_CreatedTime: "2026-08-20T10:00:00+08:00",
      ApprovalStatus: "已通过",
    }, {
      parent_IDNumber: "TEST-ID-001",
      LastWorkDate: "2026-08-21",
      extshifouziyuantingbao_109025_28464420: "自愿停保",
      LookupPrefix_ApprovalObjectID_CreatedTime: "",
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

  assert.equal(result.records[0].status, "needs_review");
  assert.equal(
    result.records[0].dimissionReason,
    "离职任职记录缺少流程时间或停保属性，请人工确认",
  );
});

test("sync ignores a compatibility snapshot whose snapshot date is missing", async () => {
  setConfiguration();
  delete process.env.SOCIAL_INSURANCE_DIMISSION_SNAPSHOT_DATE;
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

  assert.notEqual(result.sourceSummary.departureRuleSource, "configured-snapshot-fallback");
  assert.equal(result.sourceSummary.departureCompatibilitySnapshotDate, null);
  assert.equal(result.records[0].confirmationRuleContext.dimissionRecords.length, 0);
  assert.equal(
    result.sourceSummary.warnings.includes("兼容离职快照日期缺失，已忽略；本次仅使用北森实时任职记录。"),
    true,
  );
});

test("sync ignores a compatibility snapshot whose snapshot date is not a real calendar date", async () => {
  setConfiguration();
  process.env.SOCIAL_INSURANCE_DIMISSION_SNAPSHOT_DATE = "2026-02-31";
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

  assert.equal(result.sourceSummary.departureRuleSource, "beisen-live-employee-records");
  assert.equal(result.sourceSummary.departureCompatibilitySnapshotDate, null);
  assert.equal(result.records[0].confirmationRuleContext.dimissionRecords.length, 0);
  assert.equal(
    result.sourceSummary.warnings.includes("兼容离职快照日期缺失，已忽略；本次仅使用北森实时任职记录。"),
    true,
  );
});

test("sync detects live Beisen dimission fields without treating modified time as approval time", async () => {
  setConfiguration();
  delete process.env.SOCIAL_INSURANCE_DIMISSION_SNAPSHOT_DATE;
  delete process.env.SOCIAL_INSURANCE_DIMISSION_SNAPSHOT_GZIP_BASE64;
  const client = fakeClient();
  client.getChangedEmployees = async () => [{
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
        extshifoushixuniyuangong_109025_1767668301: "否",
      },
    },
    recordInfoList: [{
      employType: "内部员工",
      entryDate: "2026-07-20",
      lastWorkDate: "2026-08-20",
      employeeStatus: "离职",
      place: "深圳",
      jobNumber: "ZT-TEST-001",
      modifiedTime: "2026-08-20T10:00:00+08:00",
      customProperties: {
        extshifouziyuantingbao_109025_28464420: "自愿停保",
      },
    }],
  }];

  const result = await syncCandidates({
    periodStart: "2026-07-16",
    periodEnd: "2026-08-15",
    confirmationDate: "2026-08-24",
    subject: "SZ001",
    ruleVersion: RULE_VERSION,
  }, { client });

  assert.equal(result.records[0].status, "needs_review");
  assert.equal(
    result.records[0].dimissionReason,
    "北森实时离职记录缺少可靠审批时间或停保属性，请人工确认",
  );
  assert.equal(result.sourceSummary.departureRuleSource, "beisen-live-employee-records");
  assert.equal(result.sourceSummary.departureLiveRecordCount, 1);
  assert.equal(result.sourceSummary.departureLiveStopFlagCount, 1);
  assert.equal(result.sourceSummary.warnings.length, 0);
  assert.deepEqual(result.records[0].confirmationRuleContext.dimissionRecords, [{
    lastWorkDate: "2026-08-20",
    voluntaryStopFlag: "自愿停保",
    processCreatedTime: "2026-08-20T10:00:00+08:00",
    processTimeReliable: false,
    source: "beisen-live-employment-record",
  }]);
});

test("sync requires review when Beisen only reports a dimission employee status", async () => {
  setConfiguration();
  delete process.env.SOCIAL_INSURANCE_DIMISSION_SNAPSHOT_DATE;
  delete process.env.SOCIAL_INSURANCE_DIMISSION_SNAPSHOT_GZIP_BASE64;
  const client = fakeClient();
  const rows = await client.getChangedEmployees();
  rows[0].recordInfoList[0].employeeStatus = "离职";
  rows[0].recordInfoList[0].lastWorkDate = "";
  rows[0].recordInfoList[0].modifiedTime = "";
  client.getChangedEmployees = async () => rows;

  const result = await syncCandidates({
    periodStart: "2026-07-16",
    periodEnd: "2026-08-15",
    confirmationDate: "2026-08-24",
    subject: "SZ001",
    ruleVersion: RULE_VERSION,
  }, { client });

  assert.equal(result.records[0].status, "needs_review");
  assert.equal(
    result.records[0].dimissionReason,
    "北森实时离职记录缺少可靠审批时间或停保属性，请人工确认",
  );
});

test("live dimission context takes precedence over a configured compatibility snapshot", async () => {
  setConfiguration();
  process.env.SOCIAL_INSURANCE_DIMISSION_SNAPSHOT_GZIP_BASE64 = gzipSync(
    Buffer.from(JSON.stringify([{
      parent_IDNumber: "TEST-ID-001",
      LastWorkDate: "2026-08-19",
      extshifouziyuantingbao_109025_28464420: "自愿停保",
      LookupPrefix_ApprovalObjectID_CreatedTime: "2026-08-19T10:00:00+08:00",
      ApprovalStatus: "已通过",
    }]), "utf8"),
  ).toString("base64");
  const client = fakeClient();
  const rows = await client.getChangedEmployees();
  rows[0].recordInfoList[0].employeeStatus = "离职";
  rows[0].recordInfoList[0].lastWorkDate = "2026-08-20";
  client.getChangedEmployees = async () => rows;

  const result = await syncCandidates({
    periodStart: "2026-07-16",
    periodEnd: "2026-08-15",
    confirmationDate: "2026-08-24",
    subject: "SZ001",
    ruleVersion: RULE_VERSION,
  }, { client });

  assert.equal(result.records[0].status, "needs_review");
  assert.equal(result.records[0].confirmationRuleContext.dimissionRecords.length, 1);
  assert.equal(
    result.records[0].confirmationRuleContext.dimissionRecords[0].source,
    "beisen-live-employment-record",
  );
});

test("an invalid compatibility snapshot does not block live Beisen dimission review", async () => {
  setConfiguration();
  process.env.SOCIAL_INSURANCE_DIMISSION_SNAPSHOT_GZIP_BASE64 = "not-a-gzip-snapshot";
  const client = fakeClient();
  const rows = await client.getChangedEmployees();
  rows[0].recordInfoList[0].employeeStatus = "离职";
  client.getChangedEmployees = async () => rows;

  const result = await syncCandidates({
    periodStart: "2026-07-16",
    periodEnd: "2026-08-15",
    confirmationDate: "2026-08-24",
    subject: "SZ001",
    ruleVersion: RULE_VERSION,
  }, { client });

  assert.equal(result.records[0].status, "needs_review");
  assert.equal(
    result.sourceSummary.warnings.includes("兼容离职快照不可读取，已忽略；本次仅使用北森实时任职记录。"),
    true,
  );
});

test("connector endpoint requires bearer token and does not echo supplied credentials", async () => {
  setConfiguration();
  const response = responseRecorder();
  await subjectsHandler({ method: "POST", headers: { authorization: "Bearer wrong-token" }, body: {} }, response);
  assert.equal(response.statusCode, 401);
  assert.equal(JSON.stringify(response.payload).includes("wrong-token"), false);
});

test("health reports the connector configured without a monthly snapshot", () => {
  setConfiguration();
  delete process.env.SOCIAL_INSURANCE_DIMISSION_SNAPSHOT_DATE;
  delete process.env.SOCIAL_INSURANCE_DIMISSION_SNAPSHOT_GZIP_BASE64;
  const response = responseRecorder();

  healthHandler({}, response);

  assert.equal(response.payload.configured, true);
});

test("rule version mismatch is rejected before calling Beisen", async () => {
  setConfiguration();
  await assert.rejects(
    listSubjects({ periodStart: "2026-07-16", periodEnd: "2026-08-15", ruleVersion: "old" }, { client: fakeClient() }),
    (error) => error.code === "RULE_VERSION_MISMATCH" && error.status === 409,
  );
});
