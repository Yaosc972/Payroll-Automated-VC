from io import BytesIO
import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

import bonus_platform.app as app_module
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


def _excel_bytes_with_warehouse() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "员工账单"
    sheet.append(["工号", "姓名", "时长总计(H)", "费用总计(含税)", "币种", "物理仓"])
    sheet.append(["WUS000001", "Alice Worker", 8, 100, "USD", "1号仓"])
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _excel_bytes_with_two_warehouses() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "员工账单"
    sheet.append(["工号", "姓名", "时长总计(H)", "费用总计(含税)", "币种", "物理仓"])
    sheet.append(["WUS000001", "Alice Worker", 8, 100, "USD", "1号仓"])
    sheet.append(["WUS000002", "Bob Worker", 10, 200, "USD", "2号仓"])
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _reocr_csv_bytes() -> bytes:
    return (
        "Employee,Hours,Amount,Page,Confidence,Evidence\n"
        "Alice Worker,8,100,p1,96%,Alice Worker 8 $100\n"
    ).encode("utf-8")


def _reocr_batch_csv_bytes() -> bytes:
    return (
        "SourceFile,WarehouseId,Employee,Hours,Amount,Page,Confidence,Currency,Evidence\n"
        "elog1-1_20260520204104.pdf,1,Alice Worker,8,100,p1,96%,USD,Alice Worker 8 $100\n"
        "elog2-2_20260520204104.pdf,2,Wrong Worker,10,200,p1,96%,USD,Wrong Worker 10 $200\n"
    ).encode("utf-8")


def test_labor_telemetry_records_sanitized_events_and_exports_jsonl(monkeypatch, tmp_path):
    telemetry_dir = tmp_path / "labor_telemetry"
    telemetry_file = telemetry_dir / "events.jsonl"
    monkeypatch.setattr(app_module, "LABOR_TELEMETRY_DIR", telemetry_dir)
    monkeypatch.setattr(app_module, "LABOR_TELEMETRY_FILE", telemetry_file)
    client = TestClient(app)

    response = client.post(
        "/api/labor/telemetry",
        json={
            "event": "labor.extract.completed",
            "runId": "labor_sample",
            "supplier": "Fairway Staffing Service",
            "step": "extract_compare",
            "status": "completed",
            "durationMs": 1234.4,
            "errorMessage": "first line\nsecond line",
            "summary": {
                "pdfAmountTotal": 100,
                "excelAmountTotal": 99.9,
                "exceptionCount": 1,
                "employeeRows": [{"employee": "Alice Worker", "amount": 100}],
            },
            "context": {
                "pdfCount": 2,
                "workbookCount": 1,
                "sourceFilename": "invoice.pdf",
            },
        },
    )

    assert response.status_code == 200
    event = json.loads(telemetry_file.read_text(encoding="utf-8").strip())
    assert event["schemaVersion"] == 1
    assert event["event"] == "labor.extract.completed"
    assert event["durationMs"] == 1234
    assert event["errorMessage"] == "first line second line"
    assert event["summary"] == {
        "pdfAmountTotal": 100.0,
        "excelAmountTotal": 99.9,
        "exceptionCount": 1.0,
    }
    assert event["context"] == {"pdfCount": 2.0, "workbookCount": 1.0}

    export = client.get("/api/labor/telemetry/export")
    assert export.status_code == 200
    assert export.text.strip() == telemetry_file.read_text(encoding="utf-8").strip()


def test_labor_access_endpoint_marks_uat_trial(monkeypatch):
    monkeypatch.delenv("SIGMA_OVERSEAS_LABOR_ACCESS", raising=False)
    client = TestClient(app)

    response = client.get("/api/labor/access")

    assert response.status_code == 200
    body = response.json()
    assert body["stage"] == "UAT试用版"
    assert body["access"] == "uat_trial"
    assert body["canUse"] is True
    assert "Payroll Admin" in body["allowedRoles"]


def test_labor_access_endpoint_can_enable_production_async_mode(monkeypatch):
    monkeypatch.setenv("SIGMA_OVERSEAS_LABOR_ACCESS", "production")
    client = TestClient(app)

    response = client.get("/api/labor/access")

    assert response.status_code == 200
    body = response.json()
    assert body["stage"] == "生产试运行"
    assert body["access"] == "production"
    assert body["canUse"] is True
    assert "持久化上传" in body["message"]


def test_labor_storage_health_reports_missing_supabase_secret_without_exposing_values(monkeypatch):
    monkeypatch.setenv("SIGMA_LABOR_STORAGE_BACKEND", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_STORAGE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    client = TestClient(app)

    response = client.get("/api/labor/storage-health?probe=1")

    assert response.status_code == 200
    body = response.json()
    assert body["backend"] == "supabase"
    assert body["supabaseUrlConfigured"] is True
    assert body["serviceRoleConfigured"] is False
    assert body["ok"] is False
    assert "example.supabase.co" not in json.dumps(body)


def test_labor_create_returns_structured_storage_error(monkeypatch):
    def fail_create_labor_run(metadata):
        raise RuntimeError("storage write failed")

    monkeypatch.setattr(app_module, "create_labor_run", fail_create_labor_run)
    client = TestClient(app)

    response = client.post(
        "/api/labor/runs",
        json={
            "supplier_name": "OSI",
            "period_start": "2026-06-08",
            "period_end": "2026-06-14",
            "currency": "USD",
        },
    )

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["message"] == "海外劳务批次创建失败，持久化存储暂不可用。"
    assert detail["errorType"] == "RuntimeError"
    assert "service_role key" in detail["nextAction"]


def test_labor_direct_upload_plan_returns_signed_urls(monkeypatch):
    monkeypatch.setattr(app_module, "labor_supabase_storage_enabled", lambda: True)
    monkeypatch.setattr(
        app_module,
        "create_labor_supabase_signed_upload",
        lambda run_id, relative_path: {
            "signedUrl": f"https://storage.example/upload/{relative_path}?token=signed-upload-token",
            "token": "signed-upload-token",
            "objectPath": f"labor-runs/test/{run_id}/{relative_path}",
            "relativePath": relative_path,
        },
    )
    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "OSI", "period_start": "2026-06-08", "period_end": "2026-06-14"},
    ).json()

    response = client.post(
        f"/api/labor/runs/{run['id']}/direct-upload-plan",
        json={
            "pdfFiles": [{"name": "invoice.pdf", "size": 6_000_000, "type": "application/pdf"}],
            "workbookFiles": [{"name": "bill.xlsx", "size": 10_000, "type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}],
        },
    )

    assert response.status_code == 200
    uploads = response.json()["uploads"]
    assert [item["group"] for item in uploads] == ["pdfInvoices", "workbooks"]
    assert uploads[0]["signedUrl"].startswith("https://storage.example/upload/invoice_direct_")
    assert uploads[0]["originalFilename"] == "invoice.pdf"
    assert "service_role" not in json.dumps(response.json())


def test_labor_direct_upload_plan_uses_ascii_storage_keys_for_chinese_filenames(monkeypatch):
    captured_paths = []
    monkeypatch.setattr(app_module, "labor_supabase_storage_enabled", lambda: True)

    def fake_signed_upload(run_id, relative_path):
        captured_paths.append(relative_path)
        return {
            "signedUrl": f"https://storage.example/upload/{relative_path}?token=signed-upload-token",
            "token": "signed-upload-token",
            "objectPath": f"labor-runs/test/{run_id}/{relative_path}",
            "relativePath": relative_path,
        }

    monkeypatch.setattr(app_module, "create_labor_supabase_signed_upload", fake_signed_upload)
    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "OSI", "period_start": "2026-06-08", "period_end": "2026-06-14"},
    ).json()

    response = client.post(
        f"/api/labor/runs/{run['id']}/direct-upload-plan",
        json={
            "pdfFiles": [{"name": "供应商发票 01.pdf", "size": 6_000_000, "type": "application/pdf"}],
            "workbookFiles": [{"name": "员工账单明细 - 2026-06-23T105500.333.xlsx", "size": 10_000, "type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}],
        },
    )

    assert response.status_code == 200
    uploads = response.json()["uploads"]
    assert uploads[0]["originalFilename"] == "供应商发票 01.pdf"
    assert uploads[1]["originalFilename"] == "员工账单明细 - 2026-06-23T105500.333.xlsx"
    assert all(path.isascii() for path in captured_paths)
    assert captured_paths[0].startswith("01_direct_")
    assert captured_paths[1].startswith("2026-06-23T105500_333_direct_")
    assert not any("供应商" in path or "员工账单" in path for path in captured_paths)


def test_labor_direct_upload_complete_registers_synced_files(monkeypatch):
    monkeypatch.setattr(app_module, "labor_supabase_storage_enabled", lambda: True)
    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "OSI", "period_start": "2026-06-08", "period_end": "2026-06-14"},
    ).json()

    def fake_sync(run_id, run_dir):
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "invoice.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
        workbook = Workbook()
        workbook.active.append(["员工", "金额"])
        workbook.save(run_dir / "bill.xlsx")
        return True

    monkeypatch.setattr(app_module, "sync_labor_run_from_persistent", fake_sync)

    response = client.post(
        f"/api/labor/runs/{run['id']}/direct-upload-complete",
        json={
            "uploads": [
                {
                    "group": "pdfInvoices",
                    "filename": "invoice.pdf",
                    "originalFilename": "invoice.pdf",
                    "relativePath": "invoice.pdf",
                    "size": 6_000_000,
                },
                {
                    "group": "workbooks",
                    "filename": "bill.xlsx",
                    "originalFilename": "bill.xlsx",
                    "relativePath": "bill.xlsx",
                    "size": 10_000,
                },
            ]
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "已上传文件"
    assert body["files"]["pdfInvoices"][0]["originalFilename"] == "invoice.pdf"
    assert body["files"]["workbooks"][0]["filename"] == "bill.xlsx"
    assert body["files"]["workbook"]["filename"] == "bill.xlsx"


def test_labor_access_gate_can_disable_uat_module(monkeypatch):
    monkeypatch.setenv("SIGMA_OVERSEAS_LABOR_ACCESS", "disabled")
    client = TestClient(app)

    blocked = client.get("/api/labor/runs")
    access = client.get("/api/labor/access")

    assert access.status_code == 200
    assert access.json()["canUse"] is False
    assert blocked.status_code == 403
    assert blocked.json()["access"]["access"] == "disabled"


def test_labor_extract_is_blocked_in_vercel_uat_light_mode(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("SIGMA_OVERSEAS_LABOR_ACCESS", "uat")
    monkeypatch.setenv("SIGMA_WORKBENCH_HOME", "/tmp/sigma-workbench")
    monkeypatch.setenv("SIGMA_LABOR_STORAGE_BACKEND", "blob")
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "vercel_blob_rw_qqD75P7a2QuwEh0S_abcd1234")
    monkeypatch.setattr(
        app_module,
        "_labor_metadata_or_404",
        lambda run_id: (_ for _ in ()).throw(
            app_module.HTTPException(status_code=404, detail="metadata read should not happen")
        ),
    )
    client = TestClient(app)

    response = client.post("/api/labor/runs/labor_synthetic/extract-and-compare")

    assert response.status_code == 409
    assert "Vercel UAT" in response.json()["detail"]["message"]
    assert "测试材料验证" in response.json()["detail"]["message"]


def test_labor_extract_vercel_uat_light_mode_returns_structured_next_action(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("SIGMA_OVERSEAS_LABOR_ACCESS", "uat")
    monkeypatch.setenv("SIGMA_LABOR_STORAGE_BACKEND", "blob")
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "vercel_blob_rw_qqD75P7a2QuwEh0S_abcd1234")
    client = TestClient(app)

    response = client.post("/api/labor/runs/labor_synthetic/extract-and-compare")

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["errorCode"] == "LABOR_UAT_EXTRACT_DISABLED"
    assert detail["retryable"] is False
    assert "Vercel UAT" in detail["message"]
    assert "测试材料验证" in detail["nextAction"]


def test_labor_upload_missing_run_returns_structured_next_action():
    client = TestClient(app)

    response = client.post(
        "/api/labor/runs/labor_missing/files",
        files=[
            ("pdf_files", ("scan.pdf", b"%PDF-1.4\n", "application/pdf")),
            ("workbook_files", ("账单.xlsx", _excel_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
        ],
    )

    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["errorCode"] == "LABOR_RUN_NOT_FOUND"
    assert detail["retryable"] is False
    assert detail["requiresReupload"] is True
    assert "批次记录未找到" in detail["message"]
    assert "新建核对批次" in detail["nextAction"]


def test_labor_download_recovers_nested_blob_report_by_metadata(monkeypatch):
    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "Blob Supplier", "period_start": "2026-05-11", "period_end": "2026-05-17", "currency": "USD"},
    ).json()
    run_dir = app_module.get_labor_run_dir(run["id"])
    report_path = run_dir / "reports" / "business.html"
    app_module.update_labor_metadata(
        run["id"],
        {
            "files": {
                "businessReport": {
                    "filename": "business.html",
                    "path": str(report_path),
                    "downloadUrl": f"/api/labor/runs/{run['id']}/download/business.html",
                }
            },
            "businessReportDownloadUrl": f"/api/labor/runs/{run['id']}/download/business.html",
        },
    )

    monkeypatch.setattr(app_module, "labor_blob_storage_enabled", lambda: True)

    def fake_sync_from_blob(run_id: str, target_dir: Path) -> bool:
        restored_report = target_dir / "reports" / "business.html"
        restored_report.parent.mkdir(parents=True, exist_ok=True)
        restored_report.write_text("<html>business report</html>", encoding="utf-8")
        return True

    monkeypatch.setattr(app_module, "sync_labor_run_from_blob", fake_sync_from_blob)

    response = client.get(f"/api/labor/runs/{run['id']}/download/business.html")

    assert response.status_code == 200
    assert response.text == "<html>business report</html>"


def test_labor_download_returns_structured_restore_failure_when_blob_sync_fails(monkeypatch):
    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "Blob Supplier", "period_start": "2026-05-11", "period_end": "2026-05-17", "currency": "USD"},
    ).json()
    run_dir = app_module.get_labor_run_dir(run["id"])
    report_path = run_dir / "reports" / "business.html"
    app_module.update_labor_metadata(
        run["id"],
        {
            "files": {
                "businessReport": {
                    "filename": "business.html",
                    "path": str(report_path),
                    "downloadUrl": f"/api/labor/runs/{run['id']}/download/business.html",
                }
            },
            "businessReportDownloadUrl": f"/api/labor/runs/{run['id']}/download/business.html",
        },
    )

    monkeypatch.setattr(app_module, "labor_blob_storage_enabled", lambda: True)
    monkeypatch.setattr(app_module, "sync_labor_run_from_blob", lambda run_id, target_dir: False)

    response = client.get(f"/api/labor/runs/{run['id']}/download/business.html")

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["errorCode"] == "LABOR_REPORT_RESTORE_FAILED"
    assert detail["retryable"] is True
    assert detail["requiresReupload"] is False
    assert "报告文件暂时无法恢复" in detail["message"]
    assert "稍后重试" in detail["nextAction"]
    assert "reports/business.html" not in str(detail)


def test_labor_download_masks_blob_restore_exception_details(monkeypatch):
    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "Blob Supplier", "period_start": "2026-05-11", "period_end": "2026-05-17", "currency": "USD"},
    ).json()
    run_dir = app_module.get_labor_run_dir(run["id"])
    report_path = run_dir / "reports" / "business.html"
    app_module.update_labor_metadata(
        run["id"],
        {
            "files": {
                "businessReport": {
                    "filename": "business.html",
                    "path": str(report_path),
                    "downloadUrl": f"/api/labor/runs/{run['id']}/download/business.html",
                }
            },
            "businessReportDownloadUrl": f"/api/labor/runs/{run['id']}/download/business.html",
        },
    )

    monkeypatch.setattr(app_module, "labor_blob_storage_enabled", lambda: True)

    def raise_sensitive_restore_error(run_id: str, target_dir: Path) -> bool:
        raise RuntimeError(f"token=secret-token path={target_dir / 'reports' / 'business.html'}")

    monkeypatch.setattr(app_module, "sync_labor_run_from_blob", raise_sensitive_restore_error)

    response = client.get(f"/api/labor/runs/{run['id']}/download/business.html")

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["errorCode"] == "LABOR_REPORT_RESTORE_FAILED"
    assert detail["retryable"] is True
    assert "报告文件暂时无法恢复" in detail["message"]
    response_body = str(detail)
    assert "secret-token" not in response_body
    assert "reports/business.html" not in response_body
    assert str(run_dir) not in response_body


def test_labor_download_returns_structured_missing_file_error():
    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "Local Supplier", "period_start": "2026-05-11", "period_end": "2026-05-17", "currency": "USD"},
    ).json()
    run_dir = app_module.get_labor_run_dir(run["id"])
    missing_report_path = run_dir / "reports" / "business.html"
    app_module.update_labor_metadata(
        run["id"],
        {
            "files": {
                "businessReport": {
                    "filename": "business.html",
                    "path": str(missing_report_path),
                    "downloadUrl": f"/api/labor/runs/{run['id']}/download/business.html",
                }
            },
            "businessReportDownloadUrl": f"/api/labor/runs/{run['id']}/download/business.html",
        },
    )

    response = client.get(f"/api/labor/runs/{run['id']}/download/business.html")

    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["errorCode"] == "LABOR_REPORT_FILE_MISSING"
    assert detail["retryable"] is False
    assert detail["requiresReupload"] is False
    assert detail["requiresHumanReview"] is True
    assert "报告文件不存在或已被清理" in detail["message"]
    assert "重新生成报告" in detail["nextAction"]
    assert "reports/business.html" not in str(detail)


def test_labor_runs_list_uses_bounded_recent_metadata(monkeypatch):
    observed: dict[str, object] = {}

    def fake_list_labor_metadata(*, limit=None) -> list[dict]:
        observed["limit"] = limit
        return [
            {
                "id": "labor_recent",
                "status": "已生成差异报告",
                "supplierName": "Synthetic Supplier",
                "updatedAt": "2026-06-20T10:00:00",
                "comparisonSummary": {"exceptionCount": 1},
                "comparisonRows": [{"employeeName": "Synthetic Worker"}],
                "pdfExtractedRows": [{"employeeNameRaw": "Synthetic Worker"}],
                "excelRows": [{"employeeNameRaw": "Synthetic Worker"}],
            }
        ]

    monkeypatch.setattr(app_module, "list_labor_metadata", fake_list_labor_metadata)
    client = TestClient(app)

    response = client.get("/api/labor/runs")

    assert response.status_code == 200
    assert response.json()["runs"] == [
        {
            "id": "labor_recent",
            "status": "已生成差异报告",
            "supplierName": "Synthetic Supplier",
            "periodStart": "",
            "periodEnd": "",
            "currency": "",
            "createdAt": "",
            "updatedAt": "2026-06-20T10:00:00",
            "stage": "",
            "diffDownloadUrl": "",
            "comparisonSummary": {"exceptionCount": 1},
            "readinessGate": {},
        }
    ]
    assert observed["limit"] == 50


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
            ("workbook_files", ("账单.xlsx", _excel_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
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
        json={
            "sheet_name": "员工账单",
            "mapping": {"name": "姓名", "hours": "时长总计(H)", "amount": "费用总计(含税)", "currency": "币种"},
            "manualNameMapping": {"Gamboa, Arilene": "Arlene Gamboa"},
        },
    )
    assert mapping.status_code == 200
    assert mapping.json()["excelMapping"]["name"] == "姓名"
    assert mapping.json()["manualNameMapping"]["Gamboa, Arilene"] == "Arlene Gamboa"


def test_labor_extract_before_upload_tells_user_to_upload_files_first():
    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={
            "supplier_name": "Fairway Staffing Service",
            "period_start": "2026-05-11",
            "period_end": "2026-05-17",
            "currency": "USD",
        },
    ).json()

    response = client.post(f"/api/labor/runs/{run['id']}/extract-and-compare")

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["errorCode"] == "LABOR_FILES_REQUIRED"
    assert detail["requiresReupload"] is True
    assert "请先上传本期 PDF 发票、Excel 账单" in detail["message"]
    assert "上传文件" in detail["nextAction"]


def test_labor_extract_after_upload_without_mapping_tells_user_to_confirm_mapping():
    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={
            "supplier_name": "Fairway Staffing Service",
            "period_start": "2026-05-11",
            "period_end": "2026-05-17",
            "currency": "USD",
        },
    ).json()
    upload = client.post(
        f"/api/labor/runs/{run['id']}/files",
        files=[
            ("pdf_files", ("invoice.pdf", b"%PDF-1.4\n% sample", "application/pdf")),
            ("workbook_files", ("账单.xlsx", _excel_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
        ],
    )
    assert upload.status_code == 200

    response = client.post(f"/api/labor/runs/{run['id']}/extract-and-compare")

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["errorCode"] == "LABOR_MAPPING_REQUIRED"
    assert detail.get("requiresReupload") is False
    assert "请先确认 Excel 工作表和字段映射" in detail["message"]
    assert "字段映射" in detail["nextAction"]


def test_labor_material_index_api_lists_replay_ready_batches(tmp_path):
    batch = tmp_path / "oss 2"
    batch.mkdir()
    (batch / "US Elogis Service #7 Invoice W.E 05.24.26.pdf").write_bytes(b"%PDF-1.4\n")
    (batch / "员工账单明细 - 2026-06-04T094719.972.xlsx").write_bytes(b"fake workbook")
    (tmp_path / "handover").mkdir()
    (tmp_path / "handover" / "README_RECONCILIATION_METHOD.md").write_text("method", encoding="utf-8")

    client = TestClient(app)
    response = client.get("/api/labor/material-index", params={"root": str(tmp_path)})

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["candidateBatchCount"] == 1
    assert body["summary"]["suppliers"] == ["oss"]
    assert body["batches"] == body["candidateBatches"]
    assert body["candidateBatches"][0]["warehouseIds"] == ["7"]
    assert body["candidateBatches"][0]["invoicePdfCount"] == 1
    assert body["candidateBatches"][0]["workbookCount"] == 1
    assert body["candidateBatches"][0]["pdfFiles"] == body["candidateBatches"][0]["invoiceFiles"]


def test_labor_material_replay_plan_api_returns_mapping_candidates(tmp_path):
    batch = tmp_path / "workforce已报账"
    batch.mkdir()
    (batch / "Invoice-5058871.pdf").write_bytes(b"%PDF-1.4\n")
    (batch / "员工账单明细 - 2026-06-01T112149.990.xlsx").write_bytes(_excel_bytes())

    client = TestClient(app)
    response = client.get(
        "/api/labor/material-replay-plan",
        params={"root": str(tmp_path), "batchKey": "workforce已报账"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["planCount"] == 1
    plan = body["plans"][0]
    assert plan["supplier"] == "workforce"
    assert plan["uploadPlan"]["pdfFiles"] == ["workforce已报账/Invoice-5058871.pdf"]
    assert plan["mappingCandidates"][0]["sheetName"] == "员工账单"
    assert plan["mappingCandidates"][0]["suggestedMapping"]["name"] == "姓名"
    assert plan["mappingCandidates"][0]["suggestedMapping"]["amount"] == "费用总计(含税)"
    assert plan["replayReady"] is True


def test_labor_material_dry_run_api_does_not_create_labor_run(monkeypatch, tmp_path):
    import bonus_platform.app as app_module

    before_count = len(app_module.list_labor_metadata())
    monkeypatch.setattr(
        app_module,
        "build_material_dry_run",
        lambda root, batch_key, **kwargs: {
            "decision": "dry_run_only",
            "mode": "deterministic_first_no_write",
            "batchKey": batch_key,
            "supplier": "oss",
            "summary": {"pdfRowCount": 1, "excelRowCount": 1},
            "writesRun": False,
            "aiInvoked": False,
        },
    )

    client = TestClient(app)
    response = client.post(
        "/api/labor/material-dry-run",
        json={"root": str(tmp_path), "batchKey": "oss_2"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "dry_run_only"
    assert body["writesRun"] is False
    assert body["aiInvoked"] is False
    assert len(app_module.list_labor_metadata()) == before_count


def test_labor_material_run_api_copies_reference_files_and_prefills_mapping(tmp_path):
    batch = tmp_path / "workforce已报账"
    batch.mkdir()
    pdf_path = batch / "Invoice-5058871.pdf"
    workbook_path = batch / "员工账单明细 - 2026-06-01T112149.990.xlsx"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    workbook_path.write_bytes(_excel_bytes())
    cache_dir = batch / ".ai_extract_cache"
    cache_dir.mkdir()
    (cache_dir / "Invoice-5058871_p1_mimo-v2.5_v4.json").write_text(
        json.dumps([{"employee_name_raw": "Alice Worker", "amount": 100, "source_page": 1}]),
        encoding="utf-8",
    )

    client = TestClient(app)
    response = client.post(
        "/api/labor/material-runs",
        json={
            "root": str(tmp_path),
            "batchKey": "workforce已报账",
            "periodStart": "2026-05-11",
            "periodEnd": "2026-05-17",
            "currency": "USD",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "已确认字段"
    assert body["supplierName"] == "workforce"
    assert body["periodStart"] == "2026-05-11"
    assert body["periodEnd"] == "2026-05-17"
    assert body["workbookSheet"] == "员工账单"
    assert body["excelMapping"]["name"] == "姓名"
    assert body["excelMapping"]["amount"] == "费用总计(含税)"
    assert body["materialReplayNextStep"]["action"] == "extract_compare"
    assert body["materialReplayNextStep"]["enabled"] is True
    assert "可直接执行抽取核对" in body["materialReplayNextStep"]["description"]
    assert body["materialReplaySource"]["batchKey"] == "workforce已报账"
    assert body["materialReplaySource"]["uploadPlan"]["pdfFiles"] == ["workforce已报账/Invoice-5058871.pdf"]
    assert body["files"]["pdfInvoices"][0]["filename"].endswith(".pdf")
    assert body["files"]["workbooks"][0]["filename"].endswith(".xlsx")
    copied_pdf = Path(body["files"]["pdfInvoices"][0]["path"])
    copied_workbook = Path(body["files"]["workbooks"][0]["path"])
    assert copied_pdf.exists()
    assert copied_workbook.exists()
    assert copied_pdf != pdf_path
    assert copied_workbook != workbook_path
    assert pdf_path.exists()
    assert workbook_path.exists()
    copied_cache = copied_pdf.parent / ".ai_extract_cache" / f"{copied_pdf.stem}_p1_mimo-v2.5_v4.json"
    assert copied_cache.exists()
    assert "Alice Worker" in copied_cache.read_text(encoding="utf-8")


def test_labor_material_run_extracts_and_replays_name_mapping_candidate(monkeypatch, tmp_path):
    import bonus_platform.app as app_module

    batch = tmp_path / "29仓"
    batch.mkdir()
    (batch / "In291943.pdf").write_bytes(b"%PDF-1.4\n")
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "员工账单"
    sheet.append(["工号", "姓名", "时长总计(H)", "费用总计(含税)", "币种", "物理仓"])
    sheet.append(["WUS040020", "Deisi Pozo", 37.84, 847.84, "USD", "29号仓"])
    buffer = BytesIO()
    workbook.save(buffer)
    (batch / "员工账单明细 - 2026-05-28T141945.414.xlsx").write_bytes(buffer.getvalue())

    monkeypatch.setattr(
        app_module,
        "quick_extract_totals",
        lambda paths, config, supplier="": [{"source_file": paths[0].name, "total_amount": 900.0, "warehouse_id": "29"}],
    )
    monkeypatch.setattr(
        app_module,
        "extract_invoice_items",
        lambda paths, config, **kwargs: [
            LaborLineItem(source_type="pdf_invoice", source_file=paths[0].name, source_page_or_row="p1", employee_id="", employee_name_raw="Rozo Panche, Deisy V", hours=37.84, amount=847.84, currency="USD", confidence=0.98, evidence_text="Rozo Panche, Deisy V 37.84 $847.84")
        ],
    )

    client = TestClient(app)
    run = client.post(
        "/api/labor/material-runs",
        json={
            "root": str(tmp_path),
            "batchKey": "29仓",
            "supplierName": "29仓",
            "periodStart": "2026-05-18",
            "periodEnd": "2026-05-24",
            "currency": "USD",
        },
    ).json()

    compared = app_module._perform_labor_extract_compare(run["id"])

    candidates = compared["nameMappingGovernance"]["candidates"]
    assert compared["comparisonSummary"]["candidateMatchCount"] == 1
    assert len(candidates) == 1
    summary = compared["nameMappingGovernance"]["summary"]
    assert summary["candidateCount"] == 1
    assert summary["readyToReplayCount"] == 1
    assert summary["projectedFixedExceptionCount"] == 2
    candidate = candidates[0]
    assert candidate["cacheEmployeeName"] == "Rozo Panche, Deisy V"
    assert candidate["excelEmployeeName"] == "Deisi Pozo"
    assert candidate["confidence"] == "high"
    assert candidate["decision"] == "candidate_only"
    assert candidate["projectedFixedExceptionCount"] == 2
    assert candidate["matchReason"] == "姓名相似且金额/工时一致"
    assert "是否确认 PDF 名称 Rozo Panche, Deisy V 对应 Excel 员工 Deisi Pozo" in candidate["businessQuestion"]
    assert candidate["impactSummary"] == "金额和工时均一致"
    assert "必须预览影响" in candidate["cannotAutoResolveReason"]

    replay = client.post(
        f"/api/labor/runs/{run['id']}/name-mapping-candidates/{candidate['candidateId']}/auto-replay",
        json={"limit": 10},
    )

    assert replay.status_code == 200
    replay_body = replay.json()
    assert replay_body["decision"] == "ready_for_user_confirmation"
    assert replay_body["summary"]["fixedCount"] == 1
    assert replay_body["summary"]["regressionCount"] == 0

    confirmed = client.post(
        f"/api/labor/runs/{run['id']}/name-mapping-candidates/{candidate['candidateId']}/confirm",
        json={"confirmedBy": "ops-user", "reason": "material run replay passed", "recalculate": True},
    )

    assert confirmed.status_code == 200
    confirmed_body = confirmed.json()
    assert confirmed_body["manualNameMapping"] == {"Rozo Panche, Deisy V": "Deisi Pozo"}
    assert confirmed_body["recalculatedRun"]["status"] == "已生成差异报告"
    assert confirmed_body["recalculatedRun"]["comparisonSummary"]["exceptionCount"] == 0
    assert confirmed_body["recalculatedRun"]["diffDownloadUrl"]
    refreshed = client.get(f"/api/labor/runs/{run['id']}").json()
    assert refreshed["comparisonSummary"]["exceptionCount"] == 0
    assert refreshed["diffDownloadUrl"] == refreshed["files"]["diffReport"]["downloadUrl"]


def test_labor_material_run_name_mapping_candidate_with_amount_gap_requires_review(monkeypatch, tmp_path):
    import bonus_platform.app as app_module

    batch = tmp_path / "29仓"
    batch.mkdir()
    (batch / "In291943.pdf").write_bytes(b"%PDF-1.4\n")
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "员工账单"
    sheet.append(["工号", "姓名", "时长总计(H)", "费用总计(含税)", "币种", "物理仓"])
    sheet.append(["WUS033570", "Freddy Moran (MOR47K)", 40.48, 830.72, "USD", "29号仓"])
    buffer = BytesIO()
    workbook.save(buffer)
    (batch / "员工账单明细 - 2026-05-28T141945.414.xlsx").write_bytes(buffer.getvalue())

    monkeypatch.setattr(
        app_module,
        "quick_extract_totals",
        lambda paths, config, supplier="": [{"source_file": paths[0].name, "total_amount": 1042.43, "warehouse_id": "29"}],
    )
    monkeypatch.setattr(
        app_module,
        "extract_invoice_items",
        lambda paths, config, **kwargs: [
            LaborLineItem(source_type="pdf_invoice", source_file=paths[0].name, source_page_or_row="p1", employee_id="", employee_name_raw="Moran Treminio, Freddy", hours=40.48, amount=1042.43, currency="USD", confidence=0.98, evidence_text="Moran Treminio, Freddy 40.48 $1042.43")
        ],
    )

    client = TestClient(app)
    run = client.post(
        "/api/labor/material-runs",
        json={
            "root": str(tmp_path),
            "batchKey": "29仓",
            "supplierName": "29仓",
            "periodStart": "2026-05-18",
            "periodEnd": "2026-05-24",
            "currency": "USD",
        },
    ).json()

    compared = app_module._perform_labor_extract_compare(run["id"])

    candidates = compared["nameMappingGovernance"]["candidates"]
    assert compared["comparisonSummary"]["candidateMatchCount"] == 1
    assert compared["comparisonSummary"]["exceptionCount"] == 1
    assert len(candidates) == 1
    summary = compared["nameMappingGovernance"]["summary"]
    assert summary["candidateCount"] == 1
    assert summary["readyToReplayCount"] == 0
    assert summary["projectedFixedExceptionCount"] == 0
    assert summary["amountStillDifferentCount"] == 1
    candidate = candidates[0]
    assert candidate["cacheEmployeeName"] == "Moran Treminio, Freddy"
    assert candidate["excelEmployeeName"] == "Freddy Moran (MOR47K)"
    assert candidate["confidence"] == "medium"
    assert candidate["projectedFixedExceptionCount"] == 0
    assert candidate["matchReason"] == "姓名相似，但金额或工时仍需复核"
    assert "需先复核差异口径" in candidate["businessQuestion"]
    assert "PDF 高于 Excel" in candidate["impactSummary"]
    assert "不能直接确认匹配" in candidate["cannotAutoResolveReason"]

    replay = client.post(
        f"/api/labor/runs/{run['id']}/name-mapping-candidates/{candidate['candidateId']}/auto-replay",
        json={"limit": 10},
    )
    assert replay.status_code == 200
    replay_body = replay.json()
    assert replay_body["decision"] != "ready_for_user_confirmation"
    assert replay_body["summary"]["fixedCount"] == 0

    confirmed = client.post(
        f"/api/labor/runs/{run['id']}/name-mapping-candidates/{candidate['candidateId']}/confirm",
        json={"confirmedBy": "ops-user", "reason": "reviewed but amount still differs", "recalculate": True},
    )
    assert confirmed.status_code == 400


def test_labor_material_run_keeps_employee_detail_when_totals_pass(monkeypatch, tmp_path):
    import bonus_platform.app as app_module

    batch = tmp_path / "oss 2"
    batch.mkdir()
    (batch / "US Elogis Service #1 Invoice W.E 05.24.26.pdf").write_bytes(b"%PDF-1.4\n")
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "员工账单"
    sheet.append(["工号", "姓名", "时长总计(H)", "费用总计(含税)", "币种", "物理仓"])
    sheet.append(["WUS045753", "Manuel Lozano", 16.09, 361.42, "USD", "1号仓"])
    sheet.append(["WUS045746", "Massiel Castillo", 3.50, 78.40, "USD", "1号仓"])
    buffer = BytesIO()
    workbook.save(buffer)
    (batch / "员工账单明细 - 2026-06-04T094719.972.xlsx").write_bytes(buffer.getvalue())

    monkeypatch.setattr(
        app_module,
        "quick_extract_totals",
        lambda paths, config, supplier="": [{"source_file": paths[0].name, "total_amount": 439.82, "warehouse_id": "1"}],
    )
    monkeypatch.setattr(
        app_module,
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

    client = TestClient(app)
    run = client.post(
        "/api/labor/material-runs",
        json={
            "root": str(tmp_path),
            "batchKey": "oss_2",
            "supplierName": "oss",
            "periodStart": "2026-05-18",
            "periodEnd": "2026-05-24",
            "currency": "USD",
        },
    ).json()

    compared = app_module._perform_labor_extract_compare(run["id"])

    assert compared["warehouseComparison"]["summary"]["totalPassed"] is True
    assert compared["comparisonSummary"]["candidateMatchCount"] == 1
    assert compared["comparisonSummary"]["exceptionCount"] == 2
    assert compared["candidateMatches"][0]["issueType"] == "combined_pdf_row"
    combined = compared["combinedRowGovernance"]
    assert combined["summary"]["candidateCount"] == 1
    assert combined["summary"]["amountImpactTotal"] == 78.4
    assert combined["candidates"][0]["status"] == "pending_invoice_review"
    assert any("总金额已通过" in issue for issue in compared["extractionQuality"]["issues"])
    assert compared["diffDownloadUrl"]
    report_response = client.get(compared["diffDownloadUrl"])
    assert report_response.status_code == 200
    assert report_response.content


def test_labor_material_run_surfaces_amount_rate_review_queue(monkeypatch, tmp_path):
    import bonus_platform.app as app_module

    batch = tmp_path / "Grande"
    batch.mkdir()
    (batch / "Grande_Invoice_WH1.pdf").write_bytes(b"%PDF-1.4\n")
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "员工账单"
    sheet.append(["工号", "姓名", "时长总计(H)", "费用总计(含税)", "币种", "物理仓"])
    sheet.append(["WUS000501", "Alice Worker", 40.0, 1000.0, "USD", "1号仓"])
    buffer = BytesIO()
    workbook.save(buffer)
    (batch / "员工账单明细 - 2026-06-01T112149.990.xlsx").write_bytes(buffer.getvalue())

    monkeypatch.setattr(
        app_module,
        "quick_extract_totals",
        lambda paths, config, supplier="": [{"source_file": paths[0].name, "total_amount": 1040.0, "warehouse_id": "1"}],
    )
    monkeypatch.setattr(
        app_module,
        "extract_invoice_items",
        lambda paths, config, **kwargs: [
            LaborLineItem(
                source_type="pdf_invoice",
                source_file=paths[0].name,
                source_page_or_row="p1",
                employee_id="WUS000501",
                employee_name_raw="Alice Worker",
                hours=40.0,
                amount=1040.0,
                currency="USD",
                confidence=0.98,
                evidence_text="Alice Worker 40.00 $1040.00",
            )
        ],
    )

    client = TestClient(app)
    run = client.post(
        "/api/labor/material-runs",
        json={
            "root": str(tmp_path),
            "batchKey": "Grande",
            "supplierName": "Grande",
            "periodStart": "2026-05-18",
            "periodEnd": "2026-05-24",
            "currency": "USD",
        },
    ).json()

    compared = app_module._perform_labor_extract_compare(run["id"])

    assert compared["comparisonSummary"]["exceptionCount"] == 1
    assert compared["comparisonRows"][0]["matchStatus"] == "金额差异"
    assert compared["reviewQueues"]["primary"] == "amount_rate_review"
    amount_queue = compared["reviewQueues"]["amountRateReview"]
    assert amount_queue["count"] == 1
    assert amount_queue["reviewMode"] == "amount_basis"
    assert amount_queue["businessQuestion"] == "工时已经对齐，金额差来自费率、加班、服务费还是税费口径？"
    assert amount_queue["rows"][0]["employeeName"] == "Alice Worker"
    assert amount_queue["rows"][0]["reviewFocus"] == "先核金额口径"
    assert amount_queue["rows"][0]["amountDirectionLabel"] == "PDF 高于 Excel"
    assert "确认前不能由系统自动改金额或清账" in amount_queue["cannotAutoResolveReason"]
    assert compared["diffDownloadUrl"]
    report_response = client.get(compared["diffDownloadUrl"])
    assert report_response.status_code == 200
    assert report_response.content
    refreshed = client.get(f"/api/labor/runs/{run['id']}").json()
    assert refreshed["reviewQueues"]["primary"] == "amount_rate_review"
    assert refreshed["readinessGate"]["status"] == "blocked"
    assert refreshed["readinessGate"]["summary"]["exceptionCount"] == 1
    assert refreshed["readinessGate"]["issues"][0]["code"] == "comparison_exceptions"


def test_labor_material_run_degrades_to_reocr_review_when_ai_extraction_unavailable(monkeypatch, tmp_path):
    import bonus_platform.app as app_module

    batch = tmp_path / "oss"
    batch.mkdir()
    (batch / "elog1-1_20260520204104.pdf").write_bytes(b"%PDF-1.4\n")
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "员工账单"
    sheet.append(["工号", "姓名", "时长总计(H)", "费用总计(含税)", "币种", "物理仓"])
    sheet.append(["WUS045751", "Massiel Castillo", 30.92, 100.00, "USD", "1号仓"])
    buffer = BytesIO()
    workbook.save(buffer)
    (batch / "员工账单明细 - 2026-05-27T110404.877.xlsx").write_bytes(buffer.getvalue())

    ai_cache_audit = {
        "decision": "candidate_only",
        "requiresConfirmation": True,
        "summary": {"fileCount": 1, "candidateFileCount": 1, "candidateAmountTotal": 100.0},
        "files": [],
    }
    ai_cache_preview = {
        "decision": "candidate_only",
        "requiresConfirmation": True,
        "summary": {
            "candidateRowCount": 1,
            "excelRowCount": 1,
            "passedCount": 0,
            "exceptionCount": 1,
            "cacheAmountTotal": 100,
            "excelAmountTotal": 100,
            "amountDeltaTotal": 0,
            "matchRate": 0,
            "reviewableFileCount": 0,
            "needsReocrFileCount": 1,
        },
        "fileQuality": [],
        "rows": [],
        "exceptionRows": [],
        "candidateMatches": [],
    }
    reocr_plan = {
        "decision": "candidate_only",
        "requiresConfirmation": True,
        "summary": {"taskCount": 1, "reviewableCandidateCount": 0, "totalExpectedExcelAmount": 100.0, "totalCurrentCacheAmount": 100.0},
        "tasks": [
            {
                "sourceFile": "elog1-1_20260520204104.pdf",
                "warehouseId": "1",
                "expectedExcelAmount": 100.0,
                "amountDelta": 0.0,
                "diagnostics": {
                    "suspectedNamePairs": [
                        {
                            "cacheEmployeeName": "Espinosa Manuel",
                            "excelEmployeeName": "Massiel Castillo",
                            "amountGap": 0.0,
                            "hoursGap": -0.02,
                            "sourceRefs": "elog1 p1; workbook row 2",
                            "cacheAmount": 100,
                            "excelAmount": 100,
                            "cacheHours": 30.90,
                            "excelHours": 30.92,
                        }
                    ]
                },
            }
        ],
        "reviewableCandidates": [],
    }

    monkeypatch.setattr(
        app_module,
        "quick_extract_totals",
        lambda paths, config, supplier="": [{"source_file": paths[0].name, "total_amount": 0.0, "warehouse_id": "1"}],
    )
    monkeypatch.setattr(app_module, "audit_ai_page_cache_candidates", lambda *args, **kwargs: ai_cache_audit)
    monkeypatch.setattr(app_module, "build_ai_cache_reconciliation_preview", lambda *args, **kwargs: ai_cache_preview)
    monkeypatch.setattr(app_module, "build_reocr_candidate_plan", lambda *args, **kwargs: reocr_plan)
    monkeypatch.setattr(app_module, "extract_invoice_items", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("AI 抽取失败：network unavailable")))

    client = TestClient(app)
    run = client.post(
        "/api/labor/material-runs",
        json={
            "root": str(tmp_path),
            "batchKey": "oss",
            "supplierName": "oss",
            "periodStart": "2026-05-11",
            "periodEnd": "2026-05-17",
            "currency": "USD",
        },
    ).json()

    updated = app_module._perform_labor_extract_compare(run["id"])

    assert updated["status"] == "待图片识别复核"
    assert updated["files"]["diffReport"]["filename"].endswith(".xlsx")
    assert updated["comparisonSummary"]["exceptionCount"] == 1
    assert updated["extractionQuality"]["level"] == "critical"
    assert any("AI 抽取失败" in issue for issue in updated["extractionQuality"]["issues"])
    assert updated["aiCacheAudit"] == ai_cache_audit
    assert updated["aiCacheReconciliationPreview"] == ai_cache_preview
    assert updated["reocrPlan"] == reocr_plan
    candidate = updated["nameMappingGovernance"]["candidates"][0]
    assert candidate["cacheEmployeeName"] == "Espinosa Manuel"
    assert candidate["excelEmployeeName"] == "Massiel Castillo"
    assert candidate["decision"] == "candidate_only"
    assert candidate["requiresConfirmation"] is True
    assert updated["diffDownloadUrl"] == updated["files"]["diffReport"]["downloadUrl"]


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
            ("workbook_files", ("账单.xlsx", _excel_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
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


def test_labor_recover_stuck_run_marks_retryable_system_interruption(monkeypatch):
    import bonus_platform.app as app_module

    captured: dict[str, dict] = {}
    monkeypatch.setattr(app_module, "list_labor_metadata", lambda: [{"id": "labor_stuck", "status": "抽取中"}])
    monkeypatch.setattr(
        app_module,
        "update_labor_metadata",
        lambda run_id, updates: captured.setdefault(run_id, updates),
    )

    app_module._recover_stuck_labor_runs()

    updates = captured["labor_stuck"]
    assert updates["status"] == "抽取失败"
    assert updates["stage"] == "系统中断"
    assert updates["failureType"] == "system_interrupted"
    assert updates["errorCode"] == "LABOR_EXTRACT_INTERRUPTED"
    assert updates["retryable"] is True
    assert updates["requiresReupload"] is False
    assert updates["requiresHumanReview"] is False
    assert "重新点击" in updates["nextAction"]
    assert "服务器已重启" in updates["errorMessage"]


def test_labor_recover_stuck_run_does_not_block_startup_when_storage_fails(monkeypatch):
    import bonus_platform.app as app_module

    def fail_listing():
        raise RuntimeError("supabase storage unavailable")

    monkeypatch.setattr(app_module, "list_labor_metadata", fail_listing)
    monkeypatch.setattr(
        app_module,
        "update_labor_metadata",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("no rows should be updated")),
    )

    app_module._recover_stuck_labor_runs()


def test_labor_compare_falls_back_to_all_pdfs_when_diff_warehouse_cannot_map(monkeypatch):
    import bonus_platform.app as app_module

    captured_paths = []

    monkeypatch.setattr(
        app_module,
        "quick_extract_totals",
        lambda *args, **kwargs: [{"source_file": "Invoice-5058871.pdf", "total_amount": 50, "warehouse_id": ""}],
    )
    monkeypatch.setattr(app_module, "_warehouse_id_from_text_path", lambda *args, **kwargs: False)

    def fake_extract(pdf_paths, *args, **kwargs):
        captured_paths.extend([Path(p).name for p in pdf_paths])
        return [
            LaborLineItem(
                source_type="pdf_invoice",
                source_file="Invoice-5058871.pdf",
                source_page_or_row="p1",
                employee_id="",
                employee_name_raw="Alice Worker",
                hours=8,
                amount=100,
                currency="USD",
                confidence=0.95,
                evidence_text="Total $100",
            )
        ]

    monkeypatch.setattr(app_module, "extract_invoice_items", fake_extract)
    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "Invoice", "period_start": "2026-05-11", "period_end": "2026-05-17", "currency": "USD"},
    ).json()
    client.post(
        f"/api/labor/runs/{run['id']}/files",
        files=[
            ("pdf_files", ("Invoice-5058871.pdf", b"%PDF-1.4\n", "application/pdf")),
            ("pdf_files", ("Invoice-5058872.pdf", b"%PDF-1.4\n", "application/pdf")),
            ("workbook_files", ("账单.xlsx", _excel_bytes_with_warehouse(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
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
    assert len(captured_paths) == 2
    assert all(name.startswith(("Invoice-5058871_", "Invoice-5058872_")) for name in captured_paths)
    assert any("无法将异常仓库映射到具体 PDF" in issue for issue in body["extractionQuality"]["issues"])


def test_labor_rule_extraction_reads_wage_code_invoice_rows():
    from bonus_platform.engine.labor.extract import _extract_wage_code_invoice_rows

    rows = _extract_wage_code_invoice_rows(
        {
            "source_file": "Invoice-5058871.pdf",
            "page": 1,
            "text": """
Reference
Employee
Wage Code
Type
Hours
Rate
Amount
Aguilar, Hortensia
Reg
REG
40.00
22.58
$903.20
Aguilar, Hortensia
Reg
OT
1.40
33.86
$47.40
Customer ID
Invoice Number
5058871
""",
        },
        supplier="Invoice",
        period_start="2026-05-17",
        period_end="2026-05-22",
        currency="USD",
    )

    assert len(rows) == 2
    assert rows[0].employee_name_raw == "Aguilar, Hortensia"
    assert rows[0].hours == 40
    assert rows[0].amount == 903.20
    assert rows[1].hours == 1.4
    assert rows[1].amount == 47.40


def test_labor_rule_extraction_combines_wrapped_wage_code_names():
    from bonus_platform.engine.labor.extract import _extract_wage_code_invoice_rows

    rows = _extract_wage_code_invoice_rows(
        {
            "source_file": "Invoice-5058877.pdf",
            "page": 1,
            "text": """
ROSEL DUARTE, YAIR
GUILLERMO
Reg
REG
40.00
22.58
$903.20
ROSEL DUARTE, YAIR
GUILLERMO
Reg
OT
0.97
33.86
$32.84
""",
        },
        supplier="Invoice",
        period_start="2026-05-17",
        period_end="2026-05-22",
        currency="USD",
    )

    assert len(rows) == 2
    assert {row.employee_name_raw for row in rows} == {"ROSEL DUARTE, YAIR GUILLERMO"}
    assert round(sum(row.amount for row in rows), 2) == 936.04


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
            ("workbook_files", ("账单.xlsx", _excel_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
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


def test_labor_compare_persists_diagnostics_and_ai_cache_audit_in_report_flow(monkeypatch):
    import bonus_platform.app as app_module

    captured_report_kwargs = {}
    cost_summaries = [
        {
            "sourceFile": "otws.xlsx",
            "warehouseId": "1",
            "summary": {"reportedTotal": 100.0, "componentTotal": 100.0, "componentDelta": 0.0},
            "details": {"detailTotal": 100.0, "summaryDelta": 0.0},
        }
    ]
    ai_cache_audit = {
        "decision": "candidate_only",
        "requiresConfirmation": True,
        "summary": {"fileCount": 1, "candidateFileCount": 1, "candidateAmountTotal": 100.0},
        "files": [{"sourceFile": "invoice.pdf", "rowCount": 1, "candidateAmountTotal": 100.0}],
    }
    ai_cache_preview = {
        "decision": "candidate_only",
        "requiresConfirmation": True,
        "summary": {"needsReocrFileCount": 1, "reviewableFileCount": 0},
        "fileQuality": [
            {
                "sourceFile": "invoice.pdf",
                "warehouseId": "1",
                "decision": "needs_reocr",
                "cacheAmountTotal": 80.0,
                "excelAmountTotal": 100.0,
                "amountDelta": -20.0,
                "excelRowCount": 1,
                "recommendation": "历史识别金额与账单不一致，建议重新识别后预览影响。",
            }
        ],
    }
    reocr_plan = {
        "decision": "candidate_only",
        "requiresConfirmation": True,
        "summary": {"taskCount": 1, "reviewableCandidateCount": 0, "totalExpectedExcelAmount": 100.0, "totalCurrentCacheAmount": 80.0},
        "tasks": [{"sourceFile": "invoice.pdf", "warehouseId": "1", "expectedExcelAmount": 100.0, "amountDelta": -20.0}],
        "reviewableCandidates": [],
    }

    monkeypatch.setattr(
        app_module,
        "quick_extract_totals",
        lambda *args, **kwargs: [{"source_file": "invoice.pdf", "total_amount": 100, "warehouse_id": "1"}],
    )
    monkeypatch.setattr(app_module, "_labor_cost_summaries", lambda *args, **kwargs: cost_summaries)
    monkeypatch.setattr(app_module, "audit_ai_page_cache_candidates", lambda *args, **kwargs: ai_cache_audit)
    monkeypatch.setattr(app_module, "build_ai_cache_reconciliation_preview", lambda *args, **kwargs: ai_cache_preview)
    monkeypatch.setattr(app_module, "build_reocr_candidate_plan", lambda *args, **kwargs: reocr_plan)

    def fake_build_labor_report(*args, **kwargs):
        report_path = Path(args[0])
        report_path.write_bytes(b"report")
        captured_report_kwargs.update(kwargs)

    monkeypatch.setattr(app_module, "build_labor_report", fake_build_labor_report)

    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "SSS", "period_start": "2026-05-11", "period_end": "2026-05-17", "currency": "USD"},
    ).json()
    client.post(
        f"/api/labor/runs/{run['id']}/files",
        files=[
            ("pdf_files", ("invoice.pdf", b"%PDF-1.4\n", "application/pdf")),
            ("workbook_files", ("账单.xlsx", _excel_bytes_with_warehouse(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
        ],
    )
    client.post(
        f"/api/labor/runs/{run['id']}/mapping",
        json={"sheet_name": "员工账单", "mapping": {"employeeId": "工号", "name": "姓名", "hours": "时长总计(H)", "amount": "费用总计(含税)", "currency": "币种"}},
    )

    updated = app_module._perform_labor_extract_compare(run["id"])

    assert updated["status"] == "已生成差异报告"
    business_report = updated["files"]["businessReport"]
    assert business_report["filename"].endswith(".html")
    assert business_report["label"] == "业务核对报告"
    assert updated["businessReportDownloadUrl"] == business_report["downloadUrl"]
    business_report_response = client.get(business_report["downloadUrl"])
    assert business_report_response.status_code == 200
    business_report_html = business_report_response.text
    assert "核对结论" in business_report_html
    assert "供应商：SSS" in business_report_html
    assert "核算周期：2026-05-11 ~ 2026-05-17" in business_report_html
    assert "发票编号或文件范围：invoice.pdf" in business_report_html
    for internal_term in ["AI 候选", "规则治理", "profile", "re-OCR", "回放", "Blob", "线程"]:
        assert internal_term not in business_report_html
    assert updated["costSummaries"] == cost_summaries
    assert updated["aiCacheAudit"] == ai_cache_audit
    assert updated["aiCacheReconciliationPreview"] == ai_cache_preview
    assert updated["reocrPlan"] == reocr_plan
    assert updated["reconciliationDiagnostics"]["signals"]["amountBasis"][0]["warehouseId"] == "1"
    assert captured_report_kwargs["reconciliation_diagnostics"] == updated["reconciliationDiagnostics"]
    assert captured_report_kwargs["ai_cache_audit"] == ai_cache_audit


def test_labor_compare_creates_profile_candidate_without_saving_profile(monkeypatch):
    import bonus_platform.app as app_module

    monkeypatch.setattr(app_module, "quick_extract_totals", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        app_module,
        "extract_invoice_items",
        lambda *args, **kwargs: [
            LaborLineItem(source_type="pdf_invoice", source_file="invoice.pdf", source_page_or_row="p1", employee_id="WUS042586", employee_name_raw="Rosa Alvarez Minchaca", hours=31.19, amount=701.90, currency="USD", confidence=0.95, evidence_text="Rosa Alvarez Minchaca 31.19 $701.90")
        ],
    )
    monkeypatch.setattr(
        app_module,
        "generate_profile_from_extraction",
        lambda **kwargs: {
            "key": "onesource",
            "aliases": ["onesource"],
            "prompt_notes": ["Use candidate profile only after confirmation."],
            "image_page_policy": "first_page_only",
            "version": 1,
        },
    )

    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "ONESOURCE", "period_start": "2026-05-11", "period_end": "2026-05-17", "currency": "USD"},
    ).json()
    client.post(
        f"/api/labor/runs/{run['id']}/files",
        files=[
            ("pdf_files", ("invoice.pdf", b"%PDF-1.4\n", "application/pdf")),
            ("workbook_files", ("账单.xlsx", _excel_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
        ],
    )
    client.post(
        f"/api/labor/runs/{run['id']}/mapping",
        json={"sheet_name": "员工账单", "mapping": {"employeeId": "工号", "name": "姓名", "hours": "时长总计(H)", "amount": "费用总计(含税)", "currency": "币种"}},
    )

    updated = app_module._perform_labor_extract_compare(run["id"])

    candidates = updated["profileGovernance"]["candidates"]
    assert len(candidates) == 1
    assert candidates[0]["decision"] == "candidate_only"
    assert candidates[0]["requiresConfirmation"] is True
    assert candidates[0]["profileData"]["key"] == "onesource"
    assert candidates[0]["evidence"][0]["sourcePageOrRow"] == "p1"


def test_labor_profile_candidate_api_confirms_and_rolls_back():
    import bonus_platform.app as app_module

    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "Workforce", "period_start": "2026-05-18", "period_end": "2026-05-24", "currency": "USD"},
    ).json()
    candidate = app_module._build_profile_candidate(
        run["id"],
        "Workforce",
        {
            "key": "workforce",
            "aliases": ["workforce"],
            "prompt_notes": ["Extract wage code rows."],
            "image_page_policy": "first_page_only",
            "version": 1,
        },
        [
            LaborLineItem(source_type="pdf_invoice", source_file="Invoice-5058871.pdf", source_page_or_row="p1", employee_id="", employee_name_raw="Alice Worker", hours=8, amount=100, currency="USD", confidence=0.95, evidence_text="Alice Worker 8 $100")
        ],
    )
    app_module.update_labor_metadata(
        run["id"],
        {
            "profileGovernance": {
                "candidates": [candidate],
                "replaySummaries": {},
                "activeProfiles": [],
                "rolledBackProfiles": [],
            }
        },
    )

    blocked = client.post(
        f"/api/labor/runs/{run['id']}/profile-candidates/{candidate['candidateId']}/confirm",
        json={"confirmedBy": "ops-user", "reason": "Profile evidence reviewed"},
    )

    assert blocked.status_code == 400
    assert "缺少历史回放摘要" in blocked.json()["detail"]

    monkeypatch_runs = [
        {
            "id": run["id"],
            "supplierName": "Workforce",
            "periodStart": "2026-05-18",
            "periodEnd": "2026-05-24",
            "reconciliationDiagnostics": {"level": "ok", "issues": []},
            "extractionQuality": {"level": "ok", "issues": []},
            "comparisonSummary": {"exceptionCount": 0},
        }
    ]
    original_list = app_module.list_labor_metadata
    app_module.list_labor_metadata = lambda: monkeypatch_runs
    try:
        replay = client.post(
            f"/api/labor/runs/{run['id']}/profile-candidates/{candidate['candidateId']}/auto-replay",
            json={"limit": 10},
        )
    finally:
        app_module.list_labor_metadata = original_list

    assert replay.status_code == 200
    replay_body = replay.json()
    assert replay_body["decision"] == "ready_for_user_confirmation"
    assert replay_body["summary"]["compatibleCount"] == 1
    assert replay_body["preflight"]["blockingAfterApply"] is False
    assert replay_body["preflight"]["delta"]["compatibleCount"] == 1
    assert replay_body["preflight"]["affectedScopeCount"] == 1
    assert replay_body["preflight"]["affectedSuppliers"] == ["Workforce"]
    assert "prompt_notes" in replay_body["preflight"]["changedFields"]

    confirmed = client.post(
        f"/api/labor/runs/{run['id']}/profile-candidates/{candidate['candidateId']}/confirm",
        json={"confirmedBy": "ops-user", "reason": "Profile evidence reviewed"},
    )

    assert confirmed.status_code == 200
    assert confirmed.json()["decision"] == "active"
    assert confirmed.json()["requiresConfirmation"] is False
    assert confirmed.json()["confirmedBy"] == "ops-user"
    assert confirmed.json()["preflight"] == replay_body["preflight"]

    rolled_back = client.post(
        f"/api/labor/runs/{run['id']}/profile-candidates/{candidate['candidateId']}/rollback",
        json={"rolledBackBy": "ops-user", "reason": "Profile regression", "targetVersion": 0},
    )

    assert rolled_back.status_code == 200
    assert rolled_back.json()["decision"] == "rolled_back"
    assert rolled_back.json()["rollbackToVersion"] == 0
    governance = client.get(f"/api/labor/runs/{run['id']}").json()["profileGovernance"]
    assert governance["activeProfiles"] == []
    assert governance["rolledBackProfiles"][0]["candidateId"] == candidate["candidateId"]


def test_labor_name_mapping_candidate_confirm_and_rollback_updates_manual_mapping():
    import bonus_platform.app as app_module

    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "OSS", "period_start": "2026-05-18", "period_end": "2026-05-24", "currency": "USD"},
    ).json()
    candidate = {
        "candidateId": "name_map_sample",
        "decision": "candidate_only",
        "status": "pending_user_confirmation",
        "requiresConfirmation": True,
        "sourceFile": "elog27-1_20260520204231.pdf",
        "warehouseId": "27",
        "cacheEmployeeName": "Coria, Virgilio",
        "excelEmployeeName": "Brayan Gomez Vargas",
        "proposedMapping": {"Coria, Virgilio": "Brayan Gomez Vargas"},
        "recommendation": "金额/工时接近，优先人工确认是否为同一员工姓名映射。",
        "auditTrail": [{"action": "created", "actor": "system", "reason": "reocr_suspected_name_pair"}],
    }
    app_module.update_labor_metadata(
        run["id"],
        {
            "manualNameMapping": {},
            "nameMappingGovernance": {
                "candidates": [candidate],
                "replaySummaries": {
                    candidate["candidateId"]: {
                        "decision": "ready_for_user_confirmation",
                        "summary": {"fixedCount": 1, "regressionCount": 0},
                    }
                },
                "activeMappings": [],
                "rolledBackMappings": [],
            },
        },
    )

    confirmed = client.post(
        f"/api/labor/runs/{run['id']}/name-mapping-candidates/{candidate['candidateId']}/confirm",
        json={"confirmedBy": "ops-user", "reason": "OSS27 amount and hours align"},
    )

    assert confirmed.status_code == 200
    confirmed_body = confirmed.json()
    assert confirmed_body["decision"] == "active"
    assert confirmed_body["manualNameMapping"] == {"Coria, Virgilio": "Brayan Gomez Vargas"}
    after_confirm = client.get(f"/api/labor/runs/{run['id']}").json()
    assert after_confirm["manualNameMapping"]["Coria, Virgilio"] == "Brayan Gomez Vargas"
    assert after_confirm["nameMappingGovernance"]["activeMappings"][0]["confirmedBy"] == "ops-user"

    rolled_back = client.post(
        f"/api/labor/runs/{run['id']}/name-mapping-candidates/{candidate['candidateId']}/rollback",
        json={"rolledBackBy": "ops-user", "reason": "Later batch showed different employee"},
    )

    assert rolled_back.status_code == 200
    rolled_back_body = rolled_back.json()
    assert rolled_back_body["decision"] == "rolled_back"
    assert rolled_back_body["manualNameMapping"] == {}
    after_rollback = client.get(f"/api/labor/runs/{run['id']}").json()
    assert after_rollback["manualNameMapping"] == {}
    assert after_rollback["nameMappingGovernance"]["activeMappings"] == []
    assert after_rollback["nameMappingGovernance"]["candidates"][0]["status"] == "rolled_back"
    assert after_rollback["nameMappingGovernance"]["rolledBackMappings"][0]["candidateId"] == candidate["candidateId"]


def test_labor_allocation_governance_builds_candidates_from_warehouse_offsets():
    import bonus_platform.app as app_module

    governance = app_module._build_allocation_governance(
        "labor_allocation_sample",
        {
            "allocationIssues": [
                {
                    "employeeKey": "id:WUS043938",
                    "employeeName": "JIMENEZ, ENEAS",
                    "netAmountDelta": -0.01,
                    "warehouseCount": 2,
                    "warehouses": [
                        {"warehouseId": "25", "pdfAmount": 118.04, "excelAmount": 116.85, "amountDelta": 1.19},
                        {"warehouseId": "28", "pdfAmount": 928.67, "excelAmount": 929.87, "amountDelta": -1.2},
                    ],
                    "recommendation": "员工总额可抵消，但仓库归属金额不一致，需按仓库复核发票与账单归属。",
                }
            ]
        },
    )

    candidate = governance["candidates"][0]
    assert candidate["decision"] == "candidate_only"
    assert candidate["status"] == "pending_user_confirmation"
    assert candidate["requiresConfirmation"] is True
    assert candidate["issueType"] == "cross_warehouse_employee_allocation"
    assert candidate["employeeName"] == "JIMENEZ, ENEAS"
    assert candidate["warehouseCount"] == 2
    assert candidate["warehouses"][0]["warehouseId"] == "25"
    assert "不自动修改" in candidate["confirmationGate"]


def test_labor_excel_aggregation_preserves_cross_warehouse_employee_rows():
    import bonus_platform.app as app_module
    from bonus_platform.engine.labor.models import LaborLineItem

    rows = [
        LaborLineItem(source_type="offline_workbook", source_file="账单.xlsx", source_page_or_row="账单!2", employee_id="WUS041037", employee_name_raw="PEREZ, JOSE", hours=4.0, amount=100.67, currency="USD", confidence=1, evidence_text="", warehouse_id="25"),
        LaborLineItem(source_type="offline_workbook", source_file="账单.xlsx", source_page_or_row="账单!3", employee_id="WUS041037", employee_name_raw="PEREZ, JOSE", hours=40.0, amount=935.59, currency="USD", confidence=1, evidence_text="", warehouse_id="28"),
        LaborLineItem(source_type="offline_workbook", source_file="账单.xlsx", source_page_or_row="账单!4", employee_id="WUS041037", employee_name_raw="PEREZ, JOSE", hours=1.0, amount=10.0, currency="USD", confidence=1, evidence_text="", warehouse_id="25"),
    ]

    aggregated = app_module._aggregate_excel_rows(rows)

    by_warehouse = {row.warehouse_id: row for row in aggregated}
    assert len(aggregated) == 2
    assert by_warehouse["25"].amount == 110.67
    assert by_warehouse["25"].hours == 5.0
    assert by_warehouse["28"].amount == 935.59
    assert by_warehouse["28"].hours == 40.0


def test_labor_allocation_candidate_confirm_and_rollback_updates_readiness():
    import bonus_platform.app as app_module

    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "fairway", "period_start": "2026-05-18", "period_end": "2026-05-24", "currency": "USD"},
    ).json()
    candidate = {
        "candidateId": "allocation_sample",
        "decision": "candidate_only",
        "status": "pending_user_confirmation",
        "requiresConfirmation": True,
        "issueType": "cross_warehouse_employee_allocation",
        "employeeKey": "id:WUS041037",
        "employeeName": "PEREZ, JOSE",
        "netAmountDelta": 0.0,
        "warehouseCount": 2,
        "warehouses": [
            {"warehouseId": "25", "pdfAmount": 101.26, "excelAmount": 100.67, "amountDelta": 0.59},
            {"warehouseId": "28", "pdfAmount": 935.0, "excelAmount": 935.59, "amountDelta": -0.59},
        ],
        "recommendation": "员工总额可抵消，但仓库归属金额不一致，需按仓库复核发票与账单归属。",
        "auditTrail": [{"action": "created", "actor": "system", "reason": "cross_warehouse_employee_allocation_detected"}],
    }
    app_module.update_labor_metadata(
        run["id"],
        {
            "status": "已生成差异报告",
            "comparisonSummary": {"exceptionCount": 0},
            "diffDownloadUrl": "/api/labor/runs/sample/download/report.xlsx",
            "allocationGovernance": {
                "candidates": [candidate],
                "activeAllocations": [],
                "rolledBackAllocations": [],
            },
        },
    )

    before = client.get(f"/api/labor/runs/{run['id']}").json()
    assert before["readinessGate"]["summary"]["pendingGovernanceCount"] == 1
    assert before["readinessGate"]["status"] == "needs_review"

    confirmed = client.post(
        f"/api/labor/runs/{run['id']}/allocation-candidates/{candidate['candidateId']}/confirm",
        json={"confirmedBy": "ops-user", "reason": "warehouse allocation reviewed", "decisionNote": "accepted as allocation split"},
    )

    assert confirmed.status_code == 200
    confirmed_body = confirmed.json()
    assert confirmed_body["decision"] == "confirmed"
    assert confirmed_body["requiresConfirmation"] is False
    assert confirmed_body["readinessGate"]["summary"]["pendingGovernanceCount"] == 0
    after_confirm = client.get(f"/api/labor/runs/{run['id']}").json()
    assert after_confirm["allocationGovernance"]["activeAllocations"][0]["confirmedBy"] == "ops-user"
    assert after_confirm["allocationGovernance"]["candidates"][0]["status"] == "confirmed"
    assert after_confirm["comparisonSummary"]["exceptionCount"] == 0

    rolled_back = client.post(
        f"/api/labor/runs/{run['id']}/allocation-candidates/{candidate['candidateId']}/rollback",
        json={"rolledBackBy": "ops-user", "reason": "review note was wrong"},
    )

    assert rolled_back.status_code == 200
    rolled_back_body = rolled_back.json()
    assert rolled_back_body["decision"] == "rolled_back"
    assert rolled_back_body["readinessGate"]["summary"]["pendingGovernanceCount"] == 0
    after_rollback = client.get(f"/api/labor/runs/{run['id']}").json()
    assert after_rollback["allocationGovernance"]["activeAllocations"] == []
    assert after_rollback["allocationGovernance"]["rolledBackAllocations"][0]["candidateId"] == candidate["candidateId"]
    assert after_rollback["allocationGovernance"]["candidates"][0]["status"] == "rolled_back"


def test_labor_name_mapping_candidate_requires_and_records_impact_replay(monkeypatch):
    import bonus_platform.app as app_module

    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "OSS", "period_start": "2026-05-18", "period_end": "2026-05-24", "currency": "USD"},
    ).json()
    candidate = {
        "candidateId": "name_map_replay_sample",
        "decision": "candidate_only",
        "status": "pending_user_confirmation",
        "requiresConfirmation": True,
        "sourceFile": "elog27-1_20260520204231.pdf",
        "warehouseId": "27",
        "cacheEmployeeName": "Coria, Virgilio",
        "excelEmployeeName": "Brayan Gomez Vargas",
        "proposedMapping": {"Coria, Virgilio": "Brayan Gomez Vargas"},
        "recommendation": "金额/工时接近，优先人工确认是否为同一员工姓名映射。",
    }
    pdf_row = LaborLineItem(
        source_type="pdf_invoice",
        source_file="elog27-1_20260520204231.pdf",
        source_page_or_row="p1",
        employee_id="",
        employee_name_raw="Coria, Virgilio",
        hours=14.17,
        amount=353.69,
        currency="USD",
        confidence=0.95,
        evidence_text="Coria, Virgilio 14.17 $353.69",
        warehouse_id="27",
    )
    excel_row = LaborLineItem(
        source_type="offline_workbook",
        source_file="账单.xlsx",
        source_page_or_row="员工账单!2",
        employee_id="",
        employee_name_raw="Brayan Gomez Vargas",
        hours=14.17,
        amount=353.69,
        currency="USD",
        confidence=1.0,
        warehouse_id="27",
    )
    app_module.update_labor_metadata(
        run["id"],
        {
            "manualNameMapping": {},
            "pdfExtractedRows": [pdf_row.to_dict()],
            "excelRows": [excel_row.to_dict()],
            "nameMappingGovernance": {
                "candidates": [candidate],
                "replaySummaries": {},
                "activeMappings": [],
                "rolledBackMappings": [],
            },
        },
    )
    historical_run = {
        "id": "historical_oss_27",
        "supplierName": "OSS",
        "periodStart": "2026-05-11",
        "periodEnd": "2026-05-17",
        "manualNameMapping": {},
        "pdfExtractedRows": [pdf_row.to_dict()],
        "excelRows": [excel_row.to_dict()],
    }
    insufficient_run = {
        "id": "historical_oss_missing_detail",
        "supplierName": "OSS",
        "periodStart": "2026-05-04",
        "periodEnd": "2026-05-10",
        "manualNameMapping": {},
    }
    monkeypatch_runs = [client.get(f"/api/labor/runs/{run['id']}").json(), historical_run, insufficient_run]
    original_list = app_module.list_labor_metadata
    app_module.list_labor_metadata = lambda: monkeypatch_runs

    try:
        blocked = client.post(
            f"/api/labor/runs/{run['id']}/name-mapping-candidates/{candidate['candidateId']}/confirm",
            json={"confirmedBy": "ops-user", "reason": "reviewed"},
        )
        assert blocked.status_code == 400
        assert "影响回放摘要" in blocked.json()["detail"]

        replay = client.post(
            f"/api/labor/runs/{run['id']}/name-mapping-candidates/{candidate['candidateId']}/auto-replay",
            json={"limit": 10},
        )
        assert replay.status_code == 200
        replay_body = replay.json()
        assert replay_body["decision"] == "ready_for_user_confirmation"
        assert replay_body["mode"] == "current_and_historical_name_mapping_replay"
        assert replay_body["summary"]["fixedCount"] == 1
        assert replay_body["summary"]["regressionCount"] == 0
        assert replay_body["summary"]["historicalCheckedCount"] == 1
        assert replay_body["summary"]["historicalInsufficientCount"] == 1

        confirmed = client.post(
            f"/api/labor/runs/{run['id']}/name-mapping-candidates/{candidate['candidateId']}/confirm",
            json={"confirmedBy": "ops-user", "reason": "impact replay fixed the unmatched pair"},
        )
    finally:
        app_module.list_labor_metadata = original_list
    assert confirmed.status_code == 200
    assert confirmed.json()["manualNameMapping"] == {"Coria, Virgilio": "Brayan Gomez Vargas"}
    assert confirmed.json()["replaySummary"]["fixedCount"] == 1


def test_labor_name_mapping_candidates_are_built_from_reocr_suspected_pairs():
    import bonus_platform.app as app_module

    candidates = app_module._build_name_mapping_candidates_from_reocr_plan(
        "labor_sample",
        {
            "tasks": [
                {
                    "sourceFile": "elog27-1_20260520204231.pdf",
                    "warehouseId": "27",
                    "diagnostics": {
                        "suspectedNamePairs": [
                            {
                                "cacheEmployeeName": "Coria, Virgilio",
                                "excelEmployeeName": "Brayan Gomez Vargas",
                                "amountGap": -0.01,
                                "hoursGap": 0.3,
                                "sourceRefs": "elog27 p1; workbook row 34",
                                "cacheAmount": 353.68,
                                "excelAmount": 353.69,
                                "cacheHours": 14.47,
                                "excelHours": 14.17,
                            }
                        ]
                    },
                }
            ]
        },
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["decision"] == "candidate_only"
    assert candidate["requiresConfirmation"] is True
    assert candidate["sourceFile"] == "elog27-1_20260520204231.pdf"
    assert candidate["warehouseId"] == "27"
    assert candidate["proposedMapping"] == {"Coria, Virgilio": "Brayan Gomez Vargas"}
    assert candidate["evidence"]["sourceRefs"] == "elog27 p1; workbook row 34"


def test_labor_name_mapping_candidates_are_built_from_candidate_matches():
    import bonus_platform.app as app_module

    candidates = app_module._build_name_mapping_candidates_from_candidate_matches(
        "labor_29_sample",
        [
            {
                "pdfEmployeeName": "Rozo Panche, Deisy V",
                "excelEmployeeName": "Deisi Pozo",
                "pdfAmountTotal": 847.84,
                "excelAmountTotal": 847.84,
                "pdfHoursTotal": 37.84,
                "excelHoursTotal": 37.84,
                "amountDelta": 0,
                "hoursDelta": 0,
                "nameSimilarity": 0.4,
                "sourceRefs": "In291943.pdf p1; 账单.xlsx 员工账单明细!3",
                "recommendation": "人工复核",
            },
            {
                "pdfEmployeeName": "Moran Treminio, Freddy",
                "excelEmployeeName": "Freddy Moran (MOR47K)",
                "pdfAmountTotal": 1042.43,
                "excelAmountTotal": 830.72,
                "pdfHoursTotal": 40.48,
                "excelHoursTotal": 40.48,
                "amountDelta": 211.71,
                "hoursDelta": 0,
                "nameSimilarity": 0.52,
                "sourceRefs": "In291943.pdf p1; 账单.xlsx 员工账单明细!4",
                "recommendation": "人工复核",
            }
        ],
    )

    assert len(candidates) == 2
    candidate = candidates[0]
    assert candidate["decision"] == "candidate_only"
    assert candidate["status"] == "pending_user_confirmation"
    assert candidate["requiresConfirmation"] is True
    assert candidate["sourceFile"] == "In291943.pdf"
    assert candidate["cacheEmployeeName"] == "Rozo Panche, Deisy V"
    assert candidate["excelEmployeeName"] == "Deisi Pozo"
    assert candidate["proposedMapping"] == {"Rozo Panche, Deisy V": "Deisi Pozo"}
    assert candidate["confidence"] == "high"
    assert candidate["amountGap"] == 0
    assert candidate["hoursGap"] == 0
    assert candidate["projectedFixedExceptionCount"] == 2
    assert candidate["matchReason"] == "姓名相似且金额/工时一致"
    assert "确认后预计减少 2 项异常" in candidate["businessQuestion"]
    assert candidate["impactSummary"] == "金额和工时均一致"
    assert "必须预览影响" in candidate["cannotAutoResolveReason"]
    assert candidate["evidence"]["nameSimilarity"] == 0.4
    assert candidate["auditTrail"][0]["reason"] == "candidate_match_name_pair"
    medium_candidate = candidates[1]
    assert medium_candidate["confidence"] == "medium"
    assert medium_candidate["projectedFixedExceptionCount"] == 0
    assert medium_candidate["matchReason"] == "姓名相似，但金额或工时仍需复核"
    assert "需先复核差异口径" in medium_candidate["businessQuestion"]
    assert "PDF 高于 Excel" in medium_candidate["impactSummary"]
    assert "不能直接确认匹配" in medium_candidate["cannotAutoResolveReason"]


def test_labor_name_mapping_merge_preserves_confirmed_and_rolled_back_candidates():
    import bonus_platform.app as app_module

    generated = app_module._build_name_mapping_candidates_from_reocr_plan(
        "labor_sample",
        {
            "tasks": [
                {
                    "sourceFile": "elog27-1_20260520204231.pdf",
                    "warehouseId": "27",
                    "diagnostics": {
                        "suspectedNamePairs": [
                            {
                                "cacheEmployeeName": "Coria, Virgilio",
                                "excelEmployeeName": "Brayan Gomez Vargas",
                                "amountGap": -0.01,
                                "hoursGap": 0.3,
                            }
                        ]
                    },
                },
                {
                    "sourceFile": "elog1-1_20260520204104.pdf",
                    "warehouseId": "1",
                    "diagnostics": {
                        "suspectedNamePairs": [
                            {
                                "cacheEmployeeName": "Espinosa Manuel",
                                "excelEmployeeName": "Massiel Castillo",
                                "amountGap": 0,
                                "hoursGap": 0,
                            }
                        ]
                    },
                },
            ]
        },
    )
    confirmed = {**generated[0], "status": "confirmed", "decision": "confirmed"}
    rolled_back = {**generated[1], "status": "rolled_back", "decision": "rolled_back"}

    merged = app_module._merge_name_mapping_candidates(
        {
            "candidates": [confirmed, rolled_back],
            "activeMappings": [{**confirmed, "decision": "active", "status": "active"}],
            "rolledBackMappings": [rolled_back],
        },
        generated,
    )

    by_id = {candidate["candidateId"]: candidate for candidate in merged}
    assert by_id[confirmed["candidateId"]]["status"] == "confirmed"
    assert by_id[rolled_back["candidateId"]]["status"] == "rolled_back"
    assert len(merged) == 2


def test_labor_compare_uses_active_profile_from_current_run(monkeypatch):
    import bonus_platform.app as app_module

    captured_profiles = []
    monkeypatch.setattr(app_module, "quick_extract_totals", lambda *args, **kwargs: [])

    def fake_extract(*args, **kwargs):
        captured_profiles.append(kwargs.get("supplier_profile_override"))
        return [
            LaborLineItem(source_type="pdf_invoice", source_file="invoice.pdf", source_page_or_row="p1", employee_id="WUS042586", employee_name_raw="Rosa Alvarez Minchaca", hours=31.19, amount=701.90, currency="USD", confidence=0.95, evidence_text="Rosa Alvarez Minchaca 31.19 $701.90")
        ]

    monkeypatch.setattr(app_module, "extract_invoice_items", fake_extract)
    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "Workforce", "period_start": "2026-05-18", "period_end": "2026-05-24", "currency": "USD"},
    ).json()
    app_module.update_labor_metadata(
        run["id"],
        {
            "profileGovernance": {
                "candidates": [],
                "replaySummaries": {},
                "activeProfiles": [
                    {
                        "candidateId": "profile_workforce_active",
                        "profileKey": "workforce",
                        "supplier": "Workforce",
                        "decision": "active",
                        "status": "active",
                        "requiresConfirmation": False,
                        "profileData": {
                            "key": "workforce",
                            "aliases": ["workforce"],
                            "prompt_notes": ["Active run profile guidance."],
                            "image_page_policy": "first_page_only",
                            "version": 2,
                        },
                    }
                ],
                "rolledBackProfiles": [],
            }
        },
    )
    client.post(
        f"/api/labor/runs/{run['id']}/files",
        files=[
            ("pdf_files", ("invoice.pdf", b"%PDF-1.4\n", "application/pdf")),
            ("workbook_files", ("账单.xlsx", _excel_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
        ],
    )
    client.post(
        f"/api/labor/runs/{run['id']}/mapping",
        json={"sheet_name": "员工账单", "mapping": {"employeeId": "工号", "name": "姓名", "hours": "时长总计(H)", "amount": "费用总计(含税)", "currency": "币种"}},
    )

    updated = app_module._perform_labor_extract_compare(run["id"])

    assert updated["status"] == "已生成差异报告"
    assert captured_profiles
    assert captured_profiles[0].key == "workforce"
    assert captured_profiles[0].version == 2
    assert captured_profiles[0].prompt_notes == ["Active run profile guidance."]


def test_labor_low_confidence_rows_create_correction_candidates(monkeypatch):
    import bonus_platform.app as app_module

    monkeypatch.setattr(app_module, "quick_extract_totals", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        app_module,
        "extract_invoice_items",
        lambda *args, **kwargs: [
            LaborLineItem(source_type="pdf_invoice", source_file="invoice.pdf", source_page_or_row="p1", employee_id="WUS042586", employee_name_raw="Rosa Alvarez Minchaca", hours=31.19, amount=701.90, currency="USD", confidence=0.6, evidence_text="blurred row Rosa 31.19 701.90")
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
            ("pdf_files", ("invoice.pdf", b"%PDF-1.4\n", "application/pdf")),
            ("workbook_files", ("账单.xlsx", _excel_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
        ],
    )
    client.post(
        f"/api/labor/runs/{run['id']}/mapping",
        json={"sheet_name": "员工账单", "mapping": {"employeeId": "工号", "name": "姓名", "hours": "时长总计(H)", "amount": "费用总计(含税)", "currency": "币种"}},
    )

    updated = app_module._perform_labor_extract_compare(run["id"])
    candidates = updated["correctionGovernance"]["candidates"]

    assert len(candidates) == 1
    assert candidates[0]["decision"] == "candidate_only"
    assert candidates[0]["requiresConfirmation"] is True
    assert candidates[0]["confidence"] == 0.6
    assert candidates[0]["evidence"]["evidenceText"] == "blurred row Rosa 31.19 701.90"

    blocked = client.post(
        f"/api/labor/runs/{run['id']}/correction-candidates/{candidates[0]['candidateId']}/confirm",
        json={"confirmedBy": "ops-user", "reason": "Evidence reviewed"},
    )
    assert blocked.status_code == 400
    assert "影响回放摘要" in blocked.json()["detail"]

    replay = client.post(
        f"/api/labor/runs/{run['id']}/correction-candidates/{candidates[0]['candidateId']}/auto-replay",
        json={},
    )
    assert replay.status_code == 200
    replay_body = replay.json()
    assert replay_body["decision"] == "ready_for_user_confirmation"
    assert replay_body["summary"]["affectedEmployees"] == ["Rosa Alvarez Minchaca"]
    assert replay_body["summary"]["regressionCount"] == 0
    assert replay_body["impact"][0]["riskReduced"] is True

    confirmed = client.post(
        f"/api/labor/runs/{run['id']}/correction-candidates/{candidates[0]['candidateId']}/confirm",
        json={"confirmedBy": "ops-user", "reason": "Evidence reviewed"},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["decision"] == "active"
    assert confirmed.json()["replaySummary"]["regressionCount"] == 0
    before_preview = client.get(f"/api/labor/runs/{run['id']}").json()["comparisonSummary"]
    before_files = client.get(f"/api/labor/runs/{run['id']}").json()["files"]

    preview = client.post(
        f"/api/labor/runs/{run['id']}/corrections/projected-preview",
        json={"candidateIds": [candidates[0]["candidateId"]], "generateReport": True},
    )
    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["decision"] == "preview_only"
    assert preview_body["summaryDelta"]["lowConfidenceCount"] == -1
    assert preview_body["summaryDelta"]["exceptionCount"] == -1
    assert preview_body["affectedRows"][0]["matchStatus"] == "通过"
    assert preview_body["preflight"]["willOverwriteOfficialResult"] is False
    assert preview_body["preflight"]["willRegenerateDiffReport"] is False
    assert preview_body["preflight"]["delta"]["lowConfidenceCount"] == -1
    assert preview_body["preflight"]["delta"]["exceptionCount"] == -1
    assert preview_body["preflight"]["affectedEmployeeCount"] == 1
    assert preview_body["preflight"]["blockingAfterApply"] is False
    assert preview_body["reportFile"]["label"] == "修正预览报告"
    assert Path(preview_body["reportFile"]["path"]).exists()
    downloaded_preview = client.get(preview_body["reportFile"]["downloadUrl"])
    assert downloaded_preview.status_code == 200
    after_preview = client.get(f"/api/labor/runs/{run['id']}").json()
    assert after_preview["comparisonSummary"] == before_preview
    assert after_preview["files"]["diffReport"] == before_files["diffReport"]
    assert after_preview["files"]["correctionPreviewReport"]["filename"].endswith(".xlsx")
    assert after_preview["correctionGovernance"]["activeCorrections"][0]["preflight"] == preview_body["preflight"]

    rolled_back = client.post(
        f"/api/labor/runs/{run['id']}/correction-candidates/{candidates[0]['candidateId']}/rollback",
        json={"rolledBackBy": "ops-user", "reason": "Correction no longer needed"},
    )
    assert rolled_back.status_code == 200
    assert rolled_back.json()["decision"] == "rolled_back"


def test_labor_governance_report_collects_rule_profile_correction_and_ai_evidence():
    import bonus_platform.app as app_module

    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "Workforce", "period_start": "2026-05-18", "period_end": "2026-05-24", "currency": "USD"},
    ).json()
    run_dir = app_module.get_labor_run_dir(run["id"])
    diff_path = run_dir / "existing_diff.xlsx"
    Workbook().save(diff_path)
    correction = {
        "candidateId": "correction_sample",
        "decision": "active",
        "status": "active",
        "requiresConfirmation": False,
        "confidence": 0.6,
        "proposed": {
            "employeeName": "Rosa Alvarez Minchaca",
            "hours": 31.19,
            "amount": 701.9,
            "sourceFile": "invoice.pdf",
            "sourcePageOrRow": "p1",
        },
        "auditTrail": [{"action": "created", "actor": "system", "reason": "low confidence"}],
        "replaySummary": {"fixedCount": 1, "regressionCount": 0},
    }
    app_module.update_labor_metadata(
        run["id"],
        {
            "status": "已生成差异报告",
            "ruleGovernance": {
                "candidates": [
                    {
                        "ruleId": "workforce-low-confidence-v1",
                        "title": "低置信度复核规则",
                        "status": "pending_user_confirmation",
                        "decision": "candidate_only",
                        "version": 1,
                        "auditTrail": [{"action": "created", "actor": "ai", "reason": "diagnostic signal"}],
                    }
                ],
                "replaySummaries": {
                    "workforce-low-confidence-v1": {
                        "decision": "ready_for_user_confirmation",
                        "summary": {"replayedCount": 1, "fixedCount": 1, "regressionCount": 0},
                    }
                },
                "activeRules": [],
                "rolledBackRules": [],
            },
            "profileGovernance": {
                "candidates": [
                    {
                        "candidateId": "profile_workforce_v1",
                        "supplier": "Workforce",
                        "profileKey": "workforce",
                        "status": "pending_user_confirmation",
                        "decision": "candidate_only",
                        "profileData": {"key": "workforce", "version": 1},
                        "auditTrail": [{"action": "created", "actor": "system", "reason": "profile suggestion"}],
                    }
                ],
                "replaySummaries": {
                    "profile_workforce_v1": {
                        "decision": "ready_for_user_confirmation",
                        "summary": {"compatibleCount": 1, "regressionCount": 0},
                    }
                },
                "activeProfiles": [],
                "rolledBackProfiles": [],
            },
            "correctionGovernance": {
                "candidates": [correction],
                "replaySummaries": {
                    "correction_sample": {
                        "decision": "ready_for_user_confirmation",
                        "summary": {"affectedEmployees": ["Rosa Alvarez Minchaca"], "fixedCount": 1, "regressionCount": 0},
                    }
                },
                "activeCorrections": [correction],
                "rolledBackCorrections": [],
            },
            "nameMappingGovernance": {
                "candidates": [
                    {
                        "candidateId": "name_map_sample",
                        "decision": "candidate_only",
                        "status": "pending_user_confirmation",
                        "cacheEmployeeName": "Cache Rosa",
                        "excelEmployeeName": "Rosa Alvarez Minchaca",
                        "sourceFile": "invoice.pdf",
                        "warehouseId": "1",
                        "amountGap": 0,
                        "hoursGap": 0,
                        "recommendation": "Review name mapping",
                        "evidence": {"sourceRefs": "invoice.pdf p1; sheet row 2"},
                        "auditTrail": [{"action": "created", "actor": "system", "reason": "reocr_suspected_name_pair"}],
                    }
                ],
                "replaySummaries": {},
                "activeMappings": [],
                "rolledBackMappings": [],
            },
            "reocrReplayGovernance": {
                "replays": [
                    {
                        "decision": "ready_for_user_confirmation",
                        "mode": "new_ocr_candidate_replay",
                        "sourceFile": "invoice.pdf",
                        "warehouseId": "1",
                        "summary": {
                            "candidateRowCount": 1,
                            "candidateAmountTotal": 701.9,
                            "expectedExcelAmount": 701.9,
                            "exceptionCount": 0,
                        },
                        "diagnostics": {
                            "recommendedAction": "review_name_mapping_then_reocr_if_amounts_remain_unexplained",
                            "rootCauseHints": ["possible_name_mapping", "possible_missing_cache_rows"],
                            "suspectedNamePairs": [
                                {
                                    "cacheEmployeeName": "Cache Rosa",
                                    "excelEmployeeName": "Rosa Alvarez Minchaca",
                                    "cacheAmount": 701.9,
                                    "excelAmount": 701.9,
                                }
                            ],
                        },
                        "blockers": [],
                    }
                ],
                "activeCandidates": [
                    {
                        "candidateId": "reocr_sample",
                        "decision": "active",
                        "status": "active",
                        "sourceFile": "invoice.pdf",
                        "warehouseId": "1",
                        "confirmedBy": "ops-user",
                        "confirmationReason": "OCR replay passed",
                        "replay": {
                            "summary": {
                                "candidateRowCount": 1,
                                "candidateAmountTotal": 701.9,
                                "expectedExcelAmount": 701.9,
                                "exceptionCount": 0,
                            }
                        },
                        "auditTrail": [{"action": "confirmed", "actor": "ops-user", "reason": "OCR replay passed"}],
                    }
                ],
                "rolledBackCandidates": [
                    {
                        "candidateId": "reocr_rolled_back",
                        "decision": "rolled_back",
                        "status": "rolled_back",
                        "sourceFile": "invoice_old.pdf",
                        "warehouseId": "1",
                        "confirmedBy": "ops-user",
                        "rolledBackBy": "ops-user",
                        "rollbackReason": "Candidate was superseded by a cleaner OCR run.",
                        "replay": {
                            "summary": {
                                "candidateRowCount": 1,
                                "candidateAmountTotal": 680.0,
                                "expectedExcelAmount": 701.9,
                                "exceptionCount": 1,
                            }
                        },
                        "auditTrail": [
                            {"action": "confirmed", "actor": "ops-user", "reason": "initial OCR replay passed"},
                            {"action": "rolled_back", "actor": "ops-user", "reason": "Candidate was superseded by a cleaner OCR run."},
                        ],
                    }
                ],
            },
            "files": {
                "diffReport": app_module.attach_labor_file(run["id"], diff_path, "差异报告"),
                "reocrCandidateFiles": [
                    {
                        "filename": "partial_batch.csv",
                        "summary": {
                            "plannedTaskCount": 2,
                            "coveredTaskCount": 1,
                            "missingTaskCount": 1,
                            "extraScopeCount": 0,
                            "parsedRowCount": 1,
                        },
                        "coverage": {
                            "coverageComplete": False,
                            "plannedTaskCount": 2,
                            "coveredTaskCount": 1,
                            "missingTaskCount": 1,
                            "extraScopeCount": 0,
                            "uploadedScopes": [{"sourceFile": "invoice.pdf", "warehouseId": "1", "rowCount": 1}],
                            "missingTasks": [{"sourceFile": "invoice_2.pdf", "warehouseId": "2"}],
                            "extraScopes": [],
                        },
                    }
                ]
            },
            "aiCacheAudit": {
                "decision": "candidate_only",
                "requiresConfirmation": True,
                "message": "AI cache evidence only.",
                "summary": {"candidateFileCount": 1},
                "files": [
                    {
                        "sourceFile": "invoice.pdf",
                        "warehouseId": "1",
                        "rowCount": 1,
                        "candidateAmountTotal": 701.9,
                        "averageConfidence": 0.6,
                        "decision": "candidate_only",
                        "evidence": [{"employeeName": "Rosa Alvarez Minchaca", "amount": 701.9, "sourcePageOrRow": "p1"}],
                    }
                ],
            },
        },
    )

    before_files = client.get(f"/api/labor/runs/{run['id']}").json()["files"]
    response = client.post(f"/api/labor/runs/{run['id']}/governance-report")

    assert response.status_code == 200
    report = response.json()
    assert report["label"] == "治理审计报告"
    assert Path(report["path"]).exists()
    downloaded = client.get(report["downloadUrl"])
    assert downloaded.status_code == 200
    workbook = load_workbook(report["path"], read_only=True)
    assert workbook.sheetnames == ["治理总览", "规则治理", "姓名映射治理", "Profile治理", "修正治理", "图片识别治理", "图片识别上传覆盖", "AI候选治理", "审计记录"]
    overview_rows = list(workbook["治理总览"].iter_rows(values_only=True))
    assert any(row[:2] == ("姓名映射候选", 1) for row in overview_rows)
    name_mapping_rows = list(workbook["姓名映射治理"].iter_rows(values_only=True))
    assert any(row[0] == "候选" and row[1] == "name_map_sample" and row[2] == "Cache Rosa" and row[3] == "Rosa Alvarez Minchaca" for row in name_mapping_rows)
    reocr_rows = list(workbook["图片识别治理"].iter_rows(values_only=True))
    assert any(row[0] == "回放" and row[2] == "invoice.pdf" and row[5] == "ready_for_user_confirmation" for row in reocr_rows)
    assert any(
        row[0] == "回放"
        and row[10] == "review_name_mapping_then_reocr_if_amounts_remain_unexplained"
        and "possible_name_mapping" in str(row[11])
        and "Cache Rosa" in str(row[12])
        for row in reocr_rows
    )
    assert any(row[0] == "已确认" and row[1] == "reocr_sample" and row[13] == "ops-user" for row in reocr_rows)
    assert any(row[0] == "已回滚" and row[1] == "reocr_rolled_back" and row[14] == "Candidate was superseded by a cleaner OCR run." for row in reocr_rows)
    upload_rows = list(workbook["图片识别上传覆盖"].iter_rows(values_only=True))
    assert any(row[0] == "汇总" and row[1] == "partial_batch.csv" and row[2:7] == (2, 1, 1, 0, "否") for row in upload_rows)
    assert any(row[0] == "已上传范围" and row[7] == "invoice.pdf" and row[8] == "1" and row[9] == 1 for row in upload_rows)
    assert any(row[0] == "缺失计划任务" and row[7] == "invoice_2.pdf" and row[8] == "2" for row in upload_rows)
    audit_rows = list(workbook["审计记录"].iter_rows(values_only=True))
    assert any(row[0] == "姓名映射" and row[1] == "name_map_sample" and row[2] == "created" for row in audit_rows)
    after_files = client.get(f"/api/labor/runs/{run['id']}").json()["files"]
    assert after_files["diffReport"] == before_files["diffReport"]
    assert after_files["governanceAuditReport"]["filename"].endswith(".xlsx")


def test_labor_rule_candidate_api_blocks_confirmation_when_replay_regresses():
    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "OSI", "period_start": "2026-05-11", "period_end": "2026-05-17", "currency": "USD"},
    ).json()

    created = client.post(
        f"/api/labor/runs/{run['id']}/rule-candidates",
        json={
            "ruleId": "osi-name-fuzzy-v1",
            "title": "OSI name fuzzy matching",
            "description": "Candidate rule from employee attribution diagnostics.",
            "source": "real replay: osi",
            "evidence": [{"sourceFile": "US ELogistics Service Corp. 34794.pdf", "sourcePageOrRow": "p1"}],
            "conditions": {"supplier": "OSI"},
        },
    )

    assert created.status_code == 200
    assert created.json()["candidates"][0]["requiresConfirmation"] is True

    replay = client.post(
        f"/api/labor/runs/{run['id']}/rule-candidates/osi-name-fuzzy-v1/replay-summary",
        json={
            "replayResults": [
                {"runId": "osi_34794", "supplier": "OSI", "beforeStatus": "warning", "afterStatus": "ok", "beforeIssueCount": 1, "afterIssueCount": 0},
                {"runId": "fairway_135612", "supplier": "Fairway", "beforeStatus": "ok", "afterStatus": "warning", "beforeIssueCount": 0, "afterIssueCount": 1},
            ]
        },
    )

    assert replay.status_code == 200
    assert replay.json()["decision"] == "blocked_by_replay_regression"
    assert replay.json()["preflight"]["blockingAfterApply"] is True
    assert replay.json()["preflight"]["delta"]["regressionCount"] == 1
    assert replay.json()["preflight"]["regressionRuns"][0]["runId"] == "fairway_135612"

    confirm = client.post(
        f"/api/labor/runs/{run['id']}/rule-candidates/osi-name-fuzzy-v1/confirm",
        json={"confirmedBy": "ops-user", "reason": "should not pass"},
    )

    assert confirm.status_code == 400
    assert "未通过历史影响预览" in confirm.json()["detail"]


def test_labor_rule_candidate_api_confirms_and_rolls_back_after_clean_replay():
    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "OSS", "period_start": "2026-05-18", "period_end": "2026-05-24", "currency": "USD"},
    ).json()

    created = client.post(
        f"/api/labor/runs/{run['id']}/rule-candidates",
        json={
            "ruleId": "oss-hash-warehouse-v1",
            "title": "OSS # warehouse id extraction",
            "description": "Parse warehouse id from US Elogis Service #N invoice names.",
            "source": "real replay: oss 2",
            "proposedBy": "ai",
            "conditions": {"supplier": "OSS", "filenamePattern": "#N"},
        },
    )
    assert created.status_code == 200

    replay = client.post(
        f"/api/labor/runs/{run['id']}/rule-candidates/oss-hash-warehouse-v1/replay-summary",
        json={
            "replayResults": [
                {"runId": "oss2_warehouse_7", "supplier": "OSS", "beforeStatus": "warning", "afterStatus": "ok", "beforeIssueCount": 1, "afterIssueCount": 0},
                {"runId": "oss2_warehouse_27", "supplier": "OSS", "beforeStatus": "ok", "afterStatus": "ok", "beforeIssueCount": 0, "afterIssueCount": 0},
            ]
        },
    )
    assert replay.status_code == 200
    replay_body = replay.json()
    assert replay_body["decision"] == "ready_for_user_confirmation"
    assert replay_body["preflight"]["blockingAfterApply"] is False
    assert replay_body["preflight"]["delta"]["fixedCount"] == 1
    assert replay_body["preflight"]["affectedScopeCount"] == 2
    assert replay_body["preflight"]["affectedSuppliers"] == ["OSS"]

    confirmed = client.post(
        f"/api/labor/runs/{run['id']}/rule-candidates/oss-hash-warehouse-v1/confirm",
        json={"confirmedBy": "ops-user", "reason": "OSS2 replay clean"},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["decision"] == "active"
    assert confirmed.json()["requiresConfirmation"] is False
    assert confirmed.json()["preflight"] == replay_body["preflight"]

    rolled_back = client.post(
        f"/api/labor/runs/{run['id']}/rule-candidates/oss-hash-warehouse-v1/rollback",
        json={"rolledBackBy": "ops-user", "reason": "future batch regression", "targetVersion": 0},
    )
    assert rolled_back.status_code == 200
    assert rolled_back.json()["decision"] == "rolled_back"
    assert rolled_back.json()["rollbackToVersion"] == 0

    governance = client.get(f"/api/labor/runs/{run['id']}/governance").json()
    assert governance["activeRules"] == []
    assert governance["rolledBackRules"][0]["ruleId"] == "oss-hash-warehouse-v1"


def test_labor_reocr_candidate_replay_api_returns_ready_for_confirmation():
    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "OSS", "period_start": "2026-05-18", "period_end": "2026-05-24", "currency": "USD"},
    ).json()
    client.post(
        f"/api/labor/runs/{run['id']}/files",
        files=[
            ("pdf_files", ("elog1-1_20260520204104.pdf", b"%PDF-1.4\n", "application/pdf")),
            ("workbook_files", ("账单.xlsx", _excel_bytes_with_warehouse(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
        ],
    )
    client.post(
        f"/api/labor/runs/{run['id']}/mapping",
        json={
            "sheet_name": "员工账单",
            "mapping": {
                "employeeId": "工号",
                "name": "姓名",
                "hours": "时长总计(H)",
                "amount": "费用总计(含税)",
                "currency": "币种",
            },
        },
    )

    replay = client.post(
        f"/api/labor/runs/{run['id']}/reocr-candidates/replay",
        json={
            "task": {
                "sourceFile": "elog1-1_20260520204104.pdf",
                "warehouseId": "1",
                "expectedExcelAmount": 100,
                "amountDelta": 50,
                "confirmationGate": "new OCR candidate must replay clean before replacing cache",
            },
            "candidateRows": [
                {
                    "employeeName": "Alice Worker",
                    "sourcePageOrRow": "p1",
                    "hours": 8,
                    "amount": 100,
                    "currency": "USD",
                    "confidence": 0.96,
                    "evidenceText": "Alice Worker 8.00 $100.00",
                }
            ],
            "amountTolerance": 0.1,
            "hoursTolerance": 0.1,
            "confidenceThreshold": 0.85,
        },
    )

    assert replay.status_code == 200
    body = replay.json()
    assert body["runId"] == run["id"]
    assert body["decision"] == "ready_for_user_confirmation"
    assert body["requiresConfirmation"] is True
    assert body["blockers"] == []
    assert body["summary"]["candidateAmountTotal"] == 100
    assert body["summary"]["expectedExcelAmount"] == 100
    assert body["summary"]["amountPassed"] is True
    assert body["summary"]["exceptionCount"] == 0
    refreshed = client.get(f"/api/labor/runs/{run['id']}").json()
    assert refreshed["reocrReplayGovernance"]["replays"][0]["decision"] == "ready_for_user_confirmation"
    before_summary = refreshed.get("comparisonSummary") or {}

    confirmed = client.post(
        f"/api/labor/runs/{run['id']}/reocr-candidates/confirm",
        json={
            "sourceFile": "elog1-1_20260520204104.pdf",
            "warehouseId": "1",
            "confirmedBy": "ops-user",
            "reason": "new OCR candidate replay passed",
            "generateReport": True,
        },
    )

    assert confirmed.status_code == 200
    confirmed_body = confirmed.json()
    assert confirmed_body["decision"] == "active"
    assert confirmed_body["reportFile"]["label"] == "图片识别结果预览报告"
    assert Path(confirmed_body["reportFile"]["path"]).exists()
    downloaded = client.get(confirmed_body["reportFile"]["downloadUrl"])
    assert downloaded.status_code == 200
    after_confirm = client.get(f"/api/labor/runs/{run['id']}").json()
    assert (after_confirm.get("comparisonSummary") or {}) == before_summary
    assert after_confirm["files"]["reocrPreviewReport"]["filename"].endswith(".xlsx")
    assert after_confirm["reocrReplayGovernance"]["activeCandidates"][0]["decision"] == "active"

    candidate_id = after_confirm["reocrReplayGovernance"]["activeCandidates"][0]["candidateId"]
    applied = client.post(
        f"/api/labor/runs/{run['id']}/reocr-candidates/{candidate_id}/apply",
        json={"appliedBy": "ops-user", "reason": "preview report reviewed"},
    )

    assert applied.status_code == 200
    applied_body = applied.json()
    assert applied_body["decision"] == "applied"
    assert applied_body["comparisonSummary"]["reocrCandidateApplied"] is True
    assert applied_body["reportFile"]["label"] == "差异报告"
    assert applied_body["preflight"]["willOverwriteOfficialResult"] is True
    assert applied_body["preflight"]["willRegenerateDiffReport"] is True
    assert applied_body["preflight"]["projected"]["pdfAmountTotal"] == 100
    assert applied_body["preflight"]["projected"]["exceptionCount"] == 0
    assert applied_body["preflight"]["affectedScopeCount"] == 1
    assert applied_body["preflight"]["affectedEmployeeCount"] == 1
    assert applied_body["preflight"]["blockingAfterApply"] is False
    assert applied_body["preflight"]["postApplyWarnings"] == []
    assert client.get(applied_body["reportFile"]["downloadUrl"]).status_code == 200
    after_apply = client.get(f"/api/labor/runs/{run['id']}").json()
    assert after_apply["status"] == "已生成差异报告"
    assert after_apply["comparisonSummary"]["pdfAmountTotal"] == 100
    assert after_apply["comparisonSummary"]["exceptionCount"] == 0
    assert after_apply["comparisonRows"][0]["matchStatus"] == "通过"
    assert after_apply["reocrReplayGovernance"]["activeCandidates"][0]["status"] == "applied"
    assert after_apply["files"]["diffReport"]["filename"].endswith(".xlsx")
    assert after_apply["diffDownloadUrl"] == after_apply["files"]["diffReport"]["downloadUrl"]
    assert after_apply["reocrAdoption"]["preflight"] == applied_body["preflight"]

    rolled_back = client.post(
        f"/api/labor/runs/{run['id']}/reocr-candidates/{candidate_id}/rollback",
        json={"rolledBackBy": "ops-user", "reason": "candidate superseded by corrected OCR file"},
    )

    assert rolled_back.status_code == 200
    rolled_back_body = rolled_back.json()
    assert rolled_back_body["decision"] == "rolled_back"
    assert rolled_back_body["status"] == "rolled_back"
    assert rolled_back_body["rollbackReason"] == "candidate superseded by corrected OCR file"
    assert rolled_back_body["auditTrail"][-1]["action"] == "rolled_back"
    after_rollback = client.get(f"/api/labor/runs/{run['id']}").json()
    assert (after_rollback.get("comparisonSummary") or {}) == before_summary
    assert "diffReport" not in after_rollback.get("files", {})
    assert after_rollback.get("diffDownloadUrl", "") == ""
    assert after_rollback["reocrReplayGovernance"]["activeCandidates"] == []
    assert after_rollback["reocrReplayGovernance"]["rolledBackCandidates"][0]["candidateId"] == candidate_id


def test_labor_material_reocr_plan_short_circuits_expensive_formal_extraction(monkeypatch):
    import bonus_platform.app as app_module

    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "Prompt Staffing", "period_start": "2026-05-18", "period_end": "2026-05-24", "currency": "USD"},
    ).json()
    client.post(
        f"/api/labor/runs/{run['id']}/files",
        files=[
            ("pdf_files", ("DEPT#1.pdf", b"%PDF-1.4\n% image only", "application/pdf")),
            ("pdf_files", ("DEPT#2.pdf", b"%PDF-1.4\n% image only", "application/pdf")),
            ("workbook_files", ("账单.xlsx", _excel_bytes_with_warehouse(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
        ],
    )
    client.post(
        f"/api/labor/runs/{run['id']}/mapping",
        json={
            "sheet_name": "员工账单",
            "mapping": {"name": "姓名", "hours": "时长总计(H)", "amount": "费用总计(含税)", "currency": "币种", "warehouse": "物理仓"},
        },
    )
    app_module.update_labor_metadata(run["id"], {"materialReplaySource": {"batchKey": "prompt"}})

    def fail_if_quick_extract_runs(*args, **kwargs):
        raise AssertionError("quick_extract_totals should not run when material re-OCR tasks are already required")

    monkeypatch.setattr(app_module, "quick_extract_totals", fail_if_quick_extract_runs)
    monkeypatch.setattr(
        app_module,
        "_summarize_pdf_text_coverage",
        lambda paths: {
            "summary": {
                "fileCount": len(paths),
                "textReadableFileCount": 0,
                "imageOnlyFileCount": len(paths),
                "textReadablePageCount": 0,
                "emptyTextPageCount": len(paths),
                "imageOnlyPdfFiles": [path.name for path in paths],
            },
            "files": [
                {
                    "sourceFile": path.name,
                    "pageCount": 1,
                    "readablePageCount": 0,
                    "emptyTextPageCount": 1,
                    "hasTextLayer": False,
                    "needsOcr": True,
                    "diagnostic": "image_only_pdf",
                }
                for path in paths
            ],
        },
    )
    monkeypatch.setattr(
        app_module,
        "build_reocr_candidate_plan",
        lambda *args, **kwargs: {
            "summary": {"taskCount": 1, "reviewableCandidateCount": 0},
            "tasks": [{"sourceFile": "DEPT#1.pdf", "warehouseId": "1", "amountDelta": -100, "expectedExcelAmount": 100}],
            "reviewableCandidates": [],
        },
    )

    updated = app_module._perform_labor_extract_compare(run["id"])

    assert updated["status"] == "待图片识别复核"
    assert updated["stage"] == "待图片识别复核"
    assert updated["reviewQueues"]["primary"] == "reocr"
    assert updated["reviewQueues"]["reocr"]["taskCount"] == 1
    assert updated["extractionQuality"]["level"] == "critical"
    assert updated["pdfExtractedRows"] == []
    assert updated["files"]["diffReport"]["label"] == "待图片识别复核报告"


def test_labor_reocr_batch_preview_and_apply_updates_official_report():
    import bonus_platform.app as app_module

    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "OSS", "period_start": "2026-05-18", "period_end": "2026-05-24", "currency": "USD"},
    ).json()
    replay_1 = {
        "decision": "ready_for_user_confirmation",
        "sourceFile": "elog1.pdf",
        "warehouseId": "1",
        "summary": {"candidateAmountTotal": 100, "expectedExcelAmount": 100, "exceptionCount": 0},
        "comparison": {
            "pdfEmployeeCount": 1,
            "excelEmployeeCount": 1,
            "pdfHoursTotal": 8,
            "excelHoursTotal": 8,
            "pdfAmountTotal": 100,
            "excelAmountTotal": 100,
            "exceptionCount": 0,
            "averageConfidence": 0.95,
        },
        "comparisonRows": [
            {
                "employeeKey": "name:ALICE WORKER",
                "employeeName": "Alice Worker",
                "pdfHoursTotal": 8,
                "excelHoursTotal": 8,
                "hoursDelta": 0,
                "pdfAmountTotal": 100,
                "excelAmountTotal": 100,
                "amountDelta": 0,
                "matchStatus": "通过",
                "riskFlags": [],
                "sourceRefs": "elog1.pdf p1; bill.xlsx row 2",
            }
        ],
        "candidateMatches": [],
    }
    replay_2 = {
        "decision": "ready_for_user_confirmation",
        "sourceFile": "elog2.pdf",
        "warehouseId": "2",
        "summary": {"candidateAmountTotal": 200, "expectedExcelAmount": 200, "exceptionCount": 0},
        "comparison": {
            "pdfEmployeeCount": 1,
            "excelEmployeeCount": 1,
            "pdfHoursTotal": 10,
            "excelHoursTotal": 10,
            "pdfAmountTotal": 200,
            "excelAmountTotal": 200,
            "exceptionCount": 0,
            "averageConfidence": 0.96,
        },
        "comparisonRows": [
            {
                "employeeKey": "name:BOB WORKER",
                "employeeName": "Bob Worker",
                "pdfHoursTotal": 10,
                "excelHoursTotal": 10,
                "hoursDelta": 0,
                "pdfAmountTotal": 200,
                "excelAmountTotal": 200,
                "amountDelta": 0,
                "matchStatus": "通过",
                "riskFlags": [],
                "sourceRefs": "elog2.pdf p1; bill.xlsx row 3",
            }
        ],
        "candidateMatches": [],
    }
    app_module.update_labor_metadata(
        run["id"],
        {
            "comparisonSummary": {"exceptionCount": 4, "pdfAmountTotal": 0, "excelAmountTotal": 300, "amountDeltaTotal": -300},
            "comparisonRows": [],
            "candidateMatches": [],
            "excelMapping": {"name": "姓名", "hours": "工时", "amount": "金额"},
            "reocrPlan": {
                "tasks": [
                    {"sourceFile": "elog1.pdf", "warehouseId": "1"},
                    {"sourceFile": "elog2.pdf", "warehouseId": "2"},
                    {"sourceFile": "elog3.pdf", "warehouseId": "3"},
                ],
                "reviewableCandidates": [],
            },
            "reocrReplayGovernance": {
                "replays": [replay_1, replay_2],
                "activeCandidates": [
                    {"candidateId": "reocr_1", "decision": "active", "status": "active", "sourceFile": "elog1.pdf", "warehouseId": "1", "replay": replay_1},
                    {"candidateId": "reocr_2", "decision": "active", "status": "active", "sourceFile": "elog2.pdf", "warehouseId": "2", "replay": replay_2},
                ],
                "rolledBackCandidates": [],
            },
        },
    )

    preview = client.post(f"/api/labor/runs/{run['id']}/reocr-candidates/batch-preview", json={})
    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["decision"] == "ready_for_batch_apply"
    assert preview_body["summary"]["candidateCount"] == 2
    assert preview_body["summary"]["plannedTaskCount"] == 3
    assert preview_body["summary"]["missingAppliedTaskCount"] == 1
    assert preview_body["coverage"]["missingAppliedTasks"] == [{"sourceFile": "elog3.pdf", "warehouseId": "3"}]
    assert preview_body["comparisonSummary"]["pdfAmountTotal"] == 300
    assert preview_body["preflight"]["willOverwriteOfficialResult"] is True
    assert preview_body["preflight"]["willRegenerateDiffReport"] is True
    assert preview_body["preflight"]["current"]["exceptionCount"] == 4
    assert preview_body["preflight"]["projected"]["exceptionCount"] == 0
    assert preview_body["preflight"]["delta"]["exceptionCount"] == -4
    assert preview_body["preflight"]["delta"]["amountDeltaTotal"] == 300
    assert preview_body["preflight"]["affectedScopeCount"] == 2
    assert preview_body["preflight"]["affectedEmployeeCount"] == 2
    assert preview_body["preflight"]["coverageCompleteAfterApply"] is False
    assert preview_body["preflight"]["blockingAfterApply"] is True
    assert preview_body["preflight"]["postApplyWarnings"] == ["仍有 1 个图片识别复核任务未采纳，交付状态将保持阻断。"]

    applied = client.post(
        f"/api/labor/runs/{run['id']}/reocr-candidates/batch-apply",
        json={"appliedBy": "ops-user", "reason": "all reocr previews reviewed"},
    )
    assert applied.status_code == 200
    body = applied.json()
    assert body["decision"] == "batch_applied"
    assert body["summary"]["candidateCount"] == 2
    assert body["summary"]["missingAppliedTaskCount"] == 1
    assert body["coverage"]["coverageComplete"] is False
    assert body["preflight"] == preview_body["preflight"]
    assert body["reportFile"]["label"] == "差异报告"
    assert client.get(body["reportFile"]["downloadUrl"]).status_code == 200
    refreshed = client.get(f"/api/labor/runs/{run['id']}").json()
    assert refreshed["status"] == "已生成差异报告"
    assert refreshed["comparisonSummary"]["pdfAmountTotal"] == 300
    assert refreshed["comparisonSummary"]["exceptionCount"] == 0
    assert len(refreshed["comparisonRows"]) == 2
    assert {item["status"] for item in refreshed["reocrReplayGovernance"]["activeCandidates"]} == {"applied"}
    assert refreshed["diffDownloadUrl"] == refreshed["files"]["diffReport"]["downloadUrl"]
    assert refreshed["reocrAdoption"]["preflight"] == preview_body["preflight"]


def test_labor_reocr_batch_confirm_promotes_ready_replays_without_applying_result():
    import bonus_platform.app as app_module

    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "OSS", "period_start": "2026-05-18", "period_end": "2026-05-24", "currency": "USD"},
    ).json()
    replay_1 = {
        "decision": "ready_for_user_confirmation",
        "sourceFile": "elog1.pdf",
        "warehouseId": "1",
        "replayedAt": "2026-06-15T00:00:00",
        "summary": {"candidateAmountTotal": 100, "expectedExcelAmount": 100, "exceptionCount": 0},
        "comparison": {"pdfAmountTotal": 100, "excelAmountTotal": 100, "exceptionCount": 0},
        "comparisonRows": [{"employeeName": "Alice Worker", "matchStatus": "通过", "pdfAmountTotal": 100, "excelAmountTotal": 100, "amountDelta": 0}],
        "candidateMatches": [],
    }
    replay_2 = {
        "decision": "ready_for_user_confirmation",
        "sourceFile": "elog2.pdf",
        "warehouseId": "2",
        "replayedAt": "2026-06-15T00:00:01",
        "summary": {"candidateAmountTotal": 200, "expectedExcelAmount": 200, "exceptionCount": 0},
        "comparison": {"pdfAmountTotal": 200, "excelAmountTotal": 200, "exceptionCount": 0},
        "comparisonRows": [{"employeeName": "Bob Worker", "matchStatus": "通过", "pdfAmountTotal": 200, "excelAmountTotal": 200, "amountDelta": 0}],
        "candidateMatches": [],
    }
    replay_blocked = {
        "decision": "blocked_by_replay",
        "sourceFile": "elog3.pdf",
        "warehouseId": "3",
        "summary": {"candidateAmountTotal": 50, "expectedExcelAmount": 75, "exceptionCount": 1},
    }
    app_module.update_labor_metadata(
        run["id"],
        {
            "comparisonSummary": {"exceptionCount": 9, "pdfAmountTotal": 0, "excelAmountTotal": 300},
            "reocrReplayGovernance": {"replays": [replay_1, replay_2, replay_blocked], "activeCandidates": [], "rolledBackCandidates": []},
        },
    )

    confirmed = client.post(
        f"/api/labor/runs/{run['id']}/reocr-candidates/confirm-batch",
        json={"confirmedBy": "ops-user", "reason": "batch replay reviewed", "generateReport": True},
    )

    assert confirmed.status_code == 200
    body = confirmed.json()
    assert body["decision"] == "batch_confirmed"
    assert body["summary"]["confirmedCount"] == 2
    assert body["summary"]["skippedCount"] == 1
    assert body["reportFile"]["label"] == "图片识别批量结果预览报告"
    assert client.get(body["reportFile"]["downloadUrl"]).status_code == 200
    refreshed = client.get(f"/api/labor/runs/{run['id']}").json()
    assert len(refreshed["reocrReplayGovernance"]["activeCandidates"]) == 2
    assert {candidate["status"] for candidate in refreshed["reocrReplayGovernance"]["activeCandidates"]} == {"active"}
    assert refreshed["comparisonSummary"]["exceptionCount"] == 9
    assert refreshed["files"]["reocrPreviewReport"]["filename"].endswith(".xlsx")


def test_labor_readiness_gate_blocks_until_reocr_plan_is_fully_applied():
    import bonus_platform.app as app_module

    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "OSS", "period_start": "2026-05-18", "period_end": "2026-05-24", "currency": "USD"},
    ).json()
    report_url = f"/api/labor/runs/{run['id']}/download/report.xlsx"
    (app_module.get_labor_run_dir(run["id"]) / "report.xlsx").write_bytes(b"report")
    app_module.update_labor_metadata(
        run["id"],
        {
            "status": "已生成差异报告",
            "comparisonSummary": {
                "conclusionLevel": "pass",
                "conclusionMessage": "核对通过",
                "exceptionCount": 0,
                "pdfAmountTotal": 300,
                "excelAmountTotal": 300,
                "amountDeltaTotal": 0,
            },
            "files": {"diffReport": {"filename": "report.xlsx", "downloadUrl": report_url}},
            "diffDownloadUrl": report_url,
            "reocrPlan": {
                "tasks": [
                    {"sourceFile": "elog1.pdf", "warehouseId": "1"},
                    {"sourceFile": "elog2.pdf", "warehouseId": "2"},
                ]
            },
            "reocrReplayGovernance": {
                "activeCandidates": [
                    {"candidateId": "reocr_1", "sourceFile": "elog1.pdf", "warehouseId": "1", "status": "applied", "decision": "applied"},
                    {"candidateId": "reocr_2", "sourceFile": "elog2.pdf", "warehouseId": "2", "status": "active", "decision": "active"},
                ],
                "replays": [],
                "rolledBackCandidates": [],
            },
        },
    )

    blocked = client.get(f"/api/labor/runs/{run['id']}").json()["readinessGate"]
    assert blocked["status"] == "blocked"
    assert blocked["summary"]["reocrPlannedTaskCount"] == 2
    assert blocked["summary"]["reocrAppliedTaskCount"] == 1
    assert any(issue["code"] == "reocr_coverage_incomplete" for issue in blocked["issues"])
    assert any(issue["code"] == "pending_governance_candidates" for issue in blocked["issues"])

    app_module.update_labor_metadata(
        run["id"],
        {
            "reocrReplayGovernance": {
                "activeCandidates": [
                    {"candidateId": "reocr_1", "sourceFile": "elog1.pdf", "warehouseId": "1", "status": "applied", "decision": "applied"},
                    {"candidateId": "reocr_2", "sourceFile": "elog2.pdf", "warehouseId": "2", "status": "applied", "decision": "applied"},
                ],
                "replays": [],
                "rolledBackCandidates": [],
            },
        },
    )

    ready = client.get(f"/api/labor/runs/{run['id']}").json()["readinessGate"]
    assert ready["status"] == "ready"
    assert ready["ready"] is True
    assert ready["summary"]["blockedCount"] == 0
    assert ready["summary"]["pendingGovernanceCount"] == 0


def test_labor_readiness_gate_blocks_confirmed_reocr_when_no_plan_requires_apply_or_rollback():
    import bonus_platform.app as app_module

    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "OSS", "period_start": "2026-05-18", "period_end": "2026-05-24", "currency": "USD"},
    ).json()
    report_url = f"/api/labor/runs/{run['id']}/download/report.xlsx"
    app_module.update_labor_metadata(
        run["id"],
        {
            "status": "已生成差异报告",
            "comparisonSummary": {
                "conclusionLevel": "pass",
                "conclusionMessage": "核对通过",
                "exceptionCount": 0,
                "pdfAmountTotal": 100,
                "excelAmountTotal": 100,
                "amountDeltaTotal": 0,
            },
            "files": {"diffReport": {"filename": "report.xlsx", "downloadUrl": report_url}},
            "diffDownloadUrl": report_url,
            "reocrReplayGovernance": {
                "activeCandidates": [
                    {"candidateId": "reocr_1", "sourceFile": "elog1.pdf", "warehouseId": "1", "status": "active", "decision": "active"}
                ],
                "replays": [],
                "rolledBackCandidates": [],
            },
        },
    )

    gate = client.get(f"/api/labor/runs/{run['id']}").json()["readinessGate"]

    assert gate["status"] == "blocked"
    assert gate["summary"]["confirmedReocrNotAppliedCount"] == 1
    assert any(issue["code"] == "confirmed_reocr_not_applied" for issue in gate["issues"])


def test_labor_readiness_gate_blocks_when_report_file_is_missing():
    import bonus_platform.app as app_module

    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "OSS", "period_start": "2026-05-18", "period_end": "2026-05-24", "currency": "USD"},
    ).json()
    report_url = f"/api/labor/runs/{run['id']}/download/missing-report.xlsx"
    missing_report_path = app_module.get_labor_run_dir(run["id"]) / "missing-report.xlsx"
    app_module.update_labor_metadata(
        run["id"],
        {
            "status": "已生成差异报告",
            "comparisonSummary": {
                "conclusionLevel": "pass",
                "conclusionMessage": "核对通过",
                "exceptionCount": 0,
                "pdfAmountTotal": 100,
                "excelAmountTotal": 100,
                "amountDeltaTotal": 0,
            },
            "files": {
                "diffReport": {
                    "filename": "missing-report.xlsx",
                    "path": str(missing_report_path),
                    "downloadUrl": report_url,
                }
            },
            "diffDownloadUrl": report_url,
        },
    )

    gate = client.get(f"/api/labor/runs/{run['id']}").json()["readinessGate"]

    assert gate["status"] == "blocked"
    assert gate["ready"] is False
    assert any(issue["code"] == "report_file_missing" for issue in gate["issues"])


def test_labor_readiness_gate_blocks_missing_report_even_when_url_mismatches():
    import bonus_platform.app as app_module

    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "OSS", "period_start": "2026-05-18", "period_end": "2026-05-24", "currency": "USD"},
    ).json()
    missing_report_path = app_module.get_labor_run_dir(run["id"]) / "missing-report.xlsx"
    app_module.update_labor_metadata(
        run["id"],
        {
            "status": "已生成差异报告",
            "comparisonSummary": {
                "conclusionLevel": "pass",
                "conclusionMessage": "核对通过",
                "exceptionCount": 0,
                "pdfAmountTotal": 100,
                "excelAmountTotal": 100,
                "amountDeltaTotal": 0,
            },
            "files": {
                "diffReport": {
                    "filename": "missing-report.xlsx",
                    "path": str(missing_report_path),
                    "downloadUrl": f"/api/labor/runs/{run['id']}/download/other-report.xlsx",
                }
            },
            "diffDownloadUrl": f"/api/labor/runs/{run['id']}/download/missing-report.xlsx",
        },
    )

    gate = client.get(f"/api/labor/runs/{run['id']}").json()["readinessGate"]

    assert gate["status"] == "blocked"
    assert any(issue["code"] == "report_url_mismatch" for issue in gate["issues"])
    assert any(issue["code"] == "report_file_missing" for issue in gate["issues"])


def test_labor_reocr_candidate_replay_api_blocks_employee_level_exceptions():
    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "OSS", "period_start": "2026-05-18", "period_end": "2026-05-24", "currency": "USD"},
    ).json()
    client.post(
        f"/api/labor/runs/{run['id']}/files",
        files=[
            ("pdf_files", ("elog1-1_20260520204104.pdf", b"%PDF-1.4\n", "application/pdf")),
            ("workbook_files", ("账单.xlsx", _excel_bytes_with_warehouse(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
        ],
    )
    client.post(
        f"/api/labor/runs/{run['id']}/mapping",
        json={
            "sheet_name": "员工账单",
            "mapping": {
                "employeeId": "工号",
                "name": "姓名",
                "hours": "时长总计(H)",
                "amount": "费用总计(含税)",
                "currency": "币种",
            },
        },
    )

    replay = client.post(
        f"/api/labor/runs/{run['id']}/reocr-candidates/replay",
        json={
            "task": {
                "sourceFile": "elog1-1_20260520204104.pdf",
                "warehouseId": "1",
                "expectedExcelAmount": 100,
                "amountDelta": 50,
            },
            "candidateRows": [
                {
                    "employeeName": "Wrong Worker",
                    "sourcePageOrRow": "p1",
                    "hours": 8,
                    "amount": 100,
                    "currency": "USD",
                    "confidence": 0.96,
                    "evidenceText": "Wrong Worker 8.00 $100.00",
                }
            ],
            "amountTolerance": 0.1,
            "hoursTolerance": 0.1,
            "confidenceThreshold": 0.85,
        },
    )

    assert replay.status_code == 200
    body = replay.json()
    assert body["decision"] == "blocked_by_replay"
    assert body["summary"]["amountPassed"] is True
    assert body["summary"]["exceptionCount"] > 0
    assert body["blockers"] == ["employee_level_exceptions"]
    assert body["exceptionRows"]
    refreshed = client.get(f"/api/labor/runs/{run['id']}").json()
    assert refreshed["reocrReplayGovernance"]["replays"][0]["decision"] == "blocked_by_replay"

    confirmed = client.post(
        f"/api/labor/runs/{run['id']}/reocr-candidates/confirm",
        json={"sourceFile": "elog1-1_20260520204104.pdf", "warehouseId": "1", "confirmedBy": "ops-user"},
    )
    assert confirmed.status_code == 400
    assert "未通过影响预览" in confirmed.json()["detail"]


def test_labor_reocr_candidate_replay_file_api_parses_upload_and_records_candidate_file():
    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "OSS", "period_start": "2026-05-18", "period_end": "2026-05-24", "currency": "USD"},
    ).json()
    client.post(
        f"/api/labor/runs/{run['id']}/files",
        files=[
            ("pdf_files", ("elog1-1_20260520204104.pdf", b"%PDF-1.4\n", "application/pdf")),
            ("workbook_files", ("账单.xlsx", _excel_bytes_with_warehouse(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
        ],
    )
    client.post(
        f"/api/labor/runs/{run['id']}/mapping",
        json={
            "sheet_name": "员工账单",
            "mapping": {
                "employeeId": "工号",
                "name": "姓名",
                "hours": "时长总计(H)",
                "amount": "费用总计(含税)",
                "currency": "币种",
            },
        },
    )

    replay = client.post(
        f"/api/labor/runs/{run['id']}/reocr-candidates/replay-file",
        data={
            "task": json.dumps(
                {
                    "sourceFile": "elog1-1_20260520204104.pdf",
                    "warehouseId": "1",
                    "expectedExcelAmount": 100,
                    "amountDelta": 50,
                }
            ),
            "amount_tolerance": "0.1",
            "hours_tolerance": "0.1",
            "confidence_threshold": "0.85",
        },
        files={"candidate_file": ("reocr.csv", _reocr_csv_bytes(), "text/csv")},
    )

    assert replay.status_code == 200
    body = replay.json()
    assert body["decision"] == "ready_for_user_confirmation"
    assert body["parsedCandidateRowCount"] == 1
    assert body["parsedCandidateRows"][0]["employeeName"] == "Alice Worker"
    refreshed = client.get(f"/api/labor/runs/{run['id']}").json()
    assert refreshed["reocrReplayGovernance"]["replays"][0]["candidateFile"] == "reocr.csv"
    assert refreshed["files"]["reocrCandidateFiles"][0]["filename"].endswith(".csv")


def test_labor_reocr_candidate_replay_cache_uses_local_ai_cache_without_applying_result():
    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "OSS", "period_start": "2026-05-18", "period_end": "2026-05-24", "currency": "USD"},
    ).json()
    upload = client.post(
        f"/api/labor/runs/{run['id']}/files",
        files=[
            ("pdf_files", ("elog1-1_20260520204104.pdf", b"%PDF-1.4\n", "application/pdf")),
            ("workbook_files", ("账单.xlsx", _excel_bytes_with_warehouse(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
        ],
    ).json()
    client.post(
        f"/api/labor/runs/{run['id']}/mapping",
        json={
            "sheet_name": "员工账单",
            "mapping": {
                "employeeId": "工号",
                "name": "姓名",
                "hours": "时长总计(H)",
                "amount": "费用总计(含税)",
                "currency": "币种",
            },
        },
    )
    pdf_path = Path(upload["files"]["pdfInvoices"][0]["path"])
    cache_dir = pdf_path.parent / ".ai_extract_cache"
    cache_dir.mkdir(exist_ok=True)
    cache_path = cache_dir / f"{pdf_path.stem}_p1_mimo-v2.5_v4.json"
    cache_path.write_text(
        json.dumps(
            [
                {
                    "source_file": pdf_path.name,
                    "source_page_or_row": "1",
                    "employee_name_raw": "Alice Worker",
                    "hours": 8,
                    "amount": 100,
                    "currency": "USD",
                    "confidence": 0.95,
                    "evidence_text": "Alice Worker | Reg Time 8.00 | TOTAL $100.00",
                    "warehouse_id": "1",
                }
            ]
        ),
        encoding="utf-8",
    )

    replay = client.post(
        f"/api/labor/runs/{run['id']}/reocr-candidates/replay-cache",
        json={
            "task": {
                "sourceFile": pdf_path.name,
                "warehouseId": "1",
                "expectedExcelAmount": 100,
                "amountDelta": 0,
            }
        },
    )

    assert replay.status_code == 200
    body = replay.json()
    assert body["mode"] == "ai_cache_candidate_replay"
    assert body["candidateSource"] == "local_ai_page_cache"
    assert body["decision"] == "ready_for_user_confirmation"
    assert body["summary"]["candidateRowCount"] == 1
    assert body["cacheFiles"] == [cache_path.name]
    refreshed = client.get(f"/api/labor/runs/{run['id']}").json()
    assert refreshed["reocrReplayGovernance"]["replays"][0]["mode"] == "ai_cache_candidate_replay"
    assert "comparisonSummary" not in refreshed


def test_labor_reocr_candidate_batch_replay_cache_records_each_candidate_without_confirming():
    import bonus_platform.app as app_module

    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "OSS", "period_start": "2026-05-18", "period_end": "2026-05-24", "currency": "USD"},
    ).json()
    upload = client.post(
        f"/api/labor/runs/{run['id']}/files",
        files=[
            ("pdf_files", ("elog1-1_20260520204104.pdf", b"%PDF-1.4\n", "application/pdf")),
            ("pdf_files", ("elog2-2_20260520204104.pdf", b"%PDF-1.4\n", "application/pdf")),
            ("workbook_files", ("账单.xlsx", _excel_bytes_with_two_warehouses(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
        ],
    ).json()
    client.post(
        f"/api/labor/runs/{run['id']}/mapping",
        json={
            "sheet_name": "员工账单",
            "mapping": {
                "employeeId": "工号",
                "name": "姓名",
                "hours": "时长总计(H)",
                "amount": "费用总计(含税)",
                "currency": "币种",
            },
        },
    )
    pdf_paths = [Path(record["path"]) for record in upload["files"]["pdfInvoices"]]
    for pdf_path, name, hours, amount, warehouse in [
        (pdf_paths[0], "Alice Worker", 8, 100, "1"),
        (pdf_paths[1], "Wrong Worker", 10, 200, "2"),
    ]:
        cache_dir = pdf_path.parent / ".ai_extract_cache"
        cache_dir.mkdir(exist_ok=True)
        (cache_dir / f"{pdf_path.stem}_p1_mimo-v2.5_v4.json").write_text(
            json.dumps(
                [
                    {
                        "source_file": pdf_path.name,
                        "source_page_or_row": "1",
                        "employee_name_raw": name,
                        "hours": hours,
                        "amount": amount,
                        "currency": "USD",
                        "confidence": 0.95,
                        "evidence_text": f"{name} | TOTAL ${amount:.2f}",
                        "warehouse_id": warehouse,
                    }
                ]
            ),
            encoding="utf-8",
        )

    app_module.update_labor_metadata(
        run["id"],
        {
            "reocrPlan": {
                "reviewableCandidates": [
                    {"sourceFile": pdf_paths[0].name, "warehouseId": "1", "currentCacheAmount": 100, "expectedExcelAmount": 100, "amountDelta": 0},
                    {"sourceFile": pdf_paths[1].name, "warehouseId": "2", "currentCacheAmount": 200, "expectedExcelAmount": 200, "amountDelta": 0},
                ]
            }
        },
    )

    replay = client.post(f"/api/labor/runs/{run['id']}/reocr-candidates/replay-cache-batch", json={})

    assert replay.status_code == 200
    body = replay.json()
    assert body["decision"] == "batch_cache_replay_completed"
    assert body["summary"]["candidateCount"] == 2
    assert body["summary"]["replayedCount"] == 2
    assert body["summary"]["readyCount"] == 1
    assert body["summary"]["blockedCount"] == 1
    assert body["summary"]["errorCount"] == 0
    refreshed = client.get(f"/api/labor/runs/{run['id']}").json()
    assert [item["mode"] for item in refreshed["reocrReplayGovernance"]["replays"]] == ["ai_cache_candidate_replay", "ai_cache_candidate_replay"]
    assert refreshed["reocrReplayGovernance"].get("activeCandidates", []) == []
    assert "comparisonSummary" not in refreshed


def test_labor_reocr_candidate_template_api_generates_downloadable_csv_from_excel_rows():
    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "OSS", "period_start": "2026-05-18", "period_end": "2026-05-24", "currency": "USD"},
    ).json()
    client.post(
        f"/api/labor/runs/{run['id']}/files",
        files=[
            ("pdf_files", ("elog1-1_20260520204104.pdf", b"%PDF-1.4\n", "application/pdf")),
            ("workbook_files", ("账单.xlsx", _excel_bytes_with_warehouse(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
        ],
    )
    client.post(
        f"/api/labor/runs/{run['id']}/mapping",
        json={
            "sheet_name": "员工账单",
            "mapping": {
                "employeeId": "工号",
                "name": "姓名",
                "hours": "时长总计(H)",
                "amount": "费用总计(含税)",
                "currency": "币种",
            },
        },
    )

    response = client.post(
        f"/api/labor/runs/{run['id']}/reocr-candidates/template",
        json={"task": {"sourceFile": "elog1-1_20260520204104.pdf", "warehouseId": "1"}},
    )

    assert response.status_code == 200
    template = response.json()
    assert template["label"] == "图片识别结果模板"
    assert template["filename"].endswith(".csv")
    downloaded = client.get(template["downloadUrl"])
    assert downloaded.status_code == 200
    text = downloaded.content.decode("utf-8-sig")
    assert "SourceFile,WarehouseId,EmployeeId,Employee,Hours,Amount,Page,Confidence,Currency,Evidence,ExcelRef,ExpectedHours,ExpectedAmount" in text
    assert "elog1-1_20260520204104.pdf,1,WUS000001,Alice Worker,8.00,100.00,,0.95,USD" in text
    assert "员工账单!2,8.00,100.00" in text
    refreshed = client.get(f"/api/labor/runs/{run['id']}").json()
    assert refreshed["files"]["reocrCandidateTemplates"][0]["filename"] == template["filename"]


def test_labor_reocr_candidate_batch_template_api_exports_all_task_rows():
    import bonus_platform.app as app_module

    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "OSS", "period_start": "2026-05-18", "period_end": "2026-05-24", "currency": "USD"},
    ).json()
    client.post(
        f"/api/labor/runs/{run['id']}/files",
        files=[
            ("pdf_files", ("elog1-1_20260520204104.pdf", b"%PDF-1.4\n", "application/pdf")),
            ("pdf_files", ("elog2-2_20260520204104.pdf", b"%PDF-1.4\n", "application/pdf")),
            ("workbook_files", ("账单.xlsx", _excel_bytes_with_two_warehouses(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
        ],
    )
    client.post(
        f"/api/labor/runs/{run['id']}/mapping",
        json={
            "sheet_name": "员工账单",
            "mapping": {
                "employeeId": "工号",
                "name": "姓名",
                "hours": "时长总计(H)",
                "amount": "费用总计(含税)",
                "currency": "币种",
            },
        },
    )
    app_module.update_labor_metadata(
        run["id"],
        {
            "reocrPlan": {
                "tasks": [
                    {"sourceFile": "elog1-1_20260520204104.pdf", "warehouseId": "1"},
                    {"sourceFile": "elog2-2_20260520204104.pdf", "warehouseId": "2"},
                ]
            }
        },
    )

    response = client.post(f"/api/labor/runs/{run['id']}/reocr-candidates/template-batch", json={})

    assert response.status_code == 200
    template = response.json()
    assert template["label"] == "图片识别批量结果模板"
    assert template["summary"] == {"taskCount": 2, "rowCount": 2, "missingTaskCount": 0}
    downloaded = client.get(template["downloadUrl"])
    assert downloaded.status_code == 200
    text = downloaded.content.decode("utf-8-sig")
    assert "SourceFile,WarehouseId,EmployeeId,Employee,Hours,Amount,Page,Confidence,Currency,Evidence,ExcelRef,ExpectedHours,ExpectedAmount" in text
    assert "elog1-1_20260520204104.pdf,1,WUS000001,Alice Worker,8.00,100.00,,0.95,USD" in text
    assert "elog2-2_20260520204104.pdf,2,WUS000002,Bob Worker,10.00,200.00,,0.95,USD" in text
    assert "员工账单!2,8.00,100.00" in text
    assert "员工账单!3,10.00,200.00" in text
    refreshed = client.get(f"/api/labor/runs/{run['id']}").json()
    assert refreshed["files"]["reocrCandidateTemplates"][0]["filename"] == template["filename"]


def test_labor_reocr_candidate_batch_upload_replays_each_source_scope_without_confirming():
    import bonus_platform.app as app_module

    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "OSS", "period_start": "2026-05-18", "period_end": "2026-05-24", "currency": "USD"},
    ).json()
    client.post(
        f"/api/labor/runs/{run['id']}/files",
        files=[
            ("pdf_files", ("elog1-1_20260520204104.pdf", b"%PDF-1.4\n", "application/pdf")),
            ("pdf_files", ("elog2-2_20260520204104.pdf", b"%PDF-1.4\n", "application/pdf")),
            ("workbook_files", ("账单.xlsx", _excel_bytes_with_two_warehouses(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
        ],
    )
    client.post(
        f"/api/labor/runs/{run['id']}/mapping",
        json={
            "sheet_name": "员工账单",
            "mapping": {
                "employeeId": "工号",
                "name": "姓名",
                "hours": "时长总计(H)",
                "amount": "费用总计(含税)",
                "currency": "币种",
            },
        },
    )
    app_module.update_labor_metadata(
        run["id"],
        {
            "reocrPlan": {
                "tasks": [
                    {"sourceFile": "elog1-1_20260520204104.pdf", "warehouseId": "1", "expectedExcelAmount": 100, "amountDelta": 0},
                    {"sourceFile": "elog2-2_20260520204104.pdf", "warehouseId": "2", "expectedExcelAmount": 200, "amountDelta": 0},
                ]
            }
        },
    )

    replay = client.post(
        f"/api/labor/runs/{run['id']}/reocr-candidates/replay-file-batch",
        files={"candidate_file": ("filled_batch.csv", _reocr_batch_csv_bytes(), "text/csv")},
    )

    assert replay.status_code == 200
    body = replay.json()
    assert body["decision"] == "batch_file_replay_completed"
    assert body["summary"]["groupCount"] == 2
    assert body["summary"]["replayedCount"] == 2
    assert body["summary"]["readyCount"] == 1
    assert body["summary"]["blockedCount"] == 1
    assert body["summary"]["errorCount"] == 0
    assert body["summary"]["parsedRowCount"] == 2
    assert body["summary"]["plannedTaskCount"] == 2
    assert body["summary"]["coveredTaskCount"] == 2
    assert body["summary"]["missingTaskCount"] == 0
    assert body["summary"]["extraScopeCount"] == 0
    assert body["coverage"]["coverageComplete"] is True
    assert body["coverage"]["missingTasks"] == []
    refreshed = client.get(f"/api/labor/runs/{run['id']}").json()
    assert len(refreshed["reocrReplayGovernance"]["replays"]) == 2
    assert {item["decision"] for item in refreshed["reocrReplayGovernance"]["replays"]} == {"ready_for_user_confirmation", "blocked_by_replay"}
    assert refreshed["reocrReplayGovernance"].get("activeCandidates", []) == []
    assert refreshed["files"]["reocrCandidateFiles"][0]["label"] == "图片识别批量结果文件"
    assert "comparisonSummary" not in refreshed


def test_labor_reocr_candidate_batch_upload_reports_missing_planned_tasks():
    import bonus_platform.app as app_module

    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "OSS", "period_start": "2026-05-18", "period_end": "2026-05-24", "currency": "USD"},
    ).json()
    client.post(
        f"/api/labor/runs/{run['id']}/files",
        files=[
            ("pdf_files", ("elog1-1_20260520204104.pdf", b"%PDF-1.4\n", "application/pdf")),
            ("pdf_files", ("elog2-2_20260520204104.pdf", b"%PDF-1.4\n", "application/pdf")),
            ("workbook_files", ("账单.xlsx", _excel_bytes_with_two_warehouses(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
        ],
    )
    client.post(
        f"/api/labor/runs/{run['id']}/mapping",
        json={
            "sheet_name": "员工账单",
            "mapping": {
                "employeeId": "工号",
                "name": "姓名",
                "hours": "时长总计(H)",
                "amount": "费用总计(含税)",
                "currency": "币种",
            },
        },
    )
    app_module.update_labor_metadata(
        run["id"],
        {
            "reocrPlan": {
                "tasks": [
                    {"sourceFile": "elog1-1_20260520204104.pdf", "warehouseId": "1", "expectedExcelAmount": 100, "amountDelta": 0},
                    {"sourceFile": "elog2-2_20260520204104.pdf", "warehouseId": "2", "expectedExcelAmount": 200, "amountDelta": 0},
                ]
            }
        },
    )
    partial_csv = (
        "SourceFile,WarehouseId,EmployeeId,Employee,Hours,Amount,Page,Confidence,Currency,Evidence\n"
        "elog1-1_20260520204104.pdf,1,WUS000001,Alice Worker,8,100,p1,96%,USD,Alice Worker 8 $100\n"
    ).encode("utf-8")

    replay = client.post(
        f"/api/labor/runs/{run['id']}/reocr-candidates/replay-file-batch",
        files={"candidate_file": ("partial_batch.csv", partial_csv, "text/csv")},
    )

    assert replay.status_code == 200
    body = replay.json()
    assert body["summary"]["plannedTaskCount"] == 2
    assert body["summary"]["coveredTaskCount"] == 1
    assert body["summary"]["missingTaskCount"] == 1
    assert body["coverage"]["coverageComplete"] is False
    assert body["coverage"]["missingTasks"] == [{"sourceFile": "elog2-2_20260520204104.pdf", "warehouseId": "2"}]
    refreshed = client.get(f"/api/labor/runs/{run['id']}").json()
    assert refreshed["files"]["reocrCandidateFiles"][0]["coverage"]["missingTasks"] == body["coverage"]["missingTasks"]


def test_labor_reocr_candidate_template_upload_confirm_end_to_end_flow():
    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "OSS", "period_start": "2026-05-18", "period_end": "2026-05-24", "currency": "USD"},
    ).json()
    client.post(
        f"/api/labor/runs/{run['id']}/files",
        files=[
            ("pdf_files", ("elog1-1_20260520204104.pdf", b"%PDF-1.4\n", "application/pdf")),
            ("workbook_files", ("账单.xlsx", _excel_bytes_with_warehouse(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
        ],
    )
    client.post(
        f"/api/labor/runs/{run['id']}/mapping",
        json={
            "sheet_name": "员工账单",
            "mapping": {
                "employeeId": "工号",
                "name": "姓名",
                "hours": "时长总计(H)",
                "amount": "费用总计(含税)",
                "currency": "币种",
            },
        },
    )
    task = {"sourceFile": "elog1-1_20260520204104.pdf", "warehouseId": "1", "expectedExcelAmount": 100, "amountDelta": 50}

    template = client.post(
        f"/api/labor/runs/{run['id']}/reocr-candidates/template",
        json={"task": task},
    ).json()
    template_bytes = client.get(template["downloadUrl"]).content

    replay = client.post(
        f"/api/labor/runs/{run['id']}/reocr-candidates/replay-file",
        data={
            "task": json.dumps(task),
            "amount_tolerance": "0.1",
            "hours_tolerance": "0.1",
            "confidence_threshold": "0.85",
        },
        files={"candidate_file": ("filled_reocr_template.csv", template_bytes, "text/csv")},
    )

    assert replay.status_code == 200
    assert replay.json()["decision"] == "ready_for_user_confirmation"

    confirmed = client.post(
        f"/api/labor/runs/{run['id']}/reocr-candidates/confirm",
        json={
            "sourceFile": task["sourceFile"],
            "warehouseId": task["warehouseId"],
            "confirmedBy": "ops-user",
            "reason": "template upload replay passed",
            "generateReport": True,
        },
    )

    assert confirmed.status_code == 200
    body = confirmed.json()
    assert body["decision"] == "active"
    assert body["reportFile"]["label"] == "图片识别结果预览报告"
    assert client.get(body["reportFile"]["downloadUrl"]).status_code == 200
    refreshed = client.get(f"/api/labor/runs/{run['id']}").json()
    assert refreshed["files"]["reocrCandidateTemplates"][0]["filename"].endswith(".csv")
    assert refreshed["files"]["reocrCandidateFiles"][0]["filename"].endswith(".csv")
    assert refreshed["files"]["reocrPreviewReport"]["filename"].endswith(".xlsx")
    assert refreshed["reocrReplayGovernance"]["activeCandidates"][0]["confirmationReason"] == "template upload replay passed"


def test_labor_rule_candidate_auto_replay_uses_historical_run_metadata(monkeypatch):
    import bonus_platform.app as app_module

    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "OSS", "period_start": "2026-05-18", "period_end": "2026-05-24", "currency": "USD"},
    ).json()
    monkeypatch.setattr(
        app_module,
        "list_labor_metadata",
        lambda: [
            {
                "id": run["id"],
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
                "id": "fairway_clean",
                "supplierName": "Fairway",
                "periodStart": "2026-05-11",
                "periodEnd": "2026-05-17",
                "reconciliationDiagnostics": {"level": "ok", "issues": []},
                "comparisonSummary": {"exceptionCount": 0},
            },
        ],
    )

    client.post(
        f"/api/labor/runs/{run['id']}/rule-candidates",
        json={
            "ruleId": "oss-hash-warehouse-v1",
            "title": "OSS # warehouse id extraction",
            "description": "Parse #N warehouse id from invoice filenames.",
            "source": "real replay: oss 2",
            "conditions": {"supplier": "OSS", "fixIssueCodes": ["missing_warehouse_id"]},
        },
    )

    replay = client.post(
        f"/api/labor/runs/{run['id']}/rule-candidates/oss-hash-warehouse-v1/auto-replay",
        json={"limit": 10},
    )

    assert replay.status_code == 200
    assert replay.json()["mode"] == "metadata_signal_replay"
    assert replay.json()["decision"] == "ready_for_user_confirmation"
    assert replay.json()["summary"]["fixedCount"] == 1
    assert replay.json()["summary"]["regressionCount"] == 0

    confirmed = client.post(
        f"/api/labor/runs/{run['id']}/rule-candidates/oss-hash-warehouse-v1/confirm",
        json={"confirmedBy": "ops-user", "reason": "auto replay clean"},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["decision"] == "active"


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
            ("workbook_files", ("账单.xlsx", _excel_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
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


def test_labor_compare_uses_excel_candidates_on_initial_extract(monkeypatch):
    import bonus_platform.app as app_module

    monkeypatch.setattr(app_module, "quick_extract_totals", lambda *args, **kwargs: [])

    calls = []

    def fake_extract(*args, **kwargs):
        calls.append(kwargs)
        return [
            LaborLineItem(source_type="pdf_invoice", source_file="scan.pdf", source_page_or_row="p1", employee_id="", employee_name_raw="Rosa Alvarez Minchaca", hours=31.19, amount=701.90, currency="USD", confidence=0.9, evidence_text="initial")
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
            ("workbook_files", ("账单.xlsx", _excel_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
        ],
    )
    client.post(
        f"/api/labor/runs/{run['id']}/mapping",
        json={"sheet_name": "员工账单", "mapping": {"employeeId": "工号", "name": "姓名", "hours": "时长总计(H)", "amount": "费用总计(含税)", "currency": "币种"}},
    )

    response = client.post(f"/api/labor/runs/{run['id']}/extract-and-compare")

    assert response.status_code == 200
    body = client.get(f"/api/labor/runs/{run['id']}").json()
    assert len(calls) == 1
    assert calls[0]["expected_rows"][0]["employee_name"] == "Rosa Alvarez Minchaca"
    assert body["extractionQuality"]["level"] == "ok"
    assert body["extractionQuality"].get("retryApplied") is not True
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
            ("workbook_files", ("账单.xlsx", _excel_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
        ],
    )
    client.post(
        f"/api/labor/runs/{run['id']}/mapping",
        json={"sheet_name": "员工账单", "mapping": {"employeeId": "工号", "name": "姓名", "hours": "时长总计(H)", "amount": "费用总计(含税)", "currency": "币种"}},
    )

    response = client.post(f"/api/labor/runs/{run['id']}/extract-and-compare").json()

    assert response["status"] == "抽取中"
    assert queued.get("completed") == run["id"]


def test_labor_upload_syncs_files_to_supabase_storage(monkeypatch, tmp_path):
    from bonus_platform.engine.labor import runs as labor_runs

    monkeypatch.setattr(labor_runs, "LABOR_RUNS_DIR", tmp_path / "labor_runs")
    monkeypatch.setenv("SIGMA_LABOR_STORAGE_BACKEND", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role")
    monkeypatch.setenv("SIGMA_LABOR_SUPABASE_BUCKET", "labor-uat")
    synced = []

    def fake_sync(run_id, run_dir):
        synced.append((run_id, sorted(path.name for path in run_dir.iterdir() if path.is_file())))

    monkeypatch.setattr(labor_runs, "sync_labor_run_to_persistent", fake_sync)

    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "ONESOURCE", "period_start": "2026-06-17", "period_end": "2026-06-17", "currency": "USD"},
    ).json()

    response = client.post(
        f"/api/labor/runs/{run['id']}/files",
        files=[
            ("pdf_files", ("invoice.pdf", b"%PDF-1.4\n", "application/pdf")),
            ("workbook_files", ("bill.xlsx", _excel_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
        ],
    )

    assert response.status_code == 200
    assert response.json()["storage"]["backend"] == "supabase"
    assert any("metadata.json" in names and any(name.endswith(".pdf") for name in names) for _, names in synced)


def test_labor_extract_task_restores_persistent_files_before_processing(monkeypatch, tmp_path):
    from bonus_platform.engine.labor import runs as labor_runs

    labor_root = tmp_path / "labor_runs"
    monkeypatch.setattr(labor_runs, "LABOR_RUNS_DIR", labor_root)
    monkeypatch.setenv("SIGMA_LABOR_STORAGE_BACKEND", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role")
    monkeypatch.setenv("SIGMA_LABOR_SUPABASE_BUCKET", "labor-uat")

    snapshots = {}

    def fake_sync_to(run_id, run_dir):
        snapshots[run_id] = {
            path.relative_to(run_dir).as_posix(): path.read_bytes()
            for path in run_dir.rglob("*")
            if path.is_file()
        }

    def fake_sync_from(run_id, run_dir):
        for relative, content in snapshots.get(run_id, {}).items():
            target = run_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        return bool(snapshots.get(run_id))

    def fake_sync_metadata(run_id, run_dir, metadata):
        snapshots.setdefault(run_id, {})["metadata.json"] = json.dumps(metadata, ensure_ascii=False).encode("utf-8")

    monkeypatch.setattr(labor_runs, "sync_labor_run_to_persistent", fake_sync_to)
    monkeypatch.setattr(labor_runs, "sync_labor_metadata_to_persistent", fake_sync_metadata)
    monkeypatch.setattr(app_module, "sync_labor_run_from_persistent", fake_sync_from)

    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "ONESOURCE", "period_start": "2026-06-17", "period_end": "2026-06-17", "currency": "USD"},
    ).json()
    client.post(
        f"/api/labor/runs/{run['id']}/files",
        files=[
            ("pdf_files", ("invoice.pdf", b"%PDF-1.4\n", "application/pdf")),
            ("workbook_files", ("bill.xlsx", _excel_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
        ],
    )
    client.post(
        f"/api/labor/runs/{run['id']}/mapping",
        json={"sheet_name": "员工账单", "mapping": {"employeeId": "工号", "name": "姓名", "hours": "时长总计(H)", "amount": "费用总计(含税)", "currency": "币种"}},
    )

    run_dir = labor_runs.get_labor_run_dir(run["id"])
    for path in run_dir.glob("*"):
        if path.is_file() and path.name != "metadata.json":
            path.unlink()

    def fake_perform(run_id):
        metadata = labor_runs.load_labor_metadata(labor_runs.get_labor_run_dir(run_id))
        files = metadata["files"]
        assert Path(files["pdfInvoices"][0]["path"]).exists()
        assert Path(files["workbooks"][0]["path"]).exists()
        app_module.update_labor_metadata(
            run_id,
            {
                "status": "已生成差异报告",
                "stage": "生成报告",
                "diffDownloadUrl": "/api/labor/runs/fake/download/report.xlsx",
            },
        )

    monkeypatch.setattr(app_module, "_perform_labor_extract_compare", fake_perform)

    app_module._run_labor_extract_compare(run["id"])

    refreshed = client.get(f"/api/labor/runs/{run['id']}").json()
    assert refreshed["asyncTask"]["status"] == "completed"
    assert refreshed["asyncTask"]["statusLabel"] == "完成"


def test_labor_extract_endpoint_returns_queued_task_status(monkeypatch):
    monkeypatch.setattr(app_module, "_run_labor_extract_compare", lambda run_id: None)

    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "ONESOURCE", "period_start": "2026-06-17", "period_end": "2026-06-17", "currency": "USD"},
    ).json()
    client.post(
        f"/api/labor/runs/{run['id']}/files",
        files=[
            ("pdf_files", ("invoice.pdf", b"%PDF-1.4\n", "application/pdf")),
            ("workbook_files", ("bill.xlsx", _excel_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
        ],
    )
    client.post(
        f"/api/labor/runs/{run['id']}/mapping",
        json={"sheet_name": "员工账单", "mapping": {"employeeId": "工号", "name": "姓名", "hours": "时长总计(H)", "amount": "费用总计(含税)", "currency": "币种"}},
    )

    response = client.post(f"/api/labor/runs/{run['id']}/extract-and-compare")

    assert response.status_code == 200
    body = response.json()
    assert body["asyncTask"]["status"] == "queued"
    assert body["asyncTask"]["statusLabel"] == "待处理"


def test_labor_extract_endpoint_reuses_running_task(monkeypatch):
    def fail_if_started(run_id):
        raise AssertionError("running task should not be started twice")

    monkeypatch.setattr(app_module, "_run_labor_extract_compare", fail_if_started)

    client = TestClient(app)
    run = client.post(
        "/api/labor/runs",
        json={"supplier_name": "ONESOURCE", "period_start": "2026-06-17", "period_end": "2026-06-17", "currency": "USD"},
    ).json()
    client.post(
        f"/api/labor/runs/{run['id']}/files",
        files=[
            ("pdf_files", ("invoice.pdf", b"%PDF-1.4\n", "application/pdf")),
            ("workbook_files", ("bill.xlsx", _excel_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
        ],
    )
    client.post(
        f"/api/labor/runs/{run['id']}/mapping",
        json={"sheet_name": "员工账单", "mapping": {"employeeId": "工号", "name": "姓名", "hours": "时长总计(H)", "amount": "费用总计(含税)", "currency": "币种"}},
    )
    app_module.update_labor_metadata(
        run["id"],
        {
            "status": "抽取中",
            "asyncTask": {
                "status": "running",
                "statusLabel": "处理中",
                "message": "后台正在生成核对结果。",
            },
        },
    )

    response = client.post(f"/api/labor/runs/{run['id']}/extract-and-compare")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "抽取中"
    assert body["asyncTask"]["status"] == "running"


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
    assert AI_CONFIG["parallel_max_workers"] == 1
    assert AI_CONFIG["parallel_image_render_workers"] == 1


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
