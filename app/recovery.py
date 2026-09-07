import argparse
from uuid import UUID

from sqlalchemy import func, select, update

from app.database import SessionLocal
from app.models import Attempt, Delivery


def recover_delivery(delivery_id: UUID) -> bool:
    """завершаем зависшую попытку после истечения срока захвата"""
    with SessionLocal() as db:
        # блокируем строку на время проверки и смены статуса
        delivery = db.get(Delivery, delivery_id, with_for_update=True)
        if delivery is None or delivery.status != "processing":
            return False
        now = db.scalar(select(func.clock_timestamp()))
        if delivery.lease_until is not None and delivery.lease_until > now:
            return False

        db.execute(
            update(Attempt)
            .where(
                Attempt.delivery_id == delivery_id,
                Attempt.finished_at.is_(None),
            )
            .values(finished_at=now, error_kind="lease_expired")
        )
        delivery.status = "failed"
        delivery.lease_token = None
        delivery.lease_until = None
        delivery.next_attempt_at = None
        db.commit()
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Recover one expired webhook delivery")
    parser.add_argument("delivery_id", type=UUID, help="Delivery UUID")
    args = parser.parse_args()
    recovered = recover_delivery(args.delivery_id)
    print("recovered" if recovered else "skipped")


if __name__ == "__main__":
    main()
