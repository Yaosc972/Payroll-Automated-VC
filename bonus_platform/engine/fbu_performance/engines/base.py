"""FBU绩效核算引擎 - 基础引擎类"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CalculationSegment:
    """绩效奖金核算拆分段。"""
    period: str
    reason: str
    performance_base: float
    performance_ratio: float
    performance_coefficient: float
    performance_bonus: float = 0.0


@dataclass
class EmployeeData:
    """员工数据模型"""
    employee_id: str
    name: str
    source_employee_id: str = ""
    department: str = ""
    area: str = ""
    hourly_rate: float = 0.0
    performance_ratio: float = 0.0
    performance_score: Optional[float] = None
    performance_level: Optional[str] = None
    uploaded_coefficient: Optional[float] = None
    job_type: str = "warehouse"  # warehouse / functional / district_manager
    fixed_performance_base: Optional[float] = None

    # 考勤数据
    base_hours: float = 0.0      # 计薪出勤时长
    ot15_hours: float = 0.0      # OT1.5时长
    ot20_hours: float = 0.0      # OT2.0时长
    sick_hours: float = 0.0      # 病假时长
    annual_hours: float = 0.0    # 年假时长
    holiday_hours: float = 0.0   # 节假日时长
    is_night_shift: bool = False

    # 计算结果
    base_salary: float = 0.0
    ot15_salary: float = 0.0
    ot20_salary: float = 0.0
    sick_pay: float = 0.0
    annual_leave_pay: float = 0.0
    holiday_pay: float = 0.0
    performance_base: float = 0.0
    performance_coefficient: float = 0.0
    performance_bonus: float = 0.0
    calculation_segments: list[CalculationSegment] = field(default_factory=list)
    exceptions: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.source_employee_id:
            self.source_employee_id = self.employee_id


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
