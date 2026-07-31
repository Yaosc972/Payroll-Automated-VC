from bonus_platform.engine.fbu_performance.runs import (
    FBURunManager,
    build_attendance_view_data,
)


def test_saving_changed_input_invalidates_existing_results(tmp_path):
    manager = FBURunManager(str(tmp_path))
    run = manager.create_run(calc_month="2026-05")
    manager.update_run(
        run.run_id,
        status="completed",
        current_step=5,
        results=[{"employee_id": "E001", "performance_bonus": 100}],
        total_employees=1,
        total_bonus=100,
        match_rate=1,
    )

    manager.save_step_data(run.run_id, 1, {"employees": [{"employee_id": "E001"}]})

    updated = manager.get_run(run.run_id)
    assert updated.status == "step1"
    assert updated.current_step == 1
    assert updated.results == []
    assert updated.total_employees == 0
    assert updated.total_bonus == 0
    assert updated.match_rate == 0


def test_attendance_save_builds_compact_view_without_mutating_source(tmp_path):
    manager = FBURunManager(str(tmp_path))
    run = manager.create_run(calc_month="2026-06")
    attendance = {
        "employees": [{
            "employee_id": "E001",
            "total_base_hours": 80,
            "attendance_daily_rows": [
                {"date": "2026-06-01", "base_hours": 8},
            ],
        }],
        "summary": {"total_employees": 1},
    }

    manager.save_step_data(run.run_id, 1, attendance)

    updated = manager.get_run(
        run.run_id,
        sections={"attendance_data", "attendance_view_data"},
    )
    assert updated.attendance_data["employees"][0]["attendance_daily_rows"]
    assert "attendance_daily_rows" not in updated.attendance_view_data["employees"][0]
    assert updated.attendance_view_data["employees"][0]["total_base_hours"] == 80
    assert updated.attendance_view_data["summary"] == {"total_employees": 1}


def test_empty_attendance_source_does_not_create_truthy_compact_view():
    assert build_attendance_view_data({}) == {}
    assert build_attendance_view_data({"employees": []}) == {}
    assert build_attendance_view_data({"employees": [None]}) == {}


def test_backfilling_hourly_rate_defaults_preserves_existing_results(tmp_path):
    manager = FBURunManager(str(tmp_path))
    run = manager.create_run(calc_month="2026-05")
    manager.update_run(
        run.run_id,
        status="completed",
        results=[{"employee_id": "E001", "performance_bonus": 100}],
        total_employees=1,
        total_bonus=100,
    )

    manager.backfill_hourly_rate_policy_data(
        run.run_id,
        {"rows": [{"row_id": "E001|2026-05-10"}], "summary": {"visible_count": 1}},
    )

    updated = manager.get_run(run.run_id)
    assert updated.hourly_rate_policy_data["summary"]["visible_count"] == 1
    assert updated.results == [{"employee_id": "E001", "performance_bonus": 100}]
    assert updated.total_bonus == 100
    assert updated.status == "completed"


def test_period_adjustment_change_invalidates_existing_results(tmp_path):
    manager = FBURunManager(str(tmp_path))
    run = manager.create_run(calc_month="2026-06")
    manager.update_run(
        run.run_id,
        status="completed",
        results=[{"employee_id": "E001", "performance_bonus": 100}],
        total_bonus=100,
    )

    manager.update_run(
        run.run_id,
        period_adjustment_data={
            "rows": [{"employee_id": "E001", "amount": 50}],
            "summary": {"count": 1, "total_amount": 50},
        },
    )

    updated = manager.get_run(run.run_id)
    assert updated.results == []
    assert updated.total_bonus == 0


def test_transfer_history_change_invalidates_existing_results(tmp_path):
    manager = FBURunManager(str(tmp_path))
    run = manager.create_run(calc_month="2026-06")
    manager.update_run(
        run.run_id,
        results=[{"employee_id": "E001", "performance_bonus": 100}],
        total_bonus=100,
    )

    manager.update_run(
        run.run_id,
        transfer_file="transfer.xlsx",
        transfer_data={"events": [{"employee_id": "E001", "effective_date": "2026-07-05"}]},
    )

    updated = manager.get_run(run.run_id)
    assert updated.results == []
    assert updated.total_bonus == 0
