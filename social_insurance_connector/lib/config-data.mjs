import { gunzipSync } from "node:zlib";
import adminDictionary from "./admin-dictionary.json" with { type: "json" };
import { ConnectorError } from "./errors.mjs";

let cachedSnapshotValue = "";
let cachedDimissionIndex = new Map();

function text(value) {
  return value === null || value === undefined ? "" : String(value).trim();
}

export function getAdminDictionary() {
  return adminDictionary;
}

export function getDimissionIndex() {
  const encoded = String(process.env.SOCIAL_INSURANCE_DIMISSION_SNAPSHOT_GZIP_BASE64 || "").trim();
  if (!encoded) {
    throw new ConnectorError("DIMISSION_SNAPSHOT_MISSING", "UAT 离职快照未配置", 503);
  }
  if (encoded === cachedSnapshotValue) return cachedDimissionIndex;
  let rows;
  try {
    const decoded = gunzipSync(Buffer.from(encoded, "base64")).toString("utf8");
    rows = JSON.parse(decoded);
  } catch {
    throw new ConnectorError("DIMISSION_SNAPSHOT_INVALID", "UAT 离职快照不可读取", 503);
  }
  if (!Array.isArray(rows)) {
    throw new ConnectorError("DIMISSION_SNAPSHOT_INVALID", "UAT 离职快照格式无效", 503);
  }
  const index = new Map();
  for (const row of rows) {
    if (!row || typeof row !== "object") continue;
    const idNumber = text(row.parent_IDNumber).replace(/\s+/gu, "");
    if (!idNumber) continue;
    const record = {
      lastWorkDate: row.LastWorkDate,
      voluntaryStopFlag: row.extshifouziyuantingbao_109025_28464420,
      processCreatedTime: row.LookupPrefix_ApprovalObjectID_CreatedTime || row.CreatedTime,
      approvalStatus: row.ApprovalStatus,
    };
    if (!index.has(idNumber)) index.set(idNumber, []);
    index.get(idNumber).push(record);
  }
  cachedSnapshotValue = encoded;
  cachedDimissionIndex = index;
  return cachedDimissionIndex;
}

export function dimissionSnapshotDate() {
  const value = String(process.env.SOCIAL_INSURANCE_DIMISSION_SNAPSHOT_DATE || "").trim();
  return /^20\d{2}-\d{2}-\d{2}$/u.test(value) ? value : null;
}
