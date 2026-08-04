---
feature: communications-and-webhooks
area: backend/communications
created: 2026-08-04
last_updated: 2026-08-04
---

# Communications and Webhooks

## Overview

Communications deliver transactional account, payment, moderation, and research-workflow messages while honoring recipient preferences. The backend also receives provider callbacks for email, analytics, payment, identity verification, and wallet events.

## Architecture

Email behavior spans `mailing_list`, `notification`, and domain tasks that trigger delivery after an authoritative state change. `EmailUnsubscribeView` serves the public opt-out endpoint, while mailing-list delivery helpers construct recipient-specific unsubscribe URLs. Recent changes route signup, password-reset, purchase-receipt, hot-wallet-alert, and flagged-content notifications through the transactional-email path.

Inbound callbacks are composed at the top level under `/webhooks/`: SES, Amplitude, Circle, Persona, and Stripe each enter through a dedicated view. These handlers should verify provider authenticity, translate the payload into the owning domain model, and be safe to retry.

## Key Files

- `src/mailing_list/views.py` — email unsubscribe endpoint.
- `src/mailing_list/` — mailing-list preferences and delivery support.
- `src/notification/` — user notification data and APIs.
- `src/analytics/views/amplitude_webhook_view.py` — Amplitude callback ingestion.
- `src/purchase/circle/webhook.py` and `src/purchase/views/stripe_webhook_view.py` — payment callbacks.
- `src/user/views/persona_webhook_view.py` — identity-verification callback.
- `src/researchhub/urls.py` — public unsubscribe and webhook route registration.

## Change Guidance

- Generate opt-out links per recipient when a message can be unsubscribed from; do not reuse a generic link in bulk delivery.
- Trigger transactional messages from the domain transition that made them true, and make the send path retry-safe.
- Verify signatures or equivalent authenticity checks before processing every external callback.
- Keep provider event handling separate from presentation: persist/translate the event first, then schedule notifications or follow-up work.

## Keywords

email, transactional email, unsubscribe, mailing list, notification, SES, Stripe webhook, Circle webhook, Persona webhook, Amplitude webhook, delivery, opt-out
