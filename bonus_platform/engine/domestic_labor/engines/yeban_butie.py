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
THREE_AM_SHIFT_CODES = {"LB15"}
THREE_AM_SHIFT_DEFAULT_PERIOD = (3 * 60, 11 * 60 + 30)
JIASHAN_YIWU_WORK_AREAS = {"嘉善", "义乌"}
JIASHAN_YIWU_EXCLUDED_POSITIONS = {"保洁", "HRBP专员", "数据专员"}
DONGGUAN_EXCLUDED_SHIFT_CODES = {"LB39"}


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
    window_results: List[Dict[str, Any]] = field(default_factory=list)

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

    # 凌晨开工且白天结束的记录对齐早晨窗口；超长早班由排班进一步判断。
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


def _parse_schedule_period(value: Any) -> Optional[Tuple[float, float]]:
    """Parse the first scheduled work period from an attendance row."""
    clock_parts = [
        (int(hour), int(minute))
        for hour, minute in re.findall(r"(\d{1,2}):(\d{2})", _text(value))
        if int(minute) < 60
    ]
    if len(clock_parts) < 2:
        return None
    start_hour, start_minute = clock_parts[0]
    end_hour, end_minute = clock_parts[1]
    start = start_hour * 60 + start_minute
    end = end_hour * 60 + end_minute
    if end <= start:
        end += 24 * 60
    return start, end


def _align_schedule_to_attendance(
    period: Tuple[float, float],
    attendance_start: float,
) -> Tuple[float, float]:
    """Align early-morning schedules with normalized post-midnight punches."""
    start, end = period
    if attendance_start >= 24 * 60 and end <= 24 * 60:
        start += 24 * 60
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
                status="excluded",
                reason_code="missing_punch",
                amount=0.0,
                shift_code=shift_code,
                attendance_date=attendance_date,
                raw_start=start_value,
                raw_end=end_value,
            )
        start, end = normalized
        schedule = _parse_schedule_period(attendance.get("班次时间段"))
        spans_both_windows = False
        if (
            shift_code not in THREE_AM_SHIFT_CODES
            and start < 8 * 60 and 23 * 60 <= end < 24 * 60
            and schedule is not None and schedule[0] < 8 * 60
            and max(math.ceil(start / 30) * 30, schedule[0]) < 8 * 60
        ):
            # Each window independently applies rounding, actual breaks and the
            # one-hour threshold. Splitting punches prevents recursive re-entry.
            morning = self.calculate_day(dict(attendance, 下班一="08:00"), break_periods)
            evening = self.calculate_day(dict(attendance, 上班一="22:00"), break_periods)
            parts = (morning, evening)
            if all(part.amount is not None for part in parts):
                combined = sum(part.amount for part in parts)
                # The morning and evening windows share one daily cap.
                payload = evening.to_dict()
                payload.update(
                    raw_start=start_value, raw_end=end_value,
                    normalized_start_minutes=start, normalized_end_minutes=end,
                    rounded_start_minutes=math.ceil(start / 30) * 30,
                    rounded_end_minutes=math.floor(end / 30) * 30,
                    amount=min(combined, 25.0),
                    window_results=[dict(part.to_dict(), window=window) for window, part in zip(("早晨", "晚间"), parts)],
                    status="calculated",
                    reason_code="generic_rule",
                    break_details=[
                        dict(detail, night_window=window)
                        for window, part in zip(("morning", "evening"), parts)
                        for detail in part.break_details
                    ],
                )
                for key in ("night_minutes", "break_minutes", "evening_break_minutes",
                            "morning_break_minutes", "other_break_minutes"):
                    payload[key] = sum(getattr(part, key) for part in parts)
                return NightShiftDayResult(**payload)
        if (
            start < 8 * 60 and end >= 22 * 60 and end < 24 * 60
            and schedule is not None and schedule[0] < 8 * 60
            and max(math.ceil(start / 30) * 30, schedule[0]) < 8 * 60
        ):
            if end < 23 * 60:
                # 当晚不足1小时，修复已确认早班的早晨窗口归属。
                start += 24 * 60
                end += 24 * 60
            else:
                # 分段计算缺少有效结果时保留原暂算并提示复核。
                spans_both_windows = True
        provisional_reason = None
        if spans_both_windows:
            provisional_reason = "multiple_night_windows_pending"

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
            scheduled_period = (
                _parse_break_period(attendance.get("班次时间段"))
                or THREE_AM_SHIFT_DEFAULT_PERIOD
            )
            scheduled_start, scheduled_end = _align_break_to_attendance(
                scheduled_period,
                rounded_start,
                rounded_end,
            )
            regular_start = max(rounded_start, scheduled_start)
            regular_end = min(rounded_end, scheduled_end)
            regular_minutes = max(0.0, regular_end - regular_start)
            if regular_minutes <= 0:
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

            late_minutes = max(0.0, rounded_start - scheduled_start)
            early_leave_minutes = max(0.0, scheduled_end - rounded_end)
            effective_minutes = max(
                0.0,
                8 * 60 - late_minutes - early_leave_minutes,
            )
            if effective_minutes <= 0:
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

            break_details: List[Dict[str, Any]] = []
            for raw_segment in break_periods or ():
                try:
                    segment = normalize_break_segments([raw_segment])[0]
                except (IndexError, ValueError):
                    segment = {"period": _text(raw_segment), "category": ""}
                break_details.append({
                    "period": _text(segment.get("period")),
                    "category": segment.get("category"),
                    "deducted_minutes": 0.0,
                })

            amount = min(25.0, effective_minutes / (8 * 60) * 25)
            return NightShiftDayResult(
                status="calculated_review" if provisional_reason else "calculated",
                reason_code=provisional_reason or "three_am_shift_rule",
                amount=amount,
                shift_code=shift_code,
                attendance_date=attendance_date,
                raw_start=start_value,
                raw_end=end_value,
                normalized_start_minutes=start,
                normalized_end_minutes=end,
                rounded_start_minutes=rounded_start,
                rounded_end_minutes=rounded_end,
                night_minutes=effective_minutes,
                break_details=break_details,
            )

        scheduled_period = _parse_schedule_period(attendance.get("班次时间段"))
        scheduled_start = rounded_start
        if scheduled_period is not None:
            scheduled_start, _ = _align_schedule_to_attendance(
                scheduled_period,
                rounded_start,
            )

        night_start = max(rounded_start, scheduled_start, NIGHT_START_MINUTES)
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
            window_break_start = max(break_start, NIGHT_START_MINUTES)
            window_break_end = min(break_end, NIGHT_END_MINUTES)
            duration = max(0.0, window_break_end - window_break_start)
            overlap = max(
                0.0,
                min(rounded_end, window_break_end) - max(rounded_start, window_break_start),
            )
            deducted_minutes = 0.0
            if 0 < overlap < duration:
                deducted_minutes = overlap
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

        # 普通夜班：扣休息后满1小时起算，余下不足30分钟舍去。
        payable_minutes = math.floor(effective_minutes / 30) * 30 if effective_minutes >= 60 else 0
        amount = min(25.0, payable_minutes / 60 * 3)
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
            _text(row.get("shift_code")): row
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
                elif (
                    work_area in JIASHAN_YIWU_WORK_AREAS
                    and position in JIASHAN_YIWU_EXCLUDED_POSITIONS
                ):
                    result = _direct_day_result(
                        attendance,
                        "excluded",
                        "jiashan_yiwu_position_excluded",
                    )
                elif work_area == "东莞" and shift_code in DONGGUAN_EXCLUDED_SHIFT_CODES:
                    result = _direct_day_result(attendance, "excluded", "dongguan_lb39_excluded")
                elif work_area == "东莞" and position == "保洁":
                    result = _direct_day_result(attendance, "excluded", "dongguan_cleaner_excluded")
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
                configured_shift = configured_shifts.get(shift_code)
                effective_start_date = _attendance_date(
                    configured_shift.get("effective_start_date") if configured_shift else None
                )
                if (
                    not configured_shift
                    or (effective_start_date is not None and day_date is not None and day_date < effective_start_date)
                ):
                    pending_reason = pending_reason or "shift_break_config_missing"
                    break_periods = ()
                else:
                    break_periods = list(
                        configured_shift.get("break_segments")
                        or configured_shift.get("break_periods")
                        or []
                    )
            if result is None:
                result = self.calculate_day(
                    attendance,
                    break_periods=break_periods,
                )
                if pending_reason:
                    result = _mark_calculated_pending(result, pending_reason)
            daily_payload = result.to_dict()
            daily_payload.update({
                "shift_category": _text(attendance.get("班次类别名称") or attendance.get("班次类别")),
                "shift_name": _text(attendance.get("班次名称")),
                "shift_time": _text(attendance.get("班次时间段") or attendance.get("班次时间点描述")),
                "work_area": _text(attendance.get("工作地区") or employee_data.get("工作地区")),
            })
            daily_results.append(daily_payload)
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
            "missing_punch": "打卡不完整，当日不计补贴",
            "implausible_duration": "上下班时长超出合理范围",
            "multiple_night_windows_pending": "同日早晚窗口分段计算缺少有效结果，需复核考勤",
            "no_effective_attendance": "取整后无有效出勤时段",
            "no_night_overlap": "取整后未覆盖夜班窗口",
            "invalid_break_period": "班次休息时间格式错误",
            "partial_break_overlap": "实际出勤只覆盖部分休息时段",
            "negative_effective_duration": "扣除休息后有效时长为负数",
            "work_area_scope_pending": "工作地区不在当前夜班补贴口径内",
            "jinjiang_special_list_unconfirmed": "当月晋江特殊名单尚未上传确认",
            "jiashan_yiwu_position_excluded": "嘉善/义乌固定排除岗位不享有夜班补贴",
            "dongguan_lb39_excluded": "东莞LB39保洁班次不享有夜班补贴",
            "dongguan_cleaner_excluded": "东莞保洁不论班次均不享有夜班补贴",
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
                rule_name="夜班补贴地区资格及通用计算规则",
                formula=(
                    "命中嘉善/义乌固定排除岗位或东莞LB39班次时为0元；东莞保洁不论班次均为0元；其他记录按"
                    "扣休息后的有效夜班分钟满60分钟起算，不足60分钟为0元；满60分钟后按"
                    "min(floor(有效夜班分钟/30)*1.5, 25)计算；LB15按"
                    "max(8小时-迟到折算-早退折算,0)/8小时*25元计算；月度汇总后保留2位"
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
                    "先应用嘉善/义乌固定岗位、东莞LB39及晋江固定资格排除规则",
                    "上班向后、下班向前取整到半小时",
                    "普通班次从排班开始时间与取整后上班时间的较晚值起算",
                    "截取22:00至次日08:00夜班窗口；排班开始前不计发",
                    "按班次配置分别扣除与实际出勤及夜班窗口都重叠的休息时间",
                    "扣休息后不足1小时不计发；达到1小时后按完整30分钟计发，不足30分钟舍去，单日封顶25元",
                    "LB15以8小时正班为基准扣减取整后的迟到、早退，满8小时发25元，不足8小时折算",
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


def find_missing_payable_shifts(monthly_rows, daily_by_employee, config):
    """Preflight only: expose missing shift inputs, never provisional amounts."""
    shifts = {str(row.get("shift_code", "")): row for row in config.get("shift_breaks", [])}
    blockers = []
    engine = YeBanBuTieEngine()
    for employee in monthly_rows:
        employee_id = str(employee.get("工号", ""))
        days = daily_by_employee.get(employee_id, [])
        checked = engine.calculate(employee, days, config=config).details["daily_results"]
        missing = []
        for day in checked:
            # Missing punches, invalid dates and explicitly excluded records do
            # not need a rest configuration to determine their outcome.
            if day["status"] not in {"calculated", "calculated_review", "calculated_pending"} or not day.get("amount"):
                continue
            shift = shifts.get(day.get("shift_code", ""))
            date_value = _attendance_date(day.get("attendance_date"))
            effective = _attendance_date(shift.get("effective_start_date")) if shift else None
            if shift is not None and (effective is None or date_value >= effective):
                continue
            missing.append({key: day.get(key) for key in (
                "shift_code", "shift_category", "shift_name", "shift_time", "work_area", "attendance_date"
            )} | {"reason_code": "shift_break_config_missing"})
        if missing:
            blockers.append({"employee_id": employee_id, "employee_name": employee.get("姓名", ""),
                             "subject_details": {"yeban_butie": {"details": {"daily_results": missing}}}})
    return blockers
