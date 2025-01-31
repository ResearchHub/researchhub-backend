from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models

from utils.models import DefaultModel


class Follow(DefaultModel):
    ALLOWED_FOLLOW_MODELS = ["hub", "paper", "user", "author"]

    user = models.ForeignKey(
        "user.User",
        on_delete=models.CASCADE,
        related_name="following",
    )
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        limit_choices_to={"model__in": ALLOWED_FOLLOW_MODELS},
    )
    object_id = models.PositiveIntegerField()
    followed_object = GenericForeignKey("content_type", "object_id")

    class Meta:
        unique_together = ("user", "content_type", "object_id")

    def clean(self):
        if self.content_type.model not in self.ALLOWED_FOLLOW_MODELS:
            raise ValidationError(f"Invalid follow model: {self.content_type.model}")
        super().clean()

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)
