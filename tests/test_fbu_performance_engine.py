from bonus_platform.engine.fbu_performance.engines.base import EmployeeData
from bonus_platform.engine.fbu_performance.engines.bonus import BonusCalculator
from bonus_platform.engine.fbu_performance.engines.coefficient import CoefficientCalculator
from bonus_platform.engine.fbu_performance.engines.salary import SalaryProcessor
from bonus_platform.engine.fbu_performance.parser import FBUPerformanceParser
from bonus_platform.engine.fbu_performance.runs import FBURosterStore


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
        ["Cara", "E003", None, None, None, None, None, None, None, None, None, 0],
    ]

    data = SalaryProcessor().load(rows)

    assert data["E001"]["hourly_rate"] == 20.5
    assert data["E001"]["ratio"] == 0.1
    assert data["E002"]["hourly_rate"] == 18.0
    assert data["E002"]["ratio"] == 0.15
    assert data["E003"]["hourly_rate"] == 0.0
    assert data["E003"]["ratio"] == 0.0


def test_district_manager_uses_fixed_base_and_uploaded_coefficient():
    emp = EmployeeData(
        employee_id="zt15638",
        name="万其鑫",
        hourly_rate=40.384615,
        performance_ratio=0,
        performance_score=112.72,
        performance_level="超出预期",
        uploaded_coefficient=1.35,
        job_type="district_manager",
        fixed_performance_base=3000,
        base_hours=171.5,
        sick_hours=4.5,
    )

    BonusCalculator.calculate(emp)

    assert emp.performance_base == 3000
    assert emp.performance_coefficient == 1.35
    assert round(emp.performance_bonus, 2) == 4050


def test_adjustment_split_preview_reads_zhang_haibing_style_segments(tmp_path):
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "调薪拆分"
    sheet.append(["header"] * 32)
    for period, amount, reason in [
        ("4.1-4.11", 1404.9, "调薪前"),
        ("4.12-4.25", 1667.88, "调薪前"),
        ("4.26-4.30", 732.42, "调薪后"),
    ]:
        row = [""] * 32
        row[3] = "zt0021990"
        row[4] = "张海冰"
        row[9] = period
        row[28] = amount
        row[31] = reason
        sheet.append(row)
    path = tmp_path / "adjustments.xlsx"
    workbook.save(path)

    preview = FBUPerformanceParser().parse_adjustments_preview(str(path))

    assert preview["summary"]["total_employees"] == 1
    assert preview["summary"]["total_segments"] == 3
    assert preview["summary"]["active_performance_base"] == 732.42
    employee = preview["employees"][0]
    assert employee["employee_id"] == "zt0021990"
    assert employee["name"] == "张海冰"
    assert employee["segments"][2] == {
        "period": "4.26-4.30",
        "reason": "调薪后",
        "performance_base": 732.42,
    }


def test_adjustment_split_preview_accepts_platform_template_headers(tmp_path):
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "调薪拆分"
    sheet.append(["填报说明："])
    sheet.append(["以下为脱敏示例，不参与导入"])
    sheet.append(["zt0000001", "花名一", "4.1-4.15", 1200, "调薪前", "示例"])
    sheet.append([])
    sheet.append([])
    sheet.append(["工号", "姓名", "分段期间", "分段绩效基数", "核算标识", "备注"])
    sheet.append(["zt0021990", "张海冰", "4.26-4.30", 732.42, "调薪后", "转正"])
    path = tmp_path / "adjustments_template.xlsx"
    workbook.save(path)

    preview = FBUPerformanceParser().parse_adjustments_preview(str(path))

    assert preview["summary"]["total_employees"] == 1
    assert preview["summary"]["active_performance_base"] == 732.42
    assert preview["employees"][0]["segments"] == [
        {"period": "4.26-4.30", "reason": "调薪后", "performance_base": 732.42}
    ]


def test_adjustment_split_uses_post_adjustment_base_ratio_and_fixed_coefficient():
    parser = FBUPerformanceParser()
    engine = parser.parse_all_from_step_data(
        attendance_data=[
            {
                "employee_id": "zt0021990",
                "name": "张海冰",
                "department": "新泽西21号仓（SN）",
                "area": "新泽西区",
                "job_type": "warehouse",
                "has_night_shift": False,
                "day_shift": {"计薪出勤": 183.95, "OT1.5": 18.3, "OT2.0": 0, "病假": 0, "年假": 0, "节假日": 0},
                "night_shift": {"计薪出勤": 0, "OT1.5": 0, "OT2.0": 0, "病假": 0, "年假": 0, "节假日": 0},
            }
        ],
        salary_data=[
            {
                "employee_id": "zt0021990",
                "hourly_rate": 18,
                "ratio": 0.05,
                "calculation_method": "固定比例核算",
                "fixed_performance_base": 0,
            }
        ],
        performance_data=[],
        adjustment_data=[
            {
                "employee_id": "zt0021990",
                "segments": [
                    {"period": "4.1-4.11", "reason": "调薪前", "performance_base": 1404.9},
                    {"period": "4.12-4.25", "reason": "调薪前", "performance_base": 1667.88},
                    {"period": "4.26-4.30", "reason": "调薪后", "performance_base": 732.42},
                ],
            }
        ],
    )

    emp = engine.get_employee("zt0021990")

    assert emp.performance_base == 732.42
    assert emp.performance_ratio == 0.05
    assert emp.performance_coefficient == 1.0
    assert round(emp.performance_bonus, 2) == 36.62
    assert [round(segment.performance_bonus, 2) for segment in emp.calculation_segments] == [0, 0, 36.62]


def test_salary_preview_reports_total_valid_and_zero_hourly_counts(tmp_path):
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["姓名", "工号", "", "", "", "", "", "", "", "月度绩效奖金比例(%)", "", "时薪标准"])
    sheet.append(["Ana", "E001", "", "", "", "", "", "", "", "10%", "", 20])
    sheet.append(["Ben", "E002", "", "", "", "", "", "", "", "", "", 0])
    sheet.append(["Cara", "E003", "", "", "", "", "", "", "", 20, "", 30])
    path = tmp_path / "salary.xlsx"
    workbook.save(path)

    preview = FBUPerformanceParser().parse_salary_preview(str(path))

    assert preview["summary"]["total_employees"] == 3
    assert preview["summary"]["valid_hourly_count"] == 2
    assert preview["summary"]["zero_hourly_count"] == 1
    assert preview["summary"]["avg_hourly_rate"] == 25


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


def test_attendance_preview_uses_attendance_name_when_roster_is_missing(tmp_path):
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "sheet1"
    sheet.append(["header"] * 118)
    row = [""] * 118
    row[0] = "2026-04-01"
    row[1] = "Ana Attendance"
    row[2] = "E001"
    row[21] = "08:00"
    row[117] = 8
    sheet.append(row)
    path = tmp_path / "attendance.xlsx"
    workbook.save(path)

    preview = FBUPerformanceParser().parse_attendance_preview(str(path), target_month=4)

    employee = preview["employees"][0]
    assert employee["name"] == "Ana Attendance"
    assert employee["roster_matched"] is False
    assert preview["summary"]["roster_missing"] == 1


def test_roster_loader_finds_shifted_lingse_column_by_header(tmp_path):
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    headers = [""] * 123
    headers[0] = "姓名"
    headers[3] = "工号"
    headers[19] = "二级部门"
    headers[20] = "三级部门"
    headers[89] = "划分区域"
    headers[122] = "领色"
    sheet.append(headers)

    for employee_id, name, department_parts, lingse in [
        ("E001", "Ana Roster", ("FBU", "Americas"), "蓝领"),
        ("E002", "Ben Roster", ("FBU", "Americas"), "白领"),
        ("E003", "Cara Roster", ("HRAS人力综合条线", "FBU HRBP Dept.", "新泽西区HRBP部"), "蓝领"),
        ("zt15638", "万其鑫", ("FBU仓储事业部", "美洲区", "新泽西区"), "白领"),
    ]:
        row = [""] * 123
        row[0] = name
        row[3] = employee_id
        row[19] = department_parts[0]
        row[20] = department_parts[1]
        if len(department_parts) > 2:
            row[21] = department_parts[2]
        row[89] = "US-West"
        row[122] = lingse
        sheet.append(row)

    path = tmp_path / "roster.xlsx"
    workbook.save(path)

    roster = FBUPerformanceParser().load_roster(str(path))

    assert roster["E001"]["name"] == "Ana Roster"
    assert roster["E001"]["department"] == "FBU-Americas"
    assert roster["E001"]["area"] == "US-West"
    assert roster["E001"]["job_type"] == "warehouse"
    assert roster["E002"]["job_type"] == "warehouse"
    assert roster["E003"]["job_type"] == "functional"
    assert roster["zt15638"]["job_type"] == "district_manager"


def test_base_roster_store_saves_metadata_and_copies_snapshot(tmp_path):
    store = FBURosterStore(str(tmp_path))
    content = b"fake roster bytes"

    metadata = store.save_active_roster(content, "roster.xlsx", total_employees=12)
    copied = store.copy_active_to_run("run123")

    assert metadata["filename"] == "roster.xlsx"
    assert metadata["total_employees"] == 12
    assert store.get_metadata()["has_roster"] is True
    assert copied.read_bytes() == content
    assert copied.name == "roster.xlsx"
