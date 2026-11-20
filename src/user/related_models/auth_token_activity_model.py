from django.db import models
from rest_framework.authtoken.models import Token


class AuthTokenActivity(models.Model):
    token = models.OneToOneField(
        Token,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="activity",
    )
    issued_at = models.DateTimeField()
    last_used_at = models.DateTimeField()
