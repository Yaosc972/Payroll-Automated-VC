"""全勤奖分档迟到豁免规则回归。"""
from datetime import date
from io import BytesIO

import pytest
from openpyxl import Workbook
from fastapi.testclient import TestClient

from bonus_platform.app import app
from bonus_platform.engine.domestic_labor.engines.quanqinjiang import QuanQinJiangEngine


pytestmark = pytest.mark.usefixtures("bypass_domestic_labor_access_gate")


def _employee(**fields):
    return {
        "工号": "OWHN001",
        "姓名": "张三",
        "考勤月份": "202608",
        "入职日期": date(2023, 1, 1),
        "最后工作日": None,
        "旷工天数": 0,
        "正班迟到次数": 0,
        "早退次数": 0,
        "签卡次数": 0,
        "工伤假天数": 0,
        "事假时数": 0,
        "病假时数": 0,
        "入离职缺勤时数": 0,
        "迟到早退30分钟内扣款": 0,
        "迟到6分钟内(次)": 0,
        "迟到6-20分钟内(次)": 0,
        "迟到20-30分钟内(次)": 0,
        **fields,
    }


@pytest.mark.parametrize(
    "lateness_fields",
    [
        {},
        {"迟到6分钟内(次)": 1, "正班迟到次数": 1},
        {"迟到6分钟内(次)": 3, "正班迟到次数": 3},
        {"迟到6-20分钟内(次)": 1, "正班迟到次数": 1},
    ],
)
def test_attendance_bonus_allows_only_one_lateness_exemption_path(lateness_fields):
    result = QuanQinJiangEngine().calculate(_employee(**lateness_fields))

    assert result.amount == 100


@pytest.mark.parametrize(
    ("lateness_fields", "expected_reason"),
    [
        ({"迟到6分钟内(次)": 4, "正班迟到次数": 4}, "6分钟内迟到超过3次"),
        ({"迟到6-20分钟内(次)": 2, "正班迟到次数": 2}, "6-20分钟迟到超过1次"),
        (
            {"迟到6分钟内(次)": 2, "迟到6-20分钟内(次)": 1, "正班迟到次数": 3},
            "两档迟到混合出现",
        ),
        ({"迟到20-30分钟内(次)": 1, "正班迟到次数": 1}, "存在20-30分钟迟到"),
    ],
)
def test_attendance_bonus_rejects_exceeded_or_mixed_lateness(lateness_fields, expected_reason):
    result = QuanQinJiangEngine().calculate(_employee(**lateness_fields))

    assert result.amount == 0
    assert result.details["reason"] == "迟到豁免不符合"
    explanation = result.details["audit_explanation"]
    assert expected_reason in explanation["intermediate_values"]["迟到豁免判断"]
    assert explanation["intermediate_values"]["迟到6分钟内次数"] == lateness_fields.get("迟到6分钟内(次)", 0)
    assert explanation["intermediate_values"]["迟到6-20分钟次数"] == lateness_fields.get("迟到6-20分钟内(次)", 0)


def test_attendance_bonus_accepts_legacy_under_six_minute_header_alias():
    employee = _employee(**{"迟到6分钟内(次)": 0})
    employee.pop("迟到6分钟内(次)")
    employee["迟到6分钟内"] = 3
    employee["正班迟到次数"] = 3

    result = QuanQinJiangEngine().calculate(employee)

    assert result.amount == 100


def test_attendance_bonus_supports_production_style_wrapped_lateness_headers():
    employee = _employee(**{
        "迟到6分钟内(次)": 0,
        "迟到6-20分钟内(次)": 0,
        "迟到≤6分钟内\n（次）": 2,
        "迟到6-20分钟内\n（次）": 1,
        "正班迟到次数": 3,
    })
    employee.pop("迟到6分钟内(次)")
    employee.pop("迟到6-20分钟内(次)")

    result = QuanQinJiangEngine().calculate(employee)

    assert result.amount == 0
    assert "两档迟到混合出现" in result.details["audit_explanation"]["intermediate_values"]["迟到豁免判断"]


def test_attendance_bonus_api_applies_mutually_exclusive_lateness_rule():
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "月考勤"
    headers = [
        "工号", "姓名", "考勤月份", "入职日期", "最后工作日", "旷工天数", "正班迟到次数",
        "迟到≤6分钟内\n（次）", "迟到6-20分钟内\n（次）", "迟到20-30分钟内\n（次）", "早退次数",
        "签卡次数", "工伤假天数", "事假时数", "病假时数", "入离职缺勤时数", "迟到早退30分钟内扣款",
    ]
    sheet.append(headers)
    sheet.append([
        "OWHN0079", "张清泉", "202608", "2023-01-01", None, 0, 3,
        2, 1, 0, 0, 0, 0, 0, 0, 0, 0,
    ])
    stream = BytesIO()
    workbook.save(stream)

    client = TestClient(app)
    response = client.post(
        "/api/domestic-labor/runs",
        files={"file": ("全勤奖迟到混用.xlsx", stream.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"engines": "quanqinjiang", "attendance_month": "202608"},
    )
    assert response.status_code == 200
    run_id = response.json()["run_id"]
    try:
        for _ in range(30):
            metadata = client.get(f"/api/domestic-labor/runs/{run_id}").json()
            if metadata["status"] in {"已完成", "失败"}:
                break
            import time
            time.sleep(0.1)

        assert metadata["status"] == "已完成"
        assert metadata["results"][0]["quanqinjiang"] == 0
        detail = metadata["results"][0]["subject_details"]["quanqinjiang"]["details"]
        assert detail["reason"] == "迟到豁免不符合"
        assert "两档迟到混合出现" in detail["audit_explanation"]["intermediate_values"]["迟到豁免判断"]
    finally:
        client.delete(f"/api/domestic-labor/runs/{run_id}")
