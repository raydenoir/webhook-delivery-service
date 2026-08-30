from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import settings
from app.database import engine, get_db
from app.main import app


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
