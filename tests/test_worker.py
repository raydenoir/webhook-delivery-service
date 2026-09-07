from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx2 as httpx
import pytest

from app import worker
from app.database import SessionLocal
from app.models import Delivery, Subscription


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
