from pathlib import Path
import json

import httpx
import pytest

from bonus_platform.engine.labor import blob_storage


def test_labor_blob_store_id_parses_rw_token(monkeypatch):
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "vercel_blob_rw_qqD75P7a2QuwEh0S_abcd1234")
    monkeypatch.delenv("BLOB_STORE_ID", raising=False)
    assert blob_storage.labor_blob_store_id() == "store_qqD75P7a2QuwEh0S"


def test_labor_blob_paths_are_scoped_by_environment(monkeypatch):
    monkeypatch.setenv("SIGMA_LABOR_BLOB_ENV", "uat")

    assert blob_storage.labor_blob_run_prefix("labor_1") == "labor-runs/uat/labor_1"
    assert blob_storage.labor_blob_path("labor_1", "/nested/report.xlsx") == "labor-runs/uat/labor_1/nested/report.xlsx"
    assert blob_storage.labor_blob_relative_path("labor_1", "labor-runs/uat/labor_1/nested/report.xlsx") == "nested/report.xlsx"


def test_labor_metadata_path_roundtrip_between_local_and_blob(tmp_path: Path):
    run_dir = tmp_path / "labor_123"
    run_dir.mkdir(parents=True)
    metadata = {
        "id": "labor_123",
        "files": {
            "pdfInvoices": [
                {
                    "filename": "invoice.pdf",
                    "path": str(run_dir / "invoice.pdf"),
                }
            ],
            "workbook": {
                "filename": "bill.xlsx",
                "path": str(run_dir / "nested" / "bill.xlsx"),
            },
        },
    }
    canonical = blob_storage.canonicalize_labor_metadata_for_blob(run_dir, metadata)
    assert canonical["files"]["pdfInvoices"][0]["path"] == "invoice.pdf"
    assert canonical["files"]["workbook"]["path"] == "nested/bill.xlsx"

    materialized = blob_storage.materialize_labor_metadata_for_local(run_dir, canonical)
    assert materialized["files"]["pdfInvoices"][0]["path"] == str(run_dir / "invoice.pdf")
    assert materialized["files"]["workbook"]["path"] == str(run_dir / "nested" / "bill.xlsx")


def test_latest_blob_entries_keeps_newest_uploaded_at():
    blobs = [
        {"pathname": "labor-runs/local/labor_1/metadata.json", "uploadedAt": "2026-06-17T06:00:06.000Z", "url": "old"},
        {"pathname": "labor-runs/local/labor_1/metadata.json", "uploadedAt": "2026-06-17T06:00:15.000Z", "url": "new"},
        {"pathname": "labor-runs/local/labor_1/bill.xlsx", "uploadedAt": "2026-06-17T06:00:10.000Z", "url": "bill"},
    ]

    latest = {row["pathname"]: row for row in blob_storage._latest_blob_entries(blobs)}
    assert latest["labor-runs/local/labor_1/metadata.json"]["url"] == "new"
    assert latest["labor-runs/local/labor_1/bill.xlsx"]["url"] == "bill"


def test_sync_labor_run_from_blob_does_not_delete_existing_run_dir(monkeypatch, tmp_path: Path):
    run_id = "labor_1"
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True)
    existing = run_dir / "keep.txt"
    existing.write_text("keep", encoding="utf-8")

    monkeypatch.setattr(
        blob_storage,
        "labor_blob_storage_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        blob_storage,
        "blob_list_prefix",
        lambda prefix: [
            {
                "pathname": f"labor-runs/local/{run_id}/metadata.json",
                "uploadedAt": "2026-06-17T06:00:15.000Z",
                "url": "blob://metadata",
            }
        ],
    )
    monkeypatch.setattr(
        blob_storage,
        "blob_get_bytes",
        lambda url: b'{"id":"labor_1","files":{}}',
    )

    assert blob_storage.sync_labor_run_from_blob(run_id, run_dir) is True
    assert existing.exists()
    assert (run_dir / "metadata.json").exists()


def test_sync_labor_run_from_blob_materializes_metadata_file_paths(monkeypatch, tmp_path: Path):
    run_id = "labor_2"
    run_dir = tmp_path / run_id
    metadata_blob = {
        "id": run_id,
        "files": {
            "businessReport": {
                "filename": "business.html",
                "path": "reports/business.html",
            },
            "diffReport": {
                "filename": "diff.xlsx",
                "path": "diff.xlsx",
            },
        },
    }
    blob_payloads = {
        "blob://metadata": json.dumps(metadata_blob, ensure_ascii=False).encode("utf-8"),
        "blob://business": b"<html>business</html>",
        "blob://diff": b"diff",
    }

    monkeypatch.setattr(blob_storage, "labor_blob_storage_enabled", lambda: True)
    monkeypatch.setattr(
        blob_storage,
        "blob_list_prefix",
        lambda prefix: [
            {
                "pathname": f"labor-runs/local/{run_id}/metadata.json",
                "uploadedAt": "2026-06-17T06:00:15.000Z",
                "url": "blob://metadata",
            },
            {
                "pathname": f"labor-runs/local/{run_id}/reports/business.html",
                "uploadedAt": "2026-06-17T06:00:16.000Z",
                "url": "blob://business",
            },
            {
                "pathname": f"labor-runs/local/{run_id}/diff.xlsx",
                "uploadedAt": "2026-06-17T06:00:17.000Z",
                "url": "blob://diff",
            },
        ],
    )
    monkeypatch.setattr(blob_storage, "blob_get_bytes", lambda url: blob_payloads[url])

    assert blob_storage.sync_labor_run_from_blob(run_id, run_dir) is True

    restored_metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    assert restored_metadata["files"]["businessReport"]["path"] == str(run_dir / "reports" / "business.html")
    assert restored_metadata["files"]["diffReport"]["path"] == str(run_dir / "diff.xlsx")
    assert Path(restored_metadata["files"]["businessReport"]["path"]).exists()
    assert Path(restored_metadata["files"]["diffReport"]["path"]).exists()


def test_labor_blob_sync_roundtrip_restores_reports_with_current_run_dir(monkeypatch, tmp_path: Path):
    run_id = "labor_roundtrip"
    source_dir = tmp_path / "source" / run_id
    source_dir.mkdir(parents=True)
    (source_dir / "reports").mkdir()
    (source_dir / "reports" / "business.html").write_text("<html>business</html>", encoding="utf-8")
    (source_dir / "diff.xlsx").write_bytes(b"diff")
    (source_dir / "metadata.json").write_text(
        json.dumps(
            {
                "id": run_id,
                "files": {
                    "businessReport": {
                        "filename": "business.html",
                        "path": str(source_dir / "reports" / "business.html"),
                    },
                    "diffReport": {
                        "filename": "diff.xlsx",
                        "path": str(source_dir / "diff.xlsx"),
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    blob_payloads: dict[str, bytes] = {}

    def fake_blob_put_bytes(pathname: str, content: bytes, **kwargs):
        blob_payloads[pathname] = content
        return {"pathname": pathname, "url": f"blob://{pathname}"}

    def fake_blob_list_prefix(prefix: str):
        return [
            {
                "pathname": pathname,
                "uploadedAt": f"2026-06-17T06:00:{index:02d}.000Z",
                "url": f"blob://{pathname}",
            }
            for index, pathname in enumerate(sorted(blob_payloads), start=1)
            if pathname.startswith(prefix)
        ]

    monkeypatch.setattr(blob_storage, "labor_blob_storage_enabled", lambda: True)
    monkeypatch.setattr(blob_storage, "blob_put_bytes", fake_blob_put_bytes)
    monkeypatch.setattr(blob_storage, "blob_list_prefix", fake_blob_list_prefix)
    monkeypatch.setattr(blob_storage, "blob_get_bytes", lambda url: blob_payloads[url.removeprefix("blob://")])

    blob_storage.sync_labor_run_to_blob(run_id, source_dir)
    restored_dir = tmp_path / "restored" / run_id

    assert blob_storage.sync_labor_run_from_blob(run_id, restored_dir) is True

    restored_metadata = json.loads((restored_dir / "metadata.json").read_text(encoding="utf-8"))
    business_path = Path(restored_metadata["files"]["businessReport"]["path"])
    diff_path = Path(restored_metadata["files"]["diffReport"]["path"])
    assert business_path == restored_dir / "reports" / "business.html"
    assert diff_path == restored_dir / "diff.xlsx"
    assert business_path.read_text(encoding="utf-8") == "<html>business</html>"
    assert diff_path.read_bytes() == b"diff"


def test_blob_put_bytes_wraps_permission_failure(monkeypatch):
    def fake_blob_request(*args, **kwargs):
        request = httpx.Request("PUT", "https://example.test/blob")
        response = httpx.Response(403, request=request, json={"error": {"message": "forbidden"}})
        raise httpx.HTTPStatusError("forbidden", request=request, response=response)

    monkeypatch.setattr(blob_storage, "_blob_request", fake_blob_request)

    with pytest.raises(blob_storage.LaborBlobError) as exc_info:
        blob_storage.blob_put_bytes("labor-runs/local/labor_1/report.xlsx", b"report")

    assert exc_info.value.code == "LABOR_BLOB_PERMISSION_DENIED"
    assert exc_info.value.retryable is False
    assert "权限" in str(exc_info.value)


def test_blob_list_prefix_wraps_timeout(monkeypatch):
    def fake_blob_request(*args, **kwargs):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(blob_storage, "_blob_request", fake_blob_request)

    with pytest.raises(blob_storage.LaborBlobError) as exc_info:
        blob_storage.blob_list_prefix("labor-runs/local/")

    assert exc_info.value.code == "LABOR_BLOB_TIMEOUT"
    assert exc_info.value.retryable is True
    assert "超时" in str(exc_info.value)
