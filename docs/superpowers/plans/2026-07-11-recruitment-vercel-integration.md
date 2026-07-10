# Recruitment Bonus Vercel Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote the completed recruitment-bonus changes into the dedicated Vercel integration branch without changing the behavior or release state of other modules.

**Architecture:** Treat `codex/admin-module-release-consolidation-vercel` as the release source of truth. Cherry-pick only the two recruitment-owned commits from `codex/recruitment-bonus-workbench`, then verify shared contracts and deploy a preview before production.

**Tech Stack:** Git, Python 3, FastAPI, openpyxl, pytest, Vercel CLI.

## Global Constraints

- Keep `codex/admin-module-release-consolidation-vercel` as the Vercel production integration branch.
- Integrate only `3528fde` and `be0eb78`; do not merge the recruitment branch wholesale.
- Preserve `bonus_platform/app.py`, `bonus_platform/static/index.html`, `bonus_platform/static/permission-guard.js`, `bonus_platform/static/release-info.json`, and `vercel.json` unless an explicit reviewed dependency requires a change.
- Keep FBU and domestic labor closed; keep China employee payroll and overseas labor release states unchanged.
- Do not push the branch unless the user explicitly asks.

---

### Task 1: Selectively integrate recruitment commits

**Files:**
- Modify: `bonus_platform/engine/calculator.py`
- Modify: `bonus_platform/engine/models.py`
- Modify: `bonus_platform/engine/workbook_io.py`
- Create: `bonus_platform/engine/recruitment_import_validation.py`
- Create: `scripts/validate_recruitment_import_sources.py`
- Modify: `tests/test_monthly_only_calculation.py`
- Modify: `tests/test_pending_workbook.py`
- Create: `tests/test_recruitment_import_validation.py`

**Interfaces:**
- Consumes: recruitment commits `3528fde` and `be0eb78`.
- Produces: date-safe month detection, recruitment import validation, and role-specific last-work-date fields in pending confirmation workbooks.

- [ ] **Step 1: Cherry-pick the recruitment validation commit**

Run: `git cherry-pick 3528fde`

Expected: clean cherry-pick with no changes to shared release files.

- [ ] **Step 2: Cherry-pick the pending-review commit**

Run: `git cherry-pick be0eb78`

Expected: clean cherry-pick with changes limited to recruitment engine and tests.

- [ ] **Step 3: Verify the resulting file boundary**

Run: `git diff --name-status 3a8bb0b..HEAD`

Expected: only the files listed in this task plus this plan document.

### Task 2: Verify recruitment behavior and shared module safety

**Files:**
- Test: `tests/test_monthly_only_calculation.py`
- Test: `tests/test_pending_workbook.py`
- Test: `tests/test_recruitment_import_validation.py`
- Test: `tests/test_run_workbench_api.py`
- Test: `tests/test_admin_permissions_api.py`
- Test: `tests/test_static_branding.py`

**Interfaces:**
- Consumes: integrated recruitment engine changes.
- Produces: evidence that recruitment calculations, pending confirmations, APIs, permissions, and shared static pages remain valid.

- [ ] **Step 1: Run recruitment-focused tests**

Run: `python3 -m pytest tests/test_monthly_only_calculation.py tests/test_pending_workbook.py tests/test_recruitment_import_validation.py tests/test_run_workbench_api.py`

Expected: all tests pass.

- [ ] **Step 2: Run shared permission and static tests**

Run: `python3 -m pytest tests/test_admin_permissions_api.py tests/test_static_branding.py`

Expected: all tests pass.

- [ ] **Step 3: Run the complete suite**

Run: `python3 -m pytest`

Expected: all runnable tests pass; any environment-dependent skips are reported.

- [ ] **Step 4: Verify release metadata and protected files**

Run: `git diff 3a8bb0b..HEAD -- bonus_platform/app.py bonus_platform/static/index.html bonus_platform/static/permission-guard.js bonus_platform/static/release-info.json vercel.json`

Expected: no output.

### Task 3: Preview and production deployment

**Files:**
- Verify: `.vercel/project.json`
- Verify: `bonus_platform/static/release-info.json`

**Interfaces:**
- Consumes: fully tested Vercel integration branch.
- Produces: a verified preview deployment followed by the production alias `https://sigma-workbench.vercel.app`.

- [ ] **Step 1: Confirm Vercel project linkage and authentication**

Run: `vercel whoami` and inspect `.vercel/project.json`.

Expected: linked project `sigma-workbench` in scope `yaosc-s-project`.

- [ ] **Step 2: Create a preview deployment**

Run: `vercel deploy -y --no-wait --scope yaosc-s-project`

Expected: a preview URL is returned.

- [ ] **Step 3: Inspect preview readiness**

Run: `vercel inspect <preview-url> --scope yaosc-s-project`

Expected: deployment status is `Ready`.

- [ ] **Step 4: Verify preview endpoints**

Check the home page, recruitment module, admin module, China employee payroll permission flow, and overseas labor UAT entry. Confirm FBU and domestic labor remain closed.

- [ ] **Step 5: Deploy production**

Run: `vercel deploy --prod -y --no-wait --scope yaosc-s-project`

Expected: a production deployment URL is returned.

- [ ] **Step 6: Confirm the production alias**

Run: `vercel inspect https://sigma-workbench.vercel.app --scope yaosc-s-project`

Expected: status `Ready` and alias `https://sigma-workbench.vercel.app` points at the new deployment.
