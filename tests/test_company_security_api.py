"""Production security regressions with isolated data, real sessions and service tokens."""

import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import bonus_platform.app as platform
import bonus_platform.engine.admin_store as admin_store
import bonus_platform.engine.labor.runs as labor_runs
import bonus_platform.engine.labor.worker_jobs as worker_jobs
import bonus_platform.engine.social_insurance.router as social_router
from bonus_platform.engine.labor.materials import build_material_index


@pytest.fixture
def secured_company(tmp_path, monkeypatch):
    monkeypatch.setattr(platform, "production_runtime", lambda: True, raising=False)
    # Company production must stay protected even if a legacy switch is false.
    monkeypatch.setattr(platform, "labor_auth_required", lambda: False)
    monkeypatch.setattr(platform, "_uses_request_scoped_labor_runtime", lambda: False)
    monkeypatch.setattr(platform, "CHINA_EMPLOYEE_PAYROLL_RUNS_DIR", tmp_path / "meal")
    monkeypatch.setattr(platform, "LABOR_RUNS_DIR", tmp_path / "labor")
    monkeypatch.setattr(labor_runs, "LABOR_RUNS_DIR", tmp_path / "labor")
    monkeypatch.setattr(platform, "company_run_storage_enabled", lambda _key: False)
    monkeypatch.setattr(platform, "list_run_metadata", lambda: [])
    monkeypatch.setattr(platform, "_labor_build_snapshot", lambda: {
        "schemaVersion": 1, "status": "current", "buildId": "security-test",
        "moduleVersion": platform.OVERSEAS_LABOR_MODULE_VERSION,
        "apiContractVersion": platform.OVERSEAS_LABOR_API_CONTRACT_VERSION,
    })
    monkeypatch.setattr(platform, "_load_persisted_labor_worker_release_manifest", lambda: {})
    monkeypatch.setattr(platform, "_labor_current_user_from_request", lambda request: None)
    monkeypatch.setenv("SIGMA_OVERSEAS_LABOR_ACCESS", "production")
    monkeypatch.delenv("SIGMA_LABOR_OPERATIONS_TOKEN", raising=False)
    monkeypatch.delenv("LABOR_REFERENCE_MATERIALS_DIR", raising=False)
    # No lifespan context: do not start schedulers or clean any existing runs.
    return TestClient(platform.app)


def identity(monkeypatch, modules=("overseas",), *, admin=False):
    current = {
        "user": {"id": "security-user", "status": "active"},
        "roles": [{"id": "admin"}] if admin else [{"id": "overseasAdmin"}],
        "modules": [{"id": m, "enabled": True, "canEnter": True} for m in modules],
    }

    def resolve(request):
        request.state.labor_auth_resolved = True
        request.state.labor_current_user = current
        return current

    monkeypatch.setattr(platform, "_labor_current_user_from_request", resolve)
    return current


@pytest.mark.parametrize(("method", "url"), [
    ("GET", "/api/china-employee-payroll/meal-allowance/runs"),
    ("GET", "/api/china-employee-payroll/meal-allowance/runs/china_employee_payroll_1"),
    ("GET", "/api/china-employee-payroll/meal-allowance/china_employee_payroll_1/export"),
    ("POST", "/api/china-employee-payroll/meal-allowance"),
    ("GET", "/api/runs"), ("GET", "/api/runs/synthetic"),
    ("POST", "/api/calculate"), ("POST", "/api/runs/calculate"),
    ("POST", "/api/finalize"), ("GET", "/api/template"),
    ("GET", "/api/download/synthetic.xlsx"),
    ("GET", "/api/labor/access"), ("GET", "/api/labor/storage-info"),
    ("GET", "/api/labor/storage-health"), ("GET", "/api/labor/worker-health"),
    ("GET", "/api/labor/audit"), ("GET", "/api/labor/runs"),
    ("POST", "/api/labor/runs"), ("GET", "/api/labor/material-index?root=/app"),
    ("GET", "/api/labor/material-replay-plan?root=/app"),
    ("POST", "/api/labor/material-dry-run"), ("POST", "/api/labor/material-runs"),
    ("POST", "/api/labor/telemetry"), ("GET", "/api/labor/telemetry/export"),
    ("GET", "/api/labor/worker/release"),
    ("GET", "/api/labor/worker/release/download"),
    ("POST", "/api/labor/worker/release/finalize"),
    ("PUT", "/api/labor/worker/release/local-upload"),
    ("GET", "/api/labor/worker/unknown"),
    ("GET", "/api/overseas-payroll/worker/unknown"),
])
def test_company_anonymous_business_requests_fail_before_business_processing(secured_company, method, url):
    response = secured_company.request(method, url, json={})
    assert response.status_code == 401
    assert "/Users/" not in response.text and "/app" not in response.text


def test_replaying_exact_client_contract_does_not_authorize_anonymous_user(secured_company):
    response = secured_company.post("/api/labor/runs", json={}, headers={
        "X-Sigma-Labor-API-Contract": str(platform.OVERSEAS_LABOR_API_CONTRACT_VERSION),
        "X-Sigma-Labor-UI-Version": platform.OVERSEAS_LABOR_MODULE_VERSION,
        "X-Sigma-Labor-UI-Build": "security-test",
    })
    assert response.status_code == 401


def test_employee_role_required_and_authorized_list_preserved(secured_company, monkeypatch):
    identity(monkeypatch)
    assert secured_company.get("/api/china-employee-payroll/meal-allowance/runs").status_code == 403
    identity(monkeypatch, ("employee",))
    response = secured_company.get("/api/china-employee-payroll/meal-allowance/runs")
    assert response.status_code == 200 and response.json() == {"runs": []}


def test_business_storage_summary_hides_paths_without_breaking_limits(secured_company, monkeypatch):
    identity(monkeypatch)
    response = secured_company.get("/api/labor/storage-info")
    assert response.status_code == 200
    assert response.json()["limits"]["maxPdfFiles"] > 0
    assert response.json()["storageBackend"] in {"local", "obs", "blob", "supabase"}
    assert "storageEnvironment" in response.json()
    assert isinstance(response.json()["persistentStorageEnabled"], bool)
    assert "paths" not in response.json()
    assert "bucket" not in response.json()


@pytest.mark.parametrize("path", ["storage-health", "worker-health", "telemetry/export"])
def test_operational_details_are_not_available_to_module_user(secured_company, monkeypatch, path):
    identity(monkeypatch)
    assert secured_company.get(f"/api/labor/{path}").status_code == 403


def test_access_ops_probe_uses_existing_service_token_and_rejects_empty_token(secured_company, monkeypatch):
    assert secured_company.get("/api/labor/access", headers={"X-Admin-Token": "probe"}).status_code == 401
    monkeypatch.setenv("SIGMA_LABOR_OPERATIONS_TOKEN", "probe")
    response = secured_company.get("/api/labor/access", headers={"X-Admin-Token": "probe"})
    assert response.status_code == 200 and "apiContractVersion" in response.json()


@pytest.mark.parametrize("root", ["/app", ".", "..", "../outside", "\\\\server\\share", "/tmp"])
def test_material_root_cannot_choose_server_directories(secured_company, tmp_path, monkeypatch, root):
    identity(monkeypatch, admin=True)
    monkeypatch.setenv("LABOR_REFERENCE_MATERIALS_DIR", str(tmp_path / "allowed"))
    (tmp_path / "allowed").mkdir()
    for method, path in [("GET", "material-index"), ("GET", "material-replay-plan"),
                         ("POST", "material-dry-run"), ("POST", "material-runs")]:
        response = secured_company.request(method, f"/api/labor/{path}",
            params={"root": root} if method == "GET" else None,
            json={"root": root, "batchKey": "synthetic"} if method == "POST" else None)
        assert response.status_code == 400
        assert root not in response.json().get("detail", "")


def test_default_material_directory_and_relative_response_preserve_ui(secured_company, tmp_path, monkeypatch):
    identity(monkeypatch, admin=True)
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    (allowed / "invoice.pdf").write_bytes(b"%PDF-1.4\n")
    monkeypatch.setenv("LABOR_REFERENCE_MATERIALS_DIR", str(allowed))
    response = secured_company.get("/api/labor/material-index")
    assert response.status_code == 200
    assert str(tmp_path) not in json.dumps(response.json())
    assert response.json()["files"][0]["path"] == "invoice.pdf"


@pytest.mark.parametrize(("method", "path"), [
    ("GET", "material-index"), ("GET", "material-replay-plan"),
    ("POST", "material-dry-run"), ("POST", "material-runs"),
])
def test_material_directory_fails_closed_when_server_configuration_is_missing(secured_company, monkeypatch, method, path):
    identity(monkeypatch, admin=True)
    response = secured_company.request(method, f"/api/labor/{path}", json={})
    assert response.status_code == 409
    assert "/Users/" not in response.text


def test_material_run_keeps_internal_paths_and_hides_them_on_reload(secured_company, tmp_path, monkeypatch):
    identity(monkeypatch, admin=True)
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setenv("LABOR_REFERENCE_MATERIALS_DIR", str(allowed))
    run = labor_runs.create_labor_run({
        "supplierName": "Isolated Material", "ownerUserId": "security-user",
        "periodStart": "2026-09-01", "periodEnd": "2026-09-07",
    })
    source = {"root": str(allowed), "batchKey": "synthetic", "copiedSources": [{"path": str(allowed / "invoice.pdf")}]}
    internal_path = str((tmp_path / "labor" / run["id"] / "invoice.pdf").resolve())
    labor_runs.update_labor_metadata(run["id"], {"materialReplaySource": source, "files": {"pdfInvoices": [{"path": internal_path}]}})
    response = secured_company.get(f"/api/labor/runs/{run['id']}")
    assert response.status_code == 200
    assert str(tmp_path) not in json.dumps(response.json())
    stored = labor_runs.load_labor_metadata(labor_runs.get_labor_run_dir(run["id"]))
    assert stored["files"]["pdfInvoices"][0]["path"] == internal_path


def test_download_rejects_symlink_and_stored_path_outside_run_directory(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    outside = tmp_path / "private.xlsx"
    outside.write_bytes(b"isolated private data")
    (run_dir / "link.xlsx").symlink_to(outside)
    for metadata, filename in [({}, "link.xlsx"), ({"files": {"workbook": {"path": str(outside), "filename": "private.xlsx"}}}, "private.xlsx")]:
        (run_dir / labor_runs.METADATA_FILE).write_text(json.dumps(metadata))
        with pytest.raises(HTTPException) as error:
            platform._resolve_labor_download_path(run_dir, filename)
        assert error.value.status_code == 400
        assert str(tmp_path) not in str(error.value.detail)


def test_download_skips_empty_path_and_retains_valid_batch_file_fallback(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    metadata_file = run_dir / labor_runs.METADATA_FILE
    metadata = {"files": {"diffReport": {"filename": "report.xlsx"}}}
    metadata_file.write_text(json.dumps(metadata))
    assert platform._resolve_labor_download_path(run_dir, "report.xlsx") == run_dir / "report.xlsx"
    actual = run_dir / "stored-report.xlsx"
    actual.write_bytes(b"isolated valid report")
    metadata["files"]["projectionReport"] = {"filename": "report.xlsx", "path": str(actual)}
    metadata_file.write_text(json.dumps(metadata))
    assert platform._resolve_labor_download_path(run_dir, "report.xlsx") == actual


def test_material_symlink_cannot_escape_approved_root(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("not a reference material")
    (allowed / "linked.txt").symlink_to(outside)
    assert build_material_index(allowed)["files"] == []


def test_production_health_and_documentation_reveal_no_runtime_metadata(secured_company):
    assert secured_company.get("/api/health").json() == {"status": "ok"}
    for path in ["/docs", "/redoc", "/openapi.json"]:
        assert secured_company.get(path).status_code == 404


def test_logout_rejects_protocol_relative_next(secured_company):
    response = secured_company.get("/api/auth/logout", params={"next": "//evil.invalid"}, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"].startswith("/login.html")


@pytest.fixture
def company_sessions(tmp_path, monkeypatch):
    """Use the actual DB session resolver in company mode, with no mock login."""
    monkeypatch.setenv("SIGMA_RUNTIME_MODE", "server")
    monkeypatch.setenv("SIGMA_LABOR_AUTH_REQUIRED", "false")
    monkeypatch.setenv("SIGMA_ENABLE_MOCK_LOGIN", "true")
    monkeypatch.setenv("SIGMA_OVERSEAS_LABOR_ACCESS", "production")
    monkeypatch.setenv("SIGMA_LABOR_P1_REQUIRED", "false")
    monkeypatch.setattr(admin_store, "get_admin_db_path", lambda: tmp_path / "admin.sqlite")
    monkeypatch.setattr(admin_store, "get_admin_database_url", lambda: "")
    monkeypatch.setattr(platform, "CHINA_EMPLOYEE_PAYROLL_RUNS_DIR", tmp_path / "meal")
    monkeypatch.setattr(platform, "LABOR_RUNS_DIR", tmp_path / "labor")
    monkeypatch.setattr(labor_runs, "LABOR_RUNS_DIR", tmp_path / "labor")
    monkeypatch.setattr(worker_jobs, "LABOR_WORKER_JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(platform, "_labor_audit_path", lambda: tmp_path / "audit.jsonl")
    monkeypatch.setattr(platform, "company_run_storage_enabled", lambda _key: False)
    monkeypatch.setattr(platform, "list_run_metadata", lambda: [])
    monkeypatch.setattr(platform, "_uses_request_scoped_labor_runtime", lambda: False)
    monkeypatch.setattr(platform, "_load_persisted_labor_worker_release_manifest", lambda: {})
    platform._clear_current_user_cache()
    admin_store.init_admin_store()
    client = TestClient(platform.app, base_url="https://company.test")

    def login(user_id):
        token = admin_store.create_session(user_id)
        client.cookies.set(platform.SESSION_COOKIE_NAME, token)
        return token

    yield client, login
    platform._clear_current_user_cache()


@pytest.mark.parametrize(("user_id", "path"), [
    ("recruitmentAdminUser", "/api/runs"),
    ("cnPayrollAdminUser", "/api/china-employee-payroll/meal-allowance/runs"),
    ("cnPayrollAdminUser", "/api/social-insurance/rules"),
    ("overseasAdminUser", "/api/labor/runs"),
    ("fbuAdminUser", "/api/overseas-payroll/tools"),
    ("fbuAdminUser", "/api/tools"),
])
def test_real_company_session_preserves_authorized_module_and_rejects_revocation(company_sessions, user_id, path):
    client, login = company_sessions
    token = login(user_id)
    assert client.get(path).status_code == 200
    admin_store.delete_session(token)
    assert client.get(path).status_code == 401


@pytest.mark.parametrize("path", [
    "/api/runs", "/api/china-employee-payroll/meal-allowance/runs",
    "/api/social-insurance/rules", "/api/labor/runs", "/api/overseas-payroll/tools",
])
def test_real_expired_cookie_fails_all_business_modules(company_sessions, path):
    client, login = company_sessions
    token = login("payrollAdmin")
    with admin_store._connect() as connection:
        connection.execute("UPDATE admin_sessions SET expires_at = ? WHERE token_hash = ?", ("2000-01-01T00:00:00", admin_store._hash_token(token)))
        connection.commit()
    assert client.get(path).status_code == 401


@pytest.mark.parametrize("path", [
    "/api/china-employee-payroll/meal-allowance/runs", "/api/social-insurance/rules",
    "/api/labor/runs", "/api/overseas-payroll/tools", "/api/tools",
])
def test_real_recruitment_role_cannot_read_other_modules(company_sessions, path):
    client, login = company_sessions
    login("recruitmentAdminUser")
    assert client.get(path).status_code == 403


def test_company_disables_mock_login_even_with_development_flag(company_sessions):
    client, _ = company_sessions
    assert client.post("/api/auth/mock-login", json={"userId": "payrollAdmin"}).status_code == 404


def test_real_sessions_enforce_run_ownership_before_read_mutation_and_download(company_sessions):
    client, login = company_sessions
    login("overseasAdminUser")
    response = client.post("/api/labor/runs", json={"supplierName": "Isolated Owner", "periodStart": "2026-09-01", "periodEnd": "2026-09-07"})
    assert response.status_code == 200
    run = response.json()
    second = admin_store.upsert_feishu_user(feishu_open_id="ou_isolated_second_owner", name="Second Owner")
    admin_store.set_user_roles(second["id"], ["overseasAdmin"])
    login(second["id"])
    for method, url in [("GET", f"/api/labor/runs/{run['id']}"), ("DELETE", f"/api/labor/runs/{run['id']}"), ("GET", f"/api/labor/runs/{run['id']}/download/private.xlsx")]:
        assert client.request(method, url).status_code == 404
    assert client.get("/api/labor/runs").json()["runs"] == []
    assert client.get("/api/labor/audit", params={"run_id": run["id"]}).json()["events"] == []


def test_worker_bearer_is_valid_only_for_exact_service_method_and_path(company_sessions, monkeypatch):
    client, _ = company_sessions
    monkeypatch.setenv("SIGMA_LABOR_WORKER_TOKENS", json.dumps({"isolated-worker": {"userId": "overseasAdminUser", "deviceId": "device-1"}}))
    headers = {"Authorization": "Bearer isolated-worker", "X-Worker-Version": platform.OVERSEAS_LABOR_REQUIRED_WORKER_VERSION}
    assert client.post("/api/labor/worker/jobs/claim").status_code == 401
    assert client.post("/api/labor/worker/jobs/claim", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.post("/api/labor/worker/jobs/claim", headers=headers).status_code == 200
    assert client.get("/api/labor/worker/version", headers=headers).status_code == 200
    for method, path in [("GET", "/api/labor/worker/jobs/claim"), ("POST", "/api/labor/worker/version"), ("GET", "/api/labor/worker/unknown"), ("GET", "/api/labor/runs"), ("POST", "/api/labor/worker/release/finalize"), ("GET", "/api/overseas-payroll/worker/unknown")]:
        assert client.request(method, path, headers=headers, json={}).status_code == 401


def test_cron_bearer_is_fail_closed_and_only_exact_refresh_get_is_exempt(company_sessions, monkeypatch):
    client, _ = company_sessions
    monkeypatch.delenv("CRON_SECRET", raising=False)
    path = "/api/social-insurance/cron/refresh"
    headers = {"Authorization": "Bearer isolated-cron"}
    assert client.get(path, headers=headers).status_code == 401
    monkeypatch.setenv("CRON_SECRET", "isolated-cron")
    monkeypatch.setattr(social_router, "refresh_latest_reporting_snapshot", lambda: {"subjects": ["A", "B"], "status": "complete"})
    assert client.get(path, headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get(path, headers=headers).json() == {"subjects": ["A", "B"], "status": "complete"}
    assert client.post(path, headers=headers).status_code == 401
    assert client.get("/api/social-insurance/rules", headers=headers).status_code == 401
