from datetime import datetime, timedelta, timezone
import hashlib

import pytest

import bonus_platform.engine.labor.worker_jobs as jobs
from bonus_platform.engine.labor.worker_version import parse_stable_worker_version


@pytest.fixture()
def job_store(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "LABOR_WORKER_JOBS_DIR", tmp_path / "jobs")
    return tmp_path / "jobs"


def test_worker_claims_only_own_job_and_claim_is_exclusive(job_store):
    other = jobs.enqueue_labor_worker_job("labor_other", owner_user_id="user-2")
    own = jobs.enqueue_labor_worker_job("labor_own", owner_user_id="user-1")

    claimed = jobs.claim_labor_worker_job(owner_user_id="user-1", device_id="device-a")

    assert claimed["id"] == own["id"]
    assert claimed["ownerUserId"] == "user-1"
    assert claimed["claimedDeviceId"] == "device-a"
    assert jobs.claim_labor_worker_job(owner_user_id="user-1", device_id="device-b") is None
    assert jobs.get_labor_worker_job(other["id"])["status"] == "queued"


def test_expired_lease_can_be_reclaimed_by_same_owner(job_store, monkeypatch):
    job = jobs.enqueue_labor_worker_job("labor_run", owner_user_id="user-1")
    first = jobs.claim_labor_worker_job(owner_user_id="user-1", device_id="device-a")
    expired = dict(first)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    expired["leaseExpiresAt"] = (now - timedelta(seconds=1)).isoformat(timespec="seconds") + "Z"
    jobs._write_labor_worker_job(expired)

    reclaimed = jobs.claim_labor_worker_job(owner_user_id="user-1", device_id="device-b")

    assert reclaimed["id"] == job["id"]
    assert reclaimed["claimedDeviceId"] == "device-b"
    assert reclaimed["attempt"] == 2


def test_lease_holder_required_for_heartbeat_and_completion(job_store):
    job = jobs.enqueue_labor_worker_job("labor_run", owner_user_id="user-1")
    jobs.claim_labor_worker_job(owner_user_id="user-1", device_id="device-a")

    with pytest.raises(jobs.LaborWorkerLeaseError):
        jobs.heartbeat_labor_worker_job(job["id"], owner_user_id="user-1", device_id="device-b")
    with pytest.raises(jobs.LaborWorkerLeaseError):
        jobs.complete_labor_worker_job(job["id"], owner_user_id="user-2", device_id="device-a")

    report_sha = hashlib.sha256(b"report").hexdigest()
    input_fingerprint = hashlib.sha256(b"inputs").hexdigest()
    jobs.mark_labor_worker_result_accepted(
        job["id"],
        owner_user_id="user-1",
        device_id="device-a",
        result_report_sha256=report_sha,
        result_report_size_bytes=len(b"report"),
        result_input_fingerprint=input_fingerprint,
    )
    completed = jobs.complete_labor_worker_job(
        job["id"],
        owner_user_id="user-1",
        device_id="device-a",
        expected_result_report_sha256=report_sha,
        expected_result_report_size_bytes=len(b"report"),
        expected_result_input_fingerprint=input_fingerprint,
    )
    assert completed["status"] == "succeeded"
    assert jobs.complete_labor_worker_job(
        job["id"],
        owner_user_id="user-1",
        device_id="device-a",
        expected_result_report_sha256=report_sha,
        expected_result_report_size_bytes=len(b"report"),
        expected_result_input_fingerprint=input_fingerprint,
    )["status"] == "succeeded"


def test_retryable_failure_returns_job_to_queue(job_store):
    job = jobs.enqueue_labor_worker_job("labor_run", owner_user_id="user-1", max_attempts=2)
    jobs.claim_labor_worker_job(owner_user_id="user-1", device_id="device-a")

    retry = jobs.fail_labor_worker_job(
        job["id"],
        owner_user_id="user-1",
        device_id="device-a",
        error_code="OCR_TIMEOUT",
        error_message="timeout",
        retryable=True,
        retry_delay_seconds=0,
    )
    assert retry["status"] == "retry_wait"

    jobs.claim_labor_worker_job(owner_user_id="user-1", device_id="device-a")
    failed = jobs.fail_labor_worker_job(
        job["id"],
        owner_user_id="user-1",
        device_id="device-a",
        error_code="OCR_TIMEOUT",
        error_message="timeout",
        retryable=True,
    )
    assert failed["status"] == "failed"


def test_new_generation_supersedes_active_job_instead_of_reusing_it(job_store):
    old = jobs.enqueue_labor_worker_job(
        "labor_run",
        owner_user_id="user-1",
        task_generation_id="generation-old",
    )

    new = jobs.enqueue_labor_worker_job(
        "labor_run",
        owner_user_id="user-1",
        task_generation_id="generation-new",
    )

    assert new["id"] != old["id"]
    assert new["taskGenerationId"] == "generation-new"
    superseded = jobs.get_labor_worker_job(old["id"])
    assert superseded["status"] == "failed"
    assert superseded["errorCode"] == "TASK_GENERATION_SUPERSEDED"


def test_empty_generation_cannot_reuse_generation_bound_active_job(job_store):
    jobs.enqueue_labor_worker_job(
        "labor_run",
        owner_user_id="user-1",
        task_generation_id="generation-current",
    )

    with pytest.raises(jobs.LaborWorkerLeaseError):
        jobs.enqueue_labor_worker_job("labor_run", owner_user_id="user-1")


def test_generation_is_required_for_lease_mutations_and_completion_requires_accepted_result(job_store):
    job = jobs.enqueue_labor_worker_job(
        "labor_run",
        owner_user_id="user-1",
        task_generation_id="generation-current",
    )
    jobs.claim_labor_worker_job(owner_user_id="user-1", device_id="device-a")

    with pytest.raises(jobs.LaborWorkerLeaseError):
        jobs.heartbeat_labor_worker_job(
            job["id"],
            owner_user_id="user-1",
            device_id="device-a",
            expected_task_generation_id="generation-stale",
        )
    with pytest.raises(jobs.LaborWorkerLeaseError):
        jobs.complete_labor_worker_job(
            job["id"],
            owner_user_id="user-1",
            device_id="device-a",
            expected_task_generation_id="generation-current",
        )

    accepted = jobs.mark_labor_worker_result_accepted(
        job["id"],
        owner_user_id="user-1",
        device_id="device-a",
        expected_task_generation_id="generation-current",
        result_report_sha256=hashlib.sha256(b"report").hexdigest(),
        result_report_size_bytes=len(b"report"),
        result_input_fingerprint=hashlib.sha256(b"inputs").hexdigest(),
    )
    assert accepted["resultAcceptedGenerationId"] == "generation-current"
    completed = jobs.complete_labor_worker_job(
        job["id"],
        owner_user_id="user-1",
        device_id="device-a",
        expected_task_generation_id="generation-current",
        expected_result_report_sha256=hashlib.sha256(b"report").hexdigest(),
        expected_result_report_size_bytes=len(b"report"),
        expected_result_input_fingerprint=hashlib.sha256(b"inputs").hexdigest(),
    )
    assert completed["status"] == "succeeded"


def test_mapping_preflight_job_is_typed_and_completes_without_reconcile_report(job_store):
    job = jobs.enqueue_labor_worker_job(
        "labor_run",
        owner_user_id="user-1",
        task_generation_id="preflight-current",
        job_type="mapping_preflight",
    )
    claimed = jobs.claim_labor_worker_job(owner_user_id="user-1", device_id="device-a")

    assert job["jobType"] == "mapping_preflight"
    assert claimed["jobType"] == "mapping_preflight"
    completed = jobs.complete_labor_worker_preflight_job(
        job["id"],
        owner_user_id="user-1",
        device_id="device-a",
        expected_task_generation_id="preflight-current",
    )
    assert completed["status"] == "succeeded"


def test_reconcile_job_cannot_use_preflight_completion(job_store):
    job = jobs.enqueue_labor_worker_job(
        "labor_run",
        owner_user_id="user-1",
        task_generation_id="generation-current",
    )
    jobs.claim_labor_worker_job(owner_user_id="user-1", device_id="device-a")

    with pytest.raises(jobs.LaborWorkerLeaseError):
        jobs.complete_labor_worker_preflight_job(
            job["id"],
            owner_user_id="user-1",
            device_id="device-a",
            expected_task_generation_id="generation-current",
        )


def test_overseas_payroll_job_uses_typed_auxiliary_completion(job_store):
    job = jobs.enqueue_labor_worker_job(
        "payroll-task",
        owner_user_id="user-1",
        task_generation_id="payroll-task",
        job_type="overseas_payroll",
    )
    claimed = jobs.claim_labor_worker_job(owner_user_id="user-1", device_id="device-a", worker_version="0.3.15")

    assert claimed["jobType"] == "overseas_payroll"
    completed = jobs.complete_labor_worker_auxiliary_job(
        job["id"],
        owner_user_id="user-1",
        device_id="device-a",
        job_type="overseas_payroll",
        expected_task_generation_id="payroll-task",
    )
    assert completed["status"] == "succeeded"

    with pytest.raises(jobs.LaborWorkerLeaseError):
        jobs.complete_labor_worker_auxiliary_job(
            job["id"],
            owner_user_id="user-1",
            device_id="device-a",
            job_type="reconcile",
            expected_task_generation_id="payroll-task",
        )


@pytest.mark.parametrize("value", ["0.3", "0.3.0-beta", "v0.3.0", "999999.0.0", ""])
def test_worker_version_parser_rejects_ambiguous_or_unbounded_versions(value):
    with pytest.raises(ValueError):
        parse_stable_worker_version(value)


def test_worker_version_parser_accepts_bounded_three_part_release():
    assert parse_stable_worker_version("0.3.0") == (0, 3, 0)
def test_p1_postgres_queue_reuses_authoritative_state_database_by_default(monkeypatch):
    monkeypatch.setenv("SIGMA_LABOR_JOB_BACKEND", "postgres")
    monkeypatch.setenv("SIGMA_LABOR_DATABASE_URL", "postgres://shared-authority")
    monkeypatch.delenv("SIGMA_LABOR_JOB_DATABASE_URL", raising=False)
    monkeypatch.delenv("LABOR_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("ADMIN_DATABASE_URL", raising=False)

    store = jobs._postgres_store()

    assert store is not None
    assert store.database_url == "postgres://shared-authority"
