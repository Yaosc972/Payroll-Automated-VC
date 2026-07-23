#!/usr/bin/env python3
"""Build a read-only accuracy and coverage baseline from local labor materials."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


SUPPORTED_SUFFIXES = {".pdf", ".xlsx", ".xls", ".csv"}
IGNORED_PARTS = {".ai_extract_cache", ".workbuddy", "handover"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pdf_text(path: Path) -> str:
    from pypdf import PdfReader

    return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)


def classify_pdf(path: Path) -> dict[str, Any]:
    try:
        text = _pdf_text(path)
        error = ""
    except Exception as exc:  # A damaged PDF remains coverage evidence.
        text = ""
        error = type(exc).__name__
    character_count = len(re.sub(r"\s+", "", text))
    if character_count < 50:
        text_class = "image_or_empty"
    elif character_count < 500:
        text_class = "sparse_text"
    else:
        text_class = "text_structured"
    return {
        "filename": path.name,
        "textClass": text_class,
        "textCharacterCount": character_count,
        "parserError": error,
    }


def inventory_materials(materials_root: Path) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for path in sorted(materials_root.rglob("*")):
        if (
            not path.is_file()
            or path.suffix.lower() not in SUPPORTED_SUFFIXES
            or any(part in IGNORED_PARTS for part in path.parts)
        ):
            continue
        relative = path.relative_to(materials_root)
        item: dict[str, Any] = {
            "group": relative.parts[0],
            "relativePath": str(relative),
            "suffix": path.suffix.lower(),
            "sizeBytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        if path.suffix.lower() == ".pdf":
            item.update(classify_pdf(path))
        files.append(item)

    hashes = Counter(item["sha256"] for item in files)
    pdfs = [item for item in files if item["suffix"] == ".pdf"]
    groups = []
    for group_name in sorted({item["group"] for item in files}):
        group_files = [item for item in files if item["group"] == group_name]
        group_pdfs = [item for item in group_files if item["suffix"] == ".pdf"]
        groups.append(
            {
                "group": group_name,
                "fileCount": len(group_files),
                "pdfCount": len(group_pdfs),
                "workbookCount": sum(item["suffix"] in {".xlsx", ".xls"} for item in group_files),
                "pdfTextClasses": dict(Counter(item["textClass"] for item in group_pdfs)),
            }
        )
    return {
        "fileCount": len(files),
        "uniqueHashCount": len(hashes),
        "duplicateCopyCount": sum(count - 1 for count in hashes.values()),
        "pdfCount": len(pdfs),
        "pdfTextClasses": dict(Counter(item["textClass"] for item in pdfs)),
        "groups": groups,
        "files": files,
    }


def evaluate_cases(cases_path: Path, runs_root: Path) -> list[dict[str, Any]]:
    cases = json.loads(cases_path.read_text(encoding="utf-8"))["cases"]
    results = []
    for case in cases:
        metadata_path = runs_root / case["runId"] / "metadata.json"
        result = {**case, "metadataFound": metadata_path.exists(), "checks": []}
        if not metadata_path.exists():
            result["passed"] = False
            results.append(result)
            continue
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        summary = metadata.get("comparisonSummary") or {}
        batch_summary = (metadata.get("warehouseComparison") or {}).get("summary") or {}
        guard = metadata.get("batchGuard") or {}
        diagnostics = (metadata.get("reconciliationDiagnostics") or {}).get("signals") or {}
        actual = {
            "status": metadata.get("status"),
            "pdfAmountTotal": batch_summary.get("pdfAmountTotal", summary.get("pdfAmountTotal")),
            "excelAmountTotal": batch_summary.get("excelAmountTotal", summary.get("excelAmountTotal")),
            "amountDeltaTotal": batch_summary.get("amountDeltaTotal", summary.get("amountDeltaTotal")),
            "employeeDetailPdfAmountTotal": summary.get("pdfAmountTotal"),
            "employeeDetailExcelAmountTotal": summary.get("excelAmountTotal"),
            "batchGuardStatus": guard.get("status"),
            "detailCoverageRatio": (diagnostics.get("pdfDetailCoverage") or {}).get("coverageRatio"),
        }
        result["actual"] = actual
        for key, expected in case.get("expected", {}).items():
            observed = actual.get(key)
            passed = abs(observed - expected) <= 0.01 if isinstance(expected, float) else observed == expected
            result["checks"].append({"metric": key, "expected": expected, "actual": observed, "passed": passed})
        result["passed"] = all(check["passed"] for check in result["checks"])
        results.append(result)
    return results


def build_report(inventory: dict[str, Any], cases: list[dict[str, Any]]) -> str:
    text_classes = inventory["pdfTextClasses"]
    lines = [
        "# 海外劳务核对能力基线（2026-07-12）",
        "",
        "## 结论",
        "",
        "- 当前可支持受控内部 UAT，但不能宣称对未知供应商全面准确。",
        "- 文本型发票已有较强结构化核对能力；图片型发票仍是主要上线缺口。",
        "- 未经业务审核的历史批次只计覆盖率，不计准确率。",
        "",
        "## 材料覆盖",
        "",
        f"- 原始材料组：{len(inventory['groups'])}",
        f"- 文件：{inventory['fileCount']}，唯一哈希：{inventory['uniqueHashCount']}，重复副本：{inventory['duplicateCopyCount']}",
        f"- PDF：{inventory['pdfCount']}，文本结构型：{text_classes.get('text_structured', 0)}，文本稀疏：{text_classes.get('sparse_text', 0)}，无文本层/图片型：{text_classes.get('image_or_empty', 0)}",
        "",
        "| 材料组 | PDF | Excel | PDF 类型 | 真值状态 |",
        "| --- | ---: | ---: | --- | --- |",
    ]
    reviewed_groups = {case["materialGroup"] for case in cases}
    for group in inventory["groups"]:
        truth = "工程复核样本" if group["group"] in reviewed_groups else "待业务审核，仅覆盖"
        classes = "，".join(f"{key}:{value}" for key, value in sorted(group["pdfTextClasses"].items())) or "-"
        lines.append(f"| {group['group']} | {group['pdfCount']} | {group['workbookCount']} | {classes} | {truth} |")
    lines.extend(["", "## 已复核回归", ""])
    for case in cases:
        state = "通过" if case["passed"] else "失败"
        actual = case.get("actual") or {}
        lines.extend(
            [
                f"### {case['name']}：{state}",
                "",
                f"- PDF/Excel/差额：{actual.get('pdfAmountTotal')} / {actual.get('excelAmountTotal')} / {actual.get('amountDeltaTotal')}",
                f"- 明细覆盖率：{actual.get('detailCoverageRatio')}",
                f"- 批次门禁：{actual.get('batchGuardStatus')}；状态：{actual.get('status')}",
                f"- 证据等级：{case['evidenceLevel']}",
                "",
            ]
        )
    lines.extend(
        [
            "## 上线门槛判断",
            "",
            "1. 文本型未知供应商：允许 UAT，但必须满足金额闭合、币种一致、仓库归属唯一和差异留痕。",
            "2. 图片型未知供应商：当前只允许人工复核流程，不允许系统自动放行。",
            "3. 发布口径：准确率只统计业务确认或独立人工复算样本；其余材料只统计解析覆盖率。",
            "4. 下一优先级：提升图片型发票员工明细覆盖，并让前端明确显示整批明细覆盖率。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--materials-root", type=Path, required=True)
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    args = parser.parse_args()
    inventory = inventory_materials(args.materials_root)
    cases = evaluate_cases(args.cases, args.runs_root)
    payload = {"inventory": inventory, "cases": cases}
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    args.markdown_output.write_text(build_report(inventory, cases), encoding="utf-8")
    return 0 if all(case["passed"] for case in cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
