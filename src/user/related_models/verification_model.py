from django.db import models

from user.related_models.user_model import User


class Verification(models.Model):
    user = models.ForeignKey(
        User,
        related_name='verification',
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    file = models.FileField(
        upload_to='uploads/verification/%Y/%m/%d',
        default=None,
        null=True,
        blank=True
    )

    def __str__(self):
        return 'User: {}'.format(self.user.email)
