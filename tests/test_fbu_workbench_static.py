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
    assert ".sidebar:hover .nav-item-text" in desktop_sidebar
    assert "position: relative;" in top_bar
    assert "z-index: 40;" in top_bar
