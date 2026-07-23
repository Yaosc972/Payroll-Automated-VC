from tools.labor_ocr_row_closure import build_row_closure_report


def test_build_row_closure_report_marks_amounts_within_tolerance_closed():
    ocr_report = {
        "results": [
            {
                "backend": "rapidocr",
                "file": "invoice.pdf",
                "pages": [
                    {
                        "page": 1,
                        "visualText": (
                            "LAST NAME FIRST NAME REGULAR HRS BILL RATE AMOUNT\n"
                            "JANE DOE 8.00 10.00 80.00"
                        ),
                    }
                ],
            }
        ]
    }

    report = build_row_closure_report(ocr_report, {"invoice.pdf": 80.01}, tolerance=0.10)

    assert report["summary"] == {
        "evaluatedFileCount": 1,
        "closedFileCount": 1,
        "closureRate": 1.0,
        "tolerance": 0.1,
    }
    assert report["files"][0]["rowCount"] == 1
    assert report["files"][0]["detailAmount"] == 80.0
    assert report["files"][0]["delta"] == -0.01
    assert report["files"][0]["closed"] is True
