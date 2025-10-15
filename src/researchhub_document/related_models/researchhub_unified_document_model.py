from django.contrib.contenttypes.fields import GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Avg, Count, DecimalField, Q, Sum
from django.db.models.functions import Cast
from django.utils.functional import cached_property

from hub.models import Hub
from researchhub.settings import BASE_FRONTEND_URL
from researchhub_access_group.models import Permission
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_document.hot_score_mixin import HotScoreMixin
from researchhub_document.related_models.constants.document_type import (
    BOUNTY,
    DISCUSSION,
    DOCUMENT_TYPES,
    GRANT,
    NOTE,
    PAPER,
    POSTS,
    PREREGISTRATION,
    QUESTION,
)
from researchhub_document.related_models.document_filter_model import DocumentFilter
from researchhub_document.tasks import update_elastic_registry
from user.models import Author
from utils.models import DefaultModel, SoftDeletableModel


class ResearchhubUnifiedDocument(SoftDeletableModel, HotScoreMixin, DefaultModel):
    document_type = models.CharField(
        choices=DOCUMENT_TYPES,
        default=PAPER,
        max_length=32,
        null=False,
        help_text="Papers are imported from external src. Posts are in-house",
    )
    published_date = models.DateTimeField(auto_now_add=True, null=True)
    score = models.IntegerField(
        default=0,
        db_index=True,
        help_text="Another feed ranking score.",
    )
    hot_score = models.IntegerField(
        default=0, help_text="Feed ranking score.", db_index=True
    )
    permissions = GenericRelation(
        Permission,
        related_name="unified_document",
        related_query_name="uni_doc_source",
    )
    bounties = GenericRelation(
        "reputation.Bounty",
        content_type_field="item_content_type",
        object_id_field="item_object_id",
    )
    hubs = models.ManyToManyField(Hub, related_name="related_documents", blank=True)
    document_filter = models.OneToOneField(
        DocumentFilter,
        on_delete=models.CASCADE,
        related_name="unified_document",
        null=True,
    )
    concepts = models.ManyToManyField(
        "tag.Concept",
        related_name="documents",
        blank=True,
        through="UnifiedDocumentConcepts",
    )
    topics = models.ManyToManyField(
        "topic.Topic",
        related_name="documents",
        blank=True,
        through="topic.UnifiedDocumentTopics",
    )

    class Meta:
        indexes = (
            models.Index(
                fields=("created_date",),
                name="uni_doc_created_date_idx",
            ),
            models.Index(
                fields=("document_type",),
                name="uni_doc_not_note_doc_type_idx",
                condition=~Q(document_type=NOTE),
            ),
            models.Index(
                fields=["document_type", "-hot_score"], name="doc_type_hot_score_idx"
            ),
            models.Index(
                fields=("document_type",),
                name="uni_doc_cond_idx",
                condition=Q(is_removed=False)
                & ~Q(document_type=NOTE)
                & Q(document_filter__isnull=False),
            ),
            models.Index(
                fields=[
                    "is_removed",
                    "document_type",
                    "hot_score",
                    "document_filter",
                ],
                name="idx_paper_filter_sort",
                condition=Q(document_type="PAPER"),
            ),
            models.Index(
                fields=["hot_score"],
                name="idx_unified_doc_hot_score",
            ),
            models.Index(
                fields=["is_removed", "document_type", "hot_score"],
                name="idx_document_type_hot_score",
            ),
            models.Index(fields=["document_type"], name="idx_document_type"),
        )

    def update_filter(self, filter_type):
        if self.document_filter:
            self.document_filter.update_filter(filter_type)

    def update_filters(self, filter_types):
        for filter_type in filter_types:
            self.update_filter(filter_type)

    @property
    def authors(self):
        # This property needs to return a queryset
        # which is why we are filtering by authors

        if hasattr(self, "paper"):
            return self.paper.authorships.all()

        posts = self.posts
        if posts.exists():
            post = posts.last()
            author = Author.objects.filter(user=post.created_by)
            return author
        return Author.objects.none()

    def get_url(self):
        if self.document_type == PAPER:
            doc_url = "paper"
        elif self.document_type == DISCUSSION:
            doc_url = "post"
        else:
            # TODO: fill this with proper url for other doc types
            return None

        doc = self.get_document()

        return "{}/{}/{}/{}".format(BASE_FRONTEND_URL, doc_url, doc.id, doc.slug)

    def get_client_doc_type(self):
        if self.document_type == PAPER:
            return "paper"
        elif self.document_type == DISCUSSION:
            return "post"
        elif self.document_type == PREREGISTRATION:
            return "preregistration"
        elif self.document_type == GRANT:
            return "grant"
        elif self.document_type == QUESTION:
            return "question"
        elif self.document_type == NOTE:
            return "note"
        elif self.document_type == BOUNTY:
            return "bounty"
        else:
            raise Exception(f"Unrecognized document_type: {self.document_type}")

    def get_hub_names(self):
        return ",".join(self.hubs.values_list("name", flat=True))

    def get_primary_hub(self, fallback=False):
        from topic.models import UnifiedDocumentTopics

        primary_topic = UnifiedDocumentTopics.objects.filter(
            unified_document=self, is_primary=True
        ).first()

        if primary_topic:
            return Hub.objects.filter(
                subfield_id=primary_topic.topic.subfield_id
            ).first()

        if fallback:
            return self.hubs.first()

        return None

    def get_document(self):
        if self.document_type == PAPER:
            return self.paper
        elif self.document_type == DISCUSSION:
            return self.posts.first()
        elif self.document_type == NOTE:
            return self.note
        elif self.document_type == QUESTION:
            return self.posts.first()
        elif self.document_type == BOUNTY:
            return self.posts.first()
        elif self.document_type == PREREGISTRATION:
            return self.posts.first()
        elif self.document_type == GRANT:
            return self.posts.first()
        else:
            raise Exception(f"Unrecognized document_type: {self.document_type}")

    @cached_property
    def fe_document_type(self):
        document_type = self.document_type
        if document_type == DISCUSSION:
            return "POST"
        return document_type

    @cached_property
    def created_by(self):
        if self.document_type == PAPER:
            return self.paper.uploaded_by
        else:
            first_post = self.posts.first()
            if first_post is not None:
                return first_post.created_by
            return None

    def get_review_details(self):
        """Return average score & count of *active* reviews.

        A review is considered active if:
        1. The review itself has not been soft-deleted (`is_removed=False`).
        2. The underlying comment (`RhCommentModel`) it references has not been
           soft-deleted.
        """

        comment_content_type = ContentType.objects.get_for_model(RhCommentModel)

        active_comment_ids = RhCommentModel.objects.filter(is_removed=False).values(
            "id"
        )

        reviews = self.reviews.filter(
            is_removed=False,
            content_type=comment_content_type,
            object_id__in=active_comment_ids,
        )

        if reviews.exists():
            details = reviews.aggregate(avg=Avg("score"), count=Count("id"))
        else:
            details = {"avg": 0, "count": 0}
        return details

    def frontend_view_link(self):
        doc = self.get_document()
        document_type = self.document_type
        if document_type in (
            QUESTION,
            DISCUSSION,
            POSTS,
            BOUNTY,
            PREREGISTRATION,
            GRANT,
        ):
            document_type = "post"
        url = f"{BASE_FRONTEND_URL}/{document_type.lower()}/{doc.id}/{doc.slug}"
        return url

    # ========================================================================
    # Comment Helper Methods for Hot Score Calculation
    # ========================================================================

    def get_all_comments(self, include_removed=False):
        """
        Get all comments on this document across all threads.

        Args:
            include_removed: If True, include soft-deleted comments

        Returns:
            QuerySet of RhCommentModel instances
        """
        if not hasattr(self, "rh_threads"):
            return RhCommentModel.objects.none()

        thread_ids = self.rh_threads.values_list("id", flat=True)

        if include_removed:
            return RhCommentModel.all_objects.filter(thread_id__in=thread_ids)
        else:
            return RhCommentModel.objects.filter(thread_id__in=thread_ids)

    def get_peer_review_comments(self):
        """
        Get all peer review and community review comments.

        Returns:
            QuerySet of RhCommentModel instances
        """
        from researchhub_comment.constants.rh_comment_thread_types import (
            COMMUNITY_REVIEW,
            PEER_REVIEW,
        )

        return self.get_all_comments().filter(
            Q(comment_type=PEER_REVIEW) | Q(comment_type=COMMUNITY_REVIEW)
        )

    def get_regular_comments(self):
        """
        Get all regular comments (excluding peer reviews).

        Returns:
            QuerySet of RhCommentModel instances
        """
        from researchhub_comment.constants.rh_comment_thread_types import (
            COMMUNITY_REVIEW,
            PEER_REVIEW,
        )

        return self.get_all_comments().exclude(
            Q(comment_type=PEER_REVIEW) | Q(comment_type=COMMUNITY_REVIEW)
        )

    def get_comment_upvote_sum(self):
        """
        Get sum of all upvotes on comments.

        Returns:
            int: Total upvotes across all comments
        """
        comments = self.get_all_comments()
        total = comments.aggregate(total_score=Sum("score"))["total_score"]
        return total if total else 0

    def get_comment_tip_sum(self):
        """
        Get sum of all tips/boosts on comments.

        Returns:
            float: Total tip amount across all comments
        """
        from purchase.models import Purchase

        comments = self.get_all_comments()
        comment_content_type = ContentType.objects.get_for_model(RhCommentModel)

        tips = Purchase.objects.filter(
            content_type=comment_content_type,
            object_id__in=comments.values_list("id", flat=True),
            purchase_type=Purchase.BOOST,
            paid_status=Purchase.PAID,
        ).aggregate(
            total=Sum(Cast("amount", DecimalField(max_digits=19, decimal_places=10)))
        )[
            "total"
        ]

        if tips:
            try:
                return float(tips)
            except (ValueError, TypeError):
                return 0
        return 0

    def save(self, **kwargs):
        if getattr(self, "document_filter", None) is None:
            self.document_filter = DocumentFilter.objects.create()
        super().save(**kwargs)

        # Update the Elastic Search index for post records.
        try:
            for post in self.posts.all():
                update_elastic_registry.apply_async(post)
        except Exception:
            pass


class UnifiedDocumentConcepts(DefaultModel):
    unified_document = models.ForeignKey(
        ResearchhubUnifiedDocument,
        on_delete=models.CASCADE,
    )

    concept = models.ForeignKey(
        "tag.Concept",
        related_name="through_unified_document",
        blank=True,
        on_delete=models.CASCADE,
    )

    relevancy_score = models.FloatField(
        default=0.0,
    )

    level = models.IntegerField(
        default=0,
    )


class ResearchhubUnifiedDocumentHub(models.Model):
    researchhubunifieddocument = models.ForeignKey(
        ResearchhubUnifiedDocument, on_delete=models.CASCADE
    )
    hub = models.ForeignKey(Hub, on_delete=models.CASCADE)

    class Meta:
        indexes = [
            models.Index(
                fields=["hub", "researchhubunifieddocument"], name="idx_hub_unified_doc"
            ),
            models.Index(
                fields=["researchhubunifieddocument", "hub"], name="idx_unified_doc_hub"
            ),
        ]
        unique_together = ("researchhubunifieddocument", "hub")
