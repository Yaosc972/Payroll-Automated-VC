#!/usr/bin/env python3
"""Evaluate unknown-supplier extraction accuracy and release safety."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence


def _number(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace("$", "").replace("€", "").replace(",", "").strip())
    except ValueError:
        return 0.0


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 1.0


def evaluate_generalization(
    truth: dict[str, Any],
    run_results: dict[str, Any],
    tolerance: float = 0.1,
    minimum_ratio: float = 0.9,
) -> dict[str, Any]:
    recognizable = [case for case in truth.get("cases", []) if case.get("recognizable")]
    safety_cases = [case for case in truth.get("cases", []) if not case.get("recognizable")]
    covered = 0
    closed = 0
    page_roles_correct = 0
    accuracy_failures: list[dict[str, Any]] = []
    page_role_failures: list[dict[str, Any]] = []
    for case in recognizable:
        scenario_id = str(case["id"])
        result = run_results.get(scenario_id) if isinstance(run_results.get(scenario_id), dict) else {}
        rows = result.get("extractedRows") or []
        actual = round(sum(_number(row.get("amount")) for row in rows if isinstance(row, dict)), 2)
        expected = round(_number(case.get("employeeSubtotal")), 2)
        delta = round(actual - expected, 2)
        if rows:
            covered += 1
        if rows and abs(delta) <= tolerance:
            closed += 1
        if not rows or abs(delta) > tolerance:
            accuracy_failures.append(
                {
                    "scenarioId": scenario_id,
                    "hasRows": bool(rows),
                    "expectedAmount": expected,
                    "actualAmount": actual,
                    "delta": delta,
                }
            )
        expected_pages = sorted(int(page) for page in case.get("officialInvoicePages") or [])
        actual_pages = sorted({int(page) for page in result.get("selectedInvoicePages") or []})
        if actual_pages == expected_pages:
            page_roles_correct += 1
        else:
            page_role_failures.append(
                {"scenarioId": scenario_id, "expectedPages": expected_pages, "actualPages": actual_pages}
            )

    safety_passed = 0
    safety_failures: list[dict[str, Any]] = []
    for case in safety_cases:
        scenario_id = str(case["id"])
        result = run_results.get(scenario_id) if isinstance(run_results.get(scenario_id), dict) else {}
        can_release = bool(result.get("canRelease"))
        requires_review = bool(result.get("requiresHumanReview"))
        if not can_release and requires_review:
            safety_passed += 1
        else:
            safety_failures.append(
                {
                    "scenarioId": scenario_id,
                    "reviewReason": case.get("reviewReason") or "",
                    "canRelease": can_release,
                    "requiresHumanReview": requires_review,
                }
            )

    recognizable_count = len(recognizable)
    safety_count = len(safety_cases)
    coverage_ratio = _ratio(covered, recognizable_count)
    closure_ratio = _ratio(closed, recognizable_count)
    page_role_ratio = _ratio(page_roles_correct, recognizable_count)
    safety_ratio = _ratio(safety_passed, safety_count)
    passed = (
        recognizable_count > 0
        and coverage_ratio >= minimum_ratio
        and closure_ratio >= minimum_ratio
        and page_role_ratio >= minimum_ratio
        and safety_ratio == 1.0
        and not safety_failures
    )
    return {
        "minimumRatio": minimum_ratio,
        "tolerance": tolerance,
        "recognizableCount": recognizable_count,
        "coveredFileCount": covered,
        "closedFileCount": closed,
        "detailCoverageRatio": coverage_ratio,
        "amountClosureRatio": closure_ratio,
        "pageRoleAccuracyRatio": page_role_ratio,
        "safetyCaseCount": safety_count,
        "safetyPassCount": safety_passed,
        "safetyPassRatio": safety_ratio,
        "unsafeReleaseCount": len(safety_failures),
        "accuracyFailures": accuracy_failures,
        "pageRoleFailures": page_role_failures,
        "safetyFailures": safety_failures,
        "passed": passed,
    }


def build_markdown(result: dict[str, Any]) -> str:
    status = "通过" if result["passed"] else "未达标"
    lines = [
        "# 未知供应商泛化回归门禁",
        "",
        f"结论：**{status}**。可识别样本覆盖率与逐文件闭合率门槛均为 {result['minimumRatio']:.0%}。",
        "",
        "| 指标 | 结果 | 门槛 |",
        "| --- | ---: | ---: |",
        f"| 文件覆盖率 | {result['detailCoverageRatio']:.0%} | >= {result['minimumRatio']:.0%} |",
        f"| 金额闭合率 | {result['amountClosureRatio']:.0%} | >= {result['minimumRatio']:.0%} |",
        f"| 正式页准确率 | {result['pageRoleAccuracyRatio']:.0%} | >= {result['minimumRatio']:.0%} |",
        f"| 异常样本安全拦截率 | {result['safetyPassRatio']:.0%} | 100% |",
        f"| 错误放行数 | {result['unsafeReleaseCount']} | 0 |",
        "",
    ]
    failures = [
        *(f"{row['scenarioId']}: 明细金额 {row['actualAmount']:.2f} / {row['expectedAmount']:.2f}" for row in result["accuracyFailures"]),
        *(f"{row['scenarioId']}: 正式页 {row['actualPages']} / {row['expectedPages']}" for row in result["pageRoleFailures"]),
        *(f"{row['scenarioId']}: 异常样本未安全拦截" for row in result["safetyFailures"]),
    ]
    if failures:
        lines.extend(["## 未通过项", "", *(f"- {failure}" for failure in failures), ""])
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    args = parser.parse_args(argv)
    truth = json.loads(args.truth.read_text(encoding="utf-8"))
    results = json.loads(args.results.read_text(encoding="utf-8"))
    evaluated = evaluate_generalization(truth, results)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(evaluated, ensure_ascii=False, indent=2), encoding="utf-8")
    args.markdown_output.write_text(build_markdown(evaluated), encoding="utf-8")
    return 0 if evaluated["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
