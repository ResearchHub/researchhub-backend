from django.db import models


class CoAuthor(models.Model):
    author = models.ForeignKey(
        "user.Author", related_name="coauthors", on_delete=models.CASCADE
    )
    coauthor = models.ForeignKey(
        "user.Author", related_name="coauthored_with", on_delete=models.CASCADE
    )
    paper = models.ForeignKey(
        "paper.Paper", related_name="coauthorships", on_delete=models.CASCADE
    )

    class Meta:
        unique_together = ("author", "coauthor", "paper")
