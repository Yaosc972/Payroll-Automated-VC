from pathlib import Path
import json

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "bonus_platform" / "static" / "index.html"
ADMIN_HTML = ROOT / "bonus_platform" / "static" / "admin.html"
ADMIN_JS = ROOT / "bonus_platform" / "static" / "admin.js"
PERMISSION_GUARD_JS = ROOT / "bonus_platform" / "static" / "permission-guard.js"
LOGIN_HTML = ROOT / "bonus_platform" / "static" / "login.html"
LOGIN_JS = ROOT / "bonus_platform" / "static" / "login.js"
RECRUITMENT_HTML = ROOT / "bonus_platform" / "static" / "recruitment.html"
LABOR_HTML = ROOT / "bonus_platform" / "static" / "labor.html"
DOMESTIC_LABOR_HTML = ROOT / "bonus_platform" / "static" / "domestic-labor.html"
DOMESTIC_LABOR_JS = ROOT / "bonus_platform" / "static" / "domestic-labor.js"
OVERSEAS_LABOR_HTML = ROOT / "bonus_platform" / "static" / "overseas-labor.html"
OVERSEAS_LABOR_JS = ROOT / "bonus_platform" / "static" / "overseas-labor.js"
EMPLOYEE_PAYROLL_HTML = ROOT / "bonus_platform" / "static" / "china-employee-payroll.html"
EMPLOYEE_PAYROLL_JS = ROOT / "bonus_platform" / "static" / "china-employee-payroll.js"
LEGACY_EMPLOYEE_PAYROLL_HTML = ROOT / "bonus_platform" / "static" / "employee-payroll.html"
RELEASE_INFO_JSON = ROOT / "bonus_platform" / "static" / "release-info.json"
VERCEL_JSON = ROOT / "vercel.json"
LOGIN_HTML = ROOT / "bonus_platform" / "static" / "login.html"
STYLES_CSS = ROOT / "bonus_platform" / "static" / "styles.css"
APP_PY = ROOT / "bonus_platform" / "app.py"
APP_JS = ROOT / "bonus_platform" / "static" / "app.js"
STORY_HTML = ROOT / "bonus_platform" / "static" / "vibecoding-story.html"
HEADER_LOGO = ROOT / "bonus_platform" / "static" / "assets" / "bonus-logo-header-blue.png"
LOGIN_SIGMA_LOGO = ROOT / "bonus_platform" / "static" / "assets" / "bonus-logo-header-transparent.png"
FEISHU_LOGO = ROOT / "bonus_platform" / "static" / "assets" / "feishu-logo.png"
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
    assert "pointer-events: auto" in canvas_css


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
    assert "upload-intents/batch-finalize" in script
    assert 'overseas-labor.js?v=37' in html


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
    assert 'overseas-labor.js?v=37' in html


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
    assert 'overseas-labor.js?v=37' in html


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


def test_overseas_labor_new_batch_invalidates_an_inflight_restore():
    script = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")
    restore_block = script[
        script.index("async function restoreLaborRunFromUrl"):
        script.index("function laborRunHasSettledResult")
    ]
    reset_block = script[
        script.index("function beginNewLaborBatch"):
        script.index("async function createRun")
    ]

    assert "let laborRunRestoreGeneration = 0;" in script
    assert "const restoreGeneration = ++laborRunRestoreGeneration;" in restore_block
    assert "restoreGeneration !== laborRunRestoreGeneration" in restore_block
    assert 'new URLSearchParams(window.location.search).get("run") !== runId' in restore_block
    assert "laborRunRestoreGeneration += 1;" in reset_block


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
        script.index("function mappingPreflightSuggestion")
    ]

    assert 'requestJson(`/api/labor/runs/${laborState.run.id}/mapping-preflight`' in preflight_block
    assert 'if (current.status === "completed") return;' not in preflight_block
    assert 'response.mappingPreflight' in preflight_block
    assert "return submittedPreflight" in preflight_block
    assert "return preflight" in preflight_block
    assert "const delayMs = Math.min(15000, 5000 + (attempt * 2500))" in preflight_block


def test_overseas_labor_mapping_preflight_requires_current_environment_worker_and_shows_real_phase():
    script = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")
    preflight_block = script[
        script.index("async function ensureP1MappingPreflight"):
        script.index("function mappingPreflightSuggestion")
    ]

    assert "await loadLaborWorkerDevices()" in preflight_block
    assert preflight_block.index("await loadLaborWorkerDevices()") < preflight_block.index(
        'requestJson(`/api/labor/runs/${laborState.run.id}/mapping-preflight`'
    )
    assert "workerDeviceIsOnline" in preflight_block
    assert "核对助手尚未连接当前生产环境，请先激活或重新连接。" in script
    assert "mappingPreflightProgressMessage" in preflight_block
    assert "等待核对助手连接" in script
    assert "Worker 已领取任务" in script
    assert "正在下载 Excel" in script
    assert "正在读取工作表" in script
    assert "正在回传结果" in script
    assert "Date.now() - seenAt < 15 * 1000" in script
    assert "startLaborWorkerDevicePolling" in script
    assert "window.setInterval" in script
    assert "3000" in script
    assert "document.hidden" in script


def test_overseas_labor_worker_status_names_current_environment_and_switch_warning():
    script = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")

    assert "function laborWorkerEnvironmentLabel" in script
    assert 'window.location.hostname === "sigma-workbench.vercel.app"' in script
    assert "生产环境" in script
    assert "UAT 环境" in script
    assert "重新激活会将桌面核对助手切换到当前环境" in script


def test_overseas_labor_reuses_worker_mapping_preflight_without_redundant_api_calls():
    script = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")
    sheets_block = script[
        script.index("async function loadSheets"):
        script.index("async function ensureP1MappingPreflight")
    ]
    suggestion_block = script[
        script.index("function mappingPreflightSuggestion"):
        script.index("async function saveMapping")
    ]

    assert "const preflight = await ensureP1MappingPreflight()" in sheets_block
    assert "Array.isArray(preflight?.sheets)" in sheets_block
    assert "if (usesP1DirectUpload())" in sheets_block
    assert "return;" in sheets_block
    assert 'preflight?.status !== "completed"' in suggestion_block
    assert "mappingPreflightSuggestion(sheetName)" in suggestion_block
    assert "cachedSuggestion || await requestJson" in suggestion_block
    assert "applyFieldSuggestions(data)" in suggestion_block


def test_overseas_labor_discards_stale_field_suggestion_responses():
    script = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")
    suggestion_block = script[
        script.index("async function loadFieldSuggestions"):
        script.index("async function saveMapping")
    ]

    assert "laborFieldSuggestionRequestId" in script
    assert "const requestId = ++laborFieldSuggestionRequestId" in suggestion_block
    assert "requestId !== laborFieldSuggestionRequestId" in suggestion_block
    assert "labor.sheetSelect.value !== sheetName" in suggestion_block
    assert "laborState.run?.id !== runId" in suggestion_block


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
    assert 'href="china-employee-payroll.html"' in html
    assert "支持集团、WX考勤、月度规则计算与结果导出。" in html
    assert "支持微信考勤" not in html
    assert 'href="admin.html"' in html
    assert "V0.5-UAT" in html
    assert "本机 OCR" in html
    assert "AI 抽取、差异报告" not in html
    assert "Available · 已上线" in html
    assert "UAT Trial · 试用版" in html
    assert "UAT试点" in html
    assert "{ id: 'overseas', name: '海外劳务报账核对', href: 'overseas-labor.html', enabled: true }" in html
    assert "app.js" not in html
    assert "tabulator-tables" not in html
    assert "sigma-admin-console-draft-v3" in html
    assert "data-module-id" in html
    assert "canEnterModule" in html
    assert "if (!module?.enabled) return false" in html
    assert "currentUser.roleIds.includes('admin')) return true" in html
    assert "sigma-auth-context-v2" in html
    assert "/api/me" in html
    assert "downloadInlineFile" in APP_JS.read_text(encoding="utf-8")
    assert "inlineFile" in APP_JS.read_text(encoding="utf-8")
    assert 'id="dashboardUserMenu"' in html
    assert 'id="dashboardAdminLink"' in html
    assert 'id="dashboardLogout"' in html
    assert "/api/auth/logout" in html
    assert "退出中" in html
    assert "进入后台管理" in html
    assert "isSystemAdmin" in html
    assert "adminOnly" in html
    assert ".dashboard-user-menu" in STYLES_CSS.read_text(encoding="utf-8")
    assert "login.html?next=" in html
    assert "permission-locked" in html
    assert 'id="dashboardUserAvatar"' in html
    assert 'id="dashboardRoleTags"' in html
    assert "avatarUrl" in html
    assert ".dashboard-user-avatar" in STYLES_CSS.read_text(encoding="utf-8")
    assert ".dashboard-role-tags" in STYLES_CSS.read_text(encoding="utf-8")


def test_portal_auth_bootstrap_does_not_depend_on_optional_gsap():
    html = INDEX_HTML.read_text(encoding="utf-8")
    auth_bootstrap = html.index("fetch('/api/me'")
    script_before_auth = html[html.index("<script>", html.index("</main>")):auth_bootstrap]

    assert "if (!window.gsap || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;" not in script_before_auth
    assert "if (window.gsap && !window.matchMedia('(prefers-reduced-motion: reduce)').matches)" in script_before_auth


def test_vercel_config_does_not_override_runtime_labor_access_mode():
    config = json.loads(VERCEL_JSON.read_text(encoding="utf-8"))

    assert config["env"]["SIGMA_WORKBENCH_HOME"] == "/tmp/sigma-workbench"
    assert "SIGMA_OVERSEAS_LABOR_ACCESS" not in config["env"]


def test_overseas_labor_uses_direct_storage_upload_for_large_files():
    js = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")

    assert "/upload-intents" in js
    assert "/upload-intents/batch-finalize" in js
    assert "uploadFilesDirectlyToPrivateStorage" in js
    assert "signedUrl" in js


def test_admin_console_is_static_permission_management_shell():
    html = ADMIN_HTML.read_text(encoding="utf-8")
    js = ADMIN_JS.read_text(encoding="utf-8")
    css = STYLES_CSS.read_text(encoding="utf-8")

    assert "后台管理 · 西格玛工作台" in html
    assert "用户与角色" in html
    assert "模块权限" in html
    assert "功能权限" in html
    assert "模块配置" in html
    assert "操作日志" in html
    assert "权限配置中心" in html
    assert "localStorage 模拟" in html
    assert 'data-admin-only="true"' in html
    assert "permission-guard.js" in html
    assert 'id="activeAdminUser"' in html
    assert 'src="admin.js?v=1"' in html
    assert "app.js" not in html
    assert "tabulator-tables" not in html
    assert "rolePermissions" in js
    assert "moduleAccess" in js
    assert "selectedUserId" in js
    assert "roleIds" in js
    assert "admin-user-table" in js
    assert "admin-user-avatar" in js
    assert "avatarUrl" in js
    assert "admin-role-dropdown" in js
    assert "save-user-roles" in js
    assert "默认权限：无模块权限" in js
    assert "更新用户角色" in js
    assert "module-access" in js
    assert "开放角色进入模块" in js
    assert "系统管理员" in js
    assert "招聘奖金核算管理员" in js
    assert "国内正式工核算管理员" in js
    assert "国内外包工核算管理员" in js
    assert "FBU美洲绩效核算管理员" in js
    assert "海外报账管理员" in js
    assert "进入模块" in js
    assert "提交核算" in js
    assert "sigma-admin-console-draft-v3" in js
    assert ".admin-user-table" in css
    assert ".admin-user-avatar" in css
    assert ".admin-role-dropdown" in css
    assert ".admin-role-menu" in css
    assert ".admin-feature-table" in css
    assert ".admin-console-section" in css
    assert ".admin-module-access-grid" in css


def test_employee_payroll_meal_allowance_page_is_guarded_live_module():
    html = EMPLOYEE_PAYROLL_HTML.read_text(encoding="utf-8")
    legacy_html = LEGACY_EMPLOYEE_PAYROLL_HTML.read_text(encoding="utf-8")
    js = EMPLOYEE_PAYROLL_JS.read_text(encoding="utf-8")
    css = STYLES_CSS.read_text(encoding="utf-8")

    assert "中国区正式工薪酬核算" in html
    assert "技术部餐补核算" in html
    assert 'data-module-id="employee"' in html
    assert "permission-guard.js?v=9" in html
    assert "china-employee-payroll.js" in html
    assert "/api/china-employee-payroll/meal-allowance" in js
    assert ".china-employee-payroll-shell" in css
    assert ".employee-payroll-table" in css
    assert 'url=china-employee-payroll.html' in legacy_html
    assert 'window.location.replace("china-employee-payroll.html")' in legacy_html


def test_recruitment_page_keeps_command_center_and_home_link():
    html = RECRUITMENT_HTML.read_text(encoding="utf-8")

    assert 'data-module-id="recruitment"' in html
    assert "permission-guard.js" in html
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

    assert "劳务工薪酬核算" in html
    assert 'data-module-id="domestic"' in html
    assert "permission-guard.js" in html
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


def test_domestic_labor_uses_signed_storage_upload_before_calculation():
    html = DOMESTIC_LABOR_HTML.read_text(encoding="utf-8")
    js = DOMESTIC_LABOR_JS.read_text(encoding="utf-8")

    assert "/api/domestic-labor/runs/direct-upload-plan" in js
    assert "/direct-upload-complete" in js
    assert "XMLHttpRequest" in js
    assert "upload.onprogress" in js
    assert "plan.uploads" in js
    assert "setButtonBusy" in js
    assert "dl-button-spinner" in html
    assert "activeCanbuOperation" in js
    assert "renderCanbuOperationStatus" in js
    assert "正在后台继续处理，可安全切换步骤" in js
    assert "onPlanCreated" in js
    assert "uploadDomesticFilesConcurrently" in js
    assert "dl-operation-status" in html


def test_domestic_labor_restores_an_in_progress_batch_run():
    js = DOMESTIC_LABOR_JS.read_text(encoding="utf-8")

    assert "isCanbuBatchCalculating(batch) ? 'results'" in js
    assert "restoreCanbuRunStatus" in js
    assert "startPolling()" in js

    completed_loader = js.split("async function loadCompletedRun", 1)[1].split("async function pollStatus", 1)[0]
    assert completed_loader.index("finishCanbuOperation(runId)") < completed_loader.index("renderResults(completedRun)")
    assert "const batchIsComplete = ['已核算', '可导出', '已导出'].includes(batch.status)" in js
    assert "operation.phase !== 'failed' && isCanbuBatchCalculating(batch)" in js


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


def test_domestic_labor_housing_allowance_workbench_is_available():
    html = DOMESTIC_LABOR_HTML.read_text(encoding="utf-8")
    js = DOMESTIC_LABOR_JS.read_text(encoding="utf-8")

    assert "当前开放餐补、外宿补贴与工龄奖核算" in html
    assert "外宿补贴核算" in html
    assert "Housing Allowance · 已开放" in html
    assert 'class="dl-subject-card primary" data-subject-entry="waisu_butie"' in html
    assert "按实际入住、退宿日期和缺勤口径核算" in html
    assert "subject === 'canbu' || subject === 'waisu_butie'" in js
    assert "engines: [batch.subject]" in js
    assert "el.batchNameText.textContent = batch.name" in js
    assert "el.chromeRunBadge.hidden = !batch.runId" in js
    assert "batch.runId.slice(-8)" in js
    assert "if (subject === 'waisu_butie') return results.filter(hasWaisuReviewIssue).length" in js
    assert "住宿名单字段" in js
    assert "应发外宿补贴" in js


def test_domestic_labor_subject_cards_expose_operations_and_all_region_scope():
    html = DOMESTIC_LABOR_HTML.read_text(encoding="utf-8")

    assert html.count('class="dl-subject-line-tag">操作线</span>') == 3
    assert html.count('class="dl-subject-line-tag">全区域</span>') == 1
    assert ".dl-subject-line-tag" in html


def test_domestic_labor_home_exposes_versioned_verified_rule_package():
    html = DOMESTIC_LABOR_HTML.read_text(encoding="utf-8")
    js = DOMESTIC_LABOR_JS.read_text(encoding="utf-8")

    assert 'id="navRulePackage"' in html
    assert 'id="rulePackageEntry"' in html
    assert 'id="rulePackageView"' in html
    assert 'id="rulePackageCategoryTabs"' in html
    assert 'id="rulePackageVersionSelect"' in html
    assert "DL-PAYROLL.v1.1.1" in html
    assert "已验证科目 3" in html
    assert "/api/domestic-labor/rule-package" in js
    assert "renderRulePackage" in js
    assert "data-rule-category" in js
    assert "data-rule-subject" in js
    assert "核算规则包" in html
    assert "当前版本 1.1.1" in html
    assert "RULE PACKAGE · CURRENT" not in html
    assert "position: absolute" in html.split(".dl-rule-package-entry {", 1)[1].split("}", 1)[0]


def test_overseas_labor_page_is_separate_audit_workbench():
    html = OVERSEAS_LABOR_HTML.read_text(encoding="utf-8")
    js = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")
    css = STYLES_CSS.read_text(encoding="utf-8")

    assert "海外劳务工报账核对" in html
    assert 'data-module-id="overseas"' in html
    assert "permission-guard.js" in html
    assert "核对总金额与员工明细" in html
    assert "测试材料验证" in html
    assert "本地解析/OCR 提取证据" in html
    assert "AI 抽取供应商发票" not in html
    assert "overseas-labor.js" in html
    assert "/api/labor/runs" in js
    assert "runtimeGate" in js
    assert "formalTaskGate" in js
    assert "服务版本无法确认，正式操作已锁定" in js
    assert "字段映射" in html
    assert "结论" in html
    assert "仓库核对总览" in html
    assert ".overseas-labor-shell" in css


def test_permission_guard_blocks_direct_module_access_with_static_permissions():
    html = (ROOT / "bonus_platform" / "static" / "fbu-performance.html").read_text(encoding="utf-8")
    guard_js = PERMISSION_GUARD_JS.read_text(encoding="utf-8")

    assert 'data-module-id="fbu"' in html
    assert "permission-guard.js" in html
    assert "sigma-admin-console-draft-v3" in guard_js
    assert "/api/me" in guard_js
    assert "moduleAccess" in guard_js
    assert "rolePermissions" in guard_js
    assert "sigma-auth-context-v2" in guard_js
    assert "authFetchTimeoutMs" in guard_js
    assert "const authFetchTimeoutMs = 8 * 1000" in guard_js
    assert "ensureLoadingOverlay" in guard_js
    assert "html.permission-checking body > :not(.permission-loading-overlay)" not in guard_js
    assert 'credentials: "same-origin"' in guard_js
    assert 'cache: "no-store"' in guard_js
    assert 'const isSystemAdmin = currentRoleIds.includes("admin")' in guard_js
    assert "const canEnter = Boolean(module?.enabled) && (isSystemAdmin ||" in guard_js
    assert "selectedUserId" in guard_js
    assert "adminOnly ? null" not in guard_js
    assert "cdn.jsdelivr.net/npm/gsap" not in guard_js
    assert "无权限访问" in guard_js
    assert "后台管理仅系统管理员可访问" in guard_js
    assert "window.stop()" in guard_js


def test_server_guarded_pages_skip_the_duplicate_client_auth_request():
    guarded_pages = [
        RECRUITMENT_HTML,
        EMPLOYEE_PAYROLL_HTML,
        DOMESTIC_LABOR_HTML,
        ROOT / "bonus_platform" / "static" / "fbu-performance.html",
        OVERSEAS_LABOR_HTML,
        ADMIN_HTML,
    ]
    guard_js = PERMISSION_GUARD_JS.read_text(encoding="utf-8")

    for page in guarded_pages:
        html = page.read_text(encoding="utf-8")
        assert 'data-server-guarded="true"' in html
        assert "permission-guard.js?v=9" in html

    assert 'const serverGuarded = document.documentElement.dataset.serverGuarded === "true"' in guard_js
    assert "if (serverGuarded && !isDirectStaticPreview) return" in guard_js


def test_production_auth_does_not_block_static_startup_on_admin_db():
    app_py = APP_PY.read_text(encoding="utf-8")
    admin_store_py = (ROOT / "bonus_platform" / "engine" / "admin_store.py").read_text(encoding="utf-8")

    assert 'if not os.environ.get("VERCEL"):' in app_py
    assert "init_admin_store()" in app_py
    assert "connect_timeout=5" in admin_store_py


def test_login_page_provides_mock_feishu_ready_session_entry():
    html = LOGIN_HTML.read_text(encoding="utf-8")
    js = LOGIN_JS.read_text(encoding="utf-8")
    css = STYLES_CSS.read_text(encoding="utf-8")

    assert "登录西格玛工作台" in html
    assert "账号角色与模块权限" not in html
    assert "飞书应用已配置" not in html
    assert 'id="feishuLoginStatus"' not in html
    assert 'id="loginStatus"' not in html
    assert 'id="loginSmokeyCanvas"' in html
    assert "login-provider-icon" in html
    assert 'src="assets/bonus-logo-header-transparent.png"' in html
    assert 'src="assets/feishu-logo.png"' in html
    assert "开发调试：模拟用户登录" in html
    assert "使用飞书登录" in html
    assert "login.js" in html
    assert "fragmentSmokeySource" in js
    assert "initSmokeyBackground" in js
    assert "/api/auth/feishu/config" in js
    assert "/api/auth/feishu/login" in js
    assert "/api/me" in js
    assert "redirectIfAlreadyLoggedIn" in js
    assert "已登录，正在进入工作台" in js
    assert "/api/auth/mock-users" in js
    assert "/api/auth/mock-login" in js
    assert "mockEnabled" in js
    assert "mockLoginPanel.hidden = false" in js
    assert "sigma_session" not in js
    assert ".login-panel" in css
    assert ".login-smokey-canvas" in css
    assert ".login-provider-icon" in css
    assert ".login-provider-icon img" in css
    assert ".login-panel .dashboard-logo img" in css
    assert "background: transparent" in css.split(".login-panel .dashboard-logo img", 1)[1].split("}", 1)[0]
    assert "background: transparent" in css.split(".login-provider-icon", 1)[1].split("}", 1)[0]
    assert ".feishu-login-block" in css
    assert ".mock-login-panel" in css
    index_html = INDEX_HTML.read_text(encoding="utf-8")
    domestic_card = index_html.split('class="saas-module-card domestic-module"', 1)[1].split("</a>", 1)[0]
    fbu_card = index_html.split('class="saas-module-card fbu-module"', 1)[1].split("</a>", 1)[0]
    assert "试运行 · 已开放" in domestic_card
    assert "V0.7" in domestic_card
    assert "Available · 已上线" in fbu_card
    assert '<span class="module-version">V1.0</span>' in fbu_card
    assert "<dt>最新批次</dt><dd>2026-05</dd>" in fbu_card
    assert "真实回归" not in fbu_card
    assert "96.86%" not in fbu_card
    assert '{ id: "fbu", name: "FBU美洲绩效奖金核算", owner: "FBU美洲绩效核算管理员", enabled: true }' in ADMIN_JS.read_text(encoding="utf-8")
    with Image.open(LOGIN_SIGMA_LOGO) as logo:
        assert logo.mode == "RGBA"
        assert logo.getpixel((0, 0))[3] == 0
    with Image.open(FEISHU_LOGO) as logo:
        assert logo.mode == "RGBA"
        assert logo.getpixel((0, 0))[3] == 0

def test_china_employee_payroll_can_calculate_large_files_without_server_upload():
    html = EMPLOYEE_PAYROLL_HTML.read_text(encoding="utf-8")
    js = EMPLOYEE_PAYROLL_JS.read_text(encoding="utf-8")

    assert "xlsx.full.min.js" in html
    assert "calculateClientSideMealAllowance" in js
    assert "exportClientSideResult" in js
    assert "totalUploadSize > VERCEL_DIRECT_UPLOAD_WARNING_BYTES" in js
    assert "生产环境文件较大，将在浏览器本地解析核算，不上传 Excel 原文件。" in js
    assert "SOURCE_PUNCH_DATETIME_HEADERS" in js
    assert 'cell.z = "yyyy/m/d h:mm:ss"' in js
    assert "LBU速运事业部|战略运营部|BI组" in js
    assert "LBU战略运营部BI组纳入" in html
    assert '"深圳正常班"' in js
    assert "核算班次包含深圳正常班" in html


def test_release_info_marks_integration_branch_as_only_production_source():
    release_info = json.loads(RELEASE_INFO_JSON.read_text(encoding="utf-8"))

    assert release_info["releaseBranch"] == "codex/admin-module-release-consolidation"
    assert release_info["deployOwner"] == "integration-window-only"
    assert "Only deploy production from the integration branch" in release_info["policy"]
    assert "admin.html" in release_info["requiredStaticFiles"]
    assert "permission-guard.js" in release_info["requiredStaticFiles"]
    assert "fbu-performance.html" in release_info["requiredStaticFiles"]
    assert "fbu-performance.js" in release_info["requiredStaticFiles"]
    assert {module["id"] for module in release_info["modules"]} >= {
        "recruitment",
        "china-employee-payroll",
        "fbu",
        "overseas",
        "admin",
    }


def test_overseas_labor_upload_shows_and_prevalidates_configured_workbook_limit():
    html = OVERSEAS_LABOR_HTML.read_text(encoding="utf-8")
    js = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")

    assert "workbookUploadHint(0)" in js
    assert 'overseas-labor.js?v=37' in html
    assert "access.uploadLimits?.maxWorkbookFiles" in js
    assert "existing.workbook + pendingWorkbookCount > maxWorkbookFiles" in js
    assert "最多选择 ${maxWorkbookFiles} 个 Excel 文件" in js


def test_overseas_labor_direct_upload_finalizes_one_atomic_batch():
    script = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")
    upload_block = script[
        script.index("async function uploadFilesDirectlyToPrivateStorage"):
        script.index("async function loadSheets")
    ]

    assert "Promise.allSettled(intents.map((_intent, index) => uploadOne(index)))" in upload_block
    assert "Promise.allSettled(intents.map(uploadOne))" not in upload_block
    assert "upload-intents/batch-finalize" in upload_block
    assert "fileIds: intents.map((intent) => intent.fileId)" in upload_block
    assert "completedCount += 1" in upload_block
    assert "上传文件中有文件失败" in upload_block


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
    assert "UAT 私有存储" not in html
    assert "UAT 私有存储" not in js

    release_action_css = html[
        html.index(".overseas-labor-shell .worker-release-action {"):
        html.index(".overseas-labor-shell .drawer-chrome,")
    ]
    assert "width: 220px" in release_action_css
    assert "white-space: normal" in release_action_css
    assert "overflow-wrap: anywhere" in release_action_css
    assert "text-overflow: ellipsis" not in release_action_css


def test_overseas_labor_worker_status_opens_immediately_without_holding_header_button():
    js = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")

    assert 'labor.btnWorkerStatus.addEventListener("click", openLaborWorkerPanel);' in js
    assert 'withButtonLoading(labor.btnWorkerStatus, "正在读取"' not in js
    worker_panel = js[
        js.index("function openLaborWorkerPanel()"):
        js.index("function workerDeviceIsOnline")
    ]
    assert "void openLaborGovernance();" in worker_panel
    assert "await openLaborGovernance();" not in worker_panel


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
