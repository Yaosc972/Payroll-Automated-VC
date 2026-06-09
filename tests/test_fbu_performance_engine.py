from bonus_platform.engine.fbu_performance.engines.base import EmployeeData
from bonus_platform.engine.fbu_performance.engines.bonus import BonusCalculator
from bonus_platform.engine.fbu_performance.engines.coefficient import CoefficientCalculator
from bonus_platform.engine.fbu_performance.engines.salary import SalaryProcessor
from bonus_platform.engine.fbu_performance.parser import FBUPerformanceParser


def test_warehouse_coefficient_boundaries():
    assert CoefficientCalculator.calc_warehouse_coefficient(None) == 0
    assert CoefficientCalculator.calc_warehouse_coefficient(60) == 0
    assert CoefficientCalculator.calc_warehouse_coefficient(76) == 0.8
    assert CoefficientCalculator.calc_warehouse_coefficient(95) == 1
    assert CoefficientCalculator.calc_warehouse_coefficient(110) == 1.3
    assert CoefficientCalculator.calc_warehouse_coefficient(125) == 1.6
    assert CoefficientCalculator.calc_warehouse_coefficient(130) == 1.6


def test_functional_coefficient_normalizes_level_text():
    assert CoefficientCalculator.calc_functional_coefficient(" 符合预期+ ") == 1.2
    assert CoefficientCalculator.calc_functional_coefficient("未知等级") == 0


def test_bonus_formula_uses_performance_base_ratio_and_calculated_coefficient():
    emp = EmployeeData(
        employee_id="E001",
        name="Ana",
        hourly_rate=20,
        performance_ratio=0.1,
        performance_score=110,
        base_hours=160,
        ot15_hours=10,
        ot20_hours=5,
        sick_hours=8,
        annual_hours=8,
        holiday_hours=4,
    )

    BonusCalculator.calculate(emp)

    assert emp.performance_base == 20 * (160 + 10 * 1.5 + 5 * 2 + 8 + 8 + 4)
    assert emp.performance_coefficient == 1.3
    assert emp.performance_bonus == emp.performance_base * 0.1 * 1.3


def test_uploaded_coefficient_is_preserved_for_audit_but_formula_is_authoritative():
    emp = EmployeeData(
        employee_id="E002",
        name="Ben",
        hourly_rate=10,
        performance_ratio=0.2,
        performance_score=95,
        uploaded_coefficient=1.6,
        base_hours=100,
    )

    BonusCalculator.calculate(emp)

    assert emp.performance_coefficient == 1.0
    assert emp.uploaded_coefficient == 1.6
    assert any("上传绩效系数与系统计算系数不一致" in msg for msg in emp.exceptions)


def test_salary_processor_accepts_percent_strings():
    rows = [
        ["Ana", "E001", None, None, None, None, None, None, None, "10%", None, "20.5"],
        ["Ben", "E002", None, None, None, None, None, None, None, 15, None, 18],
    ]

    data = SalaryProcessor().load(rows)

    assert data["E001"] == {"hourly_rate": 20.5, "ratio": 0.1}
    assert data["E002"] == {"hourly_rate": 18.0, "ratio": 0.15}


def test_build_employees_splits_night_shift_and_flags_missing_matches():
    parser = FBUPerformanceParser()
    attendance_data = {
        "E001": {
            "白班": {"计薪出勤": 160, "OT1.5": 0, "OT2.0": 0, "病假": 0, "年假": 0, "节假日": 0},
            "夜班": {"计薪出勤": 8, "OT1.5": 2, "OT2.0": 0, "病假": 0, "年假": 0, "节假日": 0},
            "has_night_shift": True,
        },
        "E002": {
            "白班": {"计薪出勤": 100, "OT1.5": 0, "OT2.0": 0, "病假": 0, "年假": 0, "节假日": 0},
            "夜班": {"计薪出勤": 0, "OT1.5": 0, "OT2.0": 0, "病假": 0, "年假": 0, "节假日": 0},
            "has_night_shift": False,
        },
    }
    salary_data = {"E001": {"hourly_rate": 20, "ratio": 0.1}}
    performance_data = {"E001": {"score": 95, "level": None, "coefficient": None}}

    employees = parser.build_employees(attendance_data, salary_data, performance_data)

    by_id = {emp.employee_id: emp for emp in employees}
    assert by_id["E001"].hourly_rate == 20
    assert by_id["E001-1"].source_employee_id == "E001"
    assert by_id["E001-1"].hourly_rate == 21
    assert "未匹配薪资档案" in by_id["E002"].exceptions
    assert "未匹配绩效报表" in by_id["E002"].exceptions


def test_performance_preview_average_uses_scored_employee_count(tmp_path):
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.append([""] * 19)
    row_with_score = [""] * 19
    row_with_score[3] = "E001"
    row_with_score[16] = 80
    row_with_score[17] = "符合预期"
    row_with_score[18] = 1
    sheet.append(row_with_score)
    row_without_score = [""] * 19
    row_without_score[3] = "E002"
    row_without_score[17] = "符合预期+"
    row_without_score[18] = 1.2
    sheet.append(row_without_score)
    path = tmp_path / "performance.xlsx"
    workbook.save(path)

    preview = FBUPerformanceParser().parse_performance_preview(str(path))

    assert preview["summary"]["total_employees"] == 2
    assert preview["summary"]["scored_employees"] == 1
    assert preview["summary"]["avg_score"] == 80
