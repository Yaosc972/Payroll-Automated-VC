import hashlib
import pytest
from fastapi.testclient import TestClient
import bonus_platform.app as module


def test_local_release_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setattr(module, "LABOR_RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(module, "_local_worker_releases_enabled", lambda: True)
    monkeypatch.setattr(module, "labor_blob_signed_urls_enabled", lambda: False)
    monkeypatch.setattr(module, "labor_persistent_storage_enabled", lambda: False)
    monkeypatch.setattr(module, "_labor_request_actor", lambda request: ({}, True))
    monkeypatch.setattr(module, "labor_auth_required", lambda: False)
    data = b"test installer fixture"
    digest = hashlib.sha256(data).hexdigest()
    client = TestClient(module.app)
    url = f"/api/labor/worker/release/local-upload?platform=macos-arm64&version=0.3.16&sha256={digest}&size={len(data)}"
    assert client.put(url, content=data).status_code == 200
    assert client.put(url, content=data).status_code == 409
    filename = module._labor_worker_release_filename("macos-arm64", "0.3.16")
    artifact = module._verify_labor_worker_release_artifact(platform="macos-arm64", version="0.3.16", filename=filename, size_bytes=len(data))
    assert artifact["verifiedSha256"] == digest
    manifest = {"releases": {"macos-arm64": {**artifact, "version": "0.3.16", "filename": filename, "sha256": digest, "signature": f"sha256:{digest}"}}}
    module._persist_labor_worker_release_manifest(manifest)
    assert module._load_persisted_labor_worker_release_manifest() == manifest
    assert module._labor_public_worker_release()["available"] is True
    assert client.get("/api/labor/worker/release/download").content == data
    with pytest.raises(Exception):
        module._local_worker_release_path("../escape")


def test_local_upload_rejects_bad_hash(monkeypatch, tmp_path):
    monkeypatch.setattr(module, "LABOR_RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(module, "_local_worker_releases_enabled", lambda: True)
    monkeypatch.setattr(module, "_labor_request_actor", lambda request: ({}, True))
    response = TestClient(module.app).put(
        '/api/labor/worker/release/local-upload?platform=macos-arm64&version=0.3.16&sha256=' + '0' * 64 + '&size=3', content=b'abc'
    )
    assert response.status_code == 409
    assert not list(tmp_path.rglob('*.dmg'))
