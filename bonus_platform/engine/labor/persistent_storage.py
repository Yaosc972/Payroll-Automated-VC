from __future__ import annotations

import json
import mimetypes
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .blob_storage import (
    RUN_PREFIX,
    canonicalize_labor_metadata_for_blob,
    labor_blob_environment,
    labor_blob_storage_enabled,
    materialize_labor_metadata_for_local,
    sync_labor_run_from_blob,
    sync_labor_run_to_blob,
    list_labor_metadata_from_blob,
)


class SupabaseStorageStatusError(RuntimeError):
    def __init__(self, status_code: int, text: str):
        super().__init__(f"Supabase Storage returned HTTP {status_code}")
        self.status_code = status_code
        self.text = text


def labor_storage_backend() -> str:
    return os.environ.get("SIGMA_LABOR_STORAGE_BACKEND", "").strip().lower()


def labor_supabase_storage_enabled() -> bool:
    if labor_storage_backend() != "supabase":
        return False
    return bool(_supabase_url() and _supabase_token() and labor_supabase_bucket())


def labor_persistent_storage_enabled() -> bool:
    return labor_blob_storage_enabled() or labor_supabase_storage_enabled()


def labor_persistent_storage_info() -> dict[str, Any]:
    if labor_supabase_storage_enabled():
        return {
            "enabled": True,
            "backend": "supabase",
            "bucket": labor_supabase_bucket(),
            "environment": labor_persistent_environment(),
        }
    if labor_blob_storage_enabled():
        return {
            "enabled": True,
            "backend": "blob",
            "environment": labor_blob_environment(),
        }
    return {"enabled": False, "backend": ""}


def labor_persistent_storage_health(*, probe: bool = False) -> dict[str, Any]:
    backend = labor_storage_backend()
    health: dict[str, Any] = {
        "backend": backend,
        "environment": labor_persistent_environment(),
        "enabled": labor_persistent_storage_enabled(),
        "probe": bool(probe),
    }
    if backend == "supabase":
        health.update(
            {
                "bucket": labor_supabase_bucket(),
                "supabaseUrlConfigured": bool(_supabase_url()),
                "serviceRoleConfigured": bool(_supabase_token()),
            }
        )
        if not probe:
            return health
        if not _supabase_url() or not _supabase_token() or not labor_supabase_bucket():
            health.update({"ok": False, "errorType": "missing_configuration"})
            return health
        try:
            object_path = _supabase_object_path(
                "_health",
                f"storage-health-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.json",
            )
            _supabase_upload_bytes(
                object_path,
                json.dumps({"ok": True, "checkedAt": datetime.utcnow().isoformat() + "Z"}).encode("utf-8"),
                content_type="application/json",
            )
            health.update({"ok": True})
        except SupabaseStorageStatusError as exc:
            health.update(
                {
                    "ok": False,
                    "errorType": "http_status",
                    "statusCode": exc.status_code,
                    "errorMessage": exc.text[:240],
                }
            )
        except Exception as exc:
            health.update({"ok": False, "errorType": type(exc).__name__, "errorMessage": str(exc)[:240]})
        return health
    if backend == "blob":
        health.update({"ok": labor_blob_storage_enabled()})
        return health
    health.update({"ok": not backend, "errorType": "" if not backend else "unsupported_backend"})
    return health


def labor_persistent_environment() -> str:
    raw = (
        os.environ.get("SIGMA_LABOR_STORAGE_ENV")
        or os.environ.get("VERCEL_ENV")
        or os.environ.get("SIGMA_OVERSEAS_LABOR_ACCESS")
        or "local"
    )
    value = re.sub(r"[^0-9A-Za-z_-]+", "-", raw.strip().lower()).strip("-_")
    return value or "local"


def sync_labor_run_to_persistent(run_id: str, run_dir: Path) -> None:
    if labor_supabase_storage_enabled():
        sync_labor_run_to_supabase(run_id, run_dir)
        return
    if labor_blob_storage_enabled():
        sync_labor_run_to_blob(run_id, run_dir)


def sync_labor_run_from_persistent(run_id: str, run_dir: Path) -> bool:
    if labor_supabase_storage_enabled():
        return sync_labor_run_from_supabase(run_id, run_dir)
    if labor_blob_storage_enabled():
        return sync_labor_run_from_blob(run_id, run_dir)
    return False


def list_labor_metadata_from_persistent() -> list[dict[str, Any]]:
    if labor_supabase_storage_enabled():
        return list_labor_metadata_from_supabase()
    if labor_blob_storage_enabled():
        return list_labor_metadata_from_blob()
    return []


def _supabase_url() -> str:
    return (os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL") or "").strip().rstrip("/")


def _supabase_token() -> str:
    return (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_STORAGE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_ANON_KEY")
        or ""
    ).strip()


def labor_supabase_bucket() -> str:
    return (
        os.environ.get("SIGMA_LABOR_SUPABASE_BUCKET")
        or os.environ.get("SUPABASE_STORAGE_BUCKET")
        or "sigma-labor-runs"
    ).strip()


def create_labor_supabase_signed_upload(run_id: str, relative_path: str) -> dict[str, Any]:
    object_path = _supabase_object_path(run_id, relative_path)
    url = _supabase_storage_url(f"object/upload/sign/{labor_supabase_bucket()}/{_quote_supabase_object_path(object_path)}")
    body = _supabase_request(
        "POST",
        url,
        headers=_supabase_headers({"content-type": "application/json", "x-upsert": "true"}),
        content=b"{}",
    )
    try:
        data = json.loads(body.decode("utf-8")) if body else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError("Supabase Storage 签名上传地址返回内容异常。") from exc
    signed_path = str(data.get("url") or data.get("signedURL") or data.get("signedUrl") or "").strip()
    token = str(data.get("token") or "").strip()
    if not signed_path:
        raise RuntimeError("Supabase Storage 未返回签名上传地址。")
    signed_url = signed_path if signed_path.startswith(("http://", "https://")) else f"{_supabase_storage_url()}{signed_path}"
    return {"signedUrl": signed_url, "token": token, "objectPath": object_path, "relativePath": relative_path}


def _supabase_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    token = _supabase_token()
    if not token:
        raise RuntimeError("缺少 SUPABASE_SERVICE_ROLE_KEY，无法访问 Supabase Storage。")
    headers = {"apikey": token, "authorization": f"Bearer {token}"}
    if extra:
        headers.update(extra)
    return headers


def _supabase_object_path(run_id: str, relative_path: str) -> str:
    normalized = relative_path.replace("\\", "/").lstrip("/")
    return f"{RUN_PREFIX}/{labor_persistent_environment()}/{run_id}/{normalized}"


def _supabase_relative_path(run_id: str, object_path: str) -> str:
    prefix = f"{RUN_PREFIX}/{labor_persistent_environment()}/{run_id}/"
    return object_path[len(prefix) :] if object_path.startswith(prefix) else object_path


def _supabase_storage_url(path: str = "") -> str:
    base = _supabase_url()
    if not base:
        raise RuntimeError("缺少 SUPABASE_URL，无法访问 Supabase Storage。")
    suffix = path.lstrip("/")
    return f"{base}/storage/v1/{suffix}" if suffix else f"{base}/storage/v1"


def _quote_supabase_object_path(object_path: str) -> str:
    return quote(object_path.replace("\\", "/").lstrip("/"), safe="/")


def _supabase_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    content: bytes | None = None,
) -> bytes:
    request = Request(url, data=content, headers=headers or {}, method=method)
    try:
        with urlopen(request, timeout=120.0) as response:
            return response.read()
    except HTTPError as exc:
        raise SupabaseStorageStatusError(exc.code, exc.read().decode("utf-8", errors="replace")) from exc


def _supabase_upload_bytes(object_path: str, content: bytes, *, content_type: str) -> dict[str, Any]:
    url = _supabase_storage_url(f"object/{labor_supabase_bucket()}/{_quote_supabase_object_path(object_path)}")
    headers = _supabase_headers({"content-type": content_type, "x-upsert": "true"})
    body = _supabase_request("POST", url, headers=headers, content=content)
    if not body:
        return {}
    try:
        return json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        return {}


def _supabase_download_bytes(object_path: str) -> bytes | None:
    url = _supabase_storage_url(f"object/{labor_supabase_bucket()}/{_quote_supabase_object_path(object_path)}")
    try:
        return _supabase_request("GET", url, headers=_supabase_headers())
    except SupabaseStorageStatusError as exc:
        if exc.status_code == 404:
            return None
        raise


def _supabase_list_objects(prefix: str) -> list[dict[str, Any]]:
    url = _supabase_storage_url(f"object/list/{labor_supabase_bucket()}")
    rows: list[dict[str, Any]] = []
    offset = 0
    limit = 1000
    while True:
        payload = {
            "prefix": prefix.rstrip("/"),
            "limit": limit,
            "offset": offset,
            "sortBy": {"column": "updated_at", "order": "desc"},
        }
        body = _supabase_request(
            "POST",
            url,
            headers=_supabase_headers({"content-type": "application/json"}),
            content=json.dumps(payload).encode("utf-8"),
        )
        batch = json.loads(body.decode("utf-8")) if body else []
        if not isinstance(batch, list) or not batch:
            break
        rows.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
    return rows


def _supabase_entry_path(prefix: str, entry: dict[str, Any]) -> str:
    name = str(entry.get("name") or "")
    if not name:
        return ""
    return f"{prefix.rstrip('/')}/{name}".lstrip("/")


def sync_labor_run_to_supabase(run_id: str, run_dir: Path) -> None:
    if not labor_supabase_storage_enabled() or not run_dir.exists():
        return
    for path in sorted(run_dir.rglob("*")):
        if not path.is_file() or path.name.endswith(".tmp"):
            continue
        relative = path.relative_to(run_dir).as_posix()
        content = path.read_bytes()
        if relative == "metadata.json":
            content = json.dumps(
                canonicalize_labor_metadata_for_blob(run_dir, json.loads(content.decode("utf-8"))),
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8")
        content_type, _ = mimetypes.guess_type(path.name)
        _supabase_upload_bytes(
            _supabase_object_path(run_id, relative),
            content,
            content_type=content_type or "application/octet-stream",
        )


def sync_labor_run_from_supabase(run_id: str, run_dir: Path) -> bool:
    if not labor_supabase_storage_enabled():
        return False
    prefix = f"{RUN_PREFIX}/{labor_persistent_environment()}/{run_id}"
    objects = _supabase_list_objects(prefix)
    if not objects:
        return False
    run_dir.mkdir(parents=True, exist_ok=True)
    for entry in objects:
        object_path = _supabase_entry_path(prefix, entry)
        if not object_path:
            continue
        content = _supabase_download_bytes(object_path)
        if content is None:
            continue
        relative = _supabase_relative_path(run_id, object_path)
        local_path = run_dir / relative
        local_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = local_path.with_suffix(f"{local_path.suffix}.tmp")
        tmp_path.write_bytes(content)
        os.replace(tmp_path, local_path)
    _materialize_synced_metadata_file(run_dir)
    return True


def _materialize_synced_metadata_file(run_dir: Path) -> None:
    metadata_path = run_dir / "metadata.json"
    if not metadata_path.exists():
        return
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    materialized = materialize_labor_metadata_for_local(run_dir, metadata)
    tmp_path = metadata_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(materialized, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, metadata_path)


def list_labor_metadata_from_supabase() -> list[dict[str, Any]]:
    if not labor_supabase_storage_enabled():
        return []
    prefix = f"{RUN_PREFIX}/{labor_persistent_environment()}"
    rows: list[dict[str, Any]] = []
    for entry in _supabase_list_objects(prefix):
        object_path = _supabase_entry_path(prefix, entry)
        if not object_path.endswith("/metadata.json"):
            continue
        content = _supabase_download_bytes(object_path)
        if not content:
            continue
        try:
            rows.append(json.loads(content.decode("utf-8")))
        except json.JSONDecodeError:
            continue
    return sorted(rows, key=lambda row: row.get("updatedAt") or row.get("createdAt") or "", reverse=True)
