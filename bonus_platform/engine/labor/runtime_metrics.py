from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any


_LOCK = threading.Lock()


def record_labor_runtime_metric(event: str, *, status: str = "", summary: dict[str, Any] | None = None) -> None:
    configured = str(os.environ.get("LABOR_RUNTIME_METRICS_PATH") or "").strip()
    if not configured:
        return
    payload = {
        "event": str(event)[:96],
        "status": str(status)[:64],
        "createdAt": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "summary": summary or {},
    }
    path = Path(configured).expanduser()
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
