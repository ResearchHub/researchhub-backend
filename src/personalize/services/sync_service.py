import logging
from typing import List

from analytics.constants.event_types import EVENT_WEIGHTS
from analytics.models import UserInteractions
from personalize.clients.sync_client import SyncClient
from personalize.services.item_mapper import ItemMapper
from personalize.types import SyncResult, SyncResultWithSkipped
from personalize.utils.personalize_utils import (
    build_session_id_for_anonymous,
    build_session_id_for_user,
)
from personalize.utils.related_data_fetcher import RelatedDataFetcher
from researchhub_document.models import ResearchhubUnifiedDocument

logger = logging.getLogger(__name__)


class SyncService:
    def __init__(self, sync_client: SyncClient = None):
        self.sync_client = sync_client or SyncClient()
        self.fetcher = RelatedDataFetcher()
        self.mapper = ItemMapper()

    def sync_items(
        self, unified_docs: List[ResearchhubUnifiedDocument]
    ) -> SyncResultWithSkipped:
        if not unified_docs:
            return {
                "success": True,
                "synced": 0,
                "failed": 0,
                "skipped": 0,
                "errors": [],
            }

        doc_ids = [doc.id for doc in unified_docs]
        batch_data = self.fetcher.fetch_all(doc_ids)

        bounty_data = batch_data["bounty"]
        proposal_data = batch_data["proposal"]
        rfp_data = batch_data["rfp"]
        review_count_data = batch_data["review_count"]

        items = []
        skipped = 0

        for unified_doc in unified_docs:
            try:
                item = self.mapper.map_to_api_item(
                    unified_doc,
                    bounty_data=bounty_data.get(unified_doc.id, {}),
                    proposal_data=proposal_data.get(unified_doc.id, {}),
                    rfp_data=rfp_data.get(unified_doc.id, {}),
                    review_count_data=review_count_data,
                )
                items.append(item)
            except Exception as e:
                skipped += 1
                logger.warning(
                    f"Failed to map document {unified_doc.id} for sync: {str(e)}"
                )

        if not items:
            return {
                "success": True,
                "synced": 0,
                "failed": 0,
                "skipped": skipped,
                "errors": [],
            }

        result = self.sync_client.put_items(items)
        result["skipped"] = skipped

        return result

    def sync_item(
        self, unified_doc: ResearchhubUnifiedDocument
    ) -> SyncResultWithSkipped:
        return self.sync_items([unified_doc])

    def _build_interaction_event(self, interaction: UserInteractions) -> dict:
        event_value = EVENT_WEIGHTS.get(interaction.event, 1.0)

        event = {
            "eventId": str(interaction.id),
            "eventType": interaction.event,
            "eventValue": event_value,
            "itemId": str(interaction.unified_document_id),
            "sentAt": int(interaction.event_timestamp.timestamp()),
        }

        if interaction.personalize_rec_id:
            event["recommendationId"] = interaction.personalize_rec_id
        elif interaction.impression:
            event["impression"] = interaction.impression.split("|")

        return event

    def sync_event(self, interaction: UserInteractions) -> SyncResult:
        if not interaction.unified_document_id:
            return {
                "success": False,
                "synced": 0,
                "failed": 1,
                "errors": ["Missing unified_document_id"],
            }

        if not interaction.user_id and not interaction.external_user_id:
            return {
                "success": False,
                "synced": 0,
                "failed": 1,
                "errors": ["Missing both user_id and external_user_id"],
            }

        if interaction.user_id:
            user_id = str(interaction.user_id)
            session_id = build_session_id_for_user(
                interaction.user_id, interaction.event_timestamp
            )
        else:
            user_id = interaction.external_user_id
            session_id = build_session_id_for_anonymous(interaction.external_user_id)

        event = self._build_interaction_event(interaction)
        result = self.sync_client.put_events(user_id, session_id, [event])

        return result
