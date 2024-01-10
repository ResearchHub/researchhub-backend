from django.db import models

from discussion.constants.flag_reasons import VERDICT_REASON_CHOICES
from discussion.reaction_models import Flag
from utils.models import DefaultModel


class Verdict(DefaultModel):
    created_by = models.ForeignKey(
        "user.User", related_name="verdicts", on_delete=models.CASCADE
    )
    flag = models.OneToOneField(Flag, related_name="verdict", on_delete=models.CASCADE)
    verdict_choice = models.CharField(choices=VERDICT_REASON_CHOICES, max_length=32)
    is_content_removed = models.BooleanField(default=True)

    # This is for the case where we remove the PDF but keep the content of the paper,
    # Due to copyright issues on the PDF.
    is_paper_pdf_removed = models.BooleanField(default=False)
