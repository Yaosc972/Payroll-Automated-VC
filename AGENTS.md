# Sigma Workbench FBU Agent Instructions

## Project Scope

This worktree is for Sigma Workbench FBU Americas performance bonus work. Keep FBU changes in `/Users/zt27532/Documents/New project 2-fbu` and do not use the main Sigma worktree for FBU implementation.

## UI Work

Before making UI changes, read `DESIGN.md` and follow its tokens, component rules, and Do's and Don'ts.

Preserve the current workbench character: dense payroll operations screens, blue Sigma platform framing, controlled purple FBU module accents, compact controls, and exact business labels.

## FBU Boundaries

Stay inside FBU-related files by default, especially `bonus_platform/engine/fbu_performance/`, `bonus_platform/static/fbu-performance.html`, `bonus_platform/static/fbu-performance.js`, FBU tests, and FBU tooling.

Do not refactor shared platform files or change other module behavior unless the request explicitly opens that boundary.

## Code Changes

Inspect the relevant files before editing. Make the smallest safe change that solves the request, preserve existing naming and structure, and avoid broad refactors unless explicitly requested.

Do not modify authentication, secrets, database schema, deployment config, payment logic, or production wiring without explicit approval.

## Verification

After FBU code changes, prefer targeted FBU checks such as `python3 -m pytest tests/test_fbu_performance_engine.py tests/test_fbu_performance_api.py -q` when practical. If a change is documentation-only, validate formatting or the relevant tool output when available.
