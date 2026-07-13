---
version: alpha
name: Sigma Workbench FBU
description: Sigma Workbench design guidance for the FBU Americas performance bonus module and shared payroll operations shell.
colors:
  ink: "#101828"
  muted: "#667085"
  canvas: "#eef3f7"
  surface: "#ffffff"
  surface-soft: "#f8fafc"
  primary: "#1e3a8a"
  accent: "#2563eb"
  fbu-accent: "#4f46e5"
  fbu-accent-ink: "#312e81"
  cyan: "#22d3ee"
  violet: "#6d28d9"
  success: "#0f766e"
  warning: "#b7791f"
  danger: "#b42318"
  line: "rgba(226, 232, 240, 0.68)"
  glass-line: "rgba(255, 255, 255, 0.58)"
  on-brand: "#ffffff"
typography:
  display:
    fontFamily: "Inter, Geist, SF Pro Display, SF Pro Text, system-ui, sans-serif"
    fontSize: 24px
    fontWeight: 900
    lineHeight: 1.08
    letterSpacing: "-0.01em"
  title:
    fontFamily: "Inter, Geist, SF Pro Display, SF Pro Text, system-ui, sans-serif"
    fontSize: 20px
    fontWeight: 900
    lineHeight: 1.12
    letterSpacing: "-0.01em"
  body:
    fontFamily: "Inter, Geist, SF Pro Text, PingFang SC, Noto Sans SC, Microsoft YaHei UI, sans-serif"
    fontSize: 13px
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Inter, Geist, SF Pro Text, PingFang SC, Noto Sans SC, Microsoft YaHei UI, sans-serif"
    fontSize: 12px
    fontWeight: 650
    lineHeight: 1.25
    letterSpacing: "0.018em"
  micro-caps:
    fontFamily: "Inter, Geist, SF Pro Text, PingFang SC, Noto Sans SC, Microsoft YaHei UI, sans-serif"
    fontSize: 11px
    fontWeight: 650
    lineHeight: 1.25
    letterSpacing: "0.075em"
rounded:
  xs: 4px
  sm: 8px
  md: 12px
  lg: 20px
  xl: 28px
  pill: 999px
spacing:
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 32px
  page-x: 32px
components:
  app-header:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-brand}"
    rounded: "{rounded.xs}"
  page-shell:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink}"
    rounded: "{rounded.xs}"
  primary-button:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.on-brand}"
    rounded: "{rounded.md}"
    padding: 12px
  fbu-primary-button:
    backgroundColor: "{colors.fbu-accent}"
    textColor: "{colors.on-brand}"
    rounded: "{rounded.sm}"
    padding: 12px
  secondary-button:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: 12px
  card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.xl}"
    padding: 24px
  fbu-panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.fbu-accent-ink}"
    rounded: "{rounded.lg}"
    padding: 24px
  status-pill:
    backgroundColor: "{colors.surface-soft}"
    textColor: "{colors.accent}"
    rounded: "{rounded.pill}"
    padding: 8px
  metadata-label:
    backgroundColor: "{colors.surface-soft}"
    textColor: "{colors.muted}"
    rounded: "{rounded.sm}"
    padding: 8px
  divider:
    backgroundColor: "{colors.line}"
    textColor: "{colors.ink}"
    rounded: "{rounded.xs}"
  glass-panel:
    backgroundColor: "{colors.glass-line}"
    textColor: "{colors.ink}"
    rounded: "{rounded.xl}"
    padding: 24px
  telemetry-cyan:
    backgroundColor: "{colors.cyan}"
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    padding: 8px
  telemetry-violet:
    backgroundColor: "{colors.violet}"
    textColor: "{colors.on-brand}"
    rounded: "{rounded.pill}"
    padding: 8px
  success-pill:
    backgroundColor: "{colors.success}"
    textColor: "{colors.on-brand}"
    rounded: "{rounded.pill}"
    padding: 8px
  warning-pill:
    backgroundColor: "{colors.warning}"
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    padding: 8px
  danger-pill:
    backgroundColor: "{colors.danger}"
    textColor: "{colors.on-brand}"
    rounded: "{rounded.pill}"
    padding: 8px
---

## Overview

Sigma Workbench FBU is a focused payroll operations surface for Americas performance bonus calculation. It belongs to the wider Sigma Workbench platform, so it should keep the platform's enterprise blue shell while allowing a controlled purple FBU accent inside the module.

The interface should feel precise, auditable, and task-oriented. Users need to import source files, run calculations, inspect coefficient and attendance outcomes, compare exceptions, and export results without ambiguity.

## Colors

Use `primary` for the shared Sigma shell, navigation, headers, and platform-level framing. Use `accent` for shared workbench actions. Use `fbu-accent` only for FBU module primary actions, selected sidebar state, and key FBU workflow highlights.

Neutral surfaces should stay light: `canvas` for the background, `surface` for cards and panels, and `surface-soft` for quiet labels. `muted` is for secondary copy, timestamps, and helper text.

Use `success`, `warning`, and `danger` strictly for validation, calculation, and reconciliation status. Do not use status colors as decorative accents.

## Typography

Use Inter/Geist for Latin text and system CJK fonts for Chinese UI. Keep headings compact and operational. Use tabular numeric rendering for amounts, coefficients, hours, counts, and diff values.

FBU tables and review states should make employee IDs, names, warehouses, coefficient paths, and adjustment reasons easy to scan.

## Layout

Use an operations-console layout: fixed navigation, clear step progression, compact upload and run controls, and table-first review surfaces. Keep the FBU workflow readable on desktop without turning it into a marketing page.

Use a 4px/8px spacing rhythm. Prefer aligned filters, stable table columns, and explicit empty/error states over decorative spacing.

## Elevation & Depth

Depth should come from subtle borders, white panels, light shadows, and restrained glass effects. Avoid heavy shadows or visual effects that compete with data review.

## Shapes

Use 8px to 12px radii for FBU controls, rows, inputs, and buttons. Larger platform cards can use 20px to 28px radii. Pills are reserved for state, tags, filters, and compact workflow markers.

## Components

Primary FBU actions use `fbu-accent` with white text. Shared platform actions use `accent`. Cards and panels must expose operational content such as run status, source validation, exception counts, coefficient decisions, export state, or reconciliation deltas.

Tables should prioritize legibility: clear headers, tabular numbers, stable row height, readable hover states, and high-contrast status indicators.

## Do's and Don'ts

- Do read this file before making UI changes.
- Do preserve FBU-specific module boundaries and business labels.
- Do keep FBU workflows dense, legible, and audit-friendly.
- Do use purple only as a controlled FBU module accent.
- Do maintain keyboard-visible focus states and WCAG AA contrast.
- Don't change calculation meaning, source-file semantics, employee identifiers, or module routes for visual consistency alone.
- Don't spread FBU-specific styling into unrelated Sigma modules without explicit approval.
- Don't hide exceptions, warnings, coefficient paths, or manual-adjustment signals behind decorative UI.
