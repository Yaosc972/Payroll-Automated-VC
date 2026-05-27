from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List

from .models import LaborComparisonRow, LaborLineItem


def compare_labor_items(
    pdf_rows: List[LaborLineItem],
    excel_rows: List[LaborLineItem],
    *,
    amount_tolerance: float = 0.01,
    hours_tolerance: float = 0.1,
    confidence_threshold: float = 0.85,
) -> Dict[str, Any]:
    pdf = _aggregate(pdf_rows)
    excel = _aggregate(excel_rows)
    comparison_rows: List[LaborComparisonRow] = []

    for key in sorted(set(pdf) | set(excel)):
        pdf_group = pdf.get(key, _empty_group())
        excel_group = excel.get(key, _empty_group())
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
        status = _status(
            has_pdf=bool(pdf_group["items"]),
            has_excel=bool(excel_group["items"]),
            amount_delta=amount_delta,
            hours_delta=hours_delta,
            amount_tolerance=amount_tolerance,
            hours_tolerance=hours_tolerance,
            low_confidence=low_confidence,
        )
        comparison_rows.append(
            LaborComparisonRow(
                employee_key=key,
                employee_name=pdf_group["name"] or excel_group["name"] or key,
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
        "exceptionCount": sum(1 for row in rows if row["matchStatus"] != "通过"),
    }
    return {"summary": summary, "rows": rows}


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
) -> str:
    if has_pdf and not has_excel:
        return "低置信度抽取" if low_confidence else "PDF有Excel无"
    if has_excel and not has_pdf:
        return "Excel有PDF无"
    if abs(hours_delta) > hours_tolerance:
        return "工时不一致"
    if abs(amount_delta) > amount_tolerance:
        return "金额差异"
    if low_confidence:
        return "低置信度抽取"
    return "通过"


def _source_ref(item: LaborLineItem) -> str:
    return f"{item.source_file} {item.source_page_or_row}".strip()
