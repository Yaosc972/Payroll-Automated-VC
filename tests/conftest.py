import pytest


@pytest.fixture
def bypass_fbu_access_gate(monkeypatch):
    import bonus_platform.app as app_module

    monkeypatch.setattr(app_module, "_fbu_access_response", lambda request: None)
