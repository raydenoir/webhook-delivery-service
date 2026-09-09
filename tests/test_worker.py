import subprocess
import sys
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx2 as httpx
import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app import worker
from app.database import SessionLocal
from app.models import Attempt, Delivery, Subscription


def test_worker_selects_due_active_deliveries(
    queued_delivery: tuple[UUID, UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    delivery_id, _ = queued_delivery
    selected = []

    def record_delivery(selected_id: UUID, client: httpx.Client) -> str:
        selected.append(selected_id)
        return "skipped"

    # проверяем выборку без отправки запросов и изменения чужих доставок
    monkeypatch.setattr(worker, "send_delivery", record_delivery)
    with httpx.Client() as client:
        worker.run_once(client)
        assert delivery_id in selected
        selected.clear()
        with SessionLocal() as db:
            delivery = db.get(Delivery, delivery_id)
            delivery.next_attempt_at = datetime.now(timezone.utc) + timedelta(hours=1)
            db.commit()
        worker.run_once(client)
        assert delivery_id not in selected

        selected.clear()
        with SessionLocal() as db:
            delivery = db.get(Delivery, delivery_id)
            delivery.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.get(Subscription, delivery.subscription_id).enabled = False
            db.commit()
        worker.run_once(client)
        assert delivery_id not in selected


def test_worker_recovers_after_process_exit(queued_delivery: tuple[UUID, UUID]) -> None:
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
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(204))
    ) as client:
        assert worker.run_once(client) == 0
        with SessionLocal() as db:
            delivery = db.get(Delivery, delivery_id)
            assert delivery.status == "processing"
            delivery.lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.commit()

        assert worker.run_once(client) == 0
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

        assert worker.run_once(client) == 1
    with SessionLocal() as db:
        delivery = db.get(Delivery, delivery_id)
        assert delivery.status == "succeeded"
        assert delivery.attempt_count == 2


def test_worker_continues_after_database_error(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    pauses = []

    def run_once(client: httpx.Client) -> int:
        calls.append(1)
        if len(calls) == 1:
            raise OperationalError(None, None, Exception("Connection unavailable"))
        raise KeyboardInterrupt

    monkeypatch.setattr(worker, "run_once", run_once)
    monkeypatch.setattr(worker.time, "sleep", pauses.append)
    monkeypatch.setattr(sys, "argv", ["worker"])
    worker.main()
    assert len(calls) == 2
    assert pauses == [5]
