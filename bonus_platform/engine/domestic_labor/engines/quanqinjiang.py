"""全勤奖计算引擎 (Full Attendance Bonus Engine)."""
import calendar
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional
from .base import BaseEngine, CalculationResult, safe_float, safe_int


# 硬编码排除名单
EXCLUDED_EMPLOYEE_IDS = {"OWHN9535", "OWHN9353", "OWHX0190"}

# 日考勤中的非工作日状态
NON_WORK_STATUS = {"星期六休息", "星期天休息", "法定节假日"}


class QuanQinJiangEngine(BaseEngine):
    """全勤奖计算引擎"""

    def __init__(self, bonus_amount: float = 100.0):
        self.bonus_amount = bonus_amount

    @staticmethod
    def _has_workday_in_gap(
        employee_id: str,
        gap_start: date,
        gap_end: date,
        daily_attendance: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """检查gap期间是否存在工作日。

        优先使用日考勤数据的"工作状态"列判断，
        无日考勤数据时用日历判断（周一至周五为工作日）。
        """
        # 构建日考勤状态索引 {日期: 工作状态}
        daily_status = {}
        if daily_attendance:
            for day in daily_attendance:
                day_date = day.get("出勤日期")
                if isinstance(day_date, date):
                    daily_status[day_date] = str(day.get("工作状态", ""))
                elif isinstance(day_date, str):
                    try:
                        from datetime import datetime
                        day_date = datetime.strptime(day_date[:10], "%Y-%m-%d").date()
                        daily_status[day_date] = str(day.get("工作状态", ""))
                    except (ValueError, TypeError):
                        pass

        d = gap_start
        while d <= gap_end:
            if d in daily_status:
                status = daily_status[d]
                if status and status not in NON_WORK_STATUS:
                    return True
            else:
                # 无日考勤记录，用日历判断
                if d.weekday() < 5:  # 0-4 = 周一至周五
                    return True
            d += timedelta(days=1)

        return False

    def calculate(
        self,
        employee_data: Dict[str, Any],
        daily_attendance: Optional[List[Dict[str, Any]]] = None,
    ) -> CalculationResult:
        """计算单个员工的全勤奖"""
        employee_id = str(employee_data.get("工号", ""))
        employee_name = str(employee_data.get("姓名", ""))
        warnings = []

        # 条件1：硬编码排除
        if employee_id in EXCLUDED_EMPLOYEE_IDS:
            return CalculationResult(
                employee_id=employee_id,
                employee_name=employee_name,
                amount=0,
                details={"reason": "硬编码排除"},
                warnings=[f"员工{employee_id}在特殊排除名单中"]
            )

        # 获取考勤月份
        attendance_month = str(employee_data.get("考勤月份", ""))
        if len(attendance_month) != 6:
            return CalculationResult(
                employee_id=employee_id,
                employee_name=employee_name,
                amount=0,
                details={"reason": "考勤月份格式异常"},
                warnings=[f"考勤月份格式异常: {attendance_month}"]
            )

        month_start, month_end, _ = self.get_month_range(attendance_month)

        # 条件2：缺勤/迟到/签卡排除
        absence_conditions = [
            safe_float(employee_data.get("旷工天数", 0)) > 0,
            (safe_float(employee_data.get("正班迟到次数", 0)) + safe_float(employee_data.get("早退次数", 0))) > 3,
            safe_float(employee_data.get("签卡次数", 0)) > 3,
            safe_float(employee_data.get("工伤假天数", 0)) > 0,
            safe_float(employee_data.get("事假时数", 0)) > 0,
            safe_float(employee_data.get("病假时数", 0)) > 0,
            safe_float(employee_data.get("入离职缺勤时数", 0)) > 0,
            safe_float(employee_data.get("迟到早退30分钟内扣款", 0)) > 0,
        ]

        if any(absence_conditions):
            return CalculationResult(
                employee_id=employee_id,
                employee_name=employee_name,
                amount=0,
                details={"reason": "缺勤/迟到/签卡排除"},
                warnings=[]
            )

        # 条件3：入职时间排除（含工作日判断）
        hire_date = employee_data.get("入职日期")
        if hire_date and isinstance(hire_date, (date, datetime)):
            if isinstance(hire_date, datetime):
                hire_date = hire_date.date()
            if hire_date > month_start:
                gap_start = month_start
                gap_end = hire_date - timedelta(days=1)
                has_workday = self._has_workday_in_gap(
                    employee_id, gap_start, gap_end, daily_attendance
                )
                if has_workday:
                    return CalculationResult(
                        employee_id=employee_id,
                        employee_name=employee_name,
                        amount=0,
                        details={"reason": "入职时间排除", "hire_date": str(hire_date)},
                        warnings=[]
                    )
                # gap全是休息日/节假日，不排除，继续判断条件4

        # 条件4：在职状态判断
        last_work_day = employee_data.get("最后工作日")

        # 处理Excel空值：time(0,0)（时间格式空单元格）、零日期
        if isinstance(last_work_day, time):
            if last_work_day.hour == 0 and last_work_day.minute == 0:
                last_work_day = None
        elif isinstance(last_work_day, (date, datetime)):
            if last_work_day.year < 1905:
                last_work_day = None

        if last_work_day is None or last_work_day == "" or last_work_day == "None":
            # 在职员工
            return CalculationResult(
                employee_id=employee_id,
                employee_name=employee_name,
                amount=self.bonus_amount,
                details={"reason": "在职员工"},
                warnings=[]
            )

        if isinstance(last_work_day, (date, datetime)):
            if isinstance(last_work_day, datetime):
                last_work_day = last_work_day.date()
            if last_work_day >= month_end:
                # 在职至月末
                return CalculationResult(
                    employee_id=employee_id,
                    employee_name=employee_name,
                    amount=self.bonus_amount,
                    details={"reason": "在职至月末"},
                    warnings=[]
                )
            else:
                # 当月离职且未到月末
                return CalculationResult(
                    employee_id=employee_id,
                    employee_name=employee_name,
                    amount=0,
                    details={"reason": "当月离职", "last_work_day": str(last_work_day)},
                    warnings=[]
                )

        # 默认返回0
        return CalculationResult(
            employee_id=employee_id,
            employee_name=employee_name,
            amount=0,
            details={"reason": "未匹配任何条件"},
            warnings=["未匹配任何条件，请人工复核"]
        )

    def calculate_batch(
        self,
        employees: List[Dict[str, Any]],
        daily_data: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    ) -> List[CalculationResult]:
        """批量计算全勤奖"""
        results = []
        for emp in employees:
            employee_id = str(emp.get("工号", ""))
            daily = daily_data.get(employee_id, []) if daily_data else []
            result = self.calculate(emp, daily)
            results.append(result)
        return results

    def verify(self, results: List[CalculationResult]) -> Dict[str, Any]:
        """验证计算结果"""
        total = len(results)
        bonus_100 = sum(1 for r in results if r.amount == 100)
        bonus_0 = sum(1 for r in results if r.amount == 0)
        bonus_other = sum(1 for r in results if r.amount not in [0, 100])
        total_amount = sum(r.amount for r in results)
        all_warnings = [w for r in results for w in r.warnings]

        return {
            "总人数": total,
            "全勤奖=100的人数": bonus_100,
            "全勤奖=0的人数": bonus_0,
            "全勤奖其他值人数": bonus_other,
            "全勤奖合计金额": total_amount,
            "警告": all_warnings,
        }
