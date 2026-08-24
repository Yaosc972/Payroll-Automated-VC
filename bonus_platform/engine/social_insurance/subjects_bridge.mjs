#!/usr/bin/env node
import path from "node:path";
import { pathToFileURL } from "node:url";

process.umask(0o077);

async function main() {
  const [engineDir, modifiedStart, modifiedStop, entryStart, entryEnd] = process.argv.slice(2);
  if (!engineDir || !modifiedStart || !modifiedStop || !entryStart || !entryEnd) {
    throw new Error("缺少合同主体枚举参数");
  }
  const clientModule = await import(pathToFileURL(path.join(engineDir, "lib", "beisen-client.mjs")).href);
  const rulesModule = await import(pathToFileURL(path.join(engineDir, "lib", "rules.mjs")).href);
  const { BeisenClient, BEISEN_FIELDS } = clientModule;
  const { fieldValue, inDateRange, isAllowedCandidateProfile } = rulesModule;
  const client = new BeisenClient();
  try {
    const rows = await client.getChangedEmployees(modifiedStart, modifiedStop);
    const candidateUserIds = new Set();
    for (const row of rows) {
      const employee = row?.employeeInfo ?? {};
      const userId = Number(employee.userID);
      if (!Number.isFinite(userId)) continue;
      const services = Array.isArray(row?.recordInfoList) ? row.recordInfoList : [];
      const virtualEmployee = fieldValue(
        employee,
        BEISEN_FIELDS.EMPLOYEE_CUSTOM.virtualEmployee,
      );
      const eligible = services.some((service) => {
        const employment = fieldValue(service, "employType");
        const entryDate = fieldValue(service, "entryDate", { translated: false });
        return isAllowedCandidateProfile({ employType: employment, virtualEmployee })
          && inDateRange(entryDate, entryStart, entryEnd);
      });
      if (eligible) candidateUserIds.add(userId);
    }

    const contracts = await client.getContracts([...candidateUserIds]);
    const options = new Map();
    for (const userId of candidateUserIds) {
      const seenForEmployee = new Set();
      for (const contract of contracts.get(userId) ?? []) {
        const name = fieldValue(contract, "firstPartyCode") || fieldValue(contract, "firstParty");
        const code = fieldValue(contract, "firstPartyCode", { translated: false });
        const value = name || code;
        const key = code || value;
        if (!value || seenForEmployee.has(key)) continue;
        seenForEmployee.add(key);
        const current = options.get(key) ?? { value, label: value, code, candidateCount: 0 };
        current.candidateCount += 1;
        options.set(key, current);
      }
    }
    process.stdout.write(JSON.stringify({ subjects: [...options.values()] }) + "\n");
  } finally {
    client.clear();
  }
}

main().catch((error) => {
  process.stderr.write(JSON.stringify({ completed: false, error: String(error?.message || "合同主体枚举失败") }) + "\n");
  process.exitCode = 1;
});
