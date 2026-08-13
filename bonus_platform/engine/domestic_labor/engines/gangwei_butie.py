"""岗位补贴核算引擎。"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Iterable, List

from .base import BaseEngine, CalculationResult, safe_float
from ..models import AuditExplanation, PayrollException


SUBJECT = "gangwei_butie"
ABSENCE_THRESHOLD_HOURS = 56.0
HOURS_PER_DAY = 8.0

# 标准取自《7月岗位补贴.xlsx》18人线下结果；职级不参与判断。
VERIFIED_POSITION_STANDARDS = {
    "内部初级安检员": 300.0,
    "内部中级安检员": 450.0,
    "内部高级安检员": 650.0,
    "民航初级安检员": 1300.0,
    "民航中级安检员": 1500.0,
    "HRBP专员": 700.0,
    "高级HRBP专员": 700.0,
    "高级招聘专员": 700.0,
    "叉车司机": 800.0,
}

INSPECTOR_POSITIONS = {
    "安检员",
    "内部初级安检员",
    "内部中级安检员",
    "内部高级安检员",
    "民航初级安检员",
    "民航中级安检员",
    "民航高级安检员",
}

# 规则图已确认有资格，但7月线下样本没有可反推的金额标准。
PENDING_STANDARD_POSITIONS = {"安检员", "民航高级安检员", "揽收充电司机"}

SPECIAL_GROUP_LEADERS = {
    "陈晓龙": {"employee_ids": {"OWHN10300"}, "areas": {"东莞"}, "standard": 800.0},
    "贾万": {
        "employee_ids": set(),
        "areas": {"晋江"},
        "standard": 800.0,
        "review_message": "晋江贾万当前按特殊安检组长800元标准暂算，需核对生产线下结果",
    },
}

ABSENCE_FIELDS = (
    ("事假时数", ("事假时数",)),
    ("病假时数", ("病假时数",)),
    ("排休请假时数", ("排休请假时数",)),
    ("旷工时数", ("旷工时数",)),
    ("休年假小时", ("休年假小时", "休年假时数", "年假时数")),
    ("其他假时数（带薪）", ("其他假时数（带薪）", "其他假时数(带薪)", "其他带薪假时数")),
    ("调休时数", ("调休时数",)),
    ("入离职缺勤时数", ("入离职缺勤时数",)),
)


def _excel_round(value: float, digits: int = 2) -> float:
    quantizer = Decimal("1").scaleb(-digits)
    return float(Decimal(str(value)).quantize(quantizer, rounding=ROUND_HALF_UP))


def _first_number(data: Dict[str, Any], aliases: Iterable[str]) -> float:
    for key in aliases:
        if data.get(key) not in (None, ""):
            return max(0.0, safe_float(data.get(key)))
    return 0.0


def _special_leader(employee_id: str, employee_name: str, work_area: str) -> Dict[str, Any] | None:
    rule = SPECIAL_GROUP_LEADERS.get(employee_name)
    if not rule or work_area not in rule["areas"]:
        return None
    employee_ids = rule["employee_ids"]
    if employee_ids and employee_id not in employee_ids:
        return None
    return rule


def _exception(
    code: str,
    level: str,
    employee_id: str,
    employee_name: str,
    message: str,
    suggested_action: str,
) -> PayrollException:
    return PayrollException(
        code=code,
        level=level,
        subject=SUBJECT,
        employee_id=employee_id,
        employee_name=employee_name,
        message=message,
        suggested_action=suggested_action,
    )


class GangWeiBuTieEngine(BaseEngine):
    """按岗位标准、排班天数和56小时缺勤门槛核算岗位补贴。"""

    def calculate(self, employee_data: Dict[str, Any]) -> CalculationResult:
        employee_id = str(employee_data.get("工号", "") or "").strip()
        employee_name = str(employee_data.get("姓名", "") or "").strip()
        work_area = str(employee_data.get("工作地区", "") or "").strip()
        position = str(employee_data.get("岗位名称", "") or "").strip()
        scheduled_days = max(0.0, safe_float(employee_data.get("排班天数")))
        actual_work_days_raw = employee_data.get("实际在职工作日天数")
        actual_work_days_provided = bool(employee_data.get(
            "_实际在职工作日天数已提供",
            actual_work_days_raw not in (None, ""),
        ))
        reported_entry_exit_hours_raw = employee_data.get("入离职缺勤时数")
        reported_entry_exit_hours_provided = bool(employee_data.get(
            "_入离职缺勤时数已提供",
            reported_entry_exit_hours_raw not in (None, ""),
        ))
        warnings: List[str] = []
        exceptions: List[PayrollException] = []

        special = _special_leader(employee_id, employee_name, work_area)
        standard = 0.0
        eligibility = "不享有岗位补贴"
        qualification_basis = "未命中当前岗位补贴范围"

        if special:
            standard = float(special["standard"])
            eligibility = "有资格"
            qualification_basis = "特殊安检组长名单"
            review_message = str(special.get("review_message", "") or "")
            if review_message:
                warnings.append(review_message)
                exceptions.append(_exception(
                    "POSITION_ALLOWANCE_SPECIAL_STANDARD_PENDING",
                    "warning",
                    employee_id,
                    employee_name,
                    review_message,
                    "保留暂算金额，并由薪酬组用晋江生产线下结果确认特殊标准。",
                ))
        elif work_area == "东莞" and position in VERIFIED_POSITION_STANDARDS:
            standard = VERIFIED_POSITION_STANDARDS[position]
            eligibility = "有资格"
            qualification_basis = "东莞已验证岗位标准"
        elif work_area in {"嘉善", "义乌"} and position in INSPECTOR_POSITIONS:
            if position in VERIFIED_POSITION_STANDARDS:
                standard = VERIFIED_POSITION_STANDARDS[position]
                eligibility = "有资格"
                qualification_basis = f"{work_area}持证安检岗位；标准沿用已验证岗位名称"
            else:
                eligibility = "有资格，标准待确认"
                qualification_basis = f"{work_area}持证安检岗位"
        elif work_area == "东莞" and position in PENDING_STANDARD_POSITIONS:
            eligibility = "有资格，标准待确认"
            qualification_basis = "东莞规则图已确认岗位资格"

        inputs = {
            "工号": employee_id,
            "姓名": employee_name,
            "工作地区": work_area,
            "岗位名称": position,
            "排班天数": scheduled_days,
            "实际在职工作日天数": actual_work_days_raw if actual_work_days_provided else "未提供",
            "月考勤入离职缺勤时数": reported_entry_exit_hours_raw if reported_entry_exit_hours_provided else "未提供",
            "职级": employee_data.get("职级", ""),
        }

        if eligibility == "不享有岗位补贴":
            return self._result(
                employee_id,
                employee_name,
                0.0,
                warnings,
                exceptions,
                eligibility,
                qualification_basis,
                standard,
                scheduled_days,
                {},
                0.0,
                0.0,
                inputs,
                "岗位补贴资格判断",
                [f"工作地区为{work_area or '未填写'}，岗位为{position or '未填写'}", "未命中岗位补贴范围，应发0元"],
            )

        if standard <= 0:
            message = f"{work_area}{position}有岗位补贴资格，但金额标准待确认"
            warnings.append(message)
            exceptions.append(_exception(
                "POSITION_ALLOWANCE_STANDARD_PENDING",
                "warning",
                employee_id,
                employee_name,
                message,
                "由薪酬组确认该岗位月度标准后重新核算；不得按职级或相邻岗位自行套档。",
            ))
            return self._result(
                employee_id,
                employee_name,
                0.0,
                warnings,
                exceptions,
                eligibility,
                qualification_basis,
                standard,
                scheduled_days,
                {},
                0.0,
                0.0,
                inputs,
                "岗位补贴标准待确认",
                [f"已确认{position}有岗位补贴资格", "没有真实线下样本可确定金额标准，暂不计金额"],
            )

        if scheduled_days <= 0:
            message = "排班天数为空或为0，无法核算岗位补贴"
            warnings.append(message)
            exceptions.append(_exception(
                "POSITION_ALLOWANCE_SCHEDULE_DAYS_INVALID",
                "blocking",
                employee_id,
                employee_name,
                message,
                "核对月考勤排班天数后重新核算。",
            ))
            return self._result(
                employee_id,
                employee_name,
                0.0,
                warnings,
                exceptions,
                eligibility,
                qualification_basis,
                standard,
                scheduled_days,
                {},
                0.0,
                0.0,
                inputs,
                "岗位补贴排班天数校验",
                ["岗位有发放资格", "排班天数无效，无法作为折算分母，金额暂为0元"],
            )

        absence_breakdown = {
            label: _first_number(employee_data, aliases)
            for label, aliases in ABSENCE_FIELDS
        }
        reported_entry_exit_hours = _first_number(employee_data, ("入离职缺勤时数",))
        if reported_entry_exit_hours_provided and reported_entry_exit_hours > 0:
            entry_exit_hours = reported_entry_exit_hours
            entry_exit_source = "月考勤已有值"
        elif actual_work_days_provided:
            actual_work_days = max(0.0, safe_float(actual_work_days_raw))
            entry_exit_hours = max(scheduled_days - actual_work_days, 0.0) * HOURS_PER_DAY
            entry_exit_source = "按排班天数与实际在职工作日天数自动计算"
        else:
            entry_exit_hours = 0.0
            entry_exit_source = "实际在职工作日天数缺失，暂按0小时"
            message = "实际在职工作日天数缺失，入离职缺勤暂按0小时核算"
            exceptions.append(_exception(
                "POSITION_ALLOWANCE_ENTRY_EXIT_ABSENCE_PENDING",
                "info",
                employee_id,
                employee_name,
                message,
                "核对月考勤中的实际在职工作日天数；当前结果不阻止核算，确认后可重新核算。",
            ))
        absence_breakdown["入离职缺勤时数"] = entry_exit_hours
        womens_day_leave_days = _first_number(employee_data, ("女神假天数",))
        womens_day_leave_hours = womens_day_leave_days * HOURS_PER_DAY
        absence_breakdown["女神假折算时数"] = womens_day_leave_hours
        absence_hours = sum(absence_breakdown.values())
        deduction_hours = absence_hours if absence_hours >= ABSENCE_THRESHOLD_HOURS else 0.0
        deduction_days = deduction_hours / HOURS_PER_DAY
        payable_days = max(0.0, scheduled_days - deduction_days)
        amount = _excel_round(standard / scheduled_days * payable_days, 2)

        steps = [
            f"按工作地区、岗位名称和特殊人员判断资格，职级不参与；月度标准为{_excel_round(standard, 2)}元",
            (
                f"月考勤已有入离职缺勤{entry_exit_hours:g}小时，直接使用"
                if entry_exit_source == "月考勤已有值"
                else (
                    f"入离职缺勤=({scheduled_days:g}个排班日−{max(0.0, safe_float(actual_work_days_raw)):g}个实际在职工作日)×8={entry_exit_hours:g}小时"
                    if actual_work_days_provided
                    else "实际在职工作日天数未提供，入离职缺勤暂按0小时并提示确认"
                )
            ),
            f"女神假{womens_day_leave_days:g}天×8小时，折算为{womens_day_leave_hours:g}小时",
            f"九类缺勤合计{absence_hours:g}小时",
        ]
        if deduction_hours:
            steps.append(f"缺勤达到56小时，全部{deduction_hours:g}小时÷8，扣减{deduction_days:g}天")
        else:
            steps.append("缺勤未达到56小时，不扣减岗位补贴天数")
        steps.append(
            f"{standard:g}÷{scheduled_days:g}×({scheduled_days:g}−{deduction_days:g})，四舍五入后应发{amount:.2f}元"
        )

        return self._result(
            employee_id,
            employee_name,
            amount,
            warnings,
            exceptions,
            eligibility,
            qualification_basis,
            standard,
            scheduled_days,
            absence_breakdown,
            absence_hours,
            deduction_days,
            inputs,
            "岗位补贴月度核算",
            steps,
            entry_exit_source,
        )

    @staticmethod
    def _result(
        employee_id: str,
        employee_name: str,
        amount: float,
        warnings: List[str],
        exceptions: List[PayrollException],
        eligibility: str,
        qualification_basis: str,
        standard: float,
        scheduled_days: float,
        absence_breakdown: Dict[str, float],
        absence_hours: float,
        deduction_days: float,
        inputs: Dict[str, Any],
        rule_name: str,
        steps: List[str],
        entry_exit_source: str = "",
    ) -> CalculationResult:
        womens_day_hours = absence_breakdown.get("女神假折算时数", 0.0)
        payable_days = max(0.0, scheduled_days - deduction_days)
        formula = "岗位补贴标准÷排班天数×(排班天数−达到56小时后扣减的全部缺勤时数÷8)"
        audit = AuditExplanation(
            subject=SUBJECT,
            amount=amount,
            rule_name=rule_name,
            formula=formula,
            inputs={**inputs, **absence_breakdown},
            intermediate_values={
                "岗位补贴标准": standard,
                "入离职缺勤时数来源": entry_exit_source,
                "女神假折算时数": womens_day_hours,
                "缺勤合计时数": absence_hours,
                "扣减天数": deduction_days,
                "岗位补贴计发天数": payable_days,
            },
            steps=steps,
        ).to_dict()
        details = {
            "资格判断": eligibility,
            "资格依据": qualification_basis,
            "职级参与计算": False,
            "岗位补贴标准": standard,
            "排班天数": scheduled_days,
            "入离职缺勤时数来源": entry_exit_source,
            "女神假折算时数": womens_day_hours,
            "缺勤明细": absence_breakdown,
            "缺勤合计时数": absence_hours,
            "扣减天数": deduction_days,
            "岗位补贴计发天数": payable_days,
            "exceptions": [item.to_dict() for item in exceptions],
            "audit_explanation": audit,
        }
        return CalculationResult(
            employee_id=employee_id,
            employee_name=employee_name,
            amount=amount,
            details=details,
            warnings=warnings,
        )
