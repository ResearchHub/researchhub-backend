from django.db import models
from rest_framework_api_key.models import AbstractAPIKey

from user.models import User


class UserApiToken(AbstractAPIKey):

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="api_keys")
