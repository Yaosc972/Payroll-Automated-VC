from __future__ import annotations

import os
import re
import secrets
from typing import Any, Optional
from urllib.parse import quote, urlencode

import httpx
from fastapi import APIRouter, Body, Cookie, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from .config import AUTH_CONFIG
from .engine.admin_store import (
    admin_store_health,
    create_session,
    delete_session,
    get_admin_state,
    get_current_user,
    get_session_user_id,
    init_admin_store,
    upsert_feishu_user,
)


router = APIRouter()

SESSION_COOKIE_NAME = "sigma_session"
FEISHU_STATE_COOKIE_NAME = "sigma_feishu_state"
AUTH_NEXT_COOKIE_NAME = "sigma_auth_next"
FEISHU_API_BASE_URL = "https://open.feishu.cn/open-apis"
SAFE_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,127}$")


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _is_vercel_runtime() -> bool:
    return bool(os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV") or os.environ.get("VERCEL_URL"))


def labor_auth_required() -> bool:
    configured = os.environ.get("SIGMA_LABOR_AUTH_REQUIRED")
    if configured is not None:
        return _env_flag("SIGMA_LABOR_AUTH_REQUIRED")
    return _is_vercel_runtime()


def mock_auth_enabled() -> bool:
    return not _is_vercel_runtime() and _env_flag("SIGMA_ENABLE_MOCK_LOGIN", False)


def labor_auth_health(env: Optional[dict[str, str]] = None) -> dict[str, Any]:
    source = env if env is not None else os.environ

    def truthy(name: str, default: bool = False) -> bool:
        value = source.get(name)
        if value is None:
            return default
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    required = truthy(
        "SIGMA_LABOR_AUTH_REQUIRED",
        bool(source.get("VERCEL") or source.get("VERCEL_ENV") or source.get("VERCEL_URL")),
    )
    provider_configured = all(
        str(source.get(key) or "").strip()
        for key in ("FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_REDIRECT_URI")
    )
    secure_cookie = truthy("SESSION_COOKIE_SECURE", False)
    mock_enabled = not bool(
        source.get("VERCEL") or source.get("VERCEL_ENV") or source.get("VERCEL_URL")
    ) and truthy("SIGMA_ENABLE_MOCK_LOGIN", False)
    database = admin_store_health()
    database_backend = str(database.get("backend") or "")
    database_ready = bool(database.get("ready"))
    ready = bool(
        required
        and provider_configured
        and secure_cookie
        and not mock_enabled
        and database_backend == "postgres"
        and database_ready
    )
    return {
        "ready": ready,
        "required": required,
        "provider": "feishu" if provider_configured else "",
        "providerConfigured": provider_configured,
        "databaseBackend": database_backend,
        "databaseReady": database_ready,
        "secureCookie": secure_cookie,
        "mockLoginEnabled": mock_enabled,
    }


def _safe_next_url(value: str | None, fallback: str = "/") -> str:
    candidate = str(value or "").strip()
    if not candidate.startswith("/") or candidate.startswith("//") or "\r" in candidate or "\n" in candidate:
        return fallback
    return candidate


def _safe_id(value: object, field_name: str = "id") -> str:
    candidate = str(value or "").strip()
    if not SAFE_ID_RE.fullmatch(candidate):
        raise HTTPException(status_code=400, detail=f"无效的 {field_name}。")
    return candidate


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=bool(AUTH_CONFIG["session_cookie_secure"]),
        max_age=7 * 24 * 60 * 60,
        path="/",
    )


def session_user_id(request: Request) -> str | None:
    token = str(request.cookies.get(SESSION_COOKIE_NAME) or "").strip()
    if not token:
        return None
    try:
        init_admin_store()
        return get_session_user_id(token)
    except KeyError:
        return None


def current_user_from_request(request: Request) -> dict[str, Any] | None:
    user_id = session_user_id(request)
    if not user_id:
        return None
    try:
        current = get_current_user(user_id)
    except KeyError:
        return None
    user = current.get("user") if isinstance(current, dict) else None
    if not isinstance(user, dict) or user.get("status") != "active":
        return None
    return current


def user_can_enter_module(current: dict[str, Any], module_id: str) -> bool:
    return any(
        module.get("id") == module_id and module.get("enabled") and module.get("canEnter")
        for module in current.get("modules", [])
        if isinstance(module, dict)
    )


def user_is_system_admin(current: dict[str, Any]) -> bool:
    return any(role.get("id") == "admin" for role in current.get("roles", []) if isinstance(role, dict))


def require_current_user(request: Request) -> dict[str, Any]:
    current = current_user_from_request(request)
    if current is None:
        raise HTTPException(status_code=401, detail="未登录或登录已失效。")
    return current


@router.get("/api/auth/mock-users")
def api_auth_mock_users() -> dict[str, Any]:
    if not mock_auth_enabled():
        raise HTTPException(status_code=404, detail="Not Found")
    init_admin_store()
    users = get_admin_state()["users"]
    return {
        "users": [
            {
                "id": user["id"],
                "name": user["name"],
                "email": user.get("email"),
                "roleIds": user.get("roleIds", []),
            }
            for user in users
        ]
    }


@router.post("/api/auth/mock-login")
def api_auth_mock_login(response: Response, payload: dict = Body(...)) -> dict[str, Any]:
    if not mock_auth_enabled():
        raise HTTPException(status_code=404, detail="Not Found")
    user_id = _safe_id(payload.get("userId") or payload.get("user_id"), "user_id")
    init_admin_store()
    try:
        token = create_session(user_id)
        current = get_current_user(user_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="用户不存在。") from exc
    _set_session_cookie(response, token)
    return current


@router.post("/api/auth/logout")
def api_auth_logout(response: Response, sigma_session: Optional[str] = Cookie(default=None)) -> dict[str, str]:
    if sigma_session:
        init_admin_store()
        delete_session(sigma_session)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return {"status": "ok"}


@router.get("/api/auth/logout")
def api_auth_logout_redirect(
    next: str = "/login.html?next=%2F",
    sigma_session: Optional[str] = Cookie(default=None),
) -> RedirectResponse:
    if sigma_session:
        init_admin_store()
        delete_session(sigma_session)
    response = RedirectResponse(_safe_next_url(next, "/login.html?next=%2F"), status_code=302)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return response


@router.get("/api/me")
def api_me(request: Request) -> dict[str, Any]:
    return require_current_user(request)


def _feishu_post_json(path: str, payload: dict[str, Any], token: str | None = None) -> dict[str, Any]:
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(f"{FEISHU_API_BASE_URL}{path}", json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="飞书认证接口请求失败。") from exc
    if not isinstance(data, dict) or data.get("code") != 0:
        raise HTTPException(status_code=502, detail="飞书认证接口返回失败。")
    return data


def _feishu_get_json(path: str, token: str) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(
                f"{FEISHU_API_BASE_URL}{path}",
                headers={"Authorization": f"Bearer {token}"},
            )
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="飞书用户信息请求失败。") from exc
    if not isinstance(data, dict) or data.get("code") != 0:
        raise HTTPException(status_code=502, detail="飞书用户信息返回失败。")
    return data


@router.get("/api/auth/feishu/config")
def api_auth_feishu_config() -> dict[str, Any]:
    configured = bool(
        AUTH_CONFIG["feishu_app_id"]
        and AUTH_CONFIG["feishu_app_secret"]
        and AUTH_CONFIG["feishu_redirect_uri"]
    )
    return {"configured": configured, "redirectUri": AUTH_CONFIG["feishu_redirect_uri"] if configured else ""}


@router.get("/api/auth/feishu/login")
def api_auth_feishu_login(next: str = "/") -> RedirectResponse:
    if not AUTH_CONFIG["feishu_app_id"] or not AUTH_CONFIG["feishu_redirect_uri"]:
        raise HTTPException(status_code=503, detail="飞书应用未配置。")
    state = secrets.token_urlsafe(24)
    params = urlencode(
        {
            "app_id": AUTH_CONFIG["feishu_app_id"],
            "redirect_uri": AUTH_CONFIG["feishu_redirect_uri"],
            "state": state,
        }
    )
    response = RedirectResponse(f"{AUTH_CONFIG['feishu_auth_url']}?{params}", status_code=302)
    response.set_cookie(
        FEISHU_STATE_COOKIE_NAME,
        state,
        httponly=True,
        samesite="lax",
        secure=bool(AUTH_CONFIG["session_cookie_secure"]),
        max_age=10 * 60,
        path="/",
    )
    response.set_cookie(
        AUTH_NEXT_COOKIE_NAME,
        _safe_next_url(next),
        httponly=True,
        samesite="lax",
        secure=bool(AUTH_CONFIG["session_cookie_secure"]),
        max_age=10 * 60,
        path="/",
    )
    return response


@router.get("/api/auth/feishu/callback")
def api_auth_feishu_callback(
    code: str = "",
    state: str = "",
    sigma_feishu_state: Optional[str] = Cookie(default=None),
    sigma_auth_next: Optional[str] = Cookie(default=None),
) -> RedirectResponse:
    if (
        not code
        or not state
        or not sigma_feishu_state
        or not secrets.compare_digest(state, sigma_feishu_state)
    ):
        raise HTTPException(status_code=400, detail="飞书登录 state 校验失败。")
    if not AUTH_CONFIG["feishu_app_id"] or not AUTH_CONFIG["feishu_app_secret"]:
        raise HTTPException(status_code=503, detail="飞书应用密钥未配置。")

    app_token_payload = _feishu_post_json(
        "/auth/v3/app_access_token/internal",
        {"app_id": AUTH_CONFIG["feishu_app_id"], "app_secret": AUTH_CONFIG["feishu_app_secret"]},
    )
    app_token = str(app_token_payload.get("app_access_token") or "")
    token_payload = _feishu_post_json(
        "/authen/v1/access_token",
        {"grant_type": "authorization_code", "code": code},
        token=app_token,
    )
    token_data = token_payload.get("data") if isinstance(token_payload.get("data"), dict) else {}
    user_token = str(token_data.get("access_token") or "")
    user_payload = _feishu_get_json("/authen/v1/user_info", user_token)
    user_info = user_payload.get("data") if isinstance(user_payload.get("data"), dict) else {}
    open_id = str(user_info.get("open_id") or token_data.get("open_id") or "").strip()
    if not open_id:
        raise HTTPException(status_code=502, detail="飞书用户身份缺少 open_id。")

    init_admin_store()
    user = upsert_feishu_user(
        feishu_open_id=open_id,
        feishu_union_id=str(user_info.get("union_id") or token_data.get("union_id") or "").strip() or None,
        email=str(user_info.get("email") or user_info.get("enterprise_email") or "").strip() or None,
        avatar_url=str(user_info.get("avatar_url") or user_info.get("avatar_big") or "").strip() or None,
        name=str(user_info.get("name") or user_info.get("en_name") or "").strip() or open_id,
    )
    session_token = create_session(user["id"], action="feishu_login")
    response = RedirectResponse(_safe_next_url(sigma_auth_next), status_code=302)
    response.delete_cookie(FEISHU_STATE_COOKIE_NAME, path="/")
    response.delete_cookie(AUTH_NEXT_COOKIE_NAME, path="/")
    _set_session_cookie(response, session_token)
    return response
