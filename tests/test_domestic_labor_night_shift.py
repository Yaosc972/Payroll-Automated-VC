from datetime import time
import json

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


def test_generic_night_shift_keeps_unrounded_daily_amount():
    result = YeBanBuTieEngine().calculate_day(
        _day("22:14", "01:44"),
        break_periods=["00:10-00:30"],
    )

    assert result.status == "calculated"
    assert result.night_minutes == 180
    assert result.break_minutes == 20
    assert result.amount == 8.0


def test_post_midnight_start_is_treated_as_previous_nights_second_half():
    result = YeBanBuTieEngine().calculate_day(
        _day("00:50", "09:07", shift="HD024"),
        break_periods=["06:00-06:30"],
    )

    assert result.status == "calculated"
    assert result.amount == 19.5
    assert result.night_minutes == 7 * 60
    assert result.break_minutes == 30


def test_partial_break_overlap_is_sent_to_manual_review():
    result = YeBanBuTieEngine().calculate_day(
        _day("00:50", "06:45", shift="HD999"),
        break_periods=["06:00-07:00"],
    )

    assert result.status == "calculated_review"
    assert result.reason_code == "partial_break_overlap"
    assert result.amount == 15.0


def test_daytime_is_excluded_missing_punch_is_unpriced_and_implausible_is_provisional():
    engine = YeBanBuTieEngine()

    daytime = engine.calculate_day(_day("08:30", "17:30"))
    missing = engine.calculate_day(_day(None, "08:00"))
    implausible = engine.calculate_day(_day("10:00", "09:00"))

    assert (daytime.status, daytime.reason_code, daytime.amount) == (
        "excluded",
        "no_night_overlap",
        0.0,
    )
    assert (missing.status, missing.reason_code) == ("manual_review", "missing_punch")
    assert missing.amount is None
    assert (implausible.status, implausible.reason_code, implausible.amount) == (
        "calculated_review",
        "implausible_duration",
        25.0,
    )


def test_missing_punch_only_requires_review_for_a_scheduled_night_shift():
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
        "manual_review",
        "missing_punch",
        None,
    )


def test_three_am_shift_is_provisionally_calculated_and_left_for_review():
    result = YeBanBuTieEngine().calculate_day(_day("03:14", "14:49", shift="LB15"))

    assert result.status == "calculated_review"
    assert result.reason_code == "three_am_shift_pending"
    assert result.amount == 25.0


def test_three_am_short_shift_uses_confirmed_eight_hour_proportional_formula():
    result = YeBanBuTieEngine().calculate_day(_day("03:14", "09:49", shift="LB15"))

    assert result.status == "calculated_review"
    assert result.reason_code == "three_am_shift_pending"
    assert result.amount == 18.75


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

    assert result.amount == 33.0
    assert result.details["calculated_days"] == 2
    assert result.details["excluded_days"] == 1
    assert result.details["manual_review_days"] == 1
    assert result.details["review_calculated_days"] == 0
    assert result.details["unpriced_review_days"] == 1
    assert len(result.details["daily_results"]) == 4
    assert result.warnings == ["1条日考勤需人工复核"]


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
