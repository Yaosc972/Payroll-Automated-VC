"""FBU绩效核算引擎 - 运行管理"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional
from pathlib import Path
import shutil
import json
import uuid

from .engines.base import CalculationSegment, EmployeeData, get_calculation_path
from .exporter import FBUPerformanceExporter
from .persistent_storage import (
    delete_fbu_run_from_persistent,
    fbu_persistent_storage_enabled,
    list_fbu_run_metadata_from_persistent,
    load_fbu_file_from_persistent,
    load_fbu_run_metadata_from_persistent,
    save_fbu_files_to_persistent,
    save_fbu_run_metadata_to_persistent,
)


_FINAL_RESULT_SUM_FIELDS = {
    "base_hours",
    "ot15_hours",
    "ot20_hours",
    "sick_hours",
    "sick_settlement_hours",
    "annual_hours",
    "holiday_hours",
    "performance_base",
    "performance_bonus",
}
_FINAL_RESULT_MONEY_FIELDS = {"performance_base", "performance_bonus"}


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
            total += float(row.get(field) or 0)
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
        return list(rows[0].get("calculation_segments") or [])

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
        final_row["calculation_segments"] = _build_final_calculation_segments(rows, source_employee_id)
        final_rows.append(final_row)

    return final_rows


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
    supplemental_leave_file: str = ""
    base_override_file: str = ""
    roster_file: str = ""
    roster_source: str = ""  # activity / base
    roster_data: dict = field(default_factory=dict)
    # 分步数据
    attendance_data: dict = field(default_factory=dict)  # 考勤解析结果
    salary_data: dict = field(default_factory=dict)  # 薪资解析结果
    previous_salary_data: dict = field(default_factory=dict)
    current_salary_data: dict = field(default_factory=dict)
    salary_verification_data: dict = field(default_factory=dict)
    performance_data: dict = field(default_factory=dict)  # 绩效解析结果
    adjustment_data: dict = field(default_factory=dict)  # 调薪/转正拆分解析结果
    supplemental_leave_data: dict = field(default_factory=dict)  # sickpay&年假补充确认
    base_override_data: dict = field(default_factory=dict)  # 96工时制/线下固定基数覆盖
    # 最终结果
    total_employees: int = 0
    total_bonus: float = 0.0
    match_rate: float = 0.0
    results: list[dict] = field(default_factory=list)
    error: str = ""


class FBURunManager:
    """FBU运行管理器"""

    RESULT_INPUT_FIELDS = {
        "attendance_file", "previous_attendance_file", "salary_file",
        "previous_salary_file", "current_salary_file", "performance_file",
        "adjustment_file", "supplemental_leave_file", "base_override_file",
        "attendance_data", "salary_data",
        "previous_salary_data", "current_salary_data", "salary_verification_data",
        "performance_data", "adjustment_data", "supplemental_leave_data",
        "base_override_data",
    }

    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.runs: dict[str, FBURun] = {}
        self._load_runs()

    def _load_runs(self):
        """加载历史运行记录"""
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
                run = FBURun(**run_data)
            except TypeError:
                continue
            self.runs[run.run_id] = run

    def _quarantine_corrupt_runs_file(self, runs_file: Path):
        suffix = datetime.now().strftime("%Y%m%d%H%M%S")
        quarantine_path = runs_file.with_name(f"runs.corrupt-{suffix}.json")
        try:
            runs_file.replace(quarantine_path)
        except OSError:
            pass

    def _save_runs(self, changed_run_id: str | None = None):
        """保存运行记录"""
        runs_file = self.data_dir / "runs.json"
        with open(runs_file, "w", encoding="utf-8") as f:
            json.dump(
                [vars(run) for run in self.runs.values()],
                f,
                ensure_ascii=False,
                indent=2,
            )
        if fbu_persistent_storage_enabled() and changed_run_id:
            run = self.runs.get(changed_run_id)
            if run:
                save_fbu_run_metadata_to_persistent(changed_run_id, vars(run))

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
        if persist:
            self._save_runs(run.run_id)
        return run

    def update_run(self, run_id: str, **kwargs):
        """更新运行状态"""
        run = self.runs.get(run_id) or self.get_run(run_id)
        if run:
            if self.RESULT_INPUT_FIELDS.intersection(kwargs):
                self._invalidate_results(run)
            for key, value in kwargs.items():
                setattr(run, key, value)
            self.runs[run_id] = run
            self._save_runs(run_id)

    @staticmethod
    def _invalidate_results(run: FBURun):
        run.results = []
        run.total_employees = 0
        run.total_bonus = 0.0
        run.match_rate = 0.0

    def save_step_data(self, run_id: str, step: int, data: dict, **updates):
        """保存分步数据"""
        run = self.runs.get(run_id) or self.get_run(run_id)
        if not run:
            return

        self._invalidate_results(run)
        for key, value in updates.items():
            setattr(run, key, value)

        if step == 1:
            run.attendance_data = data
            run.current_step = 1
            run.status = "step1"
        elif step == 2:
            run.salary_data = data
            run.current_step = 2
            run.status = "step2"
        elif step == 3:
            run.performance_data = data
            run.current_step = 3
            run.status = "step3"
        elif step == 4:
            run.adjustment_data = data

        self.runs[run_id] = run
        self._save_runs(run_id)

    def get_run(self, run_id: str) -> Optional[FBURun]:
        """获取运行记录"""
        if fbu_persistent_storage_enabled():
            payload = load_fbu_run_metadata_from_persistent(run_id)
            if payload:
                try:
                    self.runs[run_id] = FBURun(**payload)
                except TypeError:
                    return None
        return self.runs.get(run_id)

    def list_runs(self) -> list[FBURun]:
        """获取所有运行记录"""
        if fbu_persistent_storage_enabled():
            restored: dict[str, FBURun] = {}
            for payload in list_fbu_run_metadata_from_persistent():
                try:
                    run = FBURun(**payload)
                except TypeError:
                    continue
                restored[run.run_id] = run
            self.runs = restored
        return sorted(
            self.runs.values(),
            key=lambda r: r.created_at,
            reverse=True,
        )

    def delete_run(self, run_id: str) -> bool:
        """删除运行记录"""
        if self.get_run(run_id):
            del self.runs[run_id]
            self._save_runs()
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

    def save_results(self, run_id: str, employees: list[EmployeeData]):
        """保存核算结果"""
        run = self.runs.get(run_id) or self.get_run(run_id)
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
                "attendance_daily_rows": emp.attendance_daily_rows,
                "work_hour_rule_periods": emp.work_hour_rule_periods,
                "performance_base": emp.performance_base,
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
                    }
                    for segment in emp.calculation_segments
                ],
                "exceptions": emp.exceptions,
            })
            total_key = emp.source_employee_id or emp.employee_id
            total_bonus_by_source_employee[total_key] = (
                total_bonus_by_source_employee.get(total_key, 0.0)
                + emp.performance_bonus
            )

        self.update_run(
            run_id,
            results=results,
            total_employees=len(build_final_result_rows(results)),
            total_bonus=round(
                sum(round(amount, 2) for amount in total_bonus_by_source_employee.values()),
                2,
            ),
            status="completed",
        )

    def export_run(self, run_id: str, output_dir: str) -> Optional[str]:
        """导出运行结果到Excel"""
        run = self.get_run(run_id)
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
