FROM mcr.microsoft.com/devcontainers/python:3.13-trixie

ENV PYTHONUNBUFFERED 1

# Remove Yarn apt source since the base image's signing key is stale.
RUN rm -f /etc/apt/sources.list.d/yarn.list \
    && apt-get update && export DEBIAN_FRONTEND=noninteractive \
    && apt-get -y install --no-install-recommends redis-tools

# Install uv and add to PATH
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
ENV PATH="/root/.local/bin:${PATH}"
