"""Structured payroll result models for domestic labor calculations."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


@dataclass
class PayrollException:
    """Structured exception record for payroll review queues."""

    code: str
    level: str
    subject: str
    message: str
    suggested_action: str = ""
    employee_id: str = ""
    employee_name: str = ""
    impact_amount: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AuditExplanation:
    """Calculation trace used by payroll audit and employee drill-down UI."""

    subject: str
    amount: float
    rule_name: str
    formula: str = ""
    inputs: Dict[str, Any] = field(default_factory=dict)
    intermediate_values: Dict[str, Any] = field(default_factory=dict)
    steps: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PayrollSubjectResult:
    """Per-subject result wrapper for future API migration."""

    subject: str
    amount: float
    exceptions: List[PayrollException] = field(default_factory=list)
    audit_explanation: AuditExplanation | None = None

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "subject": self.subject,
            "amount": self.amount,
            "exceptions": [item.to_dict() for item in self.exceptions],
        }
        if self.audit_explanation is not None:
            payload["audit_explanation"] = self.audit_explanation.to_dict()
        return payload
