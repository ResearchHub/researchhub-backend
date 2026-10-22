FROM ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff AS uv

FROM python:3.14.8-slim-trixie@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170 AS python-base

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
