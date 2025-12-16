"""
Mapper class for converting ResearchhubUnifiedDocument to AWS Personalize items.
"""

import json
from typing import Dict, Optional, Protocol, runtime_checkable

from personalize.config.constants import (
    BLUESKY_POST_COUNT,
    BLUESKY_TOTAL_LIKES,
    BLUESKY_TOTAL_QUOTES,
    BLUESKY_TOTAL_REPLIES,
    BLUESKY_TOTAL_REPOSTS,
    BOUNTY_HAS_SOLUTIONS,
    CITATION_COUNT_TOTAL,
    CREATION_TIMESTAMP,
    DELIMITER,
    FIELD_DEFAULTS,
    GITHUB_CODE_MENTIONS,
    GITHUB_TOTAL_MENTIONS,
    HAS_ACTIVE_BOUNTY,
    HUB_IDS,
    HUB_L1,
    HUB_L2,
    ITEM_ID,
    ITEM_TYPE,
    ITEM_TYPE_MAPPING,
    JOURNAL_HUB_ID,
    PEER_REVIEW_COUNT_TOTAL,
    PROPOSAL_HAS_FUNDERS,
    PROPOSAL_IS_OPEN,
    RFP_HAS_APPLICANTS,
    RFP_IS_OPEN,
    TEXT,
    TITLE,
    UPVOTE_SCORE,
    X_POST_COUNT,
    X_TOTAL_IMPRESSIONS,
    X_TOTAL_LIKES,
    X_TOTAL_QUOTES,
    X_TOTAL_REPLIES,
    X_TOTAL_REPOSTS,
)
from personalize.utils.item_utils import prepare_text_for_personalize
from utils.time import datetime_to_epoch_seconds


@runtime_checkable
class PrefetchedUnifiedDocument(Protocol):
    """
    UnifiedDocument with required prefetched relations.

    Required prefetch_related:
    - hubs
    - fundraises, related_bounties, grants
    """

    id: int
    document_type: str
    score: int


class ItemMapper:
    """Mapper for converting ResearchHub documents to Personalize items."""

    @staticmethod
    def _to_camel_case(snake_str: str) -> str:
        components = snake_str.split("_")
        return components[0].lower() + "".join(x.title() for x in components[1:])

    def map_to_csv_item(
        self,
        prefetched_doc: PrefetchedUnifiedDocument,
        bounty_data: dict,
        proposal_data: dict,
        rfp_data: dict,
        review_count_data: dict,
    ) -> Dict[str, Optional[str]]:
        return self._map_to_item(
            prefetched_doc, bounty_data, proposal_data, rfp_data, review_count_data
        )

    def map_to_api_item(
        self,
        prefetched_doc: PrefetchedUnifiedDocument,
        bounty_data: dict,
        proposal_data: dict,
        rfp_data: dict,
        review_count_data: dict,
    ) -> Dict[str, str]:
        item_data = self._map_to_item(
            prefetched_doc, bounty_data, proposal_data, rfp_data, review_count_data
        )

        item_id = item_data.pop(ITEM_ID)

        properties_dict = {}
        for key, value in item_data.items():
            if value is not None:
                camel_key = self._to_camel_case(key)
                if isinstance(value, bool):
                    properties_dict[camel_key] = "True" if value else "False"
                else:
                    properties_dict[camel_key] = value

        return {"itemId": str(item_id), "properties": json.dumps(properties_dict)}

    def _map_to_item(
        self,
        prefetched_doc: PrefetchedUnifiedDocument,
        bounty_data: dict,
        proposal_data: dict,
        rfp_data: dict,
        review_count_data: dict,
    ) -> Dict[str, Optional[str]]:
        # Initialize row with default values from constants
        row = {field: default for field, default in FIELD_DEFAULTS.items()}

        # Get the concrete document from prefetched data (avoids N+1 queries)
        if prefetched_doc.document_type == "PAPER":
            # For papers, use select_related paper (no query)
            document = prefetched_doc.paper
            if not document:
                raise ValueError(f"Paper not found for unified_doc {prefetched_doc.id}")
        else:
            # For posts, get from prefetched posts (no query)
            # Access the prefetch cache directly to avoid posts.first() query
            posts = prefetched_doc.posts.all()
            if not posts:
                raise ValueError(f"Post not found for unified_doc {prefetched_doc.id}")
            document = posts[0]  # Get first from cached list

        # Map common fields
        row.update(self._map_common_fields(prefetched_doc, document))

        # Map document-type-specific fields
        if prefetched_doc.document_type == "PAPER":
            row.update(self._map_paper_fields(prefetched_doc, document))
        else:
            row.update(self._map_post_fields(prefetched_doc, document))

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

    # Preprint source slugs to prioritize when selecting journal hub
    PREPRINT_SOURCE_SLUGS = {"biorxiv", "arxiv", "chemrxiv", "medrxiv"}

    def _map_common_fields(
        self, prefetched_doc: PrefetchedUnifiedDocument, document
    ) -> dict:
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
        from personalize.config.constants import MAX_HUB_IDS

        hub_ids = []
        hub_l1 = None
        hub_l2 = None
        journal_hub_id = None
        journal_hubs = []

        for hub in list(prefetched_doc.hubs.all())[:MAX_HUB_IDS]:
            hub_ids.append(str(hub.id))
            if hub.namespace == Hub.Namespace.CATEGORY:
                hub_l1 = str(hub.id)
            elif hub.namespace == Hub.Namespace.SUBCATEGORY:
                hub_l2 = str(hub.id)
            elif hub.namespace == Hub.Namespace.JOURNAL:
                journal_hubs.append(hub)

        # Select journal hub, prioritizing preprint sources
        if journal_hubs:
            # First, try to find a preprint source journal
            for hub in journal_hubs:
                if hub.slug in self.PREPRINT_SOURCE_SLUGS:
                    journal_hub_id = str(hub.id)
                    break
            # Fall back to first journal hub if no preprint source found
            if journal_hub_id is None:
                journal_hub_id = str(journal_hubs[0].id)

        return {
            ITEM_ID: str(prefetched_doc.id),
            ITEM_TYPE: ITEM_TYPE_MAPPING.get(
                prefetched_doc.document_type, prefetched_doc.document_type
            ),
            CREATION_TIMESTAMP: timestamp,
            UPVOTE_SCORE: (
                prefetched_doc.score if prefetched_doc.score is not None else 0
            ),
            HUB_L1: hub_l1,
            HUB_L2: hub_l2,
            HUB_IDS: DELIMITER.join(hub_ids) if hub_ids else None,
            JOURNAL_HUB_ID: journal_hub_id,
        }

    def _map_paper_fields(
        self, prefetched_doc: PrefetchedUnifiedDocument, paper
    ) -> dict:
        """Map paper-specific fields."""
        title = paper.paper_title or paper.title or ""
        abstract = paper.abstract or ""
        # Build hub names from prefetched hubs to avoid query
        hub_names = ",".join(hub.name for hub in prefetched_doc.hubs.all())

        text_concat = f"{title} {abstract} {hub_names}"

        fields = {
            TITLE: prepare_text_for_personalize(title),
            TEXT: prepare_text_for_personalize(text_concat),
            CITATION_COUNT_TOTAL: paper.citations if paper.citations is not None else 0,
        }

        if paper.external_metadata:
            metrics = paper.external_metadata.get("metrics", {})

            # Extract Bluesky metrics
            bluesky_metrics = metrics.get("bluesky", {})
            fields[BLUESKY_POST_COUNT] = bluesky_metrics.get("post_count", 0)
            fields[BLUESKY_TOTAL_LIKES] = bluesky_metrics.get("total_likes", 0)
            fields[BLUESKY_TOTAL_QUOTES] = bluesky_metrics.get("total_quotes", 0)
            fields[BLUESKY_TOTAL_REPLIES] = bluesky_metrics.get("total_replies", 0)
            fields[BLUESKY_TOTAL_REPOSTS] = bluesky_metrics.get("total_reposts", 0)

            # Extract X (Twitter) metrics
            x_metrics = metrics.get("x", {})
            fields[X_POST_COUNT] = x_metrics.get("post_count", 0)
            fields[X_TOTAL_LIKES] = x_metrics.get("total_likes", 0)
            fields[X_TOTAL_QUOTES] = x_metrics.get("total_quotes", 0)
            fields[X_TOTAL_REPLIES] = x_metrics.get("total_replies", 0)
            fields[X_TOTAL_REPOSTS] = x_metrics.get("total_reposts", 0)
            fields[X_TOTAL_IMPRESSIONS] = x_metrics.get("total_impressions", 0)

            # Extract GitHub metrics
            github_metrics = metrics.get("github_mentions", {})
            fields[GITHUB_TOTAL_MENTIONS] = github_metrics.get("total_mentions", 0)
            fields[GITHUB_CODE_MENTIONS] = github_metrics.get("breakdown", {}).get(
                "code", 0
            )

        return fields

    def _map_post_fields(self, prefetched_doc: PrefetchedUnifiedDocument, post) -> dict:
        """Map post-specific fields."""
        title = post.title or ""
        renderable_text = post.renderable_text or ""
        # Build hub names from prefetched hubs to avoid query
        hub_names = ",".join(hub.name for hub in prefetched_doc.hubs.all())

        text_concat = f"{title} {renderable_text} {hub_names}"

        return {
            TITLE: prepare_text_for_personalize(title),
            TEXT: prepare_text_for_personalize(text_concat),
        }
