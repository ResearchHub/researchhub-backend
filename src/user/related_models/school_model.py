from django.db import models


class University(models.Model):
    name = models.CharField(max_length=255)
    country = models.CharField(max_length=255)
    state = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=255)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.name}_{self.city}'

    class Meta:
        ordering = ['name']


class Major(models.Model):
    # FOD1P is a census id
    FOD1P = models.IntegerField()
    major = models.CharField(max_length=128)
    major_category = models.CharField(max_length=64)
