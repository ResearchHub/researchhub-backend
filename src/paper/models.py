from django.db import models

from hub.models import Hub
from user.models import Author


class Paper(models.Model):
    title = models.CharField(max_length=255)
    uploaded_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
    paper_publish_date = models.DateField()
    authors = models.ManyToManyField(
        Author,
        related_name='authored_papers',
        blank=True
    )
    doi = models.CharField(max_length=255, default='', blank=True)
    hubs = models.ManyToManyField(
        Hub,
        related_name='papers',
        blank=True
    )
    url = models.URLField(default='', blank=True)
    # TODO: Determine file upload path
    # file = models.FileField(upload_to='uploads/papers/%Y/%m/%d')

    def __str__(self):
        authors = list(self.authors.all())
        return '%s: %s' % (self.title, authors)
