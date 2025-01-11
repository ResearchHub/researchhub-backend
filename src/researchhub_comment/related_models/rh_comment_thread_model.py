from django.contrib.contenttypes.fields import GenericRelation
from django.db import models
from django.db.models import CharField, Count, JSONField, Q

from researchhub_access_group.models import Permission
from researchhub_comment.constants.rh_comment_thread_types import (
    GENERIC_COMMENT,
    PEER_REVIEW,
    RH_COMMENT_THREAD_TYPES,
    SUMMARY,
)
from utils.models import AbstractGenericRelationModel

"""
    NOTE: RhCommentThreadModel's generic relation convention is to
        - setup relations through AbstractGenericRelationModel
        - add an edge named `rh_threads` for inverse reference on top of a target [content] model
        - (see Hypothesis Model for reference)

    This allows queries such as [ContentModel].rh_threads[...]
    where [ContentModels] may be found in method "get_valid_target_content_model"
"""


class RhCommentThreadManager(models.Manager):
    def get_discussion_aggregates(self):
        return self.exclude(rh_comments__bounties__isnull=False).aggregate(
            discussion_count=self.get_discussion_count(),
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

    def get_discussion_count(self):
        from researchhub_comment.models import RhCommentModel

        query = """
            WITH RECURSIVE comments AS (
                SELECT id, parent_id, 0 AS relative_depth
                FROM "researchhub_comment_rhcommentmodel"
                WHERE id = %s

                UNION ALL

                SELECT child.id, child.parent_id, comments.relative_depth + 1
                FROM "researchhub_comment_rhcommentmodel" child, comments
                WHERE child.parent_id = comments.id AND child.is_removed = FALSE
            )
            SELECT id
            FROM comments;
        """

        discussion_count = 0
        for thread in self.all():
            parent_comment = thread.rh_comments.filter(
                parent_id__isnull=True,
                is_removed=False,
            ).first()

            if parent_comment:
                discussion_count += len(
                    RhCommentModel.objects.raw(query, [parent_comment.id])
                )

        return discussion_count


class RhCommentThreadModel(AbstractGenericRelationModel):
    """--- MODEL FIELDS ---"""

    thread_type = CharField(
        max_length=144,
        choices=RH_COMMENT_THREAD_TYPES,
        default=GENERIC_COMMENT,
    )
    thread_reference = CharField(
        blank=True,
        help_text="""A thread may need a special referencing tool. Use this field for such a case""",
        max_length=144,
        null=True,
    )
    anchor = JSONField(blank=True, null=True)
    permissions = GenericRelation(
        Permission,
        related_name="rh_thread",
    )

    """--- OBJECT MANAGER ---"""
    objects = RhCommentThreadManager()

    """ --- PROPERTIES --- """

    @property
    def unified_document(self):
        return self.content_object.unified_document

    """--- METHODS ---"""
