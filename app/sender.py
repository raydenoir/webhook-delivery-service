import argparse
import hashlib
import hmac
import json
import logging
from datetime import timedelta
from uuid import UUID, uuid4

import httpx2 as httpx
from billiard.exceptions import SoftTimeLimitExceeded
from pydantic import HttpUrl
from sqlalchemy import func, select, update

from app.database import SessionLocal
from app.models import Attempt, Delivery, Event, Subscription
from app.urls import validate_webhook_url

LEASE_SECONDS = 60
RETRY_DELAYS = (10, 30)
logger = logging.getLogger(__name__)


def send_delivery(delivery_id: UUID, client: httpx.Client) -> str:
    """выполняем одну попытку для queued доставки и сохраняем результат"""
    attempt_id = uuid4()
    with SessionLocal() as db:
        # забираем доставку только один раз и только для активной подписки
        delivery = db.scalar(
            update(Delivery)
            .where(
                Delivery.id == delivery_id,
                Delivery.status == "queued",
                Delivery.next_attempt_at <= func.clock_timestamp(),
                Delivery.subscription_id.in_(
                    select(Subscription.id).where(Subscription.enabled)
                ),
            )
            .values(
                status="processing",
                lease_token=attempt_id,
                lease_until=func.now() + timedelta(seconds=LEASE_SECONDS),
                attempt_count=Delivery.attempt_count + 1,
                next_attempt_at=None,
            )
            .returning(Delivery)
        )
        if delivery is None:
            return "skipped"

        event = db.get(Event, delivery.event_id)
        body = {"id": str(event.id), "type": event.type, "data": event.data}
        subscription = db.get(Subscription, delivery.subscription_id)
        signing_secret = subscription.signing_secret
        url = delivery.url
        attempt_count = delivery.attempt_count
        db.add(Attempt(id=attempt_id, delivery_id=delivery_id))
        db.commit()

    # закрываем транзакцию перед сетевым запросом
    http_status = None
    error_kind = None
    try:
        validate_webhook_url(HttpUrl(url))
        # подписываем те же байты, которые отправляем получателю
        content = json.dumps(
            body, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        headers = {
            "X-Webhook-Id": str(delivery_id),
            "Content-Type": "application/json",
        }
        if signing_secret is not None:
            signature = hmac.new(
                signing_secret.encode("utf-8"), content, hashlib.sha256
            ).hexdigest()
            headers["X-Webhook-Signature"] = "sha256=" + signature
        with client.stream(
            "POST",
            url,
            content=content,
            headers=headers,
            follow_redirects=False,
        ) as response:
            http_status = response.status_code
            if not 200 <= http_status < 300:
                error_kind = "http_error"
    except (httpx.TimeoutException, SoftTimeLimitExceeded):
        error_kind = "timeout"
    except httpx.RequestError:
        error_kind = "network_error"
    except ValueError:
        error_kind = "configuration_error"

    status = "succeeded" if error_kind is None else "failed"
    next_attempt_at = None
    retryable = error_kind in {"timeout", "network_error"} or (
        http_status is not None
        and (http_status in {408, 429} or 500 <= http_status < 600)
    )
    if retryable and attempt_count <= len(RETRY_DELAYS):
        status = "queued"
        next_attempt_at = func.clock_timestamp() + timedelta(
            seconds=RETRY_DELAYS[attempt_count - 1]
        )
    with SessionLocal() as db:
        # сохраняем результат только пока доставка принадлежит нашей попытке
        saved_id = db.scalar(
            update(Delivery)
            .where(
                Delivery.id == delivery_id,
                Delivery.status == "processing",
                Delivery.lease_token == attempt_id,
            )
            .values(
                status=status,
                lease_token=None,
                lease_until=None,
                next_attempt_at=next_attempt_at,
                publish_after=func.clock_timestamp(),
            )
            .returning(Delivery.id)
        )
        if saved_id is None:
            logger.info(
                "delivery_id=%s result=ignored reason=ownership_lost", delivery_id
            )
            return "skipped"
        db.execute(
            update(Attempt)
            .where(Attempt.id == attempt_id)
            .values(
                http_status=http_status,
                error_kind=error_kind,
                finished_at=func.now(),
            )
        )
        db.commit()
    logger.info(
        "delivery_id=%s status=%s http_status=%s error_kind=%s",
        delivery_id,
        status,
        http_status,
        error_kind,
    )
    return status


def main() -> None:
    logging.basicConfig(level=logging.INFO)
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
