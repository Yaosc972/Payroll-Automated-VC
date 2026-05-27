from io import BytesIO

import pytest
from openpyxl import Workbook, load_workbook

from bonus_platform.engine.labor.compare import compare_labor_items
from bonus_platform.engine.labor.models import LaborLineItem
from bonus_platform.engine.labor.parsing import normalize_employee_name, parse_number
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


def test_normalize_employee_name_handles_invoice_and_workbook_variants():
    assert normalize_employee_name("PEREZ, JOSE") == normalize_employee_name("Jose Perez")
    assert normalize_employee_name("#1 Ana Maria Corea") == normalize_employee_name("COREA MARIA, ANA")
    assert normalize_employee_name("CONTRERAS, EVELYN (CERVANTES)") == normalize_employee_name("Evelyn Contreras")
    assert normalize_employee_name("MORA-3491, CLAUDIA") == normalize_employee_name("Claudia Mora-3491")


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
    }

    build_labor_report(output, comparison, [], [], {"name": "姓名", "hours": "时长", "amount": "金额"})

    workbook = load_workbook(output, read_only=True)
    assert workbook.sheetnames == ["核对摘要", "金额差异员工", "工时风险项", "未匹配员工", "低置信度抽取", "PDF抽取明细", "Excel账单明细", "字段映射记录"]
