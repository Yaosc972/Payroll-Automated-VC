from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
FBU_HTML = ROOT / "bonus_platform" / "static" / "fbu-performance.html"
FBU_JS = ROOT / "bonus_platform" / "static" / "fbu-performance.js"
FBU_LOGO = ROOT / "bonus_platform" / "static" / "assets" / "sigma-platform-logo-20260731.png"


def test_local_file_entry_redirects_to_running_workbench():
    html = FBU_HTML.read_text(encoding="utf-8")

    assert "window.location.protocol === 'file:'" in html
    assert "window.location.replace(`http://127.0.0.1:8003/fbu-performance.html${window.location.hash}`)" in html


def test_attendance_step_has_non_blocking_hourly_rate_policy_controls():
    html = FBU_HTML.read_text(encoding="utf-8")
    js = FBU_JS.read_text(encoding="utf-8")

    assert "周期适用时薪" in js
    assert "核算口径（点击修改）" in js
    assert "按实际班次" in js
    assert "统一用白班时薪" in js
    assert "统一用夜班时薪" in js
    assert "仅调整该双周工资周期采用的计薪时薪" not in js
    assert js.count('class="hourly-rate-policy-help-line"') == 4
    assert "<strong>其他计薪：</strong>" in js
    assert 'role="tooltip"' in js
    assert "aria-pressed=" in js
    assert "applyHourlyRatePolicyOptimistically(activity, action, payload)" in js
    assert "保存中…" in js
    assert "await enterActivity(activity.run_id" not in js.split(
        "async function updateHourlyRatePolicy", 1
    )[1].split("function setHourlyRatePolicy", 1)[0]
    assert "添加特殊人员" in js
    assert "恢复全部建议" in js
    assert "搜索工号、姓名、部门" in js
    assert "setHourlyRatePolicyShiftFilter" in js
    assert "人工调整" in js
    assert "renderHourlyRatePolicySection(activity)" in js
    attendance_section = js.split("function renderAttendanceStep(activity)", 1)[1].split(
        "function renderSalaryStep(activity)", 1
    )[0]
    assert "renderHourlyRatePolicySection(activity)" in attendance_section
    assert "必须确认" not in attendance_section
    assert ".hourly-rate-policy-options" in html
    policy_button_css = html.split(
        ".hourly-rate-policy-options .workbench-segment {", 1
    )[1].split("}", 1)[0]
    assert "border: 1px solid #cbd5e1;" in policy_button_css
    assert "border-radius: 6px;" in policy_button_css
    assert ".hourly-rate-policy-help:hover .hourly-rate-policy-help-content" in html
    assert ".hourly-rate-policy-help:focus-within .hourly-rate-policy-help-content" in html


def test_attendance_section_navigation_stays_compact_on_the_right():
    html = FBU_HTML.read_text(encoding="utf-8")

    layout_css = html.split(".attendance-review-layout {", 1)[1].split("}", 1)[0]
    nav_css = html.split(".attendance-section-nav {", 1)[1].split("}", 1)[0]

    assert "grid-template-columns: minmax(0, 1fr) 86px;" in layout_css
    assert "position: sticky;" in nav_css
    assert "width: 86px;" in nav_css
    assert ".attendance-section-nav-button:focus-visible" in html
    assert "@media (max-width: 760px)" in html


def test_salary_step_has_optional_single_record_period_adjustment():
    html = FBU_HTML.read_text(encoding="utf-8")
    js = FBU_JS.read_text(encoding="utf-8")

    assert "绩效基数补发差额" in js
    assert "正数补发、负数扣回" in js
    assert "统一按本次核算月比例和系数计算" in js
    assert "renderPeriodAdjustmentSection(activity)" in js
    assert "/period-adjustments" in js
    assert "editPeriodAdjustment" in js
    assert "deletePeriodAdjustment" in js
    assert ".period-adjustment-form" in html
    assert "validatePeriodAdjustmentDraft" in js
    assert "focusFirstPeriodAdjustmentError" in js
    assert "当月薪资档案中未找到该工号" in js
    assert "请填写调整原因" in js
    assert "请完整填写工号、调整额、归属月份和原因" not in js
    assert 'aria-invalid="true"' in js
    assert "workbench-field-error" in html
    assert "请先上传当月薪资档案" in js
    assert "duplicateToast" in js


def test_period_adjustment_is_compact_under_fixed_base_list():
    html = FBU_HTML.read_text(encoding="utf-8")
    js = FBU_JS.read_text(encoding="utf-8")
    salary_area = js.split("function renderSalaryStep", 1)[1].split(
        "function renderPerformanceStep", 1
    )[0]
    adjustment_area = js.split("function renderPeriodAdjustmentSection", 1)[1].split(
        "function renderSalarySummaryTable", 1
    )[0]

    assert '<div class="salary-support-stack">' in salary_area
    assert salary_area.index("renderMaintainedRuleList('fixedBase', activity)") < salary_area.index(
        "renderPeriodAdjustmentSection(activity)"
    )
    assert salary_area.count("renderPeriodAdjustmentSection(activity)") == 1
    assert 'class="period-adjustment-section period-adjustment-compact"' in adjustment_area
    assert "<details" in adjustment_area
    assert "period-adjustment-records" in adjustment_area
    assert ".period-adjustment-compact" in html
    assert ".salary-support-stack" in html
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in html


def test_fbu_navigation_lives_in_top_bar_with_logo():
    html = FBU_HTML.read_text(encoding="utf-8")

    body = html.split("<body>", 1)[1]
    top_bar_markup = body.split('<header class="top-bar">', 1)[1].split("<!-- Content Area -->", 1)[0]

    assert '<aside class="sidebar">' not in body
    assert '<a class="top-module-copy top-title-lockup" href="/" aria-label="返回西格玛工作台首页">' in top_bar_markup
    assert "onclick=\"navigateTo('activities')\"" not in top_bar_markup
    assert 'class="top-title-logo"' in top_bar_markup
    assert "assets/sigma-platform-logo-20260731.png" in top_bar_markup
    assert 'href="assets/sigma-platform-logo-20260731.png"' in html.split("</head>", 1)[0]
    assert "text-decoration: none;" in html.split(".top-title-lockup {", 1)[1].split("}", 1)[0]
    assert 'class="top-module-nav"' in top_bar_markup
    assert 'data-page="workbench"' in top_bar_markup
    assert 'data-page="activities"' in top_bar_markup
    assert "FBU核算" in top_bar_markup
    assert "活动列表" in top_bar_markup
    assert ".top-module-nav .nav-item.active" in html
    assert ".main-content," in html
    assert "body.sidebar-collapsed .main-content" in html
    assert "margin-left: 0;" in html
    assert "min-width: 0;" in html.split(".step-section {", 1)[1].split("}", 1)[0]
    assert "overflow-x: auto;" in html.split(".final-results .data-table-container {", 1)[1].split("}", 1)[0]
    assert ".top-bar {\n\t        display: flex;" in html
    assert "justify-content: space-between;" in html


def test_fbu_platform_logo_has_transparent_background():
    with Image.open(FBU_LOGO) as logo:
        assert logo.mode == "RGBA"
        assert logo.size == (512, 512)
        assert logo.getpixel((0, 0))[3] == 0


def test_workbench_empty_state_uses_compact_illustration():
    html = FBU_HTML.read_text(encoding="utf-8")
    js = FBU_JS.read_text(encoding="utf-8")

    assert "workbench-empty-illustration" in html
    assert "workbench-empty-illustration" in js
    assert "创建本月活动后，再导入花名册、考勤、薪资和绩效数据。" in js
    assert "grid" in html.split(".workbench-empty {", 1)[1].split("}", 1)[0]
