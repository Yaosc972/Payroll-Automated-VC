"""FBU绩效核算引擎 - 绩效奖金计算"""
from __future__ import annotations
from .base import EmployeeData
from .coefficient import CoefficientCalculator


NINETY_SIX_HOUR_HOLIDAY_INCLUSIVE_IDS = {"zt12979"}


def _safe_number(value) -> float:
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


class BonusCalculator:
    """绩效奖金计算器"""

    @staticmethod
    def _calc_96_hour_base(emp: EmployeeData) -> float:
        rule_hourly_rate = max(emp.hourly_rate - 1, 0) if emp.is_night_shift else emp.hourly_rate
        if emp.work_hour_rule_special_total_hours:
            rounded_rate = round(rule_hourly_rate, 2)
            emp.work_hour_rule_rounded_hourly_rate = rounded_rate
            emp.base_salary = rounded_rate * emp.work_hour_rule_special_total_hours
            emp.ot15_salary = 0
            emp.ot20_salary = 0
            emp.sick_pay = 0
            emp.sick_settlement_pay = 0
            emp.annual_leave_pay = 0
            emp.holiday_pay = 0
            emp.performance_base = emp.base_salary
            return emp.performance_base

        include_holiday_in_cap = (
            emp.work_hour_rule_include_holiday_in_cap
            or emp.employee_id in NINETY_SIX_HOUR_HOLIDAY_INCLUSIVE_IDS
            or emp.source_employee_id in NINETY_SIX_HOUR_HOLIDAY_INCLUSIVE_IDS
        )

        if emp.work_hour_rule_periods:
            base_salary = 0.0
            holiday_pay = 0.0
            for period in emp.work_hour_rule_periods:
                straight_hours = (
                    _safe_number(period.get("base_hours"))
                    + _safe_number(period.get("ot15_hours"))
                    + _safe_number(period.get("ot20_hours"))
                    + _safe_number(period.get("sick_hours"))
                    + _safe_number(period.get("sick_settlement_hours"))
                    + _safe_number(period.get("annual_hours"))
                )
                holiday_hours = _safe_number(period.get("holiday_hours"))
                cap_hours = _safe_number(period.get("cap_hours")) or (straight_hours + holiday_hours)
                if include_holiday_in_cap:
                    capped_hours = min(straight_hours + holiday_hours, cap_hours)
                    extra_holiday_hours = 0.0
                else:
                    capped_hours = min(straight_hours, cap_hours)
                    extra_holiday_hours = holiday_hours

                period_base_salary = capped_hours * rule_hourly_rate
                period_holiday_pay = extra_holiday_hours * rule_hourly_rate
                period["straight_hours"] = round(straight_hours, 2)
                period["capped_hours"] = round(capped_hours, 2)
                period["extra_holiday_hours"] = round(extra_holiday_hours, 2)
                period["included_hours"] = round(capped_hours + extra_holiday_hours, 2)
                period["performance_base"] = round(period_base_salary + period_holiday_pay, 2)
                base_salary += period_base_salary
                holiday_pay += period_holiday_pay

            emp.base_salary = base_salary
            emp.ot15_salary = 0
            emp.ot20_salary = 0
            emp.sick_pay = 0
            emp.sick_settlement_pay = 0
            emp.annual_leave_pay = 0
            emp.holiday_pay = holiday_pay
            emp.performance_base = emp.base_salary + emp.holiday_pay
            return emp.performance_base

        straight_hours = (
            emp.base_hours
            + emp.ot15_hours
            + emp.ot20_hours
            + emp.sick_hours
            + emp.sick_settlement_hours
            + emp.annual_hours
        )
        cap_hours = emp.work_hour_rule_cap or (straight_hours + emp.holiday_hours)
        if include_holiday_in_cap:
            capped_hours = min(straight_hours + emp.holiday_hours, cap_hours)
            extra_holiday_hours = 0
        else:
            capped_hours = min(straight_hours, cap_hours)
            extra_holiday_hours = emp.holiday_hours

        emp.base_salary = capped_hours * rule_hourly_rate
        emp.ot15_salary = 0
        emp.ot20_salary = 0
        emp.sick_pay = 0
        emp.sick_settlement_pay = 0
        emp.annual_leave_pay = 0
        emp.holiday_pay = extra_holiday_hours * rule_hourly_rate
        emp.performance_base = emp.base_salary + emp.holiday_pay
        return emp.performance_base

    @staticmethod
    def calc_performance_base(emp: EmployeeData) -> float:
        """
        计算绩效基数

        绩效基数 = 基础工资 + OT1.5工资 + OT2.0工资 + 病假工资 + 病假清算 + 年假补贴 + 节日补贴
        """
        if emp.job_type == "district_manager" and emp.fixed_performance_base:
            emp.performance_base = emp.fixed_performance_base
            return emp.performance_base

        if "96" in str(emp.work_hour_rule or "") and not emp.base_override_amount:
            return BonusCalculator._calc_96_hour_base(emp)

        # 基础工资
        emp.base_salary = emp.base_hours * emp.hourly_rate

        # OT1.5工资
        emp.ot15_salary = emp.ot15_hours * emp.hourly_rate * 1.5

        # OT2.0工资
        emp.ot20_salary = emp.ot20_hours * emp.hourly_rate * 2.0

        # 病假工资
        emp.sick_pay = emp.sick_hours * emp.hourly_rate

        # 病假清算
        emp.sick_settlement_pay = emp.sick_settlement_hours * emp.hourly_rate

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
            + emp.sick_settlement_pay
            + emp.annual_leave_pay
            + emp.holiday_pay
        )
        if emp.base_override_amount:
            emp.performance_base = emp.base_override_amount

        return emp.performance_base

    @staticmethod
    def calc_bonus(emp: EmployeeData) -> float:
        """
        计算绩效奖金

        绩效奖金 = 绩效基数 × 绩效比例 × 绩效系数
        """
        if emp.calculation_segments:
            total_bonus = 0.0
            active_base = 0.0
            active_segments = []
            for segment in emp.calculation_segments:
                segment.performance_bonus = (
                    segment.performance_base
                    * segment.performance_ratio
                    * segment.performance_coefficient
                )
                total_bonus += segment.performance_bonus
                if segment.performance_ratio > 0:
                    active_base += segment.performance_base
                    active_segments.append(segment)

            if active_segments:
                emp.performance_ratio = active_segments[-1].performance_ratio
                emp.performance_coefficient = active_segments[-1].performance_coefficient
            emp.performance_base = active_base
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
        if emp.coefficient_override_reason and emp.uploaded_coefficient is not None:
            emp.performance_coefficient = emp.uploaded_coefficient
        elif emp.job_type == "district_manager" and emp.uploaded_coefficient is not None:
            emp.performance_coefficient = emp.uploaded_coefficient
        elif (
            emp.uploaded_coefficient is not None
            and emp.performance_score is None
            and not emp.performance_level
        ):
            emp.performance_coefficient = emp.uploaded_coefficient
        else:
            emp.performance_coefficient = CoefficientCalculator.calculate(
                job_type=emp.job_type,
                score=emp.performance_score,
                level=emp.performance_level,
            )
            if (
                emp.performance_score is None
                and not emp.performance_level
                and emp.performance_coefficient == 0
                and not emp.coefficient_override_reason
                and not emp.calculation_segments
                and emp.job_type != "district_manager"
            ):
                emp.is_deferred = True
                emp.deferred_reason = "OEHR绩效结果尚未出，延期发放"
                emp.exceptions.append(emp.deferred_reason)
        if (
            emp.uploaded_coefficient is not None
            and not emp.coefficient_override_reason
            and round(emp.uploaded_coefficient, 2) != round(emp.performance_coefficient, 2)
        ):
            emp.exceptions.append(
                f"上传绩效系数与系统计算系数不一致: 上传={emp.uploaded_coefficient:.2f}, 系统={emp.performance_coefficient:.2f}"
            )

        # 3. 计算绩效奖金
        if emp.is_deferred:
            emp.performance_bonus = 0.0
            return emp
        cls.calc_bonus(emp)

        return emp
