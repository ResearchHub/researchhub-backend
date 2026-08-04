---
feature: scholarly-content
area: backend/content
created: 2026-08-04
last_updated: 2026-08-04
---

# Scholarly Content

## Overview

The content domain models research papers and ResearchHub-native publishing as related but distinct concepts. It supports paper versions, authorship, citations, figures, uploaded PDFs, posts, unified documents, registered-report drafts, peer review, and external source ingestion.

## Architecture

`paper` owns canonical paper records and their publication metadata. Its ingestion pipeline fetches preprints from source-specific clients, maps them into local data, records fetch status, and submits batches to Celery so ingestion does not block the scheduler.

`researchhub_document` provides the presentation layer shared by papers and native posts. `ResearchhubUnifiedDocument` and related models give feeds, discovery, reviews, and community features one content-facing reference. `review` and `researchhub_comment` attach review and discussion workflows to these documents.

Content is exposed through the main DRF router (`paper`, `researchhubpost`, and `researchhub_unified_document`) plus direct upload and registered-report draft endpoints. Recent API changes deliberately make feed and paper read paths read-only; preserve that boundary unless a new authoritative creation path is explicitly designed.

## Key Files

- `src/paper/related_models/paper_model.py` — paper, fetch-log, and figure models.
- `src/paper/related_models/paper_version.py` — paper versions and series metadata.
- `src/paper/ingestion/pipeline.py` — multi-source fetch orchestration and asynchronous batch processing.
- `src/paper/ingestion/clients/` — preprint and enrichment provider adapters.
- `src/researchhub_document/models.py` — public model exports for unified documents, posts, filters, featured content, and journeys.
- `src/researchhub_document/related_models/` — unified-document and post implementations.
- `src/review/` — review resources and availability endpoint.
- `src/researchhub/urls.py` — content routes, upload endpoints, and registered-report draft endpoint.

## Change Guidance

- Preserve paper identifiers, versions, DOI handling, and author metadata when changing ingestion or serialization; search, feeds, and citations consume them.
- Add a source client and mapper together. The pipeline expects normalized source data and records success/failure in `PaperFetchLog`.
- Consider unified-document behavior when introducing a new content type: feeds, comments, reviews, and search often operate on that abstraction rather than directly on `Paper`.
- Keep PDF upload and external ingestion validation separate from simple metadata changes.

## Keywords

papers, preprints, arXiv, bioRxiv, ChemRxiv, ingestion, DOI, citations, authorship, paper versions, unified documents, posts, registered reports, peer review, PDFs
