import logging

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from feed.models import FeedEntry
from feed.tasks import create_feed_entry
from feed.views.grant_feed_view import GRANT_FEED_CACHE_VERSION_KEY
from notification.models import Notification
from purchase.models import Grant
from utils.doi import DOI

logger = logging.getLogger(__name__)


class GrantService:
    """Service for managing grant moderation operations."""

    def approve_grant(self, grant, reviewer):
        """Approve a pending grant and publish it to the feed."""
        if grant.status != Grant.PENDING:
            raise ValueError("Only pending grants can be approved")

        grant.status = Grant.OPEN
        grant.reviewed_by = reviewer
        grant.reviewed_date = timezone.now()
        grant.save(update_fields=["status", "reviewed_by", "reviewed_date"])

        cache.delete("grant_available_funding")
        cache.set(GRANT_FEED_CACHE_VERSION_KEY, timezone.now().timestamp())

        post = grant.unified_document.posts.first()
        self._assign_doi_to_post(post)
        self._create_feed_entry_for_post(post)
        self._send_moderation_notification(
            grant, reviewer, Notification.GRANT_APPROVED
        )

        return grant

    def decline_grant(self, grant, reviewer, reason=""):
        """Decline a pending grant and soft-delete its unified document."""
        if grant.status != Grant.PENDING:
            raise ValueError("Only pending grants can be declined")

        grant.status = Grant.DECLINED
        grant.reviewed_by = reviewer
        grant.reviewed_date = timezone.now()
        grant.decline_reason = reason
        grant.save(
            update_fields=[
                "status",
                "reviewed_by",
                "reviewed_date",
                "decline_reason",
            ]
        )

        unified_document = grant.unified_document
        unified_document.is_removed = True
        unified_document.save(update_fields=["is_removed"])

        cache.set(GRANT_FEED_CACHE_VERSION_KEY, timezone.now().timestamp())

        self._send_moderation_notification(
            grant, reviewer, Notification.GRANT_DECLINED
        )

        return grant

    def _assign_doi_to_post(self, post):
        if not post or post.doi:
            return

        try:
            doi = DOI()
            post.doi = doi.doi
            post.save(update_fields=["doi"])

            author = post.created_by.author_profile
            doi.register_doi_for_post([author], post.title, post)
        except Exception:
            logger.exception("Failed to assign DOI to post %s", post.id)

    def _create_feed_entry_for_post(self, post):
        if not post:
            return

        try:
            hub_ids = list(
                post.unified_document.hubs.values_list("id", flat=True)
            )
            content_type_id = ContentType.objects.get_for_model(post).id

            transaction.on_commit(
                lambda: create_feed_entry.apply_async(
                    args=(
                        post.id,
                        content_type_id,
                        FeedEntry.PUBLISH,
                        hub_ids,
                        post.created_by_id,
                    ),
                    priority=1,
                )
            )
        except Exception:
            logger.exception("Failed to create feed entry for post %s", post.id)

    def _send_moderation_notification(self, grant, action_user, notification_type):
        try:
            content_type = ContentType.objects.get_for_model(Grant)
            notification = Notification.objects.create(
                notification_type=notification_type,
                recipient=grant.created_by,
                action_user=action_user,
                content_type=content_type,
                object_id=grant.id,
                unified_document=grant.unified_document,
            )
            notification.send_notification()
        except Exception:
            logger.exception(
                "Failed to send %s notification for grant %s",
                notification_type,
                grant.id,
            )
