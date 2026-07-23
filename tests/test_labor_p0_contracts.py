from __future__ import annotations

import asyncio
import json
import threading
from copy import deepcopy
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

import bonus_platform.app as app_module
from bonus_platform.app import app
from bonus_platform.engine.labor import runs as labor_runs
from bonus_platform.engine.labor.models import LaborLineItem
from bonus_platform.engine.labor.production_readiness import evaluate_labor_production_readiness
from bonus_platform.engine.labor.structure import evaluate_batch_guards


def _row(name: str, *, source_file: str, amount: float = 100.0) -> LaborLineItem:
    return LaborLineItem(
        source_type="pdf_invoice",
        source_file=source_file,
        source_page_or_row="p1",
        employee_id="",
        employee_name_raw=name,
        hours=8.0,
        amount=amount,
        currency="EUR",
        confidence=0.99,
        warehouse_id="1",
    )


def _releasable_metadata(tmp_path: Path) -> dict:
    report_path = tmp_path / "labor-p0-diff.xlsx"
    report_path.write_bytes(b"p0-report")
    report_url = "/api/labor/runs/labor_p0/download/labor-p0-diff.xlsx"
    report_record = labor_runs.attach_labor_file("labor_p0", report_path, "差异报告")
    report_record["downloadUrl"] = report_url
    metadata = {
        "id": "labor_p0",
        "status": "已生成差异报告",
        "supplierName": "P0 Supplier",
        "periodStart": "2026-07-01",
        "periodEnd": "2026-07-07",
        "currency": "EUR",
        "files": {
            "pdfInvoices": [{"filename": "invoice-a.pdf", "originalFilename": "invoice.pdf"}],
            "workbooks": [{"filename": "bill-a.xlsx", "originalFilename": "bill.xlsx"}],
            "diffReport": report_record,
        },
        "workbookSheet": "Billing",
        "excelMapping": {"name": "Employee", "hours": "Hours", "amount": "Amount"},
        "manualNameMapping": {},
        "comparisonSummary": {
            "exceptionCount": 0,
            "pdfEmployeeCount": 1,
            "excelEmployeeCount": 1,
            "conclusionLevel": "pass",
            "canRelease": True,
            "machineCheckStatus": "passed",
        },
        "comparisonRows": [{"employeeName": "Synthetic Worker", "matchStatus": "通过"}],
        "diffDownloadUrl": report_url,
        "machineCheckStatus": "passed",
        "batchGuard": {"status": "ok", "allowReleasableReport": True},
        "reconciliationDiagnostics": {"level": "ok", "issues": []},
        "extractionQuality": {"level": "ok", "issues": []},
    }
    metadata["resultInputFingerprint"] = app_module._labor_result_input_fingerprint(metadata)
    return metadata


def test_formal_mutation_enforces_client_contract_by_default(monkeypatch):
    monkeypatch.setenv("SIGMA_TEST_NO_LABOR_CONTRACT_HEADERS", "1")
    monkeypatch.delenv("SIGMA_LABOR_REQUIRE_CLIENT_CONTRACT", raising=False)
    monkeypatch.setattr(
        app_module,
        "_labor_build_snapshot",
        lambda: {"status": "current", "buildId": "p0-contract-default"},
    )
    monkeypatch.setattr(app_module, "create_labor_run", lambda _payload: {"id": "must-not-be-created"})

    response = TestClient(app).post(
        "/api/labor/runs",
        json={
            "supplier_name": "P0 Contract Probe",
            "period_start": "2026-07-01",
            "period_end": "2026-07-07",
            "currency": "EUR",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["errorCode"] == "LABOR_CLIENT_UPGRADE_REQUIRED"


def test_formal_mutation_cannot_disable_client_contract_with_deployment_env(monkeypatch):
    monkeypatch.setenv("SIGMA_TEST_NO_LABOR_CONTRACT_HEADERS", "1")
    monkeypatch.setenv("SIGMA_LABOR_REQUIRE_CLIENT_CONTRACT", "false")
    monkeypatch.setattr(
        app_module,
        "_labor_build_snapshot",
        lambda: {"status": "current", "buildId": "p0-contract-unconditional"},
    )
    monkeypatch.setattr(app_module, "create_labor_run", lambda _payload: {"id": "must-not-be-created"})

    response = TestClient(app).post(
        "/api/labor/runs",
        json={
            "supplier_name": "P0 Contract Probe",
            "period_start": "2026-07-01",
            "period_end": "2026-07-07",
            "currency": "EUR",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["errorCode"] == "LABOR_CLIENT_UPGRADE_REQUIRED"


def test_readiness_blocks_explicitly_disabled_client_contract():
    result = evaluate_labor_production_readiness(
        env={
            "SIGMA_LABOR_REQUIRE_CLIENT_CONTRACT": "false",
            "SIGMA_LABOR_WORKER_TOKENS": json.dumps(
                {"token": {"userId": "user-1", "deviceId": "device-1"}}
            ),
            "SIGMA_LABOR_OPERATIONS_TOKEN": "ops-token",
            "SIGMA_LABOR_EXECUTION_MODE": "personal-worker",
            "SIGMA_LABOR_EXTERNAL_AI_ENABLED": "false",
        },
        storage_info={"enabled": True, "backend": "blob", "environment": "uat"},
        queue_health={"backend": "postgres", "configured": True, "ready": True},
        build_info={"status": "current", "buildId": "build-p0", "requiredWorkerVersion": "0.3.0"},
    )

    assert result["status"] == "blocked"
    assert "client_contract_required" in {item["code"] for item in result["blockers"]}


def test_stale_runtime_blocks_worker_result_and_complete(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "_labor_build_snapshot",
        lambda: {"status": "restart_required", "buildId": "stale-build"},
    )
    client = TestClient(app)

    result = client.post(
        "/api/labor/worker/jobs/job-1/result",
        files={"result_archive": ("result.zip", b"not-used", "application/zip")},
    )
    complete = client.post("/api/labor/worker/jobs/job-1/complete")

    assert result.status_code == 409
    assert result.json()["detail"]["errorCode"] == "LABOR_SERVICE_RESTART_REQUIRED"
    assert complete.status_code == 409
    assert complete.json()["detail"]["errorCode"] == "LABOR_SERVICE_RESTART_REQUIRED"


def test_new_run_starts_in_pending_human_review_state(monkeypatch, tmp_path):
    monkeypatch.setattr(labor_runs, "LABOR_RUNS_DIR", tmp_path / "runs")

    run = labor_runs.create_labor_run({"supplierName": "P0 Supplier"})

    assert run["businessReviewStatus"] == "pending"
    assert run["manualReviewRequired"] is True
    assert run["directPaymentAllowed"] is False
    assert run["requiresHumanReview"] is True


def test_batch_guard_blocks_partial_employee_detail_coverage():
    guard = evaluate_batch_guards(
        pdf_paths=[Path("invoice-1.pdf"), Path("invoice-2.pdf")],
        pdf_totals=[
            {"source_file": "invoice-1.pdf", "total_amount": 100.0},
            {"source_file": "invoice-2.pdf", "total_amount": 200.0},
        ],
        raw_pdf_rows=[_row("Alice", source_file="invoice-1.pdf")],
        formal_pdf_rows=[_row("Alice", source_file="invoice-1.pdf")],
        excel_rows=[
            _row("Alice", source_file="bill.xlsx"),
            _row("Bob", source_file="bill.xlsx", amount=200.0),
        ],
        requested_currency="EUR",
        detected_currencies={"EUR"},
    )

    assert guard.status == "employee_detail_incomplete"
    assert guard.allow_releasable_report is False
    assert guard.unresolved_files == ("invoice-2.pdf",)


def test_batch_guard_allows_summary_invoices_when_all_declared_detail_attachments_are_covered():
    guard = evaluate_batch_guards(
        pdf_paths=[Path("summary.pdf"), Path("detail-a.pdf"), Path("detail-b.pdf")],
        pdf_totals=[
            {"source_file": "summary.pdf", "total_amount": 300.0, "has_employee_detail": False},
            {"source_file": "detail-a.pdf", "total_amount": 100.0, "has_employee_detail": True},
            {"source_file": "detail-b.pdf", "total_amount": 200.0, "has_employee_detail": True},
        ],
        raw_pdf_rows=[
            _row("Alice", source_file="detail-a.pdf"),
            _row("Bob", source_file="detail-b.pdf", amount=200.0),
        ],
        formal_pdf_rows=[
            _row("Alice", source_file="detail-a.pdf"),
            _row("Bob", source_file="detail-b.pdf", amount=200.0),
        ],
        excel_rows=[
            _row("Alice", source_file="bill.xlsx"),
            _row("Bob", source_file="bill.xlsx", amount=200.0),
        ],
        requested_currency="EUR",
        detected_currencies={"EUR"},
    )

    assert guard.status == "ok"
    assert guard.allow_releasable_report is True


def test_machine_conclusion_requires_complete_clean_employee_comparison():
    warehouse = {
        "summary": {
            "totalPassed": True,
            "pdfAmountTotal": 300.0,
            "excelAmountTotal": 300.0,
            "amountDeltaTotal": 0.0,
        }
    }

    extraction_warning = app_module._build_conclusion(
        warehouse,
        {
            "summary": {
                "pdfEmployeeCount": 2,
                "excelEmployeeCount": 2,
                "amountDiffCount": 0,
                "exceptionCount": 0,
                "lowConfidenceCount": 0,
            },
            "rows": [],
        },
        {"level": "warning", "message": "员工明细证据不完整。"},
    )
    employee_exception = app_module._build_conclusion(
        warehouse,
        {
            "summary": {
                "pdfEmployeeCount": 2,
                "excelEmployeeCount": 2,
                "amountDiffCount": 0,
                "exceptionCount": 1,
                "lowConfidenceCount": 0,
            },
            "rows": [{"matchStatus": "Excel有PDF无"}],
        },
        {"level": "ok"},
    )
    complete = app_module._build_conclusion(
        warehouse,
        {
            "summary": {
                "pdfEmployeeCount": 2,
                "excelEmployeeCount": 2,
                "amountDiffCount": 0,
                "exceptionCount": 0,
                "lowConfidenceCount": 0,
            },
            "rows": [],
        },
        {"level": "ok"},
    )

    assert extraction_warning["conclusionLevel"] == "warning"
    assert employee_exception["conclusionLevel"] == "warning"
    assert complete["conclusionLevel"] == "pass"


def test_readiness_blocks_non_releasable_batch_guard_even_when_summary_looks_clean():
    metadata = {
            "status": "已生成差异报告",
            "comparisonSummary": {
                "exceptionCount": 0,
                "conclusionLevel": "pass",
                "canRelease": False,
                "machineCheckStatus": "needs_review",
            },
            "machineCheckStatus": "needs_review",
            "batchGuard": {
                "status": "employee_detail_incomplete",
                "allowReleasableReport": False,
                "message": "仍有应核对 PDF 未形成员工明细。",
            },
            "reconciliationDiagnostics": {"level": "ok", "issues": []},
            "extractionQuality": {"level": "ok", "issues": []},
        }
    metadata["resultInputFingerprint"] = app_module._labor_result_input_fingerprint(metadata)
    gate = app_module._build_labor_readiness_gate(metadata)

    assert gate["status"] == "blocked"
    assert gate["ready"] is False
    assert "non_releasable_batch_guard" in {issue["code"] for issue in gate["issues"]}


def test_readiness_requires_result_to_match_current_files_and_mapping(tmp_path: Path):
    current = _releasable_metadata(tmp_path)
    assert app_module._build_labor_readiness_gate(current)["ready"] is True

    changed_file = deepcopy(current)
    changed_file["files"]["pdfInvoices"][0]["filename"] = "invoice-b.pdf"
    changed_mapping = deepcopy(current)
    changed_mapping["excelMapping"]["amount"] = "Net Amount"

    for stale in (changed_file, changed_mapping):
        gate = app_module._build_labor_readiness_gate(stale)
        assert gate["ready"] is False
        assert "stale_result_inputs" in {issue["code"] for issue in gate["issues"]}


def test_readiness_requires_result_to_match_active_governance(tmp_path: Path):
    current = _releasable_metadata(tmp_path)
    changed = deepcopy(current)
    changed["nameMappingGovernance"] = {
        "activeMappings": [
            {
                "candidateId": "mapping-1",
                "decision": "active",
                "status": "active",
                "proposedMapping": {"ALICE": "Alice"},
            }
        ]
    }

    gate = app_module._build_labor_readiness_gate(changed)

    assert gate["ready"] is False
    assert "stale_result_inputs" in {issue["code"] for issue in gate["issues"]}


def test_readiness_fails_closed_when_result_input_fingerprint_is_missing(tmp_path: Path):
    current = _releasable_metadata(tmp_path)
    current.pop("resultInputFingerprint")

    gate = app_module._build_labor_readiness_gate(current)

    assert gate["ready"] is False
    assert "missing_result_input_fingerprint" in {issue["code"] for issue in gate["issues"]}


def test_readiness_requires_employee_rows_counts_and_downloadable_report(tmp_path: Path):
    current = _releasable_metadata(tmp_path)

    missing_rows = deepcopy(current)
    missing_rows["comparisonRows"] = []
    missing_counts = deepcopy(current)
    missing_counts["comparisonSummary"].pop("pdfEmployeeCount")
    partial_rows = deepcopy(current)
    partial_rows["comparisonSummary"]["pdfEmployeeCount"] = 2
    partial_rows["comparisonSummary"]["excelEmployeeCount"] = 2
    dirty_row = deepcopy(current)
    dirty_row["comparisonRows"][0]["matchStatus"] = "金额差异"
    missing_report = deepcopy(current)
    missing_report["files"].pop("diffReport")
    missing_report["diffDownloadUrl"] = ""

    expected_codes = {
        "missing_employee_detail_result",
        "employee_detail_counts_not_closed",
        "missing_official_report",
    }
    observed_codes = set()
    for incomplete in (missing_rows, missing_counts, partial_rows, dirty_row, missing_report):
        gate = app_module._build_labor_readiness_gate(incomplete)
        assert gate["ready"] is False
        observed_codes.update(issue["code"] for issue in gate["issues"])

    assert expected_codes.issubset(observed_codes)
    assert "employee_detail_rows_not_clean" in observed_codes


def test_readiness_rejects_tampered_official_report(tmp_path: Path):
    current = _releasable_metadata(tmp_path)
    report_path = Path(current["files"]["diffReport"]["path"])
    report_path.write_bytes(b"tampered-report")

    gate = app_module._build_labor_readiness_gate(current)

    assert gate["ready"] is False
    assert "report_file_missing" in {issue["code"] for issue in gate["issues"]}


def test_failed_worker_status_cannot_reuse_old_machine_result(tmp_path: Path):
    failed = _releasable_metadata(tmp_path)
    failed["status"] = "失败"
    failed["asyncTask"] = {"status": "failed"}

    gate = app_module._build_labor_readiness_gate(failed)

    assert gate["ready"] is False
    assert "run_not_finished" in {issue["code"] for issue in gate["issues"]}


def test_pending_ocr_status_cannot_be_machine_ready(tmp_path: Path):
    pending = _releasable_metadata(tmp_path)
    pending["status"] = "待图片识别复核"

    gate = app_module._build_labor_readiness_gate(pending)

    assert gate["ready"] is False
    assert "run_not_finished" in {issue["code"] for issue in gate["issues"]}


def test_total_only_diagnostic_scope_cannot_be_machine_ready(tmp_path: Path):
    diagnostic = _releasable_metadata(tmp_path)
    diagnostic["reconciliationScope"] = "total_only_diagnostic"
    diagnostic["diagnosticOnly"] = True
    diagnostic["resultInputFingerprint"] = app_module._labor_result_input_fingerprint(diagnostic)

    gate = app_module._build_labor_readiness_gate(diagnostic)

    assert gate["ready"] is False
    assert "formal_employee_detail_scope_required" in {issue["code"] for issue in gate["issues"]}


def test_result_input_fingerprint_tracks_file_content_at_same_path(tmp_path: Path):
    pdf_path = tmp_path / "invoice.pdf"
    workbook_path = tmp_path / "bill.xlsx"
    pdf_path.write_bytes(b"old-pdf-bytes")
    workbook_path.write_bytes(b"workbook-bytes")
    metadata = {
        "files": {
            "pdfInvoices": [labor_runs.attach_labor_file("labor_hash", pdf_path, "PDF发票")],
            "workbooks": [labor_runs.attach_labor_file("labor_hash", workbook_path, "线下账单")],
        },
        "workbookSheet": "Billing",
        "excelMapping": {"name": "Employee", "hours": "Hours", "amount": "Amount"},
    }
    before = app_module._labor_result_input_fingerprint(metadata)

    pdf_path.write_bytes(b"new-pdf-bytes")
    after = app_module._labor_result_input_fingerprint(metadata)

    assert before != after


def test_result_publish_compare_and_set_rejects_changed_inputs(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(labor_runs, "LABOR_RUNS_DIR", tmp_path / "runs")
    pdf_path = tmp_path / "invoice.pdf"
    workbook_path = tmp_path / "bill.xlsx"
    pdf_path.write_bytes(b"pdf")
    workbook_path.write_bytes(b"xlsx")
    run = labor_runs.create_labor_run(
        {
            "files": {
                "pdfInvoices": [labor_runs.attach_labor_file("pending", pdf_path, "PDF发票")],
                "workbooks": [labor_runs.attach_labor_file("pending", workbook_path, "线下账单")],
            },
            "workbookSheet": "Billing",
            "excelMapping": {"name": "Employee", "hours": "Hours", "amount": "Amount"},
        }
    )
    expected = app_module._labor_result_input_fingerprint(run)
    labor_runs.update_labor_metadata(
        run["id"],
        {"excelMapping": {"name": "Employee", "hours": "Hours", "amount": "Net Amount"}},
    )

    updated, committed = labor_runs.compare_and_update_labor_metadata(
        run["id"],
        expected_fingerprint=expected,
        fingerprint=app_module._labor_result_input_fingerprint,
        updates={
            "status": "已生成差异报告",
            "comparisonSummary": {"canRelease": True, "conclusionLevel": "pass"},
            "machineCheckStatus": "passed",
        },
        conflict_updates=lambda current: app_module._labor_invalidate_official_result(
            current,
            status="输入已变更，待重新核对",
            reason_code="inputs_changed_during_extraction",
            message="输入变更。",
        ),
    )

    assert committed is False
    assert updated["excelMapping"]["amount"] == "Net Amount"
    assert updated["comparisonSummary"] == {}
    assert updated["machineCheckStatus"] == "needs_review"
    assert updated["batchGuard"]["allowReleasableReport"] is False


def test_result_publish_rejects_stale_task_generation_without_mutating_newer_result(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(labor_runs, "LABOR_RUNS_DIR", tmp_path / "runs")
    run = labor_runs.create_labor_run(
        {
            "taskGenerationId": "task-new",
            "status": "已生成差异报告",
            "asyncTask": {"status": "completed", "taskGenerationId": "task-new"},
            "comparisonSummary": {"canRelease": True, "conclusionLevel": "pass"},
        }
    )

    updated, committed = labor_runs.compare_and_update_labor_metadata(
        run["id"],
        expected_task_generation_id="task-old",
        expected_fingerprint="same-input",
        fingerprint=lambda _metadata: "same-input",
        updates={"comparisonSummary": {"source": "stale-task"}},
        conflict_updates=lambda _current: {
            "status": "输入已变更，待重新核对",
            "comparisonSummary": {},
        },
    )

    assert committed is False
    assert updated["taskGenerationId"] == "task-new"
    assert updated["status"] == "已生成差异报告"
    assert updated["comparisonSummary"] == {"canRelease": True, "conclusionLevel": "pass"}


def test_stale_task_failure_does_not_overwrite_newer_task(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(labor_runs, "LABOR_RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(app_module, "LABOR_RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(app_module, "labor_persistent_storage_enabled", lambda: False)
    monkeypatch.setattr(app_module, "append_labor_audit_event", lambda *_args, **_kwargs: {})
    run = labor_runs.create_labor_run(
        {
            "taskGenerationId": "task-old",
            "status": "抽取中",
            "asyncTask": {"status": "running", "taskGenerationId": "task-old"},
        }
    )

    def superseded_failure(_run_id: str, task_generation_id: str = "") -> dict:
        assert task_generation_id == "task-old"
        labor_runs.update_labor_metadata(
            run["id"],
            {
                "taskGenerationId": "task-new",
                "status": "抽取中",
                "stage": "新任务处理中",
                "asyncTask": {"status": "running", "taskGenerationId": "task-new"},
            },
        )
        raise ValueError("old task failed after the new task started")

    monkeypatch.setattr(app_module, "_perform_labor_extract_compare", superseded_failure)

    completed = app_module._run_labor_extract_compare(run["id"], task_generation_id="task-old")
    saved = labor_runs.load_labor_metadata(labor_runs.get_labor_run_dir(run["id"]))

    assert completed is False
    assert saved["taskGenerationId"] == "task-new"
    assert saved["status"] == "抽取中"
    assert saved["stage"] == "新任务处理中"
    assert saved["asyncTask"] == {"status": "running", "taskGenerationId": "task-new"}


def _ready_concurrent_task_run(monkeypatch, tmp_path: Path) -> dict:
    monkeypatch.setattr(labor_runs, "LABOR_RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(app_module, "LABOR_RUNS_DIR", tmp_path / "runs")
    pdf_path = tmp_path / "invoice.pdf"
    workbook_path = tmp_path / "bill.xlsx"
    pdf_path.write_bytes(b"pdf")
    workbook_path.write_bytes(b"xlsx")
    return labor_runs.create_labor_run(
        {
            "supplierName": "Concurrent Supplier",
            "ownerUserId": "user-1",
            "files": {
                "pdfInvoices": [labor_runs.attach_labor_file("pending", pdf_path, "PDF发票")],
                "workbooks": [labor_runs.attach_labor_file("pending", workbook_path, "线下账单")],
            },
            "workbookSheet": "Billing",
            "excelMapping": {"name": "Employee", "hours": "Hours", "amount": "Amount"},
        }
    )


def _run_concurrent_extract_requests(run_id: str) -> tuple[list[dict], list[BaseException]]:
    results: list[dict] = []
    errors: list[BaseException] = []

    def submit() -> None:
        try:
            results.append(asyncio.run(app_module.extract_and_compare_labor_run(run_id)))
        except BaseException as exc:  # pragma: no cover - assertions surface thread failures.
            errors.append(exc)

    threads = [threading.Thread(target=submit) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)
    assert all(thread.is_alive() is False for thread in threads)
    return results, errors


def test_concurrent_same_run_requests_schedule_local_runner_once(monkeypatch, tmp_path: Path):
    run = _ready_concurrent_task_run(monkeypatch, tmp_path)
    monkeypatch.setenv("LABOR_AUDIT_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(app_module, "_uses_request_scoped_labor_runtime", lambda: False)
    monkeypatch.setattr(app_module, "_uses_personal_labor_worker", lambda: False)
    monkeypatch.setattr(app_module, "_LABOR_TASK_LIMITER", app_module.LaborTaskLimiter())
    barrier = threading.Barrier(2)
    original_metadata = app_module._labor_metadata_or_404

    def concurrent_snapshot(run_id: str) -> dict:
        metadata = original_metadata(run_id)
        barrier.wait(timeout=2)
        return metadata

    scheduled: list[tuple] = []

    class FakeLoop:
        def run_in_executor(self, *args):
            scheduled.append(args)
            return None

    monkeypatch.setattr(app_module, "_labor_metadata_or_404", concurrent_snapshot)
    monkeypatch.setattr(app_module.asyncio, "get_event_loop", lambda: FakeLoop())

    results, errors = _run_concurrent_extract_requests(run["id"])

    assert len(scheduled) == 1
    assert len(results) + len(errors) == 2


def test_concurrent_same_run_requests_enqueue_personal_worker_once(monkeypatch, tmp_path: Path):
    run = _ready_concurrent_task_run(monkeypatch, tmp_path)
    monkeypatch.setenv("LABOR_AUDIT_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(app_module, "_uses_request_scoped_labor_runtime", lambda: False)
    monkeypatch.setattr(app_module, "_uses_personal_labor_worker", lambda: True)
    barrier = threading.Barrier(2)
    original_metadata = app_module._labor_metadata_or_404

    def concurrent_snapshot(run_id: str) -> dict:
        metadata = original_metadata(run_id)
        barrier.wait(timeout=2)
        return metadata

    enqueued: list[str] = []

    def enqueue(run_id: str, **_kwargs) -> dict:
        enqueued.append(run_id)
        return {"id": "job-1", "runId": run_id, "status": "queued"}

    monkeypatch.setattr(app_module, "_labor_metadata_or_404", concurrent_snapshot)
    monkeypatch.setattr(app_module, "enqueue_labor_worker_job", enqueue)

    results, errors = _run_concurrent_extract_requests(run["id"])

    assert len(enqueued) == 1
    assert len(results) + len(errors) == 2


def test_metadata_load_and_update_share_the_same_run_lock(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(labor_runs, "LABOR_RUNS_DIR", tmp_path / "runs")
    run = labor_runs.create_labor_run({"supplierName": "Concurrent Supplier"})
    run_dir = labor_runs.get_labor_run_dir(run["id"])
    original_materialize = labor_runs.materialize_labor_metadata_for_local
    reader_materialized = threading.Event()
    release_reader = threading.Event()
    updater_finished = threading.Event()
    thread_errors: list[BaseException] = []

    def blocking_materialize(current_run_dir: Path, payload: dict) -> dict:
        materialized = original_materialize(current_run_dir, payload)
        if threading.current_thread().name == "labor-metadata-reader":
            reader_materialized.set()
            if not release_reader.wait(timeout=2):
                raise TimeoutError("reader was not released")
        return materialized

    def load_metadata() -> None:
        try:
            labor_runs.load_labor_metadata(run_dir)
        except BaseException as exc:  # pragma: no cover - surfaced below
            thread_errors.append(exc)

    def update_metadata() -> None:
        try:
            labor_runs.update_labor_metadata(run["id"], {"concurrentMarker": "preserved"})
        except BaseException as exc:  # pragma: no cover - surfaced below
            thread_errors.append(exc)
        finally:
            updater_finished.set()

    monkeypatch.setattr(labor_runs, "materialize_labor_metadata_for_local", blocking_materialize)
    reader = threading.Thread(target=load_metadata, name="labor-metadata-reader")
    updater = threading.Thread(target=update_metadata, name="labor-metadata-updater")
    reader.start()
    assert reader_materialized.wait(timeout=2)
    updater.start()
    updater_was_serialized = not updater_finished.wait(timeout=0.2)
    release_reader.set()
    reader.join(timeout=2)
    updater.join(timeout=2)

    assert reader.is_alive() is False
    assert updater.is_alive() is False
    assert thread_errors == []
    assert updater_was_serialized is True
    assert json.loads((run_dir / labor_runs.METADATA_FILE).read_text(encoding="utf-8"))["concurrentMarker"] == "preserved"


def test_vercel_request_runtime_never_starts_long_extract_without_personal_worker(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("SIGMA_LABOR_AUTH_REQUIRED", "0")
    monkeypatch.setenv("SIGMA_WORKBENCH_HOME", "/tmp/sigma-workbench")
    monkeypatch.setenv("SIGMA_LABOR_STORAGE_BACKEND", "blob")
    monkeypatch.setenv("SIGMA_OVERSEAS_LABOR_ACCESS", "uat_full")
    monkeypatch.delenv("SIGMA_LABOR_EXECUTION_MODE", raising=False)
    monkeypatch.setattr(
        app_module,
        "_labor_build_snapshot",
        lambda: {"status": "current", "buildId": "p0-vercel-no-long-task"},
    )

    response = TestClient(app).post("/api/labor/runs/not-created/extract-and-compare")

    assert response.status_code == 409
    assert response.json()["detail"]["errorCode"] == "LABOR_UAT_EXTRACT_DISABLED"


def test_vercel_supabase_runtime_never_starts_long_extract_without_personal_worker(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("SIGMA_LABOR_AUTH_REQUIRED", "0")
    monkeypatch.setenv("SIGMA_WORKBENCH_HOME", "/tmp/sigma-workbench")
    monkeypatch.setenv("SIGMA_LABOR_STORAGE_BACKEND", "supabase")
    monkeypatch.setenv("SIGMA_OVERSEAS_LABOR_ACCESS", "uat_full")
    monkeypatch.delenv("SIGMA_LABOR_EXECUTION_MODE", raising=False)
    monkeypatch.setattr(
        app_module,
        "_labor_build_snapshot",
        lambda: {"status": "current", "buildId": "p0-vercel-supabase-no-long-task"},
    )

    response = TestClient(app).post("/api/labor/runs/not-created/extract-and-compare")

    assert response.status_code == 409
    assert response.json()["detail"]["errorCode"] == "LABOR_UAT_EXTRACT_DISABLED"


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("GET", "/api/labor/material-index", None),
        ("GET", "/api/labor/material-replay-plan", None),
        ("POST", "/api/labor/material-dry-run", {"batchKey": "synthetic"}),
        ("POST", "/api/labor/material-runs", {"batchKey": "synthetic"}),
    ],
)
def test_vercel_request_runtime_blocks_local_material_tools(monkeypatch, method: str, path: str, payload: dict | None):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("SIGMA_LABOR_AUTH_REQUIRED", "0")
    monkeypatch.setenv("SIGMA_LABOR_STORAGE_BACKEND", "supabase")

    response = TestClient(app).request(method, path, json=payload)

    assert response.status_code == 409
    assert response.json()["detail"]["errorCode"] == "LABOR_LOCAL_MATERIAL_TOOL_DISABLED"


def test_committed_image_regression_fixtures_contain_no_raw_employee_evidence():
    fixture_dir = Path(__file__).resolve().parents[1] / "docs" / "labor_image_regression_fixtures"
    forbidden_keys = {"employee_name_raw", "employeeName", "evidence_text", "evidenceText"}
    allowed_payload_keys = {"audit", "pagePolicy", "rows"}
    allowed_row_keys = {"source_file", "source_page_or_row", "amount"}

    def walk(value: object) -> None:
        if isinstance(value, dict):
            assert forbidden_keys.isdisjoint(value), sorted(forbidden_keys.intersection(value))
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list):
            for nested in value:
                walk(nested)

    for fixture_path in sorted(fixture_dir.glob("*.json")):
        assert fixture_path.name.startswith("synthetic_")
        raw_text = fixture_path.read_text(encoding="utf-8")
        payload = json.loads(raw_text)
        walk(payload)
        assert "/Users/" not in raw_text
        for fixture in payload.values():
            assert set(fixture).issubset(allowed_payload_keys)
            assert fixture.get("audit") == {"synthetic": True}
            for row in fixture.get("rows", []):
                assert set(row).issubset(allowed_row_keys)


def test_readiness_does_not_ignore_warning_or_critical_reconciliation_diagnostics(tmp_path: Path):
    base = _releasable_metadata(tmp_path)

    warning = app_module._build_labor_readiness_gate(
        {
            **base,
            "reconciliationDiagnostics": {
                "level": "warning",
                "message": "核对信号有不稳定项。",
                "issues": [{"code": "warehouse_offsetting_deltas", "level": "warning"}],
            },
        }
    )
    critical = app_module._build_labor_readiness_gate(
        {
            **base,
            "reconciliationDiagnostics": {
                "level": "critical",
                "message": "核对信号存在冲突。",
                "issues": [{"code": "pdf_total_conflict", "level": "critical"}],
            },
        }
    )

    assert warning["status"] == "needs_review"
    assert warning["ready"] is False
    assert critical["status"] == "blocked"
    assert critical["ready"] is False
