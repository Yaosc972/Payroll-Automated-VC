"""餐补计算引擎 (Meal Allowance Engine)."""
from collections import Counter
from typing import Any, Dict, List

from .base import BaseEngine, CalculationResult, safe_float
from ..models import AuditExplanation


SUBJECT = "canbu"

DONGGUAN_DAILY_RATE = 19.0
DONGGUAN_MONTHLY_CAP = 500.0

DONGGUAN_ELIGIBLE_POSITIONS = {
    "安检员",
    "操作员",
    "叉车司机",
    "揽收充电司机",
    "查验员",
    "监察员",
}
DONGGUAN_INELIGIBLE_POSITIONS = {
    "保洁",
    "理货员",
    "安检组长",
    "操作主管",
    "操作组长",
    "稽查副主管",
    "文员",
    "物流专员",
    "行政专员",
    "质量监控专员",
    "见习组长",
    "HRBP专员",
    "高级HRBP专员",
    "高级招聘专员",
    "招聘专员",
}
DONGGUAN_DEPARTMENT_KEYWORDS = {"寮步区", "莞深操作"}

JIASHAN_MONTHLY_STANDARD = 300.0
JIASHAN_ELIGIBLE_POSITIONS = {
    "安检员",
    "操作员",
    "门禁员",
    "巡场员",
    "仓库文员",
    "操作文员",
    "设备维护专员",
    "数据专员",
    "安全员",
}
JIASHAN_INELIGIBLE_POSITIONS = {
    "操作副主管",
    "操作主管",
    "操作组长",
    "见习组长",
    "操作高级主管",
    "HRBP专员",
    "高级HRBP专员",
    "高级招聘专员",
    "招聘专员",
}

REST_DAY_STATUSES = {"星期六休息", "星期天休息", "法定节假日", "休息"}


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


def _first_non_empty(*values) -> str:
    for value in values:
        text = str(value or "").strip()
        if text and text != "None":
            return text
    return ""


def _text_from_fields(row: Dict[str, Any], field_names: List[str]) -> str:
    return " ".join(str(row.get(field, "") or "") for field in field_names)


def _department_text(employee_data: Dict[str, Any], daily_attendance: List[Dict[str, Any]]) -> str:
    fields = [
        "一级部门名称",
        "二级部门名称",
        "三级部门名称",
        "四级部门名称",
        "部门",
        "部门名称",
    ]
    parts = [_text_from_fields(employee_data, fields)]
    for day in daily_attendance or []:
        parts.append(_text_from_fields(day, fields))
    return " ".join(parts)


def _work_area(employee_data: Dict[str, Any], daily_attendance: List[Dict[str, Any]]) -> str:
    daily_areas = [
        str(day.get("工作地区", "") or "").strip()
        for day in daily_attendance or []
        if str(day.get("工作地区", "") or "").strip()
    ]
    if daily_areas:
        return Counter(daily_areas).most_common(1)[0][0]
    return str(employee_data.get("工作地区", "") or "").strip()


def _position(employee_data: Dict[str, Any], daily_attendance: List[Dict[str, Any]]) -> str:
    return _first_non_empty(
        employee_data.get("岗位名称"),
        employee_data.get("岗位"),
        *(day.get("岗位名称") or day.get("岗位") for day in (daily_attendance or [])),
    )


class CanBuEngine(BaseEngine):
    """餐补计算引擎"""

    def calculate(self, employee_data: Dict[str, Any], daily_attendance: List[Dict[str, Any]] = None) -> CalculationResult:
        """计算单个员工的餐补。"""
        daily_attendance = daily_attendance or []
        employee_id = str(employee_data.get("工号", ""))
        employee_name = str(employee_data.get("姓名", ""))
        work_area = _work_area(employee_data, daily_attendance)
        position = _position(employee_data, daily_attendance)
        department_text = _department_text(employee_data, daily_attendance)
        input_snapshot = {
            "工号": employee_id,
            "姓名": employee_name,
            "工作地区": work_area,
            "岗位名称": position,
            "部门字段": department_text,
            "日考勤记录数": len(daily_attendance),
        }

        if work_area == "东莞":
            return self._calculate_dongguan(
                employee_id,
                employee_name,
                employee_data,
                daily_attendance,
                position,
                department_text,
                input_snapshot,
            )
        if work_area == "嘉善":
            return self._calculate_jiashan(
                employee_id,
                employee_name,
                employee_data,
                position,
                input_snapshot,
            )
        if work_area == "晋江":
            return self._zero_result(
                employee_id,
                employee_name,
                "晋江区域不享有餐补",
                "餐补工作地区判断",
                "晋江区域 = 0",
                input_snapshot,
                {"工作地区": work_area},
                ["工作地区为晋江", "晋江区域不享有餐补", "餐补金额为0"],
            )

        return self._zero_result(
            employee_id,
            employee_name,
            "工作地区未配置餐补规则",
            "餐补工作地区判断",
            "未命中已配置工作地区 = 0",
            input_snapshot,
            {"工作地区": work_area},
            ["工作地区未命中东莞、嘉善或晋江", "餐补金额为0"],
        )

    def _calculate_dongguan(
        self,
        employee_id: str,
        employee_name: str,
        employee_data: Dict[str, Any],
        daily_attendance: List[Dict[str, Any]],
        position: str,
        department_text: str,
        input_snapshot: Dict[str, Any],
    ) -> CalculationResult:
        is_eligible_dept = any(keyword in department_text for keyword in DONGGUAN_DEPARTMENT_KEYWORDS)
        is_explicitly_ineligible = position in DONGGUAN_INELIGIBLE_POSITIONS
        is_eligible_position = position in DONGGUAN_ELIGIBLE_POSITIONS
        if not is_eligible_dept or is_explicitly_ineligible or not is_eligible_position:
            return self._zero_result(
                employee_id,
                employee_name,
                "东莞餐补资格不满足",
                "东莞餐补资格判断",
                "部门未命中或岗位不在享有名单 = 0",
                input_snapshot,
                {
                    "部门是否命中寮步区/莞深操作": is_eligible_dept,
                    "岗位名称": position,
                    "岗位是否明确不享有": is_explicitly_ineligible,
                    "岗位是否在享有名单": is_eligible_position,
                },
                ["工作地区为东莞", "检查部门、享有岗位和不享有岗位", "餐补金额为0"],
            )

        if not daily_attendance:
            return self._zero_result(
                employee_id,
                employee_name,
                "无日考勤数据",
                "东莞餐补日考勤校验",
                "无日考勤数据 = 0",
                input_snapshot,
                {"日考勤记录数": 0},
                ["东莞餐补需要按日考勤逐日折算", "员工无日考勤记录", "餐补金额为0"],
                warnings=[f"员工{employee_id}无日考勤数据"],
            )

        daily_totals = []
        for day in daily_attendance:
            daily_totals.append(self._calculate_dongguan_daily(day))

        monthly_total = sum(daily_totals)
        final_amount = round(min(monthly_total, DONGGUAN_MONTHLY_CAP), 2)
        warnings = []
        if monthly_total > DONGGUAN_MONTHLY_CAP:
            warnings.append(f"触发封顶: 累计{monthly_total:.2f}元 > {DONGGUAN_MONTHLY_CAP}元")

        return CalculationResult(
            employee_id=employee_id,
            employee_name=employee_name,
            amount=final_amount,
            details={
                "地区规则": "东莞",
                "日餐补明细": daily_totals,
                "月累计": round(monthly_total, 2),
                "封顶金额": DONGGUAN_MONTHLY_CAP,
                "是否触发封顶": monthly_total > DONGGUAN_MONTHLY_CAP,
                "audit_explanation": _audit_explanation(
                    final_amount,
                    "东莞餐补逐日折算与封顶",
                    "min(Σ单日餐补, 500)",
                    input_snapshot,
                    {
                        "日标准": DONGGUAN_DAILY_RATE,
                        "月封顶": DONGGUAN_MONTHLY_CAP,
                        "日考勤记录数": len(daily_attendance),
                        "日餐补合计": round(monthly_total, 2),
                        "是否触发封顶": monthly_total > DONGGUAN_MONTHLY_CAP,
                        "最终金额": final_amount,
                    },
                    [
                        "工作地区为东莞，按平台内置餐补规则计算，不依赖月报餐补标准字段",
                        "工作日按正班时数折算，休息日/节假日按刷卡加班时数折算",
                        "保留原排除规则：四级部门名称=理货操作组且计时=计件时，当天餐补为0",
                        f"最终餐补=min({round(monthly_total, 2)}, {DONGGUAN_MONTHLY_CAP})={final_amount}",
                    ],
                ),
            },
            warnings=warnings,
        )

    def _calculate_dongguan_daily(self, day_data: Dict[str, Any]) -> float:
        department = str(day_data.get("四级部门名称", ""))
        timing = str(day_data.get("计时", ""))
        if department == "理货操作组" and timing == "计件":
            return 0

        is_abnormal = str(day_data.get("是否异常", ""))
        abnormal_reason = str(day_data.get("异常原因", ""))
        if is_abnormal == "是" and abnormal_reason == "旷工":
            return 0

        work_status = str(day_data.get("工作状态", "") or "")
        if work_status in REST_DAY_STATUSES:
            effective_hours = safe_float(day_data.get("刷卡加班", 0))
        else:
            effective_hours = safe_float(day_data.get("正班时数", 0))

        if effective_hours >= 8:
            return DONGGUAN_DAILY_RATE
        if effective_hours <= 0:
            return 0
        return round(effective_hours * (DONGGUAN_DAILY_RATE / 8), 2)

    def _calculate_jiashan(
        self,
        employee_id: str,
        employee_name: str,
        employee_data: Dict[str, Any],
        position: str,
        input_snapshot: Dict[str, Any],
    ) -> CalculationResult:
        is_explicitly_ineligible = position in JIASHAN_INELIGIBLE_POSITIONS
        is_eligible_position = position in JIASHAN_ELIGIBLE_POSITIONS
        if is_explicitly_ineligible or not is_eligible_position:
            return self._zero_result(
                employee_id,
                employee_name,
                "嘉善餐补资格不满足",
                "嘉善餐补资格判断",
                "岗位不在享有名单 = 0",
                input_snapshot,
                {
                    "岗位名称": position,
                    "岗位是否明确不享有": is_explicitly_ineligible,
                    "岗位是否在享有名单": is_eligible_position,
                },
                ["工作地区为嘉善", "检查享有岗位和不享有岗位", "餐补金额为0"],
            )

        schedule_days = safe_float(employee_data.get("排班天数", 0))
        actual_work_days = safe_float(employee_data.get("实际在职工作日天数", 0))
        personal_leave_hours = safe_float(employee_data.get("事假时数", 0))
        sick_leave_hours = safe_float(employee_data.get("病假时数", 0))
        absenteeism_days = safe_float(employee_data.get("旷工天数", 0))

        personal_leave_days = round(personal_leave_hours / 8, 4)
        sick_leave_days = round(sick_leave_hours / 8, 4)
        effective_days = round(
            actual_work_days - personal_leave_days - absenteeism_days - sick_leave_days * 0.4,
            4,
        )

        if schedule_days <= 0:
            return self._zero_result(
                employee_id,
                employee_name,
                "嘉善餐补排班天数缺失",
                "嘉善餐补月报字段校验",
                "排班天数<=0 = 0",
                input_snapshot,
                {
                    "排班天数": schedule_days,
                    "实际在职工作日天数": actual_work_days,
                    "事假天数": personal_leave_days,
                    "病假天数": sick_leave_days,
                    "旷工天数": absenteeism_days,
                },
                ["工作地区为嘉善", "排班天数缺失或为0", "餐补金额为0"],
                warnings=[f"员工{employee_id}嘉善餐补排班天数缺失"],
            )

        raw_amount = JIASHAN_MONTHLY_STANDARD / schedule_days * effective_days
        final_amount = round(max(min(raw_amount, JIASHAN_MONTHLY_STANDARD), 0), 2)

        return CalculationResult(
            employee_id=employee_id,
            employee_name=employee_name,
            amount=final_amount,
            details={
                "地区规则": "嘉善",
                "月标准": JIASHAN_MONTHLY_STANDARD,
                "排班天数": schedule_days,
                "实际在职工作日天数": actual_work_days,
                "事假天数": personal_leave_days,
                "病假天数": sick_leave_days,
                "旷工天数": absenteeism_days,
                "有效餐补天数": effective_days,
                "audit_explanation": _audit_explanation(
                    final_amount,
                    "嘉善餐补月报折算",
                    "300/排班天数×(实际在职工作日天数-事假天数-旷工天数-病假天数×0.4)",
                    input_snapshot,
                    {
                        "月标准": JIASHAN_MONTHLY_STANDARD,
                        "排班天数": schedule_days,
                        "实际在职工作日天数": actual_work_days,
                        "事假时数": personal_leave_hours,
                        "事假天数": personal_leave_days,
                        "病假时数": sick_leave_hours,
                        "病假天数": sick_leave_days,
                        "旷工天数": absenteeism_days,
                        "有效餐补天数": effective_days,
                        "未封顶金额": round(raw_amount, 2),
                        "最终金额": final_amount,
                    },
                    [
                        "工作地区为嘉善，按月考勤字段计算餐补",
                        "事假天数=事假时数/8，病假天数=病假时数/8",
                        "病假按40%扣减，旷工和事假按天扣减",
                        f"最终餐补=max(min({round(raw_amount, 2)}, {JIASHAN_MONTHLY_STANDARD}), 0)={final_amount}",
                    ],
                ),
            },
            warnings=[],
        )

    def _zero_result(
        self,
        employee_id: str,
        employee_name: str,
        reason: str,
        rule_name: str,
        formula: str,
        inputs: Dict[str, Any],
        intermediate_values: Dict[str, Any],
        steps: List[str],
        warnings: List[str] = None,
    ) -> CalculationResult:
        return CalculationResult(
            employee_id=employee_id,
            employee_name=employee_name,
            amount=0,
            details={
                "reason": reason,
                "audit_explanation": _audit_explanation(
                    0,
                    rule_name,
                    formula,
                    inputs,
                    intermediate_values,
                    steps,
                ),
            },
            warnings=warnings or [],
        )

    def calculate_batch(self, employees: List[Dict[str, Any]], daily_data: Dict[str, List[Dict[str, Any]]]) -> List[CalculationResult]:
        """批量计算餐补。"""
        results = []
        for emp in employees:
            employee_id = str(emp.get("工号", ""))
            daily = daily_data.get(employee_id, [])
            result = self.calculate(emp, daily)
            results.append(result)
        return results

    def verify(self, results: List[CalculationResult]) -> Dict[str, Any]:
        """验证计算结果。"""
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
