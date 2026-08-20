import json

from fastapi.testclient import TestClient

import bonus_platform.app as app_module
import bonus_platform.engine.admin_store as admin_store
import bonus_platform.engine.feedback_store as feedback_store
from bonus_platform.app import app
from bonus_platform.permission_notifications import (
    build_feedback_submitted_card,
    build_workbench_announcement_card,
)


def _configure_store(tmp_path, monkeypatch):
    db_path = tmp_path / "admin.sqlite"
    monkeypatch.setattr(admin_store, "get_admin_db_path", lambda: db_path)
    admin_store._STORE_INITIALIZED = False
    admin_store._STORE_INITIALIZED_TARGET = ""
    app_module._clear_current_user_cache()
    monkeypatch.setenv("SIGMA_ENABLE_MOCK_LOGIN", "1")
    return db_path


def _mock_login(client: TestClient, user_id: str = "payrollAdmin") -> None:
    response = client.post("/api/auth/mock-login", json={"userId": user_id})
    assert response.status_code == 200


def test_release_announcements_seed_one_plain_language_note_per_business_module(tmp_path, monkeypatch):
    db_path = _configure_store(tmp_path, monkeypatch)

    announcements = feedback_store.list_announcements(db_path=db_path)
    assert len(announcements) == 5
    assert {item["moduleId"] for item in announcements} == {
        "recruitment",
        "employee",
        "domestic",
        "fbu",
        "overseas",
    }
    assert {item["visualStyle"] for item in announcements} >= {"sunny", "mint", "blueprint", "peach"}
    assert all(item["imageUrl"].startswith("/assets/announcement-previews/") for item in announcements)
    assert all(item["imageUrl"].endswith("?v=20260820-hd") for item in announcements)
    assert all(item["imageAlt"].endswith("页面界面") for item in announcements)
    assert any(item["title"] == "FBU绩效奖金核算已上线" for item in announcements)
    assert any(item["title"] == "海外报账核对开放试用" for item in announcements)
    rendered = json.dumps(announcements, ensure_ascii=False)
    for jargon in ("API", "OCR", "Token", "数据库", "持久化", "对象存储"):
        assert jargon not in rendered

    assert len(feedback_store.list_announcements(db_path=db_path)) == 5


def test_feedback_submission_keeps_user_history_and_image_attachment(tmp_path, monkeypatch):
    _configure_store(tmp_path, monkeypatch)
    monkeypatch.setattr(admin_store.config, "ADMIN_BOOTSTRAP_IDENTIFIERS", ["姚硕灿"])
    monkeypatch.setitem(app_module.PERMISSION_NOTIFICATION_CONFIG, "admin_open_id", "ou_general_admin")
    monkeypatch.setitem(app_module.PERMISSION_NOTIFICATION_CONFIG, "feedback_admin_name", "姚硕灿")
    monkeypatch.setattr(app_module, "_dispatch_pending_permission_notifications", lambda: None)
    admin_store.upsert_feishu_user(
        feishu_open_id="ou_feedback_yao",
        feishu_union_id="on_feedback_yao",
        email="yao@example.com",
        name="姚硕灿",
    )

    with TestClient(app) as client:
        assert client.post(
            "/api/workbench/feedback",
            data={
                "category": "general",
                "moduleId": "fbu",
                "description": "切换页面后上月薪资上传状态没有显示。",
                "pagePath": "/fbu-performance.html",
            },
            files=[("attachments", ("issue.png", b"\x89PNG\r\nfeedback", "image/png"))],
        ).status_code == 401

        _mock_login(client)
        created = client.post(
            "/api/workbench/feedback",
            data={
                "category": "general",
                "moduleId": "fbu",
                "description": "切换页面后上月薪资上传状态没有显示。",
                "pagePath": "/fbu-performance.html?token=must-not-store",
            },
            files=[("attachments", ("issue.png", b"\x89PNG\r\nfeedback", "image/png"))],
        )

        assert created.status_code == 201
        feedback = created.json()["feedback"]
        assert feedback["id"].startswith("FB-")
        assert feedback["moduleId"] == "fbu"
        assert feedback["moduleName"] == "FBU美洲绩效奖金核算"
        assert feedback["moduleShortName"] == "FBU绩效"
        assert feedback["categoryLabel"] == "用户反馈"
        assert feedback["attachmentCount"] == 1
        assert feedback["pagePath"] == "/fbu-performance.html"

        mine = client.get("/api/workbench/feedback/mine")
        assert mine.status_code == 200
        assert [item["id"] for item in mine.json()["feedback"]] == [feedback["id"]]
        mine_attachment = mine.json()["feedback"][0]["attachments"][0]
        assert mine_attachment["filename"] == "issue.png"
        assert mine_attachment["contentType"] == "image/png"
        assert mine_attachment["sizeBytes"] == len(b"\x89PNG\r\nfeedback")

        detail = client.get(f"/api/workbench/feedback/{feedback['id']}")
        assert detail.status_code == 200
        attachment = detail.json()["feedback"]["attachments"][0]
        image = client.get(
            f"/api/workbench/feedback/{feedback['id']}/attachments/{attachment['id']}"
        )
        assert image.status_code == 200
        assert image.headers["content-type"] == "image/png"
        assert image.content == b"\x89PNG\r\nfeedback"

    pending = admin_store.list_pending_admin_notifications(limit=10)
    assert len(pending) == 1
    assert pending[0]["kind"] == "feedback_submitted"
    assert pending[0]["recipientOpenId"] == "ou_feedback_yao"
    assert pending[0]["payload"]["feedbackId"] == feedback["id"]
    assert pending[0]["payload"]["categoryLabel"] == "用户反馈"
    assert pending[0]["payload"]["attachmentCount"] == 1


def test_feedback_rejects_unsupported_or_oversized_attachments(tmp_path, monkeypatch):
    _configure_store(tmp_path, monkeypatch)
    monkeypatch.setattr(app_module, "_dispatch_pending_permission_notifications", lambda: None)

    with TestClient(app) as client:
        _mock_login(client)
        unsupported = client.post(
            "/api/workbench/feedback",
            data={"category": "suggestion", "moduleId": "home", "description": "建议增加快捷入口。"},
            files=[("attachments", ("notes.txt", b"not-an-image", "text/plain"))],
        )
        assert unsupported.status_code == 400
        assert "PNG、JPG 或 WebP" in unsupported.json()["detail"]

        oversized = client.post(
            "/api/workbench/feedback",
            data={"category": "suggestion", "moduleId": "home", "description": "建议增加快捷入口。"},
            files=[("attachments", ("large.png", b"x" * (5 * 1024 * 1024 + 1), "image/png"))],
        )
        assert oversized.status_code == 413


def test_users_only_see_their_own_feedback_while_system_admin_sees_all(tmp_path, monkeypatch):
    _configure_store(tmp_path, monkeypatch)
    monkeypatch.setattr(app_module, "_dispatch_pending_permission_notifications", lambda: None)

    with TestClient(app) as client:
        _mock_login(client, "recruitmentAdminUser")
        first = client.post(
            "/api/workbench/feedback",
            data={
                "category": "general",
                "moduleId": "recruitment",
                "description": "招聘奖金页面的提示需要更清楚。",
            },
        )
        assert first.status_code == 201

        _mock_login(client, "fbuAdminUser")
        second = client.post(
            "/api/workbench/feedback",
            data={
                "category": "general",
                "moduleId": "fbu",
                "description": "绩效数据切换后希望保留当前页签。",
            },
        )
        assert second.status_code == 201

        _mock_login(client, "recruitmentAdminUser")
        mine = client.get("/api/workbench/feedback/mine")
        assert mine.status_code == 200
        assert [item["id"] for item in mine.json()["feedback"]] == [first.json()["feedback"]["id"]]
        assert client.get(f"/api/workbench/feedback/{second.json()['feedback']['id']}").status_code == 404
        assert client.get("/api/admin/feedback").status_code == 403

        _mock_login(client, "payrollAdmin")
        admin_feedback = client.get("/api/admin/feedback")
        assert admin_feedback.status_code == 200
        assert {item["id"] for item in admin_feedback.json()["feedback"]} == {
            first.json()["feedback"]["id"],
            second.json()["feedback"]["id"],
        }


def test_admin_publishes_announcement_and_queues_feishu_cards_for_active_users(tmp_path, monkeypatch):
    _configure_store(tmp_path, monkeypatch)
    monkeypatch.setattr(app_module, "_dispatch_pending_permission_notifications", lambda: None)
    user = admin_store.upsert_feishu_user(
        feishu_open_id="ou_announcement_user",
        email="announcement.user@example.com",
        name="公告用户",
    )
    admin_store.set_user_roles(user["id"], ["fbuAdmin"])

    with TestClient(app) as client:
        _mock_login(client)
        response = client.post(
            "/api/admin/announcements",
            json={
                "kind": "feature",
                "title": "反馈与更新入口上线",
                "content": "首页右下角可以提交平台问题并查看更新。",
                "moduleId": "home",
                "pushToFeishu": True,
            },
        )
        assert response.status_code == 201
        announcement = response.json()["announcement"]
        assert announcement["id"].startswith("UPD-")
        assert announcement["kind"] == "feature"
        assert announcement["createdByName"] == "Payroll Admin"
        assert announcement["publishedAt"].endswith("Z")
        assert response.json()["queuedRecipients"] == 1

        public_list = client.get("/api/workbench/announcements")
        assert public_list.status_code == 200
        assert public_list.json()["announcements"][0]["title"] == "反馈与更新入口上线"

    pending = admin_store.list_pending_admin_notifications(limit=10)
    announcement_jobs = [item for item in pending if item["kind"] == "workbench_announcement"]
    assert len(announcement_jobs) == 1
    assert announcement_jobs[0]["recipientOpenId"] == "ou_announcement_user"
    assert announcement_jobs[0]["payload"]["announcementId"] == announcement["id"]


def test_feedback_and_announcement_cards_have_lightweight_link_actions():
    feedback_card = build_feedback_submitted_card(
        {
            "feedbackId": "FB-20260820-ABC123",
            "userName": "业务用户",
            "userOpenId": "ou_user",
            "categoryLabel": "功能问题",
            "moduleName": "FBU美洲绩效奖金核算",
            "description": "页面切换后上传状态消失。",
            "attachmentCount": 2,
            "createdAt": "2026-08-20T03:20:00Z",
        },
        "https://sigma.example.com/admin.html?feedback=FB-20260820-ABC123#feedbackCenter",
        "https://applink.feishu.cn/client/chat/open?openId=ou_user",
    )
    rendered_feedback = json.dumps(feedback_card, ensure_ascii=False)
    assert feedback_card["schema"] == "2.0"
    assert "查看详情" in rendered_feedback
    assert "联系用户" in rendered_feedback
    assert "2 张截图" in rendered_feedback

    announcement_card = build_workbench_announcement_card(
        {
            "title": "FBU 核算检查优化",
            "kindLabel": "功能更新",
            "moduleName": "FBU美洲绩效奖金核算",
            "content": "薪资数据页签切换后会保留上传状态。",
            "publishedAt": "2026-08-20T03:30:00Z",
        },
        "https://sigma.example.com/?announcement=UPD-20260820-ABC123",
    )
    rendered_announcement = json.dumps(announcement_card, ensure_ascii=False)
    assert announcement_card["schema"] == "2.0"
    assert "功能更新" in rendered_announcement
    assert "打开工作台" in rendered_announcement
