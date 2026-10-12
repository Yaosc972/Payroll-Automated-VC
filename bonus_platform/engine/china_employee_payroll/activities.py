"""Independent payroll activities backed by the existing calculation snapshots."""
from __future__ import annotations

import json
import threading
from typing import Optional
from urllib.parse import urlparse
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5

from fastapi import APIRouter, BackgroundTasks, Body, File, HTTPException, Request, UploadFile

from bonus_platform.auth import current_user_from_request

from . import meal_runs, relocation_router, durable
from .relocation import RelocationError, validate_month

router = APIRouter(prefix="/api/china-employee-payroll/activities", tags=["china-payroll-activities"])
SUBJECTS = {"meal-allowance": "集团技术部餐补", "wx-meal-allowance": "WX 技术部餐补", "relocation-allowance": "ABU 职场搬迁补贴"}
_lock = threading.RLock()
WORKER_ID = uuid4().hex
DEFAULT_AVATAR = "/assets/payroll-default-avatar.png"


def _creator(request):
    current = current_user_from_request(request)
    user = current.get("user", {}) if current else {}
    if not user:
        return {"userId": "", "name": "本地用户", "avatarUrl": DEFAULT_AVATAR}
    return _public_creator({"creator": {"userId": user.get("id", ""), "name": user.get("name", ""), "avatarUrl": user.get("avatarUrl", "")}})


def _public_creator(record):
    creator = record.get("creator") if isinstance(record.get("creator"), dict) else {}
    avatar = str(creator.get("avatarUrl") or "")
    try:
        parsed = urlparse(avatar)
        valid = parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except ValueError:
        valid = False
    if not valid:
        avatar = DEFAULT_AVATAR
    return {"userId": str(creator.get("userId") or ""), "name": str(creator.get("name") or "未记录"), "avatarUrl": avatar}


def _app():
    # The application owns the existing run directory and upload implementation.
    from bonus_platform import app
    return app


def _root():
    root = _app().CHINA_EMPLOYEE_PAYROLL_RUNS_DIR / "activities"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root


def _id(value):
    try:
        if not isinstance(value, str) or UUID(value).hex != value:
            raise ValueError
    except (ValueError, AttributeError):
        raise HTTPException(404, "核算活动不存在。") from None
    return value


def _save(record):
    meal_runs.save_json(_root() / f"{_id(record['activityId'])}.json", record)


def _run(subject, run_id):
    if subject == "relocation-allowance":
        return relocation_router._read(run_id)
    if _app().company_run_storage_enabled("SIGMA_CHINA_EMPLOYEE_STORAGE_BACKEND"):
        folder = _app()._china_employee_meal_run_dir(run_id)
        run = meal_runs.read_metadata(folder)
        run.setdefault("status", "completed")
        run.setdefault("month", str(run.get("summary", {}).get("dateStart", ""))[:7])
        return run
    return meal_runs.read_metadata(meal_runs.run_directory(_app().CHINA_EMPLOYEE_PAYROLL_RUNS_DIR, run_id))


def _legacy_runs():
    root = _app().CHINA_EMPLOYEE_PAYROLL_RUNS_DIR
    if _app().company_run_storage_enabled("SIGMA_CHINA_EMPLOYEE_STORAGE_BACKEND"):
        for run_id in _app().list_company_run_ids("china-employee-meal"):
            content = _app().load_company_run_file("china-employee-meal", run_id, "metadata.json")
            if not content:
                continue
            run = json.loads(content)
            run.setdefault("runId", run_id)
            run.setdefault("status", "completed")
            run.setdefault("month", str(run.get("summary", {}).get("dateStart", ""))[:7])
            yield "wx-meal-allowance" if run.get("sourceType") == "wx" else "meal-allowance", run
        return
    for folder in root.glob("china_employee_payroll_*"):
        if not folder.is_dir():
            continue
        try:
            run = meal_runs.read_metadata(folder)
        except HTTPException:
            continue
        yield "wx-meal-allowance" if run.get("sourceType") == "wx" else "meal-allowance", run
    for path in relocation_router.RUNS_DIR.glob("*.json"):
        try:
            yield "relocation-allowance", relocation_router._read(path.stem)
        except (HTTPException, ValueError, KeyError):
            continue


def _legacy(subject, run):
    month = run.get("month", "")
    label = f"{month[:4]}年{int(month[5:])}月" if len(month) == 7 else "历史核算"
    return {"activityId": uuid5(NAMESPACE_URL, f"china-payroll/{subject}/{run['runId']}").hex,
            "name": f"{label} {SUBJECTS[subject]}", "subject": subject, "month": month,
            "createdAt": run.get("createdAt", ""), "updatedAt": run.get("createdAt", ""),
            "runId": run["runId"], "attempts": [run["runId"]], "legacy": True, "creator": run.get("creator")}


def _record(activity_id):
    path = _root() / f"{_id(activity_id)}.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    for subject, run in _legacy_runs():
        record = _legacy(subject, run)
        if record["activityId"] == activity_id:
            return record
    raise HTTPException(404, "核算活动不存在。")


def _view(record, run=None):
    status, progress, summary = record.get("status", "draft"), record.get("progress", ""), {}
    if record.get("runId"):
        try:
            run = run or _run(record["subject"], record["runId"])
            status, progress = run["status"], run.get("progress", "")
            summary = run.get("summary") or run.get("result", {}).get("summary", {})
        except HTTPException:
            status, progress = "failed", "该活动的核算文件缺失，请重新核算。"
    return {key: record.get(key, "") for key in ("activityId", "name", "subject", "month", "createdAt", "updatedAt", "runId")} | {
        "status": status, "progress": progress, "creator": _public_creator(record), "employeeCount": summary.get("employeeCount", 0),
        "amount": summary.get("totalAmount", summary.get("amount", 0)), "attemptCount": len(record.get("attempts", []))}


@router.post("", status_code=201)
def create_activity(request: Request, payload: dict = Body(...)):
    subject = payload.get("subject")
    if subject not in SUBJECTS:
        raise HTTPException(400, "请选择有效的核算科目。")
    try:
        month = validate_month(payload.get("month"))
    except RelocationError as exc:
        raise HTTPException(400, str(exc)) from None
    name = payload.get("name", "")
    if not isinstance(name, str) or len(name.strip()) > 120:
        raise HTTPException(400, "活动名称最多 120 个字。")
    name = name.strip() or f"{month[:4]}年{int(month[5:])}月 {SUBJECTS[subject]}"
    activity_id = _id(payload["requestId"]) if "requestId" in payload else uuid4().hex
    if durable.enabled():
        record = {"activityId": activity_id, "name": name, "subject": subject, "month": month,
                  "createdAt": meal_runs.now(), "updatedAt": meal_runs.now(), "status": "draft", "runId": "", "attempts": [], "creator": _creator(request)}
        return durable.view(durable.Store().create(record))
    with _lock:
        path = _root() / f"{activity_id}.json"
        if path.is_file():
            record = _record(activity_id)
            if (record["subject"], record["month"], record["name"]) != (subject, month, name):
                raise HTTPException(409, "该创建请求已用于另一核算活动。")
            return _view(record)
        record = {"activityId": activity_id, "name": name, "subject": subject, "month": month,
                  "createdAt": meal_runs.now(), "updatedAt": meal_runs.now(), "status": "draft", "runId": "", "attempts": [], "creator": _creator(request)}
        _save(record)
        return _view(record)


@router.get("")
def list_activities(search: str = "", subject: str = "", month: str = "", status: str = "", page: int = 1, page_size: int = 20):
    if page < 1 or not 1 <= page_size <= 100:
        raise HTTPException(400, "分页参数不正确。")
    records = durable.Store().records() if durable.enabled() else []
    for path in ([] if durable.enabled() else _root().glob("*.json")):
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except (ValueError, OSError):
            continue
    linked = {(r["subject"], run_id) for r in records for run_id in r.get("attempts", [r.get("runId")]) if run_id}
    activities = [(durable.view(r) if durable.enabled() else _view(r)) for r in records]
    activities.extend(_view(_legacy(s, r), r) for s, r in _legacy_runs() if (s, r["runId"]) not in linked)
    activities = [a for a in activities if (not search or search.casefold() in f"{a['name']} {a['creator']['name']}".casefold())
                  and (not subject or a["subject"] == subject) and (not month or a["month"] == month)
                  and (not status or a["status"] == status)]
    activities.sort(key=lambda a: (a["createdAt"], a["activityId"]), reverse=True)
    total = len(activities)
    page = min(page, max(1, (total + page_size - 1) // page_size))
    return {"activities": activities[(page - 1) * page_size:page * page_size], "total": total, "page": page, "pageSize": page_size}


@router.get("/{activity_id}")
def get_activity(activity_id: str):
    if durable.enabled():
        try:
            return durable.view(durable.Store().get(_id(activity_id)))
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
    return _view(_record(activity_id))


@router.post("/{activity_id}/start")
async def start_activity(activity_id: str, background_tasks: BackgroundTasks, attendance_files: Optional[list[UploadFile]] = File(None)):
    if durable.enabled():
        if attendance_files:
            if not durable.server_file_transfer():
                raise HTTPException(400, "请使用考勤文件直传后开始核算。")
            await durable.accept_server_uploads(_id(activity_id), attendance_files)
        try:
            return durable.start(_id(activity_id))
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            record = _record(activity_id)
            if not record.get("legacy"):
                raise
            return _view(record)
    with _lock:
        record = _record(activity_id)
        view = _view(record)
        # Refreshes, reconnects and double clicks reopen the accepted run.
        if view["status"] in {"running", "completed"}:
            return view
        if record["subject"] == "wx-meal-allowance" and not attendance_files:
            raise HTTPException(400, "请上传所选月份的 WX 考勤文件。")
        record.update(status="running", runId="", workerId=WORKER_ID, updatedAt=meal_runs.now(), progress="正在开始核算")
        _save(record)
    try:
        if record["subject"] == "relocation-allowance":
            run = relocation_router.start_run(background_tasks, {"month": record["month"]})
        elif record["subject"] == "meal-allowance":
            run = meal_runs.start_run(_app().CHINA_EMPLOYEE_PAYROLL_RUNS_DIR, record["month"], background_tasks)
        else:
            run = await _app().calculate_china_employee_meal_allowance(attendance_files, "wx", record["month"])
        with _lock:
            record.update(runId=run["runId"], status=run["status"], updatedAt=meal_runs.now())
            record.setdefault("attempts", []).append(run["runId"])
            _save(record)
        return _view(record)
    except Exception as exc:
        with _lock:
            record.update(status="failed", progress=exc.detail if isinstance(exc, HTTPException) and isinstance(exc.detail, str) else "核算未完成，请重试。", updatedAt=meal_runs.now())
            _save(record)
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(503, "核算活动暂时不可用，请重新打开活动查看状态。") from None


@router.get("/config/upload")
def upload_config():
    return {"directUpload": durable.enabled() and not durable.server_file_transfer()}


@router.post("/{activity_id}/uploads")
def prepare_activity_upload(activity_id: str, payload: dict = Body(...)):
    if not durable.enabled():
        raise HTTPException(409, "当前环境未启用文件直传。")
    return durable.prepare_uploads(_id(activity_id), payload)
