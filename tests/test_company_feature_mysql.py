"""Optional real MySQL checks, restricted to an explicitly isolated loopback DB."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
import subprocess
import sys
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import HTTPException
import pytest

from bonus_platform import config
from bonus_platform.engine.mysql_db import mysql_connection
from bonus_platform.engine.china_employee_payroll.durable_store import Store, LeaseLost
from bonus_platform.engine.policy import feed, scheduler
from scripts.migrate_company_features import main as migrate


@pytest.fixture
def database(monkeypatch):
    url = os.getenv("SIGMA_TEST_MYSQL_URL", "")
    if not url:
        pytest.skip("Explicit isolated local MySQL URL required")
    parsed = urlsplit(url)
    assert parsed.hostname in {"127.0.0.1", "localhost"}
    assert parsed.path.startswith("/sigma_features_test")
    monkeypatch.setenv("ADMIN_DATABASE_URL", url)
    monkeypatch.setattr(config, "ADMIN_DATABASE_URL", url)
    monkeypatch.setenv("SIGMA_CHINA_PAYROLL_BACKEND", "mysql")
    monkeypatch.setenv("SIGMA_LABOR_STORAGE_ENV", "mysql-test-" + uuid4().hex)
    migrate()
    migrate()
    return url


def record(subject="meal-allowance"):
    return {"activityId": uuid4().hex, "subject": subject, "month": "2026-09",
            "name": "核算验证", "creator": {"userId": "test", "name": "测试"},
            "status": "draft", "createdAt": "2026-10-09T10:00:00+08:00"}


def test_mysql_queue_concurrency_restart_fencing_and_environment(database, monkeypatch):
    store = Store()
    item = store.create(record())
    with ThreadPoolExecutor(8) as pool:
        jobs = list(pool.map(lambda _: Store().enqueue(item["activityId"]), range(16)))
    assert len({job["runId"] for job in jobs}) == 1
    code = "import json,sys; from bonus_platform.engine.china_employee_payroll.durable_store import Store; print(json.dumps(Store().get(sys.argv[1])))"
    recovered = json.loads(subprocess.check_output([sys.executable, "-c", code, item["activityId"]]))
    assert recovered["runId"] == jobs[0]["runId"]
    job, old = store.claim(lease_seconds=-1)
    same, new = Store().claim()
    assert same["runId"] == job["runId"] and old != new
    with pytest.raises(LeaseLost):
        store.update(job["runId"], old, {"status": "completed"}, terminal=True)
    with ThreadPoolExecutor(8) as pool:
        assert all(value is None for value in pool.map(lambda _: Store().claim(), range(8)))
    store.update(job["runId"], new, {"status": "completed", "progress": "完成"}, terminal=True)
    assert Store().get(item["activityId"])["status"] == "completed"
    monkeypatch.setenv("SIGMA_LABOR_STORAGE_ENV", "another-" + uuid4().hex)
    with pytest.raises(HTTPException) as failure:
        Store().get(item["activityId"])
    assert failure.value.status_code == 404


def test_mysql_lock_released_on_rollback_and_retry_limit(database):
    store = Store()
    one = record()
    with pytest.raises(ValueError):
        with store.transaction() as sql:
            sql("INSERT INTO sigma_china_payroll_activities(environment,id,document) VALUES (%s,%s,%s)",
                (store.environment, one["activityId"], json.dumps(one)))
            raise ValueError("rollback")
    assert Store().records() == []
    item = Store().create(one)
    store.enqueue(item["activityId"])
    for _ in range(3):
        assert Store().claim(lease_seconds=-1)
    assert store.claim() is None
    assert Store().get(item["activityId"])["status"] == "failed"
    assert len(Store().enqueue(item["activityId"])["attempts"]) == 2


def test_mysql_policy_upsert_failed_refresh_preserves_articles(database):
    source = feed.SOURCES[0]
    identifier = sha256(uuid4().bytes).hexdigest()
    rows = [{"id": identifier, "source_id": source["id"], "title": "企业职工医保缴费政策验证",
             "url": "https://www.nhsa.gov.cn/art/2026/10/9/art_104_123.html",
             "published": datetime.now(timezone.utc).date().isoformat(), "fetched_at": feed.now()}]
    for _ in range(2):
        feed.refresh(sources=[source], collector=lambda _: (rows, "ok", ""))
    first = feed.query(q="企业职工医保缴费政策验证")
    assert len([row for row in first["items"] if row["id"] == identifier]) == 1
    feed.refresh(sources=[source], collector=lambda _: ([], "error", "offline"))
    assert any(row["id"] == identifier for row in feed.query(q="企业职工医保缴费政策验证")["items"])
    check = next(row for row in feed.query()["sources"] if row["id"] == source["id"])
    assert check["state"] == "error" and check["success_at"]


def test_mysql_scheduler_lock_and_failure_state(database, monkeypatch):
    calls = []
    monkeypatch.setattr(scheduler, "refresh", lambda: calls.append(True) or [{"state": "ok"}])
    connection = mysql_connection(database)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT GET_LOCK('sigma-policy-refresh', 0)")
        assert scheduler.refresh_once() == {"state": "busy"}
        assert not calls
    finally:
        connection.close()
    assert scheduler.refresh_once() == {"state": "ok"}
    assert len(calls) == 1
    monkeypatch.setattr(scheduler, "refresh", lambda: [{"state": "error"}])
    assert scheduler.refresh_once() == {"state": "error"}
    monkeypatch.setattr(scheduler, "refresh", lambda: [{"state": "ok"}, {"state": "error"}])
    assert scheduler.refresh_once() == {"state": "partial"}
