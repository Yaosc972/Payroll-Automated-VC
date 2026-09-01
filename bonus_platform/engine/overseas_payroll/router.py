from __future__ import annotations

import asyncio
import base64
import logging
import time
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Body, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from ...auth import current_user_from_request, labor_auth_required, user_can_enter_module
from .service import _legacy_module, list_tools, process_files


router = APIRouter(prefix="/api/overseas-payroll", tags=["overseas-payroll"])
page_router = APIRouter(tags=["overseas-payroll-compat"])
MAX_FILE_BYTES = 40 * 1024 * 1024
MAX_REQUEST_BYTES = 80 * 1024 * 1024
MAX_FILES = 12
FRONTEND_PATH = Path(__file__).resolve().parent / "resources" / "index.html"
logger = logging.getLogger("bonus_platform.overseas_payroll")


def _require_access(request: Request) -> None:
    if not labor_auth_required():
        return
    current = current_user_from_request(request)
    if current is None:
        raise HTTPException(status_code=401, detail="请先登录西格玛工作台。")
    if not user_can_enter_module(current, "overseas"):
        raise HTTPException(status_code=403, detail="当前用户没有海外模块权限。")


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
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


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


@router.post("/tools/{tool_id}/process")
async def process_overseas_payroll_files(
    tool_id: str,
    request: Request,
    files: list[UploadFile] = File(...),
) -> Response:
    _require_access(request)
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
