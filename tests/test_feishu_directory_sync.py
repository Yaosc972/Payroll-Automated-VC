from fastapi.testclient import TestClient
import sqlite3
import threading

import bonus_platform.app as app_module
import bonus_platform.engine.admin_store as admin_store
from bonus_platform.app import app


def _reset_store(monkeypatch, db_path):
    monkeypatch.setattr(admin_store, "get_admin_db_path", lambda: db_path)
    admin_store._STORE_INITIALIZED = False
    admin_store._STORE_INITIALIZED_TARGET = ""


def test_feishu_user_id_is_canonical_and_existing_account_is_not_duplicated(tmp_path, monkeypatch):
    db_path = tmp_path / "admin.sqlite"
    _reset_store(monkeypatch, db_path)

    original = admin_store.upsert_feishu_user(
        feishu_open_id="ou_existing",
        feishu_union_id="on_existing",
        email="existing@example.com",
        name="已有用户",
    )
    updated = admin_store.upsert_feishu_user(
        feishu_user_id="u_10001",
        feishu_open_id="ou_existing_new",
        feishu_union_id="on_existing",
        email="existing@example.com",
        employee_number="ZT10001",
        name="已有用户",
    )

    users = admin_store.list_users(db_path)
    assert len([user for user in users if user["email"] == "existing@example.com"]) == 1
    assert updated["id"] == original["id"]
    assert updated["feishuUserId"] == "u_10001"
    assert updated["employeeNumber"] == "ZT10001"


def test_directory_snapshot_keeps_outside_login_users_and_records_departments(tmp_path, monkeypatch):
    db_path = tmp_path / "admin.sqlite"
    _reset_store(monkeypatch, db_path)
    outside = admin_store.upsert_feishu_user(
        feishu_user_id="u_outside",
        feishu_open_id="ou_outside",
        email="outside@example.com",
        name="范围外用户",
    )

    result = admin_store.apply_feishu_directory_snapshot(
        root_department_id="od_hras",
        departments=[
            {"departmentId": "od_hras", "name": "HRAS 人力综合条线", "parentDepartmentId": "0"},
            {"departmentId": "od_payroll", "name": "全球薪酬组", "parentDepartmentId": "od_hras"},
        ],
        users=[
            {
                "feishuUserId": "u_payroll",
                "feishuOpenId": "ou_payroll",
                "feishuUnionId": "on_payroll",
                "name": "薪酬同事",
                "email": "payroll@example.com",
                "employeeNumber": "ZT20001",
                "avatarUrl": "https://example.com/payroll.png",
                "departmentIds": ["od_payroll"],
            }
        ],
        actor_user_id="payrollAdmin",
        db_path=db_path,
    )

    users = {user["feishuUserId"]: user for user in admin_store.list_users(db_path) if user["feishuUserId"]}
    assert result["userCount"] == 1
    assert users["u_payroll"]["directoryScope"] == "hras"
    assert users["u_payroll"]["departmentNames"] == ["全球薪酬组"]
    assert users["u_outside"]["id"] == outside["id"]
    assert users["u_outside"]["directoryScope"] == "external"
    assert users["u_outside"]["status"] == "pending"


def test_user_removed_from_hras_scope_becomes_external_without_deletion_or_role_changes(tmp_path, monkeypatch):
    db_path = tmp_path / "admin.sqlite"
    _reset_store(monkeypatch, db_path)
    departments = [{"departmentId": "od_hras", "name": "HRAS 人力综合条线", "parentDepartmentId": "0"}]
    user = {
        "feishuUserId": "u_move",
        "feishuOpenId": "ou_move",
        "name": "调出人员",
        "departmentIds": ["od_hras"],
    }
    admin_store.apply_feishu_directory_snapshot(
        root_department_id="od_hras",
        departments=departments,
        users=[user],
        actor_user_id="payrollAdmin",
        db_path=db_path,
    )
    synced = next(item for item in admin_store.list_users(db_path) if item["feishuUserId"] == "u_move")
    admin_store.set_user_roles(synced["id"], ["fbuAdmin"], actor_user_id="payrollAdmin", db_path=db_path)

    result = admin_store.apply_feishu_directory_snapshot(
        root_department_id="od_hras",
        departments=departments,
        users=[],
        actor_user_id="payrollAdmin",
        db_path=db_path,
    )

    moved = next(item for item in admin_store.list_users(db_path) if item["feishuUserId"] == "u_move")
    assert result["movedOutsideCount"] == 1
    assert moved["directoryScope"] == "external"
    assert moved["departmentNames"] == []
    assert moved["roleIds"] == ["fbuAdmin"]
    assert moved["status"] == "active"


def test_directory_snapshot_uses_bounded_database_connections(tmp_path, monkeypatch):
    db_path = tmp_path / "admin.sqlite"
    _reset_store(monkeypatch, db_path)
    admin_store.init_admin_store(db_path)
    original_connect = admin_store._connect
    connection_count = 0

    def counted_connect(path=None):
        nonlocal connection_count
        connection_count += 1
        return original_connect(path)

    monkeypatch.setattr(admin_store, "_connect", counted_connect)
    admin_store.apply_feishu_directory_snapshot(
        root_department_id="od_hras",
        departments=[{"departmentId": "od_hras", "name": "HRAS 人力综合条线", "parentDepartmentId": "0"}],
        users=[
            {
                "feishuUserId": f"u_{index}",
                "feishuOpenId": f"ou_{index}",
                "name": f"同步用户 {index}",
                "departmentIds": ["od_hras"],
            }
            for index in range(20)
        ],
        actor_user_id="payrollAdmin",
        db_path=db_path,
    )

    assert connection_count <= 2


def test_directory_sync_endpoint_is_production_only(tmp_path, monkeypatch):
    db_path = tmp_path / "admin.sqlite"
    _reset_store(monkeypatch, db_path)
    monkeypatch.setenv("SIGMA_ENABLE_MOCK_LOGIN", "1")
    monkeypatch.setenv("SIGMA_FEISHU_DIRECTORY_SYNC_ENABLED", "1")
    monkeypatch.setenv("SIGMA_FEISHU_DIRECTORY_ROOT_DEPARTMENT_ID", "od_hras")
    called = False

    def unexpected_fetch():
        nonlocal called
        called = True
        return {}, []

    monkeypatch.setattr(app_module, "_fetch_feishu_directory_snapshot", unexpected_fetch)

    with TestClient(app) as client:
        assert client.post("/api/auth/mock-login", json={"userId": "payrollAdmin"}).status_code == 200
        monkeypatch.setenv("VERCEL_ENV", "preview")
        response = client.post("/api/admin/directory/sync")

    assert response.status_code == 409
    assert response.json()["detail"] == "飞书组织同步仅允许在生产环境执行。"
    assert called is False


def test_feishu_directory_fetch_walks_subtree_and_deduplicates_members(monkeypatch):
    monkeypatch.setenv("SIGMA_FEISHU_DIRECTORY_ROOT_DEPARTMENT_ID", "od_hras")
    monkeypatch.setattr(app_module, "_get_feishu_tenant_access_token", lambda: "tenant-token")

    def fake_get(path, token, params):
        assert token == "tenant-token"
        if path.endswith("/departments/od_hras"):
            return {"department": {"name": "HRAS 人力综合条线", "parent_department_id": "0"}}
        if path.endswith("/departments/od_hras/children"):
            assert params["fetch_child"] == "true"
            return {
                "items": [
                    {"department_id": "od_payroll", "name": "薪酬组", "parent_department_id": "od_hras"},
                    {"department_id": "od_overseas", "name": "海外薪酬组", "parent_department_id": "od_payroll"},
                ],
                "has_more": False,
            }
        if path.endswith("/users/find_by_department"):
            department_id = params["department_id"]
            return {
                "items": [{
                    "user_id": "u_one",
                    "open_id": "ou_one",
                    "name": "同一成员",
                    "employee_no": "ZT1",
                    "department_ids": [department_id],
                }],
                "has_more": False,
            }
        raise AssertionError(path)

    monkeypatch.setattr(app_module, "_feishu_directory_get", fake_get)

    departments, users = app_module._fetch_feishu_directory_snapshot()

    assert {item["departmentId"] for item in departments} == {"od_hras", "od_payroll", "od_overseas"}
    assert len(users) == 1
    assert users[0]["feishuUserId"] == "u_one"
    assert users[0]["employeeNumber"] == "ZT1"
    assert users[0]["departmentIds"] == ["od_hras", "od_payroll", "od_overseas"]


def test_feishu_directory_fetch_loads_department_members_concurrently(monkeypatch):
    monkeypatch.setenv("SIGMA_FEISHU_DIRECTORY_ROOT_DEPARTMENT_ID", "od_hras")
    monkeypatch.setattr(app_module, "_get_feishu_tenant_access_token", lambda: "tenant-token")
    member_barrier = threading.Barrier(2)

    def fake_get(path, token, params):
        assert token == "tenant-token"
        if path.endswith("/departments/od_hras"):
            return {"department": {"name": "HRAS 人力综合条线", "parent_department_id": "0"}}
        if path.endswith("/departments/od_hras/children"):
            return {
                "items": [{"department_id": "od_payroll", "name": "薪酬组", "parent_department_id": "od_hras"}],
                "has_more": False,
            }
        if path.endswith("/users/find_by_department"):
            member_barrier.wait(timeout=1)
            department_id = params["department_id"]
            return {
                "items": [{
                    "user_id": f"u_{department_id}",
                    "open_id": f"ou_{department_id}",
                    "name": department_id,
                    "department_ids": [department_id],
                }],
                "has_more": False,
            }
        raise AssertionError(path)

    monkeypatch.setattr(app_module, "_feishu_directory_get", fake_get)

    departments, users = app_module._fetch_feishu_directory_snapshot()

    assert len(departments) == 2
    assert {item["feishuUserId"] for item in users} == {"u_od_hras", "u_od_payroll"}


def test_production_directory_sync_applies_snapshot_once(tmp_path, monkeypatch):
    db_path = tmp_path / "admin.sqlite"
    _reset_store(monkeypatch, db_path)
    monkeypatch.setenv("SIGMA_ENABLE_MOCK_LOGIN", "1")
    monkeypatch.setenv("SIGMA_FEISHU_DIRECTORY_SYNC_ENABLED", "1")
    monkeypatch.setenv("SIGMA_FEISHU_DIRECTORY_ROOT_DEPARTMENT_ID", "od_hras")
    monkeypatch.setattr(
        app_module,
        "_fetch_feishu_directory_snapshot",
        lambda: (
            [{"departmentId": "od_hras", "name": "HRAS 人力综合条线", "parentDepartmentId": "0"}],
            [{
                "feishuUserId": "u_synced",
                "feishuOpenId": "ou_synced",
                "name": "同步用户",
                "employeeNumber": "ZT30001",
                "departmentIds": ["od_hras"],
            }],
        ),
    )

    with TestClient(app) as client:
        assert client.post("/api/auth/mock-login", json={"userId": "payrollAdmin"}).status_code == 200
        monkeypatch.setenv("VERCEL_ENV", "production")
        response = client.post("/api/admin/directory/sync")

    assert response.status_code == 200
    assert response.json()["sync"]["userCount"] == 1
    synced = next(user for user in admin_store.list_users(db_path) if user["feishuUserId"] == "u_synced")
    assert synced["employeeNumber"] == "ZT30001"
    assert synced["departmentNames"] == ["HRAS 人力综合条线"]


def test_admin_state_reports_directory_sync_capability_without_secrets(tmp_path, monkeypatch):
    db_path = tmp_path / "admin.sqlite"
    _reset_store(monkeypatch, db_path)
    monkeypatch.setenv("SIGMA_ENABLE_MOCK_LOGIN", "1")
    monkeypatch.setenv("SIGMA_FEISHU_DIRECTORY_SYNC_ENABLED", "1")
    monkeypatch.setenv("SIGMA_FEISHU_DIRECTORY_ROOT_DEPARTMENT_ID", "od_hras")

    with TestClient(app) as client:
        assert client.post("/api/auth/mock-login", json={"userId": "payrollAdmin"}).status_code == 200
        monkeypatch.setenv("VERCEL_ENV", "preview")
        response = client.get("/api/admin/state")

    directory = response.json()["directory"]
    assert directory == {
        "environment": "preview",
        "enabled": True,
        "canSync": False,
        "rootDepartmentConfigured": True,
        "rootDepartmentName": "HRAS 人力综合条线",
    }


def test_existing_admin_database_migrates_directory_columns_without_losing_user(tmp_path):
    db_path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE admin_users (
              id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT, avatar_url TEXT,
              feishu_open_id TEXT, feishu_union_id TEXT, status TEXT NOT NULL,
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO admin_users VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("legacy", "历史用户", "legacy@example.com", None, "ou_legacy", None, "active", "now", "now"),
        )

    admin_store.init_admin_store(db_path)

    legacy = next(user for user in admin_store.list_users(db_path) if user["id"] == "legacy")
    assert legacy["name"] == "历史用户"
    assert legacy["directoryScope"] == "external"
    assert legacy["feishuUserId"] is None
