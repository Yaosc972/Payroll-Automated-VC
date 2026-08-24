from __future__ import annotations

from copy import deepcopy
from datetime import date
import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse

from ...auth import current_user_from_request, labor_auth_required, user_can_enter_module
from . import field_metadata
from .adapter import cached_beisen_contract_subjects, list_beisen_contract_subjects, sync_beisen_candidates
from .baseline import (
    capture_monthly_baseline,
    ensure_monthly_baseline_confirmation_date,
    list_monthly_baseline_subjects,
    load_monthly_baseline,
    merge_monthly_baseline,
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
    queue_contract_subject_refresh,
    queue_reporting_snapshot_refresh,
)
from .rule_catalog import public_rule_catalog
from .runs import (
    RunNotFoundError,
    RunValidationError,
    add_supplement_employee,
    confirm_run,
    create_run,
    default_reporting_window,
    list_runs,
    load_run,
    update_employee,
)
from .supplements import (
    resolve_beisen_supplement_candidate,
    search_beisen_supplement_candidates,
    supplement_pool_status,
)
from .sync_snapshot import capture_reporting_snapshot, load_reporting_snapshot
from .template_schemas import public_template_schemas


router = APIRouter(prefix="/api/social-insurance", tags=["social-insurance"])


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
        "confirmationDate": date.today().isoformat(),
        "defaultSubject": "深圳市前海云途物流有限公司",
        "rpa": rpa_status(),
    }


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
            options: dict[str, dict[str, Any]] = {}
            for run in list_runs(50):
                value = str(run.get("subject") or "").strip()
                if not value or value in options:
                    continue
                same_period = (
                    str(run.get("periodStart") or "") == period_start
                    and str(run.get("periodEnd") or "") == period_end
                )
                summary = run.get("summary") if isinstance(run.get("summary"), dict) else {}
                options[value] = {
                    "value": value,
                    "label": value,
                    "code": "",
                    "candidateCount": int(summary.get("total") or 0) if same_period else 0,
                }
            if options:
                refresh_queued = queue_contract_subject_refresh(period_start, period_end)
                return _contract_subject_payload(
                    subjects=list(options.values()),
                    period_start=period_start,
                    period_end=period_end,
                    source="recent-beisen-runs",
                    refreshQueued=refresh_queued,
                )
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
    """Apply the subject baseline and persist one review batch."""
    source_summary = {**source_summary, "candidateCount": len(records)}
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
            warnings = source_summary.setdefault("warnings", [])
            warnings.append(
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
    run = create_run(
        records=records,
        period_start=period_start,
        period_end=period_end,
        confirmation_date=confirmation_date,
        subject=subject,
        source="beisen",
        source_summary=source_summary,
    )
    return run


@router.post("/runs/sync")
def sync_run(request: Request, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    _require_access(request)
    period_start = str(payload.get("periodStart") or "")
    period_end = str(payload.get("periodEnd") or "")
    confirmation_date = str(payload.get("confirmationDate") or period_end)
    subject = str(payload.get("subject") or "").strip()
    force_refresh = bool(payload.get("forceRefresh"))
    try:
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
    confirmation_date = str(payload.get("confirmationDate") or period_end)
    preferred_subject = str(payload.get("subject") or "").strip()
    force_refresh = bool(payload.get("forceRefresh"))
    try:
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
        grouped: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            source = record.get("source") if isinstance(record.get("source"), dict) else {}
            subject = str(source.get("subject") or source.get("subjectCode") or "").strip()
            if subject:
                grouped.setdefault(subject, []).append(record)
        cached_subjects = cached_beisen_contract_subjects(
            period_start=period_start,
            period_end=period_end,
        ) or []
        subject_order = [
            str(item.get("value") or item.get("label") or "").strip()
            for item in cached_subjects
            if isinstance(item, dict)
        ]
        subject_order = list(dict.fromkeys(subject for subject in subject_order if subject))
        subject_order.extend(
            subject
            for subject in list_monthly_baseline_subjects(
                period_start=period_start,
                period_end=period_end,
            )
            if subject not in subject_order
        )
        subject_order.extend(subject for subject in grouped if subject not in subject_order)
        if preferred_subject in subject_order:
            subject_order = [subject for subject in subject_order if subject != preferred_subject] + [preferred_subject]
        grouped = {subject: grouped.get(subject, []) for subject in subject_order}
        if not grouped:
            raise RunValidationError("北森未返回本周期可生成的合同主体批次")

        created_runs: list[dict[str, Any]] = []
        selected_run: dict[str, Any] | None = None
        for subject, subject_records in grouped.items():
            subject_summary = {
                **deepcopy(shared_summary),
                "allSubjectBatchCount": len(grouped),
            }
            capture_reporting_snapshot(
                records=subject_records,
                source_summary=subject_summary,
                period_start=period_start,
                period_end=period_end,
                confirmation_date=confirmation_date,
                subject=subject,
            )
            run = _materialize_subject_run(
                records=subject_records,
                source_summary=subject_summary,
                period_start=period_start,
                period_end=period_end,
                confirmation_date=confirmation_date,
                subject=subject,
            )
            created_runs.append(run)
            if subject == preferred_subject:
                selected_run = run
        selected_run = selected_run or created_runs[0]
        summaries = [{key: value for key, value in run.items() if key != "employees"} for run in created_runs]
        return {"batchCount": len(created_runs), "runs": summaries, "selectedRun": selected_run}
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
        run = load_run(run_id)
        candidates = search_beisen_supplement_candidates(run, str(payload.get("query") or ""))
        return {"candidates": candidates, "rawApiResponseSaved": False}
    except (RunNotFoundError, RunValidationError) as exc:
        raise _http_error(exc) from exc


@router.get("/runs/{run_id}/supplement-candidates/status")
def get_supplement_candidate_status(request: Request, run_id: str) -> dict[str, Any]:
    _require_access(request)
    try:
        return {
            **supplement_pool_status(load_run(run_id)),
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
        run = load_run(run_id)
        record = resolve_beisen_supplement_candidate(run, str(payload.get("candidateId") or ""))
        return add_supplement_employee(
            run_id,
            record,
            reason_type=str(payload.get("reasonType") or ""),
            note=str(payload.get("note") or ""),
        )
    except (RunNotFoundError, RunValidationError) as exc:
        raise _http_error(exc) from exc


@router.patch("/runs/{run_id}/employees/{employee_id}")
def patch_employee(
    request: Request,
    run_id: str,
    employee_id: str,
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    _require_access(request)
    try:
        return update_employee(run_id, employee_id, payload)
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
