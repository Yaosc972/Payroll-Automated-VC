from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import time
from typing import Any
from urllib.parse import urlencode

from ..labor.blob_storage import blob_get_bytes, blob_list_prefix, blob_put_bytes


ROOT_PREFIX = "social-insurance"
RUN_MANIFEST = ".storage-manifest.json"


class SocialInsuranceStorageError(RuntimeError):
    """社保报盘持久化存储未就绪或读写失败。"""


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
    return storage_backend() == "blob" and bool(os.environ.get("BLOB_READ_WRITE_TOKEN", "").strip())


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


def _fresh_blob_target(pathname_or_url: str, *, version: str = "") -> str:
    separator = "&" if "?" in pathname_or_url else "?"
    marker = version or str(time.time_ns())
    return f"{pathname_or_url}{separator}{urlencode({'sigma-read-version': marker})}"


def persist_json(namespace: str, key: str, payload: dict[str, Any]) -> None:
    require_persistent_storage()
    if not persistent_storage_enabled():
        return
    blob_put_bytes(
        _json_path(namespace, key),
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        content_type="application/json",
    )


def load_json(namespace: str, key: str) -> dict[str, Any] | None:
    require_persistent_storage()
    if not persistent_storage_enabled():
        return None
    content = blob_get_bytes(_fresh_blob_target(_json_path(namespace, key)))
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
    for blob in blob_list_prefix(prefix):
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
        version = str(blob.get("uploadedAt") or blob.get("uploaded_at") or "")
        content = blob_get_bytes(_fresh_blob_target(str(blob.get("url") or pathname), version=version))
        if content is None:
            continue
        try:
            payload = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def persist_run_directory(run_id: str, run_dir: Path) -> None:
    require_persistent_storage()
    if not persistent_storage_enabled():
        return
    manifest_path = f"{_run_prefix(run_id)}/{RUN_MANIFEST}"
    manifest_content = blob_get_bytes(_fresh_blob_target(manifest_path))
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
        blob_put_bytes(
            f"{_run_prefix(run_id)}/{relative}",
            content,
            content_type=content_type or "application/octet-stream",
        )
    if previous_manifest != next_manifest:
        blob_put_bytes(
            manifest_path,
            json.dumps(next_manifest, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            content_type="application/json",
        )


def restore_run_directory(run_id: str, run_dir: Path) -> bool:
    require_persistent_storage()
    if not persistent_storage_enabled():
        return False
    prefix = f"{_run_prefix(run_id)}/"
    blobs = blob_list_prefix(prefix)
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
        version = str(blob.get("uploadedAt") or blob.get("uploaded_at") or "")
        content = blob_get_bytes(_fresh_blob_target(str(blob.get("url") or pathname), version=version))
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
    for blob in blob_list_prefix(prefix):
        pathname = str(blob.get("pathname") or "")
        if not pathname.endswith("/run.json"):
            continue
        uploaded_at = str(blob.get("uploadedAt") or blob.get("uploaded_at") or "")
        existing = latest.get(pathname)
        existing_at = str(existing.get("uploadedAt") or existing.get("uploaded_at") or "") if existing else ""
        if existing is None or uploaded_at >= existing_at:
            latest[pathname] = blob
    rows: list[dict[str, Any]] = []
    for pathname, blob in latest.items():
        version = str(blob.get("uploadedAt") or blob.get("uploaded_at") or "")
        content = blob_get_bytes(_fresh_blob_target(str(blob.get("url") or pathname), version=version))
        if content is None:
            continue
        try:
            payload = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            rows.append(deepcopy(payload))
    return rows


def object_key(*values: str) -> str:
    return hashlib.sha256("\0".join(values).encode("utf-8")).hexdigest()
