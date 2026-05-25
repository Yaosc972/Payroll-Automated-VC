from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import Workbook
from openpyxl import load_workbook

from bonus_platform.app import app
from bonus_platform.config import DEFAULT_RULE_WORKBOOK
from bonus_platform.engine.calculator import calculate
from bonus_platform.engine.models import ImportRow
from bonus_platform.engine.rules import load_rulebook


def _monthly_workbook_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "导入_月度数据"
    sheet.append(["核算月份", "工号", "姓名"])
    sheet.append([202510, "zt-test-001", "月度测试"])
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_calculation_ignores_undeclared_history_upload():
    client = TestClient(app)

    response = client.post(
        "/api/calculate",
        files={
            "file": ("monthly.xlsx", _monthly_workbook_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            "history_file": ("legacy.txt", b"not a workbook", "text/plain"),
        },
    )

    assert response.status_code == 200
    assert response.json()["month"] == 202510
    assert "historySource" not in response.json()
    assert "historyRows" not in response.json()


def test_download_template_contains_only_monthly_input_sheets():
    client = TestClient(app)

    response = client.get("/api/template")
    workbook = load_workbook(BytesIO(response.content), data_only=False, read_only=True)

    assert response.status_code == 200
    assert workbook.sheetnames == ["使用说明", "导入_月度数据"]


def test_download_template_hides_legacy_override_columns_from_monthly_import():
    client = TestClient(app)

    response = client.get("/api/template")
    workbook = load_workbook(BytesIO(response.content), data_only=False, read_only=True)
    sheet = workbook["导入_月度数据"]
    headers = [sheet.cell(1, column).value for column in range(1, sheet.max_column + 1)]

    assert response.status_code == 200
    assert not [header for header in headers if header and str(header).endswith("_覆盖")]


def test_current_month_calculation_ignores_legacy_override_fields():
    values = {
        "核算月份": 202510,
        "姓名": "覆盖测试",
        "工号": "zt-override-001",
        "工作地": "中国大陆",
        "标签分类": "国内",
        "职级": "P1-3",
        "ABC类别": "C类",
        "招聘渠道": "招聘网站",
        "招聘负责人工号": "zt-recruiter",
        "招聘负责人姓名": "招聘负责人",
        "招聘启动日期": 45500,
        "候选人入职时间": 45925,
        "转正日期": 46017,
        "招聘人入职1月发放金额_覆盖": 99999,
        "招聘人入职1月发放周期_覆盖": 202510,
    }

    with_overrides = calculate([ImportRow(source_row=9, values=values)], load_rulebook(DEFAULT_RULE_WORKBOOK))
    without_overrides = calculate(
        [ImportRow(source_row=9, values={key: value for key, value in values.items() if not key.endswith("_覆盖")})],
        load_rulebook(DEFAULT_RULE_WORKBOOK),
    )

    assert with_overrides.details[0].recruiter_1m_bonus == without_overrides.details[0].recruiter_1m_bonus
    assert with_overrides.details[0].recruiter_1m_bonus != 99999


def test_pending_source_row_uses_uploaded_excel_row_number():
    rows = [
        ImportRow(
            source_row=12,
            values={
                "核算月份": 202510,
                "姓名": "源行测试",
                "工号": "zt-row-001",
                "工作地": "中国大陆",
                "标签分类": "国内",
                "职级": "P1-3",
                "ABC类别": "C类",
                "招聘渠道": "招聘网站",
                "招聘负责人工号": "zt-recruiter",
                "招聘负责人姓名": "招聘负责人",
                "招聘负责人人员状态": "",
                "招聘启动日期": 45800,
                "候选人入职时间": 45925,
                "转正日期": 46017,
            },
        )
    ]

    result = calculate(rows, load_rulebook(DEFAULT_RULE_WORKBOOK))

    assert result.pending_confirmations
    assert result.pending_confirmations[0]["源行号"] == 12
