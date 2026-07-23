from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Any

from .parsing import parse_number


WORKED_HOURS = "worked_hours"
UNKNOWN_ITEM = "unknown"

_ITEM_TYPE_ALIASES = {
    "hours": WORKED_HOURS,
    "hour": WORKED_HOURS,
    "labor": WORKED_HOURS,
    "labour": WORKED_HOURS,
    "time": WORKED_HOURS,
    "meal": "meal_allowance",
    "meal_allowance": "meal_allowance",
    "meal_ticket": "meal_allowance",
    "restaurant_ticket": "meal_allowance",
    "transport": "transport_allowance",
    "transport_allowance": "transport_allowance",
    "travel": "transport_allowance",
    "bonus": "bonus",
    "premium": "bonus",
    "allowance": "allowance",
    "expense": "expense",
    "other": "other",
    "unknown": UNKNOWN_ITEM,
}
_HOUR_UNITS = {"h", "hr", "hrs", "hour", "hours", "heure", "heures", "hora", "horas", "stunde", "stunden"}
_NON_TIME_UNITS = {
    "meal",
    "meals",
    "ticket",
    "tickets",
    "repas",
    "km",
    "kilometer",
    "kilometre",
    "day",
    "days",
    "jour",
    "jours",
    "item",
    "items",
    "each",
}
_WORKED_HOURS_SIGNAL = re.compile(
    r"\b(?:hours?|hrs?|heures?|horas?|stunden?|regular\s+time|normal(?:e|es)?\s+hours?)\b|工时|工作时长",
    re.IGNORECASE,
)
_MEAL_SIGNAL = re.compile(
    r"\b(?:ticket\s+restaurant|restaurant\s+ticket|meal(?:s|\s+allowance)?|lunch|repas|panier)\b|餐补|餐费",
    re.IGNORECASE,
)
_TRANSPORT_SIGNAL = re.compile(
    r"\b(?:transport|travel|mileage|kilometr(?:e|es|age)?|fahrkosten)\b|交通补贴|交通费",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class LineSemantics:
    item_type: str
    description: str
    quantity: float
    unit: str
    worked_hours: float


def interpret_line_semantics(
    *,
    item_type: Any = "",
    description: Any = "",
    quantity: Any = 0,
    unit: Any = "",
    hours: Any = 0,
    evidence_text: Any = "",
) -> LineSemantics:
    """Separate payable quantity from worked hours without supplier templates.

    Explicit model fields take priority. For legacy rows, only strong visible
    unit/description evidence converts the generic ``hours`` slot to quantity;
    otherwise hours remain unchanged for backward compatibility.
    """
    raw_hours = parse_number(hours)
    raw_quantity = parse_number(quantity)
    normalized_unit = _normalize_token(unit)
    normalized_type = _canonical_item_type(item_type)
    visible_text = " ".join(part for part in (str(description or ""), str(evidence_text or "")) if part).strip()
    normalized_text = _normalize_text(visible_text)

    if normalized_type == UNKNOWN_ITEM:
        if normalized_unit in _HOUR_UNITS or _WORKED_HOURS_SIGNAL.search(normalized_text):
            normalized_type = WORKED_HOURS
        elif normalized_unit in _NON_TIME_UNITS or _MEAL_SIGNAL.search(normalized_text):
            normalized_type = "meal_allowance" if _MEAL_SIGNAL.search(normalized_text) else "other"
        elif _TRANSPORT_SIGNAL.search(normalized_text) and normalized_unit in _NON_TIME_UNITS:
            normalized_type = "transport_allowance"

    is_worked_hours = normalized_type == WORKED_HOURS or (
        normalized_type == UNKNOWN_ITEM and normalized_unit not in _NON_TIME_UNITS
    )
    worked_hours = raw_hours if is_worked_hours else 0.0
    if raw_quantity == 0 and not is_worked_hours and raw_hours != 0:
        raw_quantity = raw_hours

    return LineSemantics(
        item_type=normalized_type,
        description=str(description or "").strip(),
        quantity=round(raw_quantity, 4),
        unit=str(unit or "").strip(),
        worked_hours=round(worked_hours, 4),
    )


def _canonical_item_type(value: Any) -> str:
    token = _normalize_token(value)
    return _ITEM_TYPE_ALIASES.get(token, UNKNOWN_ITEM)


def _normalize_token(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _normalize_text(str(value or ""))).strip("_")


def _normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFD", value)
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return text.lower()
