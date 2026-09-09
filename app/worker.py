import argparse
import logging
import time

import httpx2 as httpx
from sqlalchemy import func, or_, select
from sqlalchemy.exc import InterfaceError, OperationalError

from app.database import SessionLocal
from app.models import Delivery, Subscription
from app.recovery import recover_delivery
from app.sender import send_delivery

logger = logging.getLogger(__name__)


def run_once(client: httpx.Client) -> int:
    """отправляем до ста готовых доставок за один проход"""
    with SessionLocal() as db:
        expired_ids = list(
            db.scalars(
                select(Delivery.id)
                .where(
                    Delivery.status == "processing",
                    or_(
                        Delivery.lease_until <= func.clock_timestamp(),
                        Delivery.lease_until.is_(None),
                    ),
                )
                .order_by(Delivery.lease_until, Delivery.id)
                .limit(100)
            )
        )
    for delivery_id in expired_ids:
        recover_delivery(delivery_id)

    with SessionLocal() as db:
        delivery_ids = list(
            db.scalars(
                select(Delivery.id)
                .where(
                    Delivery.status == "queued",
                    Delivery.next_attempt_at <= func.clock_timestamp(),
                    Delivery.subscription_id.in_(
                        select(Subscription.id).where(Subscription.enabled)
                    ),
                )
                .order_by(Delivery.next_attempt_at, Delivery.id)
                .limit(100)
            )
        )

    # проверяем и захватываем каждую доставку внутри отправителя
    sent = 0
    for delivery_id in delivery_ids:
        if send_delivery(delivery_id, client) != "skipped":
            sent += 1
    return sent


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = argparse.ArgumentParser(description="Send due webhook deliveries")
    parser.add_argument("--once", action="store_true", help="Run one batch and exit")
    args = parser.parse_args()
    try:
        with httpx.Client(
            timeout=httpx.Timeout(10.0, connect=3.0),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            while True:
                try:
                    sent = run_once(client)
                except (OperationalError, InterfaceError) as error:
                    logger.warning(
                        "database operation failed error=%s", type(error).__name__
                    )
                    if args.once:
                        raise SystemExit(1)
                    time.sleep(5)
                    continue
                if sent or args.once:
                    print(f"sent={sent}", flush=True)
                if args.once:
                    break
                time.sleep(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
