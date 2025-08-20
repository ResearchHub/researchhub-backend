from django.contrib.contenttypes.fields import GenericRelation
from django.db import models
from django.db.models import CharField, Count, JSONField, Q

from researchhub_access_group.models import Permission
from researchhub_comment.constants.rh_comment_thread_types import (
    COMMUNITY_REVIEW,
    GENERIC_COMMENT,
    PEER_REVIEW,
    RH_COMMENT_THREAD_TYPES,
)
from utils.models import AbstractGenericRelationModel


class RhCommentThreadQuerySet(models.QuerySet):
    def get_discussion_count(self):
        """
        Counts GENERIC_COMMENT type comments without bounties, but only in threads
        where the root (top-level) comment is also GENERIC_COMMENT (regardless of
        whether the root is removed or not).
        """
        from researchhub_comment.models import RhCommentModel

        # Find threads that have a GENERIC_COMMENT as their root comment
        # Don't filter by is_removed for the root - we want to include threads
        # even if the root is censored, as long as it was originally GENERIC_COMMENT
        threads_with_generic_root = self.filter(
            rh_comments__parent__isnull=True,
            rh_comments__comment_type=GENERIC_COMMENT,
        ).distinct()

        # Count all visible GENERIC_COMMENT type comments in those threads
        visible_comments = RhCommentModel.objects.filter(
            thread__in=threads_with_generic_root,
            comment_type=GENERIC_COMMENT,
            bounties__isnull=True,
            is_removed=False,
        )

        return visible_comments.count()

    def get_discussion_aggregates(self, item):
        """
        Example aggregator, adapted from your code.
        Note: self.exclude(...) etc. uses the QuerySet instead of Manager.
        """
        # Single aggregate query for all counts
        aggregator = self.aggregate(
            # Review count - reviews without bounties (top-level only)
            review_count=Count(
                "rh_comments",
                filter=Q(
                    rh_comments__comment_type__in=[PEER_REVIEW, COMMUNITY_REVIEW],
                    rh_comments__bounties__isnull=True,
                    rh_comments__is_removed=False,
                    rh_comments__parent__isnull=True,  # Only count top-level comments
                ),
            ),
            # Bounty count - count comments that have at least one bounty attached
            bounty_count=Count(
                "rh_comments",
                distinct=True,
                filter=Q(
                    rh_comments__bounties__isnull=False,
                    rh_comments__is_removed=False,
                    rh_comments__parent__isnull=True,  # Only count top-level comments
                ),
            ),
            # Conversation count - generic comments without bounties (top-level only)
            conversation_count=Count(
                "rh_comments",
                filter=Q(
                    rh_comments__comment_type=GENERIC_COMMENT,
                    rh_comments__bounties__isnull=True,
                    rh_comments__is_removed=False,
                    rh_comments__parent__isnull=True,  # Only count top-level comments
                ),
            ),
        )

        aggregator["discussion_count"] = item.discussion_count
        return aggregator


class RhCommentThreadManager(models.Manager):
    def get_queryset(self):
        return RhCommentThreadQuerySet(self.model, using=self._db)

    def get_discussion_count(self):
        return self.get_queryset().get_discussion_count()

    def get_discussion_aggregates(self, item):
        return self.get_queryset().get_discussion_aggregates(item)


class RhCommentThreadModel(AbstractGenericRelationModel):
    thread_type = CharField(
        max_length=144,
        choices=RH_COMMENT_THREAD_TYPES,
        default=GENERIC_COMMENT,
    )
    thread_reference = CharField(
        blank=True,
        help_text=(
            "A thread may need a special referencing tool. "
            "Use this field for such a case"
        ),
        max_length=144,
        null=True,
    )
    anchor = JSONField(blank=True, null=True)
    permissions = GenericRelation(Permission, related_name="rh_thread")

    objects = RhCommentThreadManager()

    @property
    def unified_document(self):
        return self.content_object.unified_document
