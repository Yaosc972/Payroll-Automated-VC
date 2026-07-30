from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import errno
import hashlib
import json
import logging
import os
import platform
import shlex
import shutil
import sys
import threading
import time
import zipfile
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from urllib.parse import urlparse

import httpx


def _worker_platform() -> str:
    machine = platform.machine().strip().lower()
    if sys.platform == "win32":
        return "windows-x64"
    if sys.platform == "darwin" and machine in {"arm64", "aarch64"}:
        return "macos-arm64"
    return f"{sys.platform}-{machine or 'unknown'}"


class WorkerAlreadyRunning(RuntimeError):
    pass


class LaborWorkerLeaseLost(RuntimeError):
    pass


class _FailoverHttpClient:
    """Use direct networking only when the configured proxy cannot connect."""

    _SAFE_FALLBACK_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.ProxyError)

    def __init__(self, primary: httpx.Client, direct: httpx.Client) -> None:
        self.primary = primary
        self.direct = direct

    def request(self, method: str, url: str, **kwargs):
        try:
            return self.primary.request(method, url, **kwargs)
        except self._SAFE_FALLBACK_ERRORS:
            return self.direct.request(method, url, **kwargs)

    def get(self, url: str, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs):
        return self.request("POST", url, **kwargs)

    @contextmanager
    def stream(self, method: str, url: str, **kwargs):
        stream_context = self.primary.stream(method, url, **kwargs)
        try:
            response = stream_context.__enter__()
        except self._SAFE_FALLBACK_ERRORS:
            stream_context = self.direct.stream(method, url, **kwargs)
            response = stream_context.__enter__()
        try:
            yield response
        except BaseException:
            if not stream_context.__exit__(*sys.exc_info()):
                raise
        else:
            stream_context.__exit__(None, None, None)

    def close(self) -> None:
        self.primary.close()
        self.direct.close()


def _default_worker_http_client():
    timeout = httpx.Timeout(30.0, connect=3.0)
    if os.environ.get("SIGMA_WORKER_PROXY_MODE") == "system":
        return _FailoverHttpClient(
            httpx.Client(timeout=timeout, trust_env=True),
            httpx.Client(timeout=timeout, trust_env=False),
        )
    return httpx.Client(timeout=timeout, trust_env=False)


class _WorkerInstanceLock:
    def __init__(self, data_root: Path) -> None:
        self.path = Path(data_root) / "worker.pid"
        self.pid = os.getpid()

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except OSError as exc:
                if exc.errno != errno.EEXIST:
                    raise
                existing = _read_pid(self.path)
                if existing and _pid_is_alive(existing):
                    raise WorkerAlreadyRunning(f"Worker 已在运行，PID={existing}。") from exc
                self.path.unlink(missing_ok=True)
                continue
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(str(self.pid))
                handle.flush()
                os.fsync(handle.fileno())
            return self
        raise WorkerAlreadyRunning("无法取得 Worker 单实例锁。")

    def __exit__(self, *_):
        if _read_pid(self.path) == self.pid:
            self.path.unlink(missing_ok=True)
        return False


def _read_pid(path: Path) -> int | None:
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return pid if pid > 0 else None


def _pid_is_alive(pid: int) -> bool:
    if sys.platform == "win32":
        return _windows_pid_is_alive(pid)
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _windows_pid_is_alive(pid: int) -> bool:
    import ctypes

    process_query_limited_information = 0x1000
    still_active = 259
    error_invalid_parameter = 87
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(process_query_limited_information, False, int(pid))
    if not handle:
        return ctypes.get_last_error() != error_invalid_parameter
    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return True
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


class PersonalLaborWorker:
    def __init__(
        self,
        *,
        api_url: str,
        token: str,
        worker_version: str,
        data_root: Path,
        runner: Callable[[str], bool],
        client: httpx.Client | None = None,
    ) -> None:
        self.api_url = api_url.rstrip("/")
        self.token = token
        self.worker_version = worker_version
        self.data_root = Path(data_root)
        self.runner = runner
        self.client = client or _default_worker_http_client()
        self.logger = _worker_logger(self.data_root / "logs" / "worker.log")
        self._required_version_checked = False
        self._next_idle_update_check_at = time.monotonic() + 300.0
        self._ever_connected = False
        self._write_status("connecting", "正在连接核对服务。")

    @property
    def headers(self) -> dict[str, str]:
        return {"authorization": f"Bearer {self.token}", "x-worker-version": self.worker_version}

    def process_once(self) -> dict[str, Any] | None:
        if not self._ever_connected:
            self._write_status("connecting", "正在连接核对服务。")
        if not self._required_version_checked:
            version_status = self.check_update()
            self._required_version_checked = True
            if version_status is not None:
                self._ever_connected = True
                self._write_status("idle", "核对助手已连接，正在检查待处理任务。")
            if version_status and version_status.get("upgradeRequired"):
                required = str(
                    version_status.get("requiredWorkerVersion")
                    or version_status.get("minimumVersion")
                    or "最新版本"
                )
                self._write_status("upgrade_required", f"当前版本不再兼容，请先升级到 {required} 或更高版本。")
                return None
        response = self.client.post(f"{self.api_url}/api/labor/worker/jobs/claim", headers=self.headers)
        response.raise_for_status()
        self._ever_connected = True
        job = response.json().get("job")
        if not job:
            version_status = self._check_idle_update_if_due()
            if version_status and version_status.get("upgradeRequired"):
                required = str(
                    version_status.get("requiredWorkerVersion")
                    or version_status.get("minimumVersion")
                    or "最新版本"
                )
                self._write_status("upgrade_required", f"当前版本不再兼容，请先升级到 {required} 或更高版本。")
                return None
            self._write_status("idle", "核对助手在线，暂无待处理任务。")
            return None
        job_id = str(job["id"])
        run_id = str(job["runId"])
        stop = threading.Event()
        lease_lost = threading.Event()
        progress_state = {
            "status": "running",
            "phase": "claimed",
            "message": "Worker 已领取任务。",
        }
        heartbeat = threading.Thread(
            target=self._heartbeat_loop,
            args=(job_id, stop, progress_state, lease_lost),
            daemon=True,
        )
        heartbeat.start()
        try:
            self._write_status("processing", "正在处理本人核对任务。", job=job)
            self.logger.info("claimed job=%s run=%s attempt=%s", job_id, run_id, job.get("attempt"))
            is_mapping_preflight = str(job.get("jobType") or "reconcile") == "mapping_preflight"
            if is_mapping_preflight:
                self._update_progress_state(progress_state, phase="claimed", message="Worker 已领取任务。")
                self._write_status("processing", "正在下载 Excel 工作表。", job=job)
                self._update_progress_state(
                    progress_state,
                    phase="downloading_excel",
                    message="正在下载 Excel。",
                )
            self._download_input(job_id, run_id)
            if is_mapping_preflight:
                self._write_status("processing", "正在读取 Excel 工作表和字段。", job=job)
                self._update_progress_state(
                    progress_state,
                    phase="reading_workbook",
                    message="正在读取工作表。",
                )
                self._assert_worker_lease(lease_lost)
                self._upload_mapping_preflight_result(job_id, run_id, progress_state=progress_state)
            else:
                metrics_path = self.data_root / "worker-temp" / f"{job_id}-metrics.jsonl"
                metrics_path.parent.mkdir(parents=True, exist_ok=True)
                metrics_path.unlink(missing_ok=True)
                previous_metrics_path = os.environ.get("LABOR_RUNTIME_METRICS_PATH")
                os.environ["LABOR_RUNTIME_METRICS_PATH"] = str(metrics_path)
                try:
                    if self.runner(run_id) is False:
                        raise RuntimeError("本地核对引擎返回失败状态。")
                finally:
                    if previous_metrics_path is None:
                        os.environ.pop("LABOR_RUNTIME_METRICS_PATH", None)
                    else:
                        os.environ["LABOR_RUNTIME_METRICS_PATH"] = previous_metrics_path
                self._assert_worker_lease(lease_lost)
                self._upload_runtime_metrics(job_id, metrics_path)
                self._upload_result(job_id, run_id)
            self._assert_worker_lease(lease_lost)
            completed = self.client.post(f"{self.api_url}/api/labor/worker/jobs/{job_id}/complete", headers=self.headers)
            completed.raise_for_status()
            self.logger.info("completed job=%s run=%s", job_id, run_id)
            self._write_status("idle", "任务已完成，核对助手继续等待。")
            return completed.json().get("job")
        except LaborWorkerLeaseLost:
            self.logger.warning("worker lease lost job=%s run=%s", job_id, run_id)
            self._write_status("recovering", "任务连接已经失效，结果未提交；正在安全恢复。", job=job)
            return {**job, "status": "lease_lost"}
        except Exception as exc:  # noqa: BLE001 - report stable failure to the queue.
            self.logger.exception("failed job=%s run=%s", job_id, run_id)
            self._report_failure(job_id, exc)
            self._write_status("failed", "任务处理失败，等待安全重试。", job=job)
            return {**job, "status": "failed", "errorMessage": str(exc)}
        finally:
            stop.set()
            heartbeat.join(timeout=2)
            self.check_update(suppress_errors=True)
            self._next_idle_update_check_at = time.monotonic() + 300.0

    def _upload_runtime_metrics(self, job_id: str, metrics_path: Path) -> None:
        if not metrics_path.exists():
            return
        events = []
        for line in metrics_path.read_text(encoding="utf-8").splitlines()[-1000:]:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
        try:
            response = self.client.post(
                f"{self.api_url}/api/labor/worker/jobs/{job_id}/events",
                headers=self.headers,
                json={"events": events},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            self.logger.warning("runtime metrics upload failed job=%s: %s", job_id, exc)
        finally:
            metrics_path.unlink(missing_ok=True)

    def run_forever(self, *, interval_seconds: float = 2.0) -> None:
        delay = max(1.0, interval_seconds)
        while True:
            cycle_started_at = time.monotonic()
            try:
                result = self.process_once()
                if result is None:
                    time.sleep(max(0.0, delay - (time.monotonic() - cycle_started_at)))
                else:
                    time.sleep(0.5)
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code if exc.response is not None else 0
                self.logger.warning("worker API rejected request status=%s", status_code)
                if status_code in {401, 403}:
                    self._write_status("identity_expired", "核对助手身份已失效，请从海外劳务报账页面重新激活。")
                elif status_code == 426:
                    self._write_status("upgrade_required", "当前版本不再兼容，请先升级核对助手。")
                elif status_code >= 500:
                    self._write_status("service_unavailable", "生产核对服务暂时不可用，正在自动恢复连接。")
                else:
                    self._write_status("recovering", "核对服务拒绝了连接，正在自动恢复。")
                time.sleep(min(delay * 2, 60.0))
            except httpx.RequestError as exc:
                self.logger.warning("worker API unavailable: %s", exc)
                if os.environ.get("SIGMA_WORKER_PROXY_MODE") == "system":
                    self._write_status("proxy_unavailable", "系统代理当前不可用，请检查代理软件；助手会自动重试。")
                else:
                    self._write_status("network_offline", "网络当前不可用，核对助手正在自动重连。")
                time.sleep(min(delay * 2, 60.0))

    def _write_status(self, status: str, message: str, *, job: dict[str, Any] | None = None) -> None:
        payload = {
            "status": str(status),
            "message": str(message)[:240],
            "jobId": str((job or {}).get("id") or ""),
            "runId": str((job or {}).get("runId") or ""),
            "updatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "workerVersion": self.worker_version,
        }
        destination = self.data_root / "worker-status.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, destination)

    def check_update(self, *, suppress_errors: bool = False) -> dict[str, Any] | None:
        try:
            response = self.client.get(
                f"{self.api_url}/api/labor/worker/version",
                headers=self.headers,
                params={"currentVersion": self.worker_version, "platform": _worker_platform()},
                timeout=2.0,
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            manifest = response.json()
            if manifest.get("updateAvailable"):
                pending = self.data_root / "worker-update.json"
                pending.parent.mkdir(parents=True, exist_ok=True)
                pending.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
                self.logger.info("worker update available version=%s", manifest.get("version"))
            return manifest
        except httpx.HTTPError as exc:
            self.logger.warning("update check failed: %s", exc)
            if suppress_errors:
                return None
            raise

    def _check_idle_update_if_due(self) -> dict[str, Any] | None:
        if time.monotonic() < self._next_idle_update_check_at:
            return None
        self._next_idle_update_check_at = time.monotonic() + 300.0
        return self.check_update()

    def _download_input(self, job_id: str, run_id: str) -> None:
        run_dir = self.data_root / "labor_runs" / run_id
        if run_dir.exists():
            shutil.rmtree(run_dir)
        run_dir.mkdir(parents=True)
        manifest_response = self.client.get(
            f"{self.api_url}/api/labor/worker/jobs/{job_id}/input-manifest", headers=self.headers
        )
        if manifest_response.status_code == 404:
            response = self.client.get(f"{self.api_url}/api/labor/worker/jobs/{job_id}/input", headers=self.headers)
            response.raise_for_status()
            _extract_safe_zip(response.content, run_dir)
            return
        manifest_response.raise_for_status()
        manifest = manifest_response.json()
        metadata = manifest.get("metadata") if isinstance(manifest.get("metadata"), dict) else {}
        entries = list(manifest.get("files") or [])

        def download_entry(entry: dict[str, Any]) -> None:
            relative = _safe_manifest_path(str(entry.get("path") or ""))
            destination = run_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            size = 0
            signed_url = str(entry.get("signedUrl") or "").strip()
            if signed_url:
                parsed = urlparse(signed_url)
                if parsed.scheme != "https" and not (
                    parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}
                ):
                    raise ValueError("任务清单包含不安全的私有存储下载地址。")
                download_url = signed_url
                download_headers = {}
                download_params = None
            else:
                download_url = f"{self.api_url}/api/labor/worker/jobs/{job_id}/input-file"
                download_headers = self.headers
                download_params = {"relativePath": relative.as_posix()}
            with self.client.stream(
                "GET",
                download_url,
                headers=download_headers,
                params=download_params,
            ) as response:
                response.raise_for_status()
                with destination.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        handle.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
            if size != int(entry.get("size") or -1) or digest.hexdigest() != str(entry.get("sha256") or ""):
                destination.unlink(missing_ok=True)
                raise ValueError(f"任务文件校验失败: {relative.as_posix()}")

        if entries:
            with ThreadPoolExecutor(max_workers=min(4, len(entries))) as executor:
                list(executor.map(download_entry, entries))
        _materialize_worker_metadata_paths(metadata, run_dir)
        (run_dir / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _upload_result(self, job_id: str, run_id: str) -> None:
        run_dir = self.data_root / "labor_runs" / run_id
        archive = self.data_root / "worker-temp" / f"{job_id}-result.zip"
        archive.parent.mkdir(parents=True, exist_ok=True)
        try:
            _write_run_archive(run_dir, archive)
            with archive.open("rb") as handle:
                response = self.client.post(
                    f"{self.api_url}/api/labor/worker/jobs/{job_id}/result",
                    headers=self.headers,
                    files={"result_archive": (archive.name, handle, "application/zip")},
                )
            response.raise_for_status()
        finally:
            archive.unlink(missing_ok=True)

    def _upload_mapping_preflight_result(
        self,
        job_id: str,
        run_id: str,
        *,
        progress_state: dict[str, Any],
    ) -> None:
        run_dir = self.data_root / "labor_runs" / run_id
        payload = _build_mapping_preflight_payload(run_dir)
        self._update_progress_state(
            progress_state,
            phase="uploading_result",
            message="正在回传结果。",
        )
        response = self.client.post(
            f"{self.api_url}/api/labor/worker/jobs/{job_id}/mapping-preflight-result",
            headers=self.headers,
            json=payload,
        )
        response.raise_for_status()

    @staticmethod
    def _assert_worker_lease(lease_lost: threading.Event) -> None:
        if lease_lost.is_set():
            raise LaborWorkerLeaseLost("Worker 任务租约已经失效。")

    @staticmethod
    def _update_progress_state(
        progress_state: dict[str, Any],
        *,
        phase: str,
        message: str,
    ) -> None:
        normalized_phase = str(phase)
        timeline = progress_state.setdefault("timeline", {})
        timeline.setdefault(
            normalized_phase,
            datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        )
        progress_state.update(
            {
                "status": "running",
                "phase": normalized_phase,
                "message": str(message)[:160],
            }
        )

    def _heartbeat_loop(
        self,
        job_id: str,
        stop: threading.Event,
        progress_state: dict[str, Any],
        lease_lost: threading.Event,
    ) -> None:
        interval_seconds = 20
        while not stop.wait(interval_seconds):
            try:
                disk = shutil.disk_usage(self.data_root)
                progress = {
                    **progress_state,
                    "storage": {
                        "freeBytes": disk.free,
                        "totalBytes": disk.total,
                        "minimumFreeBytes": int(os.environ.get("LABOR_WORKER_MINIMUM_FREE_BYTES", 5 * 1024**3)),
                    },
                }
                response = self.client.post(
                    f"{self.api_url}/api/labor/worker/jobs/{job_id}/heartbeat",
                    headers=self.headers,
                    json={"progress": progress},
                )
                response.raise_for_status()
                interval_seconds = 20
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code if exc.response is not None else 0
                if status_code in {401, 403, 409, 426}:
                    lease_lost.set()
                    self.logger.warning("heartbeat rejected and lease lost job=%s status=%s", job_id, status_code)
                    return
                interval_seconds = 5
                self.logger.warning("heartbeat service failure job=%s status=%s", job_id, status_code)
            except httpx.HTTPError as exc:
                interval_seconds = 5
                self.logger.warning("heartbeat failed job=%s: %s", job_id, exc)

    def _report_failure(self, job_id: str, exc: Exception) -> None:
        retryable = (
            isinstance(exc, (httpx.TimeoutException, httpx.NetworkError))
            or (
                isinstance(exc, httpx.HTTPStatusError)
                and 500 <= exc.response.status_code < 600
            )
            or any(
                marker in str(exc).lower() for marker in ("timeout", "connection", "temporar", "超时", "连接")
            )
        )
        try:
            self.client.post(
                f"{self.api_url}/api/labor/worker/jobs/{job_id}/fail",
                headers=self.headers,
                json={
                    "errorCode": "LABOR_WORKER_TRANSIENT" if retryable else "LABOR_WORKER_FAILED",
                    "errorMessage": str(exc)[:500],
                    "retryable": retryable,
                },
            ).raise_for_status()
        except httpx.HTTPError as report_exc:
            self.logger.error("could not report failure job=%s: %s", job_id, report_exc)


def _extract_safe_zip(payload: bytes, destination: Path) -> None:
    from io import BytesIO

    with zipfile.ZipFile(BytesIO(payload)) as archive:
        for entry in archive.infolist():
            pure = PurePosixPath(entry.filename.replace("\\", "/"))
            if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
                raise ValueError("任务包包含非法路径。")
            target = destination.joinpath(*pure.parts)
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(entry))


def _write_run_archive(run_dir: Path, destination: Path) -> None:
    protected = set()
    try:
        metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        metadata = {}
    files = metadata.get("files") if isinstance(metadata.get("files"), dict) else {}
    for key in ("pdfInvoices", "workbooks"):
        records = files.get(key) if isinstance(files.get(key), list) else []
        for record in records:
            if not isinstance(record, dict):
                continue
            raw = str(record.get("path") or record.get("filename") or "")
            path = Path(raw)
            try:
                protected.add(path.resolve().relative_to(run_dir.resolve()).as_posix())
            except ValueError:
                protected.add(path.name)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(run_dir.rglob("*")):
            relative = path.relative_to(run_dir).as_posix()
            if path.is_file() and not path.name.endswith(".tmp") and relative not in protected:
                archive.write(path, relative)


def _safe_manifest_path(name: str) -> Path:
    pure = PurePosixPath(name.replace("\\", "/"))
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError("任务清单包含非法文件路径。")
    return Path(*pure.parts)


def _materialize_worker_metadata_paths(metadata: dict[str, Any], run_dir: Path) -> None:
    files = metadata.get("files") if isinstance(metadata.get("files"), dict) else {}
    for key in ("pdfInvoices", "workbooks"):
        records = files.get(key) if isinstance(files.get(key), list) else []
        for record in records:
            if not isinstance(record, dict) or not record.get("path"):
                continue
            relative = _safe_manifest_path(str(record["path"]))
            record["path"] = str((run_dir / relative).resolve())
    workbooks = files.get("workbooks") if isinstance(files.get("workbooks"), list) else []
    if workbooks:
        files["workbook"] = workbooks[0]


def _build_mapping_preflight_payload(run_dir: Path) -> dict[str, Any]:
    from bonus_platform.engine.labor.workbook import list_workbook_sheets, suggest_mapping

    metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    preflight = metadata.get("mappingPreflight") if isinstance(metadata.get("mappingPreflight"), dict) else {}
    input_fingerprint = str(preflight.get("inputFingerprint") or "").strip().lower()
    if len(input_fingerprint) != 64 or any(character not in "0123456789abcdef" for character in input_fingerprint):
        raise ValueError("字段预检任务缺少有效的输入指纹。")
    files = metadata.get("files") if isinstance(metadata.get("files"), dict) else {}
    records = files.get("workbooks") if isinstance(files.get("workbooks"), list) else []
    if not records or len(records) > 20:
        raise ValueError("字段预检任务的 Excel 文件清单为空或超过限制。")
    workbooks = []
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("字段预检任务包含无效 Excel 文件记录。")
        file_id = str(record.get("id") or "").strip()
        path = Path(str(record.get("path") or ""))
        if not file_id or not path.is_file():
            raise ValueError("字段预检任务的 Excel 文件尚未完整下载。")
        sheet_names = list_workbook_sheets(path)
        if not sheet_names or len(sheet_names) > 100:
            raise ValueError(f"Excel 工作表为空或超过限制：{path.name}")
        workbooks.append(
            {
                "fileId": file_id,
                "sheets": [
                    {"name": str(sheet_name), "suggestion": suggest_mapping(path, str(sheet_name))}
                    for sheet_name in sheet_names
                ],
            }
        )
    return {"inputFingerprint": input_fingerprint, "workbooks": workbooks}


def _worker_logger(path: Path) -> logging.Logger:
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"sigma.labor.worker.{path}")
    if not logger.handlers:
        handler = RotatingFileHandler(path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


def _default_runner(run_id: str) -> bool:
    from bonus_platform.app import _run_labor_extract_compare

    return _run_labor_extract_compare(run_id) is not False


def _read_worker_token(token: str, *, token_stdin: bool, stdin: Any) -> str:
    if token_stdin:
        return str(stdin.readline() or "").strip()
    return str(token or "").strip()


def _configure_default_ocr_command() -> None:
    if str(os.environ.get("AI_OCR_COMMAND") or "").strip():
        return
    if getattr(sys, "frozen", False):
        argv = [sys.executable, "--ocr-task"]
    else:
        argv = [sys.executable, "-m", "tools.labor_ocr_worker_task"]
    os.environ["AI_OCR_COMMAND"] = shlex.join(argv)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sigma personal overseas labor worker")
    parser.add_argument("--api-url", default=os.environ.get("SIGMA_LABOR_WORKER_API_URL", ""))
    parser.add_argument("--token-stdin", action="store_true")
    parser.add_argument("--version", default=os.environ.get("SIGMA_LABOR_WORKER_VERSION", "0.1.0"))
    parser.add_argument("--data-root", default=os.environ.get("SIGMA_WORKBENCH_HOME", ""))
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    token = _read_worker_token(
        os.environ.get("SIGMA_LABOR_WORKER_TOKEN", ""),
        token_stdin=args.token_stdin,
        stdin=sys.stdin,
    )
    if not args.api_url or not token or not args.data_root:
        parser.error("api-url, token and data-root are required")
    _configure_default_ocr_command()
    data_root = Path(args.data_root)
    try:
        with _WorkerInstanceLock(data_root):
            worker = PersonalLaborWorker(
                api_url=args.api_url,
                token=token,
                worker_version=args.version,
                data_root=data_root,
                runner=_default_runner,
            )
            if args.once:
                worker.process_once()
            else:
                worker.run_forever()
    except WorkerAlreadyRunning:
        return


if __name__ == "__main__":
    main()
