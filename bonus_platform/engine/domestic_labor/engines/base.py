"""Base calculation engine."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from datetime import date


@dataclass
class CalculationResult:
    """Calculation result container."""
    employee_id: str
    employee_name: str
    amount: float
    details: Dict[str, Any]
    warnings: List[str]


def safe_float(val, default=0.0) -> float:
    """Convert value to float safely, handling strings, None, etc."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def safe_int(val, default=0) -> int:
    """Convert value to int safely."""
    if val is None:
        return default
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default


class BaseEngine(ABC):
    """Base class for all calculation engines."""

    @abstractmethod
    def calculate(self, employee_data: Dict[str, Any]) -> CalculationResult:
        """Calculate for a single employee."""
        pass

    def calculate_batch(self, employees: List[Dict[str, Any]]) -> List[CalculationResult]:
        """Calculate for multiple employees."""
        return [self.calculate(emp) for emp in employees]

    @staticmethod
    def get_month_range(attendance_month: str) -> tuple[date, date, int]:
        """Get month start, end date and days in month.

        Args:
            attendance_month: Format YYYYMM (e.g., "202603")

        Returns:
            Tuple of (month_start, month_end, days_in_month)
        """
        import calendar
        year = int(attendance_month[:4])
        month = int(attendance_month[4:])
        month_start = date(year, month, 1)
        days_in_month = calendar.monthrange(year, month)[1]
        month_end = date(year, month, days_in_month)
        return month_start, month_end, days_in_month
