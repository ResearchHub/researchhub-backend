from django.db import models
from django.utils import timezone
from utils.managers import SoftDeletableManager


class DefaultModel(models.Model):
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SoftDeletableModel(models.Model):
    """Adapted from https://github.com/jazzband/django-model-utils"""

    is_removed = models.BooleanField(default=False)
    is_removed_date = models.DateTimeField(default=None, null=True, blank=True)

    class Meta:
        abstract = True

    objects = SoftDeletableManager()
    all_objects = models.Manager()

    def delete(self, soft=True, *args, **kwargs):
        """Sets `is_removed` True when `soft` is True instead of deleting.

        Attributes:
            soft (bool) - Deletes the model if False. Defaults to True.
            *args
            **kwargs
        """
        if soft:
            self.is_removed = True
            self.is_removed_date = timezone.now()
            self.save(update_fields=['is_removed', 'is_removed_date'])
        else:
            return super().delete(*args, **kwargs)
