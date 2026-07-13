import json
from io import BytesIO

from fastapi.testclient import TestClient
from openpyxl import Workbook

import bonus_platform.app as app_module
from bonus_platform.engine.fbu_performance.runs import FBURosterStore, FBURuleListStore, FBURunManager


def _workbook_bytes(workbook: Workbook) -> bytes:
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _roster_workbook_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Roster"
    sheet.append(["姓名", "工号", "二级部门", "三级部门", "四级部门", "划分区域"])
    sheet.append(["陈海冰（花名册）", "zt12988", "FBU", "仓储事业部", "新泽西仓", "新泽西区"])
    sheet.append(["万其鑫（花名册）", "zt15638", "FBU", "区域管理", "美东", "美东区"])
    return _workbook_bytes(workbook)


def _client_with_tmp_store(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "FBU_PERFORMANCE_RUNS_DIR", tmp_path)
    monkeypatch.setattr(app_module, "fbu_run_manager", FBURunManager(str(tmp_path)))
    monkeypatch.setattr(app_module, "fbu_roster_store", FBURosterStore(str(tmp_path)))
    monkeypatch.setattr(app_module, "fbu_rule_list_store", FBURuleListStore(str(tmp_path)))
    return TestClient(app_module.app)


def test_rule_lists_return_seeded_96_hour_and_fixed_base_lists(monkeypatch, tmp_path):
    client = _client_with_tmp_store(monkeypatch, tmp_path)

    response = client.get("/api/fbu-performance/rule-lists")

    assert response.status_code == 200
    payload = response.json()
    assert {row["employee_id"] for row in payload["work_hour_employees"]} == {
        "zt12979",
        "zt12988",
        "zt14260",
        "zt17850",
    }
    assert payload["fixed_base_employees"][0]["employee_id"] == "zt15638"
    assert payload["fixed_base_employees"][0]["fixed_performance_base"] == 3000


def test_run_manager_quarantines_corrupt_runs_json(tmp_path):
    runs_file = tmp_path / "runs.json"
    runs_file.write_text("{not valid json", encoding="utf-8")

    manager = FBURunManager(str(tmp_path))

    assert manager.list_runs() == []
    assert not runs_file.exists()
    assert len(list(tmp_path.glob("runs.corrupt-*.json"))) == 1

    run = manager.create_run("2026-04")
    assert run.calc_month == "2026-04"
    assert runs_file.exists()


def test_rule_lists_can_be_saved_without_uploading_workbook(monkeypatch, tmp_path):
    client = _client_with_tmp_store(monkeypatch, tmp_path)

    response = client.post(
        "/api/fbu-performance/rule-lists",
        json={
            "work_hour_employees": [
                {"employee_id": "zt12988", "name": "陈海冰", "active": True},
            ],
            "fixed_base_employees": [
                {"employee_id": "zt15638", "name": "万其鑫", "fixed_performance_base": 3000, "active": True},
            ],
        },
    )

    assert response.status_code == 200
    saved = json.loads((tmp_path / "_settings" / "rule_lists.json").read_text(encoding="utf-8"))
    assert saved["work_hour_employees"][0]["employee_id"] == "zt12988"
    assert saved["fixed_base_employees"][0]["fixed_performance_base"] == 3000


def test_rule_lists_restore_seed_rows_when_saved_lists_are_empty(monkeypatch, tmp_path):
    client = _client_with_tmp_store(monkeypatch, tmp_path)

    save_response = client.post(
        "/api/fbu-performance/rule-lists",
        json={"work_hour_employees": [], "fixed_base_employees": []},
    )

    assert save_response.status_code == 200
    saved_payload = save_response.json()
    assert {row["employee_id"] for row in saved_payload["work_hour_employees"]} == {
        "zt12979",
        "zt12988",
        "zt14260",
        "zt17850",
    }
    assert saved_payload["fixed_base_employees"][0]["employee_id"] == "zt15638"
    assert saved_payload["fixed_base_employees"][0]["fixed_performance_base"] == 3000

    get_response = client.get("/api/fbu-performance/rule-lists")
    assert get_response.status_code == 200
    payload = get_response.json()
    assert payload["fixed_base_employees"][0]["employee_id"] == "zt15638"


def test_confirm_rule_lists_writes_base_override_data_to_run(monkeypatch, tmp_path):
    client = _client_with_tmp_store(monkeypatch, tmp_path)
    run_id = client.post("/api/fbu-performance/runs", json={"calc_month": "2026-04"}).json()["run_id"]

    response = client.post(
        f"/api/fbu-performance/runs/{run_id}/rule-lists/confirm",
        json={
            "work_hour_employees": [
                {"employee_id": "zt12988", "name": "陈海冰", "active": True},
            ],
            "fixed_base_employees": [
                {"employee_id": "zt15638", "name": "万其鑫", "fixed_performance_base": 3000, "active": True},
            ],
        },
    )

    assert response.status_code == 200
    detail = client.get(f"/api/fbu-performance/runs/{run_id}").json()
    rows = detail["base_override_data"]["employees"]
    by_id = {row["employee_id"]: row for row in rows}
    assert by_id["zt12988"]["rule_type"] == "96工时制"
    assert by_id["zt12988"]["fixed_performance_base"] is None
    assert by_id["zt12988"]["source_employee_id"] == "zt12988"
    assert "area" in by_id["zt12988"]
    assert "department" in by_id["zt12988"]
    assert by_id["zt15638"]["rule_type"] == "线下固定基数覆盖"
    assert by_id["zt15638"]["fixed_performance_base"] == 3000
    assert by_id["zt15638"]["source_employee_id"] == "zt15638"
    assert "area" in by_id["zt15638"]
    assert "department" in by_id["zt15638"]
    assert detail["base_override_file"] == "页面维护"


def test_confirm_rule_lists_enriches_name_area_and_department_from_roster(monkeypatch, tmp_path):
    client = _client_with_tmp_store(monkeypatch, tmp_path)
    upload = client.post(
        "/api/fbu-performance/roster",
        files={
            "file": (
                "roster.xlsx",
                _roster_workbook_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert upload.status_code == 200

    run_id = client.post("/api/fbu-performance/runs", json={"calc_month": "2026-04"}).json()["run_id"]
    response = client.post(
        f"/api/fbu-performance/runs/{run_id}/rule-lists/confirm",
        json={
            "work_hour_employees": [
                {"employee_id": "zt12988", "name": "页面姓名", "active": True},
            ],
            "fixed_base_employees": [
                {"employee_id": "zt15638", "name": "页面姓名", "fixed_performance_base": 3000, "active": True},
            ],
        },
    )

    assert response.status_code == 200
    rows = response.json()["preview"]["employees"]
    by_id = {row["employee_id"]: row for row in rows}
    assert by_id["zt12988"]["name"] == "陈海冰（花名册）"
    assert by_id["zt12988"]["area"] == "新泽西区"
    assert by_id["zt12988"]["department"] == "FBU-仓储事业部-新泽西仓"
    assert by_id["zt15638"]["name"] == "万其鑫（花名册）"
    assert by_id["zt15638"]["area"] == "美东区"
    assert by_id["zt15638"]["department"] == "FBU-区域管理-美东"


def test_save_rule_lists_rejects_non_numeric_fixed_base(monkeypatch, tmp_path):
    client = _client_with_tmp_store(monkeypatch, tmp_path)

    response = client.post(
        "/api/fbu-performance/rule-lists",
        json={
            "work_hour_employees": [],
            "fixed_base_employees": [
                {"employee_id": "zt15638", "name": "万其鑫", "fixed_performance_base": "abc", "active": True},
            ],
        },
    )

    assert response.status_code == 400
    assert "固定绩效基数必须是数字" in response.json()["detail"]
