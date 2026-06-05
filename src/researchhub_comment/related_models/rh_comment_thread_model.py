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

ANCESTOR_DEPTH_LIMIT = 5


def _has_removed_ancestor():
    """Build a Q matching comments with at least one removed ancestor."""
    q = Q()
    lookup = "parent"
    for _ in range(ANCESTOR_DEPTH_LIMIT):
        q |= Q(**{f"{lookup}__is_removed": True})
        lookup = f"parent__{lookup}"
    return q


def exclude_orphaned_comments(qs):
    """Exclude comments whose parent chain contains a removed comment.

    Walks up to ``ANCESTOR_DEPTH_LIMIT`` ancestor levels, which covers all
    practical nesting depths.
    """
    return qs.exclude(_has_removed_ancestor())


def hidden_comment_ids():
    """Return IDs of all comments that should not appear in feeds:
    directly removed or orphaned by a removed ancestor."""
    from researchhub_comment.models import RhCommentModel

    return RhCommentModel.all_objects.filter(
        Q(is_removed=True) | _has_removed_ancestor()
    ).values_list("id", flat=True)


class RhCommentThreadQuerySet(models.QuerySet):
    def _countable_discussion_comments(self):
        """Return non-removed, non-orphaned GENERIC_COMMENTs for counting."""
        from researchhub_comment.models import RhCommentModel

        threads = self.filter(
            rh_comments__parent__isnull=True,
            rh_comments__comment_type=GENERIC_COMMENT,
        ).distinct()

        return exclude_orphaned_comments(
            RhCommentModel.objects.filter(
                thread__in=threads,
                comment_type=GENERIC_COMMENT,
                bounties__isnull=True,
                is_removed=False,
            )
        )

    def get_discussion_count(self):
        """Count visible GENERIC_COMMENTs (no bounties) in threads whose root
        comment is also GENERIC_COMMENT, regardless of whether the root itself
        is removed."""
        return self._countable_discussion_comments().count()

    def get_discussion_aggregates(self, item):
        discussion_count = self._countable_discussion_comments().count()

        # Single aggregate query for other counts
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
        )

        # Add discussion_count and conversation_count
        aggregator["discussion_count"] = discussion_count
        aggregator["conversation_count"] = discussion_count
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
        content_object = self._safe_content_object()
        if content_object is None:
            return None
        return content_object.unified_document

    def _safe_content_object(self):
        """
        Resolve `content_object` defensively.

        Returns None if the underlying ContentType points to a model that is
        no longer registered (stale `django_content_type` row, e.g. from a
        removed/renamed app) or if the target object no longer exists.
        """
        try:
            model_class = self.content_type.model_class()
        except Exception:
            return None
        if model_class is None:
            return None
        try:
            return self.content_object
        except (AttributeError, model_class.DoesNotExist):
            return None
