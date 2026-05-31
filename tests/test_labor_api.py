from io import BytesIO
from pathlib import Path

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
    from bonus_platform.engine.labor.quality import calculate_extraction_quality

    quality = calculate_extraction_quality(
        [],  # No PDF rows needed for this test
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

    assert quality["level"] == "ok"
    assert quality["message"] == "抽取质量检查通过。"
    assert quality["issues"] == []


def test_labor_compare_endpoint_returns_running_status_before_polling(monkeypatch):
    import bonus_platform.app as app_module

    queued = {}

    # 后台任务现在通过 run_in_executor 运行，monkeypatch 替换为同步调用以便测试
    monkeypatch.setattr(app_module, "_run_labor_extract_compare", lambda run_id: queued.setdefault("completed", run_id))
    # 拦截 run_in_executor，直接同步调用
    import asyncio
    original_run_in_executor = asyncio.get_event_loop().run_in_executor
    def fake_run_in_executor(executor, fn, *args):
        fn(*args)
        # 返回一个已完成的 future
        f = asyncio.Future()
        f.set_result(None)
        return f
    monkeypatch.setattr(asyncio.get_event_loop(), "run_in_executor", fake_run_in_executor)

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

    response = client.post(f"/api/labor/runs/{run['id']}/extract-and-compare").json()

    assert response["status"] == "抽取中"
    assert queued.get("completed") == run["id"]


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


def test_parallel_rule_extraction(monkeypatch):
    """测试并行规则抽取 - 通过 extract_invoice_items 并行路径"""
    import bonus_platform.engine.labor.extract as extract_module
    from bonus_platform.engine.labor.extract import extract_invoice_items

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

    # Mock _extract_pdf_pages 以返回多页数据
    monkeypatch.setattr(extract_module, "_extract_pdf_pages", lambda pdf_paths, **kw: pages)

    # 配置: 启用并行抽取
    ai_config = {
        "parallel_extraction_enabled": True,
        "parallel_max_workers": 4,
        "enabled": False,  # 禁用 AI，仅走规则路径
    }

    # 调用 extract_invoice_items（并行路径）
    items = extract_invoice_items(
        pdf_paths=[Path("invoice1.pdf"), Path("invoice2.pdf")],
        ai_config=ai_config,
        supplier="Test",
        period_start="2026-05-01",
        period_end="2026-05-31",
        currency="USD",
    )

    # 验证结果 - 两个文件的页面都应被并行处理
    assert len(items) == 3, f"应抽取 3 条记录，实际 {len(items)} 条"
    assert any(item.employee_name_raw == "Alvarez, Rosa" for item in items)
    assert any(item.employee_name_raw == "Smith, John" for item in items)
    assert any(item.employee_name_raw == "Johnson, Maria" for item in items)


def test_parallel_extraction_disabled(monkeypatch):
    """测试禁用并行抽取 - 并行开关关闭后走串行路径"""
    import bonus_platform.engine.labor.extract as extract_module
    from bonus_platform.engine.labor.extract import extract_invoice_items

    # 模拟多个页面数据
    pages = [
        {
            "source_file": "invoice1.pdf",
            "page": 1,
            "text": "05/01/2026\nAlvarez, Rosa\n8.00\nReg\nREG\n$25.00\n$200.00\n$200.00"
        },
        {
            "source_file": "invoice2.pdf",
            "page": 1,
            "text": "05/03/2026\nJohnson, Maria\n6.00\nReg\nREG\n$30.00\n$180.00\n$180.00"
        }
    ]

    # Mock _extract_pdf_pages 以返回多页数据
    monkeypatch.setattr(extract_module, "_extract_pdf_pages", lambda pdf_paths, **kw: pages)

    # 配置: 禁用并行抽取
    ai_config = {
        "parallel_extraction_enabled": False,
        "parallel_max_workers": 4,
        "enabled": False,  # 禁用 AI，仅走规则路径
    }

    # 调用 extract_invoice_items - 应走串行路径（for page in pages）
    items = extract_invoice_items(
        pdf_paths=[Path("invoice1.pdf"), Path("invoice2.pdf")],
        ai_config=ai_config,
        supplier="Test",
        period_start="2026-05-01",
        period_end="2026-05-31",
        currency="USD",
    )

    # 验证串行路径仍能正确抽取所有页面的结果（每页 1 人，共 2 人）
    assert len(items) == 2, f"串行路径应抽取 2 条记录，实际 {len(items)} 条"
    assert any(item.employee_name_raw == "Alvarez, Rosa" for item in items)
    assert any(item.employee_name_raw == "Johnson, Maria" for item in items)


def test_parallel_image_render_workers_config():
    """测试并行图片渲染配置默认值"""
    from bonus_platform.config import AI_CONFIG

    # 验证配置存在
    assert "parallel_extraction_enabled" in AI_CONFIG
    assert "parallel_max_workers" in AI_CONFIG
    assert "parallel_image_render_workers" in AI_CONFIG

    # 验证默认值
    assert AI_CONFIG["parallel_extraction_enabled"] is True
    assert AI_CONFIG["parallel_max_workers"] == 2
    assert AI_CONFIG["parallel_image_render_workers"] == 2


def test_parallel_image_rendering(monkeypatch):
    """测试并行图片渲染 - 多个 PDF 文件并行渲染"""
    import sys
    from unittest.mock import MagicMock
    from PIL import Image

    from bonus_platform.engine.labor.extract import _render_pdf_pages_to_images

    # 创建 3 个模拟 PDF 路径
    pdf_paths = [Path(f"invoice_{i}.pdf") for i in range(3)]

    # 追踪并行调用
    render_calls = []

    # Mock pypdfium2 - 函数内部 import pypdfium2
    mock_pdfium = MagicMock()

    def fake_pdf_document(path_str):
        """模拟 PdfDocument，返回包含 1 页的 mock 文档"""
        render_calls.append(path_str)
        mock_doc = MagicMock()
        mock_page = MagicMock()
        # 使用真实的 PIL Image，以便 save() 能产生实际 bytes
        pil_img = Image.new("RGB", (10, 10), color="white")
        mock_bitmap = MagicMock()
        mock_bitmap.to_pil.return_value = pil_img
        mock_page.render.return_value = mock_bitmap
        mock_page.close = MagicMock()
        # 文档有 1 页
        mock_doc.__len__ = MagicMock(return_value=1)
        mock_doc.__getitem__ = MagicMock(return_value=mock_page)
        mock_doc.close = MagicMock()
        return mock_doc

    mock_pdfium.PdfDocument = fake_pdf_document
    monkeypatch.setitem(sys.modules, "pypdfium2", mock_pdfium)

    # 调用并行渲染函数（3个文件 > 1，触发并行路径）
    result = _render_pdf_pages_to_images(pdf_paths, scale=1.5, max_workers=4)

    # 验证所有 3 个 PDF 都被渲染了
    assert len(render_calls) == 3, f"应渲染 3 个 PDF，实际渲染 {len(render_calls)} 个"
    assert len(result) == 3, f"应返回 3 个页面，实际 {len(result)} 个"

    # 验证每个页面都有正确的元数据
    source_files = {p["source_file"] for p in result}
    assert source_files == {"invoice_0.pdf", "invoice_1.pdf", "invoice_2.pdf"}
    for page in result:
        assert page["mime_type"] == "image/jpeg", "应使用 JPEG 格式以减少传输大小"
        assert page["base64"], "base64 不应为空"
        assert page["page"] == 1


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
