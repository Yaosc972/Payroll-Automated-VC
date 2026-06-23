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
    labor_blob_storage_enabled,
    list_labor_metadata_from_blob,
    materialize_labor_metadata_for_local,
    sync_labor_run_from_blob,
    sync_labor_run_to_blob,
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
    payload = materialize_labor_metadata_for_local(run_dir, payload)
    metadata_path = run_dir / METADATA_FILE
    tmp_path = metadata_path.with_suffix(f"{metadata_path.suffix}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, metadata_path)
    if labor_blob_storage_enabled():
        canonical_payload = canonicalize_labor_metadata_for_blob(run_dir, payload)
        metadata_path.write_text(json.dumps(canonical_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        sync_labor_run_to_blob(run_dir.name, run_dir)
        payload = materialize_labor_metadata_for_local(run_dir, canonical_payload)
        metadata_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def update_labor_metadata(run_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    run_dir = get_labor_run_dir(run_id)
    metadata_path = run_dir / METADATA_FILE
    if labor_blob_storage_enabled() and metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata = materialize_labor_metadata_for_local(run_dir, metadata)
    else:
        metadata = load_labor_metadata(run_dir)
    metadata.update(updates)
    return save_labor_metadata(run_dir, metadata)


def load_labor_metadata(run_dir: Path) -> Dict[str, Any]:
    if labor_blob_storage_enabled():
        sync_labor_run_from_blob(run_dir.name, run_dir)
    path = run_dir / METADATA_FILE
    if not path.exists():
        raise FileNotFoundError("劳务核对批次不存在。")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload = materialize_labor_metadata_for_local(run_dir, payload)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def list_labor_metadata(*, limit: int | None = None) -> List[Dict[str, Any]]:
    if labor_blob_storage_enabled():
        rows = list_labor_metadata_from_blob()
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
