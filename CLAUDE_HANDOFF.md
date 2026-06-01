# Claude Handoff

This document is the handoff brief for Claude Code or any other coding agent taking over the repository for a period of time.

Use this document as the operational source of truth before making changes.

## Repository

- Repo: `Payroll-Automated-VC`
- Local workspace root: `/Users/zt27532/Payroll-Automated-VC`
- Branch: `claude/handoff-01`
- Latest commit: `1f17902`

When handing work to Claude, create a fresh working branch from the latest agreed branch instead of reusing historical branches.

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
- PDF employee row extraction (rule-based + AI fallback)
- Excel row mapping and loading
- Employee-level comparison by name or employee ID
- Risk rows and downloadable Excel difference report
- Extraction quality checks with retry logic
- Warehouse-level total comparison (two-stage extraction)
- Wizard Drawer UX for batch setup
- KPI summary banner with interactive filtering

## CRITICAL UNRESOLVED ISSUE: MiMo API Gateway Hangs

**The core extraction pipeline is STILL BROKEN.** The MiMo API (`https://token-plan-cn.xiaomimimo.com/anthropic/v1/messages`) completely deadlocks the thread when making HTTP requests with large payloads (100KB+ image base64). No timeout mechanism works reliably.

### What Was Tried (All Failed)

| Approach | Commit | Result |
|----------|--------|--------|
| `urllib.request.urlopen(timeout=180)` | original | Socket timeout doesn't cover total request time |
| `urllib.request.urlopen(timeout=45)` | `a52e848` | Same — socket read timeout, not wall-clock |
| `urllib.request.urlopen(timeout=30)` | `78d0aa2` | Same — still deadlocks for 3.5+ minutes |
| `httpx.Client(timeout=30.0)` | `1f17902` | **Not yet verified** — latest attempt |
| `thinking: {"type": "disabled"}` | `a52e848` | Removed — may cause gateway deadlock |
| Parallel workers 6→2→1 | `ab7b325`, `79adbc4`, `652f735` | Reduces but doesn't eliminate hangs |

### Root Cause Analysis

1. **`urllib.request.urlopen` timeout is socket-level, not wall-clock.** With a 100KB+ SSL payload, the proxy gateway trickles bytes slowly, keeping the socket alive and evading the timeout.

2. **The `thinking: {"type": "disabled"}` Anthropic parameter may cause the MiMo gateway to deadlock.** It was removed in `78d0aa2`.

3. **MiMo service may have rate limiting or connection pooling issues** that cause concurrent requests to hang indefinitely.

### What To Try Next

1. **Verify httpx works**: Test if `httpx.Client(timeout=30.0)` actually enforces wall-clock timeout. If it does, the hang should break at 30s with `httpx.TimeoutException`.

2. **If httpx also fails**: The issue is at the MiMo gateway level. Options:
   - Switch to a different AI provider (e.g., direct Anthropic API, OpenAI)
   - Add exponential backoff retry with a 10s per-attempt timeout
   - Use a local OCR model instead of cloud AI

3. **Reduce payload size**: The 100KB image is the main problem. Consider:
   - More aggressive JPEG compression (quality=50 instead of 85)
   - Smaller render scale (0.8 instead of 1.2)
   - Downscale images before sending

4. **Add a process-level watchdog**: If a single PDF extraction takes >60s, kill the thread and skip that PDF.

## Files To Read First

Read these before editing behavior:

1. **[bonus_platform/engine/labor/extract.py](bonus_platform/engine/labor/extract.py)** — Core extraction logic, AI API calls, HTTP client. This is where the hang happens. Key functions:
   - `_http_post_json()` (line ~34) — new httpx-based HTTP client
   - `_extract_one()` (line ~270) — per-PDF extraction (Stage 1)
   - `_extract_with_ai_images()` (line ~590) — image-based extraction (Stage 2)
   - `_post_anthropic_completion()` (line ~730) — Anthropic Messages API call

2. **[bonus_platform/app.py](bonus_platform/app.py)** — FastAPI endpoints, background task orchestration. Key functions:
   - `extract_and_compare_labor_run()` (line ~295) — starts extraction
   - `_perform_labor_extract_compare()` (line ~330) — main extraction pipeline
   - `_retry_if_better()` (line ~490) — retry logic

3. **[bonus_platform/config.py](bonus_platform/config.py)** — AI configuration, parallelism settings

4. **[bonus_platform/engine/labor/compare.py](bonus_platform/engine/labor/compare.py)** — Employee matching and warehouse comparison

5. **[bonus_platform/engine/labor/quality.py](bonus_platform/engine/labor/quality.py)** — Quality scoring system

6. **[docs/故障排查报告.md](docs/故障排查报告.md)** — Full troubleshooting report with all failed attempts

## Current Behavioral Notes

- Two-stage extraction: Stage 1 extracts totals, Stage 2 extracts employees only for diff warehouses
- `PARALLEL_MAX_WORKERS=1` (serial execution) for stability
- `PARALLEL_IMAGE_RENDER_WORKERS=1`
- 30s wall-clock timeout via httpx (unverified)
- Retry logic preserves original results if retry fails
- Fuzzy field mapping for AI-extracted rows (30+ amount key variants)
- Frontend: Wizard Drawer + KPI Banner + quality alert display

## Guardrails

Do not make these kinds of changes casually:

- Do not remove or rename labor APIs without updating all call sites and tests.
- Do not delete tests to make changes pass.
- Do not change unrelated recruitment/referral bonus logic while working on overseas labor reconciliation.
- Do not do broad refactors outside the labor flow unless they are required to complete the task safely.
- Do not hardcode a one-off supplier workaround unless there is a strong reason and it is isolated behind a general mechanism or profile system.

## Working Style

Use this order of operations:

1. Read the current implementation and summarize the actual state
2. Identify the top 3 most valuable next improvements
3. Choose one focused improvement at a time
4. Implement in small commits
5. Run tests after each meaningful change
6. If UI changed, verify the page in browser as well

## Verification Requirements

Before reporting completion of a change, run:

```bash
python3 -m pytest -q
```

For local development:

```bash
python3 -m uvicorn bonus_platform.app:app --reload --port 8001 --reload-exclude outputs/ --lifespan off
```

Then verify:

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
