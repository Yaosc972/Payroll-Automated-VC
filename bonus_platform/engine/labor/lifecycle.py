from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable

from .audit import append_labor_audit_event
from .runs import labor_run_metadata_lock


ACTIVE_RUN_STATUSES = {"抽取中"}
ACTIVE_TASK_STATUSES = {"queued", "running"}


def labor_run_is_active(metadata: dict) -> bool:
    task = metadata.get("asyncTask") if isinstance(metadata.get("asyncTask"), dict) else {}
    return str(metadata.get("status") or "") in ACTIVE_RUN_STATUSES or str(task.get("status") or "") in ACTIVE_TASK_STATUSES


def _parse_datetime(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value or ""))
    except (TypeError, ValueError):
        return None


def delete_labor_run_directory(
    run_dir: Path,
    *,
    audit_path: Path,
    reason_code: str,
    actor_user_id: str = "local-default",
    delete_persistent: Callable[[str, str], None] | None = None,
    delete_authoritative: Callable[[str, str, str], None] | None = None,
    record_audit: bool = True,
) -> dict:
    run_dir = Path(run_dir)
    with labor_run_metadata_lock(run_dir.name):
        metadata_path = run_dir / "metadata.json"
        if not metadata_path.exists():
            raise FileNotFoundError("劳务核对批次不存在。")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if labor_run_is_active(metadata):
            raise RuntimeError("ACTIVE_RUN")
        run_id = str(metadata.get("id") or run_dir.name)
        owner_user_id = str(metadata.get("ownerUserId") or "local-default")
        deleted_file_count = sum(1 for path in run_dir.rglob("*") if path.is_file())
        if delete_authoritative is not None:
            delete_authoritative(run_id, actor_user_id, reason_code)
        if delete_persistent is not None:
            delete_persistent(run_id, owner_user_id)
        if record_audit:
            append_labor_audit_event(
                audit_path,
                action="run_deleted",
                run_id=run_id,
                owner_user_id=owner_user_id,
                actor_user_id=actor_user_id,
                outcome="success",
                reason_code=reason_code,
                details={"deletedFileCount": deleted_file_count},
            )
        shutil.rmtree(run_dir)
        return {"runId": run_id, "deletedFileCount": deleted_file_count, "reasonCode": reason_code}


def cleanup_expired_labor_runs(
    runs_dir: Path,
    *,
    retention_days: int,
    audit_path: Path,
    now: datetime | None = None,
    delete_persistent: Callable[[str, str], None] | None = None,
) -> dict:
    reference = now or datetime.now()
    summary = {"deletedRunIds": [], "skippedActiveRunIds": [], "errorRunIds": []}
    if retention_days <= 0 or not Path(runs_dir).exists():
        return summary
    for metadata_path in sorted(Path(runs_dir).glob("*/metadata.json")):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            run_id = str(metadata.get("id") or metadata_path.parent.name)
            if labor_run_is_active(metadata):
                summary["skippedActiveRunIds"].append(run_id)
                continue
            updated_at = _parse_datetime(metadata.get("updatedAt") or metadata.get("createdAt"))
            if updated_at is None or (reference - updated_at).days < retention_days:
                continue
            delete_labor_run_directory(
                metadata_path.parent,
                audit_path=audit_path,
                reason_code="retention_expired",
                delete_persistent=delete_persistent,
            )
            summary["deletedRunIds"].append(run_id)
        except Exception:
            summary["errorRunIds"].append(metadata_path.parent.name)
    append_labor_audit_event(
        audit_path,
        action="retention_cleanup",
        outcome="success" if not summary["errorRunIds"] else "partial",
        reason_code="scheduled_cleanup",
        details={
            "deletedFileCount": len(summary["deletedRunIds"]),
            "retentionDays": retention_days,
        },
    )
    return summary
