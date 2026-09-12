import subprocess
import sys
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx2 as httpx
import pytest
from kombu.exceptions import OperationalError as BrokerError
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app import dispatcher, tasks
from app.database import SessionLocal
from app.models import Attempt, Delivery, Subscription


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


def test_dispatcher_recovers_after_process_exit(
    queued_delivery: tuple[UUID, UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    delivery_id, _ = queued_delivery
    source = """
import os
import sys
from uuid import UUID
import httpx2 as httpx
from app.sender import send_delivery

def stop_process(request):
    os._exit(0)

with httpx.Client(transport=httpx.MockTransport(stop_process)) as client:
    send_delivery(UUID(sys.argv[1]), client)
"""
    # останавливаем отдельный процесс после захвата доставки, во время запроса
    subprocess.run(
        [sys.executable, "-c", source, str(delivery_id)], check=True, timeout=10
    )
    original_client = httpx.Client
    transport = httpx.MockTransport(lambda request: httpx.Response(204))
    monkeypatch.setattr(
        tasks.httpx,
        "Client",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )

    def publish(args: list[str], expires: int) -> None:
        assert tasks.deliver_webhook.run(args[0]) == "succeeded"

    monkeypatch.setattr(dispatcher.deliver_webhook, "apply_async", publish)
    assert dispatcher.run_once() == 0
    with SessionLocal() as db:
        delivery = db.get(Delivery, delivery_id)
        assert delivery.status == "processing"
        delivery.lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()

    assert dispatcher.run_once() == 0
    with SessionLocal() as db:
        delivery = db.get(Delivery, delivery_id)
        assert delivery.status == "queued"
        assert delivery.attempt_count == 1
        attempt = db.scalars(
            select(Attempt).where(Attempt.delivery_id == delivery_id)
        ).one()
        assert attempt.error_kind == "lease_expired"
        assert attempt.http_status is None
        delivery.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()

    assert dispatcher.run_once() == 1
    with SessionLocal() as db:
        delivery = db.get(Delivery, delivery_id)
        assert delivery.status == "succeeded"
        assert delivery.attempt_count == 2


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
