from django.db import models


class AuthorRSC(models.Model):
    author = models.ForeignKey(
        "user.Author",
        related_name="author_rsc",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
    )
    paper = models.ForeignKey(
        "paper.Paper",
        related_name="author_rsc",
        on_delete=models.CASCADE,
    )
    amount = models.DecimalField(default=0, decimal_places=10, max_digits=19)

    def __str__(self):
        return "{} {} - {} RSC".format(
            self.author.first_name, self.author.last_name, self.amount
        )
