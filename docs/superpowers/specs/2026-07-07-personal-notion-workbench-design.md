# Personal Notion Workbench Design

## Purpose

Build a lightweight Notion workspace for the user as a **个人项目负责人 / Vibecoding 操盘者**.

This is not a full knowledge base. It is a project review, work-summary, and task-follow-up system that should be useful at a glance.

## Design Principles

- Start with conclusions and current status.
- Use dashboard views, tables, cards, timelines, and simple flow diagrams wherever they make the page easier to scan.
- Keep written notes short. Default log entries should be 3-6 lines.
- Record only content that is useful for review, reporting, action, or reuse.
- Do not record command output, raw file lists, long implementation explanations, or unresolved chat noise.

## Top-Level Structure

### 1. Personal Workbench

The home page should work like a leadership-style status board:

- This week: key project movement and open follow-ups.
- Active projects: status, current focus, recent progress, next step.
- Quick links: Project Overview, Project Log, Common Tools, Follow-ups.

### 2. Project Overview

Database of projects. One row per project.

Recommended fields:

- Project
- Status: Active, Validating, Paused, Done, Blocked
- Current Focus
- Recent Progress
- Next Step
- Last Updated
- Related Logs
- Related Tasks
- Related Tools

Clicking a project opens a visual project detail page.

### 3. Project Detail Page

Each project page should be a **project map + situation page**, not a plain text document.

Sections:

- Project Map: goal, scope, current stage, inputs, outputs, core boundary.
- Flow Diagram: how the project moves from input to result.
- Current Situation: status indicators, current focus, risks, next step.
- Key Milestones: timeline of important project nodes.
- Drill-Down Entrances: recent logs, tasks, tools, lessons.

### 4. Project Log

Database of short action logs.

Default entry format:

- Date
- Project
- What Changed
- Result
- Next Step

The log is a drill-down layer, not the primary reading surface.

### 5. Common Tools

Database for Codex/Vibecoding tools and reusable workflows.

Recommended fields:

- Name
- Type: Skill, Open Source Project, Workflow, Command, Plugin
- Use Case
- When to Use
- Watch Out
- Related Project

Examples:

- brainstorming: use before shaping new features or systems.
- Playwright: use for real UI and E2E verification.
- lark-cli: use for Feishu docs, permissions, approvals, and content fetches.
- "先比对再修规则": use for payroll/accounting reconciliation work.

### 6. Follow-Ups

Light task database linked to projects.

Recommended fields:

- Task
- Project
- Status
- Priority
- Due Date
- Owner
- Source Log

This should stay lightweight and should not become a full project-management system.

## Historical Initialization

Initialize with a small curated history, not a full transcript import.

Initial projects:

- Sigma Workbench
- Overseas Labor Reconciliation
- FBU Performance Bonus
- Recruitment Bonus Validation
- Lark / Codex Tooling
- Vibecoding Workflow

Initial historical logs should be limited to 5-8 key nodes, with a hard ceiling of 10. Each should summarize an outcome, not a process.

Suggested seed logs:

- Sigma Workbench: added root-level design and agent guidance for the platform.
- Overseas Labor Reconciliation: fixed async storage and metadata stability work.
- FBU Performance Bonus: reviewed module brittleness and hardened module-specific tests.
- FBU Performance Bonus: preserved FBU worktree boundaries and handoff state.
- Recruitment Bonus Validation: kept validation read-only and improved special-region/cycle-exclusion evidence.
- Lark / Codex Tooling: updated lark-cli by identifying the active npm-owned binary path.
- Vibecoding Workflow: adopted project-first, dashboard-first Notion recording.

## Recording Rules

When updating after a task:

1. Add one short project log entry.
2. Update the related project's recent progress, next step, and last updated date.
3. Add or update a tool/workflow entry only when the method is reusable.
4. Add a follow-up only when there is a concrete next action.

## Non-Goals

- No full transcript import.
- No long-form engineering notes by default.
- No command-output archive.
- No detailed code-change ledger.
- No automatic background monitoring without an explicit future automation design.

## Notion Build Notes

The first Notion version should prioritize clarity over complexity:

- Use a home page plus four databases: Project Overview, Project Log, Common Tools, Follow-Ups.
- Use database relations where useful, but keep properties minimal.
- Use page content blocks for project maps, flow diagrams, milestone sections, and visual summaries.
- Keep all seed content concise enough to read quickly.
