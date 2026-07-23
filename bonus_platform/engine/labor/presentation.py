from __future__ import annotations

from typing import Any, Mapping


PASS_STATUSES = {"通过", "金额一致"}
EMPLOYEE_EVIDENCE_FIELDS = (
    "pdfAmountTotal",
    "excelAmountTotal",
    "pdfHoursTotal",
    "excelHoursTotal",
)
NOT_IN_INVOICE_STATUSES = {"PDF有Excel无", "Excel有PDF无"}


def build_labor_presentation(
    comparison: Mapping[str, Any] | None,
    *,
    excel_record_count: int | None = None,
) -> dict[str, Any]:
    """Build the one display/audit contract shared by API, page, and reports."""

    payload = comparison if isinstance(comparison, Mapping) else {}
    source_rows = [dict(row) for row in (payload.get("rows") or []) if isinstance(row, Mapping)]
    employee_rows = [row for row in source_rows if labor_row_has_employee_evidence(row)]
    candidate_matches = [
        dict(row)
        for row in (payload.get("candidateMatches") or [])
        if isinstance(row, Mapping)
    ]
    difference_rows = [row for row in employee_rows if not labor_row_passed(row)]
    passed_rows = [row for row in employee_rows if labor_row_passed(row)]

    summary = {
        "employeeCount": len(employee_rows),
        "differenceEmployeeCount": len(difference_rows),
        "passedEmployeeCount": len(passed_rows),
        "amountDiffEmployeeCount": sum(
            1 for row in difference_rows if str(row.get("matchStatus") or "") == "金额差异"
        ),
        "hoursDiffEmployeeCount": sum(1 for row in difference_rows if _row_has_hours_difference(row)),
        "notInInvoiceEmployeeCount": sum(
            1
            for row in difference_rows
            if str(row.get("matchStatus") or "") in NOT_IN_INVOICE_STATUSES
        ),
        "candidateMatchCount": len(candidate_matches),
        "reviewItemCount": len(difference_rows) + len(candidate_matches),
        "amountImpact": round(sum(abs(_number(row.get("amountDelta"))) for row in difference_rows), 2),
        "hoursImpact": round(sum(abs(_number(row.get("hoursDelta"))) for row in difference_rows), 2),
        "excelRecordCount": max(int(excel_record_count or 0), 0),
        "sourceComparisonRowCount": len(source_rows),
        "excludedNonEmployeeRowCount": len(source_rows) - len(employee_rows),
    }
    return {
        "schemaVersion": 1,
        "employeeRows": employee_rows,
        "candidateMatches": candidate_matches,
        "summary": summary,
    }


def labor_row_passed(row: Mapping[str, Any]) -> bool:
    return str(row.get("matchStatus") or "") in PASS_STATUSES


def labor_row_has_employee_evidence(row: Mapping[str, Any]) -> bool:
    return any(abs(_number(row.get(field))) > 0.005 for field in EMPLOYEE_EVIDENCE_FIELDS)


def validate_labor_presentation(presentation: Mapping[str, Any] | None) -> list[str]:
    payload = presentation if isinstance(presentation, Mapping) else {}
    rows = payload.get("employeeRows") if isinstance(payload.get("employeeRows"), list) else []
    candidates = payload.get("candidateMatches") if isinstance(payload.get("candidateMatches"), list) else []
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    errors: list[str] = []
    if payload.get("schemaVersion") != 1:
        errors.append("schemaVersion must equal 1")

    employee_count = _integer(summary.get("employeeCount"))
    difference_count = _integer(summary.get("differenceEmployeeCount"))
    passed_count = _integer(summary.get("passedEmployeeCount"))
    candidate_count = _integer(summary.get("candidateMatchCount"))
    review_count = _integer(summary.get("reviewItemCount"))
    amount_diff_count = _integer(summary.get("amountDiffEmployeeCount"))
    hours_diff_count = _integer(summary.get("hoursDiffEmployeeCount"))
    not_in_invoice_count = _integer(summary.get("notInInvoiceEmployeeCount"))
    source_count = _integer(summary.get("sourceComparisonRowCount"))
    excluded_count = _integer(summary.get("excludedNonEmployeeRowCount"))

    if employee_count != len(rows):
        errors.append("employeeCount must equal len(employeeRows)")
    actual_difference_count = sum(
        1 for row in rows if isinstance(row, Mapping) and not labor_row_passed(row)
    )
    if difference_count != actual_difference_count:
        errors.append("differenceEmployeeCount must equal non-passed employee rows")
    if passed_count + difference_count != employee_count:
        errors.append("passedEmployeeCount plus differenceEmployeeCount must equal employeeCount")
    if candidate_count != len(candidates):
        errors.append("candidateMatchCount must equal len(candidateMatches)")
    if review_count != difference_count + candidate_count:
        errors.append("reviewItemCount must equal differenceEmployeeCount plus candidateMatchCount")
    actual_amount_diff_count = sum(
        1
        for row in rows
        if isinstance(row, Mapping)
        and not labor_row_passed(row)
        and str(row.get("matchStatus") or "") == "金额差异"
    )
    if amount_diff_count != actual_amount_diff_count:
        errors.append("amountDiffEmployeeCount must equal amount-difference employee rows")
    actual_hours_diff_count = sum(
        1
        for row in rows
        if isinstance(row, Mapping) and not labor_row_passed(row) and _row_has_hours_difference(row)
    )
    if hours_diff_count != actual_hours_diff_count:
        errors.append("hoursDiffEmployeeCount must equal hours-difference employee rows")
    actual_not_in_invoice_count = sum(
        1
        for row in rows
        if isinstance(row, Mapping)
        and not labor_row_passed(row)
        and str(row.get("matchStatus") or "") in NOT_IN_INVOICE_STATUSES
    )
    if not_in_invoice_count != actual_not_in_invoice_count:
        errors.append("notInInvoiceEmployeeCount must equal missing-invoice employee rows")
    if source_count - employee_count != excluded_count:
        errors.append("excludedNonEmployeeRowCount must equal sourceComparisonRowCount minus employeeCount")

    actual_amount_impact = round(
        sum(
            abs(_number(row.get("amountDelta")))
            for row in rows
            if isinstance(row, Mapping) and not labor_row_passed(row)
        ),
        2,
    )
    actual_hours_impact = round(
        sum(
            abs(_number(row.get("hoursDelta")))
            for row in rows
            if isinstance(row, Mapping) and not labor_row_passed(row)
        ),
        2,
    )
    if round(_number(summary.get("amountImpact")), 2) != actual_amount_impact:
        errors.append("amountImpact must equal employeeRows amount deltas without candidate duplication")
    if round(_number(summary.get("hoursImpact")), 2) != actual_hours_impact:
        errors.append("hoursImpact must equal employeeRows hours deltas")
    if _integer(summary.get("excelRecordCount")) < 0:
        errors.append("excelRecordCount must be non-negative")
    return errors


def _row_has_hours_difference(row: Mapping[str, Any]) -> bool:
    flags = row.get("riskFlags") if isinstance(row.get("riskFlags"), list) else []
    return str(row.get("matchStatus") or "") == "工时不一致" or "工时需复核" in flags


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _integer(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
