from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .. import config


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  month INTEGER NOT NULL,
  status TEXT NOT NULL,
  source_filename TEXT,
  recruitment_total REAL DEFAULT 0,
  referral_total REAL DEFAULT 0,
  exception_count INTEGER DEFAULT 0,
  pending_count INTEGER DEFAULT 0,
  pending_total REAL DEFAULT 0,
  metadata_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""


def init_store(db_path: Path | None = None) -> Path:
    path = db_path or config.DATABASE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(SCHEMA)
        connection.commit()
    return path


def upsert_run_metadata(metadata: dict[str, Any], db_path: Path | None = None) -> None:
    if not metadata.get("id"):
        return
    path = init_store(db_path)
    payload = json.dumps(metadata, ensure_ascii=False)
    values = {
        "id": str(metadata["id"]),
        "month": int(metadata.get("month") or 0),
        "status": str(metadata.get("status") or ""),
        "source_filename": metadata.get("sourceFilename"),
        "recruitment_total": float(metadata.get("recruitmentTotal") or 0),
        "referral_total": float(metadata.get("referralTotal") or 0),
        "exception_count": int(metadata.get("exceptionCount") or 0),
        "pending_count": int(metadata.get("pendingCount") or 0),
        "pending_total": float(metadata.get("pendingTotal") or 0),
        "metadata_json": payload,
        "created_at": str(metadata.get("createdAt") or metadata.get("updatedAt") or ""),
        "updated_at": str(metadata.get("updatedAt") or metadata.get("createdAt") or ""),
    }
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            INSERT INTO runs (
              id, month, status, source_filename, recruitment_total, referral_total,
              exception_count, pending_count, pending_total, metadata_json, created_at, updated_at
            )
            VALUES (
              :id, :month, :status, :source_filename, :recruitment_total, :referral_total,
              :exception_count, :pending_count, :pending_total, :metadata_json, :created_at, :updated_at
            )
            ON CONFLICT(id) DO UPDATE SET
              month = excluded.month,
              status = excluded.status,
              source_filename = excluded.source_filename,
              recruitment_total = excluded.recruitment_total,
              referral_total = excluded.referral_total,
              exception_count = excluded.exception_count,
              pending_count = excluded.pending_count,
              pending_total = excluded.pending_total,
              metadata_json = excluded.metadata_json,
              created_at = excluded.created_at,
              updated_at = excluded.updated_at
            """,
            values,
        )
        connection.commit()


def list_indexed_runs(db_path: Path | None = None) -> list[dict[str, Any]]:
    path = db_path or config.DATABASE_PATH
    if not path.exists():
        return []
    init_store(path)
    rows: list[dict[str, Any]] = []
    with sqlite3.connect(path) as connection:
        for (payload,) in connection.execute("SELECT metadata_json FROM runs ORDER BY updated_at DESC, created_at DESC"):
            try:
                rows.append(json.loads(payload))
            except json.JSONDecodeError:
                continue
    return rows
