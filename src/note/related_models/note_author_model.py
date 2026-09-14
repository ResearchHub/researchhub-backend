from django.db import models


class NoteAuthorManager(models.Manager):
    """Load author links with their author, so bylines cost a single query."""

    def get_queryset(self) -> "models.QuerySet[NoteAuthor]":
        """Return links with the credited author already loaded."""
        return super().get_queryset().select_related("author")


class NoteAuthor(models.Model):
    """An author credited on a note and the order they appear in."""

    note = models.ForeignKey(
        "note.Note",
        on_delete=models.CASCADE,
        related_name="author_links",
    )
    author = models.ForeignKey(
        "user.Author",
        on_delete=models.CASCADE,
    )
    position = models.IntegerField()

    objects = NoteAuthorManager()

    class Meta:
        ordering = ["position", "id"]
        unique_together = ("note", "author")
