"""
Utility functions for AWS Personalize item data export.

Functions for text cleaning, hub mapping, author extraction,
and metrics aggregation.
"""

import re
from typing import Dict, Optional, Tuple

from django.contrib.contenttypes.models import ContentType
from django.db.models import Max

from analytics.services.personalize_item_constants import MAX_TEXT_LENGTH
from analytics.services.personalize_utils import datetime_to_epoch_seconds
from hub.mappers import ExternalCategoryMapper
from purchase.models import GrantApplication, Purchase
from reputation.models import BountySolution
from researchhub_comment.models import RhCommentModel


def clean_text_for_csv(text: Optional[str]) -> Optional[str]:
    """
    Clean text to be CSV-safe.

    Strips HTML tags, removes/escapes problematic characters,
    and truncates to maximum length.

    Args:
        text: Raw text that may contain HTML, newlines, etc.

    Returns:
        Cleaned text safe for CSV, or None if input is None/empty
    """
    if not text:
        return None

    # Strip HTML tags using regex
    text = re.sub(r"<[^>]+>", "", text)

    # Remove or replace problematic characters for CSV
    # Replace newlines and tabs with spaces
    text = re.sub(r"[\n\r\t]+", " ", text)

    # Replace multiple spaces with single space
    text = re.sub(r"\s+", " ", text)

    # Strip leading/trailing whitespace
    text = text.strip()

    # Truncate if too long
    if len(text) > MAX_TEXT_LENGTH:
        text = text[:MAX_TEXT_LENGTH]

    return text if text else None


def get_hub_mapping(unified_doc, document) -> Tuple[Optional[str], Optional[str]]:
    """
    Get two-level hub categorization for a document.

    Strategy:
    - For papers with external source: Use ExternalCategoryMapper
    - For other documents: Use primary hub as L1, L2 is None

    Args:
        unified_doc: ResearchhubUnifiedDocument instance
        document: The concrete document (Paper or Post)

    Returns:
        Tuple of (HUB_L1, HUB_L2) as hub slugs or None
    """
    hub_l1 = None
    hub_l2 = None

    # Check if this is a paper with external source
    if hasattr(document, "external_source") and document.external_source:
        # Try to get external category mapping
        external_source = document.external_source.lower()

        # Try to get the category from open_alex_raw_json or other fields
        if hasattr(document, "open_alex_raw_json") and document.open_alex_raw_json:
            # OpenAlex data might have primary_topic
            # We'll use primary hub instead for now
            pass

        # For arXiv papers, try to extract category from URL or metadata
        if external_source in ["arxiv", "biorxiv", "medrxiv", "chemrxiv"]:
            # Try to get category from paper metadata
            category = None
            if hasattr(document, "external_metadata"):
                metadata = document.external_metadata or {}
                category = metadata.get("category") or metadata.get("categories")

            if category:
                # Map using ExternalCategoryMapper
                try:
                    hubs = ExternalCategoryMapper.map(category, external_source)
                    if hubs and len(hubs) > 0:
                        hub_l1 = hubs[0].slug
                        if len(hubs) > 1:
                            hub_l2 = hubs[1].slug
                        return (hub_l1, hub_l2)
                except Exception:
                    pass

    # Fallback: Use primary hub
    try:
        primary_hub = unified_doc.get_primary_hub(fallback=True)
        if primary_hub:
            hub_l1 = primary_hub.slug
    except Exception:
        pass

    return (hub_l1, hub_l2)


def get_author_ids(unified_doc, document) -> Optional[str]:
    """
    Get comma-separated author IDs for a document.

    Args:
        unified_doc: ResearchhubUnifiedDocument instance
        document: The concrete document (Paper or Post)

    Returns:
        Comma-separated string of author IDs, or None
    """
    author_ids = []

    try:
        # Papers have many-to-many authors
        if hasattr(document, "authors"):
            author_ids = [str(author.id) for author in document.authors.all()]
        # Posts have created_by with author_profile
        elif hasattr(document, "created_by") and document.created_by:
            if hasattr(document.created_by, "author_profile"):
                author_profile = document.created_by.author_profile
                if author_profile:
                    author_ids = [str(author_profile.id)]
    except Exception:
        pass

    return ",".join(author_ids) if author_ids else None


def get_bounty_metrics(unified_doc) -> Dict[str, Optional[float]]:
    """
    Get bounty-related metrics for a unified document.

    Args:
        unified_doc: ResearchhubUnifiedDocument instance

    Returns:
        Dict with BOUNTY_AMOUNT, BOUNTY_EXPIRES_AT, BOUNTY_NUM_OF_SOLUTIONS
    """
    result = {
        "BOUNTY_AMOUNT": None,
        "BOUNTY_EXPIRES_AT": None,
        "BOUNTY_NUM_OF_SOLUTIONS": None,
    }

    try:
        # Get open bounties
        open_bounties = unified_doc.related_bounties.filter(status="OPEN")

        if open_bounties.exists():
            # Sum bounty amounts
            total_amount = sum(float(bounty.amount) for bounty in open_bounties)
            result["BOUNTY_AMOUNT"] = total_amount

            # Get earliest expiration date
            earliest_expiration = (
                open_bounties.filter(expiration_date__isnull=False)
                .order_by("expiration_date")
                .first()
            )

            if earliest_expiration and earliest_expiration.expiration_date:
                result["BOUNTY_EXPIRES_AT"] = datetime_to_epoch_seconds(
                    earliest_expiration.expiration_date
                )

            # Count solutions for all bounties (open or closed)
            all_bounty_ids = unified_doc.related_bounties.values_list("id", flat=True)
            solution_count = BountySolution.objects.filter(
                bounty_id__in=all_bounty_ids
            ).count()
            result["BOUNTY_NUM_OF_SOLUTIONS"] = solution_count

    except Exception:
        pass

    return result


def get_proposal_metrics(unified_doc) -> Dict[str, Optional[float]]:
    """
    Get proposal (fundraise) metrics for a unified document.

    Args:
        unified_doc: ResearchhubUnifiedDocument instance

    Returns:
        Dict with PROPOSAL_AMOUNT, PROPOSAL_EXPIRES_AT, PROPOSAL_NUM_OF_FUNDERS
    """
    result = {
        "PROPOSAL_AMOUNT": None,
        "PROPOSAL_EXPIRES_AT": None,
        "PROPOSAL_NUM_OF_FUNDERS": None,
    }

    try:
        # Get open fundraises
        open_fundraises = unified_doc.fundraises.filter(status="OPEN")

        if open_fundraises.exists():
            fundraise = open_fundraises.first()

            # Get amount raised
            amount = fundraise.get_amount_raised()
            if amount:
                result["PROPOSAL_AMOUNT"] = float(amount)

            # Get expiration date
            if fundraise.end_date:
                result["PROPOSAL_EXPIRES_AT"] = datetime_to_epoch_seconds(
                    fundraise.end_date
                )

            # Count unique funders (distinct users who made purchases)
            fundraise_content_type = ContentType.objects.get_for_model(fundraise)
            funder_count = (
                Purchase.objects.filter(
                    content_type=fundraise_content_type,
                    object_id=fundraise.id,
                    purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
                )
                .values("user")
                .distinct()
                .count()
            )

            result["PROPOSAL_NUM_OF_FUNDERS"] = funder_count

    except Exception:
        pass

    return result


def get_rfp_metrics(unified_doc) -> Dict[str, Optional[float]]:
    """
    Get RFP (Request for Proposal) metrics for a unified document.

    Args:
        unified_doc: ResearchhubUnifiedDocument instance

    Returns:
        Dict with REQUEST_FOR_PROPOSAL_AMOUNT, REQUEST_FOR_PROPOSAL_EXPIRES_AT,
        REQUEST_FOR_PROPOSAL_NUM_OF_APPLICANTS
    """
    result = {
        "REQUEST_FOR_PROPOSAL_AMOUNT": None,
        "REQUEST_FOR_PROPOSAL_EXPIRES_AT": None,
        "REQUEST_FOR_PROPOSAL_NUM_OF_APPLICANTS": None,
    }

    try:
        # Get open fundraises (RFPs also use fundraise model)
        open_fundraises = unified_doc.fundraises.filter(status="OPEN")

        if open_fundraises.exists():
            fundraise = open_fundraises.first()

            # Get amount raised
            amount = fundraise.get_amount_raised()
            if amount:
                result["REQUEST_FOR_PROPOSAL_AMOUNT"] = float(amount)

            # Get expiration date
            if fundraise.end_date:
                result["REQUEST_FOR_PROPOSAL_EXPIRES_AT"] = datetime_to_epoch_seconds(
                    fundraise.end_date
                )

        # Count grant applications
        applicant_count = GrantApplication.objects.filter(
            unified_document=unified_doc
        ).count()

        result["REQUEST_FOR_PROPOSAL_NUM_OF_APPLICANTS"] = applicant_count

    except Exception:
        pass

    return result


def get_last_comment_timestamp(unified_doc) -> Optional[int]:
    """
    Get timestamp of the most recent comment on a unified document.

    Args:
        unified_doc: ResearchhubUnifiedDocument instance

    Returns:
        Unix epoch timestamp of last comment, or None
    """
    try:
        # Get the concrete document
        document = unified_doc.get_document()

        # Get all thread IDs for this document
        if hasattr(document, "rh_threads"):
            thread_ids = document.rh_threads.values_list("id", flat=True)

            # Get the most recent comment
            latest_comment = RhCommentModel.objects.filter(
                thread_id__in=thread_ids, is_removed=False
            ).aggregate(latest=Max("created_date"))

            if latest_comment and latest_comment["latest"]:
                return datetime_to_epoch_seconds(latest_comment["latest"])

    except Exception:
        pass

    return None
