# Overseas Labor Golden Regression

This document defines the first safe baseline for real-material regression. It does not define business truth. Program output must not be copied into expected results unless a business reviewer confirms it.

## Local Data Boundary

Real materials remain outside the Git repository:

```text
/Users/zt27532/Documents/报账核对工具
```

Local manifests that contain real relative paths or file names should be written under ignored runtime output, for example:

```text
outputs/labor_golden/local_manifest.json
```

The repository already ignores `outputs/*`, so this local manifest must not enter Git. Shareable examples must use synthetic file names and no employee details.

## Manifest Shape

```json
{
  "schema_version": 1,
  "materials_root": "/Users/zt27532/Documents/报账核对工具",
  "expected_result_policy": "program output is not accepted as truth; business review required",
  "batches": [
    {
      "batch_key": "fairway已报账",
      "supplier_ref": "short irreversible hash",
      "period_hint": "2026-04-27~2026-05-03",
      "warehouse_count": 6,
      "files": [
        {
          "relative_path": "fairway已报账/example.pdf",
          "file_type": "invoice_pdf",
          "size_bytes": 12345,
          "sha256": "..."
        }
      ],
      "excel": {
        "sheet": "员工账单明细",
        "mapping_version": "suggested-v1",
        "suggested_mapping": {
          "name": "姓名",
          "hours": "时长总计(H)",
          "amount": "费用总计(含税)"
        }
      },
      "expected_result": {
        "review_status": "needs_business_review",
        "metrics": {
          "invoice_total": null,
          "excel_total": null,
          "warehouse_count": null,
          "employee_count": null,
          "total_hours": null,
          "difference_category_counts": null,
          "manual_review_count": null,
          "core_error_types": []
        }
      },
      "allowed_manual_review_items": [],
      "notes": "Expected result must be filled by reviewed business evidence."
    }
  ]
}
```

Allowed `expected_result.review_status` values:

- `needs_business_review`
- `provisional`
- `approved`
- `rejected`
- `unknown`

Only `approved` can be used as a business-truth regression target. All other statuses are useful for file coverage and replay readiness only.

## Command Interface

Build a supplier coverage plan and business review template before asking business reviewers to approve expected results:

```bash
PYTHONDONTWRITEBYTECODE=1 \
python3 -m bonus_platform.engine.labor.golden plan \
  --materials-root "/Users/zt27532/Documents/报账核对工具" \
  --output /tmp/labor_golden/coverage_plan.json
```

The plan command is read-only. It selects one candidate batch for each required supplier, emits a manifest discovery command, emits the matching `--require-approved` validation command, and includes an `expected_result_template` for business review. It does not run extraction, does not write reports, does not approve results, and does not access Blob or UAT.

To override the first required supplier set:

```bash
python3 -m bonus_platform.engine.labor.golden plan \
  --materials-root "/Users/zt27532/Documents/报账核对工具" \
  --required-suppliers fairway oss osi sss workforce grande \
  --output /tmp/labor_golden/coverage_plan.json
```

Prepare selected manifests for the first supplier set in one local output directory:

```bash
PYTHONDONTWRITEBYTECODE=1 \
python3 -m bonus_platform.engine.labor.golden prepare \
  --materials-root "/Users/zt27532/Documents/报账核对工具" \
  --output-dir /tmp/labor_golden/manifests \
  --output /tmp/labor_golden/prepare_summary.json
```

The prepare command writes `coverage_plan.json` plus one manifest per covered supplier into `--output-dir`. It validates file presence and SHA-256 hashes, but expected results remain `needs_business_review`. It must be run into a temporary or ignored local directory because the generated manifests contain real material relative paths and file names.

Discover one batch and write a local ignored manifest:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS="-p no:cacheprovider" \
python3 -m bonus_platform.engine.labor.golden discover \
  --materials-root "/Users/zt27532/Documents/报账核对工具" \
  --batch-key "fairway已报账" \
  --output /tmp/labor_golden/fairway_manifest.json
```

Discover all candidate batches for one supplier:

```bash
python3 -m bonus_platform.engine.labor.golden discover \
  --materials-root "/Users/zt27532/Documents/报账核对工具" \
  --supplier fairway \
  --output /tmp/labor_golden/fairway_all_manifest.json
```

Validate a manifest without running extraction or writing reports:

```bash
python3 -m bonus_platform.engine.labor.golden validate \
  --manifest /tmp/labor_golden/fairway_manifest.json \
  --materials-root "/Users/zt27532/Documents/报账核对工具"
```

Validate as a release gate after business approval:

```bash
python3 -m bonus_platform.engine.labor.golden validate \
  --manifest /tmp/labor_golden/fairway_manifest.json \
  --materials-root "/Users/zt27532/Documents/报账核对工具" \
  --require-approved
```

Validate all prepared manifests as one release gate:

```bash
python3 -m bonus_platform.engine.labor.golden validate-dir \
  --manifest-dir /tmp/labor_golden/manifests \
  --materials-root "/Users/zt27532/Documents/报账核对工具" \
  --require-approved \
  --output /tmp/labor_golden/release_gate.json
```

The directory release gate scans `*_manifest.json` files, validates every file hash, and returns a non-zero exit code if any manifest is missing, has changed files, is not business-approved, or has incomplete approved metrics.

Generate a business review template from prepared manifests:

```bash
python3 -m bonus_platform.engine.labor.golden review-template \
  --manifest-dir /tmp/labor_golden/manifests \
  --materials-root "/Users/zt27532/Documents/报账核对工具" \
  --output /tmp/labor_golden/business_review_template.json
```

The review template is a handoff artifact, not a result file. It keeps expected metrics empty, summarizes file counts and hash prefixes, and gives business reviewers the fields they must fill before any manifest can be marked `approved`.

To send one batch or one redacted supplier for review at a time, add `--batch-key` or `--supplier-ref` to `review-template` or `handoff`. This keeps the artifact scoped to that batch or supplier while preserving the same redaction and expected-metric requirements.

For business review, prefer generating a redacted handoff package instead of sending raw manifests:

```bash
python3 -m bonus_platform.engine.labor.golden handoff \
  --manifest-dir /tmp/labor_golden/manifests \
  --output-dir /tmp/labor_golden/business_handoff \
  --materials-root "/Users/zt27532/Documents/报账核对工具" \
  --batch-key "fairway已报账" \
  --output /tmp/labor_golden/business_handoff_summary.json
```

The handoff package writes `business_review_template.json`, `BUSINESS_REVIEW_README.md`, and `handoff_summary.json`. It removes local manifest paths, avoids raw file names, includes only file type counts and SHA-256 prefixes, and documents how business reviewers must fill each required `expected_metrics` field. It is still a local `/tmp` artifact and should not be committed.

Before sharing the handoff package, run the privacy scan gate:

```bash
python3 -m bonus_platform.engine.labor.golden scan-handoff \
  --handoff-dir /tmp/labor_golden/business_handoff \
  --materials-root "/Users/zt27532/Documents/报账核对工具" \
  --output /tmp/labor_golden/business_handoff/privacy_scan.json
```

The scan-handoff command checks the local handoff files for the materials root path, explicit forbidden terms supplied with `--forbidden-term`, and employee-id-like values. It returns a non-zero exit code if it finds a leak, so the package must be regenerated or corrected before it is shared with reviewers.

## Returned Redacted Review Workflow

When business reviewers return a completed handoff package, keep the returned file in a new local `/tmp` directory and treat it as untrusted until it passes validation. Do not copy it into Git. Do not ask business reviewers to return `batch_key` or `supplier_ref`; the handoff package uses `review_batch_ref` as the only batch identifier that can safely leave the local machine.

Recommended local layout:

```text
/tmp/labor_golden/business_handoff_returned/business_review_template.json
```

Before applying reviewer decisions, run a privacy scan on the returned package as well as the original package:

```bash
python3 -m bonus_platform.engine.labor.golden scan-handoff \
  --handoff-dir /tmp/labor_golden/business_handoff_returned \
  --materials-root "/Users/zt27532/Documents/报账核对工具" \
  --output /tmp/labor_golden/business_handoff_returned/privacy_scan.json
```

Validate one returned redacted batch before updating any reviewed manifest copies:

```bash
python3 -m bonus_platform.engine.labor.golden validate-review \
  --review-template /tmp/labor_golden/business_handoff_returned/business_review_template.json \
  --require-approved \
  --review-batch-ref batch_0123456789ab_abcdef012345 \
  --output /tmp/labor_golden/business_handoff_returned/validate_review_summary.json
```

Apply the approved returned item into a separate reviewed-manifest output directory:

```bash
python3 -m bonus_platform.engine.labor.golden apply-review \
  --manifest-dir /tmp/labor_golden/manifests \
  --review-template /tmp/labor_golden/business_handoff_returned/business_review_template.json \
  --output-dir /tmp/labor_golden/reviewed_manifests \
  --materials-root "/Users/zt27532/Documents/报账核对工具" \
  --require-approved \
  --review-batch-ref batch_0123456789ab_abcdef012345 \
  --output /tmp/labor_golden/apply_review_summary.json
```

After apply-review succeeds, run the release gate against the reviewed copies:

```bash
python3 -m bonus_platform.engine.labor.golden validate-dir \
  --manifest-dir /tmp/labor_golden/reviewed_manifests \
  --materials-root "/Users/zt27532/Documents/报账核对工具" \
  --require-approved \
  --output /tmp/labor_golden/reviewed_manifests/release_gate.json
```

Only reviewed manifest copies that pass `validate-dir --require-approved` can be used as a golden regression source. The original discovered or prepared manifests remain local coverage artifacts and should stay `needs_business_review` until a reviewed copy is produced.

After business reviewers return the completed template, validate its structure before applying it:

```bash
python3 -m bonus_platform.engine.labor.golden validate-review \
  --review-template /tmp/labor_golden/business_handoff/business_review_template.json \
  --require-approved \
  --batch-key "fairway已报账" \
  --output /tmp/labor_golden/business_handoff/validate_review_summary.json
```

The validate-review command checks reviewed items for `approved` status, reviewer, reviewed time, evidence reference, all required `expected_metrics`, and expected metric types. Add `--batch-key` to validate one returned batch before the rest of the template is complete. If the requested batch is absent from the template, validation fails with `batch_key_not_found` instead of returning an empty successful check. It does not read source materials or run reconciliation. A failed validation means the template must go back to business review before `apply-review`.

Use `--supplier-ref <redacted supplier id>` when the business review is returned by supplier rather than by batch. If the requested supplier is absent from the template, validation fails with `supplier_ref_not_found`.

After business reviewers complete the template, write reviewed manifest copies into a separate output directory:

```bash
python3 -m bonus_platform.engine.labor.golden apply-review \
  --manifest-dir /tmp/labor_golden/manifests \
  --review-template /tmp/labor_golden/business_review_template.json \
  --output-dir /tmp/labor_golden/reviewed_manifests \
  --materials-root "/Users/zt27532/Documents/报账核对工具" \
  --require-approved \
  --batch-key "fairway已报账" \
  --output /tmp/labor_golden/apply_review_summary.json
```

The apply-review command never edits the source manifest directory. In `--require-approved` mode it first runs the same completed-template validation as `validate-review`; if reviewer, reviewed time, evidence reference, required metrics, or metric types are incomplete, it stops before writing reviewed manifests. Add `--batch-key` when business reviewers return one batch at a time, or `--supplier-ref` when review is scoped by redacted supplier. In those scoped modes, only the selected batch or supplier is applied, other batches remain unapproved, and the output manifest is still only a reviewed copy. After that gate passes, it copies manifests to `--output-dir`, applies only explicit business review fields, ignores handoff-only fields such as review `file_hashes`, validates the copied manifests, and returns a non-zero exit code when any selected reviewed manifest fails the release gate.

After reviewed manifests exist, run the manifest replay validation into an isolated output directory:

```bash
python3 -m bonus_platform.engine.labor.golden replay \
  --manifest-dir /tmp/labor_golden/reviewed_manifests \
  --output-dir /tmp/labor_golden/replay_001 \
  --materials-root "/Users/zt27532/Documents/报账核对工具" \
  --batch-key "fairway已报账" \
  --output /tmp/labor_golden/replay_001.json
```

The replay command is a strict manifest-level gate. It validates approved manifests, verifies file hashes, writes `golden_manifest_replay_summary.json`, and emits a deterministic digest so repeated runs can be compared. Add `--batch-key` to validate only the selected reviewed batch after a per-batch business review. Add `--supplier-ref <redacted supplier id>` to replay one supplier from reviewed manifests without exposing the raw supplier name. A missing supplier filter fails with `supplier_ref_not_found` instead of returning an empty successful replay. It does not yet execute the full PDF/Excel reconciliation engine; that remains a later M1/M2 step after business expected results are confirmed.

The `discover`, `validate`, and `replay` commands are read-only against the materials root. They calculate SHA-256 hashes and validate file presence only. They do not call AI, do not write `outputs/labor_runs`, and do not access Blob or UAT.

`--require-approved` is intentionally stricter: every batch must have `expected_result.review_status = "approved"` and all required expected metrics populated. Use it for CI or release gates only after the business reviewer has confirmed the expected result. A discovered manifest with `needs_business_review` may pass file/hash validation, but it must fail this approval gate.

Approved expected metrics must include:

- `invoice_total`
- `excel_total`
- `warehouse_count`
- `employee_count`
- `total_hours`
- `difference_category_counts`
- `manual_review_count`
- `core_error_types`

## First Candidate Batches

The first golden set should start with at least one representative batch from each group:

- fairway
- oss
- osi
- sss
- workforce
- grande

Do not mark any expected result as `approved` until the business reviewer confirms the metrics and allowed manual-review items.

Recommended handoff:

1. Run the `plan` command and review `supplier_coverage`.
2. Run each selected `manifest_command`.
3. Ask the business reviewer to fill `expected_result_template` values from reviewed invoice, bill, and reconciliation evidence.
4. Change a batch to `approved` only after the reviewer confirms all required expected metrics.
5. Run the matching `validate_command`; unapproved or incomplete expected results must fail the release gate.
