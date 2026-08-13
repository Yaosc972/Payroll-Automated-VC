"""夜班补贴通用核算引擎。"""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .base import BaseEngine, CalculationResult
from ..models import AuditExplanation
from ..night_shift_config import (
    BREAK_CATEGORY_EVENING,
    BREAK_CATEGORY_MORNING,
    find_active_jinjiang_exclusion,
    normalize_break_segments,
)


SUBJECT = "yeban_butie"
NIGHT_START_MINUTES = 22 * 60
NIGHT_END_MINUTES = 32 * 60
MAX_PLAUSIBLE_SHIFT_MINUTES = 16 * 60
THREE_AM_SHIFT_CODES = {"LB15"}


@dataclass(frozen=True)
class NightShiftDayResult:
    """单日夜班补贴结果及可审计中间值。"""

    status: str
    reason_code: str
    amount: Optional[float]
    shift_code: str = ""
    attendance_date: str = ""
    raw_start: Any = None
    raw_end: Any = None
    normalized_start_minutes: Optional[float] = None
    normalized_end_minutes: Optional[float] = None
    rounded_start_minutes: Optional[float] = None
    rounded_end_minutes: Optional[float] = None
    night_minutes: float = 0.0
    evening_break_minutes: float = 0.0
    morning_break_minutes: float = 0.0
    other_break_minutes: float = 0.0
    break_minutes: float = 0.0
    break_details: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        for field in ("raw_start", "raw_end"):
            value = payload[field]
            if isinstance(value, (datetime, date, time)):
                payload[field] = value.isoformat()
        return payload


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _time_minutes(value: Any) -> Optional[float]:
    if isinstance(value, datetime):
        return value.hour * 60 + value.minute + value.second / 60
    if isinstance(value, time):
        return value.hour * 60 + value.minute + value.second / 60
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if 0 <= number < 1:
            return number * 24 * 60
    value_text = _text(value)
    if not value_text:
        return None
    match = re.search(r"(?<!\d)(\d{1,2}):(\d{2})(?::(\d{2}))?", value_text)
    if not match:
        return None
    hour, minute, second = (int(part or 0) for part in match.groups())
    if hour >= 24 or minute >= 60 or second >= 60:
        return None
    return hour * 60 + minute + second / 60


def _normalize_actual(start_value: Any, end_value: Any) -> Optional[Tuple[float, float]]:
    start = _time_minutes(start_value)
    end = _time_minutes(end_value)
    if start is None or end is None:
        return None

    # 00:00—08:00 开始、白天结束的记录属于前一晚夜班窗口的后半段。
    if start < 8 * 60 and start < end < 22 * 60:
        start += 24 * 60
        end += 24 * 60
    elif end <= start:
        end += 24 * 60
    return start, end


def _parse_break_period(value: Any) -> Optional[Tuple[float, float]]:
    if isinstance(value, (tuple, list)) and len(value) == 2:
        start = _time_minutes(value[0])
        end = _time_minutes(value[1])
        if start is None or end is None:
            return None
    else:
        numbers = [int(number) for number in re.findall(r"\d+", _text(value))]
        if len(numbers) < 4:
            return None
        start_hour, start_minute, end_hour, end_minute = numbers[-4:]
        if start_minute >= 60 or end_minute >= 60:
            return None
        start = start_hour * 60 + start_minute
        end = end_hour * 60 + end_minute
    if end <= start:
        end += 24 * 60
    return start, end


def _align_break_to_attendance(
    period: Tuple[float, float],
    attendance_start: float,
    attendance_end: float,
) -> Tuple[float, float]:
    candidates = [
        (period[0] + offset, period[1] + offset)
        for offset in (-24 * 60, 0, 24 * 60, 48 * 60)
    ]
    return max(
        candidates,
        key=lambda item: max(0.0, min(attendance_end, item[1]) - max(attendance_start, item[0])),
    )


def _excel_round(value: float, digits: int = 2) -> float:
    quantizer = Decimal("1").scaleb(-digits)
    return float(Decimal(str(value)).quantize(quantizer, rounding=ROUND_HALF_UP))


def _attendance_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    value_text = _text(value)
    if not value_text:
        return None
    try:
        return datetime.fromisoformat(value_text[:10]).date()
    except ValueError:
        return None


def _has_scheduled_night_work(attendance: Mapping[str, Any]) -> Optional[bool]:
    """Return whether a missing-punch row was scheduled inside the night window."""
    work_status = _text(attendance.get("工作状态"))
    if work_status and work_status != "工作日":
        return False

    schedule_text = _text(attendance.get("班次时间段"))
    clock_parts = [
        (int(hour), int(minute))
        for hour, minute in re.findall(r"(\d{1,2}):(\d{2})", schedule_text)
        if int(minute) < 60
    ]
    if len(clock_parts) < 2:
        return None

    for index in range(0, len(clock_parts) - 1, 2):
        start_hour, start_minute = clock_parts[index]
        end_hour, end_minute = clock_parts[index + 1]
        start = start_hour * 60 + start_minute
        end = end_hour * 60 + end_minute
        if start < 8 * 60 and start < end < 22 * 60:
            start += 24 * 60
            end += 24 * 60
        elif end <= start:
            end += 24 * 60
        if min(end, NIGHT_END_MINUTES) > max(start, NIGHT_START_MINUTES):
            return True
    return False


def _direct_day_result(attendance: Mapping[str, Any], status: str, reason_code: str) -> NightShiftDayResult:
    return NightShiftDayResult(
        status=status,
        reason_code=reason_code,
        amount=0.0 if status == "excluded" else None,
        shift_code=_text(attendance.get("班次编号") or attendance.get("班次")),
        attendance_date=_text(attendance.get("出勤日期") or attendance.get("日期")),
        raw_start=attendance.get("上班一"),
        raw_end=attendance.get("下班一"),
    )


def _mark_calculated_pending(
    result: NightShiftDayResult,
    reason_code: str,
) -> NightShiftDayResult:
    """Keep a provisional amount while marking an unresolved business rule."""
    if result.status != "calculated":
        return result
    payload = result.to_dict()
    payload.update(status="calculated_pending", reason_code=reason_code)
    return NightShiftDayResult(**payload)


class YeBanBuTieEngine(BaseEngine):
    """仅实现已确认的普通夜班通用规则，未确认场景进入复核。"""

    def calculate_day(
        self,
        attendance: Mapping[str, Any],
        break_periods: Sequence[Any] = (),
    ) -> NightShiftDayResult:
        shift_code = _text(attendance.get("班次编号") or attendance.get("班次"))
        attendance_date = _text(attendance.get("出勤日期") or attendance.get("日期"))
        start_value = attendance.get("上班一")
        end_value = attendance.get("下班一")

        normalized = _normalize_actual(start_value, end_value)
        if normalized is None:
            if _has_scheduled_night_work(attendance) is False:
                return NightShiftDayResult(
                    status="excluded",
                    reason_code="no_scheduled_night_work",
                    amount=0.0,
                    shift_code=shift_code,
                    attendance_date=attendance_date,
                    raw_start=start_value,
                    raw_end=end_value,
                )
            return NightShiftDayResult(
                status="manual_review",
                reason_code="missing_punch",
                amount=None,
                shift_code=shift_code,
                attendance_date=attendance_date,
                raw_start=start_value,
                raw_end=end_value,
            )
        start, end = normalized
        provisional_reason = None
        if end - start <= 0 or end - start > MAX_PLAUSIBLE_SHIFT_MINUTES:
            provisional_reason = "implausible_duration"

        rounded_start = math.ceil(start / 30) * 30
        rounded_end = math.floor(end / 30) * 30
        if rounded_end <= rounded_start:
            return NightShiftDayResult(
                status="excluded",
                reason_code="no_effective_attendance",
                amount=0.0,
                shift_code=shift_code,
                attendance_date=attendance_date,
                raw_start=start_value,
                raw_end=end_value,
                normalized_start_minutes=start,
                normalized_end_minutes=end,
                rounded_start_minutes=rounded_start,
                rounded_end_minutes=rounded_end,
            )

        if shift_code in THREE_AM_SHIFT_CODES:
            rounded_duration = max(0.0, rounded_end - rounded_start)
            amount = min(25.0, rounded_duration / (8 * 60) * 25)
            return NightShiftDayResult(
                status="calculated_review",
                reason_code="three_am_shift_pending",
                amount=amount,
                shift_code=shift_code,
                attendance_date=attendance_date,
                raw_start=start_value,
                raw_end=end_value,
                normalized_start_minutes=start,
                normalized_end_minutes=end,
                rounded_start_minutes=rounded_start,
                rounded_end_minutes=rounded_end,
                night_minutes=min(rounded_duration, 8 * 60),
            )

        night_start = max(rounded_start, NIGHT_START_MINUTES)
        night_end = min(rounded_end, NIGHT_END_MINUTES)
        night_minutes = max(0.0, night_end - night_start)
        if night_minutes <= 0:
            return NightShiftDayResult(
                status="excluded",
                reason_code="no_night_overlap",
                amount=0.0,
                shift_code=shift_code,
                attendance_date=attendance_date,
                raw_start=start_value,
                raw_end=end_value,
                normalized_start_minutes=start,
                normalized_end_minutes=end,
                rounded_start_minutes=rounded_start,
                rounded_end_minutes=rounded_end,
            )

        break_minutes = 0.0
        evening_break_minutes = 0.0
        morning_break_minutes = 0.0
        other_break_minutes = 0.0
        break_details: List[Dict[str, Any]] = []
        for raw_segment in break_periods or ():
            try:
                segment = normalize_break_segments([raw_segment])[0]
            except (IndexError, ValueError):
                segment = {"period": "", "category": ""}
            raw_period = segment.get("period")
            category = segment.get("category")
            period = _parse_break_period(raw_period)
            if period is None:
                return NightShiftDayResult(
                    status="manual_review",
                    reason_code="invalid_break_period",
                    amount=None,
                    shift_code=shift_code,
                    attendance_date=attendance_date,
                    raw_start=start_value,
                    raw_end=end_value,
                    normalized_start_minutes=start,
                    normalized_end_minutes=end,
                    rounded_start_minutes=rounded_start,
                    rounded_end_minutes=rounded_end,
                    night_minutes=night_minutes,
                    evening_break_minutes=evening_break_minutes,
                    morning_break_minutes=morning_break_minutes,
                    other_break_minutes=other_break_minutes,
                    break_minutes=break_minutes,
                    break_details=break_details,
                )
            break_start, break_end = _align_break_to_attendance(
                period,
                rounded_start,
                rounded_end,
            )
            overlap = max(0.0, min(rounded_end, break_end) - max(rounded_start, break_start))
            duration = break_end - break_start
            deducted_minutes = 0.0
            if 0 < overlap < duration:
                deducted_minutes = overlap
                provisional_reason = provisional_reason or "partial_break_overlap"
            if overlap == duration:
                deducted_minutes = duration
            break_minutes += deducted_minutes
            if category == BREAK_CATEGORY_EVENING:
                evening_break_minutes += deducted_minutes
            elif category == BREAK_CATEGORY_MORNING:
                morning_break_minutes += deducted_minutes
            else:
                other_break_minutes += deducted_minutes
            break_details.append({
                "period": _text(raw_period),
                "category": category,
                "deducted_minutes": deducted_minutes,
            })

        effective_minutes = night_minutes - break_minutes
        if effective_minutes < 0:
            effective_minutes = 0.0
            provisional_reason = "negative_effective_duration"

        amount = min(25.0, effective_minutes / 60 * 3)
        return NightShiftDayResult(
            status="calculated_review" if provisional_reason else "calculated",
            reason_code=provisional_reason or "generic_rule",
            amount=amount,
            shift_code=shift_code,
            attendance_date=attendance_date,
            raw_start=start_value,
            raw_end=end_value,
            normalized_start_minutes=start,
            normalized_end_minutes=end,
            rounded_start_minutes=rounded_start,
            rounded_end_minutes=rounded_end,
            night_minutes=night_minutes,
            evening_break_minutes=evening_break_minutes,
            morning_break_minutes=morning_break_minutes,
            other_break_minutes=other_break_minutes,
            break_minutes=break_minutes,
            break_details=break_details,
        )

    def calculate(
        self,
        employee_data: Dict[str, Any],
        daily_attendance: Optional[List[Dict[str, Any]]] = None,
        shift_breaks: Optional[Mapping[str, Sequence[Any]]] = None,
        config: Optional[Mapping[str, Any]] = None,
    ) -> CalculationResult:
        employee_id = _text(employee_data.get("工号"))
        employee_name = _text(employee_data.get("姓名"))
        daily_attendance = daily_attendance or []
        shift_breaks = shift_breaks or {}
        config_mode = config is not None
        config = config or {}
        effective_shifts = config.get("effective_shift_breaks") or config.get("shift_breaks", [])
        configured_shifts = {
            _text(row.get("shift_code")): list(
                row.get("break_segments") or row.get("break_periods") or []
            )
            for row in effective_shifts or []
            if _text(row.get("shift_code"))
        }
        daily_results = []
        total = Decimal("0")
        status_counts: Dict[str, int] = {}

        for attendance in daily_attendance:
            shift_code = _text(attendance.get("班次编号") or attendance.get("班次"))
            result = None
            pending_reason = None
            break_periods = shift_breaks.get(shift_code, ())
            if config_mode:
                work_area = _text(attendance.get("工作地区") or employee_data.get("工作地区"))
                position = _text(attendance.get("岗位名称") or employee_data.get("岗位名称"))
                work_type = _text(attendance.get("计时") or attendance.get("计件/计时"))
                day_date = _attendance_date(attendance.get("出勤日期") or attendance.get("日期"))
                if day_date is None:
                    result = _direct_day_result(attendance, "manual_review", "invalid_attendance_date")
                elif "晋江" in work_area and ("计件" in position or "计件" in work_type):
                    result = _direct_day_result(attendance, "excluded", "jinjiang_piecework_excluded")
                elif "晋江" in work_area and "门禁" in position:
                    result = _direct_day_result(attendance, "excluded", "jinjiang_gatekeeper_excluded")
                elif "晋江" in work_area and find_active_jinjiang_exclusion(
                    config.get("jinjiang_exclusions", []), employee_id, day_date
                ):
                    result = _direct_day_result(attendance, "excluded", "jinjiang_special_list_excluded")
                elif "晋江" in work_area and not config.get("jinjiang_list_confirmed", False):
                    pending_reason = "jinjiang_special_list_unconfirmed"
                elif work_area not in {"东莞", "嘉善", "义乌", "晋江"}:
                    pending_reason = "work_area_scope_pending"
                if not shift_code or shift_code not in configured_shifts:
                    pending_reason = pending_reason or "shift_break_config_missing"
                    break_periods = ()
                else:
                    break_periods = configured_shifts[shift_code]
            if result is None:
                result = self.calculate_day(
                    attendance,
                    break_periods=break_periods,
                )
                if pending_reason:
                    result = _mark_calculated_pending(result, pending_reason)
            daily_results.append(result.to_dict())
            status_counts[result.status] = status_counts.get(result.status, 0) + 1
            if result.status in {"calculated", "calculated_review", "calculated_pending"} and result.amount is not None:
                total += Decimal(str(result.amount))

        amount = _excel_round(float(total), 2)
        manual_count = status_counts.get("manual_review", 0) + status_counts.get("calculated_review", 0)
        pending_count = status_counts.get("pending_rule", 0) + status_counts.get("calculated_pending", 0)
        excluded_count = status_counts.get("excluded", 0)
        review_calculated_count = (
            status_counts.get("calculated_review", 0)
            + status_counts.get("calculated_pending", 0)
        )
        unpriced_review_count = (
            status_counts.get("manual_review", 0)
            + status_counts.get("pending_rule", 0)
        )
        warnings = []
        if manual_count:
            warnings.append(f"{manual_count}条日考勤需人工复核")
        if pending_count:
            warnings.append(f"{pending_count}条日考勤待业务口径确认")

        reason_labels = {
            "invalid_attendance_date": "出勤日期缺失或格式错误",
            "missing_punch": "员工缺勤（考勤异常）",
            "implausible_duration": "上下班时长超出合理范围",
            "no_effective_attendance": "取整后无有效出勤时段",
            "no_night_overlap": "取整后未覆盖夜班窗口",
            "invalid_break_period": "班次休息时间格式错误",
            "partial_break_overlap": "实际出勤只覆盖部分休息时段",
            "negative_effective_duration": "扣除休息后有效时长为负数",
            "three_am_shift_pending": "凌晨3点班早退口径待确认",
            "work_area_scope_pending": "工作地区不在当前夜班补贴口径内",
            "jinjiang_special_list_unconfirmed": "当月晋江特殊名单尚未上传确认",
            "shift_break_config_missing": "班次休息表未维护该班次",
        }
        unresolved_reasons = sorted({
            row["reason_code"] for row in daily_results
            if row["status"] in {
                "manual_review", "pending_rule", "calculated_review", "calculated_pending"
            }
        })
        exceptions = [
            {
                "level": "warning",
                "subject": SUBJECT,
                "code": reason,
                "message": reason_labels.get(reason, reason),
                "suggested_action": "补充配置或核对原始考勤后重新核算",
            }
            for reason in unresolved_reasons
        ]

        details = {
            "calculated_days": status_counts.get("calculated", 0),
            "manual_review_days": manual_count,
            "pending_rule_days": pending_count,
            "excluded_days": excluded_count,
            "review_calculated_days": review_calculated_count,
            "unpriced_review_days": unpriced_review_count,
            "daily_results": daily_results,
            "exceptions": exceptions,
            "audit_explanation": AuditExplanation(
                subject=SUBJECT,
                amount=amount,
                rule_name="普通夜班通用规则",
                formula=(
                    "min((夜班窗口分钟-晚上休息分钟-早上休息分钟-其他休息分钟)/60*3, 25)，"
                    "月度汇总后保留2位"
                ),
                inputs={
                    "日考勤记录数": len(daily_attendance),
                    "工作地区": _text(employee_data.get("工作地区")),
                    "岗位名称": _text(employee_data.get("岗位名称")),
                    "配置月份": _text(config.get("month")),
                    "配置版本": config.get("revision", ""),
                },
                intermediate_values=status_counts,
                steps=[
                    "上班向后、下班向前取整到半小时",
                    "截取22:00至次日08:00夜班窗口",
                    "按班次配置分别扣除实际出勤覆盖的晚上休息、早上休息及其他休息时间",
                    "单日按3元/小时计算并封顶25元",
                    "有计算依据的未确认及异常记录先计入暂算金额并标记复核",
                    "完全缺少打卡等无计算依据记录不计金额，进入人工复核",
                ],
            ).to_dict(),
        }
        return CalculationResult(
            employee_id=employee_id,
            employee_name=employee_name,
            amount=amount,
            details=details,
            warnings=warnings,
        )
