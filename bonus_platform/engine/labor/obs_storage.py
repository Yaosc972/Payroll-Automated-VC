"""
Huawei Cloud OBS (Object Storage Service) backend for labor run persistence.

Uses the official esdk-obs-python SDK (not boto3) to avoid S3-compatible
signing quirks.  This module mirrors blob_storage.py and Supabase Storage
so it drops into persistent_storage.py as an alternative backend.

Environment variables
---------------------
SIGMA_LABOR_STORAGE_BACKEND = "obs"
OBS_ACCESS_KEY              - Huawei Cloud AK
OBS_SECRET_KEY              - Huawei Cloud SK
OBS_ENDPOINT                - e.g. obs.cn-south-1.myhuaweicloud.com
OBS_BUCKET                  - bucket name (default: sigma-labor-runs)
SIGMA_LABOR_STORAGE_ENV     - environment label (production / staging / ...)
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from obs import ObsClient


RUN_PREFIX = "vc_payroll_file"


# ---------------------------------------------------------------------------
# Error wrapper
# ---------------------------------------------------------------------------

class ObsStorageError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False,
                 status_code: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.status_code = status_code


def _wrap_obs_response(resp: Any, *, operation: str) -> None:
    """Raise ObsStorageError if the OBS SDK response indicates failure."""
    if resp.status < 300:
        return
    status_code = int(resp.status)
    error_code = str(resp.errorCode or "OBS_ERROR")
    error_msg = str(resp.errorMessage or "unknown error")
    retryable = status_code >= 500 or error_code in {"RequestTimeout", "ServiceUnavailable"}
    if status_code in (401, 403):
        raise ObsStorageError(
            "OBS_PERMISSION_DENIED",
            f"OBS {operation} 权限失败: {error_code} - {error_msg}",
            retryable=False,
            status_code=status_code,
        )
    raise ObsStorageError(
        "OBS_CLIENT_ERROR",
        f"OBS {operation} 失败: {error_code} - {error_msg}",
        retryable=retryable,
        status_code=status_code,
    )


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

_SAFE_ENV_RE = re.compile(r"[^0-9A-Za-z_-]+")


def obs_environment() -> str:
    raw = (
        os.environ.get("SIGMA_LABOR_STORAGE_ENV")
        or os.environ.get("VERCEL_ENV")
        or os.environ.get("SIGMA_OVERSEAS_LABOR_ACCESS")
        or "local"
    )
    value = _SAFE_ENV_RE.sub("-", raw.strip().lower()).strip("-_")
    return value or "local"


def obs_bucket_name() -> str:
    return os.environ.get("OBS_BUCKET", "sigma-labor-runs").strip()


def _obs_access_key() -> str:
    return os.environ.get("OBS_ACCESS_KEY", "").strip()


def _obs_secret_key() -> str:
    return os.environ.get("OBS_SECRET_KEY", "").strip()


def _obs_endpoint() -> str:
    raw = os.environ.get("OBS_ENDPOINT", "").strip()
    if raw and not raw.startswith("https://"):
        raw = f"https://{raw}"
    return raw.rstrip("/")


def labor_obs_storage_enabled() -> bool:
    return (
        os.environ.get("SIGMA_LABOR_STORAGE_BACKEND", "").strip().lower() == "obs"
        and bool(_obs_access_key())
        and bool(_obs_secret_key())
        and bool(_obs_endpoint())
        and bool(obs_bucket_name())
    )


# ---------------------------------------------------------------------------
# OBS client (lazy singleton)
# ---------------------------------------------------------------------------

_obs_client: ObsClient | None = None


def _get_obs_client() -> ObsClient:
    global _obs_client
    if _obs_client is not None:
        return _obs_client
    _obs_client = ObsClient(
        access_key_id=_obs_access_key(),
        secret_access_key=_obs_secret_key(),
        server=_obs_endpoint(),
        timeout=120,
        max_retry_count=3,
    )
    return _obs_client


def _reset_obs_client() -> None:
    global _obs_client
    if _obs_client is not None:
        _obs_client.close()
        _obs_client = None


# ---------------------------------------------------------------------------
# Object key helpers
# ---------------------------------------------------------------------------

def obs_run_prefix(run_id: str) -> str:
    return f"{RUN_PREFIX}/{obs_environment()}/{run_id}"


def obs_object_key(run_id: str, relative_path: str) -> str:
    normalized = relative_path.replace("\\", "/").lstrip("/")
    return f"{obs_run_prefix(run_id)}/{normalized}"


def obs_relative_path(run_id: str, object_key: str) -> str:
    prefix = f"{obs_run_prefix(run_id)}/"
    return object_key[len(prefix):] if object_key.startswith(prefix) else object_key


# ---------------------------------------------------------------------------
# Core OBS operations
# ---------------------------------------------------------------------------

def obs_put_bytes(object_key: str, content: bytes, *,
                  content_type: str | None = None) -> dict[str, Any]:
    """Upload raw bytes to OBS."""
    bucket = obs_bucket_name()
    headers = {}
    if content_type:
        headers["Content-Type"] = content_type
    try:
        client = _get_obs_client()
        resp = client.putContent(
            bucketName=bucket,
            objectKey=object_key,
            content=content,
            headers=headers if headers else None,
        )
        _wrap_obs_response(resp, operation="上传")
        return {
            "etag": str(resp.body.etag or "").strip('"') if resp.body else "",
            "versionId": str(resp.body.versionId or "") if resp.body else "",
        }
    except ObsStorageError:
        raise
    except Exception as exc:
        raise ObsStorageError("OBS_ERROR", f"OBS 上传 失败: {exc}", retryable=True) from exc


def obs_get_bytes(object_key: str) -> bytes | None:
    """Download object body from OBS.  Returns None on 404."""
    bucket = obs_bucket_name()
    try:
        resp = _get_obs_client().getObject(
            bucketName=bucket,
            objectKey=object_key,
        )
        if resp.status == 404:
            return None
        _wrap_obs_response(resp, operation="下载")
        return _read_obs_body(resp)
    except ObsStorageError:
        raise
    except Exception as exc:
        raise ObsStorageError("OBS_ERROR", f"OBS 下载 失败: {exc}", retryable=True) from exc


def _read_obs_body(resp: Any) -> bytes | None:
    """Extract bytes from an OBS GetObject response body.

    For large files the body may be streamed via *buffer*; for small
    text files the data is accessed through *response.read()*.
    """
    body = resp.body
    if body is None:
        return None
    if getattr(body, "buffer", None) is not None:
        buf = body.buffer
        if isinstance(buf, memoryview):
            return buf.tobytes()
        if isinstance(buf, bytes):
            return buf
        return bytes(buf)
    if hasattr(body, "response") and body.response is not None:
        return body.response.read()
    return None


def obs_list_objects(prefix: str) -> list[dict[str, Any]]:
    """List all objects under a prefix.  Handles pagination."""
    bucket = obs_bucket_name()
    rows: list[dict[str, Any]] = []
    marker = None
    try:
        client = _get_obs_client()
        while True:
            resp = client.listObjects(
                bucketName=bucket,
                prefix=prefix,
                max_keys=1000,
                marker=marker,
            )
            _wrap_obs_response(resp, operation="列表")
            if resp.body:
                for obj in resp.body.contents or []:
                    rows.append({
                        "key": obj.key or "",
                        "size": obj.size or 0,
                        "lastModified": obj.lastModified,
                        "etag": str(obj.etag or "").strip('"'),
                    })
                if resp.body.isTruncated and resp.body.nextMarker:
                    marker = resp.body.nextMarker
                else:
                    break
            else:
                break
    except ObsStorageError:
        raise
    except Exception as exc:
        raise ObsStorageError("OBS_ERROR", f"OBS 列表 失败: {exc}", retryable=True) from exc
    return rows


def obs_delete_objects(object_keys: list[str]) -> None:
    """Batch delete objects from OBS."""
    if not object_keys:
        return
    bucket = obs_bucket_name()
    try:
        client = _get_obs_client()
        for i in range(0, len(object_keys), 1000):
            batch = object_keys[i:i + 1000]
            objects_input = [{"key": key} for key in batch]
            resp = client.deleteObjects(
                bucketName=bucket,
                deleteObjectsRequest={"objects": objects_input, "quiet": "true"},
            )
            _wrap_obs_response(resp, operation="删除")
    except ObsStorageError:
        raise
    except Exception as exc:
        raise ObsStorageError("OBS_ERROR", f"OBS 删除 失败: {exc}", retryable=True) from exc


# ---------------------------------------------------------------------------
# Presigned URL
# ---------------------------------------------------------------------------

def create_obs_presigned_upload(run_id: str, relative_path: str,
                                expiration: int = 3600) -> dict[str, Any]:
    """Generate a presigned PUT URL for direct frontend upload."""
    object_key = obs_object_key(run_id, relative_path)
    bucket = obs_bucket_name()
    content_type, _ = mimetypes.guess_type(relative_path)
    headers: dict[str, str] = {}
    if content_type:
        headers["Content-Type"] = content_type
    try:
        resp = _get_obs_client().createSignedUrl(
            method="PUT",
            bucketName=bucket,
            objectKey=object_key,
            expires=expiration,
            headers=headers if headers else None,
        )
        signed_url = resp.signedUrl
    except Exception as exc:
        raise ObsStorageError("OBS_ERROR", f"OBS 生成签名URL 失败: {exc}", retryable=True) from exc
    return {
        "signedUrl": signed_url,
        "objectKey": object_key,
        "relativePath": relative_path,
        "bucket": bucket,
        "contentType": content_type or "application/octet-stream",
    }


# ---------------------------------------------------------------------------
# Health probe
# ---------------------------------------------------------------------------

def obs_health(*, probe: bool = False) -> dict[str, Any]:
    health: dict[str, Any] = {
        "backend": "obs",
        "environment": obs_environment(),
        "enabled": labor_obs_storage_enabled(),
        "bucket": obs_bucket_name(),
        "endpointConfigured": bool(_obs_endpoint()),
        "credentialsConfigured": bool(_obs_access_key() and _obs_secret_key()),
        "probe": bool(probe),
    }
    if not probe:
        return health
    if not labor_obs_storage_enabled():
        health.update({"ok": False, "errorType": "missing_configuration"})
        return health
    try:
        probe_key = obs_object_key(
            "_health",
            f"storage-health-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.json",
        )
        obs_put_bytes(
            probe_key,
            json.dumps({"ok": True, "checkedAt": datetime.utcnow().isoformat() + "Z"}).encode("utf-8"),
            content_type="application/json",
        )
        health.update({"ok": True})
    except ObsStorageError as exc:
        health.update({
            "ok": False,
            "errorType": "obs_error",
            "errorCode": exc.code,
            "errorMessage": str(exc)[:240],
        })
    except Exception as exc:
        health.update({
            "ok": False,
            "errorType": type(exc).__name__,
            "errorMessage": str(exc)[:240],
        })
    return health


# ---------------------------------------------------------------------------
# Bulk sync helpers
# ---------------------------------------------------------------------------

def sync_labor_run_to_obs(run_id: str, run_dir: Path) -> None:
    """Upload every file under *run_dir* into OBS under run_id's prefix."""
    if not labor_obs_storage_enabled() or not run_dir.exists():
        return
    for path in sorted(run_dir.rglob("*")):
        if not path.is_file() or path.name.endswith(".tmp"):
            continue
        relative = path.relative_to(run_dir).as_posix()
        content_type, _ = mimetypes.guess_type(path.name)
        obs_put_bytes(
            obs_object_key(run_id, relative),
            path.read_bytes(),
            content_type=content_type or "application/octet-stream",
        )


def sync_labor_files_to_obs(run_id: str, run_dir: Path,
                             relative_paths: Iterable[str]) -> None:
    """Upload only the listed relative paths."""
    if not labor_obs_storage_enabled() or not run_dir.exists():
        return
    for relative in sorted({
        str(item).replace("\\", "/").lstrip("/")
        for item in relative_paths if str(item).strip()
    }):
        path = run_dir / relative
        if not path.is_file() or path.name.endswith(".tmp"):
            continue
        content_type, _ = mimetypes.guess_type(path.name)
        obs_put_bytes(
            obs_object_key(run_id, relative),
            path.read_bytes(),
            content_type=content_type or "application/octet-stream",
        )


def sync_labor_run_from_obs(run_id: str, run_dir: Path) -> bool:
    """Restore all objects for a run from OBS into the local *run_dir*."""
    if not labor_obs_storage_enabled():
        return False
    objects = obs_list_objects(f"{obs_run_prefix(run_id)}/")
    if not objects:
        return False
    run_dir.mkdir(parents=True, exist_ok=True)
    for obj in objects:
        object_key = obj.get("key", "")
        if not object_key or object_key.endswith("/"):
            continue
        content = obs_get_bytes(object_key)
        if content is None:
            continue
        relative = obs_relative_path(run_id, object_key)
        local_path = run_dir / relative
        local_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = local_path.with_suffix(f"{local_path.suffix}.tmp")
        tmp_path.write_bytes(content)
        os.replace(tmp_path, local_path)
    return True


def list_labor_metadata_from_obs() -> list[dict[str, Any]]:
    """List all labor run metadata.json objects from OBS."""
    if not labor_obs_storage_enabled():
        return []
    prefix = f"{RUN_PREFIX}/{obs_environment()}/"
    rows: list[dict[str, Any]] = []
    for obj in obs_list_objects(prefix):
        key = obj.get("key", "")
        if not key.endswith("/metadata.json"):
            continue
        content = obs_get_bytes(key)
        if not content:
            continue
        try:
            rows.append(json.loads(content.decode("utf-8")))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
    return sorted(rows, key=lambda row: row.get("updatedAt") or row.get("createdAt") or "",
                  reverse=True)
