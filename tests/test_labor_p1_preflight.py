from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.labor_p1_preflight import normalize_base_url, run_preflight


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FakeResponse:
    def __init__(self, status_code: int, payload: object):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, responses: dict[str, FakeResponse]):
        self.responses = responses
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(self, url: str, *, headers: dict[str, str] | None = None):
        path = "/" + url.split("/", 3)[-1] if "/" in url.split("://", 1)[-1] else "/"
        self.calls.append((path, dict(headers or {})))
        return self.responses[path]


def _check(result: dict, check_id: str) -> dict:
    return next(item for item in result["checks"] if item["id"] == check_id)


def test_vercel_config_does_not_force_legacy_blob_storage_for_p1():
    config = json.loads((PROJECT_ROOT / "vercel.json").read_text(encoding="utf-8"))

    assert "SIGMA_LABOR_STORAGE_BACKEND" not in config.get("env", {})


def test_vercel_function_runs_in_supabase_west_region_with_fluid_duration():
    config = json.loads((PROJECT_ROOT / "vercel.json").read_text(encoding="utf-8"))
    function = config["functions"]["api/index.py"]

    assert function["regions"] == ["pdx1"]
    assert function["maxDuration"] == 300


def test_preflight_rejects_insecure_non_local_target():
    with pytest.raises(ValueError, match="HTTPS"):
        normalize_base_url("http://uat.example.com")

    assert normalize_base_url("http://127.0.0.1:8444/") == "http://127.0.0.1:8444"
    assert normalize_base_url("https://uat.example.com/") == "https://uat.example.com"


def test_preflight_identifies_stale_deployment_without_reading_secrets():
    client = FakeClient(
        {
            "/api/auth/feishu/config": FakeResponse(404, {"detail": "Not Found"}),
            "/api/labor/access": FakeResponse(
                200,
                {"version": "0.4-uat", "access": "uat_trial"},
            ),
        }
    )

    result = run_preflight(
        "https://sigma-workbench-uat.vercel.app",
        operations_token="",
        client=client,
    )

    assert result["ready"] is False
    assert {item["code"] for item in result["blockers"]} == {
        "deployment_contract_stale",
        "p1_mode_not_enabled",
        "operations_token_missing",
    }
    assert _check(result, "feishu_auth")["status"] == "stale"
    assert _check(result, "p1_contract")["observedVersion"] == "0.4-uat"
    assert [path for path, _headers in client.calls] == [
        "/api/auth/feishu/config",
        "/api/labor/access",
    ]


def test_preflight_uses_authoritative_readiness_and_never_echoes_token():
    token = "ops-super-secret"
    client = FakeClient(
        {
            "/api/auth/feishu/config": FakeResponse(
                200,
                {"configured": True, "redirectUri": "https://private.example.com/callback"},
            ),
            "/api/labor/access": FakeResponse(
                200,
                {
                    "version": "0.5-uat",
                    "buildId": "build-current",
                    "p1": {"required": True, "uploadMode": "signed_private_direct"},
                    "runtimeGate": {"runtimeSourceCurrent": True},
                },
            ),
            "/api/labor/production-readiness": FakeResponse(
                200,
                {
                    "status": "ready_for_p1_integration",
                    "p1": {"required": True, "ready": True},
                    "blockers": [],
                    "manualReviewRequired": True,
                    "directPaymentAllowed": False,
                },
            ),
        }
    )

    result = run_preflight(
        "https://uat.example.com",
        operations_token=token,
        client=client,
    )

    assert result["ready"] is True
    assert result["blockers"] == []
    assert _check(result, "production_readiness")["status"] == "passed"
    readiness_headers = client.calls[-1][1]
    assert readiness_headers == {"x-admin-token": token}
    serialized = json.dumps(result, ensure_ascii=False)
    assert token not in serialized
    assert "private.example.com" not in serialized


def test_preflight_preserves_sanitized_readiness_blocker_codes():
    client = FakeClient(
        {
            "/api/auth/feishu/config": FakeResponse(200, {"configured": True}),
            "/api/labor/access": FakeResponse(
                200,
                {
                    "version": "0.5-uat",
                    "p1": {"required": True, "uploadMode": "signed_private_direct"},
                    "runtimeGate": {"runtimeSourceCurrent": True},
                },
            ),
            "/api/labor/production-readiness": FakeResponse(
                200,
                {
                    "status": "blocked",
                    "p1": {"required": True, "ready": False},
                    "manualReviewRequired": True,
                    "directPaymentAllowed": False,
                    "blockers": [
                        {"code": "postgres_state_required", "message": "状态库不可用。"},
                        {"code": "private_signed_storage_required", "message": "私有存储不可用。"},
                    ],
                },
            ),
        }
    )

    result = run_preflight(
        "https://uat.example.com",
        operations_token="valid-token",
        client=client,
    )

    assert result["ready"] is False
    assert [item["code"] for item in result["blockers"]] == [
        "postgres_state_required",
        "private_signed_storage_required",
    ]
    assert _check(result, "production_readiness")["status"] == "blocked"
