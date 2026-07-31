from io import BytesIO

import openpyxl
import pytest
from fastapi.testclient import TestClient

import bonus_platform.app as app_module
from bonus_platform.engine.fbu_performance.parser import FBUPerformanceParser
from bonus_platform.engine.fbu_performance.runs import FBURunManager, FBURosterStore


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


def _attendance(employee_id, rows, position="Deputy Inbound Team Leader 入库组副组长"):
    return [{
        "employee_id": employee_id,
        "source_employee_id": employee_id,
        "name": "刘舰锶",
        "department": "入库组（自动化）",
        "area": "新泽西区",
        "position": position,
        "personnel_status": "正式",
        "shift_type": "白班",
        "has_night_shift": False,
        "day_shift": _hours(sum(row.get("base_hours", 0) for row in rows)),
        "night_shift": _hours(),
        "attendance_daily_rows": [
            {**row, "shift_type": "白班"}
            for row in rows
        ],
    }]


def _transfer_event(effective_date="2026-07-05", approval_status="已完成"):
    return {
        "employee_id": "zt0021874",
        "name": "刘舰锶",
        "effective_date": effective_date,
        "approval_status": approval_status,
        "before_department": "管培组",
        "before_position": "Management Trainee 管培生",
        "before_area": "新泽西区",
        "after_department": "入库组（自动化）",
        "after_position": "Deputy Inbound Team Leader 入库组副组长",
        "after_area": "新泽西区",
    }


def _transfer_workbook_bytes(rows=None):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append([
        "姓名",
        "工号",
        "调动日期",
        "异动类型",
        "异动原因",
        "调动前部门",
        "调动前职位",
        "调动前划分区域",
        "调动前成本中心",
        "调动后部门",
        "调动后职位",
        "调动后划分区域",
        "调动后成本中心",
        "审批状态",
        "备注",
    ])
    for row in rows or [
        [
            "刘舰锶",
            "zt0021874",
            "2026/07/05",
            "晋升",
            "人才培养岗位轮换",
            "管培组",
            "Management Trainee 管培生",
            "新泽西区",
            "NJ",
            "入库组（自动化）",
            "Deputy Inbound Team Leader 入库组副组长",
            "新泽西区",
            "NJ",
            "已完成",
            "定岗",
        ],
    ]:
        sheet.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_transfer_preview_only_uses_completed_records(tmp_path):
    path = tmp_path / "transfer.xlsx"
    rows = [
        [
            "刘舰锶", "zt0021874", "2026/07/05", "晋升", "定岗",
            "管培组", "Management Trainee 管培生", "新泽西区", "NJ",
            "入库组", "Deputy Inbound Team Leader 入库组副组长", "新泽西区", "NJ",
            "已完成", "",
        ],
        [
            "刘舰锶", "zt0021874", "2026/07/20", "调动", "",
            "入库组", "副组长", "新泽西区", "NJ",
            "出库组", "组长", "新泽西区", "NJ",
            "审批中", "",
        ],
    ]
    path.write_bytes(_transfer_workbook_bytes(rows))

    preview = FBUPerformanceParser().parse_transfer_history_preview(str(path), "2026-07")

    assert preview["summary"]["total_rows"] == 2
    assert preview["summary"]["completed_count"] == 1
    assert preview["summary"]["ignored_count"] == 1
    assert preview["events"][0]["effective_date"] == "2026-07-05"
    assert preview["events"][0]["before_position"] == "Management Trainee 管培生"


def test_future_transfer_restores_old_role_for_entire_calculation_month():
    engine = FBUPerformanceParser().parse_all_from_step_data(
        attendance_data=_attendance(
            "zt0021874",
            [{"date": "2026-06-10", "base_hours": 8}],
        ),
        salary_data=[{
            "employee_id": "zt0021874",
            "hourly_rate": 18,
            "ratio": 0.09,
        }],
        performance_data=[],
        transfer_data={"events": [_transfer_event()]},
        calc_month="2026-06",
    )

    employee = engine.get_all_employees()[0]
    assert employee.department == "管培组"
    assert employee.position == "Management Trainee 管培生"
    assert employee.performance_coefficient == 1
    assert employee.performance_base == 144
    assert employee.performance_bonus == pytest.approx(12.96)
    assert "未匹配绩效报表" not in employee.exceptions


def test_in_month_transfer_splits_actual_attendance_by_effective_date():
    engine = FBUPerformanceParser().parse_all_from_step_data(
        attendance_data=_attendance(
            "zt0021874",
            [
                {"date": "2026-07-04", "base_hours": 8},
                {"date": "2026-07-05", "base_hours": 8},
            ],
        ),
        salary_data=[{
            "employee_id": "zt0021874",
            "hourly_rate": 18,
            "ratio": 0.09,
        }],
        performance_data=[{
            "employee_id": "zt0021874",
            "score": 100,
            "level": "",
            "coefficient": 1.2,
        }],
        transfer_data={"events": [_transfer_event()]},
        calc_month="2026-07",
    )

    employee = engine.get_all_employees()[0]
    assert employee.position == "Deputy Inbound Team Leader 入库组副组长"
    assert len(employee.calculation_segments) == 2
    before, after = employee.calculation_segments
    assert before.period == "7.4-7.4"
    assert before.position == "Management Trainee 管培生"
    assert before.performance_coefficient == 1
    assert after.period == "7.5-7.5"
    assert after.position == "Deputy Inbound Team Leader 入库组副组长"
    assert after.performance_coefficient == 1.2
    assert employee.performance_bonus == pytest.approx(28.512)


def test_transfer_upload_persists_preview_and_invalidates_results(tmp_path, monkeypatch):
    manager = FBURunManager(str(tmp_path))
    monkeypatch.setattr(app_module, "FBU_PERFORMANCE_RUNS_DIR", tmp_path)
    monkeypatch.setattr(app_module, "fbu_run_manager", manager)
    monkeypatch.setattr(app_module, "fbu_roster_store", FBURosterStore(str(tmp_path)))
    run = manager.create_run(calc_month="2026-06")
    manager.update_run(
        run.run_id,
        results=[{"employee_id": "zt0021874", "performance_bonus": 1}],
        total_bonus=1,
    )

    response = TestClient(app_module.app).post(
        "/api/fbu-performance/import-transfer-history",
        data={"run_id": run.run_id},
        files={
            "file": (
                "transfer.xlsx",
                _transfer_workbook_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        },
    )

    assert response.status_code == 200
    updated = manager.get_run(run.run_id)
    assert updated.transfer_file == "transfer.xlsx"
    assert updated.transfer_data["summary"]["completed_count"] == 1
    assert updated.results == []
    assert (tmp_path / run.run_id / "transfer_history.xlsx").exists()
