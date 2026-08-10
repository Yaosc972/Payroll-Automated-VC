from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from typing import Any
from urllib.parse import quote


def _safe_text(value: Any, fallback: str = "-") -> str:
    text = re.sub(r"[\x00-\x1f\x7f]", " ", str(value or "")).strip()
    if not text:
        return fallback
    for token in ("\\", "*", "_", "[", "]", "<", ">"):
        text = text.replace(token, f"\\{token}")
    return text[:300]


def _display_time(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "刚刚"
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        beijing = parsed.astimezone(timezone(timedelta(hours=8)))
        return beijing.strftime("%Y-%m-%d %H:%M（北京时间）")
    except ValueError:
        return _safe_text(raw)


def _button(label: str, url: str, *, primary: bool = True) -> dict[str, Any]:
    return {
        "tag": "button",
        "element_id": "open_console",
        "text": {"tag": "plain_text", "content": label},
        "type": "primary" if primary else "default",
        "width": "fill",
        "size": "medium",
        "behaviors": [{
            "type": "open_url",
            "default_url": url,
            "pc_url": url,
            "ios_url": url,
            "android_url": url,
        }],
        "margin": "8px 0px 0px 0px",
    }


def _base_card(title: str, subtitle: str, template: str, elements: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema": "2.0",
        "config": {"update_multi": True},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "subtitle": {"tag": "plain_text", "content": subtitle},
            "template": template,
            "padding": "12px 12px 12px 12px",
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 12px 12px",
            "vertical_spacing": "8px",
            "elements": elements,
        },
    }


def build_new_user_card(user: dict[str, Any], admin_url: str) -> dict[str, Any]:
    name = _safe_text(user.get("name"), "未命名用户")
    email = _safe_text(user.get("email"), "飞书账号未提供邮箱")
    created_at = _display_time(user.get("createdAt") or user.get("created_at"))
    return _base_card(
        "新用户等待权限配置",
        "Sigma Workbench · 权限中心",
        "orange",
        [
            {
                "tag": "markdown",
                "content": f"👤 **{name}** 首次登录了西格玛工作台，请确认是否需要开通业务权限。",
                "text_size": "normal",
            },
            {
                "tag": "column_set",
                "flex_mode": "bisect",
                "horizontal_spacing": "12px",
                "columns": [
                    {
                        "tag": "column",
                        "width": "weighted",
                        "weight": 1,
                        "elements": [{
                            "tag": "markdown",
                            "content": f"**账号信息**\n{email}\n\n**首次登录**\n{created_at}",
                        }],
                    },
                    {
                        "tag": "column",
                        "width": "weighted",
                        "weight": 1,
                        "elements": [{
                            "tag": "markdown",
                            "content": "**当前状态**\n<font color='orange'>待授权</font>\n\n**可访问模块**\n暂无",
                        }],
                    },
                ],
            },
            {
                "tag": "markdown",
                "content": "<font color='grey'>请在后台核对人员身份和岗位后再分配角色。未授权用户不能进入业务模块。</font>",
                "text_size": "notation",
            },
            _button("打开权限管理后台", admin_url),
        ],
    )


def _named_items(items: list[dict[str, Any]], key: str = "name") -> dict[str, str]:
    return {
        str(item.get("id") or ""): str(item.get(key) or item.get("id") or "")
        for item in items
        if isinstance(item, dict) and item.get("id")
    }


def build_permission_change_payload(
    before: dict[str, Any],
    after: dict[str, Any],
    actor: dict[str, Any],
) -> dict[str, Any]:
    before_roles = _named_items(list(before.get("roles") or []))
    after_roles = _named_items(list(after.get("roles") or []))
    before_modules = _named_items([
        item for item in list(before.get("modules") or []) if item.get("canEnter")
    ])
    after_modules = _named_items([
        item for item in list(after.get("modules") or []) if item.get("canEnter")
    ])
    user = dict(after.get("user") or {})
    return {
        "userId": str(user.get("id") or ""),
        "userName": str(user.get("name") or "西格玛用户"),
        "recipientOpenId": str(user.get("feishuOpenId") or ""),
        "actorId": str(actor.get("id") or ""),
        "actorName": str(actor.get("name") or "系统管理员"),
        "addedRoles": [after_roles[item] for item in sorted(set(after_roles) - set(before_roles))],
        "removedRoles": [before_roles[item] for item in sorted(set(before_roles) - set(after_roles))],
        "addedModules": [after_modules[item] for item in sorted(set(after_modules) - set(before_modules))],
        "removedModules": [before_modules[item] for item in sorted(set(before_modules) - set(after_modules))],
        "currentModules": [after_modules[item] for item in sorted(after_modules)],
        "changedAt": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
    }


def _list_text(items: list[str], empty: str = "无") -> str:
    values = [_safe_text(item) for item in items if str(item or "").strip()]
    return "\n".join(f"• {value}" for value in values) if values else empty


def build_permission_change_card(payload: dict[str, Any], workbench_url: str) -> dict[str, Any]:
    added_roles = list(payload.get("addedRoles") or [])
    removed_roles = list(payload.get("removedRoles") or [])
    added_modules = list(payload.get("addedModules") or [])
    removed_modules = list(payload.get("removedModules") or [])
    current_modules = list(payload.get("currentModules") or [])
    return _base_card(
        "权限配置已更新",
        "Sigma Workbench · 权限中心",
        "blue",
        [
            {
                "tag": "markdown",
                "content": f"你好，**{_safe_text(payload.get('userName'), '西格玛用户')}**。你的工作台权限已由 **{_safe_text(payload.get('actorName'), '系统管理员')}** 更新。",
                "text_size": "normal",
            },
            {
                "tag": "column_set",
                "flex_mode": "bisect",
                "horizontal_spacing": "12px",
                "columns": [
                    {
                        "tag": "column",
                        "width": "weighted",
                        "weight": 1,
                        "elements": [{
                            "tag": "markdown",
                            "content": f"<font color='green'>**新增**</font>\n{_list_text(added_roles + added_modules)}",
                        }],
                    },
                    {
                        "tag": "column",
                        "width": "weighted",
                        "weight": 1,
                        "elements": [{
                            "tag": "markdown",
                            "content": f"<font color='red'>**移除**</font>\n{_list_text(removed_roles + removed_modules)}",
                        }],
                    },
                ],
            },
            {
                "tag": "markdown",
                "content": f"**当前可访问模块**\n{_list_text(current_modules, '暂无业务模块权限')}",
            },
            {
                "tag": "markdown",
                "content": f"<font color='grey'>修改时间：{_display_time(payload.get('changedAt'))}\n如页面仍显示旧权限，请刷新工作台后重试。</font>",
                "text_size": "notation",
            },
            _button("打开西格玛工作台", workbench_url),
        ],
    )


def admin_user_url(base_url: str, user_id: str) -> str:
    return f"{str(base_url).rstrip('/')}/admin.html?user={quote(str(user_id), safe='')}"
