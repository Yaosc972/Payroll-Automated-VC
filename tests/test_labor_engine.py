from io import BytesIO
import json

import pytest
from openpyxl import Workbook, load_workbook
from urllib.error import HTTPError

from bonus_platform.engine.labor.compare import compare_labor_items
from bonus_platform.engine.labor.extract import extract_invoice_items, _extract_with_ai_images, _extract_with_rules, _request_headers
from bonus_platform.engine.labor.extract import _ai_instruction, _extract_pdf_pages, _safe_error_message
from bonus_platform.engine.labor.models import LaborLineItem, line_items_from_dicts
from bonus_platform.engine.labor.parsing import normalize_employee_name, parse_number
from bonus_platform.engine.labor.profiles import load_supplier_profiles, resolve_supplier_profile
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

    result = compare_labor_items(pdf_rows, excel_rows)

    assert result["summary"]["unmatchedPdfCount"] == 0
    assert result["summary"]["unmatchedExcelCount"] == 0
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

    result = compare_labor_items(pdf_rows, excel_rows)

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
        lambda paths, scale=1.5: [
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


def test_rendered_invoice_images_are_rotated_to_landscape(monkeypatch, tmp_path):
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
    assert image.size == (200, 100)


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

    assert content[0]["type"] == "image_url"
    assert content[0]["image_url"]["url"] == "data:image/png;base64,abc123"
    assert captured["payload"]["thinking"]["type"] == "disabled"
    assert rows[0]["employee_name_raw"] == "Alvarez Minchaca, Rosa"
    assert rows[0]["source_type"] == "pdf_invoice"
    assert rows[0]["supplier"] == "ONESOURCE"


def test_extract_invoice_items_uses_mimo_images_when_pdf_text_has_no_rows(monkeypatch, tmp_path):
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    monkeypatch.setattr("bonus_platform.engine.labor.extract._extract_pdf_pages", lambda paths: [{"source_file": "scan.pdf", "page": 1, "text": ""}])
    monkeypatch.setattr(
        "bonus_platform.engine.labor.extract._render_pdf_pages_to_images",
        lambda paths, scale=1.5: [{"source_file": "scan.pdf", "page": 1, "mime_type": "image/png", "base64": "abc123"}],
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

    assert [row["employee_name_raw"] for row in rows] == ["Alvarez Minchaca, Rosa"]


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


def test_mimo_image_extractor_uses_page_cache(monkeypatch, tmp_path):
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"pdf")
    cache_dir = tmp_path / ".ai_extract_cache"
    cache_dir.mkdir()
    cache_file = cache_dir / "scan_p1_mimo-v2.5_v4.json"
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

    cache_file = tmp_path / ".ai_extract_cache" / "scan_p1_mimo-v2.5_v4.json"
    assert cache_file.exists()


def test_extract_invoice_items_surfaces_ai_failure_when_enabled(monkeypatch, tmp_path):
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    monkeypatch.setattr("bonus_platform.engine.labor.extract._extract_pdf_pages", lambda paths: [{"source_file": "scan.pdf", "page": 1, "text": ""}])
    monkeypatch.setattr("bonus_platform.engine.labor.extract._extract_with_ai_text", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("HTTP 401 Invalid API Key")))
    monkeypatch.setattr("bonus_platform.engine.labor.extract._render_pdf_pages_to_images", lambda paths: [])

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
    assert workbook.sheetnames == ["核对摘要", "金额差异员工", "工时风险项", "未匹配员工", "未匹配候选", "低置信度抽取", "PDF抽取明细", "Excel账单明细", "字段映射记录"]
    assert workbook["未匹配候选"].max_row == 2
