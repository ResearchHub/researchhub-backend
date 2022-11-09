from django.db import models

from user.models import Author


class AuthorCitation(models.Model):
    author = models.ForeignKey(
        Author, related_name="citations", on_delete=models.CASCADE
    )
    citation_count = models.IntegerField(default=0)
    citation_name = models.CharField(max_length=256)
    cited_by_url = models.URLField(max_length=256, null=True)
    publish_year = models.CharField(max_length=4)
    title = models.CharField(max_length=256)
