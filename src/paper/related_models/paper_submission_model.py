from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import models

from paper.related_models.paper_model import Paper
from utils.models import DefaultModel


class PaperSubmission(DefaultModel):
    COMPLETE = "COMPLETE"
    INITIATED = "INITIATED"
    FAILED = "FAILED"
    FAILED_DUPLICATE = "FAILED_DUPLICATE"
    FAILED_TIMEOUT = "FAILED_TIMEOUT"
    FAILED_DOI = "FAILED_DOI"
    PROCESSING = "PROCESSING"
    PROCESSING_CROSSREF = "PROCESSING_CROSSREF"
    PROCESSING_MANUBOT = "PROCESSING_MANUBOT"
    PROCESSING_DOI = "PROCESSING_DOI"
    PROCESSING_OPENALEX = "PROCESSING_OPENALEX"
    PROCESSING_SEMANTIC_SCHOLAR = "PROCESSING_SEMANTIC_SCHOLAR"
    PROCESSING_UNPAYWALL = "PROCESSING_UNPAYWALL"

    PAPER_STATUS_CHOICES = [
        (COMPLETE, COMPLETE),
        (INITIATED, INITIATED),
        (FAILED, FAILED),
        (FAILED, FAILED_DUPLICATE),
        (FAILED_TIMEOUT, FAILED_TIMEOUT),
        (FAILED_DOI, FAILED_DOI),
        (PROCESSING, PROCESSING),
        (PROCESSING_CROSSREF, PROCESSING_CROSSREF),
        (PROCESSING_MANUBOT, PROCESSING_MANUBOT),
        (PROCESSING_OPENALEX, PROCESSING_OPENALEX),
        (PROCESSING_SEMANTIC_SCHOLAR, PROCESSING_SEMANTIC_SCHOLAR),
        (PROCESSING_UNPAYWALL, PROCESSING_UNPAYWALL),
        (PROCESSING_DOI, PROCESSING_DOI),
    ]
    doi = models.CharField(
        blank=True,
        null=True,
        max_length=255,
    )
    paper = models.OneToOneField(
        Paper,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="submission",
    )
    paper_status = models.CharField(
        choices=PAPER_STATUS_CHOICES, default=INITIATED, max_length=32
    )
    status_read = models.BooleanField(default=False)
    url = models.URLField(blank=True, null=True, max_length=1024)
    citation = models.ForeignKey(
        "citation.CitationEntry",
        null=True,
        blank=True,
        related_name="paper_submissions",
        on_delete=models.CASCADE,
    )
    uploaded_by = models.ForeignKey(
        "user.User",
        related_name="paper_submissions",
        on_delete=models.CASCADE,
        help_text="""
            RH User account that submitted this paper.
            NOTE: user didnt necessarily had to be the author.
        """,
    )

    def set_status(self, status, save=True):
        self.paper_status = status
        self.status_read = False
        if save:
            self.save()

    def set_complete_status(self, save=True):
        self.set_status(self.COMPLETE, save)

    def set_processing_status(self, save=True):
        self.set_status(self.PROCESSING, save)

    def set_duplicate_status(self, save=True):
        self.set_status(self.FAILED_DUPLICATE, save)

    def set_manubot_status(self, save=True):
        self.set_status(self.PROCESSING_MANUBOT, save)

    def set_crossref_status(self, save=True):
        self.set_status(self.PROCESSING_CROSSREF, save)

    def set_openalex_status(self, save=True):
        self.set_status(self.PROCESSING_OPENALEX, save)

    def set_semantic_scholar_status(self, save=True):
        self.set_status(self.PROCESSING_SEMANTIC_SCHOLAR, save)

    def set_unpaywall_status(self, save=True):
        self.set_status(self.PROCESSING_UNPAYWALL, save)

    def set_processing_doi_status(self, save=True):
        self.set_status(self.PROCESSING_DOI, save)

    def set_failed_status(self, save=True):
        self.set_status(self.FAILED, save)

    def set_failed_timeout_status(self, save=True):
        self.set_status(self.FAILED_TIMEOUT, save)

    def set_failed_doi_status(self, save=True):
        self.set_status(self.FAILED_DOI, save)

    def notify_status(self, **kwargs):
        user_id = self.uploaded_by.id
        room = f"{user_id}_paper_submissions"
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            room,
            {"type": "notify_paper_submission_status", "id": self.id, **kwargs},
        )
