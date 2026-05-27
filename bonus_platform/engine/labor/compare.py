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
    candidate_matches = _suggest_unmatched_candidates(rows, pdf, excel)
    summary = {
        "pdfEmployeeCount": len(pdf),
        "excelEmployeeCount": len(excel),
        "pdfHoursTotal": round(sum(row.hours for row in pdf_rows), 2),
        "excelHoursTotal": round(sum(row.hours for row in excel_rows), 2),
        "pdfAmountTotal": round(sum(row.amount for row in pdf_rows), 2),
        "excelAmountTotal": round(sum(row.amount for row in excel_rows), 2),
        "amountDeltaTotal": round(sum(row.amount for row in pdf_rows) - sum(row.amount for row in excel_rows), 2),
        "amountDiffCount": sum(1 for row in rows if row["matchStatus"] == "金额差异"),
        "hoursRiskCount": sum(1 for row in rows if row["matchStatus"] == "工时不一致"),
        "unmatchedPdfCount": sum(1 for row in rows if row["pdfHoursTotal"] and not row["excelHoursTotal"]),
        "unmatchedExcelCount": sum(1 for row in rows if row["excelHoursTotal"] and not row["pdfHoursTotal"]),
        "lowConfidenceCount": sum(1 for row in rows if "低置信度抽取" in row.get("riskFlags", []) or row["matchStatus"] == "低置信度抽取"),
        "fuzzyMatchCount": sum(1 for row in rows if "疑似姓名匹配" in row.get("riskFlags", [])),
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
    return SequenceMatcher(None, normalize_employee_name(left), normalize_employee_name(right)).ratio()


def _fuzzy_totals_support_match(pdf_group: Dict[str, Any], excel_group: Dict[str, Any], score: float, amount_tolerance: float, hours_tolerance: float) -> bool:
    amount_delta = abs(round(pdf_group["amount"] - excel_group["amount"], 2))
    hours_delta = abs(round(pdf_group["hours"] - excel_group["hours"], 2))
    if score >= 0.88:
        return True
    if score >= 0.65 and amount_delta <= max(amount_tolerance, 0.05) and hours_delta <= max(hours_tolerance, 0.1):
        return True
    if score >= 0.72 and (amount_delta <= max(amount_tolerance, 0.05) or hours_delta <= max(hours_tolerance, 0.1)):
        return True
    return False


def _matched_name(pdf_group: Dict[str, Any], excel_group: Dict[str, Any], fuzzy_matched: bool) -> str:
    if fuzzy_matched:
        return f"{pdf_group['name']} ⇄ {excel_group['name']}"
    return pdf_group["name"] or excel_group["name"]


def _suggest_unmatched_candidates(rows: List[Dict[str, Any]], pdf: Dict[str, Dict[str, Any]], excel: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    unmatched_pdf_keys = [row["employeeKey"] for row in rows if row.get("matchStatus") == "PDF有Excel无"]
    unmatched_excel_keys = [row["employeeKey"] for row in rows if row.get("matchStatus") == "Excel有PDF无"]
    candidates = []
    used_excel = set()
    for pdf_key in unmatched_pdf_keys:
        best = None
        for excel_key in unmatched_excel_keys:
            if excel_key in used_excel:
                continue
            pdf_group = pdf.get(pdf_key, _empty_group())
            excel_group = excel.get(excel_key, _empty_group())
            score = _name_similarity(pdf_group["name"], excel_group["name"])
            if score < 0.70:
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
    return sorted(candidates, key=lambda row: row["nameSimilarity"], reverse=True)


def _source_ref(item: LaborLineItem) -> str:
    return f"{item.source_file} {item.source_page_or_row}".strip()
