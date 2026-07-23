from __future__ import annotations

import re
from typing import Any

from .models import LaborLineItem
from .parsing import parse_number


_NUMBER = r"-?\d[\d,]*(?:\.\d+)?"
_NAME = r"[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ\s,.'-]*?"
_EMBEDDED_NAME_DIGIT_MAP = str.maketrans({"0": "O", "1": "I", "5": "S", "7": "Z", "8": "B"})
_DATE_PAY_ROW_RE = re.compile(
    rf"^\d{{1,2}}/\d{{1,2}}/\d{{4}}\s+(?P<name>{_NAME})\s+"
    rf"(?:Reg|Regular|OT|Overtime|DT|Doubletime)\s+"
    rf"\$?\s*{_NUMBER}\s+(?P<hours>{_NUMBER})\s+\$?\s*{_NUMBER}\s+\$?\s*(?P<amount>{_NUMBER})$",
    re.IGNORECASE,
)
_RATE_SUMMARY_RE = re.compile(
    rf"^(?P<name>{_NAME})\s+[\$S]\s*{_NUMBER}\s+[\$S]\s*{_NUMBER}\s+[\$S]\s*{_NUMBER}\s+(?P<rest>.+)$"
)
_SIMPLE_HOURS_AMOUNT_RE = re.compile(
    rf"^(?P<name>{_NAME})\s+(?P<hours>{_NUMBER})\s+(?P<rate>{_NUMBER})\s+(?P<amount>{_NUMBER})$"
)
_LOCALIZED_DECIMAL_RE = re.compile(r"(?:\d{1,3}(?:[ .]\d{3})+|\d+)[.,]\d{2}")
_FRENCH_WEEK_HEADER_RE = re.compile(
    r"^(?P<name>[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ .,'’-]+?)\s+"
    r"Semaine\s+\d+\s+du\b",
    re.IGNORECASE,
)
_FRENCH_SUBTOTAL_LABEL = r"S\s*/?\s*T(?:o)?tal"
_FRENCH_NAMED_SUBTOTAL_RE = re.compile(
    rf"^{_FRENCH_SUBTOTAL_LABEL}\s+Int(?:é|e)rimaire\s*:\s*(?P<body>.+)$",
    re.IGNORECASE,
)
_FRENCH_PLAIN_SUBTOTAL_RE = re.compile(
    rf"^{_FRENCH_SUBTOTAL_LABEL}\s+(?P<values>.+?)\s*$",
    re.IGNORECASE,
)


def extract_rows_from_visual_pages(
    pages: list[dict[str, Any]],
    *,
    supplier: str = "",
    period_start: str = "",
    period_end: str = "",
    currency: str = "",
) -> list[LaborLineItem]:
    rows: list[LaborLineItem] = []
    document_text_by_source: dict[str, str] = {}
    french_current_name: dict[str, str] = {}
    for page in pages:
        source_file = str(page.get("source_file") or page.get("file") or "")
        page_text = str(page.get("visualText") or page.get("visual_text") or "")
        document_text_by_source[source_file] = f"{document_text_by_source.get(source_file, '')}\n{page_text}"
    for page in pages:
        text = str(page.get("visualText") or page.get("visual_text") or "")
        source_file = str(page.get("source_file") or page.get("file") or "")
        document_text = document_text_by_source.get(source_file, text)
        has_simple_hours_table = bool(
            re.search(r"\bHRS\b", document_text, re.IGNORECASE)
            and re.search(r"BILL\s+RATE", document_text, re.IGNORECASE)
            and re.search(r"\bAMOUNT\b", document_text, re.IGNORECASE)
        )
        has_rate_summary = bool(
            re.search(r"Associate\s+Base\s+Rate\s+.+?Rate\s+OT\s+Rate", document_text, re.IGNORECASE)
        )
        for raw_line in text.splitlines():
            line = " ".join(raw_line.split())
            line = re.sub(
                r"-?WK\s+\d{1,2}/\d{1,2}/\d{4}\s+",
                " ",
                line,
                flags=re.IGNORECASE,
            )
            line = " ".join(line.split())
            line = re.sub(
                r"(?<=[A-Za-zÀ-ÖØ-öø-ÿ])[01578](?=[A-Za-zÀ-ÖØ-öø-ÿ])",
                lambda match: match.group().translate(_EMBEDDED_NAME_DIGIT_MAP),
                line,
            )
            named_subtotal = _parse_french_named_subtotal(line)
            if named_subtotal is not None:
                name, hours, amount = named_subtotal
                rows.append(
                    _candidate_row(
                        source_file,
                        page,
                        line,
                        name,
                        hours,
                        amount,
                        supplier=supplier,
                        period_start=period_start,
                        period_end=period_end,
                        currency=currency,
                    )
                )
                french_current_name.pop(source_file, None)
                continue
            french_header = _FRENCH_WEEK_HEADER_RE.match(line)
            if french_header:
                french_current_name[source_file] = " ".join(french_header.group("name").split()).strip(" ,.'-")
                continue
            plain_subtotal = _parse_french_plain_subtotal(line)
            if plain_subtotal is not None and french_current_name.get(source_file):
                hours, amount = plain_subtotal
                rows.append(
                    _candidate_row(
                        source_file,
                        page,
                        line,
                        french_current_name.pop(source_file),
                        hours,
                        amount,
                        supplier=supplier,
                        period_start=period_start,
                        period_end=period_end,
                        currency=currency,
                    )
                )
                continue
            parsed = _parse_date_pay_row(line)
            if parsed is None and has_rate_summary:
                parsed = _parse_rate_summary_row(line)
            if parsed is None and has_simple_hours_table:
                parsed = _parse_simple_hours_amount_row(line)
            if parsed is None:
                continue
            name, hours, amount = parsed
            rows.append(
                LaborLineItem(
                    source_type="pdf_invoice_candidate",
                    source_file=source_file,
                    source_page_or_row=f"p{int(page.get('page') or 0)}",
                    employee_id="",
                    employee_name_raw=name,
                    hours=round(hours, 3),
                    amount=round(amount, 2),
                    currency=currency,
                    confidence=0.90,
                    evidence_text=f"rapidocr_visual_row: {line}",
                    supplier=supplier,
                    period_start=period_start,
                    period_end=period_end,
                    warehouse_id="",
                )
            )
    return rows


def _candidate_row(
    source_file: str,
    page: dict[str, Any],
    line: str,
    name: str,
    hours: float,
    amount: float,
    *,
    supplier: str,
    period_start: str,
    period_end: str,
    currency: str,
) -> LaborLineItem:
    return LaborLineItem(
        source_type="pdf_invoice_candidate",
        source_file=source_file,
        source_page_or_row=f"p{int(page.get('page') or 0)}",
        employee_id="",
        employee_name_raw=name,
        hours=round(hours, 3),
        amount=round(amount, 2),
        currency=currency,
        confidence=0.95,
        evidence_text=f"rapidocr_visual_row: {line}",
        supplier=supplier,
        period_start=period_start,
        period_end=period_end,
        warehouse_id="",
    )


def _parse_french_named_subtotal(line: str) -> tuple[str, float, float] | None:
    match = _FRENCH_NAMED_SUBTOTAL_RE.match(line)
    if not match:
        return None
    body = match.group("body")
    values = list(_LOCALIZED_DECIMAL_RE.finditer(body))
    if not values:
        return None
    name = body[: values[0].start()].strip(" ,.'-")
    parsed = [parse_number(value.group()) for value in values]
    hours, amount = _french_subtotal_values(parsed)
    if len(re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]", name)) < 2 or amount <= 0:
        return None
    return name, hours, amount


def _parse_french_plain_subtotal(line: str) -> tuple[float, float] | None:
    match = _FRENCH_PLAIN_SUBTOTAL_RE.match(line)
    if not match:
        return None
    values_text = match.group("values")
    matches = _LOCALIZED_DECIMAL_RE.findall(values_text)
    if not matches or " ".join(matches) != " ".join(values_text.split()):
        return None
    hours, amount = _french_subtotal_values([parse_number(value) for value in matches])
    return (hours, amount) if amount > 0 else None


def _french_subtotal_values(values: list[float]) -> tuple[float, float]:
    amount = values[-1] if values else 0.0
    hours = 0.0
    if len(values) > 1 and 0 < values[0] <= 80 and abs(values[0] - amount) > 0.01:
        hours = values[0]
    return hours, amount


def _parse_date_pay_row(line: str) -> tuple[str, float, float] | None:
    match = _DATE_PAY_ROW_RE.match(line)
    if not match:
        return None
    return _valid_row(match.group("name"), match.group("hours"), match.group("amount"))


def _parse_simple_hours_amount_row(line: str) -> tuple[str, float, float] | None:
    if line.upper().startswith(("TOTAL", "LAST NAME", "FIRST NAME")):
        return None
    match = _SIMPLE_HOURS_AMOUNT_RE.match(line)
    if not match:
        return None
    parsed = _valid_row(match.group("name"), match.group("hours"), match.group("amount"))
    if parsed is None:
        return None
    name, hours, amount = parsed
    amount_decimals = match.group("amount").partition(".")[2]
    calculated_amount = round(hours * parse_number(match.group("rate")), 2)
    if len(amount_decimals) < 2 and abs(calculated_amount - amount) <= 0.50:
        amount = calculated_amount
    return name, hours, amount


def _parse_rate_summary_row(line: str) -> tuple[str, float, float] | None:
    if line.lower().startswith(("totals ", "associate ", "if paid ")):
        return None
    match = _RATE_SUMMARY_RE.match(line)
    if match:
        rest = match.group("rest")
        hours_text = re.split(r"\s+[\$S]\s*", rest, maxsplit=1)[0]
        hours_values = [parse_number(value) for value in re.findall(_NUMBER, hours_text)]
        all_values = [parse_number(value) for value in re.findall(_NUMBER, rest)]
        if hours_values and all_values:
            return _valid_row(match.group("name"), str(sum(hours_values)), str(all_values[-1]))

    number_matches = list(re.finditer(_NUMBER, line))
    if len(number_matches) < 6:
        return None
    rate_prefix = line[: number_matches[3].start()]
    currency_markers = rate_prefix.count("$") + len(re.findall(r"\bS(?=\s*\d)", rate_prefix))
    if currency_markers < 2:
        return None
    name = line[: number_matches[0].start()].strip(" $-:")
    values = [parse_number(item.group()) for item in number_matches]
    hours = values[3]
    if len(values) >= 7 and values[4] <= 24:
        hours += values[4]
    return _valid_row(name, str(hours), str(values[-1]))


def _valid_row(name: str, hours_raw: str, amount_raw: str) -> tuple[str, float, float] | None:
    cleaned_name = " ".join(name.strip(" -:").split())
    hours = parse_number(hours_raw)
    amount = parse_number(amount_raw)
    if len(re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]", cleaned_name)) < 2 or hours < 0 or amount <= 0:
        return None
    return cleaned_name, hours, amount
