from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "bonus_platform" / "static" / "index.html"
RECRUITMENT_HTML = ROOT / "bonus_platform" / "static" / "recruitment.html"
LABOR_HTML = ROOT / "bonus_platform" / "static" / "labor.html"
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
    assert 'href="recruitment.html"' in html
    assert 'href="labor.html"' in html
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


def test_labor_page_is_desktop_placeholder_with_local_animation():
    html = LABOR_HTML.read_text(encoding="utf-8")
    css = STYLES_CSS.read_text(encoding="utf-8")

    assert "国内劳务工薪酬核算开发中" in html
    assert "Under Development · Stay Tuned" in html
    assert 'href="/"' in html
    assert "kinetic-sculpture" in html
    assert "@keyframes gearSpin" in css
    assert "@keyframes constructionWave" in css


def test_desktop_builder_uses_platform_logo_icons():
    package = DESKTOP_PACKAGE.read_text(encoding="utf-8")

    assert '"icon": "assets/icon.icns"' in package
    assert '"icon": "assets/icon.ico"' in package
    assert DESKTOP_ICON_ICNS.exists()
    assert DESKTOP_ICON_ICO.exists()
    with Image.open(DESKTOP_ICON_PNG) as icon:
        assert icon.size == (512, 512)
        assert icon.mode == "RGBA"
