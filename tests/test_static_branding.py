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
STYLES_CSS = ROOT / "bonus_platform" / "static" / "styles.css"
APP_PY = ROOT / "bonus_platform" / "app.py"
APP_JS = ROOT / "bonus_platform" / "static" / "app.js"
STORY_HTML = ROOT / "bonus_platform" / "static" / "vibecoding-story.html"
HEADER_LOGO = ROOT / "bonus_platform" / "static" / "assets" / "bonus-logo-header-blue.png"
LOGIN_SIGMA_LOGO = ROOT / "bonus_platform" / "static" / "assets" / "bonus-logo-header-transparent.png"
FEISHU_LOGO = ROOT / "bonus_platform" / "static" / "assets" / "feishu-logo.png"
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
    assert 'href="china-employee-payroll.html"' in html
    assert 'href="admin.html"' in html
    assert "Available · 已上线" in html
    assert "UAT · 试点" in html
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


def test_vercel_config_does_not_override_runtime_labor_access_mode():
    config = json.loads(VERCEL_JSON.read_text(encoding="utf-8"))

    assert config["env"]["SIGMA_WORKBENCH_HOME"] == "/tmp/sigma-workbench"
    assert "SIGMA_OVERSEAS_LABOR_ACCESS" not in config["env"]


def test_overseas_labor_uses_direct_storage_upload_for_large_files():
    js = OVERSEAS_LABOR_JS.read_text(encoding="utf-8")

    assert "direct-upload-plan" in js
    assert "direct-upload-complete" in js
    assert "uploadOneFileToSignedUrl" in js
    assert "LABOR_DIRECT_UPLOAD_UNAVAILABLE" in js


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
    assert "permission-guard.js?v=8" in html
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
    css = STYLES_CSS.read_text(encoding="utf-8")

    assert "劳务工薪酬核算" in html
    assert 'data-module-id="domestic"' in html
    assert "permission-guard.js" in html
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
    assert 'data-module-id="overseas"' in html
    assert "permission-guard.js" in html
    assert "自动核对总金额与员工明细" in html
    assert "测试材料验证" in html
    assert "overseas-labor.js" in html
    assert "/api/labor/runs" in js
    assert "applyVercelLightUatState" in js
    assert "正式核对未启用" in js
    assert "UAT 页面试用" in js
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
    assert "Developing · 开发中" in domestic_card
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


def test_desktop_builder_uses_platform_logo_icons():
    package = DESKTOP_PACKAGE.read_text(encoding="utf-8")

    assert '"icon": "assets/icon.icns"' in package
    assert '"icon": "assets/icon.ico"' in package
    assert DESKTOP_ICON_ICNS.exists()
    assert DESKTOP_ICON_ICO.exists()
    with Image.open(DESKTOP_ICON_PNG) as icon:
        assert icon.size == (512, 512)
        assert icon.mode == "RGBA"
