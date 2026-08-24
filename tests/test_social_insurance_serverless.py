from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from bonus_platform.engine.social_insurance import adapter
from bonus_platform.engine.social_insurance import persistent_storage as storage
from bonus_platform.engine.social_insurance import router
from bonus_platform.engine.social_insurance.runs import RunValidationError


def _enable_blob(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIGMA_SOCIAL_INSURANCE_STORAGE_BACKEND", "blob")
    monkeypatch.setenv("SIGMA_SOCIAL_INSURANCE_STORAGE_ENV", "test")
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "vercel_blob_rw_test_token")


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
