from pathlib import Path

from openpyxl import Workbook, load_workbook

from bonus_platform.engine.models import CalculationResult
from bonus_platform.engine.workbook_io import (
    PENDING_CONFIRMATION_HEADERS,
    build_final_workbook,
    build_pending_workbook,
)


def _pending_result() -> CalculationResult:
    return CalculationResult(
        month=202510,
        details=[],
        recruitment_summary=[],
        referral_summary=[],
        pending_confirmations=[
            {
                "源行号": 18,
                "姓名": "待确认员工",
                "工号": "zt-pending-001",
                "奖金类型": "招聘奖金",
                "角色": "招聘负责人",
                "发放对象工号": "zt-recruiter",
                "发放对象姓名": "招聘负责人",
                "发放对象状态": "离职",
                "币种": "CNY",
                "发放节点": "入职1月奖金",
                "建议发放周期": 202510,
                "建议发放金额": 300,
                "人工确认结果": "",
                "人工确认金额": "",
                "不发/暂缓原因": "",
                "系统提示": "招聘负责人非在职状态，需确认是否发放",
            }
        ],
        exceptions=[],
    )


def test_pending_workbook_is_compact_and_has_confirmation_dropdown(tmp_path: Path):
    path = tmp_path / "pending.xlsx"

    build_pending_workbook(_pending_result(), path)

    workbook = load_workbook(path)
    sheet = workbook["待确认_发放判断"]
    headers = [sheet.cell(1, column).value for column in range(1, sheet.max_column + 1)]
    validations = list(sheet.data_validations.dataValidation)

    assert headers == PENDING_CONFIRMATION_HEADERS
    assert "确认人" not in headers
    assert "确认时间" not in headers
    assert "币种" in headers
    assert any(
        str(validation.sqref) in {"M2", f"M2:M{sheet.max_row}"}
        and validation.formula1 == '"确认发放,不发放,暂缓"'
        for validation in validations
    )


def test_final_workbook_merges_pending_confirmation_by_currency(tmp_path: Path):
    initial_path = tmp_path / "initial.xlsx"
    confirmation_path = tmp_path / "confirmation.xlsx"
    output_path = tmp_path / "final.xlsx"
    initial = Workbook()
    recruitment = initial.active
    recruitment.title = "招聘奖金汇总"
    recruitment.append(["工号", "姓名", "角色", "币种", "核算月份", "入职1月奖金", "入职3月奖金", "入职6月奖金", "转正奖金", "合计发放"])
    recruitment.append(["zt-recruiter", "招聘负责人", "招聘负责人", "CNY", 202510, 10, 0, 0, 0, 10])
    recruitment.append(["zt-recruiter", "招聘负责人", "招聘负责人", "USD", 202510, 20, 0, 0, 0, 20])
    referral = initial.create_sheet("内推奖金汇总")
    referral.append(["推荐人工号", "推荐人姓名", "币种", "核算月份", "入职1月奖金", "入职3月奖金", "入职6月奖金", "转正奖金", "合计发放"])
    initial.save(initial_path)

    confirmation = Workbook()
    pending = confirmation.active
    pending.title = "待确认_发放判断"
    pending.append(PENDING_CONFIRMATION_HEADERS)
    pending.append(
        [
            18,
            "待确认员工",
            "zt-pending-001",
            "招聘奖金",
            "招聘负责人",
            "zt-recruiter",
            "招聘负责人",
            "离职",
            "USD",
            "入职1月奖金",
            202510,
            300,
            "确认发放",
            "",
            "",
            "招聘负责人非在职状态，需确认是否发放",
        ]
    )
    confirmation.save(confirmation_path)

    build_final_workbook(initial_path, confirmation_path, output_path)

    workbook = load_workbook(output_path, data_only=True)
    rows = list(workbook["最终招聘奖金汇总"].iter_rows(min_row=2, values_only=True))
    by_currency = {row[3]: row for row in rows}

    assert by_currency["CNY"][5] == 10
    assert by_currency["CNY"][9] == 10
    assert by_currency["USD"][5] == 320
    assert by_currency["USD"][9] == 320
