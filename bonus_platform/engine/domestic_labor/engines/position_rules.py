"""Shared position-name rules for domestic labor payroll engines."""
from typing import AbstractSet


SECURITY_INSPECTOR_POSITIONS = frozenset({
    "安检员",
    "民航初级安检员",
    "民航中级安检员",
    "民航高级安检员",
    "内部初级安检员",
    "内部中级安检员",
    "内部高级安检员",
})


def is_position_eligible(position: str, eligible_positions: AbstractSet[str]) -> bool:
    """Match exact configured positions and the confirmed security-inspector aliases."""
    normalized_position = str(position or "").strip()
    return normalized_position in eligible_positions or (
        "安检员" in eligible_positions
        and normalized_position in SECURITY_INSPECTOR_POSITIONS
    )
