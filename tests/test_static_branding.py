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
LOGIN_HTML = ROOT / "bonus_platform" / "static" / "login.html"
STYLES_CSS = ROOT / "bonus_platform" / "static" / "styles.css"
APP_JS = ROOT / "bonus_platform" / "static" / "app.js"
STORY_HTML = ROOT / "bonus_platform" / "static" / "vibecoding-story.html"
HEADER_LOGO = ROOT / "bonus_platform" / "static" / "assets" / "bonus-logo-header-blue.png"
OVERSEAS_LABOR_LOGO = ROOT / "bonus_platform" / "static" / "assets" / "overseas-labor-logo-2026.png"
DESKTOP_PACKAGE = ROOT / "desktop" / "package.json"
DESKTOP_ICON_PNG = ROOT / "desktop" / "assets" / "icon.png"
DESKTOP_ICON_ICO = ROOT / "desktop" / "assets" / "icon.ico"
DESKTOP_ICON_ICNS = ROOT / "desktop" / "assets" / "icon.icns"


def test_login_smokey_canvas_is_viewport_layer_not_grid_content():
    html = LOGIN_HTML.read_text(encoding="utf-8")
    css = STYLES_CSS.read_text(encoding="utf-8")

    assert 'class="login-smokey-canvas"' in html
    canvas_css = css.split(".login-smokey-canvas {", 1)[1].split("}", 1)[0]
    assert "position: fixed" in canvas_css
    assert "inset: 0" in canvas_css
    assert "width: 100%" in canvas_css
    assert "height: 100%" in canvas_css
    assert "pointer-events: none" in canvas_css


def test_overseas_labor_page_exposes_release_contract_and_blocks_stale_runtime():
    html = OVERSEAS_LABOR_HTML.read_text(encoding="utf-8")
    script = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")

    assert 'id="moduleReleaseMeta"' in html
    assert "正式批次固定执行员工级明细核对" in html
    assert 'const LABOR_UI_MODULE_VERSION = "0.5-uat"' in script
    assert "const LABOR_UI_API_CONTRACT_VERSION = 2" in script
    assert "laborReleaseCompatibility" in script
    assert "setLaborActionAvailability" in script
    assert "runtimeGate?.runtimeSourceCurrent" in script
    assert "access?.build?.schemaVersion === 1" in script
    assert 'access?.build?.status === "current"' in script
    assert '"X-Sigma-Labor-API-Contract"' in script
    assert '"X-Sigma-Labor-UI-Version"' in script
    assert '"X-Sigma-Labor-UI-Build"' in script
    assert "前后端版本不一致" in script
    assert "require_employee_detail: true" in script
    assert "usesP1DirectUpload" in script
    assert "sha256File" in script
    assert "upload-intents" in script
    assert "intent.signedUrl" in script
    assert "upload-intents/${intent.fileId}/finalize" in script
    assert 'overseas-labor.js?v=32' in html


def test_overseas_labor_uses_one_editable_seven_day_period_range_picker():
    html = OVERSEAS_LABOR_HTML.read_text(encoding="utf-8")
    script = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")

    assert 'id="periodRange"' in html
    assert 'id="periodCalendar"' in html
    assert 'id="periodCalendarGrid"' in html
    assert 'id="periodStart"' in html and 'name="periodStart" type="hidden"' in html
    assert 'id="periodEnd"' in html and 'name="periodEnd" type="hidden"' in html
    assert 'id="clearPeriodRange"' in html
    assert 'data-period-preset="this-week"' not in html
    assert 'data-period-preset="last-week"' not in html
    assert 'data-period-preset="last-7-days"' not in html
    assert "最近7天" not in html
    assert "function renderPeriodCalendar()" in script
    assert "function selectPeriodDate(value)" in script
    assert "addDays(picked, 6)" in script
    assert "periodPickerState.selectingEnd" in script
    assert 'overseas-labor.js?v=32' in html


def test_overseas_labor_async_actions_share_button_loading_transitions():
    html = OVERSEAS_LABOR_HTML.read_text(encoding="utf-8")
    script = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")

    assert "@keyframes labor-button-spin" in html
    assert ".button-loading-indicator" in html
    assert ".is-loading" in html
    assert "const buttonLoadingState = new WeakMap()" in script
    assert "function beginButtonLoading(button, label" in script
    assert "function endButtonLoading(button" in script
    assert 'beginButtonLoading(labor.createLaborRun, "正在创建")' in script
    assert 'beginButtonLoading(labor.uploadLaborFiles, "正在上传")' in script
    assert 'beginButtonLoading(labor.loadSheets, "正在读取")' in script
    assert 'beginButtonLoading(labor.saveMapping, "正在保存")' in script
    assert 'beginButtonLoading(labor.extractCompare, "正在生成")' in script
    assert 'beginButtonLoading(labor.loadMaterialBatches, "正在加载")' in script
    assert 'beginButtonLoading(labor.runMaterialDryRun, "正在验证")' in script
    assert 'beginButtonLoading(labor.activateWorker, "正在连接")' in script
    assert 'beginButtonLoading(labor.deleteCurrentRun, "正在删除")' in script
    assert 'beginButtonLoading(button, "正在撤销")' in script
    assert 'overseas-labor.js?v=32' in html


def test_overseas_labor_uses_server_formal_task_gate_instead_of_hostname_guessing():
    script = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")
    gate_block = script[
        script.index("function isFormalLaborTaskBlocked"):
        script.index("function showFormalLaborTaskBlocked")
    ]
    extract_block = script[
        script.index("async function extractAndCompare"):
        script.index("async function pollCompareResult")
    ]

    assert "formalTaskGate?.canQueue" in gate_block
    assert "window.location.hostname" not in gate_block
    assert "isVercelLaborLightUat" not in script
    assert "showVercelLightUatExtractBlocked" not in script
    assert "isFormalLaborTaskBlocked()" in extract_block
    assert "showFormalLaborTaskBlocked()" in extract_block


def test_overseas_labor_page_exposes_batch_governance_controls():
    html = OVERSEAS_LABOR_HTML.read_text(encoding="utf-8")
    script = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")

    assert 'id="btnOpenGovernance"' in html
    assert 'id="laborGovernanceDialog"' in html
    assert 'id="deleteCurrentLaborRun"' in html
    assert 'id="laborStorageSummary"' in html
    assert 'id="laborAuditList"' in html
    assert 'requestJson("/api/labor/storage-info")' in script
    assert 'requestJson(`/api/labor/audit?run_id=${encodeURIComponent(runId)}&limit=20`)' in script


def test_overseas_labor_can_restore_an_owned_batch_from_the_run_query():
    script = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")
    restore_block = script[
        script.index("async function restoreLaborRunFromUrl"):
        script.index("function laborReleaseCompatibility")
    ]

    assert 'new URLSearchParams(window.location.search).get("run")' in restore_block
    assert 'requestJson(`/api/labor/runs/${encodeURIComponent(runId)}`)' in restore_block
    assert 'advanceWizardStep(hasUploadedFiles ? "3" : "2")' in restore_block
    assert 'run.mappingPreflight?.status === "completed"' in restore_block
    assert "await loadSheets();" in restore_block
    assert "已恢复批次" in restore_block


def test_overseas_labor_restore_shows_completed_result_or_resumes_polling():
    script = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")
    restore_block = script[
        script.index("async function restoreLaborRunFromUrl"):
        script.index("function laborReleaseCompatibility")
    ]

    assert "function restoreLaborRunOutput" in restore_block
    assert 'run.status === "已生成差异报告"' in restore_block
    assert "renderResult(run);" in restore_block
    assert "setDownload(preferredLaborReportDownloadUrl(run));" in restore_block
    assert '["queued", "waiting_for_personal_worker", "running", "retry_wait"].includes(taskStatus)' in restore_block
    assert "renderLaborProgress(run);" in restore_block
    assert "window.setInterval(pollCompareResult, 3000)" in restore_block


def test_overseas_labor_waits_for_worker_completion_before_accepting_report():
    script = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")

    assert "function laborRunHasSettledResult" in script
    helper_block = script[
        script.index("function laborRunHasSettledResult"):
        script.index("function restoreLaborRunOutput")
    ]
    restore_block = script[
        script.index("function restoreLaborRunOutput"):
        script.index("function laborReleaseCompatibility")
    ]
    poll_block = script[
        script.index("async function pollCompareResult"):
        script.index("function formatLaborFailureMessage")
    ]

    assert 'run.status === "已生成差异报告"' in helper_block
    assert 'taskStatus === "completed"' in helper_block
    assert 'taskStatus === "succeeded"' in helper_block
    assert "laborRunHasSettledResult(run)" in restore_block
    assert "laborRunHasSettledResult(run)" in poll_block


def test_overseas_labor_new_batch_resets_restored_run_and_tracks_new_run_url():
    script = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")
    reset_block = script[
        script.index("function beginNewLaborBatch"):
        script.index("async function createRun")
    ]
    create_block = script[
        script.index("async function createRun"):
        script.index("async function uploadFiles")
    ]

    assert 'labor.btnOpenDrawer.addEventListener("click", beginNewLaborBatch)' in script
    assert "stopComparePolling()" in reset_block
    assert "clearResults()" in reset_block
    assert "laborState.run = null" in reset_block
    assert 'setLaborRunQuery("")' in reset_block
    assert 'advanceWizardStep("1")' in reset_block
    assert 'labor.pdfFiles.value = ""' in reset_block
    assert 'labor.workbookFile.value = ""' in reset_block
    assert "setLaborRunQuery(run.id)" in create_block


def test_overseas_labor_new_batch_clears_all_prior_result_labels_and_ignores_stale_poll():
    script = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")
    clear_block = script[
        script.index("function clearResults"):
        script.index("async function extractAndCompare")
    ]
    poll_block = script[
        script.index("async function pollCompareResult"):
        script.index("function formatLaborFailureMessage")
    ]
    extract_block = script[
        script.index("async function extractAndCompare"):
        script.index("async function pollCompareResult")
    ]

    assert 'setText(labor.compareStatus, "新批次尚未生成核对结果。")' in clear_block
    assert 'totalCard.textContent = "尚未核对"' in clear_block
    assert 'matchedCard.textContent = "尚未核对"' in clear_block
    assert 'unmatchedCard.textContent = "待确认项目"' in clear_block
    assert "const requestedRunId = laborState.run?.id" in poll_block
    assert "laborState.run?.id !== requestedRunId" in poll_block
    assert "const requestedRunId = laborState.run?.id" in extract_block
    assert "laborState.run?.id !== requestedRunId" in extract_block


def test_overseas_labor_preserves_structured_api_conflict_message():
    script = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")
    formatter_block = script[
        script.index("function formatLaborRequestError"):
        script.index("function setDownload")
    ]

    assert 'const errorCode = String(message?.errorCode || "").trim();' in formatter_block
    assert "if (errorCode && typeof message === \"object\") return text" in formatter_block


def test_overseas_labor_revalidates_completed_mapping_preflight_before_reuse():
    script = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")
    preflight_block = script[
        script.index("async function ensureP1MappingPreflight"):
        script.index("async function loadFieldSuggestions")
    ]

    assert 'requestJson(`/api/labor/runs/${laborState.run.id}/mapping-preflight`' in preflight_block
    assert 'if (current.status === "completed") return;' not in preflight_block
    assert 'response.mappingPreflight' in preflight_block


def test_overseas_labor_exposes_personal_worker_activation_without_persisting_token_in_dom():
    html = OVERSEAS_LABOR_HTML.read_text(encoding="utf-8")
    script = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")

    assert 'id="btnWorkerStatus"' in html
    assert 'id="activateLaborWorker"' in html
    assert "/api/labor/worker/devices" in script
    assert "sigma-overseas-labor-worker://activate?" in script
    assert "workerVersion: laborState.moduleAccess" not in script
    activation_block = script[
        script.index("async function activateLaborWorker"):
        script.index("async function handleLaborWorkerDeviceAction")
    ]
    assert "activationUrl" in activation_block
    assert "localStorage" not in activation_block
    assert 'method: "DELETE"' in script


def test_overseas_labor_mapping_supports_optional_amount_components():
    html = OVERSEAS_LABOR_HTML.read_text(encoding="utf-8")
    script = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")

    assert 'id="amountComponentColumns"' in html
    assert "叠加金额列" in html
    assert "renderAmountComponentOptions" in script
    assert "amountColumns: selectedAmountColumns()" in script
    assert 'id="amountScope"' in html
    assert "金额口径" in html
    assert "amountScope: labor.amountScope.value" in script


def test_overseas_labor_conclusion_uses_stacked_readable_layout_and_filters_blank_warehouses():
    html = OVERSEAS_LABOR_HTML.read_text(encoding="utf-8")
    script = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")

    conclusion_css = html.split(".overseas-labor-shell .conclusion-section {", 2)[-1].split("}", 1)[0]
    details_css = html.split(".overseas-labor-shell .conclusion-details {", 2)[-1].split("}", 1)[0]
    assert "display: grid" in conclusion_css
    assert "display: grid" in details_css
    assert 'class="conclusion-detail conclusion-detail--summary"' in script
    assert 'class="conclusion-detail conclusion-detail--explanation"' in script
    assert 'class="conclusion-report-actions"' in script
    assert "normalizeReviewWarehouses" in script
    assert ".map((warehouse) => String(warehouse || \"\").trim())" in script
    assert ".filter(Boolean)" in script


def test_overseas_labor_employee_summary_counts_people_without_zero_rows_or_name_candidates():
    script = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")
    helper_block = script[
        script.index("function laborPresentationContract"):
        script.index("function renderEmployeeReconTable")
    ]
    result_block = script[
        script.index("function renderResult"):
        script.index("function normalizeReviewWarehouses")
    ]
    render_block = script[
        script.index("function renderEmployeeReconTable"):
        script.index("function laborBusinessStatusLabel")
    ]
    conclusion_block = script[
        script.index("function renderConclusion"):
        script.index("function buildBusinessConclusion")
    ]

    assert "run?.presentation" in helper_block
    assert "schemaVersion === 1" in helper_block
    assert "laborEmployeeComparisonRows(run?.comparisonRows)" in helper_block
    assert "const presentation = laborPresentationContract(run);" in result_block
    assert "const rows = presentation.employeeRows;" in result_block
    assert "const candidateMatches = presentation.candidateMatches;" in result_block
    assert "const employeeRows = Array.isArray(rows) ? rows : [];" in render_block
    assert "employeeRows.forEach" in render_block
    assert "candidateMatches.forEach" not in render_block
    assert 'presentationSummary?.employeeCount ?? allRows.length' in render_block
    assert "laborPresentationContract(run)" in conclusion_block


def test_overseas_labor_employee_detail_is_first_workspace_section_below_kpis():
    html = OVERSEAS_LABOR_HTML.read_text(encoding="utf-8")

    kpi_index = html.index('id="kpiBanner"')
    workspace_index = html.index('<main class="workspace">')
    employee_index = html.index('id="employeeReconSection"')
    conclusion_index = html.index('id="conclusionSection"')

    assert kpi_index < workspace_index < employee_index < conclusion_index


def test_overseas_labor_page_uses_dedicated_latest_logo_for_header_and_favicon():
    html = OVERSEAS_LABOR_HTML.read_text(encoding="utf-8")

    assert OVERSEAS_LABOR_LOGO.exists()
    assert 'href="assets/overseas-labor-logo-2026.png"' in html
    assert 'src="assets/overseas-labor-logo-2026.png"' in html
    with Image.open(OVERSEAS_LABOR_LOGO) as logo:
        assert logo.size == (1254, 1254)
        assert logo.mode == "RGBA"
        assert logo.getpixel((0, 0))[3] == 0


def test_overseas_labor_header_keeps_logo_compact_and_hides_build_metadata():
    html = OVERSEAS_LABOR_HTML.read_text(encoding="utf-8")

    logo_rule = html.split(".overseas-labor-shell .portal-logo-mark {", 1)[1].split("}", 1)[0]
    assert "min-width: 0" in logo_rule
    assert 'id="moduleReleaseMeta" role="status" aria-live="polite" hidden' in html
    assert "界面 0.5-uat · API v2" not in html


def test_overseas_labor_surfaces_component_backed_amount_difference():
    script = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")

    status_block = script[
        script.index("function laborBusinessStatusLabel"):
        script.index("function renderPassEvidence")
    ]
    pending_block = script[
        script.index("function normalizeFormalAmountRateRows"):
        script.index("function _renderHoursDiffTable")
    ]

    assert 'amountDifferenceReasonCode === "excel_amount_component_delta"' in status_block
    assert 'return "Excel含额外费用项"' in status_block
    assert "amountDifferenceExplanation" in pending_block
    assert "amountDifferenceComponents" in pending_block


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
    assert "V0.5-UAT" in html
    assert "本机 OCR" in html
    assert "AI 抽取、差异报告" not in html
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


def test_recruitment_header_omits_user_menu():
    html = RECRUITMENT_HTML.read_text(encoding="utf-8")
    css = STYLES_CSS.read_text(encoding="utf-8")

    assert 'class="workbench-user-menu"' not in html
    assert "姚硕灿" not in html
    assert "系统管理员" not in html
    assert "进入后台管理" not in html
    assert "退出登录" not in html
    assert ".workbench-user-menu" not in css
    assert ".user-menu-panel" not in css
    assert ".header-copy::before" in css
    assert "background: rgba(30, 58, 138, 0.28)" in css
    assert "background-size: 1px 10px" not in css


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
    assert "本地解析/OCR 提取证据" in html
    assert "AI 抽取供应商发票" not in html
    assert "overseas-labor.js" in html
    assert "/api/labor/runs" in js
    assert "字段映射" in html
    assert "结论" in html
    assert "仓库核对总览" in html
    assert ".overseas-labor-shell" in css


def test_overseas_labor_upload_shows_and_prevalidates_configured_workbook_limit():
    html = OVERSEAS_LABOR_HTML.read_text(encoding="utf-8")
    js = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")

    assert "workbookUploadHint(0)" in js
    assert 'overseas-labor.js?v=32' in html
    assert "access.uploadLimits?.maxWorkbookFiles" in js
    assert "existing.workbook + pendingWorkbookCount > maxWorkbookFiles" in js
    assert "最多选择 ${maxWorkbookFiles} 个 Excel 文件" in js


def test_overseas_labor_uses_inline_toolbench_and_module_only_branding():
    html = OVERSEAS_LABOR_HTML.read_text(encoding="utf-8")
    js = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")

    assert 'class="module-brand-lockup"' in html
    assert "Σ-WORKBENCH" not in html
    assert "西格玛工作台" not in html
    assert 'id="laborToolbench"' in html
    assert 'id="laborResultsView"' in html
    assert 'class="drawer-overlay"' not in html
    assert 'class="wizard-drawer"' not in html
    assert "function showLaborToolbench()" in js
    assert "function showLaborResultsView()" in js
    assert "showLaborResultsView();" in js[js.index("async function extractAndCompare"):js.index("async function pollCompareResult")]


def test_overseas_labor_file_picker_accumulates_and_can_clear_files():
    html = OVERSEAS_LABOR_HTML.read_text(encoding="utf-8")
    js = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")

    assert 'id="clearLaborFiles"' in html
    assert "selectedPdfFiles: []" in js
    assert "selectedWorkbookFiles: []" in js
    assert "function mergeSelectedLaborFiles" in js
    assert 'labor.pdfFiles.addEventListener("change", handlePdfFilesSelected)' in js
    assert 'labor.workbookFile.addEventListener("change", handleWorkbookFilesSelected)' in js
    assert "laborState.selectedPdfFiles" in js
    assert "laborState.selectedWorkbookFiles" in js
    assert "function clearSelectedLaborFiles" in js


def test_overseas_labor_page_exposes_worker_download_and_update_status():
    html = OVERSEAS_LABOR_HTML.read_text(encoding="utf-8")
    js = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")

    assert 'id="downloadLaborWorker"' in html
    assert 'id="laborWorkerReleaseStatus"' in html
    assert 'id="laborWorkerReleasePackage"' in html
    assert 'id="laborWorkerReleasePlatform"' in html
    assert 'id="uploadLaborWorkerRelease"' in html
    assert "/api/labor/worker/release" in js
    assert "/api/labor/worker/release/upload-intent" in js
    assert "function detectLaborWorkerPlatform" in js
    assert "platform=${encodeURIComponent(laborState.workerPlatform)}" in js
    assert "platform: releasePlatform" in js
    assert "updateAvailable" in js
    assert "有新版本" in js

    release_action_css = html[
        html.index(".overseas-labor-shell .worker-release-action {"):
        html.index(".overseas-labor-shell .drawer-chrome,")
    ]
    assert "width: 220px" in release_action_css
    assert "white-space: normal" in release_action_css
    assert "overflow-wrap: anywhere" in release_action_css
    assert "text-overflow: ellipsis" not in release_action_css


def test_overseas_labor_polling_uses_backend_heartbeat_instead_of_fixed_ten_minute_limit():
    js = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")

    assert "pollMaxRetries" not in js
    assert "pollMaxIdleSeconds: 600" in js
    assert "secondsSince(run?.progress?.lastUpdatedAt)" in js
    assert "后台超过10分钟没有更新进度" in js
    assert "生成核对报告超时（10分钟）" not in js


def test_overseas_labor_parses_timezone_less_backend_timestamps_as_utc():
    js = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")
    parser_block = js[
        js.index("function parseIsoTime"):
        js.index("function formatDuration")
    ]

    assert 'const text = String(value || "").trim();' in parser_block
    assert '/^\\d{4}-\\d{2}-\\d{2}T/' in parser_block
    assert '`${text}Z`' in parser_block
    assert "Date.parse(normalized)" in parser_block


def test_overseas_labor_renders_structure_guard_statuses_before_business_difference():
    js = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")

    assert "run?.batchGuard" in js
    assert 'guard.status === "pdf_recognition_incomplete"' in js
    assert 'guard.status === "partial_review"' in js
    assert 'guard.status === "currency_review"' in js
    assert "本次属于识别异常，不是业务差异" in js
    assert "张发票待确认" in js


def test_overseas_labor_uses_detected_currency_instead_of_hardcoded_dollars():
    js = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")

    assert "function laborCurrencySymbol" in js
    assert 'EUR: "€"' in js
    assert "const currencySymbol = laborCurrencySymbol(run);" in js
    assert 'labor.kpiTotal.textContent = `${currencySymbol}${formatMoney(pdfAmount)}`' in js


def test_desktop_builder_uses_platform_logo_icons():
    package = DESKTOP_PACKAGE.read_text(encoding="utf-8")

    assert '"icon": "assets/icon.icns"' in package
    assert '"icon": "assets/icon.ico"' in package
    assert DESKTOP_ICON_ICNS.exists()
    assert DESKTOP_ICON_ICO.exists()
    with Image.open(DESKTOP_ICON_PNG) as icon:
        assert icon.size == (512, 512)
        assert icon.mode == "RGBA"
