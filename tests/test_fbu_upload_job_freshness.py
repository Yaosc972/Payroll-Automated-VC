from __future__ import annotations

import json
from pathlib import Path

from bonus_platform.engine.fbu_performance.upload_jobs import FBUUploadJobStore


class _PersistentRunManager:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.remote_files: dict[tuple[str, str], bytes] = {}
        self.fresh_reads: list[tuple[str, str]] = []

    def persist_files(self, run_id: str, relative_paths: list[str]) -> None:
        for relative_path in relative_paths:
            path = self.data_dir / run_id / relative_path
            self.remote_files[(run_id, relative_path)] = path.read_bytes()

    def materialize_file(
        self,
        run_id: str,
        relative_path: str,
    ) -> Path | None:
        target = self.data_dir / run_id / relative_path
        if target.is_file():
            return target
        content = self.remote_files.get((run_id, relative_path))
        if content is None:
            return None
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return target

    def read_persisted_file(self, run_id: str, relative_path: str) -> bytes | None:
        self.fresh_reads.append((run_id, relative_path))
        return self.remote_files.get((run_id, relative_path))


def test_upload_job_load_can_refresh_stale_local_state(tmp_path):
    run_id = "run-refresh"
    manager = _PersistentRunManager(tmp_path)
    store = FBUUploadJobStore(tmp_path, manager)
    created = store.create(run_id, [], job_id="a" * 24)
    relative_path = store.relative_path(created["jobId"])

    completed = {
        **created,
        "status": "completed",
        "stage": "completed",
        "progress": 100,
        "message": "上传并解析完成",
    }
    manager.remote_files[(run_id, relative_path)] = json.dumps(
        completed,
        ensure_ascii=False,
    ).encode("utf-8")

    assert store.load(run_id, created["jobId"])["status"] == "uploading"

    refreshed = store.load(run_id, created["jobId"], refresh=True)

    assert refreshed["status"] == "completed"
    assert manager.fresh_reads == [(run_id, relative_path)]
