"""Persist meal allowance jobs and their exact calculation source snapshots."""
from __future__ import annotations

import json
import os
import threading
from datetime import date, datetime, time
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from .meal_allowance import REQUIRED_COLUMNS, ParsedAttendance, calculate_meal_allowance
from .relocation import RelocationError, validate_month

WORKER_ID = uuid4().hex
_lock = threading.Lock()
_active = False


def now() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def new_run_id() -> str:
    return "china_employee_payroll_" + datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d_%H%M%S_%f")


def _json_default(value):
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    raise TypeError(f"Unsupported source value: {type(value).__name__}")


def save_json(path: Path, data) -> None:
    """Replace a complete file so concurrent polls never see partial JSON."""
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, default=_json_default)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def run_directory(root: Path, run_id: str) -> Path:
    if Path(run_id).name != run_id or not run_id.startswith("china_employee_payroll_"):
        raise HTTPException(404, "核算批次不存在。")
    folder = root / run_id
    if not folder.is_dir():
        raise HTTPException(404, "核算批次不存在。")
    return folder


def read_metadata(folder: Path) -> dict:
    try:
        metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        raise HTTPException(404, "核算批次不存在。") from None
    metadata.setdefault("runId", folder.name)
    metadata.setdefault("status", "completed" if (folder / "result.json").is_file() else "failed")
    summary = metadata.get("summary", {})
    metadata.setdefault("month", (summary.get("dateStart") or "")[:7])
    metadata.setdefault("sourceType", summary.get("sourceType", "hr"))
    metadata.setdefault("sourceLabel", summary.get("sourceLabel", ""))
    return {key: value for key, value in metadata.items() if key != "workerId"}


def validate_attendance(parsed: ParsedAttendance, month: str | None = None) -> str:
    if month:
        month = validate_month(month)
    if parsed.missing_columns:
        raise RelocationError("考勤文件缺少必需字段：" + "、".join(parsed.missing_columns))
    if not parsed.rows:
        raise RelocationError("所选月份没有可核算的考勤记录。")
    if parsed.duplicate_keys:
        raise RelocationError("考勤数据存在重复的员工和日期，请去重后重新核算。")
    seen = set()
    months = set()
    for row in parsed.rows:
        day = row.get("考勤日期")
        employee_id = str(row.get("工号") or "").strip().lower()
        if not employee_id or not isinstance(day, date):
            raise RelocationError("考勤记录存在缺失的工号或无效的考勤日期，请修正后重新核算。")
        key = (employee_id, day.isoformat()[:10])
        if key in seen:
            raise RelocationError("考勤数据存在重复的员工和日期，请去重后重新核算。")
        seen.add(key)
        months.add(day.strftime("%Y-%m"))
    if month and months != {month}:
        raise RelocationError(f"考勤文件日期与所选核算月份 {month} 不一致，请仅上传该月份的数据。")
    if parsed.source_type == "wx" and len(months) != 1:
        raise RelocationError("WX 考勤文件包含多个月份，请按核算月份分别导入。")
    return month or (next(iter(months)) if len(months) == 1 else "")


def save_source(folder: Path, parsed: ParsedAttendance) -> None:
    save_json(folder / "data-source.json", {
        "columns": REQUIRED_COLUMNS,
        "sourceType": parsed.source_type,
        "sourceLabel": parsed.source_label,
        "rows": [{key: row.get(key, "") for key in REQUIRED_COLUMNS} for row in parsed.rows],
    })


def _work(folder: Path, run: dict) -> None:
    global _active
    try:
        from .meal_beisen import BeisenMealSource

        def progress(update):
            if isinstance(update, dict):
                run["progress"] = update.get("message", "正在读取北森考勤")
                run["progressDetail"] = {key: update[key] for key in ("stage", "completed", "total", "unit") if key in update}
            else:
                run["progress"] = str(update)
            run["progressUpdatedAt"] = now()
            save_json(folder / "metadata.json", run)

        parsed = BeisenMealSource().load(run["month"], progress)
        validate_attendance(parsed, run["month"])
        progress({"message": "正在核对规则并生成餐补结果", "stage": 2, "completed": 0, "total": None, "unit": "条"})
        save_source(folder, parsed)
        result = calculate_meal_allowance(parsed)
        save_json(folder / "result.json", result)
        run.update(status="completed", progress="核算完成", completedAt=now(), calculatedAt=now(),
                   summary=result["summary"], warnings=result["warnings"], sourceLabel=parsed.source_label)
    except RelocationError as exc:
        run.update(status="failed", progress=str(exc), completedAt=now())
    except Exception:
        # Never send raw API responses, headers, credential errors or tracebacks to clients.
        run.update(status="failed", progress="考勤数据读取或核算失败，本次未生成结果，请检查数据后重试。", completedAt=now())
    finally:
        try:
            save_json(folder / "metadata.json", run)
        finally:
            with _lock:
                _active = False


def start_run(root: Path, month, background_tasks) -> dict:
    global _active
    try:
        month = validate_month(month)
    except RelocationError as exc:
        raise HTTPException(400, str(exc)) from None
    with _lock:
        if _active:
            raise HTTPException(409, "已有集团技术部餐补核算正在执行，请等待完成。")
        _active = True
    run = {"runId": new_run_id(), "month": month, "sourceType": "hr", "sourceOrigin": "beisen",
           "sourceLabel": "集团技术部 · 北森考勤", "status": "running", "workerId": WORKER_ID,
           "createdAt": now(), "sourceFiles": [], "progress": "正在匹配集团技术部核算范围",
           "progressDetail": {"stage": 0, "completed": 0, "total": None, "unit": "个组织"}}
    folder = root / run["runId"]
    try:
        folder.mkdir(mode=0o700, parents=True, exist_ok=False)
        save_json(folder / "metadata.json", run)
    except Exception:
        with _lock:
            _active = False
        raise HTTPException(503, "核算批次保存失败，请稍后重试。") from None
    background_tasks.add_task(_work, folder, run)
    return {key: value for key, value in run.items() if key != "workerId"}
