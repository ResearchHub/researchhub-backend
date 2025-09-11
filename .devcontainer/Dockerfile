FROM mcr.microsoft.com/devcontainers/python:1-3.13-bookworm

ENV PYTHONUNBUFFERED 1

RUN apt-get update && export DEBIAN_FRONTEND=noninteractive \
    && apt-get -y install --no-install-recommends redis-tools

# Install uv and add to PATH
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
ENV PATH="/root/.local/bin:${PATH}"

# Copy dependency files
WORKDIR /workspace
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen
