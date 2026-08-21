from __future__ import annotations

import pytest

from bonus_platform.engine.fbu_performance import postgres_state


@pytest.fixture(autouse=True)
def reset_postgres_state_availability():
    postgres_state.reset_fbu_postgres_state_availability()
    yield
    postgres_state.reset_fbu_postgres_state_availability()


def test_three_way_merge_preserves_independent_row_updates():
    base = {
        "rows": [
            {"row_id": "leave:1", "confirmation_status": "pending"},
            {"row_id": "leave:2", "confirmation_status": "pending"},
        ],
        "summary": {"pending_count": 2},
    }
    desired = {
        "rows": [
            {"row_id": "leave:1", "confirmation_status": "pending"},
            {"row_id": "leave:2", "confirmation_status": "excluded"},
        ],
        "summary": {"pending_count": 1},
    }
    latest = {
        "rows": [
            {"row_id": "leave:1", "confirmation_status": "confirmed"},
            {"row_id": "leave:2", "confirmation_status": "pending"},
        ],
        "summary": {"pending_count": 1},
    }

    merged = postgres_state.merge_json_changes(base, desired, latest)
    merged = postgres_state._normalize_section("supplemental_leave_data", merged)

    assert {
        row["row_id"]: row["confirmation_status"]
        for row in merged["rows"]
    } == {"leave:1": "confirmed", "leave:2": "excluded"}
    assert merged["summary"]["pending_count"] == 0


def test_section_save_retries_revision_conflict_with_three_way_merge(monkeypatch):
    calls = []
    base = {
        "rows": [
            {"row_id": "leave:1", "confirmation_status": "pending"},
            {"row_id": "leave:2", "confirmation_status": "pending"},
        ],
        "summary": {"pending_count": 2},
    }
    desired = {
        "rows": [
            {"row_id": "leave:1", "confirmation_status": "pending"},
            {"row_id": "leave:2", "confirmation_status": "excluded"},
        ],
        "summary": {"pending_count": 1},
    }
    latest = {
        "rows": [
            {"row_id": "leave:1", "confirmation_status": "confirmed"},
            {"row_id": "leave:2", "confirmation_status": "pending"},
        ],
        "summary": {"pending_count": 1},
    }

    def rpc(name, payload):
        calls.append((name, payload))
        if len(calls) == 1:
            return {"applied": False, "data": latest, "revision": 8}
        return {"applied": True, "data": payload["p_data"], "revision": 9}

    monkeypatch.setattr(postgres_state, "_rpc", rpc)

    result = postgres_state.save_section_with_retry(
        "run_123",
        "supplemental_leave_data",
        base=base,
        desired=desired,
        expected_revision=7,
    )

    assert [call[1]["p_expected_revision"] for call in calls] == [7, 8]
    by_id = {
        row["row_id"]: row["confirmation_status"]
        for row in result["data"]["rows"]
    }
    assert by_id == {"leave:1": "confirmed", "leave:2": "excluded"}
    assert result["data"]["summary"]["pending_count"] == 0


def test_job_patch_uses_remote_state_transition_result(monkeypatch):
    monkeypatch.setattr(
        postgres_state,
        "_rpc",
        lambda name, payload: {
            "applied": False,
            "data": {"jobId": "job1", "status": "completed"},
            "revision": 4,
        },
    )

    result = postgres_state.patch_job(
        "run1",
        "job1",
        seed=None,
        patch={"status": "queued"},
        allowed_from=["uploading", "failed"],
    )

    assert result["status"] == "completed"
    assert result["__transition_applied"] is False


def test_missing_rpc_is_treated_as_pre_migration_fallback():
    error = postgres_state.FBUPostgresStateError(
        404,
        '{"code":"PGRST202","message":"Could not find the function public.sigma_fbu_commit_core"}',
    )

    assert postgres_state._schema_missing(error) is True


def test_stale_core_retry_does_not_regress_a_later_completed_step(monkeypatch):
    calls = []
    base = {"run_id": "run1", "current_step": 2, "status": "step2", "salary_file": "old.xlsx"}
    desired = {**base, "current_step": 3, "status": "step3", "performance_file": "perf.xlsx"}
    latest = {**base, "current_step": 5, "status": "completed", "salary_file": "new.xlsx"}

    def rpc(name, payload):
        calls.append(payload)
        if len(calls) == 1:
            return {"applied": False, "data": latest, "revision": 9}
        return {"applied": True, "data": payload["p_data"], "revision": 10}

    monkeypatch.setattr(postgres_state, "_rpc", rpc)
    result = postgres_state.save_core_with_retry(
        "run1",
        base=base,
        desired=desired,
        expected_revision=8,
    )

    assert result["data"]["current_step"] == 5
    assert result["data"]["status"] == "completed"
    assert result["data"]["performance_file"] == "perf.xlsx"
    assert result["data"]["salary_file"] == "new.xlsx"
