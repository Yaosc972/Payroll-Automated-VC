from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from ...config import OUTPUT_DIR
from ..labor.persistent_storage import (
    create_labor_supabase_signed_download,
    create_labor_supabase_signed_upload_for_object,
    get_labor_supabase_private_object,
    labor_p1_object_key,
    labor_supabase_object_metadata,
    labor_supabase_storage_enabled,
    put_labor_supabase_private_object,
)
from .service import list_tools


TASK_ROOT = OUTPUT_DIR / "overseas_payroll_tasks"
MAX_FILE_BYTES = 40 * 1024 * 1024
MAX_TASK_BYTES = 80 * 1024 * 1024
MAX_FILES = 12
TASK_TTL_DAYS = 14
_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[str, threading.RLock] = {}
_TOOL_INDEX = {tool["id"]: tool for tool in list_tools()}


def _task_lock(task_id: str) -> threading.RLock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(str(task_id), threading.RLock())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _expires_at() -> str:
    return (datetime.now(timezone.utc) + timedelta(days=TASK_TTL_DAYS)).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_id(value: str, prefix: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z_-]+", "_", str(value or "").strip()).strip("_-")
    return normalized if normalized.startswith(prefix) else f"{prefix}_{normalized or uuid4().hex}"


def _task_dir(task_id: str) -> Path:
    return TASK_ROOT / _safe_id(task_id, "payroll_task")


def _task_path(task_id: str) -> Path:
    return _task_dir(task_id) / "task.json"


def _manifest_object_key(owner_user_id: str, task_id: str) -> str:
    return labor_p1_object_key(
        owner_user_id=owner_user_id,
        run_id=task_id,
        file_id="manifest",
        filename="task.json",
        category="payroll-task",
    )


def _input_object_key(owner_user_id: str, task_id: str, file_id: str, filename: str) -> str:
    return labor_p1_object_key(
        owner_user_id=owner_user_id,
        run_id=task_id,
        file_id=file_id,
        filename=filename,
        category="payroll-inputs",
    )


def _output_object_key(owner_user_id: str, task_id: str, output_id: str, filename: str) -> str:
    return labor_p1_object_key(
        owner_user_id=owner_user_id,
        run_id=task_id,
        file_id=output_id,
        filename=filename,
        category="payroll-outputs",
    )


def _write_task(task: dict[str, Any]) -> dict[str, Any]:
    task_id = str(task["id"])
    task["updatedAt"] = _now()
    payload = json.dumps(task, ensure_ascii=False, indent=2).encode("utf-8")
    if labor_supabase_storage_enabled():
        put_labor_supabase_private_object(
            _manifest_object_key(str(task["ownerUserId"]), task_id),
            payload,
            content_type="application/json",
        )
    else:
        destination = _task_path(task_id)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
        temporary.write_bytes(payload)
        os.replace(temporary, destination)
    return dict(task)


def load_task(task_id: str, *, owner_user_id: str = "") -> dict[str, Any]:
    normalized = _safe_id(task_id, "payroll_task")
    if labor_supabase_storage_enabled():
        if not owner_user_id:
            raise PermissionError("读取生产任务必须提供任务归属用户。")
        payload = get_labor_supabase_private_object(_manifest_object_key(owner_user_id, normalized))
        if payload is None:
            raise FileNotFoundError("海外薪资处理任务不存在。")
        task = json.loads(payload.decode("utf-8"))
    else:
        path = _task_path(normalized)
        if not path.is_file():
            raise FileNotFoundError("海外薪资处理任务不存在。")
        task = json.loads(path.read_text(encoding="utf-8"))
    if owner_user_id and str(task.get("ownerUserId") or "") != str(owner_user_id):
        raise FileNotFoundError("海外薪资处理任务不存在。")
    return task


def update_task(
    task_id: str,
    *,
    owner_user_id: str,
    updater: Callable[[dict[str, Any]], dict[str, Any] | None],
) -> dict[str, Any]:
    with _task_lock(task_id):
        current = load_task(task_id, owner_user_id=owner_user_id)
        updated = updater(dict(current))
        return _write_task(updated if isinstance(updated, dict) else current)


def create_task(owner_user_id: str, tool_id: str, raw_files: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    tool = _TOOL_INDEX.get(str(tool_id or ""))
    if not tool:
        raise ValueError("未知海外薪资处理工具。")
    if not isinstance(raw_files, list) or not raw_files:
        raise ValueError("请至少选择一个文件。")
    if len(raw_files) > MAX_FILES:
        raise ValueError(f"一次最多上传 {MAX_FILES} 个文件。")
    if not tool["multiple"] and len(raw_files) != 1:
        raise ValueError(f"{tool['name']} 每次只支持一个文件。")
    specs = []
    total_bytes = 0
    for raw in raw_files:
        filename = Path(str(raw.get("filename") or "input.bin").replace("\\", "/")).name
        suffix = Path(filename).suffix.lower()
        if suffix not in tool["accept"]:
            raise ValueError(f"{filename} 格式不支持，应上传 {'/'.join(tool['accept'])} 文件。")
        size = int(raw.get("sizeBytes") or 0)
        sha256 = str(raw.get("sha256") or "").strip().lower()
        if size <= 0 or size > MAX_FILE_BYTES:
            raise ValueError(f"{filename} 大小无效或超过 40MB 限制。")
        if not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise ValueError(f"{filename} 缺少有效的 SHA-256。")
        total_bytes += size
        if total_bytes > MAX_TASK_BYTES:
            raise ValueError("本次上传文件合计超过 80MB 限制。")
        file_id = f"payroll_file_{uuid4().hex}"
        content_type = str(raw.get("contentType") or "application/octet-stream")[:160]
        specs.append(
            {
                "id": file_id,
                "filename": filename,
                "sizeBytes": size,
                "sha256": sha256,
                "contentType": content_type,
                "status": "pending_upload",
                "objectKey": _input_object_key(owner_user_id, "pending", file_id, filename),
            }
        )
    task_id = f"payroll_task_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}_{uuid4().hex[:8]}"
    for spec in specs:
        spec["objectKey"] = _input_object_key(owner_user_id, task_id, spec["id"], spec["filename"])
    task = {
        "id": task_id,
        "ownerUserId": str(owner_user_id),
        "toolId": tool["id"],
        "toolName": tool["name"],
        "country": tool["country"],
        "status": "uploading",
        "statusLabel": "等待文件上传",
        "files": specs,
        "output": None,
        "jobId": "",
        "error": "",
        "createdAt": _now(),
        "updatedAt": _now(),
        "expiresAt": _expires_at(),
    }
    _write_task(task)
    intents = []
    for spec in specs:
        if labor_supabase_storage_enabled():
            signed = create_labor_supabase_signed_upload_for_object(
                spec["objectKey"],
                file_kind="overseas_payroll_input",
                content_type=spec["contentType"],
            )
        else:
            signed = {
                "signedUrl": f"/api/overseas-payroll/tasks/{task_id}/files/{spec['id']}/content",
                "method": "PUT",
                "headers": {"content-type": spec["contentType"]},
                "objectKey": spec["objectKey"],
                "private": True,
            }
        intents.append({"fileId": spec["id"], "filename": spec["filename"], **signed})
    return task, intents


def local_file_path(task_id: str, file_id: str, *, output: bool = False) -> Path:
    category = "outputs" if output else "inputs"
    return _task_dir(task_id) / category / _safe_id(file_id, "payroll_file")


def store_local_file(task_id: str, file_id: str, content: bytes, *, output: bool = False) -> None:
    destination = local_file_path(task_id, file_id, output=output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    temporary.write_bytes(content)
    os.replace(temporary, destination)


def _observed_input(task: dict[str, Any], file: dict[str, Any]) -> dict[str, Any]:
    if labor_supabase_storage_enabled():
        return labor_supabase_object_metadata(str(file["objectKey"]))
    path = local_file_path(str(task["id"]), str(file["id"]))
    if not path.is_file():
        raise FileNotFoundError("上传文件不存在。")
    return {
        "sizeBytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "contentType": file.get("contentType") or "application/octet-stream",
    }


def finalize_input(task_id: str, file_id: str, *, owner_user_id: str) -> dict[str, Any]:
    def apply(task: dict[str, Any]) -> dict[str, Any]:
        file = next((item for item in task.get("files", []) if item.get("id") == file_id), None)
        if not file:
            raise FileNotFoundError("上传文件记录不存在。")
        observed = _observed_input(task, file)
        if int(observed.get("sizeBytes") or 0) != int(file["sizeBytes"]):
            raise ValueError("上传文件大小与任务清单不一致。")
        observed_sha = str(observed.get("sha256") or "").lower()
        if observed_sha and observed_sha != str(file["sha256"]).lower():
            raise ValueError("上传文件 SHA-256 与任务清单不一致。")
        file["status"] = "uploaded"
        file["uploadedAt"] = _now()
        if all(item.get("status") == "uploaded" for item in task["files"]):
            task["status"] = "ready"
            task["statusLabel"] = "文件已上传，等待进入处理队列"
        return task

    return update_task(task_id, owner_user_id=owner_user_id, updater=apply)


def task_input_downloads(task: dict[str, Any]) -> list[dict[str, Any]]:
    downloads = []
    for file in task.get("files", []):
        if file.get("status") != "uploaded":
            raise ValueError("任务输入文件尚未完成上传。")
        if labor_supabase_storage_enabled():
            signed = create_labor_supabase_signed_download(file["objectKey"], filename=file["filename"], expires_in=600)
            url = signed["signedUrl"]
        else:
            url = f"/api/overseas-payroll/worker/tasks/{task['id']}/files/{file['id']}"
        downloads.append({**file, "downloadUrl": url})
    return downloads


def prepare_output(task_id: str, *, owner_user_id: str, filename: str, size_bytes: int, sha256: str, content_type: str) -> tuple[dict[str, Any], dict[str, Any]]:
    safe_filename = Path(str(filename or "result.xlsx").replace("\\", "/")).name
    digest = str(sha256 or "").strip().lower()
    if int(size_bytes or 0) <= 0 or int(size_bytes) > MAX_TASK_BYTES:
        raise ValueError("输出文件为空或超过 80MB 限制。")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("输出文件缺少有效的 SHA-256。")
    output_id = f"payroll_output_{uuid4().hex}"

    def apply(task: dict[str, Any]) -> dict[str, Any]:
        task["output"] = {
            "id": output_id,
            "filename": safe_filename,
            "sizeBytes": int(size_bytes),
            "sha256": digest,
            "contentType": str(content_type or "application/octet-stream")[:160],
            "objectKey": _output_object_key(owner_user_id, task_id, output_id, safe_filename),
            "status": "pending_upload",
        }
        task["status"] = "processing"
        task["statusLabel"] = "正在保存处理结果"
        return task

    task = update_task(task_id, owner_user_id=owner_user_id, updater=apply)
    output = task["output"]
    if labor_supabase_storage_enabled():
        intent = create_labor_supabase_signed_upload_for_object(
            output["objectKey"],
            file_kind="overseas_payroll_output",
            content_type=output["contentType"],
        )
    else:
        intent = {
            "signedUrl": f"/api/overseas-payroll/worker/tasks/{task_id}/output/{output_id}/content",
            "method": "PUT",
            "headers": {"content-type": output["contentType"]},
            "objectKey": output["objectKey"],
            "private": True,
        }
    return task, {"outputId": output_id, "filename": safe_filename, **intent}


def finalize_output(task_id: str, *, owner_user_id: str, summary: str) -> dict[str, Any]:
    def apply(task: dict[str, Any]) -> dict[str, Any]:
        output = task.get("output") if isinstance(task.get("output"), dict) else None
        if not output:
            raise ValueError("任务没有待确认的输出文件。")
        if labor_supabase_storage_enabled():
            observed = labor_supabase_object_metadata(output["objectKey"])
            observed_size = int(observed.get("sizeBytes") or 0)
            observed_sha = str(observed.get("sha256") or "").lower()
        else:
            path = local_file_path(task_id, output["id"], output=True)
            if not path.is_file():
                raise FileNotFoundError("处理结果尚未上传。")
            observed_size = path.stat().st_size
            observed_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if observed_size != int(output["sizeBytes"]):
            raise ValueError("处理结果大小与任务清单不一致。")
        if observed_sha and observed_sha != str(output["sha256"]).lower():
            raise ValueError("处理结果 SHA-256 与任务清单不一致。")
        output["status"] = "ready"
        output["completedAt"] = _now()
        task["summary"] = str(summary or "处理完成")[:1000]
        task["status"] = "succeeded"
        task["statusLabel"] = "处理完成"
        task["error"] = ""
        return task

    return update_task(task_id, owner_user_id=owner_user_id, updater=apply)


def output_download(task: dict[str, Any]) -> dict[str, Any]:
    output = task.get("output") if isinstance(task.get("output"), dict) else None
    if task.get("status") != "succeeded" or not output or output.get("status") != "ready":
        raise ValueError("处理结果尚未生成。")
    if labor_supabase_storage_enabled():
        return create_labor_supabase_signed_download(output["objectKey"], filename=output["filename"], expires_in=300)
    return {
        "signedUrl": f"/api/overseas-payroll/tasks/{task['id']}/output/content",
        "expiresIn": 300,
        "private": True,
        "filename": output["filename"],
    }
