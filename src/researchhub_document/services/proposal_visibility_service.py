import logging
from collections.abc import Callable

from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from feed.tasks import publish_to_feed
from feed.views.funding_cache_mixin import FundingCacheMixin
from feed.views.grant_cache_mixin import GrantCacheMixin
from purchase.models import Grant
from researchhub_document.models import ResearchhubPost
from researchhub_document.related_models.constants.document_type import (
    PREREGISTRATION,
)
from user.models import Action, User

logger = logging.getLogger(__name__)


class ProposalVisibilityService:
    """Make a private proposal public and publish its public-facing activity."""

    def __init__(
        self,
        feed_publisher: Callable[[ResearchhubPost, int | None], None] | None = None,
        funding_cache_invalidator: Callable[[], None] | None = None,
        grant_cache_invalidator: Callable[[], None] | None = None,
    ) -> None:
        self.feed_publisher = feed_publisher or publish_to_feed
        self.funding_cache_invalidator = (
            funding_cache_invalidator or FundingCacheMixin.invalidate_funding_feed_cache
        )
        self.grant_cache_invalidator = (
            grant_cache_invalidator or GrantCacheMixin.invalidate_grant_feed_cache
        )

    def make_public(self, proposal_id: int, user: User) -> ResearchhubPost:
        """Make the proposal identified by ``proposal_id`` public.

        Publishing is intentionally one-way. Proposals submitted to an RFP
        that requires private applications must remain private.
        """
        grant_linked = False
        changed = False
        with transaction.atomic():
            proposal = (
                ResearchhubPost.objects.select_for_update()
                .select_related("unified_document")
                .get(pk=proposal_id)
            )
            unified_document = proposal.unified_document

            if proposal.document_type != PREREGISTRATION:
                raise ValueError("Only proposals can be made public.")
            if proposal.created_by_id != user.id:
                raise PermissionError("Only the proposal owner can make it public.")
            if unified_document.is_removed:
                raise ValueError("Removed proposals cannot be made public.")
            if unified_document.is_public:
                return proposal
            if proposal.grant_applications.filter(
                grant__application_visibility=Grant.APPLICATION_VISIBILITY_PRIVATE
            ).exists():
                raise ValueError(
                    "This proposal is an application to a grant that requires "
                    "applications to be private."
                )

            unified_document.is_public = True
            unified_document.save(update_fields=["is_public"])

            post_content_type = ContentType.objects.get_for_model(ResearchhubPost)
            Action.objects.filter(
                content_type=post_content_type,
                object_id=proposal.id,
            ).update(display=True)

            grant_linked = proposal.grant_applications.exists()
            changed = True

        if changed:
            self._publish(proposal)
            self.funding_cache_invalidator()
            if grant_linked:
                self.grant_cache_invalidator()

        return proposal

    def _publish(self, proposal: ResearchhubPost) -> None:
        try:
            self.feed_publisher(proposal, proposal.created_by_id)
        except Exception:
            logger.exception(
                "Failed to publish newly public proposal %s to the feed",
                proposal.id,
            )
