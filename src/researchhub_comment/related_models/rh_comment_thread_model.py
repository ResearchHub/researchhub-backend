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
        Counts top-level generic comments without bounties across all threads
        in this QuerySet, plus all their nested children comments.
        """
        from researchhub_comment.models import RhCommentModel

        # Count *all* generic, non-removed comments that do **not** have a
        # bounty attached – hierarchy (parent/child) no longer matters since a
        # censored parent should **not** hide its visible children from the
        # discussion count.

        visible_comments = RhCommentModel.objects.filter(
            thread__in=self,
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
        # Review comments should ignore those with bounties. Start from a
        # queryset that excludes comments carrying bounties.
        review_qs = self.exclude(rh_comments__bounties__isnull=False)

        aggregator = review_qs.aggregate(
            review_count=Count(
                "rh_comments",
                filter=Q(
                    rh_comments__comment_type__in=[PEER_REVIEW, COMMUNITY_REVIEW],
                    rh_comments__is_removed=False,
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
