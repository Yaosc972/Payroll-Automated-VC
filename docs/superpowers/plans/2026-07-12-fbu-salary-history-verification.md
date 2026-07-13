# FBU Salary History Verification Implementation Plan

> **For agentic workers:** Execute inline with test-driven development. Do not commit unless the user explicitly requests it.

**Goal:** Replace the single FBU salary upload with mandatory previous-month salary, current-month salary, and full adjustment-flow uploads, then calculate effective hourly rates and performance ratios by adjustment effective date.

**Architecture:** Add a parser-level salary-history reconciliation service that compares normalized snapshots, matches completed OEHR adjustment events, and emits resolved date segments plus blocking issues. Persist the three source previews and reconciliation result on each FBU run. Keep attendance, supplemental leave, performance, and result export steps in their current positions.

**Tech Stack:** FastAPI, dataclasses/JSON run store, openpyxl-based existing parsers, static HTML/JavaScript, pytest.

## Global Constraints

- Both hourly rate and performance ratio follow the calculation month and adjustment effective date.
- Effective date on or before month start uses new values for the full month.
- Effective date after month end uses old values for the full month.
- Effective date inside the month splits attendance-derived performance base by date.
- Ratio changes from zero to positive follow the same split rule.
- Changed values without a matching completed adjustment event are blocking pending confirmations.
- New hires absent from the previous snapshot may use the current snapshot when roster hire date explains the absence.
- Existing historical runs remain readable.
- No changes to attendance, supplemental leave, or performance step placement.

### Task 1: Salary-history reconciliation domain

**Files:**
- Modify: `bonus_platform/engine/fbu_performance/parser.py`
- Test: `tests/test_fbu_salary_history.py`

- [ ] Add failing tests for unchanged snapshots, future-effective changes, in-month splits, zero-to-positive ratios, new hires, and unmatched changes.
- [ ] Implement `reconcile_salary_history(...)` returning employee rows, effective segments, summary counts, and blocking issues.
- [ ] Verify focused tests.

### Task 2: Calculation integration and persistence

**Files:**
- Modify: `bonus_platform/engine/fbu_performance/runs.py`
- Modify: `bonus_platform/app.py`
- Modify: `bonus_platform/engine/fbu_performance/parser.py`
- Test: `tests/test_fbu_performance_api.py`

- [ ] Add backward-compatible run fields for previous/current salary data and salary verification.
- [ ] Replace the salary import endpoint with a three-file multipart import while preserving the legacy endpoint for saved runs.
- [ ] Feed resolved salary values and date segments into calculation.
- [ ] Block calculation when salary verification has unresolved blocking issues.
- [ ] Verify API and calculation tests.

### Task 3: Salary step UI

**Files:**
- Modify: `bonus_platform/static/fbu-performance.html`
- Modify: `bonus_platform/static/fbu-performance.js`
- Test: `tests/test_fbu_activity_workflow_static.py`
- Test: `tests/test_fbu_workbench_static.py`

- [ ] Add three required upload controls in the existing salary step.
- [ ] Render summary counts and a salary-change review table with effective segments and blocking states.
- [ ] Invalidate downstream results when any of the three files is replaced.
- [ ] Preserve existing navigation and no-scroll save behavior.
- [ ] Verify static tests and browser flow.

### Task 4: Real-data E2E validation

**Files:**
- Modify: `tools/fbu_real_e2e.py` only where necessary for the three-file salary flow.

- [ ] Replay April with the available adjacent salary snapshots and full adjustment flow.
- [ ] Replay May with April/May salary snapshots and full adjustment flow.
- [ ] Compare employee counts, totals, and row-level differences against offline workbooks.
- [ ] Verify `zt0021990` splits from 2026-04-26 and `zt0020155` uses hourly 18 and ratio 5% for May.
- [ ] Run full FBU targeted tests and browser/API E2E.
