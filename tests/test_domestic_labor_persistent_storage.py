from __future__ import annotations

import json
import shutil

from bonus_platform.engine.domestic_labor import persistent_storage, runs


def test_domestic_labor_storage_reuses_existing_supabase_configuration(monkeypatch):
    monkeypatch.delenv("SIGMA_DOMESTIC_LABOR_STORAGE_BACKEND", raising=False)
    monkeypatch.setenv("SIGMA_LABOR_STORAGE_BACKEND", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role")
    monkeypatch.setenv("SUPABASE_STORAGE_BUCKET", "sigma-runs")

    assert persistent_storage.domestic_labor_persistent_storage_enabled() is True
    assert persistent_storage.domestic_labor_supabase_bucket() == "sigma-runs"


def test_domestic_labor_creates_scoped_signed_upload_url(monkeypatch):
    monkeypatch.setenv("SIGMA_DOMESTIC_LABOR_STORAGE_ENV", "production")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role")
    monkeypatch.setenv("SUPABASE_STORAGE_BUCKET", "sigma-runs")
    requests = []

    def fake_request(method, url, *, headers, content=None):
        requests.append((method, url, headers, content))
        return json.dumps({"url": "/object/upload/sign/sigma-runs/token"}).encode()

    monkeypatch.setattr(persistent_storage, "_request", fake_request)

    upload = persistent_storage.create_domestic_labor_signed_upload(
        "payroll_123",
        "upload_abc.xlsx",
    )

    assert upload["signedUrl"] == "https://example.supabase.co/storage/v1/object/upload/sign/sigma-runs/token"
    assert upload["relativePath"] == "upload_abc.xlsx"
    assert upload["objectPath"] == "domestic-labor-runs/production/payroll_123/upload_abc.xlsx"
    assert requests[0][0] == "POST"
    assert "service-role" not in upload["signedUrl"]


def test_payroll_metadata_restores_after_local_instance_is_cleared(monkeypatch, tmp_path):
    remote_metadata = {}
    remote_status = {}

    monkeypatch.setattr(runs, "DOMESTIC_LABOR_RUNS_DIR", tmp_path)
    monkeypatch.setattr(runs, "domestic_labor_persistent_storage_enabled", lambda: True)
    monkeypatch.setattr(
        runs,
        "save_domestic_labor_metadata_to_persistent",
        lambda run_id, payload, status: (
            remote_metadata.update({run_id: dict(payload)}),
            remote_status.update({run_id: dict(status)}),
        ),
    )
    monkeypatch.setattr(
        runs,
        "load_domestic_labor_metadata_from_persistent",
        lambda run_id: remote_metadata.get(run_id),
    )
    monkeypatch.setattr(
        runs,
        "load_domestic_labor_status_from_persistent",
        lambda run_id: remote_status.get(run_id),
    )

    created = runs.create_payroll_run({"attendanceMonth": "202607", "engines": ["canbu"]})
    run_id = created["id"]
    completed = runs.update_payroll_metadata(
        run_id,
        {"status": "已完成", "results": [{"employee_id": "OWHN001"}]},
    )
    shutil.rmtree(runs.get_payroll_run_dir(run_id))

    restored = runs.load_payroll_metadata(runs.get_payroll_run_dir(run_id))
    compact = runs.load_payroll_status(runs.get_payroll_run_dir(run_id))

    assert restored == completed
    assert restored["results"] == [{"employee_id": "OWHN001"}]
    assert compact["status"] == "已完成"
    assert "results" not in compact


def test_payroll_file_materializes_from_persistent_storage(monkeypatch, tmp_path):
    monkeypatch.setattr(runs, "DOMESTIC_LABOR_RUNS_DIR", tmp_path)
    monkeypatch.setattr(runs, "domestic_labor_persistent_storage_enabled", lambda: True)
    monkeypatch.setattr(
        runs,
        "load_domestic_labor_file_from_persistent",
        lambda run_id, run_dir, relative_path: _write_remote_file(run_dir, relative_path),
    )

    restored = runs.materialize_payroll_file("payroll_123", "result.xlsx")

    assert restored == tmp_path / "payroll_123" / "result.xlsx"
    assert restored.read_bytes() == b"persisted"


def _write_remote_file(run_dir, relative_path):
    target = run_dir / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"persisted")
    return target
