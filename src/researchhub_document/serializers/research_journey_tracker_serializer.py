from collections.abc import Iterable

from rest_framework import serializers

from researchhub_document.models import ResearchhubPost, ResearchJourney
from researchhub_document.related_models.constants.journey_stage import (
    JOURNEY_STAGE_GRANT,
    JOURNEY_STAGE_LABELS,
    JOURNEY_TRACKER_STAGES,
)
from researchhub_document.services.journey_service import JourneyService


class ResearchJourneyTrackerSerializer(serializers.Serializer):
    """Serialize a research journey tracker without embedding work detail."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Initialize the serializer with a journey service dependency."""
        super().__init__(*args, **kwargs)
        self.journey_service = JourneyService()

    def to_representation(self, journey: ResearchJourney) -> dict:
        """Return a stable three-step tracker payload for a journey."""
        stage_posts = {
            stage.stage: stage.item
            for stage in self.journey_service.get_stages(journey)
        }
        visible_post_ids = self.get_visible_post_ids(stage_posts.values())
        latest_stage = self.get_latest_stage(stage_posts)

        return {
            "id": journey.id,
            "is_in_journal": journey.is_in_journal,
            "journal_included_date": journey.journal_included_date,
            "latest_stage": latest_stage,
            "stages": [
                self.build_stage_payload(
                    stage,
                    stage_posts.get(stage),
                    latest_stage,
                    visible_post_ids,
                )
                for stage in JOURNEY_TRACKER_STAGES
            ],
        }

    def get_visible_post_ids(self, posts: Iterable[ResearchhubPost]) -> set[int]:
        """Return ids for stage posts visible to the current viewer."""
        request = self.context.get("request")
        user = getattr(request, "user", None)
        post_ids = [post.id for post in posts if post is not None]
        return set(
            ResearchhubPost.objects.visible_to(user)
            .filter(id__in=post_ids)
            .values_list("id", flat=True)
        )

    def get_latest_stage(self, stage_posts: dict[str, ResearchhubPost]) -> str | None:
        """Return the latest available tracker stage."""
        for stage in reversed(JOURNEY_TRACKER_STAGES):
            if stage_posts.get(stage) is not None:
                return stage
        return None

    def build_stage_payload(
        self,
        stage: str,
        post: ResearchhubPost | None,
        latest_stage: str | None,
        visible_post_ids: set[int],
    ) -> dict[str, object]:
        """Build one pizza-tracker stage payload."""
        is_visible = post is not None and post.id in visible_post_ids
        return {
            "stage": stage,
            "label": JOURNEY_STAGE_LABELS[stage],
            "status": self.get_stage_status(stage, post, latest_stage, is_visible),
            "is_complete": post is not None,
            "is_current": post is not None and stage == latest_stage,
            "is_available": is_visible,
            "work": self.build_work_payload(stage, post, is_visible),
        }

    def get_stage_status(
        self,
        stage: str,
        post: ResearchhubPost | None,
        latest_stage: str | None,
        is_visible: bool,
    ) -> str:
        """Return the display status for one tracker stage."""
        if post is None:
            return "pending"
        if not is_visible:
            return "unavailable"
        if stage == latest_stage:
            return "current"
        return "completed"

    def build_work_payload(
        self, stage: str, post: ResearchhubPost | None, is_visible: bool
    ) -> dict[str, object] | None:
        """Build the lightweight work pointer for one visible stage."""
        if post is None or not is_visible:
            return None
        if stage == JOURNEY_STAGE_GRANT:
            return self.build_grant_work_payload(post)
        return self.build_post_work_payload(post)

    def build_grant_work_payload(
        self, post: ResearchhubPost
    ) -> dict[str, object] | None:
        """Build the detail pointer for a grant stage."""
        grant = post.unified_document.grants.first()
        if grant is None:
            return None
        return {
            "object_type": "grant",
            "object_id": grant.id,
            "post_id": post.id,
            "unified_document_id": post.unified_document_id,
            "document_type": post.document_type,
            "detail_url": f"/api/grant/{grant.id}/",
        }

    def build_post_work_payload(self, post: ResearchhubPost) -> dict[str, object]:
        """Build the detail pointer for a post-backed stage."""
        return {
            "object_type": "researchhubpost",
            "object_id": post.id,
            "post_id": post.id,
            "unified_document_id": post.unified_document_id,
            "document_type": post.document_type,
            "detail_url": f"/api/researchhubpost/{post.id}/",
        }
