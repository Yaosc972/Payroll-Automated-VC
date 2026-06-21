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


def test_recruitment_page_removes_difference_review_workflow():
    html = RECRUITMENT_HTML.read_text(encoding="utf-8")
    app_js = APP_JS.read_text(encoding="utf-8")

    for removed_copy in [
        "差异复核",
        "上传线下表做差异检验",
        "生成差异报告",
        "选择线下/复核 Excel",
        "只看差异",
        "差异概览",
    ]:
        assert removed_copy not in html
        assert removed_copy not in app_js

    assert 'data-step="compare"' not in html
    assert "offlineInput" not in app_js
    assert "compareRun" not in app_js
    assert "diffSummary" not in app_js
    assert "原始导入、初算结果、待确认表和最终结果" in html


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
    assert ".run-status-orb" not in css
    assert "run-status-orb" not in app_js
    assert "runsCollapsed: true" in app_js
    assert "syncRunsPanelState" in app_js


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


def test_recruitment_header_has_user_menu():
    html = RECRUITMENT_HTML.read_text(encoding="utf-8")
    css = STYLES_CSS.read_text(encoding="utf-8")

    assert 'class="workbench-user-menu"' in html
    assert "姚硕灿" in html
    assert "系统管理员" in html
    assert "进入后台管理" in html
    assert "退出登录" in html
    assert ".workbench-user-menu" in css
    assert ".user-menu-panel" in css
    assert ".header-copy::before" in css
    assert "background-size: 1px 10px" in css


def test_recruitment_template_download_lives_in_step_one_card():
    html = RECRUITMENT_HTML.read_text(encoding="utf-8")
    css = STYLES_CSS.read_text(encoding="utf-8")

    header_actions = html.split('<div class="header-actions">', 1)[1].split("</div>", 1)[0]
    assert "下载导入模板" not in header_actions
    assert "Step 1-2" in html
    assert 'class="template-inline-button"' in html
    assert 'href="/api/template?v=20260608"' in html
    assert ".template-inline-button" in css


def test_labor_page_redirects_to_domestic_labor():
    html = LABOR_HTML.read_text(encoding="utf-8")

    assert 'http-equiv="refresh"' in html
    assert "domestic-labor.html" in html
    assert "window.location.replace" in html


def test_domestic_labor_page_is_payroll_workbench():
    html = DOMESTIC_LABOR_HTML.read_text(encoding="utf-8")
    js = DOMESTIC_LABOR_JS.read_text(encoding="utf-8")
    css = STYLES_CSS.read_text(encoding="utf-8")

    assert "劳务工薪酬核算" in html
    assert "domestic-labor-shell" in html
    assert "kpi-6col" in html
    assert "engine-card-grid" in html
    assert "wizard-drawer" in html
    assert "domestic-labor.js" in html
    assert "/api/domestic-labor/runs" in js
    assert "/api/domestic-labor/templates" in js
    assert ".engine-card {" in css
    assert ".kpi-6col" in css


def test_overseas_labor_page_is_separate_audit_workbench():
    html = OVERSEAS_LABOR_HTML.read_text(encoding="utf-8")
    js = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")
    css = STYLES_CSS.read_text(encoding="utf-8")

    assert "海外劳务工报账核对" in html
    assert "上传供应商发票和账单，自动核对总金额与员工明细" in html
    assert "overseas-labor.js" in html
    assert "/api/labor/runs" in js
    assert "字段映射" in html
    assert "结论" in html
    assert "仓库核对总览" in html
    assert ".overseas-labor-shell" in css


def test_overseas_labor_visible_copy_avoids_technical_diagnostics_terms():
    html = OVERSEAS_LABOR_HTML.read_text(encoding="utf-8")
    js = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")

    assert "选择测试材料验证 · 不影响正式数据" in html
    assert "识别情况与仓库总览" in html
    assert "识别情况明细" in js
    assert "明细识别" in js
    for phrase in [
        "AI 抽取供应商发票",
        "不写入规则",
        "质量诊断与仓库概览",
        "技术诊断与抽取指标",
        "抽取方法",
        "规则 ${methods.rule",
        "AI ${Number(methods.ai_text",
        "置信度分布",
        "低置信度",
        "极低置信度",
        "PDF vs Excel",
    ]:
        assert phrase not in html
        assert phrase not in js


def test_overseas_labor_material_trial_area_uses_business_copy():
    html = OVERSEAS_LABOR_HTML.read_text(encoding="utf-8")
    js = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")

    assert "测试材料验证" in html
    assert "选择测试材料验证 · 不影响正式数据" in html
    assert "测试材料验证" in js
    assert "样例材料" not in html
    assert "样例材料" not in js
    assert "总账结论" in js
    assert "待确认原因" in js
    assert "生成测试报告" in js
    for internal_copy in [
        "参考材料索引",
        "正在扫描参考材料",
        "等待加载参考材料",
        "试跑",
        "转为正式批次",
        "正式批次后",
        "只读建议",
        "主路径",
        "需创建批次后预览确认",
        "创建正式批次",
        "测试验证交付检查",
        "PDF 合并员工行复核",
        "预计修复异常",
        "可预览",
    ]:
        assert internal_copy not in html
        assert internal_copy not in js


def test_overseas_labor_material_trial_result_copy_avoids_internal_workflow_terms():
    js = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")

    assert "测试材料验证检查" in js
    assert "待确认原因" in js
    assert "图片发票明细待确认" in js
    assert "查看原始发票" in js
    assert "正式核对时确认" in js
    for internal_copy in [
        "图片识别复核",
        "合并行复核",
        "跨仓归属复核",
        "复核路径",
        "试跑",
        "转为正式批次",
        "正式批次后",
        "需按仓复核",
        "创建批次后复核",
        "缓存可复核",
        "确认前必须预览",
        "等待批次预览",
        "等待正式批次",
        "确认前先查看影响",
        "历史识别可复核",
        "先完成图片识别影响预览",
    ]:
        assert internal_copy not in js


def test_overseas_labor_material_name_match_cards_use_business_confidence_labels():
    js = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")

    assert 'const isHighConfidence = candidate.confidence === "high";' in js
    assert 'const confidenceLabel = isHighConfidence ? "把握较高" : "需业务确认";' in js
    assert "${escapeHtml(confidenceLabel)}</span>" in js
    assert '${escapeHtml(confidence)}</span>' not in js
    assert 'candidate.confidence === "high" ? "high" : "medium"' not in js


def test_overseas_labor_employee_detail_area_is_business_report_oriented():
    html = OVERSEAS_LABOR_HTML.read_text(encoding="utf-8")
    js = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")

    assert "识别证据概览" in html
    assert "用于判断发票明细是否识别完整；完整核对结果见下方员工明细" in html
    assert "生成核对报告" in html
    assert "暂无识别证据" in html
    assert "完成字段映射后，点击「生成核对报告」开始核对" in html
    assert "已识别发票明细" in js
    assert "识别金额合计" in js
    assert "识别工时合计" in js
    assert "本区是识别证据概览，不作为最终员工核对结论" in js
    assert "<th>识别完整度</th>" in js
    assert "<th>来源位置</th>" in js
    assert "<th>原文依据</th>" in js
    assert "完整员工明细" in html
    assert "页面已展示" in js
    assert "下载报告查看" not in js
    assert "页面只展示最需要处理" not in js
    for phrase in ["员工明细识别情况", "暂无员工明细", "员工级核对证据", "抽取并比对", "暂无抽取数据", "抽取员工行", "抽取金额合计", "抽取工时合计", "<th>置信度</th>", "<th>证据</th>", "完整明细以下载报告为准"]:
        assert phrase not in html
        assert phrase not in js
    assert "生成核对结果" not in html
    assert "生成核对结果" not in js


def test_overseas_labor_main_flow_uses_business_copy_instead_of_extraction_jargon():
    html = OVERSEAS_LABOR_HTML.read_text(encoding="utf-8")
    js = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")

    assert "辅助识别和解释异常" in html
    assert "此处显示账单样例" in html
    assert "字段映射已确认，可以生成核对报告" in js
    assert "正在生成核对报告，页面会自动刷新" in js
    assert "请重新点击「生成核对报告」重试" in js
    for phrase in [
        "PDF/AI 抽取",
        "此处显示数据预览",
        "可以开始抽取比对",
        "已提交后台抽取",
        "后台抽取中",
        "抽取任务中断",
        "抽取失败。",
        "抽取并核对",
    ]:
        assert phrase not in html
        assert phrase not in js


def test_overseas_labor_frontend_blocks_vercel_light_uat_extract():
    js = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")

    assert "isVercelLaborLightUat" in js
    assert "当前 Vercel UAT 仅支持页面试用和测试材料验证" in js
    assert "不启动正式在线核对任务" in js


def test_overseas_labor_frontend_maps_technical_request_errors_to_business_next_steps():
    js = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")

    assert "function formatLaborRequestError" in js
    assert "message?.message" in js
    assert "message?.nextAction" in js
    assert "本批次记录未找到" in js
    assert "请返回「新建核对批次」重新创建并上传材料" in js
    assert "上传文件未保存成功" in js
    assert "无法连接当前服务" in js
    assert "formatLaborRequestError(data.detail || data.message || \"请求失败。\")" in js
    assert "系统找不到本批次文件" in js
    assert "重新上传 PDF 发票和 Excel 账单后再生成核对报告" in js
    assert "服务返回内容异常" in js

    failure_formatter = js.split("function formatLaborFailureMessage", 1)[1].split(
        "function businessStageLabel", 1
    )[0]
    assert "formatLaborRequestError(run?.errorMessage" in failure_formatter
    assert "const message = run?.errorMessage" not in failure_formatter


def test_overseas_labor_download_prefers_business_report_for_business_users():
    js = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")

    assert "function preferredLaborReportDownloadUrl(run)" in js
    assert "run?.businessReportDownloadUrl || run?.files?.businessReport?.downloadUrl || run?.diffDownloadUrl" in js
    assert "setDownload(preferredLaborReportDownloadUrl(run))" in js


def test_overseas_labor_result_guides_business_report_download_and_excel_detail_download():
    js = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")

    assert "renderConclusion(summary, wcSummary, run.extractionQuality, run)" in js
    assert "业务报告已生成，可下载留档或转发给业务确认。" in js
    assert "下载业务报告" in js
    assert "下载 Excel 明细" in js
    assert "内部差异 Excel" not in js
    assert "buildBusinessReportPrompt(run)" in js


def test_overseas_labor_result_conclusion_prioritizes_total_amount_for_business():
    js = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")

    assert "buildBusinessConclusion(summary, wcSummary, run)" in js
    assert "const roundedDelta = Math.round(Math.abs(amountDeltaTotal) * 100) / 100;" in js
    assert "return roundedDelta <= LABOR_TOTAL_AMOUNT_TOLERANCE;" in js
    assert "typeof wcSummary.totalPassed === \"boolean\"" not in js
    assert "总账通过" in js
    assert "总账通过，但员工明细待确认" in js
    assert "总金额存在差异，暂不能放行" in js
    assert "由于员工明细未完整识别" in js
    assert "请先查看下方员工明细中的金额、工时或费率差异" in js
    assert "detailRowsIncomplete" in js
    assert "系统已确认本批总金额一致" in js
    assert "PDF 比 Excel 多" in js
    assert "PDF 比 Excel 少" in js


def test_overseas_labor_page_explains_three_amount_layers_in_business_language():
    js = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")

    assert "总金额核对" in js
    assert "金额口径说明" not in js
    assert "整批 PDF" in js
    assert "整批 Excel" in js
    assert "已识别员工明细金额" in js
    assert "员工明细金额用于定位差异，不等同于整批总账金额" in js
    assert "不代表账单少读了" in js
    assert "当前页面只展开了用于确认的明细范围" in js
    assert "总账结论优先看整批 PDF 与整批 Excel 的差额" in js


def test_overseas_labor_conclusion_amounts_fall_back_to_summary_when_warehouse_totals_missing():
    js = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")

    assert "Number(wcSummary?.amountDeltaTotal ?? summary?.amountDeltaTotal ?? 0)" in js
    assert "Number(wcSummary?.pdfAmountTotal ?? summary?.pdfAmountTotal ?? 0)" in js
    assert "Number(wcSummary?.excelAmountTotal ?? summary?.excelAmountTotal ?? 0)" in js
    assert "const amountDeltaTotal = wcSummary ? wcSummary.amountDeltaTotal || 0 : 0;" not in js
    assert "const pdfAmountTotal = wcSummary ? Math.abs(wcSummary.pdfAmountTotal || 0) : 0;" not in js
    assert "const excelAmountTotal = wcSummary ? Math.abs(wcSummary.excelAmountTotal || 0) : 0;" not in js


def test_overseas_labor_total_pass_detail_confirmation_does_not_always_claim_incomplete_recognition():
    js = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")

    assert "const detailConfirmationMessage = detailRowsIncomplete" in js
    assert "系统已确认本批总金额一致，但部分员工明细未完整识别，员工级差异仅供确认，不能直接作为最终员工明细结论。" in js
    assert "系统已确认本批总金额一致，但员工明细仍有需要确认的项目。" in js
    assert "员工级差异仅供确认，不能直接作为最终员工明细结论。" in js
    assert "detailRowsIncomplete" in js
    assert "detailScope" in js
    assert "message: detailConfirmationMessage" in js
    assert 'message: "系统已确认本批总金额一致，但部分员工明细未完整识别。"' not in js


def test_overseas_labor_total_pass_uses_single_tolerance_helper():
    js = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")

    assert "const LABOR_TOTAL_AMOUNT_TOLERANCE = 0.1;" in js
    assert "function isLaborTotalAmountPassed(summary, wcSummary)" in js
    assert "const totalPassed = isLaborTotalAmountPassed(summary, wcSummary);" in js
    assert "const skippedEmployeeDrilldown = isLaborTotalAmountPassed(summary, wcSummary) && !rows.length;" in js
    assert "roundedDelta <= LABOR_TOTAL_AMOUNT_TOLERANCE" in js
    assert "const totalPassed = wcSummary && wcSummary.totalPassed;" not in js
    assert "const skippedEmployeeDrilldown = wcSummary && wcSummary.totalPassed && !rows.length;" not in js


def test_overseas_labor_report_sections_follow_business_reading_order():
    html = OVERSEAS_LABOR_HTML.read_text(encoding="utf-8")

    conclusion = html.index('id="conclusionSection"')
    total_and_warehouse = html.index('id="diagnosticsFold"')
    employee_recognition = html.index('id="extractPreviewTable"')
    auto_fix = html.index('id="autoFixSection"')
    pending = html.index('id="pendingItemsSection"')
    full_detail = html.index('id="employeeReconSection"')
    material_trial = html.index('id="materialReplaySection"')

    assert conclusion < total_and_warehouse < employee_recognition < auto_fix < pending < full_detail < material_trial
    assert "完整员工明细" in html
    assert "测试材料验证" in html
    assert "全员对账明细" not in html
    assert "Employee Reconciliation Detail" not in html


def test_overseas_labor_auto_fix_section_explains_safe_name_merges():
    html = OVERSEAS_LABOR_HTML.read_text(encoding="utf-8")
    js = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")

    assert 'id="autoFixSection"' in html
    assert 'id="autoFixBody"' in html
    assert "系统自动修正" in html
    assert "系统已自动合并姓名格式差异" in js
    assert "renderAutoFixSummary(rows)" in js
    assert "isAutoFixedNameRow" in js
    assert "姓名格式差异自动合并" in js
    assert "自动修正仅处理大小写、重音符号、标点、空格或前后顺序差异" in js


def test_overseas_labor_result_copy_is_business_readable_about_review_scope():
    js = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")

    assert "只展示需要确认的员工明细，不代表账单只有这些人" in js
    assert "待确认仓库" in js
    assert "待确认项目" in js
    assert "整批账单" in js
    assert "当前展示待确认员工明细" in js
    assert "不是整批账单人数" in js
    assert "异常队列" not in js
    assert "需复核仓库" not in js
    assert "核对信号存在冲突" not in js
    assert "下钻" not in js


def test_overseas_labor_reconciliation_table_translates_internal_statuses():
    js = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")

    assert "function laborBusinessStatusLabel" in js
    assert "status: laborBusinessStatusLabel(r.matchStatus, r)" in js
    assert "明细识别不完整" in js
    assert "账单有发票无" in js
    assert "发票有账单无" in js
    assert "系统已自动修正" in js
    assert "疑似同一员工" in js
    assert 'status: r.matchStatus || ""' not in js


def test_overseas_labor_visible_copy_uses_confirmation_not_review_jargon():
    html = OVERSEAS_LABOR_HTML.read_text(encoding="utf-8")
    js = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")

    assert "业务确认" in html or "业务确认" in js
    assert "待确认" in html
    assert "待确认" in js
    for old_copy in ["业务复核", "必须复核", "建议复核", "优先复核", "人工复核", "需复核"]:
        assert old_copy not in html
        assert old_copy not in js


def test_overseas_labor_visible_copy_uses_recognition_and_confirmation_not_extraction_jargon():
    html = OVERSEAS_LABOR_HTML.read_text(encoding="utf-8")
    js = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")

    assert "明细识别" in js
    assert "业务确认" in js
    for old_copy in [
        "抽取质量存在严重问题",
        "抽取质量需要关注",
        "抽取质量提示",
        "需人工核对",
        "人工核对原始发票",
    ]:
        assert old_copy not in html
        assert old_copy not in js


def test_overseas_labor_business_page_does_not_include_internal_governance_workbench():
    html = OVERSEAS_LABOR_HTML.read_text(encoding="utf-8")
    js = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")

    assert "ruleGovernanceSection" not in html
    assert "高级复核工具（内部）" not in html
    assert "ruleGovernanceBody" not in html
    assert "renderGovernancePanel(run)" not in js
    assert "handleGovernanceAction" not in js


def test_overseas_labor_initial_page_uses_business_copy_for_pending_and_incomplete_details():
    html = OVERSEAS_LABOR_HTML.read_text(encoding="utf-8")
    js = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")

    assert "待确认异常" in html
    assert "优先处理影响放行或留档的项目" in html
    assert "核对费率、加班、服务费或税费" in html
    assert "金额计算待确认" in html
    assert "金额计算方式待业务确认" in js
    assert "当前总金额" in js
    assert "确认是否属于本批发票" in html
    assert "业务确认是否同一人" in html
    assert "识别不完整时会进入待确认清单" in html
    assert "UAT试用版 · 结果需业务确认" in html
    assert "核对完成。识别不完整的明细已进入待确认清单。" in js
    assert "待确认总数" in js
    assert "查看处理建议" in js
    assert "确认前不会自动合并姓名" in js
    assert "疑似同一员工" in js
    assert "疑似同一员工处理路径" in js
    assert "需要业务确认的疑似同一员工" in js
    assert "确认本员工是否属于本批发票" in js
    assert "结果确认提示" in js
    assert "上线就绪检查" not in js
    assert "金额口径" not in html
    assert "金额口径" not in js
    for internal_copy in ["待处理事项", "待处理总数", "待人工复核", "Exception Queue", "低置信度项不阻断", "低置信度项已在风险表标记", "人工复核后使用", "人工复核", "姓名匹配建议", "姓名匹配处理路径", "需要业务确认的姓名匹配"]:
        assert internal_copy not in html
        assert internal_copy not in js


def test_desktop_builder_uses_platform_logo_icons():
    package = DESKTOP_PACKAGE.read_text(encoding="utf-8")

    assert '"icon": "assets/icon.icns"' in package
    assert '"icon": "assets/icon.ico"' in package
    assert DESKTOP_ICON_ICNS.exists()
    assert DESKTOP_ICON_ICO.exists()
    with Image.open(DESKTOP_ICON_PNG) as icon:
        assert icon.size == (512, 512)
        assert icon.mode == "RGBA"
