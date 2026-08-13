from datetime import datetime, timedelta, timezone

from bonus_platform.engine.labor.operations import build_labor_operations_snapshot


def _time(minutes_ago: int) -> str:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return (now - timedelta(minutes=minutes_ago)).isoformat(timespec="seconds") + "Z"


def test_operations_snapshot_builds_alerts_and_metrics():
    jobs = [
        {
            "id": "job-1", "status": "running", "createdAt": _time(40), "startedAt": _time(35),
            "heartbeatAt": _time(6), "errorCode": "", "finishedAt": "",
        },
        {
            "id": "job-2", "status": "failed", "createdAt": _time(20), "startedAt": _time(18),
            "finishedAt": _time(10), "errorCode": "OCR_TIMEOUT",
        },
        {
            "id": "job-3", "status": "succeeded", "createdAt": _time(10), "startedAt": _time(9),
            "finishedAt": _time(5), "errorCode": "",
        },
    ]
    events = [
        {"event": "ocr_cache", "summary": {"cacheHit": True}},
        {"event": "ocr_cache", "summary": {"cacheHit": False}},
        {"event": "model_call", "status": "failed"},
        {"event": "model_call", "status": "succeeded"},
    ]

    snapshot = build_labor_operations_snapshot(jobs, events, storage={"freeBytes": 100, "minimumFreeBytes": 1000})

    codes = {alert["code"] for alert in snapshot["alerts"]}
    assert {"WORKER_OFFLINE", "TASK_OVER_30_MINUTES", "OCR_FAILURE", "STORAGE_CAPACITY_LOW"}.issubset(codes)
    assert snapshot["metrics"]["taskFailureRate"] == 0.5
    assert snapshot["metrics"]["averageDurationSeconds"] == 360
    assert snapshot["metrics"]["ocrCacheHitRate"] == 0.5
    assert snapshot["metrics"]["modelCallFailureRate"] == 0.5


def test_operations_snapshot_has_no_offline_alert_without_active_work():
    snapshot = build_labor_operations_snapshot([], [], storage={})
    assert not any(alert["code"] == "WORKER_OFFLINE" for alert in snapshot["alerts"])
