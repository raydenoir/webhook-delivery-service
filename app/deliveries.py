from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.database import get_db
from app.models import Attempt, Delivery, DeliveryReplay, Event, Subscription
from app.schemas import AttemptRead, DeliveryRead

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
    при отправке меняем статус на processing, затем succeeded или failed.
    для временных ошибок возвращаем доставку в queued с next_attempt_at.
    выполняем до трех попыток с паузами 10 и 30 секунд.
    повторяем сетевые ошибки, таймауты и ответы 408, 429 и 5xx.
    в attempt_count показываем число попыток текущего цикла отправки.
    передаем POST с полями id, type и data события.
    в заголовке X-Webhook-Id передаем UUID доставки.
    если у подписки задан signing_secret, добавляем X-Webhook-Signature.
    передаем sha256= и шестнадцатеричный HMAC-SHA256 от исходных байтов тела.
    используем UTF-8 байты секрета в качестве ключа HMAC.
    на стороне получателя вычисляем подпись до разбора JSON.
    сравниваем ожидаемый заголовок с полученным через hmac.compare_digest.
    """
    delivery = db.get(Delivery, delivery_id)
    if delivery is None:
        raise HTTPException(status_code=404, detail="Delivery not found")
    return delivery


@router.get(
    "/deliveries/{delivery_id}/attempts",
    response_model=list[AttemptRead],
    summary="Попытки доставки",
    responses={404: {"description": "Доставка не найдена"}},
)
def list_attempts(
    delivery_id: UUID,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[Attempt]:
    """возвращаем попытки по времени начала и UUID

    сохраняем код HTTP и категорию ошибки без тела ответа получателя.
    считаем ответы 2xx успешными, остальные ответы отмечаем как http_error.
    не следуем перенаправлениям получателя.
    при таймауте записываем timeout, при сетевой ошибке network_error.
    при запрещенном адресе записываем configuration_error без HTTP-запроса.
    при восстановлении зависшей попытки записываем lease_expired.
    в таком случае не знаем, успел ли получатель обработать запрос.
    """
    if db.get(Delivery, delivery_id) is None:
        raise HTTPException(status_code=404, detail="Delivery not found")
    query = (
        select(Attempt)
        .where(Attempt.delivery_id == delivery_id)
        .order_by(Attempt.started_at, Attempt.id)
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(query))


@router.post(
    "/deliveries/{delivery_id}/replay",
    response_model=DeliveryRead,
    status_code=202,
    summary="Ручной повтор доставки",
    responses={
        404: {"description": "Доставка не найдена"},
        409: {"description": "Повтор недоступен для этого состояния или подписки"},
    },
)
def replay_delivery(
    delivery_id: UUID,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=200,
        pattern=r"^[!-~]+$",
        description="Ключ ручного повтора, уникальный в пределах доставки",
        examples=["manual-replay-1"],
    ),
    db: Session = Depends(get_db),
) -> Delivery:
    """возвращаем неудачную доставку в queued и сохраняем историю попыток

    принимаем новый ключ только для failed доставки с активной подпиской.
    при повторе принятого ключа возвращаем текущее состояние без изменений.
    сохраняем UUID доставки и заголовок X-Webhook-Id при следующей отправке.
    начинаем новый цикл попыток без удаления истории предыдущего.
    """
    # блокируем только эту доставку на время проверки и записи повтора
    delivery = db.get(Delivery, delivery_id, with_for_update=True)
    if delivery is None:
        raise HTTPException(status_code=404, detail="Delivery not found")

    replay = db.scalar(
        select(DeliveryReplay).where(
            DeliveryReplay.delivery_id == delivery_id,
            DeliveryReplay.idempotency_key == idempotency_key,
        )
    )
    if replay is None:
        if delivery.status != "failed":
            raise HTTPException(
                status_code=409, detail="Only failed deliveries can be replayed"
            )
        subscription = db.get(Subscription, delivery.subscription_id)
        if not subscription.enabled:
            raise HTTPException(status_code=409, detail="Subscription is disabled")
        delivery.status = "queued"
        delivery.attempt_count = 0
        delivery.next_attempt_at = func.clock_timestamp()
        db.add(DeliveryReplay(delivery_id=delivery_id, idempotency_key=idempotency_key))

    db.commit()
    db.refresh(delivery)
    return delivery
