from __future__ import annotations

import asyncio
from pathlib import Path
import threading

from fastapi import HTTPException
import pytest

import bonus_platform.app as app_module
from bonus_platform.engine.labor import runs as labor_runs
from bonus_platform.engine.labor import worker_jobs


def _ready_run(monkeypatch, tmp_path: Path, *, extra: dict | None = None) -> dict:
    monkeypatch.setattr(labor_runs, "LABOR_RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(app_module, "LABOR_RUNS_DIR", tmp_path / "runs")
    pdf_path = tmp_path / "invoice.pdf"
    workbook_path = tmp_path / "bill.xlsx"
    pdf_path.write_bytes(b"pdf")
    workbook_path.write_bytes(b"xlsx")
    payload = {
        "supplierName": "Handoff Supplier",
        "ownerUserId": "user-1",
        "files": {
            "pdfInvoices": [labor_runs.attach_labor_file("pending", pdf_path, "PDF发票")],
            "workbooks": [labor_runs.attach_labor_file("pending", workbook_path, "线下账单")],
        },
        "workbookSheet": "Billing",
        "excelMapping": {"name": "Employee", "hours": "Hours", "amount": "Amount"},
    }
    payload.update(extra or {})
    return labor_runs.create_labor_run(payload)


def _configure_extract(monkeypatch, tmp_path: Path, *, personal_worker: bool) -> None:
    monkeypatch.setenv("LABOR_AUDIT_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(app_module, "_uses_request_scoped_labor_runtime", lambda: False)
    monkeypatch.setattr(app_module, "_uses_personal_labor_worker", lambda: personal_worker)
    monkeypatch.setattr(app_module, "_LABOR_TASK_LIMITER", app_module.LaborTaskLimiter())


def test_executor_handoff_failure_releases_reservation_and_marks_generation_failed(monkeypatch, tmp_path: Path):
    run = _ready_run(monkeypatch, tmp_path)
    _configure_extract(monkeypatch, tmp_path, personal_worker=False)

    class FailingLoop:
        def run_in_executor(self, *_args):
            raise RuntimeError("executor-shutdown")

    monkeypatch.setattr(app_module.asyncio, "get_event_loop", lambda: FailingLoop())

    with pytest.raises(RuntimeError, match="executor-shutdown"):
        asyncio.run(app_module.extract_and_compare_labor_run(run["id"]))

    failed = labor_runs.load_labor_metadata(labor_runs.get_labor_run_dir(run["id"]))
    assert app_module._LABOR_TASK_LIMITER.snapshot()["activeGlobalTasks"] == 0
    assert failed["status"] == "抽取失败"
    assert failed["asyncTask"]["status"] == "failed"
    assert failed["asyncTask"]["taskGenerationId"] == failed["taskGenerationId"]
    assert failed["retryable"] is True


def test_personal_worker_enqueue_failure_does_not_leave_run_queued(monkeypatch, tmp_path: Path):
    run = _ready_run(monkeypatch, tmp_path)
    _configure_extract(monkeypatch, tmp_path, personal_worker=True)
    monkeypatch.setattr(
        app_module,
        "enqueue_labor_worker_job",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("queue-unavailable")),
    )

    with pytest.raises(RuntimeError, match="queue-unavailable"):
        asyncio.run(app_module.extract_and_compare_labor_run(run["id"]))

    failed = labor_runs.load_labor_metadata(labor_runs.get_labor_run_dir(run["id"]))
    assert failed["status"] == "抽取失败"
    assert failed["asyncTask"]["status"] == "failed"

    enqueued: list[str] = []

    def enqueue(run_id: str, **kwargs) -> dict:
        enqueued.append(str(kwargs.get("task_generation_id") or ""))
        return {"id": "job-retry", "runId": run_id, "status": "queued"}

    monkeypatch.setattr(app_module, "enqueue_labor_worker_job", enqueue)
    retried = asyncio.run(app_module.extract_and_compare_labor_run(run["id"]))

    assert retried["workerTask"]["id"] == "job-retry"
    assert enqueued == [retried["taskGenerationId"]]


def test_stale_personal_worker_handoff_cannot_supersede_new_generation(monkeypatch, tmp_path: Path):
    run = _ready_run(monkeypatch, tmp_path)
    _configure_extract(monkeypatch, tmp_path, personal_worker=True)
    monkeypatch.setattr(worker_jobs, "LABOR_WORKER_JOBS_DIR", tmp_path / "jobs")

    old_request_paused = threading.Event()
    release_old_request = threading.Event()
    original_append_audit_event = app_module.append_labor_audit_event

    def pause_old_request_after_begin(*args, **kwargs):
        result = original_append_audit_event(*args, **kwargs)
        if threading.current_thread().name == "old-worker-request":
            old_request_paused.set()
            assert release_old_request.wait(timeout=5), "old request was not released"
        return result

    monkeypatch.setattr(app_module, "append_labor_audit_event", pause_old_request_after_begin)
    responses: dict[str, dict] = {}
    failures: list[BaseException] = []

    def run_old_request() -> None:
        try:
            responses["old"] = asyncio.run(app_module.extract_and_compare_labor_run(run["id"]))
        except BaseException as exc:  # noqa: BLE001 - surface thread failures in the test.
            failures.append(exc)

    old_thread = threading.Thread(target=run_old_request, name="old-worker-request")
    old_thread.start()
    assert old_request_paused.wait(timeout=5), "old request did not reach the handoff seam"

    app_module.save_labor_mapping(
        run["id"],
        {
            "sheet_name": "Billing",
            "mapping": {"name": "Employee", "hours": "Hours", "amount": "Updated Amount"},
        },
    )
    responses["new"] = asyncio.run(app_module.extract_and_compare_labor_run(run["id"]))
    new_generation = responses["new"]["taskGenerationId"]
    new_job_id = responses["new"]["workerTask"]["id"]

    release_old_request.set()
    old_thread.join(timeout=5)
    assert not old_thread.is_alive()
    assert failures == []

    saved = labor_runs.load_labor_metadata(labor_runs.get_labor_run_dir(run["id"]))
    active_jobs = [
        job
        for job in worker_jobs.list_labor_worker_jobs()
        if job["runId"] == run["id"] and job["status"] in worker_jobs.ACTIVE_STATUSES
    ]
    new_job = worker_jobs.get_labor_worker_job(new_job_id)

    assert saved["taskGenerationId"] == new_generation
    assert responses["old"]["taskGenerationId"] == new_generation
    assert responses["old"]["workerTask"]["id"] == new_job_id
    assert [(job["id"], job["taskGenerationId"]) for job in active_jobs] == [
        (new_job_id, new_generation)
    ]
    assert new_job["status"] == "queued"


def test_active_run_rejects_name_mapping_recalculation_before_mutation(monkeypatch, tmp_path: Path):
    candidate_id = "name-map-1"
    run = _ready_run(
        monkeypatch,
        tmp_path,
        extra={
            "status": "抽取中",
            "asyncTask": {"status": "running", "taskGenerationId": "generation-active"},
            "taskGenerationId": "generation-active",
            "nameMappingGovernance": {
                "candidates": [
                    {
                        "candidateId": candidate_id,
                        "status": "candidate",
                        "decision": "candidate_only",
                        "proposedMapping": {"Raw Worker": "Canonical Worker"},
                    }
                ],
                "replaySummaries": {
                    candidate_id: {
                        "decision": "ready_for_user_confirmation",
                        "summary": {"fixedCount": 1, "regressionCount": 0},
                    }
                },
            },
        },
    )
    monkeypatch.setattr(
        app_module,
        "_perform_labor_extract_compare",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("direct recalculation must not run")),
    )

    with pytest.raises(HTTPException) as raised:
        app_module.confirm_labor_name_mapping_candidate(
            run["id"],
            candidate_id,
            {"confirmedBy": "reviewer", "reason": "checked", "recalculate": True},
        )

    assert raised.value.status_code == 409
    saved = labor_runs.load_labor_metadata(labor_runs.get_labor_run_dir(run["id"]))
    assert saved.get("manualNameMapping") in (None, {})
    assert saved["nameMappingGovernance"]["candidates"][0]["status"] == "candidate"
