from __future__ import annotations

import threading
from pathlib import Path

from bonus_platform.engine.labor import runs as labor_runs
from bonus_platform.engine.labor.lifecycle import delete_labor_run_directory


def _create_run(tmp_path: Path, monkeypatch, run_id: str) -> Path:
    runs_dir = tmp_path / "runs"
    monkeypatch.setattr(labor_runs, "LABOR_RUNS_DIR", runs_dir)
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True)
    labor_runs.save_labor_metadata(
        run_dir,
        {
            "id": run_id,
            "status": "已生成差异报告",
            "asyncTask": {"status": "completed"},
            "ownerUserId": "local-default",
        },
    )
    return run_dir


def test_delete_serializes_with_concurrent_metadata_update(monkeypatch, tmp_path: Path):
    run_id = "labor_delete_serialized"
    run_dir = _create_run(tmp_path, monkeypatch, run_id)
    delete_reached_persistent = threading.Event()
    release_delete = threading.Event()
    update_finished = threading.Event()
    delete_errors: list[BaseException] = []
    update_errors: list[BaseException] = []

    def blocking_persistent_delete(_run_id: str, _owner_user_id: str) -> None:
        delete_reached_persistent.set()
        if not release_delete.wait(timeout=2):
            raise TimeoutError("delete was not released")

    def delete_run() -> None:
        try:
            delete_labor_run_directory(
                run_dir,
                audit_path=tmp_path / "audit" / "labor.jsonl",
                reason_code="test_delete",
                delete_persistent=blocking_persistent_delete,
            )
        except BaseException as exc:  # pragma: no cover - surfaced below
            delete_errors.append(exc)

    def update_run() -> None:
        try:
            labor_runs.update_labor_metadata(
                run_id,
                {"status": "抽取中", "asyncTask": {"status": "running"}},
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            update_errors.append(exc)
        finally:
            update_finished.set()

    deleter = threading.Thread(target=delete_run, name="labor-deleter")
    updater = threading.Thread(target=update_run, name="labor-updater")
    deleter.start()
    assert delete_reached_persistent.wait(timeout=2)
    updater.start()
    update_was_serialized = not update_finished.wait(timeout=0.2)
    release_delete.set()
    deleter.join(timeout=2)
    updater.join(timeout=2)

    assert deleter.is_alive() is False
    assert updater.is_alive() is False
    assert delete_errors == []
    assert update_was_serialized is True
    assert len(update_errors) == 1
    assert isinstance(update_errors[0], FileNotFoundError)
    assert run_dir.exists() is False


def test_delete_waits_for_active_transition_then_refuses_removal(monkeypatch, tmp_path: Path):
    run_id = "labor_delete_active"
    run_dir = _create_run(tmp_path, monkeypatch, run_id)
    delete_finished = threading.Event()
    delete_errors: list[BaseException] = []

    def delete_run() -> None:
        try:
            delete_labor_run_directory(
                run_dir,
                audit_path=tmp_path / "audit" / "labor.jsonl",
                reason_code="test_delete",
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            delete_errors.append(exc)
        finally:
            delete_finished.set()

    with labor_runs.labor_run_metadata_lock(run_id):
        labor_runs.update_labor_metadata(
            run_id,
            {"status": "抽取中", "asyncTask": {"status": "running"}},
        )
        deleter = threading.Thread(target=delete_run, name="labor-active-deleter")
        deleter.start()
        delete_was_serialized = not delete_finished.wait(timeout=0.2)

    deleter.join(timeout=2)

    assert deleter.is_alive() is False
    assert delete_was_serialized is True
    assert [str(error) for error in delete_errors] == ["ACTIVE_RUN"]
    assert run_dir.exists() is True


def test_list_metadata_tolerates_run_deleted_between_glob_and_read(monkeypatch, tmp_path: Path):
    run_dir = _create_run(tmp_path, monkeypatch, "labor_list_delete_race")
    metadata_path = run_dir / labor_runs.METADATA_FILE
    original_read_text = Path.read_text

    def disappearing_read(path: Path, *args, **kwargs) -> str:
        if path == metadata_path:
            metadata_path.unlink(missing_ok=True)
            raise FileNotFoundError(metadata_path)
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", disappearing_read)

    assert labor_runs.list_labor_metadata() == []
