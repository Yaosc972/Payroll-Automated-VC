import json

from fastapi.testclient import TestClient

import bonus_platform.app as app_module
from bonus_platform.engine.fbu_performance.runs import FBURuleListStore, FBURunManager


def _client_with_tmp_store(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "FBU_PERFORMANCE_RUNS_DIR", tmp_path)
    monkeypatch.setattr(app_module, "fbu_run_manager", FBURunManager(str(tmp_path)))
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
    assert by_id["zt15638"]["rule_type"] == "线下固定基数覆盖"
    assert by_id["zt15638"]["fixed_performance_base"] == 3000
    assert detail["base_override_file"] == "页面维护"
