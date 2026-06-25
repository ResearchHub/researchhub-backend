from feed.feed_list_dto import (
    FundingFeedListEntrySerializer,
    FundingFeedPostSerializer,
)
from researchhub_document.related_models.constants.document_type import (
    PREREGISTRATION,
    REGISTERED_REPORT,
)
from researchhub_document.related_models.constants.journey_stage import (
    JOURNEY_BADGE_FUNDED_PROPOSAL,
    JOURNEY_BADGE_HAS_RESULTS,
    JOURNEY_STAGE_REGISTERED_REPORT,
)
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost


class JournalV2FeedPostSerializer(FundingFeedPostSerializer):
    """Minimal post payload for post-based journal feed cards."""

    def to_representation(self, post: ResearchhubPost) -> dict:
        """Return the post card payload with its journal badge."""
        data = super().to_representation(post)
        data["journal_badge"] = self.get_journal_badge(post)
        return data

    def get_journal_badge(self, post: ResearchhubPost) -> str | None:
        """Return the journal badge for the latest journey stage post."""
        if post.document_type == PREREGISTRATION:
            return JOURNEY_BADGE_FUNDED_PROPOSAL
        if post.document_type != REGISTERED_REPORT:
            return None
        if self.has_results_update(post):
            return JOURNEY_BADGE_HAS_RESULTS
        return JOURNEY_STAGE_REGISTERED_REPORT

    def has_results_update(self, post: ResearchhubPost) -> bool:
        """Return whether the registered report has a results update."""
        return bool(getattr(post, "has_results", False))


class JournalV2FeedListEntrySerializer(FundingFeedListEntrySerializer):
    """Feed entry serializer for post-based journal cards."""

    post_serializer_class = JournalV2FeedPostSerializer

    class Meta(FundingFeedListEntrySerializer.Meta):
        """Fields for journal feed list entries."""

        fields = FundingFeedListEntrySerializer.Meta.fields
