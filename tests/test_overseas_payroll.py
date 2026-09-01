from __future__ import annotations

import base64
import asyncio
import hashlib
import json
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from bonus_platform.app import app
from bonus_platform.engine.overseas_payroll import service
from bonus_platform.engine.overseas_payroll import router as payroll_router
from bonus_platform.engine.overseas_payroll import tasks
from bonus_platform.engine.overseas_payroll.router import ASYNC_ADAPTER_PATH, FRONTEND_PATH, page_router, router


def test_lists_eight_handover_tools() -> None:
    tools = service.list_tools()

    assert len(tools) == 8
    assert {tool["id"] for tool in tools} == {
        "swedish_tax",
        "dutch_pension",
        "humana_details",
        "import_paie",
        "norway_payslip",
        "norway_payment",
        "italy_payslip",
        "dutch_payslip",
    }


def test_vendored_frontend_matches_handover_checksum() -> None:
    digest = hashlib.sha256(FRONTEND_PATH.read_bytes()).hexdigest()

    assert digest == "539bb0da81d9ca7c9a4d31a3416588b51f51b57ed2fbe32de2c58dc80de622bc"


def test_routers_expose_native_and_original_frontend_contracts() -> None:
    native_paths = {route.path for route in router.routes}
    compatibility_paths = {route.path for route in page_router.routes}

    assert "/api/overseas-payroll/tools" in native_paths
    assert "/api/overseas-payroll/tools/{tool_id}/process" in native_paths
    assert "/api/overseas-payroll/tasks" in native_paths
    assert "/api/overseas-payroll/tasks/{task_id}/enqueue" in native_paths
    assert {"/overseas-payroll.html", "/api/tools", "/api/tool/{tool_id}/process"} <= compatibility_paths


def test_original_page_is_unchanged_and_runtime_loads_async_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIGMA_LABOR_AUTH_REQUIRED", "0")

    with TestClient(app) as client:
        page = client.get("/overseas-payroll.html")
        adapter = client.get("/overseas-payroll-async.js")
    asyncio.set_event_loop(asyncio.new_event_loop())

    assert page.status_code == 200
    assert '<script src="/overseas-payroll-async.js?v=2"></script>' in page.text
    assert adapter.status_code == 200
    assert adapter.content == ASYNC_ADAPTER_PATH.read_bytes()
    assert b"getElementById('sidefoot')?.remove()" in adapter.content
    assert b"getElementById('hostwarn')?.remove()" in adapter.content
    assert b"const moduleHomeUrl = '/overseas-compensation.html'" in adapter.content
    assert b"user.avatarUrl" in adapter.content
    assert b"brand.setAttribute('role', 'link')" in adapter.content


def test_overseas_compensation_parent_keeps_invoice_audit_separate() -> None:
    static_root = FRONTEND_PATH.parents[3] / "static"
    home = (static_root / "index.html").read_text(encoding="utf-8")
    parent = (static_root / "overseas-compensation.html").read_text(encoding="utf-8")

    assert 'href="overseas-compensation.html" data-module-any="fbu overseas"' in home
    assert 'href="fbu-performance.html" data-child-module="fbu"' in parent
    assert 'href="overseas-payroll.html" data-child-module="overseas"' in parent
    assert "8 项海外薪资工具" in parent
    assert "海外劳务报账核对保持独立" in parent


def test_single_file_tool_returns_decoded_content(monkeypatch: pytest.MonkeyPatch) -> None:
    encoded = base64.b64encode(b"xlsx-result").decode("ascii")
    legacy = SimpleNamespace(process_swedish_tax=lambda filename, raw: ("result.xlsx", encoded, "2 名员工"))
    monkeypatch.setattr(service, "_legacy_module", lambda: legacy)

    result = service.process_files("swedish_tax", [("tax.pdf", b"pdf")])

    assert result.filename == "result.xlsx"
    assert result.content == b"xlsx-result"
    assert result.summary == "2 名员工"


def test_multi_file_tool_builds_legacy_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def process(payload):
        captured.update(payload)
        return "paie.zip", base64.b64encode(b"zip-result").decode("ascii"), "生成完成"

    monkeypatch.setattr(service, "_legacy_module", lambda: SimpleNamespace(process_import_paie_multi=process))

    result = service.process_files("import_paie", [("source.xlsx", b"source"), ("template.xlsx", b"template")])

    assert result.content == b"zip-result"
    assert [item["filename"] for item in captured["files"]] == ["source.xlsx", "template.xlsx"]


def test_rejects_wrong_extension_before_loading_parsers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "_legacy_module", lambda: pytest.fail("parser should not load"))

    with pytest.raises(ValueError, match="格式不支持"):
        service.process_files("swedish_tax", [("tax.xlsx", b"data")])


def test_rejects_multiple_files_for_single_file_tool() -> None:
    with pytest.raises(ValueError, match="只支持一个文件"):
        service.process_files("italy_payslip", [("a.pdf", b"a"), ("b.pdf", b"b")])


def test_local_async_task_upload_process_and_download(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = b"small-pdf-input"
    result = service.ProcessResult(
        filename="result.xlsx",
        content=b"xlsx-output",
        summary="1 名员工",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    monkeypatch.setenv("SIGMA_LABOR_AUTH_REQUIRED", "0")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.setattr(tasks, "TASK_ROOT", tmp_path / "tasks")
    monkeypatch.setattr(payroll_router, "process_files", lambda _tool, files: result if files == [("tax.pdf", source)] else None)

    with TestClient(app) as client:
        created = client.post(
            "/api/overseas-payroll/tasks",
            json={
                "toolId": "swedish_tax",
                "files": [
                    {
                        "filename": "tax.pdf",
                        "sizeBytes": len(source),
                        "sha256": hashlib.sha256(source).hexdigest(),
                        "contentType": "application/pdf",
                    }
                ],
            },
        )
        assert created.status_code == 200
        payload = created.json()
        task_id = payload["task"]["id"]
        intent = payload["intents"][0]
        assert client.put(intent["signedUrl"], content=source, headers=intent["headers"]).status_code == 200
        assert client.post(
            f"/api/overseas-payroll/tasks/{task_id}/files/{intent['fileId']}/finalize"
        ).status_code == 200
        assert client.post(f"/api/overseas-payroll/tasks/{task_id}/enqueue").status_code == 200

        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            current = client.get(f"/api/overseas-payroll/tasks/{task_id}").json()
            if current["status"] in {"succeeded", "failed"}:
                break
            time.sleep(0.02)

        assert current["status"] == "succeeded"
        download = client.get(f"/api/overseas-payroll/tasks/{task_id}/download").json()
        response = client.get(download["signedUrl"])
        assert response.content == result.content
    asyncio.set_event_loop(asyncio.new_event_loop())


def test_cloud_task_downloads_processes_and_persists_result(monkeypatch: pytest.MonkeyPatch) -> None:
    source = b"private-object-input"
    result = service.ProcessResult(
        filename="cloud-result.xlsx",
        content=b"private-object-output",
        summary="云端处理完成",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    state = {
        "id": "payroll_task_cloud",
        "ownerUserId": "user-1",
        "toolId": "swedish_tax",
        "status": "queued",
        "files": [{"id": "file-1", "filename": "tax.pdf"}],
        "output": None,
    }
    stored = {}

    def update(_task_id, *, owner_user_id, updater):
        assert owner_user_id == "user-1"
        state.update(updater(dict(state)))
        return dict(state)

    def prepare(_task_id, *, owner_user_id, filename, size_bytes, sha256, content_type):
        assert owner_user_id == "user-1"
        state["output"] = {"id": "output-1", "filename": filename}
        assert size_bytes == len(result.content)
        assert sha256 == hashlib.sha256(result.content).hexdigest()
        assert content_type == result.media_type
        return dict(state), {"outputId": "output-1"}

    def store(_task_id, *, owner_user_id, output_id, content):
        stored.update(owner=owner_user_id, output_id=output_id, content=content)

    def finalize(_task_id, *, owner_user_id, summary):
        assert owner_user_id == "user-1"
        state.update(status="succeeded", statusLabel="处理完成", summary=summary)
        return dict(state)

    monkeypatch.setattr(payroll_router, "update_task", update)
    monkeypatch.setattr(payroll_router, "load_task_inputs", lambda task: [("tax.pdf", source)])
    monkeypatch.setattr(payroll_router, "process_files", lambda tool_id, files: result)
    monkeypatch.setattr(payroll_router, "prepare_output", prepare)
    monkeypatch.setattr(payroll_router, "store_task_output", store)
    monkeypatch.setattr(payroll_router, "finalize_output", finalize)

    completed = payroll_router._run_task("payroll_task_cloud", "user-1", cloud=True)

    assert completed["status"] == "succeeded"
    assert completed["summary"] == result.summary
    assert stored == {"owner": "user-1", "output_id": "output-1", "content": result.content}


def test_private_storage_enqueue_runs_in_vercel_function(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIGMA_LABOR_AUTH_REQUIRED", "0")
    task = {
        "id": "payroll_task_cloud",
        "ownerUserId": "local-default",
        "toolId": "swedish_tax",
        "status": "ready",
        "files": [],
        "output": None,
    }
    statuses = []

    monkeypatch.setattr(payroll_router, "labor_supabase_storage_enabled", lambda: True)
    monkeypatch.setattr(payroll_router, "load_task", lambda *_args, **_kwargs: dict(task))

    def update(_task_id, *, owner_user_id, updater):
        updated = updater(dict(task))
        task.update(updated)
        statuses.append(task["status"])
        return dict(task)

    monkeypatch.setattr(payroll_router, "update_task", update)

    def run(_task_id, owner_user_id, *, cloud):
        assert owner_user_id == "local-default"
        assert cloud is True
        return {**task, "status": "succeeded", "statusLabel": "处理完成"}

    monkeypatch.setattr(payroll_router, "_run_task", run)

    with TestClient(app) as client:
        response = client.post("/api/overseas-payroll/tasks/payroll_task_cloud/enqueue")
    asyncio.set_event_loop(asyncio.new_event_loop())

    assert response.status_code == 200
    assert response.json()["task"]["status"] == "succeeded"
    assert statuses == ["queued"]


def test_private_task_manifest_reads_bypass_storage_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    task = {
        "id": "payroll_task_cloud",
        "ownerUserId": "user-1",
        "toolId": "swedish_tax",
        "status": "ready",
        "files": [],
        "output": None,
    }
    observed = {}

    def get_manifest(_key, **kwargs):
        observed.update(kwargs)
        return json.dumps(task).encode("utf-8")

    monkeypatch.setattr(tasks, "labor_supabase_storage_enabled", lambda: True)
    monkeypatch.setattr(tasks, "get_labor_supabase_private_object", get_manifest)

    assert tasks.load_task("payroll_task_cloud", owner_user_id="user-1")["status"] == "ready"
    assert observed == {"bypass_cache": True}


def test_private_task_inputs_are_downloaded_and_hash_verified(monkeypatch: pytest.MonkeyPatch) -> None:
    content = b"verified-private-input"
    task = {
        "id": "payroll_task_cloud",
        "files": [
            {
                "id": "file-1",
                "filename": "tax.pdf",
                "status": "uploaded",
                "objectKey": "private/input.pdf",
                "sizeBytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        ],
    }
    monkeypatch.setattr(tasks, "labor_supabase_storage_enabled", lambda: True)
    monkeypatch.setattr(tasks, "get_labor_supabase_private_object", lambda key: content if key == "private/input.pdf" else None)

    assert tasks.load_task_inputs(task) == [("tax.pdf", content)]

    task["files"][0]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="SHA-256"):
        tasks.load_task_inputs(task)
