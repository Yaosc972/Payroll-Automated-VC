from __future__ import annotations

from pathlib import Path
from copy import deepcopy

import bonus_platform.app as app_module
from bonus_platform.engine.domestic_labor import persistent_storage as domestic
from bonus_platform.engine import company_run_storage, runs as recruitment_runs
from bonus_platform.engine.fbu_performance import migrate_mysql, mysql_state, persistent_storage as fbu, postgres_state
from bonus_platform.engine.labor import obs_storage, persistent_storage as labor
from bonus_platform.engine.social_insurance import persistent_storage as social


def _obs_env(monkeypatch):
    monkeypatch.setenv("OBS_ENDPOINT", "obs.example.invalid")
    monkeypatch.setenv("OBS_BUCKET", "test-bucket")
    monkeypatch.setenv("OBS_ACCESS_KEY", "test-access-key")
    monkeypatch.setenv("OBS_SECRET_KEY", "test-secret-key")


def test_domestic_s3_uses_obs_for_direct_and_persisted_files(monkeypatch, tmp_path: Path):
    _obs_env(monkeypatch)
    monkeypatch.setenv("SIGMA_DOMESTIC_LABOR_STORAGE_BACKEND", "s3")
    monkeypatch.setenv("SIGMA_LABOR_STORAGE_ENV", "production")
    objects = {}
    monkeypatch.setattr(domestic, "obs_put_bytes", lambda key, data, **kwargs: objects.__setitem__(key, data))
    monkeypatch.setattr(domestic, "obs_get_bytes", lambda key: objects.get(key))
    monkeypatch.setattr(domestic, "obs_list_objects", lambda prefix: [{"key": key} for key in objects if key.startswith(prefix)])
    monkeypatch.setattr(domestic, "obs_signed_upload_for_key", lambda key: f"https://obs.example.invalid/{key}")
    assert domestic.domestic_labor_persistent_storage_enabled()
    intent = domestic.create_domestic_labor_signed_upload("run_1", "data.xlsx")
    assert intent["headers"] == {}
    assert intent["bodyFormat"] == "raw"
    assert intent["objectPath"].startswith("domestic-labor-runs/production/run_1/")
    domestic._upload_bytes(intent["objectPath"], b"content", content_type="application/octet-stream")
    assert domestic._download_bytes(intent["objectPath"]) == b"content"
    assert domestic._list_objects("domestic-labor-runs/production") == [{"name": "run_1"}]
    target = tmp_path / "data.xlsx"
    assert domestic._download_to_path(intent["objectPath"], target)
    assert target.read_bytes() == b"content"


def test_fbu_s3_uses_obs_and_mysql_dispatch(monkeypatch):
    _obs_env(monkeypatch)
    monkeypatch.setenv("SIGMA_FBU_STORAGE_BACKEND", "s3")
    monkeypatch.setenv("SIGMA_FBU_STATE_BACKEND", "mysql")
    monkeypatch.setenv("SIGMA_FBU_STORAGE_ENV", "production")
    objects = {}
    monkeypatch.setattr(fbu, "obs_put_bytes", lambda key, data, **kwargs: objects.__setitem__(key, data))
    monkeypatch.setattr(fbu, "obs_get_bytes", lambda key: objects.get(key))
    monkeypatch.setattr(fbu, "obs_list_objects", lambda prefix: [{"key": key} for key in objects if key.startswith(prefix)])
    monkeypatch.setattr(fbu, "obs_signed_upload_for_key", lambda key: f"https://obs.example.invalid/{key}")
    assert fbu.fbu_persistent_storage_enabled()
    assert mysql_state.requested()
    assert postgres_state.fbu_postgres_state_requested()
    intent = fbu.create_fbu_signed_upload("run_1", "salary.xlsx")
    assert intent["headers"] == {}
    assert intent["bodyFormat"] == "raw"
    fbu._upload_bytes(intent["objectPath"], b"content", content_type="application/octet-stream")
    assert fbu._download_bytes(intent["objectPath"]) == b"content"
    assert fbu._list_objects("fbu-performance-runs/production") == [{"name": "run_1"}]
    monkeypatch.setattr(mysql_state, "rpc", lambda name, payload: {"applied": True, "data": payload})
    assert postgres_state._rpc("sigma_fbu_patch_job", {"p_run_id": "run_1"})["applied"]


def test_social_s3_uses_obs_for_json(monkeypatch):
    _obs_env(monkeypatch)
    monkeypatch.setenv("SIGMA_SOCIAL_INSURANCE_STORAGE_BACKEND", "s3")
    monkeypatch.setenv("SIGMA_SOCIAL_INSURANCE_STORAGE_ENV", "production")
    objects = {}
    monkeypatch.setattr(social, "obs_put_bytes", lambda key, data, **kwargs: objects.__setitem__(key, data))
    monkeypatch.setattr(social, "obs_get_bytes", lambda key: objects.get(key))
    monkeypatch.setattr(social, "obs_list_objects", lambda prefix: [{"key": key, "lastModified": "now"}
                                                               for key in objects if key.startswith(prefix)])
    assert social.persistent_storage_enabled()
    social.persist_json("rules", "month", {"ok": True})
    assert social.load_json("rules", "month") == {"ok": True}
    assert social.list_json("rules") == [{"ok": True}]


def test_labor_obs_dispatches_bulk_sync(monkeypatch, tmp_path: Path):
    _obs_env(monkeypatch)
    monkeypatch.setenv("SIGMA_LABOR_STORAGE_BACKEND", "obs")
    monkeypatch.setenv("SIGMA_LABOR_STORAGE_ENV", "production")
    observed = []
    monkeypatch.setattr(labor, "sync_labor_run_to_obs", lambda run_id, run_dir: observed.append((run_id, run_dir)))
    assert labor.labor_persistent_storage_enabled()
    assert labor.labor_persistent_storage_info()["backend"] == "obs"
    labor.sync_labor_run_to_persistent("run_1", tmp_path)
    assert observed == [("run_1", tmp_path)]


def test_obs_signed_urls_use_vendor_sdk(monkeypatch):
    _obs_env(monkeypatch)

    class FakeClient:
        def createSignedUrl(self, **kwargs):
            assert kwargs["bucketName"] == "test-bucket"
            assert kwargs["objectKey"] == "private/file.xlsx"
            return type("Response", (), {"signedUrl": "https://obs.example.invalid/signed"})()

    monkeypatch.setattr(obs_storage, "_get_obs_client", lambda: FakeClient())
    assert obs_storage.obs_signed_upload_for_key("private/file.xlsx").startswith("https://")
    assert obs_storage.obs_signed_download_for_key("private/file.xlsx").startswith("https://")


def test_fbu_mysql_transactional_snapshot_and_job(monkeypatch):
    monkeypatch.setenv("SIGMA_FBU_STORAGE_ENV", "production")
    state = {"sigma_fbu_runs": {}, "sigma_fbu_run_sections": {}, "sigma_fbu_upload_jobs": {}}

    class FakeCursor:
        def __init__(self):
            self.rows = []

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, sql, params):
            if "sigma_fbu_run_sections" in sql:
                table = "sigma_fbu_run_sections"
            elif "sigma_fbu_upload_jobs" in sql:
                table = "sigma_fbu_upload_jobs"
            else:
                table = "sigma_fbu_runs"
            if sql.startswith("SELECT core FROM"):
                self.rows = [{"core": value["data"]} for key, value in state[table].items() if key[0] == params[0]]
            elif sql.startswith("SELECT"):
                row = state[table].get(tuple(params))
                self.rows = [deepcopy(row)] if row else []
            elif sql.startswith("INSERT"):
                key = tuple(params[:3] if table != "sigma_fbu_runs" else params[:2])
                state[table][key] = {"data": params[-2], "revision": params[-1]}
                self.rows = []
            elif sql.startswith("DELETE"):
                for key in list(state[table]):
                    if key[:2] == tuple(params):
                        state[table].pop(key)
                self.rows = []
            else:
                raise AssertionError(sql)

        def fetchone(self):
            return self.rows[0] if self.rows else None

        def fetchall(self):
            return self.rows

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(mysql_state, "_connection", FakeConnection)
    request = {
        "p_run_id": "run_1", "p_expected_core_revision": 0,
        "p_core_data": {"run_id": "run_1", "status": "new"},
        "p_sections": {"attendance_data": {"data": {"rows": [1]}, "expected_revision": 0}},
    }
    result = mysql_state.rpc("sigma_fbu_commit_snapshot", request)
    assert result["applied"] and result["revision"] == 1
    assert mysql_state.load_run_state("run_1", {"attendance_data"})["attendance_data"] == {"rows": [1]}
    conflict = mysql_state.rpc("sigma_fbu_commit_snapshot", request)
    assert not conflict["applied"] and conflict["revision"] == 1
    job = mysql_state.rpc("sigma_fbu_patch_job", {
        "p_run_id": "run_1", "p_job_id": "job_1",
        "p_seed": {"status": "uploading"}, "p_patch": {"status": "completed"},
        "p_allowed_from": ["uploading"],
    })
    assert job["applied"] and mysql_state.load_job("run_1", "job_1")["status"] == "completed"
    denied = mysql_state.rpc("sigma_fbu_patch_job", {
        "p_run_id": "run_1", "p_job_id": "job_1", "p_patch": {"status": "failed"},
        "p_allowed_from": ["uploading"],
    })
    assert not denied["applied"] and mysql_state.load_job("run_1", "job_1")["status"] == "completed"


def test_fbu_mysql_migration_is_additive(monkeypatch):
    statements = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, statement):
            statements.append(statement.strip())

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            pass

        def rollback(self):
            raise AssertionError("migration rolled back")

        def close(self):
            pass

    monkeypatch.setattr(migrate_mysql.config, "ADMIN_DATABASE_URL", "mysql://user:password@example.invalid/test")
    monkeypatch.setattr(migrate_mysql, "mysql_connection", lambda url: FakeConnection())
    migrate_mysql.main()
    assert len(statements) == 3
    assert all(statement.startswith("CREATE TABLE IF NOT EXISTS sigma_fbu_") for statement in statements)


def test_company_file_runs_restore_from_obs(monkeypatch, tmp_path: Path):
    _obs_env(monkeypatch)
    monkeypatch.setenv("SIGMA_RECRUITMENT_STORAGE_BACKEND", "obs")
    monkeypatch.setenv("SIGMA_LABOR_STORAGE_ENV", "production")
    objects = {}
    monkeypatch.setattr(company_run_storage, "obs_put_bytes", lambda key, data, **kwargs: objects.__setitem__(key, data))
    monkeypatch.setattr(company_run_storage, "obs_get_bytes", lambda key: objects.get(key))
    monkeypatch.setattr(company_run_storage, "obs_list_objects", lambda prefix: [{"key": key}
                                                                      for key in objects if key.startswith(prefix)])
    root = tmp_path / "runs"
    run_dir = root / "run_1"
    run_dir.mkdir(parents=True)
    (run_dir / "metadata.json").write_text('{"id":"run_1"}', encoding="utf-8")
    (run_dir / "result.xlsx").write_bytes(b"report")
    assert company_run_storage.enabled("SIGMA_RECRUITMENT_STORAGE_BACKEND")
    company_run_storage.upload_run_dir("recruitment-bonus", run_dir)
    assert company_run_storage.list_run_ids("recruitment-bonus") == ["run_1"]
    assert company_run_storage.load_file("recruitment-bonus", "run_1", "metadata.json") == b'{"id":"run_1"}'
    new_root = tmp_path / "restored"
    company_run_storage.restore_run_dir("recruitment-bonus", "run_1", new_root)
    assert (new_root / "run_1" / "result.xlsx").read_bytes() == b"report"


def test_recruitment_run_restores_files_after_local_loss(monkeypatch, tmp_path: Path):
    _obs_env(monkeypatch)
    monkeypatch.setenv("SIGMA_RECRUITMENT_STORAGE_BACKEND", "obs")
    monkeypatch.setenv("SIGMA_LABOR_STORAGE_ENV", "production")
    objects = {}
    monkeypatch.setattr(company_run_storage, "obs_put_bytes", lambda key, data, **kwargs: objects.__setitem__(key, data))
    monkeypatch.setattr(company_run_storage, "obs_get_bytes", lambda key: objects.get(key))
    monkeypatch.setattr(company_run_storage, "obs_list_objects", lambda prefix: [{"key": key} for key in objects if key.startswith(prefix)])
    monkeypatch.setattr(recruitment_runs, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(recruitment_runs, "upsert_run_metadata", lambda metadata: None)
    run_dir = recruitment_runs.create_run_dir("run_2")
    (run_dir / "report.xlsx").write_bytes(b"report")
    recruitment_runs.save_metadata(run_dir, {"id": "run_2"})
    (run_dir / "metadata.json").unlink()
    (run_dir / "report.xlsx").unlink()
    restored = recruitment_runs.get_run_dir("run_2")
    assert (restored / "report.xlsx").read_bytes() == b"report"


def test_meal_run_lists_and_restores_from_obs(monkeypatch, tmp_path: Path):
    _obs_env(monkeypatch)
    monkeypatch.setenv("SIGMA_CHINA_EMPLOYEE_STORAGE_BACKEND", "obs")
    monkeypatch.setenv("SIGMA_LABOR_STORAGE_ENV", "production")
    objects = {}
    monkeypatch.setattr(company_run_storage, "obs_put_bytes", lambda key, data, **kwargs: objects.__setitem__(key, data))
    monkeypatch.setattr(company_run_storage, "obs_get_bytes", lambda key: objects.get(key))
    monkeypatch.setattr(company_run_storage, "obs_list_objects", lambda prefix: [{"key": key} for key in objects if key.startswith(prefix)])
    monkeypatch.setattr(app_module, "CHINA_EMPLOYEE_PAYROLL_RUNS_DIR", tmp_path / "meal")
    run_id = "china_employee_payroll_20260923_123456"
    run_dir = tmp_path / "meal" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "metadata.json").write_text('{"runId":"' + run_id + '","summary":{}}', encoding="utf-8")
    (run_dir / "result.json").write_text('{"summary":{},"results":[],"files":[]}', encoding="utf-8")
    company_run_storage.upload_run_dir("china-employee-meal", run_dir)
    (run_dir / "metadata.json").unlink()
    (run_dir / "result.json").unlink()
    listing = app_module.list_china_employee_meal_allowance_runs()
    assert listing["runs"][0]["runId"] == run_id
    restored = app_module.get_china_employee_meal_allowance_run(run_id)
    assert restored["runId"] == run_id
