# Monthly-Only Calculation Design

## Goal

Reduce the first platform release to current-rule monthly bonus calculation. The main calculation flow must not accept or apply legacy history workbooks.

## Product Scope

The calculation page accepts one monthly HR workbook. The platform calculates recruitment bonus and referral bonus from the current rule workbook, generates pending-confirmation workbooks when manual review is needed, and keeps the existing finalization flow for confirmed results.

Legacy payroll cumulative workbooks are out of scope for the main calculation flow. Old-rule referral payouts, historical amount overrides, historical period overrides, and the obsolete "另一半奖金" branch are not used to calculate the current-rule monthly result.

## User Flow

1. Download the import template.
2. Upload the monthly HR workbook.
3. Run the current-rule calculation.
4. Download the initial result directly when no confirmation is needed.
5. When pending nodes exist, download the pending confirmation workbook, complete it, upload initial result plus confirmation workbook, and download final result.

## Technical Design

The web UI removes the history workbook file picker and all copy that implies history upload. The browser sends only the monthly workbook to `/api/calculate`.

The API removes `history_file` from the main calculation endpoint and does not load `bonus_platform.engine.history` in that endpoint. History parsing code may remain in the repository for now because existing research tests reference it, but it is not reachable from the product calculation flow.

The calculation engine remains unchanged for current-rule node calculation and the finalization endpoint remains unchanged.

## Error Handling

The monthly workbook validation remains unchanged. If a client sends an extra `history_file` field, FastAPI ignores it because the endpoint does not declare it; it cannot influence calculation.

## Verification

Automated tests assert that:

- the page has no history upload control or history copy;
- the page JavaScript sends only the monthly workbook;
- the calculate endpoint returns current-rule results even if a client posts an extra history workbook field.

Browser verification checks the local page upload panel after the frontend change.
