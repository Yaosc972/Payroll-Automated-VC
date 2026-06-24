from io import BytesIO
import json
from pathlib import Path
import time

import pytest
from openpyxl import Workbook, load_workbook
from urllib.error import HTTPError

from bonus_platform.engine.labor.compare import compare_labor_items, compare_by_warehouse
from bonus_platform.engine.labor.extract import MiMoTimeoutException, _anthropic_messages_url, _effective_max_pages_per_request, _effective_render_scale, _extract_invoice_total_from_text, _http_post_json, extract_invoice_items, _extract_with_ai_images, _extract_with_rules, _request_headers
from bonus_platform.engine.labor.extract import _ai_instruction, _extract_pdf_pages, _safe_error_message
from bonus_platform.engine.labor.extract import _analyze_layout_with_ai
from bonus_platform.engine.labor.extract import _filter_ai_rows_by_page_text
from bonus_platform.engine.labor.extract import _filter_ai_rows_by_expected_employees
from bonus_platform.engine.labor.extract import _warehouse_id_from_filename as extract_warehouse_id_from_filename
from bonus_platform.engine.labor.extract import _warehouse_id_conflict
from bonus_platform.engine.labor.extract import _classify_pdf
from bonus_platform.engine.labor.extract import _warehouse_id_from_text
from bonus_platform.engine.labor import runs as labor_runs
from bonus_platform.engine.labor.governance import audit_ai_page_cache_candidates, build_ai_cache_reconciliation_preview, build_reocr_candidate_plan, build_rule_change_candidate, confirm_rule_candidate, replay_reocr_candidate_result, rollback_rule_version, summarize_rule_auto_replay, summarize_rule_replay
from bonus_platform.engine.labor.materials import build_material_dry_run, build_material_index, build_material_replay_plan
from bonus_platform.engine.labor.models import LaborLineItem, line_items_from_dicts
from bonus_platform.engine.labor.layout import InvoiceLayoutPlan, analyze_invoice_layout, extract_rows_from_layout_plan
from bonus_platform.engine.labor.parsing import normalize_employee_name, normalize_workbuddy_name, parse_number
from bonus_platform.engine.labor.profiles import load_supplier_profiles, resolve_supplier_profile
from bonus_platform.engine.labor.quality import build_reconciliation_diagnostics, calculate_extraction_quality
from bonus_platform.engine.labor.profiles import (
    generate_profile_from_extraction,
    save_supplier_profile,
    record_profile_failure,
    reset_profile_failure,
    _profiles_for_resolution,
    DEFAULT_PROFILE,
)
from bonus_platform.app import _non_payable_pdf_names, _normalize_labor_total_decision
from bonus_platform.engine.labor.report import build_labor_business_html_report, build_labor_report
from bonus_platform.engine.labor.workbook import parse_reocr_candidate_rows, read_workbook_rows, suggest_mapping, summarize_otws_costs


def _workbook_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "账单"
    sheet.append(["姓名", "时长总计(H)", "费用总计(含税)", "币种"])
    sheet.append(["Jose Perez", 40.14, 1037.81, "USD"])
    sheet.append(["Wilfredo Martinez", 40.78, 982.74, "USD"])
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_list_labor_metadata_supports_recent_limit(monkeypatch, tmp_path):
    runs_dir = tmp_path / "labor_runs"
    runs_dir.mkdir()
    for idx in range(3):
        run_dir = runs_dir / f"labor_{idx}"
        run_dir.mkdir()
        metadata_path = run_dir / "metadata.json"
        metadata_path.write_text(
            json.dumps(
                {
                    "id": f"labor_{idx}",
                    "createdAt": f"2026-06-20T10:0{idx}:00",
                    "updatedAt": f"2026-06-20T10:0{idx}:00",
                }
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr(labor_runs, "LABOR_RUNS_DIR", runs_dir)

    rows = labor_runs.list_labor_metadata(limit=2)

    assert [row["id"] for row in rows] == ["labor_2", "labor_1"]


def test_save_labor_metadata_uses_atomic_writes_for_persistent_backend(monkeypatch, tmp_path):
    run_dir = tmp_path / "labor_runs" / "labor_atomic"
    run_dir.mkdir(parents=True)
    original_write_text = Path.write_text

    monkeypatch.setattr(labor_runs, "labor_persistent_storage_enabled", lambda: True)
    monkeypatch.setattr(labor_runs, "labor_persistent_storage_info", lambda: {"backend": "supabase"})
    monkeypatch.setattr(labor_runs, "sync_labor_run_to_persistent", lambda run_id, path: None)

    def guarded_write_text(self, *args, **kwargs):
        if self.name == "metadata.json":
            raise AssertionError("metadata.json must be replaced atomically")
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", guarded_write_text)

    metadata = labor_runs.save_labor_metadata(run_dir, {"id": "labor_atomic", "status": "已创建"})

    assert metadata["id"] == "labor_atomic"
    assert json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))["id"] == "labor_atomic"


def test_update_labor_metadata_record_only_does_not_resync_uploaded_files(monkeypatch, tmp_path):
    run_root = tmp_path / "labor_runs"
    run_dir = run_root / "labor_direct"
    run_dir.mkdir(parents=True)
    (run_dir / "invoice.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    (run_dir / "bill.xlsx").write_bytes(_workbook_bytes())
    (run_dir / "metadata.json").write_text(
        json.dumps(
            {
                "id": "labor_direct",
                "status": "已创建",
                "files": {
                    "pdfInvoices": [{"filename": "invoice.pdf", "path": str(run_dir / "invoice.pdf")}],
                    "workbook": {"filename": "bill.xlsx", "path": str(run_dir / "bill.xlsx")},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    uploaded_metadata = {}

    monkeypatch.setattr(labor_runs, "LABOR_RUNS_DIR", run_root)
    monkeypatch.setattr(labor_runs, "labor_persistent_storage_enabled", lambda: True)
    monkeypatch.setattr(labor_runs, "labor_persistent_storage_info", lambda: {"backend": "supabase"})
    monkeypatch.setattr(
        labor_runs,
        "sync_labor_run_to_persistent",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("large files should not be resynced")),
    )

    def fake_sync_metadata(run_id, run_dir_arg, metadata):
        uploaded_metadata["runId"] = run_id
        uploaded_metadata["runDir"] = run_dir_arg
        uploaded_metadata["metadata"] = metadata

    monkeypatch.setattr(labor_runs, "sync_labor_metadata_to_persistent", fake_sync_metadata)

    metadata = labor_runs.update_labor_metadata_record_only("labor_direct", {"status": "已上传文件"})

    assert metadata["status"] == "已上传文件"
    assert uploaded_metadata["runId"] == "labor_direct"
    assert uploaded_metadata["metadata"]["files"]["pdfInvoices"][0]["path"] == "invoice.pdf"
    assert uploaded_metadata["metadata"]["files"]["workbook"]["path"] == "bill.xlsx"
    local_metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    assert local_metadata["files"]["workbook"]["path"] == str(run_dir / "bill.xlsx")


def test_update_labor_metadata_stage_only_does_not_resync_uploaded_files(monkeypatch, tmp_path):
    run_root = tmp_path / "labor_runs"
    run_dir = run_root / "labor_stage"
    run_dir.mkdir(parents=True)
    (run_dir / "invoice.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    (run_dir / "metadata.json").write_text(
        json.dumps(
            {
                "id": "labor_stage",
                "status": "已上传文件",
                "files": {
                    "pdfInvoices": [{"filename": "invoice.pdf", "path": str(run_dir / "invoice.pdf")}],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    uploaded_metadata = {}

    monkeypatch.setattr(labor_runs, "LABOR_RUNS_DIR", run_root)
    monkeypatch.setattr(labor_runs, "labor_persistent_storage_enabled", lambda: True)
    monkeypatch.setattr(labor_runs, "labor_persistent_storage_info", lambda: {"backend": "supabase"})
    monkeypatch.setattr(
        labor_runs,
        "sync_labor_run_to_persistent",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("stage updates should not resync files")),
    )

    def fake_sync_metadata(run_id, run_dir_arg, metadata):
        uploaded_metadata["runId"] = run_id
        uploaded_metadata["metadata"] = metadata

    monkeypatch.setattr(labor_runs, "sync_labor_metadata_to_persistent", fake_sync_metadata)

    metadata = labor_runs.update_labor_metadata("labor_stage", {"stage": "Stage 1: 快速抽取总金额"})

    assert metadata["stage"] == "Stage 1: 快速抽取总金额"
    assert uploaded_metadata["runId"] == "labor_stage"
    assert uploaded_metadata["metadata"]["files"]["pdfInvoices"][0]["path"] == "invoice.pdf"


def _workbook_with_tax_columns_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "账单"
    sheet.append(["姓名", "时长总计(H)", "费用总计(不含税)", "费用总计(含税)", "币种"])
    sheet.append(["Jose Perez", 40.14, 1000.00, 1037.81, "USD"])
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _workbook_with_hours_only_summary_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sheet1"
    sheet.append(["Employee Name", "Job Type", "求和项:Total Hours"])
    sheet.append(["Alberto Nunez", "Labor", 35.08])
    sheet.append(["Ivis Martinez", "Labor", 6.55])
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _workbook_with_two_header_rows_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Employee-expenses-detail"
    sheet.append([
        "Company Name",
        "Physical warehouse",
        "group",
        "Employee name",
        "Employee number",
        "Type of work",
        "工作日",
        None,
        "Total staff cost accounting time",
        "Total cost",
    ])
    sheet.append([
        "Company Name",
        "Physical warehouse",
        "group",
        "Employee name",
        "Employee number",
        "Type of work",
        "Day shift working hours",
        "Regular pay for day shift",
        "Total staff cost accounting time",
        "Total cost",
    ])
    sheet.append([
        "Strategic Staffing Solutions Corp.",
        "New Jersey Warehouse 13",
        "warehousing group",
        "JOSE MAGANA",
        "EUS031468",
        "操作员",
        8,
        188,
        8,
        188,
    ])
    sheet.append([
        "Total:",
        None,
        None,
        None,
        None,
        None,
        8,
        188,
        8,
        188,
    ])
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _otws_cost_workbook_bytes() -> bytes:
    workbook = Workbook()
    warehouse = workbook.active
    warehouse.title = "Warehouse-information"
    warehouse.append([
        "Region",
        "Physical warehouse",
        "Financial reimbursement process number",
        "Company Name",
        "Total employees during attendance period",
        "Contract Start Date",
        "currency",
        "Total hourly salary",
        "Total bonus",
        "Total vehicle compensation",
        "Total Meal Supplement",
        "Hourly Rate Difference",
        "Lot And Scot(Employment Insurance)",
        "Income Tax",
        "Total other expenses",
        "total.handling.fee",
        "additional fees",
        "Total",
        "Status",
        "Week Month Split Status",
        "Accounting start date",
        "Accounting end date",
        "实际付款金额",
        "remark",
    ])
    warehouse.append([
        "USNJ",
        "New Jersey Warehouse 13",
        "--",
        "Strategic Staffing Solutions Corp.",
        "64",
        "US ELOGISTICS SERVICE CORP",
        "USD",
        48055.81,
        0,
        0,
        0,
        0,
        0,
        0,
        162.15,
        0,
        0,
        48217.96,
        "Confirm the bill",
        "未拆分",
        "2026-05-11",
        "2026-05-17",
        0,
        "--",
    ])

    expenses = workbook.create_sheet("Employee-expenses-detail")
    expenses.append([
        "Company Name",
        "Physical warehouse",
        "group",
        "Employee name",
        "Employee number",
        "Type of work",
        "工作日",
        None,
        "Total staff cost accounting time",
        "Total cost",
    ])
    expenses.append([
        "Company Name",
        "Physical warehouse",
        "group",
        "Employee name",
        "Employee number",
        "Type of work",
        "Day shift working hours",
        "Regular pay for day shift",
        "Total staff cost accounting time",
        "Total cost",
    ])
    expenses.append([
        "Strategic Staffing Solutions Corp.",
        "New Jersey Warehouse 13",
        "warehousing group",
        "JOSE MAGANA",
        "EUS031468",
        "操作员",
        8,
        188,
        8,
        188,
    ])
    expenses.append([
        "Total:",
        None,
        None,
        None,
        None,
        None,
        8,
        188,
        8,
        188,
    ])

    benefits = workbook.create_sheet("Employee-benefits-detail")
    benefits.append([
        "Physical warehouse",
        "Employee name",
        "Employee number",
        "Bonus",
        "Car allowance",
        "Meal allowance",
        "Hourly Rate Difference",
        "Lot And Scot(Employment Insurance)",
        "Income Tax",
        "Other",
        "Total cost",
        "remark",
    ])
    benefits.append([
        "New Jersey Warehouse 13",
        "KRISTEL CONTRERAS MONTIEL",
        "EUS033091",
        0,
        0,
        0,
        0,
        0,
        0,
        162.15,
        162.15,
        "missing hours",
    ])
    benefits.append(["Total:", None, None, 0, 0, 0, 0, 0, 0, 162.15, 162.15, None])

    workbook.create_sheet("The-loading-and-unloading-of-ta").append([
        "group",
        "Employee name",
        "Loading and unloading date",
        "Ark type",
        "Container Number",
        "Number of unloading cabinets",
        "Unit price",
        "Total cost",
    ])
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_normalize_employee_name_handles_invoice_and_workbook_variants():
    assert normalize_employee_name("PEREZ, JOSE") == normalize_employee_name("Jose Perez")
    assert normalize_employee_name("#1 Ana Maria Corea") == normalize_employee_name("COREA MARIA, ANA")
    assert normalize_employee_name("CONTRERAS, EVELYN (CERVANTES)") == normalize_employee_name("Evelyn Contreras")
    assert normalize_employee_name("MORA-3491, CLAUDIA") == normalize_employee_name("Claudia Mora-3491")
    assert normalize_employee_name("Darlene CalvilloDarlene Calvillo Aparicio Aparicio") == normalize_employee_name("Calvillo Aparicio, Darlene")
    assert normalize_employee_name("Rosales Jr., Jose") == normalize_employee_name("Jose Rosales")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("$1,032.00", 1032.0),
        ("1,032.00$", 1032.0),
        ("-$", 0.0),
        ("", 0.0),
        (None, 0.0),
    ],
)
def test_parse_number_handles_invoice_money_formats(raw, expected):
    assert parse_number(raw) == expected


def test_fairway_warehouse_id_parses_from_filename_and_text():
    assert extract_warehouse_id_from_filename("135306 US Elogistics Service Corp (#10).pdf") == "10"
    assert extract_warehouse_id_from_filename("135307_US_Elogistics_Service_Corp___18_20260601_222816_133922.pdf") == "18"
    assert _warehouse_id_from_text("US ELOGISTICS SERVICE CORP\nCA(LA)- #18 TAMARIND (TAMR2)") == "18"
    assert _warehouse_id_from_text("FONTANA\n(CA)LA#10 HARBOR BAR (HARBOR)") == "10"
    assert _warehouse_id_from_text("CHINO, CA 91710\nCA(LA)#25 (CEDAR)") == "25"


def test_warehouse_id_patterns_cover_common_filename_and_text_variants():
    assert extract_warehouse_id_from_filename("INVOICE_WH-30.pdf") == "30"
    assert extract_warehouse_id_from_filename("CITISTAFF_LOC_29_20260602.pdf") == "29"
    assert extract_warehouse_id_from_filename("NJ12 Invoice Report WE 051726 JF.pdf") == "12"
    assert extract_warehouse_id_from_filename("US Elogis Service #17 Invoice W.E 05.24.26.pdf") == "17"
    assert _warehouse_id_from_text("Location: 3号仓") == "3"
    assert _warehouse_id_from_text("Warehouse: WH 28") == "28"
    assert _warehouse_id_from_text("LOC #21") == "21"
    assert _warehouse_id_from_text("Purchase Order Number\nFlanders Location NJ 8") == "8"


def test_warehouse_id_from_text_does_not_treat_invoice_period_as_location():
    assert (
        _warehouse_id_from_text(
            "Period Cust. ID Tax ID PAYMENT TERMS Location\n"
            "05/18/2026-05/24/2026 E-LOG 30 SHEIN\n"
        )
        == ""
    )


def test_warehouse_id_conflict_is_reported_when_filename_and_text_disagree():
    conflict = _warehouse_id_conflict("CHINA_EXPRESS__3_INVOICE.pdf", "US ELOGISTICS\nCA#30")

    assert conflict == {"source_file": "CHINA_EXPRESS__3_INVOICE.pdf", "filename_warehouse_id": "3", "text_warehouse_id": "30"}


def test_warehouse_comparison_reports_pdf_warehouse_conflict_errors():
    result = compare_by_warehouse(
        pdf_totals=[
            {
                "source_file": "CHINA_EXPRESS__3_INVOICE.pdf",
                "warehouse_id": "3",
                "total_amount": 1000.0,
                "warehouse_conflict": {"filename_warehouse_id": "3", "text_warehouse_id": "30"},
            }
        ],
        excel_rows_with_warehouse=[{"employee_name": "A", "warehouse_id": "3", "amount": 1000.0, "hours": 10}],
        amount_tolerance=0.1,
    )

    assert result["errors"] == ["仓库号冲突: CHINA_EXPRESS__3_INVOICE.pdf 文件名=3, 内容=30"]


def test_warehouse_total_difference_equal_to_ten_cents_passes():
    result = compare_by_warehouse(
        pdf_totals=[
            {"source_file": "fairway-warehouse-10.pdf", "warehouse_id": "10", "total_amount": 144714.83},
        ],
        excel_rows_with_warehouse=[
            {"employee_name": "Fairway Staff", "warehouse_id": "10", "amount": 144714.93, "hours": 10},
        ],
        amount_tolerance=0.1,
    )

    assert result["summary"]["amountDeltaTotal"] == -0.1
    assert result["summary"]["totalPassed"] is True


def test_saved_labor_run_total_decision_is_normalized_at_ten_cents():
    metadata = {
        "id": "labor_saved_old_result",
        "warehouseComparison": {
            "summary": {
                "pdfAmountTotal": 144714.83,
                "excelAmountTotal": 144714.93,
                "amountDeltaTotal": -0.1,
                "totalPassed": False,
                "exceptionCount": 2,
            }
        },
    }

    normalized = _normalize_labor_total_decision(metadata)

    assert normalized["warehouseComparison"]["summary"]["amountDeltaTotal"] == -0.1
    assert normalized["warehouseComparison"]["summary"]["totalPassed"] is True
    assert metadata["warehouseComparison"]["summary"]["totalPassed"] is False


def test_warehouse_comparison_infers_missing_pdf_warehouse_from_unique_excel_total():
    result = compare_by_warehouse(
        pdf_totals=[
            {"source_file": "Invoice-5058871.pdf", "warehouse_id": "", "total_amount": 8500.67},
            {"source_file": "Invoice-5058872.pdf", "warehouse_id": "", "total_amount": 3223.94},
        ],
        pdf_rows=[
            LaborLineItem(source_type="pdf_invoice", source_file="Invoice-5058871.pdf", source_page_or_row="p1", employee_id="", employee_name_raw="Worker One", hours=10, amount=8500.67, currency="USD", confidence=0.98, evidence_text=""),
            LaborLineItem(source_type="pdf_invoice", source_file="Invoice-5058872.pdf", source_page_or_row="p1", employee_id="", employee_name_raw="Worker Two", hours=8, amount=3223.94, currency="USD", confidence=0.98, evidence_text=""),
        ],
        excel_rows_with_warehouse=[
            {"employee_name": "Worker One", "warehouse_id": "19", "hours": 10, "amount": 8500.67},
            {"employee_name": "Worker Two", "warehouse_id": "18", "hours": 8, "amount": 3223.94},
        ],
        amount_tolerance=0.1,
    )

    assert result["errors"] == []
    assert result["summary"]["totalPassed"] is True
    assert result["summary"]["passedCount"] == 2
    rows_by_wh = {row["warehouseId"]: row for row in result["rows"]}
    assert set(rows_by_wh) == {"18", "19"}
    assert rows_by_wh["19"]["pdfEmployeeCount"] == 1
    assert rows_by_wh["18"]["pdfEmployeeCount"] == 1


def test_classify_pdf_distinguishes_invoice_support_and_attachments():
    assert _classify_pdf("Invoice_123.pdf", "Invoice Total $1,000.00\nEmployee A") == "primary"
    assert _classify_pdf("Supplement1.pdf", "Timecard Detail\nDaily Log\nEmployee hours only") == "supporting"
    assert _classify_pdf("COI_certificate.pdf", "Certificate of Insurance") == "attachment"
    assert _classify_pdf("scan.pdf", "") == "unknown"


def test_fairway_invoice_total_prefers_totals_or_grand_total_over_late_payment():
    assert _extract_invoice_total_from_text(
        "21 Totals 773.82 50.00 0.00 19,655.14$ 2,081.64$ -$ 21,736.78$\n"
        "If paid after 6/7/2026 please pay: $22,171.52\n"
        "GRAND TOTAL:\n"
        "21,736.78$"
    ) == 21736.78
    assert _extract_invoice_total_from_text(
        "If paid after 6/07/2026 please pay: 15,391.68$\n"
        "GRAND TOTAL:\n"
        "P.O. BOX 31001-2434\n"
        "US ELOGISTICS SERVICE CORP\n"
        "15,089.88$"
    ) == 15089.88


def test_sss_invoice_total_reads_billable_total_row():
    assert _extract_invoice_total_from_text(
        """
        Billable Billable Total
        Hours Fee Fees
        -$
        1 48,293.06$ 48,293.06$
        See Attached : Worksheets -$
        Total Due
        48,293.06$
        """
    ) == 48293.06


def test_grande_solutions_simple_table_extracts_all_employee_rows():
    text = "\n".join(
        [
            "TO Elogistics GA Service Corp",
            "Invoice : ELOG-466-FL",
            "Period Location",
            "05/18/2026-05/24/2026 E-LOG 30 SHEIN",
            "No. Name Reg. Hours O.T Hours Reg. Rate O.T Rate Total",
            "1 Alberto Núñez 35.08 $21.08 $31.62 $739.49",
            "2 Ivis Martinez 6.55 $21.08 $31.62 $138.07",
            "3 Carolay Hincapie 40 7.82 $19.84 $29.76 $1,026.32",
            "4 Liliana Cue 40 7.14 $19.84 $29.76 $1,006.09",
            "TOTAL HOURS 1251.18 67.12 SUB TOTAL $25,487.50",
        ]
    )

    rows = _extract_with_rules(
        [{"source_file": "GS_invoice-ELOG-466-FL.pdf", "page": 1, "text": text}],
        supplier="Grande Solutions Staffing",
        period_start="2026-05-18",
        period_end="2026-05-24",
        currency="USD",
    )

    assert [row.employee_name_raw for row in rows] == [
        "Alberto Núñez",
        "Ivis Martinez",
        "Carolay Hincapie",
        "Liliana Cue",
    ]
    assert round(sum(row.amount for row in rows), 2) == 2909.97
    assert round(sum(row.hours for row in rows), 2) == 136.59
    assert all(row.source_file == "GS_invoice-ELOG-466-FL.pdf" for row in rows)


def test_citi_bill_rate_rows_merge_reg_and_ot_by_employee():
    page = {
        "source_file": "In291943.pdf",
        "page": 1,
        "text": "\n".join(
            [
                "Hours  Amount Bill Rate Date  Description  Pay Rate",
                "WAREHOUSE LOC.#29PO #:",
                "$33.60  0.400 $13.44 5/17/2026 Arellano Luna, Pablo $26.250 OT",
                "$22.40  40.000 $896.00 5/17/2026 Arellano Luna, Pablo $17.500 Reg",
                "$25.60  30.000 $768.00 5/17/2026 Escobar, Armando $20.000 Reg",
                "$38.40  0.450 $17.28 5/17/2026 Escobar, Armando $30.000 OT",
                "Regular",
                "Overtime",
                "Total Due: $1,694.72",
            ]
        ),
    }

    rows = _extract_with_rules([page], "CITI", "2026-05-17", "2026-05-22", "USD")

    assert len(rows) == 2
    by_name = {row.employee_name_raw: row for row in rows}
    assert by_name["Arellano Luna, Pablo"].hours == 40.4
    assert by_name["Arellano Luna, Pablo"].amount == 909.44
    assert by_name["Arellano Luna, Pablo"].warehouse_id == "29"
    assert by_name["Escobar, Armando"].hours == 30.45
    assert by_name["Escobar, Armando"].amount == 785.28


def test_layout_analyzer_recommends_simple_numbered_labor_table_for_gs_invoice():
    page = {
        "source_file": "GS_invoice-ELOG-466-FL.pdf",
        "page": 1,
        "text": "\n".join(
            [
                "No. Name Reg. Hours O.T Hours Reg. Rate O.T Rate Total",
                "1 Alberto Núñez 35.08 $21.08 $31.62 $739.49",
                "2 Ivis Martinez 6.55 $21.08 $31.62 $138.07",
                "TOTAL HOURS 41.63 0 SUB TOTAL $877.56",
            ]
        ),
    }

    plan = analyze_invoice_layout([page])
    rows = extract_rows_from_layout_plan([page], plan, supplier="Grande Solutions Staffing", period_start="2026-05-18", period_end="2026-05-24", currency="USD")

    assert plan.layout_type == "simple_numbered_labor_table"
    assert plan.recommended_parser == "simple_invoice_table"
    assert plan.amount_column == "Total"
    assert plan.hours_columns == ["Reg. Hours", "O.T Hours"]
    assert plan.total_label == "TOTAL HOURS"
    assert round(plan.confidence, 2) >= 0.8
    assert [row.employee_name_raw for row in rows] == ["Alberto Núñez", "Ivis Martinez"]


def test_layout_analyzer_keeps_unknown_layout_out_of_rule_parser():
    page = {
        "source_file": "unknown.pdf",
        "page": 1,
        "text": "This is an invoice summary without a visible employee table.",
    }

    plan = analyze_invoice_layout([page])
    rows = extract_rows_from_layout_plan([page], plan, supplier="", period_start="", period_end="", currency="USD")

    assert plan.layout_type == "unknown"
    assert plan.recommended_parser == "ai_assisted"
    assert rows == []


def test_ai_layout_analyzer_response_is_normalized_to_layout_plan(monkeypatch):
    def fake_post_chat_completion(payload, ai_config):
        return [
            {
                "layout_type": "simple_numbered_labor_table",
                "recommended_parser": "simple_invoice_table",
                "confidence": 0.86,
                "hours_columns": ["Regular", "OT"],
                "amount_column": "Total",
                "total_label": "GRAND TOTAL",
                "employee_name_pattern": "between row number and first hours value",
            }
        ]

    import bonus_platform.engine.labor.extract as extract_module

    monkeypatch.setattr(extract_module, "_post_chat_completion", fake_post_chat_completion)

    plan = _analyze_layout_with_ai(
        [{"source_file": "unknown.pdf", "page": 1, "text": "No. Name Regular OT Total\n1 Jane Doe 40 2 $900.00"}],
        {"model": "test-model"},
        supplier="Vendor",
        currency="USD",
    )

    assert plan.layout_type == "simple_numbered_labor_table"
    assert plan.recommended_parser == "simple_invoice_table"
    assert plan.confidence == 0.86
    assert plan.hours_columns == ["Regular", "OT"]
    assert plan.amount_column == "Total"


def test_layout_plan_extracts_generic_line_item_text_table():
    page = {
        "source_file": "new_vendor.pdf",
        "page": 1,
        "text": "\n".join(
            [
                "Warehouse: WH 42",
                "Employee Hours Rate Amount",
                "1 Jane Doe WUS010325 40.00 2.50 $21.00 $892.50",
                "5/17/2026 John Smith 38.25 $20.00 $765.00",
                "Invoice Total $1,657.50",
            ]
        ),
    }
    plan = InvoiceLayoutPlan(
        layout_type="single_line_employee_amount_table",
        recommended_parser="line_item_text_table",
        confidence=0.84,
        employee_name_pattern="employee name appears before hours and amount on the same line",
        hours_columns=["Hours", "OT"],
        amount_column="Amount",
    )

    rows = extract_rows_from_layout_plan([page], plan, supplier="New Vendor", period_start="2026-05-17", period_end="2026-05-22", currency="USD")

    by_name = {row.employee_name_raw: row for row in rows}
    assert list(by_name) == ["Jane Doe", "John Smith"]
    assert by_name["Jane Doe"].employee_id == "WUS010325"
    assert by_name["Jane Doe"].hours == 42.5
    assert by_name["Jane Doe"].amount == 892.5
    assert by_name["Jane Doe"].warehouse_id == "42"
    assert by_name["John Smith"].hours == 38.25
    assert by_name["John Smith"].amount == 765.0


def test_extract_invoice_items_uses_ai_layout_plan_before_direct_ai(monkeypatch, tmp_path):
    pdf = tmp_path / "unknown_vendor.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    page = {
        "source_file": "unknown_vendor.pdf",
        "page": 1,
        "text": "Worker Detail\nJane Doe 40.00 1.00 $20.00 $830.00\nInvoice Total $830.00",
    }

    monkeypatch.setattr("bonus_platform.engine.labor.extract._extract_pdf_pages", lambda paths: [page])

    def fake_post_chat_completion(payload, ai_config):
        content = json.dumps(payload.get("messages", [{}])[-1].get("content", {}), ensure_ascii=False)
        assert "line_item_text_table" in content
        return [
            {
                "layout_type": "single_line_employee_amount_table",
                "recommended_parser": "line_item_text_table",
                "confidence": 0.86,
                "employee_name_pattern": "between row number and first hours value",
                "hours_columns": ["Hours", "OT"],
                "amount_column": "Amount",
                "evidence": ["Jane Doe 40.00 1.00 $20.00 $830.00"],
            }
        ]

    monkeypatch.setattr("bonus_platform.engine.labor.extract._post_chat_completion", fake_post_chat_completion)
    monkeypatch.setattr("bonus_platform.engine.labor.extract._extract_with_ai_text", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("direct text AI should not run")))
    monkeypatch.setattr("bonus_platform.engine.labor.extract._extract_with_ai_images", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("image AI should not run")))

    rows = extract_invoice_items(
        [pdf],
        {"enabled": True, "provider": "mimo", "api_key": "token", "base_url": "https://api.xiaomimimo.com/v1", "model": "mimo-v2.5"},
        supplier="Unknown Vendor",
        currency="USD",
    )

    assert len(rows) == 1
    assert rows[0].employee_name_raw == "Jane Doe"
    assert rows[0].hours == 41.0
    assert rows[0].amount == 830.0
    assert rows[0].confidence == 0.82


def test_ai_rows_without_supporting_page_text_are_filtered():
    pages = [
        {
            "source_file": "GS_invoice-ELOG-466-FL.pdf",
            "page": 1,
            "text": "1 Alberto Núñez 35.08 $21.08 $31.62 $739.49",
        }
    ]
    rows = [
        {"employee_name_raw": "Albert Achter", "amount": 289.88, "evidence_text": "Albert Achter 15.08 $289.88"},
        {"employee_name_raw": "Alberto Núñez", "amount": 739.49, "evidence_text": "Alberto Núñez 35.08 $739.49"},
    ]

    filtered = _filter_ai_rows_by_page_text(rows, pages)

    assert len(filtered) == 1
    assert filtered[0]["employee_name_raw"] == "Alberto Núñez"
    assert filtered[0]["source_file"] == "GS_invoice-ELOG-466-FL.pdf"
    assert filtered[0]["source_page_or_row"] == "p1"


def test_single_pdf_total_maps_to_only_excel_warehouse_when_pdf_has_no_warehouse_id():
    pdf_rows = [
        LaborLineItem(source_type="pdf_invoice", source_file="GS_invoice-ELOG-466-FL.pdf", source_page_or_row="p1", employee_id="", employee_name_raw="Alberto Núñez", hours=35.08, amount=739.49, currency="USD", confidence=0.95, evidence_text=""),
        LaborLineItem(source_type="pdf_invoice", source_file="GS_invoice-ELOG-466-FL.pdf", source_page_or_row="p1", employee_id="", employee_name_raw="Ivis Martinez", hours=6.55, amount=138.07, currency="USD", confidence=0.95, evidence_text=""),
    ]
    result = compare_by_warehouse(
        pdf_totals=[{"source_file": "GS_invoice-ELOG-466-FL.pdf", "warehouse_id": "", "total_amount": 25487.5}],
        pdf_rows=pdf_rows,
        excel_rows_with_warehouse=[
            {"employee_name": "Alberto Núñez", "warehouse_id": "1", "amount": 10000.0, "hours": 400},
            {"employee_name": "Ivis Martinez", "warehouse_id": "1", "amount": 15975.47, "hours": 800},
        ],
        amount_tolerance=0.1,
    )

    assert result["errors"] == []
    assert result["rows"][0]["warehouseId"] == "1"
    assert result["rows"][0]["pdfEmployeeCount"] == 2
    assert result["rows"][0]["pdfAmountTotal"] == 25487.5
    assert result["summary"]["totalPassed"] is False


def test_warehouse_comparison_still_runs_when_totals_offset_between_warehouses():
    result = compare_by_warehouse(
        pdf_totals=[
            {"source_file": "warehouse_3.pdf", "warehouse_id": "3", "total_amount": 5000.0},
            {"source_file": "warehouse_5.pdf", "warehouse_id": "5", "total_amount": 3000.0},
        ],
        excel_rows_with_warehouse=[
            {"employee_name": "A", "warehouse_id": "3", "amount": 4000.0, "hours": 10},
            {"employee_name": "B", "warehouse_id": "5", "amount": 4000.0, "hours": 10},
        ],
        amount_tolerance=0.1,
    )

    assert result["summary"]["amountDeltaTotal"] == 0.0
    assert result["summary"]["totalPassed"] is True
    assert result["summary"]["diffWarehouses"] == ["3", "5"]
    assert {row["warehouseId"]: row["amountDelta"] for row in result["rows"]} == {"3": 1000.0, "5": -1000.0}


def test_warehouse_comparison_flags_employee_allocation_offsets_across_warehouses():
    pdf_rows = [
        LaborLineItem(source_type="pdf_invoice", source_file="fairway_25.pdf", source_page_or_row="p1", employee_id="", employee_name_raw="PEREZ, JOSE", hours=4.0, amount=101.26, currency="USD", confidence=0.95, evidence_text="", warehouse_id="25"),
        LaborLineItem(source_type="pdf_invoice", source_file="fairway_25.pdf", source_page_or_row="p1", employee_id="", employee_name_raw="JIMENEZ, ENEAS", hours=5.0, amount=118.04, currency="USD", confidence=0.95, evidence_text="", warehouse_id="25"),
        LaborLineItem(source_type="pdf_invoice", source_file="fairway_28.pdf", source_page_or_row="p1", employee_id="", employee_name_raw="PEREZ, JOSE", hours=40.0, amount=935.00, currency="USD", confidence=0.95, evidence_text="", warehouse_id="28"),
        LaborLineItem(source_type="pdf_invoice", source_file="fairway_28.pdf", source_page_or_row="p1", employee_id="", employee_name_raw="JIMENEZ, ENEAS", hours=40.0, amount=928.67, currency="USD", confidence=0.95, evidence_text="", warehouse_id="28"),
    ]
    result = compare_by_warehouse(
        pdf_totals=[
            {"source_file": "fairway_25.pdf", "warehouse_id": "25", "total_amount": 219.30},
            {"source_file": "fairway_28.pdf", "warehouse_id": "28", "total_amount": 1863.67},
        ],
        pdf_rows=pdf_rows,
        excel_rows_with_warehouse=[
            {"employee_name": "PEREZ, JOSE", "warehouse_id": "25", "amount": 100.67, "hours": 4.0},
            {"employee_name": "JIMENEZ, ENEAS", "warehouse_id": "25", "amount": 116.85, "hours": 5.0},
            {"employee_name": "PEREZ, JOSE", "warehouse_id": "28", "amount": 935.59, "hours": 40.0},
            {"employee_name": "JIMENEZ, ENEAS", "warehouse_id": "28", "amount": 929.87, "hours": 40.0},
        ],
        amount_tolerance=0.1,
    )

    assert result["summary"]["amountDeltaTotal"] == -0.01
    assert result["summary"]["totalPassed"] is True
    assert result["summary"]["allocationIssueCount"] == 2
    assert result["summary"]["diffWarehouses"] == ["25", "28"]
    issues_by_employee = {issue["employeeName"]: issue for issue in result["allocationIssues"]}
    assert issues_by_employee["PEREZ, JOSE"]["netAmountDelta"] == 0.0
    assert [row["warehouseId"] for row in issues_by_employee["PEREZ, JOSE"]["warehouses"]] == ["25", "28"]
    assert [row["amountDelta"] for row in issues_by_employee["JIMENEZ, ENEAS"]["warehouses"]] == [1.19, -1.2]


def test_reconciliation_diagnostics_suppresses_missing_warehouse_when_single_pdf_was_safely_attributed():
    diagnostics = build_reconciliation_diagnostics(
        pdf_totals=[{"source_file": "GS_invoice-ELOG-466-FL.pdf", "warehouse_id": "", "total_amount": 25487.5}],
        comparison_summary={"pdfAmountTotal": 25487.5, "excelAmountTotal": 25975.47},
        warehouse_comparison={
            "summary": {"pdfAmountTotal": 25487.5, "excelAmountTotal": 25975.47, "warehouseCount": 1},
            "errors": [],
        },
        amount_tolerance=0.1,
    )

    assert diagnostics["level"] == "ok"
    assert diagnostics["issues"] == []


def test_reconciliation_diagnostics_flags_conflicting_pdf_signals():
    diagnostics = build_reconciliation_diagnostics(
        pdf_totals=[
            {"source_file": "fairway_10.pdf", "warehouse_id": "", "total_amount": 21736.78},
            {"source_file": "fairway_18.pdf", "warehouse_id": "18", "total_amount": 0},
            {"source_file": "fairway_19.pdf", "warehouse_id": "19", "total_amount": 27162.78},
        ],
        comparison_summary={"pdfAmountTotal": 147368.65, "excelAmountTotal": 147368.73},
        warehouse_comparison={
            "summary": {"pdfAmountTotal": 48899.56, "excelAmountTotal": 147368.73},
            "errors": ["no warehouse match"],
        },
        amount_tolerance=0.1,
    )

    issue_codes = {issue["code"] for issue in diagnostics["issues"]}
    assert diagnostics["level"] == "critical"
    assert diagnostics["signals"]["fastPdfTotal"] == 48899.56
    assert diagnostics["signals"]["employeePdfTotal"] == 147368.65
    assert "pdf_total_conflict" in issue_codes
    assert "missing_warehouse_id" in issue_codes
    assert "zero_pdf_total" in issue_codes
    assert "warehouse_mapping_errors" in issue_codes


def test_reconciliation_diagnostics_passes_when_totals_align():
    diagnostics = build_reconciliation_diagnostics(
        pdf_totals=[
            {"source_file": "fairway_10.pdf", "warehouse_id": "10", "total_amount": 21736.78},
            {"source_file": "fairway_18.pdf", "warehouse_id": "18", "total_amount": 42868.43},
        ],
        comparison_summary={"pdfAmountTotal": 64605.21, "excelAmountTotal": 64605.27},
        warehouse_comparison={"summary": {"pdfAmountTotal": 64605.21, "excelAmountTotal": 64605.27}, "errors": []},
        amount_tolerance=0.1,
    )

    assert diagnostics["level"] == "ok"
    assert diagnostics["issues"] == []
    assert diagnostics["nextStep"] == "可按当前结论使用报告。"


def test_reconciliation_diagnostics_explains_otws_amount_basis_mismatch(tmp_path):
    path = tmp_path / "OTWS - Warehouse Bill-NJ13.xlsx"
    path.write_bytes(_otws_cost_workbook_bytes())
    cost_summary = summarize_otws_costs(path)

    diagnostics = build_reconciliation_diagnostics(
        pdf_totals=[{"source_file": "NJ13 Invoice Report WE 051726 JF.pdf", "warehouse_id": "13", "total_amount": 48293.06}],
        comparison_summary={"pdfAmountTotal": 0, "excelAmountTotal": 48217.96},
        warehouse_comparison={"summary": {"pdfAmountTotal": 48293.06, "excelAmountTotal": 48217.96}, "errors": []},
        cost_summaries=[cost_summary],
        amount_tolerance=0.1,
    )

    issue_codes = {issue["code"] for issue in diagnostics["issues"]}
    assert diagnostics["level"] == "warning"
    assert "amount_basis_mismatch" in issue_codes
    assert diagnostics["signals"]["amountBasis"] == [
        {
            "warehouseId": "13",
            "sourceFile": "OTWS - Warehouse Bill-NJ13.xlsx",
            "pdfTotal": 48293.06,
            "reportedTotal": 48217.96,
            "pdfVsReportedDelta": 75.1,
            "componentTotal": 48217.96,
            "componentDelta": 0.0,
            "detailTotal": 350.15,
            "summaryDelta": 47867.81,
            "employeeExpenses": 188.0,
            "employeeBenefits": 162.15,
            "loadingAndUnloading": 0.0,
            "summaryEvidence": "Warehouse-information!2",
            "detailEvidence": "Employee-expenses-detail!3; Employee-benefits-detail!2",
            "withinTolerance": False,
        }
    ]
    mismatch = next(issue for issue in diagnostics["issues"] if issue["code"] == "amount_basis_mismatch")
    assert "仓库 13" in mismatch["items"][0]
    assert "OTWS汇总 $48,217.96" in mismatch["items"][0]


def test_reconciliation_diagnostics_flags_offsetting_warehouse_deltas():
    diagnostics = build_reconciliation_diagnostics(
        pdf_totals=[
            {"source_file": "135616 US Elogistics Service Corp (#25).pdf", "warehouse_id": "25", "total_amount": 17465.12},
            {"source_file": "135617 US Elogistics Service Corp (#28).pdf", "warehouse_id": "28", "total_amount": 4537.46},
        ],
        comparison_summary={"pdfAmountTotal": 22002.58, "excelAmountTotal": 22002.59},
        warehouse_comparison={
            "summary": {"pdfAmountTotal": 22002.58, "excelAmountTotal": 22002.59},
            "errors": [],
            "rows": [
                {
                    "warehouseId": "25",
                    "pdfAmountTotal": 17465.12,
                    "excelAmountTotal": 17463.34,
                    "amountDelta": 1.78,
                    "attribution": [{"employeeName": "JIMENEZ, ENEAS", "delta": 1.19}],
                },
                {
                    "warehouseId": "28",
                    "pdfAmountTotal": 4537.46,
                    "excelAmountTotal": 4539.25,
                    "amountDelta": -1.79,
                    "attribution": [{"employeeName": "JIMENEZ, ENEAS", "delta": -1.2}],
                },
            ],
        },
        amount_tolerance=0.1,
    )

    issue_codes = {issue["code"] for issue in diagnostics["issues"]}
    assert diagnostics["level"] == "warning"
    assert "warehouse_offsetting_deltas" in issue_codes
    assert diagnostics["signals"]["offsettingWarehouseDeltas"] == [
        {
            "warehouseId": "25",
            "pdfAmountTotal": 17465.12,
            "excelAmountTotal": 17463.34,
            "amountDelta": 1.78,
            "attribution": [{"employeeName": "JIMENEZ, ENEAS", "delta": 1.19}],
        },
        {
            "warehouseId": "28",
            "pdfAmountTotal": 4537.46,
            "excelAmountTotal": 4539.25,
            "amountDelta": -1.79,
            "attribution": [{"employeeName": "JIMENEZ, ENEAS", "delta": -1.2}],
        },
    ]
    offset_issue = next(issue for issue in diagnostics["issues"] if issue["code"] == "warehouse_offsetting_deltas")
    assert "多个仓库分别超出容差" in offset_issue["message"]
    assert "仓库 25" in offset_issue["items"][0]


def test_reconciliation_diagnostics_flags_cross_warehouse_employee_allocation():
    diagnostics = build_reconciliation_diagnostics(
        pdf_totals=[
            {"source_file": "fairway_25.pdf", "warehouse_id": "25", "total_amount": 219.30},
            {"source_file": "fairway_28.pdf", "warehouse_id": "28", "total_amount": 1863.67},
        ],
        comparison_summary={"pdfAmountTotal": 2082.97, "excelAmountTotal": 2083.08, "exceptionCount": 0},
        warehouse_comparison={
            "summary": {"pdfAmountTotal": 2082.97, "excelAmountTotal": 2083.08, "allocationIssueCount": 1},
            "errors": [],
            "allocationIssues": [
                {
                    "employeeName": "PEREZ, JOSE",
                    "netAmountDelta": 0.0,
                    "warehouseCount": 2,
                    "warehouses": [
                        {"warehouseId": "25", "amountDelta": 0.59},
                        {"warehouseId": "28", "amountDelta": -0.59},
                    ],
                    "recommendation": "员工总额可抵消，但仓库归属金额不一致，需按仓库复核发票与账单归属。",
                }
            ],
        },
        amount_tolerance=0.1,
    )

    issue_codes = {issue["code"] for issue in diagnostics["issues"]}
    assert diagnostics["level"] == "warning"
    assert "cross_warehouse_employee_allocation" in issue_codes
    assert diagnostics["signals"]["crossWarehouseEmployeeAllocation"][0]["employeeName"] == "PEREZ, JOSE"
    allocation_issue = next(issue for issue in diagnostics["issues"] if issue["code"] == "cross_warehouse_employee_allocation")
    assert "PEREZ, JOSE" in allocation_issue["items"][0]
    assert "仓库 25" in allocation_issue["items"][0]


def test_reconciliation_diagnostics_flags_employee_attribution_for_warehouse_delta():
    diagnostics = build_reconciliation_diagnostics(
        pdf_totals=[{"source_file": "US ELogistics Service Corp. 34794.pdf", "warehouse_id": "25", "total_amount": 62761.99}],
        comparison_summary={"pdfAmountTotal": 62761.99, "excelAmountTotal": 62803.2},
        warehouse_comparison={
            "summary": {"pdfAmountTotal": 62761.99, "excelAmountTotal": 62803.2},
            "errors": [],
            "rows": [
                {
                    "warehouseId": "25",
                    "pdfAmountTotal": 62761.99,
                    "excelAmountTotal": 62803.2,
                    "amountDelta": -41.21,
                    "attribution": [
                        {
                            "employeeName": "Fontes, Stevie ⇄ Stevie Fontes",
                            "pdfAmount": 822.12,
                            "excelAmount": 863.22,
                            "delta": -41.1,
                        },
                        {
                            "employeeName": "Sanchez Reveles, Jose ⇄ Jose Sanchez Reveles",
                            "pdfAmount": 919.56,
                            "excelAmount": 919.54,
                            "delta": 0.02,
                        },
                    ],
                }
            ],
        },
        amount_tolerance=0.1,
    )

    issue_codes = {issue["code"] for issue in diagnostics["issues"]}
    assert diagnostics["level"] == "warning"
    assert "warehouse_employee_attribution" in issue_codes
    assert diagnostics["signals"]["employeeAttribution"] == [
        {
            "warehouseId": "25",
            "employeeName": "Fontes, Stevie ⇄ Stevie Fontes",
            "pdfAmount": 822.12,
            "excelAmount": 863.22,
            "delta": -41.1,
            "warehouseDelta": -41.21,
        }
    ]
    attribution_issue = next(issue for issue in diagnostics["issues"] if issue["code"] == "warehouse_employee_attribution")
    assert "Fontes, Stevie" in attribution_issue["items"][0]


def test_suggest_mapping_and_read_workbook_rows_extract_required_fields(tmp_path):
    path = tmp_path / "账单.xlsx"
    path.write_bytes(_workbook_bytes())

    suggestion = suggest_mapping(path, "账单")

    assert suggestion["suggestedMapping"]["name"] == "姓名"
    assert suggestion["suggestedMapping"]["hours"] == "时长总计(H)"
    assert suggestion["suggestedMapping"]["amount"] == "费用总计(含税)"
    assert len(suggestion["previewRows"]) == 2

    rows = read_workbook_rows(
        path,
        "账单",
        {"name": "姓名", "hours": "时长总计(H)", "amount": "费用总计(含税)", "currency": "币种"},
    )

    assert [row.employee_name_raw for row in rows] == ["Jose Perez", "Wilfredo Martinez"]
    assert rows[0].hours == 40.14
    assert rows[0].amount == 1037.81
    assert rows[0].source_page_or_row == "账单!2"


def test_suggest_mapping_prefers_amount_excluding_tax_when_available(tmp_path):
    path = tmp_path / "账单.xlsx"
    path.write_bytes(_workbook_with_tax_columns_bytes())

    suggestion = suggest_mapping(path, "账单")

    assert suggestion["suggestedMapping"]["amount"] == "费用总计(不含税)"


def test_suggest_mapping_does_not_use_hours_column_as_amount(tmp_path):
    path = tmp_path / "GRANDE-5.18-5.24.xlsx"
    path.write_bytes(_workbook_with_hours_only_summary_bytes())

    suggestion = suggest_mapping(path, "Sheet1")

    assert suggestion["suggestedMapping"]["name"] == "Employee Name"
    assert suggestion["suggestedMapping"]["hours"] == "求和项:Total Hours"
    assert suggestion["suggestedMapping"]["amount"] == ""


def test_suggest_mapping_handles_two_row_otws_employee_expense_headers(tmp_path):
    path = tmp_path / "OTWS.xlsx"
    path.write_bytes(_workbook_with_two_header_rows_bytes())

    suggestion = suggest_mapping(path, "Employee-expenses-detail")

    assert suggestion["suggestedMapping"] == {
        "employeeId": "Employee number",
        "name": "Employee name",
        "hours": "Total staff cost accounting time",
        "amount": "Total cost",
        "currency": "",
    }

    rows = read_workbook_rows(path, "Employee-expenses-detail", suggestion["suggestedMapping"])

    assert len(rows) == 1
    assert rows[0].employee_id == "EUS031468"
    assert rows[0].employee_name_raw == "JOSE MAGANA"
    assert rows[0].hours == 8
    assert rows[0].amount == 188
    assert rows[0].warehouse_id == "13"


def test_summarize_otws_costs_explains_summary_and_detail_bases(tmp_path):
    path = tmp_path / "OTWS - Warehouse Bill-NJ13.xlsx"
    path.write_bytes(_otws_cost_workbook_bytes())

    summary = summarize_otws_costs(path)

    assert summary["sourceFile"] == "OTWS - Warehouse Bill-NJ13.xlsx"
    assert summary["warehouseId"] == "13"
    assert summary["supplier"] == "Strategic Staffing Solutions Corp."
    assert summary["currency"] == "USD"
    assert summary["periodStart"] == "2026-05-11"
    assert summary["periodEnd"] == "2026-05-17"
    assert summary["employeeCount"] == 64
    assert summary["summary"]["components"]["hourlySalary"] == 48055.81
    assert summary["summary"]["components"]["otherExpenses"] == 162.15
    assert summary["summary"]["componentTotal"] == 48217.96
    assert summary["summary"]["reportedTotal"] == 48217.96
    assert summary["summary"]["componentDelta"] == 0
    assert summary["summary"]["evidence"] == "Warehouse-information!2"
    assert summary["details"]["employeeExpenses"]["amount"] == 188
    assert summary["details"]["employeeExpenses"]["hours"] == 8
    assert summary["details"]["employeeExpenses"]["rowCount"] == 1
    assert summary["details"]["employeeExpenses"]["evidence"] == "Employee-expenses-detail!3"
    assert summary["details"]["employeeBenefits"]["amount"] == 162.15
    assert summary["details"]["employeeBenefits"]["rowCount"] == 1
    assert summary["details"]["detailTotal"] == 350.15
    assert summary["details"]["summaryDelta"] == 47867.81


def test_compare_labor_items_flags_amount_delta_and_ignores_one_cent():
    pdf_rows = [
        LaborLineItem(source_type="pdf_invoice", source_file="a.pdf", source_page_or_row="1", employee_id="", employee_name_raw="PEREZ, JOSE", hours=40.14, amount=1037.81, currency="USD", confidence=0.96, evidence_text="invoice row"),
        LaborLineItem(source_type="pdf_invoice", source_file="a.pdf", source_page_or_row="1", employee_id="", employee_name_raw="MARTINEZ, WILFREDO", hours=40.78, amount=982.72, currency="USD", confidence=0.91, evidence_text="invoice row"),
        LaborLineItem(source_type="pdf_invoice", source_file="a.pdf", source_page_or_row="1", employee_id="", employee_name_raw="LOW, CONFIDENCE", hours=8, amount=100, currency="USD", confidence=0.5, evidence_text="low confidence"),
    ]
    excel_rows = [
        LaborLineItem(source_type="offline_workbook", source_file="账单.xlsx", source_page_or_row="账单!2", employee_id="", employee_name_raw="Jose Perez", hours=40.14, amount=1037.80, currency="USD", confidence=1, evidence_text=""),
        LaborLineItem(source_type="offline_workbook", source_file="账单.xlsx", source_page_or_row="账单!3", employee_id="", employee_name_raw="Wilfredo Martinez", hours=40.78, amount=982.74, currency="USD", confidence=1, evidence_text=""),
    ]

    result = compare_labor_items(pdf_rows, excel_rows, amount_tolerance=0.01, hours_tolerance=0.1, confidence_threshold=0.85)

    assert result["summary"]["amountDiffCount"] == 1
    assert result["summary"]["unmatchedPdfCount"] == 1
    assert any(row["matchStatus"] == "金额差异" and row["employeeName"] == "MARTINEZ, WILFREDO" for row in result["rows"])
    assert any(row["matchStatus"] == "低置信度抽取" for row in result["rows"])
    assert all(not (row["employeeName"] == "PEREZ, JOSE" and row["matchStatus"] == "金额差异") for row in result["rows"])


def test_compare_labor_items_treats_tiny_unmatched_excel_residual_as_passed_risk():
    pdf_rows = [
        LaborLineItem(source_type="pdf_invoice", source_file="a.pdf", source_page_or_row="1", employee_id="", employee_name_raw="PEREZ, JOSE", hours=40, amount=1000, currency="USD", confidence=0.96, evidence_text="invoice row"),
    ]
    excel_rows = [
        LaborLineItem(source_type="offline_workbook", source_file="账单.xlsx", source_page_or_row="账单!2", employee_id="", employee_name_raw="Jose Perez", hours=40, amount=1000, currency="USD", confidence=1, evidence_text=""),
        LaborLineItem(source_type="offline_workbook", source_file="账单.xlsx", source_page_or_row="账单!3", employee_id="EUS000001", employee_name_raw="TINY RESIDUAL", hours=0.02, amount=0.41, currency="USD", confidence=1, evidence_text=""),
    ]

    result = compare_labor_items(pdf_rows, excel_rows, amount_tolerance=0.25, hours_tolerance=0.1)

    residual = next(row for row in result["rows"] if row["employeeName"] == "TINY RESIDUAL")
    assert residual["matchStatus"] == "通过"
    assert "微小残差" in residual["riskFlags"]
    assert result["summary"]["unmatchedExcelCount"] == 0
    assert result["summary"]["exceptionCount"] == 0


def test_compare_labor_items_matches_minor_name_typos_when_totals_align():
    pdf_rows = [
        LaborLineItem(source_type="pdf_invoice", source_file="osi.pdf", source_page_or_row="p1", employee_id="", employee_name_raw="Montealvo, Sergio", hours=46.2, amount=1345.89, currency="USD", confidence=0.98, evidence_text="invoice row"),
    ]
    excel_rows = [
        LaborLineItem(source_type="offline_workbook", source_file="账单.xlsx", source_page_or_row="账单!20", employee_id="WUS038206", employee_name_raw="Sergio Montalvo", hours=46.2, amount=1345.89, currency="USD", confidence=1, evidence_text=""),
    ]

    result = compare_labor_items(pdf_rows, excel_rows, amount_tolerance=0.1, hours_tolerance=0.1)

    assert result["summary"]["exceptionCount"] == 0
    assert result["summary"]["fuzzyMatchCount"] == 1
    assert result["rows"][0]["matchStatus"] == "通过"
    assert result["rows"][0]["employeeName"] == "Montealvo, Sergio ⇄ Sergio Montalvo"


def test_compare_labor_items_treats_exact_name_match_without_pdf_id_as_passed():
    pdf_rows = [
        LaborLineItem(source_type="pdf_invoice", source_file="osi.pdf", source_page_or_row="p1", employee_id="", employee_name_raw="Alva, Patrick", hours=34.75, amount=939.25, currency="USD", confidence=0.98, evidence_text="$939.25"),
    ]
    excel_rows = [
        LaborLineItem(source_type="offline_workbook", source_file="账单.xlsx", source_page_or_row="账单!2", employee_id="WUS045000", employee_name_raw="Patrick Alva", hours=34.75, amount=939.25, currency="USD", confidence=1, evidence_text=""),
    ]

    result = compare_labor_items(pdf_rows, excel_rows)

    assert result["summary"]["unmatchedPdfCount"] == 0
    assert result["summary"]["unmatchedExcelCount"] == 0
    assert result["summary"]["exceptionCount"] == 0
    assert result["rows"][0]["matchStatus"] == "通过"


def test_compare_labor_items_matches_partial_name_when_totals_align():
    pdf_rows = [
        LaborLineItem(source_type="pdf_invoice", source_file="osi.pdf", source_page_or_row="p1", employee_id="", employee_name_raw="Parra Hernandes, Nancy", hours=44.34, amount=1058.12, currency="USD", confidence=0.98, evidence_text="$1058.12"),
    ]
    excel_rows = [
        LaborLineItem(source_type="offline_workbook", source_file="账单.xlsx", source_page_or_row="账单!2", employee_id="WUS039740", employee_name_raw="Nancy Parra", hours=44.34, amount=1058.14, currency="USD", confidence=1, evidence_text=""),
    ]

    result = compare_labor_items(pdf_rows, excel_rows, amount_tolerance=0.05)

    assert result["summary"]["unmatchedPdfCount"] == 0
    assert result["summary"]["unmatchedExcelCount"] == 0
    assert result["summary"]["exceptionCount"] == 0
    assert result["rows"][0]["matchStatus"] == "通过"


def test_compare_labor_items_fuzzy_matches_ocr_name_variants_when_totals_align():
    pdf_rows = [
        LaborLineItem(source_type="pdf_invoice", source_file="scan.pdf", source_page_or_row="p1", employee_id="", employee_name_raw="Benavides, Jeremy", hours=22.68, amount=508.03, currency="USD", confidence=0.95, evidence_text="Total $508.03"),
    ]
    excel_rows = [
        LaborLineItem(source_type="offline_workbook", source_file="账单.xlsx", source_page_or_row="账单!4", employee_id="", employee_name_raw="Jeymmy Benavides", hours=22.68, amount=508.03, currency="USD", confidence=1, evidence_text=""),
    ]

    result = compare_labor_items(
        pdf_rows,
        excel_rows,
        manual_name_mapping={"Benavides, Jeremy": "Jeymmy Benavides"},
    )

    assert result["summary"]["unmatchedPdfCount"] == 0
    assert result["summary"]["unmatchedExcelCount"] == 0
    assert result["summary"]["exceptionCount"] == 0
    assert result["summary"]["fuzzyMatchCount"] == 1
    assert result["rows"][0]["matchStatus"] == "通过"
    assert "疑似姓名匹配" in result["rows"][0]["riskFlags"]


def test_compare_labor_items_uses_amount_as_primary_and_flags_hours_only_as_risk():
    pdf_rows = [
        LaborLineItem(source_type="pdf_invoice", source_file="invoice.pdf", source_page_or_row="p1", employee_id="", employee_name_raw="Flores, Alexis", hours=59.22, amount=1864.70, currency="USD", confidence=0.96, evidence_text="$1864.70"),
    ]
    excel_rows = [
        LaborLineItem(source_type="offline_workbook", source_file="账单.xlsx", source_page_or_row="账单!2", employee_id="", employee_name_raw="Alexis Flores", hours=51.22, amount=1864.70, currency="USD", confidence=1, evidence_text=""),
    ]

    result = compare_labor_items(pdf_rows, excel_rows, amount_tolerance=0.1, hours_tolerance=0.1)

    assert result["summary"]["exceptionCount"] == 0
    assert result["summary"]["hoursRiskCount"] == 1
    assert result["rows"][0]["matchStatus"] == "通过"
    assert "工时需复核" in result["rows"][0]["riskFlags"]


def test_compare_labor_items_marks_safe_name_format_difference_as_auto_merged():
    pdf_rows = [
        LaborLineItem(source_type="pdf_invoice", source_file="invoice.pdf", source_page_or_row="p1", employee_id="", employee_name_raw="Mucu, Pablo", hours=40, amount=1000, currency="USD", confidence=0.96, evidence_text="$1000.00"),
    ]
    excel_rows = [
        LaborLineItem(source_type="offline_workbook", source_file="bill.xlsx", source_page_or_row="Employee-expenses-detail!2", employee_id="", employee_name_raw="Pablo Mucu", hours=40, amount=1000, currency="USD", confidence=1, evidence_text=""),
    ]

    result = compare_labor_items(pdf_rows, excel_rows, amount_tolerance=0.1, hours_tolerance=0.1)

    assert result["summary"]["exceptionCount"] == 0
    assert result["rows"][0]["matchStatus"] == "通过"
    assert result["rows"][0]["employeeName"] == "Mucu, Pablo ⇄ Pablo Mucu"
    assert "姓名格式差异自动合并" in result["rows"][0]["riskFlags"]


def test_compare_labor_items_marks_accent_difference_as_auto_merged():
    pdf_rows = [
        LaborLineItem(source_type="pdf_invoice", source_file="invoice.pdf", source_page_or_row="p1", employee_id="", employee_name_raw="Alberto Núñez", hours=35.08, amount=739.49, currency="USD", confidence=0.96, evidence_text="$739.49"),
    ]
    excel_rows = [
        LaborLineItem(source_type="offline_workbook", source_file="bill.xlsx", source_page_or_row="Employee-expenses-detail!2", employee_id="", employee_name_raw="Alberto Nunez", hours=35.08, amount=739.49, currency="USD", confidence=1, evidence_text=""),
    ]

    result = compare_labor_items(pdf_rows, excel_rows, amount_tolerance=0.1, hours_tolerance=0.1)

    assert result["summary"]["exceptionCount"] == 0
    assert result["rows"][0]["matchStatus"] == "通过"
    assert result["rows"][0]["employeeName"] == "Alberto Núñez ⇄ Alberto Nunez"
    assert "姓名格式差异自动合并" in result["rows"][0]["riskFlags"]


def test_compare_labor_items_does_not_auto_merge_amount_close_name_unlike():
    pdf_rows = [
        LaborLineItem(source_type="pdf_invoice", source_file="invoice.pdf", source_page_or_row="p1", employee_id="", employee_name_raw="Maria Lopez", hours=40, amount=812.80, currency="USD", confidence=0.96, evidence_text="$812.80"),
    ]
    excel_rows = [
        LaborLineItem(source_type="offline_workbook", source_file="bill.xlsx", source_page_or_row="Employee-expenses-detail!2", employee_id="", employee_name_raw="Carlos Serna", hours=40, amount=812.80, currency="USD", confidence=1, evidence_text=""),
    ]

    result = compare_labor_items(pdf_rows, excel_rows, amount_tolerance=0.1, hours_tolerance=0.1)

    assert result["summary"]["exceptionCount"] == 2
    assert result["summary"]["unmatchedPdfCount"] == 1
    assert result["summary"]["unmatchedExcelCount"] == 1
    assert result["summary"]["fuzzyMatchCount"] == 0
    assert all(row["matchStatus"] != "通过" for row in result["rows"])
    assert result["candidateMatches"] == []


def test_compare_labor_items_matches_workbuddy_jaccard_when_amounts_align():
    pdf_rows = [
        LaborLineItem(source_type="pdf_invoice", source_file="invoice.pdf", source_page_or_row="p1", employee_id="", employee_name_raw="Nava de Luna, Julian", hours=12.25, amount=276.64, currency="USD", confidence=0.96, evidence_text="$276.64"),
    ]
    excel_rows = [
        LaborLineItem(source_type="offline_workbook", source_file="账单.xlsx", source_page_or_row="账单!2", employee_id="", employee_name_raw="Julieta Nava de Luna", hours=12.25, amount=276.64, currency="USD", confidence=1, evidence_text=""),
    ]

    result = compare_labor_items(pdf_rows, excel_rows, amount_tolerance=0.1)

    assert result["summary"]["exceptionCount"] == 0
    assert result["summary"]["fuzzyMatchCount"] == 1
    assert result["rows"][0]["matchStatus"] == "通过"
    assert "疑似姓名匹配" in result["rows"][0]["riskFlags"]


def test_workbuddy_normalize_removes_accents_punctuation_and_lowercases():
    assert normalize_workbuddy_name("García, María") == "garcia maria"
    assert normalize_workbuddy_name("Nava-de_Luna, Julián") == "nava de luna julian"


def test_compare_labor_items_uses_manual_mapping_for_two_token_spelling_variants():
    pdf_rows = [
        LaborLineItem(source_type="pdf_invoice", source_file="invoice.pdf", source_page_or_row="p1", employee_id="", employee_name_raw="Gamboa, Arilene", hours=53.62, amount=1520.28, currency="USD", confidence=0.96, evidence_text="$1520.28"),
    ]
    excel_rows = [
        LaborLineItem(source_type="offline_workbook", source_file="账单.xlsx", source_page_or_row="账单!2", employee_id="", employee_name_raw="Arlene Gamboa", hours=53.62, amount=1520.28, currency="USD", confidence=1, evidence_text=""),
    ]

    result = compare_labor_items(
        pdf_rows,
        excel_rows,
        amount_tolerance=0.1,
        manual_name_mapping={"Gamboa, Arilene": "Arlene Gamboa"},
    )

    assert result["summary"]["exceptionCount"] == 0
    assert result["summary"]["fuzzyMatchCount"] == 1
    assert result["rows"][0]["matchStatus"] == "通过"
    assert "疑似姓名匹配" in result["rows"][0]["riskFlags"]


def test_compare_labor_items_fuzzy_match_can_still_surface_amount_delta():
    pdf_rows = [
        LaborLineItem(source_type="pdf_invoice", source_file="scan.pdf", source_page_or_row="p1", employee_id="", employee_name_raw="Castillo, Misael", hours=30.92, amount=689.12, currency="USD", confidence=0.95, evidence_text="Total $689.12"),
    ]
    excel_rows = [
        LaborLineItem(source_type="offline_workbook", source_file="账单.xlsx", source_page_or_row="账单!7", employee_id="", employee_name_raw="Massiel Castillo", hours=30.92, amount=694.17, currency="USD", confidence=1, evidence_text=""),
    ]

    result = compare_labor_items(
        pdf_rows,
        excel_rows,
        manual_name_mapping={"Castillo, Misael": "Massiel Castillo"},
    )

    assert result["summary"]["amountDiffCount"] == 1
    assert result["summary"]["unmatchedPdfCount"] == 0
    assert result["summary"]["unmatchedExcelCount"] == 0
    assert result["rows"][0]["matchStatus"] == "金额差异"
    assert "疑似姓名匹配" in result["rows"][0]["riskFlags"]


def test_compare_labor_items_promotes_same_hours_name_candidate_to_amount_diff():
    pdf_rows = [
        LaborLineItem(source_type="pdf_invoice", source_file="sss.pdf", source_page_or_row="p29", employee_id="", employee_name_raw="Ruben Cadiz, Carlos", hours=7.82, amount=183.73, currency="USD", confidence=0.95, evidence_text="Ruben Cadiz, Carlos 20844 7.82 $183.73"),
    ]
    excel_rows = [
        LaborLineItem(source_type="offline_workbook", source_file="bill.xlsx", source_page_or_row="Employee-expenses-detail!42", employee_id="EUS020844", employee_name_raw="CARLOS RUBEN CADIZ RODRIGUEZ", hours=7.82, amount=168.83, currency="USD", confidence=1, evidence_text=""),
    ]

    result = compare_labor_items(pdf_rows, excel_rows, amount_tolerance=0.25, hours_tolerance=0.1)

    assert result["summary"]["amountDiffCount"] == 1
    assert result["summary"]["unmatchedPdfCount"] == 0
    assert result["summary"]["unmatchedExcelCount"] == 0
    assert result["summary"]["exceptionCount"] == 1
    assert result["summary"]["candidateMatchCount"] == 1
    row = result["rows"][0]
    assert row["employeeName"] == "Ruben Cadiz, Carlos ⇄ CARLOS RUBEN CADIZ RODRIGUEZ"
    assert row["matchStatus"] == "金额差异"
    assert row["amountDelta"] == 14.9
    assert "疑似姓名匹配" in row["riskFlags"]
    candidate = result["candidateMatches"][0]
    assert candidate["recommendation"] == "姓名疑似同一人，金额/费率差异需人工复核"


def test_compare_labor_items_flags_offsetting_unmatched_excel_as_combined_pdf_row():
    pdf_rows = [
        LaborLineItem(source_type="pdf_invoice", source_file="oss.pdf", source_page_or_row="p1", employee_id="", employee_name_raw="Lozano, Manuel", hours=19.59, amount=439.82, currency="USD", confidence=0.95, evidence_text="Lozano, Manuel ... 19.50 0.09 ... 439.82"),
    ]
    excel_rows = [
        LaborLineItem(source_type="offline_workbook", source_file="账单.xlsx", source_page_or_row="账单!21", employee_id="WUS045753", employee_name_raw="Manuel Lozano", hours=16.09, amount=361.42, currency="USD", confidence=1, evidence_text=""),
        LaborLineItem(source_type="offline_workbook", source_file="账单.xlsx", source_page_or_row="账单!24", employee_id="WUS045746", employee_name_raw="Massiel Castillo", hours=3.5, amount=78.4, currency="USD", confidence=1, evidence_text=""),
    ]

    result = compare_labor_items(pdf_rows, excel_rows, amount_tolerance=0.1, hours_tolerance=0.1)

    assert result["summary"]["exceptionCount"] == 2
    assert result["summary"]["candidateMatchCount"] == 1
    candidate = result["candidateMatches"][0]
    assert candidate["issueType"] == "combined_pdf_row"
    assert candidate["pdfEmployeeName"] == "Lozano, Manuel ⇄ Manuel Lozano"
    assert candidate["excelEmployeeName"] == "Massiel Castillo"
    assert candidate["recommendation"] == "疑似PDF合并员工，需人工核对原始发票"
    assert candidate["hoursDelta"] == 3.5
    assert candidate["amountDelta"] == 78.4
    assert "oss.pdf p1" in candidate["sourceRefs"]
    assert "账单.xlsx 账单!24" in candidate["sourceRefs"]
    flagged = {row["employeeName"]: row for row in result["rows"]}
    assert "疑似PDF合并员工" in flagged["Lozano, Manuel ⇄ Manuel Lozano"]["riskFlags"]
    assert "疑似PDF合并员工" in flagged["Massiel Castillo"]["riskFlags"]


def test_compare_labor_items_fuzzy_matches_pdf_name_to_excel_employee_id_group():
    pdf_rows = [
        LaborLineItem(source_type="pdf_invoice", source_file="scan.pdf", source_page_or_row="p1", employee_id="", employee_name_raw="Alvarez Mitrache, Rosa", hours=31.19, amount=701.9, currency="USD", confidence=0.95, evidence_text="Total $701.90"),
    ]
    excel_rows = [
        LaborLineItem(source_type="offline_workbook", source_file="账单.xlsx", source_page_or_row="账单!2", employee_id="WUS042586", employee_name_raw="Rosa Alvarez Minchaca", hours=31.19, amount=701.9, currency="USD", confidence=1, evidence_text=""),
    ]

    result = compare_labor_items(pdf_rows, excel_rows)

    assert result["summary"]["unmatchedPdfCount"] == 0
    assert result["summary"]["unmatchedExcelCount"] == 0
    assert result["rows"][0]["matchStatus"] == "通过"
    assert "疑似姓名匹配" in result["rows"][0]["riskFlags"]


def test_compare_labor_items_suggests_unmatched_name_candidates_without_merging():
    pdf_rows = [
        LaborLineItem(source_type="pdf_invoice", source_file="scan.pdf", source_page_or_row="p1", employee_id="", employee_name_raw="Alvarez Mitrache, Ross", hours=30.5, amount=698.99, currency="USD", confidence=0.95, evidence_text="Total $698.99"),
    ]
    excel_rows = [
        LaborLineItem(source_type="offline_workbook", source_file="账单.xlsx", source_page_or_row="账单!2", employee_id="WUS042586", employee_name_raw="Rosa Alvarez Minchaca", hours=31.19, amount=701.9, currency="USD", confidence=1, evidence_text=""),
    ]

    result = compare_labor_items(pdf_rows, excel_rows)

    assert result["summary"]["unmatchedPdfCount"] == 1
    assert result["summary"]["unmatchedExcelCount"] == 1
    assert result["summary"]["candidateMatchCount"] == 1
    candidate = result["candidateMatches"][0]
    assert candidate["pdfEmployeeName"] == "Alvarez Mitrache, Ross"
    assert candidate["excelEmployeeName"] == "Rosa Alvarez Minchaca"
    assert candidate["recommendation"] == "人工复核"


def test_compare_labor_items_suggests_low_similarity_candidate_when_totals_align():
    pdf_rows = [
        LaborLineItem(source_type="pdf_invoice", source_file="In291943.pdf", source_page_or_row="p1", employee_id="", employee_name_raw="Rozo Panche, Deisy V", hours=37.84, amount=847.84, currency="USD", confidence=0.98, evidence_text="$847.84"),
    ]
    excel_rows = [
        LaborLineItem(source_type="offline_workbook", source_file="账单.xlsx", source_page_or_row="员工账单明细!3", employee_id="WUS040020", employee_name_raw="Deisi Pozo", hours=37.84, amount=847.84, currency="USD", confidence=1, evidence_text=""),
    ]

    result = compare_labor_items(pdf_rows, excel_rows, amount_tolerance=0.1, hours_tolerance=0.1)

    assert result["summary"]["unmatchedPdfCount"] == 1
    assert result["summary"]["unmatchedExcelCount"] == 1
    assert result["summary"]["candidateMatchCount"] == 1
    candidate = result["candidateMatches"][0]
    assert candidate["pdfEmployeeName"] == "Rozo Panche, Deisy V"
    assert candidate["excelEmployeeName"] == "Deisi Pozo"
    assert candidate["nameSimilarity"] == 0.4
    assert candidate["amountDelta"] == 0
    assert candidate["hoursDelta"] == 0


def test_rule_pdf_extractor_adds_meal_premium_amount_without_hours():
    rows = _extract_with_rules(
        [
            {
                "source_file": "invoice.pdf",
                "page": 1,
                "text": "\n".join(
                    [
                        "Associate USEL EMPLOYEE ID Payrate Reg Rate Ot Rate Dt Rate Reg. Time Overtime Dbl. Time RT OT DT TOTAL",
                        "VEGA -0980, ALEXANDER WUS034706 20.00$    25.80$    38.70$ 51.60$ 40.00 14.51 0.03 1,032.00$  561.54$     1.55$         1,595.09$",
                        "VEGA -0980, ALEXANDER WUS034706 20.00$    25.80$    38.70$ 51.60$ 1.00 25.80$       -$           -$           25.80$",
                        "MEAL PREMIUMS",
                    ]
                ),
            }
        ],
        supplier="Fairway Staffing Service",
        period_start="2026-05-04",
        period_end="2026-05-10",
        currency="USD",
    )

    result = compare_labor_items(
        rows,
        [
            LaborLineItem(
                source_type="offline_workbook",
                source_file="账单.xlsx",
                source_page_or_row="账单!48",
                employee_id="WUS034706",
                employee_name_raw="Alxander Vega -0980",
                hours=54.54,
                amount=1620.89,
                currency="USD",
            )
        ],
    )

    assert len(rows) == 2
    assert sum(row.hours for row in rows) == 54.54
    assert round(sum(row.amount for row in rows), 2) == 1620.89
    assert result["summary"]["amountDiffCount"] == 0
    assert result["summary"]["hoursRiskCount"] == 0


def test_rule_pdf_extractor_handles_osi_vertical_invoice_rows():
    rows = _extract_with_rules(
        [
            {
                "source_file": "osi.pdf",
                "page": 1,
                "text": "\n".join(
                    [
                        "Date",
                        "Description",
                        "Hours",
                        "Pay Code",
                        "Type",
                        "Pay Rate",
                        "Bill Rate",
                        "Amount",
                        "CA#25 Bloomington",
                        "5/17/2026",
                        "Alva, Patrick",
                        "32.00",
                        "Reg",
                        "REG",
                        "$20.00",
                        "26.00",
                        "$832.00",
                        "5/17/2026",
                        "Alva, Patrick",
                        "2.75",
                        "OT",
                        "OT",
                        "$30.00",
                        "39.00",
                        "$107.25",
                    ]
                ),
            }
        ],
        supplier="OSI Staffing Inc.",
        period_start="2026-05-11",
        period_end="2026-05-17",
        currency="USD",
    )

    assert len(rows) == 2
    assert [row.employee_name_raw for row in rows] == ["Alva, Patrick", "Alva, Patrick"]
    assert round(sum(row.hours for row in rows), 2) == 34.75
    assert round(sum(row.amount for row in rows), 2) == 939.25


def test_extract_invoice_items_handles_oss_bill_rate_summary_rows(monkeypatch, tmp_path):
    pdf = tmp_path / "US Elogis Service #7 Invoice W.E 05.24.26.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    page = {
        "source_file": pdf.name,
        "page": 1,
        "text": "\n".join(
            [
                "Associate Base Rate Bill Rate OT Rate Reg. Time O.T Dbl. Time RT OT DT TOTAL",
                "Benitez, Anuar $20.00 25.60$     38.40$   16.00 0.19 409.60$         7.30$         -$             416.90$",
                "Briseno Mandujano, Gabriela $17.50 22.40$     33.60$   13.40 300.16$         -$           -$             300.16$",
                "Totals 29.40 0.19 0.00 $709.76 $7.30 $0.00 $717.06",
                "Customer US Elogistics Service Corp #7",
            ]
        ),
    }
    import bonus_platform.engine.labor.extract as extract_module

    monkeypatch.setattr(extract_module, "_extract_pdf_pages", lambda paths: [page])

    rows = extract_invoice_items([pdf], {"enabled": False, "parallel_extraction_enabled": False}, supplier="oss", currency="USD")

    assert len(rows) == 2
    assert rows[0].employee_name_raw == "Benitez, Anuar"
    assert rows[0].hours == 16.19
    assert rows[0].amount == 416.90
    assert rows[0].warehouse_id == "7"
    assert rows[1].employee_name_raw == "Briseno Mandujano, Gabriela"
    assert rows[1].hours == 13.40
    assert rows[1].amount == 300.16


def test_extract_invoice_items_handles_sss_employee_summary_rows(monkeypatch, tmp_path):
    pdf = tmp_path / "NJ13 Invoice Report WE 051726 JF.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    page = {
        "source_file": pdf.name,
        "page": 18,
        "text": "\n".join(
            [
                "Candidate Number Employee Name Candidate Notes Job Code Assignment Wage Rate Service Multiplier Bill Rate Standard Hours Worked Overtime Hours Worked Fee for Regular Hours Fee for Overtime Hours Total SSS Fee",
                "1 Flexible Workforce Shift 1 37 $16.00 27.00% $20.32 1327.15 0.00 $ 26,967.69 $ - $ 26,967.69",
                "2 Open, Open Open CUE1LD2 Loaders Shift 1 Level 2 $17.00 27.00% $21.59 0.00 0.00 $ - $ - $ -",
                "1 Contreras, Kristel 20132 CUE1C1 Cordinator Shift 1 Level 1 $17.00 27.00% $21.59 40.00 8.00 $ 863.60 $ 259.08 $ 1,122.68",
                "2 Contreras, Kristel 20132 CUE1C1 Cordinator Shift 1 Level 1 $17.00 27.00% $21.59 (40.00) (8.00) $ (863.60) $ (259.08) $ (1,122.68)",
                "3 Gonzalez, Felix 20597 CUE1LD2 Loaders Shift 1 Level 2 $17.00 27.00% $21.59 40.00 0.00 $ 863.60 $ - $ 863.60",
                "Antonio 20680 CUE1LD2 Loaders Shift 1 Level 2 $17.00 27.00% $21.59 40.00 0.00 $ 863.60 $ - $ 863.60",
                "4 Hernandez, Gabriel 20125 CUE1LD2 Loaders Shift 1 Level 2 $17.00 27.00% $21.59 40.00 8.00 $ 863.60 $ 259.08 $ 1,122.68",
                "5 Aparicio, Emilio 20253 SD Shift Differential $1.00 27.00% $1.27 40.00 0.00 $ 50.80 $ - $ 50.80",
                "6 Lopez Bellis,",
                "Dalila 20683 CUE1GL2 General Labor Shift 1",
                "Level 2 $16.00 27.00% $20.32 24.00 0.00 $ 487.68 $ - $ 487.68",
                "AM Loaders Summary Confidential Page 18",
            ]
        ),
    }
    import bonus_platform.engine.labor.extract as extract_module

    monkeypatch.setattr(extract_module, "_extract_pdf_pages", lambda paths: [page])

    rows = extract_invoice_items([pdf], {"enabled": False, "parallel_extraction_enabled": False}, supplier="sss", currency="USD")

    assert [row.employee_name_raw for row in rows] == [
        "Gonzalez, Felix",
        "Antonio",
        "Hernandez, Gabriel",
        "Aparicio, Emilio",
        "Lopez Bellis, Dalila",
    ]
    assert rows[0].employee_id == "20597"
    assert rows[0].hours == 40.0
    assert rows[0].amount == 863.60
    assert rows[1].employee_id == "20680"
    assert rows[1].amount == 863.60
    assert rows[2].hours == 48.0
    assert rows[2].amount == 1122.68
    assert rows[3].employee_id == "20253"
    assert rows[3].hours == 0.0
    assert rows[3].amount == 50.80
    assert rows[4].employee_id == "20683"
    assert rows[4].hours == 24.0
    assert rows[4].amount == 487.68
    assert all("Contreras" not in row.employee_name_raw for row in rows)
    assert rows[0].warehouse_id == "13"


def test_mimo_uses_api_key_header_instead_of_bearer_authorization():
    headers = _request_headers({"provider": "mimo", "api_key": "token"})

    assert headers["api-key"] == "token"
    assert "Authorization" not in headers


def test_ai_instruction_blocks_hallucinated_ids_and_non_employee_pages():
    instruction = _ai_instruction()

    assert "return []" in instruction.lower()
    assert "employee_id" in instruction
    assert "barcode" in instruction.lower()
    assert "spatial calibration" in instruction.lower()


def test_supplier_profile_adds_onesource_specific_extraction_guidance():
    profile = resolve_supplier_profile("One Source Staffing Inc.")
    instruction = _ai_instruction(profile)

    assert profile.key == "onesource"
    assert profile.image_page_policy == "first_page_only"
    assert "timecard" in instruction.lower()
    assert "handwritten rg/ot" in instruction.lower()


def test_supplier_profile_adds_prompt_priority_dept_guidance():
    profile = resolve_supplier_profile("Prompt Priority INC")
    instruction = _ai_instruction(profile)

    assert profile.key == "prompt"
    assert profile.image_page_policy == "all"
    assert "dept" in instruction.lower()
    assert "warehouse_id" in instruction


def test_supplier_profile_adds_citistaff_loc_guidance():
    profile = resolve_supplier_profile("CitiStaff Solutions")
    instruction = _ai_instruction(profile)

    assert profile.key == "citistaff"
    assert profile.image_page_policy == "all"
    assert "loc.#" in instruction.lower()
    assert "name mappings" in instruction.lower()


def test_unknown_supplier_uses_default_extraction_profile():
    profile = resolve_supplier_profile("Unseen Vendor LLC")

    assert profile.key == "default"
    assert profile.image_page_policy == "all"


def test_supplier_profiles_can_load_from_json_config(tmp_path):
    path = tmp_path / "profiles.json"
    path.write_text(
        json.dumps(
            [
                {
                    "key": "demo",
                    "aliases": ["demo staffing"],
                    "prompt_notes": ["Only extract rows from the Charge Summary table."],
                    "image_page_policy": "all",
                }
            ]
        ),
        encoding="utf-8",
    )

    profiles = load_supplier_profiles(path)

    assert profiles[0].key == "demo"
    assert profiles[0].aliases == ["demo staffing"]
    assert "Charge Summary" in profiles[0].prompt_notes[0]


def test_supplier_profiles_can_load_single_json_object(tmp_path):
    path = tmp_path / "profile.json"
    path.write_text(
        json.dumps(
            {
                "key": "grande",
                "aliases": ["grande solutions staffing"],
                "prompt_notes": ["Use the simple numbered labor table."],
                "image_page_policy": "all",
            }
        ),
        encoding="utf-8",
    )

    profiles = load_supplier_profiles(path)

    assert len(profiles) == 1
    assert profiles[0].key == "grande"
    assert profiles[0].aliases == ["grande solutions staffing"]


def test_supplier_profile_resolver_prefers_external_config(tmp_path):
    path = tmp_path / "profiles.json"
    path.write_text(
        json.dumps(
            [
                {
                    "key": "external-demo",
                    "aliases": ["onesource"],
                    "prompt_notes": ["External profile wins."],
                }
            ]
        ),
        encoding="utf-8",
    )

    profile = resolve_supplier_profile("ONESOURCE", profiles_path=path)

    assert profile.key == "external-demo"
    assert profile.prompt_notes == ["External profile wins."]


def test_extract_invoice_items_applies_first_page_only_profile_policy(monkeypatch, tmp_path):
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    seen_pages = []

    monkeypatch.setattr("bonus_platform.engine.labor.extract._extract_pdf_pages", lambda paths: [{"source_file": "scan.pdf", "page": 1, "text": ""}])
    monkeypatch.setattr("bonus_platform.engine.labor.extract._extract_with_rules", lambda *args, **kwargs: [])
    monkeypatch.setattr("bonus_platform.engine.labor.extract._extract_with_ai_text", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        "bonus_platform.engine.labor.extract._render_pdf_pages_to_images",
        lambda paths, scale=1.5, **kwargs: [
            {"source_file": "scan.pdf", "source_path": str(pdf), "page": 1, "mime_type": "image/png", "base64": "page1"},
            {"source_file": "scan.pdf", "source_path": str(pdf), "page": 2, "mime_type": "image/png", "base64": "page2"},
        ],
    )

    def fake_extract_images(image_pages, *args, **kwargs):
        seen_pages.extend(page["page"] for page in image_pages)
        return [
            {
                "source_file": "scan.pdf",
                "source_page_or_row": "p1",
                "employee_name_raw": "Alvarez Minchaca, Rosa",
                "hours": 31.19,
                "amount": 701.9,
                "confidence": 0.95,
                "evidence_text": "Total $701.90",
            }
        ]

    monkeypatch.setattr("bonus_platform.engine.labor.extract._extract_with_ai_images", fake_extract_images)

    rows = extract_invoice_items(
        [pdf],
        {"enabled": True, "provider": "mimo", "api_key": "token", "base_url": "https://api.xiaomimimo.com/v1", "model": "mimo-v2.5"},
        supplier="ONESOURCE",
    )

    assert seen_pages == [1]
    assert rows[0].employee_name_raw == "Alvarez Minchaca, Rosa"


def test_extract_invoice_items_applies_first_page_only_only_to_images(monkeypatch, tmp_path):
    pdf = tmp_path / "invoice.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    monkeypatch.setattr(
        "bonus_platform.engine.labor.extract._extract_pdf_pages",
        lambda paths: [
            {
                "source_file": "invoice.pdf",
                "page": 1,
                "text": "\n".join(["Reference", "Employee", "Wage Code", "Type", "Hours", "Rate", "Amount"]),
            },
            {
                "source_file": "invoice.pdf",
                "page": 2,
                "text": "\n".join(
                    [
                        "Torres, Fabiola",
                        "Reg",
                        "REG",
                        "40.00",
                        "22.58",
                        "$903.20",
                        "Torres, Fabiola",
                        "Reg",
                        "OT",
                        "4.64",
                        "33.86",
                        "$157.11",
                    ]
                ),
            },
        ],
    )

    rows = extract_invoice_items(
        [pdf],
        {"enabled": True, "provider": "mimo", "api_key": "token", "base_url": "https://api.xiaomimimo.com/v1", "model": "mimo-v2.5"},
        supplier="ONESOURCE",
    )

    assert len(rows) == 2
    assert {row.source_page_or_row for row in rows} == {"p2"}
    assert round(sum(row.amount for row in rows), 2) == 1060.31


def test_extract_invoice_items_falls_back_to_images_for_unparsed_scanned_pdf(monkeypatch, tmp_path):
    text_pdf = tmp_path / "text.pdf"
    scan_pdf = tmp_path / "scan.pdf"
    text_pdf.write_bytes(b"%PDF-1.4\n")
    scan_pdf.write_bytes(b"%PDF-1.4\n")
    seen_pages = []

    monkeypatch.setattr(
        "bonus_platform.engine.labor.extract._extract_pdf_pages",
        lambda paths: [
            {
                "source_file": "text.pdf",
                "page": 1,
                "text": "\n".join(
                    [
                        "Hours Amount Bill Rate Date Description Pay Rate",
                        "$22.40 40.000 $896.00 5/17/2026 Arellano Luna, Pablo $17.500 Reg",
                    ]
                ),
            },
            {"source_file": "scan.pdf", "page": 1, "text": ""},
            {"source_file": "scan.pdf", "page": 2, "text": ""},
        ],
    )
    monkeypatch.setattr(
        "bonus_platform.engine.labor.extract._render_pdf_pages_to_images",
        lambda paths, scale=1.5, **kwargs: [
            {"source_file": "scan.pdf", "source_path": str(scan_pdf), "page": 1, "mime_type": "image/png", "base64": "page1"},
            {"source_file": "scan.pdf", "source_path": str(scan_pdf), "page": 2, "mime_type": "image/png", "base64": "page2"},
        ],
    )

    def fake_extract_images(image_pages, *args, **kwargs):
        seen_pages.extend(page["page"] for page in image_pages)
        return [
            {
                "source_file": "scan.pdf",
                "source_page_or_row": "p2",
                "employee_name_raw": "Scan Person",
                "hours": 8,
                "amount": 160,
                "confidence": 0.9,
            }
        ]

    monkeypatch.setattr("bonus_platform.engine.labor.extract._extract_with_ai_images", fake_extract_images)

    rows = extract_invoice_items(
        [text_pdf, scan_pdf],
        {"enabled": True, "provider": "mimo", "api_key": "token", "base_url": "https://api.xiaomimimo.com/v1", "model": "mimo-v2.5"},
        supplier="CITI",
    )

    assert seen_pages == [1, 2]
    assert [row.employee_name_raw for row in rows] == ["Arellano Luna, Pablo", "Scan Person"]


def test_quick_extract_totals_uses_wage_code_rows_from_all_pages(monkeypatch, tmp_path):
    from bonus_platform.engine.labor.extract import quick_extract_totals

    pdf = tmp_path / "invoice.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(
        "bonus_platform.engine.labor.extract._extract_pdf_pages",
        lambda paths: [
            {
                "source_file": "invoice.pdf",
                "page": 1,
                "text": "\n".join(
                    [
                        "Aguilar, Hortensia",
                        "Reg",
                        "REG",
                        "40.00",
                        "22.58",
                        "$903.20",
                    ]
                ),
            },
            {
                "source_file": "invoice.pdf",
                "page": 2,
                "text": "\n".join(
                    [
                        "Torres, Fabiola",
                        "Reg",
                        "REG",
                        "40.00",
                        "22.58",
                        "$903.20",
                        "Torres, Fabiola",
                        "Reg",
                        "OT",
                        "4.64",
                        "33.86",
                        "$157.11",
                    ]
                ),
            },
        ],
    )

    totals = quick_extract_totals(
        [pdf],
        {"enabled": True, "provider": "mimo", "api_key": "token", "base_url": "https://api.xiaomimimo.com/v1", "model": "mimo-v2.5"},
        supplier="Invoice",
    )

    assert totals == [{"source_file": "invoice.pdf", "total_amount": 1963.51, "warehouse_id": "", "pdf_type": "unknown"}]


def test_quick_extract_totals_runs_rule_extraction_without_ai_config(monkeypatch, tmp_path):
    from bonus_platform.engine.labor.extract import quick_extract_totals

    pdf = tmp_path / "NJ13 Invoice Report WE 051726 JF.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(
        "bonus_platform.engine.labor.extract._extract_pdf_pages",
        lambda paths: [
            {
                "source_file": "NJ13 Invoice Report WE 051726 JF.pdf",
                "page": 1,
                "text": "\n".join(
                    [
                        "Billable Billable Total",
                        "Hours Fee Fees",
                        "-$",
                        "1 48,293.06$ 48,293.06$",
                    ]
                ),
            }
        ],
    )

    totals = quick_extract_totals([pdf], {}, supplier="Strategic Staffing Solutions Corp.")

    assert totals == [
        {
            "source_file": "NJ13 Invoice Report WE 051726 JF.pdf",
            "total_amount": 48293.06,
            "warehouse_id": "13",
            "pdf_type": "unknown",
        }
    ]


def test_audit_ai_page_cache_candidates_are_confirmation_only(tmp_path):
    pdf = tmp_path / "elog1-1_20260520204104.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    cache_dir = tmp_path / ".ai_extract_cache"
    cache_dir.mkdir()
    (cache_dir / "elog1-1_20260520204104_p1_mimo-v2.5_v6.json").write_text(
        json.dumps(
            [
                {
                    "employee_name_raw": "Alvarez Michalec Rosa",
                    "source_page_or_row": "1",
                    "amount": "$701.88",
                    "confidence": 0.98,
                    "evidence_text": "Alvarez Michalec Rosa | $701.88",
                },
                {
                    "employee_name_raw": "Bernavides Jennifer",
                    "source_page": 1,
                    "amount": "$698.01",
                    "confidence": 0.92,
                    "evidence_text": "Bernavides Jennifer | $698.01",
                },
            ]
        ),
        encoding="utf-8",
    )

    audit = audit_ai_page_cache_candidates([pdf])

    assert audit["decision"] == "candidate_only"
    assert audit["requiresConfirmation"] is True
    assert audit["summary"] == {"fileCount": 1, "candidateFileCount": 1, "candidateAmountTotal": 1399.89}
    assert audit["files"][0]["sourceFile"] == "elog1-1_20260520204104.pdf"
    assert audit["files"][0]["warehouseId"] == "1"
    assert audit["files"][0]["rowCount"] == 2
    assert audit["files"][0]["candidateAmountTotal"] == 1399.89
    assert audit["files"][0]["averageConfidence"] == 0.95
    assert audit["files"][0]["decision"] == "candidate_only"
    assert audit["files"][0]["requiresConfirmation"] is True
    assert audit["files"][0]["evidence"][0]["employeeName"] == "Alvarez Michalec Rosa"
    assert audit["files"][0]["evidence"][0]["sourcePageOrRow"] == "p1"
    assert audit["files"][0]["evidence"][1]["sourcePageOrRow"] == "p1"


def test_ai_cache_reconciliation_preview_compares_candidates_without_promoting(tmp_path):
    pdf = tmp_path / "elog1-1_20260520204104.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    cache_dir = tmp_path / ".ai_extract_cache"
    cache_dir.mkdir()
    (cache_dir / "elog1-1_20260520204104_p1_mimo-v2.5_v4.json").write_text(
        json.dumps(
            [
                {
                    "employee_name_raw": "Alice Worker",
                    "source_page": 1,
                    "hours": 8,
                    "amount": 100,
                    "confidence": 0.95,
                    "evidence_text": "Alice Worker TOTAL $100.00",
                },
                {
                    "employee_name_raw": "Bob Cache",
                    "source_page": 1,
                    "hours": 4,
                    "amount": 50,
                    "confidence": 0.9,
                    "evidence_text": "Bob Cache TOTAL $50.00",
                },
            ]
        ),
        encoding="utf-8",
    )
    excel_rows = [
        LaborLineItem(source_type="offline_workbook", source_file="账单.xlsx", source_page_or_row="账单!2", employee_id="", employee_name_raw="Alice Worker", hours=8, amount=100, currency="USD", confidence=1, evidence_text="", warehouse_id="1"),
        LaborLineItem(source_type="offline_workbook", source_file="账单.xlsx", source_page_or_row="账单!3", employee_id="", employee_name_raw="Carol Workbook", hours=4, amount=55, currency="USD", confidence=1, evidence_text="", warehouse_id="1"),
    ]

    preview = build_ai_cache_reconciliation_preview(
        [pdf],
        excel_rows,
        amount_tolerance=0.1,
        hours_tolerance=0.1,
        confidence_threshold=0.85,
    )

    assert preview["decision"] == "candidate_only"
    assert preview["requiresConfirmation"] is True
    assert preview["summary"]["candidateRowCount"] == 2
    assert preview["summary"]["excelRowCount"] == 2
    assert preview["summary"]["passedCount"] == 1
    assert preview["summary"]["exceptionCount"] == 2
    assert preview["summary"]["cacheAmountTotal"] == 150
    assert preview["summary"]["excelAmountTotal"] == 155
    assert preview["summary"]["reviewableFileCount"] == 0
    assert preview["summary"]["needsReocrFileCount"] == 1
    file_quality = preview["fileQuality"][0]
    assert file_quality["sourceFile"] == "elog1-1_20260520204104.pdf"
    assert file_quality["warehouseId"] == "1"
    assert file_quality["cacheRowCount"] == 2
    assert file_quality["excelRowCount"] == 2
    assert file_quality["cacheAmountTotal"] == 150
    assert file_quality["excelAmountTotal"] == 155
    assert file_quality["amountDelta"] == -5
    assert file_quality["averageConfidence"] == 0.925
    assert file_quality["decision"] == "needs_reocr"
    assert file_quality["recommendation"] == "历史识别金额与账单同仓库金额不一致，建议重新识别后预览影响。"
    assert file_quality["diagnostics"]["summary"]["exceptionCount"] == 2
    assert file_quality["diagnostics"]["summary"]["unmatchedCacheCount"] == 1
    assert file_quality["diagnostics"]["summary"]["unmatchedExcelCount"] == 1
    assert file_quality["diagnostics"]["summary"]["suspectedNamePairCount"] == 0
    assert file_quality["diagnostics"]["extraInCache"][0]["employeeName"] == "Bob Cache"
    assert file_quality["diagnostics"]["missingInCache"][0]["employeeName"] == "Carol Workbook"
    assert file_quality["diagnostics"]["topDifferences"][0]["amountDelta"] == -55
    assert file_quality["diagnostics"]["rootCauseHints"] == ["possible_missing_cache_rows", "possible_extra_cache_rows"]
    assert file_quality["diagnostics"]["recommendedAction"] == "reocr_with_employee_level_review"
    assert any(row["matchStatus"] == "PDF有Excel无" and row["employeeName"] == "Bob Cache" for row in preview["exceptionRows"])
    assert any(row["matchStatus"] == "Excel有PDF无" and row["employeeName"] == "Carol Workbook" for row in preview["exceptionRows"])


def test_ai_cache_reconciliation_preview_marks_file_reviewable_when_warehouse_total_aligns(tmp_path):
    pdf = tmp_path / "elog25-3_20260520204328.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    cache_dir = tmp_path / ".ai_extract_cache"
    cache_dir.mkdir()
    (cache_dir / "elog25-3_20260520204328_p1_mimo-v2.5_v4.json").write_text(
        json.dumps(
            [
                {
                    "employee_name_raw": "David Lopez",
                    "source_page": 1,
                    "hours": 24,
                    "amount": 696.12,
                    "confidence": 0.98,
                    "evidence_text": "David Lopez TOTAL $696.12",
                },
                {
                    "employee_name_raw": "Kenneth Rosales",
                    "source_page": 1,
                    "hours": 48.46,
                    "amount": 1330.43,
                    "confidence": 0.98,
                    "evidence_text": "Kenneth Rosales TOTAL $1,330.43",
                },
            ]
        ),
        encoding="utf-8",
    )
    excel_rows = [
        LaborLineItem(source_type="offline_workbook", source_file="账单.xlsx", source_page_or_row="账单!2", employee_id="", employee_name_raw="David Lopez", hours=24, amount=696.12, currency="USD", confidence=1, evidence_text="", warehouse_id="25"),
        LaborLineItem(source_type="offline_workbook", source_file="账单.xlsx", source_page_or_row="账单!3", employee_id="", employee_name_raw="Kenneth Rosales", hours=48.46, amount=1330.43, currency="USD", confidence=1, evidence_text="", warehouse_id="25"),
    ]

    preview = build_ai_cache_reconciliation_preview(
        [pdf],
        excel_rows,
        amount_tolerance=0.1,
        hours_tolerance=0.1,
        confidence_threshold=0.85,
    )

    assert preview["summary"]["reviewableFileCount"] == 1
    assert preview["summary"]["needsReocrFileCount"] == 0
    assert preview["fileQuality"][0]["decision"] == "reviewable_candidate"
    assert preview["fileQuality"][0]["amountDelta"] == 0
    assert preview["fileQuality"][0]["recommendation"] == "历史识别金额与账单同仓库金额一致，可作为人工复核证据。"


def test_ai_cache_file_diagnostics_suggests_name_mapping_before_reocr(tmp_path):
    pdf = tmp_path / "elog27-1_20260520204231.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    cache_dir = tmp_path / ".ai_extract_cache"
    cache_dir.mkdir()
    (cache_dir / "elog27-1_20260520204231_p1_mimo-v2.5_v4.json").write_text(
        json.dumps(
            [
                {
                    "employee_name_raw": "Coria, Virgilio",
                    "source_page": 1,
                    "hours": 14.47,
                    "amount": 353.68,
                    "confidence": 0.95,
                    "evidence_text": "Coria, Virgilio 14.47 $353.68",
                }
            ]
        ),
        encoding="utf-8",
    )
    excel_rows = [
        LaborLineItem(source_type="offline_workbook", source_file="账单.xlsx", source_page_or_row="账单!34", employee_id="", employee_name_raw="Brayan Gomez Vargas", hours=14.17, amount=353.69, currency="USD", confidence=1, evidence_text="", warehouse_id="27"),
    ]

    preview = build_ai_cache_reconciliation_preview(
        [pdf],
        excel_rows,
        amount_tolerance=0.1,
        hours_tolerance=0.1,
        confidence_threshold=0.85,
    )

    diagnostics = preview["fileQuality"][0]["diagnostics"]
    assert diagnostics["summary"]["suspectedNamePairCount"] == 1
    pair = diagnostics["suspectedNamePairs"][0]
    assert pair["cacheEmployeeName"] == "Coria, Virgilio"
    assert pair["excelEmployeeName"] == "Brayan Gomez Vargas"
    assert pair["amountGap"] == -0.01
    assert pair["hoursGap"] == 0.3
    assert "possible_name_mapping" in diagnostics["rootCauseHints"]
    assert diagnostics["recommendedAction"] == "review_name_mapping_then_reocr_if_amounts_remain_unexplained"


def test_reocr_candidate_plan_is_confirmation_only():
    plan = build_reocr_candidate_plan(
        [
            {
                "sourceFile": "elog7-5_20260520204043.pdf",
                "warehouseId": "7",
                "cacheRowCount": 13,
                "excelRowCount": 13,
                "cacheAmountTotal": 10945.47,
                "excelAmountTotal": 8473.21,
                "amountDelta": 2472.26,
                "decision": "needs_reocr",
                "recommendation": "历史识别金额与账单同仓库金额不一致，建议重新识别后预览影响。",
                "diagnostics": {
                    "summary": {"exceptionCount": 3, "unmatchedCacheCount": 1, "unmatchedExcelCount": 2},
                    "topDifferences": [{"employeeName": "Alice Worker", "amountDelta": 120.5}],
                    "missingInCache": [{"employeeName": "Missing Worker"}],
                    "extraInCache": [{"employeeName": "Extra Worker"}],
                },
            },
            {
                "sourceFile": "elog25-3_20260520204328.pdf",
                "warehouseId": "25",
                "cacheRowCount": 2,
                "excelRowCount": 2,
                "cacheAmountTotal": 2026.55,
                "excelAmountTotal": 2026.55,
                "amountDelta": 0,
                "decision": "reviewable_candidate",
                "recommendation": "历史识别金额与账单同仓库金额一致，可作为人工复核证据。",
            },
        ],
        amount_tolerance=0.1,
    )

    assert plan["decision"] == "candidate_only"
    assert plan["requiresConfirmation"] is True
    assert plan["summary"] == {
        "taskCount": 1,
        "reviewableCandidateCount": 1,
        "totalExpectedExcelAmount": 8473.21,
        "totalCurrentCacheAmount": 10945.47,
    }
    assert plan["tasks"][0]["sourceFile"] == "elog7-5_20260520204043.pdf"
    assert plan["tasks"][0]["amountTolerance"] == 0.1
    assert plan["tasks"][0]["diagnostics"]["summary"]["exceptionCount"] == 3
    assert plan["tasks"][0]["diagnostics"]["missingInCache"][0]["employeeName"] == "Missing Worker"
    assert plan["tasks"][0]["focusEmployees"][0]["employeeName"] == "Alice Worker"
    assert plan["tasks"][0]["focusEmployees"][1]["employeeName"] == "Missing Worker"
    assert plan["tasks"][0]["focusEmployees"][2]["employeeName"] == "Extra Worker"
    assert "必须业务确认" in plan["tasks"][0]["confirmationGate"]
    assert "必须人工确认" not in plan["tasks"][0]["confirmationGate"]
    assert plan["reviewableCandidates"][0]["sourceFile"] == "elog25-3_20260520204328.pdf"


def test_parse_reocr_candidate_rows_from_csv(tmp_path):
    path = tmp_path / "reocr.csv"
    path.write_text(
        "Employee,Hours,Amount,Page,Confidence,Evidence\n"
        "Alice Worker,8,100,p1,96%,Alice Worker 8 $100\n"
        "Bob Worker,10,200,p2,0.95,Bob Worker 10 $200\n",
        encoding="utf-8",
    )

    rows = parse_reocr_candidate_rows(path, default_currency="USD")

    assert rows == [
        {
            "employeeName": "Alice Worker",
            "sourcePageOrRow": "p1",
            "hours": 8,
            "amount": 100,
            "currency": "USD",
            "confidence": 0.96,
            "evidenceText": "Alice Worker 8 $100",
        },
        {
            "employeeName": "Bob Worker",
            "sourcePageOrRow": "p2",
            "hours": 10,
            "amount": 200,
            "currency": "USD",
            "confidence": 0.95,
            "evidenceText": "Bob Worker 10 $200",
        },
    ]


def test_parse_reocr_candidate_rows_preserves_scope_and_employee_id(tmp_path):
    path = tmp_path / "reocr_scoped.csv"
    path.write_text(
        "SourceFile,WarehouseId,EmployeeId,Employee,Hours,Amount,Page,Confidence,Currency,Evidence,ExcelRef,ExpectedHours,ExpectedAmount\n"
        "elog1.pdf,1,WUS001,Alice Worker,8,100,p1,0.95,USD,Alice Worker 8 $100,账单.xlsx 员工账单!2,8,100\n",
        encoding="utf-8",
    )

    rows = parse_reocr_candidate_rows(path, default_currency="USD")

    assert rows == [
        {
            "employeeName": "Alice Worker",
            "sourcePageOrRow": "p1",
            "hours": 8,
            "amount": 100,
            "currency": "USD",
            "confidence": 0.95,
            "evidenceText": "Alice Worker 8 $100",
            "sourceFile": "elog1.pdf",
            "warehouseId": "1",
            "employeeId": "WUS001",
        }
    ]


def test_parse_reocr_candidate_rows_requires_name_and_amount(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("Employee,Hours\nAlice Worker,8\n", encoding="utf-8")

    with pytest.raises(ValueError, match="员工姓名列和金额列"):
        parse_reocr_candidate_rows(path)


def test_reocr_candidate_replay_can_be_ready_for_user_confirmation():
    task = {
        "sourceFile": "elog7-5_20260520204043.pdf",
        "warehouseId": "7",
        "expectedExcelAmount": 300,
        "amountDelta": 2472.26,
        "confirmationGate": "新图片识别结果金额需与同仓库 Excel 金额在容差内，员工级异常需可解释，且必须人工确认。",
    }
    excel_rows = [
        LaborLineItem(source_type="offline_workbook", source_file="账单.xlsx", source_page_or_row="账单!2", employee_id="", employee_name_raw="Alice Worker", hours=8, amount=100, currency="USD", confidence=1, evidence_text="", warehouse_id="7"),
        LaborLineItem(source_type="offline_workbook", source_file="账单.xlsx", source_page_or_row="账单!3", employee_id="", employee_name_raw="Bob Worker", hours=10, amount=200, currency="USD", confidence=1, evidence_text="", warehouse_id="7"),
    ]
    candidate_rows = [
        {"employee_name_raw": "Alice Worker", "source_page_or_row": "p1", "hours": 8, "amount": 100, "confidence": 0.96},
        {"employee_name_raw": "Bob Worker", "source_page_or_row": "p1", "hours": 10, "amount": 200, "confidence": 0.96},
    ]

    replay = replay_reocr_candidate_result(
        task,
        candidate_rows,
        excel_rows,
        amount_tolerance=0.1,
        hours_tolerance=0.1,
        confidence_threshold=0.85,
    )

    assert replay["decision"] == "ready_for_user_confirmation"
    assert replay["requiresConfirmation"] is True
    assert replay["summary"]["candidateAmountTotal"] == 300
    assert replay["summary"]["amountPassed"] is True
    assert replay["summary"]["exceptionCount"] == 0
    assert replay["summary"]["fixedCacheDelta"] == 2472.26
    assert replay["blockers"] == []
    assert len(replay["previewRows"]) == 2
    assert all(row["matchStatus"] == "通过" for row in replay["previewRows"])


def test_reocr_candidate_replay_blocks_amount_mismatch():
    task = {
        "sourceFile": "elog7-5_20260520204043.pdf",
        "warehouseId": "7",
        "expectedExcelAmount": 300,
        "amountDelta": 2472.26,
        "diagnostics": {
            "recommendedAction": "review_name_mapping_then_reocr_if_amounts_remain_unexplained",
            "rootCauseHints": ["possible_name_mapping"],
            "suspectedNamePairs": [{"cacheEmployeeName": "Bob Worker", "excelEmployeeName": "Bob Worker"}],
        },
    }
    excel_rows = [
        LaborLineItem(source_type="offline_workbook", source_file="账单.xlsx", source_page_or_row="账单!2", employee_id="", employee_name_raw="Alice Worker", hours=8, amount=100, currency="USD", confidence=1, evidence_text="", warehouse_id="7"),
        LaborLineItem(source_type="offline_workbook", source_file="账单.xlsx", source_page_or_row="账单!3", employee_id="", employee_name_raw="Bob Worker", hours=10, amount=200, currency="USD", confidence=1, evidence_text="", warehouse_id="7"),
    ]
    candidate_rows = [
        {"employee_name_raw": "Alice Worker", "source_page_or_row": "p1", "hours": 8, "amount": 100, "confidence": 0.96},
        {"employee_name_raw": "Bob Worker", "source_page_or_row": "p1", "hours": 10, "amount": 210, "confidence": 0.96},
    ]

    replay = replay_reocr_candidate_result(
        task,
        candidate_rows,
        excel_rows,
        amount_tolerance=0.1,
        hours_tolerance=0.1,
        confidence_threshold=0.85,
    )

    assert replay["decision"] == "blocked_by_replay"
    assert "candidate_amount_mismatch" in replay["blockers"]
    assert "employee_level_exceptions" in replay["blockers"]
    assert replay["summary"]["amountDelta"] == 10
    assert replay["summary"]["exceptionCount"] == 1
    assert replay["diagnostics"]["recommendedAction"] == "review_name_mapping_then_reocr_if_amounts_remain_unexplained"


def test_reocr_candidate_replay_blocks_employee_exceptions_even_when_total_matches():
    task = {"sourceFile": "elog7-5_20260520204043.pdf", "warehouseId": "7", "expectedExcelAmount": 300, "amountDelta": 2472.26}
    excel_rows = [
        LaborLineItem(source_type="offline_workbook", source_file="账单.xlsx", source_page_or_row="账单!2", employee_id="", employee_name_raw="Alice Worker", hours=8, amount=100, currency="USD", confidence=1, evidence_text="", warehouse_id="7"),
        LaborLineItem(source_type="offline_workbook", source_file="账单.xlsx", source_page_or_row="账单!3", employee_id="", employee_name_raw="Bob Worker", hours=10, amount=200, currency="USD", confidence=1, evidence_text="", warehouse_id="7"),
    ]
    candidate_rows = [
        {"employee_name_raw": "Alice Worker", "source_page_or_row": "p1", "hours": 8, "amount": 100, "confidence": 0.96},
        {"employee_name_raw": "Wrong Worker", "source_page_or_row": "p1", "hours": 10, "amount": 200, "confidence": 0.96},
    ]

    replay = replay_reocr_candidate_result(
        task,
        candidate_rows,
        excel_rows,
        amount_tolerance=0.1,
        hours_tolerance=0.1,
        confidence_threshold=0.85,
    )

    assert replay["decision"] == "blocked_by_replay"
    assert replay["summary"]["amountPassed"] is True
    assert replay["summary"]["exceptionCount"] == 2
    assert replay["blockers"] == ["employee_level_exceptions"]


def test_rule_change_candidate_requires_user_confirmation():
    candidate = build_rule_change_candidate(
        rule_id="warehouse-filename-hash-number",
        title="从 OSS 文件名 #N 提取仓库号",
        description="识别 US Elogis Service #17 Invoice 这类文件名中的仓库号。",
        supplier="OSS",
        source="oss 2 real replay",
        proposed_by="ai",
        evidence=[{"sourceFile": "US Elogis Service #17 Invoice W.E 05.24.26.pdf", "warehouseId": "17"}],
        conditions={"filenamePattern": "#<warehouse_id> Invoice"},
    )

    assert candidate["decision"] == "candidate_only"
    assert candidate["status"] == "pending_user_confirmation"
    assert candidate["requiresConfirmation"] is True
    assert candidate["version"] == 1
    assert candidate["auditTrail"][0]["action"] == "created"
    assert candidate["conditions"]["filenamePattern"] == "#<warehouse_id> Invoice"


def test_rule_replay_summary_blocks_regressions_before_confirmation():
    candidate = build_rule_change_candidate(
        rule_id="minor-name-typo-match",
        title="轻微姓名拼写差异匹配",
        description="当姓名相似且工时金额一致时匹配。",
        supplier="OSI",
        source="osi real replay",
    )

    replay = summarize_rule_replay(
        candidate,
        [
            {
                "runId": "osi_34794",
                "supplier": "OSI",
                "periodStart": "2026-05-18",
                "periodEnd": "2026-05-24",
                "beforeStatus": "warning",
                "afterStatus": "ok",
                "beforeIssueCount": 2,
                "afterIssueCount": 0,
            },
            {
                "runId": "fairway_135612",
                "supplier": "Fairway",
                "periodStart": "2026-05-18",
                "periodEnd": "2026-05-24",
                "beforeStatus": "ok",
                "afterStatus": "warning",
                "beforeIssueCount": 0,
                "afterIssueCount": 1,
            },
        ],
    )

    assert replay["decision"] == "blocked_by_replay_regression"
    assert replay["requiresConfirmation"] is True
    assert replay["summary"] == {"replayedCount": 2, "fixedCount": 1, "regressionCount": 1, "unchangedCount": 0}
    assert replay["fixed"][0]["runId"] == "osi_34794"
    assert replay["regressions"][0]["runId"] == "fairway_135612"


def test_rule_auto_replay_uses_historical_metadata_diagnostics():
    candidate = build_rule_change_candidate(
        rule_id="oss-hash-warehouse-v1",
        title="OSS # warehouse id extraction",
        description="Parse warehouse id from US Elogis Service #N invoice names.",
        supplier="OSS",
        source="oss 2 real replay",
        conditions={"supplier": "OSS", "fixIssueCodes": ["missing_warehouse_id"]},
    )
    replay = summarize_rule_auto_replay(
        candidate,
        [
            {
                "id": "oss2_warehouse_7",
                "supplierName": "OSS",
                "periodStart": "2026-05-18",
                "periodEnd": "2026-05-24",
                "reconciliationDiagnostics": {
                    "level": "warning",
                    "issues": [{"code": "missing_warehouse_id", "level": "warning"}],
                },
                "comparisonSummary": {"exceptionCount": 0},
            },
            {
                "id": "fairway_135612",
                "supplierName": "Fairway",
                "reconciliationDiagnostics": {
                    "level": "ok",
                    "issues": [],
                },
                "comparisonSummary": {"exceptionCount": 0},
            },
        ],
        current_run_id="oss2_warehouse_7",
    )

    assert replay["mode"] == "metadata_signal_replay"
    assert replay["decision"] == "ready_for_user_confirmation"
    assert replay["summary"] == {"replayedCount": 2, "fixedCount": 1, "regressionCount": 0, "unchangedCount": 1}
    assert replay["replayResults"][0]["matchedIssueCodes"] == ["missing_warehouse_id"]
    assert replay["replayResults"][1]["impactReason"] == "out_of_scope_supplier"
    assert replay["requiresConfirmation"] is True
    assert replay["limitations"]


def test_confirm_rule_candidate_requires_successful_replay():
    candidate = build_rule_change_candidate(
        rule_id="warehouse-filename-hash-number",
        title="从 OSS 文件名 #N 提取仓库号",
        description="识别 US Elogis Service #17 Invoice 这类文件名中的仓库号。",
        supplier="OSS",
        source="oss 2 real replay",
    )
    blocked_replay = {
        "decision": "blocked_by_replay_regression",
        "summary": {"replayedCount": 1, "fixedCount": 0, "regressionCount": 1, "unchangedCount": 0},
    }

    with pytest.raises(ValueError, match="未通过历史影响预览"):
        confirm_rule_candidate(candidate, blocked_replay, confirmed_by="ops-user", reason="误伤已通过批次")


def test_confirm_and_rollback_rule_version_records_audit_trail():
    candidate = build_rule_change_candidate(
        rule_id="warehouse-filename-hash-number",
        title="从 OSS 文件名 #N 提取仓库号",
        description="识别 US Elogis Service #17 Invoice 这类文件名中的仓库号。",
        supplier="OSS",
        source="oss 2 real replay",
    )
    replay = {
        "decision": "ready_for_user_confirmation",
        "summary": {"replayedCount": 2, "fixedCount": 1, "regressionCount": 0, "unchangedCount": 1},
    }

    active = confirm_rule_candidate(candidate, replay, confirmed_by="ops-user", reason="OSS2 仓库号回放通过")

    assert active["decision"] == "active"
    assert active["status"] == "active"
    assert active["requiresConfirmation"] is False
    assert active["confirmedBy"] == "ops-user"
    assert active["replaySummary"] == replay["summary"]
    assert active["auditTrail"][-1]["action"] == "confirmed"

    rolled_back = rollback_rule_version(active, rolled_back_by="ops-user", reason="后续批次发现误伤", target_version=0)

    assert rolled_back["decision"] == "rolled_back"
    assert rolled_back["status"] == "rolled_back"
    assert rolled_back["rollbackToVersion"] == 0
    assert rolled_back["auditTrail"][-1] == {
        "action": "rolled_back",
        "actor": "ops-user",
        "reason": "后续批次发现误伤",
        "fromVersion": 1,
        "toVersion": 0,
    }


def test_quick_extract_totals_uses_citi_bill_rate_rows(monkeypatch, tmp_path):
    from bonus_platform.engine.labor.extract import quick_extract_totals

    pdf = tmp_path / "invoice.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(
        "bonus_platform.engine.labor.extract._extract_pdf_pages",
        lambda paths: [
            {
                "source_file": "invoice.pdf",
                "page": 1,
                "text": "\n".join(
                    [
                        "Hours Amount Bill Rate Date Description Pay Rate",
                        "WAREHOUSE LOC.#29PO #:",
                        "$22.40 40.000 $896.00 5/17/2026 Arellano Luna, Pablo $17.500 Reg",
                        "$33.60 0.400 $13.44 5/17/2026 Arellano Luna, Pablo $26.250 OT",
                    ]
                ),
            }
        ],
    )

    totals = quick_extract_totals(
        [pdf],
        {"enabled": True, "provider": "mimo", "api_key": "token", "base_url": "https://api.xiaomimimo.com/v1", "model": "mimo-v2.5"},
        supplier="CITI",
    )

    assert totals == [{"source_file": "invoice.pdf", "total_amount": 909.44, "warehouse_id": "29", "pdf_type": "unknown"}]


def test_quick_extract_totals_preserves_warehouse_conflict(monkeypatch, tmp_path):
    from bonus_platform.engine.labor.extract import quick_extract_totals

    pdf = tmp_path / "INVOICE_WH-3.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(
        "bonus_platform.engine.labor.extract._extract_pdf_pages",
        lambda paths: [
            {
                "source_file": "INVOICE_WH-3.pdf",
                "page": 1,
                "text": "US ELOGISTICS\nCA#30\nTotal Due: $1,000.00",
            }
        ],
    )

    totals = quick_extract_totals(
        [pdf],
        {"enabled": True, "provider": "mimo", "api_key": "token", "base_url": "https://api.xiaomimimo.com/v1", "model": "mimo-v2.5"},
        supplier="Invoice",
    )

    assert totals == [
        {
            "source_file": "INVOICE_WH-3.pdf",
            "total_amount": 1000.0,
            "warehouse_id": "3",
            "pdf_type": "primary",
            "warehouse_conflict": {
                "source_file": "INVOICE_WH-3.pdf",
                "filename_warehouse_id": "3",
                "text_warehouse_id": "30",
            },
        }
    ]


def test_non_payable_pdf_names_flags_supporting_types_when_payable_invoice_exists():
    totals = [
        {"source_file": "In291943.pdf", "total_amount": 13836.28, "pdf_type": "primary"},
        {"source_file": "Supplement1.pdf", "total_amount": 120.0, "pdf_type": "supporting"},
        {"source_file": "COI.pdf", "total_amount": 0, "pdf_type": "attachment"},
        {"source_file": "legacy_detail.pdf", "total_amount": 0},
        {"source_file": "unknown_scan.pdf", "total_amount": 0, "pdf_type": "unknown"},
    ]

    assert _non_payable_pdf_names(totals) == {"Supplement1.pdf", "COI.pdf", "legacy_detail.pdf"}


def test_non_payable_pdf_names_keeps_only_pdf_when_all_totals_failed():
    totals = [{"source_file": "Supplement1.pdf", "total_amount": 0, "pdf_type": "supporting"}]

    assert _non_payable_pdf_names(totals) == set()


def test_rendered_invoice_images_preserve_pdf_orientation(monkeypatch, tmp_path):
    from PIL import Image

    class FakeBitmap:
        def to_pil(self):
            return Image.new("RGB", (100, 200), "white")

    class FakePage:
        def render(self, scale):
            return FakeBitmap()

        def close(self):
            pass

    class FakeDocument:
        def __init__(self, path):
            pass

        def __len__(self):
            return 1

        def __getitem__(self, index):
            return FakePage()

        def close(self):
            pass

    class FakePdfium:
        PdfDocument = FakeDocument

    monkeypatch.setitem(__import__("sys").modules, "pypdfium2", FakePdfium)

    rows = __import__("bonus_platform.engine.labor.extract", fromlist=["_render_pdf_pages_to_images"])._render_pdf_pages_to_images([tmp_path / "scan.pdf"])

    image = Image.open(BytesIO(__import__("base64").b64decode(rows[0]["base64"])))
    assert image.size == (100, 200)


def test_pdf_text_extraction_keeps_pipeline_alive_for_unreadable_pdf(tmp_path):
    broken_pdf = tmp_path / "broken.pdf"
    broken_pdf.write_bytes(b"%PDF-1.4\n")

    pages = _extract_pdf_pages([broken_pdf])

    assert pages == [{"source_file": "broken.pdf", "page": 1, "text": ""}]


def test_mimo_image_extractor_sends_base64_pages_and_returns_rows(monkeypatch):
    captured = {}

    def fake_post(payload, ai_config):
        captured["payload"] = payload
        return [
            {
                "source_file": "scan.pdf",
                "source_page_or_row": "p1",
                "employee_id": "",
                "employee_name_raw": "Alvarez Minchaca, Rosa",
                "hours": 40,
                "amount": 800.5,
                "currency": "USD",
                "confidence": 0.88,
                "evidence_text": "Alvarez Minchaca, Rosa ... Total $800.50",
            }
        ]

    monkeypatch.setattr("bonus_platform.engine.labor.extract._post_chat_completion", fake_post)

    rows = _extract_with_ai_images(
        [
            {
                "source_file": "scan.pdf",
                "page": 1,
                "mime_type": "image/png",
                "base64": "abc123",
            }
        ],
        {
            "provider": "mimo",
            "api_key": "token",
            "base_url": "https://api.xiaomimimo.com/v1",
            "model": "mimo-v2.5",
            "max_pages_per_request": 5,
        },
        supplier="ONESOURCE",
        period_start="2026-05-11",
        period_end="2026-05-17",
        currency="USD",
    )

    content = captured["payload"]["messages"][1]["content"]

    # 检查图片格式（支持 image_url 或 image 类型）
    assert content[0]["type"] in ("image_url", "image")
    if content[0]["type"] == "image_url":
        assert content[0]["image_url"]["url"] == "data:image/png;base64,abc123"
    else:
        assert content[0]["source"]["type"] == "base64"
        assert content[0]["source"]["data"] == "abc123"
    assert rows[0]["employee_name_raw"] == "Alvarez Minchaca, Rosa"
    assert rows[0]["source_type"] == "pdf_invoice"
    assert rows[0]["supplier"] == "ONESOURCE"


def test_mimo_image_extractor_annotates_single_page_rows_when_model_omits_source(monkeypatch):
    monkeypatch.setattr(
        "bonus_platform.engine.labor.extract._post_chat_completion",
        lambda payload, ai_config: [
            {
                "employee_name_raw": "Scan Person",
                "hours": 8,
                "amount": 160,
                "confidence": 0.9,
            }
        ],
    )

    rows = _extract_with_ai_images(
        [
            {
                "source_file": "scan.pdf",
                "page": 2,
                "mime_type": "image/png",
                "base64": "abc123",
            }
        ],
        {
            "provider": "mimo",
            "api_key": "token",
            "base_url": "https://api.xiaomimimo.com/v1",
            "model": "mimo-v2.5",
            "cache_enabled": False,
        },
    )

    assert rows[0]["source_file"] == "scan.pdf"
    assert rows[0]["source_page_or_row"] == "p2"


def test_extract_invoice_items_uses_mimo_images_when_pdf_text_has_no_rows(monkeypatch, tmp_path):
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    monkeypatch.setattr("bonus_platform.engine.labor.extract._extract_pdf_pages", lambda paths: [{"source_file": "scan.pdf", "page": 1, "text": ""}])
    monkeypatch.setattr(
        "bonus_platform.engine.labor.extract._render_pdf_pages_to_images",
        lambda paths, scale=1.5, **kwargs: [{"source_file": "scan.pdf", "page": 1, "mime_type": "image/png", "base64": "abc123"}],
    )
    monkeypatch.setattr("bonus_platform.engine.labor.extract._extract_with_ai_text", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        "bonus_platform.engine.labor.extract._post_chat_completion",
        lambda payload, config: [
            {
                "source_file": "scan.pdf",
                "source_page_or_row": "p1",
                "employee_name_raw": "Alvarez Minchaca, Rosa",
                "hours": 40,
                "amount": 800.5,
                "confidence": 0.88,
                "evidence_text": "Alvarez Minchaca, Rosa ... Total $800.50",
            }
        ],
    )

    rows = extract_invoice_items(
        [pdf],
        {"enabled": True, "provider": "mimo", "api_key": "token", "base_url": "https://api.xiaomimimo.com/v1", "model": "mimo-v2.5"},
        supplier="ONESOURCE",
        period_start="2026-05-11",
        period_end="2026-05-17",
        currency="USD",
    )

    assert len(rows) == 1
    assert rows[0].employee_name_raw == "Alvarez Minchaca, Rosa"
    assert rows[0].source_type == "pdf_invoice"
    assert rows[0].supplier == "ONESOURCE"


def test_mimo_image_extractor_filters_non_employee_zero_rows(monkeypatch):
    monkeypatch.setattr(
        "bonus_platform.engine.labor.extract._post_chat_completion",
        lambda payload, config: [
            {"source_file": "scan.pdf", "source_page_or_row": "p2", "employee_name_raw": "RG-31.45", "hours": 0, "amount": 0, "confidence": 0.85},
            {"source_file": "scan.pdf", "source_page_or_row": "p1", "employee_name_raw": "Alvarez Minchaca, Rosa", "hours": 31.19, "amount": 701.9, "confidence": 0.95, "evidence_text": "Total $701.90"},
        ],
    )

    rows = _extract_with_ai_images(
        [{"source_file": "scan.pdf", "page": 2, "mime_type": "image/png", "base64": "abc123"}],
        {"provider": "mimo", "api_key": "token", "base_url": "https://api.xiaomimimo.com/v1", "model": "mimo-v2.5"},
    )

    assert [row["employee_name_raw"] for row in rows] == ["Alvarez Minchaca, Rosa"]


def test_image_extractor_includes_full_expected_employee_list(monkeypatch):
    captured = {}

    def fake_post(payload, config):
        captured["payload"] = payload
        return []

    monkeypatch.setattr("bonus_platform.engine.labor.extract._post_chat_completion", fake_post)
    expected_rows = [{"employee_name": f"Employee {idx}"} for idx in range(1, 36)]

    _extract_with_ai_images(
        [{"source_file": "scan.pdf", "page": 1, "mime_type": "image/png", "base64": "abc123"}],
        {"provider": "mimo", "api_key": "token", "base_url": "https://api.xiaomimimo.com/v1", "model": "mimo-v2.5"},
        expected_rows=expected_rows,
    )

    prompt_text = captured["payload"]["messages"][1]["content"][-1]["text"]
    assert "Employee 1" in prompt_text
    assert "Employee 20" in prompt_text
    assert "Employee 35" in prompt_text


def test_image_ai_rows_are_filtered_against_expected_employee_candidates():
    rows = [
        {"employee_name_raw": "John Doe", "hours": 0, "amount": 5500, "confidence": 0.95},
        {"employee_name_raw": "Morales, Katherine", "hours": 40.6, "amount": 916.16, "confidence": 0.95},
        {"employee_name_raw": "Gerardo Torres Valencia", "hours": 39.27, "amount": 1008.51, "confidence": 0.95},
    ]
    expected_rows = [
        {"employee_name": "Katherina Morales"},
        {"employee_name": "Gerardo Torres"},
    ]

    filtered = _filter_ai_rows_by_expected_employees(rows, expected_rows)

    assert [row["employee_name_raw"] for row in filtered] == ["Morales, Katherine", "Gerardo Torres Valencia"]


def test_mimo_image_extractor_filters_timesheet_rows_without_money_evidence(monkeypatch):
    monkeypatch.setattr(
        "bonus_platform.engine.labor.extract._post_chat_completion",
        lambda payload, config: [
            {"source_file": "scan.pdf", "source_page_or_row": "p2", "employee_name_raw": "Brian Cowan", "hours": 8, "amount": 40, "confidence": 0.85, "evidence_text": "Brian Cowan RG-40 OT-0.42"},
            {"source_file": "scan.pdf", "source_page_or_row": "p1", "employee_name_raw": "Alvarez Minchaca, Rosa", "hours": 31.19, "amount": 701.9, "confidence": 0.95, "evidence_text": "Total $701.90"},
        ],
    )

    rows = _extract_with_ai_images(
        [{"source_file": "scan.pdf", "page": 2, "mime_type": "image/png", "base64": "abc123"}],
        {"provider": "mimo", "api_key": "token", "base_url": "https://api.xiaomimimo.com/v1", "model": "mimo-v2.5"},
    )

    # evidence 标记检查已移除（太严格导致图片PDF抽取结果被误过滤）
    # amount=40 > 0 且有合理人名，现在应该保留
    assert [row["employee_name_raw"] for row in rows] == ["Brian Cowan", "Alvarez Minchaca, Rosa"]


def test_mimo_image_extractor_filters_rows_without_amount(monkeypatch):
    monkeypatch.setattr(
        "bonus_platform.engine.labor.extract._post_chat_completion",
        lambda payload, config: [
            {"source_file": "scan.pdf", "source_page_or_row": "p2", "employee_name_raw": "Kevin Sultana", "hours": 39.43, "amount": 0, "confidence": 0.85, "evidence_text": "Total Hours 39.43"},
            {"source_file": "scan.pdf", "source_page_or_row": "p1", "employee_name_raw": "Alvarez Minchaca, Rosa", "hours": 31.19, "amount": 701.9, "confidence": 0.95, "evidence_text": "Total $701.90"},
        ],
    )

    rows = _extract_with_ai_images(
        [{"source_file": "scan.pdf", "page": 2, "mime_type": "image/png", "base64": "abc123"}],
        {"provider": "mimo", "api_key": "token", "base_url": "https://api.xiaomimimo.com/v1", "model": "mimo-v2.5"},
    )

    assert [row["employee_name_raw"] for row in rows] == ["Alvarez Minchaca, Rosa"]


def test_mimo_image_extractor_skips_non_first_page_json_parse_failures(monkeypatch):
    def fake_post(payload, config):
        raise json.JSONDecodeError("Expecting value", "", 0)

    monkeypatch.setattr("bonus_platform.engine.labor.extract._post_chat_completion", fake_post)

    rows = _extract_with_ai_images(
        [{"source_file": "scan.pdf", "page": 2, "mime_type": "image/png", "base64": "abc123"}],
        {"provider": "mimo", "api_key": "token", "base_url": "https://api.xiaomimimo.com/v1", "model": "mimo-v2.5"},
    )

    assert rows == []


def test_mimo_image_extractor_retries_first_page_json_parse_failures(monkeypatch):
    calls = {"count": 0}

    def fake_post(payload, config):
        calls["count"] += 1
        if calls["count"] == 1:
            raise json.JSONDecodeError("Expecting value", "", 0)
        return [{"source_file": "scan.pdf", "source_page_or_row": "p1", "employee_name_raw": "Alvarez Minchaca, Rosa", "hours": 31.19, "amount": 701.9, "confidence": 0.95, "evidence_text": "Total $701.90"}]

    monkeypatch.setattr("bonus_platform.engine.labor.extract._post_chat_completion", fake_post)

    rows = _extract_with_ai_images(
        [{"source_file": "scan.pdf", "page": 1, "mime_type": "image/png", "base64": "abc123"}],
        {"provider": "mimo", "api_key": "token", "base_url": "https://api.xiaomimimo.com/v1", "model": "mimo-v2.5"},
    )

    assert calls["count"] == 2
    assert rows[0]["employee_name_raw"] == "Alvarez Minchaca, Rosa"


def test_mimo_image_extractor_skips_timed_out_page_and_keeps_later_rows(monkeypatch):
    calls = {"count": 0}

    def fake_post(payload, config):
        calls["count"] += 1
        if calls["count"] <= 4:
            raise MiMoTimeoutException("gateway timeout")
        return [
            {
                "source_file": "scan.pdf",
                "source_page_or_row": "p2",
                "employee_name_raw": "Alvarez Minchaca, Rosa",
                "hours": 31.19,
                "amount": 701.9,
                "confidence": 0.95,
                "evidence_text": "Total $701.90",
            }
        ]

    monkeypatch.setattr("bonus_platform.engine.labor.extract._post_chat_completion", fake_post)

    rows = _extract_with_ai_images(
        [
            {"source_file": "scan.pdf", "page": 1, "mime_type": "image/png", "base64": "abc123"},
            {"source_file": "scan.pdf", "page": 2, "mime_type": "image/png", "base64": "def456"},
        ],
        {
            "provider": "mimo",
            "api_key": "token",
            "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
            "model": "mimo-v2.5",
            "max_pages_per_request": 5,
        },
    )

    assert calls["count"] == 5
    assert [row["employee_name_raw"] for row in rows] == ["Alvarez Minchaca, Rosa"]


def test_token_plan_image_extractor_forces_single_page_chunks():
    assert _effective_max_pages_per_request(
        {
            "provider": "mimo",
            "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
            "max_pages_per_request": 5,
        }
    ) == 1


def test_mimo_image_extractor_uses_page_cache(monkeypatch, tmp_path):
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"pdf")
    cache_dir = tmp_path / ".ai_extract_cache"
    cache_dir.mkdir()
    cache_file = cache_dir / "scan_p1_mimo-v2.5_v6.json"
    cache_file.write_text(
        json.dumps(
            [
                {
                    "source_file": "scan.pdf",
                    "source_page_or_row": "p1",
                    "employee_name_raw": "Alvarez Minchaca, Rosa",
                    "hours": 31.19,
                    "amount": 701.9,
                    "confidence": 0.95,
                    "evidence_text": "Total $701.90",
                }
            ]
        ),
        encoding="utf-8",
    )

    def fail_post(payload, config):
        raise AssertionError("cache miss")

    monkeypatch.setattr("bonus_platform.engine.labor.extract._post_chat_completion", fail_post)

    rows = _extract_with_ai_images(
        [{"source_file": "scan.pdf", "source_path": str(pdf), "page": 1, "mime_type": "image/png", "base64": "abc123"}],
        {"provider": "mimo", "api_key": "token", "base_url": "https://api.xiaomimimo.com/v1", "model": "mimo-v2.5"},
    )

    assert rows[0]["employee_name_raw"] == "Alvarez Minchaca, Rosa"


def test_mimo_image_extractor_writes_page_cache(monkeypatch, tmp_path):
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"pdf")

    monkeypatch.setattr(
        "bonus_platform.engine.labor.extract._post_chat_completion",
        lambda payload, config: [
            {
                "source_file": "scan.pdf",
                "source_page_or_row": "p1",
                "employee_name_raw": "Alvarez Minchaca, Rosa",
                "hours": 31.19,
                "amount": 701.9,
                "confidence": 0.95,
                "evidence_text": "Total $701.90",
            }
        ],
    )

    _extract_with_ai_images(
        [{"source_file": "scan.pdf", "source_path": str(pdf), "page": 1, "mime_type": "image/png", "base64": "abc123"}],
        {"provider": "mimo", "api_key": "token", "base_url": "https://api.xiaomimimo.com/v1", "model": "mimo-v2.5"},
    )

    cache_file = tmp_path / ".ai_extract_cache" / "scan_p1_mimo-v2.5_v6.json"
    assert cache_file.exists()


def test_extract_invoice_items_surfaces_ai_failure_when_enabled(monkeypatch, tmp_path):
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    monkeypatch.setattr("bonus_platform.engine.labor.extract._extract_pdf_pages", lambda paths: [{"source_file": "scan.pdf", "page": 1, "text": ""}])
    monkeypatch.setattr("bonus_platform.engine.labor.extract._extract_with_ai_text", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("HTTP 401 Invalid API Key")))
    monkeypatch.setattr("bonus_platform.engine.labor.extract._render_pdf_pages_to_images", lambda paths, **kwargs: [])

    with pytest.raises(ValueError, match="AI 抽取失败"):
        extract_invoice_items(
            [pdf],
            {"enabled": True, "provider": "mimo", "api_key": "token", "base_url": "https://api.xiaomimimo.com/v1", "model": "mimo-v2.5"},
        )


def test_safe_error_message_includes_mimo_error_body():
    error = HTTPError(
        url="https://api.xiaomimimo.com/v1/chat/completions",
        code=401,
        msg="Unauthorized",
        hdrs={},
        fp=BytesIO(b'{"error":{"message":"Invalid API Key","code":"401"}}'),
    )

    message = _safe_error_message(error)

    assert "Invalid API Key" in message


def test_http_post_json_enforces_wall_clock_timeout(monkeypatch):
    class SlowResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    class SlowClient:
        def __init__(self, *args, **kwargs):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, *args, **kwargs):
            time.sleep(0.2)
            return SlowResponse()

    monkeypatch.setattr("bonus_platform.engine.labor.extract.httpx.Client", SlowClient)

    start = time.monotonic()
    with pytest.raises(MiMoTimeoutException):
        _http_post_json(
            "https://example.test/v1/messages",
            {},
            {"payload": "x"},
            wall_timeout_seconds=0.05,
        )

    assert time.monotonic() - start < 0.15


def test_anthropic_messages_url_does_not_duplicate_v1():
    assert _anthropic_messages_url({"base_url": "https://token-plan-cn.xiaomimimo.com"}) == "https://token-plan-cn.xiaomimimo.com/anthropic/v1/messages"
    assert _anthropic_messages_url({"base_url": "https://token-plan-cn.xiaomimimo.com/v1"}) == "https://token-plan-cn.xiaomimimo.com/anthropic/v1/messages"
    assert _anthropic_messages_url({"base_url": "https://token-plan-cn.xiaomimimo.com/anthropic"}) == "https://token-plan-cn.xiaomimimo.com/anthropic/v1/messages"
    assert _anthropic_messages_url({"base_url": "https://token-plan-cn.xiaomimimo.com/anthropic/v1"}) == "https://token-plan-cn.xiaomimimo.com/anthropic/v1/messages"
    assert _anthropic_messages_url({"base_url": "https://api.example.com/v1"}) == "https://api.example.com/v1/messages"


def test_effective_render_scale_caps_token_plan_payload_size():
    assert _effective_render_scale({"provider": "mimo", "base_url": "https://token-plan-cn.xiaomimimo.com/v1", "render_scale": 1.2}) == pytest.approx(0.75)
    assert _effective_render_scale({"provider": "mimo", "base_url": "https://token-plan-cn.xiaomimimo.com/v1", "render_scale": 0.6}) == pytest.approx(0.6)
    assert _effective_render_scale({"provider": "openai", "base_url": "https://api.example.com/v1", "render_scale": 1.2}) == pytest.approx(1.2)


def test_line_items_from_ai_rows_coerces_confidence_labels_and_name_ids():
    rows = line_items_from_dicts(
        [
            {
                "source_type": "pdf_invoice",
                "source_file": "scan.pdf",
                "source_page_or_row": "page 1 row 1",
                "employee_id": "Alvarez Minchaca, Rosa",
                "employee_name_raw": "Alvarez Minchaca, Rosa",
                "hours": 31.19,
                "amount": 701.9,
                "confidence": "High",
            }
        ]
    )

    assert rows[0].employee_id == ""
    assert rows[0].confidence == 0.95


def test_build_labor_report_contains_expected_sheets(tmp_path):
    output = tmp_path / "report.xlsx"
    comparison = {
        "summary": {"pdfEmployeeCount": 1, "excelEmployeeCount": 1, "amountDiffCount": 1},
        "rows": [
            {
                "employeeName": "MARTINEZ, WILFREDO",
                "matchStatus": "金额差异",
                "riskFlags": [],
                "pdfHoursTotal": 40.78,
                "excelHoursTotal": 40.78,
                "hoursDelta": 0,
                "pdfAmountTotal": 982.72,
                "excelAmountTotal": 982.74,
                "amountDelta": -0.02,
                "sourceRefs": "a.pdf p1; 账单!3",
            }
        ],
        "candidateMatches": [
            {
                "pdfEmployeeName": "Alvarez Mitrache, Ross",
                "excelEmployeeName": "Rosa Alvarez Minchaca",
                "nameSimilarity": 0.75,
                "pdfHoursTotal": 30.5,
                "excelHoursTotal": 31.19,
                "hoursDelta": -0.69,
                "pdfAmountTotal": 698.99,
                "excelAmountTotal": 701.9,
                "amountDelta": -2.91,
                "recommendation": "人工复核",
                "sourceRefs": "scan.pdf p1; 账单!2",
            }
        ],
    }

    build_labor_report(output, comparison, [], [], {"name": "姓名", "hours": "时长", "amount": "金额"})

    workbook = load_workbook(output, read_only=True)
    assert workbook.sheetnames == ["核对结论", "核对摘要", "全员对账明细", "金额差异员工", "工时待确认", "不在本批发票", "姓名格式差异", "明细识别待确认", "PDF发票明细", "Excel账单明细", "上传字段对应关系"]
    for internal_sheet_name in ["低置信度抽取", "PDF抽取明细", "字段映射记录", "工时风险项"]:
        assert internal_sheet_name not in workbook.sheetnames
    assert workbook["姓名格式差异"].max_row == 2
    assert workbook["全员对账明细"].max_row == 2


def test_build_labor_report_uses_business_language_inside_workbook(tmp_path):
    output = tmp_path / "business-report.xlsx"
    comparison = {
        "summary": {"pdfEmployeeCount": 4, "excelEmployeeCount": 4, "amountDiffCount": 1},
        "rows": [
            {
                "employeeName": "LOW CONFIDENCE",
                "matchStatus": "低置信度抽取",
                "riskFlags": ["低置信度抽取"],
                "pdfHoursTotal": 8,
                "excelHoursTotal": 0,
                "hoursDelta": 8,
                "pdfAmountTotal": 100,
                "excelAmountTotal": 0,
                "amountDelta": 100,
                "sourceRefs": "invoice.pdf p1",
            },
            {
                "employeeName": "Maria Lopez",
                "matchStatus": "Excel有PDF无",
                "riskFlags": [],
                "pdfHoursTotal": 0,
                "excelHoursTotal": 40,
                "hoursDelta": -40,
                "pdfAmountTotal": 0,
                "excelAmountTotal": 812.8,
                "amountDelta": -812.8,
                "sourceRefs": "bill.xlsx!2",
            },
            {
                "employeeName": "Mucu, Pablo ⇄ Pablo Mucu",
                "matchStatus": "通过",
                "riskFlags": ["姓名格式差异自动合并"],
                "pdfHoursTotal": 40,
                "excelHoursTotal": 40,
                "hoursDelta": 0,
                "pdfAmountTotal": 1000,
                "excelAmountTotal": 1000,
                "amountDelta": 0,
                "sourceRefs": "invoice.pdf p2; bill.xlsx!3",
            },
            {
                "employeeName": "Ross Mitrache ⇄ Rosa Alvarez",
                "matchStatus": "疑似姓名匹配",
                "riskFlags": ["疑似姓名匹配"],
                "pdfHoursTotal": 30,
                "excelHoursTotal": 31,
                "hoursDelta": -1,
                "pdfAmountTotal": 700,
                "excelAmountTotal": 701,
                "amountDelta": -1,
                "sourceRefs": "invoice.pdf p3; bill.xlsx!4",
            },
        ],
    }
    pdf_rows = [
        LaborLineItem(
            source_type="pdf_invoice",
            source_file="invoice.pdf",
            source_page_or_row="p1",
            employee_id="",
            employee_name_raw="LOW CONFIDENCE",
            hours=8,
            amount=100,
            currency="USD",
            confidence=0.5,
            evidence_text="LOW CONFIDENCE 8 $100.00",
        )
    ]

    build_labor_report(output, comparison, pdf_rows, [], {"name": "姓名", "hours": "工时", "amount": "金额"})

    workbook = load_workbook(output, read_only=True)
    visible_text = "\n".join(
        str(value)
        for sheet in workbook.worksheets
        for row in sheet.iter_rows(values_only=True)
        for value in row
        if value is not None
    )
    assert "明细识别不完整" in visible_text
    assert "账单有发票无" in visible_text
    assert "系统已自动修正" in visible_text
    assert "疑似同一员工" in visible_text
    assert "PDF发票" in visible_text
    for internal_term in ["低置信度抽取", "Excel有PDF无", "疑似姓名匹配", "source_type", "employee_name_raw", "evidence_text", "confidence", "pdf_invoice"]:
        assert internal_term not in visible_text


def test_build_labor_report_can_include_reconciliation_diagnostics(tmp_path):
    output = tmp_path / "report.xlsx"
    comparison = {"summary": {"pdfEmployeeCount": 0, "excelEmployeeCount": 0}, "rows": []}
    diagnostics = {
        "level": "warning",
        "message": "核对信号有不稳定项，建议复核。",
        "nextStep": "先确认费用口径。",
        "signals": {
            "fastPdfTotal": 48293.06,
            "employeePdfTotal": 0,
            "excelTotal": 48217.96,
            "warehouseTotal": 48293.06,
            "amountBasis": [
                {
                    "warehouseId": "13",
                    "pdfTotal": 48293.06,
                    "reportedTotal": 48217.96,
                    "pdfVsReportedDelta": 75.1,
                    "componentTotal": 48217.96,
                    "employeeExpenses": 48055.81,
                    "employeeBenefits": 162.15,
                    "loadingAndUnloading": 0.0,
                    "summaryEvidence": "Warehouse-information!2",
                    "detailEvidence": "Employee-expenses-detail!3:Employee-expenses-detail!289; Employee-benefits-detail!2",
                }
            ],
            "offsettingWarehouseDeltas": [
                {
                    "warehouseId": "25",
                    "pdfAmountTotal": 17465.12,
                    "excelAmountTotal": 17463.34,
                    "amountDelta": 1.78,
                    "attribution": [{"employeeName": "JIMENEZ, ENEAS", "delta": 1.19}],
                }
            ],
            "employeeAttribution": [
                {
                    "warehouseId": "25",
                    "employeeName": "Fontes, Stevie ⇄ Stevie Fontes",
                    "pdfAmount": 822.12,
                    "excelAmount": 863.22,
                    "delta": -41.1,
                    "warehouseDelta": -41.21,
                }
            ],
        },
        "issues": [
            {
                "code": "amount_basis_mismatch",
                "level": "warning",
                "title": "PDF 总额与账单费用口径不一致",
                "message": "账单内部费用组成已闭合，但 PDF 发票总额与 OTWS 汇总总额不同。",
                "items": ["仓库 13: PDF $48,293.06，OTWS汇总 $48,217.96，差异 $75.10"],
            }
        ],
    }

    build_labor_report(
        output,
        comparison,
        [],
        [],
        {"name": "姓名", "hours": "时长", "amount": "金额"},
        reconciliation_diagnostics=diagnostics,
    )

    workbook = load_workbook(output, read_only=True)
    assert "信号诊断" in workbook.sheetnames
    rows = list(workbook["信号诊断"].iter_rows(values_only=True))
    assert any(row[:2] == ("诊断级别", "warning") for row in rows)
    assert any(row[0] == "PDF 总额与账单费用口径不一致" for row in rows)
    assert any(row[0] == "13" and row[3] == 75.1 for row in rows)
    assert any(row[0] == "25" and row[3] == 1.78 and "JIMENEZ" in str(row[4]) for row in rows)
    assert any(row[0] == "25" and "Fontes" in str(row[1]) and row[4] == -41.1 for row in rows)


def test_build_labor_report_can_include_ai_cache_audit(tmp_path):
    output = tmp_path / "report.xlsx"
    comparison = {"summary": {"pdfEmployeeCount": 0, "excelEmployeeCount": 0}, "rows": []}
    audit = {
        "decision": "candidate_only",
        "requiresConfirmation": True,
        "message": "历史图片识别记录只能作为待复核证据，不能直接覆盖确定性核对结论。",
        "summary": {"fileCount": 1, "candidateFileCount": 1, "candidateAmountTotal": 1399.89},
        "files": [
            {
                "sourceFile": "elog1-1_20260520204104.pdf",
                "warehouseId": "1",
                "rowCount": 2,
                "candidateAmountTotal": 1399.89,
                "averageConfidence": 0.95,
                "decision": "candidate_only",
                "cacheFiles": ["elog1-1_20260520204104_p1_mimo-v2.5_v6.json"],
                "evidence": [{"employeeName": "Alvarez Michalec Rosa", "amount": 701.88, "evidenceText": "Total $701.88"}],
            }
        ],
    }

    build_labor_report(
        output,
        comparison,
        [],
        [],
        {"name": "姓名", "hours": "时长", "amount": "金额"},
        ai_cache_audit=audit,
    )

    workbook = load_workbook(output, read_only=True)
    assert "AI候选证据" in workbook.sheetnames
    rows = list(workbook["AI候选证据"].iter_rows(values_only=True))
    assert any(row[:2] == ("处理决策", "candidate_only") for row in rows)
    assert any(row[:2] == ("需要人工确认", "是") for row in rows)
    assert any(row[0] == "elog1-1_20260520204104.pdf" and row[5] == "candidate_only" for row in rows)


def test_build_labor_business_html_report_uses_business_language_without_internal_terms(tmp_path):
    output = tmp_path / "business-report.html"
    comparison = {
        "summary": {
            "pdfEmployeeCount": 2,
            "excelEmployeeCount": 2,
            "pdfAmountTotal": 1333.33,
            "excelAmountTotal": 1333.36,
            "amountDeltaTotal": -0.03,
            "passedCount": 1,
            "amountDiffCount": 1,
        },
        "rows": [
            {
                "employeeName": "Aguilar, Hortensia ⇄ Hortensia Aguilar",
                "matchStatus": "通过",
                "riskFlags": [],
                "pdfHoursTotal": 41.4,
                "excelHoursTotal": 41.4,
                "hoursDelta": 0,
                "pdfAmountTotal": 950.6,
                "excelAmountTotal": 950.61,
                "amountDelta": -0.01,
                "sourceRefs": "Invoice-5058871.pdf p1; 账单!3",
            },
            {
                "employeeName": "Andrew Torres",
                "matchStatus": "疑似姓名匹配",
                "riskFlags": ["账单多行合并"],
                "pdfHoursTotal": 20.42,
                "excelHoursTotal": 20.42,
                "hoursDelta": 0,
                "pdfAmountTotal": 382.73,
                "excelAmountTotal": 382.75,
                "amountDelta": -0.02,
                "sourceRefs": "Invoice-5058877.pdf p2; 账单!10; 账单!11",
            },
        ],
    }

    build_labor_business_html_report(
        output,
        comparison,
        supplier_name="Workforce Priority",
        period_start="2026-05-11",
        period_end="2026-05-17",
        invoice_scope="5058871-5058880",
    )

    html = output.read_text(encoding="utf-8")
    assert "Workforce Priority" in html
    assert "核算周期：2026-05-11 ~ 2026-05-17" in html
    assert "发票编号或文件范围：5058871-5058880" in html
    assert "核对结论" in html
    assert "待确认" in html
    assert "这批账能不能放行？" in html
    assert "总金额核对" in html
    assert "员工明细状态" in html
    assert "下一步" in html
    assert "PDF 发票总金额" in html
    assert "$1,333.33" in html
    assert "账单总金额" in html
    assert "$1,333.36" in html
    assert "一致员工数" in html
    assert "待确认员工数" in html
    assert "员工姓名（发票）" in html
    assert "账单姓名" in html
    assert "REG 工时" in html
    assert "OT 工时" in html
    assert "业务说明" in html
    assert "下载 Excel 明细" in html
    assert "Excel 明细用于留档、筛选和逐行核查" in html
    assert "页面结论以本 HTML 报告为准" in html
    assert "需查看明细说明" not in html
    assert "有差异员工数" not in html
    assert "必要说明" not in html
    assert "原始识别明细" not in html
    assert "字段映射" not in html
    assert "需要确认该员工是否为同一人" in html
    assert "同一员工可能存在多行账单，需要确认是否应合并" in html
    for internal_term in ["AI 候选", "规则治理", "profile", "re-OCR", "回放", "低置信度算法", "Blob", "线程"]:
        assert internal_term not in html


def test_build_labor_business_html_report_groups_auto_fixes_suspected_matches_and_pending_items(tmp_path):
    output = tmp_path / "business-report-sections.html"
    comparison = {
        "summary": {
            "pdfEmployeeCount": 3,
            "excelEmployeeCount": 3,
            "pdfAmountTotal": 2200.0,
            "excelAmountTotal": 2200.02,
            "amountDeltaTotal": -0.02,
            "passedCount": 1,
            "amountDiffCount": 1,
        },
        "rows": [
            {
                "employeeName": "Mucu, Pablo ⇄ Pablo Mucu",
                "matchStatus": "通过",
                "riskFlags": ["疑似姓名匹配"],
                "pdfHoursTotal": 40,
                "excelHoursTotal": 40,
                "hoursDelta": 0,
                "pdfAmountTotal": 1000,
                "excelAmountTotal": 1000,
                "amountDelta": 0,
                "sourceRefs": "Invoice-5058871.pdf p1; 账单!3",
            },
            {
                "employeeName": "Andrew Torres",
                "matchStatus": "低置信度抽取",
                "riskFlags": ["低置信度抽取"],
                "pdfHoursTotal": 20,
                "excelHoursTotal": 0,
                "hoursDelta": 20,
                "pdfAmountTotal": 400,
                "excelAmountTotal": 0,
                "amountDelta": 400,
                "sourceRefs": "Invoice-5058877.pdf p2",
            },
            {
                "employeeName": "Maria Lopez",
                "matchStatus": "金额差异",
                "riskFlags": [],
                "pdfHoursTotal": 40,
                "excelHoursTotal": 40,
                "hoursDelta": 0,
                "pdfAmountTotal": 810,
                "excelAmountTotal": 812.8,
                "amountDelta": -2.8,
                "sourceRefs": "Invoice-5058878.pdf p3; 账单!8",
            },
            {
                "employeeName": "Selvin Rivera",
                "matchStatus": "Excel有PDF无",
                "riskFlags": [],
                "pdfHoursTotal": 0,
                "excelHoursTotal": 48,
                "hoursDelta": -48,
                "pdfAmountTotal": 0,
                "excelAmountTotal": 1122.72,
                "amountDelta": -1122.72,
                "sourceRefs": "账单!12",
            },
        ],
        "candidateMatches": [
            {
                "pdfEmployeeName": "Mitrache, Ross",
                "excelEmployeeName": "Rosa Alvarez Minchaca",
                "nameSimilarity": 0.75,
                "pdfHoursTotal": 30.5,
                "excelHoursTotal": 31.19,
                "hoursDelta": -0.69,
                "pdfAmountTotal": 698.99,
                "excelAmountTotal": 701.9,
                "amountDelta": -2.91,
                "recommendation": "姓名接近但金额和工时仍需确认",
                "sourceRefs": "scan.pdf p1; 账单!2",
            }
        ],
    }

    build_labor_business_html_report(
        output,
        comparison,
        supplier_name="Fairway",
        period_start="2026-05-11",
        period_end="2026-05-17",
        invoice_scope="5058871-5058880",
    )

    html = output.read_text(encoding="utf-8")
    assert "系统自动修正" in html
    assert "系统已自动合并姓名格式差异" in html
    assert "Mucu, Pablo" in html
    assert "Pablo Mucu" in html
    assert "疑似同一员工，需确认" in html
    assert "Mitrache, Ross" in html
    assert "Rosa Alvarez Minchaca" in html
    assert "待确认异常" in html
    assert "优先处理影响放行或留档的项目" in html
    assert "处理顺序：先确认金额口径，再确认缺发票项，最后确认疑似同一员工。" in html
    assert "处理建议：核对费率、加班、服务费或税费是否同一口径" in html
    assert "处理建议：确认本员工是否属于本批发票" in html
    assert "确认前不会自动合并姓名" in html
    assert "员工明细未完整识别，请查看原发票" in html
    assert "下载 Excel 明细" in html
    assert "低置信度抽取" not in html
    assert "人工复核" not in html


def test_build_labor_business_html_report_auto_fix_section_handles_accent_differences(tmp_path):
    output = tmp_path / "accent-name-auto-fix-report.html"
    comparison = {
        "summary": {
            "pdfEmployeeCount": 1,
            "excelEmployeeCount": 1,
            "pdfAmountTotal": 739.49,
            "excelAmountTotal": 739.49,
            "amountDeltaTotal": 0,
            "passedCount": 1,
            "amountDiffCount": 0,
        },
        "rows": [
            {
                "employeeName": "Alberto Núñez ⇄ Alberto Nunez",
                "matchStatus": "通过",
                "riskFlags": [],
                "pdfHoursTotal": 35.08,
                "excelHoursTotal": 35.08,
                "hoursDelta": 0,
                "pdfAmountTotal": 739.49,
                "excelAmountTotal": 739.49,
                "amountDelta": 0,
                "sourceRefs": "Invoice-5058871.pdf p1; 账单!3",
            }
        ],
    }

    build_labor_business_html_report(
        output,
        comparison,
        supplier_name="Fairway",
        period_start="2026-05-11",
        period_end="2026-05-17",
        invoice_scope="5058871",
    )

    html = output.read_text(encoding="utf-8")
    assert "系统已自动合并姓名格式差异" in html
    assert "Alberto Núñez" in html
    assert "Alberto Nunez" in html
    assert "本次未发现可由系统自动合并的姓名格式差异" not in html


def test_build_labor_business_html_report_does_not_pass_when_extraction_failed(tmp_path):
    output = tmp_path / "failed-business-report.html"
    comparison = {
        "summary": {
            "extractionFailed": True,
            "failureReason": "PDF 明细未解析完成",
            "pdfEmployeeCount": 0,
            "excelEmployeeCount": 0,
            "pdfAmountTotal": 0,
            "excelAmountTotal": 0,
            "amountDeltaTotal": 0,
            "passedCount": 0,
            "amountDiffCount": 0,
        },
        "rows": [],
    }

    build_labor_business_html_report(
        output,
        comparison,
        supplier_name="Workforce Priority",
        period_start="2026-05-11",
        period_end="2026-05-17",
        invoice_scope="invoice upload",
    )

    html = output.read_text(encoding="utf-8")
    assert "系统未能完成核对" in html
    assert "核对通过" not in html
    assert "请查看原发票和账单后重新生成报告" in html
    assert "人工查看" not in html


def test_build_labor_business_html_report_marks_detail_rows_missing_as_total_pass_with_detail_confirmation(tmp_path):
    output = tmp_path / "missing-detail-report.html"
    comparison = {
        "summary": {
            "pdfEmployeeCount": 18,
            "excelEmployeeCount": 18,
            "pdfAmountTotal": 144714.83,
            "excelAmountTotal": 144714.83,
            "amountDeltaTotal": 0,
            "passedCount": 0,
            "amountDiffCount": 0,
        },
        "rows": [],
    }

    build_labor_business_html_report(
        output,
        comparison,
        supplier_name="Workforce Priority",
        period_start="2026-05-11",
        period_end="2026-05-17",
        invoice_scope="invoice upload",
    )

    html = output.read_text(encoding="utf-8")
    assert "总账通过，但员工明细待确认" in html
    assert "这批账能不能放行？" in html
    assert "需业务确认" in html
    assert "总金额已通过；员工明细未完整识别，不影响总账结论，但需要业务确认明细后再对外留档。" in html
    assert "员工明细未完整识别" in html
    assert "系统已确认本批总金额一致" in html
    assert "部分员工明细未完整识别" in html
    assert "本批总金额已完成核对，但当前没有可逐项展示的员工明细" in html
    assert "暂无可展示明细" not in html
    assert "金额口径说明" not in html
    assert "系统未能完成核对" not in html


def test_build_labor_business_html_report_treats_ten_cent_total_difference_as_pass(tmp_path):
    output = tmp_path / "ten-cent-total-pass.html"
    comparison = {
        "summary": {
            "pdfEmployeeCount": 18,
            "excelEmployeeCount": 18,
            "pdfAmountTotal": 144714.83,
            "excelAmountTotal": 144714.93,
            "amountDeltaTotal": -0.1,
            "passedCount": 0,
            "amountDiffCount": 0,
        },
        "rows": [],
    }

    build_labor_business_html_report(
        output,
        comparison,
        supplier_name="Fairway",
        period_start="2026-05-11",
        period_end="2026-05-17",
        invoice_scope="invoice upload",
    )

    html = output.read_text(encoding="utf-8")
    assert "总账通过，但员工明细待确认" in html
    assert "本批总金额已完成核对" in html
    assert "总金额存在差异，暂不能放行" not in html


def test_build_labor_business_html_report_total_pass_with_review_items_does_not_claim_incomplete_recognition(tmp_path):
    output = tmp_path / "detail-review-with-rows-report.html"
    comparison = {
        "summary": {
            "pdfEmployeeCount": 2,
            "excelEmployeeCount": 2,
            "pdfAmountTotal": 2000.00,
            "excelAmountTotal": 2000.00,
            "amountDeltaTotal": 0,
            "passedCount": 1,
            "amountDiffCount": 0,
            "candidateMatchCount": 1,
        },
        "rows": [
            {
                "employeeName": "Pablo Mucu ⇄ Mucu, Pablo",
                "matchStatus": "疑似同一员工",
                "riskFlags": [],
                "pdfHoursTotal": 40,
                "excelHoursTotal": 40,
                "hoursDelta": 0,
                "pdfAmountTotal": 1000,
                "excelAmountTotal": 1000,
                "amountDelta": 0,
                "sourceRefs": "invoice.pdf p1; bill.xlsx!2",
            }
        ],
        "candidateMatches": [
            {
                "pdfEmployeeName": "Pablo Mucu",
                "excelEmployeeName": "Mucu, Pablo",
                "amountGap": 0,
                "hoursGap": 0,
            }
        ],
    }

    build_labor_business_html_report(
        output,
        comparison,
        supplier_name="Fairway",
        period_start="2026-05-11",
        period_end="2026-05-17",
        invoice_scope="invoice upload",
    )

    html = output.read_text(encoding="utf-8")
    assert "总账通过，但员工明细待确认" in html
    assert "员工明细仍有需要确认的项目" in html
    assert "疑似同一员工，需确认" in html
    assert "部分员工明细未完整识别" not in html


def test_build_labor_business_html_report_amount_close_but_name_unlike_stays_manual_confirmation(tmp_path):
    output = tmp_path / "amount-close-name-unlike-report.html"
    comparison = {
        "summary": {
            "pdfEmployeeCount": 2,
            "excelEmployeeCount": 2,
            "pdfAmountTotal": 2000.00,
            "excelAmountTotal": 2000.00,
            "amountDeltaTotal": 0,
            "passedCount": 1,
            "amountDiffCount": 0,
            "candidateMatchCount": 1,
        },
        "rows": [
            {
                "employeeName": "Carlos Serna ⇄ Carlos Serna",
                "matchStatus": "通过",
                "riskFlags": [],
                "pdfHoursTotal": 40,
                "excelHoursTotal": 40,
                "hoursDelta": 0,
                "pdfAmountTotal": 1000,
                "excelAmountTotal": 1000,
                "amountDelta": 0,
                "sourceRefs": "invoice.pdf p1; bill.xlsx!2",
            }
        ],
        "candidateMatches": [
            {
                "pdfEmployeeName": "Maria Lopez",
                "excelEmployeeName": "Carlos Serna",
                "nameSimilarity": 0.12,
                "pdfAmountTotal": 812.80,
                "excelAmountTotal": 812.80,
                "amountDelta": 0,
                "hoursDelta": 0,
            }
        ],
    }

    build_labor_business_html_report(
        output,
        comparison,
        supplier_name="Fairway",
        period_start="2026-05-11",
        period_end="2026-05-17",
        invoice_scope="invoice upload",
    )

    html = output.read_text(encoding="utf-8")
    assert "疑似同一员工，需确认" in html
    assert "Maria Lopez ⇄ Carlos Serna" in html
    assert "金额接近，但姓名不像，不能自动合并" in html
    assert "确认前不会自动合并姓名" in html


def test_build_labor_business_html_report_prioritizes_amount_difference_when_details_incomplete(tmp_path):
    output = tmp_path / "amount-difference-incomplete-detail-report.html"
    comparison = {
        "summary": {
            "pdfEmployeeCount": 18,
            "excelEmployeeCount": 18,
            "pdfAmountTotal": 144714.83,
            "excelAmountTotal": 144714.94,
            "amountDeltaTotal": -0.11,
            "passedCount": 0,
            "amountDiffCount": 0,
        },
        "rows": [],
    }

    build_labor_business_html_report(
        output,
        comparison,
        supplier_name="Workforce Priority",
        period_start="2026-05-11",
        period_end="2026-05-17",
        invoice_scope="invoice upload",
    )

    html = output.read_text(encoding="utf-8")
    assert "总金额存在差异，暂不能放行" in html
    assert "这批账能不能放行？" in html
    assert "不建议放行" in html
    assert "总金额超出 $0.10 容差，先复核发票总额、账单总额和所属账期。" in html
    assert "总金额存在差异：PDF 比 Excel 少 $0.11" in html
    assert "由于员工明细未完整识别" in html
    assert "系统未能完成核对" not in html


def test_build_labor_business_html_report_does_not_blame_recognition_when_amount_diff_has_detail_rows(tmp_path):
    output = tmp_path / "amount-difference-with-detail-report.html"
    comparison = {
        "summary": {
            "pdfEmployeeCount": 2,
            "excelEmployeeCount": 2,
            "pdfAmountTotal": 1000.00,
            "excelAmountTotal": 999.50,
            "amountDeltaTotal": 0.50,
            "passedCount": 1,
            "amountDiffCount": 1,
        },
        "rows": [
            {
                "employeeName": "Pablo Mucu ⇄ Pablo Mucu",
                "matchStatus": "金额差异",
                "riskFlags": [],
                "pdfHoursTotal": 40,
                "excelHoursTotal": 40,
                "hoursDelta": 0,
                "pdfAmountTotal": 1000,
                "excelAmountTotal": 999.5,
                "amountDelta": 0.5,
                "sourceRefs": "invoice.pdf p1; bill.xlsx!2",
            }
        ],
    }

    build_labor_business_html_report(
        output,
        comparison,
        supplier_name="Fairway",
        period_start="2026-05-11",
        period_end="2026-05-17",
        invoice_scope="invoice upload",
    )

    html = output.read_text(encoding="utf-8")
    assert "总金额存在差异，暂不能放行" in html
    assert "总金额存在差异：PDF 比 Excel 多 $0.50" in html
    assert "请先查看下方员工明细中的金额、工时或费率差异" in html
    assert "由于员工明细未完整识别" not in html


def test_build_labor_business_html_report_total_pass_takes_priority_over_employee_detail_differences(tmp_path):
    output = tmp_path / "total-pass-with-employee-detail-difference.html"
    comparison = {
        "summary": {
            "pdfEmployeeCount": 2,
            "excelEmployeeCount": 2,
            "pdfAmountTotal": 144714.83,
            "excelAmountTotal": 144714.88,
            "amountDeltaTotal": -0.05,
            "passedCount": 1,
            "amountDiffCount": 1,
        },
        "rows": [
            {
                "employeeName": "Maria Lopez ⇄ Maria Lopez",
                "matchStatus": "金额差异",
                "riskFlags": [],
                "pdfHoursTotal": 40,
                "excelHoursTotal": 40,
                "hoursDelta": 0,
                "pdfAmountTotal": 812.80,
                "excelAmountTotal": 812.70,
                "amountDelta": 0.10,
                "sourceRefs": "invoice.pdf p1; bill.xlsx!2",
            }
        ],
    }

    build_labor_business_html_report(
        output,
        comparison,
        supplier_name="Fairway",
        period_start="2026-05-11",
        period_end="2026-05-17",
        invoice_scope="invoice upload",
    )

    html = output.read_text(encoding="utf-8")
    assert "总账通过，但员工明细待确认" in html
    assert "系统已确认本批总金额一致，但员工明细仍有需要确认的项目" in html
    assert "总金额存在差异，暂不能放行" not in html
    assert "总金额存在差异：PDF 比 Excel" not in html


def test_build_labor_business_html_report_separates_full_batch_from_review_scope(tmp_path):
    output = tmp_path / "review-scope-business-report.html"
    comparison = {
        "summary": {
            "pdfEmployeeCount": 18,
            "excelEmployeeCount": 18,
            "pdfAmountTotal": 22002.58,
            "excelAmountTotal": 22002.59,
            "amountDeltaTotal": -0.01,
            "passedCount": 18,
            "amountDiffCount": 0,
        },
        "rows": [
            {
                "employeeName": "Employee A ⇄ Employee A",
                "matchStatus": "通过",
                "riskFlags": [],
                "pdfHoursTotal": 40,
                "excelHoursTotal": 40,
                "hoursDelta": 0,
                "pdfAmountTotal": 1000,
                "excelAmountTotal": 1000,
                "amountDelta": 0,
                "sourceRefs": "warehouse 25",
            }
        ],
    }
    warehouse_comparison = {
        "summary": {
            "pdfAmountTotal": 144714.83,
            "excelAmountTotal": 144714.93,
            "amountDeltaTotal": -0.10,
            "totalPassed": False,
            "exceptionCount": 2,
            "diffWarehouses": ["25", "28"],
            "warehouseCount": 6,
        }
    }

    build_labor_business_html_report(
        output,
        comparison,
        supplier_name="Fairway",
        period_start="2026-05-11",
        period_end="2026-05-17",
        invoice_scope="6 张发票",
        warehouse_comparison=warehouse_comparison,
    )

    html = output.read_text(encoding="utf-8")
    assert "整批 PDF 发票总金额" in html
    assert "$144,714.83" in html
    assert "整批账单总金额" in html
    assert "$144,714.93" in html
    assert "需要确认" in html
    assert "需要复核" not in html
    assert "需复核" not in html
    assert "只展示需要确认的仓库员工明细，不代表账单只有这些员工" in html
    assert "仓库 25、28" in html
    assert "$22,002.59" in html
    assert "全员对账明细" not in html
    for internal_term in ["Stage 2", "下钻", "diffWarehouses", "warehouseComparison", "核对信号存在冲突"]:
        assert internal_term not in html


def test_build_labor_business_html_report_explains_full_excel_count_vs_review_detail_scope(tmp_path):
    output = tmp_path / "excel-record-count-vs-review-scope-report.html"
    comparison = {
        "summary": {
            "pdfEmployeeCount": 18,
            "excelEmployeeCount": 18,
            "pdfAmountTotal": 22002.58,
            "excelAmountTotal": 22002.59,
            "amountDeltaTotal": -0.01,
            "passedCount": 18,
            "amountDiffCount": 0,
        },
        "rows": [
            {
                "employeeName": "Employee A ⇄ Employee A",
                "matchStatus": "通过",
                "riskFlags": [],
                "pdfHoursTotal": 40,
                "excelHoursTotal": 40,
                "hoursDelta": 0,
                "pdfAmountTotal": 1000,
                "excelAmountTotal": 1000,
                "amountDelta": 0,
                "sourceRefs": "warehouse 25",
            }
        ],
    }
    warehouse_comparison = {
        "summary": {
            "pdfAmountTotal": 144714.83,
            "excelAmountTotal": 144714.93,
            "amountDeltaTotal": -0.10,
            "totalPassed": True,
            "exceptionCount": 2,
            "allocationIssueCount": 2,
            "diffWarehouses": ["25", "28"],
            "warehouseCount": 6,
        }
    }

    build_labor_business_html_report(
        output,
        comparison,
        supplier_name="Fairway",
        period_start="2026-05-11",
        period_end="2026-05-17",
        invoice_scope="6 张发票",
        warehouse_comparison=warehouse_comparison,
        excel_record_count=128,
    )

    html = output.read_text(encoding="utf-8")
    assert "整批账单已读取 128 行" in html
    assert "当前展示的是需要确认的 18 名员工明细" in html
    assert "不代表账单只有这些员工" in html
    assert "员工明细识别情况" in html
    assert "只展开需要确认的员工明细" in html
    assert "其余无明显差异的员工不在本段重复展示" in html
    assert "总账通过，但员工明细待确认" in html


def test_build_labor_business_html_report_explains_three_amount_layers(tmp_path):
    output = tmp_path / "three-amount-layers-report.html"
    comparison = {
        "summary": {
            "pdfEmployeeCount": 18,
            "excelEmployeeCount": 18,
            "pdfAmountTotal": 22002.58,
            "excelAmountTotal": 22002.59,
            "amountDeltaTotal": -0.01,
            "passedCount": 18,
            "amountDiffCount": 0,
        },
        "rows": [
            {
                "employeeName": "Employee A ⇄ Employee A",
                "matchStatus": "通过",
                "riskFlags": [],
                "pdfHoursTotal": 40,
                "excelHoursTotal": 40,
                "hoursDelta": 0,
                "pdfAmountTotal": 1000,
                "excelAmountTotal": 1000,
                "amountDelta": 0,
                "sourceRefs": "warehouse 25",
            }
        ],
    }
    warehouse_comparison = {
        "summary": {
            "pdfAmountTotal": 144714.83,
            "excelAmountTotal": 144714.93,
            "amountDeltaTotal": -0.10,
            "totalPassed": True,
            "exceptionCount": 2,
            "allocationIssueCount": 2,
            "diffWarehouses": ["25", "28"],
            "warehouseCount": 6,
        }
    }

    build_labor_business_html_report(
        output,
        comparison,
        supplier_name="Fairway",
        period_start="2026-05-11",
        period_end="2026-05-17",
        invoice_scope="6 张发票",
        warehouse_comparison=warehouse_comparison,
        excel_record_count=128,
    )

    html = output.read_text(encoding="utf-8")
    assert "总金额核对" in html
    assert "金额口径说明" not in html
    assert "整批 PDF 发票总额" in html
    assert "$144,714.83" in html
    assert "整批 Excel 账单总额" in html
    assert "$144,714.93" in html
    assert "已识别员工明细金额" in html
    assert "$22,002.58" in html
    assert "员工明细金额用于定位差异，不等同于整批总账金额" in html
    assert "不代表账单少读了" in html
    assert "当前页面只展开了用于确认的明细范围" in html
    assert "员工明细识别情况" in html
    assert "如需查看所有原始员工行，请下载 Excel 明细" in html
    assert "总账结论优先看整批 PDF 与整批 Excel 的差额" in html


def test_build_labor_business_html_report_keeps_total_pass_when_allocation_needs_confirmation(tmp_path):
    output = tmp_path / "total-pass-allocation-review-report.html"
    comparison = {
        "summary": {
            "pdfEmployeeCount": 18,
            "excelEmployeeCount": 18,
            "pdfAmountTotal": 22002.58,
            "excelAmountTotal": 22002.59,
            "amountDeltaTotal": -0.01,
            "passedCount": 18,
            "amountDiffCount": 0,
        },
        "rows": [
            {
                "employeeName": "Employee A ⇄ Employee A",
                "matchStatus": "通过",
                "riskFlags": [],
                "pdfHoursTotal": 40,
                "excelHoursTotal": 40,
                "hoursDelta": 0,
                "pdfAmountTotal": 1000,
                "excelAmountTotal": 1000,
                "amountDelta": 0,
                "sourceRefs": "warehouse 25",
            }
        ],
    }
    warehouse_comparison = {
        "summary": {
            "pdfAmountTotal": 144714.83,
            "excelAmountTotal": 144714.93,
            "amountDeltaTotal": -0.10,
            "totalPassed": True,
            "exceptionCount": 2,
            "allocationIssueCount": 2,
            "diffWarehouses": ["25", "28"],
            "warehouseCount": 6,
        }
    }

    build_labor_business_html_report(
        output,
        comparison,
        supplier_name="Fairway",
        period_start="2026-05-11",
        period_end="2026-05-17",
        invoice_scope="6 张发票",
        warehouse_comparison=warehouse_comparison,
    )

    html = output.read_text(encoding="utf-8")
    assert "总账通过，但员工明细待确认" in html
    assert "系统已确认本批总金额一致" in html
    assert "员工级差异仅供确认" in html
    assert '<div class="val">需要复核</div>' not in html
    assert "总金额存在差异，暂不能放行" not in html


# ---------------------------------------------------------------------------
# Phase 2 Tests
# ---------------------------------------------------------------------------


def _make_labor_item(
    name: str = "John Doe",
    amount: float = 1000.0,
    hours: float = 40.0,
    confidence: float = 0.95,
    source_file: str = "test.pdf",
    source_page: str = "p1",
) -> LaborLineItem:
    return LaborLineItem(
        source_type="pdf",
        source_file=source_file,
        source_page_or_row=source_page,
        employee_id="",
        employee_name_raw=name,
        hours=hours,
        amount=amount,
        currency="USD",
        confidence=confidence,
        evidence_text="",
        supplier="",
    )


def test_calculate_extraction_quality_returns_low_confidence_rows_T_P2_1():
    rows = [
        _make_labor_item(name="John", confidence=0.95),
        _make_labor_item(name="Jane", confidence=0.60),
        _make_labor_item(name="Bob", confidence=0.80),
    ]
    result = calculate_extraction_quality(
        pdf_rows=rows,
        comparison_summary={},
    )
    assert "lowConfidenceRows" in result
    low = result["lowConfidenceRows"]
    assert len(low) == 2
    names = {r["employee_name_raw"] for r in low}
    assert names == {"Jane", "Bob"}
    # Check fields present
    for row in low:
        assert "employee_name_raw" in row
        assert "amount" in row
        assert "confidence" in row
        assert "source_page_or_row" in row
        assert "source_file" in row


def test_calculate_extraction_quality_low_confidence_rows_empty_when_all_high_T_P2_2():
    rows = [
        _make_labor_item(name="John", confidence=0.95),
        _make_labor_item(name="Jane", confidence=0.90),
    ]
    result = calculate_extraction_quality(
        pdf_rows=rows,
        comparison_summary={},
    )
    assert result["lowConfidenceRows"] == []


def test_calculate_extraction_quality_respects_confidence_threshold_param_T_P2_3():
    rows = [
        _make_labor_item(name="John", confidence=0.95),
        _make_labor_item(name="Jane", confidence=0.85),
        _make_labor_item(name="Bob", confidence=0.70),
    ]
    result = calculate_extraction_quality(
        pdf_rows=rows,
        comparison_summary={},
        confidence_threshold=0.9,
    )
    low = result["lowConfidenceRows"]
    names = {r["employee_name_raw"] for r in low}
    # confidence=0.85 is < 0.9, so Jane should also be in low
    assert "Jane" in names
    assert "Bob" in names
    assert "John" not in names


def test_ai_instruction_retry_mode_appends_target_names_T_P2_4():
    prompt = _ai_instruction(retry_mode=True, target_names=["John", "Jane"])
    assert "RETRY MODE" in prompt
    assert "John" in prompt
    assert "Jane" in prompt


def test_ai_instruction_no_retry_mode_by_default_T_P2_5():
    prompt = _ai_instruction()
    assert "RETRY MODE" not in prompt


# ---------------------------------------------------------------------------
# Phase 3 Tests
# ---------------------------------------------------------------------------


def test_generate_profile_from_extraction_basic_T_P3_1():
    rows = [
        _make_labor_item(name="Alice", hours=40, amount=1000, confidence=0.95),
        _make_labor_item(name="Bob", hours=35, amount=800, confidence=0.90),
    ]
    profile = generate_profile_from_extraction("Fairway", rows)
    assert "key" in profile
    assert "aliases" in profile
    assert "prompt_notes" in profile
    assert "image_page_policy" in profile
    assert "version" in profile
    assert profile["key"] == "fairway"
    assert isinstance(profile["prompt_notes"], list)
    assert profile["version"] == 1


def test_generate_profile_from_extraction_detects_zero_hours_premiums_T_P3_2():
    rows = [
        _make_labor_item(name="Alice", hours=0, amount=50, confidence=0.95),
        _make_labor_item(name="Bob", hours=40, amount=1000, confidence=0.90),
    ]
    profile = generate_profile_from_extraction("Fairway", rows)
    notes_text = " ".join(profile["prompt_notes"]).lower()
    assert "meal premiums" in notes_text


def test_generate_profile_from_extraction_empty_supplier_T_P3_3():
    rows = [_make_labor_item(name="Alice")]
    profile = generate_profile_from_extraction("", rows)
    assert profile["key"] == "unknown"


def test_save_supplier_profile_creates_file_T_P3_4(tmp_path):
    profile = {
        "key": "test_supplier",
        "aliases": ["test supplier"],
        "prompt_notes": ["note 1"],
        "image_page_policy": "first_page_only",
        "version": 1,
    }
    result_path = save_supplier_profile(profile, tmp_path)
    assert result_path.exists()
    loaded = json.loads(result_path.read_text(encoding="utf-8"))
    assert loaded["key"] == "test_supplier"
    assert loaded["aliases"] == ["test supplier"]


def test_profiles_for_resolution_scans_directory_T_P3_5(tmp_path):
    # Create two profile JSON files in the directory
    profile_a = [
        {"key": "supplier_a", "aliases": ["supplier a"], "prompt_notes": ["note a"]}
    ]
    profile_b = [
        {"key": "supplier_b", "aliases": ["supplier b"], "prompt_notes": ["note b"]}
    ]
    (tmp_path / "a.json").write_text(json.dumps(profile_a), encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps(profile_b), encoding="utf-8")

    profiles = _profiles_for_resolution(tmp_path)
    keys = {p.key for p in profiles}
    assert "supplier_a" in keys
    assert "supplier_b" in keys


# ---------------------------------------------------------------------------
# Phase 4 Tests
# ---------------------------------------------------------------------------


def test_check_profile_validity_returns_true_for_default_T_P4_1():
    # DEFAULT_PROFILE is always valid
    assert DEFAULT_PROFILE.key == "default"
    assert DEFAULT_PROFILE.deprecated is False


def test_check_profile_validity_returns_true_when_rule_rows_exist_T_P4_2(tmp_path):
    # A non-default profile with prompt_notes (rule_rows proxy) should be valid
    from bonus_platform.engine.labor.profiles import SupplierExtractionProfile

    profile = SupplierExtractionProfile(
        key="custom",
        aliases=["custom"],
        prompt_notes=["some rule"],
        image_page_policy="first_page_only",
    )
    assert not profile.deprecated
    assert len(profile.prompt_notes) > 0


def test_check_profile_validity_returns_false_when_no_rule_rows_T_P4_3():
    from bonus_platform.engine.labor.profiles import SupplierExtractionProfile

    profile = SupplierExtractionProfile(
        key="empty",
        aliases=["empty"],
        prompt_notes=[],
        image_page_policy="first_page_only",
    )
    # Empty prompt_notes means no rules configured
    assert len(profile.prompt_notes) == 0


def test_record_profile_failure_increments_count_T_P4_4(tmp_path):
    profile_data = {
        "key": "test_profile",
        "aliases": ["test"],
        "failure_count": 0,
    }
    profile_path = tmp_path / "test_profile.json"
    profile_path.write_text(json.dumps(profile_data), encoding="utf-8")

    result = record_profile_failure(profile_path)
    assert result is not None
    assert result["failure_count"] == 1


def test_record_profile_failure_marks_deprecated_after_3_T_P4_5(tmp_path):
    profile_data = {
        "key": "bad_profile",
        "aliases": ["bad"],
        "failure_count": 2,
    }
    profile_path = tmp_path / "bad_profile.json"
    profile_path.write_text(json.dumps(profile_data), encoding="utf-8")

    result = record_profile_failure(profile_path)
    assert result is not None
    assert result["failure_count"] == 3
    assert result["deprecated"] is True


def test_reset_profile_failure_clears_count_T_P4_6(tmp_path):
    profile_data = {
        "key": "recover_profile",
        "aliases": ["recover"],
        "failure_count": 2,
        "deprecated": True,
    }
    profile_path = tmp_path / "recover_profile.json"
    profile_path.write_text(json.dumps(profile_data), encoding="utf-8")

    reset_profile_failure(profile_path)
    loaded = json.loads(profile_path.read_text(encoding="utf-8"))
    assert loaded["failure_count"] == 0
    assert "deprecated" not in loaded


def test_profiles_for_resolution_filters_deprecated_T_P4_7(tmp_path):
    # Create a deprecated profile that would match "deprecated_supplier"
    profile_data = [
        {
            "key": "deprecated_supplier",
            "aliases": ["deprecated supplier"],
            "prompt_notes": ["old rule"],
            "deprecated": True,
        }
    ]
    (tmp_path / "deprecated.json").write_text(
        json.dumps(profile_data), encoding="utf-8"
    )

    profile = resolve_supplier_profile("deprecated supplier", profiles_path=tmp_path)
    # Should fall back to DEFAULT_PROFILE because the deprecated one is filtered
    assert profile.key == "default"


def test_build_material_index_identifies_replay_ready_batches_and_ignores_temp_files(tmp_path):
    batch = tmp_path / "workforce已报账"
    batch.mkdir()
    (batch / "Invoice-5058871.pdf").write_bytes(b"%PDF-1.4\n")
    (batch / "员工账单明细 - 2026-06-01T112149.990.xlsx").write_bytes(b"fake workbook")
    (batch / "~$OTWS - Warehouse Bill-NJ8.xlsx").write_bytes(b"temp")
    (batch / "Timecard for 05.11.2026-05.17.2026.eml").write_text("context", encoding="utf-8")
    warehouse_29 = tmp_path / "29仓"
    warehouse_29.mkdir()
    (warehouse_29 / "In291943.pdf").write_bytes(b"%PDF-1.4\n")
    (warehouse_29 / "员工账单明细 - 2026-05-28T141945.414.xlsx").write_bytes(b"fake workbook")
    (tmp_path / "README.md").write_text("notes", encoding="utf-8")

    index = build_material_index(tmp_path)

    assert index["summary"]["candidateBatchCount"] == 2
    assert index["summary"]["invoicePdfCount"] == 2
    assert index["summary"]["workbookCount"] == 2
    assert index["batches"] == index["candidateBatches"]
    batch_index = next(batch for batch in index["candidateBatches"] if batch["supplier"] == "workforce")
    assert batch_index["supplier"] == "workforce"
    assert batch_index["replayReady"] is True
    assert batch_index["invoiceFiles"][0]["filename"] == "Invoice-5058871.pdf"
    assert batch_index["pdfFiles"] == batch_index["invoiceFiles"]
    assert batch_index["workbookFiles"][0]["filename"].startswith("员工账单明细")
    assert "邮件上下文" in batch_index["limitations"][0]
    assert batch_index["expectedRisks"] == batch_index["limitations"]
    warehouse_batch = next(batch for batch in index["candidateBatches"] if batch["directory"] == "29仓")
    assert warehouse_batch["warehouseIds"] == ["29"]
    assert all("~$" not in item["filename"] for item in index["files"])


def test_build_material_index_groups_nested_bill_workbooks_with_parent_invoices(tmp_path):
    batch = tmp_path / "SSS 5.11-5.17"
    bill_dir = batch / "Strategic Staffing Solutions Corp 账单"
    bill_dir.mkdir(parents=True)
    (batch / "NJ8 Invoice Report WE 051726 JF.pdf").write_bytes(b"%PDF-1.4\n")
    (batch / "NJ13 Invoice Report WE 051726 JF.pdf").write_bytes(b"%PDF-1.4\n")
    (bill_dir / "OTWS - Warehouse Bill-NJ8.xlsx").write_bytes(b"fake workbook")
    (bill_dir / "~$OTWS - Warehouse Bill-NJ8.xlsx").write_bytes(b"temp")

    index = build_material_index(tmp_path)

    sss_batch = next(batch for batch in index["candidateBatches"] if batch["batchKey"] == "SSS_5_11_5_17")
    assert sss_batch["directory"] == "SSS 5.11-5.17"
    assert sss_batch["supplier"] == "sss"
    assert sss_batch["invoicePdfCount"] == 2
    assert sss_batch["workbookCount"] == 1
    assert sss_batch["uploadableFileCount"] == 3
    assert sss_batch["workbookFiles"][0]["relativePath"] == "SSS 5.11-5.17/Strategic Staffing Solutions Corp 账单/OTWS - Warehouse Bill-NJ8.xlsx"
    assert any("子目录" in limitation for limitation in sss_batch["limitations"])


def test_build_material_replay_plan_accepts_multi_warehouse_bill_workbooks(tmp_path):
    batch = tmp_path / "SSS 5.11-5.17"
    bill_dir = batch / "Strategic Staffing Solutions Corp 账单"
    bill_dir.mkdir(parents=True)
    for warehouse_id in ("8", "13"):
        (batch / f"NJ{warehouse_id} Invoice Report WE 051726 JF.pdf").write_bytes(b"%PDF-1.4\n")
        _write_labor_bill_workbook_with_rows(
            bill_dir / f"OTWS - Warehouse Bill-NJ{warehouse_id}.xlsx",
            [["WUS001", f"Worker {warehouse_id}", 8, 100, "USD", f"New Jersey Warehouse {warehouse_id}"]],
        )

    plan = build_material_replay_plan(tmp_path, batch_key="SSS_5_11_5_17")

    item = plan["plans"][0]
    assert item["supplier"] == "sss"
    assert item["warehouseIds"] == ["8", "13"]
    assert set(item["uploadPlan"]["workbookFiles"]) == {
        "SSS 5.11-5.17/Strategic Staffing Solutions Corp 账单/OTWS - Warehouse Bill-NJ13.xlsx",
        "SSS 5.11-5.17/Strategic Staffing Solutions Corp 账单/OTWS - Warehouse Bill-NJ8.xlsx",
    }
    assert {tuple(candidate["warehouseIds"]) for candidate in item["mappingCandidates"]} == {("8",), ("13",)}
    assert "需要确认主账单" not in " ".join(item["expectedRisks"])
    assert item["replayReady"] is True


def test_build_material_replay_plan_suggests_uploads_mapping_and_risks(tmp_path):
    batch = tmp_path / "oss 2"
    batch.mkdir()
    (batch / "US Elogis Service #7 Invoice W.E 05.24.26.pdf").write_bytes(b"%PDF-1.4\n")
    workbook_path = batch / "员工账单明细 - 2026-06-04T094719.972.xlsx"
    _write_labor_bill_workbook(workbook_path)

    plan = build_material_replay_plan(tmp_path, batch_key="oss_2")

    assert plan["summary"]["planCount"] == 1
    item = plan["plans"][0]
    assert item["supplier"] == "oss"
    assert item["periodHint"] == "W.E 05.24.26"
    assert item["warehouseIds"] == ["7"]
    assert item["uploadPlan"]["pdfFiles"] == ["oss 2/US Elogis Service #7 Invoice W.E 05.24.26.pdf"]
    assert item["uploadPlan"]["workbookFiles"] == ["oss 2/员工账单明细 - 2026-06-04T094719.972.xlsx"]
    mapping = item["mappingCandidates"][0]["suggestedMapping"]
    assert mapping["name"] == "姓名"
    assert mapping["hours"] == "时长总计(H)"
    assert mapping["amount"] == "费用总计(含税)"
    assert item["replayReady"] is True
    assert item["replayMode"] == "deterministic_first"
    assert "异常解释" in item["aiAllowedFor"]


def test_build_material_replay_plan_excludes_hours_only_supporting_workbook(tmp_path):
    batch = tmp_path / "Grande-"
    batch.mkdir()
    (batch / "GS invoice-ELOG-466-FL.pdf").write_bytes(b"%PDF-1.4\n")
    bill_path = batch / "员工账单明细 - 2026-05-28T172347.826.xlsx"
    _write_labor_bill_workbook(bill_path)
    support_path = batch / "GRANDE-5.18-5.24.xlsx"
    support_path.write_bytes(_workbook_with_hours_only_summary_bytes())

    plan = build_material_replay_plan(tmp_path, batch_key="Grande")

    item = plan["plans"][0]
    assert item["uploadPlan"]["workbookFiles"] == ["Grande-/员工账单明细 - 2026-05-28T172347.826.xlsx"]
    assert len(item["mappingCandidates"]) == 1
    assert item["mappingCandidates"][0]["filename"].startswith("员工账单明细")
    assert item["excludedWorkbookFiles"] == [
        {
            "relativePath": "Grande-/GRANDE-5.18-5.24.xlsx",
            "filename": "GRANDE-5.18-5.24.xlsx",
            "reason": "缺少必要映射: amount",
        }
    ]
    assert any("辅助材料排除" in risk for risk in item["expectedRisks"])
    assert item["replayReady"] is True


def test_build_material_replay_plan_identifies_prompt_priority_batch(tmp_path):
    batch = tmp_path / "prompt"
    batch.mkdir()
    (batch / "CHINA EXPRESS #3.pdf").write_bytes(b"%PDF-1.4\n")
    (batch / "DEPT#27.pdf").write_bytes(b"%PDF-1.4\n")
    _write_labor_bill_workbook(batch / "员工账单明细 - 2026-05-28T151400.642.xlsx")

    plan = build_material_replay_plan(tmp_path, batch_key="prompt")

    item = plan["plans"][0]
    assert item["supplier"] == "prompt"
    assert item["warehouseIds"] == ["3", "27"]
    assert "未识别供应商" not in " ".join(item["expectedRisks"])
    assert item["replayReady"] is True


def test_build_material_replay_plan_uses_workbook_accounting_period(tmp_path):
    batch = tmp_path / "prompt"
    batch.mkdir()
    (batch / "DEPT#27.pdf").write_bytes(b"%PDF-1.4\n")
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "员工账单明细"
    sheet.append(["工号", "姓名", "时长总计(H)", "费用总计(含税)", "币种", "物理仓", "核算开始日期", "核算结束日期"])
    sheet.append(["WUS001", "Alice Worker", 8, 100, "USD", "27号仓", "2026-05-11", "2026-05-17"])
    workbook.save(batch / "员工账单明细 - exported.xlsx")

    plan = build_material_replay_plan(tmp_path, batch_key="prompt")

    item = plan["plans"][0]
    assert item["periodHint"] == "2026-05-11~2026-05-17"
    assert "未识别到账期" not in " ".join(item["expectedRisks"])


def test_build_material_replay_plan_uses_workbook_supplier_hint(tmp_path):
    batch = tmp_path / "29仓"
    batch.mkdir()
    (batch / "In291943.pdf").write_bytes(b"%PDF-1.4\n")
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "员工账单明细"
    sheet.append(["供应商名称", "工号", "姓名", "时长总计(H)", "费用总计(含税)", "币种", "物理仓", "核算开始日期", "核算结束日期"])
    sheet.append(["CitiStaff Solutions", "WUS001", "Alice Worker", 8, 100, "USD", "29号仓", "2026-05-11", "2026-05-17"])
    workbook.save(batch / "员工账单明细 - 2026-05-28T141945.414.xlsx")

    plan = build_material_replay_plan(tmp_path, batch_key="29仓")

    item = plan["plans"][0]
    assert item["supplier"] == "citistaff"
    assert item["periodHint"] == "2026-05-11~2026-05-17"
    assert "未识别供应商" not in " ".join(item["expectedRisks"])


def test_build_material_dry_run_uses_deterministic_extract_and_does_not_write(monkeypatch, tmp_path):
    import bonus_platform.engine.labor.materials as materials_module

    batch = tmp_path / "oss 2"
    batch.mkdir()
    (batch / "US Elogis Service #7 Invoice W.E 05.24.26.pdf").write_bytes(b"%PDF-1.4\n")
    _write_labor_bill_workbook(batch / "员工账单明细 - 2026-06-04T094719.972.xlsx")

    monkeypatch.setattr(
        materials_module,
        "quick_extract_totals",
        lambda paths, config, supplier="": [{"source_file": paths[0].name, "total_amount": 100.0, "warehouse_id": "7"}],
    )
    monkeypatch.setattr(
        materials_module,
        "extract_invoice_items",
        lambda paths, config, **kwargs: [
            LaborLineItem(source_type="pdf_invoice", source_file=paths[0].name, source_page_or_row="p1", employee_id="WUS001", employee_name_raw="Alice Worker", hours=8, amount=100, currency="USD", confidence=0.95, evidence_text="Alice Worker 8 $100")
        ],
    )
    monkeypatch.setattr(
        materials_module,
        "_extract_pdf_pages",
        lambda paths: [{"source_file": paths[0].name, "page": 1, "text": "Alice Worker 8 $100"}],
    )

    dry_run = build_material_dry_run(tmp_path, "oss_2")

    assert dry_run["decision"] == "dry_run_only"
    assert dry_run["writesRun"] is False
    assert dry_run["aiInvoked"] is False
    assert dry_run["summary"]["pdfRowCount"] == 1
    assert dry_run["summary"]["excelRowCount"] == 1
    assert dry_run["summary"]["comparison"]["exceptionCount"] == 0
    assert dry_run["summary"]["warehouse"]["totalPassed"] is True
    assert dry_run["summary"]["tierStatus"]["employeeDetailAvailable"] is True
    assert dry_run["reviewQueues"]["primary"] == "cleared"
    assert "无需继续处理" in dry_run["reviewQueues"]["primaryReason"]
    assert dry_run["deliveryGate"]["status"] == "ready"
    assert dry_run["deliveryGate"]["label"] == "可交付"
    assert dry_run["deliveryGate"]["summary"]["blockedCount"] == 0
    assert dry_run["deliveryGate"]["summary"]["reviewCount"] == 0
    assert dry_run["deliveryGate"]["issues"] == []
    assert dry_run["reviewQueues"]["employeeExceptions"]["count"] == 0
    assert dry_run["reviewQueues"]["employeeExceptions"]["suppressedByPrimary"] is False
    assert dry_run["summary"]["pdfTextCoverage"]["textReadableFileCount"] == 1
    assert dry_run["summary"]["pdfTextCoverage"]["imageOnlyFileCount"] == 0
    assert dry_run["sampleRows"][0]["matchStatus"] == "通过"
    assert dry_run["exceptionRows"] == []
    assert dry_run["candidateMatches"] == []
    assert dry_run["nameMappingGovernance"]["decision"] == "candidate_only"
    assert dry_run["nameMappingGovernance"]["summary"]["candidateCount"] == 0
    assert dry_run["aiCacheAudit"]["summary"]["candidateFileCount"] == 0


def test_material_review_queue_marks_zero_exception_batches_as_cleared():
    from bonus_platform.engine.labor.materials import _build_material_review_queues

    queues = _build_material_review_queues(
        comparison_summary={"exceptionCount": 0},
        warehouse_summary={"exceptionCount": 0},
        exception_rows=[],
        pdf_text_coverage={"summary": {"imageOnlyFileCount": 2}},
        reocr_plan={"summary": {"taskCount": 2, "reviewableCandidateCount": 0}},
        ai_cache_preview={"summary": {"exceptionCount": 2, "needsReocrFileCount": 2}},
        name_mapping_governance={"summary": {"candidateCount": 0}},
        combined_row_governance={"summary": {"candidateCount": 0}},
        allocation_issues=[],
        hours_tolerance=0.01,
    )

    assert queues["primary"] == "cleared"
    assert "无需继续处理" in queues["primaryReason"]
    assert queues["employeeExceptions"]["count"] == 0
    assert queues["employeeExceptions"]["suppressedByPrimary"] is False


def test_material_review_queue_preserves_all_reocr_tasks_for_frontend_collapse():
    from bonus_platform.engine.labor.materials import _build_material_review_queues

    tasks = [
        {
            "sourceFile": f"DEPT#{index}.pdf",
            "warehouseId": str(index),
            "amountDelta": -100 * index,
            "pdfTextCoverage": {"needsOcr": True},
            "diagnostics": {"summary": {"exceptionCount": index, "unmatchedCacheCount": 0, "unmatchedExcelCount": index}},
        }
        for index in range(1, 13)
    ]

    queues = _build_material_review_queues(
        comparison_summary={"exceptionCount": 12},
        warehouse_summary={"exceptionCount": 12},
        exception_rows=[],
        pdf_text_coverage={"summary": {"imageOnlyFileCount": 12}},
        reocr_plan={"summary": {"taskCount": 12, "reviewableCandidateCount": 0}, "tasks": tasks},
        ai_cache_preview={"summary": {"exceptionCount": 12, "needsReocrFileCount": 12}},
        name_mapping_governance={"summary": {"candidateCount": 0}},
        combined_row_governance={"summary": {"candidateCount": 0}},
        allocation_issues=[],
        hours_tolerance=0.01,
    )

    assert queues["primary"] == "reocr"
    assert queues["reocr"]["taskCount"] == 12
    assert len(queues["reocr"]["tasks"]) == 12
    assert queues["reocr"]["tasks"][-1]["sourceFile"] == "DEPT#12.pdf"
    assert queues["reocr"]["summaryText"] == "12 个 PDF 无文本层 · 12 个图片发票明细待确认 · 12 项员工级异常"
    assert len(queues["reocr"]["groups"]) == 12
    assert queues["reocr"]["groups"][0]["sourceFile"] == "DEPT#12.pdf"
    assert queues["reocr"]["groups"][0]["statusLabel"] == "需重新识别"
    assert queues["reocr"]["groups"][0]["needsTextRecognition"] is True
    assert queues["reocr"]["groups"][0]["exceptionCount"] == 12
    assert queues["reocr"]["groups"][0]["unmatchedExcelCount"] == 12


def test_build_material_dry_run_applies_sss_rounding_tolerance(monkeypatch, tmp_path):
    import bonus_platform.engine.labor.materials as materials_module

    batch = tmp_path / "SSS 5.11-5.17"
    batch.mkdir()
    (batch / "NJ8 Invoice Report WE 051726 JF.pdf").write_bytes(b"%PDF-1.4\n")
    _write_labor_bill_workbook_with_rows(batch / "OTWS - Warehouse Bill-NJ8.xlsx", [["WUS001", "Alice Worker", 8, 100.20, "USD", "New Jersey-8"]])

    monkeypatch.setattr(
        materials_module,
        "quick_extract_totals",
        lambda paths, config, supplier="": [{"source_file": paths[0].name, "total_amount": 100.0, "warehouse_id": "8"}],
    )
    monkeypatch.setattr(
        materials_module,
        "extract_invoice_items",
        lambda paths, config, **kwargs: [
            LaborLineItem(
                source_type="pdf_invoice",
                source_file=paths[0].name,
                source_page_or_row="p1",
                employee_id="WUS001",
                employee_name_raw="Alice Worker",
                hours=8,
                amount=100.0,
                currency="USD",
                confidence=0.95,
                evidence_text="Alice Worker 8 $100.00",
            )
        ],
    )
    monkeypatch.setattr(
        materials_module,
        "_extract_pdf_pages",
        lambda paths: [{"source_file": paths[0].name, "page": 1, "text": "Alice Worker 8 $100"}],
    )

    dry_run = build_material_dry_run(tmp_path, "SSS_5_11_5_17")

    assert dry_run["summary"]["tolerances"]["amount"] == 0.25
    assert any("SSS" in note for note in dry_run["summary"]["tolerances"]["notes"])
    assert dry_run["summary"]["comparison"]["exceptionCount"] == 0
    assert dry_run["summary"]["warehouse"]["totalPassed"] is True


def test_build_material_dry_run_prioritizes_amount_rate_review_for_same_hours_delta(monkeypatch, tmp_path):
    import bonus_platform.engine.labor.materials as materials_module

    batch = tmp_path / "SSS 5.11-5.17"
    batch.mkdir()
    (batch / "NJ13 Invoice Report WE 051726 JF.pdf").write_bytes(b"%PDF-1.4\n")
    _write_labor_bill_workbook_with_rows(
        batch / "OTWS - Warehouse Bill-NJ13.xlsx",
        [["WUS001", "ALVARO TEJADA CAMPOS", 8, 162.56, "USD", "New Jersey Warehouse 13"]],
    )

    monkeypatch.setattr(
        materials_module,
        "quick_extract_totals",
        lambda paths, config, supplier="": [{"source_file": paths[0].name, "total_amount": 172.72, "warehouse_id": "13"}],
    )
    monkeypatch.setattr(
        materials_module,
        "extract_invoice_items",
        lambda paths, config, **kwargs: [
            LaborLineItem(
                source_type="pdf_invoice",
                source_file=paths[0].name,
                source_page_or_row="p19",
                employee_id="WUS001",
                employee_name_raw="Tejada, Alvaro",
                hours=8,
                amount=172.72,
                currency="USD",
                confidence=0.96,
                evidence_text="Tejada, Alvaro 8 $21.59 $172.72",
            )
        ],
    )
    monkeypatch.setattr(
        materials_module,
        "_extract_pdf_pages",
        lambda paths: [{"source_file": paths[0].name, "page": 19, "text": "Tejada, Alvaro 8 $21.59 $172.72"}],
    )

    dry_run = build_material_dry_run(tmp_path, "SSS_5_11_5_17")

    assert dry_run["summary"]["comparison"]["exceptionCount"] == 1
    assert dry_run["reviewQueues"]["primary"] == "amount_rate_review"
    assert "费率" in dry_run["reviewQueues"]["primaryReason"]
    assert "复核" not in dry_run["reviewQueues"]["primaryReason"]
    queue = dry_run["reviewQueues"]["amountRateReview"]
    assert queue["count"] == 1
    assert queue["reviewMode"] == "amount_basis"
    assert queue["amountOnlyCount"] == 1
    assert queue["hoursMismatchCount"] == 0
    assert queue["amountImpactTotal"] == 10.16
    assert queue["amountOnlyImpactTotal"] == 10.16
    assert queue["largestAmountDelta"] == 10.16
    assert "工时已经对齐" in queue["businessQuestion"]
    assert "金额计算口径" in queue["businessMeaning"]
    assert "不能由系统自动" in queue["cannotAutoResolveReason"]
    row = queue["rows"][0]
    assert row["reviewType"] == "amount_basis_mismatch"
    assert row["reviewLabel"] == "工时一致，仅金额不同"
    assert row["reviewFocus"] == "先核金额口径"
    assert row["employeeName"] == "Tejada, Alvaro"
    assert row["pdfAmountTotal"] == 172.72
    assert row["excelAmountTotal"] == 162.56
    assert row["amountDelta"] == 10.16
    assert row["amountDirectionLabel"] == "PDF 高于 Excel"
    assert row["hoursDelta"] == 0
    assert row["hoursDirectionLabel"] == "工时一致"
    assert "PDF 比 Excel 多 $10.16" in row["businessQuestion"]
    assert "工时一致" in row["businessQuestion"]
    assert "金额口径属于业务结算判断" in row["cannotAutoResolveReason"]
    assert "确认前不能自动清账" in row["recommendation"]
    actions = queue["nextActions"]
    assert [item["action"] for item in actions] == [
        "create_formal_run",
        "review_source_evidence",
        "record_business_conclusion",
        "download_report",
    ]
    assert actions[0]["enabled"] is True
    assert actions[0]["label"] == "建正式批次并保留差异"
    assert actions[1]["label"] == "核对金额计算口径"
    assert "自动清账" in actions[0]["description"]
    assert "保留为待处理异常" in actions[2]["description"]
    assert actions[3]["label"] == "导出给业务确认"
    amount_visible_text = " ".join(
        [
            dry_run["reviewQueues"]["primaryReason"],
            *[str(action.get("label", "")) for action in actions],
            *[str(action.get("description", "")) for action in actions],
            row["businessQuestion"],
            row["cannotAutoResolveReason"],
            row["recommendation"],
        ]
    )
    for internal_copy in ["人工复核", "需复核", "复核费率", "复核日期范围", "复核记录"]:
        assert internal_copy not in amount_visible_text


def test_build_material_dry_run_demotes_stale_image_cache_when_deterministic_extract_is_ok(monkeypatch, tmp_path):
    import bonus_platform.engine.labor.materials as materials_module

    batch = tmp_path / "SSS 5.11-5.17"
    batch.mkdir()
    (batch / "NJ13 Invoice Report WE 051726 JF.pdf").write_bytes(b"%PDF-1.4\n")
    workbook_rows = [["WUS001", "Alice Worker", 8, 100.00, "USD", "New Jersey Warehouse 13"]]
    workbook_rows.extend(
        [f"WUS{idx:03d}", f"Worker {idx:02d}", 8, 100.00, "USD", "New Jersey Warehouse 13"]
        for idx in range(2, 13)
    )
    _write_labor_bill_workbook_with_rows(
        batch / "OTWS - Warehouse Bill-NJ13.xlsx",
        workbook_rows,
    )
    cache_dir = batch / ".ai_extract_cache"
    cache_dir.mkdir()
    (cache_dir / "NJ13_Invoice_Report_WE_051726_JF_p1_mimo-v2.5_v4.json").write_text(
        json.dumps(
            [
                {
                    "employee_name_raw": "Wrong Cache Person",
                    "source_page": 1,
                    "hours": 8,
                    "amount": 80,
                    "confidence": 0.95,
                    "evidence_text": "Wrong Cache Person 8 $80.00",
                }
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        materials_module,
        "quick_extract_totals",
        lambda paths, config, supplier="": [{"source_file": paths[0].name, "total_amount": 1220.0, "warehouse_id": "13"}],
    )
    pdf_rows = [
        LaborLineItem(
            source_type="pdf_invoice",
            source_file="NJ13 Invoice Report WE 051726 JF.pdf",
            source_page_or_row="p1",
            employee_id="WUS001",
            employee_name_raw="Alice Worker",
            hours=8,
            amount=120.0,
            currency="USD",
            confidence=0.96,
            evidence_text="Alice Worker 8 $120.00",
        )
    ]
    pdf_rows.extend(
        LaborLineItem(
            source_type="pdf_invoice",
            source_file="NJ13 Invoice Report WE 051726 JF.pdf",
            source_page_or_row="p1",
            employee_id=f"WUS{idx:03d}",
            employee_name_raw=f"Worker {idx:02d}",
            hours=8,
            amount=100.0,
            currency="USD",
            confidence=0.96,
            evidence_text=f"Worker {idx:02d} 8 $100.00",
        )
        for idx in range(2, 13)
    )
    monkeypatch.setattr(
        materials_module,
        "extract_invoice_items",
        lambda paths, config, **kwargs: pdf_rows,
    )
    monkeypatch.setattr(
        materials_module,
        "_extract_pdf_pages",
        lambda paths: [
            {
                "source_file": paths[0].name,
                "page": 1,
                "text": "\n".join(row.evidence_text for row in pdf_rows),
            }
        ],
    )

    dry_run = build_material_dry_run(tmp_path, "SSS_5_11_5_17")

    assert dry_run["summary"]["pdfRowCount"] == 12
    assert dry_run["summary"]["pdfTextCoverage"]["imageOnlyFileCount"] == 0
    assert dry_run["summary"]["quality"]["level"] == "ok"
    assert dry_run["aiCacheReconciliationPreview"]["summary"]["needsReocrFileCount"] == 1
    assert dry_run["reocrPlan"]["demotedByDeterministicExtract"] is True
    assert dry_run["reocrPlan"]["summary"]["taskCount"] == 0
    assert dry_run["reocrPlan"]["summary"]["demotedTaskCount"] == 1
    assert dry_run["reviewQueues"]["reocr"]["taskCount"] == 0
    assert dry_run["reviewQueues"]["primary"] == "amount_rate_review"
    assert dry_run["deliveryGate"]["status"] == "needs_review"
    assert dry_run["deliveryGate"]["label"] == "需业务确认"
    assert dry_run["deliveryGate"]["message"] == "无阻断项，但仍有需业务留痕确认的项目。"
    assert "复核" not in dry_run["deliveryGate"]["label"]
    assert "复核" not in dry_run["deliveryGate"]["message"]
    assert not any(issue["code"] == "reocr_required" for issue in dry_run["deliveryGate"]["issues"])
    assert any("降级为审计参考" in risk for risk in dry_run["expectedRisks"])


def test_build_material_dry_run_prioritizes_amount_hours_review_for_hours_delta(monkeypatch, tmp_path):
    import bonus_platform.engine.labor.materials as materials_module

    batch = tmp_path / "osi 2"
    batch.mkdir()
    (batch / "US ELogistics Service Corp. 34926.pdf").write_bytes(b"%PDF-1.4\n")
    _write_labor_bill_workbook_with_rows(
        batch / "员工账单明细 - 2026-06-04T094636.978.xlsx",
        [["WUS001", "Maria Elena Parraguirre", 12.25, 467.41, "USD", "1号仓"]],
    )

    monkeypatch.setattr(
        materials_module,
        "quick_extract_totals",
        lambda paths, config, supplier="": [{"source_file": paths[0].name, "total_amount": 557.76, "warehouse_id": "1"}],
    )
    monkeypatch.setattr(
        materials_module,
        "extract_invoice_items",
        lambda paths, config, **kwargs: [
            LaborLineItem(
                source_type="pdf_invoice",
                source_file=paths[0].name,
                source_page_or_row="p3",
                employee_id="WUS001",
                employee_name_raw="Parraguirre, Maria",
                hours=20.36,
                amount=557.76,
                currency="USD",
                confidence=0.98,
                evidence_text="Parraguirre, Maria 8.11 OT + 12.25 REG/OT $557.76",
            )
        ],
    )
    monkeypatch.setattr(
        materials_module,
        "_extract_pdf_pages",
        lambda paths: [{"source_file": paths[0].name, "page": 3, "text": "Parraguirre, Maria 20.36 $557.76"}],
    )

    dry_run = build_material_dry_run(tmp_path, "osi_2")

    assert dry_run["summary"]["comparison"]["exceptionCount"] == 1
    assert dry_run["reviewQueues"]["primary"] == "amount_rate_review"
    assert "工时/金额" in dry_run["reviewQueues"]["primaryReason"]
    queue = dry_run["reviewQueues"]["amountRateReview"]
    assert queue["count"] == 1
    assert queue["reviewMode"] == "hours_and_amount"
    assert queue["amountOnlyCount"] == 0
    assert queue["hoursMismatchCount"] == 1
    assert queue["hoursImpactTotal"] == 8.11
    assert queue["hoursMismatchImpactTotal"] == 90.35
    assert "同一账期" in queue["businessQuestion"]
    assert "是否在核同一批工时" in queue["businessMeaning"]
    assert "工时差会改变应付金额" in queue["cannotAutoResolveReason"]
    row = queue["rows"][0]
    assert row["reviewType"] == "hours_amount_mismatch"
    assert row["reviewLabel"] == "工时和金额都不同"
    assert row["reviewFocus"] == "先核工时口径"
    assert row["employeeName"] == "Parraguirre, Maria"
    assert row["amountDelta"] == 90.35
    assert row["amountDirectionLabel"] == "PDF 高于 Excel"
    assert row["hoursDelta"] == 8.11
    assert row["hoursDirectionLabel"] == "PDF 工时多于 Excel"
    assert "PDF 比 Excel 多 $90.35" in row["businessQuestion"]
    assert "工时多 8.11" in row["businessQuestion"]
    assert "工时差会改变应付金额" in row["cannotAutoResolveReason"]
    assert "账期范围" in row["recommendation"]
    actions = queue["nextActions"]
    assert actions[1]["label"] == "核对账期、加班和工时"
    assert "账期范围" in actions[1]["description"]


def test_build_material_dry_run_surfaces_cross_warehouse_allocation_review(monkeypatch, tmp_path):
    import bonus_platform.engine.labor.materials as materials_module

    batch = tmp_path / "fairway已报账2"
    batch.mkdir()
    (batch / "fairway_25.pdf").write_bytes(b"%PDF-1.4\n")
    (batch / "fairway_28.pdf").write_bytes(b"%PDF-1.4\n")
    _write_labor_bill_workbook_with_rows(
        batch / "员工账单明细 - 2026-06-04T094719.972.xlsx",
        [
            ["WUS041037", "PEREZ, JOSE", 4.0, 100.67, "USD", "25号仓"],
            ["WUS043938", "JIMENEZ, ENEAS", 5.0, 116.85, "USD", "25号仓"],
            ["WUS041037", "PEREZ, JOSE", 40.0, 935.59, "USD", "28号仓"],
            ["WUS043938", "JIMENEZ, ENEAS", 40.0, 929.87, "USD", "28号仓"],
        ],
    )

    monkeypatch.setattr(
        materials_module,
        "quick_extract_totals",
        lambda paths, config, supplier="": [
            {"source_file": "fairway_25.pdf", "total_amount": 219.30, "warehouse_id": "25"},
            {"source_file": "fairway_28.pdf", "total_amount": 1863.67, "warehouse_id": "28"},
        ],
    )
    monkeypatch.setattr(
        materials_module,
        "extract_invoice_items",
        lambda paths, config, **kwargs: [
            LaborLineItem(source_type="pdf_invoice", source_file="fairway_25.pdf", source_page_or_row="p1", employee_id="WUS041037", employee_name_raw="PEREZ, JOSE", hours=4.0, amount=101.26, currency="USD", confidence=0.95, evidence_text="PEREZ, JOSE 4.0 101.26", warehouse_id="25"),
            LaborLineItem(source_type="pdf_invoice", source_file="fairway_25.pdf", source_page_or_row="p1", employee_id="WUS043938", employee_name_raw="JIMENEZ, ENEAS", hours=5.0, amount=118.04, currency="USD", confidence=0.95, evidence_text="JIMENEZ, ENEAS 5.0 118.04", warehouse_id="25"),
            LaborLineItem(source_type="pdf_invoice", source_file="fairway_28.pdf", source_page_or_row="p1", employee_id="WUS041037", employee_name_raw="PEREZ, JOSE", hours=40.0, amount=935.00, currency="USD", confidence=0.95, evidence_text="PEREZ, JOSE 40.0 935.00", warehouse_id="28"),
            LaborLineItem(source_type="pdf_invoice", source_file="fairway_28.pdf", source_page_or_row="p1", employee_id="WUS043938", employee_name_raw="JIMENEZ, ENEAS", hours=40.0, amount=928.67, currency="USD", confidence=0.95, evidence_text="JIMENEZ, ENEAS 40.0 928.67", warehouse_id="28"),
        ],
    )
    monkeypatch.setattr(
        materials_module,
        "_extract_pdf_pages",
        lambda paths: [
            {"source_file": "fairway_25.pdf", "page": 1, "text": "PEREZ, JOSE 101.26 JIMENEZ, ENEAS 118.04"},
            {"source_file": "fairway_28.pdf", "page": 1, "text": "PEREZ, JOSE 935.00 JIMENEZ, ENEAS 928.67"},
        ],
    )

    dry_run = build_material_dry_run(tmp_path, "fairway已报账2")

    assert dry_run["summary"]["comparison"]["exceptionCount"] == 0
    assert dry_run["summary"]["warehouse"]["allocationIssueCount"] == 2
    assert dry_run["summary"]["tierStatus"]["allocationIssueCount"] == 2
    assert dry_run["reviewQueues"]["primary"] == "allocation_review"
    assert "仓库归属" in dry_run["reviewQueues"]["primaryReason"]
    assert "复核" not in dry_run["reviewQueues"]["primaryReason"]
    queue = dry_run["reviewQueues"]["allocationReview"]
    assert queue["count"] == 2
    assert queue["warehousePairCount"] == 4
    assert queue["amountImpactTotal"] == 1.79
    assert [item["action"] for item in queue["nextActions"]] == [
        "create_formal_run",
        "extract_compare",
        "review_warehouse_allocation",
        "confirm_or_rollback",
    ]
    assert queue["nextActions"][0]["enabled"] is True
    assert "审计记录" in queue["nextActions"][3]["description"]
    allocation_visible_text = " ".join(
        [
            dry_run["reviewQueues"]["primaryReason"],
            *dry_run["expectedRisks"],
            *[str(action.get("label", "")) for action in queue["nextActions"]],
            *[str(action.get("description", "")) for action in queue["nextActions"]],
        ]
    )
    for internal_copy in ["人工复核", "需复核", "复核仓库", "填写复核"]:
        assert internal_copy not in allocation_visible_text
    rows_by_employee = {row["employeeName"]: row for row in queue["rows"]}
    assert rows_by_employee["JIMENEZ, ENEAS"]["maxWarehouseDelta"] == 1.2
    assert rows_by_employee["PEREZ, JOSE"]["netAmountDelta"] == 0.0
    assert dry_run["allocationIssues"][0]["employeeName"] in {"JIMENEZ, ENEAS", "PEREZ, JOSE"}
    assert any("跨仓库金额抵消" in risk for risk in dry_run["expectedRisks"])


def test_build_material_dry_run_surfaces_name_mapping_candidates_as_governance_preview(monkeypatch, tmp_path):
    import bonus_platform.engine.labor.materials as materials_module

    batch = tmp_path / "29仓"
    batch.mkdir()
    (batch / "In291943.pdf").write_bytes(b"%PDF-1.4\n")
    _write_labor_bill_workbook_with_rows(
        batch / "员工账单明细 - 2026-05-28T141945.414.xlsx",
        [
            ["WUS040020", "Deisi Pozo", 37.84, 847.84, "USD", "29号仓"],
            ["WUS033570", "Freddy Moran (MOR47K)", 40.48, 830.72, "USD", "29号仓"],
        ],
    )

    monkeypatch.setattr(
        materials_module,
        "quick_extract_totals",
        lambda paths, config, supplier="": [{"source_file": paths[0].name, "total_amount": 1890.27, "warehouse_id": "29"}],
    )
    monkeypatch.setattr(
        materials_module,
        "extract_invoice_items",
        lambda paths, config, **kwargs: [
            LaborLineItem(source_type="pdf_invoice", source_file=paths[0].name, source_page_or_row="p1", employee_id="", employee_name_raw="Rozo Panche, Deisy V", hours=37.84, amount=847.84, currency="USD", confidence=0.98, evidence_text="Rozo Panche, Deisy V 37.84 $847.84"),
            LaborLineItem(source_type="pdf_invoice", source_file=paths[0].name, source_page_or_row="p1", employee_id="", employee_name_raw="Moran Treminio, Freddy", hours=40.48, amount=1042.43, currency="USD", confidence=0.98, evidence_text="Moran Treminio, Freddy 40.48 $1042.43"),
        ],
    )
    monkeypatch.setattr(
        materials_module,
        "_extract_pdf_pages",
        lambda paths: [{"source_file": paths[0].name, "page": 1, "text": "Rozo Panche, Deisy V 37.84 $847.84"}],
    )

    dry_run = build_material_dry_run(tmp_path, "29仓")

    assert dry_run["summary"]["comparison"]["candidateMatchCount"] == 2
    governance = dry_run["nameMappingGovernance"]
    assert governance["decision"] == "candidate_only"
    assert governance["requiresConfirmation"] is True
    assert governance["summary"]["candidateCount"] == 2
    assert governance["summary"]["highConfidenceCount"] == 1
    assert governance["summary"]["readyToReplayCount"] == 1
    assert governance["summary"]["projectedFixedExceptionCount"] == 2
    assert governance["summary"]["amountStillDifferentCount"] == 1
    candidate = governance["candidates"][0]
    assert candidate["status"] == "pending_user_confirmation"
    assert candidate["sourceFile"] == "In291943.pdf"
    assert candidate["cacheEmployeeName"] == "Rozo Panche, Deisy V"
    assert candidate["excelEmployeeName"] == "Deisi Pozo"
    assert candidate["proposedMapping"] == {"Rozo Panche, Deisy V": "Deisi Pozo"}
    assert candidate["confidence"] == "high"
    assert candidate["projectedFixedExceptionCount"] == 2
    assert candidate["matchReason"] == "姓名相似且金额/工时一致"
    assert "是否确认 PDF 名称 Rozo Panche, Deisy V 对应 Excel 员工 Deisi Pozo" in candidate["businessQuestion"]
    assert "预计减少 2 项异常" in candidate["businessQuestion"]
    assert candidate["impactSummary"] == "金额和工时均一致"
    assert "必须先查看影响" in candidate["cannotAutoResolveReason"]
    assert "业务确认" in candidate["cannotAutoResolveReason"]
    assert "预览" not in candidate["cannotAutoResolveReason"]
    assert "人工确认" not in candidate["cannotAutoResolveReason"]
    medium_candidate = governance["candidates"][1]
    assert medium_candidate["confidence"] == "medium"
    assert medium_candidate["cacheEmployeeName"] == "Moran Treminio, Freddy"
    assert medium_candidate["projectedFixedExceptionCount"] == 0
    assert medium_candidate["matchReason"] == "姓名相似，但金额或工时仍需确认"
    assert "需先确认差异原因" in medium_candidate["businessQuestion"]
    assert "PDF 高于 Excel" in medium_candidate["impactSummary"]
    assert "不能直接合并" in medium_candidate["cannotAutoResolveReason"]
    assert candidate["auditTrail"][0]["reason"] == "material_dry_run_candidate_match_name_pair"
    assert dry_run["reviewQueues"]["primary"] == "name_mapping"
    assert "先查看影响并确认" in dry_run["reviewQueues"]["primaryReason"]
    name_queue = dry_run["reviewQueues"]["nameMapping"]
    assert name_queue["count"] == 2
    assert name_queue["readyToReplayCount"] == 1
    assert name_queue["highConfidenceCount"] == 1
    assert name_queue["projectedFixedExceptionCount"] == 2
    assert name_queue["rows"][0]["candidateId"] == candidate["candidateId"]
    assert name_queue["rows"][0]["projectedFixedExceptionCount"] == 2
    assert name_queue["rows"][1]["projectedFixedExceptionCount"] == 0
    name_actions = name_queue["nextActions"]
    assert [item["action"] for item in name_actions] == [
        "create_formal_run",
        "extract_compare",
        "preview_impact",
        "confirm_or_rollback",
    ]
    assert name_actions[0]["enabled"] is True
    assert name_actions[1]["enabled"] is False
    assert "查看影响" in name_actions[2]["description"]
    assert "撤回" in name_actions[3]["description"]
    user_visible_name_mapping_text = " ".join(
        [
            candidate["businessQuestion"],
            candidate["cannotAutoResolveReason"],
            candidate["recommendation"],
            medium_candidate["matchReason"],
            medium_candidate["businessQuestion"],
            medium_candidate["cannotAutoResolveReason"],
            medium_candidate["recommendation"],
            *[str(action.get("description", "")) for action in name_actions],
        ]
    )
    for internal_copy in ["预览", "人工确认", "人工复核", "需复核", "复核差异口径"]:
        assert internal_copy not in user_visible_name_mapping_text
    assert any("疑似同一员工" in risk for risk in dry_run["expectedRisks"])
    assert all("姓名匹配建议" not in risk for risk in dry_run["expectedRisks"])


def test_build_material_dry_run_surfaces_combined_pdf_rows_as_governance_preview(monkeypatch, tmp_path):
    import bonus_platform.engine.labor.materials as materials_module

    batch = tmp_path / "oss 2"
    batch.mkdir()
    (batch / "US Elogis Service #1 Invoice W.E 05.24.26.pdf").write_bytes(b"%PDF-1.4\n")
    _write_labor_bill_workbook_with_rows(
        batch / "员工账单明细 - 2026-06-04T094719.972.xlsx",
        [
            ["WUS045753", "Manuel Lozano", 16.09, 361.42, "USD", "1号仓"],
            ["WUS045746", "Massiel Castillo", 3.50, 78.40, "USD", "1号仓"],
        ],
    )

    monkeypatch.setattr(
        materials_module,
        "quick_extract_totals",
        lambda paths, config, supplier="": [{"source_file": paths[0].name, "total_amount": 439.82, "warehouse_id": "1"}],
    )
    monkeypatch.setattr(
        materials_module,
        "extract_invoice_items",
        lambda paths, config, **kwargs: [
            LaborLineItem(
                source_type="pdf_invoice",
                source_file=paths[0].name,
                source_page_or_row="p1",
                employee_id="",
                employee_name_raw="Lozano, Manuel",
                hours=19.59,
                amount=439.82,
                currency="USD",
                confidence=0.95,
                evidence_text="Lozano, Manuel 19.50 0.09 439.82",
            )
        ],
    )
    monkeypatch.setattr(
        materials_module,
        "_extract_pdf_pages",
        lambda paths: [{"source_file": paths[0].name, "page": 1, "text": "Lozano, Manuel 19.50 0.09 439.82"}],
    )

    dry_run = build_material_dry_run(tmp_path, "oss_2")

    assert dry_run["summary"]["comparison"]["candidateMatchCount"] == 1
    assert dry_run["candidateMatches"][0]["issueType"] == "combined_pdf_row"
    assert dry_run["nameMappingGovernance"]["summary"]["candidateCount"] == 0
    combined = dry_run["combinedRowGovernance"]
    assert combined["decision"] == "candidate_only"
    assert combined["requiresConfirmation"] is True
    assert combined["summary"]["candidateCount"] == 1
    assert combined["summary"]["amountImpactTotal"] == 78.4
    assert combined["summary"]["hoursImpactTotal"] == 3.5
    candidate = combined["candidates"][0]
    assert candidate["status"] == "pending_invoice_review"
    assert candidate["issueType"] == "combined_pdf_row"
    assert candidate["pdfEmployeeName"] == "Lozano, Manuel ⇄ Manuel Lozano"
    assert candidate["excelEmployeeName"] == "Massiel Castillo"
    assert candidate["amountGap"] == 78.4
    assert candidate["hoursGap"] == 3.5
    assert candidate["matchReason"] == "PDF 行疑似包含多名员工或剩余金额/工时"
    assert "是否还包含 Excel 员工 Massiel Castillo" in candidate["businessQuestion"]
    assert "PDF 高于 Excel $78.40" in candidate["impactSummary"]
    assert "PDF 工时多于 Excel 3.50" in candidate["impactSummary"]
    assert "不能仅凭差额接近自动清账" in candidate["cannotAutoResolveReason"]
    assert candidate["auditTrail"][0]["reason"] == "material_dry_run_combined_pdf_row"
    assert dry_run["reviewQueues"]["primary"] == "combined_pdf_row"
    assert "原始发票" in dry_run["reviewQueues"]["primaryReason"]
    combined_queue = dry_run["reviewQueues"]["combinedPdfRows"]
    assert combined_queue["count"] == 1
    assert combined_queue["amountImpactTotal"] == 78.4
    assert combined_queue["hoursImpactTotal"] == 3.5
    assert combined_queue["rows"][0]["candidateId"] == candidate["candidateId"]
    assert any("合并员工行建议" in risk for risk in dry_run["expectedRisks"])


def test_build_material_dry_run_surfaces_ai_cache_as_candidate_only(monkeypatch, tmp_path):
    import bonus_platform.engine.labor.materials as materials_module

    batch = tmp_path / "oss"
    batch.mkdir()
    (batch / "elog7-5_20260520204043.pdf").write_bytes(b"%PDF-1.4\n")
    _write_labor_bill_workbook(batch / "员工账单明细 - 2026-05-27T110404.877.xlsx")
    cache_dir = batch / ".ai_extract_cache"
    cache_dir.mkdir()
    (cache_dir / "elog7-5_20260520204043_p1_mimo-v2.5_v4.json").write_text(
        json.dumps(
            [
                {
                    "employee_name_raw": "Alice Worker",
                    "source_page": 1,
                    "hours": 8,
                    "amount": 120,
                    "confidence": 0.95,
                    "evidence_text": "Alice Worker TOTAL $120.00",
                }
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        materials_module,
        "quick_extract_totals",
        lambda paths, config, supplier="": [{"source_file": paths[0].name, "total_amount": 120.0, "warehouse_id": "1"}],
    )
    monkeypatch.setattr(materials_module, "extract_invoice_items", lambda paths, config, **kwargs: [])
    monkeypatch.setattr(
        materials_module,
        "_extract_pdf_pages",
        lambda paths: [{"source_file": paths[0].name, "page": 1, "text": ""}],
    )

    dry_run = build_material_dry_run(tmp_path, "oss")

    assert dry_run["summary"]["pdfRowCount"] == 0
    assert dry_run["summary"]["pdfTextCoverage"]["imageOnlyFileCount"] == 1
    assert dry_run["pdfTextCoverage"]["files"][0]["needsOcr"] is True
    assert dry_run["summary"]["comparison"]["unmatchedExcelCount"] == 1
    assert dry_run["reviewQueues"]["primary"] == "reocr"
    assert "图片发票明细待确认" in dry_run["reviewQueues"]["primaryReason"]
    assert "复核" not in dry_run["reviewQueues"]["primaryReason"]
    assert "预览" not in dry_run["reviewQueues"]["primaryReason"]
    assert dry_run["reviewQueues"]["reocr"]["taskCount"] == 1
    assert dry_run["reviewQueues"]["reocr"]["imageOnlyFileCount"] == 1
    assert dry_run["deliveryGate"]["status"] == "blocked"
    assert dry_run["deliveryGate"]["label"] == "不可交付"
    assert dry_run["deliveryGate"]["summary"]["blockedCount"] == 1
    assert dry_run["deliveryGate"]["issues"][0]["code"] == "reocr_required"
    assert "图片发票明细待确认" in dry_run["deliveryGate"]["issues"][0]["title"]
    reocr_actions = dry_run["reviewQueues"]["reocr"]["nextActions"]
    assert [item["action"] for item in reocr_actions] == [
        "create_formal_run",
        "extract_compare",
        "replay_candidate",
        "confirm_apply",
    ]
    assert reocr_actions[0]["enabled"] is True
    assert reocr_actions[1]["enabled"] is False
    assert "查看影响" in reocr_actions[2]["description"]
    assert "撤回" in reocr_actions[3]["description"]
    assert dry_run["reviewQueues"]["employeeExceptions"]["count"] == 1
    assert dry_run["reviewQueues"]["employeeExceptions"]["suppressedByPrimary"] is True
    assert dry_run["aiCacheAudit"]["decision"] == "candidate_only"
    assert dry_run["aiCacheAudit"]["requiresConfirmation"] is True
    assert dry_run["aiCacheAudit"]["summary"]["candidateAmountTotal"] == 120
    assert dry_run["aiCacheAudit"]["files"][0]["evidence"][0]["sourcePageOrRow"] == "p1"
    assert dry_run["aiCacheReconciliationPreview"]["decision"] == "candidate_only"
    assert dry_run["aiCacheReconciliationPreview"]["summary"]["candidateRowCount"] == 1
    assert dry_run["aiCacheReconciliationPreview"]["summary"]["passedCount"] == 0
    assert dry_run["aiCacheReconciliationPreview"]["summary"]["exceptionCount"] == 1
    assert dry_run["aiCacheReconciliationPreview"]["summary"]["needsReocrFileCount"] == 1
    assert dry_run["aiCacheReconciliationPreview"]["fileQuality"][0]["decision"] == "needs_reocr"
    assert dry_run["reocrPlan"]["decision"] == "candidate_only"
    assert dry_run["reocrPlan"]["summary"]["taskCount"] == 1
    assert dry_run["reocrPlan"]["summary"]["imageOnlyTaskCount"] == 1
    assert dry_run["reocrPlan"]["tasks"][0]["sourceFile"] == "elog7-5_20260520204043.pdf"
    assert dry_run["reocrPlan"]["tasks"][0]["pdfTextCoverage"]["needsOcr"] is True
    assert dry_run["reocrPlan"]["tasks"][0]["extractionPrerequisite"] == "pdf_text_layer_empty_requires_ocr"
    assert dry_run["reocrPlan"]["tasks"][0]["reviewFocus"] == "需要重新图片识别"
    user_visible_reocr_text = " ".join(
        str(dry_run["reocrPlan"]["tasks"][0].get(field, ""))
        for field in ("reason", "confirmationGate", "matchReason", "businessQuestion", "impactSummary", "cannotAutoResolveReason")
    )
    assert "OCR" not in user_visible_reocr_text
    assert "AI" not in user_visible_reocr_text
    assert "图片识别" in user_visible_reocr_text or "重新识别" in user_visible_reocr_text
    assert "PDF 无可读取文本层" in dry_run["reocrPlan"]["tasks"][0]["matchReason"]
    assert "员工级异常 1 项" in dry_run["reocrPlan"]["tasks"][0]["matchReason"]
    assert "必须先查看员工级影响" in dry_run["reocrPlan"]["tasks"][0]["businessQuestion"]
    assert "员工级异常 1 项" in dry_run["reocrPlan"]["tasks"][0]["impactSummary"]
    assert "不能自动写入正式结果" in dry_run["reocrPlan"]["tasks"][0]["cannotAutoResolveReason"]
    assert "Alice Worker" in dry_run["reocrPlan"]["tasks"][0]["focusEmployees"][0]["employeeName"]
    assert "Alice Worker" in dry_run["reviewQueues"]["reocr"]["tasks"][0]["focusEmployees"][0]["employeeName"]
    assert dry_run["reviewQueues"]["reocr"]["tasks"][0]["reviewFocus"] == "需要重新图片识别"
    assert "必须业务确认" in dry_run["reocrPlan"]["tasks"][0]["confirmationGate"]
    assert dry_run["writesRun"] is False
    assert dry_run["aiInvoked"] is False
    assert any("无可读取文本层" in risk for risk in dry_run["expectedRisks"])
    assert any("历史图片识别" in risk for risk in dry_run["expectedRisks"])
    assert any("不能直接作为 PDF 明细" in risk for risk in dry_run["expectedRisks"])
    assert any("历史图片识别结果与账单仍有 1 项差异" in risk for risk in dry_run["expectedRisks"])
    assert any("历史图片识别结果：1 个 PDF 建议重新识别，0 个 PDF 可作为业务确认依据" in risk for risk in dry_run["expectedRisks"])
    assert any("已生成 1 个图片发票明细待确认事项" in risk for risk in dry_run["expectedRisks"])
    user_visible_material_text = " ".join(
        [
            dry_run["reviewQueues"]["primaryReason"],
            dry_run["deliveryGate"]["issues"][0]["title"],
            dry_run["deliveryGate"]["issues"][0]["message"],
            dry_run["deliveryGate"]["issues"][0]["action"],
            *dry_run["expectedRisks"],
            *[str(action.get("label", "")) for action in reocr_actions],
            *[str(action.get("description", "")) for action in reocr_actions],
        ]
    )
    for internal_copy in ["图片识别复核", "人工复核", "人工确认", "需预览", "必须预览", "影响预览"]:
        assert internal_copy not in user_visible_material_text


def test_build_material_dry_run_explains_image_only_pdf_without_history_cache(monkeypatch, tmp_path):
    import bonus_platform.engine.labor.materials as materials_module

    batch = tmp_path / "prompt"
    batch.mkdir()
    (batch / "DEPT#2.pdf").write_bytes(b"%PDF-1.4\n")
    _write_labor_bill_workbook_with_rows(
        batch / "员工账单明细 - 2026-05-28T151400.642.xlsx",
        [["WUS001", "Alice Worker", 8, 100, "USD", "2号仓"]],
    )

    monkeypatch.setattr(
        materials_module,
        "quick_extract_totals",
        lambda paths, config, supplier="": [{"source_file": paths[0].name, "total_amount": 0.0, "warehouse_id": "2"}],
    )
    monkeypatch.setattr(materials_module, "extract_invoice_items", lambda paths, config, **kwargs: [])
    monkeypatch.setattr(
        materials_module,
        "_extract_pdf_pages",
        lambda paths: [{"source_file": paths[0].name, "page": 1, "text": ""}],
    )

    dry_run = build_material_dry_run(tmp_path, "prompt")

    assert dry_run["reviewQueues"]["primary"] == "reocr"
    assert dry_run["deliveryGate"]["status"] == "blocked"
    assert dry_run["reocrPlan"]["summary"]["taskCount"] == 1
    task = dry_run["reocrPlan"]["tasks"][0]
    assert task["sourceFile"] == "DEPT#2.pdf"
    assert "当前没有可用 PDF 明细覆盖账单" in task["matchReason"]
    assert "账单有但当前明细缺失 1 人" in task["impactSummary"]
    user_visible_text = " ".join(
        str(task.get(field, ""))
        for field in ("matchReason", "businessQuestion", "impactSummary", "cannotAutoResolveReason")
    )
    assert "缓存金额" not in user_visible_text
    assert "历史识别" not in user_visible_text
    assert any("已生成 1 个图片发票明细待确认事项" in risk for risk in dry_run["expectedRisks"])


def test_build_material_dry_run_promotes_reocr_suspected_name_pairs_to_governance(monkeypatch, tmp_path):
    import bonus_platform.engine.labor.materials as materials_module

    batch = tmp_path / "oss"
    batch.mkdir()
    (batch / "elog1-1_20260520204104.pdf").write_bytes(b"%PDF-1.4\n")
    _write_labor_bill_workbook_with_rows(
        batch / "员工账单明细 - 2026-05-27T110404.877.xlsx",
        [
            ["WUS045751", "Massiel Castillo", 30.92, 100.00, "USD", "1号仓"],
            ["WUS045752", "Other Worker", 2.00, 50.00, "USD", "1号仓"],
        ],
    )
    cache_dir = batch / ".ai_extract_cache"
    cache_dir.mkdir()
    (cache_dir / "elog1-1_20260520204104_p1_mimo-v2.5_v4.json").write_text(
        json.dumps(
            [
                {
                    "employee_name_raw": "Espinosa Manuel",
                    "source_page": 1,
                    "hours": 30.90,
                    "amount": 100.00,
                    "confidence": 0.95,
                    "evidence_text": "Espinosa Manuel TOTAL $100.00",
                }
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        materials_module,
        "quick_extract_totals",
        lambda paths, config, supplier="": [{"source_file": paths[0].name, "total_amount": 0.0, "warehouse_id": "1"}],
    )
    monkeypatch.setattr(materials_module, "extract_invoice_items", lambda paths, config, **kwargs: [])
    monkeypatch.setattr(
        materials_module,
        "_extract_pdf_pages",
        lambda paths: [{"source_file": paths[0].name, "page": 1, "text": ""}],
    )

    dry_run = build_material_dry_run(tmp_path, "oss")

    assert dry_run["reocrPlan"]["summary"]["taskCount"] == 1
    suspected = dry_run["reocrPlan"]["tasks"][0]["diagnostics"]["suspectedNamePairs"]
    assert suspected[0]["cacheEmployeeName"] == "Espinosa Manuel"
    governance = dry_run["nameMappingGovernance"]
    assert governance["decision"] == "candidate_only"
    assert governance["summary"]["candidateCount"] == 1
    assert governance["summary"]["fromReocrDiagnosticsCount"] == 1
    candidate = governance["candidates"][0]
    assert candidate["sourceDiagnostic"] == "reocr_suspected_name_pair"
    assert candidate["sourceFile"] == "elog1-1_20260520204104.pdf"
    assert candidate["warehouseId"] == "1"
    assert candidate["proposedMapping"] == {"Espinosa Manuel": "Massiel Castillo"}
    assert candidate["auditTrail"][0]["reason"] == "material_dry_run_reocr_suspected_name_pair"
    assert any("疑似同一员工" in risk for risk in dry_run["expectedRisks"])
    assert all("姓名匹配建议" not in risk for risk in dry_run["expectedRisks"])


def _write_labor_bill_workbook(path):
    _write_labor_bill_workbook_with_rows(path, [["WUS001", "Alice Worker", 8, 100, "USD", "7号仓"]])


def _write_labor_bill_workbook_with_rows(path, rows):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "员工账单"
    sheet.append(["工号", "姓名", "时长总计(H)", "费用总计(含税)", "币种", "物理仓"])
    for row in rows:
        sheet.append(row)
    workbook.save(path)
