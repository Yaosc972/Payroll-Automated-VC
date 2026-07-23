from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

from .parsing import normalize_employee_name, parse_number
from .semantics import interpret_line_semantics


@dataclass
class LaborLineItem:
    source_type: str
    source_file: str
    source_page_or_row: str
    employee_id: str
    employee_name_raw: str
    hours: float
    amount: float
    currency: str = ""
    confidence: float = 1.0
    evidence_text: str = ""
    supplier: str = ""
    period_start: str = ""
    period_end: str = ""
    warehouse_id: str = ""
    item_type: str = "unknown"
    description: str = ""
    quantity: float = 0.0
    unit: str = ""
    amount_components: Dict[str, float] = field(default_factory=dict)
    amount_breakdown: Dict[str, float] = field(default_factory=dict)
    amount_context: Dict[str, str] = field(default_factory=dict)

    @property
    def employee_name_normalized(self) -> str:
        return normalize_employee_name(self.employee_name_raw)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["employee_name_normalized"] = self.employee_name_normalized
        return payload


@dataclass
class LaborComparisonRow:
    employee_key: str
    employee_name: str
    pdf_hours_total: float
    excel_hours_total: float
    hours_delta: float
    pdf_amount_total: float
    excel_amount_total: float
    amount_delta: float
    match_status: str
    risk_flags: List[str] = field(default_factory=list)
    source_refs: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "employeeKey": self.employee_key,
            "employeeName": self.employee_name,
            "pdfHoursTotal": self.pdf_hours_total,
            "excelHoursTotal": self.excel_hours_total,
            "hoursDelta": self.hours_delta,
            "pdfAmountTotal": self.pdf_amount_total,
            "excelAmountTotal": self.excel_amount_total,
            "amountDelta": self.amount_delta,
            "matchStatus": self.match_status,
            "riskFlags": self.risk_flags,
            "sourceRefs": "; ".join(self.source_refs),
        }


def line_items_from_dicts(rows: List[Dict[str, Any]]) -> List[LaborLineItem]:
    result: List[LaborLineItem] = []
    for row in rows:
        evidence_text = str(row.get("evidence_text") or row.get("evidenceText") or "")
        semantics = interpret_line_semantics(
            item_type=row.get("item_type") or row.get("itemType") or row.get("line_type") or row.get("lineType"),
            description=row.get("description") or row.get("item_description") or row.get("itemDescription"),
            quantity=row.get("quantity") or row.get("qty"),
            unit=row.get("unit") or row.get("quantity_unit") or row.get("quantityUnit"),
            hours=row.get("hours"),
            evidence_text=evidence_text,
        )
        result.append(
            LaborLineItem(
            source_type=str(row.get("source_type") or row.get("sourceType") or ""),
            source_file=str(row.get("source_file") or row.get("sourceFile") or ""),
            source_page_or_row=str(row.get("source_page_or_row") or row.get("sourcePageOrRow") or ""),
            employee_id=_employee_id(row.get("employee_id") or row.get("employeeId"), row.get("employee_name_raw") or row.get("employeeNameRaw") or row.get("employee_name") or row.get("employeeName") or ""),
            employee_name_raw=str(row.get("employee_name_raw") or row.get("employeeNameRaw") or row.get("employee_name") or row.get("employeeName") or ""),
            hours=semantics.worked_hours,
            amount=parse_number(row.get("amount")),
            currency=str(row.get("currency") or ""),
            confidence=_confidence(row.get("confidence")),
            evidence_text=evidence_text,
            supplier=str(row.get("supplier") or ""),
            period_start=str(row.get("period_start") or row.get("periodStart") or ""),
            period_end=str(row.get("period_end") or row.get("periodEnd") or ""),
            warehouse_id=str(row.get("warehouse_id") or row.get("warehouseId") or ""),
            item_type=semantics.item_type,
            description=semantics.description,
            quantity=semantics.quantity,
            unit=semantics.unit,
            amount_components={
                str(key): parse_number(value)
                for key, value in (row.get("amount_components") or row.get("amountComponents") or {}).items()
            },
            amount_breakdown={
                str(key): parse_number(value)
                for key, value in (row.get("amount_breakdown") or row.get("amountBreakdown") or {}).items()
            },
            amount_context={
                str(key): str(value or "").strip()
                for key, value in (row.get("amount_context") or row.get("amountContext") or {}).items()
                if str(value or "").strip()
            },
        )
        )
    return result


def _confidence(value: Any) -> float:
    if value is None:
        return 1.0
    if isinstance(value, str):
        label = value.strip().lower()
        if label in {"high", "高", "高置信度"}:
            return 0.95
        if label in {"medium", "med", "中", "中置信度"}:
            return 0.75
        if label in {"low", "低", "低置信度"}:
            return 0.5
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.7


def _employee_id(value: Any, employee_name: Any) -> str:
    employee_id = str(value or "").strip()
    if employee_id and employee_id == str(employee_name or "").strip():
        return ""
    return employee_id
