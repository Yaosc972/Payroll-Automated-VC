"""全勤奖计算引擎 (Full Attendance Bonus Engine)."""
import calendar
import re
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional
from .base import BaseEngine, CalculationResult, safe_float, safe_int
from ..models import AuditExplanation


SUBJECT = "quanqinjiang"


# 硬编码排除名单
EXCLUDED_EMPLOYEE_IDS = {"OWHN9535", "OWHN9353", "OWHX0190"}

# 日考勤中的非工作日状态
NON_WORK_STATUS = {"星期六休息", "星期天休息", "法定节假日"}


def _normalized_field_name(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).replace("（", "(").replace("）", ")").replace("≤", "")


def _first_numeric(employee_data: Dict[str, Any], *field_names: str) -> float:
    """Read the first populated attendance field while supporting old headers."""
    for field_name in field_names:
        value = employee_data.get(field_name)
        if value not in (None, ""):
            return max(0.0, safe_float(value))
    normalized_data = {
        _normalized_field_name(key): value
        for key, value in employee_data.items()
        if value not in (None, "")
    }
    for field_name in field_names:
        normalized_name = _normalized_field_name(field_name)
        if normalized_name in normalized_data:
            return max(0.0, safe_float(normalized_data[normalized_name]))
    return 0.0


def _lateness_exemption(employee_data: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate the mutually-exclusive monthly lateness exemption paths."""
    within_six = _first_numeric(
        employee_data, "迟到6分钟内(次)", "迟到6分钟内", "迟到≤6分钟内(次)"
    )
    six_to_twenty = _first_numeric(
        employee_data,
        "迟到6-20分钟内(次)",
        "迟到6-20分钟内",
        "迟到6至20分钟内(次)",
    )
    twenty_to_thirty = _first_numeric(
        employee_data,
        "迟到20-30分钟内(次)",
        "迟到20-30分钟内",
        "迟到20至30分钟内(次)",
    )

    reasons = []
    if within_six > 3:
        reasons.append("6分钟内迟到超过3次")
    if six_to_twenty > 1:
        reasons.append("6-20分钟迟到超过1次")
    if within_six > 0 and six_to_twenty > 0:
        reasons.append("两档迟到混合出现")
    if twenty_to_thirty > 0:
        reasons.append("存在20-30分钟迟到")

    if reasons:
        judgement = "；".join(reasons)
    elif within_six > 0:
        judgement = f"使用6分钟内迟到豁免：{within_six:g}/3次"
    elif six_to_twenty > 0:
        judgement = f"使用6-20分钟迟到豁免：{six_to_twenty:g}/1次"
    else:
        judgement = "未使用分档迟到豁免"

    return {
        "迟到6分钟内次数": within_six,
        "迟到6-20分钟次数": six_to_twenty,
        "迟到20-30分钟次数": twenty_to_thirty,
        "迟到豁免判断": judgement,
        "是否不符合迟到豁免": bool(reasons),
    }


def _audit_explanation(
    amount: float,
    rule_name: str,
    formula: str,
    inputs: Dict[str, Any],
    intermediate_values: Dict[str, Any] = None,
    steps: List[str] = None,
) -> Dict[str, Any]:
    return AuditExplanation(
        subject=SUBJECT,
        amount=amount,
        rule_name=rule_name,
        formula=formula,
        inputs=inputs,
        intermediate_values=intermediate_values or {},
        steps=steps or [],
    ).to_dict()


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
        input_snapshot = {
            "工号": employee_id,
            "姓名": employee_name,
            "工作地区": str(employee_data.get("工作地区", "")),
            "岗位名称": str(employee_data.get("岗位名称", employee_data.get("岗位", ""))),
            "考勤月份": str(employee_data.get("考勤月份", "")),
            "入职日期": str(employee_data.get("入职日期", "")),
            "最后工作日": str(employee_data.get("最后工作日", "")),
            "迟到6分钟内次数": _first_numeric(
                employee_data, "迟到6分钟内(次)", "迟到6分钟内", "迟到≤6分钟内(次)"
            ),
            "迟到6-20分钟次数": _first_numeric(
                employee_data, "迟到6-20分钟内(次)", "迟到6-20分钟内", "迟到6至20分钟内(次)"
            ),
            "迟到20-30分钟次数": _first_numeric(
                employee_data, "迟到20-30分钟内(次)", "迟到20-30分钟内", "迟到20至30分钟内(次)"
            ),
            "日考勤记录数": len(daily_attendance or []),
        }

        # 条件1：硬编码排除
        if employee_id in EXCLUDED_EMPLOYEE_IDS:
            return CalculationResult(
                employee_id=employee_id,
                employee_name=employee_name,
                amount=0,
                details={
                    "reason": "硬编码排除",
                    "audit_explanation": _audit_explanation(
                        0,
                        "全勤奖特殊排除名单",
                        "特殊排除名单命中 = 0",
                        input_snapshot,
                        {"是否命中特殊排除名单": True},
                        ["员工在特殊排除名单中", "全勤奖金额为0"],
                    ),
                },
                warnings=[]
            )

        # 获取考勤月份
        attendance_month = str(employee_data.get("考勤月份", ""))
        if len(attendance_month) != 6:
            return CalculationResult(
                employee_id=employee_id,
                employee_name=employee_name,
                amount=0,
                details={
                    "reason": "考勤月份格式异常",
                    "audit_explanation": _audit_explanation(
                        0,
                        "全勤奖月份校验",
                        "考勤月份无效 = 0",
                        input_snapshot,
                        {"考勤月份": attendance_month},
                        ["考勤月份不是YYYYMM格式", "无法判断月初月末", "全勤奖金额为0"],
                    ),
                },
                warnings=[f"考勤月份格式异常: {attendance_month}"]
            )

        month_start, month_end, _ = self.get_month_range(attendance_month)

        # 条件2：分档迟到豁免。两条路径互斥，不能叠加使用。
        lateness_values = _lateness_exemption(employee_data)
        if lateness_values["是否不符合迟到豁免"]:
            return CalculationResult(
                employee_id=employee_id,
                employee_name=employee_name,
                amount=0,
                details={
                    "reason": "迟到豁免不符合",
                    "audit_explanation": _audit_explanation(
                        0,
                        "全勤奖迟到豁免判断",
                        "A≤3且B≤1且不得同时大于0，且20-30分钟迟到=0；否则全勤奖=0",
                        input_snapshot,
                        lateness_values,
                        [
                            "分别统计6分钟内、6-20分钟和20-30分钟迟到次数",
                            "6分钟内最多豁免3次，或6-20分钟最多豁免1次，两条路径不可叠加",
                            lateness_values["迟到豁免判断"],
                            "全勤奖金额为0",
                        ],
                    ),
                },
                warnings=[],
            )

        # 条件3：其他缺勤/迟到早退/签卡排除
        absence_conditions = [
            safe_float(employee_data.get("旷工天数", 0)),
            safe_float(employee_data.get("正班迟到次数", 0)) + safe_float(employee_data.get("早退次数", 0)),
            safe_float(employee_data.get("签卡次数", 0)),
            safe_float(employee_data.get("工伤假天数", 0)),
            safe_float(employee_data.get("事假时数", 0)),
            safe_float(employee_data.get("病假时数", 0)),
            safe_float(employee_data.get("入离职缺勤时数", 0)),
            safe_float(employee_data.get("迟到早退30分钟内扣款", 0)),
        ]
        absence_values = {
            "旷工天数": absence_conditions[0],
            "迟到早退次数": absence_conditions[1],
            "签卡次数": absence_conditions[2],
            "工伤假天数": absence_conditions[3],
            "事假时数": absence_conditions[4],
            "病假时数": absence_conditions[5],
            "入离职缺勤时数": absence_conditions[6],
            "迟到早退30分钟内扣款": absence_conditions[7],
            **lateness_values,
        }

        if (
            absence_conditions[0] > 0
            or absence_conditions[1] > 3
            or absence_conditions[2] > 3
            or any(value > 0 for value in absence_conditions[3:])
        ):
            return CalculationResult(
                employee_id=employee_id,
                employee_name=employee_name,
                amount=0,
                details={
                    "reason": "缺勤/迟到/签卡排除",
                    "audit_explanation": _audit_explanation(
                        0,
                        "全勤奖缺勤与异常考勤判断",
                        "存在排除项 = 0",
                        input_snapshot,
                        absence_values,
                        [
                            "检查旷工、迟到早退、签卡、工伤、事假、病假、入离职缺勤和迟到早退扣款",
                            "命中至少一个全勤奖排除条件",
                            "全勤奖金额为0",
                        ],
                    ),
                },
                warnings=[]
            )

        # 条件4：入职时间排除（含工作日判断）
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
                        details={
                            "reason": "入职时间排除",
                            "hire_date": str(hire_date),
                            "audit_explanation": _audit_explanation(
                                0,
                                "全勤奖入职时间判断",
                                "月初至入职日前存在工作日 = 0",
                                input_snapshot,
                                {
                                    "月初": month_start.isoformat(),
                                    "入职日期": hire_date.isoformat(),
                                    "入职前缺口开始": gap_start.isoformat(),
                                    "入职前缺口结束": gap_end.isoformat(),
                                    "缺口内是否存在工作日": has_workday,
                                },
                                ["员工非月初入职", "月初至入职日前存在工作日", "全勤奖金额为0"],
                            ),
                        },
                        warnings=[]
                    )
                # gap全是休息日/节假日，不排除，继续判断条件4

        # 条件5：在职状态判断
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
                details={
                    "reason": "在职员工",
                    "audit_explanation": _audit_explanation(
                        self.bonus_amount,
                        "全勤奖发放判断",
                        "满足全勤条件 = 100",
                        input_snapshot,
                        {**absence_values, "最后工作日": ""},
                        ["未命中排除名单", "未命中缺勤/迟到/签卡排除项", "员工在职", f"全勤奖金额为{self.bonus_amount}"],
                    ),
                },
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
                    details={
                        "reason": "在职至月末",
                        "audit_explanation": _audit_explanation(
                            self.bonus_amount,
                            "全勤奖离职日期判断",
                            "最后工作日>=月末且满足全勤条件 = 100",
                            input_snapshot,
                            {**absence_values, "最后工作日": last_work_day.isoformat(), "月末": month_end.isoformat()},
                            ["未命中排除项", "最后工作日不早于月末", f"全勤奖金额为{self.bonus_amount}"],
                        ),
                    },
                    warnings=[]
                )
            else:
                # 当月离职且未到月末
                return CalculationResult(
                    employee_id=employee_id,
                    employee_name=employee_name,
                    amount=0,
                    details={
                        "reason": "当月离职",
                        "last_work_day": str(last_work_day),
                        "audit_explanation": _audit_explanation(
                            0,
                            "全勤奖离职日期判断",
                            "最后工作日<月末 = 0",
                            input_snapshot,
                            {"最后工作日": last_work_day.isoformat(), "月末": month_end.isoformat()},
                            ["员工当月离职且最后工作日早于月末", "全勤奖金额为0"],
                        ),
                    },
                    warnings=[]
                )

        # 默认返回0
        return CalculationResult(
            employee_id=employee_id,
            employee_name=employee_name,
            amount=0,
            details={
                "reason": "未匹配任何条件",
                "audit_explanation": _audit_explanation(
                    0,
                    "全勤奖兜底判断",
                    "未匹配发放条件 = 0",
                    input_snapshot,
                    absence_values,
                    ["未匹配明确发放或排除条件", "全勤奖金额为0", "需要人工复核"],
                ),
            },
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
