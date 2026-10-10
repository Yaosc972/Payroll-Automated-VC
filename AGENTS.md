# Sigma Workbench Domestic Labor Agent Instructions

## Project Scope

This worktree is for Sigma Workbench China domestic labor vendor payroll work. Keep domestic labor changes in `/Users/zt27532/Documents/New project 2-domestic` and do not use the main Sigma worktree for this module's implementation.

## UI Work

Before making UI changes, read `DESIGN.md` and follow its tokens, component rules, and Do's and Don'ts.

Preserve the current workbench character: dense payroll operations screens, blue Sigma platform framing, compact controls, and exact business labels. Do not preserve or reintroduce the old ink-green/warm-gray domestic module theme unless explicitly requested.

## Domestic Labor Boundaries

Stay inside domestic-labor-related files by default, especially `bonus_platform/engine/domestic_labor/`, `bonus_platform/static/domestic-labor.html`, `bonus_platform/static/domestic-labor.js`, domestic labor tests, and module-specific tooling.

Do not refactor shared platform files or change other module behavior unless the request explicitly opens that boundary.

## Code Changes

Inspect the relevant files before editing. Make the smallest safe change that solves the request, preserve existing naming and structure, and avoid broad refactors unless explicitly requested.

Do not modify authentication, secrets, database schema, deployment config, payment logic, or production wiring without explicit approval.

## Verification

After domestic labor code changes, run the most relevant targeted domestic labor checks when practical. If a change is documentation-only, validate formatting or the relevant tool output when available.

## SkillHub Releases

When domestic payroll rules, engines, input contracts, or supplemental templates change, include the matching standalone Skill updates in the same delivery. Run the targeted SkillHub checks and `python3 -m scripts.domestic_labor_skillhub_release` to maintain the durable release ledger. See `docs/DOMESTIC_LABOR_SKILLHUB.md` for canonical sources and release behavior. Preserve historical ZIP exports; generate new releases from the current sources.
