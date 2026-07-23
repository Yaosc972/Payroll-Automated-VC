#!/usr/bin/env python3
"""Evaluate image-invoice detail coverage and per-file amount closure."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def _number(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace("$", "").replace("€", "").replace(",", "").strip()
    try:
        return float(text)
    except ValueError:
        return 0.0


def _source_name(row: dict) -> str:
    return str(row.get("source_file") or row.get("sourceFile") or "")


def evaluate_run(metadata: dict, *, tolerance: float = 0.1) -> dict[str, Any]:
    totals = {
        _source_name(item): _number(item.get("total_amount") or item.get("totalAmount"))
        for item in (metadata.get("invoiceEvidenceAudit") or [])
        if _source_name(item) and _number(item.get("total_amount") or item.get("totalAmount")) > 0
    }
    rows_by_source: dict[str, list[dict]] = defaultdict(list)
    for row in metadata.get("pdfExtractedRows") or []:
        if _source_name(row):
            rows_by_source[_source_name(row)].append(row)

    covered_files = sorted(source for source in totals if rows_by_source.get(source))
    closed_files = []
    mismatches = []
    for source, expected in sorted(totals.items()):
        actual = round(sum(_number(row.get("amount")) for row in rows_by_source.get(source, [])), 2)
        delta = round(actual - expected, 2)
        if rows_by_source.get(source) and abs(delta) <= tolerance:
            closed_files.append(source)
        elif rows_by_source.get(source):
            mismatches.append({"sourceFile": source, "expectedAmount": expected, "actualAmount": actual, "delta": delta})

    invoice_count = len(totals)
    return {
        "runId": metadata.get("id"),
        "supplierName": metadata.get("supplierName"),
        "status": metadata.get("status"),
        "invoiceFileCount": invoice_count,
        "detailFileCount": len(covered_files),
        "closedFileCount": len(closed_files),
        "detailCoverageRatio": round(len(covered_files) / invoice_count, 4) if invoice_count else 0.0,
        "amountClosureRatio": round(len(closed_files) / invoice_count, 4) if invoice_count else 0.0,
        "coveredFiles": covered_files,
        "closedFiles": closed_files,
        "mismatches": mismatches,
    }


def evaluate_cache_case(case: dict, *, tolerance: float = 0.1) -> dict[str, Any]:
    cache_directory = Path(case["cacheDirectory"])
    expected_totals = {str(key): _number(value) for key, value in case.get("expectedTotals", {}).items()}
    rows_by_source: dict[str, list[dict]] = defaultdict(list)
    for path in cache_directory.glob("*_p*_*.json"):
        source = path.name.split("_p", 1)[0]
        if source not in expected_totals:
            continue
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(rows, list):
            rows_by_source[source].extend(row for row in rows if isinstance(row, dict))

    covered_files = sorted(source for source in expected_totals if rows_by_source.get(source))
    closed_files = []
    mismatches = []
    for source, expected in sorted(expected_totals.items()):
        actual = round(sum(_number(row.get("amount")) for row in rows_by_source.get(source, [])), 2)
        delta = round(actual - expected, 2)
        if rows_by_source.get(source) and abs(delta) <= tolerance:
            closed_files.append(source)
        elif rows_by_source.get(source):
            mismatches.append({"sourceFile": source, "expectedAmount": expected, "actualAmount": actual, "delta": delta})
    invoice_count = len(expected_totals)
    return {
        "runId": "legacy-cache",
        "supplierName": case.get("name"),
        "status": "legacy_cache_candidate",
        "invoiceFileCount": invoice_count,
        "detailFileCount": len(covered_files),
        "closedFileCount": len(closed_files),
        "detailCoverageRatio": round(len(covered_files) / invoice_count, 4) if invoice_count else 0.0,
        "amountClosureRatio": round(len(closed_files) / invoice_count, 4) if invoice_count else 0.0,
        "coveredFiles": covered_files,
        "closedFiles": closed_files,
        "mismatches": mismatches,
    }


def evaluate_artifact_case(case: dict, *, tolerance: float = 0.1) -> dict[str, Any]:
    artifact_path = Path(case["artifactFile"])
    expected_totals = {str(key): _number(value) for key, value in case.get("expectedTotals", {}).items()}
    rows_by_source: dict[str, list[dict]] = defaultdict(list)
    try:
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        artifact = {}
    if isinstance(artifact, dict):
        for filename, result in artifact.items():
            source = Path(str(filename)).stem
            if source not in expected_totals or not isinstance(result, dict):
                continue
            rows = result.get("rows") or []
            rows_by_source[source].extend(row for row in rows if isinstance(row, dict))

    covered_files = sorted(source for source in expected_totals if rows_by_source.get(source))
    closed_files = []
    mismatches = []
    for source, expected in sorted(expected_totals.items()):
        actual = round(sum(_number(row.get("amount")) for row in rows_by_source.get(source, [])), 2)
        delta = round(actual - expected, 2)
        if rows_by_source.get(source) and abs(delta) <= tolerance:
            closed_files.append(source)
        elif rows_by_source.get(source):
            mismatches.append({"sourceFile": source, "expectedAmount": expected, "actualAmount": actual, "delta": delta})
    invoice_count = len(expected_totals)
    return {
        "runId": "current-extraction-artifact",
        "supplierName": case.get("name"),
        "status": "current_candidate",
        "invoiceFileCount": invoice_count,
        "detailFileCount": len(covered_files),
        "closedFileCount": len(closed_files),
        "detailCoverageRatio": round(len(covered_files) / invoice_count, 4) if invoice_count else 0.0,
        "amountClosureRatio": round(len(closed_files) / invoice_count, 4) if invoice_count else 0.0,
        "coveredFiles": covered_files,
        "closedFiles": closed_files,
        "mismatches": mismatches,
    }


def evaluate_cases(cases_path: Path, runs_root: Path) -> dict[str, Any]:
    config = json.loads(cases_path.read_text(encoding="utf-8"))
    results = []
    for case in config["cases"]:
        if case.get("artifactFile"):
            result = evaluate_artifact_case(case)
        elif case.get("cacheDirectory"):
            result = evaluate_cache_case(case)
        else:
            metadata_path = runs_root / case["runId"] / "metadata.json"
            if metadata_path.exists():
                result = evaluate_run(json.loads(metadata_path.read_text(encoding="utf-8")))
            else:
                result = {"runId": case["runId"], "invoiceFileCount": 0, "detailCoverageRatio": 0.0, "amountClosureRatio": 0.0}
        result.update({"name": case["name"], "materialGroup": case["materialGroup"]})
        target = float(case.get("minimumRatio") or config.get("minimumRatio") or 0.9)
        result["minimumRatio"] = target
        result["passed"] = result["detailCoverageRatio"] >= target and result["amountClosureRatio"] >= target
        results.append(result)
    return {
        "minimumRatio": float(config.get("minimumRatio") or 0.9),
        "passed": all(item["passed"] for item in results),
        "cases": results,
    }


def build_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# 图片型发票回归门禁",
        "",
        f"目标：员工明细文件覆盖率和逐文件金额闭合率均达到 {result['minimumRatio']:.0%}。",
        "",
        "| 样本 | 发票 | 明细文件 | 闭合文件 | 覆盖率 | 闭合率 | 结果 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in result["cases"]:
        lines.append(
            f"| {item['name']} | {item['invoiceFileCount']} | {item.get('detailFileCount', 0)} | "
            f"{item.get('closedFileCount', 0)} | {item['detailCoverageRatio']:.0%} | "
            f"{item['amountClosureRatio']:.0%} | {'通过' if item['passed'] else '未达标'} |"
        )
    lines.extend(
        [
            "",
            "说明：覆盖率只表示文件产生员工行；闭合率要求该文件员工金额求和与权威发票总额在 $0.10 内一致。两项必须同时达标。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate_cases(args.cases, args.runs_root)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    args.markdown_output.write_text(build_markdown(result), encoding="utf-8")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
