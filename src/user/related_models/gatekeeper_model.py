from django.db.models import CASCADE, CharField, EmailField, ForeignKey

from user.constants.gatekeeper_constants import GATE_KEEPER_TYPES
from utils.models import DefaultModel


class Gatekeeper(DefaultModel):
    type = CharField(
        blank=False,
        choices=GATE_KEEPER_TYPES,
        db_index=True,
        max_length=128,
        null=False,
    )
    user = ForeignKey(
        "user.User", on_delete=CASCADE, related_name="gatekeeper", null=True, blank=True
    )
    email = EmailField(
        blank=True,
        db_index=True,
        null=True,
    )

    def __str__(self):
        return f"{self.__class__}"
