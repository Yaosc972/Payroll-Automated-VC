from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SHOWCASE = ROOT / "bonus_platform" / "static" / "fbu-showcase.html"
ASSET_DIR = ROOT / "bonus_platform" / "static" / "assets" / "fbu-showcase"


def test_fbu_showcase_contains_competition_story_and_live_entry():
    html = SHOWCASE.read_text(encoding="utf-8")

    for required in [
        "FBU美洲绩效奖金核算",
        "AI协同构建",
        "规则确定性执行",
        "人员核对",
        "考勤工时",
        "薪资数据",
        "绩效数据",
        "核算检查",
        "确认导出",
        "https://sigma-workbench.vercel.app/",
    ]:
        assert required in html


def test_fbu_showcase_uses_local_sanitized_product_screenshots():
    html = SHOWCASE.read_text(encoding="utf-8")

    for filename in ["results.png", "check.png", "salary.png"]:
        assert (ASSET_DIR / filename).exists()
        assert f"assets/fbu-showcase/{filename}" in html

    assert "assets/fbu-showcase/sigma-logo-latest.png" in html
    assert (ASSET_DIR / "sigma-logo-header.png").exists()
    assert "assets/fbu-showcase/sigma-logo-header.png" in html
    assert "<span>西格玛工作台</span>" in html
    assert "fbu-performance.html" not in html

    for private_value in ["zt0003518", "朱杏仪", "e0550999"]:
        assert private_value not in html


def test_fbu_showcase_has_responsive_and_accessible_interactions():
    html = SHOWCASE.read_text(encoding="utf-8")

    assert 'name="viewport"' in html
    assert "prefers-reduced-motion" in html
    assert 'aria-label="关闭截图预览"' in html
    assert "dialog" in html
    assert "IntersectionObserver" in html
    assert ".section h2" in html
    assert "white-space: nowrap" in html
