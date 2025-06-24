from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class Balance(models.Model):

    @classmethod
    def create_locked_balance(
        cls, user, amount, lock_type="FUNDRAISE_CONTRIBUTION", source=None
    ):
        """Create a locked balance entry for the user"""
        return cls.objects.create(
            user=user,
            amount=str(amount),
            content_type=(
                None if source is None else ContentType.objects.get_for_model(source)
            ),
            object_id=None if source is None else source.pk,
            is_locked=True,
            lock_type=lock_type,
        )

    user = models.ForeignKey(
        "user.User", on_delete=models.CASCADE, related_name="balances"
    )
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField(null=True)
    source = GenericForeignKey("content_type", "object_id")

    # TODO: why is this a char field?
    amount = models.CharField(max_length=255)
    testnet_amount = models.CharField(max_length=255, default=0, null=True, blank=True)

    # Balance locking fields
    is_locked = models.BooleanField(default=False)
    lock_type = models.CharField(
        max_length=50,
        choices=[
            ("FUNDRAISE_CONTRIBUTION", "Fundraise Contribution"),
        ],
        null=True,
        blank=True,
    )

    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
