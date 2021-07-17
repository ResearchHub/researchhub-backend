from django.db import models
from django_elasticsearch_dsl.registries import registry

from hub.models import Hub
from paper.models import Paper
from user.models import Author
from researchhub_access_group.models import ResearchhubAccessGroup
from researchhub_document.related_models.constants.document_type import (
  DOCUMENT_TYPES, PAPER
)
from utils.models import DefaultModel


class ResearchhubUnifiedDocument(DefaultModel):
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
    access_group = models.OneToOneField(
        ResearchhubAccessGroup,
        blank=True,
        help_text='Mostly used for ELN',
        null=True,
        on_delete=models.SET_NULL,
        related_name='document'
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
        paper = self.paper
        if paper:
            return paper.authors.all()

        posts = self.posts
        if posts:
            # This property needs to return a queryset
            # which is why we are filtering by authors
            post = posts.last()
            author = Author.objects.filter(
                user=post.created_by
            )
            return author
        return self.none()

    @property
    def is_public(self):
        if (self.access_group is None):
            return True
        else:
            return self.access_group.is_public

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
                registry.update(post)
        except:
            pass
