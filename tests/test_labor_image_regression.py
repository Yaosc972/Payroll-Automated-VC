import json

from tools.labor_image_regression import (
    build_markdown,
    evaluate_artifact_case,
    evaluate_cache_case,
    evaluate_cases,
    evaluate_run,
)


def test_evaluate_run_requires_each_covered_file_to_close():
    result = evaluate_run(
        {
            "id": "run-1",
            "invoiceEvidenceAudit": [
                {"source_file": "a.pdf", "total_amount": 100},
                {"source_file": "b.pdf", "total_amount": 200},
            ],
            "pdfExtractedRows": [
                {"source_file": "a.pdf", "amount": 100},
                {"source_file": "b.pdf", "amount": 150},
            ],
        }
    )

    assert result["detailCoverageRatio"] == 1.0
    assert result["amountClosureRatio"] == 0.5
    assert result["mismatches"][0]["sourceFile"] == "b.pdf"


def test_evaluate_cases_enforces_both_ninety_percent_gates(tmp_path):
    run_dir = tmp_path / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    (run_dir / "metadata.json").write_text(
        json.dumps(
            {
                "id": "run-1",
                "invoiceEvidenceAudit": [{"source_file": "a.pdf", "total_amount": 100}],
                "pdfExtractedRows": [{"source_file": "a.pdf", "amount": 99}],
            }
        )
    )
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps({"minimumRatio": 0.9, "cases": [{"name": "image", "materialGroup": "image", "runId": "run-1"}]}))

    result = evaluate_cases(cases, tmp_path / "runs")

    assert result["passed"] is False
    assert result["cases"][0]["detailCoverageRatio"] == 1.0
    assert result["cases"][0]["amountClosureRatio"] == 0.0
    assert "两项必须同时达标" in build_markdown(result)


def test_evaluate_cache_case_compares_legacy_page_rows_to_expected_totals(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "invoice-a_p1_model_v1.json").write_text(json.dumps([{"amount": "$60.00"}, {"amount": 40}]))
    (cache / "invoice-b_p1_model_v1.json").write_text(json.dumps([{"amount": 150}]))

    result = evaluate_cache_case(
        {"name": "legacy", "materialGroup": "legacy", "cacheDirectory": str(cache), "expectedTotals": {"invoice-a": 100, "invoice-b": 200}}
    )

    assert result["detailCoverageRatio"] == 1.0
    assert result["amountClosureRatio"] == 0.5


def test_evaluate_artifact_case_compares_current_page_rows_to_expected_totals(tmp_path):
    artifact = tmp_path / "current.json"
    artifact.write_text(
        json.dumps(
            {
                "invoice-a.pdf": {"rows": [{"source_file": "invoice-a.pdf", "amount": 60}, {"amount": 40}]},
                "invoice-b.pdf": {"rows": [{"amount": 200}]},
            }
        )
    )

    result = evaluate_artifact_case(
        {
            "name": "current",
            "materialGroup": "current",
            "artifactFile": str(artifact),
            "expectedTotals": {"invoice-a": 100, "invoice-b": 200},
        }
    )

    assert result["detailCoverageRatio"] == 1.0
    assert result["amountClosureRatio"] == 1.0
