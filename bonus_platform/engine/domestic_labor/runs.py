"""Domestic labor payroll run management — file-based storage.

Each calculation task is a directory under DOMESTIC_LABOR_RUNS_DIR containing:
  - metadata.json  (task state, params, results)
  - uploaded Excel files
"""
from __future__ import annotations

from datetime import datetime
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4

from ...config import DOMESTIC_LABOR_RUNS_DIR
from .persistent_storage import (
    delete_domestic_labor_run_from_persistent,
    domestic_labor_persistent_storage_enabled,
    list_domestic_labor_metadata_from_persistent,
    load_domestic_labor_file_from_persistent,
    load_domestic_labor_metadata_from_persistent,
    load_domestic_labor_status_from_persistent,
    save_domestic_labor_file_to_persistent,
    save_domestic_labor_metadata_to_persistent,
)


METADATA_FILE = "metadata.json"
STATUS_FILE = "status.json"


def new_payroll_run_id() -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return f"payroll_{timestamp}_{uuid4().hex[:8]}"


def create_payroll_run(metadata: Dict[str, Any]) -> Dict[str, Any]:
    run_id = new_payroll_run_id()
    run_dir = get_payroll_run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=False)
    payload = {
        "id": run_id,
        "status": "已创建",
        **metadata,
    }
    return save_payroll_metadata(run_dir, payload)


def save_payroll_metadata(run_dir: Path, metadata: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.now().isoformat(timespec="seconds")
    payload = dict(metadata)
    payload.setdefault("createdAt", now)
    payload["updatedAt"] = now
    run_dir.mkdir(parents=True, exist_ok=True)
    _save_local_payroll_metadata(run_dir, payload)
    if domestic_labor_persistent_storage_enabled():
        save_domestic_labor_metadata_to_persistent(
            run_dir.name,
            payload,
            _compact_metadata(payload),
        )
    return payload


def _save_local_payroll_metadata(run_dir: Path, payload: Dict[str, Any]) -> None:
    metadata_path = run_dir / METADATA_FILE
    tmp_path = metadata_path.with_suffix(f"{metadata_path.suffix}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, metadata_path)
    status_path = run_dir / STATUS_FILE
    status_tmp_path = status_path.with_suffix(f"{status_path.suffix}.tmp")
    status_payload = _compact_metadata(payload)
    status_tmp_path.write_text(json.dumps(status_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(status_tmp_path, status_path)


def _compact_metadata(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in payload.items() if key not in {"results", "filePath"}}


def update_payroll_metadata(run_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    run_dir = get_payroll_run_dir(run_id)
    metadata = load_payroll_metadata(run_dir)
    metadata.update(updates)
    return save_payroll_metadata(run_dir, metadata)


def load_payroll_metadata(run_dir: Path) -> Dict[str, Any]:
    path = run_dir / METADATA_FILE
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    if domestic_labor_persistent_storage_enabled():
        payload = load_domestic_labor_metadata_from_persistent(run_dir.name)
        if payload:
            run_dir.mkdir(parents=True, exist_ok=True)
            _save_local_payroll_metadata(run_dir, payload)
            return payload
    raise FileNotFoundError("薪酬计算任务不存在。")


def load_payroll_status(run_dir: Path) -> Dict[str, Any]:
    path = run_dir / STATUS_FILE
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    if domestic_labor_persistent_storage_enabled():
        payload = load_domestic_labor_status_from_persistent(run_dir.name)
        if payload:
            return payload
    metadata = load_payroll_metadata(run_dir)
    return _compact_metadata(metadata)


def list_payroll_metadata(compact: bool = False) -> List[Dict[str, Any]]:
    if domestic_labor_persistent_storage_enabled():
        return list_domestic_labor_metadata_from_persistent(compact=compact)
    if not DOMESTIC_LABOR_RUNS_DIR.exists():
        return []
    rows = []
    for path in DOMESTIC_LABOR_RUNS_DIR.glob(f"*/{METADATA_FILE}"):
        try:
            rows.append(load_payroll_status(path.parent) if compact else json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return sorted(rows, key=lambda row: row.get("updatedAt") or row.get("createdAt") or "", reverse=True)


def get_payroll_run_dir(run_id: str) -> Path:
    if not re.fullmatch(r"[0-9A-Za-z_\-]+", run_id):
        raise FileNotFoundError("薪酬计算任务不存在。")
    return DOMESTIC_LABOR_RUNS_DIR / run_id


def persist_payroll_file(run_id: str, path: str | Path) -> None:
    if domestic_labor_persistent_storage_enabled():
        save_domestic_labor_file_to_persistent(run_id, get_payroll_run_dir(run_id), path)


def materialize_payroll_file(run_id: str, filename: str) -> Path | None:
    run_dir = get_payroll_run_dir(run_id)
    target = run_dir / Path(filename).name
    if target.is_file():
        return target
    if not domestic_labor_persistent_storage_enabled():
        return None
    return load_domestic_labor_file_from_persistent(run_id, run_dir, Path(filename).name)


def delete_payroll_run(run_id: str) -> None:
    if domestic_labor_persistent_storage_enabled():
        delete_domestic_labor_run_from_persistent(run_id)


def payroll_file_url(run_id: str, path: str | Path | None) -> str:
    if not path:
        return ""
    return f"/api/domestic-labor/runs/{run_id}/download/{Path(path).name}"


def attach_payroll_file(run_id: str, path: str | Path | None, label: str) -> Dict[str, Any]:
    if not path:
        return {}
    path_obj = Path(path)
    return {
        "label": label,
        "filename": path_obj.name,
        "path": str(path_obj),
        "downloadUrl": payroll_file_url(run_id, path_obj),
    }


def safe_payroll_filename(original_name: str, suffix: str = "") -> str:
    original = Path(original_name)
    stem = "".join(
        char if char.isalnum() or char in "_-" else "_"
        for char in original.stem.replace(" ", "_")
    ).strip("_") or "file"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    suffix_part = f"_{suffix}" if suffix else ""
    return f"{stem}{suffix_part}_{timestamp}{original.suffix.lower()}"
