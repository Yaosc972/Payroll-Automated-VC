from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from difflib import SequenceMatcher
from pathlib import Path
import re
from typing import Any

from .models import LaborLineItem
from .parsing import normalize_employee_name_advanced


_NUMBER_TOKEN_RE = re.compile(
    r"(?<![\d.,])-?(?:\d{1,3}(?:[.,]\d{3})+|\d+)[.,]\d{2,3}(?![\d.,])"
)
_STRUCTURED_LINE_RE = re.compile(
    r"^\s*\d+\s+(?P<description>.+?)\s*"
    r"(?P<hours>\d+(?:[.,]\d+)?)\s*[^\d\s]*\s*"
    r"(?P<rate>\d+[.,]\d{2,3})\s*"
    r"(?P<amount>(?:\d{1,3}(?:[.,]\d{3})*|\d+)[.,]\d{2})\s*$"
)
_FRENCH_EMPLOYEE_HEADER_RE = re.compile(
    r"^(?P<name>[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ .,'’-]+?)\s+"
    r"Semaine\s+\d+\s+du\b",
    re.IGNORECASE,
)
_FRENCH_EMPLOYEE_SUBTOTAL_RE = re.compile(r"^S\s*/\s*Total\s+(?P<values>.+?)\s*$", re.IGNORECASE)
_FRENCH_TOTAL_AFFECT_RE = re.compile(
    r"\bTotal\s+affect\.?\s+(?P<values>[^\r\n]+)",
    re.IGNORECASE,
)
_LOCALIZED_DECIMAL_RE = re.compile(r"(?:\d{1,3}(?:[ .]\d{3})+|\d+)[.,]\d{2}")


@dataclass(frozen=True)
class AmountClosure:
    detail_sum: float
    net_amount: float | None
    tax_amount: float | None
    gross_amount: float | None
    confidence: str
    evidence: tuple[str, ...]
    locale: str


@dataclass(frozen=True)
class WarehouseInference:
    status: str
    warehouse_id: str
    matched_count: int
    invoice_coverage: float
    excel_coverage: float
    runner_up_warehouse_id: str
    runner_up_matched_count: int
    evidence: tuple[dict, ...]


@dataclass(frozen=True)
class StructurePromotionResult:
    pdf_totals: list[dict[str, Any]]
    pdf_rows: list[LaborLineItem]
    decisions: list[dict[str, Any]]
    unresolved_files: tuple[str, ...]
    reconciled_files: tuple[str, ...]
    currency_codes: tuple[str, ...]


@dataclass(frozen=True)
class BatchGuardResult:
    status: str
    message: str
    allow_releasable_report: bool
    unresolved_files: tuple[str, ...]


def parse_localized_number(value: str, locale_hint: str = "") -> float | None:
    token = re.sub(r"[^0-9,.-]", "", str(value or "").strip())
    if not token or token in {"-", ".", ","}:
        return None
    if locale_hint == "comma_decimal":
        normalized = token.replace(".", "").replace(",", ".")
    elif locale_hint == "dot_decimal":
        normalized = token.replace(",", "")
    elif "," in token and "." in token:
        normalized = (
            token.replace(".", "").replace(",", ".")
            if token.rfind(",") > token.rfind(".")
            else token.replace(",", "")
        )
    elif re.search(r",\d{2,3}$", token):
        normalized = token.replace(".", "").replace(",", ".")
    else:
        normalized = token.replace(",", "")
    try:
        return float(normalized)
    except ValueError:
        return None


def _number_locale(text: str) -> str:
    comma_decimal = len(re.findall(r"\d{1,3}(?:\.\d{3})+,\d{2,3}\b", text))
    dot_decimal = len(re.findall(r"\d{1,3}(?:,\d{3})+\.\d{2,3}\b", text))
    if comma_decimal > dot_decimal:
        return "comma_decimal"
    if dot_decimal > comma_decimal:
        return "dot_decimal"
    comma_endings = len(re.findall(r"\d+,\d{2}\b", text))
    dot_endings = len(re.findall(r"\d+\.\d{2}\b", text))
    return "comma_decimal" if comma_endings > dot_endings else "dot_decimal"


def find_amount_closure(
    page_texts: list[str],
    detail_sum: float,
    tolerance: float = 0.10,
) -> AmountClosure:
    text = "\n".join(str(page or "") for page in page_texts)
    locale = _number_locale(text)
    parsed: list[tuple[str, float]] = []
    for match in _NUMBER_TOKEN_RE.finditer(text):
        value = parse_localized_number(match.group(0), locale)
        if value is not None and value >= 0:
            parsed.append((match.group(0), round(value, 3)))

    matching_net_indexes = [
        index
        for index, (_, value) in enumerate(parsed)
        if abs(value - detail_sum) <= tolerance
    ]
    if not matching_net_indexes:
        return AmountClosure(
            detail_sum=round(detail_sum, 2),
            net_amount=None,
            tax_amount=None,
            gross_amount=None,
            confidence="no_match",
            evidence=(),
            locale=locale,
        )
    if len(matching_net_indexes) != 1:
        return AmountClosure(
            detail_sum=round(detail_sum, 2),
            net_amount=round(detail_sum, 2),
            tax_amount=None,
            gross_amount=None,
            confidence="ambiguous",
            evidence=tuple(parsed[index][0] for index in matching_net_indexes),
            locale=locale,
        )

    net_index = matching_net_indexes[0]
    net_token, net_value = parsed[net_index]
    triples: list[tuple[float, float, str, str]] = []
    for tax_index, (tax_token, tax_value) in enumerate(parsed):
        if tax_index == net_index or tax_value <= 0:
            continue
        for gross_index, (gross_token, gross_value) in enumerate(parsed):
            if gross_index in {net_index, tax_index}:
                continue
            if abs(net_value + tax_value - gross_value) <= tolerance:
                candidate = (round(tax_value, 2), round(gross_value, 2), tax_token, gross_token)
                if candidate not in triples:
                    triples.append(candidate)

    if len(triples) == 1:
        tax_amount, gross_amount, tax_token, gross_token = triples[0]
        return AmountClosure(
            detail_sum=round(detail_sum, 2),
            net_amount=round(net_value, 2),
            tax_amount=tax_amount,
            gross_amount=gross_amount,
            confidence="high",
            evidence=(net_token, tax_token, gross_token),
            locale=locale,
        )
    if len(triples) > 1:
        return AmountClosure(
            detail_sum=round(detail_sum, 2),
            net_amount=round(net_value, 2),
            tax_amount=None,
            gross_amount=None,
            confidence="ambiguous",
            evidence=(net_token,),
            locale=locale,
        )
    return AmountClosure(
        detail_sum=round(detail_sum, 2),
        net_amount=round(net_value, 2),
        tax_amount=None,
        gross_amount=None,
        confidence="medium",
        evidence=(net_token,),
        locale=locale,
    )


def _page_evidence_amount_closure(
    page_evidence: list[dict[str, Any]],
    detail_sum: float,
    tolerance: float,
) -> AmountClosure | None:
    """Use explicit HT/TVA/TTC fields when an image-only PDF has no text layer."""
    candidates: list[AmountClosure] = []
    for item in page_evidence:
        try:
            net_amount = float(item.get("net_amount", item.get("netAmount")) or 0)
            tax_amount = float(item.get("tax_amount", item.get("taxAmount")) or 0)
            gross_amount = float(item.get("gross_amount", item.get("grossAmount")) or 0)
        except (TypeError, ValueError):
            continue
        if net_amount <= 0 or abs(net_amount - detail_sum) > tolerance:
            continue
        has_tax_closure = bool(
            tax_amount > 0
            and gross_amount > 0
            and abs(net_amount + tax_amount - gross_amount) <= tolerance
        )
        evidence_text = str(item.get("evidence_text") or item.get("evidenceText") or "").strip()
        candidates.append(
            AmountClosure(
                detail_sum=round(detail_sum, 2),
                net_amount=round(net_amount, 2),
                tax_amount=round(tax_amount, 2) if has_tax_closure else None,
                gross_amount=round(gross_amount, 2) if has_tax_closure else None,
                confidence="page_evidence_high" if has_tax_closure else "page_evidence_medium",
                evidence=(evidence_text[:240],) if evidence_text else (),
                locale="image_page_evidence",
            )
        )
    unique = {
        (candidate.net_amount, candidate.tax_amount, candidate.gross_amount): candidate
        for candidate in candidates
    }
    return next(iter(unique.values())) if len(unique) == 1 else None


def infer_warehouse_from_rows(
    pdf_rows: list[LaborLineItem],
    excel_rows: list[LaborLineItem],
) -> WarehouseInference:
    invoice_names = {
        normalize_employee_name_advanced(row.employee_name_raw)
        for row in pdf_rows
        if normalize_employee_name_advanced(row.employee_name_raw)
    }
    excel_names_by_warehouse: dict[str, set[str]] = {}
    for row in excel_rows:
        warehouse_id = str(row.warehouse_id or "").strip()
        normalized_name = normalize_employee_name_advanced(row.employee_name_raw)
        if warehouse_id and normalized_name:
            excel_names_by_warehouse.setdefault(warehouse_id, set()).add(normalized_name)

    scores: list[dict] = []
    for warehouse_id, warehouse_names in excel_names_by_warehouse.items():
        matched = invoice_names & warehouse_names
        scores.append(
            {
                "warehouse_id": warehouse_id,
                "matched_count": len(matched),
                "invoice_coverage": round(len(matched) / len(invoice_names), 4) if invoice_names else 0.0,
                "excel_coverage": round(len(matched) / len(warehouse_names), 4) if warehouse_names else 0.0,
                "matched_names": tuple(sorted(matched)),
            }
        )
    scores.sort(key=lambda item: (item["matched_count"], item["invoice_coverage"], item["excel_coverage"]), reverse=True)
    best = scores[0] if scores else {
        "warehouse_id": "",
        "matched_count": 0,
        "invoice_coverage": 0.0,
        "excel_coverage": 0.0,
    }
    runner_up = scores[1] if len(scores) > 1 else {
        "warehouse_id": "",
        "matched_count": 0,
        "invoice_coverage": 0.0,
    }
    matched = bool(
        best["matched_count"] >= 5
        and best["invoice_coverage"] >= 0.70
        and best["matched_count"] - runner_up["matched_count"] >= 3
        and runner_up["invoice_coverage"] < 0.30
    )
    return WarehouseInference(
        status="matched" if matched else "warehouse_review",
        warehouse_id=str(best["warehouse_id"]) if matched else "",
        matched_count=int(best["matched_count"]),
        invoice_coverage=float(best["invoice_coverage"]),
        excel_coverage=float(best["excel_coverage"]),
        runner_up_warehouse_id=str(runner_up["warehouse_id"]),
        runner_up_matched_count=int(runner_up["matched_count"]),
        evidence=tuple(scores),
    )


def assign_pdf_rows_to_excel_warehouses(
    pdf_rows: list[LaborLineItem],
    excel_rows: list[LaborLineItem],
) -> tuple[list[LaborLineItem], dict[str, Any]]:
    """Assign blank PDF row warehouses from a unique employee-name match."""
    excel_candidates: dict[str, set[str]] = {}
    for row in excel_rows:
        name = normalize_employee_name_advanced(row.employee_name_raw)
        warehouse_id = str(row.warehouse_id or "").strip()
        if name and warehouse_id:
            excel_candidates.setdefault(name, set()).add(warehouse_id)

    assigned_rows: list[LaborLineItem] = []
    audit_matches: list[dict[str, Any]] = []
    unresolved_count = 0
    for row in pdf_rows:
        if str(row.warehouse_id or "").strip():
            assigned_rows.append(row)
            audit_matches.append(
                {
                    "sourceFile": str(row.source_file or ""),
                    "employeeName": row.employee_name_raw,
                    "warehouseId": str(row.warehouse_id),
                    "method": "explicit",
                    "score": 1.0,
                }
            )
            continue

        pdf_name = normalize_employee_name_advanced(row.employee_name_raw)
        selected_warehouse = ""
        method = ""
        score = 0.0
        exact_warehouses = excel_candidates.get(pdf_name, set())
        if len(exact_warehouses) == 1:
            selected_warehouse = next(iter(exact_warehouses))
            method = "exact_name"
            score = 1.0
        elif pdf_name:
            scored = sorted(
                (
                    SequenceMatcher(None, pdf_name, excel_name).ratio(),
                    excel_name,
                    warehouses,
                )
                for excel_name, warehouses in excel_candidates.items()
                if len(warehouses) == 1
            )
            if scored:
                best_score = scored[-1][0]
                near_best_warehouses = {
                    next(iter(warehouses))
                    for candidate_score, _excel_name, warehouses in scored
                    if best_score - candidate_score <= 0.03
                }
                if best_score >= 0.82 and len(near_best_warehouses) == 1:
                    selected_warehouse = next(iter(near_best_warehouses))
                    method = "fuzzy_name"
                    score = best_score

        if selected_warehouse:
            assigned_rows.append(replace(row, warehouse_id=selected_warehouse))
            audit_matches.append(
                {
                    "sourceFile": str(row.source_file or ""),
                    "employeeName": row.employee_name_raw,
                    "warehouseId": selected_warehouse,
                    "method": method,
                    "score": round(score, 4),
                }
            )
        else:
            assigned_rows.append(row)
            unresolved_count += 1

    return assigned_rows, {
        "assignedRowCount": len(audit_matches),
        "unresolvedRowCount": unresolved_count,
        "matches": audit_matches,
    }


def extract_page_texts(path: Path) -> list[str]:
    try:
        from pypdf import PdfReader
    except Exception:
        return []
    try:
        reader = PdfReader(str(path))
        return [page.extract_text() or "" for page in reader.pages]
    except Exception:
        return []


def extract_structured_invoice_rows(
    pdf_paths: list[Path],
    excel_rows: list[LaborLineItem],
) -> list[LaborLineItem]:
    excel_names: dict[str, str] = {}
    excel_currency_by_name: dict[str, str] = {}
    for row in excel_rows:
        normalized = normalize_employee_name_advanced(row.employee_name_raw)
        if not normalized:
            continue
        excel_names.setdefault(normalized, row.employee_name_raw)
        currency = str(row.currency or "").strip().upper()
        if currency:
            excel_currency_by_name.setdefault(normalized, currency)
    ordered_names = sorted(excel_names, key=len, reverse=True)

    extracted: list[LaborLineItem] = []
    for path in pdf_paths:
        page_texts = extract_page_texts(path)
        closed_subtotal_rows = _extract_closed_employee_subtotal_rows(path, page_texts)
        if closed_subtotal_rows:
            extracted.extend(closed_subtotal_rows)
            continue
        for page_number, text in enumerate(page_texts, start=1):
            locale = _number_locale(text)
            page_currency = "EUR" if "€" in text or re.search(r"\bEUR\b", text, re.IGNORECASE) else "USD" if "$" in text else ""
            for raw_line in text.splitlines():
                match = _STRUCTURED_LINE_RE.match(" ".join(raw_line.split()))
                if not match:
                    continue
                description = match.group("description").strip()
                normalized_description = normalize_employee_name_advanced(description)
                matched_name = next(
                    (
                        name
                        for name in ordered_names
                        if normalized_description == name or normalized_description.startswith(f"{name} ")
                    ),
                    "",
                )
                if not matched_name:
                    continue
                hours = parse_localized_number(match.group("hours"), locale)
                amount = parse_localized_number(match.group("amount"), locale)
                if hours is None or amount is None or hours < 0 or amount <= 0:
                    continue
                extracted.append(
                    LaborLineItem(
                        source_type="pdf_invoice",
                        source_file=path.name,
                        source_page_or_row=f"p{page_number}",
                        employee_id="",
                        employee_name_raw=excel_names[matched_name],
                        hours=round(hours, 3),
                        amount=round(amount, 2),
                        currency=page_currency or excel_currency_by_name.get(matched_name, ""),
                        confidence=1.0,
                        evidence_text=raw_line.strip(),
                        warehouse_id="",
                    )
                )
    return extracted


def _extract_closed_employee_subtotal_rows(
    path: Path,
    page_texts: list[str],
    tolerance: float = 0.10,
) -> list[LaborLineItem]:
    """Read French employee blocks only when every subtotal closes to the invoice net total."""
    document_text = "\n".join(page_texts)
    if not (
        re.search(r"\bDETAIL\s+DES\s+PRESTATIONS\b", document_text, re.IGNORECASE)
        and re.search(r"\bSemaine\s+\d+\s+du\b", document_text, re.IGNORECASE)
        and re.search(r"\bS\s*/\s*Total\b", document_text, re.IGNORECASE)
    ):
        return []

    locale = _number_locale(document_text)
    current_name = ""
    rows: list[LaborLineItem] = []
    for page_number, text in enumerate(page_texts, start=1):
        for raw_line in text.splitlines():
            line = " ".join(raw_line.split())
            header = _FRENCH_EMPLOYEE_HEADER_RE.match(line)
            if header:
                current_name = " ".join(header.group("name").split()).strip(" ,.'-")
                continue
            subtotal = _FRENCH_EMPLOYEE_SUBTOTAL_RE.match(line)
            if not subtotal or not current_name:
                continue
            values = _LOCALIZED_DECIMAL_RE.findall(subtotal.group("values"))
            parsed = [parse_localized_number(value, locale) for value in values]
            parsed = [value for value in parsed if value is not None]
            if not parsed or parsed[-1] <= 0:
                continue
            hours = parsed[0] if len(parsed) > 1 else 0.0
            rows.append(
                LaborLineItem(
                    source_type="pdf_invoice",
                    source_file=path.name,
                    source_page_or_row=f"p{page_number}",
                    employee_id="",
                    employee_name_raw=current_name,
                    hours=round(hours, 3),
                    amount=round(parsed[-1], 2),
                    currency="EUR" if "€" in document_text or re.search(r"EUR\b", document_text, re.IGNORECASE) else "",
                    confidence=1.0,
                    evidence_text=line,
                    warehouse_id="",
                    description="employee_subtotal_closed",
                )
            )
            current_name = ""

    invoice_totals = []
    for match in _FRENCH_TOTAL_AFFECT_RE.finditer(document_text):
        values = _LOCALIZED_DECIMAL_RE.findall(match.group("values"))
        if values:
            invoice_totals.append(parse_localized_number(values[-1], locale))
    invoice_totals = [value for value in invoice_totals if value is not None and value > 0]
    detail_sum = round(sum(row.amount for row in rows), 2)
    if not rows or len({round(value, 2) for value in invoice_totals}) != 1:
        return []
    if abs(detail_sum - round(invoice_totals[0], 2)) > tolerance:
        return []
    return rows


def prefer_closed_structured_rows(
    ai_rows: list[LaborLineItem],
    structured_rows: list[LaborLineItem],
    pdf_paths: list[Path],
    tolerance: float = 0.10,
) -> list[LaborLineItem]:
    paths_by_name = {path.name: path for path in pdf_paths}
    ai_by_source: dict[str, list[LaborLineItem]] = {}
    structured_by_source: dict[str, list[LaborLineItem]] = {}
    for row in ai_rows:
        ai_by_source.setdefault(str(row.source_file or ""), []).append(row)
    for row in structured_rows:
        structured_by_source.setdefault(str(row.source_file or ""), []).append(row)

    selected_by_source = dict(ai_by_source)
    for source_file, rows in structured_by_source.items():
        path = paths_by_name.get(source_file)
        if not path:
            continue
        detail_sum = round(sum(float(row.amount or 0) for row in rows), 2)
        closure = find_amount_closure(extract_page_texts(path), detail_sum, tolerance)
        preclosed_subtotals = bool(rows) and all(
            row.description == "employee_subtotal_closed" for row in rows
        )
        if preclosed_subtotals or closure.confidence in {"high", "medium"}:
            selected_by_source[source_file] = rows

    ordered_sources = [path.name for path in pdf_paths]
    ordered_sources.extend(source for source in selected_by_source if source not in ordered_sources)
    return [row for source in ordered_sources for row in selected_by_source.get(source, [])]


def _row_page_number(row: LaborLineItem) -> int:
    match = re.search(r"(?:^|\b)p(?:age)?\s*(\d+)\b", str(row.source_page_or_row or ""), re.IGNORECASE)
    return int(match.group(1)) if match else 1


def _complete_image_detail_sources(
    pdf_paths: list[Path],
    pdf_rows: list[LaborLineItem],
    excel_rows: list[LaborLineItem],
    page_audit: list[dict[str, Any]] | None,
    tolerance: float,
) -> set[str]:
    """Return source files with complete, high-confidence image-row evidence.

    This is a batch-level fallback for image-only invoices. It never guesses a
    warehouse and is disabled unless every PDF page completed with the same
    positive, evidenced rows that reached reconciliation. Excel equality is not
    a completeness signal because genuine invoice differences must remain visible.
    """
    if not pdf_paths or not page_audit or not pdf_rows or not excel_rows:
        return set()

    audit_by_source: dict[str, list[dict[str, Any]]] = {}
    for item in page_audit:
        source_file = str(item.get("sourceFile") or item.get("source_file") or "").strip()
        if source_file:
            audit_by_source.setdefault(source_file, []).append(item)

    path_names = {path.name for path in pdf_paths}
    for path in pdf_paths:
        expected_page_count = len(extract_page_texts(path))
        audited = audit_by_source.get(path.name, [])
        audited_pages = {int(item.get("page") or 0) for item in audited}
        if (
            expected_page_count <= 0
            or audited_pages != set(range(1, expected_page_count + 1))
            or any(
                str(item.get("status") or "").lower() not in {"completed", "cache_hit"}
                for item in audited
            )
            or any(int(item.get("rowCount") or 0) <= 0 for item in audited)
        ):
            return set()

    scoped_pdf_rows = [row for row in pdf_rows if str(row.source_file or "") in path_names]
    if (
        not scoped_pdf_rows
        or {str(row.source_file or "") for row in scoped_pdf_rows} != path_names
        or any(float(row.amount or 0) <= 0 for row in scoped_pdf_rows)
        or any(float(row.confidence or 0) < 0.90 for row in scoped_pdf_rows)
        or any(not str(row.evidence_text or "").strip() for row in scoped_pdf_rows)
    ):
        return set()
    del excel_rows, tolerance
    extracted_counts: dict[tuple[str, int], int] = {}
    for row in scoped_pdf_rows:
        key = (str(row.source_file or ""), _row_page_number(row))
        extracted_counts[key] = extracted_counts.get(key, 0) + 1
    for source_file, audited in audit_by_source.items():
        for item in audited:
            page = int(item.get("page") or 0)
            if extracted_counts.get((source_file, page), 0) != int(item.get("rowCount") or 0):
                return set()
    return path_names


def _image_detail_batch_closes_to_excel(
    pdf_rows: list[LaborLineItem],
    excel_rows: list[LaborLineItem],
    tolerance: float,
) -> bool:
    """Use workbook equality only as corroboration for otherwise unclosed image rows."""
    def aggregate(rows: list[LaborLineItem]) -> dict[str, float]:
        result: dict[str, float] = {}
        for row in rows:
            name = normalize_employee_name_advanced(row.employee_name_raw)
            if not name:
                return {}
            result[name] = round(result.get(name, 0.0) + float(row.amount or 0), 2)
        return result

    pdf_by_name = aggregate(pdf_rows)
    excel_by_name = aggregate(excel_rows)
    return bool(
        pdf_by_name
        and pdf_by_name.keys() == excel_by_name.keys()
        and all(abs(amount - excel_by_name[name]) <= tolerance for name, amount in pdf_by_name.items())
    )


def promote_structured_invoice_evidence(
    pdf_paths: list[Path],
    pdf_totals: list[dict[str, Any]],
    raw_pdf_rows: list[LaborLineItem],
    excel_rows: list[LaborLineItem],
    tolerance: float = 0.10,
    page_audit: list[dict[str, Any]] | None = None,
) -> StructurePromotionResult:
    paths_by_name = {path.name: path for path in pdf_paths}
    raw_pdf_rows, row_warehouse_assignment = assign_pdf_rows_to_excel_warehouses(raw_pdf_rows, excel_rows)
    rows_by_source: dict[str, list[LaborLineItem]] = {}
    currency_codes: set[str] = set()
    for row in raw_pdf_rows:
        rows_by_source.setdefault(str(row.source_file or ""), []).append(row)
        currency = str(row.currency or "").strip().upper()
        if currency:
            currency_codes.add(currency)

    promoted_totals: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    unresolved_files: list[str] = []
    reconciled_files: list[str] = []
    inferred_warehouses: dict[str, str] = {}
    complete_detail_sources = _complete_image_detail_sources(
        pdf_paths,
        raw_pdf_rows,
        excel_rows,
        page_audit,
        tolerance,
    )
    image_batch_closes_to_excel = _image_detail_batch_closes_to_excel(
        raw_pdf_rows,
        excel_rows,
        tolerance,
    )
    for original in pdf_totals:
        total = dict(original)
        source_file = str(total.get("source_file") or "")
        source_rows = rows_by_source.get(source_file, [])
        explicitly_unresolved = bool(
            total.get("authoritative") is False
            or str(total.get("evidence_status") or "").strip().lower() == "needs_review"
        )
        needs_fallback = bool(
            explicitly_unresolved
            or float(total.get("total_amount") or 0) <= 0
            or not str(total.get("warehouse_id") or "").strip()
        )
        if not needs_fallback:
            promoted_totals.append(total)
            reconciled_files.append(source_file)
            continue

        detail_sum = round(sum(float(row.amount or 0) for row in source_rows), 2)
        page_texts = extract_page_texts(paths_by_name[source_file]) if source_file in paths_by_name else []
        closure = find_amount_closure(page_texts, detail_sum, tolerance)
        page_evidence_closure = _page_evidence_amount_closure(
            list(total.get("page_evidence") or []),
            detail_sum,
            tolerance,
        )
        if closure.confidence in {"no_match", "ambiguous"} and page_evidence_closure is not None:
            closure = page_evidence_closure
        complete_line_sum_closes = source_file in complete_detail_sources
        if complete_line_sum_closes and (
            closure.confidence == "ambiguous"
            or (closure.confidence == "no_match" and image_batch_closes_to_excel)
        ):
            closure = AmountClosure(
                detail_sum=detail_sum,
                net_amount=detail_sum,
                tax_amount=None,
                gross_amount=None,
                confidence="complete_line_sum",
                evidence=tuple(str(row.evidence_text or "")[:160] for row in source_rows),
                locale=closure.locale,
            )
        authoritative_total = round(float(total.get("total_amount") or 0), 2)
        authoritative_total_closes = bool(
            total.get("authoritative") is True
            and authoritative_total > 0
            and abs(authoritative_total - detail_sum) <= tolerance
        )
        amount_closes = closure.confidence in {
            "high",
            "medium",
            "complete_line_sum",
            "page_evidence_high",
            "page_evidence_medium",
        } or authoritative_total_closes
        warehouse = infer_warehouse_from_rows(source_rows, excel_rows)
        source_warehouses = {
            str(row.warehouse_id or "").strip()
            for row in source_rows
            if str(row.warehouse_id or "").strip()
        }
        all_source_rows_assigned = bool(source_rows) and all(
            str(row.warehouse_id or "").strip() for row in source_rows
        )
        if len(source_warehouses) == 1 and all_source_rows_assigned:
            assigned_warehouse = next(iter(source_warehouses))
            warehouse = WarehouseInference(
                status="matched",
                warehouse_id=assigned_warehouse,
                matched_count=len(source_rows),
                invoice_coverage=1.0,
                excel_coverage=1.0,
                runner_up_warehouse_id="",
                runner_up_matched_count=0,
                evidence=({"warehouse_id": assigned_warehouse, "method": "unique_employee_assignment"},),
            )
        explicit_warehouse = str(total.get("warehouse_id") or "").strip()
        warehouse_conflict = bool(
            explicit_warehouse
            and warehouse.status == "matched"
            and explicit_warehouse != warehouse.warehouse_id
        )
        if not amount_closes:
            status = "amount_review"
            reason = "员工行金额无法与页面中的唯一金额候选闭合。"
        elif len(source_warehouses) > 1 and all_source_rows_assigned:
            status = "reconciled_multi_warehouse"
            reason = "员工行金额与发票总额闭合，且已按员工姓名唯一分配到多个仓库。"
            warehouse = WarehouseInference(
                status="mixed_warehouses",
                warehouse_id="",
                matched_count=len(source_rows),
                invoice_coverage=1.0,
                excel_coverage=0.0,
                runner_up_warehouse_id="",
                runner_up_matched_count=0,
                evidence=tuple(
                    {
                        "warehouse_id": warehouse_id,
                        "row_count": sum(1 for row in source_rows if str(row.warehouse_id or "") == warehouse_id),
                    }
                    for warehouse_id in sorted(source_warehouses)
                ),
            )
            total.update(
                {
                    "total_amount": round(
                        authoritative_total if authoritative_total_closes else float(closure.net_amount or detail_sum),
                        2,
                    ),
                    "pdf_type": "primary",
                    "authoritative": True,
                    "evidence_status": "authoritative",
                    "extraction_method": str(total.get("extraction_method") or "structural_multi_warehouse_closure"),
                }
            )
            reconciled_files.append(source_file)
        elif warehouse.status != "matched" or warehouse_conflict:
            if amount_closes and not warehouse_conflict:
                accepted_pages = {_row_page_number(row) for row in source_rows}
                total.update(
                    {
                        "total_amount": round(float(closure.net_amount or detail_sum), 2),
                        "pdf_type": "primary",
                        "authoritative": True,
                        "evidence_status": "authoritative",
                        "total_label": "complete_invoice_line_sum",
                        "total_page": max(accepted_pages) if accepted_pages else None,
                        "extraction_method": "complete_invoice_line_sum",
                    }
                )
                status = "reconciled_amount_warehouse_review"
                reason = "员工行金额与整批 Excel 闭合；仓库未唯一识别，保留仓库待确认。"
                reconciled_files.append(source_file)
            else:
                status = "warehouse_review"
                reason = "员工名单无法唯一确定仓库，或与发票显式仓库冲突。"
        else:
            status = "reconciled"
            reason = "员工行金额与页面金额闭合，且员工名单唯一匹配仓库。"
            accepted_pages = {_row_page_number(row) for row in source_rows}
            page_evidence = []
            for item in total.get("page_evidence") or []:
                page_item = dict(item)
                page = int(page_item.get("page") or 1)
                if page in accepted_pages:
                    page_item["role"] = "invoice_total" if page == max(accepted_pages) else "invoice_continuation"
                    page_item["role_confidence"] = max(float(page_item.get("role_confidence") or 0), 0.95)
                    page_item["warehouse_id"] = warehouse.warehouse_id
                    page_item["extraction_method"] = "structural_closure"
                page_evidence.append(page_item)
            if not page_evidence:
                page_evidence = [
                    {
                        "page": page,
                        "role": "invoice_total" if page == max(accepted_pages) else "invoice_continuation",
                        "role_confidence": 0.95,
                        "warehouse_id": warehouse.warehouse_id,
                        "extraction_method": "structural_closure",
                    }
                    for page in sorted(accepted_pages)
                ]
            total.update(
                {
                    "total_amount": round(float(closure.net_amount or detail_sum), 2),
                    "warehouse_id": warehouse.warehouse_id,
                    "pdf_type": "primary",
                    "authoritative": True,
                    "evidence_status": "authoritative",
                    "total_label": "employee_detail_sum",
                    "total_page": max(accepted_pages),
                    "page_evidence": page_evidence,
                    "excluded_pages": [
                        int(item.get("page") or 1)
                        for item in page_evidence
                        if int(item.get("page") or 1) not in accepted_pages
                    ],
                    "extraction_method": "structural_closure",
                }
            )
            inferred_warehouses[source_file] = warehouse.warehouse_id
            reconciled_files.append(source_file)

        if status not in {"reconciled", "reconciled_multi_warehouse", "reconciled_amount_warehouse_review"}:
            unresolved_files.append(source_file)
        decisions.append(
            {
                "sourceFile": source_file,
                "status": status,
                "reason": reason,
                "detailSum": detail_sum,
                "closure": asdict(closure),
                "warehouse": asdict(warehouse),
                "explicitWarehouseId": explicit_warehouse,
                "rowWarehouseAssignment": {
                    "assignedRowCount": sum(
                        1
                        for item in row_warehouse_assignment.get("matches", [])
                        if item.get("sourceFile") == source_file
                    ),
                    "unresolvedRowCount": sum(
                        1
                        for row in source_rows
                        if not str(row.warehouse_id or "").strip()
                    ),
                },
            }
        )
        promoted_totals.append(total)

    return StructurePromotionResult(
        pdf_totals=promoted_totals,
        pdf_rows=[
            replace(row, warehouse_id=inferred_warehouses[str(row.source_file or "")])
            if str(row.source_file or "") in inferred_warehouses
            else row
            for row in raw_pdf_rows
        ],
        decisions=decisions,
        unresolved_files=tuple(unresolved_files),
        reconciled_files=tuple(reconciled_files),
        currency_codes=tuple(sorted(currency_codes)),
    )


def resolve_amount_scope(header: str, declared_scope: str = "") -> str:
    declared = str(declared_scope or "").strip().lower()
    if declared in {"net", "gross"}:
        return declared
    if declared and declared not in {"auto", "review"}:
        return "review"
    normalized = " ".join(str(header or "").strip().lower().split())
    if any(token in normalized for token in ("不含税", "net", "before tax", "excluding tax")):
        return "net"
    if any(token in normalized for token in ("含税", "gross", "after tax", "including tax")):
        return "gross"
    return "review"


def evaluate_batch_guards(
    pdf_paths: list[Path],
    pdf_totals: list[dict[str, Any]],
    raw_pdf_rows: list[LaborLineItem],
    formal_pdf_rows: list[LaborLineItem],
    excel_rows: list[LaborLineItem],
    requested_currency: str,
    detected_currencies: set[str],
    unresolved_files: list[str] | tuple[str, ...] = (),
    pdf_text_coverage: dict[str, Any] | None = None,
) -> BatchGuardResult:
    del excel_rows
    formal_total = round(sum(float(item.get("total_amount") or 0) for item in pdf_totals), 2)
    coverage_summary = (
        pdf_text_coverage.get("summary", {})
        if isinstance(pdf_text_coverage, dict)
        else {}
    )
    all_pdfs_image_only = bool(pdf_paths) and int(coverage_summary.get("imageOnlyFileCount") or 0) >= len(pdf_paths)
    page_evidence_exists = any(
        str(page.get("evidence_text") or "").strip()
        for item in pdf_totals
        for page in (item.get("page_evidence") or [])
        if isinstance(page, dict)
    )
    if pdf_paths and formal_total <= 0 and (
        raw_pdf_rows or formal_pdf_rows or page_evidence_exists or all_pdfs_image_only
    ):
        return BatchGuardResult(
            status="pdf_recognition_incomplete",
            message="PDF 已检测到员工或金额证据，但正式金额未生成。本次属于识别异常，不是业务差异。",
            allow_releasable_report=False,
            unresolved_files=tuple(sorted(set(unresolved_files))),
        )

    requested = str(requested_currency or "").strip().upper()
    detected = {str(code or "").strip().upper() for code in detected_currencies if str(code or "").strip()}
    if requested and detected and requested not in detected:
        return BatchGuardResult(
            status="currency_review",
            message=f"批次币种为 {requested}，发票识别币种为 {', '.join(sorted(detected))}，确认前不能放行。",
            allow_releasable_report=False,
            unresolved_files=tuple(sorted(set(unresolved_files))),
        )

    total_sources = {
        str(item.get("source_file") or "").strip()
        for item in pdf_totals
        if str(item.get("source_file") or "").strip()
    }
    declared_detail_sources = {
        str(item.get("source_file") or "").strip()
        for item in pdf_totals
        if item.get("has_employee_detail") and str(item.get("source_file") or "").strip()
    }
    expected_detail_sources = declared_detail_sources or total_sources or {path.name for path in pdf_paths}
    extracted_detail_sources = {
        str(row.source_file or "").strip()
        for row in formal_pdf_rows
        if str(row.source_file or "").strip()
    }
    missing_detail_sources = tuple(sorted(expected_detail_sources - extracted_detail_sources))
    if missing_detail_sources:
        return BatchGuardResult(
            status="employee_detail_incomplete",
            message=f"仍有 {len(missing_detail_sources)} 份应核对 PDF 未形成员工明细，确认前不能机器通过。",
            allow_releasable_report=False,
            unresolved_files=missing_detail_sources,
        )

    unresolved = tuple(sorted(set(unresolved_files)))
    if unresolved:
        return BatchGuardResult(
            status="partial_review",
            message=f"已完成部分发票核对；仍有 {len(unresolved)} 张发票待确认。",
            allow_releasable_report=False,
            unresolved_files=unresolved,
        )
    return BatchGuardResult(
        status="ok",
        message="结构和金额证据已完成核对。",
        allow_releasable_report=True,
        unresolved_files=(),
    )
