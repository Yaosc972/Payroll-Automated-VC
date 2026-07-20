from __future__ import annotations

import gzip
import json
import mimetypes
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from http.client import RemoteDisconnected
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


FBU_RUN_PREFIX = "fbu-performance-runs"


class FBUStorageStatusError(RuntimeError):
    def __init__(self, status_code: int, text: str):
        super().__init__(f"Supabase Storage returned HTTP {status_code}")
        self.status_code = status_code
        self.text = text


def fbu_storage_backend() -> str:
    return (
        os.environ.get("SIGMA_FBU_STORAGE_BACKEND")
        or os.environ.get("SIGMA_LABOR_STORAGE_BACKEND")
        or ""
    ).strip().lower()


def fbu_persistent_storage_enabled() -> bool:
    return bool(
        fbu_storage_backend() == "supabase"
        and _supabase_url()
        and _supabase_token()
        and fbu_supabase_bucket()
    )


def fbu_persistent_environment() -> str:
    raw = (
        os.environ.get("SIGMA_FBU_STORAGE_ENV")
        or os.environ.get("SIGMA_LABOR_STORAGE_ENV")
        or os.environ.get("VERCEL_ENV")
        or "local"
    )
    value = re.sub(r"[^0-9A-Za-z_-]+", "-", raw.strip().lower()).strip("-_")
    return value or "local"


def fbu_supabase_bucket() -> str:
    return (
        os.environ.get("SIGMA_FBU_SUPABASE_BUCKET")
        or os.environ.get("SIGMA_LABOR_SUPABASE_BUCKET")
        or os.environ.get("SUPABASE_STORAGE_BUCKET")
        or "sigma-labor-runs"
    ).strip()


def save_fbu_run_metadata_to_persistent(run_id: str, payload: dict[str, Any]) -> None:
    content = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    _upload_bytes(
        _object_path(run_id, "metadata.json"),
        gzip.compress(content, compresslevel=6),
        content_type="application/gzip",
    )


def load_fbu_run_metadata_from_persistent(run_id: str) -> dict[str, Any] | None:
    content = _download_bytes(_object_path(run_id, "metadata.json"))
    if content is None:
        return None
    if content.startswith(b"\x1f\x8b"):
        content = gzip.decompress(content)
    payload = json.loads(content.decode("utf-8"))
    return payload if isinstance(payload, dict) else None


def list_fbu_run_metadata_from_persistent() -> list[dict[str, Any]]:
    prefix = _environment_prefix()
    rows: list[dict[str, Any]] = []
    for entry in _list_objects(prefix):
        run_id = str(entry.get("name") or "").strip()
        if not re.fullmatch(r"[0-9A-Za-z_-]+", run_id) or run_id.startswith("_"):
            continue
        payload = load_fbu_run_metadata_from_persistent(run_id)
        if payload:
            rows.append(payload)
    return sorted(rows, key=lambda row: str(row.get("created_at") or ""), reverse=True)


def save_fbu_files_to_persistent(run_id: str, run_dir: Path, relative_paths: Iterable[str]) -> None:
    uploads: list[tuple[str, bytes, str]] = []
    for relative_path in _normalized_paths(relative_paths):
        path = run_dir / relative_path
        if not path.is_file() or path.name.startswith("."):
            continue
        content_type, _ = mimetypes.guess_type(path.name)
        uploads.append((relative_path, path.read_bytes(), content_type or "application/octet-stream"))

    def upload(item: tuple[str, bytes, str]) -> None:
        relative_path, content, content_type = item
        _upload_bytes(
            _object_path(run_id, relative_path),
            content,
            content_type=content_type,
        )

    if len(uploads) <= 1:
        for item in uploads:
            upload(item)
        return

    with ThreadPoolExecutor(max_workers=min(4, len(uploads))) as executor:
        list(executor.map(upload, uploads))


def load_fbu_file_from_persistent(run_id: str, run_dir: Path, relative_path: str) -> Path | None:
    normalized = _normalize_relative_path(relative_path)
    target = run_dir / normalized
    content = _download_bytes(_object_path(run_id, normalized))
    if content is None:
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return target


def create_fbu_signed_upload(run_id: str, relative_path: str) -> dict[str, Any]:
    normalized = _normalize_relative_path(relative_path)
    object_path = _object_path(run_id, normalized)
    body = _request(
        "POST",
        _storage_url(
            f"object/upload/sign/{fbu_supabase_bucket()}/{_quoted_path(object_path)}"
        ),
        headers=_headers({"content-type": "application/json", "x-upsert": "true"}),
        content=b"{}",
    )
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError("Supabase Storage 签名上传地址返回内容异常。") from exc
    signed_path = str(
        payload.get("url") or payload.get("signedURL") or payload.get("signedUrl") or ""
    ).strip()
    if not signed_path:
        raise RuntimeError("Supabase Storage 未返回签名上传地址。")
    if signed_path.startswith(("http://", "https://")):
        signed_url = signed_path
    elif signed_path.startswith("/storage/v1/"):
        signed_url = f"{_supabase_url()}{signed_path}"
    else:
        signed_url = _storage_url(signed_path)
    return {
        "signedUrl": signed_url,
        "objectPath": object_path,
        "relativePath": normalized,
    }


def delete_fbu_files_from_persistent(run_id: str, relative_paths: Iterable[str]) -> None:
    object_paths = [
        _object_path(run_id, relative_path)
        for relative_path in _normalized_paths(relative_paths)
    ]
    if not object_paths:
        return
    _request(
        "DELETE",
        _storage_url(f"object/{fbu_supabase_bucket()}"),
        headers=_headers({"content-type": "application/json"}),
        content=json.dumps({"prefixes": object_paths}).encode("utf-8"),
    )


def delete_fbu_run_from_persistent(run_id: str) -> None:
    prefix = f"{_environment_prefix()}/{_safe_run_id(run_id)}"
    object_paths = [f"{prefix}/{entry['name']}" for entry in _list_objects(prefix) if entry.get("name")]
    if not object_paths:
        return
    url = _storage_url(f"object/{fbu_supabase_bucket()}")
    _request(
        "DELETE",
        url,
        headers=_headers({"content-type": "application/json"}),
        content=json.dumps({"prefixes": object_paths}).encode("utf-8"),
    )


def _normalized_paths(relative_paths: Iterable[str]) -> list[str]:
    return sorted({_normalize_relative_path(path) for path in relative_paths if str(path).strip()})


def _normalize_relative_path(relative_path: str) -> str:
    normalized = str(relative_path).replace("\\", "/").strip().lstrip("/")
    parts = [part for part in normalized.split("/") if part not in {"", "."}]
    if not parts or any(part == ".." for part in parts):
        raise ValueError("FBU 持久化文件路径无效")
    return "/".join(parts)


def _safe_run_id(run_id: str) -> str:
    value = str(run_id).strip()
    if not re.fullmatch(r"[0-9A-Za-z_-]+", value):
        raise ValueError("FBU 活动编号无效")
    return value


def _environment_prefix() -> str:
    return f"{FBU_RUN_PREFIX}/{fbu_persistent_environment()}"


def _object_path(run_id: str, relative_path: str) -> str:
    return f"{_environment_prefix()}/{_safe_run_id(run_id)}/{_normalize_relative_path(relative_path)}"


def _supabase_url() -> str:
    return (os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL") or "").strip().rstrip("/")


def _supabase_token() -> str:
    return (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_STORAGE_SERVICE_ROLE_KEY")
        or ""
    ).strip()


def _headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    token = _supabase_token()
    if not token:
        raise RuntimeError("缺少 SUPABASE_SERVICE_ROLE_KEY，无法持久化 FBU 活动。")
    headers = {"apikey": token, "authorization": f"Bearer {token}"}
    if extra:
        headers.update(extra)
    return headers


def _storage_url(path: str) -> str:
    base = _supabase_url()
    if not base:
        raise RuntimeError("缺少 SUPABASE_URL，无法持久化 FBU 活动。")
    return f"{base}/storage/v1/{path.lstrip('/')}"


def _quoted_path(path: str) -> str:
    return quote(path.replace("\\", "/").lstrip("/"), safe="/")


def _request(method: str, url: str, *, headers: dict[str, str], content: bytes | None = None) -> bytes:
    for attempt in range(3):
        request = Request(url, data=content, headers=headers, method=method)
        try:
            with urlopen(request, timeout=120.0) as response:
                return response.read()
        except HTTPError as exc:
            raise FBUStorageStatusError(exc.code, exc.read().decode("utf-8", errors="replace")) from exc
        except (URLError, TimeoutError, RemoteDisconnected, ConnectionError, OSError):
            if attempt == 2:
                raise
            time.sleep(0.5 * (2**attempt))
    return b""


def _upload_bytes(object_path: str, content: bytes, *, content_type: str) -> None:
    url = _storage_url(f"object/{fbu_supabase_bucket()}/{_quoted_path(object_path)}")
    _request(
        "POST",
        url,
        headers=_headers({"content-type": content_type, "x-upsert": "true"}),
        content=content,
    )


def _download_bytes(object_path: str) -> bytes | None:
    url = _storage_url(f"object/{fbu_supabase_bucket()}/{_quoted_path(object_path)}")
    try:
        return _request("GET", url, headers=_headers())
    except FBUStorageStatusError as exc:
        if _storage_error_status(exc) == 404:
            return None
        raise


def _storage_error_status(exc: FBUStorageStatusError) -> int:
    try:
        payload = json.loads(exc.text)
    except (json.JSONDecodeError, TypeError):
        return exc.status_code
    if not isinstance(payload, dict):
        return exc.status_code
    try:
        return int(payload.get("statusCode"))
    except (TypeError, ValueError):
        return exc.status_code


def _list_objects(prefix: str) -> list[dict[str, Any]]:
    url = _storage_url(f"object/list/{fbu_supabase_bucket()}")
    payload = {"prefix": prefix.rstrip("/"), "limit": 1000, "offset": 0}
    body = _request(
        "POST",
        url,
        headers=_headers({"content-type": "application/json"}),
        content=json.dumps(payload).encode("utf-8"),
    )
    rows = json.loads(body.decode("utf-8")) if body else []
    return rows if isinstance(rows, list) else []
