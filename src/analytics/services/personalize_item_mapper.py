"""
Mapper for converting ResearchhubUnifiedDocument to AWS Personalize item rows.

Maps unified documents to CSV rows with all metadata fields.
"""

from typing import Dict, Optional

from django.db.models import Q, QuerySet

from analytics.services.personalize_item_constants import (
    AUTHOR_IDS,
    BLUESKY_COUNT_TOTAL,
    BOUNTY_AMOUNT,
    BOUNTY_EXPIRES_AT,
    BOUNTY_NUM_OF_SOLUTIONS,
    CITATION_COUNT_TOTAL,
    CREATION_TIMESTAMP,
    CSV_HEADERS,
    EXCLUDED_DOCUMENT_TYPES,
    HUB_IDS,
    HUB_L1,
    HUB_L2,
    ITEM_ID,
    ITEM_TYPE,
    LAST_COMMENT_AT,
    PROPOSAL_AMOUNT,
    PROPOSAL_EXPIRES_AT,
    PROPOSAL_NUM_OF_FUNDERS,
    REQUEST_FOR_PROPOSAL_AMOUNT,
    REQUEST_FOR_PROPOSAL_EXPIRES_AT,
    REQUEST_FOR_PROPOSAL_NUM_OF_APPLICANTS,
    SCORE,
    TEXT,
    TITLE,
    TWEET_COUNT_TOTAL,
)
from analytics.services.personalize_item_utils import (
    clean_text_for_csv,
    get_author_ids,
    get_bounty_metrics,
    get_hub_mapping,
    get_last_comment_timestamp,
    get_proposal_metrics,
    get_rfp_metrics,
)
from analytics.services.personalize_utils import datetime_to_epoch_seconds
from researchhub_document.models import ResearchhubUnifiedDocument


class ItemMapper:
    """Maps ResearchhubUnifiedDocument instances to CSV item rows."""

    def get_queryset(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        item_ids: Optional[set] = None,
    ) -> QuerySet:
        """
        Get queryset of unified documents for export.

        Filters:
        - Not removed
        - Not excluded document types (NOTE, HYPOTHESIS)
        - Not excluded from feed
        - For papers: Include native papers OR papers with interactions
        - For posts: Include all
        - Optional date range filter
        - Optional filter by specific item IDs (from interactions)

        Args:
            start_date: Filter documents created after this date
            end_date: Filter documents created before this date
            item_ids: Set of item IDs to filter by (if provided)

        Returns:
            QuerySet of ResearchhubUnifiedDocument
        """
        queryset = (
            ResearchhubUnifiedDocument.objects.select_related(
                "document_filter",
            )
            .prefetch_related(
                "hubs",
                "related_bounties",
                "fundraises",
                "grants__contacts__author_profile",
                "paper__authorships__author",
            )
            .filter(
                is_removed=False,
            )
            .exclude(document_type__in=EXCLUDED_DOCUMENT_TYPES)
            .exclude(document_filter__is_excluded_in_feed=True)
        )

        # Apply paper filtering logic:
        # - Include all native papers (user-submitted preprints)
        # - Include all non-paper documents (posts like GRANT, DISCUSSION, etc.)
        # - External papers: only if they're in item_ids (have interactions)
        if item_ids:
            # If item_ids provided (from interaction export), filter by those
            queryset = queryset.filter(id__in=item_ids)
        else:
            # Otherwise, include native papers and all posts
            native_paper = Q(
                document_type="PAPER",
                paper__retrieved_from_external_source=False,
            )
            non_paper = ~Q(document_type="PAPER")

            queryset = queryset.filter(native_paper | non_paper)

        if start_date:
            queryset = queryset.filter(created_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_date__lte=end_date)

        return queryset.order_by("id")

    def map_to_item_row(self, unified_doc) -> Dict[str, Optional[str]]:
        """
        Map a unified document to a CSV row dictionary.

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
            # If we can't get the document, return empty row with just ID
            row[ITEM_ID] = str(unified_doc.id)
            row[ITEM_TYPE] = unified_doc.document_type
            return row

        # Common fields for all document types
        row[ITEM_ID] = str(unified_doc.id)
        row[ITEM_TYPE] = unified_doc.document_type

        # For papers, use paper_publish_date instead of created_date
        if (
            unified_doc.document_type == "PAPER"
            and hasattr(document, "paper_publish_date")
            and document.paper_publish_date
        ):
            timestamp = datetime_to_epoch_seconds(document.paper_publish_date)
        else:
            timestamp = datetime_to_epoch_seconds(unified_doc.created_date)
        row[CREATION_TIMESTAMP] = timestamp

        row[SCORE] = unified_doc.score

        # Hub mapping
        hub_l1, hub_l2 = get_hub_mapping(unified_doc, document)
        row[HUB_L1] = hub_l1
        row[HUB_L2] = hub_l2

        # Hub IDs
        hub_ids = [str(hub.id) for hub in unified_doc.hubs.all()]
        row[HUB_IDS] = ",".join(hub_ids) if hub_ids else None

        # Author IDs
        row[AUTHOR_IDS] = get_author_ids(unified_doc, document)

        # Document-type-specific fields
        if unified_doc.document_type == "PAPER":
            self._map_paper_fields(row, unified_doc, document)
        else:
            # Post types (DISCUSSION, GRANT, QUESTION, etc.)
            self._map_post_fields(row, unified_doc, document)

        # Bounty metrics (can apply to any document type)
        bounty_metrics = get_bounty_metrics(unified_doc)
        row[BOUNTY_AMOUNT] = bounty_metrics["BOUNTY_AMOUNT"]
        row[BOUNTY_EXPIRES_AT] = bounty_metrics["BOUNTY_EXPIRES_AT"]
        row[BOUNTY_NUM_OF_SOLUTIONS] = bounty_metrics["BOUNTY_NUM_OF_SOLUTIONS"]

        # Proposal metrics (for PREREGISTRATION type)
        if unified_doc.document_type == "PREREGISTRATION":
            proposal_metrics = get_proposal_metrics(unified_doc)
            row[PROPOSAL_AMOUNT] = proposal_metrics["PROPOSAL_AMOUNT"]
            row[PROPOSAL_EXPIRES_AT] = proposal_metrics["PROPOSAL_EXPIRES_AT"]
            row[PROPOSAL_NUM_OF_FUNDERS] = proposal_metrics["PROPOSAL_NUM_OF_FUNDERS"]

        # RFP metrics (for GRANT type)
        if unified_doc.document_type == "GRANT":
            rfp_metrics = get_rfp_metrics(unified_doc)
            row[REQUEST_FOR_PROPOSAL_AMOUNT] = rfp_metrics[
                "REQUEST_FOR_PROPOSAL_AMOUNT"
            ]
            row[REQUEST_FOR_PROPOSAL_EXPIRES_AT] = rfp_metrics[
                "REQUEST_FOR_PROPOSAL_EXPIRES_AT"
            ]
            row[REQUEST_FOR_PROPOSAL_NUM_OF_APPLICANTS] = rfp_metrics[
                "REQUEST_FOR_PROPOSAL_NUM_OF_APPLICANTS"
            ]

        # Last comment timestamp
        row[LAST_COMMENT_AT] = get_last_comment_timestamp(unified_doc)

        return row

    def _map_paper_fields(self, row: Dict, unified_doc, paper) -> None:
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
            row[BLUESKY_COUNT_TOTAL] = metadata.get("bluesky_count", 0)
            row[TWEET_COUNT_TOTAL] = metadata.get("twitter_count", 0)

    def _map_post_fields(self, row: Dict, unified_doc, post) -> None:
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
