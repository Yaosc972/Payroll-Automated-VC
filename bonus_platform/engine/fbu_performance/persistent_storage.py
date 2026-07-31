from __future__ import annotations

import gzip
from collections import OrderedDict
import copy
from datetime import datetime
import json
import mimetypes
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.client import RemoteDisconnected
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


FBU_RUN_PREFIX = "fbu-performance-runs"
FBU_RUN_SCHEMA_VERSION = 2
FBU_RUN_INDEX_FILENAME = "_runs-index.json"
FBU_RUN_SECTION_FIELDS = frozenset({
    "attendance_data",
    "attendance_view_data",
    "salary_data",
    "previous_salary_data",
    "current_salary_data",
    "salary_verification_data",
    "performance_data",
    "adjustment_data",
    "transfer_data",
    "supplemental_leave_data",
    "base_override_data",
    "hourly_rate_policy_data",
    "period_adjustment_data",
    "results",
    "results_view_data",
})
_RUN_INDEX_LOCK = threading.RLock()
_JSON_CACHE_LOCK = threading.RLock()
_JSON_CACHE_MAX_ITEM_BYTES = 2 * 1024 * 1024
_JSON_CACHE_MAX_TOTAL_BYTES = 16 * 1024 * 1024
_JSON_CACHE: OrderedDict[str, tuple[float, int, Any]] = OrderedDict()
_JSON_CACHE_TOTAL_BYTES = 0


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


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _fbu_json_cache_ttl_seconds() -> float:
    raw = os.environ.get("SIGMA_FBU_JSON_CACHE_TTL_SECONDS", "2")
    try:
        return min(30.0, max(0.0, float(raw)))
    except (TypeError, ValueError):
        return 2.0


def _clear_fbu_json_cache() -> None:
    global _JSON_CACHE_TOTAL_BYTES
    with _JSON_CACHE_LOCK:
        _JSON_CACHE.clear()
        _JSON_CACHE_TOTAL_BYTES = 0


def _invalidate_fbu_json_cache_prefix(prefix: str) -> None:
    global _JSON_CACHE_TOTAL_BYTES
    with _JSON_CACHE_LOCK:
        for key in [key for key in _JSON_CACHE if key.startswith(prefix)]:
            _, size, _ = _JSON_CACHE.pop(key)
            _JSON_CACHE_TOTAL_BYTES -= size


def _get_cached_json(object_path: str) -> Any | None:
    global _JSON_CACHE_TOTAL_BYTES
    now = time.monotonic()
    with _JSON_CACHE_LOCK:
        cached = _JSON_CACHE.get(object_path)
        if cached is None:
            return None
        expires_at, size, payload = cached
        if expires_at <= now:
            _JSON_CACHE.pop(object_path, None)
            _JSON_CACHE_TOTAL_BYTES -= size
            return None
        _JSON_CACHE.move_to_end(object_path)
        return copy.deepcopy(payload)


def _cache_json(object_path: str, payload: Any, encoded_size: int) -> None:
    global _JSON_CACHE_TOTAL_BYTES
    ttl_seconds = _fbu_json_cache_ttl_seconds()
    if ttl_seconds <= 0 or encoded_size > _JSON_CACHE_MAX_ITEM_BYTES:
        _invalidate_fbu_json_cache_prefix(object_path)
        return
    with _JSON_CACHE_LOCK:
        previous = _JSON_CACHE.pop(object_path, None)
        if previous:
            _JSON_CACHE_TOTAL_BYTES -= previous[1]
        _JSON_CACHE[object_path] = (
            time.monotonic() + ttl_seconds,
            encoded_size,
            copy.deepcopy(payload),
        )
        _JSON_CACHE_TOTAL_BYTES += encoded_size
        while _JSON_CACHE_TOTAL_BYTES > _JSON_CACHE_MAX_TOTAL_BYTES and _JSON_CACHE:
            _, (_, size, _) = _JSON_CACHE.popitem(last=False)
            _JSON_CACHE_TOTAL_BYTES -= size


def _upload_json(object_path: str, payload: Any) -> None:
    content = _json_bytes(payload)
    _upload_bytes(object_path, content, content_type="application/json")
    _cache_json(object_path, payload, len(content))


def _download_json(object_path: str) -> Any:
    cached = _get_cached_json(object_path)
    if cached is not None:
        return cached
    content = _download_bytes(object_path)
    if content is None:
        return None
    if content.startswith(b"\x1f\x8b"):
        content = gzip.decompress(content)
    payload = json.loads(content.decode("utf-8"))
    _cache_json(object_path, payload, len(content))
    return payload


def _run_index_object_path() -> str:
    return f"{_environment_prefix()}/{FBU_RUN_INDEX_FILENAME}"


def _section_relative_path(field: str) -> str:
    if field not in FBU_RUN_SECTION_FIELDS:
        raise ValueError(f"FBU 活动区块名称无效：{field}")
    return f"sections/{field}.json"


def _section_count(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if not isinstance(value, dict):
        return 0
    for key in ("employees", "rows", "events", "results", "items"):
        rows = value.get(key)
        if isinstance(rows, list):
            return len(rows)
    return 0


def _bounded_summary(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    summary = value.get("summary")
    if not isinstance(summary, dict):
        return {}

    def compact(item: Any, depth: int = 0) -> Any:
        if depth >= 2:
            return None
        if isinstance(item, (str, int, float, bool)) or item is None:
            return item
        if isinstance(item, dict):
            return {
                str(key): normalized
                for key, raw in list(item.items())[:60]
                if (normalized := compact(raw, depth + 1)) is not None
            }
        if isinstance(item, list) and len(item) <= 20:
            normalized_rows = [compact(raw, depth + 1) for raw in item]
            return [raw for raw in normalized_rows if raw is not None]
        return None

    normalized = compact(summary)
    if not isinstance(normalized, dict):
        return {}
    encoded = _json_bytes(normalized)
    if len(encoded) <= 16_384:
        return normalized
    return {
        key: raw
        for key, raw in normalized.items()
        if isinstance(raw, (str, int, float, bool)) or raw is None
    }


def _section_manifest(field: str, value: Any) -> dict[str, Any]:
    present = bool(value)
    return {
        "path": _section_relative_path(field),
        "present": present,
        "count": _section_count(value),
        "bytes": len(_json_bytes(value)) if present else 0,
        "summary": _bounded_summary(value),
    }


def build_fbu_run_manifest(
    payload: dict[str, Any],
    *,
    previous: dict[str, Any] | None = None,
    changed_fields: set[str] | None = None,
) -> dict[str, Any]:
    previous_run = dict((previous or {}).get("run") or {})
    previous_sections = dict((previous or {}).get("sections") or {})
    core_updates = {
        key: value
        for key, value in payload.items()
        if key not in FBU_RUN_SECTION_FIELDS
    }
    previous_run.update(core_updates)

    if changed_fields is None:
        section_fields = {
            field
            for field in FBU_RUN_SECTION_FIELDS
            if field in payload
        }
    else:
        section_fields = set(changed_fields).intersection(FBU_RUN_SECTION_FIELDS)
    for field in section_fields:
        previous_sections[field] = _section_manifest(field, payload.get(field))

    return {
        "schemaVersion": FBU_RUN_SCHEMA_VERSION,
        "updatedAt": datetime.now().isoformat(),
        "run": previous_run,
        "sections": previous_sections,
    }


def _load_fbu_run_manifest(run_id: str) -> dict[str, Any] | None:
    payload = _download_json(_object_path(run_id, "summary.json"))
    if not isinstance(payload, dict) or not isinstance(payload.get("run"), dict):
        return None
    return payload


def _load_fbu_run_index() -> list[dict[str, Any]] | None:
    payload = _download_json(_run_index_object_path())
    if payload is None:
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("runs"), list):
        return []
    return [
        row
        for row in payload["runs"]
        if isinstance(row, dict) and isinstance(row.get("run"), dict)
    ]


def _save_fbu_run_index(rows: list[dict[str, Any]]) -> None:
    ordered = sorted(
        rows,
        key=lambda row: str((row.get("run") or {}).get("created_at") or ""),
        reverse=True,
    )
    _upload_json(
        _run_index_object_path(),
        {
            "schemaVersion": FBU_RUN_SCHEMA_VERSION,
            "updatedAt": datetime.now().isoformat(),
            "runs": ordered,
        },
    )


def _load_legacy_fbu_run_metadata(run_id: str) -> dict[str, Any] | None:
    payload = _download_json(_object_path(run_id, "metadata.json"))
    return payload if isinstance(payload, dict) else None


def list_fbu_run_summaries_from_persistent() -> list[dict[str, Any]]:
    indexed = _load_fbu_run_index()
    if indexed is not None:
        return sorted(
            indexed,
            key=lambda row: str((row.get("run") or {}).get("created_at") or ""),
            reverse=True,
        )

    prefix = _environment_prefix()
    rows: list[dict[str, Any]] = []
    for entry in _list_objects(prefix):
        run_id = str(entry.get("name") or "").strip()
        if not re.fullmatch(r"[0-9A-Za-z_-]+", run_id) or run_id.startswith("_"):
            continue
        manifest = _load_fbu_run_manifest(run_id)
        if not manifest:
            legacy = _load_legacy_fbu_run_metadata(run_id)
            if legacy:
                manifest = build_fbu_run_manifest(legacy)
        if manifest:
            rows.append(manifest)
    if rows:
        _save_fbu_run_index(rows)
    return sorted(
        rows,
        key=lambda row: str((row.get("run") or {}).get("created_at") or ""),
        reverse=True,
    )


def _upsert_fbu_run_index(manifest: dict[str, Any]) -> None:
    run_id = str((manifest.get("run") or {}).get("run_id") or "")
    if not run_id:
        raise ValueError("FBU 活动摘要缺少活动编号")
    with _RUN_INDEX_LOCK:
        rows = list_fbu_run_summaries_from_persistent()
        by_id = {
            str((row.get("run") or {}).get("run_id") or ""): row
            for row in rows
        }
        by_id[run_id] = manifest
        _save_fbu_run_index(list(by_id.values()))


def _remove_fbu_run_from_index(run_id: str) -> None:
    with _RUN_INDEX_LOCK:
        rows = _load_fbu_run_index()
        if rows is None:
            return
        filtered = [
            row
            for row in rows
            if str((row.get("run") or {}).get("run_id") or "") != run_id
        ]
        _save_fbu_run_index(filtered)


def save_fbu_run_snapshot_to_persistent(
    run_id: str,
    payload: dict[str, Any],
    *,
    changed_fields: set[str] | None = None,
) -> dict[str, Any]:
    previous = _load_fbu_run_manifest(run_id)
    legacy: dict[str, Any] | None = None
    migration_fields: set[str] = set()
    if previous is None:
        legacy = _load_legacy_fbu_run_metadata(run_id)
        if legacy:
            previous = build_fbu_run_manifest(legacy)
            migration_fields = {
                field
                for field in FBU_RUN_SECTION_FIELDS
                if field in legacy and bool(legacy.get(field))
            }
    manifest = build_fbu_run_manifest(
        payload,
        previous=previous,
        changed_fields=changed_fields,
    )
    if changed_fields is None:
        section_fields = {
            field
            for field in FBU_RUN_SECTION_FIELDS
            if field in payload
            and (
                bool(payload.get(field))
                or bool(((previous or {}).get("sections") or {}).get(field, {}).get("present"))
            )
        }
    else:
        section_fields = set(changed_fields).intersection(FBU_RUN_SECTION_FIELDS)
    section_fields.update(migration_fields)

    def upload_section(field: str) -> None:
        value = payload.get(field) if field in payload else (legacy or {}).get(field)
        _upload_json(
            _object_path(run_id, _section_relative_path(field)),
            value,
        )

    ordered_section_fields = sorted(section_fields)
    if len(ordered_section_fields) <= 1:
        for field in ordered_section_fields:
            upload_section(field)
    else:
        with ThreadPoolExecutor(
            max_workers=min(4, len(ordered_section_fields))
        ) as executor:
            list(executor.map(upload_section, ordered_section_fields))
    _upload_json(_object_path(run_id, "summary.json"), manifest)
    _upsert_fbu_run_index(manifest)
    return manifest


def load_fbu_run_snapshot_from_persistent(
    run_id: str,
    *,
    sections: set[str] | None = None,
) -> dict[str, Any] | None:
    manifest = _load_fbu_run_manifest(run_id)
    if not manifest:
        legacy = _load_legacy_fbu_run_metadata(run_id)
        if legacy is None:
            return None
        if sections is None:
            return legacy
        return {
            key: value
            for key, value in legacy.items()
            if key not in FBU_RUN_SECTION_FIELDS or key in sections
        }

    payload = dict(manifest["run"])
    requested = (
        set(FBU_RUN_SECTION_FIELDS)
        if sections is None
        else set(sections).intersection(FBU_RUN_SECTION_FIELDS)
    )

    def load_section(field: str) -> tuple[str, Any]:
        section = (manifest.get("sections") or {}).get(field) or {}
        if not section.get("present"):
            return field, [] if field == "results" else {}
        value = _download_json(_object_path(run_id, _section_relative_path(field)))
        if value is None:
            return field, [] if field == "results" else {}
        return field, value

    if len(requested) <= 1:
        loaded = [load_section(field) for field in sorted(requested)]
    else:
        with ThreadPoolExecutor(max_workers=min(8, len(requested))) as executor:
            loaded = list(executor.map(load_section, sorted(requested)))
    payload.update(dict(loaded))
    return payload


def save_fbu_run_metadata_to_persistent(run_id: str, payload: dict[str, Any]) -> None:
    """Compatibility wrapper for callers that still persist a complete run payload."""
    save_fbu_run_snapshot_to_persistent(run_id, payload)


def load_fbu_run_metadata_from_persistent(run_id: str) -> dict[str, Any] | None:
    """Compatibility wrapper that reconstructs the complete run payload."""
    return load_fbu_run_snapshot_from_persistent(run_id)


def list_fbu_run_metadata_from_persistent() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for manifest in list_fbu_run_summaries_from_persistent():
        run_id = str((manifest.get("run") or {}).get("run_id") or "")
        payload = load_fbu_run_snapshot_from_persistent(run_id)
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
    for object_path in object_paths:
        _invalidate_fbu_json_cache_prefix(object_path)


def delete_fbu_run_from_persistent(run_id: str) -> None:
    prefix = f"{_environment_prefix()}/{_safe_run_id(run_id)}"
    object_paths = [f"{prefix}/{entry['name']}" for entry in _list_objects(prefix) if entry.get("name")]
    if object_paths:
        url = _storage_url(f"object/{fbu_supabase_bucket()}")
        _request(
            "DELETE",
            url,
            headers=_headers({"content-type": "application/json"}),
            content=json.dumps({"prefixes": object_paths}).encode("utf-8"),
        )
    _invalidate_fbu_json_cache_prefix(f"{prefix}/")
    _remove_fbu_run_from_index(run_id)


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
