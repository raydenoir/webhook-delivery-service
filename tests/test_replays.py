from uuid import UUID

import httpx2 as httpx
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.sender import send_delivery


def test_manual_replay_preserves_history(queued_delivery: tuple[UUID, UUID]) -> None:
    delivery_id, _ = queued_delivery
    path = f"/v1/deliveries/{delivery_id}"
    headers = {
        "Authorization": f"Bearer {settings.api_key.get_secret_value()}",
        "Idempotency-Key": "manual-replay",
    }
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(400))
    ) as receiver:
        assert send_delivery(delivery_id, receiver) == "failed"

    with TestClient(app, headers=headers) as api:
        original = api.get(path + "/attempts").json()
        assert len(original) == 1
        response = api.post(path + "/replay")
        assert response.status_code == 202
        assert response.json()["status"] == "queued"
        assert response.json()["id"] == str(delivery_id)
        assert api.post(path + "/replay").status_code == 202
        assert api.get(path + "/attempts").json() == original

        with httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(204))
        ) as receiver:
            assert send_delivery(delivery_id, receiver) == "succeeded"
        assert api.post(path + "/replay").json()["status"] == "succeeded"
        attempts = api.get(path + "/attempts").json()
        assert len(attempts) == 2
        assert attempts[0] == original[0]
        assert attempts[1]["http_status"] == 204
