from fastapi.testclient import TestClient
import pytest

import bonus_platform.engine.admin_store as admin_store
import bonus_platform.hras_shell as hras_shell
from bonus_platform.app import app


def _fake_shell_profile(**overrides):
    profile = {
        "userId": 99,
        "username": "shell.admin",
        "realName": "壳子管理员",
        "roleName": "管理员",
        "role": "SUPER_ADMIN",
        "feishuOpenId": "ou_shell_admin",
        "email": "shell.admin@example.com",
        "modulePermissions": '["*"]',
    }
    profile.update(overrides)
    return profile


@pytest.fixture(autouse=True)
def reset_hras_token_cache(monkeypatch):
    monkeypatch.setenv("HRAS_SHELL_REGISTER_ENABLED", "false")
    monkeypatch.delenv("HRAS_SHELL_URL", raising=False)
    monkeypatch.delenv("HRAS_JWT_SECRET", raising=False)
    monkeypatch.delenv("JWT_SECRET", raising=False)
    hras_shell._token_cache.clear()
    hras_shell._user_profile_cache.clear()
    yield
    hras_shell._token_cache.clear()
    hras_shell._user_profile_cache.clear()


def test_health_and_metrics_follow_shell_contract():
    with TestClient(app) as client:
        health = client.get("/health")
        metrics = client.get("/metrics")

    assert health.status_code == 200
    assert health.json() == {"status": "UP"}
    assert metrics.status_code == 200
    payload = metrics.json()
    assert payload["status"] == "UP"
    assert "request_count" in payload["base"]


def test_shell_token_maps_to_local_session_and_skips_login_redirect(tmp_path, monkeypatch):
    db_path = tmp_path / "admin.sqlite"
    monkeypatch.setattr(admin_store, "get_admin_db_path", lambda: db_path)
    admin_store.init_admin_store()
    monkeypatch.setattr(hras_shell, "verify_shell_token", lambda _token: _fake_shell_profile())

    with TestClient(app, follow_redirects=False) as client:
        anonymous = client.get("/recruitment.html")
        embedded = client.get("/recruitment.html", params={"token": "aaa.bbb.ccc"})
        me = client.get("/api/me")

    assert anonymous.status_code == 302
    assert "/login.html" in anonymous.headers["location"]
    assert embedded.status_code == 200
    assert me.status_code == 200
    body = me.json()
    assert body["authSource"] == "hras-shell"
    assert any(role["id"] == "admin" for role in body["roles"])
    assert any(module["id"] == "recruitment" and module["canEnter"] for module in body["modules"])


def test_shell_module_permissions_drive_workbench_access(tmp_path, monkeypatch):
    db_path = tmp_path / "admin.sqlite"
    monkeypatch.setattr(admin_store, "get_admin_db_path", lambda: db_path)
    admin_store.init_admin_store()
    monkeypatch.setattr(
        hras_shell,
        "verify_shell_token",
        lambda _token: _fake_shell_profile(
            roleName="招聘核算",
            role="recruitment",
            modulePermissions='["hras-payroll/recruitment.html"]',
            feishuOpenId="ou_shell_recruiter",
            email="recruiter@example.com",
            username="recruiter",
            realName="壳子招聘员",
        ),
    )

    with TestClient(app, follow_redirects=False) as client:
        recruitment = client.get("/recruitment.html", params={"token": "aaa.bbb.ccc"})
        admin_page = client.get("/admin.html", params={"token": "aaa.bbb.ccc"})
        me = client.get("/api/me", headers={"Authorization": "Bearer aaa.bbb.ccc"})

    assert recruitment.status_code == 200
    assert admin_page.status_code == 403
    assert me.status_code == 200
    modules = {item["id"]: item["canEnter"] for item in me.json()["modules"]}
    assert modules["recruitment"] is True
    assert not any(role["id"] == "admin" for role in me.json()["roles"])


def test_independent_login_still_uses_local_session(tmp_path, monkeypatch):
    db_path = tmp_path / "admin.sqlite"
    monkeypatch.setattr(admin_store, "get_admin_db_path", lambda: db_path)
    monkeypatch.setenv("SIGMA_ENABLE_MOCK_LOGIN", "1")

    with TestClient(app, follow_redirects=False) as client:
        login = client.post("/api/auth/mock-login", json={"userId": "payrollAdmin"})
        me = client.get("/api/me")
        page = client.get("/recruitment.html")

    assert login.status_code == 200
    assert me.status_code == 200
    assert me.json()["user"]["id"] == "payrollAdmin"
    assert me.json().get("authSource") != "hras-shell"
    assert page.status_code == 200


def test_iframe_headers_are_not_blocked():
    with TestClient(app) as client:
        response = client.get("/health")

    assert "x-frame-options" not in {key.lower() for key in response.headers}


def test_production_does_not_accept_unverified_shell_tokens(tmp_path, monkeypatch):
    db_path = tmp_path / "admin.sqlite"
    monkeypatch.setattr(admin_store, "get_admin_db_path", lambda: db_path)
    monkeypatch.setenv("VERCEL_ENV", "production")
    monkeypatch.setenv("VERCEL", "1")
    profile = hras_shell.verify_shell_token("eyJhbGciOiJIUzUxMiJ9.eyJ1c2VySWQiOjF9.sig")
    assert profile is None
