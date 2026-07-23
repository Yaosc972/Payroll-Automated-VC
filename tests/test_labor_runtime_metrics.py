import json

from bonus_platform.engine.labor.runtime_metrics import record_labor_runtime_metric
from bonus_platform.engine.labor.extract import MiMoTimeoutException, _extract_with_ai_images


def test_runtime_metric_writes_only_when_path_is_configured(monkeypatch, tmp_path):
    path = tmp_path / "metrics.jsonl"
    monkeypatch.setenv("LABOR_RUNTIME_METRICS_PATH", str(path))

    record_labor_runtime_metric("ocr_cache", status="hit", summary={"cacheHit": True})

    saved = json.loads(path.read_text())
    assert saved["event"] == "ocr_cache"
    assert saved["summary"]["cacheHit"] is True


def test_image_model_calls_record_success_and_failure(monkeypatch, tmp_path):
    path = tmp_path / "metrics.jsonl"
    monkeypatch.setenv("LABOR_RUNTIME_METRICS_PATH", str(path))
    calls = {"count": 0}

    def fake_post(*_):
        calls["count"] += 1
        if calls["count"] == 1:
            raise MiMoTimeoutException("timeout")
        return [{"employee_name_raw": "Worker", "hours": 8, "amount": 100, "confidence": 0.95}]

    monkeypatch.setattr("bonus_platform.engine.labor.extract._post_chat_completion", fake_post)
    _extract_with_ai_images(
        [
            {"source_file": "a.pdf", "page": 1, "mime_type": "image/png", "base64": "abc"},
            {"source_file": "b.pdf", "page": 1, "mime_type": "image/png", "base64": "def"},
        ],
        {
            "provider": "mimo", "api_key": "token", "base_url": "https://example.test/v1",
            "model": "mimo", "max_pages_per_request": 1, "image_retry_delays": [], "cache_enabled": False,
        },
    )

    events = [json.loads(line) for line in path.read_text().splitlines()]
    model_statuses = [event["status"] for event in events if event["event"] == "model_call"]
    assert model_statuses == ["failed", "succeeded"]
