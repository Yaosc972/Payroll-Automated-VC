import { BeisenClient, BEISEN_FIELDS } from "./beisen-client.mjs";
import { getAdminDictionary, getDimissionIndex, dimissionSnapshotDate } from "./config-data.mjs";
import { ConnectorError } from "./errors.mjs";
import {
  createAdminIndex,
  createOfferTierIndex,
  dateOnly,
  decideDimission,
  evaluateEmployee,
  fieldValue,
  inDateRange,
  isAllowedCandidateProfile,
  isCandidateEmployee,
  resolveJobNumber,
  text,
} from "./rules.mjs";

function parseDateOnly(value, field) {
  if (!/^20\d{2}-\d{2}-\d{2}$/u.test(String(value || ""))) {
    throw new ConnectorError("INVALID_REQUEST", `${field}必须为 YYYY-MM-DD`, 400);
  }
  const parsed = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(parsed.valueOf())) throw new ConnectorError("INVALID_REQUEST", `${field}无效`, 400);
  return parsed;
}

function validateRuleVersion(value) {
  const expected = String(process.env.SOCIAL_INSURANCE_RULE_VERSION || "2026.08.24-06").trim();
  if (!value || String(value) !== expected) {
    throw new ConnectorError("RULE_VERSION_MISMATCH", "连接器规则版本与工作台不一致", 409);
  }
}

function validatePeriod(payload) {
  const start = parseDateOnly(payload.periodStart, "periodStart");
  const end = parseDateOnly(payload.periodEnd, "periodEnd");
  if (start > end) throw new ConnectorError("INVALID_REQUEST", "增员周期开始日期不能晚于结束日期", 400);
  validateRuleVersion(payload.ruleVersion);
  return { start, end };
}

function modifiedWindow(periodStart) {
  const start = new Date(`${periodStart}T00:00:00Z`);
  start.setUTCDate(start.getUTCDate() - 90);
  const stop = new Date();
  stop.setUTCDate(stop.getUTCDate() + 1);
  return {
    modifiedStart: start.toISOString().slice(0, 10),
    modifiedStop: stop.toISOString().slice(0, 10),
  };
}

function indexedOfferValue(index, userId, idNumber) {
  return index?.byUserId?.get(userId)?.value || index?.byIdNumber?.get(idNumber)?.value || "";
}

function normalizedFromBeisen(rows, contracts, offerIndexes = {}) {
  const output = [];
  for (const row of rows) {
    const employee = row?.employeeInfo ?? {};
    const userId = Number(employee.userID);
    const contract = contracts.get(userId)?.[0] ?? {};
    const employeeIdNumber = fieldValue(employee, "iDNumber", { translated: false }).replace(/\s+/gu, "");
    const socialTierRemark = indexedOfferValue(offerIndexes.socialTierRemark, userId, employeeIdNumber);
    const socialContributionBase = indexedOfferValue(offerIndexes.socialContributionBase, userId, employeeIdNumber);
    const housingContributionBase = indexedOfferValue(offerIndexes.housingContributionBase, userId, employeeIdNumber);
    const services = Array.isArray(row?.recordInfoList) ? row.recordInfoList : [];
    for (const service of services) {
      output.push({
        sourceType: "beisen",
        userId,
        name: fieldValue(employee, "name"),
        jobNumber: resolveJobNumber(employee, service),
        idNumber: employeeIdNumber,
        subject: fieldValue(contract, "firstPartyCode") || fieldValue(contract, "firstParty"),
        subjectCode: fieldValue(contract, "firstPartyCode", { translated: false }),
        place: fieldValue(service, "place"),
        employType: fieldValue(service, "employType"),
        gender: fieldValue(employee, "gender"),
        mobile: fieldValue(employee, "mobilePhone", { translated: false }),
        entryDate: fieldValue(service, "entryDate", { translated: false }),
        lastWorkDate: fieldValue(service, "lastWorkDate", { translated: false }),
        serviceRecordId: fieldValue(service, "pObjectDataID", { translated: false }),
        modifiedTime: fieldValue(service, "businessModifiedTime", { translated: false }) || fieldValue(service, "modifiedTime", { translated: false }),
        socialTierRemark,
        socialContributionBase,
        housingContributionBase,
        socialComputer: fieldValue(employee, BEISEN_FIELDS.EMPLOYEE_CUSTOM.socialComputer, { translated: false }),
        housingFundAccount: fieldValue(employee, BEISEN_FIELDS.EMPLOYEE_CUSTOM.housingFundAccount, { translated: false }),
        householdAddress: fieldValue(employee, BEISEN_FIELDS.EMPLOYEE_CUSTOM.householdAddress, { translated: false }),
        birthplace: fieldValue(employee, "birthplace"),
        domicileType: fieldValue(employee, "domicileType"),
        education: fieldValue(employee, "educationLevel"),
        currentAddress: fieldValue(employee, BEISEN_FIELDS.EMPLOYEE_CUSTOM.currentAddress, { translated: false }),
        residenceAddress: fieldValue(employee, "residenceAddress", { translated: false }),
        homeAddress: fieldValue(employee, "homeAddress", { translated: false }),
        nation: fieldValue(employee, "nation"),
        employeeStatus: fieldValue(service, "employeeStatus"),
        email: fieldValue(employee, "email", { translated: false }) || fieldValue(employee, "emailAddress", { translated: false }),
        virtualEmployee: fieldValue(employee, BEISEN_FIELDS.EMPLOYEE_CUSTOM.virtualEmployee),
        employmentPlace: fieldValue(service, BEISEN_FIELDS.SERVICE_CUSTOM.employmentPlace),
        changeDescription: fieldValue(service, "changeDesc") || fieldValue(service, "changeDescription"),
      });
    }
  }
  return output;
}

function subjectMatches(employee, target) {
  if (target === "*") return Boolean(text(employee.subject) || text(employee.subjectCode));
  return [employee.subject, employee.subjectCode].map(text).filter(Boolean).some((value) => value === target);
}

function mergeByIdentity(rows) {
  const sorted = [...rows].sort((left, right) => (Date.parse(text(left.modifiedTime)) || 0) - (Date.parse(text(right.modifiedTime)) || 0));
  const merged = new Map();
  let anonymous = 0;
  for (const row of sorted) {
    const identity = text(row.idNumber).replace(/\s+/gu, "");
    const key = identity || `__missing_${row.userId || row.jobNumber || ++anonymous}`;
    const current = merged.get(key);
    if (!current) {
      merged.set(key, { ...row });
      continue;
    }
    const next = { ...current };
    for (const [field, value] of Object.entries(row)) if (text(value)) next[field] = value;
    next.sourceType = current.sourceType === row.sourceType ? current.sourceType : "hybrid";
    merged.set(key, next);
  }
  return [...merged.values()];
}

function issue(message) {
  return { field: "", severity: "blocking", message };
}

function normalizedStatus(status) {
  return { "可报盘": "ready", "待人工确认": "needs_review", "规则排除": "excluded" }[status] || "needs_review";
}

export async function listSubjects(payload, { client = new BeisenClient() } = {}) {
  validatePeriod(payload);
  const { modifiedStart, modifiedStop } = modifiedWindow(payload.periodStart);
  try {
    const rows = await client.getChangedEmployees(modifiedStart, modifiedStop);
    const candidateUserIds = new Set();
    for (const row of rows) {
      const employee = row?.employeeInfo ?? {};
      const userId = Number(employee.userID);
      if (!Number.isFinite(userId)) continue;
      const services = Array.isArray(row?.recordInfoList) ? row.recordInfoList : [];
      const virtualEmployee = fieldValue(employee, BEISEN_FIELDS.EMPLOYEE_CUSTOM.virtualEmployee);
      const eligible = services.some((service) => isAllowedCandidateProfile({
        employType: fieldValue(service, "employType"),
        virtualEmployee,
      }) && inDateRange(fieldValue(service, "entryDate", { translated: false }), payload.periodStart, payload.periodEnd));
      if (eligible) candidateUserIds.add(userId);
    }
    const contracts = await client.getContracts([...candidateUserIds]);
    const options = new Map();
    for (const userId of candidateUserIds) {
      const seen = new Set();
      for (const contract of contracts.get(userId) ?? []) {
        const name = fieldValue(contract, "firstPartyCode") || fieldValue(contract, "firstParty");
        const code = fieldValue(contract, "firstPartyCode", { translated: false });
        const value = name || code;
        const key = code || value;
        if (!value || seen.has(key)) continue;
        seen.add(key);
        const current = options.get(key) ?? { value, label: value, code, candidateCount: 0 };
        current.candidateCount += 1;
        options.set(key, current);
      }
    }
    return { subjects: [...options.values()] };
  } finally {
    client.clear?.();
  }
}

export async function syncCandidates(payload, { client = new BeisenClient() } = {}) {
  const { end } = validatePeriod(payload);
  const confirmationDate = parseDateOnly(payload.confirmationDate, "confirmationDate");
  if (confirmationDate < end) throw new ConnectorError("INVALID_REQUEST", "名单确认日不能早于增员周期结束日", 400);
  const subject = text(payload.subject);
  if (!subject) throw new ConnectorError("INVALID_REQUEST", "subject不能为空", 400);
  const { modifiedStart, modifiedStop } = modifiedWindow(payload.periodStart);
  const startedAt = Date.now();
  try {
    const [rows, offers] = await Promise.all([
      client.getChangedEmployees(modifiedStart, modifiedStop),
      client.getChangedOffers(modifiedStart, modifiedStop),
    ]);
    const userIds = rows.map((row) => Number(row?.employeeInfo?.userID)).filter(Number.isFinite);
    const contracts = await client.getContracts(userIds);
    const offerIndexes = {
      socialTierRemark: createOfferTierIndex(offers, BEISEN_FIELDS.OFFER_CUSTOM.socialTierRemark),
      socialContributionBase: createOfferTierIndex(offers, "socialSecurityRadices"),
      housingContributionBase: createOfferTierIndex(offers, "housingFundRadices"),
    };
    const employees = normalizedFromBeisen(rows, contracts, offerIndexes);
    const filteredRaw = employees.filter((employee) => isCandidateEmployee(employee, {
      subject,
      entryStart: payload.periodStart,
      entryEnd: payload.periodEnd,
    }));
    const filtered = subject === "*"
      ? [...new Map([...filteredRaw].sort((left, right) => (Date.parse(text(left.modifiedTime)) || 0) - (Date.parse(text(right.modifiedTime)) || 0)).map((employee) => [
        `${text(employee.idNumber).replace(/\s+/gu, "")}::${text(employee.subjectCode) || text(employee.subject)}`,
        employee,
      ])).values()]
      : mergeByIdentity(filteredRaw);
    const idCounts = new Map();
    for (const employee of filtered) {
      const id = text(employee.idNumber).replace(/\s+/gu, "");
      if (id) idCounts.set(id, (idCounts.get(id) ?? 0) + 1);
    }
    const dimissionIndex = getDimissionIndex();
    const adminIndex = createAdminIndex(getAdminDictionary());
    const cutoff = `${payload.confirmationDate}T23:59:59+08:00`;
    const records = filtered.map((employee) => {
      const id = text(employee.idNumber).replace(/\s+/gu, "");
      const dimissionRecords = dimissionIndex.get(id) ?? [];
      const dimission = decideDimission(dimissionRecords, cutoff, employee.entryDate);
      const evaluated = evaluateEmployee(employee, adminIndex);
      let status = evaluated.status;
      const reasons = [...evaluated.issues];
      if ((idCounts.get(id) ?? 0) > 1) {
        status = "待人工确认";
        reasons.push("同批次证件号码重复");
      }
      const baseStatus = normalizedStatus(status);
      const baseIssues = reasons.filter(Boolean).map(issue);
      if (dimission.decision === "排除") status = "规则排除";
      if (dimission.decision === "待人工确认") status = "待人工确认";
      if (dimission.decision === "待人工确认") reasons.unshift(dimission.reason);
      if (status === "规则排除") reasons.splice(0, reasons.length, dimission.reason);
      return {
        status: normalizedStatus(status),
        confirmed: false,
        issues: reasons.filter(Boolean).map(issue),
        report: evaluated.report,
        source: employee,
        entryDate: dateOnly(employee.entryDate),
        dimissionReason: dimission.reason,
        coverageSource: {},
        confirmationRuleContext: {
          version: 1,
          baseStatus,
          baseIssues,
          currentEntryDate: dateOnly(employee.entryDate),
          dimissionRecords: dimissionRecords.map((record) => ({
            lastWorkDate: record.lastWorkDate ?? "",
            voluntaryStopFlag: text(record.voluntaryStopFlag),
            processCreatedTime: record.processCreatedTime ?? "",
          })),
        },
      };
    });
    const snapshotDate = dimissionSnapshotDate();
    const warnings = [];
    if (!snapshotDate) warnings.push("离职快照日期未配置，请在最终提交前确认数据时点。");
    else if (snapshotDate < payload.periodEnd) warnings.push(`离职快照日期为${snapshotDate}，早于周期结束日。`);
    return {
      records,
      sourceSummary: {
        provider: "beisen-open-platform",
        candidateCount: records.length,
        readyCount: records.filter((record) => record.status === "ready").length,
        manualCount: records.filter((record) => record.status === "needs_review").length,
        excludedCount: records.filter((record) => record.status === "excluded").length,
        departureRuleSource: "uat-environment-snapshot",
        departureSnapshotDate: snapshotDate,
        confirmationDate: payload.confirmationDate,
        rawApiResponseSaved: false,
        governmentSiteAccessed: false,
        elapsedMs: Date.now() - startedAt,
        warnings,
      },
    };
  } finally {
    client.clear?.();
  }
}
