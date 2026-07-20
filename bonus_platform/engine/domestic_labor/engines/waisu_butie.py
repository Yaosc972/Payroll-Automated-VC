"""外宿补贴计算引擎 (External Housing Subsidy Engine)."""
from collections import Counter
from datetime import date, datetime
from typing import Any, Dict, List
from .base import BaseEngine, CalculationResult, safe_float
from ..models import AuditExplanation


SUBJECT = "waisu_butie"

DONGGUAN_ELIGIBLE_POSITIONS = {
    "安检员",
    "操作员",
    "叉车司机",
    "查验员",
    "监察员",
    "理货员",
    "揽收充电司机",
    "安检组长",
    "操作组长",
    "稽查副主管",
    "文员",
    "物流专员",
    "操作文员",
}
DONGGUAN_INELIGIBLE_POSITIONS = {
    "保洁",
    "行政专员",
    "质量监控专员",
    "HRBP专员",
    "高级HRBP专员",
    "高级招聘专员",
    "招聘专员",
}
DONGGUAN_ELIGIBLE_NAME_OVERRIDES = {"陈西莎", "田盈"}

JIASHAN_YIWU_ELIGIBLE_POSITIONS = {
    "安检员",
    "操作员",
    "门禁员",
    "巡场员",
    "仓库文员",
    "操作副主管",
    "操作主管",
    "操作组长",
    "见习组长",
    "设备维养专员",
    "设备维护专员",
    "设备维护员",
    "安检组长",
    "安全员",
    "HRBP专员",
    "高级HRBP专员",
    "高级招聘专员",
    "招聘专员",
    "数据专员",
    "保洁",
    "操作文员",
}

JINJIANG_ELIGIBLE_POSITIONS = {
    "操作员",
    "门禁员",
    "操作组长",
    "HRBP专员",
    "安全员",
}


def _to_date(val):
    """将datetime/date/str统一转为date对象。"""
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    return val


def _first_non_empty(*values) -> str:
    for value in values:
        text = str(value or "").strip()
        if text and text != "None":
            return text
    return ""


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
        daily_attendance = daily_attendance or []
        housing_records = housing_records or []
        work_area = _work_area(employee_data, daily_attendance)
        position = _position(employee_data, daily_attendance)
        standard = self.subsidy_standard
        warnings = []
        input_snapshot = {
            "工号": employee_id,
            "姓名": employee_name,
            "考勤月份": str(employee_data.get("考勤月份", "")),
            "工作地区": work_area,
            "岗位名称": position,
            "入职日期": str(employee_data.get("入职日期", "")),
            "最后工作日": str(employee_data.get("最后工作日", "")),
            "日考勤记录数": len(daily_attendance or []),
            "住宿记录数": len(housing_records or []),
        }

        # 考勤月份
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
                        "外宿补贴月份校验",
                        "考勤月份无效 = 0",
                        input_snapshot,
                        {"考勤月份": attendance_month},
                        ["考勤月份不是YYYYMM格式", "无法确定月初月末", "外宿补贴金额为0"],
                    ),
                },
                warnings=[f"考勤月份格式异常: {attendance_month}"]
            )

        month_start, month_end, days_in_month = self.get_month_range(attendance_month)

        # F1: 全月未出勤标记
        has_attendance = None
        if daily_attendance:
            has_attendance = any(
                day.get("上班一") or day.get("下班一")
                for day in daily_attendance
                if str(day.get("工号", "")) == employee_id
            )
            if not has_attendance and not self._has_mid_month_entry_or_exit(employee_data, month_start, month_end):
                return CalculationResult(
                    employee_id=employee_id,
                    employee_name=employee_name,
                    amount=0,
                    details={
                        "reason": "全月未出勤",
                        "audit_explanation": _audit_explanation(
                            0,
                            "外宿补贴出勤判断",
                            "全月无打卡 = 0",
                            input_snapshot,
                            {"日考勤记录数": len(daily_attendance), "是否有打卡": False},
                            ["日考勤未发现上班/下班打卡", "视为全月未出勤", "外宿补贴金额为0"],
                        ),
                    },
                    warnings=[f"员工{employee_id}全月未出勤"]
                )
        else:
            warnings.append(f"员工{employee_id}无日考勤数据")

        attendance_days_value = employee_data.get("正班出勤天数")
        attendance_days = safe_float(attendance_days_value)
        absent_days = safe_float(employee_data.get("旷工天数", 0))
        if (
            attendance_days_value not in (None, "")
            and attendance_days <= 1
            and absent_days >= 1
        ):
            return self._zero_result(
                employee_id,
                employee_name,
                "正班出勤不超过1天且旷工至少1天",
                "外宿补贴出勤与旷工判断",
                "正班出勤天数<=1且旷工天数>=1 = 0",
                input_snapshot,
                {
                    "正班出勤天数": attendance_days,
                    "旷工天数": absent_days,
                },
                [
                    f"工作地区为{work_area}",
                    f"正班出勤天数为{attendance_days}",
                    f"旷工天数为{absent_days}",
                    "外宿补贴金额为0",
                ],
            )

        if work_area == "晋江":
            return self._calculate_jinjiang(
                employee_id,
                employee_name,
                employee_data,
                position,
                standard,
                month_start,
                month_end,
                days_in_month,
                input_snapshot,
            )

        if work_area in {"东莞", "嘉善", "义乌"}:
            eligibility = self._check_regional_eligibility(work_area, employee_name, position)
            if not eligibility["eligible"]:
                return self._zero_result(
                    employee_id,
                    employee_name,
                    f"{work_area}外宿补贴资格不满足",
                    f"{work_area}外宿补贴资格判断",
                    "岗位不在享有名单或命中不享有名单 = 0",
                    input_snapshot,
                    eligibility,
                    [f"工作地区为{work_area}", "按线下享有/不享有岗位名单判断", "外宿补贴金额为0"],
                )

        # F3: 当月在职范围
        hire_date = employee_data.get("入职日期")
        last_work_day = employee_data.get("最后工作日")

        if isinstance(hire_date, (date, datetime)):
            employment_start = max(_to_date(hire_date), month_start)
        else:
            employment_start = month_start

        covers_month_start = (
            isinstance(hire_date, (date, datetime))
            and _to_date(hire_date) <= month_start
        )

        if last_work_day is None or last_work_day == "" or last_work_day == "None":
            employment_end = month_end
            is_full_month = covers_month_start
        elif isinstance(last_work_day, (date, datetime)):
            normalized_last_work_day = _to_date(last_work_day)
            employment_end = min(normalized_last_work_day, month_end)
            is_full_month = covers_month_start and normalized_last_work_day >= month_end
        else:
            employment_end = month_end
            is_full_month = False

        days_employed = (employment_end - employment_start).days + 1
        if days_employed <= 0:
            return CalculationResult(
                employee_id=employee_id,
                employee_name=employee_name,
                amount=0,
                details={
                    "reason": "在职日期异常",
                    "audit_explanation": _audit_explanation(
                        0,
                        "外宿补贴在职日期校验",
                        "在职天数<=0 = 0",
                        input_snapshot,
                        {
                            "在职开始": employment_start.isoformat(),
                            "在职结束": employment_end.isoformat(),
                            "在职天数": days_employed,
                        },
                        ["按入职/离职日期计算当月在职区间", "在职天数小于等于0", "外宿补贴金额为0"],
                    ),
                },
                warnings=[f"员工{employee_id}在职日期异常"]
            )

        if has_attendance is False and days_employed == 1 and employment_end == month_start:
            return self._zero_result(
                employee_id,
                employee_name,
                "首日离职且无打卡",
                "外宿补贴出勤判断",
                "当月首日离职且无打卡 = 0",
                input_snapshot,
                {
                    "在职开始": employment_start.isoformat(),
                    "在职结束": employment_end.isoformat(),
                    "在职天数": days_employed,
                    "是否有打卡": False,
                },
                ["当月在职仅首日", "日考勤未发现上班/下班打卡", "外宿补贴金额为0"],
            )

        # F4-F5: 住宿名单匹配和住宿扣除天数
        housing_deduction_days = self._housing_deduction_days(
            employee_id,
            housing_records,
            work_area,
            month_start,
            month_end,
            employment_start,
            employment_end,
        )

        # F6: 外宿补贴天数
        subsidy_days = max(0, days_employed - housing_deduction_days)

        # F7: 缺勤时数合计。嘉善/义乌线下公式对当月入离职人员也执行缺勤扣减。
        applies_absence_proration = is_full_month or work_area in {"嘉善", "义乌"}
        absence_hours = 0
        if applies_absence_proration:
            absence_hours = self._absence_hours(employee_data, work_area)

        if (
            applies_absence_proration
            and absence_hours >= 56
            and self._has_active_housing(employee_id, housing_records, month_start, month_end)
        ):
            return self._zero_result(
                employee_id,
                employee_name,
                "在宿且缺勤满56小时",
                f"{work_area}外宿补贴住宿与缺勤折算" if work_area else "外宿补贴住宿与缺勤折算",
                "在宿未退且缺勤>=56小时 = 0",
                input_snapshot,
                {
                    "月份天数": days_in_month,
                    "在职天数": days_employed,
                    "住宿扣除天数": housing_deduction_days,
                    "缺勤时数": absence_hours,
                    "休年假小时": safe_float(employee_data.get("休年假小时", 0)),
                    "补贴标准": standard,
                },
                ["住宿名单显示当月已入住且无退宿", "缺勤时数达到56小时", "外宿补贴金额为0"],
            )

        # F8: 外宿补贴
        # 缺勤≥56小时的有效天数公式仅适用于无住宿扣除的全月在职员工；
        # 有住宿扣除的员工已通过subsidy_days扣减，不再重复扣减缺勤
        if applies_absence_proration and absence_hours >= 56 and housing_deduction_days == 0:
            effective_days = days_in_month - absence_hours / 8
            if work_area in {"嘉善", "义乌"}:
                effective_days = subsidy_days - absence_hours / 8
            subsidy_amount = round(standard / days_in_month * effective_days, 2)
        else:
            subsidy_amount = round(standard / days_in_month * subsidy_days, 2)

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
                "补贴标准": standard,
                "audit_explanation": _audit_explanation(
                    subsidy_amount,
                    f"{work_area}外宿补贴住宿与缺勤折算" if work_area else "外宿补贴资格、住宿与缺勤折算",
                    "补贴标准/月天数 × 有效补贴天数",
                    input_snapshot,
                    {
                        "月份天数": days_in_month,
                        "在职天数": days_employed,
                        "住宿扣除天数": housing_deduction_days,
                        "外宿补贴天数": subsidy_days,
                        "缺勤时数": absence_hours,
                        "休年假小时": safe_float(employee_data.get("休年假小时", 0)),
                        "全月在职": is_full_month,
                        "补贴标准": standard,
                        "最终金额": subsidy_amount,
                    },
                    [
                        f"当月在职区间为{employment_start.isoformat()}至{employment_end.isoformat()}，在职{days_employed}天",
                        f"住宿名单扣除{housing_deduction_days}天",
                        f"外宿补贴天数=max(在职天数-住宿扣除天数, 0)={subsidy_days}",
                        "全月在职且缺勤达到56小时、且无住宿扣除时，按缺勤折算有效天数",
                        f"最终外宿补贴为{subsidy_amount}",
                    ],
                ),
            },
            warnings=warnings
        )

    def _check_regional_eligibility(self, work_area: str, employee_name: str, position: str) -> Dict[str, Any]:
        if work_area == "东莞":
            name_override = employee_name in DONGGUAN_ELIGIBLE_NAME_OVERRIDES
            explicitly_ineligible = position in DONGGUAN_INELIGIBLE_POSITIONS and not name_override
            eligible_position = position in DONGGUAN_ELIGIBLE_POSITIONS or name_override
            return {
                "工作地区": work_area,
                "岗位名称": position,
                "姓名": employee_name,
                "岗位是否明确不享有": explicitly_ineligible,
                "岗位是否在享有名单": eligible_position,
                "姓名是否特殊享有": name_override,
                "eligible": eligible_position and not explicitly_ineligible,
            }
        if work_area in {"嘉善", "义乌"}:
            eligible_position = position in JIASHAN_YIWU_ELIGIBLE_POSITIONS
            return {
                "工作地区": work_area,
                "岗位名称": position,
                "岗位是否明确不享有": False,
                "岗位是否在享有名单": eligible_position,
                "eligible": eligible_position,
            }
        return {"工作地区": work_area, "岗位名称": position, "eligible": True}

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

    def _housing_deduction_days(
        self,
        employee_id: str,
        housing_records: List[Dict[str, Any]],
        work_area: str,
        month_start: date,
        month_end: date,
        employment_start: date,
        employment_end: date,
    ) -> int:
        deduction_days = 0
        for record in housing_records or []:
            if str(record.get("工号", "")) != employee_id:
                continue
            check_in = record.get("入住时间")
            check_out = record.get("退宿时间")
            if not isinstance(check_in, (date, datetime)):
                continue

            housing_start = max(_to_date(check_in), month_start)
            if check_out is None or check_out == "" or not isinstance(check_out, (date, datetime)):
                housing_end = month_end
            else:
                co = _to_date(check_out)
                housing_end = min(co - date.resolution, month_end)

            overlap_start = max(employment_start, housing_start)
            overlap_end = min(employment_end, housing_end)
            if overlap_end >= overlap_start:
                deduction_days += (overlap_end - overlap_start).days + 1
        return deduction_days

    def _has_active_housing(
        self,
        employee_id: str,
        housing_records: List[Dict[str, Any]],
        month_start: date,
        month_end: date,
    ) -> bool:
        for record in housing_records or []:
            if str(record.get("工号", "")) != employee_id:
                continue
            check_in = record.get("入住时间")
            check_out = record.get("退宿时间")
            if not isinstance(check_in, (date, datetime)):
                continue
            check_in_date = _to_date(check_in)
            if check_in_date > month_end:
                continue
            return check_out is None or check_out == "" or not isinstance(check_out, (date, datetime))
        return False

    def _has_mid_month_entry_or_exit(self, employee_data: Dict[str, Any], month_start: date, month_end: date) -> bool:
        hire_date = employee_data.get("入职日期")
        last_work_day = employee_data.get("最后工作日")
        if isinstance(hire_date, (date, datetime)) and month_start <= _to_date(hire_date) <= month_end:
            return True
        if isinstance(last_work_day, (date, datetime)) and month_start <= _to_date(last_work_day) <= month_end:
            return True
        return False

    def _entry_exit_absence_hours(self, employee_data: Dict[str, Any]) -> float:
        schedule_days = safe_float(employee_data.get("排班天数", 0))
        actual_days = safe_float(employee_data.get("实际在职工作日天数", 0))
        if schedule_days > 0:
            return max(schedule_days - actual_days, 0) * 8
        return safe_float(employee_data.get("入离职缺勤时数", 0))

    def _absence_hours(self, employee_data: Dict[str, Any], work_area: str = "") -> float:
        if work_area in {"嘉善", "义乌"}:
            leave_day_fields = [
                "婚假天数",
                "陪产假天数",
                "工伤假天数",
                "医疗期天数",
                "丧假天数",
                "产假天数",
                "多胞胎假天数",
                "剖腹产假天数",
                "流产假天数",
                "产检假天数",
                "女神假天数",
            ]
            leave_days = sum(safe_float(employee_data.get(field, 0)) for field in leave_day_fields)
            return (
                leave_days * 8
                + safe_float(employee_data.get("排休请假天数", 0)) * 8
                + safe_float(employee_data.get("休年假小时", 0))
                + safe_float(employee_data.get("事假时数", 0))
                + safe_float(employee_data.get("调休时数", 0))
                + safe_float(employee_data.get("哺乳假小时", 0))
                + safe_float(employee_data.get("病假时数", 0)) * 0.6
                + safe_float(employee_data.get("旷工天数", 0)) * 8
            )
        return (
            safe_float(employee_data.get("事假时数", 0))
            + safe_float(employee_data.get("排休请假时数", 0))
            + safe_float(employee_data.get("病假时数", 0))
            + safe_float(employee_data.get("旷工时数", 0))
            + self._entry_exit_absence_hours(employee_data)
        )

    def _jinjiang_leave_days(self, employee_data: Dict[str, Any]) -> float:
        day_fields = [
            "旷工天数",
            "排休请假天数",
            "排休请假",
            "婚假天数",
            "陪产假天数",
            "工伤假天数",
            "丧假天数",
            "多胞胎假天数",
            "剖腹产假天数",
            "剖腹产天数",
            "流产假天数",
            "产检假天数",
        ]
        hour_fields = ["休年假小时", "事假时数", "病假时数", "调休时数", "哺乳假小时"]
        return round(
            sum(safe_float(employee_data.get(field, 0)) for field in day_fields)
            + sum(safe_float(employee_data.get(field, 0)) for field in hour_fields) / 8,
            4,
        )

    def _entry_exit_natural_days(self, employee_data: Dict[str, Any], month_start: date, month_end: date) -> int:
        hire_date = employee_data.get("入职日期")
        last_work_day = employee_data.get("最后工作日")
        if isinstance(last_work_day, (date, datetime)):
            lwd = _to_date(last_work_day)
            if month_start <= lwd < month_end:
                return max((month_end - lwd).days, 0)

        missing_days = 0
        if isinstance(hire_date, (date, datetime)):
            hd = _to_date(hire_date)
            if month_start < hd <= month_end:
                missing_days += (hd - month_start).days
        return max(missing_days, 0)

    def _calculate_jinjiang(
        self,
        employee_id: str,
        employee_name: str,
        employee_data: Dict[str, Any],
        position: str,
        standard: float,
        month_start: date,
        month_end: date,
        days_in_month: int,
        input_snapshot: Dict[str, Any],
    ) -> CalculationResult:
        eligible_position = position in JINJIANG_ELIGIBLE_POSITIONS
        if not eligible_position:
            return self._zero_result(
                employee_id,
                employee_name,
                "晋江外宿补贴资格不满足",
                "晋江外宿补贴资格判断",
                "岗位不在享有名单 = 0",
                input_snapshot,
                {"岗位名称": position, "岗位是否在享有名单": False},
                ["工作地区为晋江", "按线下享有岗位名单判断", "外宿补贴金额为0"],
            )

        entry_exit_days = self._entry_exit_natural_days(employee_data, month_start, month_end)
        leave_days = self._jinjiang_leave_days(employee_data)
        entry_exit_deduction = round(standard / days_in_month * entry_exit_days, 2)
        leave_deduction = round(standard / days_in_month * leave_days, 2) if leave_days > 7 else 0
        amount = round(max(standard - entry_exit_deduction - leave_deduction, 0), 2)

        return CalculationResult(
            employee_id=employee_id,
            employee_name=employee_name,
            amount=amount,
            details={
                "地区规则": "晋江",
                "入离职缺勤自然日天数": entry_exit_days,
                "请假旷工天数": leave_days,
                "入离职扣减": entry_exit_deduction,
                "请假扣减": leave_deduction,
                "补贴标准": standard,
                "audit_explanation": _audit_explanation(
                    amount,
                    "晋江外宿补贴月考勤扣减",
                    "外宿补贴标准-入离职扣减-请假扣减",
                    input_snapshot,
                    {
                        "补贴标准": standard,
                        "月份天数": days_in_month,
                        "入离职缺勤自然日天数": entry_exit_days,
                        "请假旷工天数": leave_days,
                        "入离职扣减": entry_exit_deduction,
                        "请假扣减": leave_deduction,
                        "最终金额": amount,
                    },
                    [
                        "工作地区为晋江，按月考勤扣减公式计算",
                        f"入离职扣减=ROUND({standard}/{days_in_month}*{entry_exit_days},2)={entry_exit_deduction}",
                        "请假旷工天数超过7天才扣减请假",
                        f"最终外宿补贴={standard}-{entry_exit_deduction}-{leave_deduction}={amount}",
                    ],
                ),
            },
            warnings=[],
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
