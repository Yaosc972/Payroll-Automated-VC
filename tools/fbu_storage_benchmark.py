#!/usr/bin/env python3
"""Compare legacy FBU monolith payloads with the split-storage read/write shape."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from time import perf_counter
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bonus_platform.engine.fbu_performance.persistent_storage import (  # noqa: E402
    build_fbu_run_manifest,
)
from bonus_platform.engine.fbu_performance.runs import (  # noqa: E402
    build_fbu_run_list_summary,
    build_final_result_rows,
)


DEFAULT_RUNS_FILE = PROJECT_ROOT / "outputs" / "fbu_performance_runs" / "runs.json"


def json_size(payload: Any) -> int:
    return len(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )


def pct_reduction(before: int, after: int) -> float:
    if before <= 0:
        return 0.0
    return round((1 - (after / before)) * 100, 2)


def benchmark(path: Path) -> dict[str, Any]:
    started = perf_counter()
    with path.open("r", encoding="utf-8") as handle:
        runs = json.load(handle)
    parse_ms = round((perf_counter() - started) * 1000, 2)
    if not isinstance(runs, list):
        raise ValueError("runs.json 顶层必须是数组")

    started = perf_counter()
    manifests = [build_fbu_run_manifest(run) for run in runs if isinstance(run, dict)]
    list_rows = [build_fbu_run_list_summary(manifest) for manifest in manifests]
    index_payload = {
        "schemaVersion": 2,
        "runs": manifests,
    }
    index_build_ms = round((perf_counter() - started) * 1000, 2)

    compact_legacy_bytes = json_size(runs)
    list_payload_bytes = json_size({"runs": list_rows})
    index_bytes = json_size(index_payload)
    largest_run = max(
        (run for run in runs if isinstance(run, dict)),
        key=json_size,
        default={},
    )
    largest_manifest = build_fbu_run_manifest(largest_run)
    core_detail = {
        **dict(largest_manifest.get("run") or {}),
        "loaded_sections": [],
    }
    full_detail_bytes = json_size(largest_run)
    core_detail_bytes = json_size(core_detail)

    results = largest_run.get("results") if isinstance(largest_run, dict) else []
    final_rows = build_final_result_rows(results) if isinstance(results, list) else []
    result_page_bytes = json_size({
        "results": final_rows[:50],
        "pagination": {
            "page": 1,
            "page_size": 50,
            "total": len(final_rows),
        },
    })

    largest_summary_bytes = json_size(largest_manifest)
    sample_incremental_section = {
        "rows": [{"employee_id": "benchmark", "amount": 1}],
        "summary": {"total_amount": 1},
    }
    local_incremental_write_bytes = (
        index_bytes
        + largest_summary_bytes
        + json_size(sample_incremental_section)
        + json_size([])
    )
    remote_incremental_write_bytes = (
        index_bytes
        + largest_summary_bytes
        + json_size(sample_incremental_section)
        + json_size([])
    )

    return {
        "source": str(path),
        "run_count": len(runs),
        "legacy": {
            "file_bytes": path.stat().st_size,
            "compact_all_runs_bytes": compact_legacy_bytes,
            "parse_ms": parse_ms,
            "largest_full_detail_bytes": full_detail_bytes,
        },
        "v2": {
            "index_bytes": index_bytes,
            "list_response_bytes": list_payload_bytes,
            "index_build_ms": index_build_ms,
            "largest_core_detail_bytes": core_detail_bytes,
            "result_page_50_bytes": result_page_bytes,
            "sample_incremental_write_bytes": local_incremental_write_bytes,
        },
        "comparison": {
            "list_payload_reduction_pct": pct_reduction(
                compact_legacy_bytes,
                list_payload_bytes,
            ),
            "core_detail_reduction_pct": pct_reduction(
                full_detail_bytes,
                core_detail_bytes,
            ),
            "local_small_save_reduction_pct": pct_reduction(
                path.stat().st_size,
                local_incremental_write_bytes,
            ),
            "remote_largest_run_save_reduction_pct": pct_reduction(
                full_detail_bytes,
                remote_incremental_write_bytes,
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-file", type=Path, default=DEFAULT_RUNS_FILE)
    args = parser.parse_args()
    if not args.runs_file.is_file():
        parser.error(f"文件不存在：{args.runs_file}")
    print(json.dumps(benchmark(args.runs_file), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
