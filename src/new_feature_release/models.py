from django.db import models
from user.models import User

class NewFeatureClick(models.Model):
    """A record of a new feature being clicked"""

    feature = models.CharField(max_length=64)
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='feature_clicks'
    )

    def __str__(self):
        return self.feature

    def __int__(self):
        return self.id