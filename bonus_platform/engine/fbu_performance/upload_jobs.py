from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import threading
from typing import Any
import uuid


FBU_UPLOAD_JOB_STALL_SECONDS = 300
_JOB_ID_RE = re.compile(r"^[0-9a-f]{24}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class FBUUploadJobStore:
    """Small durable state records for direct-upload parsing jobs."""

    def __init__(self, data_dir: str | Path, run_manager: Any):
        self.data_dir = Path(data_dir)
        self.run_manager = run_manager
        self._lock = threading.RLock()

    @staticmethod
    def validate_job_id(job_id: str) -> str:
        value = str(job_id or "").strip()
        if not _JOB_ID_RE.fullmatch(value):
            raise ValueError("上传任务编号无效")
        return value

    def relative_path(self, job_id: str) -> str:
        return f"jobs/{self.validate_job_id(job_id)}.json"

    def path(self, run_id: str, job_id: str) -> Path:
        return self.data_dir / str(run_id) / self.relative_path(job_id)

    def create(
        self,
        run_id: str,
        uploads: list[dict[str, Any]],
        *,
        job_id: str | None = None,
    ) -> dict[str, Any]:
        job_id = self.validate_job_id(job_id or uuid.uuid4().hex[:24])
        timestamp = _now()
        payload = {
            "jobId": job_id,
            "runId": str(run_id),
            "status": "uploading",
            "stage": "uploading",
            "progress": 0,
            "message": "等待文件上传",
            "attempt": 0,
            "createdAt": timestamp,
            "updatedAt": timestamp,
            "uploads": uploads,
            "result": {},
            "error": "",
        }
        self.save(run_id, payload)
        return payload

    def load(self, run_id: str, job_id: str) -> dict[str, Any] | None:
        relative_path = self.relative_path(job_id)
        path = self.path(run_id, job_id)
        if not path.is_file():
            path = self.run_manager.materialize_file(run_id, relative_path) or path
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if (
            not isinstance(payload, dict)
            or payload.get("runId") != run_id
            or payload.get("jobId") != job_id
        ):
            return None
        return payload

    def save(self, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        job_id = self.validate_job_id(str(payload.get("jobId") or ""))
        if str(payload.get("runId") or "") != str(run_id):
            raise ValueError("上传任务与当前活动不匹配")
        path = self.path(run_id, job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        with self._lock:
            try:
                temporary.write_text(
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8",
                )
                with temporary.open("rb") as handle:
                    os.fsync(handle.fileno())
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
            self.run_manager.persist_files(run_id, [self.relative_path(job_id)])
        return payload

    def update(self, run_id: str, job_id: str, **changes: Any) -> dict[str, Any]:
        with self._lock:
            payload = self.load(run_id, job_id)
            if payload is None:
                raise FileNotFoundError(job_id)
            payload.update(changes)
            payload["updatedAt"] = _now()
            return self.save(run_id, payload)

    def public(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = dict(payload)
        status = str(result.get("status") or "")
        updated_at = _parse_timestamp(result.get("updatedAt"))
        age_seconds = (
            (datetime.now(timezone.utc) - updated_at).total_seconds()
            if updated_at
            else 0
        )
        recoverable = status in {"queued", "processing"} and age_seconds >= FBU_UPLOAD_JOB_STALL_SECONDS
        result["recoverable"] = recoverable
        result["canRetry"] = status == "failed" or recoverable
        if recoverable:
            result["message"] = "处理任务已中断，可点击重试继续。"
        return result
