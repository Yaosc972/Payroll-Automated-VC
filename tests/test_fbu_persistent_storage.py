from __future__ import annotations

import gzip
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import Workbook
import pytest

import bonus_platform.app as app_module
from bonus_platform.engine.fbu_performance import runs as fbu_runs
from bonus_platform.engine.fbu_performance import persistent_storage as fbu_storage


pytestmark = pytest.mark.usefixtures("bypass_fbu_access_gate")


def test_run_metadata_is_compressed_and_old_plain_json_remains_readable(monkeypatch):
    uploaded: dict[str, object] = {}
    payload = {
        "run_id": "run-1",
        "attendance_data": {"employees": [{"employee_id": f"zt{index}"} for index in range(200)]},
    }

    def capture_upload(object_path, content, *, content_type):
        uploaded.update({"path": object_path, "content": content, "content_type": content_type})

    monkeypatch.setattr(fbu_storage, "_upload_bytes", capture_upload)
    fbu_storage.save_fbu_run_metadata_to_persistent("run-1", payload)

    content = uploaded["content"]
    assert isinstance(content, bytes)
    assert content.startswith(b"\x1f\x8b")
    assert uploaded["content_type"] == "application/gzip"
    assert len(content) < len(gzip.decompress(content))

    monkeypatch.setattr(fbu_storage, "_download_bytes", lambda object_path: content)
    assert fbu_storage.load_fbu_run_metadata_from_persistent("run-1") == payload

    plain = b'{"run_id":"legacy-run","status":"pending"}'
    monkeypatch.setattr(fbu_storage, "_download_bytes", lambda object_path: plain)
    assert fbu_storage.load_fbu_run_metadata_from_persistent("legacy-run")["run_id"] == "legacy-run"


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


def _install_fake_persistent_backend(monkeypatch):
    metadata: dict[str, dict] = {}
    files: dict[tuple[str, str], bytes] = {}

    monkeypatch.setattr(fbu_runs, "fbu_persistent_storage_enabled", lambda: True)
    monkeypatch.setattr(
        fbu_runs,
        "save_fbu_run_metadata_to_persistent",
        lambda run_id, payload: metadata.__setitem__(run_id, dict(payload)),
    )
    monkeypatch.setattr(
        fbu_runs,
        "load_fbu_run_metadata_from_persistent",
        lambda run_id: dict(metadata[run_id]) if run_id in metadata else None,
    )
    monkeypatch.setattr(
        fbu_runs,
        "list_fbu_run_metadata_from_persistent",
        lambda: [dict(payload) for payload in metadata.values()],
    )
    monkeypatch.setattr(
        fbu_runs,
        "delete_fbu_run_from_persistent",
        lambda run_id: metadata.pop(run_id, None),
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


def test_mutating_loaded_run_does_not_download_metadata_again(monkeypatch, tmp_path):
    metadata, _ = _install_fake_persistent_backend(monkeypatch)
    seed = fbu_runs.FBURun(
        run_id="run-1",
        created_at="2026-07-14T09:00:00",
        calc_month="2026-05",
    )
    metadata[seed.run_id] = vars(seed).copy()
    load_count = 0

    def load_metadata(run_id):
        nonlocal load_count
        load_count += 1
        return dict(metadata[run_id])

    monkeypatch.setattr(fbu_runs, "load_fbu_run_metadata_from_persistent", load_metadata)
    manager = fbu_runs.FBURunManager(str(tmp_path))

    assert manager.get_run(seed.run_id) is not None
    manager.update_run(seed.run_id, status="step1")
    manager.save_step_data(seed.run_id, 1, {"employees": []})

    assert load_count == 1


def test_save_step_data_applies_metadata_and_persists_once(monkeypatch, tmp_path):
    manager = fbu_runs.FBURunManager(str(tmp_path))
    created = manager.create_run("2026-05", persist=False)
    save_calls: list[str] = []
    monkeypatch.setattr(manager, "_save_runs", save_calls.append)

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
