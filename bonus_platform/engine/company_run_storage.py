"""Optional private OBS persistence for file-based payroll runs.

Activation is explicit per module so existing local history can be exported
before a production deployment starts reading OBS as the authority.
"""

from __future__ import annotations

import mimetypes
import os
import re
from pathlib import Path
from uuid import uuid4

from .labor.obs_storage import obs_get_bytes, obs_list_objects, obs_put_bytes, obs_storage_configured


_SAFE_RUN_ID = re.compile(r"^[0-9A-Za-z_-]+$")


def enabled(variable: str) -> bool:
    if os.environ.get(variable, "").strip().lower() not in {"obs", "s3"}:
        return False
    if not obs_storage_configured():
        raise RuntimeError(f"{variable} 已启用，但 OBS 配置不完整")
    return True


def _environment() -> str:
    raw = os.environ.get("SIGMA_LABOR_STORAGE_ENV") or "local"
    return re.sub(r"[^0-9A-Za-z_-]+", "-", raw.strip().lower()).strip("-_") or "local"


def _prefix(module: str, run_id: str = "") -> str:
    if not _SAFE_RUN_ID.fullmatch(module) or (run_id and not _SAFE_RUN_ID.fullmatch(run_id)):
        raise ValueError("业务批次标识无效")
    return f"{module}/{_environment()}/" + (f"{run_id}/" if run_id else "")


def upload_run_dir(module: str, run_dir: Path) -> None:
    prefix = _prefix(module, run_dir.name)
    for path in sorted(run_dir.rglob("*")):
        if not path.is_file() or path.name.endswith(".tmp"):
            continue
        relative = path.relative_to(run_dir).as_posix()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        obs_put_bytes(prefix + relative, path.read_bytes(), content_type=content_type)


def restore_run_dir(module: str, run_id: str, root: Path) -> Path:
    prefix = _prefix(module, run_id)
    run_dir = root / run_id
    for row in obs_list_objects(prefix):
        key = str(row.get("key") or "")
        if not key.startswith(prefix) or key.endswith("/"):
            continue
        relative = Path(key[len(prefix):])
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            continue
        content = obs_get_bytes(key)
        if content is None:
            continue
        target = run_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.restore.tmp")
        try:
            temporary.write_bytes(content)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    return run_dir


def list_run_ids(module: str, *, limit: int = 50) -> list[str]:
    prefix = _prefix(module)
    run_ids = {
        key[len(prefix):].split("/", 1)[0]
        for row in obs_list_objects(prefix)
        if (key := str(row.get("key") or "")).startswith(prefix)
        and key.endswith("/metadata.json")
    }
    return sorted((run_id for run_id in run_ids if _SAFE_RUN_ID.fullmatch(run_id)), reverse=True)[:limit]


def load_file(module: str, run_id: str, filename: str) -> bytes | None:
    if Path(filename).name != filename or not filename or filename.startswith("."):
        raise ValueError("业务文件名无效")
    return obs_get_bytes(_prefix(module, run_id) + filename)
