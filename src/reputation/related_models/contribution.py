from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class Contribution(models.Model):
    # PAPER = 'PAPER'
    SUBMITTER = "SUBMITTER"
    UPVOTER = "UPVOTER"
    AUTHOR = "AUTHOR"
    CURATOR = "CURATOR"
    COMMENTER = "COMMENTER"
    SUPPORTER = "SUPPORTER"
    VIEWER = "VIEWER"
    PEER_REVIEWER = "PEER_REVIEWER"

    contribution_choices = [
        # (PAPER, PAPER),
        (AUTHOR, AUTHOR),
        (SUBMITTER, SUBMITTER),
        (UPVOTER, UPVOTER),
        (CURATOR, CURATOR),
        (COMMENTER, COMMENTER),
        (SUPPORTER, SUPPORTER),
        (VIEWER, VIEWER),
        (PEER_REVIEWER, PEER_REVIEWER),
    ]

    contribution_type = models.CharField(max_length=16, choices=contribution_choices)
    user = models.ForeignKey(
        "user.User", related_name="contributions", on_delete=models.SET_NULL, null=True
    )
    unified_document = models.ForeignKey(
        "researchhub_document.ResearchhubUnifiedDocument",
        related_name="contributions",
        on_delete=models.SET_NULL,
        null=True,
    )
    content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True)
    ordinal = models.PositiveIntegerField()
    object_id = models.PositiveIntegerField()
    item = GenericForeignKey(
        "content_type",
        "object_id",
    )

    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    def __str__(self):
        return "Contribution: {} - {}".format(self.id, self.contribution_type)
