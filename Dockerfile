FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.3 /uv /bin/uv

WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./

RUN useradd --create-home app
USER app

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
