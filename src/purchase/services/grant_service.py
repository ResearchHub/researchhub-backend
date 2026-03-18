import logging

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.db import transaction

from discussion.views import create_flag
from feed.signals.post_signals import _create_post_feed_entries
from user.related_models.verdict_model import Verdict
from feed.views.grant_feed_mixin import GrantFeedMixin
from notification.models import Notification
from purchase.models import Grant
from utils.doi import DOI

logger = logging.getLogger(__name__)


class GrantModerationService:
    """Service for managing grant moderation operations."""

    def approve_grant(self, grant, reviewer):
        """Approve a pending grant and publish it to the feed."""
        if grant.status != Grant.PENDING:
            raise ValueError("Only pending grants can be approved")

        with transaction.atomic():
            grant.status = Grant.OPEN
            grant.save(update_fields=["status"])

            post = grant.unified_document.posts.first()
            self._assign_doi_to_post(post)
            self._publish_to_feed(post)

            cache.delete("grant_available_funding")
            GrantFeedMixin.invalidate_grant_feed_cache()
            self._send_moderation_notification(
                grant, reviewer, Notification.GRANT_APPROVED
            )

        return grant

    def decline_grant(self, grant, reviewer, reason="", reason_choice=""):
        """Decline a pending grant, create a flag, and soft-delete its unified document."""
        if grant.status != Grant.PENDING:
            raise ValueError("Only pending grants can be declined")

        with transaction.atomic():
            grant.status = Grant.DECLINED
            grant.save(update_fields=["status"])
            self._flag_and_remove_grant(grant, reviewer, reason, reason_choice)

            GrantFeedMixin.invalidate_grant_feed_cache()
            self._send_moderation_notification(
                grant, reviewer, Notification.GRANT_DECLINED
            )

        return grant

    def _flag_and_remove_grant(self, grant, reviewer, reason, reason_choice):
        flag, _ = create_flag(
            user=reviewer,
            item=grant,
            reason=reason,
            reason_choice=reason_choice,
            reason_memo=reason,
        )

        verdict = Verdict.objects.create(
            created_by=reviewer,
            flag=flag,
            verdict_choice=reason_choice,
            is_content_removed=True,
        )
        flag.verdict_created_date = verdict.created_date
        flag.save(update_fields=["verdict_created_date"])

        unified_document = grant.unified_document
        unified_document.is_removed = True
        unified_document.save(update_fields=["is_removed"])

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

    def _publish_to_feed(self, post):
        if not post:
            return

        try:
            _create_post_feed_entries(post)
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
