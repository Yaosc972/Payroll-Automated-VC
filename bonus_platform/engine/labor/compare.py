from __future__ import annotations

from collections import defaultdict
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List

from .models import LaborComparisonRow, LaborLineItem
from .parsing import normalize_employee_name


def compare_labor_items(
    pdf_rows: List[LaborLineItem],
    excel_rows: List[LaborLineItem],
    *,
    amount_tolerance: float = 0.05,
    hours_tolerance: float = 0.1,
    confidence_threshold: float = 0.85,
) -> Dict[str, Any]:
    pdf = _aggregate(pdf_rows)
    excel = _aggregate(excel_rows)
    fuzzy_matches = _fuzzy_match_unmatched_groups(pdf, excel, amount_tolerance=amount_tolerance, hours_tolerance=hours_tolerance)
    comparison_rows: List[LaborComparisonRow] = []

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
        risk_flags = []
        low_confidence = pdf_group["min_confidence"] < confidence_threshold
        if low_confidence:
            risk_flags.append("低置信度抽取")
        fuzzy_matched = bool(excel_key)
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
        comparison_rows.append(
            LaborComparisonRow(
                employee_key=key,
                employee_name=_matched_name(pdf_group, excel_group, fuzzy_matched) or key,
                pdf_hours_total=pdf_hours,
                excel_hours_total=excel_hours,
                hours_delta=hours_delta,
                pdf_amount_total=pdf_amount,
                excel_amount_total=excel_amount,
                amount_delta=amount_delta,
                match_status=status,
                risk_flags=risk_flags,
                source_refs=pdf_group["refs"] + excel_group["refs"],
            )
        )

    rows = [row.to_dict() for row in comparison_rows]
    candidate_matches, promoted_pdf, promoted_excel = _suggest_unmatched_candidates(rows, pdf, excel)

    # Replace promoted PDF-only / Excel-only rows with merged "疑似姓名匹配" rows
    promoted_rows: List[Dict[str, Any]] = []
    kept_rows: List[Dict[str, Any]] = []
    for row in rows:
        key = row["employeeKey"]
        if key in promoted_pdf:
            # Find the matching candidate to build merged row
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
            # Skip the Excel side — already merged into the PDF row above
            continue
        kept_rows.append(row)
    rows = kept_rows + promoted_rows

    # Calculate additional quality metrics
    total_rows = len(rows)
    passed_count = sum(1 for row in rows if row["matchStatus"] == "通过")
    match_rate = round(passed_count / total_rows * 100, 1) if total_rows > 0 else 0.0

    # Calculate average confidence from PDF rows
    pdf_confidences = [item.confidence for item in pdf_rows]
    average_confidence = round(sum(pdf_confidences) / len(pdf_confidences), 3) if pdf_confidences else 0.0

    # Calculate percentage deltas
    pdf_amount_total = sum(row.amount for row in pdf_rows)
    excel_amount_total = sum(row.amount for row in excel_rows)
    amount_delta_total = round(pdf_amount_total - excel_amount_total, 2)
    amount_delta_percentage = round(abs(amount_delta_total) / max(abs(pdf_amount_total), abs(excel_amount_total), 1.0) * 100, 2)

    pdf_hours_total = round(sum(row.hours for row in pdf_rows), 2)
    excel_hours_total = round(sum(row.hours for row in excel_rows), 2)
    hours_delta_total = round(pdf_hours_total - excel_hours_total, 2)
    hours_delta_percentage = round(abs(hours_delta_total) / max(abs(pdf_hours_total), abs(excel_hours_total), 1.0) * 100, 2)

    summary = {
        "pdfEmployeeCount": len(pdf),
        "excelEmployeeCount": len(excel),
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
    return {"summary": summary, "rows": rows, "candidateMatches": candidate_matches}


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


def _fuzzy_match_unmatched_groups(
    pdf: Dict[str, Dict[str, Any]],
    excel: Dict[str, Dict[str, Any]],
    *,
    amount_tolerance: float,
    hours_tolerance: float,
) -> Dict[str, Any]:
    exact_keys = set(pdf) & set(excel)
    pdf_candidates = [key for key, group in pdf.items() if key not in exact_keys and group["name"]]
    excel_candidates = [key for key, group in excel.items() if key not in exact_keys and group["name"]]
    matches: Dict[str, str] = {}
    used_excel = set()
    scored = []
    for pdf_key in pdf_candidates:
        for excel_key in excel_candidates:
            if excel_key in used_excel:
                continue
            score = _name_similarity(pdf[pdf_key]["name"], excel[excel_key]["name"])
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

    # Add SequenceMatcher-based similarity for better fuzzy matching
    left_normalized = normalize_employee_name(left)
    right_normalized = normalize_employee_name(right)
    sequence_score = SequenceMatcher(None, left_normalized, right_normalized).ratio()

    # Check for nickname/variant matches
    from .parsing import expand_name_variants
    left_variants = expand_name_variants(left)
    right_variants = expand_name_variants(right)
    variant_intersection = left_variants & right_variants
    variant_bonus = 0.3 if variant_intersection else 0.0

    # Weighted average: token-based score gets 40%, sequence-based gets 60%, plus variant bonus
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
    """Find name-similar pairs among unmatched rows.

    Returns (candidates, promoted_pdf_keys, promoted_excel_keys).
    High-similarity pairs (>= 0.65) are "promoted" — the caller should remove
    the original PDF-only / Excel-only rows and replace them with a merged
    "疑似姓名匹配" row so the operator can confirm at a glance.
    """
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
            # Promote high-similarity pairs into main comparison view
            if best["nameSimilarity"] >= 0.65:
                promoted_pdf.add(best["pdfEmployeeKey"])
                promoted_excel.add(best["excelEmployeeKey"])
    return sorted(candidates, key=lambda row: row["nameSimilarity"], reverse=True), promoted_pdf, promoted_excel


def _source_ref(item: LaborLineItem) -> str:
    return f"{item.source_file} {item.source_page_or_row}".strip()


import re
from pathlib import Path


def _warehouse_id_from_filename(source_file: str) -> str:
    """Extract warehouse number from PDF filename like DEPT_1, CHINA_EXPRESS__3."""
    name = Path(source_file).stem.split("_202")[0]  # strip timestamp suffix
    m = re.search(r"DEPT[_-](\d+)", name, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"CHINA_EXPRESS__?(\d+)", name, re.IGNORECASE)
    if m:
        return m.group(1)
    return ""


def _warehouse_id_from_excel_label(label: str) -> str:
    """Extract warehouse number from Excel 物理仓 like '洛杉矶27号仓(PPS)'."""
    m = re.search(r"(\d+)号仓", str(label or ""))
    return m.group(1) if m else ""


def compare_by_warehouse(
    pdf_rows: List[LaborLineItem],
    excel_rows_with_warehouse: List[Dict[str, Any]],
    amount_tolerance: float = 0.05,
) -> Dict[str, Any]:
    """Compare PDF totals vs Excel totals grouped by warehouse.

    excel_rows_with_warehouse: list of dicts with keys: warehouse_id, hours, amount
    """
    # Group PDF rows by warehouse
    pdf_by_wh: Dict[str, Dict[str, float]] = defaultdict(lambda: {"hours": 0.0, "amount": 0.0, "count": 0})
    pdf_warehouse_errors: List[str] = []
    for item in pdf_rows:
        wh = _warehouse_id_from_filename(item.source_file)
        if not wh:
            wh = str(item.warehouse_id or "") if hasattr(item, "warehouse_id") else ""
        if not wh:
            pdf_warehouse_errors.append(f"无法从文件名提取仓库号: {item.source_file}")
            continue
        pdf_by_wh[wh]["hours"] = round(pdf_by_wh[wh]["hours"] + item.hours, 2)
        pdf_by_wh[wh]["amount"] = round(pdf_by_wh[wh]["amount"] + item.amount, 2)
        pdf_by_wh[wh]["count"] += 1

    # Group Excel rows by warehouse
    excel_by_wh: Dict[str, Dict[str, float]] = defaultdict(lambda: {"hours": 0.0, "amount": 0.0, "count": 0})
    excel_warehouse_errors: List[str] = []
    for row in excel_rows_with_warehouse:
        wh = str(row.get("warehouse_id") or "")
        if not wh:
            excel_warehouse_errors.append(f"Excel 行缺少物理仓: {row.get('employee_name', '')}")
            continue
        excel_by_wh[wh]["hours"] = round(excel_by_wh[wh]["hours"] + float(row.get("hours") or 0), 2)
        excel_by_wh[wh]["amount"] = round(excel_by_wh[wh]["amount"] + float(row.get("amount") or 0), 2)
        excel_by_wh[wh]["count"] += 1

    # Build comparison rows
    all_wh = sorted(set(pdf_by_wh) | set(excel_by_wh))
    warehouse_rows = []
    for wh in all_wh:
        pdf = pdf_by_wh.get(wh, {"hours": 0, "amount": 0, "count": 0})
        excel = excel_by_wh.get(wh, {"hours": 0, "amount": 0, "count": 0})
        amount_delta = round(pdf["amount"] - excel["amount"], 2)
        hours_delta = round(pdf["hours"] - excel["hours"], 2)
        status = "通过" if abs(amount_delta) <= amount_tolerance else "金额差异"
        warehouse_rows.append({
            "warehouseId": wh,
            "pdfEmployeeCount": pdf["count"],
            "excelEmployeeCount": excel["count"],
            "pdfHoursTotal": pdf["hours"],
            "excelHoursTotal": excel["hours"],
            "hoursDelta": hours_delta,
            "pdfAmountTotal": pdf["amount"],
            "excelAmountTotal": excel["amount"],
            "amountDelta": amount_delta,
            "matchStatus": status,
        })

    passed = sum(1 for r in warehouse_rows if r["matchStatus"] == "通过")
    summary = {
        "warehouseCount": len(warehouse_rows),
        "passedCount": passed,
        "exceptionCount": len(warehouse_rows) - passed,
        "pdfAmountTotal": round(sum(r["pdfAmountTotal"] for r in warehouse_rows), 2),
        "excelAmountTotal": round(sum(r["excelAmountTotal"] for r in warehouse_rows), 2),
        "amountDeltaTotal": round(sum(r["amountDelta"] for r in warehouse_rows), 2),
    }
    return {"summary": summary, "rows": warehouse_rows, "errors": pdf_warehouse_errors + excel_warehouse_errors}
