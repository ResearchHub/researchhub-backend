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
from analytics.services.personalize_item_utils import (
    clean_text_for_csv,
    get_author_ids,
    get_bounty_metrics,
    get_hub_mapping,
    get_proposal_metrics,
    get_rfp_metrics,
)
from analytics.services.personalize_utils import datetime_to_epoch_seconds


def map_to_item(unified_doc) -> Dict[str, Optional[str]]:
    """
    Map a ResearchhubUnifiedDocument to a Personalize item dictionary.

    Args:
        unified_doc: ResearchhubUnifiedDocument instance

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
    _map_common_fields(row, unified_doc, document)

    # Map document-type-specific fields
    if unified_doc.document_type == "PAPER":
        _map_paper_fields(row, unified_doc, document)
    else:
        # Post types (DISCUSSION, GRANT, QUESTION, PREREGISTRATION)
        _map_post_fields(row, unified_doc, document)

    # Add optional metrics
    _add_optional_metrics(row, unified_doc)

    return row


def _map_common_fields(row: Dict, unified_doc, document) -> None:
    """
    Map fields common to all document types.

    Args:
        row: Row dictionary to update
        unified_doc: ResearchhubUnifiedDocument instance
        document: The concrete document (Paper or Post)
    """
    # Basic IDs
    row[ITEM_ID] = str(unified_doc.id)
    row[ITEM_TYPE] = unified_doc.document_type

    # Timestamp - use paper_publish_date for papers if available
    if (
        unified_doc.document_type == "PAPER"
        and hasattr(document, "paper_publish_date")
        and document.paper_publish_date
    ):
        timestamp = datetime_to_epoch_seconds(document.paper_publish_date)
    else:
        timestamp = datetime_to_epoch_seconds(unified_doc.created_date)
    row[CREATION_TIMESTAMP] = timestamp

    # Upvote score
    row[UPVOTE_SCORE] = unified_doc.score

    # Hub mapping
    hub_l1, hub_l2 = get_hub_mapping(unified_doc, document)
    row[HUB_L1] = hub_l1
    row[HUB_L2] = hub_l2

    # Hub IDs
    hub_ids = [str(hub.id) for hub in unified_doc.hubs.all()]
    row[HUB_IDS] = DELIMITER.join(hub_ids) if hub_ids else None

    # Author IDs
    row[AUTHOR_IDS] = get_author_ids(unified_doc, document)


def _map_paper_fields(row: Dict, unified_doc, paper) -> None:
    """
    Map paper-specific fields.

    Args:
        row: Row dictionary to update
        unified_doc: ResearchhubUnifiedDocument instance
        paper: Paper instance
    """
    # Get title and abstract
    title = paper.paper_title or paper.title or ""
    abstract = paper.abstract or ""

    # Get hub names for concatenation
    hub_names = unified_doc.get_hub_names()

    # TITLE field: just the title
    row[TITLE] = clean_text_for_csv(title)

    # TEXT field: title + abstract + hubs
    text_concat = f"{title} {abstract} {hub_names}"
    row[TEXT] = clean_text_for_csv(text_concat)

    # Citation count
    row[CITATION_COUNT_TOTAL] = paper.citations

    # Social metrics from external_metadata (Altmetric data)
    if paper.external_metadata:
        metadata = paper.external_metadata
        metrics = metadata.get("metrics", {})
        row[BLUESKY_COUNT_TOTAL] = metrics.get("bluesky_count", 0)
        row[TWEET_COUNT_TOTAL] = metrics.get("twitter_count", 0)


def _map_post_fields(row: Dict, unified_doc, post) -> None:
    """
    Map post-specific fields.

    Args:
        row: Row dictionary to update
        unified_doc: ResearchhubUnifiedDocument instance
        post: ResearchhubPost instance
    """
    # Get title and renderable_text
    title = post.title or ""
    renderable_text = post.renderable_text or ""

    # Get hub names for concatenation
    hub_names = unified_doc.get_hub_names()

    # TITLE field: just the title
    row[TITLE] = clean_text_for_csv(title)

    # TEXT field: title + renderable_text + hubs
    text_concat = f"{title} {renderable_text} {hub_names}"
    row[TEXT] = clean_text_for_csv(text_concat)


def _add_optional_metrics(row: Dict, unified_doc) -> None:
    """
    Add optional metrics (bounty, proposal, RFP, comments).

    Args:
        row: Row dictionary to update
        unified_doc: ResearchhubUnifiedDocument instance
    """
    # Bounty metrics (can apply to any document type)
    bounty_metrics = get_bounty_metrics(unified_doc)
    row[HAS_ACTIVE_BOUNTY] = bounty_metrics["HAS_ACTIVE_BOUNTY"]
    row[BOUNTY_HAS_SOLUTIONS] = bounty_metrics["BOUNTY_HAS_SOLUTIONS"]

    # Proposal metrics (for PREREGISTRATION type)
    if unified_doc.document_type == "PREREGISTRATION":
        proposal_metrics = get_proposal_metrics(unified_doc)
        row[PROPOSAL_IS_OPEN] = proposal_metrics["PROPOSAL_IS_OPEN"]
        row[PROPOSAL_HAS_FUNDERS] = proposal_metrics["PROPOSAL_HAS_FUNDERS"]

    # RFP metrics (for GRANT type)
    if unified_doc.document_type == "GRANT":
        rfp_metrics = get_rfp_metrics(unified_doc)
        row[RFP_IS_OPEN] = rfp_metrics["RFP_IS_OPEN"]
        row[RFP_HAS_APPLICANTS] = rfp_metrics["RFP_HAS_APPLICANTS"]
