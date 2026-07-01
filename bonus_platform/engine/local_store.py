from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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

MYSQL_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id VARCHAR(255) PRIMARY KEY,
  month INT NOT NULL,
  status VARCHAR(50) NOT NULL,
  source_filename VARCHAR(500),
  recruitment_total DOUBLE DEFAULT 0,
  referral_total DOUBLE DEFAULT 0,
  exception_count INT DEFAULT 0,
  pending_count INT DEFAULT 0,
  pending_total DOUBLE DEFAULT 0,
  metadata_json JSON NOT NULL,
  created_at VARCHAR(50) NOT NULL,
  updated_at VARCHAR(50) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""


def _admin_database_url() -> str:
    return (os.environ.get("ADMIN_DATABASE_URL") or os.environ.get("DATABASE_URL") or "").strip()


def _is_mysql() -> bool:
    return _admin_database_url().startswith("mysql://")


class _MySQLStoreConnection:
    """将 PyMySQL connection 包装为 sqlite3 风格的 conn.execute() 接口。"""

    def __init__(self, conn: Any) -> None:
        self._conn = conn
        self._cursor: Any = None

    def __enter__(self) -> "_MySQLStoreConnection":
        self._cursor = self._conn.cursor()
        return self

    def __exit__(self, *args: Any) -> None:
        if self._cursor:
            self._cursor.close()
        self._conn.close()

    def execute(self, sql: str, params: Any = ()) -> Any:
        self._cursor.execute(sql, params)
        return self._cursor

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()


def _connect_mysql():
    import pymysql
    from urllib.parse import unquote
    parsed = urlparse(_admin_database_url())
    conn = pymysql.connect(
        host=parsed.hostname or "127.0.0.1",
        port=parsed.port or 3306,
        user=parsed.username or "root",
        password=unquote(parsed.password) if parsed.password else "",
        database=(parsed.path or "/sigma").lstrip("/") or "sigma",
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
        connect_timeout=5,
        read_timeout=30,
    )
    return _MySQLStoreConnection(conn)


def init_store(db_path: Path | None = None) -> Path:
    if _is_mysql():
        with _connect_mysql() as conn:
            conn.execute(MYSQL_SCHEMA)
            # MYSQL_SCHEMA may have trailing CREATE TABLE stmt with ;
            # already handled by wrapper
            conn.commit()
        return config.DATABASE_PATH
    path = db_path or config.DATABASE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(SCHEMA)
        connection.commit()
    return path


def upsert_run_metadata(metadata: dict[str, Any], db_path: Path | None = None) -> None:
    if not metadata.get("id"):
        return
    if _is_mysql():
        _upsert_run_metadata_mysql(metadata)
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


def _upsert_run_metadata_mysql(metadata: dict[str, Any]) -> None:
    init_store()
    payload = json.dumps(metadata, ensure_ascii=False)
    with _connect_mysql() as conn:
        conn.execute(
            """
            INSERT INTO runs (
              id, month, status, source_filename, recruitment_total, referral_total,
              exception_count, pending_count, pending_total, metadata_json, created_at, updated_at
            )
            VALUES (
              %(id)s, %(month)s, %(status)s, %(source_filename)s, %(recruitment_total)s, %(referral_total)s,
              %(exception_count)s, %(pending_count)s, %(pending_total)s, %(metadata_json)s, %(created_at)s, %(updated_at)s
            )
            ON DUPLICATE KEY UPDATE
              month = VALUES(month),
              status = VALUES(status),
              source_filename = VALUES(source_filename),
              recruitment_total = VALUES(recruitment_total),
              referral_total = VALUES(referral_total),
              exception_count = VALUES(exception_count),
              pending_count = VALUES(pending_count),
              pending_total = VALUES(pending_total),
              metadata_json = VALUES(metadata_json),
              created_at = VALUES(created_at),
              updated_at = VALUES(updated_at)
            """,
            {
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
            },
        )
        conn.commit()


def list_indexed_runs(db_path: Path | None = None) -> list[dict[str, Any]]:
    if _is_mysql():
        init_store()
        rows: list[dict[str, Any]] = []
        with _connect_mysql() as conn:
            for row in conn.execute("SELECT metadata_json FROM runs ORDER BY updated_at DESC, created_at DESC"):
                try:
                    payload = row.get("metadata_json")
                    if isinstance(payload, str):
                        payload = json.loads(payload)
                    if isinstance(payload, dict):
                        rows.append(payload)
                except json.JSONDecodeError:
                    continue
        return rows
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
