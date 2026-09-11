from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx2 as httpx
import pytest
from billiard.exceptions import SoftTimeLimitExceeded
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Attempt, Delivery
from app.sender import send_delivery


def test_retry_limit_and_delays(queued_delivery: tuple[UUID, UUID]) -> None:
    delivery_id, _ = queued_delivery
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(503))
    ) as client:
        for number, delay in [(1, 10), (2, 30), (3, None)]:
            expected = "queued" if delay else "failed"
            assert send_delivery(delivery_id, client) == expected
            with SessionLocal() as db:
                delivery = db.get(Delivery, delivery_id)
                assert delivery.attempt_count == number
                attempts = list(
                    db.scalars(
                        select(Attempt)
                        .where(Attempt.delivery_id == delivery_id)
                        .order_by(Attempt.started_at)
                    )
                )
                assert len(attempts) == number
                if delay:
                    seconds = (
                        delivery.next_attempt_at - attempts[-1].finished_at
                    ).total_seconds()
                    assert delay - 1 <= seconds <= delay + 1
                else:
                    assert delivery.next_attempt_at is None
            assert send_delivery(delivery_id, client) == "skipped"
            if delay:
                # приближаем следующую попытку, чтобы не ждать в тесте
                with SessionLocal() as db:
                    db.get(Delivery, delivery_id).next_attempt_at = datetime.now(
                        timezone.utc
                    ) - timedelta(seconds=1)
                    db.commit()


@pytest.mark.parametrize(
    "error", [httpx.ReadTimeout("Timed out"), SoftTimeLimitExceeded()]
)
def test_timeout_schedules_retry(
    queued_delivery: tuple[UUID, UUID], error: Exception
) -> None:
    delivery_id, _ = queued_delivery

    def handle(request: httpx.Request) -> httpx.Response:
        raise error

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert send_delivery(delivery_id, client) == "queued"
    with SessionLocal() as db:
        assert db.get(Delivery, delivery_id).next_attempt_at is not None
        attempt = db.scalars(
            select(Attempt).where(Attempt.delivery_id == delivery_id)
        ).one()
        assert attempt.error_kind == "timeout"
