from __future__ import annotations

import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import logging
import os
import time
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Body, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response

from ...auth import current_user_from_request, labor_auth_required, user_can_enter_module
from ..labor.persistent_storage import labor_supabase_storage_enabled
from .service import _legacy_module, list_tools, process_files
from .tasks import (
    create_task,
    finalize_input,
    finalize_output,
    load_task_inputs,
    load_task,
    local_file_path,
    output_download,
    prepare_output,
    store_local_file,
    store_task_output,
    update_task,
)


router = APIRouter(prefix="/api/overseas-payroll", tags=["overseas-payroll"])
page_router = APIRouter(tags=["overseas-payroll-compat"])
MAX_FILE_BYTES = 40 * 1024 * 1024
MAX_REQUEST_BYTES = 80 * 1024 * 1024
MAX_FILES = 12
RESOURCE_ROOT = Path(__file__).resolve().parent / "resources"
FRONTEND_PATH = RESOURCE_ROOT / "index.html"
ASYNC_ADAPTER_PATH = RESOURCE_ROOT / "async_adapter.js"
logger = logging.getLogger("bonus_platform.overseas_payroll")
_LOCAL_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="overseas-payroll")


def _require_access(request: Request) -> str:
    if not labor_auth_required():
        return "local-default"
    current = current_user_from_request(request)
    if current is None:
        raise HTTPException(status_code=401, detail="请先登录西格玛工作台。")
    if not user_can_enter_module(current, "overseas"):
        raise HTTPException(status_code=403, detail="当前用户没有海外模块权限。")
    user = current.get("user") if isinstance(current.get("user"), dict) else {}
    owner_user_id = str(user.get("id") or "").strip()
    if not owner_user_id:
        raise HTTPException(status_code=401, detail="当前登录用户缺少有效标识。")
    return owner_user_id


def _public_task(task: dict) -> dict:
    files = [
        {key: value for key, value in file.items() if key != "objectKey"}
        for file in task.get("files", [])
        if isinstance(file, dict)
    ]
    output = task.get("output") if isinstance(task.get("output"), dict) else None
    if output:
        output = {key: value for key, value in output.items() if key != "objectKey"}
    return {key: value for key, value in {**task, "files": files, "output": output}.items() if key != "ownerUserId"}


def _public_transfer_intent(intent: dict) -> dict:
    return {
        key: intent[key]
        for key in ("fileId", "outputId", "filename", "signedUrl", "method", "headers", "expiresIn", "private")
        if key in intent
    }


def _legacy_tool_payload() -> list[dict]:
    return [
        {
            "id": tool["id"],
            "name": tool["name"],
            "desc": tool["description"],
            "accept": ",".join(tool["accept"]),
            "enabled": True,
            "en_name": tool["id"].upper().replace("_", " "),
            "version": "v1.0",
            "status_text": "已上线",
            "last_batch": "2026-08",
            "last_result": "-",
            "btn_text": "",
            "category": "工资核算" if tool["id"] == "import_paie" else "海外核算",
            "multi": tool["multiple"],
            "preview": tool["preview"],
            "country": tool["country"],
        }
        for tool in list_tools()
    ]


@page_router.get("/overseas-payroll.html", response_class=HTMLResponse)
def overseas_payroll_page(request: Request) -> HTMLResponse:
    _require_access(request)
    html = FRONTEND_PATH.read_text(encoding="utf-8")
    # These are the same runtime substitutions made by the original server.
    # The checked-in frontend resource remains byte-identical to the handover.
    html = html.replace("__PASSCODE_HINT__", "").replace("__NO_AUTH__", "false")
    html = html.replace("</body>", '<script src="/overseas-payroll-async.js?v=2"></script></body>')
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@page_router.get("/overseas-payroll-async.js")
def overseas_payroll_async_adapter() -> Response:
    return Response(
        ASYNC_ADAPTER_PATH.read_bytes(),
        media_type="application/javascript; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


@page_router.get("/logout")
def overseas_payroll_logout() -> RedirectResponse:
    return RedirectResponse("/api/auth/logout?next=/login.html?next=%2Foverseas-payroll.html", status_code=302)


@page_router.get("/api/tools")
def legacy_overseas_payroll_tools(request: Request) -> dict:
    _require_access(request)
    return {"tools": _legacy_tool_payload()}


def _decode_legacy_payload(payload: dict) -> tuple[list[tuple[str, bytes]], str]:
    raw_files = payload.get("files") if isinstance(payload.get("files"), list) else None
    if raw_files is None:
        raw_files = [{"filename": payload.get("filename", "input.bin"), "data": payload.get("data", "")}]
    if len(raw_files) > MAX_FILES:
        raise ValueError(f"一次最多上传 {MAX_FILES} 个文件。")
    files: list[tuple[str, bytes]] = []
    total_bytes = 0
    for item in raw_files:
        filename = Path(str(item.get("filename") or "input.bin")).name
        try:
            content = base64.b64decode(str(item.get("data") or ""), validate=True)
        except Exception as exc:
            raise ValueError(f"{filename} 文件内容不是有效的 Base64 数据。") from exc
        if len(content) > MAX_FILE_BYTES:
            raise ValueError(f"{filename} 超过 40MB 限制。")
        total_bytes += len(content)
        if total_bytes > MAX_REQUEST_BYTES:
            raise ValueError("本次上传文件合计超过 80MB 限制。")
        files.append((filename, content))
    return files, files[0][0] if files else "input.bin"


@page_router.post("/api/tool/{tool_id}/process")
async def legacy_process_overseas_payroll_files(
    tool_id: str,
    request: Request,
    payload: dict = Body(...),
) -> JSONResponse:
    try:
        _require_access(request)
    except HTTPException as exc:
        return JSONResponse({"ok": False, "error": str(exc.detail)})
    started = time.perf_counter()
    try:
        files, source_filename = _decode_legacy_payload(payload)
        result = await asyncio.to_thread(process_files, tool_id, files)
        content = result.content
        output_filename = result.filename
        legacy = _legacy_module()
        if payload.get("mask") and output_filename.lower().endswith(".xlsx"):
            encoded = base64.b64encode(content).decode("ascii")
            content = base64.b64decode(legacy.mask_xlsx(encoded))
            stem, suffix = Path(output_filename).stem, Path(output_filename).suffix
            output_filename = f"{stem}（脱敏版）{suffix}"
        encoded_output = base64.b64encode(content).decode("ascii")
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return JSONResponse(
            {
                "ok": True,
                "filename": output_filename,
                "data": encoded_output,
                "meta": {"elapsed_ms": elapsed_ms, "in_bytes": sum(len(item[1]) for item in files), "out_bytes": len(content)},
                "country": next((tool["country"] for tool in list_tools() if tool["id"] == tool_id), "通用"),
                "count": legacy._parse_count(result.summary),
                "gross": legacy.compute_gross_from_xlsx(encoded_output) if output_filename.lower().endswith(".xlsx") else None,
                "month": legacy._parse_month(source_filename),
                "people": result.summary,
            }
        )
    except KeyError as exc:
        return JSONResponse({"ok": False, "error": str(exc)})
    except (ValueError, RuntimeError) as exc:
        return JSONResponse({"ok": False, "error": str(exc)})
    except Exception:
        logger.exception("Overseas payroll processing failed for tool %s", tool_id)
        return JSONResponse({"ok": False, "error": "文件解析失败，请确认文件版式或联系维护人员查看服务日志。"})


@router.get("/tools")
def overseas_payroll_tools(request: Request) -> dict:
    _require_access(request)
    return {"tools": list_tools()}


def _run_task(task_id: str, owner_user_id: str, *, cloud: bool) -> dict:
    try:
        task = update_task(
            task_id,
            owner_user_id=owner_user_id,
            updater=lambda current: {
                **current,
                "status": "processing",
                "statusLabel": "云端函数正在处理" if cloud else "本地核对助手正在处理",
                "progress": {"message": "正在下载并解析工资文件" if cloud else "正在解析工资文件"},
            },
        )
        files = load_task_inputs(task)
        result = process_files(str(task["toolId"]), files)
        _, intent = prepare_output(
            task_id,
            owner_user_id=owner_user_id,
            filename=result.filename,
            size_bytes=len(result.content),
            sha256=hashlib.sha256(result.content).hexdigest(),
            content_type=result.media_type,
        )
        store_task_output(
            task_id,
            owner_user_id=owner_user_id,
            output_id=intent["outputId"],
            content=result.content,
        )
        return finalize_output(task_id, owner_user_id=owner_user_id, summary=result.summary)
    except Exception as exc:  # noqa: BLE001 - persisted as a safe user-facing task failure.
        logger.exception("Overseas payroll task failed: %s", task_id)
        try:
            return update_task(
                task_id,
                owner_user_id=owner_user_id,
                updater=lambda current: {
                    **current,
                    "status": "failed",
                    "statusLabel": "处理失败",
                    "error": str(exc)[:500],
                },
            )
        except Exception:
            logger.exception("Failed to persist overseas payroll task failure: %s", task_id)
            raise


def _run_local_task(task_id: str, owner_user_id: str) -> None:
    _run_task(task_id, owner_user_id, cloud=False)


@router.post("/tasks")
def create_overseas_payroll_task(request: Request, payload: dict = Body(...)) -> dict:
    owner_user_id = _require_access(request)
    try:
        task, intents = create_task(owner_user_id, str(payload.get("toolId") or ""), payload.get("files") or [])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"task": _public_task(task), "intents": [_public_transfer_intent(intent) for intent in intents]}


@router.put("/tasks/{task_id}/files/{file_id}/content")
async def upload_local_overseas_payroll_file(task_id: str, file_id: str, request: Request) -> dict:
    owner_user_id = _require_access(request)
    if labor_supabase_storage_enabled():
        raise HTTPException(status_code=404, detail="生产文件必须使用签名地址直传私有存储。")
    task = load_task(task_id, owner_user_id=owner_user_id)
    file = next((item for item in task.get("files", []) if item.get("id") == file_id), None)
    if not file:
        raise HTTPException(status_code=404, detail="上传文件记录不存在。")
    content = await request.body()
    if len(content) > MAX_FILE_BYTES or len(content) != int(file["sizeBytes"]):
        raise HTTPException(status_code=413, detail="上传文件大小与任务清单不一致。")
    store_local_file(task_id, file_id, content)
    return {"ok": True}


@router.post("/tasks/{task_id}/files/{file_id}/finalize")
def finalize_overseas_payroll_file(task_id: str, file_id: str, request: Request) -> dict:
    owner_user_id = _require_access(request)
    try:
        task = finalize_input(task_id, file_id, owner_user_id=owner_user_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"task": _public_task(task)}


@router.post("/tasks/{task_id}/enqueue")
def enqueue_overseas_payroll_task(task_id: str, request: Request) -> dict:
    owner_user_id = _require_access(request)
    task = load_task(task_id, owner_user_id=owner_user_id)
    if task.get("status") not in {"ready", "queued"}:
        raise HTTPException(status_code=409, detail="任务文件尚未全部上传，不能开始处理。")
    if not labor_supabase_storage_enabled():
        if task.get("status") != "queued":
            task = update_task(
                task_id,
                owner_user_id=owner_user_id,
                updater=lambda current: {**current, "status": "queued", "statusLabel": "已进入本地处理队列"},
            )
            _LOCAL_EXECUTOR.submit(_run_local_task, task_id, owner_user_id)
        return {"task": _public_task(task)}
    if task.get("status") == "ready":
        task = update_task(
            task_id,
            owner_user_id=owner_user_id,
            updater=lambda current: {
                **current,
                "status": "queued",
                "statusLabel": "已进入 Vercel 云端处理",
                "jobId": "",
            },
        )
        task = _run_task(task_id, owner_user_id, cloud=True)
    return {"task": _public_task(task)}


@router.get("/tasks/{task_id}")
def get_overseas_payroll_task(task_id: str, request: Request) -> dict:
    owner_user_id = _require_access(request)
    try:
        return _public_task(load_task(task_id, owner_user_id=owner_user_id))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/tasks/{task_id}/download")
def get_overseas_payroll_download(task_id: str, request: Request) -> dict:
    owner_user_id = _require_access(request)
    task = load_task(task_id, owner_user_id=owner_user_id)
    try:
        return output_download(task)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/tasks/{task_id}/output/content")
def download_local_overseas_payroll_output(task_id: str, request: Request) -> FileResponse:
    owner_user_id = _require_access(request)
    if labor_supabase_storage_enabled():
        raise HTTPException(status_code=404, detail="生产结果必须通过签名地址下载。")
    task = load_task(task_id, owner_user_id=owner_user_id)
    output = task.get("output") if isinstance(task.get("output"), dict) else None
    if task.get("status") != "succeeded" or not output:
        raise HTTPException(status_code=409, detail="处理结果尚未生成。")
    path = local_file_path(task_id, output["id"], output=True)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="处理结果文件不存在。")
    return FileResponse(path, filename=output["filename"], media_type=output.get("contentType") or "application/octet-stream")


@router.post("/tools/{tool_id}/process")
async def process_overseas_payroll_files(
    tool_id: str,
    request: Request,
    files: list[UploadFile] = File(...),
) -> Response:
    _require_access(request)
    if os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV"):
        raise HTTPException(status_code=410, detail="生产环境请使用异步任务和私有存储直传接口。")
    if len(files) > MAX_FILES:
        raise HTTPException(status_code=413, detail=f"一次最多上传 {MAX_FILES} 个文件。")
    uploaded: list[tuple[str, bytes]] = []
    total_bytes = 0
    for file in files:
        content = await file.read(MAX_FILE_BYTES + 1)
        if len(content) > MAX_FILE_BYTES:
            raise HTTPException(status_code=413, detail=f"{file.filename or '文件'} 超过 40MB 限制。")
        total_bytes += len(content)
        if total_bytes > MAX_REQUEST_BYTES:
            raise HTTPException(status_code=413, detail="本次上传文件合计超过 80MB 限制。")
        uploaded.append((file.filename or "input.bin", content))
    try:
        result = await asyncio.to_thread(process_files, tool_id, uploaded)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="文件解析失败，请确认文件版式或联系维护人员查看服务日志。") from exc
    encoded_filename = quote(result.filename)
    return Response(
        content=result.content,
        media_type=result.media_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
            "X-Sigma-Process-Summary": quote(result.summary),
        },
    )
