from __future__ import annotations

import copy
import json
import os
import re
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


FBU_POSTGRES_RUNS_TABLE = "sigma_fbu_runs"
FBU_POSTGRES_SECTIONS_TABLE = "sigma_fbu_run_sections"
FBU_POSTGRES_JOBS_TABLE = "sigma_fbu_upload_jobs"
_AVAILABILITY_LOCK = threading.RLock()
_AVAILABILITY: tuple[float, bool] | None = None
_MISSING = object()


class FBUPostgresStateError(RuntimeError):
    def __init__(self, status_code: int, text: str):
        super().__init__(f"Supabase Data API returned HTTP {status_code}")
        self.status_code = status_code
        self.text = text


def _supabase_url() -> str:
    return (
        os.environ.get("SUPABASE_URL")
        or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
        or ""
    ).strip().rstrip("/")


def _supabase_token() -> str:
    return (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_STORAGE_SERVICE_ROLE_KEY")
        or ""
    ).strip()


def fbu_postgres_state_requested() -> bool:
    backend = str(os.environ.get("SIGMA_FBU_STATE_BACKEND") or "auto").strip().lower()
    if backend in {"storage", "json", "off", "disabled"}:
        return False
    if backend not in {"auto", "postgres", "database", "db"}:
        return False
    storage_backend = str(
        os.environ.get("SIGMA_FBU_STORAGE_BACKEND")
        or os.environ.get("SIGMA_LABOR_STORAGE_BACKEND")
        or ""
    ).strip().lower()
    return bool(_supabase_url() and _supabase_token() and storage_backend == "supabase")


def _environment() -> str:
    raw = (
        os.environ.get("SIGMA_FBU_STORAGE_ENV")
        or os.environ.get("SIGMA_LABOR_STORAGE_ENV")
        or os.environ.get("VERCEL_ENV")
        or "local"
    )
    value = re.sub(r"[^0-9A-Za-z_-]+", "-", raw.strip().lower()).strip("-_")
    return value or "local"


def _headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    token = _supabase_token()
    if not token:
        raise RuntimeError("缺少 SUPABASE_SERVICE_ROLE_KEY，无法读取 FBU 数据库状态。")
    headers = {
        "apikey": token,
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if extra:
        headers.update(extra)
    return headers


def _request_json(
    method: str,
    path: str,
    *,
    payload: Any = None,
    headers: dict[str, str] | None = None,
) -> Any:
    base = _supabase_url()
    if not base:
        raise RuntimeError("缺少 SUPABASE_URL，无法读取 FBU 数据库状态。")
    body = None if payload is None else json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    request = Request(
        f"{base}/rest/v1/{path.lstrip('/')}",
        data=body,
        method=method,
        headers=_headers(headers),
    )
    try:
        with urlopen(request, timeout=30) as response:
            content = response.read()
    except HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        raise FBUPostgresStateError(exc.code, text) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"读取 FBU 数据库状态失败：{exc}") from exc
    if not content:
        return None
    return json.loads(content.decode("utf-8"))


def _schema_missing(exc: FBUPostgresStateError) -> bool:
    text = str(exc.text or "")
    return exc.status_code in {404, 406} and any(
        marker in text
        for marker in (
            "PGRST202",
            "PGRST204",
            "PGRST205",
            "42P01",
            "sigma_fbu_",
            FBU_POSTGRES_RUNS_TABLE,
        )
    )


def _set_available(value: bool, ttl_seconds: float = 60.0) -> None:
    global _AVAILABILITY
    with _AVAILABILITY_LOCK:
        _AVAILABILITY = (time.monotonic() + ttl_seconds, value)


def _known_available() -> bool | None:
    with _AVAILABILITY_LOCK:
        if _AVAILABILITY is None:
            return None
        expires_at, value = _AVAILABILITY
        if expires_at <= time.monotonic():
            return None
        return value


def reset_fbu_postgres_state_availability() -> None:
    global _AVAILABILITY
    with _AVAILABILITY_LOCK:
        _AVAILABILITY = None


def _call(path: str, *, method: str = "GET", payload: Any = None, headers=None) -> Any:
    if not fbu_postgres_state_requested() or _known_available() is False:
        return None
    try:
        result = _request_json(method, path, payload=payload, headers=headers)
    except FBUPostgresStateError as exc:
        if _schema_missing(exc):
            _set_available(False)
            return None
        raise
    _set_available(True, ttl_seconds=300.0)
    return result


def _rpc(name: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    result = _call(f"rpc/{name}", method="POST", payload=payload)
    if isinstance(result, list) and len(result) == 1 and isinstance(result[0], dict):
        return result[0]
    return result if isinstance(result, dict) else None


def _identity_field(*row_sets: list[Any]) -> str:
    rows = [row for row_set in row_sets for row in row_set]
    if not rows or not all(isinstance(row, dict) for row in rows):
        return ""
    for field in ("row_id", "employee_id", "source_employee_id", "id", "key"):
        values_by_set = [
            [str(row.get(field) or "") for row in row_set]
            for row_set in row_sets
        ]
        if all(
            all(values) and len(values) == len(set(values))
            for values in values_by_set
            if values
        ):
            return field
    return ""


def _merge_keyed_list(base: list, desired: list, latest: list, identity: str) -> list:
    base_by_id = {str(row.get(identity)): row for row in base}
    desired_by_id = {str(row.get(identity)): row for row in desired}
    latest_by_id = {str(row.get(identity)): row for row in latest}
    output: list[Any] = []
    emitted: set[str] = set()

    for latest_row in latest:
        row_id = str(latest_row.get(identity))
        if row_id in base_by_id and row_id not in desired_by_id:
            continue
        if row_id in desired_by_id:
            if row_id in base_by_id:
                output.append(
                    merge_json_changes(
                        base_by_id[row_id],
                        desired_by_id[row_id],
                        latest_row,
                    )
                )
            else:
                output.append(copy.deepcopy(desired_by_id[row_id]))
            emitted.add(row_id)
        else:
            output.append(copy.deepcopy(latest_row))
            emitted.add(row_id)

    for desired_row in desired:
        row_id = str(desired_row.get(identity))
        if row_id in emitted:
            continue
        if row_id in base_by_id and row_id not in latest_by_id:
            output.append(copy.deepcopy(desired_row))
        elif row_id not in base_by_id:
            output.append(copy.deepcopy(desired_row))
        emitted.add(row_id)
    return output


def merge_json_changes(base: Any, desired: Any, latest: Any) -> Any:
    """Three-way merge: apply this request's delta without undoing other writers."""
    if desired == base:
        return copy.deepcopy(latest)
    if latest == base or desired == latest:
        return copy.deepcopy(desired)

    if isinstance(base, dict) and isinstance(desired, dict) and isinstance(latest, dict):
        output = copy.deepcopy(latest)
        for key in set(base).union(desired):
            base_value = base.get(key, _MISSING)
            desired_value = desired.get(key, _MISSING)
            latest_value = latest.get(key, _MISSING)
            if desired_value is _MISSING:
                if base_value is not _MISSING:
                    output.pop(key, None)
                continue
            if base_value is _MISSING:
                output[key] = copy.deepcopy(desired_value)
                continue
            if latest_value is _MISSING:
                latest_value = base_value
            output[key] = merge_json_changes(base_value, desired_value, latest_value)
        return output

    if isinstance(base, list) and isinstance(desired, list) and isinstance(latest, list):
        identity = _identity_field(base, desired, latest)
        if identity:
            return _merge_keyed_list(base, desired, latest, identity)
    return copy.deepcopy(desired)


def _normalize_section(section_name: str, data: Any) -> Any:
    if section_name != "supplemental_leave_data" or not isinstance(data, dict):
        return data
    rows = data.get("rows")
    if not isinstance(rows, list):
        return data
    summary = dict(data.get("summary") or {})
    def number(value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    include_rows = [row for row in rows if isinstance(row, dict) and row.get("include_in_base")]
    summary.update({
        "total_rows": len(rows),
        "include_count": len(include_rows),
        "include_hours": round(sum(number(row.get("included_hours")) for row in include_rows), 2),
        "pending_count": sum(isinstance(row, dict) and row.get("confirmation_status") == "pending" for row in rows),
        "confirmed_count": sum(isinstance(row, dict) and row.get("confirmation_status") == "confirmed" for row in rows),
        "excluded_count": sum(isinstance(row, dict) and row.get("confirmation_status") == "excluded" for row in rows),
    })
    return {**data, "summary": summary}


def commit_core(run_id: str, *, seed: dict, patch: dict) -> dict[str, Any] | None:
    return _rpc("sigma_fbu_commit_core", {
        "p_environment": _environment(),
        "p_run_id": run_id,
        "p_seed": seed,
        "p_patch": patch,
    })


def _core_step(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _merge_core_after_conflict(base: dict, desired: dict, latest: dict) -> dict:
    merged = merge_json_changes(base, desired, latest)
    base_step = _core_step(base.get("current_step"))
    desired_step = _core_step(desired.get("current_step"))
    latest_step = _core_step(latest.get("current_step"))
    if desired_step != base_step and latest_step != base_step and desired_step < latest_step:
        merged["current_step"] = latest.get("current_step")
        merged["status"] = latest.get("status")
    return merged


def save_core_with_retry(
    run_id: str,
    *,
    base: dict[str, Any],
    desired: dict[str, Any],
    expected_revision: int,
    max_attempts: int = 4,
) -> dict[str, Any] | None:
    candidate = copy.deepcopy(desired)
    merge_base = copy.deepcopy(base)
    revision = int(expected_revision or 0)
    for _ in range(max_attempts):
        result = _rpc("sigma_fbu_cas_core", {
            "p_environment": _environment(),
            "p_run_id": run_id,
            "p_expected_revision": revision,
            "p_seed": base,
            "p_data": candidate,
        })
        if result is None:
            return None
        if result.get("applied"):
            return result
        latest = dict(result.get("data") or {})
        revision = int(result.get("revision") or 0)
        candidate = _merge_core_after_conflict(merge_base, desired, latest)
        merge_base = latest
    raise RuntimeError("FBU 活动核心状态并发更新冲突")


def replace_section(run_id: str, section_name: str, data: Any) -> dict[str, Any] | None:
    return _rpc("sigma_fbu_replace_section", {
        "p_environment": _environment(),
        "p_run_id": run_id,
        "p_section_name": section_name,
        "p_data": data,
    })


def save_section_with_retry(
    run_id: str,
    section_name: str,
    *,
    base: Any,
    desired: Any,
    expected_revision: int,
    max_attempts: int = 4,
) -> dict[str, Any] | None:
    candidate = copy.deepcopy(desired)
    merge_base = copy.deepcopy(base)
    revision = int(expected_revision or 0)
    for _ in range(max_attempts):
        result = _rpc("sigma_fbu_cas_section", {
            "p_environment": _environment(),
            "p_run_id": run_id,
            "p_section_name": section_name,
            "p_expected_revision": revision,
            "p_data": _normalize_section(section_name, candidate),
        })
        if result is None:
            return None
        if result.get("applied"):
            return result
        latest = result.get("data")
        revision = int(result.get("revision") or 0)
        candidate = merge_json_changes(merge_base, desired, latest)
        candidate = _normalize_section(section_name, candidate)
    raise RuntimeError(f"FBU 活动区块并发更新冲突：{section_name}")


def save_snapshot_with_retry(
    run_id: str,
    *,
    base_core: dict[str, Any],
    desired_core: dict[str, Any],
    expected_core_revision: int,
    sections: dict[str, dict[str, Any]],
    max_attempts: int = 4,
) -> dict[str, Any] | None:
    candidate_core = copy.deepcopy(desired_core)
    candidate_sections = {
        field: copy.deepcopy(spec.get("desired"))
        for field, spec in sections.items()
    }
    expected_sections = {
        field: int(spec.get("expected_revision") or 0)
        for field, spec in sections.items()
    }
    core_revision = int(expected_core_revision or 0)
    for _ in range(max_attempts):
        result = _rpc("sigma_fbu_commit_snapshot", {
            "p_environment": _environment(),
            "p_run_id": run_id,
            "p_expected_core_revision": core_revision,
            "p_seed_core": base_core,
            "p_core_data": candidate_core,
            "p_sections": {
                field: {
                    "data": _normalize_section(field, candidate_sections[field]),
                    "expected_revision": expected_sections[field],
                    "replace": bool(spec.get("replace")),
                }
                for field, spec in sections.items()
            },
        })
        if result is None:
            return None
        if result.get("applied"):
            return result
        latest_core = dict(result.get("data") or {})
        core_revision = int(result.get("revision") or 0)
        candidate_core = _merge_core_after_conflict(
            base_core,
            desired_core,
            latest_core,
        )
        latest_sections = dict(result.get("sections") or {})
        for field, spec in sections.items():
            latest = dict(latest_sections.get(field) or {})
            expected_sections[field] = int(latest.get("revision") or 0)
            if spec.get("replace"):
                candidate_sections[field] = copy.deepcopy(spec.get("desired"))
            else:
                candidate_sections[field] = merge_json_changes(
                    spec.get("base"),
                    spec.get("desired"),
                    latest.get("data"),
                )
    raise RuntimeError("FBU 活动事务并发更新冲突")


def load_run_state(run_id: str, sections: set[str]) -> dict[str, Any] | None:
    query = urlencode({
        "environment": f"eq.{_environment()}",
        "run_id": f"eq.{run_id}",
        "select": "core,revision",
        "limit": "1",
    })
    rows = _call(f"{FBU_POSTGRES_RUNS_TABLE}?{query}")
    if rows is None:
        return None
    if not isinstance(rows, list) or not rows:
        return {}
    core = dict(rows[0].get("core") or {})
    core["__core_revision"] = int(rows[0].get("revision") or 0)
    revisions: dict[str, int] = {}
    if sections:
        names = ",".join(quote(name, safe="") for name in sorted(sections))
        section_query = urlencode({
            "environment": f"eq.{_environment()}",
            "run_id": f"eq.{run_id}",
            "section_name": f"in.({names})",
            "select": "section_name,data,revision",
        })
        section_rows = _call(f"{FBU_POSTGRES_SECTIONS_TABLE}?{section_query}")
        if section_rows is None:
            return None
        for row in section_rows or []:
            name = str(row.get("section_name") or "")
            if not name:
                continue
            core[name] = row.get("data")
            revisions[name] = int(row.get("revision") or 0)
        for name in sections:
            core.setdefault(name, [] if name == "results" else {})
            revisions.setdefault(name, 0)
    core["__section_revisions"] = revisions
    return core


def list_run_states() -> list[dict[str, Any]] | None:
    query = urlencode({
        "environment": f"eq.{_environment()}",
        "select": "core,revision",
        "limit": "10000",
    })
    rows = _call(
        f"{FBU_POSTGRES_RUNS_TABLE}?{query}",
        headers={"Range": "0-9999"},
    )
    if rows is None:
        return None
    return sorted(
        [dict(row.get("core") or {}) for row in rows if isinstance(row, dict)],
        key=lambda row: str(row.get("created_at") or ""),
        reverse=True,
    )


def load_job(run_id: str, job_id: str) -> dict[str, Any] | None:
    query = urlencode({
        "environment": f"eq.{_environment()}",
        "run_id": f"eq.{run_id}",
        "job_id": f"eq.{job_id}",
        "select": "payload,revision",
        "limit": "1",
    })
    rows = _call(f"{FBU_POSTGRES_JOBS_TABLE}?{query}")
    if rows is None or not rows:
        return None
    return dict(rows[0].get("payload") or {})


def patch_job(
    run_id: str,
    job_id: str,
    *,
    seed: dict[str, Any] | None,
    patch: dict[str, Any],
    allowed_from: list[str] | None = None,
) -> dict[str, Any] | None:
    result = _rpc("sigma_fbu_patch_job", {
        "p_environment": _environment(),
        "p_run_id": run_id,
        "p_job_id": job_id,
        "p_seed": seed or {},
        "p_patch": patch,
        "p_allowed_from": allowed_from,
    })
    if result is None:
        return None
    payload = dict(result.get("data") or {})
    payload["__transition_applied"] = bool(result.get("applied"))
    return payload


def delete_run(run_id: str) -> bool | None:
    query = urlencode({
        "environment": f"eq.{_environment()}",
        "run_id": f"eq.{run_id}",
    })
    result = _call(
        f"{FBU_POSTGRES_RUNS_TABLE}?{query}",
        method="DELETE",
        headers={"Prefer": "return=minimal"},
    )
    return None if result is None and _known_available() is False else True
