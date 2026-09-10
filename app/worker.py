import argparse
import logging
import time
from datetime import timedelta

from kombu.exceptions import OperationalError as BrokerError
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import InterfaceError, OperationalError

from app.database import SessionLocal
from app.models import Delivery, Subscription
from app.recovery import recover_delivery
from app.tasks import deliver_webhook

logger = logging.getLogger(__name__)
PUBLISH_PAUSE = 30


def run_once() -> int:
    """восстанавливаем зависшие доставки и публикуем до ста готовых заданий"""
    with SessionLocal() as db:
        expired_ids = list(
            db.scalars(
                select(Delivery.id)
                .where(
                    Delivery.status == "processing",
                    or_(
                        Delivery.lease_until <= func.now(),
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
                    Delivery.next_attempt_at <= func.now(),
                    Delivery.publish_after <= func.now(),
                    Delivery.subscription_id.in_(
                        select(Subscription.id).where(Subscription.enabled)
                    ),
                )
                .order_by(Delivery.next_attempt_at, Delivery.id)
                .limit(100)
            )
        )

    published = 0
    for delivery_id in delivery_ids:
        # фиксируем паузу до публикации, чтобы пережить остановку диспетчера
        with SessionLocal() as db:
            claimed_id = db.scalar(
                update(Delivery)
                .where(
                    Delivery.id == delivery_id,
                    Delivery.status == "queued",
                    Delivery.next_attempt_at <= func.clock_timestamp(),
                    Delivery.publish_after <= func.clock_timestamp(),
                )
                .values(
                    publish_after=func.clock_timestamp()
                    + timedelta(seconds=PUBLISH_PAUSE)
                )
                .returning(Delivery.id)
            )
            db.commit()
        if claimed_id is None:
            continue
        deliver_webhook.apply_async(args=[str(delivery_id)], expires=PUBLISH_PAUSE)
        published += 1
        logger.info("delivery_id=%s action=published", delivery_id)
    return published


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = argparse.ArgumentParser(description="Publish due webhook deliveries")
    parser.add_argument("--once", action="store_true", help="Run one batch and exit")
    args = parser.parse_args()
    try:
        while True:
            try:
                published = run_once()
            except (OperationalError, InterfaceError, BrokerError) as error:
                logger.warning("background cycle failed error=%s", type(error).__name__)
                if args.once:
                    raise SystemExit(1)
                time.sleep(5)
                continue
            if published or args.once:
                print(f"published={published}", flush=True)
            if args.once:
                break
            time.sleep(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
