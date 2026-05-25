from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
import shutil
from tempfile import NamedTemporaryFile
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import DEFAULT_IMPORT_TEMPLATE, DEFAULT_RULE_WORKBOOK, EXPORT_DIR, MAX_PREVIEW_ROWS, ensure_data_files
from .engine.calculator import calculate
from .engine.compare import build_difference_report
from .engine.rules import load_rulebook
from .engine.runs import (
    attach_file_record,
    create_run_dir,
    get_run_dir,
    list_run_metadata,
    load_metadata,
    new_run_id,
    rule_info,
    run_file_url,
    save_metadata,
    update_metadata,
)
from .engine.table_data import build_table_data, load_table_data, merge_diff_rows, save_table_data
from .engine.workbook_io import build_final_workbook, build_pending_workbook, build_result_workbook, read_import_rows


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_data_files()
    yield


app = FastAPI(title="招聘奖金与内推奖金核算平台", lifespan=lifespan)
STATIC_DIR = Path(__file__).resolve().parent / "static"


@app.get("/api/health")
def health() -> dict:
    ensure_data_files()
    return {"status": "ok", "rule_workbook": str(DEFAULT_RULE_WORKBOOK)}


@app.post("/api/calculate")
async def calculate_bonus(
    file: UploadFile = File(...),
) -> dict:
    if not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="请上传 Excel 文件（.xlsx 或 .xlsm）。")
    if not DEFAULT_RULE_WORKBOOK.exists():
        raise HTTPException(status_code=500, detail=f"找不到规则模板：{DEFAULT_RULE_WORKBOOK}")

    upload_path = await _save_upload(file)

    try:
        rows = read_import_rows(upload_path)
        rules = load_rulebook(DEFAULT_RULE_WORKBOOK)
        result = calculate(rows, rules)
        output_path = _output_path(file.filename)
        pending_path = _output_path(file.filename, suffix="待确认表")
        build_result_workbook(result, output_path)
        if result.pending_confirmations:
            build_pending_workbook(result, pending_path)
        else:
            pending_path = None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"计算失败：{exc}") from exc
    finally:
        upload_path.unlink(missing_ok=True)

    payload = _calculation_payload(result)
    return {
        **payload,
        "downloadUrl": f"/api/download/{output_path.name}",
        "pendingDownloadUrl": f"/api/download/{pending_path.name}" if pending_path else "",
        "filename": output_path.name,
    }


@app.post("/api/runs/calculate")
async def calculate_run(
    file: UploadFile = File(...),
) -> dict:
    if not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="请上传 Excel 文件（.xlsx 或 .xlsm）。")
    if not DEFAULT_RULE_WORKBOOK.exists():
        raise HTTPException(status_code=500, detail=f"找不到规则模板：{DEFAULT_RULE_WORKBOOK}")

    temp_upload_path = await _save_upload(file)
    try:
        rows = read_import_rows(temp_upload_path)
        rules = load_rulebook(DEFAULT_RULE_WORKBOOK)
        result = calculate(rows, rules)
        run_id = new_run_id(result.month)
        run_dir = create_run_dir(run_id)
        input_path = run_dir / _safe_output_name(file.filename, "原始导入")
        shutil.move(str(temp_upload_path), input_path)
        output_path = run_dir / _safe_output_name(file.filename, "初算结果")
        pending_path = run_dir / _safe_output_name(file.filename, "待确认表")
        build_result_workbook(result, output_path)
        if result.pending_confirmations:
            build_pending_workbook(result, pending_path)
        else:
            pending_path = None
        save_table_data(run_dir, build_table_data(run_id, result))
    except ValueError as exc:
        temp_upload_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        temp_upload_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"计算失败：{exc}") from exc

    payload = _calculation_payload(result)
    status = "待确认" if payload["pendingCount"] else "已初算"
    files = {
        "input": attach_file_record(run_id, input_path, "原始导入"),
        "initialResult": attach_file_record(run_id, output_path, "初算结果"),
        "pending": attach_file_record(run_id, pending_path, "待确认表"),
    }
    metadata = save_metadata(
        run_dir,
        {
            "id": run_id,
            "month": result.month,
            "status": status,
            "sourceFilename": file.filename,
            "files": files,
            "ruleInfo": rule_info(),
            **payload,
            "downloadUrl": files["initialResult"]["downloadUrl"],
            "pendingDownloadUrl": files["pending"].get("downloadUrl", ""),
        },
    )
    return metadata


@app.get("/api/runs")
def list_runs() -> dict:
    return {"runs": list_run_metadata()}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict:
    try:
        return load_metadata(get_run_dir(run_id))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="批次不存在。") from exc


@app.get("/api/runs/{run_id}/table-data")
def get_run_table_data(run_id: str) -> dict:
    try:
        return load_table_data(get_run_dir(run_id))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="批次不存在。") from exc


@app.post("/api/runs/{run_id}/finalize")
async def finalize_run(
    run_id: str,
    confirmation_file: UploadFile = File(...),
) -> dict:
    if not confirmation_file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="确认结果请上传 Excel 文件（.xlsx 或 .xlsm）。")
    try:
        run_dir = get_run_dir(run_id)
        metadata = load_metadata(run_dir)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="批次不存在。") from exc

    initial_path = Path(metadata["files"]["initialResult"]["path"])
    if not initial_path.exists():
        raise HTTPException(status_code=404, detail="批次初算结果不存在，无法生成最终结果。")

    confirmation_path = await _save_upload_to(confirmation_file, run_dir / _safe_output_name(confirmation_file.filename, "确认结果"))
    final_path = run_dir / _safe_output_name(metadata.get("sourceFilename") or "初算结果.xlsx", "最终结果")
    try:
        build_final_workbook(initial_path, confirmation_path, final_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"生成最终结果失败：{exc}") from exc

    files = dict(metadata.get("files", {}))
    files["confirmation"] = attach_file_record(run_id, confirmation_path, "确认结果")
    files["finalResult"] = attach_file_record(run_id, final_path, "最终结果")
    updated = update_metadata(
        run_id,
        {
            "status": "已最终确认",
            "files": files,
            "finalDownloadUrl": files["finalResult"]["downloadUrl"],
        },
    )
    return updated


@app.post("/api/runs/{run_id}/compare")
async def compare_run(
    run_id: str,
    offline_file: UploadFile = File(...),
) -> dict:
    if not offline_file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="线下复核表请上传 Excel 文件（.xlsx 或 .xlsm）。")
    try:
        run_dir = get_run_dir(run_id)
        metadata = load_metadata(run_dir)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="批次不存在。") from exc

    source_record = metadata.get("files", {}).get("finalResult") or metadata.get("files", {}).get("initialResult")
    if not source_record:
        raise HTTPException(status_code=404, detail="批次结果不存在，无法生成差异报告。")

    offline_path = await _save_upload_to(offline_file, run_dir / _safe_output_name(offline_file.filename, "线下复核表"))
    diff_path = run_dir / _safe_output_name(metadata.get("sourceFilename") or "核算结果.xlsx", "差异报告")
    try:
        metrics = build_difference_report(Path(source_record["path"]), offline_path, diff_path)
        merge_diff_rows(run_dir, metrics)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"生成差异报告失败：{exc}") from exc

    files = dict(metadata.get("files", {}))
    files["offlineReview"] = attach_file_record(run_id, offline_path, "线下复核表")
    files["diffReport"] = attach_file_record(run_id, diff_path, "差异报告")
    updated = update_metadata(
        run_id,
        {
            "status": "已生成差异报告",
            "files": files,
            "diffMetrics": metrics,
            "diffDownloadUrl": files["diffReport"]["downloadUrl"],
        },
    )
    return updated


@app.post("/api/finalize")
async def finalize_bonus(
    initial_result_file: UploadFile = File(...),
    confirmation_file: UploadFile = File(...),
) -> dict:
    for upload, label in ((initial_result_file, "初算结果"), (confirmation_file, "确认结果")):
        if not upload.filename.lower().endswith((".xlsx", ".xlsm")):
            raise HTTPException(status_code=400, detail=f"{label}请上传 Excel 文件（.xlsx 或 .xlsm）。")

    initial_path = await _save_upload(initial_result_file)
    confirmation_path = await _save_upload(confirmation_file)
    try:
        output_path = _output_path(initial_result_file.filename, suffix="最终结果")
        build_final_workbook(initial_path, confirmation_path, output_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"生成最终结果失败：{exc}") from exc
    finally:
        initial_path.unlink(missing_ok=True)
        confirmation_path.unlink(missing_ok=True)

    return {
        "filename": output_path.name,
        "downloadUrl": f"/api/download/{output_path.name}",
    }


@app.get("/api/download/{filename}")
def download(filename: str) -> FileResponse:
    path = EXPORT_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="文件不存在或已被清理。")
    return FileResponse(path, filename=filename, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/api/runs/{run_id}/download/{filename}")
def download_run_file(run_id: str, filename: str) -> FileResponse:
    try:
        run_dir = get_run_dir(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="批次不存在。") from exc
    path = run_dir / Path(filename).name
    if not path.exists():
        raise HTTPException(status_code=404, detail="文件不存在或已被清理。")
    return FileResponse(path, filename=path.name, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/api/template")
def download_template() -> FileResponse:
    if not DEFAULT_IMPORT_TEMPLATE.exists():
        raise HTTPException(status_code=404, detail="模板文件不存在。")
    return FileResponse(
        DEFAULT_IMPORT_TEMPLATE,
        filename=DEFAULT_IMPORT_TEMPLATE.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _output_path(original_name: str, suffix: str = "平台计算结果") -> Path:
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    stem = Path(original_name).stem.replace(" ", "_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return EXPORT_DIR / f"{stem}_{suffix}_{timestamp}.xlsx"


async def _save_upload(file: UploadFile) -> Path:
    with NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(await file.read())
        return Path(tmp.name)


async def _save_upload_to(file: UploadFile, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(await file.read())
    return path


def _safe_output_name(original_name: str, suffix: str) -> str:
    stem = Path(original_name).stem.replace(" ", "_")
    stem = "".join(char if char.isalnum() or char in "_-" else "_" for char in stem).strip("_") or "workbook"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return f"{stem}_{suffix}_{timestamp}.xlsx"


def _calculation_payload(result) -> dict:
    recruitment_total = round(sum(row.get("合计发放", 0) for row in result.recruitment_summary), 2)
    referral_total = round(sum(row.get("合计发放", 0) for row in result.referral_summary), 2)
    pending_total = round(sum(row.get("建议发放金额", 0) for row in result.pending_confirmations), 2)
    preview = [
        {
            "姓名": detail.name,
            "工号": detail.employee_no,
            "职级": detail.grade,
            "ABC类别": detail.category,
            "招聘渠道": detail.channel,
            "招聘人入职1月奖金": detail.recruiter_1m_bonus,
            "内推入职1月奖金": detail.referral_1m_bonus,
            "异常提示": "；".join(detail.exceptions),
        }
        for detail in result.details[:MAX_PREVIEW_ROWS]
    ]
    return {
        "month": result.month,
        "importedRows": len(result.details),
        "recruitmentTotal": recruitment_total,
        "referralTotal": referral_total,
        "exceptionCount": len(result.exceptions),
        "pendingCount": len(result.pending_confirmations),
        "pendingTotal": pending_total,
        "detailPreview": preview,
        "pendingConfirmations": result.pending_confirmations[:MAX_PREVIEW_ROWS],
        "exceptions": result.exceptions[:MAX_PREVIEW_ROWS],
    }


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
