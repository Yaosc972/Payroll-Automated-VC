# 西格玛工作台桌面单机版 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package the current FastAPI bonus workbench as a Windows/macOS local desktop app while preserving deterministic Excel calculation behavior.

**Architecture:** Keep the existing FastAPI backend and static frontend. Add a local data directory abstraction, a SQLite run index, and an Electron shell that starts/stops the backend and opens the workbench window.

**Tech Stack:** Python, FastAPI, openpyxl, SQLite stdlib, Electron, Node.js, pytest.

---

## File Structure

- Modify `bonus_platform/config.py`: centralize data directory paths and support `SIGMA_WORKBENCH_HOME`.
- Create `bonus_platform/engine/local_store.py`: initialize SQLite and upsert/list run metadata.
- Modify `bonus_platform/engine/runs.py`: write batch metadata to SQLite while keeping `metadata.json`.
- Modify `bonus_platform/app.py`: add a desktop-friendly health payload and keep API compatibility.
- Create `desktop/package.json`: Electron app metadata and scripts.
- Create `desktop/main.js`: Electron main process that starts FastAPI and loads the local URL.
- Create `desktop/preload.js`: minimal isolated preload bridge placeholder.
- Create `tests/test_local_store.py`: test local data directory and SQLite indexing.
- Modify `tests/test_run_workbench_api.py`: assert run list remains API-compatible after SQLite index addition.
- Modify `README.md` and `bonus_platform/README.md`: document desktop single-user mode.

## Task 1: Local Data Directory

**Files:**
- Modify: `bonus_platform/config.py`
- Test: `tests/test_local_store.py`

- [ ] Step 1: Write tests for environment-controlled data root.
- [ ] Step 2: Implement `SIGMA_WORKBENCH_HOME` support.
- [ ] Step 3: Run `python3 -m pytest tests/test_local_store.py -q`.

## Task 2: SQLite Run Index

**Files:**
- Create: `bonus_platform/engine/local_store.py`
- Modify: `bonus_platform/engine/runs.py`
- Test: `tests/test_local_store.py`

- [ ] Step 1: Write a test that saves metadata and verifies a SQLite row exists.
- [ ] Step 2: Implement `init_store()`, `upsert_run_metadata()`, and `list_indexed_runs()`.
- [ ] Step 3: Call `upsert_run_metadata()` from `save_metadata()`.
- [ ] Step 4: Keep JSON fallback in `list_run_metadata()`.
- [ ] Step 5: Run `python3 -m pytest tests/test_local_store.py tests/test_run_workbench_api.py -q`.

## Task 3: Electron Shell

**Files:**
- Create: `desktop/package.json`
- Create: `desktop/main.js`
- Create: `desktop/preload.js`

- [ ] Step 1: Add Electron package metadata and npm scripts.
- [ ] Step 2: Implement main process backend startup with `python3 -m uvicorn bonus_platform.app:app`.
- [ ] Step 3: Set `SIGMA_WORKBENCH_HOME` before spawning backend.
- [ ] Step 4: Stop backend process on window close and app quit.
- [ ] Step 5: Add a local startup timeout and error window.

## Task 4: Documentation

**Files:**
- Modify: `README.md`
- Modify: `bonus_platform/README.md`

- [ ] Step 1: Document web development mode.
- [ ] Step 2: Document desktop single-user data storage.
- [ ] Step 3: Document packaging constraints and first-run behavior.

## Task 5: Verification

**Files:**
- No production files.

- [ ] Step 1: Run `python3 -m pytest -q`.
- [ ] Step 2: Run JS syntax checks for `desktop/main.js` and `desktop/preload.js`.
- [ ] Step 3: Confirm existing API tests still pass.

## Self-Review

- Spec coverage: local data directory, SQLite index, Electron shell, docs, and tests are covered.
- Placeholder scan: no TBD/TODO implementation placeholders remain in this plan.
- Scope check: cloud deployment, user permissions, auto-update, and code signing are intentionally outside first version.
