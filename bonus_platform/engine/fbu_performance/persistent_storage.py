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
from uuid import uuid4
from http.client import RemoteDisconnected
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from . import postgres_state


FBU_RUN_PREFIX = "fbu-performance-runs"
FBU_RUN_SCHEMA_VERSION = 2
FBU_RUN_INDEX_FILENAME = "_runs-index.json"
FBU_RUN_INDEX_ENTRY_PREFIX = "_run-index"
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
_ATTENDANCE_RECOVERY_SECTION_FIELDS = frozenset({
    "attendance_data",
    "attendance_view_data",
    "hourly_rate_policy_data",
})
_STALE_MANIFEST_RECOVERY_SECTION_FIELDS = frozenset({
    "base_override_data",
    "previous_salary_data",
    "current_salary_data",
    "adjustment_data",
    "salary_verification_data",
    "salary_data",
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


def _download_json(
    object_path: str,
    *,
    refresh: bool = False,
    cache_version: str = "",
) -> Any:
    cache_path = (
        f"{object_path}#version={cache_version}"
        if cache_version
        else object_path
    )
    if refresh:
        _invalidate_fbu_json_cache_prefix(object_path)
    cached = _get_cached_json(cache_path)
    if cached is not None:
        return cached
    content = _download_bytes(object_path)
    if content is None:
        return None
    if content.startswith(b"\x1f\x8b"):
        content = gzip.decompress(content)
    payload = json.loads(content.decode("utf-8"))
    _cache_json(cache_path, payload, len(content))
    return payload


def _run_index_object_path() -> str:
    return f"{_environment_prefix()}/{FBU_RUN_INDEX_FILENAME}"


def _run_index_entry_object_path(run_id: str) -> str:
    return f"{_environment_prefix()}/{FBU_RUN_INDEX_ENTRY_PREFIX}/{_safe_run_id(run_id)}.json"


def _section_relative_path(field: str) -> str:
    if field not in FBU_RUN_SECTION_FIELDS:
        raise ValueError(f"FBU 活动区块名称无效：{field}")
    return f"sections/{field}.json"


def _mutation_relative_path() -> str:
    return f"mutations/{time.time_ns():020d}-{uuid4().hex}.json"


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


def _section_manifest(
    field: str,
    value: Any,
    *,
    updated_at: str | None = None,
) -> dict[str, Any]:
    present = bool(value)
    return {
        "path": _section_relative_path(field),
        "present": present,
        "count": _section_count(value),
        "bytes": len(_json_bytes(value)) if present else 0,
        "summary": _bounded_summary(value),
        "updatedAt": updated_at or datetime.now().isoformat(),
    }


def build_fbu_run_manifest(
    payload: dict[str, Any],
    *,
    previous: dict[str, Any] | None = None,
    changed_fields: set[str] | None = None,
) -> dict[str, Any]:
    previous_run = dict((previous or {}).get("run") or {})
    previous_run.pop("roster_data", None)
    previous_sections = dict((previous or {}).get("sections") or {})
    core_updates = {
        key: value
        for key, value in payload.items()
        if key not in FBU_RUN_SECTION_FIELDS and key != "roster_data"
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


def _load_fbu_run_manifest(
    run_id: str,
    *,
    refresh: bool = False,
) -> dict[str, Any] | None:
    payload = _download_json(
        _object_path(run_id, "summary.json"),
        refresh=refresh,
    )
    if not isinstance(payload, dict) or not isinstance(payload.get("run"), dict):
        return None
    return payload


def _load_fbu_run_mutations(
    run_id: str,
    *,
    refresh: bool = False,
    exclude: set[str] | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    prefix = _object_path(run_id, "mutations")
    try:
        entries = _list_objects(prefix)
    except (
        FBUStorageStatusError,
        URLError,
        TimeoutError,
        RemoteDisconnected,
        ConnectionError,
        OSError,
        RuntimeError,
    ):
        return []

    mutation_names = []
    for entry in entries:
        name = str(entry.get("name") or "").strip()
        if not re.fullmatch(r"[0-9A-Za-z_-]+\.json", name):
            continue
        if exclude and name in exclude:
            continue
        mutation_names.append(name)

    def load_mutation(name: str) -> tuple[str, dict[str, Any] | None]:
        mutation = _download_json(f"{prefix}/{name}", refresh=refresh)
        return name, mutation if isinstance(mutation, dict) else None

    if len(mutation_names) <= 1:
        loaded = [load_mutation(name) for name in mutation_names]
    else:
        with ThreadPoolExecutor(max_workers=min(8, len(mutation_names))) as executor:
            loaded = list(executor.map(load_mutation, mutation_names))
    mutations = [
        (name, mutation)
        for name, mutation in loaded
        if mutation is not None
    ]
    mutations.sort(
        key=lambda item: (
            str(item[1].get("createdAt") or ""),
            item[0],
        )
    )
    return mutations


def _merge_fbu_run_mutations(
    run_id: str,
    manifest: dict[str, Any] | None,
    *,
    refresh: bool = False,
) -> dict[str, Any] | None:
    applied = {
        str(name)
        for name in ((manifest or {}).get("appliedMutations") or [])
        if isinstance(name, str)
    }
    mutations = _load_fbu_run_mutations(
        run_id,
        refresh=refresh,
        exclude=applied,
    )
    if not mutations:
        return manifest

    merged = copy.deepcopy(manifest) if manifest else {
        "schemaVersion": FBU_RUN_SCHEMA_VERSION,
        "updatedAt": "",
        "run": {"run_id": run_id},
        "sections": {},
    }
    run = merged.setdefault("run", {})
    sections = merged.setdefault("sections", {})
    for name, mutation in mutations:
        mutation_run = mutation.get("run")
        mutation_sections = mutation.get("sections")
        if isinstance(mutation_run, dict):
            run.update(mutation_run)
        if isinstance(mutation_sections, dict):
            sections.update(mutation_sections)
        mutation_time = str(mutation.get("createdAt") or "")
        if mutation_time > str(merged.get("updatedAt") or ""):
            merged["updatedAt"] = mutation_time
        applied.add(name)
    merged["appliedMutations"] = sorted(applied)
    return merged


def _save_fbu_run_mutation(
    run_id: str,
    payload: dict[str, Any],
    *,
    changed_fields: set[str] | None,
    section_values: dict[str, Any],
) -> None:
    if changed_fields is None:
        core_fields = {
            key
            for key in payload
            if key not in FBU_RUN_SECTION_FIELDS and key != "roster_data"
        }
    else:
        core_fields = {
            key
            for key in changed_fields
            if key in payload
            and key not in FBU_RUN_SECTION_FIELDS
            and key != "roster_data"
        }
    created_at = datetime.now().isoformat()
    mutation = {
        "schemaVersion": FBU_RUN_SCHEMA_VERSION,
        "createdAt": created_at,
        "run": {key: payload[key] for key in sorted(core_fields)},
        "sections": {
            field: _section_manifest(field, value, updated_at=created_at)
            for field, value in sorted(section_values.items())
        },
    }
    _upload_json(
        _object_path(run_id, _mutation_relative_path()),
        mutation,
    )


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
    database_states = postgres_state.list_run_states()
    database_core_by_id = {
        str(row.get("run_id") or ""): row
        for row in (database_states or [])
        if str(row.get("run_id") or "")
    }
    indexed = _load_fbu_run_index()
    if database_states is not None:
        per_run_entries = []
    else:
        try:
            per_run_entries = _list_objects(
                f"{_environment_prefix()}/{FBU_RUN_INDEX_ENTRY_PREFIX}"
            )
        except RuntimeError:
            per_run_entries = []
    entry_ids = [
        str(entry.get("name") or "")[:-5]
        for entry in per_run_entries
        if str(entry.get("name") or "").endswith(".json")
    ]
    if entry_ids:
        with ThreadPoolExecutor(max_workers=min(8, len(entry_ids))) as executor:
            per_run_rows = list(executor.map(
                lambda entry_id: _download_json(_run_index_entry_object_path(entry_id)),
                entry_ids,
            ))
        per_run_by_id = {
            str((row.get("run") or {}).get("run_id") or ""): row
            for row in per_run_rows
            if isinstance(row, dict) and isinstance(row.get("run"), dict)
        }
    else:
        per_run_by_id = {}
    if indexed is not None:
        by_id = {
            str((row.get("run") or {}).get("run_id") or ""): row
            for row in indexed
        }
        by_id.update(per_run_by_id)
        by_id.update({
            run_id: build_fbu_run_manifest(core, previous=by_id.get(run_id))
            for run_id, core in database_core_by_id.items()
        })
        return sorted(
            by_id.values(),
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
    by_id = {
        str((row.get("run") or {}).get("run_id") or ""): row
        for row in rows
    }
    by_id.update(per_run_by_id)
    by_id.update({
        run_id: build_fbu_run_manifest(core, previous=by_id.get(run_id))
        for run_id, core in database_core_by_id.items()
    })
    return sorted(
        by_id.values(),
        key=lambda row: str((row.get("run") or {}).get("created_at") or ""),
        reverse=True,
    )


def _upsert_fbu_run_index(manifest: dict[str, Any]) -> None:
    run_id = str((manifest.get("run") or {}).get("run_id") or "")
    if not run_id:
        raise ValueError("FBU 活动摘要缺少活动编号")
    # This per-run object is the concurrency-safe canonical Storage index. The
    # aggregate file below remains a compatibility cache for older deployments.
    _upload_json(_run_index_entry_object_path(run_id), manifest)
    with _RUN_INDEX_LOCK:
        rows = list_fbu_run_summaries_from_persistent()
        by_id = {
            str((row.get("run") or {}).get("run_id") or ""): row
            for row in rows
        }
        by_id[run_id] = manifest
        _save_fbu_run_index(list(by_id.values()))


def _remove_fbu_run_from_index(run_id: str) -> None:
    _request(
        "DELETE",
        _storage_url(f"object/{fbu_supabase_bucket()}"),
        headers=_headers({"content-type": "application/json"}),
        content=json.dumps({"prefixes": [_run_index_entry_object_path(run_id)]}).encode("utf-8"),
    )
    _invalidate_fbu_json_cache_prefix(_run_index_entry_object_path(run_id))
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
    base_sections: dict[str, Any] | None = None,
    section_revisions: dict[str, int] | None = None,
    replace_sections: set[str] | None = None,
    base_core: dict[str, Any] | None = None,
    core_revision: int = 0,
) -> dict[str, Any]:
    database_manifest = _save_fbu_run_snapshot_to_postgres(
        run_id,
        payload,
        changed_fields=changed_fields,
        base_sections=base_sections,
        section_revisions=section_revisions,
        replace_sections=replace_sections,
        base_core=base_core,
        core_revision=core_revision,
    )
    if database_manifest:
        payload = {
            **payload,
            **dict(database_manifest.get("effectiveSections") or {}),
        }
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

    section_values = {
        field: payload.get(field) if field in payload else (legacy or {}).get(field)
        for field in section_fields
    }

    def upload_section(field: str) -> None:
        value = section_values[field]
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
    _save_fbu_run_mutation(
        run_id,
        payload,
        changed_fields=changed_fields,
        section_values=section_values,
    )
    latest = previous
    if changed_fields is not None:
        latest = _merge_fbu_run_mutations(
            run_id,
            _load_fbu_run_manifest(run_id, refresh=True) or previous,
            refresh=True,
        ) or previous
    manifest_payload = payload
    if changed_fields is not None and latest is not None:
        manifest_payload = {
            key: value
            for key, value in payload.items()
            if key in changed_fields
        }
    manifest = build_fbu_run_manifest(
        manifest_payload,
        previous=latest,
        changed_fields=changed_fields,
    )
    _upload_json(_object_path(run_id, "summary.json"), manifest)
    _upsert_fbu_run_index(manifest)
    return database_manifest or manifest


def _save_fbu_run_snapshot_to_postgres(
    run_id: str,
    payload: dict[str, Any],
    *,
    changed_fields: set[str] | None,
    base_sections: dict[str, Any] | None,
    section_revisions: dict[str, int] | None,
    replace_sections: set[str] | None,
    base_core: dict[str, Any] | None,
    core_revision: int,
) -> dict[str, Any] | None:
    if not postgres_state.fbu_postgres_state_requested():
        return None
    all_core = {
        key: value
        for key, value in payload.items()
        if key not in FBU_RUN_SECTION_FIELDS
        and key not in {"roster_data", "__core_revision", "__section_revisions"}
    }
    if changed_fields is None:
        section_fields = {
            field
            for field in FBU_RUN_SECTION_FIELDS
            if field in payload and bool(payload.get(field))
        }
    else:
        section_fields = set(changed_fields).intersection(FBU_RUN_SECTION_FIELDS)
    revisions = dict(section_revisions or {})
    snapshot_result = postgres_state.save_snapshot_with_retry(
        run_id,
        base_core=dict(base_core or all_core),
        desired_core=all_core,
        expected_core_revision=int(core_revision or 0),
        sections={
            field: {
                "base": (base_sections or {}).get(
                    field,
                    payload.get(field, [] if field == "results" else {}),
                ),
                "desired": payload.get(field, [] if field == "results" else {}),
                "expected_revision": int(revisions.get(field) or 0),
                "replace": changed_fields is None or field in set(replace_sections or ()),
            }
            for field in sorted(section_fields)
        },
    )
    if snapshot_result is None:
        return None
    section_results = dict(snapshot_result.get("sections") or {})
    effective_sections = {
        field: dict(section_results.get(field) or {}).get("data")
        for field in section_fields
    }
    revisions.update({
        field: int(dict(section_results.get(field) or {}).get("revision") or 0)
        for field in section_fields
    })

    core = dict(snapshot_result.get("data") or all_core)
    manifest = build_fbu_run_manifest(core)
    now = datetime.now().isoformat()
    manifest["sections"] = {
        **dict(manifest.get("sections") or {}),
        **{
            field: {
                **_section_manifest(field, value, updated_at=now),
                "revision": revisions[field],
            }
            for field, value in effective_sections.items()
        },
    }
    manifest["sectionRevisions"] = revisions
    manifest["coreRevision"] = int(snapshot_result.get("revision") or 0)
    manifest["effectiveSections"] = effective_sections
    return manifest


def load_fbu_run_snapshot_from_persistent(
    run_id: str,
    *,
    sections: set[str] | None = None,
    refresh: bool = False,
) -> dict[str, Any] | None:
    requested = (
        set(FBU_RUN_SECTION_FIELDS)
        if sections is None
        else set(sections).intersection(FBU_RUN_SECTION_FIELDS)
    )
    database_payload = postgres_state.load_run_state(run_id, requested)
    if database_payload:
        revisions = dict(database_payload.get("__section_revisions") or {})
        missing = {field for field in requested if not int(revisions.get(field) or 0)}
        if missing:
            legacy = _load_fbu_run_snapshot_from_storage(
                run_id,
                sections=missing,
                refresh=refresh,
            )
            for field in missing:
                value = (legacy or {}).get(field)
                if not value:
                    continue
                result = postgres_state.replace_section(run_id, field, value)
                if result:
                    database_payload[field] = result.get("data")
                    revisions[field] = int(result.get("revision") or 0)
            database_payload["__section_revisions"] = revisions
        return database_payload
    legacy = _load_fbu_run_snapshot_from_storage(
        run_id,
        sections=sections,
        refresh=refresh,
    )
    if legacy and database_payload == {}:
        _save_fbu_run_snapshot_to_postgres(
            run_id,
            legacy,
            changed_fields=None,
            base_sections=None,
            section_revisions=None,
            replace_sections=requested,
            base_core=None,
            core_revision=0,
        )
    return legacy


def _load_fbu_run_snapshot_from_storage(
    run_id: str,
    *,
    sections: set[str] | None = None,
    refresh: bool = False,
) -> dict[str, Any] | None:
    requested = (
        set(FBU_RUN_SECTION_FIELDS)
        if sections is None
        else set(sections).intersection(FBU_RUN_SECTION_FIELDS)
    )
    manifest = _merge_fbu_run_mutations(
        run_id,
        _load_fbu_run_manifest(run_id, refresh=refresh),
        refresh=refresh,
    )
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
    def load_section(field: str) -> tuple[str, Any]:
        section = (manifest.get("sections") or {}).get(field) or {}
        recovery_expected = (
            field in _STALE_MANIFEST_RECOVERY_SECTION_FIELDS
            or (
                field in _ATTENDANCE_RECOVERY_SECTION_FIELDS
                and bool((manifest.get("run") or {}).get("attendance_file"))
            )
        )
        if not section.get("present") and not recovery_expected:
            return field, [] if field == "results" else {}
        value = _download_json(
            _object_path(run_id, _section_relative_path(field)),
            refresh=refresh,
            cache_version=str(section.get("updatedAt") or ""),
        )
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


def copy_fbu_file_in_persistent(
    run_id: str,
    source_relative_path: str,
    destination_relative_path: str,
) -> None:
    """Promote an already uploaded object without downloading and uploading it again."""
    source_path = _object_path(run_id, source_relative_path)
    destination_path = _object_path(run_id, destination_relative_path)
    if source_path == destination_path:
        return
    _request(
        "POST",
        _storage_url("object/copy"),
        headers=_headers({"content-type": "application/json"}),
        content=json.dumps({
            "bucketId": fbu_supabase_bucket(),
            "sourceKey": source_path,
            "destinationKey": destination_path,
        }).encode("utf-8"),
    )
    _invalidate_fbu_json_cache_prefix(destination_path)


def read_fbu_file_from_persistent(run_id: str, relative_path: str) -> bytes | None:
    normalized = _normalize_relative_path(relative_path)
    return _download_bytes(_object_path(run_id, normalized))


def load_fbu_file_from_persistent(run_id: str, run_dir: Path, relative_path: str) -> Path | None:
    normalized = _normalize_relative_path(relative_path)
    target = run_dir / normalized
    content = read_fbu_file_from_persistent(run_id, normalized)
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
    postgres_state.delete_run(run_id)
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
