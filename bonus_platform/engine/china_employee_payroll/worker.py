"""Standalone worker: python -m bonus_platform.engine.china_employee_payroll.worker.

No Vercel request lifetime dependency. Lease heartbeat and fencing support restarts
and multiple workers. Input/result manifests reference immutable private objects.
"""
from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import zipfile

from . import durable, meal_runs
from .durable_store import Store, LeaseLost
from .meal_allowance import calculate_meal_allowance, parse_wx_attendance_workbooks
from .meal_beisen import BeisenMealSource
from .relocation import BeisenMonthlySource, RelocationError, calculate_relocation
from .relocation_export import build_workbook

logger = logging.getLogger(__name__)


def calculate(job, directory, progress):
    """Pure per-attempt workspace; only published object manifests are authoritative."""
    month = job["month"]
    if job["subject"] == "relocation-allowance":
        source = BeisenMonthlySource().load(month, progress)
        result = calculate_relocation(month, source, progress)
        attendance = result.pop("attendanceSource")
        run = {**job, "status": "completed", "calculatedAt": meal_runs.now(), "result": result, "attendanceSource": attendance}
        content, filename = build_workbook(run)
        return result["summary"], {"result": result}, {"run": run, "rawSource": source}, content, filename
    if job["subject"] == "wx-meal-allowance":
        paths = []
        for index, manifest in enumerate(job["inputs"]):
            progress({"message": "正在校验 WX 考勤文件", "stage": 0, "completed": index, "total": len(job["inputs"]), "unit": "个文件"})
            path = directory / f"input-{index}.xlsx"
            path.write_bytes(durable.read_file(manifest))
            with zipfile.ZipFile(path) as archive:
                if sum(info.file_size for info in archive.infolist()) > 512 * 1024 * 1024:
                    raise RelocationError("考勤文件解压后过大，请按月拆分文件。")
            paths.append(path)
        parsed = parse_wx_attendance_workbooks(paths)
    else:
        parsed = BeisenMealSource().load(month, progress)
    meal_runs.validate_attendance(parsed, month)
    progress({"message": "正在核对规则并生成餐补结果", "stage": 2})
    meal_runs.save_source(directory, parsed)
    result = calculate_meal_allowance(parsed)
    metadata = {**job, "status": "completed", "calculatedAt": meal_runs.now(), "summary": result["summary"],
                "normalizedExport": True, "sourceOrigin": "upload" if job["sourceType"] == "wx" else "beisen"}
    meal_runs.save_json(directory / "metadata.json", metadata)
    meal_runs.save_json(directory / "result.json", result)
    # Reuse the production export styling, formula safety and calculation rules.
    from bonus_platform.app import _build_china_employee_meal_allowance_export, _compact_china_employee_payroll_result
    path = _build_china_employee_meal_allowance_export(directory, job["runId"])
    import json
    snapshot = {"metadata": metadata, "result": result, "attendanceSource": json.loads((directory / "data-source.json").read_text())}
    public = {"summary": result["summary"], "results": _compact_china_employee_payroll_result(result),
              "files": result.get("files", []), "warnings": result.get("warnings", {}), "sourceType": job["sourceType"]}
    return result["summary"], public, snapshot, path.read_bytes(), path.name


def process_one(store=None, calculator=calculate):
    store = store or Store()
    claimed = store.claim()
    if not claimed:
        return False
    job, token = claimed
    stop, lost = threading.Event(), threading.Event()

    def heartbeat():
        while not stop.wait(25):
            try:
                store.update(job["runId"], token)
            except Exception:
                lost.set()
                return

    def progress(update):
        if lost.is_set():
            raise LeaseLost()
        values = {"progress": update.get("message", "正在核算"), "progressDetail": {k: v for k, v in update.items() if k != "message"}} if isinstance(update, dict) else {"progress": str(update)}
        store.update(job["runId"], token, values)

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        with TemporaryDirectory(prefix="sigma-china-payroll-") as temporary:
            summary, public, snapshot, content, filename = calculator(job, Path(temporary), progress)
            progress("正在保存核算结果和考勤源数据")
            # Each lease owns a different object namespace; stale workers cannot
            # overwrite files referenced by a successor's completed transaction.
            saved = durable.put(job, "snapshot.json.gz", durable.encode(snapshot), "snapshots", identifier=token)
            result = durable.put(job, "result.json.gz", durable.encode(public), "results", identifier=token)
            exported = durable.put(job, filename, content, "exports", durable.XLSX, identifier=token)
            # Verify persistence before making a completed result visible.
            for manifest in (saved, result, exported):
                durable.read_file(manifest)
            store.update(job["runId"], token, {"status": "completed", "progress": "核算完成", "summary": summary,
                         "calculatedAt": meal_runs.now(), "snapshot": saved, "publicResult": result, "export": exported}, terminal=True)
    except LeaseLost:
        logger.warning("Payroll lease was lost; unpublished attempt discarded")
    except Exception as exc:
        message = str(exc) if isinstance(exc, RelocationError) else "核算或持久化保存失败，本次未发布结果，请检查服务后重试。"
        try:
            store.update(job["runId"], token, {"status": "failed", "progress": message}, terminal=True)
        except LeaseLost:
            pass
        logger.warning("Payroll attempt failed (%s)", type(exc).__name__)
    finally:
        stop.set()
        thread.join(timeout=30)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if os.getenv("VERCEL") or os.getenv("VERCEL_ENV"):
        raise RuntimeError("Run this worker on a persistent host, not a Vercel function")
    if not durable.storage.labor_private_object_storage_enabled():
        raise RuntimeError("Private persistent file storage is required")
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            worked = process_one()
        except Exception as exc:
            logger.warning("Payroll queue unavailable (%s)", type(exc).__name__)
            worked = False
        if args.once:
            break
        if not worked:
            time.sleep(5)


if __name__ == "__main__":
    main()
