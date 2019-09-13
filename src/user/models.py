from django.db import models
from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """
    User objects have the following fields by default:
        https://docs.djangoproject.com/en/2.2/ref/contrib/auth/#django.contrib.auth.models.User
    """

    def __str__(self):
        return self.email


class University(models.Model):
    name = models.CharField(max_length=255)
    country = models.CharField(max_length=255)
    state = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=255)

    def __str__(self):
        return self.name


class Author(models.Model):
    user = models.OneToOneField(
        User,
        related_name='author_profile',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    first_name = models.CharField(max_length=30)
    last_name = models.CharField(max_length=30)
    university = models.ForeignKey(
        University,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    def __str__(self):
        university = self.university
        if university is None:
            university = ''
        return f'{self.first_name}_{self.last_name}_{university}'
