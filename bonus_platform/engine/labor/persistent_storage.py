from __future__ import annotations

import json
import hashlib
import mimetypes
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urlparse
from uuid import uuid4

import httpx

from .blob_storage import (
    RUN_PREFIX,
    canonicalize_labor_metadata_for_blob,
    labor_blob_environment,
    labor_blob_storage_enabled,
    materialize_labor_metadata_for_local,
    sync_labor_run_from_blob,
    sync_labor_run_to_blob,
    list_labor_metadata_from_blob,
    delete_labor_run_from_blob,
)


_RUN_LOCKS_GUARD = threading.Lock()
_RUN_LOCKS: dict[str, threading.RLock] = {}
_STORAGE_HEALTH_LOCK = threading.Lock()
_STORAGE_HEALTH_CACHE: dict[str, Any] = {"key": "", "checkedAt": 0.0, "value": None}


def _run_storage_lock(run_id: str) -> threading.RLock:
    with _RUN_LOCKS_GUARD:
        return _RUN_LOCKS.setdefault(str(run_id), threading.RLock())


def _persistent_retry(operation, *, attempts: int = 3):
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError):
            if attempt >= attempts:
                raise
            time.sleep(0.25 * (2 ** (attempt - 1)))


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


def labor_persistent_storage_health(*, probe: bool = False, cache_seconds: int = 60) -> dict[str, Any]:
    backend = labor_storage_backend()
    health: dict[str, Any] = {
        "backend": backend,
        "environment": labor_persistent_environment(),
        "enabled": labor_persistent_storage_enabled(),
        "ready": False,
        "private": False,
        "directUpload": False,
        "directDownload": False,
        "writeReadDelete": False,
        "probe": bool(probe),
    }
    if backend != "supabase":
        if backend == "blob":
            health["errorType"] = "direct_signed_flow_not_supported"
        elif backend:
            health["errorType"] = "unsupported_backend"
        else:
            health["errorType"] = "missing_configuration"
        return health
    health.update(
        {
            "bucket": labor_supabase_bucket(),
            "supabaseUrlConfigured": bool(_supabase_url()),
            "serviceRoleConfigured": bool(_supabase_token()),
        }
    )
    if not probe:
        return health
    cache_key = "|".join(
        (backend, _supabase_url(), labor_supabase_bucket(), labor_persistent_environment())
    )
    now = time.monotonic()
    if cache_seconds > 0:
        with _STORAGE_HEALTH_LOCK:
            cached = _STORAGE_HEALTH_CACHE.get("value")
            if (
                cached is not None
                and _STORAGE_HEALTH_CACHE.get("key") == cache_key
                and now - float(_STORAGE_HEALTH_CACHE.get("checkedAt") or 0) < cache_seconds
            ):
                return dict(cached)
    if not _supabase_url() or not _supabase_token() or not labor_supabase_bucket():
        health["errorType"] = "missing_configuration"
        return health
    try:
        bucket = _supabase_bucket_info()
        is_private = bucket.get("public") is False
        health["private"] = is_private
        if not is_private:
            health["errorType"] = "public_bucket_forbidden"
            result = health
        else:
            probe_result = _probe_supabase_direct_storage()
            health.update(
                {
                    "writeReadDelete": bool(probe_result.get("writeReadDelete")),
                    "directUpload": bool(probe_result.get("directUpload")),
                    "directDownload": bool(probe_result.get("directDownload")),
                }
            )
            health["ready"] = all(
                health[key]
                for key in ("private", "writeReadDelete", "directUpload", "directDownload")
            )
            if not health["ready"]:
                health["errorType"] = "probe_incomplete"
            result = health
    except httpx.HTTPStatusError as exc:
        result = {
            **health,
            "errorType": "http_status",
            "statusCode": int(exc.response.status_code),
        }
    except Exception as exc:  # noqa: BLE001 - health details must never expose credentials or signed URLs.
        result = {**health, "errorType": type(exc).__name__[:96]}
    if cache_seconds > 0:
        with _STORAGE_HEALTH_LOCK:
            _STORAGE_HEALTH_CACHE.update({"key": cache_key, "checkedAt": now, "value": dict(result)})
    return result


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
    with _run_storage_lock(run_id):
        if labor_supabase_storage_enabled():
            _persistent_retry(lambda: sync_labor_run_to_supabase(run_id, run_dir))
            return
        if labor_blob_storage_enabled():
            _persistent_retry(lambda: sync_labor_run_to_blob(run_id, run_dir))


def sync_labor_run_from_persistent(run_id: str, run_dir: Path) -> bool:
    with _run_storage_lock(run_id):
        if labor_supabase_storage_enabled():
            return bool(_persistent_retry(lambda: sync_labor_run_from_supabase(run_id, run_dir)))
        if labor_blob_storage_enabled():
            return bool(_persistent_retry(lambda: sync_labor_run_from_blob(run_id, run_dir)))
        return False


def list_labor_metadata_from_persistent() -> list[dict[str, Any]]:
    if labor_supabase_storage_enabled():
        return list_labor_metadata_from_supabase()
    if labor_blob_storage_enabled():
        return list_labor_metadata_from_blob()
    return []


def delete_labor_run_from_persistent(run_id: str, owner_user_id: str = "") -> None:
    with _run_storage_lock(run_id):
        if labor_supabase_storage_enabled():
            _persistent_retry(
                lambda: delete_labor_run_from_supabase(
                    run_id,
                    owner_user_id=owner_user_id,
                )
            )
            return
        if labor_blob_storage_enabled():
            _persistent_retry(lambda: delete_labor_run_from_blob(run_id))


def _supabase_url() -> str:
    return (os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL") or "").strip().rstrip("/")


def _supabase_token() -> str:
    return (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_STORAGE_SERVICE_ROLE_KEY")
        or ""
    ).strip()


def labor_supabase_bucket() -> str:
    return (
        os.environ.get("SIGMA_LABOR_SUPABASE_BUCKET")
        or os.environ.get("SUPABASE_STORAGE_BUCKET")
        or "sigma-labor-runs"
    ).strip()


def labor_p1_object_key(
    *,
    owner_user_id: str,
    run_id: str,
    file_id: str,
    filename: str,
    category: str = "inputs",
) -> str:
    owner = _safe_object_segment(owner_user_id, "owner")
    run = _safe_object_segment(run_id, "run")
    file_key = _safe_object_segment(file_id, "file")
    category_key = _safe_object_segment(category, "inputs")
    safe_name = _safe_storage_filename(filename)
    return (
        f"{RUN_PREFIX}/{labor_persistent_environment()}/owners/{owner}/"
        f"runs/{run}/{category_key}/{file_key}/{safe_name}"
    )


def create_labor_supabase_signed_upload(
    *,
    owner_user_id: str,
    run_id: str,
    file_id: str,
    filename: str,
    file_kind: str,
    content_type: str = "application/octet-stream",
) -> dict[str, Any]:
    object_key = labor_p1_object_key(
        owner_user_id=owner_user_id,
        run_id=run_id,
        file_id=file_id,
        filename=filename,
        category="inputs",
    )
    return create_labor_supabase_signed_upload_for_object(
        object_key,
        file_kind=file_kind,
        content_type=content_type,
    )


def persist_labor_private_output(
    *,
    owner_user_id: str,
    run_id: str,
    output_kind: str,
    path: Path,
    expected_sha256: str,
    expected_size_bytes: int,
) -> dict[str, Any]:
    """Upload one verified Worker output into the owner-scoped private namespace."""

    if not labor_supabase_storage_enabled():
        raise RuntimeError("P1 Worker 输出持久化要求配置 Supabase 私有对象存储。")
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError("Worker 输出文件不存在。")
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    actual_sha256 = digest.hexdigest()
    expected_digest = str(expected_sha256 or "").strip().lower()
    try:
        expected_size = int(expected_size_bytes)
    except (TypeError, ValueError) as exc:
        raise ValueError("Worker 输出文件大小清单无效。") from exc
    if (
        not re.fullmatch(r"[0-9a-f]{64}", expected_digest)
        or expected_digest != actual_sha256
        or expected_size <= 0
        or source.stat().st_size != expected_size
    ):
        raise ValueError("Worker 输出文件与大小或 SHA-256 清单不一致。")
    object_key = labor_p1_object_key(
        owner_user_id=owner_user_id,
        run_id=run_id,
        file_id=f"{_safe_object_segment(output_kind, 'output')}-{actual_sha256[:16]}",
        filename=source.name,
        category="outputs",
    )
    content_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
    _supabase_upload_bytes(
        object_key,
        source.read_bytes(),
        content_type=content_type,
    )
    observed = labor_supabase_object_metadata(object_key)
    if int(observed.get("sizeBytes") or 0) != expected_size:
        raise RuntimeError("私有存储中的 Worker 输出大小与本地结果不一致。")
    return {
        "objectKey": object_key,
        "storageBackend": "supabase",
        "storagePrivate": True,
        "storageVerified": True,
        "storageVerifiedAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "storageVerifiedSizeBytes": expected_size,
        "contentType": str(observed.get("contentType") or content_type),
        "sizeBytes": expected_size,
        "sha256": actual_sha256,
    }


def create_labor_supabase_signed_upload_for_object(
    object_key: str,
    *,
    file_kind: str,
    content_type: str = "application/octet-stream",
) -> dict[str, Any]:
    if not labor_supabase_storage_enabled():
        raise RuntimeError("P1 签名直传要求配置 Supabase 私有对象存储。")
    normalized_key = _normalize_labor_p1_object_key(object_key)
    path = f"object/upload/sign/{quote(labor_supabase_bucket(), safe='')}/{quote(normalized_key, safe='/')}"
    data = _supabase_json_request(
        "POST",
        path,
        json_body={"upsert": False},
        extra_headers={"x-upsert": "false"},
    )
    signed_path = str(data.get("signedURL") or data.get("signedUrl") or data.get("url") or "").strip()
    token = str(data.get("token") or "").strip()
    if not signed_path:
        raise RuntimeError("Supabase Storage 未返回签名上传地址。")
    signed_url = _absolute_supabase_signed_url(signed_path, token=token)
    return {
        "signedUrl": signed_url,
        "token": token,
        "method": "PUT",
        "headers": {"content-type": str(content_type or "application/octet-stream")},
        "objectKey": normalized_key,
        "fileKind": _safe_object_segment(file_kind, "other"),
        "expiresIn": 7200,
        "private": True,
    }


def create_labor_supabase_signed_download(
    object_key: str,
    *,
    filename: str = "",
    expires_in: int = 120,
) -> dict[str, Any]:
    if not labor_supabase_storage_enabled():
        raise RuntimeError("P1 签名下载要求配置 Supabase 私有对象存储。")
    normalized_key = _normalize_labor_p1_object_key(object_key)
    ttl = max(30, min(int(expires_in or 120), 600))
    safe_filename = _safe_storage_filename(filename) if filename else ""
    data = _supabase_json_request(
        "POST",
        f"object/sign/{quote(labor_supabase_bucket(), safe='')}/{quote(normalized_key, safe='/')}",
        json_body={"expiresIn": ttl},
    )
    signed_path = str(data.get("signedURL") or data.get("signedUrl") or data.get("url") or "").strip()
    if not signed_path:
        raise RuntimeError("Supabase Storage 未返回签名下载地址。")
    signed_url = _absolute_supabase_signed_url(signed_path)
    if safe_filename:
        separator = "&" if "?" in signed_url else "?"
        signed_url = f"{signed_url}{separator}{urlencode({'download': safe_filename})}"
    return {
        "signedUrl": signed_url,
        "expiresIn": ttl,
        "private": True,
        "filename": safe_filename,
    }


def put_labor_supabase_private_object(
    object_key: str,
    content: bytes,
    *,
    content_type: str = "application/octet-stream",
) -> dict[str, Any]:
    normalized_key = _normalize_labor_p1_object_key(object_key)
    return _supabase_upload_bytes(normalized_key, content, content_type=content_type)


def get_labor_supabase_private_object(object_key: str) -> bytes | None:
    normalized_key = _normalize_labor_p1_object_key(object_key)
    return _supabase_download_bytes(normalized_key)


def labor_supabase_object_metadata(object_key: str) -> dict[str, Any]:
    """Read object metadata with service credentials without proxying the file body."""
    if not labor_supabase_storage_enabled():
        raise RuntimeError("P1 文件确认要求配置 Supabase 私有对象存储。")
    normalized_key = _normalize_labor_p1_object_key(object_key)
    url = _supabase_storage_url(
        f"object/{quote(labor_supabase_bucket(), safe='')}/{quote(normalized_key, safe='/')}"
    )

    def response_size(response: httpx.Response) -> int:
        content_range = str(response.headers.get("content-range") or "")
        range_match = re.search(r"/(\d+)\s*$", content_range)
        raw_size = range_match.group(1) if range_match else response.headers.get("content-length")
        try:
            return int(raw_size or 0)
        except (TypeError, ValueError):
            return 0

    with httpx.Client(timeout=30.0) as client:
        response = client.request("HEAD", url, headers=_supabase_headers())
        if response.status_code not in {405, 501}:
            response.raise_for_status()
        size_bytes = response_size(response)
        if response.status_code in {405, 501} or size_bytes <= 0:
            response = client.request(
                "GET",
                url,
                headers=_supabase_headers({"range": "bytes=0-0"}),
            )
            response.raise_for_status()
            size_bytes = response_size(response)
    if size_bytes <= 0:
        raise RuntimeError("Supabase Storage 文件大小无效。")
    return {
        "objectKey": normalized_key,
        "sizeBytes": size_bytes,
        "contentType": str(response.headers.get("content-type") or "application/octet-stream"),
    }


def _supabase_json_request(
    method: str,
    path: str,
    *,
    json_body: Any = None,
    extra_headers: dict[str, str] | None = None,
) -> Any:
    headers = _supabase_headers({"content-type": "application/json", **(extra_headers or {})})
    with httpx.Client(timeout=120.0) as client:
        response = client.request(
            method,
            _supabase_storage_url(path),
            headers=headers,
            json=json_body,
        )
    response.raise_for_status()
    if not response.content:
        return {}
    return response.json()


def _supabase_bucket_info() -> dict[str, Any]:
    data = _supabase_json_request(
        "GET",
        f"bucket/{quote(labor_supabase_bucket(), safe='')}",
    )
    if not isinstance(data, dict):
        raise RuntimeError("Supabase Storage bucket 信息格式异常。")
    return data


def _probe_supabase_direct_storage() -> dict[str, bool]:
    probe_id = uuid4().hex
    payload = json.dumps(
        {"probe": probe_id, "checkedAt": datetime.now(timezone.utc).isoformat()},
        separators=(",", ":"),
    ).encode("utf-8")
    intent = create_labor_supabase_signed_upload(
        owner_user_id="_health",
        run_id=f"health-{probe_id[:12]}",
        file_id=probe_id,
        filename="storage-health.json",
        file_kind="health_probe",
        content_type="application/json",
    )
    object_key = intent["objectKey"]
    object_prefix = object_key.rsplit("/", 1)[0]
    direct_upload = False
    direct_download = False
    write_read_delete = False
    try:
        with httpx.Client(timeout=30.0) as client:
            uploaded = client.put(
                intent["signedUrl"],
                headers=intent["headers"],
                content=payload,
            )
        uploaded.raise_for_status()
        direct_upload = True
        stored = _supabase_download_bytes(object_key)
        write_read_delete = stored == payload
        download = create_labor_supabase_signed_download(
            object_key,
            filename="storage-health.json",
            expires_in=60,
        )
        with httpx.Client(timeout=30.0) as client:
            downloaded = client.get(download["signedUrl"])
        downloaded.raise_for_status()
        direct_download = downloaded.content == payload
    finally:
        _supabase_delete_objects([object_key])
    remaining_paths = {
        _supabase_entry_path(object_prefix, entry)
        for entry in _supabase_list_objects(object_prefix)
    }
    write_read_delete = write_read_delete and object_key not in remaining_paths
    return {
        "writeReadDelete": write_read_delete,
        "directUpload": direct_upload,
        "directDownload": direct_download,
    }


def _absolute_supabase_signed_url(path: str, *, token: str = "") -> str:
    candidate = str(path or "").strip()
    if candidate.startswith(("http://", "https://")):
        absolute = candidate
    elif candidate.startswith("/storage/v1/"):
        absolute = f"{_supabase_url()}{candidate}"
    else:
        absolute = f"{_supabase_storage_url()}/{candidate.lstrip('/')}"
    if token and "token=" not in urlparse(absolute).query:
        separator = "&" if "?" in absolute else "?"
        absolute = f"{absolute}{separator}{urlencode({'token': token})}"
    parsed = urlparse(absolute)
    expected = urlparse(_supabase_url())
    if parsed.netloc != expected.netloc or parsed.scheme not in {"https", "http"}:
        raise RuntimeError("Supabase Storage 返回了非预期主机的签名地址。")
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1"}:
        raise RuntimeError("Supabase Storage 签名地址必须使用 HTTPS。")
    return absolute


def _normalize_labor_p1_object_key(object_key: str) -> str:
    normalized_key = str(object_key or "").replace("\\", "/").lstrip("/")
    expected_prefix = f"{RUN_PREFIX}/{labor_persistent_environment()}/owners/"
    if not normalized_key.startswith(expected_prefix) or ".." in normalized_key.split("/"):
        raise ValueError("对象路径不属于当前 P1 私有存储命名空间。")
    return normalized_key


def _safe_object_segment(value: str, fallback: str) -> str:
    text = re.sub(r"[^0-9A-Za-z_-]+", "_", str(value or "").strip()).strip("_-")
    return (text or fallback)[:128]


def _safe_storage_filename(value: str) -> str:
    name = Path(str(value or "file").replace("\\", "/")).name
    stem = re.sub(r"[^0-9A-Za-z._-]+", "_", name).strip("._-")
    stem = re.sub(r"\.{2,}", ".", stem)
    return (stem or "file")[:180]


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


def _supabase_upload_bytes(object_path: str, content: bytes, *, content_type: str) -> dict[str, Any]:
    url = _supabase_storage_url(f"object/{labor_supabase_bucket()}/{object_path}")
    headers = _supabase_headers({"content-type": content_type, "x-upsert": "true"})
    with httpx.Client(timeout=120.0) as client:
        response = client.post(url, headers=headers, content=content)
    response.raise_for_status()
    if not response.content:
        return {}
    try:
        return response.json()
    except json.JSONDecodeError:
        return {}


def _supabase_download_bytes(object_path: str) -> bytes | None:
    url = _supabase_storage_url(f"object/{labor_supabase_bucket()}/{object_path}")
    with httpx.Client(timeout=120.0) as client:
        response = client.get(url, headers=_supabase_headers())
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.content


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
        with httpx.Client(timeout=120.0) as client:
            response = client.post(url, headers=_supabase_headers({"content-type": "application/json"}), json=payload)
        response.raise_for_status()
        batch = response.json() if response.content else []
        if not isinstance(batch, list) or not batch:
            break
        rows.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
    return rows


def _supabase_delete_objects(object_paths: list[str]) -> None:
    if not object_paths:
        return
    url = _supabase_storage_url(f"object/{labor_supabase_bucket()}")
    with httpx.Client(timeout=120.0) as client:
        response = client.request(
            "DELETE",
            url,
            headers=_supabase_headers({"content-type": "application/json"}),
            json={"prefixes": object_paths},
        )
    response.raise_for_status()


def delete_labor_run_from_supabase(run_id: str, owner_user_id: str = "") -> None:
    if not labor_supabase_storage_enabled():
        return
    safe_run_id = _safe_object_segment(run_id, "run")
    prefixes = [f"{RUN_PREFIX}/{labor_persistent_environment()}/{safe_run_id}"]
    owner = str(owner_user_id or "").strip()
    if owner:
        prefixes.append(
            f"{RUN_PREFIX}/{labor_persistent_environment()}/owners/"
            f"{_safe_object_segment(owner, 'owner')}/runs/{safe_run_id}"
        )
    for prefix in prefixes:
        objects = _supabase_list_objects(prefix)
        paths = [_supabase_entry_path(prefix, entry) for entry in objects]
        _supabase_delete_objects([path for path in paths if path])


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
