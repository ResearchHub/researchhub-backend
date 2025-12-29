from django.db import models

from utils.models import DefaultModel


class XPost(DefaultModel):
    """
    Model to store X (Twitter) posts that reference a paper.
    Used for tracking social media engagement metrics for papers.
    """

    paper = models.ForeignKey(
        "paper.Paper",
        on_delete=models.CASCADE,
        related_name="x_posts",
        help_text="The paper this X post references",
    )

    # X post identifiers
    post_id = models.CharField(
        max_length=64,
        db_index=True,
        help_text="The unique ID of the post on X",
    )
    author_id = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        db_index=True,
        help_text="The X user ID of the post author",
    )

    # Post content
    text = models.TextField(
        blank=True,
        default="",
        help_text="The text content of the post",
    )
    posted_date = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="When the post was created on X",
    )

    # Engagement metrics (updated periodically)
    like_count = models.PositiveIntegerField(default=0)
    repost_count = models.PositiveIntegerField(default=0)
    reply_count = models.PositiveIntegerField(default=0)
    quote_count = models.PositiveIntegerField(default=0)
    impression_count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["paper", "post_id"],
                name="unique_paper_x_post",
            ),
        ]
        indexes = [
            models.Index(fields=["paper", "-posted_date"]),
        ]
        ordering = ["-posted_date"]

    def __str__(self):
        return f"XPost {self.post_id} for Paper {self.paper_id}"

    @property
    def url(self) -> str:
        """Return the URL to view this post on X."""
        return f"https://x.com/i/web/status/{self.post_id}"

    @property
    def total_engagement(self) -> int:
        """Return total engagement (likes + reposts + replies + quotes)."""
        return self.like_count + self.repost_count + self.reply_count + self.quote_count
