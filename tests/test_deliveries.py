from uuid import uuid4

from fastapi.testclient import TestClient


def test_delivery_selection_and_duplicate_event(client: TestClient) -> None:
    event_type = "test." + uuid4().hex
    active = client.post(
        "/v1/subscriptions",
        json={"event_type": event_type, "url": "https://example.com/active"},
    ).json()
    disabled = client.post(
        "/v1/subscriptions",
        json={"event_type": event_type, "url": "https://example.com/disabled"},
    ).json()
    client.patch(f"/v1/subscriptions/{disabled['id']}", json={"enabled": False})
    client.post(
        "/v1/subscriptions",
        json={"event_type": "other.event", "url": "https://example.com/other"},
    )
    headers = {"Idempotency-Key": uuid4().hex}
    body = {"type": event_type, "data": {}}
    response = client.post("/v1/events", json=body, headers=headers)
    assert response.status_code == 202
    event = response.json()
    path = f"/v1/events/{event['id']}/deliveries"
    deliveries = client.get(path).json()
    assert len(deliveries) == 1
    delivery = deliveries[0]
    assert delivery["subscription_id"] == active["id"]
    assert delivery["url"] == active["url"]
    assert delivery["status"] == "queued"
    assert client.get(f"/v1/deliveries/{delivery['id']}").json() == delivery

    assert client.post("/v1/events", json=body, headers=headers).json() == event
    assert client.get(path).json() == deliveries


def test_event_without_subscribers(client: TestClient) -> None:
    event = client.post(
        "/v1/events",
        json={"type": "test." + uuid4().hex, "data": {}},
        headers={"Idempotency-Key": uuid4().hex},
    ).json()
    assert client.get(f"/v1/events/{event['id']}/deliveries").json() == []
