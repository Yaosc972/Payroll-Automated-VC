from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_labor_worker_page_distinguishes_connection_states():
    source = (ROOT / "bonus_platform" / "static" / "overseas-labor.js").read_text(encoding="utf-8")

    for state in ("online", "recovering", "identity_expired", "offline"):
        assert state in source
    assert "核对助手身份已失效" in source
    assert "核对助手正在恢复连接" in source
    assert "核对助手网络已离线" in source
    assert "请打开助手查看代理或网络原因" in source


def test_labor_worker_release_ui_waits_for_matching_platform_pair():
    source = (ROOT / "bonus_platform" / "static" / "overseas-labor.js").read_text(encoding="utf-8")
    html = (ROOT / "bonus_platform" / "static" / "overseas-labor.html").read_text(encoding="utf-8")

    assert "finalized.published === true" in source
    assert "两个平台版本一致后才会统一生效" in source
    assert "已安全暂存" in source
    assert "双平台已统一发布" in source
    assert "上传待发布安装包" in html
    assert "隐私与安全性 → 仍要打开" in html
    assert "更多信息 → 仍要运行" in html
