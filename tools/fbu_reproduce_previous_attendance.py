"""Build the failed attendance RPC from a read-only exported activity snapshot."""
from __future__ import annotations

import argparse
import copy
import csv
import json
from pathlib import Path

from bonus_platform.app import _append_fbu_previous_attendance_context_to_preview
from bonus_platform.engine.fbu_performance.parser import build_hourly_rate_policy_data
from bonus_platform.engine.fbu_performance.postgres_state import _encode_section_for_storage
from bonus_platform.engine.fbu_performance.runs import build_attendance_view_data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("previous", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--probe-sql", type=Path)
    args = parser.parse_args()
    csv.field_size_limit(100_000_000)
    with args.snapshot.open(encoding="utf-8-sig", newline="") as source:
        snapshot = json.loads(next(csv.DictReader(source))["snapshot"])
    core = snapshot["core"]
    saved = snapshot["sections"]
    attendance = _append_fbu_previous_attendance_context_to_preview(
        copy.deepcopy(saved["attendance_data"]["data"]), args.previous,
        core["calc_month"], "7月考勤日报表-20260819.xlsx",
    )
    updates = {
        "attendance_data": attendance,
        "attendance_view_data": build_attendance_view_data(attendance),
        "hourly_rate_policy_data": build_hourly_rate_policy_data(
            attendance, core["calc_month"], saved["hourly_rate_policy_data"]["data"],
        ),
        "results": [],
        "results_view_data": {},
    }
    desired = {**core, "previous_attendance_file": "7月考勤日报表-20260819.xlsx",
               "status": "step1", "current_step": 1, "total_employees": 0,
               "total_bonus": 0, "match_rate": 0}
    payload = {
        "p_environment": "production", "p_run_id": core["run_id"],
        "p_expected_core_revision": snapshot["revision"], "p_seed_core": core,
        "p_core_data": desired,
        "p_sections": {key: {"data": _encode_section_for_storage(key, value),
                              "expected_revision": saved.get(key, {}).get("revision", 0),
                              "replace": key in {"attendance_data", "attendance_view_data", "results", "results_view_data"}}
                       for key, value in updates.items()},
    }
    args.output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    if args.probe_sql:
        original = saved["attendance_data"]["data"]
        additions = {}
        for old, new in zip(original["employees"], attendance["employees"], strict=True):
            rows = [row for row in new["attendance_daily_rows"] if row not in old["attendance_daily_rows"]]
            reconstructed = {**old, "attendance_daily_rows": sorted(old["attendance_daily_rows"] + rows, key=lambda row: str(row.get("date") or ""))} if rows else old
            assert reconstructed == new
            if rows:
                additions[new["employee_id"]] = rows
        delta = json.dumps({"additions": additions, "summary": attendance["summary"],
                            "hourly_rate_policy_data": updates["hourly_rate_policy_data"]},
                           ensure_ascii=False, separators=(",", ":"))
        assert "$fbu_delta$" not in delta
        sql = (Path(__file__).with_name("fbu_snapshot_timeout_probe.sql")).read_text()
        reconstruction = """
  payload := payload - 'supplemental_leave_data';
  payload := jsonb_set(payload, '{attendance_data,data,employees}', (
    select jsonb_agg(case when patch->'additions' ? (employee->>'employee_id')
      then jsonb_set(employee,'{attendance_daily_rows}',(
        select jsonb_agg(day order by day->>'date') from jsonb_array_elements(
          employee->'attendance_daily_rows' || (patch->'additions'->(employee->>'employee_id'))) as d(day)
      )) else employee end order by ordinal)
    from jsonb_array_elements(payload#>'{attendance_data,data,employees}') with ordinality as e(employee,ordinal)
  ));
  payload := jsonb_set(payload,'{attendance_data,data,summary}',patch->'summary');
  payload := jsonb_set(payload,'{attendance_view_data,data,summary}',patch->'summary');
  payload := jsonb_set(payload,'{hourly_rate_policy_data,data}',patch->'hourly_rate_policy_data');
"""
        sql = sql.replace("  baseline jsonb;", "  baseline jsonb;\n  patch jsonb;")
        sql = sql.replace("  definition := pg_get_functiondef", f"  patch := $fbu_delta${delta}$fbu_delta$::jsonb;\n{reconstruction}\n  definition := pg_get_functiondef")
        args.probe_sql.write_text(sql)
    print(json.dumps({"payload_bytes": args.output.stat().st_size,
                      "section_bytes": {key: len(json.dumps(value, ensure_ascii=False).encode()) for key, value in updates.items()},
                      "context": attendance.get("summary", {}).get("attendance_context", {})}, ensure_ascii=False))


if __name__ == "__main__":
    main()
