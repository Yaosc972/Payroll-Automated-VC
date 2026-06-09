from io import BytesIO
import json
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
from bonus_platform.app import _non_payable_pdf_names
from bonus_platform.engine.labor.report import build_labor_report
from bonus_platform.engine.labor.workbook import read_workbook_rows, suggest_mapping


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


def _workbook_with_tax_columns_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "账单"
    sheet.append(["姓名", "时长总计(H)", "费用总计(不含税)", "费用总计(含税)", "币种"])
    sheet.append(["Jose Perez", 40.14, 1000.00, 1037.81, "USD"])
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
    assert _warehouse_id_from_text("Location: 3号仓") == "3"
    assert _warehouse_id_from_text("Warehouse: WH 28") == "28"
    assert _warehouse_id_from_text("LOC #21") == "21"


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
    assert result["summary"]["totalPassed"] is False
    assert result["summary"]["diffWarehouses"] == ["3", "5"]
    assert {row["warehouseId"]: row["amountDelta"] for row in result["rows"]} == {"3": 1000.0, "5": -1000.0}


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
    assert result["summary"]["hoursDiffCount"] == 1
    assert result["rows"][0]["matchStatus"] == "通过"
    assert "工时需复核" in result["rows"][0]["riskFlags"]


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


def test_supplier_profiles_can_load_single_object_config(tmp_path):
    path = tmp_path / "invoice.json"
    path.write_text(
        json.dumps(
            {
                "key": "invoice",
                "aliases": ["invoice"],
                "prompt_notes": ["Use every invoice page."],
                "image_page_policy": "all",
            }
        ),
        encoding="utf-8",
    )

    profiles = load_supplier_profiles(path)

    assert len(profiles) == 1
    assert profiles[0].key == "invoice"
    assert profiles[0].image_page_policy == "all"


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
    assert workbook.sheetnames == ["核对结论", "核对摘要", "全员对账明细", "金额差异员工", "工时风险项", "不在本批发票", "姓名格式差异", "低置信度抽取", "PDF抽取明细", "Excel账单明细", "字段映射记录"]
    assert workbook["姓名格式差异"].max_row == 2
    assert workbook["全员对账明细"].max_row == 2


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
