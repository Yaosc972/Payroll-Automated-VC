from __future__ import annotations

from datetime import datetime
import json
import re
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4

from ...config import LABOR_RUNS_DIR


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
    (run_dir / METADATA_FILE).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def update_labor_metadata(run_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    run_dir = get_labor_run_dir(run_id)
    metadata = load_labor_metadata(run_dir)
    metadata.update(updates)
    return save_labor_metadata(run_dir, metadata)


def load_labor_metadata(run_dir: Path) -> Dict[str, Any]:
    path = run_dir / METADATA_FILE
    if not path.exists():
        raise FileNotFoundError("劳务核对批次不存在。")
    return json.loads(path.read_text(encoding="utf-8"))


def list_labor_metadata() -> List[Dict[str, Any]]:
    if not LABOR_RUNS_DIR.exists():
        return []
    rows = []
    for path in LABOR_RUNS_DIR.glob(f"*/{METADATA_FILE}"):
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
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

