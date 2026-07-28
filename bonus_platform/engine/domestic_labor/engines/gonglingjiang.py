"""工龄奖计算引擎 (Seniority Bonus Engine)."""
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List
from .base import BaseEngine, CalculationResult, safe_float
from ..models import AuditExplanation, PayrollException


SUBJECT = "gonglingjiang"


DEPARTMENT_MAP_GSDG = {
    "中国操作部": "操作",
    "第四纵队": "揽收",
    "头程运营部": "FBU",
}

OPERATION_POSITIONS_GSDG = {
    "内勤专员", "中转员", "门禁员", "操作员", "监察员",
    "安检员", "操作文员", "查验员", "叉车司机", "揽收充电司机",
}

# 操作归属部门按月考勤字段逐行判断，工作地区明确时优先套用地区规则。
OPERATION_DEPARTMENTS = {
    "东南枢纽", "华东B2B枢纽", "华东枢纽", "中国操作部",
}

DONGGUAN_OPERATION_POSITIONS = {
    "安检员", "操作文员", "操作员", "叉车司机", "揽收充电司机",
    "查验员", "监察员", "理货员",
}

DONGGUAN_EXCLUDED_POSITIONS = {
    "HRBP专员", "安检组长", "保洁", "操作组长", "高级HRBP专员",
    "高级招聘专员", "稽查副主管", "稽查组长", "物流专员",
}

JINJIANG_OPERATION_POSITIONS = {"操作员", "门禁员"}

DONGGUAN_SENIORITY_CAP = 600
DONGGUAN_SENIORITY_RATE = 150
JINJIANG_SENIORITY_CAP = 150
JINJIANG_SENIORITY_RATE = 50
COLLECTION_SENIORITY_CAP = 600
COLLECTION_SENIORITY_RATE = 150
FBU_SENIORITY_CAP = 500
FBU_SENIORITY_RATE = 100

DEPARTMENT_MAP_WES = {
    "华东枢纽": "操作",
    "华东揽收组": "揽收",
    "东南枢纽": "操作",
    "华西区操作部": "操作",
    "闽赣揽收组": "揽收",
    "华东B2B枢纽": "操作",
}

OPERATION_POSITIONS_WES = {
    "操作员", "内勤专员", "中转员", "门禁员", "安检员", "操作文员",
}

COLLECTION_POSITIONS_WES = {"揽收操作员", "内勤专员"}

NO_BONUS_POSITIONS_WES = {
    "操作组长", "见习组长", "HRBP专员", "揽收组长",
    "操作副主管", "操作主管", "操作经理",
}

WES_SENIORITY_CAP = 150
WES_SENIORITY_RATE = 50


def _excel_round(value: float, digits: int = 2) -> float:
    quantizer = Decimal("1").scaleb(-digits)
    return float(Decimal(str(value)).quantize(quantizer, rounding=ROUND_HALF_UP))


def _exception(
    code: str,
    level: str,
    employee_id: str,
    employee_name: str,
    message: str,
    suggested_action: str,
    impact_amount: float = 0.0,
) -> PayrollException:
    return PayrollException(
        code=code,
        level=level,
        subject=SUBJECT,
        employee_id=employee_id,
        employee_name=employee_name,
        message=message,
        suggested_action=suggested_action,
        impact_amount=impact_amount,
    )


def _audit_explanation(
    amount: float,
    rule_name: str,
    inputs: Dict[str, Any],
    intermediate_values: Dict[str, Any] = None,
    steps: List[str] = None,
    formula: str = "",
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


def _details(
    base: Dict[str, Any],
    amount: float,
    rule_name: str,
    inputs: Dict[str, Any],
    intermediate_values: Dict[str, Any] = None,
    steps: List[str] = None,
    formula: str = "",
    exceptions: List[PayrollException] = None,
) -> Dict[str, Any]:
    payload = dict(base)
    payload["exceptions"] = [item.to_dict() for item in (exceptions or [])]
    payload["audit_explanation"] = _audit_explanation(
        amount=amount,
        rule_name=rule_name,
        formula=formula,
        inputs=inputs,
        intermediate_values=intermediate_values,
        steps=steps,
    )
    return payload


class GongLingJiangEngine(BaseEngine):
    """工龄奖计算引擎"""

    def __init__(self):
        pass

    def calculate(
        self,
        employee_data: Dict[str, Any],
        hrbp_list: List[str] = None,
        region_cap: float = None,
        region: str = None,
    ) -> CalculationResult:
        """计算单个员工的工龄奖

        Args:
            employee_data: 月考勤数据
            hrbp_list: 东莞第四纵队揽收线工龄奖名单中的工号
            region: 区域兼容口径（'wes'=华西/华东/东南，其他为莞深广珠）
        """
        employee_id = str(employee_data.get("工号", ""))
        employee_name = str(employee_data.get("姓名", ""))
        warnings = []
        exceptions = []

        # F1: 按员工工作地区和操作归属部门逐行判断
        primary_department = str(employee_data.get("一级部门名称", ""))
        department = str(employee_data.get("二级部门名称", ""))
        position = str(employee_data.get("岗位名称", ""))
        work_area = str(employee_data.get("工作地区", ""))
        input_snapshot = {
            "工号": employee_id,
            "姓名": employee_name,
            "一级部门名称": primary_department,
            "二级部门名称": department,
            "岗位名称": position,
            "工作地区": work_area,
            "考勤月份": employee_data.get("考勤月份", ""),
            "入职日期": str(employee_data.get("入职日期", "")),
        }
        zero_reason = ""
        zero_rule_name = "工龄奖资格判断"
        zero_steps = ["部门已匹配，但岗位条件未满足", "工龄奖金额为0"]

        is_operation_department = department in OPERATION_DEPARTMENTS

        if is_operation_department:
            dept_category = "操作"
            standard = 0
            cap = DONGGUAN_SENIORITY_CAP

            if work_area == "东莞":
                if position in DONGGUAN_OPERATION_POSITIONS and position not in DONGGUAN_EXCLUDED_POSITIONS:
                    standard = DONGGUAN_SENIORITY_RATE
                else:
                    zero_reason = "东莞操作岗位不享有工龄奖"
                    zero_steps = ["工作地区为东莞，部门归属操作", "岗位不在东莞操作享有范围或命中不享有岗位", "工龄奖金额为0"]
            elif work_area in {"嘉善", "义乌"}:
                zero_reason = f"{work_area}区域无工龄奖"
                zero_rule_name = "工龄奖工作地区判断"
                zero_steps = [f"工作地区为{work_area}", f"{work_area}区域无工龄奖", "工龄奖金额为0"]
            elif work_area == "晋江":
                cap = JINJIANG_SENIORITY_CAP
                if position in JINJIANG_OPERATION_POSITIONS:
                    standard = JINJIANG_SENIORITY_RATE
                else:
                    zero_reason = "晋江操作岗位不享有工龄奖"
                    zero_steps = ["工作地区为晋江，部门归属操作", "岗位不是晋江一线操作员", "工龄奖金额为0"]
            else:
                if department in DEPARTMENT_MAP_GSDG and position in OPERATION_POSITIONS_GSDG:
                    standard = DONGGUAN_SENIORITY_RATE
                elif region == "wes" and department in DEPARTMENT_MAP_WES and position in OPERATION_POSITIONS_WES:
                    standard = WES_SENIORITY_RATE
                    cap = WES_SENIORITY_CAP
                else:
                    zero_reason = "工作地区未配置操作工龄奖规则"
                    zero_steps = ["部门归属操作", "工作地区及历史兼容口径均未命中", "工龄奖金额为0"]

        elif work_area == "东莞" and department == "第四纵队":
            dept_category = "揽收"
            cap = COLLECTION_SENIORITY_CAP
            standard = 0
            if hrbp_list and employee_id in hrbp_list and "组长" not in position:
                standard = COLLECTION_SENIORITY_RATE
            elif not hrbp_list:
                message = f"员工{employee_id}为第四纵队揽收人员，请维护本月揽收线工龄奖名单"
                warnings.append(message)
                exceptions.append(_exception(
                    "MISSING_HRBP_LIST",
                    "warning",
                    employee_id,
                    employee_name,
                    message,
                    "补充包含工号和姓名的本月揽收线工龄奖名单，或人工确认该员工不发放工龄奖。",
                ))
                zero_reason = "缺少揽收线工龄奖名单"
                zero_steps = ["工作地区为东莞且二级部门为第四纵队", "未维护本月揽收线工龄奖名单", "工龄奖金额为0"]
            else:
                zero_reason = "未命中揽收线工龄奖名单或岗位为组长"
                zero_steps = ["工作地区为东莞且二级部门为第四纵队", "工号未命中名单或岗位包含组长", "工龄奖金额为0"]

        elif work_area == "东莞" and department == "头程运营部":
            dept_category = "FBU"
            standard = FBU_SENIORITY_RATE
            cap = FBU_SENIORITY_CAP

        elif region == "wes":
            dept_category = DEPARTMENT_MAP_WES.get(department, "其他")
            standard = 0
            cap = WES_SENIORITY_CAP

            if dept_category == "操作" and position in OPERATION_POSITIONS_WES:
                standard = WES_SENIORITY_RATE
            elif dept_category == "揽收" and position in COLLECTION_POSITIONS_WES:
                standard = WES_SENIORITY_RATE

            if position in NO_BONUS_POSITIONS_WES:
                standard = 0
                if dept_category != "其他":
                    message = f"员工{employee_id}岗位{position}为组长/非一线，无工龄奖"
                    warnings.append(message)
                    exceptions.append(_exception(
                        "EXCLUDED_POSITION",
                        "info",
                        employee_id,
                        employee_name,
                        message,
                        "如岗位信息有误，请修正后重新计算。",
                    ))

        else:
            dept_category = "其他"
            standard = 0
            cap = 0

        if dept_category == "其他":
            return CalculationResult(
                employee_id=employee_id,
                employee_name=employee_name,
                amount=0,
                details=_details(
                    {"reason": "非操作线部门不在当前工龄奖范围", "department": department},
                    amount=0,
                    rule_name="工龄奖部门范围判断",
                    inputs={
                        **input_snapshot,
                        "部门类别": dept_category,
                        "揽收线工龄奖名单人数": len(hrbp_list or []) if dept_category == "揽收" else "不适用",
                    },
                    steps=["二级部门未匹配当前操作线工龄奖适用范围", "工龄奖金额为0"],
                    formula="不适用部门 = 0",
                    exceptions=exceptions,
                ),
                warnings=[]
            )

        if standard == 0:
            return CalculationResult(
                employee_id=employee_id,
                employee_name=employee_name,
                amount=0,
                details=_details(
                    {"reason": zero_reason or "不符合工龄奖标准", "department": dept_category, "position": position},
                    amount=0,
                    rule_name=zero_rule_name,
                    inputs={**input_snapshot, "部门类别": dept_category},
                    steps=zero_steps,
                    formula="资格不满足 = 0",
                    exceptions=exceptions,
                ),
                warnings=warnings
            )

        regular_attendance_days = employee_data.get("正班出勤天数")
        if regular_attendance_days is not None and safe_float(regular_attendance_days) == 0:
            message = f"员工{employee_id}正班出勤天数为0，工龄奖已按缺勤折算规则计算，请复核是否应发放"
            warnings.append(message)
            exceptions.append(_exception(
                "ZERO_REGULAR_ATTENDANCE_DAYS",
                "info",
                employee_id,
                employee_name,
                message,
                "复核月报正班出勤天数、请假/旷工/排休记录；如确认无误，可按系统折算结果发放。",
            ))

        # F2.5: 检查备注异常
        remark = str(employee_data.get("备注", "") or "")
        remark_keywords = ["事假未出勤", "全月事假", "事假全月", "未出勤"]
        if any(kw in remark for kw in remark_keywords):
            message = f"员工{employee_id}({employee_name})备注'{remark}'，需人工确认是否发放工龄奖"
            warnings.append(f"⚠️ {message}")
            exceptions.append(_exception(
                "REMARK_REVIEW_REQUIRED",
                "warning",
                employee_id,
                employee_name,
                message,
                "复核备注对应的出勤状态，必要时登记人工调整或确认发放。",
            ))

        # F3: 工龄（司龄）
        hire_date = employee_data.get("入职日期")
        if not isinstance(hire_date, date):
            message = f"员工{employee_id}入职日期异常"
            exceptions.append(_exception(
                "INVALID_HIRE_DATE",
                "blocking",
                employee_id,
                employee_name,
                message,
                "补充正确入职日期后重新计算。",
            ))
            return CalculationResult(
                employee_id=employee_id,
                employee_name=employee_name,
                amount=0,
                details=_details(
                    {"reason": "入职日期异常"},
                    amount=0,
                    rule_name="工龄奖入职日期校验",
                    inputs=input_snapshot,
                    steps=["入职日期不是有效日期", "无法计算工龄", "工龄奖金额为0"],
                    formula="入职日期无效 = 0",
                    exceptions=exceptions,
                ),
                warnings=[message]
            )

        # 假设发放月为当月1日
        attendance_month = str(employee_data.get("考勤月份", ""))
        if len(attendance_month) == 6:
            year = int(attendance_month[:4])
            month = int(attendance_month[4:])
            ref_date = date(year, month, 1)
        else:
            ref_date = date.today().replace(day=1)

        years = ref_date.year - hire_date.year
        if (ref_date.month, ref_date.day) < (hire_date.month, hire_date.day):
            years -= 1
        years = max(years, 0)

        if years == 0:
            return CalculationResult(
                employee_id=employee_id,
                employee_name=employee_name,
                amount=0,
                details=_details(
                    {"reason": "入职不足1年", "years": 0},
                    amount=0,
                    rule_name="工龄奖工龄判断",
                    inputs={**input_snapshot, "参考日期": ref_date.isoformat()},
                    intermediate_values={"工龄(年)": 0},
                    steps=["按考勤月份月初计算司龄", "司龄不足1年", "工龄奖金额为0"],
                    formula="工龄不足1年 = 0",
                    exceptions=exceptions,
                ),
                warnings=[]
            )

        # F5: 应发工龄奖
        yingfa = min(standard * years, cap)

        # F6: 线下工资表按小时汇总；不同区域月报可能提供小时或天数字段。
        personal_leave_hours = safe_float(employee_data.get("事假时数", 0))
        sick_leave_hours = safe_float(employee_data.get("病假时数", 0))
        absenteeism_days = safe_float(employee_data.get("旷工天数", 0))
        rest_leave_days = safe_float(employee_data.get("排休请假天数", 0))
        raw_absenteeism_hours = employee_data.get("旷工时数")
        raw_rest_leave_hours = employee_data.get("排休请假时数")
        if raw_absenteeism_hours not in (None, ""):
            absenteeism_hours = safe_float(raw_absenteeism_hours)
            absenteeism_source = "旷工时数"
        else:
            absenteeism_hours = absenteeism_days * 8
            absenteeism_source = "旷工天数×8"
        if raw_rest_leave_hours not in (None, ""):
            rest_leave_hours = safe_float(raw_rest_leave_hours)
            rest_leave_source = "排休请假时数"
        else:
            rest_leave_hours = rest_leave_days * 8
            rest_leave_source = "排休请假天数×8"
        spk_hours = personal_leave_hours + sick_leave_hours + absenteeism_hours + rest_leave_hours

        # F7: 排班天数
        paiban = float(employee_data.get("排班天数", 0) or 0)
        if paiban == 0:
            message = f"员工{employee_id}排班天数为0，无法折算"
            exceptions.append(_exception(
                "ZERO_SCHEDULE_DAYS",
                "blocking",
                employee_id,
                employee_name,
                message,
                "补充排班天数后重新计算。",
            ))
            return CalculationResult(
                employee_id=employee_id,
                employee_name=employee_name,
                amount=0,
                details=_details(
                    {"reason": "排班天数为0"},
                    amount=0,
                    rule_name="工龄奖排班天数校验",
                    inputs={**input_snapshot, "排班天数": paiban},
                    steps=["排班天数为0", "无法计算日折算标准", "工龄奖金额为0"],
                    formula="排班天数为0 = 0",
                    exceptions=exceptions,
                ),
                warnings=[message]
            )

        # F8: 入离职缺勤时数
        actual_days = float(employee_data.get("实际在职工作日天数", 0) or 0)
        ruli_hours = (paiban - actual_days) * 8

        # F9: 最终工龄奖
        day_rate = yingfa / paiban
        after_spk = day_rate * (paiban - spk_hours / 8) if spk_hours >= 56 else yingfa
        after_ruli = after_spk - day_rate * (ruli_hours / 8)
        full_month_personal_leave = (
            regular_attendance_days is not None
            and safe_float(regular_attendance_days) == 0
            and personal_leave_hours > 0
        )
        final = 0 if full_month_personal_leave else _excel_round(after_ruli)

        absence_step = (
            f"事病旷排休合计{spk_hours}小时，达到56小时门槛，按出勤天数比例折算"
            if spk_hours >= 56
            else f"事病旷排休合计{spk_hours}小时，未达到56小时门槛，应发金额全额保留"
        )
        ruli_step = (
            f"入离职缺勤时数{ruli_hours}小时，按天比例扣减"
            if ruli_hours > 0
            else "入离职缺勤时数为0，不额外扣减"
        )
        final_step = (
            "正班出勤天数为0且存在事假，按线下工资表人工归零口径处理"
            if full_month_personal_leave
            else "按Excel ROUND规则保留2位小数，不额外设置最低金额"
        )

        return CalculationResult(
            employee_id=employee_id,
            employee_name=employee_name,
            amount=final,
            details={
                "部门类别": dept_category,
                "岗位": position,
                "工龄(年)": years,
                "标准": standard,
                "上限": cap,
                "应发": yingfa,
                "事病旷排休时数": spk_hours,
                "入离职缺勤时数": ruli_hours,
                "最终金额": final,
                "exceptions": [item.to_dict() for item in exceptions],
                "audit_explanation": _audit_explanation(
                    amount=final,
                    rule_name="工龄奖标准与缺勤折算",
                    formula="min(标准 × 工龄, 上限) → 按请假与入离职缺勤折算",
                    inputs={
                        **input_snapshot,
                        "部门类别": dept_category,
                        "规则地区": work_area or "未配置",
                        "排班天数": paiban,
                        "实际在职工作日天数": actual_days,
                        "揽收线工龄奖名单人数": len(hrbp_list or []) if dept_category == "揽收" else "不适用",
                    },
                    intermediate_values={
                        "工龄(年)": years,
                        "标准": standard,
                        "上限": cap,
                        "应发": yingfa,
                        "日折算金额": round(day_rate, 6),
                        "事假时数": personal_leave_hours,
                        "病假时数": sick_leave_hours,
                        "旷工天数": absenteeism_days,
                        "旷工时数": absenteeism_hours,
                        "旷工字段口径": absenteeism_source,
                        "旷工折算时数": absenteeism_hours,
                        "排休请假天数": rest_leave_days,
                        "排休请假时数": rest_leave_hours,
                        "排休字段口径": rest_leave_source,
                        "排休请假折算时数": rest_leave_hours,
                        "事病旷排休时数": spk_hours,
                        "入离职缺勤时数": ruli_hours,
                        "全月事假未出勤归零": full_month_personal_leave,
                        "请假折算后金额": _excel_round(after_spk),
                        "入离职折算后金额": _excel_round(after_ruli),
                        "最终金额": final,
                    },
                    steps=[
                        f"部门{department}匹配为{dept_category}",
                        f"岗位{position}匹配工龄奖资格",
                        f"按{ref_date.isoformat()}计算工龄为{years}年",
                        f"应发金额=min({standard}×{years}, {cap})={yingfa}",
                        "事病旷排休时数=事假时数+病假时数+旷工时数+排休请假时数（天数字段按8小时折算）",
                        absence_step,
                        ruli_step,
                        final_step,
                        f"最终工龄奖为{final}",
                    ],
                ),
            },
            warnings=warnings
        )

    def calculate_batch(
        self,
        employees: List[Dict[str, Any]],
        hrbp_list: List[str] = None,
        region_cap: float = None,
        region: str = None,
    ) -> List[CalculationResult]:
        """批量计算工龄奖"""
        return [self.calculate(emp, hrbp_list, region_cap, region) for emp in employees]

    def verify(self, results: List[CalculationResult]) -> Dict[str, Any]:
        """验证计算结果"""
        total = len(results)
        has_bonus = sum(1 for r in results if r.amount > 0)
        total_amount = sum(r.amount for r in results)
        all_warnings = [w for r in results for w in r.warnings]

        return {
            "总人数": total,
            "有工龄奖人数": has_bonus,
            "工龄奖合计金额": total_amount,
            "警告": all_warnings,
        }
