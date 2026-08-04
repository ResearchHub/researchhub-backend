---
feature: discovery-and-personalization
area: backend/discovery
created: 2026-08-04
last_updated: 2026-08-04
---

# Discovery and Personalization

## Overview

Discovery turns ResearchHub content and community activity into searchable and ranked experiences. It covers OpenSearch indexing and query construction, type-ahead suggestions, activity and content feeds, hot-score ranking, caching, personalized recommendations, and analytics event processing.

## Architecture

`search` defines OpenSearch document mappings for papers, posts, users, hubs, institutions, and journals. `UnifiedSearchService` queries paper and post indexes together, gives DOI lookups a direct path, applies relevance/newest ordering, and returns highlighted results. Index maintenance can be run through Django management commands.

`feed` stores `FeedEntry` records and serves read-only viewsets for popular, latest, following, funding, grant, journal, and moderator feeds. It owns filtering, ordering, hot-score calculation, and response caching. For personalized requests, `FeedViewSet` delegates recommendation selection to `personalize.services.feed_service` and exposes cache/source headers for observability.

`analytics` receives Amplitude callbacks and turns product events into interaction data and business-insight reports. It is an input to measurement and personalization, not the source of truth for content or account state.

## Key Files

- `src/search/documents/` — OpenSearch document definitions.
- `src/search/services/unified_search_service.py` — cross-index search, DOI path, pagination, highlighting, and failure handling.
- `src/search/services/unified_search_query_builder.py` — relevance and popularity query construction.
- `src/search/urls.py` — unified search, suggestions, journal, hub, and institution routes.
- `src/feed/models.py` — feed entries and hot-score breakdowns.
- `src/feed/views/feed_view.py` — read-only feed delivery, caching, and personalization handoff.
- `src/feed/hot_score.py` and `hot_score_breakdown.py` — ranking implementation.
- `src/personalize/services/feed_service.py` — recommendation integration used by personalized feeds.
- `src/analytics/views/amplitude_webhook_view.py` — inbound analytics webhook.

## Change Guidance

- Update the search document and reindex path when a searchable field changes; database changes alone do not update OpenSearch.
- Preserve `RH-Cache` and `RH-Feed-Source` behavior when changing feed delivery; clients and operations use these headers to diagnose served results.
- Keep recommendation fallback/caching behavior intact when modifying personalized feeds so external recommendation failures degrade safely.
- Revisit rankings, cache keys, and related feed tests together when changing feed eligibility or sort fields.

## Keywords

OpenSearch, search, index, DOI, autocomplete, suggestions, feed, personalization, recommendations, hot score, cache, ranking, Amplitude, analytics
