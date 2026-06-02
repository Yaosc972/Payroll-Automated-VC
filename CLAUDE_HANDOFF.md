# Claude Handoff

This document is the handoff brief for Claude Code or any other coding agent taking over the Sigma Workbench repository.

Use this document as the operational source of truth before making changes.

## Repository

- Repo: `Payroll-Automated-VC`
- Local workspace root: `/Users/zt27532/Documents/New project 2`
- Current branch: `claude/handoff-01`
- Local state at handoff: this branch is ahead of `origin/claude/handoff-01`; check `git status --short --branch` before editing.

When taking over, create a fresh working branch from the latest agreed branch if you are doing new work. Do not overwrite uncommitted user or agent changes.

## Product Scope

Sigma Workbench has three project areas:

1. Recruitment bonus calculation
2. Overseas labor invoice reconciliation
3. Domestic labor worker payroll calculation

The current priority is **overseas labor invoice reconciliation**.

Do not confuse overseas labor invoice reconciliation with domestic labor worker payroll calculation. Domestic labor worker payroll is a separate project area and should keep separate design, naming, and code boundaries.

## Current Priority: Overseas Labor Invoice Reconciliation

Business goal:

Upload overseas labor vendor PDF invoices plus one Excel billing workbook, extract employee-level rows from the PDF invoices, compare them against Excel employee rows, identify discrepancies and risks, and generate a downloadable difference report.

Page entry:

- `http://127.0.0.1:8001/overseas-labor.html`

User-facing flow:

1. Create a labor reconciliation batch
2. Upload PDF invoices and one Excel workbook
3. Confirm Excel field mapping
4. Stage 1: extract PDF invoice totals and compare by warehouse
5. If totals differ, Stage 2: extract employee rows from PDFs
6. Compare PDF employee rows against Excel employee rows
7. Review quality risks and download the difference report

Current implementation includes:

- FastAPI backend with labor-specific batch APIs
- Static frontend for the overseas labor workflow
- Excel sheet discovery, field suggestions, and field mapping
- Warehouse-level total comparison
- PDF employee row extraction with rule-based parsing plus AI/image fallback
- Employee-level comparison by name or employee ID
- Extraction quality diagnostics and retry logic
- Downloadable Excel difference report
- Wizard Drawer UX and KPI/result panels in the frontend

## Recent Fixes To Preserve

The current working state includes several important fixes. Do not casually revert them.

1. Metadata writes are atomic.
   - `bonus_platform/engine/labor/runs.py`
   - `bonus_platform/engine/runs.py`
   - Reason: frontend polling could previously read an empty or partially written `metadata.json`, causing 500 errors during background extraction.

2. Server startup recovers interrupted labor batches.
   - `bonus_platform/app.py`
   - Any batch left in `抽取中` after a server restart is marked as `抽取失败` with a clear retry message.

3. Do not run long extraction tasks with `uvicorn --reload`.
   - Use a stable server process for manual testing:
     ```bash
     python3 -m uvicorn bonus_platform.app:app --port 8001
     ```
   - `--reload` can interrupt background extraction and leave stale batch state.

4. PDF image rendering must preserve orientation.
   - `bonus_platform/engine/labor/extract.py`
   - A previous implementation forced any portrait page to landscape with `rotate(90)`. That made scanned invoice text sideways for the AI and caused employee-detail extraction to return `[]`.

5. AI image extraction cache version is `v6`.
   - This intentionally avoids stale `v5` image caches produced from wrongly rotated pages.

6. AI image rows are filtered against Excel candidate employees.
   - This prevents hallucinated names such as `John Doe`.
   - Matching rule: token Jaccard `>= 0.30` or full-name character similarity `>= 0.78`.

## Known Risks

- MiMo/Anthropic image requests can still timeout or disconnect on some pages.
- If all image pages fail or return empty arrays, Stage 2 can still fail with `AI 图片抽取返回 0 条员工明细`.
- Error reporting is still too coarse. The UI should eventually distinguish:
  - PDF render failure
  - AI request timeout/disconnect
  - AI returned empty rows
  - rows discarded by Excel-candidate filtering
  - comparison/report generation failure
- Supplier formats vary. Avoid hardcoding one-off invoice rules unless isolated behind a supplier profile or a generally reusable parser.

## Suggested Next Work

For the overseas labor flow, prioritize in this order:

1. Re-run a real overseas labor invoice batch after the orientation/cache fix.
2. Add per-page extraction diagnostics: render status, AI request status, raw row count, filtered row count, final kept row count.
3. Improve user-facing failure messages so the user knows which stage failed and what to retry.
4. Add or refine supplier profiles only after inspecting actual invoice layouts.
5. Consider OCR or structured table extraction as a fallback if MiMo image extraction remains unreliable.

## Files To Read First

Read these before editing behavior:

1. `bonus_platform/app.py`
   - FastAPI endpoints
   - background extraction orchestration
   - batch recovery logic

2. `bonus_platform/engine/labor/extract.py`
   - PDF text extraction
   - PDF image rendering
   - AI/MiMo request code
   - employee row normalization and filtering

3. `bonus_platform/engine/labor/compare.py`
   - employee and warehouse comparison

4. `bonus_platform/engine/labor/quality.py`
   - extraction quality and diagnostics

5. `bonus_platform/engine/labor/runs.py`
   - labor batch metadata and file records

6. `bonus_platform/static/overseas-labor.js`
   - frontend labor workflow

7. `docs/superpowers/specs/2026-05-26-overseas-labor-billing-reconciliation-design.md`

8. `docs/superpowers/plans/2026-05-29-extraction-optimization.md`

## Other Product Areas

Recruitment bonus calculation exists and should not be broken while working on overseas labor reconciliation.

Domestic labor worker payroll calculation is part of the broader Sigma Workbench product scope, but it is a separate project area. Do not implement it by mixing it into the overseas invoice reconciliation flow.

## Guardrails

- Do not remove or rename APIs without updating frontend call sites and tests.
- Do not delete tests to make changes pass.
- Do not change recruitment bonus behavior while working on overseas labor reconciliation unless the task explicitly requires it.
- Do not do broad refactors outside the current behavior under repair.
- Do not hardcode supplier-specific behavior unless the behavior belongs in a profile or a documented parser.
- Always inspect `git status` and `git diff` before editing.

## Verification Requirements

For overseas labor changes, run:

```bash
python3 -m pytest -q tests/test_labor_engine.py tests/test_labor_api.py
```

For broader changes, run:

```bash
python3 -m pytest -q
```

For local manual testing:

```bash
python3 -m uvicorn bonus_platform.app:app --port 8001
```

Then verify:

- `http://127.0.0.1:8001/`
- `http://127.0.0.1:8001/overseas-labor.html`

## Handoff-Back Requirements

When Claude hands work back, ask it to provide:

- working branch name
- latest commit hash
- whether tests passed
- short change summary
- unresolved issues
- suggested next step

That is enough for a later handoff back into Codex.
