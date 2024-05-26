from django.db import models


class AuthorContributionSummary(models.Model):
    SOURCE_OPENALEX = "OPENALEX"
    SOURCE_RESEARCHHUB = "RESEARCHHUB"
    SOURCE_CHOICES = [
        (SOURCE_OPENALEX, "OpenAlex"),
        (SOURCE_RESEARCHHUB, "ResearchHub"),
    ]
    source = models.CharField(
        max_length=20, null=False, blank=False, choices=SOURCE_CHOICES
    )
    author = models.ForeignKey(
        "user.Author", on_delete=models.CASCADE, related_name="contribution_summaries"
    )
    works_count = models.IntegerField(null=False, blank=True, default=0)
    citation_count = models.IntegerField(null=False, blank=True, default=0)
    year = models.IntegerField(null=False, blank=False)

    class Meta:
        unique_together = ("source", "author", "year")
