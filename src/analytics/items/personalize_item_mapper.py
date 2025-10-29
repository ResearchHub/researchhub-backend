"""
Functional mapper for converting ResearchhubUnifiedDocument to AWS Personalize items.
"""

from typing import Dict, Optional

from analytics.constants.personalize_constants import (
    AUTHOR_IDS,
    BLUESKY_COUNT_TOTAL,
    BOUNTY_HAS_SOLUTIONS,
    CITATION_COUNT_TOTAL,
    CREATION_TIMESTAMP,
    CSV_HEADERS,
    DELIMITER,
    HAS_ACTIVE_BOUNTY,
    HUB_IDS,
    HUB_L1,
    HUB_L2,
    ITEM_ID,
    ITEM_TYPE,
    PROPOSAL_HAS_FUNDERS,
    PROPOSAL_IS_OPEN,
    RFP_HAS_APPLICANTS,
    RFP_IS_OPEN,
    TEXT,
    TITLE,
    TWEET_COUNT_TOTAL,
    UPVOTE_SCORE,
)
from analytics.services.personalize_item_utils import clean_text_for_csv, get_author_ids
from analytics.services.personalize_utils import datetime_to_epoch_seconds


def map_to_item(
    unified_doc,
    bounty_data: dict,
    proposal_data: dict,
    rfp_data: dict,
) -> Dict[str, Optional[str]]:
    """
    Map a ResearchhubUnifiedDocument to a Personalize item dictionary.

    Args:
        unified_doc: ResearchhubUnifiedDocument instance (with prefetched relations)
        bounty_data: Dict with has_active_bounty and has_solutions flags
        proposal_data: Dict with is_open and has_funders flags
        rfp_data: Dict with is_open and has_applicants flags

    Returns:
        Dictionary with keys matching CSV_HEADERS
    """
    # Initialize row with None values
    row = {header: None for header in CSV_HEADERS}

    # Get the concrete document
    try:
        document = unified_doc.get_document()
    except Exception:
        # If we can't get the document, return minimal row
        row[ITEM_ID] = str(unified_doc.id)
        row[ITEM_TYPE] = unified_doc.document_type
        return row

    # Map common fields
    row.update(_map_common_fields(unified_doc, document))

    # Map document-type-specific fields
    if unified_doc.document_type == "PAPER":
        row.update(_map_paper_fields(unified_doc, document))
    else:
        row.update(_map_post_fields(unified_doc, document))

    # Add batch-fetched metrics
    row.update(
        {
            HAS_ACTIVE_BOUNTY: bounty_data.get("has_active_bounty", False),
            BOUNTY_HAS_SOLUTIONS: bounty_data.get("has_solutions", False),
            PROPOSAL_IS_OPEN: proposal_data.get("is_open", False),
            PROPOSAL_HAS_FUNDERS: proposal_data.get("has_funders", False),
            RFP_IS_OPEN: rfp_data.get("is_open", False),
            RFP_HAS_APPLICANTS: rfp_data.get("has_applicants", False),
        }
    )

    return row


def _map_common_fields(unified_doc, document) -> dict:
    """Map fields common to all document types."""
    from hub.models import Hub

    # Timestamp
    if (
        unified_doc.document_type == "PAPER"
        and hasattr(document, "paper_publish_date")
        and document.paper_publish_date
    ):
        timestamp = datetime_to_epoch_seconds(document.paper_publish_date)
    else:
        timestamp = datetime_to_epoch_seconds(unified_doc.created_date)

    # Hub processing
    hub_ids = []
    hub_l1 = None
    hub_l2 = None

    for hub in unified_doc.hubs.all():
        hub_ids.append(str(hub.id))
        if hub.namespace == Hub.Namespace.CATEGORY:
            hub_l1 = str(hub.id)
        elif hub.namespace == Hub.Namespace.SUBCATEGORY:
            hub_l2 = str(hub.id)

    return {
        ITEM_ID: str(unified_doc.id),
        ITEM_TYPE: unified_doc.document_type,
        CREATION_TIMESTAMP: timestamp,
        UPVOTE_SCORE: unified_doc.score,
        HUB_L1: hub_l1,
        HUB_L2: hub_l2,
        HUB_IDS: DELIMITER.join(hub_ids) if hub_ids else None,
        AUTHOR_IDS: get_author_ids(unified_doc, document),
    }


def _map_paper_fields(unified_doc, paper) -> dict:
    """Map paper-specific fields."""
    title = paper.paper_title or paper.title or ""
    abstract = paper.abstract or ""
    hub_names = unified_doc.get_hub_names()

    text_concat = f"{title} {abstract} {hub_names}"

    fields = {
        TITLE: clean_text_for_csv(title),
        TEXT: clean_text_for_csv(text_concat),
        CITATION_COUNT_TOTAL: paper.citations,
    }

    if paper.external_metadata:
        metrics = paper.external_metadata.get("metrics", {})
        fields[BLUESKY_COUNT_TOTAL] = metrics.get("bluesky_count", 0)
        fields[TWEET_COUNT_TOTAL] = metrics.get("twitter_count", 0)

    return fields


def _map_post_fields(unified_doc, post) -> dict:
    """Map post-specific fields."""
    title = post.title or ""
    renderable_text = post.renderable_text or ""
    hub_names = unified_doc.get_hub_names()

    text_concat = f"{title} {renderable_text} {hub_names}"

    return {
        TITLE: clean_text_for_csv(title),
        TEXT: clean_text_for_csv(text_concat),
    }
