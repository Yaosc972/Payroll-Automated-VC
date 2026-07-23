from bonus_platform.engine.labor.ocr_candidate_adapter import OcrLine, OcrPageResult
from tools import labor_ocr_worker_task


def test_worker_task_converts_ocr_pages_to_candidate_rows(monkeypatch, tmp_path):
    pdf_path = tmp_path / "invoice.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    page = OcrPageResult(
        backend="rapidocr",
        page_number=1,
        lines=(
            OcrLine("DEPT#29", 0.99, ()),
            OcrLine("LAST NAME FIRST NAME REGULAR HRS BILL RATE AMOUNT", 0.99, ()),
            OcrLine("JANE DOE 8.00 10.00 80.00", 0.98, ()),
        ),
        duration_seconds=0.2,
    )
    monkeypatch.setattr(labor_ocr_worker_task, "_ocr_pdf", lambda _path, **_kwargs: [page])

    result = labor_ocr_worker_task.process_manifest(
        {
            "pdfFiles": [str(pdf_path)],
            "supplier": "Unknown",
            "periodStart": "2026-05-11",
            "periodEnd": "2026-05-17",
            "currency": "USD",
        }
    )

    assert result["status"] == "completed"
    assert result["rows"][0]["employee_name_raw"] == "JANE DOE"
    assert result["rows"][0]["amount"] == 80.0
    assert result["rows"][0]["warehouse_id"] == "29"
    assert result["files"][0]["pageCount"] == 1


def test_worker_task_records_unique_explicit_invoice_total(monkeypatch, tmp_path):
    pdf_path = tmp_path / "invoice.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    page = OcrPageResult(
        backend="rapidocr",
        page_number=1,
        lines=(
            OcrLine("LAST NAME FIRST NAME HRS BILL RATE AMOUNT", 0.99, ()),
            OcrLine("RODRIGUEZ LIT7Y 4.07 22.58 91.90", 0.98, ()),
            OcrLine("TOTAL: $ 91.90", 0.99, ()),
        ),
        duration_seconds=0.2,
    )
    monkeypatch.setattr(labor_ocr_worker_task, "_ocr_pdf", lambda _path, **_kwargs: [page])

    result = labor_ocr_worker_task.process_manifest(
        {
            "pdfFiles": [str(pdf_path)],
            "cacheDir": str(tmp_path / "cache"),
            "currency": "USD",
        }
    )

    assert result["rows"][0]["employee_name_raw"] == "RODRIGUEZ LITZY"
    assert result["files"][0]["explicitTotalAmount"] == 91.90
    assert result["files"][0]["explicitTotalEvidence"]["page"] == 1
    assert result["files"][0]["explicitTotalEvidence"]["evidenceText"] == "TOTAL: $ 91.90"


def test_worker_task_accepts_ocr_s_currency_marker_for_explicit_total():
    page = OcrPageResult(
        backend="rapidocr",
        page_number=1,
        lines=(OcrLine("TOTAL: s 3,317.09", 0.99, ()),),
        duration_seconds=0.2,
    )

    evidence = labor_ocr_worker_task._extract_explicit_total_evidence([page])

    assert evidence["explicitTotalAmount"] == 3317.09
    assert evidence["explicitTotalEvidence"]["currency"] == "$"


def test_worker_task_reuses_content_cache_after_pdf_rename(monkeypatch, tmp_path):
    first_pdf = tmp_path / "first.pdf"
    renamed_pdf = tmp_path / "renamed.pdf"
    first_pdf.write_bytes(b"identical pdf")
    renamed_pdf.write_bytes(b"identical pdf")
    cache_dir = tmp_path / "cache"
    calls = {"ocr": 0}
    page = OcrPageResult(
        backend="rapidocr",
        page_number=1,
        lines=(
            OcrLine("DEPT#29", 0.99, ()),
            OcrLine("LAST NAME FIRST NAME REGULAR HRS BILL RATE AMOUNT", 0.99, ()),
            OcrLine("JANE DOE 8.00 10.00 80.00", 0.98, ()),
        ),
        duration_seconds=0.2,
    )

    def fake_ocr(_path, **_kwargs):
        calls["ocr"] += 1
        return [page]

    monkeypatch.setattr(labor_ocr_worker_task, "_ocr_pdf", fake_ocr)

    first = labor_ocr_worker_task.process_manifest(
        {"pdfFiles": [str(first_pdf)], "cacheDir": str(cache_dir), "currency": "USD"}
    )
    second = labor_ocr_worker_task.process_manifest(
        {"pdfFiles": [str(renamed_pdf)], "cacheDir": str(cache_dir), "currency": "USD"}
    )

    assert calls["ocr"] == 1
    assert first["files"][0]["cacheHit"] is False
    assert second["files"][0]["cacheHit"] is True
    assert second["rows"][0]["source_file"] == "renamed.pdf"
    assert second["files"][0]["sourceFile"] == "renamed.pdf"


def test_worker_task_publishes_page_progress_without_employee_details(monkeypatch, tmp_path):
    pdf_path = tmp_path / "invoice.pdf"
    pdf_path.write_bytes(b"pdf")
    progress_path = tmp_path / "progress.json"
    snapshots = []
    pages = [
        OcrPageResult("rapidocr", 1, (), 0.1),
        OcrPageResult("rapidocr", 2, (), 0.1),
    ]

    def fake_write(_path, payload):
        snapshots.append(dict(payload))

    def fake_ocr(_path, *, page_callback=None, **_kwargs):
        for index, page in enumerate(pages, start=1):
            if page_callback:
                page_callback(page, index, len(pages))
        return pages

    monkeypatch.setattr(labor_ocr_worker_task, "_write_progress", fake_write)
    monkeypatch.setattr(labor_ocr_worker_task, "_ocr_pdf", fake_ocr)

    labor_ocr_worker_task.process_manifest(
        {
            "pdfFiles": [str(pdf_path)],
            "cacheDir": str(tmp_path / "cache"),
            "progressFile": str(progress_path),
        }
    )

    assert snapshots[0]["status"] == "running"
    running_pages = [item["processedPages"] for item in snapshots if item["status"] == "running"]
    assert running_pages == sorted(running_pages)
    assert {0, 1, 2}.issubset(running_pages)
    assert snapshots[-1]["status"] == "completed"
    assert snapshots[-1]["processedFiles"] == 1
    assert snapshots[-1]["totalPages"] == 2
    assert all("rows" not in item and "employee" not in str(item).lower() for item in snapshots)
