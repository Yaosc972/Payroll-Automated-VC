import hashlib
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
FBU_HTML = ROOT / "bonus_platform" / "static" / "fbu-performance.html"
FBU_JS = ROOT / "bonus_platform" / "static" / "fbu-performance.js"


def _html() -> str:
    return FBU_HTML.read_text(encoding="utf-8")


def _js() -> str:
    return FBU_JS.read_text(encoding="utf-8")


def test_fbu_html_javascript_version_matches_content_hash():
    digest = hashlib.sha256(FBU_JS.read_bytes()).hexdigest()[:12]

    assert f'fbu-performance.js?v={digest}' in _html()


def test_activity_navigation_does_not_treat_stale_results_as_completed():
    js = _js()

    assert "activity.status === 'completed' || Array.isArray(activity.results)" not in js


def test_activity_detail_uses_six_plain_language_steps():
    js = _js()

    for label in ["人员核对", "考勤工时", "薪资数据", "绩效数据", "核算检查", "确认导出"]:
        assert label in js

    assert "const ACTIVITY_STEPS" in js
    assert "function setActivityStep" in js
    assert "function renderActivityStepper" in js
    assert "activity-step-status" in js


def test_top_navigation_does_not_contain_fbu_workflow_entries():
    html = _html()
    body = html.split("<body>", 1)[1]
    top_nav = body.split('<nav class="top-module-nav"', 1)[1].split("</nav>", 1)[0]

    assert '<aside class="sidebar">' not in body

    for forbidden in ["考勤汇总", "薪资匹配", "绩效明细", "核算结果", "异常队列", "基础数据"]:
        assert forbidden not in top_nav

    assert 'data-page="activities"' in top_nav
    assert 'data-page="workbench"' in top_nav


def test_upload_entries_are_owned_by_exactly_one_step():
    js = _js()

    assert "const STEP_MATERIALS" in js
    for key in [
        "roster",
        "attendance",
        "previousAttendance",
        "supplementalLeave",
        "previousSalary",
        "currentSalary",
        "salaryAdjustments",
        "transferHistory",
        "performance",
    ]:
        assert js.count(f"materialKey: '{key}'") == 1

    assert "上月薪资档案" in js
    assert "当月薪资档案" in js
    assert "全量调薪流程" in js
    assert "人事调动记录" in js
    assert "/import-salary-history-material" in js
    assert "formData.append('material_type', type)" in js
    assert "formData.append('file', file)" in js
    assert "/import-transfer-history" in js

    for copy in [
        "上传OEHR当月考勤日报表",
        "上传OEHR上月考勤日报表",
        "上传线下sickpay与年假补充数据",
        "上传OEHR上月薪资档案（含离职）",
        "上传OEHR当月最新薪资档案（含离职）",
        "上传当前划分区域全量调薪管理导出",
        "上传覆盖核算月及相邻生效日的当前划分区域调动记录",
        "上传OEHR当月绩效报表",
    ]:
        assert copy in js


def test_previous_attendance_upload_is_always_visible_as_optional_material():
    js = _js()
    material = js.split(
        "{ materialKey: 'previousAttendance'", 1
    )[1].split("},", 1)[0]

    assert "required: false" in material
    assert "conditional:" not in material


def test_attendance_step_recovers_missing_rows_without_hiding_hourly_policy():
    js = _js()
    needs = js.split("function buildNeedsForStep", 1)[1].split(
        "function renderNeedsPanel", 1
    )[0]
    policy = js.split("function renderHourlyRatePolicySection", 1)[1].split(
        "async function", 1
    )[0]

    assert "activity.attendance_file && !hasUsableAttendanceView(activity)" in needs
    assert "请重新上传考勤日报" in needs
    assert "!hasUsableAttendanceView(activity) && !hasHourlyRatePolicyRows(activity)" in policy


def test_upload_entries_use_inline_timeline_progress_not_react_stack():
    html = _html()
    js = _js()

    for required in [
        "workbenchUploadStates",
        "startWorkbenchUploadProgress",
        "finishWorkbenchUploadProgress",
        "failWorkbenchUploadProgress",
        "clearWorkbenchUpload",
        "data-upload-type",
        "material-progress",
        "material-status-dot",
    ]:
        assert required in f"{html}\n{js}"

    for forbidden in [
        "TimelineUpload",
        "lucide-react",
        "@radix-ui/react-progress",
        "components/ui",
    ]:
        assert forbidden not in f"{html}\n{js}"


def test_workbench_upload_feedback_stays_inline_not_global_toast():
    html = _html()
    js = _js()

    for marker in [
        "async function uploadWorkbenchRosterFile",
        "async function uploadWorkbenchFile",
        "function handleWorkbenchUploadChange",
        "function clearWorkbenchUpload",
    ]:
        section = js.split(marker, 1)[1].split("\nfunction ", 1)[0]
        assert "showNotification(" not in section

    assert "material-action-note" in html
    assert "actionNote" in js


def test_previous_attendance_waits_then_auto_uploads_after_current_attendance():
    js = _js()

    render_material_row = js.split("function renderMaterialRow", 1)[1].split(
        "function renderStepMaterials", 1
    )[0]
    handle_upload_change = js.split("function handleWorkbenchUploadChange", 1)[1].split(
        "function clearWorkbenchUpload", 1
    )[0]
    complete_upload_job = js.split("async function completeFbuUploadJob", 1)[1].split(
        "async function pollFbuUploadJob", 1
    )[0]
    pending_upload = js.split(
        "async function flushPendingPreviousAttendanceUpload", 1
    )[1].split("async function completeFbuUploadJob", 1)[0]

    assert "material.uploadType === 'previousAttendance'" in render_material_row
    assert "? '选择文件'" in render_material_row
    assert "等待当月考勤完成后自动上传" in js
    assert "state.workbenchPreviousAttendanceFile = file;" in handle_upload_change
    assert "uploadWorkbenchPreviousAttendanceFile(file)" in pending_upload
    assert "await flushPendingPreviousAttendanceUpload(metadata.runId)" in complete_upload_job


def test_attendance_materials_place_current_and_previous_attendance_side_by_side():
    html = _html()
    js = _js()

    render_step_materials = js.split("function renderStepMaterials", 1)[1].split(
        "function getTableFilter", 1
    )[0]
    assert "attendance-material-list" in render_step_materials
    assert "stepKey === 'attendance'" in render_step_materials
    assert ".attendance-material-list {" in html
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in html
    assert '.attendance-material-list [data-upload-type="supplementalLeave"]' in html
    assert "grid-column: 1 / -1;" in html


def test_rule_confirmation_sits_beside_upload_materials():
    html = _html()
    js = _js()
    attendance_section = js.split("function renderAttendanceStep", 1)[1].split("function renderSalaryStep", 1)[0]
    salary_section = js.split("function renderSalaryStep", 1)[1].split("function renderPerformanceStep", 1)[0]

    assert "step-rule-grid" in attendance_section
    assert "renderStepMaterials('attendance', activity)" in attendance_section
    assert "renderMaintainedRuleList('workHour', activity)" in attendance_section
    assert attendance_section.index("renderStepMaterials('attendance', activity)") < attendance_section.index("renderMaintainedRuleList('workHour', activity)")

    assert "step-rule-grid" in salary_section
    assert "renderStepMaterials('salary', activity)" in salary_section
    assert "renderMaintainedRuleList('fixedBase', activity)" in salary_section
    assert salary_section.index("renderStepMaterials('salary', activity)") < salary_section.index("renderMaintainedRuleList('fixedBase', activity)")

    assert ".step-rule-grid {" in html
    assert "grid-template-columns: minmax(0, 1.12fr) minmax(360px, 0.88fr);" in html


def test_success_feedback_does_not_use_global_toast():
    html = _html()
    js = _js()

    show_notification = js.split("function showNotification", 1)[1].split("// ═══ Init", 1)[0]
    assert "if (type === 'success') return;" in show_notification
    assert "操作完成" not in show_notification
    assert "action-inline-note" in html


def test_supplemental_leave_is_required_attendance_material():
    js = _js()

    step_match = re.search(r"[\"']考勤工时[\"']", js)
    assert step_match, "缺失考勤工时步骤定义"

    nearby = js[step_match.start():step_match.start() + 1600]
    assert (
        re.search(r"materialKey\s*:\s*['\"]supplementalLeave['\"].{0,260}tag\s*:\s*['\"]必传['\"]", nearby, re.S)
        or re.search(r"tag\s*:\s*['\"]必传['\"].{0,260}materialKey\s*:\s*['\"]supplementalLeave['\"]", nearby, re.S)
    ), (
        "考勤工时材料块未将补充假勤设置为必传"
    )


def test_maintained_lists_replace_rule_upload_in_activity_flow():
    html = _html()
    js = _js()

    assert "workbenchUploadBaseOverrides" not in html
    assert "function renderMaintainedRuleList" in js
    assert "function confirmMaintainedRuleList" in js
    assert "96工时制员工" in js
    assert "固定基数人员" in js
    assert "确认名单" in js
    assert "编辑名单" in js
    assert "管理名单" not in js


def test_maintained_lists_have_inline_editor_instead_of_placeholder():
    js = _js()

    maintained_section = js.split("function renderMaintainedRuleList", 1)[1].split(
        "function buildWorkbenchTasks", 1
    )[0]
    assert "名单维护入口保留" not in maintained_section
    assert "function renderMaintainedRuleEditor" in js
    assert "function saveMaintainedRuleList" in js
    assert "function addMaintainedRuleRow" in js
    assert "openMaintainedRuleDialog" in js
    assert "ruleListDialog" in _html()
    assert "managed-rule-input" in js
    assert "<select" not in maintained_section


def test_slow_form_actions_show_busy_state_and_prevent_duplicate_submits():
    js = _js()

    assert "maintainedRulePending: ''" in js
    assert "salaryVerificationPendingIds: new Set()" in js
    assert "if (state.maintainedRulePending)" in js
    assert "state.salaryVerificationPendingIds.has(normalizedId)" in js
    assert "确认中…" in js
    assert "保存中…" in js
    assert "处理中…" in js
    assert 'aria-busy="true"' in js


def test_attendance_step_requests_compact_view_instead_of_daily_detail():
    js = _js()
    sections = js.split("const ACTIVITY_STEP_SECTIONS", 1)[1].split(
        "const SALARY_HISTORY_MATERIAL_FIELDS", 1
    )[0]
    attendance = sections.split("attendance:", 1)[1].split("salary:", 1)[0]

    assert "'attendance_view_data'" in attendance
    assert "'attendance_data'" not in attendance


def test_performance_upload_and_leave_supplement_are_side_by_side():
    html = _html()
    js = _js()
    section = js.split("function renderPerformanceStep", 1)[1].split(
        "function renderStepContent", 1
    )[0]

    assert "performance-step-grid" in section
    assert ".performance-step-grid" in html
    assert "renderStepMaterials('performance', activity)" in section
    assert "renderPerformanceInlineSupplement(activity)" in section


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

    for forbidden in ["诊断", "阻断项", "审计记录", "人工确认项", "口径", "链路", "规则命中", "来源映射", "异常记录", "上下文"]:
        assert forbidden not in searchable


def test_activity_stepper_shows_status_without_summary():
    html = _html()
    js = _js()

    render_stepper = js.split("function renderActivityStepper", 1)[1].split("function renderStepHeader", 1)[0]
    assert "activity-step-status" in render_stepper
    assert "activity-step-summary" not in render_stepper
    assert "getStepSummary" not in render_stepper

    status_style = re.search(r"\.payroll-activity-stepper \.activity-step-status\s*\{([^}]*)\}", html)
    assert status_style, "步骤状态样式缺失"
    assert re.search(r"font-size\s*:\s*11px\s*;", status_style.group(1))
    assert ".payroll-activity-stepper .activity-step-summary" not in html


def test_workbench_uses_flat_activity_controls():
    html = _html()
    js = _js()
    combined = f"{html}\n{js}"

    for marker in [
        "activity-title-main",
        "activity-title-tag",
        "activity-return-button",
        "payroll-activity-stepper",
        "step-info-strip",
        "activity-table-toolbar",
        "activity-table-search",
        "setWorkbenchStepSearch",
    ]:
        assert marker in combined

    assert ".activity-step.done" in html
    assert ".activity-step.warning" in html

    render_workbench = js.split("function renderWorkbench", 1)[1].split("function renderActivities", 1)[0]
    assert "返回活动列表" not in render_workbench


def test_activity_table_search_uses_compact_svg_icon():
    html = _html()
    js = _js()

    assert "activity-search-icon-svg" in js
    assert "viewBox=\"0 0 16 16\"" in js
    assert 'const inputId = `workbenchStepSearchInput-${type}`' in js
    assert 'for="${escapeHtml(inputId)}"' in js
    assert 'id="${escapeHtml(inputId)}"' in js
    assert "placeholder = '搜索工号、姓名'" in js
    assert "activity-table-search-clear" in js
    assert ".activity-table-search-icon::after" not in html
    assert "::-webkit-search-decoration" in html
    assert "::-webkit-search-cancel-button" in html
    set_search = js.split("function setWorkbenchStepSearch", 1)[1].split("function toggleWorkbenchResultDetail", 1)[0]
    assert "captureInputFocus()" in set_search
    assert "restoreInputFocus(" in set_search
    assert "restoreInputFocus(focusSnapshot)" in set_search

    search_styles = re.findall(r"\.activity-table-search\s*\{([^}]*)\}", html)
    assert search_styles, "activity table search style should exist"
    assert any(re.search(r"height\s*:\s*28px\s*;", block) for block in search_styles)
    assert any(
        re.search(r"width\s*:\s*clamp\(160px,\s*16vw,\s*220px\)\s*;", block)
        for block in search_styles
    )

    icon_style = re.search(r"\.activity-table-search-icon\s*\{([^}]*)\}", html)
    assert icon_style, "activity table search icon style should exist"
    assert re.search(r"pointer-events\s*:\s*none\s*;", icon_style.group(1))

    input_style = re.search(r"\.activity-table-search-input\s*\{([^}]*)\}", html)
    assert input_style, "activity table search input style should exist"
    assert re.search(r"position\s*:\s*relative\s*;", input_style.group(1))
    assert re.search(r"z-index\s*:\s*1\s*;", input_style.group(1))


def test_activity_table_search_debounces_and_preserves_composition_events():
    js = _js()
    section = js.split("function setWorkbenchStepSearch", 1)[1].split("function setCheckTab", 1)[0]
    search_markup = js.split("function renderWorkbenchTableSearch", 1)[1].split(
        "function renderCompactEmployeeTable", 1
    )[0]

    assert "filterTimers[`workbench:${type}`]" in section
    assert "composingFilterInputs" in js
    assert "getTablePagination(type).page = 1" in section
    assert "renderWorkbenchCurrentStep();" in section
    assert "restoreInputFocus(focusSnapshot);" in section
    assert "window.setTimeout" in section
    assert "260" in section
    assert "handleWorkbenchStepSearchInput(event, ${formatJsArg(type)})" in search_markup
    assert "handleWorkbenchStepSearchCompositionStart(event, ${formatJsArg(type)})" in search_markup
    assert "handleWorkbenchStepSearchCompositionEnd(event, ${formatJsArg(type)})" in search_markup
    assert "handleWorkbenchStepSearchKeydown(event, ${formatJsArg(type)})" in search_markup
    assert "event?.isComposing" in section
    assert "composingFilterInputs.has(input)" in section
    assert 'type="search"' in search_markup
    assert 'autocomplete="off"' in search_markup
    assert "clearWorkbenchStepSearch" in search_markup


def test_high_frequency_workbench_interactions_use_current_step_rendering():
    js = _js()

    assert "function renderWorkbenchCurrentStep" in js
    for function_name, next_marker in [
        ("setWorkbenchUploadState", "function clearWorkbenchUploadState"),
        ("setActivityStep", "function getStepIndex"),
        ("setWorkbenchTaskFilter", "function setWorkbenchResultFilter"),
        ("setWorkbenchResultFilter", "function getWorkbenchStepSearch"),
        ("setCheckTab", "function toggleWorkbenchResultDetail"),
        ("toggleWorkbenchResultDetail", "function updateWorkbenchSupplementDraft"),
        ("setFinalResultSlice", "function isNinetySixHourResult"),
    ]:
        area = js.split(f"function {function_name}", 1)[1].split(next_marker, 1)[0]
        assert "renderWorkbenchCurrentStep" in area
        assert "renderWorkbench();" not in area


def test_compact_performance_supplement_and_calculation_responses_are_requested():
    js = _js()
    supplement = js.split("async function saveWorkbenchPerformanceSupplement", 1)[1].split(
        "function openPerformanceSupplementModal", 1
    )[0]
    calculation = js.split("async function executeCalculate", 1)[1].split(
        "el.btnCalculate", 1
    )[0]

    assert "response_mode: 'employee'" in supplement
    assert "applyPerformanceSupplementCompactResult" in supplement
    assert "renderWorkbenchCurrentStep" in supplement
    assert "/calculation-jobs" in calculation
    assert "renderWorkbenchCurrentStep" in calculation


def test_activity_header_matches_light_payroll_activity_pattern():
    html = _html()
    js = _js()
    combined = f"{html}\n{js}"

    for marker in [
        "activity-page-titlebar",
        "activity-progress-strip",
        "activity-step-link",
        "step-info-close",
        "hideCurrentStepNotice",
    ]:
        assert marker in combined

    title_style = re.search(r"\.activity-titlebar\s*\{([^}]*)\}", html)
    assert title_style, "activity-titlebar 样式缺失"
    assert re.search(r"border\s*:\s*none\s*;", title_style.group(1))
    assert re.search(r"background\s*:\s*transparent\s*;", title_style.group(1))


def test_activity_stepper_has_clear_connectors_hover_and_anchor():
    html = _html()

    connector_style = re.search(r"\.payroll-activity-stepper \.activity-step::after\s*\{([^}]*)\}", html)
    assert connector_style, "步骤连接线样式缺失"
    assert re.search(r"left\s*:\s*11[0-9]px\s*;", connector_style.group(1)), (
        "连接线应从步骤文字后方开始，避免压住文字"
    )

    for marker in [
        ".payroll-activity-stepper .activity-step:hover::after",
        ".payroll-activity-stepper .activity-step:hover .activity-step-index",
        ".activity-step.warning:not(.active)",
    ]:
        assert marker in html

    js = _js()
    assert "function renderActivityStepIndex" in js
    assert "activity-step-pin" in js
    assert "<svg" in js
    assert "activity-step-pin-body" in js


def test_activity_stepper_pin_is_compact_not_oversized():
    html = _html()

    step_style = re.search(r"\.payroll-activity-stepper \.activity-step\s*\{([^}]*)\}", html)
    assert step_style, "步骤项样式缺失"
    assert re.search(r"grid-template-columns\s*:\s*36px minmax\(0,\s*1fr\)\s*;", step_style.group(1))
    assert re.search(r"min-height\s*:\s*40px\s*;", step_style.group(1))

    pin_style = re.search(r"\.payroll-activity-stepper \.activity-step-index\.active-pin\s*\{([^}]*)\}", html)
    assert pin_style, "当前步骤 pin 容器样式缺失"
    assert re.search(r"width\s*:\s*34px\s*;", pin_style.group(1))
    assert re.search(r"height\s*:\s*40px\s*;", pin_style.group(1))

    svg_style = re.search(r"\.activity-step-pin\s*\{([^}]*)\}", html)
    assert svg_style, "当前步骤 SVG 样式缺失"
    assert re.search(r"width\s*:\s*34px\s*;", svg_style.group(1))
    assert re.search(r"height\s*:\s*40px\s*;", svg_style.group(1))


def test_supplemental_leave_uses_compact_filter_and_bulk_bars():
    html = _html()
    js = _js()
    combined = f"{html}\n{js}"
    section = js.split("function renderSupplementalLeaveSection", 1)[1].split("function renderAttendanceSummaryTable", 1)[0]

    for marker in [
        "supplemental-filter-bar",
        "supplemental-filter-segments",
        "setSupplementalLeaveQuality",
        "supplemental-bulk-bar",
        "supplemental-bulk-presets",
        "setSupplementalBulkPreset",
        "status-dot-badge",
    ]:
        assert marker in combined

    assert "筛选补充假勤" not in section
    assert "按处理状态" not in section
    assert "<select" not in section
    assert ".supplemental-filter-bar" in html
    assert ".supplemental-bulk-bar" in html


def test_supplemental_leave_moves_included_hours_into_the_title():
    html = _html()
    js = _js()
    section = js.split("function renderSupplementalLeaveSection", 1)[1].split(
        "function renderAttendanceSummaryTable", 1
    )[0]

    assert "supplemental-title-line" in section
    assert "supplemental-title-hours" in section
    assert 'data-summary-key="include_hours"' in section
    assert "leave-summary-compact" not in section
    assert "renderSupplementalSummaryItem(summary" not in section
    assert ".supplemental-title-hours" in html


def test_special_person_tags_are_rendered_near_name():
    js = _js()

    assert "function getSpecialPersonTags" in js
    assert "function renderNameWithTags" in js
    for label in ["区长", "96工时制", "固定基数", "本月调薪", "离职发放"]:
        assert label in js
    assert "存在调薪" not in js
    assert "event.effective_date).startsWith(activity?.calc_month" in js
    assert "row?.calculation_segments?.length" in js
    assert "person-tag" in js
    assert 'title="${escapeHtml(name)}"' in js


def test_sticky_employee_columns_are_opaque_and_have_stable_widths():
    html = _html()

    assert "--employee-id-column-width: 132px" in html
    assert "--employee-name-column-width: 176px" in html
    assert "width: var(--employee-id-column-width)" in html
    assert "left: var(--employee-id-column-width)" in html
    assert ".data-table tbody .sticky-employee-id" in html
    assert "background: #fff" in html


def test_truncated_employee_name_has_custom_hover_preview():
    html = _html()
    js = _js()
    renderer = js.split("function renderNameWithTags", 1)[1].split("function getBaseOverrideRows", 1)[0]

    assert "showEmployeeNamePreview(event" in renderer
    assert "moveEmployeeNamePreview(event)" in renderer
    assert "hideEmployeeNamePreview()" in renderer
    assert "function showEmployeeNamePreview" in js
    assert "text.scrollWidth <= text.clientWidth" in js
    assert "String(name || '').length <= 14" in js
    assert "employee-name-preview" in html


def test_attendance_step_table_uses_calculation_hour_fields_not_rule_column():
    js = _js()
    section = js.split("function renderAttendanceSummaryTable", 1)[1].split("function renderSalarySummaryTable", 1)[0]

    for label in ["普通工时", "OT1.5", "OT2.0", "病假", "年假", "计薪工时"]:
        assert label in section

    assert "total_ot15" in section
    assert "total_ot20" in section
    assert "sick_hours" in section
    assert "annual_hours" in section
    assert "total_base_hours" in section
    assert "96工时制" not in section


def test_attendance_step_places_supplemental_leave_before_hourly_rate_and_work_hours():
    js = _js()
    attendance_step = js.split("function renderAttendanceStep", 1)[1].split("function renderSalaryStep", 1)[0]
    attendance_table = js.split("function renderAttendanceSummaryTable", 1)[1].split("function renderSalarySummaryTable", 1)[0]

    assert "renderSupplementalLeaveSection(activity)" in attendance_step
    assert (
        attendance_step.index("renderSupplementalLeaveSection(activity)")
        < attendance_step.index("renderHourlyRatePolicySection(activity)")
        < attendance_step.index("renderAttendanceSummaryTable(activity)")
    )
    assert "renderSupplementalLeaveSection(activity)" not in attendance_table


def test_supplemental_leave_row_save_uses_visible_workbench_activity():
    js = _js()
    save_handler = js.split("async function updateSupplementalLeaveRow", 1)[1].split(
        "// ═══ Render Results Data ═══", 1
    )[0]

    assert "const activity = getWorkbenchActivity();" in save_handler
    assert "activity?.run_id" in save_handler
    assert "state.currentActivity.run_id" not in save_handler
    assert "response_mode: 'row'" in save_handler
    assert "applyOptimisticSupplementalLeaveRow" in save_handler
    assert save_handler.index("applyOptimisticSupplementalLeaveRow") < save_handler.index("await apiJson")
    assert "applySupplementalLeaveCompactResult" in save_handler
    assert "rollbackOptimisticSupplementalLeaveRow" in save_handler


def test_attendance_step_has_compact_section_navigation():
    js = _js()
    attendance_step = js.split("function renderAttendanceStep", 1)[1].split(
        "function renderSalaryStep", 1
    )[0]
    navigation = js.split("function renderAttendanceSectionNav", 1)[1].split(
        "function scrollToAttendanceSection", 1
    )[0]
    scroll_handler = js.split("function scrollToAttendanceSection", 1)[1].split(
        "function renderAttendanceStep", 1
    )[0]

    assert "renderAttendanceSectionNav()" in attendance_step
    for target_id in [
        "attendanceSupplementalSection",
        "attendanceHourlyRateSection",
        "attendanceWorkHoursSection",
    ]:
        assert f'id="{target_id}"' in attendance_step
        assert f'aria-controls="{target_id}"' in navigation
    for label in ["补充假勤", "周期时薪", "工时表"]:
        assert label in navigation
    assert "scrollIntoView" in scroll_handler
    assert "prefers-reduced-motion: reduce" in scroll_handler


def test_performance_supplement_inline_form_supports_name_and_continuous_entries():
    js = _js()
    render_section = js.split("function renderWorkbenchPerformanceSupplement", 1)[1].split("function renderWorkbenchResultRow", 1)[0]
    save_section = js.split("async function saveWorkbenchPerformanceSupplement", 1)[1].split("async function applyWorkbenchSupplementalSuggestion", 1)[0]

    assert "workbenchSupplementEmployeeId" in render_section
    assert "workbenchSupplementName" in render_section
    assert "workbenchSupplementCoefficient" in render_section
    assert "workbenchSupplementNote" in render_section
    assert "绩效系数" in render_section
    assert "姓名" in render_section
    assert "已补录人员" in render_section
    assert "performance-supplement-chip" in render_section
    assert "保存并继续" in render_section
    assert "补充得分" not in js
    assert "补充绩效得分" not in js
    assert "得分" not in render_section
    assert "等级" not in render_section
    assert "levelOptions" not in render_section
    assert "setWorkbenchSupplementLevel" not in js

    assert "name" in save_section
    assert "coefficient" in save_section
    assert "请填写绩效系数" in save_section
    assert "workbenchSupplementScore" not in save_section
    assert "workbenchSupplementLevel" not in save_section


def test_activity_step_tables_render_all_rows_with_pagination():
    js = _js()
    section = js.split("function renderCompactEmployeeTable", 1)[1].split("function renderPeopleTable", 1)[0]

    assert "getPaginatedRows(type" in section
    assert "renderTablePagination(type, pageInfo)" in section
    assert "const previewLimit = 12" not in section
    assert "slice(0, previewLimit)" not in section
    assert "slice(0, 80)" not in section


def test_activities_list_is_compact_user_scoped_and_paginated():
    html = _html()
    js = _js()
    section = js.split("function renderActivities", 1)[1].split("function getActivityStatusMeta", 1)[0]

    assert "currentPage: 'activities'" in js
    assert "activityOwnerFilter: 'mine'" in js
    assert "activities: { page: 1, pageSize: 50 }" in js
    assert "state.activities.filter(isMyActivity)" in section
    assert "getPaginatedRows('activities', filteredActivities)" in section
    assert "pageInfo.items.map" in section
    assert "el.activitiesBody.innerHTML = state.activities.map" not in section
    assert "renderActivityResumeAction()" in section
    assert "renderActivityOwnerFilters()" in section
    assert "renderActivitiesPagination(pageInfo)" in section
    assert '<th>绩效周期</th>' in html
    assert "function formatPerformancePeriod(calcMonth)" in js
    assert "formatPerformancePeriod(activity.calc_month)" in section
    assert "renderEmptyTableRow(5, message)" in section
    assert "deleteActivitiesByIds" in js
    delete_activity_area = js.split("async function deleteActivity", 1)[1].split("async function deleteActivitiesByIds", 1)[0]
    delete_shared_area = js.split("async function deleteActivitiesByIds", 1)[1].split("// ═══ Base Roster", 1)[0]
    assert "await deleteActivitiesByIds([activityId]" in delete_activity_area
    assert "`${API_BASE}/runs/bulk-delete`" in delete_shared_area
    assert "JSON.stringify({ run_ids: runIds })" in delete_shared_area
    assert "state.activities = state.activities.filter(activity => !runIds.includes(activity.run_id));" in delete_shared_area
    assert "delete state.foundationRunDetails[id];" in delete_shared_area
    assert "renderActivities();" in delete_shared_area
    assert "批量删除" not in js
    assert "activity-row-check" not in js
    assert "activitiesBatchBar" not in f"{html}\n{js}"
    assert "renderTablePagination('activities', pageInfo)" in js
    assert "if (type === 'activities') renderActivities();" in js
    assert 'id="activitiesPagination"' in html
    assert 'id="activityResumeButton"' in html
    assert 'id="activityResumePanel"' not in html
    assert ".activity-resume-button[hidden]" in html
    assert "从一个新活动开始" not in js
    assert "创建我的活动" not in js
    assert "button.hidden = true;" in section
    assert "`继续上次 · ${step.label}`" in section
    assert 'data-activity-owner-filter="mine"' in html
    assert "总活动数" not in html
    assert "异常数" not in html


def test_activity_creation_and_header_expose_region_creator_and_default_avatar():
    html = _html()
    js = _js()

    assert "DEFAULT_USER_AVATAR = 'assets/sigma-user-avatar-default.png'" in js
    assert "created_by_user_id" in js
    assert "created_by_name" in js
    assert "created_by_avatar_url" in js
    assert "activity.region_name || DEFAULT_FBU_REGION.name" in js
    assert "activity-creator-card" in f"{html}\n{js}"
    assert "同月同区域可创建多个活动" in js
    assert "region_code: regionCode" in js
    assert "活动名称：绩效奖金核算-" in js
    assert 'id="appDialogSelect"' in html
    assert 'id="appDialogPreview"' in html


def test_fbu_entry_never_auto_opens_another_users_activity():
    js = _js()
    load_section = js.split("async function loadActivities", 1)[1].split("function getWorkbenchActivity", 1)[0]
    init_section = js.split("DOMContentLoaded", 1)[1]

    assert "getWorkbenchDefaultActivity" not in js
    assert "await enterActivity(defaultActivity.run_id" not in load_section
    assert "navigateTo('activities');" in init_section
    assert "loadActivities();" not in init_section
    assert "sigma:fbu:last-owned-activity:" in js
    assert "if (!activity?.run_id || !isMyActivity(activity)) return;" in js


def test_activity_list_uses_summary_without_detail_prefetch():
    js = _js()

    render_by_type = js.split("function renderTableByType", 1)[1].split(
        "function applyTableFilter", 1
    )[0]

    assert "async function loadActivityListDetails" not in js
    assert "ACTIVITY_DETAIL_PREFETCH_CONCURRENCY" not in js
    assert "ACTIVITY_DETAIL_PREFETCH_LIMIT" not in js
    assert "if (type === 'activities') renderActivities();" in render_by_type


def test_salary_table_shows_full_employee_context_without_horizontal_scroll():
    html = _html()
    js = _js()
    salary_section = js.split("function renderSalarySummaryTable", 1)[1].split(
        "function renderPerformanceInlineSupplement", 1
    )[0]

    for label in ["部门全称", "岗位", "人员状态", "划分区域", "成本归属", "时薪", "绩效比例", "固定基数"]:
        assert label in salary_section
    assert "row.position" in salary_section
    assert "row.personnel_status" in salary_section
    assert "row.cost_owner" in salary_section
    assert "salary-activity-table" in js
    salary_css = html.split(".salary-activity-table {", 1)[1].split("}", 1)[0]
    assert "min-width: 0;" in salary_css
    assert "table-layout: fixed;" in salary_css
    salary_cell_css = html.split(".salary-activity-table tbody td,", 1)[1].split("}", 1)[0]
    assert "white-space: normal;" in salary_cell_css
    assert "overflow-wrap: anywhere;" in salary_cell_css


def test_position_columns_use_latest_roster_position_not_html_pills():
    js = _js()
    people_section = js.split("function renderPeopleTable", 1)[1].split("function renderSupplementalLeaveSection", 1)[0]
    base_section = js.split("function renderPerformanceBaseSummary", 1)[1].split("function renderCheckIssuesPanel", 1)[0]
    final_section = js.split("function renderFinalResultRow", 1)[1].split("function getFinalResultDetailKey", 1)[0]

    assert "function getDisplayPosition" in js
    assert "activity?.roster_data?.employees" in people_section
    assert "activity?.salary_data?.employees" in js
    assert "escapeHtml(getDisplayPosition(row, activity))" in people_section
    assert "escapeHtml(getDisplayPosition(result, activity))" in base_section
    assert "escapeHtml(getDisplayPosition(result, activity))" in final_section
    assert "escapeHtml(result.position || formatResultJobType" not in js


def test_table_pagination_uses_page_size_select():
    html = _html()
    js = _js()
    section = js.split("function renderTablePagination", 1)[1].split("function renderEmptyTableRow", 1)[0]

    assert "<select" in section
    assert "page-size-select" in section
    assert "changeTablePageSize" in section
    assert "page-size-btn" not in section
    assert "page-size-segments" not in section
    assert "page-size-select" in html


def test_check_issue_table_uses_pagination_not_first_20_only():
    js = _js()
    section = js.split("function renderCheckPreview", 1)[1].split("function renderExportStep", 1)[0]

    assert "issues.slice(0, 20)" not in section
    assert "getPaginatedRows('check', issues)" in section
    assert "renderTablePagination('check', pageInfo)" in section


def test_check_step_starts_with_performance_base_summary_tab():
    html = _html()
    js = _js()
    section = js.split("function renderCheckPreview", 1)[1].split("function renderExportStep", 1)[0]

    assert "checkTab: 'base'" in js
    assert "{ key: 'base', label: '绩效基数汇总' }" in section
    assert "{ key: 'issues', label: '检查事项' }" in section
    assert section.index("绩效基数汇总") < section.index("检查事项")
    assert "renderPerformanceBaseSummary(activity)" in section
    assert "renderCheckIssuesPanel(activity)" in section
    assert "function setCheckTab" in js
    assert "getPaginatedRows('baseSummary', results)" in js
    assert "renderTablePagination('baseSummary', pageInfo)" in js
    assert "baseSummary: { page: 1, pageSize: 50 }" in js
    assert ".check-tabbar" in html
    assert ".base-summary-detail-table" in html


def test_final_results_have_summary_and_pagination():
    js = _js()
    section = js.split("function renderFinalResults", 1)[1].split("function renderFinalResultRow", 1)[0]

    assert "getFinalResultGroups(results)" in section
    assert "renderFinalResultGroup(group, activity)" in section
    assert "renderTablePagination(group.paginationKey, pageInfo)" in js
    assert "奖金总额" in section
    assert "结果人数" in section
    assert "仓库管理人员" in js
    assert "非仓人员" in js
    assert "区长" in js
    assert "highlight-base" in js
    assert "results.map" not in section


def test_final_results_support_search_with_category_pagination():
    html = _html()
    js = _js()
    search_section = js.split("function rowMatchesFinalResultSearch", 1)[1].split(
        "function isNinetySixHourResult", 1
    )[0]
    group_section = js.split("function renderFinalResultGroup", 1)[1].split(
        "function renderFinalResultRow", 1
    )[0]
    setter_section = js.split("function setWorkbenchStepSearch", 1)[1].split(
        "function queueWorkbenchStepSearch", 1
    )[0]

    assert "getDisplayPosition(result, activity)" in search_section
    for field in ["employee_id", "name", "department", "area", "position"]:
        assert f"result?.{field}" in search_section
    assert "getFinalResultSearchRows(group.rows, activity)" in group_section
    assert "renderWorkbenchTableSearch('finalResults'" in group_section
    assert "搜索工号、姓名、部门或岗位" in group_section
    assert "没有匹配的核算结果" in group_section
    for pagination_key in ["resultsWarehouse", "resultsFunctional", "resultsDistrict"]:
        assert pagination_key in setter_section
    assert ".final-result-group-head .activity-table-search" in html


def test_final_result_action_is_calculation_process():
    html = _html()
    js = _js()
    section = js.split("function renderFinalResultGroup", 1)[1].split("function getFinalResultDetailKey", 1)[0]

    assert "计算过程</th>" in section
    assert ">计算过程</button>" in section
    assert ">查看说明</button>" not in section
    assert '<h3 class="modal-title" id="finalResultExplanationTitle">计算过程</h3>' in html
    assert "function renderFinalBaseCalculationDetail" in js
    assert "function renderBonusCalculationFormula" in js
    assert "绩效基数计算" in js
    assert "奖金计算过程" in js
    assert "<span>${escapeHtml(row.reason || '-')}</span>" in js
    assert "计算时薪" in js
    assert ".final-result-explanation-modal .modal-body" in html
    assert "max-height: calc(100vh - 32px)" in html
    assert "overflow-y: auto" in html


def test_workbench_results_are_paginated_not_capped_at_80():
    js = _js()
    section = js.split("function renderWorkbenchResults", 1)[1].split("function renderWorkbenchAudit", 1)[0]

    assert "slice(0, 80)" not in section
    assert "getPaginatedRows('results', filteredResults)" in section
    assert "renderTablePagination('results', pageInfo)" in section


def test_uploading_feedback_is_indeterminate_not_fake_percentage():
    html = _html()
    js = _js()
    start_section = js.split("function startWorkbenchUploadProgress", 1)[1].split(
        "function finishWorkbenchUploadProgress", 1
    )[0]
    upload_view = js.split("if (uploadState.status === 'uploading')", 1)[1].split(
        "if (uploadState.status === 'selected')", 1
    )[0]

    assert "setInterval" not in start_section
    assert "indeterminate: true" in upload_view
    assert "material-progress ${uploadView.indeterminate ? 'indeterminate' : ''}" in js
    assert ".material-progress.indeterminate span" in html


def test_salary_history_materials_upload_immediately_then_auto_reconcile():
    js = _js()
    upload_section = js.split("async function uploadWorkbenchSalaryHistoryMaterial", 1)[1].split(
        "async function confirmSalaryVerification", 1
    )[0]
    change_section = js.split("function handleWorkbenchUploadChange", 1)[1].split(
        "function clearWorkbenchUpload", 1
    )[0]

    assert "startWorkbenchUploadProgress(type, file)" in upload_section
    assert "/import-salary-history-material" in upload_section
    assert "data.ready_for_reconciliation" in upload_section
    assert "已上传，待补：" in upload_section
    assert "Object.keys(SALARY_HISTORY_MATERIAL_FIELDS)" in upload_section
    assert "'已核验'" in upload_section
    assert "uploadWorkbenchSalaryHistoryMaterial(type, file)" in change_section
    assert "集齐三份文件后自动核验" not in js
    assert "workbenchSalaryHistoryFiles" not in js
    assert "文件已解析，待补：" in js


def test_activity_uploads_require_current_activity_except_roster():
    js = _js()
    section = js.split("function openWorkbenchUpload", 1)[1].split("async function uploadWorkbenchRosterFile", 1)[0]

    assert "type !== 'roster'" in section
    assert "previousAttendance" not in section


def test_activity_title_does_not_show_employee_scope_tag():
    js = _js()
    title_section = js.split("function renderWorkbench", 1)[1].split("function renderActivityRow", 1)[0]

    assert "activity-title-tag" not in title_section
    assert "员工范围" not in title_section


def test_final_table_freezes_only_employee_id_and_name():
    html = _html()
    js = _js()

    assert ".sticky-employee-id" in html
    assert ".sticky-employee-name" in html
    assert ".sticky-bonus" not in html
    assert "sticky-bonus" not in js


def test_activity_workflow_has_no_modal_first_upload_or_supplement_paths():
    html = _html()
    js = _js()

    assert 'id="uploadModal"' not in html
    assert 'id="performanceSupplementModal"' not in html
    assert 'id="calcChainModal"' not in html
    assert "openUploadModal(" not in js
    assert "openPerformanceSupplementModal(" not in js
    assert "showCalcChain(" not in js


def test_workbench_success_paths_do_not_call_removed_page_renderers():
    js = _js()

    workflow_refresh_area = js.split("// ═══ Enter Activity ═══", 1)[1].split("// ═══ Upload Buttons ═══", 1)[0]

    for forbidden in [
        "renderAttendanceData();",
        "renderSalaryData();",
        "renderPerformanceData();",
        "renderSupplementalLeaveData();",
        "renderResultsData();",
    ]:
        assert forbidden not in workflow_refresh_area


def test_upload_success_updates_current_activity_without_refetching_detail():
    js = _js()

    multipart_area = js.split("async function uploadWorkbenchFileMultipart", 1)[1].split(
        "async function uploadWorkbenchSalaryHistoryMaterialMultipart", 1
    )[0]

    assert "applyCurrentActivityPatch" in multipart_area
    assert "await enterActivity" not in multipart_area


def test_async_upload_refresh_discards_stale_empty_step_sections():
    js = _js()

    enter_activity_area = js.split("async function enterActivity", 1)[1].split(
        "// ═══ New Activity ═══", 1
    )[0]
    upload_job_area = js.split("async function completeFbuUploadJob", 1)[1].split(
        "async function resumeFbuUploadJob", 1
    )[0]
    salary_multipart_area = js.split(
        "async function uploadWorkbenchSalaryHistoryMaterialMultipart", 1
    )[1].split(
        "async function uploadWorkbenchSalaryHistoryMaterial", 1
    )[0]

    assert "preserveStep = false" in enter_activity_area
    assert "initialStep = ''" in enter_activity_area
    assert "refreshSections = false" in enter_activity_area
    assert "isDifferentActivity || refreshSections" in enter_activity_area
    assert "state.currentActivity = null;" in enter_activity_area
    assert "refreshSections: true" in upload_job_area
    assert "refreshSections: true" in salary_multipart_area


def test_attendance_import_defaults_supplemental_leave_to_pending():
    js = _js()
    helper_area = js.split("function prioritizePendingSupplementalLeave", 1)[1].split(
        "function uploadFbuFileToSignedUrl", 1
    )[0]
    upload_job_area = js.split("async function completeFbuUploadJob", 1)[1].split(
        "async function resumeFbuUploadJob", 1
    )[0]
    multipart_area = js.split("async function uploadWorkbenchFileMultipart", 1)[1].split(
        "async function uploadWorkbenchSalaryHistoryMaterialMultipart", 1
    )[0]
    previous_attendance_area = js.split(
        "async function uploadWorkbenchPreviousAttendanceFileMultipart", 1
    )[1].split("function handleWorkbenchUploadChange", 1)[0]

    assert "state.tableFilters.supplementalLeave = { quality: 'pending' };" in helper_area
    assert "getTablePagination('supplementalLeave').page = 1;" in helper_area
    assert "'attendance', 'previousAttendance'" in upload_job_area
    assert "prioritizePendingSupplementalLeave();" in upload_job_area
    assert "prioritizePendingSupplementalLeave();" in multipart_area
    assert "prioritizePendingSupplementalLeave();" in previous_attendance_area


def test_new_activity_opens_first_step_instead_of_auto_detected_step():
    js = _js()

    new_activity_area = js.split("el.btnNewActivity.addEventListener", 1)[1].split("// ═══ Delete Activity ═══", 1)[0]

    assert "data.activity" in new_activity_area
    assert "applyCurrentActivityPatch" in new_activity_area
    assert "state.activityStep = 'people'" in new_activity_area
    assert "enterActivity(data.run_id" not in new_activity_area


def test_activity_list_diagnostics_do_not_prefetch_full_run_details():
    js = _js()

    assert "async function loadActivityListDetails" not in js


def test_salary_confirmation_updates_local_activity_without_detail_refetch():
    js = _js()

    compact_result_area = js.split("function applySalaryVerificationCompactResult", 1)[1].split(
        "async function confirmSalaryVerification", 1
    )[0]
    confirmation_area = js.split("async function confirmSalaryVerification", 1)[1].split(
        "async function uploadWorkbenchPreviousAttendanceFile", 1
    )[0]

    assert "applyCurrentActivityPatch" in compact_result_area
    assert "await enterActivity" not in confirmation_area
    assert "salaryVerificationQueue" in confirmation_area
    assert "flushSalaryVerificationQueue" in confirmation_area
    assert "response_mode: 'employees'" in confirmation_area
    assert "confirmations" in confirmation_area
    assert "}, 300)" in confirmation_area
    assert "setSalaryVerificationRowSaving(employeeId, true)" in confirmation_area
    assert "applySalaryVerificationBatchResult" in confirmation_area
    assert "renderWorkbench();" not in confirmation_area


def test_salary_history_upload_requests_compact_response_and_restores_verification_rows():
    js = _js()
    upload_area = js.split("async function uploadWorkbenchSalaryHistoryMaterialMultipart", 1)[1].split(
        "function findSalaryVerificationRowElement", 1
    )[0]

    assert "/import-salary-history-material" in upload_area
    assert "ready_for_reconciliation" in upload_area
    assert "refreshSections: true" in upload_area


def test_calculation_button_shows_loading_state_and_refreshes_results():
    js = _js()
    calculation = js.split("async function executeCalculate", 1)[1].split(
        "el.btnCalculate", 1
    )[0]

    assert "calculationPending" in js
    assert "button-spinner" in js
    assert "if (state.calculationPending) return" in calculation
    assert "state.calculationPending = true" in calculation
    assert "state.calculationPending = false" in calculation
    assert "/calculation-jobs" in calculation
    completion = js.split("async function completeFbuCalculationJob", 1)[1].split(
        "async function pollFbuCalculationJob", 1
    )[0]
    poller = js.split("async function pollFbuCalculationJob", 1)[1].split(
        "async function resumeFbuCalculationJob", 1
    )[0]
    assert "initialStep: 'export'" in completion
    assert "return completeFbuCalculationJob(metadata, job);" in poller
    assert "renderWorkbenchCurrentStep" in calculation


def test_existing_activity_opens_earliest_incomplete_input_step_before_check():
    js = _js()
    navigation = js.split("function getActivityStepFromActivity", 1)[1].split("function navigateTo", 1)[0]

    assert "if (!activity.roster_file) return 'people'" in navigation
    assert "if (!activity.attendance_file || !activity.supplemental_leave_file) return 'attendance'" in navigation
    assert "!activity.previous_salary_file" in navigation
    assert "if (!activity.performance_file) return 'performance'" in navigation
    assert "return 'check'" in navigation
    assert "getFirstIncompleteInputStep(activity)" not in navigation


def test_check_step_shows_one_prerequisite_link_instead_of_duplicate_upload_tasks():
    js = _js()
    needs = js.split("function buildNeedsForStep", 1)[1].split("function renderNeedsPanel", 1)[0]

    assert "const incompleteStep = getFirstIncompleteInputStep(activity)" in needs
    assert "请先完成" in needs
    assert "setActivityStep" in needs
    assert "['people', 'attendance', 'salary', 'performance'].forEach" not in needs


def test_salary_step_exposes_blocking_history_rows_with_snapshot_choices():
    js = _js()
    salary_review = js.split("function renderSalaryVerificationReview", 1)[1].split(
        "function renderSalarySummaryTable", 1
    )[0]
    salary_step = js.split("function renderSalaryStep", 1)[1].split("function renderPerformanceStep", 1)[0]

    assert "verification_status === 'blocking'" in salary_review
    assert "薪资历史差异确认" in salary_review
    assert "薪资字段变化或相邻月份快照缺失" in salary_review
    assert "snapshotValue(row, 'previous', 'hourly_rate'" in salary_review
    assert "snapshotValue(row, 'current', 'hourly_rate'" in salary_review
    assert "snapshotValue(row, 'previous', 'ratio'" in salary_review
    assert "snapshotValue(row, 'current', 'ratio'" in salary_review
    assert "renderSalaryVerificationButton" in salary_review
    verification_button = js.split(
        "function renderSalaryVerificationButton", 1
    )[1].split("async function confirmSalaryVerification", 1)[0]
    assert "confirmSalaryVerification" in verification_button
    assert "renderSalaryVerificationReview(activity)" in salary_step
    assert "getSalarySnapshotMonthLabels(activity?.calc_month)" in salary_review
    assert "${monthLabels.previous}时薪" in salary_review
    assert "${monthLabels.current}时薪" in salary_review
    assert "`按${monthLabels.previous}值`" in salary_review
    assert "`按${monthLabels.current}值`" in salary_review
    assert 'id="salaryVerificationReview"' in salary_review
    assert 'data-employee-id="${escapeHtml(row.employee_id)}"' in salary_review
    assert "missing_current_snapshot" in salary_review
    assert "missing_previous_snapshot" in salary_review
    assert 'status-badge danger">缺失' in salary_review
    assert "snapshotMissing(row, 'previous') ? ''" in salary_review
    assert "snapshotMissing(row, 'current') ? ''" in salary_review
    assert "row.resolution === 'missing_current_snapshot'" in salary_review
    assert "'ignore_current'" in salary_review
    assert "${monthLabels.current}忽略不计" in salary_review
    assert "后续重新上传" in salary_review


def test_salary_verification_confirmation_uses_authoritative_response_without_immediate_reload():
    js = _js()
    confirmation = js.split("async function confirmSalaryVerification", 1)[1].split(
        "async function uploadWorkbenchPreviousAttendanceFile", 1
    )[0]

    assert "applySalaryVerificationBatchResult" in confirmation
    assert "refreshSalaryVerificationSections(updated)" in confirmation
    assert "await enterActivity" not in confirmation


def test_transfer_history_warning_is_visible_in_the_title_meta():
    html = _html()
    js = _js()
    transfer_review = js.split("function renderTransferHistoryReview", 1)[1].split(
        "function renderPeriodAdjustmentSection", 1
    )[0]

    assert 'class="transfer-history-head-meta"' in transfer_review
    assert "material-action-note warning transfer-history-warning" in transfer_review
    assert "已忽略审批中、已废弃或缺少生效日记录" in transfer_review
    assert ".transfer-history-warning" in html
    warning_css = html.split(".transfer-history-warning {", 1)[1].split("}", 1)[0]
    assert "max-width: none;" in warning_css
    assert "overflow: visible;" in warning_css


def test_salary_snapshot_month_labels_handle_year_boundary():
    js = _js()
    helper = js.split("function getSalarySnapshotMonthLabels", 1)[1].split(
        "function renderSalaryVerificationReview", 1
    )[0]

    assert "crossesYear" in helper
    assert "年${month}月" in helper


def test_check_step_names_salary_history_blocking_count():
    js = _js()
    needs = js.split("function buildNeedsForStep", 1)[1].split("function renderNeedsPanel", 1)[0]

    assert "薪资历史核验还有" in needs
    assert "条差异待确认" in needs


def test_calculate_button_is_disabled_until_precalculation_check_is_ready():
    js = _js()
    renderer = js.split("function renderWorkbench()", 1)[1].split("function renderActivityCard", 1)[0]

    assert "const canCalculate = buildNeedsForStep('check', activity).length === 0" in renderer
    assert "renderCalculateButton(canCalculate)" in renderer
    calculate_button = js.split("function renderCalculateButton", 1)[1].split(
        "function renderWorkbench", 1
    )[0]
    assert "const disabled = !canCalculate || isPending" in calculate_button


def test_workbench_initial_activity_load_cannot_stay_on_reading_placeholder():
    js = _js()

    load_activities_area = js.split("async function loadActivities", 1)[1].split(
        "function hasWorkbenchActivityPayload", 1
    )[0]
    enter_activity_area = js.split("async function enterActivity", 1)[1].split("// ═══ New Activity ═══", 1)[0]

    assert "catch (error)" in load_activities_area
    assert "state.currentActivity = null;" in load_activities_area
    assert "renderWorkbench();" in load_activities_area.split("catch (error)", 1)[1]

    assert "catch (error)" in enter_activity_area
    assert "state.currentActivity = null;" in enter_activity_area
    assert "renderWorkbench();" in enter_activity_area.split("catch (error)", 1)[1]


def test_activity_detail_load_preserves_activity_list_page_without_prefetch():
    js = _js()

    enter_activity_area = js.split("async function enterActivity", 1)[1].split("// ═══ New Activity ═══", 1)[0]

    assert "if (preservePage && state.currentPage === 'activities')" in enter_activity_area
    assert "Keep list interactions stable while background activity details are loading." in enter_activity_area
    assert "renderActivities();" in enter_activity_area
    assert "loadActivityListDetails();" not in enter_activity_area
    assert "navigateTo(preservePage ? state.currentPage : 'workbench');" in enter_activity_area
    assert enter_activity_area.index("if (preservePage && state.currentPage === 'activities')") < enter_activity_area.index("navigateTo(preservePage ? state.currentPage : 'workbench');")


def test_activity_hub_initial_load_does_not_prefetch_activity_details():
    js = _js()

    load_activities_area = js.split("async function loadActivities", 1)[1].split(
        "function getWorkbenchActivity", 1
    )[0]

    assert "enterActivity(" not in load_activities_area
    assert "navigateTo('activities')" in load_activities_area
    assert "loadActivityListDetails();" not in load_activities_area


def test_workbench_loads_activity_core_then_only_the_active_step_sections():
    js = _js()

    enter_activity_area = js.split("async function enterActivity", 1)[1].split(
        "// ═══ New Activity ═══", 1
    )[0]
    step_loader = js.split("async function ensureActivityStepData", 1)[1].split(
        "async function enterActivity", 1
    )[0]

    assert "?include=core" in enter_activity_area
    assert "ensureActivityStepData(state.activityStep" in enter_activity_area
    assert "ACTIVITY_STEP_SECTIONS" in js
    assert "loaded_sections" in js
    assert "include=${encodeURIComponent(include)}" in step_loader


def test_initial_workbench_overlaps_rule_list_and_activity_core_requests():
    js = _js()
    load_rule_lists = js.split("async function loadRuleLists", 1)[1].split(
        "function getWorkbenchSourceKey", 1
    )[0]
    enter_activity = js.split("async function enterActivity", 1)[1].split(
        "// ═══ New Activity ═══", 1
    )[0]

    assert "state.ruleListsRequest" in load_rule_lists
    assert "if (state.ruleListsRequest) return state.ruleListsRequest;" in load_rule_lists
    request_start = "const ruleListsRequest = state.ruleLists ? null : loadRuleLists();"
    assert request_start in enter_activity
    assert enter_activity.index(request_start) < enter_activity.index("?include=core")
    assert enter_activity.index("await ruleListsRequest;") > enter_activity.index(
        "?include=core"
    )


def test_lazy_step_status_uses_manifest_summaries_after_refresh():
    js = _js()
    needs = js.split("function buildNeedsForStep", 1)[1].split(
        "function renderNeedsPanel", 1
    )[0]

    assert "function getActivitySectionSummary" in js
    assert "state.activities.find(item => item.run_id === activity?.run_id)" in js
    assert "work_hour_rule_count" in needs
    assert "fixed_base_count" in needs
    assert "suggested_count" in needs
    assert "getSalaryVerificationBlockingCount(activity)" in needs


def test_final_results_use_server_pagination_and_search_instead_of_full_detail():
    js = _js()

    loader = js.split("async function loadFinalResultsPage", 1)[1].split(
        "function getFinalResultGroupKey", 1
    )[0]
    step_sections = js.split("const ACTIVITY_STEP_SECTIONS", 1)[1].split("};", 1)[0]

    assert "export: []" in step_sections
    assert "/results?" in loader
    assert "page_size" in loader
    assert "encodeURIComponent(query)" in loader
    assert "group=${encodeURIComponent(group)}" in loader
    assert "finalResultsRemote" in js
    assert "loadFinalResultsPage({ page: 1" in js
    assert "remote.pagination" in js


def test_check_step_uses_compact_diagnostics_and_server_paged_results():
    js = _js()
    step_sections = js.split("const ACTIVITY_STEP_SECTIONS", 1)[1].split("};", 1)[0]
    check_sections = step_sections.split("check:", 1)[1].split("],", 1)[0]
    loader = js.split("async function loadCheckResultsPage", 1)[1].split(
        "async function loadFinalResultsPage", 1
    )[0]

    assert "'diagnostics'" in check_sections
    assert "'salary_verification_data'" in check_sections
    assert "'base_override_data'" in check_sections
    assert "'supplemental_leave_data'" in check_sections
    for large_section in [
        "'attendance_data'",
        "'salary_data'",
        "'performance_data'",
        "'results'",
    ]:
        assert large_section not in check_sections
    assert "/results?" in loader
    assert "group=all" in loader
    assert "checkResultsRemote" in js
    assert "loadCheckResultsPage({ page: 1" in js


def test_export_button_only_appears_in_final_step_renderer():
    js = _js()

    before_export_step = js.split("function renderExportStep", 1)[0]
    assert "exportData('results')" not in before_export_step
    assert "导出结果" in js.split("function renderExportStep", 1)[1]
