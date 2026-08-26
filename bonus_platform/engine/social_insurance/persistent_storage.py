from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import time
from typing import Any, NoReturn
from urllib.parse import urlencode

import httpx

from ..labor.blob_storage import blob_get_bytes, blob_list_prefix, blob_put_bytes
from ..labor.persistent_storage import (
    _supabase_download_bytes as supabase_download_bytes,
    _supabase_entry_path as supabase_entry_path,
    _supabase_list_objects as supabase_list_objects,
    _supabase_token as supabase_token,
    _supabase_upload_bytes as supabase_upload_bytes,
    _supabase_url as supabase_url,
    labor_supabase_bucket,
)


ROOT_PREFIX = "social-insurance"
RUN_MANIFEST = ".storage-manifest.json"


class SocialInsuranceStorageError(RuntimeError):
    """社保报盘持久化存储未就绪或读写失败。"""

    def __init__(
        self,
        message: str,
        *,
        code: str = "",
        retryable: bool = False,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.status_code = status_code


def storage_backend() -> str:
    return os.environ.get("SIGMA_SOCIAL_INSURANCE_STORAGE_BACKEND", "").strip().lower()


def storage_environment() -> str:
    raw = (
        os.environ.get("SIGMA_SOCIAL_INSURANCE_STORAGE_ENV")
        or os.environ.get("VERCEL_ENV")
        or "local"
    )
    normalized = re.sub(r"[^0-9A-Za-z_-]+", "-", raw.strip().lower()).strip("-_")
    return normalized or "local"


def persistent_storage_enabled() -> bool:
    backend = storage_backend()
    if backend == "blob":
        return bool(os.environ.get("BLOB_READ_WRITE_TOKEN", "").strip())
    if backend == "supabase":
        return bool(supabase_url() and supabase_token() and labor_supabase_bucket())
    return False


def serverless_runtime() -> bool:
    return bool(os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))


def require_persistent_storage() -> None:
    if serverless_runtime() and not persistent_storage_enabled():
        raise SocialInsuranceStorageError(
            "社保报盘在云端运行必须配置私有持久化存储；已拒绝写入临时目录。"
        )


def storage_status() -> dict[str, Any]:
    enabled = persistent_storage_enabled()
    return {
        "mode": "serverless" if serverless_runtime() else "local-development",
        "backend": storage_backend() or "local",
        "environment": storage_environment(),
        "persistent": enabled,
        "ready": enabled if serverless_runtime() else True,
    }


def _root() -> str:
    return f"{ROOT_PREFIX}/{storage_environment()}"


def _run_prefix(run_id: str) -> str:
    return f"{_root()}/runs/{run_id}"


def _json_path(namespace: str, key: str) -> str:
    safe_namespace = re.sub(r"[^0-9A-Za-z_-]+", "-", namespace.strip()).strip("-_")
    safe_key = re.sub(r"[^0-9A-Za-z_.-]+", "-", key.strip()).strip("-_")
    if not safe_namespace or not safe_key:
        raise SocialInsuranceStorageError("持久化对象路径无效")
    return f"{_root()}/{safe_namespace}/{safe_key}.json"


def _fresh_storage_target(pathname_or_url: str, *, version: str = "") -> str:
    separator = "&" if "?" in pathname_or_url else "?"
    marker = version or str(time.time_ns())
    return f"{pathname_or_url}{separator}{urlencode({'sigma-read-version': marker})}"


def _put_bytes(pathname: str, content: bytes, *, content_type: str) -> dict[str, Any]:
    if storage_backend() == "supabase":
        try:
            return supabase_upload_bytes(pathname, content, content_type=content_type)
        except Exception as exc:  # noqa: BLE001 - normalize vendor errors safely.
            _raise_supabase_error(exc, operation="上传")
    return blob_put_bytes(pathname, content, content_type=content_type)


def _get_bytes(pathname_or_url: str) -> bytes | None:
    if storage_backend() == "supabase":
        try:
            return supabase_download_bytes(pathname_or_url)
        except httpx.HTTPStatusError as exc:
            if _supabase_object_missing(exc.response):
                return None
            _raise_supabase_error(exc, operation="下载")
        except Exception as exc:  # noqa: BLE001 - normalize vendor errors safely.
            _raise_supabase_error(exc, operation="下载")
    return blob_get_bytes(pathname_or_url)


def _supabase_object_missing(response: httpx.Response) -> bool:
    if response.status_code != 400:
        return False
    try:
        payload = response.json()
    except ValueError:
        return False
    if not isinstance(payload, dict):
        return False
    embedded_status = str(
        payload.get("statusCode") or payload.get("httpStatusCode") or ""
    ).strip()
    if embedded_status != "404":
        return False
    identifiers = {
        str(payload.get("code") or "").strip().casefold(),
        str(payload.get("error") or "").strip().casefold(),
    }
    return bool(identifiers & {"nosuchkey", "not_found", "notfound"})


def _list_prefix(prefix: str) -> list[dict[str, Any]]:
    if storage_backend() != "supabase":
        return blob_list_prefix(prefix)
    rows: list[dict[str, Any]] = []
    normalized_prefix = prefix.rstrip("/")
    pending = [normalized_prefix]
    visited: set[str] = set()
    try:
        while pending:
            current_prefix = pending.pop()
            if current_prefix in visited:
                continue
            visited.add(current_prefix)
            for entry in supabase_list_objects(current_prefix):
                name = str(entry.get("name") or "").strip("/")
                if not name or "/" in name or name in {".", ".."}:
                    continue
                pathname = supabase_entry_path(current_prefix, entry)
                if not pathname or not pathname.startswith(f"{current_prefix}/"):
                    continue
                if entry.get("id") is None and entry.get("metadata") is None:
                    pending.append(pathname)
                    continue
                rows.append(
                    {
                        "pathname": pathname,
                        "uploadedAt": entry.get("updated_at")
                        or entry.get("created_at")
                        or "",
                    }
                )
    except Exception as exc:  # noqa: BLE001 - normalize vendor errors without leaking credentials.
        _raise_supabase_error(exc, operation="列表读取")
    return sorted(rows, key=lambda row: str(row["pathname"]))


def _raise_supabase_error(exc: Exception, *, operation: str) -> NoReturn:
    if isinstance(exc, SocialInsuranceStorageError):
        raise exc
    if isinstance(exc, httpx.TimeoutException):
        raise SocialInsuranceStorageError(
            f"Supabase Storage {operation}超时，请稍后重试。",
            code="SOCIAL_INSURANCE_STORAGE_TIMEOUT",
            retryable=True,
        ) from exc
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = int(exc.response.status_code)
        if status_code in {401, 403}:
            raise SocialInsuranceStorageError(
                f"Supabase Storage {operation}权限失败，请检查 Storage 凭证或 bucket 权限。",
                code="SOCIAL_INSURANCE_STORAGE_PERMISSION_DENIED",
                status_code=status_code,
            ) from exc
        raise SocialInsuranceStorageError(
            f"Supabase Storage {operation}失败，HTTP {status_code}。",
            code="SOCIAL_INSURANCE_STORAGE_HTTP_ERROR",
            retryable=status_code >= 500,
            status_code=status_code,
        ) from exc
    if isinstance(exc, httpx.RequestError):
        raise SocialInsuranceStorageError(
            f"Supabase Storage {operation}网络异常，请稍后重试。",
            code="SOCIAL_INSURANCE_STORAGE_NETWORK_ERROR",
            retryable=True,
        ) from exc
    raise SocialInsuranceStorageError(
        f"Supabase Storage {operation}失败。",
        code="SOCIAL_INSURANCE_STORAGE_ERROR",
    ) from exc


def persist_json(namespace: str, key: str, payload: dict[str, Any]) -> None:
    require_persistent_storage()
    if not persistent_storage_enabled():
        return
    _put_bytes(
        _json_path(namespace, key),
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        content_type="application/json",
    )


def load_json(namespace: str, key: str) -> dict[str, Any] | None:
    require_persistent_storage()
    if not persistent_storage_enabled():
        return None
    content = _get_bytes(_fresh_storage_target(_json_path(namespace, key)))
    if content is None:
        return None
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SocialInsuranceStorageError("持久化对象内容不可读取") from exc
    if not isinstance(payload, dict):
        raise SocialInsuranceStorageError("持久化对象格式无效")
    return payload


def list_json(namespace: str) -> list[dict[str, Any]]:
    require_persistent_storage()
    if not persistent_storage_enabled():
        return []
    prefix = f"{_root()}/{namespace.strip('/')}/"
    rows: list[dict[str, Any]] = []
    latest: dict[str, dict[str, Any]] = {}
    for blob in _list_prefix(prefix):
        pathname = str(blob.get("pathname") or "")
        if not pathname.endswith(".json"):
            continue
        uploaded_at = str(blob.get("uploadedAt") or blob.get("uploaded_at") or "")
        existing = latest.get(pathname)
        existing_at = str(existing.get("uploadedAt") or existing.get("uploaded_at") or "") if existing else ""
        if existing is None or uploaded_at >= existing_at:
            latest[pathname] = blob
    for pathname in sorted(latest):
        blob = latest[pathname]
        # Object-store list metadata can briefly lag an overwrite.  Always use
        # a new marker so another function instance reads the current body.
        content = _get_bytes(_fresh_storage_target(str(blob.get("url") or pathname)))
        if content is None:
            continue
        try:
            payload = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def persist_run_document(run_id: str, run_path: Path) -> None:
    """Persist only run.json at the same object key used by full directory saves."""
    require_persistent_storage()
    if not persistent_storage_enabled():
        return
    try:
        content = run_path.read_bytes()
    except OSError as exc:
        raise SocialInsuranceStorageError("社保报盘批次文件不可读取") from exc
    _put_bytes(
        f"{_run_prefix(run_id)}/run.json",
        content,
        content_type="application/json",
    )


def restore_run_document(run_id: str, run_path: Path) -> bool:
    """Restore only run.json without listing or downloading report artifacts."""
    require_persistent_storage()
    if not persistent_storage_enabled():
        return False
    content = _get_bytes(
        _fresh_storage_target(f"{_run_prefix(run_id)}/run.json")
    )
    if content is None:
        return False
    run_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = run_path.with_name(f".{run_path.name}.restore.tmp")
    try:
        temporary.write_bytes(content)
        temporary.replace(run_path)
        run_path.chmod(0o600)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise SocialInsuranceStorageError("社保报盘批次文件未能恢复") from exc
    return True


def persist_run_directory(run_id: str, run_dir: Path) -> None:
    require_persistent_storage()
    if not persistent_storage_enabled():
        return
    manifest_path = f"{_run_prefix(run_id)}/{RUN_MANIFEST}"
    manifest_content = _get_bytes(_fresh_storage_target(manifest_path))
    try:
        previous_manifest = json.loads(manifest_content.decode("utf-8")) if manifest_content else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        previous_manifest = {}
    if not isinstance(previous_manifest, dict):
        previous_manifest = {}
    next_manifest: dict[str, str] = {}
    for path in sorted(run_dir.rglob("*")):
        if not path.is_file() or path.name.endswith(".tmp") or path.name.startswith(".approved-"):
            continue
        relative = path.relative_to(run_dir).as_posix()
        content_type, _ = mimetypes.guess_type(path.name)
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        next_manifest[relative] = digest
        if previous_manifest.get(relative) == digest:
            continue
        _put_bytes(
            f"{_run_prefix(run_id)}/{relative}",
            content,
            content_type=content_type or "application/octet-stream",
        )
    if previous_manifest != next_manifest:
        _put_bytes(
            manifest_path,
            json.dumps(next_manifest, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            content_type="application/json",
        )


def restore_run_directory(run_id: str, run_dir: Path) -> bool:
    require_persistent_storage()
    if not persistent_storage_enabled():
        return False
    prefix = f"{_run_prefix(run_id)}/"
    blobs = _list_prefix(prefix)
    if not blobs:
        return False
    latest: dict[str, dict[str, Any]] = {}
    for blob in blobs:
        pathname = str(blob.get("pathname") or "")
        if not pathname.startswith(prefix):
            continue
        uploaded_at = str(blob.get("uploadedAt") or blob.get("uploaded_at") or "")
        existing = latest.get(pathname)
        existing_at = str(existing.get("uploadedAt") or existing.get("uploaded_at") or "") if existing else ""
        if existing is None or uploaded_at >= existing_at:
            latest[pathname] = blob
    run_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    restored = False
    for pathname, blob in latest.items():
        relative = pathname[len(prefix) :]
        if not relative or relative.endswith("/") or relative == RUN_MANIFEST:
            continue
        # A per-read marker prevents stale list metadata from reusing an older
        # cached object body in another function instance.
        content = _get_bytes(_fresh_storage_target(str(blob.get("url") or pathname)))
        if content is None:
            continue
        target = run_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = target.with_name(f".{target.name}.restore.tmp")
        temporary.write_bytes(content)
        temporary.replace(target)
        restored = True
    return restored


def list_persisted_runs() -> list[dict[str, Any]]:
    require_persistent_storage()
    if not persistent_storage_enabled():
        return []
    prefix = f"{_root()}/runs/"
    latest: dict[str, dict[str, Any]] = {}
    for blob in _list_prefix(prefix):
        pathname = str(blob.get("pathname") or "")
        if not pathname.endswith("/run.json"):
            continue
        uploaded_at = str(blob.get("uploadedAt") or blob.get("uploaded_at") or "")
        existing = latest.get(pathname)
        existing_at = str(existing.get("uploadedAt") or existing.get("uploaded_at") or "") if existing else ""
        if existing is None or uploaded_at >= existing_at:
            latest[pathname] = blob
    def read_run(item: tuple[str, dict[str, Any]]) -> dict[str, Any] | None:
        pathname, blob = item
        content = _get_bytes(_fresh_storage_target(str(blob.get("url") or pathname)))
        if content is None:
            return None
        try:
            payload = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return deepcopy(payload) if isinstance(payload, dict) else None

    items = list(latest.items())
    if len(items) <= 1:
        loaded = [read_run(item) for item in items]
    else:
        with ThreadPoolExecutor(max_workers=min(8, len(items))) as executor:
            loaded = list(executor.map(read_run, items))
    return [payload for payload in loaded if payload is not None]


def object_key(*values: str) -> str:
    return hashlib.sha256("\0".join(values).encode("utf-8")).hexdigest()
