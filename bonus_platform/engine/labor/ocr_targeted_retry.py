from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from .models import LaborLineItem
from .parsing import normalize_employee_name


def _page_number(value: Any) -> int | None:
    match = re.search(r"(?:^|\b)(?:p|page)\s*(\d+)(?:\b|$)", str(value or ""), re.IGNORECASE)
    return int(match.group(1)) if match else None


def build_targeted_ocr_retry_plan(candidate: dict[str, Any]) -> dict[str, Any]:
    blockers = set(candidate.get("blockers") or [])
    if blockers != {"strict_name_review_required"}:
        return {"eligible": False, "reason": "candidate_has_other_blockers"}
    closure = candidate.get("fileClosure") or []
    if not closure or any(not item.get("closed") for item in closure):
        return {"eligible": False, "reason": "candidate_amount_not_closed"}

    matches = candidate.get("nameGate", {}).get("matches") or []
    review_matches = [item for item in matches if item.get("status") in {"review", "unmatched"}]
    review_names = {normalize_employee_name(item.get("candidateName") or "") for item in review_matches}
    review_names.discard("")
    pages: dict[str, set[int]] = defaultdict(set)
    found_names: set[str] = set()
    for row in candidate.get("rows") or []:
        normalized_name = normalize_employee_name(row.get("employee_name_raw") or row.get("employeeNameRaw") or "")
        if normalized_name not in review_names:
            continue
        page = _page_number(row.get("source_page_or_row") or row.get("sourcePageOrRow"))
        source = str(row.get("source_file") or row.get("sourceFile") or "").strip()
        if page is not None and source:
            pages[source].add(page)
            found_names.add(normalized_name)
    if not review_names or found_names != review_names:
        return {"eligible": False, "reason": "review_page_unavailable"}

    return {
        "eligible": True,
        "reason": "strict_name_review_pages_located",
        "allowedPagesBySource": {source: sorted(values) for source, values in sorted(pages.items())},
        "reviewExcelNames": sorted(
            {
                str(item.get("excelName") or "").strip()
                for item in review_matches
                if str(item.get("excelName") or "").strip()
            }
        ),
    }


def merge_targeted_ocr_retry_rows(
    candidate_rows: list[LaborLineItem],
    retry_rows: list[LaborLineItem],
    *,
    allowed_pages_by_source: dict[str, list[int]],
    expected_totals: dict[str, float],
    tolerance: float,
) -> dict[str, Any]:
    target_pages = {source: set(pages) for source, pages in allowed_pages_by_source.items()}
    retained = [
        row
        for row in candidate_rows
        if _page_number(row.source_page_or_row) not in target_pages.get(row.source_file, set())
    ]
    merged = retained + list(retry_rows)
    actual_totals: dict[str, float] = defaultdict(float)
    for row in merged:
        actual_totals[row.source_file] += float(row.amount or 0)
    closed = bool(expected_totals) and all(
        abs(round(actual_totals.get(source, 0.0), 2) - float(expected)) <= tolerance
        for source, expected in expected_totals.items()
    )
    return {
        "closed": closed,
        "rows": merged if closed else candidate_rows,
        "actualTotals": {source: round(amount, 2) for source, amount in actual_totals.items()},
    }
