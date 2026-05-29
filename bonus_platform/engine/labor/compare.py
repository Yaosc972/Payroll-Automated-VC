from __future__ import annotations

import math
import re
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .models import LaborComparisonRow, LaborLineItem, line_items_from_dicts
from .parsing import normalize_employee_name


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
) -> Dict[str, Any]:
    """Employee-level comparison between PDF and Excel rows."""
    pdf = _aggregate(pdf_rows)
    excel = _aggregate(excel_rows)
    rows = _match_employee_groups(pdf, excel,
                                  amount_tolerance=amount_tolerance,
                                  hours_tolerance=hours_tolerance,
                                  confidence_threshold=confidence_threshold)

    candidate_matches, promoted_pdf, promoted_excel = _suggest_unmatched_candidates(rows, pdf, excel)
    rows = _apply_promotions(rows, candidate_matches, promoted_pdf, promoted_excel)
    summary = _build_summary(rows, pdf_rows, excel_rows, candidate_matches)
    return {"summary": summary, "rows": rows, "candidateMatches": candidate_matches}


def compare_by_warehouse(
    excel_rows_with_warehouse: List[Dict[str, Any]],
    pdf_totals: List[Dict[str, Any]] | None = None,
    pdf_rows: List[LaborLineItem] | None = None,
    amount_tolerance: float = 0.05,
    hours_tolerance: float = 0.1,
    confidence_threshold: float = 0.85,
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
    total_passed = abs(total_delta) <= effective_total_tolerance

    summary = {
        "pdfAmountTotal": pdf_total,
        "excelAmountTotal": excel_total,
        "amountDeltaTotal": total_delta,
        "totalPassed": total_passed,
        "warehouseCount": 0,
        "passedCount": 0,
        "exceptionCount": 0,
    }

    if total_passed:
        return {"summary": summary, "rows": [], "errors": []}

    # Tier 2: per-warehouse comparison
    if pdf_totals:
        pdf_by_wh: Dict[str, Dict[str, float]] = defaultdict(lambda: {"amount": 0.0, "count": 0})
        for t in pdf_totals:
            wh = str(t.get("warehouse_id") or "")
            if not wh:
                errors.append(f"无法提取仓库号: {t.get('source_file', '')}")
                continue
            pdf_by_wh[wh]["amount"] = round(pdf_by_wh[wh]["amount"] + float(t.get("total_amount") or 0), 2)
            pdf_by_wh[wh]["count"] += 1
        pdf_wh_amounts = dict(pdf_by_wh)
    else:
        pdf_wh_amounts = {}

    pdf_row_by_wh: Dict[str, List[LaborLineItem]] = {}
    if pdf_rows:
        pdf_row_by_wh, pdf_errors = _group_pdf_by_warehouse(pdf_rows)
        errors.extend(pdf_errors)
    excel_by_wh, excel_errors = _group_excel_by_warehouse(excel_rows_with_warehouse)
    errors.extend(excel_errors)

    all_wh = sorted(set(pdf_wh_amounts) | set(pdf_row_by_wh) | set(excel_by_wh))
    warehouse_rows = []
    for wh in all_wh:
        # PDF amounts: prefer totals, fallback to rows
        if wh in pdf_wh_amounts:
            pdf_amount = pdf_wh_amounts[wh]["amount"]
            pdf_count = pdf_wh_amounts[wh]["count"]
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
        wh_passed = abs(amount_delta) <= effective_wh_tolerance

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
            )
            # Build attribution for warehouses with diff >= $1
            if abs(amount_delta) >= 1.0:
                row["attribution"] = _build_attribution(row["employeeRows"])

        warehouse_rows.append(row)

    passed = sum(1 for r in warehouse_rows if r["matchStatus"] == "通过")
    summary.update({
        "warehouseCount": len(warehouse_rows),
        "passedCount": passed,
        "exceptionCount": len(warehouse_rows) - passed,
        "diffWarehouses": [r["warehouseId"] for r in warehouse_rows if r["matchStatus"] != "通过"],
    })
    return {"summary": summary, "rows": warehouse_rows, "errors": errors}


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
) -> List[Dict[str, Any]]:
    """Match employee groups between aggregated PDF and Excel data."""
    fuzzy_matches = _fuzzy_match_unmatched_groups(pdf, excel,
                                                  amount_tolerance=amount_tolerance,
                                                  hours_tolerance=hours_tolerance)
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
        if fuzzy_matched:
            risk_flags.append("疑似姓名匹配")

        status = _status(
            has_pdf=bool(pdf_group["items"]),
            has_excel=bool(excel_group["items"]),
            amount_delta=amount_delta,
            hours_delta=hours_delta,
            amount_tolerance=amount_tolerance,
            hours_tolerance=hours_tolerance,
            low_confidence=low_confidence,
            fuzzy_matched=fuzzy_matched,
        )
        rows.append({
            "employeeKey": key,
            "employeeName": _matched_name(pdf_group, excel_group, fuzzy_matched) or key,
            "pdfHoursTotal": pdf_hours,
            "excelHoursTotal": excel_hours,
            "hoursDelta": hours_delta,
            "pdfAmountTotal": pdf_amount,
            "excelAmountTotal": excel_amount,
            "amountDelta": amount_delta,
            "matchStatus": status,
            "riskFlags": risk_flags,
        })
    return rows


# ---------------------------------------------------------------------------
# Warehouse grouping helpers
# ---------------------------------------------------------------------------

def _group_pdf_by_warehouse(
    pdf_rows: List[LaborLineItem],
) -> tuple[Dict[str, List[LaborLineItem]], List[str]]:
    grouped: Dict[str, List[LaborLineItem]] = defaultdict(list)
    errors: List[str] = []
    for item in pdf_rows:
        wh = _warehouse_id_from_filename(item.source_file)
        if not wh:
            wh = str(item.warehouse_id or "")
        if not wh:
            errors.append(f"无法从文件名提取仓库号: {item.source_file}")
            continue
        grouped[wh].append(item)
    return dict(grouped), errors


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
) -> str:
    if has_pdf and not has_excel:
        return "低置信度抽取" if low_confidence else "PDF有Excel无"
    if has_excel and not has_pdf:
        return "Excel有PDF无"
    if abs(hours_delta) > hours_tolerance:
        return "工时不一致"
    if abs(amount_delta) > amount_tolerance:
        return "金额差异"
    if fuzzy_matched:
        return "通过"
    if low_confidence:
        return "低置信度抽取"
    return "通过"


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


def _fuzzy_match_unmatched_groups(
    pdf: Dict[str, Dict[str, Any]],
    excel: Dict[str, Dict[str, Any]],
    *,
    amount_tolerance: float,
    hours_tolerance: float,
    use_improved: bool = True,
) -> Dict[str, Any]:
    exact_keys = set(pdf) & set(excel)
    pdf_candidates = [key for key, group in pdf.items() if key not in exact_keys and group["name"]]
    excel_candidates = [key for key, group in excel.items() if key not in exact_keys and group["name"]]
    matches: Dict[str, str] = {}
    used_excel = set()
    scored = []
    similarity_func = _name_similarity_improved if use_improved else _name_similarity
    for pdf_key in pdf_candidates:
        for excel_key in excel_candidates:
            if excel_key in used_excel:
                continue
            score = similarity_func(pdf[pdf_key]["name"], excel[excel_key]["name"])
            if not _fuzzy_totals_support_match(pdf[pdf_key], excel[excel_key], score, amount_tolerance, hours_tolerance):
                continue
            scored.append((score, pdf_key, excel_key))
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


def _fuzzy_totals_support_match(pdf_group: Dict[str, Any], excel_group: Dict[str, Any], score: float, amount_tolerance: float, hours_tolerance: float) -> bool:
    amount_delta = abs(round(pdf_group["amount"] - excel_group["amount"], 2))
    hours_delta = abs(round(pdf_group["hours"] - excel_group["hours"], 2))
    max_amount = max(abs(pdf_group["amount"]), abs(excel_group["amount"]), 1.0)
    relative_amount_diff = amount_delta / max_amount
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


def _suggest_unmatched_candidates(rows: List[Dict[str, Any]], pdf: Dict[str, Dict[str, Any]], excel: Dict[str, Dict[str, Any]]) -> tuple[List[Dict[str, Any]], set, set]:
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
            if score < 0.55:
                continue
            amount_delta = round(pdf_group["amount"] - excel_group["amount"], 2)
            hours_delta = round(pdf_group["hours"] - excel_group["hours"], 2)
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
            candidates.append(best)
            used_excel.add(best["excelEmployeeKey"])
            if best["nameSimilarity"] >= 0.65:
                promoted_pdf.add(best["pdfEmployeeKey"])
                promoted_excel.add(best["excelEmployeeKey"])
    return sorted(candidates, key=lambda row: row["nameSimilarity"], reverse=True), promoted_pdf, promoted_excel


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
                    "matchStatus": "疑似姓名匹配",
                    "riskFlags": ["名字相似，金额/工时未对齐"],
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
        "hoursRiskCount": sum(1 for row in rows if row["matchStatus"] == "工时不一致"),
        "unmatchedPdfCount": sum(1 for row in rows if row["matchStatus"] in ("PDF有Excel无", "低置信度抽取") and row["pdfHoursTotal"] and not row["excelHoursTotal"]),
        "unmatchedExcelCount": sum(1 for row in rows if row["matchStatus"] == "Excel有PDF无"),
        "lowConfidenceCount": sum(1 for row in rows if "低置信度抽取" in row.get("riskFlags", []) or row["matchStatus"] == "低置信度抽取"),
        "fuzzyMatchCount": sum(1 for row in rows if row["matchStatus"] == "疑似姓名匹配" or "疑似姓名匹配" in row.get("riskFlags", [])),
        "candidateMatchCount": len(candidate_matches),
        "exceptionCount": sum(1 for row in rows if row["matchStatus"] != "通过"),
    }


# ---------------------------------------------------------------------------
# Warehouse ID extraction
# ---------------------------------------------------------------------------

def _warehouse_id_from_filename(source_file: str) -> str:
    name = Path(source_file).stem.split("_202")[0]
    m = re.search(r"DEPT[_-](\d+)", name, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"CHINA_EXPRESS__?(\d+)", name, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"elog(\d+)-", name, re.IGNORECASE)
    if m:
        return m.group(1)
    return ""


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
            "employeeName": row.get("employeeName", ""),
            "pdfAmount": row.get("pdfAmountTotal", 0),
            "excelAmount": row.get("excelAmountTotal", 0),
            "delta": row.get("amountDelta", 0),
        })

    # Add "other" entry if there are more rows
    if len(diff_rows) > max_items:
        other_delta = sum(r.get("amountDelta", 0) for r in diff_rows[max_items:])
        attribution.append({
            "employeeName": f"其他{len(diff_rows) - max_items}人",
            "pdfAmount": None,
            "excelAmount": None,
            "delta": round(other_delta, 2),
        })

    return attribution
