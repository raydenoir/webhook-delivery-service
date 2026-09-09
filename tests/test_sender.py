import hashlib
import hmac
import json
from uuid import UUID, uuid4

import httpx2 as httpx
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Attempt, Delivery
from app.sender import send_delivery


def test_successful_delivery(queued_delivery: tuple[UUID, UUID]) -> None:
    delivery_id, event_id = queued_delivery
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "POST"
        assert request.headers["X-Webhook-Id"] == str(delivery_id)
        assert "X-Webhook-Signature" not in request.headers
        assert json.loads(request.content) == {
            "id": str(event_id),
            "type": "sender.test",
            "data": {"value": 1},
        }
        # пробуем повторную отправку, пока первая еще выполняется
        assert send_delivery(delivery_id, client) == "skipped"
        return httpx.Response(204)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert send_delivery(delivery_id, client) == "succeeded"
        assert send_delivery(delivery_id, client) == "skipped"
    assert len(requests) == 1
    with SessionLocal() as db:
        assert db.get(Delivery, delivery_id).status == "succeeded"
        attempt = db.scalars(
            select(Attempt).where(Attempt.delivery_id == delivery_id)
        ).one()
        assert attempt.http_status == 204
        assert attempt.error_kind is None
        assert attempt.finished_at is not None


def test_receiver_error(queued_delivery: tuple[UUID, UUID]) -> None:
    delivery_id, _ = queued_delivery
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(400))
    ) as client:
        assert send_delivery(delivery_id, client) == "failed"
    with SessionLocal() as db:
        attempt = db.scalars(
            select(Attempt).where(Attempt.delivery_id == delivery_id)
        ).one()
        assert attempt.http_status == 400
        assert attempt.error_kind == "http_error"


def test_signed_delivery(client: TestClient) -> None:
    secret = "receiver-secret-with-at-least-32-characters"
    response = client.post(
        "/v1/subscriptions",
        json={
            "event_type": "order.signed",
            "url": "https://example.com/webhook",
            "signing_secret": secret,
        },
    )
    assert response.status_code == 201
    subscription = response.json()
    assert "signing_secret" not in subscription
    assert secret not in client.get("/v1/subscriptions").text
    assert (
        "signing_secret"
        not in client.get(f"/v1/subscriptions/{subscription['id']}").json()
    )

    event = client.post(
        "/v1/events",
        json={"type": "order.signed", "data": {"note": "оплачено"}},
        headers={"Idempotency-Key": uuid4().hex},
    ).json()
    delivery = client.get(f"/v1/events/{event['id']}/deliveries").json()[0]

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.headers["Content-Type"] == "application/json"
        signature = request.headers["X-Webhook-Signature"]
        expected = (
            "sha256="
            + hmac.new(secret.encode(), request.content, hashlib.sha256).hexdigest()
        )
        assert hmac.compare_digest(signature, expected)
        changed = (
            "sha256="
            + hmac.new(
                secret.encode(), request.content + b" ", hashlib.sha256
            ).hexdigest()
        )
        assert not hmac.compare_digest(signature, changed)
        assert json.loads(request.content)["data"] == {"note": "оплачено"}
        return httpx.Response(204)

    with httpx.Client(transport=httpx.MockTransport(handle)) as receiver:
        assert send_delivery(UUID(delivery["id"]), receiver) == "succeeded"
