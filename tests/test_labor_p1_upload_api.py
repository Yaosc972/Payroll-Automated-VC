import threading

import pytest
from fastapi.testclient import TestClient

import bonus_platform.app as app_module
import bonus_platform.engine.admin_store as admin_store
import bonus_platform.engine.labor.runs as labor_runs
from bonus_platform.app import app


@pytest.fixture
def p1_upload_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SIGMA_LABOR_AUTH_REQUIRED", "1")
    monkeypatch.setenv("SIGMA_ENABLE_MOCK_LOGIN", "1")
    monkeypatch.setenv("SIGMA_LABOR_P1_REQUIRED", "0")
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.setattr(admin_store, "get_admin_db_path", lambda: tmp_path / "admin.sqlite")
    monkeypatch.setattr(admin_store, "get_admin_database_url", lambda: "")
    monkeypatch.setattr(labor_runs, "LABOR_RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(app_module, "LABOR_RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(app_module, "_labor_audit_path", lambda: tmp_path / "audit.jsonl")
    admin_store._STORE_INITIALIZED = False
    admin_store._STORE_INITIALIZED_TARGET = ""
    return tmp_path


def _login(client):
    response = client.post("/api/auth/mock-login", json={"userId": "overseasAdminUser"})
    assert response.status_code == 200


def _headers(client):
    access = client.get("/api/labor/access").json()
    return {
        "x-sigma-labor-api-contract": str(access["apiContractVersion"]),
        "x-sigma-labor-ui-version": str(access["version"]),
        "x-sigma-labor-ui-build": str(access["buildId"]),
    }


def _create_run(client):
    response = client.post(
        "/api/labor/runs",
        headers=_headers(client),
        json={
            "supplierName": "Signed Upload Supplier",
            "periodStart": "2026-07-01",
            "periodEnd": "2026-07-07",
        },
    )
    assert response.status_code == 200
    return response.json()


def test_p1_upload_intent_binds_storage_path_and_manifest_to_session_owner(p1_upload_env, monkeypatch):
    pending_batches = []
    monkeypatch.setattr(app_module, "labor_postgres_state_enabled", lambda: True)
    monkeypatch.setattr(
        app_module,
        "labor_p1_object_key",
        lambda **kwargs: f"labor-runs/uat/owners/{kwargs['owner_user_id']}/runs/{kwargs['run_id']}/inputs/{kwargs['file_id']}/{kwargs['filename']}",
        raising=False,
    )
    monkeypatch.setattr(
        app_module,
        "create_pending_labor_file_states",
        lambda **kwargs: pending_batches.append(kwargs) or [
            {"id": item["file_id"], "uploadState": "pending"}
            for item in kwargs["files"]
        ],
        raising=False,
    )
    monkeypatch.setattr(
        app_module,
        "create_labor_supabase_signed_upload_for_object",
        lambda object_key, **_kwargs: {
            "signedUrl": f"https://project.supabase.co/upload?token={object_key[-8:]}",
            "token": "short-token",
            "method": "PUT",
            "headers": {"content-type": "application/pdf"},
            "objectKey": object_key,
            "expiresIn": 7200,
            "private": True,
        },
        raising=False,
    )

    with TestClient(app) as client:
        _login(client)
        run = _create_run(client)
        response = client.post(
            f"/api/labor/runs/{run['id']}/upload-intents",
            headers=_headers(client),
            json={
                "files": [
                    {
                        "filename": "invoice.pdf",
                        "fileKind": "pdf_invoice",
                        "contentType": "application/pdf",
                        "sizeBytes": 1024,
                        "sha256": "a" * 64,
                    }
                ]
            },
        )

    assert response.status_code == 200
    intent = response.json()["intents"][0]
    assert intent["method"] == "PUT"
    assert pending_batches[0]["owner_user_id"] == "overseasAdminUser"
    assert pending_batches[0]["actor_user_id"] == "overseasAdminUser"
    assert "/owners/overseasAdminUser/" in pending_batches[0]["files"][0]["object_key"]


def test_p1_upload_intent_accepts_near_limit_pdf_and_workbook_and_rejects_oversize(
    p1_upload_env,
    monkeypatch,
):
    pending_batches = []
    signing_calls = []
    signing_barrier = threading.Barrier(2)
    monkeypatch.setattr(app_module, "labor_postgres_state_enabled", lambda: True)
    monkeypatch.setattr(
        app_module,
        "create_pending_labor_file_states",
        lambda **kwargs: pending_batches.append(kwargs) or [
            {"id": item["file_id"], "uploadState": "pending"}
            for item in kwargs["files"]
        ],
    )

    def sign(object_key, **_kwargs):
        signing_calls.append(object_key)
        signing_barrier.wait(timeout=2)
        return {
            "signedUrl": "https://project.supabase.co/upload?token=short",
            "method": "PUT",
            "headers": {},
            "objectKey": object_key,
            "expiresIn": 7200,
            "private": True,
        }

    monkeypatch.setattr(
        app_module,
        "create_labor_supabase_signed_upload_for_object",
        sign,
    )

    near_limit_files = [
        {
            "filename": "near-limit-invoice.pdf",
            "fileKind": "pdf_invoice",
            "contentType": "application/pdf",
            "sizeBytes": 49_285_028,
            "sha256": "00124f458491edb5e1a85a3aaaea2cc07f21af039695d34196d91e3193607fe3",
        },
        {
            "filename": "near-limit-bill.xlsx",
            "fileKind": "workbook",
            "contentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "sizeBytes": 19_512_933,
            "sha256": "153b1bf80a1420518813bce1b5699c3d69f83d0530d75c77ea8bc47d51d5ef1d",
        },
    ]

    with TestClient(app) as client:
        _login(client)
        run = _create_run(client)
        accepted = client.post(
            f"/api/labor/runs/{run['id']}/upload-intents",
            headers=_headers(client),
            json={"files": near_limit_files},
        )
        oversized_pdf = client.post(
            f"/api/labor/runs/{run['id']}/upload-intents",
            headers=_headers(client),
            json={
                "files": [
                    {
                        **near_limit_files[0],
                        "sizeBytes": 50 * 1024 * 1024 + 1,
                    }
                ]
            },
        )
        oversized_workbook = client.post(
            f"/api/labor/runs/{run['id']}/upload-intents",
            headers=_headers(client),
            json={
                "files": [
                    {
                        **near_limit_files[1],
                        "sizeBytes": 20 * 1024 * 1024 + 1,
                    }
                ]
            },
        )

    assert accepted.status_code == 200
    assert len(accepted.json()["intents"]) == 2
    assert [item["size_bytes"] for item in pending_batches[0]["files"]] == [
        49_285_028,
        19_512_933,
    ]
    assert len(signing_calls) == 2
    assert oversized_pdf.status_code == 413
    assert oversized_pdf.json()["detail"]["errorCode"] == "LABOR_PDF_SIZE_LIMIT_EXCEEDED"
    assert oversized_workbook.status_code == 413
    assert oversized_workbook.json()["detail"]["errorCode"] == "LABOR_WORKBOOK_SIZE_LIMIT_EXCEEDED"
    assert len(signing_calls) == 2


def test_p1_upload_intents_do_not_write_partial_manifest_when_signing_fails(p1_upload_env, monkeypatch):
    pending_batches = []
    signing_calls = []
    monkeypatch.setattr(app_module, "labor_postgres_state_enabled", lambda: True)
    monkeypatch.setattr(
        app_module,
        "create_pending_labor_file_states",
        lambda **kwargs: pending_batches.append(kwargs) or [],
        raising=False,
    )

    def sign(object_key, **_kwargs):
        signing_calls.append(object_key)
        if len(signing_calls) == 2:
            raise RuntimeError("private storage unavailable")
        return {
            "signedUrl": "https://project.supabase.co/upload?token=short",
            "method": "PUT",
            "headers": {},
            "objectKey": object_key,
            "expiresIn": 7200,
            "private": True,
        }

    monkeypatch.setattr(app_module, "create_labor_supabase_signed_upload_for_object", sign, raising=False)

    with TestClient(app) as client:
        _login(client)
        run = _create_run(client)
        response = client.post(
            f"/api/labor/runs/{run['id']}/upload-intents",
            headers=_headers(client),
            json={
                "files": [
                    {
                        "filename": "invoice-1.pdf",
                        "fileKind": "pdf_invoice",
                        "contentType": "application/pdf",
                        "sizeBytes": 1024,
                        "sha256": "a" * 64,
                    },
                    {
                        "filename": "invoice-2.pdf",
                        "fileKind": "pdf_invoice",
                        "contentType": "application/pdf",
                        "sizeBytes": 1024,
                        "sha256": "b" * 64,
                    },
                ]
            },
        )

    assert response.status_code == 503
    assert len(signing_calls) == 2
    assert pending_batches == []


def test_p1_upload_intents_log_sanitized_state_failure_diagnostics(p1_upload_env, monkeypatch, caplog):
    class DatabaseConstraintError(RuntimeError):
        sqlstate = "23514"

        class diag:
            table_name = "labor_run_files"
            constraint_name = "labor_run_files_state_check"

    monkeypatch.setattr(app_module, "labor_postgres_state_enabled", lambda: True)
    monkeypatch.setattr(
        app_module,
        "create_labor_supabase_signed_upload_for_object",
        lambda object_key, **_kwargs: {
            "signedUrl": "https://project.supabase.co/upload?token=short",
            "method": "PUT",
            "headers": {},
            "objectKey": object_key,
            "expiresIn": 7200,
            "private": True,
        },
        raising=False,
    )

    def fail_state_write(**_kwargs):
        raise DatabaseConstraintError("sensitive database detail")

    monkeypatch.setattr(app_module, "create_pending_labor_file_states", fail_state_write, raising=False)

    with TestClient(app) as client:
        _login(client)
        run = _create_run(client)
        with caplog.at_level("ERROR", logger="bonus_platform.labor"):
            response = client.post(
                f"/api/labor/runs/{run['id']}/upload-intents",
                headers=_headers(client),
                json={
                    "files": [
                        {
                            "filename": "invoice.pdf",
                            "fileKind": "pdf_invoice",
                            "contentType": "application/pdf",
                            "sizeBytes": 1024,
                            "sha256": "a" * 64,
                        }
                    ]
                },
            )

    assert response.status_code == 503
    assert response.json()["detail"]["errorCode"] == "LABOR_P1_STATE_UNAVAILABLE"
    assert "error_type=DatabaseConstraintError" in caplog.text
    assert "sqlstate=23514" in caplog.text
    assert "constraint=labor_run_files_state_check" in caplog.text
    assert "sensitive database detail" not in caplog.text


def test_p1_finalize_and_signed_download_use_manifest_not_client_object_path(p1_upload_env, monkeypatch):
    file_state = {
        "id": "file-1",
        "runId": "labor-1",
        "ownerUserId": "overseasAdminUser",
        "fileKind": "pdf_invoice",
        "objectKey": "labor-runs/uat/owners/overseasAdminUser/runs/labor-1/inputs/file-1/invoice.pdf",
        "originalFilename": "invoice.pdf",
        "contentType": "application/pdf",
        "sizeBytes": 1024,
        "sha256": "a" * 64,
        "uploadState": "pending",
    }
    finalized = []
    monkeypatch.setattr(app_module, "labor_postgres_state_enabled", lambda: True)
    monkeypatch.setattr(app_module, "get_labor_file_state", lambda **_kwargs: dict(file_state), raising=False)
    monkeypatch.setattr(
        app_module,
        "labor_supabase_object_metadata",
        lambda object_key: {"objectKey": object_key, "sizeBytes": 1024, "contentType": "application/pdf"},
        raising=False,
    )
    monkeypatch.setattr(
        app_module,
        "finalize_labor_file_state",
        lambda **kwargs: finalized.append(kwargs) or {**file_state, "uploadState": "ready"},
        raising=False,
    )
    monkeypatch.setattr(
        app_module,
        "create_labor_supabase_signed_download",
        lambda object_key, **_kwargs: {
            "signedUrl": f"https://project.supabase.co/download?key={object_key[-8:]}",
            "expiresIn": 120,
            "private": True,
            "filename": "invoice.pdf",
        },
    )

    with TestClient(app) as client:
        _login(client)
        run = _create_run(client)
        file_state["runId"] = run["id"]
        file_state["objectKey"] = file_state["objectKey"].replace("labor-1", run["id"])
        finalized_response = client.post(
            f"/api/labor/runs/{run['id']}/upload-intents/file-1/finalize",
            headers=_headers(client),
            json={"sha256": "a" * 64, "objectKey": "attacker/controlled/path"},
        )
        file_state["uploadState"] = "ready"
        download_response = client.get(
            f"/api/labor/runs/{run['id']}/files/file-1/signed-download"
        )

    assert finalized_response.status_code == 200
    assert finalized[0]["observed_size_bytes"] == 1024
    assert finalized[0]["reported_sha256"] == "a" * 64
    assert download_response.status_code == 200
    assert download_response.json()["private"] is True
    assert "attacker" not in download_response.json()["signedUrl"]


def test_p1_batch_finalize_checks_objects_and_commits_manifest_once(p1_upload_env, monkeypatch):
    file_states = [
        {
            "id": "file-pdf",
            "runId": "labor-1",
            "ownerUserId": "overseasAdminUser",
            "fileKind": "pdf_invoice",
            "objectKey": "labor-runs/production/owners/overseasAdminUser/runs/labor-1/inputs/file-pdf/invoice.pdf",
            "originalFilename": "invoice.pdf",
            "contentType": "application/pdf",
            "sizeBytes": 1024,
            "sha256": "a" * 64,
            "uploadState": "pending",
        },
        {
            "id": "file-xlsx",
            "runId": "labor-1",
            "ownerUserId": "overseasAdminUser",
            "fileKind": "workbook",
            "objectKey": "labor-runs/production/owners/overseasAdminUser/runs/labor-1/inputs/file-xlsx/bill.xlsx",
            "originalFilename": "bill.xlsx",
            "contentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "sizeBytes": 2048,
            "sha256": "b" * 64,
            "uploadState": "pending",
        },
    ]
    finalized_batches = []
    monkeypatch.setattr(app_module, "labor_postgres_state_enabled", lambda: True)
    monkeypatch.setattr(
        app_module,
        "list_labor_file_states",
        lambda **_kwargs: [dict(item) for item in file_states],
    )
    monkeypatch.setattr(
        app_module,
        "labor_supabase_object_metadata",
        lambda object_key: {
            "objectKey": object_key,
            "sizeBytes": 1024 if object_key.endswith("invoice.pdf") else 2048,
            "contentType": (
                "application/pdf"
                if object_key.endswith("invoice.pdf")
                else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
        },
    )
    monkeypatch.setattr(
        app_module,
        "finalize_labor_file_states",
        lambda **kwargs: finalized_batches.append(kwargs) or [
            {**item, "uploadState": "ready"} for item in file_states
        ],
        raising=False,
    )

    with TestClient(app) as client:
        _login(client)
        run = _create_run(client)
        for item in file_states:
            item["runId"] = run["id"]
            item["objectKey"] = item["objectKey"].replace("labor-1", run["id"])
        response = client.post(
            f"/api/labor/runs/{run['id']}/upload-intents/batch-finalize",
            headers=_headers(client),
            json={"fileIds": ["file-pdf", "file-xlsx"]},
        )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["files"]] == ["file-pdf", "file-xlsx"]
    assert len(finalized_batches) == 1
    assert [item["file_id"] for item in finalized_batches[0]["files"]] == [
        "file-pdf",
        "file-xlsx",
    ]


def test_p1_rejects_legacy_multipart_upload_even_when_readiness_is_green(p1_upload_env, monkeypatch):
    monkeypatch.setenv("SIGMA_LABOR_P1_REQUIRED", "1")
    monkeypatch.setattr(
        app_module,
        "_labor_p1_readiness_snapshot",
        lambda: {"p1": {"ready": True}, "blockers": []},
    )

    with TestClient(app) as client:
        _login(client)
        run = _create_run(client)
        response = client.post(
            f"/api/labor/runs/{run['id']}/files",
            headers=_headers(client),
        )

    assert response.status_code == 409
    assert response.json()["detail"]["errorCode"] == "LABOR_P1_SIGNED_UPLOAD_REQUIRED"
