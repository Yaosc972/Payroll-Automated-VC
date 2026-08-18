from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
import threading
import time

from fastapi.testclient import TestClient
from openpyxl import Workbook
import pytest

import bonus_platform.app as app_module
from bonus_platform.engine.fbu_performance import runs as fbu_runs
from bonus_platform.engine.fbu_performance import persistent_storage as fbu_storage


pytestmark = pytest.mark.usefixtures("bypass_fbu_access_gate")


def test_multiple_run_files_are_uploaded_in_parallel(monkeypatch, tmp_path):
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    filenames = ["previous_salary.xlsx", "salary.xlsx", "adjustments.xlsx"]
    for filename in filenames:
        (run_dir / filename).write_bytes(filename.encode())

    barrier = threading.Barrier(len(filenames))
    thread_ids: set[int] = set()

    def capture_upload(object_path, content, *, content_type):
        thread_ids.add(threading.get_ident())
        barrier.wait(timeout=2)

    monkeypatch.setattr(fbu_storage, "_upload_bytes", capture_upload)
    fbu_storage.save_fbu_files_to_persistent("run-1", run_dir, filenames)

    assert len(thread_ids) == len(filenames)


@pytest.fixture(autouse=True)
def reset_fbu_persistent_json_cache():
    fbu_storage._clear_fbu_json_cache()
    yield
    fbu_storage._clear_fbu_json_cache()


def test_activity_list_summary_omits_large_sections_and_storage_metadata():
    payload = {
        "run_id": "run-1",
        "created_at": "2026-07-31T10:00:00",
        "calc_month": "2026-06",
        "status": "step2",
        "current_step": 2,
        "total_employees": 300,
        "total_bonus": 0,
        "attendance_data": {"employees": [{"employee_id": f"E{index}"} for index in range(300)]},
        "salary_verification_data": {
            "employees": [{"employee_id": f"E{index}"} for index in range(300)],
            "summary": {"blocking_count": 3, "resolved_count": 297},
        },
    }

    summary = fbu_runs.build_fbu_run_list_summary(
        fbu_storage.build_fbu_run_manifest(payload)
    )

    assert set(summary) == {
        "run_id",
        "created_at",
        "calc_month",
        "status",
        "current_step",
        "total_employees",
        "total_bonus",
        "sections",
    }
    assert "attendance_data" not in summary
    assert summary["sections"] == {
        "salary_verification_data": {
            "present": True,
            "summary": {"blocking_count": 3},
        }
    }
    assert len(json.dumps(summary, ensure_ascii=False).encode("utf-8")) < 1_000


def test_download_treats_supabase_wrapped_not_found_as_missing(monkeypatch):
    monkeypatch.setattr(fbu_storage, "_storage_url", lambda path: f"https://storage.test/{path}")
    monkeypatch.setattr(fbu_storage, "_headers", lambda extra=None: {})

    def raise_wrapped_not_found(*args, **kwargs):
        raise fbu_storage.FBUStorageStatusError(
            400,
            '{"statusCode":"404","error":"not_found","message":"Object not found"}',
        )

    monkeypatch.setattr(fbu_storage, "_request", raise_wrapped_not_found)

    assert fbu_storage._download_bytes("fbu-performance-runs/production/run-1/roster.xlsx") is None


def test_download_does_not_hide_real_supabase_bad_request(monkeypatch):
    monkeypatch.setattr(fbu_storage, "_storage_url", lambda path: f"https://storage.test/{path}")
    monkeypatch.setattr(fbu_storage, "_headers", lambda extra=None: {})

    def raise_bad_request(*args, **kwargs):
        raise fbu_storage.FBUStorageStatusError(
            400,
            '{"statusCode":"400","error":"InvalidKey","message":"Invalid key"}',
        )

    monkeypatch.setattr(fbu_storage, "_request", raise_bad_request)

    with pytest.raises(fbu_storage.FBUStorageStatusError):
        fbu_storage._download_bytes("bad-key")


def test_create_fbu_signed_upload_uses_run_scoped_object_path(monkeypatch):
    monkeypatch.setenv("SIGMA_FBU_STORAGE_ENV", "production")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role")
    monkeypatch.setenv("SIGMA_FBU_SUPABASE_BUCKET", "sigma-runs")
    captured = {}

    def fake_request(method, url, *, headers, content=None):
        captured.update(method=method, url=url, headers=headers, content=content)
        return b'{"url":"/object/upload/sign/sigma-runs/token"}'

    monkeypatch.setattr(fbu_storage, "_request", fake_request)

    upload = fbu_storage.create_fbu_signed_upload(
        "run_123",
        "direct_uploads/plan_attendance.xlsx",
    )

    assert captured["method"] == "POST"
    assert captured["url"].endswith(
        "/storage/v1/object/upload/sign/sigma-runs/"
        "fbu-performance-runs/production/run_123/direct_uploads/plan_attendance.xlsx"
    )
    assert captured["headers"]["x-upsert"] == "true"
    assert upload == {
        "signedUrl": "https://example.supabase.co/storage/v1/object/upload/sign/sigma-runs/token",
        "objectPath": "fbu-performance-runs/production/run_123/direct_uploads/plan_attendance.xlsx",
        "relativePath": "direct_uploads/plan_attendance.xlsx",
    }


def test_copy_fbu_file_in_persistent_uses_server_side_copy(monkeypatch):
    monkeypatch.setenv("SIGMA_FBU_STORAGE_ENV", "production")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role")
    monkeypatch.setenv("SIGMA_FBU_SUPABASE_BUCKET", "sigma-runs")
    captured = {}

    def fake_request(method, url, *, headers, content=None):
        captured.update(method=method, url=url, headers=headers, content=content)
        return b"{}"

    monkeypatch.setattr(fbu_storage, "_request", fake_request)

    fbu_storage.copy_fbu_file_in_persistent(
        "run_123",
        "direct_uploads/job_attendance.xlsx",
        "attendance.xlsx",
    )

    assert captured["method"] == "POST"
    assert captured["url"] == "https://example.supabase.co/storage/v1/object/copy"
    assert captured["headers"]["content-type"] == "application/json"
    assert json.loads(captured["content"]) == {
        "bucketId": "sigma-runs",
        "sourceKey": "fbu-performance-runs/production/run_123/direct_uploads/job_attendance.xlsx",
        "destinationKey": "fbu-performance-runs/production/run_123/attendance.xlsx",
    }


def test_v2_snapshot_splits_large_sections_and_lists_from_single_index(monkeypatch):
    monkeypatch.setenv("SIGMA_FBU_STORAGE_ENV", "production")
    objects: dict[str, bytes] = {}
    reads: list[str] = []

    def upload(object_path: str, content: bytes, content_type: str) -> None:
        objects[object_path] = content

    def download(object_path: str) -> bytes | None:
        reads.append(object_path)
        return objects.get(object_path)

    monkeypatch.setattr(fbu_storage, "_upload_bytes", upload)
    monkeypatch.setattr(fbu_storage, "_download_bytes", download)
    monkeypatch.setattr(fbu_storage, "_list_objects", lambda prefix: [])

    payload = {
        "run_id": "run_123",
        "created_at": "2026-07-30T10:00:00",
        "calc_month": "2026-06",
        "status": "completed",
        "current_step": 5,
        "attendance_file": "attendance.xlsx",
        "attendance_data": {
            "summary": {"total_employees": 303},
            "employees": [{"employee_id": "zt1", "daily_rows": [{"date": "2026-06-01"}]}],
        },
        "salary_data": {"employees": [{"employee_id": "zt1", "hourly_rate": 20}]},
        "results": [{"employee_id": "zt1", "performance_bonus": 100}],
        "roster_data": {
            "employees": [{"employee_id": f"zt{index:06d}"} for index in range(500)],
        },
        "total_employees": 1,
        "total_bonus": 100,
    }

    manifest = fbu_storage.save_fbu_run_snapshot_to_persistent("run_123", payload)

    prefix = "fbu-performance-runs/production"
    assert manifest["schemaVersion"] == 2
    assert json.loads(objects[f"{prefix}/run_123/summary.json"])["run"]["run_id"] == "run_123"
    assert json.loads(objects[f"{prefix}/run_123/sections/attendance_data.json"]) == payload["attendance_data"]
    assert json.loads(objects[f"{prefix}/run_123/sections/results.json"]) == payload["results"]
    assert "attendance_data" not in manifest["run"]
    assert "results" not in manifest["run"]
    assert "roster_data" not in manifest["run"]

    fbu_storage._clear_fbu_json_cache()
    reads.clear()
    summaries = fbu_storage.list_fbu_run_summaries_from_persistent()
    assert summaries[0]["run"]["run_id"] == "run_123"
    assert reads == [f"{prefix}/_runs-index.json"]

    reads.clear()
    restored = fbu_storage.load_fbu_run_snapshot_from_persistent(
        "run_123",
        sections={"attendance_data"},
    )
    assert restored["attendance_data"] == payload["attendance_data"]
    assert "salary_data" not in restored
    assert "results" not in restored
    assert reads == [
        f"{prefix}/run_123/summary.json",
        f"{prefix}/run_123/sections/attendance_data.json",
    ]


def test_snapshot_refresh_bypasses_cached_manifest(monkeypatch):
    monkeypatch.setenv("SIGMA_FBU_STORAGE_ENV", "production")
    prefix = "fbu-performance-runs/production/run_123"
    objects = {
        f"{prefix}/summary.json": json.dumps({
            "schemaVersion": 2,
            "run": {"run_id": "run_123", "current_salary_file": ""},
            "sections": {},
        }).encode("utf-8"),
    }
    monkeypatch.setattr(
        fbu_storage,
        "_download_bytes",
        lambda object_path: objects.get(object_path),
    )

    cached = fbu_storage.load_fbu_run_snapshot_from_persistent(
        "run_123",
        sections=set(),
    )
    assert cached["current_salary_file"] == ""

    objects[f"{prefix}/summary.json"] = json.dumps({
        "schemaVersion": 2,
        "run": {"run_id": "run_123", "current_salary_file": "current.xlsx"},
        "sections": {},
    }).encode("utf-8")

    still_cached = fbu_storage.load_fbu_run_snapshot_from_persistent(
        "run_123",
        sections=set(),
    )
    refreshed = fbu_storage.load_fbu_run_snapshot_from_persistent(
        "run_123",
        sections=set(),
        refresh=True,
    )

    assert still_cached["current_salary_file"] == ""
    assert refreshed["current_salary_file"] == "current.xlsx"


def test_salary_section_recovers_when_manifest_presence_is_stale(monkeypatch):
    monkeypatch.setenv("SIGMA_FBU_STORAGE_ENV", "production")
    prefix = "fbu-performance-runs/production/run_123"
    salary_data = {"employees": [{"employee_id": "zt1", "hourly_rate": 20}]}
    objects = {
        f"{prefix}/summary.json": json.dumps({
            "schemaVersion": 2,
            "run": {"run_id": "run_123"},
            "sections": {
                "current_salary_data": {
                    "path": "sections/current_salary_data.json",
                    "present": False,
                },
            },
        }).encode("utf-8"),
        f"{prefix}/sections/current_salary_data.json": json.dumps(salary_data).encode("utf-8"),
    }
    monkeypatch.setattr(
        fbu_storage,
        "_download_bytes",
        lambda object_path: objects.get(object_path),
    )

    restored = fbu_storage.load_fbu_run_snapshot_from_persistent(
        "run_123",
        sections={"current_salary_data"},
    )

    assert restored["current_salary_data"] == salary_data


def test_v2_manifest_removes_legacy_embedded_roster_from_previous_summary():
    previous = {
        "run": {
            "run_id": "run_legacy",
            "calc_month": "2026-06",
            "roster_data": {
                "employees": [{"employee_id": f"zt{index:06d}"} for index in range(500)],
            },
        },
        "sections": {},
    }

    manifest = fbu_storage.build_fbu_run_manifest(
        {
            "run_id": "run_legacy",
            "calc_month": "2026-06",
            "status": "step1",
            "roster_data": previous["run"]["roster_data"],
        },
        previous=previous,
        changed_fields={"status"},
    )

    assert "roster_data" not in manifest["run"]


def test_v2_json_reads_reuse_short_lived_process_cache(monkeypatch):
    monkeypatch.setenv("SIGMA_FBU_STORAGE_ENV", "production")
    prefix = "fbu-performance-runs/production"
    attendance_data = {
        "summary": {"total_employees": 1},
        "employees": [{"employee_id": "zt1"}],
    }
    manifest = fbu_storage.build_fbu_run_manifest({
        "run_id": "run_123",
        "created_at": "2026-07-30T10:00:00",
        "calc_month": "2026-06",
        "status": "step1",
        "attendance_data": attendance_data,
    })
    objects = {
        f"{prefix}/_runs-index.json": json.dumps({
            "schemaVersion": 2,
            "runs": [manifest],
        }).encode("utf-8"),
        f"{prefix}/run_123/summary.json": json.dumps(manifest).encode("utf-8"),
        f"{prefix}/run_123/sections/attendance_data.json": json.dumps(
            attendance_data
        ).encode("utf-8"),
    }
    reads: list[str] = []

    def download(object_path: str) -> bytes | None:
        reads.append(object_path)
        return objects.get(object_path)

    monkeypatch.setattr(fbu_storage, "_download_bytes", download)
    fbu_storage._clear_fbu_json_cache()

    fbu_storage.list_fbu_run_summaries_from_persistent()
    fbu_storage.list_fbu_run_summaries_from_persistent()
    fbu_storage.load_fbu_run_snapshot_from_persistent(
        "run_123",
        sections={"attendance_data"},
    )
    fbu_storage.load_fbu_run_snapshot_from_persistent(
        "run_123",
        sections={"attendance_data"},
    )

    assert reads == [
        f"{prefix}/_runs-index.json",
        f"{prefix}/run_123/summary.json",
        f"{prefix}/run_123/sections/attendance_data.json",
    ]


def test_v2_snapshot_recovers_attendance_section_hidden_by_stale_manifest(monkeypatch):
    monkeypatch.setenv("SIGMA_FBU_STORAGE_ENV", "production")
    prefix = "fbu-performance-runs/production"
    attendance_data = {
        "summary": {"total_employees": 1},
        "employees": [{"employee_id": "zt1", "total_base_hours": 80}],
    }
    stale_manifest = fbu_storage.build_fbu_run_manifest({
        "run_id": "run_123",
        "created_at": "2026-07-31T10:00:00",
        "calc_month": "2026-06",
        "status": "step1",
        "attendance_file": "attendance.xlsx",
    })
    objects = {
        f"{prefix}/run_123/summary.json": json.dumps(stale_manifest).encode("utf-8"),
        f"{prefix}/run_123/sections/attendance_data.json": json.dumps(
            attendance_data
        ).encode("utf-8"),
    }
    reads: list[str] = []

    def download(object_path: str) -> bytes | None:
        reads.append(object_path)
        return objects.get(object_path)

    monkeypatch.setattr(fbu_storage, "_download_bytes", download)

    restored = fbu_storage.load_fbu_run_snapshot_from_persistent(
        "run_123",
        sections={"attendance_data"},
    )

    assert restored["attendance_data"] == attendance_data
    assert reads == [
        f"{prefix}/run_123/summary.json",
        f"{prefix}/run_123/sections/attendance_data.json",
    ]


def test_v2_snapshot_recovers_base_override_hidden_by_concurrent_manifest(monkeypatch):
    monkeypatch.setenv("SIGMA_FBU_STORAGE_ENV", "production")
    prefix = "fbu-performance-runs/production"
    base_override_data = {
        "summary": {"work_hour_rule_count": 4},
        "employees": [{"employee_id": "zt12979", "rule_type": "96工时制"}],
    }
    stale_manifest = fbu_storage.build_fbu_run_manifest({
        "run_id": "run_123",
        "created_at": "2026-07-31T10:00:00",
        "calc_month": "2026-06",
        "status": "step1",
    })
    objects = {
        f"{prefix}/run_123/summary.json": json.dumps(stale_manifest).encode("utf-8"),
        f"{prefix}/run_123/sections/base_override_data.json": json.dumps(
            base_override_data
        ).encode("utf-8"),
    }

    monkeypatch.setattr(
        fbu_storage,
        "_download_bytes",
        lambda object_path: objects.get(object_path),
    )

    restored = fbu_storage.load_fbu_run_snapshot_from_persistent(
        "run_123",
        sections={"base_override_data"},
    )

    assert restored["base_override_data"] == base_override_data


def test_incremental_snapshot_merges_manifest_changed_during_section_upload(monkeypatch):
    monkeypatch.setenv("SIGMA_FBU_STORAGE_ENV", "production")
    monkeypatch.setenv("SIGMA_FBU_JSON_CACHE_TTL_SECONDS", "2")
    prefix = "fbu-performance-runs/production"
    initial = fbu_storage.build_fbu_run_manifest({
        "run_id": "run_123",
        "created_at": "2026-07-31T10:00:00",
        "calc_month": "2026-06",
        "status": "step1",
    })
    base_override_data = {
        "summary": {"work_hour_rule_count": 4},
        "employees": [{"employee_id": "zt12979", "rule_type": "96工时制"}],
    }
    confirmed = fbu_storage.build_fbu_run_manifest(
        {
            "run_id": "run_123",
            "base_override_file": "页面维护",
            "base_override_data": base_override_data,
        },
        previous=initial,
        changed_fields={"base_override_file", "base_override_data"},
    )
    objects: dict[str, bytes] = {
        f"{prefix}/run_123/summary.json": json.dumps(initial).encode("utf-8"),
    }

    def upload(object_path: str, content: bytes, content_type: str) -> None:
        objects[object_path] = content
        if object_path.endswith("/sections/supplemental_leave_data.json"):
            objects[f"{prefix}/run_123/sections/base_override_data.json"] = json.dumps(
                base_override_data
            ).encode("utf-8")
            objects[f"{prefix}/run_123/summary.json"] = json.dumps(confirmed).encode(
                "utf-8"
            )

    monkeypatch.setattr(fbu_storage, "_upload_bytes", upload)
    monkeypatch.setattr(
        fbu_storage,
        "_download_bytes",
        lambda object_path: objects.get(object_path),
    )
    monkeypatch.setattr(fbu_storage, "_upsert_fbu_run_index", lambda manifest: None)

    manifest = fbu_storage.save_fbu_run_snapshot_to_persistent(
        "run_123",
        {
            "run_id": "run_123",
            "created_at": "2026-07-31T10:00:00",
            "calc_month": "2026-06",
            "status": "step1",
            "base_override_file": "",
            "supplemental_leave_file": "leave.xlsx",
            "supplemental_leave_data": {"rows": [{"employee_id": "zt1"}]},
        },
        changed_fields={"supplemental_leave_file", "supplemental_leave_data"},
    )

    assert manifest["run"]["base_override_file"] == "页面维护"
    assert manifest["sections"]["base_override_data"]["present"] is True


def test_v2_json_cache_refreshes_remote_data_after_ttl(monkeypatch):
    monkeypatch.setenv("SIGMA_FBU_JSON_CACHE_TTL_SECONDS", "2")
    object_path = "fbu-performance-runs/production/_runs-index.json"
    now = [100.0]
    objects = {
        object_path: json.dumps({"version": 1}).encode("utf-8"),
    }
    reads: list[str] = []

    def download(path: str) -> bytes | None:
        reads.append(path)
        return objects.get(path)

    monkeypatch.setattr(fbu_storage.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(fbu_storage, "_download_bytes", download)
    fbu_storage._clear_fbu_json_cache()

    assert fbu_storage._download_json(object_path) == {"version": 1}
    objects[object_path] = json.dumps({"version": 2}).encode("utf-8")
    assert fbu_storage._download_json(object_path) == {"version": 1}

    now[0] += 2.01

    assert fbu_storage._download_json(object_path) == {"version": 2}
    assert reads == [object_path, object_path]


def test_load_run_snapshot_refresh_bypasses_cached_manifest_and_sections(monkeypatch):
    monkeypatch.setenv("SIGMA_FBU_STORAGE_ENV", "production")
    monkeypatch.setenv("SIGMA_FBU_JSON_CACHE_TTL_SECONDS", "30")
    prefix = "fbu-performance-runs/production/run_123"
    initial_section = {
        "employees": [{"employee_id": "E001", "verification_status": "blocking"}],
        "summary": {"blocking_count": 1},
    }
    resolved_section = {
        "employees": [{"employee_id": "E001", "verification_status": "resolved"}],
        "summary": {"blocking_count": 0},
    }
    initial_manifest = fbu_storage.build_fbu_run_manifest({
        "run_id": "run_123",
        "salary_verification_data": initial_section,
    })
    resolved_manifest = fbu_storage.build_fbu_run_manifest({
        "run_id": "run_123",
        "salary_verification_data": resolved_section,
    })
    objects = {
        f"{prefix}/summary.json": json.dumps(initial_manifest).encode("utf-8"),
        f"{prefix}/sections/salary_verification_data.json": json.dumps(initial_section).encode("utf-8"),
    }
    monkeypatch.setattr(
        fbu_storage,
        "_download_bytes",
        lambda object_path: objects.get(object_path),
    )

    cached = fbu_storage.load_fbu_run_snapshot_from_persistent(
        "run_123",
        sections={"salary_verification_data"},
    )
    assert cached["salary_verification_data"]["summary"]["blocking_count"] == 1

    objects[f"{prefix}/summary.json"] = json.dumps(resolved_manifest).encode("utf-8")
    objects[f"{prefix}/sections/salary_verification_data.json"] = json.dumps(
        resolved_section
    ).encode("utf-8")

    refreshed = fbu_storage.load_fbu_run_snapshot_from_persistent(
        "run_123",
        sections={"salary_verification_data"},
        refresh=True,
    )

    assert refreshed["salary_verification_data"]["summary"]["blocking_count"] == 0


def test_v2_incremental_snapshot_only_rewrites_changed_sections(monkeypatch):
    monkeypatch.setenv("SIGMA_FBU_STORAGE_ENV", "production")
    objects: dict[str, bytes] = {}
    uploads: list[str] = []

    def upload(object_path: str, content: bytes, content_type: str) -> None:
        uploads.append(object_path)
        objects[object_path] = content

    monkeypatch.setattr(fbu_storage, "_upload_bytes", upload)
    monkeypatch.setattr(fbu_storage, "_download_bytes", lambda object_path: objects.get(object_path))
    monkeypatch.setattr(fbu_storage, "_list_objects", lambda prefix: [])

    payload = {
        "run_id": "run_123",
        "created_at": "2026-07-30T10:00:00",
        "calc_month": "2026-06",
        "status": "completed",
        "current_step": 5,
        "attendance_data": {"employees": [{"employee_id": "zt1"}]},
        "period_adjustment_data": {"rows": []},
        "results": [{"employee_id": "zt1", "performance_bonus": 100}],
        "total_employees": 1,
        "total_bonus": 100,
    }
    fbu_storage.save_fbu_run_snapshot_to_persistent("run_123", payload)

    uploads.clear()
    payload["period_adjustment_data"] = {
        "rows": [{"employee_id": "zt1", "amount": 50}],
        "summary": {"total_amount": 50},
    }
    payload["results"] = []
    payload["status"] = "step2"
    payload["total_employees"] = 0
    payload["total_bonus"] = 0
    fbu_storage.save_fbu_run_snapshot_to_persistent(
        "run_123",
        payload,
        changed_fields={"period_adjustment_data", "results", "status", "total_employees", "total_bonus"},
    )

    suffixes = {path.split("/run_123/", 1)[-1] for path in uploads if "/run_123/" in path}
    assert suffixes == {
        "summary.json",
        "sections/period_adjustment_data.json",
        "sections/results.json",
    }
    assert not any(path.endswith("sections/attendance_data.json") for path in uploads)


def test_v2_incremental_snapshot_parallelizes_independent_remote_writes(monkeypatch):
    monkeypatch.setenv("SIGMA_FBU_STORAGE_ENV", "production")
    prefix = "fbu-performance-runs/production"
    payload = {
        "run_id": "run_123",
        "created_at": "2026-07-30T10:00:00",
        "calc_month": "2026-06",
        "status": "completed",
        "period_adjustment_data": {"rows": []},
        "results": [{"employee_id": "zt1", "performance_bonus": 100}],
        "total_employees": 1,
        "total_bonus": 100,
    }
    manifest = fbu_storage.build_fbu_run_manifest(payload)
    objects: dict[str, bytes] = {
        f"{prefix}/_runs-index.json": json.dumps({
            "schemaVersion": 2,
            "runs": [manifest],
        }).encode("utf-8"),
        f"{prefix}/run_123/summary.json": json.dumps(manifest).encode("utf-8"),
        f"{prefix}/run_123/sections/period_adjustment_data.json": b'{"rows":[]}',
        f"{prefix}/run_123/sections/results.json": json.dumps(
            payload["results"]
        ).encode("utf-8"),
    }
    active_uploads = 0
    max_active_uploads = 0
    active_lock = threading.Lock()

    def upload(object_path: str, content: bytes, content_type: str) -> None:
        nonlocal active_uploads, max_active_uploads
        with active_lock:
            active_uploads += 1
            max_active_uploads = max(max_active_uploads, active_uploads)
        time.sleep(0.03)
        objects[object_path] = content
        with active_lock:
            active_uploads -= 1

    monkeypatch.setattr(fbu_storage, "_upload_bytes", upload)
    monkeypatch.setattr(
        fbu_storage,
        "_download_bytes",
        lambda object_path: objects.get(object_path),
    )
    fbu_storage._clear_fbu_json_cache()

    fbu_storage.save_fbu_run_snapshot_to_persistent(
        "run_123",
        {
            **payload,
            "status": "step2",
            "period_adjustment_data": {
                "rows": [{"employee_id": "zt1", "amount": 50}],
            },
            "results": [],
            "total_employees": 0,
            "total_bonus": 0,
        },
        changed_fields={
            "status",
            "period_adjustment_data",
            "results",
            "total_employees",
            "total_bonus",
        },
    )

    assert max_active_uploads >= 2


def test_first_incremental_write_migrates_all_legacy_metadata_sections(monkeypatch):
    monkeypatch.setenv("SIGMA_FBU_STORAGE_ENV", "production")
    prefix = "fbu-performance-runs/production"
    legacy = {
        "run_id": "legacy_123",
        "created_at": "2026-07-01T10:00:00",
        "calc_month": "2026-06",
        "status": "completed",
        "attendance_data": {"employees": [{"employee_id": "zt1"}]},
        "salary_data": {"employees": [{"employee_id": "zt1", "hourly_rate": 20}]},
        "results": [{"employee_id": "zt1", "performance_bonus": 100}],
        "total_employees": 1,
        "total_bonus": 100,
    }
    objects: dict[str, bytes] = {
        f"{prefix}/legacy_123/metadata.json": json.dumps(legacy).encode("utf-8"),
    }

    def upload(object_path: str, content: bytes, content_type: str) -> None:
        objects[object_path] = content

    monkeypatch.setattr(fbu_storage, "_upload_bytes", upload)
    monkeypatch.setattr(fbu_storage, "_download_bytes", lambda object_path: objects.get(object_path))
    monkeypatch.setattr(fbu_storage, "_list_objects", lambda object_prefix: [])

    fbu_storage.save_fbu_run_snapshot_to_persistent(
        "legacy_123",
        {
            "run_id": "legacy_123",
            "created_at": legacy["created_at"],
            "calc_month": "2026-06",
            "status": "step2",
            "period_adjustment_data": {
                "rows": [{"employee_id": "zt1", "amount": 50}],
            },
            "results": [],
            "total_employees": 0,
            "total_bonus": 0,
        },
        changed_fields={
            "status",
            "period_adjustment_data",
            "results",
            "total_employees",
            "total_bonus",
        },
    )

    assert json.loads(
        objects[f"{prefix}/legacy_123/sections/attendance_data.json"]
    ) == legacy["attendance_data"]
    assert json.loads(
        objects[f"{prefix}/legacy_123/sections/salary_data.json"]
    ) == legacy["salary_data"]
    restored = fbu_storage.load_fbu_run_snapshot_from_persistent(
        "legacy_123",
        sections={"attendance_data", "salary_data", "period_adjustment_data"},
    )
    assert restored["attendance_data"] == legacy["attendance_data"]
    assert restored["salary_data"] == legacy["salary_data"]
    assert restored["period_adjustment_data"]["rows"][0]["amount"] == 50


def _install_fake_persistent_backend(monkeypatch):
    metadata: dict[str, dict] = {}
    files: dict[tuple[str, str], bytes] = {}
    manifests: dict[str, dict] = {}

    monkeypatch.setattr(fbu_runs, "fbu_persistent_storage_enabled", lambda: True)

    def save_snapshot(run_id, payload, *, changed_fields=None):
        current = dict(metadata.get(run_id) or {})
        if changed_fields is None:
            current = dict(payload)
        else:
            for key, value in payload.items():
                if key not in fbu_storage.FBU_RUN_SECTION_FIELDS or key in changed_fields:
                    current[key] = value
        metadata[run_id] = current
        manifest = fbu_storage.build_fbu_run_manifest(
            current,
            previous=manifests.get(run_id),
            changed_fields=changed_fields,
        )
        manifests[run_id] = manifest
        return manifest

    def load_snapshot(run_id, *, sections=None, refresh=False):
        current = metadata.get(run_id)
        if current is None:
            return None
        if sections is None:
            return dict(current)
        return {
            key: value
            for key, value in current.items()
            if key not in fbu_storage.FBU_RUN_SECTION_FIELDS or key in sections
        }

    monkeypatch.setattr(fbu_runs, "save_fbu_run_snapshot_to_persistent", save_snapshot)
    monkeypatch.setattr(fbu_runs, "load_fbu_run_snapshot_from_persistent", load_snapshot)
    monkeypatch.setattr(
        fbu_runs,
        "list_fbu_run_summaries_from_persistent",
        lambda: list(manifests.values()),
    )
    monkeypatch.setattr(
        fbu_runs,
        "delete_fbu_run_from_persistent",
        lambda run_id: (metadata.pop(run_id, None), manifests.pop(run_id, None)),
    )

    def save_files(run_id: str, run_dir: Path, relative_paths: list[str]) -> None:
        for relative_path in relative_paths:
            path = run_dir / relative_path
            if path.is_file():
                files[(run_id, relative_path)] = path.read_bytes()

    def load_file(run_id: str, run_dir: Path, relative_path: str) -> Path | None:
        content = files.get((run_id, relative_path))
        if content is None:
            return None
        path = run_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    monkeypatch.setattr(fbu_runs, "save_fbu_files_to_persistent", save_files)
    monkeypatch.setattr(fbu_runs, "load_fbu_file_from_persistent", load_file)
    return metadata, files


def test_run_metadata_survives_separate_manager_instances(monkeypatch, tmp_path):
    _install_fake_persistent_backend(monkeypatch)
    first = fbu_runs.FBURunManager(str(tmp_path / "instance-a"))

    created = first.create_run("2026-05")
    first.save_step_data(created.run_id, 1, {"employees": [{"employee_id": "zt1"}]})

    second = fbu_runs.FBURunManager(str(tmp_path / "instance-b"))
    restored = second.get_run(created.run_id)

    assert restored is not None
    assert restored.calc_month == "2026-05"
    assert restored.attendance_data["employees"][0]["employee_id"] == "zt1"
    assert [run.run_id for run in second.list_runs()] == [created.run_id]


def test_run_manager_can_force_persistent_manifest_refresh(monkeypatch, tmp_path):
    refresh_values = []
    monkeypatch.setattr(fbu_runs, "fbu_persistent_storage_enabled", lambda: True)

    def load_snapshot(run_id, *, sections=None, refresh=False):
        refresh_values.append(refresh)
        return {
            "run_id": run_id,
            "created_at": "2026-08-18T00:00:00",
            "calc_month": "2026-08",
        }

    monkeypatch.setattr(
        fbu_runs,
        "load_fbu_run_snapshot_from_persistent",
        load_snapshot,
    )
    manager = fbu_runs.FBURunManager(str(tmp_path))

    restored = manager.get_run("run_123", sections=set(), refresh=True)

    assert restored is not None
    assert restored.run_id == "run_123"
    assert refresh_values == [True]


def test_save_step_data_applies_metadata_and_persists_once(monkeypatch, tmp_path):
    manager = fbu_runs.FBURunManager(str(tmp_path))
    created = manager.create_run("2026-05", persist=False)
    save_calls: list[str] = []
    monkeypatch.setattr(manager, "_save_runs", lambda run_id, changed_fields=None: save_calls.append(run_id))

    manager.save_step_data(
        created.run_id,
        1,
        {"employees": [{"employee_id": "zt1"}]},
        attendance_file="attendance.xlsx",
        previous_attendance_file="previous.xlsx",
    )

    updated = manager.runs[created.run_id]
    assert updated.attendance_file == "attendance.xlsx"
    assert updated.previous_attendance_file == "previous.xlsx"
    assert updated.attendance_data["employees"][0]["employee_id"] == "zt1"
    assert save_calls == [created.run_id]


def test_run_file_can_be_materialized_in_another_instance(monkeypatch, tmp_path):
    _, files = _install_fake_persistent_backend(monkeypatch)
    first = fbu_runs.FBURunManager(str(tmp_path / "instance-a"))
    created = first.create_run("2026-05")
    run_dir = first.data_dir / created.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "attendance.xlsx").write_bytes(b"attendance-content")

    first.persist_files(created.run_id, ["attendance.xlsx"])
    assert files[(created.run_id, "attendance.xlsx")] == b"attendance-content"

    second = fbu_runs.FBURunManager(str(tmp_path / "instance-b"))
    restored_path = second.materialize_file(created.run_id, "attendance.xlsx")

    assert restored_path is not None
    assert restored_path.read_bytes() == b"attendance-content"


def test_run_manager_promotes_direct_upload_before_job_cleanup(monkeypatch, tmp_path):
    manager = fbu_runs.FBURunManager(str(tmp_path))
    calls = []
    monkeypatch.setattr(fbu_runs, "fbu_persistent_storage_enabled", lambda: True)
    monkeypatch.setattr(
        fbu_runs,
        "delete_fbu_files_from_persistent",
        lambda run_id, paths: calls.append(("delete", run_id, list(paths))),
    )
    monkeypatch.setattr(
        fbu_runs,
        "copy_fbu_file_in_persistent",
        lambda run_id, source, destination: calls.append(("copy", run_id, source, destination)),
    )

    promoted = manager.promote_persisted_file(
        "run_123",
        "direct_uploads/job_attendance.xlsx",
        "attendance.xlsx",
    )

    assert promoted is True
    assert calls == [
        ("delete", "run_123", ["attendance.xlsx"]),
        (
            "copy",
            "run_123",
            "direct_uploads/job_attendance.xlsx",
            "attendance.xlsx",
        ),
    ]


def test_local_manager_does_not_require_persistent_backend(monkeypatch, tmp_path):
    monkeypatch.setattr(fbu_runs, "fbu_persistent_storage_enabled", lambda: False)
    manager = fbu_runs.FBURunManager(str(tmp_path))

    created = manager.create_run("2026-05")

    assert manager.get_run(created.run_id) is created
    assert (tmp_path / "runs.json").exists()


def test_roster_and_rule_lists_survive_separate_store_instances(monkeypatch, tmp_path):
    _install_fake_persistent_backend(monkeypatch)
    first_roster = fbu_runs.FBURosterStore(str(tmp_path / "instance-a"))
    first_rules = fbu_runs.FBURuleListStore(str(tmp_path / "instance-a"))

    first_roster.save_active_roster(b"roster-content", "roster.xlsx", total_employees=3)
    first_rules.save(
        {
            "work_hour_employees": [{"employee_id": "zt1", "name": "A", "active": True}],
            "fixed_base_employees": [
                {"employee_id": "zt2", "name": "B", "fixed_performance_base": 2000, "active": True}
            ],
        }
    )

    second_roster = fbu_runs.FBURosterStore(str(tmp_path / "instance-b"))
    second_rules = fbu_runs.FBURuleListStore(str(tmp_path / "instance-b"))

    assert second_roster.get_metadata()["total_employees"] == 3
    copied = second_roster.copy_active_to_run("run-2")
    assert copied is not None
    assert copied.read_bytes() == b"roster-content"
    assert second_rules.get()["work_hour_employees"][0]["employee_id"] == "zt1"


def test_fbu_activity_upload_and_detail_work_across_three_instances(monkeypatch, tmp_path):
    _install_fake_persistent_backend(monkeypatch)
    client = TestClient(app_module.app)

    instance_a = tmp_path / "instance-a"
    monkeypatch.setattr(app_module, "FBU_PERFORMANCE_RUNS_DIR", instance_a)
    monkeypatch.setattr(app_module, "fbu_run_manager", fbu_runs.FBURunManager(str(instance_a)))
    monkeypatch.setattr(app_module, "fbu_roster_store", fbu_runs.FBURosterStore(str(instance_a)))
    created = client.post("/api/fbu-performance/runs", json={"calc_month": "2026-05"})
    assert created.status_code == 200
    run_id = created.json()["run_id"]

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "sheet1"
    sheet.append(["header"] * 118)
    row = [""] * 118
    row[0] = "2026-05-01"
    row[1] = "Test User"
    row[2] = "zt100"
    row[21] = "08:00"
    row[117] = 8
    sheet.append(row)
    buffer = BytesIO()
    workbook.save(buffer)

    instance_b = tmp_path / "instance-b"
    monkeypatch.setattr(app_module, "FBU_PERFORMANCE_RUNS_DIR", instance_b)
    monkeypatch.setattr(app_module, "fbu_run_manager", fbu_runs.FBURunManager(str(instance_b)))
    monkeypatch.setattr(app_module, "fbu_roster_store", fbu_runs.FBURosterStore(str(instance_b)))
    uploaded = client.post(
        "/api/fbu-performance/import-attendance",
        data={"calc_month": "2026-05", "run_id": run_id},
        files={
            "file": (
                "attendance.xlsx",
                buffer.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert uploaded.status_code == 200, uploaded.text
    download_url = uploaded.json()["result_file"]["download_url"]

    instance_c = tmp_path / "instance-c"
    monkeypatch.setattr(app_module, "FBU_PERFORMANCE_RUNS_DIR", instance_c)
    monkeypatch.setattr(app_module, "fbu_run_manager", fbu_runs.FBURunManager(str(instance_c)))
    monkeypatch.setattr(app_module, "fbu_roster_store", fbu_runs.FBURosterStore(str(instance_c)))
    detail = client.get(f"/api/fbu-performance/runs/{run_id}")

    assert detail.status_code == 200, detail.text
    assert detail.json()["attendance_data"]["employees"][0]["employee_id"] == "zt100"

    downloaded = client.get(download_url)
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.content.startswith(b"PK")
