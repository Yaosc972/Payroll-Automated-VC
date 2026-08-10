from fastapi.testclient import TestClient

from bonus_platform.app import app


def test_feishu_event_url_verification_echoes_challenge() -> None:
    response = TestClient(app).post(
        "/api/feishu/events",
        json={
            "challenge": "verification-challenge",
            "token": "verification-token",
            "type": "url_verification",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"challenge": "verification-challenge"}


def test_feishu_message_event_is_acknowledged_without_reply() -> None:
    response = TestClient(app).post(
        "/api/feishu/events",
        json={
            "schema": "2.0",
            "header": {
                "event_id": "event-1",
                "event_type": "im.message.receive_v1",
            },
            "event": {"message": {"message_id": "message-1"}},
        },
    )

    assert response.status_code == 200
    assert response.json() == {"code": 0}
