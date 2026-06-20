from fastapi.testclient import TestClient

import bonus_platform.app as app_module
import bonus_platform.engine.admin_store as admin_store
from bonus_platform.app import app


def test_admin_state_seeds_users_roles_modules_and_permissions(tmp_path, monkeypatch):
    db_path = tmp_path / "admin.sqlite"
    monkeypatch.setattr(admin_store, "get_admin_db_path", lambda: db_path)

    with TestClient(app) as client:
        login = client.post("/api/auth/mock-login", json={"userId": "payrollAdmin"})
        assert login.status_code == 200
        response = client.get("/api/admin/state")

    assert response.status_code == 200
    data = response.json()
    assert {role["id"] for role in data["roles"]} >= {"admin", "employeeAdmin", "domesticAdmin"}
    assert {user["id"] for user in data["users"]} >= {"payrollAdmin", "cnPayrollAdminUser"}
    assert any(module["id"] == "employee" and module["enabled"] is False for module in data["modules"])
    assert data["moduleAccess"]["employeeAdmin"]["employee"] is True
    assert data["moduleAccess"]["employeeAdmin"]["domestic"] is False
    assert data["rolePermissions"]["admin"]["archive"] is True


def test_admin_api_updates_permissions_and_audit_logs(tmp_path, monkeypatch):
    db_path = tmp_path / "admin.sqlite"
    monkeypatch.setattr(admin_store, "get_admin_db_path", lambda: db_path)

    with TestClient(app) as client:
        login = client.post("/api/auth/mock-login", json={"userId": "payrollAdmin"})
        assert login.status_code == 200
        module_response = client.patch("/api/admin/modules/employee", json={"enabled": True})
        domestic_module_response = client.patch("/api/admin/modules/domestic", json={"enabled": True})
        access_response = client.put("/api/admin/modules/domestic/roles/employeeAdmin", json={"canEnter": True})
        user_response = client.put(
            "/api/admin/users/recruitmentAdminUser/roles",
            json={"roleIds": ["recruitmentAdmin", "domesticAdmin"]},
        )
        clear_user_response = client.put(
            "/api/admin/users/recruitmentAdminUser/roles",
            json={"roleIds": []},
        )
        reactivate_user_response = client.put(
            "/api/admin/users/recruitmentAdminUser/roles",
            json={"roleIds": ["recruitmentAdmin", "domesticAdmin"]},
        )
        feature_response = client.put("/api/admin/roles/domesticAdmin/features/export", json={"enabled": True})
        client.post("/api/auth/logout")
        client.post("/api/auth/mock-login", json={"userId": "recruitmentAdminUser"})
        me_response = client.get("/api/me")
        client.post("/api/auth/logout")
        client.post("/api/auth/mock-login", json={"userId": "payrollAdmin"})
        logs_response = client.get("/api/admin/audit-logs")

    assert module_response.status_code == 200
    assert module_response.json()["module"]["enabled"] is True
    assert domestic_module_response.status_code == 200
    assert domestic_module_response.json()["module"]["enabled"] is True
    assert access_response.status_code == 200
    assert access_response.json()["moduleAccess"]["domestic"] is True
    assert user_response.status_code == 200
    assert set(user_response.json()["user"]["roleIds"]) == {"recruitmentAdmin", "domesticAdmin"}
    assert user_response.json()["user"]["status"] == "active"
    assert clear_user_response.status_code == 200
    assert clear_user_response.json()["user"]["status"] == "pending"
    assert reactivate_user_response.status_code == 200
    assert reactivate_user_response.json()["user"]["status"] == "active"
    assert feature_response.status_code == 200
    assert feature_response.json()["rolePermissions"]["export"] is True

    assert me_response.status_code == 200
    me = me_response.json()
    domestic = next(module for module in me["modules"] if module["id"] == "domestic")
    assert domestic["canEnter"] is True

    assert logs_response.status_code == 200
    actions = [log["action"] for log in logs_response.json()["logs"]]
    assert "set_user_roles" in actions
    assert "set_module_enabled" in actions


def test_admin_api_rejects_invalid_ids_and_non_admin_actor(tmp_path, monkeypatch):
    db_path = tmp_path / "admin.sqlite"
    monkeypatch.setattr(admin_store, "get_admin_db_path", lambda: db_path)

    with TestClient(app) as client:
        unauthenticated_response = client.get("/api/me")
        invalid_response = client.post("/api/auth/mock-login", json={"userId": "bad;drop"})
        unknown_response = client.post("/api/auth/mock-login", json={"userId": "unknownUser"})
        client.post("/api/auth/mock-login", json={"userId": "recruitmentAdminUser"})
        forbidden_response = client.patch(
            "/api/admin/modules/employee",
            json={"enabled": True},
        )
        client.post("/api/auth/logout")
        client.post("/api/auth/mock-login", json={"userId": "payrollAdmin"})
        invalid_bool_response = client.patch(
            "/api/admin/modules/employee",
            json={"enabled": "false"},
        )
        allowed_response = client.patch(
            "/api/admin/modules/employee",
            json={"enabled": True},
        )

    assert unauthenticated_response.status_code == 401
    assert invalid_response.status_code == 400
    assert unknown_response.status_code == 404
    assert forbidden_response.status_code == 403
    assert invalid_bool_response.status_code == 400
    assert allowed_response.status_code == 200


def test_admin_api_prevents_self_lockout_and_last_admin_removal(tmp_path, monkeypatch):
    db_path = tmp_path / "admin.sqlite"
    monkeypatch.setattr(admin_store, "get_admin_db_path", lambda: db_path)

    with TestClient(app) as client:
        client.post("/api/auth/mock-login", json={"userId": "payrollAdmin"})
        self_remove_response = client.put("/api/admin/users/payrollAdmin/roles", json={"roleIds": []})
        give_other_admin_response = client.put(
            "/api/admin/users/recruitmentAdminUser/roles",
            json={"roleIds": ["admin"]},
        )
        second_self_remove_response = client.put("/api/admin/users/payrollAdmin/roles", json={"roleIds": []})
        other_remove_response = client.put(
            "/api/admin/users/recruitmentAdminUser/roles",
            json={"roleIds": ["recruitmentAdmin"]},
        )

    assert self_remove_response.status_code == 400
    assert "不能移除当前登录账号" in self_remove_response.json()["detail"]
    assert give_other_admin_response.status_code == 200
    assert second_self_remove_response.status_code == 400
    assert other_remove_response.status_code == 200


def test_mock_login_sets_session_cookie_and_logout_clears_it(tmp_path, monkeypatch):
    db_path = tmp_path / "admin.sqlite"
    monkeypatch.setattr(admin_store, "get_admin_db_path", lambda: db_path)

    with TestClient(app) as client:
        login = client.post("/api/auth/mock-login", json={"userId": "payrollAdmin"})
        me = client.get("/api/me")
        logout = client.post("/api/auth/logout")
        after_logout = client.get("/api/me")
        client.post("/api/auth/mock-login", json={"userId": "payrollAdmin"})
        logout_redirect = client.get("/api/auth/logout", follow_redirects=False)

    assert login.status_code == 200
    assert "sigma_session" in login.headers.get("set-cookie", "")
    assert me.status_code == 200
    assert me.json()["user"]["id"] == "payrollAdmin"
    assert logout.status_code == 200
    assert after_logout.status_code == 401
    assert logout_redirect.status_code == 302
    assert logout_redirect.headers["location"] == "login.html?next=%2F"


def test_feishu_oauth_skeleton_config_and_state_validation(tmp_path, monkeypatch):
    db_path = tmp_path / "admin.sqlite"
    monkeypatch.setattr(admin_store, "get_admin_db_path", lambda: db_path)

    with TestClient(app) as client:
        config_response = client.get("/api/auth/feishu/config")
        unconfigured_login = client.get("/api/auth/feishu/login", follow_redirects=False)
        invalid_callback = client.get("/api/auth/feishu/callback", params={"code": "abc", "state": "bad"})

    assert config_response.status_code == 200
    assert config_response.json()["configured"] is False
    assert unconfigured_login.status_code == 503
    assert invalid_callback.status_code == 400


def test_upsert_feishu_user_creates_pending_user_without_roles(tmp_path, monkeypatch):
    db_path = tmp_path / "admin.sqlite"
    monkeypatch.setattr(admin_store, "get_admin_db_path", lambda: db_path)

    user = admin_store.upsert_feishu_user(
        feishu_open_id="ou_test_user",
        feishu_union_id="on_test_user",
        email="feishu.user@example.com",
        avatar_url="https://example.com/avatar.png",
        name="Feishu User",
    )

    assert user["id"] == "feishu_ou_test_user"
    assert user["name"] == "Feishu User"
    assert user["avatarUrl"] == "https://example.com/avatar.png"
    assert user["status"] == "pending"
    assert user["roleIds"] == []


def test_bootstrap_identifier_auto_grants_system_admin(tmp_path, monkeypatch):
    db_path = tmp_path / "admin.sqlite"
    monkeypatch.setattr(admin_store, "get_admin_db_path", lambda: db_path)
    monkeypatch.setattr(admin_store.config, "ADMIN_BOOTSTRAP_IDENTIFIERS", ["姚硕灿"])

    user = admin_store.upsert_feishu_user(
        feishu_open_id="ou_yao",
        feishu_union_id="on_yao",
        email="yao@example.com",
        name="姚硕灿",
    )
    current = admin_store.get_current_user(user["id"])

    assert "admin" in user["roleIds"]
    assert current["roles"][0]["id"] == "admin"


def test_feishu_callback_creates_session_for_pending_user(tmp_path, monkeypatch):
    db_path = tmp_path / "admin.sqlite"
    monkeypatch.setattr(admin_store, "get_admin_db_path", lambda: db_path)
    monkeypatch.setitem(app_module.AUTH_CONFIG, "feishu_app_id", "cli_test")
    monkeypatch.setitem(app_module.AUTH_CONFIG, "feishu_app_secret", "secret_test")
    monkeypatch.setitem(app_module.AUTH_CONFIG, "feishu_redirect_uri", "https://example.com/api/auth/feishu/callback")
    monkeypatch.setattr(app_module, "_get_feishu_app_access_token", lambda: "app-token")
    monkeypatch.setattr(
        app_module,
        "_get_feishu_user_access_token",
        lambda code, app_access_token: {"access_token": "user-token", "open_id": "ou_callback_user"},
    )
    monkeypatch.setattr(
        app_module,
        "_get_feishu_user_info",
        lambda user_access_token: {
            "open_id": "ou_callback_user",
            "union_id": "on_callback_user",
            "email": "callback.user@example.com",
            "avatar_url": "https://example.com/callback.png",
            "name": "Callback User",
        },
    )

    with TestClient(app) as client:
        client.cookies.set("sigma_feishu_state", "state-ok")
        callback = client.get(
            "/api/auth/feishu/callback",
            params={"code": "login-code", "state": "state-ok"},
            follow_redirects=False,
        )
        me = client.get("/api/me")

    assert callback.status_code == 302
    assert callback.headers["location"] == "/"
    assert "sigma_session" in callback.headers.get("set-cookie", "")
    assert me.status_code == 200
    assert me.json()["user"]["id"] == "feishu_ou_callback_user"
    assert me.json()["user"]["avatarUrl"] == "https://example.com/callback.png"
    assert me.json()["user"]["status"] == "pending"
    assert me.json()["roles"] == []


def test_feishu_callback_uses_contact_avatar_when_user_info_has_no_avatar(tmp_path, monkeypatch):
    db_path = tmp_path / "admin.sqlite"
    monkeypatch.setattr(admin_store, "get_admin_db_path", lambda: db_path)
    monkeypatch.setitem(app_module.AUTH_CONFIG, "feishu_app_id", "cli_test")
    monkeypatch.setitem(app_module.AUTH_CONFIG, "feishu_app_secret", "secret_test")
    monkeypatch.setitem(app_module.AUTH_CONFIG, "feishu_redirect_uri", "https://example.com/api/auth/feishu/callback")
    monkeypatch.setattr(app_module, "_get_feishu_app_access_token", lambda: "app-token")
    monkeypatch.setattr(app_module, "_get_feishu_tenant_access_token", lambda: "tenant-token")
    monkeypatch.setattr(
        app_module,
        "_get_feishu_user_access_token",
        lambda code, app_access_token: {"access_token": "user-token", "open_id": "ou_contact_avatar_user"},
    )
    monkeypatch.setattr(
        app_module,
        "_get_feishu_user_info",
        lambda user_access_token: {
            "open_id": "ou_contact_avatar_user",
            "union_id": "on_contact_avatar_user",
            "email": "contact.avatar@example.com",
            "name": "Contact Avatar",
        },
    )
    monkeypatch.setattr(
        app_module,
        "_get_feishu_contact_user",
        lambda open_id, tenant_access_token: {
            "avatar": {
                "avatar_72": "https://example.com/avatar-72.png",
                "avatar_240": "https://example.com/avatar-240.png",
            }
        },
    )

    with TestClient(app) as client:
        client.cookies.set("sigma_feishu_state", "state-ok")
        callback = client.get(
            "/api/auth/feishu/callback",
            params={"code": "login-code", "state": "state-ok"},
            follow_redirects=False,
        )
        me = client.get("/api/me")

    assert callback.status_code == 302
    assert me.status_code == 200
    assert me.json()["user"]["avatarUrl"] == "https://example.com/avatar-240.png"


def test_admin_store_accepts_sqlite_database_url(tmp_path, monkeypatch):
    db_path = tmp_path / "configured-admin.sqlite"
    monkeypatch.setattr(admin_store, "get_admin_database_url", lambda: f"sqlite:///{db_path}")

    initialized_path = admin_store.init_admin_store()
    roles = admin_store.list_roles()

    assert initialized_path == db_path
    assert db_path.exists()
    assert any(role["id"] == "admin" for role in roles)


def test_admin_database_url_normalizes_bracketed_pooler_host(monkeypatch):
    monkeypatch.setattr(
        admin_store.config,
        "ADMIN_DATABASE_URL",
        "postgresql://postgres.ref:secret@[aws-1-us-west-2.pooler.supabase.com]:6543/postgres",
    )

    assert (
        admin_store.get_admin_database_url()
        == "postgresql://postgres.ref:secret@aws-1-us-west-2.pooler.supabase.com:6543/postgres"
    )
