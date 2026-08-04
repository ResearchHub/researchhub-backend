---
feature: community-and-moderation
area: backend/community
created: 2026-08-04
last_updated: 2026-08-04
---

# Community and Moderation

## Overview

Community features establish researcher identity and organize participation around hubs and content. They include users and author profiles, institutions and organizations, follows, hub membership, comments, reactions, flags, editor/moderator tools, user verification, and risk scoring.

## Architecture

`user` is the identity hub: its custom `User` model and related author, organization, verification, follow, contribution, leaderboard, and risk-score records are reused throughout the application. `hub` groups people and content into research communities with membership and role semantics.

Legacy discussion reactions live in `discussion`; the newer `researchhub_comment` app provides generic, threaded comments that can attach to multiple model types through the nested comments route. Moderation touches several domains, so permissions, flag state, and asynchronous notifications should remain close to the model/action that owns them while using shared user and hub references.

## Key Files

- `src/user/related_models/user_model.py` — custom user model and account-level behavior.
- `src/user/related_models/author_model.py` — researcher profile data.
- `src/user/related_models/user_verification_model.py` and `risk_score_model.py` — trust and risk signals.
- `src/user/views/` — user, author, editor, moderator, and Persona webhook APIs.
- `src/hub/models.py` — hubs and membership relationships.
- `src/discussion/models.py` — votes, flags, and legacy generic reactions.
- `src/researchhub_comment/related_models/` — generic comment/thread entities.
- `src/researchhub_comment/views/rh_comment_view.py` — nested comment API.

## Change Guidance

- Use the custom user model and existing verification/role checks; do not introduce parallel identity state.
- A generic comment attachment requires both content-type compatibility and permission coverage for the target model.
- Preserve the distinction between moderation flags, user risk scoring, and content visibility. They are related signals, not interchangeable status fields.
- Review hub membership effects when changing content visibility, curation, or feed eligibility.

## Keywords

users, authors, profiles, hubs, memberships, follows, organizations, institutions, comments, threads, votes, flags, moderation, editor, verification, risk score
