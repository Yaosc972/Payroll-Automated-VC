from __future__ import annotations

from datetime import date, datetime, timedelta
import logging
import os
from pathlib import Path
import tempfile
import threading
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .adapter import list_beisen_contract_subjects, sync_beisen_candidates
from .publication import materialize_all_subject_runs
from .reporting_diagnostics import ReportingRefreshDiagnostics, safe_error_category
from .runs import default_reporting_window, list_runs, load_run
from .supplements import (
    prepare_beisen_supplement_pool,
    prewarm_beisen_supplement_pool,
    supplement_pool_status,
)
from .sync_snapshot import capture_reporting_snapshot, seed_recent_reporting_snapshots


LOGGER = logging.getLogger("bonus_platform.social_insurance.prefetch")
JOB_ID = "social-insurance-supplement-pool"
INTERACTIVE_JOB_ID = f"{JOB_ID}-interactive"
REPORTING_JOB_ID = "social-insurance-reporting-snapshot"
REPORTING_INTERACTIVE_JOB_ID = f"{REPORTING_JOB_ID}-interactive"
SUBJECT_INTERACTIVE_JOB_PREFIX = "social-insurance-contract-subjects"
_SCHEDULER: BackgroundScheduler | None = None
_SCHEDULER_LOCK = threading.Lock()
_REPORTING_REFRESH_LOCK = threading.Lock()
_REPORTING_REFRESHING: set[tuple[str, str, str, str]] = set()
_SUBJECT_REFRESH_LOCK = threading.Lock()
_SUBJECT_REFRESHING: set[tuple[str, str]] = set()


def _env_enabled(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def prefetch_enabled() -> bool:
    if os.environ.get("VERCEL"):
        return False
    explicitly_configured = os.environ.get("SIGMA_SOCIAL_INSURANCE_PREFETCH_ENABLED")
    if explicitly_configured is not None:
        return _env_enabled("SIGMA_SOCIAL_INSURANCE_PREFETCH_ENABLED")
    return bool(
        os.environ.get("SIGMA_SOCIAL_INSURANCE_ENGINE_DIR")
        or os.environ.get("SIGMA_SOCIAL_INSURANCE_SYNC_FIXTURE")
    )


def _interval_minutes() -> int:
    try:
        return max(15, int(os.environ.get("SIGMA_SOCIAL_INSURANCE_PREFETCH_INTERVAL_MINUTES", "120")))
    except ValueError:
        return 120


def _startup_delay_seconds() -> float:
    configured = os.environ.get("SIGMA_SOCIAL_INSURANCE_PREFETCH_STARTUP_DELAY_SECONDS")
    if configured is None:
        return float(_interval_minutes() * 60)
    try:
        return max(0.0, float(configured))
    except ValueError:
        return float(_interval_minutes() * 60)


def _reporting_startup_delay_seconds() -> float:
    try:
        return max(
            5.0,
            float(os.environ.get("SIGMA_SOCIAL_INSURANCE_REPORTING_STARTUP_DELAY_SECONDS", "30")),
        )
    except ValueError:
        return 30.0


def _interactive_delay_seconds() -> float:
    try:
        return max(
            0.0,
            float(os.environ.get("SIGMA_SOCIAL_INSURANCE_PREFETCH_INTERACTIVE_DELAY_SECONDS", "0")),
        )
    except ValueError:
        return 0.0


def _reporting_interactive_delay_seconds() -> float:
    try:
        return max(
            1.0,
            float(os.environ.get("SIGMA_SOCIAL_INSURANCE_REPORTING_REFRESH_DELAY_SECONDS", "5")),
        )
    except ValueError:
        return 5.0


def _refresh_reporting_context(context: dict[str, str]) -> dict[str, Any]:
    refresh_key = (
        str(context.get("periodStart") or ""),
        str(context.get("periodEnd") or ""),
        str(context.get("confirmationDate") or ""),
        str(context.get("subject") or "").strip(),
    )
    with _REPORTING_REFRESH_LOCK:
        if refresh_key in _REPORTING_REFRESHING:
            return {"state": "warming", "label": "本期报盘快照正在后台更新"}
        _REPORTING_REFRESHING.add(refresh_key)
    diagnostics = ReportingRefreshDiagnostics()
    try:
        with diagnostics.stage("current_sync"):
            with tempfile.TemporaryDirectory(prefix="sigma-social-reporting-prefetch-") as temporary:
                records, source_summary = sync_beisen_candidates(
                    period_start=context["periodStart"],
                    period_end=context["periodEnd"],
                    confirmation_date=context["confirmationDate"],
                    subject=context["subject"],
                    output_dir=Path(temporary),
                )
        with diagnostics.stage("snapshot_persist"):
            captured = capture_reporting_snapshot(
                records=records,
                source_summary=source_summary,
                period_start=context["periodStart"],
                period_end=context["periodEnd"],
                confirmation_date=context["confirmationDate"],
                subject=context["subject"],
            )
        if context["subject"] != "*":
            return {"state": "ready", **captured, **diagnostics.success_payload()}
        with diagnostics.stage("supplement_pool"):
            supplement_records, supplement_pool = prepare_beisen_supplement_pool({
                "id": "scheduled-supplement-pool",
                "periodStart": context["periodStart"],
                "periodEnd": context["periodEnd"],
                "confirmationDate": context["confirmationDate"],
                "subject": "*",
                "employees": [],
            }, force=True)
        with diagnostics.stage("subjects"):
            subjects = list_beisen_contract_subjects(
                period_start=context["periodStart"],
                period_end=context["periodEnd"],
                force_refresh=True,
            )
        published = materialize_all_subject_runs(
            records=records,
            source_summary={
                **source_summary,
                "dataMode": "scheduled-beisen-release",
                "snapshotCapturedAt": captured["capturedAt"],
                "snapshotAgeSeconds": 0,
                "snapshotStale": False,
            },
            period_start=context["periodStart"],
            period_end=context["periodEnd"],
            confirmation_date=context["confirmationDate"],
            subject_options=subjects,
            supplement_pool_records=supplement_records,
            supplement_pool_status=supplement_pool,
            diagnostics=diagnostics,
        )
        return {
            "state": "ready",
            **captured,
            "batchCount": published["batchCount"],
            "releaseId": published["releaseId"],
            "supplementSearchIndexCount": published["supplementSearchIndexCount"],
            "supplementCandidateCount": int(supplement_pool.get("recordCount") or 0),
            "supplementPoolCachedAt": supplement_pool.get("cachedAt"),
            **diagnostics.success_payload(),
        }
    except Exception as exc:  # noqa: BLE001 - only fixed safe diagnostics may enter scheduler logs.
        diagnostics.fail_active_stage()
        error = diagnostics.error_payload(safe_error_category(exc))
        LOGGER.warning(
            "社保本期报盘快照后台更新失败 stage=%s category=%s elapsedMs=%d stageTimingsMs=%s",
            error["failedStage"],
            error["errorCategory"],
            error["elapsedMs"],
            error["stageTimingsMs"],
        )
        return {
            "state": "error",
            "label": "本期报盘快照后台更新失败",
            **error,
        }
    finally:
        with _REPORTING_REFRESH_LOCK:
            _REPORTING_REFRESHING.discard(refresh_key)


def _current_reporting_context() -> dict[str, str]:
    period_start, period_end = default_reporting_window(date.today())
    return {
        "periodStart": period_start,
        "periodEnd": period_end,
        "confirmationDate": date.today().isoformat(),
        "subject": "*",
    }


def refresh_latest_reporting_snapshot() -> dict[str, Any]:
    return _refresh_reporting_context(_current_reporting_context())


def queue_reporting_snapshot_refresh(context: dict[str, str]) -> bool:
    scheduler = _SCHEDULER
    if scheduler is None or not scheduler.running:
        return False
    scheduler.add_job(
        _refresh_reporting_context,
        args=[dict(context)],
        id=REPORTING_INTERACTIVE_JOB_ID,
        name="后台更新当前社保报盘快照",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        next_run_time=datetime.now(scheduler.timezone) + timedelta(seconds=_reporting_interactive_delay_seconds()),
    )
    return True


def _refresh_contract_subjects(period_start: str, period_end: str) -> dict[str, Any]:
    refresh_key = (str(period_start), str(period_end))
    with _SUBJECT_REFRESH_LOCK:
        if refresh_key in _SUBJECT_REFRESHING:
            return {"state": "warming", "label": "合同主体正在后台更新"}
        _SUBJECT_REFRESHING.add(refresh_key)
    try:
        subjects = list_beisen_contract_subjects(
            period_start=refresh_key[0],
            period_end=refresh_key[1],
            force_refresh=True,
        )
        return {"state": "ready", "subjectCount": len(subjects)}
    except Exception:  # noqa: BLE001 - connector details must not enter scheduler logs.
        LOGGER.warning("北森合同主体后台更新失败；具体原因仅在受控业务操作中展示")
        return {"state": "error", "label": "合同主体后台更新失败"}
    finally:
        with _SUBJECT_REFRESH_LOCK:
            _SUBJECT_REFRESHING.discard(refresh_key)


def queue_contract_subject_refresh(period_start: str, period_end: str) -> bool:
    scheduler = _SCHEDULER
    if scheduler is None or not scheduler.running:
        return False
    job_id = f"{SUBJECT_INTERACTIVE_JOB_PREFIX}-{period_start}-{period_end}"
    with _SUBJECT_REFRESH_LOCK:
        if (str(period_start), str(period_end)) in _SUBJECT_REFRESHING:
            return True
    if scheduler.get_job(job_id) is not None:
        return True
    scheduler.add_job(
        _refresh_contract_subjects,
        args=[str(period_start), str(period_end)],
        id=job_id,
        name="后台补齐北森合同主体",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        next_run_time=datetime.now(scheduler.timezone),
    )
    return True


def prefetch_latest_supplement_pool() -> dict[str, Any]:
    recent = list_runs(1)
    if not recent:
        return {"state": "empty", "label": "尚无可预热批次"}
    run = load_run(str(recent[0].get("id") or ""))
    return _prefetch_run(str(run.get("id") or ""))


def _prefetch_run(run_id: str) -> dict[str, Any]:
    run = load_run(run_id)
    try:
        return prewarm_beisen_supplement_pool(run, force=True)
    except Exception:  # noqa: BLE001 - keep connector and employee details out of logs.
        LOGGER.warning("社保候选池后台更新失败；具体原因仅在受控业务状态中展示")
        return {"state": "error", "label": "后台更新失败，可稍后重试"}


def queue_supplement_pool_prefetch(run_id: str) -> bool:
    scheduler = _SCHEDULER
    if scheduler is None or not scheduler.running:
        return False
    run = load_run(run_id)
    if supplement_pool_status(run).get("state") in {"ready", "warming"}:
        return False
    scheduler.add_job(
        _prefetch_run,
        args=[run_id],
        id=INTERACTIVE_JOB_ID,
        name="立即更新当前社保补充增员候选池",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        next_run_time=datetime.now(scheduler.timezone) + timedelta(seconds=_interactive_delay_seconds()),
    )
    return True


def start_social_insurance_prefetch_scheduler() -> None:
    global _SCHEDULER
    if not prefetch_enabled():
        return
    with _SCHEDULER_LOCK:
        if _SCHEDULER is not None and _SCHEDULER.running:
            return
        seed_recent_reporting_snapshots()
        scheduler = BackgroundScheduler(timezone="Asia/Shanghai", daemon=True)
        scheduler.add_job(
            prefetch_latest_supplement_pool,
            trigger=IntervalTrigger(minutes=_interval_minutes()),
            id=JOB_ID,
            name="后台更新社保补充增员候选池",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            next_run_time=datetime.now(scheduler.timezone) + timedelta(seconds=_startup_delay_seconds()),
        )
        scheduler.add_job(
            refresh_latest_reporting_snapshot,
            trigger=IntervalTrigger(minutes=_interval_minutes()),
            id=REPORTING_JOB_ID,
            name="后台更新社保全主体周期快照",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            next_run_time=(
                datetime.now(scheduler.timezone)
                + timedelta(seconds=_reporting_startup_delay_seconds())
            ),
        )
        scheduler.start()
        _SCHEDULER = scheduler


def stop_social_insurance_prefetch_scheduler() -> None:
    global _SCHEDULER
    with _SCHEDULER_LOCK:
        scheduler = _SCHEDULER
        _SCHEDULER = None
    if scheduler is not None and scheduler.running:
        scheduler.shutdown(wait=False)


def prefetch_scheduler_status() -> dict[str, Any]:
    scheduler = _SCHEDULER
    job = scheduler.get_job(JOB_ID) if scheduler is not None and scheduler.running else None
    reporting_job = scheduler.get_job(REPORTING_JOB_ID) if scheduler is not None and scheduler.running else None
    return {
        "enabled": prefetch_enabled(),
        "running": bool(scheduler is not None and scheduler.running),
        "refreshMinutes": _interval_minutes(),
        "nextRunAt": job.next_run_time.isoformat() if job and job.next_run_time else None,
        "reportingSnapshotNextRunAt": (
            reporting_job.next_run_time.isoformat()
            if reporting_job and reporting_job.next_run_time
            else None
        ),
    }
