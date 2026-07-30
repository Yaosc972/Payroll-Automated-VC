from datetime import datetime
import json

import pytest

from bonus_platform.engine.labor.worker_jobs_postgres import PostgresLaborWorkerStore, _version_code


class FakeResult:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows or []

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, results):
        self.results = list(results)
        self.queries = []
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=None):
        self.queries.append((" ".join(sql.split()), params))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def commit(self):
        self.committed = True

    def rollback(self):
        pass


def _row(*, status="running", required_version="", task_generation_id="", job_type="reconcile"):
    now = datetime(2026, 7, 13, 12, 0, 0)
    return {
        "id": "job-1", "run_id": "labor-1", "job_type": job_type, "status": status, "attempt": 1, "max_attempts": 3,
        "worker_id": "device-a", "metadata_snapshot": {
            "ownerUserId": "user-1",
            "requiredWorkerVersion": required_version,
            "requiredWorkerVersionCode": _version_code(required_version),
            "taskGenerationId": task_generation_id,
            "progress": {},
        },
        "available_at": now, "lease_expires_at": now, "heartbeat_at": now,
        "created_at": now, "updated_at": now, "started_at": now, "finished_at": None,
        "error_code": None, "error_detail": None,
    }


def test_postgres_claim_is_owner_scoped_and_atomic():
    connection = FakeConnection([FakeResult(row=_row())])
    store = PostgresLaborWorkerStore("postgres://test", connect=lambda: connection)

    claimed = store.claim("user-1", "device-a", "0.2.5")

    sql, params = connection.queries[0]
    assert "for update skip locked" in sql.lower()
    assert "metadata_snapshot->>'ownerUserId'=%s" in sql
    assert params[0] == "user-1"
    assert params[1] == _version_code("0.2.5")
    assert claimed["ownerUserId"] == "user-1"
    assert connection.committed is True


def test_postgres_health_requires_existing_jobs_table():
    connection = FakeConnection([FakeResult(row={"table_name": None})])
    store = PostgresLaborWorkerStore("postgres://test", connect=lambda: connection)

    assert store.health() == {"backend": "postgres", "configured": True, "ready": False}


def test_postgres_latest_job_query_is_scoped_to_run_generation_type_and_status():
    connection = FakeConnection(
        [
            FakeResult(
                row=_row(
                    status="queued",
                    task_generation_id="generation-current",
                    job_type="mapping_preflight",
                )
            )
        ]
    )
    store = PostgresLaborWorkerStore("postgres://test", connect=lambda: connection)

    job = store.find_latest(
        "labor-1",
        task_generation_id="generation-current",
        job_type="mapping_preflight",
        statuses={"queued", "running", "retry_wait"},
    )

    sql, params = connection.queries[0]
    assert "run_id=%s" in sql
    assert "metadata_snapshot->>'taskGenerationId'" in sql
    assert "job_type=%s" in sql
    assert "status in" in sql
    assert "limit 1" in sql.lower()
    assert params[:3] == ("labor-1", "generation-current", "mapping_preflight")
    assert job["id"] == "job-1"


def test_postgres_job_store_health_never_returns_connection_secret():
    secret = "postgres://user:must-not-leak@example.invalid/database"

    def unavailable():
        raise RuntimeError(f"could not connect to {secret}")

    store = PostgresLaborWorkerStore(secret, connect=unavailable)

    health = store.health()

    assert health["ready"] is False
    assert health["errorType"] == "RuntimeError"
    assert "must-not-leak" not in str(health)


def test_postgres_job_store_disables_prepared_statements_for_transaction_pooler(monkeypatch):
    import psycopg

    captured = {}
    connection = object()

    def fake_connect(database_url, **kwargs):
        captured["database_url"] = database_url
        captured.update(kwargs)
        return connection

    monkeypatch.setattr(psycopg, "connect", fake_connect)

    store = PostgresLaborWorkerStore("postgres://pooler.example.invalid/database")

    assert store._connect() is connection
    assert captured["prepare_threshold"] is None


def test_version_code_orders_semver_numerically():
    assert _version_code("0.10.0") > _version_code("0.2.99")


def test_postgres_enqueue_recovers_concurrent_unique_index_race():
    class UniqueRace(Exception):
        sqlstate = "23505"

    queued = _row(status="queued", required_version="0.1.0")
    connection = FakeConnection([FakeResult(row=None), UniqueRace(), FakeResult(row=queued)])
    store = PostgresLaborWorkerStore("postgres://test", connect=lambda: connection)

    result = store.enqueue("labor-1", "user-1", "0.1.0", 3)

    assert result["id"] == "job-1"
    assert result["ownerUserId"] == "user-1"


@pytest.mark.parametrize("status", ["queued", "retry_wait"])
def test_postgres_enqueue_atomically_raises_required_version_for_waiting_job(status):
    existing = _row(status=status, required_version="0.1.0")
    upgraded = _row(status=status, required_version="0.3.0")
    connection = FakeConnection([FakeResult(row=existing), FakeResult(row=upgraded)])
    store = PostgresLaborWorkerStore("postgres://test", connect=lambda: connection)

    result = store.enqueue("labor-1", "user-1", "0.3.0", 3)

    select_sql, _ = connection.queries[0]
    update_sql, update_params = connection.queries[1]
    assert "for update" in select_sql.lower()
    assert "jsonb_set" in update_sql.lower()
    assert "status in ('queued','retry_wait')" in update_sql.lower()
    assert update_params == ("0.3.0", _version_code("0.3.0"), "job-1")
    assert result["requiredWorkerVersion"] == "0.3.0"
    assert connection.committed is True


def test_postgres_enqueue_does_not_silently_change_running_job_required_version():
    running = _row(status="running", required_version="0.1.0")
    connection = FakeConnection([FakeResult(row=running)])
    store = PostgresLaborWorkerStore("postgres://test", connect=lambda: connection)

    result = store.enqueue("labor-1", "user-1", "0.3.0", 3)

    assert result["status"] == "running"
    assert result["requiredWorkerVersion"] == "0.1.0"
    assert len(connection.queries) == 1
    assert "for update" in connection.queries[0][0].lower()
    assert connection.committed is True


def test_postgres_enqueue_persists_task_generation_in_jsonb_snapshot():
    inserted = _row(status="queued", task_generation_id="generation-current")
    connection = FakeConnection([FakeResult(row=None), FakeResult(row=inserted)])
    store = PostgresLaborWorkerStore("postgres://test", connect=lambda: connection)

    result = store.enqueue("labor-1", "user-1", "0.3.0", 3, "generation-current")

    insert_sql, insert_params = connection.queries[1]
    snapshot = json.loads(insert_params[-1])
    assert "metadata_snapshot" in insert_sql
    assert snapshot["taskGenerationId"] == "generation-current"
    assert result["taskGenerationId"] == "generation-current"


def test_postgres_mapping_preflight_job_persists_type_and_has_scoped_completion():
    inserted = _row(
        status="queued",
        task_generation_id="preflight-current",
        job_type="mapping_preflight",
    )
    connection = FakeConnection([FakeResult(row=None), FakeResult(row=inserted)])
    store = PostgresLaborWorkerStore("postgres://test", connect=lambda: connection)

    result = store.enqueue(
        "labor-1",
        "user-1",
        "0.3.0",
        3,
        "preflight-current",
        "mapping_preflight",
    )

    insert_sql, insert_params = connection.queries[1]
    assert "job_type" in insert_sql
    assert "mapping_preflight" in insert_params
    assert result["jobType"] == "mapping_preflight"

    running = _row(task_generation_id="preflight-current", job_type="mapping_preflight")
    completed = _row(
        status="succeeded",
        task_generation_id="preflight-current",
        job_type="mapping_preflight",
    )
    completion_connection = FakeConnection([FakeResult(row=running), FakeResult(row=completed)])
    completion_store = PostgresLaborWorkerStore("postgres://test", connect=lambda: completion_connection)
    completion_store.complete_preflight(
        "job-1",
        "user-1",
        "device-a",
        "preflight-current",
    )
    completion_sql, completion_params = completion_connection.queries[1]
    assert "job_type='mapping_preflight'" in completion_sql.replace(" ", "")
    assert "preflight-current" in completion_params


def test_postgres_enqueue_supersedes_different_active_generation_before_insert():
    old = _row(status="running", task_generation_id="generation-old")
    inserted = _row(status="queued", task_generation_id="generation-new")
    connection = FakeConnection([FakeResult(row=old), FakeResult(row=old), FakeResult(row=inserted)])
    store = PostgresLaborWorkerStore("postgres://test", connect=lambda: connection)

    result = store.enqueue("labor-1", "user-1", "0.3.0", 3, "generation-new")

    supersede_sql, supersede_params = connection.queries[1]
    assert "status='failed'" in supersede_sql.replace(" ", "")
    assert "TASK_GENERATION_SUPERSEDED" in supersede_params
    assert result["taskGenerationId"] == "generation-new"


def test_postgres_lease_updates_are_generation_scoped_and_complete_requires_result_marker():
    report_sha = "a" * 64
    input_fingerprint = "b" * 64
    row = _row(task_generation_id="generation-current")
    heartbeat_connection = FakeConnection([FakeResult(row=row)])
    heartbeat_store = PostgresLaborWorkerStore("postgres://test", connect=lambda: heartbeat_connection)

    heartbeat_store.heartbeat(
        "job-1", "user-1", "device-a", {}, "generation-current"
    )

    heartbeat_sql, heartbeat_params = heartbeat_connection.queries[0]
    assert "taskGenerationId" in heartbeat_sql
    assert "generation-current" in heartbeat_params

    complete_connection = FakeConnection([FakeResult(row=row), FakeResult(row=row)])
    complete_store = PostgresLaborWorkerStore("postgres://test", connect=lambda: complete_connection)
    complete_store.complete(
        "job-1",
        "user-1",
        "device-a",
        "generation-current",
        report_sha,
        6,
        input_fingerprint,
    )
    complete_sql, complete_params = complete_connection.queries[1]
    assert "resultAcceptedAt" in complete_sql
    assert "resultAcceptedGenerationId" in complete_sql
    assert complete_params.count("generation-current") >= 2
    assert report_sha in complete_params
    assert 6 in complete_params
    assert input_fingerprint in complete_params


def test_postgres_result_acceptance_marker_binds_evidence_and_can_be_revoked():
    accepted_row = _row(task_generation_id="generation-current")
    accepted_row["metadata_snapshot"].update(
        {
            "resultAcceptedAt": "2026-07-16T00:00:00Z",
            "resultAcceptedGenerationId": "generation-current",
            "resultAcceptedReportSha256": "a" * 64,
            "resultAcceptedReportSizeBytes": 6,
            "resultAcceptedInputFingerprint": "b" * 64,
        }
    )
    mark_connection = FakeConnection([FakeResult(row=accepted_row)])
    mark_store = PostgresLaborWorkerStore("postgres://test", connect=lambda: mark_connection)

    marked = mark_store.mark_result_accepted(
        "job-1",
        "user-1",
        "device-a",
        "generation-current",
        "a" * 64,
        6,
        "b" * 64,
    )

    mark_sql, mark_params = mark_connection.queries[0]
    marker_payload = json.loads(mark_params[0])
    assert "metadata_snapshot=metadata_snapshot ||" in mark_sql
    assert marker_payload["resultAcceptedReportSha256"] == "a" * 64
    assert marker_payload["resultAcceptedReportSizeBytes"] == 6
    assert marker_payload["resultAcceptedInputFingerprint"] == "b" * 64
    assert marked["resultAcceptedReportSizeBytes"] == 6

    cleared_row = _row(task_generation_id="generation-current")
    clear_connection = FakeConnection([FakeResult(row=cleared_row)])
    clear_store = PostgresLaborWorkerStore("postgres://test", connect=lambda: clear_connection)
    cleared = clear_store.clear_result_acceptance(
        "job-1", "user-1", "device-a", "generation-current"
    )
    clear_sql, _ = clear_connection.queries[0]
    assert "resultAcceptedReportSha256" in clear_sql
    assert "resultAcceptedReportSizeBytes" in clear_sql
    assert "resultAcceptedInputFingerprint" in clear_sql
    assert cleared["resultAcceptedAt"] == ""


def test_expired_postgres_lease_is_reclaimed_and_old_device_cannot_finish():
    generation = "generation-current"
    report_sha = "a" * 64
    input_fingerprint = "b" * 64
    reclaimed = _row(task_generation_id=generation)
    reclaimed["attempt"] = 2
    reclaimed["worker_id"] = "device-new"
    reclaimed["metadata_snapshot"] = {
        **reclaimed["metadata_snapshot"],
        "resultAcceptedAt": "2026-07-16T00:00:00Z",
        "resultAcceptedGenerationId": generation,
        "resultAcceptedReportSha256": report_sha,
        "resultAcceptedReportSizeBytes": 6,
        "resultAcceptedInputFingerprint": input_fingerprint,
    }

    claim_connection = FakeConnection([FakeResult(row=reclaimed)])
    claimed = PostgresLaborWorkerStore(
        "postgres://test",
        connect=lambda: claim_connection,
    ).claim("user-1", "device-new", "0.3.1")

    claim_sql, claim_params = claim_connection.queries[0]
    normalized_claim = " ".join(claim_sql.lower().split())
    assert "status='running' and (lease_expires_at is null or lease_expires_at <= now())" in normalized_claim
    assert "attempt=job.attempt+1" in normalized_claim
    assert claim_params[2] == "device-new"
    assert claimed["attempt"] == 2
    assert claimed["claimedDeviceId"] == "device-new"

    stale_connection = FakeConnection(
        [FakeResult(row=reclaimed), FakeResult(row=None)]
    )
    stale_store = PostgresLaborWorkerStore(
        "postgres://test",
        connect=lambda: stale_connection,
    )
    with pytest.raises(PermissionError, match="租约已经失效"):
        stale_store.complete(
            "job-1",
            "user-1",
            "device-old",
            generation,
            report_sha,
            6,
            input_fingerprint,
        )

    stale_update_sql, stale_update_params = stale_connection.queries[1]
    assert "worker_id=%s" in stale_update_sql
    assert "lease_expires_at > now()" in stale_update_sql
    assert stale_update_params[1] == "device-old"

    completed = {**reclaimed, "status": "succeeded"}
    current_connection = FakeConnection(
        [FakeResult(row=reclaimed), FakeResult(row=completed)]
    )
    current_store = PostgresLaborWorkerStore(
        "postgres://test",
        connect=lambda: current_connection,
    )
    result = current_store.complete(
        "job-1",
        "user-1",
        "device-new",
        generation,
        report_sha,
        6,
        input_fingerprint,
    )

    assert result["status"] == "succeeded"
    assert result["claimedDeviceId"] == "device-new"
