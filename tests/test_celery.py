import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Attempt, Delivery, Event
from app.recovery import recover_delivery
from app.tasks import celery_app, deliver_webhook

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        sys.platform != "linux" or os.environ.get("RUN_INTEGRATION_TESTS") != "1",
        reason="requires Linux and RUN_INTEGRATION_TESTS=1",
    ),
]


def stop_worker(process: subprocess.Popen) -> None:
    # завершаем только созданную нами группу процессов вместе с prefork-пулом
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=5)


def wait_for_status(delivery_id: UUID, status: str) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        with SessionLocal() as db:
            if db.get(Delivery, delivery_id).status == status:
                return
        time.sleep(0.1)
    raise AssertionError(f"Delivery {delivery_id} did not reach {status}")


def wait_for_task(task_id: str, results: Path) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        path = results / task_id
        if path.exists() and path.read_text() == "SUCCESS":
            return
        time.sleep(0.1)
    raise AssertionError(f"Task {task_id} did not finish successfully")


@pytest.fixture
def worker(tmp_path):
    queue = "test-" + uuid4().hex
    processes = []

    def start(concurrency: int = 1) -> subprocess.Popen:
        with (tmp_path / f"worker-{len(processes)}.log").open("w") as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "celery",
                    "-A",
                    "tests.celery_app:celery_app",
                    "worker",
                    "--pool=prefork",
                    f"--concurrency={concurrency}",
                    "--loglevel=INFO",
                    "-Q",
                    queue,
                    "--hostname=" + queue,
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env={**os.environ, "CELERY_TEST_RESULTS": str(tmp_path)},
            )
        processes.append(process)
        return process

    try:
        yield queue, start
    finally:
        for process in processes:
            stop_worker(process)
        with celery_app.connection_for_write() as connection:
            connection.channel().queue_delete(queue=queue)
        for path in tmp_path.glob("worker-*.log"):
            print(path.read_text()[-5000:])


def test_restart_and_duplicate_tasks(
    queued_delivery: tuple[UUID, UUID], worker, tmp_path
) -> None:
    delivery_id, event_id = queued_delivery
    queue, start = worker
    with SessionLocal() as db:
        db.get(Event, event_id).data = {"wait": True}
        db.commit()
    process = start(concurrency=2)
    original = deliver_webhook.apply_async(args=[str(delivery_id)], queue=queue)
    wait_for_status(delivery_id, "processing")
    stop_worker(process)

    with SessionLocal() as db:
        db.get(Delivery, delivery_id).lease_until = datetime.now(
            timezone.utc
        ) - timedelta(seconds=1)
        db.get(Event, event_id).data = {"wait": False}
        db.commit()
    assert recover_delivery(delivery_id)
    with SessionLocal() as db:
        db.get(Delivery, delivery_id).next_attempt_at = datetime.now(
            timezone.utc
        ) - timedelta(seconds=1)
        db.commit()

    # запускаем настоящий worker снова и отправляем две одинаковые задачи
    start(concurrency=2)
    task_ids = [original.id]
    for _ in range(2):
        task = deliver_webhook.apply_async(args=[str(delivery_id)], queue=queue)
        task_ids.append(task.id)
    # дожидаемся всех дублей и повторно полученной задачи перед проверкой истории
    for task_id in task_ids:
        wait_for_task(task_id, tmp_path)
    wait_for_status(delivery_id, "succeeded")
    with SessionLocal() as db:
        attempts = list(
            db.scalars(
                select(Attempt)
                .where(Attempt.delivery_id == delivery_id)
                .order_by(Attempt.started_at)
            )
        )
        assert len(attempts) == 2
        assert attempts[0].error_kind == "lease_expired"
        assert attempts[1].http_status == 204


def test_time_limit_frees_worker_slot(
    queued_delivery: tuple[UUID, UUID], worker
) -> None:
    delivery_id, event_id = queued_delivery
    queue, start = worker
    second_id = uuid4()
    with SessionLocal() as db:
        db.get(Event, event_id).data = {"wait": True}
        event = Event(
            type="sender.test",
            data={},
            idempotency_key=uuid4().hex,
            request_hash="a" * 64,
        )
        db.add(event)
        db.flush()
        db.add(
            Delivery(
                id=second_id,
                event_id=event.id,
                subscription_id=db.get(Delivery, delivery_id).subscription_id,
                url="https://example.com/webhook",
            )
        )
        db.commit()

    start()
    deliver_webhook.apply_async(
        args=[str(delivery_id)], queue=queue, soft_time_limit=1, time_limit=2
    )
    wait_for_status(delivery_id, "processing")
    deliver_webhook.apply_async(args=[str(second_id)], queue=queue)
    wait_for_status(second_id, "succeeded")
    with SessionLocal() as db:
        assert db.get(Delivery, delivery_id).status == "processing"
        assert db.get(Delivery, second_id).attempt_count == 1
