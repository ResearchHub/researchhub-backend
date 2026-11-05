FROM ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 AS uv

FROM python:3.14.9-slim-trixie@sha256:35caba83af2fe6da9a5d922f9b0156f21d1246a48278c58a08bd253303ba42e8 AS python-base

FROM python-base AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app

COPY --from=uv /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./

RUN uv sync --frozen --no-dev --no-install-project --no-cache

FROM python-base AS runtime

ENV APP_ENV=production \
    PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home --shell /usr/sbin/nologin app

WORKDIR /app/src

COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app src ./
COPY --chmod=755 docker/entrypoint.sh /usr/local/bin/entrypoint

RUN /usr/local/bin/python3 -m pip uninstall -y pip \
    && python -m compileall -q . \
    && python manage.py collectstatic --noinput

USER app

VOLUME ["/tmp"]

EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/entrypoint"]
CMD ["api"]
