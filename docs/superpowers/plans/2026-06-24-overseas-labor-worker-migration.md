# Overseas Labor Worker Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move overseas labor reconciliation off Vercel background execution and into a durable worker-oriented job flow.

**Architecture:** Vercel remains the control plane for short API requests: create run, sign uploads, register files, confirm mapping, enqueue reconciliation, and poll status. A Worker process owns the data plane: claim a job, restore/download inputs, run the existing reconciliation code, upload reports, and update run/job status. Phase 1 keeps the existing run metadata storage as the compatibility bridge and adds a local JSON job store plus SQL schema for the Supabase/Postgres target.

**Tech Stack:** FastAPI, Python, Supabase Storage, Postgres schema migration, existing `bonus_platform.engine.labor` reconciliation engine, pytest.

## Global Constraints

- Do not modify unrelated business modules.
- Do not run long PDF/Excel reconciliation in Vercel request background threads when worker mode is enabled.
- Keep local development path working without requiring Supabase/Postgres.
- Preserve existing upload, mapping, and report-generation engine code.
- Add tests before production code.
- Do not push unless explicitly requested.

---

### Task 1: Add Worker Job Model and Store

**Files:**
- Create: `bonus_platform/engine/labor/jobs.py`
- Test: `tests/test_labor_engine.py`

**Interfaces:**
- Produces: `labor_worker_jobs_enabled() -> bool`
- Produces: `enqueue_labor_reconciliation_job(run_id: str, metadata: dict | None = None) -> dict`
- Produces: `claim_next_labor_job(worker_id: str) -> dict | None`
- Produces: `complete_labor_job(job_id: str, updates: dict | None = None) -> dict`
- Produces: `fail_labor_job(job_id: str, message: str, *, retryable: bool = False, error_code: str = "LABOR_JOB_FAILED") -> dict`

- [x] **Step 1: Write failing tests**

```python
def test_enqueue_labor_reconciliation_job_creates_queued_job(monkeypatch, tmp_path):
    monkeypatch.setattr(labor_jobs, "LABOR_JOBS_DIR", tmp_path / "labor_jobs")
    job = labor_jobs.enqueue_labor_reconciliation_job("labor_demo", {"supplierName": "OSI"})
    assert job["runId"] == "labor_demo"
    assert job["status"] == "queued"
    assert job["jobType"] == "reconcile"
    assert job["attempt"] == 0

def test_claim_next_labor_job_marks_running(monkeypatch, tmp_path):
    monkeypatch.setattr(labor_jobs, "LABOR_JOBS_DIR", tmp_path / "labor_jobs")
    created = labor_jobs.enqueue_labor_reconciliation_job("labor_demo", {})
    claimed = labor_jobs.claim_next_labor_job("worker-1")
    assert claimed["id"] == created["id"]
    assert claimed["status"] == "running"
    assert claimed["workerId"] == "worker-1"
    assert claimed["attempt"] == 1
```

- [x] **Step 2: Verify tests fail**

Run: `python3 -m pytest tests/test_labor_engine.py::test_enqueue_labor_reconciliation_job_creates_queued_job tests/test_labor_engine.py::test_claim_next_labor_job_marks_running`

Expected: FAIL because `bonus_platform.engine.labor.jobs` does not exist.

- [x] **Step 3: Implement local JSON job store**

Create a small atomic JSON store under `outputs/labor_jobs` by default. Use deterministic JSON fields compatible with later Postgres rows: `id`, `runId`, `jobType`, `status`, `attempt`, `maxAttempts`, `workerId`, `createdAt`, `updatedAt`, `startedAt`, `finishedAt`, `errorCode`, `errorDetail`, `retryable`.

- [x] **Step 4: Verify tests pass**

Run the targeted tests, then run `python3 -m pytest tests/test_labor_engine.py`.

### Task 2: Change Extract API to Enqueue in Worker Mode

**Files:**
- Modify: `bonus_platform/app.py`
- Test: `tests/test_labor_api.py`

**Interfaces:**
- Consumes: `labor_worker_jobs_enabled()`
- Consumes: `enqueue_labor_reconciliation_job(run_id, metadata)`
- Produces: `POST /api/labor/runs/{run_id}/extract-and-compare` returns `202 Accepted` in worker mode with `asyncTask.jobId`.

- [x] **Step 1: Write failing API test**

```python
def test_labor_extract_endpoint_enqueues_worker_job_in_worker_mode(monkeypatch):
    monkeypatch.setenv("SIGMA_LABOR_EXECUTION_MODE", "worker")
    monkeypatch.setenv("SIGMA_OVERSEAS_LABOR_ACCESS", "production")
    monkeypatch.setattr(app_module, "_run_labor_extract_compare", lambda run_id: (_ for _ in ()).throw(AssertionError("inline worker must not run")))
    monkeypatch.setattr(asyncio.get_event_loop(), "run_in_executor", lambda *args: (_ for _ in ()).throw(AssertionError("Vercel executor must not run")))
    ...
    response = client.post(f"/api/labor/runs/{run['id']}/extract-and-compare")
    assert response.status_code == 202
    assert response.json()["asyncTask"]["jobId"]
```

- [x] **Step 2: Verify test fails**

Run: `python3 -m pytest tests/test_labor_api.py::test_labor_extract_endpoint_enqueues_worker_job_in_worker_mode`

Expected: FAIL because endpoint still uses `run_in_executor`.

- [x] **Step 3: Implement API branch**

After file and mapping validation, if worker mode is enabled, create a labor job, update metadata to `抽取中` with `asyncTask.status = queued`, `asyncTask.jobId = job["id"]`, and return `JSONResponse(status_code=202, content=queued)`.

- [x] **Step 4: Verify local legacy path still works**

Run the existing inline tests around `extract-and-compare` and ensure they still pass when `SIGMA_LABOR_EXECUTION_MODE` is not set.

### Task 3: Add Worker Entrypoint

**Files:**
- Create: `bonus_platform/worker/__init__.py`
- Create: `bonus_platform/worker/labor.py`
- Create: `bonus_platform/worker/main.py`
- Test: `tests/test_labor_engine.py`

**Interfaces:**
- Produces: `process_one_labor_job(worker_id: str | None = None) -> dict | None`
- Produces command: `python -m bonus_platform.worker.main --once`

- [x] **Step 1: Write failing Worker test**

```python
def test_worker_processes_claimed_labor_job(monkeypatch, tmp_path):
    monkeypatch.setattr(labor_jobs, "LABOR_JOBS_DIR", tmp_path / "labor_jobs")
    labor_jobs.enqueue_labor_reconciliation_job("labor_demo", {})
    processed = {}
    monkeypatch.setattr(labor_worker, "_run_labor_extract_compare", lambda run_id: processed.setdefault("runId", run_id))
    result = labor_worker.process_one_labor_job(worker_id="worker-test")
    assert result["status"] == "succeeded"
    assert processed["runId"] == "labor_demo"
```

- [x] **Step 2: Verify test fails**

Run: `python3 -m pytest tests/test_labor_engine.py::test_worker_processes_claimed_labor_job`

Expected: FAIL because Worker module does not exist.

- [x] **Step 3: Implement Worker**

`process_one_labor_job` claims one queued job, calls the existing reconciliation function, marks the job succeeded, and marks transient failures through `fail_labor_job`.

- [x] **Step 4: Verify test passes**

Run targeted Worker tests.

### Task 4: Add Supabase/Postgres Schema for the Target Architecture

**Files:**
- Create: `supabase/migrations/20260624_labor_worker_schema.sql`
- Test: `tests/test_labor_engine.py`

**Interfaces:**
- Produces SQL tables: `labor_runs`, `labor_files`, `labor_jobs`, `labor_job_attempts`.

- [x] **Step 1: Write schema presence test**

```python
def test_labor_worker_schema_declares_required_tables():
    sql = Path("supabase/migrations/20260624_labor_worker_schema.sql").read_text(encoding="utf-8")
    for table in ("labor_runs", "labor_files", "labor_jobs", "labor_job_attempts"):
        assert f"create table if not exists {table}" in sql
```

- [x] **Step 2: Verify test fails**

Run: `python3 -m pytest tests/test_labor_engine.py::test_labor_worker_schema_declares_required_tables`

Expected: FAIL because migration file does not exist.

- [x] **Step 3: Add schema**

Add the four tables, indexes for active jobs, and timestamps. Keep it additive; do not modify existing admin tables.

- [x] **Step 4: Verify full suite**

Run: `python3 -m pytest`.
