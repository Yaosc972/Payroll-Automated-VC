from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "bonus_platform" / "static" / "index.html"
RECRUITMENT_HTML = ROOT / "bonus_platform" / "static" / "recruitment.html"
LABOR_HTML = ROOT / "bonus_platform" / "static" / "labor.html"
DOMESTIC_LABOR_HTML = ROOT / "bonus_platform" / "static" / "domestic-labor.html"
DOMESTIC_LABOR_JS = ROOT / "bonus_platform" / "static" / "domestic-labor.js"
OVERSEAS_LABOR_HTML = ROOT / "bonus_platform" / "static" / "overseas-labor.html"
OVERSEAS_LABOR_JS = ROOT / "bonus_platform" / "static" / "overseas-labor.js"
STYLES_CSS = ROOT / "bonus_platform" / "static" / "styles.css"
APP_JS = ROOT / "bonus_platform" / "static" / "app.js"
STORY_HTML = ROOT / "bonus_platform" / "static" / "vibecoding-story.html"
HEADER_LOGO = ROOT / "bonus_platform" / "static" / "assets" / "bonus-logo-header-blue.png"
DESKTOP_PACKAGE = ROOT / "desktop" / "package.json"
DESKTOP_ICON_PNG = ROOT / "desktop" / "assets" / "icon.png"
DESKTOP_ICON_ICO = ROOT / "desktop" / "assets" / "icon.ico"
DESKTOP_ICON_ICNS = ROOT / "desktop" / "assets" / "icon.icns"


def test_header_uses_blue_brand_asset_and_favicon_keeps_dark_asset():
    html = RECRUITMENT_HTML.read_text(encoding="utf-8")

    assert 'href="assets/bonus-logo-dark.png"' in html
    assert 'src="assets/bonus-logo-header-blue.png"' in html
    assert "Σ-Workbench" in html
    assert "西格玛工作台" in html
    assert "招聘奖金核算" in html
    assert "月度核算工作台" not in html


def test_header_branding_and_hero_title_have_dedicated_layout_rules():
    html = RECRUITMENT_HTML.read_text(encoding="utf-8")
    css = STYLES_CSS.read_text(encoding="utf-8")

    assert 'class="brand-logo"' in html
    assert 'class="hero-title ' in html
    assert ".brand-logo {" in css
    assert "box-shadow:" not in css.split(".brand-logo {", 1)[1].split("}", 1)[0]
    assert ".hero-title {" in css


def test_header_logo_background_is_truly_transparent():
    with Image.open(HEADER_LOGO) as logo:
        assert logo.mode == "RGBA"
        assert logo.getpixel((0, 0))[3] == 0


def test_monthly_calculation_ui_does_not_offer_history_upload():
    html = RECRUITMENT_HTML.read_text(encoding="utf-8")
    app_js = APP_JS.read_text(encoding="utf-8")

    assert "historyFileInput" not in html
    assert "历史奖金表" not in html
    assert "可选历史奖金表" not in html
    assert "historyFileInput" not in app_js
    assert 'form.append("history_file"' not in app_js


def test_command_center_table_replaces_limited_preview_tabs():
    html = RECRUITMENT_HTML.read_text(encoding="utf-8")
    app_js = APP_JS.read_text(encoding="utf-8")

    assert "tabulator-tables" in html
    assert 'id="commandTable"' in html
    assert 'id="globalSearch"' in html
    assert 'id="detailDrawer"' in html
    assert "/table-data" in app_js
    assert "new Tabulator" in app_js
    assert "最多展示前 50 行" not in html
    assert "previewTable" not in html


def test_command_center_uses_glass_toast_skeleton_and_collapsible_panels():
    html = RECRUITMENT_HTML.read_text(encoding="utf-8")
    css = STYLES_CSS.read_text(encoding="utf-8")
    app_js = APP_JS.read_text(encoding="utf-8")

    assert 'id="toggleRunsButton"' in html
    assert 'id="toggleFiltersButton"' in html
    assert 'id="toastRegion"' in html
    assert "backdrop-filter: blur(36px)" in css
    assert ".toast-region" in css
    assert ".table-loading" in css
    assert "showTableSkeleton" in app_js
    assert "showToast" in app_js
    assert "runs-collapsed" in app_js
    assert "filters-collapsed" in app_js


def test_command_center_uses_next_gen_minimal_glass_language():
    css = STYLES_CSS.read_text(encoding="utf-8")
    app_js = APP_JS.read_text(encoding="utf-8")

    assert "--neon-cyan" in css
    assert "--neon-violet" in css
    assert "brushed-metal" in css
    assert ".app-header" in css
    assert "rgba(255, 255, 255, 0.64)" in css
    assert "inner-edge-glow" in css
    assert ".run-status-orb" in css
    assert "linear-gradient(135deg, var(--neon-cyan), var(--neon-violet))" in css
    assert "run-status-orb" in app_js


def test_command_center_uses_premium_typography_system():
    css = STYLES_CSS.read_text(encoding="utf-8")

    assert "--font-sans" in css
    assert "--font-cjk" in css
    assert "--font-number" in css
    assert "-webkit-font-smoothing: antialiased" in css
    assert "text-rendering: geometricPrecision" in css
    assert "font-variant-numeric: tabular-nums" in css
    assert "--type-micro-tracking" in css
    assert "--weight-black" in css
    assert ".metric strong" in css
    assert "font-family: var(--font-number)" in css


def test_story_gallery_uses_large_single_row_demo_images():
    html = STORY_HTML.read_text(encoding="utf-8")

    assert "assets/story/mvp-platform-v2.png" in html
    assert "grid-template-columns: minmax(0, 1fr)" in html
    assert "height: auto" in html
    assert "min-height: 360px" in html


def test_portal_home_is_multi_module_entry_without_calculation_bootstrap():
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert "Welcome to Sigma Workbench" in html
    assert "Σ-WORKBENCH" in html
    assert "Recruitment Bonus Reconciliation" in html
    assert "招聘奖金核算" in html
    assert "Domestic Labor Vendor Payroll" in html
    assert "劳务工薪酬核算" in html
    assert "Overseas Labor Invoice Audit" in html
    assert "海外劳务工报账核对" in html
    assert 'href="recruitment.html"' in html
    assert 'href="domestic-labor.html"' in html
    assert 'href="overseas-labor.html"' in html
    assert "Available · 已上线" in html
    assert "app.js" not in html
    assert "tabulator-tables" not in html


def test_recruitment_page_keeps_command_center_and_home_link():
    html = RECRUITMENT_HTML.read_text(encoding="utf-8")

    assert 'href="/"' in html
    assert "返回首页" in html
    assert 'class="brand-block brand-home-link"' in html
    assert 'aria-label="返回西格玛工作台首页"' in html
    assert "app.js" in html
    assert 'id="commandTable"' in html
    assert "招聘奖金核算" in html


def test_labor_page_redirects_to_domestic_labor():
    html = LABOR_HTML.read_text(encoding="utf-8")

    assert 'http-equiv="refresh"' in html
    assert "domestic-labor.html" in html
    assert "window.location.replace" in html


def test_domestic_labor_page_is_payroll_workbench():
    html = DOMESTIC_LABOR_HTML.read_text(encoding="utf-8")
    js = DOMESTIC_LABOR_JS.read_text(encoding="utf-8")

    assert "劳务工薪酬核算" in html
    assert "domestic-labor-shell" in html
    assert "kpi-6col" in html
    assert "domestic-labor.js" in html
    assert "/api/domestic-labor/runs" in js
    assert "/api/domestic-labor/templates" in js
    assert 'id="wizardDrawer"' not in html
    assert 'id="drawerOverlay"' not in html
    assert 'id="btnOpenDrawer"' not in html
    assert 'id="engineCardGrid"' not in html
    assert "New Payroll Task" not in html
    assert "新建计算任务" not in html
    assert "下载报告" not in html
    assert "刷新状态" not in html


def test_domestic_labor_meal_workbench_static_labels():
    html = DOMESTIC_LABOR_HTML.read_text(encoding="utf-8")
    js = DOMESTIC_LABOR_JS.read_text(encoding="utf-8")

    assert "国内劳务薪酬中台" in html
    assert "餐补核算批次" in html
    assert 'id="canbuBatchMonth"' in html
    assert 'id="canbuBatchModal"' in html
    assert 'id="btnConfirmCanbuBatch"' in html
    assert 'id="calcModal"' in html
    assert "核算月份" in html
    assert "数据上传" in js
    assert "字段检查" in js
    assert "餐补核算" in js
    assert "导出结果" in js
    assert "导出作为结果页动作" in js
    assert "导出归档" not in js
    assert "异常复核" not in html


def test_domestic_labor_export_button_shows_progress_and_respects_reduced_motion():
    html = DOMESTIC_LABOR_HTML.read_text(encoding="utf-8")
    js = DOMESTIC_LABOR_JS.read_text(encoding="utf-8")

    assert 'class="btn-primary btn-export" id="btnExportCanbu"' in js
    assert "state.exportInProgress" in js
    assert "正在生成 Excel" in js
    assert "Excel 已生成" in js
    assert "dl-export-button-dots" in js
    assert ".btn-export.is-exporting" in html
    assert ".btn-export.is-exported" in html
    assert "@media (prefers-reduced-motion: reduce)" in html


def test_domestic_labor_housing_allowance_workbench_is_available():
    html = DOMESTIC_LABOR_HTML.read_text(encoding="utf-8")
    js = DOMESTIC_LABOR_JS.read_text(encoding="utf-8")

    assert "当前开放全勤奖、餐费补贴、外宿补贴、工龄奖、岗位补贴、高温补贴与夜班补贴核算" in html
    assert "外宿补贴核算" in html
    assert '<span class="dl-subject-kicker">Housing Allowance</span>' in html
    assert 'class="dl-subject-card primary" data-subject-entry="waisu_butie"' in html
    assert "按实际入住、退宿日期和缺勤口径核算" in html
    assert "subject === 'canbu' || subject === 'waisu_butie'" in js
    assert "form.append('engines', batch.subject)" in js
    assert "el.batchNameText.textContent = batch.name" in js
    assert "el.chromeRunBadge.hidden = !batch.runId" in js
    assert "batch.runId.slice(-8)" in js
    assert "if (subject === 'waisu_butie') return results.filter(hasWaisuReviewIssue).length" in js
    assert "住宿名单字段" in js
    assert "应发外宿补贴" in js


def test_domestic_labor_subject_cards_show_operation_and_all_region_scope():
    html = DOMESTIC_LABOR_HTML.read_text(encoding="utf-8")
    js = DOMESTIC_LABOR_JS.read_text(encoding="utf-8")
    card_grid = html.split('id="subjectCardGrid"', 1)[1].split('</div>', 1)[0]

    assert html.count('class="dl-subject-line-tag">操作线</span>') == 5
    assert html.count('class="dl-subject-line-tag">全区域</span>') == 2
    assert "全勤奖核算" in html
    assert "餐费补贴核算" in html
    assert "岗位补贴核算" in html
    assert "高温补贴核算" in html
    assert "夜班补贴核算" in html
    assert "外宿补贴核算" in html
    assert "工龄奖核算" in html
    assert html.count('disabled aria-disabled="true"') == 0
    assert 'data-subject-entry="gangwei_butie"' in html
    assert 'data-subject-entry="gaowen_butie"' in html
    assert 'data-subject-entry="yeban_butie"' in html
    assert 'class="dl-subject-card primary validating" data-subject-entry="gangwei_butie"' in html
    assert 'class="dl-subject-card primary validating" data-subject-entry="gaowen_butie"' in html
    assert 'class="dl-subject-card primary validating" data-subject-entry="yeban_butie"' in html
    assert '<span class="dl-subject-status-tag">验证中</span>' in html
    assert ".dl-subject-card.primary.validating" in html
    assert "#FFF7E6" in html
    assert "平台内置班次休息表，晋江额外排除人员按月确认" in html
    assert "班次休息表、地区岗位、晋江特殊名单和连班登记" not in html
    assert "btnSaveNightShiftBreaks" in js
    assert "复制上月晋江名单" in js
    assert "确认本月无额外排除人员" in js
    assert "计件岗、门禁由系统自动排除" in js
    assert "晋江不享有夜班补贴人员名单" in js
    assert "晚上休息扣除" in js
    assert "早上休息扣除" in js
    assert "休息扣除合计" in js
    assert 'data-shift-field="break_category_${number}"' in js
    assert "地区岗位范围" not in js
    assert "连班登记" not in js
    assert "核算合计（含暂算）" in js
    assert "暂算需确认日" in js
    assert "异常未计金额日" in js
    assert "金额已核算" in js
    assert "需处理事项" in js
    assert "有未核算日" not in js
    assert "本月核算结果" in js
    assert "需要处理的日期" in js
    assert "员工缺勤（考勤异常）" in js
    assert "补充当天上下班打卡" not in js
    assert "只计算22:00至次日08:00内的有效时长" in js
    assert "Calculation explanation" not in html
    assert "review_calculated_days" in js
    assert ".dl-subject-line-tag" in html
    assert "· 已开放" not in card_grid
    assert "· 待开发" not in card_grid
    assert "· 待确认规则" not in card_grid

    subject_order = [
        "canbu",
        "quanqinjiang",
        "waisu_butie",
        "gonglingjiang",
        "gangwei_butie",
        "gaowen_butie",
        "yeban_butie",
    ]
    positions = [html.index(f'data-subject-entry="{subject}"') for subject in subject_order]
    assert positions == sorted(positions)


def test_domestic_labor_home_description_stays_on_one_line_on_desktop():
    html = DOMESTIC_LABOR_HTML.read_text(encoding="utf-8")
    desktop_rule = html.split(".dl-subject-desc {", 1)[1].split("}", 1)[0]
    responsive_rule = html.split("@media (max-width: 1180px)", 1)[1].split("@media (max-width: 760px)", 1)[0]

    assert "max-width: none" in desktop_rule
    assert "white-space: nowrap" in desktop_rule
    assert ".dl-subject-desc { white-space: normal; }" in responsive_rule


def test_domestic_labor_attendance_bonus_workbench_is_available():
    html = DOMESTIC_LABOR_HTML.read_text(encoding="utf-8")
    js = DOMESTIC_LABOR_JS.read_text(encoding="utf-8")

    assert 'class="dl-subject-card primary" data-subject-entry="quanqinjiang"' in html
    assert '<span class="dl-subject-kicker">Attendance Bonus</span>' in html
    assert "subject === 'quanqinjiang'" in js
    assert "全勤奖数据 Excel" in js
    assert "全勤判断字段" in js
    assert "renderQuanqinResults" in js
    assert "应发全勤奖" in js


def test_domestic_labor_position_allowance_explains_july_rule_source_without_blocking():
    js = DOMESTIC_LABOR_JS.read_text(encoding="utf-8")

    assert "岗位补贴标准以2026年7月确认规则为依据" in js
    assert "实际在职工作日天数" in js
    assert "自动计算入离职缺勤时数" in js
    assert "month < '2026-07'" not in js


def test_domestic_labor_attendance_bonus_card_uses_subject_level_summary():
    html = DOMESTIC_LABOR_HTML.read_text(encoding="utf-8")

    assert "按入离职、缺勤、迟到早退和签卡等考勤口径核算，固定标准100元。" in html
    assert "迟到豁免二选一：6分钟内最多3次" not in html


def test_domestic_labor_does_not_show_identified_fields_before_upload():
    js = DOMESTIC_LABOR_JS.read_text(encoding="utf-8")

    assert "if (step !== 'upload' && !batch.runId) step = 'upload';" in js
    assert "const available = stepItem.key === 'upload' || Boolean(batch?.runId);" in js
    assert "disabled aria-disabled=\"true\"" in js
    assert "if (button.disabled || button.getAttribute('aria-disabled') === 'true') return;" in js


def test_domestic_labor_uses_current_workbench_logo_for_browser_icon():
    html = DOMESTIC_LABOR_HTML.read_text(encoding="utf-8")

    assert 'rel="icon" type="image/png" sizes="512x512" href="assets/workbench-logo-2026.png?v=20260806"' in html
    assert 'rel="apple-touch-icon" href="assets/workbench-logo-2026.png?v=20260806"' in html
    assert 'href="assets/bonus-logo-dark.png"' not in html


def test_domestic_labor_home_exposes_versioned_verified_rule_package():
    html = DOMESTIC_LABOR_HTML.read_text(encoding="utf-8")
    js = DOMESTIC_LABOR_JS.read_text(encoding="utf-8")

    assert 'id="navRulePackage"' in html
    assert 'id="rulePackageEntry"' in html
    assert 'id="rulePackageView"' in html
    assert 'id="rulePackageCategoryTabs"' in html
    assert 'id="rulePackageVersionSelect"' in html
    assert "DL-PAYROLL.v1.4.0" in html
    assert "已验证规则 4 项 · 验证中规则 3 项" in html
    assert "/api/domestic-labor/rule-package" in js
    assert "renderRulePackage" in js
    assert "data-rule-category" in js
    assert "data-rule-subject" in js
    assert "核算规则包" in html
    assert "当前版本 1.4.0" in html
    assert "字段计算公式" in js
    assert "renderRuleFieldCalculations" in js
    assert "RULE PACKAGE · CURRENT" not in html
    assert "position: absolute" in html.split(".dl-rule-package-entry {", 1)[1].split("}", 1)[0]


def test_overseas_labor_page_is_separate_audit_workbench():
    html = OVERSEAS_LABOR_HTML.read_text(encoding="utf-8")
    js = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")
    css = STYLES_CSS.read_text(encoding="utf-8")

    assert "海外劳务工报账核对" in html
    assert "AI 抽取供应商发票" in html
    assert "overseas-labor.js" in html
    assert "/api/labor/runs" in js
    assert "字段映射" in html
    assert "结论" in html
    assert "仓库核对总览" in html
    assert ".overseas-labor-shell" in css


def test_desktop_builder_uses_platform_logo_icons():
    package = DESKTOP_PACKAGE.read_text(encoding="utf-8")

    assert '"icon": "assets/icon.icns"' in package
    assert '"icon": "assets/icon.ico"' in package
    assert DESKTOP_ICON_ICNS.exists()
    assert DESKTOP_ICON_ICO.exists()
    with Image.open(DESKTOP_ICON_PNG) as icon:
        assert icon.size == (512, 512)
        assert icon.mode == "RGBA"
