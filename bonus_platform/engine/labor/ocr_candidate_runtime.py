from __future__ import annotations

import json
import shlex
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from .models import LaborLineItem, line_items_from_dicts
from .ocr_name_gate import build_ocr_name_gate


def run_ocr_candidate_command(
    pdf_paths: list[Path],
    *,
    command: str,
    supplier: str = "",
    period_start: str = "",
    period_end: str = "",
    currency: str = "",
    timeout_seconds: int = 900,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    manifest = {
        "schemaVersion": 1,
        "taskType": "overseas_labor_ocr_candidate",
        "pdfFiles": [str(path.expanduser().resolve()) for path in pdf_paths],
        "supplier": supplier,
        "periodStart": period_start,
        "periodEnd": period_end,
        "currency": currency,
        "candidateOnly": True,
    }
    if not str(command or "").strip():
        return {
            "status": "unavailable",
            "rows": [],
            "files": [],
            "error": "OCR command is not configured",
            "manifest": manifest,
        }
    with tempfile.TemporaryDirectory(prefix="labor-ocr-task-") as temporary_dir:
        manifest_path = Path(temporary_dir) / "input.json"
        output_path = Path(temporary_dir) / "output.json"
        progress_path = Path(temporary_dir) / "progress.json"
        manifest["progressFile"] = str(progress_path)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        argv = [
            *shlex.split(command),
            "--input-manifest",
            str(manifest_path),
            "--output-json",
            str(output_path),
        ]
        try:
            process = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except OSError as exc:
            return {
                "status": "failed",
                "rows": [],
                "files": [],
                "error": f"{type(exc).__name__}: {exc}",
                "manifest": manifest,
            }
        deadline = time.monotonic() + max(int(timeout_seconds), 1)
        last_progress = ""
        timed_out = False
        while process.poll() is None:
            if progress_path.exists():
                try:
                    progress_text = progress_path.read_text(encoding="utf-8")
                    if progress_text != last_progress:
                        progress_payload = json.loads(progress_text)
                        if isinstance(progress_payload, dict):
                            last_progress = progress_text
                            if progress_callback is not None:
                                try:
                                    progress_callback(progress_payload)
                                except Exception:
                                    pass
                except (OSError, json.JSONDecodeError):
                    pass
            if time.monotonic() >= deadline:
                timed_out = True
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                break
            time.sleep(0.05)
        stdout, stderr = process.communicate()
        if progress_path.exists():
            try:
                progress_text = progress_path.read_text(encoding="utf-8")
                if progress_text != last_progress and progress_callback is not None:
                    progress_payload = json.loads(progress_text)
                    if isinstance(progress_payload, dict):
                        progress_callback(progress_payload)
            except (OSError, json.JSONDecodeError):
                pass
        if timed_out:
            return {
                "status": "failed",
                "rows": [],
                "files": [],
                "error": f"OCR worker timed out after {max(int(timeout_seconds), 1)} seconds",
                "manifest": manifest,
            }
        if process.returncode != 0 or not output_path.exists():
            error = (stderr or stdout or "OCR worker returned no output").strip()
            return {
                "status": "failed",
                "rows": [],
                "files": [],
                "error": error[-2000:],
                "manifest": manifest,
            }
        try:
            payload = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {
                "status": "failed",
                "rows": [],
                "files": [],
                "error": f"invalid OCR worker output: {exc}",
                "manifest": manifest,
            }
        return {
            **payload,
            "status": str(payload.get("status") or "completed"),
            "rows": payload.get("rows") if isinstance(payload.get("rows"), list) else [],
            "files": payload.get("files") if isinstance(payload.get("files"), list) else [],
            "manifest": manifest,
        }


def evaluate_ocr_candidate_result(
    result: dict[str, Any],
    excel_rows: list[LaborLineItem],
    expected_totals: dict[str, float],
    *,
    amount_tolerance: float,
    hours_tolerance: float = 0.10,
) -> dict[str, Any]:
    candidate_items = line_items_from_dicts(result.get("rows") or [])
    amount_by_source: dict[str, float] = {}
    for item in candidate_items:
        amount_by_source[item.source_file] = round(amount_by_source.get(item.source_file, 0.0) + item.amount, 2)
    file_closure = []
    for source_file, actual_amount in sorted(amount_by_source.items()):
        expected = expected_totals.get(source_file)
        delta = round(actual_amount - float(expected or 0), 2)
        file_closure.append(
            {
                "sourceFile": source_file,
                "candidateAmount": actual_amount,
                "expectedAmount": round(float(expected or 0), 2),
                "delta": delta,
                "closed": expected is not None and abs(delta) <= amount_tolerance,
            }
        )
    name_gate = build_ocr_name_gate(
        candidate_items,
        excel_rows,
        amount_tolerance=amount_tolerance,
        hours_tolerance=hours_tolerance,
    )
    failed_pages = sum(int(item.get("failedPageCount") or 0) for item in result.get("files", []))
    blockers = []
    if result.get("status") != "completed" or failed_pages:
        blockers.append("ocr_pages_incomplete")
    if not candidate_items:
        blockers.append("no_candidate_rows")
    if len(file_closure) != len(expected_totals) or any(not item["closed"] for item in file_closure):
        blockers.append("candidate_amount_not_closed")
    if int(name_gate["summary"].get("review") or 0) or int(name_gate["summary"].get("unmatched") or 0):
        blockers.append("strict_name_review_required")
    safe_to_use = not blockers
    return {
        "decision": "auto_accept" if safe_to_use else "needs_review",
        "safeToUse": safe_to_use,
        "candidateOnly": True,
        "blockers": blockers,
        "summary": {
            "candidateRowCount": len(candidate_items),
            "candidateAmountTotal": round(sum(item.amount for item in candidate_items), 2),
            "expectedFileCount": len(expected_totals),
            "closedFileCount": sum(bool(item["closed"]) for item in file_closure),
            "failedPageCount": failed_pages,
        },
        "fileClosure": file_closure,
        "nameGate": name_gate,
        "rows": [item.to_dict() for item in candidate_items],
    }
