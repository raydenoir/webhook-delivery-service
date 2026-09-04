import json
from uuid import UUID

import httpx2 as httpx
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
