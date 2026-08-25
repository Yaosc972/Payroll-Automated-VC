from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import re
import secrets
from typing import Any

from ... import config
from .baseline import (
    capture_monthly_baseline,
    ensure_monthly_baseline_confirmation_date,
    list_monthly_baseline_subjects,
    load_monthly_baseline,
    merge_monthly_baseline,
)
from .persistent_storage import (
    SocialInsuranceStorageError,
    load_json,
    object_key,
    persist_json,
    persistent_storage_enabled,
    serverless_runtime,
)
from .report_package import build_export_preflight
from .reporting_diagnostics import ReportingRefreshDiagnostics
from .rule_catalog import RULE_VERSION
from .runs import RunValidationError, create_run, current_timestamp
from .supplements import publish_supplement_search_indexes
from .sync_snapshot import capture_reporting_snapshot


RELEASE_NAMESPACE = "reporting-releases"
LATEST_RELEASE_KEY = "latest"
_RELEASE_ID_PATTERN = re.compile(r"release_[0-9]{14}_[0-9a-f]{8}")


def _release_root() -> Path:
    configured = os.environ.get("SIGMA_SOCIAL_INSURANCE_RELEASES_DIR")
    if configured:
        root = Path(configured).expanduser()
    else:
        runs_root = Path(
            os.environ.get("SIGMA_SOCIAL_INSURANCE_RUNS_DIR")
            or config.SOCIAL_INSURANCE_RUNS_DIR
        ).expanduser()
        root = runs_root / "_reporting_releases"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    return root


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
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


def _read_json_file(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _period_pointer_key(period_start: str, period_end: str) -> str:
    return f"period-{object_key(period_start, period_end)}"


def _release_path(release_id: str) -> Path:
    if not _RELEASE_ID_PATTERN.fullmatch(release_id):
        raise RunValidationError("集成发布版本格式无效")
    return _release_root() / f"{release_id}.json"


def _pointer_path(key: str) -> Path:
    return _release_root() / f"{key}.json"


def _load_release_object(key: str, path: Path) -> dict[str, Any] | None:
    payload: dict[str, Any] | None = None
    if persistent_storage_enabled() and (serverless_runtime() or not path.is_file()):
        try:
            payload = load_json(RELEASE_NAMESPACE, key)
        except SocialInsuranceStorageError as exc:
            raise RunValidationError("最近成功集成版本暂时不可读取") from exc
    if payload is None and path.is_file():
        payload = _read_json_file(path)
    return deepcopy(payload) if isinstance(payload, dict) else None


def load_reporting_release(release_id: str) -> dict[str, Any] | None:
    path = _release_path(str(release_id or "").strip())
    payload = _load_release_object(path.stem, path)
    if payload is None:
        return None
    if payload.get("id") != path.stem or payload.get("state") != "ready":
        raise RunValidationError("最近成功集成版本内容无效")
    if not isinstance(payload.get("subjects"), list):
        raise RunValidationError("最近成功集成主体目录无效")
    return payload


def load_latest_reporting_release(
    *,
    period_start: str = "",
    period_end: str = "",
) -> dict[str, Any] | None:
    if bool(period_start) != bool(period_end):
        raise RunValidationError("查询集成版本时必须同时提供周期开始和结束日期")
    pointer_key = (
        _period_pointer_key(period_start, period_end)
        if period_start and period_end
        else LATEST_RELEASE_KEY
    )
    pointer = _load_release_object(pointer_key, _pointer_path(pointer_key))
    if pointer is None:
        return None
    release_id = str(pointer.get("releaseId") or "").strip()
    release = load_reporting_release(release_id)
    if release is None:
        raise RunValidationError("最近成功集成版本尚未完整发布")
    if period_start and (
        release.get("periodStart") != period_start
        or release.get("periodEnd") != period_end
    ):
        raise RunValidationError("最近成功集成版本与所选周期不匹配")
    return release


def _persist_release(payload: dict[str, Any]) -> None:
    release_id = str(payload["id"])
    period_key = _period_pointer_key(
        str(payload["periodStart"]),
        str(payload["periodEnd"]),
    )
    pointer = {
        "version": 1,
        "releaseId": release_id,
        "periodStart": payload["periodStart"],
        "periodEnd": payload["periodEnd"],
        "confirmationDate": payload["confirmationDate"],
        "publishedAt": payload["publishedAt"],
    }
    release_path = _release_path(release_id)
    _write_json_atomic(release_path, payload)
    if persistent_storage_enabled():
        try:
            # The immutable manifest is written first.  The latest pointer is
            # switched only after every batch and both lookup objects exist.
            persist_json(RELEASE_NAMESPACE, release_id, payload)
            persist_json(RELEASE_NAMESPACE, period_key, pointer)
            persist_json(RELEASE_NAMESPACE, LATEST_RELEASE_KEY, pointer)
        except SocialInsuranceStorageError as exc:
            raise RunValidationError("最近成功集成版本未能发布到持久化存储") from exc
    _write_json_atomic(_pointer_path(period_key), pointer)
    _write_json_atomic(_pointer_path(LATEST_RELEASE_KEY), pointer)


def materialize_subject_run(
    *,
    records: list[dict[str, Any]],
    source_summary: dict[str, Any],
    period_start: str,
    period_end: str,
    confirmation_date: str,
    subject: str,
) -> dict[str, Any]:
    """Apply the monthly baseline and persist one independently reviewable batch."""
    source_summary = {**deepcopy(source_summary), "candidateCount": len(records)}
    monthly_baseline = load_monthly_baseline(
        period_start=period_start,
        period_end=period_end,
        subject=subject,
    )
    if (
        monthly_baseline is not None
        and not monthly_baseline.get("confirmationDate")
        and source_summary.get("historicalBaselineSeedUsed")
    ):
        monthly_baseline = ensure_monthly_baseline_confirmation_date(
            period_start=period_start,
            period_end=period_end,
            confirmation_date=confirmation_date,
            subject=subject,
        )
    if monthly_baseline is not None:
        preserve_baseline_decisions = monthly_baseline.get("confirmationDate") == confirmation_date
        records, merge_summary = merge_monthly_baseline(
            records,
            monthly_baseline["records"],
            preserve_baseline_decisions=preserve_baseline_decisions,
        )
        if merge_summary["baselineOnlyCount"] and not preserve_baseline_decisions:
            source_summary.setdefault("warnings", []).append(
                f"月度名单基线有{merge_summary['baselineOnlyCount']}人未出现在北森当前任职结果中，已保留并转人工确认。"
            )
        source_summary["monthlyBaseline"] = {
            "created": False,
            "capturedAt": monthly_baseline.get("capturedAt"),
            "source": monthly_baseline.get("source"),
            **merge_summary,
        }
    elif records:
        captured = capture_monthly_baseline(
            records=records,
            period_start=period_start,
            period_end=period_end,
            confirmation_date=confirmation_date,
            subject=subject,
            source=(
                "beisen-api-plus-historical-source"
                if source_summary.get("historicalBaselineSeedUsed")
                else "beisen-monthly-snapshot"
            ),
        )
        source_summary["monthlyBaseline"] = {
            **captured,
            "baselineCount": captured["recordCount"],
            "currentCount": len(records),
            "baselineOnlyCount": 0,
            "baselineDecisionReuseCount": 0,
            "mergedCount": len(records),
        }
    else:
        source_summary["monthlyBaseline"] = {
            "created": False,
            "recordCount": 0,
            "baselineCount": 0,
            "currentCount": 0,
            "baselineOnlyCount": 0,
            "baselineDecisionReuseCount": 0,
            "mergedCount": 0,
        }
    return create_run(
        records=records,
        period_start=period_start,
        period_end=period_end,
        confirmation_date=confirmation_date,
        subject=subject,
        source="beisen",
        source_summary=source_summary,
    )


def _subject_value(record: dict[str, Any]) -> str:
    source = record.get("source") if isinstance(record.get("source"), dict) else {}
    return str(source.get("subject") or source.get("subjectCode") or "").strip()


def materialize_all_subject_runs(
    *,
    records: list[dict[str, Any]],
    source_summary: dict[str, Any],
    period_start: str,
    period_end: str,
    confirmation_date: str,
    subject_options: list[dict[str, Any]] | None = None,
    preferred_subject: str = "",
    supplement_pool_records: list[dict[str, Any]] | None = None,
    supplement_pool_status: dict[str, Any] | None = None,
    diagnostics: ReportingRefreshDiagnostics | None = None,
) -> dict[str, Any]:
    """Create every subject batch, then atomically publish one PII-free release manifest."""
    if diagnostics is not None:
        diagnostics.begin_stage("batch_materialize")
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        subject = _subject_value(record)
        if subject:
            grouped.setdefault(subject, []).append(record)

    option_by_subject: dict[str, dict[str, Any]] = {}
    subject_order: list[str] = []
    for item in subject_options or []:
        if not isinstance(item, dict):
            continue
        subject = str(item.get("value") or item.get("label") or "").strip()
        if not subject or subject in option_by_subject:
            continue
        option_by_subject[subject] = item
        subject_order.append(subject)
    for subject in list_monthly_baseline_subjects(
        period_start=period_start,
        period_end=period_end,
    ):
        if subject not in subject_order:
            subject_order.append(subject)
    for subject in grouped:
        if subject not in subject_order:
            subject_order.append(subject)
    if not subject_order:
        raise RunValidationError("北森未返回本周期可生成的合同主体批次")

    normalized_preferred = str(preferred_subject or "").strip()
    selected_subject = normalized_preferred if normalized_preferred in subject_order else subject_order[0]
    creation_order = [subject for subject in subject_order if subject != selected_subject] + [selected_subject]
    run_by_subject: dict[str, dict[str, Any]] = {}
    created_runs: list[dict[str, Any]] = []
    for subject in creation_order:
        subject_records = grouped.get(subject, [])
        subject_summary = {
            **deepcopy(source_summary),
            "allSubjectBatchCount": len(subject_order),
        }
        capture_reporting_snapshot(
            records=subject_records,
            source_summary=subject_summary,
            period_start=period_start,
            period_end=period_end,
            confirmation_date=confirmation_date,
            subject=subject,
        )
        run = materialize_subject_run(
            records=subject_records,
            source_summary=subject_summary,
            period_start=period_start,
            period_end=period_end,
            confirmation_date=confirmation_date,
            subject=subject,
        )
        run_by_subject[subject] = run
        created_runs.append(run)

    published_at = current_timestamp()
    release_id = f"release_{published_at[:19].replace('-', '').replace(':', '').replace('T', '')}_{secrets.token_hex(4)}"
    subjects: list[dict[str, Any]] = []
    for subject in subject_order:
        option = option_by_subject.get(subject) or {}
        run = run_by_subject[subject]
        subjects.append({
            "value": subject,
            "label": str(option.get("label") or subject),
            "code": str(option.get("code") or ""),
            "candidateCount": len(grouped.get(subject, [])),
            "runId": run["id"],
            "runUpdatedAt": run.get("updatedAt"),
            "summary": deepcopy(run.get("summary") or {}),
            "preflight": build_export_preflight(run),
        })
    safe_source = {
        key: deepcopy(source_summary[key])
        for key in (
            "provider",
            "dataMode",
            "snapshotCapturedAt",
            "snapshotAgeSeconds",
            "snapshotStale",
            "warnings",
        )
        if key in source_summary
    }
    release = {
        "version": 1,
        "id": release_id,
        "state": "ready",
        "ruleVersion": RULE_VERSION,
        "periodStart": period_start,
        "periodEnd": period_end,
        "confirmationDate": confirmation_date,
        "publishedAt": published_at,
        "selectedSubject": selected_subject,
        "batchCount": len(subjects),
        "subjects": subjects,
        "source": safe_source,
    }
    supplement_index_summary = {"indexCount": 0, "candidateCount": 0}
    if diagnostics is not None:
        diagnostics.complete_active_stage()
        diagnostics.begin_stage("index_publish")
    if supplement_pool_records is not None:
        supplement_index_summary = publish_supplement_search_indexes(
            created_runs,
            records=supplement_pool_records,
            pool_status=supplement_pool_status or {},
        )
    if diagnostics is not None:
        diagnostics.complete_active_stage()
        diagnostics.begin_stage("release_publish")
    _persist_release(release)
    selected_run = run_by_subject[selected_subject]
    summaries = [
        {key: value for key, value in run.items() if key != "employees"}
        for run in created_runs
    ]
    if diagnostics is not None:
        diagnostics.complete_active_stage()
    return {
        "batchCount": len(created_runs),
        "runs": summaries,
        "selectedRun": selected_run,
        "releaseId": release_id,
        "release": release,
        "supplementSearchIndexCount": supplement_index_summary["indexCount"],
        "supplementSearchCandidateCount": supplement_index_summary["candidateCount"],
    }
