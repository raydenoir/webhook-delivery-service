from uuid import uuid4

from fastapi.testclient import TestClient


def test_create_and_disable_subscription(client: TestClient) -> None:
    response = client.post(
        "/v1/subscriptions",
        json={"event_type": "order.paid", "url": "https://example.com/webhook"},
    )
    assert response.status_code == 201
    subscription = response.json()
    assert subscription["enabled"] is True
    path = f"/v1/subscriptions/{subscription['id']}"
    assert client.get(path).json() == subscription
    assert subscription in client.get("/v1/subscriptions").json()

    response = client.patch(path, json={"enabled": False})
    assert response.status_code == 200
    assert client.get(path).json()["enabled"] is False


def test_subscription_requires_api_key(client: TestClient) -> None:
    client.headers.pop("Authorization")
    assert client.get("/v1/subscriptions").status_code == 401


def test_reject_unsafe_webhook_url(client: TestClient) -> None:
    for url in ("http://example.com/webhook", "https://other.test/webhook"):
        response = client.post(
            "/v1/subscriptions", json={"event_type": "order.paid", "url": url}
        )
        assert response.status_code == 422


def test_missing_subscription(client: TestClient) -> None:
    assert client.get(f"/v1/subscriptions/{uuid4()}").status_code == 404


def test_reject_short_signing_secret(client: TestClient) -> None:
    response = client.post(
        "/v1/subscriptions",
        json={
            "event_type": "order.paid",
            "url": "https://example.com/webhook",
            "signing_secret": "short",
        },
    )
    assert response.status_code == 422
