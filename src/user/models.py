from django.db import models
from django.contrib.auth.models import AbstractUser

class User(AbstractUser):
    """
    User objects have the following fields by default:
        https://docs.djangoproject.com/en/2.2/ref/contrib/auth/#django.contrib.auth.models.User
    """

    def __str__(self):
        return self.email
