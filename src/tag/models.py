from django.db import models


class Tag(models.Model):
    """A secondary way to organize papers, posts
    and other entities
    """

    key = models.CharField(max_length=1024, unique=True)
    papers = models.ManyToManyField(
        'paper.Paper',
        related_name='tags',
        blank=True
    )
    created_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.key

    def save(self, *args, **kwargs):
        self.key = self.key.lower()
        return super(Tag, self).save(*args, **kwargs)
