"""Beisen meal-source mapping and completeness checks, without live API calls."""
from datetime import date
from types import SimpleNamespace

import pytest

from bonus_platform.engine.china_employee_payroll import meal_beisen
from bonus_platform.engine.china_employee_payroll.meal_allowance import ParsedAttendance, REQUIRED_COLUMNS, calculate_meal_allowance
from bonus_platform.engine.china_employee_payroll.relocation import RelocationError


MONTH = "2026-09"
DATE_TYPES = {"0": "工作日", "1": "休息日", "2": "节假日"}
SHIFTS = {"101": "深圳灵活打卡8:30-9:10", "102": "普通朝九晚六"}


def organization(oid=1, second="HQU技术部", third="技术部"):
    return {"oId": oid, "name": third, "startDate": "2020-01-01", "stopDate": "9999-12-31",
            "translateProperties": {"SecondLevelOrganizationText": second, "ThirdLevelOrganizationText": third,
                                    "FourthLevelOrganizationText": "研发组", "FifthLevelOrganizationText": ""}}


def attendance(sid=1001, day=1, **changes):
    return {"UserId": sid, "StaffId": sid, "SwipingCardDate": f"2026-09-{day:02}",
            "FirstCardIncludeFillCheck": f"2026-09-{day:02}T09:10:00",
            "LastCardIncludeFillCheck": f"2026-09-{day:02}T21:05:00", "OIdWorkShift": 101,
            "DateType": 0, "RetroactiveRemark": "", "AttendanceOrgId": 1, **changes}


def normalize(records, organizations=None, staff=None):
    return meal_beisen.normalize_attendance(records, MONTH,
        staff or {1001: {"jobNumber": "zt1001", "name": "测试员工", "status": "在职"}},
        organizations or {1: organization()}, SHIFTS, DATE_TYPES)


def bare_source():
    source = object.__new__(meal_beisen.BeisenMealSource)
    source.key = "test-key"
    source.secret = "test-secret"
    source.token = "test-token"
    source.closed = False
    source.client = SimpleNamespace(close=lambda: setattr(source, "closed", True))
    return source


def monthly_scope(employee_count=1):
    return {
        "attendance": [{"Month": MONTH + "-01", "StaffId": sid, "EmpRecordOID": sid + 10000, "AttendanceOrg": 1}
                       for sid in range(1001, 1001 + employee_count)],
        "services": [{"objectId": sid + 10000, "userID": sid, "jobNumber": f"zt{sid}", "oIdDepartment": 1,
                      "startDate": "2020-01-01", "stopDate": "9999-12-31", "entryDate": "2020-01-01",
                      "translateProperties": {"EmployeeStatusText": "在职"}}
                     for sid in range(1001, 1001 + employee_count)],
        "people": [{"userID": sid, "name": f"测试员工{sid}"} for sid in range(1001, 1001 + employee_count)],
        "organizations": [organization()],
    }


def configured_source(monkeypatch, responder, scope=None):
    source = bare_source()
    source._shifts = lambda: SHIFTS
    source._date_types = lambda: DATE_TYPES
    source.requests = []

    def request(path, body, authenticate=False):
        source.requests.append((path, body))
        if path == "/token":
            return {"access_token": "test-token"}
        assert path == meal_beisen.ATTENDANCE_PATH
        items, total = responder(body)
        return {"Data": {"Items": items, "TotalCount": total}}

    source.request = request
    monkeypatch.setattr(meal_beisen, "_MonthlyScope", lambda: SimpleNamespace(load=lambda month, progress: scope or monthly_scope()))
    return source


def test_normalized_rows_preserve_source_punches_and_match_existing_meal_rules():
    records = [attendance(day=1),
               attendance(day=2, LastCardIncludeFillCheck="2026-09-02T20:59:00"),
               attendance(day=3, LastCardIncludeFillCheck="2026-09-04T00:10:00"),
               attendance(day=4, LastCardIncludeFillCheck="2026-09-04T09:00:00", RetroactiveRemark="公出 08:30-22:00[已通过]"),
               attendance(day=5, DateType=1),
               attendance(day=6, OIdWorkShift=102)]
    rows = normalize(records)
    assert rows[0]["考勤日期"] == date(2026, 9, 1)
    assert rows[2]["末打卡(含补签)"] == "2026-09-04T00:10:00"
    assert rows[0]["首打卡(含补签)"] == records[0]["FirstCardIncludeFillCheck"]
    assert rows[3]["备注"] == records[3]["RetroactiveRemark"]
    assert set(rows[0]) == set(REQUIRED_COLUMNS)
    result = calculate_meal_allowance(ParsedAttendance(rows, [], REQUIRED_COLUMNS, []))
    assert result["summary"]["payableDayCount"] == 3
    assert result["summary"]["totalAmount"] == 60
    assert [row["payable"] for row in result["dailyRows"]] == [True, False, True, True, False, False]


def test_daily_organization_controls_scope_and_case_insensitive_fields():
    records = [attendance(), attendance(day=2, AttendanceOrgId=2)]
    organizations = {1: organization(), 2: organization(2, "ABU航空事业部", "客服部")}
    rows = normalize([{key.lower(): value for key, value in row.items()} for row in records], organizations)
    assert len(rows) == 1
    assert rows[0]["二级组织"] == "HQU技术部"


@pytest.mark.parametrize("change,reason", [
    ({"StaffId": 999, "UserId": 999}, "范围外"),
    ({"SwipingCardDate": "2026-08-31"}, "日期"),
    ({"SwipingCardDate": "not-a-date"}, "日期"),
    ({"AttendanceOrgId": 404}, "组织"),
    ({"DateType": 404}, "日期类型"),
    ({"OIdWorkShift": 404}, "班次"),
    ({"OIdWorkShift": None}, "班次"),
])
def test_normalization_rejects_unknown_or_mismatched_fields(change, reason):
    with pytest.raises(RelocationError, match=reason):
        normalize([attendance(**change)])


def test_missing_columns_and_duplicate_employee_dates_fail_before_calculation():
    record = attendance()
    del record["DateType"]
    with pytest.raises(RelocationError, match="缺少核算字段"):
        normalize([record])
    with pytest.raises(RelocationError, match="重复"):
        normalize([attendance(), attendance()])


@pytest.mark.parametrize("field", ["FirstCardIncludeFillCheck", "LastCardIncludeFillCheck"])
def test_invalid_nonempty_punch_does_not_silently_become_zero_allowance(field):
    with pytest.raises(RelocationError, match="打卡"):
        normalize([attendance(**{field: "invalid-punch"})])


def test_empty_punches_are_valid_missing_punch_records():
    row = normalize([attendance(FirstCardIncludeFillCheck=None, LastCardIncludeFillCheck=None)])[0]
    result = calculate_meal_allowance(ParsedAttendance([row], [], REQUIRED_COLUMNS, []))
    assert result["summary"]["totalAmount"] == 0


def test_omitted_null_punches_and_remarks_match_empty_excel_cells():
    record = attendance(StaffId="1001", AttendanceOrgId="1")
    for key in ("FirstCardIncludeFillCheck", "LastCardIncludeFillCheck", "RetroactiveRemark"):
        record.pop(key)
    row = normalize([record])[0]
    assert row["首打卡(含补签)"] is None and row["备注"] == ""
    result = calculate_meal_allowance(ParsedAttendance([row], [], REQUIRED_COLUMNS, []))
    assert result["summary"]["totalAmount"] == 0


def test_missing_org_translations_cannot_silently_exclude_employee():
    org = organization()
    org.pop("translateProperties")
    with pytest.raises(RelocationError, match="组织"):
        normalize([attendance()], {1: org})


def test_hras_special_team_requires_fourth_level_translation():
    org = organization(1, "HRAS人力综合条线", "HSSC人力共享中心")
    org["translateProperties"].pop("FourthLevelOrganizationText")
    with pytest.raises(RelocationError, match="组织"):
        normalize([attendance()], {1: org})


def test_parent_organization_without_deeper_levels_is_valid_but_not_eligible():
    org = organization(1, "HRAS人力综合条线", "HSSC人力共享中心")
    org.update(thirdLevelOrganization=1, fourthLevelOrganization=None)
    org["translateProperties"].pop("FourthLevelOrganizationText")
    assert normalize([attendance()], {1: org}) == []
    org.update(secondLevelOrganization=1, thirdLevelOrganization=None)
    org["translateProperties"].pop("ThirdLevelOrganizationText")
    assert normalize([attendance()], {1: org}) == []


@pytest.mark.parametrize("replies,reason", [
    ([{"Data": {"WorkShiftInfos": [], "Total": 1}}], "分页不完整"),
    ([{"Data": {"WorkShiftInfos": [{"OId": 101, "Name": "A"}], "Total": 2}},
      {"Data": {"WorkShiftInfos": [{"OId": 102, "Name": "B"}], "Total": 3}}], "发生变化"),
    ([{"Data": {"WorkShiftInfos": [{"OId": 101, "Name": "A"}, {"OId": 101, "Name": "B"}], "Total": 2}}], "重复"),
    ([{"Data": {"WorkShiftInfos": [{"OId": 101}], "Total": 1}}], "不完整"),
])
def test_shift_pagination_is_complete_and_unambiguous(replies, reason):
    source = bare_source()
    replies = iter(replies)
    source.request = lambda path, body: next(replies)
    with pytest.raises(RelocationError, match=reason):
        source._shifts()


def test_date_types_come_from_named_options_instead_of_assumed_numbers():
    source = bare_source()
    calls = []
    def request(path, body):
        calls.append((path, body))
        return {"data": [{"dataSourceResults": [{"value": 7, "text": "工作日"}, {"value": 9, "text": "节假日"}]}]}
    source.request = request
    assert source._date_types() == {"7": "工作日", "9": "节假日"}
    assert calls[0][1]["listFilter"] == [{"dsName": "Attendance.DateType", "fieldName": "DateType"}]


@pytest.mark.parametrize("options", [
    [{"value": 7, "text": "工作日"}, {"value": 7, "text": "休息日"}, {"value": 8, "text": "工作日"}],
    [{"value": 7, "text": "工作日"}, {"text": "节假日"}],
])
def test_ambiguous_or_incomplete_date_type_options_are_rejected(options):
    source = bare_source()
    source.request = lambda path, body: {"data": [{"dataSourceResults": options}]}
    with pytest.raises(RelocationError, match="日期类型"):
        source._date_types()


def test_monthly_scope_joins_service_object_id_then_verifies_user_id(monkeypatch):
    scope = monthly_scope(2)
    # A non-technical monthly row is not included in the daily request.
    scope["organizations"].append(organization(2, "ABU航空事业部", "客服部"))
    scope["attendance"][1]["AttendanceOrg"] = 2
    scope["services"][1]["oIdDepartment"] = 2
    source = configured_source(monkeypatch, lambda body: ([attendance()], 1), scope)
    updates = []
    parsed = source.load(MONTH, updates.append)
    request = source.requests[-1][1]
    assert request["userIds"] == [1001]
    assert request["startDate"] == "2026-09-01" and request["stopDate"] == "2026-09-30"
    assert request["searchColumns"] == meal_beisen.COLUMNS
    assert parsed.rows[0]["工号"] == "zt1001"
    assert parsed.source_type == "hr" and parsed.missing_columns == []
    assert any(update["stage"] == 1 and update["completed"] == 1 and update["total"] == 1 for update in updates)
    assert source.closed and not source.key and not source.secret and not source.token


def test_mismatched_monthly_service_identity_is_not_used(monkeypatch):
    scope = monthly_scope()
    scope["services"][0]["userID"] = 999
    source = configured_source(monkeypatch, lambda body: ([attendance()], 1), scope)
    with pytest.raises(RelocationError, match="任职关联"):
        source.load(MONTH)
    assert source.closed
    assert all(path != meal_beisen.ATTENDANCE_PATH for path, body in source.requests)


def test_monthly_scope_must_belong_to_requested_month(monkeypatch):
    scope = monthly_scope()
    scope["attendance"][0]["Month"] = "2026-08-01"
    source = configured_source(monkeypatch, lambda body: ([attendance()], 1), scope)
    with pytest.raises(RelocationError, match="月份"):
        source.load(MONTH)


def test_live_monthly_string_org_id_links_to_numeric_org_and_daily_id(monkeypatch):
    scope = monthly_scope()
    scope["attendance"][0]["AttendanceOrg"] = "1"
    scope["attendance"][0]["EmpRecordOID"] = "record-1"
    scope["services"][0]["objectId"] = "record-1"
    source = configured_source(monkeypatch, lambda body: ([attendance()], 1), scope)
    parsed = source.load(MONTH)
    assert calculate_meal_allowance(parsed)["summary"]["totalAmount"] == 20


def test_employee_transferred_out_midmonth_remains_in_daily_candidate_pool(monkeypatch):
    scope = monthly_scope()
    scope["organizations"].append(organization(2, "ABU航空事业部", "客服部"))
    scope["attendance"][0]["AttendanceOrg"] = 2
    scope["services"][0]["oIdDepartment"] = 2
    scope["services"][0]["startDate"] = "2026-09-16"
    scope["services"].append({**scope["services"][0], "objectId": 21001, "oIdDepartment": 1,
                              "startDate": "2020-01-01", "stopDate": "2026-09-15"})
    source = configured_source(monkeypatch, lambda body: ([attendance(day=1), attendance(day=20, AttendanceOrgId=2)], 2), scope)
    parsed = source.load(MONTH)
    assert source.requests[-1][1]["userIds"] == [1001]
    assert len(parsed.rows) == 1
    assert parsed.rows[0]["考勤日期"] == date(2026, 9, 1)
    assert calculate_meal_allowance(parsed)["summary"]["totalAmount"] == 20


def test_unresolved_overlapping_history_org_cannot_silently_drop_employee(monkeypatch):
    scope = monthly_scope(2)
    scope["organizations"].append(organization(2, "ABU航空事业部", "客服部"))
    scope["attendance"][1]["AttendanceOrg"] = 2
    scope["services"][1]["oIdDepartment"] = 2
    scope["services"][1]["startDate"] = "2026-09-16"
    scope["services"].append({**scope["services"][1], "objectId": 21002, "oIdDepartment": 999,
                              "startDate": "2020-01-01", "stopDate": "2026-09-15"})
    source = configured_source(monkeypatch, lambda body: ([attendance()], 1), scope)
    with pytest.raises(RelocationError, match="组织"):
        source.load(MONTH)


@pytest.mark.parametrize("second_total,second_rows,reason", [
    (102, 2, "发生变化"),
    (101, 0, "完整"),
])
def test_daily_pagination_rejects_total_changes_or_missing_rows(monkeypatch, second_total, second_rows, reason):
    def responder(body):
        if body["pageIndex"] == 1:
            return [attendance(sid, day) for sid in range(1001, 1005) for day in range(1, 26)], 101
        return [attendance(1005, day) for day in range(1, second_rows + 1)], second_total
    source = configured_source(monkeypatch, responder, monthly_scope(5))
    with pytest.raises(RelocationError, match=reason):
        source.load(MONTH)
    assert source.closed


def test_daily_batches_cannot_compensate_for_each_others_missing_rows(monkeypatch):
    def responder(body):
        # Globally 2 rows / 2 total, but one batch supplied 2 / 1 and the other 0 / 1.
        if body["userIds"][0] == 1001:
            return [attendance(1001, 1), attendance(1002, 1)], 1
        return [], 1
    source = configured_source(monkeypatch, responder, monthly_scope(101))
    with pytest.raises(RelocationError, match="完整|总量|批次"):
        source.load(MONTH)


def test_daily_response_cannot_contain_employee_from_another_requested_batch(monkeypatch):
    def responder(body):
        return [attendance(1101 if body["userIds"][0] == 1001 else 1001)], 1
    source = configured_source(monkeypatch, responder, monthly_scope(101))
    with pytest.raises(RelocationError, match="范围|批次"):
        source.load(MONTH)
