"""HRAS 壳子接入：iframe Token、平台权限覆盖、可选启动注册与指标。"""

from __future__ import annotations

from collections import deque
import base64
import copy
import hashlib
import hmac
import json
import os
import time
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import Request, Response

from .config import AUTH_CONFIG
from .engine.admin_store import (
    create_session,
    get_current_user,
    get_session_user_id,
    init_admin_store,
    upsert_feishu_user,
)


SESSION_COOKIE_NAME = "sigma_session"
DEFAULT_MODULE_KEY = "hras-payroll"
_STATIC_SUFFIXES = (
    ".js",
    ".css",
    ".png",
    ".jpg",
    ".jpeg",
    ".svg",
    ".webp",
    ".ico",
    ".gif",
    ".woff",
    ".woff2",
    ".map",
    ".json",
)
_SKIP_IDENTITY_PREFIXES = (
    "/api/auth/feishu",
    "/api/auth/lark",
    "/api/auth/mock",
)
_SKIP_IDENTITY_PATHS = {"/health", "/metrics", "/api/health"}
_ADMIN_ROLE_HINTS = {
    "admin",
    "super_admin",
    "superadmin",
    "super-admin",
    "管理员",
    "系统管理员",
    "超级管理员",
}
_LOCAL_MODULE_IDS = (
    "recruitment",
    "employee",
    "domestic",
    "fbu",
    "overseas_payroll",
    "overseas",
    "social_insurance",
)
_MODULE_HINTS = (
    ("social-insurance", "social_insurance"),
    ("social_insurance", "social_insurance"),
    ("china-employee", "employee"),
    ("employee-payroll", "employee"),
    ("overseas-payroll", "overseas_payroll"),
    ("overseas_payroll", "overseas_payroll"),
    ("overseas-labor", "overseas"),
    ("overseas-compensation", "fbu"),
    ("recruitment", "recruitment"),
    ("domestic", "domestic"),
    ("employee", "employee"),
    ("fbu", "fbu"),
    ("overseas", "overseas"),
    ("admin", "admin"),
)

_token_cache: dict[str, tuple[float, dict[str, Any], str, bool]] = {}
_user_profile_cache: dict[str, dict[str, Any]] = {}
_metrics_started_at = time.time()
_request_count = 0
_error_count = 0
_total_response_ms = 0.0
_recent_durations: deque[float] = deque(maxlen=200)


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def shell_url() -> str:
    return str(os.environ.get("HRAS_SHELL_URL") or "http://localhost:8066").rstrip("/")


def register_enabled() -> bool:
    return _env_flag("HRAS_SHELL_REGISTER_ENABLED", False)


def module_key() -> str:
    return str(os.environ.get("HRAS_MODULE_KEY") or DEFAULT_MODULE_KEY).strip() or DEFAULT_MODULE_KEY


def module_name() -> str:
    return str(os.environ.get("HRAS_MODULE_NAME") or "HRAS 全球薪酬核算工作台").strip()


def module_api_key() -> str:
    return str(os.environ.get("HRAS_MODULE_API_KEY") or "").strip()


def jwt_secret() -> str:
    return str(os.environ.get("HRAS_JWT_SECRET") or os.environ.get("JWT_SECRET") or "").strip()


def should_skip_identity(path: str) -> bool:
    if path in _SKIP_IDENTITY_PATHS:
        return True
    if any(path.startswith(prefix) for prefix in _SKIP_IDENTITY_PREFIXES):
        return True
    lower = path.lower()
    return any(lower.endswith(suffix) for suffix in _STATIC_SUFFIXES)


def extract_shell_token(request: Request) -> str | None:
    candidates = [
        str(request.query_params.get("token") or "").strip(),
        _bearer_token(request),
    ]
    for token in candidates:
        if token and _looks_like_jwt(token):
            return token
    return None


def request_user_id(request: Request) -> str | None:
    bound = getattr(request.state, "sigma_user_id", None)
    if bound:
        return str(bound)
    token = str(request.cookies.get(SESSION_COOKIE_NAME) or "").strip()
    if not token:
        return None
    try:
        init_admin_store()
        return get_session_user_id(token)
    except KeyError:
        return None


def current_user_from_state(request: Request) -> dict[str, Any] | None:
    current = getattr(request.state, "sigma_current_user", None)
    return current if isinstance(current, dict) else None


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=bool(AUTH_CONFIG["session_cookie_secure"]),
        max_age=7 * 24 * 60 * 60,
        path="/",
    )


def strip_frame_blocking_headers(response: Response) -> None:
    for key in list(response.headers.keys()):
        if key.lower() == "x-frame-options":
            del response.headers[key]
            continue
        if key.lower() != "content-security-policy":
            continue
        csp = response.headers[key]
        if "frame-ancestors" not in csp.lower():
            continue
        parts = [
            item.strip()
            for item in csp.split(";")
            if item.strip() and "frame-ancestors" not in item.lower()
        ]
        if parts:
            response.headers[key] = "; ".join(parts)
        else:
            del response.headers[key]


def mark_request_start(request: Request) -> None:
    request.state.hras_metrics_started = time.perf_counter()


def record_request_metrics(request: Request, response: Response) -> None:
    global _request_count, _error_count, _total_response_ms
    started = getattr(request.state, "hras_metrics_started", None)
    duration_ms = (time.perf_counter() - started) * 1000 if isinstance(started, float) else 0.0
    _request_count += 1
    _total_response_ms += duration_ms
    _recent_durations.append(duration_ms)
    if getattr(response, "status_code", 200) >= 400:
        _error_count += 1


def metrics_payload() -> dict[str, Any]:
    avg_ms = round(_total_response_ms / _request_count, 2) if _request_count else 0
    error_rate = round(_error_count / _request_count, 3) if _request_count else 0.0
    return {
        "status": "UP",
        "timestamp": int(time.time()),
        "base": {
            "request_count": _request_count,
            "error_rate": error_rate,
            "avg_response_ms": avg_ms,
            "cpu_percent": -1.0,
            "memory_mb": -1.0,
            "uptime_seconds": int(time.time() - _metrics_started_at),
        },
        "custom": {
            "module_key": module_key(),
        },
    }


async def register_with_shell() -> None:
    if not register_enabled():
        print("[模块注册] 已跳过（HRAS_SHELL_REGISTER_ENABLED=false），走管理员预创建 / 独立运行。")
        return
    payload = {
        "module_key": module_key(),
        "name": module_name(),
        "menu": {
            "icon": "accountBook",
            "children": [
                {"path": "/", "name": "工作台"},
                {"path": "/recruitment.html", "name": "全球招聘奖金核算"},
                {"path": "/china-employee-payroll.html", "name": "中国区正式工薪酬核算"},
                {"path": "/domestic-labor.html", "name": "中国区外包工薪酬核算"},
                {"path": "/overseas-compensation.html", "name": "海外薪酬核算"},
                {"path": "/overseas-labor.html", "name": "海外劳务报账核对"},
                {"path": "/social-insurance.html", "name": "社保报盘工作台"},
            ],
        },
    }
    url = f"{shell_url()}/api/modules/register"
    print(f"[模块注册] 正在向壳子注册: {url}")
    headers = {"Content-Type": "application/json; charset=utf-8"}
    api_key = module_api_key()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
        print(f"[模块注册] ✅ 注册成功 | module_key={module_key()} | status={response.status_code}")
    except Exception as exc:  # noqa: BLE001 - registration must never block startup.
        print(f"[模块注册] ⚠️ 注册失败（壳子可能未启动），模块仍可独立运行。错误：{exc}")


def bind_shell_identity(request: Request) -> str | None:
    """Resolve shell JWT into a local session. Return a new session token when created."""
    existing_user_id = _cookie_user_id(request)
    token = extract_shell_token(request)
    if not token:
        if existing_user_id:
            request.state.sigma_user_id = existing_user_id
            profile = _user_profile_cache.get(existing_user_id)
            if profile:
                request.state.hras_shell_profile = profile
                request.state.sigma_current_user = apply_shell_permissions(
                    get_current_user(existing_user_id),
                    profile,
                )
        return None

    profile = verify_shell_token(token)
    if not profile:
        if existing_user_id:
            request.state.sigma_user_id = existing_user_id
        return None

    cache_key = _token_cache_key(token)
    cached = _token_cache.get(cache_key)
    now = time.time()
    if cached and cached[0] > now:
        _, cached_profile, user_id, session_created = cached
        request.state.hras_shell_profile = cached_profile
        request.state.sigma_user_id = user_id
        request.state.sigma_current_user = apply_shell_permissions(get_current_user(user_id), cached_profile)
        _user_profile_cache[user_id] = cached_profile
        if existing_user_id == user_id or session_created:
            return None
        session_token = _create_shell_session(user_id)
        _token_cache[cache_key] = (cached[0], cached_profile, user_id, True)
        return session_token

    init_admin_store()
    user = upsert_shell_user(profile)
    user_id = str(user["id"])
    current = apply_shell_permissions(get_current_user(user_id), profile)
    request.state.hras_shell_profile = profile
    request.state.sigma_user_id = user_id
    request.state.sigma_current_user = current
    _user_profile_cache[user_id] = profile
    create_session_token = existing_user_id != user_id
    session_token = _create_shell_session(user_id) if create_session_token else None
    _token_cache[cache_key] = (now + 10 * 60, profile, user_id, bool(session_token or existing_user_id == user_id))
    return session_token


def verify_shell_token(token: str) -> dict[str, Any] | None:
    secret = jwt_secret()
    if secret:
        claims = _verify_jwt(token, secret)
        if not claims:
            return None
        remote = _fetch_shell_profile(token)
        return _merge_profile(claims, remote)
    remote = _fetch_shell_profile(token)
    if remote:
        return remote
    return _decode_unverified_jwt(token) if _allow_unverified_jwt() else None


def upsert_shell_user(profile: dict[str, Any]) -> dict[str, Any]:
    open_id = str(profile.get("feishuOpenId") or "").strip()
    email = str(profile.get("email") or "").strip() or None
    username = str(profile.get("username") or "").strip()
    user_id = str(profile.get("userId") or "").strip()
    name = str(profile.get("realName") or username or email or user_id or "HRAS 用户").strip()
    synthetic_open_id = open_id or (f"hras_{user_id}" if user_id else "") or (f"hras_{username}" if username else "")
    if not synthetic_open_id:
        synthetic_open_id = f"hras_{_token_cache_key(name)[:16]}"
    return upsert_feishu_user(
        feishu_open_id=synthetic_open_id,
        feishu_user_id=str(profile.get("feishuUserId") or "").strip() or None,
        feishu_union_id=str(profile.get("feishuUnionId") or "").strip() or None,
        email=email,
        name=name,
        employee_number=username or None,
        audit=False,
    )


def apply_shell_permissions(current: dict[str, Any], profile: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(current, dict) or not profile:
        return current
    overlaid = copy.deepcopy(current)
    user = overlaid.get("user") if isinstance(overlaid.get("user"), dict) else {}
    if user.get("status") not in {"active", "pending"}:
        user["status"] = "pending"
        overlaid["user"] = user

    granted, is_admin = _granted_local_modules(profile)
    roles = list(overlaid.get("roles") or [])
    role_ids = [str(role.get("id") or "") for role in roles if isinstance(role, dict)]
    if is_admin and "admin" not in role_ids:
        roles.insert(0, {"id": "admin", "name": "系统管理员", "moduleId": None, "isSystem": True})
        role_ids.insert(0, "admin")
        if isinstance(overlaid.get("user"), dict):
            overlaid["user"]["roleIds"] = ["admin", *[item for item in overlaid["user"].get("roleIds") or [] if item != "admin"]]
            overlaid["user"]["status"] = "active"
    overlaid["roles"] = roles

    permissions = overlaid.get("permissions") if isinstance(overlaid.get("permissions"), dict) else {}
    module_access = dict(permissions.get("moduleAccess") or {})
    role_permissions = dict(permissions.get("rolePermissions") or {})
    if is_admin:
        module_access["admin"] = {module_id: True for module_id in _LOCAL_MODULE_IDS}
        role_permissions["admin"] = {**(role_permissions.get("admin") or {}), "enter": True}
    permissions["moduleAccess"] = module_access
    permissions["rolePermissions"] = role_permissions
    overlaid["permissions"] = permissions

    modules = []
    for module in overlaid.get("modules") or []:
        if not isinstance(module, dict):
            continue
        module_id = str(module.get("id") or "")
        enabled = bool(module.get("enabled"))
        local_can_enter = bool(module.get("canEnter"))
        platform_can_enter = enabled and (is_admin or module_id in granted)
        modules.append({**module, "canEnter": bool(platform_can_enter or local_can_enter)})
    overlaid["modules"] = modules
    overlaid["authSource"] = "hras-shell"
    overlaid["shellUser"] = {
        "userId": profile.get("userId"),
        "username": profile.get("username"),
        "realName": profile.get("realName"),
        "roleName": profile.get("roleName") or profile.get("role"),
        "orgCode": profile.get("orgCode"),
        "buCode": profile.get("buCode"),
    }
    return overlaid


def _granted_local_modules(profile: dict[str, Any]) -> tuple[set[str], bool]:
    role_text = " ".join(
        str(item or "")
        for item in (
            profile.get("roleName"),
            profile.get("role"),
            profile.get("roleCode"),
        )
    ).replace(",", " ")
    role_tokens = {item.strip().lower() for item in role_text.split() if item.strip()}
    is_admin = bool(role_tokens & {item.lower() for item in _ADMIN_ROLE_HINTS})
    raw_permissions = _parse_module_permissions(profile.get("modulePermissions"))
    if "*" in raw_permissions or any(item.lower() in {"*", "all"} for item in raw_permissions):
        is_admin = True
    granted: set[str] = set()
    parent_keys = {module_key().lower(), DEFAULT_MODULE_KEY, "payroll", "sigma-workbench"}
    for item in raw_permissions:
        normalized = str(item or "").strip().lower()
        if not normalized or normalized in {"*", "all"}:
            continue
        remainder = normalized
        for parent in sorted(parent_keys, key=len, reverse=True):
            if remainder == parent:
                granted.update(_LOCAL_MODULE_IDS)
                remainder = ""
                break
            prefix = f"{parent}/"
            if remainder.startswith(prefix):
                remainder = remainder[len(prefix):]
                break
        if not remainder:
            continue
        matched = False
        for hint, module_id in _MODULE_HINTS:
            if hint in remainder or hint in normalized:
                granted.add(module_id)
                matched = True
                break
        if not matched and remainder in _LOCAL_MODULE_IDS:
            granted.add(remainder)
    if is_admin:
        granted.update(_LOCAL_MODULE_IDS)
        granted.add("admin")
    elif not raw_permissions:
        granted.update(_LOCAL_MODULE_IDS)
    return granted, is_admin


def _parse_module_permissions(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, dict):
        keys = [str(key) for key in value.keys() if str(key).strip()]
        nested: list[str] = []
        for key, item in value.items():
            nested.append(str(key))
            if isinstance(item, list):
                nested.extend(str(child) for child in item)
            elif item not in (None, True, False, ""):
                nested.append(str(item))
        return [item for item in nested if item.strip()]
    text = str(value).strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return [part.strip() for part in text.split(",") if part.strip()]
    return _parse_module_permissions(parsed)


def _looks_like_jwt(token: str) -> bool:
    return token.count(".") == 2 and all(token.split("."))


def _bearer_token(request: Request) -> str:
    header = str(request.headers.get("authorization") or request.headers.get("Authorization") or "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return ""


def _cookie_user_id(request: Request) -> str | None:
    token = str(request.cookies.get(SESSION_COOKIE_NAME) or "").strip()
    if not token:
        return None
    try:
        init_admin_store()
        return get_session_user_id(token)
    except KeyError:
        return None


def _create_shell_session(user_id: str) -> str:
    return create_session(user_id, action="hras_shell_login")


def _token_cache_key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _b64url_decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def _decode_unverified_jwt(token: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(_b64url_decode(token.split(".")[1]))
    except (ValueError, IndexError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return _profile_from_claims(payload)


def _verify_jwt(token: str, secret: str) -> dict[str, Any] | None:
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
        actual = _b64url_decode(signature_b64)
        secret_bytes = secret.encode("utf-8")
        for digest in (hashlib.sha512, hashlib.sha256, hashlib.sha384):
            expected = hmac.new(secret_bytes, signing_input, digest).digest()
            if hmac.compare_digest(expected, actual):
                payload = json.loads(_b64url_decode(payload_b64))
                if not isinstance(payload, dict):
                    return None
                exp = payload.get("exp")
                if isinstance(exp, (int, float)) and exp < time.time() - 30:
                    return None
                return _profile_from_claims(payload)
    except (ValueError, json.JSONDecodeError):
        return None
    return None


def _profile_from_claims(claims: dict[str, Any]) -> dict[str, Any]:
    return {
        "userId": claims.get("userId") or claims.get("user_id"),
        "username": claims.get("username") or claims.get("sub"),
        "realName": claims.get("realName") or claims.get("name"),
        "roleName": claims.get("roleName") or claims.get("role"),
        "role": claims.get("role"),
        "roleCode": claims.get("roleCode"),
        "modulePermissions": claims.get("modulePermissions"),
        "buCode": claims.get("buCode"),
        "orgCode": claims.get("orgCode"),
        "orgBsCode": claims.get("orgBsCode"),
        "feishuOpenId": claims.get("feishuOpenId"),
        "feishuUnionId": claims.get("feishuUnionId"),
        "feishuUserId": claims.get("feishuUserId"),
        "email": claims.get("email"),
    }


def _fetch_shell_profile(token: str) -> dict[str, Any] | None:
    if not str(os.environ.get("HRAS_SHELL_URL") or "").strip():
        return None
    url = f"{shell_url()}/api/auth/me"
    try:
        with httpx.Client(timeout=3.0) as client:
            response = client.get(url, headers={"Authorization": f"Bearer {token}"})
        if response.status_code >= 400:
            return None
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        data = payload if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return None
    return _profile_from_claims(data) | {
        "realName": data.get("realName") or data.get("name"),
        "modulePermissions": data.get("modulePermissions"),
        "feishuOpenId": data.get("feishuOpenId"),
        "feishuUnionId": data.get("feishuUnionId"),
        "feishuUserId": data.get("feishuUserId"),
        "email": data.get("email"),
        "roleName": data.get("roleName") or data.get("role"),
        "roles": data.get("roles"),
    }


def _merge_profile(claims: dict[str, Any], remote: dict[str, Any] | None) -> dict[str, Any]:
    if not remote:
        return claims
    merged = dict(claims)
    for key, value in remote.items():
        if value not in (None, "", [], {}):
            merged[key] = value
    return merged


def _allow_unverified_jwt() -> bool:
    vercel_env = str(os.environ.get("VERCEL_ENV") or "").strip().lower()
    if os.environ.get("VERCEL") or vercel_env in {"production", "prod", "preview"}:
        return False
    return _env_flag("HRAS_ALLOW_UNVERIFIED_JWT", not bool(jwt_secret()))


def origin_from_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return value
