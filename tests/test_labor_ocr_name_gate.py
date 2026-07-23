from bonus_platform.engine.labor.models import LaborLineItem
from bonus_platform.engine.labor.ocr_name_gate import build_ocr_name_gate


def _row(name, hours, amount, source="pdf_invoice_candidate"):
    return LaborLineItem(
        source_type=source,
        source_file="sample",
        source_page_or_row="p1",
        employee_id="",
        employee_name_raw=name,
        hours=hours,
        amount=amount,
    )


def test_name_gate_confirms_unique_token_exact_match_with_different_order():
    report = build_ocr_name_gate(
        [_row("Arellano Luna, Pablo", 40.4, 909.44)],
        [_row("Pablo Arellano Luna (ARE95A)", 40.4, 909.44, "offline_workbook")],
    )

    assert report["matches"][0]["status"] == "confirmed"
    assert report["matches"][0]["excelName"] == "Pablo Arellano Luna (ARE95A)"
    assert report["summary"]["unlinkedExcel"] == 0


def test_name_gate_keeps_spelling_difference_for_review_even_when_totals_match():
    report = build_ocr_name_gate(
        [_row("Deisy Rozo Panche", 37.84, 847.84)],
        [_row("Deisi Pozo", 37.84, 847.84, "offline_workbook")],
    )

    assert report["matches"][0]["status"] == "review"
    assert report["matches"][0]["amountSupported"] is True
    assert report["matches"][0]["hoursSupported"] is True


def test_name_gate_does_not_confirm_ambiguous_duplicate_normalized_names():
    report = build_ocr_name_gate(
        [_row("Maria Lopez", 8, 80)],
        [
            _row("Maria Lopez (A1)", 8, 80, "offline_workbook"),
            _row("Maria Lopez (A2)", 8, 80, "offline_workbook"),
        ],
    )

    assert report["matches"][0]["status"] != "confirmed"
