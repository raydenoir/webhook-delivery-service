import json
import os
import time
from pathlib import Path

import httpx2 as httpx
from billiard.exceptions import SoftTimeLimitExceeded
from celery.signals import task_postrun

from app.tasks import celery_app  # noqa: F401

original_client = httpx.Client


@task_postrun.connect
def record_task_result(task_id, state, **kwargs):
    # отмечаем завершение задачи после выполнения ее кода
    (Path(os.environ["CELERY_TEST_RESULTS"]) / task_id).write_text(state)


def handle(request: httpx.Request) -> httpx.Response:
    if json.loads(request.content)["data"].get("wait"):
        # игнорируем мягкое прерывание, чтобы проверить жесткий предел задачи
        try:
            time.sleep(120)
        except SoftTimeLimitExceeded:
            time.sleep(120)
    return httpx.Response(204)


def make_client(**kwargs) -> httpx.Client:
    return original_client(transport=httpx.MockTransport(handle), **kwargs)


# подменяем только получателя, оставляем настоящие Celery и RabbitMQ
httpx.Client = make_client
