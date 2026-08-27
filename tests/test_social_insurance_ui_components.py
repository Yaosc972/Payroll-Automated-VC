from __future__ import annotations

from pathlib import Path


STATIC_DIR = Path(__file__).resolve().parents[1] / "bonus_platform" / "static"


def _read(name: str) -> str:
    return (STATIC_DIR / name).read_text(encoding="utf-8")


def test_review_drawer_uses_searchable_combobox_instead_of_browser_datalist():
    script = _read("social-insurance.js")

    assert "createSearchableCombobox" in script
    assert "role', 'listbox'" in script
    assert "aria-expanded" in script
    assert "ArrowDown" in script
    assert "administrativeDivisionOptions" not in script


def test_workflow_components_have_stepper_dropzone_and_toast_regions():
    page = _read("social-insurance.html")
    script = _read("social-insurance.js")

    assert 'id="templateDropzone"' in page
    assert 'id="toastRegion"' in page
    assert "bindTemplateDropzone" in script
    assert "aria-current" in script
    assert "toast-item" in script


def test_native_controls_receive_sigma_component_styling():
    styles = _read("social-insurance.css")

    assert "appearance: none" in styles
    assert ".combobox-menu" in styles
    assert ".template-dropzone.dragging" in styles
    assert ".toast-stack" in styles


def test_social_insurance_assets_are_cache_busted_for_component_upgrade():
    page = _read("social-insurance.html")

    assert "social-insurance.css?v=44" in page
    assert "social-insurance.js?v=48" in page


def test_review_decision_uses_vertical_include_and_exclude_buttons():
    script = _read("social-insurance.js")
    styles = _read("social-insurance.css")
    render_block = script.split("const decisionCell = document.createElement('td');", 1)[1].split(
        "const person = document.createElement('td');", 1
    )[0]

    assert "decision-actions" in render_block
    assert "['include', '纳入']" in render_block
    assert "['exclude', '排除']" in render_block
    assert render_block.index("['include', '纳入']") < render_block.index("['exclude', '排除']")
    assert "aria-pressed" in render_block
    assert "checkbox" not in render_block
    decision_rule = styles.split(".decision-actions {", 1)[1].split("}", 1)[0]
    assert "flex-direction: column" in decision_rule


def test_quick_decision_shows_pending_state_before_waiting_and_rolls_back_on_failure():
    script = _read("social-insurance.js")
    handler = script.split("async function quickDecision", 1)[1].split(
        "function drawerFieldDefinitions", 1
    )[0]

    assert "decisionUpdates: new Map()" in script
    assert handler.index("state.decisionUpdates.set") < handler.index("await api")
    assert "state.decisionUpdates.delete" in handler
    assert "showToast(error.message, 'error')" in handler
    assert "status-pill pending" in script
    assert "?includePreflight=true" in handler
    assert "applyBatchBundle(payload.run, payload.preflight)" in handler


def test_silent_refresh_clears_a_batch_from_the_previous_selection():
    script = _read("social-insurance.js")

    assert "if (silent && state.run)" not in script
    assert "本周期尚未生成" in script


def test_subject_switch_clears_previous_batch_before_loading_the_new_run():
    script = _read("social-insurance.js")
    loader = script.split("async function loadSelectedSubjectRun", 1)[1].split("function renderMetrics", 1)[0]
    loading_state = "state.runLoading = true;\n    state.run = null;\n    renderRun();\n    byId('lastSyncLabel').textContent = '正在加载主体批次…';"
    request = "const payload = await api(path);"

    assert loading_state in loader
    assert loader.index(loading_state) < loader.index(request)
    assert "payload.run" in loader
    assert "payload.preflight" in loader
    assert "`${API_ROOT}/runs?${params.toString()}`" not in loader
    assert "`${API_ROOT}/releases/${encodeURIComponent(state.release.id)}/runs/current?" in loader


def test_confirmation_date_change_clears_the_old_batch_without_loading_storage():
    script = _read("social-insurance.js")
    binding = script.split("byId('confirmationDate').addEventListener('change'", 1)[1].split(";", 1)[0]

    assert "resetSelectedRunForConfirmationDate" in binding
    assert "loadSelectedSubjectRun" not in binding
    assert "function defaultConfirmationDate" in script
    assert "defaultConfirmationDate(byId('periodEnd').value)" in script


def test_subject_counts_distinguish_current_beisen_candidates_from_the_saved_batch():
    page = _read("social-insurance.html")
    script = _read("social-insurance.js")

    assert "<span>本批人数</span>" in page
    assert "北森当前" in script
    assert "基线保留" in script
    assert "本批" in script
    assert "monthlyBaseline?.baselineOnlyCount" in script


def test_subject_switch_uses_an_in_memory_bundle_and_a_loading_skeleton():
    script = _read("social-insurance.js")
    styles = _read("social-insurance.css")

    assert "batchCache: new Map()" in script
    assert "state.batchCache.get" in script
    assert "batch-loading-placeholder" in script
    assert ".batch-loading-placeholder" in styles
    assert "batch-loading-shimmer" in styles


def test_initial_page_bootstraps_from_the_latest_published_integration_without_polling():
    script = _read("social-insurance.js")
    initializer = script.split("async function initialize()", 1)[1].split("initialize();", 1)[0]

    assert "`${API_ROOT}/bootstrap`" in initializer
    assert "runs?limit=1" not in initializer
    assert "loadContractSubjects" not in initializer
    assert "recent-beisen-runs" not in script
    assert "scheduleContractSubjectCompletion" not in script


def test_run_update_time_is_rendered_in_shanghai_business_time():
    script = _read("social-insurance.js")

    assert "function formatRunTimestamp" in script
    assert "timeZone: 'Asia/Shanghai'" in script
    assert "formatRunTimestamp(state.run.updatedAt)" in script


def test_primary_batch_and_metric_cards_have_no_vertical_accent_bars():
    styles = (STATIC_DIR / "social-insurance.css").read_text(encoding="utf-8")

    assert ".batch-console::before" not in styles
    assert ".metrics article::before" not in styles
    assert ".metrics .success::before" not in styles
    assert ".metrics .warning::before" not in styles
    assert ".metrics .muted::before" not in styles


def test_next_action_cards_have_no_decorative_edge_bars():
    styles = _read("social-insurance.css")

    assert ".action-card::before" not in styles
    assert ".action-card.ready::before" not in styles
    rpa_rule = styles.split(".rpa-card {", 1)[1].split("}", 1)[0]
    assert "border-top" not in rpa_rule


def test_batch_metrics_use_compact_single_line_label_and_number_layout():
    page = _read("social-insurance.html")
    styles = _read("social-insurance.css")

    metrics_markup = page.split('<section class="metrics"', 1)[1].split("</section>", 1)[0]
    assert "<small>" not in metrics_markup
    metric_card_rule = styles.split(".metrics article", 1)[1].split("}", 1)[0]
    assert "align-items: baseline" in metric_card_rule
    assert "justify-content: center" in metric_card_rule
    assert "gap: 16px" in metric_card_rule
    assert "min-height: 62px" in metric_card_rule
    assert "font-variant-numeric: tabular-nums" in styles


def test_batch_overview_uses_quiet_icons_and_borderless_metrics():
    page = _read("social-insurance.html")
    script = _read("social-insurance.js")
    styles = _read("social-insurance.css")

    sync_button = page.split('id="syncButton"', 1)[1].split("</button>", 1)[0]
    assert "↻" not in sync_button
    assert "button-batch-icon" in sync_button
    assert "button-spinner" in script
    assert ".button-spinner" in styles
    assert ".stage.complete > b::after" not in styles
    complete_badge_rule = styles.split(".stage.complete > b {", 1)[1].split("}", 1)[0]
    assert "font-size: 0" not in complete_badge_rule
    stage_badge_rule = styles.split(".stage > b {", 1)[1].split("}", 1)[0]
    assert "place-items: center" in stage_badge_rule
    assert "line-height: 1" in stage_badge_rule
    metric_rule = styles.split(".metrics article", 1)[1].split("}", 1)[0]
    assert "border-right" not in metric_rule


def test_workflow_uses_connected_chevron_stepper():
    page = _read("social-insurance.html")
    styles = _read("social-insurance.css")

    stage_markup = page.split('<nav class="stage-rail"', 1)[1].split("</nav>", 1)[0]
    assert stage_markup.count('class="stage') == 5
    assert '<i aria-hidden="true"></i>' not in stage_markup
    assert ".stage:not(:last-child)::before" in styles
    assert ".stage:not(:last-child)::after" in styles
    assert "border-left-color: var(--stage-bg)" in styles
    assert "grid-template-columns: repeat(5, minmax(0, 1fr))" in styles


def test_review_panel_stretches_to_align_with_the_action_column_bottom():
    styles = _read("social-insurance.css")

    review_rule = styles.split(".review-panel {", 1)[1].split("}", 1)[0]
    assert "align-self: stretch" in review_rule
    assert "display: flex" in review_rule
    assert "flex-direction: column" in review_rule
    table_rule = styles.split(".table-wrap {", 1)[1].split("}", 1)[0]
    assert "flex: 1 1 0" in table_rule
    footer_rule = styles.split(".table-footer {", 1)[1].split("}", 1)[0]
    assert "margin-top: auto" in footer_rule


def test_wide_review_table_has_persistent_mouse_friendly_horizontal_navigation():
    page = _read("social-insurance.html")
    script = _read("social-insurance.js")
    styles = _read("social-insurance.css")

    for element_id in ("tableScrollDockSlot", "tableScrollDock", "tableScrollLeft", "tableScrollRange", "tableScrollRight"):
        assert f'id="{element_id}"' in page
    assert "bindTableHorizontalControl" in script
    assert "syncTableHorizontalControl" in script
    assert "syncFloatingTableTools" in script
    assert "panelRect.top <= stickyTop + 1" in script
    assert "tableScrollRange" in script
    assert "is-floating" in script
    assert "scrollBy" in script
    assert ".table-scroll-dock-slot" in styles
    assert ".table-scroll-dock" in styles
    assert ".table-scroll-dock.is-floating" in styles
    assert "::-webkit-slider-thumb" in styles
    assert ".table-wrap::-webkit-scrollbar" in styles
    assert "height: 0" in styles.split(".table-wrap::-webkit-scrollbar", 1)[1].split("}", 1)[0]


def test_review_table_keeps_headers_and_person_identity_visible_while_scrolling():
    page = _read("social-insurance.html")
    script = _read("social-insurance.js")
    styles = _read("social-insurance.css")

    assert 'id="tableStickyHeader"' in page
    assert "append('处理', 'sticky-key sticky-decision')" in script
    assert "append('姓名', 'sticky-key sticky-person')" in script
    assert "syncFloatingTableTools" in script
    assert "sticky-decision" in script
    assert "sticky-person" in script
    assert ".table-sticky-header.is-visible" in styles
    assert ".floating-key-heading" in styles
    assert "floating-person-heading" in script
    assert ".sticky-decision" in styles
    assert ".sticky-person" in styles


def test_review_table_uses_content_fitted_compact_identity_columns():
    page = _read("social-insurance.html")
    script = _read("social-insurance.js")
    styles = _read("social-insurance.css")

    assert "{ label: '工号', value: (employee) => employee.source?.jobNumber, className: 'mono-cell job-number-cell' }" in script
    assert "append(column.label, column.className?.includes('job-number') ? 'job-number-heading' : '')" in script
    assert "--review-person-width: 104px" in styles
    assert "--review-action-width: 180px" in styles
    assert ".review-field-cell.job-number-cell" in styles
    assert "table { width: max-content; min-width: 100%;" in styles
    assert "min-width: 4300px" not in styles


def test_review_action_keeps_long_status_and_edit_button_on_one_line():
    styles = _read("social-insurance.css")

    action_cell_rule = styles.split("td.sticky-action", 1)[1].split("}", 1)[0]
    assert "white-space: nowrap" in action_cell_rule


def test_review_table_matches_offline_employee_report_field_order():
    script = _read("social-insurance.js")

    expected_source_headers = [
        "工号", "身份证号码", "合同主体", "工作地点", "雇佣关系", "性别",
        "手机号码", "入职日期", "离职日期", "社保缴交基数", "公积金缴交基数", "公积金个人比例", "社保缴纳地",
        "社保电脑号", "公积金号", "户口地址", "户籍所在地", "户口类别", "最高学历", "现居住地址", "民族",
        "在职状态", "邮箱", "员工考勤地点", "是否虚拟员工", "变动说明",
    ]
    source_definition = script.split("const SOURCE_COLUMNS = [", 1)[1].split("];", 1)[0]
    positions = [source_definition.index(f"['{header}'") for header in expected_source_headers]
    assert positions == sorted(positions)
    for source_key in (
        "jobNumber", "gender", "lastWorkDate", "housingContributionRate", "socialContributionPlace", "birthplace",
        "domicileType", "education", "currentAddress", "employeeStatus", "email", "employmentPlace", "virtualEmployee",
        "changeDescription",
    ):
        assert f"'{source_key}'" in source_definition
    assert "maskPhone" in script
    assert "maskEmail" in script
    assert "maskAddress" not in script
    assert "'address-field-cell', 'address'" not in script
    assert "colSpan = columns.length + 3" in script


def test_contract_subject_uses_compact_searchable_picker_instead_of_native_popup():
    page = _read("social-insurance.html")
    script = _read("social-insurance.js")
    styles = _read("social-insurance.css")

    assert 'id="subjectTrigger"' in page
    assert 'id="subjectSearch"' in page
    assert 'id="subjectPickerOptions"' in page
    assert '<select id="subject" hidden' in page
    assert "renderSubjectPickerOptions" in script
    assert "closeSubjectPicker" in script
    assert "max-height: 268px" in styles


def test_social_insurance_header_uses_current_hras_brand_and_glass_treatment():
    page = _read("social-insurance.html")
    rules_page = _read("social-insurance-rules.html")
    styles = _read("social-insurance.css")
    rules_styles = _read("social-insurance-rules.css")

    for source in (page, rules_page):
        assert "HRAS 全球薪酬核算工作台" in source
        assert "HRAS GLOBAL PAYROLL WORKBENCH" in source
        assert "Global Payroll Operations" not in source
        assert "Σ Workbench" not in source
        assert "西格玛" not in source
    assert "社保报盘" in page
    assert "社保增员工作台" not in page
    assert ">新建批次<" in page
    assert ">新建增员批次<" not in page
    assert 'class="module-mark"' not in page
    assert "backdrop-filter: blur" in styles.split(".si-topbar", 1)[1].split("}", 1)[0]
    assert "background: #fff" not in styles.split(".brand-logo", 1)[1].split("}", 1)[0]
    assert "background: #fff" not in rules_styles.split(".brand-logo", 1)[1].split("}", 1)[0]


def test_only_brand_area_keeps_english_headings():
    page = _read("social-insurance.html")
    rules_page = _read("social-insurance-rules.html")
    removed_titles = (
        "MVP", "REVIEW QUEUE", "NEXT ACTIONS", "STEP 03", "STEP 04",
        "EMPLOYEE REVIEW", "SUPPLEMENTAL ENROLLMENT", "BUSINESS RULEBOOK", "VERSION HISTORY", "RPA待接入",
    )

    for title in removed_titles:
        assert title not in page
        assert title not in rules_page
    assert page.count("HRAS GLOBAL PAYROLL WORKBENCH") == 1
    assert rules_page.count("HRAS GLOBAL PAYROLL WORKBENCH") == 1


def test_unified_enrollment_review_shows_coverage_tasks_and_processing_routes():
    page = _read("social-insurance.html")
    script = _read("social-insurance.js")

    assert "全国增员 · 北森数据源" in page
    assert all(label in script for label in ("label: '社保医保'", "['公积金', 'housingStatus'"))
    assert 'id="routePlan"' in page
    assert 'id="coverageTaskSummary"' in page
    assert "renderProcessingPlan" in script
    assert "coverageStatusSummary" in script


def test_batch_form_helper_text_stays_in_flow_and_layout_is_responsive():
    styles = _read("social-insurance.css")

    confirmation_rule = styles.split(".confirmation-date-field > small", 1)[1].split("}", 1)[0]
    assert "position: absolute" not in confirmation_rule
    assert "display: block" in confirmation_rule
    assert "grid-template-columns: minmax(320px, .9fr) 170px minmax(300px, 1.15fr) 210px" in styles
    assert "@media (max-width: 1160px)" in styles
    assert "@media (max-width: 640px)" in styles
    body_rule = styles.split("body {", 1)[1].split("}", 1)[0]
    assert "margin: 0" in body_rule
    assert "min-width: 0" in body_rule


def test_period_changes_only_accept_the_latest_subject_request_and_mark_old_batch():
    page = _read("social-insurance.html")
    script = _read("social-insurance.js")

    assert 'id="periodContextNotice"' in page
    assert "subjectRequestSequence" in script
    assert "scheduleContractSubjectLoad" in script
    assert "当前显示的是上一批次" in script
    assert "正在加载当前周期合同主体" in script


def test_batch_creation_has_one_business_action_and_compact_heading():
    page = _read("social-insurance.html")
    script = _read("social-insurance.js")
    styles = _read("social-insurance.css")

    assert 'id="refreshSubjectsButton"' not in page
    assert 'id="retrySubjectsButton"' in page
    assert "生成本批名单" in page
    assert "一键同步北森" not in page
    assert "NEW ENROLLMENT BATCH" not in page
    assert "受控数据处理" not in page
    section_title = page.split('<div class="section-title">', 1)[1].split('</div>\n          <div class="batch-form">', 1)[0]
    assert 'id="beisenPoolStatus"' not in section_title
    assert 'class="batch-context"' not in page
    assert "scheduleContractSubjectLoad(byId('subject').value, 0, true)" in script
    assert ".section-title-meta" in styles


def test_period_generation_creates_all_subject_batches_and_subject_switch_loads_existing_batch():
    page = _read("social-insurance.html")
    script = _read("social-insurance.js")

    assert "生成全部主体批次" in page
    assert "使用最新集成快照并按主体拆分" in page
    assert "runs/sync-all" in script
    assert "background-all-subject-snapshot" in script
    assert "使用定时快照生成" in script
    assert "实时同步北森并生成" in script
    assert "loadSelectedSubjectRun" in script
    assert "periodStart" in script
    assert "confirmationDate" in script


def test_page_never_polls_partial_recent_subjects():
    script = _read("social-insurance.js")

    assert "scheduleContractSubjectCompletion" not in script
    assert "recent-beisen-runs" not in script
    assert "后台正在补齐完整主体" not in script


def test_initial_subject_selection_comes_from_the_atomic_published_release():
    script = _read("social-insurance.js")

    assert "applyContractSubjects(subjects, payload.selectedSubject || '')" in script
    assert "state.run?.subject || config.defaultSubject" not in script
    assert "recent.runs?.[0]?.subject" not in script


def test_published_subject_loading_does_not_replace_the_period_default_confirmation_date():
    script = _read("social-insurance.js")
    loader = script.split("async function loadContractSubjects", 1)[1].split(
        "function scheduleContractSubjectLoad", 1
    )[0]

    assert "byId('confirmationDate').value = payload.confirmationDate" not in loader


def test_batch_uses_explicit_confirmation_date_for_departure_cutoff():
    page = _read("social-insurance.html")
    script = _read("social-insurance.js")

    assert 'id="confirmationDate"' in page
    assert "名单确认日" in page
    assert "confirmationDate: byId('confirmationDate').value" in script


def test_period_and_confirmation_dates_use_consistent_calendar_popovers():
    page = _read("social-insurance.html")
    script = _read("social-insurance.js")

    assert 'id="periodRangeTrigger"' in page
    assert 'id="periodCalendar"' in page
    assert 'id="periodCalendarMonths"' in page
    assert 'id="confirmationDateTrigger"' in page
    assert 'id="confirmationCalendar"' in page
    assert 'id="confirmationCalendarMonths"' in page
    assert 'id="periodStart" type="hidden"' in page
    assert 'id="periodEnd" type="hidden"' in page
    assert 'id="confirmationDate" type="hidden"' in page
    assert 'id="periodStart" type="date"' not in page
    assert "renderCalendarMonth" in script
    assert "openDatePicker('period')" in script
    assert "openDatePicker('confirmation')" in script


def test_supplement_enrollment_uses_beisen_search_and_fixed_business_reasons():
    page = _read("social-insurance.html")
    script = _read("social-insurance.js")

    assert 'id="openSupplementButton"' in page
    assert 'id="supplementDialog"' in page
    assert 'value="prior_period_omission"' in page
    assert 'value="delayed_enrollment"' in page
    assert 'value="back_payment"' not in page
    assert "/supplement-candidates/search" in script
    assert "/supplements" in script


def test_supplement_search_exposes_running_and_persistent_failure_states():
    page = _read("social-insurance.html")
    script = _read("social-insurance.js")

    assert 'aria-busy="false"' in page
    assert "正在查找人员" in script
    assert "优先查找平台最近的北森同步记录" in script
    assert "查找失败，请重试" in script
    assert "无法连接 HRAS 本地服务" in script


def test_sync_completion_refreshes_supplement_action_state():
    script = _read("social-insurance.js")

    assert "finally { state.operation = null; setBusy(button, false); renderActions(); }" in script


def test_review_toolbar_can_export_all_enrollment_employees_in_one_workbook():
    page = _read("social-insurance.html")
    script = _read("social-insurance.js")
    styles = _read("social-insurance.css")

    assert 'id="auditExportButton"' in page
    assert "导出审核清单" in page
    assert "/audit-export" in script
    assert "downloadAuditExport" in script
    assert 'id="exportTransition"' in page
    assert 'aria-live="polite"' in page
    assert "async function downloadExportFile" in script
    assert "response.blob()" in script
    assert "URL.createObjectURL" in script
    assert "aria-busy" in script
    assert "exportTransitionSequence" in script
    assert "window.location.assign" not in script
    assert ".export-transition" in styles
    assert ".export-transition.active" in styles
    assert "export-track" in styles


def test_review_supports_business_template_and_source_views_with_route_preflight():
    page = _read("social-insurance.html")
    script = _read("social-insurance.js")
    styles = _read("social-insurance.css")

    for label in ("业务审核", "模板字段", "北森源数据"):
        assert f">{label}<" in page
    for element_id in ("templateRouteSelect", "preflightCard", "preflightList", "missingExportButton", "templateUploadRoute"):
        assert f'id="{element_id}"' in page
    assert "currentTableColumns" in script
    assert "ensurePreflight" in script
    assert "/preflight" in script
    assert "/missing-export" in script
    assert "/generate-package" in script
    assert ".preflight-item" in styles
    assert ".review-view-switch" in styles


def test_drawer_uses_route_specific_field_order_and_shows_field_origins():
    page = _read("social-insurance.html")
    script = _read("social-insurance.js")
    styles = _read("social-insurance.css")

    assert 'id="drawerRouteTabs"' in page
    assert "renderDrawerTemplateFields" in script
    assert "employee.templateReports?.[state.editingRoute]" in script
    assert "field-origin" in script
    assert "templateRoute" in script
    assert "templateReport" in script
    assert ".drawer-route-tabs" in styles
    assert ".missing-required-field" in styles


def test_beisen_candidate_pool_status_only_appears_inside_supplement_dialog():
    page = _read("social-insurance.html")
    script = _read("social-insurance.js")

    section_title = page.split('<div class="section-title">', 1)[1].split('</div>\n          <div class="batch-form">', 1)[0]
    supplement_dialog = page.split('id="supplementDialog"', 1)[1]
    assert 'id="beisenPoolState"' not in section_title
    assert 'id="supplementPoolState"' in supplement_dialog
    assert 'id="supplementPoolDetail"' in supplement_dialog
    assert "loadSupplementPoolStatus" in script
    assert "/supplement-candidates/status" in script
    assert "历史候选已准备" in script
    assert "首次查找时自动加载" in script
    assert "payload.state === 'error'" in script
    assert "window.setTimeout(loadSupplementPoolStatus, 30000)" in script
    initialize = script.split("async function initialize()", 1)[1]
    assert "loadSupplementPoolStatus();" not in initialize
    open_dialog = script.split("function openSupplementDialog()", 1)[1].split("function closeSupplementDialog()", 1)[0]
    assert "loadSupplementPoolStatus();" in open_dialog


def test_departure_snapshot_warning_explains_its_business_decision():
    script = _read("social-insurance.js")

    assert "该提示用于确认离职数据是否覆盖到名单确认日" in script


def test_business_rules_have_a_separate_versioned_entry():
    workbench = _read("social-insurance.html")
    rules_page = _read("social-insurance-rules.html")
    rules_script = _read("social-insurance-rules.js")

    assert 'href="social-insurance-rules.html"' in workbench
    assert ">点击查看业务规则</a>" in workbench
    assert "本地受控处理" not in workbench
    assert 'id="rulesVersion"' in rules_page
    assert 'id="rulesUpdatedAt"' in rules_page
    assert "/api/social-insurance/rules" in rules_script
    assert "人员怎么进入本期名单" in rules_page
