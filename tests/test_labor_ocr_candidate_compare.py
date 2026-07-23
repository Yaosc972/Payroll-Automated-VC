import subprocess
import sys
from pathlib import Path

from bonus_platform.engine.labor.ocr_candidate_adapter import OcrLine, OcrPageResult
from tools.labor_ocr_candidate_compare import summarize_candidate_run


def test_candidate_compare_cli_can_start_from_project_root():
    project_root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, "tools/labor_ocr_candidate_compare.py", "--help"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Compare candidate OCR engines" in completed.stdout


def test_summarize_candidate_run_counts_pages_and_business_signals():
    pages = [
        OcrPageResult(
            backend="rapidocr",
            page_number=1,
            lines=(
                OcrLine(
                    text="Employee Jane Doe Hours 8.00 Amount $80.00",
                    confidence=0.96,
                    polygon=(),
                ),
            ),
            duration_seconds=0.5,
        ),
        OcrPageResult(
            backend="rapidocr",
            page_number=2,
            lines=(),
            duration_seconds=0.3,
            error="image decode failed",
        ),
    ]

    summary = summarize_candidate_run("sample.pdf", "rapidocr", pages)

    assert summary["pageCount"] == 2
    assert summary["successfulPageCount"] == 1
    assert summary["failedPageCount"] == 1
    assert summary["durationSeconds"] == 0.8
    assert summary["signals"]["hasAmountSignal"] is True
    assert summary["signals"]["hasEmployeeNameSignal"] is True
    assert summary["signals"]["hasHoursSignal"] is True
    assert summary["errors"] == [{"page": 2, "error": "image decode failed"}]
    assert summary["pages"][0]["visualText"] == "Employee Jane Doe Hours 8.00 Amount $80.00"
    assert summary["pages"][0]["lines"][0]["confidence"] == 0.96
