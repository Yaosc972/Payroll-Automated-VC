from fastapi.testclient import TestClient

import bonus_platform.app as app_module
import bonus_platform.auth as auth_module
from bonus_platform.app import app
from bonus_platform.engine.labor.production_readiness import evaluate_labor_production_readiness


def _p1_env():
    return {
        "SIGMA_LABOR_P1_REQUIRED": "true",
        "SIGMA_LABOR_AUTH_REQUIRED": "true",
        "SIGMA_LABOR_STATE_BACKEND": "postgres",
        "SIGMA_LABOR_DATABASE_URL": "postgres://private",
        "SIGMA_LABOR_EXECUTION_MODE": "personal-worker",
        "SIGMA_LABOR_OPERATIONS_TOKEN": "ops-token",
        "SIGMA_LABOR_EXTERNAL_AI_ENABLED": "false",
    }


def _build_info():
    return {"status": "current", "buildId": "p1-build", "apiContractVersion": 2}


def test_p1_snapshot_uses_authoritative_worker_queue_health(monkeypatch):
    expected_queue_health = {"backend": "postgres", "configured": True, "ready": True}
    monkeypatch.setattr(
        app_module,
        "labor_p1_worker_job_store_health",
        lambda: expected_queue_health,
        raising=False,
    )
    monkeypatch.setattr(app_module, "labor_persistent_storage_info", lambda: {})
    monkeypatch.setattr(app_module, "labor_persistent_storage_health", lambda **_kwargs: {})
    monkeypatch.setattr(app_module, "labor_worker_identity_health", lambda: {})
    monkeypatch.setattr(app_module, "_labor_build_snapshot", lambda: {})
    monkeypatch.setattr(app_module, "labor_auth_health", lambda: {})
    monkeypatch.setattr(app_module, "labor_postgres_state_health", lambda: {})
    monkeypatch.setattr(
        app_module,
        "evaluate_labor_production_readiness",
        lambda **kwargs: kwargs["queue_health"],
    )

    assert app_module._labor_p1_readiness_snapshot() == expected_queue_health


def test_p1_readiness_blocks_missing_auth_and_authoritative_state():
    result = evaluate_labor_production_readiness(
        env=_p1_env(),
        storage_info={"enabled": True, "backend": "supabase", "environment": "uat"},
        queue_health={"backend": "postgres", "configured": True, "ready": True},
        build_info=_build_info(),
        auth_health={"ready": False},
        state_health={"backend": "postgres", "configured": True, "ready": False},
        storage_health={"ready": True, "private": True, "directUpload": True, "directDownload": True},
        worker_identity_health={"ready": True, "backend": "postgres"},
    )

    blocker_codes = {item["code"] for item in result["blockers"]}
    assert "trusted_auth_required" in blocker_codes
    assert "postgres_state_required" in blocker_codes
    assert result["p1"]["ready"] is False


def test_p1_readiness_reports_infrastructure_ready_without_claiming_shadow_uat():
    result = evaluate_labor_production_readiness(
        env=_p1_env(),
        storage_info={"enabled": True, "backend": "supabase", "environment": "uat"},
        queue_health={"backend": "postgres", "configured": True, "ready": True},
        build_info=_build_info(),
        auth_health={"ready": True, "provider": "feishu", "databaseBackend": "postgres"},
        state_health={"backend": "postgres", "configured": True, "ready": True, "missingTables": []},
        storage_health={"ready": True, "private": True, "directUpload": True, "directDownload": True},
        worker_identity_health={"ready": True, "backend": "postgres"},
    )

    assert result["status"] == "ready_for_p1_integration"
    assert result["readinessLevel"] == "p1_infrastructure"
    assert result["p1"]["ready"] is True
    assert result["manualReviewRequired"] is True
    assert result["directPaymentAllowed"] is False


def test_p1_readiness_does_not_require_legacy_static_worker_tokens():
    env = _p1_env()
    env.pop("SIGMA_LABOR_WORKER_TOKENS", None)

    result = evaluate_labor_production_readiness(
        env=env,
        storage_info={"enabled": True, "backend": "supabase", "environment": "uat"},
        queue_health={"backend": "postgres", "configured": True, "ready": True},
        build_info=_build_info(),
        auth_health={"ready": True},
        state_health={"backend": "postgres", "configured": True, "ready": True},
        storage_health={"ready": True, "private": True, "directUpload": True, "directDownload": True},
        worker_identity_health={"ready": True, "backend": "postgres"},
    )

    assert "worker_tokens_required" not in {item["code"] for item in result["blockers"]}
    assert result["p1"]["ready"] is True


def test_p1_readiness_snapshot_reuses_recent_success_and_supports_forced_refresh(monkeypatch):
    for key, value in _p1_env().items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("SIGMA_LABOR_P1_READINESS_CACHE_SECONDS", "30")
    app_module._LABOR_P1_READINESS_CACHE.clear()
    calls = {"queue": 0}

    def queue_health():
        calls["queue"] += 1
        return {"backend": "postgres", "configured": True, "ready": True}

    monkeypatch.setattr(app_module, "labor_p1_worker_job_store_health", queue_health)
    monkeypatch.setattr(
        app_module,
        "labor_persistent_storage_info",
        lambda: {"enabled": True, "backend": "supabase", "environment": "production"},
    )
    monkeypatch.setattr(
        app_module,
        "labor_persistent_storage_health",
        lambda **_kwargs: {
            "ready": True,
            "private": True,
            "directUpload": True,
            "directDownload": True,
        },
    )
    monkeypatch.setattr(app_module, "labor_worker_identity_health", lambda: {"ready": True, "backend": "postgres"})
    monkeypatch.setattr(app_module, "labor_auth_health", lambda: {"ready": True})
    monkeypatch.setattr(
        app_module,
        "labor_postgres_state_health",
        lambda: {"backend": "postgres", "configured": True, "ready": True},
    )
    monkeypatch.setattr(app_module, "_labor_build_snapshot", _build_info)

    first = app_module._labor_p1_readiness_snapshot()
    second = app_module._labor_p1_readiness_snapshot()
    refreshed = app_module._labor_p1_readiness_snapshot(force_refresh=True)

    assert first["p1"]["ready"] is True
    assert second == first
    assert refreshed["p1"]["ready"] is True
    assert calls["queue"] == 2


def test_p1_auth_health_requires_feishu_postgres_secure_cookie_and_no_mock(monkeypatch):
    monkeypatch.setattr(
        auth_module,
        "admin_store_health",
        lambda: {"backend": "postgres", "configured": True, "ready": True},
    )
    env = {
        "SIGMA_LABOR_AUTH_REQUIRED": "true",
        "ADMIN_DATABASE_URL": "postgres://private",
        "FEISHU_APP_ID": "app-id",
        "FEISHU_APP_SECRET": "app-secret",
        "FEISHU_REDIRECT_URI": "https://example.com/api/auth/feishu/callback",
        "SESSION_COOKIE_SECURE": "true",
    }

    health = auth_module.labor_auth_health(env)

    assert health == {
        "ready": True,
        "required": True,
        "provider": "feishu",
        "providerConfigured": True,
        "databaseBackend": "postgres",
        "databaseReady": True,
        "secureCookie": True,
        "mockLoginEnabled": False,
    }


def test_p1_hard_gate_blocks_formal_run_creation(monkeypatch, tmp_path):
    monkeypatch.setenv("SIGMA_LABOR_P1_REQUIRED", "1")
    monkeypatch.setenv("SIGMA_LABOR_AUTH_REQUIRED", "0")
    monkeypatch.setattr(
        app_module,
        "_labor_p1_readiness_snapshot",
        lambda: {
            "p1": {"ready": False},
            "blockers": [{"code": "postgres_state_required", "message": "状态库不可用。"}],
        },
        raising=False,
    )
    monkeypatch.setattr(app_module, "LABOR_RUNS_DIR", tmp_path / "runs")

    with TestClient(app) as client:
        access = client.get("/api/labor/access").json()
        response = client.post(
            "/api/labor/runs",
            headers={
                "x-sigma-labor-api-contract": str(access["apiContractVersion"]),
                "x-sigma-labor-ui-version": str(access["version"]),
                "x-sigma-labor-ui-build": str(access["buildId"]),
            },
            json={
                "supplierName": "Blocked Supplier",
                "periodStart": "2026-07-01",
                "periodEnd": "2026-07-07",
            },
        )

    assert response.status_code == 503
    assert response.json()["detail"]["errorCode"] == "LABOR_P1_NOT_READY"
    assert response.json()["detail"]["blockerCodes"] == ["postgres_state_required"]


def test_labor_access_selects_private_direct_upload_only_when_p1_is_required(monkeypatch):
    monkeypatch.setenv("SIGMA_LABOR_P1_REQUIRED", "1")

    with TestClient(app) as client:
        access = client.get("/api/labor/access").json()

    assert access["p1"]["required"] is True
    assert access["p1"]["uploadMode"] == "signed_private_direct"
    assert access["p1"]["legacyMultipartAllowed"] is False


def test_p1_hard_gate_targets_formal_data_flow_not_device_bootstrap():
    assert app_module._labor_p1_formal_mutation("/api/labor/runs/labor-1/upload-intents", "POST") is True
    assert app_module._labor_p1_formal_mutation(
        "/api/labor/runs/labor-1/upload-intents/batch-finalize",
        "POST",
    ) is True
    assert app_module._labor_p1_formal_mutation("/api/labor/runs/labor-1/extract-and-compare", "POST") is True
    assert app_module._labor_p1_formal_mutation("/api/labor/worker/devices", "POST") is False
    assert app_module._labor_p1_formal_mutation("/api/labor/worker/devices/device-1/rotate", "POST") is False


def test_p1_hard_gate_covers_the_entire_worker_task_protocol():
    task_requests = (
        ("/api/labor/worker/jobs/claim", "POST"),
        ("/api/labor/worker/jobs/job-1/heartbeat", "POST"),
        ("/api/labor/worker/jobs/job-1/input", "GET"),
        ("/api/labor/worker/jobs/job-1/input-manifest", "GET"),
        ("/api/labor/worker/jobs/job-1/input-file", "GET"),
        ("/api/labor/worker/jobs/job-1/mapping-preflight-result", "POST"),
        ("/api/labor/worker/jobs/job-1/result", "POST"),
        ("/api/labor/worker/jobs/job-1/events", "POST"),
        ("/api/labor/worker/jobs/job-1/complete", "POST"),
        ("/api/labor/worker/jobs/job-1/fail", "POST"),
    )

    assert all(app_module._labor_p1_formal_request(path, method) for path, method in task_requests)
    assert app_module._labor_p1_formal_request("/api/labor/worker/version", "GET") is False
    assert app_module._labor_p1_formal_request("/api/labor/worker/devices", "POST") is False


def test_p1_not_ready_blocks_worker_claim_before_identity_resolution(monkeypatch):
    monkeypatch.setenv("SIGMA_LABOR_P1_REQUIRED", "1")
    monkeypatch.setenv("SIGMA_LABOR_AUTH_REQUIRED", "0")
    monkeypatch.setattr(
        app_module,
        "_labor_p1_readiness_snapshot",
        lambda: {
            "p1": {"ready": False},
            "blockers": [{"code": "private_storage_required", "message": "私有存储不可用。"}],
        },
    )
    monkeypatch.setattr(
        app_module,
        "_labor_worker_identity",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("identity must not resolve")),
    )

    response = TestClient(app).post("/api/labor/worker/jobs/claim")

    assert response.status_code == 503
    assert response.json()["detail"]["errorCode"] == "LABOR_P1_NOT_READY"
    assert response.json()["detail"]["blockerCodes"] == ["private_storage_required"]
