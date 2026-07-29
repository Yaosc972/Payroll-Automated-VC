from pathlib import Path
import json
import shutil
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

import bonus_platform.engine.labor.persistent_storage as storage
import bonus_platform.engine.labor.blob_storage as blob


def test_persistent_upload_retries_transient_failure(monkeypatch, tmp_path):
    attempts = []
    monkeypatch.setattr(storage, "labor_supabase_storage_enabled", lambda: True)
    monkeypatch.setattr(storage.time, "sleep", lambda _: None)

    def flaky(run_id, run_dir):
        attempts.append(run_id)
        if len(attempts) < 3:
            raise storage.httpx.TimeoutException("timeout")

    monkeypatch.setattr(storage, "sync_labor_run_to_supabase", flaky)

    storage.sync_labor_run_to_persistent("labor_1", tmp_path)
    assert attempts == ["labor_1", "labor_1", "labor_1"]


def test_persistent_delete_is_idempotent_when_remote_is_missing(monkeypatch):
    monkeypatch.setattr(storage, "labor_supabase_storage_enabled", lambda: True)
    calls = []
    monkeypatch.setattr(
        storage,
        "delete_labor_run_from_supabase",
        lambda run_id, owner_user_id="": calls.append((run_id, owner_user_id)),
    )

    storage.delete_labor_run_from_persistent("labor_missing")
    storage.delete_labor_run_from_persistent("labor_missing")

    assert calls == [("labor_missing", ""), ("labor_missing", "")]


def test_p1_delete_removes_legacy_and_owner_scoped_supabase_objects(monkeypatch):
    remote = {
        "labor-runs/uat/labor-1/metadata.json": b"legacy",
        "labor-runs/uat/owners/user-1/runs/labor-1/inputs/file-1/invoice.pdf": b"input",
        "labor-runs/uat/owners/user-1/runs/labor-1/outputs/diff/report.xlsx": b"output",
        "labor-runs/uat/owners/user-2/runs/labor-1/inputs/file-2/other.pdf": b"other-owner",
        "labor-runs/uat/owners/user-1/runs/labor-2/inputs/file-3/other.pdf": b"other-run",
    }
    monkeypatch.setenv("SIGMA_LABOR_STORAGE_BACKEND", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://storage.test")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "secret")
    monkeypatch.setenv("SIGMA_LABOR_SUPABASE_BUCKET", "labor")
    monkeypatch.setenv("SIGMA_LABOR_STORAGE_ENV", "uat")
    monkeypatch.setattr(storage.httpx, "Client", lambda **_: FakeSupabaseClient(remote))

    storage.delete_labor_run_from_persistent("labor-1", owner_user_id="user-1")

    assert remote == {
        "labor-runs/uat/owners/user-2/runs/labor-1/inputs/file-2/other.pdf": b"other-owner",
        "labor-runs/uat/owners/user-1/runs/labor-2/inputs/file-3/other.pdf": b"other-run",
    }


def test_persistent_download_does_not_retry_non_transient_error(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "labor_supabase_storage_enabled", lambda: True)
    attempts = []

    def invalid(*_):
        attempts.append(1)
        raise ValueError("invalid manifest")

    monkeypatch.setattr(storage, "sync_labor_run_from_supabase", invalid)
    with pytest.raises(ValueError, match="invalid manifest"):
        storage.sync_labor_run_from_persistent("labor_1", Path(tmp_path))
    assert len(attempts) == 1


def test_supabase_full_lifecycle_upload_restart_restore_idempotent_and_delete(monkeypatch, tmp_path):
    remote: dict[str, bytes] = {}
    monkeypatch.setenv("SIGMA_LABOR_STORAGE_BACKEND", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://storage.test")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "secret")
    monkeypatch.setenv("SIGMA_LABOR_SUPABASE_BUCKET", "labor")
    monkeypatch.setenv("SIGMA_LABOR_STORAGE_ENV", "uat")
    monkeypatch.setattr(storage.httpx, "Client", lambda **_: FakeSupabaseClient(remote))

    run_id = "labor_restart"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    pdf = run_dir / "invoice.pdf"
    excel = run_dir / "bill.xlsx"
    report = run_dir / "reports" / "report.html"
    report.parent.mkdir()
    pdf.write_bytes(b"pdf-content")
    excel.write_bytes(b"excel-content")
    report.write_text("report-content", encoding="utf-8")
    (run_dir / "metadata.json").write_text(
        json.dumps(
            {
                "id": run_id,
                "files": {
                    "pdfInvoices": [{"path": str(pdf), "filename": pdf.name}],
                    "workbooks": [{"path": str(excel), "filename": excel.name}],
                    "businessReport": {"path": str(report), "filename": report.name},
                },
            }
        ),
        encoding="utf-8",
    )

    storage.sync_labor_run_to_persistent(run_id, run_dir)
    first_snapshot = dict(remote)
    assert set(remote) == {
        "labor-runs/uat/labor_restart/bill.xlsx",
        "labor-runs/uat/labor_restart/invoice.pdf",
        "labor-runs/uat/labor_restart/metadata.json",
        "labor-runs/uat/labor_restart/reports/report.html",
    }
    assert storage._supabase_list_objects("labor-runs/uat/labor_restart")
    storage.sync_labor_run_to_persistent(run_id, run_dir)
    assert remote == first_snapshot

    shutil.rmtree(run_dir)
    assert storage.sync_labor_run_from_persistent(run_id, run_dir) is True
    assert (run_dir / "invoice.pdf").read_bytes() == b"pdf-content"
    assert (run_dir / "bill.xlsx").read_bytes() == b"excel-content"
    assert (run_dir / "reports" / "report.html").read_text() == "report-content"
    metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["files"]["pdfInvoices"][0]["path"] == str(run_dir / "invoice.pdf")

    storage.delete_labor_run_from_persistent(run_id)
    assert remote == {}
    storage.delete_labor_run_from_persistent(run_id)
    assert remote == {}


class FakeSupabaseClient:
    def __init__(self, remote: dict[str, bytes]):
        self.remote = remote

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def post(self, url, *, headers=None, content=None, json=None):
        path = httpx.URL(url).path
        if "/object/list/" in path:
            prefix = str((json or {}).get("prefix") or "").rstrip("/")
            offset = int((json or {}).get("offset") or 0)
            limit = int((json or {}).get("limit") or 1000)
            names = [key[len(prefix) + 1 :] for key in sorted(self.remote) if key.startswith(prefix + "/")]
            return self._response("POST", url, 200, json_body=[{"name": name} for name in names[offset : offset + limit]])
        marker = "/object/labor/"
        object_path = path.split(marker, 1)[1]
        self.remote[object_path] = bytes(content or b"")
        return self._response("POST", url, 200, json_body={"Key": object_path})

    def get(self, url, *, headers=None):
        marker = "/object/labor/"
        object_path = httpx.URL(url).path.split(marker, 1)[1]
        if object_path not in self.remote:
            return self._response("GET", url, 404)
        return self._response("GET", url, 200, content=self.remote[object_path])

    def request(self, method, url, *, headers=None, json=None):
        if method == "DELETE":
            for path in (json or {}).get("prefixes", []):
                self.remote.pop(path, None)
            return self._response(method, url, 200, json_body={})
        raise AssertionError((method, url))

    @staticmethod
    def _response(method, url, status, *, content=b"", json_body=None):
        request = httpx.Request(method, url)
        return httpx.Response(status, request=request, json=json_body) if json_body is not None else httpx.Response(status, request=request, content=content)


def test_blob_full_lifecycle_upload_restart_restore_idempotent_and_delete(monkeypatch, tmp_path):
    remote: dict[str, bytes] = {}
    monkeypatch.setenv("SIGMA_LABOR_STORAGE_BACKEND", "blob")
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "vercel_blob_rw_teststore_secret")
    monkeypatch.setenv("SIGMA_LABOR_BLOB_ENV", "uat")
    monkeypatch.setattr(blob.httpx, "Client", lambda **_: FakeBlobClient(remote))

    run_id = "labor_blob_restart"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    (run_dir / "invoice.pdf").write_bytes(b"pdf")
    (run_dir / "bill.xlsx").write_bytes(b"excel")
    (run_dir / "report.html").write_bytes(b"report")
    (run_dir / "metadata.json").write_text(json.dumps({"id": run_id, "files": {}}), encoding="utf-8")

    storage.sync_labor_run_to_persistent(run_id, run_dir)
    first = dict(remote)
    storage.sync_labor_run_to_persistent(run_id, run_dir)
    assert remote == first

    shutil.rmtree(run_dir)
    assert storage.sync_labor_run_from_persistent(run_id, run_dir) is True
    assert (run_dir / "invoice.pdf").read_bytes() == b"pdf"
    assert (run_dir / "bill.xlsx").read_bytes() == b"excel"
    assert (run_dir / "report.html").read_bytes() == b"report"

    storage.delete_labor_run_from_persistent(run_id)
    assert remote == {}


class FakeBlobClient:
    def __init__(self, remote: dict[str, bytes]):
        self.remote = remote

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def request(self, method, url, *, headers=None, content=None, json=None):
        parsed = httpx.URL(url)
        if method == "PUT":
            pathname = parsed.params.get("pathname")
            self.remote[pathname] = bytes(content or b"")
            return self._response(method, url, 200, {"pathname": pathname, "url": self._url(pathname)})
        if method == "GET":
            prefix = parsed.params.get("prefix") or ""
            blobs = [
                {"pathname": key, "url": self._url(key), "uploadedAt": "2026-07-13T12:00:00Z"}
                for key in sorted(self.remote) if key.startswith(prefix)
            ]
            return self._response(method, url, 200, {"blobs": blobs, "hasMore": False})
        if method == "POST" and parsed.path.endswith("/delete"):
            for target in (json or {}).get("urls", []):
                pathname = target.rsplit("/", 1)[-1] if "/" not in target.removeprefix("https://") else target.split("blob.test/", 1)[-1]
                self.remote.pop(pathname, None)
            return self._response(method, url, 200, {})
        raise AssertionError((method, url))

    def get(self, url, *, headers=None):
        pathname = str(url).split("blob.test/", 1)[-1]
        if pathname not in self.remote:
            return self._response("GET", url, 404, None)
        request = httpx.Request("GET", url)
        return httpx.Response(200, request=request, content=self.remote[pathname])

    @staticmethod
    def _url(pathname: str) -> str:
        return f"https://blob.test/{pathname}"

    @staticmethod
    def _response(method, url, status, payload):
        request = httpx.Request(method, url)
        return httpx.Response(status, request=request, json=payload) if payload is not None else httpx.Response(status, request=request)

def test_blob_put_signed_url_preserves_the_exact_release_path(monkeypatch):
    captured = {}

    def fake_request(method, query="", **kwargs):
        captured.update({"method": method, "query": query, **kwargs})
        return {
            "delegationToken": "eyJzdG9yZUlkIjoic3RvcmVfdGVzdCJ9.signature",
            "clientSigningToken": "test-signing-token",
        }

    monkeypatch.setattr(blob, "_blob_request", fake_request)

    signed_url = blob.create_labor_blob_presigned_url(
        "labor-runs/uat/owners/system/worker-releases/windows-x64/worker.exe",
        operation="put",
    )

    assert parse_qs(urlparse(signed_url).query)["vercel-blob-add-random-suffix"] == ["false"]


def test_blob_put_bytes_preserves_the_exact_pathname(monkeypatch):
    captured = {}

    def fake_request(method, query="", **kwargs):
        captured.update({"method": method, "query": query, **kwargs})
        return {"pathname": "labor-runs/uat/owners/system/worker-releases/manifest.json"}

    monkeypatch.setattr(blob, "_blob_request", fake_request)

    blob.blob_put_bytes(
        "labor-runs/uat/owners/system/worker-releases/manifest.json",
        b"{}",
        content_type="application/json",
    )

    assert captured["headers"]["x-add-random-suffix"] == "0"
    assert captured["headers"]["x-allow-overwrite"] == "1"
