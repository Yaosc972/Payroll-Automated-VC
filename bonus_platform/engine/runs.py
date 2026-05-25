from __future__ import annotations

from datetime import datetime
import json
import re
from pathlib import Path
from uuid import uuid4
from typing import Any, Dict, List

from ..config import DEFAULT_RULE_WORKBOOK, RUNS_DIR


METADATA_FILE = "metadata.json"


def new_run_id(month: int) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return f"{month}_{timestamp}_{uuid4().hex[:8]}"


def create_run_dir(run_id: str) -> Path:
    path = RUNS_DIR / run_id
    path.mkdir(parents=True, exist_ok=False)
    return path


def save_metadata(run_dir: Path, metadata: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.now().isoformat(timespec="seconds")
    metadata = dict(metadata)
    metadata.setdefault("createdAt", now)
    metadata["updatedAt"] = now
    metadata_path = run_dir / METADATA_FILE
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadata


def update_metadata(run_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    run_dir = get_run_dir(run_id)
    metadata = load_metadata(run_dir)
    metadata.update(updates)
    return save_metadata(run_dir, metadata)


def load_metadata(run_dir: Path) -> Dict[str, Any]:
    metadata_path = run_dir / METADATA_FILE
    if not metadata_path.exists():
        raise FileNotFoundError(f"找不到批次元数据：{run_dir.name}")
    return json.loads(metadata_path.read_text(encoding="utf-8"))


def list_run_metadata() -> List[Dict[str, Any]]:
    if not RUNS_DIR.exists():
        return []
    runs = []
    for metadata_path in RUNS_DIR.glob(f"*/{METADATA_FILE}"):
        try:
            runs.append(json.loads(metadata_path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return sorted(runs, key=lambda row: row.get("updatedAt") or row.get("createdAt") or "", reverse=True)


def get_run_dir(run_id: str) -> Path:
    if not re.fullmatch(r"[0-9A-Za-z_\-]+", run_id):
        raise FileNotFoundError("批次不存在。")
    return RUNS_DIR / run_id


def run_file_url(run_id: str, path: str | Path | None) -> str:
    if not path:
        return ""
    return f"/api/runs/{run_id}/download/{Path(path).name}"


def attach_file_record(run_id: str, path: str | Path | None, label: str) -> Dict[str, Any]:
    if not path:
        return {}
    path_obj = Path(path)
    return {
        "label": label,
        "filename": path_obj.name,
        "path": str(path_obj),
        "downloadUrl": run_file_url(run_id, path_obj),
    }


def rule_info() -> Dict[str, Any]:
    if not DEFAULT_RULE_WORKBOOK.exists():
        return {
            "workbook": str(DEFAULT_RULE_WORKBOOK),
            "updatedAt": "",
            "size": 0,
        }
    stat = DEFAULT_RULE_WORKBOOK.stat()
    return {
        "workbook": str(DEFAULT_RULE_WORKBOOK),
        "updatedAt": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        "size": stat.st_size,
    }
