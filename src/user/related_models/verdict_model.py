from django.db import models

from discussion.reaction_models import Flag
from utils.models import DefaultModel

# TODO: Migrate
ABUSIVE_OR_RUDE = "ABUSIVE_OR_RUDE"
COPYRIGHT = "COPYRIGHT"
LOW_QUALITY = "LOW_QUALITY"
NOT_CONSTRUCTIVE = "NOT_CONSTRUCTIVE"
PLAGIARISM = "PLAGIARISM"
SPAM = "SPAM"

FLAG_REASON_CHOICES = [
    (ABUSIVE_OR_RUDE, ABUSIVE_OR_RUDE),
    (COPYRIGHT, COPYRIGHT),
    (LOW_QUALITY, LOW_QUALITY),
    (NOT_CONSTRUCTIVE, NOT_CONSTRUCTIVE),
    (PLAGIARISM, PLAGIARISM),
    (SPAM, SPAM),
]


class Verdict(DefaultModel):
    created_by = models.ForeignKey(
        "user.User", related_name="verdicts", on_delete=models.CASCADE
    )
    flag = models.OneToOneField(Flag, related_name="verdict", on_delete=models.CASCADE)
    verdict_choice = models.CharField(choices=FLAG_REASON_CHOICES, max_length=32)
    is_content_removed = models.BooleanField(default=True)
