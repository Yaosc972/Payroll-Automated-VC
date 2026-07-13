from io import BytesIO

from fastapi.testclient import TestClient
from openpyxl import load_workbook
from openpyxl import Workbook

import bonus_platform.app as app_module
from bonus_platform.engine.fbu_performance.engines.base import EmployeeData
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


def _attendance_bytes_for_rows(rows: list[tuple[str, float]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "sheet1"
    sheet.append(["header"] * 149)
    for attendance_date, base_hours in rows:
        row = [""] * 149
        row[0] = attendance_date
        row[1] = "Ana Attendance"
        row[2] = "E001"
        row[21] = "08:00"
        row[23] = 8
        row[37] = base_hours
        row[117] = base_hours
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


def _oehr_adjustment_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "调薪"
    sheet.append([
        "审批主题",
        "姓名",
        "工号",
        "审批状态",
        "二级部门",
        "三级部门",
        "四级部门",
        "五级部门",
        "六级部门",
        "七级部门",
        "八级部门",
        "调薪类型",
        "职级",
        "调薪原因",
        "调薪生效日期",
        "调薪后薪酬制度",
        "调薪后成本归属",
        "调薪后币种",
        "基本工资标准",
        "绩效奖金计算方式",
        "月度绩效奖金基数",
        "月度绩效奖金比例(%)",
        "是否考勤豁免人员",
        "时薪标准",
        "备注",
    ])
    sheet.append([
        "张海冰的调薪申请",
        "张海冰",
        "zt0021990",
        "已完成",
        "FBU仓储事业部",
        "美洲区",
        "新泽西区",
        "新泽西21号仓（SN）",
        "理货组",
        "",
        "",
        "非窗口期调薪",
        "",
        "转正调薪",
        "2026/04/26",
        "时薪制",
        "理货组",
        "美元(USD)",
        18,
        "固定比例核算",
        0,
        5,
        "否",
        18,
        "P1-2转正，增加绩效占比",
    ])
    return _workbook_bytes(workbook)


def _performance_report_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "4月绩效报表"
    sheet.append(["header"] * 19)
    row = [""] * 19
    row[3] = "zt001"
    row[16] = 95
    row[17] = "符合预期"
    row[18] = 1
    sheet.append(row)
    return _workbook_bytes(workbook)


def _performance_supplement_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "离职线下绩效考核表"
    sheet.append(["工号", "姓名", "绩效得分", "绩效等级", "绩效系数", "备注"])
    sheet.append(["zt001", "Ana", 60, "待改进", 0.5, "不应覆盖OEHR"])
    sheet.append(["zt0019943", "洪梓腾", 88.75, "符合预期-", 0.93, "5.29离职，线下绩效考核表"])
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

    run_detail = client.get(f"/api/fbu-performance/runs/{run_id}")
    assert run_detail.status_code == 200
    roster_data = run_detail.json()["roster_data"]
    assert roster_data["summary"]["total_employees"] == 1
    assert roster_data["employees"][0]["employee_id"] == "E001"
    assert roster_data["employees"][0]["name"] == "Ana Roster"
    assert roster_data["employees"][0]["department"] == "HRAS人力综合条线-FBU HRBP Dept."

    attendance_response = client.post(
        "/api/fbu-performance/import-attendance",
        data={"calc_month": "2026-04", "run_id": run_id},
        files={"file": ("attendance.xlsx", _attendance_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert attendance_response.status_code == 200
    attendance_payload = attendance_response.json()
    employee = attendance_payload["preview"]["employees"][0]
    assert employee["name"] == "Ana Roster"
    assert employee["department"] == "HRAS人力综合条线-FBU HRBP Dept."
    assert employee["area"] == "US-West"
    assert employee["job_type"] == "functional"
    assert employee["roster_matched"] is True
    assert attendance_payload["result_file"]["type"] == "attendance"
    assert attendance_payload["result_file"]["filename"].startswith("考勤汇总_2026-04_")
    download_response = client.get(attendance_payload["result_file"]["download_url"])
    assert download_response.status_code == 200
    assert download_response.content[:2] == b"PK"


def test_fbu_bulk_delete_removes_selected_runs(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "FBU_PERFORMANCE_RUNS_DIR", tmp_path)
    monkeypatch.setattr(app_module, "fbu_run_manager", FBURunManager(str(tmp_path)))
    monkeypatch.setattr(app_module, "fbu_roster_store", FBURosterStore(str(tmp_path)))

    client = TestClient(app_module.app)
    first_id = client.post("/api/fbu-performance/runs", json={"calc_month": "2026-04"}).json()["run_id"]
    second_id = client.post("/api/fbu-performance/runs", json={"calc_month": "2026-05"}).json()["run_id"]

    response = client.post("/api/fbu-performance/runs/bulk-delete", json={"run_ids": [first_id, second_id]})

    assert response.status_code == 200
    assert response.json()["deleted_count"] == 2
    assert client.get(f"/api/fbu-performance/runs/{first_id}").status_code == 404
    assert client.get(f"/api/fbu-performance/runs/{second_id}").status_code == 404


def test_fbu_attendance_upload_accepts_previous_month_context_without_counting_it(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "FBU_PERFORMANCE_RUNS_DIR", tmp_path)
    monkeypatch.setattr(app_module, "fbu_run_manager", FBURunManager(str(tmp_path)))
    monkeypatch.setattr(app_module, "fbu_roster_store", FBURosterStore(str(tmp_path)))

    client = TestClient(app_module.app)
    run_response = client.post("/api/fbu-performance/runs", json={"calc_month": "2026-04"})
    assert run_response.status_code == 200
    run_id = run_response.json()["run_id"]

    attendance_response = client.post(
        "/api/fbu-performance/import-attendance",
        data={"calc_month": "2026-04", "run_id": run_id},
        files={
            "file": (
                "attendance-202604.xlsx",
                _attendance_bytes_for_rows([("2026-04-01", 8)]),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
            "previous_attendance": (
                "attendance-202603.xlsx",
                _attendance_bytes_for_rows([
                    ("2026-03-01", 8),
                    ("2026-03-29", 8),
                    ("2026-03-30", 8),
                    ("2026-03-31", 8),
                    ("2026-03-28", 8),
                ]),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        },
    )

    assert attendance_response.status_code == 200
    payload = attendance_response.json()
    employee = payload["preview"]["employees"][0]
    assert [row["date"] for row in employee["attendance_daily_rows"]] == [
        "2026-03-29",
        "2026-03-30",
        "2026-03-31",
        "2026-04-01",
    ]
    assert employee["total_base_hours"] == 8
    assert payload["preview"]["summary"]["total_base_hours"] == 8
    context = payload["preview"]["summary"]["attendance_context"]
    assert context["required"] is True
    assert context["status"] == "complete"
    assert context["required_start"] == "2026-03-29"
    assert context["required_end"] == "2026-03-31"
    assert context["covered_dates"] == ["2026-03-29", "2026-03-30", "2026-03-31"]
    assert context["missing_dates"] == []
    assert "已识别96工时制跨月首段" in context["message"]

    run_detail = client.get(f"/api/fbu-performance/runs/{run_id}").json()
    assert run_detail["attendance_file"] == "attendance-202604.xlsx"
    assert run_detail["previous_attendance_file"] == "attendance-202603.xlsx"


def test_fbu_attendance_upload_rejects_file_without_calculation_month_rows(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "FBU_PERFORMANCE_RUNS_DIR", tmp_path)
    monkeypatch.setattr(app_module, "fbu_run_manager", FBURunManager(str(tmp_path)))
    monkeypatch.setattr(app_module, "fbu_roster_store", FBURosterStore(str(tmp_path)))

    client = TestClient(app_module.app)
    run_id = client.post("/api/fbu-performance/runs", json={"calc_month": "2026-04"}).json()["run_id"]
    response = client.post(
        "/api/fbu-performance/import-attendance",
        data={"calc_month": "2026-04", "run_id": run_id},
        files={
            "file": (
                "attendance-202605.xlsx",
                _attendance_bytes_for_rows([("2026-05-01", 8)]),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "考勤日报未包含 2026-04 的数据，请确认活动月份或重新上传文件"
    run = app_module.fbu_run_manager.get_run(run_id)
    assert run.attendance_data == {}
    assert run.current_step == 0


def test_failed_attendance_reupload_preserves_previous_file_and_preview(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "FBU_PERFORMANCE_RUNS_DIR", tmp_path)
    monkeypatch.setattr(app_module, "fbu_run_manager", FBURunManager(str(tmp_path)))
    monkeypatch.setattr(app_module, "fbu_roster_store", FBURosterStore(str(tmp_path)))

    client = TestClient(app_module.app)
    run_id = client.post("/api/fbu-performance/runs", json={"calc_month": "2026-04"}).json()["run_id"]
    valid_bytes = _attendance_bytes_for_rows([("2026-04-01", 8)])
    first_response = client.post(
        "/api/fbu-performance/import-attendance",
        data={"calc_month": "2026-04", "run_id": run_id},
        files={"file": ("attendance-202604.xlsx", valid_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert first_response.status_code == 200
    original_preview = app_module.fbu_run_manager.get_run(run_id).attendance_data

    failed_response = client.post(
        "/api/fbu-performance/import-attendance",
        data={"calc_month": "2026-04", "run_id": run_id},
        files={
            "file": (
                "attendance-202605.xlsx",
                _attendance_bytes_for_rows([("2026-05-01", 8)]),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert failed_response.status_code == 400
    run = app_module.fbu_run_manager.get_run(run_id)
    assert run.attendance_file == "attendance-202604.xlsx"
    assert run.attendance_data == original_preview
    assert run.status == "step1"
    assert (tmp_path / run_id / "attendance.xlsx").read_bytes() == valid_bytes


def test_fbu_attendance_upload_can_add_previous_context_after_current_file(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "FBU_PERFORMANCE_RUNS_DIR", tmp_path)
    monkeypatch.setattr(app_module, "fbu_run_manager", FBURunManager(str(tmp_path)))
    monkeypatch.setattr(app_module, "fbu_roster_store", FBURosterStore(str(tmp_path)))

    client = TestClient(app_module.app)
    run_id = client.post("/api/fbu-performance/runs", json={"calc_month": "2026-04"}).json()["run_id"]
    first_response = client.post(
        "/api/fbu-performance/import-attendance",
        data={"calc_month": "2026-04", "run_id": run_id},
        files={
            "file": (
                "attendance-202604.xlsx",
                _attendance_bytes_for_rows([("2026-04-01", 8)]),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        },
    )
    assert first_response.status_code == 200

    context_response = client.post(
        "/api/fbu-performance/import-attendance",
        data={"calc_month": "2026-04", "run_id": run_id},
        files={
            "previous_attendance": (
                "attendance-202603.xlsx",
                _attendance_bytes_for_rows([
                    ("2026-03-01", 8),
                    ("2026-03-29", 8),
                    ("2026-03-30", 8),
                    ("2026-03-31", 8),
                    ("2026-03-28", 8),
                ]),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        },
    )

    assert context_response.status_code == 200
    payload = context_response.json()
    assert payload["preview"]["summary"]["attendance_context"]["status"] == "complete"
    assert payload["preview"]["employees"][0]["total_base_hours"] == 8
    assert [row["date"] for row in payload["preview"]["employees"][0]["attendance_daily_rows"]] == [
        "2026-03-29",
        "2026-03-30",
        "2026-03-31",
        "2026-04-01",
    ]
    assert not (tmp_path / run_id / "attendance_with_context.xlsx").exists()
    run_detail = client.get(f"/api/fbu-performance/runs/{run_id}").json()
    assert run_detail["attendance_file"] == "attendance-202604.xlsx"
    assert run_detail["previous_attendance_file"] == "attendance-202603.xlsx"


def test_fbu_attendance_upload_reports_missing_previous_context_dates(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "FBU_PERFORMANCE_RUNS_DIR", tmp_path)
    monkeypatch.setattr(app_module, "fbu_run_manager", FBURunManager(str(tmp_path)))
    monkeypatch.setattr(app_module, "fbu_roster_store", FBURosterStore(str(tmp_path)))

    client = TestClient(app_module.app)
    run_response = client.post("/api/fbu-performance/runs", json={"calc_month": "2026-04"})
    assert run_response.status_code == 200
    run_id = run_response.json()["run_id"]

    attendance_response = client.post(
        "/api/fbu-performance/import-attendance",
        data={"calc_month": "2026-04", "run_id": run_id},
        files={
            "file": (
                "attendance-202604.xlsx",
                _attendance_bytes_for_rows([("2026-04-01", 8)]),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        },
    )

    assert attendance_response.status_code == 200
    context = attendance_response.json()["preview"]["summary"]["attendance_context"]
    assert context["required"] is True
    assert context["status"] == "missing"
    assert context["required_start"] == "2026-03-29"
    assert context["required_end"] == "2026-03-31"
    assert context["covered_dates"] == []
    assert context["missing_dates"] == ["2026-03-29", "2026-03-30", "2026-03-31"]
    assert "缺少上一月 2026-03-29 至 2026-03-31 考勤" in context["message"]


def test_fbu_performance_supplement_upload_merges_missing_employee_without_overwrite(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "FBU_PERFORMANCE_RUNS_DIR", tmp_path)
    monkeypatch.setattr(app_module, "EXPORT_DIR", tmp_path)
    monkeypatch.setattr(app_module, "fbu_run_manager", FBURunManager(str(tmp_path)))
    monkeypatch.setattr(app_module, "fbu_roster_store", FBURosterStore(str(tmp_path)))

    client = TestClient(app_module.app)

    run_response = client.post("/api/fbu-performance/runs", json={"calc_month": "2026-04"})
    assert run_response.status_code == 200
    run_id = run_response.json()["run_id"]

    performance_response = client.post(
        "/api/fbu-performance/import-performance",
        data={"run_id": run_id},
        files={"file": ("performance.xlsx", _performance_report_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert performance_response.status_code == 200
    assert performance_response.json()["preview"]["summary"]["total_employees"] == 1

    supplement_response = client.post(
        "/api/fbu-performance/import-performance",
        data={"run_id": run_id},
        files={"file": ("resigned-performance.xlsx", _performance_supplement_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert supplement_response.status_code == 200
    payload = supplement_response.json()
    summary = payload["preview"]["summary"]
    assert summary["source_type"] == "merged_performance"
    assert summary["supplement_added"] == 1
    assert summary["supplement_skipped_existing"] == 1
    employees = {employee["employee_id"]: employee for employee in payload["preview"]["employees"]}
    assert employees["zt001"]["score"] == 95
    assert employees["zt001"]["coefficient"] == 1
    assert employees["zt0019943"]["name"] == "洪梓腾"
    assert employees["zt0019943"]["coefficient"] == 0.93
    assert employees["zt0019943"]["performance_source"] == "绩效补录"

    run_detail = client.get(f"/api/fbu-performance/runs/{run_id}").json()
    saved = {employee["employee_id"]: employee for employee in run_detail["performance_data"]["employees"]}
    assert set(saved) == {"zt001", "zt0019943"}


def test_fbu_performance_supplement_can_be_entered_from_page(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "FBU_PERFORMANCE_RUNS_DIR", tmp_path)
    monkeypatch.setattr(app_module, "EXPORT_DIR", tmp_path)
    monkeypatch.setattr(app_module, "fbu_run_manager", FBURunManager(str(tmp_path)))
    monkeypatch.setattr(app_module, "fbu_roster_store", FBURosterStore(str(tmp_path)))

    client = TestClient(app_module.app)

    run_response = client.post("/api/fbu-performance/runs", json={"calc_month": "2026-04"})
    assert run_response.status_code == 200
    run_id = run_response.json()["run_id"]

    performance_response = client.post(
        "/api/fbu-performance/import-performance",
        data={"run_id": run_id},
        files={"file": ("performance.xlsx", _performance_report_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert performance_response.status_code == 200

    supplement_response = client.post(
        f"/api/fbu-performance/runs/{run_id}/performance-supplement",
        json={
            "employee_id": "zt0019943",
            "name": "洪梓腾",
            "score": 88.75,
            "level": "符合预期-",
            "coefficient": 0.93,
            "note": "5.29离职，线下绩效考核表",
        },
    )

    assert supplement_response.status_code == 200
    payload = supplement_response.json()
    summary = payload["preview"]["summary"]
    assert summary["source_type"] == "merged_performance"
    assert summary["supplement_added"] == 1
    employees = {employee["employee_id"]: employee for employee in payload["preview"]["employees"]}
    assert employees["zt001"]["score"] == 95
    assert employees["zt0019943"]["name"] == "洪梓腾"
    assert employees["zt0019943"]["score"] == 88.75
    assert employees["zt0019943"]["level"] == "符合预期-"
    assert employees["zt0019943"]["coefficient"] == 0.93
    assert employees["zt0019943"]["performance_source"] == "绩效补录"
    assert employees["zt0019943"]["note"] == "5.29离职，线下绩效考核表"

    duplicate_response = client.post(
        f"/api/fbu-performance/runs/{run_id}/performance-supplement",
        json={
            "employee_id": "zt001",
            "name": "Ana",
            "score": 60,
            "level": "待改进",
            "coefficient": 0.5,
            "note": "不应覆盖OEHR",
        },
    )

    assert duplicate_response.status_code == 200
    duplicate_payload = duplicate_response.json()
    duplicate_summary = duplicate_payload["preview"]["summary"]
    assert duplicate_summary["supplement_added"] == 0
    assert duplicate_summary["supplement_skipped_existing"] == 1
    duplicate_employees = {employee["employee_id"]: employee for employee in duplicate_payload["preview"]["employees"]}
    assert duplicate_employees["zt001"]["score"] == 95
    assert duplicate_employees["zt001"]["coefficient"] == 1

    second_supplement_response = client.post(
        f"/api/fbu-performance/runs/{run_id}/performance-supplement",
        json={
            "employee_id": "zt009999",
            "name": "临时补录员工",
            "coefficient": 0.88,
            "note": "继续补录第二人",
        },
    )

    assert second_supplement_response.status_code == 200
    second_payload = second_supplement_response.json()
    second_employees = {employee["employee_id"]: employee for employee in second_payload["preview"]["employees"]}
    assert second_employees["zt0019943"]["name"] == "洪梓腾"
    assert second_employees["zt009999"]["name"] == "临时补录员工"
    assert second_employees["zt009999"]["coefficient"] == 0.88
    assert second_employees["zt009999"]["performance_source"] == "绩效补录"


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
    assert payload["result_file"]["type"] == "adjustments"
    assert payload["result_file"]["filename"].startswith("调薪拆分_2026-04_")
    download_response = client.get(payload["result_file"]["download_url"])
    assert download_response.status_code == 200
    assert download_response.content[:2] == b"PK"

    run_detail = client.get(f"/api/fbu-performance/runs/{run_id}").json()
    assert run_detail["adjustment_file"] == "adjustments.xlsx"
    assert run_detail["adjustment_data"]["employees"][0]["segments"][0]["reason"] == "调薪后"


def test_fbu_oehr_adjustment_upload_exports_event_preview(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "FBU_PERFORMANCE_RUNS_DIR", tmp_path)
    monkeypatch.setattr(app_module, "EXPORT_DIR", tmp_path)
    monkeypatch.setattr(app_module, "fbu_run_manager", FBURunManager(str(tmp_path)))
    monkeypatch.setattr(app_module, "fbu_roster_store", FBURosterStore(str(tmp_path)))

    client = TestClient(app_module.app)

    run_response = client.post("/api/fbu-performance/runs", json={"calc_month": "2026-04"})
    assert run_response.status_code == 200
    run_id = run_response.json()["run_id"]

    adjustment_response = client.post(
        "/api/fbu-performance/import-adjustments",
        data={"run_id": run_id},
        files={"file": ("oehr_adjustments.xlsx", _oehr_adjustment_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert adjustment_response.status_code == 200
    payload = adjustment_response.json()
    assert payload["preview"]["summary"]["total_events"] == 1
    assert payload["preview"]["summary"]["auto_split_ready"] == 1
    assert payload["result_file"]["type"] == "adjustments"
    download_response = client.get(payload["result_file"]["download_url"])
    assert download_response.status_code == 200
    assert download_response.content[:2] == b"PK"


def test_fbu_salary_history_upload_persists_three_sources_and_blocks_unmatched_changes(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "FBU_PERFORMANCE_RUNS_DIR", tmp_path)
    monkeypatch.setattr(app_module, "fbu_run_manager", FBURunManager(str(tmp_path)))
    monkeypatch.setattr(app_module, "fbu_roster_store", FBURosterStore(str(tmp_path)))

    previews = iter([
        {"employees": [{"employee_id": "E001", "hourly_rate": 18, "ratio": 0.05}]},
        {"employees": [{"employee_id": "E001", "hourly_rate": 21, "ratio": 0.09}]},
    ])
    monkeypatch.setattr(
        app_module.FBUPerformanceParser,
        "parse_salary_preview",
        lambda self, path: next(previews),
    )
    monkeypatch.setattr(
        app_module.FBUPerformanceParser,
        "parse_adjustments_preview",
        lambda self, path: {"employees": [], "events": [], "summary": {"total_events": 0}},
    )

    client = TestClient(app_module.app)
    run_id = client.post("/api/fbu-performance/runs", json={"calc_month": "2026-05"}).json()["run_id"]
    response = client.post(
        "/api/fbu-performance/import-salary-history",
        data={"run_id": run_id},
        files={
            "previous_salary": ("april.xlsx", b"previous", "application/octet-stream"),
            "current_salary": ("may.xlsx", b"current", "application/octet-stream"),
            "adjustments": ("adjustments.xlsx", b"adjustments", "application/octet-stream"),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["verification"]["summary"]["blocking_count"] == 1
    run = app_module.fbu_run_manager.get_run(run_id)
    assert run.previous_salary_file == "april.xlsx"
    assert run.current_salary_file == "may.xlsx"
    assert run.adjustment_file == "adjustments.xlsx"
    assert run.salary_data["employees"][0]["verification_status"] == "blocking"

    calculate_response = client.post(f"/api/fbu-performance/calculate/{run_id}")
    assert calculate_response.status_code == 409
    assert "薪资历史核验仍有 1 条" in calculate_response.json()["detail"]

    confirm_response = client.post(
        f"/api/fbu-performance/runs/{run_id}/salary-verification/confirm",
        json={"employee_id": "E001", "choice": "previous", "note": "薪酬组确认"},
    )
    assert confirm_response.status_code == 200
    confirmed = confirm_response.json()
    assert confirmed["verification"]["summary"]["blocking_count"] == 0
    assert confirmed["preview"]["employees"][0]["hourly_rate"] == 18
    assert confirmed["preview"]["employees"][0]["ratio"] == 0.05
    assert confirmed["preview"]["employees"][0]["resolution"] == "manual_use_previous"


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
    assert workbook.sheetnames == ["调薪拆分"]
    main_sheet = workbook["调薪拆分"]
    assert main_sheet.cell(3, 1).value == "zt0000001"
    assert main_sheet.cell(3, 2).value == "花名一"
    assert [main_sheet.cell(6, col).value for col in range(1, 7)] == [
        "工号",
        "姓名",
        "分段期间",
        "分段绩效基数",
        "核算标识",
        "备注",
    ]
    assert main_sheet.cell(7, 1).value is None
    validations = list(main_sheet.data_validations.dataValidation)
    assert len(validations) == 1
    assert validations[0].type == "list"
    assert validations[0].formula1 == '"调薪前,调薪后"'
    assert "E7:E1000" in str(validations[0].sqref)


def test_fbu_export_escapes_formula_like_values_and_selects_header(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "EXPORT_DIR", tmp_path)
    monkeypatch.setattr(app_module, "fbu_run_manager", FBURunManager(str(tmp_path)))

    run = app_module.fbu_run_manager.create_run(calc_month="2026-04")
    app_module.fbu_run_manager.save_results(
        run.run_id,
        [
            EmployeeData(
                employee_id="zt001",
                name="=SUM(A1:A2)",
                department="+Formula Dept",
                area="@Area",
                hourly_rate=18,
                performance_ratio=0.05,
                performance_base=1000,
                performance_coefficient=1,
                performance_bonus=50,
            )
        ],
    )

    client = TestClient(app_module.app)
    response = client.get(f"/api/fbu-performance/runs/{run.run_id}/export-excel?type=results")

    assert response.status_code == 200
    filename = response.json()["filename"]
    workbook = load_workbook(tmp_path / filename, data_only=False)
    assert workbook.sheetnames == ["汇总表", "1.仓库管理人员", "2.非仓人员", "3.区长"]
    summary = workbook["汇总表"]
    assert summary["A1"].value == "新泽西区绩效考核与奖金核算"
    assert not str(summary["A1"].value).startswith("=")
    assert summary.sheet_view.selection[0].activeCell == "A2"
    sheet = workbook["1.仓库管理人员"]
    assert sheet.sheet_view.selection[0].activeCell == "A3"
    values = [cell.value for row in sheet.iter_rows() for cell in row if isinstance(cell.value, str)]
    assert not any(value.startswith("=") for value in values)
    assert "'=SUM(A1:A2)" in values


def test_fbu_results_export_marks_district_manager_fixed_base_path(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "EXPORT_DIR", tmp_path)
    monkeypatch.setattr(app_module, "fbu_run_manager", FBURunManager(str(tmp_path)))

    run = app_module.fbu_run_manager.create_run(calc_month="2026-04")
    app_module.fbu_run_manager.save_results(
        run.run_id,
        [
            EmployeeData(
                employee_id="zt15638",
                name="万其鑫",
                position="区域经理",
                job_type="district_manager",
                hourly_rate=40.384615,
                performance_ratio=0,
                fixed_performance_base=3000,
                performance_base=3000,
                uploaded_coefficient=1.35,
                performance_coefficient=1.35,
                performance_bonus=4050,
            )
        ],
    )

    client = TestClient(app_module.app)
    response = client.get(f"/api/fbu-performance/runs/{run.run_id}/export-excel?type=results")

    assert response.status_code == 200
    filename = response.json()["filename"]
    workbook = load_workbook(tmp_path / filename, data_only=False)
    assert workbook.sheetnames == ["汇总表", "1.仓库管理人员", "2.非仓人员", "3.区长"]
    sheet = workbook["3.区长"]
    headers = [cell.value for cell in sheet[3]]
    row = [cell.value for cell in sheet[4]]
    values_by_header = dict(zip(headers, row))
    assert values_by_header["岗位"] == "区域经理"
    assert values_by_header["绩效奖金基数"] == 3000


def test_fbu_results_merge_shift_split_rows_for_final_view_and_export(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "EXPORT_DIR", tmp_path)
    monkeypatch.setattr(app_module, "fbu_run_manager", FBURunManager(str(tmp_path)))

    run = app_module.fbu_run_manager.create_run(calc_month="2026-04")
    app_module.fbu_run_manager.save_results(
        run.run_id,
        [
            EmployeeData(
                employee_id="zt0020984-1",
                source_employee_id="zt0020984",
                name="黄东俊",
                area="新泽西区",
                department="新泽西21号仓（SN）",
                position="仓库组长",
                job_type="warehouse",
                hourly_rate=18,
                performance_ratio=0.05,
                performance_base=3516.93,
                performance_score=107.3,
                performance_level="符合预期+",
                performance_coefficient=1.25,
                performance_bonus=219.81,
            ),
            EmployeeData(
                employee_id="zt0020984",
                source_employee_id="zt0020984",
                name="黄东俊",
                area="新泽西区",
                department="新泽西21号仓（SN）",
                position="仓库组长",
                job_type="warehouse",
                hourly_rate=19,
                performance_ratio=0.05,
                performance_base=610.66,
                performance_score=107.3,
                performance_level="符合预期+",
                performance_coefficient=1.25,
                performance_bonus=38.17,
            ),
        ],
    )

    client = TestClient(app_module.app)
    detail_response = client.get(f"/api/fbu-performance/runs/{run.run_id}")

    assert detail_response.status_code == 200
    final_results = detail_response.json()["results"]
    assert len(final_results) == 1
    assert final_results[0]["employee_id"] == "zt0020984"
    assert final_results[0]["raw_employee_ids"] == ["zt0020984-1", "zt0020984"]
    assert "hourly_rate" not in final_results[0]
    assert "attendance_daily_rows" not in final_results[0]
    assert final_results[0]["performance_score"] == 107.3
    assert final_results[0]["performance_level"] == "符合预期+"
    assert final_results[0]["position"] == "仓库组长"
    assert final_results[0]["performance_base"] == 4127.59
    assert final_results[0]["performance_bonus"] == 257.98

    export_response = client.get(f"/api/fbu-performance/runs/{run.run_id}/export-excel?type=results")

    assert export_response.status_code == 200
    filename = export_response.json()["filename"]
    workbook = load_workbook(tmp_path / filename, data_only=False)
    assert workbook.sheetnames == ["汇总表", "1.仓库管理人员", "2.非仓人员", "3.区长"]
    summary = workbook["汇总表"]
    assert summary["A2"].value == "绩效周期"
    assert summary["C3"].value == "仓库管理人员"
    assert summary["D3"].value == 257.98
    sheet = workbook["1.仓库管理人员"]
    assert sheet["A2"].value == "员工信息"
    assert sheet["J2"].value == "本月绩效考核结果(OEHR)"
    assert sheet["M2"].value == "本月应发绩效工资"
    headers = [cell.value for cell in sheet[3]]
    assert "时薪($)" not in headers
    assert "绩效得分" in headers
    assert "4月绩效基数" in headers
    rows = list(sheet.iter_rows(min_row=4, max_row=4, values_only=True))
    values_by_header = dict(zip(headers, rows[0]))
    assert values_by_header["员工工号"] == "zt0020984"
    assert values_by_header["职位"] == "仓库组长"
    assert values_by_header["绩效得分"] == 107.3
    assert values_by_header["4月绩效基数"] == 4127.59
    assert sheet["M4"].value == 257.98


def test_fbu_results_export_backfills_position_from_uploaded_roster_preview(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "EXPORT_DIR", tmp_path)
    monkeypatch.setattr(app_module, "fbu_run_manager", FBURunManager(str(tmp_path)))

    run = app_module.fbu_run_manager.create_run(calc_month="2026-04")
    app_module.fbu_run_manager.update_run(
        run.run_id,
        attendance_data={
            "employees": [
                {
                    "employee_id": "zt0003518",
                    "name": "朱杏仪",
                    "position": "高级仓库专员",
                }
            ]
        },
    )
    app_module.fbu_run_manager.save_results(
        run.run_id,
        [
            EmployeeData(
                employee_id="zt0003518",
                name="朱杏仪",
                job_type="warehouse",
                hourly_rate=18,
                performance_ratio=0.06,
                performance_base=5456.75,
                performance_score=112.4,
                performance_level="超出预期",
                performance_coefficient=1.35,
                performance_bonus=442,
            )
        ],
    )

    client = TestClient(app_module.app)
    response = client.get(f"/api/fbu-performance/runs/{run.run_id}/export-excel?type=results")

    assert response.status_code == 200
    filename = response.json()["filename"]
    workbook = load_workbook(tmp_path / filename, data_only=False)
    sheet = workbook["1.仓库管理人员"]
    headers = [cell.value for cell in sheet[3]]
    values_by_header = dict(zip(headers, list(sheet.iter_rows(min_row=4, max_row=4, values_only=True))[0]))
    assert values_by_header["职位"] == "高级仓库专员"


def test_fbu_results_export_marks_96_hour_base_in_red(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "EXPORT_DIR", tmp_path)
    monkeypatch.setattr(app_module, "fbu_run_manager", FBURunManager(str(tmp_path)))

    run = app_module.fbu_run_manager.create_run(calc_month="2026-04")
    app_module.fbu_run_manager.save_results(
        run.run_id,
        [
            EmployeeData(
                employee_id="zt12979",
                name="赵婉妍",
                job_type="warehouse",
                performance_ratio=0.05,
                performance_base=2000,
                performance_score=100,
                performance_coefficient=1,
                performance_bonus=100,
                work_hour_rule="96工时制",
            )
        ],
    )

    client = TestClient(app_module.app)
    response = client.get(f"/api/fbu-performance/runs/{run.run_id}/export-excel?type=results")

    assert response.status_code == 200
    filename = response.json()["filename"]
    workbook = load_workbook(tmp_path / filename, data_only=False)
    sheet = workbook["1.仓库管理人员"]
    headers = [cell.value for cell in sheet[3]]
    base_col = headers.index("4月绩效基数") + 1
    base_cell = sheet.cell(row=4, column=base_col)
    assert base_cell.value == 2000
    assert base_cell.font.color.rgb == "00C00000"
    assert base_cell.fill.fgColor.rgb == "00FCE4D6"


def test_fbu_calculate_uses_saved_rule_lists_even_when_current_step_is_behind(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "fbu_run_manager", FBURunManager(str(tmp_path)))

    run = app_module.fbu_run_manager.create_run(calc_month="2026-05")
    attendance_employee = {
        "employee_id": "zt12979",
        "source_employee_id": "zt12979",
        "name": "赵婉妍",
        "department": "FBU仓储事业部-美洲区-新泽西区",
        "area": "新泽西区",
        "position": "USNJ Deputy General Manager 新泽西区副总经理",
        "job_type": "warehouse",
        "day_shift": {
            "计薪出勤": 100,
            "OT1.5": 40,
            "OT2.0": 0,
            "病假": 0,
            "病假清算": 0,
            "年假": 0,
            "节假日": 0,
        },
        "night_shift": {
            "计薪出勤": 0,
            "OT1.5": 0,
            "OT2.0": 0,
            "病假": 0,
            "病假清算": 0,
            "年假": 0,
            "节假日": 0,
        },
        "has_night_shift": False,
        "attendance_daily_rows": [
            {"date": "2026-05-01", "shift_type": "白班", "base_hours": 100, "ot15_hours": 40, "holiday_hours": 0},
        ],
    }
    app_module.fbu_run_manager.save_step_data(run.run_id, 1, {"employees": [attendance_employee]})
    app_module.fbu_run_manager.save_step_data(run.run_id, 3, {
        "employees": [
            {
                "employee_id": "zt12979",
                "score": 100,
                "level": "符合预期",
                "coefficient": 1,
            }
        ]
    })
    app_module.fbu_run_manager.update_run(
        run.run_id,
        base_override_data={
            "employees": [
                {
                    "employee_id": "zt12979",
                    "source_employee_id": "zt12979",
                    "name": "赵婉妍",
                    "rule_type": "96工时制",
                    "fixed_performance_base": None,
                    "allocation_month": "2026-05",
                    "status": "启用",
                    "include_in_calculation": True,
                }
            ]
        },
    )
    app_module.fbu_run_manager.save_step_data(run.run_id, 2, {
        "employees": [
            {
                "employee_id": "zt12979",
                "hourly_rate": 20,
                "ratio": 0.05,
                "fixed_performance_base": 0,
            }
        ]
    })
    assert app_module.fbu_run_manager.get_run(run.run_id).current_step == 2

    client = TestClient(app_module.app)
    response = client.post(f"/api/fbu-performance/calculate/{run.run_id}")

    assert response.status_code == 200
    result = app_module.fbu_run_manager.get_run(run.run_id).results[0]
    assert result["work_hour_rule"] == "96工时制"
    assert result["calculation_path"] == "96工时制自动基数路径"


def test_fbu_diagnostics_reports_matching_issues_and_exports(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "EXPORT_DIR", tmp_path)
    monkeypatch.setattr(app_module, "fbu_run_manager", FBURunManager(str(tmp_path)))

    run = app_module.fbu_run_manager.create_run(calc_month="2026-04")
    app_module.fbu_run_manager.save_step_data(run.run_id, 1, {
        "employees": [
            {"employee_id": "zt001", "name": "Ana"},
            {"employee_id": "zt002", "name": "Ben"},
        ]
    })
    app_module.fbu_run_manager.save_step_data(run.run_id, 2, {
        "employees": [
            {"employee_id": "zt001", "name": "Ana", "hourly_rate": 18, "ratio": 0.05},
            {"employee_id": "zt003", "name": "Cara", "hourly_rate": 0, "ratio": 0},
        ]
    })
    app_module.fbu_run_manager.save_step_data(run.run_id, 3, {
        "employees": [
            {"employee_id": "zt001", "name": "Ana"},
            {"employee_id": "zt004", "name": "Dora"},
        ]
    })
    app_module.fbu_run_manager.save_step_data(run.run_id, 4, {
        "employees": [
            {"employee_id": "zt005", "name": "Eli", "segments": [{"reason": "调薪后", "performance_base": 0}]},
        ]
    })

    client = TestClient(app_module.app)
    response = client.get(f"/api/fbu-performance/runs/{run.run_id}/diagnostics")

    assert response.status_code == 200
    diagnostics = response.json()
    assert diagnostics["summary"]["attendance_count"] == 2
    assert diagnostics["summary"]["matched_salary_count"] == 1
    assert diagnostics["summary"]["matched_performance_count"] == 1
    issue_types = {issue["type"] for issue in diagnostics["issues"]}
    assert "考勤有薪资无" in issue_types
    assert "薪资有考勤无" in issue_types
    assert "绩效有考勤无" in issue_types
    assert "拆分有考勤无" in issue_types
    assert "拆分有薪资无" in issue_types

    export_response = client.get(f"/api/fbu-performance/runs/{run.run_id}/export-excel?type=diagnostics")
    assert export_response.status_code == 200
    workbook = load_workbook(tmp_path / export_response.json()["filename"], data_only=True)
    assert workbook["数据诊断"].cell(3, 1).value == "严重程度"


def test_fbu_diagnostics_matches_shift_split_suffix_to_source_employee(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "EXPORT_DIR", tmp_path)
    monkeypatch.setattr(app_module, "fbu_run_manager", FBURunManager(str(tmp_path)))

    run = app_module.fbu_run_manager.create_run(calc_month="2026-04")
    app_module.fbu_run_manager.save_step_data(run.run_id, 1, {
        "employees": [
            {"employee_id": "zt0020984-1", "name": "黄东俊", "has_night_shift": False},
            {"employee_id": "zt0020984", "name": "黄东俊", "has_night_shift": True},
            {"employee_id": "zt009-1", "name": "缺绩效员工", "has_night_shift": False},
        ]
    })
    app_module.fbu_run_manager.save_step_data(run.run_id, 2, {
        "employees": [
            {"employee_id": "zt0020984", "name": "黄东俊", "hourly_rate": 18, "ratio": 0.05},
            {"employee_id": "zt009", "name": "缺绩效员工", "hourly_rate": 18, "ratio": 0.05},
        ]
    })
    app_module.fbu_run_manager.save_step_data(run.run_id, 3, {
        "employees": [
            {"employee_id": "zt0020984", "name": "黄东俊"},
        ]
    })

    client = TestClient(app_module.app)
    response = client.get(f"/api/fbu-performance/runs/{run.run_id}/diagnostics")

    assert response.status_code == 200
    diagnostics = response.json()
    assert diagnostics["summary"]["attendance_count"] == 3
    assert diagnostics["summary"]["matched_salary_count"] == 3
    assert diagnostics["summary"]["matched_performance_count"] == 2
    assert diagnostics["summary"]["can_calculate_count"] == 3
    assert diagnostics["summary"]["error_count"] == 0
    issue_pairs = {(issue["employee_id"], issue["type"]) for issue in diagnostics["issues"]}
    assert ("zt0020984-1", "考勤有薪资无") not in issue_pairs
    assert ("zt0020984-1", "考勤有绩效无") not in issue_pairs
    assert ("zt009-1", "考勤有绩效无") not in issue_pairs
    assert ("zt009", "考勤有绩效无") in issue_pairs


def test_fbu_diagnostics_does_not_flag_future_steps_before_upload(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "EXPORT_DIR", tmp_path)
    monkeypatch.setattr(app_module, "fbu_run_manager", FBURunManager(str(tmp_path)))

    run = app_module.fbu_run_manager.create_run(calc_month="2026-04")
    app_module.fbu_run_manager.save_step_data(run.run_id, 1, {
        "employees": [
            {"employee_id": "zt001", "name": "Ana"},
            {"employee_id": "zt002", "name": "Ben"},
        ]
    })

    client = TestClient(app_module.app)
    response = client.get(f"/api/fbu-performance/runs/{run.run_id}/diagnostics")

    assert response.status_code == 200
    diagnostics = response.json()
    issue_types = {issue["type"] for issue in diagnostics["issues"]}
    assert "考勤有薪资无" not in issue_types
    assert "考勤有绩效无" not in issue_types
    assert diagnostics["summary"]["issue_count"] == 0
    assert diagnostics["summary"]["error_count"] == 0
