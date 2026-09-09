---
version: alpha
name: Sigma Workbench Domestic Labor
description: Sigma Workbench design guidance for the China domestic labor vendor payroll module using the shared Sigma enterprise dashboard system.
colors:
  ink: "#101828"
  muted: "#667085"
  canvas: "#eef3f7"
  surface: "#ffffff"
  surface-soft: "#f8fafc"
  primary: "#1e3a8a"
  accent: "#2563eb"
  cyan: "#22d3ee"
  violet: "#6d28d9"
  success: "#0f766e"
  warning: "#9a6700"
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
  payroll-panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
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
    backgroundColor: "{colors.surface-soft}"
    textColor: "{colors.warning}"
    rounded: "{rounded.pill}"
    padding: 8px
  danger-pill:
    backgroundColor: "{colors.danger}"
    textColor: "{colors.on-brand}"
    rounded: "{rounded.pill}"
    padding: 8px
---

## Overview

Sigma Workbench Domestic Labor is a payroll operations surface for China domestic labor vendor payroll. It belongs to the wider Sigma Workbench platform and should use the shared Sigma enterprise dashboard system rather than a separate green or warm-gray module theme.

The interface should feel reliable, audit-friendly, and operational. Users need to upload vendor payroll files, select engines, review validation results, inspect exceptions, compare source data, and export outputs without visual noise.

## Colors

Use `primary` for persistent navigation, headers, and platform-level framing. Use `accent` for primary actions, selected states, links, and focus rings.

Neutral surfaces should stay cool and light: `canvas` for page background, `surface` for panels and cards, and `surface-soft` for quiet controls, labels, and warning backgrounds. `muted` is for helper text, metadata, and secondary row information.

Use `success`, `warning`, and `danger` strictly for validation or payroll-risk communication. Do not create module-specific palettes unless explicitly requested.

## Typography

Use Inter/Geist for Latin text and system CJK fonts for Chinese UI. Headings should be compact and operational, not decorative.

Amounts, counts, row IDs, employee IDs, attendance values, and comparison deltas should use tabular numeric rendering where possible.

## Layout

Use an operations-console layout: sticky top controls, clear batch metadata, compact engine selection, upload flow, status rows, and table-first review regions. Avoid marketing-style hero composition inside payroll work screens.

Use a 4px/8px spacing rhythm. Prefer stable table columns, aligned controls, explicit empty states, and visible error/warning summaries over decorative spacing.

## Elevation & Depth

Depth should come from subtle borders, light shadows, white panels, and restrained glass effects. Avoid heavy shadows, high-saturation gradients, and visual effects that compete with payroll review.

## Shapes

Use 8px to 12px radii for buttons, inputs, filters, table controls, and smaller cards. Use 20px to 28px radii for larger platform cards and panels. Pills are reserved for status, batch metadata, filters, and compact workflow markers.

## Components

Primary actions use `accent` with white text. Secondary actions use light surfaces with ink text and visible borders when needed.

Panels and cards must expose operational content such as upload status, batch period, engine state, validation issues, exception counts, comparison deltas, export readiness, or audit notes. Do not use cards only as decoration.

Tables should prioritize legibility: clear headers, stable row height, tabular numbers, restrained hover states, and high-contrast warning/error indicators.

## Do's and Don'ts

- Do read this file before making UI changes.
- Do preserve domestic labor module boundaries and exact Chinese business labels.
- Do keep payroll workflows dense, legible, and audit-friendly.
- Do use the shared Sigma blue enterprise system for this module.
- Do maintain keyboard-visible focus states and WCAG AA contrast.
- Don't reintroduce the old ink-green or warm-gray domestic module theme unless explicitly requested.
- Don't change source-file meaning, payroll calculation semantics, employee identifiers, engine names, or module routes for visual consistency alone.
- Don't hide validation warnings, exception counts, comparison deltas, or export readiness behind decorative UI.
