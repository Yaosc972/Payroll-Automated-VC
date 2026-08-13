"""高温补贴验证版核算引擎。"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .base import BaseEngine, CalculationResult, safe_float
from ..models import AuditExplanation, PayrollException


SUBJECT = "gaowen_butie"
TEMPERATURE_THRESHOLD = 33.0
HIGH_TEMPERATURE_MONTHS = {6, 7, 8, 9, 10}

LIAOBU_SITE = "华南1号枢纽-寮步仓"
FENGGANG_SITE = "华南2号枢纽-凤岗仓"
CHASHAN_SITE = "中国仓组-东莞茶山仓"
QINGXI_SITE = "华南B2B枢纽-清溪仓"
JIASHAN_SITE = "华东枢纽-嘉善仓"
YIWU_SITE = "华东B2B枢纽-义乌仓"
JINJIANG_SITE = "东南枢纽-晋江仓"

DONGGUAN_EXCLUDED_NAMES = {
    "王雯雯", "罗华兰", "李宝兰", "陈西莎", "李伟聪", "黄巧珑", "邱志莹",
    "沈翠娟", "黄彩霞", "刘晓叶", "甘华珍", "曾丽霞", "李发哲", "吴凤玲",
    "廖钰梁", "艾望珍", "凌银来",
}
ZHEJIANG_EXCLUDED_NAMES = {"张青", "盛菊英", "周钰铉", "周钰炫", "叶玉", "樊明雪"}
JINJIANG_EXCLUDED_NAMES = {"陈远远"}
JINJIANG_ELIGIBLE_POSITIONS = {"操作员", "门禁员", "操作组长"}

REGION_STANDARDS = {
    "东莞": {"hourly_rate": 1.725, "daily_cap": 13.8, "monthly_cap": 300.0},
    # 当前线下规则表仍按13.8元/天执行；浙江室内/室外拆分待薪酬组确认后再分流。
    "嘉善": {"hourly_rate": 1.725, "daily_cap": 13.8, "monthly_cap": 300.0},
    "义乌": {"hourly_rate": 1.725, "daily_cap": 13.8, "monthly_cap": 300.0},
    "晋江": {"hourly_rate": 1.5, "daily_cap": 12.0, "monthly_cap": 260.0},
}


@dataclass(frozen=True)
class HighTemperatureDayResult:
    attendance_date: str
    shift: str
    site: str
    temperature: Optional[float]
    attendance_hours: float
    amount: float
    status: str
    reason_code: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _excel_round(value: float, digits: int = 2) -> float:
    quantizer = Decimal("1").scaleb(-digits)
    return float(Decimal(str(value)).quantize(quantizer, rounding=ROUND_HALF_UP))


def _date_value(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    value_text = _text(value)
    if not value_text:
        return None
    for candidate in (value_text[:10], value_text.replace("/", "-")[:10]):
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def _normalize_shift(value: Any) -> str:
    value_text = _text(value)
    if "夜" in value_text or "晚" in value_text or "凌晨" in value_text:
        return "夜班"
    if "白" in value_text or "早" in value_text or "中班" in value_text:
        return "白班"
    return ""


def _attendance_shift(attendance: Mapping[str, Any]) -> str:
    # 测温班次若由上游明确提供可直接使用；日考勤中的班次名称可能含
    # “早上连班”等说明文字，必须优先以真正的排班起始时间判定。
    shift = _normalize_shift(attendance.get("测温班次"))
    if shift:
        return shift

    schedule = _text(attendance.get("班次时间段"))
    match = re.search(r"(?<!\d)(\d{1,2}):(\d{2})", schedule)
    if match:
        hour = int(match.group(1)) % 24
        return "夜班" if hour >= 18 or hour < 6 else "白班"

    for field in ("班次类别名称", "班次名称"):
        shift = _normalize_shift(attendance.get(field))
        if shift:
            return shift

    start_value = attendance.get("上班一")
    if isinstance(start_value, datetime):
        hour = start_value.hour
    else:
        match = re.search(r"(?<!\d)(\d{1,2}):(\d{2})", _text(start_value))
        hour = int(match.group(1)) % 24 if match else -1
    if hour >= 0:
        return "夜班" if hour >= 18 or hour < 6 else "白班"
    return ""


def resolve_temperature_site(employee_data: Mapping[str, Any]) -> str:
    """Resolve the physical measurement warehouse from employee organization fields."""
    work_area = _text(employee_data.get("工作地区"))
    if "嘉善" in work_area:
        return JIASHAN_SITE
    if "义乌" in work_area:
        return YIWU_SITE
    if "晋江" in work_area:
        return JINJIANG_SITE

    organization = "|".join(
        _text(employee_data.get(field))
        for field in (
            "一级部门名称", "二级部门名称", "三级部门名称", "四级部门名称",
            "五级部门名称", "六级部门名称", "部门名称", "部门",
        )
    )
    if "中国仓安全组" in organization or "中国仓组" in organization or "茶山" in organization:
        return CHASHAN_SITE
    if any(keyword in organization for keyword in ("凤岗安全组", "凤岗稽查组", "凤岗安检查验组", "华南2号枢纽", "凤岗")):
        return FENGGANG_SITE
    if "华南B2B枢纽组" in organization or "清溪" in organization:
        return QINGXI_SITE
    if "华南B2B枢纽" in organization:
        return LIAOBU_SITE
    if any(keyword in organization for keyword in ("寮步安全组", "寮步稽查组", "寮步安检查验组", "华南1号枢纽", "寮步")):
        return LIAOBU_SITE
    if any(keyword in organization for keyword in ("操作支持组", "操作风控组", "后勤保障组")):
        return LIAOBU_SITE
    return ""


def _exception(
    code: str,
    employee_id: str,
    employee_name: str,
    message: str,
    suggested_action: str,
) -> PayrollException:
    return PayrollException(
        code=code,
        level="warning",
        subject=SUBJECT,
        employee_id=employee_id,
        employee_name=employee_name,
        message=message,
        suggested_action=suggested_action,
    )


class GaoWenBuTieEngine(BaseEngine):
    """Match attendance to same-site/date/shift temperature and calculate allowance."""

    def __init__(self, temperature_records: Optional[Sequence[Mapping[str, Any]]] = None):
        self.temperature_records = list(temperature_records or [])
        self.temperature_index = self._build_temperature_index(self.temperature_records)

    @staticmethod
    def _build_temperature_index(
        records: Iterable[Mapping[str, Any]],
    ) -> Dict[Tuple[str, date, str], float]:
        index: Dict[Tuple[str, date, str], float] = {}
        for record in records:
            site = _text(record.get("测温网点"))
            day = _date_value(record.get("班次日期") or record.get("日期"))
            shift = _normalize_shift(record.get("测温班次") or record.get("班次"))
            temperature = safe_float(record.get("测温温度"), float("nan"))
            if not site or day is None or not shift or temperature != temperature:
                continue
            key = (site, day, shift)
            index[key] = max(index.get(key, temperature), temperature)
        return index

    @staticmethod
    def _qualification(employee_data: Mapping[str, Any]) -> Tuple[str, str]:
        name = _text(employee_data.get("姓名"))
        work_area = _text(employee_data.get("工作地区"))
        position = _text(employee_data.get("岗位名称") or employee_data.get("岗位"))
        if "东莞" in work_area and name in DONGGUAN_EXCLUDED_NAMES:
            return "固定排除名单", "东莞高温补贴固定排除人员"
        if work_area in {"嘉善", "义乌"} and name in ZHEJIANG_EXCLUDED_NAMES:
            return "固定排除名单", "嘉善/义乌高温补贴固定排除人员"
        if "晋江" in work_area and name in JINJIANG_EXCLUDED_NAMES:
            return "固定排除名单", "晋江HRBP固定排除人员"
        if "晋江" in work_area and position not in JINJIANG_ELIGIBLE_POSITIONS:
            return "岗位不在晋江适用范围", "晋江当前仅操作员、门禁员和操作组长适用"
        return "符合当前适用范围", "忽略职级和领色，按地区固定规则判断"

    @staticmethod
    def _hours(attendance: Mapping[str, Any]) -> Tuple[float, str]:
        regular = max(0.0, safe_float(attendance.get("正班时数")))
        overtime = max(0.0, safe_float(attendance.get("刷卡加班")))
        actual_present = "实际上班时数" in attendance and attendance.get("实际上班时数") not in (None, "")
        # 生产日考勤的“实际上班时数”存在大量零缓存，不能覆盖明确的正班时数。
        # 仅当正班为0且只有系统残留的半小时以内刷卡加班时，按无实际出勤处理。
        if actual_present and safe_float(attendance.get("实际上班时数")) <= 0 and regular <= 0 and overtime <= 0.5:
            return 0.0, "actual_attendance_zero"
        hours = max(regular, overtime)
        return hours, "" if hours > 0 else "no_actual_attendance"

    def calculate(
        self,
        employee_data: Dict[str, Any],
        daily_attendance: Optional[List[Dict[str, Any]]] = None,
    ) -> CalculationResult:
        employee_id = _text(employee_data.get("工号"))
        employee_name = _text(employee_data.get("姓名"))
        work_area = _text(employee_data.get("工作地区"))
        position = _text(employee_data.get("岗位名称") or employee_data.get("岗位"))
        daily_attendance = daily_attendance or []
        standard = REGION_STANDARDS.get(work_area)
        site = resolve_temperature_site(employee_data)
        qualification, qualification_basis = self._qualification(employee_data)
        exceptions: List[PayrollException] = []
        warnings: List[str] = []

        if not self.temperature_records:
            message = "未提供高温测温登记，当前金额仅作待确认的0元结果"
            warnings.append(message)
            exceptions.append(_exception(
                "HIGH_TEMPERATURE_MEASUREMENTS_MISSING",
                employee_id,
                employee_name,
                message,
                "补充当月测温登记后重新核算；任务可继续创建，但当前0元不能作为最终发放结论。",
            ))

        if standard is None:
            message = f"{work_area or '未填写地区'}尚未配置高温补贴标准"
            warnings.append(message)
            exceptions.append(_exception(
                "HIGH_TEMPERATURE_REGION_UNRESOLVED",
                employee_id,
                employee_name,
                message,
                "确认工作地区及适用省份后重新核算；当前不阻止任务创建。",
            ))
            standard = {"hourly_rate": 0.0, "daily_cap": 0.0, "monthly_cap": 0.0}
        elif not site:
            message = "无法根据组织字段识别对应测温网点"
            warnings.append(message)
            exceptions.append(_exception(
                "HIGH_TEMPERATURE_SITE_UNRESOLVED",
                employee_id,
                employee_name,
                message,
                "核对员工组织归属与测温网点映射；不要把漏传测温文件当作无测温区域全额发放。",
            ))

        daily_results: List[Dict[str, Any]] = []
        raw_total = Decimal("0")
        hot_days = 0
        payable_days = 0
        excluded_qualification = qualification != "符合当前适用范围"

        for attendance in daily_attendance:
            attendance_day = _date_value(attendance.get("出勤日期") or attendance.get("日期"))
            shift = _attendance_shift(attendance)
            temperature = self.temperature_index.get((site, attendance_day, shift)) if site and attendance_day and shift else None
            hours, hours_reason = self._hours(attendance)
            status = "excluded"
            reason_code = ""
            amount = Decimal("0")

            if attendance_day is None:
                reason_code = "invalid_attendance_date"
            elif attendance_day.month not in HIGH_TEMPERATURE_MONTHS:
                reason_code = "outside_high_temperature_season"
            elif excluded_qualification:
                reason_code = "employee_or_position_excluded"
            elif not site:
                reason_code = "measurement_site_unresolved"
            elif not shift:
                reason_code = "attendance_shift_unresolved"
            elif hours_reason:
                reason_code = hours_reason
            elif temperature is None:
                reason_code = "no_matching_temperature"
            elif temperature < TEMPERATURE_THRESHOLD:
                reason_code = "temperature_below_33"
            else:
                hot_days += 1
                amount = min(
                    Decimal(str(standard["daily_cap"])),
                    Decimal(str(hours)) * Decimal(str(standard["hourly_rate"])),
                )
                status = "calculated"
                reason_code = "calculated"
                if amount > 0:
                    payable_days += 1
                    raw_total += amount

            daily_results.append(HighTemperatureDayResult(
                attendance_date=attendance_day.isoformat() if attendance_day else "",
                shift=shift,
                site=site,
                temperature=temperature,
                attendance_hours=_excel_round(hours, 4),
                amount=_excel_round(float(amount), 4),
                status=status,
                reason_code=reason_code,
            ).to_dict())

        monthly_before_cap = _excel_round(float(raw_total), 4)
        final_amount = _excel_round(min(float(raw_total), float(standard["monthly_cap"])), 2)
        status_counts: Dict[str, int] = {}
        for row in daily_results:
            status_counts[row["reason_code"]] = status_counts.get(row["reason_code"], 0) + 1

        if status_counts.get("invalid_attendance_date") or status_counts.get("attendance_shift_unresolved"):
            message = "部分日考勤无法识别日期或白/夜班"
            warnings.append(message)
            exceptions.append(_exception(
                "HIGH_TEMPERATURE_ATTENDANCE_UNRESOLVED",
                employee_id,
                employee_name,
                message,
                "核对日考勤日期、班次名称或班次时间段后重新核算。",
            ))

        formula = (
            f"同测温网点、同出勤日期、同白/夜班最高温度≥{TEMPERATURE_THRESHOLD:g}℃时，"
            "当日金额=MIN(MAX(正班时数,刷卡加班)×小时单价,单日封顶)，月度合计再封顶"
        )
        details = {
            "资格判断": qualification,
            "资格依据": qualification_basis,
            "测温网点": site,
            "温度门槛": TEMPERATURE_THRESHOLD,
            "小时单价": standard["hourly_rate"],
            "单日封顶": standard["daily_cap"],
            "月度封顶": standard["monthly_cap"],
            "高温出勤天数": hot_days,
            "计发天数": payable_days,
            "月度封顶前金额": monthly_before_cap,
            "daily_results": daily_results,
            "reason_counts": status_counts,
            "exceptions": [item.to_dict() for item in exceptions],
            "validation_note": (
                "嘉善/义乌当前沿用线下规则表13.8元/天；浙江室内9.2元/室外13.8元的岗位映射待薪酬组确认。"
                if work_area in {"嘉善", "义乌"} else ""
            ),
            "audit_explanation": AuditExplanation(
                subject=SUBJECT,
                amount=final_amount,
                rule_name="高温补贴验证版逐日核算",
                formula=formula,
                inputs={
                    "工号": employee_id,
                    "姓名": employee_name,
                    "工作地区": work_area,
                    "岗位名称": position,
                    "测温网点": site,
                    "日考勤记录数": len(daily_attendance),
                    "测温记录数": len(self.temperature_records),
                    "职级参与计算": False,
                    "领色参与计算": False,
                },
                intermediate_values={
                    "温度门槛": TEMPERATURE_THRESHOLD,
                    "小时单价": standard["hourly_rate"],
                    "单日封顶": standard["daily_cap"],
                    "高温出勤天数": hot_days,
                    "月度封顶前金额": monthly_before_cap,
                    "月度封顶": standard["monthly_cap"],
                },
                steps=[
                    "根据员工工作地区和组织层级识别实际测温网点",
                    "根据班次名称或班次时间段识别白班/夜班",
                    "匹配同网点、同出勤日期、同班次的最高温度",
                    "温度达到33℃且有实际出勤时，取正班时数与刷卡加班较大值",
                    f"按{standard['hourly_rate']:g}元/小时计算，单日封顶{standard['daily_cap']:g}元",
                    f"逐日原始金额求和后，月度封顶{standard['monthly_cap']:g}元并保留2位小数",
                ],
            ).to_dict(),
        }
        return CalculationResult(
            employee_id=employee_id,
            employee_name=employee_name,
            amount=final_amount,
            details=details,
            warnings=warnings,
        )
