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
