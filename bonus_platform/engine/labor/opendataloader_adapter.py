from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .extract import _warehouse_id_from_filename, _warehouse_id_from_text
from .models import LaborLineItem
from .parsing import parse_number


_DATE_TOKEN = r"\d{1,2}/\d{1,2}/\d{4}"
_NAME_TOKEN = r"[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ\s,.'-]*?"
_NUMBER_TOKEN = r"\d[\d,]*(?:\.\d+)?"
_MONEY_TOKEN = r"\$\s*\d[\d,]*\.\d{2}"

_ROW_RE = re.compile(
    rf"(?P<date>{_DATE_TOKEN})\s+"
    rf"(?P<name>{_NAME_TOKEN})\s+"
    rf"(?P<hours>{_NUMBER_TOKEN})\s+"
    rf"(?P<pay_code>CAPenalty|Reg|OT|DT)\s+"
    rf"(?P<pay_type>REG|OT|DT)\s+"
    rf"\$\s*(?P<pay_rate>{_NUMBER_TOKEN})\s+"
    rf"\$?\s*(?P<bill_rate>{_NUMBER_TOKEN})\s+"
    rf"(?P<amount>{_MONEY_TOKEN})",
    re.IGNORECASE,
)

_INVOICE_AMOUNT_RE = re.compile(
    r"(?:Invoice\s*(?:Amt|Amount)|Invoice\s*Total|Total\s*Due)\s*[:#]?\s*\$?\s*(\d[\d,]*\.\d{2})",
    re.IGNORECASE,
)
_ANY_AMOUNT_RE = re.compile(r"\$\s*\d[\d,]*\.\d{2}")


def extract_labor_rows_from_opendataloader_json(
    json_path: Path,
    *,
    supplier: str = "",
    period_start: str = "",
    period_end: str = "",
    currency: str = "USD",
) -> List[LaborLineItem]:
    """Convert OpenDataLoader PDF JSON output into labor invoice line items."""
    data = json.loads(json_path.read_text(encoding="utf-8"))
    source_file = str(data.get("file name") or data.get("file_name") or json_path.with_suffix(".pdf").name)
    all_text = " ".join(_iter_content_text(data))
    warehouse_id = _warehouse_id_from_text(all_text) or _warehouse_id_from_filename(source_file)

    rows: List[LaborLineItem] = []
    seen: set[Tuple[str, str, float, float, str, str]] = set()
    for text, page_ref in _iter_row_candidates(data):
        for match in _ROW_RE.finditer(_compact_text(text)):
            name = _clean_employee_name(match.group("name"))
            if not name:
                continue
            hours = round(parse_number(match.group("hours")), 2)
            amount = round(parse_number(match.group("amount")), 2)
            if not amount:
                continue
            identity = (
                source_file,
                match.group("date"),
                name.upper(),
                hours,
                amount,
                match.group("pay_code").upper(),
            )
            if identity in seen:
                continue
            seen.add(identity)
            evidence = " ".join(match.group(0).split())
            rows.append(
                LaborLineItem(
                    source_type="pdf_invoice",
                    source_file=source_file,
                    source_page_or_row=page_ref,
                    employee_id="",
                    employee_name_raw=name,
                    hours=hours,
                    amount=amount,
                    currency=currency,
                    confidence=0.92,
                    evidence_text=f"opendataloader: {evidence}",
                    supplier=supplier,
                    period_start=period_start,
                    period_end=period_end,
                    warehouse_id=warehouse_id,
                )
            )
    return rows


def extract_invoice_total_from_opendataloader_markdown(markdown_path: Path) -> float:
    """Extract an invoice total from OpenDataLoader Markdown output."""
    text = markdown_path.read_text(encoding="utf-8")
    match = _INVOICE_AMOUNT_RE.search(text)
    if match:
        return round(parse_number(match.group(1)), 2)
    amounts = _ANY_AMOUNT_RE.findall(text)
    if not amounts:
        return 0.0
    return round(parse_number(amounts[-1]), 2)


def summarize_opendataloader_output(
    output_dir: Path,
    *,
    supplier: str = "",
    period_start: str = "",
    period_end: str = "",
    currency: str = "USD",
) -> Dict[str, Any]:
    """Summarize all OpenDataLoader JSON/Markdown files in an output directory."""
    rows: List[LaborLineItem] = []
    invoice_totals: List[Dict[str, Any]] = []
    for json_path in sorted(output_dir.glob("*.json")):
        file_rows = extract_labor_rows_from_opendataloader_json(
            json_path,
            supplier=supplier,
            period_start=period_start,
            period_end=period_end,
            currency=currency,
        )
        rows.extend(file_rows)
        markdown_path = json_path.with_suffix(".md")
        total_amount = extract_invoice_total_from_opendataloader_markdown(markdown_path) if markdown_path.exists() else 0.0
        source_file = file_rows[0].source_file if file_rows else json_path.with_suffix(".pdf").name
        invoice_totals.append(
            {
                "sourceFile": source_file,
                "warehouseId": file_rows[0].warehouse_id if file_rows else _warehouse_id_from_filename(source_file),
                "invoiceTotal": total_amount,
                "lineRowCount": len(file_rows),
                "lineAmountTotal": round(sum(row.amount for row in file_rows), 2),
            }
        )
    return {
        "rows": rows,
        "rowCount": len(rows),
        "lineAmountTotal": round(sum(row.amount for row in rows), 2),
        "invoiceTotals": invoice_totals,
        "invoiceTotalAmount": round(sum(item["invoiceTotal"] for item in invoice_totals), 2),
    }


def _iter_row_candidates(node: Any) -> Iterable[Tuple[str, str]]:
    if isinstance(node, dict):
        node_type = str(node.get("type") or "")
        if node_type == "paragraph" and node.get("content"):
            yield str(node["content"]), _page_ref(node)
        if node_type == "table row":
            cells = node.get("cells") or []
            cell_texts = [_compact_text(" ".join(_iter_content_text(cell))) for cell in cells]
            row_text = " ".join(text for text in cell_texts if text)
            if row_text:
                yield row_text, _page_ref(node, cells)
        for value in node.values():
            yield from _iter_row_candidates(value)
    elif isinstance(node, list):
        for value in node:
            yield from _iter_row_candidates(value)


def _iter_content_text(node: Any) -> Iterable[str]:
    if isinstance(node, dict):
        content = node.get("content")
        if content:
            yield str(content)
        for value in node.values():
            yield from _iter_content_text(value)
    elif isinstance(node, list):
        for value in node:
            yield from _iter_content_text(value)


def _page_ref(node: Dict[str, Any], cells: Optional[List[Dict[str, Any]]] = None) -> str:
    page = node.get("page number")
    if not page and cells:
        for cell in cells:
            page = cell.get("page number")
            if page:
                break
    return f"p{page}" if page else "opendataloader"


def _compact_text(value: str) -> str:
    return " ".join(str(value or "").replace("\u00a0", " ").split())


def _clean_employee_name(value: str) -> str:
    name = _compact_text(value)
    name = re.sub(r"\s+,", ",", name)
    name = re.sub(r"^(?:CA#?\d+\s+)?", "", name, flags=re.IGNORECASE)
    if name.lower() in {"date", "description", "totals", "total"}:
        return ""
    return name
