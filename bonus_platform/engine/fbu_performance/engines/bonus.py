"""FBU绩效核算引擎 - 绩效奖金计算"""
from __future__ import annotations
from .base import EmployeeData
from .coefficient import CoefficientCalculator


class BonusCalculator:
    """绩效奖金计算器"""

    @staticmethod
    def calc_performance_base(emp: EmployeeData) -> float:
        """
        计算绩效基数

        绩效基数 = 基础工资 + OT1.5工资 + OT2.0工资 + 病假工资 + 年假补贴 + 节日补贴
        """
        if emp.job_type == "district_manager" and emp.fixed_performance_base:
            emp.performance_base = emp.fixed_performance_base
            return emp.performance_base

        # 基础工资
        emp.base_salary = emp.base_hours * emp.hourly_rate

        # OT1.5工资
        emp.ot15_salary = emp.ot15_hours * emp.hourly_rate * 1.5

        # OT2.0工资
        emp.ot20_salary = emp.ot20_hours * emp.hourly_rate * 2.0

        # 病假工资
        emp.sick_pay = emp.sick_hours * emp.hourly_rate

        # 年假补贴
        emp.annual_leave_pay = emp.annual_hours * emp.hourly_rate

        # 节日补贴
        emp.holiday_pay = emp.holiday_hours * emp.hourly_rate

        # 绩效基数
        emp.performance_base = (
            emp.base_salary
            + emp.ot15_salary
            + emp.ot20_salary
            + emp.sick_pay
            + emp.annual_leave_pay
            + emp.holiday_pay
        )

        return emp.performance_base

    @staticmethod
    def calc_bonus(emp: EmployeeData) -> float:
        """
        计算绩效奖金

        绩效奖金 = 绩效基数 × 绩效比例 × 绩效系数
        """
        if emp.calculation_segments:
            total_bonus = 0.0
            active_segments = []
            for segment in emp.calculation_segments:
                segment.performance_bonus = (
                    segment.performance_base
                    * segment.performance_ratio
                    * segment.performance_coefficient
                )
                total_bonus += segment.performance_bonus
                if segment.performance_ratio > 0:
                    active_segments.append(segment)

            if active_segments:
                emp.performance_base = sum(segment.performance_base for segment in active_segments)
                emp.performance_ratio = active_segments[-1].performance_ratio
                emp.performance_coefficient = active_segments[-1].performance_coefficient
            else:
                emp.performance_base = 0.0
            emp.performance_bonus = total_bonus
            return emp.performance_bonus

        if emp.job_type == "district_manager" and emp.fixed_performance_base:
            emp.performance_bonus = emp.performance_base * emp.performance_coefficient
            return emp.performance_bonus

        emp.performance_bonus = (
            emp.performance_base
            * emp.performance_ratio
            * emp.performance_coefficient
        )
        return emp.performance_bonus

    @classmethod
    def calculate(cls, emp: EmployeeData) -> EmployeeData:
        """
        完整计算流程

        1. 计算绩效基数
        2. 计算绩效系数
        3. 计算绩效奖金
        """
        # 1. 计算绩效基数
        cls.calc_performance_base(emp)

        # 2. 计算绩效系数
        if emp.job_type == "district_manager" and emp.uploaded_coefficient is not None:
            emp.performance_coefficient = emp.uploaded_coefficient
        else:
            emp.performance_coefficient = CoefficientCalculator.calculate(
                job_type=emp.job_type,
                score=emp.performance_score,
                level=emp.performance_level,
            )
        if (
            emp.uploaded_coefficient is not None
            and round(emp.uploaded_coefficient, 2) != round(emp.performance_coefficient, 2)
        ):
            emp.exceptions.append(
                f"上传绩效系数与系统计算系数不一致: 上传={emp.uploaded_coefficient:.2f}, 系统={emp.performance_coefficient:.2f}"
            )

        # 3. 计算绩效奖金
        cls.calc_bonus(emp)

        return emp
