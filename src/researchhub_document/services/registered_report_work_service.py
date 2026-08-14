from dataclasses import dataclass

from django.db.models import Prefetch

from researchhub_document.models import ResearchhubPost
from researchhub_document.services.journey_service import JourneyService
from researchhub_document.services.researchhub_post_author_service import (
    build_author_prefetch,
)
from review.models import Review
from user.models import User


@dataclass(frozen=True)
class RegisteredReportWorkPayload:
    """Data required to render a registered report work page."""

    report: ResearchhubPost
    grant: ResearchhubPost | None
    proposal: ResearchhubPost | None


class RegisteredReportWorkService:
    """Load registered report work-page data with viewer-safe tracker stages."""

    def __init__(
        self,
        journey_service: JourneyService | None = None,
    ) -> None:
        """Initialize the service with optional dependencies."""
        self.journey_service = journey_service or JourneyService()

    def get_work_payload(
        self, post_id: int, user: User | None
    ) -> RegisteredReportWorkPayload:
        """Return a visible report and the stages visible to the requester."""
        report = (
            ResearchhubPost.objects.visible_to(user)
            .select_related(
                "created_by",
                "created_by__author_profile",
                "journey",
                "journey__grant_post",
                "journey__preregistration_post",
                "journey__preregistration_post__created_by",
                "journey__preregistration_post__created_by__author_profile",
                "journey__preregistration_post__unified_document",
                "note",
                "note__latest_version",
                "unified_document",
            )
            .prefetch_related(
                build_author_prefetch(),
                "unified_document__hubs",
                build_author_prefetch(
                    "journey__preregistration_post__researchhubpostauthor_set"
                ),
                "journey__preregistration_post__unified_document__hubs",
                Prefetch(
                    "journey__preregistration_post__unified_document__reviews",
                    queryset=Review.objects.filter(is_removed=False).select_related(
                        "created_by",
                        "created_by__author_profile",
                    ),
                ),
            )
            .filter(pk=post_id)
            .first()
        )
        if report is None:
            raise ResearchhubPost.DoesNotExist

        journey = report.journey
        proposal = self.journey_service.get_proposal(journey) if journey else None
        grant = journey.grant_post if journey else None

        return RegisteredReportWorkPayload(
            report=report,
            grant=self._get_visible_stage(grant, user),
            proposal=self._get_visible_stage(proposal, user),
        )

    def _get_visible_stage(
        self, post: ResearchhubPost | None, user: User | None
    ) -> ResearchhubPost | None:
        """Return a tracker stage only when the requester can view it."""
        if post is None:
            return None
        if ResearchhubPost.objects.visible_to(user).filter(pk=post.pk).exists():
            return post
        return None
