from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.database import get_db
from app.models import Subscription
from app.schemas import SubscriptionCreate, SubscriptionRead, SubscriptionUpdate

router = APIRouter(
    prefix="/v1/subscriptions",
    tags=["subscriptions"],
    dependencies=[Depends(require_api_key)],
)


@router.post("", response_model=SubscriptionRead, status_code=201)
def create_subscription(
    data: SubscriptionCreate, db: Session = Depends(get_db)
) -> Subscription:
    subscription = Subscription(event_type=data.event_type, url=str(data.url))
    db.add(subscription)
    db.commit()
    db.refresh(subscription)
    return subscription


@router.get("", response_model=list[SubscriptionRead])
def list_subscriptions(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[Subscription]:
    query = (
        select(Subscription)
        .order_by(Subscription.created_at, Subscription.id)
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(query))


@router.get("/{subscription_id}", response_model=SubscriptionRead)
def get_subscription(
    subscription_id: UUID, db: Session = Depends(get_db)
) -> Subscription:
    subscription = db.get(Subscription, subscription_id)
    if subscription is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return subscription


@router.patch("/{subscription_id}", response_model=SubscriptionRead)
def update_subscription(
    subscription_id: UUID,
    data: SubscriptionUpdate,
    db: Session = Depends(get_db),
) -> Subscription:
    subscription = db.get(Subscription, subscription_id)
    if subscription is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    subscription.enabled = data.enabled
    db.commit()
    db.refresh(subscription)
    return subscription
