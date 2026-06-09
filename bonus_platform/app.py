from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
import logging
import re
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
from pathlib import Path
import shutil
from tempfile import NamedTemporaryFile
from fastapi import BackgroundTasks, Body, FastAPI, File, HTTPException, UploadFile
from openpyxl import load_workbook

logger = logging.getLogger("bonus_platform.labor")
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import AI_CONFIG, DEFAULT_IMPORT_TEMPLATE, DEFAULT_RULE_WORKBOOK, EXPORT_DIR, MAX_PREVIEW_ROWS, SUPPLIER_PROFILES_OUTPUT_DIR, DOMESTIC_LABOR_RUNS_DIR, FBU_PERFORMANCE_RUNS_DIR, ensure_data_files
from .engine.domestic_labor.parser import PayrollDataLoader
from .engine.domestic_labor.engines import QuanQinJiangEngine, CanBuEngine, WaiSuBuTieEngine, GongLingJiangEngine
from .engine.domestic_labor.templates import generate_template, get_template_info, ENGINE_TEMPLATES
from .engine.domestic_labor.exporter import ExcelExporter
from .engine.domestic_labor.runs import (
    create_payroll_run, update_payroll_metadata, load_payroll_metadata,
    list_payroll_metadata, get_payroll_run_dir, attach_payroll_file, safe_payroll_filename,
)
from .engine.calculator import calculate
from .engine.compare import build_difference_report
from .engine.labor.compare import compare_labor_items, compare_by_warehouse
from .engine.labor.extract import extract_invoice_items, quick_extract_totals, _warehouse_id_from_filename, _warehouse_id_from_text
from .engine.labor.quality import calculate_extraction_quality, calculate_quality_score, build_reconciliation_diagnostics
from .engine.labor.report import build_labor_report
from .engine.labor.profiles import (
    generate_profile_from_extraction,
    save_supplier_profile,
    record_profile_failure,
    reset_profile_failure,
    resolve_supplier_profile,
)

# --- FBU Performance engine imports ---
from .engine.fbu_performance.parser import FBUPerformanceParser
from .engine.fbu_performance.runs import FBURosterStore, FBURunManager


SUPPORTING_PDF_RE = re.compile(r"(?:supplement|support|time\s*card|timecard|detail|backup|appendix)", re.IGNORECASE)
NON_PAYABLE_PDF_TYPES = {"supporting", "attachment"}


def _non_payable_pdf_names(pdf_totals: list[dict]) -> set[str]:
    has_payable_invoice = any(
        float(total.get("total_amount") or 0) > 0
        and str(total.get("pdf_type") or "") not in NON_PAYABLE_PDF_TYPES
        for total in pdf_totals
    )
    if not has_payable_invoice:
        return set()
    return {
        str(total.get("source_file") or "")
        for total in pdf_totals
        if str(total.get("pdf_type") or "") in NON_PAYABLE_PDF_TYPES
        or (
            float(total.get("total_amount") or 0) == 0
            and SUPPORTING_PDF_RE.search(str(total.get("source_file") or ""))
        )
    }


def _warehouse_id_from_text_path(pdf_path: Path, diff_wh: list) -> bool:
    """检查 PDF 内容中的仓库号是否在差异仓库列表中。

    用于文件名无法提取仓库号时（如 US ELogistics 格式），从 PDF 内容中匹配。
    """
    try:
        from .engine.labor.extract import _extract_pdf_pages
        pages = _extract_pdf_pages([pdf_path], max_pages=1)
        if pages:
            wh = _warehouse_id_from_text(pages[0].get("text", ""))
            return wh in diff_wh
    except Exception:
        pass
    return False
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
from .engine.table_data import build_final_table_data, build_table_data, load_table_data, merge_diff_rows, save_table_data
from .engine.workbook_io import build_final_workbook, build_pending_workbook, build_result_workbook, read_import_rows


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_data_files()
    _recover_stuck_labor_runs()
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
        metadata = load_labor_metadata(get_labor_run_dir(run_id))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="劳务核对批次不存在。") from exc
    return _check_stale_extracting(metadata)


@app.post("/api/labor/runs/{run_id}/files")
async def upload_labor_files(
    run_id: str,
    pdf_files: list[UploadFile] = File(...),
    workbook_files: list[UploadFile] = File(...),
) -> dict:
    try:
        run_dir = get_labor_run_dir(run_id)
        metadata = load_labor_metadata(run_dir)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="劳务核对批次不存在。") from exc
    if not pdf_files:
        raise HTTPException(status_code=400, detail="请至少上传一张 PDF 发票。")
    if not workbook_files:
        raise HTTPException(status_code=400, detail="请上传线下账单 Excel 文件。")
    _EXCEL_EXTS = (".xlsx", ".xlsm", ".xls")
    pdf_records = []
    for upload in pdf_files:
        if not upload.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="供应商发票请上传 PDF 文件。")
        path = await _save_upload_to(upload, run_dir / safe_labor_filename(upload.filename))
        pdf_records.append(attach_labor_file(run_id, path, "PDF发票"))
    workbook_records = []
    for upload in workbook_files:
        if not upload.filename.lower().endswith(_EXCEL_EXTS):
            raise HTTPException(status_code=400, detail=f"线下账单请上传 Excel 文件（.xlsx / .xlsm / .xls）。收到：{upload.filename}")
        path = await _save_upload_to(upload, run_dir / safe_labor_filename(upload.filename))
        workbook_records.append(attach_labor_file(run_id, path, "线下账单"))
    files = dict(metadata.get("files", {}))
    files["pdfInvoices"] = pdf_records
    files["workbooks"] = workbook_records
    # 兼容旧字段：第一个文件也写入 workbook
    if workbook_records:
        files["workbook"] = workbook_records[0]
    return update_labor_metadata(run_id, {"status": "已上传文件", "files": files})


@app.get("/api/labor/runs/{run_id}/workbook-sheets")
def labor_workbook_sheets(run_id: str) -> dict:
    metadata = _labor_metadata_or_404(run_id)
    paths = _labor_workbook_paths(metadata)
    try:
        if len(paths) == 1:
            return {"sheets": list_workbook_sheets(paths[0])}
        # 多文件：返回去重的 sheet 名（用户按名称选择，读取时合并所有文件）
        all_sheets: list[str] = []
        seen: set[str] = set()
        for p in paths:
            for name in list_workbook_sheets(p):
                if name not in seen:
                    seen.add(name)
                    all_sheets.append(name)
        return {"sheets": all_sheets, "fileCount": len(paths)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"读取 Excel 工作表失败：{exc}") from exc


@app.post("/api/labor/runs/{run_id}/field-suggestions")
def labor_field_suggestions(run_id: str, payload: dict = Body(...)) -> dict:
    metadata = _labor_metadata_or_404(run_id)
    paths = _labor_workbook_paths(metadata)
    sheet_name = str(payload.get("sheet_name") or payload.get("sheetName") or "").strip()
    if not sheet_name:
        raise HTTPException(status_code=400, detail="请选择 Excel 工作表。")
    try:
        # 从第一个文件读取字段映射建议（所有文件结构应一致）
        return suggest_mapping(paths[0], sheet_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/labor/runs/{run_id}/mapping")
def save_labor_mapping(run_id: str, payload: dict = Body(...)) -> dict:
    sheet_name = str(payload.get("sheet_name") or payload.get("sheetName") or "").strip()
    mapping = payload.get("mapping") or {}
    manual_name_mapping = payload.get("manualNameMapping") or payload.get("manual_name_mapping") or payload.get("manualMapping") or {}
    if not sheet_name:
        raise HTTPException(status_code=400, detail="请选择 Excel 工作表。")
    for field in ("name", "hours", "amount"):
        if not mapping.get(field):
            raise HTTPException(status_code=400, detail="字段映射缺少姓名、工时或金额。")
    return update_labor_metadata(
        run_id,
        {
            "status": "已确认字段",
            "workbookSheet": sheet_name,
            "excelMapping": mapping,
            "manualNameMapping": manual_name_mapping,
        },
    )


@app.post("/api/labor/runs/{run_id}/extract-and-compare")
async def extract_and_compare_labor_run(run_id: str) -> dict:
    metadata = _labor_metadata_or_404(run_id)
    mapping = metadata.get("excelMapping") or {}
    manual_name_mapping = metadata.get("manualNameMapping") or {}
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
            "stage": "初始化",
            "errorMessage": "",
            "diffDownloadUrl": "",
        },
    )
    # 在独立线程中运行，不阻塞事件循环
    asyncio.get_event_loop().run_in_executor(None, _run_labor_extract_compare, run_id)
    return queued


def _run_labor_extract_compare(run_id: str) -> None:
    try:
        logger.info(f"[{run_id}] === 抽取任务启动 ===")
        _perform_labor_extract_compare(run_id)
        logger.info(f"[{run_id}] === 抽取任务完成 ===")
    except ValueError as exc:
        logger.error(f"[{run_id}] 抽取失败(ValueError): {exc}")
        update_labor_metadata(run_id, {"status": "抽取失败", "stage": "错误", "errorMessage": str(exc)})
    except Exception as exc:
        logger.error(f"[{run_id}] 抽取失败(Exception): {exc}", exc_info=True)
        update_labor_metadata(run_id, {"status": "抽取失败", "stage": "错误", "errorMessage": f"生成劳务核对结果失败：{exc}"})


def _aggregate_excel_rows(excel_rows: list) -> list:
    """按员工名聚合 Excel 行（合并同一员工的多天记录）。

    如果同一员工只出现一次，保持原样。
    如果同一员工出现多次，合并 hours 和 amount。
    """
    from collections import defaultdict
    from .engine.labor.models import LaborLineItem

    groups = defaultdict(list)
    for row in excel_rows:
        key = (row.employee_name_raw or "").strip().lower()
        groups[key].append(row)

    if all(len(v) == 1 for v in groups.values()):
        return excel_rows  # 无需聚合

    aggregated = []
    for key, rows in groups.items():
        if len(rows) == 1:
            aggregated.append(rows[0])
        else:
            # 合并：取第一条的元数据，hours/amount 求和
            base = rows[0]
            total_hours = sum(r.hours for r in rows)
            total_amount = sum(r.amount for r in rows)
            merged = LaborLineItem(
                employee_name_raw=base.employee_name_raw,
                employee_id=base.employee_id,
                hours=round(total_hours, 2),
                amount=round(total_amount, 2),
                currency=base.currency,
                source_file=base.source_file,
                source_page_or_row=base.source_page_or_row,
                source_type=base.source_type,
                warehouse_id=base.warehouse_id,
                supplier=base.supplier,
                period_start=base.period_start,
                period_end=base.period_end,
                confidence=base.confidence,
                evidence_text=base.evidence_text,
            )
            aggregated.append(merged)

    logger.info(f"Excel 行聚合: {len(excel_rows)} 行 → {len(aggregated)} 行 ({len(excel_rows) - len(aggregated)} 条合并)")
    return aggregated


def _perform_labor_extract_compare(run_id: str) -> dict:
    metadata = _labor_metadata_or_404(run_id)
    run_dir = get_labor_run_dir(run_id)
    mapping = metadata.get("excelMapping") or {}
    sheet_name = metadata.get("workbookSheet") or ""
    workbook_paths = _labor_workbook_paths(metadata)
    pdf_paths = [Path(record["path"]) for record in metadata.get("files", {}).get("pdfInvoices", []) if record.get("path")]
    supplier = metadata.get("supplierName", "")
    period_start = metadata.get("periodStart", "")
    period_end = metadata.get("periodEnd", "")
    currency = metadata.get("currency", "")
    manual_name_mapping = metadata.get("manualNameMapping") or {}

    try:
        # [F] Excel 解析（多文件合并）
        logger.info(f"[{run_id}] [F] 开始解析 Excel: {len(workbook_paths)} 个文件, 工作表: {sheet_name}")
        update_labor_metadata(run_id, {"stage": "解析 Excel 账单"})
        excel_rows = []
        for wb_path in workbook_paths:
            rows = read_workbook_rows(wb_path, sheet_name, mapping)
            logger.info(f"[{run_id}] [F]   {wb_path.name}: {len(rows)} 行")
            excel_rows.extend(rows)
        logger.info(f"[{run_id}] [F] Excel 解析完成: 共 {len(excel_rows)} 行")
        # 聚合同一员工的多天记录
        excel_rows = _aggregate_excel_rows(excel_rows)
        excel_warehouse_data = [
            {"warehouse_id": row.warehouse_id, "hours": row.hours, "amount": row.amount, "employee_name": row.employee_name_raw}
            for row in excel_rows
        ]

        # === Stage 1: Quick total extraction ===
        logger.info(f"[{run_id}] === Stage 1: 快速总金额抽取 ({len(pdf_paths)} 个 PDF) ===")
        update_labor_metadata(run_id, {"stage": "Stage 1: 快速抽取总金额"})
        pdf_totals = quick_extract_totals(pdf_paths, AI_CONFIG, supplier=supplier)
        for t in pdf_totals:
            logger.info(f"[{run_id}]   PDF总金额: {t.get('source_file','?')} -> {t.get('total_amount', 0)}")
        all_totals_zero = all(float(t.get("total_amount") or 0) == 0 for t in pdf_totals)
        if all_totals_zero:
            logger.warning(f"[{run_id}] 所有 PDF 总金额为 0，将进入 Stage 2 全量抽取")
            pdf_totals = []  # Fall through to full extraction
        non_payable_pdf_names = _non_payable_pdf_names(pdf_totals)
        payable_pdf_totals = [t for t in pdf_totals if str(t.get("source_file") or "") not in non_payable_pdf_names]
        warehouse_comparison = compare_by_warehouse(
            pdf_totals=payable_pdf_totals,
            excel_rows_with_warehouse=excel_warehouse_data,
            amount_tolerance=AI_CONFIG["amount_tolerance"],
            manual_name_mapping=manual_name_mapping,
        )

        pdf_rows = []
        comparison = {"summary": {}, "rows": [], "candidateMatches": []}
        extraction_quality = {"level": "ok", "message": "总金额核对通过，无需抽取员工明细。", "issues": [], "retryAttempted": False, "retryApplied": False}
        stage2_quality_issues: list[str] = []

        if warehouse_comparison["summary"]["totalPassed"]:
            logger.info(f"[{run_id}] ✅ Stage 1 通过: 总金额一致，无需抽取员工明细")
            update_labor_metadata(run_id, {"stage": "Stage 1 通过: 总金额一致"})
        else:
            # === Stage 2: Full extraction for diff warehouses ===
            logger.info(f"[{run_id}] === Stage 2: 总金额不一致，进入员工明细抽取 ===")
            update_labor_metadata(run_id, {"stage": "Stage 2: 抽取员工明细"})
            diff_wh = warehouse_comparison["summary"].get("diffWarehouses", [])
            if not diff_wh and not all_totals_zero:
                # Totals don't match but no warehouses identified — shouldn't happen
                all_totals_zero = True
            if all_totals_zero:
                # Quick extraction failed, extract all employees
                diff_wh = ["*"]
            if diff_wh:
                # Only extract employees from diff warehouse PDFs (unless all totals failed)
                if "*" not in diff_wh:
                    # 先尝试从文件名提取仓库号匹配
                    filtered_pdf_paths = [p for p in pdf_paths if _warehouse_id_from_filename(p.name) in diff_wh]
                    # 如果文件名无法匹配任何仓库号（如 US ELogistics 格式），回退到从 PDF 内容提取
                    if not filtered_pdf_paths:
                        filtered_pdf_paths = [p for p in pdf_paths if _warehouse_id_from_text_path(p, diff_wh)]
                    zero_total_pdf_names = {
                        str(total.get("source_file") or "")
                        for total in pdf_totals
                        if float(total.get("total_amount") or 0) == 0
                    }
                    non_payable_pdf_paths = [p for p in pdf_paths if p.name in non_payable_pdf_names]
                    if non_payable_pdf_paths:
                        issue = (
                            "检测到支持材料/附件 PDF，未计入应付金额明细抽取，避免与主发票重复计入。"
                            f" 文件: {', '.join(p.name for p in non_payable_pdf_paths)}"
                        )
                        stage2_quality_issues.append(issue)
                        logger.warning(f"[{run_id}] {issue}")
                    zero_total_pdf_paths = [p for p in pdf_paths if p.name in zero_total_pdf_names and p not in filtered_pdf_paths]
                    zero_total_pdf_paths = [p for p in zero_total_pdf_paths if p.name not in non_payable_pdf_names]
                    if zero_total_pdf_paths:
                        filtered_pdf_paths.extend(zero_total_pdf_paths)
                        issue = (
                            "部分 PDF 快速总金额为 0，已纳入 Stage 2 明细抽取，避免扫描件或未知版式被仓库过滤遗漏。"
                            f" 文件: {', '.join(p.name for p in zero_total_pdf_paths)}"
                        )
                        stage2_quality_issues.append(issue)
                        logger.warning(f"[{run_id}] {issue}")
                    filtered_excel_rows = [r for r in excel_rows if r.warehouse_id in diff_wh]
                    if not filtered_pdf_paths:
                        filtered_pdf_paths = pdf_paths
                        filtered_excel_rows = excel_rows
                        issue = (
                            "无法将异常仓库映射到具体 PDF，已全量抽取 PDF 并按全量 Excel 比对。"
                            f" 异常仓库: {', '.join(diff_wh)}"
                        )
                        stage2_quality_issues.append(issue)
                        logger.warning(f"[{run_id}] {issue}")
                else:
                    filtered_pdf_paths = pdf_paths
                    filtered_excel_rows = excel_rows

                logger.info(f"[{run_id}] [C/D] 开始抽取员工明细: {len(filtered_pdf_paths)} 个 PDF, {len(filtered_excel_rows)} 行 Excel")
                update_labor_metadata(run_id, {"stage": f"Stage 2: AI 抽取 {len(filtered_pdf_paths)} 个 PDF"})
                pdf_rows = extract_invoice_items(
                    filtered_pdf_paths, AI_CONFIG,
                    supplier=supplier, period_start=period_start, period_end=period_end, currency=currency,
                    expected_rows=_expected_labor_rows(filtered_excel_rows),
                )
                logger.info(f"[{run_id}] [C/D] 员工明细抽取完成: {len(pdf_rows)} 条记录")

                # === Profile 失效检测 ===
                _supplier_profile = resolve_supplier_profile(supplier, AI_CONFIG.get("supplier_profiles_path"))
                if _supplier_profile and _supplier_profile.key != "default":
                    _profile_file = Path(AI_CONFIG.get("supplier_profiles_path", "")) / f"{_supplier_profile.key}.json"
                    if _profile_file.exists():
                        if not pdf_rows:
                            record_profile_failure(_profile_file)
                        else:
                            reset_profile_failure(_profile_file)

                if not pdf_rows:
                    raise ValueError("PDF 未抽取出员工明细。请确认发票是可复制文本 PDF，或启用 AI/OCR 后重试。")

                logger.info(f"[{run_id}] [G] 开始数据比对: PDF {len(pdf_rows)} 行 vs Excel {len(filtered_excel_rows)} 行")
                update_labor_metadata(run_id, {"stage": "比对员工明细"})
                comparison = compare_labor_items(
                    pdf_rows, filtered_excel_rows,
                    amount_tolerance=AI_CONFIG["amount_tolerance"],
                    hours_tolerance=AI_CONFIG["hours_tolerance"],
                    confidence_threshold=AI_CONFIG["confidence_threshold"],
                    manual_name_mapping=manual_name_mapping,
                )
                extraction_quality = calculate_extraction_quality(pdf_rows, comparison["summary"], confidence_threshold=AI_CONFIG["confidence_threshold"])
                extraction_quality["retryAttempted"] = False
                extraction_quality["retryApplied"] = False
                _append_quality_issues(extraction_quality, stage2_quality_issues)
                logger.info(f"[{run_id}] [G] 比对完成: 质量={extraction_quality['level']}, 问题={len(extraction_quality.get('issues',[]))}条")

                should_retry_quality = extraction_quality["level"] in ("warning", "critical")
                if should_retry_quality and any("快速总金额为 0" in issue for issue in stage2_quality_issues):
                    should_retry_quality = False
                    logger.info(f"[{run_id}] 已包含扫描/未知版式 PDF 补充抽取，跳过质量重试以避免重复大图 AI 请求")
                # 硬编码阈值：PDF > 2 个时全量重试耗时过长（每个 PDF 需 AI 处理 30-60s），
                # 超过此阈值跳过重试，避免整体超时。可通过 AI_MAX_RETRY_PDFS 环境变量覆盖。
                if should_retry_quality and len(filtered_pdf_paths) > 2:
                    should_retry_quality = False
                    logger.info(f"[{run_id}] PDF 数量 {len(filtered_pdf_paths)} > 2，跳过质量重试以避免超时")

                if should_retry_quality:
                    logger.info(f"[{run_id}] 质量为 {extraction_quality['level']}，尝试重试...")
                    update_labor_metadata(run_id, {"stage": "重试抽取（质量优化）"})
                    original_rows = list(pdf_rows)
                    original_comparison = dict(comparison)
                    original_quality = dict(extraction_quality)

                    # 先尝试局部重试低置信度行
                    low_conf_rows = extraction_quality.get("lowConfidenceRows") or []
                    partial_retry_done = False
                    # 硬编码阈值：低置信度行占比 ≤ 50% 时才尝试局部重试，
                    # 超过则认为整体质量太差，直接走全量重试。
                    if low_conf_rows and len(low_conf_rows) <= len(pdf_rows) * 0.5:
                        target_names = list({row["employee_name_raw"] for row in low_conf_rows if row.get("employee_name_raw")})
                        partial_result = _retry_low_confidence_rows(
                            filtered_pdf_paths, low_conf_rows, AI_CONFIG,
                            supplier=supplier, period_start=period_start, period_end=period_end, currency=currency,
                            expected_rows=_expected_labor_rows(filtered_excel_rows),
                        )
                        # 硬编码阈值：局部重试结果行数需 ≥ 原始行数的 80%，否则认为结果不完整，降级到全量重试。
                        if partial_result and len(partial_result) >= len(pdf_rows) * 0.8:
                            partial_comparison = compare_labor_items(
                                partial_result, filtered_excel_rows,
                                amount_tolerance=AI_CONFIG["amount_tolerance"],
                                hours_tolerance=AI_CONFIG["hours_tolerance"],
                                confidence_threshold=AI_CONFIG["confidence_threshold"],
                                manual_name_mapping=manual_name_mapping,
                            )
                            partial_quality = calculate_extraction_quality(partial_result, partial_comparison["summary"], confidence_threshold=AI_CONFIG["confidence_threshold"])
                            if calculate_quality_score(partial_quality, partial_comparison["summary"]) < calculate_quality_score(extraction_quality, comparison["summary"]):
                                # 合并：保留原始高置信度行 + 局部重试的低置信度员工结果
                                high_conf_rows = [r for r in pdf_rows if r.confidence >= AI_CONFIG["confidence_threshold"]]
                                low_conf_names = {name.lower() for name in target_names}
                                retry_low_conf_rows = [r for r in partial_result if r.employee_name_raw.lower() in low_conf_names]
                                merged_rows = high_conf_rows + retry_low_conf_rows
                                merged_comparison = compare_labor_items(
                                    merged_rows, filtered_excel_rows,
                                    amount_tolerance=AI_CONFIG["amount_tolerance"],
                                    hours_tolerance=AI_CONFIG["hours_tolerance"],
                                    confidence_threshold=AI_CONFIG["confidence_threshold"],
                                    manual_name_mapping=manual_name_mapping,
                                )
                                merged_quality = calculate_extraction_quality(merged_rows, merged_comparison["summary"], confidence_threshold=AI_CONFIG["confidence_threshold"])
                                if calculate_quality_score(merged_quality, merged_comparison["summary"]) < calculate_quality_score(extraction_quality, comparison["summary"]):
                                    logger.info(f"[{run_id}] 局部重试改善了质量，采用合并结果（高置信度 {len(high_conf_rows)} 行 + 重试 {len(retry_low_conf_rows)} 行）")
                                    pdf_rows = merged_rows
                                    comparison = merged_comparison
                                    extraction_quality = merged_quality
                                    extraction_quality["retryAttempted"] = True
                                    extraction_quality["retryApplied"] = True
                                    partial_retry_done = True
                                else:
                                    logger.info(f"[{run_id}] 局部重试合并后未改善质量，降级到全量重试")
                            else:
                                logger.info(f"[{run_id}] 局部重试未改善质量，降级到全量重试")

                    # 局部重试不够好或没有低置信度行，走全量重试
                    if not partial_retry_done:
                        pdf_rows, comparison, extraction_quality = _retry_if_better(
                            filtered_pdf_paths, pdf_rows, filtered_excel_rows, extraction_quality, comparison,
                            manual_name_mapping=manual_name_mapping,
                            supplier=supplier, period_start=period_start, period_end=period_end, currency=currency,
                        )

                # === 自动生成供应商 Profile ===
                if extraction_quality.get("level") == "ok" and pdf_rows:
                    try:
                        profile_data = generate_profile_from_extraction(
                            supplier=supplier,
                            pdf_rows=pdf_rows,
                            extraction_quality_level=extraction_quality.get("level", "ok"),
                        )
                        profile_path = save_supplier_profile(profile_data, Path(SUPPLIER_PROFILES_OUTPUT_DIR))
                        logger.info(f"[{run_id}] 已自动生成供应商 Profile: {profile_path.name}")
                    except Exception as exc:
                        logger.warning(f"[{run_id}] 供应商 Profile 自动生成失败: {exc}")

                # Re-run warehouse comparison with full employee rows for Tier 3
                # Pass pdf_totals to preserve correct total amounts for non-diff warehouses
                warehouse_comparison = compare_by_warehouse(
                    pdf_totals=payable_pdf_totals,
                    pdf_rows=pdf_rows,
                    excel_rows_with_warehouse=excel_warehouse_data,
                    amount_tolerance=AI_CONFIG["amount_tolerance"],
                    hours_tolerance=AI_CONFIG["hours_tolerance"],
                    confidence_threshold=AI_CONFIG["confidence_threshold"],
                    manual_name_mapping=manual_name_mapping,
                )

                # Recalculate quality with warehouse comparison data, preserving retry flags
                retry_attempted = extraction_quality.get("retryAttempted", False)
                retry_applied = extraction_quality.get("retryApplied", False)
                extraction_quality = calculate_extraction_quality(pdf_rows, comparison["summary"], warehouse_comparison, confidence_threshold=AI_CONFIG["confidence_threshold"])
                extraction_quality["retryAttempted"] = retry_attempted
                extraction_quality["retryApplied"] = retry_applied
                _append_quality_issues(extraction_quality, stage2_quality_issues)

        logger.info(f"[{run_id}] 生成差异报告...")
        update_labor_metadata(run_id, {"stage": "生成报告"})
        report_path = run_dir / safe_labor_filename("海外劳务工报账核对报告.xlsx", "差异报告")
        build_labor_report(report_path, comparison, pdf_rows, excel_rows, mapping, warehouse_comparison, extraction_quality)
        logger.info(f"[{run_id}] 报告已生成: {report_path.name}")
    except ValueError:
        raise
    files = dict(metadata.get("files", {}))
    files["diffReport"] = attach_labor_file(run_id, report_path, "差异报告")

    # 计算结论级别
    conclusion = _build_conclusion(warehouse_comparison, comparison, extraction_quality, amount_tolerance=AI_CONFIG["amount_tolerance"])
    reconciliation_diagnostics = build_reconciliation_diagnostics(
        pdf_totals=payable_pdf_totals,
        comparison_summary=comparison["summary"],
        warehouse_comparison=warehouse_comparison,
        amount_tolerance=AI_CONFIG["amount_tolerance"],
    )

    updated = update_labor_metadata(
        run_id,
        {
            "status": "已生成差异报告",
            "files": files,
            "comparisonSummary": {**comparison["summary"], **conclusion},
            "comparisonRows": comparison["rows"],
            "candidateMatches": comparison.get("candidateMatches", []),
            "warehouseComparison": warehouse_comparison,
            "extractionQuality": extraction_quality,
            "reconciliationDiagnostics": reconciliation_diagnostics,
            "pdfExtractedRows": [row.to_dict() for row in pdf_rows],
            "excelRows": [row.to_dict() for row in excel_rows],
            "diffDownloadUrl": files["diffReport"]["downloadUrl"],
        },
    )
    return updated


def _append_quality_issues(extraction_quality: dict, issues: list[str]) -> None:
    if not issues:
        return
    existing = extraction_quality.setdefault("issues", [])
    for issue in issues:
        if issue not in existing:
            existing.append(issue)


def _retry_low_confidence_rows(
    pdf_paths: list,
    low_confidence_rows: list,
    ai_config: dict,
    supplier: str,
    period_start: str,
    period_end: str,
    currency: str,
    expected_rows: list | None = None,
) -> list | None:
    """对低置信度行做局部重试。

    从 low_confidence_rows 提取员工名单，用 retry_mode 重新抽取。
    返回合并后的新结果，失败时返回 None（降级到全量重试）。
    """
    if not low_confidence_rows:
        return None

    target_names = list({row["employee_name_raw"] for row in low_confidence_rows if row.get("employee_name_raw")})
    if not target_names:
        return None

    logger.info(f"局部重试: {len(target_names)} 个低置信度员工: {target_names[:10]}")
    try:
        retry_config = dict(ai_config)
        retry_config["cache_enabled"] = False
        retry_config["parallel_max_workers"] = 1
        retry_config["parallel_image_render_workers"] = 1

        fresh_paths = [Path(str(p)) for p in pdf_paths]
        for p in fresh_paths:
            if not p.exists():
                logger.warning(f"局部重试跳过: 文件不存在 {p}")
                return None

        retry_rows = extract_invoice_items(
            fresh_paths, retry_config,
            supplier=supplier, period_start=period_start, period_end=period_end, currency=currency,
            expected_rows=expected_rows,
            retry_mode=True,
            target_names=target_names,
        )
        if not retry_rows:
            logger.info("局部重试返回 0 条，降级到全量重试")
            return None

        logger.info(f"局部重试完成: {len(retry_rows)} 条")
        return retry_rows
    except Exception as exc:
        logger.warning(f"局部重试异常，降级到全量重试: {exc}")
        return None


def _retry_if_better(pdf_paths, pdf_rows, excel_rows, extraction_quality, comparison, **kwargs):
    manual_name_mapping = kwargs.pop("manual_name_mapping", None)
    retry_config = dict(AI_CONFIG)
    retry_config["cache_enabled"] = False
    # Serial execution for retry stability
    retry_config["parallel_max_workers"] = 1
    retry_config["parallel_image_render_workers"] = 1
    # Ensure PDF paths are fresh (not from a closed file handle)
    fresh_pdf_paths = [Path(str(p)) for p in pdf_paths]
    for p in fresh_pdf_paths:
        if not p.exists():
            logger.error(f"重试失败: PDF 文件不存在: {p}")
            extraction_quality["retryAttempted"] = True
            extraction_quality["retryApplied"] = False
            return pdf_rows, comparison, extraction_quality
    logger.info(f"重试抽取: {len(fresh_pdf_paths)} 个 PDF, cache_enabled=False, workers=1")
    try:
        retry_pdf_rows = extract_invoice_items(
            fresh_pdf_paths, retry_config,
            expected_rows=_expected_labor_rows(excel_rows), **kwargs,
        )
    except Exception as exc:
        logger.error(f"重试抽取异常，保留原始结果: {exc}", exc_info=True)
        extraction_quality["retryAttempted"] = True
        extraction_quality["retryApplied"] = False
        return pdf_rows, comparison, extraction_quality
    logger.info(f"重试抽取结果: {len(retry_pdf_rows)} 条")
    if not retry_pdf_rows:
        logger.warning("重试抽取返回 0 条，保留原始结果")
        extraction_quality["retryAttempted"] = True
        extraction_quality["retryApplied"] = False
        return pdf_rows, comparison, extraction_quality
    if retry_pdf_rows:
        retry_comparison = compare_labor_items(
            retry_pdf_rows, excel_rows,
            amount_tolerance=AI_CONFIG["amount_tolerance"],
            hours_tolerance=AI_CONFIG["hours_tolerance"],
            confidence_threshold=AI_CONFIG["confidence_threshold"],
            manual_name_mapping=manual_name_mapping,
        )
        retry_quality = calculate_extraction_quality(retry_pdf_rows, retry_comparison["summary"], confidence_threshold=AI_CONFIG["confidence_threshold"])
        extraction_quality["retryAttempted"] = True
        if calculate_quality_score(retry_quality, retry_comparison["summary"]) < calculate_quality_score(extraction_quality, comparison["summary"]):
            retry_quality["retryAttempted"] = True
            retry_quality["retryApplied"] = True
            return retry_pdf_rows, retry_comparison, retry_quality
        extraction_quality["retryApplied"] = False
    return pdf_rows, comparison, extraction_quality


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


def _check_stale_extracting(metadata: dict) -> dict:
    """Mark run as failed if it's been stuck in '抽取中' for over 10 minutes."""
    if metadata.get("status") != "抽取中":
        return metadata
    from datetime import datetime as _dt, timedelta
    updated = metadata.get("updatedAt") or metadata.get("createdAt") or ""
    try:
        updated_dt = _dt.fromisoformat(updated)
    except (ValueError, TypeError):
        return metadata
    if _dt.now() - updated_dt > timedelta(minutes=30):
        run_id = metadata.get("id")
        if run_id:
            try:
                metadata = update_labor_metadata(run_id, {
                    "status": "抽取失败",
                    "errorMessage": "抽取超时（超过 30 分钟未完成）。请重新点击「抽取并核对」重试。",
                })
            except Exception:
                pass
    return metadata


def _recover_stuck_labor_runs() -> None:
    """Mark stale '抽取中' runs as failed on server startup."""
    for metadata in list_labor_metadata():
        if metadata.get("status") != "抽取中":
            continue
        run_id = metadata.get("id")
        if run_id:
            try:
                update_labor_metadata(run_id, {
                    "status": "抽取失败",
                    "errorMessage": "服务器已重启，抽取任务被中断。请重新点击「抽取并核对」重试。",
                })
            except Exception:
                pass


def _build_conclusion(warehouse_comparison: dict, comparison: dict, extraction_quality: dict, amount_tolerance: float = 0.05) -> dict:
    """Build conclusion level and message for the reconciliation result."""
    from bonus_platform.engine.labor.compare import _adaptive_tolerance

    wc_summary = warehouse_comparison.get("summary", {})
    comp_summary = comparison.get("summary", {})
    total_passed = wc_summary.get("totalPassed", False)
    amount_delta_total = abs(wc_summary.get("amountDeltaTotal", 0))
    pdf_amount_total = abs(wc_summary.get("pdfAmountTotal", 0))
    excel_amount_total = abs(wc_summary.get("excelAmountTotal", 0))
    max_amount = max(pdf_amount_total, excel_amount_total, 1.0)
    amount_delta_pct = amount_delta_total / max_amount * 100

    pdf_employee_count = comp_summary.get("pdfEmployeeCount", 0)
    excel_employee_count = comp_summary.get("excelEmployeeCount", 0)
    amount_diff_count = comp_summary.get("amountDiffCount", 0)
    low_confidence_count = comp_summary.get("lowConfidenceCount", 0)
    exception_count = comp_summary.get("exceptionCount", 0)

    # 结论级别判定
    effective_tolerance = _adaptive_tolerance(max_amount, amount_tolerance)
    if extraction_quality.get("level") == "critical":
        conclusion_level = "critical"
        conclusion_message = "抽取质量存在严重问题，必须人工复核"
    elif extraction_quality.get("level") == "warning" or low_confidence_count > 0:
        conclusion_level = "warning"
        conclusion_message = "存在低置信度抽取，需人工复核"
    elif total_passed and amount_diff_count == 0:
        conclusion_level = "pass"
        conclusion_message = "仓库总金额核对通过"
    elif amount_delta_total <= effective_tolerance and amount_diff_count == 0:
        conclusion_level = "pass"
        conclusion_message = f"仓库总金额核对通过，差异 ${amount_delta_total:.2f} ({amount_delta_pct:.2f}%)"
    else:
        conclusion_level = "warning"
        if amount_diff_count > 0:
            conclusion_message = f"{amount_diff_count}人工时/金额差异需关注"
        else:
            conclusion_message = f"仓库总金额差异 ${amount_delta_total:.2f} ({amount_delta_pct:.2f}%)"

    # 计算不在本批发票人数（使用实际的"Excel有PDF无"行数，而非简单减法）
    comparison_rows = comparison.get("rows", [])
    not_in_invoice_count = sum(1 for r in comparison_rows if r.get("matchStatus") == "Excel有PDF无")

    return {
        "conclusionLevel": conclusion_level,
        "conclusionMessage": conclusion_message,
        "notInInvoiceCount": not_in_invoice_count,
    }


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

    final_payload = _final_calculation_payload(final_path, metadata)
    save_table_data(run_dir, build_final_table_data(run_id, final_path, final_payload["month"]))

    files = dict(metadata.get("files", {}))
    files["confirmation"] = attach_file_record(run_id, confirmation_path, "确认结果")
    files["finalResult"] = attach_file_record(run_id, final_path, "最终结果")
    updated = update_metadata(
        run_id,
        {
            "status": "已最终确认",
            "files": files,
            "finalDownloadUrl": files["finalResult"]["downloadUrl"],
            **final_payload,
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
        headers={"Cache-Control": "no-store"},
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


def _final_calculation_payload(final_path: Path, fallback_metadata: dict) -> dict:
    workbook = load_workbook(final_path, data_only=True, read_only=True)
    try:
        fallback_month = _coerce_month(fallback_metadata.get("month")) or 0
        month = (
            _first_summary_month(workbook, "最终招聘奖金汇总")
            or _first_summary_month(workbook, "最终内推奖金汇总")
            or _intro_value(workbook, "核算月份")
            or fallback_month
        )
        detail_rows = _workbook_rows(workbook, "招聘奖金明细", skip_total=False)
        exception_rows = _workbook_rows(workbook, "异常清单", skip_total=False)
        preview = [
            {
                "姓名": row.get("姓名", ""),
                "工号": row.get("工号", ""),
                "职级": row.get("职级", ""),
                "ABC类别": row.get("ABC类别", ""),
                "招聘渠道": row.get("招聘渠道", ""),
                "招聘人入职1月奖金": row.get("招聘人入职1月奖金", 0),
                "内推入职1月奖金": row.get("内推入职1月奖金", 0),
                "异常提示": row.get("异常提示", ""),
            }
            for row in detail_rows[:MAX_PREVIEW_ROWS]
        ]
        return {
            "month": month,
            "importedRows": len(detail_rows),
            "recruitmentTotal": _summary_total(workbook, "最终招聘奖金汇总"),
            "referralTotal": _summary_total(workbook, "最终内推奖金汇总"),
            "exceptionCount": len(exception_rows),
            "pendingCount": 0,
            "pendingTotal": 0,
            "detailPreview": preview,
            "pendingConfirmations": [],
            "exceptions": exception_rows[:MAX_PREVIEW_ROWS],
        }
    finally:
        workbook.close()


def _workbook_rows(workbook, sheet_name: str, skip_total: bool = True) -> list[dict]:
    if sheet_name not in workbook.sheetnames:
        return []
    sheet = workbook[sheet_name]
    headers = [sheet.cell(1, column).value for column in range(1, sheet.max_column + 1)]
    rows: list[dict] = []
    for values in sheet.iter_rows(min_row=2, values_only=True):
        row = {str(header).strip(): values[index] for index, header in enumerate(headers) if header and index < len(values)}
        if not any(value not in (None, "") for value in row.values()):
            continue
        if skip_total and _is_workbook_total_row(row):
            continue
        rows.append(row)
    return rows


def _is_workbook_total_row(row: dict) -> bool:
    return any(str(value or "").strip() in {"合计", "总计"} for value in row.values())


def _summary_total(workbook, sheet_name: str) -> float:
    total = sum(_float_value(row.get("合计发放")) for row in _workbook_rows(workbook, sheet_name, skip_total=True))
    return round(total, 2)


def _first_summary_month(workbook, sheet_name: str) -> int | None:
    for row in _workbook_rows(workbook, sheet_name, skip_total=True):
        month = _coerce_month(row.get("核算月份"))
        if month:
            return month
    return None


def _intro_value(workbook, label: str) -> int | None:
    if "计算说明" not in workbook.sheetnames:
        return None
    sheet = workbook["计算说明"]
    for key, value in sheet.iter_rows(min_row=2, max_col=2, values_only=True):
        if str(key or "").strip() == label:
            return _coerce_month(value)
    return None


def _coerce_month(value) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.year * 100 + value.month
    if isinstance(value, (int, float)):
        return int(value)
    digits = "".join(char for char in str(value) if char.isdigit())
    if len(digits) >= 6:
        return int(digits[:6])
    return None


def _float_value(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _labor_metadata_or_404(run_id: str) -> dict:
    try:
        return load_labor_metadata(get_labor_run_dir(run_id))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="劳务核对批次不存在。") from exc


def _labor_workbook_path(metadata: dict) -> Path:
    """返回第一个 workbook 文件路径（兼容旧逻辑）"""
    paths = _labor_workbook_paths(metadata)
    return paths[0]


def _labor_workbook_paths(metadata: dict) -> list[Path]:
    """返回所有 workbook 文件路径，支持多文件上传"""
    files_meta = metadata.get("files", {})
    # 优先使用 workbooks 列表（新格式）
    records = files_meta.get("workbooks") or []
    if not records:
        # 兼容旧格式：单个 workbook 字段
        single = files_meta.get("workbook")
        if single:
            records = [single]
    if not records:
        raise HTTPException(status_code=400, detail="请先上传线下账单 Excel。")
    paths = []
    for rec in records:
        p = Path(rec.get("path", ""))
        if not p.exists():
            raise HTTPException(status_code=404, detail=f"线下账单文件不存在：{p.name}")
        paths.append(p)
    return paths


# ============================================================
# DOMESTIC LABOR PAYROLL API  /api/domestic-labor/*
# ============================================================

DOMESTIC_LABOR_RUNS_DIR.mkdir(parents=True, exist_ok=True)
PAYROLL_OUTPUT_DIR = DOMESTIC_LABOR_RUNS_DIR.parent / "payroll_outputs"
PAYROLL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

payroll_logger = logging.getLogger("bonus_platform.payroll")


def _run_payroll_calculation(run_id: str, file_path: str, attendance_month: str,
                              engines: list, password: str = None,
                              hrbp_list: list = None):
    """Background worker: load Excel, run engines, save results."""
    payroll_logger.info("Starting payroll calculation for %s, engines=%s", run_id, engines)
    try:
        update_payroll_metadata(run_id, {"status": "计算中"})
        with PayrollDataLoader(file_path, password=password) as loader:
            monthly = loader.monthly
            daily_by_emp = loader.group_daily_by_employee()
            housing_by_emp = loader.group_housing_by_employee()

            # Region auto-detection
            region = "default"
            if monthly.rows:
                dept2 = str(monthly.rows[0].get("二级部门名称", ""))
                if any(k in dept2 for k in ("华东枢纽", "华东揽收组", "华西枢纽", "华西揽收组")):
                    region = "wes"

            results = []
            for row in monthly.rows:
                emp_id = str(row.get("工号", ""))
                emp_name = str(row.get("姓名", ""))
                dept = str(row.get("二级部门名称", ""))
                r = {"employee_id": emp_id, "employee_name": emp_name, "department": dept,
                     "quanqinjiang": 0, "canbu": 0, "waisu_butie": 0, "gonglingjiang": 0,
                     "total": 0, "warnings": []}

                if "quanqinjiang" in engines:
                    cr = QuanQinJiangEngine().calculate(row, daily_by_emp.get(emp_id, []))
                    r["quanqinjiang"] = cr.amount
                    r["warnings"].extend(cr.warnings)

                if "canbu" in engines:
                    cr = CanBuEngine().calculate(row, daily_by_emp.get(emp_id, []))
                    r["canbu"] = cr.amount
                    r["warnings"].extend(cr.warnings)

                if "waisu_butie" in engines:
                    cr = WaiSuBuTieEngine().calculate(row, daily_by_emp.get(emp_id, []),
                                                       housing_by_emp.get(emp_id, []))
                    r["waisu_butie"] = cr.amount
                    r["warnings"].extend(cr.warnings)

                if "gonglingjiang" in engines:
                    cr = GongLingJiangEngine().calculate(row, hrbp_list or [], region=region)
                    r["gonglingjiang"] = cr.amount
                    r["warnings"].extend(cr.warnings)

                r["total"] = r["quanqinjiang"] + r["canbu"] + r["waisu_butie"] + r["gonglingjiang"]
                r["warnings"] = "; ".join(r["warnings"]) if r["warnings"] else ""
                results.append(r)

            # Compute summary
            summary = {
                "total_employees": len(results),
                "total_quanqinjiang": sum(r["quanqinjiang"] for r in results),
                "total_canbu": sum(r["canbu"] for r in results),
                "total_waisu_butie": sum(r["waisu_butie"] for r in results),
                "total_gonglingjiang": sum(r["gonglingjiang"] for r in results),
                "grand_total": sum(r["total"] for r in results),
                "warning_count": sum(1 for r in results if r["warnings"]),
            }

            update_payroll_metadata(run_id, {
                "status": "已完成",
                "results": results,
                "summary": summary,
            })
            payroll_logger.info("Payroll calculation completed for %s: %d employees", run_id, len(results))
    except Exception as exc:
        payroll_logger.exception("Payroll calculation failed for %s", run_id)
        update_payroll_metadata(run_id, {"status": "失败", "error": str(exc)})


@app.get("/api/domestic-labor/runs")
def list_domestic_labor_runs() -> dict:
    return {"runs": list_payroll_metadata()}


@app.post("/api/domestic-labor/runs")
async def create_domestic_labor_run(file: UploadFile = File(...), engines: str = Body(""),
                                     attendance_month: str = Body(""),
                                     password: str = Body(""), hrbp_list: str = Body("")):
    # Validate file
    if not file.filename.lower().endswith((".xlsx", ".xlsm", ".xls")):
        raise HTTPException(400, "请上传 Excel 文件（.xlsx / .xlsm / .xls）")

    # Parse engines
    engine_list = [e.strip() for e in engines.split(",") if e.strip()]
    if not engine_list:
        raise HTTPException(400, "请至少选择一个计算引擎")
    valid_engines = set(ENGINE_TEMPLATES.keys())
    for e in engine_list:
        if e not in valid_engines:
            raise HTTPException(400, f"未知引擎: {e}")

    # Save uploaded file
    DOMESTIC_LABOR_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    run_id_temp = safe_payroll_filename(file.filename)
    # We'll create the run first, then save file into its directory
    run = create_payroll_run({
        "engines": engine_list,
        "attendanceMonth": attendance_month,
        "fileName": file.filename,
    })
    run_id = run["id"]
    run_dir = get_payroll_run_dir(run_id)

    saved_name = safe_payroll_filename(file.filename)
    file_path = run_dir / saved_name
    with open(file_path, "wb") as f:
        f.write(await file.read())

    # Parse hrbp_list if provided
    hrbp = None
    if hrbp_list.strip():
        try:
            hrbp = __import__("json").loads(hrbp_list)
        except Exception:
            pass

    update_payroll_metadata(run_id, {
        "status": "已上传",
        "filePath": str(file_path),
        "savedFileName": saved_name,
        "fileSize": file_path.stat().st_size,
    })

    # Launch background calculation
    asyncio.get_event_loop().run_in_executor(
        None, _run_payroll_calculation, run_id, str(file_path),
        attendance_month, engine_list, password or None, hrbp,
    )

    return {"run_id": run_id, "status": "已上传", "message": "计算任务已提交"}


@app.get("/api/domestic-labor/runs/{run_id}")
def get_domestic_labor_run(run_id: str) -> dict:
    try:
        metadata = load_payroll_metadata(get_payroll_run_dir(run_id))
    except FileNotFoundError as exc:
        raise HTTPException(404, "薪酬计算任务不存在。") from exc
    return metadata


@app.get("/api/domestic-labor/runs/{run_id}/results")
def get_domestic_labor_results(run_id: str) -> dict:
    try:
        metadata = load_payroll_metadata(get_payroll_run_dir(run_id))
    except FileNotFoundError as exc:
        raise HTTPException(404, "薪酬计算任务不存在。") from exc
    return {
        "run_id": run_id,
        "status": metadata.get("status"),
        "results": metadata.get("results", []),
        "summary": metadata.get("summary", {}),
    }


@app.get("/api/domestic-labor/runs/{run_id}/export")
def export_domestic_labor(run_id: str) -> dict:
    try:
        metadata = load_payroll_metadata(get_payroll_run_dir(run_id))
    except FileNotFoundError as exc:
        raise HTTPException(404, "薪酬计算任务不存在。") from exc
    results = metadata.get("results", [])
    if not results:
        raise HTTPException(400, "暂无计算结果可导出")
    file_name = f"薪酬核算_{metadata.get('attendanceMonth', '')}_{run_id}.xlsx"
    out_path = PAYROLL_OUTPUT_DIR / file_name
    exporter = ExcelExporter(str(out_path))
    summary = metadata.get("summary", {})
    exporter.export(results, metadata.get("attendanceMonth", ""), summary)
    return {"file_path": str(out_path), "file_name": file_name}


@app.get("/api/domestic-labor/runs/{run_id}/download/{filename}")
def download_domestic_labor_file(run_id: str, filename: str) -> FileResponse:
    try:
        run_dir = get_payroll_run_dir(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, "薪酬计算任务不存在。") from exc
    # Check run dir first, then output dir
    path = run_dir / Path(filename).name
    if not path.exists():
        path = PAYROLL_OUTPUT_DIR / Path(filename).name
    if not path.exists():
        raise HTTPException(404, "文件不存在或已被清理。")
    return FileResponse(path, filename=path.name)


@app.delete("/api/domestic-labor/runs/{run_id}")
def delete_domestic_labor_run(run_id: str) -> dict:
    try:
        run_dir = get_payroll_run_dir(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, "薪酬计算任务不存在。") from exc
    shutil.rmtree(run_dir, ignore_errors=True)
    return {"message": f"已删除任务: {run_id}"}


@app.get("/api/domestic-labor/templates")
def list_domestic_labor_templates() -> dict:
    return {"templates": [get_template_info(k) for k in ENGINE_TEMPLATES]}


@app.get("/api/domestic-labor/templates/{engine_key}/download")
def download_domestic_labor_template(engine_key: str) -> FileResponse:
    if engine_key not in ENGINE_TEMPLATES:
        raise HTTPException(404, "模板不存在")
    data = generate_template(engine_key)
    tmp = NamedTemporaryFile(delete=False, suffix=f"_{engine_key}_template.xlsx")
    tmp.write(data)
    tmp.close()
    return FileResponse(
        tmp.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=f"{engine_key}_template.xlsx",
    )


# =========================================================================
# FBU PERFORMANCE API  /api/fbu-performance/*
# =========================================================================

fbu_run_manager = FBURunManager(str(FBU_PERFORMANCE_RUNS_DIR))
fbu_roster_store = FBURosterStore(str(FBU_PERFORMANCE_RUNS_DIR))


def _load_fbu_roster_for_run(parser: FBUPerformanceParser, run_id: str) -> Path | None:
    """加载活动花名册；没有活动花名册时复制并加载基础花名册。"""
    run_dir = FBU_PERFORMANCE_RUNS_DIR / run_id
    roster_path = next((path for path in [run_dir / "roster.xlsx", run_dir / "roster.xls"] if path.exists()), None)
    if roster_path is None:
        roster_path = fbu_roster_store.copy_active_to_run(run_id)
        if roster_path:
            run = fbu_run_manager.get_run(run_id)
            metadata = fbu_roster_store.get_metadata()
            if run:
                fbu_run_manager.update_run(
                    run_id,
                    roster_file=metadata.get("filename", "active_roster.xlsx"),
                    roster_source="base",
                )
    if roster_path and roster_path.exists():
        parser.load_roster(str(roster_path))
        return roster_path
    return None


@app.get("/api/fbu-performance/roster")
def get_fbu_base_roster() -> dict:
    """获取FBU基础花名册状态"""
    return fbu_roster_store.get_metadata()


@app.post("/api/fbu-performance/roster")
async def upload_fbu_base_roster(file: UploadFile = File(...)) -> dict:
    """上传FBU基础花名册，供后续月度活动默认引用"""
    try:
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in {".xlsx", ".xls"}:
            raise HTTPException(400, "请上传 .xlsx 或 .xls 格式的花名册")
        content = await file.read()
        tmp_path = FBU_PERFORMANCE_RUNS_DIR / "_roster" / f"_upload_check{suffix}"
        tmp_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_bytes(content)

        parser = FBUPerformanceParser()
        roster = parser.load_roster(str(tmp_path))
        metadata = fbu_roster_store.save_active_roster(
            content=content,
            filename=file.filename,
            total_employees=len(roster),
        )
        tmp_path.unlink(missing_ok=True)
        return {"success": True, "roster": metadata}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"花名册解析失败: {str(e)}")


@app.post("/api/fbu-performance/import-attendance")
async def import_fbu_attendance(
    file: UploadFile = File(...),
    calc_month: str = Body(...),
    roster: UploadFile = File(None),
    run_id: str = Body(None),
) -> dict:
    """Step 1: 导入考勤日报表"""
    # 获取或创建运行记录
    if run_id:
        run = fbu_run_manager.get_run(run_id)
        if not run:
            raise HTTPException(404, "任务不存在")
    else:
        run = fbu_run_manager.create_run(calc_month=calc_month)

    # 保存上传文件
    run_dir = FBU_PERFORMANCE_RUNS_DIR / run.run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    file_path = run_dir / "attendance.xlsx"
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    # 保存花名册（如果提供）
    roster_path = None
    if roster:
        roster_suffix = Path(roster.filename or "").suffix.lower()
        if roster_suffix not in {".xlsx", ".xls"}:
            raise HTTPException(400, "请上传 .xlsx 或 .xls 格式的花名册")
        roster_path = run_dir / f"roster{roster_suffix}"
        with open(roster_path, "wb") as f:
            content = await roster.read()
            f.write(content)
        fbu_run_manager.update_run(
            run.run_id,
            roster_file=roster.filename,
            roster_source="activity",
        )

    # 更新文件名
    fbu_run_manager.update_run(run.run_id, attendance_file=file.filename)

    # 解析并预览
    try:
        target_month = int(calc_month.split("-")[1]) if "-" in calc_month else int(calc_month)
        parser = FBUPerformanceParser()

        # 加载本活动花名册；没有时自动引用当前基础花名册
        if roster_path and roster_path.exists():
            parser.load_roster(str(roster_path))
        else:
            _load_fbu_roster_for_run(parser, run.run_id)

        preview = parser.parse_attendance_preview(str(file_path), target_month)

        # 保存分步数据
        fbu_run_manager.save_step_data(run.run_id, 1, preview)

        return {
            "success": True,
            "run_id": run.run_id,
            "step": 1,
            "preview": preview,
        }
    except Exception as e:
        fbu_run_manager.update_run(run.run_id, status="failed", error=str(e))
        raise HTTPException(500, f"考勤数据解析失败: {str(e)}")


@app.post("/api/fbu-performance/import-salary")
async def import_fbu_salary(
    run_id: str = Body(...),
    file: UploadFile = File(...),
) -> dict:
    """Step 2: 导入薪资档案"""
    run = fbu_run_manager.get_run(run_id)
    if not run:
        raise HTTPException(404, "任务不存在")

    # 保存上传文件
    run_dir = FBU_PERFORMANCE_RUNS_DIR / run_id
    file_path = run_dir / "salary.xlsx"
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    # 更新文件名
    fbu_run_manager.update_run(run_id, salary_file=file.filename)

    # 解析并预览
    try:
        parser = FBUPerformanceParser()

        # 加载活动花名册或基础花名册快照
        _load_fbu_roster_for_run(parser, run_id)

        preview = parser.parse_salary_preview(str(file_path))

        # 保存分步数据
        fbu_run_manager.save_step_data(run_id, 2, preview)

        return {
            "success": True,
            "run_id": run_id,
            "step": 2,
            "preview": preview,
        }
    except Exception as e:
        fbu_run_manager.update_run(run_id, status="failed", error=str(e))
        raise HTTPException(500, f"薪资数据解析失败: {str(e)}")


@app.post("/api/fbu-performance/import-performance")
async def import_fbu_performance(
    run_id: str = Body(...),
    file: UploadFile = File(...),
) -> dict:
    """Step 3: 导入绩效报表"""
    run = fbu_run_manager.get_run(run_id)
    if not run:
        raise HTTPException(404, "任务不存在")

    # 保存上传文件
    run_dir = FBU_PERFORMANCE_RUNS_DIR / run_id
    file_path = run_dir / "performance.xlsx"
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    # 更新文件名
    fbu_run_manager.update_run(run_id, performance_file=file.filename)

    # 解析并预览
    try:
        parser = FBUPerformanceParser()

        # 加载活动花名册或基础花名册快照
        _load_fbu_roster_for_run(parser, run_id)

        preview = parser.parse_performance_preview(str(file_path))

        # 保存分步数据
        fbu_run_manager.save_step_data(run_id, 3, preview)

        return {
            "success": True,
            "run_id": run_id,
            "step": 3,
            "preview": preview,
        }
    except Exception as e:
        fbu_run_manager.update_run(run_id, status="failed", error=str(e))
        raise HTTPException(500, f"绩效数据解析失败: {str(e)}")


@app.post("/api/fbu-performance/import")
async def import_fbu_performance_data(
    attendance: UploadFile = File(...),
    salary: UploadFile = File(...),
    performance: UploadFile = File(...),
    calc_month: str = Body(...),
) -> dict:
    """导入FBU绩效数据文件（保留兼容）"""
    # 创建运行记录
    run = fbu_run_manager.create_run(
        calc_month=calc_month,
        attendance_file=attendance.filename,
        salary_file=salary.filename,
        performance_file=performance.filename,
    )

    # 保存上传文件
    run_dir = FBU_PERFORMANCE_RUNS_DIR / run.run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    for file, name in [(attendance, "attendance.xlsx"), (salary, "salary.xlsx"), (performance, "performance.xlsx")]:
        file_path = run_dir / name
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)

    fbu_run_manager.update_run(run.run_id, status="imported")

    return {
        "success": True,
        "run_id": run.run_id,
        "message": "数据导入成功",
    }


@app.post("/api/fbu-performance/calculate/{run_id}")
def calculate_fbu_performance(run_id: str) -> dict:
    """执行FBU绩效核算"""
    run = fbu_run_manager.get_run(run_id)
    if not run:
        raise HTTPException(404, "任务不存在")

    try:
        fbu_run_manager.update_run(run_id, status="processing")

        parser = FBUPerformanceParser()

        # 判断是分步模式还是一次性导入模式
        if run.current_step >= 3 and run.attendance_data and run.salary_data and run.performance_data:
            # 分步模式：从已保存的分步数据计算
            engine = parser.parse_all_from_step_data(
                attendance_data=run.attendance_data.get('employees', []),
                salary_data=run.salary_data.get('employees', []),
                performance_data=run.performance_data.get('employees', []),
            )
        else:
            # 一次性导入模式：从文件计算
            run_dir = FBU_PERFORMANCE_RUNS_DIR / run_id
            target_month = int(run.calc_month.split("-")[1]) if "-" in run.calc_month else int(run.calc_month)
            _load_fbu_roster_for_run(parser, run_id)

            engine = parser.parse_all(
                attendance_file=str(run_dir / "attendance.xlsx"),
                salary_file=str(run_dir / "salary.xlsx"),
                performance_file=str(run_dir / "performance.xlsx"),
                target_month=target_month,
            )

        # 保存结果
        employees = engine.get_all_employees()
        fbu_run_manager.save_results(run_id, employees)

        return {
            "success": True,
            "run_id": run_id,
            "total_employees": len(employees),
            "total_bonus": sum(e.performance_bonus for e in employees),
        }

    except Exception as e:
        fbu_run_manager.update_run(run_id, status="failed", error=str(e))
        raise HTTPException(500, f"计算失败: {str(e)}")


@app.post("/api/fbu-performance/runs")
def create_fbu_performance_run(body: dict) -> dict:
    """创建新的月度核算活动"""
    calc_month = body.get("calc_month")
    if not calc_month:
        raise HTTPException(400, "缺少核算月份")

    # 验证calc_month格式 (YYYY-MM)
    import re
    if not re.match(r'^\d{4}-\d{2}$', calc_month):
        raise HTTPException(400, "核算月份格式无效，应为YYYY-MM")

    # 验证月份范围
    try:
        year, month = calc_month.split('-')
        if not (2020 <= int(year) <= 2030 and 1 <= int(month) <= 12):
            raise HTTPException(400, "核算月份范围无效")
    except ValueError:
        raise HTTPException(400, "核算月份格式无效")

    run = fbu_run_manager.create_run(calc_month=calc_month)
    roster_path = fbu_roster_store.copy_active_to_run(run.run_id)
    if roster_path:
        metadata = fbu_roster_store.get_metadata()
        fbu_run_manager.update_run(
            run.run_id,
            roster_file=metadata.get("filename", "active_roster.xlsx"),
            roster_source="base",
        )
        run = fbu_run_manager.get_run(run.run_id) or run

    return {
        "success": True,
        "run_id": run.run_id,
        "calc_month": run.calc_month,
        "status": run.status,
        "roster_file": run.roster_file,
        "roster_source": run.roster_source,
    }


@app.get("/api/fbu-performance/runs")
def list_fbu_performance_runs() -> dict:
    """获取FBU绩效核算任务列表"""
    runs = fbu_run_manager.list_runs()
    return {
        "runs": [
            {
                "run_id": r.run_id,
                "created_at": r.created_at,
                "calc_month": r.calc_month,
                "status": r.status,
                "current_step": r.current_step,
                "total_employees": r.total_employees,
                "total_bonus": r.total_bonus,
                "roster_file": r.roster_file,
                "roster_source": r.roster_source,
            }
            for r in runs
        ]
    }


@app.get("/api/fbu-performance/runs/{run_id}")
def get_fbu_performance_run(run_id: str) -> dict:
    """获取FBU绩效核算任务详情"""
    run = fbu_run_manager.get_run(run_id)
    if not run:
        raise HTTPException(404, "任务不存在")
    return vars(run)


@app.get("/api/fbu-performance/runs/{run_id}/results")
def get_fbu_performance_results(run_id: str) -> dict:
    """获取FBU绩效核算结果"""
    run = fbu_run_manager.get_run(run_id)
    if not run:
        raise HTTPException(404, "任务不存在")
    if run.status != "completed":
        raise HTTPException(400, "任务未完成")
    return {"results": run.results}


@app.get("/api/fbu-performance/runs/{run_id}/export")
def export_fbu_performance(run_id: str) -> dict:
    """导出FBU绩效核算结果"""
    # 检查任务是否存在
    run = fbu_run_manager.get_run(run_id)
    if not run:
        raise HTTPException(404, "任务不存在")

    # 检查任务状态
    if run.status != "completed":
        raise HTTPException(400, f"任务未完成，当前状态: {run.status}")

    # 导出
    output_path = fbu_run_manager.export_run(run_id, str(EXPORT_DIR))
    if not output_path:
        raise HTTPException(500, "导出失败，请检查数据完整性")

    return {"file_path": output_path, "file_name": Path(output_path).name}


@app.get("/api/fbu-performance/runs/{run_id}/export-excel")
def export_fbu_excel(run_id: str, type: str = "attendance") -> dict:
    """导出带样式的Excel文件"""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    # 检查任务是否存在
    run = fbu_run_manager.get_run(run_id)
    if not run:
        raise HTTPException(404, "任务不存在")

    # 获取数据
    data = []
    title = ""
    filename = ""

    if type == "attendance" and run.attendance_data:
        data = run.attendance_data.get('employees', [])
        title = "考勤汇总"
        filename = f"考勤汇总_{run.calc_month}_{run_id}.xlsx"
    elif type == "salary" and run.salary_data:
        data = run.salary_data.get('employees', [])
        title = "薪资匹配"
        filename = f"薪资匹配_{run.calc_month}_{run_id}.xlsx"
    elif type == "performance" and run.performance_data:
        data = run.performance_data.get('employees', [])
        title = "绩效明细"
        filename = f"绩效明细_{run.calc_month}_{run_id}.xlsx"
    elif type == "results" and run.results:
        data = run.results
        title = "核算结果"
        filename = f"核算结果_{run.calc_month}_{run_id}.xlsx"
    else:
        raise HTTPException(400, "没有数据可导出")

    if not data:
        raise HTTPException(400, "没有数据可导出")

    # 创建Excel
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = title

    # 定义样式
    # 员工信息列样式（蓝色系）
    emp_fill = PatternFill(start_color="E3F2FD", end_color="E3F2FD", fill_type="solid")
    emp_font = Font(bold=True, color="1565C0")

    # 数据列样式（绿色系）
    data_fill = PatternFill(start_color="E8F5E9", end_color="E8F5E9", fill_type="solid")
    data_font = Font(bold=True, color="2E7D32")

    # 计算列样式（橙色系）
    calc_fill = PatternFill(start_color="FFF3E0", end_color="FFF3E0", fill_type="solid")
    calc_font = Font(bold=True, color="E65100")

    # 金额列样式（紫色系）
    money_fill = PatternFill(start_color="F3E5F5", end_color="F3E5F5", fill_type="solid")
    money_font = Font(bold=True, color="6A1B9A")

    # 标题行样式
    title_fill = PatternFill(start_color="2196F3", end_color="2196F3", fill_type="solid")
    title_font = Font(bold=True, color="FFFFFF", size=14)

    # 表头样式
    header_fill = PatternFill(start_color="37474F", end_color="37474F", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")

    # 边框样式
    thin_border = Border(
        left=Side(style='thin', color='BDBDBD'),
        right=Side(style='thin', color='BDBDBD'),
        top=Side(style='thin', color='BDBDBD'),
        bottom=Side(style='thin', color='BDBDBD')
    )

    # 写入标题
    ws.merge_cells('A1:L1')
    title_cell = ws['A1']
    title_cell.value = f"FBU美洲绩效核算 - {title} ({run.calc_month})"
    title_cell.font = title_font
    title_cell.fill = title_fill
    title_cell.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[1].height = 35

    # 定义列配置
    if type == "attendance":
        columns = [
            ('工号', 'employee_id', 'emp', 15),
            ('姓名', 'name', 'emp', 12),
            ('划分区域', 'area', 'emp', 15),
            ('部门全称', 'department', 'emp', 40),
            ('岗位类型', 'job_type', 'emp', 10),
            ('夜班', 'has_night_shift', 'data', 8),
            ('计薪出勤(h)', 'total_base_hours', 'data', 14),
            ('OT1.5(h)', 'total_ot15', 'data', 12),
            ('OT2.0(h)', 'total_ot20', 'data', 12),
            ('病假(h)', 'sick', 'data', 10),
            ('年假(h)', 'annual', 'data', 10),
            ('节假日(h)', 'holiday', 'data', 10),
        ]
    elif type == "salary":
        columns = [
            ('工号', 'employee_id', 'emp', 15),
            ('姓名', 'name', 'emp', 12),
            ('划分区域', 'area', 'emp', 15),
            ('部门全称', 'department', 'emp', 40),
            ('时薪($)', 'hourly_rate', 'money', 12),
            ('绩效比例', 'ratio', 'money', 12),
        ]
    elif type == "performance":
        columns = [
            ('工号', 'employee_id', 'emp', 15),
            ('姓名', 'name', 'emp', 12),
            ('划分区域', 'area', 'emp', 15),
            ('部门全称', 'department', 'emp', 40),
            ('岗位类型', 'job_type', 'emp', 10),
            ('绩效得分', 'score', 'data', 12),
            ('绩效等级', 'level', 'data', 12),
            ('绩效系数', 'coefficient', 'calc', 12),
        ]
    elif type == "results":
        columns = [
            ('工号', 'employee_id', 'emp', 15),
            ('姓名', 'name', 'emp', 12),
            ('划分区域', 'area', 'emp', 15),
            ('部门全称', 'department', 'emp', 40),
            ('岗位类型', 'job_type', 'emp', 10),
            ('时薪($)', 'hourly_rate', 'money', 12),
            ('绩效基数($)', 'performance_base', 'calc', 14),
            ('绩效比例', 'performance_ratio', 'money', 12),
            ('绩效系数', 'performance_coefficient', 'calc', 12),
            ('绩效奖金($)', 'performance_bonus', 'money', 14),
        ]

    # 写入表头
    header_row = 3
    for col_idx, (header, _, style_type, width) in enumerate(columns, 1):
        cell = ws.cell(row=header_row, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center', vertical='center')
        cell.border = thin_border
        ws.column_dimensions[chr(64 + col_idx) if col_idx <= 26 else chr(64 + (col_idx - 1) // 26) + chr(65 + (col_idx - 1) % 26)].width = width

    ws.row_dimensions[header_row].height = 25

    # 写入数据
    for row_idx, item in enumerate(data, header_row + 1):
        for col_idx, (_, field, style_type, _) in enumerate(columns, 1):
            value = item.get(field, '')

            # 特殊处理
            if field == 'job_type':
                value = '仓库' if value == 'warehouse' else '职能'
            elif field == 'has_night_shift':
                value = '是' if value else '否'
            elif field == 'sick':
                # 从day_shift和night_shift获取
                day_shift = item.get('day_shift', {})
                night_shift = item.get('night_shift', {})
                value = day_shift.get('病假', 0) + night_shift.get('病假', 0)
            elif field == 'annual':
                day_shift = item.get('day_shift', {})
                night_shift = item.get('night_shift', {})
                value = day_shift.get('年假', 0) + night_shift.get('年假', 0)
            elif field == 'holiday':
                day_shift = item.get('day_shift', {})
                night_shift = item.get('night_shift', {})
                value = day_shift.get('节假日', 0) + night_shift.get('节假日', 0)

            # 格式化数值
            if isinstance(value, float):
                if field in ['hourly_rate', 'performance_base', 'performance_bonus']:
                    value = round(value, 2)
                elif field in ['ratio', 'performance_ratio']:
                    value = f"{value * 100:.1f}%"
                elif field in ['total_base_hours', 'total_ot15', 'total_ot20', 'sick', 'annual', 'holiday']:
                    value = f"{value:.2f}"
                elif field in ['score', 'coefficient', 'performance_coefficient']:
                    value = round(value, 2)

            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.border = thin_border
            cell.alignment = Alignment(horizontal='center', vertical='center')

            # 应用样式
            if style_type == 'emp':
                cell.fill = emp_fill
            elif style_type == 'data':
                cell.fill = data_fill
            elif style_type == 'calc':
                cell.fill = calc_fill
            elif style_type == 'money':
                cell.fill = money_fill

        ws.row_dimensions[row_idx].height = 22

    # 添加汇总行
    summary_row = len(data) + header_row + 2
    ws.cell(row=summary_row, column=1, value="汇总").font = Font(bold=True, size=12)

    if type == "attendance":
        total_base = sum(e.get('total_base_hours', 0) for e in data)
        total_ot15 = sum(e.get('total_ot15', 0) for e in data)
        total_ot20 = sum(e.get('total_ot20', 0) for e in data)
        ws.cell(row=summary_row, column=2, value=f"员工数: {len(data)}")
        ws.cell(row=summary_row, column=7, value=f"{total_base:.2f}h")
        ws.cell(row=summary_row, column=8, value=f"{total_ot15:.2f}h")
        ws.cell(row=summary_row, column=9, value=f"{total_ot20:.2f}h")
    elif type == "results":
        total_bonus = sum(e.get('performance_bonus', 0) for e in data)
        ws.cell(row=summary_row, column=2, value=f"员工数: {len(data)}")
        ws.cell(row=summary_row, column=10, value=f"${total_bonus:,.2f}")

    # 保存文件
    output_path = EXPORT_DIR / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(output_path))

    return {
        "success": True,
        "filename": filename,
        "file_path": str(output_path),
    }


@app.get("/api/fbu-performance/runs/{run_id}/download/{filename}")
def download_fbu_performance_file(run_id: str, filename: str) -> FileResponse:
    """下载FBU绩效核算文件"""
    path = EXPORT_DIR / Path(filename).name
    if not path.exists():
        raise HTTPException(404, "文件不存在")
    return FileResponse(path, filename=path.name)


@app.delete("/api/fbu-performance/runs/{run_id}")
def delete_fbu_performance_run(run_id: str) -> dict:
    """删除FBU绩效核算任务"""
    # 检查任务是否存在
    run = fbu_run_manager.get_run(run_id)
    if not run:
        raise HTTPException(404, "任务不存在")

    # 删除文件目录
    run_dir = FBU_PERFORMANCE_RUNS_DIR / run_id
    if run_dir.exists():
        shutil.rmtree(run_dir, ignore_errors=True)

    # 删除运行记录
    fbu_run_manager.delete_run(run_id)
    return {"message": f"已删除任务: {run_id}"}


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
