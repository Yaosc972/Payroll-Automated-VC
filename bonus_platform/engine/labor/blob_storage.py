from __future__ import annotations

import base64
import json
import hashlib
import hmac
import mimetypes
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

import httpx


DEFAULT_BLOB_API_URL = "https://vercel.com/api/blob"
RUN_PREFIX = "labor-runs"
STORAGE_MANIFEST_FILE = ".sigma-storage-manifest.json"
_RW_TOKEN_RE = re.compile(r"^vercel_blob_rw_([^_]+)_[A-Za-z0-9]+$")


class LaborBlobError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool, status_code: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.status_code = status_code


def _wrap_blob_error(exc: Exception, *, operation: str) -> LaborBlobError:
    if isinstance(exc, LaborBlobError):
        return exc
    if isinstance(exc, httpx.TimeoutException):
        return LaborBlobError("LABOR_BLOB_TIMEOUT", f"Blob {operation} 超时，请稍后重试。", retryable=True)
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        if status_code in {401, 403}:
            return LaborBlobError(
                "LABOR_BLOB_PERMISSION_DENIED",
                f"Blob {operation} 权限失败，请检查 UAT Blob Token 或存储权限。",
                retryable=False,
                status_code=status_code,
            )
        return LaborBlobError(
            "LABOR_BLOB_HTTP_ERROR",
            f"Blob {operation} 失败，HTTP {status_code}。",
            retryable=status_code >= 500,
            status_code=status_code,
        )
    if isinstance(exc, httpx.RequestError):
        return LaborBlobError("LABOR_BLOB_NETWORK_ERROR", f"Blob {operation} 网络异常，请稍后重试。", retryable=True)
    return LaborBlobError("LABOR_BLOB_ERROR", f"Blob {operation} 失败：{exc}", retryable=False)


def _raise_blob_error(exc: Exception, *, operation: str) -> None:
    raise _wrap_blob_error(exc, operation=operation) from exc


def labor_blob_storage_enabled() -> bool:
    return os.environ.get("SIGMA_LABOR_STORAGE_BACKEND", "").strip().lower() == "blob" and bool(
        os.environ.get("BLOB_READ_WRITE_TOKEN")
    )


def labor_blob_signed_urls_enabled() -> bool:
    return bool(os.environ.get("BLOB_READ_WRITE_TOKEN", "").strip())


def labor_blob_store_id() -> str:
    configured = os.environ.get("BLOB_STORE_ID", "").strip()
    if configured:
        return configured if configured.startswith("store_") else f"store_{configured}"
    token = os.environ.get("BLOB_READ_WRITE_TOKEN", "").strip()
    match = _RW_TOKEN_RE.fullmatch(token)
    if not match:
        raise RuntimeError("无法从 BLOB_READ_WRITE_TOKEN 解析 Blob store id。")
    return f"store_{match.group(1)}"


def labor_blob_token() -> str:
    token = os.environ.get("BLOB_READ_WRITE_TOKEN", "").strip()
    if not token:
        raise RuntimeError("缺少 BLOB_READ_WRITE_TOKEN，无法访问 Vercel Blob。")
    return token


def labor_blob_environment() -> str:
    raw = (
        os.environ.get("SIGMA_LABOR_BLOB_ENV")
        or os.environ.get("VERCEL_ENV")
        or os.environ.get("SIGMA_OVERSEAS_LABOR_ACCESS")
        or "local"
    )
    value = re.sub(r"[^0-9A-Za-z_-]+", "-", raw.strip().lower()).strip("-_")
    return value or "local"


def labor_blob_run_prefix(run_id: str) -> str:
    return f"{RUN_PREFIX}/{labor_blob_environment()}/{run_id}"


def labor_blob_path(run_id: str, relative_path: str) -> str:
    normalized = relative_path.replace("\\", "/").lstrip("/")
    return f"{labor_blob_run_prefix(run_id)}/{normalized}"


def labor_blob_relative_path(run_id: str, blob_path: str) -> str:
    prefix = f"{labor_blob_run_prefix(run_id)}/"
    if blob_path.startswith(prefix):
        return blob_path[len(prefix) :]
    return blob_path


def _blob_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {
        "authorization": f"Bearer {labor_blob_token()}",
        "x-vercel-blob-store-id": labor_blob_store_id(),
        "x-api-version": "9",
    }
    if extra:
        headers.update(extra)
    return headers


def _blob_api_url(query: str = "") -> str:
    base = os.environ.get("VERCEL_BLOB_API_URL") or DEFAULT_BLOB_API_URL
    return f"{base}{query}"


def _blob_request(method: str, query: str = "", *, headers: dict[str, str] | None = None, content: bytes | None = None, json_body: Any = None) -> Any:
    with httpx.Client(timeout=120.0) as client:
        response = client.request(
            method,
            _blob_api_url(query),
            headers=_blob_headers(headers),
            content=content,
            json=json_body,
        )
    response.raise_for_status()
    if not response.content:
        return None
    return response.json()


def _base64url_decode_json(segment: str) -> dict[str, Any]:
    padding = "=" * ((4 - len(segment) % 4) % 4)
    payload = base64.urlsafe_b64decode(f"{segment}{padding}".encode("ascii"))
    parsed = json.loads(payload.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("Blob delegation payload is invalid.")
    return parsed


def create_labor_blob_presigned_url(
    pathname: str,
    *,
    operation: str,
    expires_in: int = 300,
    maximum_size_in_bytes: int | None = None,
    allowed_content_types: list[str] | None = None,
) -> str:
    """Create a short-lived URL scoped to one private Blob object operation."""
    normalized = str(pathname or "").replace("\\", "/").lstrip("/")
    if not normalized or not normalized.startswith(f"{RUN_PREFIX}/"):
        raise ValueError("Blob pathname is outside the labor private namespace.")
    if operation not in {"get", "put", "head", "delete"}:
        raise ValueError("Unsupported Blob signed URL operation.")
    ttl = max(60, min(int(expires_in), 7 * 24 * 60 * 60))
    valid_until = int(time.time() * 1000) + ttl * 1000
    body: dict[str, Any] = {
        "pathname": normalized,
        "operations": [operation],
        "validUntil": valid_until,
    }
    if maximum_size_in_bytes is not None:
        body["maximumSizeInBytes"] = int(maximum_size_in_bytes)
    if allowed_content_types:
        body["allowedContentTypes"] = [str(value) for value in allowed_content_types]
    issued = _blob_request(
        "POST",
        "/signed-token",
        headers={"content-type": "application/json", "x-api-version": "12"},
        json_body=body,
    )
    if not isinstance(issued, dict):
        raise RuntimeError("Blob signed token response is invalid.")
    delegation = str(issued.get("delegationToken") or "")
    client_signing_token = str(issued.get("clientSigningToken") or "")
    if "." not in delegation or not client_signing_token:
        raise RuntimeError("Blob signed token response is incomplete.")
    scope = _base64url_decode_json(delegation.split(".", 1)[0])
    store_id = str(scope.get("storeId") or "").removeprefix("store_")
    if not store_id:
        raise RuntimeError("Blob signed token does not identify a store.")
    presign_options = {"vercel-blob-add-random-suffix": "false"} if operation == "put" else {}
    canonical = "\n".join(
        sorted(
            (f"operation={operation}", f"pathname={normalized}"),
        )
        + sorted(f"{key}={value}" for key, value in presign_options.items())
    )
    signature = base64.urlsafe_b64encode(
        hmac.new(client_signing_token.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).digest()
    ).decode("ascii").rstrip("=")
    signed_params = urlencode(
        {
            "vercel-blob-delegation": delegation,
            "vercel-blob-signature": signature,
            **presign_options,
        }
    )
    if operation in {"get", "head"}:
        target = f"https://{store_id}.private.blob.vercel-storage.com/{quote(normalized, safe='/')}"
    else:
        target = f"{_blob_api_url('/')}?{urlencode({'pathname': normalized})}"
    separator = "&" if "?" in target else "?"
    return f"{target}{separator}{signed_params}"


def blob_put_bytes(pathname: str, content: bytes, *, content_type: str | None = None, access: str = "private") -> dict[str, Any]:
    params = httpx.QueryParams({"pathname": pathname})
    headers = {
        "x-vercel-blob-access": access,
        "x-add-random-suffix": "0",
        "x-allow-overwrite": "1",
        "x-content-length": str(len(content)),
    }
    if content_type:
        headers["x-content-type"] = content_type
    try:
        return _blob_request("PUT", f"/?{params}", headers=headers, content=content) or {}
    except Exception as exc:  # noqa: BLE001 - convert transport/vendor errors to stable audit codes.
        _raise_blob_error(exc, operation="上传")


def blob_list_prefix(prefix: str) -> list[dict[str, Any]]:
    cursor = ""
    rows: list[dict[str, Any]] = []
    try:
        while True:
            params = {"prefix": prefix, "limit": "1000", "mode": "expanded"}
            if cursor:
                params["cursor"] = cursor
            payload = _blob_request("GET", f"/?{httpx.QueryParams(params)}") or {}
            rows.extend(payload.get("blobs", []) or [])
            if not payload.get("hasMore"):
                break
            cursor = str(payload.get("cursor") or "")
            if not cursor:
                break
    except Exception as exc:  # noqa: BLE001 - convert transport/vendor errors to stable audit codes.
        _raise_blob_error(exc, operation="列表读取")
    return rows


def blob_get_bytes(pathname_or_url: str, *, access: str = "private") -> bytes | None:
    if pathname_or_url.startswith("http://") or pathname_or_url.startswith("https://"):
        url = pathname_or_url
    else:
        store_id = labor_blob_store_id().removeprefix("store_").lower()
        url = f"https://{store_id}.{access}.blob.vercel-storage.com/{pathname_or_url}"
    try:
        with httpx.Client(timeout=120.0) as client:
            response = client.get(url, headers={"authorization": f"Bearer {labor_blob_token()}"})
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.content
    except Exception as exc:  # noqa: BLE001 - convert transport/vendor errors to stable audit codes.
        _raise_blob_error(exc, operation="下载")


def blob_delete_pathnames(pathnames: list[str]) -> None:
    if not pathnames:
        return
    try:
        _blob_request("POST", "/delete", headers={"content-type": "application/json"}, json_body={"urls": pathnames})
    except Exception as exc:  # noqa: BLE001 - convert transport/vendor errors to stable audit codes.
        _raise_blob_error(exc, operation="删除")


def delete_labor_run_from_blob(run_id: str) -> None:
    if not labor_blob_storage_enabled():
        return
    blobs = blob_list_prefix(labor_blob_run_prefix(run_id))
    targets = [str(blob.get("url") or blob.get("pathname") or "") for blob in blobs]
    blob_delete_pathnames([target for target in targets if target])


def _latest_blob_entries(blobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for blob in blobs:
        pathname = str(blob.get("pathname") or "")
        if not pathname:
            continue
        current = latest.get(pathname)
        candidate_key = str(blob.get("uploadedAt") or blob.get("uploaded_at") or "")
        current_key = str(current.get("uploadedAt") or current.get("uploaded_at") or "") if current else ""
        if current is None or candidate_key >= current_key:
            latest[pathname] = blob
    return list(latest.values())


def canonicalize_labor_metadata_for_blob(run_dir: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    payload = json.loads(json.dumps(metadata, ensure_ascii=False))
    for file_info in (payload.get("files") or {}).values():
        if isinstance(file_info, list):
            for record in file_info:
                _canonicalize_file_record(run_dir, record)
        elif isinstance(file_info, dict):
            _canonicalize_file_record(run_dir, file_info)
    return payload


def materialize_labor_metadata_for_local(run_dir: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    payload = json.loads(json.dumps(metadata, ensure_ascii=False))
    for file_info in (payload.get("files") or {}).values():
        if isinstance(file_info, list):
            for record in file_info:
                _materialize_file_record(run_dir, record)
        elif isinstance(file_info, dict):
            _materialize_file_record(run_dir, file_info)
    return payload


def _canonicalize_file_record(run_dir: Path, record: Any) -> None:
    if not isinstance(record, dict):
        return
    raw_path = str(record.get("path") or "").strip()
    if not raw_path:
        return
    path = Path(raw_path)
    try:
        record["path"] = str(path.relative_to(run_dir))
    except ValueError:
        record["path"] = path.name


def _materialize_file_record(run_dir: Path, record: Any) -> None:
    if not isinstance(record, dict):
        return
    raw_path = str(record.get("path") or "").strip()
    if not raw_path:
        return
    path = Path(raw_path)
    record["path"] = str(path if path.is_absolute() else (run_dir / path))


def sync_labor_run_to_blob(run_id: str, run_dir: Path) -> None:
    if not labor_blob_storage_enabled():
        return
    if not run_dir.exists():
        return
    remote_manifest = _load_blob_storage_manifest(run_id)
    next_manifest: dict[str, str] = {}
    uploads: list[tuple[str, bytes, str]] = []
    for path in sorted(run_dir.rglob("*")):
        if not path.is_file() or path.name.endswith(".tmp"):
            continue
        relative = path.relative_to(run_dir).as_posix()
        content_type, _ = mimetypes.guess_type(path.name)
        content = path.read_bytes()
        if relative == "metadata.json":
            content = _canonical_metadata_file_bytes(run_dir, content)
        digest = hashlib.sha256(content).hexdigest()
        next_manifest[relative] = digest
        if remote_manifest.get(relative) != digest:
            uploads.append((relative, content, content_type or "application/octet-stream"))
    for relative, content, content_type in uploads:
        blob_put_bytes(labor_blob_path(run_id, relative), content, content_type=content_type)
    if remote_manifest != next_manifest:
        manifest_content = json.dumps(next_manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        blob_put_bytes(
            labor_blob_path(run_id, STORAGE_MANIFEST_FILE),
            manifest_content,
            content_type="application/json",
        )


def _load_blob_storage_manifest(run_id: str) -> dict[str, str]:
    blobs = _latest_blob_entries(blob_list_prefix(f"{labor_blob_run_prefix(run_id)}/"))
    manifest = next(
        (blob for blob in blobs if str(blob.get("pathname") or "").endswith(f"/{STORAGE_MANIFEST_FILE}")),
        None,
    )
    if not manifest:
        return {}
    content = blob_get_bytes(str(manifest.get("url") or manifest.get("pathname") or ""))
    if not content:
        return {}
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return {str(key): str(value) for key, value in payload.items()} if isinstance(payload, dict) else {}


def _canonical_metadata_file_bytes(run_dir: Path, content: bytes) -> bytes:
    try:
        metadata = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return content
    canonical = canonicalize_labor_metadata_for_blob(run_dir, metadata)
    return json.dumps(canonical, ensure_ascii=False, indent=2).encode("utf-8")


def sync_labor_run_from_blob(run_id: str, run_dir: Path) -> bool:
    if not labor_blob_storage_enabled():
        return False
    blobs = _latest_blob_entries(blob_list_prefix(f"{labor_blob_run_prefix(run_id)}/"))
    if not blobs:
        return False
    run_dir.mkdir(parents=True, exist_ok=True)
    for blob in blobs:
        pathname = str(blob.get("pathname") or "")
        relative = labor_blob_relative_path(run_id, pathname)
        if not relative or relative.endswith("/") or relative == STORAGE_MANIFEST_FILE:
            continue
        content = blob_get_bytes(str(blob.get("url") or pathname))
        if content is None:
            continue
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


def list_labor_metadata_from_blob() -> list[dict[str, Any]]:
    if not labor_blob_storage_enabled():
        return []
    rows: list[dict[str, Any]] = []
    for blob in _latest_blob_entries(blob_list_prefix(f"{RUN_PREFIX}/{labor_blob_environment()}/")):
        pathname = str(blob.get("pathname") or "")
        if not pathname.endswith("/metadata.json"):
            continue
        content = blob_get_bytes(pathname)
        if not content:
            continue
        try:
            rows.append(json.loads(content.decode("utf-8")))
        except json.JSONDecodeError:
            continue
    return sorted(rows, key=lambda row: row.get("updatedAt") or row.get("createdAt") or "", reverse=True)
