from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
from typing import Any

from ... import config
from .rule_catalog import RULE_VERSION
from .runs import RunValidationError, list_runs, load_run


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
    _write_json_atomic(_snapshot_path(context), payload)
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
    path = _snapshot_path(context)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        captured_at = datetime.fromisoformat(str(payload.get("capturedAt") or "").replace("Z", "+00:00"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise RunValidationError("北森后台同步快照不可读取") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        raise RunValidationError("北森后台同步快照格式无效")
    if payload.get("ruleVersion") != RULE_VERSION:
        return None
    if any(payload.get(key) != value for key, value in context.items()):
        raise RunValidationError("北森后台同步快照与当前批次不匹配")
    age_seconds = max(0, int((datetime.now(timezone.utc) - captured_at).total_seconds()))
    return {
        **deepcopy(payload),
        "ageSeconds": age_seconds,
        "stale": age_seconds > snapshot_fresh_seconds(),
    }


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
