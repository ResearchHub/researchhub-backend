from django.db import models
from user.models import Author


class Paper(models.Model):
    authors = models.ManyToManyField(Author, related_name='authored_papers')
