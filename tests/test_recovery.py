from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import httpx2 as httpx
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Attempt, Delivery
from app.recovery import recover_delivery
from app.sender import send_delivery


def test_recover_only_expired_delivery(queued_delivery: tuple[UUID, UUID]) -> None:
    delivery_id, _ = queued_delivery
    attempt_id = uuid4()
    with SessionLocal() as db:
        delivery = db.get(Delivery, delivery_id)
        delivery.status = "processing"
        delivery.attempt_count = 3
        delivery.lease_token = attempt_id
        delivery.lease_until = datetime.now(timezone.utc) + timedelta(seconds=60)
        db.add(Attempt(id=attempt_id, delivery_id=delivery_id))
        db.commit()
    assert recover_delivery(delivery_id) is False

    with SessionLocal() as db:
        db.get(Delivery, delivery_id).lease_until = datetime.now(
            timezone.utc
        ) - timedelta(seconds=1)
        db.commit()
    assert recover_delivery(delivery_id) is True
    assert recover_delivery(delivery_id) is False
    with SessionLocal() as db:
        assert db.get(Delivery, delivery_id).status == "failed"
        attempt = db.get(Attempt, attempt_id)
        assert attempt.error_kind == "lease_expired"
        assert attempt.http_status is None
        assert attempt.finished_at is not None


def test_late_response_cannot_overwrite_recovery(
    queued_delivery: tuple[UUID, UUID],
) -> None:
    delivery_id, _ = queued_delivery

    def handle(request: httpx.Request) -> httpx.Response:
        # восстанавливаем доставку до прихода ответа получателя
        with SessionLocal() as db:
            db.get(Delivery, delivery_id).lease_until = datetime.now(
                timezone.utc
            ) - timedelta(seconds=1)
            db.commit()
        assert recover_delivery(delivery_id) is True
        return httpx.Response(204)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert send_delivery(delivery_id, client) == "skipped"
    with SessionLocal() as db:
        assert db.get(Delivery, delivery_id).status == "queued"
        attempt = db.scalars(
            select(Attempt).where(Attempt.delivery_id == delivery_id)
        ).one()
        assert attempt.error_kind == "lease_expired"
        assert attempt.http_status is None
