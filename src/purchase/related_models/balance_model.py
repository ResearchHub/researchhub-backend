from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class Balance(models.Model):

    @classmethod
    def create_locked_balance(
        cls, user, amount, lock_type="FUNDRAISE_CONTRIBUTION", source=None
    ):
        """Create a locked balance entry for the user"""
        from user.related_models.user_model import User

        # Use User model as default content_type if no source provided
        if source is None:
            content_type = ContentType.objects.get_for_model(User)
            object_id = user.pk
        else:
            content_type = ContentType.objects.get_for_model(source)
            object_id = source.pk

        return cls.objects.create(
            user=user,
            amount=str(amount),
            content_type=content_type,
            object_id=object_id,
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
