from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from tempfile import gettempdir
from uuid import uuid4
from urllib.parse import quote

from .relocation_export import build_workbook
from . import durable
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Body, HTTPException
from fastapi.responses import Response

from .relocation import BeisenMonthlySource, RelocationError, RULE_VERSION, calculate_relocation, validate_month

router = APIRouter(prefix="/api/china-employee-payroll/relocation-allowance", tags=["relocation-allowance"])
RUNS_DIR = Path(gettempdir()) / "sigma_workbench_relocation_runs"
WORKER_ID = uuid4().hex
_lock = threading.Lock()
_active = False


def _path(run_id):
    if len(run_id) != 32 or any(c not in "0123456789abcdef" for c in run_id):
        raise HTTPException(404, "核算批次不存在。")
    return RUNS_DIR / f"{run_id}.json"


def _save(run):
    RUNS_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = _path(run["runId"])
    temporary = target.with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(run, stream, ensure_ascii=False)
    temporary.replace(target)


def _read(run_id):
    target = _path(run_id)
    if not target.is_file():
        raise HTTPException(404, "核算批次不存在。")
    run = json.loads(target.read_text(encoding="utf-8"))
    run.pop("workerId", None)
    # Apply clarified review labels to saved batches without changing their amounts or source version.
    result = run.get("result")
    if run.get("status") == "completed" and result:
        obsolete = {"职能条线组织例外待确认", "离职特殊口径待确认", "核算月后离职，发放口径待确认"}
        for row in result["results"]:
            reasons = [r for r in row.get("reason", "").split("；") if r and r not in obsolete]
            row["reason"] = "；".join(reasons)
            if row.get("status") == "待确认" and not reasons:
                row["status"] = "已试算"
        result["summary"]["reviewCount"] = sum(r["status"] == "待确认" for r in result["results"])
        result["reviewPolicyVersion"] = RULE_VERSION
    return run


def _work(run):
    global _active
    try:
        def progress(message):
            if isinstance(message, dict):
                run["progress"] = message["message"]
                run["progressDetail"] = {k: v for k, v in message.items() if k != "message"}
            else:
                run["progress"] = message
            run["progressUpdatedAt"] = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
            _save(run)
        source = BeisenMonthlySource().load(run["month"], progress)
        result = calculate_relocation(run["month"], source, progress)
        run["attendanceSource"] = result.pop("attendanceSource")
        run["calculatedAt"] = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
        run.update(status="completed", progress="核算完成，待确认项请复核", result=result)
    except RelocationError as exc:
        run.update(status="failed", progress=str(exc))
    except Exception:
        run.update(status="failed", progress="数据校验或核算失败，本次未生成结果，请检查北森数据后重试。")
    finally:
        try:
            _save(run)
        finally:
            with _lock:
                _active = False


@router.post("/runs", status_code=202)
def start_run(background_tasks: BackgroundTasks, payload: dict = Body(...)):
    global _active
    if durable.enabled():
        return durable.legacy_start_disabled()
    try:
        month = validate_month(payload.get("month"))
    except RelocationError as exc:
        raise HTTPException(400, str(exc)) from None
    with _lock:
        if _active:
            raise HTTPException(409, "已有搬迁补贴核算正在执行，请等待完成。")
        _active = True
    run = {"runId": uuid4().hex, "month": month, "status": "running", "workerId": WORKER_ID,
           "progress": "正在准备读取北森数据", "createdAt": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")}
    try:
        _save(run)
    except Exception:
        with _lock:
            _active = False
        raise HTTPException(503, "核算批次保存失败，请稍后重试。") from None
    background_tasks.add_task(_work, run)
    return {k: v for k, v in run.items() if k != "workerId"}


@router.get("/runs")
def list_runs():
    if durable.enabled():
        return durable.list_runs(True)
    paths = sorted(RUNS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:30]
    return {"runs": [{k: v for k, v in _read(path.stem).items() if k not in {"result", "attendanceSource"}} for path in paths]}


@router.get("/runs/{run_id}")
def get_run(run_id: str):
    if durable.enabled():
        return durable.get_run(run_id, True)
    return {k: v for k, v in _read(run_id).items() if k != "attendanceSource"}


@router.get("/runs/{run_id}/export")
def export_run(run_id: str):
    if durable.enabled():
        return durable.export_run(run_id, True)
    run = _read(run_id)
    if run["status"] != "completed":
        raise HTTPException(409, "核算尚未完成，无法导出。")
    content, filename = build_workbook(run)
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename=relocation-allowance.xlsx; filename*=UTF-8''{quote(filename)}"})
