from bonus_platform.engine.labor.models import LaborLineItem
from bonus_platform.engine.labor.ocr_targeted_retry import (
    build_targeted_ocr_retry_plan,
    merge_targeted_ocr_retry_rows,
)


def _row(name: str, amount: float, page: str, source: str = "invoice.pdf") -> LaborLineItem:
    return LaborLineItem(
        source_type="pdf_invoice",
        source_file=source,
        source_page_or_row=page,
        employee_id="",
        employee_name_raw=name,
        hours=8,
        amount=amount,
        currency="USD",
        confidence=0.9,
        evidence_text=name,
    )


def test_targeted_retry_plan_selects_only_pages_with_review_names():
    candidate = {
        "safeToUse": False,
        "blockers": ["strict_name_review_required"],
        "fileClosure": [{"sourceFile": "invoice.pdf", "expectedAmount": 150, "closed": True}],
        "nameGate": {
            "matches": [
                {"candidateName": "Jane Doe", "excelName": "Jane Doe", "status": "confirmed"},
                {"candidateName": "Jon Smth", "excelName": "John Smith", "status": "review"},
            ]
        },
        "rows": [_row("Jane Doe", 100, "p1").to_dict(), _row("Jon Smth", 50, "p4").to_dict()],
    }

    plan = build_targeted_ocr_retry_plan(candidate)

    assert plan["eligible"] is True
    assert plan["allowedPagesBySource"] == {"invoice.pdf": [4]}
    assert plan["reviewExcelNames"] == ["John Smith"]


def test_targeted_retry_plan_falls_back_when_review_row_has_no_page():
    candidate = {
        "safeToUse": False,
        "blockers": ["strict_name_review_required"],
        "fileClosure": [{"sourceFile": "invoice.pdf", "expectedAmount": 50, "closed": True}],
        "nameGate": {"matches": [{"candidateName": "Jon Smth", "excelName": "John Smith", "status": "review"}]},
        "rows": [_row("Jon Smth", 50, "unknown").to_dict()],
    }

    plan = build_targeted_ocr_retry_plan(candidate)

    assert plan["eligible"] is False
    assert plan["reason"] == "review_page_unavailable"


def test_targeted_retry_merge_requires_invoice_amount_closure():
    candidate_rows = [_row("Jane Doe", 100, "p1"), _row("Jon Smth", 50, "p4")]
    retry_rows = [_row("John Smith", 50, "p4")]

    merged = merge_targeted_ocr_retry_rows(
        candidate_rows,
        retry_rows,
        allowed_pages_by_source={"invoice.pdf": [4]},
        expected_totals={"invoice.pdf": 150},
        tolerance=0.1,
    )
    failed = merge_targeted_ocr_retry_rows(
        candidate_rows,
        [_row("John Smith", 40, "p4")],
        allowed_pages_by_source={"invoice.pdf": [4]},
        expected_totals={"invoice.pdf": 150},
        tolerance=0.1,
    )

    assert merged["closed"] is True
    assert [row.employee_name_raw for row in merged["rows"]] == ["Jane Doe", "John Smith"]
    assert failed["closed"] is False
    assert failed["rows"] == candidate_rows
