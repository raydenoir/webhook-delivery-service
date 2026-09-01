import json
from hashlib import sha256
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DataError
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.database import get_db
from app.models import Event
from app.schemas import EventCreate, EventRead

MAX_EVENT_SIZE = 64 * 1024

router = APIRouter(
    prefix="/v1/events",
    tags=["events"],
    dependencies=[Depends(require_api_key)],
    responses={401: {"description": "Отсутствующий или неверный API-ключ"}},
)


@router.post(
    "",
    response_model=EventRead,
    status_code=202,
    summary="Прием события",
    responses={
        409: {"description": "Ключ уже использован для другого события"},
        413: {"description": "Нормализованное тело события превышает 64 КиБ в UTF-8"},
        422: {"description": "Некорректное тело события или заголовок запроса"},
    },
)
def create_event(
    data: EventCreate,
    response: Response,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=200,
        pattern=r"^[!-~]+$",
        description="Уникальный ключ запроса из печатных ASCII-символов без пробелов",
        examples=["order-1842-paid-v1"],
    ),
    db: Session = Depends(get_db),
) -> Event:
    """сохраняем событие в PostgreSQL и возвращаем HTTP 202

    при повторе с тем же ключом и содержимым возвращаем прежнее событие.
    игнорируем отступы и порядок полей JSON-объектов при сравнении.
    при изменении типа или данных возвращаем HTTP 409.
    храним ключ вместе с событием, проверяем его уникальность во всем сервисе.
    в заголовке Location возвращаем путь к сохраненному событию.
    """
    try:
        body = json.dumps(
            data.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except ValueError:
        raise HTTPException(
            status_code=422, detail="Event must contain valid JSON"
        ) from None

    if len(body) > MAX_EVENT_SIZE:
        raise HTTPException(status_code=413, detail="Event exceeds 64 KiB")
    request_hash = sha256(body).hexdigest()

    # оставляем выбор победителя уникальному ограничению в базе
    statement = (
        insert(Event)
        .values(
            type=data.type,
            data=data.data,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
        .returning(Event)
    )
    try:
        event = db.scalar(statement)
    except DataError:
        db.rollback()
        raise HTTPException(
            status_code=422, detail="Event data cannot be stored as JSON"
        ) from None

    if event is None:
        event = db.scalars(
            select(Event).where(Event.idempotency_key == idempotency_key)
        ).one()
        if event.request_hash != request_hash:
            raise HTTPException(
                status_code=409, detail="Idempotency key is used for a different event"
            )

    db.commit()
    db.refresh(event)
    response.headers["Location"] = f"/v1/events/{event.id}"
    return event


@router.get(
    "/{event_id}",
    response_model=EventRead,
    summary="Получение события",
    responses={404: {"description": "Событие не найдено"}},
)
def get_event(event_id: UUID, db: Session = Depends(get_db)) -> Event:
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return event
