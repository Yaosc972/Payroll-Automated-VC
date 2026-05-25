from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from math import trunc
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .models import (
    CalculationResult,
    ImportRow,
    RecruitmentDetail,
    add_months,
    as_date,
    as_number,
    as_text,
    yyyymm,
)
from .rules import RuleBook


CURRENT_EMPLOYEE_STATUSES = {"正式", "试用", "待入职", "在职", "正式在职", "试用在职"}
EMPTY_MARKERS = {"", "-"}
DEVELOPED_LOCATION_TOKENS = {
    "德国", "捷克", "美国", "英国", "法国", "加拿大", "日本", "韩国", "荷兰",
    "意大利", "西班牙", "葡萄牙", "奥地利", "瑞士", "比利时", "卢森堡",
    "丹麦", "瑞典", "挪威", "芬兰", "爱尔兰", "澳大利亚", "新西兰",
    "新加坡", "以色列", "波兰",
    "germany", "czech", "united states", "usa", "u.s.", "america", "uk",
    "united kingdom", "england", "france", "canada", "japan", "korea",
    "netherlands", "holland", "italy", "spain", "portugal", "austria",
    "switzerland", "belgium", "luxembourg", "denmark", "sweden", "norway",
    "finland", "ireland", "australia", "new zealand", "singapore", "israel",
    "poland",
}


def calculate(rows: Iterable[ImportRow], rules: RuleBook, *, allow_legacy_overrides: bool = False) -> CalculationResult:
    imported_rows = [row for row in rows if _has_employee(row)]
    month = _detect_month(imported_rows)
    employee_counts = _employee_counts(imported_rows)

    details = [
        _calculate_row(row, rules, month, employee_counts, allow_legacy_overrides)
        for row in imported_rows
    ]

    for detail in details:
        detail.exceptions = [
            message for message in detail.exceptions
            if _is_current_month_exception(detail, message, month)
        ]

    exceptions = _build_exception_rows(details)
    pending_confirmations = _build_pending_confirmations(details, month)
    return CalculationResult(
        month=month,
        details=details,
        recruitment_summary=_build_recruitment_summary(details, month, pending_confirmations),
        referral_summary=_build_referral_summary(details, month, pending_confirmations),
        pending_confirmations=pending_confirmations,
        exceptions=exceptions,
    )


def _has_employee(row: ImportRow) -> bool:
    return any(row.text(field) for field in ("工号", "姓名", "候选人入职时间", "招聘负责人工号", "推荐人工号"))


def _detect_month(rows: List[ImportRow]) -> int:
    for row in rows:
        month = as_number(row.get("核算月份"))
        if month:
            return int(month)
    today = datetime.today()
    return today.year * 100 + today.month


def _employee_counts(rows: List[ImportRow]) -> Dict[str, int]:
    counts: Dict[str, int] = defaultdict(int)
    for row in rows:
        employee_no = row.text("工号")
        if employee_no:
            counts[employee_no] += 1
    return counts


def _calculate_row(
    row: ImportRow,
    rules: RuleBook,
    month: int,
    employee_counts: Dict[str, int],
    allow_legacy_overrides: bool,
) -> RecruitmentDetail:
    employee_no = row.text("工号")
    name = row.text("姓名")
    grade = row.text("职级")
    category = row.text("ABC类别")
    channel = row.text("招聘渠道")
    label = _label(row)
    start_date = as_date(row.get("招聘启动日期"))
    onboard_date = as_date(row.get("候选人入职时间")) or as_date(row.get("入职日期"))
    probation_date = as_date(row.get("转正日期"))
    last_work_date = as_date(row.get("最后工作日"))
    exclusion_days = as_number(row.get("周期剔除天数"))

    standard_cycle = rules.cycle(label, category, grade)
    standard_bonus, currency = rules.recruitment(label, category, grade)
    channel_ratio = rules.channel(channel)
    actual_cycle = _date_diff(onboard_date, start_date)
    if actual_cycle is not None:
        actual_cycle -= exclusion_days
    cycle_diff = actual_cycle - standard_cycle if actual_cycle is not None and standard_cycle is not None else None
    adjusted_total = _adjusted_recruitment_bonus(standard_bonus, channel_ratio, cycle_diff)

    assistant_id = row.text("协助招聘人工号")
    has_assistant = assistant_id not in EMPTY_MARKERS
    recruiter_base = adjusted_total * (0.7 if has_assistant else 1.0)
    assistant_base = adjusted_total * 0.3 if has_assistant else 0.0

    first_ratio = _recruit_first_ratio(label, category)
    three_ratio = _recruit_three_ratio(label, category)
    six_ratio = _recruit_six_ratio(label, category)
    probation_ratio = _recruit_probation_ratio(label, category)

    recruiter_1m = _amount(row, "招聘人入职1月发放金额_覆盖", round(recruiter_base * first_ratio, 2), allow_legacy_overrides)
    recruiter_3m = _amount(row, "招聘人入职3月发放金额_覆盖", round(recruiter_base * three_ratio, 2), allow_legacy_overrides)
    recruiter_6m = _amount(row, "招聘人入职6月发放金额_覆盖", round(recruiter_base * six_ratio, 2), allow_legacy_overrides)
    recruiter_probation = _amount(row, "招聘人转正发放金额_覆盖", round(recruiter_base * probation_ratio, 2), allow_legacy_overrides)
    assistant_1m = _amount(row, "协助人入职1月发放金额_覆盖", round(assistant_base * first_ratio, 2), allow_legacy_overrides)
    assistant_3m = _amount(row, "协助人入职3月发放金额_覆盖", round(assistant_base * three_ratio, 2), allow_legacy_overrides)
    assistant_6m = _amount(row, "协助人入职6月发放金额_覆盖", round(assistant_base * six_ratio, 2), allow_legacy_overrides)
    assistant_probation = _amount(row, "协助人转正发放金额_覆盖", round(assistant_base * probation_ratio, 2), allow_legacy_overrides)

    referrer_id = row.text("推荐人工号")
    recruiter_status = _status_value(row, "招聘负责人人员状态", "招聘负责人状态")
    assistant_status = _status_value(row, "协助招聘人人员状态", "协助招聘人状态")
    has_referrer = referrer_id not in EMPTY_MARKERS
    referrer_is_manager = "是" if has_referrer and referrer_id in _manager_ids(row) else "否"
    referrer_disqualified = _referrer_disqualified(row)
    referral_scope = _referral_scope(row)
    referral_rule_region = _referral_rule_region(row, referral_scope)
    referral_rule = rules.referral(referral_scope, referral_rule_region, category, grade) if has_referrer else None
    referral_payable = has_referrer and referrer_is_manager == "否" and not referrer_disqualified and referral_rule is not None
    referral_standard = referral_rule.amount if referral_rule else 0.0
    referral_1m = _amount(row, "内推入职1月发放金额_覆盖", round(referral_standard * referral_rule.ratio_1m, 2) if referral_payable else 0.0, allow_legacy_overrides)
    referral_3m = _amount(row, "内推入职3月发放金额_覆盖", round(referral_standard * referral_rule.ratio_3m, 2) if referral_payable else 0.0, allow_legacy_overrides)
    referral_6m = _amount(row, "内推入职6月发放金额_覆盖", round(referral_standard * referral_rule.ratio_6m, 2) if referral_payable else 0.0, allow_legacy_overrides)
    referral_probation = _amount(row, "内推转正发放金额_覆盖", round(referral_standard * referral_rule.ratio_probation, 2) if referral_payable else 0.0, allow_legacy_overrides)

    exceptions = _exceptions(
        row=row,
        employee_no=employee_no,
        employee_counts=employee_counts,
        grade=grade,
        category=category,
        channel=channel,
        start_date=start_date,
        onboard_date=onboard_date,
        standard_cycle=standard_cycle,
        standard_bonus=standard_bonus,
        has_referrer=has_referrer,
        referrer_is_manager=referrer_is_manager,
        referrer_disqualified=referrer_disqualified,
        referral_rule=referral_rule,
    )

    return RecruitmentDetail(
        row_no=row.source_row,
        name=name,
        employee_no=employee_no,
        status=row.text("人员状态"),
        location=row.text("工作地"),
        grade=grade,
        category=category,
        channel=channel,
        recruiter_id=row.text("招聘负责人工号"),
        recruiter_name=row.text("招聘负责人姓名"),
        recruiter_status=recruiter_status,
        recruiter_last_work_date=row.get("招聘负责人最后工作日") or row.get("招聘负责人离职日期"),
        assistant_id=assistant_id,
        assistant_name=row.text("协助招聘人姓名"),
        assistant_status=assistant_status,
        assistant_last_work_date=row.get("协助招聘人最后工作日") or row.get("协助招聘负责人最后工作日") or row.get("协助招聘人离职日期"),
        start_date=start_date,
        onboard_date=onboard_date,
        probation_date=probation_date,
        label=label,
        standard_cycle_days=standard_cycle or 0.0,
        actual_cycle_days=actual_cycle,
        cycle_diff_days=cycle_diff,
        channel_ratio=channel_ratio,
        standard_bonus=standard_bonus,
        adjusted_total_bonus=round(adjusted_total, 2),
        recruiter_bonus_base=round(recruiter_base, 2),
        recruiter_1m_bonus=recruiter_1m,
        recruiter_1m_period=_period(row, "招聘人入职1月发放周期_覆盖", _period_after(onboard_date, 1, recruiter_1m, last_work_date), allow_legacy_overrides),
        recruiter_3m_bonus=recruiter_3m,
        recruiter_3m_period=_period(row, "招聘人入职3月发放周期_覆盖", _period_after(onboard_date, 3, recruiter_3m, last_work_date), allow_legacy_overrides),
        recruiter_6m_bonus=recruiter_6m,
        recruiter_6m_period=_period(row, "招聘人入职6月发放周期_覆盖", _period_after(onboard_date, 6, recruiter_6m, last_work_date), allow_legacy_overrides),
        recruiter_probation_bonus=recruiter_probation,
        recruiter_probation_period=_period(row, "招聘人转正发放周期_覆盖", _probation_period(probation_date, recruiter_probation, last_work_date), allow_legacy_overrides),
        assistant_bonus_base=round(assistant_base, 2),
        assistant_1m_bonus=assistant_1m,
        assistant_1m_period=_period(row, "协助人入职1月发放周期_覆盖", _period_after(onboard_date, 1, assistant_1m, last_work_date), allow_legacy_overrides),
        assistant_3m_bonus=assistant_3m,
        assistant_3m_period=_period(row, "协助人入职3月发放周期_覆盖", _period_after(onboard_date, 3, assistant_3m, last_work_date), allow_legacy_overrides),
        assistant_6m_bonus=assistant_6m,
        assistant_6m_period=_period(row, "协助人入职6月发放周期_覆盖", _period_after(onboard_date, 6, assistant_6m, last_work_date), allow_legacy_overrides),
        assistant_probation_bonus=assistant_probation,
        assistant_probation_period=_period(row, "协助人转正发放周期_覆盖", _probation_period(probation_date, assistant_probation, last_work_date), allow_legacy_overrides),
        currency=currency or (referral_rule.currency if referral_rule else ""),
        referrer_name=row.text("推荐人姓名"),
        referrer_id=referrer_id,
        referrer_status=_status_value(row, "推荐人人员状态", "推荐人状态"),
        referrer_is_manager=referrer_is_manager,
        referral_rule_scope=referral_scope,
        referral_standard_bonus=referral_standard,
        referral_1m_bonus=referral_1m,
        referral_1m_period=_period(row, "内推入职1月发放周期_覆盖", _period_after(onboard_date, 1, referral_1m, last_work_date), allow_legacy_overrides),
        referral_3m_bonus=referral_3m,
        referral_3m_period=_period(row, "内推入职3月发放周期_覆盖", _period_after(onboard_date, 3, referral_3m, last_work_date), allow_legacy_overrides),
        referral_6m_bonus=referral_6m,
        referral_6m_period=_period(row, "内推入职6月发放周期_覆盖", _period_after(onboard_date, 6, referral_6m, last_work_date), allow_legacy_overrides),
        referral_probation_bonus=referral_probation,
        referral_probation_period=_period(row, "内推转正发放周期_覆盖", _probation_period(probation_date, referral_probation, last_work_date), allow_legacy_overrides),
        exceptions=exceptions,
    )


def _label(row: ImportRow) -> str:
    label = row.text("标签分类")
    if label:
        return label
    location = row.text("工作地")
    return "国内" if "中国" in location or "大陆" in location else "海外"


def _date_diff(later: Optional[datetime], earlier: Optional[datetime]) -> Optional[float]:
    if not later or not earlier:
        return None
    return float((later - earlier).days)


def _adjusted_recruitment_bonus(standard_bonus: float, channel_ratio: float, cycle_diff: Optional[float]) -> float:
    if not standard_bonus or cycle_diff is None:
        return 0.0
    base = standard_bonus * channel_ratio
    raw = base * (1 - trunc(cycle_diff / 10) * 0.1)
    return max(base * 0.3, min(base * 1.3, raw))


def _recruit_first_ratio(label: str, category: str) -> float:
    if label == "国内" and category in {"A类", "B类"}:
        return 0.2
    if label == "海外" and category in {"A类", "B类"}:
        return 0.3
    if category in {"C类", "C1类"}:
        return 0.5
    return 0.0


def _recruit_three_ratio(label: str, category: str) -> float:
    if label != "海外":
        return 0.0
    if category == "A类":
        return 0.3
    if category == "B类":
        return 0.7
    if category == "C1类":
        return 0.5
    return 0.0


def _recruit_six_ratio(label: str, category: str) -> float:
    return 0.4 if label == "海外" and category == "A类" else 0.0


def _recruit_probation_ratio(label: str, category: str) -> float:
    if label != "国内":
        return 0.0
    if category in {"A类", "B类"}:
        return 0.8
    if category == "C类":
        return 0.5
    return 0.0


def _period_after(onboard_date: Optional[datetime], months: int, amount: float, last_work_date: Optional[datetime] = None) -> Any:
    if not amount:
        return ""
    due_date = _full_month_date(onboard_date, months)
    if not due_date:
        return ""
    if last_work_date and last_work_date < due_date:
        return "-"
    return yyyymm(due_date) or ""


def _amount(row: ImportRow, field: str, calculated: float, allow_legacy_overrides: bool) -> float:
    if not allow_legacy_overrides:
        return calculated
    return _override_amount(row, field, calculated)


def _override_amount(row: ImportRow, field: str, calculated: float) -> float:
    raw_value = row.get(field)
    if raw_value in (None, ""):
        return calculated
    return round(as_number(raw_value), 2)


def _period(row: ImportRow, field: str, calculated: Any, allow_legacy_overrides: bool) -> Any:
    if not allow_legacy_overrides:
        return calculated
    return _override_period(row, field, calculated)


def _override_period(row: ImportRow, field: str, calculated: Any) -> Any:
    raw_value = row.get(field)
    if raw_value in (None, ""):
        return calculated
    if isinstance(raw_value, float) and raw_value.is_integer():
        return int(raw_value)
    return raw_value


def _probation_period(probation_date: Optional[datetime], amount: float, last_work_date: Optional[datetime] = None) -> Any:
    if not amount:
        return ""
    if probation_date and last_work_date and yyyymm(last_work_date) == yyyymm(probation_date):
        return "-"
    return yyyymm(probation_date) or "未转正，待发放"


def _full_month_date(onboard_date: Optional[datetime], months: int) -> Optional[datetime]:
    due_date = add_months(onboard_date, months)
    return due_date - timedelta(days=1) if due_date else None


def _manager_ids(row: ImportRow) -> set[str]:
    fields = ["直接上级工号", "间接上级1工号", "间接上级2工号", "间接上级3工号", "间接上级4工号"]
    return {row.text(field) for field in fields if row.text(field)}


def _referral_scope(row: ImportRow) -> str:
    explicit_scope = row.text("特殊地区规则")
    if explicit_scope in {"FBU德国", "FBU捷克"}:
        return explicit_scope
    return "集团统一"


def _referral_rule_region(row: ImportRow, scope: str) -> str:
    if scope != "集团统一":
        return scope
    return _normalized_referral_region(row)


def _normalized_referral_region(row: ImportRow) -> str:
    location = row.text("工作地")
    location_lower = location.lower()
    if any(token in location for token in ("中国", "大陆")) or location == "国内":
        return "国内发展中国家"
    if any(token in location_lower for token in DEVELOPED_LOCATION_TOKENS):
        return "海外发达国家"
    imported_region = row.text("奖金地区类型")
    if imported_region:
        return imported_region
    return "海外发展中国家" if location else ""


def _referrer_disqualified(row: ImportRow) -> bool:
    referrer_grade = row.text("推荐人职级").upper()
    if referrer_grade.startswith(("P4", "P5", "M4", "M5")):
        return True
    referrer_position = row.text("推荐人职位")
    return "招聘" in referrer_position or "HRBP" in referrer_position.upper()


def _exceptions(
    row: ImportRow,
    employee_no: str,
    employee_counts: Dict[str, int],
    grade: str,
    category: str,
    channel: str,
    start_date: Optional[datetime],
    onboard_date: Optional[datetime],
    standard_cycle: Optional[float],
    standard_bonus: float,
    has_referrer: bool,
    referrer_is_manager: str,
    referrer_disqualified: bool,
    referral_rule: Any,
) -> List[str]:
    messages: List[str] = []
    if employee_no and employee_counts.get(employee_no, 0) > 1:
        messages.append("工号重复")
    if not all([grade, category, channel, start_date, onboard_date]):
        messages.append("招聘奖金缺关键字段")
    if standard_cycle is None:
        messages.append("未匹配招聘周期")
    if not standard_bonus:
        messages.append("未匹配招聘奖金标准")
    if has_referrer and referrer_is_manager == "是":
        messages.append("推荐人为直接/间接上级，不计内推")
    if has_referrer and referrer_disqualified:
        messages.append("推荐人为招聘岗/HRBP或P4/M4及以上，不计内推")
    if has_referrer and not row.text("特殊地区规则") and any(token in row.text("工作地") for token in ("德国", "捷克")):
        messages.append("工作地为德国/捷克，需确认是否适用FBU特殊内推规则")
    if has_referrer and referrer_is_manager != "是" and not referral_rule:
        messages.append("未匹配内推规则或不满足资格")
    referrer_status = row.text("推荐人人员状态")
    if has_referrer and referrer_status and referrer_status not in CURRENT_EMPLOYEE_STATUSES:
        messages.append("推荐人非正式在职，需确认")
    return messages


def _build_exception_rows(details: List[RecruitmentDetail]) -> List[Dict[str, Any]]:
    rows = []
    for detail in details:
        for message in detail.exceptions:
            rows.append(
                {
                    "源行号": detail.row_no,
                    "姓名": detail.name,
                    "工号": detail.employee_no,
                    "异常类型": message,
                    "处理建议": _exception_advice(message),
                }
            )
    return rows


def _is_current_month_exception(detail: RecruitmentDetail, message: str, month: int) -> bool:
    has_recruitment_payment = any(period == month for period, _amount in detail.monthly_recruitment_amounts)
    has_referral_payment = any(period == month for period, _amount in detail.monthly_referral_amounts)
    if message in {"工号重复", "招聘奖金缺关键字段", "未匹配招聘周期", "未匹配招聘奖金标准"}:
        return has_recruitment_payment
    if "推荐" in message or "内推" in message:
        return has_referral_payment
    return has_recruitment_payment or has_referral_payment


def _exception_advice(message: str) -> str:
    if "内推" in message or "推荐" in message:
        return "复核推荐人资格、地区规则和上下级关系。"
    if "重复" in message:
        return "检查是否重复导入或员工工号是否填写错误。"
    return "补充字段或维护规则表后重新计算。"


def _build_recruitment_summary(details: List[RecruitmentDetail], month: int, pending_confirmations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    summary: Dict[Tuple[str, str, str, str], Dict[str, Any]] = {}
    pending_keys = _pending_keys(pending_confirmations)
    for detail in details:
        _add_recruiter_summary(
            summary,
            detail=detail,
            person_id=detail.recruiter_id,
            person_name=detail.recruiter_name,
            role="招聘负责人",
            currency=detail.currency,
            month=month,
            pending_keys=pending_keys,
            amounts=[
                (detail.recruiter_1m_period, detail.recruiter_1m_bonus, "入职1月奖金"),
                (detail.recruiter_3m_period, detail.recruiter_3m_bonus, "入职3月奖金"),
                (detail.recruiter_6m_period, detail.recruiter_6m_bonus, "入职6月奖金"),
                (detail.recruiter_probation_period, detail.recruiter_probation_bonus, "转正奖金"),
            ],
        )
        _add_recruiter_summary(
            summary,
            detail=detail,
            person_id=detail.assistant_id,
            person_name=detail.assistant_name,
            role="协助招聘人",
            currency=detail.currency,
            month=month,
            pending_keys=pending_keys,
            amounts=[
                (detail.assistant_1m_period, detail.assistant_1m_bonus, "入职1月奖金"),
                (detail.assistant_3m_period, detail.assistant_3m_bonus, "入职3月奖金"),
                (detail.assistant_6m_period, detail.assistant_6m_bonus, "入职6月奖金"),
                (detail.assistant_probation_period, detail.assistant_probation_bonus, "转正奖金"),
            ],
        )
    return _summary_values(summary)


def _add_recruiter_summary(
    summary: Dict[Tuple[str, str, str, str], Dict[str, Any]],
    detail: RecruitmentDetail,
    person_id: str,
    person_name: str,
    role: str,
    currency: str,
    month: int,
    pending_keys: set[Tuple[int, str, str]],
    amounts: List[Tuple[Any, float, str]],
) -> None:
    if person_id in EMPTY_MARKERS:
        return
    key = (person_id, person_name, role, currency)
    row = summary.setdefault(
        key,
        {"工号": person_id, "姓名": person_name, "角色": role, "币种": currency, "核算月份": month, "入职1月奖金": 0.0, "入职3月奖金": 0.0, "入职6月奖金": 0.0, "转正奖金": 0.0, "合计发放": 0.0},
    )
    for period, amount, field in amounts:
        if period == month and amount:
            if _node_key(detail, role, field) in pending_keys:
                continue
            row[field] += amount
            row["合计发放"] += amount


def _build_referral_summary(details: List[RecruitmentDetail], month: int, pending_confirmations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    summary: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    pending_keys = _pending_keys(pending_confirmations)
    for detail in details:
        if detail.referrer_id in EMPTY_MARKERS:
            continue
        key = (detail.referrer_id, detail.referrer_name, detail.currency)
        row = summary.setdefault(
            key,
            {"推荐人工号": detail.referrer_id, "推荐人姓名": detail.referrer_name, "币种": detail.currency, "核算月份": month, "入职1月奖金": 0.0, "入职3月奖金": 0.0, "入职6月奖金": 0.0, "转正奖金": 0.0, "合计发放": 0.0},
        )
        for period, amount, field in [
            (detail.referral_1m_period, detail.referral_1m_bonus, "入职1月奖金"),
            (detail.referral_3m_period, detail.referral_3m_bonus, "入职3月奖金"),
            (detail.referral_6m_period, detail.referral_6m_bonus, "入职6月奖金"),
            (detail.referral_probation_period, detail.referral_probation_bonus, "转正奖金"),
        ]:
            if period == month and amount:
                if _node_key(detail, "推荐人", field) in pending_keys:
                    continue
                row[field] += amount
                row["合计发放"] += amount
    return _summary_values(summary)


def _summary_values(summary: Dict[Tuple[str, ...], Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = list(summary.values())
    return [row for row in rows if row.get("合计发放")]


def _build_pending_confirmations(details: List[RecruitmentDetail], month: int) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for detail in details:
        _append_pending_nodes(
            rows,
            detail,
            month,
            role="招聘负责人",
            person_id=detail.recruiter_id,
            person_name=detail.recruiter_name,
            person_status=detail.recruiter_status,
            node_type="招聘奖金",
            amounts=[
                (detail.recruiter_1m_period, detail.recruiter_1m_bonus, "入职1月奖金"),
                (detail.recruiter_3m_period, detail.recruiter_3m_bonus, "入职3月奖金"),
                (detail.recruiter_6m_period, detail.recruiter_6m_bonus, "入职6月奖金"),
                (detail.recruiter_probation_period, detail.recruiter_probation_bonus, "转正奖金"),
            ],
        )
        _append_pending_nodes(
            rows,
            detail,
            month,
            role="协助招聘人",
            person_id=detail.assistant_id,
            person_name=detail.assistant_name,
            person_status=detail.assistant_status,
            node_type="招聘奖金",
            amounts=[
                (detail.assistant_1m_period, detail.assistant_1m_bonus, "入职1月奖金"),
                (detail.assistant_3m_period, detail.assistant_3m_bonus, "入职3月奖金"),
                (detail.assistant_6m_period, detail.assistant_6m_bonus, "入职6月奖金"),
                (detail.assistant_probation_period, detail.assistant_probation_bonus, "转正奖金"),
            ],
        )
        _append_pending_nodes(
            rows,
            detail,
            month,
            role="推荐人",
            person_id=detail.referrer_id,
            person_name=detail.referrer_name,
            person_status=detail.referrer_status,
            node_type="内推奖金",
            amounts=[
                (detail.referral_1m_period, detail.referral_1m_bonus, "入职1月奖金"),
                (detail.referral_3m_period, detail.referral_3m_bonus, "入职3月奖金"),
                (detail.referral_6m_period, detail.referral_6m_bonus, "入职6月奖金"),
                (detail.referral_probation_period, detail.referral_probation_bonus, "转正奖金"),
            ],
        )
    return rows


def _append_pending_nodes(
    rows: List[Dict[str, Any]],
    detail: RecruitmentDetail,
    month: int,
    role: str,
    person_id: str,
    person_name: str,
    person_status: str,
    node_type: str,
    amounts: List[Tuple[Any, float, str]],
) -> None:
    if person_id in EMPTY_MARKERS:
        return
    reason = _confirmation_reason(role, person_status)
    if not reason:
        return
    for period, amount, field in amounts:
        if period == month and amount:
            rows.append(
                {
                    "源行号": detail.row_no,
                    "姓名": detail.name,
                    "工号": detail.employee_no,
                    "奖金类型": node_type,
                    "角色": role,
                    "发放对象工号": person_id,
                    "发放对象姓名": person_name,
                    "发放对象状态": person_status or "缺失",
                    "币种": detail.currency,
                    "发放节点": field,
                    "建议发放周期": period,
                    "建议发放金额": amount,
                    "人工确认结果": "",
                    "人工确认金额": "",
                    "不发/暂缓原因": "",
                    "系统提示": reason,
                }
            )


def _confirmation_reason(role: str, person_status: str) -> str:
    if person_status == "缺失":
        return f"{role}状态缺失，需确认是否发放"
    if not person_status:
        return ""
    if person_status not in CURRENT_EMPLOYEE_STATUSES:
        return f"{role}非在职状态，需确认是否发放"
    return ""


def _status_value(row: ImportRow, *fields: str) -> str:
    for field in fields:
        if field in row.values:
            return row.text(field) or "缺失"
    return ""


def _pending_keys(pending_confirmations: List[Dict[str, Any]]) -> set[Tuple[int, str, str]]:
    return {
        (int(row["源行号"]), str(row["角色"]), str(row["发放节点"]))
        for row in pending_confirmations
    }


def _node_key(detail: RecruitmentDetail, role: str, field: str) -> Tuple[int, str, str]:
    return (detail.row_no, role, field)
