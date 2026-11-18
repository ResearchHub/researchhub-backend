from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from utils.models import DefaultModel


class ContentScreening(DefaultModel):
    """Jev's moderation scores for a piece of user content, flagged or not.

    ``scores`` maps each question asked to the probability Jev gave "true". Edited
    content is screened again, so an item can have several screenings.
    """

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    item = GenericForeignKey("content_type", "object_id")
    model = models.CharField(max_length=255)
    scores = models.JSONField()
    flagged = models.BooleanField()
    cost_microusd = models.PositiveBigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "research_ai_content_screening"
        indexes = [
            models.Index(
                fields=["content_type", "object_id"], name="ra_content_screening_item"
            ),
        ]
