import logging

from django.core.cache import cache
from django.db import transaction
from django_opensearch_dsl.registries import registry

from feed.signals.post_signals import _create_post_feed_entries
from feed.views.grant_cache_mixin import GrantCacheMixin
from notification.models import Notification
from purchase.models import Grant
from user.services.moderation import (
    create_removal_verdict,
    send_moderation_notification,
)

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
            self._publish_to_feed(post)
            self._reindex_post(post)

            cache.delete("grant_available_funding")
            GrantCacheMixin.invalidate_grant_feed_cache()
            self._send_moderation_notification(
                grant, reviewer, Notification.GRANT_APPROVED
            )

        return grant

    def decline_grant(self, grant, reviewer, reason="", reason_choice=""):
        """
        Decline a pending grant, create a flag, and soft-delete its unified document.
        """
        if grant.status != Grant.PENDING:
            raise ValueError("Only pending grants can be declined")

        with transaction.atomic():
            grant.status = Grant.DECLINED
            grant.save(update_fields=["status"])
            self._flag_and_remove_grant(grant, reviewer, reason, reason_choice)

            GrantCacheMixin.invalidate_grant_feed_cache()
            self._send_moderation_notification(
                grant, reviewer, Notification.GRANT_DECLINED
            )

        return grant

    def _flag_and_remove_grant(self, grant, reviewer, reason, reason_choice):
        create_removal_verdict(reviewer, grant, reason, reason_choice)

        unified_document = grant.unified_document
        unified_document.is_removed = True
        unified_document.save(update_fields=["is_removed"])

    def _publish_to_feed(self, post):
        if not post:
            return

        try:
            _create_post_feed_entries(post)
        except Exception:
            logger.exception("Failed to create feed entry for post %s", post.id)

    def _reindex_post(self, post):
        """Refresh the grant post in OpenSearch after its status changes.

        Approving a grant only saves ``Grant.status``; the backing post (which
        the post index keys on) is untouched, so its search document would not
        otherwise reflect the now-approved grant. Run after commit so the index
        sees the persisted state.
        """
        if not post:
            return

        def _update():
            try:
                registry.update(post)
            except Exception:
                logger.exception("Failed to reindex grant post %s", post.id)

        transaction.on_commit(_update)

    def _send_moderation_notification(self, grant, action_user, notification_type):
        send_moderation_notification(
            notification_type,
            recipient=grant.created_by,
            action_user=action_user,
            item=grant,
        )
