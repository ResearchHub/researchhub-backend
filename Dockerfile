FROM ghcr.io/astral-sh/uv:0.12.1 AS uv

FROM python:3.13-slim-trixie AS builder

ENV UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app

COPY --from=uv /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./

RUN uv sync --frozen --no-dev --no-install-project --no-cache

FROM python:3.13-slim-trixie AS runtime

ENV APP_ENV=production \
    PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home --shell /usr/sbin/nologin app

WORKDIR /app/src

COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app src ./

RUN python manage.py collectstatic --noinput

USER app

EXPOSE 8000

CMD ["daphne", "--bind", "0.0.0.0", "--port", "8000", "researchhub.asgi:application"]
