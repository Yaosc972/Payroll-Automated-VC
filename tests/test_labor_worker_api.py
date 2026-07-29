import json
import hashlib
import asyncio
import zipfile
from io import BytesIO

from fastapi.testclient import TestClient
import pytest

import bonus_platform.app as app_module
import bonus_platform.engine.labor.worker_jobs as jobs
import bonus_platform.engine.labor.worker_archive as worker_archive
import bonus_platform.engine.labor.runs as labor_runs
from bonus_platform.app import app


CURRENT_WORKER_VERSION = app_module.OVERSEAS_LABOR_REQUIRED_WORKER_VERSION


def _configure(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "LABOR_WORKER_JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setenv(
        "SIGMA_LABOR_WORKER_TOKENS",
        json.dumps(
            {
                "token-user-1": {"userId": "user-1", "deviceId": "device-a"},
                "token-user-2": {"userId": "user-2", "deviceId": "device-b"},
            }
        ),
    )
    return TestClient(app)


def test_worker_api_rejects_missing_and_unknown_token(monkeypatch, tmp_path):
    client = _configure(monkeypatch, tmp_path)
    assert client.post("/api/labor/worker/jobs/claim").status_code == 401
    assert client.post(
        "/api/labor/worker/jobs/claim",
        headers={"authorization": "Bearer unknown"},
    ).status_code == 401


def test_worker_api_claims_only_token_owner_job(monkeypatch, tmp_path):
    client = _configure(monkeypatch, tmp_path)
    jobs.enqueue_labor_worker_job("labor_other", owner_user_id="user-2")
    own = jobs.enqueue_labor_worker_job("labor_own", owner_user_id="user-1")

    response = client.post(
        "/api/labor/worker/jobs/claim",
        headers={"authorization": "Bearer token-user-1", "x-worker-version": CURRENT_WORKER_VERSION},
    )

    assert response.status_code == 200
    assert response.json()["job"]["id"] == own["id"]
    assert "ownerUserId" not in response.json()["job"]


def test_run_status_exposes_active_mapping_preflight_worker_progress(monkeypatch):
    monkeypatch.setenv("SIGMA_LABOR_EXECUTION_MODE", "personal-worker")
    monkeypatch.setattr(
        app_module,
        "list_labor_worker_jobs",
        lambda: [
            {
                "id": "mapping-job-1",
                "runId": "labor-preflight",
                "jobType": "mapping_preflight",
                "taskGenerationId": "mapping-generation-1",
                "status": "running",
                "progress": {
                    "phase": "reading_workbook",
                    "message": "正在读取工作表",
                },
                "updatedAt": "2026-07-25T16:00:00Z",
            }
        ],
    )

    enriched = app_module._with_personal_worker_status(
        {
            "id": "labor-preflight",
            "mappingPreflight": {
                "status": "running",
                "taskGenerationId": "mapping-generation-1",
            },
        }
    )

    assert enriched["workerTask"]["id"] == "mapping-job-1"
    assert enriched["workerTask"]["progress"]["phase"] == "reading_workbook"
    assert "asyncTask" not in enriched


def test_run_status_survives_transient_worker_queue_lookup_failure(monkeypatch):
    monkeypatch.setenv("SIGMA_LABOR_EXECUTION_MODE", "personal-worker")

    def unavailable():
        raise RuntimeError("temporary queue lookup failure")

    monkeypatch.setattr(app_module, "list_labor_worker_jobs", unavailable)
    metadata = {"id": "labor-uploaded", "status": "已创建"}

    assert app_module._with_personal_worker_status(metadata) == metadata


def test_p1_mapping_preflight_round_trip_persists_worker_proposal_for_user_confirmation(monkeypatch, tmp_path):
    client = _configure(monkeypatch, tmp_path)
    monkeypatch.setenv("SIGMA_LABOR_EXECUTION_MODE", "personal-worker")
    monkeypatch.setattr(labor_runs, "LABOR_RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(app_module, "LABOR_RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(app_module, "_labor_audit_path", lambda: tmp_path / "audit.jsonl")
    run_dir = tmp_path / "runs" / "labor_preflight"
    run_dir.mkdir(parents=True)
    workbook_sha = "a" * 64
    metadata = {
        "id": "labor_preflight",
        "ownerUserId": "user-1",
        "status": "已上传文件",
        "files": {
            "pdfInvoices": [
                {
                    "id": "pdf-1",
                    "objectKey": "labor-runs/uat/pdf-1/invoice.pdf",
                    "uploadState": "ready",
                    "sizeBytes": 100,
                    "sha256": "b" * 64,
                }
            ],
            "workbooks": [
                {
                    "id": "xlsx-1",
                    "objectKey": "labor-runs/uat/xlsx-1/bill.xlsx",
                    "originalFilename": "bill.xlsx",
                    "uploadState": "ready",
                    "sizeBytes": 200,
                    "sha256": workbook_sha,
                }
            ],
        },
    }
    (run_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    access = client.get("/api/labor/access").json()
    browser_headers = {
        "x-sigma-labor-api-contract": str(access["apiContractVersion"]),
        "x-sigma-labor-ui-version": str(access["version"]),
        "x-sigma-labor-ui-build": str(access["buildId"]),
    }

    started = client.post(
        "/api/labor/runs/labor_preflight/mapping-preflight",
        headers=browser_headers,
        json={},
    )
    assert started.status_code == 200
    generation = started.json()["mappingPreflight"]["taskGenerationId"]
    job = started.json()["workerTask"]
    assert job["jobType"] == "mapping_preflight"

    claimed = client.post(
        "/api/labor/worker/jobs/claim",
        headers={"authorization": "Bearer token-user-1", "x-worker-version": CURRENT_WORKER_VERSION},
    )
    assert claimed.status_code == 200
    assert claimed.json()["job"]["id"] == job["id"]
    current = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    fingerprint = current["mappingPreflight"]["inputFingerprint"]

    proposal = client.post(
        f"/api/labor/worker/jobs/{job['id']}/mapping-preflight-result",
        headers={"authorization": "Bearer token-user-1", "x-worker-version": CURRENT_WORKER_VERSION},
        json={
            "inputFingerprint": fingerprint,
            "workbooks": [
                {
                    "fileId": "xlsx-1",
                    "sheets": [
                        {
                            "name": "员工账单",
                            "suggestion": {
                                "headers": ["姓名", "工时", "金额"],
                                "suggestedMapping": {
                                    "employeeId": "",
                                    "name": "姓名",
                                    "hours": "工时",
                                    "amount": "金额",
                                    "currency": "",
                                },
                                "amountColumnCandidates": ["金额"],
                                "previewRows": [{"姓名": "Alice", "工时": 8, "金额": 100}],
                            },
                        },
                        {
                            "name": "汇总",
                            "suggestion": {
                                "headers": ["人数", "总金额"],
                                "suggestedMapping": {
                                    "employeeId": "",
                                    "name": "人数",
                                    "hours": "总金额",
                                    "amount": "总金额",
                                    "currency": "",
                                },
                                "amountColumnCandidates": ["总金额"],
                                "previewRows": [{"人数": 1, "总金额": 100}],
                            },
                        },
                    ],
                }
            ],
        },
    )
    assert proposal.status_code == 200
    assert proposal.json()["mappingPreflight"]["taskGenerationId"] == generation

    revalidated = client.post(
        "/api/labor/runs/labor_preflight/mapping-preflight",
        headers=browser_headers,
        json={},
    )
    assert revalidated.status_code == 200
    assert revalidated.json()["started"] is False
    assert revalidated.json()["mappingPreflight"]["status"] == "completed"
    assert revalidated.json()["mappingPreflight"]["taskGenerationId"] == generation

    sheets = client.get("/api/labor/runs/labor_preflight/workbook-sheets")
    suggestion = client.post(
        "/api/labor/runs/labor_preflight/field-suggestions",
        headers=browser_headers,
        json={"sheet_name": "员工账单"},
    )
    completed = client.post(
        f"/api/labor/worker/jobs/{job['id']}/complete",
        headers={"authorization": "Bearer token-user-1", "x-worker-version": CURRENT_WORKER_VERSION},
    )

    assert sheets.json() == {
        "sheets": ["员工账单", "汇总"],
        "fileCount": 1,
        "source": "personal_worker_preflight",
    }
    assert suggestion.json()["suggestedMapping"]["name"] == "姓名"
    assert completed.status_code == 200
    assert completed.json()["job"]["status"] == "succeeded"

    stale_mapping = client.post(
        "/api/labor/runs/labor_preflight/mapping",
        headers=browser_headers,
        json={
            "sheet_name": "员工账单",
            "mapping": {"name": "人数", "hours": "总金额", "amount": "总金额"},
        },
    )
    assert stale_mapping.status_code == 400
    assert "所选工作表不包含字段" in stale_mapping.json()["detail"]

    mapped = client.post(
        "/api/labor/runs/labor_preflight/mapping",
        headers=browser_headers,
        json={
            "sheet_name": "员工账单",
            "mapping": {"name": "姓名", "hours": "工时", "amount": "金额"},
        },
    )
    submitted = client.post(
        "/api/labor/runs/labor_preflight/extract-and-compare",
        headers=browser_headers,
    )
    assert mapped.status_code == 200
    assert submitted.status_code == 200
    assert submitted.json()["workerTask"]["jobType"] == "reconcile"


def test_mapping_preflight_rejects_malformed_worker_arrays_without_server_error():
    metadata = {
        "files": {
            "workbooks": [
                {
                    "id": "xlsx-1",
                    "objectKey": "labor-runs/uat/xlsx-1/bill.xlsx",
                    "originalFilename": "bill.xlsx",
                    "uploadState": "ready",
                    "sizeBytes": 200,
                    "sha256": "a" * 64,
                }
            ]
        }
    }
    payload = {
        "workbooks": [
            {
                "fileId": "xlsx-1",
                "sheets": [
                    {
                        "name": "员工账单",
                        "suggestion": {
                            "headers": {"unexpected": "object"},
                            "suggestedMapping": {},
                            "amountColumnCandidates": [],
                            "previewRows": [],
                        },
                    }
                ],
            }
        ]
    }

    with pytest.raises(jobs.LaborWorkerLeaseError, match="列名列表格式无效"):
        app_module._normalize_mapping_preflight_result(metadata, payload)


def test_ready_private_records_ignore_corrupt_size_metadata():
    metadata = {
        "files": {
            "workbooks": [
                {
                    "id": "xlsx-1",
                    "objectKey": "labor-runs/uat/xlsx-1/bill.xlsx",
                    "uploadState": "ready",
                    "sizeBytes": "not-a-number",
                    "sha256": "a" * 64,
                }
            ]
        }
    }

    assert app_module._labor_ready_private_records(metadata, "workbooks") == []


def test_worker_api_returns_explicit_upgrade_required_for_invalid_or_old_version(monkeypatch, tmp_path):
    client = _configure(monkeypatch, tmp_path)
    jobs.enqueue_labor_worker_job(
        "labor_own",
        owner_user_id="user-1",
        required_worker_version=CURRENT_WORKER_VERSION,
    )

    invalid = client.post(
        "/api/labor/worker/jobs/claim",
        headers={"authorization": "Bearer token-user-1", "x-worker-version": "0.3"},
    )
    old = client.post(
        "/api/labor/worker/jobs/claim",
        headers={"authorization": "Bearer token-user-1", "x-worker-version": "0.2.9"},
    )

    assert invalid.status_code == 426
    assert invalid.json()["detail"]["errorCode"] == "LABOR_WORKER_UPGRADE_REQUIRED"
    assert old.status_code == 426
    assert old.json()["detail"]["requiredWorkerVersion"] == CURRENT_WORKER_VERSION


def test_browser_worker_release_exposes_latest_private_installer_without_object_key(monkeypatch, tmp_path):
    client = _configure(monkeypatch, tmp_path)
    digest = "a" * 64
    monkeypatch.setenv(
        "SIGMA_LABOR_WORKER_UPDATE_MANIFEST",
        json.dumps(
            {
                "version": CURRENT_WORKER_VERSION,
                "minimumVersion": CURRENT_WORKER_VERSION,
                "url": "https://uat.example.com/api/labor/worker/release/download",
                "sha256": digest,
                "signature": f"sha256:{digest}",
                "objectKey": "worker-releases/macos-arm64/worker.dmg",
                "filename": "worker.dmg",
            }
        ),
    )

    response = client.get("/api/labor/worker/release")

    assert response.status_code == 200
    assert response.json()["version"] == CURRENT_WORKER_VERSION
    assert response.json()["downloadUrl"] == "/api/labor/worker/release/download"
    assert "objectKey" not in response.json()


def test_persisted_worker_release_overrides_environment_and_becomes_required(monkeypatch, tmp_path):
    client = _configure(monkeypatch, tmp_path)
    monkeypatch.setenv("SIGMA_LABOR_STORAGE_ENV", "production")
    digest = "f" * 64
    monkeypatch.setenv(
        "SIGMA_LABOR_WORKER_UPDATE_MANIFEST",
        json.dumps(
            {
                "version": CURRENT_WORKER_VERSION,
                "minimumVersion": CURRENT_WORKER_VERSION,
                "url": "https://uat.example.com/old.dmg",
                "sha256": "a" * 64,
                "signature": f"sha256:{'a' * 64}",
            }
        ),
    )
    monkeypatch.setattr(
        app_module,
        "_load_persisted_labor_worker_release_manifest",
        lambda: {
            "schemaVersion": 3,
            "requiredWorkerVersion": "0.3.13",
            "releases": {
                "macos-arm64": {
                    "version": "0.3.13",
                    "minimumVersion": "0.3.13",
                    "sha256": digest,
                    "signature": f"sha256:{digest}",
                    "blobPathname": "labor-runs/production/owners/system/worker-releases/macos-arm64/worker.dmg",
                    "filename": "worker.dmg",
                }
            },
        },
    )

    response = client.get("/api/labor/worker/release")

    assert response.status_code == 200
    assert response.json()["version"] == "0.3.13"
    assert response.json()["requiredWorkerVersion"] == "0.3.13"
    assert response.json()["storageEnvironment"] == "production"


def test_admin_can_finalize_uploaded_worker_release_as_pending_manifest(monkeypatch, tmp_path):
    client = _configure(monkeypatch, tmp_path)
    monkeypatch.setattr(app_module, "_labor_request_actor", lambda request: ("admin-user", True))
    monkeypatch.setattr(app_module, "_load_persisted_labor_worker_release_manifest", lambda: {})
    monkeypatch.setattr(
        app_module,
        "_verify_labor_worker_release_artifact",
        lambda **kwargs: {
            "blobPathname": "labor-runs/production/owners/system/worker-releases/macos-arm64/worker.dmg",
            "sizeBytes": kwargs["size_bytes"],
        },
    )
    stored = {}
    monkeypatch.setattr(
        app_module,
        "_persist_labor_worker_release_manifest",
        lambda manifest: stored.update(manifest),
    )
    digest = "b" * 64

    response = client.post(
        "/api/labor/worker/release/finalize",
        json={
            "platform": "macos-arm64",
            "version": "0.3.13",
            "filename": "Σ海外报账核对助手-0.3.13-arm64.dmg",
            "sizeBytes": 126_000_000,
            "sha256": digest,
        },
    )

    assert response.status_code == 200
    assert response.json()["version"] == "0.3.13"
    assert response.json()["published"] is False
    assert response.json()["missingPlatforms"] == ["windows-x64"]
    assert response.json()["requiredWorkerVersion"] == CURRENT_WORKER_VERSION
    assert stored["requiredWorkerVersion"] == CURRENT_WORKER_VERSION
    assert stored["releases"] == {}
    assert stored["pendingReleases"]["macos-arm64"]["sha256"] == digest
    assert stored["pendingReleases"]["macos-arm64"]["signature"] == f"sha256:{digest}"


def test_admin_worker_release_waits_for_matching_platform_before_atomic_publish(monkeypatch, tmp_path):
    client = _configure(monkeypatch, tmp_path)
    monkeypatch.setattr(app_module, "labor_auth_required", lambda: True)
    monkeypatch.setattr(
        app_module,
        "current_user_from_request",
        lambda request: {"user": {"id": "admin-user"}, "roles": ["admin"]},
    )
    monkeypatch.setattr(app_module, "user_can_enter_module", lambda current, module: True)
    monkeypatch.setattr(app_module, "_labor_request_actor", lambda request: ("admin-user", True))
    monkeypatch.setattr(app_module, "get_session_user_id", lambda token: "admin-user")
    monkeypatch.setattr(app_module, "_user_can_enter_module", lambda user_id, module: True)
    active_version = CURRENT_WORKER_VERSION
    release_version = "0.3.14"
    stored = {
        "schemaVersion": 3,
        "requiredWorkerVersion": active_version,
        "releases": {
            platform: {
                "version": active_version,
                "minimumVersion": active_version,
                "sha256": digest,
                "signature": f"sha256:{digest}",
                "blobPathname": f"worker-releases/{platform}/old-package",
                "filename": app_module._labor_worker_release_filename(platform, active_version),
            }
            for platform, digest in (("macos-arm64", "a" * 64), ("windows-x64", "b" * 64))
        },
    }
    monkeypatch.setattr(
        app_module,
        "_load_persisted_labor_worker_release_manifest",
        lambda: json.loads(json.dumps(stored)),
    )

    def persist(manifest):
        stored.clear()
        stored.update(json.loads(json.dumps(manifest)))

    monkeypatch.setattr(app_module, "_persist_labor_worker_release_manifest", persist)
    monkeypatch.setattr(
        app_module,
        "_verify_labor_worker_release_artifact",
        lambda **kwargs: {
            "blobPathname": (
                f"worker-releases/{kwargs['platform']}/"
                f"{app_module._labor_worker_release_filename(kwargs['platform'], kwargs['version'])}"
            ),
            "sizeBytes": kwargs["size_bytes"],
        },
    )

    mac = client.post(
        "/api/labor/worker/release/finalize",
        json={
            "platform": "macos-arm64",
            "version": release_version,
            "filename": app_module._labor_worker_release_filename("macos-arm64", release_version),
            "sizeBytes": 126_000_000,
            "sha256": "c" * 64,
        },
    )

    assert mac.status_code == 200
    assert mac.json()["published"] is False
    assert mac.json()["missingPlatforms"] == ["windows-x64"]
    assert stored["requiredWorkerVersion"] == active_version
    assert stored["releases"]["macos-arm64"]["version"] == active_version
    assert stored["pendingReleases"]["macos-arm64"]["version"] == release_version

    client.cookies.set(app_module.SESSION_COOKIE_NAME, "test-session")
    pending_status = client.get("/api/labor/worker/release?platform=windows-x64")
    assert pending_status.status_code == 200, pending_status.text
    assert pending_status.json()["pendingVersions"] == {"macos-arm64": release_version}

    mismatched_windows = client.post(
        "/api/labor/worker/release/finalize",
        json={
            "platform": "windows-x64",
            "version": "0.3.15",
            "filename": app_module._labor_worker_release_filename("windows-x64", "0.3.15"),
            "sizeBytes": 150_000_000,
            "sha256": "e" * 64,
        },
    )
    assert mismatched_windows.status_code == 200
    assert mismatched_windows.json()["published"] is False
    assert stored["requiredWorkerVersion"] == active_version

    windows = client.post(
        "/api/labor/worker/release/finalize",
        json={
            "platform": "windows-x64",
            "version": release_version,
            "filename": app_module._labor_worker_release_filename("windows-x64", release_version),
            "sizeBytes": 150_000_000,
            "sha256": "d" * 64,
        },
    )

    assert windows.status_code == 200
    assert windows.json()["published"] is True
    assert windows.json()["missingPlatforms"] == []
    assert stored["requiredWorkerVersion"] == release_version
    assert stored["pendingReleases"] == {}
    assert {release["version"] for release in stored["releases"].values()} == {release_version}


def test_worker_version_exposes_direct_private_download_for_persisted_release(monkeypatch, tmp_path):
    client = _configure(monkeypatch, tmp_path)
    digest = "c" * 64
    monkeypatch.setattr(
        app_module,
        "_load_persisted_labor_worker_release_manifest",
        lambda: {
            "schemaVersion": 3,
            "requiredWorkerVersion": "0.3.13",
            "releases": {
                "macos-arm64": {
                    "version": "0.3.13",
                    "minimumVersion": "0.3.13",
                    "sha256": digest,
                    "signature": f"sha256:{digest}",
                    "objectKey": "labor-runs/production/owners/system/worker-releases/macos-arm64/worker.dmg",
                    "filename": "worker.dmg",
                }
            },
        },
    )

    response = client.get(
        "/api/labor/worker/version",
        headers={"authorization": "Bearer token-user-1"},
        params={"currentVersion": CURRENT_WORKER_VERSION, "platform": "macos-arm64"},
    )

    assert response.status_code == 200
    assert response.json()["updateAvailable"] is True
    assert response.json()["upgradeRequired"] is True
    assert response.json()["downloadUrl"] == "/api/labor/worker/release/download"


def test_browser_worker_release_selects_windows_x64_from_release_catalog(monkeypatch, tmp_path):
    client = _configure(monkeypatch, tmp_path)
    digest = "e" * 64
    monkeypatch.setenv(
        "SIGMA_LABOR_WORKER_UPDATE_MANIFEST",
        json.dumps(
            {
                "schemaVersion": 2,
                "releases": {
                    "macos-arm64": {
                        "version": CURRENT_WORKER_VERSION,
                        "sha256": "a" * 64,
                        "signature": f"sha256:{'a' * 64}",
                        "blobPathname": "labor-runs/uat/owners/system/worker-releases/macos-arm64/worker.dmg",
                        "filename": "worker.dmg",
                    },
                    "windows-x64": {
                        "version": CURRENT_WORKER_VERSION,
                        "sha256": digest,
                        "signature": f"sha256:{digest}",
                        "blobPathname": "labor-runs/uat/owners/system/worker-releases/windows-x64/worker.exe",
                        "filename": "worker.exe",
                    },
                },
            }
        ),
    )

    response = client.get("/api/labor/worker/release?platform=windows-x64")

    assert response.status_code == 200
    assert response.json()["available"] is True
    assert response.json()["platform"] == "windows-x64"
    assert response.json()["filename"] == "worker.exe"
    assert response.json()["downloadUrl"] == "/api/labor/worker/release/download?platform=windows-x64"


def test_browser_worker_release_reports_unpublished_windows_build(monkeypatch, tmp_path):
    client = _configure(monkeypatch, tmp_path)
    monkeypatch.setenv(
        "SIGMA_LABOR_WORKER_UPDATE_MANIFEST",
        json.dumps(
            {
                "schemaVersion": 2,
                "releases": {
                    "macos-arm64": {
                        "version": CURRENT_WORKER_VERSION,
                        "sha256": "a" * 64,
                        "signature": f"sha256:{'a' * 64}",
                        "blobPathname": "labor-runs/uat/owners/system/worker-releases/macos-arm64/worker.dmg",
                        "filename": "worker.dmg",
                    }
                },
            }
        ),
    )

    response = client.get("/api/labor/worker/release?platform=windows-x64")

    assert response.status_code == 200
    assert response.json()["available"] is False
    assert response.json()["platform"] == "windows-x64"
    assert response.json()["requiredWorkerVersion"] == CURRENT_WORKER_VERSION


def test_browser_worker_release_download_redirects_to_short_private_url(monkeypatch, tmp_path):
    client = _configure(monkeypatch, tmp_path)
    digest = "b" * 64
    monkeypatch.setenv(
        "SIGMA_LABOR_WORKER_UPDATE_MANIFEST",
        json.dumps(
            {
                "version": CURRENT_WORKER_VERSION,
                "minimumVersion": CURRENT_WORKER_VERSION,
                "url": "https://uat.example.com/api/labor/worker/release/download",
                "sha256": digest,
                "signature": f"sha256:{digest}",
                "objectKey": "worker-releases/macos-arm64/worker.dmg",
                "filename": "worker.dmg",
            }
        ),
    )
    monkeypatch.setattr(
        app_module,
        "create_labor_supabase_signed_download",
        lambda object_key, **kwargs: {
            "signedUrl": "https://project.supabase.co/storage/v1/object/sign/private?token=short",
            "expiresIn": 120,
        },
    )

    response = client.get("/api/labor/worker/release/download", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"].startswith("https://project.supabase.co/")


def test_browser_worker_release_download_redirects_to_short_private_blob_url(monkeypatch, tmp_path):
    client = _configure(monkeypatch, tmp_path)
    digest = "b" * 64
    pathname = "labor-runs/uat/owners/system/worker-releases/macos-arm64/worker.dmg"
    monkeypatch.setenv(
        "SIGMA_LABOR_WORKER_UPDATE_MANIFEST",
        json.dumps(
            {
                "version": CURRENT_WORKER_VERSION,
                "minimumVersion": CURRENT_WORKER_VERSION,
                "url": "https://uat.example.com/api/labor/worker/release/download",
                "sha256": digest,
                "signature": f"sha256:{digest}",
                "blobPathname": pathname,
                "filename": "worker.dmg",
            }
        ),
    )
    monkeypatch.setattr(
        app_module,
        "create_labor_blob_presigned_url",
        lambda blob_pathname, **kwargs: "https://store.private.blob.vercel-storage.com/worker.dmg?short=1",
    )

    response = client.get("/api/labor/worker/release/download", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"].startswith("https://store.private.blob.vercel-storage.com/")


def test_browser_worker_release_download_uses_requested_windows_blob(monkeypatch, tmp_path):
    client = _configure(monkeypatch, tmp_path)
    digest = "f" * 64
    pathname = "labor-runs/uat/owners/system/worker-releases/windows-x64/worker.exe"
    monkeypatch.setenv(
        "SIGMA_LABOR_WORKER_UPDATE_MANIFEST",
        json.dumps(
            {
                "schemaVersion": 2,
                "releases": {
                    "windows-x64": {
                        "version": CURRENT_WORKER_VERSION,
                        "sha256": digest,
                        "signature": f"sha256:{digest}",
                        "blobPathname": pathname,
                        "filename": "worker.exe",
                    }
                },
            }
        ),
    )
    observed = {}

    def sign(blob_pathname, **kwargs):
        observed["pathname"] = blob_pathname
        return "https://store.private.blob.vercel-storage.com/worker.exe?short=1"

    monkeypatch.setattr(app_module, "create_labor_blob_presigned_url", sign)

    response = client.get(
        "/api/labor/worker/release/download?platform=windows-x64",
        follow_redirects=False,
    )

    assert response.status_code == 307
    assert observed["pathname"] == pathname


def test_admin_can_issue_bounded_worker_release_upload_intent(monkeypatch, tmp_path):
    client = _configure(monkeypatch, tmp_path)
    monkeypatch.setattr(app_module, "_labor_request_actor", lambda request: ("admin-user", True))
    monkeypatch.setattr(app_module, "labor_blob_signed_urls_enabled", lambda: False)
    monkeypatch.setattr(
        app_module,
        "create_labor_supabase_signed_upload_for_object",
        lambda object_key, **kwargs: {
            "signedUrl": "https://project.supabase.co/storage/v1/object/upload/sign/private?token=short",
            "method": "PUT",
            "headers": {"content-type": kwargs["content_type"]},
            "objectKey": object_key,
            "expiresIn": 7200,
            "private": True,
        },
    )

    response = client.post(
        "/api/labor/worker/release/upload-intent",
        json={
            "version": CURRENT_WORKER_VERSION,
            "filename": f"Σ海外报账核对助手-{CURRENT_WORKER_VERSION}-arm64.dmg",
            "sizeBytes": 126_000_000,
            "sha256": "c" * 64,
        },
    )

    assert response.status_code == 200
    assert "/owners/system/worker-releases/macos-arm64/" in response.json()["objectKey"]
    assert response.json()["method"] == "PUT"


def test_admin_worker_release_upload_prefers_private_blob_signed_url(monkeypatch, tmp_path):
    client = _configure(monkeypatch, tmp_path)
    monkeypatch.setattr(app_module, "_labor_request_actor", lambda request: ("admin-user", True))
    monkeypatch.setattr(app_module, "labor_blob_signed_urls_enabled", lambda: True)
    monkeypatch.setattr(
        app_module,
        "create_labor_blob_presigned_url",
        lambda pathname, **kwargs: "https://vercel.com/api/blob/?pathname=worker.dmg&signed=1",
    )

    response = client.post(
        "/api/labor/worker/release/upload-intent",
        json={
            "version": CURRENT_WORKER_VERSION,
            "filename": f"Σ海外报账核对助手-{CURRENT_WORKER_VERSION}-arm64.dmg",
            "sizeBytes": 126_000_000,
            "sha256": "d" * 64,
        },
    )

    assert response.status_code == 200
    assert response.json()["signedUrl"].startswith("https://vercel.com/api/blob/")
    assert response.json()["blobPathname"].endswith(".dmg")
    assert "objectKey" not in response.json()


def test_admin_worker_release_upload_accepts_windows_x64_exe(monkeypatch, tmp_path):
    client = _configure(monkeypatch, tmp_path)
    monkeypatch.setattr(app_module, "_labor_request_actor", lambda request: ("admin-user", True))
    monkeypatch.setattr(app_module, "labor_blob_signed_urls_enabled", lambda: True)
    observed = {}

    def sign(pathname, **kwargs):
        observed.update({"pathname": pathname, **kwargs})
        return "https://vercel.com/api/blob/?pathname=worker.exe&signed=1"

    monkeypatch.setattr(app_module, "create_labor_blob_presigned_url", sign)
    release_version = "0.3.12"
    filename = f"Σ海外报账核对助手-{release_version}-windows-x64.exe"

    response = client.post(
        "/api/labor/worker/release/upload-intent",
        json={
            "platform": "windows-x64",
            "version": release_version,
            "filename": filename,
            "sizeBytes": 150_000_000,
            "sha256": "9" * 64,
        },
    )

    assert response.status_code == 200
    assert response.json()["platform"] == "windows-x64"
    assert response.json()["blobPathname"].endswith(f"/windows-x64/{filename}")
    assert "application/x-msdownload" in observed["allowed_content_types"]


def test_worker_version_selects_platform_specific_update(monkeypatch, tmp_path):
    client = _configure(monkeypatch, tmp_path)
    digest = "7" * 64
    monkeypatch.setenv(
        "SIGMA_LABOR_WORKER_UPDATE_MANIFEST",
        json.dumps(
            {
                "schemaVersion": 2,
                "releases": {
                    "windows-x64": {
                        "version": "0.4.0",
                        "minimumVersion": CURRENT_WORKER_VERSION,
                        "url": "https://uat.example.com/api/labor/worker/release/download?platform=windows-x64",
                        "sha256": digest,
                        "signature": f"sha256:{digest}",
                    }
                },
            }
        ),
    )

    response = client.get(
        "/api/labor/worker/version",
        headers={"authorization": "Bearer token-user-1"},
        params={"currentVersion": CURRENT_WORKER_VERSION, "platform": "windows-x64"},
    )

    assert response.status_code == 200
    assert response.json()["platform"] == "windows-x64"
    assert response.json()["version"] == "0.4.0"
    assert response.json()["updateAvailable"] is True


def test_stale_runtime_refuses_new_worker_claim(monkeypatch, tmp_path):
    client = _configure(monkeypatch, tmp_path)
    monkeypatch.setattr(
        app_module,
        "_labor_build_snapshot",
        lambda: {"status": "restart_required", "buildId": "stale"},
    )

    response = client.post(
        "/api/labor/worker/jobs/claim",
        headers={"authorization": "Bearer token-user-1", "x-worker-version": CURRENT_WORKER_VERSION},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["errorCode"] == "LABOR_SERVICE_RESTART_REQUIRED"


def test_worker_api_rejects_other_device_heartbeat(monkeypatch, tmp_path):
    client = _configure(monkeypatch, tmp_path)
    job = jobs.enqueue_labor_worker_job("labor_own", owner_user_id="user-1")
    client.post(
        "/api/labor/worker/jobs/claim",
        headers={"authorization": "Bearer token-user-1", "x-worker-version": CURRENT_WORKER_VERSION},
    )

    response = client.post(
        f"/api/labor/worker/jobs/{job['id']}/heartbeat",
        headers={"authorization": "Bearer token-user-2"},
        json={"progress": {"phase": "ocr"}},
    )

    assert response.status_code == 409


def test_worker_heartbeat_refreshes_run_progress_for_browser_polling(monkeypatch, tmp_path):
    client = _configure(monkeypatch, tmp_path)
    run_dir = _generation_run(tmp_path, "generation-current")
    monkeypatch.setattr(app_module, "get_labor_run_dir", lambda _run_id: run_dir)
    monkeypatch.setattr(labor_runs, "get_labor_run_dir", lambda _run_id: run_dir)
    monkeypatch.setattr(app_module, "sync_labor_run_to_persistent", lambda *_: None)
    metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    metadata["progress"] = {
        "stage": "OCR识别",
        "message": "正在识别发票。",
        "lastUpdatedAt": "2026-07-20T15:00:00",
    }
    (run_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    job = jobs.enqueue_labor_worker_job(
        "labor_own",
        owner_user_id="user-1",
        task_generation_id="generation-current",
    )
    client.post(
        "/api/labor/worker/jobs/claim",
        headers={"authorization": "Bearer token-user-1", "x-worker-version": CURRENT_WORKER_VERSION},
    )

    response = client.post(
        f"/api/labor/worker/jobs/{job['id']}/heartbeat",
        headers={"authorization": "Bearer token-user-1"},
        json={"progress": {"phase": "ocr"}},
    )

    assert response.status_code == 200
    saved = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    assert saved["progress"]["stage"] == "OCR识别"
    assert saved["progress"]["message"] == "正在识别发票。"
    assert saved["progress"]["lastUpdatedAt"] != "2026-07-20T15:00:00"


def test_completed_worker_heartbeat_is_idempotent_for_same_device(monkeypatch, tmp_path):
    client = _configure(monkeypatch, tmp_path)
    completed = {
        "id": "job-completed",
        "runId": "labor-completed",
        "status": "succeeded",
        "ownerUserId": "user-1",
        "claimedDeviceId": "device-a",
    }
    monkeypatch.setattr(app_module, "get_labor_worker_job", lambda _job_id: completed)

    response = client.post(
        "/api/labor/worker/jobs/job-completed/heartbeat",
        headers={"authorization": "Bearer token-user-1", "x-worker-version": CURRENT_WORKER_VERSION},
        json={"progress": {"phase": "completed"}},
    )

    assert response.status_code == 200
    assert response.json()["job"]["status"] == "succeeded"


def test_operations_endpoint_requires_admin_token(monkeypatch, tmp_path):
    client = _configure(monkeypatch, tmp_path)
    monkeypatch.setenv("SIGMA_LABOR_OPERATIONS_TOKEN", "admin-secret")

    assert client.get("/api/labor/operations").status_code == 401
    response = client.get("/api/labor/operations", headers={"x-admin-token": "admin-secret"})

    assert response.status_code == 200
    assert {"alerts", "metrics", "recentJobs", "storage"}.issubset(response.json())


def test_operations_endpoint_does_not_treat_server_cache_as_supabase_capacity(monkeypatch, tmp_path):
    client = _configure(monkeypatch, tmp_path)
    monkeypatch.setenv("SIGMA_LABOR_OPERATIONS_TOKEN", "admin-secret")
    monkeypatch.setenv("SIGMA_LABOR_STORAGE_BACKEND", "supabase")
    monkeypatch.setattr(
        app_module.shutil,
        "disk_usage",
        lambda _path: type("DiskUsage", (), {"free": 100, "total": 1000})(),
    )
    monkeypatch.setattr(app_module, "list_labor_worker_jobs", lambda: [])

    response = client.get("/api/labor/operations", headers={"x-admin-token": "admin-secret"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["storage"]["backend"] == "supabase"
    assert payload["storage"]["minimumFreeBytes"] == 0
    assert payload["storage"]["capacityScope"] == "server_cache_only"
    assert not any(alert["code"] == "STORAGE_CAPACITY_LOW" for alert in payload["alerts"])


def test_personal_worker_status_is_visible_in_run_polling(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    monkeypatch.setenv("SIGMA_LABOR_EXECUTION_MODE", "personal-worker")
    jobs.enqueue_labor_worker_job("labor_own", owner_user_id="user-1")

    queued = app_module._with_personal_worker_status({"id": "labor_own", "status": "抽取中"})

    assert queued["asyncTask"]["status"] == "waiting_for_personal_worker"
    assert queued["workerTask"]["runId"] == "labor_own"


def test_personal_worker_status_uses_latest_attempt(monkeypatch):
    monkeypatch.setenv("SIGMA_LABOR_EXECUTION_MODE", "personal-worker")
    monkeypatch.setattr(
        app_module,
        "list_labor_worker_jobs",
        lambda: [
            {"id": "old", "runId": "labor_own", "status": "failed", "updatedAt": "2026-07-13T01:00:00Z"},
            {"id": "new", "runId": "labor_own", "status": "succeeded", "updatedAt": "2026-07-13T02:00:00Z"},
        ],
    )

    result = app_module._with_personal_worker_status({"id": "labor_own", "status": "PDF识别未完成"})

    assert result == {"id": "labor_own", "status": "PDF识别未完成"}


def test_personal_worker_status_ignores_jobs_from_superseded_generation(monkeypatch):
    monkeypatch.setenv("SIGMA_LABOR_EXECUTION_MODE", "personal-worker")
    monkeypatch.setattr(
        app_module,
        "list_labor_worker_jobs",
        lambda: [
            {
                "id": "old",
                "runId": "labor_own",
                "status": "running",
                "taskGenerationId": "generation-old",
                "updatedAt": "2026-07-13T03:00:00Z",
            },
            {
                "id": "current",
                "runId": "labor_own",
                "status": "queued",
                "taskGenerationId": "generation-current",
                "updatedAt": "2026-07-13T02:00:00Z",
            },
        ],
    )

    result = app_module._with_personal_worker_status(
        {
            "id": "labor_own",
            "status": "抽取中",
            "taskGenerationId": "generation-current",
            "asyncTask": {"status": "queued", "taskGenerationId": "generation-current"},
        }
    )

    assert result["workerTask"]["id"] == "current"
    assert result["asyncTask"]["status"] == "waiting_for_personal_worker"


def test_worker_input_and_result_require_current_lease(monkeypatch, tmp_path):
    client = _configure(monkeypatch, tmp_path)
    run_dir = _generation_run(tmp_path, "")
    monkeypatch.setattr(app_module, "get_labor_run_dir", lambda run_id: tmp_path / "runs" / run_id)
    monkeypatch.setattr(labor_runs, "get_labor_run_dir", lambda run_id: tmp_path / "runs" / run_id)
    monkeypatch.setattr(app_module, "sync_labor_run_to_persistent", lambda *_: None)
    job = jobs.enqueue_labor_worker_job("labor_own", owner_user_id="user-1")
    client.post(
        "/api/labor/worker/jobs/claim",
        headers={"authorization": "Bearer token-user-1", "x-worker-version": CURRENT_WORKER_VERSION},
    )

    denied = client.get(
        f"/api/labor/worker/jobs/{job['id']}/input",
        headers={"authorization": "Bearer token-user-2"},
    )
    allowed = client.get(
        f"/api/labor/worker/jobs/{job['id']}/input",
        headers={"authorization": "Bearer token-user-1"},
    )
    manifest = client.get(
        f"/api/labor/worker/jobs/{job['id']}/input-manifest",
        headers={"authorization": "Bearer token-user-1"},
    )
    streamed = client.get(
        f"/api/labor/worker/jobs/{job['id']}/input-file",
        headers={"authorization": "Bearer token-user-1"},
        params={"relativePath": "invoice.pdf"},
    )
    traversal = client.get(
        f"/api/labor/worker/jobs/{job['id']}/input-file",
        headers={"authorization": "Bearer token-user-1"},
        params={"relativePath": "../secret"},
    )
    current = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    incoming = _complete_result_metadata(current)
    result = client.post(
        f"/api/labor/worker/jobs/{job['id']}/result",
        headers={"authorization": "Bearer token-user-1", "x-worker-version": CURRENT_WORKER_VERSION},
        files={
            "result_archive": (
                "result.zip",
                _zip_bytes({"metadata.json": json.dumps(incoming).encode(), "result.xlsx": b"report"}),
                "application/zip",
            )
        },
    )

    assert denied.status_code == 409
    assert allowed.status_code == 200
    assert allowed.headers["content-type"] == "application/zip"
    assert manifest.json()["files"][0]["path"] == "invoice.pdf"
    assert streamed.content == b"pdf"
    assert traversal.status_code == 400
    assert result.status_code == 200
    assert (run_dir / "result.xlsx").read_bytes() == b"report"


def test_p1_worker_result_is_published_to_authoritative_state_before_acceptance(monkeypatch, tmp_path):
    run_dir = tmp_path / "runs" / "labor-p1-result"
    run_dir.mkdir(parents=True)
    fingerprint = "d" * 64
    merged = {
        "id": "labor-p1-result",
        "ownerUserId": "user-1",
        "status": "核对完成",
        "taskGenerationId": "generation-current",
        "resultInputFingerprint": fingerprint,
        "files": {
            "pdfInvoices": [],
            "workbooks": [],
            "diffReport": {"filename": "result.xlsx", "sizeBytes": 6, "sha256": "e" * 64},
        },
        "comparisonSummary": {"canRelease": False},
    }
    (run_dir / "metadata.json").write_text(json.dumps(merged), encoding="utf-8")
    captured = {}
    monkeypatch.setattr(app_module, "labor_postgres_state_enabled", lambda: True)

    def publish(run_id, **kwargs):
        captured["runId"] = run_id
        captured.update(kwargs)
        return dict(merged), True

    monkeypatch.setattr(app_module, "compare_and_update_labor_metadata", publish)

    published = app_module._publish_worker_result_to_authoritative_state(
        "labor-p1-result",
        run_dir,
        generation="generation-current",
    )

    assert published["resultInputFingerprint"] == fingerprint
    assert captured["runId"] == "labor-p1-result"
    assert captured["expected_task_generation_id"] == "generation-current"
    assert captured["expected_fingerprint"] == fingerprint
    assert captured["updates"] == merged


def test_p1_report_download_redirects_to_short_private_signed_url(monkeypatch, tmp_path):
    object_key = "labor-runs/uat/owners/user-1/runs/labor-1/outputs/diff/result.xlsx"
    metadata = {
        "id": "labor-1",
        "ownerUserId": "user-1",
        "files": {
            "diffReport": {
                "filename": "result.xlsx",
                "objectKey": object_key,
                "storageVerified": True,
                "sizeBytes": 100,
                "sha256": "a" * 64,
            }
        },
    }
    monkeypatch.setattr(app_module, "labor_postgres_state_enabled", lambda: True)
    monkeypatch.setattr(app_module, "_labor_metadata_or_404", lambda _run_id: metadata)
    monkeypatch.setattr(
        app_module,
        "create_labor_supabase_signed_download",
        lambda key, **kwargs: {
            "signedUrl": "https://project.supabase.co/storage/v1/object/sign/private?token=short",
            "objectKey": key,
            "expiresIn": kwargs["expires_in"],
        },
    )

    response = app_module.download_labor_file("labor-1", "result.xlsx")

    assert response.status_code == 307
    assert response.headers["location"].endswith("token=short")
    assert response.headers["cache-control"] == "no-store"


def test_p1_report_download_never_falls_back_to_a_local_file(monkeypatch, tmp_path):
    run_dir = tmp_path / "labor-runs" / "labor-1"
    run_dir.mkdir(parents=True)
    (run_dir / "result.xlsx").write_bytes(b"local-only-report")
    metadata = {
        "id": "labor-1",
        "ownerUserId": "user-1",
        "files": {
            "diffReport": {
                "filename": "result.xlsx",
                "downloadUrl": "/api/labor/runs/labor-1/download/result.xlsx",
            }
        },
    }
    monkeypatch.setenv("SIGMA_LABOR_P1_REQUIRED", "1")
    monkeypatch.setattr(app_module, "labor_postgres_state_enabled", lambda: True)
    monkeypatch.setattr(app_module, "_labor_metadata_or_404", lambda _run_id: metadata)
    monkeypatch.setattr(app_module, "get_labor_run_dir", lambda _run_id: run_dir)

    with pytest.raises(app_module.HTTPException) as exc_info:
        app_module.download_labor_file("labor-1", "result.xlsx")

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["errorCode"] == "LABOR_P1_PRIVATE_REPORT_REQUIRED"


def test_p1_verified_private_report_satisfies_report_file_evidence(monkeypatch):
    report = {
        "filename": "result.xlsx",
        "objectKey": "labor-runs/uat/owners/user-1/runs/labor-1/outputs/diff/result.xlsx",
        "storageVerified": True,
        "storageVerifiedSizeBytes": 100,
        "sizeBytes": 100,
        "sha256": "a" * 64,
    }
    monkeypatch.setattr(app_module, "labor_postgres_state_enabled", lambda: True)

    assert app_module._labor_diff_report_file_exists({"id": "labor-1"}, report) is True


def test_p1_worker_input_manifest_uses_ready_database_files_and_short_signed_downloads(monkeypatch, tmp_path):
    run_dir = _generation_run(tmp_path, "generation-p1")
    object_key = "labor-runs/uat/owners/user-1/runs/labor_own/inputs/file-1/invoice.pdf"
    monkeypatch.setattr(app_module, "labor_postgres_state_enabled", lambda: True)
    monkeypatch.setattr(
        app_module,
        "list_labor_file_states",
        lambda **kwargs: [
            {
                "id": "file-1",
                "runId": kwargs["run_id"],
                "ownerUserId": kwargs["owner_user_id"],
                "fileKind": "pdf_invoice",
                "objectKey": object_key,
                "originalFilename": "invoice.pdf",
                "contentType": "application/pdf",
                "sizeBytes": 3,
                "sha256": hashlib.sha256(b"pdf").hexdigest(),
                "uploadState": "ready",
            }
        ],
        raising=False,
    )
    monkeypatch.setattr(
        app_module,
        "create_labor_supabase_signed_download",
        lambda key, **_kwargs: {
            "signedUrl": f"https://project.supabase.co/storage/v1/object/sign/private?key={key[-8:]}",
            "expiresIn": 600,
            "private": True,
        },
    )

    manifest = app_module._worker_input_manifest(run_dir, owner_user_id="user-1")

    assert manifest["downloadMode"] == "signed_private"
    assert manifest["files"][0]["fileId"] == "file-1"
    assert manifest["files"][0]["path"] == "inputs/file-1/invoice.pdf"
    assert manifest["files"][0]["signedUrl"].startswith("https://project.supabase.co/")
    assert manifest["metadata"]["files"]["pdfInvoices"][0]["path"] == "inputs/file-1/invoice.pdf"


def test_mapping_preflight_manifest_downloads_workbooks_without_pdf_invoices(monkeypatch, tmp_path):
    run_dir = _generation_run(tmp_path, "generation-preflight")
    pdf_bytes = b"pdf"
    workbook_bytes = b"xlsx"
    monkeypatch.setattr(app_module, "labor_postgres_state_enabled", lambda: True)
    monkeypatch.setattr(
        app_module,
        "list_labor_file_states",
        lambda **kwargs: [
            {
                "id": "file-pdf",
                "runId": kwargs["run_id"],
                "ownerUserId": kwargs["owner_user_id"],
                "fileKind": "pdf_invoice",
                "objectKey": "labor-runs/uat/invoice.pdf",
                "originalFilename": "invoice.pdf",
                "contentType": "application/pdf",
                "sizeBytes": len(pdf_bytes),
                "sha256": hashlib.sha256(pdf_bytes).hexdigest(),
                "uploadState": "ready",
            },
            {
                "id": "file-xlsx",
                "runId": kwargs["run_id"],
                "ownerUserId": kwargs["owner_user_id"],
                "fileKind": "workbook",
                "objectKey": "labor-runs/uat/bill.xlsx",
                "originalFilename": "bill.xlsx",
                "contentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "sizeBytes": len(workbook_bytes),
                "sha256": hashlib.sha256(workbook_bytes).hexdigest(),
                "uploadState": "ready",
            },
        ],
        raising=False,
    )
    monkeypatch.setattr(
        app_module,
        "create_labor_supabase_signed_download",
        lambda key, **_kwargs: {
            "signedUrl": f"https://project.supabase.co/storage/v1/object/sign/private?key={str(key).rsplit('/', 1)[-1]}",
            "expiresIn": 600,
            "private": True,
        },
    )

    manifest = app_module._worker_input_manifest(
        run_dir,
        owner_user_id="user-1",
        job_type="mapping_preflight",
    )

    assert [entry["fileKind"] for entry in manifest["files"]] == ["workbook"]
    assert [entry["path"] for entry in manifest["files"]] == ["inputs/file-xlsx/bill.xlsx"]
    assert manifest["metadata"]["files"]["pdfInvoices"] == []
    assert manifest["metadata"]["files"]["workbooks"][0]["filename"] == "bill.xlsx"


def test_running_worker_cannot_submit_or_complete_after_minimum_version_increases(monkeypatch, tmp_path):
    client = _configure(monkeypatch, tmp_path)
    job = jobs.enqueue_labor_worker_job(
        "labor_own",
        owner_user_id="user-1",
        required_worker_version=CURRENT_WORKER_VERSION,
    )
    claimed = client.post(
        "/api/labor/worker/jobs/claim",
        headers={"authorization": "Bearer token-user-1", "x-worker-version": CURRENT_WORKER_VERSION},
    )
    assert claimed.status_code == 200
    monkeypatch.setenv("SIGMA_LABOR_REQUIRED_WORKER_VERSION", "0.4.0")

    result = client.post(
        f"/api/labor/worker/jobs/{job['id']}/result",
        headers={"authorization": "Bearer token-user-1", "x-worker-version": CURRENT_WORKER_VERSION},
        files={"result_archive": ("result.zip", b"not-used", "application/zip")},
    )
    complete = client.post(
        f"/api/labor/worker/jobs/{job['id']}/complete",
        headers={"authorization": "Bearer token-user-1", "x-worker-version": CURRENT_WORKER_VERSION},
    )

    assert result.status_code == 426
    assert result.json()["detail"]["requiredWorkerVersion"] == "0.4.0"
    assert complete.status_code == 426
    assert complete.json()["detail"]["requiredWorkerVersion"] == "0.4.0"


def test_worker_runtime_events_are_lease_bound_and_sanitized(monkeypatch, tmp_path):
    client = _configure(monkeypatch, tmp_path)
    telemetry = tmp_path / "telemetry" / "events.jsonl"
    monkeypatch.setattr(app_module, "LABOR_TELEMETRY_DIR", telemetry.parent)
    monkeypatch.setattr(app_module, "LABOR_TELEMETRY_FILE", telemetry)
    job = jobs.enqueue_labor_worker_job("labor_own", owner_user_id="user-1")
    client.post(
        "/api/labor/worker/jobs/claim",
        headers={"authorization": "Bearer token-user-1", "x-worker-version": CURRENT_WORKER_VERSION},
    )

    denied = client.post(
        f"/api/labor/worker/jobs/{job['id']}/events",
        headers={"authorization": "Bearer token-user-2"},
        json={"events": [{"event": "model_call", "status": "failed"}]},
    )
    allowed = client.post(
        f"/api/labor/worker/jobs/{job['id']}/events",
        headers={"authorization": "Bearer token-user-1"},
        json={"events": [
            {"event": "ocr_cache", "status": "hit", "summary": {"cacheHit": True}, "secret": "no"},
            {"event": "unapproved", "status": "failed"},
        ]},
    )

    assert denied.status_code == 409
    assert allowed.json()["accepted"] == 1
    saved = json.loads(telemetry.read_text())
    assert saved["source"] == "personal-desktop-worker"
    assert saved["runId"] == "labor_own"
    assert saved["summary"]["cacheHit"] is True
    assert "secret" not in saved


@pytest.mark.parametrize("job_generation", ["", "generation-old"], ids=["legacy-empty", "stale-nonempty"])
def test_stale_generation_worker_is_rejected_by_every_mutating_or_input_endpoint(
    monkeypatch,
    tmp_path,
    job_generation,
):
    client = _configure(monkeypatch, tmp_path)
    run_dir = _generation_run(tmp_path, "generation-new")
    monkeypatch.setattr(app_module, "get_labor_run_dir", lambda _run_id: run_dir)
    monkeypatch.setattr(labor_runs, "get_labor_run_dir", lambda _run_id: run_dir)
    monkeypatch.setattr(app_module, "sync_labor_run_to_persistent", lambda *_: None)
    job = jobs.enqueue_labor_worker_job(
        "labor_own",
        owner_user_id="user-1",
        task_generation_id=job_generation,
    )
    jobs.claim_labor_worker_job(owner_user_id="user-1", device_id="device-a", worker_version=CURRENT_WORKER_VERSION)
    headers = {"authorization": "Bearer token-user-1", "x-worker-version": CURRENT_WORKER_VERSION}

    responses = [
        client.post(f"/api/labor/worker/jobs/{job['id']}/heartbeat", headers=headers, json={"progress": {}}),
        client.get(f"/api/labor/worker/jobs/{job['id']}/input", headers=headers),
        client.get(f"/api/labor/worker/jobs/{job['id']}/input-manifest", headers=headers),
        client.get(
            f"/api/labor/worker/jobs/{job['id']}/input-file",
            headers=headers,
            params={"relativePath": "invoice.pdf"},
        ),
        client.post(f"/api/labor/worker/jobs/{job['id']}/events", headers=headers, json={"events": []}),
        client.post(
            f"/api/labor/worker/jobs/{job['id']}/result",
            headers=headers,
            files={"result_archive": ("result.zip", _result_zip(), "application/zip")},
        ),
        client.post(f"/api/labor/worker/jobs/{job['id']}/complete", headers=headers),
        client.post(f"/api/labor/worker/jobs/{job['id']}/fail", headers=headers, json={"retryable": False}),
    ]

    assert [response.status_code for response in responses] == [409] * len(responses)
    saved = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    assert saved["taskGenerationId"] == "generation-new"
    assert saved["asyncTask"]["status"] == "running"


@pytest.mark.parametrize("result_kind", ["missing", "incomplete", "stale"])
def test_unaccepted_worker_result_is_non_2xx_marks_same_generation_failed_and_cannot_complete(
    monkeypatch,
    tmp_path,
    result_kind,
):
    client = _configure(monkeypatch, tmp_path)
    run_dir = _generation_run(tmp_path, "generation-current")
    monkeypatch.setattr(app_module, "get_labor_run_dir", lambda _run_id: run_dir)
    monkeypatch.setattr(labor_runs, "get_labor_run_dir", lambda _run_id: run_dir)
    monkeypatch.setattr(app_module, "sync_labor_run_to_persistent", lambda *_: None)
    job = jobs.enqueue_labor_worker_job(
        "labor_own",
        owner_user_id="user-1",
        task_generation_id="generation-current",
    )
    jobs.claim_labor_worker_job(owner_user_id="user-1", device_id="device-a", worker_version=CURRENT_WORKER_VERSION)
    headers = {"authorization": "Bearer token-user-1", "x-worker-version": CURRENT_WORKER_VERSION}
    current = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    if result_kind == "missing":
        archive = _zip_bytes({"result.xlsx": b"report"})
    elif result_kind == "incomplete":
        archive = _zip_bytes({"metadata.json": b"{}", "result.xlsx": b"report"})
    else:
        incoming = _complete_result_metadata(current)
        incoming["resultInputFingerprint"] = "0" * 64
        archive = _zip_bytes({"metadata.json": json.dumps(incoming).encode(), "result.xlsx": b"report"})

    rejected = client.post(
        f"/api/labor/worker/jobs/{job['id']}/result",
        headers=headers,
        files={"result_archive": ("result.zip", archive, "application/zip")},
    )
    completed = client.post(f"/api/labor/worker/jobs/{job['id']}/complete", headers=headers)

    assert rejected.status_code == 409
    assert rejected.json()["detail"]["errorCode"].startswith("LABOR_WORKER_RESULT_")
    assert completed.status_code == 409
    assert not jobs.get_labor_worker_job(job["id"]).get("resultAcceptedAt")
    saved = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    assert saved["taskGenerationId"] == "generation-current"
    assert saved["status"] == "抽取失败"
    assert saved["asyncTask"]["status"] == "failed"
    assert saved["retryable"] is True

    # A rejected replacement cannot leave the previous formal evidence visible.
    assert saved["diffDownloadUrl"] == ""
    assert "diffReport" not in saved["files"]
    assert saved["comparisonSummary"] == {}
    assert saved["comparisonRows"] == []
    assert saved["resultInputFingerprint"] == ""


def test_complete_requires_full_integrity_checked_result_for_same_generation(monkeypatch, tmp_path):
    client = _configure(monkeypatch, tmp_path)
    run_dir = _generation_run(tmp_path, "generation-current")
    monkeypatch.setattr(app_module, "get_labor_run_dir", lambda _run_id: run_dir)
    monkeypatch.setattr(labor_runs, "get_labor_run_dir", lambda _run_id: run_dir)
    monkeypatch.setattr(app_module, "sync_labor_run_to_persistent", lambda *_: None)
    job = jobs.enqueue_labor_worker_job(
        "labor_own",
        owner_user_id="user-1",
        task_generation_id="generation-current",
    )
    jobs.claim_labor_worker_job(owner_user_id="user-1", device_id="device-a", worker_version=CURRENT_WORKER_VERSION)
    headers = {"authorization": "Bearer token-user-1", "x-worker-version": CURRENT_WORKER_VERSION}
    current = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    incoming = _complete_result_metadata(current)

    accepted = client.post(
        f"/api/labor/worker/jobs/{job['id']}/result",
        headers=headers,
        files={
            "result_archive": (
                "result.zip",
                _zip_bytes({"metadata.json": json.dumps(incoming).encode(), "result.xlsx": b"report"}),
                "application/zip",
            )
        },
    )
    completed = client.post(f"/api/labor/worker/jobs/{job['id']}/complete", headers=headers)

    assert accepted.status_code == 200
    assert completed.status_code == 200
    stored_job = jobs.get_labor_worker_job(job["id"])
    assert stored_job["resultAcceptedGenerationId"] == "generation-current"
    assert stored_job["status"] == "succeeded"


def test_completion_accepts_verified_private_report_after_serverless_instance_switch(monkeypatch, tmp_path):
    client = _configure(monkeypatch, tmp_path)
    run_dir = _generation_run(tmp_path, "generation-current")
    monkeypatch.setattr(app_module, "get_labor_run_dir", lambda _run_id: run_dir)
    monkeypatch.setattr(labor_runs, "get_labor_run_dir", lambda _run_id: run_dir)
    current = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    incoming = _complete_result_metadata(current)
    diff_report = incoming["files"]["diffReport"]
    diff_report.update(
        {
            "objectKey": "labor-runs/uat/owners/user-1/runs/labor_own/outputs/diff_report/result.xlsx",
            "storageBackend": "supabase",
            "storagePrivate": True,
            "storageVerified": True,
            "storageVerifiedAt": "2026-07-23T10:29:50Z",
            "storageVerifiedSizeBytes": diff_report["sizeBytes"],
        }
    )
    merged = {
        **current,
        **incoming,
        "files": {
            **current["files"],
            **incoming["files"],
        },
    }
    (run_dir / "metadata.json").write_text(json.dumps(merged), encoding="utf-8")

    assert not (run_dir / "result.xlsx").exists()
    assert app_module._worker_result_acceptance_evidence(run_dir) == (
        diff_report["sha256"],
        diff_report["sizeBytes"],
        incoming["resultInputFingerprint"],
    )
    job = jobs.enqueue_labor_worker_job(
        "labor_own",
        owner_user_id="user-1",
        task_generation_id="generation-current",
    )
    jobs.claim_labor_worker_job(
        owner_user_id="user-1",
        device_id="device-a",
        worker_version=CURRENT_WORKER_VERSION,
    )
    jobs.mark_labor_worker_result_accepted(
        job["id"],
        owner_user_id="user-1",
        device_id="device-a",
        expected_task_generation_id="generation-current",
        result_report_sha256=diff_report["sha256"],
        result_report_size_bytes=diff_report["sizeBytes"],
        result_input_fingerprint=incoming["resultInputFingerprint"],
    )

    completed = client.post(
        f"/api/labor/worker/jobs/{job['id']}/complete",
        headers={"authorization": "Bearer token-user-1", "x-worker-version": CURRENT_WORKER_VERSION},
    )

    assert completed.status_code == 200
    assert completed.json()["job"]["status"] == "succeeded"


def test_completion_rejects_missing_local_report_without_verified_private_storage(tmp_path):
    run_dir = _generation_run(tmp_path, "generation-current")
    current = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    incoming = _complete_result_metadata(current)
    merged = {
        **current,
        **incoming,
        "files": {
            **current["files"],
            **incoming["files"],
        },
    }
    (run_dir / "metadata.json").write_text(json.dumps(merged), encoding="utf-8")

    assert app_module._worker_result_acceptance_evidence(run_dir) == ("", 0, "")


@pytest.mark.parametrize("bad_result_kind", ["missing", "empty-report"])
def test_new_bad_result_upload_revokes_prior_acceptance_and_cannot_complete(
    monkeypatch,
    tmp_path,
    bad_result_kind,
):
    client = _configure(monkeypatch, tmp_path)
    run_dir = _generation_run(tmp_path, "generation-current")
    monkeypatch.setattr(app_module, "get_labor_run_dir", lambda _run_id: run_dir)
    monkeypatch.setattr(labor_runs, "get_labor_run_dir", lambda _run_id: run_dir)
    monkeypatch.setattr(app_module, "sync_labor_run_to_persistent", lambda *_: None)
    job = jobs.enqueue_labor_worker_job(
        "labor_own",
        owner_user_id="user-1",
        task_generation_id="generation-current",
    )
    jobs.claim_labor_worker_job(owner_user_id="user-1", device_id="device-a", worker_version=CURRENT_WORKER_VERSION)
    headers = {"authorization": "Bearer token-user-1", "x-worker-version": CURRENT_WORKER_VERSION}
    current = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    good_metadata = _complete_result_metadata(current)
    good = client.post(
        f"/api/labor/worker/jobs/{job['id']}/result",
        headers=headers,
        files={
            "result_archive": (
                "good.zip",
                _zip_bytes({"metadata.json": json.dumps(good_metadata).encode(), "result.xlsx": b"report"}),
                "application/zip",
            )
        },
    )
    accepted_job = jobs.get_labor_worker_job(job["id"])
    assert good.status_code == 200
    assert accepted_job["resultAcceptedReportSha256"] == hashlib.sha256(b"report").hexdigest()
    assert accepted_job["resultAcceptedReportSizeBytes"] == len(b"report")
    assert accepted_job["resultAcceptedInputFingerprint"] == good_metadata["resultInputFingerprint"]

    if bad_result_kind == "missing":
        bad_archive = _zip_bytes({"result.xlsx": b"report"})
    else:
        current_after_good = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        empty_metadata = _complete_result_metadata(current_after_good, report=b"")
        bad_archive = _zip_bytes(
            {"metadata.json": json.dumps(empty_metadata).encode(), "result.xlsx": b""}
        )
    bad = client.post(
        f"/api/labor/worker/jobs/{job['id']}/result",
        headers=headers,
        files={"result_archive": ("bad.zip", bad_archive, "application/zip")},
    )
    completed = client.post(f"/api/labor/worker/jobs/{job['id']}/complete", headers=headers)

    assert bad.status_code == 409
    revoked_job = jobs.get_labor_worker_job(job["id"])
    assert revoked_job["resultAcceptedAt"] == ""
    assert revoked_job["resultAcceptedGenerationId"] == ""
    assert revoked_job["resultAcceptedReportSha256"] == ""
    assert revoked_job["resultAcceptedReportSizeBytes"] == 0
    assert revoked_job["resultAcceptedInputFingerprint"] == ""
    assert completed.status_code == 409
    saved = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    assert saved["taskGenerationId"] == "generation-current"
    assert saved["status"] == "抽取失败"
    assert saved["asyncTask"]["status"] == "failed"
    assert saved["retryable"] is True
    assert saved["diffDownloadUrl"] == ""
    assert "diffReport" not in saved["files"]
    assert saved["comparisonSummary"] == {}
    assert saved["comparisonRows"] == []
    assert saved["resultInputFingerprint"] == ""


def test_mapping_change_after_accepted_result_blocks_completion_by_evidence_binding(monkeypatch, tmp_path):
    client = _configure(monkeypatch, tmp_path)
    run_dir = _generation_run(tmp_path, "generation-current")
    monkeypatch.setattr(app_module, "get_labor_run_dir", lambda _run_id: run_dir)
    monkeypatch.setattr(labor_runs, "get_labor_run_dir", lambda _run_id: run_dir)
    monkeypatch.setattr(app_module, "sync_labor_run_to_persistent", lambda *_: None)
    job = jobs.enqueue_labor_worker_job(
        "labor_own",
        owner_user_id="user-1",
        task_generation_id="generation-current",
    )
    jobs.claim_labor_worker_job(owner_user_id="user-1", device_id="device-a", worker_version=CURRENT_WORKER_VERSION)
    headers = {"authorization": "Bearer token-user-1", "x-worker-version": CURRENT_WORKER_VERSION}
    current = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    incoming = _complete_result_metadata(current)
    accepted = client.post(
        f"/api/labor/worker/jobs/{job['id']}/result",
        headers=headers,
        files={
            "result_archive": (
                "good.zip",
                _zip_bytes({"metadata.json": json.dumps(incoming).encode(), "result.xlsx": b"report"}),
                "application/zip",
            )
        },
    )
    changed = client.post(
        "/api/labor/runs/labor_own/mapping",
        json={
            "sheet_name": "Sheet1",
            "mapping": {"name": "Employee", "hours": "Hours", "amount": "Changed Amount"},
        },
    )
    completed = client.post(f"/api/labor/worker/jobs/{job['id']}/complete", headers=headers)

    assert accepted.status_code == 200
    assert changed.status_code == 200
    assert completed.status_code == 409
    saved = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    assert saved["taskGenerationId"] == "generation-current"
    assert saved["resultInputFingerprint"] == ""
    assert "diffReport" not in saved["files"]


def test_report_file_tamper_after_acceptance_blocks_completion(monkeypatch, tmp_path):
    client = _configure(monkeypatch, tmp_path)
    run_dir = _generation_run(tmp_path, "generation-current")
    monkeypatch.setattr(app_module, "get_labor_run_dir", lambda _run_id: run_dir)
    monkeypatch.setattr(labor_runs, "get_labor_run_dir", lambda _run_id: run_dir)
    monkeypatch.setattr(app_module, "sync_labor_run_to_persistent", lambda *_: None)
    job = jobs.enqueue_labor_worker_job(
        "labor_own",
        owner_user_id="user-1",
        task_generation_id="generation-current",
    )
    jobs.claim_labor_worker_job(owner_user_id="user-1", device_id="device-a", worker_version=CURRENT_WORKER_VERSION)
    headers = {"authorization": "Bearer token-user-1", "x-worker-version": CURRENT_WORKER_VERSION}
    current = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    incoming = _complete_result_metadata(current)
    accepted = client.post(
        f"/api/labor/worker/jobs/{job['id']}/result",
        headers=headers,
        files={
            "result_archive": (
                "good.zip",
                _zip_bytes({"metadata.json": json.dumps(incoming).encode(), "result.xlsx": b"report"}),
                "application/zip",
            )
        },
    )
    (run_dir / "result.xlsx").write_bytes(b"tampered")

    completed = client.post(f"/api/labor/worker/jobs/{job['id']}/complete", headers=headers)

    assert accepted.status_code == 200
    assert completed.status_code == 409
    saved = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    assert saved["status"] == "抽取失败"
    assert saved["diffDownloadUrl"] == ""
    assert "diffReport" not in saved["files"]
    assert app_module._build_labor_readiness_gate(saved)["ready"] is False


def test_input_file_tamper_after_acceptance_blocks_completion(monkeypatch, tmp_path):
    client = _configure(monkeypatch, tmp_path)
    run_dir = _generation_run(tmp_path, "generation-current")
    monkeypatch.setattr(app_module, "get_labor_run_dir", lambda _run_id: run_dir)
    monkeypatch.setattr(labor_runs, "get_labor_run_dir", lambda _run_id: run_dir)
    monkeypatch.setattr(app_module, "sync_labor_run_to_persistent", lambda *_: None)
    job = jobs.enqueue_labor_worker_job(
        "labor_own",
        owner_user_id="user-1",
        task_generation_id="generation-current",
    )
    jobs.claim_labor_worker_job(owner_user_id="user-1", device_id="device-a", worker_version=CURRENT_WORKER_VERSION)
    headers = {"authorization": "Bearer token-user-1", "x-worker-version": CURRENT_WORKER_VERSION}
    current = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    incoming = _complete_result_metadata(current)
    accepted = client.post(
        f"/api/labor/worker/jobs/{job['id']}/result",
        headers=headers,
        files={
            "result_archive": (
                "good.zip",
                _zip_bytes({"metadata.json": json.dumps(incoming).encode(), "result.xlsx": b"report"}),
                "application/zip",
            )
        },
    )
    (run_dir / "invoice.pdf").write_bytes(b"changed input")

    completed = client.post(f"/api/labor/worker/jobs/{job['id']}/complete", headers=headers)

    assert accepted.status_code == 200
    assert completed.status_code == 409
    saved = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    assert saved["status"] == "抽取失败"
    assert saved["resultInputFingerprint"] == ""
    assert "diffReport" not in saved["files"]
    assert app_module._build_labor_readiness_gate(saved)["ready"] is False


def test_zero_byte_report_record_is_never_ready(monkeypatch, tmp_path):
    run_dir = tmp_path / "runs" / "labor_own"
    run_dir.mkdir(parents=True)
    report = run_dir / "empty.xlsx"
    report.write_bytes(b"")
    record = {
        "filename": report.name,
        "path": str(report),
        "sizeBytes": 0,
        "sha256": hashlib.sha256(b"").hexdigest(),
    }

    assert app_module._labor_diff_report_file_exists({"id": "labor_own"}, record) is False


@pytest.mark.parametrize("failure_stage", ["sync", "mark", "lease-expired"])
def test_post_merge_acceptance_failure_invalidates_formal_result_and_remains_retryable(
    monkeypatch,
    tmp_path,
    failure_stage,
):
    client = _configure(monkeypatch, tmp_path)
    run_dir = _generation_run(tmp_path, "generation-current")
    monkeypatch.setattr(app_module, "get_labor_run_dir", lambda _run_id: run_dir)
    monkeypatch.setattr(labor_runs, "get_labor_run_dir", lambda _run_id: run_dir)
    if failure_stage == "sync":
        monkeypatch.setattr(
            app_module,
            "sync_labor_run_to_persistent",
            lambda *_: (_ for _ in ()).throw(RuntimeError("sync failed")),
        )
    else:
        monkeypatch.setattr(app_module, "sync_labor_run_to_persistent", lambda *_: None)
        monkeypatch.setattr(
            app_module,
            "mark_labor_worker_result_accepted",
            lambda *_, **__: (_ for _ in ()).throw(
                jobs.LaborWorkerLeaseError("lease expired")
                if failure_stage == "lease-expired"
                else RuntimeError("mark failed")
            ),
        )
    job = jobs.enqueue_labor_worker_job(
        "labor_own",
        owner_user_id="user-1",
        task_generation_id="generation-current",
    )
    jobs.claim_labor_worker_job(owner_user_id="user-1", device_id="device-a", worker_version=CURRENT_WORKER_VERSION)
    headers = {"authorization": "Bearer token-user-1", "x-worker-version": CURRENT_WORKER_VERSION}
    current = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    incoming = _complete_result_metadata(current)

    response = client.post(
        f"/api/labor/worker/jobs/{job['id']}/result",
        headers=headers,
        files={
            "result_archive": (
                "good.zip",
                _zip_bytes({"metadata.json": json.dumps(incoming).encode(), "result.xlsx": b"report"}),
                "application/zip",
            )
        },
    )

    assert response.status_code == 503
    stored_job = jobs.get_labor_worker_job(job["id"])
    assert stored_job["resultAcceptedAt"] == ""
    saved = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    assert saved["taskGenerationId"] == "generation-current"
    assert saved["status"] == "抽取失败"
    assert saved["retryable"] is True
    assert saved["diffDownloadUrl"] == ""
    assert "diffReport" not in saved["files"]
    assert app_module._build_labor_readiness_gate(saved)["ready"] is False


@pytest.mark.parametrize("failure_stage", ["too-large", "read-error"])
def test_new_result_upload_read_failure_revokes_old_ready_result(
    monkeypatch,
    tmp_path,
    failure_stage,
):
    client = _configure(monkeypatch, tmp_path)
    run_dir = _generation_run(tmp_path, "generation-current")
    monkeypatch.setattr(app_module, "get_labor_run_dir", lambda _run_id: run_dir)
    monkeypatch.setattr(labor_runs, "get_labor_run_dir", lambda _run_id: run_dir)
    monkeypatch.setattr(app_module, "sync_labor_run_to_persistent", lambda *_: None)
    job = jobs.enqueue_labor_worker_job(
        "labor_own",
        owner_user_id="user-1",
        task_generation_id="generation-current",
    )
    jobs.claim_labor_worker_job(owner_user_id="user-1", device_id="device-a", worker_version=CURRENT_WORKER_VERSION)
    headers = {"authorization": "Bearer token-user-1", "x-worker-version": CURRENT_WORKER_VERSION}
    current = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    incoming = _complete_result_metadata(current)
    accepted = client.post(
        f"/api/labor/worker/jobs/{job['id']}/result",
        headers=headers,
        files={
            "result_archive": (
                "good.zip",
                _zip_bytes({"metadata.json": json.dumps(incoming).encode(), "result.xlsx": b"report"}),
                "application/zip",
            )
        },
    )
    assert accepted.status_code == 200
    assert app_module._build_labor_readiness_gate(
        json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    )["ready"] is True

    class OversizedPayload:
        def __len__(self):
            return 200 * 1024 * 1024 + 1

    class FailingUpload:
        async def read(self, _limit):
            if failure_stage == "read-error":
                raise OSError("read failed")
            return OversizedPayload()

    with pytest.raises(app_module.HTTPException) as caught:
        asyncio.run(
            app_module.upload_personal_labor_worker_result(
                job["id"],
                FailingUpload(),
                authorization="Bearer token-user-1",
                x_worker_version=CURRENT_WORKER_VERSION,
            )
        )

    assert caught.value.status_code == (413 if failure_stage == "too-large" else 503)
    stored_job = jobs.get_labor_worker_job(job["id"])
    assert stored_job["resultAcceptedAt"] == ""
    saved = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    assert saved["taskGenerationId"] == "generation-current"
    assert saved["diffDownloadUrl"] == ""
    assert "diffReport" not in saved["files"]
    assert saved["comparisonSummary"] == {}
    assert saved["comparisonRows"] == []
    assert saved["resultInputFingerprint"] == ""
    assert app_module._build_labor_readiness_gate(saved)["ready"] is False


def _result_zip() -> bytes:
    from io import BytesIO
    import zipfile

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("business-report.html", "done")
    return buffer.getvalue()


def _generation_run(tmp_path, generation: str):
    run_dir = tmp_path / "runs" / "labor_own"
    run_dir.mkdir(parents=True)
    invoice = run_dir / "invoice.pdf"
    workbook = run_dir / "bill.xlsx"
    invoice.write_bytes(b"pdf")
    workbook.write_bytes(b"xlsx")
    metadata = {
        "id": "labor_own",
        "ownerUserId": "user-1",
        "supplierName": "Supplier",
        "periodStart": "2026-07-01",
        "periodEnd": "2026-07-07",
        "currency": "EUR",
        "status": "抽取中",
        "taskGenerationId": generation,
        "asyncTask": {"status": "running", "taskGenerationId": generation},
        "workbookSheet": "Sheet1",
        "excelMapping": {"name": "Employee", "hours": "Hours", "amount": "Amount"},
        "files": {
            "pdfInvoices": [
                {
                    "filename": "invoice.pdf",
                    "path": str(invoice),
                    "sizeBytes": invoice.stat().st_size,
                    "sha256": hashlib.sha256(invoice.read_bytes()).hexdigest(),
                }
            ],
            "workbooks": [
                {
                    "filename": "bill.xlsx",
                    "path": str(workbook),
                    "sizeBytes": workbook.stat().st_size,
                    "sha256": hashlib.sha256(workbook.read_bytes()).hexdigest(),
                }
            ],
            "workbook": {
                "filename": "bill.xlsx",
                "path": str(workbook),
                "sizeBytes": workbook.stat().st_size,
                "sha256": hashlib.sha256(workbook.read_bytes()).hexdigest(),
            },
        },
    }
    metadata["resultInputFingerprint"] = worker_archive._result_input_fingerprint(metadata)
    (run_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    return run_dir


def _complete_result_metadata(current: dict, *, report: bytes = b"report") -> dict:
    download_url = "/api/labor/runs/labor_own/download/result.xlsx"
    return {
        "status": "已生成差异报告",
        "asyncTask": {
            "status": "succeeded",
            "taskGenerationId": current["taskGenerationId"],
        },
        "comparisonSummary": {
            "canRelease": True,
            "conclusionLevel": "pass",
            "exceptionCount": 0,
            "pdfEmployeeCount": 1,
            "excelEmployeeCount": 1,
        },
        "comparisonRows": [{"employeeName": "Alice", "matchStatus": "通过"}],
        "candidateMatches": [],
        "warehouseComparison": {},
        "extractionQuality": {"level": "ok"},
        "reconciliationDiagnostics": {"level": "ok", "issues": []},
        "costSummaries": [],
        "invoiceEvidenceAudit": [],
        "reviewQueues": {},
        "structureReconciliation": {},
        "batchGuard": {"status": "ok", "allowReleasableReport": True},
        "pdfExtractedRows": [{"employee_name_raw": "Alice", "amount": 100}],
        "excelRows": [{"employee_name_raw": "Alice", "amount": 100}],
        "files": {
            "diffReport": {
                "filename": "result.xlsx",
                "path": "/worker/result.xlsx",
                "downloadUrl": download_url,
                "sizeBytes": len(report),
                "sha256": hashlib.sha256(report).hexdigest(),
            }
        },
        "machineCheckStatus": "passed",
        "diffDownloadUrl": download_url,
        "resultInputFingerprint": worker_archive._result_input_fingerprint(current),
        "taskGenerationId": current["taskGenerationId"],
    }


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()
