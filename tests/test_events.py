from uuid import uuid4

from fastapi.testclient import TestClient


def test_create_and_read_event(client: TestClient) -> None:
    body = {"type": "order.paid", "data": {"order_id": "1842"}}
    response = client.post(
        "/v1/events", json=body, headers={"Idempotency-Key": uuid4().hex}
    )
    assert response.status_code == 202
    event = response.json()
    assert event["type"] == body["type"]
    assert event["data"] == body["data"]
    assert client.get(response.headers["Location"]).json() == event


def test_event_idempotency(client: TestClient) -> None:
    headers = {"Idempotency-Key": uuid4().hex}
    body = {"type": "order.paid", "data": {"order_id": "1842"}}
    first = client.post("/v1/events", json=body, headers=headers)
    repeated = client.post("/v1/events", json=body, headers=headers)
    assert first.status_code == repeated.status_code == 202
    assert first.json() == repeated.json()

    changed = {"type": "order.paid", "data": {"order_id": "1843"}}
    conflict = client.post("/v1/events", json=changed, headers=headers)
    assert conflict.status_code == 409
    assert client.get(first.headers["Location"]).json() == first.json()
