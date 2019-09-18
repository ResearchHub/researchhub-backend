from django.db import models


class Thread(models.Model):
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
