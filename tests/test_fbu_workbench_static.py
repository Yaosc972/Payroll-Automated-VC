from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FBU_HTML = ROOT / "bonus_platform" / "static" / "fbu-performance.html"
FBU_JS = ROOT / "bonus_platform" / "static" / "fbu-performance.js"


def test_fbu_navigation_lives_in_top_bar_with_logo():
    html = FBU_HTML.read_text(encoding="utf-8")

    body = html.split("<body>", 1)[1]
    top_bar_markup = body.split('<header class="top-bar">', 1)[1].split("<!-- Content Area -->", 1)[0]

    assert '<aside class="sidebar">' not in body
    assert '<a class="top-module-copy top-title-lockup" href="/" aria-label="返回西格玛工作台首页">' in top_bar_markup
    assert "onclick=\"navigateTo('activities')\"" not in top_bar_markup
    assert 'class="top-title-logo"' in top_bar_markup
    assert "assets/bonus-logo-header-blue.png" in top_bar_markup
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


def test_workbench_empty_state_uses_compact_illustration():
    html = FBU_HTML.read_text(encoding="utf-8")
    js = FBU_JS.read_text(encoding="utf-8")

    assert "workbench-empty-illustration" in html
    assert "workbench-empty-illustration" in js
    assert "创建本月活动后，再导入花名册、考勤、薪资和绩效数据。" in js
    assert "grid" in html.split(".workbench-empty {", 1)[1].split("}", 1)[0]
