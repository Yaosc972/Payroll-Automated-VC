from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List

from .models import LaborLineItem


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
    return []
