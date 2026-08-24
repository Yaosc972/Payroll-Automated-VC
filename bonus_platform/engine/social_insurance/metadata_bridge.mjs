#!/usr/bin/env node
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

process.umask(0o077);

async function main() {
  const [engineDir, templatePath] = process.argv.slice(2);
  if (!engineDir || !templatePath) throw new Error("缺少政务模板字典参数");
  const spreadsheetModule = await import(pathToFileURL(path.join(engineDir, "lib", "spreadsheet-io.mjs")).href);
  const { convertTemplateToXlsx, readAdminDictionary } = spreadsheetModule;
  let convertedPath = templatePath;
  try {
    if (path.extname(templatePath).toLowerCase() === ".xls") {
      convertedPath = await convertTemplateToXlsx(templatePath);
    }
    const values = await readAdminDictionary(convertedPath);
    process.stdout.write(JSON.stringify({ administrativeDivisions: values }) + "\n");
  } finally {
    const convertedDir = path.dirname(convertedPath);
    if (convertedPath !== templatePath && path.basename(convertedDir).startsWith("social-insurance-template-")) {
      await fs.rm(convertedDir, { recursive: true, force: true });
    }
  }
}

main().catch((error) => {
  process.stderr.write(JSON.stringify({ completed: false, error: String(error?.message || "政务模板字典读取失败") }) + "\n");
  process.exitCode = 1;
});
