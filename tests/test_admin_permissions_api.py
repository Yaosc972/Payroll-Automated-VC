from fastapi.testclient import TestClient
import pytest

import bonus_platform.app as app_module
import bonus_platform.engine.admin_store as admin_store
from bonus_platform.app import app


@pytest.fixture(autouse=True)
def enable_mock_auth_for_local_api_tests(monkeypatch):
    monkeypatch.setenv("SIGMA_ENABLE_MOCK_LOGIN", "1")


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
    assert any(module["id"] == "employee" and module["enabled"] is True for module in data["modules"])
    assert any(module["id"] == "overseas" and module["enabled"] is True for module in data["modules"])
    assert any(
        module["id"] == "domestic"
        and module["enabled"] is True
        and module["developmentStatus"] == "uat"
        for module in data["modules"]
    )
    assert any(
        module["id"] == "fbu"
        and module["enabled"] is True
        and module["developmentStatus"] == "available"
        for module in data["modules"]
    )
    assert data["moduleAccess"]["employeeAdmin"]["employee"] is True
    assert data["moduleAccess"]["employeeAdmin"]["domestic"] is False
    assert data["rolePermissions"]["admin"]["archive"] is True


def test_module_contact_reuses_directory_avatar_without_exposing_identity_fields(tmp_path, monkeypatch):
    db_path = tmp_path / "admin.sqlite"
    monkeypatch.setattr(admin_store, "get_admin_db_path", lambda: db_path)
    monkeypatch.setattr(
        app_module,
        "list_users",
        lambda: [
            {
                "name": "夏盈盈",
                "status": "active",
                "avatarUrl": "https://example.com/xia.png",
                "email": "private@example.com",
                "feishuOpenId": "private-open-id",
            }
        ],
    )

    with TestClient(app) as client:
        login = client.post("/api/auth/mock-login", json={"userId": "payrollAdmin"})
        assert login.status_code == 200
        response = client.get("/api/workbench/module-contacts/overseas-payroll")

    assert response.status_code == 200
    assert response.json() == {
        "contact": {
            "name": "夏盈盈",
            "department": "海外薪酬组",
            "avatarUrl": "/api/workbench/module-contacts/overseas-payroll/avatar",
        }
    }


def test_module_contact_avatar_is_proxied_from_the_trusted_feishu_cdn(tmp_path, monkeypatch):
    db_path = tmp_path / "admin.sqlite"
    monkeypatch.setattr(admin_store, "get_admin_db_path", lambda: db_path)
    monkeypatch.setattr(
        app_module,
        "list_users",
        lambda: [
            {
                "name": "夏盈盈",
                "status": "active",
                "avatarUrl": "https://s1-imfile.feishucdn.com/avatar.png",
            }
        ],
    )

    class AvatarResponse:
        status_code = 200
        headers = {"content-type": "image/png"}
        content = b"safe-avatar"

    monkeypatch.setattr(app_module.httpx, "get", lambda *_args, **_kwargs: AvatarResponse())

    with TestClient(app) as client:
        login = client.post("/api/auth/mock-login", json={"userId": "payrollAdmin"})
        assert login.status_code == 200
        response = client.get("/api/workbench/module-contacts/overseas-payroll/avatar")

    assert response.status_code == 200
    assert response.content == b"safe-avatar"
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "private, max-age=3600"


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
    employee = next(module for module in me["modules"] if module["id"] == "employee")
    assert employee["enabled"] is True
    domestic = next(module for module in me["modules"] if module["id"] == "domestic")
    assert domestic["enabled"] is True
    assert domestic["canEnter"] is True

    assert logs_response.status_code == 200
    actions = [log["action"] for log in logs_response.json()["logs"]]
    assert "set_user_roles" in actions
    assert "set_module_enabled" in actions


def test_business_activity_audit_classifies_useful_actions_and_filters_noise():
    assert app_module._business_activity_audit_event("GET", "/recruitment.html", 200) == {
        "action": "module_open",
        "target_type": "module",
        "target_id": "recruitment",
        "detail": "进入全球招聘奖金核算",
    }
    assert app_module._business_activity_audit_event("POST", "/api/domestic-labor/runs", 201) == {
        "action": "run_create",
        "target_type": "module",
        "target_id": "domestic",
        "detail": "新建核算批次",
    }
    assert app_module._business_activity_audit_event(
        "GET",
        "/api/fbu-performance/runs/run-123/export-excel",
        200,
    ) == {
        "action": "result_export",
        "target_type": "module",
        "target_id": "fbu",
        "detail": "导出结果 · 批次 ID：run-123",
    }
    assert app_module._business_activity_audit_event(
        "POST",
        "/api/labor/runs/run-456/extract-and-compare",
        200,
    ) == {
        "action": "calculation_submit",
        "target_type": "module",
        "target_id": "overseas",
        "detail": "提交核对 · 批次 ID：run-456",
    }
    assert app_module._business_activity_audit_event(
        "POST",
        "/api/china-employee-payroll/meal-allowance",
        200,
    )["action"] == "calculation_submit"

    assert app_module._business_activity_audit_event("GET", "/api/domestic-labor/runs", 200) is None
    assert app_module._business_activity_audit_event("POST", "/api/labor/worker/jobs/claim", 200) is None
    assert app_module._business_activity_audit_event("POST", "/api/labor/telemetry", 202) is None
    assert app_module._business_activity_audit_event(
        "POST",
        "/api/labor/runs/run-456/upload-intents",
        200,
    ) is None
    assert app_module._business_activity_audit_event(
        "POST",
        "/api/domestic-labor/runs/direct-upload-plan",
        200,
    ) is None
    assert app_module._business_activity_audit_event("PUT", "/api/admin/users/user-1/roles", 200) is None
    assert app_module._business_activity_audit_event("POST", "/api/domestic-labor/runs", 500) is None


def test_business_activity_audit_classifies_permission_and_operation_failures():
    assert app_module._business_activity_audit_outcome_event(
        "GET",
        "/china-employee-payroll.html",
        403,
    ) == {
        "action": "access_denied",
        "target_type": "module",
        "target_id": "employee",
        "detail": "权限拒绝 · HTTP 403",
    }
    assert app_module._business_activity_audit_outcome_event(
        "POST",
        "/api/china-employee-payroll/meal-allowance",
        422,
    ) == {
        "action": "operation_failed",
        "target_type": "module",
        "target_id": "employee",
        "detail": "提交核算失败 · HTTP 422",
    }
    assert app_module._business_activity_audit_outcome_event(
        "GET",
        "/api/domestic-labor/runs",
        500,
    ) is None
    assert app_module._business_activity_audit_outcome_event(
        "POST",
        "/api/labor/worker/jobs/claim",
        500,
    ) is None


def test_authenticated_permission_denial_and_business_failure_are_audited(tmp_path, monkeypatch):
    db_path = tmp_path / "admin.sqlite"
    monkeypatch.setattr(admin_store, "get_admin_db_path", lambda: db_path)

    with TestClient(app) as client:
        client.post("/api/auth/mock-login", json={"userId": "recruitmentAdminUser"})
        forbidden_page = client.get("/china-employee-payroll.html")
        client.post("/api/auth/logout")

        client.post("/api/auth/mock-login", json={"userId": "cnPayrollAdminUser"})
        failed_calculation = client.post("/api/china-employee-payroll/meal-allowance")
        client.post("/api/auth/logout")

        client.post("/api/auth/mock-login", json={"userId": "payrollAdmin"})
        logs_response = client.get("/api/admin/audit-logs?limit=50")

    assert forbidden_page.status_code == 403
    assert failed_calculation.status_code == 422
    logs = logs_response.json()["logs"]
    assert any(
        log["actorUserId"] == "recruitmentAdminUser"
        and log["action"] == "access_denied"
        and log["targetId"] == "employee"
        for log in logs
    )
    assert any(
        log["actorUserId"] == "cnPayrollAdminUser"
        and log["action"] == "operation_failed"
        and log["detail"] == "提交核算失败 · HTTP 422"
        for log in logs
    )


def test_module_entry_and_logout_are_recorded_for_authenticated_user(tmp_path, monkeypatch):
    db_path = tmp_path / "admin.sqlite"
    monkeypatch.setattr(admin_store, "get_admin_db_path", lambda: db_path)

    with TestClient(app) as client:
        login = client.post("/api/auth/mock-login", json={"userId": "recruitmentAdminUser"})
        module_page = client.get("/recruitment.html")
        logout = client.post("/api/auth/logout")
        client.post("/api/auth/mock-login", json={"userId": "payrollAdmin"})
        logs_response = client.get("/api/admin/audit-logs?limit=50")

    assert login.status_code == 200
    assert module_page.status_code == 200
    assert logout.status_code == 200
    logs = logs_response.json()["logs"]
    recruitment_actions = {
        log["action"]
        for log in logs
        if log["actorUserId"] == "recruitmentAdminUser"
    }
    assert {"mock_login", "module_open", "logout"} <= recruitment_actions


def test_admin_audit_logs_api_returns_server_side_pagination(tmp_path, monkeypatch):
    db_path = tmp_path / "admin.sqlite"
    monkeypatch.setattr(admin_store, "get_admin_db_path", lambda: db_path)
    admin_store.init_admin_store(db_path)
    for index in range(23):
        admin_store.record_audit_event(
            "payrollAdmin",
            "business_operation",
            "module",
            "recruitment",
            f"测试记录 {index + 1}",
            db_path=db_path,
        )

    with TestClient(app) as client:
        client.post("/api/auth/mock-login", json={"userId": "payrollAdmin"})
        first_page = client.get("/api/admin/audit-logs?page=1&page_size=10")
        second_page = client.get("/api/admin/audit-logs?page=2&page_size=10")
        last_page = client.get("/api/admin/audit-logs?page=999&page_size=10")

    assert first_page.status_code == 200
    assert first_page.json()["pagination"] == {
        "page": 1,
        "pageSize": 10,
        "total": 24,
        "totalPages": 3,
    }
    assert len(first_page.json()["logs"]) == 10
    assert len(second_page.json()["logs"]) == 10
    assert {log["id"] for log in first_page.json()["logs"]}.isdisjoint(
        {log["id"] for log in second_page.json()["logs"]}
    )
    assert last_page.json()["pagination"]["page"] == 3
    assert len(last_page.json()["logs"]) == 4


def test_overseas_labor_requires_module_role_on_page_and_api(tmp_path, monkeypatch):
    db_path = tmp_path / "admin.sqlite"
    monkeypatch.setattr(admin_store, "get_admin_db_path", lambda: db_path)

    with TestClient(app) as client:
        client.post("/api/auth/mock-login", json={"userId": "recruitmentAdminUser"})
        page_without_role = client.get("/overseas-labor.html")
        api_without_role = client.get("/api/labor/runs")

        client.post("/api/auth/logout")
        client.post("/api/auth/mock-login", json={"userId": "overseasAdminUser"})
        page_with_role = client.get("/overseas-labor.html")
        api_with_role = client.get("/api/labor/runs")

    assert page_without_role.status_code == 403
    assert api_without_role.status_code == 403
    assert page_with_role.status_code == 200
    assert api_with_role.status_code == 200


def test_fbu_requires_enabled_module_and_authorized_role_on_page_and_api(tmp_path, monkeypatch):
    db_path = tmp_path / "admin.sqlite"
    monkeypatch.setattr(admin_store, "get_admin_db_path", lambda: db_path)
    monkeypatch.setenv("SIGMA_HIDE_DEVELOPING_MODULES", "1")

    with TestClient(app) as client:
        unauthenticated_page = client.get("/fbu-performance.html")
        unauthenticated_api = client.get("/api/fbu-performance/runs")

        client.post("/api/auth/mock-login", json={"userId": "recruitmentAdminUser"})
        unauthorized_page = client.get("/fbu-performance.html")
        unauthorized_api = client.get("/api/fbu-performance/runs")

        client.post("/api/auth/logout")
        client.post("/api/auth/mock-login", json={"userId": "fbuAdminUser"})
        fbu_admin_page = client.get("/fbu-performance.html")
        fbu_admin_api = client.get("/api/fbu-performance/runs")

        client.post("/api/auth/logout")
        client.post("/api/auth/mock-login", json={"userId": "payrollAdmin"})
        system_admin_api = client.get("/api/fbu-performance/runs")

    assert unauthenticated_page.status_code == 401
    assert unauthenticated_api.status_code == 401
    assert unauthorized_page.status_code == 403
    assert unauthorized_api.status_code == 403
    assert fbu_admin_page.status_code == 200
    assert fbu_admin_api.status_code == 200
    assert system_admin_api.status_code == 200


def test_domestic_labor_requires_enabled_module_and_authorized_role_on_page_and_api(tmp_path, monkeypatch):
    db_path = tmp_path / "admin.sqlite"
    monkeypatch.setattr(admin_store, "get_admin_db_path", lambda: db_path)

    with TestClient(app) as client:
        unauthenticated_page = client.get("/domestic-labor.html", follow_redirects=False)
        unauthenticated_api = client.get("/api/domestic-labor/runs")

        client.post("/api/auth/mock-login", json={"userId": "recruitmentAdminUser"})
        unauthorized_page = client.get("/domestic-labor.html")
        unauthorized_api = client.get("/api/domestic-labor/runs")

        client.post("/api/auth/logout")
        client.post("/api/auth/mock-login", json={"userId": "cnPayrollAdminUser"})
        domestic_admin_page = client.get("/domestic-labor.html")
        domestic_admin_api = client.get("/api/domestic-labor/runs")

        client.post("/api/auth/logout")
        client.post("/api/auth/mock-login", json={"userId": "payrollAdmin"})
        system_admin_api = client.get("/api/domestic-labor/runs")

    assert unauthenticated_page.status_code == 302
    assert unauthenticated_page.headers["location"].startswith("/login.html?next=")
    assert unauthenticated_api.status_code == 401
    assert unauthorized_page.status_code == 403
    assert unauthorized_api.status_code == 403
    assert domestic_admin_page.status_code == 200
    assert domestic_admin_api.status_code == 200
    assert system_admin_api.status_code == 200


def test_remaining_protected_pages_are_authorized_before_static_html_is_served(tmp_path, monkeypatch):
    db_path = tmp_path / "admin.sqlite"
    monkeypatch.setattr(admin_store, "get_admin_db_path", lambda: db_path)

    with TestClient(app) as client:
        unauthenticated_recruitment = client.get("/recruitment.html", follow_redirects=False)
        unauthenticated_employee = client.get("/china-employee-payroll.html", follow_redirects=False)
        unauthenticated_admin = client.get("/admin.html", follow_redirects=False)

        client.post("/api/auth/mock-login", json={"userId": "recruitmentAdminUser"})
        recruitment_page = client.get("/recruitment.html")
        forbidden_employee = client.get("/china-employee-payroll.html")
        forbidden_admin = client.get("/admin.html")

        client.post("/api/auth/logout")
        client.post("/api/auth/mock-login", json={"userId": "cnPayrollAdminUser"})
        employee_page = client.get("/china-employee-payroll.html")

        client.post("/api/auth/logout")
        client.post("/api/auth/mock-login", json={"userId": "payrollAdmin"})
        admin_page = client.get("/admin.html")

    assert unauthenticated_recruitment.status_code == 302
    assert unauthenticated_employee.status_code == 302
    assert unauthenticated_admin.status_code == 302
    assert recruitment_page.status_code == 200
    assert forbidden_employee.status_code == 403
    assert forbidden_admin.status_code == 403
    assert employee_page.status_code == 200
    assert admin_page.status_code == 200


def test_mock_auth_endpoints_are_disabled_on_vercel(tmp_path, monkeypatch):
    db_path = tmp_path / "admin.sqlite"
    monkeypatch.setattr(admin_store, "get_admin_db_path", lambda: db_path)
    monkeypatch.setenv("VERCEL_ENV", "production")

    with TestClient(app) as client:
        users_response = client.get("/api/auth/mock-users")
        login_response = client.post("/api/auth/mock-login", json={"userId": "payrollAdmin"})

    assert users_response.status_code == 404
    assert login_response.status_code == 404


def test_mock_auth_endpoints_require_explicit_local_flag(tmp_path, monkeypatch):
    db_path = tmp_path / "admin.sqlite"
    monkeypatch.setattr(admin_store, "get_admin_db_path", lambda: db_path)
    monkeypatch.delenv("SIGMA_ENABLE_MOCK_LOGIN", raising=False)
    monkeypatch.delenv("VERCEL_ENV", raising=False)

    with TestClient(app) as client:
        users_response = client.get("/api/auth/mock-users")
        login_response = client.post("/api/auth/mock-login", json={"userId": "payrollAdmin"})

    assert users_response.status_code == 404
    assert login_response.status_code == 404


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
        invalid_lark_callback = client.get("/api/auth/lark/callback", params={"code": "abc", "state": "bad"})

    assert config_response.status_code == 200
    assert config_response.json()["configured"] is False
    assert unconfigured_login.status_code == 503
    assert invalid_callback.status_code == 400
    assert invalid_lark_callback.status_code == 400


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


def test_get_current_user_builds_permission_snapshot_with_one_connection(tmp_path, monkeypatch):
    db_path = tmp_path / "admin.sqlite"
    monkeypatch.setattr(admin_store, "get_admin_db_path", lambda: db_path)
    admin_store._STORE_INITIALIZED = False
    admin_store._STORE_INITIALIZED_TARGET = ""
    admin_store.init_admin_store()

    real_connect = admin_store._connect
    calls = 0

    def counted_connect(db_path=None):
        nonlocal calls
        calls += 1
        return real_connect(db_path)

    monkeypatch.setattr(admin_store, "_connect", counted_connect)

    current = admin_store.get_current_user("overseasAdminUser")

    assert current["user"]["id"] == "overseasAdminUser"
    assert any(module["id"] == "overseas" and module["canEnter"] for module in current["modules"])
    assert calls == 1


def test_get_session_auth_context_uses_one_connection(tmp_path, monkeypatch):
    db_path = tmp_path / "admin.sqlite"
    monkeypatch.setattr(admin_store, "get_admin_db_path", lambda: db_path)
    admin_store._STORE_INITIALIZED = False
    admin_store._STORE_INITIALIZED_TARGET = ""
    admin_store.init_admin_store()
    token = admin_store.create_session("overseasAdminUser")

    real_connect = admin_store._connect
    calls = 0

    def counted_connect(db_path=None):
        nonlocal calls
        calls += 1
        return real_connect(db_path)

    monkeypatch.setattr(admin_store, "_connect", counted_connect)

    user_id, permission_revision = admin_store.get_session_auth_context(token)

    assert user_id == "overseasAdminUser"
    assert len(permission_revision) == 64
    assert calls == 1


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
