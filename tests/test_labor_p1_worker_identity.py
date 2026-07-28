from datetime import datetime, timezone
import hashlib

from fastapi.testclient import TestClient
import pytest

import bonus_platform.app as app_module
import bonus_platform.engine.admin_store as admin_store
from bonus_platform.app import app
from bonus_platform.engine.labor import worker_identity_postgres as identity


class FakeResult:
    def __init__(self, row=None, rows=None):
        self._row = row
        self._rows = rows or []

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


class FakeConnection:
    def __init__(self, results):
        self.results = list(results)
        self.queries = []
        self.committed = False
        self.rolled_back = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=None):
        self.queries.append((" ".join(sql.split()), params))
        result = self.results.pop(0) if self.results else FakeResult()
        if isinstance(result, Exception):
            raise result
        return result

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def _device_row():
    now = datetime(2026, 7, 16, 8, 0, tzinfo=timezone.utc)
    return {
        "id": "labor_device_1",
        "owner_user_id": "overseasAdminUser",
        "display_name": "My Mac",
        "platform": "macos-arm64",
        "worker_version": "0.3.0",
        "capabilities": {},
        "last_seen_at": None,
        "revoked_at": None,
        "created_at": now,
        "updated_at": now,
    }


def test_p1_worker_token_is_returned_once_but_only_sha256_is_persisted(monkeypatch):
    device = _device_row()
    connection = FakeConnection(
        [FakeResult(row=device), FakeResult(), FakeResult(), FakeResult()]
    )
    monkeypatch.setattr(identity.secrets, "token_urlsafe", lambda _size: "opaque-worker-token-value")

    issued = identity.issue_labor_worker_token(
        owner_user_id="overseasAdminUser",
        actor_user_id="overseasAdminUser",
        display_name="My Mac",
        platform="macos-arm64",
        worker_version="0.3.0",
        ttl_seconds=900,
        device_id="labor_device_1",
        connect=lambda: connection,
    )

    expected_token = "sigma_labor_w1_opaque-worker-token-value"
    expected_hash = hashlib.sha256(expected_token.encode()).hexdigest()
    token_insert = next(item for item in connection.queries if "insert into public.labor_worker_tokens" in item[0].lower())
    assert issued["token"] == expected_token
    assert issued["expiresIn"] == 900
    assert expected_hash in token_insert[1]
    assert expected_token not in str(connection.queries)
    assert connection.committed is True


def test_p1_worker_activation_code_is_short_lived_and_hash_only(monkeypatch):
    device = _device_row()
    connection = FakeConnection(
        [FakeResult(row=device), FakeResult(), FakeResult(), FakeResult()]
    )
    monkeypatch.setattr(identity.secrets, "token_urlsafe", lambda _size: "opaque-activation-code")

    issued = identity.issue_labor_worker_activation(
        owner_user_id="overseasAdminUser",
        actor_user_id="overseasAdminUser",
        display_name="My Mac",
        platform="macos-arm64",
        worker_version="0.3.1",
        ttl_seconds=300,
        device_id="labor_device_1",
        connect=lambda: connection,
    )

    expected_code = "sigma_labor_a1_opaque-activation-code"
    expected_hash = hashlib.sha256(expected_code.encode()).hexdigest()
    token_insert = next(item for item in connection.queries if "insert into public.labor_worker_tokens" in item[0].lower())
    assert issued["activationCode"] == expected_code
    assert issued["expiresIn"] == 300
    assert expected_hash in token_insert[1]
    assert expected_code not in str(connection.queries)
    assert connection.committed is True


def test_p1_worker_activation_exchange_is_atomic_and_returns_worker_token(monkeypatch):
    activation_code = "sigma_labor_a1_exchange-me"
    activation_row = {
        "activation_id": "labor_activation_1",
        "device_id": "labor_device_1",
        "owner_user_id": "overseasAdminUser",
        **{key: value for key, value in _device_row().items() if key != "id"},
    }
    connection = FakeConnection(
        [FakeResult(row=activation_row), FakeResult(), FakeResult(), FakeResult(), FakeResult()]
    )
    monkeypatch.setattr(identity.secrets, "token_urlsafe", lambda _size: "exchanged-worker-token")

    issued = identity.exchange_labor_worker_activation(
        activation_code,
        worker_version="0.3.1",
        ttl_seconds=900,
        connect=lambda: connection,
    )

    expected_token = "sigma_labor_w1_exchanged-worker-token"
    activation_select, select_params = connection.queries[0]
    activation_revoke, revoke_params = connection.queries[1]
    worker_insert = next(item for item in connection.queries if "insert into public.labor_worker_tokens" in item[0].lower())
    assert "for update" in activation_select.lower()
    assert "t.revoked_at is null" in activation_select.lower()
    assert "t.expires_at > now()" in activation_select.lower()
    assert select_params == (hashlib.sha256(activation_code.encode()).hexdigest(),)
    assert "revoked_at=coalesce(revoked_at, now())" in activation_revoke.lower()
    assert revoke_params == ("labor_activation_1",)
    assert hashlib.sha256(expected_token.encode()).hexdigest() in worker_insert[1]
    assert expected_token not in str(connection.queries)
    assert issued["token"] == expected_token
    assert issued["device"]["id"] == "labor_device_1"
    assert connection.committed is True


def test_p1_worker_activation_exchange_rejects_reused_or_expired_code():
    activation_code = "sigma_labor_a1_reused-or-expired-code"
    connection = FakeConnection([FakeResult(row=None)])

    with pytest.raises(identity.LaborWorkerIdentityInvalid, match="激活码无效或已失效"):
        identity.exchange_labor_worker_activation(
            activation_code,
            worker_version="0.3.2",
            connect=lambda: connection,
        )

    query, params = connection.queries[0]
    normalized = query.lower()
    assert "t.revoked_at is null" in normalized
    assert "t.expires_at > now()" in normalized
    assert "d.revoked_at is null" in normalized
    assert params == (hashlib.sha256(activation_code.encode()).hexdigest(),)
    assert len(connection.queries) == 1
    assert connection.rolled_back is True


def test_p1_worker_activation_exchange_rejects_worker_token_before_database_access():
    connection_opened = False

    def connect():
        nonlocal connection_opened
        connection_opened = True
        return FakeConnection([])

    with pytest.raises(identity.LaborWorkerIdentityInvalid, match="激活码无效或已失效"):
        identity.exchange_labor_worker_activation(
            "sigma_labor_w1_worker-token-cannot-activate",
            worker_version="0.3.2",
            connect=connect,
        )

    assert connection_opened is False


def test_p1_worker_token_resolution_is_device_bound_and_updates_last_seen():
    token = "sigma_labor_w1_resolve-me"
    token_row = {
        "token_id": "labor_token_1",
        "device_id": "labor_device_1",
        "owner_user_id": "overseasAdminUser",
        "expires_at": datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
        "display_name": "My Mac",
        "platform": "macos-arm64",
    }
    connection = FakeConnection([FakeResult(row=token_row), FakeResult(), FakeResult()])

    resolved = identity.resolve_labor_worker_token(
        token,
        worker_version="0.3.1",
        refresh_ttl_seconds=24 * 60 * 60,
        connect=lambda: connection,
    )

    query, params = connection.queries[0]
    assert "join public.labor_worker_devices" in query.lower()
    assert params == (hashlib.sha256(token.encode()).hexdigest(),)
    assert resolved["userId"] == "overseasAdminUser"
    assert resolved["deviceId"] == "labor_device_1"
    device_update = next((sql, params) for sql, params in connection.queries if "last_seen_at=now()" in sql.lower())
    assert "worker_version" in device_update[0].lower()
    assert "0.3.1" in device_update[1]
    token_update = next((sql, params) for sql, params in connection.queries if "last_used_at=now()" in sql.lower())
    assert "greatest(expires_at, now()+(%s*interval '1 second'))" in token_update[0].lower()
    assert token_update[1][:2] == (24 * 60 * 60, 24 * 60 * 60)


def test_p1_worker_token_rejects_expired_or_revoked_record_before_updating_last_seen():
    token = "sigma_labor_w1_expired-or-revoked-token"
    connection = FakeConnection([FakeResult(row=None)])

    with pytest.raises(identity.LaborWorkerIdentityInvalid, match="无效或已失效"):
        identity.resolve_labor_worker_token(
            token,
            worker_version="0.3.1",
            connect=lambda: connection,
        )

    query, params = connection.queries[0]
    normalized = query.lower()
    assert "t.revoked_at is null" in normalized
    assert "t.expires_at > now()" in normalized
    assert "d.revoked_at is null" in normalized
    assert params == (hashlib.sha256(token.encode()).hexdigest(),)
    assert len(connection.queries) == 1
    assert connection.rolled_back is True


def test_p1_worker_token_recovers_recent_naturally_expired_latest_device_token():
    token = "sigma_labor_w1_recover-recent-expiry"
    token_row = {
        "token_id": "labor_token_1",
        "device_id": "labor_device_1",
        "owner_user_id": "overseasAdminUser",
        "expires_at": datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc),
        "display_name": "My Mac",
        "platform": "macos-arm64",
    }
    connection = FakeConnection(
        [
            FakeResult(row=None),
            FakeResult(row=token_row),
            FakeResult(),
            FakeResult(),
            FakeResult(),
        ]
    )

    resolved = identity.resolve_labor_worker_token(
        token,
        worker_version="0.3.12",
        refresh_ttl_seconds=90 * 24 * 60 * 60,
        recovery_grace_seconds=7 * 24 * 60 * 60,
        connect=lambda: connection,
    )

    assert resolved == {
        "userId": "overseasAdminUser",
        "deviceId": "labor_device_1",
    }
    recovery_query, recovery_params = connection.queries[1]
    normalized = recovery_query.lower()
    assert "t.expires_at <= now()" in normalized
    assert "t.revoked_at is null" in normalized
    assert "d.revoked_at is null" in normalized
    assert "newer.created_at > t.created_at" in normalized
    assert recovery_params == (
        hashlib.sha256(token.encode()).hexdigest(),
        7 * 24 * 60 * 60,
    )
    token_update = next(
        (sql, params)
        for sql, params in connection.queries
        if "set last_used_at=now()" in sql.lower()
    )
    assert token_update[1][:2] == (90 * 24 * 60 * 60, 90 * 24 * 60 * 60)
    assert connection.committed is True


def test_p1_worker_token_does_not_recover_when_grace_lookup_finds_no_safe_record():
    token = "sigma_labor_w1_revoked-stale-or-superseded"
    connection = FakeConnection([FakeResult(row=None), FakeResult(row=None)])

    with pytest.raises(identity.LaborWorkerIdentityInvalid, match="无效或已失效"):
        identity.resolve_labor_worker_token(
            token,
            worker_version="0.3.12",
            refresh_ttl_seconds=90 * 24 * 60 * 60,
            recovery_grace_seconds=7 * 24 * 60 * 60,
            connect=lambda: connection,
        )

    assert len(connection.queries) == 2
    assert connection.rolled_back is True


def test_p1_worker_device_revoke_is_owner_scoped_and_revokes_all_active_tokens():
    connection = FakeConnection(
        [FakeResult(row=_device_row()), FakeResult(), FakeResult(), FakeResult()]
    )

    revoked = identity.revoke_labor_worker_device(
        owner_user_id="overseasAdminUser",
        actor_user_id="overseasAdminUser",
        device_id="labor_device_1",
        connect=lambda: connection,
    )

    select_query, select_params = connection.queries[0]
    device_update, device_params = connection.queries[1]
    token_update, token_params = connection.queries[2]
    assert "for update" in select_query.lower()
    assert select_params == ("labor_device_1", "overseasAdminUser")
    assert "update public.labor_worker_devices" in device_update.lower()
    assert "revoked_at=coalesce(revoked_at, now())" in device_update.lower()
    assert device_params == ("labor_device_1", "overseasAdminUser")
    assert "update public.labor_worker_tokens" in token_update.lower()
    assert "revoked_at=coalesce(revoked_at, now())" in token_update.lower()
    assert token_params == ("labor_device_1", "overseasAdminUser")
    assert revoked["id"] == "labor_device_1"
    assert revoked["revoked"] is True
    assert connection.committed is True


def test_p1_worker_token_rotation_does_not_replace_reported_version_with_browser_guess(monkeypatch):
    device = _device_row()
    connection = FakeConnection([FakeResult(row=device), FakeResult(), FakeResult(), FakeResult()])
    monkeypatch.setattr(identity.secrets, "token_urlsafe", lambda _size: "rotated-worker-token")

    issued = identity.issue_labor_worker_token(
        owner_user_id="overseasAdminUser",
        actor_user_id="overseasAdminUser",
        display_name="My Mac",
        platform="macos-arm64",
        worker_version="",
        ttl_seconds=900,
        device_id="labor_device_1",
        connect=lambda: connection,
    )

    assert issued["device"]["workerVersion"] == "0.3.0"
    device_update = next(
        (sql, params)
        for sql, params in connection.queries
        if "update public.labor_worker_devices" in sql.lower()
    )
    assert device_update[1][2] == "0.3.0"


def test_p1_reactivation_code_preserves_current_worker_token_until_exchange(monkeypatch):
    device = _device_row()
    connection = FakeConnection([FakeResult(row=device), FakeResult(), FakeResult(), FakeResult()])
    monkeypatch.setattr(identity.secrets, "token_urlsafe", lambda _size: "replacement-activation")

    identity.issue_labor_worker_activation(
        owner_user_id="overseasAdminUser",
        actor_user_id="overseasAdminUser",
        display_name="My Mac",
        platform="macos-arm64",
        worker_version="",
        ttl_seconds=300,
        device_id="labor_device_1",
        connect=lambda: connection,
    )

    revoke_query = next(
        (sql, params)
        for sql, params in connection.queries
        if "update public.labor_worker_tokens" in sql.lower()
    )
    assert "id like %s" in revoke_query[0].lower()
    assert revoke_query[1][-1] == "labor_activation_%"


@pytest.fixture
def browser_auth_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SIGMA_LABOR_AUTH_REQUIRED", "1")
    monkeypatch.setenv("SIGMA_ENABLE_MOCK_LOGIN", "1")
    monkeypatch.setenv("SIGMA_LABOR_P1_REQUIRED", "1")
    monkeypatch.setenv("SIGMA_LABOR_PUBLIC_URL", "https://sigma.example.com")
    monkeypatch.setattr(admin_store, "get_admin_db_path", lambda: tmp_path / "admin.sqlite")
    monkeypatch.setattr(admin_store, "get_admin_database_url", lambda: "")
    monkeypatch.setattr(app_module, "_labor_p1_readiness_snapshot", lambda: {"p1": {"ready": True}, "blockers": []})
    admin_store._STORE_INITIALIZED = False
    admin_store._STORE_INITIALIZED_TARGET = ""


def test_browser_device_activation_uses_session_owner_and_returns_custom_protocol_url(browser_auth_env, monkeypatch):
    issued = []
    monkeypatch.setattr(app_module, "labor_postgres_state_enabled", lambda: True)
    monkeypatch.setattr(app_module, "labor_auth_health", lambda: {"ready": True})
    monkeypatch.setattr(
        app_module,
        "issue_labor_worker_activation",
        lambda **kwargs: issued.append(kwargs) or {
            "activationCode": "sigma_labor_a1_one-time-code",
            "expiresIn": 300,
            "expiresAt": "2026-07-16T08:15:00Z",
            "device": {"id": "labor_device_1", "displayName": "My Mac"},
        },
        raising=False,
    )

    with TestClient(app) as client:
        assert client.post("/api/auth/mock-login", json={"userId": "overseasAdminUser"}).status_code == 200
        response = client.post(
            "/api/labor/worker/devices",
            json={
                "ownerUserId": "attacker",
                "displayName": "My Mac",
                "platform": "macos-arm64",
                "workerVersion": "0.3.0",
            },
        )

    assert response.status_code == 200
    assert issued[0]["owner_user_id"] == "overseasAdminUser"
    assert issued[0]["actor_user_id"] == "overseasAdminUser"
    assert response.json()["activationUrl"].startswith("sigma-overseas-labor-worker://activate?")
    assert "sigma_labor_a1_one-time-code" in response.json()["activationUrl"]
    assert "sigma_labor_w1_" not in response.json()["activationUrl"]


def test_desktop_activation_exchange_returns_worker_token_without_browser_session(browser_auth_env, monkeypatch):
    exchanged = []
    monkeypatch.setattr(app_module, "labor_postgres_state_enabled", lambda: True)
    monkeypatch.setattr(app_module, "labor_auth_health", lambda: {"ready": True})
    monkeypatch.setattr(
        app_module,
        "exchange_labor_worker_activation",
        lambda code, **kwargs: exchanged.append((code, kwargs)) or {
            "token": "sigma_labor_w1_exchanged-token",
            "expiresIn": 900,
            "expiresAt": "2026-07-16T08:20:00Z",
            "device": {"id": "labor_device_1", "displayName": "My Mac"},
        },
        raising=False,
    )

    response = TestClient(app).post(
        "/api/labor/worker/activate",
        json={
            "activationCode": "sigma_labor_a1_one-time-code",
            "workerVersion": "0.3.1",
        },
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["token"] == "sigma_labor_w1_exchanged-token"
    assert exchanged[0][0] == "sigma_labor_a1_one-time-code"
    assert exchanged[0][1]["worker_version"] == "0.3.1"


def test_p1_device_activation_rejects_untrusted_auth_before_issuing_a_token(monkeypatch):
    issued = []
    monkeypatch.setenv("SIGMA_LABOR_P1_REQUIRED", "1")
    monkeypatch.setenv("SIGMA_LABOR_AUTH_REQUIRED", "0")
    monkeypatch.setattr(app_module, "labor_postgres_state_enabled", lambda: True)
    monkeypatch.setattr(app_module, "labor_auth_health", lambda: {"ready": False})
    monkeypatch.setattr(
        app_module,
        "issue_labor_worker_activation",
        lambda **kwargs: issued.append(kwargs) or {
            "activationCode": "must-not-be-issued",
            "expiresIn": 300,
            "expiresAt": "2026-07-16T08:15:00Z",
            "device": {"id": "labor_device_untrusted"},
        },
    )

    response = TestClient(app).post(
        "/api/labor/worker/devices",
        json={"displayName": "Untrusted Mac", "platform": "macos-arm64"},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["errorCode"] == "LABOR_P1_TRUSTED_AUTH_REQUIRED"
    assert issued == []


def test_p1_worker_bearer_identity_uses_postgres_resolver_not_static_env(monkeypatch):
    resolved_calls = []
    monkeypatch.setenv(
        "SIGMA_LABOR_WORKER_TOKENS",
        '{"database-token":{"userId":"wrong","deviceId":"wrong"}}',
    )
    monkeypatch.delenv("SIGMA_LABOR_WORKER_TOKEN_TTL_SECONDS", raising=False)
    monkeypatch.setattr(app_module, "labor_postgres_state_enabled", lambda: True)
    monkeypatch.setattr(
        app_module,
        "resolve_labor_worker_token",
        lambda raw, **kwargs: resolved_calls.append((raw, kwargs))
        or {"userId": "database-user", "deviceId": "database-device", "raw": raw},
        raising=False,
    )

    resolved = app_module._labor_worker_identity("Bearer database-token")

    assert resolved == {"userId": "database-user", "deviceId": "database-device"}
    assert resolved_calls == [
        (
            "database-token",
            {
                "worker_version": "",
                "refresh_ttl_seconds": 90 * 24 * 60 * 60,
                "recovery_grace_seconds": 7 * 24 * 60 * 60,
            },
        )
    ]


def test_browser_device_revocation_immediately_invalidates_old_worker_bearer(
    browser_auth_env,
    monkeypatch,
):
    token = "sigma_labor_w1_browser-revocation-test"
    token_state = {"active": True}
    revoke_calls = []

    def resolve(raw, **_kwargs):
        if raw != token or not token_state["active"]:
            raise identity.LaborWorkerIdentityInvalid("Worker 身份令牌无效或已失效。")
        return {"userId": "overseasAdminUser", "deviceId": "labor_device_1"}

    def revoke(**kwargs):
        revoke_calls.append(kwargs)
        token_state["active"] = False
        return {
            "id": "labor_device_1",
            "ownerUserId": "overseasAdminUser",
            "displayName": "My Mac",
            "revoked": True,
        }

    monkeypatch.setattr(app_module, "labor_postgres_state_enabled", lambda: True)
    monkeypatch.setattr(app_module, "labor_auth_health", lambda: {"ready": True})
    monkeypatch.setattr(app_module, "resolve_labor_worker_token", resolve)
    monkeypatch.setattr(app_module, "revoke_labor_worker_device", revoke)
    monkeypatch.setattr(app_module, "claim_labor_worker_job", lambda **_kwargs: None)
    monkeypatch.setattr(app_module, "_labor_assert_runtime_current", lambda: None)

    worker_headers = {
        "authorization": f"Bearer {token}",
        "x-worker-version": app_module.OVERSEAS_LABOR_REQUIRED_WORKER_VERSION,
    }
    with TestClient(app) as client:
        assert client.post(
            "/api/auth/mock-login",
            json={"userId": "overseasAdminUser"},
        ).status_code == 200
        before = client.post("/api/labor/worker/jobs/claim", headers=worker_headers)
        revoked = client.delete("/api/labor/worker/devices/labor_device_1")
        after = client.post("/api/labor/worker/jobs/claim", headers=worker_headers)

    assert before.status_code == 200
    assert before.json() == {"job": None}
    assert revoked.status_code == 200
    assert revoked.json()["revoked"] is True
    assert revoke_calls == [
        {
            "owner_user_id": "overseasAdminUser",
            "actor_user_id": "overseasAdminUser",
            "device_id": "labor_device_1",
        }
    ]
    assert after.status_code == 401
    assert "无效或已失效" in after.json()["detail"]
    assert token not in revoked.text
