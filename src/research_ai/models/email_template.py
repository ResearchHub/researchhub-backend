from django.db import models

from utils.models import DefaultModel


class EmailTemplate(DefaultModel):
    """
    User-defined variable template for outreach emails ({{entity.field}} placeholders).
    """

    created_by = models.ForeignKey(
        "user.User",
        on_delete=models.CASCADE,
        related_name="created_research_ai_email_templates",
    )
    name = models.CharField(
        max_length=255,
        db_comment="User-defined template name.",
    )
    email_subject = models.TextField(
        blank=True,
        db_comment="Subject; may contain {{entity.field}}.",
    )
    email_body = models.TextField(
        blank=True,
        db_comment="Body; may contain {{entity.field}}.",
    )

    class Meta:
        db_table = "research_ai_email_template"
        ordering = ["-updated_date"]
        indexes = [
            models.Index(
                fields=["created_by"],
                name="research_ai_et_created_by",
            ),
        ]

    def __str__(self):
        return f"EmailTemplate {self.id} ({self.name})"
