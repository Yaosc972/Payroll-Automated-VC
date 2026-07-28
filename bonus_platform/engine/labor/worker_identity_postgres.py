from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import secrets
from typing import Any, Callable, Mapping
from uuid import uuid4

from .state_postgres import _insert_audit, _open_connection, _required, labor_postgres_state_enabled


class LaborWorkerIdentityError(RuntimeError):
    pass


class LaborWorkerIdentityInvalid(PermissionError, LaborWorkerIdentityError):
    pass


class LaborWorkerDeviceNotFound(FileNotFoundError, LaborWorkerIdentityError):
    pass


def labor_worker_identity_health(
    *,
    env: Mapping[str, str] | None = None,
    connect: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    if not labor_postgres_state_enabled(env):
        return {"backend": "static-env", "configured": False, "ready": False}
    try:
        with _open_connection(env=env, connect=connect) as connection:
            row = connection.execute(
                """
                select
                    to_regclass('public.labor_worker_devices') is not null as devices_ready,
                    to_regclass('public.labor_worker_tokens') is not null as tokens_ready
                """
            ).fetchone()
        values = dict(row or {})
        ready = bool(values.get("devices_ready") and values.get("tokens_ready"))
        return {
            "backend": "postgres",
            "configured": True,
            "ready": ready,
            "deviceTableReady": bool(values.get("devices_ready")),
            "tokenTableReady": bool(values.get("tokens_ready")),
        }
    except Exception as exc:  # noqa: BLE001 - do not expose DSNs or credentials in readiness.
        return {
            "backend": "postgres",
            "configured": True,
            "ready": False,
            "errorType": type(exc).__name__[:96],
        }


def _issue_labor_worker_credential(
    *,
    owner_user_id: str,
    actor_user_id: str,
    display_name: str,
    platform: str,
    worker_version: str = "",
    capabilities: Mapping[str, Any] | None = None,
    ttl_seconds: int = 8 * 60 * 60,
    device_id: str = "",
    token_prefix: str,
    token_id_prefix: str,
    minimum_ttl_seconds: int,
    maximum_ttl_seconds: int,
    registered_action: str,
    rotated_action: str,
    revoke_token_id_prefix: str = "",
    connect: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    owner = _required(owner_user_id, "owner_user_id")
    actor = _required(actor_user_id, "actor_user_id")
    safe_ttl = max(minimum_ttl_seconds, min(int(ttl_seconds or 0), maximum_ttl_seconds))
    safe_name = str(display_name or "个人核对助手").strip()[:120] or "个人核对助手"
    safe_platform = str(platform or "unknown").strip()[:80] or "unknown"
    safe_version = str(worker_version or "").strip()[:40]
    safe_capabilities = dict(capabilities or {})
    raw_token = f"{token_prefix}{secrets.token_urlsafe(32)}"
    token_hash = _token_hash(raw_token)
    safe_device_id = str(device_id or "").strip() or f"labor_device_{uuid4().hex}"
    token_id = f"{token_id_prefix}{uuid4().hex}"
    with _open_connection(connect=connect) as connection:
        try:
            if device_id:
                existing = connection.execute(
                    """
                    select * from public.labor_worker_devices
                    where id=%s and owner_user_id=%s and revoked_at is null
                    for update
                    """,
                    (safe_device_id, owner),
                ).fetchone()
                if not existing:
                    raise LaborWorkerDeviceNotFound("Worker 设备不存在或已撤销。")
                existing_values = dict(existing)
                effective_version = safe_version or str(existing_values.get("worker_version") or "").strip()[:40]
                connection.execute(
                    """
                    update public.labor_worker_devices
                    set display_name=%s, platform=%s, worker_version=%s,
                        capabilities=%s::jsonb, updated_at=now()
                    where id=%s and owner_user_id=%s and revoked_at is null
                    """,
                    (
                        safe_name,
                        safe_platform,
                        effective_version,
                        json.dumps(safe_capabilities, ensure_ascii=False, separators=(",", ":")),
                        safe_device_id,
                        owner,
                    ),
                )
                device_row = {
                    **existing_values,
                    "display_name": safe_name,
                    "platform": safe_platform,
                    "worker_version": effective_version,
                }
                action = rotated_action
            else:
                device_row = connection.execute(
                    """
                    insert into public.labor_worker_devices (
                        id, owner_user_id, display_name, platform, worker_version,
                        capabilities, created_at, updated_at
                    ) values (%s, %s, %s, %s, %s, %s::jsonb, now(), now())
                    returning *
                    """,
                    (
                        safe_device_id,
                        owner,
                        safe_name,
                        safe_platform,
                        safe_version,
                        json.dumps(safe_capabilities, ensure_ascii=False, separators=(",", ":")),
                    ),
                ).fetchone()
                if not device_row:
                    raise LaborWorkerIdentityError("Worker 设备注册失败。")
                action = registered_action
            revoke_scope = "and id like %s" if revoke_token_id_prefix else ""
            revoke_params = (
                (safe_device_id, owner, f"{revoke_token_id_prefix}%")
                if revoke_token_id_prefix
                else (safe_device_id, owner)
            )
            connection.execute(
                f"""
                update public.labor_worker_tokens
                set revoked_at=coalesce(revoked_at, now())
                where device_id=%s and owner_user_id=%s and revoked_at is null
                  {revoke_scope}
                """,
                revoke_params,
            )
            connection.execute(
                """
                insert into public.labor_worker_tokens (
                    id, device_id, owner_user_id, token_hash, expires_at, created_at
                ) values (%s, %s, %s, %s, now()+(%s*interval '1 second'), now())
                """,
                (token_id, safe_device_id, owner, token_hash, safe_ttl),
            )
            _insert_audit(
                connection,
                run_id="",
                owner_user_id=owner,
                actor_user_id=actor,
                action=action,
                details={"deviceId": safe_device_id, "platform": safe_platform, "expiresIn": safe_ttl},
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=safe_ttl)
    return {
        "credential": raw_token,
        "expiresIn": safe_ttl,
        "expiresAt": expires_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "device": _public_device(dict(device_row)),
    }


def issue_labor_worker_token(
    *,
    owner_user_id: str,
    actor_user_id: str,
    display_name: str,
    platform: str,
    worker_version: str = "",
    capabilities: Mapping[str, Any] | None = None,
    ttl_seconds: int = 8 * 60 * 60,
    device_id: str = "",
    connect: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    issued = _issue_labor_worker_credential(
        owner_user_id=owner_user_id,
        actor_user_id=actor_user_id,
        display_name=display_name,
        platform=platform,
        worker_version=worker_version,
        capabilities=capabilities,
        ttl_seconds=ttl_seconds,
        device_id=device_id,
        token_prefix="sigma_labor_w1_",
        token_id_prefix="labor_token_",
        minimum_ttl_seconds=300,
        maximum_ttl_seconds=24 * 60 * 60,
        registered_action="worker_device_registered",
        rotated_action="worker_token_rotated",
        connect=connect,
    )
    return {"token": issued.pop("credential"), **issued}


def issue_labor_worker_activation(
    *,
    owner_user_id: str,
    actor_user_id: str,
    display_name: str,
    platform: str,
    worker_version: str = "",
    capabilities: Mapping[str, Any] | None = None,
    ttl_seconds: int = 5 * 60,
    device_id: str = "",
    connect: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    issued = _issue_labor_worker_credential(
        owner_user_id=owner_user_id,
        actor_user_id=actor_user_id,
        display_name=display_name,
        platform=platform,
        worker_version=worker_version,
        capabilities=capabilities,
        ttl_seconds=ttl_seconds,
        device_id=device_id,
        token_prefix="sigma_labor_a1_",
        token_id_prefix="labor_activation_",
        minimum_ttl_seconds=60,
        maximum_ttl_seconds=10 * 60,
        registered_action="worker_activation_registered",
        rotated_action="worker_activation_rotated",
        revoke_token_id_prefix="labor_activation_",
        connect=connect,
    )
    return {"activationCode": issued.pop("credential"), **issued}


def exchange_labor_worker_activation(
    raw_activation_code: str,
    *,
    worker_version: str = "",
    ttl_seconds: int = 90 * 24 * 60 * 60,
    connect: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    activation_code = str(raw_activation_code or "").strip()
    safe_version = str(worker_version or "").strip()[:40]
    safe_ttl = max(300, min(int(ttl_seconds or 0), 365 * 24 * 60 * 60))
    if not activation_code.startswith("sigma_labor_a1_") or len(activation_code) < 24:
        raise LaborWorkerIdentityInvalid("Worker 激活码无效或已失效。")

    raw_token = f"sigma_labor_w1_{secrets.token_urlsafe(32)}"
    token_id = f"labor_token_{uuid4().hex}"
    with _open_connection(connect=connect) as connection:
        try:
            row = connection.execute(
                """
                select t.id as activation_id, t.device_id, t.owner_user_id,
                       d.display_name, d.platform, d.worker_version, d.capabilities,
                       d.last_seen_at, d.revoked_at, d.created_at, d.updated_at
                from public.labor_worker_tokens t
                join public.labor_worker_devices d on d.id=t.device_id
                where t.token_hash=%s and t.revoked_at is null and t.expires_at > now()
                  and d.revoked_at is null and d.owner_user_id=t.owner_user_id
                for update of t, d
                """,
                (_token_hash(activation_code),),
            ).fetchone()
            if not row:
                raise LaborWorkerIdentityInvalid("Worker 激活码无效或已失效。")
            values = dict(row)
            activation_id = str(values.get("activation_id") or "")
            device_id = str(values.get("device_id") or "")
            owner_user_id = str(values.get("owner_user_id") or "")
            connection.execute(
                """
                update public.labor_worker_tokens
                set revoked_at=coalesce(revoked_at, now()), last_used_at=now()
                where id=%s and revoked_at is null and expires_at > now()
                """,
                (activation_id,),
            )
            connection.execute(
                """
                update public.labor_worker_tokens
                set revoked_at=coalesce(revoked_at, now())
                where device_id=%s and owner_user_id=%s and id<>%s and revoked_at is null
                """,
                (device_id, owner_user_id, activation_id),
            )
            connection.execute(
                """
                insert into public.labor_worker_tokens (
                    id, device_id, owner_user_id, token_hash, expires_at, created_at
                ) values (%s, %s, %s, %s, now()+(%s*interval '1 second'), now())
                """,
                (token_id, device_id, owner_user_id, _token_hash(raw_token), safe_ttl),
            )
            connection.execute(
                """
                update public.labor_worker_devices
                set worker_version=case when %s <> '' then %s else worker_version end,
                    updated_at=now()
                where id=%s and owner_user_id=%s and revoked_at is null
                """,
                (safe_version, safe_version, device_id, owner_user_id),
            )
            _insert_audit(
                connection,
                run_id="",
                owner_user_id=owner_user_id,
                actor_user_id=owner_user_id,
                action="worker_activation_exchanged",
                details={"deviceId": device_id, "expiresIn": safe_ttl},
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=safe_ttl)
    device_row = {
        **values,
        "id": device_id,
        "worker_version": safe_version or str(values.get("worker_version") or ""),
    }
    return {
        "token": raw_token,
        "expiresIn": safe_ttl,
        "expiresAt": expires_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "device": _public_device(device_row),
    }


def resolve_labor_worker_token(
    raw_token: str,
    *,
    worker_version: str = "",
    refresh_ttl_seconds: int = 0,
    recovery_grace_seconds: int = 0,
    connect: Callable[[], Any] | None = None,
) -> dict[str, str]:
    token = str(raw_token or "").strip()
    safe_version = str(worker_version or "").strip()[:40]
    safe_refresh_ttl = max(0, min(int(refresh_ttl_seconds or 0), 365 * 24 * 60 * 60))
    safe_recovery_grace = max(0, min(int(recovery_grace_seconds or 0), 30 * 24 * 60 * 60))
    if not token.startswith("sigma_labor_w1_") or len(token) < 24:
        raise LaborWorkerIdentityInvalid("Worker 身份令牌无效或已失效。")
    with _open_connection(connect=connect) as connection:
        try:
            row = connection.execute(
                """
                select t.id as token_id, t.device_id, t.owner_user_id, t.expires_at,
                       d.display_name, d.platform
                from public.labor_worker_tokens t
                join public.labor_worker_devices d on d.id=t.device_id
                where t.token_hash=%s and t.revoked_at is null and t.expires_at > now()
                  and d.revoked_at is null and d.owner_user_id=t.owner_user_id
                for update of t, d
                """,
                (_token_hash(token),),
            ).fetchone()
            recovered = False
            if not row and safe_recovery_grace:
                row = connection.execute(
                    """
                    select t.id as token_id, t.device_id, t.owner_user_id, t.expires_at,
                           d.display_name, d.platform
                    from public.labor_worker_tokens t
                    join public.labor_worker_devices d on d.id=t.device_id
                    where t.token_hash=%s and t.id like 'labor_token_%%'
                      and t.revoked_at is null and t.expires_at <= now()
                      and t.expires_at > now()-(%s*interval '1 second')
                      and d.revoked_at is null and d.owner_user_id=t.owner_user_id
                      and not exists (
                          select 1
                          from public.labor_worker_tokens newer
                          where newer.device_id=t.device_id
                            and newer.owner_user_id=t.owner_user_id
                            and newer.id like 'labor_token_%%'
                            and newer.created_at > t.created_at
                            and newer.revoked_at is null
                      )
                    for update of t, d
                    """,
                    (_token_hash(token), safe_recovery_grace),
                ).fetchone()
                recovered = bool(row)
            if not row:
                raise LaborWorkerIdentityInvalid("Worker 身份令牌无效或已失效。")
            values = dict(row)
            connection.execute(
                """
                update public.labor_worker_tokens
                set last_used_at=now(),
                    expires_at=case
                        when %s > 0 then greatest(expires_at, now()+(%s*interval '1 second'))
                        else expires_at
                    end
                where id=%s and revoked_at is null
                """,
                (safe_refresh_ttl, safe_refresh_ttl, str(values.get("token_id") or "")),
            )
            connection.execute(
                """
                update public.labor_worker_devices
                set last_seen_at=now(),
                    worker_version=case when %s <> '' then %s else worker_version end,
                    updated_at=now()
                where id=%s and revoked_at is null
                """,
                (safe_version, safe_version, str(values.get("device_id") or "")),
            )
            if recovered:
                _insert_audit(
                    connection,
                    run_id="",
                    owner_user_id=str(values.get("owner_user_id") or ""),
                    actor_user_id=str(values.get("owner_user_id") or ""),
                    action="worker_token_grace_recovered",
                    details={
                        "deviceId": str(values.get("device_id") or ""),
                        "recoveryGraceSeconds": safe_recovery_grace,
                    },
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return {
        "userId": str(values.get("owner_user_id") or ""),
        "deviceId": str(values.get("device_id") or ""),
    }


def list_labor_worker_devices(
    *,
    owner_user_id: str,
    connect: Callable[[], Any] | None = None,
) -> list[dict[str, Any]]:
    owner = _required(owner_user_id, "owner_user_id")
    with _open_connection(connect=connect) as connection:
        rows = connection.execute(
            """
            select * from public.labor_worker_devices
            where owner_user_id=%s
            order by revoked_at nulls first, updated_at desc, id
            """,
            (owner,),
        ).fetchall()
    return [_public_device(dict(row)) for row in rows]


def revoke_labor_worker_device(
    *,
    owner_user_id: str,
    actor_user_id: str,
    device_id: str,
    connect: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    owner = _required(owner_user_id, "owner_user_id")
    actor = _required(actor_user_id, "actor_user_id")
    safe_device_id = _required(device_id, "device_id")
    with _open_connection(connect=connect) as connection:
        try:
            row = connection.execute(
                """
                select * from public.labor_worker_devices
                where id=%s and owner_user_id=%s
                for update
                """,
                (safe_device_id, owner),
            ).fetchone()
            if not row:
                raise LaborWorkerDeviceNotFound("Worker 设备不存在。")
            connection.execute(
                """
                update public.labor_worker_devices
                set revoked_at=coalesce(revoked_at, now()), updated_at=now()
                where id=%s and owner_user_id=%s
                """,
                (safe_device_id, owner),
            )
            connection.execute(
                """
                update public.labor_worker_tokens
                set revoked_at=coalesce(revoked_at, now())
                where device_id=%s and owner_user_id=%s and revoked_at is null
                """,
                (safe_device_id, owner),
            )
            _insert_audit(
                connection,
                run_id="",
                owner_user_id=owner,
                actor_user_id=actor,
                action="worker_device_revoked",
                details={"deviceId": safe_device_id},
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return {**_public_device(dict(row)), "revoked": True}


def _token_hash(raw_token: str) -> str:
    return hashlib.sha256(str(raw_token).encode("utf-8")).hexdigest()


def _public_device(row: Mapping[str, Any]) -> dict[str, Any]:
    values = dict(row)
    return {
        "id": str(values.get("id") or ""),
        "ownerUserId": str(values.get("owner_user_id") or ""),
        "displayName": str(values.get("display_name") or ""),
        "platform": str(values.get("platform") or ""),
        "workerVersion": str(values.get("worker_version") or ""),
        "lastSeenAt": _stamp(values.get("last_seen_at")),
        "revokedAt": _stamp(values.get("revoked_at")),
        "createdAt": _stamp(values.get("created_at")),
        "updatedAt": _stamp(values.get("updated_at")),
    }


def _stamp(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return str(value or "")
