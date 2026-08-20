from __future__ import annotations

from pathlib import PurePath
import re
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from ..time_utils import utcnow_naive
from . import admin_store


MODULE_NAMES = {
    "home": "HRAS 全球薪酬核算工作台",
    "recruitment": "全球招聘奖金核算",
    "employee": "中国区正式工薪酬核算",
    "domestic": "中国区外包工薪酬核算",
    "fbu": "FBU美洲绩效奖金核算",
    "overseas": "海外劳务报账核对",
}
MODULE_SHORT_NAMES = {
    "home": "首页",
    "recruitment": "招聘奖金",
    "employee": "正式工",
    "domestic": "外包工",
    "fbu": "FBU绩效",
    "overseas": "海外报账",
}
CATEGORY_LABELS = {
    "general": "用户反馈",
    "function_issue": "功能问题",
    "data_issue": "数据问题",
    "suggestion": "使用建议",
}
ANNOUNCEMENT_KIND_LABELS = {
    "feature": "功能更新",
    "known_issue": "问题提示",
}
ANNOUNCEMENT_STYLES = {"sunny", "blueprint", "peach", "mint"}
ANNOUNCEMENT_MEDIA = {
    "home": {
        "imageUrl": "/assets/announcement-previews/home.webp?v=20260820-hd",
        "imageAlt": "HRAS 全球薪酬核算工作台首页界面",
    },
    "recruitment": {
        "imageUrl": "/assets/announcement-previews/recruitment.webp?v=20260820-hd",
        "imageAlt": "招聘奖金核算页面界面",
    },
    "employee": {
        "imageUrl": "/assets/announcement-previews/employee.webp?v=20260820-hd",
        "imageAlt": "中国区正式工薪酬核算页面界面",
    },
    "domestic": {
        "imageUrl": "/assets/announcement-previews/domestic.webp?v=20260820-hd",
        "imageAlt": "中国区外包工薪酬核算页面界面",
    },
    "fbu": {
        "imageUrl": "/assets/announcement-previews/fbu.webp?v=20260820-hd",
        "imageAlt": "FBU 美洲绩效奖金核算页面界面",
    },
    "overseas": {
        "imageUrl": "/assets/announcement-previews/overseas.webp?v=20260820-hd",
        "imageAlt": "海外劳务报账核对页面界面",
    },
}


def _now() -> str:
    return utcnow_naive().replace(microsecond=0).isoformat() + "Z"


def _public_id(prefix: str) -> str:
    day = utcnow_naive().strftime("%Y%m%d")
    return f"{prefix}-{day}-{uuid4().hex[:6].upper()}"


def _safe_filename(value: str) -> str:
    name = PurePath(str(value or "image")).name
    name = re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]", "_", name).strip("._")
    return (name or "image")[:120]


def _safe_page_path(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    path = parsed.path if parsed.scheme or parsed.netloc else raw.split("?", 1)[0].split("#", 1)[0]
    return path[:300] if path.startswith("/") else ""


def _feedback_summary(row: Any) -> dict[str, Any]:
    data = dict(row)
    return {
        "id": str(data["id"]),
        "userId": str(data["user_id"]),
        "userName": str(data["user_name"]),
        "userOpenId": str(data.get("user_open_id") or ""),
        "category": str(data["category"]),
        "categoryLabel": CATEGORY_LABELS.get(str(data["category"]), str(data["category"])),
        "moduleId": str(data["module_id"]),
        "moduleName": str(data["module_name"]),
        "moduleShortName": MODULE_SHORT_NAMES.get(str(data["module_id"]), str(data["module_name"])),
        "description": str(data["description"]),
        "pagePath": str(data.get("page_path") or ""),
        "createdAt": str(data["created_at"]),
        "attachmentCount": int(data.get("attachment_count") or 0),
    }


def _attachment_summary(row: Any) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "filename": str(row["filename"]),
        "contentType": str(row["content_type"]),
        "sizeBytes": int(row["size_bytes"]),
        "createdAt": str(row["created_at"]),
    }


def create_feedback(
    *,
    user: dict[str, Any],
    category: str,
    module_id: str,
    description: str,
    page_path: str = "",
    user_agent: str = "",
    attachments: list[dict[str, Any]] | None = None,
    db_path=None,
) -> dict[str, Any]:
    admin_store.init_admin_store(db_path)
    if category not in CATEGORY_LABELS:
        raise ValueError("invalid_feedback_category")
    if module_id not in MODULE_NAMES:
        raise ValueError("invalid_feedback_module")
    cleaned_description = str(description or "").strip()
    if len(cleaned_description) < 4 or len(cleaned_description) > 4000:
        raise ValueError("invalid_feedback_description")
    feedback_id = _public_id("FB")
    created_at = _now()
    attachment_rows = list(attachments or [])
    with admin_store._connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO workbench_feedback (
              id, user_id, user_name, user_open_id, category, module_id, module_name,
              description, page_path, user_agent, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                feedback_id,
                str(user.get("id") or ""),
                str(user.get("name") or "未命名用户")[:160],
                str(user.get("feishuOpenId") or "")[:160],
                category,
                module_id,
                MODULE_NAMES[module_id],
                cleaned_description,
                _safe_page_path(page_path),
                str(user_agent or "")[:300],
                created_at,
            ),
        )
        for item in attachment_rows:
            content = bytes(item.get("content") or b"")
            connection.execute(
                """
                INSERT INTO workbench_feedback_attachments (
                  id, feedback_id, filename, content_type, size_bytes, content, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"ATT-{uuid4().hex[:12].upper()}",
                    feedback_id,
                    _safe_filename(str(item.get("filename") or "image")),
                    str(item.get("contentType") or "application/octet-stream")[:100],
                    len(content),
                    content,
                    created_at,
                ),
            )
        connection.commit()
    return get_feedback(feedback_id, db_path=db_path)


def list_feedback_for_user(user_id: str, limit: int = 50, db_path=None) -> list[dict[str, Any]]:
    admin_store.init_admin_store(db_path)
    with admin_store._connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT f.*, COUNT(a.id) AS attachment_count
            FROM workbench_feedback f
            LEFT JOIN workbench_feedback_attachments a ON a.feedback_id = f.id
            WHERE f.user_id = ?
            GROUP BY f.id
            ORDER BY f.created_at DESC
            LIMIT ?
            """,
            (user_id, max(1, min(int(limit), 100))),
        ).fetchall()
        feedback = [_feedback_summary(row) for row in rows]
        if not feedback:
            return []
        feedback_ids = [item["id"] for item in feedback]
        placeholders = ", ".join("?" for _ in feedback_ids)
        attachment_rows = connection.execute(
            f"""
            SELECT id, feedback_id, filename, content_type, size_bytes, created_at
            FROM workbench_feedback_attachments
            WHERE feedback_id IN ({placeholders})
            ORDER BY created_at, id
            """,
            tuple(feedback_ids),
        ).fetchall()
    attachments_by_feedback = {feedback_id: [] for feedback_id in feedback_ids}
    for attachment in attachment_rows:
        attachments_by_feedback[str(attachment["feedback_id"])].append(_attachment_summary(attachment))
    for item in feedback:
        item["attachments"] = attachments_by_feedback[item["id"]]
    return feedback


def list_feedback_for_admin(limit: int = 100, db_path=None) -> list[dict[str, Any]]:
    admin_store.init_admin_store(db_path)
    with admin_store._connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT f.*, COUNT(a.id) AS attachment_count
            FROM workbench_feedback f
            LEFT JOIN workbench_feedback_attachments a ON a.feedback_id = f.id
            GROUP BY f.id
            ORDER BY f.created_at DESC
            LIMIT ?
            """,
            (max(1, min(int(limit), 200)),),
        ).fetchall()
    return [_feedback_summary(row) for row in rows]


def get_feedback(feedback_id: str, db_path=None) -> dict[str, Any]:
    admin_store.init_admin_store(db_path)
    with admin_store._connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT f.*, COUNT(a.id) AS attachment_count
            FROM workbench_feedback f
            LEFT JOIN workbench_feedback_attachments a ON a.feedback_id = f.id
            WHERE f.id = ?
            GROUP BY f.id
            """,
            (feedback_id,),
        ).fetchone()
        if not row:
            raise KeyError("feedback_not_found")
        attachments = connection.execute(
            """
            SELECT id, filename, content_type, size_bytes, created_at
            FROM workbench_feedback_attachments
            WHERE feedback_id = ?
            ORDER BY created_at, id
            """,
            (feedback_id,),
        ).fetchall()
    result = _feedback_summary(row)
    result["attachments"] = [_attachment_summary(item) for item in attachments]
    return result


def get_feedback_attachment(feedback_id: str, attachment_id: str, db_path=None) -> dict[str, Any]:
    admin_store.init_admin_store(db_path)
    with admin_store._connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT id, feedback_id, filename, content_type, size_bytes, content
            FROM workbench_feedback_attachments
            WHERE id = ? AND feedback_id = ?
            """,
            (attachment_id, feedback_id),
        ).fetchone()
    if not row:
        raise KeyError("attachment_not_found")
    result = dict(row)
    result["content"] = bytes(result["content"])
    return result


def _announcement_from_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    module_id = str(data["module_id"])
    media = ANNOUNCEMENT_MEDIA.get(module_id, {})
    return {
        "id": str(data["id"]),
        "kind": str(data["kind"]),
        "kindLabel": ANNOUNCEMENT_KIND_LABELS.get(str(data["kind"]), str(data["kind"])),
        "title": str(data["title"]),
        "content": str(data["content"]),
        "moduleId": module_id,
        "moduleName": str(data["module_name"]),
        "visualStyle": str(data["visual_style"]),
        "imageUrl": str(media.get("imageUrl") or ""),
        "imageAlt": str(media.get("imageAlt") or ""),
        "createdBy": str(data["created_by"]),
        "createdByName": str(data["created_by_name"]),
        "publishedAt": str(data["published_at"]),
    }


def create_announcement(
    *,
    actor: dict[str, Any],
    kind: str,
    title: str,
    content: str,
    module_id: str = "home",
    visual_style: str = "sunny",
    db_path=None,
) -> dict[str, Any]:
    admin_store.init_admin_store(db_path)
    if kind not in ANNOUNCEMENT_KIND_LABELS:
        raise ValueError("invalid_announcement_kind")
    if module_id not in MODULE_NAMES:
        raise ValueError("invalid_announcement_module")
    if visual_style not in ANNOUNCEMENT_STYLES:
        raise ValueError("invalid_announcement_style")
    cleaned_title = str(title or "").strip()
    cleaned_content = str(content or "").strip()
    if len(cleaned_title) < 2 or len(cleaned_title) > 120:
        raise ValueError("invalid_announcement_title")
    if len(cleaned_content) < 2 or len(cleaned_content) > 8000:
        raise ValueError("invalid_announcement_content")
    announcement_id = _public_id("UPD")
    published_at = _now()
    with admin_store._connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO workbench_announcements (
              id, kind, title, content, module_id, module_name, visual_style,
              created_by, created_by_name, published_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                announcement_id,
                kind,
                cleaned_title,
                cleaned_content,
                module_id,
                MODULE_NAMES[module_id],
                visual_style,
                str(actor.get("id") or ""),
                str(actor.get("name") or "系统管理员")[:160],
                published_at,
            ),
        )
        connection.commit()
    return get_announcement(announcement_id, db_path=db_path)


def get_announcement(announcement_id: str, db_path=None) -> dict[str, Any]:
    admin_store.init_admin_store(db_path)
    with admin_store._connect(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM workbench_announcements WHERE id = ?",
            (announcement_id,),
        ).fetchone()
    if not row:
        raise KeyError("announcement_not_found")
    return _announcement_from_row(row)


def list_announcements(limit: int = 50, db_path=None) -> list[dict[str, Any]]:
    admin_store.init_admin_store(db_path)
    with admin_store._connect(db_path) as connection:
        rows = connection.execute(
            "SELECT * FROM workbench_announcements ORDER BY published_at DESC LIMIT ?",
            (max(1, min(int(limit), 100)),),
        ).fetchall()
    return [_announcement_from_row(row) for row in rows]
