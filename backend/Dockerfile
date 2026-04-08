FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY backend ./backend
COPY app ./app

RUN pip install --no-cache-dir -U pip setuptools wheel && \
    pip install --no-cache-dir -e .

EXPOSE 8000

ENV APP_ENV=production \
    TRADING_MODE=paper \
    LIVE_TRADING=false \
    LIVE_TRADING_ENABLED=false \
    LIVE_TRADING_CONFIRM=false \
    LIVE_TRADING_EXTRA_CONFIRM=false

CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]

