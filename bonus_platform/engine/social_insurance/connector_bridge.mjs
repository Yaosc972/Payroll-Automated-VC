#!/usr/bin/env node
import path from "node:path";
import { pathToFileURL } from "node:url";

import { ensureLocalBeisenCredentials } from "./local_beisen_credentials.mjs";

process.umask(0o077);

async function main() {
  const [engineDir, operation, payloadJson] = process.argv.slice(2);
  if (!engineDir || !operation || !payloadJson) throw new Error("缺少北森本地连接器参数");
  if (!["subjects", "sync"].includes(operation)) throw new Error("不支持的北森本地连接器操作");
  ensureLocalBeisenCredentials();
  const service = await import(pathToFileURL(path.join(engineDir, "lib", "service.mjs")).href);
  const payload = JSON.parse(payloadJson);
  const handler = operation === "subjects" ? service.listSubjects : service.syncCandidates;
  if (typeof handler !== "function") throw new Error("本地北森连接器缺少业务入口");
  const result = await handler(payload);
  process.stdout.write(`${JSON.stringify(result)}\n`);
}

main().catch((error) => {
  process.stderr.write(`${JSON.stringify({ error: String(error?.message || "北森本地连接器执行失败") })}\n`);
  process.exitCode = 1;
});
