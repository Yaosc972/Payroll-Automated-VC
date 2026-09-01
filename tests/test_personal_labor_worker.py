import ctypes
import json
import hashlib
import io
import os
import shlex
import sys
import threading
import zipfile
from io import BytesIO

import httpx
import pytest
from openpyxl import Workbook

from bonus_platform.worker.personal import (
    PersonalLaborWorker,
    WorkerAlreadyRunning,
    _FailoverHttpClient,
    _WorkerInstanceLock,
    _default_runner,
    _pid_is_alive,
)


def test_personal_worker_reads_desktop_token_from_one_time_stdin_pipe():
    from bonus_platform.worker import personal

    assert personal._read_worker_token("", token_stdin=True, stdin=io.StringIO("opaque-worker-token\n")) == "opaque-worker-token"
    assert personal._read_worker_token("explicit-token", token_stdin=False, stdin=io.StringIO("ignored\n")) == "explicit-token"


def test_personal_worker_normalizes_supported_desktop_platforms(monkeypatch):
    from bonus_platform.worker import personal

    monkeypatch.setattr(personal.sys, "platform", "win32")
    monkeypatch.setattr(personal.platform, "machine", lambda: "AMD64")
    assert personal._worker_platform() == "windows-x64"

    monkeypatch.setattr(personal.sys, "platform", "darwin")
    monkeypatch.setattr(personal.platform, "machine", lambda: "arm64")
    assert personal._worker_platform() == "macos-arm64"


def test_worker_http_client_falls_back_to_direct_only_before_connection_is_established():
    request = httpx.Request("GET", "https://sigma.example.com/api/labor/worker/version")

    class Client:
        def __init__(self, result):
            self.result = result
            self.calls = 0

        def request(self, *_args, **_kwargs):
            self.calls += 1
            if isinstance(self.result, Exception):
                raise self.result
            return self.result

    direct_response = httpx.Response(200, request=request)
    proxied = Client(httpx.ConnectError("proxy refused", request=request))
    direct = Client(direct_response)
    client = _FailoverHttpClient(proxied, direct)

    assert client.get(str(request.url)) is direct_response
    assert proxied.calls == 1
    assert direct.calls == 1

    proxied_timeout = Client(httpx.ReadTimeout("response stalled", request=request))
    direct_not_called = Client(direct_response)
    with pytest.raises(httpx.ReadTimeout):
        _FailoverHttpClient(proxied_timeout, direct_not_called).get(str(request.url))
    assert direct_not_called.calls == 0


def test_worker_http_stream_does_not_fallback_after_response_is_open():
    request = httpx.Request("GET", "https://sigma.example.com/private.pdf")

    class StreamContext:
        def __init__(self, response=None, enter_error=None):
            self.response = response
            self.enter_error = enter_error

        def __enter__(self):
            if self.enter_error:
                raise self.enter_error
            return self.response

        def __exit__(self, *_args):
            return False

    class Client:
        def __init__(self, context):
            self.context = context
            self.calls = 0

        def stream(self, *_args, **_kwargs):
            self.calls += 1
            return self.context

    response = httpx.Response(200, request=request)
    primary = Client(StreamContext(response=response))
    direct = Client(StreamContext(response=response))
    with pytest.raises(httpx.ConnectError):
        with _FailoverHttpClient(primary, direct).stream("GET", str(request.url)):
            raise httpx.ConnectError("read failed after response opened", request=request)
    assert primary.calls == 1
    assert direct.calls == 0

    primary_unavailable = Client(StreamContext(enter_error=httpx.ConnectError("proxy refused", request=request)))
    with _FailoverHttpClient(primary_unavailable, direct).stream("GET", str(request.url)) as opened:
        assert opened is response
    assert direct.calls == 1


def test_personal_worker_update_check_sends_platform(tmp_path, monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["platform"] = request.url.params.get("platform")
        return httpx.Response(200, json={"updateAvailable": False})

    monkeypatch.setattr("bonus_platform.worker.personal._worker_platform", lambda: "windows-x64")
    worker = PersonalLaborWorker(
        api_url="https://example.test",
        token="secret",
        worker_version="0.3.9",
        data_root=tmp_path,
        runner=lambda _: True,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    worker.check_update()

    assert seen["platform"] == "windows-x64"


def test_personal_worker_cli_does_not_offer_plaintext_token_argument(monkeypatch, capsys):
    from bonus_platform.worker import personal

    monkeypatch.setattr(sys, "argv", ["sigma-labor-worker", "--help"])
    with pytest.raises(SystemExit) as exc_info:
        personal.main()

    assert exc_info.value.code == 0
    help_text = capsys.readouterr().out
    assert "--token-stdin" in help_text
    assert "--token TOKEN" not in help_text


def test_packaged_worker_configures_self_contained_ocr_subcommand(monkeypatch):
    from bonus_platform.worker import personal

    executable = "/Applications/Sigma Labor Worker/sigma-labor-worker"
    monkeypatch.delenv("AI_OCR_COMMAND", raising=False)
    monkeypatch.setattr(personal.sys, "executable", executable)
    monkeypatch.setattr(personal.sys, "frozen", True, raising=False)

    personal._configure_default_ocr_command()

    assert shlex.split(os.environ["AI_OCR_COMMAND"]) == [executable, "--ocr-task"]


def test_personal_worker_processes_one_job_and_checks_update_after_completion(tmp_path):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/claim"):
            return httpx.Response(200, json={"job": {"id": "job-1", "runId": "labor-1", "attempt": 1}})
        if request.url.path.endswith("/input-manifest"):
            content = b"pdf-input"
            return httpx.Response(200, json={
                "metadata": {"id": "labor-1", "files": {"pdfInvoices": [{"path": "invoice.pdf"}]}},
                "files": [{"path": "invoice.pdf", "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}],
            })
        if request.url.path.endswith("/input-file"):
            return httpx.Response(200, content=b"pdf-input")
        if request.url.path.endswith("/input"):
            return httpx.Response(200, content=_zip({"metadata.json": b'{"id":"labor-1"}'}))
        if request.url.path.endswith("/result"):
            assert b"report.html" in request.content
            assert b"pdf-input" not in request.content
            return httpx.Response(200, json={"ok": True})
        if request.url.path.endswith("/complete"):
            return httpx.Response(200, json={"job": {"id": "job-1", "status": "succeeded"}})
        if request.url.path.endswith("/version"):
            return httpx.Response(200, json={"updateAvailable": True, "version": "0.2.0"})
        raise AssertionError(request.url)

    def runner(run_id: str) -> bool:
        run_dir = tmp_path / "labor_runs" / run_id
        (run_dir / "report.html").write_text("done", encoding="utf-8")
        return True

    worker = PersonalLaborWorker(
        api_url="https://example.test",
        token="secret",
        worker_version="0.1.0",
        data_root=tmp_path,
        runner=runner,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = worker.process_once()

    assert result["status"] == "succeeded"
    assert calls[-1] == ("GET", "/api/labor/worker/version")
    assert json.loads((tmp_path / "worker-update.json").read_text())["version"] == "0.2.0"


def test_personal_worker_processes_overseas_payroll_via_private_storage(tmp_path, monkeypatch):
    from bonus_platform.engine.overseas_payroll import service as payroll_service

    source = b"private-payroll-pdf"
    output = b"private-payroll-xlsx"
    storage_authorization = []
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/version"):
            return httpx.Response(404)
        if request.url.path.endswith("/claim"):
            return httpx.Response(
                200,
                json={"job": {"id": "job-payroll", "runId": "task-payroll", "jobType": "overseas_payroll", "attempt": 1}},
            )
        if request.url.path.endswith("/manifest"):
            return httpx.Response(
                200,
                json={
                    "task": {"id": "task-payroll", "toolId": "swedish_tax"},
                    "files": [
                        {
                            "id": "file-1",
                            "filename": "tax.pdf",
                            "sizeBytes": len(source),
                            "sha256": hashlib.sha256(source).hexdigest(),
                            "downloadUrl": "https://storage.example.test/private/input",
                        }
                    ],
                },
            )
        if request.url.host == "storage.example.test" and request.method == "GET":
            storage_authorization.append(request.headers.get("authorization"))
            return httpx.Response(200, content=source)
        if request.url.path.endswith("/output-intent"):
            assert request.headers["authorization"] == "Bearer secret"
            return httpx.Response(
                200,
                json={
                    "intent": {
                        "signedUrl": "https://storage.example.test/private/output",
                        "method": "PUT",
                        "headers": {"content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
                    }
                },
            )
        if request.url.host == "storage.example.test" and request.method == "PUT":
            storage_authorization.append(request.headers.get("authorization"))
            assert request.content == output
            return httpx.Response(200)
        if request.url.path.endswith("/output-finalize"):
            return httpx.Response(200, json={"status": "succeeded"})
        if request.url.path.endswith("/complete"):
            return httpx.Response(200, json={"job": {"id": "job-payroll", "status": "succeeded"}})
        raise AssertionError(request.url)

    monkeypatch.setattr(
        payroll_service,
        "process_files",
        lambda tool_id, files: payroll_service.ProcessResult(
            "result.xlsx",
            output,
            "1 名员工",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ) if tool_id == "swedish_tax" and files == [("tax.pdf", source)] else None,
    )
    worker = PersonalLaborWorker(
        api_url="https://example.test",
        token="secret",
        worker_version="0.3.15",
        data_root=tmp_path,
        runner=lambda _: pytest.fail("labor runner should not execute"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    completed = worker.process_once()

    assert completed["status"] == "succeeded"
    assert storage_authorization == [None, None]
    assert ("POST", "/api/overseas-payroll/worker/jobs/job-payroll/output-finalize") in calls


def test_personal_worker_downloads_p1_input_from_private_signed_url_and_materializes_paths(tmp_path):
    content = b"private-pdf-input"
    seen_storage_authorization = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/version"):
            return httpx.Response(404)
        if request.url.path.endswith("/claim"):
            return httpx.Response(200, json={"job": {"id": "job-p1", "runId": "labor-p1", "attempt": 1}})
        if request.url.path.endswith("/input-manifest"):
            return httpx.Response(
                200,
                json={
                    "metadata": {
                        "id": "labor-p1",
                        "files": {"pdfInvoices": [{"id": "file-1", "path": "inputs/file-1/invoice.pdf"}]},
                    },
                    "files": [
                        {
                            "fileId": "file-1",
                            "path": "inputs/file-1/invoice.pdf",
                            "size": len(content),
                            "sha256": hashlib.sha256(content).hexdigest(),
                            "signedUrl": "https://project.supabase.co/storage/v1/object/sign/private?token=short",
                        }
                    ],
                },
            )
        if request.url.host == "project.supabase.co":
            seen_storage_authorization.append(request.headers.get("authorization"))
            return httpx.Response(200, content=content)
        if request.url.path.endswith("/result"):
            return httpx.Response(200, json={"ok": True})
        if request.url.path.endswith("/complete"):
            return httpx.Response(200, json={"job": {"id": "job-p1", "status": "succeeded"}})
        raise AssertionError(request.url)

    observed_path = {}

    def runner(run_id: str) -> bool:
        run_dir = tmp_path / "labor_runs" / run_id
        metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        path = metadata["files"]["pdfInvoices"][0]["path"]
        observed_path["value"] = path
        assert Path(path).read_bytes() == content
        (run_dir / "report.html").write_text("done", encoding="utf-8")
        return True

    from pathlib import Path

    worker = PersonalLaborWorker(
        api_url="https://example.test",
        token="worker-secret",
        worker_version="0.3.0",
        data_root=tmp_path,
        runner=runner,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = worker.process_once()

    assert result["status"] == "succeeded"
    assert Path(observed_path["value"]).is_absolute()
    assert seen_storage_authorization == [None]


def test_personal_worker_rejects_same_size_tampered_private_input_before_runner(tmp_path):
    expected_content = b"a" * (1024 * 1024)
    tampered_content = b"b" + expected_content[1:]
    failed_payload = {}
    runner_calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/version"):
            return httpx.Response(404)
        if request.url.path.endswith("/claim"):
            return httpx.Response(
                200,
                json={"job": {"id": "job-tampered", "runId": "labor-tampered", "attempt": 1}},
            )
        if request.url.path.endswith("/input-manifest"):
            return httpx.Response(
                200,
                json={
                    "metadata": {
                        "id": "labor-tampered",
                        "files": {
                            "pdfInvoices": [
                                {"id": "file-1", "path": "inputs/file-1/invoice.pdf"}
                            ]
                        },
                    },
                    "files": [
                        {
                            "path": "inputs/file-1/invoice.pdf",
                            "size": len(expected_content),
                            "sha256": hashlib.sha256(expected_content).hexdigest(),
                            "signedUrl": "https://project.supabase.co/storage/v1/object/sign/private?token=short",
                        }
                    ],
                },
            )
        if request.url.host == "project.supabase.co":
            return httpx.Response(200, content=tampered_content)
        if request.url.path.endswith("/fail"):
            failed_payload.update(json.loads(request.content))
            return httpx.Response(200, json={"job": {"status": "failed"}})
        raise AssertionError(request.url)

    worker = PersonalLaborWorker(
        api_url="https://example.test",
        token="worker-secret",
        worker_version="0.3.0",
        data_root=tmp_path,
        runner=lambda run_id: runner_calls.append(run_id) or True,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = worker.process_once()

    assert result["status"] == "failed"
    assert "任务文件校验失败" in result["errorMessage"]
    assert failed_payload["retryable"] is False
    assert failed_payload["errorCode"] == "LABOR_WORKER_FAILED"
    assert runner_calls == []
    assert not (tmp_path / "labor_runs" / "labor-tampered" / "inputs" / "file-1" / "invoice.pdf").exists()


def test_personal_worker_runs_mapping_preflight_without_reconcile_engine_or_result_archive(tmp_path):
    workbook_buffer = BytesIO()
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "员工账单"
    sheet.append(["姓名", "工时", "金额"])
    sheet.append(["Alice", 8, 100])
    workbook.save(workbook_buffer)
    workbook_bytes = workbook_buffer.getvalue()
    fingerprint = "c" * 64
    submitted = {}
    calls = []
    progress_phases = []
    progress_timelines = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/version"):
            return httpx.Response(404)
        if request.url.path.endswith("/claim"):
            return httpx.Response(
                200,
                json={
                    "job": {
                        "id": "job-preflight",
                        "runId": "labor-preflight",
                        "jobType": "mapping_preflight",
                        "attempt": 1,
                    }
                },
            )
        if request.url.path.endswith("/input-manifest"):
            return httpx.Response(
                200,
                json={
                    "metadata": {
                        "id": "labor-preflight",
                        "mappingPreflight": {"inputFingerprint": fingerprint},
                        "files": {
                            "workbooks": [
                                {"id": "file-xlsx", "path": "inputs/file-xlsx/bill.xlsx"}
                            ]
                        },
                    },
                    "files": [
                        {
                            "path": "inputs/file-xlsx/bill.xlsx",
                            "size": len(workbook_bytes),
                            "sha256": hashlib.sha256(workbook_bytes).hexdigest(),
                            "signedUrl": "https://project.supabase.co/storage/v1/object/sign/private?token=short",
                        }
                    ],
                },
            )
        if request.url.host == "project.supabase.co":
            return httpx.Response(200, content=workbook_bytes)
        if request.url.path.endswith("/mapping-preflight-result"):
            submitted.update(json.loads(request.content))
            return httpx.Response(200, json={"ok": True})
        if request.url.path.endswith("/heartbeat"):
            progress = json.loads(request.content)["progress"]
            progress_phases.append(progress["phase"])
            progress_timelines.append(progress["timeline"])
            return httpx.Response(200, json={"job": {"id": "job-preflight", "status": "running"}})
        if request.url.path.endswith("/complete"):
            return httpx.Response(200, json={"job": {"id": "job-preflight", "status": "succeeded"}})
        raise AssertionError(request.url)

    worker = PersonalLaborWorker(
        api_url="https://example.test",
        token="worker-secret",
        worker_version="0.3.0",
        data_root=tmp_path,
        runner=lambda _: (_ for _ in ()).throw(AssertionError("预检不应运行正式核对引擎")),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = worker.process_once()

    assert result["status"] == "succeeded"
    assert submitted["inputFingerprint"] == fingerprint
    assert submitted["workbooks"][0]["fileId"] == "file-xlsx"
    suggestion = submitted["workbooks"][0]["sheets"][0]["suggestion"]
    assert suggestion["suggestedMapping"] == {
        "employeeId": "",
        "name": "姓名",
        "hours": "工时",
        "amount": "金额",
        "currency": "",
    }
    assert not any(path.endswith("/input-file") for _, path in calls)
    assert not any(path.endswith("/result") for _, path in calls)
    assert progress_phases == []
    assert progress_timelines == []
    assert not any(path.endswith("/heartbeat") for _, path in calls)


def test_personal_worker_reports_engine_failure(tmp_path):
    failed_payload = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/claim"):
            return httpx.Response(200, json={"job": {"id": "job-1", "runId": "labor-1", "attempt": 1}})
        if request.url.path.endswith("/input-manifest"):
            return httpx.Response(404)
        if request.url.path.endswith("/input"):
            return httpx.Response(200, content=_zip({"metadata.json": b"{}"}))
        if request.url.path.endswith("/fail"):
            failed_payload.update(json.loads(request.content))
            return httpx.Response(200, json={"job": {"status": "failed"}})
        if request.url.path.endswith("/version"):
            return httpx.Response(404)
        raise AssertionError(request.url)

    worker = PersonalLaborWorker(
        api_url="https://example.test",
        token="secret",
        worker_version="0.1.0",
        data_root=tmp_path,
        runner=lambda _: (_ for _ in ()).throw(RuntimeError("bad invoice")),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = worker.process_once()

    assert result["status"] == "failed"
    assert failed_payload["retryable"] is False
    assert failed_payload["errorCode"] == "LABOR_WORKER_FAILED"


def test_personal_worker_reports_server_503_as_retryable(tmp_path):
    failed_payload = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/fail"):
            failed_payload.update(json.loads(request.content))
            return httpx.Response(200, json={"job": {"status": "retry_wait"}})
        raise AssertionError(request.url)

    worker = PersonalLaborWorker(
        api_url="https://example.test",
        token="secret",
        worker_version="0.3.1",
        data_root=tmp_path,
        runner=lambda _: True,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    response = httpx.Response(
        503,
        request=httpx.Request("POST", "https://example.test/api/labor/worker/jobs/job-1/result"),
    )
    with pytest.raises(httpx.HTTPStatusError) as caught:
        response.raise_for_status()

    worker._report_failure("job-1", caught.value)

    assert failed_payload["retryable"] is True
    assert failed_payload["errorCode"] == "LABOR_WORKER_TRANSIENT"


def test_personal_worker_marks_task_lease_lost_on_heartbeat_conflict(tmp_path):
    waits = []

    class StopAfterHeartbeat:
        def wait(self, seconds):
            waits.append(seconds)
            return len(waits) > 1

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, request=request, json={"detail": "lease expired"})

    worker = PersonalLaborWorker(
        api_url="https://example.test",
        token="secret",
        worker_version="0.3.13",
        data_root=tmp_path,
        runner=lambda _: True,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    lease_lost = threading.Event()

    worker._heartbeat_loop("job-1", StopAfterHeartbeat(), {}, lease_lost)

    assert waits[0] == 20
    assert lease_lost.is_set() is True


def _zip(files: dict[str, bytes]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def test_default_runner_treats_none_as_success(monkeypatch):
    import bonus_platform.app as app_module

    monkeypatch.setattr(app_module, "_run_labor_extract_compare", lambda _: None)
    assert _default_runner("labor-1") is True


def test_personal_worker_writes_processing_then_idle_status_without_token(tmp_path):
    processing = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/claim"):
            return httpx.Response(200, json={"job": {"id": "job-status", "runId": "labor-status", "attempt": 1}})
        if request.url.path.endswith("/input-manifest"):
            return httpx.Response(200, json={"metadata": {"id": "labor-status"}, "files": []})
        if request.url.path.endswith("/events"):
            return httpx.Response(200, json={"ok": True})
        if request.url.path.endswith("/result"):
            return httpx.Response(200, json={"ok": True})
        if request.url.path.endswith("/complete"):
            return httpx.Response(200, json={"job": {"id": "job-status", "status": "succeeded"}})
        if request.url.path.endswith("/version"):
            return httpx.Response(404)
        raise AssertionError(request.url)

    def runner(_: str) -> bool:
        processing.update(json.loads((tmp_path / "worker-status.json").read_text(encoding="utf-8")))
        return True

    worker = PersonalLaborWorker(
        api_url="https://example.test",
        token="secret-token-that-must-never-leak",
        worker_version="0.3.0",
        data_root=tmp_path,
        runner=runner,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    worker.process_once()

    final = json.loads((tmp_path / "worker-status.json").read_text(encoding="utf-8"))
    assert processing["status"] == "processing"
    assert processing["jobId"] == "job-status"
    assert processing["runId"] == "labor-status"
    assert final["status"] == "idle"
    assert final["workerVersion"] == "0.3.0"
    assert "secret-token-that-must-never-leak" not in (tmp_path / "worker-status.json").read_text(encoding="utf-8")


def test_personal_worker_writes_idle_status_when_queue_is_empty(tmp_path):
    worker = PersonalLaborWorker(
        api_url="https://example.test",
        token="secret-token-that-must-never-leak",
        worker_version="0.3.0",
        data_root=tmp_path,
        runner=lambda _: True,
        client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"job": None}))),
    )

    assert worker.process_once() is None

    status = json.loads((tmp_path / "worker-status.json").read_text(encoding="utf-8"))
    assert status["status"] == "idle"
    assert status["jobId"] == ""
    assert status["runId"] == ""


def test_personal_worker_does_not_block_each_claim_with_repeated_update_checks(tmp_path):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/version"):
            return httpx.Response(404)
        if request.url.path.endswith("/claim"):
            return httpx.Response(200, json={"job": None})
        raise AssertionError(request.url)

    worker = PersonalLaborWorker(
        api_url="https://example.test",
        token="secret",
        worker_version="0.3.0",
        data_root=tmp_path,
        runner=lambda _: True,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert worker.process_once() is None
    assert worker.process_once() is None

    assert calls.count("/api/labor/worker/version") == 1
    assert calls.count("/api/labor/worker/jobs/claim") == 2


def test_personal_worker_marks_connected_after_first_successful_handshake(tmp_path):
    status_seen_before_claim = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/version"):
            return httpx.Response(200, json={"updateAvailable": False})
        if request.url.path.endswith("/claim"):
            status_seen_before_claim.update(
                json.loads((tmp_path / "worker-status.json").read_text(encoding="utf-8"))
            )
            return httpx.Response(200, json={"job": None})
        raise AssertionError(request.url)

    worker = PersonalLaborWorker(
        api_url="https://example.test",
        token="secret",
        worker_version="0.3.13",
        data_root=tmp_path,
        runner=lambda _: True,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    worker.process_once()

    assert status_seen_before_claim["status"] == "idle"
    assert "已连接" in status_seen_before_claim["message"]


def test_personal_worker_checks_required_version_before_claiming_work(tmp_path):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/version"):
            return httpx.Response(
                200,
                json={
                    "version": "0.3.0",
                    "minimumVersion": "0.3.0",
                    "requiredWorkerVersion": "0.3.0",
                    "updateAvailable": True,
                    "upgradeRequired": True,
                },
            )
        if request.url.path.endswith("/claim"):
            raise AssertionError("upgrade-required Worker must not claim work")
        raise AssertionError(request.url)

    worker = PersonalLaborWorker(
        api_url="https://example.test",
        token="secret",
        worker_version="0.2.9",
        data_root=tmp_path,
        runner=lambda _: True,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert worker.process_once() is None

    status = json.loads((tmp_path / "worker-status.json").read_text(encoding="utf-8"))
    assert calls == ["/api/labor/worker/version"]
    assert status["status"] == "upgrade_required"
    assert "0.3.0" in status["message"]


def test_personal_worker_distinguishes_unavailable_system_proxy(monkeypatch, tmp_path):
    class StopWorkerLoop(Exception):
        pass

    def unavailable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    worker = PersonalLaborWorker(
        api_url="https://example.test",
        token="secret-token-that-must-never-leak",
        worker_version="0.3.0",
        data_root=tmp_path,
        runner=lambda _: True,
        client=httpx.Client(transport=httpx.MockTransport(unavailable)),
    )
    monkeypatch.setenv("SIGMA_WORKER_PROXY_MODE", "system")
    monkeypatch.setattr("bonus_platform.worker.personal.time.sleep", lambda _: (_ for _ in ()).throw(StopWorkerLoop()))

    with pytest.raises(StopWorkerLoop):
        worker.run_forever(interval_seconds=1)

    status = json.loads((tmp_path / "worker-status.json").read_text(encoding="utf-8"))
    assert status["status"] == "proxy_unavailable"
    assert "secret-token-that-must-never-leak" not in (tmp_path / "worker-status.json").read_text(encoding="utf-8")


def test_personal_worker_requests_reactivation_when_token_has_expired(monkeypatch, tmp_path):
    class StopWorkerLoop(Exception):
        pass

    def expired(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, request=request, json={"detail": "expired"})

    worker = PersonalLaborWorker(
        api_url="https://example.test",
        token="expired-secret-token-that-must-never-leak",
        worker_version="0.3.0",
        data_root=tmp_path,
        runner=lambda _: True,
        client=httpx.Client(transport=httpx.MockTransport(expired)),
    )
    monkeypatch.setattr("bonus_platform.worker.personal.time.sleep", lambda _: (_ for _ in ()).throw(StopWorkerLoop()))

    with pytest.raises(StopWorkerLoop):
        worker.run_forever(interval_seconds=1)

    raw_status = (tmp_path / "worker-status.json").read_text(encoding="utf-8")
    status = json.loads(raw_status)
    assert status["status"] == "identity_expired"
    assert "重新激活" in status["message"]
    assert "expired-secret-token-that-must-never-leak" not in raw_status


def test_personal_worker_distinguishes_production_service_failure(monkeypatch, tmp_path):
    class StopWorkerLoop(Exception):
        pass

    def unavailable(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request, json={"detail": "unavailable"})

    worker = PersonalLaborWorker(
        api_url="https://example.test",
        token="secret",
        worker_version="0.3.0",
        data_root=tmp_path,
        runner=lambda _: True,
        client=httpx.Client(transport=httpx.MockTransport(unavailable)),
    )
    monkeypatch.setattr("bonus_platform.worker.personal.time.sleep", lambda _: (_ for _ in ()).throw(StopWorkerLoop()))

    with pytest.raises(StopWorkerLoop):
        worker.run_forever(interval_seconds=1)

    status = json.loads((tmp_path / "worker-status.json").read_text(encoding="utf-8"))
    assert status["status"] == "service_unavailable"


def test_worker_instance_lock_allows_only_one_process_per_data_root(tmp_path):
    with _WorkerInstanceLock(tmp_path):
        assert int((tmp_path / "worker.pid").read_text()) > 0
        with pytest.raises(WorkerAlreadyRunning):
            with _WorkerInstanceLock(tmp_path):
                pass

    assert not (tmp_path / "worker.pid").exists()


@pytest.mark.parametrize(("exit_code", "expected"), [(259, True), (0, False)])
def test_worker_pid_probe_uses_windows_process_status(monkeypatch, exit_code, expected):
    from bonus_platform.worker import personal

    calls = []

    class FakeKernel32:
        def OpenProcess(self, access, inherit_handle, pid):
            calls.append(("open", access, inherit_handle, pid))
            return 123

        def GetExitCodeProcess(self, handle, result):
            calls.append(("status", handle))
            result._obj.value = exit_code
            return True

        def CloseHandle(self, handle):
            calls.append(("close", handle))
            return True

    monkeypatch.setattr(personal.sys, "platform", "win32")
    monkeypatch.setattr(
        personal.os,
        "kill",
        lambda *_: pytest.fail("Windows PID probing must not call os.kill(pid, 0)"),
    )
    monkeypatch.setattr(ctypes, "WinDLL", lambda *_args, **_kwargs: FakeKernel32(), raising=False)

    assert _pid_is_alive(4321) is expected
    assert calls == [
        ("open", 0x1000, False, 4321),
        ("status", 123),
        ("close", 123),
    ]


def test_worker_instance_lock_reclaims_stale_pid(tmp_path):
    (tmp_path / "worker.pid").write_text("99999999", encoding="utf-8")

    with _WorkerInstanceLock(tmp_path):
        assert int((tmp_path / "worker.pid").read_text()) > 0
