# FBU Precalculation Check Navigation Implementation Plan

**Goal:** Open an activity at its earliest incomplete input step and reserve the check step for user-initiated review immediately before calculation.

**Architecture:** Add one helper that evaluates the existing needs for people, attendance, salary, and performance in order. Reuse it for automatic activity entry and for a single prerequisite message on the check step, without duplicating upload tasks there.

**Tech Stack:** Static JavaScript, pytest static workflow tests, Playwright browser verification.

## Constraints

- Completed activities still open on confirmation/export.
- New activities still open on people review.
- Upload refreshes preserve the user's current step.
- The check step remains manually accessible before prerequisites are complete.
- No calculation or API behavior changes.

## Tasks

- [x] Add static tests for earliest-incomplete automatic entry and non-duplicated check prerequisites.
- [x] Implement `getFirstIncompleteInputStep(activity)` using existing `buildNeedsForStep` conditions.
- [x] Make automatic entry use the helper and fall through to `check` only after the four input steps are complete.
- [x] Replace the check step's full upload-task aggregation with one link to the earliest incomplete step.
- [x] Disable calculation until the precalculation check has no prerequisite blockers.
- [x] Run static FBU tests, full FBU tests, and browser verification.
