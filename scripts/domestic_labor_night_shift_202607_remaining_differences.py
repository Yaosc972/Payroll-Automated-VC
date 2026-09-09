"""导出确认平台规则及线下公式问题后，2026年7月夜班补贴剩余逐日差异。"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bonus_platform.engine.domestic_labor.engines.yeban_butie import (
    NIGHT_END_MINUTES,
    NIGHT_START_MINUTES,
    _has_scheduled_night_work,
)
from bonus_platform.engine.domestic_labor.night_shift_config import (
    load_night_shift_config,
)
from scripts.domestic_labor_night_shift_202607_validation import (
    DEFAULT_EAST,
    DEFAULT_SOUTH,
    TOLERANCE,
    _calculate,
    _day,
    _money,
    _number,
    _read_region,
    _text,
)


DEFAULT_OUTPUT = Path("/tmp/night_shift_202607_remaining_differences.json")


REASON_LABELS = {
    "generic_rule": "通用规则已计算",
    "missing_punch": "缺少有效打卡",
    "implausible_duration": "打卡跨度超过16小时",
    "no_effective_attendance": "取整后无有效出勤",
    "no_night_overlap": "取整后未覆盖夜班窗口",
    "partial_break_overlap": "只覆盖部分休息段",
    "three_am_shift_rule": "凌晨3点班正班折算公式",
    "jiashan_yiwu_position_excluded": "嘉善/义乌固定岗位排除",
    "dongguan_lb39_excluded": "东莞LB39固定排除",
    "shift_break_config_missing": "班次休息资料缺失",
}


CONFIRMED_OFFLINE_FORMULA_SHIFTS = {"HD050", "HD059"}
CONFIRMED_OFFLINE_FORMULA_ISSUE = "线下公式下拉问题（无需平台处理）"
CONFIRMED_NO_MORNING_BREAK_SHIFTS = {"HD003", "HD012", "HD014", "HD027"}
CONFIRMED_ROUNDED_BREAK_SHIFT_CODES = {
    "HD007", "HD010", "HD016", "HD017", "HD018", "HD021", "HD059", "LB12", "LB23",
}


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) else value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _precision(value: float) -> float:
    """保留日金额原始精度，最终汇总时再保留两位。"""
    return round(float(value) + 1e-10, 6)


def _attendance_index(grouped: Mapping[str, Sequence[Mapping[str, Any]]]):
    return {
        (_text(row.get("工号")), _day(row.get("出勤日期"))): row
        for rows in grouped.values()
        for row in rows
    }


def _schedule_span(schedule: str):
    points = [(int(h), int(m)) for h, m in re.findall(r"(\d{1,2}):(\d{2})", schedule)]
    if len(points) < 2 or any(m >= 60 for _, m in points[:2]):
        return None
    start = points[0][0] * 60 + points[0][1]
    end = points[1][0] * 60 + points[1][1]
    if start < 8 * 60 and start < end < 22 * 60:
        start += 24 * 60
        end += 24 * 60
    elif end <= start:
        end += 24 * 60
    return start, end


def _out_of_schedule_night_minutes(result: Mapping[str, Any], schedule: str) -> float:
    span = _schedule_span(schedule)
    actual_start = result.get("rounded_start_minutes")
    actual_end = result.get("rounded_end_minutes")
    if span is None or actual_start is None or actual_end is None:
        return 0.0
    schedule_start, schedule_end = span
    actual_night_start = max(float(actual_start), NIGHT_START_MINUTES)
    actual_night_end = min(float(actual_end), NIGHT_END_MINUTES)
    if actual_night_end <= actual_night_start:
        return 0.0
    scheduled_overlap = max(
        0.0,
        min(actual_night_end, schedule_end) - max(actual_night_start, schedule_start),
    )
    return max(0.0, actual_night_end - actual_night_start - scheduled_overlap)


def _classify(
    source: Mapping[str, Any],
    attendance: Mapping[str, Any],
    result: Mapping[str, Any],
    difference: float,
    out_of_schedule_night_minutes: float,
    *,
    ignore_break_difference: bool = False,
) -> str:
    reason = _text(result.get("reason_code"))
    line_amount = _number(source.get("amount"))
    platform_amount = _number(result.get("amount"))
    line_break = _number(source.get("line_evening_break_hours")) + _number(
        source.get("line_morning_break_hours")
    )
    platform_break = _number(result.get("break_minutes")) / 60
    scheduled_night = _has_scheduled_night_work(attendance)

    if reason == "shift_break_config_missing" and _text(source.get("shift_code")) != "LB68":
        return "缺班次休息资料"
    if reason == "missing_punch":
        return "缺少有效打卡"
    if reason == "implausible_duration":
        return "异常超长打卡"
    if _text(source.get("work_status")) != "工作日":
        return "休息日计发口径不一致"
    if reason == "partial_break_overlap":
        return "实际只覆盖部分休息段"
    if out_of_schedule_night_minutes > TOLERANCE and difference > TOLERANCE:
        return "平台计入排班外夜间打卡"
    if scheduled_night is False and platform_amount > TOLERANCE and line_amount <= TOLERANCE:
        return "非夜班排班但平台按实际打卡计发"
    if not ignore_break_difference and line_break - platform_break > TOLERANCE:
        return "线下休息字段高于平台"
    if not ignore_break_difference and platform_break - line_break > TOLERANCE:
        return "平台休息字段高于线下"
    if platform_amount > TOLERANCE and line_amount <= TOLERANCE:
        return "线下不计发、平台计发"
    if platform_amount <= TOLERANCE and line_amount > TOLERANCE:
        return "平台不计发、线下计发"
    return "起止取整或其他公式差异"


def _break_difference_fully_explains_amount(detail: Mapping[str, Any]) -> bool:
    """判断按平台休息时长纠正线下金额后，是否与平台金额一致。"""
    break_delta = (
        _number(detail.get("line_break_hours"))
        - _number(detail.get("platform_break_hours"))
    ) * 3
    corrected_line_amount = min(
        25.0,
        max(0.0, _number(detail.get("line_yuan")) + break_delta),
    )
    return abs(_number(detail.get("platform_yuan")) - corrected_line_amount) <= TOLERANCE


def _summaries(details):
    by_region = defaultdict(lambda: Counter())
    by_issue = defaultdict(lambda: Counter())
    by_shift = defaultdict(lambda: Counter())
    issue_employees = defaultdict(set)
    shift_employees = defaultdict(set)
    shift_metadata = {}
    shift_issues = defaultdict(Counter)
    for row in details:
        difference = row["difference_yuan"]
        for key, target in (
            (row["region"], by_region[row["region"]]),
            (row["issue"], by_issue[row["issue"]]),
            (f'{row["region"]}:{row["shift_code"]}', by_shift[f'{row["region"]}:{row["shift_code"]}']),
        ):
            target["mismatch_rows"] += 1
            target["platform_yuan"] += row["platform_yuan"]
            target["line_yuan"] += row["line_yuan"]
            target["absolute_yuan"] += abs(difference)
        issue_employees[row["issue"]].add(row["employee_id"])
        shift_key = f'{row["region"]}:{row["shift_code"]}'
        shift_employees[shift_key].add(row["employee_id"])
        shift_metadata.setdefault(shift_key, {
            "region": row["region"],
            "shift_code": row["shift_code"],
            "shift_name": row["shift_name"],
            "shift_schedule": row["shift_schedule"],
            "configured_breaks": row["configured_breaks"],
        })
        shift_issues[shift_key][row["issue"]] += 1

    def rows(mapping, employee_sets=None):
        output = []
        for key, values in mapping.items():
            record = {
                "key": key,
                "mismatch_rows": values["mismatch_rows"],
                "platform_yuan": _money(values["platform_yuan"]),
                "line_yuan": _money(values["line_yuan"]),
                "net_yuan": _money(values["platform_yuan"] - values["line_yuan"]),
                "absolute_yuan": _money(values["absolute_yuan"]),
            }
            if employee_sets is not None:
                record["employees"] = len(employee_sets[key])
            output.append(record)
        output.sort(key=lambda row: (-row["absolute_yuan"], -row["mismatch_rows"], row["key"]))
        return output

    shift_rows = rows(by_shift, shift_employees)
    for row in shift_rows:
        row.update(shift_metadata[row["key"]])
        row["main_issue"] = shift_issues[row["key"]].most_common(1)[0][0]

    return {
        "by_region": rows(by_region),
        "by_issue": rows(by_issue, issue_employees),
        "by_shift": shift_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--south", type=Path, default=DEFAULT_SOUTH)
    parser.add_argument("--east", type=Path, default=DEFAULT_EAST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    config = load_night_shift_config("202607", required=False)
    master = {
        _text(row.get("shift_code")): row
        for row in config.get("effective_shift_breaks", [])
    }
    details = []
    region_counts = {}
    missing_shift_stats = defaultdict(Counter)
    missing_shift_employees = defaultdict(set)
    missing_shift_metadata = {}
    for label, display, path in (
        ("south", "华南", args.south),
        ("east", "华东", args.east),
    ):
        people, grouped, offline, duplicate_keys = _read_region(label, path)
        platform, _, _ = _calculate(people, grouped, config)
        attendance_by_key = _attendance_index(grouped)
        region_counts[display] = {
            "source_rows": len(offline),
            "duplicate_keys": duplicate_keys,
            "platform_rows": len(platform),
        }
        for key, source in offline.items():
            shift_code = _text(source.get("shift_code"))
            if shift_code and shift_code not in master and shift_code != "LB68":
                missing_key = f"{display}:{shift_code}"
                result = platform.get(key, {})
                stats = missing_shift_stats[missing_key]
                stats["attendance_rows"] += 1
                stats["line_paid_rows"] += _number(source.get("amount")) > TOLERANCE
                stats["line_yuan"] += _number(source.get("amount"))
                stats["platform_yuan"] += _number(result.get("amount"))
                stats["pending_rows"] += _text(result.get("reason_code")) == "shift_break_config_missing"
                stats["mismatch_rows"] += abs(
                    _number(result.get("amount")) - _number(source.get("amount"))
                ) > TOLERANCE
                missing_shift_employees[missing_key].add(source.get("employee_id"))
                missing_shift_metadata.setdefault(missing_key, {
                    "region": display,
                    "shift_code": shift_code,
                    "shift_name": source.get("source_shift_name"),
                    "shift_schedule": source.get("shift_schedule"),
                })
        for key in sorted(set(offline) & set(platform), key=lambda item: (item[1], item[0])):
            source = offline[key]
            result = platform[key]
            platform_amount = _number(result.get("amount"))
            line_amount = _number(source.get("amount"))
            difference = platform_amount - line_amount
            if abs(difference) <= TOLERANCE:
                continue
            attendance = attendance_by_key[key]
            shift_code = _text(source.get("shift_code") or result.get("shift_code"))
            shift = master.get(shift_code, {})
            out_of_schedule = _out_of_schedule_night_minutes(result, _text(source.get("shift_schedule")))
            detail = {
                "region": display,
                "source_file": path.name,
                "source_sheet": "日考勤" if label == "east" else "202607日考勤",
                "source_row": source.get("source_row"),
                "employee_id": source.get("employee_id"),
                "employee_name": source.get("employee_name"),
                "attendance_date": source.get("attendance_date"),
                "work_area": source.get("work_area"),
                "position": source.get("position"),
                "work_status": source.get("work_status"),
                "shift_code": shift_code,
                "shift_name": _text(shift.get("shift_name")) or _text(source.get("source_shift_name")),
                "shift_schedule": source.get("shift_schedule"),
                "abnormal": source.get("abnormal"),
                "abnormal_reason": source.get("abnormal_reason"),
                "configured_breaks": "、".join(shift.get("break_periods") or []),
                "raw_start": _json_value(source.get("raw_start")),
                "raw_end": _json_value(source.get("raw_end")),
                "rounded_start_minutes": result.get("rounded_start_minutes"),
                "rounded_end_minutes": result.get("rounded_end_minutes"),
                "night_hours": _money(_number(result.get("night_minutes")) / 60),
                "line_evening_break_hours": _money(_number(source.get("line_evening_break_hours"))),
                "line_morning_break_hours": _money(_number(source.get("line_morning_break_hours"))),
                "line_break_hours": _money(
                    _number(source.get("line_evening_break_hours"))
                    + _number(source.get("line_morning_break_hours"))
                ),
                "platform_break_hours": _money(_number(result.get("break_minutes")) / 60),
                "out_of_schedule_night_hours": _money(out_of_schedule / 60),
                "platform_yuan": _precision(platform_amount),
                "line_yuan": _precision(line_amount),
                "difference_yuan": _precision(difference),
                "platform_status": _text(result.get("status")),
                "platform_reason": _text(result.get("reason_code")),
                "platform_reason_label": REASON_LABELS.get(
                    _text(result.get("reason_code")), _text(result.get("reason_code"))
                ),
            }
            evidence_flags = []
            if _text(source.get("work_status")) != "工作日":
                evidence_flags.append("休息日记录")
            if out_of_schedule > TOLERANCE:
                evidence_flags.append(
                    f"平台计入排班外夜间{_money(out_of_schedule / 60)}小时"
                )
            line_break_hours = _number(source.get("line_evening_break_hours")) + _number(
                source.get("line_morning_break_hours")
            )
            platform_break_hours = _number(result.get("break_minutes")) / 60
            if abs(line_break_hours - platform_break_hours) > TOLERANCE:
                evidence_flags.append(
                    f"线下休息{_money(line_break_hours)}小时/平台{_money(platform_break_hours)}小时"
                )
            if line_amount <= TOLERANCE < platform_amount:
                evidence_flags.append("线下0元/平台计发")
            if platform_amount <= TOLERANCE < line_amount:
                evidence_flags.append("平台0元/线下计发")
            if _text(result.get("status")) != "calculated":
                evidence_flags.append(REASON_LABELS.get(
                    _text(result.get("reason_code")), _text(result.get("reason_code"))
                ))
            detail["evidence_flags"] = "；".join(evidence_flags)
            confirmed_rounded_break = (
                shift_code in CONFIRMED_ROUNDED_BREAK_SHIFT_CODES
                and abs(line_break_hours - platform_break_hours) > TOLERANCE
            )
            detail["confirmed_rounded_break_formula"] = confirmed_rounded_break
            if confirmed_rounded_break:
                detail["confirmed_formula_note"] = (
                    "休息按取整后实际覆盖时长扣除；线下扣整段属于公式下拉问题"
                )
            confirmed_no_morning_break = (
                display == "华东"
                and shift_code in CONFIRMED_NO_MORNING_BREAK_SHIFTS
                and _number(source.get("line_morning_break_hours")) > TOLERANCE
            )
            detail["confirmed_no_morning_break_formula"] = confirmed_no_morning_break
            if confirmed_no_morning_break:
                detail["confirmed_formula_note"] = (
                    "该班次没有早上休息段；线下多扣0.5小时属于表格公式问题"
                )

            if display == "华东" and shift_code in CONFIRMED_OFFLINE_FORMULA_SHIFTS:
                detail["issue"] = CONFIRMED_OFFLINE_FORMULA_ISSUE
                detail["requires_platform_action"] = False
            elif confirmed_rounded_break and _break_difference_fully_explains_amount(detail):
                detail["issue"] = CONFIRMED_OFFLINE_FORMULA_ISSUE
                detail["requires_platform_action"] = False
            elif confirmed_no_morning_break and _break_difference_fully_explains_amount(detail):
                detail["issue"] = CONFIRMED_OFFLINE_FORMULA_ISSUE
                detail["requires_platform_action"] = False
            else:
                detail["issue"] = _classify(
                    source,
                    attendance,
                    result,
                    difference,
                    out_of_schedule,
                    ignore_break_difference=(
                        confirmed_rounded_break or confirmed_no_morning_break
                    ),
                )
                detail["requires_platform_action"] = True
            details.append(detail)

    confirmed_offline_formula_details = [
        row for row in details if not row["requires_platform_action"]
    ]
    confirmed_rounded_break_details = [
        row for row in details if row["confirmed_rounded_break_formula"]
    ]
    confirmed_no_morning_break_details = [
        row for row in details if row["confirmed_no_morning_break_formula"]
    ]
    actionable_details = [
        row for row in details if row["requires_platform_action"]
    ]
    summaries = _summaries(actionable_details)
    confirmed_offline_formula_summaries = _summaries(
        confirmed_offline_formula_details
    )
    missing_shifts = []
    for key, stats in missing_shift_stats.items():
        metadata = missing_shift_metadata[key]
        missing_shifts.append({
            **metadata,
            "employees": len(missing_shift_employees[key]),
            "attendance_rows": stats["attendance_rows"],
            "line_paid_rows": stats["line_paid_rows"],
            "pending_rows": stats["pending_rows"],
            "mismatch_rows": stats["mismatch_rows"],
            "platform_yuan": _money(stats["platform_yuan"]),
            "line_yuan": _money(stats["line_yuan"]),
            "net_yuan": _money(stats["platform_yuan"] - stats["line_yuan"]),
        })
    missing_shifts.sort(key=lambda row: (-row["attendance_rows"], row["shift_code"]))
    payload: Dict[str, Any] = {
        "month": "202607",
        "confirmed_rules": {
            "HD048": ["23:00-24:00", "06:00-06:30"],
            "LB15": "休息18:00-18:30；8小时正班基准扣减迟到、早退后折算",
        },
        "confirmed_offline_formula_issues": {
            "decision": "无需调整平台计算或班次休息配置",
            "shifts": confirmed_offline_formula_summaries["by_shift"],
            "rows": len(confirmed_offline_formula_details),
            "rounded_actual_coverage": {
                "decision": "取整后实际覆盖多少休息时间就扣多少",
                "rows": len(confirmed_rounded_break_details),
                "fully_explained_rows": sum(
                    not row["requires_platform_action"]
                    for row in confirmed_rounded_break_details
                ),
                "other_reason_rows": sum(
                    row["requires_platform_action"]
                    for row in confirmed_rounded_break_details
                ),
            },
            "east_no_morning_break": {
                "decision": "HD003、HD012、HD014、HD027没有早上休息段；线下多扣0.5小时",
                "rows": len(confirmed_no_morning_break_details),
                "fully_explained_rows": sum(
                    not row["requires_platform_action"]
                    for row in confirmed_no_morning_break_details
                ),
                "other_reason_rows": sum(
                    row["requires_platform_action"]
                    for row in confirmed_no_morning_break_details
                ),
            },
        },
        "quality": {
            "region_counts": region_counts,
            "matched_rows": sum(item["source_rows"] for item in region_counts.values()),
            "duplicate_keys": sum(item["duplicate_keys"] for item in region_counts.values()),
            "raw_mismatch_rows": len(details),
            "confirmed_offline_formula_rows": len(confirmed_offline_formula_details),
            "mismatch_rows": len(actionable_details),
        },
        **summaries,
        "missing_shift_sources": missing_shifts,
        "details": actionable_details,
        "confirmed_offline_formula_details": confirmed_offline_formula_details,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        key: value
        for key, value in payload.items()
        if key not in {"details", "confirmed_offline_formula_details"}
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
