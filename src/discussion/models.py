from django.db import models

from paper.models import Paper


class Thread(models.Model):
    paper = models.ForeignKey(
        Paper,
        on_delete=models.SET_NULL,
        blank=True,
        null=True
    )
    title = models.CharField(max_length=255)


class Post(models.Model):
    parent = models.ForeignKey(
        Thread,
        on_delete=models.SET_NULL,
        blank=True,
        null=True
    )


class Reply(models.Model):
    parent = models.ForeignKey(
        Post,
        on_delete=models.SET_NULL,
        blank=True,
        null=True
    )
