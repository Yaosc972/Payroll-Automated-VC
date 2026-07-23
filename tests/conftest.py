from __future__ import annotations

import os
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def bypass_fbu_access_gate(monkeypatch):
    import bonus_platform.app as app_module

    monkeypatch.setattr(app_module, "_fbu_access_response", lambda request: None)


@pytest.fixture
def bypass_domestic_labor_access_gate(monkeypatch):
    import bonus_platform.app as app_module

    monkeypatch.setattr(app_module, "_domestic_labor_access_response", lambda request: None)


@pytest.fixture(autouse=True)
def _attach_current_labor_client_contract_to_test_requests(monkeypatch):
    """Make legacy TestClient calls behave like the current labor page.

    Production has no bypass. Dedicated contract tests set the test-only
    SIGMA_TEST_NO_LABOR_CONTRACT_HEADERS flag to exercise missing/stale headers.
    """

    original_request = TestClient.request

    def request_with_contract(self, method, url, *args, **kwargs):
        path = urlsplit(str(url)).path
        guarded = (
            str(method).upper() in {"POST", "PUT", "PATCH", "DELETE"}
            and (
                path == "/api/labor/runs"
                or path.startswith("/api/labor/runs/")
                or path == "/api/labor/material-runs"
            )
        )
        if guarded and os.environ.get("SIGMA_TEST_NO_LABOR_CONTRACT_HEADERS") != "1":
            import bonus_platform.app as app_module

            build = app_module._labor_build_snapshot()
            headers = dict(kwargs.get("headers") or {})
            headers.setdefault("x-sigma-labor-api-contract", str(app_module.OVERSEAS_LABOR_API_CONTRACT_VERSION))
            headers.setdefault("x-sigma-labor-ui-version", app_module.OVERSEAS_LABOR_MODULE_VERSION)
            headers.setdefault("x-sigma-labor-ui-build", str(build.get("buildId") or ""))
            kwargs["headers"] = headers
        return original_request(self, method, url, *args, **kwargs)

    monkeypatch.setattr(TestClient, "request", request_with_contract)


@pytest.fixture
def bypass_overseas_labor_access_gate(monkeypatch):
    import bonus_platform.app as app_module

    monkeypatch.setattr(app_module, "_overseas_labor_access_response", lambda request: None)
