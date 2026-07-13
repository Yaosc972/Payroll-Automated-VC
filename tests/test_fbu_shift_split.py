from bonus_platform.engine.fbu_performance.parser import FBUPerformanceParser


def _shift_hours(base=0, ot15=0, ot20=0, sick=0, annual=0, holiday=0):
    return {
        "计薪出勤": base,
        "OT1.5": ot15,
        "OT2.0": ot20,
        "病假": sick,
        "年假": annual,
        "节假日": holiday,
    }


def _build_employees(attendance):
    parser = FBUPerformanceParser()
    return parser.build_employees(
        attendance,
        salary_data={"zt001": {"hourly_rate": 20, "ratio": 0.1}},
        performance_data={"zt001": {"score": 95, "level": "A"}},
        employee_info={"zt001": {"name": "测试员工", "department": "测试部门", "area": "测试区域", "job_type": "warehouse"}},
    )


def test_mixed_day_and_night_keeps_night_on_original_id_and_suffixes_day_id():
    employees = _build_employees({
        "zt001": {
            "白班": _shift_hours(base=8, ot15=2),
            "夜班": _shift_hours(base=7, ot15=1),
            "has_night_shift": True,
        }
    })

    by_id = {employee.employee_id: employee for employee in employees}

    assert set(by_id) == {"zt001-1", "zt001"}
    assert by_id["zt001-1"].is_night_shift is False
    assert by_id["zt001-1"].hourly_rate == 20
    assert by_id["zt001"].is_night_shift is True
    assert by_id["zt001"].hourly_rate == 21


def test_single_shift_employees_do_not_get_suffix():
    day_only = _build_employees({
        "zt001": {
            "白班": _shift_hours(base=8),
            "夜班": _shift_hours(),
            "has_night_shift": False,
        }
    })
    night_only = _build_employees({
        "zt001": {
            "白班": _shift_hours(),
            "夜班": _shift_hours(base=8),
            "has_night_shift": True,
        }
    })

    assert [employee.employee_id for employee in day_only] == ["zt001"]
    assert day_only[0].is_night_shift is False
    assert [employee.employee_id for employee in night_only] == ["zt001"]
    assert night_only[0].is_night_shift is True
    assert night_only[0].hourly_rate == 21


def test_attendance_preview_rows_are_physically_split_for_mixed_shift():
    parser = FBUPerformanceParser()
    rows = parser.build_attendance_preview_rows({
        "zt001": {
            "白班": _shift_hours(base=8, ot15=2, sick=1),
            "夜班": _shift_hours(base=7, ot15=1, annual=3),
            "has_night_shift": True,
        }
    })

    by_id = {row["employee_id"]: row for row in rows}

    assert set(by_id) == {"zt001-1", "zt001"}
    assert by_id["zt001-1"]["shift_type"] == "白班"
    assert by_id["zt001-1"]["day_shift"]["计薪出勤"] == 8
    assert by_id["zt001-1"]["night_shift"]["计薪出勤"] == 0
    assert by_id["zt001-1"]["total_ot15"] == 2
    assert by_id["zt001-1"]["sick_hours"] == 1
    assert by_id["zt001-1"]["annual_hours"] == 0

    assert by_id["zt001"]["shift_type"] == "夜班"
    assert by_id["zt001"]["day_shift"]["计薪出勤"] == 0
    assert by_id["zt001"]["night_shift"]["计薪出勤"] == 7
    assert by_id["zt001"]["total_ot15"] == 1
    assert by_id["zt001"]["sick_hours"] == 0
    assert by_id["zt001"]["annual_hours"] == 3


def test_split_preview_rows_match_salary_by_original_employee_id():
    parser = FBUPerformanceParser()
    employees = parser.build_employees(
        attendance_data={
            "zt001-1": {
                "白班": _shift_hours(base=8),
                "夜班": _shift_hours(),
                "has_night_shift": False,
            },
            "zt001": {
                "白班": _shift_hours(),
                "夜班": _shift_hours(base=7),
                "has_night_shift": True,
            },
        },
        salary_data={"zt001": {"hourly_rate": 20, "ratio": 0.1}},
        performance_data={"zt001": {"score": 95, "level": "A"}},
        employee_info={"zt001": {"name": "测试员工", "department": "测试部门", "area": "测试区域", "job_type": "warehouse"}},
    )

    by_id = {employee.employee_id: employee for employee in employees}

    assert by_id["zt001-1"].hourly_rate == 20
    assert by_id["zt001"].hourly_rate == 21
    assert by_id["zt001-1"].performance_ratio == 0.1
    assert by_id["zt001"].performance_ratio == 0.1


def test_leave_only_shift_is_preserved_in_preview_and_calculation_rows():
    parser = FBUPerformanceParser()
    rows = parser.build_attendance_preview_rows({
        "zt001": {
            "白班": _shift_hours(annual=8),
            "夜班": _shift_hours(),
            "has_night_shift": False,
        }
    })
    employees = _build_employees({
        "zt001": {
            "白班": _shift_hours(annual=8),
            "夜班": _shift_hours(),
            "has_night_shift": False,
        }
    })

    assert len(rows) == 1
    assert rows[0]["employee_id"] == "zt001"
    assert rows[0]["shift_type"] == "白班"
    assert rows[0]["annual_hours"] == 8
    assert len(employees) == 1
    assert employees[0].annual_hours == 8
