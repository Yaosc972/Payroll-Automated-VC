import json
import hashlib
from pathlib import Path

from openpyxl import Workbook

from bonus_platform.engine.labor.golden import (
    apply_golden_review_template,
    build_golden_candidate_plan,
    build_golden_review_handoff,
    build_golden_review_template,
    discover_golden_batches,
    prepare_golden_manifests,
    run_golden_manifest_replay,
    scan_golden_handoff_privacy,
    sha256_file,
    validate_golden_review_template,
    validate_golden_manifest_dir,
    validate_golden_manifest,
)


def _write_workbook(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "员工账单明细"
    sheet.append(["工号", "姓名", "时长总计(H)", "费用总计(含税)", "币种"])
    sheet.append(["E000001", "Synthetic Worker", 8, 100, "USD"])
    workbook.save(path)


def test_discover_golden_batches_hashes_files_without_expected_truth(tmp_path):
    batch = tmp_path / "oss 2"
    batch.mkdir()
    pdf = batch / "US Elogis Service #7 Invoice W.E 05.24.26.pdf"
    workbook = batch / "员工账单明细 - 2026-06-04T094719.972.xlsx"
    pdf.write_bytes(b"%PDF-1.4\nsynthetic invoice\n")
    _write_workbook(workbook)

    manifest = discover_golden_batches(tmp_path, batch_key="oss_2")

    assert manifest["schema_version"] == 1
    assert manifest["expected_result_policy"].startswith("program output is not accepted")
    assert len(manifest["batches"]) == 1
    discovered = manifest["batches"][0]
    assert discovered["batch_key"] == "oss_2"
    assert discovered["supplier_ref"]
    assert discovered["expected_result"]["review_status"] == "needs_business_review"
    assert {record["file_type"] for record in discovered["files"]} == {"invoice_pdf", "workbook"}
    hashes = {record["relative_path"]: record["sha256"] for record in discovered["files"]}
    assert hashes["oss 2/US Elogis Service #7 Invoice W.E 05.24.26.pdf"] == sha256_file(pdf)
    assert hashes["oss 2/员工账单明细 - 2026-06-04T094719.972.xlsx"] == sha256_file(workbook)


def test_validate_golden_manifest_rejects_hash_mismatch(tmp_path):
    batch = tmp_path / "fairway已报账"
    batch.mkdir()
    pdf = batch / "135306 US Elogistics Service Corp (#10).pdf"
    pdf.write_bytes(b"%PDF-1.4\nsynthetic invoice\n")
    manifest = {
        "schema_version": 1,
        "materials_root": str(tmp_path),
        "batches": [
            {
                "batch_key": "fairway已报账",
                "supplier_ref": "abc123def456",
                "files": [
                    {
                        "relative_path": "fairway已报账/135306 US Elogistics Service Corp (#10).pdf",
                        "file_type": "invoice_pdf",
                        "sha256": "0" * 64,
                    }
                ],
                "expected_result": {"review_status": "needs_business_review"},
            }
        ],
    }

    result = validate_golden_manifest(json.loads(json.dumps(manifest)), tmp_path)

    assert result["ok"] is False
    assert any(error["code"] == "sha256_mismatch" for error in result["errors"])
    assert result["warnings"][0]["code"] == "not_business_approved"


def test_validate_golden_manifest_accepts_existing_unapproved_manifest(tmp_path):
    batch = tmp_path / "Grande-"
    batch.mkdir()
    workbook = batch / "GRANDE-5.18-5.24.xlsx"
    _write_workbook(workbook)
    manifest = {
        "schema_version": 1,
        "materials_root": str(tmp_path),
        "batches": [
            {
                "batch_key": "Grande",
                "supplier_ref": "abc123def456",
                "files": [
                    {
                        "relative_path": "Grande-/GRANDE-5.18-5.24.xlsx",
                        "file_type": "workbook",
                        "sha256": sha256_file(workbook),
                    }
                ],
                "expected_result": {"review_status": "needs_business_review"},
            }
        ],
    }

    result = validate_golden_manifest(manifest, tmp_path)

    assert result["ok"] is True
    assert result["batch_count"] == 1
    assert result["file_count"] == 1
    assert result["warnings"][0]["code"] == "not_business_approved"


def test_validate_golden_manifest_rejects_missing_required_batch_field(tmp_path):
    batch = tmp_path / "oss"
    batch.mkdir()
    pdf = batch / "invoice.pdf"
    pdf.write_bytes(b"%PDF-1.4\nsynthetic invoice\n")
    manifest = {
        "schema_version": 1,
        "materials_root": str(tmp_path),
        "batches": [
            {
                "batch_key": "oss",
                "files": [
                    {
                        "relative_path": "oss/invoice.pdf",
                        "file_type": "invoice_pdf",
                        "sha256": sha256_file(pdf),
                    }
                ],
                "expected_result": {"review_status": "needs_business_review"},
            }
        ],
    }

    result = validate_golden_manifest(manifest, tmp_path)

    assert result["ok"] is False
    assert {"code": "missing_batch_field", "batch_key": "oss", "field": "supplier_ref"} in result["errors"]


def test_validate_golden_manifest_require_approved_rejects_unreviewed_manifest(tmp_path):
    batch = tmp_path / "workforce已报账"
    batch.mkdir()
    workbook = batch / "账单.xlsx"
    _write_workbook(workbook)
    manifest = {
        "schema_version": 1,
        "materials_root": str(tmp_path),
        "batches": [
            {
                "batch_key": "workforce已报账",
                "supplier_ref": "abc123def456",
                "files": [
                    {
                        "relative_path": "workforce已报账/账单.xlsx",
                        "file_type": "workbook",
                        "sha256": sha256_file(workbook),
                    }
                ],
                "expected_result": {"review_status": "needs_business_review"},
            }
        ],
    }

    result = validate_golden_manifest(manifest, tmp_path, require_approved=True)

    assert result["ok"] is False
    assert result["require_approved"] is True
    assert any(error["code"] == "expected_not_approved" for error in result["errors"])


def test_validate_golden_manifest_approved_requires_complete_metrics(tmp_path):
    batch = tmp_path / "osi"
    batch.mkdir()
    pdf = batch / "invoice.pdf"
    pdf.write_bytes(b"%PDF-1.4\nsynthetic invoice\n")
    manifest = {
        "schema_version": 1,
        "materials_root": str(tmp_path),
        "batches": [
            {
                "batch_key": "osi",
                "supplier_ref": "abc123def456",
                "files": [
                    {
                        "relative_path": "osi/invoice.pdf",
                        "file_type": "invoice_pdf",
                        "sha256": sha256_file(pdf),
                    }
                ],
                "expected_result": {
                    "review_status": "approved",
                    "metrics": {
                        "invoice_total": 100.0,
                    },
                },
            }
        ],
    }

    result = validate_golden_manifest(manifest, tmp_path, require_approved=True)

    assert result["ok"] is False
    missing_fields = {error.get("field") for error in result["errors"] if error["code"] == "approved_expected_metric_missing"}
    assert "excel_total" in missing_fields
    assert "core_error_types" in missing_fields


def test_validate_golden_manifest_approved_complete_metrics_passes_require_approved(tmp_path):
    batch = tmp_path / "sss"
    batch.mkdir()
    pdf = batch / "invoice.pdf"
    pdf.write_bytes(b"%PDF-1.4\nsynthetic invoice\n")
    manifest = {
        "schema_version": 1,
        "materials_root": str(tmp_path),
        "batches": [
            {
                "batch_key": "sss",
                "supplier_ref": "abc123def456",
                "files": [
                    {
                        "relative_path": "sss/invoice.pdf",
                        "file_type": "invoice_pdf",
                        "sha256": sha256_file(pdf),
                    }
                ],
                "expected_result": {
                    "review_status": "approved",
                    "metrics": {
                        "invoice_total": 100.0,
                        "excel_total": 100.0,
                        "warehouse_count": 1,
                        "employee_count": 1,
                        "total_hours": 8.0,
                        "difference_category_counts": {},
                        "manual_review_count": 0,
                        "core_error_types": [],
                    },
                },
            }
        ],
    }

    result = validate_golden_manifest(manifest, tmp_path, require_approved=True)

    assert result["ok"] is True
    assert result["errors"] == []
    assert result["warnings"] == []


def test_golden_regression_doc_includes_redacted_review_return_workflow():
    doc = Path("docs/labor_golden_regression.md").read_text(encoding="utf-8")

    assert "## Returned Redacted Review Workflow" in doc
    assert "--review-batch-ref batch_" in doc
    assert "scan-handoff" in doc
    assert "validate-review" in doc
    assert "apply-review" in doc
    assert "review_batch_ref" in doc
    assert "Do not ask business reviewers to return `batch_key` or `supplier_ref`" in doc


def test_build_golden_candidate_plan_selects_supplier_batches_and_review_template(tmp_path):
    oss_batch = tmp_path / "oss 2"
    oss_batch.mkdir()
    (oss_batch / "US Elogis Service #7 Invoice W.E 05.24.26.pdf").write_bytes(b"%PDF-1.4\nsynthetic oss invoice\n")
    _write_workbook(oss_batch / "员工账单明细 - 2026-06-04T094719.972.xlsx")

    fairway_batch = tmp_path / "fairway已报账"
    fairway_batch.mkdir()
    (fairway_batch / "135306 US Elogistics Service Corp (#10).pdf").write_bytes(b"%PDF-1.4\nsynthetic fairway invoice\n")
    _write_workbook(fairway_batch / "员工账单明细 - 2026-05-27T100728.693.xlsx")

    plan = build_golden_candidate_plan(tmp_path, required_suppliers=["oss", "fairway", "missing supplier"])

    assert plan["summary"] == {
        "required_supplier_count": 3,
        "covered_supplier_count": 2,
        "missing_supplier_count": 1,
        "missing_suppliers": ["missingsupplier"],
    }
    coverage = {row["supplier"]: row for row in plan["supplier_coverage"]}
    assert coverage["oss"]["selected_batch_key"] == "oss_2"
    assert coverage["oss"]["review_status"] == "needs_business_review"
    assert coverage["oss"]["invoice_pdf_count"] == 1
    assert coverage["oss"]["workbook_count"] == 1
    assert "/tmp/labor_golden/oss_2_manifest.json" in coverage["oss"]["manifest_command"]
    assert "/tmp/labor_golden/oss_2_manifest.json" in coverage["oss"]["validate_command"]
    assert "invoice_total" in coverage["oss"]["required_business_fields"]
    assert coverage["fairway"]["selected_batch_key"] == "fairway已报账"
    assert coverage["missingsupplier"]["review_status"] == "missing_candidate_batch"
    assert plan["expected_result_template"]["review_status"] == "needs_business_review"
    assert plan["expected_result_template"]["metrics"]["invoice_total"] is None
    assert plan["expected_result_template"]["metrics"]["difference_category_counts"] == {}


def test_prepare_golden_manifests_writes_plan_and_selected_manifests(tmp_path):
    oss_batch = tmp_path / "oss 2"
    oss_batch.mkdir()
    (oss_batch / "US Elogis Service #7 Invoice W.E 05.24.26.pdf").write_bytes(b"%PDF-1.4\nsynthetic oss invoice\n")
    _write_workbook(oss_batch / "员工账单明细 - 2026-06-04T094719.972.xlsx")

    fairway_batch = tmp_path / "fairway已报账"
    fairway_batch.mkdir()
    (fairway_batch / "135306 US Elogistics Service Corp (#10).pdf").write_bytes(b"%PDF-1.4\nsynthetic fairway invoice\n")
    _write_workbook(fairway_batch / "员工账单明细 - 2026-05-27T100728.693.xlsx")

    output_dir = tmp_path / "golden_out"

    prepared = prepare_golden_manifests(
        tmp_path,
        output_dir,
        required_suppliers=["oss", "fairway", "missing supplier"],
    )

    assert prepared["summary"] == {
        "required_supplier_count": 3,
        "prepared_manifest_count": 2,
        "missing_supplier_count": 1,
        "failed_manifest_count": 0,
    }
    assert (output_dir / "coverage_plan.json").exists()
    manifest_paths = {item["supplier"]: Path(item["manifest_path"]) for item in prepared["prepared_manifests"]}
    assert manifest_paths["oss"].name == "oss_2_manifest.json"
    assert manifest_paths["fairway"].name == "fairway已报账_manifest.json"
    oss_manifest = json.loads(manifest_paths["oss"].read_text(encoding="utf-8"))
    assert oss_manifest["batches"][0]["batch_key"] == "oss_2"
    assert oss_manifest["batches"][0]["expected_result"]["review_status"] == "needs_business_review"
    assert prepared["prepared_manifests"][0]["validation"]["ok"] is True
    assert prepared["missing_suppliers"] == ["missingsupplier"]


def test_apply_golden_review_template_writes_reviewed_copy_without_mutating_source(tmp_path):
    batch = tmp_path / "oss 2"
    batch.mkdir()
    pdf = batch / "US Elogis Service #7 Invoice W.E 05.24.26.pdf"
    workbook = batch / "员工账单明细 - 2026-06-04T094719.972.xlsx"
    pdf.write_bytes(b"%PDF-1.4\nsynthetic oss invoice\n")
    _write_workbook(workbook)
    manifest_dir = tmp_path / "manifests"
    prepared = prepare_golden_manifests(tmp_path, manifest_dir, required_suppliers=["oss"])
    manifest_path = Path(prepared["prepared_manifests"][0]["manifest_path"])
    review_template = {
        "schema_version": 1,
        "review_items": [
            {
                "batch_key": "oss_2",
                "review_status": "approved",
                "reviewer": "business-reviewer",
                "reviewed_at": "2026-06-19T10:00:00Z",
                "evidence_reference": "review workbook row 1",
                "review_notes": "confirmed from reviewed evidence",
                "allowed_manual_review_items": ["rounding_review"],
                "expected_metrics": {
                    "invoice_total": 100.0,
                    "excel_total": 100.0,
                    "warehouse_count": 1,
                    "employee_count": 1,
                    "total_hours": 8.0,
                    "difference_category_counts": {},
                    "manual_review_count": 0,
                    "core_error_types": [],
                },
                "file_hashes": [{"relative_path": "must-not-enter-manifest"}],
            }
        ],
    }
    template_path = tmp_path / "review_template.json"
    template_path.write_text(json.dumps(review_template), encoding="utf-8")
    output_dir = tmp_path / "reviewed"

    result = apply_golden_review_template(
        manifest_dir,
        template_path,
        output_dir,
        materials_root=tmp_path,
        require_approved=True,
    )

    assert result["ok"] is True
    assert result["summary"]["updated_manifest_count"] == 1
    source_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert source_manifest["batches"][0]["expected_result"]["review_status"] == "needs_business_review"
    reviewed_manifest = json.loads((output_dir / manifest_path.name).read_text(encoding="utf-8"))
    expected = reviewed_manifest["batches"][0]["expected_result"]
    assert expected["review_status"] == "approved"
    assert expected["reviewer"] == "business-reviewer"
    assert expected["reviewed_at"] == "2026-06-19T10:00:00Z"
    assert expected["evidence_reference"] == "review workbook row 1"
    assert expected["metrics"]["invoice_total"] == 100.0
    assert reviewed_manifest["batches"][0]["allowed_manual_review_items"] == ["rounding_review"]
    assert "file_hashes" not in reviewed_manifest["batches"][0]


def test_apply_golden_review_template_can_filter_to_one_batch(tmp_path):
    materials = tmp_path / "materials"
    materials.mkdir()
    oss = materials / "oss"
    oss.mkdir()
    fairway = materials / "fairway"
    fairway.mkdir()
    oss_pdf = oss / "invoice.pdf"
    oss_pdf.write_bytes(b"%PDF-1.4\nsynthetic oss invoice\n")
    fairway_pdf = fairway / "invoice.pdf"
    fairway_pdf.write_bytes(b"%PDF-1.4\nsynthetic fairway invoice\n")

    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    (manifest_dir / "mixed_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "materials_root": str(materials),
                "batches": [
                    {
                        "batch_key": "oss",
                        "supplier_ref": "oss-ref",
                        "period_hint": "2026-05-18~2026-05-24",
                        "files": [
                            {
                                "relative_path": "oss/invoice.pdf",
                                "file_type": "invoice_pdf",
                                "sha256": sha256_file(oss_pdf),
                            }
                        ],
                        "expected_result": {"review_status": "needs_business_review"},
                    },
                    {
                        "batch_key": "fairway",
                        "supplier_ref": "fairway-ref",
                        "period_hint": "2026-05-18~2026-05-24",
                        "files": [
                            {
                                "relative_path": "fairway/invoice.pdf",
                                "file_type": "invoice_pdf",
                                "sha256": sha256_file(fairway_pdf),
                            }
                        ],
                        "expected_result": {"review_status": "needs_business_review"},
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    review_template = {
        "schema_version": 1,
        "review_items": [
            {
                "batch_key": "oss",
                "review_status": "approved",
                "reviewer": "business-reviewer",
                "reviewed_at": "2026-06-19T10:00:00Z",
                "evidence_reference": "review workbook row 1",
                "expected_metrics": {
                    "invoice_total": 100.0,
                    "excel_total": 100.0,
                    "warehouse_count": 1,
                    "employee_count": 1,
                    "total_hours": 8.0,
                    "difference_category_counts": {},
                    "manual_review_count": 0,
                    "core_error_types": [],
                },
            },
            {
                "batch_key": "fairway",
                "review_status": "needs_business_review",
                "expected_metrics": {},
            },
        ],
    }

    result = apply_golden_review_template(
        manifest_dir,
        review_template,
        tmp_path / "reviewed",
        materials_root=materials,
        require_approved=True,
        batch_key="oss",
    )
    reviewed_manifest = json.loads((tmp_path / "reviewed" / "mixed_manifest.json").read_text(encoding="utf-8"))

    assert result["ok"] is True
    assert result["summary"]["review_item_count"] == 1
    assert result["summary"]["updated_manifest_count"] == 1
    assert reviewed_manifest["batches"][0]["expected_result"]["review_status"] == "approved"
    assert reviewed_manifest["batches"][1]["expected_result"]["review_status"] == "needs_business_review"


def test_review_template_and_apply_review_can_filter_to_one_supplier_ref(tmp_path):
    materials = tmp_path / "materials"
    materials.mkdir()
    oss = materials / "oss"
    oss.mkdir()
    fairway = materials / "fairway"
    fairway.mkdir()
    oss_pdf = oss / "invoice.pdf"
    oss_pdf.write_bytes(b"%PDF-1.4\nsynthetic oss invoice\n")
    fairway_pdf = fairway / "invoice.pdf"
    fairway_pdf.write_bytes(b"%PDF-1.4\nsynthetic fairway invoice\n")

    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    (manifest_dir / "mixed_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "materials_root": str(materials),
                "batches": [
                    {
                        "batch_key": "oss",
                        "supplier_ref": "oss-ref",
                        "period_hint": "2026-05-18~2026-05-24",
                        "files": [
                            {
                                "relative_path": "oss/invoice.pdf",
                                "file_type": "invoice_pdf",
                                "sha256": sha256_file(oss_pdf),
                            }
                        ],
                        "expected_result": {"review_status": "needs_business_review"},
                    },
                    {
                        "batch_key": "fairway",
                        "supplier_ref": "fairway-ref",
                        "period_hint": "2026-05-18~2026-05-24",
                        "files": [
                            {
                                "relative_path": "fairway/invoice.pdf",
                                "file_type": "invoice_pdf",
                                "sha256": sha256_file(fairway_pdf),
                            }
                        ],
                        "expected_result": {"review_status": "needs_business_review"},
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    template = build_golden_review_template(
        manifest_dir,
        materials_root=materials,
        supplier_ref="oss-ref",
    )

    assert template["summary"]["batch_count"] == 1
    assert template["review_items"][0]["batch_key"] == "oss"
    assert template["review_items"][0]["supplier_ref"] == "oss-ref"

    reviewed_template = {
        "schema_version": 1,
        "review_items": [
            {
                "batch_key": "oss",
                "supplier_ref": "oss-ref",
                "review_status": "approved",
                "reviewer": "business-reviewer",
                "reviewed_at": "2026-06-20T10:00:00Z",
                "evidence_reference": "review workbook row 1",
                "expected_metrics": {
                    "invoice_total": 100.0,
                    "excel_total": 100.0,
                    "warehouse_count": 1,
                    "employee_count": 1,
                    "total_hours": 8.0,
                    "difference_category_counts": {},
                    "manual_review_count": 0,
                    "core_error_types": [],
                },
            },
            {
                "batch_key": "fairway",
                "supplier_ref": "fairway-ref",
                "review_status": "needs_business_review",
                "expected_metrics": {},
            },
        ],
    }

    validation = validate_golden_review_template(
        reviewed_template,
        require_approved=True,
        supplier_ref="oss-ref",
    )
    result = apply_golden_review_template(
        manifest_dir,
        reviewed_template,
        tmp_path / "reviewed",
        materials_root=materials,
        require_approved=True,
        supplier_ref="oss-ref",
    )
    reviewed_manifest = json.loads((tmp_path / "reviewed" / "mixed_manifest.json").read_text(encoding="utf-8"))

    assert validation["ok"] is True
    assert validation["summary"]["review_item_count"] == 1
    assert result["ok"] is True
    assert result["supplier_ref"] == "oss-ref"
    assert result["summary"]["review_item_count"] == 1
    assert reviewed_manifest["batches"][0]["expected_result"]["review_status"] == "approved"
    assert reviewed_manifest["batches"][1]["expected_result"]["review_status"] == "needs_business_review"


def test_validate_golden_review_template_rejects_missing_supplier_ref_filter(tmp_path):
    template = {
        "schema_version": 1,
        "review_items": [
            {
                "batch_key": "oss",
                "supplier_ref": "oss-ref",
                "review_status": "approved",
                "reviewer": "business-reviewer",
                "reviewed_at": "2026-06-20T10:00:00Z",
                "evidence_reference": "review workbook row 1",
                "expected_metrics": {
                    "invoice_total": 100.0,
                    "excel_total": 100.0,
                    "warehouse_count": 1,
                    "employee_count": 1,
                    "total_hours": 8.0,
                    "difference_category_counts": {},
                    "manual_review_count": 0,
                    "core_error_types": [],
                },
            }
        ],
    }

    result = validate_golden_review_template(template, require_approved=True, supplier_ref="missing-ref")

    assert result["ok"] is False
    assert result["summary"]["review_item_count"] == 0
    assert result["summary"]["error_count"] == 1
    assert result["errors"] == [
        {
            "code": "supplier_ref_not_found",
            "supplier_ref": "missing-ref",
            "message": "supplier_ref was not found in review_items",
        }
    ]


def test_apply_golden_review_template_fails_approved_item_with_incomplete_metrics(tmp_path):
    batch = tmp_path / "workforce已报账"
    batch.mkdir()
    pdf = batch / "Invoice-5058871.pdf"
    workbook = batch / "员工账单明细 - 2026-06-01T112149.990.xlsx"
    pdf.write_bytes(b"%PDF-1.4\nsynthetic workforce invoice\n")
    _write_workbook(workbook)
    manifest_dir = tmp_path / "manifests"
    prepared = prepare_golden_manifests(tmp_path, manifest_dir, required_suppliers=["workforce"])
    manifest_path = Path(prepared["prepared_manifests"][0]["manifest_path"])
    review_template = {
        "schema_version": 1,
        "review_items": [
            {
                "batch_key": "workforce已报账",
                "review_status": "approved",
                "expected_metrics": {
                    "invoice_total": 100.0,
                },
            }
        ],
    }
    template_path = tmp_path / "review_template.json"
    template_path.write_text(json.dumps(review_template), encoding="utf-8")

    result = apply_golden_review_template(
        manifest_dir,
        template_path,
        tmp_path / "reviewed",
        materials_root=tmp_path,
        require_approved=True,
    )

    assert result["ok"] is False
    assert result["summary"]["failed_manifest_count"] == 0
    assert result["summary"]["template_error_count"] > 0
    assert result["updated_manifests"] == []
    assert result["failed_manifests"] == []
    assert any(
        error["code"] == "approved_expected_metric_missing"
        for item in result["template_validation"]["items"]
        for error in item["errors"]
    )
    assert not list((tmp_path / "reviewed").glob("*_manifest.json"))
    source_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert source_manifest["batches"][0]["expected_result"]["review_status"] == "needs_business_review"


def test_apply_golden_review_template_require_approved_rejects_incomplete_review_before_writing(tmp_path):
    batch = tmp_path / "workforce已报账"
    batch.mkdir()
    pdf = batch / "Invoice-5058871.pdf"
    workbook = batch / "员工账单明细 - 2026-06-01T112149.990.xlsx"
    pdf.write_bytes(b"%PDF-1.4\nsynthetic workforce invoice\n")
    _write_workbook(workbook)
    manifest_dir = tmp_path / "manifests"
    prepare_golden_manifests(tmp_path, manifest_dir, required_suppliers=["workforce"])
    review_template = {
        "schema_version": 1,
        "review_items": [
            {
                "batch_key": "workforce已报账",
                "review_status": "approved",
                "reviewer": "",
                "reviewed_at": "",
                "evidence_reference": "",
                "expected_metrics": {
                    "invoice_total": 100.0,
                    "excel_total": 100.0,
                    "warehouse_count": 1,
                    "employee_count": 1,
                    "total_hours": 8.0,
                    "difference_category_counts": {},
                    "manual_review_count": 0,
                    "core_error_types": [],
                },
            }
        ],
    }

    result = apply_golden_review_template(
        manifest_dir,
        review_template,
        tmp_path / "reviewed",
        materials_root=tmp_path,
        require_approved=True,
    )

    assert result["ok"] is False
    assert result["summary"]["source_manifest_count"] == 1
    assert result["summary"]["failed_manifest_count"] == 0
    assert result["summary"]["template_error_count"] == 3
    assert result["updated_manifests"] == []
    assert result["failed_manifests"] == []
    assert not list((tmp_path / "reviewed").glob("*_manifest.json"))
    codes = {error["code"] for item in result["template_validation"]["items"] for error in item["errors"]}
    assert {"missing_reviewer", "missing_reviewed_at", "missing_evidence_reference"}.issubset(codes)


def test_validate_golden_manifest_dir_fails_release_gate_for_unapproved_manifest(tmp_path):
    materials = tmp_path / "materials"
    materials.mkdir()
    batch = materials / "oss"
    batch.mkdir()
    pdf = batch / "invoice.pdf"
    pdf.write_bytes(b"%PDF-1.4\nsynthetic invoice\n")

    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    (manifest_dir / "oss_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "materials_root": str(materials),
                "batches": [
                    {
                        "batch_key": "oss",
                        "supplier_ref": "abc123def456",
                        "files": [
                            {
                                "relative_path": "oss/invoice.pdf",
                                "file_type": "invoice_pdf",
                                "sha256": sha256_file(pdf),
                            }
                        ],
                        "expected_result": {"review_status": "needs_business_review"},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = validate_golden_manifest_dir(manifest_dir, materials, require_approved=True)

    assert result["ok"] is False
    assert result["summary"] == {
        "manifest_count": 1,
        "batch_count": 1,
        "file_count": 1,
        "error_count": 1,
        "warning_count": 1,
    }
    assert result["manifests"][0]["errors"][0]["code"] == "expected_not_approved"


def test_validate_golden_manifest_dir_passes_release_gate_for_approved_manifest(tmp_path):
    materials = tmp_path / "materials"
    materials.mkdir()
    batch = materials / "sss"
    batch.mkdir()
    pdf = batch / "invoice.pdf"
    pdf.write_bytes(b"%PDF-1.4\nsynthetic invoice\n")

    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    (manifest_dir / "sss_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "materials_root": str(materials),
                "batches": [
                    {
                        "batch_key": "sss",
                        "supplier_ref": "abc123def456",
                        "files": [
                            {
                                "relative_path": "sss/invoice.pdf",
                                "file_type": "invoice_pdf",
                                "sha256": sha256_file(pdf),
                            }
                        ],
                        "expected_result": {
                            "review_status": "approved",
                            "metrics": {
                                "invoice_total": 100.0,
                                "excel_total": 100.0,
                                "warehouse_count": 1,
                                "employee_count": 1,
                                "total_hours": 8.0,
                                "difference_category_counts": {},
                                "manual_review_count": 0,
                                "core_error_types": [],
                            },
                        },
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = validate_golden_manifest_dir(manifest_dir, materials, require_approved=True)

    assert result["ok"] is True
    assert result["summary"]["manifest_count"] == 1
    assert result["summary"]["error_count"] == 0
    assert result["summary"]["warning_count"] == 0


def test_run_golden_manifest_replay_passes_for_approved_manifest_and_writes_stable_summary(tmp_path):
    materials = tmp_path / "materials"
    materials.mkdir()
    batch = materials / "sss"
    batch.mkdir()
    pdf = batch / "invoice.pdf"
    pdf.write_bytes(b"%PDF-1.4\nsynthetic invoice\n")

    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    (manifest_dir / "sss_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "materials_root": str(materials),
                "batches": [
                    {
                        "batch_key": "sss",
                        "supplier_ref": "abc123def456",
                        "files": [
                            {
                                "relative_path": "sss/invoice.pdf",
                                "file_type": "invoice_pdf",
                                "sha256": sha256_file(pdf),
                            }
                        ],
                        "expected_result": {
                            "review_status": "approved",
                            "metrics": {
                                "invoice_total": 100.0,
                                "excel_total": 100.0,
                                "warehouse_count": 1,
                                "employee_count": 1,
                                "total_hours": 8.0,
                                "difference_category_counts": {},
                                "manual_review_count": 0,
                                "core_error_types": [],
                            },
                        },
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    first = run_golden_manifest_replay(manifest_dir, tmp_path / "replay_1", materials_root=materials)
    second = run_golden_manifest_replay(manifest_dir, tmp_path / "replay_2", materials_root=materials)

    assert first["ok"] is True
    assert first["summary"]["manifest_count"] == 1
    assert first["summary"]["approved_batch_count"] == 1
    assert first["deterministic_digest"] == second["deterministic_digest"]
    assert (tmp_path / "replay_1" / "golden_manifest_replay_summary.json").exists()
    assert first["output_dir"].endswith("replay_1")
    assert first["validation"]["ok"] is True


def test_run_golden_manifest_replay_rejects_unapproved_manifest(tmp_path):
    materials = tmp_path / "materials"
    materials.mkdir()
    batch = materials / "oss"
    batch.mkdir()
    pdf = batch / "invoice.pdf"
    pdf.write_bytes(b"%PDF-1.4\nsynthetic invoice\n")

    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    (manifest_dir / "oss_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "materials_root": str(materials),
                "batches": [
                    {
                        "batch_key": "oss",
                        "supplier_ref": "abc123def456",
                        "files": [
                            {
                                "relative_path": "oss/invoice.pdf",
                                "file_type": "invoice_pdf",
                                "sha256": sha256_file(pdf),
                            }
                        ],
                        "expected_result": {"review_status": "needs_business_review"},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = run_golden_manifest_replay(manifest_dir, tmp_path / "replay", materials_root=materials)

    assert result["ok"] is False
    assert result["summary"]["approved_batch_count"] == 0
    assert result["summary"]["error_count"] == 1
    assert result["validation"]["manifests"][0]["errors"][0]["code"] == "expected_not_approved"
    assert (tmp_path / "replay" / "golden_manifest_replay_summary.json").exists()


def test_run_golden_manifest_replay_can_filter_to_one_approved_batch(tmp_path):
    materials = tmp_path / "materials"
    materials.mkdir()
    sss = materials / "sss"
    sss.mkdir()
    oss = materials / "oss"
    oss.mkdir()
    sss_pdf = sss / "invoice.pdf"
    sss_pdf.write_bytes(b"%PDF-1.4\nsynthetic sss invoice\n")
    oss_pdf = oss / "invoice.pdf"
    oss_pdf.write_bytes(b"%PDF-1.4\nsynthetic oss invoice\n")

    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    (manifest_dir / "mixed_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "materials_root": str(materials),
                "batches": [
                    {
                        "batch_key": "sss",
                        "supplier_ref": "sss-ref",
                        "files": [
                            {
                                "relative_path": "sss/invoice.pdf",
                                "file_type": "invoice_pdf",
                                "sha256": sha256_file(sss_pdf),
                            }
                        ],
                        "expected_result": {
                            "review_status": "approved",
                            "metrics": {
                                "invoice_total": 100.0,
                                "excel_total": 100.0,
                                "warehouse_count": 1,
                                "employee_count": 1,
                                "total_hours": 8.0,
                                "difference_category_counts": {},
                                "manual_review_count": 0,
                                "core_error_types": [],
                            },
                        },
                    },
                    {
                        "batch_key": "oss",
                        "supplier_ref": "oss-ref",
                        "files": [
                            {
                                "relative_path": "oss/invoice.pdf",
                                "file_type": "invoice_pdf",
                                "sha256": sha256_file(oss_pdf),
                            }
                        ],
                        "expected_result": {"review_status": "needs_business_review"},
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = run_golden_manifest_replay(manifest_dir, tmp_path / "replay", materials_root=materials, batch_key="sss")

    assert result["ok"] is True
    assert result["summary"]["manifest_count"] == 1
    assert result["summary"]["batch_count"] == 1
    assert result["summary"]["approved_batch_count"] == 1
    assert result["validation"]["ok"] is True
    assert (tmp_path / "replay" / "golden_manifest_replay_summary.json").exists()


def test_run_golden_manifest_replay_can_filter_to_one_supplier_ref(tmp_path):
    materials = tmp_path / "materials"
    materials.mkdir()
    sss = materials / "sss"
    sss.mkdir()
    oss = materials / "oss"
    oss.mkdir()
    sss_pdf = sss / "invoice.pdf"
    sss_pdf.write_bytes(b"%PDF-1.4\nsynthetic sss invoice\n")
    oss_pdf = oss / "invoice.pdf"
    oss_pdf.write_bytes(b"%PDF-1.4\nsynthetic oss invoice\n")

    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    (manifest_dir / "mixed_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "materials_root": str(materials),
                "batches": [
                    {
                        "batch_key": "sss",
                        "supplier_ref": "sss-ref",
                        "files": [
                            {
                                "relative_path": "sss/invoice.pdf",
                                "file_type": "invoice_pdf",
                                "sha256": sha256_file(sss_pdf),
                            }
                        ],
                        "expected_result": {
                            "review_status": "needs_business_review",
                        },
                    },
                    {
                        "batch_key": "oss",
                        "supplier_ref": "oss-ref",
                        "files": [
                            {
                                "relative_path": "oss/invoice.pdf",
                                "file_type": "invoice_pdf",
                                "sha256": sha256_file(oss_pdf),
                            }
                        ],
                        "expected_result": {
                            "review_status": "approved",
                            "metrics": {
                                "invoice_total": 100.0,
                                "excel_total": 100.0,
                                "warehouse_count": 1,
                                "employee_count": 1,
                                "total_hours": 8.0,
                                "difference_category_counts": {},
                                "manual_review_count": 0,
                                "core_error_types": [],
                            },
                        },
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = run_golden_manifest_replay(
        manifest_dir,
        tmp_path / "replay",
        materials_root=materials,
        supplier_ref="oss-ref",
    )

    assert result["ok"] is True
    assert result["supplier_ref"] == "oss-ref"
    assert result["summary"]["batch_count"] == 1
    assert result["summary"]["approved_batch_count"] == 1
    assert result["validation"]["ok"] is True


def test_run_golden_manifest_replay_rejects_missing_supplier_ref_filter(tmp_path):
    materials = tmp_path / "materials"
    materials.mkdir()
    oss = materials / "oss"
    oss.mkdir()
    oss_pdf = oss / "invoice.pdf"
    oss_pdf.write_bytes(b"%PDF-1.4\nsynthetic oss invoice\n")

    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    (manifest_dir / "oss_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "materials_root": str(materials),
                "batches": [
                    {
                        "batch_key": "oss",
                        "supplier_ref": "oss-ref",
                        "files": [
                            {
                                "relative_path": "oss/invoice.pdf",
                                "file_type": "invoice_pdf",
                                "sha256": sha256_file(oss_pdf),
                            }
                        ],
                        "expected_result": {
                            "review_status": "approved",
                            "metrics": {
                                "invoice_total": 100.0,
                                "excel_total": 100.0,
                                "warehouse_count": 1,
                                "employee_count": 1,
                                "total_hours": 8.0,
                                "difference_category_counts": {},
                                "manual_review_count": 0,
                                "core_error_types": [],
                            },
                        },
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = run_golden_manifest_replay(
        manifest_dir,
        tmp_path / "replay",
        materials_root=materials,
        supplier_ref="missing-ref",
    )

    assert result["ok"] is False
    assert result["supplier_ref"] == "missing-ref"
    assert result["summary"]["batch_count"] == 0
    assert result["summary"]["error_count"] == 1
    assert result["validation"]["errors"] == [
        {
            "code": "supplier_ref_not_found",
            "supplier_ref": "missing-ref",
            "message": "supplier_ref was not found in golden manifests",
        }
    ]


def test_build_golden_review_template_keeps_expected_metrics_empty_and_masks_file_paths(tmp_path):
    materials = tmp_path / "materials"
    materials.mkdir()
    batch = materials / "oss"
    batch.mkdir()
    pdf = batch / "invoice.pdf"
    pdf.write_bytes(b"%PDF-1.4\nsynthetic invoice\n")
    workbook = batch / "bill.xlsx"
    _write_workbook(workbook)

    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    (manifest_dir / "oss_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "materials_root": str(materials),
                "batches": [
                    {
                        "batch_key": "oss",
                        "supplier_ref": "abc123def456",
                        "period_hint": "2026-05-18~2026-05-24",
                        "files": [
                            {
                                "relative_path": "oss/invoice.pdf",
                                "file_type": "invoice_pdf",
                                "sha256": sha256_file(pdf),
                            },
                            {
                                "relative_path": "oss/bill.xlsx",
                                "file_type": "workbook",
                                "sha256": sha256_file(workbook),
                            },
                        ],
                        "excel": {
                            "sheet": "员工账单明细",
                            "mapping_version": "suggested-v1",
                            "suggested_mapping": {"name": "姓名", "hours": "工时", "amount": "金额"},
                        },
                        "expected_result": {"review_status": "needs_business_review"},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    template = build_golden_review_template(manifest_dir, materials_root=materials)

    assert template["summary"] == {
        "batch_count": 1,
        "file_count": 2,
        "needs_business_review_count": 1,
    }
    review = template["review_items"][0]
    assert review["batch_key"] == "oss"
    assert review["review_status"] == "needs_business_review"
    assert review["period_hint"] == "2026-05-18~2026-05-24"
    assert review["file_summary"] == {"invoice_pdf": 1, "workbook": 1}
    assert review["file_hashes"][0] == {"file_type": "invoice_pdf", "sha256_prefix": sha256_file(pdf)[:12]}
    assert "relative_path" not in review["file_hashes"][0]
    assert review["excel"] == {
        "sheet": "员工账单明细",
        "mapping_version": "suggested-v1",
        "suggested_mapping": {"name": "姓名", "hours": "工时", "amount": "金额"},
    }
    assert review["expected_metrics"] == {
        "invoice_total": None,
        "excel_total": None,
        "warehouse_count": None,
        "employee_count": None,
        "total_hours": None,
        "difference_category_counts": {},
        "manual_review_count": None,
        "core_error_types": [],
    }
    assert "program output" in template["review_policy"]


def test_build_golden_review_handoff_writes_business_package_without_file_paths_or_batch_keys(tmp_path):
    materials = tmp_path / "materials"
    materials.mkdir()
    batch = materials / "oss-real-batch"
    batch.mkdir()
    pdf = batch / "invoice-with-real-name.pdf"
    pdf.write_bytes(b"%PDF-1.4\nsynthetic invoice\n")
    workbook = batch / "employee-detail-real-name.xlsx"
    _write_workbook(workbook)

    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    (manifest_dir / "oss_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "materials_root": str(materials),
                "batches": [
                    {
                        "batch_key": "oss-real-batch",
                        "supplier_ref": "abc123def456",
                        "period_hint": "2026-05-18~2026-05-24",
                        "files": [
                            {
                                "relative_path": "oss-real-batch/invoice-with-real-name.pdf",
                                "file_type": "invoice_pdf",
                                "sha256": sha256_file(pdf),
                            },
                            {
                                "relative_path": "oss-real-batch/employee-detail-real-name.xlsx",
                                "file_type": "workbook",
                                "sha256": sha256_file(workbook),
                            },
                        ],
                        "expected_result": {"review_status": "needs_business_review"},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    output_dir = tmp_path / "handoff"

    handoff = build_golden_review_handoff(manifest_dir, output_dir, materials_root=materials)

    assert handoff["ok"] is True
    assert handoff["summary"]["batch_count"] == 1
    assert handoff["summary"]["needs_business_review_count"] == 1
    assert (output_dir / "business_review_template.json").exists()
    assert (output_dir / "BUSINESS_REVIEW_README.md").exists()
    assert (output_dir / "handoff_summary.json").exists()
    assert "invoice_total" in handoff["metric_guidance"]
    assert "程序输出不能作为真值" in (output_dir / "BUSINESS_REVIEW_README.md").read_text(encoding="utf-8")
    combined = "\n".join(path.read_text(encoding="utf-8") for path in output_dir.iterdir() if path.is_file())
    assert "invoice-with-real-name.pdf" not in combined
    assert "employee-detail-real-name.xlsx" not in combined
    assert "oss-real-batch" not in combined
    assert str(materials) not in combined
    handoff_template = json.loads((output_dir / "business_review_template.json").read_text(encoding="utf-8"))
    review_item = handoff_template["review_items"][0]
    assert "batch_key" not in review_item
    expected_supplier_ref = hashlib.sha256("abc123def456".encode("utf-8")).hexdigest()[:12]
    expected_ref = hashlib.sha256("abc123def456:oss-real-batch".encode("utf-8")).hexdigest()[:12]
    assert review_item["review_batch_ref"] == f"batch_{expected_supplier_ref}_{expected_ref}"
    assert "supplier_ref" not in review_item


def test_scan_golden_handoff_privacy_accepts_redacted_handoff(tmp_path):
    materials = tmp_path / "materials"
    materials.mkdir()
    batch = materials / "oss"
    batch.mkdir()
    pdf = batch / "invoice-with-real-name.pdf"
    pdf.write_bytes(b"%PDF-1.4\nsynthetic invoice\n")
    workbook = batch / "employee-detail-real-name.xlsx"
    _write_workbook(workbook)

    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    (manifest_dir / "oss_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "materials_root": str(materials),
                "batches": [
                    {
                        "batch_key": "oss",
                        "supplier_ref": "abc123def456",
                        "files": [
                            {
                                "relative_path": "oss/invoice-with-real-name.pdf",
                                "file_type": "invoice_pdf",
                                "sha256": sha256_file(pdf),
                            },
                            {
                                "relative_path": "oss/employee-detail-real-name.xlsx",
                                "file_type": "workbook",
                                "sha256": sha256_file(workbook),
                            },
                        ],
                        "expected_result": {"review_status": "needs_business_review"},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "handoff"
    build_golden_review_handoff(manifest_dir, output_dir, materials_root=materials)

    result = scan_golden_handoff_privacy(output_dir, materials_root=materials)

    assert result["ok"] is True
    assert result["summary"]["issue_count"] == 0
    assert result["issues"] == []


def test_apply_review_template_accepts_redacted_handoff_review_batch_ref(tmp_path):
    materials = tmp_path / "materials"
    materials.mkdir()
    batch = materials / "oss-real-batch"
    batch.mkdir()
    pdf = batch / "invoice-with-real-name.pdf"
    pdf.write_bytes(b"%PDF-1.4\nsynthetic invoice\n")
    workbook = batch / "employee-detail-real-name.xlsx"
    _write_workbook(workbook)

    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    (manifest_dir / "oss_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "materials_root": str(materials),
                "batches": [
                    {
                        "batch_key": "oss-real-batch",
                        "supplier_ref": "abc123def456",
                        "files": [
                            {
                                "relative_path": "oss-real-batch/invoice-with-real-name.pdf",
                                "file_type": "invoice_pdf",
                                "sha256": sha256_file(pdf),
                            },
                            {
                                "relative_path": "oss-real-batch/employee-detail-real-name.xlsx",
                                "file_type": "workbook",
                                "sha256": sha256_file(workbook),
                            },
                        ],
                        "expected_result": {"review_status": "needs_business_review"},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    handoff_dir = tmp_path / "handoff"
    build_golden_review_handoff(manifest_dir, handoff_dir, materials_root=materials)
    template_path = handoff_dir / "business_review_template.json"
    template = json.loads(template_path.read_text(encoding="utf-8"))
    item = template["review_items"][0]
    assert "batch_key" not in item
    item.update(
        {
            "review_status": "approved",
            "reviewer": "business-reviewer",
            "reviewed_at": "2026-06-20",
            "evidence_reference": "review-note-001",
            "expected_metrics": {
                "invoice_total": 100.0,
                "excel_total": 100.0,
                "warehouse_count": 1,
                "employee_count": 1,
                "total_hours": 8.0,
                "difference_category_counts": {},
                "manual_review_count": 0,
                "core_error_types": [],
            },
        }
    )
    template_path.write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")

    result = apply_golden_review_template(
        manifest_dir,
        template_path,
        tmp_path / "reviewed",
        materials_root=materials,
        require_approved=True,
        review_batch_ref=item["review_batch_ref"],
    )

    assert result["ok"] is True
    assert result["review_batch_ref"] == item["review_batch_ref"]
    assert result["summary"]["updated_manifest_count"] == 1
    reviewed = json.loads((tmp_path / "reviewed" / "oss_manifest.json").read_text(encoding="utf-8"))
    assert reviewed["batches"][0]["expected_result"]["review_status"] == "approved"


def test_scan_golden_handoff_privacy_rejects_paths_file_names_and_employee_ids(tmp_path):
    handoff_dir = tmp_path / "handoff"
    handoff_dir.mkdir()
    (handoff_dir / "business_review_template.json").write_text(
        json.dumps(
            {
                "leak_path": "/Users/zt27532/Documents/报账核对工具/oss/invoice.pdf",
                "leak_file": "employee-detail-real-name.xlsx",
                "leak_employee": "EUS034858",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = scan_golden_handoff_privacy(
        handoff_dir,
        materials_root="/Users/zt27532/Documents/报账核对工具",
        forbidden_terms=["employee-detail-real-name.xlsx"],
    )

    assert result["ok"] is False
    assert result["summary"]["issue_count"] >= 3
    codes = {issue["code"] for issue in result["issues"]}
    assert "materials_root_path_leak" in codes
    assert "forbidden_term_leak" in codes
    assert "employee_id_like_value" in codes


def test_build_golden_review_handoff_can_filter_to_one_batch(tmp_path):
    materials = tmp_path / "materials"
    materials.mkdir()
    oss = materials / "oss"
    oss.mkdir()
    fairway = materials / "fairway"
    fairway.mkdir()
    oss_pdf = oss / "invoice.pdf"
    oss_pdf.write_bytes(b"%PDF-1.4\nsynthetic invoice\n")
    fairway_pdf = fairway / "invoice.pdf"
    fairway_pdf.write_bytes(b"%PDF-1.4\nsynthetic invoice\n")

    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    (manifest_dir / "mixed_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "materials_root": str(materials),
                "batches": [
                    {
                        "batch_key": "oss",
                        "supplier_ref": "oss-ref",
                        "period_hint": "2026-05-18~2026-05-24",
                        "files": [
                            {
                                "relative_path": "oss/invoice.pdf",
                                "file_type": "invoice_pdf",
                                "sha256": sha256_file(oss_pdf),
                            }
                        ],
                        "expected_result": {"review_status": "approved"},
                    },
                    {
                        "batch_key": "fairway",
                        "supplier_ref": "fairway-ref",
                        "period_hint": "2026-05-18~2026-05-24",
                        "files": [
                            {
                                "relative_path": "fairway/invoice.pdf",
                                "file_type": "invoice_pdf",
                                "sha256": sha256_file(fairway_pdf),
                            }
                        ],
                        "expected_result": {"review_status": "needs_business_review"},
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    output_dir = tmp_path / "handoff"

    handoff = build_golden_review_handoff(
        manifest_dir,
        output_dir,
        materials_root=materials,
        batch_key="fairway",
    )
    template = json.loads((output_dir / "business_review_template.json").read_text(encoding="utf-8"))

    assert handoff["summary"]["batch_count"] == 1
    assert handoff["summary"]["needs_business_review_count"] == 1
    expected_supplier_ref = hashlib.sha256("fairway-ref".encode("utf-8")).hexdigest()[:12]
    expected_ref = hashlib.sha256("fairway-ref:fairway".encode("utf-8")).hexdigest()[:12]
    assert [item["review_batch_ref"] for item in template["review_items"]] == [f"batch_{expected_supplier_ref}_{expected_ref}"]
    assert "batch_key" not in template["review_items"][0]
    assert "supplier_ref" not in template["review_items"][0]
    assert "fairway" not in json.dumps(template, ensure_ascii=False)


def test_validate_golden_review_template_accepts_complete_approved_item(tmp_path):
    template = {
        "schema_version": 1,
        "review_items": [
            {
                "batch_key": "oss",
                "review_status": "approved",
                "reviewer": "business-reviewer",
                "reviewed_at": "2026-06-19T10:00:00Z",
                "evidence_reference": "approved invoice and bill workbook",
                "expected_metrics": {
                    "invoice_total": 100.0,
                    "excel_total": 100.0,
                    "warehouse_count": 1,
                    "employee_count": 1,
                    "total_hours": 8.0,
                    "difference_category_counts": {},
                    "manual_review_count": 0,
                    "core_error_types": [],
                },
            }
        ],
    }

    result = validate_golden_review_template(template, require_approved=True)

    assert result["ok"] is True
    assert result["summary"] == {
        "review_item_count": 1,
        "approved_count": 1,
        "error_count": 0,
        "warning_count": 0,
    }
    assert result["items"][0]["errors"] == []


def test_validate_golden_review_template_rejects_incomplete_approved_item(tmp_path):
    template = {
        "schema_version": 1,
        "review_items": [
            {
                "batch_key": "workforce",
                "review_status": "approved",
                "reviewer": "",
                "reviewed_at": "",
                "evidence_reference": "",
                "expected_metrics": {
                    "invoice_total": "100.00",
                    "excel_total": 100.0,
                    "warehouse_count": 1,
                    "employee_count": 1,
                    "total_hours": 8.0,
                    "difference_category_counts": {},
                    "manual_review_count": 0,
                    "core_error_types": [],
                },
            }
        ],
    }

    result = validate_golden_review_template(template, require_approved=True)

    assert result["ok"] is False
    codes = {error["code"] for error in result["items"][0]["errors"]}
    assert "missing_reviewer" in codes
    assert "missing_reviewed_at" in codes
    assert "missing_evidence_reference" in codes
    assert "invalid_expected_metric_type" in codes


def test_validate_golden_review_template_can_filter_to_one_batch(tmp_path):
    template = {
        "schema_version": 1,
        "review_items": [
            {
                "batch_key": "oss",
                "review_status": "approved",
                "reviewer": "business-reviewer",
                "reviewed_at": "2026-06-19T10:00:00Z",
                "evidence_reference": "approved invoice and bill workbook",
                "expected_metrics": {
                    "invoice_total": 100.0,
                    "excel_total": 100.0,
                    "warehouse_count": 1,
                    "employee_count": 1,
                    "total_hours": 8.0,
                    "difference_category_counts": {},
                    "manual_review_count": 0,
                    "core_error_types": [],
                },
            },
            {
                "batch_key": "fairway",
                "review_status": "needs_business_review",
                "expected_metrics": {},
            },
        ],
    }

    result = validate_golden_review_template(template, require_approved=True, batch_key="oss")

    assert result["ok"] is True
    assert result["summary"] == {
        "review_item_count": 1,
        "approved_count": 1,
        "error_count": 0,
        "warning_count": 0,
    }
    assert [item["batch_key"] for item in result["items"]] == ["oss"]


def test_validate_golden_review_template_can_filter_to_one_redacted_review_batch_ref(tmp_path):
    template = {
        "schema_version": 1,
        "review_items": [
            {
                "review_batch_ref": "batch_safe_oss",
                "review_status": "approved",
                "reviewer": "business-reviewer",
                "reviewed_at": "2026-06-19T10:00:00Z",
                "evidence_reference": "approved invoice and bill workbook",
                "expected_metrics": {
                    "invoice_total": 100.0,
                    "excel_total": 100.0,
                    "warehouse_count": 1,
                    "employee_count": 1,
                    "total_hours": 8.0,
                    "difference_category_counts": {},
                    "manual_review_count": 0,
                    "core_error_types": [],
                },
            },
            {
                "review_batch_ref": "batch_safe_fairway",
                "review_status": "needs_business_review",
                "expected_metrics": {},
            },
        ],
    }

    result = validate_golden_review_template(
        template,
        require_approved=True,
        review_batch_ref="batch_safe_oss",
    )

    assert result["ok"] is True
    assert result["summary"] == {
        "review_item_count": 1,
        "approved_count": 1,
        "error_count": 0,
        "warning_count": 0,
    }
    assert [item["review_batch_ref"] for item in result["items"]] == ["batch_safe_oss"]


def test_validate_golden_review_template_rejects_missing_batch_filter(tmp_path):
    template = {
        "schema_version": 1,
        "review_items": [
            {
                "batch_key": "oss",
                "review_status": "approved",
                "reviewer": "business-reviewer",
                "reviewed_at": "2026-06-19T10:00:00Z",
                "evidence_reference": "approved invoice and bill workbook",
                "expected_metrics": {
                    "invoice_total": 100.0,
                    "excel_total": 100.0,
                    "warehouse_count": 1,
                    "employee_count": 1,
                    "total_hours": 8.0,
                    "difference_category_counts": {},
                    "manual_review_count": 0,
                    "core_error_types": [],
                },
            }
        ],
    }

    result = validate_golden_review_template(template, require_approved=True, batch_key="missing")

    assert result["ok"] is False
    assert result["summary"]["review_item_count"] == 0
    assert result["summary"]["error_count"] == 1
    assert result["errors"] == [
        {
            "code": "batch_key_not_found",
            "batch_key": "missing",
            "message": "batch_key was not found in review_items",
        }
    ]


def test_validate_golden_review_template_rejects_missing_redacted_review_batch_ref(tmp_path):
    template = {
        "schema_version": 1,
        "review_items": [
            {
                "review_batch_ref": "batch_safe_oss",
                "review_status": "approved",
                "reviewer": "business-reviewer",
                "reviewed_at": "2026-06-19T10:00:00Z",
                "evidence_reference": "approved invoice and bill workbook",
                "expected_metrics": {
                    "invoice_total": 100.0,
                    "excel_total": 100.0,
                    "warehouse_count": 1,
                    "employee_count": 1,
                    "total_hours": 8.0,
                    "difference_category_counts": {},
                    "manual_review_count": 0,
                    "core_error_types": [],
                },
            }
        ],
    }

    result = validate_golden_review_template(
        template,
        require_approved=True,
        review_batch_ref="batch_missing",
    )

    assert result["ok"] is False
    assert result["summary"]["review_item_count"] == 0
    assert result["summary"]["error_count"] == 1
    assert result["errors"] == [
        {
            "code": "review_batch_ref_not_found",
            "review_batch_ref": "batch_missing",
            "message": "review_batch_ref was not found in review_items",
        }
    ]
