from __future__ import annotations

import argparse
import json
import logging
import sys
import time

from bonus_platform.config import AI_CONFIG
from bonus_platform.engine.labor.jobs import labor_worker_job_store_health
from bonus_platform.engine.labor.persistent_storage import labor_persistent_storage_health


logger = logging.getLogger(__name__)


def worker_preflight(*, probe: bool = False) -> dict:
    storage = labor_persistent_storage_health(probe=probe)
    jobs = labor_worker_job_store_health(probe=probe)
    ai = _ai_health()
    problems: list[dict] = []
    warnings: list[dict] = []

    if not storage.get("enabled"):
        problems.append(
            {
                "component": "storage",
                "code": "LABOR_STORAGE_DISABLED",
                "message": "海外劳务 Worker 需要启用持久化文件存储。",
            }
        )
    if storage.get("ok") is False:
        problems.append(
            {
                "component": "storage",
                "code": str(storage.get("errorType") or "LABOR_STORAGE_UNHEALTHY"),
                "message": str(storage.get("errorMessage") or "Supabase Storage 探测失败。"),
            }
        )
    if not jobs.get("enabled"):
        problems.append(
            {
                "component": "jobs",
                "code": "LABOR_WORKER_DISABLED",
                "message": "海外劳务 Worker 队列未启用。",
            }
        )
    if jobs.get("ok") is False:
        problems.append(
            {
                "component": "jobs",
                "code": str(jobs.get("errorCode") or "LABOR_WORKER_QUEUE_UNHEALTHY"),
                "message": str(jobs.get("message") or "海外劳务 Worker 队列不可用。"),
            }
        )
    if ai["enabled"] and not ai["apiKeyConfigured"]:
        problems.append(
            {
                "component": "ai",
                "code": "AI_API_KEY_MISSING",
                "message": "已启用 AI 抽取，但缺少 AI_API_KEY 或 MIMO_API_KEY。",
            }
        )
    if not ai["enabled"]:
        warnings.append(
            {
                "component": "ai",
                "code": "AI_DISABLED",
                "message": "AI 抽取未启用；仅能处理无需 AI/OCR 的文本型材料。",
            }
        )

    return {
        "ok": not problems,
        "probe": bool(probe),
        "storage": storage,
        "jobs": jobs,
        "ai": ai,
        "problems": problems,
        "warnings": warnings,
    }


def _ai_health() -> dict:
    return {
        "enabled": bool(AI_CONFIG.get("enabled")),
        "provider": str(AI_CONFIG.get("provider") or ""),
        "apiKeyConfigured": bool(AI_CONFIG.get("api_key")),
        "model": str(AI_CONFIG.get("model") or ""),
        "timeoutSeconds": int(AI_CONFIG.get("timeout_seconds") or 0),
        "documentToolchain": str(AI_CONFIG.get("document_toolchain") or ""),
        "parallelMaxWorkers": int(AI_CONFIG.get("parallel_max_workers") or 0),
        "parallelImageRenderWorkers": int(AI_CONFIG.get("parallel_image_render_workers") or 0),
    }


def _print_health(health: dict) -> None:
    print(json.dumps(health, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Sigma overseas labor worker")
    parser.add_argument("--once", action="store_true", help="Process at most one queued job and exit.")
    parser.add_argument("--check", action="store_true", help="Run startup checks and exit.")
    parser.add_argument("--probe", action="store_true", help="Probe Supabase Storage/Postgres during startup checks.")
    parser.add_argument("--require-ready", action="store_true", help="Run startup checks before entering the worker loop.")
    parser.add_argument("--fail-fast", action="store_true", help="Exit when claiming or processing a job raises unexpectedly.")
    parser.add_argument("--max-jobs", type=int, default=0, help="Process up to this many jobs, then exit. 0 means unlimited.")
    parser.add_argument("--interval", type=float, default=5.0, help="Polling interval in seconds for continuous mode.")
    parser.add_argument("--worker-id", default="", help="Stable worker identifier.")
    args = parser.parse_args(argv)

    if args.check or args.require_ready:
        health = worker_preflight(probe=args.probe)
        _print_health(health)
        if not health["ok"]:
            raise SystemExit(1)
        if args.check:
            return

    processed = 0

    while True:
        try:
            result = _process_one_labor_job(worker_id=args.worker_id or None)
        except Exception:
            logger.exception("Unexpected overseas labor worker failure")
            if args.once or args.fail_fast or args.max_jobs:
                raise
            time.sleep(max(args.interval, 1.0))
            continue
        if result:
            processed += 1
        if args.max_jobs and processed >= args.max_jobs:
            return
        if args.once:
            return
        time.sleep(max(args.interval, 1.0))


def _process_one_labor_job(worker_id: str | None = None) -> dict | None:
    from .labor import process_one_labor_job

    return process_one_labor_job(worker_id=worker_id)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
