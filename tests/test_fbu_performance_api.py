from io import BytesIO

from fastapi.testclient import TestClient
from openpyxl import load_workbook
from openpyxl import Workbook

import bonus_platform.app as app_module
from bonus_platform.engine.fbu_performance.runs import FBURosterStore, FBURunManager


def _workbook_bytes(workbook: Workbook) -> bytes:
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _roster_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["header"] * 123)
    row = [""] * 123
    row[0] = "Ana Roster"
    row[3] = "E001"
    row[19] = "HRAS人力综合条线"
    row[20] = "FBU HRBP Dept."
    row[89] = "US-West"
    row[122] = "蓝领"
    sheet.append(row)
    return _workbook_bytes(workbook)


def _attendance_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "sheet1"
    sheet.append(["header"] * 118)
    row = [""] * 118
    row[0] = "2026-04-01"
    row[1] = "Ana Attendance"
    row[2] = "E001"
    row[21] = "08:00"
    row[117] = 8
    sheet.append(row)
    return _workbook_bytes(workbook)


def _adjustment_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "调薪拆分"
    sheet.append(["header"] * 32)
    row = [""] * 32
    row[3] = "zt001"
    row[4] = "Ana Roster"
    row[9] = "4.26-4.30"
    row[28] = 500
    row[31] = "调薪后"
    sheet.append(row)
    return _workbook_bytes(workbook)


def test_base_roster_is_reused_by_new_fbu_activity(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "FBU_PERFORMANCE_RUNS_DIR", tmp_path)
    monkeypatch.setattr(app_module, "fbu_run_manager", FBURunManager(str(tmp_path)))
    monkeypatch.setattr(app_module, "fbu_roster_store", FBURosterStore(str(tmp_path)))

    client = TestClient(app_module.app)

    roster_response = client.post(
        "/api/fbu-performance/roster",
        files={"file": ("roster.xlsx", _roster_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert roster_response.status_code == 200
    assert roster_response.json()["roster"]["total_employees"] == 1

    run_response = client.post("/api/fbu-performance/runs", json={"calc_month": "2026-04"})
    assert run_response.status_code == 200
    run_id = run_response.json()["run_id"]
    assert run_response.json()["roster_source"] == "base"

    attendance_response = client.post(
        "/api/fbu-performance/import-attendance",
        data={"calc_month": "2026-04", "run_id": run_id},
        files={"file": ("attendance.xlsx", _attendance_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert attendance_response.status_code == 200
    employee = attendance_response.json()["preview"]["employees"][0]
    assert employee["name"] == "Ana Roster"
    assert employee["department"] == "HRAS人力综合条线-FBU HRBP Dept."
    assert employee["area"] == "US-West"
    assert employee["job_type"] == "functional"
    assert employee["roster_matched"] is True


def test_fbu_adjustment_upload_is_saved_as_optional_run_data(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "FBU_PERFORMANCE_RUNS_DIR", tmp_path)
    monkeypatch.setattr(app_module, "fbu_run_manager", FBURunManager(str(tmp_path)))
    monkeypatch.setattr(app_module, "fbu_roster_store", FBURosterStore(str(tmp_path)))

    client = TestClient(app_module.app)

    run_response = client.post("/api/fbu-performance/runs", json={"calc_month": "2026-04"})
    assert run_response.status_code == 200
    run_id = run_response.json()["run_id"]

    adjustment_response = client.post(
        "/api/fbu-performance/import-adjustments",
        data={"run_id": run_id},
        files={"file": ("adjustments.xlsx", _adjustment_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert adjustment_response.status_code == 200
    payload = adjustment_response.json()
    assert payload["preview"]["summary"]["total_employees"] == 1
    assert payload["preview"]["summary"]["active_performance_base"] == 500

    run_detail = client.get(f"/api/fbu-performance/runs/{run_id}").json()
    assert run_detail["adjustment_file"] == "adjustments.xlsx"
    assert run_detail["adjustment_data"]["employees"][0]["segments"][0]["reason"] == "调薪后"


def test_fbu_adjustment_template_download_returns_workbook(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "EXPORT_DIR", tmp_path)

    client = TestClient(app_module.app)

    response = client.get("/api/fbu-performance/templates/adjustments/download")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert response.content[:2] == b"PK"

    workbook = load_workbook(BytesIO(response.content), data_only=True)
    assert workbook.sheetnames == ["调薪拆分", "填写示例"]
    main_sheet = workbook["调薪拆分"]
    assert [main_sheet.cell(1, col).value for col in range(1, 7)] == [
        "工号",
        "姓名",
        "分段期间",
        "分段绩效基数",
        "核算标识",
        "备注",
    ]
    assert main_sheet.cell(2, 1).value is None
    validations = list(main_sheet.data_validations.dataValidation)
    assert len(validations) == 1
    assert validations[0].type == "list"
    assert validations[0].formula1 == '"调薪前,调薪后"'
    assert "E2:E1000" in str(validations[0].sqref)
    assert workbook["填写示例"].cell(2, 1).value == "zt0021990"
