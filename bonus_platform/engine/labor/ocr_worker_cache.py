from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .runtime_metrics import record_labor_runtime_metric


CACHE_SCHEMA_VERSION = 1
OCR_SCHEMA_VERSION = "rapidocr-ppocrv6-small-v1"
ROW_PARSER_SCHEMA_VERSION = "visual-rows-v5"


def labor_ocr_cache_dir() -> Path:
    configured = str(os.environ.get("LABOR_OCR_CACHE_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".cache" / "sigma-workbench" / "overseas-labor-ocr"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _write_envelope(destination: Path, envelope: dict[str, Any]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(envelope, temporary, ensure_ascii=False, separators=(",", ":"))
            temporary.flush()
        temporary_path.replace(destination)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def pdf_content_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cache_path(cache_dir: Path, pdf_path: Path) -> Path:
    digest = pdf_content_digest(pdf_path)
    version_key = hashlib.sha256(
        f"{CACHE_SCHEMA_VERSION}:{OCR_SCHEMA_VERSION}:{ROW_PARSER_SCHEMA_VERSION}".encode("utf-8")
    ).hexdigest()[:12]
    return Path(cache_dir) / f"{digest}-{version_key}.json"


def _is_complete_payload(payload: Any) -> bool:
    if not isinstance(payload, dict) or payload.get("status") != "completed":
        return False
    file_payload = payload.get("file")
    return (
        isinstance(payload.get("rows"), list)
        and isinstance(file_payload, dict)
        and int(file_payload.get("failedPageCount") or 0) == 0
    )


def load_cached_pdf(cache_dir: Path, pdf_path: Path) -> dict[str, Any] | None:
    path = cache_path(cache_dir, pdf_path)
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        record_labor_runtime_metric("ocr_cache", status="miss", summary={"cacheHit": False})
        return None
    if not isinstance(envelope, dict):
        return None
    if envelope.get("cacheSchemaVersion") != CACHE_SCHEMA_VERSION:
        return None
    if envelope.get("ocrSchemaVersion") != OCR_SCHEMA_VERSION:
        return None
    if envelope.get("rowParserSchemaVersion") != ROW_PARSER_SCHEMA_VERSION:
        return None
    if envelope.get("contentDigest") != pdf_content_digest(pdf_path):
        return None
    payload = envelope.get("payload")
    if not _is_complete_payload(payload):
        record_labor_runtime_metric("ocr_cache", status="miss", summary={"cacheHit": False})
        return None
    timestamp = _utc_now().isoformat()
    envelope.setdefault("createdAt", datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat())
    envelope["lastAccessedAt"] = timestamp
    _write_envelope(path, envelope)
    record_labor_runtime_metric("ocr_cache", status="hit", summary={"cacheHit": True})
    return payload


def store_cached_pdf(cache_dir: Path, pdf_path: Path, payload: dict[str, Any]) -> Path:
    if not _is_complete_payload(payload):
        raise ValueError("Only complete OCR payloads can be cached")
    destination = cache_path(cache_dir, pdf_path)
    timestamp = _utc_now().isoformat()
    envelope = {
        "cacheSchemaVersion": CACHE_SCHEMA_VERSION,
        "ocrSchemaVersion": OCR_SCHEMA_VERSION,
        "rowParserSchemaVersion": ROW_PARSER_SCHEMA_VERSION,
        "contentDigest": pdf_content_digest(pdf_path),
        "createdAt": timestamp,
        "lastAccessedAt": timestamp,
        "payload": payload,
    }
    _write_envelope(destination, envelope)
    return destination


def _entry_access_time(path: Path, envelope: dict[str, Any]) -> datetime:
    raw = envelope.get("lastAccessedAt") or envelope.get("createdAt")
    try:
        value = datetime.fromisoformat(str(raw or ""))
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)


def cleanup_ocr_cache(
    cache_dir: Path,
    *,
    retention_days: int,
    max_bytes: int,
    now: datetime | None = None,
) -> dict[str, int]:
    root = Path(cache_dir)
    summary = {
        "expiredEntryCount": 0,
        "corruptEntryCount": 0,
        "capacityEvictedEntryCount": 0,
        "reclaimedBytes": 0,
        "remainingBytes": 0,
        "remainingEntryCount": 0,
    }
    if not root.exists():
        return summary
    reference = now or _utc_now()
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    retained: list[tuple[Path, int, datetime]] = []
    for path in sorted(root.glob("*.json")):
        try:
            size = path.stat().st_size
            envelope = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(envelope, dict) or not _is_complete_payload(envelope.get("payload")):
                raise ValueError("invalid cache envelope")
            accessed_at = _entry_access_time(path, envelope)
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            path.unlink(missing_ok=True)
            summary["corruptEntryCount"] += 1
            summary["reclaimedBytes"] += size
            continue
        if retention_days > 0 and reference - accessed_at >= timedelta(days=retention_days):
            path.unlink(missing_ok=True)
            summary["expiredEntryCount"] += 1
            summary["reclaimedBytes"] += size
            continue
        retained.append((path, size, accessed_at))
    total = sum(size for _, size, _ in retained)
    for path, size, _ in sorted(retained, key=lambda item: (item[2], item[0].name)):
        if total <= max_bytes:
            break
        path.unlink(missing_ok=True)
        total -= size
        summary["capacityEvictedEntryCount"] += 1
        summary["reclaimedBytes"] += size
    summary["remainingBytes"] = max(total, 0)
    summary["remainingEntryCount"] = sum(1 for path, _, _ in retained if path.exists())
    return summary
