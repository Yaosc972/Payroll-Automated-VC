#!/usr/bin/env node
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

process.umask(0o077);

async function main() {
  const [engineDir, templatePath, rowsPath, outputDir] = process.argv.slice(2);
  if (!engineDir || !templatePath || !rowsPath || !outputDir) {
    throw new Error("缺少报盘生成参数");
  }
  const spreadsheetModule = path.join(engineDir, "lib", "spreadsheet-io.mjs");
  const { buildReportWorkbook, convertTemplateToXlsx, convertXlsxToXls, readUnitIdFromReport } = await import(
    pathToFileURL(spreadsheetModule).href
  );
  const payload = JSON.parse(await fs.readFile(rowsPath, "utf8"));
  if (!Array.isArray(payload.readyRows) || payload.readyRows.length === 0) {
    throw new Error("没有已确认的报盘人员");
  }
  await fs.mkdir(outputDir, { recursive: true, mode: 0o700 });
  await fs.chmod(outputDir, 0o700);
  const convertedTemplate = await convertTemplateToXlsx(templatePath);
  const unitId = await readUnitIdFromReport(convertedTemplate);
  if (!unitId) throw new Error("政务模板缺少单位编号");
  const xlsxPath = path.join(outputDir, "深圳社保增员_报盘.xlsx");
  await buildReportWorkbook({
    convertedTemplatePath: convertedTemplate,
    outputPath: xlsxPath,
    unitId,
    readyRows: payload.readyRows,
  });
  const xlsPath = convertXlsxToXls(xlsxPath, outputDir);
  await fs.chmod(xlsxPath, 0o600);
  await fs.chmod(xlsPath, 0o600);
  process.stdout.write(JSON.stringify({
    completed: true,
    xlsx: path.basename(xlsxPath),
    xls: path.basename(xlsPath),
    employeeCount: payload.readyRows.length,
  }) + "\n");
}

main().catch((error) => {
  process.stderr.write(JSON.stringify({ completed: false, error: String(error?.message || "报盘生成失败") }) + "\n");
  process.exitCode = 1;
});
