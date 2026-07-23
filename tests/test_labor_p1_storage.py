from urllib.parse import parse_qs, urlparse
import hashlib

import bonus_platform.engine.labor.persistent_storage as storage


def _configure_supabase(monkeypatch):
    monkeypatch.setenv("SIGMA_LABOR_STORAGE_BACKEND", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role-secret")
    monkeypatch.setenv("SIGMA_LABOR_SUPABASE_BUCKET", "sigma-labor-private")
    monkeypatch.setenv("SIGMA_LABOR_STORAGE_ENV", "uat")


def test_p1_signed_upload_path_is_owner_and_run_scoped_without_upsert(monkeypatch):
    _configure_supabase(monkeypatch)
    requests = []

    def fake_json(method, path, **kwargs):
        requests.append((method, path, kwargs))
        return {
            "url": "/storage/v1/object/upload/sign/sigma-labor-private/path?token=upload-token",
            "token": "upload-token",
        }

    monkeypatch.setattr(storage, "_supabase_json_request", fake_json)

    intent = storage.create_labor_supabase_signed_upload(
        owner_user_id="feishu_user/unsafe",
        run_id="labor-1",
        file_id="file-1",
        filename="invoice ../ July.pdf",
        file_kind="pdf_invoice",
    )

    assert intent["method"] == "PUT"
    assert intent["objectKey"].startswith("labor-runs/uat/owners/feishu_user_unsafe/runs/labor-1/inputs/file-1/")
    assert ".." not in intent["objectKey"]
    assert urlparse(intent["signedUrl"]).netloc == "project.supabase.co"
    assert requests[0][0] == "POST"
    assert requests[0][2]["json_body"] == {"upsert": False}
    assert requests[0][2]["extra_headers"]["x-upsert"] == "false"


def test_p1_signed_download_is_short_lived_and_private(monkeypatch):
    _configure_supabase(monkeypatch)
    requests = []

    def fake_json(method, path, **kwargs):
        requests.append((method, path, kwargs))
        return {"signedURL": "/storage/v1/object/sign/private?token=download-token"}

    monkeypatch.setattr(storage, "_supabase_json_request", fake_json)

    result = storage.create_labor_supabase_signed_download(
        "labor-runs/uat/owners/user-1/runs/labor-1/reports/report.xlsx",
        filename="report.xlsx",
        expires_in=99999,
    )

    assert result["expiresIn"] == 600
    assert result["private"] is True
    assert requests[0][2]["json_body"] == {"expiresIn": 600}
    signed_url = urlparse(result["signedUrl"])
    assert signed_url.netloc == "project.supabase.co"
    assert parse_qs(signed_url.query) == {
        "token": ["download-token"],
        "download": ["report.xlsx"],
    }


def test_p1_signed_upload_for_existing_manifest_object_keeps_exact_key(monkeypatch):
    _configure_supabase(monkeypatch)
    requests = []
    object_key = "labor-runs/uat/owners/user-1/runs/labor-1/inputs/file-1/invoice.pdf"

    def fake_json(method, path, **kwargs):
        requests.append((method, path, kwargs))
        return {"signedURL": "/storage/v1/object/upload/sign/private?token=upload-token"}

    monkeypatch.setattr(storage, "_supabase_json_request", fake_json)

    result = storage.create_labor_supabase_signed_upload_for_object(
        object_key,
        file_kind="pdf_invoice",
        content_type="application/pdf",
    )

    assert result["objectKey"] == object_key
    assert result["method"] == "PUT"
    assert requests[0][2]["json_body"] == {"upsert": False}


def test_p1_object_metadata_uses_service_authenticated_head_without_downloading_file(monkeypatch):
    _configure_supabase(monkeypatch)
    captured = {}
    object_key = "labor-runs/uat/owners/user-1/runs/labor-1/inputs/file-1/invoice.pdf"

    class FakeResponse:
        status_code = 200
        headers = {"content-length": "1024", "content-type": "application/pdf"}

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def request(self, method, url, **kwargs):
            captured.update({"method": method, "url": url, **kwargs})
            return FakeResponse()

    monkeypatch.setattr(storage.httpx, "Client", FakeClient)

    result = storage.labor_supabase_object_metadata(object_key)

    assert result == {
        "objectKey": object_key,
        "sizeBytes": 1024,
        "contentType": "application/pdf",
    }
    assert captured["method"] == "HEAD"
    assert captured["headers"]["authorization"] == "Bearer service-role-secret"


def test_p1_object_metadata_falls_back_to_range_get_when_head_size_is_zero(monkeypatch):
    _configure_supabase(monkeypatch)
    requests = []
    object_key = "labor-runs/uat/owners/user-1/runs/labor-1/outputs/report/business-report.html"

    class FakeResponse:
        def __init__(self, status_code, headers):
            self.status_code = status_code
            self.headers = headers

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def request(self, method, url, **kwargs):
            requests.append((method, url, kwargs))
            if method == "HEAD":
                return FakeResponse(200, {"content-length": "0", "content-type": "text/html"})
            return FakeResponse(
                206,
                {"content-range": "bytes 0-0/58314", "content-length": "1", "content-type": "text/html"},
            )

    monkeypatch.setattr(storage.httpx, "Client", FakeClient)

    result = storage.labor_supabase_object_metadata(object_key)

    assert result["sizeBytes"] == 58314
    assert result["contentType"] == "text/html"
    assert [method for method, _, _ in requests] == ["HEAD", "GET"]
    assert requests[1][2]["headers"]["range"] == "bytes=0-0"


def test_p1_storage_health_requires_private_bucket_and_full_direct_probe(monkeypatch):
    _configure_supabase(monkeypatch)
    monkeypatch.setattr(storage, "_supabase_bucket_info", lambda: {"id": "sigma-labor-private", "public": False})
    monkeypatch.setattr(
        storage,
        "_probe_supabase_direct_storage",
        lambda: {
            "writeReadDelete": True,
            "directUpload": True,
            "directDownload": True,
        },
    )

    health = storage.labor_persistent_storage_health(probe=True, cache_seconds=0)

    assert health["ready"] is True
    assert health["private"] is True
    assert health["writeReadDelete"] is True
    assert health["directUpload"] is True
    assert health["directDownload"] is True
    assert "service-role-secret" not in str(health)


def test_p1_storage_health_rejects_public_bucket(monkeypatch):
    _configure_supabase(monkeypatch)
    monkeypatch.setattr(storage, "_supabase_bucket_info", lambda: {"id": "sigma-labor-private", "public": True})
    called = []
    monkeypatch.setattr(storage, "_probe_supabase_direct_storage", lambda: called.append(True))

    health = storage.labor_persistent_storage_health(probe=True, cache_seconds=0)

    assert health["ready"] is False
    assert health["private"] is False
    assert health["errorType"] == "public_bucket_forbidden"
    assert called == []


def test_p1_storage_probe_confirms_delete_from_authoritative_list_not_cached_get(monkeypatch):
    _configure_supabase(monkeypatch)
    object_key = (
        "labor-runs/uat/owners/_health/runs/health-cached/"
        "inputs/file-1/storage-health.json"
    )
    deleted = []
    stored = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        @property
        def content(self):
            return stored["payload"]

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def put(self, *_args, **kwargs):
            stored["payload"] = bytes(kwargs["content"])
            return FakeResponse()

        def get(self, *_args, **_kwargs):
            return FakeResponse()

    monkeypatch.setattr(storage.httpx, "Client", FakeClient)
    monkeypatch.setattr(
        storage,
        "create_labor_supabase_signed_upload",
        lambda **_kwargs: {
            "objectKey": object_key,
            "signedUrl": "https://project.supabase.co/upload",
            "headers": {"content-type": "application/json"},
        },
    )
    monkeypatch.setattr(
        storage,
        "create_labor_supabase_signed_download",
        lambda *_args, **_kwargs: {"signedUrl": "https://project.supabase.co/download"},
    )
    monkeypatch.setattr(storage, "_supabase_download_bytes", lambda _key: stored["payload"])
    monkeypatch.setattr(storage, "_supabase_delete_objects", lambda keys: deleted.extend(keys))
    monkeypatch.setattr(storage, "_supabase_list_objects", lambda _prefix: [])

    result = storage._probe_supabase_direct_storage()

    assert result == {
        "writeReadDelete": True,
        "directUpload": True,
        "directDownload": True,
    }
    assert deleted == [object_key]


def test_p1_worker_output_is_uploaded_to_owner_scoped_private_object_and_verified(monkeypatch, tmp_path):
    _configure_supabase(monkeypatch)
    report = tmp_path / "result.xlsx"
    report.write_bytes(b"formal-report")
    digest = hashlib.sha256(report.read_bytes()).hexdigest()
    uploaded = {}

    def upload(object_key, content, *, content_type):
        uploaded.update({"objectKey": object_key, "content": content, "contentType": content_type})
        return {}

    monkeypatch.setattr(storage, "_supabase_upload_bytes", upload)
    monkeypatch.setattr(
        storage,
        "labor_supabase_object_metadata",
        lambda object_key: {
            "objectKey": object_key,
            "sizeBytes": len(b"formal-report"),
            "contentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        },
    )

    result = storage.persist_labor_private_output(
        owner_user_id="user-1",
        run_id="labor-1",
        output_kind="diff_report",
        path=report,
        expected_sha256=digest,
        expected_size_bytes=len(b"formal-report"),
    )

    assert uploaded["content"] == b"formal-report"
    assert uploaded["objectKey"].startswith("labor-runs/uat/owners/user-1/runs/labor-1/outputs/")
    assert result["objectKey"] == uploaded["objectKey"]
    assert result["storageVerified"] is True
    assert result["sha256"] == digest
