from uuid import UUID

import httpx2 as httpx
from celery import Celery

from app.config import settings
from app.sender import send_delivery

celery_app = Celery("webhooks", broker=settings.broker_url)
celery_app.conf.update(
    task_default_queue="webhooks",
    task_serializer="json",
    accept_content=["json"],
    task_ignore_result=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    # задаем тип служебных очередей, совместимый с rabbitmq 4.4
    control_queue_durable=True,
    event_queue_exclusive=True,
    broker_connection_timeout=3,
    broker_transport_options={"confirm_publish": True},
    task_publish_retry=False,
)


@celery_app.task
def deliver_webhook(delivery_id: str) -> str:
    """получаем UUID из очереди и выполняем одну попытку доставки"""
    with httpx.Client(
        timeout=httpx.Timeout(10.0, connect=3.0),
        follow_redirects=False,
        trust_env=False,
    ) as client:
        return send_delivery(UUID(delivery_id), client)
