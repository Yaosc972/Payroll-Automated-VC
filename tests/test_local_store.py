from __future__ import annotations

import importlib
import sqlite3

from bonus_platform import config
from bonus_platform.engine.local_store import init_store, list_indexed_runs, upsert_run_metadata


def test_resolve_data_root_uses_sigma_workbench_home(monkeypatch, tmp_path):
    monkeypatch.setenv("SIGMA_WORKBENCH_HOME", str(tmp_path))
    reloaded = importlib.reload(config)

    try:
        assert reloaded.OUTPUT_DIR == tmp_path
        assert reloaded.DATABASE_PATH == tmp_path / "sigma_workbench.db"
    finally:
        monkeypatch.delenv("SIGMA_WORKBENCH_HOME", raising=False)
        importlib.reload(config)


def test_upsert_run_metadata_writes_sqlite_index(tmp_path):
    db_path = tmp_path / "sigma_workbench.db"
    metadata = {
        "id": "202510_test_run",
        "month": 202510,
        "status": "已初算",
        "sourceFilename": "monthly.xlsx",
        "recruitmentTotal": 123.45,
        "referralTotal": 67.89,
        "exceptionCount": 2,
        "pendingCount": 1,
        "pendingTotal": 30,
        "createdAt": "2026-05-25T10:00:00",
        "updatedAt": "2026-05-25T10:01:00",
    }

    upsert_run_metadata(metadata, db_path)

    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT id, month, status, recruitment_total, pending_count FROM runs WHERE id = ?",
            ("202510_test_run",),
        ).fetchone()
    assert row == ("202510_test_run", 202510, "已初算", 123.45, 1)
    assert list_indexed_runs(db_path)[0]["id"] == "202510_test_run"


def test_init_store_is_idempotent(tmp_path):
    db_path = tmp_path / "nested" / "sigma_workbench.db"

    first = init_store(db_path)
    second = init_store(db_path)

    assert first == db_path
    assert second == db_path
    assert db_path.exists()


def test_ensure_data_files_copies_rule_and_template_from_seed(monkeypatch, tmp_path):
    data_root = tmp_path / "data"
    seed_root = tmp_path / "seed"
    seed_root.mkdir()
    for filename in ("招聘奖金核算_规则库.xlsx", "招聘奖金核算_月度导入模板.xlsx"):
        (seed_root / filename).write_bytes(b"seed")
    monkeypatch.setenv("SIGMA_WORKBENCH_HOME", str(data_root))
    monkeypatch.setenv("SIGMA_WORKBENCH_SEED_DIR", str(seed_root))
    reloaded = importlib.reload(config)

    try:
        reloaded.ensure_data_files()

        assert (data_root / "招聘奖金核算_规则库.xlsx").read_bytes() == b"seed"
        assert (data_root / "招聘奖金核算_月度导入模板.xlsx").read_bytes() == b"seed"
    finally:
        monkeypatch.delenv("SIGMA_WORKBENCH_HOME", raising=False)
        monkeypatch.delenv("SIGMA_WORKBENCH_SEED_DIR", raising=False)
        importlib.reload(config)
