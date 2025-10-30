"""
Functional mapper for converting ResearchhubUnifiedDocument to AWS Personalize items.
"""

from typing import Dict, Optional, Protocol, runtime_checkable

from analytics.constants.personalize_constants import (
    AUTHOR_IDS,
    BLUESKY_COUNT_TOTAL,
    BOUNTY_HAS_SOLUTIONS,
    CITATION_COUNT_TOTAL,
    CREATION_TIMESTAMP,
    DELIMITER,
    FIELD_DEFAULTS,
    HAS_ACTIVE_BOUNTY,
    HUB_IDS,
    HUB_L1,
    HUB_L2,
    ITEM_ID,
    ITEM_TYPE,
    ITEM_TYPE_MAPPING,
    PEER_REVIEW_COUNT_TOTAL,
    PROPOSAL_HAS_FUNDERS,
    PROPOSAL_IS_OPEN,
    RFP_HAS_APPLICANTS,
    RFP_IS_OPEN,
    TEXT,
    TITLE,
    TWEET_COUNT_TOTAL,
    UPVOTE_SCORE,
)
from analytics.utils.personalize_item_utils import clean_text_for_csv
from utils.time import datetime_to_epoch_seconds


@runtime_checkable
class PrefetchedUnifiedDocument(Protocol):
    """
    UnifiedDocument with required prefetched relations.

    Required prefetch_related:
    - hubs
    - grants, grants__contacts__author_profile
    - fundraises, related_bounties
    - paper__authorships__author
    - posts__authors
    """

    id: int
    document_type: str
    score: int


def map_to_item(
    prefetched_doc: PrefetchedUnifiedDocument,
    bounty_data: dict,
    proposal_data: dict,
    rfp_data: dict,
    review_count_data: dict,
) -> Dict[str, Optional[str]]:
    """
    Map a prefetched ResearchhubUnifiedDocument to a Personalize item dictionary.

    Args:
        prefetched_doc: UnifiedDocument with prefetched relations
        bounty_data: Dict with has_active_bounty and has_solutions flags
        proposal_data: Dict with is_open and has_funders flags
        rfp_data: Dict with is_open and has_applicants flags
        review_count_data: Dict mapping doc_id to review count

    Returns:
        Dictionary with keys matching CSV_HEADERS
    """
    # Initialize row with default values from constants
    row = {field: default for field, default in FIELD_DEFAULTS.items()}

    # Get the concrete document
    try:
        document = prefetched_doc.get_document()
    except Exception:
        # If we can't get the document, return minimal row
        row[ITEM_ID] = str(prefetched_doc.id)
        row[ITEM_TYPE] = prefetched_doc.document_type
        return row

    # Map common fields
    row.update(_map_common_fields(prefetched_doc, document))

    # Map document-type-specific fields
    if prefetched_doc.document_type == "PAPER":
        row.update(_map_paper_fields(prefetched_doc, document))
    else:
        row.update(_map_post_fields(prefetched_doc, document))

    # Add batch-fetched metrics
    row.update(
        {
            HAS_ACTIVE_BOUNTY: bounty_data.get("has_active_bounty", False),
            BOUNTY_HAS_SOLUTIONS: bounty_data.get("has_solutions", False),
            PROPOSAL_IS_OPEN: proposal_data.get("is_open", False),
            PROPOSAL_HAS_FUNDERS: proposal_data.get("has_funders", False),
            RFP_IS_OPEN: rfp_data.get("is_open", False),
            RFP_HAS_APPLICANTS: rfp_data.get("has_applicants", False),
            PEER_REVIEW_COUNT_TOTAL: review_count_data.get(prefetched_doc.id, 0),
        }
    )

    return row


def _map_common_fields(prefetched_doc: PrefetchedUnifiedDocument, document) -> dict:
    """Map fields common to all document types using prefetched data."""
    from hub.models import Hub

    # Timestamp
    if (
        prefetched_doc.document_type == "PAPER"
        and hasattr(document, "paper_publish_date")
        and document.paper_publish_date
    ):
        timestamp = datetime_to_epoch_seconds(document.paper_publish_date)
    else:
        timestamp = datetime_to_epoch_seconds(prefetched_doc.created_date)

    # Hub processing
    hub_ids = []
    hub_l1 = None
    hub_l2 = None

    for hub in prefetched_doc.hubs.all():
        hub_ids.append(str(hub.id))
        if hub.namespace == Hub.Namespace.CATEGORY:
            hub_l1 = str(hub.id)
        elif hub.namespace == Hub.Namespace.SUBCATEGORY:
            hub_l2 = str(hub.id)

    # Author extraction (using prefetched data only)
    author_ids = []

    if prefetched_doc.document_type == "GRANT":
        grant = prefetched_doc.grants.first()
        if grant:
            for contact in grant.contacts.all():
                if hasattr(contact, "author_profile") and contact.author_profile:
                    author_ids.append(str(contact.author_profile.id))

    elif prefetched_doc.document_type == "PAPER":
        for authorship in document.authorships.all():
            if authorship.author:
                author_ids.append(str(authorship.author.id))

    else:
        for author in document.authors.all():
            author_ids.append(str(author.id))

    return {
        ITEM_ID: str(prefetched_doc.id),
        ITEM_TYPE: ITEM_TYPE_MAPPING.get(
            prefetched_doc.document_type, prefetched_doc.document_type
        ),
        CREATION_TIMESTAMP: timestamp,
        UPVOTE_SCORE: prefetched_doc.score if prefetched_doc.score is not None else 0,
        HUB_L1: hub_l1,
        HUB_L2: hub_l2,
        HUB_IDS: DELIMITER.join(hub_ids) if hub_ids else None,
        AUTHOR_IDS: DELIMITER.join(author_ids) if author_ids else None,
    }


def _map_paper_fields(prefetched_doc: PrefetchedUnifiedDocument, paper) -> dict:
    """Map paper-specific fields."""
    title = paper.paper_title or paper.title or ""
    abstract = paper.abstract or ""
    hub_names = prefetched_doc.get_hub_names()

    text_concat = f"{title} {abstract} {hub_names}"

    fields = {
        TITLE: clean_text_for_csv(title),
        TEXT: clean_text_for_csv(text_concat),
        CITATION_COUNT_TOTAL: paper.citations if paper.citations is not None else 0,
    }

    if paper.external_metadata:
        metrics = paper.external_metadata.get("metrics", {})
        fields[BLUESKY_COUNT_TOTAL] = metrics.get("bluesky_count", 0)
        fields[TWEET_COUNT_TOTAL] = metrics.get("twitter_count", 0)

    return fields


def _map_post_fields(prefetched_doc: PrefetchedUnifiedDocument, post) -> dict:
    """Map post-specific fields."""
    title = post.title or ""
    renderable_text = post.renderable_text or ""
    hub_names = prefetched_doc.get_hub_names()

    text_concat = f"{title} {renderable_text} {hub_names}"

    return {
        TITLE: clean_text_for_csv(title),
        TEXT: clean_text_for_csv(text_concat),
    }
