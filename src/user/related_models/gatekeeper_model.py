from django.db.models import CharField, EmailField

from utils.models import DefaultModel

from user.constants.gatekeeper_constants import GATE_KEEPER_TYPES


class Gatekeeper(DefaultModel):
    type = CharField(
        blank=False,
        choices=GATE_KEEPER_TYPES,
        db_index=True,
        max_length=128,
        null=False,
    )
    email = EmailField(
        blank=False,
        db_index=True,
        null=False,
    )

    def __str__(self):
        return f'{self.__class__}'
