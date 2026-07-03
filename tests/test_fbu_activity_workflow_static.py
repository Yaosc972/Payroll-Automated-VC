from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FBU_HTML = ROOT / "bonus_platform" / "static" / "fbu-performance.html"
FBU_JS = ROOT / "bonus_platform" / "static" / "fbu-performance.js"


def _html() -> str:
    return FBU_HTML.read_text(encoding="utf-8")


def _js() -> str:
    return FBU_JS.read_text(encoding="utf-8")


def test_activity_detail_uses_six_plain_language_steps():
    js = _js()

    for label in ["人员核对", "考勤工时", "薪资数据", "绩效数据", "核算检查", "确认导出"]:
        assert label in js

    assert "const ACTIVITY_STEPS" in js
    assert "function setActivityStep" in js
    assert "function renderActivityStepper" in js
    assert "activity-step-summary" in js


def test_sidebar_does_not_contain_fbu_workflow_entries():
    html = _html()
    sidebar = html.split('<aside class="sidebar"', 1)[1].split("</aside>", 1)[0]

    for forbidden in ["考勤汇总", "薪资匹配", "绩效明细", "核算结果", "异常队列", "基础数据"]:
        assert forbidden not in sidebar

    assert 'data-page="activities"' in sidebar
    assert 'data-page="workbench"' in sidebar


def test_upload_entries_are_owned_by_exactly_one_step():
    js = _js()

    assert "const STEP_MATERIALS" in js
    for key in [
        "roster",
        "attendance",
        "previousAttendance",
        "supplementalLeave",
        "salary",
        "adjustments",
        "performance",
    ]:
        assert js.count(f"materialKey: '{key}'") == 1

    for copy in [
        "上传OEHR当月考勤日报表",
        "上传OEHR上月考勤日报表",
        "上传线下sickpay与年假补充数据",
        "上传OEHR最新薪资档案（含离职）",
        "上传OEHR转正调薪流程",
        "上传OEHR当月绩效报表",
    ]:
        assert copy in js


def test_maintained_lists_replace_rule_upload_in_activity_flow():
    html = _html()
    js = _js()

    assert "workbenchUploadBaseOverrides" not in html
    assert "function renderMaintainedRuleList" in js
    assert "function confirmMaintainedRuleList" in js
    assert "96工时制员工" in js
    assert "固定基数人员" in js
    assert "确认名单" in js
    assert "管理名单" in js


def test_no_banned_words_in_workbench_user_copy():
    combined = _html() + "\n" + _js()
    user_copy_regions = [
        "ACTIVITY_STEPS",
        "STEP_MATERIALS",
        "renderActivityStepper",
        "renderStepHeader",
        "renderNeedsPanel",
        "renderFinalResultRow",
        "renderFinalCalculationDetail",
    ]

    snippets = []
    for marker in user_copy_regions:
        if marker in combined:
            snippets.append(combined.split(marker, 1)[1][:4000])
    searchable = "\n".join(snippets)

    for forbidden in ["诊断", "阻断项", "审计记录", "人工确认项", "口径", "链路", "规则命中", "来源映射", "异常记录"]:
        assert forbidden not in searchable


def test_special_person_tags_are_rendered_near_name():
    js = _js()

    assert "function getSpecialPersonTags" in js
    assert "function renderNameWithTags" in js
    for label in ["区长", "96工时制", "固定基数", "存在调薪", "离职发放"]:
        assert label in js
    assert "person-tag" in js


def test_final_table_freezes_only_employee_id_and_name():
    html = _html()
    js = _js()

    assert ".sticky-employee-id" in html
    assert ".sticky-employee-name" in html
    assert ".sticky-bonus" not in html
    assert "sticky-bonus" not in js
