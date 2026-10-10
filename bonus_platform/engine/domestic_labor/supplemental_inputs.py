"""Validate supplemental payroll inputs before any calculation or file persistence."""
from collections import defaultdict
from datetime import date, datetime
import math

from .engines.gaowen_butie import GaoWenBuTieEngine


HIGH_TEMPERATURE_EXCLUSION_REASONS = ("办公地点有空调", "固定排除名单", "岗位不在晋江适用范围")


class SupplementalConfirmationRequired(ValueError):
    def __init__(self, sheets):
        super().__init__("名单为空，请确认本月确实没有相关人员后再核算。")
        self.detail = {"code": "supplemental_empty_confirmation_required", "message": str(self), "sheets": sheets}


def validate_supplemental_confirmation(value):
    if not isinstance(value, dict) or any(key not in {"temperature_exclusions", "housing"} or decision != "none"
                                          for key, decision in value.items()):
        raise ValueError("空名单确认格式错误")
    return dict(value)


def _date(value, label, optional=False):
    if value in (None, "") and optional:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip().replace("/", "-"))
    except ValueError as exc:
        raise ValueError(f"{label}日期无效，请填写 YYYY-MM-DD") from exc


def _employee(row, employees, label):
    employee_id = str(row.get("工号") or "").strip()
    if not employee_id or employee_id not in employees:
        raise ValueError(f"{label}工号未匹配月考勤：{employee_id or '未填工号'}")
    employee = employees[employee_id]
    name = str(row.get("姓名") or "").strip()
    if not name or name != str(employee.get("姓名") or "").strip():
        raise ValueError(f"{label}工号 {employee_id} 的姓名与月考勤不一致或未填写")
    return employee_id, employee


def _check_intervals(records, inclusive, label):
    grouped = defaultdict(list)
    for record in records:
        grouped[record["工号"]].append(record)
    for employee_id, periods in grouped.items():
        ordered = sorted(periods, key=lambda item: item["start"])
        for previous, current in zip(ordered, ordered[1:]):
            end = previous["end"] or date.max
            if current["start"] < end or (inclusive and current["start"] == end):
                raise ValueError(f"{label}工号 {employee_id} 存在重复或重叠日期区间，请核对后再上传")


def prepare_supplemental_inputs(loader, engines, confirmation=None):
    confirmation = validate_supplemental_confirmation(confirmation if confirmation is not None else {})
    employees = {str(row.get("工号") or "").strip(): row for row in loader.monthly.rows}
    raw = loader.supplemental_raw
    empty = []
    summary = {}
    if "gaowen_butie" in engines:
        if loader.temperature is None:
            raise ValueError("高温补贴核算缺少测温登记，请补充当月资料")
        if loader.temperature_exclusions is None:
            raise ValueError("高温补贴核算缺少不享有高温补贴名单；没有人员也请上传带表头的空名单")
        source_months = {loader._month_digits(employee.get("考勤月份")) for employee in employees.values() if employee.get("考勤月份")}
        for index, row in enumerate(raw.get("temperature", []), 1):
            # Legacy office lists placed beside measurement data are still read separately.
            if not any(row.get(key) not in (None, "") for key in ("班次日期", "测温班次", "测温网点", "测温温度")):
                continue
            label = f"测温登记第 {index} 条"
            day = _date(row.get("班次日期"), label)
            if source_months and day.strftime("%Y%m") not in source_months:
                raise ValueError(f"{label}日期不属于本次考勤月份，请核对适用月份")
            if str(row.get("测温班次") or "").strip() not in {"白班", "夜班"}:
                raise ValueError(f"{label}测温班次须为白班或夜班")
            if not str(row.get("测温网点") or "").strip():
                raise ValueError(f"{label}缺少测温网点")
            try:
                temperature = float(row.get("测温温度"))
            except (ValueError, TypeError) as exc:
                raise ValueError(f"{label}测温温度须为数值") from exc
            if not math.isfinite(temperature):
                raise ValueError(f"{label}测温温度须为有限数值")
        # Dates normalized here must reach the engine rather than its silent skip path.
        for row in loader.temperature.rows:
            row["班次日期"] = _date(row.get("班次日期"), "测温登记")
        if not loader.temperature.rows:
            raise ValueError("测温登记没有有效记录，请补充当月测温资料")
        records = []
        for index, row in enumerate(loader.temperature_exclusions.rows, 1):
            label = f"不享有高温补贴名单第 {index} 条"
            employee_id, employee = _employee(row, employees, label)
            area = str(row.get("工作地区") or "").strip()
            if not area or area != str(employee.get("工作地区") or "").strip():
                raise ValueError(f"{label}工号 {employee_id} 的工作地区与月考勤不一致或未填写")
            reason = str(row.get("不享有原因") or "").strip()
            if reason not in HIGH_TEMPERATURE_EXCLUSION_REASONS:
                raise ValueError(f"{label}不享有原因未在已确认规则内：{reason or '未填写'}；过渡性高温补贴继续线下核算")
            if reason != "办公地点有空调" and GaoWenBuTieEngine._qualification(employee)[0] != reason:
                raise ValueError(f"{label}工号 {employee_id} 不符合所填的已确认排除规则")
            start, end = _date(row.get("生效日期"), label), _date(row.get("结束日期"), label, optional=True)
            if end and end < start:
                raise ValueError(f"{label}结束日期早于生效日期")
            records.append({**row, "工号": employee_id, "start": start, "end": end, "不享有原因": reason})
        _check_intervals(records, True, "不享有高温补贴名单")
        loader.validated_temperature_exclusions = records
        summary["temperature_exclusion_rows"] = len(records)
        summary["temperature_exclusion_intervals"] = [{key: value.isoformat() if isinstance(value, date) else value
            for key, value in record.items() if key in {"工号", "姓名", "工作地区", "不享有原因", "start", "end"}} for record in records]
        if not records and confirmation.get("temperature_exclusions") != "none":
            empty.append({"key": "temperature_exclusions", "name": "不享有高温补贴名单", "statement": "本月无额外不享有高温补贴人员"})
        if records and "temperature_exclusions" in confirmation:
            raise ValueError("不享有高温补贴名单已有人员，不能同时确认空名单")
    if "waisu_butie" in engines:
        records = []
        for index, row in enumerate(raw.get("housing", []), 1):
            label = f"住宿名单第 {index} 条"
            employee_id, employee = _employee(row, employees, label)
            start, end = _date(row.get("入住时间") or row.get("入宿时间"), label), _date(row.get("退宿时间") or row.get("离宿时间"), label, optional=True)
            if end and end < start:
                raise ValueError(f"{label}退宿时间早于入住时间")
            records.append({**row, "工号": employee_id, "入住时间": start, "退宿时间": end, "start": start, "end": end})
        _check_intervals(records, False, "住宿名单")
        loader.housing.rows[:] = records
        summary["housing_rows"] = len(records)
        if not records and confirmation.get("housing") != "none":
            empty.append({"key": "housing", "name": "住宿名单", "statement": "本月无住宿人员（包括跨月仍在宿人员）"})
        if records and "housing" in confirmation:
            raise ValueError("住宿名单已有人员，不能同时确认空名单")
    if empty:
        raise SupplementalConfirmationRequired(empty)
    if confirmation:
        summary["supplemental_confirmation"] = confirmation
    return summary
