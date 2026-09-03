from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.deliveries import router as deliveries_router
from app.events import router as events_router
from app.subscriptions import router as subscriptions_router

app = FastAPI(title="Webhook Service")
app.include_router(subscriptions_router)
app.include_router(events_router)
app.include_router(deliveries_router)


@app.get("/health", summary="Проверка API")
async def health() -> dict[str, str]:
    """проверяем ответ API без обращения к БД"""
    return {"status": "ok"}


@app.get(
    "/ready",
    summary="Проверка подключения к БД",
    responses={503: {"description": "База данных недоступна"}},
)
def ready(db: Session = Depends(get_db)) -> JSONResponse:
    """проверяем PostgreSQL запросом SELECT 1, при ошибке возвращаем HTTP 503"""
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "database": "unavailable"},
        )
    return JSONResponse(content={"status": "ok", "database": "ok"})
