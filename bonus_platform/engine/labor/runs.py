from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List
from uuid import uuid4

from ...config import LABOR_RUNS_DIR
from .blob_storage import (
    canonicalize_labor_metadata_for_blob,
    materialize_labor_metadata_for_local,
)
from .persistent_storage import (
    labor_persistent_storage_enabled,
    labor_persistent_storage_info,
    list_labor_metadata_from_persistent,
    sync_labor_run_from_persistent,
    sync_labor_run_to_persistent,
)
from .state_postgres import (
    LaborStateNotFound,
    create_labor_run_state,
    labor_postgres_state_enabled,
    list_labor_run_states,
    load_labor_run_state,
    transition_labor_run_state,
)


METADATA_FILE = "metadata.json"
_WINDOWS_REPLACE_RETRY_DELAYS = (0.05, 0.1, 0.2, 0.4, 0.8)
_RUN_METADATA_LOCKS_GUARD = threading.Lock()
_RUN_METADATA_LOCKS: dict[str, threading.RLock] = {}


def _run_metadata_lock(run_id: str) -> threading.RLock:
    with _RUN_METADATA_LOCKS_GUARD:
        return _RUN_METADATA_LOCKS.setdefault(str(run_id), threading.RLock())


@contextmanager
def labor_run_metadata_lock(run_id: str):
    """Serialize local metadata transitions for one labor run."""

    with _run_metadata_lock(run_id):
        yield


def new_labor_run_id() -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return f"labor_{timestamp}_{uuid4().hex[:8]}"


def create_labor_run(metadata: Dict[str, Any]) -> Dict[str, Any]:
    run_id = new_labor_run_id()
    run_dir = get_labor_run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=False)
    payload = {
        "id": run_id,
        "status": "已创建",
        "files": {},
        **metadata,
        "businessReviewStatus": "pending",
        "manualReviewRequired": True,
        "directPaymentAllowed": False,
        "requiresHumanReview": True,
    }
    if labor_postgres_state_enabled():
        stored = create_labor_run_state(
            payload,
            actor_user_id=str(payload.get("ownerUserId") or ""),
        )
        return _cache_authoritative_labor_metadata(run_dir, stored)
    return save_labor_metadata(run_dir, payload)


def save_labor_metadata(run_dir: Path, metadata: Dict[str, Any]) -> Dict[str, Any]:
    with _run_metadata_lock(run_dir.name):
        if labor_postgres_state_enabled():
            payload = dict(metadata)
            payload.setdefault("id", run_dir.name)
            try:
                stored, _ = transition_labor_run_state(
                    run_dir.name,
                    lambda _current: payload,
                    actor_user_id=str(payload.get("ownerUserId") or ""),
                )
            except LaborStateNotFound:
                stored = create_labor_run_state(
                    payload,
                    actor_user_id=str(payload.get("ownerUserId") or ""),
                )
            return _cache_authoritative_labor_metadata(run_dir, stored)
        now = datetime.now().isoformat(timespec="seconds")
        payload = dict(metadata)
        payload.setdefault("createdAt", now)
        payload["updatedAt"] = now
        if labor_persistent_storage_enabled():
            payload["storage"] = labor_persistent_storage_info()
        payload = materialize_labor_metadata_for_local(run_dir, payload)
        metadata_path = run_dir / METADATA_FILE
        _write_labor_metadata_file(metadata_path, payload)
        if labor_persistent_storage_enabled() and not labor_postgres_state_enabled():
            canonical_payload = canonicalize_labor_metadata_for_blob(run_dir, payload)
            _write_labor_metadata_file(metadata_path, canonical_payload)
            sync_labor_run_to_persistent(run_dir.name, run_dir)
            payload = materialize_labor_metadata_for_local(run_dir, canonical_payload)
            _write_labor_metadata_file(metadata_path, payload)
        return payload


def update_labor_metadata(
    run_id: str,
    updates: Dict[str, Any],
    *,
    actor_user_id: str = "",
    action: str = "",
    reason_code: str = "",
    audit_details: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    if labor_postgres_state_enabled():
        stored, _ = transition_labor_run_state(
            run_id,
            lambda current: {**current, **updates},
            actor_user_id=actor_user_id,
            action=action,
            reason_code=reason_code,
            audit_details=audit_details,
        )
        return _cache_authoritative_labor_metadata(get_labor_run_dir(run_id), stored)
    with _run_metadata_lock(run_id):
        run_dir = get_labor_run_dir(run_id)
        metadata = _load_labor_metadata_for_update(run_dir)
        metadata.update(updates)
        return save_labor_metadata(run_dir, metadata)


def update_labor_metadata_record_only(run_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    """Compatibility wrapper for existing production upload routes."""
    return update_labor_metadata(run_id, updates)


def begin_labor_metadata_task(
    run_id: str,
    *,
    task_generation_id: str,
    updates: Callable[[Dict[str, Any]], Dict[str, Any]],
    actor_user_id: str = "",
) -> tuple[Dict[str, Any], bool]:
    """Atomically claim one active reconciliation generation for a run."""

    generation = str(task_generation_id or "").strip()
    if not generation:
        raise ValueError("task_generation_id is required")
    if labor_postgres_state_enabled():
        def transition(metadata: Dict[str, Any]) -> Dict[str, Any] | None:
            async_task = metadata.get("asyncTask") if isinstance(metadata.get("asyncTask"), dict) else {}
            if metadata.get("status") == "抽取中" and async_task.get("status") in {"queued", "running"}:
                return None
            next_updates = updates(dict(metadata))
            if not isinstance(next_updates, dict):
                raise TypeError("labor task updates must be a dict")
            payload = {**metadata, **next_updates, "taskGenerationId": generation}
            current_task = payload.get("asyncTask") if isinstance(payload.get("asyncTask"), dict) else {}
            payload["asyncTask"] = {**current_task, "taskGenerationId": generation}
            return payload

        stored, changed = transition_labor_run_state(
            run_id,
            transition,
            actor_user_id=actor_user_id,
            action="reconciliation_task_queued",
            reason_code="reconciliation_requested",
        )
        return _cache_authoritative_labor_metadata(get_labor_run_dir(run_id), stored), changed
    with _run_metadata_lock(run_id):
        run_dir = get_labor_run_dir(run_id)
        metadata = _load_labor_metadata_for_update(run_dir)
        async_task = metadata.get("asyncTask") if isinstance(metadata.get("asyncTask"), dict) else {}
        if metadata.get("status") == "抽取中" and async_task.get("status") in {"queued", "running"}:
            return metadata, False
        next_updates = updates(dict(metadata))
        if not isinstance(next_updates, dict):
            raise TypeError("labor task updates must be a dict")
        metadata.update(next_updates)
        metadata["taskGenerationId"] = generation
        current_task = metadata.get("asyncTask") if isinstance(metadata.get("asyncTask"), dict) else {}
        metadata["asyncTask"] = {**current_task, "taskGenerationId": generation}
        return save_labor_metadata(run_dir, metadata), True


def begin_labor_mapping_preflight(
    run_id: str,
    *,
    task_generation_id: str,
    input_fingerprint: str,
    actor_user_id: str = "",
) -> tuple[Dict[str, Any], bool]:
    """Atomically create one Worker mapping-preflight generation for the current inputs."""

    generation = str(task_generation_id or "").strip()
    fingerprint = str(input_fingerprint or "").strip().lower()
    if not generation:
        raise ValueError("task_generation_id is required")
    if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise ValueError("input_fingerprint must be SHA-256")

    def transition(metadata: Dict[str, Any]) -> Dict[str, Any] | None:
        current = metadata.get("mappingPreflight") if isinstance(metadata.get("mappingPreflight"), dict) else {}
        if (
            str(current.get("inputFingerprint") or "").strip().lower() == fingerprint
            and str(current.get("status") or "") in {"queued", "running", "completed"}
        ):
            return None
        now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        return {
            **metadata,
            "mappingPreflight": {
                "status": "queued",
                "statusLabel": "等待本人核对助手读取 Excel",
                "message": "字段预检任务已提交，等待本人核对助手读取工作表和列名。",
                "taskGenerationId": generation,
                "inputFingerprint": fingerprint,
                "requestedAt": now,
                "completedAt": "",
                "workbooks": [],
                "sheets": [],
                "errorCode": "",
                "errorMessage": "",
            },
        }

    if labor_postgres_state_enabled():
        stored, changed = transition_labor_run_state(
            run_id,
            transition,
            actor_user_id=actor_user_id,
            action="mapping_preflight_queued",
            reason_code="mapping_preflight_requested",
            audit_details={"inputFingerprint": fingerprint},
        )
        return _cache_authoritative_labor_metadata(get_labor_run_dir(run_id), stored), changed
    with _run_metadata_lock(run_id):
        run_dir = get_labor_run_dir(run_id)
        metadata = _load_labor_metadata_for_update(run_dir)
        proposed = transition(metadata)
        if proposed is None:
            return metadata, False
        return save_labor_metadata(run_dir, proposed), True


def update_labor_metadata_for_mapping_preflight(
    run_id: str,
    *,
    expected_task_generation_id: str,
    updates: Dict[str, Any] | Callable[[Dict[str, Any]], Dict[str, Any]],
    actor_user_id: str = "",
    action: str = "",
    reason_code: str = "",
) -> tuple[Dict[str, Any], bool]:
    """Apply a mapping-preflight-owned transition only while its nested generation is current."""

    expected = str(expected_task_generation_id or "").strip()

    def transition(metadata: Dict[str, Any]) -> Dict[str, Any] | None:
        current = metadata.get("mappingPreflight") if isinstance(metadata.get("mappingPreflight"), dict) else {}
        if not expected or str(current.get("taskGenerationId") or "").strip() != expected:
            return None
        next_updates = updates(dict(metadata)) if callable(updates) else updates
        if not isinstance(next_updates, dict):
            raise TypeError("labor mapping preflight updates must be a dict")
        return {**metadata, **next_updates}

    if labor_postgres_state_enabled():
        stored, changed = transition_labor_run_state(
            run_id,
            transition,
            actor_user_id=actor_user_id,
            action=action,
            reason_code=reason_code,
        )
        return _cache_authoritative_labor_metadata(get_labor_run_dir(run_id), stored), changed
    with _run_metadata_lock(run_id):
        run_dir = get_labor_run_dir(run_id)
        metadata = _load_labor_metadata_for_update(run_dir)
        proposed = transition(metadata)
        if proposed is None:
            return metadata, False
        return save_labor_metadata(run_dir, proposed), True


def update_labor_metadata_for_task(
    run_id: str,
    *,
    expected_task_generation_id: str,
    updates: Dict[str, Any] | Callable[[Dict[str, Any]], Dict[str, Any]],
) -> tuple[Dict[str, Any], bool]:
    """Apply a task-owned transition only while that generation is current."""

    expected = str(expected_task_generation_id or "").strip()
    if labor_postgres_state_enabled():
        def transition(metadata: Dict[str, Any]) -> Dict[str, Any] | None:
            if not expected or _labor_task_generation_id(metadata) != expected:
                return None
            next_updates = updates(dict(metadata)) if callable(updates) else updates
            if not isinstance(next_updates, dict):
                raise TypeError("labor task updates must be a dict")
            return {**metadata, **next_updates}

        stored, changed = transition_labor_run_state(run_id, transition)
        return _cache_authoritative_labor_metadata(get_labor_run_dir(run_id), stored), changed
    with _run_metadata_lock(run_id):
        run_dir = get_labor_run_dir(run_id)
        metadata = _load_labor_metadata_for_update(run_dir)
        if not expected or _labor_task_generation_id(metadata) != expected:
            return metadata, False
        next_updates = updates(dict(metadata)) if callable(updates) else updates
        if not isinstance(next_updates, dict):
            raise TypeError("labor task updates must be a dict")
        metadata.update(next_updates)
        return save_labor_metadata(run_dir, metadata), True


def compare_and_update_labor_metadata(
    run_id: str,
    *,
    expected_task_generation_id: str = "",
    expected_fingerprint: str,
    fingerprint: Callable[[Dict[str, Any]], str],
    updates: Dict[str, Any],
    conflict_updates: Callable[[Dict[str, Any]], Dict[str, Any]],
) -> tuple[Dict[str, Any], bool]:
    """Atomically publish a result only while its input snapshot is current."""

    if labor_postgres_state_enabled():
        committed = False

        def transition(metadata: Dict[str, Any]) -> Dict[str, Any] | None:
            nonlocal committed
            expected_generation = str(expected_task_generation_id or "").strip()
            if expected_generation and _labor_task_generation_id(metadata) != expected_generation:
                return None
            if fingerprint(metadata) != expected_fingerprint:
                return {**metadata, **conflict_updates(dict(metadata))}
            committed = True
            return {**metadata, **updates}

        stored, _ = transition_labor_run_state(run_id, transition)
        return _cache_authoritative_labor_metadata(get_labor_run_dir(run_id), stored), committed
    with _run_metadata_lock(run_id):
        run_dir = get_labor_run_dir(run_id)
        metadata = _load_labor_metadata_for_update(run_dir)
        expected_generation = str(expected_task_generation_id or "").strip()
        if expected_generation and _labor_task_generation_id(metadata) != expected_generation:
            return metadata, False
        if fingerprint(metadata) != expected_fingerprint:
            metadata.update(conflict_updates(dict(metadata)))
            return save_labor_metadata(run_dir, metadata), False
        metadata.update(updates)
        return save_labor_metadata(run_dir, metadata), True


def _labor_task_generation_id(metadata: Dict[str, Any]) -> str:
    async_task = metadata.get("asyncTask") if isinstance(metadata.get("asyncTask"), dict) else {}
    return str(metadata.get("taskGenerationId") or async_task.get("taskGenerationId") or "").strip()


def _load_labor_metadata_for_update(run_dir: Path) -> Dict[str, Any]:
    if labor_postgres_state_enabled():
        return load_labor_run_state(run_dir.name)
    metadata_path = run_dir / METADATA_FILE
    if labor_persistent_storage_enabled() and metadata_path.exists():
        metadata = _read_labor_metadata_file(metadata_path)
        return materialize_labor_metadata_for_local(run_dir, metadata)
    return load_labor_metadata(run_dir)


def load_labor_metadata(run_dir: Path) -> Dict[str, Any]:
    with _run_metadata_lock(run_dir.name):
        if labor_postgres_state_enabled():
            stored = load_labor_run_state(run_dir.name)
            return _cache_authoritative_labor_metadata(run_dir, stored)
        path = run_dir / METADATA_FILE
        if labor_persistent_storage_enabled() and not path.exists():
            sync_labor_run_from_persistent(run_dir.name, run_dir)
        if not path.exists():
            raise FileNotFoundError("劳务核对批次不存在。")
        payload = _read_labor_metadata_file(path)
        payload = materialize_labor_metadata_for_local(run_dir, payload)
        _write_labor_metadata_file(path, payload)
        return payload


def _write_labor_metadata_file(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        for retry_delay in (*_WINDOWS_REPLACE_RETRY_DELAYS, None):
            try:
                os.replace(tmp_path, path)
                return
            except PermissionError as exc:
                if getattr(exc, "winerror", None) not in {5, 32} or retry_delay is None:
                    raise
                time.sleep(retry_delay)
    finally:
        tmp_path.unlink(missing_ok=True)


def _read_labor_metadata_file(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def list_labor_metadata(
    *,
    limit: int | None = None,
    owner_user_id: str = "",
) -> List[Dict[str, Any]]:
    if labor_postgres_state_enabled():
        return list_labor_run_states(owner_user_id=owner_user_id, limit=limit or 500)
    if labor_persistent_storage_enabled():
        rows = list_labor_metadata_from_persistent()
        if owner_user_id:
            rows = [row for row in rows if str(row.get("ownerUserId") or "") == owner_user_id]
        return rows[:limit] if limit else rows
    if not LABOR_RUNS_DIR.exists():
        return []
    rows = []
    paths = list(LABOR_RUNS_DIR.glob(f"*/{METADATA_FILE}"))
    if limit:
        paths = sorted(paths, key=_labor_metadata_mtime, reverse=True)
    for path in paths:
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
        if limit and len(rows) >= limit:
            break
    if owner_user_id:
        rows = [row for row in rows if str(row.get("ownerUserId") or "") == owner_user_id]
    return sorted(rows, key=lambda row: row.get("updatedAt") or row.get("createdAt") or "", reverse=True)


def _labor_metadata_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _cache_authoritative_labor_metadata(run_dir: Path, metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Materialize a Postgres snapshot locally without making the cache authoritative."""

    with _run_metadata_lock(run_dir.name):
        run_dir.mkdir(parents=True, exist_ok=True)
        payload = materialize_labor_metadata_for_local(run_dir, dict(metadata))
        metadata_path = run_dir / METADATA_FILE
        current_revision = 0
        if metadata_path.exists():
            try:
                current_revision = int(_read_labor_metadata_file(metadata_path).get("stateRevision") or 0)
            except (OSError, ValueError, json.JSONDecodeError):
                current_revision = 0
        next_revision = int(payload.get("stateRevision") or 0)
        if not current_revision or next_revision >= current_revision:
            _write_labor_metadata_file(metadata_path, payload)
        if labor_persistent_storage_enabled() and not labor_postgres_state_enabled():
            canonical_payload = canonicalize_labor_metadata_for_blob(run_dir, payload)
            _write_labor_metadata_file(metadata_path, canonical_payload)
            sync_labor_run_to_persistent(run_dir.name, run_dir)
            payload = materialize_labor_metadata_for_local(run_dir, canonical_payload)
            _write_labor_metadata_file(metadata_path, payload)
        return payload


def get_labor_run_dir(run_id: str) -> Path:
    if not re.fullmatch(r"[0-9A-Za-z_\-]+", run_id):
        raise FileNotFoundError("劳务核对批次不存在。")
    return LABOR_RUNS_DIR / run_id


def labor_file_url(run_id: str, path: str | Path | None) -> str:
    if not path:
        return ""
    return f"/api/labor/runs/{run_id}/download/{Path(path).name}"


def attach_labor_file(run_id: str, path: str | Path | None, label: str) -> Dict[str, Any]:
    if not path:
        return {}
    path_obj = Path(path)
    record = {
        "label": label,
        "filename": path_obj.name,
        "path": str(path_obj),
        "downloadUrl": labor_file_url(run_id, path_obj),
    }
    if path_obj.exists() and path_obj.is_file():
        digest = hashlib.sha256()
        with path_obj.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        record["sizeBytes"] = path_obj.stat().st_size
        record["sha256"] = digest.hexdigest()
    return record


def safe_labor_filename(original_name: str, suffix: str = "") -> str:
    original = Path(original_name)
    stem = "".join(char if char.isalnum() or char in "_-" else "_" for char in original.stem.replace(" ", "_")).strip("_") or "file"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    suffix_part = f"_{suffix}" if suffix else ""
    return f"{stem}{suffix_part}_{timestamp}{original.suffix.lower()}"


def safe_labor_storage_filename(original_name: str, suffix: str = "") -> str:
    """Backward-compatible name used by existing production report routes."""
    return safe_labor_filename(original_name, suffix)
