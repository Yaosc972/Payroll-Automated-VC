# Admin organization directory design QA

- Reference: `/Users/zt27532/.codex/generated_images/01a0427a-56de-7943-bd3a-48758d9e414f/exec-83530801-0d9f-457b-8f13-8db18cfb7358.png`
- Verified screenshot: `/private/tmp/hras-admin-redesign/final-admin.png`
- Viewport: 1470 × 743
- Browser: ego-browser task space 2

## Visual comparison

- Preserved the selected two-column information architecture: organization tree on the left, dense people table on the right.
- Preserved the enterprise blue / cool mist / glass-panel language from the existing workbench.
- Replaced the concept logo with the current `workbench-logo-2026.png` asset.
- Removed the explicitly excluded fields: hire date, direct manager, position, employee type, and work location.
- Kept essential directory fields visible: user, employee number, primary department, Feishu user ID, account status, and role summary.
- Role details are collapsed behind a compact editor so multi-role users no longer create tall tag stacks.
- Real directory sync is visibly disabled in Local/Preview.

## Interaction checks

- Department filter: passed (海外薪酬组 → 2 users).
- Search: passed (夏盈盈 → 1 user).
- Role editor expansion: passed (all role choices visible).
- Production-only sync guard: passed (disabled in local UI; API rejects non-production before any Feishu request).
- Omitted-field scan: passed.
- Logo source check: passed.

final result: passed
