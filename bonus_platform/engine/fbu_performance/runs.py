"""FBU绩效核算引擎 - 运行管理"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional
from pathlib import Path
import shutil
import json
import os
import threading
import uuid

from .engines.base import CalculationSegment, EmployeeData, get_calculation_path
from .exporter import FBUPerformanceExporter
from .persistent_storage import (
    FBU_RUN_SECTION_FIELDS,
    build_fbu_run_manifest,
    delete_fbu_files_from_persistent,
    delete_fbu_run_from_persistent,
    fbu_persistent_storage_enabled,
    list_fbu_run_summaries_from_persistent,
    load_fbu_file_from_persistent,
    load_fbu_run_snapshot_from_persistent,
    read_fbu_file_from_persistent,
    save_fbu_files_to_persistent,
    save_fbu_run_snapshot_to_persistent,
)


_FINAL_RESULT_SUM_FIELDS = {
    "base_hours",
    "ot15_hours",
    "ot20_hours",
    "sick_hours",
    "sick_settlement_hours",
    "annual_hours",
    "holiday_hours",
    "system_performance_base",
    "period_adjustment",
    "performance_base",
    "performance_bonus",
}
_FINAL_RESULT_MONEY_FIELDS = {
    "system_performance_base",
    "period_adjustment",
    "performance_base",
    "performance_bonus",
}


def _parse_saved_date(value) -> date | None:
    """Parse an ISO date saved in runs.json back into a date object."""
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None


def _result_source_employee_id(row: dict[str, Any]) -> str:
    source_employee_id = str(row.get("source_employee_id") or "").strip()
    if source_employee_id:
        return source_employee_id
    return str(row.get("employee_id") or "").strip()


def _first_present(rows: list[dict[str, Any]], field: str) -> Any:
    for row in rows:
        value = row.get(field)
        if value not in (None, ""):
            return value
    return rows[0].get(field) if rows else ""


def _unique_ordered(values: list[Any]) -> list[Any]:
    unique = []
    seen = set()
    for value in values:
        if value in (None, ""):
            continue
        key = str(value)
        if key in seen:
            continue
        seen.add(key)
        unique.append(value)
    return unique


def _sum_result_field(rows: list[dict[str, Any]], field: str) -> float:
    total = 0.0
    for row in rows:
        try:
            value = row.get(field)
            if field == "system_performance_base" and value is None:
                value = row.get("performance_base")
            total += float(value or 0)
        except (TypeError, ValueError):
            continue
    return round(total, 2 if field in _FINAL_RESULT_MONEY_FIELDS else 4)


def _split_segment_reason(row: dict[str, Any], source_employee_id: str) -> str:
    employee_id = str(row.get("employee_id") or "")
    if employee_id.endswith("-1"):
        return "白班拆行"
    if employee_id == source_employee_id:
        return "夜班拆行"
    return "拆行核算"


def _build_final_calculation_segments(
    rows: list[dict[str, Any]],
    source_employee_id: str,
) -> list[dict[str, Any]]:
    if len(rows) == 1:
        row = rows[0]
        saved_segments = list(row.get("calculation_segments") or [])
        if saved_segments:
            return saved_segments
        period_adjustment = float(row.get("period_adjustment") or 0)
        adjustment_bonus = (
            period_adjustment
            * float(row.get("performance_ratio") or 0)
            * float(row.get("performance_coefficient") or 0)
        )
        return [{
            "period": "",
            "reason": row.get("calculation_path") or "标准绩效基数路径",
            "performance_base": round(float(
                row.get("system_performance_base")
                if row.get("system_performance_base") is not None
                else row.get("performance_base") or 0
            ), 2),
            "performance_ratio": row.get("performance_ratio") or 0,
            "performance_coefficient": row.get("performance_coefficient") or 0,
            "performance_bonus": round(
                float(row.get("performance_bonus") or 0) - adjustment_bonus,
                2,
            ),
        }]

    segments: list[dict[str, Any]] = []
    for row in rows:
        raw_segments = row.get("calculation_segments") or []
        if raw_segments:
            for segment in raw_segments:
                segments.append(dict(segment))
            continue
        segments.append({
            "period": row.get("employee_id", ""),
            "reason": _split_segment_reason(row, source_employee_id),
            "performance_base": round(float(row.get("performance_base") or 0), 2),
            "performance_ratio": row.get("performance_ratio") or 0,
            "performance_coefficient": row.get("performance_coefficient") or 0,
            "performance_bonus": round(float(row.get("performance_bonus") or 0), 2),
        })
    return segments


def _base_component(
    label: str,
    amount: float,
    *,
    hours: float | None = None,
    hourly_rate: float | None = None,
    multiplier: float = 1.0,
    period: str = "",
    note: str = "",
) -> dict[str, Any]:
    component = {
        "label": label,
        "amount": round(float(amount or 0), 2),
        "multiplier": float(multiplier or 1),
    }
    if hours is not None:
        component["hours"] = round(float(hours or 0), 4)
    if hourly_rate is not None:
        component["hourly_rate"] = round(float(hourly_rate or 0), 4)
    if period:
        component["period"] = period
    if note:
        component["note"] = note
    return component


def _build_base_calculation_detail(emp: EmployeeData) -> dict[str, Any]:
    """Build a durable audit trail for the performance-base calculation."""
    path = get_calculation_path(emp)
    display_label = "夜班" if emp.is_night_shift else ("白班" if emp.employee_id.endswith("-1") else "")
    detail: dict[str, Any] = {
        "employee_id": emp.employee_id,
        "display_label": display_label,
        "path": path,
        "performance_base": round(float(emp.system_performance_base or emp.performance_base or 0), 2),
        "components": [],
        "note": "",
    }

    if emp.job_type == "district_manager" and emp.fixed_performance_base:
        detail["components"] = [_base_component("区长固定绩效基数", emp.fixed_performance_base)]
        detail["note"] = "按已确认的区长固定绩效基数核算。"
        return detail

    if emp.base_override_amount:
        detail["components"] = [_base_component("固定绩效基数覆盖", emp.base_override_amount)]
        detail["note"] = emp.base_override_reason or emp.base_override_type or "按已确认的固定绩效基数覆盖。"
        return detail

    if emp.calculation_segments:
        detail["components"] = [
            _base_component(
                segment.reason or "拆分基数",
                segment.performance_base,
                period=segment.period,
                note=f"适用绩效比例 {segment.performance_ratio:.1%}",
            )
            for segment in emp.calculation_segments
        ]
        detail["note"] = "按调薪或转正生效日拆分；仅适用绩效比例大于 0 的分段计入最终绩效基数。"
        return detail

    if "96" in str(emp.work_hour_rule or ""):
        rule_rate = emp.work_hour_rule_rounded_hourly_rate or (
            max(emp.hourly_rate - 1, 0) if emp.is_night_shift else emp.hourly_rate
        )
        if emp.work_hour_rule_special_total_hours:
            detail["components"] = [
                _base_component(
                    "96工时制计入工时",
                    emp.performance_base,
                    hours=emp.work_hour_rule_special_total_hours,
                    hourly_rate=rule_rate,
                )
            ]
            detail["note"] = "按特殊工时汇总的计入工时和规则时薪计算。"
            return detail

        if emp.work_hour_rule_periods:
            detail["components"] = [
                _base_component(
                    "周期计入工时",
                    period.get("performance_base", 0),
                    hours=period.get("included_hours", 0),
                    hourly_rate=rule_rate,
                    period=str(period.get("period") or ""),
                    note=f"周期上限 {float(period.get('cap_hours') or 0):.2f}h",
                )
                for period in emp.work_hour_rule_periods
            ]
            detail["note"] = "各周期先按 96 工时制上限确认计入工时，再汇总绩效基数。"
            return detail

        components = []
        if emp.base_salary or not emp.holiday_pay:
            included_hours = emp.base_salary / rule_rate if rule_rate else 0
            components.append(_base_component(
                "96工时制封顶计入工时",
                emp.base_salary,
                hours=included_hours,
                hourly_rate=rule_rate,
            ))
        if emp.holiday_pay:
            holiday_hours = emp.holiday_pay / rule_rate if rule_rate else 0
            components.append(_base_component(
                "封顶外节日工时",
                emp.holiday_pay,
                hours=holiday_hours,
                hourly_rate=rule_rate,
            ))
        detail["components"] = components
        detail["note"] = "按 96 工时制上限和节日工时口径计算。"
        return detail

    standard_components = [
        _base_component("基础工时", emp.base_salary, hours=emp.base_hours, hourly_rate=emp.hourly_rate),
        _base_component("OT 1.5", emp.ot15_salary, hours=emp.ot15_hours, hourly_rate=emp.hourly_rate, multiplier=1.5),
        _base_component("OT 2.0", emp.ot20_salary, hours=emp.ot20_hours, hourly_rate=emp.hourly_rate, multiplier=2.0),
        _base_component("病假", emp.sick_pay, hours=emp.sick_hours, hourly_rate=emp.hourly_rate),
        _base_component("离职病假清算", emp.sick_settlement_pay, hours=emp.sick_settlement_hours, hourly_rate=emp.hourly_rate),
        _base_component("年假", emp.annual_leave_pay, hours=emp.annual_hours, hourly_rate=emp.hourly_rate),
        _base_component("节日补贴", emp.holiday_pay, hours=emp.holiday_hours, hourly_rate=emp.hourly_rate),
    ]
    visible_components = [component for component in standard_components if component["amount"] or component.get("hours")]
    component_total = round(
        emp.base_salary
        + emp.ot15_salary
        + emp.ot20_salary
        + emp.sick_pay
        + emp.sick_settlement_pay
        + emp.annual_leave_pay
        + emp.holiday_pay,
        2,
    )
    if abs(component_total - detail["performance_base"]) > 0.01:
        visible_components = [_base_component("本月绩效基数", emp.performance_base)]
        detail["note"] = "结果数据未保存工时组成，展示本月已核算绩效基数。"
    else:
        detail["note"] = "标准路径按各类工时工资与补贴相加。"
    detail["components"] = visible_components or [_base_component("基础工时", 0, hours=0, hourly_rate=emp.hourly_rate)]
    return detail


def _build_saved_base_calculation_detail(row: dict[str, Any]) -> dict[str, Any]:
    """Reconstruct base audit details for runs saved before the audit field existed."""
    employee_id = str(row.get("employee_id") or "")
    path = str(row.get("calculation_path") or "标准绩效基数路径")
    performance_base = float(row.get("performance_base") or 0)
    detail: dict[str, Any] = {
        "employee_id": employee_id,
        "display_label": "白班" if employee_id.endswith("-1") else "",
        "path": path,
        "performance_base": round(performance_base, 2),
        "components": [],
        "note": "",
    }

    if path == "区长固定基数路径":
        detail["components"] = [_base_component("区长固定绩效基数", performance_base)]
        detail["note"] = "按已确认的区长固定绩效基数核算。"
        return detail

    if row.get("base_override_amount"):
        detail["components"] = [_base_component("固定绩效基数覆盖", performance_base)]
        detail["note"] = str(
            row.get("base_override_reason")
            or row.get("base_override_type")
            or "按已确认的固定绩效基数覆盖。"
        )
        return detail

    segments = row.get("calculation_segments") or []
    if segments:
        detail["components"] = [
            _base_component(
                str(segment.get("reason") or "拆分基数"),
                segment.get("performance_base", 0),
                period=str(segment.get("period") or ""),
                note=f"适用绩效比例 {float(segment.get('performance_ratio') or 0):.1%}",
            )
            for segment in segments
        ]
        detail["note"] = "按调薪或转正生效日拆分；仅适用绩效比例大于 0 的分段计入最终绩效基数。"
        return detail

    if "96" in str(row.get("work_hour_rule") or ""):
        special_hours = float(row.get("work_hour_rule_special_total_hours") or 0)
        rounded_rate = float(row.get("work_hour_rule_rounded_hourly_rate") or 0)
        if special_hours:
            rule_rate = rounded_rate or (performance_base / special_hours if special_hours else 0)
            detail["components"] = [_base_component(
                "96工时制计入工时",
                performance_base,
                hours=special_hours,
                hourly_rate=rule_rate,
            )]
            detail["note"] = "按特殊工时汇总的计入工时和规则时薪计算。"
            return detail

        periods = row.get("work_hour_rule_periods") or []
        if periods:
            components = []
            for period in periods:
                hours = float(period.get("included_hours") or 0)
                amount = float(period.get("performance_base") or 0)
                rule_rate = rounded_rate or (amount / hours if hours else float(row.get("hourly_rate") or 0))
                components.append(_base_component(
                    "周期计入工时",
                    amount,
                    hours=hours,
                    hourly_rate=rule_rate,
                    period=str(period.get("period") or ""),
                    note=f"周期上限 {float(period.get('cap_hours') or 0):.2f}h",
                ))
            detail["components"] = components
            detail["note"] = "各周期先按 96 工时制上限确认计入工时，再汇总绩效基数。"
            return detail

        detail["components"] = [_base_component("96工时制绩效基数", performance_base)]
        detail["note"] = "历史结果未保存完整周期明细，展示已核算的 96 工时制绩效基数。"
        return detail

    hourly_rate = float(row.get("hourly_rate") or 0)
    component_specs = [
        ("基础工时", "base_hours", 1.0),
        ("OT 1.5", "ot15_hours", 1.5),
        ("OT 2.0", "ot20_hours", 2.0),
        ("病假", "sick_hours", 1.0),
        ("离职病假清算", "sick_settlement_hours", 1.0),
        ("年假", "annual_hours", 1.0),
        ("节日补贴", "holiday_hours", 1.0),
    ]
    components = []
    for label, hours_field, multiplier in component_specs:
        hours = float(row.get(hours_field) or 0)
        if not hours:
            continue
        components.append(_base_component(
            label,
            hours * hourly_rate * multiplier,
            hours=hours,
            hourly_rate=hourly_rate,
            multiplier=multiplier,
        ))
    reconstructed_total = round(sum(component["amount"] for component in components), 2)
    if components and abs(reconstructed_total - round(performance_base, 2)) <= 0.02:
        detail["components"] = components
        detail["note"] = "根据历史批次保存的工时和时薪还原标准基数计算。"
    else:
        detail["components"] = [_base_component("本月绩效基数", performance_base)]
        detail["note"] = "历史结果未保存完整工时组成，展示已核算的绩效基数。"
    return detail


def _build_final_base_calculation_details(
    rows: list[dict[str, Any]],
    source_employee_id: str,
) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for row in rows:
        row_details = row.get("base_calculation_details") or [_build_saved_base_calculation_detail(row)]
        for raw_detail in row_details:
            detail = dict(raw_detail)
            if len(rows) > 1 and not detail.get("display_label"):
                detail["display_label"] = _split_segment_reason(row, source_employee_id)
            details.append(detail)
    return details


def build_final_result_rows(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge internal split rows into final employee result rows for viewing/export."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for row in results:
        source_employee_id = _result_source_employee_id(row)
        if source_employee_id not in grouped:
            grouped[source_employee_id] = []
            order.append(source_employee_id)
        grouped[source_employee_id].append(row)

    final_rows: list[dict[str, Any]] = []
    for source_employee_id in order:
        rows = grouped[source_employee_id]
        final_row = dict(rows[0])
        final_row["employee_id"] = source_employee_id
        final_row["source_employee_id"] = source_employee_id
        final_row["raw_employee_ids"] = _unique_ordered([row.get("employee_id") for row in rows])
        final_row["merged_result"] = len(rows) > 1
        final_row.pop("hourly_rate", None)
        final_row.pop("attendance_daily_rows", None)
        final_row.pop("work_hour_rule_periods", None)

        for field in _FINAL_RESULT_SUM_FIELDS:
            final_row[field] = _sum_result_field(rows, field)

        for field in [
            "performance_ratio",
            "performance_score",
            "performance_level",
            "uploaded_coefficient",
            "coefficient_override_reason",
            "performance_coefficient",
            "job_type",
            "position",
            "work_hour_rule",
            "base_override_type",
            "base_override_reason",
        ]:
            final_row[field] = _first_present(rows, field)

        paths = _unique_ordered([row.get("calculation_path") for row in rows])
        if paths:
            final_row["calculation_path"] = " / ".join(str(path) for path in paths)

        exceptions: list[Any] = []
        for row in rows:
            exceptions.extend(row.get("exceptions") or [])
        final_row["exceptions"] = _unique_ordered(exceptions)
        final_row["period_adjustment_source_month"] = _first_present(
            rows, "period_adjustment_source_month"
        )
        final_row["period_adjustment_reason"] = _first_present(
            rows, "period_adjustment_reason"
        )
        calculation_segments = _build_final_calculation_segments(rows, source_employee_id)
        if final_row["period_adjustment"]:
            calculation_segments.append({
                "period": final_row["period_adjustment_source_month"],
                "reason": final_row["period_adjustment_reason"] or "Period adjustment",
                "performance_base": final_row["period_adjustment"],
                "performance_ratio": final_row.get("performance_ratio") or 0,
                "performance_coefficient": final_row.get("performance_coefficient") or 0,
                "performance_bonus": round(
                    final_row["period_adjustment"]
                    * float(final_row.get("performance_ratio") or 0)
                    * float(final_row.get("performance_coefficient") or 0),
                    2,
                ),
                "is_period_adjustment": True,
            })
        final_row["calculation_segments"] = calculation_segments
        base_details = _build_final_base_calculation_details(rows, source_employee_id)
        if final_row["period_adjustment"]:
            base_details.append({
                "employee_id": source_employee_id,
                "display_label": "",
                "path": "Period adjustment",
                "performance_base": final_row["period_adjustment"],
                "components": [_base_component(
                    final_row["period_adjustment_reason"] or "绩效基数差额",
                    final_row["period_adjustment"],
                    period=final_row["period_adjustment_source_month"],
                )],
                "note": "该差额计入最终绩效基数，奖金按本次核算月绩效比例和系数计算。",
            })
        final_row["base_calculation_details"] = base_details
        final_rows.append(final_row)

    return final_rows


def build_results_view_data(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the compact, page-ready representation used by result browsing."""
    return {
        "schema_version": 1,
        "rows": build_final_result_rows(results),
    }


def has_attendance_employees(attendance_data: dict[str, Any]) -> bool:
    return bool(
        isinstance(attendance_data, dict)
        and isinstance(attendance_data.get("employees"), list)
        and any(
            isinstance(employee, dict)
            for employee in attendance_data["employees"]
        )
    )


def build_attendance_view_data(attendance_data: dict[str, Any]) -> dict[str, Any]:
    """Build the attendance-step view without calculation-only daily rows."""
    if not has_attendance_employees(attendance_data):
        return {}
    employees = [
        employee
        for employee in (attendance_data.get("employees") or [])
        if isinstance(employee, dict)
    ]
    if not employees:
        return {}
    view = {
        key: value
        for key, value in attendance_data.items()
        if key != "employees"
    }
    view["employees"] = [
        {
            key: value
            for key, value in employee.items()
            if key != "attendance_daily_rows"
        }
        for employee in employees
    ]
    return view


FBU_RUN_LIST_FIELDS = (
    "run_id",
    "created_at",
    "calc_month",
    "status",
    "current_step",
    "total_employees",
    "total_bonus",
    "match_rate",
    "error",
)
FBU_RUN_LIST_SECTION_SUMMARY_KEYS = {
    "base_override_data": {"work_hour_count", "fixed_base_count"},
    "salary_verification_data": {"blocking_count"},
    "supplemental_leave_data": {"suggested_count"},
}


def build_fbu_run_list_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    """Build the small activity-list contract without returning storage metadata."""
    run = dict(manifest.get("run") or {})
    summary = {
        field_name: run.get(field_name)
        for field_name in FBU_RUN_LIST_FIELDS
        if field_name in run
    }
    compact_sections: dict[str, dict[str, Any]] = {}
    sections = manifest.get("sections") or {}
    for field_name, allowed_summary_keys in FBU_RUN_LIST_SECTION_SUMMARY_KEYS.items():
        section = sections.get(field_name)
        if not isinstance(section, dict) or not section.get("present"):
            continue
        compact = {"present": True}
        raw_summary = section.get("summary")
        if isinstance(raw_summary, dict):
            section_summary = {
                key: raw_summary[key]
                for key in allowed_summary_keys
                if key in raw_summary
                and isinstance(raw_summary[key], (str, int, float, bool))
            }
            if section_summary:
                compact["summary"] = section_summary
        compact_sections[field_name] = compact
    summary["sections"] = compact_sections
    return summary


@dataclass
class FBURun:
    """FBU核算运行记录"""
    run_id: str
    created_at: str
    calc_month: str
    status: str = "pending"  # pending / step1 / step2 / step3 / processing / completed / failed
    current_step: int = 0  # 当前步骤 (0=未开始, 1=考勤, 2=薪资, 3=绩效, 4=计算中, 5=完成)
    attendance_file: str = ""
    previous_attendance_file: str = ""
    salary_file: str = ""
    previous_salary_file: str = ""
    current_salary_file: str = ""
    performance_file: str = ""
    adjustment_file: str = ""
    transfer_file: str = ""
    supplemental_leave_file: str = ""
    base_override_file: str = ""
    roster_file: str = ""
    roster_source: str = ""  # activity / base
    roster_data: dict = field(default_factory=dict)
    # 分步数据
    attendance_data: dict = field(default_factory=dict)  # 考勤解析结果
    attendance_view_data: dict = field(default_factory=dict)  # 页面考勤汇总（不含逐日明细）
    salary_data: dict = field(default_factory=dict)  # 薪资解析结果
    previous_salary_data: dict = field(default_factory=dict)
    current_salary_data: dict = field(default_factory=dict)
    salary_verification_data: dict = field(default_factory=dict)
    performance_data: dict = field(default_factory=dict)  # 绩效解析结果
    adjustment_data: dict = field(default_factory=dict)  # 调薪/转正拆分解析结果
    transfer_data: dict = field(default_factory=dict)  # 人事调动历史（调动日期=生效日期）
    supplemental_leave_data: dict = field(default_factory=dict)  # sickpay&年假补充确认
    base_override_data: dict = field(default_factory=dict)  # 96工时制/线下固定基数覆盖
    hourly_rate_policy_data: dict = field(default_factory=dict)  # 双周工资周期适用时薪建议/人工调整
    period_adjustment_data: dict = field(default_factory=dict)  # 绩效基数补发/扣回差额
    # 最终结果
    total_employees: int = 0
    total_bonus: float = 0.0
    match_rate: float = 0.0
    results: list[dict] = field(default_factory=list)
    results_view_data: dict = field(default_factory=dict)
    error: str = ""


class FBURunManager:
    """FBU运行管理器"""

    RESULT_INPUT_FIELDS = {
        "attendance_file", "previous_attendance_file", "salary_file",
        "previous_salary_file", "current_salary_file", "performance_file",
        "adjustment_file", "transfer_file", "supplemental_leave_file", "base_override_file",
        "attendance_data", "salary_data",
        "previous_salary_data", "current_salary_data", "salary_verification_data",
        "performance_data", "adjustment_data", "transfer_data", "supplemental_leave_data",
        "base_override_data", "hourly_rate_policy_data", "period_adjustment_data",
    }

    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.runs: dict[str, FBURun] = {}
        self._manifests: dict[str, dict[str, Any]] = {}
        self._loaded_sections: dict[str, set[str]] = {}
        self._legacy_payloads: dict[str, dict[str, Any]] | None = None
        self._lock = threading.RLock()
        self._load_runs()

    @property
    def _index_file(self) -> Path:
        return self.data_dir / "runs.index.json"

    @staticmethod
    def _run_fields() -> set[str]:
        return set(FBURun.__dataclass_fields__)

    @classmethod
    def _run_from_payload(cls, payload: dict[str, Any]) -> FBURun:
        return FBURun(**{
            key: value
            for key, value in payload.items()
            if key in cls._run_fields()
        })

    @staticmethod
    def _write_json_atomic(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def _load_runs(self):
        """加载历史运行记录"""
        if self._index_file.exists():
            try:
                with self._index_file.open("r", encoding="utf-8") as handle:
                    index_payload = json.load(handle)
            except (OSError, json.JSONDecodeError):
                index_payload = {}
            manifests = index_payload.get("runs") if isinstance(index_payload, dict) else None
            if isinstance(manifests, list):
                for manifest in manifests:
                    if not isinstance(manifest, dict) or not isinstance(manifest.get("run"), dict):
                        continue
                    try:
                        run = self._run_from_payload(manifest["run"])
                    except TypeError:
                        continue
                    self.runs[run.run_id] = run
                    self._manifests[run.run_id] = manifest
                    self._loaded_sections[run.run_id] = set()
                return

        runs_file = self.data_dir / "runs.json"
        if not runs_file.exists():
            return

        try:
            with open(runs_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            self._quarantine_corrupt_runs_file(runs_file)
            return

        if not isinstance(data, list):
            self._quarantine_corrupt_runs_file(runs_file)
            return

        for run_data in data:
            try:
                run = self._run_from_payload(run_data)
            except TypeError:
                continue
            self.runs[run.run_id] = run
            self._manifests[run.run_id] = build_fbu_run_manifest(run_data)
            self._loaded_sections[run.run_id] = set(FBU_RUN_SECTION_FIELDS)

    def _quarantine_corrupt_runs_file(self, runs_file: Path):
        suffix = datetime.now().strftime("%Y%m%d%H%M%S")
        quarantine_path = runs_file.with_name(f"runs.corrupt-{suffix}.json")
        try:
            runs_file.replace(quarantine_path)
        except OSError:
            pass

    def _local_section_path(self, run_id: str, field: str) -> Path:
        return self.data_dir / run_id / "sections" / f"{field}.json"

    def _save_local_run_snapshot(
        self,
        run_id: str,
        payload: dict[str, Any],
        changed_fields: set[str] | None,
    ) -> dict[str, Any]:
        previous = self._manifests.get(run_id)
        manifest = build_fbu_run_manifest(
            payload,
            previous=previous,
            changed_fields=changed_fields,
        )
        if changed_fields is None:
            section_fields = {
                field
                for field in FBU_RUN_SECTION_FIELDS
                if field in payload
                and (
                    bool(payload.get(field))
                    or bool(((previous or {}).get("sections") or {}).get(field, {}).get("present"))
                )
            }
        else:
            section_fields = set(changed_fields).intersection(FBU_RUN_SECTION_FIELDS)
        for field_name in section_fields:
            self._write_json_atomic(
                self._local_section_path(run_id, field_name),
                payload.get(field_name),
            )
        self._write_json_atomic(self.data_dir / run_id / "summary.json", manifest)
        self._manifests[run_id] = manifest
        self._loaded_sections.setdefault(run_id, set()).update(section_fields)
        return manifest

    def _write_local_index(self) -> None:
        manifests = sorted(
            self._manifests.values(),
            key=lambda row: str((row.get("run") or {}).get("created_at") or ""),
            reverse=True,
        )
        self._write_json_atomic(
            self._index_file,
            {
                "schemaVersion": 2,
                "updatedAt": datetime.now().isoformat(),
                "runs": manifests,
            },
        )
        compatibility_file = self.data_dir / "runs.json"
        if not compatibility_file.exists():
            self._write_json_atomic(
                compatibility_file,
                [manifest.get("run") or {} for manifest in manifests],
            )

    def _save_runs(
        self,
        changed_run_id: str | None = None,
        changed_fields: set[str] | None = None,
    ):
        """保存运行记录"""
        with self._lock:
            run = self.runs.get(changed_run_id) if changed_run_id else None
            if run:
                self._save_local_run_snapshot(
                    changed_run_id,
                    vars(run),
                    changed_fields,
                )
            self._write_local_index()
            if fbu_persistent_storage_enabled() and run:
                manifest = save_fbu_run_snapshot_to_persistent(
                    changed_run_id,
                    vars(run),
                    changed_fields=changed_fields,
                )
                self._manifests[changed_run_id] = manifest

    def create_run(
        self,
        calc_month: str,
        attendance_file: str = "",
        salary_file: str = "",
        performance_file: str = "",
        persist: bool = True,
    ) -> FBURun:
        """创建新的运行"""
        run = FBURun(
            run_id=str(uuid.uuid4())[:8],
            created_at=datetime.now().isoformat(),
            calc_month=calc_month,
            attendance_file=attendance_file,
            salary_file=salary_file,
            performance_file=performance_file,
        )
        self.runs[run.run_id] = run
        self._loaded_sections[run.run_id] = set(FBU_RUN_SECTION_FIELDS)
        if persist:
            self._save_runs(run.run_id)
        return run

    def update_run(self, run_id: str, *, persist: bool = True, **kwargs):
        """更新运行状态"""
        run = self.get_run(run_id, sections=set())
        if run:
            changed_fields = set(kwargs)
            if self.RESULT_INPUT_FIELDS.intersection(kwargs):
                self._invalidate_results(run)
                changed_fields.update({
                    "results",
                    "results_view_data",
                    "total_employees",
                    "total_bonus",
                    "match_rate",
                })
            for key, value in kwargs.items():
                setattr(run, key, value)
            self.runs[run_id] = run
            self._loaded_sections.setdefault(run_id, set()).update(
                changed_fields.intersection(FBU_RUN_SECTION_FIELDS)
            )
            if persist:
                self._save_runs(run_id, changed_fields)

    def backfill_hourly_rate_policy_data(self, run_id: str, data: dict) -> None:
        """Persist generated defaults for legacy runs without invalidating saved results."""
        run = self.get_run(run_id, sections={"hourly_rate_policy_data"})
        if not run or run.hourly_rate_policy_data:
            return
        run.hourly_rate_policy_data = data
        self.runs[run_id] = run
        self._save_runs(run_id, {"hourly_rate_policy_data"})

    def backfill_results_view_data(self, run_id: str, data: dict) -> None:
        """Persist a derived result view without changing calculation status."""
        run = self.get_run(run_id, sections={"results_view_data"})
        if not run or run.results_view_data:
            return
        run.results_view_data = data
        self.runs[run_id] = run
        self._save_runs(run_id, {"results_view_data"})

    def backfill_attendance_view_data(self, run_id: str, data: dict) -> None:
        """Persist a derived attendance view without changing calculation status."""
        run = self.get_run(run_id, sections={"attendance_view_data"})
        if (
            not run
            or has_attendance_employees(run.attendance_view_data)
            or not has_attendance_employees(data)
        ):
            return
        run.attendance_view_data = data
        self.runs[run_id] = run
        self._save_runs(run_id, {"attendance_view_data"})

    @staticmethod
    def _invalidate_results(run: FBURun):
        run.results = []
        run.results_view_data = {}
        run.total_employees = 0
        run.total_bonus = 0.0
        run.match_rate = 0.0

    def save_step_data(self, run_id: str, step: int, data: dict, **updates):
        """保存分步数据"""
        run = self.get_run(run_id, sections=set())
        if not run:
            return

        self._invalidate_results(run)
        changed_fields = {
            "results",
            "results_view_data",
            "total_employees",
            "total_bonus",
            "match_rate",
            *updates.keys(),
        }
        for key, value in updates.items():
            setattr(run, key, value)

        if step == 1:
            run.attendance_data = data
            run.attendance_view_data = build_attendance_view_data(data)
            run.current_step = 1
            run.status = "step1"
            changed_fields.update({"attendance_data", "attendance_view_data"})
        elif step == 2:
            run.salary_data = data
            run.current_step = 2
            run.status = "step2"
            changed_fields.add("salary_data")
        elif step == 3:
            run.performance_data = data
            run.current_step = 3
            run.status = "step3"
            changed_fields.add("performance_data")
        elif step == 4:
            run.adjustment_data = data
            changed_fields.add("adjustment_data")

        self.runs[run_id] = run
        changed_fields.update({"current_step", "status"})
        self._loaded_sections.setdefault(run_id, set()).update(
            changed_fields.intersection(FBU_RUN_SECTION_FIELDS)
        )
        self._save_runs(run_id, changed_fields)

    def _load_legacy_payloads(self) -> dict[str, dict[str, Any]]:
        if self._legacy_payloads is not None:
            return self._legacy_payloads
        self._legacy_payloads = {}
        runs_file = self.data_dir / "runs.json"
        if not runs_file.exists():
            return self._legacy_payloads
        try:
            with runs_file.open("r", encoding="utf-8") as handle:
                rows = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return self._legacy_payloads
        if isinstance(rows, list):
            self._legacy_payloads = {
                str(row.get("run_id")): row
                for row in rows
                if isinstance(row, dict) and row.get("run_id")
            }
        return self._legacy_payloads

    def _load_local_sections(self, run_id: str, sections: set[str]) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        legacy: dict[str, Any] | None = None
        for field_name in sections:
            section_path = self._local_section_path(run_id, field_name)
            if section_path.exists():
                try:
                    with section_path.open("r", encoding="utf-8") as handle:
                        payload[field_name] = json.load(handle)
                    continue
                except (OSError, json.JSONDecodeError):
                    pass
            if legacy is None:
                legacy = self._load_legacy_payloads().get(run_id) or {}
            if field_name in legacy:
                payload[field_name] = legacy[field_name]
            else:
                payload[field_name] = [] if field_name == "results" else {}
        return payload

    def _merge_run_payload(self, run_id: str, payload: dict[str, Any]) -> FBURun | None:
        existing = self.runs.get(run_id)
        merged = vars(existing).copy() if existing else {}
        merged.update({
            key: value
            for key, value in payload.items()
            if key in self._run_fields()
        })
        try:
            run = self._run_from_payload(merged)
        except TypeError:
            return None
        self.runs[run_id] = run
        return run

    def get_run(
        self,
        run_id: str,
        sections: set[str] | None = None,
    ) -> Optional[FBURun]:
        """获取运行记录"""
        requested = (
            set(FBU_RUN_SECTION_FIELDS)
            if sections is None
            else set(sections).intersection(FBU_RUN_SECTION_FIELDS)
        )
        if fbu_persistent_storage_enabled():
            payload = load_fbu_run_snapshot_from_persistent(
                run_id,
                sections=requested,
            )
            if payload:
                run = self._merge_run_payload(run_id, payload)
                if not run:
                    return None
                self._loaded_sections.setdefault(run_id, set()).update(requested)
                self._manifests[run_id] = build_fbu_run_manifest(
                    payload,
                    previous=self._manifests.get(run_id),
                    changed_fields=requested,
                )
                return run

        run = self.runs.get(run_id)
        if not run:
            return None
        missing = requested.difference(self._loaded_sections.get(run_id, set()))
        if missing:
            loaded = self._load_local_sections(run_id, missing)
            run = self._merge_run_payload(run_id, loaded) or run
            self._loaded_sections.setdefault(run_id, set()).update(missing)
        return run

    def list_runs(self) -> list[FBURun]:
        """获取所有运行记录"""
        if fbu_persistent_storage_enabled():
            for manifest in list_fbu_run_summaries_from_persistent():
                payload = manifest.get("run") or {}
                run_id = str(payload.get("run_id") or "")
                if not run_id:
                    continue
                try:
                    run = self._run_from_payload(payload)
                except TypeError:
                    continue
                existing = self.runs.get(run_id)
                if existing:
                    merged = vars(existing).copy()
                    merged.update(payload)
                    run = self._run_from_payload(merged)
                self.runs[run_id] = run
                self._manifests[run_id] = manifest
                self._loaded_sections.setdefault(run_id, set())
        return sorted(
            self.runs.values(),
            key=lambda r: r.created_at,
            reverse=True,
        )

    def list_run_summaries(self) -> list[dict[str, Any]]:
        """Return list-safe run data without materializing large sections."""
        rows = []
        for run in self.list_runs():
            manifest = self._manifests.get(run.run_id) or build_fbu_run_manifest(vars(run))
            rows.append(build_fbu_run_list_summary(manifest))
        return rows

    def delete_run(self, run_id: str) -> bool:
        """删除运行记录"""
        if self.get_run(run_id, sections=set()):
            del self.runs[run_id]
            self._manifests.pop(run_id, None)
            self._loaded_sections.pop(run_id, None)
            self._write_local_index()
            if fbu_persistent_storage_enabled():
                delete_fbu_run_from_persistent(run_id)
            return True
        return False

    def persist_files(self, run_id: str, relative_paths: list[str]) -> None:
        if fbu_persistent_storage_enabled():
            save_fbu_files_to_persistent(run_id, self.data_dir / run_id, relative_paths)

    def materialize_file(self, run_id: str, relative_path: str) -> Optional[Path]:
        target = self.data_dir / run_id / relative_path
        if target.is_file():
            return target
        if not fbu_persistent_storage_enabled():
            return None
        return load_fbu_file_from_persistent(run_id, self.data_dir / run_id, relative_path)

    def read_persisted_file(self, run_id: str, relative_path: str) -> bytes | None:
        """Read current durable bytes without overwriting a warm instance's local cache."""
        if fbu_persistent_storage_enabled():
            return read_fbu_file_from_persistent(run_id, relative_path)
        target = self.data_dir / run_id / relative_path
        return target.read_bytes() if target.is_file() else None

    def delete_persisted_files(self, run_id: str, relative_paths: list[str]) -> None:
        if fbu_persistent_storage_enabled():
            delete_fbu_files_from_persistent(run_id, relative_paths)

    def save_results(self, run_id: str, employees: list[EmployeeData]):
        """保存核算结果"""
        run = self.get_run(run_id, sections=set())
        if not run:
            return

        results = []
        total_bonus_by_source_employee: dict[str, float] = {}

        for emp in employees:
            results.append({
                "employee_id": emp.employee_id,
                "source_employee_id": emp.source_employee_id,
                "name": emp.name,
                "department": emp.department,
                "area": emp.area,
                "position": emp.position,
                "personnel_status": emp.personnel_status,
                "hire_date": emp.hire_date.isoformat() if emp.hire_date else "",
                "confirmation_date": emp.confirmation_date.isoformat() if emp.confirmation_date else "",
                "resignation_date": emp.resignation_date.isoformat() if emp.resignation_date else "",
                "job_type": emp.job_type,
                "fixed_performance_base": emp.fixed_performance_base,
                "base_override_amount": emp.base_override_amount,
                "base_override_type": emp.base_override_type,
                "base_override_reason": emp.base_override_reason,
                "work_hour_rule": emp.work_hour_rule,
                "work_hour_rule_cap": emp.work_hour_rule_cap,
                "work_hour_rule_include_holiday_in_cap": emp.work_hour_rule_include_holiday_in_cap,
                "work_hour_rule_special_total_hours": emp.work_hour_rule_special_total_hours,
                "work_hour_rule_rounded_hourly_rate": emp.work_hour_rule_rounded_hourly_rate,
                "calculation_path": get_calculation_path(emp),
                "hourly_rate": emp.hourly_rate,
                "performance_ratio": emp.performance_ratio,
                "base_hours": emp.base_hours,
                "ot15_hours": emp.ot15_hours,
                "ot20_hours": emp.ot20_hours,
                "sick_hours": emp.sick_hours,
                "sick_settlement_hours": emp.sick_settlement_hours,
                "annual_hours": emp.annual_hours,
                "holiday_hours": emp.holiday_hours,
                "is_night_shift": emp.is_night_shift,
                "attendance_daily_rows": emp.attendance_daily_rows,
                "work_hour_rule_periods": emp.work_hour_rule_periods,
                "performance_base": emp.performance_base,
                "system_performance_base": emp.system_performance_base or emp.performance_base,
                "period_adjustment": emp.period_adjustment,
                "period_adjustment_source_month": emp.period_adjustment_source_month,
                "period_adjustment_reason": emp.period_adjustment_reason,
                "performance_score": emp.performance_score,
                "performance_level": emp.performance_level,
                "uploaded_coefficient": emp.uploaded_coefficient,
                "coefficient_override_reason": emp.coefficient_override_reason,
                "performance_coefficient": emp.performance_coefficient,
                "performance_bonus": emp.performance_bonus,
                "is_deferred": emp.is_deferred,
                "deferred_reason": emp.deferred_reason,
                "calculation_segments": [
                    {
                        "period": segment.period,
                        "reason": segment.reason,
                        "performance_base": segment.performance_base,
                        "performance_ratio": segment.performance_ratio,
                        "performance_coefficient": segment.performance_coefficient,
                        "performance_bonus": segment.performance_bonus,
                        "department": segment.department,
                        "position": segment.position,
                        "job_type": segment.job_type,
                    }
                    for segment in emp.calculation_segments
                ],
                "base_calculation_details": [_build_base_calculation_detail(emp)],
                "exceptions": emp.exceptions,
            })
            total_key = emp.source_employee_id or emp.employee_id
            total_bonus_by_source_employee[total_key] = (
                total_bonus_by_source_employee.get(total_key, 0.0)
                + emp.performance_bonus
            )

        results_view_data = build_results_view_data(results)
        self.update_run(
            run_id,
            results=results,
            results_view_data=results_view_data,
            total_employees=len(results_view_data["rows"]),
            total_bonus=round(
                sum(round(amount, 2) for amount in total_bonus_by_source_employee.values()),
                2,
            ),
            status="completed",
        )

    def export_run(self, run_id: str, output_dir: str) -> Optional[str]:
        """导出运行结果到Excel"""
        run = self.get_run(run_id, sections={"results"})
        if not run or run.status != "completed":
            return None

        # 重建员工数据
        employees = []
        for r in run.results:
            emp = EmployeeData(
                employee_id=r["employee_id"],
                source_employee_id=r.get("source_employee_id", r["employee_id"]),
                name=r["name"],
                department=r.get("department", ""),
                area=r.get("area", ""),
                position=r.get("position", ""),
                personnel_status=r.get("personnel_status", ""),
                hire_date=_parse_saved_date(r.get("hire_date")),
                confirmation_date=_parse_saved_date(r.get("confirmation_date")),
                resignation_date=_parse_saved_date(r.get("resignation_date")),
                job_type=r["job_type"],
                fixed_performance_base=r.get("fixed_performance_base"),
                base_override_amount=r.get("base_override_amount"),
                base_override_type=r.get("base_override_type", ""),
                base_override_reason=r.get("base_override_reason", ""),
                work_hour_rule=r.get("work_hour_rule", ""),
                work_hour_rule_cap=r.get("work_hour_rule_cap", 0),
                work_hour_rule_include_holiday_in_cap=r.get("work_hour_rule_include_holiday_in_cap", False),
                work_hour_rule_special_total_hours=r.get("work_hour_rule_special_total_hours", 0),
                work_hour_rule_rounded_hourly_rate=r.get("work_hour_rule_rounded_hourly_rate", 0),
                hourly_rate=r["hourly_rate"],
                performance_ratio=r["performance_ratio"],
                base_hours=r["base_hours"],
                ot15_hours=r["ot15_hours"],
                ot20_hours=r["ot20_hours"],
                sick_hours=r["sick_hours"],
                sick_settlement_hours=r.get("sick_settlement_hours", 0),
                annual_hours=r["annual_hours"],
                holiday_hours=r["holiday_hours"],
                attendance_daily_rows=r.get("attendance_daily_rows", []),
                work_hour_rule_periods=r.get("work_hour_rule_periods", []),
                performance_base=r["performance_base"],
                system_performance_base=r.get("system_performance_base", r["performance_base"]),
                period_adjustment=r.get("period_adjustment", 0),
                period_adjustment_source_month=r.get("period_adjustment_source_month", ""),
                period_adjustment_reason=r.get("period_adjustment_reason", ""),
                performance_score=r["performance_score"],
                performance_level=r["performance_level"],
                uploaded_coefficient=r.get("uploaded_coefficient"),
                coefficient_override_reason=r.get("coefficient_override_reason", ""),
                performance_coefficient=r["performance_coefficient"],
                performance_bonus=r["performance_bonus"],
                is_deferred=r.get("is_deferred", False),
                deferred_reason=r.get("deferred_reason", ""),
                calculation_segments=[
                    CalculationSegment(
                        period=s.get("period", ""),
                        reason=s.get("reason", ""),
                        performance_base=s.get("performance_base", 0),
                        performance_ratio=s.get("performance_ratio", 0),
                        performance_coefficient=s.get("performance_coefficient", 0),
                        performance_bonus=s.get("performance_bonus", 0),
                        department=s.get("department", ""),
                        position=s.get("position", ""),
                        job_type=s.get("job_type", ""),
                    )
                    for s in r.get("calculation_segments", [])
                ],
                exceptions=r.get("exceptions", []),
            )
            employees.append(emp)

        # 导出
        exporter = FBUPerformanceExporter()
        output_path = Path(output_dir) / f"FBU绩效核算_{run.calc_month}_{run_id}.xlsx"

        summary = {
            "核算月份": run.calc_month,
            "员工总数": run.total_employees,
            "绩效奖金总额": f"${run.total_bonus:,.2f}",
            "匹配率": f"{run.match_rate:.1%}",
        }

        return exporter.export_to_excel(employees, str(output_path), summary)


class FBURosterStore:
    """FBU基础花名册存储。"""

    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.roster_dir = self.data_dir / "_roster"
        self.roster_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_file = self.roster_dir / "metadata.json"

    def _active_roster_path(self, metadata: Optional[dict] = None) -> Path:
        extension = (metadata or {}).get("extension", ".xlsx")
        if extension not in {".xlsx", ".xls"}:
            extension = ".xlsx"
        return self.roster_dir / f"active_roster{extension}"

    def get_metadata(self) -> dict:
        if fbu_persistent_storage_enabled():
            load_fbu_file_from_persistent("_roster", self.roster_dir, "metadata.json")
        if not self.metadata_file.exists():
            return {"has_roster": False}
        with open(self.metadata_file, "r", encoding="utf-8") as f:
            metadata = json.load(f)
        if fbu_persistent_storage_enabled():
            load_fbu_file_from_persistent(
                "_roster",
                self.roster_dir,
                self._active_roster_path(metadata).name,
            )
        metadata["has_roster"] = self._active_roster_path(metadata).exists()
        return metadata

    def save_active_roster(self, content: bytes, filename: str, total_employees: int = 0) -> dict:
        extension = Path(filename).suffix.lower()
        if extension not in {".xlsx", ".xls"}:
            extension = ".xlsx"
        for existing in self.roster_dir.glob("active_roster.*"):
            existing.unlink(missing_ok=True)
        active_roster = self._active_roster_path({"extension": extension})
        active_roster.write_bytes(content)
        metadata = {
            "has_roster": True,
            "filename": filename,
            "extension": extension,
            "uploaded_at": datetime.now().isoformat(),
            "total_employees": total_employees,
        }
        with open(self.metadata_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        if fbu_persistent_storage_enabled():
            save_fbu_files_to_persistent(
                "_roster",
                self.roster_dir,
                ["metadata.json", active_roster.name],
            )
        return metadata

    def copy_active_to_run(self, run_id: str, metadata: Optional[dict] = None) -> Optional[Path]:
        metadata = metadata or self.get_metadata()
        active_roster = self._active_roster_path(metadata)
        if not active_roster.exists():
            return None
        run_dir = self.data_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        target = run_dir / f"roster{metadata.get('extension', '.xlsx')}"
        shutil.copyfile(active_roster, target)
        if fbu_persistent_storage_enabled():
            save_fbu_files_to_persistent(run_id, run_dir, [target.name])
        return target


DEFAULT_WORK_HOUR_EMPLOYEES = [
    {"employee_id": "zt12979", "name": "赵婉妍", "active": True},
    {"employee_id": "zt12988", "name": "陈海冰", "active": True},
    {"employee_id": "zt14260", "name": "陈炜", "active": True},
    {"employee_id": "zt17850", "name": "韩勇", "active": True},
]

DEFAULT_FIXED_BASE_EMPLOYEES = [
    {
        "employee_id": "zt15638",
        "name": "万其鑫",
        "fixed_performance_base": 3000,
        "active": True,
    },
]


class FBURuleListStore:
    """Stores stable FBU 96-hour and fixed-base lists outside monthly uploads."""

    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.settings_dir = self.data_dir / "_settings"
        self.settings_dir.mkdir(parents=True, exist_ok=True)
        self.rule_lists_file = self.settings_dir / "rule_lists.json"

    def _default_payload(self) -> dict:
        return {
            "work_hour_employees": list(DEFAULT_WORK_HOUR_EMPLOYEES),
            "fixed_base_employees": list(DEFAULT_FIXED_BASE_EMPLOYEES),
        }

    def _with_seed_rows(self, payload: dict) -> dict:
        defaults = self._default_payload()
        work_hour_employees = payload.get("work_hour_employees") or defaults["work_hour_employees"]
        fixed_base_employees = payload.get("fixed_base_employees") or defaults["fixed_base_employees"]
        return {
            "work_hour_employees": work_hour_employees,
            "fixed_base_employees": fixed_base_employees,
        }

    def get(self) -> dict:
        if fbu_persistent_storage_enabled():
            load_fbu_file_from_persistent("_settings", self.settings_dir, "rule_lists.json")
        if not self.rule_lists_file.exists():
            return self._default_payload()
        with open(self.rule_lists_file, "r", encoding="utf-8") as f:
            payload = json.load(f)
        return self._with_seed_rows(payload)

    def save(self, payload: dict) -> dict:
        normalized = self._with_seed_rows({
            "work_hour_employees": self._normalize_work_hour_rows(payload.get("work_hour_employees", [])),
            "fixed_base_employees": self._normalize_fixed_base_rows(payload.get("fixed_base_employees", [])),
        })
        with open(self.rule_lists_file, "w", encoding="utf-8") as f:
            json.dump(normalized, f, ensure_ascii=False, indent=2)
        if fbu_persistent_storage_enabled():
            save_fbu_files_to_persistent(
                "_settings",
                self.settings_dir,
                ["rule_lists.json"],
            )
        return normalized

    def _normalize_work_hour_rows(self, rows: list[dict]) -> list[dict]:
        result = []
        for row in rows:
            employee_id = str(row.get("employee_id") or "").strip()
            if not employee_id:
                continue
            result.append({
                "employee_id": employee_id,
                "name": str(row.get("name") or "").strip(),
                "active": bool(row.get("active", True)),
            })
        return result

    def _normalize_fixed_base_rows(self, rows: list[dict]) -> list[dict]:
        result = []
        for row in rows:
            employee_id = str(row.get("employee_id") or "").strip()
            if not employee_id:
                continue
            fixed_performance_base = row.get("fixed_performance_base")
            if fixed_performance_base in (None, ""):
                normalized_fixed_base = 0.0
            else:
                try:
                    normalized_fixed_base = float(fixed_performance_base)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"{employee_id} 的固定绩效基数必须是数字") from exc
            result.append({
                "employee_id": employee_id,
                "name": str(row.get("name") or "").strip(),
                "fixed_performance_base": normalized_fixed_base,
                "active": bool(row.get("active", True)),
            })
        return result
