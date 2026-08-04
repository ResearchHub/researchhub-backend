---
feature: core-api-platform
area: backend/platform
created: 2026-08-04
last_updated: 2026-08-04
---

# Core API Platform

## Overview

ResearchHub is a Django 5 REST backend. It exposes product APIs through Django REST Framework, combines token authentication with allauth/dj-rest-auth flows, and runs longer or scheduled work with Celery. The backend is deliberately split into domain Django apps rather than one central service layer.

## Architecture

`researchhub.urls` is the public composition root: it registers DRF viewsets for primary resources, includes feature-specific URL modules, and owns health, auth, uploads, checkout, and third-party webhook routes. `researchhub.settings` installs the domain apps and configures PostgreSQL, Redis-backed channels/cache, OpenSearch, storage, email, observability, and REST defaults.

Celery is the asynchronous boundary. `researchhub.celery` discovers app-local `tasks.py` files, defines named queues, and schedules recurring maintenance such as feed refreshes, payments, reputation recalculation, and user maintenance. Keep synchronous request handlers short; delegate provider calls, bulk updates, and periodic work to the appropriate task queue.

## Key Files

- `src/researchhub/urls.py` — top-level REST router, included feature routes, auth, webhooks, and health endpoint.
- `src/researchhub/settings.py` — installed apps and shared runtime configuration.
- `src/researchhub/celery.py` — Celery app, queue names, and periodic schedule.
- `src/researchhub/asgi.py` / `src/researchhub/wsgi.py` — ASGI and WSGI deployment entry points.
- `src/manage.py` — Django management entry point.
- `pyproject.toml` — Python version and dependency contract.

## Conventions

- Put data ownership, serializers, permissions, views, tasks, and tests in the relevant domain app.
- Add public API endpoints through the top-level router or an included URL module; avoid unregistered standalone views.
- Treat webhook endpoints as trust boundaries: validate provider payloads before changing domain state.
- Use migrations for persistent model changes and management commands for explicit repair or backfill work.
- Run local development with the container stack described in `README.md`; it supplies PostgreSQL, Redis, and OpenSearch.

## Keywords

Django, Django REST Framework, DRF, API router, authentication, allauth, Celery, Redis, PostgreSQL, OpenSearch, ASGI, webhooks, settings
