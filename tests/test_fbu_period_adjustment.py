from fastapi.testclient import TestClient
from openpyxl import load_workbook
import pytest

import bonus_platform.app as app_module
from bonus_platform.engine.fbu_performance.engines.base import EmployeeData
from bonus_platform.engine.fbu_performance.parser import FBUPerformanceParser
from bonus_platform.engine.fbu_performance.runs import (
    FBURunManager,
    build_final_result_rows,
)


pytestmark = pytest.mark.usefixtures("bypass_fbu_access_gate")


def _hours(base=0):
    return {
        "计薪出勤": base,
        "OT1.5": 0,
        "OT2.0": 0,
        "病假": 0,
        "病假清算": 0,
        "年假": 0,
        "节假日": 0,
    }


def test_period_adjustment_api_upserts_deletes_and_invalidates_results(tmp_path, monkeypatch):
    manager = FBURunManager(str(tmp_path))
    monkeypatch.setattr(app_module, "fbu_run_manager", manager)
    run = manager.create_run(calc_month="2026-06")
    manager.update_run(
        run.run_id,
        salary_data={
            "employees": [
                {"employee_id": "zt100", "name": "测试员工", "hourly_rate": 20, "ratio": 0.1}
            ]
        },
        results=[{"employee_id": "zt100", "performance_bonus": 100}],
        total_bonus=100,
    )
    client = TestClient(app_module.app)

    response = client.post(
        f"/api/fbu-performance/runs/{run.run_id}/period-adjustments",
        json={
            "action": "upsert",
            "employee_id": "zt100",
            "amount": 250,
            "source_month": "2026-05",
            "reason": "补发5月绩效基数差额",
        },
    )

    assert response.status_code == 200
    data = response.json()["period_adjustment_data"]
    assert data["summary"] == {"count": 1, "total_amount": 250.0}
    assert data["rows"][0]["name"] == "测试员工"
    assert manager.get_run(run.run_id).results == []

    invalid_month = client.post(
        f"/api/fbu-performance/runs/{run.run_id}/period-adjustments",
        json={
            "action": "upsert",
            "employee_id": "zt100",
            "amount": 250,
            "source_month": "2026-13",
            "reason": "无效月份",
        },
    )
    assert invalid_month.status_code == 400

    response = client.post(
        f"/api/fbu-performance/runs/{run.run_id}/period-adjustments",
        json={"action": "delete", "employee_id": "zt100"},
    )
    assert response.status_code == 200
    assert response.json()["period_adjustment_data"]["rows"] == []


def test_period_adjustment_is_applied_once_after_day_night_split(tmp_path):
    attendance = [
        {
            "employee_id": "zt100-1",
            "source_employee_id": "zt100",
            "name": "测试员工",
            "department": "新泽西区",
            "position": "测试岗位",
            "has_night_shift": False,
            "day_shift": _hours(8),
            "night_shift": _hours(),
            "attendance_daily_rows": [
                {"date": "2026-06-03", "shift_type": "白班", "base_hours": 8},
            ],
        },
        {
            "employee_id": "zt100",
            "source_employee_id": "zt100",
            "name": "测试员工",
            "department": "新泽西区",
            "position": "测试岗位",
            "has_night_shift": True,
            "day_shift": _hours(),
            "night_shift": _hours(8),
            "attendance_daily_rows": [
                {"date": "2026-06-04", "shift_type": "夜班", "base_hours": 8},
            ],
        },
    ]
    engine = FBUPerformanceParser().parse_all_from_step_data(
        attendance_data=attendance,
        salary_data=[{"employee_id": "zt100", "hourly_rate": 20, "ratio": 0.1}],
        performance_data=[
            {"employee_id": "zt100", "score": None, "level": "", "coefficient": 1.2}
        ],
        period_adjustment_data={
            "rows": [{
                "employee_id": "zt100",
                "amount": 100,
                "source_month": "2026-05",
                "reason": "补发5月绩效基数差额",
            }]
        },
        calc_month="2026-06",
    )

    employees = engine.get_all_employees()
    assert sum(employee.period_adjustment for employee in employees) == 100
    assert sum(employee.performance_base for employee in employees) == pytest.approx(
        sum(employee.system_performance_base for employee in employees) + 100
    )
    assert sum(employee.performance_bonus for employee in employees) == pytest.approx(
        sum(employee.system_performance_base for employee in employees) * 0.1 * 1.2
        + 100 * 0.1 * 1.2
    )

    manager = FBURunManager(str(tmp_path))
    run = manager.create_run(calc_month="2026-06")
    manager.save_results(run.run_id, employees)
    final = build_final_result_rows(manager.get_run(run.run_id).results)[0]
    assert final["period_adjustment"] == 100
    assert final["performance_base"] == pytest.approx(final["system_performance_base"] + 100)
    adjustment_segment = final["calculation_segments"][-1]
    assert adjustment_segment["is_period_adjustment"] is True
    assert adjustment_segment["performance_ratio"] == pytest.approx(0.1)
    assert adjustment_segment["performance_coefficient"] == pytest.approx(1.2)


def test_legacy_result_uses_existing_base_as_system_base():
    final = build_final_result_rows([{
        "employee_id": "zt100",
        "name": "测试员工",
        "performance_base": 1000,
        "performance_bonus": 100,
    }])[0]

    assert final["system_performance_base"] == 1000


def test_period_adjustment_is_visible_in_result_export(tmp_path, monkeypatch):
    manager = FBURunManager(str(tmp_path))
    monkeypatch.setattr(app_module, "fbu_run_manager", manager)
    monkeypatch.setattr(app_module, "EXPORT_DIR", tmp_path)
    run = manager.create_run(calc_month="2026-06")
    manager.save_results(
        run.run_id,
        [EmployeeData(
            employee_id="zt100",
            name="测试员工",
            department="新泽西区-测试部门",
            position="测试岗位",
            hourly_rate=20,
            performance_ratio=0.1,
            system_performance_base=1000,
            period_adjustment=200,
            period_adjustment_source_month="2026-05",
            period_adjustment_reason="补发5月绩效基数差额",
            performance_base=1200,
            performance_coefficient=1.2,
            performance_bonus=144,
        )],
    )

    response = TestClient(app_module.app).get(
        f"/api/fbu-performance/runs/{run.run_id}/export-excel?type=results"
    )

    assert response.status_code == 200
    workbook = load_workbook(tmp_path / response.json()["filename"], data_only=False)
    sheet = workbook["1.仓库管理人员"]
    headers = [cell.value for cell in sheet[3]]
    values = dict(zip(headers, [cell.value for cell in sheet[4]]))
    assert values["系统计算绩效基数"] == 1000
    assert values["Period adjustment"] == 200
    assert values["6月绩效基数"] == 1200
    assert "系统计算绩效基数：$1,000.00" in values["绩效基数计算过程"]
    assert "Period adjustment：$200.00" in values["绩效基数计算过程"]
    assert "最终绩效基数：$1,200.00" in values["绩效基数计算过程"]
    assert "$1,000.00 × 10.0% × 1.20 = $120.00" in values["奖金计算过程"]
    assert "$200.00 × 10.0% × 1.20 = $24.00" in values["奖金计算过程"]
