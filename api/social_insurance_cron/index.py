from __future__ import annotations

from http.server import BaseHTTPRequestHandler
import json
import logging
import os
import secrets
import time
from typing import Any, Callable


RUNTIME_LABEL = "dedicated-cron-v1"
LOGGER = logging.getLogger("bonus_platform.social_insurance.cron_function")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
# httpx INFO records include full signed Blob URLs.  Keep the same credential
# redaction boundary as the monolithic application entrypoint.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
_MODULE_STARTED_AT = time.monotonic()
refresh_latest_reporting_snapshot: Callable[[], dict[str, Any]] | None
safe_error_category: Callable[[Exception], str]
try:
    from bonus_platform.engine.social_insurance.reporting_diagnostics import (
        safe_error_category,
    )
    from bonus_platform.engine.social_insurance.prefetch import (
        refresh_latest_reporting_snapshot,
    )
except Exception:  # noqa: BLE001 - import details must not enter public runtime logs.
    refresh_latest_reporting_snapshot = None
    safe_error_category = lambda _exc: "unknown"
_MODULE_IMPORT_MS = max(0, int((time.monotonic() - _MODULE_STARTED_AT) * 1000))
LOGGER.info(
    "社保 Cron 轻量函数初始化完成 runtime=%s state=%s moduleImportMs=%d",
    RUNTIME_LABEL,
    "ready" if refresh_latest_reporting_snapshot is not None else "error",
    _MODULE_IMPORT_MS,
)


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((time.monotonic() - started_at) * 1000))


class handler(BaseHTTPRequestHandler):
    def _write_json(self, status_code: int, payload: dict[str, Any]) -> None:
        content = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract.
        expected = os.environ.get("CRON_SECRET", "").strip()
        supplied = self.headers.get("authorization", "")
        if not expected or not secrets.compare_digest(supplied, f"Bearer {expected}"):
            self._write_json(401, {"detail": "定时同步授权失败"})
            return

        dispatch_started_at = time.monotonic()
        LOGGER.info(
            "社保 Cron 请求进入轻量函数 runtime=%s moduleImportMs=%d",
            RUNTIME_LABEL,
            _MODULE_IMPORT_MS,
        )
        if refresh_latest_reporting_snapshot is None:
            dispatch_ms = _elapsed_ms(dispatch_started_at)
            LOGGER.warning(
                "社保 Cron 轻量函数不可用 runtime=%s stage=function_import "
                "category=dependency_import moduleImportMs=%d dispatchMs=%d",
                RUNTIME_LABEL,
                _MODULE_IMPORT_MS,
                dispatch_ms,
            )
            self._write_json(503, {
                "state": "error",
                "label": "社保定时刷新函数初始化失败",
                "failedStage": "function_import",
                "errorCategory": "dependency_import",
                "stageTimingsMs": {"function_import": _MODULE_IMPORT_MS},
                "elapsedMs": _MODULE_IMPORT_MS + dispatch_ms,
                "runtime": RUNTIME_LABEL,
                "runtimeTimingsMs": {
                    "module_import": _MODULE_IMPORT_MS,
                    "handler_dispatch": dispatch_ms,
                },
            })
            return

        try:
            result = refresh_latest_reporting_snapshot()
            if not isinstance(result, dict):
                raise TypeError("reporting refresh result must be a dictionary")
        except Exception as exc:  # noqa: BLE001 - raw details may contain employee data.
            dispatch_ms = _elapsed_ms(dispatch_started_at)
            category = safe_error_category(exc)
            LOGGER.warning(
                "社保 Cron 轻量函数执行失败 runtime=%s stage=function_dispatch "
                "category=%s moduleImportMs=%d dispatchMs=%d",
                RUNTIME_LABEL,
                category,
                _MODULE_IMPORT_MS,
                dispatch_ms,
            )
            self._write_json(500, {
                "state": "error",
                "label": "社保定时刷新函数执行失败",
                "failedStage": "function_dispatch",
                "errorCategory": category,
                "stageTimingsMs": {"function_dispatch": dispatch_ms},
                "elapsedMs": _MODULE_IMPORT_MS + dispatch_ms,
                "runtime": RUNTIME_LABEL,
                "runtimeTimingsMs": {
                    "module_import": _MODULE_IMPORT_MS,
                    "handler_dispatch": dispatch_ms,
                },
            })
            return

        dispatch_ms = _elapsed_ms(dispatch_started_at)
        safe_state = str(result.get("state") or "unknown")
        if safe_state not in {"ready", "warming", "empty", "error"}:
            safe_state = "unknown"
        LOGGER.info(
            "社保 Cron 轻量函数执行结束 runtime=%s state=%s "
            "moduleImportMs=%d dispatchMs=%d",
            RUNTIME_LABEL,
            safe_state,
            _MODULE_IMPORT_MS,
            dispatch_ms,
        )
        self._write_json(200, {
            **result,
            "runtime": RUNTIME_LABEL,
            "runtimeTimingsMs": {
                "module_import": _MODULE_IMPORT_MS,
                "handler_dispatch": dispatch_ms,
            },
        })

    def log_message(self, _format: str, *_args: object) -> None:
        # Access logs add no diagnostic value here and may duplicate proxy metadata.
        return
