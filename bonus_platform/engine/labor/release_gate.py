from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping

from .presentation import validate_labor_presentation


RELEASE_CASE_SCHEMA_VERSION = 1
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_CASE_FIELDS = (
    "caseId",
    "supplierName",
    "periodStart",
    "periodEnd",
    "currency",
    "pdfFiles",
    "workbooks",
    "expected",
)


def load_release_cases(case_dir: str | Path) -> list[dict[str, Any]]:
    directory = Path(case_dir).expanduser()
    approved: list[dict[str, Any]] = []
    if directory.exists() and directory.is_dir():
        for path in sorted(directory.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"invalid release case {path.name}: {exc}") from exc
            if isinstance(payload, dict) and payload.get("reviewStatus") == "approved":
                approved.append({**payload, "_casePath": str(path)})
    if not approved:
        raise ValueError(f"at least one approved release case is required in {directory}")
    return approved


def validate_release_case(
    case: Mapping[str, Any],
    materials_root: str | Path | None = None,
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    if case.get("schemaVersion") != RELEASE_CASE_SCHEMA_VERSION:
        errors.append(
            {
                "code": "invalid_schema_version",
                "expected": RELEASE_CASE_SCHEMA_VERSION,
                "observed": case.get("schemaVersion"),
            }
        )
    if case.get("reviewStatus") != "approved":
        errors.append({"code": "case_not_approved", "observed": case.get("reviewStatus")})
    for field in REQUIRED_CASE_FIELDS:
        if case.get(field) in (None, "", [], {}):
            errors.append({"code": "missing_case_field", "field": field})

    root = resolve_release_materials_root(case, materials_root)
    if root is None:
        errors.append({"code": "missing_materials_root"})
    elif not root.exists() or not root.is_dir():
        errors.append({"code": "invalid_materials_root", "path": str(root)})
    else:
        for category in ("pdfFiles", "workbooks"):
            records = case.get(category) if isinstance(case.get(category), list) else []
            for index, record in enumerate(records):
                errors.extend(_validate_material_record(root, category, index, record))

    expected = case.get("expected") if isinstance(case.get("expected"), Mapping) else {}
    for path in expected:
        if not str(path).strip() or "." not in str(path):
            errors.append({"code": "invalid_expected_path", "path": str(path)})
    return {
        "ok": not errors,
        "caseId": str(case.get("caseId") or ""),
        "materialsRoot": str(root) if root else "",
        "errors": errors,
    }


def evaluate_release_case(
    case: Mapping[str, Any],
    result: Mapping[str, Any],
    *,
    materials_root: str | Path | None = None,
) -> dict[str, Any]:
    validation = validate_release_case(case, materials_root)
    errors = list(validation["errors"])
    presentation = result.get("presentation") if isinstance(result.get("presentation"), Mapping) else {}
    for message in validate_labor_presentation(presentation):
        errors.append({"code": "invalid_presentation_contract", "message": message})

    expected = case.get("expected") if isinstance(case.get("expected"), Mapping) else {}
    tolerance = _number(case.get("numericTolerance"), default=0.01)
    observed: dict[str, Any] = {}
    for dotted_path, expected_value in expected.items():
        path = str(dotted_path)
        actual_value, found = _dotted_value(result, path)
        observed[path] = actual_value if found else None
        if not found or not _expected_value_matches(expected_value, actual_value, tolerance):
            errors.append(
                {
                    "code": "expected_value_mismatch",
                    "path": path,
                    "expected": expected_value,
                    "observed": actual_value if found else None,
                }
            )

    forbidden = {
        _normalized_name(value)
        for value in (case.get("forbiddenEmployeeNames") or [])
        if _normalized_name(value)
    }
    employee_rows = presentation.get("employeeRows") if isinstance(presentation.get("employeeRows"), list) else []
    for row in employee_rows:
        if not isinstance(row, Mapping):
            continue
        employee_name = str(row.get("employeeName") or "")
        if _normalized_name(employee_name) in forbidden:
            errors.append(
                {
                    "code": "forbidden_employee_name",
                    "employeeName": employee_name,
                }
            )

    return {
        "ok": not errors,
        "caseId": str(case.get("caseId") or ""),
        "materialsRoot": validation["materialsRoot"],
        "observed": observed,
        "errors": errors,
    }


def resolve_release_materials_root(
    case: Mapping[str, Any],
    override: str | Path | None = None,
) -> Path | None:
    value = override if override not in (None, "") else case.get("materialsRoot")
    if value in (None, ""):
        return None
    return Path(str(value)).expanduser().resolve()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_material_record(
    root: Path,
    category: str,
    index: int,
    record: Any,
) -> list[dict[str, Any]]:
    if not isinstance(record, Mapping):
        return [{"code": "invalid_material_record", "category": category, "index": index}]
    errors: list[dict[str, Any]] = []
    relative_path = str(record.get("path") or "").strip()
    expected_hash = str(record.get("sha256") or "").strip().lower()
    if not relative_path:
        errors.append({"code": "missing_material_path", "category": category, "index": index})
        return errors
    if not SHA256_PATTERN.fullmatch(expected_hash):
        errors.append(
            {
                "code": "invalid_sha256",
                "category": category,
                "path": relative_path,
            }
        )
    material_path = (root / relative_path).resolve()
    try:
        material_path.relative_to(root)
    except ValueError:
        errors.append({"code": "material_path_escape", "category": category, "path": relative_path})
        return errors
    if not material_path.exists() or not material_path.is_file():
        errors.append({"code": "missing_material_file", "category": category, "path": relative_path})
        return errors
    if SHA256_PATTERN.fullmatch(expected_hash):
        observed_hash = sha256_file(material_path)
        if observed_hash != expected_hash:
            errors.append(
                {
                    "code": "sha256_mismatch",
                    "category": category,
                    "path": relative_path,
                    "expected": expected_hash,
                    "observed": observed_hash,
                }
            )
    if category == "workbooks":
        if not str(record.get("sheetName") or "").strip():
            errors.append({"code": "missing_workbook_sheet", "path": relative_path})
        mapping = record.get("mapping") if isinstance(record.get("mapping"), Mapping) else {}
        for field in ("name", "hours", "amount"):
            if not str(mapping.get(field) or "").strip():
                errors.append({"code": "missing_workbook_mapping", "path": relative_path, "field": field})
    return errors


def _dotted_value(payload: Mapping[str, Any], path: str) -> tuple[Any, bool]:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None, False
        current = current[part]
    return current, True


def _expected_value_matches(expected: Any, observed: Any, tolerance: float) -> bool:
    if (
        isinstance(expected, (int, float))
        and not isinstance(expected, bool)
        and isinstance(observed, (int, float))
        and not isinstance(observed, bool)
    ):
        return math.isclose(float(expected), float(observed), rel_tol=0.0, abs_tol=max(tolerance, 0.0))
    return expected == observed


def _normalized_name(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _number(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
