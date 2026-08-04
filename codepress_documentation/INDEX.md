# ResearchHub Backend Documentation

This directory records the durable feature boundaries and architectural conventions of the ResearchHub API. It is intended to help future maintainers find the owning code before changing a cross-cutting workflow.

## Feature Index

- [Core API Platform](./features/core-api-platform/README.md) — Django/DRF entry points, authentication, async work, and operational boundaries.
- [Scholarly Content](./features/scholarly-content/README.md) — papers, unified documents, posts, review, and external-paper ingestion.
- [Community and Moderation](./features/community-and-moderation/README.md) — users, author profiles, hubs, comments, voting, and safety controls.
- [Incentives and Payments](./features/incentives-and-payments/README.md) — ResearchCoin reputation, bounties, funding, payment providers, and wallet workflows.
- [Discovery and Personalization](./features/discovery-and-personalization/README.md) — OpenSearch, feeds, rankings, caching, and behavioral analytics.
- [AI Research Workflows](./features/ai-research-workflows/README.md) — expert discovery, generated outreach, proposal drafting, and AI peer review.
- [Communications and Webhooks](./features/communications-and-webhooks/README.md) — transactional delivery, opt-outs, notifications, and inbound provider callbacks.

## Repository Map

The application code lives in `src/`. `researchhub` is the Django project package; most product areas are Django apps with models, serializers, views, services, tasks, migrations, and tests nearby. Runtime dependencies include PostgreSQL, Redis, OpenSearch, Celery, Django Channels, AWS storage/email services, payment providers, and blockchain integrations.

The public REST surface begins in `src/researchhub/urls.py`. New product work generally belongs in the domain app that owns its data and behavior, then becomes reachable through that router or an included URL module.
