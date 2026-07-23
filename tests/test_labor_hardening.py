import json
from datetime import datetime, timedelta
from pathlib import Path

from bonus_platform.engine.labor.audit import append_labor_audit_event, read_labor_audit_events
from bonus_platform.engine.labor.hardening import LaborHardeningPolicy, LaborResourceLimitError, LaborTaskLimiter, labor_storage_info
from bonus_platform.engine.labor.lifecycle import cleanup_expired_labor_runs


def test_hardening_policy_uses_configurable_defaults(monkeypatch):
    for name in (
        "LABOR_RUN_RETENTION_DAYS",
        "LABOR_OCR_CACHE_RETENTION_DAYS",
        "LABOR_OCR_CACHE_MAX_BYTES",
        "LABOR_MAX_PDF_BYTES",
        "LABOR_MAX_WORKBOOK_BYTES",
        "LABOR_MAX_PDF_FILES",
        "LABOR_MAX_WORKBOOK_FILES",
        "LABOR_MAX_PDF_PAGES",
        "LABOR_MAX_ACTIVE_TASKS_PER_OWNER",
        "LABOR_MAX_ACTIVE_TASKS_GLOBAL",
    ):
        monkeypatch.delenv(name, raising=False)

    policy = LaborHardeningPolicy.from_env()

    assert policy.run_retention_days == 90
    assert policy.ocr_cache_retention_days == 30
    assert policy.ocr_cache_max_bytes == 5 * 1024**3
    assert policy.max_pdf_bytes == 50 * 1024**2
    assert policy.max_workbook_bytes == 20 * 1024**2
    assert policy.max_pdf_files == 30
    assert policy.max_workbook_files == 10
    assert policy.max_pdf_pages == 300
    assert policy.max_active_tasks_per_owner == 1
    assert policy.max_active_tasks_global == 2


def test_hardening_policy_falls_back_from_invalid_positive_limits(monkeypatch):
    monkeypatch.setenv("LABOR_MAX_PDF_BYTES", "0")
    monkeypatch.setenv("LABOR_MAX_PDF_FILES", "not-a-number")
    monkeypatch.setenv("LABOR_RUN_RETENTION_DAYS", "0")

    policy = LaborHardeningPolicy.from_env()

    assert policy.max_pdf_bytes == 50 * 1024**2
    assert policy.max_pdf_files == 30
    assert policy.run_retention_days == 0


def test_audit_log_is_append_only_and_redacts_sensitive_fields(tmp_path):
    audit_path = tmp_path / "audit" / "labor.jsonl"

    first = append_labor_audit_event(
        audit_path,
        action="run_created",
        run_id="labor_1",
        owner_user_id="user-1",
        actor_user_id="user-1",
        outcome="success",
        details={"pdfFileCount": 2, "employeeName": "Sensitive Person", "amount": 123.45},
    )
    second = append_labor_audit_event(
        audit_path,
        action="files_uploaded",
        run_id="labor_1",
        owner_user_id="user-1",
        actor_user_id="user-1",
        outcome="success",
        details={"pdfPageCount": 5},
    )

    events = read_labor_audit_events(audit_path)
    raw = audit_path.read_text(encoding="utf-8")
    assert [event["eventId"] for event in events] == [first["eventId"], second["eventId"]]
    assert events[0]["details"] == {"pdfFileCount": 2}
    assert "Sensitive Person" not in raw
    assert "123.45" not in raw


def test_storage_info_exposes_policy_without_credentials(tmp_path):
    policy = LaborHardeningPolicy.from_env()

    info = labor_storage_info(
        policy,
        run_dir=tmp_path / "runs",
        cache_dir=tmp_path / "cache",
        audit_path=tmp_path / "audit" / "labor.jsonl",
        storage_backend="blob",
        storage_environment="uat",
        persistent_enabled=True,
    )

    assert info["storageBackend"] == "blob"
    assert info["paths"]["runDirectory"] == str(tmp_path / "runs")
    assert info["retention"]["runDays"] == 90
    assert info["limits"]["maxPdfPages"] == 300
    assert "token" not in json.dumps(info).lower()


def test_retention_cleanup_deletes_only_expired_inactive_runs(tmp_path):
    runs_dir = tmp_path / "runs"
    audit_path = tmp_path / "audit" / "labor.jsonl"
    persistent_deletes = []
    now = datetime(2026, 7, 13, 12, 0, 0)
    rows = [
        ("expired", now - timedelta(days=91), "已生成差异报告"),
        ("recent", now - timedelta(days=2), "已生成差异报告"),
        ("active", now - timedelta(days=120), "抽取中"),
    ]
    for run_id, updated_at, status in rows:
        run_dir = runs_dir / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "metadata.json").write_text(
            json.dumps(
                {
                    "id": run_id,
                    "updatedAt": updated_at.isoformat(),
                    "status": status,
                    "ownerUserId": "user-1",
                }
            ),
            encoding="utf-8",
        )

    summary = cleanup_expired_labor_runs(
        runs_dir,
        retention_days=90,
        audit_path=audit_path,
        now=now,
        delete_persistent=lambda run_id, owner_user_id: persistent_deletes.append((run_id, owner_user_id)),
    )

    assert summary["deletedRunIds"] == ["expired"]
    assert not (runs_dir / "expired").exists()
    assert (runs_dir / "recent").exists()
    assert (runs_dir / "active").exists()
    assert persistent_deletes == [("expired", "user-1")]
    assert read_labor_audit_events(audit_path)[0]["action"] == "run_deleted"


def test_task_limiter_enforces_owner_and_global_limits_and_releases():
    limiter = LaborTaskLimiter()
    policy = LaborHardeningPolicy(
        run_retention_days=90,
        ocr_cache_retention_days=30,
        ocr_cache_max_bytes=100,
        max_pdf_bytes=100,
        max_workbook_bytes=100,
        max_pdf_files=30,
        max_workbook_files=3,
        max_pdf_pages=300,
        max_active_tasks_per_owner=1,
        max_active_tasks_global=2,
    )

    run_1_token = limiter.reserve("run-1", "user-1", policy=policy, active_runs=[])
    try:
        limiter.reserve("run-2", "user-1", policy=policy, active_runs=[])
        raise AssertionError("owner limit should reject")
    except LaborResourceLimitError as exc:
        assert exc.code == "LABOR_OWNER_CONCURRENCY_LIMIT_EXCEEDED"
    limiter.reserve("run-3", "user-2", policy=policy, active_runs=[])
    try:
        limiter.reserve("run-4", "user-3", policy=policy, active_runs=[])
        raise AssertionError("global limit should reject")
    except LaborResourceLimitError as exc:
        assert exc.code == "LABOR_GLOBAL_CONCURRENCY_LIMIT_EXCEEDED"

    limiter.release("run-1", run_1_token)
    limiter.reserve("run-2", "user-1", policy=policy, active_runs=[])
    assert limiter.snapshot()["activeGlobalTasks"] == 2


def test_task_limiter_reservation_token_prevents_duplicate_and_stale_release():
    limiter = LaborTaskLimiter()
    policy = LaborHardeningPolicy(
        run_retention_days=90,
        ocr_cache_retention_days=30,
        ocr_cache_max_bytes=100,
        max_pdf_bytes=100,
        max_workbook_bytes=100,
        max_pdf_files=30,
        max_workbook_files=3,
        max_pdf_pages=300,
        max_active_tasks_per_owner=1,
        max_active_tasks_global=2,
    )

    first_token = limiter.reserve("run-1", "user-1", policy=policy, active_runs=[])
    assert isinstance(first_token, str) and first_token
    try:
        limiter.reserve("run-1", "user-1", policy=policy, active_runs=[])
        raise AssertionError("the same run must not receive a second reservation")
    except LaborResourceLimitError as exc:
        assert exc.code == "LABOR_RUN_ALREADY_ACTIVE"

    assert limiter.release("run-1", "stale-token") is False
    assert limiter.snapshot()["activeGlobalTasks"] == 1
    assert limiter.release("run-1", first_token) is True

    second_token = limiter.reserve("run-1", "user-1", policy=policy, active_runs=[])
    assert second_token != first_token
    assert limiter.release("run-1", first_token) is False
    assert limiter.snapshot()["activeGlobalTasks"] == 1
    assert limiter.release("run-1", second_token) is True


def test_task_limiter_ignores_metadata_from_a_previous_process():
    limiter = LaborTaskLimiter()
    policy = LaborHardeningPolicy(
        run_retention_days=90,
        ocr_cache_retention_days=30,
        ocr_cache_max_bytes=100,
        max_pdf_bytes=100,
        max_workbook_bytes=100,
        max_pdf_files=30,
        max_workbook_files=3,
        max_pdf_pages=300,
        max_active_tasks_per_owner=1,
        max_active_tasks_global=2,
    )

    limiter.reserve(
        "new-run",
        "user-1",
        policy=policy,
        active_runs=[
                {
                    "id": "previous-process-run",
                    "ownerUserId": "user-1",
                    "status": "抽取中",
                    "asyncTask": {"status": "running"},
                }
        ],
    )

    assert limiter.snapshot()["activeGlobalTasks"] == 1
