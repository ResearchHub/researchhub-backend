---
feature: incentives-and-payments
area: backend/finance
created: 2026-08-04
last_updated: 2026-08-04
---

# Incentives and Payments

## Overview

ResearchHub’s incentive system combines ResearchCoin reputation accounting with real payment and funding workflows. It supports balances, purchases, deposits, withdrawals, distributions, bounties, staking yield, fundraising, grants, payment-provider records, and provider callbacks.

## Architecture

`reputation` owns ledger-like domain operations for scores, contributions, distributions, deposits, withdrawals, escrow, bounties, and staking. Its scheduled tasks recalculate reputation, inspect pending withdrawals, maintain staking snapshots/yield, and monitor the hot wallet.

`purchase` owns checkout- and provider-facing payment workflows: payment records, balances, wallets, purchases, exchange rates, fundraising, grants, and Circle/Stripe/Endaoment integrations. The public API is composed in `researchhub.urls`; provider callbacks enter through dedicated webhook routes. `ethereum` contains blockchain-specific support code.

## Key Files

- `src/reputation/related_models/score.py` — scores, score changes, and algorithm variables.
- `src/reputation/related_models/bounty.py` — bounties and solutions.
- `src/reputation/related_models/deposit.py`, `withdrawal.py`, and `distribution.py` — transfer lifecycle records.
- `src/reputation/distributor.py` and `distributions.py` — allocation/distribution logic.
- `src/purchase/related_models/payment_model.py` — payment processor and purpose records.
- `src/purchase/related_models/fundraise_model.py`, `grant_model.py`, and `grant_application_model.py` — research funding workflows.
- `src/purchase/circle/` and `src/purchase/endaoment/` — external provider clients, services, and callbacks.
- `docs/DEPOSIT_FLOW.md` and `docs/STAKING_YIELD_API.md` — focused existing operational references.

## Change Guidance

- Treat provider webhooks and scheduled payout jobs as idempotent state transitions. Avoid creating transfers solely from request retries.
- Reuse paid-status and balance models instead of storing payment completion state ad hoc.
- Check the corresponding scheduled task and provider callback whenever changing a payment, deposit, withdrawal, fundraise, or distribution lifecycle.
- Keep token/reputation policy separate from fiat-provider concerns, even when the customer-facing workflow combines them.

## Keywords

ResearchCoin, RSC, reputation, score, bounty, distribution, deposit, withdrawal, staking, balance, wallet, Stripe, Circle, Endaoment, payment, fundraise, grant
