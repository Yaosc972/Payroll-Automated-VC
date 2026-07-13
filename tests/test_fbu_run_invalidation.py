from bonus_platform.engine.fbu_performance.runs import FBURunManager


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
