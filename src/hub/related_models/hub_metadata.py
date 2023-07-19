from django.db import models
from django.db.models import JSONField

from .hub_provider import HubProvider
from .hub_v2 import HubV2


class HubMetadata(models.Model):
    hub = models.ForeignKey(HubV2, on_delete=models.CASCADE, related_name="metadata")
    hub_provider = models.ForeignKey(
        HubProvider, on_delete=models.CASCADE, related_name="hub_metadata"
    )
    raw_data = JSONField()

    def __str__(self):
        return (
            f"Metadata for {self.hub.display_name} "
            f"from {self.hub_provider.display_name}"
        )
