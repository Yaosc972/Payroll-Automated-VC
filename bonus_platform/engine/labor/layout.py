from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List

from .models import LaborLineItem
from .parsing import parse_number


@dataclass
class InvoiceLayoutPlan:
    layout_type: str
    recommended_parser: str
    confidence: float
    employee_name_pattern: str = ""
    hours_columns: List[str] = field(default_factory=list)
    amount_column: str = ""
    total_label: str = ""
    warehouse_source: str = ""
    evidence: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "layoutType": self.layout_type,
            "recommendedParser": self.recommended_parser,
            "confidence": self.confidence,
            "employeeNamePattern": self.employee_name_pattern,
            "hoursColumns": self.hours_columns,
            "amountColumn": self.amount_column,
            "totalLabel": self.total_label,
            "warehouseSource": self.warehouse_source,
            "evidence": self.evidence,
        }


def analyze_invoice_layout(pages: List[Dict[str, Any]]) -> InvoiceLayoutPlan:
    """Analyze invoice text and choose a parser plan.

    This is the deterministic front of a future AI layout analyzer: callers use
    the same plan object whether the plan came from rules or from AI.
    """
    text = "\n".join(page.get("text") or "" for page in pages)
    compact_lines = [" ".join(line.split()) for line in text.splitlines()]
    compact_lines = [line for line in compact_lines if line]

    simple_header = next(
        (
            line
            for line in compact_lines
            if re.search(r"\bNo\.\s+Name\b", line, re.IGNORECASE)
            and re.search(r"Reg\.\s*Hours|Reg\s+Hours", line, re.IGNORECASE)
            and re.search(r"O\.?T\.?\s*Hours|OT\s+Hours", line, re.IGNORECASE)
            and re.search(r"\bTotal\b", line, re.IGNORECASE)
        ),
        "",
    )
    simple_rows = [
        line
        for line in compact_lines
        if re.match(r"^\d+\s+[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ\s.'-]*?\s+\d.*\$\d[\d,]*\.\d{2}$", line)
    ]
    if simple_header and simple_rows:
        total_label = "GRAND TOTAL" if re.search(r"\bGRAND\s+TOTAL\b", text, re.IGNORECASE) else "TOTAL HOURS"
        return InvoiceLayoutPlan(
            layout_type="simple_numbered_labor_table",
            recommended_parser="simple_invoice_table",
            confidence=0.9 if len(simple_rows) >= 2 else 0.8,
            employee_name_pattern="after row number before first hour number",
            hours_columns=["Reg. Hours", "O.T Hours"],
            amount_column="Total",
            total_label=total_label,
            warehouse_source="not_visible",
            evidence=[simple_header, *simple_rows[:3]],
        )

    return InvoiceLayoutPlan(
        layout_type="unknown",
        recommended_parser="ai_assisted",
        confidence=0.0,
        evidence=compact_lines[:3],
    )


def layout_plan_from_dict(data: Dict[str, Any]) -> InvoiceLayoutPlan:
    layout_type = str(data.get("layout_type") or data.get("layoutType") or "unknown")
    recommended_parser = str(data.get("recommended_parser") or data.get("recommendedParser") or "ai_assisted")
    try:
        confidence = float(data.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    hours_columns = data.get("hours_columns") or data.get("hoursColumns") or []
    if not isinstance(hours_columns, list):
        hours_columns = [str(hours_columns)]
    evidence = data.get("evidence") or []
    if not isinstance(evidence, list):
        evidence = [str(evidence)]
    return InvoiceLayoutPlan(
        layout_type=layout_type,
        recommended_parser=recommended_parser,
        confidence=max(0.0, min(confidence, 1.0)),
        employee_name_pattern=str(data.get("employee_name_pattern") or data.get("employeeNamePattern") or ""),
        hours_columns=[str(value) for value in hours_columns],
        amount_column=str(data.get("amount_column") or data.get("amountColumn") or ""),
        total_label=str(data.get("total_label") or data.get("totalLabel") or ""),
        warehouse_source=str(data.get("warehouse_source") or data.get("warehouseSource") or ""),
        evidence=[str(value) for value in evidence],
    )


def extract_rows_from_layout_plan(
    pages: List[Dict[str, Any]],
    plan: InvoiceLayoutPlan,
    *,
    supplier: str,
    period_start: str,
    period_end: str,
    currency: str,
) -> List[LaborLineItem]:
    if plan.recommended_parser == "simple_invoice_table":
        from .extract import _extract_simple_invoice_rows

        rows: List[LaborLineItem] = []
        for page in pages:
            rows.extend(
                _extract_simple_invoice_rows(
                    page,
                    supplier=supplier,
                    period_start=period_start,
                    period_end=period_end,
                    currency=currency,
                )
            )
        return rows
    if plan.recommended_parser == "line_item_text_table":
        return _extract_line_item_text_table_rows(
            pages,
            supplier=supplier,
            period_start=period_start,
            period_end=period_end,
            currency=currency,
        )
    return []


def _extract_line_item_text_table_rows(
    pages: List[Dict[str, Any]],
    *,
    supplier: str,
    period_start: str,
    period_end: str,
    currency: str,
) -> List[LaborLineItem]:
    """通用单行员工明细解析器。

    AI 版式识别只负责判断“这一版是否是一行一个员工”的结构；这里仍用确定性规则取值，
    避免把 AI 的自由文本判断直接写进金额结果。
    """
    rows: List[LaborLineItem] = []
    for page in pages:
        warehouse_id = _warehouse_id_from_text_local(page.get("text") or "")
        for raw_line in (page.get("text") or "").splitlines():
            compact = " ".join(raw_line.split())
            if not _looks_like_line_item(compact):
                continue
            item = _line_item_from_text_line(
                compact,
                page,
                warehouse_id=warehouse_id,
                supplier=supplier,
                period_start=period_start,
                period_end=period_end,
                currency=currency,
            )
            if item:
                rows.append(item)
    return rows


def _looks_like_line_item(line: str) -> bool:
    if not line:
        return False
    if re.search(r"\b(?:total|subtotal|summary|invoice|balance|amount due)\b", line, re.IGNORECASE):
        return False
    if not re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]{2,}", line):
        return False
    return bool(re.search(r"\$?\s*-?[\d,]+\.\d{2}\$?", line))


def _line_item_from_text_line(
    line: str,
    page: Dict[str, Any],
    *,
    warehouse_id: str,
    supplier: str,
    period_start: str,
    period_end: str,
    currency: str,
) -> LaborLineItem | None:
    amount_matches = list(re.finditer(r"-?\$\s*[\d,]+\.\d{2}|-?[\d,]+\.\d{2}\$", line))
    if not amount_matches:
        amount_matches = list(re.finditer(r"-?[\d,]+\.\d{2}", line))
    if not amount_matches:
        return None
    amount = parse_number(amount_matches[-1].group(0))
    if not amount:
        return None

    name_area = line[: amount_matches[0].start()]
    name = _extract_employee_name_from_line_prefix(name_area)
    if not name:
        return None

    hours = _extract_hours_from_line(line, amount_matches)
    if hours <= 0:
        return None
    return LaborLineItem(
        source_type="pdf_invoice",
        source_file=str(page.get("source_file") or ""),
        source_page_or_row=f"p{page.get('page')}",
        employee_id=_extract_employee_id(line),
        employee_name_raw=name,
        hours=round(hours, 2),
        amount=round(amount, 2),
        currency=currency,
        confidence=0.82,
        evidence_text=line,
        supplier=supplier,
        period_start=period_start,
        period_end=period_end,
        warehouse_id=warehouse_id,
    )


def _extract_employee_name_from_line_prefix(prefix: str) -> str:
    cleaned = re.sub(r"^\s*\d+\s+", " ", prefix)
    cleaned = re.sub(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", " ", cleaned)
    cleaned = re.sub(r"\b(?:WUS)?\d{3,8}\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.split(r"\b(?:reg|regular|ot|overtime|dt|doubletime|hours?|hrs?)\b", cleaned, flags=re.IGNORECASE)[0]
    cleaned = re.split(r"\s+\d+(?:\.\d+)?\b", cleaned, maxsplit=1)[0]
    cleaned = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ,\s.'-]", " ", cleaned)
    cleaned = " ".join(cleaned.split()).strip(" ,.-'")
    tokens = [token for token in cleaned.split() if len(token.strip(".,'")) > 1]
    if len(tokens) < 2:
        return ""
    return cleaned


def _extract_hours_from_line(line: str, amount_matches: List[re.Match[str]]) -> float:
    prefix = line[: amount_matches[0].start()]
    prefix = re.sub(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", " ", prefix)
    prefix = re.sub(r"\b(?:WUS)?\d{3,8}\b", " ", prefix, flags=re.IGNORECASE)
    numeric_values = [
        parse_number(match.group(0))
        for match in re.finditer(r"(?<![A-Za-z])\d{1,3}(?:\.\d{1,3})?(?![A-Za-z])", prefix)
    ]
    hours = [value for value in numeric_values if 0 < value <= 80]
    if not hours:
        return 0.0
    # 单行表常见为 regular + OT 多列，排除行号/日期后把合理工时相加。
    if len(hours) >= 2 and hours[0].is_integer() and int(hours[0]) <= 200 and re.match(r"^\s*\d+\s+", line):
        hours = hours[1:]
    return sum(hours[:3])


def _extract_employee_id(line: str) -> str:
    match = re.search(r"\b(WUS\d{3,8}|\d{5,8})\b", line, re.IGNORECASE)
    return match.group(1) if match else ""


def _warehouse_id_from_text_local(text: str) -> str:
    patterns = [
        r"\(CA\)\s*LA\s*#\s*(\d+)",
        r"CA\s*#\s*(\d+)",
        r"DEPT\s*:?\s*(\d+)",
        r"WAREHOUSE\s+LOC\.?\s*#\s*(\d+)",
        r"\bWH(?:\s|[:#-])+\s*(\d+)",
        r"\bLOC(?:ATION)?\.?(?:\s|[:#-])+\s*(\d+)",
        r"(\d{1,3})\s*号仓",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    return ""
