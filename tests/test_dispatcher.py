import sys
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from kombu.exceptions import OperationalError as BrokerError
from sqlalchemy.exc import OperationalError

from app import dispatcher
from app.database import SessionLocal
from app.models import Delivery, Subscription


def test_dispatcher_selects_due_active_deliveries(
    queued_delivery: tuple[UUID, UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    delivery_id, _ = queued_delivery
    selected = []

    def record_delivery(args: list[str], expires: int) -> None:
        selected.append(UUID(args[0]))

    # проверяем выборку без отправки запросов и изменения чужих доставок
    monkeypatch.setattr(dispatcher.deliver_webhook, "apply_async", record_delivery)
    dispatcher.run_once()
    assert delivery_id in selected
    selected.clear()
    with SessionLocal() as db:
        delivery = db.get(Delivery, delivery_id)
        delivery.next_attempt_at = datetime.now(timezone.utc) + timedelta(hours=1)
        db.commit()
    dispatcher.run_once()
    assert delivery_id not in selected

    selected.clear()
    with SessionLocal() as db:
        delivery = db.get(Delivery, delivery_id)
        delivery.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        delivery.publish_after = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.get(Subscription, delivery.subscription_id).enabled = False
        db.commit()
    dispatcher.run_once()
    assert delivery_id not in selected


def test_dispatcher_continues_after_database_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    pauses = []

    def run_once() -> int:
        calls.append(1)
        if len(calls) == 1:
            raise OperationalError(None, None, Exception("Connection unavailable"))
        raise KeyboardInterrupt

    monkeypatch.setattr(dispatcher, "run_once", run_once)
    monkeypatch.setattr(dispatcher.time, "sleep", pauses.append)
    monkeypatch.setattr(sys, "argv", ["dispatcher"])
    dispatcher.main()
    assert len(calls) == 2
    assert pauses == [5]


def test_failed_publication_is_retried(
    queued_delivery: tuple[UUID, UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    delivery_id, _ = queued_delivery
    published = []

    def unavailable(args: list[str], expires: int) -> None:
        raise BrokerError("Broker unavailable")

    def publish(args: list[str], expires: int) -> None:
        published.append(UUID(args[0]))

    monkeypatch.setattr(dispatcher.deliver_webhook, "apply_async", unavailable)
    with pytest.raises(BrokerError):
        dispatcher.run_once()
    with SessionLocal() as db:
        delivery = db.get(Delivery, delivery_id)
        assert delivery.status == "queued"
        assert delivery.attempt_count == 0
        delivery.publish_after = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()

    monkeypatch.setattr(dispatcher.deliver_webhook, "apply_async", publish)
    assert dispatcher.run_once() == 1
    assert dispatcher.run_once() == 0
    assert published == [delivery_id]
