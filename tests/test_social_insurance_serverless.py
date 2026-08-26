from __future__ import annotations

from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from bonus_platform.engine.social_insurance import adapter
from bonus_platform.engine.social_insurance import persistent_storage as storage
from bonus_platform.engine.social_insurance import router
from bonus_platform.engine.social_insurance import runs
from bonus_platform.engine.social_insurance import supplements
from bonus_platform.engine.social_insurance.runs import RunValidationError


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _enable_blob(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIGMA_SOCIAL_INSURANCE_STORAGE_BACKEND", "blob")
    monkeypatch.setenv("SIGMA_SOCIAL_INSURANCE_STORAGE_ENV", "test")
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "vercel_blob_rw_test_token")


def _request_cron_handler(
    handler_class: type[BaseHTTPRequestHandler],
    *,
    authorization: str = "",
) -> tuple[int, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_class)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=2)
        headers = {"Authorization": authorization} if authorization else {}
        connection.request(
            "GET",
            "/api/social-insurance/cron/refresh",
            headers=headers,
        )
        response = connection.getresponse()
        status = response.status
        payload_text = response.read().decode("utf-8")
        connection.close()
        return status, payload_text
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_vercel_runtime_refuses_ephemeral_social_insurance_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("SIGMA_SOCIAL_INSURANCE_STORAGE_BACKEND", raising=False)
    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN", raising=False)

    with pytest.raises(storage.SocialInsuranceStorageError, match="拒绝写入临时目录"):
        storage.require_persistent_storage()


def test_blob_storage_restores_complete_run_on_another_instance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _enable_blob(monkeypatch)
    objects: dict[str, bytes] = {}

    def put(pathname: str, content: bytes, **_kwargs):
        objects[pathname] = bytes(content)
        return {"pathname": pathname}

    def listed(prefix: str):
        return [
            {"pathname": pathname, "uploadedAt": "2026-08-24T12:00:00Z"}
            for pathname in objects
            if pathname.startswith(prefix)
        ]

    monkeypatch.setattr(storage, "blob_put_bytes", put)
    monkeypatch.setattr(storage, "blob_list_prefix", listed)
    get_calls: list[str] = []
    cached_reads: dict[str, bytes | None] = {}

    def get(pathname: str):
        get_calls.append(pathname)
        if pathname not in cached_reads:
            cached_reads[pathname] = objects.get(pathname.split("?", 1)[0])
        return cached_reads[pathname]

    monkeypatch.setattr(storage, "blob_get_bytes", get)

    source = tmp_path / "instance-a" / "sir_20260824120000_abcd1234"
    source.mkdir(parents=True)
    (source / "run.json").write_text(
        json.dumps({"id": source.name, "subject": "深圳测试主体", "employees": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    (source / "社保增员报盘.xlsx").write_bytes(b"xlsx-content")

    storage.persist_run_directory(source.name, source)

    target = tmp_path / "instance-b" / source.name
    assert storage.restore_run_directory(source.name, target) is True
    assert json.loads((target / "run.json").read_text(encoding="utf-8"))["subject"] == "深圳测试主体"
    assert (target / "社保增员报盘.xlsx").read_bytes() == b"xlsx-content"
    assert any("sigma-read-version=" in pathname for pathname in get_calls)

    (source / "run.json").write_text(
        json.dumps({"id": source.name, "subject": "深圳测试主体（已修改）", "employees": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    storage.persist_run_directory(source.name, source)
    storage.restore_run_directory(source.name, target)

    assert json.loads((target / "run.json").read_text(encoding="utf-8"))["subject"] == "深圳测试主体（已修改）"
    run_reads = [pathname for pathname in get_calls if "/run.json?" in pathname]
    assert len(set(run_reads)) >= 2


def test_run_context_index_is_persisted_without_employee_details(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _enable_blob(monkeypatch)
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("SIGMA_SOCIAL_INSURANCE_RUNS_DIR", str(tmp_path / "instance-a"))
    objects: dict[tuple[str, str], dict] = {}
    monkeypatch.setattr(
        runs,
        "persist_json",
        lambda namespace, key, payload: objects.__setitem__((namespace, key), json.loads(json.dumps(payload))),
    )
    monkeypatch.setattr(runs, "load_json", lambda namespace, key: objects.get((namespace, key)))
    run = {
        "id": "sir_20260825120000_abcd1234",
        "periodStart": "2026-07-16",
        "periodEnd": "2026-08-15",
        "confirmationDate": "2026-08-25",
        "subject": "深圳测试主体",
        "createdAt": "2026-08-25T04:00:00Z",
        "updatedAt": "2026-08-25T04:00:00Z",
        "summary": {"total": 1, "latestEmployeeName": "不应进入索引"},
        "employees": [{"report": {"姓名": "不应进入索引"}}],
    }

    assert runs.persist_run_index(run) is True
    monkeypatch.setenv("SIGMA_SOCIAL_INSURANCE_RUNS_DIR", str(tmp_path / "instance-b"))
    loaded = runs.load_run_index(
        period_start="2026-07-16",
        period_end="2026-08-15",
        confirmation_date="2026-08-25",
        subject="深圳测试主体",
    )

    assert loaded is not None
    assert loaded["runId"] == run["id"]
    assert "employees" not in loaded
    assert "不应进入索引" not in json.dumps(loaded, ensure_ascii=False)


def test_supplement_search_context_is_shared_without_raw_employee_identity_details(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _enable_blob(monkeypatch)
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("SIGMA_SOCIAL_INSURANCE_RUNS_DIR", str(tmp_path / "instance-a"))
    objects: dict[tuple[str, str], dict] = {}
    monkeypatch.setattr(
        runs,
        "persist_json",
        lambda namespace, key, payload: objects.__setitem__((namespace, key), json.loads(json.dumps(payload))),
    )
    monkeypatch.setattr(runs, "load_json", lambda namespace, key: objects.get((namespace, key)))
    run = {
        "id": "sir_20260825130000_abcd1234",
        "ruleVersion": runs.RULE_VERSION,
        "periodStart": "2026-07-16",
        "periodEnd": "2026-08-15",
        "confirmationDate": "2026-08-25",
        "subject": "深圳测试主体",
        "updatedAt": "2026-08-25T05:00:00Z",
        "employees": [
            {
                "report": {
                    "姓名": "不应进入轻量上下文",
                    "证件号码": "TEST-IDENTITY-CONTEXT-001",
                }
            }
        ],
    }

    assert runs.persist_supplement_search_context(run) is True
    monkeypatch.setenv("SIGMA_SOCIAL_INSURANCE_RUNS_DIR", str(tmp_path / "instance-b"))
    loaded = runs.load_supplement_search_context(run["id"])

    assert loaded is not None
    assert loaded["id"] == run["id"]
    assert loaded["subject"] == "深圳测试主体"
    assert len(loaded["existingCandidateIds"]) == 1
    serialized = json.dumps(loaded, ensure_ascii=False)
    assert "不应进入轻量上下文" not in serialized
    assert "TEST-IDENTITY-CONTEXT-001" not in serialized


def test_precomputed_supplement_index_is_read_once_per_serverless_process(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _enable_blob(monkeypatch)
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("SIGMA_SOCIAL_INSURANCE_RUNS_DIR", str(tmp_path / "instance-a"))
    objects: dict[tuple[str, str], dict] = {}
    load_calls: list[tuple[str, str]] = []

    def persist(namespace: str, key: str, payload: dict) -> None:
        objects[(namespace, key)] = json.loads(json.dumps(payload))

    def load(namespace: str, key: str) -> dict | None:
        load_calls.append((namespace, key))
        return objects.get((namespace, key))

    monkeypatch.setattr(supplements, "persist_json", persist)
    monkeypatch.setattr(supplements, "load_json", load)
    run = {
        "id": "sir_20260825140000_abcd1234",
        "updatedAt": "2026-08-25T06:00:00Z",
        "periodStart": "2026-07-16",
        "periodEnd": "2026-08-15",
        "confirmationDate": "2026-08-25",
        "subject": "深圳测试主体",
        "employees": [],
    }
    candidate = {
        "entryDate": "2026-06-03",
        "status": "ready",
        "report": {
            "姓名": "进程缓存候选",
            "证件号码": "TEST-IDENTITY-INDEX-001",
        },
        "source": {"subject": "深圳测试主体"},
    }

    supplements.publish_supplement_search_indexes(
        [run],
        records=[candidate],
        pool_status={
            "cachedAt": "2026-08-25T06:00:00Z",
            "recordCount": 1,
        },
    )
    persisted = objects[(supplements.SEARCH_INDEX_NAMESPACE, run["id"])]
    assert "TEST-IDENTITY-INDEX-001" not in json.dumps(persisted, ensure_ascii=False)

    supplements.clear_supplement_search_index_cache()
    monkeypatch.setenv("SIGMA_SOCIAL_INSURANCE_RUNS_DIR", str(tmp_path / "instance-b"))
    first = supplements.precomputed_supplement_status(run["id"])
    second = supplements.search_precomputed_supplement_candidates(run["id"], "进程缓存")
    third = supplements.search_precomputed_supplement_candidates(run["id"], "001")

    assert first is not None
    assert second is not None and [item["name"] for item in second] == ["进程缓存候选"]
    assert third is not None and [item["name"] for item in third] == ["进程缓存候选"]
    assert load_calls == [(supplements.SEARCH_INDEX_NAMESPACE, run["id"])]


def test_supplement_index_mutation_bypasses_process_miss_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _enable_blob(monkeypatch)
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("SIGMA_SOCIAL_INSURANCE_RUNS_DIR", str(tmp_path / "instance"))
    objects: dict[tuple[str, str], dict] = {}
    load_calls: list[tuple[str, str]] = []

    def persist(namespace: str, key: str, payload: dict) -> None:
        objects[(namespace, key)] = json.loads(json.dumps(payload))

    def load(namespace: str, key: str) -> dict | None:
        load_calls.append((namespace, key))
        return objects.get((namespace, key))

    monkeypatch.setattr(supplements, "persist_json", persist)
    monkeypatch.setattr(supplements, "load_json", load)
    run = {
        "id": "sir_20260825150000_abcd1234",
        "updatedAt": "2026-08-25T07:00:00Z",
        "periodStart": "2026-07-16",
        "periodEnd": "2026-08-15",
        "confirmationDate": "2026-08-25",
        "subject": "深圳测试主体",
        "employees": [],
    }
    candidate = {
        "entryDate": "2026-06-03",
        "status": "ready",
        "report": {"姓名": "迟到索引候选", "证件号码": "TEST-IDENTITY-LATE-001"},
        "source": {"subject": "深圳测试主体"},
    }
    supplements.publish_supplement_search_indexes(
        [run],
        records=[candidate],
        pool_status={"cachedAt": "2026-08-25T07:00:00Z", "recordCount": 1},
    )
    object_key = (supplements.SEARCH_INDEX_NAMESPACE, run["id"])
    published = objects.pop(object_key)
    (tmp_path / "instance" / ".supplement-search-index" / f"{run['id']}.json").unlink()
    supplements.clear_supplement_search_index_cache()
    assert supplements.load_supplement_search_index(run["id"]) is None
    objects[object_key] = published

    removed = supplements.remove_supplement_candidate_from_search_index(
        run["id"],
        published["candidates"][0]["id"],
        run_updated_at="2026-08-25T07:01:00Z",
    )

    assert removed is True
    assert objects[object_key]["candidateCount"] == 0
    assert load_calls == [object_key, object_key]


def test_remote_connector_replaces_local_engine_for_subjects_and_sync(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SIGMA_SOCIAL_INSURANCE_CONNECTOR_URL", "https://connector.example.com/social-insurance")
    monkeypatch.setenv("SIGMA_SOCIAL_INSURANCE_CONNECTOR_TOKEN", "service-token")
    adapter.clear_contract_subject_cache()
    calls: list[tuple[str, dict]] = []

    def connector_call(operation: str, payload: dict, *, timeout: float):
        calls.append((operation, payload))
        if operation == "subjects":
            return {
                "subjects": [
                    {"value": "深圳测试主体", "label": "深圳测试主体", "code": "SZ001", "candidateCount": 3}
                ]
            }
        return {
            "records": [{"status": "ready", "report": {"姓名": "测试人员"}, "source": {"subject": "深圳测试主体"}}],
            "sourceSummary": {"candidateCount": 1},
        }

    monkeypatch.setattr(adapter, "_connector_call", connector_call)

    subjects = adapter.list_beisen_contract_subjects(
        period_start="2026-07-16",
        period_end="2026-08-15",
    )
    records, summary = adapter.sync_beisen_candidates(
        period_start="2026-07-16",
        period_end="2026-08-15",
        confirmation_date="2026-08-24",
        subject="深圳测试主体",
        output_dir=tmp_path,
    )

    assert subjects[0]["candidateCount"] == 3
    assert records[0]["report"]["姓名"] == "测试人员"
    assert summary["provider"] == "beisen-remote-connector"
    assert [operation for operation, _payload in calls] == ["subjects", "sync"]


def test_vercel_runtime_refuses_local_beisen_engine_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("SIGMA_SOCIAL_INSURANCE_CONNECTOR_URL", raising=False)
    monkeypatch.delenv("SIGMA_SOCIAL_INSURANCE_CONNECTOR_TOKEN", raising=False)
    monkeypatch.delenv("SIGMA_SOCIAL_INSURANCE_SYNC_FIXTURE", raising=False)

    with pytest.raises(RunValidationError, match="必须配置远程连接器"):
        adapter.list_beisen_contract_subjects(
            period_start="2026-07-16",
            period_end="2026-08-15",
        )


def test_cron_refresh_requires_secret_and_returns_refresh_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRON_SECRET", "cron-secret")
    unauthorized = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    with pytest.raises(HTTPException) as exc_info:
        router.refresh_reporting_snapshot_from_cron(unauthorized)
    assert exc_info.value.status_code == 401

    authorized = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"authorization", b"Bearer cron-secret")],
        }
    )
    monkeypatch.setattr(
        router,
        "refresh_latest_reporting_snapshot",
        lambda: {"state": "ready", "recordCount": 34},
    )
    assert router.refresh_reporting_snapshot_from_cron(authorized) == {
        "state": "ready",
        "recordCount": 34,
    }


def test_vercel_routes_reporting_cron_to_a_minimal_dedicated_python_function() -> None:
    config = json.loads((PROJECT_ROOT / "vercel.json").read_text(encoding="utf-8"))

    assert config["rewrites"][0] == {
        "source": "/api/social-insurance/cron/refresh",
        "destination": "/api/social_insurance_cron/index.py",
    }
    assert config["rewrites"][1] == {
        "source": "/(.*)",
        "destination": "/api/index.py",
    }
    assert config["functions"]["api/social_insurance_cron/index.py"] == {
        "regions": ["pdx1"],
        "maxDuration": 300,
    }
    requirements = {
        line.strip()
        for line in (
            PROJECT_ROOT / "api" / "social_insurance_cron" / "requirements.txt"
        ).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert requirements == {
        "APScheduler==3.11.3",
        "httpx[socks]==0.28.1",
        "openpyxl==3.1.5",
    }


def test_dedicated_reporting_cron_import_skips_the_monolithic_application(
    tmp_path: Path,
) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json, logging, sys; "
                "from api.social_insurance_cron import index; "
                "print(json.dumps({"
                "'refreshReady': index.refresh_latest_reporting_snapshot is not None, "
                "'monolithicAppLoaded': 'bonus_platform.app' in sys.modules, "
                "'moduleImportMs': index._MODULE_IMPORT_MS, "
                "'httpxLogLevel': logging.getLogger('httpx').getEffectiveLevel()"
                "}))"
            ),
        ],
        cwd=PROJECT_ROOT,
        env={
            **os.environ,
            "VERCEL": "1",
            "SIGMA_WORKBENCH_HOME": str(tmp_path / "workbench"),
        },
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["refreshReady"] is True
    assert payload["monolithicAppLoaded"] is False
    assert isinstance(payload["moduleImportMs"], int)
    assert payload["moduleImportMs"] >= 0
    assert payload["httpxLogLevel"] >= logging.WARNING


def test_dedicated_reporting_cron_preserves_auth_and_refresh_response_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.social_insurance_cron import index as cron_function

    monkeypatch.setenv("CRON_SECRET", "cron-secret")
    monkeypatch.setattr(
        cron_function,
        "refresh_latest_reporting_snapshot",
        lambda: {"state": "ready", "recordCount": 34},
    )
    unauthorized_status, unauthorized_text = _request_cron_handler(
        cron_function.handler,
    )
    authorized_status, authorized_text = _request_cron_handler(
        cron_function.handler,
        authorization="Bearer cron-secret",
    )
    unauthorized_payload = json.loads(unauthorized_text)
    authorized_payload = json.loads(authorized_text)

    assert unauthorized_status == 401
    assert unauthorized_payload == {"detail": "定时同步授权失败"}
    assert authorized_status == 200
    assert authorized_payload["state"] == "ready"
    assert authorized_payload["recordCount"] == 34
    assert authorized_payload["runtime"] == "dedicated-cron-v1"
    assert set(authorized_payload["runtimeTimingsMs"]) == {
        "module_import",
        "handler_dispatch",
    }
    assert all(
        isinstance(duration, int) and duration >= 0
        for duration in authorized_payload["runtimeTimingsMs"].values()
    )


def test_dedicated_reporting_cron_returns_safe_dispatch_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from api.social_insurance_cron import index as cron_function

    sensitive_marker = "SECRET-CRON-EMPLOYEE-440301199001010044"
    monkeypatch.setenv("CRON_SECRET", "cron-secret")

    def fail_refresh():
        raise RunValidationError(sensitive_marker)

    monkeypatch.setattr(
        cron_function,
        "refresh_latest_reporting_snapshot",
        fail_refresh,
    )
    with caplog.at_level(
        logging.WARNING,
        logger="bonus_platform.social_insurance.cron_function",
    ):
        status, payload_text = _request_cron_handler(
            cron_function.handler,
            authorization="Bearer cron-secret",
        )

    payload = json.loads(payload_text)
    assert status == 500
    assert payload["state"] == "error"
    assert payload["failedStage"] == "function_dispatch"
    assert payload["errorCategory"] == "validation"
    assert payload["runtime"] == "dedicated-cron-v1"
    assert payload["stageTimingsMs"] == {
        "function_dispatch": payload["runtimeTimingsMs"]["handler_dispatch"],
    }
    assert payload["elapsedMs"] >= sum(payload["runtimeTimingsMs"].values())
    assert sensitive_marker not in payload_text
    assert sensitive_marker not in caplog.text
