import os
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import make_url, text

test_database_url = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://webhook:webhook@127.0.0.1:5433/webhook_test",
)
if make_url(test_database_url).database != "webhook_test":
    raise pytest.UsageError("TEST_DATABASE_URL must use the webhook_test database")

# задаем окружение до импорта приложения и создания его подключения
os.environ["DATABASE_URL"] = test_database_url
os.environ["API_KEY"] = "test-api-key"
os.environ["ALLOWED_WEBHOOK_HOSTS"] = '["example.com"]'

from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Delivery, Event, Subscription  # noqa: E402


def clear_tables() -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE delivery_replays, attempts, deliveries, events, subscriptions"
            )
        )


@pytest.fixture(scope="session", autouse=True)
def test_database() -> Iterator[None]:
    if engine.url != make_url(test_database_url):
        raise pytest.UsageError("Application must use TEST_DATABASE_URL during tests")
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def clean_database(test_database: None) -> Iterator[None]:
    clear_tables()
    try:
        yield
    finally:
        clear_tables()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app, headers={"Authorization": "Bearer test-api-key"}) as client:
        yield client


@pytest.fixture
def queued_delivery() -> tuple[UUID, UUID]:
    subscription_id, event_id, delivery_id = uuid4(), uuid4(), uuid4()
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
    return delivery_id, event_id
