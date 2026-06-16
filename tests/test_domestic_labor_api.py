"""国内劳务工薪酬核算 API 测试"""
from datetime import date
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from bonus_platform.app import app
from bonus_platform.engine.domestic_labor.engines.canbu import CanBuEngine
from bonus_platform.engine.domestic_labor.engines.gonglingjiang import GongLingJiangEngine
from bonus_platform.engine.domestic_labor.engines.quanqinjiang import QuanQinJiangEngine
from bonus_platform.engine.domestic_labor.engines.waisu_butie import WaiSuBuTieEngine
from bonus_platform.engine.domestic_labor import parser as domestic_parser
from bonus_platform.engine.domestic_labor.parser import ExcelParser


def _create_test_excel(sheet_names: dict[str, list[list]]) -> bytes:
    """创建测试 Excel 文件"""
    wb = Workbook()
    # Remove default sheet
    wb.remove(wb.active)

    for sheet_name, rows in sheet_names.items():
        ws = wb.create_sheet(sheet_name)
        for row in rows:
            ws.append(row)

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def test_excel_parser_supports_legacy_xls(monkeypatch, tmp_path):
    """老式 .xls 文件走 xlrd 解析分支，避免被 openpyxl 拒绝"""
    class FakeCell:
        def __init__(self, value):
            self.value = value
            self.ctype = domestic_parser.xlrd.XL_CELL_NUMBER if isinstance(value, (int, float)) else domestic_parser.xlrd.XL_CELL_TEXT

    class FakeSheet:
        name = "Sheet"
        nrows = 2
        ncols = 4
        values = [
            ["工号", "姓名", "正班出勤天数", "旷工天数"],
            ["OWHN001", "张三", 20.0, 1.0],
        ]

        def cell_value(self, row, col):
            return self.values[row][col]

        def cell(self, row, col):
            return FakeCell(self.values[row][col])

    class FakeBook:
        datemode = 0

        def sheet_names(self):
            return ["Sheet"]

        def sheet_by_name(self, name):
            assert name == "Sheet"
            return FakeSheet()

    xls_path = tmp_path / "attendance.xls"
    xls_path.write_bytes(b"fake xls")
    monkeypatch.setattr(domestic_parser.xlrd, "open_workbook", lambda _: FakeBook())

    parser = ExcelParser(str(xls_path)).load()
    parsed = parser.parse_sheet("Sheet")

    assert parser.get_sheet_names() == ["Sheet"]
    assert parsed.headers == ["工号", "姓名", "正班出勤天数", "旷工天数"]
    assert parsed.rows == [{"工号": "OWHN001", "姓名": "张三", "正班出勤天数": 20, "旷工天数": 1}]


def _quanqinjiang_data() -> bytes:
    """全勤奖测试数据"""
    return _create_test_excel({
        "全勤奖": [
            ["工号", "姓名", "考勤月份", "入职日期", "最后工作日", "旷工天数", "正班迟到次数", "早退次数", "签卡次数", "工伤假天数", "事假时数", "病假时数", "入离职缺勤时数", "迟到早退30分钟内扣款"],
            ["OWHN001", "张三", "202606", "2023-01-15", None, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            ["OWHN002", "李四", "202606", "2022-06-01", None, 1, 0, 0, 0, 0, 0, 0, 0, 0],
        ],
    })


def _multi_engine_data() -> bytes:
    """多引擎测试数据"""
    return _create_test_excel({
        "全勤奖": [
            ["工号", "姓名", "考勤月份", "入职日期", "最后工作日", "旷工天数", "正班迟到次数", "早退次数", "签卡次数", "工伤假天数", "事假时数", "病假时数", "入离职缺勤时数", "迟到早退30分钟内扣款"],
            ["OWHN001", "张三", "202606", "2023-01-15", None, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        ],
        "餐补": [
            ["工号", "姓名", "餐补标准", "出勤天数", "正班时数合计", "预计算餐补"],
            ["OWHN001", "张三", "19元/天，封顶500元/月", 22, 176, None],
        ],
    })


def _gonglingjiang_data() -> bytes:
    """工龄奖 API 工作流测试数据"""
    return _create_test_excel({
        "月考勤": [
            ["工号", "姓名", "考勤月份", "二级部门名称", "岗位名称", "入职日期", "排班天数", "实际在职工作日天数", "正班出勤天数", "事假时数", "病假时数", "旷工天数", "排休请假天数"],
            ["OWHN001", "张三", "202606", "第四纵队", "内勤专员", "2023-01-01", 26, 26, 26, 0, 0, 0, 0],
        ],
    })


# ── 测试用例 ──


def test_list_templates():
    """测试模板列表接口"""
    client = TestClient(app)
    response = client.get("/api/domestic-labor/templates")

    assert response.status_code == 200
    data = response.json()
    assert "templates" in data
    assert len(data["templates"]) == 4

    # 验证每个模板结构
    engines = {t["engine"] for t in data["templates"]}
    assert engines == {"quanqinjiang", "canbu", "waisu_butie", "gonglingjiang"}

    for template in data["templates"]:
        assert "name" in template
        assert "description" in template
        assert "columns" in template


def test_download_template():
    """测试模板下载接口"""
    client = TestClient(app)
    response = client.get("/api/domestic-labor/templates/quanqinjiang/download")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert len(response.content) > 0


def test_download_template_invalid_engine():
    """测试无效引擎模板下载"""
    client = TestClient(app)
    response = client.get("/api/domestic-labor/templates/invalid_engine/download")

    assert response.status_code == 404


def test_create_run_with_valid_data():
    """测试创建计算任务 - 有效数据"""
    client = TestClient(app)

    response = client.post(
        "/api/domestic-labor/runs",
        files={"file": ("test.xlsx", _quanqinjiang_data(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"engines": "quanqinjiang", "attendance_month": "202606"},
    )

    assert response.status_code == 200
    data = response.json()
    assert "run_id" in data
    assert data["status"] == "已上传"
    assert "计算任务已提交" in data["message"]

    # Cleanup
    client.delete(f"/api/domestic-labor/runs/{data['run_id']}")


def test_create_run_without_engines():
    """测试创建计算任务 - 无引擎"""
    client = TestClient(app)

    response = client.post(
        "/api/domestic-labor/runs",
        files={"file": ("test.xlsx", _quanqinjiang_data(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"engines": "", "attendance_month": "202606"},
    )

    assert response.status_code == 400
    assert "请至少选择一个计算引擎" in response.json()["detail"]


def test_create_run_with_invalid_engine():
    """测试创建计算任务 - 无效引擎"""
    client = TestClient(app)

    response = client.post(
        "/api/domestic-labor/runs",
        files={"file": ("test.xlsx", _quanqinjiang_data(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"engines": "invalid_engine", "attendance_month": "202606"},
    )

    assert response.status_code == 400
    assert "未知引擎" in response.json()["detail"]


def test_create_run_with_invalid_file():
    """测试创建计算任务 - 无效文件类型"""
    client = TestClient(app)

    response = client.post(
        "/api/domestic-labor/runs",
        files={"file": ("test.txt", b"not an excel", "text/plain")},
        data={"engines": "quanqinjiang", "attendance_month": "202606"},
    )

    assert response.status_code == 400
    assert "请上传 Excel 文件" in response.json()["detail"]


def test_get_run_status():
    """测试获取任务状态"""
    client = TestClient(app)

    # Create run
    create_response = client.post(
        "/api/domestic-labor/runs",
        files={"file": ("test.xlsx", _quanqinjiang_data(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"engines": "quanqinjiang", "attendance_month": "202606"},
    )
    run_id = create_response.json()["run_id"]

    # Get status
    response = client.get(f"/api/domestic-labor/runs/{run_id}")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert data["status"] in ["已上传", "计算中", "已完成", "失败"]

    # Cleanup
    client.delete(f"/api/domestic-labor/runs/{run_id}")


def test_get_run_not_found():
    """测试获取不存在的任务"""
    client = TestClient(app)
    response = client.get("/api/domestic-labor/runs/nonexistent_id")

    assert response.status_code == 404


def test_list_runs():
    """测试任务列表"""
    client = TestClient(app)
    response = client.get("/api/domestic-labor/runs")

    assert response.status_code == 200
    data = response.json()
    assert "runs" in data
    assert isinstance(data["runs"], list)


def test_delete_run():
    """测试删除任务"""
    client = TestClient(app)

    # Create run
    create_response = client.post(
        "/api/domestic-labor/runs",
        files={"file": ("test.xlsx", _quanqinjiang_data(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"engines": "quanqinjiang", "attendance_month": "202606"},
    )
    run_id = create_response.json()["run_id"]

    # Delete
    response = client.delete(f"/api/domestic-labor/runs/{run_id}")
    assert response.status_code == 200
    assert "已删除" in response.json()["message"]

    # Verify deleted
    get_response = client.get(f"/api/domestic-labor/runs/{run_id}")
    assert get_response.status_code == 404


def test_full_workflow():
    """完整工作流测试：创建 → 等待 → 结果 → 导出 → 下载"""
    client = TestClient(app)

    # 1. 创建任务
    create_response = client.post(
        "/api/domestic-labor/runs",
        files={"file": ("test.xlsx", _multi_engine_data(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"engines": "quanqinjiang,canbu", "attendance_month": "202606"},
    )
    assert create_response.status_code == 200
    run_id = create_response.json()["run_id"]

    # 2. 等待计算完成 (轮询)
    import time
    for _ in range(20):
        time.sleep(0.5)
        status_response = client.get(f"/api/domestic-labor/runs/{run_id}")
        status = status_response.json()["status"]
        if status in ["已完成", "失败"]:
            break

    assert status == "已完成"

    # 3. 获取结果
    results_response = client.get(f"/api/domestic-labor/runs/{run_id}/results")
    assert results_response.status_code == 200
    results = results_response.json()
    assert results["status"] == "已完成"
    assert len(results["results"]) == 1
    assert results["results"][0]["employee_id"] == "OWHN001"

    # 4. 导出 Excel
    export_response = client.get(f"/api/domestic-labor/runs/{run_id}/export")
    assert export_response.status_code == 200
    file_name = export_response.json()["file_name"]
    assert "薪酬核算" in file_name

    # 5. 下载文件
    download_response = client.get(f"/api/domestic-labor/runs/{run_id}/download/{file_name}")
    assert download_response.status_code == 200
    assert len(download_response.content) > 0

    # Cleanup
    client.delete(f"/api/domestic-labor/runs/{run_id}")


def test_gonglingjiang_api_exposes_subject_details_and_audit_explanation():
    """API 结果暴露引擎详情，供前端解释抽屉使用"""
    client = TestClient(app)

    create_response = client.post(
        "/api/domestic-labor/runs",
        files={"file": ("gongling.xlsx", _gonglingjiang_data(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={
            "engines": "gonglingjiang",
            "attendance_month": "202606",
            "hrbp_list": '["OWHN001"]',
        },
    )
    assert create_response.status_code == 200
    run_id = create_response.json()["run_id"]

    import time
    for _ in range(20):
        time.sleep(0.5)
        status_response = client.get(f"/api/domestic-labor/runs/{run_id}")
        metadata = status_response.json()
        if metadata["status"] in ["已完成", "失败"]:
            break

    assert metadata["status"] == "已完成"
    row = metadata["results"][0]
    subject_detail = row["subject_details"]["gonglingjiang"]
    explanation = subject_detail["audit_explanation"]

    assert row["gonglingjiang"] == 450
    assert subject_detail["amount"] == 450
    assert subject_detail["exceptions"] == []
    assert explanation["subject"] == "gonglingjiang"
    assert explanation["intermediate_values"]["工龄(年)"] == 3
    assert row["exceptions"] == []

    client.delete(f"/api/domestic-labor/runs/{run_id}")


def test_quanqinjiang_returns_audit_explanation():
    """全勤奖返回计算公式和审计解释"""
    employee = {
        "工号": "OWHN001",
        "姓名": "张三",
        "考勤月份": "202606",
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
    }

    result = QuanQinJiangEngine().calculate(employee)
    explanation = result.details["audit_explanation"]

    assert result.amount == 100
    assert explanation["subject"] == "quanqinjiang"
    assert explanation["formula"] == "满足全勤条件 = 100"
    assert explanation["intermediate_values"]["旷工天数"] == 0
    assert explanation["steps"]


def test_canbu_dongguan_uses_platform_rule_without_meal_standard():
    """东莞餐补使用平台规则，不依赖月报餐补标准"""
    employee = {
        "工号": "OWHN001",
        "姓名": "张三",
        "工作地区": "",
        "一级部门名称": "莞深操作",
        "岗位名称": "操作员",
        "餐补标准": "",
    }
    daily_attendance = [
        {"工号": "OWHN001", "工作地区": "东莞", "工作状态": "工作日", "正班时数": 8, "刷卡加班": 0},
        {"工号": "OWHN001", "工作地区": "东莞", "工作状态": "工作日", "正班时数": 4, "刷卡加班": 0},
        {"工号": "OWHN001", "工作地区": "东莞", "工作状态": "星期天休息", "正班时数": 0, "刷卡加班": 3},
    ]

    result = CanBuEngine().calculate(employee, daily_attendance)
    explanation = result.details["audit_explanation"]

    assert result.amount == 35.62
    assert explanation["subject"] == "canbu"
    assert explanation["formula"] == "min(Σ单日餐补, 500)"
    assert explanation["inputs"]["工作地区"] == "东莞"
    assert explanation["intermediate_values"]["日餐补合计"] == 35.62
    assert explanation["steps"]


def test_canbu_dongguan_keeps_existing_piecework_exclusion():
    """东莞保留理货操作组计件排除规则"""
    employee = {
        "工号": "OWHN001",
        "姓名": "张三",
        "工作地区": "东莞",
        "一级部门名称": "莞深操作",
        "岗位名称": "操作员",
    }
    daily_attendance = [
        {
            "工号": "OWHN001",
            "工作地区": "东莞",
            "工作状态": "工作日",
            "正班时数": 8,
            "刷卡加班": 0,
            "四级部门名称": "理货操作组",
            "计时": "计件",
        },
    ]

    result = CanBuEngine().calculate(employee, daily_attendance)

    assert result.amount == 0
    assert result.details["日餐补明细"] == [0]


def test_canbu_jinjiang_is_not_eligible():
    """晋江区域不享有餐补"""
    employee = {
        "工号": "OWHN001",
        "姓名": "张三",
        "工作地区": "晋江",
        "一级部门名称": "东南区",
        "岗位名称": "操作员",
    }

    result = CanBuEngine().calculate(employee, daily_attendance=[])
    explanation = result.details["audit_explanation"]

    assert result.amount == 0
    assert result.details["reason"] == "晋江区域不享有餐补"
    assert explanation["formula"] == "晋江区域 = 0"


def test_canbu_jiashan_is_pending_rule():
    """嘉善餐补口径待补充，暂不计算"""
    employee = {
        "工号": "OWHN001",
        "姓名": "张三",
        "工作地区": "嘉善",
        "岗位名称": "操作员",
    }

    result = CanBuEngine().calculate(employee, daily_attendance=[])

    assert result.amount == 0
    assert result.details["reason"] == "嘉善餐补规则待补充"
    assert "嘉善餐补规则待补充" in result.warnings[0]


def test_waisu_butie_returns_audit_explanation():
    """外宿补贴返回按天折算公式"""
    employee = {
        "工号": "OWHN001",
        "姓名": "张三",
        "考勤月份": "202606",
        "外宿补贴标准": "150",
        "入职日期": date(2023, 1, 1),
        "最后工作日": None,
        "事假时数": 0,
        "排休请假时数": 0,
        "病假时数": 0,
        "旷工时数": 0,
        "入离职缺勤时数": 0,
    }
    daily_attendance = [{"工号": "OWHN001", "上班一": "09:00", "下班一": "18:00"}]

    result = WaiSuBuTieEngine().calculate(employee, daily_attendance, housing_records=[])
    explanation = result.details["audit_explanation"]

    assert result.amount == 150
    assert explanation["subject"] == "waisu_butie"
    assert explanation["formula"] == "补贴标准/月天数 × 有效补贴天数"
    assert explanation["intermediate_values"]["外宿补贴天数"] == 30
    assert explanation["steps"]


def test_gonglingjiang_returns_structured_exception_for_missing_hrbp_list():
    """工龄奖缺少 HRBP 名单时保留 warning，并返回结构化异常"""
    result = GongLingJiangEngine().calculate(_gongling_collection_employee(), hrbp_list=[], region="gsdg")

    assert result.amount == 0
    assert "请提供本月HRBP发放名单" in result.warnings[0]
    assert result.details["exceptions"][0]["code"] == "MISSING_HRBP_LIST"
    assert result.details["exceptions"][0]["level"] == "warning"
    assert result.details["exceptions"][0]["subject"] == "gonglingjiang"
    assert "suggested_action" in result.details["exceptions"][0]
    assert result.details["audit_explanation"]["rule_name"] == "工龄奖资格判断"


def test_gonglingjiang_returns_audit_explanation_for_hrbp_match():
    """工龄奖发放结果包含审计解释、中间值和计算步骤"""
    result = GongLingJiangEngine().calculate(
        _gongling_collection_employee(),
        hrbp_list=["OWHN001"],
        region="gsdg",
    )

    explanation = result.details["audit_explanation"]
    assert result.amount == 450
    assert explanation["subject"] == "gonglingjiang"
    assert explanation["amount"] == 450
    assert explanation["inputs"]["HRBP名单人数"] == 1
    assert explanation["intermediate_values"]["工龄(年)"] == 3
    assert explanation["intermediate_values"]["标准"] == 150
    assert explanation["intermediate_values"]["上限"] == 600
    assert explanation["steps"]
    assert result.details["exceptions"] == []


def test_gonglingjiang_collection_employee_outside_hrbp_list_is_normal_zero():
    """HRBP 名单存在但员工不在名单内时，正常不发放且不进入异常队列"""
    result = GongLingJiangEngine().calculate(
        _gongling_collection_employee(),
        hrbp_list=["OWHN999"],
        region="gsdg",
    )

    assert result.amount == 0
    assert result.details["reason"] == "不符合工龄奖标准"
    assert result.details["exceptions"] == []
    assert result.warnings == []


def test_gonglingjiang_uses_raw_absence_fields_instead_of_leave_hours():
    """工龄奖缺勤折算不读取月报聚合的请假时数，按规则卡原始字段计算"""
    employee = {
        **_gongling_collection_employee(),
        "请假时数": 80,
        "事假时数": 0,
        "病假时数": 0,
        "旷工天数": 0,
        "排休请假天数": 0,
    }
    result = GongLingJiangEngine().calculate(employee, hrbp_list=["OWHN001"], region="gsdg")

    assert result.amount == 450
    explanation = result.details["audit_explanation"]
    assert explanation["intermediate_values"]["事病旷排休时数"] == 0
    assert "未达到56小时门槛" in " ".join(explanation["steps"])


def test_gonglingjiang_absence_components_trigger_proration():
    """事假+病假+旷工天数×8+排休请假天数×8 达到56小时后按天折算"""
    employee = {
        **_gongling_collection_employee(),
        "事假时数": 8,
        "病假时数": 8,
        "旷工天数": 1,
        "排休请假天数": 4,
    }
    result = GongLingJiangEngine().calculate(employee, hrbp_list=["OWHN001"], region="gsdg")

    assert result.amount == 328.85
    explanation = result.details["audit_explanation"]
    assert explanation["intermediate_values"]["事病旷排休时数"] == 56
    assert explanation["intermediate_values"]["旷工折算时数"] == 8
    assert explanation["intermediate_values"]["排休请假折算时数"] == 32
    assert "达到56小时门槛" in " ".join(explanation["steps"])


def test_gonglingjiang_final_amount_floors_at_zero():
    """工龄奖折算后金额为负时按规则卡兜底为0"""
    employee = {
        **_gongling_collection_employee(),
        "实际在职工作日天数": -10,
    }
    result = GongLingJiangEngine().calculate(employee, hrbp_list=["OWHN001"], region="gsdg")

    assert result.amount == 0
    assert result.details["audit_explanation"]["intermediate_values"]["入离职折算后金额"] < 0


def test_gonglingjiang_zero_regular_attendance_days_still_prorates():
    """正班出勤天数为0不直接归0，继续折算并给出提示异常"""
    employee = {
        **_gongling_collection_employee(),
        "正班出勤天数": 0,
        "事假时数": 128,
        "排班天数": 20,
        "实际在职工作日天数": 20,
    }
    result = GongLingJiangEngine().calculate(employee, hrbp_list=["OWHN001"], region="gsdg")

    assert result.amount == 90
    assert result.details["audit_explanation"]["rule_name"] == "工龄奖标准与缺勤折算"
    assert result.details["audit_explanation"]["intermediate_values"]["事病旷排休时数"] == 128
    assert result.details["exceptions"][0]["code"] == "ZERO_REGULAR_ATTENDANCE_DAYS"
    assert result.details["exceptions"][0]["level"] == "info"
    assert "正班出勤天数为0" in result.warnings[0]


def test_gonglingjiang_dongguan_operation_uses_work_area_position_rules():
    """东莞操作按工作地区和新岗位范围发放"""
    employee = {
        **_operation_employee(),
        "工作地区": "东莞",
        "岗位名称": "操作员",
    }
    result = GongLingJiangEngine().calculate(employee, hrbp_list=[], region="gsdg")

    assert result.amount == 450
    explanation = result.details["audit_explanation"]
    assert explanation["inputs"]["工作地区"] == "东莞"
    assert explanation["intermediate_values"]["标准"] == 150
    assert explanation["intermediate_values"]["上限"] == 600


def test_gonglingjiang_dongguan_operation_excludes_non_allowed_position():
    """东莞操作内勤专员不再按操作岗位发放工龄奖"""
    employee = {
        **_operation_employee(),
        "工作地区": "东莞",
        "岗位名称": "内勤专员",
    }
    result = GongLingJiangEngine().calculate(employee, hrbp_list=[], region="gsdg")

    assert result.amount == 0
    assert result.details["reason"] == "东莞操作岗位不享有工龄奖"
    assert result.details["audit_explanation"]["rule_name"] == "工龄奖资格判断"


def test_gonglingjiang_jiashan_operation_has_no_seniority_bonus():
    """嘉善操作区域无工龄奖"""
    employee = {
        **_operation_employee(),
        "工作地区": "嘉善",
        "二级部门名称": "华东枢纽",
        "岗位名称": "操作员",
    }
    result = GongLingJiangEngine().calculate(employee, hrbp_list=[], region="gsdg")

    assert result.amount == 0
    assert result.details["reason"] == "嘉善区域无工龄奖"
    assert result.details["audit_explanation"]["rule_name"] == "工龄奖工作地区判断"


def test_gonglingjiang_jinjiang_operation_uses_50_rate_and_150_cap():
    """晋江操作员按50元/年且150封顶"""
    employee = {
        **_operation_employee(),
        "工作地区": "晋江",
        "一级部门名称": "东南区",
        "二级部门名称": "东南枢纽",
        "岗位名称": "操作员",
        "入职日期": date(2020, 1, 1),
    }
    result = GongLingJiangEngine().calculate(employee, hrbp_list=[], region="gsdg")

    assert result.amount == 150
    explanation = result.details["audit_explanation"]
    assert explanation["intermediate_values"]["工龄(年)"] == 6
    assert explanation["intermediate_values"]["标准"] == 50
    assert explanation["intermediate_values"]["上限"] == 150


def test_gonglingjiang_operation_deducts_work_injury_days():
    """操作类工龄奖按工伤假天数×8折算扣减"""
    employee = {
        **_operation_employee(),
        "工作地区": "东莞",
        "岗位名称": "操作员",
        "排班天数": 20,
        "实际在职工作日天数": 20,
        "工伤假天数": 2,
    }
    result = GongLingJiangEngine().calculate(employee, hrbp_list=[], region="gsdg")

    assert result.amount == 405
    explanation = result.details["audit_explanation"]
    assert explanation["intermediate_values"]["工伤假天数"] == 2
    assert explanation["intermediate_values"]["工伤折算时数"] == 16
    assert "工伤假天数2" in " ".join(explanation["steps"])


def _gongling_collection_employee() -> dict:
    return {
        "工号": "OWHN001",
        "姓名": "张三",
        "二级部门名称": "第四纵队",
        "岗位名称": "内勤专员",
        "入职日期": date(2023, 1, 1),
        "考勤月份": "202606",
        "排班天数": 26,
        "实际在职工作日天数": 26,
        "正班出勤天数": 26,
        "请假时数": 0,
        "事假时数": 0,
        "病假时数": 0,
        "旷工天数": 0,
        "排休请假天数": 0,
    }


def _operation_employee() -> dict:
    return {
        "工号": "OWHN888",
        "姓名": "李四",
        "一级部门名称": "莞深操作",
        "二级部门名称": "中国操作部",
        "岗位名称": "操作员",
        "工作地区": "东莞",
        "入职日期": date(2023, 1, 1),
        "考勤月份": "202606",
        "排班天数": 26,
        "实际在职工作日天数": 26,
        "正班出勤天数": 26,
        "事假时数": 0,
        "病假时数": 0,
        "旷工天数": 0,
        "排休请假天数": 0,
        "工伤假天数": 0,
    }
