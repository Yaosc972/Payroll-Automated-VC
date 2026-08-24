from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
from typing import Any

from ... import config
from .runs import RunValidationError


BASELINE_ONLY_MESSAGE = "月度名单基线中有此人，但当前北森任职接口未返回；请结合最新离职信息确认是否仍纳入。"


def _baseline_root() -> Path:
    configured = os.environ.get("SIGMA_SOCIAL_INSURANCE_BASELINES_DIR")
    root = Path(configured).expanduser() if configured else config.SOCIAL_INSURANCE_BASELINES_DIR
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    return root


def _validated_period(period_start: str, period_end: str) -> tuple[str, str]:
    try:
        start = date.fromisoformat(str(period_start))
        end = date.fromisoformat(str(period_end))
    except (TypeError, ValueError) as exc:
        raise RunValidationError("月度名单基线周期必须为 YYYY-MM-DD") from exc
    if start > end:
        raise RunValidationError("月度名单基线开始日期不能晚于结束日期")
    return start.isoformat(), end.isoformat()


def _baseline_path(*, period_start: str, period_end: str, subject: str) -> Path:
    start, end = _validated_period(period_start, period_end)
    normalized_subject = str(subject or "").strip()
    if not normalized_subject:
        raise RunValidationError("月度名单基线合同主体不能为空")
    subject_key = hashlib.sha256(normalized_subject.encode("utf-8")).hexdigest()[:12]
    return _baseline_root() / f"{start}_{end}_{subject_key}.json"


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
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


def capture_monthly_baseline(
    *,
    records: list[dict[str, Any]],
    period_start: str,
    period_end: str,
    confirmation_date: str,
    subject: str,
    source: str,
) -> dict[str, Any]:
    """首次同步时固化候选名单；同周期后续同步不会覆盖原始基线。"""
    path = _baseline_path(period_start=period_start, period_end=period_end, subject=subject)
    if path.exists():
        existing = load_monthly_baseline(
            period_start=period_start,
            period_end=period_end,
            subject=subject,
        )
        return {
            "capturedAt": existing.get("capturedAt"),
            "recordCount": len(existing.get("records") or []),
            "source": existing.get("source"),
            "created": False,
        }
    if not isinstance(records, list) or not records:
        raise RunValidationError("北森未返回候选人员，未建立空的月度名单基线")
    start, end = _validated_period(period_start, period_end)
    try:
        confirmation = date.fromisoformat(str(confirmation_date))
    except (TypeError, ValueError) as exc:
        raise RunValidationError("月度名单基线确认日必须为 YYYY-MM-DD") from exc
    if confirmation < date.fromisoformat(end):
        raise RunValidationError("月度名单基线确认日不能早于周期结束日")
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    payload = {
        "version": 1,
        "periodStart": start,
        "periodEnd": end,
        "confirmationDate": confirmation.isoformat(),
        "subject": str(subject).strip(),
        "source": str(source or "beisen-monthly-snapshot").strip(),
        "capturedAt": now,
        "records": deepcopy(records),
    }
    _write_json_atomic(path, payload)
    return {
        "capturedAt": now,
        "recordCount": len(records),
        "source": payload["source"],
        "created": True,
    }


def load_monthly_baseline(*, period_start: str, period_end: str, subject: str) -> dict[str, Any] | None:
    path = _baseline_path(period_start=period_start, period_end=period_end, subject=subject)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunValidationError("月度名单基线不可读取") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        raise RunValidationError("月度名单基线格式无效")
    if (
        payload.get("periodStart") != period_start
        or payload.get("periodEnd") != period_end
        or payload.get("subject") != str(subject).strip()
    ):
        raise RunValidationError("月度名单基线与当前周期或合同主体不一致")
    return payload


def list_monthly_baseline_subjects(*, period_start: str, period_end: str) -> list[str]:
    """Return every subject already protected by the period baseline."""
    start, end = _validated_period(period_start, period_end)
    subjects: set[str] = set()
    for path in _baseline_root().glob(f"{start}_{end}_*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RunValidationError("月度名单基线不可读取") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
            raise RunValidationError("月度名单基线格式无效")
        if payload.get("periodStart") != start or payload.get("periodEnd") != end:
            raise RunValidationError("月度名单基线与当前周期不一致")
        subject = str(payload.get("subject") or "").strip()
        if not subject:
            raise RunValidationError("月度名单基线合同主体不能为空")
        if not any(_identity(record) for record in payload["records"] if isinstance(record, dict)):
            continue
        subjects.add(subject)
    return sorted(subjects)


def ensure_monthly_baseline_confirmation_date(
    *,
    period_start: str,
    period_end: str,
    confirmation_date: str,
    subject: str,
) -> dict[str, Any]:
    """为早期基线补充确认日元数据；人员记录保持原样。"""
    payload = load_monthly_baseline(
        period_start=period_start,
        period_end=period_end,
        subject=subject,
    )
    if payload is None:
        raise RunValidationError("月度名单基线不存在")
    try:
        confirmation = date.fromisoformat(str(confirmation_date))
    except (TypeError, ValueError) as exc:
        raise RunValidationError("月度名单基线确认日必须为 YYYY-MM-DD") from exc
    if confirmation < date.fromisoformat(period_end):
        raise RunValidationError("月度名单基线确认日不能早于周期结束日")
    existing = str(payload.get("confirmationDate") or "")
    if existing and existing != confirmation.isoformat():
        raise RunValidationError("月度名单基线已绑定其他确认日，不能直接覆盖")
    if existing:
        return payload
    payload["version"] = 2
    payload["confirmationDate"] = confirmation.isoformat()
    path = _baseline_path(period_start=period_start, period_end=period_end, subject=subject)
    _write_json_atomic(path, payload)
    return payload


def _identity(record: dict[str, Any]) -> str:
    report = record.get("report") if isinstance(record.get("report"), dict) else {}
    return str(report.get("证件号码") or "").replace(" ", "").strip().upper()


def merge_monthly_baseline(
    current_records: list[dict[str, Any]],
    baseline_records: list[dict[str, Any]],
    *,
    preserve_baseline_decisions: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """实时记录优先；仅在历史基线出现的人员转人工，不允许静默漏掉。"""
    current = deepcopy(current_records)
    baseline = deepcopy(baseline_records)
    current_identities = {_identity(record) for record in current if _identity(record)}
    merged = list(current)
    baseline_only_count = 0
    baseline_decision_reuse_count = 0
    for record in baseline:
        identity = _identity(record)
        if identity and identity in current_identities:
            continue
        if not identity:
            continue
        baseline_only_count += 1
        if preserve_baseline_decisions:
            baseline_decision_reuse_count += 1
        elif str(record.get("status") or "") != "excluded" and str(record.get("decision") or "") != "exclude":
            issues = [item for item in record.get("issues") or [] if isinstance(item, dict)]
            if not any(str(item.get("message") or "") == BASELINE_ONLY_MESSAGE for item in issues):
                issues.append({"field": "", "severity": "blocking", "message": BASELINE_ONLY_MESSAGE})
            record["issues"] = issues
            record["status"] = "needs_review"
            record["confirmed"] = False
            record["reason"] = BASELINE_ONLY_MESSAGE
        merged.append(record)
    return merged, {
        "baselineCount": len(baseline),
        "currentCount": len(current),
        "baselineOnlyCount": baseline_only_count,
        "baselineDecisionReuseCount": baseline_decision_reuse_count,
        "mergedCount": len(merged),
    }
