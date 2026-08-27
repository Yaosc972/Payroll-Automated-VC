from __future__ import annotations

import json
import logging
import os
import secrets
import tempfile
from pathlib import Path
from time import perf_counter_ns
from typing import Any

from fastapi import APIRouter, Body, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse

from ...auth import current_user_from_request, labor_auth_required, user_can_enter_module
from . import field_metadata
from .adapter import (
    cached_beisen_contract_subjects,
    connector_status,
    list_beisen_contract_subjects,
    sync_beisen_candidates,
)
from .baseline import (
    list_monthly_baseline_subjects,
    load_monthly_baseline,
)
from .field_metadata import FieldMetadataError
from .report import build_audit_export, generate_report, resolve_download, rpa_status, store_template
from .report_package import (
    build_export_preflight,
    build_missing_export,
    generate_report_package,
    resolve_package_download,
)
from .prefetch import (
    prefetch_scheduler_status,
    queue_reporting_snapshot_refresh,
    refresh_latest_reporting_snapshot,
)
from .publication import (
    load_latest_reporting_release,
    load_reporting_release,
    materialize_all_subject_runs,
    materialize_subject_run,
)
from .persistent_storage import storage_status
from .rule_catalog import public_rule_catalog
from .runs import (
    RunNotFoundError,
    RunValidationError,
    add_supplement_employee,
    confirm_run,
    default_confirmation_date,
    default_reporting_window,
    list_runs,
    load_run,
    load_run_index,
    load_supplement_search_context,
    persist_run_index,
    update_employee,
)
from .supplements import (
    invalidate_supplement_search_index,
    precomputed_supplement_status,
    remove_supplement_candidate_from_search_index,
    resolve_beisen_supplement_candidate,
    search_beisen_supplement_candidates,
    search_precomputed_supplement_candidates,
    supplement_pool_status,
)
from .sync_snapshot import capture_reporting_snapshot, load_reporting_snapshot
from .template_schemas import public_template_schemas


router = APIRouter(prefix="/api/social-insurance", tags=["social-insurance"])
PERFORMANCE_LOGGER = logging.getLogger("bonus_platform.social_insurance.performance")


def _elapsed_ms(started_ns: int) -> float:
    return (perf_counter_ns() - started_ns) / 1_000_000


def _decision_server_timing(performance: dict[str, Any]) -> str:
    metrics = (
        ("snapshot-load", "snapshot_load_ms"),
        ("state-mutation", "state_mutation_ms"),
        ("snapshot-save", "snapshot_save_ms"),
        ("preflight", "preflight_ms"),
        ("total", "total_ms"),
    )
    return ", ".join(
        f"{metric};dur={float(performance.get(field) or 0):.3f}"
        for metric, field in metrics
    )


def _log_decision_performance(
    response: Response,
    *,
    request_id: str,
    include_preflight: bool,
    performance: dict[str, float | int],
) -> None:
    event = {
        "event": "social_insurance_decision_performance",
        "request_id": request_id,
        "include_preflight": include_preflight,
        "snapshot_bytes": int(performance.get("snapshot_bytes") or 0),
        "persisted_bytes": int(performance.get("persisted_bytes") or 0),
        "snapshot_load_ms": round(float(performance.get("snapshot_load_ms") or 0), 3),
        "state_mutation_ms": round(float(performance.get("state_mutation_ms") or 0), 3),
        "snapshot_save_ms": round(float(performance.get("snapshot_save_ms") or 0), 3),
        "preflight_ms": round(float(performance.get("preflight_ms") or 0), 3),
        "total_ms": round(float(performance.get("total_ms") or 0), 3),
    }
    response.headers["Server-Timing"] = _decision_server_timing(event)
    response.headers["X-Sigma-Request-ID"] = request_id
    PERFORMANCE_LOGGER.info(
        json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )


def _require_access(request: Request) -> None:
    if not labor_auth_required():
        return
    current = current_user_from_request(request)
    if current is None:
        raise HTTPException(status_code=401, detail="请先登录西格玛工作台。")
    if not user_can_enter_module(current, "social_insurance"):
        raise HTTPException(status_code=403, detail="当前用户没有社保报盘工作台权限。")


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, RunNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, (RunValidationError, FieldMetadataError)):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=500, detail="社保报盘处理失败")


@router.get("/config")
def get_config(request: Request) -> dict[str, Any]:
    _require_access(request)
    start, end = default_reporting_window()
    return {
        "periodStart": start,
        "periodEnd": end,
        "confirmationDate": default_confirmation_date(end),
        "defaultSubject": "深圳市前海云途物流有限公司",
        "rpa": rpa_status(),
        "runtime": {
            "storage": storage_status(),
            "connector": connector_status(),
            "scheduler": "vercel-cron" if os.environ.get("VERCEL") else "local-development",
        },
    }


def _published_subject(release: dict[str, Any], subject: str) -> dict[str, Any] | None:
    normalized = str(subject or "").strip()
    return next(
        (
            item
            for item in release.get("subjects") or []
            if isinstance(item, dict) and str(item.get("value") or "").strip() == normalized
        ),
        None,
    )


def _public_published_subjects(release: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            key: item.get(key)
            for key in ("value", "label", "code", "candidateCount", "runId")
        }
        for item in release.get("subjects") or []
        if isinstance(item, dict)
    ]


def _published_run_bundle(release: dict[str, Any], subject: str) -> tuple[dict[str, Any], dict[str, Any]]:
    published_subject = _published_subject(release, subject)
    if published_subject is None:
        raise RunValidationError("所选合同主体不属于该成功集成版本")
    run = load_run(str(published_subject.get("runId") or ""))
    expected = (
        str(release.get("periodStart") or ""),
        str(release.get("periodEnd") or ""),
        str(release.get("confirmationDate") or ""),
        str(published_subject.get("value") or "").strip(),
    )
    actual = (
        str(run.get("periodStart") or ""),
        str(run.get("periodEnd") or ""),
        str(run.get("confirmationDate") or ""),
        str(run.get("subject") or "").strip(),
    )
    if actual != expected:
        raise RunValidationError("成功集成版本引用的主体批次不匹配")
    preflight = published_subject.get("preflight")
    if (
        not isinstance(preflight, dict)
        or preflight.get("runId") != run.get("id")
        or str(published_subject.get("runUpdatedAt") or "") != str(run.get("updatedAt") or "")
    ):
        preflight = build_export_preflight(run)
    return run, preflight


@router.get("/bootstrap")
def get_bootstrap(request: Request) -> dict[str, Any]:
    """Return the latest fully published integration without scans or live Beisen calls."""
    _require_access(request)
    try:
        release = load_latest_reporting_release()
        if release is None:
            start, end = default_reporting_window()
            return {
                "state": "empty",
                "label": "尚无成功发布的北森集成版本",
                "config": {
                    "periodStart": start,
                    "periodEnd": end,
                    "confirmationDate": default_confirmation_date(end),
                },
                "release": None,
                "subjects": [],
                "selectedSubject": "",
                "run": None,
                "preflight": None,
            }
        selected_subject = str(release.get("selectedSubject") or "").strip()
        if _published_subject(release, selected_subject) is None:
            selected_subject = str((release.get("subjects") or [{}])[0].get("value") or "").strip()
        confirmation_date = default_confirmation_date(str(release.get("periodEnd") or ""))
        run: dict[str, Any] | None = None
        preflight: dict[str, Any] | None = None
        if str(release.get("confirmationDate") or "") == confirmation_date:
            run, preflight = _published_run_bundle(release, selected_subject)
        return {
            "state": "ready",
            "config": {
                "periodStart": release["periodStart"],
                "periodEnd": release["periodEnd"],
                "confirmationDate": confirmation_date,
            },
            "release": {
                key: release.get(key)
                for key in (
                    "id",
                    "state",
                    "ruleVersion",
                    "periodStart",
                    "periodEnd",
                    "confirmationDate",
                    "publishedAt",
                    "batchCount",
                    "source",
                )
            },
            "subjects": _public_published_subjects(release),
            "selectedSubject": selected_subject,
            "run": run,
            "preflight": preflight,
        }
    except (RunNotFoundError, RunValidationError) as exc:
        raise _http_error(exc) from exc


@router.get("/cron/refresh")
def refresh_reporting_snapshot_from_cron(request: Request) -> dict[str, Any]:
    expected = os.environ.get("CRON_SECRET", "").strip()
    supplied = request.headers.get("authorization", "")
    if not expected or not secrets.compare_digest(supplied, f"Bearer {expected}"):
        raise HTTPException(status_code=401, detail="定时同步授权失败")
    try:
        return refresh_latest_reporting_snapshot()
    except (RunNotFoundError, RunValidationError) as exc:
        raise _http_error(exc) from exc


@router.get("/metadata")
def get_field_metadata(request: Request) -> dict[str, Any]:
    _require_access(request)
    try:
        return {
            "fields": field_metadata.public_field_definitions(),
            "administrativeDivisions": field_metadata.load_administrative_divisions(),
            "administrativeDivisionChoices": field_metadata.load_administrative_division_choices(),
            "schemas": public_template_schemas(),
            "source": "government-template-schema-registry",
        }
    except FieldMetadataError as exc:
        raise _http_error(exc) from exc


@router.get("/rules")
def get_business_rules(request: Request) -> dict[str, Any]:
    _require_access(request)
    return public_rule_catalog()


@router.get("/runs")
def get_runs(
    request: Request,
    limit: int = 20,
    period_start: str = Query(default="", alias="periodStart"),
    period_end: str = Query(default="", alias="periodEnd"),
    confirmation_date: str = Query(default="", alias="confirmationDate"),
    subject: str = Query(default=""),
) -> dict[str, Any]:
    _require_access(request)
    return {"runs": list_runs(
        limit,
        period_start=period_start,
        period_end=period_end,
        confirmation_date=confirmation_date,
        subject=subject,
    )}


def _contract_subject_payload(
    *,
    subjects: list[dict[str, Any]],
    period_start: str,
    period_end: str,
    source: str,
    **extra: Any,
) -> dict[str, Any]:
    merged = [dict(item) for item in subjects if isinstance(item, dict)]
    known = {
        str(item.get("value") or item.get("label") or "").strip()
        for item in merged
    }
    baseline_subject_count = 0
    for subject in list_monthly_baseline_subjects(
        period_start=period_start,
        period_end=period_end,
    ):
        if subject in known:
            continue
        baseline = load_monthly_baseline(
            period_start=period_start,
            period_end=period_end,
            subject=subject,
        )
        merged.append({
            "value": subject,
            "label": subject,
            "code": "",
            "candidateCount": len((baseline or {}).get("records") or []),
        })
        known.add(subject)
        baseline_subject_count += 1
    return {
        "subjects": merged,
        "periodStart": period_start,
        "periodEnd": period_end,
        "source": source,
        "baselineSubjectCount": baseline_subject_count,
        **extra,
    }


@router.get("/subjects")
def get_contract_subjects(
    request: Request,
    period_start: str = Query(alias="periodStart"),
    period_end: str = Query(alias="periodEnd"),
    refresh: bool = Query(default=False),
) -> dict[str, Any]:
    _require_access(request)
    try:
        if not refresh and not os.environ.get("SIGMA_SOCIAL_INSURANCE_SYNC_FIXTURE"):
            release = load_latest_reporting_release(
                period_start=period_start,
                period_end=period_end,
            )
            if release is not None:
                return {
                    "subjects": _public_published_subjects(release),
                    "periodStart": period_start,
                    "periodEnd": period_end,
                    "confirmationDate": release["confirmationDate"],
                    "source": "reporting-release",
                    "releaseId": release["id"],
                    "publishedAt": release["publishedAt"],
                }
            cached_subjects = cached_beisen_contract_subjects(
                period_start=period_start,
                period_end=period_end,
            )
            if cached_subjects is not None:
                return _contract_subject_payload(
                    subjects=cached_subjects,
                    period_start=period_start,
                    period_end=period_end,
                    source="beisen-contract-cache",
                )
            return {
                "subjects": [],
                "periodStart": period_start,
                "periodEnd": period_end,
                "source": "no-published-release",
            }
        try:
            subjects = list_beisen_contract_subjects(
                period_start=period_start,
                period_end=period_end,
                force_refresh=refresh,
            )
        except RunValidationError:
            cached_subjects = cached_beisen_contract_subjects(
                period_start=period_start,
                period_end=period_end,
            ) if refresh else None
            if cached_subjects is None:
                raise
            return _contract_subject_payload(
                subjects=cached_subjects,
                period_start=period_start,
                period_end=period_end,
                source="beisen-contract-cache",
                refreshWarning="北森实时刷新暂时失败，已保留最近缓存主体",
            )
        return _contract_subject_payload(
            subjects=subjects,
            period_start=period_start,
            period_end=period_end,
            source="beisen-contracts",
        )
    except (RunNotFoundError, RunValidationError) as exc:
        raise _http_error(exc) from exc


def _materialize_subject_run(
    *,
    records: list[dict[str, Any]],
    source_summary: dict[str, Any],
    period_start: str,
    period_end: str,
    confirmation_date: str,
    subject: str,
) -> dict[str, Any]:
    return materialize_subject_run(
        records=records,
        period_start=period_start,
        period_end=period_end,
        confirmation_date=confirmation_date,
        subject=subject,
        source_summary=source_summary,
    )


@router.post("/runs/sync")
def sync_run(request: Request, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    _require_access(request)
    period_start = str(payload.get("periodStart") or "")
    period_end = str(payload.get("periodEnd") or "")
    confirmation_date = str(payload.get("confirmationDate") or "")
    subject = str(payload.get("subject") or "").strip()
    force_refresh = bool(payload.get("forceRefresh"))
    try:
        if not confirmation_date:
            confirmation_date = default_confirmation_date(period_end)
        reporting_snapshot = None if force_refresh else load_reporting_snapshot(
                period_start=period_start,
                period_end=period_end,
                confirmation_date=confirmation_date,
                subject=subject,
            )
        if reporting_snapshot is not None:
            records = reporting_snapshot["records"]
            source_summary = {
                **(reporting_snapshot.get("sourceSummary") or {}),
                "dataMode": "background-snapshot",
                "snapshotCapturedAt": reporting_snapshot.get("capturedAt"),
                "snapshotAgeSeconds": reporting_snapshot.get("ageSeconds", 0),
                "snapshotStale": bool(reporting_snapshot.get("stale")),
            }
            if reporting_snapshot.get("stale"):
                source_summary.setdefault("warnings", []).append(
                    "当前使用最近一次北森后台快照生成名单，系统正在后台更新；最终提交前请确认更新时间。"
                )
                queue_reporting_snapshot_refresh({
                    "periodStart": period_start,
                    "periodEnd": period_end,
                    "confirmationDate": confirmation_date,
                    "subject": subject,
                })
        else:
            with tempfile.TemporaryDirectory(prefix="sigma-social-sync-") as temporary:
                records, source_summary = sync_beisen_candidates(
                    period_start=period_start,
                    period_end=period_end,
                    confirmation_date=confirmation_date,
                    subject=subject,
                    output_dir=Path(temporary),
                )
            capture_reporting_snapshot(
                records=records,
                source_summary=source_summary,
                period_start=period_start,
                period_end=period_end,
                confirmation_date=confirmation_date,
                subject=subject,
            )
            source_summary = {
                **source_summary,
                "dataMode": "live-beisen",
                "snapshotAgeSeconds": 0,
                "snapshotStale": False,
            }
        return _materialize_subject_run(
            records=records,
            source_summary=source_summary,
            period_start=period_start,
            period_end=period_end,
            confirmation_date=confirmation_date,
            subject=subject,
        )
    except (RunNotFoundError, RunValidationError) as exc:
        raise _http_error(exc) from exc


@router.post("/runs/sync-all")
def sync_all_runs(request: Request, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Fetch Beisen once, then persist an independently reviewable batch per subject."""
    _require_access(request)
    period_start = str(payload.get("periodStart") or "")
    period_end = str(payload.get("periodEnd") or "")
    confirmation_date = str(payload.get("confirmationDate") or "")
    preferred_subject = str(payload.get("subject") or "").strip()
    force_refresh = bool(payload.get("forceRefresh"))
    try:
        if not confirmation_date:
            confirmation_date = default_confirmation_date(period_end)
        reporting_snapshot = None if force_refresh else load_reporting_snapshot(
            period_start=period_start,
            period_end=period_end,
            confirmation_date=confirmation_date,
            subject="*",
        )
        if reporting_snapshot is not None and not reporting_snapshot.get("stale"):
            records = reporting_snapshot["records"]
            shared_summary = {
                **(reporting_snapshot.get("sourceSummary") or {}),
                "dataMode": "background-all-subject-snapshot",
                "snapshotCapturedAt": reporting_snapshot.get("capturedAt"),
                "snapshotAgeSeconds": reporting_snapshot.get("ageSeconds", 0),
                "snapshotStale": False,
            }
        else:
            with tempfile.TemporaryDirectory(prefix="sigma-social-sync-all-") as temporary:
                records, shared_summary = sync_beisen_candidates(
                    period_start=period_start,
                    period_end=period_end,
                    confirmation_date=confirmation_date,
                    subject="*",
                    output_dir=Path(temporary),
                )
            capture_reporting_snapshot(
                records=records,
                source_summary=shared_summary,
                period_start=period_start,
                period_end=period_end,
                confirmation_date=confirmation_date,
                subject="*",
            )
            shared_summary = {
                **shared_summary,
                "dataMode": "live-beisen-all-subjects",
                "snapshotAgeSeconds": 0,
                "snapshotStale": False,
            }
        cached_subjects = cached_beisen_contract_subjects(
            period_start=period_start,
            period_end=period_end,
        ) or []
        return materialize_all_subject_runs(
            records=records,
            source_summary=shared_summary,
            period_start=period_start,
            period_end=period_end,
            confirmation_date=confirmation_date,
            subject_options=cached_subjects,
            preferred_subject=preferred_subject,
        )
    except (RunNotFoundError, RunValidationError) as exc:
        raise _http_error(exc) from exc


@router.get("/runs/current")
def get_current_run(
    request: Request,
    period_start: str = Query(alias="periodStart"),
    period_end: str = Query(alias="periodEnd"),
    confirmation_date: str = Query(alias="confirmationDate"),
    subject: str = Query(),
) -> dict[str, Any]:
    """Resolve one exact batch through its PII-free index and return preflight in the same response."""
    _require_access(request)
    normalized_subject = subject.strip()
    try:
        if not normalized_subject:
            raise RunValidationError("合同主体不能为空")
        indexed = load_run_index(
            period_start=period_start,
            period_end=period_end,
            confirmation_date=confirmation_date,
            subject=normalized_subject,
        )
        run: dict[str, Any] | None = None
        lookup_source = "run-index" if indexed else "none"
        if indexed:
            try:
                run = load_run(str(indexed["runId"]))
            except RunNotFoundError:
                run = None
        expected = (period_start, period_end, confirmation_date, normalized_subject)
        if run is not None and (
            str(run.get("periodStart") or ""),
            str(run.get("periodEnd") or ""),
            str(run.get("confirmationDate") or ""),
            str(run.get("subject") or "").strip(),
        ) != expected:
            run = None
        if run is None:
            recent = list_runs(
                1,
                period_start=period_start,
                period_end=period_end,
                confirmation_date=confirmation_date,
                subject=normalized_subject,
            )
            if not recent:
                return {"run": None, "preflight": None, "lookupSource": "none"}
            run = load_run(str(recent[0]["id"]))
            persist_run_index(run, force=True)
            lookup_source = "run-list-fallback"
        return {
            "run": run,
            "preflight": build_export_preflight(run),
            "lookupSource": lookup_source,
        }
    except (RunNotFoundError, RunValidationError) as exc:
        raise _http_error(exc) from exc


@router.get("/releases/{release_id}/runs/current")
def get_published_run(
    request: Request,
    release_id: str,
    subject: str = Query(),
) -> dict[str, Any]:
    """Read the exact batch referenced by one immutable successful release."""
    _require_access(request)
    try:
        release = load_reporting_release(release_id)
        if release is None:
            raise RunNotFoundError("成功集成版本不存在")
        run, preflight = _published_run_bundle(release, subject)
        return {
            "run": run,
            "preflight": preflight,
            "lookupSource": "reporting-release",
            "releaseId": release_id,
        }
    except (RunNotFoundError, RunValidationError) as exc:
        raise _http_error(exc) from exc


@router.get("/runs/{run_id}")
def get_run(request: Request, run_id: str) -> dict[str, Any]:
    _require_access(request)
    try:
        return load_run(run_id)
    except (RunNotFoundError, RunValidationError) as exc:
        raise _http_error(exc) from exc


@router.post("/runs/{run_id}/supplement-candidates/search")
def search_supplement_candidates(
    request: Request,
    run_id: str,
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    _require_access(request)
    try:
        query = str(payload.get("query") or "")
        candidates = search_precomputed_supplement_candidates(run_id, query)
        if candidates is None:
            run = load_supplement_search_context(run_id) or load_run(run_id)
            candidates = search_beisen_supplement_candidates(run, query)
        return {"candidates": candidates, "rawApiResponseSaved": False}
    except (RunNotFoundError, RunValidationError) as exc:
        raise _http_error(exc) from exc


@router.get("/runs/{run_id}/supplement-candidates/status")
def get_supplement_candidate_status(request: Request, run_id: str) -> dict[str, Any]:
    _require_access(request)
    try:
        status = precomputed_supplement_status(run_id)
        if status is None:
            status = supplement_pool_status(
                load_supplement_search_context(run_id) or load_run(run_id)
            )
        return {
            **status,
            "scheduler": prefetch_scheduler_status(),
        }
    except (RunNotFoundError, RunValidationError) as exc:
        raise _http_error(exc) from exc


@router.post("/runs/{run_id}/supplements")
def add_supplement(
    request: Request,
    run_id: str,
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    _require_access(request)
    try:
        candidate_id = str(payload.get("candidateId") or "")
        run = load_run(run_id)
        record = resolve_beisen_supplement_candidate(run, candidate_id)
        updated = add_supplement_employee(
            run_id,
            record,
            reason_type=str(payload.get("reasonType") or ""),
            note=str(payload.get("note") or ""),
        )
        remove_supplement_candidate_from_search_index(
            run_id,
            candidate_id,
            run_updated_at=str(updated.get("updatedAt") or ""),
        )
        return updated
    except (RunNotFoundError, RunValidationError) as exc:
        raise _http_error(exc) from exc


@router.patch("/runs/{run_id}/employees/{employee_id}")
def patch_employee(
    request: Request,
    response: Response,
    run_id: str,
    employee_id: str,
    payload: dict[str, Any] = Body(...),
    include_preflight: bool = Query(default=False, alias="includePreflight"),
) -> dict[str, Any]:
    _require_access(request)
    decision_performance: dict[str, float | int] | None = (
        {} if set(payload) == {"decision"} else None
    )
    request_id = secrets.token_hex(8) if decision_performance is not None else ""
    request_started_ns = perf_counter_ns()
    try:
        updated = update_employee(
            run_id,
            employee_id,
            payload,
            performance=decision_performance,
        )
        report_updates = payload.get("report") if isinstance(payload.get("report"), dict) else {}
        template_updates = (
            payload.get("templateReport")
            if isinstance(payload.get("templateReport"), dict)
            else {}
        )
        if "证件号码" in report_updates or "证件号码" in template_updates:
            invalidate_supplement_search_index(run_id)
        if include_preflight:
            preflight_started_ns = perf_counter_ns()
            result = {
                "run": updated,
                "preflight": build_export_preflight(updated),
            }
            if decision_performance is not None:
                decision_performance["preflight_ms"] = _elapsed_ms(preflight_started_ns)
        else:
            result = updated
            if decision_performance is not None:
                decision_performance["preflight_ms"] = 0.0
        if decision_performance is not None:
            decision_performance["total_ms"] = _elapsed_ms(request_started_ns)
            _log_decision_performance(
                response,
                request_id=request_id,
                include_preflight=include_preflight,
                performance=decision_performance,
            )
        return result
    except (RunNotFoundError, RunValidationError) as exc:
        raise _http_error(exc) from exc


@router.post("/runs/{run_id}/confirm")
def confirm(request: Request, run_id: str) -> dict[str, Any]:
    _require_access(request)
    try:
        return confirm_run(run_id)
    except (RunNotFoundError, RunValidationError) as exc:
        raise _http_error(exc) from exc


@router.get("/runs/{run_id}/audit-export")
def download_audit_export(request: Request, run_id: str) -> FileResponse:
    _require_access(request)
    try:
        path = build_audit_export(run_id)
    except (RunNotFoundError, RunValidationError) as exc:
        raise _http_error(exc) from exc
    return FileResponse(
        path,
        filename=path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/runs/{run_id}/missing-export")
def download_missing_export(request: Request, run_id: str) -> FileResponse:
    _require_access(request)
    try:
        path = build_missing_export(run_id)
    except (RunNotFoundError, RunValidationError) as exc:
        raise _http_error(exc) from exc
    return FileResponse(
        path,
        filename=path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/runs/{run_id}/preflight")
def get_export_preflight(request: Request, run_id: str) -> dict[str, Any]:
    _require_access(request)
    try:
        return build_export_preflight(run_id)
    except (RunNotFoundError, RunValidationError) as exc:
        raise _http_error(exc) from exc


@router.post("/runs/{run_id}/template")
async def upload_template(
    request: Request,
    run_id: str,
    file: UploadFile = File(...),
    route: str = Query(default=""),
) -> dict[str, Any]:
    _require_access(request)
    try:
        content = await file.read(20 * 1024 * 1024 + 1)
        return store_template(run_id, file.filename or "government-template.xls", content, route=route)
    except (RunNotFoundError, RunValidationError) as exc:
        raise _http_error(exc) from exc
    finally:
        await file.close()


@router.post("/runs/{run_id}/generate")
def generate(request: Request, run_id: str) -> dict[str, Any]:
    _require_access(request)
    try:
        return generate_report(run_id)
    except (RunNotFoundError, RunValidationError) as exc:
        raise _http_error(exc) from exc


@router.post("/runs/{run_id}/generate-package")
def generate_package(request: Request, run_id: str) -> dict[str, Any]:
    _require_access(request)
    try:
        return generate_report_package(run_id)
    except (RunNotFoundError, RunValidationError) as exc:
        raise _http_error(exc) from exc


@router.get("/runs/{run_id}/package/download")
def download_package(request: Request, run_id: str) -> FileResponse:
    _require_access(request)
    try:
        path = resolve_package_download(run_id)
    except (RunNotFoundError, RunValidationError) as exc:
        raise _http_error(exc) from exc
    return FileResponse(path, filename=path.name, media_type="application/zip")


@router.get("/runs/{run_id}/download/{filename}")
def download(request: Request, run_id: str, filename: str) -> FileResponse:
    _require_access(request)
    try:
        path = resolve_download(run_id, filename)
    except (RunNotFoundError, RunValidationError) as exc:
        raise _http_error(exc) from exc
    media_type = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if path.suffix.lower() == ".xlsx"
        else "application/vnd.ms-excel"
    )
    return FileResponse(path, filename=path.name, media_type=media_type)


@router.get("/rpa/status")
def get_rpa_status(request: Request) -> dict[str, Any]:
    _require_access(request)
    return rpa_status()
