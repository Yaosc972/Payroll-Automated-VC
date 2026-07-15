import pytest


@pytest.fixture
def bypass_fbu_access_gate(monkeypatch):
    import bonus_platform.app as app_module

    monkeypatch.setattr(app_module, "_fbu_access_response", lambda request: None)


@pytest.fixture
def bypass_domestic_labor_access_gate(monkeypatch):
    import bonus_platform.app as app_module

    monkeypatch.setattr(app_module, "_domestic_labor_access_response", lambda request: None)


@pytest.fixture
def bypass_overseas_labor_access_gate(monkeypatch):
    import bonus_platform.app as app_module

    monkeypatch.setattr(app_module, "_overseas_labor_access_response", lambda request: None)
