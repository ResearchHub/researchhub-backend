from django.contrib.contenttypes.fields import GenericRelation
from django.db import models
from django.db.models import Avg, Count, Q
from django.utils.functional import cached_property

from hub.models import Hub
from researchhub.settings import BASE_FRONTEND_URL
from researchhub_access_group.models import Permission
from researchhub_document.hot_score_mixin import HotScoreMixin
from researchhub_document.related_models.constants.document_type import (
    BOUNTY,
    DISCUSSION,
    DOCUMENT_TYPES,
    HYPOTHESIS,
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
        default=0,
        help_text="Feed ranking score.",
    )
    hot_score_v2 = models.IntegerField(
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
                fields=("document_type",),
                name="uni_doc_cond_idx",
                condition=Q(is_removed=False)
                & ~Q(document_type=NOTE)
                & Q(document_filter__isnull=False),
            ),
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
            return self.paper.authors.all()

        if hasattr(self, "hypothesis"):
            author = Author.objects.filter(user=self.hypothesis.created_by)
            return author

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
        elif self.document_type == HYPOTHESIS:
            doc_url = "hypothesis"
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
        elif self.document_type == HYPOTHESIS:
            return "hypothesis"
        elif self.document_type == PREREGISTRATION:
            return "preregistration"
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

    def get_document(self):
        if self.document_type == PAPER:
            return self.paper
        elif self.document_type == DISCUSSION:
            return self.posts.first()
        elif self.document_type == HYPOTHESIS:
            return self.hypothesis
        elif self.document_type == NOTE:
            return self.note
        elif self.document_type == QUESTION:
            return self.posts.first()
        elif self.document_type == BOUNTY:
            return self.posts.first()
        elif self.document_type == PREREGISTRATION:
            return self.posts.first()
        else:
            raise Exception(f"Unrecognized document_type: {self.document_type}")

    @cached_property
    def fe_document_type(self):
        document_type = self.document_type
        if document_type == HYPOTHESIS:
            return "META-STUDY"
        elif document_type == DISCUSSION:
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
        details = {"avg": 0, "count": 0}
        reviews = self.reviews
        if reviews.exists():
            details = reviews.aggregate(avg=Avg("score"), count=Count("id"))
        return details

    def frontend_view_link(self):
        doc = self.get_document()
        document_type = self.document_type
        if document_type in (QUESTION, DISCUSSION, POSTS, BOUNTY, PREREGISTRATION):
            document_type = "post"
        url = f"{BASE_FRONTEND_URL}/{document_type.lower()}/{doc.id}/{doc.slug}"
        return url

    def save(self, **kwargs):
        if getattr(self, "document_filter", None) is None:
            self.document_filter = DocumentFilter.objects.create()
        super().save(**kwargs)

        # Update the Elastic Search index for post records.
        try:
            for post in self.posts.all():
                update_elastic_registry.apply_async(post)
        except:
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
