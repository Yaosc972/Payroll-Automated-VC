from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .state_postgres import (
    append_labor_audit_event_state,
    labor_postgres_state_enabled,
    read_labor_audit_events_state,
)


_AUDIT_LOCK = threading.Lock()
_ALLOWED_DETAIL_FIELDS = {
    "pdfFileCount",
    "workbookFileCount",
    "pdfPageCount",
    "uploadedBytes",
    "deletedFileCount",
    "deletedCacheEntryCount",
    "reclaimedBytes",
    "remainingBytes",
    "activeOwnerTasks",
    "activeGlobalTasks",
    "limit",
    "storageBackend",
    "retentionDays",
}


def _safe_text(value: Any, *, max_length: int = 160) -> str:
    return str(value or "").strip()[:max_length]


def _safe_details(details: dict[str, Any] | None) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in (details or {}).items():
        if key not in _ALLOWED_DETAIL_FIELDS:
            continue
        if isinstance(value, bool):
            safe[key] = value
        elif isinstance(value, (int, float)):
            safe[key] = value
        else:
            safe[key] = _safe_text(value)
    return safe


def append_labor_audit_event(
    audit_path: Path,
    *,
    action: str,
    run_id: str = "",
    owner_user_id: str = "",
    actor_user_id: str = "",
    outcome: str = "success",
    reason_code: str = "",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = {
        "eventId": uuid4().hex,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "runId": _safe_text(run_id, max_length=96),
        "ownerUserId": _safe_text(owner_user_id, max_length=128) or "local-default",
        "actorUserId": _safe_text(actor_user_id, max_length=128) or "local-default",
        "action": _safe_text(action, max_length=96),
        "outcome": _safe_text(outcome, max_length=32),
        "reasonCode": _safe_text(reason_code, max_length=96),
        "details": _safe_details(details),
    }
    if labor_postgres_state_enabled():
        append_labor_audit_event_state(
            action=event["action"],
            run_id=event["runId"],
            owner_user_id=event["ownerUserId"],
            actor_user_id=event["actorUserId"],
            outcome=event["outcome"],
            reason_code=event["reasonCode"],
            details=event["details"],
        )
        return event
    audit_path = Path(audit_path)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
    with _AUDIT_LOCK:
        with audit_path.open("a", encoding="utf-8") as destination:
            destination.write(line)
            destination.flush()
    return event


def read_labor_audit_events(
    audit_path: Path,
    *,
    limit: int | None = None,
    owner_user_id: str = "",
    run_id: str = "",
) -> list[dict[str, Any]]:
    if labor_postgres_state_enabled():
        return read_labor_audit_events_state(
            owner_user_id=owner_user_id,
            run_id=run_id,
            limit=limit or 500,
        )
    path = Path(audit_path)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    if owner_user_id:
        rows = [row for row in rows if str(row.get("ownerUserId") or "") == owner_user_id]
    if run_id:
        rows = [row for row in rows if str(row.get("runId") or "") == run_id]
    if limit and limit > 0:
        return rows[-limit:]
    return rows
