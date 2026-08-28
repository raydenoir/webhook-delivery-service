# Webhook Service

HTTP API сервиса webhook-уведомлений на FastAPI.

## Локальный запуск

Сервис использует Python 3.13 и PostgreSQL 17. Окружением и зависимостями
управляет uv. Для запуска БД требуется Docker Compose.
Команды выполняются из корня проекта.

```powershell
uv venv --python 3.13
uv sync --locked
Copy-Item .env.example .env
docker compose up -d --wait
uv run uvicorn app.main:app --reload
```

Документация API доступна по адресу http://127.0.0.1:8000/docs.

Адрес БД задается переменной `DATABASE_URL` в `.env` или в окружении процесса.
Переменная окружения имеет приоритет. Значения в `.env.example` и `compose.yaml`
предназначены для локального запуска. Данные PostgreSQL хранятся в Docker volume.

Команда `docker compose stop` останавливает БД с сохранением данных.

## Проверка состояния

```powershell
curl.exe http://127.0.0.1:8000/health
```

Эндпоинт `/health` возвращает HTTP 200 и показывает, что API отвечает на запросы.

```json
{"status": "ok"}
```

Эндпоинт `/ready` проверяет подключение к PostgreSQL запросом `SELECT 1`.
При доступной БД возвращает HTTP 200.

```json
{"status": "ok", "database": "ok"}
```

При недоступной БД возвращает HTTP 503. Эндпоинт `/health` при этом продолжает
отвечать HTTP 200.

```json
{"status": "error", "database": "unavailable"}
```

## Проверка кода

```powershell
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Для тестов требуется запущенный PostgreSQL и настроенный `DATABASE_URL`.
