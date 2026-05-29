"""Enhanced quality scoring for labor extraction and comparison.

Provides detailed quality metrics including:
- Confidence distribution analysis
- Name matching quality scoring
- Extraction method success tracking
- Per-warehouse quality breakdown
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List

from .models import LaborLineItem


def calculate_extraction_quality(
    pdf_rows: List[LaborLineItem],
    comparison_summary: Dict[str, Any],
    warehouse_comparison: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Calculate comprehensive extraction quality metrics.

    Returns a quality assessment with:
    - level: 'ok', 'warning', or 'critical'
    - message: Human-readable summary
    - issues: List of detailed issue descriptions
    - metrics: Detailed quality metrics for analysis
    """
    issues: List[str] = []
    metrics: Dict[str, Any] = {}

    # === Confidence Distribution ===
    if pdf_rows:
        confidences = [item.confidence for item in pdf_rows]
        avg_confidence = sum(confidences) / len(confidences)
        low_confidence_count = sum(1 for c in confidences if c < 0.85)
        very_low_confidence_count = sum(1 for c in confidences if c < 0.5)

        metrics["confidence"] = {
            "average": round(avg_confidence, 3),
            "lowCount": low_confidence_count,
            "veryLowCount": very_low_confidence_count,
            "totalCount": len(pdf_rows),
        }

        if very_low_confidence_count > 0:
            issues.append(f"{very_low_confidence_count} 条记录置信度极低 (<0.5)，建议重点复核。")
        elif low_confidence_count > len(pdf_rows) * 0.2:
            issues.append(f"{low_confidence_count} 条记录置信度较低 (<0.85)，占比 {low_confidence_count/len(pdf_rows)*100:.0f}%。")

    # === Extraction Method Analysis ===
    if pdf_rows:
        method_counts = defaultdict(int)
        for item in pdf_rows:
            # Infer method from confidence and evidence
            if item.confidence >= 0.95 and item.evidence_text:
                method_counts["rule"] += 1
            elif item.confidence >= 0.85:
                method_counts["ai_text"] += 1
            else:
                method_counts["ai_image"] += 1

        metrics["extractionMethods"] = dict(method_counts)

        # If too many items came from low-confidence methods
        ai_image_count = method_counts.get("ai_image", 0)
        if ai_image_count > len(pdf_rows) * 0.3:
            issues.append(f"{ai_image_count} 条记录来自图片抽取（低置信度），建议检查 PDF 质量。")

    # === Employee Count Comparison ===
    pdf_count = int(comparison_summary.get("pdfEmployeeCount") or 0)
    excel_count = int(comparison_summary.get("excelEmployeeCount") or 0)
    unmatched_pdf = int(comparison_summary.get("unmatchedPdfCount") or 0)
    unmatched_excel = int(comparison_summary.get("unmatchedExcelCount") or 0)

    metrics["employeeCounts"] = {
        "pdf": pdf_count,
        "excel": excel_count,
        "unmatchedPdf": unmatched_pdf,
        "unmatchedExcel": unmatched_excel,
    }

    if excel_count > 0:
        count_diff_pct = abs(pdf_count - excel_count) / excel_count * 100
        if count_diff_pct > 10:
            issues.append(f"PDF员工数 {pdf_count} 与 Excel员工数 {excel_count} 偏差 {count_diff_pct:.0f}%。")

        unmatched_pct = (unmatched_pdf + unmatched_excel) / excel_count * 100
        if unmatched_pct > 25:
            issues.append(f"未匹配员工 {unmatched_pdf + unmatched_excel} 人，占比 {unmatched_pct:.0f}%。")

    # === Amount and Hours Drift ===
    pdf_hours = float(comparison_summary.get("pdfHoursTotal") or 0)
    excel_hours = float(comparison_summary.get("excelHoursTotal") or 0)
    pdf_amount = float(comparison_summary.get("pdfAmountTotal") or 0)
    excel_amount = float(comparison_summary.get("excelAmountTotal") or 0)

    metrics["totals"] = {
        "pdfHours": pdf_hours,
        "excelHours": excel_hours,
        "hoursDelta": round(pdf_hours - excel_hours, 2),
        "pdfAmount": pdf_amount,
        "excelAmount": excel_amount,
        "amountDelta": round(pdf_amount - excel_amount, 2),
    }

    if excel_hours > 0:
        hours_drift_pct = abs(pdf_hours - excel_hours) / excel_hours * 100
        if hours_drift_pct > 10:
            issues.append(f"总工时差异 {round(pdf_hours - excel_hours, 2)}，偏差 {hours_drift_pct:.0f}%。")

    if excel_amount > 0:
        amount_drift_pct = abs(pdf_amount - excel_amount) / excel_amount * 100
        if amount_drift_pct > 10:
            issues.append(f"总金额差异 {round(pdf_amount - excel_amount, 2)}，偏差 {amount_drift_pct:.0f}%。")

    # === Per-Warehouse Quality ===
    if warehouse_comparison and "rows" in warehouse_comparison:
        warehouse_issues = []
        for wh_row in warehouse_comparison["rows"]:
            wh_id = wh_row.get("warehouseId", "")
            wh_status = wh_row.get("matchStatus", "")
            wh_delta = abs(float(wh_row.get("amountDelta") or 0))

            if wh_status != "通过" and wh_delta > 100:
                warehouse_issues.append(f"仓库 {wh_id}: 金额差异 ${wh_delta:.2f}")

        if warehouse_issues:
            metrics["warehouseIssues"] = warehouse_issues
            if len(warehouse_issues) > 3:
                issues.append(f"{len(warehouse_issues)} 个仓库存在较大差异，建议逐个复核。")

    # === Name Matching Quality ===
    if pdf_rows:
        # Analyze name patterns for potential issues
        names = [item.employee_name_raw for item in pdf_rows]
        has_chinese = any(any('一' <= c <= '鿿' for c in name) for name in names)
        has_english = any(any(c.isalpha() and ord(c) < 128 for c in name) for name in names)
        has_mixed = has_chinese and has_english

        metrics["namePatterns"] = {
            "hasChinese": has_chinese,
            "hasEnglish": has_english,
            "hasMixed": has_mixed,
        }

        if has_mixed:
            issues.append("检测到中英文混合姓名，匹配准确率可能受影响。")

    # === Overall Quality Level ===
    if not issues:
        level = "ok"
        message = "抽取质量检查通过。"
    elif any("极低" in issue or "复核" in issue for issue in issues):
        level = "critical"
        message = "抽取质量存在严重问题，必须人工复核。"
    else:
        level = "warning"
        message = "抽取质量存在风险，请复核 PDF 抽取明细后再使用差异报告。"

    return {
        "level": level,
        "message": message,
        "issues": issues,
        "metrics": metrics,
    }


def calculate_quality_score(quality: Dict[str, Any], summary: Dict[str, Any]) -> tuple:
    """Calculate a numeric quality score for comparison.

    Lower tuple values indicate better quality.
    Used to decide whether retry improved the extraction.
    """
    level_penalty = {"ok": 0, "warning": 1, "critical": 2}.get(quality.get("level"), 1)
    issue_count = len(quality.get("issues") or [])
    exception_count = int(summary.get("exceptionCount") or 0)
    unmatched_count = int(summary.get("unmatchedPdfCount") or 0) + int(summary.get("unmatchedExcelCount") or 0)
    amount_delta = abs(float(summary.get("amountDeltaTotal") or 0))

    # Confidence-based penalty
    metrics = quality.get("metrics", {})
    confidence_info = metrics.get("confidence", {})
    low_confidence_penalty = confidence_info.get("veryLowCount", 0) * 2 + confidence_info.get("lowCount", 0)

    return (
        level_penalty,
        issue_count,
        exception_count,
        unmatched_count,
        low_confidence_penalty,
        amount_delta,
    )
