from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bonus_platform.engine.labor.ocr_candidate_rows import extract_rows_from_visual_pages


def build_row_closure_report(
    ocr_report: dict[str, Any],
    expected_totals: dict[str, float],
    *,
    tolerance: float = 0.10,
) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for item in ocr_report.get("results", []):
        file_name = str(item.get("file") or "")
        if item.get("backend") != "rapidocr" or file_name not in expected_totals:
            continue
        pages = [
            {
                "source_file": file_name,
                "page": page.get("page"),
                "visualText": page.get("visualText") or "",
            }
            for page in item.get("pages", [])
        ]
        rows = extract_rows_from_visual_pages(pages, currency="USD")
        detail_amount = round(sum(row.amount for row in rows), 2)
        expected_amount = round(float(expected_totals[file_name]), 2)
        delta = round(detail_amount - expected_amount, 2)
        files.append(
            {
                "file": file_name,
                "rowCount": len(rows),
                "employeeCount": len({row.employee_name_raw.upper() for row in rows}),
                "hours": round(sum(row.hours for row in rows), 2),
                "detailAmount": detail_amount,
                "expectedAmount": expected_amount,
                "delta": delta,
                "closed": abs(delta) <= tolerance,
            }
        )
    closed_count = sum(bool(item["closed"]) for item in files)
    return {
        "source": "labor_ocr_row_closure",
        "formalFlowChanged": False,
        "summary": {
            "evaluatedFileCount": len(files),
            "closedFileCount": closed_count,
            "closureRate": round(closed_count / len(files), 4) if files else 0.0,
            "tolerance": tolerance,
        },
        "files": files,
    }


def write_row_closure_report(report: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "ocr_row_closure.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# 海外劳务 OCR 员工明细闭合报告",
        "",
        "候选结果只用于离线验证，正式核对链路未改变。",
        "",
        "| 文件 | 员工 | 明细行 | 工时 | 明细金额 | 发票总额 | 差额 | 闭合 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in report["files"]:
        lines.append(
            f"| {item['file']} | {item['employeeCount']} | {item['rowCount']} | {item['hours']:.2f} | "
            f"{item['detailAmount']:.2f} | {item['expectedAmount']:.2f} | {item['delta']:.2f} | "
            f"{'通过' if item['closed'] else '待复核'} |"
        )
    (output_dir / "OCR_ROW_CLOSURE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate OCR employee-row amount closure")
    parser.add_argument("--ocr-report", required=True)
    parser.add_argument("--expected-totals", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--tolerance", type=float, default=0.10)
    args = parser.parse_args(argv)
    ocr_report = json.loads(Path(args.ocr_report).read_text(encoding="utf-8"))
    expected_totals = json.loads(Path(args.expected_totals).read_text(encoding="utf-8"))
    report = build_row_closure_report(ocr_report, expected_totals, tolerance=args.tolerance)
    write_row_closure_report(report, Path(args.output_dir))
    print(Path(args.output_dir) / "OCR_ROW_CLOSURE.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
