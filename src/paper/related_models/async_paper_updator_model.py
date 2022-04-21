from django.db.models import (
    CASCADE,
    CharField,
    ForeignKey,
    ManyToManyField,
    OneToOneField,
)

from hub.models import Hub
from paper.related_models.paper_submission_model import PaperSubmission
from utils.models import DefaultModel


class AsyncPaperUpdator(DefaultModel):
    """
    This model is used during Paper async upload stage to allow
    users to add metadata in advance before BE paper extraction finishes.
    """

    created_by = ForeignKey("user.User", blank=False, null=False, on_delete=CASCADE)
    doi = CharField(
        blank=True,
        default=None,
        help_text="May be either extracted / user uploaded doi",
        max_length=255,
        null=True,
        unique=True,
    )
    hubs = ManyToManyField(Hub, blank=False)
    paper_submission = OneToOneField(
        PaperSubmission,
        blank=False,
        help_text="Self-explanatory",
        null=False,
        on_delete=CASCADE,
        related_name="async_upadtor",
    )
    title = CharField(max_length=1024, help_text="User generated title")
