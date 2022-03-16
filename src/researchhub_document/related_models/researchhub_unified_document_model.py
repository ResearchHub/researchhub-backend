from django.db import models
from django.contrib.contenttypes.fields import GenericRelation

from hub.models import Hub
from paper.models import Paper
from user.models import Author
from researchhub_access_group.models import Permission
from researchhub_document.related_models.constants.document_type import (
  DOCUMENT_TYPES, PAPER, DISCUSSION, HYPOTHESIS, NOTE
)
from utils.models import DefaultModel
from researchhub_document.tasks import (
    update_elastic_registry
)
from researchhub_document.hot_score_mixin2 import HotScoreMixin


class ResearchhubUnifiedDocument(DefaultModel, HotScoreMixin):
    is_public = models.BooleanField(
        default=True,
        help_text='Unified document is public'
    )
    is_removed = models.BooleanField(
        default=False,
        db_index=True,
        help_text='Unified Document is removed (deleted)'
    )
    document_type = models.CharField(
      choices=DOCUMENT_TYPES,
      default=PAPER,
      max_length=32,
      null=False,
      help_text='Papers are imported from external src. Posts are in-house'
    )
    published_date = models.DateTimeField(
        auto_now_add=True,
        null=True
    )
    score = models.IntegerField(
        default=0,
        db_index=True,
        help_text='Another feed ranking score.',
    )
    hot_score = models.IntegerField(
        default=0,
        help_text='Feed ranking score.',
    )
    hot_score_v2 = models.IntegerField(
        default=0,
        help_text='Feed ranking score.',
    )
    permissions = GenericRelation(
        Permission,
        related_name='unified_document',
        related_query_name='uni_doc_source',
    )
    paper = models.OneToOneField(
        Paper,
        db_index=True,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='unified_document',
    )
    hubs = models.ManyToManyField(
        Hub,
        related_name='related_documents',
        blank=True
    )

    @property
    def authors(self):
        # This property needs to return a queryset
        # which is why we are filtering by authors

        paper = self.paper
        if paper:
            return paper.authors.all()

        if hasattr(self, 'hypothesis'):
            author = Author.objects.filter(
                user=self.hypothesis.created_by
            )
            return author

        posts = self.posts
        if posts.exists():
            post = posts.last()
            author = Author.objects.filter(
                user=post.created_by
            )
            return author
        return self.none()

    def get_document(self):
        if (self.document_type == PAPER):
            return self.paper
        elif (self.document_type == DISCUSSION):
            return self.posts.first()
        elif (self.document_type == HYPOTHESIS):
            return self.hypothesis
        elif (self.document_type == NOTE):
            return self.note
        else:
            raise Exception(f"Unrecognized document_type: {self.document_type}")

    @property
    def created_by(self):
        if (self.document_type == PAPER):
            return self.paper.uploaded_by
        else:
            first_post = self.posts.first()
            if (first_post is not None):
                return first_post.created_by
            return None

    def save(self, **kwargs):
        super().save(**kwargs)

        # Update the Elastic Search index for post records.
        try:
            for post in self.posts.all():
                update_elastic_registry.apply_async(post)
        except:
            pass
