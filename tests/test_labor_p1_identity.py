import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

import bonus_platform.app as app_module
import bonus_platform.engine.admin_store as admin_store
import bonus_platform.engine.labor.runs as labor_runs
from bonus_platform.app import app


@pytest.fixture
def p1_identity_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SIGMA_LABOR_AUTH_REQUIRED", "1")
    monkeypatch.setenv("SIGMA_ENABLE_MOCK_LOGIN", "1")
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("VERCEL_ENV", raising=False)
    monkeypatch.delenv("VERCEL_URL", raising=False)
    monkeypatch.setattr(admin_store, "get_admin_db_path", lambda: tmp_path / "admin.sqlite")
    monkeypatch.setattr(admin_store, "get_admin_database_url", lambda: "")
    monkeypatch.setattr(labor_runs, "LABOR_RUNS_DIR", tmp_path / "labor_runs")
    monkeypatch.setattr(app_module, "LABOR_RUNS_DIR", tmp_path / "labor_runs")
    monkeypatch.setattr(app_module, "_labor_audit_path", lambda: tmp_path / "labor_audit.jsonl")
    admin_store._STORE_INITIALIZED = False
    admin_store._STORE_INITIALIZED_TARGET = ""
    return tmp_path


def _labor_headers(client: TestClient) -> dict[str, str]:
    access = client.get("/api/labor/access").json()
    return {
        "x-sigma-labor-api-contract": str(access["apiContractVersion"]),
        "x-sigma-labor-ui-version": str(access["version"]),
        "x-sigma-labor-ui-build": str(access["buildId"]),
    }


def _login(client: TestClient, user_id: str) -> None:
    response = client.post("/api/auth/mock-login", json={"userId": user_id})
    assert response.status_code == 200


def test_labor_p1_requires_authenticated_session(p1_identity_env):
    with TestClient(app) as client:
        response = client.get("/api/labor/runs")

    assert response.status_code == 401
    assert response.json()["detail"]["errorCode"] == "LABOR_AUTH_REQUIRED"


def test_labor_p1_rejects_authenticated_user_without_overseas_role(p1_identity_env):
    with TestClient(app) as client:
        _login(client, "recruitmentAdminUser")
        response = client.get("/api/labor/runs")

    assert response.status_code == 403
    assert response.json()["detail"]["errorCode"] == "LABOR_MODULE_FORBIDDEN"


def test_labor_p1_binds_owner_to_session_and_hides_cross_owner_run(p1_identity_env):
    admin_store.init_admin_store()
    second_user = admin_store.upsert_feishu_user(
        feishu_open_id="ou_second_overseas",
        name="Second Overseas Auditor",
    )
    admin_store.set_user_roles(second_user["id"], ["overseasAdmin"])

    with TestClient(app) as client:
        _login(client, "overseasAdminUser")
        created = client.post(
            "/api/labor/runs",
            headers=_labor_headers(client),
            json={
                "supplierName": "P1 Owner Supplier",
                "periodStart": "2026-07-01",
                "periodEnd": "2026-07-07",
                "ownerUserId": second_user["id"],
            },
        )
        assert created.status_code == 200
        run = created.json()

        client.post("/api/auth/logout")
        _login(client, second_user["id"])
        hidden_get = client.get(f"/api/labor/runs/{run['id']}")
        hidden_list = client.get("/api/labor/runs")

    assert run["ownerUserId"] == "overseasAdminUser"
    assert hidden_get.status_code == 404
    assert hidden_list.status_code == 200
    assert hidden_list.json()["runs"] == []


def test_labor_p1_system_admin_can_access_owned_run(p1_identity_env):
    with TestClient(app) as client:
        _login(client, "overseasAdminUser")
        created = client.post(
            "/api/labor/runs",
            headers=_labor_headers(client),
            json={
                "supplierName": "P1 Admin Visibility",
                "periodStart": "2026-07-08",
                "periodEnd": "2026-07-14",
            },
        )
        assert created.status_code == 200

        client.post("/api/auth/logout")
        _login(client, "payrollAdmin")
        response = client.get(f"/api/labor/runs/{created.json()['id']}")

    assert response.status_code == 200
    assert response.json()["ownerUserId"] == "overseasAdminUser"


def test_labor_p1_hides_cross_owner_mutation_and_audit_events(p1_identity_env):
    admin_store.init_admin_store()
    second_user = admin_store.upsert_feishu_user(
        feishu_open_id="ou_second_auditor",
        name="Second Overseas Auditor",
    )
    admin_store.set_user_roles(second_user["id"], ["overseasAdmin"])

    with TestClient(app) as client:
        _login(client, "overseasAdminUser")
        created = client.post(
            "/api/labor/runs",
            headers=_labor_headers(client),
            json={
                "supplierName": "Private Owner Supplier",
                "periodStart": "2026-07-01",
                "periodEnd": "2026-07-07",
            },
        )
        assert created.status_code == 200
        run_id = created.json()["id"]

        client.post("/api/auth/logout")
        _login(client, second_user["id"])
        hidden_delete = client.delete(
            f"/api/labor/runs/{run_id}",
            headers=_labor_headers(client),
        )
        audit = client.get("/api/labor/audit")

    assert hidden_delete.status_code == 404
    assert audit.status_code == 200
    assert all(event.get("ownerUserId") == second_user["id"] for event in audit.json()["events"])


def test_labor_p1_cross_owner_file_routes_fail_before_storage_side_effects(
    p1_identity_env,
    monkeypatch,
):
    admin_store.init_admin_store()
    second_user = admin_store.upsert_feishu_user(
        feishu_open_id="ou_cross_owner_files",
        name="Cross Owner File Auditor",
    )
    admin_store.set_user_roles(second_user["id"], ["overseasAdmin"])
    storage_calls = []
    monkeypatch.setattr(
        app_module,
        "create_labor_supabase_signed_upload_for_object",
        lambda *_args, **_kwargs: storage_calls.append("sign-upload") or {},
    )
    monkeypatch.setattr(
        app_module,
        "get_labor_file_state",
        lambda **_kwargs: storage_calls.append("read-file-state") or {},
    )
    monkeypatch.setattr(
        app_module,
        "create_labor_supabase_signed_download",
        lambda *_args, **_kwargs: storage_calls.append("sign-download") or {},
    )

    with TestClient(app) as client:
        _login(client, "overseasAdminUser")
        created = client.post(
            "/api/labor/runs",
            headers=_labor_headers(client),
            json={
                "supplierName": "Private File Supplier",
                "periodStart": "2026-07-01",
                "periodEnd": "2026-07-07",
            },
        )
        assert created.status_code == 200
        run_id = created.json()["id"]

        client.post("/api/auth/logout")
        _login(client, second_user["id"])
        headers = _labor_headers(client)
        responses = [
            client.post(
                f"/api/labor/runs/{run_id}/upload-intents",
                headers=headers,
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
            ),
            client.post(
                f"/api/labor/runs/{run_id}/upload-intents/file-1/finalize",
                headers=headers,
                json={"sha256": "a" * 64},
            ),
            client.get(f"/api/labor/runs/{run_id}/files/file-1/signed-download"),
            client.get(f"/api/labor/runs/{run_id}/download/report.xlsx"),
        ]

    assert [response.status_code for response in responses] == [404, 404, 404, 404]
    assert all(
        response.json()["detail"]["errorCode"] == "LABOR_RUN_NOT_FOUND"
        for response in responses
    )
    assert storage_calls == []


def test_labor_p1_supplier_history_is_scoped_to_owner(p1_identity_env):
    admin_store.init_admin_store()
    second_user = admin_store.upsert_feishu_user(
        feishu_open_id="ou_supplier_auditor",
        name="Supplier Scope Auditor",
    )
    admin_store.set_user_roles(second_user["id"], ["overseasAdmin"])

    with TestClient(app) as client:
        _login(client, "overseasAdminUser")
        created = client.post(
            "/api/labor/runs",
            headers=_labor_headers(client),
            json={
                "supplierName": "Owner Secret Supplier",
                "periodStart": "2026-07-01",
                "periodEnd": "2026-07-07",
            },
        )
        assert created.status_code == 200

        client.post("/api/auth/logout")
        _login(client, second_user["id"])
        response = client.get("/api/labor/suppliers")

    assert response.status_code == 200
    names = {row["name"] for row in response.json()["suppliers"]}
    assert "Owner Secret Supplier" not in names


def test_labor_p1_material_run_owner_comes_from_session(p1_identity_env, monkeypatch):
    root = p1_identity_env / "materials"
    root.mkdir()
    monkeypatch.setattr(
        app_module,
        "build_material_replay_plan",
        lambda *_args, **_kwargs: {
            "root": str(root),
            "plans": [
                {
                    "batchKey": "fixture-batch",
                    "directory": "fixture-batch",
                    "supplier": "Fixture Supplier",
                    "mappingCandidates": [],
                    "expectedRisks": [],
                    "uploadPlan": {},
                }
            ],
        },
    )
    monkeypatch.setattr(app_module, "_copy_material_plan_files", lambda *_args: ({}, []))

    with TestClient(app) as client:
        _login(client, "overseasAdminUser")
        response = client.post(
            "/api/labor/material-runs",
            headers=_labor_headers(client),
            json={
                "root": str(root),
                "batchKey": "fixture-batch",
                "ownerUserId": "payrollAdmin",
            },
        )

    assert response.status_code == 200
    assert response.json()["ownerUserId"] == "overseasAdminUser"


def test_workbench_exposes_auth_requirement_and_home_uses_real_session(p1_identity_env):
    index_html = (app_module.STATIC_DIR / "index.html").read_text(encoding="utf-8")

    with TestClient(app) as client:
        access = client.get("/api/workbench/access")

    assert access.status_code == 200
    assert access.json()["authRequired"] is True
    assert 'id="dashboardCurrentUser"' in index_html
    assert 'id="dashboardLogout"' in index_html
    assert "fetch('/api/me'" in index_html or 'fetch("/api/me"' in index_html

    with TestClient(app, follow_redirects=False) as client:
        anonymous_home = client.get("/")
        _login(client, "overseasAdminUser")
        authenticated_home = client.get("/")

    assert anonymous_home.status_code == 302
    assert anonymous_home.headers["location"].startswith("/login.html?next=")
    assert authenticated_home.status_code == 200


def test_authenticated_governance_actor_ignores_client_supplied_name(monkeypatch):
    monkeypatch.setattr(app_module, "labor_auth_required", lambda: True)
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    request.state.labor_current_user = {
        "user": {"id": "trusted-reviewer"},
        "roles": ["overseasAdmin"],
    }

    actor = app_module._labor_action_actor(
        request,
        {"confirmedBy": "attacker", "appliedBy": "attacker"},
        "confirmedBy",
        "appliedBy",
    )

    assert actor == "trusted-reviewer"


def test_business_review_is_bound_to_logged_in_reviewer(p1_identity_env, monkeypatch):
    metadata = {
        "id": "labor-review-1",
        "ownerUserId": "overseasAdminUser",
        "status": "已完成",
        "resultInputFingerprint": "a" * 64,
        "businessReviewStatus": "pending",
        "machineCheckStatus": "needs_review",
    }
    captured = []
    monkeypatch.setattr(app_module, "_labor_metadata_or_404", lambda _run_id: dict(metadata))
    monkeypatch.setattr(app_module, "_labor_result_input_fingerprint", lambda _row: "a" * 64)
    monkeypatch.setattr(
        app_module,
        "update_labor_metadata",
        lambda run_id, updates, **kwargs: captured.append((run_id, updates, kwargs)) or {**metadata, **updates},
    )

    with TestClient(app) as client:
        _login(client, "overseasAdminUser")
        response = client.post(
            "/api/labor/runs/labor-review-1/business-review",
            headers=_labor_headers(client),
            json={"decision": "approved", "reason": "逐项复核完成", "reviewedBy": "attacker"},
        )

    assert response.status_code == 200
    assert captured[0][1]["businessReviewedBy"] == "overseasAdminUser"
    assert captured[0][2]["actor_user_id"] == "overseasAdminUser"
    assert response.json()["directPaymentAllowed"] is False
