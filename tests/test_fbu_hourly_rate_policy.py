from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

import bonus_platform.app as app_module
from bonus_platform.engine.fbu_performance.parser import (
    FBUPerformanceParser,
    build_hourly_rate_policy_data,
    update_hourly_rate_policy_data,
)
from bonus_platform.engine.fbu_performance.runs import FBURunManager


pytestmark = pytest.mark.usefixtures("bypass_fbu_access_gate")


def _shift_hours(**overrides):
    values = {
        "计薪出勤": 0,
        "OT1.5": 0,
        "OT2.0": 0,
        "病假": 0,
        "病假清算": 0,
        "年假": 0,
        "节假日": 0,
    }
    values.update(overrides)
    return values


def _preview_row(employee_id, shift_type, daily_rows, **overrides):
    is_night = shift_type == "夜班"
    shift_hours = _shift_hours()
    for row in daily_rows:
        shift_hours["计薪出勤"] += row.get("base_hours", 0)
        shift_hours["OT1.5"] += row.get("ot15_hours", 0)
        shift_hours["OT2.0"] += row.get("ot20_hours", 0)
        shift_hours["病假"] += row.get("sick_hours", 0)
        shift_hours["年假"] += row.get("annual_hours", 0)
    return {
        "employee_id": employee_id,
        "source_employee_id": employee_id.removesuffix("-1"),
        "name": overrides.get("name", "测试员工"),
        "department": "新泽西区",
        "position": "测试岗位",
        "shift_type": shift_type,
        "has_night_shift": is_night,
        "day_shift": _shift_hours() if is_night else shift_hours,
        "night_shift": shift_hours if is_night else _shift_hours(),
        "attendance_daily_rows": [
            {**row, "shift_type": shift_type}
            for row in daily_rows
        ],
    }


def test_period_suggestions_cover_all_night_mixed_and_exclude_leave_only():
    preview = {
        "employees": [
            _preview_row("zt100", "夜班", [{"date": "2026-06-03", "base_hours": 8}]),
            _preview_row("zt200-1", "白班", [{"date": "2026-06-04", "base_hours": 8}]),
            _preview_row("zt200", "夜班", [{"date": "2026-06-05", "base_hours": 8}]),
            _preview_row("zt300", "白班", [{"date": "2026-06-06", "sick_hours": 8}]),
        ],
    }

    data = build_hourly_rate_policy_data(preview, "2026-06")
    by_employee = {}
    for row in data["rows"]:
        by_employee.setdefault(row["employee_id"], []).append(row)

    assert by_employee["zt100"][0]["suggested_policy"] == "night"
    assert by_employee["zt100"][0]["visible"] is True
    assert by_employee["zt200"][0]["suggested_policy"] == "by_shift"
    assert by_employee["zt200"][0]["visible"] is True
    assert "zt300" not in by_employee


def test_rebuild_preserves_manual_override_for_same_employee_period():
    preview = {
        "employees": [
            _preview_row("zt100", "白班", [{"date": "2026-06-03", "base_hours": 8}]),
        ],
    }
    initial = build_hourly_rate_policy_data(preview, "2026-06")
    row_id = initial["rows"][0]["row_id"]
    changed = update_hourly_rate_policy_data(
        initial,
        action="update",
        row_id=row_id,
        selected_policy="night",
    )

    rebuilt = build_hourly_rate_policy_data(preview, "2026-06", changed)

    assert rebuilt["rows"][0]["selected_policy"] == "night"
    assert rebuilt["rows"][0]["manual_override"] is True
    assert rebuilt["rows"][0]["visible"] is True


def test_full_period_night_rate_applies_to_white_ot_sick_and_annual_hours():
    attendance = [
        _preview_row(
            "zt100",
            "白班",
            [{
                "date": "2026-06-03",
                "base_hours": 8,
                "ot15_hours": 2,
                "sick_hours": 3,
                "annual_hours": 4,
            }],
        ),
    ]
    policies = build_hourly_rate_policy_data({"employees": attendance}, "2026-06")
    policies = update_hourly_rate_policy_data(
        policies,
        action="update",
        row_id=policies["rows"][0]["row_id"],
        selected_policy="night",
    )

    engine = FBUPerformanceParser().parse_all_from_step_data(
        attendance_data=deepcopy(attendance),
        salary_data=[{
            "employee_id": "zt100",
            "hourly_rate": 23,
            "ratio": 0.1,
        }],
        performance_data=[{
            "employee_id": "zt100",
            "score": 100,
            "level": "",
            "coefficient": 1,
        }],
        calc_month="2026-06",
        hourly_rate_policy_data=policies,
    )

    employee = engine.get_all_employees()[0]
    assert employee.hourly_rate == 24
    assert employee.base_salary == pytest.approx(8 * 24)
    assert employee.ot15_salary == pytest.approx(2 * 24 * 1.5)
    assert employee.sick_pay == pytest.approx(3 * 24)
    assert employee.annual_leave_pay == pytest.approx(4 * 24)
    assert employee.performance_base == pytest.approx(432)


def test_policy_api_updates_suggestion_and_invalidates_old_results(tmp_path, monkeypatch):
    manager = FBURunManager(str(tmp_path))
    monkeypatch.setattr(app_module, "fbu_run_manager", manager)
    run = manager.create_run(calc_month="2026-06")
    attendance = {
        "employees": [
            _preview_row("zt100", "夜班", [{"date": "2026-06-03", "base_hours": 8}]),
        ],
    }
    policies = build_hourly_rate_policy_data(attendance, "2026-06")
    manager.update_run(
        run.run_id,
        attendance_data=attendance,
        hourly_rate_policy_data=policies,
    )
    manager.update_run(
        run.run_id,
        results=[{"employee_id": "zt100", "performance_bonus": 100}],
        total_bonus=100,
    )
    row_id = policies["rows"][0]["row_id"]

    response = TestClient(app_module.app).post(
        f"/api/fbu-performance/runs/{run.run_id}/hourly-rate-policies",
        json={"action": "update", "row_id": row_id, "selected_policy": "base"},
    )

    assert response.status_code == 200
    updated = manager.get_run(run.run_id)
    assert updated.hourly_rate_policy_data["rows"][0]["selected_policy"] == "base"
    assert updated.hourly_rate_policy_data["rows"][0]["manual_override"] is True
    assert updated.results == []
