import json
from pathlib import Path

from tools.labor_accuracy_baseline import build_report, evaluate_cases, inventory_materials


def test_inventory_materials_separates_text_and_image_pdfs(tmp_path, monkeypatch):
    group = tmp_path / "supplier-a"
    group.mkdir()
    text_pdf = group / "text.pdf"
    image_pdf = group / "image.pdf"
    workbook = group / "bill.xlsx"
    text_pdf.write_bytes(b"text")
    image_pdf.write_bytes(b"image")
    workbook.write_bytes(b"sheet")
    monkeypatch.setattr(
        "tools.labor_accuracy_baseline.classify_pdf",
        lambda path: {"filename": path.name, "textClass": "text_structured" if path == text_pdf else "image_or_empty", "textCharacterCount": 100 if path == text_pdf else 0, "parserError": ""},
    )

    result = inventory_materials(tmp_path)

    assert result["pdfCount"] == 2
    assert result["pdfTextClasses"] == {"text_structured": 1, "image_or_empty": 1}
    assert result["groups"][0]["workbookCount"] == 1


def test_evaluate_cases_checks_saved_run_metrics(tmp_path):
    run_dir = tmp_path / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    (run_dir / "metadata.json").write_text(
        json.dumps(
            {
                "status": "已生成差异报告",
                "comparisonSummary": {"pdfAmountTotal": 10.0, "excelAmountTotal": 9.0, "amountDeltaTotal": 1.0},
                "warehouseComparison": {"summary": {"pdfAmountTotal": 100.0, "excelAmountTotal": 90.0, "amountDeltaTotal": 10.0}},
                "batchGuard": {"status": "ok"},
                "reconciliationDiagnostics": {"signals": {"pdfDetailCoverage": {"coverageRatio": 1.0}}},
            }
        )
    )
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps({"cases": [{"name": "case", "materialGroup": "a", "runId": "run-1", "evidenceLevel": "reviewed", "expected": {"pdfAmountTotal": 100.0, "detailCoverageRatio": 1.0}}]}))

    result = evaluate_cases(cases, tmp_path / "runs")

    assert result[0]["passed"] is True
    assert result[0]["actual"]["employeeDetailPdfAmountTotal"] == 10.0
    assert "未经业务审核的历史批次只计覆盖率" in build_report({"groups": [], "fileCount": 0, "uniqueHashCount": 0, "duplicateCopyCount": 0, "pdfCount": 0, "pdfTextClasses": {}}, result)
