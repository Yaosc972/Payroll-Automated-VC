from bonus_platform.engine.fbu_performance.parser import FBUPerformanceParser


def salary(employee_id, hourly_rate, ratio, **extra):
    return {
        "employee_id": employee_id,
        "hourly_rate": hourly_rate,
        "ratio": ratio,
        "calculation_method": "固定比例核算",
        "fixed_performance_base": 0,
        **extra,
    }


def event(employee_id, effective_date, hourly_rate, ratio, status="已完成", reason="晋升调薪"):
    return {
        "employee_id": employee_id,
        "name": "测试员工",
        "approval_status": status,
        "adjustment_reason": reason,
        "effective_date": effective_date,
        "hourly_rate": hourly_rate,
        "performance_ratio": ratio,
    }


def test_future_effective_change_uses_previous_values_for_entire_calc_month():
    result = FBUPerformanceParser.reconcile_salary_history(
        previous_salary=[salary("zt0020155", 18, 0.05)],
        current_salary=[salary("zt0020155", 21, 0.09)],
        adjustment_events=[event("zt0020155", "2026-06-01", 21, 0.09)],
        calc_month="2026-05",
    )

    row = result["employees"][0]
    assert row["hourly_rate"] == 18
    assert row["ratio"] == 0.05
    assert row["verification_status"] == "resolved"
    assert row["resolution"] == "future_effective_use_previous"
    assert row["effective_segments"] == []
    assert result["summary"]["blocking_count"] == 0


def test_in_month_zero_to_positive_ratio_creates_effective_date_segments():
    result = FBUPerformanceParser.reconcile_salary_history(
        previous_salary=[salary("zt0021990", 18, 0)],
        current_salary=[salary("zt0021990", 18, 0.05)],
        adjustment_events=[event("zt0021990", "2026-04-26", 18, 0.05, reason="转正调薪")],
        calc_month="2026-04",
    )

    row = result["employees"][0]
    assert row["hourly_rate"] == 18
    assert row["ratio"] == 0.05
    assert row["resolution"] == "in_month_split"
    assert row["effective_segments"] == [
        {
            "period_start": "2026-04-01",
            "period_end": "2026-04-25",
            "hourly_rate": 18,
            "performance_ratio": 0,
            "reason": "调薪前",
        },
        {
            "period_start": "2026-04-26",
            "period_end": "2026-04-30",
            "hourly_rate": 18,
            "performance_ratio": 0.05,
            "reason": "调薪后",
        },
    ]


def test_changed_values_without_completed_adjustment_are_blocking():
    result = FBUPerformanceParser.reconcile_salary_history(
        previous_salary=[salary("E001", 18, 0.05)],
        current_salary=[salary("E001", 21, 0.09)],
        adjustment_events=[],
        calc_month="2026-05",
    )

    row = result["employees"][0]
    assert row["verification_status"] == "blocking"
    assert row["resolution"] == "missing_adjustment"
    assert result["summary"]["blocking_count"] == 1


def test_stale_adjustment_cannot_explain_a_new_snapshot_change():
    result = FBUPerformanceParser.reconcile_salary_history(
        previous_salary=[salary("E001", 18, 0.05)],
        current_salary=[salary("E001", 18, 0)],
        adjustment_events=[event("E001", "2024-04-01", 18, 0)],
        calc_month="2026-05",
    )

    assert result["employees"][0]["resolution"] == "missing_adjustment"
    assert result["summary"]["blocking_count"] == 1


def test_new_employee_missing_previous_snapshot_uses_current_values_when_hire_date_explains_absence():
    result = FBUPerformanceParser.reconcile_salary_history(
        previous_salary=[],
        current_salary=[salary("E001", 21.63, 0.1111)],
        adjustment_events=[],
        calc_month="2026-05",
        roster_by_id={"E001": {"hire_date": "2026-05-03"}},
    )

    row = result["employees"][0]
    assert row["verification_status"] == "resolved"
    assert row["resolution"] == "new_employee_use_current"
    assert row["hourly_rate"] == 21.63
    assert row["ratio"] == 0.1111


def test_missing_previous_snapshot_is_blocking_without_new_hire_evidence():
    result = FBUPerformanceParser.reconcile_salary_history(
        previous_salary=[],
        current_salary=[salary("E001", 21.63, 0.1111)],
        adjustment_events=[],
        calc_month="2026-05",
        roster_by_id={"E001": {"hire_date": "2025-12-01"}},
    )

    row = result["employees"][0]
    assert row["verification_status"] == "blocking"
    assert row["resolution"] == "missing_previous_snapshot"
    assert result["summary"]["blocking_count"] == 1


def test_in_month_salary_history_segments_drive_bonus_calculation():
    parser = FBUPerformanceParser()
    resolved = FBUPerformanceParser.reconcile_salary_history(
        previous_salary=[salary("E001", 18, 0)],
        current_salary=[salary("E001", 18, 0.05)],
        adjustment_events=[event("E001", "2026-04-26", 18, 0.05, reason="转正调薪")],
        calc_month="2026-04",
    )

    engine = parser.parse_all_from_step_data(
        attendance_data=[
            {
                "employee_id": "E001",
                "name": "测试员工",
                "department": "测试仓",
                "area": "新泽西区",
                "personnel_status": "正式",
                "position": "Tallyman 理货员",
                "job_type": "warehouse",
                "has_night_shift": False,
                "day_shift": {"计薪出勤": 16, "OT1.5": 0, "OT2.0": 0, "病假": 0, "年假": 0, "节假日": 0},
                "night_shift": {"计薪出勤": 0, "OT1.5": 0, "OT2.0": 0, "病假": 0, "年假": 0, "节假日": 0},
                "attendance_daily_rows": [
                    {"date": "2026-04-25", "shift_type": "白班", "base_hours": 8},
                    {"date": "2026-04-26", "shift_type": "白班", "base_hours": 8},
                ],
            }
        ],
        salary_data=resolved["employees"],
        performance_data=[
            {"employee_id": "E001", "score": 95, "level": "B", "coefficient": 1}
        ],
        calc_month="2026-04",
    )

    employee = engine.get_employee("E001")
    assert round(employee.performance_bonus, 2) == 7.20
    assert [segment.reason for segment in employee.calculation_segments] == ["调薪前", "调薪后"]
    assert [segment.performance_ratio for segment in employee.calculation_segments] == [0, 0.05]


def test_verified_salary_history_is_not_overwritten_by_stale_legacy_adjustment_event():
    parser = FBUPerformanceParser()
    verified_salary = salary(
        "E001",
        21,
        0.05,
        verification_status="resolved",
        resolution="unchanged",
        effective_segments=[],
    )

    engine = parser.parse_all_from_step_data(
        attendance_data=[
            {
                "employee_id": "E001",
                "name": "测试员工",
                "department": "测试仓",
                "area": "新泽西区",
                "personnel_status": "正式",
                "position": "Deputy Team Leader 副组长",
                "job_type": "warehouse",
                "has_night_shift": False,
                "day_shift": {"计薪出勤": 8, "OT1.5": 0, "OT2.0": 0, "病假": 0, "年假": 0, "节假日": 0},
                "night_shift": {"计薪出勤": 0, "OT1.5": 0, "OT2.0": 0, "病假": 0, "年假": 0, "节假日": 0},
                "attendance_daily_rows": [
                    {"date": "2026-05-01", "shift_type": "白班", "base_hours": 8},
                ],
            }
        ],
        salary_data=[verified_salary],
        performance_data=[
            {"employee_id": "E001", "score": 95, "level": "B", "coefficient": 1}
        ],
        adjustment_data={
            "employees": [],
            "events": [event("E001", "2025-08-01", 18, 0.05, reason="转正调薪")],
        },
        calc_month="2026-05",
    )

    employee = engine.get_employee("E001")
    assert employee.hourly_rate == 21
    assert employee.performance_base == 168
