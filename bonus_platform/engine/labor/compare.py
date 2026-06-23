from __future__ import annotations

import math
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List

from .extract import _warehouse_id_from_filename
from .models import LaborComparisonRow, LaborLineItem, line_items_from_dicts
from .parsing import normalize_employee_name, normalize_workbuddy_name, pdf_name_to_first_last


# ---------------------------------------------------------------------------
# Adaptive tolerance
# ---------------------------------------------------------------------------

def _adaptive_tolerance(amount: float, base_tolerance: float = 0.05) -> float:
    """根据金额大小自适应调整容忍度。

    大金额允许更大的绝对差异，但保持相对差异在合理范围内。
    - 金额 <= $1,000: 使用基础容忍度
    - 金额 > $1,000: 容忍度按对数增长，例如 $50,000 → ~0.074
    """
    if amount <= 1000:
        return base_tolerance
    multiplier = 1 + math.log10(amount / 1000)
    return base_tolerance * multiplier


def amount_within_tolerance(delta: float, tolerance: float = 0.10) -> bool:
    """Compare money at cent precision so $0.10 is treated as within tolerance."""
    return round(abs(float(delta or 0)), 2) <= round(abs(float(tolerance or 0)), 2)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compare_labor_items(
    pdf_rows: List[LaborLineItem],
    excel_rows: List[LaborLineItem],
    *,
    amount_tolerance: float = 0.05,
    hours_tolerance: float = 0.1,
    confidence_threshold: float = 0.85,
    manual_name_mapping: Dict[str, str] | None = None,
) -> Dict[str, Any]:
    """Employee-level comparison between PDF and Excel rows."""
    pdf = _aggregate(pdf_rows)
    excel = _aggregate(excel_rows)
    rows = _match_employee_groups(pdf, excel,
                                  amount_tolerance=amount_tolerance,
                                  hours_tolerance=hours_tolerance,
                                  confidence_threshold=confidence_threshold,
                                  manual_name_mapping=manual_name_mapping)

    candidate_matches, promoted_pdf, promoted_excel = _suggest_unmatched_candidates(
        rows,
        pdf,
        excel,
        amount_tolerance=amount_tolerance,
        hours_tolerance=hours_tolerance,
    )
    rows = _apply_promotions(rows, candidate_matches, promoted_pdf, promoted_excel)
    offset_candidates = _suggest_residual_offset_candidates(rows)
    if offset_candidates:
        rows = _apply_residual_offset_flags(rows, offset_candidates)
        candidate_matches.extend(offset_candidates)
    summary = _build_summary(rows, pdf_rows, excel_rows, candidate_matches)
    return {"summary": summary, "rows": rows, "candidateMatches": candidate_matches}


def compare_by_warehouse(
    excel_rows_with_warehouse: List[Dict[str, Any]],
    pdf_totals: List[Dict[str, Any]] | None = None,
    pdf_rows: List[LaborLineItem] | None = None,
    amount_tolerance: float = 0.05,
    hours_tolerance: float = 0.1,
    confidence_threshold: float = 0.85,
    manual_name_mapping: Dict[str, str] | None = None,
) -> Dict[str, Any]:
    """Three-tier reconciliation: total → warehouse → employee.

    Two calling modes:
    - Fast mode (pdf_totals only): Tier 1 + Tier 2, no employee detail.
    - Full mode (pdf_rows): Tier 3 for warehouses that need employee comparison.

    If both are provided, pdf_totals drives Tier 1/2 and pdf_rows drives Tier 3
    only for warehouses with differences.
    """
    errors: List[str] = []

    # Tier 1: total amount comparison
    if pdf_totals:
        pdf_total = round(sum(float(t.get("total_amount") or 0) for t in pdf_totals), 2)
    elif pdf_rows:
        pdf_total = round(sum(r.amount for r in pdf_rows), 2)
    else:
        pdf_total = 0.0
    excel_total = round(sum(float(r.get("amount") or 0) for r in excel_rows_with_warehouse), 2)
    total_delta = round(pdf_total - excel_total, 2)
    effective_total_tolerance = _adaptive_tolerance(max(abs(pdf_total), abs(excel_total)), amount_tolerance)
    total_passed = amount_within_tolerance(total_delta, effective_total_tolerance)

    summary = {
        "pdfAmountTotal": pdf_total,
        "excelAmountTotal": excel_total,
        "amountDeltaTotal": total_delta,
        "totalPassed": total_passed,
        "warehouseCount": 0,
        "passedCount": 0,
        "exceptionCount": 0,
    }

    excel_by_wh, excel_errors = _group_excel_by_warehouse(excel_rows_with_warehouse)
    errors.extend(excel_errors)
    fallback_warehouse_id = next(iter(excel_by_wh), "") if len(excel_by_wh) == 1 else ""

    inferred_pdf_warehouses: Dict[str, str] = {}
    if pdf_totals:
        pdf_totals, inferred_pdf_warehouses = _infer_pdf_warehouses_from_excel_totals(
            pdf_totals,
            excel_by_wh,
            amount_tolerance=amount_tolerance,
        )

    # Tier 2: per-warehouse comparison
    if pdf_totals:
        pdf_by_wh: Dict[str, Dict[str, float]] = defaultdict(lambda: {"amount": 0.0, "count": 0})
        for t in pdf_totals:
            conflict = t.get("warehouse_conflict")
            if conflict:
                errors.append(
                    "仓库号冲突: "
                    f"{t.get('source_file', '')} 文件名={conflict.get('filename_warehouse_id', '')}, "
                    f"内容={conflict.get('text_warehouse_id', '')}"
                )
            wh = str(t.get("warehouse_id") or "")
            if not wh:
                if fallback_warehouse_id and len(pdf_totals) == 1:
                    wh = fallback_warehouse_id
                else:
                    errors.append(f"无法提取仓库号: {t.get('source_file', '')}")
                    continue
            pdf_by_wh[wh]["amount"] = round(pdf_by_wh[wh]["amount"] + float(t.get("total_amount") or 0), 2)
            pdf_by_wh[wh]["count"] += 1
        pdf_wh_amounts = dict(pdf_by_wh)
    else:
        pdf_wh_amounts = {}

    pdf_row_by_wh: Dict[str, List[LaborLineItem]] = {}
    if pdf_rows:
        pdf_row_by_wh, pdf_errors = _group_pdf_by_warehouse(
            pdf_rows,
            fallback_warehouse_id=fallback_warehouse_id,
            source_file_warehouse_map=inferred_pdf_warehouses,
        )
        errors.extend(pdf_errors)

    all_wh = sorted(set(pdf_wh_amounts) | set(pdf_row_by_wh) | set(excel_by_wh))
    warehouse_rows = []
    for wh in all_wh:
        # PDF amounts: prefer totals, fallback to rows
        if wh in pdf_wh_amounts:
            pdf_amount = pdf_wh_amounts[wh]["amount"]
            pdf_count = len(pdf_row_by_wh[wh]) if wh in pdf_row_by_wh else pdf_wh_amounts[wh]["count"]
        elif wh in pdf_row_by_wh:
            items = pdf_row_by_wh[wh]
            pdf_amount = round(sum(i.amount for i in items), 2)
            pdf_count = len(items)
        else:
            pdf_amount = 0.0
            pdf_count = 0

        excel_items = excel_by_wh.get(wh, [])
        excel_amount = round(sum(float(r.get("amount") or 0) for r in excel_items), 2)
        amount_delta = round(pdf_amount - excel_amount, 2)
        effective_wh_tolerance = _adaptive_tolerance(max(abs(pdf_amount), abs(excel_amount)), amount_tolerance)
        wh_passed = amount_within_tolerance(amount_delta, effective_wh_tolerance)

        row = {
            "warehouseId": wh,
            "pdfEmployeeCount": pdf_count,
            "excelEmployeeCount": len(excel_items),
            "pdfHoursTotal": round(sum(i.hours for i in pdf_row_by_wh.get(wh, [])), 2) if wh in pdf_row_by_wh else 0,
            "excelHoursTotal": round(sum(float(r.get("hours") or 0) for r in excel_items), 2),
            "pdfAmountTotal": pdf_amount,
            "excelAmountTotal": excel_amount,
            "amountDelta": amount_delta,
            "matchStatus": "通过" if wh_passed else "金额差异",
            "employeeRows": [],
            "attribution": [],
        }

        # Tier 3: employee detail only for warehouses with differences AND available rows
        if not wh_passed and wh in pdf_row_by_wh:
            pdf_items = pdf_row_by_wh[wh]
            excel_line_items = line_items_from_dicts(excel_items)
            pdf_agg = _aggregate(pdf_items)
            excel_agg = _aggregate(excel_line_items)
            row["employeeRows"] = _match_employee_groups(
                pdf_agg, excel_agg,
                amount_tolerance=amount_tolerance,
                hours_tolerance=hours_tolerance,
                confidence_threshold=confidence_threshold,
                manual_name_mapping=manual_name_mapping,
            )
            # Build attribution for warehouses with diff >= $1
            if abs(amount_delta) >= 1.0:
                row["attribution"] = _build_attribution(row["employeeRows"])

        warehouse_rows.append(row)

    passed = sum(1 for r in warehouse_rows if r["matchStatus"] == "通过")
    diff_warehouses = [r["warehouseId"] for r in warehouse_rows if r["matchStatus"] != "通过"]
    allocation_issues = _build_cross_warehouse_allocation_issues(
        warehouse_rows,
        amount_tolerance=amount_tolerance,
    )
    # 总账结论只看 PDF 与 Excel 总金额；仓库或员工分摊差异保留为待确认事项。
    summary.update({
        "warehouseCount": len(warehouse_rows),
        "passedCount": passed,
        "exceptionCount": len(warehouse_rows) - passed,
        "diffWarehouses": diff_warehouses,
        "allocationIssueCount": len(allocation_issues),
    })
    return {"summary": summary, "rows": warehouse_rows, "errors": errors, "allocationIssues": allocation_issues}


# ---------------------------------------------------------------------------
# Core matching engine (shared by employee-level and warehouse-level)
# ---------------------------------------------------------------------------

def _match_employee_groups(
    pdf: Dict[str, Dict[str, Any]],
    excel: Dict[str, Dict[str, Any]],
    *,
    amount_tolerance: float,
    hours_tolerance: float,
    confidence_threshold: float,
    manual_name_mapping: Dict[str, str] | None = None,
) -> List[Dict[str, Any]]:
    """Match employee groups between aggregated PDF and Excel data."""
    fuzzy_matches = _fuzzy_match_unmatched_groups(pdf, excel,
                                                  amount_tolerance=amount_tolerance,
                                                  hours_tolerance=hours_tolerance,
                                                  manual_name_mapping=manual_name_mapping)
    rows: List[Dict[str, Any]] = []

    for key in sorted(set(pdf) | set(excel)):
        if key in fuzzy_matches["skip_keys"]:
            continue
        pdf_group = pdf.get(key, _empty_group())
        excel_key = fuzzy_matches["pdf_to_excel"].get(key)
        excel_group = excel.get(excel_key, _empty_group()) if excel_key else excel.get(key, _empty_group())

        pdf_amount = round(pdf_group["amount"], 2)
        excel_amount = round(excel_group["amount"], 2)
        pdf_hours = round(pdf_group["hours"], 2)
        excel_hours = round(excel_group["hours"], 2)
        amount_delta = round(pdf_amount - excel_amount, 2)
        hours_delta = round(pdf_hours - excel_hours, 2)

        low_confidence = pdf_group["min_confidence"] < confidence_threshold
        fuzzy_matched = bool(excel_key)

        risk_flags = []
        if low_confidence:
            risk_flags.append("低置信度抽取")
        name_format_auto_merged = _is_name_format_auto_merged(pdf_group, excel_group)
        if fuzzy_matched:
            risk_flags.append("疑似姓名匹配")
        de_minimis_unmatched = _is_de_minimis_unmatched(
            has_pdf=bool(pdf_group["items"]),
            has_excel=bool(excel_group["items"]),
            amount_delta=amount_delta,
            hours_delta=hours_delta,
            amount_tolerance=amount_tolerance,
            hours_tolerance=hours_tolerance,
            low_confidence=low_confidence,
        )
        if de_minimis_unmatched:
            risk_flags.append("微小残差")
        amount_matches = abs(amount_delta) <= amount_tolerance
        safe_name_format_auto_merged = name_format_auto_merged and amount_matches
        if not fuzzy_matched and safe_name_format_auto_merged:
            risk_flags.append("姓名格式差异自动合并")
        if amount_matches and abs(hours_delta) > hours_tolerance:
            risk_flags.append("工时需复核")

        status = _status(
            has_pdf=bool(pdf_group["items"]),
            has_excel=bool(excel_group["items"]),
            amount_delta=amount_delta,
            hours_delta=hours_delta,
            amount_tolerance=amount_tolerance,
            hours_tolerance=hours_tolerance,
            low_confidence=low_confidence,
            fuzzy_matched=fuzzy_matched,
            de_minimis_unmatched=de_minimis_unmatched,
        )
        rows.append({
            "employeeKey": key,
            "employeeName": _matched_name(pdf_group, excel_group, fuzzy_matched or safe_name_format_auto_merged) or key,
            "pdfHoursTotal": pdf_hours,
            "excelHoursTotal": excel_hours,
            "hoursDelta": hours_delta,
            "pdfAmountTotal": pdf_amount,
            "excelAmountTotal": excel_amount,
            "amountDelta": amount_delta,
            "matchStatus": status,
            "riskFlags": risk_flags,
            "sourceRefs": "; ".join(pdf_group["refs"] + excel_group["refs"]),
        })
    return rows


# ---------------------------------------------------------------------------
# Warehouse grouping helpers
# ---------------------------------------------------------------------------

def _group_pdf_by_warehouse(
    pdf_rows: List[LaborLineItem],
    fallback_warehouse_id: str = "",
    source_file_warehouse_map: Dict[str, str] | None = None,
) -> tuple[Dict[str, List[LaborLineItem]], List[str]]:
    grouped: Dict[str, List[LaborLineItem]] = defaultdict(list)
    errors: List[str] = []
    source_file_warehouse_map = source_file_warehouse_map or {}
    for item in pdf_rows:
        wh = _warehouse_id_from_filename(item.source_file)
        if not wh:
            wh = str(item.warehouse_id or "")
        if not wh:
            wh = source_file_warehouse_map.get(item.source_file, "")
        if not wh:
            if fallback_warehouse_id:
                wh = fallback_warehouse_id
            else:
                errors.append(f"无法从文件名提取仓库号: {item.source_file}")
                continue
        grouped[wh].append(item)
    return dict(grouped), errors


def _infer_pdf_warehouses_from_excel_totals(
    pdf_totals: List[Dict[str, Any]],
    excel_by_wh: Dict[str, List[Dict[str, Any]]],
    amount_tolerance: float,
) -> tuple[List[Dict[str, Any]], Dict[str, str]]:
    """Infer missing PDF warehouse ids when totals uniquely match Excel warehouses."""
    if not pdf_totals or not excel_by_wh:
        return pdf_totals, {}

    excel_amounts = {
        wh: round(sum(float(row.get("amount") or 0) for row in rows), 2)
        for wh, rows in excel_by_wh.items()
    }
    used_warehouses: set[str] = {
        str(total.get("warehouse_id") or "")
        for total in pdf_totals
        if str(total.get("warehouse_id") or "")
    }
    used_sources: set[str] = set()
    source_map: Dict[str, str] = {}
    enriched: List[Dict[str, Any]] = []

    for total in pdf_totals:
        current_wh = str(total.get("warehouse_id") or "")
        if current_wh:
            enriched.append(total)
            continue

        amount = round(float(total.get("total_amount") or 0), 2)
        candidates = [
            wh
            for wh, excel_amount in excel_amounts.items()
            if wh not in used_warehouses and abs(round(amount - excel_amount, 2)) <= amount_tolerance
        ]
        if len(candidates) == 1:
            wh = candidates[0]
            updated = dict(total)
            updated["warehouse_id"] = wh
            updated["warehouse_inferred_from"] = "excel_total_amount"
            source = str(total.get("source_file") or "")
            if source and source not in used_sources:
                source_map[source] = wh
                used_sources.add(source)
            used_warehouses.add(wh)
            enriched.append(updated)
        else:
            enriched.append(total)

    return enriched, source_map


def _group_excel_by_warehouse(
    rows: List[Dict[str, Any]],
) -> tuple[Dict[str, List[Dict[str, Any]]], List[str]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    errors: List[str] = []
    for row in rows:
        wh = str(row.get("warehouse_id") or "")
        if not wh:
            errors.append(f"Excel 行缺少物理仓: {row.get('employee_name', '')}")
            continue
        grouped[wh].append(row)
    return dict(grouped), errors


# ---------------------------------------------------------------------------
# Employee aggregation and matching internals
# ---------------------------------------------------------------------------

def _aggregate(items: Iterable[LaborLineItem]) -> Dict[str, Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = defaultdict(_empty_group)
    for item in items:
        key = _item_key(item)
        if not key:
            continue
        group = grouped[key]
        group["name"] = group["name"] or item.employee_name_raw
        group["hours"] = round(group["hours"] + item.hours, 2)
        group["amount"] = round(group["amount"] + item.amount, 2)
        group["min_confidence"] = min(group["min_confidence"], item.confidence)
        group["items"].append(item)
        group["refs"].append(_source_ref(item))
    return dict(grouped)


def _empty_group() -> Dict[str, Any]:
    return {"name": "", "hours": 0.0, "amount": 0.0, "min_confidence": 1.0, "items": [], "refs": []}


def _item_key(item: LaborLineItem) -> str:
    employee_id = item.employee_id.strip().upper()
    if employee_id:
        return f"id:{employee_id}"
    return f"name:{item.employee_name_normalized}"


def _status(
    *,
    has_pdf: bool,
    has_excel: bool,
    amount_delta: float,
    hours_delta: float,
    amount_tolerance: float,
    hours_tolerance: float,
    low_confidence: bool,
    fuzzy_matched: bool = False,
    de_minimis_unmatched: bool = False,
) -> str:
    if de_minimis_unmatched:
        return "通过"
    if has_pdf and not has_excel:
        return "低置信度抽取" if low_confidence else "PDF有Excel无"
    if has_excel and not has_pdf:
        return "Excel有PDF无"
    if abs(amount_delta) > amount_tolerance:
        return "金额差异"
    if low_confidence:
        return "低置信度抽取"
    # Amount is the primary audit criterion. Hour deltas can reflect REG/OT/rest-day
    # bucket differences while the billed total is still correct, so they remain a
    # risk flag instead of failing the row.
    return "通过"


def _is_de_minimis_unmatched(
    *,
    has_pdf: bool,
    has_excel: bool,
    amount_delta: float,
    hours_delta: float,
    amount_tolerance: float,
    hours_tolerance: float,
    low_confidence: bool,
) -> bool:
    if low_confidence or has_pdf == has_excel:
        return False
    return abs(amount_delta) <= max(float(amount_tolerance), 0.50) and abs(hours_delta) <= max(float(hours_tolerance), 0.05)


def _name_similarity_improved(left: str, right: str) -> float:
    """改进的姓名相似度计算。

    结合多种算法：
    1. 标准化后的精确匹配
    2. Token 集合相似度（处理词序差异）
    3. 编辑距离相似度（处理拼写错误）
    4. 昵称变体匹配
    """
    from .parsing import expand_name_variants, normalize_employee_name_advanced

    # 标准化
    left_norm = normalize_employee_name_advanced(left)
    right_norm = normalize_employee_name_advanced(right)

    # 精确匹配
    if left_norm == right_norm:
        return 1.0

    # Token 集合相似度
    left_tokens = set(left_norm.split())
    right_tokens = set(right_norm.split())
    if not left_tokens or not right_tokens:
        return 0.0

    intersection = left_tokens & right_tokens
    union = left_tokens | right_tokens
    jaccard = len(intersection) / len(union) if union else 0.0

    # 编辑距离相似度
    sequence_ratio = SequenceMatcher(None, left_norm, right_norm).ratio()

    # 昵称变体匹配
    left_variants = expand_name_variants(left)
    right_variants = expand_name_variants(right)
    variant_bonus = 0.3 if left_variants & right_variants else 0.0

    # 综合评分（加权平均）
    score = jaccard * 0.4 + sequence_ratio * 0.6 + variant_bonus

    return min(score, 1.0)


def _workbuddy_jaccard(left: str, right: str) -> float:
    """Token Jaccard over normalized names, matching the WorkBuddy handoff method."""
    left_tokens = set(normalize_workbuddy_name(pdf_name_to_first_last(left)).split())
    right_tokens = set(normalize_workbuddy_name(right).split())
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _manual_mapping_lookup(pdf_name: str, excel: Dict[str, Dict[str, Any]], manual_name_mapping: Dict[str, str] | None) -> str:
    if not manual_name_mapping or pdf_name not in manual_name_mapping:
        return ""
    target = normalize_workbuddy_name(manual_name_mapping[pdf_name])
    for excel_key, group in excel.items():
        if normalize_workbuddy_name(group["name"]) == target:
            return excel_key
    return ""


def _format_exact_lookup(pdf_name: str, excel: Dict[str, Dict[str, Any]]) -> str:
    target = normalize_workbuddy_name(pdf_name_to_first_last(pdf_name))
    for excel_key, group in excel.items():
        if normalize_workbuddy_name(group["name"]) == target:
            return excel_key
    return ""


def _fuzzy_match_unmatched_groups(
    pdf: Dict[str, Dict[str, Any]],
    excel: Dict[str, Dict[str, Any]],
    *,
    amount_tolerance: float,
    hours_tolerance: float,
    manual_name_mapping: Dict[str, str] | None = None,
) -> Dict[str, Any]:
    exact_keys = set(pdf) & set(excel)
    pdf_candidates = [key for key, group in pdf.items() if key not in exact_keys and group["name"]]
    excel_candidates = [key for key, group in excel.items() if key not in exact_keys and group["name"]]
    matches: Dict[str, str] = {}
    used_excel = set()
    scored = []
    for pdf_key in pdf_candidates:
        manual_excel_key = _manual_mapping_lookup(pdf[pdf_key]["name"], excel, manual_name_mapping)
        if manual_excel_key and manual_excel_key in excel_candidates and manual_excel_key not in used_excel:
            matches[pdf_key] = manual_excel_key
            used_excel.add(manual_excel_key)
            continue

        exact_excel_key = _format_exact_lookup(pdf[pdf_key]["name"], excel)
        if exact_excel_key and exact_excel_key in excel_candidates and exact_excel_key not in used_excel:
            matches[pdf_key] = exact_excel_key
            used_excel.add(exact_excel_key)
            continue

        for excel_key in excel_candidates:
            if excel_key in used_excel:
                continue
            jaccard = _workbuddy_jaccard(pdf[pdf_key]["name"], excel[excel_key]["name"])
            score = _name_similarity(pdf[pdf_key]["name"], excel[excel_key]["name"])
            if not _fuzzy_totals_support_match(
                pdf[pdf_key],
                excel[excel_key],
                score=score,
                jaccard=jaccard,
                amount_tolerance=amount_tolerance,
                hours_tolerance=hours_tolerance,
            ):
                continue
            scored.append((max(jaccard, score), pdf_key, excel_key))
    for _score, pdf_key, excel_key in sorted(scored, reverse=True):
        if pdf_key in matches or excel_key in used_excel:
            continue
        matches[pdf_key] = excel_key
        used_excel.add(excel_key)
    return {"pdf_to_excel": matches, "skip_keys": used_excel}


def _name_similarity(left: str, right: str) -> float:
    left_tokens = set(normalize_employee_name(left).split())
    right_tokens = set(normalize_employee_name(right).split())
    if not left_tokens or not right_tokens:
        return 0.0
    intersection = left_tokens & right_tokens
    min_size = min(len(left_tokens), len(right_tokens))
    max_size = max(len(left_tokens), len(right_tokens))
    base = len(intersection) / min_size
    left_longest = max(left_tokens, key=len) if left_tokens else ""
    right_longest = max(right_tokens, key=len) if right_tokens else ""
    longest_bonus = 0.15 if left_longest == right_longest else 0.0
    coverage = len(intersection) / max_size
    token_score = round(min(base * 0.7 + coverage * 0.3 + longest_bonus, 1.0), 3)

    left_normalized = normalize_employee_name(left)
    right_normalized = normalize_employee_name(right)
    sequence_score = SequenceMatcher(None, left_normalized, right_normalized).ratio()

    from .parsing import expand_name_variants
    left_variants = expand_name_variants(left)
    right_variants = expand_name_variants(right)
    variant_intersection = left_variants & right_variants
    variant_bonus = 0.3 if variant_intersection else 0.0

    return round(min(token_score * 0.4 + sequence_score * 0.6 + variant_bonus, 1.0), 3)


def _fuzzy_totals_support_match(pdf_group: Dict[str, Any], excel_group: Dict[str, Any], score: float, jaccard: float, amount_tolerance: float, hours_tolerance: float) -> bool:
    amount_delta = abs(round(pdf_group["amount"] - excel_group["amount"], 2))
    hours_delta = abs(round(pdf_group["hours"] - excel_group["hours"], 2))
    max_amount = max(abs(pdf_group["amount"]), abs(excel_group["amount"]), 1.0)
    relative_amount_diff = amount_delta / max_amount
    if jaccard >= 0.35 and amount_delta <= amount_tolerance:
        return True
    if score >= 0.85:
        return True
    if score >= 0.70 and relative_amount_diff <= 0.02 and hours_delta <= max(hours_tolerance, 0.5):
        return True
    if score >= 0.60 and relative_amount_diff <= 0.01 and hours_delta <= max(hours_tolerance, 0.2):
        return True
    return False


def _matched_name(pdf_group: Dict[str, Any], excel_group: Dict[str, Any], fuzzy_matched: bool) -> str:
    if fuzzy_matched:
        return f"{pdf_group['name']} ⇄ {excel_group['name']}"
    return pdf_group["name"] or excel_group["name"]


def _is_name_format_auto_merged(pdf_group: Dict[str, Any], excel_group: Dict[str, Any]) -> bool:
    if not pdf_group.get("items") or not excel_group.get("items"):
        return False
    pdf_name = str(pdf_group.get("name") or "").strip()
    excel_name = str(excel_group.get("name") or "").strip()
    if not pdf_name or not excel_name or pdf_name == excel_name:
        return False
    return normalize_employee_name(pdf_name) == normalize_employee_name(excel_name)


def _suggest_unmatched_candidates(
    rows: List[Dict[str, Any]],
    pdf: Dict[str, Dict[str, Any]],
    excel: Dict[str, Dict[str, Any]],
    *,
    amount_tolerance: float,
    hours_tolerance: float,
) -> tuple[List[Dict[str, Any]], set, set]:
    unmatched_pdf_keys = [row["employeeKey"] for row in rows if row.get("matchStatus") == "PDF有Excel无"]
    unmatched_excel_keys = [row["employeeKey"] for row in rows if row.get("matchStatus") == "Excel有PDF无"]
    candidates = []
    promoted_pdf: set = set()
    promoted_excel: set = set()
    used_excel = set()
    for pdf_key in unmatched_pdf_keys:
        best = None
        for excel_key in unmatched_excel_keys:
            if excel_key in used_excel:
                continue
            pdf_group = pdf.get(pdf_key, _empty_group())
            excel_group = excel.get(excel_key, _empty_group())
            score = _name_similarity(pdf_group["name"], excel_group["name"])
            amount_delta = round(pdf_group["amount"] - excel_group["amount"], 2)
            hours_delta = round(pdf_group["hours"] - excel_group["hours"], 2)
            totals_align = abs(amount_delta) <= amount_tolerance and abs(hours_delta) <= hours_tolerance
            if score < 0.55 and not (totals_align and score >= 0.35):
                continue
            candidate = {
                "pdfEmployeeKey": pdf_key,
                "excelEmployeeKey": excel_key,
                "pdfEmployeeName": pdf_group["name"],
                "excelEmployeeName": excel_group["name"],
                "nameSimilarity": round(score, 3),
                "pdfHoursTotal": round(pdf_group["hours"], 2),
                "excelHoursTotal": round(excel_group["hours"], 2),
                "hoursDelta": hours_delta,
                "pdfAmountTotal": round(pdf_group["amount"], 2),
                "excelAmountTotal": round(excel_group["amount"], 2),
                "amountDelta": amount_delta,
                "recommendation": "人工复核",
                "sourceRefs": "; ".join(pdf_group["refs"] + excel_group["refs"]),
            }
            if best is None or candidate["nameSimilarity"] > best["nameSimilarity"]:
                best = candidate
        if best:
            if _should_promote_name_amount_candidate(best, hours_tolerance=hours_tolerance):
                best["recommendation"] = "姓名疑似同一人，金额/费率差异需人工复核"
                promoted_pdf.add(pdf_key)
                promoted_excel.add(best["excelEmployeeKey"])
            candidates.append(best)
            used_excel.add(best["excelEmployeeKey"])
    return sorted(candidates, key=lambda row: row["nameSimilarity"], reverse=True), promoted_pdf, promoted_excel


def _should_promote_name_amount_candidate(candidate: Dict[str, Any], *, hours_tolerance: float) -> bool:
    """Collapse same-person rate deltas into one review row without passing them."""
    score = float(candidate.get("nameSimilarity") or 0)
    hours_delta = abs(float(candidate.get("hoursDelta") or 0))
    amount_delta = abs(float(candidate.get("amountDelta") or 0))
    if amount_delta <= 0:
        return False
    return score >= 0.55 and hours_delta <= max(float(hours_tolerance), 0.05)


def _suggest_residual_offset_candidates(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Find offsetting employee exceptions that indicate a combined PDF row.

    Real OSS invoices can contain a PDF line whose hours/amount include another
    Excel employee without listing that employee name in the PDF text. This must
    remain an exception, but the exact offset is useful review evidence.
    """
    amount_diff_rows = [
        row for row in rows
        if row.get("matchStatus") == "金额差异"
        and row.get("pdfAmountTotal", 0) > row.get("excelAmountTotal", 0)
        and row.get("pdfHoursTotal", 0) > row.get("excelHoursTotal", 0)
    ]
    unmatched_excel_rows = [row for row in rows if row.get("matchStatus") == "Excel有PDF无"]
    candidates: List[Dict[str, Any]] = []
    used_excel: set = set()

    for pdf_row in sorted(amount_diff_rows, key=lambda row: abs(row.get("amountDelta", 0)), reverse=True):
        pdf_amount_delta = round(float(pdf_row.get("amountDelta") or 0), 2)
        pdf_hours_delta = round(float(pdf_row.get("hoursDelta") or 0), 2)
        best: Dict[str, Any] | None = None
        for excel_row in unmatched_excel_rows:
            excel_key = str(excel_row.get("employeeKey") or "")
            if excel_key in used_excel:
                continue
            excel_amount = round(float(excel_row.get("excelAmountTotal") or 0), 2)
            excel_hours = round(float(excel_row.get("excelHoursTotal") or 0), 2)
            amount_residual = round(pdf_amount_delta - excel_amount, 2)
            hours_residual = round(pdf_hours_delta - excel_hours, 2)
            if abs(amount_residual) > 0.01 or abs(hours_residual) > 0.01:
                continue
            candidate = {
                "issueType": "combined_pdf_row",
                "pdfEmployeeKey": pdf_row.get("employeeKey", ""),
                "excelEmployeeKey": excel_key,
                "pdfEmployeeName": pdf_row.get("employeeName", ""),
                "excelEmployeeName": excel_row.get("employeeName", ""),
                "nameSimilarity": round(_name_similarity(str(pdf_row.get("employeeName") or ""), str(excel_row.get("employeeName") or "")), 3),
                "pdfHoursTotal": round(float(pdf_row.get("pdfHoursTotal") or 0), 2),
                "excelHoursTotal": round(float(excel_row.get("excelHoursTotal") or 0), 2),
                "hoursDelta": pdf_hours_delta,
                "pdfAmountTotal": round(float(pdf_row.get("pdfAmountTotal") or 0), 2),
                "excelAmountTotal": excel_amount,
                "amountDelta": pdf_amount_delta,
                "recommendation": "疑似PDF合并员工，需人工核对原始发票",
                "sourceRefs": "; ".join(ref for ref in [
                    str(pdf_row.get("sourceRefs") or ""),
                    str(excel_row.get("sourceRefs") or ""),
                ] if ref),
            }
            if best is None or abs(candidate["amountDelta"]) > abs(best["amountDelta"]):
                best = candidate
        if best:
            candidates.append(best)
            used_excel.add(str(best["excelEmployeeKey"]))

    return candidates


def _apply_residual_offset_flags(rows: List[Dict[str, Any]], candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    pdf_keys = {str(candidate.get("pdfEmployeeKey") or "") for candidate in candidates}
    excel_keys = {str(candidate.get("excelEmployeeKey") or "") for candidate in candidates}
    flagged: List[Dict[str, Any]] = []
    for row in rows:
        key = str(row.get("employeeKey") or "")
        if key in pdf_keys or key in excel_keys:
            row = dict(row)
            risk_flags = list(row.get("riskFlags") or [])
            if "疑似PDF合并员工" not in risk_flags:
                risk_flags.append("疑似PDF合并员工")
            row["riskFlags"] = risk_flags
        flagged.append(row)
    return flagged


def _apply_promotions(
    rows: List[Dict[str, Any]],
    candidate_matches: List[Dict[str, Any]],
    promoted_pdf: set,
    promoted_excel: set,
) -> List[Dict[str, Any]]:
    promoted_rows: List[Dict[str, Any]] = []
    kept_rows: List[Dict[str, Any]] = []
    for row in rows:
        key = row["employeeKey"]
        if key in promoted_pdf:
            cand = next((c for c in candidate_matches if c["pdfEmployeeKey"] == key), None)
            if cand:
                promoted_rows.append({
                    "employeeKey": key,
                    "employeeName": f"{cand['pdfEmployeeName']} ⇄ {cand['excelEmployeeName']}",
                    "pdfHoursTotal": cand["pdfHoursTotal"],
                    "excelHoursTotal": cand["excelHoursTotal"],
                    "hoursDelta": cand["hoursDelta"],
                    "pdfAmountTotal": cand["pdfAmountTotal"],
                    "excelAmountTotal": cand["excelAmountTotal"],
                    "amountDelta": cand["amountDelta"],
                    "matchStatus": "金额差异",
                    "riskFlags": ["疑似姓名匹配", "金额/费率需复核"],
                    "sourceRefs": cand["sourceRefs"],
                })
            continue
        if key in promoted_excel:
            continue
        kept_rows.append(row)
    return kept_rows + promoted_rows


def _build_summary(
    rows: List[Dict[str, Any]],
    pdf_rows: List[LaborLineItem],
    excel_rows: List[LaborLineItem],
    candidate_matches: List[Dict[str, Any]],
) -> Dict[str, Any]:
    total_rows = len(rows)
    passed_count = sum(1 for row in rows if row["matchStatus"] == "通过")
    match_rate = round(passed_count / total_rows * 100, 1) if total_rows > 0 else 0.0

    pdf_confidences = [item.confidence for item in pdf_rows]
    average_confidence = round(sum(pdf_confidences) / len(pdf_confidences), 3) if pdf_confidences else 0.0

    pdf_amount_total = sum(row.amount for row in pdf_rows)
    excel_amount_total = sum(row.amount for row in excel_rows)
    amount_delta_total = round(pdf_amount_total - excel_amount_total, 2)
    amount_delta_percentage = round(abs(amount_delta_total) / max(abs(pdf_amount_total), abs(excel_amount_total), 1.0) * 100, 2)

    pdf_hours_total = round(sum(row.hours for row in pdf_rows), 2)
    excel_hours_total = round(sum(row.hours for row in excel_rows), 2)
    hours_delta_total = round(pdf_hours_total - excel_hours_total, 2)
    hours_delta_percentage = round(abs(hours_delta_total) / max(abs(pdf_hours_total), abs(excel_hours_total), 1.0) * 100, 2)

    return {
        "pdfEmployeeCount": len(_aggregate(pdf_rows)),
        "excelEmployeeCount": len(_aggregate(excel_rows)),
        "pdfHoursTotal": pdf_hours_total,
        "excelHoursTotal": excel_hours_total,
        "pdfAmountTotal": round(pdf_amount_total, 2),
        "excelAmountTotal": round(excel_amount_total, 2),
        "amountDeltaTotal": amount_delta_total,
        "amountDeltaPercentage": amount_delta_percentage,
        "hoursDeltaTotal": hours_delta_total,
        "hoursDeltaPercentage": hours_delta_percentage,
        "matchRate": match_rate,
        "averageConfidence": average_confidence,
        "amountDiffCount": sum(1 for row in rows if row["matchStatus"] == "金额差异"),
        "hoursRiskCount": sum(1 for row in rows if row["matchStatus"] == "工时不一致" or "工时需复核" in row.get("riskFlags", [])),
        "unmatchedPdfCount": sum(1 for row in rows if row["matchStatus"] in ("PDF有Excel无", "低置信度抽取") and row["pdfHoursTotal"] and not row["excelHoursTotal"]),
        "unmatchedExcelCount": sum(1 for row in rows if row["matchStatus"] == "Excel有PDF无"),
        "lowConfidenceCount": sum(1 for row in rows if "低置信度抽取" in row.get("riskFlags", []) or row["matchStatus"] == "低置信度抽取"),
        "fuzzyMatchCount": sum(1 for row in rows if row["matchStatus"] == "疑似姓名匹配" or "疑似姓名匹配" in row.get("riskFlags", [])),
        "candidateMatchCount": len(candidate_matches),
        "exceptionCount": sum(1 for row in rows if row["matchStatus"] != "通过"),
    }


def _source_ref(item: LaborLineItem) -> str:
    return f"{item.source_file} {item.source_page_or_row}".strip()


def _build_attribution(employee_rows: List[Dict[str, Any]], max_items: int = 5) -> List[Dict[str, Any]]:
    """Build attribution list for warehouses with significant differences.

    Returns top contributors sorted by absolute amount delta, with an "other" entry for the rest.
    """
    # Filter rows with amount difference
    diff_rows = [row for row in employee_rows if abs(row.get("amountDelta", 0)) >= 0.01]
    # Sort by absolute amount delta descending
    diff_rows.sort(key=lambda r: abs(r.get("amountDelta", 0)), reverse=True)

    attribution = []
    for row in diff_rows[:max_items]:
        attribution.append({
            "employeeKey": row.get("employeeKey", ""),
            "employeeName": row.get("employeeName", ""),
            "pdfAmount": row.get("pdfAmountTotal", 0),
            "excelAmount": row.get("excelAmountTotal", 0),
            "delta": row.get("amountDelta", 0),
            "sourceRefs": row.get("sourceRefs", ""),
        })

    # Add "other" entry if there are more rows
    if len(diff_rows) > max_items:
        other_delta = sum(r.get("amountDelta", 0) for r in diff_rows[max_items:])
        attribution.append({
            "employeeKey": "",
            "employeeName": f"其他{len(diff_rows) - max_items}人",
            "pdfAmount": None,
            "excelAmount": None,
            "delta": round(other_delta, 2),
            "sourceRefs": "",
        })

    return attribution


def _build_cross_warehouse_allocation_issues(
    warehouse_rows: List[Dict[str, Any]],
    *,
    amount_tolerance: float,
    max_items: int = 20,
) -> List[Dict[str, Any]]:
    """Detect employees whose warehouse deltas offset across locations.

    Employee-level aggregation can pass when the same employee is over-billed in
    one warehouse and under-billed in another. These are allocation issues, not
    employee total issues, and must stay visible for warehouse ownership review.
    """
    by_employee: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for warehouse in warehouse_rows:
        warehouse_delta = round(float(warehouse.get("amountDelta") or 0), 2)
        if abs(warehouse_delta) <= amount_tolerance:
            continue
        for item in warehouse.get("attribution", []) or []:
            employee_name = str(item.get("employeeName") or "").strip()
            if not employee_name or employee_name.startswith("其他"):
                continue
            delta = round(float(item.get("delta") or 0), 2)
            if abs(delta) <= amount_tolerance:
                continue
            employee_key = str(item.get("employeeKey") or "").strip() or f"name:{normalize_employee_name(employee_name)}"
            by_employee[employee_key].append(
                {
                    "warehouseId": str(warehouse.get("warehouseId") or ""),
                    "employeeName": employee_name,
                    "pdfAmount": round(float(item.get("pdfAmount") or 0), 2) if item.get("pdfAmount") is not None else None,
                    "excelAmount": round(float(item.get("excelAmount") or 0), 2) if item.get("excelAmount") is not None else None,
                    "amountDelta": delta,
                    "warehouseDelta": warehouse_delta,
                    "sourceRefs": str(item.get("sourceRefs") or ""),
                }
            )

    issues: List[Dict[str, Any]] = []
    for employee_key, rows in by_employee.items():
        if len(rows) < 2:
            continue
        has_positive = any(float(row["amountDelta"]) > amount_tolerance for row in rows)
        has_negative = any(float(row["amountDelta"]) < -amount_tolerance for row in rows)
        if not has_positive or not has_negative:
            continue
        net_delta = round(sum(float(row["amountDelta"]) for row in rows), 2)
        if abs(net_delta) > amount_tolerance:
            continue
        rows = sorted(rows, key=lambda row: (row["warehouseId"], -abs(float(row["amountDelta"]))))
        issues.append(
            {
                "employeeKey": employee_key,
                "employeeName": rows[0]["employeeName"],
                "netAmountDelta": net_delta,
                "warehouseCount": len({row["warehouseId"] for row in rows}),
                "warehouses": rows,
                "recommendation": "员工总额可抵消，但仓库归属金额不一致，需按仓库复核发票与账单归属。",
            }
        )

    return sorted(
        issues,
        key=lambda item: max(abs(float(row.get("amountDelta") or 0)) for row in item["warehouses"]),
        reverse=True,
    )[:max_items]
