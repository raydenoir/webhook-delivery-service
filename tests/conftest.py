from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal, engine, get_db
from app.main import app
from app.models import Attempt, Delivery, DeliveryReplay, Event, Subscription


@pytest.fixture
def client() -> Iterator[TestClient]:
    with engine.connect() as connection:
        transaction = connection.begin()
        # изолируем commit обработчиков, чтобы откатить все изменения теста
        session = Session(bind=connection, join_transaction_mode="create_savepoint")

        def get_test_db() -> Iterator[Session]:
            yield session

        app.dependency_overrides[get_db] = get_test_db
        try:
            with TestClient(app) as test_client:
                test_client.headers["Authorization"] = (
                    f"Bearer {settings.api_key.get_secret_value()}"
                )
                yield test_client
        finally:
            app.dependency_overrides.pop(get_db)
            session.close()
            transaction.rollback()


@pytest.fixture
def queued_delivery() -> Iterator[tuple[UUID, UUID]]:
    subscription_id, event_id, delivery_id = uuid4(), uuid4(), uuid4()
    try:
        with SessionLocal() as db:
            db.add(
                Subscription(
                    id=subscription_id,
                    event_type="sender.test",
                    url="https://example.com/webhook",
                )
            )
            db.add(
                Event(
                    id=event_id,
                    type="sender.test",
                    data={"value": 1},
                    idempotency_key=uuid4().hex,
                    request_hash="a" * 64,
                )
            )
            db.flush()
            db.add(
                Delivery(
                    id=delivery_id,
                    event_id=event_id,
                    subscription_id=subscription_id,
                    url="https://example.com/webhook",
                )
            )
            db.commit()
        yield delivery_id, event_id
    finally:
        with SessionLocal() as db:
            db.execute(
                delete(DeliveryReplay).where(DeliveryReplay.delivery_id == delivery_id)
            )
            db.execute(delete(Attempt).where(Attempt.delivery_id == delivery_id))
            db.execute(delete(Delivery).where(Delivery.id == delivery_id))
            db.execute(delete(Event).where(Event.id == event_id))
            db.execute(delete(Subscription).where(Subscription.id == subscription_id))
            db.commit()
