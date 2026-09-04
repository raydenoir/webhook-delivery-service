import argparse
from uuid import UUID, uuid4

import httpx2 as httpx
from pydantic import HttpUrl
from sqlalchemy import func, select, update

from app.database import SessionLocal
from app.models import Attempt, Delivery, Event, Subscription
from app.urls import validate_webhook_url


def send_delivery(delivery_id: UUID, client: httpx.Client) -> str:
    """выполняем одну попытку для queued доставки и сохраняем результат"""
    with SessionLocal() as db:
        # забираем доставку только один раз и только для активной подписки
        delivery = db.scalar(
            update(Delivery)
            .where(
                Delivery.id == delivery_id,
                Delivery.status == "queued",
                Delivery.subscription_id.in_(
                    select(Subscription.id).where(Subscription.enabled)
                ),
            )
            .values(status="processing")
            .returning(Delivery)
        )
        if delivery is None:
            return "skipped"

        event = db.get(Event, delivery.event_id)
        body = {"id": str(event.id), "type": event.type, "data": event.data}
        url = delivery.url
        attempt_id = uuid4()
        db.add(Attempt(id=attempt_id, delivery_id=delivery_id))
        db.commit()

    # закрываем транзакцию перед сетевым запросом
    http_status = None
    error_kind = None
    try:
        validate_webhook_url(HttpUrl(url))
        with client.stream(
            "POST",
            url,
            json=body,
            headers={"X-Webhook-Id": str(delivery_id)},
            follow_redirects=False,
        ) as response:
            http_status = response.status_code
            if not 200 <= http_status < 300:
                error_kind = "http_error"
    except httpx.TimeoutException:
        error_kind = "timeout"
    except httpx.RequestError:
        error_kind = "network_error"
    except ValueError:
        error_kind = "configuration_error"

    status = "succeeded" if error_kind is None else "failed"
    with SessionLocal() as db:
        db.execute(
            update(Attempt)
            .where(Attempt.id == attempt_id)
            .values(
                http_status=http_status,
                error_kind=error_kind,
                finished_at=func.now(),
            )
        )
        db.execute(
            update(Delivery).where(Delivery.id == delivery_id).values(status=status)
        )
        db.commit()
    return status


def main() -> None:
    parser = argparse.ArgumentParser(description="Send one queued webhook delivery")
    parser.add_argument("delivery_id", type=UUID, help="Delivery UUID")
    args = parser.parse_args()
    with httpx.Client(
        timeout=httpx.Timeout(10.0, connect=3.0),
        follow_redirects=False,
        trust_env=False,
    ) as client:
        status = send_delivery(args.delivery_id, client)
    print(status)
    raise SystemExit(1 if status == "failed" else 0)


if __name__ == "__main__":
    main()
