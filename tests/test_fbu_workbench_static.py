from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FBU_HTML = ROOT / "bonus_platform" / "static" / "fbu-performance.html"


def test_fbu_sidebar_expands_on_desktop_hover_and_focus():
    html = FBU_HTML.read_text(encoding="utf-8")

    desktop_sidebar = html.split("HRIS reference control language", 1)[1].split(".top-bar {", 1)[0]
    top_bar = html.split(".top-bar {", 1)[1].split("}", 1)[0]

    assert "position: fixed;" in desktop_sidebar
    assert "left: 12px;" in desktop_sidebar
    assert "width: 64px;" in desktop_sidebar
    assert "background: #ffffff;" in desktop_sidebar
    assert "transition: width 220ms cubic-bezier(0.2, 0.8, 0.2, 1)" in desktop_sidebar
    assert ".sidebar:hover," in desktop_sidebar
    assert ".sidebar:focus-within" in desktop_sidebar
    assert "width: 196px;" in desktop_sidebar
    assert ".sidebar:hover ~ .main-content" in desktop_sidebar
    assert ".sidebar:focus-within ~ .main-content" in desktop_sidebar
    assert "margin-left: 132px;" in desktop_sidebar
    assert "width: auto;" in desktop_sidebar
    assert ".sidebar:hover .nav-item-text" in desktop_sidebar
    assert "min-width: 0;" in html.split(".step-section {", 1)[1].split("}", 1)[0]
    assert "overflow-x: auto;" in html.split(".final-results .data-table-container {", 1)[1].split("}", 1)[0]
    step_help = html.split(".step-help {", 1)[1].split("}", 1)[0]
    assert "width: 220px;" in step_help
    assert "flex:" not in step_help
    assert "position: relative;" in top_bar
    assert "z-index: 40;" in top_bar
