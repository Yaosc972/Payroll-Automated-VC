import os
from pathlib import Path
from datetime import datetime

import pytest

from bonus_platform.config import DEFAULT_RULE_WORKBOOK
from bonus_platform.engine.calculator import _period_after, _probation_period, _referral_scope, calculate
from bonus_platform.engine.models import ImportRow
from bonus_platform.engine.history import load_history_overrides, merge_history_overrides
from bonus_platform.engine.rules import load_rulebook
from bonus_platform.engine.workbook_io import read_import_rows


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MONTHLY_202509 = PROJECT_ROOT / "outputs" / "招聘奖金与内推奖金自动核算模板_计算2次.xlsx"
HISTORY_202509 = Path(os.environ.get("BONUS_HISTORY_202509", PROJECT_ROOT / "outputs" / "history_202509.xlsx"))
CUMULATIVE_TEMPLATE_202509 = PROJECT_ROOT / "outputs" / "招聘奖金与内推奖金自动核算模板_计算2次_累计口径修复版.xlsx"
MONTHLY_202510 = Path(os.environ.get("BONUS_MONTHLY_202510", PROJECT_ROOT / "outputs" / "monthly_202510.xlsx"))


def require_files(*paths: Path) -> None:
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        pytest.skip(f"local legacy workbook fixture not available: {', '.join(missing)}")


def test_reads_payroll_legacy_history_overrides():
    require_files(HISTORY_202509)
    overrides = load_history_overrides(HISTORY_202509)

    assert overrides.source_type == "薪酬组原线下累计表"
    assert len(overrides.by_key) >= 1950
    row = overrides.by_key["zt27669"]
    assert row["招聘人入职1月发放周期_覆盖"] == 202509
    assert row["招聘人入职1月发放金额_覆盖"] == 50


def test_merging_legacy_history_makes_202509_recruitment_match_payroll_total():
    require_files(MONTHLY_202509, HISTORY_202509)
    rows = read_import_rows(MONTHLY_202509)
    overrides = load_history_overrides(HISTORY_202509)
    merged_rows = merge_history_overrides(rows, overrides)

    result = calculate(merged_rows, load_rulebook(DEFAULT_RULE_WORKBOOK), allow_legacy_overrides=True)
    recruitment_total = round(sum(row["合计发放"] for row in result.recruitment_summary), 2)

    assert recruitment_total == 25353.05


def test_merging_legacy_history_routes_non_current_referrers_to_pending():
    require_files(MONTHLY_202509, HISTORY_202509)
    rows = read_import_rows(MONTHLY_202509)
    overrides = load_history_overrides(HISTORY_202509)
    merged_rows = merge_history_overrides(rows, overrides)

    result = calculate(merged_rows, load_rulebook(DEFAULT_RULE_WORKBOOK), allow_legacy_overrides=True)
    referral_total = round(sum(row["合计发放"] for row in result.referral_summary), 2)

    assert referral_total == 13850
    assert result.pending_confirmations


def test_reads_template_import_sheet_overrides_without_formula_cache():
    require_files(CUMULATIVE_TEMPLATE_202509)
    overrides = load_history_overrides(CUMULATIVE_TEMPLATE_202509)

    assert overrides.source_type == "模板导入覆盖字段"
    row = overrides.by_key["zt27669"]
    assert row["招聘人入职1月发放周期_覆盖"] == 202509
    assert row["招聘人入职1月发放金额_覆盖"] == 50


def test_legacy_history_keeps_referral_nodes_due_after_pending_statuses():
    require_files(MONTHLY_202510, HISTORY_202509)
    rows = read_import_rows(MONTHLY_202510)
    overrides = load_history_overrides(HISTORY_202509)
    merged_rows = merge_history_overrides(rows, overrides)

    result = calculate(merged_rows, load_rulebook(DEFAULT_RULE_WORKBOOK), allow_legacy_overrides=True)
    referral_total = round(sum(row["合计发放"] for row in result.referral_summary), 2)

    assert result.month == 202510
    assert referral_total == 13145


def test_developed_country_locations_override_imported_referral_region():
    require_files(MONTHLY_202510, HISTORY_202509)
    rows = read_import_rows(MONTHLY_202510)
    overrides = load_history_overrides(HISTORY_202509)
    merged_rows = merge_history_overrides(rows, overrides)

    result = calculate(merged_rows, load_rulebook(DEFAULT_RULE_WORKBOOK), allow_legacy_overrides=True)
    uk_detail = next(row for row in result.details if row.employee_no == "zt0021193")
    us_detail = next(row for row in result.details if row.employee_no == "zt0021267")

    assert uk_detail.referral_standard_bonus == 150
    assert uk_detail.referral_1m_bonus == 75
    assert us_detail.referral_standard_bonus == 150
    assert us_detail.referral_1m_bonus == 75


def test_fbu_czech_c1_matches_c_category_referral_rule():
    require_files(MONTHLY_202510, HISTORY_202509)
    rows = read_import_rows(MONTHLY_202510)
    overrides = load_history_overrides(HISTORY_202509)
    merged_rows = merge_history_overrides(rows, overrides)
    for row in merged_rows:
        if row.text("工号") == "zt0021323":
            row.values["特殊地区规则"] = "FBU捷克"

    result = calculate(merged_rows, load_rulebook(DEFAULT_RULE_WORKBOOK), allow_legacy_overrides=True)
    czech_detail = next(row for row in result.details if row.employee_no == "zt0021323")

    assert czech_detail.referral_rule_scope == "FBU捷克"
    assert czech_detail.referral_standard_bonus == 8000
    assert czech_detail.referral_6m_bonus == 8000


def test_fbu_referral_scope_requires_explicit_special_region_rule():
    germany_row = ImportRow(source_row=2, values={"工作地": "国外/德国/杜塞尔多夫"})
    czech_row = ImportRow(source_row=3, values={"工作地": "国外/捷克/乌斯季"})
    explicit_row = ImportRow(source_row=4, values={"工作地": "国外/英国/伯明翰", "特殊地区规则": "FBU德国"})

    assert _referral_scope(germany_row) == "集团统一"
    assert _referral_scope(czech_row) == "集团统一"
    assert _referral_scope(explicit_row) == "FBU德国"


def test_unmarked_fbu_location_is_flagged_for_referral_review():
    require_files(MONTHLY_202510, HISTORY_202509)
    rows = read_import_rows(MONTHLY_202510)
    overrides = load_history_overrides(HISTORY_202509)
    merged_rows = merge_history_overrides(rows, overrides)

    result = calculate(merged_rows, load_rulebook(DEFAULT_RULE_WORKBOOK), allow_legacy_overrides=True)
    czech_detail = next(row for row in result.details if row.employee_no == "zt0021239")

    assert czech_detail.referral_rule_scope == "集团统一"
    assert "工作地为德国/捷克，需确认是否适用FBU特殊内推规则" in czech_detail.exceptions


def test_entry_period_uses_full_month_minus_one_day():
    assert _period_after(datetime(2025, 9, 25), 1, 100) == 202510


def test_entry_period_is_blocked_when_employee_leaves_before_full_month():
    assert _period_after(datetime(2025, 9, 25), 1, 100, datetime(2025, 10, 10)) == "-"


def test_probation_period_is_blocked_when_employee_leaves_in_probation_month():
    assert _probation_period(datetime(2025, 10, 24), 100, datetime(2025, 10, 30)) == "-"


def test_missing_recruiter_status_moves_current_month_payment_to_pending():
    require_files(MONTHLY_202510, HISTORY_202509)
    rows = read_import_rows(MONTHLY_202510)
    overrides = load_history_overrides(HISTORY_202509)
    merged_rows = merge_history_overrides(rows, overrides)
    for row in merged_rows:
        row.values["招聘负责人人员状态"] = ""
        row.values["协助招聘人人员状态"] = ""

    result = calculate(merged_rows, load_rulebook(DEFAULT_RULE_WORKBOOK), allow_legacy_overrides=True)

    assert result.pending_confirmations
    assert any(row["奖金类型"] == "招聘奖金" and row["角色"] == "招聘负责人" for row in result.pending_confirmations)
    assert round(sum(row["合计发放"] for row in result.recruitment_summary), 2) == 0


def test_legacy_six_month_referral_marker_keeps_historical_full_amount():
    require_files(MONTHLY_202510, HISTORY_202509)
    rows = read_import_rows(MONTHLY_202510)
    overrides = load_history_overrides(HISTORY_202509)
    merged_rows = merge_history_overrides(rows, overrides)

    result = calculate(merged_rows, load_rulebook(DEFAULT_RULE_WORKBOOK), allow_legacy_overrides=True)
    detail = next(row for row in result.details if row.employee_no == "zt26894")

    assert detail.referral_probation_period == 202510
    assert detail.referral_probation_bonus == 1500


def test_high_grade_referrer_is_not_paid_referral_bonus():
    require_files(MONTHLY_202510, HISTORY_202509)
    rows = read_import_rows(MONTHLY_202510)
    overrides = load_history_overrides(HISTORY_202509)
    merged_rows = merge_history_overrides(rows, overrides)

    result = calculate(merged_rows, load_rulebook(DEFAULT_RULE_WORKBOOK), allow_legacy_overrides=True)
    detail = next(row for row in result.details if row.employee_no == "zt27805")

    assert detail.referral_standard_bonus == 600
    assert detail.referral_1m_bonus == 0
