# Webhook Service

HTTP API сервиса webhook-уведомлений на FastAPI.

## Локальный запуск

Сервис использует Python 3.13. Окружением и зависимостями управляет uv.
Команды выполняются из корня проекта.

```powershell
uv venv --python 3.13
uv sync --locked
uv run uvicorn app.main:app --reload
```

Документация API доступна по адресу http://127.0.0.1:8000/docs.

## Проверка состояния

```powershell
curl.exe http://127.0.0.1:8000/health
```

Эндпоинт `/health` возвращает HTTP 200 и показывает, что API отвечает на запросы.

```json
{"status": "ok"}
```

## Проверка кода

```powershell
uv run ruff check .
uv run ruff format --check .
```
