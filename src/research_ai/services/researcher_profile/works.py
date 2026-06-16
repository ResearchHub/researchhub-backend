"""Fetch and select the expert's papers for the profile.

These works seed proposal generation, so we only keep papers we can actually
read: open-access works that expose a full-text PDF. Selection keeps the
``MAX_WORKS`` papers with first/last authorship outranking middle, then recency.
"""

import logging

from research_ai.services.researcher_profile.resolver import AuthorResolution
from utils.openalex import OpenAlex, Work

logger = logging.getLogger(__name__)

MAX_WORKS = 5  # papers kept on the profile (first/last author, then recency)
_WORKS_PAGE_SIZE = 50  # recent-works window fetched from OpenAlex before selection


def _select_works(works: list[Work]) -> list[Work]:
    """Drop PDF-less papers, rank by lead-authorship then recency, dedup, cap."""
    readable = [work for work in works if work.pdf_url]

    def rank(work: Work) -> tuple[bool, str]:
        return (work.is_lead_author, work.publication_date)

    ranked = sorted(readable, key=rank, reverse=True)

    deduped: list[Work] = []
    seen: set[tuple[str, str]] = set()
    for work in ranked:
        key = (work.title.lower(), work.publication_year)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(work)

    return deduped[:MAX_WORKS]


def collect_works(
    resolution: AuthorResolution, *, oa_client: OpenAlex
) -> tuple[list[Work], list[str]]:
    """Fetch and select the profile works for a resolved author.

    Best-effort: failures are returned as error strings, never raised.
    """
    if not resolution.openalex_author_id:
        return [], []
    try:
        works = oa_client.get_works_typed(
            openalex_author_id=resolution.openalex_author_id,
            batch_size=_WORKS_PAGE_SIZE,
            sort="publication_date:desc",
            open_access_only=True,
        )
    except Exception as exc:  # noqa: BLE001 - works listing is best-effort
        logger.info("OpenAlex works fetch failed: %s", exc)
        return [], [f"openalex-works: {exc}"]
    return _select_works(works), []
