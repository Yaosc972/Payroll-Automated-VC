"""外宿补贴计算引擎 (External Housing Subsidy Engine)."""
import calendar
from datetime import date, datetime
from typing import Any, Dict, List, Optional
from .base import BaseEngine, CalculationResult


def _to_date(val):
    """将datetime/date/str统一转为date对象。"""
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    return val


class WaiSuBuTieEngine(BaseEngine):
    """外宿补贴计算引擎"""

    def __init__(self, subsidy_standard: float = 150.0):
        self.subsidy_standard = subsidy_standard

    def calculate(
        self,
        employee_data: Dict[str, Any],
        daily_attendance: List[Dict[str, Any]] = None,
        housing_records: List[Dict[str, Any]] = None,
    ) -> CalculationResult:
        """计算单个员工的外宿补贴

        Args:
            employee_data: 月考勤数据 (Sheet2)
            daily_attendance: 日考勤数据 (Sheet1)
            housing_records: 住宿名单 (Sheet3)
        """
        employee_id = str(employee_data.get("工号", ""))
        employee_name = str(employee_data.get("姓名", ""))
        warnings = []

        # 考勤月份
        attendance_month = str(employee_data.get("考勤月份", ""))
        if len(attendance_month) != 6:
            return CalculationResult(
                employee_id=employee_id,
                employee_name=employee_name,
                amount=0,
                details={"reason": "考勤月份格式异常"},
                warnings=[f"考勤月份格式异常: {attendance_month}"]
            )

        month_start, month_end, days_in_month = self.get_month_range(attendance_month)

        # F1: 全月未出勤标记
        if daily_attendance:
            has_attendance = any(
                day.get("上班一") or day.get("下班一")
                for day in daily_attendance
                if str(day.get("工号", "")) == employee_id
            )
            if not has_attendance:
                return CalculationResult(
                    employee_id=employee_id,
                    employee_name=employee_name,
                    amount=0,
                    details={"reason": "全月未出勤"},
                    warnings=[f"员工{employee_id}全月未出勤"]
                )
        else:
            warnings.append(f"员工{employee_id}无日考勤数据")

        # F2: 补贴资格判断
        subsidy_standard = employee_data.get("外宿补贴标准")
        if str(subsidy_standard) in ["/", ""] or subsidy_standard is None:
            return CalculationResult(
                employee_id=employee_id,
                employee_name=employee_name,
                amount=0,
                details={"reason": "无补贴资格"},
                warnings=[]
            )

        # F3: 当月在职范围
        hire_date = employee_data.get("入职日期")
        last_work_day = employee_data.get("最后工作日")

        if isinstance(hire_date, (date, datetime)):
            employment_start = max(_to_date(hire_date), month_start)
        else:
            employment_start = month_start

        if last_work_day is None or last_work_day == "" or last_work_day == "None":
            employment_end = month_end
            # 全月在职 = 入职日期 < 月初日期 且 最后工作日为空
            if isinstance(hire_date, (date, datetime)) and _to_date(hire_date) < month_start:
                is_full_month = True
            else:
                is_full_month = False
        elif isinstance(last_work_day, (date, datetime)):
            employment_end = min(_to_date(last_work_day), month_end)
            is_full_month = False
        else:
            employment_end = month_end
            is_full_month = False

        days_employed = (employment_end - employment_start).days + 1
        if days_employed <= 0:
            return CalculationResult(
                employee_id=employee_id,
                employee_name=employee_name,
                amount=0,
                details={"reason": "在职日期异常"},
                warnings=[f"员工{employee_id}在职日期异常"]
            )

        # F4-F5: 住宿名单匹配和住宿扣除天数
        housing_deduction_days = 0
        if housing_records:
            for record in housing_records:
                if str(record.get("工号", "")) == employee_id:
                    check_in = record.get("入住时间")
                    check_out = record.get("退宿时间")

                    if isinstance(check_in, (date, datetime)):
                        housing_start = max(_to_date(check_in), month_start)
                    else:
                        continue

                    if check_out is None or check_out == "" or not isinstance(check_out, (date, datetime)):
                        housing_end = month_end
                    elif isinstance(check_out, (date, datetime)):
                        co = _to_date(check_out)
                        if co <= month_end:
                            housing_end = co - date.resolution
                        else:
                            housing_end = month_end
                    else:
                        housing_end = month_end

                    overlap_start = max(employment_start, housing_start)
                    overlap_end = min(employment_end, housing_end)
                    housing_deduction_days = max(0, (overlap_end - overlap_start).days + 1)
                    break

        # F6: 外宿补贴天数
        subsidy_days = max(0, days_employed - housing_deduction_days)

        # F7: 缺勤时数合计（仅全月在职员工）
        absence_hours = 0
        if is_full_month:
            absence_hours = (
                float(employee_data.get("事假时数", 0) or 0)
                + float(employee_data.get("排休请假时数", 0) or 0)
                + float(employee_data.get("病假时数", 0) or 0)
                + float(employee_data.get("旷工时数", 0) or 0)
                + float(employee_data.get("入离职缺勤时数", 0) or 0)
            )

        # F8: 外宿补贴
        # 缺勤≥56小时的有效天数公式仅适用于无住宿扣除的全月在职员工；
        # 有住宿扣除的员工已通过subsidy_days扣减，不再重复扣减缺勤
        if is_full_month and absence_hours >= 56 and housing_deduction_days == 0:
            effective_days = days_in_month - absence_hours / 8
            subsidy_amount = round(self.subsidy_standard / days_in_month * effective_days, 2)
        else:
            subsidy_amount = round(self.subsidy_standard / days_in_month * subsidy_days, 2)

        if subsidy_amount < 0:
            subsidy_amount = 0
            warnings.append(f"员工{employee_id}补贴天数为负，请人工复核")

        return CalculationResult(
            employee_id=employee_id,
            employee_name=employee_name,
            amount=subsidy_amount,
            details={
                "在职天数": days_employed,
                "住宿扣除天数": housing_deduction_days,
                "外宿补贴天数": subsidy_days,
                "缺勤时数": absence_hours,
                "全月在职": is_full_month,
                "补贴标准": self.subsidy_standard,
            },
            warnings=warnings
        )

    def calculate_batch(
        self,
        employees: List[Dict[str, Any]],
        daily_data: Dict[str, List[Dict[str, Any]]] = None,
        housing_data: Dict[str, List[Dict[str, Any]]] = None,
    ) -> List[CalculationResult]:
        """批量计算外宿补贴"""
        results = []
        for emp in employees:
            employee_id = str(emp.get("工号", ""))
            daily = daily_data.get(employee_id, []) if daily_data else []
            housing = housing_data.get(employee_id, []) if housing_data else []
            result = self.calculate(emp, daily, housing)
            results.append(result)
        return results

    def verify(self, results: List[CalculationResult]) -> Dict[str, Any]:
        """验证计算结果"""
        total = len(results)
        has_subsidy = sum(1 for r in results if r.amount > 0)
        total_amount = sum(r.amount for r in results)
        all_warnings = [w for r in results for w in r.warnings]

        return {
            "总人数": total,
            "有补贴人数": has_subsidy,
            "外宿补贴合计金额": total_amount,
            "警告": all_warnings,
        }
