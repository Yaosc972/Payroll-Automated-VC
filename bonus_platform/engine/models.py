from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from openpyxl.utils.datetime import from_excel


def as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def as_number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def as_date(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)) and value > 1000:
        try:
            return from_excel(value)
        except (TypeError, ValueError):
            return None
    return None


def yyyymm(date_value: Any) -> Optional[int]:
    normalized = as_date(date_value)
    if normalized:
        return normalized.year * 100 + normalized.month
    return None


def add_months(date_value: Any, months: int) -> Optional[datetime]:
    normalized = as_date(date_value)
    if not normalized:
        return None
    month = normalized.month - 1 + months
    year = normalized.year + month // 12
    month = month % 12 + 1
    month_days = [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    day = min(normalized.day, month_days[month - 1])
    return datetime(year, month, day)


@dataclass
class ImportRow:
    source_row: int
    values: Dict[str, Any]

    def get(self, field: str, default: Any = None) -> Any:
        return self.values.get(field, default)

    def text(self, field: str) -> str:
        return as_text(self.get(field))


@dataclass
class RecruitmentDetail:
    row_no: int
    name: str
    employee_no: str
    status: str
    location: str
    grade: str
    category: str
    channel: str
    recruiter_id: str
    recruiter_name: str
    recruiter_status: str
    recruiter_last_work_date: Any
    assistant_id: str
    assistant_name: str
    assistant_status: str
    assistant_last_work_date: Any
    start_date: Any
    onboard_date: Any
    probation_date: Any
    label: str
    standard_cycle_days: float
    actual_cycle_days: Optional[float]
    cycle_diff_days: Optional[float]
    channel_ratio: float
    standard_bonus: float
    adjusted_total_bonus: float
    recruiter_bonus_base: float
    recruiter_1m_bonus: float
    recruiter_1m_period: Optional[int]
    recruiter_3m_bonus: float
    recruiter_3m_period: Optional[int]
    recruiter_6m_bonus: float
    recruiter_6m_period: Optional[int]
    recruiter_probation_bonus: float
    recruiter_probation_period: Any
    assistant_bonus_base: float
    assistant_1m_bonus: float
    assistant_1m_period: Any
    assistant_3m_bonus: float
    assistant_3m_period: Any
    assistant_6m_bonus: float
    assistant_6m_period: Any
    assistant_probation_bonus: float
    assistant_probation_period: Any
    currency: str
    referrer_name: str
    referrer_id: str
    referrer_status: str
    referrer_is_manager: str
    referral_rule_scope: str
    referral_standard_bonus: float
    referral_1m_bonus: float
    referral_1m_period: Any
    referral_3m_bonus: float
    referral_3m_period: Any
    referral_6m_bonus: float
    referral_6m_period: Any
    referral_probation_bonus: float
    referral_probation_period: Any
    exceptions: List[str] = field(default_factory=list)

    @property
    def monthly_recruitment_amounts(self) -> List[tuple[int, float]]:
        pairs = [
            (self.recruiter_1m_period, self.recruiter_1m_bonus),
            (self.recruiter_3m_period, self.recruiter_3m_bonus),
            (self.recruiter_6m_period, self.recruiter_6m_bonus),
            (self.recruiter_probation_period, self.recruiter_probation_bonus),
            (self.assistant_1m_period, self.assistant_1m_bonus),
            (self.assistant_3m_period, self.assistant_3m_bonus),
            (self.assistant_6m_period, self.assistant_6m_bonus),
            (self.assistant_probation_period, self.assistant_probation_bonus),
        ]
        return [(int(period), amount) for period, amount in pairs if isinstance(period, int) and amount]

    @property
    def monthly_referral_amounts(self) -> List[tuple[int, float]]:
        pairs = [
            (self.referral_1m_period, self.referral_1m_bonus),
            (self.referral_3m_period, self.referral_3m_bonus),
            (self.referral_6m_period, self.referral_6m_bonus),
            (self.referral_probation_period, self.referral_probation_bonus),
        ]
        return [(int(period), amount) for period, amount in pairs if isinstance(period, int) and amount]


@dataclass
class CalculationResult:
    month: int
    details: List[RecruitmentDetail]
    recruitment_summary: List[Dict[str, Any]]
    referral_summary: List[Dict[str, Any]]
    pending_confirmations: List[Dict[str, Any]]
    exceptions: List[Dict[str, Any]]
