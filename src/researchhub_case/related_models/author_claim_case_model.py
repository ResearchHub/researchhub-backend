from django.db import models

from paper.models import Paper
from paper.related_models.authorship_model import Authorship
from reputation.models import Escrow
from reputation.related_models.paper_reward import PaperReward
from researchhub_case.constants.case_constants import AUTHOR_CLAIM_CASE_STATUS, OPEN
from researchhub_case.related_models.researchhub_case_abstract_model import (
    AbstractResearchhubCase,
)
from user.models import Author


class AuthorClaimCase(AbstractResearchhubCase):
    provided_email = models.EmailField(
        blank=False,
        help_text=(
            "Requestors may use this field to validate themselves with this email"
        ),
        null=False,
    )
    status = models.CharField(
        choices=AUTHOR_CLAIM_CASE_STATUS,
        default=OPEN,
        max_length=32,
        null=False,
    )
    target_paper_doi = models.CharField(max_length=255, null=True)
    target_paper_title = models.CharField(max_length=1024, null=True)
    token_generated_time = models.IntegerField(
        blank=True,
        default=None,
        help_text="Intentionally setting as a int field",
        null=True,
    )
    validation_attempt_count = models.IntegerField(
        blank=False,
        default=-1,
        help_text="Number of attempts to validate themselves given token",
        null=False,
    )
    validation_token = models.CharField(
        blank=True,
        db_index=True,
        default=None,
        help_text="See author_claim_case_post_create_signal",
        max_length=255,
        null=True,
        unique=True,
    )
    target_paper = models.ForeignKey(
        Paper,
        blank=False,
        null=True,
        on_delete=models.CASCADE,
        related_name="related_claim_cases",
    )
    claimed_rsc = models.ManyToManyField(Escrow, blank=True, related_name="claim_case")
    preregistration_url = models.URLField(
        blank=True,
        help_text="URL to preregistration",
        null=True,
    )

    open_data_url = models.URLField(
        blank=True,
        help_text="URL to open data",
        null=True,
    )

    paper_reward = models.ForeignKey(
        PaperReward,
        blank=True,
        null=True,
        on_delete=models.PROTECT,
    )

    version = models.IntegerField(
        default=1,
        help_text="Version of the case",
        null=False,
        blank=False,
    )
