import json
from datetime import datetime, timedelta, timezone

import pytest

from bonus_platform.engine.labor import ocr_worker_cache


def _complete_payload(source_file: str = "invoice.pdf") -> dict:
    return {
        "status": "completed",
        "rows": [{"source_file": source_file, "employee_name_raw": "Jane Doe", "amount": 80.0}],
        "file": {"sourceFile": source_file, "pageCount": 1, "failedPageCount": 0},
    }


def test_cache_hits_identical_pdf_content_after_rename(tmp_path):
    first = tmp_path / "first.pdf"
    renamed = tmp_path / "renamed.pdf"
    first.write_bytes(b"same pdf bytes")
    renamed.write_bytes(b"same pdf bytes")
    cache_dir = tmp_path / "cache"

    ocr_worker_cache.store_cached_pdf(cache_dir, first, _complete_payload(first.name))

    cached = ocr_worker_cache.load_cached_pdf(cache_dir, renamed)
    assert cached is not None
    assert cached["rows"][0]["employee_name_raw"] == "Jane Doe"


def test_cache_misses_changed_content_with_same_filename(tmp_path):
    pdf = tmp_path / "invoice.pdf"
    cache_dir = tmp_path / "cache"
    pdf.write_bytes(b"version one")
    ocr_worker_cache.store_cached_pdf(cache_dir, pdf, _complete_payload())

    pdf.write_bytes(b"version two")

    assert ocr_worker_cache.load_cached_pdf(cache_dir, pdf) is None


def test_cache_misses_when_schema_version_changes(monkeypatch, tmp_path):
    pdf = tmp_path / "invoice.pdf"
    pdf.write_bytes(b"pdf")
    cache_dir = tmp_path / "cache"
    ocr_worker_cache.store_cached_pdf(cache_dir, pdf, _complete_payload())

    monkeypatch.setattr(ocr_worker_cache, "ROW_PARSER_SCHEMA_VERSION", "visual-rows-v999")

    assert ocr_worker_cache.load_cached_pdf(cache_dir, pdf) is None


def test_cache_ignores_corrupt_json(tmp_path):
    pdf = tmp_path / "invoice.pdf"
    pdf.write_bytes(b"pdf")
    cache_dir = tmp_path / "cache"
    path = ocr_worker_cache.cache_path(cache_dir, pdf)
    path.parent.mkdir(parents=True)
    path.write_text("{broken", encoding="utf-8")

    assert ocr_worker_cache.load_cached_pdf(cache_dir, pdf) is None


def test_cache_rejects_failed_page_payload(tmp_path):
    pdf = tmp_path / "invoice.pdf"
    pdf.write_bytes(b"pdf")
    payload = _complete_payload()
    payload["file"]["failedPageCount"] = 1

    with pytest.raises(ValueError, match="complete"):
        ocr_worker_cache.store_cached_pdf(tmp_path / "cache", pdf, payload)


def test_cache_file_contains_no_reconciliation_decisions(tmp_path):
    pdf = tmp_path / "invoice.pdf"
    pdf.write_bytes(b"pdf")
    cache_path = ocr_worker_cache.store_cached_pdf(tmp_path / "cache", pdf, _complete_payload())

    envelope = json.loads(cache_path.read_text(encoding="utf-8"))
    assert set(envelope) == {
        "cacheSchemaVersion",
        "ocrSchemaVersion",
        "rowParserSchemaVersion",
        "contentDigest",
        "createdAt",
        "lastAccessedAt",
        "payload",
    }
    assert "nameGate" not in envelope["payload"]
    assert "safeToUse" not in envelope["payload"]


def test_cache_load_updates_last_accessed_time(monkeypatch, tmp_path):
    pdf = tmp_path / "invoice.pdf"
    pdf.write_bytes(b"pdf")
    cache_dir = tmp_path / "cache"
    cache_path = ocr_worker_cache.store_cached_pdf(cache_dir, pdf, _complete_payload())
    before = json.loads(cache_path.read_text(encoding="utf-8"))["lastAccessedAt"]
    monkeypatch.setattr(
        ocr_worker_cache,
        "_utc_now",
        lambda: datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc),
    )

    assert ocr_worker_cache.load_cached_pdf(cache_dir, pdf) is not None

    after = json.loads(cache_path.read_text(encoding="utf-8"))["lastAccessedAt"]
    assert after != before
    assert after == "2026-07-13T12:00:00+00:00"


def test_cache_cleanup_removes_expired_corrupt_and_lru_entries(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    now = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(ocr_worker_cache, "_utc_now", lambda: now)
    paths = []
    for index, age_days in enumerate((40, 10, 1), start=1):
        pdf = tmp_path / f"invoice-{index}.pdf"
        pdf.write_bytes(f"pdf-{index}".encode())
        path = ocr_worker_cache.store_cached_pdf(cache_dir, pdf, _complete_payload(pdf.name))
        envelope = json.loads(path.read_text(encoding="utf-8"))
        envelope["lastAccessedAt"] = (now - timedelta(days=age_days)).isoformat()
        path.write_text(json.dumps(envelope), encoding="utf-8")
        paths.append(path)
    corrupt = cache_dir / "corrupt.json"
    corrupt.write_text("{broken", encoding="utf-8")
    newest_size = paths[2].stat().st_size

    summary = ocr_worker_cache.cleanup_ocr_cache(
        cache_dir,
        retention_days=30,
        max_bytes=newest_size + 10,
        now=now,
    )

    assert not paths[0].exists()
    assert not paths[1].exists()
    assert paths[2].exists()
    assert not corrupt.exists()
    assert summary["expiredEntryCount"] == 1
    assert summary["corruptEntryCount"] == 1
    assert summary["capacityEvictedEntryCount"] == 1
    assert summary["remainingBytes"] <= newest_size + 10
