from django.db import models


# Article processing charges (APC) for papers
class PaperAPC(models.Model):
    paper = models.ForeignKey("Paper", on_delete=models.CASCADE, related_name="apcs")
    amount = models.IntegerField(null=True, blank=True)
    currency = models.CharField(max_length=3, null=True, blank=True)
    paid = models.BooleanField(default=False)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)


class PaperAPCDeclaration(models.Model):
    ACCEPT_TERMS_AND_CONDITIONS = "ACCEPT_TERMS_AND_CONDITIONS"
    AUTHORIZE_CC_BY_4_0 = "AUTHORIZE_CC_BY_4_0"
    CONFIRM_AUTHORS_RIGHTS = "CONFIRM_AUTHORS_RIGHTS"
    CONFIRM_ORIGINALITY_AND_COMPLIANCE = "CONFIRM_ORIGINALITY_AND_COMPLIANCE"
    ACKNOWLEDGE_OPEN_PEER_REVIEWS = "ACKNOWLEDGE_OPEN_PEER_REVIEWS"

    DECLARATION_TYPE_CHOICES = [
        (ACCEPT_TERMS_AND_CONDITIONS, "Accept Terms and Conditions"),
        (AUTHORIZE_CC_BY_4_0, "Authorize CC BY 4.0"),
        (CONFIRM_AUTHORS_RIGHTS, "Confirm Authors Rights"),
        (CONFIRM_ORIGINALITY_AND_COMPLIANCE, "Confirm Originality and Compliance"),
        (ACKNOWLEDGE_OPEN_PEER_REVIEWS, "Acknowledge Open Peer Reviews"),
    ]

    paper_apc = models.ForeignKey(
        "PaperAPC", on_delete=models.CASCADE, related_name="declarations"
    )
    declaration_type = models.CharField(
        max_length=100,
        choices=DECLARATION_TYPE_CHOICES,
    )
    accepted = models.BooleanField(
        default=False, help_text="Indicates if the declaration has been accepted"
    )
    accepted_by = models.ForeignKey(
        "user.User",
        on_delete=models.CASCADE,
        null=True,
        related_name="paper_apc_declarations",
        help_text="User who accepted this declaration",
    )
    accepted_date = models.DateTimeField(
        null=True, blank=True, help_text="When the declaration was accepted"
    )
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ["paper_apc", "declaration_type", "accepted_by"]
        indexes = [
            models.Index(fields=["paper_apc", "declaration_type", "accepted_by"]),
        ]
