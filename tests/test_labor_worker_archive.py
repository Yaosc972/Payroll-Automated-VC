import hashlib
import json
import threading
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

import bonus_platform.engine.labor.worker_archive as worker_archive
from bonus_platform.engine.labor import runs as labor_runs
from bonus_platform.engine.labor.worker_archive import (
    LaborWorkerArchiveError,
    build_worker_input_archive,
    merge_worker_result_archive,
)


def test_worker_input_archive_contains_relative_run_files(tmp_path):
    run_dir = tmp_path / "labor_1"
    run_dir.mkdir()
    (run_dir / "metadata.json").write_text('{"id":"labor_1"}', encoding="utf-8")
    (run_dir / "invoice.pdf").write_bytes(b"pdf")

    payload = build_worker_input_archive(run_dir)

    with zipfile.ZipFile(BytesIO(payload)) as archive:
        assert set(archive.namelist()) == {"metadata.json", "invoice.pdf"}


def test_worker_result_archive_cannot_overwrite_inputs(tmp_path):
    run_dir = tmp_path / "labor_1"
    run_dir.mkdir()
    (run_dir / "invoice.pdf").write_bytes(b"original")
    current = _server_metadata()
    (run_dir / "metadata.json").write_text(json.dumps(current), encoding="utf-8")
    incoming = _complete_result_metadata(current)
    payload = _zip(
        {
            "invoice.pdf": b"changed",
            "result.xlsx": b"report",
            "metadata.json": json.dumps(incoming).encode(),
        }
    )

    merged = merge_worker_result_archive(run_dir, payload)

    assert (run_dir / "invoice.pdf").read_bytes() == b"original"
    assert (run_dir / "result.xlsx").read_bytes() == b"report"
    assert merged == ["result.xlsx", "metadata.json"]


def test_worker_result_archive_rejects_path_traversal(tmp_path):
    with pytest.raises(LaborWorkerArchiveError):
        merge_worker_result_archive(tmp_path / "labor_1", _zip({"../escape.txt": b"bad"}))


def test_worker_result_archive_rejects_duplicate_normalized_paths_without_changes(tmp_path):
    run_dir = tmp_path / "labor_1"
    run_dir.mkdir()
    metadata_path = run_dir / "metadata.json"
    metadata_path.write_bytes(b'{"id":"labor_1","status":"original"}')
    before = metadata_path.read_bytes()

    with pytest.raises(LaborWorkerArchiveError):
        merge_worker_result_archive(
            run_dir,
            _zip_entries([("metadata.json", b"{}"), ("METADATA.JSON", b"{}")]),
        )

    assert metadata_path.read_bytes() == before


def test_worker_result_archive_is_unchanged_when_late_entry_is_invalid(tmp_path):
    run_dir = tmp_path / "labor_1"
    run_dir.mkdir()
    metadata_path = run_dir / "metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "id": "labor_1",
                "status": "已生成差异报告",
                "businessReviewStatus": "approved",
                "manualReviewRequired": False,
                "directPaymentAllowed": True,
                "requiresHumanReview": False,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "existing-report.xlsx").write_bytes(b"existing")
    before = {
        path.relative_to(run_dir).as_posix(): path.read_bytes()
        for path in sorted(run_dir.rglob("*"))
        if path.is_file()
    }
    incoming = json.dumps({"status": "已完成", "summary": {"passed": 3}}).encode()

    with pytest.raises(LaborWorkerArchiveError):
        merge_worker_result_archive(
            run_dir,
            _zip({"metadata.json": incoming, "../escape.txt": b"bad"}),
        )

    after = {
        path.relative_to(run_dir).as_posix(): path.read_bytes()
        for path in sorted(run_dir.rglob("*"))
        if path.is_file()
    }
    assert after == before
    assert not (tmp_path / "escape.txt").exists()


def test_worker_result_archive_is_unchanged_when_result_metadata_is_invalid(tmp_path):
    run_dir = tmp_path / "labor_1"
    run_dir.mkdir()
    metadata_path = run_dir / "metadata.json"
    metadata_path.write_bytes(b'{"id":"labor_1","status":"original"}')
    before = metadata_path.read_bytes()

    with pytest.raises(LaborWorkerArchiveError):
        merge_worker_result_archive(
            run_dir,
            _zip({"report.xlsx": b"new-report", "metadata.json": b"not-json"}),
        )

    assert metadata_path.read_bytes() == before
    assert not (run_dir / "report.xlsx").exists()


def test_worker_result_archive_rolls_back_when_commit_fails(monkeypatch, tmp_path):
    run_dir = tmp_path / "labor_1"
    run_dir.mkdir()
    current = _server_metadata()
    metadata_path = run_dir / "metadata.json"
    metadata_path.write_text(json.dumps(current), encoding="utf-8")
    (run_dir / "result.xlsx").write_bytes(b"old-report")
    before = {
        path.relative_to(run_dir).as_posix(): path.read_bytes()
        for path in sorted(run_dir.rglob("*"))
        if path.is_file()
    }
    incoming = _complete_result_metadata(current, report_bytes=b"new-report")
    real_replace = worker_archive.os.replace
    failed = False

    def fail_metadata_commit_once(source, destination):
        nonlocal failed
        if not failed and Path(source).name == "prepared-metadata.json" and Path(destination).name == "metadata.json":
            failed = True
            raise OSError("simulated metadata commit failure")
        return real_replace(source, destination)

    monkeypatch.setattr(worker_archive.os, "replace", fail_metadata_commit_once)

    with pytest.raises(LaborWorkerArchiveError) as caught:
        merge_worker_result_archive(
            run_dir,
            _zip({"metadata.json": json.dumps(incoming).encode(), "result.xlsx": b"new-report"}),
        )

    after = {
        path.relative_to(run_dir).as_posix(): path.read_bytes()
        for path in sorted(run_dir.rglob("*"))
        if path.is_file()
    }
    assert failed is True, repr(caught.value.__cause__)
    assert after == before


def test_worker_result_archive_does_not_overwrite_concurrent_mapping_update(monkeypatch, tmp_path):
    run_dir = tmp_path / "labor_1"
    run_dir.mkdir()
    current = _server_metadata()
    (run_dir / "metadata.json").write_text(json.dumps(current), encoding="utf-8")
    incoming = _complete_result_metadata(current)
    payload = _zip({"metadata.json": json.dumps(incoming).encode(), "result.xlsx": b"report"})
    monkeypatch.setattr(labor_runs, "get_labor_run_dir", lambda _run_id: run_dir)
    monkeypatch.setattr(labor_runs, "labor_persistent_storage_enabled", lambda: False)

    validation_reached = threading.Event()
    release_commit = threading.Event()
    update_started = threading.Event()
    update_finished = threading.Event()
    merge_errors = []
    update_errors = []
    original_validate = worker_archive._validate_commit_targets

    def pause_before_commit(target_run_dir, staged_files):
        original_validate(target_run_dir, staged_files)
        validation_reached.set()
        if not release_commit.wait(timeout=5):
            raise TimeoutError("test did not release Worker archive commit")

    monkeypatch.setattr(worker_archive, "_validate_commit_targets", pause_before_commit)

    def merge_result():
        try:
            merge_worker_result_archive(run_dir, payload)
        except Exception as exc:  # noqa: BLE001 - captured for the test thread.
            merge_errors.append(exc)

    def update_mapping():
        update_started.set()
        try:
            labor_runs.update_labor_metadata(
                "labor_1",
                {"excelMapping": {"name": "Employee", "hours": "Hours", "amount": "Net Amount"}},
            )
        except Exception as exc:  # noqa: BLE001 - captured for the test thread.
            update_errors.append(exc)
        finally:
            update_finished.set()

    merge_thread = threading.Thread(target=merge_result)
    merge_thread.start()
    assert validation_reached.wait(timeout=5)
    update_thread = threading.Thread(target=update_mapping)
    update_thread.start()
    assert update_started.wait(timeout=5)
    update_was_blocked = not update_finished.wait(timeout=0.2)
    release_commit.set()
    merge_thread.join(timeout=5)
    update_thread.join(timeout=5)

    assert update_was_blocked is True
    assert not merge_thread.is_alive()
    assert not update_thread.is_alive()
    assert merge_errors == []
    assert update_errors == []
    saved = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    assert saved["excelMapping"]["amount"] == "Net Amount"


def test_worker_result_metadata_only_merges_result_fields(tmp_path):
    run_dir = tmp_path / "labor_1"
    run_dir.mkdir()
    current = _server_metadata()
    (run_dir / "metadata.json").write_text(json.dumps(current), encoding="utf-8")
    incoming = {
        **_complete_result_metadata(current),
        "ownerUserId": "attacker",
        "supplierName": "Changed",
        "businessReviewStatus": "approved",
        "manualReviewRequired": False,
        "directPaymentAllowed": True,
        "requiresHumanReview": False,
    }

    merge_worker_result_archive(
        run_dir,
        _zip({"metadata.json": json.dumps(incoming).encode(), "result.xlsx": b"report"}),
    )

    saved = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    assert saved["ownerUserId"] == "user-1"
    assert saved["supplierName"] == "Original"
    assert saved["status"] == "已生成差异报告"
    assert saved["comparisonSummary"] == incoming["comparisonSummary"]
    assert saved["businessReviewStatus"] == "pending"
    assert saved["manualReviewRequired"] is True
    assert saved["directPaymentAllowed"] is False
    assert saved["requiresHumanReview"] is True


def test_worker_result_archive_without_metadata_is_rejected_without_mutating_old_result(tmp_path):
    run_dir = tmp_path / "labor_1"
    run_dir.mkdir()
    (run_dir / "metadata.json").write_text(
        json.dumps(
            {
                "id": "labor_1",
                "status": "已生成差异报告",
                "comparisonSummary": {
                    "canRelease": True,
                    "conclusionLevel": "pass",
                    "machineCheckStatus": "passed",
                },
                "machineCheckStatus": "passed",
                "resultInputFingerprint": "old-official-fingerprint",
                "batchGuard": {"status": "ok", "allowReleasableReport": True},
                "reconciliationDiagnostics": {"level": "ok", "issues": []},
                "comparisonRows": [{"employeeName": "Alice", "matchStatus": "通过"}],
                "candidateMatches": [{"pdfName": "Alice", "excelName": "Alice"}],
                "warehouseComparison": {"summary": {"totalPassed": True}},
                "costSummaries": [{"warehouseId": "1", "amount": 100}],
                "pdfExtractedRows": [{"employee_name_raw": "Alice", "amount": 100}],
                "excelRows": [{"employee_name_raw": "Alice", "amount": 100}],
                "reviewQueues": {"summary": {"total": 0}},
                "structureReconciliation": {"unresolvedFiles": []},
                "diffDownloadUrl": "/api/labor/runs/labor_1/download/old-diff.xlsx",
                "businessReportDownloadUrl": "/api/labor/runs/labor_1/download/old-business.html",
                "files": {
                    "pdfInvoices": [{"filename": "invoice.pdf", "path": "invoice.pdf"}],
                    "workbooks": [{"filename": "bill.xlsx", "path": "bill.xlsx"}],
                    "diffReport": {
                        "filename": "old-diff.xlsx",
                        "path": "old-diff.xlsx",
                        "downloadUrl": "/api/labor/runs/labor_1/download/old-diff.xlsx",
                    },
                    "businessReport": {
                        "filename": "old-business.html",
                        "path": "old-business.html",
                        "downloadUrl": "/api/labor/runs/labor_1/download/old-business.html",
                    },
                },
                "businessReviewStatus": "approved",
                "manualReviewRequired": False,
                "directPaymentAllowed": True,
                "requiresHumanReview": False,
            }
        ),
        encoding="utf-8",
    )

    before = (run_dir / "metadata.json").read_bytes()
    with pytest.raises(LaborWorkerArchiveError) as caught:
        merge_worker_result_archive(run_dir, _zip({"report-only.xlsx": b"report"}))

    assert caught.value.code == "worker_result_metadata_missing"
    assert caught.value.formal_result_rejected is True
    assert (run_dir / "metadata.json").read_bytes() == before
    assert not (run_dir / "report-only.xlsx").exists()


@pytest.mark.parametrize(
    "incoming",
    [
        {},
        {
            "comparisonSummary": {
                "canRelease": True,
                "conclusionLevel": "pass",
                "machineCheckStatus": "passed",
            },
            "machineCheckStatus": "passed",
            "resultInputFingerprint": "forged-partial-fingerprint",
            "batchGuard": {"status": "ok", "allowReleasableReport": True},
            "reconciliationDiagnostics": {"level": "ok", "issues": []},
        },
    ],
    ids=["empty", "partial-pass"],
)
def test_worker_result_archive_with_incomplete_metadata_is_rejected_without_mutation(tmp_path, incoming):
    run_dir = tmp_path / "labor_1"
    run_dir.mkdir()
    current = _server_metadata()
    (run_dir / "metadata.json").write_text(json.dumps(current), encoding="utf-8")

    before = (run_dir / "metadata.json").read_bytes()
    with pytest.raises(LaborWorkerArchiveError) as caught:
        merge_worker_result_archive(
            run_dir,
            _zip({"metadata.json": json.dumps(incoming).encode(), "report-only.xlsx": b"report"}),
        )

    assert caught.value.code == "worker_result_metadata_incomplete"
    assert (run_dir / "metadata.json").read_bytes() == before
    assert not (run_dir / "report-only.xlsx").exists()


def test_worker_result_archive_with_stale_input_fingerprint_is_rejected_without_mutation(tmp_path):
    run_dir = tmp_path / "labor_1"
    run_dir.mkdir()
    current = _server_metadata()
    (run_dir / "metadata.json").write_text(json.dumps(current), encoding="utf-8")
    incoming = _complete_result_metadata(current)
    incoming["resultInputFingerprint"] = "0" * 64

    before = (run_dir / "metadata.json").read_bytes()
    with pytest.raises(LaborWorkerArchiveError) as caught:
        merge_worker_result_archive(
            run_dir,
            _zip({"metadata.json": json.dumps(incoming).encode(), "result.xlsx": b"report"}),
        )

    assert caught.value.code == "worker_result_input_mismatch"
    assert (run_dir / "metadata.json").read_bytes() == before
    assert not (run_dir / "result.xlsx").exists()


def test_worker_result_archive_rejects_report_content_that_does_not_match_declared_hash(tmp_path):
    run_dir = tmp_path / "labor_1"
    run_dir.mkdir()
    current = _server_metadata()
    (run_dir / "metadata.json").write_text(json.dumps(current), encoding="utf-8")
    incoming = _complete_result_metadata(current, report_bytes=b"declared-report")
    before = (run_dir / "metadata.json").read_bytes()

    with pytest.raises(LaborWorkerArchiveError) as caught:
        merge_worker_result_archive(
            run_dir,
            _zip({"metadata.json": json.dumps(incoming).encode(), "result.xlsx": b"different-report"}),
        )

    assert caught.value.code == "worker_result_report_integrity_mismatch"
    assert (run_dir / "metadata.json").read_bytes() == before
    assert not (run_dir / "result.xlsx").exists()


def test_worker_result_archive_rejects_empty_formal_report(tmp_path):
    run_dir = tmp_path / "labor_1"
    run_dir.mkdir()
    current = _server_metadata()
    (run_dir / "metadata.json").write_text(json.dumps(current), encoding="utf-8")
    incoming = _complete_result_metadata(current, report_bytes=b"")
    before = (run_dir / "metadata.json").read_bytes()

    with pytest.raises(LaborWorkerArchiveError) as caught:
        merge_worker_result_archive(
            run_dir,
            _zip({"metadata.json": json.dumps(incoming).encode(), "result.xlsx": b""}),
        )

    assert caught.value.code == "worker_result_report_empty"
    assert (run_dir / "metadata.json").read_bytes() == before
    assert not (run_dir / "result.xlsx").exists()


def test_old_generation_result_cannot_commit_after_run_generation_switches(tmp_path):
    run_dir = tmp_path / "labor_1"
    run_dir.mkdir()
    current = _server_metadata()
    current["taskGenerationId"] = "generation-old"
    current["asyncTask"] = {"status": "running", "taskGenerationId": "generation-old"}
    (run_dir / "metadata.json").write_text(json.dumps(current), encoding="utf-8")
    incoming = _complete_result_metadata(current)
    payload = _zip({"metadata.json": json.dumps(incoming).encode(), "result.xlsx": b"report"})
    started = threading.Event()
    errors = []

    def merge_old_result():
        started.set()
        try:
            merge_worker_result_archive(
                run_dir,
                payload,
                expected_task_generation_id="generation-old",
            )
        except Exception as exc:  # noqa: BLE001 - asserted below.
            errors.append(exc)

    with labor_runs.labor_run_metadata_lock("labor_1"):
        thread = threading.Thread(target=merge_old_result)
        thread.start()
        assert started.wait(timeout=5)
        current["taskGenerationId"] = "generation-new"
        current["asyncTask"] = {"status": "queued", "taskGenerationId": "generation-new"}
        (run_dir / "metadata.json").write_text(json.dumps(current), encoding="utf-8")
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], LaborWorkerArchiveError)
    assert errors[0].code == "worker_result_generation_mismatch"
    assert not (run_dir / "result.xlsx").exists()
    saved = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    assert saved["taskGenerationId"] == "generation-new"


def test_worker_result_metadata_preserves_formal_reconciliation_fields(tmp_path):
    run_dir = tmp_path / "labor_1"
    run_dir.mkdir()
    current = _server_metadata()
    (run_dir / "metadata.json").write_text(json.dumps(current), encoding="utf-8")
    incoming = _complete_result_metadata(current)

    merge_worker_result_archive(
        run_dir,
        _zip({"metadata.json": json.dumps(incoming).encode(), "result.xlsx": b"report"}),
    )

    saved = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    for key, value in incoming.items():
        if key == "files":
            continue
        assert saved[key] == value
    assert saved["files"]["pdfInvoices"][0]["filename"] == "server-invoice.pdf"
    assert saved["files"]["workbooks"][0]["filename"] == "server-bill.xlsx"
    assert saved["files"]["workbook"]["filename"] == "server-bill.xlsx"
    assert saved["files"]["diffReport"]["filename"] == "result.xlsx"


def test_worker_result_paths_are_materialized_for_server_run_directory(tmp_path):
    run_dir = tmp_path / "server" / "labor_1"
    run_dir.mkdir(parents=True)
    current = _server_metadata()
    (run_dir / "metadata.json").write_text(json.dumps(current), encoding="utf-8")
    incoming = _complete_result_metadata(current)
    incoming["files"]["diffReport"] = {
        "filename": "report.xlsx",
        "path": "/worker/home/labor_1/report.xlsx",
        "downloadUrl": "/api/labor/runs/labor_1/download/report.xlsx",
        "sizeBytes": len(b"report"),
        "sha256": hashlib.sha256(b"report").hexdigest(),
    }
    incoming["diffDownloadUrl"] = "/api/labor/runs/labor_1/download/report.xlsx"

    merge_worker_result_archive(
        run_dir,
        _zip({"metadata.json": json.dumps(incoming).encode(), "report.xlsx": b"report"}),
    )

    saved = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    assert saved["files"]["diffReport"]["path"] == str(run_dir / "report.xlsx")


def _zip(files: dict[str, bytes]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def _zip_entries(files: list[tuple[str, bytes]]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files:
            archive.writestr(name, content)
    return buffer.getvalue()


def _server_metadata() -> dict:
    metadata = {
        "id": "labor_1",
        "ownerUserId": "user-1",
        "supplierName": "Original",
        "periodStart": "2026-07-01",
        "periodEnd": "2026-07-07",
        "currency": "EUR",
        "workbookSheet": "Billing",
        "excelMapping": {"name": "Employee", "hours": "Hours", "amount": "Amount"},
        "manualNameMapping": {},
        "files": {
            "pdfInvoices": [
                {"filename": "server-invoice.pdf", "originalFilename": "invoice.pdf", "path": "server-invoice.pdf"}
            ],
            "workbooks": [
                {"filename": "server-bill.xlsx", "originalFilename": "bill.xlsx", "path": "server-bill.xlsx"}
            ],
            "workbook": {"filename": "server-bill.xlsx", "originalFilename": "bill.xlsx", "path": "server-bill.xlsx"},
        },
        "comparisonSummary": {"canRelease": True, "conclusionLevel": "pass", "machineCheckStatus": "passed"},
        "machineCheckStatus": "passed",
        "batchGuard": {"status": "ok", "allowReleasableReport": True},
        "reconciliationDiagnostics": {"level": "ok", "issues": []},
        "businessReviewStatus": "approved",
        "manualReviewRequired": False,
        "directPaymentAllowed": True,
        "requiresHumanReview": False,
    }
    metadata["resultInputFingerprint"] = _result_input_fingerprint(metadata)
    return metadata


def _complete_result_metadata(current: dict, *, report_bytes: bytes = b"report") -> dict:
    download_url = "/api/labor/runs/labor_1/download/result.xlsx"
    return {
        "status": "已生成差异报告",
        "comparisonSummary": {
            "exceptionCount": 0,
            "conclusionLevel": "pass",
            "canRelease": True,
            "machineCheckStatus": "passed",
        },
        "machineCheckStatus": "passed",
        "resultInputFingerprint": _result_input_fingerprint(current),
        "batchGuard": {"status": "ok", "allowReleasableReport": True},
        "reconciliationDiagnostics": {"level": "ok", "issues": []},
        "extractionQuality": {"level": "ok", "issues": []},
        "comparisonRows": [{"employeeName": "Alice", "matchStatus": "通过"}],
        "candidateMatches": [{"pdfName": "Alice", "excelName": "Alice"}],
        "warehouseComparison": {"summary": {"pdfAmountTotal": 100, "excelAmountTotal": 100}},
        "costSummaries": [{"warehouseId": "1", "amount": 100}],
        "pdfExtractedRows": [{"employee_name_raw": "Alice", "amount": 100}],
        "excelRows": [{"employee_name_raw": "Alice", "amount": 100}],
        "reviewQueues": {"summary": {"total": 0}},
        "structureReconciliation": {"unresolvedFiles": []},
        "invoiceEvidenceAudit": [],
        "diffDownloadUrl": download_url,
        "files": {
            "pdfInvoices": [{"filename": "attacker-invoice.pdf", "path": "/worker/attacker-invoice.pdf"}],
            "workbooks": [{"filename": "attacker-bill.xlsx", "path": "/worker/attacker-bill.xlsx"}],
            "workbook": {"filename": "attacker-bill.xlsx", "path": "/worker/attacker-bill.xlsx"},
            "diffReport": {
                "filename": "result.xlsx",
                "path": "/worker/home/labor_1/result.xlsx",
                "downloadUrl": download_url,
                "sizeBytes": len(report_bytes),
                "sha256": hashlib.sha256(report_bytes).hexdigest(),
            },
        },
    }


def _result_input_fingerprint(metadata: dict) -> str:
    files = metadata.get("files") if isinstance(metadata.get("files"), dict) else {}

    def stable_file_records(key: str) -> list[dict]:
        records = files.get(key) if isinstance(files.get(key), list) else []
        return [
            {
                str(field): value
                for field, value in record.items()
                if field not in {"path", "downloadUrl", "url"}
            }
            for record in records
            if isinstance(record, dict)
        ]

    active_governance = {}
    for governance_key, active_key in (
        ("ruleGovernance", "activeRules"),
        ("nameMappingGovernance", "activeMappings"),
        ("allocationGovernance", "activeAllocations"),
        ("profileGovernance", "activeProfiles"),
        ("correctionGovernance", "activeCorrections"),
        ("reocrReplayGovernance", "activeCandidates"),
    ):
        governance = metadata.get(governance_key) if isinstance(metadata.get(governance_key), dict) else {}
        active_governance[governance_key] = governance.get(active_key) if isinstance(governance.get(active_key), list) else []

    payload = {
        "supplierName": str(metadata.get("supplierName") or metadata.get("supplier") or ""),
        "periodStart": str(metadata.get("periodStart") or ""),
        "periodEnd": str(metadata.get("periodEnd") or ""),
        "currency": str(metadata.get("currency") or ""),
        "reconciliationScope": str(metadata.get("reconciliationScope") or "employee_detail_required"),
        "pdfInvoices": stable_file_records("pdfInvoices"),
        "workbooks": stable_file_records("workbooks"),
        "workbookSheet": str(metadata.get("workbookSheet") or ""),
        "excelMapping": metadata.get("excelMapping") if isinstance(metadata.get("excelMapping"), dict) else {},
        "workbookMappings": metadata.get("workbookMappings") if isinstance(metadata.get("workbookMappings"), list) else [],
        "manualNameMapping": metadata.get("manualNameMapping") if isinstance(metadata.get("manualNameMapping"), dict) else {},
        "activeGovernance": active_governance,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
