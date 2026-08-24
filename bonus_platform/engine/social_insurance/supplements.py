from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
import tempfile
import threading
import time
from typing import Any

from .adapter import sync_beisen_candidates
from .runs import RunValidationError, list_runs, load_run


SEARCH_LOOKBACK_DAYS = 366
SEARCH_CACHE_SECONDS = 600
POOL_CACHE_SECONDS = max(600, int(os.environ.get("SIGMA_SOCIAL_INSURANCE_POOL_CACHE_SECONDS", "14400")))
_RESOLUTION_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
_POOL_CACHE: dict[str, tuple[float, str, str, list[dict[str, Any]]]] = {}
_POOL_STATUS: dict[str, dict[str, Any]] = {}
_POOL_REFRESHING: set[str] = set()
_POOL_CONDITION = threading.Condition()


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
    ))


def _timestamp_after(seconds: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).replace(microsecond=0).isoformat()


def _identity(record: dict[str, Any]) -> str:
    report = record.get("report") if isinstance(record.get("report"), dict) else {}
    return str(report.get("证件号码") or "").replace(" ", "").strip().upper()


def _candidate_id(record: dict[str, Any]) -> str:
    identity = _identity(record)
    return f"sup_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]}" if identity else ""


def _mask_identity(identity: str) -> str:
    value = str(identity or "").strip()
    if len(value) <= 8:
        return "****" if value else ""
    return f"{value[:4]}{'*' * min(10, len(value) - 8)}{value[-4:]}"


def _query_records(run: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        period_start = date.fromisoformat(str(run.get("periodStart") or ""))
    except ValueError as exc:
        raise RunValidationError("当前批次周期无效") from exc
    entry_end = period_start - timedelta(days=1)
    entry_start = entry_end - timedelta(days=SEARCH_LOOKBACK_DAYS)
    with tempfile.TemporaryDirectory(prefix="sigma-social-supplement-") as temporary:
        records, _summary = sync_beisen_candidates(
            period_start=entry_start.isoformat(),
            period_end=entry_end.isoformat(),
            confirmation_date=str(run.get("confirmationDate") or run.get("periodEnd") or ""),
            subject="*",
            output_dir=Path(temporary),
        )
    return [record for record in records if str(record.get("status") or "") != "excluded"]


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
        records = _query_records(run)
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
    cached_at = _timestamp_after()
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
        }
        _POOL_REFRESHING.discard(key)
        _POOL_CONDITION.notify_all()
    return records


def prewarm_beisen_supplement_pool(run: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    _pool_records(run, force=force)
    return supplement_pool_status(run)


def supplement_pool_status(run: dict[str, Any]) -> dict[str, Any]:
    key = _pool_key(run)
    with _POOL_CONDITION:
        _clear_expired_cache()
        status = deepcopy(_POOL_STATUS.get(key) or {
            "state": "empty",
            "label": "等待后台更新",
        })
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
    _clear_expired_cache()
    run_id = str(run.get("id") or "")
    active_subject = str(run.get("subject") or "").strip()

    def matches(records: list[dict[str, Any]], lookup_source: str) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        seen: set[str] = set()
        for record in records:
            identity = _identity(record)
            report = record.get("report") if isinstance(record.get("report"), dict) else {}
            name = str(report.get("姓名") or "").strip()
            if not identity or identity in existing or identity in seen:
                continue
            if normalized_query not in name.lower() and normalized_query not in identity[-4:].lower():
                continue
            seen.add(identity)
            source = record.get("source") if isinstance(record.get("source"), dict) else {}
            record_subject = str(source.get("subject") or source.get("subjectCode") or "").strip()
            if active_subject and record_subject != active_subject:
                continue
            candidate_id = _candidate_id(record)
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
                "lookupSource": lookup_source,
            })
            if len(output) >= 20:
                break
        return output

    try:
        active_period_start = date.fromisoformat(str(run.get("periodStart") or ""))
    except ValueError as exc:
        raise RunValidationError("当前批次周期无效") from exc
    history_start = active_period_start - timedelta(days=SEARCH_LOOKBACK_DAYS + 1)
    historical_records: list[dict[str, Any]] = []
    for summary in list_runs(50):
        historical_run_id = str(summary.get("id") or "")
        if not historical_run_id or historical_run_id == run_id:
            continue
        if str(summary.get("subject") or "").strip() != str(run.get("subject") or "").strip():
            continue
        historical_run = load_run(historical_run_id)
        for record in historical_run.get("employees") or []:
            if str(record.get("status") or "") == "excluded":
                continue
            try:
                entry_date = date.fromisoformat(str(record.get("entryDate") or ""))
            except ValueError:
                continue
            if history_start <= entry_date < active_period_start:
                historical_records.append(record)
    historical_matches = matches(historical_records, "recent-beisen-run")
    if historical_matches:
        return historical_matches
    return matches(_pool_records(run), "beisen-pool")


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
