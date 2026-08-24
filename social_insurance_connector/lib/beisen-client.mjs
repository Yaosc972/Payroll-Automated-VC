import { ConnectorError } from "./errors.mjs";

const EMPLOYEE_CUSTOM = {
  socialComputer: "extsocno_109025_273047989",
  housingFundAccount: "extbankaccount_109025_722757437",
  householdAddress: "extRADD3_109025_721488871",
  currentAddress: "extnowadd_109025_1438726230",
  virtualEmployee: "extshifoushixuniyuangong_109025_1767668301",
};

const SERVICE_CUSTOM = {
  employmentPlace: "extempatsplc_109025_254164879",
};

const OFFER_CUSTOM = {
  socialTierRemark: "extygxxshebaojiaonadi_109025_621990250",
};

export const BEISEN_FIELDS = { EMPLOYEE_CUSTOM, SERVICE_CUSTOM, OFFER_CUSTOM };

function chunks(values, size) {
  const output = [];
  for (let index = 0; index < values.length; index += size) output.push(values.slice(index, index + size));
  return output;
}

function isoDate(date) {
  return date.toISOString().slice(0, 10);
}

function splitWindows(start, stop) {
  const from = new Date(`${start}T00:00:00Z`);
  const to = new Date(`${stop}T00:00:00Z`);
  if (Number.isNaN(from.valueOf()) || Number.isNaN(to.valueOf()) || from > to) {
    throw new ConnectorError("INVALID_DATE_RANGE", "日期范围无效", 400);
  }
  const windows = [];
  let cursor = from;
  while (cursor <= to) {
    const end = new Date(Math.min(to.valueOf(), cursor.valueOf() + 89 * 86400000));
    windows.push([isoDate(cursor), isoDate(end)]);
    cursor = new Date(end.valueOf() + 86400000);
  }
  return windows;
}

function configuredBaseUrl() {
  const value = String(process.env.BEISEN_BASE_URL || "https://openapi.italent.cn").trim().replace(/\/$/u, "");
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    throw new ConnectorError("BEISEN_NOT_CONFIGURED", "北森地址配置无效", 503);
  }
  if (parsed.protocol !== "https:") {
    throw new ConnectorError("BEISEN_NOT_CONFIGURED", "北森地址必须使用 HTTPS", 503);
  }
  return value;
}

export class BeisenClient {
  constructor({ fetchImpl = globalThis.fetch } = {}) {
    if (process.env.NODE_TLS_REJECT_UNAUTHORIZED === "0") {
      throw new ConnectorError("TLS_DISABLED", "检测到 TLS 校验被关闭", 503);
    }
    this.fetchImpl = fetchImpl;
    this.baseUrl = configuredBaseUrl();
    this.appKey = String(process.env.BEISEN_APP_KEY || "").trim();
    this.appSecret = String(process.env.BEISEN_APP_SECRET || "").trim();
    if (!this.appKey || !this.appSecret) {
      throw new ConnectorError("BEISEN_NOT_CONFIGURED", "北森授权未配置", 503);
    }
    this.accessToken = "";
  }

  async fetchJson(path, body, stage) {
    let response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}${path}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(this.accessToken ? { Authorization: `Bearer ${this.accessToken}` } : {}),
        },
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(30000),
      });
    } catch {
      throw new ConnectorError("BEISEN_UNAVAILABLE", `北森${stage}请求失败`, 502);
    }
    const payload = await response.json().catch(() => null);
    if (!response.ok || !payload) {
      throw new ConnectorError("BEISEN_UPSTREAM_ERROR", `北森${stage}返回异常`, 502);
    }
    return payload;
  }

  async authenticate() {
    const payload = await this.fetchJson("/token", {
      grant_type: "client_credentials",
      app_key: this.appKey,
      app_secret: this.appSecret,
    }, "认证");
    this.accessToken = typeof payload.access_token === "string" ? payload.access_token : "";
    if (!this.accessToken) throw new ConnectorError("BEISEN_AUTH_FAILED", "北森认证失败", 502);
  }

  async request(path, body, stage) {
    if (!this.accessToken) await this.authenticate();
    const payload = await this.fetchJson(path, body, stage);
    if (payload.code && String(payload.code) !== "200") {
      throw new ConnectorError("BEISEN_UPSTREAM_ERROR", `北森${stage}返回异常`, 502);
    }
    return payload;
  }

  async getChangedEmployees(modifiedStart, modifiedStop) {
    const columns = [
      "UserID", "Name", "IDType", "IDNumber", "Gender", "Nation", "Birthplace",
      "RegistAddress", "ResidenceAddress", "HomeAddress", "MobilePhone", "DomicileType",
      "EducationLevel", "EntryDate", "LastWorkDate", "JobNumber", "OIdDepartment",
      "OIdOrganization", "EmployeeStatus", "EmployType", "ServiceType", "Place",
      "PObjectDataID", "BusinessModifiedTime", "ModifiedTime",
      ...Object.values(EMPLOYEE_CUSTOM), ...Object.values(SERVICE_CUSTOM),
    ];
    const queryWindow = async ([startTime, stopTime]) => {
      const rows = [];
      let scrollId = "";
      let isLast = false;
      let pages = 0;
      while (!isLast) {
        if (++pages > 200) throw new ConnectorError("BEISEN_PAGE_LIMIT", "北森员工查询超过安全页数", 502);
        const payload = await this.request("/TenantBaseExternal/api/v5/Employee/GetListByTimeWindow", {
          timeWindowQueryType: 1,
          startTime,
          stopTime,
          capacity: 300,
          columns,
          serviceType: [0],
          scrollId,
          isWithDeleted: false,
          enableTranslate: true,
        }, "员工查询");
        if (Array.isArray(payload.data)) rows.push(...payload.data);
        isLast = payload.isLastData === true;
        scrollId = typeof payload.scrollId === "string" ? payload.scrollId : "";
        if (!isLast && !scrollId) throw new ConnectorError("BEISEN_SCROLL_ERROR", "北森员工查询分页异常", 502);
      }
      return rows;
    };
    const windows = await Promise.all(splitWindows(modifiedStart, modifiedStop).map(queryWindow));
    return windows.flat();
  }

  async getContracts(userIds) {
    const contractMap = new Map();
    for (const batch of chunks([...new Set(userIds.map(Number).filter(Number.isFinite))], 300)) {
      if (!batch.length) continue;
      const payload = await this.request("/TenantBaseExternal/api/v5/Contract/GetByUserIds", {
        isCurrentEffective: true,
        status: 1,
        oIds: batch,
        contractType: 0,
        columns: ["UserID", "FirstParty", "FirstPartyCode", "FirstPartyLookup", "Status", "ContractType"],
        isWithDeleted: false,
        enableTranslate: true,
      }, "合同查询");
      const groups = payload.data && typeof payload.data === "object" ? Object.values(payload.data) : [];
      for (const contract of groups.flatMap((group) => Array.isArray(group) ? group : [])) {
        const userId = Number(contract.userID);
        if (!Number.isFinite(userId)) continue;
        if (!contractMap.has(userId)) contractMap.set(userId, []);
        contractMap.get(userId).push(contract);
      }
    }
    return contractMap;
  }

  async getChangedOffers(modifiedStart, modifiedStop) {
    const columns = [
      "UserID", "IDNumber", "BusinessModifiedTime", "ModifiedTime", "ApprovalStatus", "OfferStatus",
      "ObjectId", "SocialSecurityRadices", "HousingFundRadices", ...Object.values(OFFER_CUSTOM),
    ];
    const allRows = [];
    for (const [startTime, stopTime] of splitWindows(modifiedStart, modifiedStop)) {
      let scrollId = "";
      let isLast = false;
      let pages = 0;
      while (!isLast) {
        if (++pages > 200) throw new ConnectorError("BEISEN_PAGE_LIMIT", "北森 Offer 查询超过安全页数", 502);
        const payload = await this.request("/TenantBaseExternal/api/v5/Offer/GetByTimeWindow", {
          timeWindowQueryType: 1,
          startTime,
          stopTime,
          capacity: 300,
          columns,
          scrollId,
          isWithDeleted: false,
          enableTranslate: true,
        }, "Offer 查询");
        if (Array.isArray(payload.data)) allRows.push(...payload.data);
        isLast = payload.isLastData === true;
        scrollId = typeof payload.scrollId === "string" ? payload.scrollId : "";
        if (!isLast && !scrollId) throw new ConnectorError("BEISEN_SCROLL_ERROR", "北森 Offer 查询分页异常", 502);
      }
    }
    return allRows;
  }

  clear() {
    this.appKey = "";
    this.appSecret = "";
    this.accessToken = "";
  }
}
