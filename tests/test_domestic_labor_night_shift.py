from datetime import time
import json

import pytest

from bonus_platform.engine.domestic_labor.engines.yeban_butie import YeBanBuTieEngine


def _day(start, end, shift="DN06", **extra):
    return {
        "工号": "TEST001",
        "姓名": "测试员工",
        "出勤日期": "2026-05-01",
        "班次编号": shift,
        "上班一": start,
        "下班一": end,
        **extra,
    }


def test_generic_night_shift_rounds_clips_deducts_break_and_caps_at_25():
    result = YeBanBuTieEngine().calculate_day(
        _day("20:17", "10:12"),
        break_periods=["24:00-25:00"],
    )

    assert result.status == "calculated"
    assert result.amount == 25.0
    assert result.rounded_start_minutes == 20 * 60 + 30
    assert result.rounded_end_minutes == 34 * 60
    assert result.night_minutes == 10 * 60
    assert result.break_minutes == 60


def test_night_shift_does_not_pay_before_the_scheduled_shift_start():
    result = YeBanBuTieEngine().calculate_day(
        _day(
            "22:10",
            "09:51",
            shift="LB51",
            班次时间段="23:00-32:00;",
        ),
        break_periods=["24:00-25:00"],
    )

    assert result.status == "calculated"
    assert result.night_minutes == 9 * 60
    assert result.break_minutes == 60
    assert result.amount == 24.0


def test_confirmed_start_boundary_does_not_assume_an_end_boundary():
    result = YeBanBuTieEngine().calculate_day(
        _day(
            "11:46",
            "22:33",
            shift="LB68",
            班次时间段="12:00-20:30;",
        ),
    )

    assert result.status == "calculated"
    assert result.night_minutes == 30
    assert result.amount == 0.0


def test_night_shift_does_not_deduct_breaks_outside_the_night_window():
    result = YeBanBuTieEngine().calculate_day(
        _day("12:49", "00:29", shift="LB06"),
        break_periods=[
            {"period": "18:00-18:30", "category": "其他休息"},
            {"period": "23:00-24:00", "category": "晚上休息"},
        ],
    )

    assert result.status == "calculated"
    assert result.night_minutes == 2 * 60
    assert result.other_break_minutes == 0
    assert result.evening_break_minutes == 60
    assert result.break_minutes == 60
    assert result.amount == 3.0


def test_night_shift_keeps_evening_and_morning_breaks_separate():
    result = YeBanBuTieEngine().calculate_day(
        _day("22:00", "07:30", shift="HD021"),
        break_periods=[
            {"period": "23:00-24:00", "category": "晚上休息"},
            {"period": "06:00-06:30", "category": "早上休息"},
        ],
    )

    assert result.status == "calculated"
    assert result.night_minutes == 9.5 * 60
    assert result.evening_break_minutes == 60
    assert result.morning_break_minutes == 30
    assert result.break_minutes == 90
    assert result.amount == 24
    assert result.to_dict()["break_details"] == [
        {
            "period": "23:00-24:00",
            "category": "晚上休息",
            "deducted_minutes": 60,
        },
        {
            "period": "06:00-06:30",
            "category": "早上休息",
            "deducted_minutes": 30,
        },
    ]


def test_night_shift_daily_audit_with_excel_time_is_json_serializable():
    result = YeBanBuTieEngine().calculate_day(
        _day(time(20, 17), time(8, 12)),
        break_periods=["24:00-25:00"],
    )

    payload = result.to_dict()

    assert payload["raw_start"] == "20:17:00"
    assert payload["raw_end"] == "08:12:00"
    json.dumps(payload, ensure_ascii=False)


def test_generic_night_shift_discards_partial_half_hour_after_breaks():
    result = YeBanBuTieEngine().calculate_day(
        _day("22:14", "01:44"),
        break_periods=["00:10-00:30"],
    )

    assert result.status == "calculated"
    assert result.night_minutes == 180
    assert result.break_minutes == 20
    assert result.amount == 7.5


@pytest.mark.parametrize(('rest', 'expected'), [
    ('22:00-23:01', 0),  # 扣休息后59分钟
    ('22:00-23:00', 3),
    ('22:00-22:59', 3),
    ('22:00-22:31', 3),
    ('22:00-22:30', 4.5),
    ('22:00-22:29', 4.5),
])
def test_one_hour_threshold_and_half_hour_floor_after_breaks(rest, expected):
    result = YeBanBuTieEngine().calculate_day(
        _day('22:00', '00:00'), break_periods=[rest],
    )
    assert result.amount == expected


def test_post_midnight_start_is_treated_as_previous_nights_second_half():
    result = YeBanBuTieEngine().calculate_day(
        _day("00:50", "09:07", shift="HD024"),
        break_periods=["06:00-06:30"],
    )

    assert result.status == "calculated"
    assert result.amount == 19.5
    assert result.night_minutes == 7 * 60
    assert result.break_minutes == 30


@pytest.mark.parametrize(('start', 'end'), [('05:58', '22:30'), ('05:48', '22:14'), ('05:49', '22:08')])
def test_early_shift_keeps_morning_window_when_finishing_after_22(start, end):
    result = YeBanBuTieEngine().calculate_day(
        _day(start, end, shift='HD003', 班次时间段='06:00-15:00;'),
        break_periods=['12:00-13:00', '18:00-18:30'],
    )
    assert result.amount == 6
    assert result.night_minutes == 120
    assert result.break_minutes == 0
    assert result.status == 'calculated'
    assert result.reason_code == 'generic_rule'


def test_early_shift_keeps_break_deduction_and_minimum_duration():
    result = YeBanBuTieEngine().calculate_day(
        _day('07:01', '22:30', shift='HD003', 班次时间段='06:00-15:00;'),
    )
    assert result.amount == 0
    result = YeBanBuTieEngine().calculate_day(
        _day('05:58', '22:30', 班次时间段='06:00-15:00;'),
        break_periods=['06:00-06:30'],
    )
    assert result.amount == 4.5
    assert result.break_minutes == 30


def test_both_night_windows_sum_independently_without_duration_review():
    result = YeBanBuTieEngine().calculate_day(
        _day('05:58', '23:30', shift='HD003', 班次时间段='06:00-15:00;'),
    )
    assert result.amount == 10.5
    assert result.status == 'calculated'
    assert result.reason_code == 'generic_rule'
    assert result.night_minutes == 210


def test_confirmed_dual_window_case_and_independent_threshold():
    engine = YeBanBuTieEngine()
    assert engine.calculate_day(_day('05:56', '23:00', shift='HD003', 班次时间段='06:00-15:00;')).amount == 9
    assert engine.calculate_day(_day('05:58', '22:30', shift='HD003', 班次时间段='06:00-15:00;')).amount == 6
    result = engine.calculate_day(_day('07:01', '23:00', shift='HD003', 班次时间段='06:00-15:00;'))
    assert result.amount == 3
    result = engine.calculate_day(_day('05:56', '23:00', shift='HD003', 班次时间段='06:00-15:00;'), ['06:00-06:30', '22:00-22:30'])
    assert result.amount == 4.5
    assert result.break_minutes == 60


@pytest.mark.parametrize('start,end,expected', [
    ('01:00', '23:00', 24),
    ('00:30', '23:00', 25),
    ('00:01', '23:30', 25),
])
def test_dual_window_combined_daily_cap(start, end, expected):
    result = YeBanBuTieEngine().calculate_day(_day(start, end, shift='HD003', 班次时间段='00:00-09:00;'))
    assert result.amount == expected
    assert result.status == 'calculated'
    assert result.reason_code == 'generic_rule'


def test_early_punch_for_eight_am_shift_preserves_evening_payment():
    result = YeBanBuTieEngine().calculate_day(
        _day('07:31', '23:50', shift='LB03', 班次时间段='08:00-17:00;'),
        break_periods=['12:00-13:00', '18:00-18:30', '23:00-24:00'],
    )
    assert result.amount == 3


def test_partial_break_overlap_deducts_only_rounded_actual_coverage():
    result = YeBanBuTieEngine().calculate_day(
        _day("00:50", "06:45", shift="HD999"),
        break_periods=["06:00-07:00"],
    )

    assert result.status == "calculated"
    assert result.reason_code == "generic_rule"
    assert result.break_minutes == 30
    assert result.amount == 15.0


def test_missing_punch_is_excluded_and_long_duration_is_calculated():
    engine = YeBanBuTieEngine()

    daytime = engine.calculate_day(_day("08:30", "17:30"))
    missing = engine.calculate_day(_day(None, "08:00"))
    implausible = engine.calculate_day(_day("10:00", "09:00"))

    assert (daytime.status, daytime.reason_code, daytime.amount) == (
        "excluded",
        "no_night_overlap",
        0.0,
    )
    assert (missing.status, missing.reason_code) == ("excluded", "missing_punch")
    assert missing.amount == 0
    assert (implausible.status, implausible.reason_code, implausible.amount) == (
        "calculated",
        "generic_rule",
        25.0,
    )


def test_missing_punch_does_not_require_review_even_for_scheduled_night_shift():
    engine = YeBanBuTieEngine()

    rest_day = engine.calculate_day(
        _day(None, None, 工作状态="星期天休息", 班次时间段="21:00-30:00;")
    )
    scheduled_day = engine.calculate_day(
        _day(None, None, 工作状态="工作日", 班次时间段="09:00-18:00;")
    )
    scheduled_night = engine.calculate_day(
        _day(None, None, 工作状态="工作日", 班次时间段="21:00-30:00;")
    )

    assert (rest_day.status, rest_day.reason_code, rest_day.amount) == (
        "excluded",
        "no_scheduled_night_work",
        0.0,
    )
    assert (scheduled_day.status, scheduled_day.reason_code, scheduled_day.amount) == (
        "excluded",
        "no_scheduled_night_work",
        0.0,
    )
    assert (scheduled_night.status, scheduled_night.reason_code, scheduled_night.amount) == (
        "excluded",
        "missing_punch",
        0.0,
    )


def test_three_am_shift_uses_confirmed_regular_shift_formula_without_review():
    result = YeBanBuTieEngine().calculate_day(
        _day("03:00", "11:30", shift="LB15", 班次时间段="03:00-11:30;"),
        break_periods=["18:00-18:30"],
    )

    assert result.status == "calculated"
    assert result.reason_code == "three_am_shift_rule"
    assert result.night_minutes == 8 * 60
    assert result.break_minutes == 0
    assert result.break_details == [{
        "period": "18:00-18:30",
        "category": "其他休息",
        "deducted_minutes": 0.0,
    }]
    assert result.amount == 25.0


@pytest.mark.parametrize(
    ("start", "end", "expected_regular_minutes", "expected_amount"),
    [
        ("03:05", "11:30", 7.5 * 60, 23.4375),
        ("03:32", "14:35", 7 * 60, 21.875),
        ("03:14", "09:49", 5.5 * 60, 17.1875),
    ],
)
def test_three_am_short_shift_prorates_regular_hours_and_ignores_overtime(
    start, end, expected_regular_minutes, expected_amount
):
    result = YeBanBuTieEngine().calculate_day(
        _day(start, end, shift="LB15", 班次时间段="03:00-11:30;"),
        break_periods=["18:00-18:30"],
    )

    assert result.status == "calculated"
    assert result.reason_code == "three_am_shift_rule"
    assert result.night_minutes == expected_regular_minutes
    assert result.break_minutes == 0
    assert result.amount == expected_amount


def test_monthly_result_sums_only_calculated_days_and_rounds_after_sum():
    result = YeBanBuTieEngine().calculate(
        {"工号": "TEST001", "姓名": "测试员工"},
        daily_attendance=[
            _day("22:14", "01:44", shift="DN99"),
            _day("20:17", "10:12", shift="DN06"),
            _day("08:30", "17:30", shift="DAY"),
            _day(None, "08:00", shift="DN06"),
        ],
        shift_breaks={"DN99": ["00:10-00:30"], "DN06": ["24:00-25:00"]},
    )

    assert result.amount == 32.5
    assert result.details["calculated_days"] == 2
    assert result.details["excluded_days"] == 2
    assert result.details["manual_review_days"] == 0
    assert result.details["review_calculated_days"] == 0
    assert result.details["unpriced_review_days"] == 0
    assert len(result.details["daily_results"]) == 4
    assert result.warnings == []


def test_dongguan_piecework_uses_normal_rule_instead_of_being_blocked():
    result = YeBanBuTieEngine().calculate(
        {"工号": "DG001", "姓名": "东莞员工", "工作地区": "东莞", "岗位名称": "操作员"},
        [_day("22:00", "08:00", shift="LB01", 工号="DG001", 工作地区="东莞", 计时="计件")],
        config={
            "shift_breaks": [{"shift_code": "LB01", "break_periods": []}],
            "jinjiang_exclusions": [],
            "jinjiang_list_confirmed": True,
        },
    )

    assert result.amount == 25.0
    assert result.details["calculated_days"] == 1
    assert result.details["pending_rule_days"] == 0
    assert result.details["daily_results"][0]["reason_code"] == "generic_rule"


@pytest.mark.parametrize(('area', 'position', 'shift', 'amount'), [
    ('东莞', '保洁', 'LB05', 0),
    ('东莞', '保洁', 'NEW', 0),
    ('东莞', '操作员', 'LB05', 25),
    ('晋江', '保洁', 'LB05', 25),
])
def test_dongguan_cleaner_exclusion_is_independent_of_shift(area, position, shift, amount):
    result = YeBanBuTieEngine().calculate(
        {'工号': 'TEST001', '工作地区': area, '岗位名称': position},
        [_day('22:00', '08:00', shift=shift)],
        config={'shift_breaks': [{'shift_code': 'LB05', 'break_periods': []}],
                'jinjiang_list_confirmed': True},
    )
    assert result.amount == amount
    if area == '东莞' and position == '保洁':
        assert result.details['daily_results'][0]['reason_code'] == 'dongguan_cleaner_excluded'
        assert result.details['excluded_days'] == 1


def test_dongguan_lb39_is_excluded_by_shift_code_without_affecting_other_areas():
    engine = YeBanBuTieEngine()
    config = {
        "shift_breaks": [{"shift_code": "LB39", "break_periods": []}],
        "jinjiang_exclusions": [],
        "jinjiang_list_confirmed": True,
    }

    dongguan = engine.calculate(
        {"工号": "DG001", "姓名": "东莞员工", "工作地区": "东莞", "岗位名称": "保洁"},
        [_day("22:00", "08:00", shift="LB39", 工号="DG001")],
        config=config,
    )
    jiashan = engine.calculate(
        {"工号": "HD001", "姓名": "嘉善员工", "工作地区": "嘉善", "岗位名称": "操作员"},
        [_day("22:00", "08:00", shift="LB39", 工号="HD001")],
        config=config,
    )

    assert dongguan.amount == 0
    assert dongguan.details["excluded_days"] == 1
    assert dongguan.details["daily_results"][0]["reason_code"] == "dongguan_lb39_excluded"
    assert jiashan.amount == 25


def test_fixed_area_rules_and_jinjiang_exclusions_are_auditable():
    engine = YeBanBuTieEngine()
    config = {
        "shift_breaks": [{"shift_code": "JJ01", "break_periods": ["00:00-01:00"]}],
        "jinjiang_exclusions": [{
            "employee_id": "JJ003", "employee_name": "特殊员工", "reason": "轻松岗位",
            "start_date": "2026-05-01", "end_date": "",
        }],
        "jinjiang_list_confirmed": True,
    }

    normal = engine.calculate(
        {"工号": "JJ001", "姓名": "正常员工", "工作地区": "晋江", "岗位名称": "操作员"},
        [_day("22:00", "08:00", shift="JJ01", 工号="JJ001")],
        config=config,
    )
    piecework = engine.calculate(
        {"工号": "JJ002", "姓名": "计件员工", "工作地区": "晋江", "岗位名称": "操作员"},
        [_day("22:00", "08:00", shift="JJ01", 工号="JJ002", 计时="计件")],
        config=config,
    )
    special = engine.calculate(
        {"工号": "JJ003", "姓名": "特殊员工", "工作地区": "晋江", "岗位名称": "操作员"},
        [_day("22:00", "08:00", shift="JJ01", 工号="JJ003")],
        config=config,
    )
    gatekeeper = engine.calculate(
        {"工号": "JJ004", "姓名": "门禁员工", "工作地区": "晋江", "岗位名称": "门禁"},
        [_day("22:00", "08:00", shift="JJ01", 工号="JJ004")],
        config=config,
    )

    assert normal.amount == 25
    assert normal.details["calculated_days"] == 1
    assert piecework.amount == 0
    assert piecework.details["excluded_days"] == 1
    assert piecework.details["daily_results"][0]["reason_code"] == "jinjiang_piecework_excluded"
    assert special.amount == 0
    assert special.details["daily_results"][0]["reason_code"] == "jinjiang_special_list_excluded"
    assert gatekeeper.amount == 0
    assert gatekeeper.details["daily_results"][0]["reason_code"] == "jinjiang_gatekeeper_excluded"


def test_jiashan_and_yiwu_do_not_require_position_configuration():
    engine = YeBanBuTieEngine()
    config = {
        "shift_breaks": [{"shift_code": "HD01", "break_periods": []}],
        "jinjiang_exclusions": [],
        "jinjiang_list_confirmed": True,
    }

    jiashan = engine.calculate(
        {"工号": "HD001", "姓名": "嘉善员工", "工作地区": "嘉善", "岗位名称": "任意岗位"},
        [_day("22:00", "08:00", shift="HD01")],
        config=config,
    )
    yiwu = engine.calculate(
        {"工号": "HD002", "姓名": "义乌员工", "工作地区": "义乌", "岗位名称": "新岗位"},
        [_day("22:00", "08:00", shift="HD01", 工号="HD002")],
        config=config,
    )

    assert jiashan.amount == 25
    assert yiwu.amount == 25
    assert jiashan.details["pending_rule_days"] == 0
    assert yiwu.details["pending_rule_days"] == 0


@pytest.mark.parametrize("work_area", ["嘉善", "义乌"])
@pytest.mark.parametrize("position", ["保洁", "HRBP专员", "数据专员"])
def test_jiashan_yiwu_confirmed_positions_are_excluded(work_area, position):
    result = YeBanBuTieEngine().calculate(
        {
            "工号": "HD001",
            "姓名": "华东员工",
            "工作地区": work_area,
            "岗位名称": position,
        },
        [_day("22:00", "08:00", shift="HD01")],
        config={
            "shift_breaks": [{"shift_code": "HD01", "break_periods": []}],
            "jinjiang_exclusions": [],
            "jinjiang_list_confirmed": True,
        },
    )

    assert result.amount == 0
    assert result.details["excluded_days"] == 1
    assert result.details["daily_results"][0]["reason_code"] == "jiashan_yiwu_position_excluded"
    assert "命中嘉善/义乌固定排除岗位或东莞LB39班次时为0元" in (
        result.details["audit_explanation"]["formula"]
    )


def test_missing_shift_and_unconfirmed_jinjiang_list_calculate_provisionally():
    engine = YeBanBuTieEngine()
    config = {
        "shift_breaks": [{"shift_code": "JJ01", "break_periods": []}],
        "jinjiang_exclusions": [],
        "jinjiang_list_confirmed": False,
    }

    unconfirmed = engine.calculate(
        {"工号": "JJ001", "姓名": "晋江员工", "工作地区": "晋江", "岗位名称": "操作员"},
        [_day("22:00", "08:00", shift="JJ01", 工号="JJ001")],
        config=config,
    )
    missing_shift = engine.calculate(
        {"工号": "HD001", "姓名": "嘉善员工", "工作地区": "嘉善", "岗位名称": "操作员"},
        [_day("22:00", "08:00", shift="HD99", 工号="HD001")],
        config=config,
    )

    assert unconfirmed.details["daily_results"][0]["reason_code"] == "jinjiang_special_list_unconfirmed"
    assert missing_shift.details["daily_results"][0]["reason_code"] == "shift_break_config_missing"
    assert unconfirmed.details["daily_results"][0]["status"] == "calculated_pending"
    assert missing_shift.details["daily_results"][0]["status"] == "calculated_pending"
    assert unconfirmed.amount == 25.0
    assert missing_shift.amount == 25.0
    assert unconfirmed.details["pending_rule_days"] == 1
    assert missing_shift.details["pending_rule_days"] == 1
    assert unconfirmed.details["review_calculated_days"] == 1
    assert missing_shift.details["review_calculated_days"] == 1


def test_new_shift_configuration_applies_from_selected_effective_date():
    result = YeBanBuTieEngine().calculate(
        {"工号": "HD001", "姓名": "嘉善员工", "工作地区": "嘉善", "岗位名称": "操作员"},
        [
            _day("22:00", "08:00", shift="HD99", 出勤日期="2026-08-14", 班次名称="新增夜班", 班次时间段="22:00-08:00"),
            _day("22:00", "08:00", shift="HD99", 出勤日期="2026-08-15", 班次名称="新增夜班", 班次时间段="22:00-08:00"),
        ],
        config={
            "shift_breaks": [{
                "shift_code": "HD99",
                "effective_start_date": "2026-08-15",
                "break_segments": [{"period": "23:00-24:00", "category": "晚上休息"}],
            }],
            "jinjiang_exclusions": [],
            "jinjiang_list_confirmed": True,
        },
    )

    first, second = result.details["daily_results"]
    assert first["reason_code"] == "shift_break_config_missing"
    assert second["reason_code"] == "generic_rule"
    assert second["break_minutes"] == 60
    assert second["shift_name"] == "新增夜班"
    assert second["shift_time"] == "22:00-08:00"


def test_missing_shift_gate_only_blocks_payable_days_and_checks_effective_date():
    from bonus_platform.engine.domestic_labor.engines.yeban_butie import find_missing_payable_shifts
    config = {"shift_breaks": [], "jinjiang_list_confirmed": True}
    employees = [{"工号": "A", "工作地区": "嘉善", "岗位名称": "操作员"},
                 {"工号": "B", "工作地区": "晋江", "岗位名称": "门禁"}]
    days = {"A": [_day("20:00", "08:00", shift="NEW", 出勤日期="2026-07-02"),
                  _day(None, "08:00", shift="MISSING"), _day("09:00", "18:00", shift="DAY")],
            "B": [_day("20:00", "08:00", shift="GATE")]}
    blocked = find_missing_payable_shifts(employees, days, config)
    assert len(blocked) == 1
    pending = blocked[0]["subject_details"]["yeban_butie"]["details"]["daily_results"]
    assert [row["shift_code"] for row in pending] == ["NEW"]
    assert "amount" not in pending[0]
    config["shift_breaks"] = [{"shift_code": "NEW", "break_segments": [], "effective_start_date": "2026-07-03"}]
    assert find_missing_payable_shifts(employees, days, config)
    config["shift_breaks"][0]["effective_start_date"] = "2026-07-02"
    assert find_missing_payable_shifts(employees, days, config) == []


@pytest.mark.parametrize('auto,listed,expected', [(True,False,0),(False,True,0),(True,True,0),(False,False,25)])
def test_jinjiang_auto_and_uploaded_roster_form_union(auto, listed, expected):
    config = {'shift_breaks': [{'shift_code':'JJ01','break_periods':[]}],
              'jinjiang_list_confirmed':True,
              'jinjiang_exclusions': ([{'employee_id':'TEST001','reason':'计件岗','start_date':'2026-07-01','end_date':'2026-07-31'}] if listed else [])}
    result = YeBanBuTieEngine().calculate(
        {'工号':'TEST001','工作地区':'晋江','岗位名称':'操作员'},
        [_day('22:00','08:00',shift='JJ01',出勤日期='2026-07-02',计时='计件' if auto else '')], config=config)
    assert result.amount == expected
    assert result.details['excluded_days'] == (1 if auto or listed else 0)
    assert result.warnings == []
    assert len(result.details['daily_results']) == 1


def test_jinjiang_roster_does_not_exclude_outside_effective_dates():
    config = {'shift_breaks':[{'shift_code':'JJ01','break_periods':[]}], 'jinjiang_list_confirmed':True,
              'jinjiang_exclusions':[{'employee_id':'TEST001','reason':'计件岗','start_date':'2026-07-02','end_date':'2026-07-02'}]}
    result = YeBanBuTieEngine().calculate(
        {'工号':'TEST001','工作地区':'晋江','岗位名称':'操作员'},
        [_day('22:00','08:00',shift='JJ01',出勤日期=date) for date in ['2026-07-01','2026-07-02','2026-07-03']], config=config)
    assert result.amount == 50
    assert result.details['excluded_days'] == 1
    assert result.warnings == []
