"""Dongguan housing allowance uses the confirmed position table, regardless of grade."""
from datetime import date

import pytest

from bonus_platform.engine.domestic_labor.engines.waisu_butie import WaiSuBuTieEngine
from bonus_platform.engine.domestic_labor.rule_package import get_rule_package


ELIGIBLE = [
    "安检副主管", "安检员", "安检组长", "操作文员", "操作员", "操作主管", "操作组长",
    "叉车司机", "查验员", "稽查副主管", "稽查组长", "监察员", "理货员",
    "民航初级安检员", "民航中级安检员", "民航高级安检员",
    "内部初级安检员", "内部中级安检员", "内部高级安检员",
    "实习生", "文员", "物流专员", "揽收充电司机",
]
INELIGIBLE = ["HRBP主管", "HRBP专员", "保洁", "高级招聘专员", "人事专员", "行政专员", "招聘专员", "质量监控专员"]


def calculate(position, *, name="测试员工", grade="", area="东莞"):
    employee = {
        "工号": "TEST001", "姓名": name, "工作地区": area, "岗位名称": position,
        "职级": grade, "考勤月份": "202609", "入职日期": date(2024, 1, 1),
        "排班天数": 22, "实际在职工作日天数": 22, "正班出勤天数": 22,
    }
    daily = [{"工号": "TEST001", "工作地区": area, "出勤日期": date(2026, 9, 1),
              "上班一": "09:00", "下班一": "18:00"}]
    return WaiSuBuTieEngine().calculate(employee, daily, housing_records=[])


@pytest.mark.parametrize("position", ELIGIBLE)
@pytest.mark.parametrize("grade", ["", "P1-1", "M2-2"])
def test_dongguan_housing_position_table_pays_regardless_of_grade(position, grade):
    assert calculate(position, grade=grade).amount == 150


@pytest.mark.parametrize("position", INELIGIBLE)
@pytest.mark.parametrize("name", ["测试员工", "陈西莎", "田盈"])
def test_dongguan_housing_position_table_has_no_name_exceptions(position, name):
    result = calculate(position, name=name, grade="M2-2")
    assert result.amount == 0
    assert result.details["audit_explanation"]["intermediate_values"]["岗位是否明确不享有"]


@pytest.mark.parametrize("position", ["高级HRBP专员", "未知岗位", "操作员助理", ""])
def test_dongguan_housing_unlisted_positions_are_not_eligible(position):
    assert calculate(position, name="陈西莎").amount == 0


@pytest.mark.parametrize("area", ["嘉善", "义乌"])
def test_dongguan_housing_table_does_not_restrict_other_regions(area):
    assert calculate("HRBP主管", area=area).amount == 150


def test_dongguan_housing_rules_publish_full_table_and_preserve_previous_version():
    package = get_rule_package()
    subject = next(s for s in package["subjects"] if s["id"] == "waisu_butie")
    region = next(r for r in subject["regions"] if r["name"] == "东莞")
    assert package["version"] == "1.4.13"
    assert subject["version"] == "DL-WAISU.v1.0.8"
    assert set(region["eligible_positions"]) == set(ELIGIBLE)
    assert set(region["ineligible_positions"]) == set(INELIGIBLE)
    assert "忽略职级" in region["rule"]
    assert "陈西莎、田盈按已确认特殊名单享有" not in str(subject)
    previous = get_rule_package("1.4.12")
    old_subject = next(s for s in previous["subjects"] if s["id"] == "waisu_butie")
    assert old_subject["version"] == "DL-WAISU.v1.0.7"
    assert "陈西莎、田盈按已确认特殊名单享有" in str(old_subject)
