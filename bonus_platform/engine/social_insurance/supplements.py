from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
import time
from typing import Any

from ... import config
from .adapter import sync_beisen_candidates
from .persistent_storage import (
    SocialInsuranceStorageError,
    load_json,
    persist_json,
    persistent_storage_enabled,
    serverless_runtime,
)
from .rule_catalog import RULE_VERSION
from .runs import RunValidationError, list_runs, load_run, supplement_candidate_id
from .sync_snapshot import capture_reporting_snapshot, load_reporting_snapshot


SEARCH_LOOKBACK_DAYS = 366
SEARCH_CACHE_SECONDS = 600
POOL_CACHE_SECONDS = max(600, int(os.environ.get("SIGMA_SOCIAL_INSURANCE_POOL_CACHE_SECONDS", "14400")))
POOL_SNAPSHOT_DATA_MODE = "supplement-candidate-pool-v1"
LOOKUP_SOURCE_FIELD = "_supplementLookupSource"
SEARCH_INDEX_NAMESPACE = "supplement-search-index"
SEARCH_INDEX_VERSION = 1
SEARCH_INDEX_CACHE_SECONDS = max(
    15,
    int(os.environ.get("SIGMA_SOCIAL_INSURANCE_SEARCH_INDEX_CACHE_SECONDS", "60")),
)
SEARCH_INDEX_CACHE_MAX_ENTRIES = max(
    8,
    min(512, int(os.environ.get("SIGMA_SOCIAL_INSURANCE_SEARCH_INDEX_CACHE_MAX_ENTRIES", "64"))),
)
_RESOLUTION_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
_POOL_CACHE: dict[str, tuple[float, str, str, list[dict[str, Any]]]] = {}
_POOL_STATUS: dict[str, dict[str, Any]] = {}
_POOL_REFRESHING: set[str] = set()
_POOL_CONDITION = threading.Condition()
_SEARCH_INDEX_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_SEARCH_INDEX_MISS_CACHE: dict[str, float] = {}
_SEARCH_INDEX_LOCK = threading.Lock()


def _search_index_root() -> Path:
    configured = os.environ.get("SIGMA_SOCIAL_INSURANCE_RUNS_DIR")
    runs_root = Path(configured).expanduser() if configured else config.SOCIAL_INSURANCE_RUNS_DIR
    root = runs_root / ".supplement-search-index"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    return root


def _safe_run_id(run_id: str) -> str:
    normalized = str(run_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,80}", normalized):
        raise RunValidationError("批次ID格式无效")
    return normalized


def _search_index_path(run_id: str) -> Path:
    return _search_index_root() / f"{_safe_run_id(run_id)}.json"


def _write_search_index(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    try:
        temporary.chmod(0o600)
    except OSError:
        pass
    temporary.replace(path)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _search_index_cache_key(run_id: str) -> str:
    return f"{_search_index_root().resolve()}|{_safe_run_id(run_id)}"


def clear_supplement_search_index_cache() -> None:
    with _SEARCH_INDEX_LOCK:
        _SEARCH_INDEX_CACHE.clear()
        _SEARCH_INDEX_MISS_CACHE.clear()


def _clear_expired_search_indexes() -> None:
    now = time.monotonic()
    with _SEARCH_INDEX_LOCK:
        for key, (expires_at, _payload) in list(_SEARCH_INDEX_CACHE.items()):
            if expires_at <= now:
                _SEARCH_INDEX_CACHE.pop(key, None)
        for key, expires_at in list(_SEARCH_INDEX_MISS_CACHE.items()):
            if expires_at <= now:
                _SEARCH_INDEX_MISS_CACHE.pop(key, None)


def _trim_search_index_cache() -> None:
    while len(_SEARCH_INDEX_CACHE) + len(_SEARCH_INDEX_MISS_CACHE) > SEARCH_INDEX_CACHE_MAX_ENTRIES:
        ready = min(
            ((expires_at, key, "ready") for key, (expires_at, _payload) in _SEARCH_INDEX_CACHE.items()),
            default=None,
        )
        missing = min(
            ((expires_at, key, "missing") for key, expires_at in _SEARCH_INDEX_MISS_CACHE.items()),
            default=None,
        )
        oldest = min((item for item in (ready, missing) if item is not None), default=None)
        if oldest is None:
            return
        _expires_at, key, kind = oldest
        if kind == "ready":
            _SEARCH_INDEX_CACHE.pop(key, None)
        else:
            _SEARCH_INDEX_MISS_CACHE.pop(key, None)


def _store_search_index_cache(payload: dict[str, Any]) -> None:
    key = _search_index_cache_key(str(payload.get("runId") or ""))
    with _SEARCH_INDEX_LOCK:
        _SEARCH_INDEX_MISS_CACHE.pop(key, None)
        _SEARCH_INDEX_CACHE[key] = (
            time.monotonic() + SEARCH_INDEX_CACHE_SECONDS,
            deepcopy(payload),
        )
        _trim_search_index_cache()


def _store_search_index_miss(run_id: str) -> None:
    key = _search_index_cache_key(run_id)
    with _SEARCH_INDEX_LOCK:
        _SEARCH_INDEX_CACHE.pop(key, None)
        _SEARCH_INDEX_MISS_CACHE[key] = time.monotonic() + SEARCH_INDEX_CACHE_SECONDS
        _trim_search_index_cache()


def _existing_candidate_ids(run: dict[str, Any]) -> set[str]:
    output = {
        str(value or "")
        for value in run.get("existingCandidateIds") or []
        if str(value or "")
    }
    for employee in run.get("employees") or []:
        if not isinstance(employee, dict):
            continue
        report = employee.get("report") if isinstance(employee.get("report"), dict) else {}
        candidate_id = supplement_candidate_id(str(report.get("证件号码") or ""))
        if candidate_id:
            output.add(candidate_id)
    return output


def _indexed_candidate(record: dict[str, Any]) -> dict[str, str] | None:
    identity = _identity(record)
    candidate_id = _candidate_id(record)
    if not identity or not candidate_id:
        return None
    report = record.get("report") if isinstance(record.get("report"), dict) else {}
    source = record.get("source") if isinstance(record.get("source"), dict) else {}
    return {
        "id": candidate_id,
        "name": str(report.get("姓名") or "").strip(),
        "maskedId": _mask_identity(identity),
        "identitySuffix": identity[-4:].lower(),
        "entryDate": str(record.get("entryDate") or ""),
        "subject": str(source.get("subject") or ""),
        "place": str(source.get("place") or ""),
        "employType": str(source.get("employType") or ""),
        "validation": (
            "需复核字段"
            if str(record.get("status") or "") == "needs_review"
            else "字段已带出"
        ),
        "lookupSource": str(record.get(LOOKUP_SOURCE_FIELD) or "beisen-pool"),
    }


def _build_search_index(
    run: dict[str, Any],
    records: list[dict[str, Any]],
    pool_status: dict[str, Any],
) -> dict[str, Any]:
    run_id = _safe_run_id(str(run.get("id") or ""))
    active_subject = str(run.get("subject") or "").strip()
    existing_candidate_ids = _existing_candidate_ids(run)
    seen: set[str] = set()
    candidates: list[dict[str, str]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        candidate = _indexed_candidate(record)
        if candidate is None:
            continue
        candidate_id = candidate["id"]
        if active_subject and candidate["subject"] != active_subject:
            continue
        if candidate_id in existing_candidate_ids or candidate_id in seen:
            continue
        seen.add(candidate_id)
        candidates.append(candidate)
    record_count = pool_status.get("recordCount")
    return {
        "version": SEARCH_INDEX_VERSION,
        "ruleVersion": RULE_VERSION,
        "state": "ready",
        "runId": run_id,
        "runUpdatedAt": str(run.get("updatedAt") or ""),
        "periodStart": str(run.get("periodStart") or ""),
        "periodEnd": str(run.get("periodEnd") or ""),
        "confirmationDate": str(run.get("confirmationDate") or ""),
        "subject": active_subject,
        "cachedAt": str(pool_status.get("cachedAt") or _timestamp_after()),
        "expiresAt": str(pool_status.get("expiresAt") or _timestamp_after(POOL_CACHE_SECONDS)),
        "recordCount": int(record_count) if isinstance(record_count, int) else len(records),
        "candidateCount": len(candidates),
        "storage": "precomputed-search-index",
        "candidates": candidates,
    }


def _persist_search_index(payload: dict[str, Any]) -> None:
    run_id = _safe_run_id(str(payload.get("runId") or ""))
    try:
        _write_search_index(_search_index_path(run_id), payload)
        if persistent_storage_enabled():
            persist_json(SEARCH_INDEX_NAMESPACE, run_id, payload)
    except (OSError, SocialInsuranceStorageError, RuntimeError) as exc:
        raise RunValidationError("补充增员搜索索引未能保存到持久化存储") from exc
    _store_search_index_cache(payload)


def publish_supplement_search_indexes(
    runs: list[dict[str, Any]],
    *,
    records: list[dict[str, Any]],
    pool_status: dict[str, Any],
) -> dict[str, int]:
    payloads = [
        _build_search_index(run, records, pool_status)
        for run in runs
        if isinstance(run, dict)
    ]
    if len(payloads) <= 1:
        for payload in payloads:
            _persist_search_index(payload)
    else:
        with ThreadPoolExecutor(max_workers=min(8, len(payloads))) as executor:
            list(executor.map(_persist_search_index, payloads))
    return {
        "indexCount": len(payloads),
        "candidateCount": sum(int(payload.get("candidateCount") or 0) for payload in payloads),
    }


def _valid_search_index(payload: Any, run_id: str) -> bool:
    if not isinstance(payload, dict):
        return False
    candidates = payload.get("candidates")
    if (
        payload.get("version") != SEARCH_INDEX_VERSION
        or payload.get("ruleVersion") != RULE_VERSION
        or payload.get("state") != "ready"
        or payload.get("runId") != run_id
        or not all(
            str(payload.get(key) or "").strip()
            for key in (
                "runUpdatedAt",
                "periodStart",
                "periodEnd",
                "confirmationDate",
                "subject",
                "cachedAt",
            )
        )
        or not isinstance(payload.get("recordCount"), int)
        or not isinstance(candidates, list)
    ):
        return False
    allowed_keys = {
        "id",
        "name",
        "maskedId",
        "identitySuffix",
        "entryDate",
        "subject",
        "place",
        "employType",
        "validation",
        "lookupSource",
    }
    return all(
        isinstance(candidate, dict)
        and set(candidate).issubset(allowed_keys)
        and re.fullmatch(r"sup_[0-9a-f]{24}", str(candidate.get("id") or "")) is not None
        and 1 <= len(str(candidate.get("identitySuffix") or "")) <= 4
        for candidate in candidates
    )


def load_supplement_search_index(
    run_id: str,
    *,
    bypass_process_cache: bool = False,
) -> dict[str, Any] | None:
    normalized_run_id = _safe_run_id(run_id)
    if not bypass_process_cache:
        _clear_expired_search_indexes()
        key = _search_index_cache_key(normalized_run_id)
        cached_payload: dict[str, Any] | None = None
        with _SEARCH_INDEX_LOCK:
            if key in _SEARCH_INDEX_MISS_CACHE:
                return None
            cached = _SEARCH_INDEX_CACHE.get(key)
            if cached is not None:
                cached_payload = deepcopy(cached[1])
        if cached_payload is not None:
            if _valid_search_index(cached_payload, normalized_run_id):
                return cached_payload
            _store_search_index_miss(normalized_run_id)
            return None
    path = _search_index_path(normalized_run_id)
    payload: dict[str, Any] | None = None
    if persistent_storage_enabled() and (serverless_runtime() or not path.is_file()):
        try:
            payload = load_json(SEARCH_INDEX_NAMESPACE, normalized_run_id)
        except (SocialInsuranceStorageError, RuntimeError):
            return None
    if payload is None and path.is_file():
        try:
            candidate = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            candidate = None
        if isinstance(candidate, dict):
            payload = candidate
    if not _valid_search_index(payload, normalized_run_id):
        _store_search_index_miss(normalized_run_id)
        return None
    _store_search_index_cache(payload)
    return deepcopy(payload)


def search_precomputed_supplement_candidates(
    run_id: str,
    query: str,
) -> list[dict[str, Any]] | None:
    normalized_query = str(query or "").strip().lower()
    if len(normalized_query) < 2 or len(normalized_query) > 50:
        raise RunValidationError("请输入2至50个字符的姓名或证件号后四位")
    index = load_supplement_search_index(run_id)
    if index is None:
        return None
    output: list[dict[str, Any]] = []
    for candidate in index.get("candidates") or []:
        if (
            normalized_query not in str(candidate.get("name") or "").lower()
            and normalized_query not in str(candidate.get("identitySuffix") or "").lower()
        ):
            continue
        output.append({
            key: deepcopy(value)
            for key, value in candidate.items()
            if key != "identitySuffix"
        })
        if len(output) >= 20:
            break
    return output


def precomputed_supplement_status(run_id: str) -> dict[str, Any] | None:
    index = load_supplement_search_index(run_id)
    if index is None:
        return None
    return {
        "state": "ready",
        "label": "北森候选索引已准备",
        "cachedAt": index.get("cachedAt"),
        "expiresAt": index.get("expiresAt"),
        "recordCount": int(index.get("recordCount") or 0),
        "candidateCount": int(index.get("candidateCount") or 0),
        "storage": "precomputed-search-index",
        "cacheSeconds": SEARCH_INDEX_CACHE_SECONDS,
        "rawApiResponseSaved": False,
    }


def remove_supplement_candidate_from_search_index(
    run_id: str,
    candidate_id: str,
    *,
    run_updated_at: str = "",
) -> bool:
    index = load_supplement_search_index(run_id, bypass_process_cache=True)
    if index is None:
        return False
    normalized_candidate_id = str(candidate_id or "").strip()
    candidates = [
        candidate
        for candidate in index.get("candidates") or []
        if str(candidate.get("id") or "") != normalized_candidate_id
    ]
    if len(candidates) == len(index.get("candidates") or []):
        return False
    updated = {
        **index,
        "runUpdatedAt": str(run_updated_at or index.get("runUpdatedAt") or ""),
        "candidateCount": len(candidates),
        "candidates": candidates,
    }
    try:
        _persist_search_index(updated)
    except RunValidationError:
        # The run mutation already succeeded. Keep this process correct and let
        # the bounded cache expire instead of turning a successful add into an
        # ambiguous API failure.
        _store_search_index_cache(updated)
        return False
    return True


def invalidate_supplement_search_index(run_id: str) -> bool:
    index = load_supplement_search_index(run_id, bypass_process_cache=True)
    if index is None:
        return False
    stale = {
        **index,
        "state": "stale",
        "candidateCount": 0,
        "candidates": [],
    }
    try:
        _persist_search_index(stale)
    except RunValidationError:
        _store_search_index_miss(run_id)
        return False
    _store_search_index_miss(run_id)
    return True


def _clear_expired_cache() -> None:
    now = time.monotonic()
    for key, (expires_at, _record) in list(_RESOLUTION_CACHE.items()):
        if expires_at <= now:
            _RESOLUTION_CACHE.pop(key, None)
    for key, (expires_at, _cached_at, _expires_at, _records) in list(_POOL_CACHE.items()):
        if expires_at <= now:
            _POOL_CACHE.pop(key, None)
            if _POOL_STATUS.get(key, {}).get("state") == "ready":
                _POOL_STATUS[key] = {"state": "empty", "label": "等待后台更新"}


def _pool_key(run: dict[str, Any]) -> str:
    return "|".join((
        str(Path(os.environ.get("SIGMA_SOCIAL_INSURANCE_RUNS_DIR") or "default-runs-root").expanduser()),
        str(run.get("periodStart") or ""),
        str(run.get("periodEnd") or ""),
        str(run.get("confirmationDate") or run.get("periodEnd") or ""),
    ))


def _timestamp_after(seconds: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).replace(microsecond=0).isoformat()


def _identity(record: dict[str, Any]) -> str:
    report = record.get("report") if isinstance(record.get("report"), dict) else {}
    return str(report.get("证件号码") or "").replace(" ", "").strip().upper()


def _candidate_id(record: dict[str, Any]) -> str:
    return supplement_candidate_id(_identity(record))


def _mask_identity(identity: str) -> str:
    value = str(identity or "").strip()
    if len(value) <= 8:
        return "****" if value else ""
    return f"{value[:4]}{'*' * min(10, len(value) - 8)}{value[-4:]}"


def _pool_window(run: dict[str, Any]) -> tuple[str, str, str]:
    try:
        period_start = date.fromisoformat(str(run.get("periodStart") or ""))
    except ValueError as exc:
        raise RunValidationError("当前批次周期无效") from exc
    entry_end = period_start - timedelta(days=1)
    entry_start = entry_end - timedelta(days=SEARCH_LOOKBACK_DAYS)
    confirmation_date = str(run.get("confirmationDate") or run.get("periodEnd") or "")
    return entry_start.isoformat(), entry_end.isoformat(), confirmation_date


def _query_records(run: dict[str, Any]) -> list[dict[str, Any]]:
    entry_start, entry_end, confirmation_date = _pool_window(run)
    with tempfile.TemporaryDirectory(prefix="sigma-social-supplement-") as temporary:
        records, _summary = sync_beisen_candidates(
            period_start=entry_start,
            period_end=entry_end,
            confirmation_date=confirmation_date,
            subject="*",
            output_dir=Path(temporary),
        )
    return [record for record in records if str(record.get("status") or "") != "excluded"]


def _record_subject(record: dict[str, Any]) -> str:
    source = record.get("source") if isinstance(record.get("source"), dict) else {}
    return str(source.get("subject") or source.get("subjectCode") or "").strip()


def _historical_pool_records(run: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        active_period_start = date.fromisoformat(str(run.get("periodStart") or ""))
    except ValueError as exc:
        raise RunValidationError("当前批次周期无效") from exc
    history_start = active_period_start - timedelta(days=SEARCH_LOOKBACK_DAYS + 1)
    run_id = str(run.get("id") or "")
    active_subject = str(run.get("subject") or "").strip()
    output: list[dict[str, Any]] = []
    for summary in list_runs(50):
        historical_run_id = str(summary.get("id") or "")
        if not historical_run_id or historical_run_id == run_id:
            continue
        if (
            active_subject
            and active_subject != "*"
            and str(summary.get("subject") or "").strip() != active_subject
        ):
            continue
        historical_run = load_run(historical_run_id)
        for record in historical_run.get("employees") or []:
            if not isinstance(record, dict) or str(record.get("status") or "") == "excluded":
                continue
            try:
                entry_date = date.fromisoformat(str(record.get("entryDate") or ""))
            except ValueError:
                continue
            if history_start <= entry_date < active_period_start:
                candidate = deepcopy(record)
                candidate[LOOKUP_SOURCE_FIELD] = "recent-beisen-run"
                output.append(candidate)
    return output


def _merge_pool_records(
    historical_records: list[dict[str, Any]],
    beisen_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for records, lookup_source in (
        (historical_records, "recent-beisen-run"),
        (beisen_records, "beisen-pool"),
    ):
        for record in records:
            identity = _identity(record)
            if not identity:
                continue
            key = (identity, _record_subject(record))
            if key in seen:
                continue
            seen.add(key)
            candidate = deepcopy(record)
            candidate[LOOKUP_SOURCE_FIELD] = str(
                candidate.get(LOOKUP_SOURCE_FIELD) or lookup_source
            )
            output.append(candidate)
    return output


def _build_pool_records(run: dict[str, Any]) -> list[dict[str, Any]]:
    return _merge_pool_records(_historical_pool_records(run), _query_records(run))


def _load_shared_pool(run: dict[str, Any]) -> tuple[str, list[dict[str, Any]]] | None:
    period_start, period_end, confirmation_date = _pool_window(run)
    snapshot = load_reporting_snapshot(
        period_start=period_start,
        period_end=period_end,
        confirmation_date=confirmation_date,
        subject="*",
    )
    if snapshot is None:
        return None
    source_summary = (
        snapshot.get("sourceSummary")
        if isinstance(snapshot.get("sourceSummary"), dict)
        else {}
    )
    records = snapshot.get("records")
    if source_summary.get("dataMode") != POOL_SNAPSHOT_DATA_MODE or not isinstance(records, list):
        return None
    return str(snapshot.get("capturedAt") or _timestamp_after()), records


def _capture_shared_pool(run: dict[str, Any], records: list[dict[str, Any]]) -> str:
    period_start, period_end, confirmation_date = _pool_window(run)
    captured = capture_reporting_snapshot(
        records=records,
        source_summary={
            "provider": "beisen-open-platform",
            "dataMode": POOL_SNAPSHOT_DATA_MODE,
            "rawApiResponseSaved": False,
        },
        period_start=period_start,
        period_end=period_end,
        confirmation_date=confirmation_date,
        subject="*",
    )
    return str(captured["capturedAt"])


def _store_pool_cache(
    key: str,
    records: list[dict[str, Any]],
    *,
    cached_at: str,
) -> None:
    expires_at = _timestamp_after(POOL_CACHE_SECONDS)
    with _POOL_CONDITION:
        _POOL_CACHE[key] = (
            time.monotonic() + POOL_CACHE_SECONDS,
            cached_at,
            expires_at,
            records,
        )
        _POOL_STATUS[key] = {
            "state": "ready",
            "label": "北森候选池已准备",
            "cachedAt": cached_at,
            "expiresAt": expires_at,
            "recordCount": len(records),
            "storage": "shared-snapshot",
        }


def _pool_records(run: dict[str, Any], *, force: bool = False) -> list[dict[str, Any]]:
    key = _pool_key(run)
    waited_for_refresh = False
    with _POOL_CONDITION:
        _clear_expired_cache()
        while key in _POOL_REFRESHING:
            waited_for_refresh = True
            _POOL_CONDITION.wait()
            _clear_expired_cache()
        cached = _POOL_CACHE.get(key)
        if cached is not None and (not force or waited_for_refresh):
            return cached[3]
        _POOL_REFRESHING.add(key)
        _POOL_STATUS[key] = {
            "state": "warming",
            "label": "正在后台更新北森数据",
            "startedAt": _timestamp_after(),
        }
    try:
        shared_pool = None if force else _load_shared_pool(run)
        if shared_pool is None:
            records = _build_pool_records(run)
            cached_at = _capture_shared_pool(run, records)
        else:
            cached_at, records = shared_pool
    except Exception:
        with _POOL_CONDITION:
            _POOL_STATUS[key] = {
                "state": "error",
                "label": "后台更新失败，可稍后重试",
                "failedAt": _timestamp_after(),
            }
            _POOL_REFRESHING.discard(key)
            _POOL_CONDITION.notify_all()
        raise
    _store_pool_cache(key, records, cached_at=cached_at)
    with _POOL_CONDITION:
        _POOL_REFRESHING.discard(key)
        _POOL_CONDITION.notify_all()
    return records


def prepare_beisen_supplement_pool(
    run: dict[str, Any],
    *,
    force: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    records = _pool_records(run, force=force)
    return records, supplement_pool_status(run)


def load_shared_supplement_pool(
    run: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]] | None:
    """Load an existing shared pool without triggering a live Beisen query."""
    shared_pool = _load_shared_pool(run)
    if shared_pool is None:
        return None
    cached_at, records = shared_pool
    _store_pool_cache(_pool_key(run), records, cached_at=cached_at)
    return records, supplement_pool_status(run)


def prewarm_beisen_supplement_pool(run: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    _records, status = prepare_beisen_supplement_pool(run, force=force)
    return status


def supplement_pool_status(run: dict[str, Any]) -> dict[str, Any]:
    key = _pool_key(run)
    with _POOL_CONDITION:
        _clear_expired_cache()
        status = deepcopy(_POOL_STATUS.get(key) or {})
    if not status:
        shared_pool = _load_shared_pool(run)
        if shared_pool is not None:
            cached_at, records = shared_pool
            _store_pool_cache(key, records, cached_at=cached_at)
            with _POOL_CONDITION:
                status = deepcopy(_POOL_STATUS[key])
    if not status:
        status = {"state": "empty", "label": "等待后台更新"}
    return {
        **status,
        "cacheSeconds": POOL_CACHE_SECONDS,
        "rawApiResponseSaved": False,
    }


def search_beisen_supplement_candidates(run: dict[str, Any], query: str) -> list[dict[str, Any]]:
    normalized_query = str(query or "").strip().lower()
    if len(normalized_query) < 2 or len(normalized_query) > 50:
        raise RunValidationError("请输入2至50个字符的姓名或证件号后四位")
    existing = {
        str(item.get("report", {}).get("证件号码") or "").replace(" ", "").strip().upper()
        for item in run.get("employees") or []
    }
    existing_candidate_ids = {
        str(value or "")
        for value in run.get("existingCandidateIds") or []
        if str(value or "")
    }
    _clear_expired_cache()
    run_id = str(run.get("id") or "")
    active_subject = str(run.get("subject") or "").strip()

    def matches(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        seen: set[str] = set()
        for record in records:
            identity = _identity(record)
            candidate_id = _candidate_id(record)
            report = record.get("report") if isinstance(record.get("report"), dict) else {}
            name = str(report.get("姓名") or "").strip()
            record_subject = _record_subject(record)
            if active_subject and record_subject != active_subject:
                continue
            if (
                not identity
                or identity in existing
                or candidate_id in existing_candidate_ids
                or identity in seen
            ):
                continue
            if normalized_query not in name.lower() and normalized_query not in identity[-4:].lower():
                continue
            seen.add(identity)
            source = record.get("source") if isinstance(record.get("source"), dict) else {}
            _RESOLUTION_CACHE[(run_id, candidate_id)] = (
                time.monotonic() + SEARCH_CACHE_SECONDS,
                deepcopy(record),
            )
            output.append({
                "id": candidate_id,
                "name": name,
                "maskedId": _mask_identity(identity),
                "entryDate": str(record.get("entryDate") or ""),
                "subject": str(source.get("subject") or ""),
                "place": str(source.get("place") or ""),
                "employType": str(source.get("employType") or ""),
                "validation": "需复核字段" if str(record.get("status") or "") == "needs_review" else "字段已带出",
                "lookupSource": str(record.get(LOOKUP_SOURCE_FIELD) or "beisen-pool"),
            })
            if len(output) >= 20:
                break
        return output

    return matches(_pool_records(run))


def resolve_beisen_supplement_candidate(run: dict[str, Any], candidate_id: str) -> dict[str, Any]:
    normalized_id = str(candidate_id or "").strip()
    if not normalized_id.startswith("sup_") or len(normalized_id) != 28:
        raise RunValidationError("补充增员候选标识无效")
    existing = {
        str(item.get("report", {}).get("证件号码") or "").replace(" ", "").strip().upper()
        for item in run.get("employees") or []
    }
    _clear_expired_cache()
    cached = _RESOLUTION_CACHE.pop((str(run.get("id") or ""), normalized_id), None)
    if cached is not None:
        identity = _identity(cached[1])
        if identity and identity not in existing:
            return deepcopy(cached[1])
    for record in _pool_records(run):
        identity = _identity(record)
        if identity and identity not in existing and _candidate_id(record) == normalized_id:
            return deepcopy(record)
    raise RunValidationError("北森中未找到该补充人员，可能已离职、主体变化或不再符合当前增员条件")
