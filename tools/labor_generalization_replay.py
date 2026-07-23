#!/usr/bin/env python3
"""Replay synthetic labor fixtures through the formal HTTP API."""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any

import httpx


TERMINAL_STATUSES = {
    "已生成差异报告",
    "部分核对完成",
    "待图片识别复核",
    "PDF识别未完成",
    "待币种确认",
    "抽取失败",
}


class RequestsTransport:
    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = httpx.Client(trust_env=False)
        self._formal_headers: dict[str, str] | None = None

    def _client_contract_headers(self) -> dict[str, str]:
        if self._formal_headers is not None:
            return self._formal_headers
        response = self.session.get(f"{self.base_url}/api/labor/access", timeout=self.timeout)
        response.raise_for_status()
        access = response.json()
        headers = {
            "x-sigma-labor-api-contract": str(access.get("apiContractVersion") or ""),
            "x-sigma-labor-ui-version": str(access.get("version") or ""),
            "x-sigma-labor-ui-build": str(access.get("buildId") or ""),
        }
        if not all(headers.values()):
            raise RuntimeError("海外劳务 access 未返回完整页面/API/build 契约。")
        self._formal_headers = headers
        return headers

    def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.session.post(
            f"{self.base_url}{path}",
            json=payload,
            headers=self._client_contract_headers(),
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def post_files(self, path: str, pdf_path: Path, workbook_path: Path) -> dict[str, Any]:
        with pdf_path.open("rb") as pdf_file, workbook_path.open("rb") as workbook_file:
            response = self.session.post(
                f"{self.base_url}{path}",
                headers=self._client_contract_headers(),
                files=[
                    ("pdf_files", (pdf_path.name, pdf_file, "application/pdf")),
                    (
                        "workbook_files",
                        (workbook_path.name, workbook_file, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                    ),
                ],
                timeout=self.timeout,
            )
        response.raise_for_status()
        return response.json()

    def get_json(self, path: str) -> dict[str, Any]:
        response = self.session.get(f"{self.base_url}{path}", timeout=self.timeout)
        response.raise_for_status()
        return response.json()


def _write_results(path: Path | None, results: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_results(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _selected_pages(metadata: dict[str, Any]) -> list[int]:
    pages: set[int] = set()
    for row in metadata.get("pdfExtractedRows") or []:
        location = str(row.get("source_page_or_row") or row.get("sourcePageOrRow") or "")
        match = re.search(r"(?:page|p)\s*(\d+)", location, re.IGNORECASE)
        if match:
            pages.add(int(match.group(1)))
        elif location.strip().isdigit():
            pages.add(int(location.strip()))
    return sorted(pages)


def _result_from_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    comparison = metadata.get("comparisonSummary") if isinstance(metadata.get("comparisonSummary"), dict) else {}
    return {
        "runId": metadata.get("id"),
        "status": metadata.get("status"),
        "selectedInvoicePages": _selected_pages(metadata),
        "extractedRows": metadata.get("pdfExtractedRows") or [],
        "canRelease": bool(comparison.get("canRelease")),
        "requiresHumanReview": bool(metadata.get("requiresHumanReview")),
        "errorMessage": metadata.get("errorMessage") or "",
        "diffDownloadUrl": metadata.get("diffDownloadUrl") or "",
        "businessReportDownloadUrl": metadata.get("businessReportDownloadUrl") or "",
    }


def _poll_run(
    transport: Any,
    run_id: str,
    *,
    poll_interval: float,
    poll_timeout: float,
) -> dict[str, Any] | None:
    deadline = time.monotonic() + poll_timeout
    while time.monotonic() <= deadline:
        try:
            metadata = transport.get_json(f"/api/labor/runs/{run_id}")
        except (TimeoutError, httpx.TimeoutException):
            if poll_interval:
                time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))
            continue
        status = str(metadata.get("status") or "")
        async_status = str((metadata.get("asyncTask") or {}).get("status") or "")
        if status in TERMINAL_STATUSES or (status and status != "抽取中" and async_status not in {"queued", "running"}):
            return metadata
        if poll_interval:
            time.sleep(poll_interval)
    return None


def replay_fixture_set(
    base_url: str,
    fixture_dir: Path,
    truth_path: Path,
    *,
    results_path: Path | None = None,
    transport: Any | None = None,
    poll_interval: float = 2.0,
    poll_timeout: float = 900.0,
) -> dict[str, Any]:
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    results = _load_results(results_path)
    transport = transport or RequestsTransport(base_url)
    for case in truth.get("cases") or []:
        scenario_id = str(case["id"])
        previous = results.get(scenario_id) if isinstance(results.get(scenario_id), dict) else {}
        run_id = str(previous.get("runId") or "")
        if not run_id:
            created = transport.post_json(
                "/api/labor/runs",
                {
                    "supplier_name": f"Unknown Synthetic {scenario_id}",
                    "period_start": "2026-06-01",
                    "period_end": "2026-06-07",
                    "currency": case.get("currency") or "USD",
                    "notes": f"generalization:{scenario_id}",
                    "require_employee_detail": True,
                },
            )
            run_id = str(created["id"])
            results[scenario_id] = {"runId": run_id, "status": "created"}
            _write_results(results_path, results)
            transport.post_files(
                f"/api/labor/runs/{run_id}/files",
                fixture_dir / str(case["pdfFile"]),
                fixture_dir / str(case["workbookFile"]),
            )
            transport.post_json(
                f"/api/labor/runs/{run_id}/mapping",
                {
                    "sheet_name": "Employee Billing",
                    "mapping": {
                        "employeeId": "Employee ID",
                        "name": "Name",
                        "hours": "Hours",
                        "amount": case.get("amountColumn") or "Amount",
                        "currency": "Currency",
                    },
                },
            )
            transport.post_json(f"/api/labor/runs/{run_id}/extract-and-compare", {})
            results[scenario_id] = {"runId": run_id, "status": "polling"}
            _write_results(results_path, results)
        metadata = _poll_run(
            transport,
            run_id,
            poll_interval=poll_interval,
            poll_timeout=poll_timeout,
        )
        if metadata is None:
            results[scenario_id] = {"runId": run_id, "status": "poll_timeout"}
        else:
            results[scenario_id] = _result_from_metadata(metadata)
        _write_results(results_path, results)
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--fixture-dir", type=Path, required=True)
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--poll-timeout", type=float, default=900.0)
    args = parser.parse_args()
    replay_fixture_set(
        args.base_url,
        args.fixture_dir,
        args.truth,
        results_path=args.results,
        poll_timeout=args.poll_timeout,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
