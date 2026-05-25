# Monthly-Only Calculation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove history workbook handling from the first-release monthly calculation flow.

**Architecture:** Keep the current rule calculator and confirmation finalization flow. Narrow the product boundary at the UI and API layers so `/api/calculate` reads only the uploaded monthly workbook and frontend copy no longer presents historical upload as part of the flow.

**Tech Stack:** FastAPI, static HTML/CSS/JavaScript, pytest.

---

### Task 1: Lock Product Boundary With Tests

**Files:**
- Modify: `tests/test_static_branding.py`
- Create: `tests/test_monthly_only_calculation.py`

- [ ] Add static assertions that `index.html` and `app.js` contain no history upload IDs, labels, or `history_file` form append.
- [ ] Add an API test that posts a monthly workbook plus an extra history file and proves the response equals current-rule calculation behavior for the monthly workbook.
- [ ] Run the new tests and confirm they fail while history handling is still present.

### Task 2: Remove History Upload From Frontend

**Files:**
- Modify: `bonus_platform/static/index.html`
- Modify: `bonus_platform/static/app.js`
- Modify: `bonus_platform/static/styles.css`

- [ ] Update copy to describe monthly HR data only.
- [ ] Remove the history file picker and JavaScript bindings.
- [ ] Rebalance the upload row for one file picker plus calculate button.
- [ ] Run static tests.

### Task 3: Remove History Handling From API Main Flow

**Files:**
- Modify: `bonus_platform/app.py`
- Modify: `bonus_platform/README.md`

- [ ] Remove `history_file` endpoint input, validation, temporary file lifecycle, and history response metadata.
- [ ] Update README first-release scope and usage instructions.
- [ ] Run API tests and existing calculator tests.

### Task 4: Verify Locally

**Files:**
- Verify: `bonus_platform/static/index.html`

- [ ] Open the served page in the in-app browser and inspect the upload panel.
- [ ] Run the full targeted test suite.
- [ ] Report the narrowed flow and verification evidence.
