from io import BytesIO

import pytest
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


def test_adaptive_tolerance_for_large_amounts():
    """测试大金额的自适应容忍度"""
    from bonus_platform.engine.labor.compare import _adaptive_tolerance

    # 小金额使用基础容忍度
    assert _adaptive_tolerance(500) == 0.05

    # $1000 边界
    assert _adaptive_tolerance(1000) == 0.05
    assert _adaptive_tolerance(1001) > 0.05

    # 大金额容忍度更高
    tol_50k = _adaptive_tolerance(50000)
    tol_100k = _adaptive_tolerance(100000)
    assert tol_50k > 0.05
    assert tol_100k > tol_50k

    # 仓库19 的 $0.09 差异（$54,689）应在容忍范围内
    tol_54k = _adaptive_tolerance(54689)
    assert 0.09 <= tol_54k, f"$0.09 差异应被容忍, 但容忍度仅为 {tol_54k}"

    # 容忍度不应过高（即使 $1M 也不超过 $1）
    assert _adaptive_tolerance(1_000_000) < 1.0


def test_advanced_name_normalization():
    """测试高级姓名标准化"""
    from bonus_platform.engine.labor.parsing import normalize_employee_name_advanced

    # "Last, First" 格式
    assert normalize_employee_name_advanced("Alvarez, Rosa") == "rosa alvarez"

    # 中间名缩写
    assert normalize_employee_name_advanced("Rosa J. Alvarez") == "rosa alvarez"

    # 多余空格
    assert normalize_employee_name_advanced("  Rosa   Alvarez  ") == "rosa alvarez"

    # 空字符串
    assert normalize_employee_name_advanced("") == ""

    # 单个名字
    assert normalize_employee_name_advanced("Rosa") == "rosa"

    # 三个部分无中间名缩写
    assert normalize_employee_name_advanced("Rosa Maria Alvarez") == "rosa maria alvarez"


def test_parallel_rule_extraction():
    """测试并行规则抽取"""
    from bonus_platform.engine.labor.extract import extract_invoice_items, _extract_with_rules
    from bonus_platform.config import AI_CONFIG

    # 模拟多个页面数据
    pages = [
        {
            "source_file": "invoice1.pdf",
            "page": 1,
            "text": "05/01/2026\nAlvarez, Rosa\n8.00\nReg\nREG\n$25.00\n$200.00\n$200.00\n05/02/2026\nSmith, John\n4.00\nOT\nOT\n$37.50\n$150.00\n$150.00"
        },
        {
            "source_file": "invoice2.pdf",
            "page": 1,
            "text": "05/03/2026\nJohnson, Maria\n6.00\nReg\nREG\n$30.00\n$180.00\n$180.00"
        }
    ]

    # 测试并行抽取
    items = _extract_with_rules(pages, supplier="Test", period_start="2026-05-01", period_end="2026-05-31", currency="USD")

    # 验证结果
    assert len(items) == 3, f"应抽取 3 条记录，实际 {len(items)} 条"
    assert any(item.employee_name_raw == "Alvarez, Rosa" for item in items)
    assert any(item.employee_name_raw == "Smith, John" for item in items)
    assert any(item.employee_name_raw == "Johnson, Maria" for item in items)


def test_parallel_extraction_disabled():
    """测试禁用并行抽取"""
    from bonus_platform.engine.labor.extract import _extract_with_rules

    # 模拟页面数据
    pages = [
        {
            "source_file": "invoice1.pdf",
            "page": 1,
            "text": "05/01/2026\nAlvarez, Rosa\n8.00\nReg\nREG\n$25.00\n$200.00\n$200.00"
        }
    ]

    # 测试串行抽取（单页面）
    items = _extract_with_rules(pages, supplier="Test", period_start="2026-05-01", period_end="2026-05-31", currency="USD")

    # 验证结果
    assert len(items) == 1
    assert items[0].employee_name_raw == "Alvarez, Rosa"
    assert items[0].amount == 200.0


def test_parallel_image_render_workers_config():
    """测试并行图片渲染配置"""
    from bonus_platform.config import AI_CONFIG

    # 验证配置存在
    assert "parallel_extraction_enabled" in AI_CONFIG
    assert "parallel_max_workers" in AI_CONFIG
    assert "parallel_image_render_workers" in AI_CONFIG

    # 验证默认值
    assert AI_CONFIG["parallel_extraction_enabled"] is True
    assert AI_CONFIG["parallel_max_workers"] == 6
    assert AI_CONFIG["parallel_image_render_workers"] == 4


def test_improved_name_similarity():
    """测试改进的姓名相似度"""
    from bonus_platform.engine.labor.compare import _name_similarity_improved

    # 相同姓名
    assert _name_similarity_improved("Rosa Alvarez", "Rosa Alvarez") == 1.0

    # "Last, First" vs "First Last"
    score_comma = _name_similarity_improved("Alvarez, Rosa", "Rosa Alvarez")
    assert score_comma > 0.8, f"Last/First格式匹配得分过低: {score_comma}"

    # 中间名差异
    score_middle = _name_similarity_improved("Rosa J. Alvarez", "Rosa Alvarez")
    assert score_middle > 0.8, f"中间名差异匹配得分过低: {score_middle}"

    # 拼写错误
    score_typo = _name_similarity_improved("Rosa Alvarez", "Rosa Alvarex")
    assert score_typo > 0.65, f"拼写错误匹配得分过低: {score_typo}"

    # 昵称变体
    score_nick = _name_similarity_improved("Bob Smith", "Robert Smith")
    assert score_nick > 0.5, f"昵称变体匹配得分过低: {score_nick}"

    # 完全不同的名字
    score_diff = _name_similarity_improved("Rosa Alvarez", "John Smith")
    assert score_diff < 0.5, f"不同名字匹配得分过高: {score_diff}"
