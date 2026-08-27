const DAY_MS = 24 * 60 * 60 * 1000;

export const TEMPLATE_HEADERS = [
  "证件号码", "姓名", "户籍", "入深户时间", "民族", "手机号码", "通讯地址", "电脑号",
  "岗位类别", "个人身份", "用工形式", "学历", "职称", "国家职业资格或职业技能等级",
  "医疗缴费档次", "部门名称", "户籍地类别", "户口所在地行政区划代码", "就业形式", "就业前身份",
];

export function text(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") {
    for (const key of ["displayName", "name", "text", "value", "label"]) {
      if (value[key] !== null && value[key] !== undefined) return String(value[key]).trim();
    }
    return "";
  }
  return String(value).trim();
}

export function fieldValue(record, key, { translated = true } = {}) {
  if (!record || typeof record !== "object") return "";
  if (translated) {
    const translatedMap = record.translateProperties;
    if (translatedMap && typeof translatedMap === "object") {
      const pascalKey = key[0]?.toUpperCase() + key.slice(1);
      for (const translatedKey of [key, pascalKey, `_${key}`, `${key}Text`, `${pascalKey}Text`]) {
        const candidate = text(translatedMap[translatedKey]);
        if (candidate) return candidate;
      }
    }
  }
  const direct = text(record[key]);
  if (direct) return direct;
  const custom = record.customProperties;
  return custom && typeof custom === "object" ? text(custom[key]) : "";
}

export function resolveJobNumber(employee, service) {
  return fieldValue(employee, "jobNumber", { translated: false }) ||
    fieldValue(service, "jobNumber", { translated: false });
}

export function isAllowedCandidateProfile(employee) {
  const employment = text(employee?.employType);
  if (!/^(内部员工|管培生)$/u.test(employment)) return false;
  const virtualFlag = text(employee?.virtualEmployee).toLowerCase().replace(/\s+/gu, "");
  return !/^(?:是|true|1|yes|y|虚拟|虚拟员工|1[.。]?是)$/u.test(virtualFlag);
}

export function isCandidateEmployee(employee, { subject, entryStart, entryEnd }) {
  const target = text(subject);
  const employeeSubjects = [employee?.subject, employee?.subjectCode].map(text).filter(Boolean);
  const subjectMatched = target === "*"
    ? employeeSubjects.length > 0
    : employeeSubjects.some((value) => value === target);
  return subjectMatched &&
    isAllowedCandidateProfile(employee) &&
    inDateRange(employee?.entryDate, entryStart, entryEnd);
}

export function matchesLocationScope(employee, subject) {
  void employee;
  void subject;
  // 候选层只判断合同主体、用工类型和入职周期。地点留到报盘工作台，
  // 再按参保城市映射政务模板；这里提前过滤会静默漏掉非深圳员工。
  return true;
}

export function createOfferTierIndex(offers, tierField) {
  const byUserId = new Map();
  const byIdNumber = new Map();
  for (const offer of offers ?? []) {
    const value = fieldValue(offer, tierField);
    if (!value) continue;
    const modifiedTime = Date.parse(
      fieldValue(offer, "businessModifiedTime", { translated: false }) ||
      fieldValue(offer, "modifiedTime", { translated: false }),
    ) || 0;
    const candidate = { value, modifiedTime };
    const userIdRaw = fieldValue(offer, "userID", { translated: false });
    const userId = userIdRaw ? Number(userIdRaw) : Number.NaN;
    const idNumber = fieldValue(offer, "iDNumber", { translated: false }).replace(/\s+/gu, "");
    if (Number.isFinite(userId) && userId > 0) {
      const current = byUserId.get(userId);
      if (!current || modifiedTime >= current.modifiedTime) byUserId.set(userId, candidate);
    }
    if (idNumber) {
      const current = byIdNumber.get(idNumber);
      if (!current || modifiedTime >= current.modifiedTime) byIdNumber.set(idNumber, candidate);
    }
  }
  return { byUserId, byIdNumber };
}

export function parseDate(value) {
  if (value instanceof Date && !Number.isNaN(value.valueOf())) return value;
  if (typeof value === "number" && Number.isFinite(value)) {
    return new Date(Date.UTC(1899, 11, 30) + value * DAY_MS);
  }
  const raw = text(value);
  if (!raw) return null;
  const parsed = new Date(raw);
  return Number.isNaN(parsed.valueOf()) ? null : parsed;
}

export function dateOnly(value) {
  const date = parseDate(value);
  if (!date) return "";
  if (typeof value === "number") return date.toISOString().slice(0, 10);
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(date);
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

export function inDateRange(value, start, stop) {
  const date = parseDate(value);
  const from = parseDate(`${start}T00:00:00+08:00`);
  const to = parseDate(`${stop}T23:59:59+08:00`);
  return !!(date && from && to && date >= from && date <= to);
}

function removeSuffix(name) {
  return name.replace(/(特别行政区|自治区|自治州|自治县|地区|盟|省|市|区|县|旗)$/u, "");
}

function addressText(value) {
  return text(value).replace(/[\s,，。;；()（）]/gu, "");
}

const ETHNIC_GROUP_PATTERN = /(土家族|苗族|侗族|瑶族|壮族|回族|藏族|彝族|蒙古族|满族|仡佬族|朝鲜族|哈尼族|傣族|黎族|傈僳族|佤族|畲族|高山族|拉祜族|水族|东乡族|纳西族|景颇族|柯尔克孜族|土族|达斡尔族|仫佬族|羌族|布朗族|撒拉族|毛南族|锡伯族|阿昌族|普米族|塔吉克族|怒族|乌孜别克族|俄罗斯族|鄂温克族|德昂族|保安族|裕固族|京族|塔塔尔族|独龙族|鄂伦春族|赫哲族|门巴族|珞巴族|基诺族)/u;

const VERIFIED_ADMIN_OVERRIDES = new Map([
  ["zt29396", "410822"],
  ["zt29527", "430422"],
  ["zt29485", "440305"],
  ["zt29481", "445203"],
]);

function geographicShortName(name) {
  const shortName = removeSuffix(name);
  return name.endsWith("自治县") ? shortName.split(ETHNIC_GROUP_PATTERN)[0] : shortName;
}

function provinceShortName(name) {
  return name
    .replace(/(壮族|回族|维吾尔族)自治区$/u, "")
    .replace(/(特别行政区|自治区|省|市)$/u, "");
}

export function createAdminIndex(dictionaryValues) {
  const entries = [];
  for (const raw of dictionaryValues) {
    const match = text(raw).match(/^(\d{2}|\d{4}|\d{6})[.．](.+)$/u);
    if (!match) continue;
    const [, code, name] = match;
    entries.push({
      code,
      name: name.trim(),
      shortName: removeSuffix(name.trim()),
      geoName: geographicShortName(name.trim()),
    });
  }
  const byCode = new Map(entries.map((entry) => [entry.code, entry]));
  const provinces = entries.filter((entry) => entry.code.length === 2);
  const cities = entries.filter((entry) => entry.code.length === 4);
  const counties = entries.filter((entry) => entry.code.length === 6);
  return { entries, byCode, provinces, cities, counties };
}

function identifyProvince(rawSource, index) {
  const source = addressText(rawSource);
  if (!source || !index) return "";
  const provinces = index.provinces
    .map((entry) => ({ ...entry, alias: provinceShortName(entry.name) }))
    .sort((left, right) => right.name.length - left.name.length);
  const fullAtStart = provinces.find((entry) => source.startsWith(entry.name));
  if (fullAtStart) return fullAtStart.code;

  const cities = [...index.cities].sort((left, right) => right.name.length - left.name.length);
  const cityAtStart = cities.find((entry) =>
    (entry.name.length >= 2 && source.startsWith(entry.name)) ||
    (entry.shortName.length >= 2 && source.startsWith(entry.shortName))
  );
  if (cityAtStart) return cityAtStart.code.slice(0, 2);

  const fullContained = provinces.find((entry) => entry.name.length >= 3 && source.includes(entry.name));
  if (fullContained) return fullContained.code;

  for (const entry of provinces) {
    if (entry.alias.length < 2) continue;
    const offset = source.indexOf(entry.alias);
    if (offset < 0) continue;
    const following = source.slice(offset + entry.alias.length, offset + entry.alias.length + 1);
    if (offset === 0 || ["省", "市", "区", "族", "别"].includes(following)) return entry.code;
  }

  const cityContained = cities.find((entry) => entry.name.length >= 2 && source.includes(entry.name));
  return cityContained ? cityContained.code.slice(0, 2) : "";
}

function contextScore(source, entry, index) {
  let score = 0;
  if (source.includes(entry.name)) score += 12;
  else if (entry.shortName.length >= 2 && shortCountyNameMatches(source, entry, index)) score += 7;
  else if (entry.name.endsWith("自治县") && entry.geoName.length >= 2 && shortCountyNameMatches(source, { ...entry, shortName: entry.geoName }, index)) score += 7;
  else return -1;

  const city = index.byCode.get(entry.code.slice(0, 4));
  const province = index.byCode.get(entry.code.slice(0, 2));
  if (city && (source.includes(city.name) || (city.shortName.length >= 2 && source.includes(city.shortName)))) score += 4;
  if (province && (source.includes(province.name) || (province.shortName.length >= 2 && source.includes(province.shortName)))) score += 2;
  return score;
}

function shortCountyNameMatches(source, entry, index) {
  let offset = source.indexOf(entry.shortName);
  while (offset >= 0) {
    const following = source.slice(offset + entry.shortName.length, offset + entry.shortName.length + 1);
    const prefecture = following === "市" && index.cities.some((city) =>
      city.name === `${entry.shortName}市` || city.shortName === entry.shortName
    );
    if (!prefecture) {
      if (entry.name.endsWith("市")) return true;
      if (["市", "区", "县", "镇", "乡", "街", "路"].includes(following)) return true;
    }
    offset = source.indexOf(entry.shortName, offset + 1);
  }
  return false;
}

function matchOneAddress(rawSource, index, provinceHint = "") {
  const source = addressText(rawSource);
  if (!source) return null;
  const provinceCode = identifyProvince(source, index) || provinceHint;
  if (!provinceCode) return { status: "manual", value: "", reason: "地址未能识别有效省份" };
  const excludedNames = new Set(["市辖区", "市本级", "农垦", "农垦局"]);

  const scored = index.counties
    .filter((entry) => entry.code.startsWith(provinceCode) && !excludedNames.has(entry.name))
    .map((entry) => ({ entry, score: contextScore(source, entry, index) }))
    .filter(({ score }) => score >= 0)
    .sort((a, b) => b.score - a.score || b.entry.name.length - a.entry.name.length);

  if (scored.length && (scored.length === 1 || scored[0].score > scored[1].score)) {
    return { status: "matched", value: `${scored[0].entry.code}.${scored[0].entry.name}`, reason: "区县唯一匹配" };
  }

  const cityMatches = index.cities.filter((entry) => entry.code.startsWith(provinceCode) && (
    source.includes(entry.name) || (entry.shortName.length >= 2 && source.includes(entry.shortName))
  )
  );
  if (cityMatches.length === 1) {
    const municipal = index.byCode.get(`${cityMatches[0].code}01`);
    if (municipal && municipal.name === "市辖区") {
      return { status: "matched", value: `${municipal.code}.${municipal.name}`, reason: "仅到地级市，使用模板市辖区" };
    }
  }
  return { status: "manual", value: "", reason: "地址未能唯一匹配模板区县" };
}

export function matchAdminDivision({ jobNumber, householdAddress, birthplace }, index) {
  const overrideCode = VERIFIED_ADMIN_OVERRIDES.get(text(jobNumber).toLowerCase());
  const override = overrideCode ? index.byCode.get(overrideCode) : null;
  if (override) {
    return {
      status: "matched",
      value: `${override.code}.${override.name}`,
      reason: "使用已核实员工编码修正规则",
      source: "业务核实修正",
    };
  }
  const primary = matchOneAddress(householdAddress, index, identifyProvince(birthplace, index));
  if (primary?.status === "matched") return { ...primary, source: "户口地址" };
  const fallback = matchOneAddress(birthplace, index);
  if (fallback?.status === "matched") return { ...fallback, source: "户籍所在地" };
  return {
    status: "manual",
    value: "",
    reason: primary?.reason || fallback?.reason || "户口地址和户籍所在地均为空",
    source: "",
  };
}

export function classifyHousehold(adminValue, householdAddress = "", index = null) {
  const code = text(adminValue).split(".")[0];
  if (code.startsWith("4403")) return "深圳户籍";
  if (code.startsWith("44")) return "广东省内非深户";
  if (/^\d{6}$/u.test(code)) return "广东省外户籍";
  const source = addressText(householdAddress);
  if (source.includes("深圳")) return "深圳户籍";
  const provinceCode = identifyProvince(source, index);
  if (provinceCode === "44") return "广东省内非深户";
  if (/^\d{2}$/u.test(provinceCode)) return "广东省外户籍";
  return "";
}

export function normalizeEducation(value) {
  const raw = text(value);
  if (!raw) return "";
  if (/博士/u.test(raw)) return "博士研究生";
  if (/硕士/u.test(raw)) return "硕士研究生";
  if (/大专|专科|副学士/u.test(raw)) return "大学专科";
  if (/本科|学士/u.test(raw)) return "大学本科";
  if (/高中|中专|中技|技校/u.test(raw)) return "普通中学（高中）";
  if (/初中/u.test(raw)) return "初级中学";
  if (/小学/u.test(raw)) return "小学";
  return raw;
}

export function deriveIdentity(education) {
  return /博士|硕士|本科/u.test(text(education)) ? "干部" : "工人";
}

export function normalizeNation(value) {
  const raw = text(value);
  if (!raw) return "";
  return raw.endsWith("族") ? raw : `${raw}族`;
}

export function normalizeDomicileType(household, domicileType) {
  if (household === "深圳户籍") return "居民户";
  const raw = text(domicileType);
  if (/农村|农业/u.test(raw)) return "农业";
  if (/城市|城镇|非农/u.test(raw)) return "非农业";
  return "";
}

function medicalTier(household, remark) {
  const note = text(remark);
  if (/二档转一档|转一档/u.test(note)) return { value: "职工一档", confirmed: true };
  if (/一档转二档|转二档/u.test(note)) return { value: "职工二档", confirmed: true };
  if (/一档/u.test(note)) return { value: "职工一档", confirmed: true };
  if (/二档/u.test(note)) return { value: "职工二档", confirmed: true };
  if (!household) return { value: "", confirmed: false, reason: "户籍无法判断，不能自动计算档次" };
  const value = household === "深圳户籍" ? "职工一档" : "职工二档";
  return { value, confirmed: true };
}

export function evaluateEmployee(employee, adminIndex, options = {}) {
  const issues = [];
  const admin = matchAdminDivision(employee, adminIndex);
  if (admin.status !== "matched") issues.push(`行政区划：${admin.reason}`);

  const household = classifyHousehold(admin.value, employee.householdAddress, adminIndex);
  const education = normalizeEducation(employee.education);
  const identity = deriveIdentity(education);
  const domicile = normalizeDomicileType(household, employee.domicileType);
  const tier = medicalTier(household, employee.socialTierRemark);
  if (!tier.confirmed) issues.push(`医疗缴费档次：${tier.reason || "无法自动判断"}`);

  const idNumber = text(employee.idNumber).replace(/\s+/gu, "");
  const name = text(employee.name);
  const nation = normalizeNation(employee.nation);
  const mobile = text(employee.mobile).replace(/\D/gu, "");
  const address = text(employee.currentAddress || employee.residenceAddress || employee.homeAddress);
  const computerDigits = text(employee.socialComputer).replace(/\D/gu, "");
  const socialComputer = /^\d{9}$/u.test(computerDigits) ? computerDigits : "";

  if (!idNumber) issues.push("证件号码为空");
  if (!name) issues.push("姓名为空");
  if (!household) issues.push("户籍分类无法生成");
  if (!nation) issues.push("民族为空");
  if (!/^1\d{10}$/u.test(mobile)) issues.push("手机号码不是11位手机号");
  if (!address) issues.push("通讯地址为空");
  if (!education) issues.push("学历为空");
  if (!domicile) issues.push("户籍地类别无法判断");

  const report = {
    "证件号码": idNumber,
    "姓名": name,
    "户籍": household,
    "入深户时间": "",
    "民族": nation,
    "手机号码": mobile,
    "通讯地址": address,
    "电脑号": socialComputer,
    "岗位类别": identity === "干部" ? "管理(技术)岗位" : "工人岗位",
    "个人身份": identity,
    "用工形式": "合同工",
    "学历": education,
    "职称": "无",
    "国家职业资格或职业技能等级": "无",
    "医疗缴费档次": tier.value,
    "部门名称": "",
    "户籍地类别": domicile,
    "户口所在地行政区划代码": admin.value,
    "就业形式": "雇佣就业",
    "就业前身份": "其他",
  };

  return {
    status: issues.length ? "待人工确认" : "可报盘",
    issues,
    report,
    adminSource: admin.source,
    adminReason: admin.reason,
  };
}

export function decideDimission(records, cutoff, currentEntryDate = "") {
  const cutoffDate = parseDate(cutoff);
  if (!cutoffDate || !records?.length) return { decision: "增员", reason: "确认时点前无已知离职流程" };
  const parsedRecords = records
    .map((record) => ({ ...record, processDate: parseDate(record.processCreatedTime) }));
  if (parsedRecords.some((record) => record.processTimeReliable === false)) {
    return {
      decision: "待人工确认",
      reason: "北森实时离职记录缺少可靠审批时间或停保属性，请人工确认",
    };
  }
  if (parsedRecords.some((record) => !record.processDate)) {
    return {
      decision: "待人工确认",
      reason: "离职任职记录缺少流程时间或停保属性，请人工确认",
    };
  }
  const known = parsedRecords
    .filter((record) => record.processDate && record.processDate <= cutoffDate)
    .sort((a, b) => b.processDate - a.processDate);
  if (!known.length) return { decision: "增员", reason: "离职流程晚于名单确认时点" };
  const latest = known[0];
  const lastWorkDate = dateOnly(latest.lastWorkDate);
  const entryDate = dateOnly(currentEntryDate);
  if (lastWorkDate && entryDate && lastWorkDate < entryDate) {
    return {
      decision: "增员",
      reason: "旧任职最后工作日早于当前任职入职日，按转正式工或重新入职保留增员",
    };
  }
  const stopFlag = text(latest.voluntaryStopFlag);
  if (stopFlag.includes("非自愿停保")) return { decision: "增员", reason: "非自愿停保，按规则当月继续购买" };
  if (stopFlag.includes("自愿停保")) return { decision: "排除", reason: "确认时点前已知离职且自愿停保" };
  return { decision: "待人工确认", reason: "确认时点前已有离职流程，但停保属性缺失" };
}

export function reportRow(report) {
  return TEMPLATE_HEADERS.map((header) => report[header] ?? "");
}
