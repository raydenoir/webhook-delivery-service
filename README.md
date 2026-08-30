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
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Документация API доступна по адресу http://127.0.0.1:8000/docs.

Адрес БД задается переменной `DATABASE_URL` в `.env` или в окружении процесса.
Переменная окружения имеет приоритет. Значения в `.env.example` и `compose.yaml`
предназначены для локального запуска. Данные PostgreSQL хранятся в Docker volume.

Команда `docker compose stop` останавливает БД с сохранением данных.

## Подписки

Подписка связывает тип события с HTTPS-адресом получателя.

| Метод | Маршрут | Действие |
|---|---|---|
| POST | `/v1/subscriptions` | Создание подписки |
| GET | `/v1/subscriptions` | Список подписок |
| GET | `/v1/subscriptions/{id}` | Получение подписки |
| PATCH | `/v1/subscriptions/{id}` | Включение или отключение подписки |

Маршруты подписок требуют заголовок `Authorization: Bearer <API_KEY>`.
Ключ задается в `.env` или в окружении процесса и дает доступ ко всем подпискам
сервиса. Без корректного ключа API возвращает HTTP 401.

Хост получателя должен точно совпадать с одним из значений `ALLOWED_WEBHOOK_HOSTS`.
Список задается JSON-массивом, например `["example.com", "hooks.example.com"]`.
URL с логином, паролем или фрагментом не принимаются.

Тип события содержит строчные латинские буквы, цифры, точки, дефисы и символы
подчеркивания, начинается с буквы и ограничен 100 символами.

Пример создания подписки с локальными настройками из `.env.example`.

```powershell
$url = "http://127.0.0.1:8000/v1/subscriptions"
$headers = @{ Authorization = "Bearer local-development-key" }
$body = @{
    event_type = "order.paid"
    url = "https://example.com/webhooks"
} | ConvertTo-Json

$subscription = Invoke-RestMethod -Method Post -Uri $url -Headers $headers -ContentType "application/json" -Body $body
```

При создании API возвращает HTTP 201, UUID подписки, тип события, URL,
признак `enabled` и время создания. Новая подписка включена по умолчанию.

Список возвращается с параметрами `limit` и `offset`. По умолчанию `limit` равен
50, максимальное значение 100. `offset` начинается с нуля.
Подписки отсортированы по времени создания и UUID.

Для отключения подписки используется PATCH с телом `{"enabled": false}`.
Значение `true` включает ее обратно. Запись сохраняется в БД.
Запрос к отсутствующей подписке возвращает HTTP 404, некорректные данные HTTP 422.

## События

`POST /v1/events` сохраняет событие в PostgreSQL и возвращает HTTP 202.
Тело запроса содержит `type` и `data`. Для `type` действуют те же ограничения,
что и для типа события в подписке. `data` содержит JSON-объект с произвольными
вложенными значениями.

Запрос требует заголовки `Authorization: Bearer <API_KEY>` и `Idempotency-Key`.
Ключ идемпотентности содержит от 1 до 200 печатных ASCII-символов без пробелов.
Он уникален для всего сервиса и хранится вместе с событием.

Повтор запроса с тем же ключом и содержимым возвращает HTTP 202 и прежнее событие.
Отступы и порядок полей JSON-объектов не влияют на сравнение.
Если тип события или данные отличаются, API возвращает HTTP 409.
Исходное событие остается неизменным. Разные ключи создают отдельные события,
даже если их содержимое одинаковое.

Максимальный размер нормализованного тела события составляет 64 КиБ в UTF-8.
При превышении API возвращает HTTP 413, при некорректных данных HTTP 422.

Пример запроса с локальными настройками.

```powershell
$url = "http://127.0.0.1:8000/v1/events"
$headers = @{
    Authorization = "Bearer local-development-key"
    "Idempotency-Key" = "order-1842-paid-v1"
}
$body = @{
    type = "order.paid"
    data = @{ order_id = "1842" }
} | ConvertTo-Json

$event = Invoke-RestMethod -Method Post -Uri $url -Headers $headers -ContentType "application/json" -Body $body
```

Ответ содержит UUID события, тип, данные и время создания.
Заголовок `Location` указывает на `/v1/events/{id}`.
HTTP 202 подтверждает сохранение события в БД.

`GET /v1/events/{id}` возвращает сохраненное событие и требует API-ключ.
Для отсутствующего события API возвращает HTTP 404.

## Миграции БД

Схема БД управляется Alembic. Команда `uv run alembic upgrade head` применяет
миграции, а `uv run alembic current` показывает текущую версию схемы.

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

Для тестов требуется запущенный PostgreSQL с примененными миграциями и настройки
из `.env`. Обычные тесты API выполняются в транзакциях с откатом изменений.
Конкурентные тесты событий используют отдельные соединения и удаляют созданные
ими события после проверки.
