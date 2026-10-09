"""Payroll API persistence through the existing private OBS/Supabase interface."""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
import re
from uuid import uuid4

from fastapi import HTTPException
from .durable_store import Store, enabled, hosted
from .meal_runs import _json_default
from ..labor import persistent_storage as storage

MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_TOTAL_BYTES = 100 * 1024 * 1024
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def view(record):
    from .activities import _public_creator
    summary = record.get("summary", {})
    return {key: record.get(key, "") for key in ("activityId", "name", "subject", "month", "createdAt", "updatedAt", "runId", "status", "progress")} | {
        "creator": _public_creator(record), "employeeCount": summary.get("employeeCount", 0),
        "amount": summary.get("totalAmount", summary.get("amount", 0)), "attemptCount": len(record.get("attempts", []))}


def object_key(record, filename, category, identifier=None):
    return storage.labor_p1_object_key(owner_user_id=record["creator"]["userId"] or "local-payroll",
        run_id="china-payroll-" + record["activityId"], file_id=identifier or uuid4().hex,
        filename=filename, category="china-payroll-" + category)


def prepare_uploads(activity_id, payload):
    store = Store()
    record = store.get(activity_id)
    files = payload.get("files")
    if not isinstance(files, list) or not 1 <= len(files) <= 20:
        raise HTTPException(400, "请选择 1 至 20 个考勤文件。")
    inputs, total = [], 0
    for file in files:
        if not isinstance(file, dict):
            raise HTTPException(400, "文件信息无效。")
        name, size, digest = file.get("name"), file.get("size"), file.get("sha256")
        if not isinstance(name, str) or Path(name).name != name or not name.lower().endswith((".xlsx", ".xlsm")) or len(name) > 180:
            raise HTTPException(400, "请使用有效的 Excel 文件名。")
        if type(size) is not int or not 0 < size <= MAX_FILE_BYTES or not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest):
            raise HTTPException(400, "文件大小或校验值无效，单文件上限 50 MB。")
        total += size
        inputs.append({"name": name, "size": size, "sha256": digest, "objectKey": object_key(record, name, "inputs")})
    if total > MAX_TOTAL_BYTES:
        raise HTTPException(400, "一次核算的文件总大小不能超过 100 MB。")
    # Sign before updating accepted input manifest; failures leave previous inputs intact.
    signed = [storage.create_labor_supabase_signed_upload_for_object(item["objectKey"], file_kind="china-payroll", content_type=XLSX) for item in inputs]
    store.uploads(activity_id, inputs)
    return {"files": signed}


def start(activity_id):
    # No background task or file parsing in an HTTP request. The worker validates
    # every accepted input's length and digest before it can produce any result.
    return view(Store().enqueue(activity_id))


def put(record, filename, content, category, content_type="application/octet-stream", identifier=None):
    key = object_key(record, filename, category, identifier)
    storage.put_labor_supabase_private_object(key, content, content_type=content_type)
    return {"objectKey": key, "size": len(content), "sha256": hashlib.sha256(content).hexdigest(), "filename": filename}


def read_file(manifest):
    content = storage.get_labor_supabase_private_object(manifest["objectKey"], bypass_cache=True)
    if content is None or len(content) != manifest["size"] or hashlib.sha256(content).hexdigest() != manifest["sha256"]:
        raise HTTPException(409, "保存的核算文件缺失或校验失败，请联系管理员检查存储。")
    return content


def encode(data):
    return gzip.compress(json.dumps(data, ensure_ascii=False, default=_json_default).encode("utf-8"), mtime=0)


def get_run(run_id, relocation=False):
    job = Store().job(run_id)
    if (job["subject"] == "relocation-allowance") != relocation:
        raise HTTPException(404, "核算批次不存在。")
    public = {k: job[k] for k in ("runId", "createdAt", "calculatedAt", "month", "status", "progress", "progressDetail", "sourceType", "summary") if k in job}
    if job["status"] == "completed":
        public.update(json.loads(gzip.decompress(read_file(job["publicResult"]))))
    return public


def export_run(run_id, relocation=False):
    job = Store().job(run_id)
    if (job["subject"] == "relocation-allowance") != relocation:
        raise HTTPException(404, "核算批次不存在。")
    if job["status"] != "completed":
        raise HTTPException(409, "核算尚未完成，无法导出。")
    manifest = job["export"]
    signed = storage.create_labor_supabase_signed_download(manifest["objectKey"], filename=manifest["filename"])
    return {"downloadUrl": signed["signedUrl"], "filename": manifest["filename"], "sha256": manifest["sha256"], "size": manifest["size"]}


def legacy_start_disabled():
    raise HTTPException(409, "请从活动列表创建活动后开始核算。")


def list_runs(relocation=False):
    records = sorted(Store().records(), key=lambda r: r["createdAt"], reverse=True)
    jobs = [Store().job(r["runId"]) for r in records if r.get("runId") and (r["subject"] == "relocation-allowance") == relocation][:50]
    fields = ("runId", "createdAt", "month", "status", "progress", "progressDetail", "sourceType", "summary")
    return {"runs": [{key: job[key] for key in fields if key in job} for job in jobs]}
