from io import BytesIO

from fastapi.testclient import TestClient
from openpyxl import Workbook

from bonus_platform.app import app
from bonus_platform.engine.labor.models import LaborLineItem


def _excel_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "员工账单"
    sheet.append(["工号", "姓名", "时长总计(H)", "费用总计(含税)", "币种"])
    sheet.append(["WUS042586", "Rosa Alvarez Minchaca", 31.19, 701.90, "USD"])
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_labor_run_api_creates_batch_uploads_files_and_suggests_mapping():
    client = TestClient(app)

    create = client.post(
        "/api/labor/runs",
        json={"supplier_name": "Fairway Staffing Service", "period_start": "2026-05-11", "period_end": "2026-05-17", "currency": "USD", "notes": "sample"},
    )

    assert create.status_code == 200
    run = create.json()
    assert run["id"].startswith("labor_")
    assert run["status"] == "已创建"

    upload = client.post(
        f"/api/labor/runs/{run['id']}/files",
        files=[
            ("pdf_files", ("invoice.pdf", b"%PDF-1.4\n% sample", "application/pdf")),
            ("workbook_file", ("账单.xlsx", _excel_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
        ],
    )

    assert upload.status_code == 200
    uploaded = upload.json()
    assert uploaded["status"] == "已上传文件"
    assert uploaded["files"]["workbook"]["filename"].endswith(".xlsx")
    assert uploaded["files"]["pdfInvoices"][0]["filename"].endswith(".pdf")

    sheets = client.get(f"/api/labor/runs/{run['id']}/workbook-sheets")
    assert sheets.status_code == 200
    assert sheets.json()["sheets"] == ["员工账单"]

    suggestion = client.post(f"/api/labor/runs/{run['id']}/field-suggestions", json={"sheet_name": "员工账单"})
    assert suggestion.status_code == 200
    assert suggestion.json()["suggestedMapping"]["name"] == "姓名"
    assert suggestion.json()["suggestedMapping"]["hours"] == "时长总计(H)"

    mapping = client.post(
        f"/api/labor/runs/{run['id']}/mapping",
        json={"sheet_name": "员工账单", "mapping": {"name": "姓名", "hours": "时长总计(H)", "amount": "费用总计(含税)", "currency": "币种"}},
    )
    assert mapping.status_code == 200
    assert mapping.json()["excelMapping"]["name"] == "姓名"


def test_labor_compare_records_failure_when_pdf_extraction_returns_no_employee_rows(monkeypatch):
    import bonus_platform.app as app_module

    monkeypatch.setattr(app_module, "quick_extract_totals", lambda *args, **kwargs: [])
    monkeypatch.setattr(app_module, "extract_invoice_items", lambda *args, **kwargs: [])
    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "ONESOURCE", "period_start": "2026-05-11", "period_end": "2026-05-17", "currency": "USD"},
    ).json()
    upload = client.post(
        f"/api/labor/runs/{run['id']}/files",
        files=[
            ("pdf_files", ("scan.pdf", b"%PDF-1.4\n", "application/pdf")),
            ("workbook_file", ("账单.xlsx", _excel_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
        ],
    )
    assert upload.status_code == 200
    client.post(
        f"/api/labor/runs/{run['id']}/mapping",
        json={"sheet_name": "员工账单", "mapping": {"name": "姓名", "hours": "时长总计(H)", "amount": "费用总计(含税)", "currency": "币种"}},
    )

    response = client.post(f"/api/labor/runs/{run['id']}/extract-and-compare")

    assert response.status_code == 200
    assert response.json()["status"] == "抽取中"
    body = client.get(f"/api/labor/runs/{run['id']}").json()
    assert body["status"] == "抽取失败"
    assert "PDF 未抽取出员工明细" in body["errorMessage"]


def test_labor_compare_response_includes_candidate_matches(monkeypatch):
    import bonus_platform.app as app_module

    monkeypatch.setattr(app_module, "quick_extract_totals", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        app_module,
        "extract_invoice_items",
        lambda *args, **kwargs: [
            LaborLineItem(source_type="pdf_invoice", source_file="scan.pdf", source_page_or_row="p1", employee_id="", employee_name_raw="Alvarez Mitrache, Ross", hours=30.5, amount=698.99, currency="USD", confidence=0.95, evidence_text="Total $698.99")
        ],
    )
    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "ONESOURCE", "period_start": "2026-05-11", "period_end": "2026-05-17", "currency": "USD"},
    ).json()
    client.post(
        f"/api/labor/runs/{run['id']}/files",
        files=[
            ("pdf_files", ("scan.pdf", b"%PDF-1.4\n", "application/pdf")),
            ("workbook_file", ("账单.xlsx", _excel_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
        ],
    )
    client.post(
        f"/api/labor/runs/{run['id']}/mapping",
        json={"sheet_name": "员工账单", "mapping": {"employeeId": "工号", "name": "姓名", "hours": "时长总计(H)", "amount": "费用总计(含税)", "currency": "币种"}},
    )

    response = client.post(f"/api/labor/runs/{run['id']}/extract-and-compare")

    assert response.status_code == 200
    body = client.get(f"/api/labor/runs/{run['id']}").json()
    assert "candidateMatches" in body
    assert isinstance(body["candidateMatches"], list)


def test_labor_compare_records_extraction_quality_warning_for_misaligned_totals(monkeypatch):
    import bonus_platform.app as app_module

    monkeypatch.setattr(app_module, "quick_extract_totals", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        app_module,
        "extract_invoice_items",
        lambda *args, **kwargs: [
            LaborLineItem(source_type="pdf_invoice", source_file="scan.pdf", source_page_or_row="p1", employee_id="", employee_name_raw="Alvarez Mitrache, Rosa", hours=10, amount=100, currency="USD", confidence=0.95, evidence_text="Total $100")
        ],
    )
    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "ONESOURCE", "period_start": "2026-05-11", "period_end": "2026-05-17", "currency": "USD"},
    ).json()
    client.post(
        f"/api/labor/runs/{run['id']}/files",
        files=[
            ("pdf_files", ("scan.pdf", b"%PDF-1.4\n", "application/pdf")),
            ("workbook_file", ("账单.xlsx", _excel_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
        ],
    )
    client.post(
        f"/api/labor/runs/{run['id']}/mapping",
        json={"sheet_name": "员工账单", "mapping": {"employeeId": "工号", "name": "姓名", "hours": "时长总计(H)", "amount": "费用总计(含税)", "currency": "币种"}},
    )

    response = client.post(f"/api/labor/runs/{run['id']}/extract-and-compare")

    assert response.status_code == 200
    body = client.get(f"/api/labor/runs/{run['id']}").json()
    assert body["status"] == "已生成差异报告"
    assert body["extractionQuality"]["level"] == "warning"
    assert any("总金额差异" in issue for issue in body["extractionQuality"]["issues"])
    assert "请复核 PDF 抽取明细" in body["extractionQuality"]["message"]


def test_labor_compare_retries_with_excel_candidates_when_quality_warns(monkeypatch):
    import bonus_platform.app as app_module

    monkeypatch.setattr(app_module, "quick_extract_totals", lambda *args, **kwargs: [])

    calls = []

    def fake_extract(*args, **kwargs):
        calls.append(kwargs)
        if kwargs.get("expected_rows"):
            return [
                LaborLineItem(source_type="pdf_invoice", source_file="scan.pdf", source_page_or_row="p1", employee_id="", employee_name_raw="Rosa Alvarez Minchaca", hours=31.19, amount=701.90, currency="USD", confidence=0.9, evidence_text="retry")
            ]
        return [
            LaborLineItem(source_type="pdf_invoice", source_file="scan.pdf", source_page_or_row="p1", employee_id="", employee_name_raw="Alvarez Mitrache, Rosa", hours=10, amount=100, currency="USD", confidence=0.95, evidence_text="first pass")
        ]

    monkeypatch.setattr(app_module, "extract_invoice_items", fake_extract)
    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "ONESOURCE", "period_start": "2026-05-11", "period_end": "2026-05-17", "currency": "USD"},
    ).json()
    client.post(
        f"/api/labor/runs/{run['id']}/files",
        files=[
            ("pdf_files", ("scan.pdf", b"%PDF-1.4\n", "application/pdf")),
            ("workbook_file", ("账单.xlsx", _excel_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
        ],
    )
    client.post(
        f"/api/labor/runs/{run['id']}/mapping",
        json={"sheet_name": "员工账单", "mapping": {"employeeId": "工号", "name": "姓名", "hours": "时长总计(H)", "amount": "费用总计(含税)", "currency": "币种"}},
    )

    response = client.post(f"/api/labor/runs/{run['id']}/extract-and-compare")

    assert response.status_code == 200
    body = client.get(f"/api/labor/runs/{run['id']}").json()
    assert len(calls) == 2
    assert calls[1]["expected_rows"][0]["employee_name"] == "Rosa Alvarez Minchaca"
    assert body["extractionQuality"]["level"] == "ok"
    assert body["extractionQuality"]["retryApplied"] is True
    assert body["comparisonSummary"]["exceptionCount"] == 0


def test_labor_extraction_quality_passes_when_counts_and_totals_align():
    import bonus_platform.app as app_module

    quality = app_module._labor_extraction_quality(
        {
            "pdfEmployeeCount": 161,
            "excelEmployeeCount": 161,
            "pdfHoursTotal": 5912.62,
            "excelHoursTotal": 5912.62,
            "pdfAmountTotal": 150078.21,
            "excelAmountTotal": 150119.51,
            "unmatchedPdfCount": 0,
            "unmatchedExcelCount": 0,
        }
    )

    assert quality == {"level": "ok", "message": "抽取质量检查通过。", "issues": []}


def test_labor_compare_endpoint_returns_running_status_before_polling(monkeypatch):
    import bonus_platform.app as app_module

    queued = {}

    class FakeBackgroundTasks:
        def add_task(self, fn, *args, **kwargs):
            queued["fn"] = fn
            queued["args"] = args
            queued["kwargs"] = kwargs

    monkeypatch.setattr(app_module, "_run_labor_extract_compare", lambda run_id: queued.setdefault("completed", run_id))
    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "ONESOURCE", "period_start": "2026-05-11", "period_end": "2026-05-17", "currency": "USD"},
    ).json()
    client.post(
        f"/api/labor/runs/{run['id']}/files",
        files=[
            ("pdf_files", ("scan.pdf", b"%PDF-1.4\n", "application/pdf")),
            ("workbook_file", ("账单.xlsx", _excel_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
        ],
    )
    client.post(
        f"/api/labor/runs/{run['id']}/mapping",
        json={"sheet_name": "员工账单", "mapping": {"employeeId": "工号", "name": "姓名", "hours": "时长总计(H)", "amount": "费用总计(含税)", "currency": "币种"}},
    )

    response = app_module.extract_and_compare_labor_run(run["id"], FakeBackgroundTasks())

    assert response["status"] == "抽取中"
    assert queued["args"] == (run["id"],)
