import json
from pathlib import Path

from fastapi.testclient import TestClient

import bonus_platform.app as app_module
import bonus_platform.engine.admin_store as admin_store
from bonus_platform.app import app
from bonus_platform.permission_notifications import (
    build_new_user_card,
    build_permission_change_card,
    build_permission_change_payload,
)


ROOT = Path(__file__).resolve().parents[1]


def _button_url(card: dict) -> str:
    button = next(element for element in card["body"]["elements"] if element["tag"] == "button")
    behavior = next(item for item in button["behaviors"] if item["type"] == "open_url")
    return behavior["default_url"]


def test_new_user_card_is_polished_json_v2_with_admin_entry():
    card = build_new_user_card(
        {
            "id": "feishu_ou_new",
            "name": "新用户",
            "email": "new.user@example.com",
            "createdAt": "2026-08-10T08:00:00Z",
        },
        "https://sigma-workbench.vercel.app/admin.html?user=feishu_ou_new",
    )

    assert card["schema"] == "2.0"
    assert card["header"]["template"] == "orange"
    assert card["header"]["title"]["content"] == "新用户等待权限配置"
    rendered = json.dumps(card, ensure_ascii=False)
    assert "新用户" in rendered
    assert "当前状态" in rendered
    assert "待授权" in rendered
    assert _button_url(card).endswith("/admin.html?user=feishu_ou_new")


def test_permission_change_payload_reports_role_and_module_differences():
    before = {
        "user": {"id": "feishu_ou_user", "name": "业务用户", "feishuOpenId": "ou_user"},
        "roles": [{"id": "employeeAdmin", "name": "国内正式工核算管理员"}],
        "modules": [
            {"id": "employee", "name": "中国区正式工薪酬核算", "canEnter": True},
            {"id": "fbu", "name": "FBU美洲绩效奖金核算", "canEnter": False},
        ],
    }
    after = {
        "user": {"id": "feishu_ou_user", "name": "业务用户", "feishuOpenId": "ou_user"},
        "roles": [{"id": "fbuAdmin", "name": "FBU美洲绩效核算管理员"}],
        "modules": [
            {"id": "employee", "name": "中国区正式工薪酬核算", "canEnter": False},
            {"id": "fbu", "name": "FBU美洲绩效奖金核算", "canEnter": True},
        ],
    }

    payload = build_permission_change_payload(
        before,
        after,
        {"id": "feishu_ou_admin", "name": "姚硕灿"},
    )

    assert payload["recipientOpenId"] == "ou_user"
    assert payload["addedRoles"] == ["FBU美洲绩效核算管理员"]
    assert payload["removedRoles"] == ["国内正式工核算管理员"]
    assert payload["addedModules"] == ["FBU美洲绩效奖金核算"]
    assert payload["removedModules"] == ["中国区正式工薪酬核算"]
    assert payload["actorName"] == "姚硕灿"


def test_permission_change_card_uses_clear_change_sections_and_workbench_link():
    card = build_permission_change_card(
        {
            "userName": "业务用户",
            "actorName": "姚硕灿",
            "addedRoles": ["FBU美洲绩效核算管理员"],
            "removedRoles": ["国内正式工核算管理员"],
            "addedModules": ["FBU美洲绩效奖金核算"],
            "removedModules": ["中国区正式工薪酬核算"],
            "currentModules": ["FBU美洲绩效奖金核算"],
            "changedAt": "2026-08-10T08:30:00Z",
        },
        "https://sigma-workbench.vercel.app/",
    )

    assert card["schema"] == "2.0"
    assert card["header"]["template"] == "blue"
    rendered = json.dumps(card, ensure_ascii=False)
    assert "权限配置已更新" in rendered
    assert "新增" in rendered and "移除" in rendered
    assert "FBU美洲绩效奖金核算" in rendered
    assert _button_url(card) == "https://sigma-workbench.vercel.app/"


def test_admin_card_deep_link_selects_and_expands_target_user():
    js = (ROOT / "bonus_platform" / "static" / "admin.js").read_text(encoding="utf-8")

    assert 'new URLSearchParams(window.location.search).get("user")' in js
    assert 'dropdown.dataset.user === requestedUserId' in js
    assert "dropdown.open = true" in js
    assert "scrollIntoView" in js


def test_notification_outbox_deduplicates_and_tracks_delivery(tmp_path, monkeypatch):
    db_path = tmp_path / "admin.sqlite"
    monkeypatch.setattr(admin_store, "get_admin_db_path", lambda: db_path)
    admin_store._STORE_INITIALIZED = False
    admin_store._STORE_INITIALIZED_TARGET = ""

    first = admin_store.enqueue_admin_notification(
        event_key="new-user:feishu_ou_new",
        kind="new_user_pending",
        recipient_open_id="ou_admin",
        payload={"userName": "新用户"},
    )
    duplicate = admin_store.enqueue_admin_notification(
        event_key="new-user:feishu_ou_new",
        kind="new_user_pending",
        recipient_open_id="ou_admin",
        payload={"userName": "不应覆盖"},
    )

    assert first["id"] == duplicate["id"]
    assert duplicate["payload"]["userName"] == "新用户"
    assert admin_store.list_pending_admin_notifications(limit=10) == [first]
    assert admin_store.claim_admin_notification(first["id"]) is True
    assert admin_store.claim_admin_notification(first["id"]) is False

    admin_store.mark_admin_notification_failed(first["id"], "temporary failure")
    failed = admin_store.get_admin_notification(first["id"])
    assert failed["status"] == "pending"
    assert failed["attemptCount"] == 1
    assert failed["lastError"] == "temporary failure"

    admin_store.mark_admin_notification_sent(first["id"], "om_message")
    sent = admin_store.get_admin_notification(first["id"])
    assert sent["status"] == "sent"
    assert sent["messageId"] == "om_message"
    assert admin_store.list_pending_admin_notifications(limit=10) == []


def _configure_feishu_callback(monkeypatch, open_id="ou_new_user"):
    monkeypatch.setitem(app_module.AUTH_CONFIG, "feishu_app_id", "cli_test")
    monkeypatch.setitem(app_module.AUTH_CONFIG, "feishu_app_secret", "secret_test")
    monkeypatch.setitem(
        app_module.AUTH_CONFIG,
        "feishu_redirect_uri",
        "https://example.com/api/auth/feishu/callback",
    )
    monkeypatch.setattr(app_module, "_get_feishu_app_access_token", lambda: "app-token")
    monkeypatch.setattr(
        app_module,
        "_get_feishu_user_access_token",
        lambda code, app_access_token: {"access_token": "user-token", "open_id": open_id},
    )
    monkeypatch.setattr(
        app_module,
        "_get_feishu_user_info",
        lambda user_access_token: {
            "open_id": open_id,
            "union_id": f"on_{open_id}",
            "email": "new.user@example.com",
            "avatar_url": "https://example.com/avatar.png",
            "name": "新用户",
        },
    )


def test_first_feishu_login_queues_one_admin_card_only(tmp_path, monkeypatch):
    db_path = tmp_path / "admin.sqlite"
    monkeypatch.setattr(admin_store, "get_admin_db_path", lambda: db_path)
    admin_store._STORE_INITIALIZED = False
    admin_store._STORE_INITIALIZED_TARGET = ""
    _configure_feishu_callback(monkeypatch)
    monkeypatch.setitem(app_module.PERMISSION_NOTIFICATION_CONFIG, "admin_open_id", "ou_admin")
    monkeypatch.setitem(app_module.PERMISSION_NOTIFICATION_CONFIG, "public_url", "https://sigma.example.com")
    monkeypatch.setattr(app_module, "_dispatch_pending_permission_notifications", lambda: None)

    with TestClient(app) as client:
        for state in ("state-one", "state-two"):
            client.cookies.set("sigma_feishu_state", state)
            callback = client.get(
                "/api/auth/feishu/callback",
                params={"code": f"code-{state}", "state": state},
                follow_redirects=False,
            )
            assert callback.status_code == 302

    pending = admin_store.list_pending_admin_notifications(limit=10)
    assert len(pending) == 1
    assert pending[0]["kind"] == "new_user_pending"
    assert pending[0]["recipientOpenId"] == "ou_admin"
    assert pending[0]["payload"]["userName"] == "新用户"


def test_role_update_queues_diff_card_and_delivery_failure_does_not_rollback(tmp_path, monkeypatch):
    db_path = tmp_path / "admin.sqlite"
    monkeypatch.setattr(admin_store, "get_admin_db_path", lambda: db_path)
    admin_store._STORE_INITIALIZED = False
    admin_store._STORE_INITIALIZED_TARGET = ""
    monkeypatch.setenv("SIGMA_ENABLE_MOCK_LOGIN", "1")
    monkeypatch.setitem(app_module.PERMISSION_NOTIFICATION_CONFIG, "admin_open_id", "ou_admin")
    monkeypatch.setitem(app_module.PERMISSION_NOTIFICATION_CONFIG, "public_url", "https://sigma.example.com")
    monkeypatch.setattr(
        app_module,
        "_send_feishu_permission_card",
        lambda notification: (_ for _ in ()).throw(RuntimeError("temporary feishu failure")),
    )
    target = admin_store.upsert_feishu_user(
        feishu_open_id="ou_target_user",
        email="target@example.com",
        name="目标用户",
    )

    with TestClient(app) as client:
        assert client.post("/api/auth/mock-login", json={"userId": "payrollAdmin"}).status_code == 200
        response = client.put(
            f"/api/admin/users/{target['id']}/roles",
            json={"roleIds": ["fbuAdmin"]},
        )

    assert response.status_code == 200
    assert response.json()["user"]["roleIds"] == ["fbuAdmin"]
    current = admin_store.get_current_user(target["id"])
    assert current["user"]["status"] == "active"
    assert [role["id"] for role in current["roles"]] == ["fbuAdmin"]

    pending = admin_store.list_pending_admin_notifications(limit=10)
    assert len(pending) == 1
    notification = pending[0]
    assert notification["kind"] == "permission_changed"
    assert notification["recipientOpenId"] == "ou_target_user"
    assert notification["payload"]["addedRoles"] == ["FBU美洲绩效核算管理员"]
    assert notification["payload"]["addedModules"] == ["FBU美洲绩效奖金核算"]
    assert notification["attemptCount"] == 1
    assert notification["lastError"] == "temporary feishu failure"


def test_feishu_transport_sends_interactive_json_v2_card(monkeypatch):
    captured = {}
    monkeypatch.setitem(app_module.PERMISSION_NOTIFICATION_CONFIG, "public_url", "https://sigma.example.com")
    monkeypatch.setattr(app_module, "_get_feishu_tenant_access_token", lambda: "tenant-token")

    def fake_post(path, payload, token=None):
        captured.update({"path": path, "payload": payload, "token": token})
        return {"code": 0, "data": {"message_id": "om_card_message"}}

    monkeypatch.setattr(app_module, "_feishu_post_json", fake_post)

    message_id = app_module._send_feishu_permission_card({
        "kind": "new_user_pending",
        "recipientOpenId": "ou_admin",
        "payload": {
            "userId": "feishu_ou_new",
            "userName": "新用户",
            "name": "新用户",
            "email": "new@example.com",
            "createdAt": "2026-08-10T08:00:00Z",
        },
    })

    assert message_id == "om_card_message"
    assert captured["path"] == "/im/v1/messages?receive_id_type=open_id"
    assert captured["token"] == "tenant-token"
    assert captured["payload"]["receive_id"] == "ou_admin"
    assert captured["payload"]["msg_type"] == "interactive"
    assert json.loads(captured["payload"]["content"])["schema"] == "2.0"
