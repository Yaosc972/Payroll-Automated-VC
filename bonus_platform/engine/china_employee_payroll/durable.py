"""Payroll API persistence through the existing private OBS/Supabase interface."""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
import re
from uuid import uuid4
from urllib.parse import quote

from fastapi import HTTPException
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool
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


def server_file_transfer():
    # Match company domestic-labor/FBU: browsers use authenticated same-origin
    # APIs; the server transfers private OBS/S3 objects. Vercel keeps direct I/O.
    return enabled() and storage.labor_storage_backend() in {"obs", "s3"}


def _upload_inputs(record, files):
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
    return inputs


def prepare_uploads(activity_id, payload):
    if server_file_transfer():
        raise HTTPException(409, "当前环境通过工作台服务器上传考勤文件。")
    store = Store()
    record = store.get(activity_id)
    inputs = _upload_inputs(record, payload.get("files"))
    # Sign before updating accepted input manifest; failures leave previous inputs intact.
    signed = [storage.create_labor_supabase_signed_upload_for_object(item["objectKey"], file_kind="china-payroll", content_type=XLSX) for item in inputs]
    store.uploads(activity_id, inputs)
    return {"files": signed}


async def accept_server_uploads(activity_id, files):
    store = Store()
    record = await run_in_threadpool(store.get, activity_id)
    # A retried start reopens the accepted job instead of replacing its inputs.
    if record["status"] in {"running", "completed"}:
        return
    if record["subject"] != "wx-meal-allowance":
        raise HTTPException(409, "当前科目无需上传考勤文件。")
    if not 1 <= len(files) <= 20:
        raise HTTPException(400, "请选择 1 至 20 个考勤文件。")
    contents, descriptors, total = [], [], 0
    try:
        for file in files:
            content = await file.read(MAX_FILE_BYTES + 1)
            total += len(content)
            if len(content) > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
                raise HTTPException(400, "单文件上限 50 MB，一次核算总大小上限 100 MB。")
            contents.append(content)
            descriptors.append({"name": file.filename, "size": len(content), "sha256": hashlib.sha256(content).hexdigest()})
        inputs = _upload_inputs(record, descriptors)
        def persist():
            # Publish the manifest only after every object is stored. The worker
            # independently verifies these server-computed lengths and hashes.
            for item, content in zip(inputs, contents):
                storage.put_labor_supabase_private_object(item["objectKey"], content, content_type=XLSX)
            store.uploads(activity_id, inputs)
        await run_in_threadpool(persist)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "考勤文件保存失败，请重新打开活动查看状态后重试。") from None
    finally:
        for file in files:
            await file.close()


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
    if server_file_transfer():
        try:
            content = read_file(manifest)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, "导出文件读取失败，请稍后重试。") from None
        return Response(content, media_type=XLSX,
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(manifest['filename'], safe='')}",
                                 "Cache-Control": "no-store"})
    signed = storage.create_labor_supabase_signed_download(manifest["objectKey"], filename=manifest["filename"])
    return {"downloadUrl": signed["signedUrl"], "filename": manifest["filename"], "sha256": manifest["sha256"], "size": manifest["size"]}


def legacy_start_disabled():
    raise HTTPException(409, "请从活动列表创建活动后开始核算。")


def list_runs(relocation=False):
    records = sorted(Store().records(), key=lambda r: r["createdAt"], reverse=True)
    jobs = [Store().job(r["runId"]) for r in records if r.get("runId") and (r["subject"] == "relocation-allowance") == relocation][:50]
    fields = ("runId", "createdAt", "month", "status", "progress", "progressDetail", "sourceType", "summary")
    return {"runs": [{key: job[key] for key in fields if key in job} for job in jobs]}
