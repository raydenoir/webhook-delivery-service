from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.database import get_db
from app.models import Delivery, Event
from app.schemas import DeliveryRead

router = APIRouter(
    prefix="/v1",
    tags=["deliveries"],
    dependencies=[Depends(require_api_key)],
    responses={401: {"description": "Отсутствующий или неверный API-ключ"}},
)


@router.get(
    "/events/{event_id}/deliveries",
    response_model=list[DeliveryRead],
    summary="Доставки события",
    responses={404: {"description": "Событие не найдено"}},
)
def list_deliveries(
    event_id: UUID,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[Delivery]:
    """возвращаем доставки по времени создания и UUID

    фиксируем список получателей и их адреса при приеме события.
    для события без подходящих подписок возвращаем пустой список.
    при повторе события сохраняем прежний список доставок.
    """
    if db.get(Event, event_id) is None:
        raise HTTPException(status_code=404, detail="Event not found")
    query = (
        select(Delivery)
        .where(Delivery.event_id == event_id)
        .order_by(Delivery.created_at, Delivery.id)
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(query))


@router.get(
    "/deliveries/{delivery_id}",
    response_model=DeliveryRead,
    summary="Получение доставки",
    responses={404: {"description": "Доставка не найдена"}},
)
def get_delivery(delivery_id: UUID, db: Session = Depends(get_db)) -> Delivery:
    """возвращаем запись доставки со статусом и адресом получателя

    создаем новые доставки со статусом queued.
    """
    delivery = db.get(Delivery, delivery_id)
    if delivery is None:
        raise HTTPException(status_code=404, detail="Delivery not found")
    return delivery
