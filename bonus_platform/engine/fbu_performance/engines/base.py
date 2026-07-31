"""FBU绩效核算引擎 - 基础引擎类"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from typing import Optional


DISTRICT_MANAGER_FIXED_BASE_PATH = "区长固定基数路径"
FIXED_BASE_OVERRIDE_PATH = "线下固定基数覆盖路径"
NINETY_SIX_HOUR_FIXED_BASE_PATH = "96工时制固定基数覆盖路径"
NINETY_SIX_HOUR_AUTO_BASE_PATH = "96工时制自动基数路径"
ADJUSTMENT_SPLIT_PATH = "调薪/转正拆分路径"
TRANSFER_SPLIT_PATH = "岗位调动生效日拆分路径"
STANDARD_PERFORMANCE_BASE_PATH = "标准绩效基数路径"


@dataclass
class CalculationSegment:
    """绩效奖金核算拆分段。"""
    period: str
    reason: str
    performance_base: float
    performance_ratio: float
    performance_coefficient: float
    performance_bonus: float = 0.0
    department: str = ""
    position: str = ""
    job_type: str = ""


@dataclass
class EmployeeData:
    """员工数据模型"""
    employee_id: str
    name: str
    source_employee_id: str = ""
    department: str = ""
    area: str = ""
    position: str = ""
    personnel_status: str = ""
    hire_date: Optional[date] = None
    confirmation_date: Optional[date] = None
    resignation_date: Optional[date] = None
    hourly_rate: float = 0.0
    performance_ratio: float = 0.0
    performance_score: Optional[float] = None
    performance_level: Optional[str] = None
    uploaded_coefficient: Optional[float] = None
    coefficient_override_reason: str = ""
    job_type: str = "warehouse"  # warehouse / functional / district_manager
    fixed_performance_base: Optional[float] = None
    base_override_amount: Optional[float] = None
    base_override_type: str = ""
    base_override_reason: str = ""
    work_hour_rule: str = ""
    work_hour_rule_cap: float = 0.0
    work_hour_rule_include_holiday_in_cap: bool = False
    work_hour_rule_special_total_hours: float = 0.0
    work_hour_rule_rounded_hourly_rate: float = 0.0

    # 考勤数据
    base_hours: float = 0.0      # 计薪出勤时长
    ot15_hours: float = 0.0      # OT1.5时长
    ot20_hours: float = 0.0      # OT2.0时长
    sick_hours: float = 0.0      # 病假时长
    sick_settlement_hours: float = 0.0  # 病假清算时长
    annual_hours: float = 0.0    # 年假时长
    holiday_hours: float = 0.0   # 节假日时长
    is_night_shift: bool = False
    attendance_daily_rows: list[dict] = field(default_factory=list)
    work_hour_rule_periods: list[dict] = field(default_factory=list)

    # 计算结果
    base_salary: float = 0.0
    ot15_salary: float = 0.0
    ot20_salary: float = 0.0
    sick_pay: float = 0.0
    sick_settlement_pay: float = 0.0
    annual_leave_pay: float = 0.0
    holiday_pay: float = 0.0
    performance_base: float = 0.0
    system_performance_base: float = 0.0
    period_adjustment: float = 0.0
    period_adjustment_source_month: str = ""
    period_adjustment_reason: str = ""
    performance_coefficient: float = 0.0
    performance_bonus: float = 0.0
    is_deferred: bool = False
    deferred_reason: str = ""
    calculation_segments: list[CalculationSegment] = field(default_factory=list)
    exceptions: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.source_employee_id:
            self.source_employee_id = self.employee_id

    @property
    def calculation_path(self) -> str:
        return get_calculation_path(self)


def get_calculation_path(emp: EmployeeData) -> str:
    """Return the business calculation path used for audit/export."""
    if emp.job_type == "district_manager" and emp.fixed_performance_base:
        return DISTRICT_MANAGER_FIXED_BASE_PATH
    if emp.base_override_amount:
        if "96" in str(emp.base_override_type):
            return NINETY_SIX_HOUR_FIXED_BASE_PATH
        return FIXED_BASE_OVERRIDE_PATH
    if "96" in str(emp.work_hour_rule or ""):
        return NINETY_SIX_HOUR_AUTO_BASE_PATH
    if any(segment.position for segment in emp.calculation_segments):
        return TRANSFER_SPLIT_PATH
    if emp.calculation_segments:
        return ADJUSTMENT_SPLIT_PATH
    return STANDARD_PERFORMANCE_BASE_PATH


class FBUPerformanceEngine:
    """FBU绩效核算引擎基类"""

    def __init__(self):
        self.employees: dict[str, EmployeeData] = {}

    def add_employee(self, emp: EmployeeData):
        """添加员工数据"""
        self.employees[emp.employee_id] = emp

    def get_employee(self, employee_id: str) -> Optional[EmployeeData]:
        """获取员工数据"""
        return self.employees.get(employee_id)

    def get_all_employees(self) -> list[EmployeeData]:
        """获取所有员工"""
        return list(self.employees.values())
