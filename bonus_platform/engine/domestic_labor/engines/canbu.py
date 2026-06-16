"""餐补计算引擎 (Meal Allowance Engine)."""
from typing import Any, Dict, List
from .base import BaseEngine, CalculationResult
from ..models import AuditExplanation


SUBJECT = "canbu"


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


class CanBuEngine(BaseEngine):
    """餐补计算引擎"""

    def __init__(self, daily_rate: float = 19.0, monthly_cap: float = 500.0):
        self.daily_rate = daily_rate
        self.monthly_cap = monthly_cap

    def calculate(self, employee_data: Dict[str, Any], daily_attendance: List[Dict[str, Any]] = None) -> CalculationResult:
        """计算单个员工的餐补

        Args:
            employee_data: 月考勤数据 (Sheet2)
            daily_attendance: 日考勤数据列表 (Sheet1)
        """
        employee_id = str(employee_data.get("工号", ""))
        employee_name = str(employee_data.get("姓名", ""))
        warnings = []
        input_snapshot = {
            "工号": employee_id,
            "姓名": employee_name,
            "餐补标准": str(employee_data.get("餐补标准", "")),
            "日考勤记录数": len(daily_attendance or []),
        }

        # 补贴资格判断
        meal_standard = str(employee_data.get("餐补标准", ""))
        if meal_standard != "19元/天，封顶500元/月" or meal_standard in ["/", ""]:
            return CalculationResult(
                employee_id=employee_id,
                employee_name=employee_name,
                amount=0,
                details={
                    "reason": "无补贴资格",
                    "audit_explanation": _audit_explanation(
                        0,
                        "餐补资格判断",
                        "餐补标准不匹配 = 0",
                        input_snapshot,
                        {"餐补标准": meal_standard},
                        ["员工餐补标准未匹配 19元/天，封顶500元/月", "餐补金额为0"],
                    ),
                },
                warnings=[]
            )

        if not daily_attendance:
            return CalculationResult(
                employee_id=employee_id,
                employee_name=employee_name,
                amount=0,
                details={
                    "reason": "无日考勤数据",
                    "audit_explanation": _audit_explanation(
                        0,
                        "餐补日考勤校验",
                        "无日考勤数据 = 0",
                        input_snapshot,
                        {"日考勤记录数": 0},
                        ["员工无日考勤记录", "无法逐日计算餐补", "餐补金额为0"],
                    ),
                },
                warnings=[f"员工{employee_id}无日考勤数据"]
            )

        # 逐日计算
        daily_totals = []
        for day in daily_attendance:
            daily_amount = self._calculate_daily(day)
            daily_totals.append(daily_amount)

        # 汇总并封顶
        monthly_total = sum(daily_totals)
        final_amount = round(min(monthly_total, self.monthly_cap), 2)

        if monthly_total > self.monthly_cap:
            warnings.append(f"触发封顶: 累计{monthly_total:.2f}元 > {self.monthly_cap}元")

        return CalculationResult(
            employee_id=employee_id,
            employee_name=employee_name,
            amount=final_amount,
            details={
                "日餐补明细": daily_totals,
                "月累计": round(monthly_total, 2),
                "封顶金额": self.monthly_cap,
                "是否触发封顶": monthly_total > self.monthly_cap,
                "audit_explanation": _audit_explanation(
                    final_amount,
                    "餐补逐日累计与封顶",
                    "min(Σ单日餐补, 月封顶500)",
                    input_snapshot,
                    {
                        "日考勤记录数": len(daily_attendance),
                        "日餐补合计": round(monthly_total, 2),
                        "月封顶": self.monthly_cap,
                        "是否触发封顶": monthly_total > self.monthly_cap,
                        "最终金额": final_amount,
                    },
                    [
                        "按日考勤逐日计算餐补",
                        "单日餐补优先使用日考勤预计算值；否则按有效出勤时数折算",
                        f"月累计餐补为{round(monthly_total, 2)}",
                        f"最终餐补=min({round(monthly_total, 2)}, {self.monthly_cap})={final_amount}",
                    ],
                ),
            },
            warnings=warnings
        )

    def _calculate_daily(self, day_data: Dict[str, Any]) -> float:
        """计算单日餐补

        优先使用日考勤文件中的预计算"餐补"值；
        如无则从正班时数等原始数据计算。
        """
        # 如果日考勤数据已有预计算的餐补值，直接使用
        pre_calc = day_data.get("餐补")
        if pre_calc is not None and pre_calc != "" and pre_calc != "None":
            try:
                return float(pre_calc)
            except (ValueError, TypeError):
                pass

        # 理货操作组计件排除
        department = str(day_data.get("四级部门名称", ""))
        timing = str(day_data.get("计时", ""))
        if department == "理货操作组" and timing == "计件":
            return 0

        # 旷工排除
        is_abnormal = str(day_data.get("是否异常", ""))
        abnormal_reason = str(day_data.get("异常原因", ""))
        if is_abnormal == "是" and abnormal_reason == "旷工":
            return 0

        # 日有效出勤时数
        regular_hours = float(day_data.get("正班时数", 0) or 0)
        overtime_hours = float(day_data.get("刷卡加班", 0) or 0)
        effective_hours = max(regular_hours, overtime_hours)

        # 日餐补计算
        if effective_hours > 8:
            return self.daily_rate
        elif effective_hours == 0:
            return 0
        else:
            return effective_hours * (self.daily_rate / 8)

    def calculate_batch(self, employees: List[Dict[str, Any]], daily_data: Dict[str, List[Dict[str, Any]]]) -> List[CalculationResult]:
        """批量计算餐补

        Args:
            employees: 员工月考勤数据列表
            daily_data: 按工号分组的日考勤数据 {工号: [日考勤数据]}
        """
        results = []
        for emp in employees:
            employee_id = str(emp.get("工号", ""))
            daily = daily_data.get(employee_id, [])
            result = self.calculate(emp, daily)
            results.append(result)
        return results

    def verify(self, results: List[CalculationResult]) -> Dict[str, Any]:
        """验证计算结果"""
        total = len(results)
        capped = sum(1 for r in results if r.details.get("是否触发封顶", False))
        total_amount = sum(r.amount for r in results)
        all_warnings = [w for r in results for w in r.warnings]

        return {
            "参与计算人数": total,
            "触发封顶人数": capped,
            "餐补合计金额": total_amount,
            "警告": all_warnings,
        }
