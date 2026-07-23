from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable


PAGE_ROLES = {
    "invoice_primary",
    "invoice_continuation",
    "invoice_total",
    "email_cover",
    "timecard_summary",
    "daily_detail",
    "supporting_attachment",
    "unknown",
}

_INVOICE_ROLES = {
    "invoice_primary",
    "invoice_continuation",
    "invoice_total",
}
_INVOICE_SECTION_BOUNDARY_ROLES = {
    "email_cover",
    "timecard_summary",
    "daily_detail",
    "supporting_attachment",
}
_HIGH_CONFIDENCE = 0.9
_EXPLICIT_TOTAL_LABEL = re.compile(
    r"(?:amount\s+due|balance\s+due|grand\s+total|invoice\s+total|total\s+due|net\s+total|"
    r"total\s+ht|total\s+ttc|total\s+neto|nettosumme|gesamt|\btotals?\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class LaborPageEvidence:
    source_file: str
    page: int
    role: str
    role_confidence: float
    warehouse_id: str = ""
    total_amount: float | None = None
    total_label: str = ""
    net_amount: float | None = None
    tax_amount: float | None = None
    gross_amount: float | None = None
    evidence_text: str = ""
    extraction_method: str = ""


@dataclass(frozen=True)
class LaborInvoiceEvidence:
    source_file: str
    warehouse_id: str
    total_amount: float | None
    total_page: int | None
    evidence_status: str
    authoritative: bool
    page_evidence: tuple[LaborPageEvidence, ...]
    excluded_pages: tuple[int, ...]


@dataclass(frozen=True)
class _TotalCandidate:
    page: LaborPageEvidence
    priority: int


def select_invoice_evidence(
    source_file: str,
    pages: Iterable[LaborPageEvidence],
    profile: Any = None,
) -> LaborInvoiceEvidence:
    """Select a payable invoice total from page evidence only.

    Supporting pages remain in the audit trail but never contribute an amount.
    """
    page_evidence = tuple(_coerce_page(page) for page in pages)
    expected_source_file = str(source_file or "").strip()
    if any(
        page.source_file.strip() and page.source_file.strip() != expected_source_file
        for page in page_evidence
    ):
        excluded_pages = tuple(page.page for page in page_evidence if page.role not in _INVOICE_ROLES)
        return _review_result(source_file, page_evidence, excluded_pages)
    invoice_pages = _invoice_section_pages(page_evidence)
    invoice_page_ids = {id(page) for page in invoice_pages}
    excluded_pages = tuple(page.page for page in page_evidence if id(page) not in invoice_page_ids)
    warehouse_id = _unique_warehouse_id(invoice_pages)
    has_untrusted_warehouse_signal = any(page.warehouse_id.strip() for page in invoice_pages) and not warehouse_id

    if has_untrusted_warehouse_signal:
        return _review_result(source_file, page_evidence, excluded_pages)

    candidates = _total_candidates(invoice_pages, profile)
    if not candidates:
        return _review_result(source_file, page_evidence, excluded_pages, warehouse_id)

    highest_priority = min(candidate.priority for candidate in candidates)
    preferred = tuple(candidate for candidate in candidates if candidate.priority == highest_priority)
    amounts = {round(float(candidate.page.total_amount), 2) for candidate in preferred}
    if len(amounts) != 1:
        return _review_result(source_file, page_evidence, excluded_pages, warehouse_id)
    preferred_amount = next(iter(amounts))
    if any(
        round(float(candidate.page.total_amount), 2) != preferred_amount
        for candidate in candidates
        if candidate.priority > highest_priority
    ):
        return _review_result(source_file, page_evidence, excluded_pages, warehouse_id)

    selected = min(preferred, key=lambda candidate: candidate.page.page).page
    return LaborInvoiceEvidence(
        source_file=source_file,
        warehouse_id=warehouse_id,
        total_amount=round(float(selected.total_amount), 2),
        total_page=selected.page,
        evidence_status="authoritative",
        authoritative=True,
        page_evidence=page_evidence,
        excluded_pages=excluded_pages,
    )


def _coerce_page(page: LaborPageEvidence | dict[str, Any]) -> LaborPageEvidence:
    if isinstance(page, LaborPageEvidence):
        return page
    return LaborPageEvidence(
        source_file=str(page.get("source_file") or page.get("sourceFile") or ""),
        page=int(page.get("page") or page.get("page_number") or page.get("pageNumber") or 0),
        role=str(page.get("role") or page.get("page_role") or page.get("pageRole") or "unknown"),
        role_confidence=float(page.get("role_confidence") or page.get("roleConfidence") or 0),
        warehouse_id=str(page.get("warehouse_id") or page.get("warehouseId") or ""),
        total_amount=_optional_float(page.get("total_amount", page.get("totalAmount"))),
        total_label=str(page.get("total_label") or page.get("totalLabel") or ""),
        net_amount=_optional_float(page.get("net_amount", page.get("netAmount"))),
        tax_amount=_optional_float(page.get("tax_amount", page.get("taxAmount"))),
        gross_amount=_optional_float(page.get("gross_amount", page.get("grossAmount"))),
        evidence_text=str(page.get("evidence_text") or page.get("evidenceText") or ""),
        extraction_method=str(page.get("extraction_method") or page.get("extractionMethod") or ""),
    )


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _total_candidates(
    pages: tuple[LaborPageEvidence, ...],
    profile: Any,
) -> tuple[_TotalCandidate, ...]:
    profile_methods = _profile_values(profile, "authoritative_total_method", "authoritativeTotalMethod")
    candidates: list[_TotalCandidate] = []
    for page in pages:
        if page.total_amount is None or page.total_amount <= 0:
            continue
        if page.role_confidence < _HIGH_CONFIDENCE:
            continue
        method = page.extraction_method.strip().lower()
        if _EXPLICIT_TOTAL_LABEL.search(page.total_label):
            candidates.append(_TotalCandidate(page, 1))
        elif method in {"invoice_line_sum", "complete_invoice_line_sum"}:
            candidates.append(_TotalCandidate(page, 2))
        elif method and method in profile_methods:
            candidates.append(_TotalCandidate(page, 3))
    return tuple(candidates)


def _invoice_section_pages(pages: tuple[LaborPageEvidence, ...]) -> tuple[LaborPageEvidence, ...]:
    invoice_pages: list[LaborPageEvidence] = []
    section_started = False
    section_closed = False
    for page in sorted(pages, key=lambda item: item.page):
        if section_closed:
            continue
        if page.role in _INVOICE_ROLES:
            invoice_pages.append(page)
            section_started = True
            continue
        if (
            section_started
            and page.role in _INVOICE_SECTION_BOUNDARY_ROLES
            and page.role_confidence >= _HIGH_CONFIDENCE
        ):
            section_closed = True
    return tuple(invoice_pages)


def _profile_values(profile: Any, *names: str) -> set[str]:
    values: Any = None
    if isinstance(profile, dict):
        for name in names:
            if name in profile:
                values = profile[name]
                break
    else:
        for name in names:
            if hasattr(profile, name):
                values = getattr(profile, name)
                break
    if values is None:
        return set()
    if isinstance(values, str):
        values = [values]
    return {str(value).strip().lower() for value in values if str(value).strip()}


def _unique_warehouse_id(pages: tuple[LaborPageEvidence, ...]) -> str:
    warehouse_ids = {
        page.warehouse_id.strip()
        for page in pages
        if page.role_confidence >= _HIGH_CONFIDENCE and page.warehouse_id.strip()
    }
    return next(iter(warehouse_ids)) if len(warehouse_ids) == 1 else ""


def _review_result(
    source_file: str,
    page_evidence: tuple[LaborPageEvidence, ...],
    excluded_pages: tuple[int, ...],
    warehouse_id: str = "",
) -> LaborInvoiceEvidence:
    return LaborInvoiceEvidence(
        source_file=source_file,
        warehouse_id=warehouse_id,
        total_amount=None,
        total_page=None,
        evidence_status="needs_review",
        authoritative=False,
        page_evidence=page_evidence,
        excluded_pages=excluded_pages,
    )
