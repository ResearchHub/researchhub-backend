from django.db import models
from django.utils.translation import gettext_lazy as _
from user.related_models.user_model import User


class UserVerification(models.Model):
    """
    Model to store the KYC verification status of a user.
    Verification can be done manually or by an external service,
    currently with [Persona](https://withpersona.com/).
    """

    class Type(models.TextChoices):
        MANUAL = "MANUAL", _("Manual")
        PERSONA = "PERSONA", _("Persona")

    class Status(models.TextChoices):
        """
        Status of the user verification based on the inquiry
        status from Persona.

        Also see: https://docs.withpersona.com/docs/events#types-of-events
        """

        APPROVED = "APPROVED", _("Approved")
        DECLINED = "DECLINED", _("Declined")
        FAILED = "FAILED", _("Failed")
        PENDING = "PENDING", _("Pending")

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        null=False,
        blank=False,
        unique=True,
    )
    first_name = models.TextField()
    last_name = models.TextField()
    status = models.TextField(choices=Status.choices)
    verified_by = models.TextField(choices=Type.choices)
    external_id = models.TextField()
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    @property
    def is_verified(self) -> bool:
        return self.status == self.Status.APPROVED
