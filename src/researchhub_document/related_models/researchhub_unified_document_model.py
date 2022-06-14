from statistics import mean

from django.contrib.contenttypes.fields import GenericRelation
from django.db import models
from django.db.models import Avg

from hub.models import Hub
from researchhub_access_group.models import Permission
from researchhub_document.hot_score_mixin import HotScoreMixin
from researchhub_document.related_models.constants.document_type import (
    DISCUSSION,
    DOCUMENT_TYPES,
    HYPOTHESIS,
    NOTE,
    PAPER,
)
from researchhub_document.tasks import update_elastic_registry
from review.models.review_model import Review
from user.models import Author
from utils.models import DefaultModel


class ResearchhubUnifiedDocument(DefaultModel, HotScoreMixin):
    is_public = models.BooleanField(
        default=True, help_text="Unified document is public"
    )
    is_removed = models.BooleanField(
        default=False, db_index=True, help_text="Unified Document is removed (deleted)"
    )
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
        default=0,
        help_text="Feed ranking score.",
    )
    permissions = GenericRelation(
        Permission,
        related_name="unified_document",
        related_query_name="uni_doc_source",
    )
    hubs = models.ManyToManyField(Hub, related_name="related_documents", blank=True)

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
        return self.none()

    def get_document(self):
        if self.document_type == PAPER:
            return self.paper
        elif self.document_type == DISCUSSION:
            return self.posts.first()
        elif self.document_type == HYPOTHESIS:
            return self.hypothesis
        elif self.document_type == NOTE:
            return self.note
        else:
            raise Exception(f"Unrecognized document_type: {self.document_type}")

    @property
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
        reviews = self.reviews.values_list("score", flat=True)
        if reviews:
            details["avg"] = round(mean(reviews), 1)
            details["count"] = reviews.count()
        return details

    def old_get_review_details(self):
        details = {"avg": 0, "count": 0}

        review_scores = Review.objects.filter(
            unified_document=self, is_removed=False
        ).values("score")

        details["count"] = review_scores.count()

        if review_scores.count() > 0:
            details["avg"] = round(review_scores.aggregate(avg=Avg("score"))["avg"], 1)

        return details

    def save(self, **kwargs):
        super().save(**kwargs)

        # Update the Elastic Search index for post records.
        try:
            for post in self.posts.all():
                update_elastic_registry.apply_async(post)
        except:
            pass
