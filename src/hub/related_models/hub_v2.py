from django.db import models


class HubV2(models.Model):
    id = models.CharField(max_length=255, primary_key=True)
    display_name = models.CharField(max_length=255)
    description = models.TextField()
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
    is_removed = models.BooleanField(default=False)

    def __str__(self):
        return self.display_name
