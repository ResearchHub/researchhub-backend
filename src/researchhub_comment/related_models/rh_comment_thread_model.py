from django.contrib.contenttypes.fields import GenericRelation
from django.db import connection, models
from django.db.models import CharField, Count, JSONField, Q
from django.db.models.functions import Cast

from researchhub_access_group.models import Permission
from researchhub_comment.constants.rh_comment_thread_types import (
    GENERIC_COMMENT,
    PEER_REVIEW,
    RH_COMMENT_THREAD_TYPES,
    SUMMARY,
)
from utils.models import AbstractGenericRelationModel


class RhCommentThreadQuerySet(models.QuerySet):
    def get_discussion_count(self):
        """
        Uses a recursive CTE to count all comments (including replies)
        ignoring removed comments, for all threads in this QuerySet.
        """
        thread_ids = list(self.values_list("id", flat=True))
        if not thread_ids:
            return 0

        query = """
            WITH RECURSIVE comment_tree AS (
                SELECT c.id, c.parent_id, 1 AS comment_count
                FROM researchhub_comment_rhcommentmodel c
                JOIN researchhub_comment_rhcommentthreadmodel t ON c.thread_id = t.id
                WHERE c.parent_id IS NULL
                  AND c.is_removed = FALSE
                  AND t.id IN (SELECT UNNEST(%s))

                UNION ALL

                SELECT c.id, c.parent_id, 1
                FROM researchhub_comment_rhcommentmodel c
                JOIN comment_tree ct ON c.parent_id = ct.id
                WHERE c.is_removed = FALSE
            )
            SELECT COALESCE(SUM(comment_count), 0)::int AS total_count
            FROM comment_tree;
        """

        with connection.cursor() as cursor:
            cursor.execute(query, [thread_ids])
            result = cursor.fetchone()
            return result[0] if result else 0

    def get_discussion_aggregates(self):
        """
        Example aggregator, adapted from your code.
        Note: self.exclude(...) etc. uses the QuerySet instead of Manager.
        """
        aggregator = self.exclude(rh_comments__bounties__isnull=False).aggregate(
            review_count=Count(
                "rh_comments",
                filter=Q(
                    thread_type=PEER_REVIEW,
                    rh_comments__is_removed=False,
                    rh_comments__parent__isnull=False,
                    rh_comments__parent__bounties__isnull=True,
                ),
            ),
            summary_count=Count(
                "rh_comments",
                filter=Q(
                    thread_type=SUMMARY,
                    rh_comments__is_removed=False,
                    rh_comments__parent__isnull=False,
                    rh_comments__parent__bounties__isnull=True,
                ),
            ),
        )

        aggregator["discussion_count"] = self.get_discussion_count()
        return aggregator


class RhCommentThreadManager(models.Manager):
    def get_queryset(self):
        return RhCommentThreadQuerySet(self.model, using=self._db)

    def get_discussion_count(self):
        return self.get_queryset().get_discussion_count()

    def get_discussion_aggregates(self):
        return self.get_queryset().get_discussion_aggregates()


class RhCommentThreadModel(AbstractGenericRelationModel):
    thread_type = CharField(
        max_length=144,
        choices=RH_COMMENT_THREAD_TYPES,
        default=GENERIC_COMMENT,
    )
    thread_reference = CharField(
        blank=True,
        help_text="A thread may need a special referencing tool. Use this field for such a case",
        max_length=144,
        null=True,
    )
    anchor = JSONField(blank=True, null=True)
    permissions = GenericRelation(Permission, related_name="rh_thread")

    objects = RhCommentThreadManager()

    @property
    def unified_document(self):
        return self.content_object.unified_document
