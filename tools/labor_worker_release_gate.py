#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES_DIR = PROJECT_ROOT / "outputs" / "labor_golden" / "approved_cases"
DEFAULT_OUTPUT = PROJECT_ROOT / "outputs" / "labor_golden" / "worker_release_gate_latest.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run approved legacy invoice cases through the formal overseas-labor engine.",
    )
    parser.add_argument("--cases-dir", default=str(DEFAULT_CASES_DIR))
    parser.add_argument("--materials-root", default=os.environ.get("SIGMA_LABOR_GOLDEN_MATERIALS_ROOT", ""))
    parser.add_argument("--case-id", default="")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    return parser.parse_args()


def configure_isolated_runtime(runtime_root: Path) -> None:
    isolated = {
        "SIGMA_WORKBENCH_HOME": str(runtime_root),
        "SIGMA_LABOR_STORAGE_BACKEND": "local",
        "SIGMA_LABOR_STATE_BACKEND": "local",
        "SIGMA_LABOR_P1_REQUIRED": "0",
        "AI_ENABLED": "0",
        "SIGMA_LABOR_EXTERNAL_AI_ENABLED": "0",
        "AI_PROVIDER": "",
        "AI_API_KEY": "",
        "MIMO_API_KEY": "",
        "AI_BASE_URL": "",
        "AI_MODEL": "",
        "PARALLEL_EXTRACTION_ENABLED": "0",
        "SUPABASE_URL": "",
        "NEXT_PUBLIC_SUPABASE_URL": "",
        "SUPABASE_SERVICE_ROLE_KEY": "",
        "SUPABASE_STORAGE_SERVICE_ROLE_KEY": "",
        "VERCEL": "",
    }
    os.environ.update(isolated)


def run_formal_case(case: dict[str, Any], materials_root: Path) -> dict[str, Any]:
    from bonus_platform.engine.labor.runs import (
        attach_labor_file,
        create_labor_run,
        get_labor_run_dir,
        update_labor_metadata,
    )
    import bonus_platform.app as app_module

    run = create_labor_run(
        {
            "supplierName": str(case.get("supplierName") or ""),
            "periodStart": str(case.get("periodStart") or ""),
            "periodEnd": str(case.get("periodEnd") or ""),
            "currency": str(case.get("currency") or ""),
            "notes": f"worker release gate: {case.get('caseId', '')}",
            "requireEmployeeDetail": True,
            "reconciliationScope": "employee_detail_required",
            "ownerUserId": "worker-release-gate",
        }
    )
    run_dir = get_labor_run_dir(run["id"])
    pdf_records = []
    for index, record in enumerate(case.get("pdfFiles") or [], start=1):
        source = (materials_root / str(record["path"])).resolve()
        target = _copy_case_material(source, run_dir, index=index)
        pdf_records.append(attach_labor_file(run["id"], target, "PDF发票"))

    workbook_records = []
    workbook_mappings = []
    for index, record in enumerate(case.get("workbooks") or [], start=1):
        source = (materials_root / str(record["path"])).resolve()
        target = _copy_case_material(source, run_dir, index=index)
        workbook_records.append(attach_labor_file(run["id"], target, "Excel账单"))
        workbook_mappings.append(
            {
                "filename": target.name,
                "sheetName": str(record.get("sheetName") or ""),
                "mapping": dict(record.get("mapping") or {}),
            }
        )

    first_workbook = workbook_mappings[0]
    update_labor_metadata(
        run["id"],
        {
            "files": {"pdfInvoices": pdf_records, "workbooks": workbook_records},
            "workbookSheet": first_workbook["sheetName"],
            "excelMapping": first_workbook["mapping"],
            "workbookMappings": workbook_mappings,
            "materialReplaySource": {
                "batchKey": str(case.get("caseId") or ""),
                "source": "worker_release_gate",
            },
        },
    )
    return app_module._perform_labor_extract_compare(run["id"])


def _copy_case_material(source: Path, run_dir: Path, *, index: int) -> Path:
    target = run_dir / source.name
    if target.exists():
        target = run_dir / f"{index}_{source.name}"
    shutil.copy2(source, target)
    return target


def main() -> int:
    args = parse_args()
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    from bonus_platform.engine.labor.release_gate import (
        evaluate_release_case,
        load_release_cases,
        resolve_release_materials_root,
        validate_release_case,
    )

    output_path = Path(args.output).expanduser()
    try:
        cases = load_release_cases(Path(args.cases_dir).expanduser())
    except ValueError as exc:
        payload = _gate_payload([], [{"code": "release_cases_unavailable", "message": str(exc)}])
        _write_gate_output(output_path, payload)
        print(f"[FAIL] {exc}")
        return 1

    if args.case_id:
        cases = [case for case in cases if str(case.get("caseId") or "") == args.case_id]
        if not cases:
            message = f"approved release case not found: {args.case_id}"
            payload = _gate_payload([], [{"code": "release_case_not_found", "message": message}])
            _write_gate_output(output_path, payload)
            print(f"[FAIL] {message}")
            return 1

    evaluations: list[dict[str, Any]] = []
    gate_errors: list[dict[str, Any]] = []
    with TemporaryDirectory(prefix="sigma-labor-release-gate-") as runtime_dir:
        configure_isolated_runtime(Path(runtime_dir))
        for case in cases:
            root = resolve_release_materials_root(case, args.materials_root or None)
            validation = validate_release_case(case, root)
            if not validation["ok"] or root is None:
                evaluation = {
                    "ok": False,
                    "caseId": str(case.get("caseId") or ""),
                    "observed": {},
                    "errors": validation["errors"],
                }
            else:
                try:
                    result = run_formal_case(case, root)
                    evaluation = evaluate_release_case(case, result, materials_root=root)
                except Exception as exc:  # noqa: BLE001 - release gate must fail closed.
                    evaluation = {
                        "ok": False,
                        "caseId": str(case.get("caseId") or ""),
                        "observed": {},
                        "errors": [{"code": "formal_run_failed", "message": str(exc)}],
                    }
            evaluations.append(evaluation)
            label = "PASS" if evaluation["ok"] else "FAIL"
            print(f"[{label}] {evaluation['caseId']}")
            for error in evaluation.get("errors") or []:
                print(f"  - {error.get('code')}: {_error_message(error)}")

    payload = _gate_payload(evaluations, gate_errors)
    _write_gate_output(output_path, payload)
    print(f"Release gate: {'PASS' if payload['ok'] else 'FAIL'} ({output_path})")
    return 0 if payload["ok"] else 1


def _gate_payload(cases: list[dict[str, Any]], errors: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "ok": bool(cases) and not errors and all(case.get("ok") is True for case in cases),
        "runtimePolicy": {
            "storage": "temporary_local",
            "state": "temporary_local",
            "externalAi": False,
            "productionWrite": False,
        },
        "caseCount": len(cases),
        "cases": cases,
        "errors": errors,
    }


def _write_gate_output(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _error_message(error: dict[str, Any]) -> str:
    return str(error.get("message") or error.get("path") or error.get("field") or "release gate mismatch")


if __name__ == "__main__":
    raise SystemExit(main())
