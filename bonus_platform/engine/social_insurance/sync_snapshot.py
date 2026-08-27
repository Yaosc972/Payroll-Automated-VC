from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
from typing import Any

from ... import config
from .persistent_storage import (
    SocialInsuranceStorageError,
    load_json,
    persist_json,
    persistent_storage_enabled,
    require_persistent_storage,
    serverless_runtime,
)
from .rule_catalog import RULE_VERSION
from .runs import RunValidationError, list_runs, load_run


CONFIRMATION_RULE_CONTEXT = "confirmationRuleContext"
PERIOD_SNAPSHOT_VERSION = 2
SHANGHAI_TIMEZONE = timezone(timedelta(hours=8))


def _snapshot_root() -> Path:
    configured = os.environ.get("SIGMA_SOCIAL_INSURANCE_SNAPSHOTS_DIR")
    baseline_root = os.environ.get("SIGMA_SOCIAL_INSURANCE_BASELINES_DIR")
    root = (
        Path(configured).expanduser()
        if configured
        else (Path(baseline_root).expanduser() if baseline_root else config.SOCIAL_INSURANCE_BASELINES_DIR)
        / "reporting_snapshots"
    )
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    return root


def _context(
    *,
    period_start: str,
    period_end: str,
    confirmation_date: str,
    subject: str,
) -> dict[str, str]:
    normalized = {
        "periodStart": str(period_start or "").strip(),
        "periodEnd": str(period_end or "").strip(),
        "confirmationDate": str(confirmation_date or "").strip(),
        "subject": str(subject or "").strip(),
    }
    try:
        start = datetime.fromisoformat(normalized["periodStart"]).date()
        end = datetime.fromisoformat(normalized["periodEnd"]).date()
        confirmation = datetime.fromisoformat(normalized["confirmationDate"]).date()
    except ValueError as exc:
        raise RunValidationError("同步快照日期必须为 YYYY-MM-DD") from exc
    if start > end or confirmation < end or not normalized["subject"]:
        raise RunValidationError("同步快照周期、确认日或合同主体无效")
    return normalized


def _snapshot_path(context: dict[str, str]) -> Path:
    token = "\0".join(context.values())
    key = hashlib.sha256(token.encode("utf-8")).hexdigest()[:24]
    return _snapshot_root() / f"{key}.json"


def _period_snapshot_path(context: dict[str, str]) -> Path:
    token = "\0".join((context["periodStart"], context["periodEnd"], context["subject"]))
    key = hashlib.sha256(token.encode("utf-8")).hexdigest()[:24]
    return _snapshot_root() / f"period-{key}.json"


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    try:
        temporary.chmod(0o600)
    except OSError:
        pass
    temporary.replace(path)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _persist_snapshot(path: Path, payload: dict[str, Any]) -> None:
    try:
        require_persistent_storage()
        persist_json("snapshots", path.stem, payload)
    except SocialInsuranceStorageError as exc:
        raise RunValidationError("北森同步快照未能保存到持久化存储") from exc


def _restore_snapshot(path: Path) -> None:
    try:
        require_persistent_storage()
        if not persistent_storage_enabled():
            return
        payload = load_json("snapshots", path.stem)
    except SocialInsuranceStorageError as exc:
        raise RunValidationError("北森同步快照未能从持久化存储恢复") from exc
    if payload is not None:
        _write_json_atomic(path, payload)


def _supports_confirmation_rebase(records: list[dict[str, Any]]) -> bool:
    for record in records:
        context = record.get(CONFIRMATION_RULE_CONTEXT)
        if not isinstance(context, dict) or context.get("version") != 1:
            return False
        if context.get("baseStatus") not in {"ready", "needs_review"}:
            return False
        if not isinstance(context.get("baseIssues"), list) or not isinstance(context.get("dimissionRecords"), list):
            return False
    return True


def _parse_rule_datetime(value: Any) -> datetime | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            parsed = datetime(1899, 12, 30, tzinfo=timezone.utc) + timedelta(days=float(value))
        except (OverflowError, ValueError):
            return None
        return parsed.astimezone(SHANGHAI_TIMEZONE)
    raw = str(value or "").strip()
    if not raw:
        return None
    if len(raw) == 10:
        raw = f"{raw}T00:00:00+08:00"
    elif raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHANGHAI_TIMEZONE)
    return parsed.astimezone(SHANGHAI_TIMEZONE)


def _confirmation_decision(
    context: dict[str, Any],
    *,
    confirmation_date: str,
) -> tuple[str, str]:
    cutoff = datetime.fromisoformat(f"{confirmation_date}T23:59:59.999999+08:00")
    known: list[tuple[datetime, dict[str, Any]]] = []
    invalid_process_time = False
    for entry in context.get("dimissionRecords") or []:
        if not isinstance(entry, dict):
            continue
        process_date = _parse_rule_datetime(entry.get("processCreatedTime"))
        if entry.get("processTimeReliable") is False:
            return "review", "北森实时离职记录缺少可靠审批时间或停保属性，请人工确认"
        if process_date is None:
            invalid_process_time = True
        if process_date is not None and process_date <= cutoff:
            known.append((process_date, entry))
    if invalid_process_time:
        return "review", "离职任职记录缺少流程时间或停保属性，请人工确认"
    if not known:
        reason = (
            "确认时点前无已知离职流程"
            if not context.get("dimissionRecords")
            else "离职流程晚于名单确认时点"
        )
        return "include", reason
    _, latest = max(known, key=lambda item: item[0])
    last_work = _parse_rule_datetime(latest.get("lastWorkDate"))
    current_entry = _parse_rule_datetime(context.get("currentEntryDate"))
    if last_work is not None and current_entry is not None and last_work.date() < current_entry.date():
        return "include", "旧任职最后工作日早于当前任职入职日，按转正式工或重新入职保留增员"
    stop_flag = str(latest.get("voluntaryStopFlag") or "").strip()
    if "非自愿停保" in stop_flag:
        return "include", "非自愿停保，按规则当月继续购买"
    if "自愿停保" in stop_flag:
        return "exclude", "确认时点前已知离职且自愿停保"
    return "review", "确认时点前已有离职流程，但停保属性缺失"


def _blocking_issue(message: str) -> dict[str, str]:
    return {"field": "", "severity": "blocking", "message": message}


def _rebase_records(
    records: list[dict[str, Any]],
    *,
    confirmation_date: str,
) -> list[dict[str, Any]]:
    rebased: list[dict[str, Any]] = []
    for source_record in records:
        record = deepcopy(source_record)
        context = record[CONFIRMATION_RULE_CONTEXT]
        base_status = str(context["baseStatus"])
        base_issues = [
            deepcopy(issue)
            for issue in context.get("baseIssues") or []
            if isinstance(issue, dict) and str(issue.get("message") or "").strip()
        ]
        decision, reason = _confirmation_decision(context, confirmation_date=confirmation_date)
        if decision == "exclude":
            status = "excluded"
            issues = [_blocking_issue(reason)]
        elif decision == "review":
            status = "needs_review"
            issues = [_blocking_issue(reason), *base_issues]
        else:
            status = base_status
            issues = base_issues
        record.update({
            "status": status,
            "decision": "exclude" if status == "excluded" else "include",
            "confirmed": False,
            "issues": issues,
            "reason": "规则校验通过" if status == "ready" else (issues[0]["message"] if issues else "需要业务确认"),
            "dimissionReason": reason,
        })
        rebased.append(record)
    return rebased


def _load_snapshot_payload(path: Path) -> tuple[dict[str, Any], datetime] | None:
    if persistent_storage_enabled() and (serverless_runtime() or not path.exists()):
        _restore_snapshot(path)
    else:
        try:
            require_persistent_storage()
        except SocialInsuranceStorageError as exc:
            raise RunValidationError(str(exc)) from exc
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        captured_at = datetime.fromisoformat(str(payload.get("capturedAt") or "").replace("Z", "+00:00"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise RunValidationError("北森后台同步快照不可读取") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        raise RunValidationError("北森后台同步快照格式无效")
    return payload, captured_at


def _snapshot_result(payload: dict[str, Any], captured_at: datetime) -> dict[str, Any]:
    age_seconds = max(0, int((datetime.now(timezone.utc) - captured_at).total_seconds()))
    return {
        **deepcopy(payload),
        "ageSeconds": age_seconds,
        "stale": age_seconds > snapshot_fresh_seconds(),
    }


def capture_reporting_snapshot(
    *,
    records: list[dict[str, Any]],
    source_summary: dict[str, Any],
    period_start: str,
    period_end: str,
    confirmation_date: str,
    subject: str,
    captured_at: str | None = None,
) -> dict[str, Any]:
    context = _context(
        period_start=period_start,
        period_end=period_end,
        confirmation_date=confirmation_date,
        subject=subject,
    )
    if not isinstance(records, list):
        raise RunValidationError("同步快照候选记录格式无效")
    if captured_at:
        try:
            captured = datetime.fromisoformat(str(captured_at).replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError as exc:
            raise RunValidationError("同步快照时间无效") from exc
    else:
        captured = datetime.now(timezone.utc)
    normalized_captured_at = captured.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    payload = {
        "version": 1,
        "ruleVersion": RULE_VERSION,
        **context,
        "capturedAt": normalized_captured_at,
        "records": deepcopy(records),
        "sourceSummary": {
            key: deepcopy(value)
            for key, value in (source_summary or {}).items()
            if key not in {"rawApiResponse", "records", "employees"}
        },
    }
    path = _snapshot_path(context)
    _write_json_atomic(path, payload)
    _persist_snapshot(path, payload)
    if context["subject"] == "*" and _supports_confirmation_rebase(records):
        period_payload = {
            **deepcopy(payload),
            "version": PERIOD_SNAPSHOT_VERSION,
            "capturedConfirmationDate": context["confirmationDate"],
            "reusableAcrossConfirmationDates": True,
        }
        period_path = _period_snapshot_path(context)
        _write_json_atomic(period_path, period_payload)
        _persist_snapshot(period_path, period_payload)
    return {"capturedAt": normalized_captured_at, "recordCount": len(records)}


def load_reporting_snapshot(
    *,
    period_start: str,
    period_end: str,
    confirmation_date: str,
    subject: str,
) -> dict[str, Any] | None:
    context = _context(
        period_start=period_start,
        period_end=period_end,
        confirmation_date=confirmation_date,
        subject=subject,
    )
    period_result: dict[str, Any] | None = None
    if context["subject"] == "*":
        loaded_period = _load_snapshot_payload(_period_snapshot_path(context))
        if loaded_period is not None:
            period_payload, period_captured_at = loaded_period
            if period_payload.get("ruleVersion") == RULE_VERSION:
                expected_period = {
                    key: context[key]
                    for key in ("periodStart", "periodEnd", "subject")
                }
                if any(period_payload.get(key) != value for key, value in expected_period.items()):
                    raise RunValidationError("北森周期快照与当前增员周期不匹配")
                if (
                    period_payload.get("version") == PERIOD_SNAPSHOT_VERSION
                    and period_payload.get("reusableAcrossConfirmationDates") is True
                    and _supports_confirmation_rebase(period_payload["records"])
                ):
                    captured_confirmation = str(
                        period_payload.get("capturedConfirmationDate")
                        or period_payload.get("confirmationDate")
                        or ""
                    )
                    period_payload = deepcopy(period_payload)
                    period_payload["records"] = _rebase_records(
                        period_payload["records"],
                        confirmation_date=context["confirmationDate"],
                    )
                    period_payload["confirmationDate"] = context["confirmationDate"]
                    period_payload["sourceSummary"] = {
                        **(period_payload.get("sourceSummary") or {}),
                        "confirmationDate": context["confirmationDate"],
                        "snapshotRebasedFromConfirmationDate": captured_confirmation,
                    }
                    period_result = _snapshot_result(period_payload, period_captured_at)
                    if not period_result["stale"]:
                        return period_result

    loaded_exact = _load_snapshot_payload(_snapshot_path(context))
    if loaded_exact is not None:
        payload, captured_at = loaded_exact
        if payload.get("ruleVersion") != RULE_VERSION:
            return period_result
        if any(payload.get(key) != value for key, value in context.items()):
            raise RunValidationError("北森后台同步快照与当前批次不匹配")
        exact_result = _snapshot_result(payload, captured_at)
        if not exact_result["stale"] or period_result is None:
            return exact_result
    return period_result


def snapshot_fresh_seconds() -> int:
    try:
        return max(900, int(os.environ.get("SIGMA_SOCIAL_INSURANCE_SYNC_SNAPSHOT_FRESH_SECONDS", "7200")))
    except ValueError:
        return 7200


def seed_recent_reporting_snapshots(limit: int = 10) -> int:
    """Seed processed snapshots from recent Beisen runs before interactive traffic arrives."""
    seeded = 0
    seen: set[tuple[str, str, str, str]] = set()
    for summary in list_runs(limit):
        context_key = (
            str(summary.get("periodStart") or ""),
            str(summary.get("periodEnd") or ""),
            str(summary.get("confirmationDate") or summary.get("periodEnd") or ""),
            str(summary.get("subject") or "").strip(),
        )
        if not all(context_key) or context_key in seen or str(summary.get("source") or "") != "beisen":
            continue
        seen.add(context_key)
        if str(summary.get("ruleVersion") or "") != RULE_VERSION:
            continue
        if load_reporting_snapshot(
            period_start=context_key[0],
            period_end=context_key[1],
            confirmation_date=context_key[2],
            subject=context_key[3],
        ) is not None:
            continue
        run = load_run(str(summary.get("id") or ""))
        records: list[dict[str, Any]] = []
        for employee in run.get("employees") or []:
            if not isinstance(employee, dict) or employee.get("supplemental"):
                continue
            record = deepcopy(employee)
            for field in ("id", "maskedId", "decision", "confirmed", "reviewNote"):
                record.pop(field, None)
            report = record.get("report") if isinstance(record.get("report"), dict) else {}
            household = str(report.get("户籍") or "").strip()
            legacy_medical_issue = any(
                str(issue.get("field") or "") == "医疗缴费档次"
                and any(
                    marker in str(issue.get("message") or "")
                    for marker in ("未返回档次备注", "确认默认档次", "档次备注无法识别")
                )
                for issue in record.get("issues") or []
            )
            if legacy_medical_issue and household:
                report["医疗缴费档次"] = "职工一档" if household == "深圳户籍" else "职工二档"
            issues = [
                issue
                for issue in record.get("issues") or []
                if not (
                    legacy_medical_issue
                    and household
                    and str(issue.get("field") or "") == "医疗缴费档次"
                )
            ]
            record["issues"] = issues
            if record.get("status") != "excluded" and not any(
                issue.get("severity") == "blocking" for issue in issues
            ):
                record["status"] = "ready"
                record["reason"] = "规则校验通过"
            records.append(record)
        if not records:
            continue
        capture_reporting_snapshot(
            records=records,
            source_summary={
                **(run.get("sourceSummary") or {}),
                "snapshotSeededFromRecentRun": True,
                "sourceRunCreatedAt": run.get("createdAt"),
            },
            period_start=context_key[0],
            period_end=context_key[1],
            confirmation_date=context_key[2],
            subject=context_key[3],
            captured_at=str(run.get("createdAt") or "") or None,
        )
        seeded += 1
    return seeded
