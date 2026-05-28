# Claude Handoff

This document is the handoff brief for Claude Code or any other coding agent taking over the repository for a period of time.

Use this document as the operational source of truth before making changes.

## Repository

- Repo: `Payroll-Automated-VC`
- Local workspace root: `/Users/zt27532/Documents/New project 2`
- Main active feature lineage:
  - `codex/command-center-v1`: labor reconciliation logic and quality retry work
  - `ui/redesign`: current overseas labor page redesign

When handing work to Claude, create a fresh working branch from the latest agreed branch instead of reusing historical branches.

Recommended pattern:

```bash
git checkout ui/redesign
git pull
git checkout -b claude/handoff-01
git push -u origin claude/handoff-01
```

## Product Context

This repo started as a local recruitment/referral bonus calculation workbench. It now also includes a separate workflow for overseas labor invoice reconciliation.

The overseas labor workflow is the main handoff target.

User-facing flow:

1. Create a labor reconciliation batch
2. Upload PDF invoices and one Excel workbook
3. Confirm field mapping
4. Extract employee rows from PDFs
5. Compare PDF totals against Excel employee rows
6. Review risks and download a difference report

Page entry:

- `http://127.0.0.1:8001/overseas-labor.html`

## What Exists Today

Current implementation already includes:

- FastAPI backend with labor-specific batch APIs
- Static frontend for the overseas labor workflow
- PDF employee row extraction
- Excel row mapping and loading
- Employee-level comparison by name or employee ID
- Risk rows and downloadable Excel difference report
- Extraction quality checks
- Retry path that re-runs extraction using Excel employee candidates when the first extraction quality is poor
- A redesigned light-theme overseas labor UI on `ui/redesign`

## Files To Read First

Read these before editing behavior:

- [README.md](/Users/zt27532/Documents/New project 2/README.md)
- [bonus_platform/README.md](/Users/zt27532/Documents/New project 2/bonus_platform/README.md)
- [docs/superpowers/specs/2026-05-26-overseas-labor-billing-reconciliation-design.md](/Users/zt27532/Documents/New project 2/docs/superpowers/specs/2026-05-26-overseas-labor-billing-reconciliation-design.md)
- [bonus_platform/app.py](/Users/zt27532/Documents/New project 2/bonus_platform/app.py)
- [bonus_platform/engine/labor/extract.py](/Users/zt27532/Documents/New project 2/bonus_platform/engine/labor/extract.py)
- [bonus_platform/engine/labor/compare.py](/Users/zt27532/Documents/New project 2/bonus_platform/engine/labor/compare.py)
- [bonus_platform/engine/labor/workbook.py](/Users/zt27532/Documents/New project 2/bonus_platform/engine/labor/workbook.py)
- [bonus_platform/engine/labor/report.py](/Users/zt27532/Documents/New project 2/bonus_platform/engine/labor/report.py)
- [bonus_platform/static/overseas-labor.html](/Users/zt27532/Documents/New project 2/bonus_platform/static/overseas-labor.html)
- [bonus_platform/static/overseas-labor.js](/Users/zt27532/Documents/New project 2/bonus_platform/static/overseas-labor.js)
- [bonus_platform/static/styles.css](/Users/zt27532/Documents/New project 2/bonus_platform/static/styles.css)
- [tests/test_labor_api.py](/Users/zt27532/Documents/New project 2/tests/test_labor_api.py)

## Current Behavioral Notes

These are the important current behaviors to preserve unless there is a deliberate, verified improvement:

- The system is not a generic AI summary page. It is a reconciliation workflow with a fixed sequence and downloadable report.
- The backend should keep the existing batch structure and labor APIs.
- Labor extraction quality is evaluated after comparison. Current checks include:
  - PDF employee count vs Excel employee count
  - unmatched employee count
  - total hours drift
  - total amount drift
- If first-pass quality is poor, the system may retry extraction with Excel employee candidates.
- The overseas labor UI currently lives in the redesigned light theme branch and should remain usable while logic keeps evolving.

## Guardrails

Do not make these kinds of changes casually:

- Do not remove or rename labor APIs without updating all call sites and tests.
- Do not delete tests to make changes pass.
- Do not change unrelated recruitment/referral bonus logic while working on overseas labor reconciliation.
- Do not do broad refactors outside the labor flow unless they are required to complete the task safely.
- Do not hardcode a one-off supplier workaround unless there is a strong reason and it is isolated behind a general mechanism or profile system.

## Preferred Direction

The project should move toward a more general extraction and comparison system, not toward maintaining dozens of supplier-specific hacks.

Good directions:

- improve generic PDF row extraction robustness
- improve name matching and row alignment logic
- improve retry or fallback mechanisms
- improve confidence and quality scoring
- improve report trustworthiness and operator review clarity

Higher-risk directions that need more restraint:

- rewriting batch metadata layout
- redesigning API shapes
- replacing the comparison model wholesale
- vendor-specific branching that will not scale

## Working Style

Use this order of operations:

1. Read the current implementation and summarize the actual state
2. Identify the top 3 most valuable next improvements
3. Choose one focused improvement at a time
4. Implement in small commits
5. Run tests after each meaningful change
6. If UI changed, verify the page in browser as well

Avoid trying to solve extraction quality, UI polish, report format, and architecture cleanup all at once.

## Verification Requirements

Before reporting completion of a change, run:

```bash
python3 -m pytest -q
```

For local development:

```bash
python3 -m uvicorn bonus_platform.app:app --reload --port 8001
```

Then verify:

- `http://127.0.0.1:8001/overseas-labor.html`

If frontend files changed, confirm the page still renders and the labor workflow page has no obvious runtime error.

## Recommended Prompt For Claude

Paste the following into Claude Code when starting a handoff:

```text
You are taking over this repository for a period of time. Continue improving the overseas labor invoice reconciliation workflow.

Start from the current branch only. Read CLAUDE_HANDOFF.md first, then read the listed core files before making changes.

Your focus is not only UI. You may modify frontend, backend, extraction logic, comparison logic, and reporting if needed, but stay within the overseas labor reconciliation scope.

Work rules:
- Use the current branch as your base and do not rewrite branch history
- Make focused changes, not broad unrelated refactors
- Keep existing labor APIs working unless you deliberately update all call sites and tests
- Do not delete tests to get green
- Run `python3 -m pytest -q` after each meaningful change
- If you change frontend files, verify `http://127.0.0.1:8001/overseas-labor.html`

Before coding:
1. Summarize the current implementation state
2. List the top 3 next improvements
3. Pick the most valuable one and implement it first

At the end of each work round, output:
- latest commit hash
- what changed
- why it changed
- what remains unresolved
- which files the next agent should read first
```

## Handoff-Back Requirements

When Claude hands work back, ask it to provide:

- working branch name
- latest commit hash
- whether tests passed
- short change summary
- unresolved issues
- suggested next step

That is enough for a later handoff back into Codex.

