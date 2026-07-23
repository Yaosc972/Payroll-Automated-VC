import hashlib
import json

import pytest

from bonus_platform.engine.labor.release_gate import (
    evaluate_release_case,
    load_release_cases,
    validate_release_case,
)


def _case(file_hash: str) -> dict:
    return {
        "schemaVersion": 1,
        "caseId": "legacy-invoice",
        "reviewStatus": "approved",
        "supplierName": "Legacy Supplier",
        "periodStart": "2026-05-25",
        "periodEnd": "2026-05-31",
        "currency": "EUR",
        "pdfFiles": [{"path": "invoice.pdf", "sha256": file_hash}],
        "workbooks": [
            {
                "path": "bill.xlsx",
                "sha256": file_hash,
                "sheetName": "Sheet2",
                "mapping": {"name": "员工", "hours": "工时", "amount": "金额"},
            }
        ],
        "expected": {
            "presentation.summary.employeeCount": 6,
            "presentation.summary.reviewItemCount": 7,
            "comparisonSummary.amountDeltaTotal": 455.79,
        },
        "forbiddenEmployeeNames": ["site", "Gonesse"],
    }


def _result() -> dict:
    return {
        "presentation": {
            "schemaVersion": 1,
            "employeeRows": [
                {
                    "employeeName": f"Employee {index}",
                    "matchStatus": "金额差异",
                    "pdfAmountTotal": 100,
                    "excelAmountTotal": 90,
                    "amountDelta": 10,
                    "pdfHoursTotal": 8,
                    "excelHoursTotal": 8,
                    "hoursDelta": 0,
                }
                for index in range(1, 7)
            ],
            "candidateMatches": [{"pdfEmployeeName": "Employee 3 long", "excelEmployeeName": "Employee 3"}],
            "summary": {
                "employeeCount": 6,
                "differenceEmployeeCount": 6,
                "passedEmployeeCount": 0,
                "amountDiffEmployeeCount": 6,
                "hoursDiffEmployeeCount": 0,
                "notInInvoiceEmployeeCount": 0,
                "candidateMatchCount": 1,
                "reviewItemCount": 7,
                "amountImpact": 60,
                "hoursImpact": 0,
                "excelRecordCount": 6,
                "sourceComparisonRowCount": 6,
                "excludedNonEmployeeRowCount": 0,
            },
        },
        "comparisonSummary": {"amountDeltaTotal": 455.79},
    }


def test_release_case_validates_hashes_and_approved_expected_result(tmp_path):
    payload = b"same fixture bytes"
    digest = hashlib.sha256(payload).hexdigest()
    (tmp_path / "invoice.pdf").write_bytes(payload)
    (tmp_path / "bill.xlsx").write_bytes(payload)
    case = _case(digest)

    validation = validate_release_case(case, tmp_path)
    evaluation = evaluate_release_case(case, _result(), materials_root=tmp_path)

    assert validation["ok"] is True
    assert evaluation["ok"] is True
    assert evaluation["observed"]["presentation.summary.employeeCount"] == 6
    assert evaluation["observed"]["presentation.summary.reviewItemCount"] == 7


def test_release_case_blocks_hash_drift_result_drift_and_footer_employee(tmp_path):
    payload = b"actual fixture bytes"
    digest = hashlib.sha256(b"approved fixture bytes").hexdigest()
    (tmp_path / "invoice.pdf").write_bytes(payload)
    (tmp_path / "bill.xlsx").write_bytes(payload)
    case = _case(digest)
    result = _result()
    result["presentation"]["employeeRows"].append(
        {
            "employeeName": "site",
            "matchStatus": "Excel有PDF无",
            "pdfAmountTotal": 0,
            "excelAmountTotal": 1,
            "amountDelta": -1,
            "pdfHoursTotal": 0,
            "excelHoursTotal": 0,
            "hoursDelta": 0,
        }
    )
    result["presentation"]["summary"]["employeeCount"] = 7
    result["presentation"]["summary"]["differenceEmployeeCount"] = 7
    result["presentation"]["summary"]["reviewItemCount"] = 8
    result["presentation"]["summary"]["amountImpact"] = 61
    result["presentation"]["summary"]["sourceComparisonRowCount"] = 7

    evaluation = evaluate_release_case(case, result, materials_root=tmp_path)

    assert evaluation["ok"] is False
    error_codes = {error["code"] for error in evaluation["errors"]}
    assert "sha256_mismatch" in error_codes
    assert "expected_value_mismatch" in error_codes
    assert "forbidden_employee_name" in error_codes


def test_release_gate_requires_at_least_one_approved_case(tmp_path):
    with pytest.raises(ValueError, match="approved release case"):
        load_release_cases(tmp_path)

    (tmp_path / "draft.json").write_text(
        json.dumps({"schemaVersion": 1, "caseId": "draft", "reviewStatus": "provisional"}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="approved release case"):
        load_release_cases(tmp_path)
