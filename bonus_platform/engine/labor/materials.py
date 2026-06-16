from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .compare import compare_by_warehouse, compare_labor_items
from .extract import _extract_pdf_pages, extract_invoice_items, quick_extract_totals
from .governance import audit_ai_page_cache_candidates, build_ai_cache_reconciliation_preview, build_reocr_candidate_plan
from .quality import calculate_extraction_quality
from .workbook import list_workbook_sheets, suggest_mapping
from .workbook import read_workbook_rows


BUSINESS_EXTENSIONS = {".pdf", ".xlsx", ".xls", ".xlsm", ".csv", ".eml"}
DOCUMENT_EXTENSIONS = {".md", ".html", ".json", ".txt"}
SCRIPT_EXTENSIONS = {".py", ".css", ".js"}
WORKBOOK_EXTENSIONS = {".xlsx", ".xls", ".xlsm", ".csv"}


def build_material_index(root: str | Path, *, max_depth: int = 6) -> Dict[str, Any]:
    root_path = Path(root).expanduser()
    if not root_path.exists():
        raise FileNotFoundError(f"参考材料目录不存在: {root_path}")
    if not root_path.is_dir():
        raise NotADirectoryError(f"参考材料路径不是目录: {root_path}")

    files = [_material_file_record(path, root_path) for path in _iter_material_files(root_path, max_depth=max_depth)]
    files = [record for record in files if record]
    batches = _build_candidate_batches(files)
    suppliers = sorted({batch["supplier"] for batch in batches if batch.get("supplier")})
    return {
        "root": str(root_path),
        "summary": {
            "fileCount": len(files),
            "candidateBatchCount": len(batches),
            "supplierCount": len(suppliers),
            "suppliers": suppliers,
            "invoicePdfCount": sum(1 for item in files if item["category"] == "invoice_pdf"),
            "workbookCount": sum(1 for item in files if item["category"] == "workbook_bill"),
            "documentCount": sum(1 for item in files if item["category"] in {"document", "historical_output"}),
        },
        "candidateBatches": batches,
        "batches": batches,
        "files": files,
    }


def build_material_replay_plan(root: str | Path, batch_key: str = "", *, max_depth: int = 6) -> Dict[str, Any]:
    index = build_material_index(root, max_depth=max_depth)
    batches = index["candidateBatches"]
    if batch_key:
        batches = [batch for batch in batches if batch["batchKey"] == batch_key or batch["directory"] == batch_key]
    plans = [_build_one_replay_plan(index["root"], batch) for batch in batches]
    return {
        "root": index["root"],
        "summary": {
            "planCount": len(plans),
            "replayReadyCount": sum(1 for plan in plans if plan["replayReady"]),
            "needsReviewCount": sum(1 for plan in plans if plan["expectedRisks"]),
            "suppliers": sorted({plan["supplier"] for plan in plans if plan.get("supplier")}),
        },
        "plans": plans,
    }


def build_material_dry_run(
    root: str | Path,
    batch_key: str,
    *,
    amount_tolerance: float = 0.10,
    hours_tolerance: float = 0.10,
    confidence_threshold: float = 0.85,
    currency: str = "USD",
) -> Dict[str, Any]:
    plan_payload = build_material_replay_plan(root, batch_key=batch_key)
    plans = plan_payload.get("plans") or []
    if not plans:
        raise ValueError(f"未找到可只读验证的材料批次: {batch_key}")
    plan = plans[0]
    amount_tolerance, hours_tolerance, tolerance_notes = _effective_material_tolerances(
        plan.get("supplier", ""),
        amount_tolerance,
        hours_tolerance,
    )
    root_path = Path(plan_payload["root"])
    pdf_paths = [root_path / relative for relative in plan["uploadPlan"]["pdfFiles"]]
    pdf_text_coverage = _summarize_pdf_text_coverage(pdf_paths)
    workbook_rows = []
    workbook_errors = []
    for mapping_candidate in plan.get("mappingCandidates", []) or []:
        if mapping_candidate.get("error"):
            workbook_errors.append(
                {
                    "relativePath": mapping_candidate.get("relativePath", ""),
                    "error": mapping_candidate.get("error", ""),
                }
            )
            continue
        try:
            workbook_rows.extend(
                read_workbook_rows(
                    root_path / mapping_candidate["relativePath"],
                    mapping_candidate["sheetName"],
                    mapping_candidate["suggestedMapping"],
                )
            )
        except Exception as exc:  # noqa: BLE001 - 只读验证汇总应返回可审阅错误。
            workbook_errors.append({"relativePath": mapping_candidate.get("relativePath", ""), "error": str(exc)})

    deterministic_config = {
        "enabled": False,
        "parallel_extraction_enabled": False,
        "confidence_threshold": confidence_threshold,
        "amount_tolerance": amount_tolerance,
        "hours_tolerance": hours_tolerance,
    }
    pdf_totals = quick_extract_totals(pdf_paths, deterministic_config, supplier=plan["supplier"])
    pdf_rows = extract_invoice_items(
        pdf_paths,
        deterministic_config,
        supplier=plan["supplier"],
        period_start="",
        period_end="",
        currency=currency,
    )
    comparison = compare_labor_items(
        pdf_rows,
        workbook_rows,
        amount_tolerance=amount_tolerance,
        hours_tolerance=hours_tolerance,
        confidence_threshold=confidence_threshold,
    )
    excel_rows_with_warehouse = [row.to_dict() for row in workbook_rows]
    warehouse_comparison = compare_by_warehouse(
        excel_rows_with_warehouse,
        pdf_totals=pdf_totals,
        pdf_rows=pdf_rows,
        amount_tolerance=amount_tolerance,
        hours_tolerance=hours_tolerance,
        confidence_threshold=confidence_threshold,
    )
    quality = calculate_extraction_quality(
        pdf_rows,
        comparison["summary"],
        warehouse_comparison,
        confidence_threshold=confidence_threshold,
    )
    ai_cache_audit = audit_ai_page_cache_candidates(pdf_paths)
    ai_cache_preview = build_ai_cache_reconciliation_preview(
        pdf_paths,
        workbook_rows,
        amount_tolerance=amount_tolerance,
        hours_tolerance=hours_tolerance,
        confidence_threshold=confidence_threshold,
        currency=currency,
    )
    reocr_plan = build_reocr_candidate_plan(
        ai_cache_preview.get("fileQuality", []) or [],
        amount_tolerance=amount_tolerance,
    )
    _attach_text_coverage_to_reocr_plan(reocr_plan, pdf_text_coverage)
    reocr_plan = _demote_reocr_plan_when_deterministic_extract_is_trusted(
        reocr_plan,
        pdf_rows=pdf_rows,
        pdf_text_coverage=pdf_text_coverage,
        quality=quality,
    )
    _enrich_material_reocr_plan(reocr_plan)
    name_mapping_governance = _build_material_name_mapping_governance(
        batch_key=plan["batchKey"],
        candidate_matches=comparison.get("candidateMatches", []),
        reocr_plan=reocr_plan,
        amount_tolerance=amount_tolerance,
        hours_tolerance=hours_tolerance,
    )
    combined_row_governance = _build_material_combined_row_governance(
        batch_key=plan["batchKey"],
        candidate_matches=comparison.get("candidateMatches", []),
        amount_tolerance=amount_tolerance,
        hours_tolerance=hours_tolerance,
    )
    risks = list(plan.get("expectedRisks") or [])
    image_only_count = int(pdf_text_coverage.get("summary", {}).get("imageOnlyFileCount") or 0)
    if image_only_count:
        risks.append(f"{image_only_count} 个 PDF 无可读取文本层，确定性文本规则不可用，需重新做图片识别并人工确认。")
    if workbook_errors:
        risks.append("部分账单读取失败，只读验证结果不完整。")
    if not pdf_rows:
        risks.append("确定性 PDF 明细抽取为空，可能需要重新图片识别辅助。")
        if warehouse_comparison.get("summary", {}).get("totalPassed"):
            risks.append("总额/仓库层可确定性通过，但员工级明细缺失，不能直接确认全员核对。")
    if ai_cache_audit.get("summary", {}).get("candidateFileCount"):
        risks.append("发现历史识别缓存，只能作为待复核证据，需人工确认后才能影响核对结论。")
        if reocr_plan.get("demotedByDeterministicExtract"):
            risks.append("历史图片识别记录与确定性抽取不一致，已降级为审计参考，不进入待处理任务。")
        else:
            candidate_amount = round(float(ai_cache_audit.get("summary", {}).get("candidateAmountTotal") or 0), 2)
            workbook_amount = round(sum(row.amount for row in workbook_rows), 2)
            if abs(round(candidate_amount - workbook_amount, 2)) > amount_tolerance:
                risks.append(
                    f"历史识别缓存金额 ${candidate_amount:,.2f} 与账单金额 ${workbook_amount:,.2f} 不一致，不能直接作为 PDF 明细。"
                )
            preview_exceptions = int(ai_cache_preview.get("summary", {}).get("exceptionCount") or 0)
            if preview_exceptions:
                risks.append(f"历史图片识别结果与账单仍有 {preview_exceptions} 项差异，需要人工复核或重新图片识别。")
            needs_reocr = int(ai_cache_preview.get("summary", {}).get("needsReocrFileCount") or 0)
            reviewable = int(ai_cache_preview.get("summary", {}).get("reviewableFileCount") or 0)
            if needs_reocr or reviewable:
                risks.append(f"历史图片识别文件级评估：{needs_reocr} 个 PDF 建议重新图片识别，{reviewable} 个 PDF 可作为人工复核证据。")
        if reocr_plan.get("summary", {}).get("taskCount"):
            risks.append(f"已生成 {reocr_plan['summary']['taskCount']} 个图片识别复核任务，需预览并人工确认后才能用于正式结果。")
    elif reocr_plan.get("summary", {}).get("taskCount"):
        risks.append(f"已生成 {reocr_plan['summary']['taskCount']} 个图片识别复核任务，需预览并人工确认后才能用于正式结果。")
    if reocr_plan.get("demotedByDeterministicExtract") and not any("降级为审计参考" in risk for risk in risks):
        risks.append("历史图片识别记录与确定性抽取不一致，已降级为审计参考，不进入待处理任务。")
    name_mapping_count = int(name_mapping_governance.get("summary", {}).get("candidateCount") or 0)
    if name_mapping_count:
        risks.append(f"已生成 {name_mapping_count} 个姓名匹配建议，必须预览并人工确认后才能写入当前批次。")
    combined_row_count = int(combined_row_governance.get("summary", {}).get("candidateCount") or 0)
    if combined_row_count:
        risks.append(f"已生成 {combined_row_count} 个疑似 PDF 合并员工行建议，需人工核对原始发票后处理，不能自动改名或清账。")
    allocation_issue_count = int(warehouse_comparison.get("summary", {}).get("allocationIssueCount") or 0)
    if allocation_issue_count:
        risks.append(f"发现 {allocation_issue_count} 个员工跨仓库金额抵消，员工总额可能通过但仓库归属需人工复核。")
    tier_status = {
        "totalPassed": bool(warehouse_comparison.get("summary", {}).get("totalPassed")),
        "warehouseExceptionCount": int(warehouse_comparison.get("summary", {}).get("exceptionCount") or 0),
        "employeeDetailAvailable": bool(pdf_rows),
        "employeeExceptionCount": int(comparison["summary"].get("exceptionCount") or 0),
        "allocationIssueCount": allocation_issue_count,
    }
    exception_rows = [row for row in comparison["rows"] if row.get("matchStatus") != "通过"]
    review_queues = _build_material_review_queues(
        comparison_summary=comparison["summary"],
        warehouse_summary=warehouse_comparison.get("summary", {}),
        exception_rows=exception_rows,
        pdf_text_coverage=pdf_text_coverage,
        reocr_plan=reocr_plan,
        ai_cache_preview=ai_cache_preview,
        name_mapping_governance=name_mapping_governance,
        combined_row_governance=combined_row_governance,
        allocation_issues=warehouse_comparison.get("allocationIssues", []) or [],
        hours_tolerance=hours_tolerance,
    )
    delivery_gate = _build_material_delivery_gate(
        review_queues=review_queues,
        tier_status=tier_status,
        expected_risks=risks,
        quality=quality,
    )
    return {
        "decision": "dry_run_only",
        "mode": "deterministic_first_no_write",
        "batchKey": plan["batchKey"],
        "directory": plan["directory"],
        "supplier": plan["supplier"],
        "periodHint": plan.get("periodHint", ""),
        "uploadPlan": plan["uploadPlan"],
        "mappingCandidates": plan.get("mappingCandidates", []),
        "pdfTotals": pdf_totals,
        "summary": {
            "pdfRowCount": len(pdf_rows),
            "excelRowCount": len(workbook_rows),
            "pdfTotalCount": len(pdf_totals),
            "tolerances": {
                "amount": amount_tolerance,
                "hours": hours_tolerance,
                "notes": tolerance_notes,
            },
            "pdfTextCoverage": pdf_text_coverage["summary"],
            "comparison": comparison["summary"],
            "warehouse": warehouse_comparison.get("summary", {}),
            "tierStatus": tier_status,
            "quality": {
                "level": quality.get("level", ""),
                "message": quality.get("message", ""),
                "score": quality.get("score"),
            },
        },
        "sampleRows": comparison["rows"][:20],
        "exceptionRows": exception_rows[:20],
        "reviewQueues": review_queues,
        "deliveryGate": delivery_gate,
        "candidateMatches": comparison.get("candidateMatches", [])[:20],
        "nameMappingGovernance": name_mapping_governance,
        "combinedRowGovernance": combined_row_governance,
        "allocationIssues": warehouse_comparison.get("allocationIssues", [])[:20],
        "aiCacheAudit": ai_cache_audit,
        "aiCacheReconciliationPreview": ai_cache_preview,
        "reocrPlan": reocr_plan,
        "pdfTextCoverage": pdf_text_coverage,
        "warehouseRows": warehouse_comparison.get("rows", [])[:20],
        "workbookErrors": workbook_errors,
        "expectedRisks": risks,
        "writesRun": False,
        "aiInvoked": False,
    }


def _build_material_review_queues(
    *,
    comparison_summary: Dict[str, Any],
    warehouse_summary: Dict[str, Any],
    exception_rows: List[Dict[str, Any]],
    pdf_text_coverage: Dict[str, Any],
    reocr_plan: Dict[str, Any],
    ai_cache_preview: Dict[str, Any],
    name_mapping_governance: Dict[str, Any],
    combined_row_governance: Dict[str, Any],
    allocation_issues: List[Dict[str, Any]],
    hours_tolerance: float,
) -> Dict[str, Any]:
    text_summary = pdf_text_coverage.get("summary", {}) if isinstance(pdf_text_coverage, dict) else {}
    reocr_summary = reocr_plan.get("summary", {}) if isinstance(reocr_plan, dict) else {}
    cache_summary = ai_cache_preview.get("summary", {}) if isinstance(ai_cache_preview, dict) else {}
    image_only_count = int(text_summary.get("imageOnlyFileCount") or 0)
    reocr_task_count = int(reocr_summary.get("taskCount") or 0)
    reviewable_count = int(reocr_summary.get("reviewableCandidateCount") or 0)
    exception_count = int(comparison_summary.get("exceptionCount") or 0)
    warehouse_exception_count = int(warehouse_summary.get("exceptionCount") or 0) if isinstance(warehouse_summary, dict) else 0
    name_mapping_summary = name_mapping_governance.get("summary", {}) if isinstance(name_mapping_governance, dict) else {}
    ready_name_mapping_count = int(name_mapping_summary.get("readyToReplayCount") or 0)
    combined_summary = combined_row_governance.get("summary", {}) if isinstance(combined_row_governance, dict) else {}
    combined_candidate_count = int(combined_summary.get("candidateCount") or 0)
    allocation_rows = _build_material_allocation_review_rows(allocation_issues)
    amount_rate_rows = _build_amount_rate_review_rows(
        exception_rows,
        hours_tolerance=hours_tolerance,
    )
    amount_rate_summary = _summarize_amount_rate_review_rows(
        amount_rate_rows,
        hours_tolerance=hours_tolerance,
    )
    reocr_tasks = list(reocr_plan.get("tasks") or [])
    reocr_reviewable = list(reocr_plan.get("reviewableCandidates") or [])
    reocr_groups = _build_material_reocr_groups(reocr_tasks, reocr_reviewable)

    primary = "employee_exceptions"
    primary_reason = "员工级异常需复核。"
    if allocation_rows:
        primary = "allocation_review"
        primary_reason = "员工总额可抵消，但仓库归属金额不一致，需按仓库复核发票与账单归属。"
    elif exception_count <= 0 and warehouse_exception_count <= 0:
        primary = "cleared"
        primary_reason = "员工、仓库和总额均通过；本批无需继续处理。"
    elif image_only_count and (reocr_task_count or reviewable_count):
        primary = "reocr"
        primary_reason = "PDF 无文本层，必须先完成图片识别复核并预览影响，再复核员工差异。"
    elif ready_name_mapping_count:
        primary = "name_mapping"
        primary_reason = "存在金额/工时一致的姓名匹配建议，先预览确认可减少异常。"
    elif combined_candidate_count:
        primary = "combined_pdf_row"
        primary_reason = "疑似 PDF 合并员工行需先核对原始发票；确认前不能自动清账。"
    elif amount_rate_rows:
        primary = "amount_rate_review"
        if amount_rate_summary["hoursMismatchCount"]:
            primary_reason = "姓名已匹配，但 PDF 与 Excel 的工时/金额不同，需复核日期范围、加班行和费用口径。"
        else:
            primary_reason = "姓名和工时基本一致，但 PDF 与 Excel 金额不同，需复核费率/加班/服务费口径。"
    elif int(name_mapping_summary.get("candidateCount") or 0):
        primary = "name_mapping"
        primary_reason = "姓名匹配建议需先预览确认。"

    return {
        "primary": primary,
        "primaryReason": primary_reason,
        "reocr": {
            "taskCount": reocr_task_count,
            "reviewableCandidateCount": reviewable_count,
            "imageOnlyFileCount": image_only_count,
            "needsReocrFileCount": int(cache_summary.get("needsReocrFileCount") or 0),
            "cacheExceptionCount": int(cache_summary.get("exceptionCount") or 0),
            "nextActions": _build_material_reocr_next_actions(
                task_count=reocr_task_count,
                reviewable_count=reviewable_count,
                image_only_count=image_only_count,
            ),
            "summaryText": _build_material_reocr_summary_text(
                task_count=reocr_task_count,
                reviewable_count=reviewable_count,
                image_only_count=image_only_count,
                exception_count=int(cache_summary.get("exceptionCount") or 0),
            ),
            "groups": reocr_groups,
            "tasks": reocr_tasks,
            "reviewableCandidates": reocr_reviewable,
        },
        "combinedPdfRows": {
            "count": combined_candidate_count,
            "amountImpactTotal": _safe_round_number(combined_summary.get("amountImpactTotal")),
            "hoursImpactTotal": _safe_round_number(combined_summary.get("hoursImpactTotal")),
            "needsInvoiceReviewCount": int(combined_summary.get("needsInvoiceReviewCount") or 0),
            "rows": (combined_row_governance.get("candidates") or [])[:8],
        },
        "nameMapping": {
            "count": int(name_mapping_summary.get("candidateCount") or 0),
            "readyToReplayCount": ready_name_mapping_count,
            "highConfidenceCount": int(name_mapping_summary.get("highConfidenceCount") or 0),
            "projectedFixedExceptionCount": int(name_mapping_summary.get("projectedFixedExceptionCount") or 0),
            "amountStillDifferentCount": int(name_mapping_summary.get("amountStillDifferentCount") or 0),
            "hoursStillDifferentCount": int(name_mapping_summary.get("hoursStillDifferentCount") or 0),
            "nextActions": _build_material_name_mapping_next_actions(
                candidate_count=int(name_mapping_summary.get("candidateCount") or 0),
                ready_to_replay_count=ready_name_mapping_count,
            ),
            "rows": (name_mapping_governance.get("candidates") or [])[:8],
        },
        "amountRateReview": {
            "count": len(amount_rate_rows),
            "reviewMode": amount_rate_summary["reviewMode"],
            "businessQuestion": amount_rate_summary["businessQuestion"],
            "businessMeaning": amount_rate_summary["businessMeaning"],
            "cannotAutoResolveReason": amount_rate_summary["cannotAutoResolveReason"],
            "amountImpactTotal": amount_rate_summary["amountImpactTotal"],
            "amountOnlyCount": amount_rate_summary["amountOnlyCount"],
            "amountOnlyImpactTotal": amount_rate_summary["amountOnlyImpactTotal"],
            "hoursImpactTotal": amount_rate_summary["hoursImpactTotal"],
            "hoursMismatchCount": amount_rate_summary["hoursMismatchCount"],
            "hoursMismatchImpactTotal": amount_rate_summary["hoursMismatchImpactTotal"],
            "largestAmountDelta": amount_rate_summary["largestAmountDelta"],
            "nextActions": _build_material_amount_rate_next_actions(
                row_count=len(amount_rate_rows),
                hours_mismatch_count=amount_rate_summary["hoursMismatchCount"],
            ),
            "rows": amount_rate_rows[:8],
        },
        "allocationReview": {
            "count": len(allocation_rows),
            "warehousePairCount": sum(int(row.get("warehouseCount") or 0) for row in allocation_rows),
            "amountImpactTotal": round(sum(abs(float(row.get("maxWarehouseDelta") or 0)) for row in allocation_rows), 2),
            "nextActions": _build_material_allocation_next_actions(row_count=len(allocation_rows)),
            "rows": allocation_rows[:8],
        },
        "employeeExceptions": {
            "count": exception_count,
            "shownCount": min(len(exception_rows), 8),
            "suppressedByPrimary": primary != "employee_exceptions" and exception_count > 0,
            "rows": exception_rows[:8],
        },
    }


def _build_material_reocr_groups(tasks: List[Dict[str, Any]], reviewable_candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[tuple[str, str], Dict[str, Any]] = {}
    for item, item_type in [
        *((task, "task") for task in tasks or []),
        *((candidate, "reviewable") for candidate in reviewable_candidates or []),
    ]:
        if not isinstance(item, dict):
            continue
        source_file = str(item.get("sourceFile") or "").strip()
        warehouse_id = str(item.get("warehouseId") or "").strip()
        key = (source_file, warehouse_id)
        group = grouped.setdefault(
            key,
            {
                "sourceFile": source_file,
                "warehouseId": warehouse_id,
                "taskCount": 0,
                "reviewableCandidateCount": 0,
                "amountImpactTotal": 0.0,
                "exceptionCount": 0,
                "unmatchedCurrentCount": 0,
                "unmatchedExcelCount": 0,
                "needsTextRecognition": False,
                "reviewFocus": item.get("reviewFocus", ""),
                "matchReason": item.get("matchReason", ""),
                "impactSummary": item.get("impactSummary", ""),
            },
        )
        if item_type == "task":
            group["taskCount"] += 1
        else:
            group["reviewableCandidateCount"] += 1
        group["amountImpactTotal"] = round(
            float(group.get("amountImpactTotal") or 0) + abs(float(item.get("amountDelta") or 0)),
            2,
        )
        diagnostics = item.get("diagnostics") if isinstance(item.get("diagnostics"), dict) else {}
        summary = diagnostics.get("summary") if isinstance(diagnostics.get("summary"), dict) else {}
        group["exceptionCount"] += int(summary.get("exceptionCount") or 0)
        group["unmatchedCurrentCount"] += int(summary.get("unmatchedCacheCount") or 0)
        group["unmatchedExcelCount"] += int(summary.get("unmatchedExcelCount") or 0)
        coverage = item.get("pdfTextCoverage") if isinstance(item.get("pdfTextCoverage"), dict) else {}
        group["needsTextRecognition"] = bool(group.get("needsTextRecognition")) or bool(coverage.get("needsOcr"))
        if not group.get("matchReason") and item.get("matchReason"):
            group["matchReason"] = item.get("matchReason")
        if not group.get("impactSummary") and item.get("impactSummary"):
            group["impactSummary"] = item.get("impactSummary")
    groups = list(grouped.values())
    for group in groups:
        group["count"] = int(group.get("taskCount") or 0) + int(group.get("reviewableCandidateCount") or 0)
        group["statusLabel"] = "需重新识别" if int(group.get("taskCount") or 0) else "历史识别可预览"
    return sorted(
        groups,
        key=lambda item: (
            0 if int(item.get("taskCount") or 0) else 1,
            -abs(float(item.get("amountImpactTotal") or 0)),
            str(item.get("sourceFile") or ""),
        ),
    )


def _build_material_reocr_summary_text(*, task_count: int, reviewable_count: int, image_only_count: int, exception_count: int) -> str:
    parts = []
    if int(image_only_count or 0):
        parts.append(f"{int(image_only_count)} 个 PDF 无文本层")
    if int(task_count or 0):
        parts.append(f"{int(task_count)} 个需图片识别复核")
    if int(reviewable_count or 0):
        parts.append(f"{int(reviewable_count)} 个历史识别可预览")
    if int(exception_count or 0):
        parts.append(f"{int(exception_count)} 项员工级异常")
    return " · ".join(parts) if parts else "暂无图片识别复核任务"


def _build_material_reocr_next_actions(*, task_count: int, reviewable_count: int, image_only_count: int) -> List[Dict[str, Any]]:
    planned_count = int(task_count or 0) + int(reviewable_count or 0)
    if planned_count <= 0 and int(image_only_count or 0) <= 0:
        return []
    first_step = (
        "创建正式批次并进入图片识别复核"
        if task_count
        else "创建正式批次并预览历史图片识别结果"
    )
    return [
        {
            "step": 1,
            "action": "create_formal_run",
            "label": first_step,
            "description": "复制本批真实材料，保留只读验证诊断；创建后仍不会写入任何规则。",
            "enabled": True,
        },
        {
            "step": 2,
            "action": "extract_compare",
            "label": "抽取并比对",
            "description": "正式批次完成员工级抽取后，会生成图片识别复核任务、姓名匹配建议和异常队列。",
            "enabled": False,
        },
        {
            "step": 3,
            "action": "replay_candidate",
            "label": "上传或预览图片识别结果",
            "description": "识别结果必须按 PDF/仓库范围预览，通过金额和员工级校验后才允许确认。",
            "enabled": False,
        },
        {
            "step": 4,
            "action": "confirm_apply",
            "label": "人工确认后采纳或撤回",
            "description": "确认只激活识别结果；采纳前仍会生成影响预览，失败或误采纳可撤回。",
            "enabled": False,
        },
    ]


def _build_material_amount_rate_next_actions(*, row_count: int, hours_mismatch_count: int) -> List[Dict[str, Any]]:
    if int(row_count or 0) <= 0:
        return []
    review_label = "核对账期、加班和工时" if int(hours_mismatch_count or 0) > 0 else "核对金额计算口径"
    review_description = (
        "先核对 PDF 与 Excel 的账期范围、日期行、加班行和工时汇总，确认是否同一结算口径。"
        if int(hours_mismatch_count or 0) > 0
        else "先核对发票费率、加班倍率、服务费和税费口径，确认金额差异来源。"
    )
    return [
        {
            "step": 1,
            "action": "create_formal_run",
            "label": "建正式批次并保留差异",
            "description": "复制真实材料并保留当前只读验证差异；创建后不会自动清账。",
            "enabled": True,
        },
        {
            "step": 2,
            "action": "review_source_evidence",
            "label": review_label,
            "description": review_description,
            "enabled": False,
        },
        {
            "step": 3,
            "action": "record_business_conclusion",
            "label": "填写差异原因",
            "description": "把差异原因写入复核记录；无法解释的差异继续保留为待处理异常。",
            "enabled": False,
        },
        {
            "step": 4,
            "action": "download_report",
            "label": "导出给业务确认",
            "description": "报告保留 PDF/Excel 金额、工时、差额和来源证据，供业务线下确认。",
            "enabled": False,
        },
    ]


def _build_material_allocation_next_actions(*, row_count: int) -> List[Dict[str, Any]]:
    if int(row_count or 0) <= 0:
        return []
    return [
        {
            "step": 1,
            "action": "create_formal_run",
            "label": "创建正式批次",
            "description": "复制真实材料并保留跨仓归属建议；创建后不会自动确认仓库归属。",
            "enabled": True,
        },
        {
            "step": 2,
            "action": "extract_compare",
            "label": "抽取并比对",
            "description": "正式结果会重新生成仓库差异和跨仓归属建议，保留 PDF/Excel 来源证据。",
            "enabled": False,
        },
        {
            "step": 3,
            "action": "review_warehouse_allocation",
            "label": "复核仓库归属",
            "description": "按员工逐仓核对发票与账单归属，确认是否同一员工跨仓金额抵消。",
            "enabled": False,
        },
        {
            "step": 4,
            "action": "confirm_or_rollback",
            "label": "填写复核意见",
            "description": "确认只写入当前批次审计记录；发现归属错误时继续保留异常或撤回结论。",
            "enabled": False,
        },
    ]


def _build_material_delivery_gate(
    *,
    review_queues: Dict[str, Any],
    tier_status: Dict[str, Any],
    expected_risks: List[str],
    quality: Dict[str, Any],
) -> Dict[str, Any]:
    issues: List[Dict[str, Any]] = []
    reocr = review_queues.get("reocr", {}) if isinstance(review_queues.get("reocr"), dict) else {}
    employee_exceptions = review_queues.get("employeeExceptions", {}) if isinstance(review_queues.get("employeeExceptions"), dict) else {}
    amount_rate = review_queues.get("amountRateReview", {}) if isinstance(review_queues.get("amountRateReview"), dict) else {}
    name_mapping = review_queues.get("nameMapping", {}) if isinstance(review_queues.get("nameMapping"), dict) else {}
    combined = review_queues.get("combinedPdfRows", {}) if isinstance(review_queues.get("combinedPdfRows"), dict) else {}
    allocation = review_queues.get("allocationReview", {}) if isinstance(review_queues.get("allocationReview"), dict) else {}

    primary = str(review_queues.get("primary") or "")
    if primary == "reocr" and int(reocr.get("taskCount") or 0):
        issues.append(
            {
                "severity": "blocked",
                "code": "reocr_required",
                "title": "图片识别未闭环",
                "message": f"还有 {int(reocr.get('taskCount') or 0)} 个图片识别复核任务，必须预览并人工确认后才能交付。",
                "action": "先创建正式批次，上传或预览识别结果，再确认采纳或撤回。",
            }
        )
    if int(employee_exceptions.get("count") or 0) and not employee_exceptions.get("suppressedByPrimary"):
        issues.append(
            {
                "severity": "blocked",
                "code": "employee_exceptions",
                "title": "员工级异常未清",
                "message": f"仍有 {int(employee_exceptions.get('count') or 0)} 项员工级异常，不能直接交付。",
                "action": "先处理员工级差异，或将差异归类到可解释复核队列。",
            }
        )
    if int(amount_rate.get("count") or 0):
        issues.append(
            {
                "severity": "review",
                "code": "amount_rate_review",
                "title": "金额/工时口径待复核",
                "message": f"{int(amount_rate.get('count') or 0)} 人金额或工时口径待确认，影响金额 ${float(amount_rate.get('amountImpactTotal') or 0):,.2f}。",
                "action": "按卡片逐项确认费率、服务费、税费、账期或加班口径。",
            }
        )
    if int(name_mapping.get("count") or 0):
        issues.append(
            {
                "severity": "review",
                "code": "name_mapping",
                "title": "姓名匹配建议未确认",
                "message": f"还有 {int(name_mapping.get('count') or 0)} 个姓名匹配建议，预计可减少 {int(name_mapping.get('projectedFixedExceptionCount') or 0)} 项异常。",
                "action": "创建正式批次后先预览影响，再由人工确认或撤回。",
            }
        )
    if int(combined.get("count") or 0):
        issues.append(
            {
                "severity": "review",
                "code": "combined_pdf_row",
                "title": "PDF 合并员工行待核",
                "message": f"发现 {int(combined.get('count') or 0)} 个疑似合并员工行，需核对原始发票。",
                "action": "确认是否需要拆分员工金额/工时，不能自动分摊或清账。",
            }
        )
    if int(allocation.get("count") or 0):
        issues.append(
            {
                "severity": "review",
                "code": "allocation_review",
                "title": "跨仓归属待复核",
                "message": f"发现 {int(allocation.get('count') or 0)} 名员工存在跨仓归属差异。",
                "action": "按仓库核对发票与账单归属，确认后保留审计记录。",
            }
        )
    if str(quality.get("level") or "").lower() in {"low", "warning"}:
        issues.append(
            {
                "severity": "review",
                "code": "quality_review",
                "title": "抽取质量需复核",
                "message": str(quality.get("message") or "抽取质量未达到直接交付标准。"),
                "action": "复核证据和低置信度项后再交付。",
            }
        )

    primary_code = {
        "reocr": "reocr_required",
        "amount_rate_review": "amount_rate_review",
        "name_mapping": "name_mapping",
        "combined_pdf_row": "combined_pdf_row",
        "allocation_review": "allocation_review",
        "employee_exceptions": "employee_exceptions",
    }.get(primary, "")
    issues = sorted(
        issues,
        key=lambda issue: (
            0 if issue.get("severity") == "blocked" else 1,
            0 if issue.get("code") == primary_code else 1,
            str(issue.get("code") or ""),
        ),
    )
    blocked_count = sum(1 for issue in issues if issue.get("severity") == "blocked")
    review_count = sum(1 for issue in issues if issue.get("severity") == "review")
    status = "blocked" if blocked_count else "needs_review" if review_count else "ready"
    label = "不可交付" if status == "blocked" else "需复核" if status == "needs_review" else "可交付"
    message = (
        "仍存在阻断项，不能上线或交付。"
        if status == "blocked"
        else "无阻断项，但仍有需人工留痕确认的复核项。"
        if status == "needs_review"
        else "员工、仓库和总额均通过，且没有未闭环复核队列。"
    )
    return {
        "status": status,
        "label": label,
        "message": message,
        "summary": {
            "blockedCount": blocked_count,
            "reviewCount": review_count,
            "riskCount": len(expected_risks or []),
            "employeeDetailAvailable": bool(tier_status.get("employeeDetailAvailable")),
        },
        "issues": issues[:8],
    }


def _build_material_name_mapping_next_actions(*, candidate_count: int, ready_to_replay_count: int) -> List[Dict[str, Any]]:
    if int(candidate_count or 0) <= 0:
        return []
    first_description = (
        "复制本批真实材料，正式批次创建后仍不会自动写入姓名匹配。"
        if ready_to_replay_count
        else "复制本批真实材料；建议仍需先完成正式抽取比对，再判断能否预览。"
    )
    return [
        {
            "step": 1,
            "action": "create_formal_run",
            "label": "创建正式批次",
            "description": first_description,
            "enabled": True,
        },
        {
            "step": 2,
            "action": "extract_compare",
            "label": "抽取并比对",
            "description": "正式结果会重新生成姓名匹配建议，并保留原始 PDF/Excel 证据。",
            "enabled": False,
        },
        {
            "step": 3,
            "action": "preview_impact",
            "label": "预览姓名匹配影响",
            "description": "建议必须先预览，确认修复人数、回归人数和受影响员工。",
            "enabled": False,
        },
        {
            "step": 4,
            "action": "confirm_or_rollback",
            "label": "填写复核意见",
            "description": "人工确认后才写入当前批次；确认记录可审计，错误匹配可撤回。",
            "enabled": False,
        },
    ]


def _build_amount_rate_review_rows(exception_rows: List[Dict[str, Any]], *, hours_tolerance: float) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    tolerance = max(float(hours_tolerance), 0.05)
    for row in exception_rows:
        if row.get("matchStatus") != "金额差异":
            continue
        raw_hours_delta = float(row.get("hoursDelta") or 0)
        hours_delta = abs(raw_hours_delta)
        amount_delta = float(row.get("amountDelta") or 0)
        if abs(amount_delta) <= 0 and hours_delta <= tolerance:
            continue
        review_type = "hours_amount_mismatch" if hours_delta > tolerance else "amount_basis_mismatch"
        review_label = "工时和金额都不同" if review_type == "hours_amount_mismatch" else "工时一致，仅金额不同"
        review_focus = "先核工时口径" if review_type == "hours_amount_mismatch" else "先核金额口径"
        amount_direction_label = _build_amount_direction_label(amount_delta)
        hours_direction_label = _build_hours_direction_label(raw_hours_delta, tolerance)
        business_question = _build_amount_rate_row_question(
            amount_delta=amount_delta,
            hours_delta=raw_hours_delta,
            review_type=review_type,
        )
        recommendation = (
            "先核对 PDF 与 Excel 的账期范围、日期行、加班行是否一致；确认前不能自动清账。"
            if review_type == "hours_amount_mismatch"
            else "先核对 PDF 发票费率、加班/差额行、服务费倍率与 Excel 成本口径；确认前不能自动清账。"
        )
        cannot_auto_resolve_reason = (
            "工时差会改变应付金额，必须先确认账期、日期行和加班口径。"
            if review_type == "hours_amount_mismatch"
            else "金额口径属于业务结算判断，系统不能在未留痕确认前自动改金额或清账。"
        )
        rows.append(
            {
                "reviewType": review_type,
                "reviewLabel": review_label,
                "reviewFocus": review_focus,
                "employeeKey": row.get("employeeKey", ""),
                "employeeName": row.get("employeeName", ""),
                "pdfAmountTotal": round(float(row.get("pdfAmountTotal") or 0), 2),
                "excelAmountTotal": round(float(row.get("excelAmountTotal") or 0), 2),
                "amountDelta": round(amount_delta, 2),
                "amountDirectionLabel": amount_direction_label,
                "pdfHoursTotal": round(float(row.get("pdfHoursTotal") or 0), 2),
                "excelHoursTotal": round(float(row.get("excelHoursTotal") or 0), 2),
                "hoursDelta": round(raw_hours_delta, 2),
                "hoursDirectionLabel": hours_direction_label,
                "riskFlags": list(row.get("riskFlags") or []),
                "sourceRefs": row.get("sourceRefs", ""),
                "businessQuestion": business_question,
                "cannotAutoResolveReason": cannot_auto_resolve_reason,
                "recommendation": recommendation,
            }
        )
    return sorted(rows, key=lambda item: abs(float(item.get("amountDelta") or 0)), reverse=True)


def _build_amount_direction_label(amount_delta: float) -> str:
    if abs(amount_delta) <= 0.005:
        return "金额一致"
    return "PDF 高于 Excel" if amount_delta > 0 else "PDF 少于 Excel"


def _build_hours_direction_label(hours_delta: float, tolerance: float) -> str:
    if abs(hours_delta) <= tolerance:
        return "工时一致"
    return "PDF 工时多于 Excel" if hours_delta > 0 else "PDF 工时少于 Excel"


def _build_amount_rate_row_question(*, amount_delta: float, hours_delta: float, review_type: str) -> str:
    amount_abs = abs(round(float(amount_delta), 2))
    amount_word = "多" if amount_delta > 0 else "少"
    if review_type == "hours_amount_mismatch":
        hours_abs = abs(round(float(hours_delta), 2))
        hours_word = "多" if hours_delta > 0 else "少"
        return (
            f"PDF 比 Excel {amount_word} ${amount_abs:,.2f}，工时{hours_word} {hours_abs:.2f}；"
            "先核账期、日期行和加班工时，再判断金额差。"
        )
    return (
        f"PDF 比 Excel {amount_word} ${amount_abs:,.2f}，工时一致；"
        "先确认费率、加班/差额行、服务费倍率或税费是否采用同一口径。"
    )


def _summarize_amount_rate_review_rows(rows: List[Dict[str, Any]], *, hours_tolerance: float) -> Dict[str, Any]:
    tolerance = max(float(hours_tolerance), 0.05)
    amount_impact_total = round(sum(abs(float(row.get("amountDelta") or 0)) for row in rows), 2)
    hours_impact_total = round(sum(abs(float(row.get("hoursDelta") or 0)) for row in rows), 2)
    hours_rows = [row for row in rows if abs(float(row.get("hoursDelta") or 0)) > tolerance]
    amount_only_rows = [row for row in rows if abs(float(row.get("hoursDelta") or 0)) <= tolerance]
    hours_mismatch_impact = round(sum(abs(float(row.get("amountDelta") or 0)) for row in hours_rows), 2)
    amount_only_impact = round(sum(abs(float(row.get("amountDelta") or 0)) for row in amount_only_rows), 2)
    largest_amount_delta = round(max((abs(float(row.get("amountDelta") or 0)) for row in rows), default=0.0), 2)
    review_mode = "hours_and_amount" if hours_rows else "amount_basis"
    if review_mode == "hours_and_amount":
        business_question = "这些员工是否使用了同一账期、日期行、加班和工时汇总口径？"
        business_meaning = "姓名已匹配，但工时也不同；必须先确认 PDF 与 Excel 是否在核同一批工时，再判断金额。"
        cannot_auto_resolve_reason = "工时差会改变应付金额，系统不能仅凭姓名匹配或金额接近自动清账。"
    else:
        business_question = "工时已经对齐，金额差来自费率、加班、服务费还是税费口径？"
        business_meaning = "员工和工时基本一致，问题集中在金额计算口径；通常需要业务确认发票与账单采用的费率或费用组成。"
        cannot_auto_resolve_reason = "金额口径属于业务结算判断，确认前不能由系统自动改金额或清账。"
    return {
        "reviewMode": review_mode,
        "businessQuestion": business_question,
        "businessMeaning": business_meaning,
        "cannotAutoResolveReason": cannot_auto_resolve_reason,
        "amountImpactTotal": amount_impact_total,
        "amountOnlyCount": len(amount_only_rows),
        "amountOnlyImpactTotal": amount_only_impact,
        "hoursImpactTotal": hours_impact_total,
        "hoursMismatchCount": len(hours_rows),
        "hoursMismatchImpactTotal": hours_mismatch_impact,
        "largestAmountDelta": largest_amount_delta,
    }


def _build_material_allocation_review_rows(allocation_issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for issue in allocation_issues or []:
        if not isinstance(issue, dict):
            continue
        warehouses = [warehouse for warehouse in issue.get("warehouses", []) if isinstance(warehouse, dict)]
        max_delta = max((abs(float(warehouse.get("amountDelta") or 0)) for warehouse in warehouses), default=0.0)
        rows.append(
            {
                "employeeKey": issue.get("employeeKey", ""),
                "employeeName": issue.get("employeeName", ""),
                "netAmountDelta": _safe_round_number(issue.get("netAmountDelta")),
                "warehouseCount": int(issue.get("warehouseCount") or len(warehouses)),
                "maxWarehouseDelta": round(max_delta, 2),
                "warehouses": warehouses[:4],
                "recommendation": issue.get("recommendation")
                or "员工总额可抵消，但仓库归属金额不一致，需按仓库复核发票与账单归属。",
            }
        )
    return sorted(rows, key=lambda item: abs(float(item.get("maxWarehouseDelta") or 0)), reverse=True)


def _effective_material_tolerances(supplier: str, amount_tolerance: float, hours_tolerance: float) -> tuple[float, float, List[str]]:
    notes: List[str] = []
    normalized_supplier = _normalize_supplier_name(supplier)
    if normalized_supplier == "sss":
        adjusted_amount = max(float(amount_tolerance), 0.25)
        if adjusted_amount != float(amount_tolerance):
            notes.append("SSS 发票按小数费率逐行计算，$0.25 内金额差异按舍入误差处理。")
        amount_tolerance = adjusted_amount
    return float(amount_tolerance), float(hours_tolerance), notes


def _normalize_supplier_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _build_material_combined_row_governance(
    *,
    batch_key: str,
    candidate_matches: List[Dict[str, Any]],
    amount_tolerance: float,
    hours_tolerance: float,
) -> Dict[str, Any]:
    candidates = _build_material_combined_row_candidates(
        batch_key=batch_key,
        candidate_matches=candidate_matches,
        amount_tolerance=amount_tolerance,
        hours_tolerance=hours_tolerance,
    )
    return {
        "decision": "candidate_only",
        "requiresConfirmation": True,
        "mode": "material_dry_run_combined_pdf_row_preview",
        "summary": {
            "candidateCount": len(candidates),
            "amountImpactTotal": round(sum(abs(float(candidate.get("amountGap") or 0)) for candidate in candidates), 2),
            "hoursImpactTotal": round(sum(abs(float(candidate.get("hoursGap") or 0)) for candidate in candidates), 2),
            "needsInvoiceReviewCount": len(candidates),
        },
        "candidates": candidates[:20],
        "activeResolutions": [],
        "rolledBackResolutions": [],
        "replaySummaries": {},
    }


def _build_material_combined_row_candidates(
    *,
    batch_key: str,
    candidate_matches: List[Dict[str, Any]],
    amount_tolerance: float,
    hours_tolerance: float,
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for match in candidate_matches or []:
        if not isinstance(match, dict):
            continue
        if str(match.get("issueType") or "") != "combined_pdf_row":
            continue
        pdf_name = str(match.get("pdfEmployeeName") or "").strip()
        excel_name = str(match.get("excelEmployeeName") or "").strip()
        source_refs = str(match.get("sourceRefs") or "")
        source_file = str(match.get("sourceFile") or "").strip() or _source_file_from_candidate_refs(source_refs)
        warehouse_id = str(match.get("warehouseId") or "").strip()
        identity = (source_file, warehouse_id, pdf_name, excel_name)
        if identity in seen:
            continue
        seen.add(identity)

        amount_delta = _safe_round_number(match.get("amountDelta"))
        hours_delta = _safe_round_number(match.get("hoursDelta"))
        exact_remainder = abs(amount_delta) <= amount_tolerance and abs(hours_delta) <= hours_tolerance
        impact_summary = _build_candidate_impact_summary(amount_delta=amount_delta, hours_delta=hours_delta)
        candidate_id = "material_combined_row_" + "_".join(
            _safe_key(part)
            for part in (batch_key, source_file or "candidate_match", warehouse_id or "all", pdf_name, excel_name)
        )
        candidates.append(
            {
                "candidateId": candidate_id,
                "decision": "candidate_only",
                "status": "pending_invoice_review",
                "requiresConfirmation": True,
                "issueType": "combined_pdf_row",
                "sourceFile": source_file,
                "warehouseId": warehouse_id,
                "pdfEmployeeName": pdf_name,
                "excelEmployeeName": excel_name,
                "amountGap": amount_delta,
                "hoursGap": hours_delta,
                "confidence": "review_required" if not exact_remainder else "low_impact_review",
                "matchReason": "PDF 行疑似包含多名员工或剩余金额/工时",
                "businessQuestion": (
                    f"PDF 中的 {pdf_name or '该员工行'} 是否还包含 Excel 员工 {excel_name or '另一名员工'} 的金额或工时？"
                    "需先核对原始发票行，确认前不能把差额自动分摊。"
                ),
                "impactSummary": impact_summary,
                "cannotAutoResolveReason": "合并行需要人工确认原始发票中的员工拆分关系，系统不能仅凭差额接近自动清账。",
                "recommendation": str(match.get("recommendation") or "疑似 PDF 合并员工行，需人工核对原始发票。"),
                "evidence": {
                    "sourceRefs": source_refs,
                    "pdfAmount": match.get("pdfAmountTotal", 0),
                    "excelAmount": match.get("excelAmountTotal", 0),
                    "pdfHours": match.get("pdfHoursTotal", 0),
                    "excelHours": match.get("excelHoursTotal", 0),
                    "nameSimilarity": match.get("nameSimilarity", 0),
                },
                "auditTrail": [
                    {
                        "action": "created",
                        "actor": "system",
                        "reason": "material_dry_run_combined_pdf_row",
                    }
                ],
            }
        )
    return candidates


def _build_material_name_mapping_governance(
    *,
    batch_key: str,
    candidate_matches: List[Dict[str, Any]],
    reocr_plan: Dict[str, Any] | None = None,
    amount_tolerance: float,
    hours_tolerance: float,
) -> Dict[str, Any]:
    candidates = _dedupe_material_name_mapping_candidates([
        *_build_material_name_mapping_candidates(
            batch_key=batch_key,
            candidate_matches=candidate_matches,
            amount_tolerance=amount_tolerance,
            hours_tolerance=hours_tolerance,
        ),
        *_build_material_name_mapping_candidates_from_reocr_plan(
            batch_key=batch_key,
            reocr_plan=reocr_plan or {},
        ),
    ])
    candidates = sorted(
        candidates,
        key=lambda candidate: (
            candidate.get("confidence") != "high",
            abs(float(candidate.get("amountGap") or 0)) > amount_tolerance,
            abs(float(candidate.get("hoursGap") or 0)) > hours_tolerance,
            -abs(float(candidate.get("amountGap") or 0)),
        ),
    )
    return {
        "decision": "candidate_only",
        "requiresConfirmation": True,
        "mode": "material_dry_run_name_mapping_preview",
        "summary": {
            "candidateCount": len(candidates),
            "highConfidenceCount": sum(1 for candidate in candidates if candidate.get("confidence") == "high"),
            "readyToReplayCount": sum(1 for candidate in candidates if candidate.get("confidence") == "high" and abs(float(candidate.get("amountGap") or 0)) <= amount_tolerance and abs(float(candidate.get("hoursGap") or 0)) <= hours_tolerance),
            "projectedFixedExceptionCount": sum(int(candidate.get("projectedFixedExceptionCount") or 0) for candidate in candidates),
            "amountStillDifferentCount": sum(1 for candidate in candidates if abs(float(candidate.get("amountGap") or 0)) > amount_tolerance),
            "hoursStillDifferentCount": sum(1 for candidate in candidates if abs(float(candidate.get("hoursGap") or 0)) > hours_tolerance),
            "fromReocrDiagnosticsCount": sum(1 for candidate in candidates if candidate.get("sourceDiagnostic") == "reocr_suspected_name_pair"),
        },
        "candidates": candidates[:20],
        "activeMappings": [],
        "rolledBackMappings": [],
        "replaySummaries": {},
    }


def _dedupe_material_name_mapping_candidates(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for candidate in candidates:
        identity = (
            str(candidate.get("sourceFile") or ""),
            str(candidate.get("warehouseId") or ""),
            str(candidate.get("cacheEmployeeName") or ""),
            str(candidate.get("excelEmployeeName") or ""),
        )
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(candidate)
    return deduped


def _build_material_name_mapping_candidates_from_reocr_plan(
    *,
    batch_key: str,
    reocr_plan: Dict[str, Any],
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for task in reocr_plan.get("tasks", []) or []:
        if not isinstance(task, dict):
            continue
        diagnostics = task.get("diagnostics") if isinstance(task.get("diagnostics"), dict) else {}
        for pair in diagnostics.get("suspectedNamePairs", []) or []:
            if not isinstance(pair, dict):
                continue
            cache_name = str(pair.get("cacheEmployeeName") or "").strip()
            excel_name = str(pair.get("excelEmployeeName") or "").strip()
            source_file = str(task.get("sourceFile") or "").strip()
            warehouse_id = str(task.get("warehouseId") or "").strip()
            if not cache_name or not excel_name:
                continue
            identity = (source_file, warehouse_id, cache_name, excel_name)
            if identity in seen:
                continue
            seen.add(identity)
            candidate_id = "material_name_map_" + "_".join(
                _safe_key(part)
                for part in (batch_key, source_file or "reocr", warehouse_id or "all", cache_name, excel_name)
            )
            candidates.append(
                {
                    "candidateId": candidate_id,
                    "decision": "candidate_only",
                    "status": "pending_user_confirmation",
                    "requiresConfirmation": True,
                    "sourceDiagnostic": "reocr_suspected_name_pair",
                    "sourceFile": source_file,
                    "warehouseId": warehouse_id,
                    "cacheEmployeeName": cache_name,
                    "excelEmployeeName": excel_name,
                    "proposedMapping": {cache_name: excel_name},
                    "amountGap": _safe_round_number(pair.get("amountGap")),
                    "hoursGap": _safe_round_number(pair.get("hoursGap")),
                    "confidence": str(pair.get("confidence") or "medium"),
                    "projectedFixedExceptionCount": 0,
                    "matchReason": "图片识别诊断发现姓名疑似对应",
                    "businessQuestion": (
                        f"是否确认图片识别名称 {cache_name} 对应账单员工 {excel_name}？"
                        "需先重新识别或预览影响，再决定是否写入姓名匹配。"
                    ),
                    "impactSummary": _build_candidate_impact_summary(
                        amount_delta=_safe_round_number(pair.get("amountGap")),
                        hours_delta=_safe_round_number(pair.get("hoursGap")),
                    ),
                    "cannotAutoResolveReason": "该建议来自图片识别诊断，必须先完成识别复核和影响预览，不能直接写入规则。",
                    "recommendation": str(pair.get("recommendation") or "金额/工时接近，建议创建批次后预览并人工确认姓名匹配。"),
                    "evidence": {
                        "sourceRefs": pair.get("sourceRefs", ""),
                        "cacheAmount": pair.get("cacheAmount", 0),
                        "excelAmount": pair.get("excelAmount", 0),
                        "cacheHours": pair.get("cacheHours", 0),
                        "excelHours": pair.get("excelHours", 0),
                    },
                    "auditTrail": [
                        {
                            "action": "created",
                            "actor": "system",
                            "reason": "material_dry_run_reocr_suspected_name_pair",
                        }
                    ],
                }
            )
    return candidates


def _build_material_name_mapping_candidates(
    *,
    batch_key: str,
    candidate_matches: List[Dict[str, Any]],
    amount_tolerance: float,
    hours_tolerance: float,
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for match in candidate_matches or []:
        if not isinstance(match, dict):
            continue
        if str(match.get("issueType") or "") == "combined_pdf_row":
            continue
        pdf_name = str(match.get("pdfEmployeeName") or "").strip()
        excel_name = str(match.get("excelEmployeeName") or "").strip()
        if not pdf_name or not excel_name:
            continue
        source_refs = str(match.get("sourceRefs") or "")
        source_file = str(match.get("sourceFile") or "").strip() or _source_file_from_candidate_refs(source_refs)
        warehouse_id = str(match.get("warehouseId") or "").strip()
        identity = (source_file, warehouse_id, pdf_name, excel_name)
        if identity in seen:
            continue
        seen.add(identity)

        amount_delta = _safe_round_number(match.get("amountDelta"))
        hours_delta = _safe_round_number(match.get("hoursDelta"))
        exact_totals = abs(amount_delta) <= amount_tolerance and abs(hours_delta) <= hours_tolerance
        projected_fixed_count = 2 if exact_totals else 0
        match_reason = "姓名相似且金额/工时一致" if exact_totals else "姓名相似，但金额或工时仍需复核"
        impact_summary = _build_candidate_impact_summary(amount_delta=amount_delta, hours_delta=hours_delta)
        candidate_id = "material_name_map_" + "_".join(
            _safe_key(part)
            for part in (batch_key, source_file or "candidate_match", warehouse_id or "all", pdf_name, excel_name)
        )
        candidates.append(
            {
                "candidateId": candidate_id,
                "decision": "candidate_only",
                "status": "pending_user_confirmation",
                "requiresConfirmation": True,
                "sourceFile": source_file,
                "warehouseId": warehouse_id,
                "cacheEmployeeName": pdf_name,
                "excelEmployeeName": excel_name,
                "proposedMapping": {pdf_name: excel_name},
                "amountGap": amount_delta,
                "hoursGap": hours_delta,
                "confidence": "high" if exact_totals else "medium",
                "projectedFixedExceptionCount": projected_fixed_count,
                "matchReason": match_reason,
                "businessQuestion": (
                    f"是否确认 PDF 名称 {pdf_name} 对应 Excel 员工 {excel_name}？"
                    f"{'确认后预计减少 ' + str(projected_fixed_count) + ' 项异常。' if projected_fixed_count else '金额或工时仍不同，需先复核差异口径。'}"
                ),
                "impactSummary": impact_summary,
                "cannotAutoResolveReason": (
                    "姓名匹配会改变员工级对账归属，必须预览影响并由人工确认后才可写入。"
                    if exact_totals
                    else "姓名相似不能解释金额或工时差异，必须先复核差异口径，不能直接确认匹配。"
                ),
                "recommendation": (
                    "金额/工时一致，建议创建批次后预览并人工确认姓名匹配。"
                    if exact_totals
                    else "姓名相似但金额或工时仍有差异，创建批次后需先复核金额口径再确认映射。"
                ),
                "evidence": {
                    "sourceRefs": source_refs,
                    "cacheAmount": match.get("pdfAmountTotal", 0),
                    "excelAmount": match.get("excelAmountTotal", 0),
                    "cacheHours": match.get("pdfHoursTotal", 0),
                    "excelHours": match.get("excelHoursTotal", 0),
                    "nameSimilarity": match.get("nameSimilarity", 0),
                },
                "auditTrail": [
                    {
                        "action": "created",
                        "actor": "system",
                        "reason": "material_dry_run_candidate_match_name_pair",
                    }
                ],
            }
        )
    return candidates


def _source_file_from_candidate_refs(source_refs: str) -> str:
    for segment in str(source_refs or "").split(";"):
        token = segment.strip().split(" ")[0] if segment.strip() else ""
        if token.lower().endswith(".pdf"):
            return Path(token).name
    return ""


def _build_candidate_impact_summary(*, amount_delta: float, hours_delta: float) -> str:
    parts: List[str] = []
    if abs(float(amount_delta or 0)) > 0.005:
        direction = "PDF 高于 Excel" if amount_delta > 0 else "PDF 少于 Excel"
        parts.append(f"{direction} ${abs(float(amount_delta)):,.2f}")
    if abs(float(hours_delta or 0)) > 0.005:
        direction = "PDF 工时多于 Excel" if hours_delta > 0 else "PDF 工时少于 Excel"
        parts.append(f"{direction} {abs(float(hours_delta)):.2f}")
    return "；".join(parts) if parts else "金额和工时均一致"


def _safe_round_number(value: Any) -> float:
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _safe_key(value: str) -> str:
    token = re.sub(r"[^0-9A-Za-z_-]+", "_", str(value or "").strip())
    return token.strip("_") or "unknown"


def _summarize_pdf_text_coverage(pdf_paths: List[Path]) -> Dict[str, Any]:
    pages = _extract_pdf_pages(pdf_paths)
    pages_by_file: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for page in pages:
        pages_by_file[str(page.get("source_file") or "")].append(page)

    files = []
    for path in pdf_paths:
        source_file = path.name
        source_pages = pages_by_file.get(source_file, [])
        page_count = len(source_pages)
        readable_pages = sum(1 for page in source_pages if (page.get("text") or "").strip())
        text_chars = sum(len(page.get("text") or "") for page in source_pages)
        image_only = page_count > 0 and readable_pages == 0
        files.append(
            {
                "sourceFile": source_file,
                "pageCount": page_count,
                "readablePageCount": readable_pages,
                "emptyTextPageCount": max(page_count - readable_pages, 0),
                "textCharCount": text_chars,
                "hasTextLayer": readable_pages > 0,
                "needsOcr": image_only,
                "diagnostic": "image_only_pdf" if image_only else "text_layer_readable",
            }
        )

    image_only_files = [item["sourceFile"] for item in files if item["needsOcr"]]
    return {
        "summary": {
            "fileCount": len(files),
            "textReadableFileCount": sum(1 for item in files if item["hasTextLayer"]),
            "imageOnlyFileCount": len(image_only_files),
            "textReadablePageCount": sum(int(item["readablePageCount"]) for item in files),
            "emptyTextPageCount": sum(int(item["emptyTextPageCount"]) for item in files),
            "imageOnlyPdfFiles": image_only_files[:20],
        },
        "files": files,
    }


def _attach_text_coverage_to_reocr_plan(reocr_plan: Dict[str, Any], pdf_text_coverage: Dict[str, Any]) -> None:
    coverage_by_file = {
        str(item.get("sourceFile") or ""): item
        for item in pdf_text_coverage.get("files", [])
    }
    image_only_task_count = 0
    for collection_name in ("tasks", "reviewableCandidates"):
        for item in reocr_plan.get(collection_name, []) or []:
            coverage = coverage_by_file.get(str(item.get("sourceFile") or ""))
            if not coverage:
                continue
            item["pdfTextCoverage"] = {
                "hasTextLayer": bool(coverage.get("hasTextLayer")),
                "pageCount": int(coverage.get("pageCount") or 0),
                "readablePageCount": int(coverage.get("readablePageCount") or 0),
                "emptyTextPageCount": int(coverage.get("emptyTextPageCount") or 0),
                "needsOcr": bool(coverage.get("needsOcr")),
                "diagnostic": coverage.get("diagnostic", ""),
            }
            if coverage.get("needsOcr"):
                item["extractionPrerequisite"] = "pdf_text_layer_empty_requires_ocr"
                if collection_name == "tasks":
                    image_only_task_count += 1
    summary = reocr_plan.setdefault("summary", {})
    summary["imageOnlyTaskCount"] = image_only_task_count


def _demote_reocr_plan_when_deterministic_extract_is_trusted(
    reocr_plan: Dict[str, Any],
    *,
    pdf_rows: List[Any],
    pdf_text_coverage: Dict[str, Any],
    quality: Dict[str, Any],
) -> Dict[str, Any]:
    """Keep stale image-recognition cache out of the primary review queue.

    Historical image-recognition rows are useful evidence when deterministic
    PDF extraction is unavailable. If the PDF text layer is readable and the
    deterministic employee extraction quality is already OK, cache deltas are
    usually stale history rather than a reason to ask business users for more
    image recognition work.
    """
    if not isinstance(reocr_plan, dict):
        return reocr_plan
    if not pdf_rows:
        return reocr_plan
    text_summary = pdf_text_coverage.get("summary", {}) if isinstance(pdf_text_coverage, dict) else {}
    if int(text_summary.get("imageOnlyFileCount") or 0) > 0:
        return reocr_plan
    if str(quality.get("level") or "").lower() != "ok":
        return reocr_plan
    task_count = len(reocr_plan.get("tasks") or [])
    reviewable_count = len(reocr_plan.get("reviewableCandidates") or [])
    if task_count + reviewable_count <= 0:
        return reocr_plan
    demoted = {
        **reocr_plan,
        "requiresConfirmation": False,
        "message": "确定性 PDF 明细抽取已通过质量检查；历史图片识别记录只作为审计参考，不进入待处理任务。",
        "demotedByDeterministicExtract": True,
        "demotionReason": "deterministic_pdf_extract_quality_ok",
        "demotedCandidates": list(reocr_plan.get("tasks") or []) + list(reocr_plan.get("reviewableCandidates") or []),
        "tasks": [],
        "reviewableCandidates": [],
    }
    summary = dict(reocr_plan.get("summary") or {})
    summary.update(
        {
            "taskCount": 0,
            "reviewableCandidateCount": 0,
            "imageOnlyTaskCount": 0,
            "demotedTaskCount": task_count,
            "demotedReviewableCandidateCount": reviewable_count,
        }
    )
    demoted["summary"] = summary
    return demoted


def _enrich_material_reocr_plan(reocr_plan: Dict[str, Any]) -> None:
    for collection_name, label in (
        ("tasks", "需要重新图片识别"),
        ("reviewableCandidates", "历史识别缓存可先预览"),
    ):
        for item in reocr_plan.get(collection_name, []) or []:
            if not isinstance(item, dict):
                continue
            diagnostics = item.get("diagnostics") if isinstance(item.get("diagnostics"), dict) else {}
            summary = diagnostics.get("summary") if isinstance(diagnostics.get("summary"), dict) else {}
            coverage = item.get("pdfTextCoverage") if isinstance(item.get("pdfTextCoverage"), dict) else {}
            amount_delta = _safe_round_number(item.get("amountDelta"))
            exception_count = int(summary.get("exceptionCount") or 0)
            amount_diff_count = int(summary.get("amountDiffCount") or 0)
            unmatched_cache = int(summary.get("unmatchedCacheCount") or 0)
            unmatched_excel = int(summary.get("unmatchedExcelCount") or 0)
            has_history_rows = (
                abs(float(item.get("currentCacheAmount") or 0)) > 0.005
                or unmatched_cache > 0
                or amount_diff_count > 0
            )
            needs_ocr = bool(coverage.get("needsOcr")) or str(item.get("extractionPrerequisite") or "") == "pdf_text_layer_empty_requires_ocr"
            root_reasons = []
            if needs_ocr:
                root_reasons.append("PDF 无可读取文本层")
            if abs(amount_delta) > 0.005:
                if has_history_rows:
                    direction = "历史识别金额高于账单" if amount_delta > 0 else "历史识别金额低于账单"
                else:
                    direction = "当前可用 PDF 明细高于账单" if amount_delta > 0 else "当前没有可用 PDF 明细覆盖账单"
                root_reasons.append(f"{direction} ${abs(amount_delta):,.2f}")
            if exception_count:
                root_reasons.append(f"员工级异常 {exception_count} 项")
            if unmatched_cache or unmatched_excel:
                if has_history_rows:
                    root_reasons.append(f"历史识别多出 {unmatched_cache} 人、账单有但历史识别缺失 {unmatched_excel} 人")
                else:
                    root_reasons.append(f"当前可用明细多出 {unmatched_cache} 人、账单有但当前明细缺失 {unmatched_excel} 人")
            item["reviewFocus"] = label
            item["matchReason"] = "；".join(root_reasons) if root_reasons else "历史识别缓存需人工复核"
            item["businessQuestion"] = (
                f"{item.get('sourceFile') or '该 PDF'} 是否需要重新图片识别，并用新识别结果替换当前员工明细候选？"
                "必须先预览员工级影响，再决定是否采纳。"
                if collection_name == "tasks"
                else f"{item.get('sourceFile') or '该 PDF'} 的历史识别缓存是否可作为复核证据？需先预览员工级差异，再决定是否确认。"
            )
            item["impactSummary"] = _build_reocr_impact_summary(
                amount_delta=amount_delta,
                exception_count=exception_count,
                unmatched_cache=unmatched_cache,
                unmatched_excel=unmatched_excel,
                has_history_rows=has_history_rows,
            )
            item["cannotAutoResolveReason"] = (
                "图片识别会替换员工级 PDF 明细，必须经过范围校验、影响预览和人工确认，不能自动写入正式结果。"
                if collection_name == "tasks"
                else "历史识别缓存不是本次确定性抽取结果，只能作为待复核证据，确认前不能自动影响核对结论。"
            )


def _build_reocr_impact_summary(
    *,
    amount_delta: float,
    exception_count: int,
    unmatched_cache: int,
    unmatched_excel: int,
    has_history_rows: bool = True,
) -> str:
    parts: List[str] = []
    if abs(float(amount_delta or 0)) > 0.005:
        if has_history_rows:
            direction = "历史识别金额高于账单" if amount_delta > 0 else "历史识别金额低于账单"
        else:
            direction = "当前可用 PDF 明细高于账单" if amount_delta > 0 else "当前没有可用 PDF 明细覆盖账单"
        parts.append(f"{direction} ${abs(float(amount_delta)):,.2f}")
    if int(exception_count or 0):
        parts.append(f"员工级异常 {int(exception_count)} 项")
    if int(unmatched_cache or 0) or int(unmatched_excel or 0):
        if has_history_rows:
            parts.append(f"历史识别多出 {int(unmatched_cache or 0)} 人，账单有但历史识别缺失 {int(unmatched_excel or 0)} 人")
        else:
            parts.append(f"当前可用明细多出 {int(unmatched_cache or 0)} 人，账单有但当前明细缺失 {int(unmatched_excel or 0)} 人")
    return "；".join(parts) if parts else "金额和员工明细需预览确认"


def _iter_material_files(root: Path, *, max_depth: int) -> Iterable[Path]:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if _is_ignored_path(path):
            continue
        try:
            depth = len(path.relative_to(root).parts) - 1
        except ValueError:
            continue
        if depth > max_depth:
            continue
        yield path


def _is_ignored_path(path: Path) -> bool:
    name = path.name
    if name.startswith(".") or name.startswith("~$"):
        return True
    return any(part.startswith(".") or part == "__pycache__" for part in path.parts)


def _material_file_record(path: Path, root: Path) -> Dict[str, Any] | None:
    suffix = path.suffix.lower()
    if suffix not in BUSINESS_EXTENSIONS | DOCUMENT_EXTENSIONS | SCRIPT_EXTENSIONS:
        return None
    relative = path.relative_to(root)
    relative_path = relative.as_posix()
    relative_directory = relative.parent.as_posix()
    category = _classify_material_file(path)
    supplier = _infer_supplier(" ".join(relative.parts))
    warehouse_ids = _infer_warehouse_ids(path.name)
    return {
        "path": str(path),
        "relativePath": relative_path,
        "directory": relative_directory if relative_directory != "." else "",
        "filename": path.name,
        "extension": suffix,
        "category": category,
        "supplier": supplier,
        "warehouseIds": warehouse_ids,
        "periodHint": _infer_period_hint(" ".join(relative.parts)),
        "uploadable": category in {"invoice_pdf", "workbook_bill"},
        "sizeBytes": path.stat().st_size,
    }


def _classify_material_file(path: Path) -> str:
    suffix = path.suffix.lower()
    name = path.name.lower()
    if suffix == ".pdf":
        if any(token in name for token in ("supplement", "timecard", "time card")):
            return "supporting_pdf"
        return "invoice_pdf"
    if suffix in WORKBOOK_EXTENSIONS:
        if any(token in name for token in ("员工账单", "bill", "账单", "warehouse")):
            return "workbook_bill"
        if any(token in name for token in ("profile", "mapping", "config", "规则")):
            return "config_workbook"
        return "workbook_bill"
    if suffix == ".eml":
        return "email_context"
    if suffix in {".html"}:
        return "historical_output"
    if suffix in DOCUMENT_EXTENSIONS:
        return "document"
    if suffix in SCRIPT_EXTENSIONS:
        return "tooling"
    return "other"


def _build_candidate_batches(files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for item in files:
        grouped[_candidate_batch_directory(item)].append(item)

    batches = []
    for directory, rows in sorted(grouped.items()):
        invoices = [row for row in rows if row["category"] == "invoice_pdf"]
        workbooks = [row for row in rows if row["category"] == "workbook_bill"]
        if not invoices or not workbooks:
            continue
        supplier = _choose_supplier(rows)
        period_hint = _choose_period(rows)
        warehouse_ids = sorted({wid for row in invoices + workbooks for wid in row.get("warehouseIds", [])}, key=_warehouse_sort_key)
        limitations = _batch_limitations(rows)
        batches.append(
            {
                "batchKey": _safe_batch_key(directory or "root"),
                "directory": directory,
                "supplier": supplier,
                "periodHint": period_hint,
                "invoicePdfCount": len(invoices),
                "workbookCount": len(workbooks),
                "uploadableFileCount": len(invoices) + len(workbooks),
                "supportingFileCount": sum(1 for row in rows if row["category"] not in {"invoice_pdf", "workbook_bill"}),
                "warehouseIds": warehouse_ids,
                "invoiceFiles": [_small_file_ref(row) for row in invoices],
                "pdfFiles": [_small_file_ref(row) for row in invoices],
                "workbookFiles": [_small_file_ref(row) for row in workbooks],
                "replayReady": True,
                "limitations": limitations,
                "expectedRisks": limitations,
            }
        )
    return batches


def _candidate_batch_directory(item: Dict[str, Any]) -> str:
    relative_path = Path(str(item.get("relativePath") or ""))
    if len(relative_path.parts) > 1:
        return relative_path.parts[0]
    return str(item.get("directory") or "")


def _build_one_replay_plan(root: str, batch: Dict[str, Any]) -> Dict[str, Any]:
    risks = list(batch.get("limitations") or [])
    mapping_candidates = []
    for workbook in batch.get("workbookFiles", []) or []:
        mapping_candidates.append(_workbook_mapping_candidate(Path(root) / workbook["relativePath"], workbook["relativePath"]))
    bill_mapping_candidates = [item for item in mapping_candidates if not item.get("error")]
    excluded_mapping_candidates = [item for item in mapping_candidates if item.get("error")]
    supplier = batch.get("supplier") or "unknown"
    if supplier == "unknown":
        supplier = _supplier_from_mapping_candidates(bill_mapping_candidates) or "unknown"
    if supplier == "unknown":
        risks.append("未识别供应商，需要人工确认 supplier。")
    period_hint = batch.get("periodHint", "") or _period_hint_from_mapping_candidates(bill_mapping_candidates)
    if not period_hint:
        risks.append("未识别到账期，需要人工确认账期开始和结束日期。")
    if len(bill_mapping_candidates) > 1 and not _is_multi_warehouse_workbook_set(
        bill_mapping_candidates,
        batch.get("invoiceFiles", []),
    ):
        risks.append("目录包含多个可用账单 workbook，需要确认主账单。")
    if excluded_mapping_candidates:
        excluded_names = "、".join(item.get("filename") or item.get("relativePath", "") for item in excluded_mapping_candidates[:3])
        risks.append(f"部分 Excel 无有效账单金额映射，已按辅助材料排除: {excluded_names}")
    if not bill_mapping_candidates:
        risks.append("未找到可用于核对的主账单 workbook，需要人工确认账单文件。")
    return {
        "batchKey": batch["batchKey"],
        "directory": batch["directory"],
        "supplier": supplier,
        "periodHint": period_hint,
        "warehouseIds": batch.get("warehouseIds", []),
        "uploadPlan": {
            "pdfFiles": [item["relativePath"] for item in batch.get("invoiceFiles", [])],
            "workbookFiles": [item["relativePath"] for item in bill_mapping_candidates],
        },
        "mappingCandidates": bill_mapping_candidates,
        "excludedWorkbookFiles": [
            {
                "relativePath": item.get("relativePath", ""),
                "filename": item.get("filename", ""),
                "reason": item.get("error", ""),
            }
            for item in excluded_mapping_candidates
        ],
        "expectedRisks": risks,
        "replayReady": bool(batch.get("invoiceFiles")) and bool(bill_mapping_candidates),
        "replayMode": "deterministic_first",
        "aiAllowedFor": ["异常解释", "规则建议", "Profile建议", "低置信度修正"],
    }


def _workbook_mapping_candidate(path: Path, relative_path: str) -> Dict[str, Any]:
    payload = {
        "relativePath": relative_path,
        "filename": path.name,
        "sheets": [],
        "sheetName": "",
        "headers": [],
        "suggestedMapping": {},
        "previewRowCount": 0,
        "error": "",
    }
    try:
        sheets = list_workbook_sheets(path)
        payload["sheets"] = sheets
        if not sheets:
            payload["error"] = "Workbook 无工作表。"
            return payload
        preferred = _choose_sheet_for_mapping(sheets)
        suggestion = suggest_mapping(path, preferred)
        payload.update(
            {
                "sheetName": suggestion.get("sheetName") or preferred,
                "headers": suggestion.get("headers") or [],
                "suggestedMapping": suggestion.get("suggestedMapping") or {},
                "periodHint": _period_hint_from_preview_rows(suggestion.get("previewRows") or []),
                "supplierHint": _supplier_hint_from_preview_rows(suggestion.get("previewRows") or []),
                "warehouseIds": _infer_warehouse_ids(path.name),
                "previewRowCount": len(suggestion.get("previewRows") or []),
            }
        )
        missing = [key for key in ("name", "hours", "amount") if not payload["suggestedMapping"].get(key)]
        if missing:
            payload["error"] = f"缺少必要映射: {', '.join(missing)}"
    except Exception as exc:  # noqa: BLE001 - 计划生成不能因单个 workbook 中断。
        payload["error"] = str(exc)
    return payload


def _is_multi_warehouse_workbook_set(mapping_candidates: List[Dict[str, Any]], invoice_files: List[Dict[str, Any]]) -> bool:
    workbook_ids = []
    for candidate in mapping_candidates:
        ids = candidate.get("warehouseIds") or []
        if len(ids) != 1:
            return False
        workbook_ids.append(str(ids[0]))
    if len(set(workbook_ids)) != len(workbook_ids):
        return False
    invoice_ids = {str(wid) for item in invoice_files for wid in item.get("warehouseIds", [])}
    return bool(invoice_ids) and set(workbook_ids).issubset(invoice_ids)


def _supplier_from_mapping_candidates(mapping_candidates: List[Dict[str, Any]]) -> str:
    for candidate in mapping_candidates:
        supplier_hint = str(candidate.get("supplierHint") or "").strip()
        if supplier_hint:
            inferred = _infer_supplier(supplier_hint)
            return inferred or _normalize_supplier_name(supplier_hint)
    return ""


def _period_hint_from_mapping_candidates(mapping_candidates: List[Dict[str, Any]]) -> str:
    for candidate in mapping_candidates:
        period_hint = str(candidate.get("periodHint") or "").strip()
        if period_hint:
            return period_hint
    return ""


def _supplier_hint_from_preview_rows(rows: List[Dict[str, Any]]) -> str:
    for row in rows[:10]:
        value = _first_row_value(row, ("供应商名称", "Company Name", "Supplier Name", "supplier"))
        if value:
            return value
    return ""


def _period_hint_from_preview_rows(rows: List[Dict[str, Any]]) -> str:
    for row in rows[:10]:
        start = _first_row_value(row, ("核算开始日期", "账期开始", "Accounting start date", "start date"))
        end = _first_row_value(row, ("核算结束日期", "账期结束", "Accounting end date", "end date"))
        if start and end:
            return f"{start}~{end}"
    return ""


def _first_row_value(row: Dict[str, Any], headers: tuple[str, ...]) -> str:
    normalized = {str(key).strip().lower(): value for key, value in row.items()}
    for header in headers:
        value = normalized.get(header.lower())
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _choose_sheet_for_mapping(sheets: List[str]) -> str:
    preferred_tokens = ("员工账单", "employee", "detail", "账单", "sheet")
    for sheet in sheets:
        lowered = sheet.lower()
        if any(token.lower() in lowered for token in preferred_tokens):
            return sheet
    return sheets[0]


def _small_file_ref(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "relativePath": row["relativePath"],
        "filename": row["filename"],
        "category": row["category"],
        "warehouseIds": row.get("warehouseIds", []),
        "sizeBytes": row.get("sizeBytes", 0),
    }


def _choose_supplier(rows: List[Dict[str, Any]]) -> str:
    suppliers = [row.get("supplier", "") for row in rows if row.get("supplier")]
    if suppliers:
        return max(set(suppliers), key=suppliers.count)
    return "unknown"


def _choose_period(rows: List[Dict[str, Any]]) -> str:
    periods = [row.get("periodHint", "") for row in rows if row.get("periodHint")]
    return max(set(periods), key=periods.count) if periods else ""


def _infer_supplier(text: str) -> str:
    normalized = text.lower()
    checks = [
        ("workforce", ("workforce", "work force")),
        ("fairway", ("fairway",)),
        ("osi", ("osi", "one source", "onesource")),
        ("oss", ("oss", "one stop", "elogis service")),
        ("sss", ("strategic staffing", "sss ")),
        ("grande", ("grande", "gs invoice")),
        ("prompt", ("prompt priority", "prompt", "china express")),
        ("citistaff", ("citistaff", "citi staff")),
    ]
    for supplier, tokens in checks:
        if any(token in normalized for token in tokens):
            return supplier
    return ""


def _infer_warehouse_ids(name: str) -> List[str]:
    ids = set()
    for match in re.finditer(r"\bIn\s*(\d{2})\d{4}\b", name, flags=re.IGNORECASE):
        ids.add(str(int(match.group(1))))
    for pattern in (
        r"#\s*(\d{1,3})",
        r"\bNJ\s*(\d{1,3})\b",
        r"\bDEPT#?\s*(\d{1,3})\b",
        r"\b(\d{1,3})\s*仓\b",
    ):
        for match in re.finditer(pattern, name, flags=re.IGNORECASE):
            ids.add(str(int(match.group(1))))
    return sorted(ids, key=_warehouse_sort_key)


def _infer_period_hint(text: str) -> str:
    patterns = [
        r"(\d{1,2}\.\d{1,2})-(\d{1,2}\.\d{1,2})",
        r"(\d{2}\.\d{2}\.\d{4})-(\d{2}\.\d{2}\.\d{4})",
        r"WE\s*(\d{6})",
        r"W\.E\s*(\d{2}\.\d{2}\.\d{2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(0)
    return ""


def _batch_limitations(rows: List[Dict[str, Any]]) -> List[str]:
    limitations = []
    if any(row["category"] == "email_context" for row in rows):
        limitations.append("目录包含邮件上下文，不能作为上传附件，但可作为人工说明。")
    if any(row["category"] == "supporting_pdf" for row in rows):
        limitations.append("目录包含 supporting PDF，只读验证时需确认是否参与金额核对。")
    uploadable_directories = {
        str(row.get("directory") or "")
        for row in rows
        if row["category"] in {"invoice_pdf", "workbook_bill"}
    }
    if len(uploadable_directories) > 1:
        limitations.append("发票和账单分布在子目录中，系统已按父目录合并为一个材料批次。")
    return limitations


def _safe_batch_key(value: str) -> str:
    key = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "_", value).strip("_")
    return key or "batch"


def _warehouse_sort_key(value: str) -> tuple[int, str]:
    try:
        return (0, f"{int(value):04d}")
    except (TypeError, ValueError):
        return (1, str(value))
