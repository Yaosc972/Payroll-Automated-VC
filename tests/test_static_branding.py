from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "bonus_platform" / "static" / "index.html"
STYLES_CSS = ROOT / "bonus_platform" / "static" / "styles.css"
APP_JS = ROOT / "bonus_platform" / "static" / "app.js"
HEADER_LOGO = ROOT / "bonus_platform" / "static" / "assets" / "bonus-logo-header-transparent.png"


def test_header_uses_transparent_brand_asset_and_favicon_keeps_dark_asset():
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert 'href="assets/bonus-logo-dark.png"' in html
    assert 'src="assets/bonus-logo-header-transparent.png"' in html


def test_header_branding_and_hero_title_have_dedicated_layout_rules():
    html = INDEX_HTML.read_text(encoding="utf-8")
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
    html = INDEX_HTML.read_text(encoding="utf-8")
    app_js = APP_JS.read_text(encoding="utf-8")

    assert "historyFileInput" not in html
    assert "历史奖金表" not in html
    assert "可选历史奖金表" not in html
    assert "historyFileInput" not in app_js
    assert 'form.append("history_file"' not in app_js
