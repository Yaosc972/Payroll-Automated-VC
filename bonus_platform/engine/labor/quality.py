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


def build_reconciliation_diagnostics(
    *,
    pdf_totals: List[Dict[str, Any]] | None,
    comparison_summary: Dict[str, Any],
    warehouse_comparison: Dict[str, Any] | None,
    cost_summaries: List[Dict[str, Any]] | None = None,
    amount_tolerance: float = 0.1,
) -> Dict[str, Any]:
    """Explain whether reconciliation signals agree with each other.

    This is intentionally business-facing: it identifies unstable signals that
    would make a result untrustworthy even if a downstream employee comparison
    happens to align.
    """
    pdf_totals = pdf_totals or []
    cost_summaries = cost_summaries or []
    wc_summary = (warehouse_comparison or {}).get("summary", {})
    wc_errors = (warehouse_comparison or {}).get("errors", []) or []

    fast_pdf_total = round(sum(float(t.get("total_amount") or 0) for t in pdf_totals), 2)
    employee_pdf_total = round(float(comparison_summary.get("pdfAmountTotal") or 0), 2)
    excel_total = round(
        float(wc_summary.get("excelAmountTotal") or comparison_summary.get("excelAmountTotal") or 0),
        2,
    )

    issues: List[Dict[str, Any]] = []
    missing_warehouse = sorted(
        {
            str(t.get("source_file") or "")
            for t in pdf_totals
            if t.get("source_file") and not str(t.get("warehouse_id") or "").strip()
        }
    )
    safely_attributed_single_warehouse = (
        len(pdf_totals) == 1
        and len(missing_warehouse) == 1
        and not wc_errors
        and int(wc_summary.get("warehouseCount") or 0) == 1
    )
    zero_total_files = sorted(
        {
            str(t.get("source_file") or "")
            for t in pdf_totals
            if t.get("source_file") and float(t.get("total_amount") or 0) == 0
        }
    )

    if missing_warehouse and not safely_attributed_single_warehouse:
        issues.append(
            {
                "code": "missing_warehouse_id",
                "level": "warning",
                "title": "部分 PDF 未识别仓库号",
                "message": "系统无法稳定按仓库定位这些发票，仓库维度核对可能失真。",
                "items": missing_warehouse[:12],
            }
        )

    if zero_total_files:
        issues.append(
            {
                "code": "zero_pdf_total",
                "level": "critical",
                "title": "部分 PDF 总金额抽取为 0",
                "message": "这些发票的总金额信号没有被可靠读取，不能直接放行。",
                "items": zero_total_files[:12],
            }
        )

    if fast_pdf_total > 0 and employee_pdf_total > 0:
        delta = round(fast_pdf_total - employee_pdf_total, 2)
        if abs(delta) > amount_tolerance:
            issues.append(
                {
                    "code": "pdf_total_conflict",
                    "level": "critical",
                    "title": "PDF 总额信号互相冲突",
                    "message": (
                        f"快速总额为 ${fast_pdf_total:,.2f}，员工明细求和为 "
                        f"${employee_pdf_total:,.2f}，差异 ${abs(delta):,.2f}。"
                    ),
                    "items": ["优先复核 Totals/GRAND TOTAL 是否被误读，尤其是逾期付款金额。"],
                }
            )

    if wc_errors:
        sample_errors = [str(err) for err in wc_errors[:8]]
        issues.append(
            {
                "code": "warehouse_mapping_errors",
                "level": "warning",
                "title": "仓库映射过程存在异常",
                "message": "系统在仓库号定位时遇到异常，建议先按仓库汇总复核。",
                "items": sample_errors,
            }
        )

    offsetting_warehouse_deltas = _build_offsetting_warehouse_delta_signals(
        (warehouse_comparison or {}).get("rows", []) or [],
        amount_tolerance,
    )
    if offsetting_warehouse_deltas:
        net_delta = round(sum(float(item.get("amountDelta") or 0) for item in offsetting_warehouse_deltas), 2)
        items = [
            (
                f"仓库 {item['warehouseId']}: PDF ${item['pdfAmountTotal']:,.2f}，"
                f"Excel ${item['excelAmountTotal']:,.2f}，差异 ${item['amountDelta']:,.2f}"
            )
            for item in offsetting_warehouse_deltas[:8]
        ]
        issues.append(
            {
                "code": "warehouse_offsetting_deltas",
                "level": "warning",
                "title": "仓库差异互相抵消",
                "message": f"多个仓库分别超出容差，但合计差异仅 ${net_delta:,.2f}，可能是跨仓员工分摊或仓库归属不一致。",
                "items": items,
            }
        )

    employee_attribution = _build_employee_attribution_signals(
        (warehouse_comparison or {}).get("rows", []) or [],
        amount_tolerance,
    )
    if employee_attribution:
        items = [
            (
                f"仓库 {item['warehouseId']}: {item['employeeName']} 贡献差异 "
                f"${item['delta']:,.2f}，仓库总差异 ${item['warehouseDelta']:,.2f}"
            )
            for item in employee_attribution[:8]
        ]
        issues.append(
            {
                "code": "warehouse_employee_attribution",
                "level": "warning",
                "title": "仓库差异集中在少数员工",
                "message": "仓库金额差异主要由少数员工贡献，建议优先复核这些员工的工时、费率或补充费用。",
                "items": items,
            }
        )

    allocation_issues = list((warehouse_comparison or {}).get("allocationIssues", []) or [])
    if allocation_issues:
        items = [
            (
                f"{item.get('employeeName', '')}: "
                + "；".join(
                    f"仓库 {row.get('warehouseId', '')} 差异 ${float(row.get('amountDelta') or 0):,.2f}"
                    for row in (item.get("warehouses", []) or [])[:4]
                )
            )
            for item in allocation_issues[:8]
        ]
        issues.append(
            {
                "code": "cross_warehouse_employee_allocation",
                "level": "warning",
                "title": "员工跨仓库金额抵消",
                "message": "员工汇总金额可通过，但同一员工在不同仓库存在正负差异，说明仓库归属或分摊口径需要复核。",
                "items": items,
            }
        )

    amount_basis = _build_amount_basis_signals(pdf_totals, cost_summaries, amount_tolerance)
    basis_mismatches = [item for item in amount_basis if abs(float(item.get("pdfVsReportedDelta") or 0)) > amount_tolerance]
    if basis_mismatches:
        items = [
            (
                f"仓库 {item['warehouseId']}: PDF ${item['pdfTotal']:,.2f}，"
                f"OTWS汇总 ${item['reportedTotal']:,.2f}，差异 ${item['pdfVsReportedDelta']:,.2f}；"
                f"员工薪资 ${item['employeeExpenses']:,.2f}，补充费用 ${item['employeeBenefits']:,.2f}，"
                f"证据 {item['summaryEvidence']}"
            )
            for item in basis_mismatches[:8]
        ]
        issues.append(
            {
                "code": "amount_basis_mismatch",
                "level": "warning",
                "title": "PDF 总额与账单费用口径不一致",
                "message": "账单内部费用组成已闭合，但 PDF 发票总额与 OTWS 汇总总额不同，需确认供应商发票是否包含额外费用、抵扣或调整项。",
                "items": items,
            }
        )

    blocking = any(issue["level"] == "critical" for issue in issues)
    level = "critical" if blocking else "warning" if issues else "ok"
    if level == "ok":
        message = "核对信号稳定。"
        next_step = "可按当前结论使用报告。"
    elif blocking:
        message = "核对信号存在冲突，不能直接放行。"
        next_step = "先复核总金额来源，再按仓库和员工明细下钻。"
    else:
        message = "核对信号有不稳定项，建议复核。"
        next_step = "先看异常仓库和未识别来源，再决定是否放行。"

    return {
        "level": level,
        "message": message,
        "nextStep": next_step,
        "signals": {
            "fastPdfTotal": fast_pdf_total,
            "employeePdfTotal": employee_pdf_total,
            "excelTotal": excel_total,
            "warehouseTotal": round(float(wc_summary.get("pdfAmountTotal") or 0), 2),
            "amountBasis": amount_basis,
            "offsettingWarehouseDeltas": offsetting_warehouse_deltas,
            "employeeAttribution": employee_attribution,
            "crossWarehouseEmployeeAllocation": allocation_issues,
        },
        "issues": issues,
    }


def _build_employee_attribution_signals(
    warehouse_rows: List[Dict[str, Any]],
    amount_tolerance: float,
) -> List[Dict[str, Any]]:
    signals: List[Dict[str, Any]] = []
    for row in warehouse_rows:
        warehouse_delta = round(float(row.get("amountDelta") or 0), 2)
        if abs(warehouse_delta) <= amount_tolerance:
            continue
        attribution = row.get("attribution", []) or []
        concrete = [
            item for item in attribution
            if item.get("employeeName") and item.get("pdfAmount") is not None and item.get("excelAmount") is not None
        ]
        if not concrete:
            continue
        concrete.sort(key=lambda item: abs(float(item.get("delta") or 0)), reverse=True)
        top = concrete[0]
        top_delta = round(float(top.get("delta") or 0), 2)
        if abs(top_delta) < max(amount_tolerance, abs(warehouse_delta) * 0.8):
            continue
        signals.append(
            {
                "warehouseId": str(row.get("warehouseId") or ""),
                "employeeName": str(top.get("employeeName") or ""),
                "pdfAmount": round(float(top.get("pdfAmount") or 0), 2),
                "excelAmount": round(float(top.get("excelAmount") or 0), 2),
                "delta": top_delta,
                "warehouseDelta": warehouse_delta,
            }
        )
    return signals


def _build_offsetting_warehouse_delta_signals(
    warehouse_rows: List[Dict[str, Any]],
    amount_tolerance: float,
) -> List[Dict[str, Any]]:
    diff_rows = [
        row
        for row in warehouse_rows
        if abs(float(row.get("amountDelta") or 0)) > amount_tolerance
    ]
    if len(diff_rows) < 2:
        return []
    net_delta = round(sum(float(row.get("amountDelta") or 0) for row in diff_rows), 2)
    if abs(net_delta) > amount_tolerance:
        return []
    return [
        {
            "warehouseId": str(row.get("warehouseId") or ""),
            "pdfAmountTotal": round(float(row.get("pdfAmountTotal") or 0), 2),
            "excelAmountTotal": round(float(row.get("excelAmountTotal") or 0), 2),
            "amountDelta": round(float(row.get("amountDelta") or 0), 2),
            "attribution": row.get("attribution", []) or [],
        }
        for row in diff_rows
    ]


def _build_amount_basis_signals(
    pdf_totals: List[Dict[str, Any]],
    cost_summaries: List[Dict[str, Any]],
    amount_tolerance: float,
) -> List[Dict[str, Any]]:
    pdf_by_warehouse = {
        str(item.get("warehouse_id") or "").strip(): round(float(item.get("total_amount") or 0), 2)
        for item in pdf_totals
        if str(item.get("warehouse_id") or "").strip()
    }
    signals: List[Dict[str, Any]] = []
    for summary in cost_summaries:
        warehouse_id = str(summary.get("warehouseId") or "").strip()
        if not warehouse_id:
            continue
        summary_section = summary.get("summary") or {}
        details = summary.get("details") or {}
        employee_expenses = details.get("employeeExpenses") or {}
        employee_benefits = details.get("employeeBenefits") or {}
        loading = details.get("loadingAndUnloading") or {}
        pdf_total = pdf_by_warehouse.get(warehouse_id, 0.0)
        reported_total = round(float(summary_section.get("reportedTotal") or 0), 2)
        detail_total = round(float(details.get("detailTotal") or 0), 2)
        signals.append(
            {
                "warehouseId": warehouse_id,
                "sourceFile": summary.get("sourceFile", ""),
                "pdfTotal": pdf_total,
                "reportedTotal": reported_total,
                "pdfVsReportedDelta": round(pdf_total - reported_total, 2),
                "componentTotal": round(float(summary_section.get("componentTotal") or 0), 2),
                "componentDelta": round(float(summary_section.get("componentDelta") or 0), 2),
                "detailTotal": detail_total,
                "summaryDelta": round(float(details.get("summaryDelta") or 0), 2),
                "employeeExpenses": round(float(employee_expenses.get("amount") or 0), 2),
                "employeeBenefits": round(float(employee_benefits.get("amount") or 0), 2),
                "loadingAndUnloading": round(float(loading.get("amount") or 0), 2),
                "summaryEvidence": summary_section.get("evidence", ""),
                "detailEvidence": "; ".join(
                    value
                    for value in (
                        employee_expenses.get("evidence", ""),
                        employee_benefits.get("evidence", ""),
                        loading.get("evidence", ""),
                    )
                    if value
                ),
                "withinTolerance": abs(pdf_total - reported_total) <= amount_tolerance,
            }
        )
    return signals


def calculate_extraction_quality(
    pdf_rows: List[LaborLineItem],
    comparison_summary: Dict[str, Any],
    warehouse_comparison: Dict[str, Any] | None = None,
    confidence_threshold: float = 0.85,
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
    # 收集低置信度行明细，供局部重试使用
    low_confidence_rows: List[Dict[str, Any]] = []
    if pdf_rows:
        confidences = [item.confidence for item in pdf_rows]
        avg_confidence = sum(confidences) / len(confidences)
        low_confidence_count = sum(1 for c in confidences if c < confidence_threshold)
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

        # 收集低置信度行明细（confidence < 0.85），用于局部重试
        for item in pdf_rows:
            if item.confidence < confidence_threshold:
                low_confidence_rows.append({
                    "employee_name_raw": item.employee_name_raw,
                    "amount": item.amount,
                    "confidence": round(item.confidence, 3),
                    "source_page_or_row": item.source_page_or_row,
                    "source_file": item.source_file,
                })

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
        "lowConfidenceRows": low_confidence_rows,
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
