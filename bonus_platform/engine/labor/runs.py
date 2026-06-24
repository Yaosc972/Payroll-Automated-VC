from __future__ import annotations

from datetime import datetime
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List
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
    sync_labor_metadata_to_persistent,
    sync_labor_run_from_persistent,
    sync_labor_run_to_persistent,
)


METADATA_FILE = "metadata.json"


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
    }
    return save_labor_metadata(run_dir, payload)


def save_labor_metadata(run_dir: Path, metadata: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.now().isoformat(timespec="seconds")
    payload = dict(metadata)
    payload.setdefault("createdAt", now)
    payload["updatedAt"] = now
    if labor_persistent_storage_enabled():
        payload["storage"] = labor_persistent_storage_info()
    payload = materialize_labor_metadata_for_local(run_dir, payload)
    metadata_path = run_dir / METADATA_FILE
    _write_labor_metadata_file(metadata_path, payload)
    if labor_persistent_storage_enabled():
        canonical_payload = canonicalize_labor_metadata_for_blob(run_dir, payload)
        _write_labor_metadata_file(metadata_path, canonical_payload)
        sync_labor_run_to_persistent(run_dir.name, run_dir)
        payload = materialize_labor_metadata_for_local(run_dir, canonical_payload)
        _write_labor_metadata_file(metadata_path, payload)
    return payload


def update_labor_metadata(run_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    run_dir = get_labor_run_dir(run_id)
    metadata_path = run_dir / METADATA_FILE
    if labor_persistent_storage_enabled() and metadata_path.exists():
        metadata = _read_labor_metadata_file(metadata_path)
        metadata = materialize_labor_metadata_for_local(run_dir, metadata)
    else:
        metadata = load_labor_metadata(run_dir)
    metadata.update(updates)
    return save_labor_metadata(run_dir, metadata)


def update_labor_metadata_record_only(run_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    run_dir = get_labor_run_dir(run_id)
    metadata_path = run_dir / METADATA_FILE
    if labor_persistent_storage_enabled() and metadata_path.exists():
        metadata = _read_labor_metadata_file(metadata_path)
        metadata = materialize_labor_metadata_for_local(run_dir, metadata)
    else:
        metadata = load_labor_metadata(run_dir)
    metadata.update(updates)
    return save_labor_metadata_record_only(run_dir, metadata)


def save_labor_metadata_record_only(run_dir: Path, metadata: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.now().isoformat(timespec="seconds")
    payload = dict(metadata)
    payload.setdefault("createdAt", now)
    payload["updatedAt"] = now
    if labor_persistent_storage_enabled():
        payload["storage"] = labor_persistent_storage_info()
    payload = materialize_labor_metadata_for_local(run_dir, payload)
    metadata_path = run_dir / METADATA_FILE
    _write_labor_metadata_file(metadata_path, payload)
    if labor_persistent_storage_enabled():
        canonical_payload = canonicalize_labor_metadata_for_blob(run_dir, payload)
        sync_labor_metadata_to_persistent(run_dir.name, run_dir, canonical_payload)
        payload = materialize_labor_metadata_for_local(run_dir, canonical_payload)
        _write_labor_metadata_file(metadata_path, payload)
    return payload


def load_labor_metadata(run_dir: Path) -> Dict[str, Any]:
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
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)


def _read_labor_metadata_file(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def list_labor_metadata(*, limit: int | None = None) -> List[Dict[str, Any]]:
    if labor_persistent_storage_enabled():
        rows = list_labor_metadata_from_persistent()
        return rows[:limit] if limit else rows
    if not LABOR_RUNS_DIR.exists():
        return []
    rows = []
    paths = list(LABOR_RUNS_DIR.glob(f"*/{METADATA_FILE}"))
    if limit:
        paths = sorted(paths, key=lambda path: path.stat().st_mtime, reverse=True)
    for path in paths:
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
        if limit and len(rows) >= limit:
            break
    return sorted(rows, key=lambda row: row.get("updatedAt") or row.get("createdAt") or "", reverse=True)


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
    return {"label": label, "filename": path_obj.name, "path": str(path_obj), "downloadUrl": labor_file_url(run_id, path_obj)}


def safe_labor_filename(original_name: str, suffix: str = "") -> str:
    original = Path(original_name)
    stem = "".join(char if char.isalnum() or char in "_-" else "_" for char in original.stem.replace(" ", "_")).strip("_") or "file"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    suffix_part = f"_{suffix}" if suffix else ""
    return f"{stem}{suffix_part}_{timestamp}{original.suffix.lower()}"


def safe_labor_storage_filename(original_name: str, suffix: str = "") -> str:
    original = Path(original_name)
    raw_stem = original.stem.replace(" ", "_")
    stem = "".join(
        char if char.isascii() and (char.isalnum() or char in "_-") else "_"
        for char in raw_stem
    ).strip("_-")
    stem = re.sub(r"_+", "_", stem) or "file"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    suffix_part = f"_{suffix}" if suffix else ""
    ext = "".join(char for char in original.suffix.lower() if char.isascii() and (char.isalnum() or char == ".")) or ".bin"
    return f"{stem}{suffix_part}_{timestamp}{ext}"
