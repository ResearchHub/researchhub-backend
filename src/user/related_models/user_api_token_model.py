from django.db import models
from rest_framework_api_key.models import AbstractAPIKey


class UserApiToken(AbstractAPIKey):
    TEMPORARY_VERIFICATION_TOKEN = "TEMPORARY_VERIFICATION_TOKEN"

    user = models.ForeignKey(
        "user.User", on_delete=models.CASCADE, related_name="api_keys"
    )
