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

import httpx
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from bonus_platform.engine.social_insurance import adapter
from bonus_platform.engine.social_insurance import persistent_storage as storage
from bonus_platform.engine.social_insurance import publication
from bonus_platform.engine.social_insurance import reporting_diagnostics
from bonus_platform.engine.social_insurance import router
from bonus_platform.engine.social_insurance import runs
from bonus_platform.engine.social_insurance import supplements
from bonus_platform.engine.social_insurance.runs import RunValidationError


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _enable_blob(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIGMA_SOCIAL_INSURANCE_STORAGE_BACKEND", "blob")
    monkeypatch.setenv("SIGMA_SOCIAL_INSURANCE_STORAGE_ENV", "test")
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "vercel_blob_rw_test_token")


def _enable_supabase(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIGMA_SOCIAL_INSURANCE_STORAGE_BACKEND", "supabase")
    monkeypatch.setenv("SIGMA_SOCIAL_INSURANCE_STORAGE_ENV", "test")
    monkeypatch.setenv("SUPABASE_URL", "https://storage.test")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role-secret")
    monkeypatch.setenv("SIGMA_LABOR_SUPABASE_BUCKET", "sigma-labor-private")


class FakeSupabaseClient:
    def __init__(self, remote: dict[str, bytes]):
        self.remote = remote

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def post(self, url, *, headers=None, content=None, json=None):
        path = httpx.URL(url).path
        if "/object/list/" in path:
            prefix = str((json or {}).get("prefix") or "").rstrip("/")
            offset = int((json or {}).get("offset") or 0)
            limit = int((json or {}).get("limit") or 1000)
            entries: dict[str, dict[str, object]] = {}
            for key in sorted(self.remote):
                if not key.startswith(prefix + "/"):
                    continue
                relative = key[len(prefix) + 1 :]
                name, separator, _nested = relative.partition("/")
                if separator:
                    entries.setdefault(
                        name,
                        {"name": name, "id": None, "metadata": None},
                    )
                    continue
                entries[name] = {
                    "name": name,
                    "id": "object-id",
                    "metadata": {"size": len(self.remote[key])},
                    "updated_at": "2026-08-26T08:00:00Z",
                }
            return self._response(
                "POST",
                url,
                200,
                json_body=list(entries.values())[offset : offset + limit],
            )
        marker = "/object/sigma-labor-private/"
        object_path = path.split(marker, 1)[1]
        self.remote[object_path] = bytes(content or b"")
        return self._response("POST", url, 200, json_body={"Key": object_path})

    def get(self, url, *, headers=None):
        marker = "/object/sigma-labor-private/"
        object_path = httpx.URL(url).path.split(marker, 1)[1]
        if object_path not in self.remote:
            return self._response("GET", url, 404)
        return self._response("GET", url, 200, content=self.remote[object_path])

    @staticmethod
    def _response(method, url, status, *, content=b"", json_body=None):
        request = httpx.Request(method, url)
        if json_body is not None:
            return httpx.Response(status, request=request, json=json_body)
        return httpx.Response(status, request=request, content=content)


class DeniedSupabaseClient(FakeSupabaseClient):
    def get(self, url, *, headers=None):
        return self._response("GET", url, 403)


class LegacyMissingObjectSupabaseClient(FakeSupabaseClient):
    def get(self, url, *, headers=None):
        marker = "/object/sigma-labor-private/"
        object_path = httpx.URL(url).path.split(marker, 1)[1]
        if object_path not in self.remote:
            return self._response(
                "GET",
                url,
                400,
                json_body={
                    "statusCode": "404",
                    "error": "not_found",
                    "message": "Object not found",
                },
            )
        return super().get(url, headers=headers)


class InvalidRequestSupabaseClient(FakeSupabaseClient):
    def get(self, url, *, headers=None):
        return self._response(
            "GET",
            url,
            400,
            json_body={
                "statusCode": "400",
                "error": "invalid_request",
                "message": "Invalid request",
            },
        )


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


def test_supabase_storage_round_trips_and_lists_reporting_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_supabase(monkeypatch)
    remote: dict[str, bytes] = {}
    monkeypatch.setattr(
        "bonus_platform.engine.labor.persistent_storage.httpx.Client",
        lambda **_kwargs: FakeSupabaseClient(remote),
    )

    storage.persist_json(
        "reporting-releases",
        "latest",
        {"releaseId": "release-20260826", "state": "ready"},
    )

    assert storage.storage_status()["backend"] == "supabase"
    assert storage.storage_status()["persistent"] is True
    assert storage.load_json("reporting-releases", "latest") == {
        "releaseId": "release-20260826",
        "state": "ready",
    }
    assert storage.list_json("reporting-releases") == [
        {"releaseId": "release-20260826", "state": "ready"}
    ]
    assert set(remote) == {
        "social-insurance/test/reporting-releases/latest.json"
    }


def test_supabase_legacy_missing_object_response_is_an_empty_json_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_supabase(monkeypatch)
    monkeypatch.setattr(
        "bonus_platform.engine.labor.persistent_storage.httpx.Client",
        lambda **_kwargs: LegacyMissingObjectSupabaseClient({}),
    )

    assert storage.load_json("baselines", "missing-baseline") is None


def test_supabase_unrelated_bad_request_is_still_a_storage_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_supabase(monkeypatch)
    monkeypatch.setattr(
        "bonus_platform.engine.labor.persistent_storage.httpx.Client",
        lambda **_kwargs: InvalidRequestSupabaseClient({}),
    )

    with pytest.raises(storage.SocialInsuranceStorageError) as exc_info:
        storage.load_json("baselines", "invalid-request")

    assert exc_info.value.code == "SOCIAL_INSURANCE_STORAGE_HTTP_ERROR"
    assert exc_info.value.status_code == 400


def test_supabase_storage_restores_complete_run_on_another_instance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _enable_supabase(monkeypatch)
    remote: dict[str, bytes] = {}
    monkeypatch.setattr(
        "bonus_platform.engine.labor.persistent_storage.httpx.Client",
        lambda **_kwargs: LegacyMissingObjectSupabaseClient(remote),
    )
    run_id = "sir_20260826120000_abcd1234"
    source = tmp_path / "instance-a" / run_id
    source.mkdir(parents=True)
    (source / "run.json").write_text(
        json.dumps(
            {"id": run_id, "subject": "深圳测试主体", "employees": []},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    report = source / "reports" / "社保增员报盘.xlsx"
    report.parent.mkdir()
    report.write_bytes(b"xlsx-content")
    (source / "ignored.tmp").write_bytes(b"temporary")

    storage.persist_run_directory(run_id, source)

    target = tmp_path / "instance-b" / run_id
    assert storage.restore_run_directory(run_id, target) is True
    restored_run = json.loads((target / "run.json").read_text(encoding="utf-8"))
    assert restored_run["subject"] == "深圳测试主体"
    assert (target / "reports" / "社保增员报盘.xlsx").read_bytes() == b"xlsx-content"
    assert storage.list_persisted_runs() == [
        {"id": run_id, "subject": "深圳测试主体", "employees": []}
    ]

    (source / "run.json").write_text(
        json.dumps(
            {"id": run_id, "subject": "深圳测试主体（已更新）", "employees": []},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    storage.persist_run_directory(run_id, source)
    assert storage.restore_run_directory(run_id, target) is True
    restored_run = json.loads((target / "run.json").read_text(encoding="utf-8"))
    assert restored_run["subject"] == "深圳测试主体（已更新）"

    assert "social-insurance/test/runs/sir_20260826120000_abcd1234/ignored.tmp" not in remote
    assert set(remote) == {
        "social-insurance/test/runs/sir_20260826120000_abcd1234/.storage-manifest.json",
        "social-insurance/test/runs/sir_20260826120000_abcd1234/reports/社保增员报盘.xlsx",
        "social-insurance/test/runs/sir_20260826120000_abcd1234/run.json",
    }


def test_supabase_permission_failure_keeps_storage_diagnostic_category(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_supabase(monkeypatch)
    monkeypatch.setattr(
        "bonus_platform.engine.labor.persistent_storage.httpx.Client",
        lambda **_kwargs: DeniedSupabaseClient({}),
    )

    with pytest.raises(storage.SocialInsuranceStorageError) as exc_info:
        storage.load_json("reporting-releases", "latest")

    assert reporting_diagnostics.safe_error_category(exc_info.value) == "storage_permission"
    assert "service-role-secret" not in str(exc_info.value)


def test_supabase_publication_is_readable_after_serverless_restart(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _enable_supabase(monkeypatch)
    monkeypatch.setenv("VERCEL", "1")
    instance_a = tmp_path / "instance-a"
    monkeypatch.setenv("SIGMA_SOCIAL_INSURANCE_RUNS_DIR", str(instance_a / "runs"))
    monkeypatch.setenv("SIGMA_SOCIAL_INSURANCE_RELEASES_DIR", str(instance_a / "releases"))
    monkeypatch.setenv("SIGMA_SOCIAL_INSURANCE_BASELINES_DIR", str(instance_a / "baselines"))
    monkeypatch.setenv("SIGMA_SOCIAL_INSURANCE_SNAPSHOTS_DIR", str(instance_a / "snapshots"))
    remote: dict[str, bytes] = {}
    monkeypatch.setattr(
        "bonus_platform.engine.labor.persistent_storage.httpx.Client",
        lambda **_kwargs: LegacyMissingObjectSupabaseClient(remote),
    )

    published = publication.materialize_all_subject_runs(
        records=[],
        source_summary={"provider": "beisen-open-platform"},
        period_start="2026-07-16",
        period_end="2026-08-15",
        confirmation_date="2026-08-26",
        subject_options=[{"value": "深圳测试主体", "label": "深圳测试主体"}],
    )
    release_id = published["releaseId"]

    instance_b = tmp_path / "instance-b"
    monkeypatch.setenv("SIGMA_SOCIAL_INSURANCE_RUNS_DIR", str(instance_b / "runs"))
    monkeypatch.setenv("SIGMA_SOCIAL_INSURANCE_RELEASES_DIR", str(instance_b / "releases"))
    loaded = publication.load_latest_reporting_release(
        period_start="2026-07-16",
        period_end="2026-08-15",
    )

    assert loaded is not None
    assert loaded["id"] == release_id
    assert loaded["state"] == "ready"
    assert loaded["batchCount"] == 1
    assert loaded["subjects"][0]["value"] == "深圳测试主体"
    assert f"social-insurance/test/reporting-releases/{release_id}.json" in remote
    assert "social-insurance/test/reporting-releases/latest.json" in remote


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


def test_run_document_fast_path_uses_the_existing_object_path_without_listing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _enable_blob(monkeypatch)
    objects: dict[str, bytes] = {}
    put_paths: list[str] = []
    get_paths: list[str] = []

    def put(pathname: str, content: bytes, **_kwargs):
        put_paths.append(pathname)
        objects[pathname] = bytes(content)
        return {"pathname": pathname}

    def get(pathname: str):
        get_paths.append(pathname)
        return objects.get(pathname.split("?", 1)[0])

    monkeypatch.setattr(storage, "blob_put_bytes", put)
    monkeypatch.setattr(storage, "blob_get_bytes", get)
    monkeypatch.setattr(
        storage,
        "blob_list_prefix",
        lambda _prefix: pytest.fail("单字段决策更新不应扫描整个批次目录"),
    )
    run_id = "sir_20260826163000_abcd1234"
    source = tmp_path / "instance-a" / run_id / "run.json"
    source.parent.mkdir(parents=True)
    source.write_text(
        json.dumps({"id": run_id, "subject": "深圳测试主体", "employees": []}, ensure_ascii=False),
        encoding="utf-8",
    )

    storage.persist_run_document(run_id, source)
    target = tmp_path / "instance-b" / run_id / "run.json"
    assert storage.restore_run_document(run_id, target) is True

    expected_path = f"social-insurance/test/runs/{run_id}/run.json"
    assert put_paths == [expected_path]
    assert get_paths and get_paths[0].split("?", 1)[0] == expected_path
    assert json.loads(target.read_text(encoding="utf-8"))["subject"] == "深圳测试主体"


def test_fast_run_document_update_remains_compatible_with_full_restore(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _enable_blob(monkeypatch)
    objects: dict[str, bytes] = {}

    monkeypatch.setattr(
        storage,
        "blob_put_bytes",
        lambda pathname, content, **_kwargs: objects.__setitem__(pathname, bytes(content))
        or {"pathname": pathname},
    )
    monkeypatch.setattr(
        storage,
        "blob_get_bytes",
        lambda pathname: objects.get(pathname.split("?", 1)[0]),
    )
    monkeypatch.setattr(
        storage,
        "blob_list_prefix",
        lambda prefix: [
            {"pathname": pathname, "uploadedAt": "2026-08-26T08:00:00Z"}
            for pathname in objects
            if pathname.startswith(prefix)
        ],
    )
    run_id = "sir_20260826163500_abcd1234"
    source_dir = tmp_path / "instance-a" / run_id
    source_dir.mkdir(parents=True)
    run_path = source_dir / "run.json"
    run_path.write_text(
        json.dumps({"id": run_id, "status": "draft", "employees": []}),
        encoding="utf-8",
    )
    report_path = source_dir / "reports" / "社保增员报盘.xlsx"
    report_path.parent.mkdir()
    report_path.write_bytes(b"existing-report")
    storage.persist_run_directory(run_id, source_dir)

    run_path.write_text(
        json.dumps({"id": run_id, "status": "confirmed", "employees": []}),
        encoding="utf-8",
    )
    storage.persist_run_document(run_id, run_path)
    restored_dir = tmp_path / "instance-b" / run_id

    assert storage.restore_run_directory(run_id, restored_dir) is True
    assert json.loads((restored_dir / "run.json").read_text(encoding="utf-8"))["status"] == "confirmed"
    assert (restored_dir / "reports" / "社保增员报盘.xlsx").read_bytes() == b"existing-report"


def test_decision_only_update_skips_full_directory_and_unchanged_search_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SIGMA_SOCIAL_INSURANCE_RUNS_DIR", str(tmp_path / "runs"))
    run = runs.create_run(
        records=[
            {
                "status": "ready",
                "reason": "规则校验通过",
                "issues": [],
                "report": {
                    "证件号码": "TEST-ID-FAST-DECISION-001",
                    "姓名": "快速决策员工",
                    "户籍": "广东省外户籍",
                    "民族": "汉族",
                    "手机号码": "13000000000",
                    "岗位类别": "工人岗位",
                    "个人身份": "工人",
                    "用工形式": "合同工",
                    "学历": "大学专科",
                    "职称": "无",
                    "国家职业资格或职业技能等级": "无",
                    "医疗缴费档次": "职工二档",
                    "户籍地类别": "农业",
                    "户口所在地行政区划代码": "450801.市辖区",
                    "就业形式": "雇佣就业",
                    "就业前身份": "其他",
                },
                "source": {"subject": "深圳测试主体", "place": "深圳", "employType": "内部员工"},
            }
        ],
        period_start="2026-07-16",
        period_end="2026-08-15",
        confirmation_date="2026-08-26",
        subject="深圳测试主体",
        source="beisen",
    )
    employee_id = run["employees"][0]["id"]
    calls: list[str] = []
    monkeypatch.setattr(runs, "persistent_storage_enabled", lambda: True)
    monkeypatch.setattr(runs, "serverless_runtime", lambda: True)
    monkeypatch.setattr(runs, "_restore_run_document", lambda _run_id: calls.append("restore-document") or True)
    monkeypatch.setattr(runs, "_restore_run", lambda _run_id: pytest.fail("不应恢复完整批次目录"))
    monkeypatch.setattr(runs, "_persist_run_document", lambda _run_id: calls.append("persist-document"))
    monkeypatch.setattr(runs, "_persist_run", lambda _run_id: pytest.fail("不应写入完整批次目录"))
    monkeypatch.setattr(runs, "persist_run_index", lambda _run, **_kwargs: calls.append("persist-index") or True)
    monkeypatch.setattr(
        runs,
        "persist_supplement_search_context",
        lambda _run: pytest.fail("决策变化不改变补充候选集合"),
    )

    updated = runs.update_employee(run["id"], employee_id, {"decision": "exclude"})

    assert updated["employees"][0]["status"] == "excluded"
    assert calls == ["restore-document", "persist-document", "persist-index"]


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


def test_vercel_routes_reporting_cron_to_an_isolated_named_python_service() -> None:
    config = json.loads((PROJECT_ROOT / "vercel.json").read_text(encoding="utf-8"))

    assert "functions" not in config
    assert config["services"] == {
        "workbench": {
            "root": ".",
            "runtime": "python",
            "entrypoint": "api/index.py",
            "functions": {
                "api/index.py": {
                    "regions": ["pdx1"],
                    "maxDuration": 300,
                }
            },
        },
        "social_insurance_cron": {
            "root": ".",
            "runtime": "python",
            "entrypoint": "api/social_insurance_cron/index.py",
            "functions": {
                "api/social_insurance_cron/index.py": {
                    "regions": ["pdx1"],
                    "maxDuration": 300,
                }
            },
        },
    }
    assert config["rewrites"][0] == {
        "source": "/api/social-insurance/cron/refresh",
        "destination": {"service": "social_insurance_cron"},
    }
    assert config["rewrites"][1] == {
        "source": "/(.*)",
        "destination": {"service": "workbench"},
    }
    assert config["env"] == {
        "SIGMA_WORKBENCH_HOME": "/tmp/sigma-workbench",
        "SIGMA_WORKBENCH_SEED_DIR": "outputs",
        "SIGMA_HIDE_DEVELOPING_MODULES": "0",
        "SIGMA_OVERSEAS_LABOR_UAT_ROLES": "Payroll Admin,Compensation UAT",
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
