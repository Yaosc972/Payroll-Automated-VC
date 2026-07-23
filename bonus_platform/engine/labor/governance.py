from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .compare import compare_labor_items
from .extract import _warehouse_id_from_filename
from .models import LaborLineItem, line_items_from_dicts
from .parsing import parse_number


def build_rule_change_candidate(
    *,
    rule_id: str,
    title: str,
    description: str,
    supplier: str,
    source: str,
    proposed_by: str = "ai",
    evidence: List[Dict[str, Any]] | None = None,
    conditions: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Create a governance record for a proposed rule/Profile change.

    The record is intentionally non-effective. It can be stored, reviewed, and
    replayed, but it must not be applied until a user confirms it.
    """
    return {
        "ruleId": rule_id,
        "title": title,
        "description": description,
        "supplier": supplier,
        "source": source,
        "proposedBy": proposed_by,
        "decision": "candidate_only",
        "status": "pending_user_confirmation",
        "requiresConfirmation": True,
        "version": 1,
        "conditions": conditions or {},
        "evidence": evidence or [],
        "auditTrail": [
            {
                "action": "created",
                "actor": proposed_by,
                "reason": source,
            }
        ],
    }


def summarize_rule_replay(candidate: Dict[str, Any], replay_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Summarize historical replay impact for a rule candidate.

    replay_results rows are intentionally plain dicts so the function can be
    used by tests, batch metadata, or future UI code without coupling to app.py.
    Expected row fields include: runId, supplier, periodStart, periodEnd,
    beforeStatus, afterStatus, beforeIssueCount, afterIssueCount.
    """
    fixed = []
    regressions = []
    unchanged = []
    for result in replay_results:
        before_status = str(result.get("beforeStatus") or "")
        after_status = str(result.get("afterStatus") or "")
        before_issues = int(result.get("beforeIssueCount") or 0)
        after_issues = int(result.get("afterIssueCount") or 0)
        row = {
            "runId": result.get("runId", ""),
            "supplier": result.get("supplier", ""),
            "periodStart": result.get("periodStart", ""),
            "periodEnd": result.get("periodEnd", ""),
            "beforeStatus": before_status,
            "afterStatus": after_status,
            "beforeIssueCount": before_issues,
            "afterIssueCount": after_issues,
            "impact": _replay_impact(before_status, after_status, before_issues, after_issues),
        }
        if row["impact"] == "fixed":
            fixed.append(row)
        elif row["impact"] == "regression":
            regressions.append(row)
        else:
            unchanged.append(row)

    decision = "ready_for_user_confirmation" if fixed and not regressions else "blocked_by_replay_regression" if regressions else "needs_more_replay_evidence"
    return {
        "ruleId": candidate.get("ruleId", ""),
        "decision": decision,
        "requiresConfirmation": True,
        "candidateStatus": candidate.get("status", "pending_user_confirmation"),
        "summary": {
            "replayedCount": len(replay_results),
            "fixedCount": len(fixed),
            "regressionCount": len(regressions),
            "unchangedCount": len(unchanged),
        },
        "fixed": fixed,
        "regressions": regressions,
        "unchanged": unchanged,
    }


def summarize_rule_auto_replay(
    candidate: Dict[str, Any],
    historical_runs: List[Dict[str, Any]],
    *,
    current_run_id: str = "",
    limit: int = 20,
) -> Dict[str, Any]:
    """Build replay results from stored historical batch diagnostics.

    This is a deterministic metadata replay. It does not re-extract PDFs or
    invoke AI; it evaluates whether the candidate's declared conditions match
    historical diagnostic issue codes and estimates the before/after issue
    counts for governance review.
    """
    replay_results: List[Dict[str, Any]] = []
    for run in historical_runs:
        if len(replay_results) >= limit:
            break
        result = _metadata_replay_result(candidate, run, current_run_id=current_run_id)
        if result:
            replay_results.append(result)

    summary = summarize_rule_replay(candidate, replay_results)
    summary["mode"] = "metadata_signal_replay"
    summary["replayResults"] = replay_results
    summary["limitations"] = [
        "本回放基于历史批次 metadata 中的诊断信号、质量等级和异常数，不重新抽取 PDF，也不调用 AI。",
        "确认生产规则前，仍需结合真实材料端到端回放或人工复核关键样本。",
    ]
    return summary


def confirm_rule_candidate(
    candidate: Dict[str, Any],
    replay_summary: Dict[str, Any],
    *,
    confirmed_by: str,
    reason: str,
) -> Dict[str, Any]:
    """Create an active rule version from a candidate after replay review."""
    if replay_summary.get("decision") != "ready_for_user_confirmation":
        raise ValueError("规则候选未通过历史影响预览，不能确认生效。")
    audit_trail = list(candidate.get("auditTrail") or [])
    audit_trail.append(
        {
            "action": "confirmed",
            "actor": confirmed_by,
            "reason": reason,
            "replaySummary": replay_summary.get("summary", {}),
        }
    )
    return {
        **candidate,
        "decision": "active",
        "status": "active",
        "requiresConfirmation": False,
        "version": int(candidate.get("version") or 1),
        "confirmedBy": confirmed_by,
        "confirmationReason": reason,
        "replaySummary": replay_summary.get("summary", {}),
        "auditTrail": audit_trail,
    }


def rollback_rule_version(
    active_rule: Dict[str, Any],
    *,
    rolled_back_by: str,
    reason: str,
    target_version: int | None = None,
) -> Dict[str, Any]:
    """Create a rollback record for an active rule version."""
    current_version = int(active_rule.get("version") or 1)
    rollback_target = target_version if target_version is not None else max(current_version - 1, 0)
    audit_trail = list(active_rule.get("auditTrail") or [])
    audit_trail.append(
        {
            "action": "rolled_back",
            "actor": rolled_back_by,
            "reason": reason,
            "fromVersion": current_version,
            "toVersion": rollback_target,
        }
    )
    return {
        **active_rule,
        "decision": "rolled_back",
        "status": "rolled_back",
        "rolledBackBy": rolled_back_by,
        "rollbackReason": reason,
        "rollbackToVersion": rollback_target,
        "auditTrail": audit_trail,
    }


def audit_ai_page_cache_candidates(pdf_paths: List[Path]) -> Dict[str, Any]:
    """Build a governance view of historical AI page caches.

    Historical page caches are useful evidence, but they are not deterministic
    reconciliation results. This function deliberately returns candidate-only
    records that require user confirmation before they can affect a conclusion.
    """
    candidates = [_audit_one_pdf_cache(path) for path in pdf_paths]
    return {
        "decision": "candidate_only",
        "requiresConfirmation": True,
        "message": "历史图片识别记录只能作为待复核证据，不能直接覆盖确定性核对结论。",
        "files": candidates,
        "summary": {
            "fileCount": len(candidates),
            "candidateFileCount": sum(1 for item in candidates if item["rowCount"] > 0),
            "candidateAmountTotal": round(sum(float(item["candidateAmountTotal"]) for item in candidates), 2),
        },
    }


def build_ai_cache_reconciliation_preview(
    pdf_paths: List[Path],
    excel_rows: List[LaborLineItem],
    *,
    amount_tolerance: float,
    hours_tolerance: float,
    confidence_threshold: float,
    currency: str = "USD",
) -> Dict[str, Any]:
    """Compare historical AI cache rows to Excel as candidate-only evidence.

    This preview is intentionally read-only. It helps a reviewer understand
    whether cached AI extraction is close enough to inspect, but it must not
    promote cached rows into deterministic reconciliation results.
    """
    cache_rows = _cache_line_items(pdf_paths, currency=currency)
    comparison = compare_labor_items(
        cache_rows,
        excel_rows,
        amount_tolerance=amount_tolerance,
        hours_tolerance=hours_tolerance,
        confidence_threshold=confidence_threshold,
    )
    exception_rows = [row for row in comparison["rows"] if row.get("matchStatus") != "通过"]
    file_quality = _ai_cache_file_quality(
        pdf_paths,
        excel_rows,
        amount_tolerance=amount_tolerance,
        hours_tolerance=hours_tolerance,
        confidence_threshold=confidence_threshold,
        currency=currency,
    )
    return {
        "decision": "candidate_only",
        "requiresConfirmation": bool(cache_rows),
        "message": "历史图片识别记录仅用于辅助复核，不能直接替代确定性 PDF 明细。",
        "summary": {
            "candidateRowCount": len(cache_rows),
            "excelRowCount": len(excel_rows),
            "passedCount": sum(1 for row in comparison["rows"] if row.get("matchStatus") == "通过"),
            "exceptionCount": comparison["summary"].get("exceptionCount", 0),
            "cacheAmountTotal": comparison["summary"].get("pdfAmountTotal", 0),
            "excelAmountTotal": comparison["summary"].get("excelAmountTotal", 0),
            "amountDeltaTotal": comparison["summary"].get("amountDeltaTotal", 0),
            "matchRate": comparison["summary"].get("matchRate", 0),
            "reviewableFileCount": sum(1 for row in file_quality if row.get("decision") == "reviewable_candidate"),
            "needsReocrFileCount": sum(1 for row in file_quality if row.get("decision") == "needs_reocr"),
        },
        "fileQuality": file_quality,
        "rows": comparison["rows"][:20],
        "exceptionRows": exception_rows[:20],
        "candidateMatches": comparison.get("candidateMatches", [])[:20],
    }


def build_reocr_candidate_plan(file_quality: List[Dict[str, Any]], *, amount_tolerance: float) -> Dict[str, Any]:
    """Create candidate-only OCR tasks from file-level AI cache quality."""
    tasks = []
    reviewable = []
    for row in file_quality:
        decision = row.get("decision")
        if decision == "needs_reocr":
            tasks.append(
                {
                    "sourceFile": row.get("sourceFile", ""),
                    "warehouseId": row.get("warehouseId", ""),
                    "reason": row.get("recommendation", ""),
                    "currentCacheAmount": row.get("cacheAmountTotal", 0),
                    "expectedExcelAmount": row.get("excelAmountTotal", 0),
                    "amountDelta": row.get("amountDelta", 0),
                    "expectedExcelRowCount": row.get("excelRowCount", 0),
                    "diagnostics": row.get("diagnostics", {}),
                    "focusEmployees": _reocr_focus_employee_rows(row.get("diagnostics", {})),
                    "amountTolerance": amount_tolerance,
                    "confirmationGate": "新图片识别结果金额需与同仓库 Excel 金额在容差内，员工级异常需可解释，且必须业务确认。",
                }
            )
        elif decision == "reviewable_candidate":
            reviewable.append(
                {
                    "sourceFile": row.get("sourceFile", ""),
                    "warehouseId": row.get("warehouseId", ""),
                    "currentCacheAmount": row.get("cacheAmountTotal", 0),
                    "expectedExcelAmount": row.get("excelAmountTotal", 0),
                    "amountDelta": row.get("amountDelta", 0),
                    "diagnostics": row.get("diagnostics", {}),
                    "focusEmployees": _reocr_focus_employee_rows(row.get("diagnostics", {})),
                    "recommendation": row.get("recommendation", ""),
                }
            )
    return {
        "decision": "candidate_only",
        "requiresConfirmation": bool(tasks or reviewable),
        "message": "图片重新识别计划只生成待复核任务，不会自动写入规则或改变核对结论。",
        "summary": {
            "taskCount": len(tasks),
            "reviewableCandidateCount": len(reviewable),
            "totalExpectedExcelAmount": round(sum(float(task.get("expectedExcelAmount") or 0) for task in tasks), 2),
            "totalCurrentCacheAmount": round(sum(float(task.get("currentCacheAmount") or 0) for task in tasks), 2),
        },
        "tasks": tasks,
        "reviewableCandidates": reviewable,
    }


def _reocr_focus_employee_rows(diagnostics: Dict[str, Any], *, limit: int = 5) -> List[Dict[str, Any]]:
    """Summarize the employee rows that explain why a file needs re-OCR/review."""
    if not isinstance(diagnostics, dict):
        return []
    rows: List[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for collection_name in ("topDifferences", "missingInCache", "extraInCache"):
        for item in diagnostics.get(collection_name, []) or []:
            if not isinstance(item, dict):
                continue
            employee_name = str(item.get("employeeName") or "").strip()
            match_status = str(item.get("matchStatus") or "").strip()
            identity = (employee_name, match_status)
            if not employee_name or identity in seen:
                continue
            seen.add(identity)
            rows.append(
                {
                    "employeeName": employee_name,
                    "matchStatus": match_status,
                    "amountDelta": round(float(item.get("amountDelta") or 0), 2),
                    "hoursDelta": round(float(item.get("hoursDelta") or 0), 2),
                    "sourceRefs": item.get("sourceRefs", ""),
                }
            )
            if len(rows) >= limit:
                return rows
    return rows


def replay_reocr_candidate_result(
    task: Dict[str, Any],
    candidate_rows: List[Dict[str, Any]] | List[LaborLineItem],
    excel_rows: List[LaborLineItem],
    *,
    amount_tolerance: float,
    hours_tolerance: float,
    confidence_threshold: float,
) -> Dict[str, Any]:
    """Replay a new OCR candidate against Excel before user confirmation."""
    candidate_items = _coerce_candidate_items(task, candidate_rows)
    warehouse_id = str(task.get("warehouseId") or "").strip()
    scoped_excel_rows = [
        row for row in excel_rows
        if not warehouse_id or str(row.warehouse_id or "").strip() == warehouse_id
    ]
    comparison = compare_labor_items(
        candidate_items,
        scoped_excel_rows,
        amount_tolerance=amount_tolerance,
        hours_tolerance=hours_tolerance,
        confidence_threshold=confidence_threshold,
    )
    from .ocr_name_gate import build_ocr_name_gate

    name_gate = build_ocr_name_gate(
        candidate_items,
        scoped_excel_rows,
        amount_tolerance=amount_tolerance,
        hours_tolerance=hours_tolerance,
    )
    summary = comparison["summary"]
    expected_amount = round(float(task.get("expectedExcelAmount") or summary.get("excelAmountTotal") or 0), 2)
    candidate_amount = round(float(summary.get("pdfAmountTotal") or 0), 2)
    amount_delta = round(candidate_amount - expected_amount, 2)
    amount_passed = abs(amount_delta) <= amount_tolerance
    exception_count = int(summary.get("exceptionCount") or 0)
    low_confidence_count = int(summary.get("lowConfidenceCount") or 0)
    strict_name_pending = int(name_gate["summary"].get("review") or 0) + int(name_gate["summary"].get("unmatched") or 0)
    ready = amount_passed and exception_count == 0 and low_confidence_count == 0 and strict_name_pending == 0
    blockers = []
    if not amount_passed:
        blockers.append("candidate_amount_mismatch")
    if exception_count:
        blockers.append("employee_level_exceptions")
    if low_confidence_count:
        blockers.append("low_confidence_candidates")
    if strict_name_pending and exception_count == 0:
        blockers.append("strict_name_review_required")
    decision = "ready_for_user_confirmation" if ready else "blocked_by_replay"
    exception_rows = [row for row in comparison["rows"] if row.get("matchStatus") != "通过"]
    return {
        "decision": decision,
        "requiresConfirmation": True,
        "mode": "new_ocr_candidate_replay",
        "sourceFile": task.get("sourceFile", ""),
        "warehouseId": warehouse_id,
        "summary": {
            "candidateRowCount": len(candidate_items),
            "excelRowCount": len(scoped_excel_rows),
            "candidateAmountTotal": candidate_amount,
            "expectedExcelAmount": expected_amount,
            "amountDelta": amount_delta,
            "amountPassed": amount_passed,
            "exceptionCount": exception_count,
            "lowConfidenceCount": low_confidence_count,
            "fixedCacheDelta": round(abs(float(task.get("amountDelta") or 0)) - abs(amount_delta), 2),
        },
        "blockers": blockers,
        "comparison": summary,
        "comparisonRows": comparison["rows"],
        "previewRows": comparison["rows"][:50],
        "exceptionRows": exception_rows[:20],
        "candidateMatches": comparison.get("candidateMatches", [])[:20],
        "nameGate": name_gate,
        "diagnostics": task.get("diagnostics", {}),
        "confirmationGate": task.get("confirmationGate", ""),
    }


def replay_ai_cache_candidate_result(
    task: Dict[str, Any],
    pdf_path: Path,
    excel_rows: List[LaborLineItem],
    *,
    amount_tolerance: float,
    hours_tolerance: float,
    confidence_threshold: float,
    currency: str = "USD",
) -> Dict[str, Any]:
    """Replay existing local AI/OCR page cache as a candidate-only result.

    The cache is historical evidence, not a deterministic extraction result.
    This function intentionally delegates to the same replay gate used by new
    OCR uploads so cached rows must pass amount, employee, and confidence checks
    before a user can confirm them.
    """
    cache_rows = _cache_line_items_for_path(pdf_path, currency=currency)
    replay = replay_reocr_candidate_result(
        task,
        cache_rows,
        excel_rows,
        amount_tolerance=amount_tolerance,
        hours_tolerance=hours_tolerance,
        confidence_threshold=confidence_threshold,
    )
    replay["mode"] = "ai_cache_candidate_replay"
    replay["candidateSource"] = "local_ai_page_cache"
    replay["cacheFiles"] = [cache.name for cache in _page_cache_files(pdf_path)]
    replay["message"] = "本次预览使用本地历史图片识别记录，只生成待复核结果；确认前不会影响正式核对结论。"
    return replay


def _audit_one_pdf_cache(path: Path) -> Dict[str, Any]:
    rows = _load_page_cache_rows(path)
    row_count = len(rows)
    total = round(sum(parse_number(row.get("amount")) for row in rows), 2)
    confidences = [_confidence(row.get("confidence")) for row in rows if row.get("confidence") not in (None, "")]
    average_confidence = round(sum(confidences) / len(confidences), 3) if confidences else 0.0
    evidence = []
    for row in rows[:5]:
        evidence.append(
            {
                "employeeName": str(row.get("employee_name_raw") or row.get("employeeNameRaw") or row.get("employee_name") or row.get("employeeName") or ""),
                "amount": round(parse_number(row.get("amount")), 2),
                "sourcePageOrRow": _source_page_or_row(row),
                "evidenceText": str(row.get("evidence_text") or row.get("evidenceText") or "")[:200],
            }
        )
    return {
        "sourceFile": path.name,
        "warehouseId": _warehouse_id_from_filename(path.name),
        "rowCount": row_count,
        "candidateAmountTotal": total,
        "averageConfidence": average_confidence,
        "decision": "candidate_only",
        "requiresConfirmation": row_count > 0,
        "cacheFiles": [cache.name for cache in _page_cache_files(path)],
        "evidence": evidence,
    }


def _coerce_candidate_items(task: Dict[str, Any], rows: List[Dict[str, Any]] | List[LaborLineItem]) -> List[LaborLineItem]:
    if not rows:
        return []
    if isinstance(rows[0], LaborLineItem):
        return list(rows)  # type: ignore[arg-type]
    source_file = str(task.get("sourceFile") or "")
    warehouse_id = str(task.get("warehouseId") or "")
    normalized = []
    for row in rows:  # type: ignore[assignment]
        item = dict(row)
        item.setdefault("source_type", "new_ocr_candidate")
        item.setdefault("source_file", source_file)
        item.setdefault("warehouse_id", warehouse_id)
        normalized.append(item)
    return line_items_from_dicts(normalized)


def _cache_line_items(pdf_paths: List[Path], *, currency: str) -> List[LaborLineItem]:
    rows: List[LaborLineItem] = []
    for path in pdf_paths:
        rows.extend(_cache_line_items_for_path(path, currency=currency))
    return rows


def _cache_line_items_for_path(path: Path, *, currency: str) -> List[LaborLineItem]:
    rows: List[LaborLineItem] = []
    warehouse_id = _warehouse_id_from_filename(path.name)
    for row in _load_page_cache_rows(path):
        name = str(row.get("employee_name_raw") or row.get("employeeNameRaw") or row.get("employee_name") or row.get("employeeName") or "").strip()
        amount = parse_number(row.get("amount"))
        if not name or amount == 0:
            continue
        rows.append(
            LaborLineItem(
                source_type="ai_cache_candidate",
                source_file=path.name,
                source_page_or_row=_source_page_or_row(row),
                employee_id=str(row.get("employee_id") or row.get("employeeId") or "").strip(),
                employee_name_raw=name,
                hours=parse_number(row.get("hours")),
                amount=amount,
                currency=str(row.get("currency") or currency),
                confidence=_confidence(row.get("confidence")),
                evidence_text=str(row.get("evidence_text") or row.get("evidenceText") or ""),
                warehouse_id=str(row.get("warehouse_id") or row.get("warehouseId") or warehouse_id),
            )
        )
    return rows


def _ai_cache_file_quality(
    pdf_paths: List[Path],
    excel_rows: List[LaborLineItem],
    *,
    amount_tolerance: float,
    hours_tolerance: float,
    confidence_threshold: float,
    currency: str,
) -> List[Dict[str, Any]]:
    excel_by_warehouse: Dict[str, Dict[str, float]] = {}
    for row in excel_rows:
        warehouse_id = str(row.warehouse_id or "").strip()
        if not warehouse_id:
            continue
        group = excel_by_warehouse.setdefault(warehouse_id, {"amount": 0.0, "hours": 0.0, "count": 0.0})
        group["amount"] = round(group["amount"] + row.amount, 2)
        group["hours"] = round(group["hours"] + row.hours, 2)
        group["count"] += 1

    quality_rows = []
    for path in pdf_paths:
        audit = _audit_one_pdf_cache(path)
        warehouse_id = str(audit.get("warehouseId") or "")
        excel_group = excel_by_warehouse.get(warehouse_id, {"amount": 0.0, "hours": 0.0, "count": 0.0})
        cache_amount = round(float(audit.get("candidateAmountTotal") or 0), 2)
        excel_amount = round(float(excel_group.get("amount") or 0), 2)
        amount_delta = round(cache_amount - excel_amount, 2)
        cache_count = int(audit.get("rowCount") or 0)
        excel_count = int(excel_group.get("count") or 0)
        cache_items = _cache_line_items_for_path(path, currency=currency)
        scoped_excel_rows = [
            row for row in excel_rows
            if not warehouse_id or str(row.warehouse_id or "").strip() == warehouse_id
        ]
        diagnostics = _ai_cache_file_diagnostics(
            cache_items,
            scoped_excel_rows,
            amount_tolerance=amount_tolerance,
            hours_tolerance=hours_tolerance,
            confidence_threshold=confidence_threshold,
        )

        if not warehouse_id:
            decision = "missing_warehouse"
            recommendation = "缺少仓库号，需人工确认 PDF 与账单仓库关系。"
        elif excel_count == 0:
            decision = "no_excel_warehouse"
            recommendation = "账单中未找到同仓库记录，需确认上传材料是否匹配。"
        elif cache_count == 0:
            decision = "needs_reocr"
            recommendation = "该 PDF 没有可复核的历史图片识别记录，需重新识别后预览影响。"
        elif abs(amount_delta) <= amount_tolerance:
            decision = "reviewable_candidate"
            recommendation = "历史识别金额与账单同仓库金额一致，可作为人工复核证据。"
        else:
            decision = "needs_reocr"
            recommendation = "历史识别金额与账单同仓库金额不一致，建议重新识别后预览影响。"

        quality_rows.append(
            {
                "sourceFile": path.name,
                "warehouseId": warehouse_id,
                "cacheRowCount": cache_count,
                "excelRowCount": excel_count,
                "cacheAmountTotal": cache_amount,
                "excelAmountTotal": excel_amount,
                "amountDelta": amount_delta,
                "averageConfidence": audit.get("averageConfidence", 0),
                "decision": decision,
                "recommendation": recommendation,
                "diagnostics": diagnostics,
            }
        )
    return quality_rows


def _ai_cache_file_diagnostics(
    cache_items: List[LaborLineItem],
    excel_rows: List[LaborLineItem],
    *,
    amount_tolerance: float,
    hours_tolerance: float,
    confidence_threshold: float,
) -> Dict[str, Any]:
    comparison = compare_labor_items(
        cache_items,
        excel_rows,
        amount_tolerance=amount_tolerance,
        hours_tolerance=hours_tolerance,
        confidence_threshold=confidence_threshold,
    )
    exception_rows = [row for row in comparison["rows"] if row.get("matchStatus") != "通过"]
    top_differences = sorted(
        exception_rows,
        key=lambda row: (abs(float(row.get("amountDelta") or 0)), abs(float(row.get("hoursDelta") or 0))),
        reverse=True,
    )[:5]
    missing_in_cache = [
        _small_employee_diff(row)
        for row in exception_rows
        if row.get("matchStatus") == "Excel有PDF无"
    ][:5]
    extra_in_cache = [
        _small_employee_diff(row)
        for row in exception_rows
        if row.get("matchStatus") in {"PDF有Excel无", "低置信度抽取"}
    ][:5]
    suspected_pairs = _suspected_unmatched_name_pairs(
        [row for row in exception_rows if row.get("matchStatus") in {"PDF有Excel无", "低置信度抽取"}],
        [row for row in exception_rows if row.get("matchStatus") == "Excel有PDF无"],
        amount_tolerance=max(amount_tolerance, 0.05),
        hours_tolerance=max(hours_tolerance, 0.35),
    )
    root_cause_hints = _root_cause_hints(exception_rows, suspected_pairs)
    return {
        "summary": {
            "exceptionCount": comparison["summary"].get("exceptionCount", 0),
            "amountDiffCount": comparison["summary"].get("amountDiffCount", 0),
            "unmatchedCacheCount": comparison["summary"].get("unmatchedPdfCount", 0),
            "unmatchedExcelCount": comparison["summary"].get("unmatchedExcelCount", 0),
            "lowConfidenceCount": comparison["summary"].get("lowConfidenceCount", 0),
            "candidateMatchCount": len(comparison.get("candidateMatches", []) or []),
            "suspectedNamePairCount": len(suspected_pairs),
        },
        "topDifferences": [_small_employee_diff(row) for row in top_differences],
        "missingInCache": missing_in_cache,
        "extraInCache": extra_in_cache,
        "suspectedNamePairs": suspected_pairs[:5],
        "rootCauseHints": root_cause_hints,
        "recommendedAction": _recommended_reocr_action(root_cause_hints),
        "candidateMatches": comparison.get("candidateMatches", [])[:5],
    }


def _small_employee_diff(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "employeeName": row.get("employeeName", ""),
        "matchStatus": row.get("matchStatus", ""),
        "cacheAmount": row.get("pdfAmountTotal", 0),
        "excelAmount": row.get("excelAmountTotal", 0),
        "amountDelta": row.get("amountDelta", 0),
        "cacheHours": row.get("pdfHoursTotal", 0),
        "excelHours": row.get("excelHoursTotal", 0),
        "hoursDelta": row.get("hoursDelta", 0),
        "riskFlags": row.get("riskFlags", []),
        "sourceRefs": row.get("sourceRefs", ""),
    }


def _suspected_unmatched_name_pairs(
    extra_rows: List[Dict[str, Any]],
    missing_rows: List[Dict[str, Any]],
    *,
    amount_tolerance: float,
    hours_tolerance: float,
) -> List[Dict[str, Any]]:
    pairs: List[Dict[str, Any]] = []
    used_missing: set[str] = set()
    for extra in sorted(extra_rows, key=lambda row: abs(float(row.get("amountDelta") or 0)), reverse=True):
        best: Dict[str, Any] | None = None
        for missing in missing_rows:
            missing_key = str(missing.get("employeeKey") or missing.get("employeeName") or "")
            if missing_key in used_missing:
                continue
            amount_gap = round(float(extra.get("pdfAmountTotal") or 0) - float(missing.get("excelAmountTotal") or 0), 2)
            hours_gap = round(float(extra.get("pdfHoursTotal") or 0) - float(missing.get("excelHoursTotal") or 0), 2)
            if abs(amount_gap) > amount_tolerance or abs(hours_gap) > hours_tolerance:
                continue
            candidate = {
                "cacheEmployeeName": extra.get("employeeName", ""),
                "excelEmployeeName": missing.get("employeeName", ""),
                "cacheAmount": extra.get("pdfAmountTotal", 0),
                "excelAmount": missing.get("excelAmountTotal", 0),
                "amountGap": amount_gap,
                "cacheHours": extra.get("pdfHoursTotal", 0),
                "excelHours": missing.get("excelHoursTotal", 0),
                "hoursGap": hours_gap,
                "confidence": "medium",
                "recommendation": "金额/工时接近，优先人工确认是否为同一员工姓名映射；确认前不能自动清账。",
                "sourceRefs": "; ".join(ref for ref in [str(extra.get("sourceRefs") or ""), str(missing.get("sourceRefs") or "")] if ref),
            }
            if best is None or abs(candidate["amountGap"]) + abs(candidate["hoursGap"]) < abs(best["amountGap"]) + abs(best["hoursGap"]):
                best = candidate
        if best:
            pairs.append(best)
            used_missing.add(str(best.get("excelEmployeeName") or ""))
    return pairs


def _root_cause_hints(exception_rows: List[Dict[str, Any]], suspected_pairs: List[Dict[str, Any]]) -> List[str]:
    hints = []
    if suspected_pairs:
        hints.append("possible_name_mapping")
    if any(row.get("matchStatus") == "Excel有PDF无" for row in exception_rows):
        hints.append("possible_missing_cache_rows")
    if any(row.get("matchStatus") in {"PDF有Excel无", "低置信度抽取"} for row in exception_rows):
        hints.append("possible_extra_cache_rows")
    if any(row.get("matchStatus") == "金额差异" for row in exception_rows):
        hints.append("employee_amount_or_hours_mismatch")
    if any("疑似PDF合并员工" in (row.get("riskFlags") or []) for row in exception_rows):
        hints.append("possible_combined_pdf_row")
    return hints


def _recommended_reocr_action(root_cause_hints: List[str]) -> str:
    if root_cause_hints == ["possible_name_mapping"]:
        return "review_name_mapping_before_reocr"
    if "possible_name_mapping" in root_cause_hints:
        return "review_name_mapping_then_reocr_if_amounts_remain_unexplained"
    if "possible_missing_cache_rows" in root_cause_hints or "possible_extra_cache_rows" in root_cause_hints:
        return "reocr_with_employee_level_review"
    if "employee_amount_or_hours_mismatch" in root_cause_hints:
        return "review_amount_hours_basis_then_reocr_if_needed"
    return "review_file_manually"


def _load_page_cache_rows(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for cache_path in _page_cache_files(path):
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, list):
            continue
        rows.extend(row for row in payload if isinstance(row, dict))
    return rows


def _page_cache_files(path: Path) -> List[Path]:
    cache_dir = path.parent / ".ai_extract_cache"
    if not cache_dir.exists():
        return []
    return sorted(
        cache_path
        for cache_path in cache_dir.glob(f"{path.stem}_p*_*.json")
        if "_totals_" not in cache_path.name
    )


def _source_page_or_row(row: Dict[str, Any]) -> str:
    value = str(row.get("source_page_or_row") or row.get("sourcePageOrRow") or "").strip()
    if value.isdigit():
        return f"p{value}"
    if value:
        return value
    source_page = row.get("source_page")
    if source_page not in (None, ""):
        return f"p{source_page}"
    return ""


def _confidence(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _replay_impact(before_status: str, after_status: str, before_issues: int, after_issues: int) -> str:
    if after_status in {"critical", "failed", "error"} and before_status not in {"critical", "failed", "error"}:
        return "regression"
    if after_issues > before_issues:
        return "regression"
    if before_status != "ok" and after_status == "ok":
        return "fixed"
    if after_issues < before_issues:
        return "fixed"
    return "unchanged"


def _metadata_replay_result(candidate: Dict[str, Any], run: Dict[str, Any], *, current_run_id: str) -> Dict[str, Any] | None:
    run_id = str(run.get("id") or "")
    if not run_id:
        return None

    conditions = candidate.get("conditions") if isinstance(candidate.get("conditions"), dict) else {}
    supplier_scope = _condition_values(conditions, "supplier", "suppliers")
    run_supplier = str(run.get("supplierName") or run.get("supplier") or "")
    in_scope = not supplier_scope or _lower(run_supplier) in {_lower(value) for value in supplier_scope}

    diagnostics = run.get("reconciliationDiagnostics") if isinstance(run.get("reconciliationDiagnostics"), dict) else {}
    issues = diagnostics.get("issues") if isinstance(diagnostics.get("issues"), list) else []
    issue_codes = {str(issue.get("code") or "") for issue in issues if isinstance(issue, dict)}
    fix_issue_codes = _candidate_issue_codes(candidate)
    matched_issue_codes = sorted(issue_codes & fix_issue_codes)

    comparison_summary = run.get("comparisonSummary") if isinstance(run.get("comparisonSummary"), dict) else {}
    extraction_quality = run.get("extractionQuality") if isinstance(run.get("extractionQuality"), dict) else {}
    before_status = _run_status(diagnostics, extraction_quality, comparison_summary)
    before_issue_count = _metadata_issue_count(issues, comparison_summary, extraction_quality)
    critical_issue_codes = {
        str(issue.get("code") or "")
        for issue in issues
        if isinstance(issue, dict) and str(issue.get("level") or "") == "critical"
    }

    if not in_scope:
        after_issue_count = before_issue_count
        after_status = before_status
        impact_reason = "out_of_scope_supplier"
    elif matched_issue_codes:
        after_issue_count = max(0, before_issue_count - len(matched_issue_codes))
        remaining_critical = critical_issue_codes - set(matched_issue_codes)
        after_status = "critical" if remaining_critical else "ok" if after_issue_count == 0 else "warning"
        impact_reason = "matched_candidate_issue_codes"
    else:
        after_issue_count = before_issue_count
        after_status = before_status
        impact_reason = "no_matching_diagnostic_issue"

    return {
        "runId": run_id,
        "currentRun": run_id == current_run_id,
        "supplier": run_supplier,
        "periodStart": str(run.get("periodStart") or ""),
        "periodEnd": str(run.get("periodEnd") or ""),
        "beforeStatus": before_status,
        "afterStatus": after_status,
        "beforeIssueCount": before_issue_count,
        "afterIssueCount": after_issue_count,
        "matchedIssueCodes": matched_issue_codes,
        "issueCodes": sorted(code for code in issue_codes if code),
        "impactReason": impact_reason,
    }


def _candidate_issue_codes(candidate: Dict[str, Any]) -> set[str]:
    conditions = candidate.get("conditions") if isinstance(candidate.get("conditions"), dict) else {}
    explicit = _condition_values(conditions, "fixIssueCodes", "fix_issue_codes", "issueCodes", "issue_codes")
    if explicit:
        return {str(value) for value in explicit if str(value)}

    text = " ".join(
        str(candidate.get(key) or "")
        for key in ("ruleId", "title", "description", "source")
    ).lower()
    inferred: set[str] = set()
    if "warehouse" in text or "仓库" in text or "#n" in text:
        inferred.update({"missing_warehouse_id", "warehouse_mapping_errors", "warehouse_offsetting_deltas"})
    if "zero" in text or "scan" in text or "扫描" in text:
        inferred.add("zero_pdf_total")
    if "name" in text or "fuzzy" in text or "姓名" in text:
        inferred.add("warehouse_employee_attribution")
    if "amount" in text or "otws" in text or "basis" in text or "金额" in text or "口径" in text:
        inferred.add("amount_basis_mismatch")
    return inferred


def _condition_values(conditions: Dict[str, Any], *keys: str) -> List[str]:
    for key in keys:
        value = conditions.get(key)
        if isinstance(value, list):
            return [str(item) for item in value if str(item)]
        if value not in (None, ""):
            return [str(value)]
    return []


def _metadata_issue_count(
    issues: List[Dict[str, Any]],
    comparison_summary: Dict[str, Any],
    extraction_quality: Dict[str, Any],
) -> int:
    structured_issue_count = len([issue for issue in issues if isinstance(issue, dict)])
    quality_issues = extraction_quality.get("issues") if isinstance(extraction_quality.get("issues"), list) else []
    exception_count = int(comparison_summary.get("exceptionCount") or 0)
    return structured_issue_count + len(quality_issues) + exception_count


def _run_status(
    diagnostics: Dict[str, Any],
    extraction_quality: Dict[str, Any],
    comparison_summary: Dict[str, Any],
) -> str:
    for source in (diagnostics, extraction_quality, comparison_summary):
        level = str(source.get("level") or source.get("status") or "").lower()
        if level:
            return level
    return "ok" if int(comparison_summary.get("exceptionCount") or 0) == 0 else "warning"


def _lower(value: Any) -> str:
    return str(value or "").strip().lower()
