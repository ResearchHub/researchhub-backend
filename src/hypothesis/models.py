from django.db import models
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericRelation

from discussion.reaction_models import AbstractGenericReactionModel
from researchhub_document.models import ResearchhubUnifiedDocument
from user.models import User


class Hypothesis(AbstractGenericReactionModel):
    created_by = models.ForeignKey(
        User,
        db_index=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name='created_hypotheses',
    )
    unified_document = models.OneToOneField(
        ResearchhubUnifiedDocument,
        blank=True,
        null=True,
        on_delete=models.CASCADE,
        related_name='hypothesis'
    )
    actions = GenericRelation(
        'user.Action',
        object_id_field='object_id',
        content_type_field='content_type',
        related_query_name='hypothesis'
    )

    slug = models.SlugField(max_length=1024)
    result_score = models.DecimalField(
        max_digits=5,
        decimal_places=2
    )
    title = models.TextField(blank=True, default='')

    def calculate_result_score(self, save=False):
        pass


class Citation(AbstractGenericReactionModel):
    cited_by = models.ManyToManyField(
        User,
        related_name='citations',
    )
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE
    )
    object_id = models.PositiveIntegerField()
    item = GenericForeignKey(
        'content_type',
        'object_id'
    )
    hypothesis = models.ForeignKey(
        Hypothesis,
        db_index=True,
        null=False,
        on_delete=models.CASCADE,
        related_name='citations'
    )
