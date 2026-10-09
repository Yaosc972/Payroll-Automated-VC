"""Module-scoped durable activities and leased jobs; production never creates schema."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
import sqlite3
import time
from uuid import uuid4

from fastapi import HTTPException
from .meal_runs import now
from ..labor.persistent_storage import labor_persistent_environment

SCHEMA = """
CREATE TABLE IF NOT EXISTS sigma_china_payroll_activities (
 environment TEXT NOT NULL, id TEXT NOT NULL, document TEXT NOT NULL,
 PRIMARY KEY (environment, id)
);
CREATE TABLE IF NOT EXISTS sigma_china_payroll_jobs (
 environment TEXT NOT NULL, id TEXT NOT NULL, activity_id TEXT NOT NULL,
 status TEXT NOT NULL, lease_token TEXT NOT NULL DEFAULT '',
 lease_until DOUBLE PRECISION NOT NULL DEFAULT 0, claims INTEGER NOT NULL DEFAULT 0,
 created_at DOUBLE PRECISION NOT NULL, document TEXT NOT NULL,
 PRIMARY KEY (environment, id),
 FOREIGN KEY (environment, activity_id) REFERENCES sigma_china_payroll_activities(environment, id)
);
CREATE INDEX IF NOT EXISTS sigma_china_payroll_claim_idx
 ON sigma_china_payroll_jobs(environment, status, created_at);
"""


def enabled():
    return os.getenv("SIGMA_CHINA_PAYROLL_BACKEND", "").strip().lower() in {"mysql", "postgres", "sqlite"}


def hosted():
    from bonus_platform.auth import production_runtime
    return production_runtime()


class Store:
    def __init__(self):
        self.backend = os.getenv("SIGMA_CHINA_PAYROLL_BACKEND", "").strip().lower()
        self.environment = labor_persistent_environment()
        if len(self.environment) > 64:
            raise RuntimeError("Payroll environment name exceeds 64 characters")
        if self.backend == "sqlite":
            if hosted() or self.environment != "local":
                raise RuntimeError("SQLite is restricted to local verification")
            self.database = os.environ["SIGMA_CHINA_PAYROLL_SQLITE_PATH"]
        elif self.backend == "postgres":
            self.database = (os.getenv("ADMIN_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()
            if not self.database:
                raise RuntimeError("Missing server database configuration")
        elif self.backend == "mysql":
            from bonus_platform.config import _database_url_from_environment
            self.database = _database_url_from_environment()
            if not self.database.startswith(("mysql://", "mysql+pymysql://")):
                raise RuntimeError("Missing company MySQL configuration")
        else:
            raise RuntimeError("Durable payroll backend is not configured")

    @contextmanager
    def transaction(self):
        lock_name = None
        cursors = []
        if self.backend == "sqlite":
            connection = sqlite3.connect(self.database, timeout=15)
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
        elif self.backend == "postgres":
            import psycopg
            connection = psycopg.connect(self.database, connect_timeout=10)
            # Small metadata transactions only; no network/file work holds this lock.
            key = int.from_bytes(hashlib.sha256(("china-payroll/" + self.environment).encode()).digest()[:8], "big", signed=True)
            connection.execute("SET LOCAL statement_timeout = '15s'")
            connection.execute("SELECT pg_advisory_xact_lock(%s)", (key,))
        else:
            from ..mysql_db import mysql_connection
            connection = mysql_connection(self.database)
            lock_name = "china-payroll/" + hashlib.sha256(self.environment.encode()).hexdigest()[:48]
        try:
            if lock_name:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT GET_LOCK(%s, 15) AS acquired", (lock_name,))
                    if cursor.fetchone()["acquired"] != 1:
                        raise RuntimeError("Payroll metadata lock unavailable")
                connection.begin()
            def execute(sql, values=()):
                if self.backend == "mysql":
                    cursor = connection.cursor()
                    cursors.append(cursor)
                    cursor.execute(sql, values)
                    return _TupleRows(cursor)
                return connection.execute(sql.replace("%s", "?") if self.backend == "sqlite" else sql, values)
            yield execute
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            for cursor in cursors:
                cursor.close()
            if lock_name:
                try:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT RELEASE_LOCK(%s)", (lock_name,))
                finally:
                    connection.close()
            else:
                connection.close()

    def initialize_local(self):
        if self.backend != "sqlite":
            raise RuntimeError("Production schema requires an approved migration")
        with sqlite3.connect(self.database) as connection:
            connection.executescript(SCHEMA)

    def _clock(self, sql):
        if self.backend == "sqlite":
            return time.time()
        query = "SELECT UNIX_TIMESTAMP(CURRENT_TIMESTAMP(6))" if self.backend == "mysql" else "SELECT EXTRACT(EPOCH FROM clock_timestamp())"
        return float(sql(query).fetchone()[0])

    def _get(self, sql, table, identifier):
        row = sql(f"SELECT document FROM {table} WHERE environment=%s AND id=%s", (self.environment, identifier)).fetchone()
        if not row:
            raise HTTPException(404, "核算活动或批次不存在。")
        return json.loads(row[0])

    def _save_activity(self, sql, record):
        sql("UPDATE sigma_china_payroll_activities SET document=%s WHERE environment=%s AND id=%s",
            (json.dumps(record, ensure_ascii=False), self.environment, record["activityId"]))

    def get(self, identifier):
        with self.transaction() as sql:
            return self._get(sql, "sigma_china_payroll_activities", identifier)

    def records(self):
        with self.transaction() as sql:
            return [json.loads(row[0]) for row in sql("SELECT document FROM sigma_china_payroll_activities WHERE environment=%s", (self.environment,)).fetchall()]

    def create(self, record):
        with self.transaction() as sql:
            existing = sql("SELECT document FROM sigma_china_payroll_activities WHERE environment=%s AND id=%s", (self.environment, record["activityId"])).fetchone()
            if existing:
                previous = json.loads(existing[0])
                if any(previous[k] != record[k] for k in ("subject", "month", "name")) or previous["creator"]["userId"] != record["creator"]["userId"]:
                    raise HTTPException(409, "该创建请求已用于另一核算活动。")
                return previous
            sql("INSERT INTO sigma_china_payroll_activities(environment,id,document) VALUES (%s,%s,%s)",
                (self.environment, record["activityId"], json.dumps(record, ensure_ascii=False)))
            return record

    def uploads(self, identifier, inputs):
        with self.transaction() as sql:
            record = self._get(sql, "sigma_china_payroll_activities", identifier)
            if record["subject"] != "wx-meal-allowance" or record["status"] not in {"draft", "failed"}:
                raise HTTPException(409, "当前活动不能更换考勤文件。")
            record.update(inputs=inputs, updatedAt=now())
            self._save_activity(sql, record)
            return record

    def enqueue(self, identifier):
        with self.transaction() as sql:
            record = self._get(sql, "sigma_china_payroll_activities", identifier)
            if record["status"] in {"running", "completed"}:
                return record
            if record["subject"] == "wx-meal-allowance" and not record.get("inputs"):
                raise HTTPException(400, "请先上传所选月份的 WX 考勤文件。")
            run_id = uuid4().hex
            job = {"runId": run_id, "activityId": identifier, "subject": record["subject"], "month": record["month"],
                   "creator": record["creator"], "inputs": record.get("inputs", []), "createdAt": now(),
                   "status": "running", "progress": "已进入核算队列", "sourceType": "wx" if record["subject"] == "wx-meal-allowance" else "hr"}
            sql("INSERT INTO sigma_china_payroll_jobs(environment,id,activity_id,status,created_at,document) VALUES (%s,%s,%s,%s,%s,%s)",
                (self.environment, run_id, identifier, "queued", time.time(), json.dumps(job, ensure_ascii=False)))
            record.update(runId=run_id, status="running", progress=job["progress"], updatedAt=now())
            record.setdefault("attempts", []).append(run_id)
            self._save_activity(sql, record)
            return record

    def job(self, run_id):
        with self.transaction() as sql:
            return self._get(sql, "sigma_china_payroll_jobs", run_id)

    def claim(self, lease_seconds=120):
        with self.transaction() as sql:
            while True:
                timestamp = self._clock(sql)
                row = sql("SELECT id,document,claims FROM sigma_china_payroll_jobs WHERE environment=%s AND (status='queued' OR (status='running' AND lease_until<%s)) ORDER BY created_at LIMIT 1", (self.environment, timestamp)).fetchone()
                if not row:
                    return None
                job = json.loads(row[1])
                if row[2] >= 3:
                    job.update(status="failed", progress="核算多次中断，请检查 Worker 后重新核算。")
                    self._finish(sql, job, "failed")
                    continue
                token = uuid4().hex
                sql("UPDATE sigma_china_payroll_jobs SET status='running',lease_token=%s,lease_until=%s,claims=claims+1 WHERE environment=%s AND id=%s",
                    (token, timestamp + lease_seconds, self.environment, row[0]))
                return job, token

    def _finish(self, sql, job, status):
        sql("UPDATE sigma_china_payroll_jobs SET document=%s,status=%s,lease_token='',lease_until=0 WHERE environment=%s AND id=%s",
            (json.dumps(job, ensure_ascii=False), status, self.environment, job["runId"]))
        record = self._get(sql, "sigma_china_payroll_activities", job["activityId"])
        if record["runId"] == job["runId"]:
            record.update(status=job["status"], progress=job["progress"], summary=job.get("summary", {}), updatedAt=now())
            self._save_activity(sql, record)

    def update(self, run_id, token, updates=None, terminal=False, lease_seconds=120):
        with self.transaction() as sql:
            timestamp = self._clock(sql)
            row = sql("SELECT document FROM sigma_china_payroll_jobs WHERE environment=%s AND id=%s AND status='running' AND lease_token=%s AND lease_until>%s",
                      (self.environment, run_id, token, timestamp)).fetchone()
            if not row:
                raise LeaseLost()
            job = json.loads(row[0])
            job.update(updates or {})
            if terminal:
                self._finish(sql, job, job["status"])
            else:
                sql("UPDATE sigma_china_payroll_jobs SET document=%s,lease_until=%s WHERE environment=%s AND id=%s",
                    (json.dumps(job, ensure_ascii=False), timestamp + lease_seconds, self.environment, run_id))
            return job


class LeaseLost(RuntimeError):
    """A reclaimed/expired job can never publish over a newer worker."""


class _TupleRows:
    """Keep the store's positional row contract with the existing DictCursor."""
    def __init__(self, cursor):
        self.cursor = cursor

    def fetchone(self):
        row = self.cursor.fetchone()
        return tuple(row.values()) if row is not None else None

    def fetchall(self):
        return [tuple(row.values()) for row in self.cursor.fetchall()]
