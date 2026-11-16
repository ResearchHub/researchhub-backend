from django.db import models

from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from utils.models import DefaultModel


class CommentSpamScreening(DefaultModel):
    """Jev's spam scores for a comment, whether or not they flagged it.

    Edits are screened again, so a comment can have several screenings.
    """

    comment = models.ForeignKey(
        RhCommentModel, on_delete=models.CASCADE, related_name="spam_screenings"
    )
    model = models.CharField(max_length=255)
    promotional = models.FloatField()
    solicitation = models.FloatField()
    off_topic = models.FloatField()
    flagged = models.BooleanField()
    cost_microusd = models.PositiveBigIntegerField(null=True, blank=True)
