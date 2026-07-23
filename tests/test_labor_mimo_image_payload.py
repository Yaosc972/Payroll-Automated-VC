from bonus_platform.engine.labor import extract


def test_mimo_payg_image_extraction_uses_openai_image_url_payload(monkeypatch):
    captured = {}

    def fake_post_chat_completion(payload, ai_config):
        captured["payload"] = payload
        return []

    monkeypatch.setattr(extract, "_post_chat_completion", fake_post_chat_completion)

    extract._extract_with_ai_images(
        [
            {
                "source_file": "DEPT_1.pdf",
                "page": 1,
                "mime_type": "image/png",
                "base64": "abc123",
            }
        ],
        {
            "enabled": True,
            "provider": "mimo",
            "base_url": "https://api.xiaomimimo.com/v1",
            "model": "mimo-v2.5",
            "api_key": "test-key",
            "max_pages_per_request": 1,
            "max_completion_tokens": 1024,
            "cache_enabled": False,
        },
        supplier="prompt",
        currency="USD",
    )

    content = captured["payload"]["messages"][1]["content"]
    image_parts = [part for part in content if part.get("type") in {"image", "image_url"}]

    assert image_parts == [
        {
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64,abc123"},
        }
    ]
