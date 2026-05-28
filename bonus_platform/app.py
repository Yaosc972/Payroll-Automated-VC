from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
import shutil
from tempfile import NamedTemporaryFile
from fastapi import BackgroundTasks, Body, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import AI_CONFIG, DEFAULT_IMPORT_TEMPLATE, DEFAULT_RULE_WORKBOOK, EXPORT_DIR, MAX_PREVIEW_ROWS, ensure_data_files
from .engine.calculator import calculate
from .engine.compare import build_difference_report
from .engine.labor.compare import compare_labor_items
from .engine.labor.extract import extract_invoice_items
from .engine.labor.report import build_labor_report
from .engine.labor.runs import (
    attach_labor_file,
    create_labor_run,
    get_labor_run_dir,
    list_labor_metadata,
    load_labor_metadata,
    safe_labor_filename,
    update_labor_metadata,
)
from .engine.labor.workbook import list_workbook_sheets, read_workbook_rows, suggest_mapping
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


@app.get("/api/labor/runs")
def list_labor_runs() -> dict:
    return {"runs": list_labor_metadata()}


@app.post("/api/labor/runs")
def create_labor_run_endpoint(payload: dict = Body(...)) -> dict:
    supplier = str(payload.get("supplier_name") or payload.get("supplierName") or "").strip()
    period_start = str(payload.get("period_start") or payload.get("periodStart") or "").strip()
    period_end = str(payload.get("period_end") or payload.get("periodEnd") or "").strip()
    if not supplier:
        raise HTTPException(status_code=400, detail="请填写供应商名称。")
    if not period_start or not period_end:
        raise HTTPException(status_code=400, detail="请填写账期开始和结束日期。")
    return create_labor_run(
        {
            "supplierName": supplier,
            "periodStart": period_start,
            "periodEnd": period_end,
            "currency": str(payload.get("currency") or "USD").strip() or "USD",
            "notes": str(payload.get("notes") or ""),
        }
    )


@app.get("/api/labor/runs/{run_id}")
def get_labor_run(run_id: str) -> dict:
    try:
        return load_labor_metadata(get_labor_run_dir(run_id))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="劳务核对批次不存在。") from exc


@app.post("/api/labor/runs/{run_id}/files")
async def upload_labor_files(
    run_id: str,
    pdf_files: list[UploadFile] = File(...),
    workbook_file: UploadFile = File(...),
) -> dict:
    try:
        run_dir = get_labor_run_dir(run_id)
        metadata = load_labor_metadata(run_dir)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="劳务核对批次不存在。") from exc
    if not pdf_files:
        raise HTTPException(status_code=400, detail="请至少上传一张 PDF 发票。")
    if not workbook_file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="线下账单请上传 Excel 文件（.xlsx 或 .xlsm）。")
    pdf_records = []
    for upload in pdf_files:
        if not upload.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="供应商发票请上传 PDF 文件。")
        path = await _save_upload_to(upload, run_dir / safe_labor_filename(upload.filename))
        pdf_records.append(attach_labor_file(run_id, path, "PDF发票"))
    workbook_path = await _save_upload_to(workbook_file, run_dir / safe_labor_filename(workbook_file.filename))
    files = dict(metadata.get("files", {}))
    files["pdfInvoices"] = pdf_records
    files["workbook"] = attach_labor_file(run_id, workbook_path, "线下账单")
    return update_labor_metadata(run_id, {"status": "已上传文件", "files": files})


@app.get("/api/labor/runs/{run_id}/workbook-sheets")
def labor_workbook_sheets(run_id: str) -> dict:
    metadata = _labor_metadata_or_404(run_id)
    workbook_path = _labor_workbook_path(metadata)
    try:
        return {"sheets": list_workbook_sheets(workbook_path)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"读取 Excel 工作表失败：{exc}") from exc


@app.post("/api/labor/runs/{run_id}/field-suggestions")
def labor_field_suggestions(run_id: str, payload: dict = Body(...)) -> dict:
    metadata = _labor_metadata_or_404(run_id)
    workbook_path = _labor_workbook_path(metadata)
    sheet_name = str(payload.get("sheet_name") or payload.get("sheetName") or "").strip()
    if not sheet_name:
        raise HTTPException(status_code=400, detail="请选择 Excel 工作表。")
    try:
        return suggest_mapping(workbook_path, sheet_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/labor/runs/{run_id}/mapping")
def save_labor_mapping(run_id: str, payload: dict = Body(...)) -> dict:
    sheet_name = str(payload.get("sheet_name") or payload.get("sheetName") or "").strip()
    mapping = payload.get("mapping") or {}
    if not sheet_name:
        raise HTTPException(status_code=400, detail="请选择 Excel 工作表。")
    for field in ("name", "hours", "amount"):
        if not mapping.get(field):
            raise HTTPException(status_code=400, detail="字段映射缺少姓名、工时或金额。")
    return update_labor_metadata(run_id, {"status": "已确认字段", "workbookSheet": sheet_name, "excelMapping": mapping})


@app.post("/api/labor/runs/{run_id}/extract-and-compare")
def extract_and_compare_labor_run(run_id: str, background_tasks: BackgroundTasks) -> dict:
    metadata = _labor_metadata_or_404(run_id)
    mapping = metadata.get("excelMapping") or {}
    sheet_name = metadata.get("workbookSheet") or ""
    if not sheet_name or not mapping:
        raise HTTPException(status_code=400, detail="请先确认 Excel 工作表和字段映射。")
    pdf_paths = [Path(record["path"]) for record in metadata.get("files", {}).get("pdfInvoices", []) if record.get("path")]
    if not pdf_paths:
        raise HTTPException(status_code=400, detail="请先上传 PDF 发票。")
    queued = update_labor_metadata(
        run_id,
        {
            "status": "抽取中",
            "errorMessage": "",
            "diffDownloadUrl": "",
        },
    )
    background_tasks.add_task(_run_labor_extract_compare, run_id)
    return queued


def _run_labor_extract_compare(run_id: str) -> None:
    try:
        _perform_labor_extract_compare(run_id)
    except ValueError as exc:
        update_labor_metadata(run_id, {"status": "抽取失败", "errorMessage": str(exc)})
    except Exception as exc:
        update_labor_metadata(run_id, {"status": "抽取失败", "errorMessage": f"生成劳务核对结果失败：{exc}"})


def _perform_labor_extract_compare(run_id: str) -> dict:
    metadata = _labor_metadata_or_404(run_id)
    run_dir = get_labor_run_dir(run_id)
    mapping = metadata.get("excelMapping") or {}
    sheet_name = metadata.get("workbookSheet") or ""
    workbook_path = _labor_workbook_path(metadata)
    pdf_paths = [Path(record["path"]) for record in metadata.get("files", {}).get("pdfInvoices", []) if record.get("path")]
    try:
        pdf_rows = extract_invoice_items(
            pdf_paths,
            AI_CONFIG,
            supplier=metadata.get("supplierName", ""),
            period_start=metadata.get("periodStart", ""),
            period_end=metadata.get("periodEnd", ""),
            currency=metadata.get("currency", ""),
        )
        if not pdf_rows:
            raise ValueError("PDF 未抽取出员工明细。请确认发票是可复制文本 PDF，或启用 AI/OCR 后重试。")
        excel_rows = read_workbook_rows(workbook_path, sheet_name, mapping)
        comparison = compare_labor_items(
            pdf_rows,
            excel_rows,
            amount_tolerance=AI_CONFIG["amount_tolerance"],
            hours_tolerance=AI_CONFIG["hours_tolerance"],
            confidence_threshold=AI_CONFIG["confidence_threshold"],
        )
        extraction_quality = _labor_extraction_quality(comparison["summary"])
        extraction_quality["retryAttempted"] = False
        extraction_quality["retryApplied"] = False
        if extraction_quality["level"] == "warning":
            retry_config = dict(AI_CONFIG)
            retry_config["cache_enabled"] = False
            retry_pdf_rows = extract_invoice_items(
                pdf_paths,
                retry_config,
                supplier=metadata.get("supplierName", ""),
                period_start=metadata.get("periodStart", ""),
                period_end=metadata.get("periodEnd", ""),
                currency=metadata.get("currency", ""),
                expected_rows=_expected_labor_rows(excel_rows),
            )
            if retry_pdf_rows:
                retry_comparison = compare_labor_items(
                    retry_pdf_rows,
                    excel_rows,
                    amount_tolerance=AI_CONFIG["amount_tolerance"],
                    hours_tolerance=AI_CONFIG["hours_tolerance"],
                    confidence_threshold=AI_CONFIG["confidence_threshold"],
                )
                retry_quality = _labor_extraction_quality(retry_comparison["summary"])
                extraction_quality["retryAttempted"] = True
                if _labor_quality_score(retry_quality, retry_comparison["summary"]) < _labor_quality_score(extraction_quality, comparison["summary"]):
                    pdf_rows = retry_pdf_rows
                    comparison = retry_comparison
                    extraction_quality = retry_quality
                    extraction_quality["retryAttempted"] = True
                    extraction_quality["retryApplied"] = True
                else:
                    extraction_quality["retryApplied"] = False
        report_path = run_dir / safe_labor_filename("海外劳务工报账核对报告.xlsx", "差异报告")
        build_labor_report(report_path, comparison, pdf_rows, excel_rows, mapping)
    except ValueError:
        raise
    files = dict(metadata.get("files", {}))
    files["diffReport"] = attach_labor_file(run_id, report_path, "差异报告")
    updated = update_labor_metadata(
        run_id,
        {
            "status": "已生成差异报告",
            "files": files,
            "comparisonSummary": comparison["summary"],
            "comparisonRows": comparison["rows"],
            "candidateMatches": comparison.get("candidateMatches", []),
            "extractionQuality": extraction_quality,
            "pdfExtractedRows": [row.to_dict() for row in pdf_rows],
            "excelRows": [row.to_dict() for row in excel_rows],
            "diffDownloadUrl": files["diffReport"]["downloadUrl"],
        },
    )
    return updated


def _expected_labor_rows(excel_rows) -> list[dict]:
    return [
        {
            "employee_id": row.employee_id,
            "employee_name": row.employee_name_raw,
            "hours": row.hours,
            "amount": row.amount,
            "currency": row.currency,
            "source_ref": row.source_page_or_row,
        }
        for row in excel_rows
    ]


def _labor_quality_score(quality: dict, summary: dict) -> tuple:
    return (
        1 if quality.get("level") == "warning" else 0,
        len(quality.get("issues") or []),
        int(summary.get("exceptionCount") or 0),
        int(summary.get("unmatchedPdfCount") or 0) + int(summary.get("unmatchedExcelCount") or 0),
        abs(float(summary.get("amountDeltaTotal") or 0)),
    )


def _labor_extraction_quality(summary: dict) -> dict:
    pdf_count = int(summary.get("pdfEmployeeCount") or 0)
    excel_count = int(summary.get("excelEmployeeCount") or 0)
    unmatched_pdf = int(summary.get("unmatchedPdfCount") or 0)
    unmatched_excel = int(summary.get("unmatchedExcelCount") or 0)
    pdf_hours = float(summary.get("pdfHoursTotal") or 0)
    excel_hours = float(summary.get("excelHoursTotal") or 0)
    pdf_amount = float(summary.get("pdfAmountTotal") or 0)
    excel_amount = float(summary.get("excelAmountTotal") or 0)

    issues = []
    if excel_count and abs(pdf_count - excel_count) / excel_count > 0.10:
        issues.append(f"PDF员工数 {pdf_count} 与 Excel员工数 {excel_count} 偏差超过 10%。")
    if excel_count and (unmatched_pdf + unmatched_excel) / excel_count > 0.25:
        issues.append(f"未匹配员工 {unmatched_pdf + unmatched_excel} 人，超过 Excel人数的 25%。")
    if excel_hours and abs(pdf_hours - excel_hours) / excel_hours > 0.10:
        issues.append(f"总工时差异 {round(pdf_hours - excel_hours, 2)}，超过 Excel总工时的 10%。")
    if excel_amount:
        amount_drift = abs(pdf_amount - excel_amount) / excel_amount
        if amount_drift > 0.10:
            issues.append(f"总金额差异 {round(pdf_amount - excel_amount, 2)}，超过 Excel总金额的 10%。")

    if issues:
        return {
            "level": "warning",
            "message": "抽取质量存在风险，请复核 PDF 抽取明细后再使用差异报告。",
            "issues": issues,
        }
    return {"level": "ok", "message": "抽取质量检查通过。", "issues": []}


@app.get("/api/labor/runs/{run_id}/download/{filename}")
def download_labor_file(run_id: str, filename: str) -> FileResponse:
    try:
        run_dir = get_labor_run_dir(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="劳务核对批次不存在。") from exc
    path = run_dir / Path(filename).name
    if not path.exists():
        raise HTTPException(status_code=404, detail="文件不存在或已被清理。")
    return FileResponse(path, filename=path.name)


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


def _labor_metadata_or_404(run_id: str) -> dict:
    try:
        return load_labor_metadata(get_labor_run_dir(run_id))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="劳务核对批次不存在。") from exc


def _labor_workbook_path(metadata: dict) -> Path:
    workbook_record = metadata.get("files", {}).get("workbook") or {}
    path = workbook_record.get("path")
    if not path:
        raise HTTPException(status_code=400, detail="请先上传线下账单 Excel。")
    workbook_path = Path(path)
    if not workbook_path.exists():
        raise HTTPException(status_code=404, detail="线下账单文件不存在。")
    return workbook_path


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
