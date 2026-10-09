"""Company scheduler: one named MySQL lock across replicas, no startup DDL."""
import logging
from datetime import datetime, timedelta
import os

from apscheduler.schedulers.background import BackgroundScheduler

from bonus_platform import config
from bonus_platform.engine.mysql_db import mysql_connection
from .feed import refresh

logger = logging.getLogger(__name__)
_scheduler = None


def refresh_once():
    connection = None
    lock_name = "sigma-policy-refresh"
    acquired = False
    try:
        connection = mysql_connection(config.ADMIN_DATABASE_URL)
        with connection.cursor() as cursor:
            cursor.execute("SELECT GET_LOCK(%s, 0) AS acquired", (lock_name,))
            acquired = cursor.fetchone()["acquired"] == 1
            if not acquired:
                return {"state": "busy"}
        results = refresh()
        logger.info("Policy refresh: %s sources succeeded", sum(r["state"] == "ok" for r in results))
        succeeded = sum(r["state"] == "ok" for r in results)
        return {"state": "ok" if succeeded == len(results) and results else "partial" if succeeded else "error"}
    except Exception as exc:
        logger.warning("Policy refresh unavailable (%s)", type(exc).__name__)
        return {"state": "error"}
    finally:
        try:
            if acquired:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT RELEASE_LOCK(%s)", (lock_name,))
        finally:
            if connection:
                connection.close()


def start():
    global _scheduler
    if os.getenv("SIGMA_POLICY_REFRESH_ENABLED", "").strip().lower() not in {"1", "true", "yes"}:
        return
    if os.getenv("VERCEL") or os.getenv("VERCEL_ENV") or not config.ADMIN_DATABASE_URL.startswith(("mysql://", "mysql+pymysql://")):
        raise RuntimeError("Company policy scheduler requires a persistent MySQL host")
    if _scheduler and _scheduler.running:
        return
    _scheduler = BackgroundScheduler(timezone="Asia/Shanghai", daemon=True)
    # Bound batches rotate 15 sources; daily runs need two days. An hourly
    # company schedule rotates all sources without changing web request limits.
    _scheduler.add_job(refresh_once, "interval", hours=1, id="company-policy-refresh", max_instances=1,
                       coalesce=True, next_run_time=datetime.now(_scheduler.timezone) + timedelta(seconds=60))
    _scheduler.start()


def stop():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=True)
        _scheduler = None
