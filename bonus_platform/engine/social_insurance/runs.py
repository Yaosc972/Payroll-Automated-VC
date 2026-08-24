from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
from typing import Any

from ... import config
from .coverage import build_coverage_tasks, coverage_summary, processing_plan
from .field_metadata import FieldMetadataError, validate_report_field_value
from .rule_catalog import RULE_VERSION
from .template_schemas import hydrate_employee_template_reports, validate_template_updates


TEMPLATE_FIELDS = (
    "证件号码",
    "姓名",
    "户籍",
    "入深户时间",
    "民族",
    "手机号码",
    "通讯地址",
    "电脑号",
    "岗位类别",
    "个人身份",
    "用工形式",
    "学历",
    "职称",
    "国家职业资格或职业技能等级",
    "医疗缴费档次",
    "部门名称",
    "户籍地类别",
    "户口所在地行政区划代码",
    "就业形式",
    "就业前身份",
)

# 业务审核字段不写入深圳政务模板，但必须随批次保留、支持人工复核和整批导出。
AUDIT_FIELDS = (
    "社保缴交基数",
    "公积金缴交基数",
    "公积金号",
    "户口具体地址",
)
REPORT_FIELDS = (*TEMPLATE_FIELDS, *AUDIT_FIELDS)

FIELD_ALIASES = {
    "部门": "部门名称",
    "灵活就业人员就业形式": "就业形式",
    "就业前个人身份": "就业前身份",
}

REQUIRED_REPORT_FIELDS = (
    "证件号码",
    "姓名",
    "户籍",
    "民族",
    "手机号码",
    "岗位类别",
    "个人身份",
    "用工形式",
    "学历",
    "职称",
    "国家职业资格或职业技能等级",
    "医疗缴费档次",
    "户籍地类别",
    "户口所在地行政区划代码",
    "就业形式",
    "就业前身份",
)

VALID_EMPLOYEE_STATUSES = {"ready", "needs_review", "excluded"}
VALID_DECISIONS = {"include", "exclude"}
SUPPLEMENT_REASONS = {
    "prior_period_omission": "上期漏报",
    "delayed_enrollment": "延迟增员",
}


class RunValidationError(ValueError):
    """批次不满足业务门槛。"""


class RunNotFoundError(FileNotFoundError):
    """批次或人员不存在。"""


def current_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _runs_root() -> Path:
    configured = os.environ.get("SIGMA_SOCIAL_INSURANCE_RUNS_DIR")
    root = Path(configured).expanduser() if configured else config.SOCIAL_INSURANCE_RUNS_DIR
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    return root


def _safe_id(value: str, label: str = "ID") -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,80}", value or ""):
        raise RunValidationError(f"{label}格式无效")
    return value


def get_run_dir(run_id: str) -> Path:
    return _runs_root() / _safe_id(run_id, "批次ID")


def _run_path(run_id: str) -> Path:
    return get_run_dir(run_id) / "run.json"


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        temporary.chmod(0o600)
    except OSError:
        pass
    temporary.replace(path)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _parse_iso_date(value: str, label: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise RunValidationError(f"{label}必须为 YYYY-MM-DD") from exc


def _previous_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def default_reporting_window(today: date | None = None) -> tuple[str, str]:
    """返回最近一个已完整结束的 16 日至次月 15 日窗口。"""
    current = today or date.today()
    if current.day >= 16:
        start_year, start_month = _previous_month(current.year, current.month)
        start = date(start_year, start_month, 16)
        end = date(current.year, current.month, 15)
    else:
        end_year, end_month = _previous_month(current.year, current.month)
        start_year, start_month = _previous_month(end_year, end_month)
        start = date(start_year, start_month, 16)
        end = date(end_year, end_month, 15)
    return start.isoformat(), end.isoformat()


def _mask_identity(identity: str) -> str:
    value = str(identity or "").strip()
    if len(value) <= 8:
        return "****" if value else ""
    return f"{value[:4]}{'*' * min(10, len(value) - 8)}{value[-4:]}"


def _employee_id(identity: str, index: int) -> str:
    seed = f"{identity}\0{index}".encode("utf-8")
    return f"emp_{hashlib.sha256(seed).hexdigest()[:16]}"


def _normalized_issue(issue: Any) -> dict[str, str] | None:
    if not isinstance(issue, dict):
        return None
    message = str(issue.get("message") or "").strip()
    if not message:
        return None
    severity = str(issue.get("severity") or "blocking").strip().lower()
    if severity not in {"blocking", "info"}:
        severity = "blocking"
    return {
        "field": str(issue.get("field") or "").strip(),
        "severity": severity,
        "message": message,
    }


def _normalized_employee(record: dict[str, Any], index: int) -> dict[str, Any]:
    report_source = record.get("report") if isinstance(record.get("report"), dict) else {}
    aliased_source = {
        FIELD_ALIASES.get(str(field), str(field)): value
        for field, value in report_source.items()
    }
    raw_source = record.get("source") if isinstance(record.get("source"), dict) else {}
    audit_fallbacks = {
        "社保缴交基数": raw_source.get("socialContributionBase"),
        "公积金缴交基数": raw_source.get("housingContributionBase"),
        "公积金号": raw_source.get("housingFundAccount"),
        "户口具体地址": raw_source.get("householdAddress"),
    }
    report = {
        field: str(aliased_source.get(field) or audit_fallbacks.get(field) or "").strip()
        for field in REPORT_FIELDS
    }
    identity = report["证件号码"]
    status = str(record.get("status") or "ready").strip().lower()
    status_aliases = {"可报盘": "ready", "待人工确认": "needs_review", "规则排除": "excluded"}
    status = status_aliases.get(status, status)
    if status not in VALID_EMPLOYEE_STATUSES:
        status = "needs_review"
    issues = [item for item in (_normalized_issue(value) for value in record.get("issues") or []) if item]
    decision = str(record.get("decision") or ("exclude" if status == "excluded" else "include"))
    if decision not in VALID_DECISIONS:
        decision = "include"
    source = record.get("source") if isinstance(record.get("source"), dict) else {}
    coverage_source = record.get("coverageSource") if isinstance(record.get("coverageSource"), dict) else {}
    normalized_source = {
        "subject": str(source.get("subject") or "").strip(),
        "jobNumber": str(source.get("jobNumber") or "").strip(),
        "place": str(source.get("place") or "").strip(),
        "employType": str(source.get("employType") or "").strip(),
        "gender": str(source.get("gender") or "").strip(),
        "mobile": str(source.get("mobile") or "").strip(),
        "lastWorkDate": str(source.get("lastWorkDate") or "").strip(),
        "housingContributionRate": str(source.get("housingContributionRate") or "").strip(),
        "socialContributionPlace": str(source.get("socialContributionPlace") or "").strip(),
        "birthplace": str(source.get("birthplace") or "").strip(),
        "domicileType": str(source.get("domicileType") or "").strip(),
        "education": str(source.get("education") or "").strip(),
        "currentAddress": str(source.get("currentAddress") or source.get("residenceAddress") or "").strip(),
        "nation": str(source.get("nation") or "").strip(),
        "employeeStatus": str(source.get("employeeStatus") or "").strip(),
        "email": str(source.get("email") or "").strip(),
        "employmentPlace": str(source.get("employmentPlace") or "").strip(),
        "changeDescription": str(source.get("changeDescription") or "").strip(),
        "virtualEmployee": str(source.get("virtualEmployee") or "").strip(),
        "birthDate": str(source.get("birthDate") or "").strip(),
        "nationality": str(source.get("nationality") or "").strip(),
        "firstWorkDate": str(source.get("firstWorkDate") or "").strip(),
        "maritalStatus": str(source.get("maritalStatus") or "").strip(),
        "politicalStatus": str(source.get("politicalStatus") or "").strip(),
        "householdPostalCode": str(source.get("householdPostalCode") or "").strip(),
        "residencePostalCode": str(source.get("residencePostalCode") or "").strip(),
        "actualEmployerName": str(source.get("actualEmployerName") or "").strip(),
        "actualEmployerCreditCode": str(source.get("actualEmployerCreditCode") or "").strip(),
        "jobNature": str(source.get("jobNature") or "").strip(),
        "establishmentType": str(source.get("establishmentType") or "").strip(),
        "personalSocialNumber": str(source.get("personalSocialNumber") or "").strip(),
        "socialContributionBase": str(source.get("socialContributionBase") or "").strip(),
        "housingContributionBase": str(source.get("housingContributionBase") or "").strip(),
        "householdAddress": str(source.get("householdAddress") or "").strip(),
        "socialPlace": str(source.get("socialPlace") or coverage_source.get("socialPlace") or "").strip(),
        "socialMedicalStatus": str(source.get("socialMedicalStatus") or coverage_source.get("socialMedicalStatus") or "").strip(),
        "housingStatus": str(source.get("housingStatus") or coverage_source.get("housingStatus") or "").strip(),
    }
    employee = {
        "id": _employee_id(identity, index),
        "status": status,
        "decision": decision,
        "confirmed": bool(record.get("confirmed", status == "ready")),
        "reviewNote": str(record.get("reviewNote") or "").strip(),
        "reason": str(record.get("reason") or ("规则校验通过" if status == "ready" else "需要业务确认")),
        "issues": issues,
        "report": report,
        "maskedId": _mask_identity(identity),
        "entryDate": str(record.get("entryDate") or "").strip(),
        "source": normalized_source,
        "coverageSource": {
            "socialPlace": normalized_source["socialPlace"],
            "socialMedicalStatus": normalized_source["socialMedicalStatus"],
            "housingStatus": normalized_source["housingStatus"],
        },
    }
    employee["coverageTasks"] = build_coverage_tasks(
        coverage_source=employee["coverageSource"],
        source=employee["source"],
        employee_status=status,
        decision=decision,
    )
    return employee


def _summarize(employees: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(employees),
        "ready": sum(item["status"] == "ready" for item in employees),
        "needsReview": sum(item["status"] == "needs_review" for item in employees),
        "excluded": sum(item["status"] == "excluded" for item in employees),
        "included": sum(item["decision"] == "include" for item in employees),
        "infoOnly": sum(
            any(issue.get("severity") == "info" for issue in item.get("issues") or [])
            for item in employees
        ),
        "supplemental": sum(bool(item.get("supplemental")) for item in employees),
        **coverage_summary(employees),
    }


def create_run(
    *,
    records: list[dict[str, Any]],
    period_start: str,
    period_end: str,
    subject: str,
    source: str,
    confirmation_date: str | None = None,
    source_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    start = _parse_iso_date(period_start, "开始日期")
    end = _parse_iso_date(period_end, "结束日期")
    if start > end:
        raise RunValidationError("开始日期不能晚于结束日期")
    confirmation = _parse_iso_date(confirmation_date or period_end, "名单确认日")
    if confirmation < end:
        raise RunValidationError("名单确认日不能早于增员周期结束日")
    normalized_subject = str(subject or "").strip()
    if not normalized_subject:
        raise RunValidationError("合同主体不能为空")
    run_id = f"sir_{datetime.now().strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(4)}"
    employees = [_normalized_employee(record, index) for index, record in enumerate(records)]
    now = current_timestamp()
    run = {
        "id": run_id,
        "module": "social_insurance",
        "version": "mvp-0.1",
        "ruleVersion": RULE_VERSION,
        "status": "draft",
        "periodStart": start.isoformat(),
        "periodEnd": end.isoformat(),
        "confirmationDate": confirmation.isoformat(),
        "subject": normalized_subject,
        "source": str(source or "beisen"),
        "sourceSummary": {
            "provider": str((source_summary or {}).get("provider") or source or "beisen"),
            **{
                key: value
                for key, value in (source_summary or {}).items()
                if key not in {
                    "rawApiResponse",
                    "rawApiResponseSaved",
                    "governmentSiteAccessed",
                    "records",
                    "employees",
                }
            },
            "rawApiResponseSaved": False,
            "governmentSiteAccessed": False,
        },
        "employees": employees,
        "summary": _summarize(employees),
        "processingPlan": processing_plan(employees),
        "template": None,
        "reportFile": None,
        "reportPackage": None,
        "rpa": {
            "state": "not_configured",
            "label": "RPA待接入",
            "governmentLogin": False,
            "governmentUpload": False,
            "governmentSubmit": False,
            "finalConfirmation": "manual",
        },
        "createdAt": now,
        "updatedAt": now,
    }
    for employee in employees:
        hydrate_employee_template_reports(employee, run)
        if employee.get("decision") == "include" and any(
            report.get("missingRequired")
            for report in (employee.get("templateReports") or {}).values()
            if isinstance(report, dict)
        ):
            employee["status"] = "needs_review"
            employee["confirmed"] = False
            employee["reason"] = "政务模板必填资料待补充或确认"
            employee["coverageTasks"] = build_coverage_tasks(
                coverage_source=employee.get("coverageSource"),
                source=employee.get("source"),
                employee_status="needs_review",
                decision="include",
            )
            hydrate_employee_template_reports(employee, run)
    run["summary"] = _summarize(employees)
    run["processingPlan"] = processing_plan(employees)
    _write_json_atomic(_run_path(run_id), run)
    return run


def load_run(run_id: str) -> dict[str, Any]:
    path = _run_path(run_id)
    if not path.exists():
        raise RunNotFoundError("社保报盘批次不存在")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunValidationError("社保报盘批次文件不可读取") from exc
    if not isinstance(payload, dict):
        raise RunValidationError("社保报盘批次格式无效")
    for employee in payload.get("employees") or []:
        if not isinstance(employee, dict):
            continue
        if not isinstance(employee.get("coverageTasks"), dict):
            employee["coverageTasks"] = build_coverage_tasks(
                coverage_source=employee.get("coverageSource"),
                source=employee.get("source"),
                employee_status=str(employee.get("status") or "needs_review"),
                decision=str(employee.get("decision") or "include"),
            )
        hydrate_employee_template_reports(employee, payload)
    payload["summary"] = _summarize(payload.get("employees") or [])
    payload["processingPlan"] = processing_plan(payload.get("employees") or [])
    return payload


def save_run(run: dict[str, Any]) -> dict[str, Any]:
    for employee in run.get("employees") or []:
        if isinstance(employee, dict):
            hydrate_employee_template_reports(employee, run)
    run["summary"] = _summarize(run.get("employees") or [])
    run["processingPlan"] = processing_plan(run.get("employees") or [])
    run["updatedAt"] = current_timestamp()
    _write_json_atomic(_run_path(str(run.get("id") or "")), run)
    return run


def list_runs(
    limit: int = 20,
    *,
    period_start: str = "",
    period_end: str = "",
    confirmation_date: str = "",
    subject: str = "",
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for path in _runs_root().glob("sir_*/run.json"):
        try:
            run = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if period_start and str(run.get("periodStart") or "") != period_start:
            continue
        if period_end and str(run.get("periodEnd") or "") != period_end:
            continue
        if confirmation_date and str(run.get("confirmationDate") or "") != confirmation_date:
            continue
        if subject and str(run.get("subject") or "").strip() != subject.strip():
            continue
        output.append({key: value for key, value in run.items() if key != "employees"})
    output.sort(
        key=lambda run: (str(run.get("createdAt") or run.get("updatedAt") or ""), str(run.get("id") or "")),
        reverse=True,
    )
    return output[:max(1, min(limit, 100))]


def update_employee(run_id: str, employee_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    run = load_run(run_id)
    employee = next((item for item in run.get("employees") or [] if item.get("id") == employee_id), None)
    if employee is None:
        raise RunNotFoundError("批次人员不存在")
    unknown = set(updates) - {
        "decision", "confirmed", "reviewNote", "report", "templateRoute", "templateReport",
    }
    if unknown:
        raise RunValidationError(f"不支持修改字段：{'、'.join(sorted(unknown))}")
    if "decision" in updates:
        decision = str(updates["decision"])
        if decision not in VALID_DECISIONS:
            raise RunValidationError("人员决策只能为 include 或 exclude")
        employee["decision"] = decision
    if "confirmed" in updates:
        employee["confirmed"] = bool(updates["confirmed"])
    if "reviewNote" in updates:
        employee["reviewNote"] = str(updates["reviewNote"] or "").strip()[:500]
    if "report" in updates:
        report_updates = updates["report"]
        if not isinstance(report_updates, dict):
            raise RunValidationError("报盘字段必须为对象")
        unknown_fields = set(report_updates) - set(REPORT_FIELDS) - set(FIELD_ALIASES)
        if unknown_fields:
            raise RunValidationError(f"未知报盘字段：{'、'.join(sorted(unknown_fields))}")
        for field, value in report_updates.items():
            canonical_field = FIELD_ALIASES.get(field, field)
            normalized_value = str(value or "").strip()
            try:
                validate_report_field_value(canonical_field, normalized_value)
            except FieldMetadataError as exc:
                raise RunValidationError(str(exc)) from exc
            employee["report"][canonical_field] = normalized_value
        employee["maskedId"] = _mask_identity(employee["report"].get("证件号码", ""))
    if "templateReport" in updates:
        route = str(updates.get("templateRoute") or "").strip()
        template_updates = updates.get("templateReport")
        if not route:
            raise RunValidationError("请选择需要修改的政务模板")
        if not isinstance(template_updates, dict):
            raise RunValidationError("政务模板字段必须为对象")
        try:
            normalized_updates = validate_template_updates(route, template_updates)
        except ValueError as exc:
            raise RunValidationError(str(exc)) from exc
        available_routes = set((employee.get("templateReports") or {}).keys())
        if route not in available_routes:
            raise RunValidationError("该人员不属于所选政务模板办理路径")
        employee.setdefault("templateOverrides", {}).setdefault(route, {}).update(normalized_updates)
        if route == "shenzhen-social-medical":
            for field, value in normalized_updates.items():
                if field in employee.get("report", {}):
                    employee["report"][field] = value
    if employee.get("decision") == "exclude":
        employee["status"] = "excluded"
    else:
        missing_required = any(
            not str(employee.get("report", {}).get(field) or "").strip()
            for field in REQUIRED_REPORT_FIELDS
        )
        has_blocking_issue = any(
            issue.get("severity") == "blocking"
            for issue in employee.get("issues") or []
        )
        if missing_required or (has_blocking_issue and not employee.get("confirmed")):
            employee["status"] = "needs_review"
        elif employee.get("confirmed"):
            employee["status"] = "ready"
    employee["coverageTasks"] = build_coverage_tasks(
        coverage_source=employee.get("coverageSource"),
        source=employee.get("source"),
        employee_status=str(employee.get("status") or "needs_review"),
        decision=str(employee.get("decision") or "include"),
    )
    hydrate_employee_template_reports(employee, run)
    if employee.get("decision") == "include":
        has_template_missing = any(
            report.get("missingRequired")
            for report in (employee.get("templateReports") or {}).values()
            if isinstance(report, dict)
        )
        if has_template_missing:
            employee["status"] = "needs_review"
    if run.get("status") in {"confirmed", "generated"}:
        run["status"] = "draft"
        run["reportFile"] = None
        run["reportPackage"] = None
    return save_run(run)


def add_supplement_employee(
    run_id: str,
    record: dict[str, Any],
    *,
    reason_type: str,
    note: str,
) -> dict[str, Any]:
    run = load_run(run_id)
    reason_label = SUPPLEMENT_REASONS.get(str(reason_type or "").strip())
    if not reason_label:
        raise RunValidationError("补充增员原因只能选择上期漏报或延迟增员")
    normalized_note = str(note or "").strip()
    if len(normalized_note) < 4:
        raise RunValidationError("请填写至少4个字的补充增员说明")
    normalized_note = normalized_note[:500]
    entry_date = _parse_iso_date(str(record.get("entryDate") or ""), "补充人员入职日期")
    period_start = _parse_iso_date(str(run.get("periodStart") or ""), "批次开始日期")
    if entry_date >= period_start:
        raise RunValidationError("该人员入职日期在本期正常增员周期内，请通过一键同步北森处理")
    source = record.get("source") if isinstance(record.get("source"), dict) else {}
    if str(source.get("subject") or "").strip() != str(run.get("subject") or "").strip():
        raise RunValidationError("补充人员当前合同主体与本批次不一致")
    employee = _normalized_employee(record, len(run.get("employees") or []))
    identity = str(employee.get("report", {}).get("证件号码") or "").replace(" ", "").upper()
    if not identity:
        raise RunValidationError("补充人员证件号码为空")
    for existing in run.get("employees") or []:
        existing_identity = str(existing.get("report", {}).get("证件号码") or "").replace(" ", "").upper()
        if existing_identity == identity:
            raise RunValidationError("该人员已在当前批次，不能重复补充")
    issue_message = f"{reason_label}属于人工补充增员，需复核补充原因和报盘字段。"
    employee["issues"] = [
        {"field": "", "severity": "blocking", "message": issue_message},
        *employee.get("issues", []),
    ]
    employee.update({
        "status": "needs_review",
        "decision": "include",
        "confirmed": False,
        "reviewNote": "",
        "reason": issue_message,
        "supplemental": {
            "type": str(reason_type).strip(),
            "label": reason_label,
            "note": normalized_note,
            "addedAt": current_timestamp(),
        },
    })
    run.setdefault("employees", []).append(employee)
    run["ruleVersion"] = RULE_VERSION
    if run.get("status") in {"confirmed", "generated"}:
        run["status"] = "draft"
        run["reportFile"] = None
        run["reportPackage"] = None
    return save_run(run)


def _blocking_reason(employee: dict[str, Any]) -> str | None:
    if employee.get("decision") != "include":
        return None
    if employee.get("status") == "needs_review" and not employee.get("confirmed"):
        return "needs_review"
    if any(issue.get("severity") == "blocking" for issue in employee.get("issues") or []) and not employee.get("confirmed"):
        return "blocking_issue"
    missing = [field for field in REQUIRED_REPORT_FIELDS if not str((employee.get("report") or {}).get(field) or "").strip()]
    if missing and not employee.get("confirmed"):
        return f"missing:{','.join(missing)}"
    route_missing = {
        route: report.get("missingRequired") or []
        for route, report in (employee.get("templateReports") or {}).items()
        if isinstance(report, dict) and report.get("missingRequired")
    }
    return f"template_missing:{','.join(route_missing)}" if route_missing and not employee.get("confirmed") else None


def confirm_run(run_id: str) -> dict[str, Any]:
    run = load_run(run_id)
    included = [item for item in run.get("employees") or [] if item.get("decision") == "include"]
    if not included:
        raise RunValidationError("当前批次没有纳入报盘的人员")
    unresolved = [item for item in included if _blocking_reason(item)]
    if unresolved:
        raise RunValidationError(f"仍有{len(unresolved)}人需要人工确认")
    run["status"] = "confirmed"
    run["confirmedAt"] = current_timestamp()
    return save_run(run)
