from django.db import models
from django.contrib.contenttypes.fields import GenericRelation

from discussion.reaction_models import AbstractGenericReactionModel
from researchhub_document.models import ResearchhubUnifiedDocument
from user.models import User


class Hypothesis(AbstractGenericReactionModel):
    actions = GenericRelation(
        'user.Action',
        object_id_field='object_id',
        content_type_field='content_type',
        related_query_name='hypothesis'
    )
    created_by = models.ForeignKey(
        User,
        db_index=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name='created_hypotheses',
    )
    renderable_text = models.TextField(
        null=True
    )
    result_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True
    )
    slug = models.SlugField(max_length=1024)
    src = models.FileField(
        blank=True,
        null=True,
        default=None,
        max_length=512,
        upload_to='uploads/hypothesis/%Y/%m/%d/',
    )
    title = models.TextField(blank=True, default='')
    unified_document = models.OneToOneField(
        ResearchhubUnifiedDocument,
        blank=True,
        null=True,
        on_delete=models.CASCADE,
        related_name='hypothesis'
    )

    def calculate_result_score(self, save=False):
        pass

    @property
    def users_to_notify(self):
        return [self.created_by]
