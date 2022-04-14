from django.db import models

from user.models import User, Organization
from utils.models import DefaultModel


class NoteTemplate(DefaultModel):
    created_by = models.ForeignKey(
        User,
        null=True,
        related_name='created_templates',
        on_delete=models.SET_NULL
    )
    is_default = models.BooleanField(
        default=False
    )
    name = models.CharField(
        default='Template',
        max_length=128,
    )
    organization = models.ForeignKey(
        Organization,
        null=True,
        related_name='created_templates',
        on_delete=models.SET_NULL
    )
    src = models.FileField(
        max_length=512,
        upload_to='note/template/uploads/%Y/%m/%d',
        default=None,
        null=True,
        blank=True
    )
    is_removed = models.BooleanField(
        default=False,
        db_index=True
    )
