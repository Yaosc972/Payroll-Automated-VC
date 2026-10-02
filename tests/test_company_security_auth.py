from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
import pytest

from bonus_platform import auth


DEPLOYMENT_KEYS = (
    "SIGMA_RUNTIME_MODE", "SIGMA_WORKBENCH_PUBLIC_URL", "VERCEL", "VERCEL_ENV",
    "VERCEL_URL", "AIDEPLOY_ENV", "AIDEPLOY_APP", "AIDEPLOY_SERVICE",
    "AIDEPLOY_RELEASE_SEQ", "AIDEPLOY_URL", "SIGMA_LABOR_AUTH_REQUIRED",
    "SIGMA_ENABLE_MOCK_LOGIN", "SIGMA_CORS_ALLOWED_ORIGINS", "FEISHU_REDIRECT_URI",
)


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for key in DEPLOYMENT_KEYS:
        monkeypatch.delenv(key, raising=False)


@pytest.mark.parametrize("key,value", [
    ("SIGMA_RUNTIME_MODE", "server"), ("SIGMA_RUNTIME_MODE", "production"),
    ("AIDEPLOY_ENV", "production"), ("AIDEPLOY_ENV", "preview"),
    ("AIDEPLOY_SERVICE", "payroll-automated-vc"), ("VERCEL_ENV", "preview"),
    ("SIGMA_WORKBENCH_PUBLIC_URL", "https://hras-ai-vc.ztn.cn"),
])
def test_hosted_auth_cannot_be_disabled_by_local_development_flags(monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    monkeypatch.setenv("SIGMA_LABOR_AUTH_REQUIRED", "false")
    monkeypatch.setenv("SIGMA_ENABLE_MOCK_LOGIN", "true")
    assert auth.production_runtime()
    assert auth.labor_auth_required()
    assert not auth.mock_auth_enabled()
    assert auth.session_cookie_secure()


def test_explicit_local_development_can_use_mock_login(monkeypatch):
    monkeypatch.setenv("SIGMA_WORKBENCH_PUBLIC_URL", "http://localhost:8006")
    monkeypatch.setenv("SIGMA_LABOR_AUTH_REQUIRED", "false")
    monkeypatch.setenv("SIGMA_ENABLE_MOCK_LOGIN", "true")
    assert not auth.production_runtime()
    assert not auth.labor_auth_required()
    assert auth.mock_auth_enabled()


@pytest.fixture
def company_session_client(tmp_path, monkeypatch):
    import bonus_platform.app as platform
    import bonus_platform.engine.admin_store as admin_store

    monkeypatch.setenv("SIGMA_RUNTIME_MODE", "server")
    monkeypatch.setenv("SIGMA_LABOR_AUTH_REQUIRED", "false")
    monkeypatch.setenv("SIGMA_ENABLE_MOCK_LOGIN", "true")
    monkeypatch.setattr(admin_store, "get_admin_db_path", lambda: tmp_path / "auth.sqlite")
    monkeypatch.setattr(admin_store, "get_admin_database_url", lambda: "")
    monkeypatch.setattr(admin_store, "_STORE_INITIALIZED", False)
    monkeypatch.setattr(admin_store, "_STORE_INITIALIZED_TARGET", "")
    monkeypatch.setattr(platform, "CHINA_EMPLOYEE_PAYROLL_RUNS_DIR", tmp_path / "meal")
    monkeypatch.setattr(platform, "company_run_storage_enabled", lambda _: False)
    platform._clear_current_user_cache()
    admin_store.init_admin_store()
    # HTTPS matches production Secure cookies; omit lifespan to avoid schedulers.
    client = TestClient(platform.app, base_url="https://security.test")
    yield client, admin_store
    client.close()
    platform._clear_current_user_cache()


def test_company_meal_uses_real_session_and_rejects_revocation_after_permission_cache(company_session_client):
    client, store = company_session_client
    path = "/api/china-employee-payroll/meal-allowance/runs"
    client.cookies.set("sigma_session", "synthetic-forged-session")
    assert client.get(path).status_code == 401
    token = store.create_session("cnPayrollAdminUser", action="isolated_security_test")
    client.cookies.set("sigma_session", token)
    assert client.get(path).json() == {"runs": []}
    assert client.get(path).status_code == 200
    store.delete_session(token)
    assert client.get(path).status_code == 401


def test_company_meal_module_permissions_follow_real_role_changes(company_session_client):
    client, store = company_session_client
    path = "/api/china-employee-payroll/meal-allowance/runs"
    client.cookies.set("sigma_session", store.create_session("recruitmentAdminUser"))
    assert client.get(path).status_code == 403
    client.cookies.set("sigma_session", store.create_session("cnPayrollAdminUser"))
    assert client.get(path).status_code == 200
    store.set_user_roles("cnPayrollAdminUser", [])
    assert client.get(path).status_code == 403


def test_company_mock_endpoints_stay_closed_even_with_legacy_enable_flag(company_session_client):
    client, _ = company_session_client
    assert client.get("/api/auth/mock-users").status_code == 404
    assert client.post("/api/auth/mock-login", json={"userId": "payrollAdmin"}).status_code == 404
    assert client.get("/api/auth/feishu/config").json()["mockLoginEnabled"] is False


def test_company_auth_readiness_accepts_ready_mysql_sessions(monkeypatch):
    monkeypatch.setattr(auth, "admin_store_health", lambda: {"backend": "mysql", "ready": True})
    result = auth.labor_auth_health({
        "SIGMA_RUNTIME_MODE": "server", "FEISHU_APP_ID": "test-app",
        "FEISHU_APP_SECRET": "synthetic-test-secret", "FEISHU_REDIRECT_URI": "https://hras-ai-vc.ztn.cn/api/auth/feishu/callback",
    })
    assert result["ready"]
    assert result["databaseBackend"] == "mysql"


@pytest.mark.parametrize("target", [
    "//evil.example", "///evil.example", "/\\evil.example", "\\evil.example",
    "https://evil.example", "javascript:alert(1)", "/%2fevil.example",
    "/%252fevil.example", "/%5cevil.example", "/%255cevil.example",
    "/\r\nevil.example", "/%0devil.example", "/%250aevil.example",
    "\t//evil.example", "login.html.evil.example", "/" + "a" * 2048,
])
def test_return_url_rejects_external_and_browser_normalized_destinations(target):
    assert auth._safe_next_url(target, "/login.html") == "/login.html"


@pytest.mark.parametrize("target,expected", [
    ("/", "/"), ("/overseas-labor.html#run=demo", "/overseas-labor.html#run=demo"),
    ("/login.html?next=%2Fdomestic-labor.html", "/login.html?next=%2Fdomestic-labor.html"),
    ("login.html?next=%2F", "/login.html?next=%2F"),
    ("/china-employee-payroll.html?month=2026-09", "/china-employee-payroll.html?month=2026-09"),
])
def test_return_url_keeps_normal_workbench_navigation(target, expected):
    assert auth._safe_next_url(target) == expected


def test_cors_rejects_untrusted_browsers_but_preserves_trusted_upload_and_download():
    settings = auth.cors_settings({
        "SIGMA_RUNTIME_MODE": "server",
        "SIGMA_CORS_ALLOWED_ORIGINS": "https://hras-ai-vc.ztn.cn,*,null,http://localhost:8006",
    })
    app = FastAPI()
    app.add_middleware(CORSMiddleware, **settings)

    @app.get("/download")
    def download():
        return {"status": "ok"}

    with TestClient(app) as client:
        preflight = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type,x-sigma-labor-ui-build"}
        good = client.options("/download", headers={**preflight, "Origin": "https://hras-ai-vc.ztn.cn"})
        assert good.status_code == 200
        assert good.headers["access-control-allow-origin"] == "https://hras-ai-vc.ztn.cn"
        assert good.headers["access-control-allow-credentials"] == "true"
        for origin in ("https://evil.example", "null", "http://localhost:8006"):
            bad = client.options("/download", headers={**preflight, "Origin": origin})
            assert bad.status_code == 400
            assert "access-control-allow-origin" not in bad.headers
            actual = client.get("/download", headers={"Origin": origin})
            assert "access-control-allow-origin" not in actual.headers
        unexpected_header = client.options("/download", headers={
            **preflight, "Origin": "https://hras-ai-vc.ztn.cn", "Access-Control-Request-Headers": "x-spoofed-role",
        })
        assert unexpected_header.status_code == 400


def test_hosted_cors_without_origin_configuration_still_allows_same_origin_only():
    assert auth.cors_settings({"SIGMA_RUNTIME_MODE": "server"})["allow_origins"] == []


def test_local_file_preview_cors_remains_available():
    assert auth.cors_settings({})["allow_origins"] == ["null", "http://127.0.0.1:8006", "http://localhost:8006"]
